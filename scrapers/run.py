"""CLI untuk test source adapter manual.

Usage:
    python -m scrapers.run "kedai kopi"                       # default LEAD_SOURCE
    python -m scrapers.run "kedai kopi" --source serpapi
    python -m scrapers.run "kedai kopi" --source gmaps_scrape --location Yogyakarta --max 20
    python -m scrapers.run "kedai kopi" --source csv_import   # baca CSV_IMPORT_PATH

Output ringkas per record + summary di akhir. Jangan dipakai untuk bulk
scraping — ini alat verifikasi; loop produksi ada di worker (PHASE 2).
"""

from __future__ import annotations

import argparse
import os
import sys

from scrapers import get_adapter, list_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scrapers.run",
        description="Search businesses via the configured source adapter.",
    )
    parser.add_argument("query", help="search query (ignored by file importers)")
    parser.add_argument(
        "--source", default=None, choices=sorted(list_sources()),
        help="source adapter name (default: LEAD_SOURCE env, gmaps_scrape)",
    )
    parser.add_argument("--location", default="", help="location hint (city/region)")
    parser.add_argument("--max", type=int, default=20, help="max results (default 20)")
    parser.add_argument(
        "--path", default=None,
        help="input file path for importers (sets CSV/JSON/XLSX_IMPORT_PATH)",
    )
    parser.add_argument(
        "--out", default=None,
        help="write results to CSV (default columns; data/ is gitignored)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        adapter = get_adapter(args.source)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.path:
        # file importers read their path env at __init__; re-instantiate so
        # the CLI-supplied path is picked up without shell env juggling
        path_env = getattr(adapter, "path_env", "")
        if not path_env:
            print(f"error: --path not supported by {adapter.source_name}", file=sys.stderr)
            return 2
        os.environ[path_env] = args.path
        adapter = get_adapter(args.source)

    print(f"source: {adapter.source_name} ({adapter.source_label})")
    print(f"query:  {args.query!r} location={args.location!r} max={args.max}")
    if not adapter.configured():
        print(f"not configured: set {adapter.key_hint()}", file=sys.stderr)
        return 1

    result = adapter.search(args.query, location=args.location, max_results=args.max)
    if result.error:
        print(f"error: {result.error}", file=sys.stderr)

    for biz in result.businesses:
        rating = f"{biz.rating:.1f}" if biz.rating is not None else "  - "
        reviews = str(biz.review_count) if biz.review_count is not None else "-"
        print(
            f"  {rating} ({reviews:>4}) {biz.name[:44]:<44} "
            f"tel={biz.phone or '-':<18} web={'Y' if biz.has_website else 'n'} "
            f"cat={biz.category or '-'}"
        )

    print(
        f"\n{len(result.businesses)} records | source={result.source}"
        + (f" | error={result.error}" if result.error else "")
    )
    if args.out and result.businesses:
        out_path = write_csv(result.businesses, args.out)
        print(f"saved: {out_path}")
    return 1 if result.error else 0


def write_csv(businesses, out_path: str) -> str:
    """Persist results to CSV (UTF-8, Excel-friendly). Creates parent dirs."""
    import csv
    from pathlib import Path

    path = Path(out_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name", "address", "phone", "website", "category",
        "rating", "review_count", "place_id", "latitude", "longitude",
        "source", "source_url", "email",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for biz in businesses:
            writer.writerow({f: getattr(biz, f, "") for f in fields})
    return str(path)


if __name__ == "__main__":
    sys.exit(main())
