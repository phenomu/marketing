"""Persistence for discovery: business upserts + job lifecycle.

SQLAlchemy Core only (no ORM) — same engine mechanism in native and
container runs. Tables live in `app.db.METADATA`; this module owns the
write logic. Every function takes an explicit Engine so tests can pass
their own (SQLite) engine without touching global state.
"""

from __future__ import annotations

import logging
import datetime as dt

from sqlalchemy import create_engine, delete, func, insert, select, update
from sqlalchemy.engine import Engine

from app.db import BUSINESSES, CONTACTS, CRAWL_JOBS, CRAWL_PAGES, DISCOVERY_JOBS
from app.industries import matches_industry
from app.urls import extract_domain, is_platform, normalize_website
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


def upsert_businesses(
    engine: Engine, businesses: list[Business], industry_rules=None
) -> tuple[int, int]:
    """Insert new businesses / refresh existing ones by dedup key.

    Non-empty incoming fields overwrite stored values (fresher source
    data wins); empty fields never erase existing data. industry_rules
    (app.industries.IndustryRules, optional) tags industry_match. Returns
    (new_count, updated_count).
    """
    new_count = updated_count = 0
    now = _utcnow()
    for biz in businesses:
        key = biz.key
        if not key or not biz.name.strip():
            continue
        industry_match = False
        if industry_rules is not None:
            industry_match = matches_industry(
                industry_rules, biz.category or "", biz.name or ""
            )
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
                "industry_match": industry_match,
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


# --- crawl (PHASE 3) ---------------------------------------------------------


def enqueue_crawl_domains(engine: Engine, limit: int = 200, industry_rules=None) -> int:
    """Queue crawl jobs for business domains not yet queued. When
    industry_rules are provided (app.industries.IndustryRules), a domain
    is queued only if at least one business on it matches the include
    rules — an empty/disabled include list queues everything. Returns
    newly queued rows."""
    from sqlalchemy import func

    with engine.begin() as conn:
        existing = {row[0] for row in conn.execute(select(CRAWL_JOBS.c.domain))}
        domain_rows = conn.execute(
            select(BUSINESSES.c.domain, BUSINESSES.c.category, BUSINESSES.c.name)
            .where(BUSINESSES.c.domain != "")
            .order_by(BUSINESSES.c.id)
            .limit(limit * 3)
        ).all()
        picked: set[str] = set()
        for row in domain_rows:
            if len(picked) >= limit:
                break
            if row.domain in existing or row.domain in picked:
                continue
            if is_platform(row.domain):
                continue  # social profile, not a business site
            if industry_rules is not None and industry_rules.enabled:
                if not matches_industry(industry_rules, row.category, row.name):
                    continue
            picked.add(row.domain)
        queued = 0
        now = _utcnow()
        for domain in sorted(picked):
            conn.execute(
                insert(CRAWL_JOBS).values(domain=domain, status="pending", queued_at=now)
            )
            queued += 1
    return queued


def claim_next_crawl(engine: Engine) -> dict | None:
    """Mark the oldest pending crawl job running and return it."""
    with engine.begin() as conn:
        row = conn.execute(
            select(CRAWL_JOBS.c.id, CRAWL_JOBS.c.domain)
            .where(CRAWL_JOBS.c.status == "pending")
            .order_by(CRAWL_JOBS.c.id)
            .limit(1)
        ).first()
        if row is None:
            return None
        conn.execute(
            update(CRAWL_JOBS)
            .where(CRAWL_JOBS.c.id == row.id)
            .values(status="running", started_at=_utcnow())
        )
    return {"id": int(row.id), "domain": row.domain}


