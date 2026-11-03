#!/usr/bin/env python3
"""MARKETING — service health monitor (PHASE 9).

Checks every component against its real signals (nothing fabricated):
  - api            GET /health (HTTP 200 = alive; DB status reported)
  - api readiness  GET /ready  (503 = DB unreachable)
  - dashboard      GET /_stcore/health (Streamlit internal health)
  - worker         heartbeat file freshness (app.heartbeat)
  - scheduler      heartbeat file freshness
  - db             direct connection via the app engine
  - disk           free space on the data/log volume path

Exit code: 0 all healthy, 1 any component failing — cron/monitoring can
alert on the exit code alone. `--json` prints machine-readable output.

Usage:
  python scripts/health_monitor.py
  python scripts/health_monitor.py --json
  python scripts/health_monitor.py --api http://10.0.0.5:8000
                                   --dashboard http://10.0.0.5:8501

Cron example (every 5 min, log + alert on failure):
  */5 * * * * cd /opt/marketing && python scripts/health_monitor.py \
      >> logs/monitor.log 2>&1 || echo "MARKETING DOWN" | mail -s alert ops@…
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

HEARTBEAT_MAX_AGE_S = 90.0  # worker/scheduler interval is 30/60s


def _check_api(base: str) -> dict:
    import httpx

    started = time.time()
    try:
        r = httpx.get(f"{base}/health", timeout=5.0)
        body = r.json() if r.status_code == 200 else {}
        return {
            "component": "api",
            "ok": r.status_code == 200,
            "detail": {
                "http": r.status_code,
                "database": body.get("database"),
                "environment": body.get("environment"),
                "latency_ms": round((time.time() - started) * 1000),
            },
        }
    except Exception as exc:  # noqa: BLE001 — report, never crash
        return {"component": "api", "ok": False, "detail": {"error": str(exc)[:120]}}


def _check_api_ready(base: str) -> dict:
    import httpx

    try:
        r = httpx.get(f"{base}/ready", timeout=5.0)
        return {
            "component": "api-ready",
            "ok": r.status_code == 200,
            "detail": {"http": r.status_code},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "component": "api-ready",
            "ok": False,
            "detail": {"error": str(exc)[:120]},
        }


def _check_dashboard(base: str) -> dict:
    import httpx

    try:
        r = httpx.get(f"{base}/_stcore/health", timeout=5.0)
        return {
            "component": "dashboard",
            "ok": r.status_code == 200 and r.text.strip() == "ok",
            "detail": {"http": r.status_code, "body": r.text.strip()[:20]},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "component": "dashboard",
            "ok": False,
            "detail": {"error": str(exc)[:120]},
        }


def _check_db() -> dict:
    from app.db import check_db

    ok = check_db()
    detail: dict = {"connected": ok}
    if ok:
        from sqlalchemy import text

        from app.db import get_engine

        try:
            with get_engine().connect() as conn:
                counts = {
                    t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                    for t in ("businesses", "contacts", "leads")
                }
            detail["rows"] = counts
        except Exception as exc:  # noqa: BLE001 — count is optional
            detail["rows_error"] = str(exc)[:120]
    return {"component": "db", "ok": ok, "detail": detail}


def _check_heartbeat(name: str) -> dict:
    from app.heartbeat import heartbeat_age_s

    age = heartbeat_age_s(name)
    ok = age is not None and age <= HEARTBEAT_MAX_AGE_S
    return {
        "component": name,
        "ok": ok,
        "detail": {
            "age_s": round(age, 1) if age is not None else None,
            "max_age_s": HEARTBEAT_MAX_AGE_S,
        },
    }


def _check_disk() -> dict:
    import shutil as _shutil

    from config import settings

    path = str(settings.log_dir)
    try:
        usage = _shutil.disk_usage(path)
        free_gb = usage.free / 1024**3
        return {
            "component": "disk",
            "ok": free_gb > 1.0,
            "detail": {"path": path, "free_gb": round(free_gb, 2), "min_free_gb": 1.0},
        }
    except Exception as exc:  # noqa: BLE001
        return {"component": "disk", "ok": False, "detail": {"error": str(exc)[:120]}}


def run_checks(api_base: str, dashboard_base: str, skip_http: bool) -> list[dict]:
    checks: list[dict] = []
    if skip_http:
        checks += [_check_db(), _check_disk()]
    else:
        checks = [
            _check_api(api_base),
            _check_api_ready(api_base),
            _check_dashboard(dashboard_base),
            _check_db(),
            _check_heartbeat("worker"),
            _check_heartbeat("scheduler"),
            _check_disk(),
        ]
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="MARKETING service health monitor")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--dashboard", default="http://127.0.0.1:8501")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="skip HTTP probes (db/heartbeat/disk only)",
    )
    args = parser.parse_args()

    checks = run_checks(args.api, args.dashboard, args.skip_http)
    all_ok = all(c["ok"] for c in checks)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    if args.json:
        print(
            json.dumps(
                {"timestamp": stamp, "ok": all_ok, "checks": checks},
                indent=2,
                default=str,
            )
        )
    else:
        print(f"[{stamp}] MARKETING health — {'ALL OK' if all_ok else 'FAILURES'}")
        for c in checks:
            mark = "OK  " if c["ok"] else "FAIL"
            print(f"  {mark} {c['component']:<10} {c['detail']}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
