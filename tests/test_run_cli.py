"""CLI runner tests: arg parsing, output, exit codes (no network)."""

from __future__ import annotations

import csv

from scrapers.run import build_parser, main


def test_parser_defaults(monkeypatch):
    monkeypatch.delenv("LEAD_SOURCE", raising=False)
    args = build_parser().parse_args(["kedai kopi"])
    assert args.query == "kedai kopi"
    assert args.source is None
    assert args.location == ""
    assert args.max == 20


def test_parser_explicit_source():
    args = build_parser().parse_args(
        ["bakery", "--source", "csv_import", "--location", "Solo", "--max", "5"]
    )
    assert args.source == "csv_import"
    assert args.location == "Solo"
    assert args.max == 5


def test_csv_import_run_outputs_records_and_exits_zero(tmp_path, capsys):
    csv_path = tmp_path / "leads.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(
            [
                ["name", "phone", "website"],
                ["Kafe Uji", "0812", "https://uji.id"],
            ]
        )
    code = main(["apapun", "--source", "csv_import", "--path", str(csv_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Kafe Uji" in out
    assert "csv_import" in out


def test_unconfigured_source_exits_nonzero(capsys, monkeypatch):
    # file importer without a path configured
    monkeypatch.delenv("CSV_IMPORT_PATH", raising=False)
    code = main(["x", "--source", "csv_import"])
    err = capsys.readouterr().err
    assert code == 1
    assert "CSV_IMPORT_PATH" in err
