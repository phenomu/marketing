"""Bounce handling (PHASE 6).

Plain-SMTP outbound has no inbound side (that is a provider webhook in
a later phase), so bounces arrive as imports: `email[,reason]` lines
from the SMTP provider's bounce export, via the CLI:

    python -m app.outreach_cli bounces --file data/bounces.csv

Hard bounces are permanent: suppression (reason=hard-bounce) + the
lead's status flips to `bounced` so no campaign ever selects it again.
Soft bounces (reason starting 'soft') only log — they are transient and
must NOT suppress.
"""

from __future__ import annotations

import logging

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.db import LEADS, SUPPRESSIONS, get_engine
from app.outreach.unsubscribe import _norm, make_token, verify_token  # noqa: F401

log = logging.getLogger(__name__)


def mark_bounces(
    engine: Engine, entries: list[tuple[str, str]], source: str = "import"
) -> dict:
    """Mark hard bounces. entries = [(email, reason), ...]. Never raises.

    reason "soft..." -> log only. Anything else (incl. empty) -> hard.
    """
    stats = {"hard": 0, "soft": 0, "skipped": 0}
    try:
        for email, reason in entries:
            email_n = _norm(email or "")
            if not email_n or "@" not in email_n:
                stats["skipped"] += 1
                continue
            if reason.strip().lower().startswith("soft"):
                stats["soft"] += 1
                log.info("soft bounce (no suppression): %s %s", email_n, reason)
                continue
            stats["hard"] += 1
            _suppress(engine, email_n, "hard-bounce", source)
            with engine.begin() as conn:
                conn.execute(
                    update(LEADS)
                    .where(LEADS.c.best_email == email_n)
                    .values(status="bounced")
                )
    except Exception as exc:  # noqa: BLE001 — import tool must not crash
        stats["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("bounce import failed: %s", exc)
    log.info("bounce import: %s", stats)
    return stats


def _suppress(engine: Engine, email_norm: str, reason: str, source: str) -> None:
    from sqlalchemy import insert

    try:
        with engine.begin() as conn:
            exists = conn.execute(
                select(SUPPRESSIONS.c.id).where(SUPPRESSIONS.c.email_norm == email_norm)
            ).scalar()
            if exists is None:
                conn.execute(
                    insert(SUPPRESSIONS).values(
                        email_norm=email_norm, reason=reason, source=source[:64]
                    )
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("suppress %s failed: %s", email_norm, exc)


def process_unsubscribe_token(engine: Engine, token: str) -> str | None:
    """Endpoint helper: verify token -> suppress the email + flip lead
    status. Returns the email on success, None on invalid token."""
    email = verify_token(token)
    if email is None:
        return None
    _suppress(engine, email, "unsubscribe", "link")
    with engine.begin() as conn:
        conn.execute(
            update(LEADS).where(LEADS.c.best_email == email).values(status="suppressed")
        )
    log.info("unsubscribe processed for %s", email)
    return email
