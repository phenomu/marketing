"""Persistence for discovery: business upserts + job lifecycle.

SQLAlchemy Core only (no ORM) — same engine mechanism in native and
container runs. Tables live in `app.db.METADATA`; this module owns the
write logic. Every function takes an explicit Engine so tests can pass
their own (SQLite) engine without touching global state.
"""

from __future__ import annotations

import logging
import datetime as dt

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Engine

from app.db import BUSINESSES, DISCOVERY_JOBS
from app.urls import extract_domain, normalize_website
from scrapers.base import Business

log = logging.getLogger(__name__)

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_STATUSES = (JOB_PENDING, JOB_RUNNING, JOB_DONE, JOB_FAILED)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def create_engine_sqlite(path: str) -> Engine:
    """Convenience for tests/scripts: file-backed SQLite engine."""
    return create_engine(f"sqlite:///{path}", future=True)


# --- discovery jobs ---------------------------------------------------------


def insert_job(engine: Engine, source: str, query: str, location: str, max_results: int) -> int:
    """Queue one discovery job. Returns its id."""
    with engine.begin() as conn:
        result = conn.execute(
            insert(DISCOVERY_JOBS).values(
                source=source,
                query=query,
                location=location,
                max_results=max_results,
                status=JOB_PENDING,
                created_at=_utcnow(),
            )
        )
        job_id = int(result.inserted_primary_key[0])
    log.info("queued discovery job %s (%s %r in %r)", job_id, source, query, location)
    return job_id


def claim_next_pending(engine: Engine) -> dict | None:
    """Mark the oldest pending job as running and return it as a dict.
    Single-worker design: no row locking needed; claim is one UPDATE."""
    with engine.begin() as conn:
        row = conn.execute(
            select(DISCOVERY_JOBS.c.id, DISCOVERY_JOBS.c.source, DISCOVERY_JOBS.c.query,
                   DISCOVERY_JOBS.c.location, DISCOVERY_JOBS.c.max_results)
            .where(DISCOVERY_JOBS.c.status == JOB_PENDING)
            .order_by(DISCOVERY_JOBS.c.id)
            .limit(1)
        ).first()
        if row is None:
            return None
        conn.execute(
            update(DISCOVERY_JOBS)
            .where(DISCOVERY_JOBS.c.id == row.id)
            .values(status=JOB_RUNNING, started_at=_utcnow())
        )
    return {
        "id": int(row.id),
        "source": row.source,
        "query": row.query,
        "location": row.location,
        "max_results": int(row.max_results),
    }


def complete_job(
    engine: Engine,
    job_id: int,
    status: str,
    found: int = 0,
    new: int = 0,
    updated: int = 0,
    error: str = "",
) -> None:
    if status not in JOB_STATUSES:
        raise ValueError(f"invalid job status: {status}")
    with engine.begin() as conn:
        conn.execute(
            update(DISCOVERY_JOBS)
            .where(DISCOVERY_JOBS.c.id == job_id)
            .values(
                status=status,
                found_count=found,
                new_count=new,
                updated_count=updated,
                error=error[:2000],
                finished_at=_utcnow(),
            )
        )
    log.info(
        "discovery job %s -> %s (found=%s new=%s updated=%s%s)",
        job_id, status, found, new, updated, f" error={error}" if error else "",
    )


def last_job_per_search(engine: Engine, source: str, query: str, location: str):
    """Newest job row for one search triple, ANY status (or None).
    Pending rows count as covered — re-enqueue only after the row is
    finished (done/failed), so a failed search retries on the next
    scheduler tick after manual plan touch... but failed ones re-queue
    automatically (see enqueue_from_plan)."""
    with engine.connect() as conn:
        return conn.execute(
            select(DISCOVERY_JOBS)
            .where(
                (DISCOVERY_JOBS.c.source == source)
                & (DISCOVERY_JOBS.c.query == query)
                & (DISCOVERY_JOBS.c.location == location)
            )
            .order_by(DISCOVERY_JOBS.c.id.desc())
            .limit(1)
        ).first()


def list_jobs(engine: Engine, limit: int = 20) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(DISCOVERY_JOBS).order_by(DISCOVERY_JOBS.c.id.desc()).limit(limit)
        ).mappings()
        return [dict(r) for r in rows]


# --- businesses --------------------------------------------------------------


def upsert_businesses(engine: Engine, businesses: list[Business]) -> tuple[int, int]:
    """Insert new businesses / refresh existing ones by dedup key.

    Non-empty incoming fields overwrite stored values (fresher source
    data wins); empty fields never erase existing data. Returns
    (new_count, updated_count).
    """
    new_count = updated_count = 0
    now = _utcnow()
    for biz in businesses:
        key = biz.key
        if not key or not biz.name.strip():
            continue
        with engine.begin() as conn:
            existing = conn.execute(
                select(BUSINESSES.c.id).where(BUSINESSES.c.key == key)
            ).first()
            values = {
                "key": key,
                "name": biz.name.strip(),
                "address": (biz.address or "").strip(),
                "phone": (biz.phone or "").strip(),
                "website": normalize_website(biz.website or ""),
                "domain": extract_domain(biz.website or ""),
                "category": (biz.category or "").strip(),
                "place_id": (biz.place_id or "").strip(),
                "source": biz.source,
                "source_url": (biz.source_url or "").strip(),
                "latitude": biz.latitude,
                "longitude": biz.longitude,
                "rating": biz.rating,
                "review_count": biz.review_count,
            }
            if existing is None:
                conn.execute(
                    insert(BUSINESSES).values(**values, first_seen_at=now, last_seen_at=now)
                )
                new_count += 1
            else:
                # only overwrite with non-empty values; keep first_seen_at
                updates = {k: v for k, v in values.items() if v not in ("", None)}
                updates["id"] = int(existing.id)
                conn.execute(
                    update(BUSINESSES)
                    .where(BUSINESSES.c.id == existing.id)
                    .values(**updates, last_seen_at=now)
                )
                updated_count += 1
    return new_count, updated_count


def count_businesses(engine: Engine) -> int:
    from sqlalchemy import func

    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(BUSINESSES)).scalar() or 0)


def list_businesses(engine: Engine, limit: int = 50, has_website: bool | None = None) -> list[dict]:
    stmt = select(BUSINESSES).order_by(BUSINESSES.c.last_seen_at.desc()).limit(limit)
    if has_website is True:
        stmt = stmt.where(BUSINESSES.c.domain != "")
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(stmt).mappings()]
