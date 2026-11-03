"""Lead CSV export (PHASE 5).

Library: export_leads_csv(engine, path, ...).
CLI: python -m app.export [--out data/leads.csv] [--min-score 30]
                          [--email-status valid|unknown|any] [--limit 500]

CSV: utf-8-sig + CRLF so Excel opens it cleanly. The output path comes
from the operator (CLI flag); parents are created, the file is write-only
artefact — never read back, never executed.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
from pathlib import Path

from sqlalchemy.engine import Engine

from app.db import get_engine
from app.store import list_leads

log = logging.getLogger(__name__)

COLUMNS = [
    "score",
    "name",
    "best_email",
    "email_status",
    "best_phone",
    "category",
    "address",
    "domain",
    "lead_status",
    "score_detail",
    "updated_at",
]


def _write_leads_csv(rows: list[dict], fh) -> None:
    writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "score": row["score"],
                "name": row["name"],
                "best_email": row["best_email"],
                "email_status": row["email_status"],
                "best_phone": row["best_phone"],
                "category": row["category"],
                "address": row["address"],
                "domain": row["domain"],
                "lead_status": row["status"],
                "score_detail": row["score_detail"],
                "updated_at": row["updated_at"].isoformat()
                if row["updated_at"]
                else "",
            }
        )


def export_leads_csv(
    engine: Engine,
    path: str | Path,
    min_score: int = 0,
    email_status: str | None = None,
    limit: int = 500,
) -> dict:
    """Write leads to CSV. Returns {rows, path}."""
    rows = list_leads(
        engine, limit=limit, min_score=min_score,
        email_status=None if email_status in (None, "any") else email_status,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        _write_leads_csv(rows, fh)
    log.info("exported %s lead(s) to %s", len(rows), path)
    return {"rows": len(rows), "path": str(path)}


def leads_csv_bytes(
    engine: Engine,
    min_score: int = 0,
    email_status: str | None = None,
    limit: int = 500,
) -> bytes:
    """Same CSV stream, in memory — used by the dashboard download button."""
    rows = list_leads(
        engine, limit=limit, min_score=min_score,
        email_status=None if email_status in (None, "any") else email_status,
    )
    buf = io.StringIO()
    _write_leads_csv(rows, buf)
    return buf.getvalue().encode("utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.export", description="Export leads to CSV"
    )
    parser.add_argument("--out", default="data/leads.csv", help="output CSV path")
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument(
        "--email-status",
        default="any",
        choices=["any", "valid", "unknown", "invalid", "unchecked"],
    )
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)

    from config.logging_setup import setup_logging

    setup_logging("export")
    result = export_leads_csv(
        get_engine(),
        args.out,
        min_score=args.min_score,
        email_status=args.email_status,
        limit=args.limit,
    )
    print(f"exported {result['rows']} lead(s) -> {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
