"""Hermetic tests for PHASE 5 — validation, leads, export.

No network: domain/MX layers run with injected resolvers and lookup
stubs; SMTP connects to a fake server object.
"""

from __future__ import annotations

import importlib
import socket
import datetime as dt

import pytest
from sqlalchemy import create_engine

from app.db import METADATA
from app.store import (
    pending_email_contacts,
    set_contact_validation,
    business_contact_summary,
    upsert_leads,
    list_leads,
    count_leads,
    upsert_businesses,
    save_contacts,
)
from app.leads import build_leads, score_lead
from app.validation import (
    VALID, INVALID, UNKNOWN,
    syntax_check, domain_check, mx_check, validate_email, run_validation_batch,
)
from app.extract import Contact
from scrapers.base import Business

validation_mod = importlib.import_module("app.validation")


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", future=True)
    METADATA.create_all(eng)
    return eng


def _resolver(ip: str):
    def resolve(host, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return resolve


# --- layer 1: syntax --------------------------------------------------------


class TestSyntax:
    def test_valid(self):
        assert syntax_check("halo@senjakopi.id").status == VALID

    def test_double_at(self):
        assert syntax_check("bad@@x.com").status == INVALID

    def test_no_at(self):
        assert syntax_check("plain-text").status == INVALID

    def test_too_long(self):
        assert syntax_check("a" * 250 + "@x.com").status == INVALID

    def test_empty(self):
        assert syntax_check("").status == INVALID

    def test_junk_domain(self):
        assert syntax_check("a@example.com").status == INVALID

    def test_uppercase_normalized(self):
        status = syntax_check("HALO@Senjakopi.ID")
        assert status.email == "halo@senjakopi.id"
        assert status.status == VALID

    def test_detail_populated(self):
        status = syntax_check("bad@@x.com")
        assert status.detail
        assert status.checked_at


# --- layer 2: domain --------------------------------------------------------


class TestDomain:
    def test_resolves_public(self):
        status = domain_check(
            "a@senjakopi.id", _resolver=_resolver("93.184.216.34")
        )
        assert status.status == VALID

    def test_unresolvable(self):
        def dead_resolver(host, *a, **kw):
            raise socket.gaierror("name resolution failed")
        status = domain_check("a@nx.example", _resolver=dead_resolver)
        assert status.status == INVALID
        assert "resolve" in status.detail

    def test_private_ip_rejected(self):
        # resolver hook returns private addresses — SSRF guard rejects
        status = domain_check("a@internal.local", _resolver=_resolver("10.0.0.5"))
        assert status.status == INVALID

    def test_loopback_rejected(self):
        status = domain_check("a@localhost", _resolver=_resolver("127.0.0.1"))
        assert status.status == INVALID


# --- layer 3: MX ------------------------------------------------------------


class FakeSMTP:
    """Records construction; succeeds or raises on connect."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.helo_calls = 0
        self.quit_calls = 0
        self.fail = FakeSMTP._next_fail
        FakeSMTP.instances.append(self)

    _next_fail: bool = False

    def __enter__(self):
        if self.fail:
            raise OSError("connection refused (port 25 blocked)")
        return self

    def __exit__(self, *exc):
        return False

    def helo(self, name):
        self.helo_calls += 1
        return (250, b"ok")

    def quit(self):
        self.quit_calls += 1


def _mx(records: list[tuple[int, str]]):
    def lookup(domain):
        return records
    return lookup


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeSMTP.instances.clear()
    FakeSMTP._next_fail = False
    yield


class TestMx:
    def test_connectable_mx_valid(self, monkeypatch):
        monkeypatch.setattr(validation_mod, "is_public_host", lambda h, **kw: True)
        status = mx_check(
            "a@kopiaroma.id",
            _smtp=FakeSMTP,
            _mx_lookup=_mx([(10, "mail.kopiaroma.id")]),
        )
        assert status.status == VALID
        assert FakeSMTP.instances[0].helo_calls == 1
        assert FakeSMTP.instances[0].quit_calls == 1  # NO-SEND: connect/hello/quit only

    def test_no_mx_invalid(self):
        status = mx_check("a@nomail.example", _smtp=FakeSMTP, _mx_lookup=_mx([]))
        assert status.status == INVALID
        assert "no MX" in status.detail

    def test_refused_is_unknown_not_invalid(self, monkeypatch):
        monkeypatch.setattr(validation_mod, "is_public_host", lambda h, **kw: True)

        def fail_factory(host, port, timeout=10):
            raise OSError("connect refused (port 25 blocked)")

        status = mx_check(
            "a@blocked.example",
            _smtp=fail_factory,
            _mx_lookup=_mx([(10, "mx.blocked.example")]),
        )
        assert status.status == UNKNOWN  # port-25 block ≠ dead mailbox
        assert "refused" in status.detail or "unreachable" in status.detail

    def test_private_mx_host_skipped(self):
        # MX record pointing at a private host must never be connected
        attempts = []

        def boom_factory(host, port, timeout=10):
            attempts.append((host, port))
            raise AssertionError("must not connect to private MX")

        status = mx_check(
            "a@evil.example",
            _smtp=boom_factory,
            _mx_lookup=_mx([(10, "192.168.1.1")]),
        )
        assert status.status == UNKNOWN
        assert attempts == []  # no connection attempt

    def test_mx_sorted_by_preference(self, monkeypatch):
        monkeypatch.setattr(validation_mod, "is_public_host", lambda h, **kw: True)

        def lookup(domain):
            return [(30, "mx3.x"), (5, "mx1.x")]

        status = mx_check("a@x.example", _smtp=FakeSMTP, _mx_lookup=lookup)
        assert status.status == VALID
        assert FakeSMTP.instances[0].host == "mx1.x"  # lowest pref first


# --- pipeline: validate_email -----------------------------------------------


class TestValidateEmail:
    def test_syntax_short_circuits(self):
        status = validate_email(
            "bad@@x.com",
            _resolver=_resolver("1.2.3.4"),
            _mx_lookup=_mx([(10, "mx.x")]),
            _smtp=FakeSMTP,
        )
        assert status.status == INVALID

    def test_all_layers_pass(self):
        status = validate_email(
            "inquiry@blancocoffee.id",
            _resolver=_resolver("1.2.3.4"),
            _mx_lookup=_mx([(10, "mail.blancocoffee.id")]),
            _smtp=FakeSMTP,
        )
        assert status.status == VALID

    def test_domain_fail_short_circuits_before_mx(self):
        status = validate_email(
            "a@nx.example",
            _resolver=_resolver("127.0.0.1"),  # private IP -> domain fails
            _mx_lookup=_mx([(10, "mx.x")]),
            _smtp=FakeSMTP,
        )
        assert status.status == INVALID
        assert status.detail == "domain does not resolve"


# --- store: validation persistence ------------------------------------------


class TestValidationStore:
    def test_pending_and_persist(self, engine):
        bid = _business(engine, "Kopi Senja", "senjakopi.id")
        save_contacts(engine, bid, 1, [
            Contact("email", "halo@senjakopi.id", "halo@senjakopi.id",
                    "https://senjakopi.id/contact", "mailto", 80),
        ])
        pending = pending_email_contacts(engine)
        assert len(pending) == 1
        assert pending[0]["value_norm"] == "halo@senjakopi.id"

        set_contact_validation(engine, pending[0]["id"], VALID, "mx ok")
        assert pending_email_contacts(engine) == []  # no longer pending
        again = pending_email_contacts(engine)
        assert again == []

    def test_only_emails_claimed(self, engine):
        bid = _business(engine, "Kopi Senja", "senjakopi.id")
        save_contacts(engine, bid, 1, [
            Contact("phone", "0812-3456-7890", "+6281234567890", "", "text", 60),
        ])
        assert pending_email_contacts(engine) == []


def _business(engine, name: str, domain: str) -> int:
    upsert_businesses(engine, [Business(
        name=name, category="coffee shop",
        address="Jl. Malioboro", phone="0812", website=f"https://{domain}",
    )])
    from app.store import primary_business_id
    return primary_business_id(engine, domain)


# --- leads ------------------------------------------------------------------


class TestLeads:
    def _seed(self, engine) -> int:
        bid = _business(engine, "Kopi Senja", "senjakopi.id")
        save_contacts(engine, bid, 1, [
            Contact("email", "halo@senjakopi.id", "halo@senjakopi.id",
                    "https://senjakopi.id/contact", "mailto", 80),
            Contact("phone", "0812-3456-7890", "+6281234567890", "", "text", 60),
            Contact("social", "IG", "instagram.com/kopisenja", "", "link", 55),
            Contact("address", "Jl. Malioboro 1", "jl. malioboro 1", "", "text", 50),
        ])
        # mark the email as MX-validated so scoring sees status=valid
        row = pending_email_contacts(engine)[0]
        set_contact_validation(engine, row["id"], "valid", "stub mx ok")
        return bid

    def test_score_breakdown(self):
        score, detail = score_lead(
            {"email": (1, 80, 3, "halo@senjakopi.id", "valid"),
             "phone": (2, 60, 0, "+6281234567890", None),
             "social": True, "address": True},
            {"domain": "senjakopi.id", "last_seen_at": dt.datetime.utcnow()},
        )
        # email valid 40 + phone 20 + social 5 + address 10 + website 15 + fresh 10
        assert score == 100
        assert "email:valid=40" in detail
        assert "phone:yes=20" in detail

    def test_no_email_low_score(self):
        score, _ = score_lead(
            {"social": True},
            {"domain": "", "last_seen_at": None},
        )
        assert score == 5

    def test_build_leads_persists(self, engine):
        bid = self._seed(engine)
        result = build_leads(engine)
        assert result["new"] == 1
        lead = list_leads(engine)[0]
        assert lead["best_email"] == "halo@senjakopi.id"
        assert lead["score"] == 100
        assert lead["name"] == "Kopi Senja"

    def test_build_leads_idempotent(self, engine):
        self._seed(engine)
        assert build_leads(engine)["new"] == 1
        assert build_leads(engine)["updated"] == 1
        assert count_leads(engine) == 1

    def test_status_change_updates_lead(self, engine):
        bid = self._seed(engine)
        build_leads(engine)
        # invalidate the (already-validated) email via direct store call
        from app.db import CONTACTS as _C
        from sqlalchemy import select, update
        with engine.begin() as conn:
            cid = conn.execute(
                select(_C.c.id).where(_C.c.value_norm == "halo@senjakopi.id")
            ).scalar()
            conn.execute(
                update(_C).where(_C.c.id == cid)
                .values(status=INVALID, status_detail="no MX record")
            )
        build_leads(engine)
        lead = list_leads(engine)[0]
        assert lead["email_status"] == "invalid"
        assert lead["score"] < 100  # email valid 40 → invalid 0

    def test_filter_min_score(self, engine):
        self._seed(engine)
        build_leads(engine)
        assert len(list_leads(engine, min_score=100)) == 1
        assert len(list_leads(engine, min_score=101)) == 0


# --- export ------------------------------------------------------------------


class TestExport:
    def test_csv_written(self, engine, tmp_path):
        bid = _business(engine, "Kopi Senja", "senjakopi.id")
        save_contacts(engine, bid, 1, [
            Contact("email", "halo@senjakopi.id", "halo@senjakopi.id",
                    "", "mailto", 80),
        ])
        build_leads(engine)
        out = tmp_path / "leads.csv"
        from app.export import export_leads_csv
        result = export_leads_csv(engine, out)
        assert result["rows"] == 1
        content = out.read_text(encoding="utf-8-sig")
        assert "halo@senjakopi.id" in content
        assert "Kopi Senja" in content
        assert content.startswith("score,name,best_email")

    def test_csv_filters(self, engine, tmp_path):
        bid = _business(engine, "Kopi Senja", "senjakopi.id")
        save_contacts(engine, bid, 1, [
            Contact("email", "halo@senjakopi.id", "halo@senjakopi.id",
                    "", "mailto", 80),
        ])
        build_leads(engine)
        from app.export import export_leads_csv
        result = export_leads_csv(engine, tmp_path / "f.csv", email_status="valid")
        assert result["rows"] == 0  # not validated yet → unknown status


# --- worker batch ------------------------------------------------------------


class TestValidationBatch:
    def test_batch_validates_and_persists(self, engine, monkeypatch):
        bid = _business(engine, "Kopi Senja", "senjakopi.id")
        save_contacts(engine, bid, 1, [
            Contact("email", "halo@senjakopi.id", "halo@senjakopi.id",
                    "", "mailto", 80),
        ])
        # hermetic: force layers to syntax+domain with a stub resolver
        monkeypatch.setattr(validation_mod, "validate_email",
            lambda addr, layers=("syntax", "domain"), **kw: type("S", (), {
                "email": addr, "status": "valid", "detail": "stub",
                "checked_at": "2026-11-02T00:00:00Z"})())
        stats = run_validation_batch(engine=engine, limit=5)
        assert stats["emails"] == 1
        assert stats["valid"] == 1
        assert pending_email_contacts(engine) == []

    def test_batch_never_raises(self, engine, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("db gone")
        monkeypatch.setattr(validation_mod, "validate_email", boom)
        stats = run_validation_batch(engine=engine, limit=5)
        assert stats["emails"] == 0
