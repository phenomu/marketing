"""Crawler worker — long-running process polling for crawl jobs.

Loop, heartbeat, DB connectivity, and graceful shutdown are real. As of
PHASE 2 the worker drains the discovery job queue (keywords.yaml ->
scheduler enqueues -> worker runs source adapters -> businesses upserted).
Website crawling jobs land with PHASE 3.
"""

from __future__ import annotations

import logging
import time

from app.db import check_db
from app.discovery import run_pending_jobs
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
                except Exception as exc:  # noqa: BLE001 — service loop must survive
                    log.exception("discovery batch failed: %s", exc)
            # TODO(PHASE 3): poll the crawl job table and process pending jobs.
            time.sleep(settings.worker_interval_s)
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    run()
