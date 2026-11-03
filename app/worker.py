"""Crawler worker — long-running process polling for crawl jobs.

Loop, heartbeat, DB connectivity, and graceful shutdown are real. As of
PHASE 2 the worker drains the discovery job queue (keywords.yaml ->
scheduler enqueues -> worker runs source adapters -> businesses upserted);
as of PHASE 3 it also drains the crawl queue (business domains -> worker
crawls websites -> pages + contact/about stored, bounded by
CRAWL_BATCH_LIMIT per tick).
"""

from __future__ import annotations

import logging
import time

from app.db import check_db, get_engine
from app.discovery import run_pending_jobs
from app.backfill import backfill_listing_phones
from app.crawl import run_pending_crawls
from app.extract import run_pending_extractions
from app.leads import build_leads
from app.validation import run_validation_batch
from app.outreach.campaign import run_campaigns, run_followups
from app.heartbeat import write_heartbeat
from config import settings
from config.logging_setup import setup_logging

log = logging.getLogger(__name__)


def run() -> None:
    setup_logging("worker")
    log.info("worker started (interval=%ss, env=%s)", settings.worker_interval_s, settings.app_env)
    try:
        while True:
            db_state = "up" if check_db() else "down"
            write_heartbeat("worker", db=db_state)
            if db_state == "down":
                log.warning("database unreachable; worker idles until it recovers")
            else:
                try:
                    stats = run_pending_jobs()
                    if stats["jobs"]:
                        log.info(
                            "discovery batch: %s jobs, %s new, %s updated",
                            stats["jobs"], stats["new"], stats["updated"],
                        )
                        # listing phones (businesses.phone from gmaps/serpapi)
                        # must reach the contacts table or leads never see
                        # them — promote + rebuild immediately
                        fill = backfill_listing_phones(get_engine())
                        if fill["inserted"]:
                            log.info(
                                "listing phones promoted: %s contact(s)",
                                fill["inserted"],
                            )
                        if fill["inserted"]:
                            lead_stats = build_leads(get_engine())
                            if lead_stats["new"] or lead_stats["updated"]:
                                log.info(
                                    "leads rebuilt: %s new, %s updated",
                                    lead_stats["new"], lead_stats["updated"],
                                )
                    # drain crawl jobs one domain at a time so the heartbeat
                    # stays fresh while long crawls run (compose healthcheck
                    # marks the worker unhealthy otherwise)
                    crawl_jobs = crawl_ok = 0
                    batch = {"jobs": 0, "ok": 0, "pending": 0}
                    for _ in range(settings.crawl_batch_limit):
                        write_heartbeat("worker", db=db_state)
                        batch = run_pending_crawls(limit=1)
                        crawl_jobs += batch["jobs"]
                        crawl_ok += batch["ok"]
                        if batch["jobs"] == 0:
                            break
                    if crawl_jobs:
                        log.info(
                            "crawl batch: %s job(s), %s ok, %s pending left",
                            crawl_jobs, crawl_ok, batch["pending"],
                        )
                    extract_stats = run_pending_extractions()
                    if extract_stats["jobs"]:
                        log.info(
                            "extraction batch: %s job(s), %s new, %s updated",
                            extract_stats["jobs"], extract_stats["new"],
                            extract_stats["updated"],
                        )
                    validation_stats = run_validation_batch(limit=settings.validate_batch_limit)
                    if validation_stats["emails"]:
                        log.info(
                            "validation batch: %s email(s) — %s valid, %s invalid, %s unknown",
                            validation_stats["emails"], validation_stats["valid"],
                            validation_stats["invalid"], validation_stats["unknown"],
                        )
                    if validation_stats["emails"] or extract_stats["jobs"]:
                        lead_stats = build_leads(get_engine())
                        if lead_stats["new"] or lead_stats["updated"]:
                            log.info(
                                "leads rebuilt: %s new, %s updated",
                                lead_stats["new"], lead_stats["updated"],
                            )
                    outreach_stats = run_campaigns(get_engine())
                    if outreach_stats["campaigns"]:
                        log.info("outreach batch: %s", outreach_stats)
                    followup_stats = run_followups(get_engine())
                    if followup_stats["checked"]:
                        log.info("followup batch: %s", followup_stats)
                except Exception as exc:  # noqa: BLE001 — service loop must survive
                    log.exception("worker batch failed: %s", exc)
            # Next up: PHASE 7 dashboard real (TRACKER.md).
            time.sleep(settings.worker_interval_s)
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    run()
