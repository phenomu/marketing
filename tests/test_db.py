"""Database layer tests — run against the test SQLite DB (see conftest.py)."""

from sqlalchemy import text

from app.db import SCHEMA_VERSION, check_db, get_engine, init_db


def test_check_db() -> None:
    assert check_db() is True


def test_init_db_idempotent_and_stamps_version() -> None:
    init_db()
    init_db()  # second run must not fail or duplicate
    with get_engine().connect() as conn:
        value = conn.execute(
            text("SELECT value FROM app_meta WHERE key = 'schema_version'")
        ).scalar()
    assert value == SCHEMA_VERSION
