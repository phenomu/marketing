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

from app.db import check_db
from app.discovery import run_pending_jobs
from app.crawl import enqueue_crawls, run_pending_crawls
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
                except Exception as exc:  # noqa: BLE001 — service loop must survive
                    log.exception("worker batch failed: %s", exc)
            # (PHASE 4+: email extraction runs on stored page text)
            time.sleep(settings.worker_interval_s)
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    run()
