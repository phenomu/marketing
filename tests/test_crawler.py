"""PHASE 3 tests: industry rules, robots.txt, fetch retry, HTML parsing,
crawl engine, crawl store/queue. All hermetic (no network — HTTP is
monkeypatched or injected; engines get in-memory SQLite)."""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import create_engine

fetch_mod = importlib.import_module("app.crawler.fetch")
robots_mod = importlib.import_module("app.crawler.robots")
from app.crawler import extract
from app.crawler.engine import CrawlOutcome, CrawledPage, crawl_domain
from app.db import CRAWL_JOBS, CRAWL_PAGES, METADATA
from app.industries import IndustryRules, load_industry_rules, matches_industry
from app.store import (
    claim_next_crawl,
    complete_crawl_job,
    count_crawl_jobs,
    enqueue_crawl_domains,
    list_crawl_jobs,
    list_businesses,
    save_crawl_pages,
    upsert_businesses,
)
from scrapers.base import Business


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", future=True)
    METADATA.create_all(eng)
    return eng


HOME_HTML = """
<html><head><title>Kedai Kopi Senja</title></head><body>
<nav>
  <a href="/">Home</a>
  <a href="/kontak-kami">Kontak Kami</a>
  <a href="/tentang">Tentang</a>
  <a href="https://other-site.com/page">external</a>
  <a href="mailto:halo@senjakopi.id">email kami</a>
</nav>
<h1>Kopi Senja</h1>
<footer class="site-footer">
  <p>Jl. Malioboro No. 1, Yogyakarta — Telp 0812-3456-7890</p>
</footer>
</body></html>
"""

CONTACT_HTML = """
<html><head><title>Kontak — Kopi Senja</title></head><body>
<h1>Hubungi Kami</h1>
<p>Email: halo@senjakopi.id atau cs@senjakopi.id</p>
<script>var x = 'ignore@scripts.id'</script>
</body></html>
"""


class TestIndustries:
    def test_load_and_match(self, tmp_path):
        f = tmp_path / "ind.yaml"
        f.write_text("include: [kopi, kafe]\nexclude: [warung]\n", encoding="utf-8")
        rules = load_industry_rules(f)
        assert rules.include == ("kopi", "kafe") and rules.exclude == ("warung",)
        assert matches_industry(rules, "Coffee Shop", "Senja") is False  # 'kopi' != 'coffee'
        assert matches_industry(rules, "Kedai Kopi", "A") is True
        assert matches_industry(rules, "Warung", "Kopi Senja") is False  # exclude wins

    def test_missing_file_disabled(self, tmp_path):
        rules = load_industry_rules(tmp_path / "nope.yaml")
        assert rules.enabled is False
        assert matches_industry(rules, "anything", "x") is False

    def test_case_insensitive(self):
        rules = IndustryRules(include=("clinic",))
        assert matches_industry(rules, "Dental CLINIC", "") is True

    def test_real_config_loads(self):
        rules = load_industry_rules()
        assert rules.enabled and "kopi" in rules.include

    def test_rules_off_queues_all_domains(self, engine):
        upsert_businesses(engine, [Business(name="Any", website="https://a.com")])
        queued = enqueue_crawl_domains(engine, industry_rules=IndustryRules())
        assert queued == 1  # disabled rules -> everything crawls

    def test_rules_filter_domains(self, engine):
        upsert_businesses(
            engine,
            [
                Business(name="Kafe Kopi", website="https://kopi.example", category="Coffee shop"),
                Business(name="Bengkel", website="https://bengkel.example", category="Auto repair"),
            ],
            industry_rules=IndustryRules(include=("kopi",)),
        )
        rows = list_businesses(engine)
        tagged = {r["name"]: r["industry_match"] for r in rows}
        assert tagged["Kafe Kopi"] is True and tagged["Bengkel"] is False
        queued = enqueue_crawl_domains(engine, industry_rules=IndustryRules(include=("kopi",)))
        assert queued == 1
        jobs = [j["domain"] for j in list_crawl_jobs(engine)]
        assert jobs == ["kopi.example"]


