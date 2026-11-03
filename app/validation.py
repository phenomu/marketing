"""Email validation — syntax, domain, MX (PHASE 5).

Three layers, cheapest first:
1. syntax  — regex + junk/asset rules (same filters as the extractor).
2. domain  — DNS A resolution, through the SSRF guard.
3. mx      — DNS MX lookup + SMTP connect (NO-SEND: EHLO/QUIT only).

The SMTP layer never sends mail: connect, say hello, quit. Its purpose is
to prove a mail server exists at the domain, not to verify a mailbox.
Port-25 blocking (common on residential ISPs and in docker networks) is
NOT treated as invalid — the result becomes `unknown` instead, so an
unreachable network can never mark real mailboxes as dead.

Statuses: `valid` | `invalid` | `unknown` | `unchecked`.
Never raises; a `status_detail` note explains every non-`valid` verdict.

MX/SMTP targets are external data (harvested emails) — every connection
goes through the SSRF guard (D-031): the MX host must resolve to public
IPs only before we connect.
"""

from __future__ import annotations

import logging
import re
import smtplib
import socket
import time
from dataclasses import dataclass
from typing import Callable

from app.extract import _ASSET_RE, _JUNK_DOMAINS
from app.urls import is_public_host

log = logging.getLogger(__name__)

# py3dns needs its resolver list bootstrapped once (reads /etc/resolv.conf)
try:
    import DNS

    _HAS_PY3DNS = True
    _DNS_READY = False  # becomes True after DiscoverNameServers() runs
except Exception:  # noqa: BLE001 — missing lib or no resolv.conf
    DNS = None
    _HAS_PY3DNS = False
    _DNS_READY = False

# local part + domain, subdomain-tolerant, TLD 2-7
SYNTAX_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,7}$")

HELO_NAME = "marketing-validator.local"
SMTP_TIMEOUT_S = 10
SMTP_PORT = 25

VALID = "valid"
INVALID = "invalid"
UNKNOWN = "unknown"
DEFAULT_LAYERS = ("syntax", "domain", "mx")


@dataclass
class EmailStatus:
    email: str
    status: str = "unchecked"
    detail: str = ""
    checked_at: str = ""  # ISO-8601 UTC

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at,
        }


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(addr: str) -> str:
    return (addr or "").strip().lower()


# --- layer 1: syntax --------------------------------------------------------


def syntax_check(addr: str) -> EmailStatus:
    """Shape of the address — pure CPU, no I/O."""
    email = _clean(addr)
    ts = _timestamp()
    if not email:
        return EmailStatus(email, INVALID, "empty address", ts)
    if len(email) > 254:
        return EmailStatus(email, INVALID, "too long", ts)
    if email.count("@") != 1:
        return EmailStatus(email, INVALID, "not exactly one @", ts)
    local, domain = email.split("@")
    if not local or len(local) > 64:
        return EmailStatus(email, INVALID, "bad local part length", ts)
    if not SYNTAX_RE.fullmatch(email):
        return EmailStatus(email, INVALID, "syntax", ts)
    if domain in _JUNK_DOMAINS or _ASSET_RE.search(email):
        return EmailStatus(email, INVALID, "junk/asset address", ts)
    if local.count(".") > 3 or re.fullmatch(r"[.\-_]+", local):
        return EmailStatus(email, INVALID, "degenerate local part", ts)
    return EmailStatus(email, VALID, "syntax ok", ts)


# --- layer 2: domain --------------------------------------------------------


def domain_check(
    addr: str, _resolver: Callable = socket.getaddrinfo
) -> EmailStatus:
    """Domain resolves to public IPs (SSRF guard). `_resolver` is the
    same hook is_public_host uses — tests drive it without DNS."""
    email = _clean(addr)
    if email.count("@") != 1:
        return EmailStatus(email, INVALID, "not exactly one @", _timestamp())
    domain = email.rsplit("@", 1)[1]
    if not is_public_host(domain, _resolver=_resolver):
        return EmailStatus(email, INVALID, "domain does not resolve", _timestamp())
    return EmailStatus(email, VALID, "domain resolves", _timestamp())


# --- layer 3: MX ------------------------------------------------------------


def _mx_lookup_real(domain: str) -> list[tuple[int, str]]:
    """MX records via py3dns — [(preference, host)] sorted by preference,
    never raises. Returns [] when py3dns is unavailable or lookup fails."""
    if not _HAS_PY3DNS:
        return []
    global _DNS_READY
    if not _DNS_READY:
        try:
            DNS.DiscoverNameServers()  # bootstrap from /etc/resolv.conf
            _DNS_READY = True
        except Exception as exc:  # noqa: BLE001
            log.debug("discover name servers failed: %s", exc)
            return []
    records: list[tuple[int, str]] = []
    try:
        req = DNS.DnsRequest(domain, qtype=DNS.Type.MX, timeout=5)
        for ans in req.req().answers:
            data = ans.get("data") if isinstance(ans, dict) else getattr(ans, "data", None)
            pref, host = None, None
            if isinstance(data, tuple) and len(data) == 2:
                pref, host = data
            else:
                parts = str(data).split()
                if len(parts) == 2:
                    pref, host = parts
            if host and host not in ("", "."):
                records.append((int(pref) if str(pref).isdigit() else 0, str(host).rstrip(".")))
    except Exception as exc:  # noqa: BLE001 — DNS/network errors vary
        log.debug("mx lookup %s failed: %s", domain, exc)
        return []
    records.sort()
    return records