def save_crawl_pages(engine: Engine, crawl_job_id: int, pages) -> int:
    """Insert CrawlOutcome.pages rows (replaces any previous rows for the
    job — re-crawls overwrite). Returns pages stored."""
    import json

    with engine.begin() as conn:
        conn.execute(CRAWL_PAGES.delete().where(CRAWL_PAGES.c.crawl_job_id == crawl_job_id))
        for page in pages:
            conn.execute(
                insert(CRAWL_PAGES).values(
                    crawl_job_id=crawl_job_id,
                    url=page.url,
                    kind=page.kind,
                    http_status=page.http_status,
                    fetched_ok=page.fetched_ok,
                    title=(page.title or "")[:500],
                    text=page.text,
                    mailtos=json.dumps(page.mailtos or []),
                    fetched_at=_utcnow(),
                )
            )
    return len(pages)


def complete_crawl_job(
    engine: Engine,
    crawl_job_id: int,
    status: str,
    pages_crawled: int = 0,
    outcome=None,
    error: str = "",
) -> None:
    """Finish a crawl job: counters + contact/about URLs + mailto total."""
    contact_url = about_url = ""
    mailto_count = 0
    if outcome is not None:
        contact_pages = [p for p in outcome.pages if p.kind == "contact" and p.fetched_ok]
        about_pages = [p for p in outcome.pages if p.kind == "about" and p.fetched_ok]
        contact_url = contact_pages[0].url if contact_pages else ""
        about_url = about_pages[0].url if about_pages else ""
        mailto_count = sum(len(p.mailtos) for p in outcome.pages)
    with engine.begin() as conn:
        conn.execute(
            update(CRAWL_JOBS)
            .where(CRAWL_JOBS.c.id == crawl_job_id)
            .values(
                status=status,
                pages_crawled=pages_crawled,
                contact_url=contact_url[:512],
                about_url=about_url[:512],
                mailto_count=mailto_count,
                error=error[:2000],
                finished_at=_utcnow(),
            )
        )
    log.info(
        "crawl job %s -> %s (pages=%s mailto=%s%s)",
        crawl_job_id, status, pages_crawled, mailto_count,
        f" error={error}" if error else "",
    )


def count_crawl_jobs(engine: Engine, status: str | None = None) -> int:
    from sqlalchemy import func

    stmt = select(func.count()).select_from(CRAWL_JOBS)
    if status:
        stmt = stmt.where(CRAWL_JOBS.c.status == status)
    with engine.connect() as conn:
        return int(conn.execute(stmt).scalar() or 0)


def list_crawl_jobs(engine: Engine, limit: int = 20) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(CRAWL_JOBS).order_by(CRAWL_JOBS.c.id.desc()).limit(limit)
        ).mappings()
        return [dict(r) for r in rows]


def tag_existing_businesses(engine: Engine, industry_rules) -> int:
    """Backfill industry_match for rows stored before the rules existed.
    Returns rows updated."""
    tagged = 0
    with engine.begin() as conn:
        rows = conn.execute(select(BUSINESSES.c.id, BUSINESSES.c.category, BUSINESSES.c.name)).all()
        for row in rows:
            match = matches_industry(industry_rules, row.category, row.name)
            conn.execute(
                update(BUSINESSES)
                .where(BUSINESSES.c.id == row.id)
                .values(industry_match=match)
            )
            tagged += 1
    return tagged


# --- contacts layer (PHASE 4) -------------------------------------------------


