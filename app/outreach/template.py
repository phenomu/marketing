"""Email templates + personalization (PHASE 6).

Personalization fields come from the lead + business rows only — no
data the system does not already hold. Template placeholders use
`{{name}}` syntax, rendered with a tiny safe formatter (str.format_map
with a missing-key fallback — no Jinja, no code execution).

The default templates are conservative: honest subject, clear sender
identity, functional plain-text part, unsubscribe link in both parts
(email marketing rule: identitas pengirim jelas, subjek jujur,
unsubscribe tersedia — AGENTS.md).
"""

from __future__ import annotations

import html
import logging

import re

log = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

DEFAULT_SUBJECT = "Kerja sama untuk {{name}}?"

DEFAULT_BODY_TEXT = """Halo tim {{name}},

Kami menemukan {{name}} saat memetakan bisnis {{category}} di {{location}}.
Website {{domain}} kami sudah lihat — menarik.

Apakah terbuka untuk diskusi singkat soal kerja sama pemasaran?

Salam,
{{sender_name}}
{{sender_email}}

—
Jika tidak ingin menerima email lagi dari kami, klik link berikut:
{{unsubscribe_url}}
"""

DEFAULT_BODY_HTML = """<p>Halo tim {{name}},</p>
<p>Kami menemukan {{name}} saat memetakan bisnis {{category}} di {{location}}.
Website {{domain}} kami sudah lihat — menarik.</p>
<p>Apakah terbuka untuk diskusi singkat soal kerja sama pemasaran?</p>
<p>Salam,<br>
{{sender_name}}<br>
{{sender_email}}</p>
<hr>
<p style="font-size:12px;color:#888">Jika tidak ingin menerima email lagi dari
kami, <a href="{{unsubscribe_url}}">klik di sini untuk berhenti berlangganan</a>.</p>
"""


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def build_context(
    lead: dict, sender_name: str, sender_email: str, unsubscribe_url: str
) -> dict:
    """Merge business fields + sender identity + unsubscribe link."""
    return _SafeDict(
        name=lead.get("name", ""),
        category=lead.get("category", ""),
        location=lead.get("location", "") or lead.get("city", ""),
        domain=lead.get("domain", ""),
        sender_name=sender_name,
        sender_email=sender_email,
        unsubscribe_url=unsubscribe_url,
    )


def render(template: str, context: dict) -> str:
    """Replace {{placeholder}} tokens. Unknown keys -> empty string.
    Single braces (HTML/CSS) are left untouched — only the double-brace
    form is a placeholder. Never raises."""
    def _sub(match: re.Match) -> str:
        return str(context.get(match.group(1), ""))
    return _PLACEHOLDER_RE.sub(_sub, template)


def render_message(
    lead: dict,
    subject: str,
    body_text: str,
    body_html: str,
    sender_name: str,
    sender_email: str,
    unsubscribe_url: str,
) -> tuple[str, str, str]:
    """Render subject + both bodies for one lead. Returns
    (subject, body_text, body_html). Missing business data collapses to
    neutral phrasing, never an error."""
    ctx = build_context(lead, sender_name, sender_email, unsubscribe_url)
    # location: businesses table has no city column — collapse to category
    # phrasing when empty
    if not ctx["location"]:
        ctx["location"] = ctx["category"] or "Indonesia"
    subject_r = render(subject, ctx)
    text_r = render(body_text, ctx)
    html_r = render(body_html, ctx) if body_html else ""
    return subject_r, text_r, html_r


def escape_html_fields(body_html: str, lead: dict) -> str:
    """Escape business-provided fields interpolated into HTML. Business
    names come from scraped listings — never trust them as markup
    (XSS-in-email / phishing-injection defense). Call AFTER render, on
    values only — render() output here keeps placeholders safe."""
    for field in ("name", "category", "domain"):
        value = lead.get(field, "")
        if value and value in body_html:
            body_html = body_html.replace(value, html.escape(value, quote=False))
    return body_html
