"""Adapter tests: parser (offline fixture), registry, keyless behavior.

The gmaps parser fixture mirrors the real tbm=map record shape (live
capture, 2026-11-01); adapters without keys return SearchResult.error
instead of raising.
"""

from __future__ import annotations

import json

import pytest

from scrapers import Business, get_adapter, list_sources
from scrapers.gmaps_scrape import _parse_payload, _parse_record


def make_record() -> list:
    """Build one record list with the field slots the parser reads."""
    rec: list = [None] * 179
    rec[1] = "ftznauysDueM4-EP0_qSCQ"
    rec[2] = "2ahUKEwj_token"
    rec[3] = ["Jl. Lengkong Besar No.117", "Cikawao"]
    rec[4] = [None, None, None, None, None, None, None, 4.9, 123]
    rec[7] = ["https://www.example.com/location", "example.com"]
    rec[9] = [-6.9286075, 107.61325509999999, -6.9286075, 107.61325509999999]
    rec[10] = "0x2e68e90075334c65:0xfcb1e02e015819d"
    rec[11] = "Apotek K-24 Lengkong Besar Bandung"
    rec[13] = ["Apotek"]
    rec[14] = "rec-wrapper"
    rec[37] = [None, 70]
    rec[39] = "Jl. Lengkong Besar No.117, Cikawao, Kota Bandung, Jawa Barat 40261"
    rec[178] = [
        ["0877-2286-7123", [None, "0877-2286-7123"], [None, "+62 877-2286-7123"], "087722867123"]
    ]
    return rec


RECORD = make_record()


class TestParseRecord:
    def test_full_record_maps_all_fields(self):
        biz = _parse_record(RECORD)
        assert biz is not None
        assert biz.name == "Apotek K-24 Lengkong Besar Bandung"
        assert biz.phone == "087722867123"
        assert biz.website == "https://www.example.com/location"
        assert biz.rating == 4.9
        assert biz.review_count == 70
        assert biz.category == "Apotek"
        assert biz.place_id == "0x2e68e90075334c65:0xfcb1e02e015819d"
        assert biz.latitude == -6.9286075
        assert biz.longitude == 107.61325509999999
        assert biz.source == "gmaps_scrape"

    def test_short_record_returns_none(self):
        assert _parse_record([None, "x"]) is None
        assert _parse_record(None) is None
        assert _parse_record("nope") is None

    def test_record_without_name_returns_none(self):
        no_name = list(RECORD)
        no_name[11] = "   "
        assert _parse_record(no_name) is None


class TestParsePayload:
    def test_parses_container_entries_and_dedups(self):
        entry = [None] * 15
        entry[14] = RECORD
        # one page: data[0][1] holds entries; duplicate entry must dedup
        body = ")]}'\n" + json.dumps([[["q"], [None, entry, entry]]] + [None] * 71)
        out = _parse_payload(body)
        assert len(out) == 1
        assert out[0].name == "Apotek K-24 Lengkong Besar Bandung"

    def test_non_json_body_returns_empty(self):
        assert _parse_payload("<html>blocked</html>") == []
        assert _parse_payload("") == []


class TestBusiness:
    def test_key_uses_place_id_when_present(self):
        b = Business(name="x", place_id="0x1:0x2")
        assert b.key == "place:0x1:0x2"

    def test_key_falls_back_to_normalized_name_address(self):
        b = Business(name="  Kedai   Kopi ", address="Jl. A")
        assert b.key == "na:kedai kopi jl. a"

    def test_has_website(self):
        assert Business(name="x", website="https://a.com").has_website
        assert not Business(name="x", website="  ").has_website


class TestRegistry:
    def test_lists_all_six_sources(self):
        assert set(list_sources()) == {
            "gmaps_scrape",
            "google_places",
            "serpapi",
            "csv_import",
            "json_import",
            "xlsx_import",
        }

    def test_default_source_from_env(self, monkeypatch):
        monkeypatch.setenv("LEAD_SOURCE", "serpapi")
        assert get_adapter().source_name == "serpapi"

    def test_unknown_source_raises_with_names(self):
        with pytest.raises(ValueError, match="gmaps_scrape"):
            get_adapter("nope")


class TestKeylessAdapters:
    def test_places_without_key_reports_error(self):
        result = get_adapter("google_places").search("klinik")
        assert result.businesses == []
        assert "GOOGLE_PLACES_API_KEY" in result.error

    def test_serpapi_without_key_reports_error(self):
        result = get_adapter("serpapi").search("klinik")
        assert result.businesses == []
        assert "SERPAPI_KEY" in result.error