class TestRobots:
    def test_parse_allow_and_disallow(self, monkeypatch):
        robots_mod.clear_cache()
        text = "User-agent: *\nDisallow: /private/\nAllow: /"
        monkeypatch.setattr(
            robots_mod.requests, "get",
            lambda url, **kw: type("R", (), {"status_code": 200, "text": text})(),
        )
        assert robots_mod.allowed("https://a.com/", "bot") is True
        assert robots_mod.allowed("https://a.com/private/x", "bot") is False

    def test_404_means_allow(self, monkeypatch):
        robots_mod.clear_cache()
        monkeypatch.setattr(
            robots_mod.requests, "get",
            lambda url, **kw: type("R", (), {"status_code": 404, "text": ""})(),
        )
        assert robots_mod.allowed("https://a.com/anything", "bot") is True

    def test_network_error_means_allow(self, monkeypatch):
        import requests as real_requests

        robots_mod.clear_cache()
        def boom(url, **kw):
            raise real_requests.ConnectionError("down")
        monkeypatch.setattr(robots_mod.requests, "get", boom)
        assert robots_mod.allowed("https://a.com/", "bot") is True


class TestFetch:
    def test_retry_then_success(self, monkeypatch):
        calls = {"n": 0}
        class Resp:
            def __init__(self, code):
                self.status_code = code
                self.encoding = "utf-8"
            def iter_content(self, chunk_size=8192):
                return iter([b"<html>hi</html>"])
            def close(self):
                pass
        class NS:
            RequestException = Exception
            def get(self, url, **kw):
                calls["n"] += 1
                return Resp(500 if calls["n"] == 1 else 200)
        sleeps = []
        monkeypatch.setattr(fetch_mod, "requests", NS())
        result = fetch_mod.fetch("https://a.com/", "bot", retries=2, delay=0.01, sleep=sleeps.append)
        assert result.ok and result.html == "<html>hi</html>"
        assert calls["n"] == 2 and len(sleeps) == 1  # backed off once

    def test_403_no_retry(self, monkeypatch):
        calls = {"n": 0}
        class Resp:
            status_code = 403
            def iter_content(self, chunk_size=8192):
                return iter([])
            def close(self):
                pass
        class NS:
            RequestException = Exception
            def get(self, url, **kw):
                calls["n"] += 1
                return Resp()
        monkeypatch.setattr(fetch_mod, "requests", NS())
        result = fetch_mod.fetch("https://a.com/", "bot", retries=3, delay=0.01, sleep=lambda s: None)
        assert not result.ok and result.status == 403 and calls["n"] == 1


class TestParse:
    def test_links_mailtos_contact_detection(self):
        links = extract.parse_links(HOME_HTML, "https://senjakopi.id/")
        assert "https://senjakopi.id/kontak-kami" in links.contact_links
        assert "https://senjakopi.id/tentang" in links.contact_links
        assert "https://senjakopi.id/" in links.links
        assert all("other-site.com" not in u for u in links.links)  # external dropped
        assert "halo@senjakopi.id" in links.mailtos

    def test_page_text_drops_script(self):
        text = extract.page_text(CONTACT_HTML)
        assert "Hubungi Kami" in text and "ignore@scripts.id" not in text

    def test_title(self):
        assert extract.page_title(HOME_HTML) == "Kedai Kopi Senja"

    def test_footer(self):
        footer = extract.footer_text(HOME_HTML)
        assert "Malioboro" in footer and "0812-3456-7890" in footer

    def test_mailto_extraction(self):
        assert extract.extract_mailtos(HOME_HTML) == ["halo@senjakopi.id"]


class FakeCrawlHTTP:
    """Robots + pages served from a dict {path: (status, html)}."""

    def __init__(self, pages, robots_text=""):
        self.pages = pages
        self.robots_text = robots_text
        self.fetch_log: list[str] = []

    def install(self, monkeypatch):
        robots_mod.clear_cache()

        robots_ns = type(
            "RobotsNS", (), {"get": lambda url, **kw: type("R", (), {
                "status_code": 200 if self.robots_text else 404,
                "text": self.robots_text,
            })()},
        )
        monkeypatch.setattr(robots_mod, "requests", robots_ns)

        fetch_module = importlib.import_module("app.crawler.fetch")
        http = self

        class FetchNS:
            RequestException = Exception
            def get(self, url, **kw):
                http.fetch_log.append(url)
                path = url.split("/", 3)[-1]
                status, html = http.pages.get(path, (404, ""))
                holder = type("R", (), {})()
                holder.status_code = status
                holder.encoding = "utf-8"
                holder.iter_content = lambda chunk_size=8192: iter([html.encode()])
                holder.close = lambda: None
                return holder

        monkeypatch.setattr(fetch_module, "requests", FetchNS())


