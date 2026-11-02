"""URL helpers: normalization + domain extraction for website dedup.

Sources return messy URLs (mixed case, missing scheme, tracking params,
www prefixes). Discovery stores the normalized form; PHASE 3 crawls by
domain so the same site is never fetched twice.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)

# Query params that identify a visitor/campaign, never the content.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "igshid", "ref", "ref_src"}
DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_website(raw: str) -> str:
    """Canonical form of a business website URL. Empty stays empty.

    - trims whitespace, drops surrounding junk (angled brackets, quotes)
    - adds https:// when the scheme is missing
    - lowercases scheme + host, drops default ports and leading www.
    - strips tracking query params, orders the rest
    - drops fragments
    Idempotent: normalize(normalize(x)) == normalize(x).
    """
    value = (raw or "").strip()
    if not value:
        return ""
    for junk in ("<", ">", '"', "'"):
        value = value.replace(junk, "")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value

    parts = urlsplit(value)
    scheme = parts.scheme.lower() or "https"
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    netloc = host
    if parts.port is not None and parts.port != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"

    path = parts.path.rstrip("/") or ""
    kept = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
        and not any(k.lower().startswith(p) for p in TRACKING_PREFIXES)
    )
    query = urlencode(kept)
    return urlunsplit((scheme, netloc, path, query, ""))


def extract_domain(raw: str) -> str:
    """Registrable-ish host of a URL (normalized, www stripped). May be
    empty when there is nothing usable — callers treat that as 'unknown'."""
    normalized = normalize_website(raw)
    if not normalized:
        return ""
    return urlsplit(normalized).hostname or ""
