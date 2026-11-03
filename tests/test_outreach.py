"""Hermetic tests for PHASE 6 — outreach engine.

No network: SMTP is stubbed, templates render offline, tokens are
generated with the dev secret. The unsubscribe endpoint is exercised
via FastAPI's TestClient (no live server).
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Engine

from app.db import CAMPAIGNS, LEADS, OUTREACH_EVENTS, SUPPRESSIONS, METADATA
from app.store import upsert_businesses, save_contacts, upsert_leads, count_leads
from app.extract import Contact
from app.outreach.campaign import (
    create_campaign,
    get_campaign,
    run_campaign,
    run_campaigns,
    run_followups,
)
from app.outreach.smtp import send_email
from app.outreach.template import render_message, render
from app.outreach.unsubscribe import make_token, verify_token
from app.outreach.bounce import mark_bounces, process_unsubscribe_token
from scrapers.base import Business


@pytest.fixture
def engine():
    """Thread-safe in-memory engine: the FastAPI endpoint tests run the
    handler in a worker thread, and SingletonThreadPool would hand it a
    different (empty) memory database."""
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(eng)
    return eng


@pytest.fixture
def api_client(engine, monkeypatch):
    """FastAPI TestClient pointed at the test engine."""
    from app import main as main_mod

    monkeypatch.setattr(main_mod, "get_engine", lambda: engine)
    import app.outreach.bounce as bounce_mod
    monkeypatch.setattr(bounce_mod, "get_engine", lambda: engine)
    client = TestClient(main_mod.api)
    return client


def _seed(engine: Engine, email: str = "halo@senjakopi.id", lead_status: str = "new") -> int:
    """One business with a validated email contact + a lead row.
    Returns lead id."""
    upsert_businesses(engine, [Business(
        name="Kopi Senja", category="coffee shop",
        address="Jl. Malioboro", phone="0812", website="https://senjakopi.id",
    )])
    from app.store import primary_business_id
    bid = primary_business_id(engine, "senjakopi.id")
    save_contacts(engine, bid, 1, [
        Contact("email", email, email, "", "mailto", 80),
    ])
    # simulate MX-validated
    from app.db import CONTACTS
    with engine.begin() as conn:
        cid = conn.execute(
            select(CONTACTS.c.id).where(CONTACTS.c.value_norm == email)
        ).scalar()
        conn.execute(
            update(CONTACTS).where(CONTACTS.c.id == cid)
            .values(status="valid", status_detail="mx ok", checked_at=dt.datetime.utcnow())
        )
    upsert_leads(engine, [{
        "business_id": bid,
        "email_contact_id": cid,
        "best_email": email,
        "best_phone": "",
        "email_status": "valid",
        "score": 85,
        "score_detail": "stub",
    }])
    with engine.connect() as conn:
        lead_id = conn.execute(
            select(LEADS.c.id).where(LEADS.c.business_id == bid)
        ).scalar()
        if lead_status != "new":
            with engine.begin() as c2:
                c2.execute(
                    update(LEADS).where(LEADS.c.id == lead_id).values(status=lead_status)
                )
    return int(lead_id)


def _campaign(engine: Engine, **kwargs) -> int:
    defaults = dict(
        name="test-campaign",
        subject="Halo {{name}}",
        body_text="Hai {{name}} di {{location}}, from {{sender_name}}. Unsub: {{unsubscribe_url}}",
        body_html="",
        min_score=0,
        email_statuses="valid,unknown",
    )
    defaults.update(kwargs)
    return create_campaign(engine, **defaults)


# --- smtp: dry-run guarantees -------------------------------------------------


class TestSmtpDryRun:
    def test_default_is_dry(self):
        # no SMTP creds + DRY_RUN default true -> sent-dry, never a socket
        result = send_email("a@b.com", "s", "", "t")
        assert result.status == "sent-dry"
        assert result.mode == "dry"

    def test_live_requires_full_arming(self, monkeypatch):
        import app.outreach.smtp as smtp_mod

        def _patch(**over):
            for key, val in over.items():
                object.__setattr__(smtp_mod.settings, key, val)

        _patch(dry_run=False, smtp_host="smtp.example.com",
               smtp_user="u@example.com", smtp_pass="pw",
               outreach_send_live=False)  # arming flag missing -> still dry
        try:
            result = send_email("a@b.com", "s", "", "t")
        finally:
            _patch(dry_run=True, smtp_host="", smtp_user="", smtp_pass="",
                   outreach_send_live=False)
        assert result.status == "sent-dry"
        assert "not armed" in result.detail

    def test_smtp_never_raises(self, monkeypatch):
        import app.outreach.smtp as smtp_mod

        def _patch(**over):
            for key, val in over.items():
                object.__setattr__(smtp_mod.settings, key, val)

        _patch(dry_run=False, smtp_host="smtp.example.com",
               smtp_user="u", smtp_pass="p", outreach_send_live=True)
        try:
            def boom(*a, **kw):
                raise OSError("network down")

            monkeypatch.setattr(smtp_mod.smtplib, "SMTP", boom)
            result = send_email("a@b.com", "s", "", "t")
        finally:
            _patch(dry_run=True, smtp_host="", smtp_user="", smtp_pass="",
                   outreach_send_live=False)
        assert result.status == "failed"  # per-recipient failure, no crash
        assert "OSError" in result.detail


# --- templates ---------------------------------------------------------------


class TestTemplates:
    def test_render_personalization(self):
        lead = {"name": "Kopi Senja", "category": "coffee shop",
                "location": "Yogyakarta", "domain": "senjakopi.id"}
        subject, text, html = render_message(
            lead, "Halo {{name}}", "Pesan untuk {{name}}", "",
            "Phenom", "me@example.com", "http://x/unsub",
        )
        assert subject == "Halo Kopi Senja"
        assert "Kopi Senja" in text

    def test_missing_fields_collapse(self):
        lead = {"name": "", "category": "", "domain": ""}
        subject, text, _ = render_message(
            lead, "s", "{{name}}|{{category}}|{{domain}}", "",
            "p", "e", "u",
        )
        assert text == "||"

    def test_location_fallback(self):
        lead = {"name": "X", "category": "cafe", "location": ""}
        _, text, _ = render_message(lead, "s", "loc={{location}}", "", "p", "e", "u")
        assert text == "loc=cafe"  # falls back to category

    def test_render_malformed_braces_safe(self):
        out = render("body { bad }} {x", {"x": "1"})
        assert isinstance(out, str)  # never raises

    def test_missing_key_renders_empty(self):
        assert render("a{{missing}}b", {}) == "ab"


# --- unsubscribe tokens ------------------------------------------------------


class TestUnsubscribeToken:
    def test_roundtrip(self):
        token = make_token("Halo@Senjakopi.ID")
        assert verify_token(token) == "halo@senjakopi.id"  # normalized

    def test_tamper_detected(self):
        token = make_token("a@b.com")
        assert verify_token(token[:-1] + ("0" if token[-1] != "0" else "1")) is None

    def test_garbage_rejected(self):
        assert verify_token("") is None
        assert verify_token("no-signature") is None
        assert verify_token("!!!.???") is None

    def test_unsubscribe_flow(self, engine):
        _seed(engine, "halo@senjakopi.id")
        process_unsubscribe_token(engine, make_token("halo@senjakopi.id"))
        with engine.connect() as conn:
            suppressed = conn.execute(select(SUPPRESSIONS.c.email_norm)).scalars().all()
            lead_status = conn.execute(select(LEADS.c.status)).scalars().all()
        assert "halo@senjakopi.id" in suppressed
        assert "suppressed" in lead_status

    def test_endpoint(self, api_client):
        token = make_token("x@y.com")
        resp = api_client.get(f"/unsubscribe?token={token}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unsubscribed"

    def test_endpoint_invalid(self, api_client):
        resp = api_client.get("/unsubscribe?token=garbage")
        assert resp.status_code == 404


# --- campaign runner ---------------------------------------------------------


class TestCampaignRunner:
    def test_dry_run_no_smtp_traffic(self, engine, monkeypatch):
        """Dry mode must never touch the SMTP layer — patch smtplib itself
        with a bomb and prove the send path is not reached."""
        import types

        import app.outreach.smtp as smtp_mod

        lead_id = _seed(engine)
        campaign_id = _campaign(engine, name="dry1")

        class _Bomb:
            def __init__(self, *a, **kw):
                raise AssertionError("SMTP must not be touched in dry run")

        monkeypatch.setattr(
            smtp_mod, "smtplib", types.SimpleNamespace(SMTP=_Bomb)
        )
        stats = run_campaign(engine, campaign_id, limit=5)
        assert stats["sent_dry"] == 1
        assert stats["sent"] == 0
        assert stats["error"] == ""

    def test_event_logged_and_lead_contacted(self, engine):
        lead_id = _seed(engine)
        campaign_id = _campaign(engine, name="log1")
        run_campaign(engine, campaign_id, limit=5)
        with engine.connect() as conn:
            events = conn.execute(select(OUTREACH_EVENTS)).mappings().all()
            lead = conn.execute(select(LEADS)).mappings().first()
        assert len(events) == 1
        assert events[0]["event_type"] == "sent-dry"
        assert events[0]["email"] == "halo@senjakopi.id"
        assert lead["status"] == "contacted"

    def test_duplicate_send_prevented(self, engine):
        _seed(engine)
        campaign_id = _campaign(engine, name="dup1")
        first = run_campaign(engine, campaign_id, limit=5)
        second = run_campaign(engine, campaign_id, limit=5)
        assert first["sent_dry"] == 1
        assert second["sent_dry"] == 0
        assert second["skipped_duplicate"] == 1

    def test_min_score_filter(self, engine):
        _seed(engine)  # score 85
        campaign_id = _campaign(engine, name="score1", min_score=90)
        stats = run_campaign(engine, campaign_id, limit=5)
        assert stats["sent_dry"] == 0

    def test_email_status_filter(self, engine):
        _seed(engine)  # email_status valid
        campaign_id = _campaign(engine, name="status1", email_statuses="invalid")
        stats = run_campaign(engine, campaign_id, limit=5)
        assert stats["sent_dry"] == 0

    def test_suppressed_lead_skipped(self, engine):
        _seed(engine)
        process_unsubscribe_token(engine, make_token("halo@senjakopi.id"))
        campaign_id = _campaign(engine, name="sup1")
        stats = run_campaign(engine, campaign_id, limit=5)
        assert stats["sent_dry"] == 0

    def test_bounced_lead_never_selected(self, engine):
        _seed(engine, lead_status="bounced")
        campaign_id = _campaign(engine, name="bounce1")
        stats = run_campaign(engine, campaign_id, limit=5)
        assert stats["sent_dry"] == 0

    def test_daily_limit_enforced(self, engine, monkeypatch):
        import app.outreach.campaign as camp_mod

        _seed(engine)
        campaign_id = _campaign(engine, name="limit1")
        object.__setattr__(camp_mod.settings, "outreach_send_per_day", 0)
        try:
            stats = run_campaign(engine, campaign_id, limit=5)
        finally:
            object.__setattr__(camp_mod.settings, "outreach_send_per_day", 50)
        assert stats["sent_dry"] == 0
        assert stats["skipped_daily_limit"] == 1

    def test_never_raises(self, engine, monkeypatch):
        import app.outreach.campaign as camp_mod

        def boom(*a, **kw):
            raise RuntimeError("db gone")

        monkeypatch.setattr(camp_mod, "_eligible_leads", boom)
        stats = run_campaign(engine, 999)
        assert "error" in stats

    def test_run_campaigns_only_running(self, engine):
        _seed(engine)
        draft_id = _campaign(engine, name="draft1")
        stats = run_campaigns(engine)
        assert stats["campaigns"] == 0  # draft campaigns never move

        with engine.begin() as conn:
            conn.execute(
                update(CAMPAIGNS).where(CAMPAIGNS.c.id == draft_id).values(status="running")
            )
        stats = run_campaigns(engine)
        assert stats["campaigns"] == 1
        assert stats["sent_dry"] == 1


# --- follow-ups --------------------------------------------------------------


class TestFollowups:
    def test_followup_after_days(self, engine, monkeypatch):
        _seed(engine)
        campaign_id = _campaign(engine, name="f1", followup_days=3)
        run_campaign(engine, campaign_id, limit=5)
        # age the primary send past the follow-up window
        with engine.begin() as conn:
            conn.execute(
                update(OUTREACH_EVENTS)
                .where(OUTREACH_EVENTS.c.campaign_id == campaign_id)
                .values(created_at=dt.datetime.utcnow() - dt.timedelta(days=5))
            )
        stats = run_followups(engine)
        assert stats["sent_dry"] == 1
        # follow-up duplicate prevention
        stats2 = run_followups(engine)
        assert stats2["sent_dry"] == 0
        assert stats2["skipped_duplicate"] == 1

    def test_no_followup_within_window(self, engine):
        _seed(engine)
        campaign_id = _campaign(engine, name="f2", followup_days=30)
        run_campaign(engine, campaign_id, limit=5)
        stats = run_followups(engine)
        assert stats["sent_dry"] == 0

    def test_suppressed_not_followed_up(self, engine):
        _seed(engine)
        campaign_id = _campaign(engine, name="f3", followup_days=3)
        run_campaign(engine, campaign_id, limit=5)
        process_unsubscribe_token(engine, make_token("halo@senjakopi.id"))
        with engine.begin() as conn:
            conn.execute(
                update(OUTREACH_EVENTS)
                .where(OUTREACH_EVENTS.c.campaign_id == campaign_id)
                .values(created_at=dt.datetime.utcnow() - dt.timedelta(days=5))
            )
        stats = run_followups(engine)
        assert stats["sent_dry"] == 0
        assert stats["skipped_suppressed"] == 1


# --- bounces -----------------------------------------------------------------


class TestBounces:
    def test_hard_bounce_suppresses(self, engine):
        _seed(engine)
        stats = mark_bounces(engine, [("halo@senjakopi.id", "550 unknown user")])
        assert stats["hard"] == 1
        with engine.connect() as conn:
            reasons = conn.execute(select(SUPPRESSIONS.c.reason)).scalars().all()
            lead = conn.execute(select(LEADS.c.status)).scalars().all()
        assert "hard-bounce" in reasons
        assert "bounced" in lead

    def test_soft_bounce_not_suppressed(self, engine):
        _seed(engine)
        stats = mark_bounces(engine, [("halo@senjakopi.id", "soft: mailbox full")])
        assert stats["soft"] == 1
        assert stats["hard"] == 0
        with engine.connect() as conn:
            n = conn.execute(select(SUPPRESSIONS.c.id)).scalars().all()
        assert n == []

    def test_garbage_input_skipped(self, engine):
        stats = mark_bounces(engine, [("", "x"), ("no-at-sign", "y")])
        assert stats["skipped"] == 2

    def test_never_raises(self, engine, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("db gone")
        import app.outreach.bounce as bounce_mod
        monkeypatch.setattr(bounce_mod, "_suppress", boom)
        stats = mark_bounces(engine, [("a@b.com", "hard")])
        assert "error" in stats


# --- campaign create ---------------------------------------------------------


class TestCampaignCreate:
    def test_duplicate_name_rejected(self, engine):
        _campaign(engine, name="dup")
        with pytest.raises(ValueError):
            _campaign(engine, name="dup")

    def test_defaults(self, engine):
        campaign_id = _campaign(engine, name="d1")
        campaign = get_campaign(engine, campaign_id)
        assert campaign["status"] == "draft"
        assert campaign["followup_days"] == 0
        assert campaign["email_statuses"] == "valid,unknown"
