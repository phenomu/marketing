"""SMTP transport (PHASE 6).

Thin wrapper over smtplib with two hard guarantees:

1. DRY RUN unless explicitly disabled — `settings.dry_run` defaults to
   True and a live send additionally requires SMTP host/user/pass AND
   an explicit OUTREACH_SEND_LIVE=true env var (belt and suspenders:
   flipping DRY_RUN=false alone is not enough to leave the machine).
2. Never raises — the campaign runner treats failures as per-recipient
   events (`failed`), not crashes.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from config import settings

log = logging.getLogger(__name__)


def _live_armed() -> bool:
    """True only when DRY_RUN=false, SMTP creds complete, and the extra
    OUTREACH_SEND_LIVE=true arming flag is present."""
    if settings.dry_run:
        return False
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_pass):
        return False
    if not settings.outreach_send_live:
        return False
    return True


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


class SendResult:
    __slots__ = ("email", "status", "detail", "mode")

    def __init__(self, email: str, status: str, detail: str, mode: str):
        self.email = email
        self.status = status  # sent|sent-dry|failed
        self.detail = detail
        self.mode = mode  # dry|live


def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str,
    reply_to: str = "",
    extra_headers: dict[str, str] | None = None,
) -> SendResult:
    """Send (or dry-run) one email. Never raises."""
    headers = extra_headers or {}

    if not _live_armed():
        reason = "dry run (DRY_RUN=true)" if settings.dry_run else (
            "dry run (live not armed: needs DRY_RUN=false + SMTP creds + "
            "OUTREACH_SEND_LIVE=true)"
        )
        log.info("DRY SEND to=%s subject=%r", to_email, subject)
        return SendResult(to_email, "sent-dry", reason, "dry")

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((settings.sender_name, settings.smtp_user))
        msg["To"] = to_email
        msg["Message-ID"] = make_msgid()
        if reply_to:
            msg["Reply-To"] = reply_to
        for key, value in headers.items():
            msg[key] = value
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_s
        ) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.send_message(msg)
        return SendResult(to_email, "sent", "ok", "live")
    except Exception as exc:  # noqa: BLE001 — per-recipient failure, not a crash
        log.warning("send to %s failed: %s", to_email, exc)
        return SendResult(to_email, "failed", f"{type(exc).__name__}: {exc}", "live")


def smtp_configured() -> bool:
    """True when SMTP credentials are present (for dashboards/CLI)."""
    return _smtp_configured()
