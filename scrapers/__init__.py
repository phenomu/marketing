"""Source adapters for business discovery. Pick via LEAD_SOURCE env.

    from scrapers import get_adapter, list_sources
    adapter = get_adapter()          # LEAD_SOURCE default: gmaps_scrape
    result = adapter.search("kedai kopi", location="Bandung")
    result.businesses, result.error
"""

from .base import Business, SearchResult, SourceAdapter
from .registry import default_source, get_adapter, list_sources

__all__ = [
    "Business",
    "SearchResult",
    "SourceAdapter",
    "get_adapter",
    "list_sources",
    "default_source",
]
