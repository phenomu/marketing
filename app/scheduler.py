"""Background scheduler — periodic task runner.

Status: SCAFFOLD. The interval loop + heartbeat are real; scheduled jobs
(follow-ups, retry passes) land with PHASE 6 (see TRACKER.md).
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
            # TODO(PHASE 6): run follow-up scheduling + retry passes from the DB.
            time.sleep(settings.scheduler_interval_s)
    except KeyboardInterrupt:
        log.info("scheduler stopped")


if __name__ == "__main__":
    run()
