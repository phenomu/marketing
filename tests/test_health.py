"""API health/readiness endpoint tests."""

from fastapi.testclient import TestClient

import app
from app.main import api

client = TestClient(api)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "marketing"
    assert body["version"] == app.__version__


def test_health_is_liveness() -> None:
    """Liveness must stay 200 even when the DB is unreachable."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # version comes from the running code, not a hardcoded string (freshness probe)
    assert body["version"] == app.__version__
    assert body["database"] in {"up", "down"}


def test_ready_is_503_when_db_down(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_db", lambda: False)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "down"


def test_ready_is_200_when_db_up(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_db", lambda: True)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
