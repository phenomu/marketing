"""HTTP fetch for the crawler with retry, timeout, and size cap (PHASE 3).

Never raises for expected conditions — returns FetchResult with ok/error
so the engine can record failures per URL and move on (never-raise).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024  # 2 MB body cap
RETRY_STATUS = {429, 500, 502, 503, 504}


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
    Body capped at MAX_BYTES."""
    getter = (session or requests).get
    result = FetchResult(url=url)
    for attempt in range(retries + 1):
        if attempt and delay:
            sleep(delay * (2 ** (attempt - 1)))
        try:
            response = getter(
                url,
                headers={"User-Agent": user_agent, "Accept-Language": "id,en;q=0.8"},
                timeout=timeout_s,
                stream=True,
                allow_redirects=True,
            )
            body = b""
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body += chunk
                if len(body) >= MAX_BYTES:
                    log.info("body cap reached for %s", url)
                    break
            response.close()
            result.status = response.status_code
            if 200 <= response.status_code < 300:
                result.ok = True
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
