"""NEON COMMAND design system for the MARKETING dashboard.

Pure module: tokens, CSS builder, and small HTML component builders.
No Streamlit import here — unit-testable hermetically (see
tests/test_theme.py). main.py injects the CSS via st.markdown.

Design tokens follow the NEON COMMAND directive: deep navy surfaces,
neon cyan primary, electric purple secondary, mint accent, restrained
glass and glow. All values that reach the UI come from real queries —
this module only styles them.
"""

from __future__ import annotations

import html as _html
from typing import Any

# --- tokens ------------------------------------------------------------------

COLORS: dict[str, str] = {
    # surfaces
    "bg_base": "#070B14",
    "bg_app": "#0B1120",
    "bg_panel": "#10192A",
    "bg_elevated": "#172238",
    # primary / secondary
    "cyan": "#00E5FF",
    "purple": "#8B5CF6",
    "lavender": "#C084FC",
    "mint": "#22F7A5",
    # status
    "success": "#35D399",
    "warning": "#FBBF24",
    "error": "#FB7185",
    "neutral": "#94A3B8",
    # text
    "text_primary": "#F1F5F9",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
}

STATUS_COLORS: dict[str, str] = {
    "done": "success",
    "valid": "success",
    "running": "success",
    "contacted": "success",
    "sent": "success",
    "sent-dry": "cyan",
    "pending": "warning",
    "new": "cyan",
    "unchecked": "warning",
    "unknown": "warning",
    "draft": "warning",
    "paused": "warning",
    "failed": "error",
    "invalid": "error",
    "bounced": "error",
    "suppressed": "neutral",
    "suppression": "neutral",
}

RADII = {"sm": "8px", "md": "12px", "md-lg": "14px", "lg": "16px"}
FONT_STACKS = {
    "heading": "'Space Grotesk', 'Inter', system-ui, sans-serif",
    "body": "'Inter', system-ui, -apple-system, sans-serif",
    "mono": "'JetBrains Mono', 'SFMono-Regular', Menlo, monospace",
}

REQUIRED_TOKEN_KEYS = (
    "bg_base", "bg_app", "bg_panel", "bg_elevated",
    "cyan", "purple", "lavender", "mint",
    "success", "warning", "error", "neutral",
    "text_primary", "text_secondary", "text_muted",
)


def _c(name: str) -> str:
    return COLORS[name]


# --- css ----------------------------------------------------------------------


def theme_css() -> str:
    """Full stylesheet injected once per app run via st.markdown."""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
  --nc-bg-base: {_c('bg_base')};
  --nc-bg-app: {_c('bg_app')};
  --nc-bg-panel: {_c('bg_panel')};
  --nc-bg-elevated: {_c('bg_elevated')};
  --nc-cyan: {_c('cyan')};
  --nc-purple: {_c('purple')};
  --nc-lavender: {_c('lavender')};
  --nc-mint: {_c('mint')};
  --nc-success: {_c('success')};
  --nc-warning: {_c('warning')};
  --nc-error: {_c('error')};
  --nc-neutral: {_c('neutral')};
  --nc-text: {_c('text_primary')};
  --nc-text-2: {_c('text_secondary')};
  --nc-text-3: {_c('text_muted')};
  --nc-font-head: {FONT_STACKS['heading']};
  --nc-font-body: {FONT_STACKS['body']};
  --nc-font-mono: {FONT_STACKS['mono']};
}}

/* ---- global app shell --------------------------------------------------- */

.stApp, [data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1100px 500px at 85% -10%, rgba(139,92,246,0.07), transparent 60%),
    radial-gradient(900px 420px at -10% 110%, rgba(0,229,255,0.05), transparent 55%),
    var(--nc-bg-app);
  color: var(--nc-text);
  font-family: var(--nc-font-body);
  font-size: 14px;
}}

.block-container {{
  padding: 1.4rem 2rem 3rem 2rem !important;
  max-width: 1440px;
}}

#MainMenu, footer,
[data-testid="stDecoration"], [data-testid="stStatusWidget"] {{
  display: none !important;
}}
/* streamlit's own top strip: keep (holds the sidebar collapse control) but
   make it invisible on the dark shell */
