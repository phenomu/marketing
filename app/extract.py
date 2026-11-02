"""Contact extraction (PHASE 4): emails, phone numbers, social media
profiles and street addresses mined from stored crawl-page text (plus
per-page mailto: links the crawler saved).

Pure functions + a never-raise runner. Persistence lives in app/store.py;
the worker calls run_pending_extractions() after each crawl batch.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import Engine

from app.db import get_engine
from app.store import (
    claim_pending_extractions,
    load_crawl_pages,
    mark_extraction_done,
    primary_business_id,
    save_contacts,
    update_business_address_if_empty,
)
from config import settings

log = logging.getLogger(__name__)

# --- emails ---------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,7}")
# "info (at) domain (dot) com" — brackets or plain words
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b([A-Za-z0-9._%+\-]{2,})\b\s*[(\[<{]?\s*(?:at)\s*[)\]>}]?\s*"
    r"\b([A-Za-z0-9\-]+(?:\s*\.\s*[A-Za-z0-9\-]+)*)\b\s*"
    r"[(\[<{]?\s*(?:dot)\s*[)\]>}]?\s*\b([A-Za-z]{2,7})\b",
    re.IGNORECASE,
)
_ASSET_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|svg|ico|css|js|mjs|json|mp[34]|webm|pdf|woff2?|ttf|eot|otf|avif|heic|html|php|aspx|jsp)$",
    re.IGNORECASE,
)
_JUNK_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com", "domain.co.id",
    "test.com", "email.com", "yourdomain.com", "yourdomain.co.id", "email.com.id",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "schema.org", "w3.org",
    "sentry.wixpress.com", "no-reply.com", "noreply.com", "user.com", "mail.com",
    "sitename.com", "website.com", "abc.com", "test.test",
}

# --- phones (Indonesian formats) ------------------------------------------

_PHONE_CAND_RE = re.compile(r"(?<![\d])(?:\+?62|0)[0-9\-().\s]{7,16}[0-9]")
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}\b")
_PRICE_RE = re.compile(r"(?:rp|harga)\.?\s*[\d.,]+", re.IGNORECASE)

# --- social profiles --------------------------------------------------------

_SOCIAL_HOSTS = (
    "instagram.com", "facebook.com", "tiktok.com", "linkedin.com",
    "youtube.com", "twitter.com", "x.com", "t.me",
)
_SOCIAL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(instagram\.com|facebook\.com|tiktok\.com|linkedin\.com"
    r"|youtube\.com|twitter\.com|x\.com|t\.me|wa\.me)(/[A-Za-z0-9_.\-/?=&]+)?",
    re.IGNORECASE,
)
_CONTENT_PATH_PREFIXES = {
    "p", "reel", "tv", "explore", "embed", "sharer", "share", "dialog",
    "watch", "playlist", "shorts", "hashtag", "tags", "events", "home",
    "search", "i", "intent", "login", "signup", "groups", "marketplace",
    "stories", "channels", "feed", "about", "help", "legal",
}
_LINKEDIN_PREFIXES = {"company", "in", "school", "org", "pub"}

# --- address ----------------------------------------------------------------

_ADDRESS_RE = re.compile(r"\b(?:Jl\.?|Jln\.?|Jalan)\s*[^,;]{2,80}", re.IGNORECASE)

_PAGE_CONF = {"contact": 80, "about": 70, "home": 60, "other": 40}
_SOURCE_CONF = {"mailto": 20, "link": 15, "text": 0}


@dataclass
class Contact:
    kind: str  # email|phone|social|address
    value: str  # raw, as found
    norm: str  # normalized dedup key
    source_url: str = ""
    source_kind: str = "text"  # mailto|link|text
    confidence: int = 0


def normalize_email(addr: str) -> str:
    return addr.strip().strip(".").lstrip("<").rstrip(">").lower().removeprefix("mailto:")


def _email_valid(addr: str) -> bool:
    if not addr or len(addr) > 254 or len(addr.split("@")[0]) > 64:
        return False
    domain = addr.rsplit("@", 1)[1]
    if domain in _JUNK_DOMAINS or _ASSET_RE.search(addr):
        return False
    if not re.fullmatch(r"[a-z0-9.\-]+\.[a-z]{2,7}", domain):
        return False
    local = addr.split("@")[0]
    if local.count(".") > 3 or re.fullmatch(r"[.\-_]+", local):
        return False
    return True


def extract_emails(text: str, mailtos: list[str] | None = None) -> list[str]:
    """Emails from mailto links first (authoritative), then plain/obfuscated text."""
    out: list[str] = []
    for addr in mailtos or []:
        norm = normalize_email(addr)
        if _email_valid(norm) and norm not in out:
            out.append(norm)
    for m in EMAIL_RE.findall(text or ""):
        norm = normalize_email(m)
        if _email_valid(norm) and norm not in out:
            out.append(norm)
    for local, domained, tld in OBFUSCATED_EMAIL_RE.findall(text or ""):
        domained = domained.replace(" ", "")
        norm = normalize_email(f"{local}@{domained}.{tld}")
        if _email_valid(norm) and norm not in out:
            out.append(norm)
    return out


# --- phones ---------------------------------------------------------------


_RUN_RE = re.compile(r"(\d)\1{5,}")  # 6+ identical digits in a row


def normalize_phone(candidate: str) -> str | None:
    """+62xxxxxxxxxx from Indonesian phone text; None when not a phone."""
    digits = re.sub(r"\D", "", candidate)
    if not digits:
        return None
    if digits.startswith("62"):
        rest = digits[2:]
    elif digits.startswith("0"):
        rest = digits[1:]
    elif len(digits) >= 9 and digits.startswith("8"):
        rest = digits  # bare mobile number without prefix
    else:
        return None
    if not 8 <= len(rest) <= 12 or rest[0] not in "289":
        return None
    if _RUN_RE.search(rest):  # 000000000 / 8111111111 etc.
        return None
    return "+62" + rest


def extract_phones(text: str, extra: list[str] | None = None) -> list[str]:
    """Normalized Indonesian phone numbers from text (and optional raw values)."""
    cleaned = _PRICE_RE.sub(" ", _DATE_RE.sub(" ", text or ""))
    out: list[str] = []
    for cand in _PHONE_CAND_RE.findall(cleaned) + list(extra or []):
        norm = normalize_phone(cand)
        if norm and norm not in out:
            out.append(norm)
    return out


# --- social -----------------------------------------------------------------


def _social_from_match(host: str, path: str | None) -> tuple[str, str] | None:
    """(value, norm) for a social profile link, or None when content path."""
    host = host.lower()
    path = (path or "").strip("/")
    path = path.split("?", 1)[0].split("#", 1)[0].rstrip(".")
    if host == "wa.me":
        return None  # handled as phone, not social
    if not path:
        return None
    segs = [s for s in path.split("/") if s]
    if not segs:
        return None
    first = segs[0].lower()

    if host == "linkedin.com" and first in _LINKEDIN_PREFIXES and len(segs) >= 2:
        handle = f"{segs[0]}/{segs[1]}"
    elif host == "youtube.com" and first in ("channel", "c", "user") and len(segs) >= 2:
        handle = f"{segs[0]}/{segs[1]}"  # youtube.com/channel/ID is the profile URL
    elif first in _CONTENT_PATH_PREFIXES or first.startswith("profile.php"):
        return None  # content page, not a profile
    else:
        handle = segs[0]
    value = f"https://{host}/{handle}"
    return value, f"{host}/{handle}".lower()


def extract_socials(text: str) -> list[str]:
    """Normalized social profile URLs (instagram.com/handle form)."""
    out: list[str] = []
    for host, path in _SOCIAL_RE.findall(text or ""):
        got = _social_from_match(host, path)
        if got and got[1] not in out:
            out.append(got[1])
    return out


def wa_phones(text: str) -> list[str]:
    """Phone numbers behind wa.me / api.whatsapp.com links."""
    out: list[str] = []
    for host, path in _SOCIAL_RE.findall(text or ""):
        if host.lower() != "wa.me":
            continue
        digits = re.sub(r"\D", "", (path or "").split("?", 1)[0].strip("/"))
        norm = normalize_phone(digits)
        if norm and norm not in out:
            out.append(norm)
    return out


# --- address ----------------------------------------------------------------


def extract_addresses(text: str) -> list[str]:
    """Indonesian street addresses (Jl./Jalan/Jln. …) from text."""
    out: list[str] = []
    for m in _ADDRESS_RE.findall(text or ""):
        addr = " ".join(m.split()).rstrip(",; ")
        if len(addr) > 7 and addr not in out:
            out.append(addr)
    return out


# --- per-page orchestration ---------------------------------------------------


def extract_from_page(page: dict) -> list[Contact]:
    """All contacts from one stored crawl page (dict from load_crawl_pages)."""
    text = page.get("text") or ""
    kind = page.get("kind") or "other"
    url = page.get("url") or ""
    base = _PAGE_CONF.get(kind, 40)
    out: dict[tuple[str, str], Contact] = {}

    def _add(ct_kind: str, raw: str, norm: str, source_kind: str, conf: int) -> None:
        key = (ct_kind, norm)
        existing = out.get(key)
        if existing is not None:
            existing.confidence = max(existing.confidence, conf)
            if not existing.source_url:
                existing.source_url = url
            return
        out[key] = Contact(
            kind=ct_kind, value=raw, norm=norm,
            source_url=url, source_kind=source_kind, confidence=conf,
        )

    for addr in extract_emails(text, page.get("mailtos") or []):
        _add("email", addr, addr, "mailto" if addr in (page.get("mailtos") or []) else "text",
             base + _SOURCE_CONF["mailto" if addr in (page.get("mailtos") or []) else "text"])
    for phone in extract_phones(text):
        _add("phone", phone, phone, "text", base)
    for phone in wa_phones(text):
        _add("phone", phone, phone, "link", base + _SOURCE_CONF["link"])
    for norm in extract_socials(text):
        _add("social", norm, norm, "link", base + _SOURCE_CONF["link"])
    for addr in extract_addresses(text):
        _add("address", addr, " ".join(addr.lower().split()), "text", base)

    return sorted(out.values(), key=lambda c: -c.confidence)


def extract_contacts(pages: list[dict]) -> list[Contact]:
    """Contacts across pages of one domain; dedup keeps best confidence."""
    merged: dict[tuple[str, str], Contact] = {}
    for page in pages:
        for contact in extract_from_page(page):
            key = (contact.kind, contact.norm)
            current = merged.get(key)
            if current is not None:
                if contact.confidence > current.confidence:
                    current.source_url = contact.source_url or current.source_url
                    current.source_kind = contact.source_kind
                current.confidence = max(current.confidence, contact.confidence)
            else:
                merged[key] = contact
    return sorted(merged.values(), key=lambda c: -c.confidence)


def run_pending_extractions(engine: Engine | None = None, limit: int | None = None) -> dict:
    """Extraction runner (worker side). Processes crawl jobs that finished
    crawling but were never extracted. Never raises — failures are logged
    and the job is marked extracted (retrying deterministic text won't help)."""
    engine = engine or get_engine()
    limit = limit if limit is not None else settings.extract_batch_limit
    jobs = claim_pending_extractions(engine, limit)
    stats = {"jobs": len(jobs), "new": 0, "updated": 0, "addresses_filled": 0}
    for job in jobs:
        try:
            pages = load_crawl_pages(engine, job["id"])
            business_id = primary_business_id(engine, job["domain"])
            if business_id is None:
                log.info(
                    "extraction job %s: no business row for domain %s — skipped",
                    job["id"], job["domain"],
                )
            else:
                contacts = extract_contacts(pages)
                if contacts:
                    counts = save_contacts(engine, business_id, job["id"], contacts)
                    stats["new"] += counts["new"]
                    stats["updated"] += counts["updated"]
                    for contact in contacts:
                        if contact.kind == "address":
                            stats["addresses_filled"] += update_business_address_if_empty(
                                engine, business_id, contact.value
                            )
                            break
                log.info(
                    "extraction job %s (%s): %s contact(s)",
                    job["id"], job["domain"], len(contacts),
                )
        except Exception as exc:  # noqa: BLE001 — runner must survive
            log.exception("extraction job %s failed: %s", job["id"], exc)
        mark_extraction_done(engine, job["id"])
    return stats
