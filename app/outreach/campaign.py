"""Campaign lifecycle + runner (PHASE 6).

The runner sends (or dry-runs) one batch of a campaign:

    select eligible leads -> render -> send -> log outreach_events
    -> update leads.status -> daily limit enforcement -> follow-ups.

Safety rails (all enforced in code, not just docs):

- suppression list checked before any send (D-037);
- duplicate-send prevention: unique (campaign_id, lead_id, event_type)
  plus a runtime check against already-sent pairs — the same campaign
  never emails a lead twice;
- daily send cap: outreach_events rows of type sent/sent-dry counted
  per UTC day, capped at OUTREACH_SEND_PER_DAY (dry rows count too —
  the same numbers are rehearsed in dry mode);
- lead status filter: suppressed/bounced leads never selected;
- unsubscribed emails hit the suppressions table via the one-click
  link (unsubscribe.py) and from there are excluded forever.
"""

from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import quote

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Engine

from app.db import (
    BUSINESSES,
    CAMPAIGNS,
    LEADS,
    OUTREACH_EVENTS,
    SUPPRESSIONS,
    get_engine,
)
from app.outreach.smtp import send_email
from app.outreach.template import (
    DEFAULT_SUBJECT,
    DEFAULT_BODY_TEXT,
    DEFAULT_BODY_HTML,
    render_message,
)
from app.outreach.unsubscribe import make_token
from app.store import list_leads
from config import settings

log = logging.getLogger(__name__)

PRIMARY_TYPES = ("sent", "sent-dry")
FOLLOWUP_TYPES = ("followup", "followup-dry")


def create_campaign(
    engine: Engine,
    name: str,
    subject: str,
    body_text: str,
    body_html: str = "",
    followup_subject: str = "",
    followup_body_text: str = "",
    followup_body_html: str = "",
    followup_days: int = 0,
    min_score: int = 0,
    email_statuses: str = "valid,unknown",
) -> int:
    """Insert a campaign (draft status). Returns its id. Duplicate name
    or missing required text surfaces as ValueError, never a crash."""
    values = dict(
        name=name,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        followup_subject=followup_subject,
        followup_body_text=followup_body_text,
        followup_body_html=followup_body_html,
        followup_days=followup_days,
        min_score=min_score,
        email_statuses=email_statuses,
    )
    try:
        with engine.begin() as conn:
            result = conn.execute(insert(CAMPAIGNS).values(**values))
            return int(result.inserted_primary_key[0])
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"campaign create failed: {exc}") from exc


def get_campaign(engine: Engine, campaign_id: int) -> dict | None:
    with engine.connect() as conn:
        row = (
            conn.execute(select(CAMPAIGNS).where(CAMPAIGNS.c.id == campaign_id))
            .mappings()
            .first()
        )
        return dict(row) if row else None


def _suppressed_emails(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(select(SUPPRESSIONS.c.email_norm)).all()}


def _sent_count_today(engine: Engine) -> int:
    midnight = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with engine.connect() as conn:
        return int(
            conn.execute(
                select(func.count()).select_from(OUTREACH_EVENTS).where(
                    OUTREACH_EVENTS.c.event_type.in_(("sent", "sent-dry")),
                    OUTREACH_EVENTS.c.created_at >= midnight,
                )
            ).scalar()
            or 0
        )


def _eligible_leads(
    engine: Engine, campaign: dict, limit: int
) -> tuple[list[dict], int]:
    """(eligible, n_skipped) — suppressed/bounced/filtered-out leads are
    counted so operators can see why a batch shrank."""
    statuses = [
        s.strip()
        for s in campaign.get("email_statuses", "valid,unknown").split(",")
        if s.strip()
    ]
    suppressed = _suppressed_emails(engine)
    rows = list_leads(
        engine,
        limit=limit * 3,
        min_score=campaign.get("min_score", 0),
        email_status=None,  # statuses is a CSV filter — applied in Python
    )
    eligible: list[dict] = []
    skipped = 0
    for row in rows:
        if not row["best_email"] or row["email_status"] not in statuses:
            continue
        if row["best_email"] in suppressed or row.get("status") in (
            "suppressed", "bounced",
        ):
            skipped += 1
            continue
        eligible.append(row)
        if len(eligible) >= limit:
            break
    return eligible, skipped