header[data-testid="stHeader"] {{
  background: transparent !important;
  color: var(--nc-text-3) !important;
}}

h1 {{
  font-family: var(--nc-font-head);
  font-size: 28px !important;
  font-weight: 700;
  color: var(--nc-text) !important;
  letter-spacing: -0.01em;
  padding-bottom: 4px;
  border-bottom: 1px solid rgba(148,163,184,0.14);
  margin-bottom: 6px !important;
}}

h2, h3, .stSubheader {{
  font-family: var(--nc-font-head);
  color: var(--nc-text) !important;
}}

p, span, label, li {{ color: var(--nc-text-2); }}
strong {{ color: var(--nc-text); }}

/* ---- topbar --------------------------------------------------------------- */

.nc-topbar {{
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; margin-bottom: 18px;
  background: linear-gradient(180deg, rgba(23,34,56,0.72), rgba(16,25,42,0.55));
  border: 1px solid rgba(148,163,184,0.14);
  border-radius: {RADII['lg']};
  padding: 10px 18px;
  backdrop-filter: blur(10px);
  animation: nc-fade-in 280ms ease-out both;
}}
.nc-crumb {{
  display: flex; align-items: center; gap: 10px;
  font-family: var(--nc-font-mono); font-size: 12.5px;
  color: var(--nc-text-3); letter-spacing: 0.04em;
}}
.nc-crumb .sep {{ color: var(--nc-text-3); opacity: 0.5; }}
.nc-crumb .here {{ color: var(--nc-cyan); font-family: var(--nc-font-head); font-weight: 600; letter-spacing: 0.06em; }}
.nc-topbar-right {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}

/* ---- sidebar --------------------------------------------------------------- */

section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, var(--nc-bg-panel), var(--nc-bg-base));
  border-right: 1px solid rgba(0,229,255,0.10) !important;
  width: 258px !important;
  min-width: 258px !important;
  max-width: 258px !important;
  transition: width 200ms ease;
}}
section[data-testid="stSidebar"] > div:first-child,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
  width: 258px !important;
}}
section[data-testid="stSidebar"] .block-container {{ padding: 1rem 0.9rem; }}
section[data-testid="stSidebar"] hr {{ border-color: rgba(148,163,184,0.12); }}

.nc-logo {{
  display: flex; align-items: center; gap: 10px; padding: 6px 4px 2px 4px;
  font-family: var(--nc-font-head); font-size: 17px; font-weight: 700;
  color: var(--nc-text); letter-spacing: 0.08em;
}}
.nc-logo .mark {{
  width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid rgba(0,229,255,0.45); border-radius: 8px;
  color: var(--nc-cyan); font-size: 13px;
  box-shadow: 0 0 14px rgba(0,229,255,0.22), inset 0 0 10px rgba(0,229,255,0.10);
}}
.nc-logo small {{
  display: block; font-family: var(--nc-font-mono); font-size: 9.5px;
  font-weight: 400; color: var(--nc-text-3); letter-spacing: 0.18em;
}}

