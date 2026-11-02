"""PHASE 2 — business discovery: keywords.yaml -> discovery jobs -> businesses.

The scheduler enqueues one discovery job per (source, query, location)
combination from `config/keywords.yaml`; the worker claims pending jobs,
runs the source adapter, and upserts businesses (dedup by Business.key,
domain extraction for the PHASE 3 crawl queue).

All failure modes land in the job row (status=failed + error text) —
discovery never raises into the service loop (D-019 contract).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app import store
from app.db import get_engine, init_db
from scrapers import get_adapter, list_sources

log = logging.getLogger(__name__)

KEYWORDS_FILE = Path(__file__).resolve().parent.parent / "config" / "keywords.yaml"


def load_keyword_plan(path: Path = KEYWORDS_FILE) -> dict[str, Any]:
    """Parse keywords.yaml. Missing file -> empty plan (worker idles)."""
    if not path.is_file():
        log.warning("keyword plan not found: %s (no discovery jobs will be enqueued)", path)
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        log.warning("keyword plan %s is not a mapping; ignoring", path)
        return {}
    return data


def plan_to_searches(plan: dict[str, Any], default_source: str) -> list[dict[str, Any]]:
    """Expand the plan into concrete search dicts:
    {source, query, location, max_results}. Cross product of queries x
    locations, per-source overrides via `sources:` block."""
    queries = [str(q).strip() for q in plan.get("queries", []) if str(q).strip()]
    locations = [str(l).strip() for l in plan.get("locations", []) if str(l).strip()]
    max_results = int(plan.get("max_results", 20))

    searches: list[dict[str, Any]] = []
    sources_block = plan.get("sources", {}) or {}
    enabled = sources_block.get(default_source, True)  # default: the LEAD_SOURCE is enabled

    if enabled:
        for query in queries:
            for location in locations:
                searches.append(
                    {
                        "source": default_source,
                        "query": query,
                        "location": location,
                        "max_results": max_results,
                    }
                )

    # extra sources explicitly enabled in the plan (e.g. importers)
    for source_name, cfg in sources_block.items():
        if source_name == default_source:
            continue
        if cfg is False:
            continue
        cfg = cfg if isinstance(cfg, dict) else {}
        if source_name not in list_sources():
            log.warning("plan enables unknown source %r; skipping", source_name)
            continue
        src_queries = cfg.get("queries") or queries
        src_locations = cfg.get("locations") or locations
        src_max = int(cfg.get("max_results", max_results))
        for query in src_queries:
            for location in src_locations:
                searches.append(
                    {
                        "source": source_name,
                        "query": str(query),
                        "location": str(location),
                        "max_results": src_max,
                    }
                )
    return searches


def enqueue_from_plan(engine: Engine, default_source: str, plan: dict[str, Any]) -> int:
    """Queue discovery jobs for every search not already covered.
    A search is covered when its newest job row is pending, running, or
    done — only failed (or missing) searches (re)queue, so transient
    source errors retry on the next scheduler tick while completed ones
    stay stable. Returns the number of jobs newly queued."""
    queued = 0
    for search in plan_to_searches(plan, default_source):
        existing = store.last_job_per_search(
            engine, search["source"], search["query"], search["location"]
        )
        if existing is not None and existing.status in ("done", "running", "pending"):
            continue  # already covered — keep the plan idempotent
        store.insert_job(
            engine,
            source=search["source"],
            query=search["query"],
            location=search["location"],
            max_results=search["max_results"],
        )
        queued += 1
    return queued


def run_pending_jobs(engine: Engine | None = None, limit: int | None = None) -> dict[str, int]:
    """Worker entry point: claim and run pending discovery jobs until the
    queue drains (or `limit` jobs are processed). Returns counters."""
    engine = engine or get_engine()
    processed = new_total = updated_total = 0
    while limit is None or processed < limit:
        job = store.claim_next_pending(engine)
        if job is None:
            break
        processed += 1
        result = _run_single_job(engine, job)
        new_total += result["new"]
        updated_total += result["updated"]
    return {"jobs": processed, "new": new_total, "updated": updated_total}


def _run_single_job(engine: Engine, job: dict) -> dict[str, int]:
    job_id = job["id"]
    try:
        adapter = get_adapter(job["source"])
    except ValueError as exc:
        store.complete_job(engine, job_id, store.JOB_FAILED, error=f"unknown source: {exc}")
        return {"new": 0, "updated": 0}

    result = adapter.search(
        job["query"], location=job["location"], max_results=job["max_results"]
    )
    if result.error and not result.businesses:
        store.complete_job(
            engine, job_id, store.JOB_FAILED, found=len(result.businesses), error=result.error
        )
        return {"new": 0, "updated": 0}

    new_count, updated_count = store.upsert_businesses(engine, result.businesses)
    status = store.JOB_DONE if not result.error else store.JOB_FAILED
    store.complete_job(
        engine,
        job_id,
        status,
        found=len(result.businesses),
        new=new_count,
        updated=updated_count,
        error=result.error,
    )
    return {"new": new_count, "updated": updated_count}
