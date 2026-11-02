"""Crawl engine: one domain -> pages stored (PHASE 3).

Flow per job: robots.txt (cached) -> homepage -> contact-priority
link queue (bounded by CRAWL_MAX_PAGES) -> store text+footer per page.
Politeness: CRAWL_DELAY_S between requests, robots.txt honored, single
UA. Never raises — outcome lands in the job row.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from config import settings
from . import extract
from .fetch import fetch
from .robots import allowed

log = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    url: str
    kind: str = "other"  # home|contact|about|other
    http_status: int = 0
    fetched_ok: bool = False
    title: str = ""
    text: str = ""
    footer: str = ""
    mailtos: list[str] = field(default_factory=list)


@dataclass
class CrawlOutcome:
    domain: str
    pages: list[CrawledPage] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _kind_for(url: str, contact_links: list[str]) -> str:
    lower = url.lower()
    if url in contact_links:
        if any(w in lower for w in ("kontak", "contact", "hubungi", "whatsapp", "wa.me", "email")):
            return "contact"
        return "about"
    if any(w in lower for w in ("tentang", "about")):
        return "about"
    if any(w in lower for w in ("kontak", "contact", "hubungi")):
        return "contact"
    return "other"


def crawl_domain(
    domain: str,
    user_agent: str | None = None,
    max_pages: int | None = None,
    delay_s: float | None = None,
    timeout_s: int | None = None,
    retries: int | None = None,
    sleep=time.sleep,
    scheme: str = "https",
) -> CrawlOutcome:
    """Crawl one domain. config.settings defaults, all overridable (tests)."""
    user_agent = user_agent or settings.crawl_user_agent
    max_pages = max_pages if max_pages is not None else settings.crawl_max_pages
    delay_s = delay_s if delay_s is not None else settings.crawl_delay_s
    timeout_s = timeout_s if timeout_s is not None else settings.crawl_timeout_s
    retries = retries if retries is not None else settings.crawl_retries

    outcome = CrawlOutcome(domain=domain)
    # robots.txt is authoritative for the homepage too
    if not allowed(f"{scheme}://{domain}/", user_agent, timeout_s=timeout_s):
        outcome.error = "robots.txt disallows crawling"
        log.info("skip %s: robots.txt disallow", domain)
        return outcome

    queue: list[tuple[str, str]] = [(f"{scheme}://{domain}/", "home")]
    visited: set[str] = set()

    while queue and len(visited) < max_pages:
        url, kind = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not allowed(url, user_agent, timeout_s=timeout_s):
            log.info("skip %s: robots.txt disallow", url)
            continue
        if visited and delay_s:
            sleep(delay_s)

        result = fetch(
            url, user_agent, timeout_s=timeout_s, retries=retries, sleep=sleep
        )
        page = CrawledPage(
            url=url, kind=kind, http_status=result.status, fetched_ok=result.ok
        )
        if not result.ok:
            outcome.pages.append(page)
            if kind == "home":
                outcome.error = f"homepage fetch failed: {result.error}"
                return outcome
            continue

        page.title = extract.page_title(result.html)
        page.text = extract.page_text(result.html)
        page.footer = extract.footer_text(result.html)
        page.mailtos = extract.extract_mailtos(result.html)
        outcome.pages.append(page)

        if not result.html.strip():
            continue
        links = extract.parse_links(result.html, url)
        # contact links first, then the rest; keep queue bounded
        for link in links.contact_links:
            if link not in visited and (link, "contact") not in queue:
                queue.append((link, "contact"))
        for link in links.links:
            if link not in visited and (link, "other") not in queue:
                queue.append((link, "other"))
        # trim to a sane look-ahead
        queue = queue[: max_pages * 3]

    log.info(
        "crawled %s: %s page(s) OK (%s disallowed-skipped)",
        domain,
        sum(1 for p in outcome.pages if p.fetched_ok),
        len(visited) - sum(1 for p in outcome.pages if p.fetched_ok),
    )
    return outcome