/* radio nav → command list (Streamlit 1.6x react-aria DOM) */
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {{
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 9px 10px;
  margin: 1px 0;
  border-radius: {RADII['md']};
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease, box-shadow 150ms ease;
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover {{
  background: rgba(0,229,255,0.06);
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] {{
  background: linear-gradient(90deg, rgba(0,229,255,0.14), rgba(0,229,255,0.04));
  border-color: rgba(0,229,255,0.22);
  box-shadow: inset 3px 0 0 0 var(--nc-cyan);
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] span {{
  color: var(--nc-text); font-weight: 600;
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] span {{ font-size: 13.5px; }}
/* the native circle indicator — keep the layout row, drop the dot */
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div:first-of-type > div:first-child {{
  display: none !important;
}}
/* full-width clickable row: every wrapper up the chain must fill */
section[data-testid="stSidebar"] [data-testid="stElementContainer"],
section[data-testid="stSidebar"] [data-testid="stRadio"],
section[data-testid="stSidebar"] [data-testid="stRadioGroup"],
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] > div {{
  width: 100% !important;
  max-width: 100% !important;
}}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div:first-of-type {{
  width: 100%;
}}

/* sidebar collapse arrow */
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="stSidebarCollapseButton"] button {{
  color: var(--nc-text-2) !important;
  background: rgba(16,25,42,0.8) !important;
  border: 1px solid rgba(148,163,184,0.18) !important;
  border-radius: 8px !important;
}}

/* sidebar status block */
.nc-side-status {{
  margin-top: 10px; padding: 10px 12px;
  background: rgba(16,25,42,0.85);
  border: 1px solid rgba(148,163,184,0.13);
  border-radius: {RADII['md']};
  font-family: var(--nc-font-mono); font-size: 10.5px; line-height: 1.7;
  color: var(--nc-text-3);
}}
.nc-side-status .k {{ color: var(--nc-text-3); }}
.nc-side-status .v {{ color: var(--nc-text-2); }}

/* ---- cards / panels -------------------------------------------------------- */

.nc-card {{
  background: linear-gradient(180deg, rgba(23,34,56,0.65), var(--nc-bg-panel));
  border: 1px solid rgba(148,163,184,0.14);
  border-radius: {RADII['lg']};
  padding: 16px 18px;
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
  animation: nc-fade-up 320ms ease-out both;
}}
.nc-card:hover {{
  border-color: rgba(0,229,255,0.38);
  box-shadow: 0 0 0 1px rgba(0,229,255,0.10), 0 8px 26px rgba(0,0,0,0.35);
}}

.nc-kpi {{
  display: flex; flex-direction: column; gap: 6px; height: 100%;
}}
.nc-kpi .ico {{
  width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;
  border-radius: {RADII['sm']}; font-size: 16px;
  background: rgba(0,229,255,0.08); border: 1px solid rgba(0,229,255,0.25);
  color: var(--nc-cyan);
}}
.nc-kpi .ico.purple {{
  background: rgba(139,92,246,0.10); border-color: rgba(139,92,246,0.35);
  color: var(--nc-lavender);
}}
.nc-kpi .ico.mint {{
  background: rgba(34,247,165,0.08); border-color: rgba(34,247,165,0.30);
  color: var(--nc-mint);
}}
.nc-kpi .label {{
  font-size: 12px; font-weight: 500; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--nc-text-3);
}}
.nc-kpi .value {{
  font-family: var(--nc-font-head); font-size: 32px; font-weight: 700;
  color: var(--nc-text); line-height: 1.05;
  font-variant-numeric: tabular-nums;
}}
.nc-kpi .value.cyan {{ color: var(--nc-cyan); }}
.nc-kpi .value.purple {{ color: var(--nc-lavender); }}
.nc-kpi .value.mint {{ color: var(--nc-mint); }}
.nc-kpi .sub {{ font-size: 11.5px; color: var(--nc-text-3); font-family: var(--nc-font-mono); }}

/* KPI grid rendered directly in the parent DOM (anchor cards) */
.nc-kpi-grid {{
  display: grid; gap: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0 0 8px 0;
}}
@media (max-width: 1100px) and (min-width: 721px) {{
  .nc-kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
}}
@media (max-width: 720px) {{
  .nc-kpi-grid {{ grid-template-columns: 1fr; }}
}}
.nc-kpi-grid a.nc-card {{
  text-decoration: none; color: inherit; display: block;
  position: relative;
}}
.nc-kpi-grid a.nc-card::after {{
  content: "→"; position: absolute; right: 14px; top: 14px;
  color: var(--nc-cyan); opacity: 0; font-size: 14px;
  transition: opacity 180ms ease, transform 180ms ease;
}}
.nc-kpi-grid a.nc-card:hover::after {{ opacity: 0.9; transform: translateX(2px); }}
.nc-kpi-grid a.nc-card:hover {{
  border-color: rgba(0,229,255,0.55);
  box-shadow: 0 0 0 1px rgba(0,229,255,0.16), 0 8px 26px rgba(0,0,0,0.40);
}}

/* ---- badges ------------------------------------------------------------------ */

.nc-badge {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 2.5px 10px; border-radius: 999px;
  font-family: var(--nc-font-mono); font-size: 11px; font-weight: 500;
  letter-spacing: 0.03em; line-height: 1.5;
  border: 1px solid rgba(148,163,184,0.20);
  color: var(--nc-text-2); background: rgba(23,34,56,0.60);
}}
.nc-badge .dot {{ width: 6px; height: 6px; border-radius: 999px; background: currentColor; }}

.nc-cyan {{ color: var(--nc-cyan); border-color: rgba(0,229,255,0.35); background: rgba(0,229,255,0.08); }}
.nc-purple {{ color: var(--nc-lavender); border-color: rgba(192,132,252,0.35); background: rgba(139,92,246,0.10); }}
.nc-success {{ color: var(--nc-success); border-color: rgba(53,211,153,0.35); background: rgba(53,211,153,0.09); }}
.nc-warning {{ color: var(--nc-warning); border-color: rgba(251,191,36,0.35); background: rgba(251,191,36,0.08); }}
.nc-error {{ color: var(--nc-error); border-color: rgba(251,113,133,0.35); background: rgba(251,113,133,0.09); }}
.nc-neutral {{ color: var(--nc-neutral); }}

/* ---- native widgets dark skin ------------------------------------------------- */

.stButton > button, .stDownloadButton > button, div[data-testid="stFormSubmitButton"] > button {{
  background: var(--nc-bg-elevated) !important;
  color: var(--nc-text) !important;
  border: 1px solid rgba(148,163,184,0.22) !important;
  border-radius: {RADII['md']} !important;
  font-weight: 500 !important; font-size: 13.5px !important;
  font-family: var(--nc-font-body) !important;
  transition: border-color 170ms ease, box-shadow 170ms ease, background 170ms ease, transform 120ms ease;
}}
.stButton > button:hover {{
  border-color: rgba(0,229,255,0.55) !important;
  box-shadow: 0 0 16px rgba(0,229,255,0.16) !important;
  color: var(--nc-cyan) !important;
}}
.stButton > button:active {{ transform: scale(0.985); }}
.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button[kind="primary"] {{
  background: linear-gradient(135deg, rgba(0,229,255,0.18), rgba(139,92,246,0.14)) !important;
  border-color: rgba(0,229,255,0.50) !important;
  color: var(--nc-cyan) !important;
}}

div[data-baseweb="popover"], div[data-baseweb="select"] > div,
div[data-testid="stSelectbox"], div[data-testid="stMultiSelect"] {{
  color: var(--nc-text-2);
}}
div[data-baseweb="select"] > div > div {{
  background-color: var(--nc-bg-panel) !important;
  border-color: rgba(148,163,184,0.22) !important;
  color: var(--nc-text) !important;
  border-radius: {RADII['sm']} !important;
}}
input, textarea {{
  background-color: var(--nc-bg-panel) !important;
  color: var(--nc-text) !important;
  border-color: rgba(148,163,184,0.22) !important;
  font-family: var(--nc-font-body) !important;
}}
input:focus, textarea:focus, div[data-baseweb="select"]:focus-within {{
  border-color: rgba(0,229,255,0.55) !important;
  box-shadow: 0 0 0 3px rgba(0,229,255,0.10) !important;
}}
::placeholder {{ color: var(--nc-text-3) !important; }}

[data-testid="stSlider"] [role="slider"] {{
  background-color: var(--nc-cyan) !important;
  border-color: var(--nc-cyan) !important;
}}

/* tabs */
.stTabs [data-baseweb="tab-list"] {{
  gap: 2px; border-bottom: 1px solid rgba(148,163,184,0.16);
}}
.stTabs [data-baseweb="tab"] {{
  background: transparent; color: var(--nc-text-3);
  font-family: var(--nc-font-head); font-size: 13px; letter-spacing: 0.03em;
  padding: 8px 14px; border-radius: 9px 9px 0 0;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: var(--nc-text-2); }}
.stTabs [aria-selected="true"] {{
  color: var(--nc-cyan) !important;
  background: linear-gradient(180deg, rgba(0,229,255,0.10), transparent) !important;
  box-shadow: inset 0 -2px 0 0 var(--nc-cyan);
}}

/* forms */
div[data-testid="stForm"] {{
  background: rgba(16,25,42,0.55);
  border: 1px solid rgba(148,163,184,0.13);
  border-radius: {RADII['lg']};
  padding: 18px !important;
}}

/* dataframes — glide grid chrome */
[data-testid="stDataFrame"] {{
  border: 1px solid rgba(148,163,184,0.14);
  border-radius: {RADII['md']};
  overflow: hidden;
  background: var(--nc-bg-panel);
}}
[data-testid="stDataFrame"]:hover {{ border-color: rgba(0,229,255,0.30); }}

/* metric blocks (any remaining st.metric) */
div[data-testid="stMetric"] {{
  background: linear-gradient(180deg, rgba(23,34,56,0.65), var(--nc-bg-panel));
  border: 1px solid rgba(148,163,184,0.14);
  border-radius: {RADII['md-lg']};
  padding: 12px 16px;
}}
div[data-testid="stMetricValue"] {{ font-family: var(--nc-font-head); font-size: 26px; color: var(--nc-cyan); }}

/* expander */
[data-testid="stExpander"] {{
  background: rgba(16,25,42,0.55);
  border: 1px solid rgba(148,163,184,0.13) !important;
  border-radius: {RADII['md']} !important;
}}

/* code blocks → mono panels */
pre, code, [data-testid="stCodeBlock"] {{
  font-family: var(--nc-font-mono) !important;
  background: var(--nc-bg-base) !important;
  border: 1px solid rgba(148,163,184,0.12);
  color: var(--nc-mint) !important;
}}

/* toasts / alerts */
[data-testid="stToast"], [data-testid="stAlert"] {{
  background: var(--nc-bg-elevated) !important;
  border: 1px solid rgba(0,229,255,0.25);
  color: var(--nc-text) !important;
  border-radius: {RADII['md']} !important;
}}

/* json viewer */
[data-testid="stJson"] {{
  background: var(--nc-bg-base);
  border: 1px solid rgba(148,163,184,0.12);
  border-radius: {RADII['md']};
  font-family: var(--nc-font-mono); font-size: 12px;
}}

/* ---- chart panel ------------------------------------------------------------- */

.nc-chart-panel {{
  background: linear-gradient(180deg, rgba(23,34,56,0.55), var(--nc-bg-panel));
  border: 1px solid rgba(148,163,184,0.14);
  border-radius: {RADII['lg']};
  padding: 8px 10px 4px 10px;
  animation: nc-fade-up 360ms ease-out both;
}}
.nc-chart-panel:hover {{ border-color: rgba(0,229,255,0.30); }}
.nc-chart-title {{
  font-family: var(--nc-font-head); font-size: 14px; font-weight: 600;
  color: var(--nc-text); padding: 8px 8px 4px 8px; letter-spacing: 0.02em;
}}
.nc-chart-title small {{
  font-family: var(--nc-font-mono); font-size: 10.5px; font-weight: 400;
  color: var(--nc-text-3); margin-left: 8px; letter-spacing: 0.06em;
}}

/* ---- page header block --------------------------------------------------------- */

.nc-pagehead {{ margin: 4px 0 20px 0; animation: nc-fade-in 240ms ease-out both; }}
.nc-pagehead .title {{
  font-family: var(--nc-font-head); font-size: 26px; font-weight: 700;
  color: var(--nc-text); letter-spacing: -0.01em; line-height: 1.2;
}}
.nc-pagehead .title::after {{
  content: ""; display: block; width: 56px; height: 3px; margin-top: 8px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--nc-cyan), rgba(139,92,246,0.9));
  box-shadow: 0 0 12px rgba(0,229,255,0.35);
}}
.nc-pagehead .sub {{
  font-size: 13px; color: var(--nc-text-3); margin-top: 8px; max-width: 860px;
}}

