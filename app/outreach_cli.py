"""Outreach CLI (PHASE 6).

Manual/testing tool — production runs campaigns via the worker.

    python -m app.outreach_cli campaign-create --name x --subject y \
        --body-file data/body.txt [--followup-days 3] [--min-score 60]
    python -m app.outreach_cli campaign-run --id 1 [--limit 5]
    python -m app.outreach_cli followups
    python -m app.outreach_cli bounces --file data/bounces.csv
    python -m app.outreach_cli preview --id 1 --lead 3
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.db import get_engine, init_db
from config import settings
from config.logging_setup import setup_logging

log = logging.getLogger(__name__)


def _cmd_campaign_create(args) -> int:
    from app.outreach.campaign import create_campaign

    body_text = (
        open(args.body_file, encoding="utf-8").read() if args.body_file else ""
    )
    body_html = (
        open(args.html_file, encoding="utf-8").read() if args.html_file else ""
    )
    try:
        campaign_id = create_campaign(
            get_engine(),
            name=args.name,
            subject=args.subject,
            body_text=body_text,
            body_html=body_html,
            followup_days=args.followup_days,
            min_score=args.min_score,
            email_statuses=args.email_statuses,
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"campaign {campaign_id} created (draft): {args.name}")
    return 0


def _cmd_campaign_run(args) -> int:
    from app.outreach.campaign import run_campaign

    stats = run_campaign(get_engine(), args.id, limit=args.limit)
    mode = "DRY" if stats.get("mode") != "live" else "LIVE"
    print(f"[{mode}] campaign {stats['campaign']}: sent={stats['sent']} "
          f"sent_dry={stats['sent_dry']} failed={stats['failed']} "
          f"dup={stats['skipped_duplicate']} limit={stats['skipped_daily_limit']}")
    if stats.get("error"):
        print(f"error: {stats['error']}")
        return 1
    return 0


def _set_campaign_status(campaign_id: int, status: str) -> int:
    from sqlalchemy import update as sa_update

    from app.db import CAMPAIGNS

    with get_engine().begin() as conn:
        conn.execute(
            sa_update(CAMPAIGNS).where(CAMPAIGNS.c.id == campaign_id).values(status=status)
        )
    print(f"campaign {campaign_id} -> {status}")
    return 0


def _cmd_campaign_start(args) -> int:
    return _set_campaign_status(args.id, "running")


def _cmd_campaign_pause(args) -> int:
    return _set_campaign_status(args.id, "paused")


def _cmd_followups(args) -> int:
    from app.outreach.campaign import run_followups

    stats = run_followups(get_engine(), limit=args.limit)
    print(f"followups: checked={stats['checked']} sent={stats['sent']} "
          f"sent_dry={stats['sent_dry']} failed={stats['failed']} "
          f"dup={stats['skipped_duplicate']}")
    if stats.get("error"):
        print(f"error: {stats['error']}")
        return 1
    return 0


def _cmd_bounces(args) -> int:
    from app.outreach.bounce import mark_bounces

    entries: list[tuple[str, str]] = []
    try:
        for line in open(args.file, encoding="utf-8"):
            line = line.strip()
            if not line or line.lower().startswith(("email", "#")):
                continue
            parts = [p.strip() for p in line.split(",", 1)]
            entries.append((parts[0], parts[1] if len(parts) > 1 else ""))
    except OSError as exc:
        print(f"error: cannot read {args.file}: {exc}")
        return 1
    stats = mark_bounces(get_engine(), entries, source=f"cli:{args.file}")
    print(f"bounces: hard={stats['hard']} soft={stats['soft']} skipped={stats['skipped']}")
    if stats.get("error"):
        print(f"error: {stats['error']}")
        return 1
    return 0


def _cmd_preview(args) -> int:
    from app.outreach.campaign import get_campaign, _lead_by_id, _unsubscribe_url
    from app.outreach.template import render_message

    campaign = get_campaign(get_engine(), args.id)
    if not campaign:
        print(f"campaign {args.id} not found")
        return 1
    lead = _lead_by_id(get_engine(), args.lead)
    if not lead:
        print(f"lead {args.lead} not found")
        return 1
    subject, body_text, _html = render_message(
        lead,
        campaign["subject"],
        campaign["body_text"],
        campaign["body_html"],
        settings.sender_name,
        settings.smtp_from or "noreply@marketing.local",
        _unsubscribe_url(lead["best_email"]),
    )
    print(f"--- TO: {lead['best_email']}")
    print(f"--- SUBJECT: {subject}")
    print()
    print(body_text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.outreach_cli", description="Outreach campaign tools (DRY RUN default)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("campaign-create", help="create a draft campaign")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--subject", required=True)
    p_create.add_argument("--body-file", help="plain text body file")
    p_create.add_argument("--html-file", help="HTML body file")
    p_create.add_argument("--followup-days", type=int, default=0)
    p_create.add_argument("--min-score", type=int, default=0)
    p_create.add_argument("--email-statuses", default="valid,unknown")
    p_create.set_defaults(func=_cmd_campaign_create)

    p_run = sub.add_parser("campaign-run", help="run one batch (DRY RUN by default)")
    p_run.add_argument("--id", type=int, required=True)
    p_run.add_argument("--limit", type=int, default=None)
    p_run.set_defaults(func=_cmd_campaign_run)

    p_start = sub.add_parser("campaign-start", help="set campaign status=running (worker picks it up)")
    p_start.add_argument("--id", type=int, required=True)
    p_start.set_defaults(func=_cmd_campaign_start)

    p_pause = sub.add_parser("campaign-pause", help="set campaign status=paused")
    p_pause.add_argument("--id", type=int, required=True)
    p_pause.set_defaults(func=_cmd_campaign_pause)

    p_follow = sub.add_parser("followups", help="run follow-up scheduler once")
    p_follow.add_argument("--limit", type=int, default=None)
    p_follow.set_defaults(func=_cmd_followups)

    p_bounce = sub.add_parser("bounces", help="import bounces (hard -> suppress)")
    p_bounce.add_argument("--file", required=True)
    p_bounce.set_defaults(func=_cmd_bounces)

    p_preview = sub.add_parser("preview", help="render an email for one lead")
    p_preview.add_argument("--id", type=int, required=True, help="campaign id")
    p_preview.add_argument("--lead", type=int, required=True, help="lead id")
    p_preview.set_defaults(func=_cmd_preview)

    args = parser.parse_args(argv)
    setup_logging("outreach-cli")
    init_db()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
