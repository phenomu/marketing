"""HTML parsing for the crawler (PHASE 3): links, contact-page detection,
visible text, footer, and mailto harvesting (stored raw for PHASE 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

# words in href/text that mark a contact/about page (EN + ID)
CONTACT_WORDS = (
    "kontak", "contact", "hubungi", "whatsapp", "wa.me", "email",
    "tentang", "about", "lokasi", "location", "team", "tim",
)

_MAILTO_RE = re.compile(r"mailto:([^\"'>\s?]+)", re.IGNORECASE)


@dataclass
class PageLinks:
    links: list[str] = field(default_factory=list)          # absolute, normalized
    mailtos: list[str] = field(default_factory=list)         # bare addresses
    contact_links: list[str] = field(default_factory=list)   # subset: contact-ish


def _same_site(url: str, base_host: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    if host == base_host:
        return True
    return host.endswith("." + base_host)  # subdomains of the same site


def parse_links(html: str, base_url: str) -> PageLinks:
    """All same-site links from the page, classified into contact-ish and
    the rest. Absolute URLs; fragments/queryless dedup handled by caller."""
    base_host = (urlsplit(base_url).hostname or "").lower()
    out = PageLinks()
    if not base_host:
        return out
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.lower().startswith("mailto:"):
            for address in _MAILTO_RE.findall(href):
                if address not in out.mailtos:
                    out.mailtos.append(address)
            continue
        if not href or href.startswith(("#", "javascript:", "tel:", "data:")):
            continue
        url = urljoin(base_url, href)
        if not _same_site(url, base_host):
            continue
        # strip fragment + trailing slash for dedup
        parts = urlsplit(url)
        canonical = parts._replace(fragment="", query="", netloc=parts.netloc.lower()).geturl()
        path = parts.path.rstrip("/") or "/"
        canonical = parts._replace(fragment="", netloc=parts.netloc.lower(), path=path).geturl()
        if canonical in seen:
            continue
        seen.add(canonical)
        out.links.append(canonical)
        text = " ".join(anchor.get_text(" ").lower().split())
        if any(word in canonical.lower() for word in CONTACT_WORDS) or any(
            word in text for word in CONTACT_WORDS
        ):
            out.contact_links.append(canonical)
    return out


def page_text(html: str, max_chars: int = 20000) -> str:
    """Visible text of the page, whitespace-collapsed, capped."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return text[:max_chars]


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())[:500]
    return ""


def footer_text(html: str, max_chars: int = 4000) -> str:
    """Best-effort footer content: <footer> tag, else element whose class/id
    contains 'footer'. Contact blocks usually live there."""
    soup = BeautifulSoup(html, "lxml")
    node = soup.find("footer")
    if node is None:
        node = soup.find(class_=re.compile("footer", re.I))
    if node is None:
        node = soup.find(id=re.compile("footer", re.I))
    if node is None:
        return ""
    for tag in node(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(node.get_text(" ").split())
    return text[:max_chars]


def extract_mailtos(html: str) -> list[str]:
    """mailto: addresses in the raw HTML (PHASE 4 does full text mining)."""
    out: list[str] = []
    for address in _MAILTO_RE.findall(html):
        if address not in out:
            out.append(address)
    return out