def mx_check(
    addr: str,
    helo_name: str = HELO_NAME,
    smtp_timeout_s: int = SMTP_TIMEOUT_S,
    _smtp: Callable = smtplib.SMTP,
    _mx_lookup: Callable = _mx_lookup_real,
    _resolver: Callable = socket.getaddrinfo,
) -> EmailStatus:
    """MX record exists and a server accepts a connection (NO-SEND).

    The connect target must pass the SSRF guard. Connectable MX -> valid;
    MX exists but refuses/times out -> unknown (network conditions are
    not proof the mailbox is dead); no MX -> invalid."""
    email = _clean(addr)
    if email.count("@") != 1:
        return EmailStatus(email, INVALID, "not exactly one @", _timestamp())
    domain = email.rsplit("@", 1)[1]
    ts = _timestamp()

    try:
        mx_hosts = _mx_lookup(domain)
    except Exception as exc:  # noqa: BLE001 — defensive, never raise
        return EmailStatus(email, UNKNOWN, f"mx lookup failed: {type(exc).__name__}", ts)
    if not mx_hosts:
        return EmailStatus(email, INVALID, "no MX record", ts)
    mx_hosts = sorted(mx_hosts, key=lambda r: r[0])  # lowest preference first

    reasons: list[str] = []
    for _pref, host in mx_hosts:
        if not is_public_host(host, _resolver=_resolver):
            continue  # private/unresolvable MX — skip, try next record
        try:
            with _smtp(host, SMTP_PORT, timeout=smtp_timeout_s) as client:
                client.helo(helo_name)
                client.quit()
            return EmailStatus(email, VALID, f"mx {host} accepted connection", ts)
        except (smtplib.SMTPException, OSError) as exc:
            reasons.append(f"{host}: {type(exc).__name__}")
            continue
    if reasons:
        return EmailStatus(
            email, UNKNOWN, f"mx refused/unreachable: {'; '.join(reasons)[:120]}", ts
        )
    return EmailStatus(email, UNKNOWN, "all mx hosts non-public", ts)


# --- entry points -----------------------------------------------------------


def validate_email(
    addr: str,
    layers: tuple[str, ...] = DEFAULT_LAYERS,
    _resolver: Callable = socket.getaddrinfo,
    _mx_lookup: Callable = _mx_lookup_real,
    _smtp: Callable = smtplib.SMTP,
) -> EmailStatus:
    """Run layers cheapest-first; first non-`valid` verdict wins."""
    email = _clean(addr)
    status = EmailStatus(email, "unchecked", "no layers requested", _timestamp())
    for layer in layers:
        if layer == "syntax":
            status = syntax_check(email)
        elif layer == "domain":
            status = domain_check(email, _resolver=_resolver)
        elif layer == "mx":
            status = mx_check(
                email, _mx_lookup=_mx_lookup, _smtp=_smtp, _resolver=_resolver
            )
        else:
            continue
        if status.status != VALID:
            return status
    return status


def run_validation(
    emails: list[str], layers: tuple[str, ...] = DEFAULT_LAYERS, **kwargs
) -> list[EmailStatus]:
    """Batch helper — one EmailStatus per input."""
    return [validate_email(email, layers, **kwargs) for email in emails]


def run_validation_batch(engine=None, limit: int = 5) -> dict:
    """Worker entry: validate up to `limit` pending email contacts and
    persist results. MX connect only — NO-SEND. Never raises.

    Returns {emails, valid, invalid, unknown}."""
    from app.db import get_engine
    from app.store import pending_email_contacts, set_contact_validation

    engine = engine or get_engine()
    stats = {"emails": 0, "valid": 0, "invalid": 0, "unknown": 0}
    try:
        pending = pending_email_contacts(engine, limit=limit)
    except Exception as exc:  # noqa: BLE001
        log.warning("validation claim failed: %s", exc)
        return stats
    for row in pending:
        try:
            status = validate_email(row["value_norm"])
        except Exception as exc:  # noqa: BLE001 — one bad row must not kill the batch
            log.warning(
                "validate %s crashed (%s); marking unknown", row["value_norm"], exc
            )
            stats["emails"] += 1
            stats["unknown"] += 1
            try:
                set_contact_validation(
                    engine, row["id"], "unknown", f"validator error: {type(exc).__name__}"
                )
            except Exception:  # noqa: BLE001
                log.warning("persist validation fallback failed: %s", row["value_norm"])
            continue
        stats["emails"] += 1
        stats[status.status] = stats.get(status.status, 0) + 1
        try:
            set_contact_validation(
                engine, row["id"], status.status, status.detail
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("persist validation %s failed: %s", row["value_norm"], exc)
    if stats["emails"]:
        log.info(
            "validated %s email(s): %s valid / %s invalid / %s unknown",
            stats["emails"], stats["valid"], stats["invalid"], stats["unknown"],
        )
    return stats
