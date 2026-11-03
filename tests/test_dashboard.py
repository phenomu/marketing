"""Hermetic tests for the PHASE 7 dashboard data layer.

No network, no Streamlit runtime — exercises dashboard/queries.py
against a throwaway SQLite engine seeded with the same helpers the
outreach suite uses.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Engine

from app.db import (
    CAMPAIGNS,
    LEADS,
    METADATA,
    OUTREACH_EVENTS,
    SUPPRESSIONS,
    get_engine,
)
from app.store import upsert_leads
from app.export import leads_csv_bytes, export_leads_csv
from dashboard import queries
from tests.test_outreach import _seed, _campaign
from app.outreach.campaign import run_campaign, set_campaign_status


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", future=True)
    METADATA.create_all(eng)
    return eng


class TestOverview:
    def test_overview_counts(self, engine):
        _seed(engine)
        cid = _campaign(engine, name="ov1")
        run_campaign(engine, cid, limit=5)
        data = queries.overview(engine)
        assert data["error"] == ""
        assert data["businesses"] == 1
        assert data["contacts_by_kind"]["email"] == 1
        assert data["leads_by_status"]["contacted"] == 1
        assert data["campaigns_by_status"]["draft"] == 1
        assert data["events_by_type"]["sent-dry"] == 1
        assert data["suppressions"] == 0

    def test_overview_never_raises(self, engine):
        # nonexistent tables -> returns error string, not an exception
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE leads"))
        data = queries.overview(engine)
        assert data["error"] != ""


class TestLeadsTable:
    def test_filters(self, engine):
        _seed(engine)
        rows = queries.leads_table(engine)
        assert len(rows) == 1
        assert rows[0]["best_email"] == "halo@senjakopi.id"
        # min_score above the seeded score
        assert queries.leads_table(engine, min_score=99) == []
        # email status filter
        assert queries.leads_table(engine, email_status="invalid") == []
        # lead status filter: seed is "new", so contacted filters it out
        assert queries.leads_table(engine, lead_status="contacted") == []
        assert len(queries.leads_table(engine, lead_status="new")) == 1

    def test_error_shape(self, engine, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("db gone")

        monkeypatch.setattr(queries, "list_leads", boom)
        rows = queries.leads_table(engine)
        assert rows and rows[0]["error"]


class TestLeadDetail:
    def test_detail(self, engine):
        lead_id = _seed(engine)
        detail = queries.lead_detail(engine, lead_id)
        assert detail["error"] == ""
        assert detail["lead"]["id"] == lead_id
        assert detail["business"]["name"] == "Kopi Senja"
        assert len(detail["contacts"]) == 1
        assert detail["events"] == []

    def test_detail_events_included(self, engine):
        lead_id = _seed(engine)
        cid = _campaign(engine, name="det1")
        run_campaign(engine, cid, limit=5)
        detail = queries.lead_detail(engine, lead_id)
        assert len(detail["events"]) == 1
        assert detail["events"][0]["event_type"] == "sent-dry"

    def test_detail_missing(self, engine):
        detail = queries.lead_detail(engine, 999)
        assert "tidak ditemukan" in detail["error"]


class TestCampaigns:
    def test_campaigns_table(self, engine):
        _seed(engine)
        _campaign(engine, name="t1")
        _campaign(engine, name="t2")
        rows = queries.campaigns_table(engine)
        assert len(rows) == 2

    def test_campaign_events(self, engine):
        _seed(engine)
        cid = _campaign(engine, name="e1")
        run_campaign(engine, cid, limit=5)
        events = queries.campaign_events(engine, cid)
        assert len(events) == 1
        assert events[0]["campaign_id"] == cid

    def test_set_campaign_status(self, engine):
        _seed(engine)
        cid = _campaign(engine, name="s1")
        assert set_campaign_status(engine, cid, "running") is True
        with engine.connect() as conn:
            status = conn.execute(
                select(CAMPAIGNS.c.status).where(CAMPAIGNS.c.id == cid)
            ).scalar()
        assert status == "running"

    def test_set_campaign_status_invalid(self, engine):
        _seed(engine)
        cid = _campaign(engine, name="s2")
        with pytest.raises(ValueError):
            set_campaign_status(engine, cid, "send-live")


class TestAnalytics:
    def test_events_daily(self, engine):
        _seed(engine)
        cid = _campaign(engine, name="a1")
        run_campaign(engine, cid, limit=5)
        rows = queries.events_daily(engine, days=1)
        assert len(rows) == 1
        assert rows[0]["n"] == 1

    def test_score_buckets(self, engine):
        _seed(engine)  # score 85 → bucket 80
        rows = queries.leads_by_score_bucket(engine)
        assert rows[0]["bucket"] == 80

    def test_contacts_by_kind(self, engine):
        _seed(engine)
        rows = queries.contacts_by_kind(engine)
        assert any(r["kind"] == "email" for r in rows)


class TestExport:
    def test_csv_bytes(self, engine):
        _seed(engine)
        payload = leads_csv_bytes(engine)
        text = payload.decode("utf-8-sig")
        lines = text.splitlines()
        assert lines[0].startswith("score,name,best_email")
        assert "halo@senjakopi.id" in text
        assert len(lines) == 2

    def test_csv_bytes_matches_file_export(self, engine, tmp_path):
        _seed(engine)
        file_out = export_leads_csv(engine, tmp_path / "f.csv")
        payload = leads_csv_bytes(engine)
        on_disk = (tmp_path / "f.csv").read_bytes()
        assert payload == on_disk
        assert file_out["rows"] == 1


class TestDiscoveryPage:
    def test_discovery_overview(self, engine):
        from app.store import insert_job

        insert_job(engine, "gmaps_scrape", "kopi jogja", "Indonesia", 10)
        disc = queries.discovery_overview(engine)
        assert disc["error"] == ""
        assert disc["jobs"][0]["query"] == "kopi jogja"

    def test_suppressions_table(self, engine):
        with engine.begin() as conn:
            conn.execute(
                insert(SUPPRESSIONS).values(
                    email_norm="x@y.com", reason="unsubscribe"
                )
            )
        rows = queries.suppressions_table(engine)
        assert rows[0]["email_norm"] == "x@y.com"
