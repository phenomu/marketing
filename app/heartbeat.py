"""Heartbeat files for non-HTTP services (worker, scheduler).

Each loop writes logs/heartbeat/<name>.json; compose healthchecks verify
freshness via scripts/heartbeat_check.py. Works identically native and in
containers (both write under the mounted logs volume).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from config import settings


def heartbeat_path(name: str) -> Path:
    return settings.log_dir / "heartbeat" / f"{name}.json"


def write_heartbeat(name: str, **extra: object) -> Path:
    path = heartbeat_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), "pid": os.getpid(), **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def heartbeat_age_s(name: str) -> float | None:
    path = heartbeat_path(name)
    if not path.is_file():
        return None
    return max(0.0, time.time() - path.stat().st_mtime)


def is_healthy(name: str, max_age_s: float = 90.0) -> bool:
    age = heartbeat_age_s(name)
    return age is not None and age <= max_age_s
