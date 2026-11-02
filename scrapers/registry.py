"""Source registry: resolve adapter by name, default from settings.

`LEAD_SOURCE` env selects the default adapter. get_adapter() raises only
for a genuinely unknown name — a known adapter that is not configured
(e.g. no API key) still resolves, and callers surface `configured()`.
"""

from __future__ import annotations

from typing import Any

from config import get as env_get

from .base import SourceAdapter


def _iter_adapters() -> dict[str, type[SourceAdapter]]:
    # Local imports keep module import cheap and avoid cycles when an
    # adapter module grows heavier dependencies.
    from .file_import import CsvImportAdapter, JsonImportAdapter, XlsxImportAdapter
    from .gmaps_scrape import GmapsScraperAdapter
    from .google_places import GooglePlacesAdapter
    from .serpapi import SerpApiAdapter

    return {
        cls.source_name: cls
        for cls in (
            GmapsScraperAdapter,
            GooglePlacesAdapter,
            SerpApiAdapter,
            CsvImportAdapter,
            JsonImportAdapter,
            XlsxImportAdapter,
        )
    }


def default_source() -> str:
    return env_get("LEAD_SOURCE", "gmaps_scrape").strip().lower()


def list_sources() -> list[str]:
    return sorted(_iter_adapters())


def get_adapter(name: str | None = None, **kwargs: Any) -> SourceAdapter:
    """Instantiate an adapter by name. Empty name falls back to the
    LEAD_SOURCE setting. Unknown name raises ValueError with the
    available names listed."""
    resolved = (name or default_source()).strip().lower()
    adapters = _iter_adapters()
    if resolved not in adapters:
        raise ValueError(
            f"unknown source {resolved!r}; available: {', '.join(sorted(adapters))}"
        )
    return adapters[resolved](**kwargs)