class TestCrawlEngine:
    def _http(self, monkeypatch, robots_text=""):
        http = FakeCrawlHTTP(
            pages={
                "": (200, HOME_HTML),
                "kontak-kami": (200, CONTACT_HTML),
            },
            robots_text=robots_text,
        )
        http.install(monkeypatch)
        return http

    def test_crawl_home_and_contact(self, monkeypatch):
        http = self._http(monkeypatch)
        outcome = crawl_domain(
            "senjakopi.id", delay_s=0, timeout_s=1, retries=0, max_pages=5
        )
        assert outcome.error == ""
        kinds = {p.url: p.kind for p in outcome.pages}
        assert kinds.get("https://senjakopi.id/") == "home"
        assert kinds.get("https://senjakopi.id/kontak-kami") == "contact"
        contact = next(p for p in outcome.pages if p.kind == "contact")
        assert "Hubungi Kami" in contact.text
        home = next(p for p in outcome.pages if p.kind == "home")
        assert "halo@senjakopi.id" in home.mailtos  # mailto link harvested during crawl
        assert "Malioboro" in home.footer  # footer extraction on the homepage
        assert "Kopi Senja" in home.text

    def test_robots_disallow_blocks_crawl(self, monkeypatch):
        http = self._http(monkeypatch, robots_text="User-agent: *\nDisallow: /")
        outcome = crawl_domain(
            "senjakopi.id", delay_s=0, timeout_s=1, retries=0, max_pages=5
        )
        assert "disallow" in outcome.error.lower()
        assert http.fetch_log == []  # nothing fetched

    def test_homepage_down_fails_job(self, monkeypatch):
        http = FakeCrawlHTTP(pages={}, robots_text="")
        http.pages[""] = (503, "")
        http.install(monkeypatch)
        outcome = crawl_domain(
            "senjakopi.id", delay_s=0, timeout_s=1, retries=0, max_pages=5
        )
        assert "homepage fetch failed" in outcome.error

    def test_politeness_delay_between_pages(self, monkeypatch):
        http = self._http(monkeypatch)
        sleeps: list[float] = []
        crawl_domain(
            "senjakopi.id", delay_s=1.5, timeout_s=1, retries=0,
            max_pages=5, sleep=sleeps.append,
        )
        assert 1.5 in sleeps  # polite delay actually applied


class TestCrawlStore:
    def _seed(self, engine):
        upsert_businesses(engine, [Business(name="Kafe X", website="https://x.example", category="Coffee shop")])

    def test_enqueue_claim_complete_cycle(self, engine):
        self._seed(engine)
        assert enqueue_crawl_domains(engine) == 1
        assert enqueue_crawl_domains(engine) == 0  # dedup by domain
        job = claim_next_crawl(engine)
        assert job is not None and job["domain"] == "x.example"
        assert claim_next_crawl(engine) is None
        outcome = CrawlOutcome(
            domain="x.example",
            pages=[
                CrawledPage(url="https://x.example/", kind="home", fetched_ok=True, text="t", mailtos=["a@x.example"]),
                CrawledPage(url="https://x.example/contact", kind="contact", fetched_ok=True, text="c"),
            ],
        )
        stored = save_crawl_pages(engine, job["id"], outcome.pages)
        assert stored == 2
        complete_crawl_job(engine, job["id"], "done", pages_crawled=2, outcome=outcome)
        jobs = list_crawl_jobs(engine)
        assert jobs[0]["status"] == "done"
        assert jobs[0]["contact_url"] == "https://x.example/contact"
        assert jobs[0]["mailto_count"] == 1
        from sqlalchemy import select

        with engine.connect() as conn:
            rows = conn.execute(select(CRAWL_PAGES.c.url).order_by(CRAWL_PAGES.c.id)).scalars().all()
        assert rows == ["https://x.example/", "https://x.example/contact"]

    def test_requeued_after_failure(self, engine):
        self._seed(engine)
        enqueue_crawl_domains(engine)
        job = claim_next_crawl(engine)
        complete_crawl_job(engine, job["id"], "failed", error="boom")
        # failed crawl jobs are terminal (per-request retries already ran);
        # scheduled retry passes are a PHASE 6 concern, not auto-requeue
        assert enqueue_crawl_domains(engine) == 0
        assert count_crawl_jobs(engine, status="pending") == 0

    def test_worker_runner_never_raises(self, engine, monkeypatch):
        from app import crawl as crawl_mod

        self._seed(engine)
        enqueue_crawl_domains(engine)

        def crash(domain, **kw):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(crawl_mod, "crawl_domain", crash)
        stats = crawl_mod.run_pending_crawls(engine)
        assert stats["jobs"] == 1 and stats["ok"] == 0
        jobs = list_crawl_jobs(engine)
        assert jobs[0]["status"] == "failed"
        assert "RuntimeError" in jobs[0]["error"]
