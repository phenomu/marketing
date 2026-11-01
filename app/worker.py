"""Crawler worker — long-running process polling for crawl jobs.

Status: SCAFFOLD. Loop, heartbeat, DB connectivity, and graceful shutdown are
real; crawl job discovery/execution lands with PHASE 2-3 (see TRACKER.md —
never present this as a completed feature).
"""

from __future__ import annotations

import logging
import time

from app.db import check_db
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
            # TODO(PHASE 2-3): poll the crawl job table and process pending jobs.
            time.sleep(settings.worker_interval_s)
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    run()
