"""FastAPI backend entrypoint.

Health endpoints only for now; business endpoints arrive with later phases
(see TRACKER.md). Same app object runs natively (uvicorn) and in the container.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import app
from app.db import check_db
from config import settings
from config.logging_setup import setup_logging

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
