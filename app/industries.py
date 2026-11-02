"""Industry filtering rules — user-editable config, no code change needed.

`config/industries.yaml` holds include/exclude keyword lists. A business
matches when its category OR name contains an include keyword and no
exclude keyword (case-insensitive substring). Matching only TAGS the
row (`industry_match`); nothing is dropped — filtering happens at
export/lead-management time (PHASE 5), so widening the list later
recovers businesses already stored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

INDUSTRIES_FILE = Path(__file__).resolve().parent.parent / "config" / "industries.yaml"


@dataclass(frozen=True)
class IndustryRules:
    include: tuple[str, ...] = field(default_factory=tuple)
    exclude: tuple[str, ...] = field(default_factory=tuple)

    @property
    def enabled(self) -> bool:
        return bool(self.include)


def load_industry_rules(path: Path = INDUSTRIES_FILE) -> IndustryRules:
    """Parse the rules file. Missing/empty file -> disabled (match=False
    for everything, one warning) — never blocks the pipeline."""
    if not path.is_file():
        log.warning("industry rules not found: %s (no industry tagging)", path)
        return IndustryRules()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        log.warning("industry rules %s unreadable (%s); no tagging", path, exc)
        return IndustryRules()
    if not isinstance(data, dict):
        log.warning("industry rules %s is not a mapping; no tagging", path)
        return IndustryRules()

    include = tuple(
        str(k).strip().lower() for k in (data.get("include") or []) if str(k).strip()
    )
    exclude = tuple(
        str(k).strip().lower() for k in (data.get("exclude") or []) if str(k).strip()
    )
    rules = IndustryRules(include=include, exclude=exclude)
    log.info(
        "industry rules loaded: %s include / %s exclude keyword(s)",
        len(include), len(exclude),
    )
    return rules


def matches_industry(
    rules: IndustryRules, category: str, name: str = ""
) -> bool:
    """True when the business matches the include/exclude rules."""
    if not rules.enabled:
        return False
    haystack = f"{category or ''} {name or ''}".lower()
    if any(word in haystack for word in rules.exclude):
        return False
    return any(word in haystack for word in rules.include)
