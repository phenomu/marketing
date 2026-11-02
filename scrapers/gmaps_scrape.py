"""FREE technique: scrape Google Maps search results via the internal
`tbm=map` JSON endpoint (no API key, no CAPTCHA bypass — plain GET with a
browser-like User-Agent, polite rate limiting).

Verified format (2026-11-01, reverse-engineered live):
    GET https://www.google.com/search?tbm=map&q=<query>&hl=en&gl=id
        &pb=!1s<query+with+plus>!7i<page-size>!8i<offset>!10b1
    Response: `)]}'\n`-prefixed JSON; records at data[0][1][N][14] for N >= 1:
    [11] name, [18] address, [7][0] website, [4][7] rating, [37][1] review
    count, [13][0] category, [10] hex feature id, [9][2..3] lat/lng,
    [178][0][3] normalized phone, [39] formatted address.

No cookies or JS execution needed. 20 records per page; `!8i<offset>`
paginates. Google may change this internal shape at any time — the parser
degrades to an empty result with `error` set instead of raising.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote_plus

import requests

from config import settings

from .base import Business, SearchResult, SourceAdapter

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.google.com/search"
PAGE_SIZE = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _as_str(v: Any) -> str:
    return v if isinstance(v, str) else ""


def _as_float(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse_record(rec: Any) -> Business | None:
    """Map one raw tbm=map record list to a Business. Returns None when the
    node is not shaped like a place record (schema drift guard)."""
    if not isinstance(rec, list) or len(rec) < 15 or not isinstance(rec[11], str):
        return None
    if not rec[11].strip():
        return None
    rating = _as_float(rec[4][7]) if isinstance(rec[4], list) and len(rec[4]) > 7 else None
    reviews = (
        rec[37][1] if isinstance(rec[37], list) and len(rec[37]) > 1 and isinstance(rec[37][1], int)
        else None
    )
    website = ""
    if isinstance(rec[7], list) and rec[7] and isinstance(rec[7][0], str):
        website = rec[7][0]
    phone = ""
    if len(rec) > 178 and isinstance(rec[178], list) and rec[178]:
        ph = rec[178][0]
        if isinstance(ph, list) and len(ph) > 3 and isinstance(ph[3], str):
            phone = ph[3].strip()
    lat = lng = None
    if isinstance(rec[9], list) and len(rec[9]) > 3:
        lat, lng = _as_float(rec[9][2]), _as_float(rec[9][3])
    return Business(
        name=rec[11].strip(),
        address=_as_str(rec[18]) or _as_str(rec[39]),
        phone=phone,
        website=website,
        rating=rating,
        review_count=reviews,
        category=_as_str(rec[13][0]) if isinstance(rec[13], list) and rec[13] else "",
        place_id=_as_str(rec[10]),
        source="gmaps_scrape",
        source_url=f"https://www.google.com/maps/place/?q=place_id:{_as_str(rec[10])}",
        latitude=lat,
        longitude=lng,
    )


def _parse_payload(body: str) -> list[Business]:
    """Parse the )]}'-prefixed JSON body into Business records."""
    if not body.startswith(")]}'"):
        return []
    data = json.loads(body[4:].lstrip())
    container = data[0][1] if isinstance(data, list) and data and isinstance(data[0], list) else None
    if not isinstance(container, list):
        return []
    out = []
    seen: set[str] = set()
    for entry in container:
        if not isinstance(entry, list) or len(entry) <= 14:
            continue
        biz = _parse_record(entry[14])
        if biz and biz.key not in seen:
            seen.add(biz.key)
            out.append(biz)
    return out


class GmapsScraperAdapter(SourceAdapter):
    """Free Google Maps source. Rate-limited, keyless, unofficial endpoint."""

    source_name = "gmaps_scrape"
    source_label = "Google Maps (scrape, free)"
    requires_key = False

    def __init__(self, session: requests.Session | None = None, delay_s: float | None = None):
        self._session = session or requests.Session()
        self._session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        )
        self._delay_s = settings.scrape_delay_s if delay_s is None else delay_s

    def search(self, query: str, location: str = "", **kwargs: Any) -> SearchResult:
        full_query = f"{query} {location}".strip()
        max_results = int(kwargs.get("max_results", settings.scrape_max_results))
        collected: list[Business] = []
        error = ""
        offset = 0
        while len(collected) < max_results:
            pb = f"!1s{quote_plus(full_query)}!7i{PAGE_SIZE}!8i{offset}!10b1"
            try:
                resp = self._session.get(
                    SEARCH_URL,
                    params={"tbm": "map", "q": full_query, "hl": settings.gmaps_hl, "gl": settings.gmaps_gl, "pb": pb},
                    timeout=settings.scrape_timeout_s,
                )
                if resp.status_code != 200:
                    error = f"HTTP {resp.status_code} from Google (endpoint blocked or changed?)"
                    break
                if not resp.text.startswith(")]}'"):
                    error = "unexpected response shape (not tbm=map JSON) — endpoint changed or rate limited"
                    break
                page = _parse_payload(resp.text)
                if not page:
                    break  # no more results
                collected.extend(page)
                offset += PAGE_SIZE
                if len(page) < PAGE_SIZE:
                    break
                time.sleep(self._delay_s)  # politeness between pages
            except requests.RequestException as exc:
                error = f"network error: {exc}"
                break
        collected = collected[:max_results]
        return SearchResult(
            businesses=collected,
            source=self.source_name,
            query=query,
            location=location,
            error=error,
        )
