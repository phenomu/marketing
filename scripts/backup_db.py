#!/usr/bin/env python3
"""MARKETING — PostgreSQL backup / restore (PHASE 9).

Backup:  pg_dump custom format (-Fc) into backups/ with a UTC timestamp,
         rotated to keep the newest N files. When the database server
         runs in the compose `db` container, that container's own
         pg_dump is used (version always matches the server) and the
         dump is docker-cp'd out; otherwise host pg_dump is used.
Restore: pg_restore --clean --if-exists --single-transaction — either
         the whole dump applies or nothing changes. Requires an explicit
         --confirm-my-data flag because it REPLACES the database.
Verify:  pg_restore --list — shows table inventory of a dump.

Connection settings come from the same env/.env the app uses; the
password only travels via PGPASSWORD env (never argv).

Exit codes: 0 ok, 1 usage, 2 backup failed, 3 restore/verify failed.

Usage:
  python scripts/backup_db.py backup              # backup now (keep 14)
  python scripts/backup_db.py backup --keep 30
  python scripts/backup_db.py verify backups/marketing-...dump
  python scripts/backup_db.py restore backups/marketing-...dump --confirm-my-data

Override the server container name with DB_BACKUP_CONTAINER (default
marketing-db); set it empty to force host tools.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import get  # noqa: E402

DB_CONTAINER = (get("DB_BACKUP_CONTAINER", "marketing-db") or "").strip()


def _parse_toc_tables(toc: str) -> list[str]:
    """Table names from a pg_restore --list TOC. Lines look like:
    "217; 1259 16389 TABLE public app_meta marketing"
    (oid; catalog-oid objoid TYPE schema name owner) — name = field 6.
    "TABLE DATA" entries (data payloads) are two words in the TYPE field
    and must not be listed; SEQUENCE/INDEX/COMMENT lines are skipped."""
    tables: list[str] = []
    for line in toc.splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[3] == "TABLE" and fields[4] != "DATA":
            tables.append(fields[5])
    return tables


def _pg_parts_from_url(url: str) -> tuple[str, str, int, str, str]:
    """(user, password, port, host, dbname) from a postgresql:// URL with
    sensible defaults for missing parts."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return (
        parts.username or "marketing",
        parts.password or "",
        parts.port or 5432,
        parts.hostname or "127.0.0.1",
        parts.path.lstrip("/") or "marketing",
    )


def _rotate(backup_dir: Path, keep: int) -> tuple[Path, ...]:
    """Delete the oldest dumps beyond `keep`; return the removed paths."""
    dumps = sorted(backup_dir.glob("marketing-*.dump"), key=lambda p: p.stat().st_mtime)
    removed: tuple[Path, ...] = ()
    if keep > 0:
        removed = tuple(dumps[:-keep])
        for old in removed:
            old.unlink()
    return removed


def _pg_parts() -> tuple[str, str, int, str, str]:
    """(user, password, port, host, dbname) from env/.env or DATABASE_URL."""
    url = get("DATABASE_URL", "").strip()
    if url:
        return _pg_parts_from_url(url)
    return (
        get("POSTGRES_USER", "marketing"),
        get("POSTGRES_PASSWORD", ""),
        int(get("POSTGRES_PORT", "5432") or 5432),
        get("POSTGRES_HOST", "127.0.0.1"),
        get("POSTGRES_DB", "marketing"),
    )