/* ---- email preview frame --------------------------------------------------------- */

.nc-mail-frame {{
  background: var(--nc-bg-base);
  border: 1px solid rgba(139,92,246,0.30);
  border-radius: {RADII['md-lg']};
  padding: 10px;
}}

/* ---- docs page -------------------------------------------------------------------- */

.nc-docs-note {{
  margin: 0 0 16px 0; padding: 10px 14px;
  background: rgba(16,25,42,0.70);
  border: 1px solid rgba(0,229,255,0.20);
  border-left: 3px solid var(--nc-cyan);
  border-radius: {RADII['md']};
  font-family: var(--nc-font-mono); font-size: 11.5px;
  color: var(--nc-text-2); letter-spacing: 0.02em;
}}
.nc-docs-note::before {{
  content: "▤ ";
  color: var(--nc-cyan);
}}

/* markdown prose (README render) */
[data-testid="stMarkdownContainer"] h2 {{
  font-family: var(--nc-font-head); font-size: 21px; font-weight: 700;
  color: var(--nc-text); margin-top: 26px; margin-bottom: 10px;
  padding-bottom: 6px; border-bottom: 1px solid rgba(148,163,184,0.14);
}}
[data-testid="stMarkdownContainer"] h2:first-child {{ margin-top: 6px; }}
[data-testid="stMarkdownContainer"] h3 {{
  font-family: var(--nc-font-head); font-size: 16px; font-weight: 600;
  color: var(--nc-text-2); margin-top: 20px;
}}
[data-testid="stMarkdownContainer"] a {{
  color: var(--nc-cyan); text-decoration: none;
  border-bottom: 1px dashed rgba(0,229,255,0.35);
}}
[data-testid="stMarkdownContainer"] a:hover {{
  color: var(--nc-mint); border-bottom-color: var(--nc-mint);
}}
[data-testid="stMarkdownContainer"] table {{
  border-collapse: collapse; width: 100%; margin: 12px 0;
  font-size: 13px;
}}
[data-testid="stMarkdownContainer"] th {{
  background: rgba(23,34,56,0.85); color: var(--nc-text);
  font-family: var(--nc-font-head); font-size: 12.5px; font-weight: 600;
  text-align: left; padding: 8px 12px;
  border: 1px solid rgba(148,163,184,0.16);
}}
[data-testid="stMarkdownContainer"] td {{
  padding: 7px 12px; color: var(--nc-text-2);
  border: 1px solid rgba(148,163,184,0.12);
  background: rgba(16,25,42,0.45);
}}
[data-testid="stMarkdownContainer"] tr:hover td {{
  background: rgba(0,229,255,0.05);
}}
[data-testid="stMarkdownContainer"] code {{
  background: rgba(7,11,20,0.90); color: var(--nc-mint);
  font-family: var(--nc-font-mono); font-size: 12px;
  padding: 1.5px 6px; border-radius: 5px;
  border: 1px solid rgba(148,163,184,0.10);
}}
[data-testid="stMarkdownContainer"] hr {{
  border: none; height: 1px; margin: 22px 0;
  background: linear-gradient(90deg, rgba(0,229,255,0.25), rgba(139,92,246,0.20), transparent);
}}
[data-testid="stMarkdownContainer"] blockquote {{
  border-left: 3px solid rgba(0,229,255,0.40);
  background: rgba(0,229,255,0.04); color: var(--nc-text-2);
  margin: 12px 0; padding: 8px 14px; border-radius: 0 {RADII['sm']} {RADII['sm']} 0;
}}

