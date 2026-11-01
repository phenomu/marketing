"""Database access layer.

Single SQLAlchemy engine built from `config.settings.database_url` — the exact
same mechanism in native and container execution (repo rule). Phase 5 replaces
this minimal schema with the full lead models.
"""

from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine

from config import settings

log = logging.getLogger(__name__)

SCHEMA_VERSION = "0.1"

METADATA = MetaData()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


APP_META = Table(
    "app_meta",
    METADATA,
    Column("key", String(64), primary_key=True),
    Column("value", String(255)),
    Column("updated_at", DateTime, default=_utcnow, onupdate=_utcnow),
)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # FastAPI serves /health from worker threads; sqlite defaults to
        # check_same_thread=True which breaks that.
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, future=True)
    return engine


def check_db() -> bool:
    """True when a trivial query succeeds. Never raises."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — health probe must not crash
        log.warning("database check failed: %s", exc)
        return False


def init_db() -> str:
    """Create the minimal schema and stamp schema_version. Idempotent."""
    engine = get_engine()
    METADATA.create_all(engine)
    with engine.begin() as conn:
        current = conn.execute(
            text("SELECT value FROM app_meta WHERE key = 'schema_version'")
        ).scalar()
        if current is None:
            conn.execute(APP_META.insert().values(key="schema_version", value=SCHEMA_VERSION))
        elif current != SCHEMA_VERSION:
            conn.execute(
                APP_META.update()
                .where(APP_META.c.key == "schema_version")
                .values(value=SCHEMA_VERSION)
            )
    log.info("database initialized (schema_version=%s, url=%s)", SCHEMA_VERSION, _safe_url())
    return SCHEMA_VERSION


def _safe_url() -> str:
    """Database URL with the password stripped, for logs."""
    url = settings.database_url
    if "@" in url and "://" in url:
        scheme, _, rest = url.partition("://")
        credentials, _, hostpart = rest.rpartition("@")
        if ":" in credentials:
            user = credentials.split(":", 1)[0]
            return f"{scheme}://{user}:***@{hostpart}"
    return url
