"""PHASE 4 tests: contact extraction from stored crawl-page text.

Hermetic — no network, SQLite in-memory, pure functions + store layer.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select

from app.db import CONTACTS, CRAWL_JOBS, CRAWL_PAGES, METADATA
from app.extract import (
    Contact,
    extract_addresses,
    extract_emails,
    extract_from_page,
    extract_phones,
    extract_socials,
    normalize_phone,
    run_pending_extractions,
)
from app.store import (
    claim_pending_extractions,
    count_contacts,
    list_contacts,
    load_crawl_pages,
    mark_extraction_done,
    primary_business_id,
    save_contacts,
    update_business_address_if_empty,
    upsert_businesses,
)

PAGE_TEXT = (
    "Hubungi Kami Kedai Kopi Senja — email: halo@senjakopi.id atau cs (at) senjakopi "
    "(dot) id. Telp 0812-3456-7890 / +62 877 1234 5678. Instagram: instagram.com/kopisenja "
    "https://www.facebook.com/kopisenja.id twitter.com/KopiSenja. "
    "Alamat: Jl. Malioboro No. 1, Yogyakarta. Visit our sister site at example.com "
    "Foto tersedia di gambar-1234.png dan style.css."
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", future=True)
    METADATA.create_all(eng)
    return eng


class TestEmails:
    def test_plain_and_obfuscated(self):
        found = extract_emails(PAGE_TEXT)
        assert "halo@senjakopi.id" in found
        assert "cs@senjakopi.id" in found  # obfuscated (at)/(dot)

    def test_mailto_priority(self):
        found = extract_emails("contact us at sales@shop.id", ["info@shop.id"])
        assert found == ["info@shop.id", "sales@shop.id"]  # mailto first

    def test_junk_filtered(self):
        text = "see schema.org and logo.png and your email at example.com or a@b.c d"
        found = extract_emails(text)
        assert found == []

    def test_asset_lookalike_filtered(self):
        found = extract_emails("IMG path team.png + support@real-shop.co")
        assert found == ["support@real-shop.co"]

    def test_dedup(self):
        found = extract_emails("x@y.id X@Y.ID x@y.id")
        assert found == ["x@y.id"]


class TestPhones:
    def test_indonesian_formats(self):
        found = extract_phones(PAGE_TEXT)
        assert "+6281234567890" in found
        assert "+6287712345678" in found

    def test_prices_and_dates_not_phones(self):
        text = "Rp 150.000 sejak 2021-05-03 dan 0811 22 33 44"
        found = extract_phones(text)
        assert found == ["+62811223344"]

    def test_repeated_digits_rejected(self):
        assert extract_phones("call 0821 0000 0000") == []

    def test_normalize_bare_mobile(self):
        assert normalize_phone("081234567890") == "+6281234567890"
        assert normalize_phone("+6281234567890") == "+6281234567890"
        assert normalize_phone("6281234567890") == "+6281234567890"
        assert normalize_phone("123456") is None


class TestSocials:
    def test_profiles_kept(self):
        found = extract_socials(PAGE_TEXT)
        assert "instagram.com/kopisenja" in found
        assert "facebook.com/kopisenja.id" in found
        assert "twitter.com/kopisenja" in found

    www = "www.facebook.com/travelbrand"


    def test_content_pages_dropped(self):
        text = (
            "feed https://instagram.com/p/xyz123 and https://www.facebook.com/watch?v=1 "
            "https://instagram.com/reel/abc https://www.youtube.com/watch?v=x "
            "https://www.facebook.com/profile.php?id=123456"
        )
        assert extract_socials(text) == []

    def test_youtube_channel_kept(self):
        text = "subscribe youtube.com/channel/UCabc123def"
        assert extract_socials(text) == ["youtube.com/channel/ucabc123def"]

class TestAddresses:
    def test_jalan_prefix(self):
        found = extract_addresses(PAGE_TEXT)
        assert found == ["Jl. Malioboro No. 1"]

    def test_no_address(self):
        assert extract_addresses("no address here") == []


class TestPerPage:
    def test_confidence_contact_page_beats_home(self):
        contact_page = {
            "url": "https://s.id/contact", "kind": "contact",
            "text": "email a@s.id", "mailtos": [],
        }
        home_page = {
            "url": "https://s.id/", "kind": "home",
            "text": "email a@s.id", "mailtos": [],
        }
        contacts = extract_from_page(contact_page)
        assert contacts[0].confidence == 80  # contact page 80 + text 0
        home = extract_from_page(home_page)
        assert home[0].confidence == 60


class TestStore:
    def _seed(self, engine):
        from scrapers.base import Business

        upsert_businesses(
            engine,
            [Business(name="Kopi Senja", website="https://senjakopi.id", category="Coffee shop")],
        )
        bid = primary_business_id(engine, "senjakopi.id")
        assert bid is not None
        job = _insert_crawl_job(engine, "senjakopi.id", status="done")
        _insert_pages(engine, job, [(PAGE_TEXT, "contact", ["halo@senjakopi.id"])])
        return bid, job

    def test_full_extraction_cycle(self, engine):
        bid, job = self._seed(engine)
        stats = run_pending_extractions(engine)
        assert stats["jobs"] == 1
        assert stats["new"] >= 4  # email + phone + social + address
        contacts = list_contacts(engine, bid)
        kinds = {c["kind"] for c in contacts}
        assert kinds == {"email", "phone", "social", "address"}
        emails = [c["value"] for c in contacts if c["kind"] == "email"]
        assert "halo@senjakopi.id" in emails
        assert "cs@senjakopi.id" in emails
        phones = [c["value"] for c in contacts if c["kind"] == "phone"]
        assert "+6281234567890" in phones
        # extraction marked done — rerun is a no-op
        assert run_pending_extractions(engine) == {
            "jobs": 0, "new": 0, "updated": 0, "addresses_filled": 0,
        }
        # address backfilled into businesses row
        with engine.connect() as conn:
            from app.db import BUSINESSES
            addr = conn.execute(
                select(BUSINESSES.c.address).where(BUSINESSES.c.id == bid)
            ).scalar()
        assert "Malioboro" in addr

    def test_address_not_overwritten(self, engine):
        bid, job = self._seed(engine)
        with engine.begin() as conn:
            from app.db import BUSINESSES
            conn.execute(
                BUSINESSES.update().where(BUSINESSES.c.id == bid).values(address="Jl. Lama 9")
            )
        run_pending_extractions(engine)
        with engine.connect() as conn:
            from app.db import BUSINESSES
            addr = conn.execute(
                select(BUSINESSES.c.address).where(BUSINESSES.c.id == bid)
            ).scalar()
        assert addr == "Jl. Lama 9"  # discovery data wins

    def test_rerun_dedups_via_value_norm(self, engine):
        bid, job = self._seed(engine)
        run_pending_extractions(engine)
        # simulate re-crawl of same domain: same job row, fresh pages
        _insert_pages(engine, job, [(PAGE_TEXT, "contact", [])])
        with engine.begin() as conn:
            conn.execute(
                CRAWL_JOBS.update()
                .where(CRAWL_JOBS.c.id == job)
                .values(contacts_extracted=False)
            )
        stats = run_pending_extractions(engine)
        assert stats["jobs"] == 1
        assert stats["new"] == 0  # all contacts already present
        assert stats["updated"] >= 4  # last_seen bumped
        assert count_contacts(engine, bid) == 8  # no duplicate rows


def _insert_crawl_job(engine, domain: str, status: str = "done") -> int:
    import datetime as dt

    from app.db import CRAWL_JOBS as CJ

    with engine.begin() as conn:
        conn.execute(
            CJ.insert().values(
                domain=domain, status=status, pages_crawled=1,
                contacts_extracted=False, queued_at=dt.datetime.utcnow(),
            )
        )
        return conn.execute(select(CJ.c.id).order_by(CJ.c.id.desc())).scalar()


def _insert_pages(engine, crawl_job_id: int, pages) -> int:
    import datetime as dt

    from app.db import CRAWL_PAGES as CP

    with engine.begin() as conn:
        for text, kind, mailtos in pages:
            conn.execute(
                CP.insert().values(
                    crawl_job_id=crawl_job_id, url="https://x.id/" + kind,
                    kind=kind, http_status=200, fetched_ok=True,
                    title="t", text=text, mailtos=json.dumps(mailtos),
                    fetched_at=dt.datetime.utcnow(),
                )
            )
    return len(pages)
