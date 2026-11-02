"""Website crawler (PHASE 3): robots.txt-aware, polite, bounded."""

from .engine import CrawlOutcome, CrawledPage, crawl_domain
from .extract import (
    CONTACT_WORDS,
    footer_text,
    extract_mailtos,
    page_text,
    page_title,
    parse_links,
)
from .fetch import FetchResult, fetch
from .robots import allowed, clear_cache, fetch_robots

__all__ = [
    "CrawlOutcome",
    "CrawledPage",
    "crawl_domain",
    "CONTACT_WORDS",
    "footer_text",
    "extract_mailtos",
    "page_text",
    "page_title",
    "parse_links",
    "FetchResult",
    "fetch",
    "allowed",
    "clear_cache",
    "fetch_robots",
]
