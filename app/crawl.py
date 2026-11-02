"""PHASE 3 runner: crawl queue orchestration + worker/scheduler wiring.

scheduler tick: enqueue crawl jobs for business domains not yet queued
(honors industry rules only via businesses already stored; every domain
is a lead candidate). worker tick: claim pending crawl jobs and run
crawl_domain, storing pages + job outcome. Never raises into the
service loop (D-019 contract).
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Engine

from app.crawler import crawl_domain
from app.db import get_engine
from app.industries import load_industry_rules
from app.store import (
    claim_next_crawl,
    complete_crawl_job,
    count_crawl_jobs,
    enqueue_crawl_domains,
    save_crawl_pages,
)

log = logging.getLogger(__name__)


def enqueue_crawls(engine: Engine | None = None) -> int:
    """Scheduler entry point: queue crawl jobs for new domains, filtered by
    config/industries.yaml when it defines include keywords (edit the file
    — the next scheduler tick picks up the change without restart)."""
    engine = engine or get_engine()
    rules = load_industry_rules()
    queued = enqueue_crawl_domains(engine, industry_rules=rules)
    if queued:
        log.info("queued %s crawl job(s) from business domains", queued)
    return queued


def run_pending_crawls(engine: Engine | None = None, limit: int | None = None) -> dict:
    """Worker entry point: drain pending crawl jobs (optionally bounded).
    Returns counters. Failures land in the job row, never raise."""
    engine = engine or get_engine()
    processed = ok = 0
    while limit is None or processed < limit:
        job = claim_next_crawl(engine)
        if job is None:
            break
        processed += 1
        try:
            outcome = crawl_domain(job["domain"])
        except Exception as exc:  # noqa: BLE001 — never-raise into the loop
            log.exception("crawl crashed for %s: %s", job["domain"], exc)
            complete_crawl_job(engine, job["id"], "failed", error=f"{type(exc).__name__}: {exc}")
            continue
        pages_ok = sum(1 for p in outcome.pages if p.fetched_ok)
        save_crawl_pages(engine, job["id"], outcome.pages)
        if outcome.error and pages_ok == 0:
            complete_crawl_job(
                engine, job["id"], "failed", pages_crawled=pages_ok, error=outcome.error
            )
        else:
            complete_crawl_job(
                engine,
                job["id"],
                "done",
                pages_crawled=pages_ok,
                outcome=outcome,
                error=outcome.error,
            )
            ok += 1
    return {"jobs": processed, "ok": ok, "pending": count_crawl_jobs(engine, "pending")}
