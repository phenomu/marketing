"""PHASE 3 runner: crawl queue orchestration + worker/scheduler wiring.

scheduler tick: enqueue crawl jobs for business domains not yet queued
(honors industry rules only via businesses already stored; every domain
is a lead candidate). worker tick: claim pending crawl jobs and run
crawl_domain, storing pages + job outcome. Never raises into the
service loop (D-019 contract).
"""

from __future__ import annotations

import datetime as dt

import logging

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from app.crawler import crawl_domain
from app.db import CRAWL_JOBS, get_engine
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


def reset_failed_crawls(engine: Engine | None = None, stale_minutes: int = 30) -> int:
    """QA/retry pass (PHASE 8): requeue terminal-failed crawl jobs and
    stale `running` claims (worker crash mid-crawl) back to `pending`.
    Politeness: no fetching here — the normal crawl path (robots.txt
    check, per-domain delay) applies when the worker picks them up.
    Returns the number of jobs requeued. Never raises."""
    engine = engine or get_engine()
    cutoff = dt.datetime.utcnow() - dt.timedelta(minutes=stale_minutes)  # DB stores naive UTC
    requeued = 0
    try:
        with engine.begin() as conn:
            result = conn.execute(
                CRAWL_JOBS.update()
                .where(CRAWL_JOBS.c.status == "failed")
                .values(status="pending", error="")
            )
            requeued += result.rowcount or 0
        with engine.begin() as conn:
            stale = conn.execute(
                select(CRAWL_JOBS.c.id, CRAWL_JOBS.c.started_at).where(
                    CRAWL_JOBS.c.status == "running"
                )
            ).all()
            stale_ids = [
                row_id for row_id, started_at in stale
                if started_at is None or started_at < cutoff
            ]
            if stale_ids:
                result = conn.execute(
                    CRAWL_JOBS.update()
                    .where(CRAWL_JOBS.c.id.in_(stale_ids))
                    .values(status="pending", error="requeued: stale claim")
                )
                requeued += result.rowcount or 0
    except Exception as exc:  # noqa: BLE001 — never-raise
        log.warning("reset_failed_crawls failed: %s", exc)
    return requeued


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
