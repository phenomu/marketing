"""Streamlit dashboard — minimal status page.

PHASE 7 builds the real lead/campaign views. This page proves the service
wiring: it reads the backend /health endpoint (BACKEND_URL) and shows it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
import streamlit as st  # noqa: E402

from config import settings  # noqa: E402

st.set_page_config(page_title="MARKETING Dashboard", page_icon="📊")

st.title("MARKETING Dashboard")
st.caption(
    f"environment: **{settings.app_env}** · dry_run: **{settings.dry_run}** · "
    f"backend: `{settings.backend_url}`"
)

try:
    response = requests.get(f"{settings.backend_url}/health", timeout=5)
    response.raise_for_status()
    health = response.json()
except Exception as exc:  # noqa: BLE001 — show offline state, never crash the page
    st.error(f"Backend tidak terjangkau: {exc}")
    st.stop()
else:
    left, middle, right = st.columns(3)
    left.metric("Backend version", health.get("version", "?"))
    middle.metric("Database", health.get("database", "?"))
    right.metric("DRY RUN", "ON" if health.get("dry_run") else "OFF")

    if health.get("database") != "up":
        st.warning("Database down — cek `docker compose ps` / logs.")
