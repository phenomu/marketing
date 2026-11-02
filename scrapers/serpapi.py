"""PAID technique (third-party): SerpAPI Google Maps engine.

GET https://serpapi.com/search.json?engine=google_maps&q=<query>&api_key=...
Free tier 250 searches/mo, then $25/1k (Starter) — see serpapi.com/pricing.
Returns `local_results` with title/address/phone/website/rating/reviews.

No key configured -> search() returns an empty result with `error` set,
never raises.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from config import settings

from .base import Business, SearchResult, SourceAdapter

log = logging.getLogger(__name__)

SEARCH_URL = "https://serpapi.com/search.json"
PAGE_SIZE = 20


def _parse_local_result(r: dict[str, Any]) -> Business:
    gps = r.get("gps_coordinates") or {}
    return Business(
        name=str(r.get("title") or ""),
        address=str(r.get("address") or ""),
        phone=str(r.get("phone") or ""),
        website=str(r.get("website") or ""),
        rating=r.get("rating") if isinstance(r.get("rating"), (int, float)) else None,
        review_count=r.get("reviews") if isinstance(r.get("reviews"), int) else None,
        category=str(r.get("type") or ""),
        place_id=str(r.get("place_id") or ""),
        source="serpapi",
        source_url=str(r.get("link") or ""),
        latitude=gps.get("latitude") if isinstance(gps.get("latitude"), (int, float)) else None,
        longitude=gps.get("longitude") if isinstance(gps.get("longitude"), (int, float)) else None,
    )


class SerpApiAdapter(SourceAdapter):
    """SerpAPI Google Maps source. Requires SERPAPI_KEY."""

    source_name = "serpapi"
    source_label = "SerpAPI Google Maps (third-party, paid)"
    requires_key = True

    def __init__(self, session: requests.Session | None = None, api_key: str | None = None):
        self._session = session or requests.Session()
        self._api_key = (api_key if api_key is not None else settings.serpapi_api_key).strip()

    def configured(self) -> bool:
        return bool(self._api_key)

    def key_hint(self) -> str:
        return "SERPAPI_KEY"

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
        start = 0
        while len(collected) < max_results:
            try:
                resp = self._session.get(
                    SEARCH_URL,
                    params={
                        "engine": "google_maps",
                        "q": full_query,
                        "type": "search",
                        "hl": settings.gmaps_hl,
                        "gl": settings.gmaps_gl,
                        "start": start,
                        "api_key": self._api_key,
                    },
                    timeout=settings.scrape_timeout_s,
                )
                if resp.status_code == 401:
                    error = "HTTP 401 — invalid SerpAPI key"
                    break
                if resp.status_code == 429:
                    error = "HTTP 429 — plan limit reached (250/mo free tier)"
                    break
                if resp.status_code != 200:
                    error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    break
                data = resp.json()
                results = data.get("local_results", [])
                if not results:
                    break
                for r in results:
                    biz = _parse_local_result(r)
                    if biz.name:
                        collected.append(biz)
                start += PAGE_SIZE
                serpapi_error = data.get("serpapi_pagination", {})
                if not data.get("serpapi_pagination"):
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
