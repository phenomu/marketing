"""Documentation reader for the NEON COMMAND dashboard.

Renders the operator user guide (dashboard/docs_guide.md — how to use
every feature) into dashboard tabs. Pure module — no Streamlit import,
hermetically testable (D-020).

UX-safety: the only source is docs_guide.md, a repo-committed guide
file. The dashboard renders it with st.markdown WITHOUT
unsafe_allow_html, so Streamlit strips any HTML — XSS-safe by default.
No .env, no credentials, no internal notes.
"""

from __future__ import annotations

from pathlib import Path

GUIDE_PATH = Path(__file__).resolve().parent / "docs_guide.md"

# guide H2 sections → dashboard doc tabs (order = display order)
DOC_GROUPS: list[tuple[str, list[str]]] = [
    ("Memulai", ["1. Memulai"]),
    ("Pipeline: Discovery & Crawl", ["2. Lead Discovery — Menambah Prospek", "3. Crawl & Ekstraksi Kontak"]),
    ("Lead & Data", ["4. Lead Management — Filter & Cari Lead"]),
    ("Outreach: Campaign & Email", ["5. Campaigns — Mengirim Email", "6. Email Preview — Uji Template Sebelum Kirim", "7. Analytics & Export"]),
    ("Mode Aman & Operasi", ["8. Mode Aman & Kepatuhan", "9. CLI & Operasi", "10. Troubleshooting"]),
]

GROUP_ICONS = {
    "Memulai": "◈",
    "Pipeline: Discovery & Crawl": "⌖",
    "Lead & Data": "☰",
    "Outreach: Campaign & Email": "✉",
    "Mode Aman & Operasi": "⚙",
}


def load_guide(path: Path | str | None = None) -> str:
    """Read the user guide; empty string when absent (never raises)."""
    p = Path(path) if path else GUIDE_PATH
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def split_sections(md: str) -> list[tuple[str, str]]:
    """Split markdown into (h2_title, body) pairs. H1 and preamble are
    dropped; sub-structure (###, tables, code) stays in the body."""
    if not md:
        return []
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    buf: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(buf).strip()))
            current_title = line[3:].strip()
            buf = []
        elif current_title is not None:
            buf.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(buf).strip()))
    return sections


def build_groups(md: str) -> list[tuple[str, str]]:
    """Return [(group_label, concatenated_markdown)] for the docs tabs.

    Sections not covered by DOC_GROUPS are skipped — the docs page shows
    curated guide content only.
    """
    secs = dict(split_sections(md))
    out: list[tuple[str, str]] = []
    for group, names in DOC_GROUPS:
        parts = [f"## {n}\n{secs[n]}" for n in names if n in secs]
        if parts:
            out.append((group, "\n\n---\n\n".join(parts)))
    return out
