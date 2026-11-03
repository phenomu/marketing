"""PHASE 9 auth layer tests (app.auth middleware + dashboard gate logic).

The middleware is exercised through the real FastAPI TestClient with
API_AUTH_TOKEN monkeypatched in the env source (settings `get` reads
real env first — os.environ is authoritative for containers).
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

import app.auth
from app.main import api

client = TestClient(api)


def _set_token(monkeypatch, value: str) -> None:
    monkeypatch.setattr(app.auth, "get", lambda k, d="": value if k == "API_AUTH_TOKEN" else d)
    # module-level middleware closure reads app.auth.auth_token at request
    # time — patch the token reader itself:
    monkeypatch.setattr(app.auth, "auth_token", lambda: value)


def test_auth_off_by_default(monkeypatch) -> None:
    _set_token(monkeypatch, "")
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["app"] == "marketing"


def test_auth_on_blocks_unauthenticated(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    r = client.get("/")
    assert r.status_code == 401
    assert r.json()["status"] == "unauthorized"


def test_auth_on_allows_x_auth_token_header(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    r = client.get("/", headers={"X-Auth-Token": "secret-token"})
    assert r.status_code == 200


def test_auth_on_allows_bearer_header(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    r = client.get("/", headers={"Authorization": "Bearer secret-token"})
    assert r.status_code == 200


def test_auth_rejects_wrong_token(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    r = client.get("/", headers={"X-Auth-Token": "wrong"})
    assert r.status_code == 401


def test_auth_rejects_empty_when_enabled(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    r = client.get("/", headers={"X-Auth-Token": ""})
    assert r.status_code == 401


def test_health_stays_public(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    assert client.get("/health").status_code == 200


def test_ready_stays_public(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    assert client.get("/ready").status_code in (200, 503)


def test_unsubscribe_stays_public(monkeypatch) -> None:
    # RFC 8058 / D-037: recipients click this from mail clients — no auth ever
    _set_token(monkeypatch, "secret-token")
    r = client.get("/unsubscribe", params={"token": "x"})
    # bad token value → 404 (invalid token path), NOT 401
    assert r.status_code == 404


def test_unsubscribe_post_stays_public(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    r = client.post("/unsubscribe", params={"token": "x"})
    assert r.status_code == 404


def test_trailing_slash_public(monkeypatch) -> None:
    _set_token(monkeypatch, "secret-token")
    # /health/ must still match the public set after normalization
    r = client.get("/health/")
    assert r.status_code == 200


def test_docs_blocked_in_prod_auth(monkeypatch) -> None:
    # docs are dev-only by APP_ENV; with auth on, non-public paths 401
    _set_token(monkeypatch, "secret-token")
    r = client.get("/docs")
    assert r.status_code in (401, 404)


def test_is_public_path_unit() -> None:
    assert app.auth.is_public_path("/health")
    assert app.auth.is_public_path("/health/")
    assert app.auth.is_public_path("/unsubscribe")
    assert not app.auth.is_public_path("/")
    assert not app.auth.is_public_path("/admin")
    assert not app.auth.is_public_path("/healthz")  # not a prefix match


def test_normalize_root() -> None:
    assert app.auth._normalize("/") == "/"
    assert app.auth._normalize("/a/") == "/a"
    assert app.auth._normalize("/a") == "/a"
