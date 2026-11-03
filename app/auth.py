"""API authentication layer (PHASE 9, D-032).

Opt-in token auth for the FastAPI backend. Disabled by default (empty
API_AUTH_TOKEN) — safe for local dev where every port binds 127.0.0.1.
Enable on any deployment that exposes a port beyond localhost.

Design:
- PUBLIC_PATHS stay reachable without a token: /health and /ready are
  probed by infrastructure (compose healthchecks, monitoring, uptime
  robots) that cannot carry credentials; /unsubscribe is clicked by
  email RECIPIENTS and must never require auth (RFC 8058 compliance —
  D-037).
- Token is read from the environment at request time (not frozen into
  Settings) so tests can monkeypatch it and rotations apply without
  a restart of the import-time value.
- Constant-time comparison (secrets.compare_digest) — no timing leak.
- The token is NEVER logged; denied attempts log path + client only.
- Accepted headers: X-Auth-Token: <token> or Authorization: Bearer <token>.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from config import get

log = logging.getLogger(__name__)

#: paths that stay public when auth is enabled (exact match, root-level)
PUBLIC_PATHS: frozenset[str] = frozenset({"/health", "/ready", "/unsubscribe"})


def auth_token() -> str:
    """Current API token (env API_AUTH_TOKEN); empty string = auth off."""
    return get("API_AUTH_TOKEN", "").strip()


def auth_enabled() -> bool:
    return bool(auth_token())


def _normalize(path: str) -> str:
    """Exact-match normalization: drop query string, collapse a single
    trailing slash ('/health/' -> '/health'); root stays '/'."""
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def is_public_path(path: str) -> bool:
    return _normalize(path) in PUBLIC_PATHS


def _extract_provided_token(request: Request) -> str:
    header = request.headers.get("x-auth-token", "").strip()
    if header:
        return header
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _token_matches(provided: str, expected: str) -> bool:
    return bool(provided) and bool(expected) and secrets.compare_digest(
        provided, expected
    )


async def auth_middleware(request: Request, call_next):
    """FastAPI http middleware: 401 unless a valid token is presented
    on non-public paths. No-op when API_AUTH_TOKEN is unset."""
    expected = auth_token()
    if not expected:
        return await call_next(request)

    path = _normalize(request.url.path)
    if path in PUBLIC_PATHS:
        return await call_next(request)

    provided = _extract_provided_token(request)
    if _token_matches(provided, expected):
        return await call_next(request)

    client = request.client.host if request.client else "?"
    log.warning("auth: denied %s from %s", path, client)
    return JSONResponse(
        status_code=401,
        content={"status": "unauthorized", "hint": "X-Auth-Token or Bearer"},
    )
