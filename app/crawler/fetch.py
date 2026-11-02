"""HTTP fetch for the crawler with retry, timeout, and size cap (PHASE 3).

SSRF-hardened: the target host (and every redirect hop) must resolve to a
public IP — crawl targets come from external business listings, so a
hostile listing can plant internal addresses (cloud metadata, docker
network) as its "website".

Never raises for expected conditions — returns FetchResult with ok/error
so the engine can record failures per URL and move on (never-raise).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests

from app.urls import is_public_host

log = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024  # 2 MB body cap
RETRY_STATUS = {429, 500, 502, 503, 504}
REDIRECT_STATUS = {301, 302, 303, 307, 308}
MAX_HOPS = 5


@dataclass
class FetchResult:
    url: str
    ok: bool = False
    status: int = 0
    html: str = ""
    error: str = ""

    @property
    def retryable(self) -> bool:
        return self.status in RETRY_STATUS or bool(self.error)


def _target_allowed(url: str) -> bool:
    """http(s) URL whose host resolves public — the SSRF gate."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    return is_public_host(parts.hostname)


def _read_body(response) -> bytes:
    body = b""
    for chunk in response.iter_content(chunk_size=64 * 1024):
        body += chunk
        if len(body) >= MAX_BYTES:
            log.info("body cap reached")
            break
    return body


def _get(getter, url: str, user_agent: str, timeout_s: int):
    return getter(
        url,
        headers={"User-Agent": user_agent, "Accept-Language": "id,en;q=0.8"},
        timeout=timeout_s,
        stream=True,
        allow_redirects=False,
    )


def fetch(
    url: str,
    user_agent: str,
    timeout_s: int = 15,
    retries: int = 2,
    delay: float = 0.0,
    sleep=time.sleep,
    session: requests.Session | None = None,
) -> FetchResult:
    """GET `url` with `retries` attempts (backoff 2^attempt * delay).
    4xx (except 429) is final; network errors and 5xx/429 are retried.
    Redirects are followed manually (max MAX_HOPS); every hop must pass
    the public-host check. Body capped at MAX_BYTES."""
    getter = (session or requests).get
    result = FetchResult(url=url)

    if not _target_allowed(url):
        result.error = "blocked: non-public or invalid target (SSRF guard)"
        log.warning("fetch blocked by SSRF guard: %s", url)
        return result

    current = url
    for attempt in range(retries + 1):
        if attempt and delay:
            sleep(delay * (2 ** (attempt - 1)))
        try:
            response = _get(getter, current, user_agent, timeout_s)
            # follow redirects manually — each hop re-validated
            hops = 0
            while response.status_code in REDIRECT_STATUS:
                if hops >= MAX_HOPS:
                    result.status = response.status_code
                    result.error = "too many redirects"
                    response.close()
                    return result
                location = (getattr(response, "headers", None) or {}).get("Location", "")
                status = response.status_code
                response.close()
                if not location:
                    result.status = status
                    result.error = "redirect without Location"
                    return result
                nxt = urljoin(current, location)
                if not _target_allowed(nxt):
                    result.status = status
                    result.error = f"blocked redirect to non-public target: {location[:120]}"
                    log.warning(
                        "redirect blocked by SSRF guard: %s -> %s", current, location[:120]
                    )
                    return result
                current = nxt
                hops += 1
                response = _get(getter, current, user_agent, timeout_s)
            body = _read_body(response)
            result.status = response.status_code
            if 200 <= response.status_code < 300:
                result.ok = True
                result.url = current
                result.html = body.decode(response.encoding or "utf-8", errors="replace")
                return result
            result.error = f"HTTP {response.status_code}"
            if response.status_code not in RETRY_STATUS:
                return result  # 4xx: final, no retry
        except requests.RequestException as exc:
            result.error = f"{type(exc).__name__}: {exc}"

    if not result.ok:
        log.info("fetch failed after %s attempt(s): %s (%s)", retries + 1, url, result.error)
    return result
