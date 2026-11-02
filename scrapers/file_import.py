"""File import adapters: CSV / JSON / XLSX -> Business records.

Bootstrap path when leads already exist in a spreadsheet: the importers
implement the same SourceAdapter contract as the HTTP sources, so the
discovery pipeline (registry -> adapter.search() -> store) stays uniform.
`search()` ignores query/location — a file importer returns every row.

Each adapter reads its input path from an env var (CSV_IMPORT_PATH,
JSON_IMPORT_PATH, XLSX_IMPORT_PATH); relative paths resolve against the
repo root. Unset path or missing file returns SearchResult with `error`
set, never raises.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

from config import get as env_get

from .base import Business, SearchResult, SourceAdapter

log = logging.getLogger(__name__)

# Header aliases per Business field (first match wins, case-insensitive).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "nama", "business", "business_name", "title"),
    "address": ("address", "alamat", "addr", "location"),
    "phone": ("phone", "telepon", "tel", "telephone", "no_telp", "whatsapp", "wa"),
    "website": ("website", "web", "url", "site", "situs"),
    "category": ("category", "kategori", "type", "jenis", "industry"),
    "rating": ("rating", "nilai"),
    "review_count": ("review_count", "reviews", "reviews_count", "ulasan", "jumlah_ulasan"),
    "place_id": ("place_id", "google_place_id", "id"),
}


def _resolve_path(raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (Path(__file__).resolve().parent.parent / p)


def _pick(row: dict[str, Any], field: str) -> Any:
    """First non-empty value among the row's keys matching the aliases."""
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in COLUMN_ALIASES[field]:
        val = lowered.get(alias)
        if val not in (None, ""):
            return val
    return ""


def _to_float(val: Any) -> float | None:
    try:
        return float(str(val).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_int(val: Any) -> int | None:
    try:
        return int(float(str(val).replace(",", "")))
    except (TypeError, ValueError):
        return None


def row_to_business(row: dict[str, Any]) -> Business | None:
    """Map one dict row (CSV header row, JSON object, XLSX row) to Business.
    Returns None when no name-like field has a value."""
    name = str(_pick(row, "name") or "").strip()
    if not name:
        return None
    return Business(
        name=name,
        address=str(_pick(row, "address") or "").strip(),
        phone=str(_pick(row, "phone") or "").strip(),
        website=str(_pick(row, "website") or "").strip(),
        category=str(_pick(row, "category") or "").strip(),
        rating=_to_float(_pick(row, "rating")),
        review_count=_to_int(_pick(row, "review_count")),
        place_id=str(_pick(row, "place_id") or "").strip(),
        source="",  # set by the adapter
    )


class FileImportAdapter(SourceAdapter):
    """Shared file-import plumbing. Subclasses fill `source_name` /
    `source_label` / `path_env` and implement `_read_rows()`."""

    path_env = ""  # e.g. "CSV_IMPORT_PATH"

    def __init__(self, path: str | Path | None = None):
        raw = str(path) if path is not None else env_get(self.path_env, "")
        self._path = _resolve_path(raw) if raw.strip() else None

    def configured(self) -> bool:
        return bool(self._path and self._path.is_file())

    def key_hint(self) -> str:
        return self.path_env

    def _read_rows(self) -> Iterable[dict[str, Any]]:
        raise NotImplementedError

    def search(self, query: str, location: str = "", **kwargs: Any) -> SearchResult:
        if not self._path:
            return self._empty(f"no input file configured (set {self.path_env})")
        if not self._path.is_file():
            return self._empty(f"input file not found: {self._path}")
        try:
            rows = list(self._read_rows())
        except (OSError, ValueError) as exc:
            return self._empty(f"failed to read {self._path}: {exc}")
        businesses: list[Business] = []
        seen: set[str] = set()
        for row in rows:
            biz = row_to_business(row)
            if biz is None:
                continue
            biz.source = self.source_name
            if biz.key not in seen:
                seen.add(biz.key)
                businesses.append(biz)
        return SearchResult(
            businesses=businesses, source=self.source_name, query="", location=""
        )

    def _empty(self, error: str) -> SearchResult:
        return SearchResult(businesses=[], source=self.source_name, query="", location="", error=error)


class CsvImportAdapter(FileImportAdapter):
    source_name = "csv_import"
    source_label = "CSV file import"
    path_env = "CSV_IMPORT_PATH"

    def _read_rows(self) -> Iterable[dict[str, Any]]:
        assert self._path is not None  # guarded by search()/configured()
        with self._path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                yield dict(row)


class JsonImportAdapter(FileImportAdapter):
    source_name = "json_import"
    source_label = "JSON file import"
    path_env = "JSON_IMPORT_PATH"

    def _read_rows(self) -> Iterable[dict[str, Any]]:
        assert self._path is not None  # guarded by search()/configured()
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # {"businesses": [...]} wrapper or a single record dict
            for key in ("businesses", "results", "items", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        if isinstance(data, list):
            return data
        raise ValueError(f"unsupported JSON structure: {type(data).__name__}")


class XlsxImportAdapter(FileImportAdapter):
    source_name = "xlsx_import"
    source_label = "XLSX file import"
    path_env = "XLSX_IMPORT_PATH"

    def _read_rows(self) -> Iterable[dict[str, Any]]:
        from openpyxl import load_workbook  # deferred: heavy import

        assert self._path is not None  # guarded by search()/configured()
        workbook = load_workbook(self._path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                return []
            keys = [str(c).strip() if c is not None else "" for c in header]
            out = []
            for values in rows:
                if all(v is None or str(v).strip() == "" for v in values):
                    continue  # skip fully empty rows
                out.append(dict(zip(keys, values)))
            return out
        finally:
            workbook.close()
