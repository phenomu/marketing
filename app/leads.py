"""Lead building + scoring (PHASE 5).

A lead is one row per business: best contact per channel plus a 0-100
score. Score is a transparent heuristic (D-033), not ML:

    email   valid  +40 | unknown +25 | unchecked +15 | invalid 0 | none 0
    phone   present +20
    social  present +5
    address present +10
    website crawled (domain set) +15
    fresh   last_seen <= 14d +10 | <= 30d +5

Breakdown is stored in leads.score_detail so the operator can see WHY a
lead scored what it scored. Never raises.
"""

from __future__ import annotations

import logging
import datetime as dt

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import BUSINESSES, CONTACTS
from app.store import business_contact_summary, upsert_leads

log = logging.getLogger(__name__)

EMAIL_POINTS = {"valid": 40, "unknown": 25, "unchecked": 15, "invalid": 0}
PHONE_POINTS = 20
SOCIAL_POINTS = 5
ADDRESS_POINTS = 10
WEBSITE_POINTS = 15
FRESH_14D = 10
FRESH_30D = 5


def _freshness_points(last_seen: dt.datetime | None) -> int:
    if last_seen is None:
        return 0
    age_days = (dt.datetime.utcnow() - last_seen).days
    if age_days <= 14:
        return FRESH_14D
    if age_days <= 30:
        return FRESH_30D
    return 0


def score_lead(summary: dict, business: dict) -> tuple[int, str]:
    """(score, breakdown) for one business. Pure function — no I/O."""
    parts: list[str] = []
    score = 0

    email = summary.get("email")
    if email:
        status = email[4] or "unknown"
        pts = EMAIL_POINTS.get(status, 0)
        score += pts
        parts.append(f"email:{status}={pts}")
    else:
        parts.append("email:none=0")

    if summary.get("phone"):
        score += PHONE_POINTS
        parts.append(f"phone:yes={PHONE_POINTS}")
    else:
        parts.append("phone:no=0")

    if summary.get("social"):
        score += SOCIAL_POINTS
        parts.append(f"social:yes={SOCIAL_POINTS}")
    if summary.get("address"):
        score += ADDRESS_POINTS
        parts.append(f"address:yes={ADDRESS_POINTS}")
    if business.get("domain"):
        score += WEBSITE_POINTS
        parts.append(f"website:yes={WEBSITE_POINTS}")
    score += _freshness_points(business.get("last_seen_at"))
    parts.append(f"fresh={_freshness_points(business.get('last_seen_at'))}")

    return min(score, 100), " ".join(parts)


def build_leads(engine: Engine, business_ids: list[int] | None = None) -> dict:
    """Rebuild leads from current contacts. Returns {new, updated, skipped}."""
    summaries = business_contact_summary(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                BUSINESSES.c.id,
                BUSINESSES.c.name,
                BUSINESSES.c.domain,
                BUSINESSES.c.last_seen_at,
            )
        ).mappings()
        businesses = {r["id"]: dict(r) for r in rows}

    leads: list[dict] = []
    skipped = 0
    for summary in summaries:
        bid = summary["business_id"]
        business = businesses.get(bid)
        if business is None:
            skipped += 1
            continue
        if business_ids is not None and bid not in business_ids:
            continue
        score, detail = score_lead(summary, business)
        email = summary.get("email")
        phone = summary.get("phone")
        leads.append(
            {
                "business_id": bid,
                "email_contact_id": email[0] if email else None,
                "phone_contact_id": phone[0] if phone else None,
                "best_email": email[3] if email else "",
                "best_phone": phone[3] if phone else "",
                "email_status": (email[4] if email else "unknown") or "unknown",
                "score": score,
                "score_detail": detail,
            }
        )
    result = upsert_leads(engine, leads)
    result["skipped"] = skipped
    log.info("leads rebuilt: %s", result)
    return result
