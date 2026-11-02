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
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine

from config import settings

log = logging.getLogger(__name__)

SCHEMA_VERSION = "0.3"

METADATA = MetaData()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


BUSINESSES = Table(
    "businesses",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(255), nullable=False, unique=True, index=True),  # dedup key
    Column("name", String(255), nullable=False),
    Column("address", String(512), default=""),
    Column("phone", String(64), default=""),
    Column("website", String(512), default=""),
    Column("domain", String(255), default="", index=True),  # website dedup + crawl queue
    Column("category", String(128), default=""),
    Column("place_id", String(128), default=""),
    Column("source", String(32), default=""),
    Column("source_url", String(512), default=""),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("rating", Float),
    Column("review_count", Integer),
    Column("industry_match", Boolean, default=False, nullable=False),  # industries.yaml
    Column("first_seen_at", DateTime, default=_utcnow),
    Column("last_seen_at", DateTime, default=_utcnow, onupdate=_utcnow),
)

DISCOVERY_JOBS = Table(
    "discovery_jobs",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(32), nullable=False),
    Column("query", String(255), nullable=False),
    Column("location", String(128), default=""),
    Column("max_results", Integer, default=20),
    Column("status", String(16), default="pending"),  # pending|running|done|failed
    Column("found_count", Integer, default=0),
    Column("new_count", Integer, default=0),
    Column("updated_count", Integer, default=0),
    Column("error", String(2000), default=""),
    Column("created_at", DateTime, default=_utcnow),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
)


CRAWL_JOBS = Table(
    "crawl_jobs",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("domain", String(255), nullable=False, unique=True, index=True),
    Column("status", String(16), default="pending"),  # pending|running|done|failed
    Column("pages_crawled", Integer, default=0),
    Column("contact_url", String(512), default=""),
    Column("about_url", String(512), default=""),
    Column("mailto_count", Integer, default=0),
    Column("error", String(2000), default=""),
    Column("queued_at", DateTime, default=_utcnow),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
)

CRAWL_PAGES = Table(
    "crawl_pages",
    METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("crawl_job_id", Integer, ForeignKey("crawl_jobs.id"), nullable=False, index=True),
    Column("url", String(512), nullable=False),
    Column("kind", String(16), default="other"),  # home|contact|about|other
    Column("http_status", Integer),
    Column("fetched_ok", Boolean, default=False),
    Column("title", String(512), default=""),
    Column("text", Text, default=""),  # visible text for PHASE 4 extraction
    Column("fetched_at", DateTime, default=_utcnow),
)


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
    """Create the schema and stamp schema_version. Idempotent; on existing
    databases it also applies additive migrations (new tables/columns
    from older schema versions — see _MIGRATIONS)."""
    engine = get_engine()
    METADATA.create_all(engine)

    with engine.begin() as conn:
        current = conn.execute(
            text("SELECT value FROM app_meta WHERE key = 'schema_version'")
        ).scalar()
        if current is None:
            conn.execute(APP_META.insert().values(key="schema_version", value=SCHEMA_VERSION))
        elif current != SCHEMA_VERSION:
            if current in _MIGRATIONS:
                for stmt in _MIGRATIONS[current]:
                    conn.execute(text(stmt))
            conn.execute(
                APP_META.update()
                .where(APP_META.c.key == "schema_version")
                .values(value=SCHEMA_VERSION)
            )
    log.info("database initialized (schema_version=%s, url=%s)", SCHEMA_VERSION, _safe_url())
    return SCHEMA_VERSION


# Additive migrations applied when upgrading an existing database.
# SQLite/PG both accept these statements (ADD COLUMN only).
_MIGRATIONS: dict[str, tuple[str, ...]] = {
    "0.2": (
        "ALTER TABLE businesses ADD COLUMN industry_match BOOLEAN NOT NULL DEFAULT false",
    ),
}


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
