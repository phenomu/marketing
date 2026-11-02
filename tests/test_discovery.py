"""PHASE 2 tests: URL normalization, store upserts, discovery pipeline.

Discovery tests use a fake adapter (no network) and a fresh SQLite
engine per test — hermetic per D-020.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app import store as store_module
from app.db import METADATA
from app.discovery import (
    enqueue_from_plan,
    load_keyword_plan,
    plan_to_searches,
    run_pending_jobs,
)
from app.store import (
    JOB_DONE,
    JOB_FAILED,
    claim_next_pending,
    complete_job,
    count_businesses,
    insert_job,
    list_businesses,
    list_jobs,
    upsert_businesses,
)
from app.urls import extract_domain, normalize_website
from scrapers.base import Business, SearchResult


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", future=True)  # in-memory, isolated
    METADATA.create_all(eng)
    return eng


class TestNormalizeWebsite:
    def test_adds_scheme_strips_www_and_tracking(self):
        assert (
            normalize_website("WWW.Example.com/page/?utm_source=x&id=2")
            == "https://example.com/page?id=2"
        )

    def test_idempotent(self):
        once = normalize_website("www.toko.id/kopi/?fbclid=abc")
        assert normalize_website(once) == once

    def test_empty_stays_empty(self):
        assert normalize_website("") == ""
        assert normalize_website("   ") == ""

    def test_surrounding_junk_removed(self):
        assert normalize_website("<https://a.co>") == "https://a.co"

    def test_domain_extraction(self):
        assert extract_domain("https://www.Kedai.id/menu") == "kedai.id"
        assert extract_domain("") == ""


class TestStore:
    def test_upsert_insert_then_update_keeps_first_seen(self, engine):
        b1 = Business(name="Kafe A", phone="0811", website="https://www.kafe-a.id", source="test")
        assert upsert_businesses(engine, [b1]) == (1, 0)
        # second run: same place, fresh phone, empty website must NOT erase
        b2 = Business(name="Kafe A", phone="0822", website="", source="test")
        assert upsert_businesses(engine, [b2]) == (0, 1)
        rows = list_businesses(engine)
        assert len(rows) == 1
        assert rows[0]["phone"] == "0822"
        assert rows[0]["website"] == "https://kafe-a.id"  # kept + normalized
        assert rows[0]["domain"] == "kafe-a.id"
        assert rows[0]["first_seen_at"] is not None

    def test_job_lifecycle(self, engine):
        job_id = insert_job(engine, "fake", "kopi", "Jogja", 10)
        job = claim_next_pending(engine)
        assert job is not None and job["id"] == job_id
        assert claim_next_pending(engine) is None  # nothing pending anymore
        complete_job(engine, job_id, JOB_DONE, found=5, new=3, updated=2)
        jobs = list_jobs(engine)
        assert jobs[0]["status"] == "done"
        assert jobs[0]["found_count"] == 5
        assert jobs[0]["new_count"] == 3

    def test_bad_status_rejected(self, engine):
        job_id = insert_job(engine, "fake", "q", "", 5)
        with pytest.raises(ValueError):
            complete_job(engine, job_id, "bogus")


class FakeAdapter:
    """SourceAdapter stand-in: deterministic records, optional error."""

    source_name = "fake"
    source_label = "fake source"

    def __init__(self, records=None, error=""):
        self.records = records or []
        self.error = error
        self.calls: list[tuple] = []

    def configured(self):
        return True

    def key_hint(self):
        return "FAKE_KEY"

    def search(self, query, location="", **kwargs):
        self.calls.append((query, location, kwargs.get("max_results")))
        return SearchResult(
            businesses=list(self.records), source=self.source_name,
            query=query, location=location, total=len(self.records), error=self.error,
        )


class TestDiscovery:
    def test_plan_expansion_cross_product(self):
        plan = {"queries": ["kopi", "laundry"], "locations": ["Jogja", "Solo"], "max_results": 5}
        searches = plan_to_searches(plan, "gmaps_scrape")
        assert len(searches) == 4
        assert all(s["source"] == "gmaps_scrape" and s["max_results"] == 5 for s in searches)

    def test_plan_disable_default_source(self):
        plan = {"queries": ["kopi"], "locations": ["Jogja"], "sources": {"gmaps_scrape": False}}
        assert plan_to_searches(plan, "gmaps_scrape") == []

    def test_missing_plan_file_returns_empty(self, tmp_path):
        assert load_keyword_plan(tmp_path / "nope.yaml") == {}

    def test_enqueue_idempotent(self, engine):
        plan = {"queries": ["kopi"], "locations": ["Jogja"]}
        assert enqueue_from_plan(engine, "gmaps_scrape", plan) == 1
        assert enqueue_from_plan(engine, "gmaps_scrape", plan) == 0  # covered

    def test_run_pending_jobs_end_to_end(self, engine, monkeypatch):
        fake = FakeAdapter(records=[Business(name="Kafe X", place_id="p1", website="www.kafe.id")])
        monkeypatch.setattr("app.discovery.get_adapter", lambda source=None: fake)
        insert_job(engine, "fake", "kopi", "Jogja", 10)
        stats = run_pending_jobs(engine)
        assert stats == {"jobs": 1, "new": 1, "updated": 0}
        assert count_businesses(engine) == 1
        # domain extracted for the crawl queue
        assert list_businesses(engine)[0]["domain"] == "kafe.id"
        # second run: queue drained, nothing new
        assert run_pending_jobs(engine) == {"jobs": 0, "new": 0, "updated": 0}

    def test_failed_adapter_marks_job_failed(self, engine, monkeypatch):
        fake = FakeAdapter(error="HTTP 429 quota")
        monkeypatch.setattr("app.discovery.get_adapter", lambda source=None: fake)
        insert_job(engine, "fake", "kopi", "Jogja", 10)
        stats = run_pending_jobs(engine)
        assert stats == {"jobs": 1, "new": 0, "updated": 0}
        jobs = list_jobs(engine)
        assert jobs[0]["status"] == "failed"
        assert "429" in jobs[0]["error"]

    def test_partial_error_still_stores_records(self, engine, monkeypatch):
        fake = FakeAdapter(records=[Business(name="Kafe Y", place_id="p2")], error="partial")
        monkeypatch.setattr("app.discovery.get_adapter", lambda source=None: fake)
        insert_job(engine, "fake", "kopi", "Jogja", 10)
        stats = run_pending_jobs(engine)
        assert stats["new"] == 1  # records kept even when error text present
        assert count_businesses(engine) == 1
        jobs = list_jobs(engine)
        assert jobs[0]["status"] == "failed"  # error still surfaced in the job row
        assert jobs[0]["new_count"] == 1
