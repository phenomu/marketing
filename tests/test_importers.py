"""File importer tests: CSV/JSON/XLSX fixtures via tmp_path, error paths.

Covers column alias mapping (EN + ID headers), wrapper/list JSON shapes,
empty-row skipping, dedup, and the never-raise contract for unset path /
missing file / malformed content.
"""

from __future__ import annotations

import json

import pytest

from scrapers.file_import import (
    CsvImportAdapter,
    JsonImportAdapter,
    row_to_business,
    XlsxImportAdapter,
)


def write_csv(path, rows: list[list[str]]) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


class TestRowToBusiness:
    def test_en_headers(self):
        biz = row_to_business(
            {"Name": "Toko Kopi", "Phone": "0812", "Website": "https://t.co", "Rating": "4.8"}
        )
        assert biz is not None
        assert biz.name == "Toko Kopi"
        assert biz.phone == "0812"
        assert biz.website == "https://t.co"
        assert biz.rating == 4.8

    def test_id_headers(self):
        biz = row_to_business(
            {"Nama": "Warung Sate", "Telepon": "0274", "Situs": "https://w.id", "Ulasan": "120"}
        )
        assert biz is not None
        assert biz.name == "Warung Sate"
        assert biz.phone == "0274"
        assert biz.website == "https://w.id"
        assert biz.review_count == 120

    def test_no_name_returns_none(self):
        assert row_to_business({"Phone": "0812"}) is None
        assert row_to_business({}) is None

    def test_bad_numbers_stay_none(self):
        biz = row_to_business({"Name": "X", "Rating": "n/a", "Ulasan": "-"})
        assert biz is not None
        assert biz.rating is None
        assert biz.review_count is None


class TestCsvImport:
    def test_imports_and_dedups(self, tmp_path):
        csv_path = tmp_path / "leads.csv"
        write_csv(
            csv_path,
            [
                ["name", "phone", "website"],
                ["Toko A", "0811", "https://a.com"],
                ["Toko A", "0811", "https://a.com"],  # dup by name+address
                ["Toko B", "0822", ""],
            ],
        )
        result = CsvImportAdapter(path=csv_path).search("ignored")
        assert result.error == ""
        assert len(result.businesses) == 2
        assert result.businesses[0].name == "Toko A"
        assert result.businesses[0].source == "csv_import"

    def test_missing_file_error(self, tmp_path):
        result = CsvImportAdapter(path=tmp_path / "nope.csv").search("x")
        assert result.businesses == []
        assert "not found" in result.error

    def test_unset_path_error(self):
        result = CsvImportAdapter(path="").search("x")
        assert result.businesses == []
        assert "CSV_IMPORT_PATH" in result.error


class TestJsonImport:
    def test_list_shape(self, tmp_path):
        p = tmp_path / "leads.json"
        p.write_text(
            json.dumps([{"name": "A"}, {"nama": "B"}, {"phone": "1"}]), encoding="utf-8"
        )
        result = JsonImportAdapter(path=p).search("")
        assert [b.name for b in result.businesses] == ["A", "B"]

    def test_wrapper_shape(self, tmp_path):
        p = tmp_path / "leads.json"
        p.write_text(
            json.dumps({"businesses": [{"name": "A", "rating": 4.5}]}), encoding="utf-8"
        )
        result = JsonImportAdapter(path=p).search("")
        assert len(result.businesses) == 1
        assert result.businesses[0].rating == 4.5

    def test_malformed_json_error(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        result = JsonImportAdapter(path=p).search("")
        assert result.businesses == []
        assert "failed to read" in result.error


class TestXlsxImport:
    @pytest.fixture
    def xlsx_path(self, tmp_path):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["Nama", "Telepon", "Situs"])
        ws.append(["Kedai X", "0899", "https://x.id"])
        ws.append([])  # fully empty row — must be skipped
        ws.append(["Kedai Y", "", ""])
        p = tmp_path / "leads.xlsx"
        wb.save(p)
        return p

    def test_imports_rows(self, xlsx_path):
        result = XlsxImportAdapter(path=xlsx_path).search("")
        names = [b.name for b in result.businesses]
        assert "Kedai X" in names and "Kedai Y" in names
        kedai_x = result.businesses[0]
        assert kedai_x.phone == "0899"
        assert kedai_x.website == "https://x.id"
        assert kedai_x.source == "xlsx_import"

    def test_unset_path_error(self):
        result = XlsxImportAdapter(path="").search("")
        assert "XLSX_IMPORT_PATH" in result.error