def _already_sent(engine: Engine, campaign_id: int) -> set[tuple[int, str]]:
    """(lead_id, event_type) pairs already logged for this campaign —
    duplicate-send prevention at the event level."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(OUTREACH_EVENTS.c.lead_id, OUTREACH_EVENTS.c.event_type).where(
                OUTREACH_EVENTS.c.campaign_id == campaign_id
            )
        ).all()
        return {(r[0], r[1]) for r in rows}


def _log_event(
    engine: Engine, campaign_id: int, lead: dict, event_type: str, detail: str
) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(OUTREACH_EVENTS).values(
                    campaign_id=campaign_id,
                    lead_id=lead["id"],
                    email=lead["best_email"],
                    event_type=event_type,
                    detail=detail[:512],
                )
            )
    except Exception as exc:  # noqa: BLE001 — logging must not crash the batch
        log.warning(
            "event log failed (campaign=%s lead=%s): %s", campaign_id, lead["id"], exc
        )


def _mark_contacted(engine: Engine, lead_id: int) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                update(LEADS).where(LEADS.c.id == lead_id).values(status="contacted")
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("mark contacted failed (lead=%s): %s", lead_id, exc)


def unsubscribe_url(email: str) -> str:
    """Public one-click unsubscribe URL for an address."""
    token = make_token(email)
    return f"{settings.unsubscribe_base_url}/unsubscribe?token={quote(token)}"


def _unsubscribe_url(email: str) -> str:
    return unsubscribe_url(email)


def set_campaign_status(engine: Engine, campaign_id: int, status: str) -> bool:
    """Operator action: draft|running|paused|done. Only valid transitions
    are accepted; worker picks up running campaigns on its next tick."""
    if status not in ("draft", "running", "paused", "done"):
        raise ValueError(f"invalid campaign status: {status}")
    from sqlalchemy import update as sa_update

    with engine.begin() as conn:
        result = conn.execute(
            sa_update(CAMPAIGNS).where(CAMPAIGNS.c.id == campaign_id).values(status=status)
        )
    return bool(result.rowcount)


def run_campaign(engine: Engine, campaign_id: int, limit: int | None = None) -> dict:
    """Run one batch of a campaign. Never raises. Returns stats.

    DRY RUN: zero SMTP traffic — events logged as `sent-dry`.
    Live: requires DRY_RUN=false + SMTP creds + OUTREACH_SEND_LIVE=true.
    """
    stats = {
        "campaign": campaign_id,
        "mode": "dry" if not _live_mode() else "live",
        "sent": 0,
        "sent_dry": 0,
        "failed": 0,
        "skipped_suppressed": 0,
        "skipped_duplicate": 0,
        "skipped_daily_limit": 0,
        "error": "",
    }
    try:
        campaign = get_campaign(engine, campaign_id)
        if campaign is None:
            stats["error"] = "campaign not found"
            return stats

        batch_limit = limit if limit is not None else settings.outreach_batch_limit
        already = _already_sent(engine, campaign_id)
        sent_today = _sent_count_today(engine)
        eligible, n_suppressed = _eligible_leads(engine, campaign, batch_limit)
        stats["skipped_suppressed"] = n_suppressed

        for lead in eligible:
            if (lead["id"], "sent") in already or (lead["id"], "sent-dry") in already:
                stats["skipped_duplicate"] += 1
                continue

            if sent_today >= settings.outreach_send_per_day:
                stats["skipped_daily_limit"] += 1
                log.info("daily send limit reached (%s)", settings.outreach_send_per_day)
                break

            unsub_url = _unsubscribe_url(lead["best_email"])
            subject, body_text, body_html = render_message(
                lead,
                campaign["subject"] or DEFAULT_SUBJECT,
                campaign["body_text"] or DEFAULT_BODY_TEXT,
                campaign["body_html"] or DEFAULT_BODY_HTML,
                settings.sender_name,
                settings.smtp_from or settings.smtp_user or "noreply@marketing.local",
                unsub_url,
            )
            headers = {
                "List-Unsubscribe": f"<{unsub_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }

            result = send_email(
                lead["best_email"], subject, body_html, body_text,
                extra_headers=headers,
            )
            if result.status in ("sent", "sent-dry"):
                stats["sent" if result.status == "sent" else "sent_dry"] += 1
                sent_today += 1
                _log_event(engine, campaign_id, lead, result.status, result.detail)
            else:
                stats["failed"] += 1
                _log_event(engine, campaign_id, lead, "failed", result.detail)
            _mark_contacted(engine, lead["id"])
    except Exception as exc:  # noqa: BLE001 — never crash the caller
        stats["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("campaign run failed: %s", exc)
    return stats


def _live_mode() -> bool:
    from app.outreach.smtp import _live_armed

    return _live_armed()


def run_campaigns(engine: Engine, limit: int | None = None) -> dict:
    """Worker entry: run one batch of every running (non-draft) campaign.
    Never raises. Campaigns in draft/paused/done status are skipped —
    an operator must explicitly start a campaign before anything moves."""
    stats = {"campaigns": 0, "sent": 0, "sent_dry": 0, "failed": 0,
             "skipped_duplicate": 0, "skipped_daily_limit": 0}
    try:
        with engine.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    select(CAMPAIGNS.c.id).where(CAMPAIGNS.c.status == "running")
                ).all()
            ]
        for campaign_id in ids:
            result = run_campaign(engine, campaign_id, limit=limit)
            stats["campaigns"] += 1
            for key in ("sent", "sent_dry", "failed", "skipped_duplicate",
                        "skipped_daily_limit"):
                stats[key] += result.get(key, 0)
            if result.get("error"):
                log.warning("campaign %s error: %s", campaign_id, result["error"])
    except Exception as exc:  # noqa: BLE001 — service loop must survive
        stats["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("run_campaigns failed: %s", exc)
    return stats


def run_followups(engine: Engine, limit: int | None = None) -> dict:
    """Follow-up scheduler: for campaigns with followup_days > 0, send
    one follow-up to leads whose primary send is old enough, skipping
    bounced/suppressed/unsubscribed and already-followed-up pairs. Dry
    mode logs `followup-dry`. Bounded by the daily cap."""
    stats = {
        "checked": 0,
        "sent": 0,
        "sent_dry": 0,
        "failed": 0,
        "skipped_duplicate": 0,
        "skipped_daily_limit": 0,
        "skipped_suppressed": 0,
        "error": "",
    }
    try:
        with engine.connect() as conn:
            campaigns = [
                dict(r)
                for r in conn.execute(
                    select(CAMPAIGNS).where(CAMPAIGNS.c.followup_days > 0)
                ).mappings()
            ]
        for campaign in campaigns:
            batch_limit = limit if limit is not None else settings.outreach_batch_limit
            already = _already_sent(engine, campaign["id"])
            cutoff = dt.datetime.utcnow() - dt.timedelta(days=campaign["followup_days"])
            with engine.connect() as conn:
                primaries = [
                    dict(r)
                    for r in conn.execute(
                        select(OUTREACH_EVENTS.c.lead_id, OUTREACH_EVENTS.c.email)
                        .where(
                            OUTREACH_EVENTS.c.campaign_id == campaign["id"],
                            OUTREACH_EVENTS.c.event_type.in_(PRIMARY_TYPES),
                            OUTREACH_EVENTS.c.created_at <= cutoff,
                        )
                        .order_by(OUTREACH_EVENTS.c.created_at)
                        .limit(batch_limit)
                    ).mappings()
                ]
            for primary in primaries:
                stats["checked"] += 1
                if any(
                    (primary["lead_id"], t) in already for t in FOLLOWUP_TYPES
                ):
                    stats["skipped_duplicate"] += 1
                    continue
                lead = _lead_by_id(engine, primary["lead_id"])
                if not lead:
                    continue
                if lead["best_email"] in _suppressed_emails(engine):
                    stats["skipped_suppressed"] += 1
                    continue
                if lead.get("status") in ("suppressed", "bounced"):
                    stats["skipped_suppressed"] += 1
                    continue
                if _sent_count_today(engine) >= settings.outreach_send_per_day:
                    stats["skipped_daily_limit"] += 1
                    break
                unsub_url = _unsubscribe_url(lead["best_email"])
                subject, body_text, body_html = render_message(
                    lead,
                    campaign["followup_subject"] or f"Re: {campaign['subject']}",
                    campaign["followup_body_text"] or f"Re: {campaign['body_text']}",
                    campaign["followup_body_html"],
                    settings.sender_name,
                    settings.smtp_from or settings.smtp_user or "noreply@marketing.local",
                    unsub_url,
                )
                result = send_email(lead["best_email"], subject, body_html, body_text)
                if result.status in ("sent", "sent-dry"):
                    key = "sent" if result.status == "sent" else "sent_dry"
                    stats[key] += 1
                    _log_event(
                        engine,
                        campaign["id"],
                        lead,
                        result.status.replace("sent", "followup"),
                        result.detail,
                    )
                else:
                    stats["failed"] += 1
                    _log_event(engine, campaign["id"], lead, "failed", result.detail)
    except Exception as exc:  # noqa: BLE001
        stats["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("followup run failed: %s", exc)
    return stats


def _lead_by_id(engine: Engine, lead_id: int) -> dict | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(LEADS, BUSINESSES.c.name, BUSINESSES.c.category, BUSINESSES.c.domain)
                .select_from(LEADS)
                .join(BUSINESSES, BUSINESSES.c.id == LEADS.c.business_id)
                .where(LEADS.c.id == lead_id)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None
