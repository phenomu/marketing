"""Create the database schema (app_meta) — SQLite or PostgreSQL per settings."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import init_db  # noqa: E402
from config.logging_setup import setup_logging  # noqa: E402


def main() -> int:
    setup_logging("init_db")
    schema_version = init_db()
    print(f"database initialized (schema_version={schema_version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
