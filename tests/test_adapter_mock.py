"""Mocked-HTTP adapter tests: full search() flows without network.

FakeSession records calls and returns canned payloads shaped like the real
APIs (Places API (New) JSON, SerpAPI local_results, tbm=map payloads), so
pagination, field mapping, and error surfacing are covered offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scrapers.gmaps_scrape import GmapsScraperAdapter
from scrapers.google_places import GooglePlacesAdapter
from scrapers.serpapi import SerpApiAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for test_scrapers import
from test_scrapers import make_record  # noqa: E402


class _FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else json.dumps(payload or {})

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class _FakeSession:
    """Minimal requests.Session stand-in: records calls, pops responses."""

    def __init__(self, responses: list[_FakeResp]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict | None]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, params: dict | None = None, timeout=None, **kw):
        self.calls.append(("GET", url, params))
        return self._responses.pop(0)

    def post(self, url: str, json=None, headers=None, timeout=None, **kw):
        self.calls.append(("POST", url, json))
        return self._responses.pop(0)


class TestGooglePlacesMocked:
    def _place(self, name: str) -> dict:
        return {
            "id": "gp_" + name.lower().replace(" ", ""),
            "displayName": {"text": name},
            "formattedAddress": "Jl. Test No.1",
            "nationalPhoneNumber": "0812-345-6789",
            "websiteUri": "https://" + name.lower().replace(" ", "") + ".test",
            "rating": 4.7,
            "userRatingCount": 88,
            "primaryTypeDisplayName": {"text": "Cafe"},
            "location": {"latitude": -6.9, "longitude": 107.6},
        }

    def test_success_with_pagination(self):
        responses = [
            _FakeResp(payload={"places": [self._place("Kopi A")], "nextPageToken": "tok1"}),
            _FakeResp(payload={"places": [self._place("Kopi B")]}),
        ]
        session = _FakeSession(responses)
        adapter = GooglePlacesAdapter(session=session, api_key="test-key")
        result = adapter.search("kopi", location="Bandung", max_results=20)
        assert result.error == ""
        assert [b.name for b in result.businesses] == ["Kopi A", "Kopi B"]
        b = result.businesses[0]
        assert b.place_id == "gp_kopia"
        assert b.phone == "0812-345-6789"
        assert b.rating == 4.7 and b.review_count == 88
        assert b.category == "Cafe"
        assert b.latitude == -6.9 and b.longitude == 107.6
        # two POSTs (pagination), field mask header sent
        assert len(session.calls) == 2
        assert session.calls[0][0] == "POST"

    def test_403_surfaces_key_error(self):
        session = _FakeSession([_FakeResp(status_code=403)])
        adapter = GooglePlacesAdapter(session=session, api_key="bad")
        result = adapter.search("kopi")
        assert result.businesses == []
        assert "403" in result.error and "key invalid" in result.error

    def test_429_surfaces_quota_error(self):
        session = _FakeSession([_FakeResp(status_code=429)])
        adapter = GooglePlacesAdapter(session=session, api_key="k")
        result = adapter.search("kopi")
        assert "429" in result.error and "quota" in result.error


class TestSerpApiMocked:
    def _local(self, name: str) -> dict:
        return {
            "title": name,
            "address": "Jl. Serp No.2",
            "phone": "+62 811-2233",
            "website": "https://" + name.lower().replace(" ", "") + ".id",
            "rating": 4.5,
            "reviews": 42,
            "type": "Restaurant",
            "place_id": "serp_" + name.lower().replace(" ", ""),
            "gps_coordinates": {"latitude": -7.0, "longitude": 110.0},
        }

    def test_success_with_pagination(self):
        responses = [
            _FakeResp(
                payload={
                    "local_results": [self._local("Sate A")],
                    "serpapi_pagination": {"next": "x"},
                }
            ),
            _FakeResp(payload={"local_results": [self._local("Sate B")]}),
        ]
        session = _FakeSession(responses)
        adapter = SerpApiAdapter(session=session, api_key="test-key")
        result = adapter.search("sate", location="Solo")
        assert result.error == ""
        assert [b.name for b in result.businesses] == ["Sate A", "Sate B"]
        b = result.businesses[0]
        assert b.category == "Restaurant"
        assert b.review_count == 42
        assert b.latitude == -7.0 and b.longitude == 110.0
        # second GET used start=20 offset
        assert session.calls[1][2]["start"] == 20

    def test_401_invalid_key(self):
        session = _FakeSession([_FakeResp(status_code=401)])
        result = SerpApiAdapter(session=session, api_key="bad").search("x")
        assert "401" in result.error and "invalid" in result.error

    def test_429_plan_limit(self):
        session = _FakeSession([_FakeResp(status_code=429)])
        result = SerpApiAdapter(session=session, api_key="k").search("x")
        assert "429" in result.error and "limit" in result.error


class TestGmapsScrapeMocked:
    def _payload(self, records: list) -> str:
        entries = []
        for rec in records:
            entry = [None] * 15
            entry[14] = rec
            entries.append(entry)
        return ")]}'\n" + json.dumps([[["q"], [None, *entries]]] + [None] * 71)

    def test_search_paginates_and_stops_on_short_page(self):
        rec1, rec2 = make_record(), make_record()
        rec2[11] = "Kedai Dua"
        rec2[10] = "0xdeadbeef:0x1"  # distinct place_id so dedup keeps both
        session = _FakeSession(
            [
                _FakeResp(text=self._payload([rec1, rec2])),  # full page signals next
                _FakeResp(text=self._payload([make_record()[:15]])),  # short page
            ]
        )
        # first response only yields 2 records (fewer than PAGE_SIZE stops loop)
        adapter = GmapsScraperAdapter(session=session, delay_s=0)
        result = adapter.search("kopi", location="Bandung", max_results=5)
        assert result.error == ""
        assert len(result.businesses) == 2
        assert result.businesses[0].name == "Apotek K-24 Lengkong Besar Bandung"
        assert result.businesses[1].name == "Kedai Dua"
        # offset of the (never-reached) next page would be 20
        assert session.calls[0][2]["pb"].startswith("!1skopi+Bandung!7i20!8i0")

    def test_non_json_response_sets_error(self):
        session = _FakeSession([_FakeResp(text="<html>blocked</html>")])
        adapter = GmapsScraperAdapter(session=session, delay_s=0)
        result = adapter.search("kopi")
        assert result.businesses == []
        assert "unexpected response shape" in result.error

    def test_http_error_sets_error(self):
        session = _FakeSession([_FakeResp(status_code=429)])
        adapter = GmapsScraperAdapter(session=session, delay_s=0)
        result = adapter.search("kopi")
        assert result.businesses == []
        assert "HTTP 429" in result.error