def claim_pending_extractions(engine: Engine, limit: int) -> list[dict]:
    """Crawl jobs that finished crawling but were never extracted.
    Marks nothing — extraction completion is set by mark_extraction_done."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(CRAWL_JOBS.c.id, CRAWL_JOBS.c.domain)
            .where(CRAWL_JOBS.c.status == "done", CRAWL_JOBS.c.contacts_extracted == False)  # noqa: E712
            .order_by(CRAWL_JOBS.c.id)
            .limit(limit)
        ).all()
    return [{"id": int(r.id), "domain": r.domain} for r in rows]


def load_crawl_pages(engine: Engine, crawl_job_id: int) -> list[dict]:
    import json

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                CRAWL_PAGES.c.url, CRAWL_PAGES.c.kind, CRAWL_PAGES.c.text,
                CRAWL_PAGES.c.mailtos, CRAWL_PAGES.c.fetched_ok,
            )
            .where(CRAWL_PAGES.c.crawl_job_id == crawl_job_id, CRAWL_PAGES.c.fetched_ok == True)  # noqa: E712
            .order_by(CRAWL_PAGES.c.id)
        ).mappings()
        out = []
        for r in rows:
            page = dict(r)
            try:
                page["mailtos"] = json.loads(page.pop("mailtos") or "[]")
            except (TypeError, ValueError):
                page["mailtos"] = []
            out.append(page)
        return out


def primary_business_id(engine: Engine, domain: str) -> int | None:
    """Business row matching a crawl domain: highest id (latest upsert)."""
    with engine.connect() as conn:
        row = conn.execute(
            select(BUSINESSES.c.id)
            .where(BUSINESSES.c.domain == domain)
            .order_by(BUSINESSES.c.id.desc())
            .limit(1)
        ).first()
    return int(row.id) if row else None


def save_contacts(engine: Engine, business_id: int, crawl_job_id: int, contacts) -> dict:
    """Insert new contact rows; on (business, kind, value_norm) conflict bump
    last_seen_at and keep the best confidence. Returns {new, updated}."""
    new = updated = 0
    with engine.begin() as conn:
        existing = {
            (r.kind, r.value_norm): (r.id, r.confidence)
            for r in conn.execute(
                select(CONTACTS.c.id, CONTACTS.c.kind, CONTACTS.c.value_norm, CONTACTS.c.confidence)
                .where(CONTACTS.c.business_id == business_id)
            ).all()
        }
        now = _utcnow()
        for contact in contacts:
            row_key = (contact.kind, contact.norm)
            known = existing.get(row_key)
            if known is None:
                conn.execute(
                    insert(CONTACTS).values(
                        business_id=business_id,
                        crawl_job_id=crawl_job_id,
                        kind=contact.kind,
                        value=contact.value[:2000],
                        value_norm=contact.norm[:320],
                        source_url=(contact.source_url or "")[:512],
                        source_kind=contact.source_kind,
                        confidence=contact.confidence,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
                new += 1
            else:
                row_id, old_conf = known
                conn.execute(
                    update(CONTACTS)
                    .where(CONTACTS.c.id == row_id)
                    .values(
                        crawl_job_id=crawl_job_id,
                        last_seen_at=now,
                        confidence=max(int(old_conf or 0), contact.confidence),
                    )
                )
                updated += 1
    return {"new": new, "updated": updated}


def mark_extraction_done(engine: Engine, crawl_job_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(CRAWL_JOBS)
            .where(CRAWL_JOBS.c.id == crawl_job_id)
            .values(contacts_extracted=True)
        )


def update_business_address_if_empty(engine: Engine, business_id: int, address: str) -> int:
    """Fill businesses.address only when empty — discovery data wins over
    crawl guesses. Returns rows updated."""
    with engine.begin() as conn:
        result = conn.execute(
            update(BUSINESSES)
            .where(BUSINESSES.c.id == business_id, BUSINESSES.c.address == "")
            .values(address=address[:512])
        )
        return result.rowcount


def count_contacts(engine: Engine, business_id: int | None = None, kind: str | None = None) -> int:
    stmt = select(func.count()).select_from(CONTACTS)
    if business_id is not None:
        stmt = stmt.where(CONTACTS.c.business_id == business_id)
    if kind:
        stmt = stmt.where(CONTACTS.c.kind == kind)
    with engine.connect() as conn:
        return int(conn.execute(stmt).scalar() or 0)


def list_contacts(engine: Engine, business_id: int, limit: int = 50) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(CONTACTS)
            .where(CONTACTS.c.business_id == business_id)
            .order_by(CONTACTS.c.kind, CONTACTS.c.confidence.desc())
            .limit(limit)
        ).mappings()
        return [dict(r) for r in rows]
