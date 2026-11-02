"""robots.txt handling for the crawler (PHASE 3).

RFC 9309 posture: robots.txt is fetched once per domain and cached in
process; fetch failure or 4xx means "no rules" (crawling allowed) but
the error is logged. 5xx/timeout is treated as "allow but log" as well
— the worker never blocks on robots problems (never-raise contract).
"""

from __future__ import annotations

import logging
import urllib.robotparser as robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

_ROBOTS_CACHE: dict[str, robotparser.RobotFileParser] = {}


def _robots_url(scheme: str, domain: str) -> str:
    return f"{scheme}://{domain}/robots.txt"


def fetch_robots(
    domain: str, user_agent: str, timeout_s: int = 10, scheme: str = "https"
) -> robotparser.RobotFileParser:
    """RobotFileParser for the domain (cached). Never raises: network
    problems or 5xx yield an allow-all parser with a warning log."""
    if domain in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[domain]

    parser = robotparser.RobotFileParser(_robots_url(scheme, domain))
    parser.parse([])  # default: empty rules = allow everything
    try:
        response = requests.get(
            _robots_url(scheme, domain),
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
        )
        if response.status_code >= 500:
            log.warning("robots.txt %s -> HTTP %s; assuming allow", domain, response.status_code)
        elif response.status_code >= 400:
            log.info("robots.txt %s -> HTTP %s (no rules); allow", domain, response.status_code)
        else:
            parser.parse(response.text.splitlines())
    except requests.RequestException as exc:
        log.warning("robots.txt %s unreachable (%s); assuming allow", domain, exc)

    _ROBOTS_CACHE[domain] = parser
    return parser


def allowed(url: str, user_agent: str, timeout_s: int = 10) -> bool:
    """True when robots.txt permits fetching `url` for our UA."""
    parts = urlsplit(url)
    if not parts.hostname:
        return False
    scheme = parts.scheme or "https"
    domain = parts.hostname
    parser = fetch_robots(domain, user_agent, timeout_s=timeout_s, scheme=scheme)
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001 — malformed rules never stop the worker
        return True


def clear_cache() -> None:
    """Test hook."""
    _ROBOTS_CACHE.clear()
