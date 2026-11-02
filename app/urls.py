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


# Big platforms that show up as business "websites" but are social/media
# profiles, not a crawlable business site (no contact page to mine).
PLATFORM_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "youtube.com", "linkedin.com", "whatsapp.com", "api.whatsapp.com",
    "wa.me", "tokopedia.com", "shopee.co.id", "gofood.com", "gojek.com",
    "grab.com", "google.com", "maps.google.com", "goo.gl", "linktr.ee",
    "bit.ly", "t.me", "telegram.me",
}


def is_platform(domain: str) -> bool:
    """True when the domain is a social/marketplace platform profile
    rather than the business's own site."""
    d = (domain or "").lower().lstrip(".")
    return d in PLATFORM_DOMAINS or d.endswith(".wa.me") or d.endswith(".linktr.ee")


# --- SSRF guard -------------------------------------------------------------
# Crawl domains originate from EXTERNAL source data (business listings):
# a hostile listing can plant an internal address as its "website". Every
# outbound request must re-validate the target before connecting.

import ipaddress
import socket


def _ip_is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for loopback/private/link-local/reserved ranges — never a valid
    crawl target. Covers the cloud-metadata link-local 169.254.169.254."""
    return (
        ip.is_private       # covers 10/8, 172.16/12, 192.194/16, fc00::/7
        or ip.is_loopback
        or ip.is_link_local # covers 169.254.169.254 (cloud metadata)
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_public_host(host: str, _resolver=socket.getaddrinfo) -> bool:
    """True when host resolves (or literally is) only to public IPs and uses
    an http(s) scheme. Host strings may carry a scheme prefix (cleaned).
    Never raises — unresolvable/invalid hosts are not public."""
    if not host:
        return False
    candidate = host.strip().lower()
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # strip userinfo; keep bare host (port already dropped by extract_domain,
    # CLI input may carry one)
    candidate = candidate.rpartition("@")[2].split(":", 1)[0].rstrip("].")
    if not candidate or "[" in candidate:
        return False
    try:
        addr = ipaddress.ip_address(candidate)  # IP literal
        return not _ip_is_private(addr)
    except ValueError:
        pass
    if not candidate.replace(".", "").replace("-", "").isalnum():
        return False  # hostname with odd characters — reject
    try:
        infos = _resolver(candidate, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, ValueError):
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        if ip_str.startswith("::ffff:"):
            ip_str = ip_str[7:].strip("[]")
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if _ip_is_private(addr):
            return False
    return True
