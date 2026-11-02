"""Manual crawl tool for testing (same pattern as scrapers/run.py).

Usage:
    .venv/bin/python -m app.crawl_cli --domain example.com   # crawl satu domain, print ringkasan
    .venv/bin/python -m app.crawl_cli --limit 3              # jalankan 3 job dari queue (live)
    .venv/bin/python -m app.crawl_cli --enqueue              # queue domain dari businesses
    .venv/bin/python -m app.crawl_cli --list                 # lihat job terakhir
    .venv/bin/python -m app.crawl_cli --pages <job_id>       # lihat halaman hasil job

Production berjalan lewat worker/scheduler — CLI ini hanya untuk verifikasi
manual dan debugging.
"""

from __future__ import annotations

import argparse
import sys

from app.crawler import crawl_domain
from app.crawl import enqueue_crawls, run_pending_crawls
from app.db import get_engine, init_db
from app.store import list_crawl_jobs


def _print_outcome(outcome) -> None:
    ok_pages = [p for p in outcome.pages if p.fetched_ok]
    print(f"domain: {outcome.domain}")
    if outcome.error:
        print(f"error : {outcome.error}")
    print(f"pages fetched OK: {len(ok_pages)}/{len(outcome.pages)}")
    for page in ok_pages:
        emails = ", ".join(page.mailtos) or "-"
        print(f"  [{page.kind:7}] {page.url}")
        print(f"           title: {(page.title or '-')[:70]}")
        if page.mailtos:
            print(f"           mailto: {emails}")
    contact = [p.url for p in ok_pages if p.kind == "contact"]
    about = [p.url for p in ok_pages if p.kind == "about"]
    if contact:
        print(f"contact pages: {', '.join(contact)}")
    if about:
        print(f"about pages  : {', '.join(about)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.crawl", description="Manual website crawler (PHASE 3)"
    )
    parser.add_argument("--domain", help="crawl single domain now (no queue)")
    parser.add_argument("--limit", type=int, help="run N pending crawl jobs from the queue")
    parser.add_argument("--enqueue", action="store_true", help="queue business domains")
    parser.add_argument("--list", action="store_true", help="show recent crawl jobs")
    parser.add_argument("--pages", type=int, metavar="JOB_ID", help="show pages of a job")
    args = parser.parse_args(argv)

    if not any((args.domain, args.limit, args.enqueue, args.list, args.pages)):
        parser.print_help()
        return 0

    if args.domain:
        outcome = crawl_domain(args.domain.lstrip("https://").strip("/"))
        _print_outcome(outcome)
        return 0 if not outcome.error else 1

    engine = get_engine()
    init_db()

    if args.enqueue:
        queued = enqueue_crawls(engine)
        print(f"queued: {queued} crawl job(s)")
        return 0

    if args.limit:
        stats = run_pending_crawls(engine, limit=args.limit)
        print(
            f"crawl batch: {stats['jobs']} job(s), {stats['ok']} ok, "
            f"{stats['pending']} pending left"
        )
        for job in list_crawl_jobs(engine, limit=args.limit):
            print(
                f"  #{job['id']} {job['domain']:32} -> {job['status']:7} "
                f"pages={job['pages_crawled']} mailto={job['mailto_count']}"
                + (f" error={job['error'][:60]}" if job['error'] else "")
            )
        return 0

    if args.list:
        for job in list_crawl_jobs(engine, limit=20):
            print(
                f"  #{job['id']} {job['domain']:32} {job['status']:7} "
                f"pages={job['pages_crawled']} contact={job['contact_url'] or '-'}"
            )
        return 0

    if args.pages:
        from app.db import CRAWL_PAGES
        from sqlalchemy import select

        with engine.connect() as conn:
            rows = conn.execute(
                select(CRAWL_PAGES)
                .where(CRAWL_PAGES.c.crawl_job_id == args.pages)
                .order_by(CRAWL_PAGES.c.id)
            ).mappings()
            found = False
            for row in rows:
                found = True
                print(
                    f"  [{row['kind']:7}] {row['url']} (HTTP {row['http_status']}, "
                    f"{len(row['text'] or '')} chars)"
                )
            if not found:
                print(f"no pages stored for job #{args.pages}")
                return 1
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
