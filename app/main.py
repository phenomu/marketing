"""FastAPI backend entrypoint.

Health endpoints only for now; business endpoints arrive with later phases
(see TRACKER.md). Same app object runs natively (uvicorn) and in the container.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import logging

import app
from app.db import check_db, get_engine
from config import settings
from config.logging_setup import setup_logging

log = logging.getLogger(__name__)

setup_logging("backend")

api = FastAPI(
    title="MARKETING API",
    version=app.__version__,
    # Swagger UI / ReDoc / OpenAPI schema only in development — the API is
    # read-internal (health probes + later dashboard endpoints); production
    # deployments should not expose an endpoint inventory.
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)


@api.get("/")
def root() -> dict:
    return {
        "app": "marketing",
        "version": app.__version__,
        "environment": settings.app_env,
        "docs": "/docs",
    }


@api.get("/health")
def health() -> dict:
    """Liveness: always 200 while the process serves; DB status is reported, not fatal."""
    db_up = check_db()
    return {
        "status": "ok",
        "version": app.__version__,  # freshness probe: reflects running code
        "environment": settings.app_env,
        "database": "up" if db_up else "down",
        "dry_run": settings.dry_run,
    }


@api.get("/ready")
def ready():
    """Readiness: 503 when the database is unreachable (used by compose healthchecks)."""
    if not check_db():
        return JSONResponse(
            status_code=503, content={"status": "not-ready", "database": "down"}
        )
    return {"status": "ready", "database": "up", "version": app.__version__}


# --- PHASE 6: one-click unsubscribe (public, unauthenticated by design) -----


@api.get("/unsubscribe")
def unsubscribe_get(token: str):
    """Landing page for the one-click unsubscribe link (no confirm click
    needed — one click, done; RFC 8058-style single-request opt-down)."""
    from app.outreach.bounce import process_unsubscribe_token

    try:
        email = process_unsubscribe_token(get_engine(), token)
    except Exception:  # noqa: BLE001 — DB down must not 500-crash the loop
        log.exception("unsubscribe GET failed")
        return JSONResponse(
            status_code=503, content={"status": "temporarily unavailable"}
        )
    if email is None:
        return JSONResponse(
            status_code=404, content={"status": "invalid or expired token"}
        )
    return JSONResponse(
        content={"status": "unsubscribed", "email": _mask_email(email)}
    )


@api.post("/unsubscribe")
def unsubscribe_post(token: str):
    """RFC 8058 one-click POST variant for mail clients that support it."""
    from app.outreach.bounce import process_unsubscribe_token

    try:
        email = process_unsubscribe_token(get_engine(), token)
    except Exception:  # noqa: BLE001 — DB down must not 500-crash the loop
        log.exception("unsubscribe POST failed")
        return JSONResponse(
            status_code=503, content={"status": "temporarily unavailable"}
        )
    if email is None:
        return JSONResponse(status_code=404, content={"status": "invalid token"})
    return JSONResponse(
        content={"status": "unsubscribed", "email": _mask_email(email)}
    )


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"
