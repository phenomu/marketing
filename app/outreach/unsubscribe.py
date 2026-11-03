"""One-click unsubscribe (PHASE 6).

Token = base64url(email) + "." + hex(hmac-sha256(secret, email))[:16].

Deterministic and stateless — no token storage; the suppressions table
is the only state. The public endpoint lives in app/main.py
(GET/POST /unsubscribe?token=...). Tokens never expire: an unsubscribe
link must work forever, not just for the campaign that sent it.

Production MUST set UNSUBSCRIBE_SECRET (env). Dev fallback derives a
stable secret from the database URL so tokens survive restarts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from config import settings

log = logging.getLogger(__name__)


def _secret() -> bytes:
    secret = settings.unsubscribe_secret
    if not secret:
        secret = hashlib.sha256(settings.database_url.encode()).hexdigest()
        log.debug("UNSUBSCRIBE_SECRET unset — using DB-derived dev secret")
    return secret.encode()


def _norm(email: str) -> str:
    return email.strip().lower()


def make_token(email: str) -> str:
    payload = base64.urlsafe_b64encode(_norm(email).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), _norm(email).encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def verify_token(token: str) -> str | None:
    """Return the email if the token signature is valid, else None.
    Never raises — malformed input is just an invalid token."""
    try:
        payload, _, sig = token.partition(".")
        if not payload or not sig:
            return None
        padding = "=" * (-len(payload) % 4)
        email = base64.urlsafe_b64decode(payload + padding).decode("utf-8", errors="strict")
        email = _norm(email)
        expected = hmac.new(_secret(), email.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        if len(email) > 320 or "@" not in email:
            return None
        return email
    except Exception:  # noqa: BLE001 — invalid token, not an error
        return None
