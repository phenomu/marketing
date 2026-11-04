"""Dashboard data layer — pure query functions, no Streamlit.

Separated from app.py so they are unit-testable against a throwaway
SQLite engine (same pattern as the rest of the test suite: hermetic,
no network). Every function is never-raise: on error it returns an
empty/default shape and the message, so one broken query cannot kill
the whole page render.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Connection, Engine, desc, func, select, text
from sqlalchemy.engine import create_engine

from app.db import (
    BUSINESSES,
    CAMPAIGNS,
    CONTACTS,
    CRAWL_JOBS,
    DISCOVERY_JOBS,
    LEADS,
    OUTREACH_EVENTS,
    SUPPRESSIONS,
    get_engine,
)
from app.store import list_leads

ReportingEngine = Engine


def _rows(conn: Connection, stmt) -> list[dict]:
    return [dict(r) for r in conn.execute(stmt).mappings().all()]


def overview(engine: Engine) -> dict[str, Any]:
    """Headline numbers for the Overview page."""
    out: dict[str, Any] = {
        "businesses": 0,
        "contacts_by_kind": {},
        "email_statuses": {},
        "leads_by_status": {},
        "crawl_by_status": {},
        "discovery_by_status": {},
        "campaigns_by_status": {},
        "events_by_type": {},
        "suppressions": 0,
        "suppressions_by_reason": {},
        "last_event_at": None,
        "error": "",
    }
    try:
        with engine.connect() as conn:
            out["businesses"] = conn.execute(
                select(func.count()).select_from(BUSINESSES)
            ).scalar() or 0
            for row in _rows(conn, select(CONTACTS.c.kind, func.count().label("n")).group_by(CONTACTS.c.kind)):
                out["contacts_by_kind"][row["kind"]] = row["n"]
            for row in _rows(conn, select(CONTACTS.c.status, func.count().label("n")).where(CONTACTS.c.kind == "email").group_by(CONTACTS.c.status)):
                out["email_statuses"][row["status"] or "unchecked"] = row["n"]
            for row in _rows(conn, select(LEADS.c.status, func.count().label("n")).group_by(LEADS.c.status)):
                out["leads_by_status"][row["status"]] = row["n"]
            for row in _rows(conn, select(CRAWL_JOBS.c.status, func.count().label("n")).group_by(CRAWL_JOBS.c.status)):
                out["crawl_by_status"][row["status"]] = row["n"]
            for row in _rows(conn, select(DISCOVERY_JOBS.c.status, func.count().label("n")).group_by(DISCOVERY_JOBS.c.status)):
                out["discovery_by_status"][row["status"]] = row["n"]
            for row in _rows(conn, select(CAMPAIGNS.c.status, func.count().label("n")).group_by(CAMPAIGNS.c.status)):
                out["campaigns_by_status"][row["status"]] = row["n"]
            for row in _rows(conn, select(OUTREACH_EVENTS.c.event_type, func.count().label("n")).group_by(OUTREACH_EVENTS.c.event_type)):
                out["events_by_type"][row["event_type"]] = row["n"]
            out["suppressions"] = conn.execute(
                select(func.count()).select_from(SUPPRESSIONS)
            ).scalar() or 0
            for row in _rows(conn, select(SUPPRESSIONS.c.reason, func.count().label("n")).group_by(SUPPRESSIONS.c.reason)):
                out["suppressions_by_reason"][row["reason"]] = row["n"]
            last = conn.execute(select(func.max(OUTREACH_EVENTS.c.created_at))).scalar()
            out["last_event_at"] = last.isoformat() if last else None
    except Exception as exc:  # noqa: BLE001 — never-raise data layer
        out["error"] = str(exc)
    return out


def leads_table(
    engine: Engine,
    min_score: int = 0,
    email_status: str = "any",
    lead_status: str = "any",
    limit: int | None = 500,
) -> list[dict]:
    """Lead management table with the same filters the CSV export uses."""
    try:
        rows = list_leads(
            engine,
            limit=limit,
            min_score=min_score,
            email_status=None if email_status == "any" else email_status,
        )
        if lead_status != "any":
            rows = [r for r in rows if r.get("status") == lead_status]
        return rows
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def lead_detail(engine: Engine, lead_id: int) -> dict[str, Any]:
    """One lead: business row, all its contacts, its outreach events."""
    out: dict[str, Any] = {"lead": None, "business": None, "contacts": [], "events": [], "error": ""}
    try:
        with engine.connect() as conn:
            lead = conn.execute(
                select(LEADS).where(LEADS.c.id == lead_id)
            ).mappings().first()
            if lead is None:
                out["error"] = f"lead {lead_id} tidak ditemukan"
                return out
            out["lead"] = dict(lead)
            business = conn.execute(
                select(BUSINESSES).where(BUSINESSES.c.id == lead["business_id"])
            ).mappings().first()
            out["business"] = dict(business) if business else None
            out["contacts"] = _rows(
                conn,
                select(CONTACTS).where(CONTACTS.c.business_id == lead["business_id"]).order_by(CONTACTS.c.kind, desc(CONTACTS.c.confidence)).limit(100),
            )
            out["events"] = _rows(
                conn,
                select(OUTREACH_EVENTS).where(OUTREACH_EVENTS.c.lead_id == lead_id).order_by(desc(OUTREACH_EVENTS.c.created_at)).limit(50),
            )
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def campaigns_table(engine: Engine) -> list[dict]:
    try:
        with engine.connect() as conn:
            return _rows(conn, select(CAMPAIGNS).order_by(desc(CAMPAIGNS.c.id)).limit(100))
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def campaign_events(engine: Engine, campaign_id: int, limit: int = 200) -> list[dict]:
    try:
        with engine.connect() as conn:
            return _rows(
                conn,
                select(OUTREACH_EVENTS)
                .where(OUTREACH_EVENTS.c.campaign_id == campaign_id)
                .order_by(desc(OUTREACH_EVENTS.c.created_at))
                .limit(limit),
            )
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def businesses_table(
    engine: Engine,
    source: str = "any",
    industry: str = "any",
    search: str = "",
    limit: int | None = 500,
) -> list[dict]:
    """Businesses browser for the KPI drill-down (source filter + name/
    category/address search). limit=None returns every row (operator
    'Tampilkan: Semua')."""
    try:
        stmt = select(
            BUSINESSES.c.id,
            BUSINESSES.c.name,
            BUSINESSES.c.category,
            BUSINESSES.c.phone,
            BUSINESSES.c.domain,
            BUSINESSES.c.address,
            BUSINESSES.c.source,
            BUSINESSES.c.rating,
            BUSINESSES.c.review_count,
            BUSINESSES.c.industry_match,
        ).order_by(desc(BUSINESSES.c.id))
        if limit is not None:
            stmt = stmt.limit(limit)
        if source != "any":
            stmt = stmt.where(BUSINESSES.c.source == source)
        if industry == "match":
            stmt = stmt.where(BUSINESSES.c.industry_match.is_(True))
        if search.strip():
            like = f"%{search.strip()}%"
            stmt = stmt.where(
                BUSINESSES.c.name.ilike(like)
                | BUSINESSES.c.category.ilike(like)
                | BUSINESSES.c.address.ilike(like)
            )
        with engine.connect() as conn:
            return _rows(conn, stmt)
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def contacts_table(
    engine: Engine,
    kind: str = "any",
    status: str = "any",
    search: str = "",
    limit: int | None = 500,
) -> list[dict]:
    """Contact browser for the KPI drill-down. limit=None = unlimited."""
    try:
        stmt = select(
            CONTACTS.c.id,
            CONTACTS.c.business_id,
            CONTACTS.c.kind,
            CONTACTS.c.value,
            CONTACTS.c.status,
            CONTACTS.c.confidence,
            CONTACTS.c.source_kind,
        ).order_by(desc(CONTACTS.c.id))
        if limit is not None:
            stmt = stmt.limit(limit)
        if kind != "any":
            stmt = stmt.where(CONTACTS.c.kind == kind)
        if status != "any":
            stmt = stmt.where(CONTACTS.c.status == status)
        if search.strip():
            like = f"%{search.strip()}%"
            stmt = stmt.where(CONTACTS.c.value.ilike(like))
        with engine.connect() as conn:
            rows = _rows(conn, stmt)
        if rows and "error" in rows[0]:
            return rows
        # join business names in one pass
        ids = {r["business_id"] for r in rows if r.get("business_id")}
        names: dict[int, str] = {}
        if ids:
            with engine.connect() as conn:
                for r in _rows(
                    conn,
                    select(BUSINESSES.c.id, BUSINESSES.c.name).where(
                        BUSINESSES.c.id.in_(tuple(ids))
                    ),
                ):
                    names[r["id"]] = r["name"]
        for r in rows:
            r["business_name"] = names.get(r.get("business_id"), "")
        return rows
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def discovery_overview(engine: Engine) -> dict[str, Any]:

    """Discovery + crawl pipeline state for the Lead discovery page."""
    out: dict[str, Any] = {"jobs": [], "crawl_jobs": [], "error": ""}
    try:
        with engine.connect() as conn:
            out["jobs"] = _rows(conn, select(DISCOVERY_JOBS).order_by(desc(DISCOVERY_JOBS.c.id)).limit(30))
            out["crawl_jobs"] = _rows(conn, select(CRAWL_JOBS).order_by(desc(CRAWL_JOBS.c.id)).limit(30))
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def events_daily(engine: Engine, days: int = 14) -> list[dict]:
    """Outreach events per (day, type) for the analytics chart."""
    try:
        since = dt.datetime.utcnow() - dt.timedelta(days=days)
        with engine.connect() as conn:
            rows = _rows(
                conn,
                select(
                    func.date(OUTREACH_EVENTS.c.created_at).label("day"),
                    OUTREACH_EVENTS.c.event_type,
                    func.count().label("n"),
                )
                .where(OUTREACH_EVENTS.c.created_at >= since)
                .group_by("day", OUTREACH_EVENTS.c.event_type)
                .order_by("day"),
            )
        return rows
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def leads_by_score_bucket(engine: Engine) -> list[dict]:
    try:
        with engine.connect() as conn:
            bucket = func.floor(LEADS.c.score / 20) * 20
            return _rows(
                conn,
                select(bucket.label("bucket"), func.count().label("n")).group_by("bucket").order_by("bucket"),
            )
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def contacts_by_kind(engine: Engine) -> list[dict]:
    try:
        with engine.connect() as conn:
            return _rows(conn, select(CONTACTS.c.kind, func.count().label("n")).group_by(CONTACTS.c.kind))
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def table_count(engine: Engine, table: str, where: str = "") -> int | None:
    """Exact row count for a browser caption (browser tables render a
    capped window — LIMIT 1000 — so len(df) understates the true total
    and looks like data is missing). Returns None on any error so the
    caption falls back to the window count. `table` is whitelisted;
    `where` is caller-built from validated filter values only (no user
    text — search terms use bound parameters in the table queries)."""
    allowed = {"contacts": CONTACTS, "businesses": BUSINESSES, "leads": LEADS}
    t = allowed.get(table)
    if t is None:
        return None
    try:
        stmt = select(func.count()).select_from(t)
        if where:
            stmt = stmt.where(text(where))
        with engine.connect() as conn:
            return int(conn.execute(stmt).scalar() or 0)
    except Exception:  # noqa: BLE001 — cosmetic caption, never fatal
        return None


def suppressions_table(engine: Engine) -> list[dict]:
    try:
        with engine.connect() as conn:
            return _rows(conn, select(SUPPRESSIONS).order_by(desc(SUPPRESSIONS.c.id)).limit(200))
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def default_engine() -> Engine:
    return get_engine()