/* ---- animations --------------------------------------------------------------- */

@keyframes nc-fade-in {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
@keyframes nc-fade-up {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }}
}}

/* ---- responsive --------------------------------------------------------------- */

@media (max-width: 1100px) {{
  .block-container {{ padding: 1.1rem 1.2rem 2.4rem 1.2rem !important; }}
  .nc-kpi .value {{ font-size: 27px; }}
}}
@media (max-width: 720px) {{
  .nc-topbar {{ flex-direction: column; align-items: flex-start; }}
  .nc-kpi .value {{ font-size: 23px; }}
  h1 {{ font-size: 23px !important; }}
}}
</style>
"""


# --- html component builders (pure) ---------------------------------------------


def esc(value: Any) -> str:
    return _html.escape(str(value), quote=True)


def badge(text: str, tone: str = "neutral", dot: bool = True) -> str:
    """Status chip. tone: cyan|purple|success|warning|error|neutral."""
    dot_html = '<span class="dot"></span>' if dot else ""
    return (
        f'<span class="nc-badge nc-{esc(tone)}">{dot_html}{esc(text)}</span>'
    )


def status_badge(status: str) -> str:
    """Map a domain status string to a colored badge automatically."""
    tone = STATUS_COLORS.get(str(status).lower(), "neutral")
    return badge(str(status), tone)


def kpi_card(
    label: str,
    value: Any,
    icon: str = "◈",
    tone: str = "cyan",
    sub: str = "",
) -> str:
    """KPI card HTML. tone: cyan|purple|mint (icon + number tint)."""
    value_class = f" {esc(tone)}" if tone in ("cyan", "purple", "mint") else ""
    sub_html = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="nc-card nc-kpi">'
        f'<div class="ico{(" " + esc(tone)) if tone in ("purple", "mint") else ""}">{esc(icon)}</div>'
        f'<div class="label">{esc(label)}</div>'
        f'<div class="value{value_class}">{esc(value)}</div>'
        f"{sub_html}"
        f"</div>"
    )


def kpi_card_link(
    label: str,
    value: Any,
    view: str,
    icon: str = "◈",
    tone: str = "cyan",
    sub: str = "",
) -> str:
    """Clickable KPI card: whole card is an anchor to ?view=<view>.
    Rendered in the PARENT document (st.markdown), so a plain link
    works — component iframes are sandboxed and cannot navigate."""
    value_class = f" {esc(tone)}" if tone in ("cyan", "purple", "mint") else ""
    sub_html = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<a class="nc-card nc-kpi" href="?view={esc(view)}">'
        f'<div class="ico{(" " + esc(tone)) if tone in ("purple", "mint") else ""}">{esc(icon)}</div>'
        f'<div class="label">{esc(label)}</div>'
        f'<div class="value{value_class}">{esc(value)}</div>'
        f"{sub_html}"
        f"</a>"
    )


def kpi_grid_links(cards_html: list[str]) -> str:
    """Responsive grid of clickable KPI cards (parent-DOM version)."""
    return f'<div class="nc-kpi-grid">{"".join(cards_html)}</div>'


def topbar(page: str, badges_html: list[str]) -> str:
    """Top command bar: breadcrumb + real status badges. Badges supplied
    by the caller from live settings — nothing fabricated here."""
    crumbs = (
        '<div class="nc-crumb">'
        '<span>MARKETING</span><span class="sep">/</span>'
        f'<span class="here">{esc(page.upper())}</span>'
        "</div>"
    )
    right = (
        '<div class="nc-topbar-right">'
        + "".join(badges_html)
        + "</div>"
    )
    return f'<div class="nc-topbar">{crumbs}{right}</div>'


def page_header(title: str, subtitle: str = "") -> str:
    """Full page header: styled title + subtitle (replaces st.title)."""
    sub = f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ""
    return (
        f'<div class="nc-pagehead">'
        f'<div class="title">{esc(title)}</div>'
        f"{sub}"
        f"</div>"
    )


def chart_panel(title: str, hint: str = "", body: str = "") -> str:
    """Panel wrapper for chart components rendered separately."""
    hint_html = f"<small>{esc(hint)}</small>" if hint else ""
    head = f'<div class="nc-chart-title">{esc(title)}{hint_html}</div>'
    return f'<div class="nc-chart-panel">{head}{body}</div>'


def side_status(rows: list[tuple[str, str]]) -> str:
    """Sidebar footer: key/value system status lines (real values)."""
    lines = "".join(
        f'<div><span class="k">{esc(k)}</span> <span class="v">{esc(v)}</span></div>'
        for k, v in rows
    )
    return f'<div class="nc-side-status">{lines}</div>'


def docs_note(text: str) -> str:
    """Docs page source banner (rendered above the tabs)."""
    return f'<div class="nc-docs-note">{esc(text)}</div>'
