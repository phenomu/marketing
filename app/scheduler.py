"""Background scheduler — periodic task runner.

Interval loop + heartbeat real. PHASE 2: refreshes the discovery queue
from `config/keywords.yaml` (idempotent). PHASE 3: queues crawl jobs for
business domains (filtered by `config/industries.yaml` when it defines
include keywords — file is re-read each tick, no restart needed).
Follow-up/retry scheduling lands with PHASE 6.
"""

from __future__ import annotations

import logging
import time

from app.crawl import enqueue_crawls
from app.db import check_db, get_engine
from app.discovery import enqueue_from_plan, load_keyword_plan
from app.heartbeat import write_heartbeat
from config import settings
from config.logging_setup import setup_logging

log = logging.getLogger(__name__)


def refresh_discovery_queue() -> int:
    """Enqueue discovery jobs from keywords.yaml. Returns jobs queued."""
    plan = load_keyword_plan()
    if not plan:
        return 0
    return enqueue_from_plan(get_engine(), settings.lead_source, plan)


def run() -> None:
    setup_logging("scheduler")
    log.info(
        "scheduler started (interval=%ss, env=%s)",
        settings.scheduler_interval_s,
        settings.app_env,
    )
    try:
        while True:
            db_state = "up" if check_db() else "down"
            write_heartbeat("scheduler", db=db_state)
            if db_state == "up":
                try:
                    queued = refresh_discovery_queue()
                    if queued:
                        log.info("queued %s discovery job(s) from keywords.yaml", queued)
                    crawled = enqueue_crawls()
                    if crawled:
                        log.info("queued %s crawl job(s) from business domains", crawled)
                except Exception as exc:  # noqa: BLE001 — service loop must survive
                    log.exception("scheduler refresh failed: %s", exc)
            # TODO(PHASE 6): run follow-up scheduling + retry passes from the DB.
            time.sleep(settings.scheduler_interval_s)
    except KeyboardInterrupt:
        log.info("scheduler stopped")


if __name__ == "__main__":
    run()
