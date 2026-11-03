"""Streamlit dashboard — real data views (PHASE 7).

Reads the production database directly through the same store layer the
worker uses. No new API surface is exposed (D-032: auth deferred — every
port stays bound to 127.0.0.1 until the server deployment phase).

Pages: Overview · Lead Discovery · Lead Management · Lead Detail ·
Campaigns · Email Preview · Analytics · Export.

All write actions here are the same functions the CLI/worker use —
nothing bypasses the PHASE 6 safety rails (dry run default, triple-armed
live send, suppression pre-check).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard import queries  # noqa: E402
from app.export import leads_csv_bytes  # noqa: E402
from app.outreach.campaign import (  # noqa: E402
    create_campaign,
    get_campaign,
    run_campaign,
    set_campaign_status,
    unsubscribe_url,
)
from app.outreach.template import render_message  # noqa: E402
from app.store import insert_job  # noqa: E402
from config import settings  # noqa: E402

st.set_page_config(page_title="MARKETING Dashboard", page_icon="📊", layout="wide")

PAGES = [
    "Overview",
    "Lead Discovery",
    "Lead Management",
    "Lead Detail",
    "Campaigns",
    "Email Preview",
    "Analytics",
    "Export",
]


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


# --- sidebar ----------------------------------------------------------------

st.sidebar.title("MARKETING")
st.sidebar.caption(
    f"env: {settings.app_env} · dry_run: {settings.dry_run}"
)
if not settings.dry_run:
    st.sidebar.error("DRY RUN OFF — live mode aktif. Cek OUTREACH_SEND_LIVE.")
page = st.sidebar.radio("Navigasi", PAGES, label_visibility="collapsed")


# --- Overview ----------------------------------------------------------------

if page == "Overview":
    st.title("Overview")
    data = queries.overview(_engine())
    if data["error"]:
        st.error(f"DB error: {data['error']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bisnis", data["businesses"])
    c2.metric("Kontak", sum(data["contacts_by_kind"].values()))
    c3.metric("Leads", sum(data["leads_by_status"].values()))
    c4.metric("Suppression", data["suppressions"])

    left, mid, right = st.columns(3)
    left.subheader("Status lead")
    left.table(pd.DataFrame(
        {"status": list(data["leads_by_status"]),
         "n": list(data["leads_by_status"].values())}
    ))
    mid.subheader("Status email")
    mid.table(pd.DataFrame(
        {"status": list(data["email_statuses"]),
         "n": list(data["email_statuses"].values())}
    ))
    right.subheader("Campaign")
    right.table(pd.DataFrame(
        {"status": list(data["campaigns_by_status"]),
         "n": list(data["campaigns_by_status"].values())}
    ))

    st.subheader("Pipeline")
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("Crawl selesai", data["crawl_by_status"].get("done", 0))
    pc2.metric("Crawl pending", data["crawl_by_status"].get("pending", 0))
    pc3.metric("Crawl gagal", data["crawl_by_status"].get("failed", 0))

    st.subheader("Outreach events")
    ev = pd.DataFrame(
        {"event": list(data["events_by_type"]),
         "n": list(data["events_by_type"].values())}
    )
    st.table(ev)
    st.caption(
        f"Event terakhir: {data['last_event_at'] or '—'} · "
        f"Suppression: {data['suppressions_by_reason'] or '—'}"
    )


# --- Lead Discovery ----------------------------------------------------------

elif page == "Lead Discovery":
    st.title("Lead Discovery")
    st.caption(
        "Antrian job discovery (source listing). Worker memproses job "
        "`pending` tiap tick. Tambah job manual di bawah — idempoten "
        "dicover oleh last_job_per_search saat enqueue scheduler."
    )

    disc = queries.discovery_overview(_engine())
    if disc["error"]:
        st.error(f"DB error: {disc['error']}")

    tab_jobs, tab_crawl, tab_add = st.tabs(
        ["Discovery jobs", "Crawl jobs", "Tambah job"]
    )
    with tab_jobs:
        rows = [
            {
                "id": j["id"], "source": j["source"], "query": j["query"],
                "location": j["location"], "status": j["status"],
                "found": j.get("found_count", 0) or 0,
            }
            for j in disc["jobs"]
        ]
        st.dataframe(_df(rows), use_container_width=True)
    with tab_crawl:
        rows = [
            {"id": j["id"], "domain": j["domain"], "status": j["status"],
             "pages": j.get("pages_saved", 0) or 0}
            for j in disc["crawl_jobs"]
        ]
        st.dataframe(_df(rows), use_container_width=True)
    with tab_add:
        with st.form("add_job"):
            query = st.text_input("Query", placeholder="kopi jakarta")
            location = st.text_input("Lokasi", value="Indonesia")
            source = st.selectbox("Source", ["gmaps_scrape", "serpapi"])
            max_results = st.number_input("Max hasil", 5, 100, 20)
            submitted = st.form_submit_button("Enqueue job")
        if submitted:
            if not query.strip():
                st.error("Query kosong.")
            else:
                try:
                    job_id = insert_job(
                        _engine(), source, query.strip(), location.strip(), int(max_results)
                    )
                    st.success(f"Job #{job_id} pending — worker proses tick berikutnya.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Gagal: {exc}")


# --- Lead Management ---------------------------------------------------------

elif page == "Lead Management":
    st.title("Lead Management")

    f1, f2, f3 = st.columns(3)
    min_score = f1.slider("Skor minimum", 0, 100, 0)
    email_status = f2.selectbox(
        "Status email", ["any", "valid", "unknown", "invalid", "unchecked"]
    )
    lead_status = f3.selectbox(
        "Status lead", ["any", "new", "contacted", "suppressed", "bounced"]
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
    st.caption(f"{len(df)} lead")
    st.dataframe(df, use_container_width=True)

    st.download_button(
        "Download CSV",
        data=leads_csv_bytes(
            _engine(), min_score=min_score, email_status=email_status, limit=500
        ),
        file_name="leads.csv",
        mime="text/csv",
        disabled=df.empty,
    )


# --- Lead Detail -------------------------------------------------------------

elif page == "Lead Detail":
    st.title("Lead Detail")
    rows = queries.leads_table(_engine(), limit=1000)
    options = {
        f"#{r['id']} · {r['name']} · skor {r['score']}": r["id"] for r in rows
    }
    selected = st.selectbox("Pilih lead", list(options.keys()))
    if selected:
        detail = queries.lead_detail(_engine(), options[selected])
        if detail["error"]:
            st.error(detail["error"])
        else:
            lead, business = detail["lead"], detail["business"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Skor", lead["score"])
            c2.metric("Status", lead["status"])
            c3.metric("Email", lead["email_status"])
            c4.metric("Kontak", len(detail["contacts"]))

            st.subheader("Bisnis")
            if business:
                st.json({
                    "nama": business.get("name"),
                    "kategori": business.get("category"),
                    "alamat": business.get("address"),
                    "telepon": business.get("phone"),
                    "website": business.get("domain"),
                })

            st.subheader("Skor breakdown")
            if lead["score_detail"]:
                st.code(lead["score_detail"], language=None)
            else:
                st.caption("—")

            st.subheader("Kontak")
            st.dataframe(_df(detail["contacts"]), use_container_width=True)

            st.subheader("Riwayat outreach")
            events = [
                {"event": e["event_type"], "email": e["email"],
                 "detail": e["detail"], "waktu": _fmt_ts(e["created_at"])}
                for e in detail["events"]
            ]
            st.dataframe(_df(events), use_container_width=True)


# --- Campaigns ---------------------------------------------------------------

elif page == "Campaigns":
    st.title("Campaigns")
    st.caption(
        "Worker hanya memproses campaign status `running` (dry run default). "
        "`Kirim batch` = jalankan sekali sekarang. Kirim nyata tetap "
        "butuh otorisasi eksplisit (D-036)."
    )

    rows = queries.campaigns_table(_engine())
    df = _df(rows)
    if not df.empty:
        df = df[["id", "name", "status", "min_score", "followup_days", "email_statuses"]]
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Belum ada campaign.")

    if not df.empty:
        st.subheader("Aksi")
        selected_id = st.selectbox(
            "Campaign", [int(r) for r in df["id"].tolist()]
        )
        a1, a2, a3, a4 = st.columns(4)
        if a1.button("▶ Start (worker kirim tiap tick)"):
            set_campaign_status(_engine(), selected_id, "running")
            getattr(st, 'rerun', st.experimental_rerun)()
        if a2.button("⏸ Pause"):
            set_campaign_status(_engine(), selected_id, "paused")
            getattr(st, 'rerun', st.experimental_rerun)()
        if a3.button("⏹ Selesai (done)"):
            set_campaign_status(_engine(), selected_id, "done")
            getattr(st, 'rerun', st.experimental_rerun)()
        if a4.button("⚡ Kirim 1 batch sekarang (dry)"):
            stats = run_campaign(_engine(), selected_id, limit=10)
            st.json(stats)

        st.subheader(f"Event campaign #{selected_id}")
        events = queries.campaign_events(_engine(), selected_id)
        events = [
            {"event": e["event_type"], "email": e["email"],
             "detail": e["detail"], "waktu": _fmt_ts(e["created_at"])}
            for e in events
        ]
        st.dataframe(_df(events), use_container_width=True)

    st.subheader("Campaign baru")
    with st.form("new_campaign"):
        n_name = st.text_input("Nama (unik)")
        n_subject = st.text_input("Subjek", "Kerja sama untuk {{name}}?")
        n_body = st.text_area(
            "Body teks (placeholder: {{name}} {{category}} {{location}} {{domain}} "
            "{{sender_name}} {{sender_email}} {{unsubscribe_url}})",
            height=150,
        )
        n_min = st.number_input("Skor minimum", 0, 100, 0)
        n_followup = st.number_input("Follow-up setelah (hari, 0=off)", 0, 30, 0)
        created = st.form_submit_button("Buat (draft)")
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
    st.title("Email Preview")
    st.caption("Render persis seperti yang dikirim campaign (dry maupun live).")

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

        campaign = get_campaign(_engine(), c_options[c_sel])
        lead = next(l for l in leads if l["id"] == l_options[l_sel])
        email = lead["best_email"] or "contoh@domain.id"
        unsub = unsubscribe_url(email)
        subject, text, html = render_message(
            lead,
            campaign["subject"],
            campaign["body_text"],
            campaign.get("body_html") or "",
            "MARKETING",
            settings.smtp_from or "marketing@example.com",
            unsub,
        )
        st.subheader("Subjek")
        st.code(subject, language=None)
        left, right = st.columns(2)
        left.subheader("Teks")
        left.code(text, language=None)
        right.subheader("HTML")
        right.code(html or "—", language="html")
        st.caption(f"Unsubscribe: {unsub}")
        st.caption(
            "Header otomatis: List-Unsubscribe + List-Unsubscribe-Post: "
            "List-Unsubscribe=One-Click (RFC 8058)."
        )


# --- Analytics ---------------------------------------------------------------

elif page == "Analytics":
    st.title("Analytics")

    st.subheader("Distribusi skor lead")
    buckets = queries.leads_by_score_bucket(_engine())
    dfb = _df(buckets)
    if not dfb.empty:
        dfb["rentang"] = dfb["bucket"].map(lambda b: f"{int(b)}-{int(b) + 19}")
        st.bar_chart(dfb.set_index("rentang")["n"])

    st.subheader("Kontak per jenis")
    kinds = queries.contacts_by_kind(_engine())
    dfk = _df(kinds)
    if not dfk.empty:
        st.bar_chart(dfk.set_index("kind")["n"])

    st.subheader("Outreach per hari (14 hari)")
    daily = queries.events_daily(_engine())
    dfd = _df(daily)
    if not dfd.empty:
        piv = dfd.pivot_table(
            index="day", columns="event_type", values="n", fill_value=0
        )
        st.bar_chart(piv)


# --- Export ------------------------------------------------------------------

elif page == "Export":
    st.title("Export")
    st.caption("CSV utf-8 (Excel-friendly) — filter sama seperti tabel lead.")

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
        "Download leads.csv", data=payload, file_name="leads.csv", mime="text/csv"
    )
    preview = payload.decode("utf-8-sig").splitlines()
    st.caption(f"{len(preview) - 1} baris")
    st.dataframe(
        pd.DataFrame(
            [row.split(",") for row in preview[1:25]],
            columns=preview[0].split(","),
        ),
        use_container_width=True,
    )
