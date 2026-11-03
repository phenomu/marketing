"""PHASE 9 backup/restore script tests (scripts/backup_db.py).

Live round-trip (backup → verify → restore against the real PG
container) is run manually and recorded in TRACKER (T-051); these unit
tests cover the pure parsing/rotation logic hermetically — no docker,
no database, no network (D-020).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backup_db  # noqa: E402


TOC_SAMPLE = """\
;
; Archive created at 2026-11-03 12:54:57 UTC
;     dbname: marketing
;
217; 1259 16389 TABLE public app_meta marketing
219; 1259 16395 TABLE public businesses marketing
218; 1259 16394 SEQUENCE public businesses_id_seq marketing
3556; 0 16395 TABLE DATA public businesses marketing
3579; 0 0 SEQUENCE OWNED BY public businesses_id_seq marketing
356; 0 0 INDEX public businesses_pkey marketing
"""


def test_toc_table_parsing_filters_data_and_sequences() -> None:
    """The verify() parser must list real tables only: TABLE entries yes,
    TABLE DATA / SEQUENCE / INDEX / comments no."""
    tables = backup_db._parse_toc_tables(TOC_SAMPLE)
    assert tables == ["app_meta", "businesses"]


def test_toc_parsing_empty_and_garbage() -> None:
    assert backup_db._parse_toc_tables("") == []
    assert backup_db._parse_toc_tables("\n\n; comment\n") == []
    assert backup_db._parse_toc_tables("not a toc at all") == []


def test_toc_parsing_weird_spacing() -> None:
    line = "231; 1259 16570 TABLE public campaigns marketing\n"
    assert backup_db._parse_toc_tables(line) == ["campaigns"]


def test_pg_parts_from_database_url() -> None:
    parts = backup_db._pg_parts_from_url(
        "postgresql://user:pw@db.example.com:5433/mkt"
    )
    assert parts == ("user", "pw", 5433, "db.example.com", "mkt")


def test_pg_parts_from_url_defaults() -> None:
    parts = backup_db._pg_parts_from_url("postgresql://u@h/db")
    # missing port → default 5432; missing password → empty
    assert parts == ("u", "", 5432, "h", "db")


def test_pg_parts_from_url_bare() -> None:
    assert backup_db._pg_parts_from_url("postgresql://nohost") == (
        "marketing", "", 5432, "nohost", "marketing",
    )


def test_backup_refuses_without_password(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(backup_db, "_pg_parts", lambda: ("u", "", 5432, "h", "d"))
    with pytest.raises(SystemExit) as exc:
        backup_db.do_backup(keep=5)
    assert exc.value.code == 2


def test_restore_requires_confirm_flag(tmp_path) -> None:
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        backup_db.do_restore(dump, confirmed=False)
    assert exc.value.code == 3


def test_restore_requires_existing_file(tmp_path) -> None:
    with pytest.raises(SystemExit) as exc:
        backup_db.do_restore(tmp_path / "missing.dump", confirmed=True)
    assert exc.value.code == 3


def test_rotation_keeps_newest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(backup_db, "REPO_ROOT", tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # three fake dumps, oldest first by mtime
    names = []
    for i, stamp in enumerate(["20260101T0000Z", "20260102T0000Z", "20260103T0000Z"]):
        p = backup_dir / f"marketing-marketing-{stamp}.dump"
        p.write_bytes(b"x")
        import os

        os.utime(p, (1600000000 + i * 100, 1600000000 + i * 100))
        names.append(p)
    removed = backup_db._rotate(backup_dir, keep=2)
    assert len(removed) == 1
    assert removed[0].name == "marketing-marketing-20260101T0000Z.dump"
    remaining = sorted(p.name for p in backup_dir.glob("marketing-*.dump"))
    assert remaining == [
        "marketing-marketing-20260102T0000Z.dump",
        "marketing-marketing-20260103T0000Z.dump",
    ]
