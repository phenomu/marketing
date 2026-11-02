"""Shared source adapter contract.

Every data source (Google Maps scrape, Google Places API, SerpAPI, file
importers) implements the same interface so the discovery pipeline is
source-agnostic. A `Business` is the smallest unit that flows through the
pipeline; PHASE 3 crawls `website` for contact extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

COUNTRY_DEFAULT = "ID"


@dataclass
class Business:
    """One business record discovered from a source. Source-agnostic shape."""

    name: str
    address: str = ""
    phone: str = ""
    website: str = ""
    rating: float | None = None
    review_count: int | None = None
    category: str = ""
    place_id: str = ""
    source: str = ""
    source_url: str = ""
    latitude: float | None = None
    longitude: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable dedup key: place_id when the source provides one, else
        a normalized (name + address) fallback."""
        if self.place_id:
            return f"place:{self.place_id}"
        norm = " ".join(f"{self.name} {self.address}".lower().split())
        return f"na:{norm}"

    @property
    def has_website(self) -> bool:
        return bool(self.website.strip())


@dataclass
class SearchResult:
    """Wrapper carrying results plus source metadata for job logging."""

    businesses: list[Business]
    source: str
    query: str
    location: str = ""
    total: int = 0
    quota_exhausted: bool = False
    error: str = ""

    def __post_init__(self) -> None:
        if not self.total:
            self.total = len(self.businesses)


class SourceAdapter(ABC):
    """Contract for every source adapter. Implementations must:

    - never raise for expected conditions (no key configured, quota spent,
      zero results) — return SearchResult with error set instead, so the
      worker loop logs and continues;
    - stay side-effect free beyond HTTP reads;
    - carry their `source_name` for registry + job logging.
    """

    #: short registry key, e.g. "gmaps_scrape", "google_places", "serpapi"
    source_name: str = ""

    #: human label for logs/dashboard
    source_label: str = ""

    #: true when the adapter needs a configured credential
    requires_key: bool = False

    @abstractmethod
    def search(self, query: str, location: str = "", **kwargs: Any) -> SearchResult:
        """Search businesses by keyword + optional location filter."""

    def configured(self) -> bool:
        """False when the adapter cannot run (missing key). Subclasses
        override only if they need more than key presence."""
        return True

    def key_hint(self) -> str:
        """Env var name a maintainer must set to enable this source."""
        return ""
