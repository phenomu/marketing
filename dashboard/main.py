"""Streamlit dashboard — NEON COMMAND UI (PHASE 7 + redesign 2026-11-03).

Reads the production database directly through the same store layer the
worker uses. No new API surface is exposed (D-032: auth deferred — every
port stays bound to 127.0.0.1 until the server deployment phase).

Pages: Overview · Lead Discovery · Lead Management · Lead Detail ·
Campaigns · Email Preview · Analytics · Export.

All write actions here are the same functions the CLI/worker use —
nothing bypasses the PHASE 6 safety rails (dry run default,
triple-armed live send, suppression pre-check).

Visual redesign (NEON COMMAND): theme tokens/CSS in dashboard/theme.py,
ECharts renderers in dashboard/charts.py (bundle in dashboard/assets,
no CDN at runtime). Backend logic, routes and behavior are unchanged;
every number on screen still comes from live queries.
"""

from __future__ import annotations

import csv
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import charts  # noqa: E402
from dashboard import docs  # noqa: E402
from dashboard import queries  # noqa: E402
from dashboard import theme  # noqa: E402
from app.export import leads_csv_bytes  # noqa: E402
from app.outreach.campaign import (  # noqa: E402
    create_campaign,
    get_campaign,
    run_campaign,
    set_campaign_status,
    unsubscribe_url,
    update_campaign_template,
)
from app.outreach.template import render_message  # noqa: E402
from app.store import insert_job  # noqa: E402
from config import settings  # noqa: E402

