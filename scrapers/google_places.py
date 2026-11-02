"""PAID technique (official): Google Places API (New) Text Search.

POST https://places.googleapis.com/v1/places:searchText
Headers: X-Goog-Api-Key, X-Goog-FieldMask.
Billed per request (Text Search (New) Essentials SKU, ~$32/1k requests);
field mask is explicit so we never pay for fields we do not map.

No key configured -> search() returns an empty result with `error` set
("no API key configured"), never raises.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

import requests

from config import settings

from .base import Business, SearchResult, SourceAdapter

log = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Keep the mask minimal: only fields we actually map into Business.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.primaryTypeDisplayName",
        "places.location",
    ]
)

PAGE_SIZE = 20


def _txt(v: Any) -> str:
    if isinstance(v, dict) and isinstance(v.get("text"), str):
        return v["text"]
    return ""


def _parse_place(p: dict[str, Any]) -> Business:
    loc = p.get("location") or {}
    return Business(
        name=_txt(p.get("displayName")),
        address=str(p.get("formattedAddress") or ""),
        phone=str(p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber") or ""),
        website=str(p.get("websiteUri") or ""),
        rating=p.get("rating") if isinstance(p.get("rating"), (int, float)) else None,
        review_count=p.get("userRatingCount") if isinstance(p.get("userRatingCount"), int) else None,
        category=_txt(p.get("primaryTypeDisplayName")),
        place_id=str(p.get("id") or ""),
        source="google_places",
        source_url=f"https://www.google.com/maps/place/?q=place_id:{p.get('id', '')}",
        latitude=loc.get("latitude") if isinstance(loc.get("latitude"), (int, float)) else None,
        longitude=loc.get("longitude") if isinstance(loc.get("longitude"), (int, float)) else None,
    )


class GooglePlacesAdapter(SourceAdapter):
    """Official Places API (New) source. Requires GOOGLE_PLACES_API_KEY."""

    source_name = "google_places"
    source_label = "Google Places API (official, paid)"
    requires_key = True

    def __init__(self, session: requests.Session | None = None, api_key: str | None = None):
        self._session = session or requests.Session()
        self._api_key = (api_key if api_key is not None else settings.google_places_api_key).strip()

    def configured(self) -> bool:
        return bool(self._api_key)

    def key_hint(self) -> str:
        return "GOOGLE_PLACES_API_KEY"

    def search(self, query: str, location: str = "", **kwargs: Any) -> SearchResult:
        if not self._api_key:
            return SearchResult(
                businesses=[],
                source=self.source_name,
                query=query,
                location=location,
                error=f"no API key configured (set {self.key_hint()})",
            )
        full_query = f"{query} {location}".strip()
        max_results = int(kwargs.get("max_results", settings.scrape_max_results))
        collected: list[Business] = []
        error = ""
        page_token = ""
        while len(collected) < max_results:
            body: dict[str, Any] = {"textQuery": full_query, "pageSize": min(PAGE_SIZE, max_results - len(collected))}
            if page_token:
                body["pageToken"] = page_token
            try:
                resp = self._session.post(
                    SEARCH_URL,
                    json=body,
                    headers={
                        "X-Goog-Api-Key": self._api_key,
                        "X-Goog-FieldMask": FIELD_MASK,
                        "Content-Type": "application/json",
                    },
                    timeout=settings.scrape_timeout_s,
                )
                if resp.status_code == 403:
                    error = "HTTP 403 — key invalid or Places API not enabled"
                    break
                if resp.status_code == 429:
                    error = "HTTP 429 — quota exceeded"
                    break
                if resp.status_code != 200:
                    error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    break
                data = resp.json()
                for p in data.get("places", []):
                    biz = _parse_place(p)
                    if biz.name:
                        collected.append(biz)
                page_token = str(data.get("nextPageToken") or "")
                if not page_token:
                    break
            except requests.RequestException as exc:
                error = f"network error: {exc}"
                break
            except ValueError as exc:
                error = f"invalid JSON response: {exc}"
                break
        collected = collected[:max_results]
        return SearchResult(
            businesses=collected,
            source=self.source_name,
            query=query,
            location=location,
            error=error,
        )
