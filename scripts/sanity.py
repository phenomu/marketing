"""CLI sanity check: print effective settings + DB connectivity (native or container)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import check_db, init_db  # noqa: E402
from config import settings  # noqa: E402
from config.logging_setup import setup_logging  # noqa: E402


def _mask_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url or "(not configured)"
    scheme, rest = url.split("://", 1)
    credentials, _, hostpart = rest.rpartition("@")
    user = credentials.split(":", 1)[0] if credentials else ""
    return f"{scheme}://{user}:***@{hostpart}"


def main() -> int:
    setup_logging("sanity")
    print("== MARKETING settings ==")
    print(f"app_env            = {settings.app_env}")
    print(f"version            = {settings.version}")
    print(f"log_dir            = {settings.log_dir}")
    print(f"dry_run            = {settings.dry_run}")
    print(f"backend_url        = {settings.backend_url}")
    print(f"worker_interval    = {settings.worker_interval_s}s")
    print(f"scheduler_interval = {settings.scheduler_interval_s}s")
    print(f"database_url       = {_mask_url(settings.database_url)}")
    if not settings.database_url:
        print("db check           = SKIPPED (no DATABASE_URL / POSTGRES_PASSWORD)")
        return 0
    if check_db():
        print("db check           = UP")
        print(f"schema_version     = {init_db()}")
        return 0
    print("db check           = DOWN")
    return 1


if __name__ == "__main__":
    sys.exit(main())
