"""Heartbeat file mechanism (worker/scheduler liveness)."""

import time

from app.heartbeat import heartbeat_age_s, heartbeat_path, is_healthy, write_heartbeat


def test_write_and_read_heartbeat() -> None:
    path = write_heartbeat("testsvc", extra="value")
    assert path.is_file()
    payload = __import__("json").loads(path.read_text())
    assert payload["extra"] == "value"
    age = heartbeat_age_s("testsvc")
    assert age is not None and age < 5


def test_is_healthy_missing_service() -> None:
    assert is_healthy("no-such-service-xyz") is False


def test_is_healthy_stale(tmp_path, monkeypatch) -> None:
    write_heartbeat("stalesvc")
    # age the file beyond the threshold
    old = time.time() - 600
    path = heartbeat_path("stalesvc")
    __import__("os").utime(path, (old, old))
    assert is_healthy("stalesvc", max_age_s=90.0) is False