def _container_available() -> bool:
    """True when the db container is running (its pg tools always match
    the server version — host pg_dump 16 cannot dump a 17 server)."""
    if not DB_CONTAINER:
        return False
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    probe = subprocess.run(
        [docker_bin, "exec", DB_CONTAINER, "pg_dump", "--version"],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def _require_host_tool(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        print(
            f"ERROR: '{tool}' not found on PATH and no server container "
            f"('{DB_CONTAINER or 'unset'}') is reachable. Install "
            "postgresql-client or start the db container.",
            file=sys.stderr,
        )
        sys.exit(2)
    return path


def _tool_prefix(tool: str) -> tuple[list[str], bool]:
    """Command prefix for pg_dump/pg_restore. Container path talks to the
    local server via unix socket inside the container; host path uses
    -h/-p. Password is injected at run time via PGPASSWORD either way."""
    if _container_available():
        docker_bin = shutil.which("docker") or "docker"
        user, _pw, _port, _host, dbname = _pg_parts()
        return (
            [docker_bin, "exec", DB_CONTAINER, tool, "-U", user, "-d", dbname],
            True,
        )
    host_tool = _require_host_tool(tool)
    user, _pw, port, host, dbname = _pg_parts()
    return (
        [host_tool, "-h", host, "-p", str(port), "-U", user, "-d", dbname],
        False,
    )


def _run(
    prefix: list[str], extra: list[str], password: str
) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return subprocess.run([*prefix, *extra], env=env, capture_output=True, text=True)


def do_backup(keep: int) -> Path:
    user, password, _port, _host, dbname = _pg_parts()
    if not password:
        print("ERROR: no database password configured (.env).", file=sys.stderr)
        sys.exit(2)

    backup_dir = REPO_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = backup_dir / f"marketing-{dbname}-{stamp}.dump"

    prefix, in_container = _tool_prefix("pg_dump")
    tmp_container_path = f"/tmp/marketing-backup-{stamp}.dump"
    extra = [
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={tmp_container_path if in_container else out}",
    ]
    mode = "container" if in_container else "host"
    print(f"backup: {dbname} -> {out.name} ({mode} pg_dump)")
    result = _run(prefix, extra, password)
    if result.returncode != 0:
        print(f"pg_dump FAILED:\n{result.stderr}", file=sys.stderr)
        sys.exit(2)

    if in_container:
        cp = subprocess.run(
            ["docker", "cp", f"{DB_CONTAINER}:{tmp_container_path}", str(out)],
            capture_output=True,
            text=True,
        )
        subprocess.run(  # best-effort cleanup inside the container
            ["docker", "exec", DB_CONTAINER, "rm", "-f", tmp_container_path],
            capture_output=True,
        )
        if cp.returncode != 0:
            print(f"docker cp FAILED:\n{cp.stderr}", file=sys.stderr)
            sys.exit(2)

    if not out.is_file() or out.stat().st_size == 0:
        print("ERROR: backup file missing/empty after dump.", file=sys.stderr)
        sys.exit(2)
    print(f"ok: {out.stat().st_size / 1024 / 1024:.2f} MB")

    removed = _rotate(backup_dir, keep)
    for old in removed:
        print(f"rotated out: {old.name}")
    return out


def do_restore(path: Path, confirmed: bool) -> None:
    user, password, _port, _host, dbname = _pg_parts()
    if not password:
        print("ERROR: no database password configured (.env).", file=sys.stderr)
        sys.exit(3)
    if not path.is_file():
        print(f"ERROR: dump not found: {path}", file=sys.stderr)
        sys.exit(3)
    if not confirmed:
        print(
            "ERROR: restore REPLACES the current database contents.\n"
            "Re-run with --confirm-my-data to acknowledge.",
            file=sys.stderr,
        )
        sys.exit(3)

    prefix, in_container = _tool_prefix("pg_restore")
    if in_container:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_arg = f"/tmp/marketing-restore-{stamp}.dump"
        cp = subprocess.run(
            ["docker", "cp", str(path.resolve()), f"{DB_CONTAINER}:{file_arg}"],
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            print(f"docker cp FAILED:\n{cp.stderr}", file=sys.stderr)
            sys.exit(3)
    else:
        file_arg = str(path.resolve())

    extra = [
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        "--single-transaction",
        file_arg,
    ]
    print(f"restore: {path.name} -> {dbname} (single transaction)")
    result = _run(prefix, extra, password)
    if in_container:
        subprocess.run(  # best-effort cleanup
            ["docker", "exec", DB_CONTAINER, "rm", "-f", file_arg],
            capture_output=True,
        )
    if result.returncode != 0:
        print(f"pg_restore FAILED (rolled back):\n{result.stderr}", file=sys.stderr)
        sys.exit(3)
    print("ok: database restored")


def do_verify(path: Path) -> None:
    if not path.is_file():
        print(f"ERROR: dump not found: {path}", file=sys.stderr)
        sys.exit(3)
    prefix, in_container = _tool_prefix("pg_restore")
    if in_container:
        file_arg = "/tmp/marketing-verify.dump"
        subprocess.run(
            ["docker", "cp", str(path.resolve()), f"{DB_CONTAINER}:{file_arg}"],
            capture_output=True,
        )
        result = _run(prefix, ["--list", file_arg], "")
        subprocess.run(
            ["docker", "exec", DB_CONTAINER, "rm", "-f", file_arg],
            capture_output=True,
        )
    else:
        result = _run(prefix, ["--list", str(path.resolve())], "")
    if result.returncode != 0 or not result.stdout:
        print(f"pg_restore --list FAILED:\n{result.stderr}", file=sys.stderr)
        sys.exit(3)
    tables = _parse_toc_tables(result.stdout)
    print(f"archive ok: {len(tables)} tables")
    for t in tables:
        print(f"  - {t}")


def main() -> None:
    parser = argparse.ArgumentParser(description="backup/restore/verify MARKETING DB")
    parser.add_argument("action", choices=["backup", "restore", "verify"])
    parser.add_argument("file", nargs="?", help="dump file (restore/verify)")
    parser.add_argument("--keep", type=int, default=14, help="backups to keep")
    parser.add_argument(
        "--confirm-my-data",
        action="store_true",
        help="restore: acknowledge the database will be REPLACED",
    )
    args = parser.parse_args()

    if args.action == "backup":
        do_backup(args.keep)
    elif args.action == "verify":
        if not args.file:
            print("ERROR: verify needs a file", file=sys.stderr)
            sys.exit(1)
        do_verify(Path(args.file))
    else:
        if not args.file:
            print("ERROR: restore needs a file", file=sys.stderr)
            sys.exit(1)
        do_restore(Path(args.file), confirmed=args.confirm_my_data)


if __name__ == "__main__":
    main()