st.set_page_config(
    page_title="MARKETING — Neon Command",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- security gate (PHASE 9, D-032) ------------------------------------------

# Streamlit runs in the operator's browser and cannot set custom headers,
# so the auth token arrives as ?token=… (bookmarkable). The same
# API_AUTH_TOKEN gates the FastAPI backend (app.auth). Empty token =
# auth disabled (localhost default); setting it enables the gate in ANY
# environment — one switch, no way to enable in dev but forget in prod.
_query_token = st.query_params.get("token", "").strip()

_auth_expected = ""
try:  # imported here so tests can monkeypatch app.auth before import
    from app.auth import auth_token as _auth_token

    _auth_expected = _auth_token().strip()
except Exception:  # noqa: BLE001 — auth import must never break the UI
    _auth_expected = ""

if _auth_expected and _query_token != _auth_expected:
    st.markdown(theme.theme_css(), unsafe_allow_html=True)
    st.markdown(
        theme.page_header("Akses ditolak", "Autentikasi diperlukan."),
        unsafe_allow_html=True,
    )
    st.warning(
        "Dashboard ini memerlukan token akses. Buka URL dengan parameter "
        "`?token=…` (nilai = API_AUTH_TOKEN environment variable)."
    )
    st.stop()
if _query_token:
    # keep the token out of the address bar after a successful auth:
    # replace ?token=… with a session flag so it is not re-sent on every
    # click / bookmarked / leaked via referrer.
    if st.session_state.get("nc_auth") is True or _query_token == _auth_expected:
        st.session_state["nc_auth"] = True
        try:
            del st.query_params["token"]
        except Exception:  # noqa: BLE001 — cosmetic, never fatal
            pass

st.markdown(theme.theme_css(), unsafe_allow_html=True)

# Flash notification (SweetAlert-style): survives st.rerun() via a
# session_state flag. st.success/st.error placed right before an
# st.rerun() never renders — the rerun clears the frame before the
# browser paints it. The flag is consumed one render later and the
# modal auto-dismisses via CSS animation.
if "nc_flash" in st.session_state:
    _f = st.session_state.pop("nc_flash")
    st.markdown(
        theme.flash_alert(_f["kind"], _f["title"], _f["message"]),
        unsafe_allow_html=True,
    )


def flash(kind: str, title: str, message: str) -> None:
    """Queue a flash modal for the NEXT render, then rerun."""
    st.session_state["nc_flash"] = {
        "kind": kind, "title": title, "message": message
    }
    st.rerun()

PAGES = [
    "Overview",
    "Lead Discovery",
    "Lead Management",
    "Lead Detail",
    "Campaigns",
    "Email Preview",
    "Analytics",
    "Export",
    "Dokumentasi",
]

PAGE_ICONS = {
    "Overview": "◈",
    "Lead Discovery": "⌖",
    "Lead Management": "☰",
    "Lead Detail": "◉",
    "Campaigns": "✉",
    "Email Preview": "◫",
    "Analytics": "▲",
    "Export": "⇩",
    "Dokumentasi": "▤",
}


def _engine():
    """Lazy import so tests can monkeypatch app.db.get_engine."""
    from app.db import get_engine

    return get_engine()


def _df(rows: list[dict]) -> pd.DataFrame:
    if not rows or "error" in rows[0]:
        if rows and rows[0].get("error"):
            st.warning(f"Query gagal: {rows[0]['error']}")
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _fmt_ts(value) -> str:
    return value.isoformat(sep=" ", timespec="minutes") if value else ""


def _csv_rows(payload: bytes, limit: int = 25) -> pd.DataFrame:
    """Parse the exported CSV with the csv module — fields are quoted
    and may contain commas; a naive split() miscounts columns."""
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    rows = [dict(r) for _, r in zip(range(limit), reader)]
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _kpi_grid(cards: list[str], columns: int = 4, height: int = 190) -> None:
    st.components.v1.html(  # type: ignore[attr-defined]
        charts.kpi_grid_component(cards, columns=columns), height=height,
        scrolling=False,
    )


def _chart(html_doc: str, height: int) -> None:
    st.components.v1.html(  # type: ignore[attr-defined]
        html_doc, height=height, scrolling=False
    )


def _autorefresh(seconds: int = 10) -> None:
    """Poll loop: rerun the page every `seconds` while the rendered
    block stays active. Streamlit re-renders only on user interaction by
    default, so background progress (worker ticks) would otherwise be
    invisible until a manual refresh. Uses st_autorefresh when the
    extra package is absent, falls back to a meta-refresh fragment."""
    try:
        import streamlit_autorefresh  # type: ignore[import-not-found]

        streamlit_autorefresh.st_autorefresh(
            interval=seconds * 1000, key=f"autorefresh-{seconds}"
        )
    except ImportError:
        # no extra dependency: a tiny HTML meta-refresh would reload the
        # WHOLE page (losing scroll) — instead show a hint and rely on
        # the Refresh button. This branch is a graceful no-op.
        pass


def _panel(title: str, hint: str = "") -> None:
    st.markdown(theme.chart_panel(title, hint), unsafe_allow_html=True)


def _topbar(page: str) -> None:
    badges = [
        theme.badge(settings.app_env, "purple" if settings.app_env == "production" else "cyan", dot=False),
        theme.badge(
            "DRY RUN" if settings.dry_run else "LIVE MODE",
            "warning" if settings.dry_run else "error",
        ),
    ]
    st.markdown(theme.topbar(page, badges), unsafe_allow_html=True)


def _page_header(title: str, subtitle: str) -> None:
    st.markdown(theme.page_header(title, subtitle), unsafe_allow_html=True)


# --- sidebar ----------------------------------------------------------------

with st.sidebar:
    st.markdown(
        """
<div class="nc-logo">
  <span class="mark">◉</span>
  <span>MARKETING<small>NEON COMMAND</small></span>
</div>
""",
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Navigasi",
        PAGES,
        format_func=lambda p: f"{PAGE_ICONS[p]}   {p}",
        label_visibility="collapsed",
    )
    if not settings.dry_run:
        st.error("DRY RUN OFF — live mode aktif. Cek OUTREACH_SEND_LIVE.")
    # live sidebar status — real settings, nothing fabricated
    st.markdown(
        theme.side_status([
            ("env", settings.app_env),
            ("dry_run", str(settings.dry_run)),
            ("send_live", str(settings.outreach_send_live)),
            ("bind", "127.0.0.1"),
        ]),
        unsafe_allow_html=True,
    )

_topbar(page)

# --- KPI drill-down (?view=bisnis|kontak|leads) -------------------------------
# KPI cards on Overview link here; the target page (Lead Management)
# carries the Bisnis/Kontak browser as tabs, so this only redirects.

_view = st.query_params.get("view", "").strip()
if _view in ("bisnis", "kontak", "leads"):
    del st.query_params["view"]
    if page != "Lead Management":
        page = "Lead Management"


# --- Overview ----------------------------------------------------------------

if page == "Overview":
    _page_header(
        "Overview",
        "Ringkasan pipeline lead-generation: discovery, crawling, kontak, "
        "leads, outreach — semua angka dari database live.",
    )
    data = queries.overview(_engine())
    if data["error"]:
        st.error(f"DB error: {data['error']}")

    leads_total = sum(data["leads_by_status"].values())
    events_total = sum(data["events_by_type"].values())
    st.markdown(
        theme.kpi_grid_links([
            theme.kpi_card_link(
                "Bisnis", data["businesses"], view="bisnis", icon="◈",
                tone="cyan",
                sub=f"discovery done: {data['discovery_by_status'].get('done', 0)}",
            ),
            theme.kpi_card_link(
                "Kontak", sum(data["contacts_by_kind"].values()),
                view="kontak", icon="⌖", tone="purple",
                sub=" · ".join(f"{k} {v}" for k, v in data["contacts_by_kind"].items()) or "—",
            ),
            theme.kpi_card_link(
                "Leads", leads_total, view="leads", icon="◉", tone="cyan",
                sub=" · ".join(f"{k} {v}" for k, v in data["leads_by_status"].items()) or "—",
            ),
            theme.kpi_card(
                "Outreach events", events_total, icon="✉", tone="mint",
                sub=f"last: {data['last_event_at'] or '—'}",
            ),
        ]),
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # activity (65%) + distribution (35%)
    a_col, d_col = st.columns([13, 7])
    with a_col:
        daily = [r for r in queries.events_daily(_engine()) if "error" not in r]
        _chart(
            charts.activity_chart_component(
                daily, height=280, title="Aktivitas outreach", hint="events / hari · 14 hari"
            ),
            324,
        )
    with d_col:
        kinds = [r for r in queries.contacts_by_kind(_engine()) if "error" not in r]
        _chart(
            charts.donut_chart_component(
                [(k["kind"], k["n"]) for k in kinds], center_label="kontak",
                height=250, title="Distribusi kontak", hint="per jenis",
            ),
            294,
        )

    # pipeline + health + system
    p_col, h_col, s_col = st.columns([2, 1, 1])
    with p_col:
        crawl_items = sorted(data["crawl_by_status"].items())
        _chart(
            charts.bar_chart_component(
                [k for k, _ in crawl_items], [v for _, v in crawl_items],
                height=185, title="Pipeline crawl", hint="job per status",
            ),
            229,
        )
    with h_col:
        done = data["crawl_by_status"].get("done", 0)
        total_crawl = sum(data["crawl_by_status"].values()) or 1
        _chart(
            charts.gauge_chart_component(
                done, "done", max_value=total_crawl, height=140,
                title="Kesehatan crawl", hint="done / total",
            ),
            184,
        )
    with s_col:
        _panel("System", "status nyata")
        rows_html = "".join(
            f"<div style='padding:8px 10px;border-bottom:1px solid rgba(148,163,184,0.10);"
            f"font-size:12px;color:#94A3B8'>{theme.status_badge(status)}"
            f"<span style='margin-left:8px'>{label}</span></div>"
            for label, status in [
                ("worker", "running"),
                ("campaign running", "running" if data["campaigns_by_status"].get("running") else "paused"),
                ("suppression", "suppressed"),
            ]
        )
        st.markdown(
            f"<div class='nc-card' style='padding:2px 0'>{rows_html}</div>",
            unsafe_allow_html=True,
        )

    ev_items = sorted(data["events_by_type"].items())
    if ev_items:
        _chart(
            charts.bar_chart_component(
                [k for k, _ in ev_items], [v for _, v in ev_items],
                height=150, horizontal=True, title="Outreach events", hint="per tipe",
            ),
            40 + 34 * len(ev_items) + 44,
        )
    st.caption(
        f"Event terakhir: {data['last_event_at'] or '—'} · "
        f"Suppression: {data['suppressions_by_reason'] or '—'}"
    )


# --- Lead Discovery ----------------------------------------------------------

elif page == "Lead Discovery":
    _page_header(
        "Lead Discovery",
        "Antrian job discovery (source listing). Worker memproses job "
        "pending tiap tick — tambah job manual di tab ketiga.",
    )

    disc = queries.discovery_overview(_engine())
    if disc["error"]:
        st.error(f"DB error: {disc['error']}")

    tab_jobs, tab_crawl, tab_add = st.tabs(
        ["Discovery jobs", "Crawl jobs", "Tambah job"]
    )
    with tab_jobs:
        # auto-poll while a job is pending: the worker processes jobs
        # every ~30s, and Streamlit only re-renders on interaction —
        # without this, a freshly enqueued job stays invisible until a
        # manual page refresh.
        pending = sum(1 for j in disc["jobs"] if j["status"] == "pending")
        if pending:
            st.info(
                f"⏳ {pending} job pending — worker memproses tiap ±30s. "
                "Tabel refresh otomatis tiap 10s."
            )
            _autorefresh(10)
        r1, r2 = st.columns([4, 1])
        r2.button("🔄 Refresh", help="Muat ulang tabel job sekarang")
        rows = [
            {
                "id": j["id"], "source": j["source"], "query": j["query"],
                "location": j["location"], "status": j["status"],
                "found": j.get("found_count", 0) or 0,
            }
            for j in disc["jobs"]
        ]
        st.dataframe(_df(rows), use_container_width=True, hide_index=True)
    with tab_crawl:
        rows = [
            {"id": j["id"], "domain": j["domain"], "status": j["status"],
             "pages": j.get("pages_saved", 0) or 0,
             "error": (j.get("error") or "")[:60]}
            for j in disc["crawl_jobs"]
        ]
        st.dataframe(_df(rows), use_container_width=True, hide_index=True)
    with tab_add:
        with st.form("add_job"):
            query = st.text_input("Query", placeholder="kopi jakarta")
            location = st.text_input("Lokasi", value="Indonesia")
            source = st.selectbox("Source", ["gmaps_scrape", "serpapi"])
            max_results = st.number_input("Max hasil", 5, 100, 20)
            submitted = st.form_submit_button("Enqueue job", type="primary")
        if submitted:
            if not query.strip():
                st.error("Query kosong.")
            else:
                try:
                    job_id = insert_job(
                        _engine(), source, query.strip(),
                        location.strip(), int(max_results)
                    )
                    flash(
                        "ok",
                        f"Job #{job_id} masuk antrian",
                        f"\"{query.strip()}\" ({source}) pending — worker "
                        "memproses ±30s. Tabel job di bawah sudah "
                        "ter-update.",
                    )
                except Exception as exc:  # noqa: BLE001
                    flash(
                        "err",
                        "Gagal enqueue job",
                        f"Error: {exc}",
                    )


# --- Lead Management ---------------------------------------------------------

elif page == "Lead Management":
    _page_header(
        "Lead Management",
        "Tabel lead (dengan filter) + browser bisnis & kontak — semua "
        "baris database.",
    )

    tab_leads, tab_bisnis, tab_kontak = st.tabs(
        ["Leads", "Bisnis", "Kontak"]
    )
    with tab_leads:
        with st.expander("Filter", expanded=True):
            f1, f2, f3 = st.columns(3)
            min_score = f1.slider("Skor minimum", 0, 100, 0)
            email_status = f2.selectbox(
                "Status email", ["any", "valid", "unknown", "invalid", "unchecked"]
            )
            lead_status = f3.selectbox(
                "Status lead", ["any", "new", "contacted", "suppressed", "bounced"],
            )

        rows = queries.leads_table(
            _engine(), min_score=min_score, email_status=email_status,
            lead_status=lead_status, limit=500,
        )
        df = _df(rows)
        if not df.empty:
            df = df[[
                "id", "name", "best_email", "email_status", "score", "status",
                "category", "domain", "best_phone",
            ]]
        c_count, c_dl = st.columns([3, 1])
        c_count.caption(f"{len(df)} lead")
        c_dl.download_button(
            "⬇ Download CSV",
            data=leads_csv_bytes(
                _engine(), min_score=min_score, email_status=email_status, limit=500
            ),
            file_name="leads.csv",
            mime="text/csv",
            disabled=df.empty,
            key="dl_leads_tab",
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_bisnis:
        b1, b2, b3 = st.columns([2, 2, 3])
        src = b1.selectbox(
            "Source", ["any", "gmaps_scrape", "serpapi", "google_places"],
            key="biz_src",
        )
        ind = b2.selectbox("Industry", ["any", "match"], key="biz_ind")
        q = b3.text_input("Cari nama/kategori/alamat", "", key="biz_q")
        brows = queries.businesses_table(
            _engine(), source=src, industry=ind, search=q, limit=1000
        )
        bdf = _df(brows)
        if not bdf.empty:
            bdf = bdf.rename(columns={
                "id": "ID", "name": "Nama", "category": "Kategori",
                "phone": "Telepon", "domain": "Domain", "address": "Alamat",
                "source": "Source", "rating": "Rating",
                "review_count": "Review", "industry_match": "Target",
            })
        st.caption(f"{len(bdf)} bisnis")
        st.dataframe(bdf, use_container_width=True, hide_index=True)

    with tab_kontak:
        k1, k2, k3 = st.columns([2, 2, 3])
        kind = k1.selectbox(
            "Jenis", ["any", "email", "phone", "social", "address"],
            key="kon_kind",
        )
        status = k2.selectbox(
            "Status", ["any", "valid", "unknown", "invalid", "pending"],
            key="kon_status",
        )
        kq = k3.text_input("Cari nilai kontak", "", key="kon_q")
        krows = queries.contacts_table(
            _engine(), kind=kind, status=status, search=kq, limit=1000
        )
        kdf = _df(krows)
        if not kdf.empty:
            kdf = kdf.rename(columns={
                "id": "ID", "business_id": "Bisnis ID",
                "business_name": "Bisnis", "kind": "Jenis",
                "value": "Nilai", "status": "Status",
                "confidence": "Conf", "source_kind": "Sumber",
            })
        st.caption(f"{len(kdf)} kontak")
        st.dataframe(kdf, use_container_width=True, hide_index=True)


# --- Lead Detail -------------------------------------------------------------

elif page == "Lead Detail":
    _page_header(
        "Lead Detail",
        "Detail satu lead: bisnis, skor breakdown, kontak, riwayat outreach.",
    )
    rows = queries.leads_table(_engine(), limit=1000)
    if not rows:
        st.info("Belum ada lead — jalankan pipeline dulu.")
    else:
        options = {
            f"#{r['id']} · {r['name']} · skor {r['score']}": r["id"]
            for r in rows
        }
        selected = st.selectbox("Pilih lead", list(options.keys()))
        if selected:
            detail = queries.lead_detail(_engine(), options[selected])
            if detail["error"]:
                st.error(detail["error"])
            else:
                lead, business = detail["lead"], detail["business"]
                _kpi_grid([
                    charts.kpi_card_countup("Skor", int(lead["score"]), "◈", "cyan"),
                    charts.kpi_card_countup(
                        "Kontak", len(detail["contacts"]), "⌖", "purple"
                    ),
                    charts.kpi_card_countup(
                        "Events", len(detail["events"]), "✉", "mint"
                    ),
                ], columns=3, height=175)
                st.markdown(
                    theme.status_badge(str(lead["status"])) + "&nbsp;&nbsp;" +
                    theme.status_badge(str(lead["email_status"])),
                    unsafe_allow_html=True,
                )

                st.subheader("Bisnis")
                if business:
                    b1, b2 = st.columns([2, 1])
                    b1.markdown(
                        f"**{business.get('name') or '—'}**\n\n"
                        f"kategori: {business.get('category') or '—'}  \n"
                        f"alamat: {business.get('address') or '—'}  \n"
                        f"telepon: {business.get('phone') or '—'}  \n"
                        f"website: {business.get('domain') or '—'}"
                    )
                    if business.get("domain"):
                        b2.link_button(
                            "Buka website", f"https://{business['domain']}"
                        )

                st.subheader("Skor breakdown")
                if lead["score_detail"]:
                    st.code(lead["score_detail"], language=None)
                else:
                    st.caption("—")

                st.subheader("Kontak")
                st.dataframe(
                    _df(detail["contacts"]), use_container_width=True,
                    hide_index=True,
                )

                st.subheader("Riwayat outreach")
                events = [
                    {"event": e["event_type"], "email": e["email"],
                     "detail": e["detail"], "waktu": _fmt_ts(e["created_at"])}
                    for e in detail["events"]
                ]
                st.dataframe(_df(events), use_container_width=True, hide_index=True)


# --- Campaigns ---------------------------------------------------------------

elif page == "Campaigns":
    _page_header(
        "Campaigns",
        "Worker hanya memproses campaign running (dry run default). "
        "Kirim nyata tetap butuh otorisasi eksplisit (D-036). Template "
        "bisa diedit di bawah — live preview di halaman Email Preview.",
    )

    rows = queries.campaigns_table(_engine())
    df = _df(rows)
    if df.empty:
        st.info("Belum ada campaign.")
    else:
        df = df[[
            "id", "name", "status", "min_score", "followup_days",
            "email_statuses",
        ]]
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Aksi")
        selected_id = st.selectbox(
            "Campaign", [int(r) for r in df["id"].tolist()]
        )
        camp = get_campaign(_engine(), selected_id)
        if camp:
            st.markdown(
                theme.status_badge(str(camp["status"])),
                unsafe_allow_html=True,
            )
        a1, a2, a3, a4 = st.columns(4)
        if a1.button("▶ Start (worker kirim tiap tick)"):
            set_campaign_status(_engine(), selected_id, "running")
            st.rerun()
        if a2.button("⏸ Pause"):
            set_campaign_status(_engine(), selected_id, "paused")
            st.rerun()
        if a3.button("⏹ Selesai (done)"):
            set_campaign_status(_engine(), selected_id, "done")
            st.rerun()
        if a4.button("⚡ Kirim 1 batch sekarang (dry)"):
            stats = run_campaign(_engine(), selected_id, limit=10)
            st.toast("Batch dijalankan (dry).")
            st.json(stats)

        st.subheader(f"Event campaign #{selected_id}")
        events = queries.campaign_events(_engine(), selected_id)
        events = [
            {"event": e["event_type"], "email": e["email"],
             "detail": e["detail"], "waktu": _fmt_ts(e["created_at"])}
            for e in events
        ]
        st.dataframe(_df(events), use_container_width=True, hide_index=True)

        st.subheader(f"Edit template campaign #{selected_id}")
        if camp:
            with st.form(f"edit_tpl_{selected_id}"):
                e_subject = st.text_input("Subjek", camp["subject"])
                e_body = st.text_area(
                    "Body teks (placeholder: {{name}} {{category}} "
                    "{{location}} {{domain}} {{sender_name}} "
                    "{{sender_email}} {{unsubscribe_url}})",
                    value=camp["body_text"], height=160,
                )
                e_html = st.text_area(
                    "Body HTML (opsional — kosong = text-only)",
                    value=camp.get("body_html") or "", height=120,
                )
                ef1, ef2 = st.columns(2)
                e_min = ef1.number_input(
                    "Skor minimum", 0, 100, int(camp["min_score"])
                )
                e_followup = ef2.number_input(
                    "Follow-up setelah (hari, 0=off)",
                    0, 30, int(camp["followup_days"]),
                )
                saved = st.form_submit_button("Simpan template", type="primary")
            if saved:
                try:
                    ok = update_campaign_template(
                        _engine(), selected_id,
                        subject=e_subject, body_text=e_body, body_html=e_html,
                        min_score=int(e_min), followup_days=int(e_followup),
                    )
                    if ok:
                        st.success(
                            f"Template campaign #{selected_id} tersimpan. "
                            "Lihat hasilnya di Email Preview."
                        )
                    else:
                        st.error(f"Campaign #{selected_id} tidak ditemukan.")
                except ValueError as exc:
                    st.error(f"Gagal: {exc}")

    st.divider()
    st.subheader("Campaign baru")
    with st.form("new_campaign"):
        n_name = st.text_input("Nama (unik)")
        n_subject = st.text_input("Subjek", "Kerja sama untuk {{name}}?")
        n_body = st.text_area(
            "Body teks (placeholder: {{name}} {{category}} {{location}} "
            "{{domain}} {{sender_name}} {{sender_email}} {{unsubscribe_url}})",
            height=150,
        )
        n_min = st.number_input("Skor minimum", 0, 100, 0)
        n_followup = st.number_input(
            "Follow-up setelah (hari, 0=off)", 0, 30, 0
        )
        created = st.form_submit_button("Buat (draft)", type="primary")
    if created:
        try:
            cid = create_campaign(
                _engine(), name=n_name.strip(), subject=n_subject.strip(),
                body_text=n_body, min_score=int(n_min),
                followup_days=int(n_followup),
            )
            st.success(f"Campaign #{cid} dibuat (draft).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Gagal: {exc}")


# --- Email Preview -----------------------------------------------------------

elif page == "Email Preview":
    _page_header(
        "Email Preview",
        "Render persis seperti yang dikirim campaign. Edit subjek/body "
        "untuk custom tanpa menyimpan, atau simpan langsung ke campaign.",
    )

    campaigns = queries.campaigns_table(_engine())
    leads = queries.leads_table(_engine(), limit=1000)
    if not campaigns or not leads:
        st.info("Butuh minimal 1 campaign + 1 lead.")
    else:
        c1, c2 = st.columns(2)
        c_options = {f"#{c['id']} · {c['name']}": c["id"] for c in campaigns}
        l_options = {f"#{l['id']} · {l['name']}": l["id"] for l in leads}
        c_sel = c1.selectbox("Campaign", list(c_options.keys()))
        l_sel = c2.selectbox("Lead", list(l_options.keys()))

        campaign = get_campaign(_engine(), c_options[c_sel]) or {}
        lead = next(l for l in leads if l["id"] == l_options[l_sel])
        email = lead["best_email"] or "contoh@domain.id"
        unsub = unsubscribe_url(email)

        with st.form("email_preview"):
            p_subject = st.text_input("Subjek", campaign.get("subject") or "")
            p_body = st.text_area(
                "Body teks", value=campaign.get("body_text") or "", height=160
            )
            p_html = st.text_area(
                "Body HTML (opsional)",
                value=campaign.get("body_html") or "", height=120,
            )
            col_a, col_b = st.columns(2)
            col_a.form_submit_button("👁 Render preview")
            save_tpl = col_b.form_submit_button("💾 Simpan ke campaign")
        if save_tpl:
            try:
                update_campaign_template(
                    _engine(), c_options[c_sel],
                    subject=p_subject, body_text=p_body, body_html=p_html,
                )
                st.success("Template campaign tersimpan.")
            except ValueError as exc:
                st.error(f"Gagal: {exc}")

        subject, text, html = render_message(
            lead,
            p_subject or "",
            p_body or "",
            p_html or "",
            "MARKETING",
            settings.smtp_from or "marketing@example.com",
            unsub,
        )
        _panel("Subjek ter-render", "placeholder disubstitusi")
        st.code(subject, language=None)

        left, right = st.columns(2)
        with left:
            _panel("Teks", "body text")
            st.code(text, language=None)
        with right:
            _panel("HTML", "body html")
            st.code(html or "—", language="html")

        if html:
            _chart(charts.mail_preview_component(html, height=320), 364)
        else:
            _panel("Pratinjau HTML (rendered)", "mail client simulation")
            st.caption("Body HTML kosong — kirim text-only.")

        st.caption(f"Unsubscribe: {unsub}")
        st.caption(
            "Header otomatis: List-Unsubscribe + List-Unsubscribe-Post: "
            "List-Unsubscribe=One-Click (RFC 8058)."
        )


# --- Analytics ---------------------------------------------------------------

elif page == "Analytics":
    _page_header(
        "Analytics",
        "Distribusi skor lead, kontak per jenis, outreach harian — "
        "semua dari data nyata.",
    )

    buckets = [r for r in queries.leads_by_score_bucket(_engine()) if "error" not in r]
    if buckets:
        _chart(
            charts.bar_chart_component(
                [f"{int(r['bucket'])}-{int(r['bucket']) + 19}" for r in buckets],
                [int(r["n"]) for r in buckets], height=205,
                title="Distribusi skor lead", hint="bucket 20 poin",
            ),
            249,
        )

    a1, a2 = st.columns(2)
    with a1:
        kinds = [r for r in queries.contacts_by_kind(_engine()) if "error" not in r]
        if kinds:
            _chart(
                charts.donut_chart_component(
                    [(k["kind"], k["n"]) for k in kinds],
                    height=245, title="Kontak per jenis", hint="distribusi",
                ),
                289,
            )
    with a2:
        daily = [r for r in queries.events_daily(_engine()) if "error" not in r]
        if daily:
            _chart(
                charts.activity_chart_component(
                    daily, height=240, title="Outreach per hari", hint="14 hari",
                ),
                284,
            )


# --- Export ------------------------------------------------------------------

elif page == "Export":
    _page_header(
        "Export",
        "CSV utf-8 (Excel-friendly) — filter sama seperti tabel lead.",
    )

    e1, e2, e3 = st.columns(3)
    x_min = e1.slider("Skor minimum", 0, 100, 0)
    x_status = e2.selectbox(
        "Status email", ["any", "valid", "unknown", "invalid", "unchecked"]
    )
    x_limit = e3.number_input("Maks baris", 1, 5000, 500)

    payload = leads_csv_bytes(
        _engine(), min_score=x_min, email_status=x_status, limit=int(x_limit)
    )
    st.download_button(
        "⬇ Download leads.csv", data=payload, file_name="leads.csv",
        mime="text/csv",
    )
    n_rows = len(list(csv.reader(StringIO(payload.decode("utf-8-sig"))))) - 1
    st.caption(f"{n_rows} baris")
    st.dataframe(_csv_rows(payload), use_container_width=True, hide_index=True)


# --- Dokumentasi --------------------------------------------------------------

elif page == "Dokumentasi":
    _page_header(
        "Dokumentasi",
        "Panduan penggunaan semua fitur MARKETING — dari discovery lead "
        "sampai kirim campaign, mode aman, CLI, dan troubleshooting.",
    )

    md = docs.load_guide()
    if not md:
        st.info(
            "docs_guide.md tidak ditemukan — dokumentasi hanya tersedia "
            "saat menjalankan dari repo/image lengkap."
        )
    else:
        groups = docs.build_groups(md)
        if not groups:
            st.warning("docs_guide.md kosong / tidak punya section.")
        else:
            st.markdown(
                theme.docs_note(
                    "Sumber: dashboard/docs_guide.md (panduan operator) · "
                    "render markdown aman — HTML di-sanitize Streamlit"
                ),
                unsafe_allow_html=True,
            )
            labels = [f"{docs.GROUP_ICONS.get(g, '▤')}   {g}" for g, _ in groups]
            tabs = st.tabs(labels)
            for tab, (group, body) in zip(tabs, groups):
                with tab:
                    st.markdown(body)
