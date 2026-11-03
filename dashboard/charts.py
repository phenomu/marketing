"""ECharts renderers for the NEON COMMAND dashboard.

Each builder takes REAL rows from dashboard.queries and returns a
self-contained HTML document (echarts.min.js inlined from
dashboard/assets — no CDN dependency at runtime) suitable for
st.components.v1.html.

Chart rules per the directive: transparent background, muted axes,
cyan primary / purple secondary series, gradient area fills, smooth
curves, dark glass tooltips, subtle animation, responsive resize,
prefers-reduced-motion respected.

Pure module: no Streamlit import — hermetically testable.
"""

from __future__ import annotations

import json
from pathlib import Path

_ECHARTS_PATH = Path(__file__).resolve().parent / "assets" / "echarts.min.js"

PALETTE = {
    "cyan": "#00E5FF",
    "purple": "#8B5CF6",
    "lavender": "#C084FC",
    "mint": "#22F7A5",
    "warning": "#FBBF24",
    "error": "#FB7185",
    "neutral": "#94A3B8",
    "text2": "#94A3B8",
    "text3": "#64748B",
    "panel": "#10192A",
}

AXIS_LABEL = {"color": PALETTE["text3"], "fontSize": 11, "fontFamily": "JetBrains Mono"}
SPLIT_LINE = {"lineStyle": {"color": "rgba(148,163,184,0.10)"}}
TOOLTIP = {
    "backgroundColor": "rgba(11,17,32,0.94)",
    "borderColor": "rgba(0,229,255,0.25)",
    "borderWidth": 1,
    "textStyle": {"color": "#F1F5F9", "fontSize": 12, "fontFamily": "JetBrains Mono"},
    "extraCssText": "backdrop-filter: blur(6px); border-radius: 10px; box-shadow: 0 6px 24px rgba(0,0,0,0.4);",
}


def _echarts_js() -> str:
    if not _ECHARTS_PATH.exists():  # defensive: image build copies assets/
        raise FileNotFoundError(
            f"echarts bundle missing: {_ECHARTS_PATH} (dashboard/assets must ship in the image)"
        )
    return _ECHARTS_PATH.read_text(encoding="utf-8")


def _html_doc(option: dict, height: int = 300, borderless: bool = False) -> str:
    """Render one ECharts option into a full responsive HTML doc."""
    option_json = json.dumps(option, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: transparent;
    font-family: 'JetBrains Mono', monospace; }}
  #chart {{ width: 100%; height: {height}px; }}
  @media (prefers-reduced-motion: reduce) {{
    #chart * {{ transition: none !important; animation: none !important; }}
  }}
</style>
</head>
<body>
<div id="chart"></div>
<script>
{_echarts_js()}
</script>
<script>
(function () {{
  var reduce = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var chart = echarts.init(document.getElementById('chart'), null, {{
    renderer: 'canvas'
  }});
  var option = {option_json};
  if (reduce) {{
    option.animation = false;
  }} else {{
    option.animationDuration = 850;
    option.animationEasing = 'cubicOut';
  }}
  chart.setOption(option);
  window.addEventListener('resize', function () {{ chart.resize(); }});
}})();
</script>
</body>
</html>"""


# --- chart builders (data → echarts option) -----------------------------------


def area_option(days: list[str], series: list[dict]) -> dict:
    """Smooth gradient area chart. series: [{name, values, color}]."""
    colors = [s.get("color", PALETTE["cyan"]) for s in series]
    return {
        "backgroundColor": "transparent",
        "color": colors,
        "tooltip": {**TOOLTIP, "trigger": "axis"},
        "legend": {
            "show": len(series) > 1,
            "top": 0,
            "textStyle": {"color": PALETTE["text2"], "fontSize": 11},
            "itemWidth": 14,
            "itemHeight": 8,
        },
        "grid": {"left": 8, "right": 16, "top": 28, "bottom": 6, "containLabel": True},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": days,
            "axisLabel": {**AXIS_LABEL, "hideOverlap": True},
            "axisLine": {"lineStyle": {"color": "rgba(148,163,184,0.18)"}},
            "axisTick": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "minInterval": 1,
            "axisLabel": AXIS_LABEL,
            "splitLine": SPLIT_LINE,
        },
        "series": [
            {
                "name": s["name"],
                "type": "line",
                "smooth": 0.35,
                "symbol": "circle",
                "symbolSize": 6,
                "showSymbol": False,
                "lineStyle": {"width": 2.2, "color": s.get("color", PALETTE["cyan"])},
                "itemStyle": {"color": s.get("color", PALETTE["cyan"])},
                "areaStyle": {
                    "opacity": 1,
                    "color": {
                        "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                        "colorStops": [
                            {"offset": 0, "color": s.get("fill", "rgba(0,229,255,0.28)")},
                            {"offset": 1, "color": "rgba(7,11,20,0)"},
                        ],
                    },
                },
                "data": s["values"],
            }
            for s in series
        ],
    }


def donut_option(rows: list[tuple[str, int]], center_label: str = "") -> dict:
    """Donut for distribution (e.g. contacts by kind)."""
    palette = [PALETTE["cyan"], PALETTE["purple"], PALETTE["lavender"],
               PALETTE["mint"], PALETTE["warning"], PALETTE["neutral"],
               PALETTE["error"]]
    data = [{"name": n, "value": v} for n, v in rows]
    return {
        "backgroundColor": "transparent",
        "tooltip": {**TOOLTIP, "trigger": "item", "confine": True},
        "legend": {
            "bottom": 0,
            "textStyle": {"color": PALETTE["text2"], "fontSize": 11},
            "itemWidth": 10, "itemHeight": 10, "icon": "roundRect",
        },
        "title": {
            "text": center_label,
            "left": "center", "top": "42%",
            "textStyle": {
                "color": PALETTE["text3"], "fontSize": 11,
                "fontFamily": "JetBrains Mono",
            },
        },
        "series": [
            {
                "type": "pie",
                "radius": ["48%", "70%"],
                "center": ["50%", "46%"],
                "avoidLabelOverlap": True,
                "itemStyle": {
                    "borderRadius": 6,
                    "borderColor": "#0B1120",
                    "borderWidth": 2,
                },
                "label": {
                    "show": True,
                    "color": PALETTE["text2"],
                    "fontSize": 11,
                    "fontFamily": "JetBrains Mono",
                },
                "data": data,
            }
        ],
        "color": palette[: max(len(data), 1)],
    }


def bar_option(categories: list[str], values: list[int], color: str | None = None, horizontal: bool = False) -> dict:
    """Bar chart (vertical default, horizontal for category breakdown)."""
    base_color = color or PALETTE["cyan"]
    ax = "xAxis" if horizontal else "yAxis"
    option: dict = {
        "backgroundColor": "transparent",
        "tooltip": {**TOOLTIP, "trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 8, "right": 18, "top": 14, "bottom": 6, "containLabel": True},
        "xAxis": {
            "type": "category" if horizontal else "value",
            "data": categories if horizontal else None,
            "axisLabel": AXIS_LABEL,
            "axisLine": {"lineStyle": {"color": "rgba(148,163,184,0.18)"}},
            "axisTick": {"show": False},
            "splitLine": SPLIT_LINE if not horizontal else {"show": False},
            "minInterval": 1 if not horizontal else None,
        },
        "yAxis": {
            "type": "value" if horizontal else "category",
            "data": categories if not horizontal else None,
            "axisLabel": AXIS_LABEL,
            "splitLine": SPLIT_LINE if horizontal else {"show": False},
            "axisLine": {"lineStyle": {"color": "rgba(148,163,184,0.18)"}},
            "minInterval": 1 if horizontal else None,
        },
        "series": [
            {
                "type": "bar",
                "data": values,
                "barMaxWidth": 34,
                "itemStyle": {
                    "borderRadius": [5, 5, 0, 0] if not horizontal else [0, 5, 5, 0],
                    "color": {
                        "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                        "colorStops": [
                            {"offset": 0, "color": base_color},
                            {"offset": 1, "color": "rgba(11,17,32,0.25)"},
                        ],
                    },
                },
            }
        ],
    }
    if horizontal:
        option["yAxis"]["inverse"] = True
    return option


def gauge_option(value: float, name: str, max_value: float = 100) -> dict:
    """System-health gauge (e.g. crawl success ratio)."""
    pct = 0 if max_value == 0 else round(value / max_value * 100, 1)
    color = PALETTE["cyan"] if pct >= 60 else (PALETTE["warning"] if pct >= 30 else PALETTE["error"])
    return {
        "backgroundColor": "transparent",
        "tooltip": TOOLTIP,
        "series": [
            {
                "type": "gauge",
                "startAngle": 210,
                "endAngle": -30,
                "min": 0,
                "max": max_value,
                "progress": {
                    "show": True,
                    "width": 10,
                    "itemStyle": {"color": color},
                },
                "axisLine": {"lineStyle": {"width": 10, "color": [[1, "rgba(148,163,184,0.14)"]]}},
                "axisTick": {"show": False},
                "splitLine": {"show": False},
                "axisLabel": {"show": False},
                "pointer": {"show": False},
                "anchor": {"show": False},
                "title": {
                    "show": True,
                    "offsetCenter": [0, "62%"],
                    "color": PALETTE["text3"],
                    "fontSize": 11,
                    "fontFamily": "JetBrains Mono",
                },
                "detail": {
                    "valueAnimation": True,
                    "offsetCenter": [0, "18%"],
                    "color": color,
                    "fontSize": 22,
                    "fontFamily": "Space Grotesk",
                    "formatter": "{value}%",
                },
                "data": [{"value": pct, "name": name}],
            }
        ],
    }


def sparkline_svg(values: list[int], color: str | None = None, width: int = 120, height: int = 26) -> str:
    """Tiny inline SVG sparkline for KPI cards (no JS needed)."""
    if not values:
        return ""
    color = color or PALETTE["cyan"]
    vmax, vmin = max(values), min(values)
    span = (vmax - vmin) or 1
    step = width / max(len(values) - 1, 1)
    pts = [
        (round(i * step, 1), round(height - 3 - (v - vmin) / span * (height - 6), 1))
        for i, v in enumerate(values)
    ]
    path = " ".join(f"{x},{y}" for x, y in pts)
    area = f"M0,{height} L{path.replace(' ', ' L')} L{width},{height} Z"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:block;margin-top:2px">'
        f'<path d="{area}" fill="{color}18" stroke="none"/>'
        f'<polyline points="{path}" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{pts[-1][0]}" cy="{pts[-1][1]}" r="2.2" fill="{color}"/>'
        f"</svg>"
    )


# --- full components (html doc) ------------------------------------------------


def activity_chart_component(daily_rows: list[dict], height: int = 300) -> str:
    """events_daily rows → smooth area chart (cyan primary, purple others)."""
    by_day: dict[str, dict[str, int]] = {}
    types: list[str] = []
    for r in daily_rows:
        day = str(r.get("day"))
        etype = str(r.get("event_type"))
        if etype not in types:
            types.append(etype)
        by_day.setdefault(day, {})[etype] = int(r.get("n", 0))
    days = sorted(by_day)
    series = []
    for i, etype in enumerate(sorted(types)):
        color = PALETTE["cyan"] if etype in ("sent", "sent-dry") else PALETTE["purple"]
        fill = "rgba(0,229,255,0.28)" if i == 0 else "rgba(139,92,246,0.24)"
        series.append({
            "name": etype,
            "values": [by_day[d].get(etype, 0) for d in days],
            "color": color,
            "fill": fill,
        })
    return _html_doc(area_option(days, series), height=height)


def donut_chart_component(rows: list[tuple[str, int]], center_label: str = "", height: int = 280) -> str:
    return _html_doc(donut_option(rows, center_label), height=height)


def bar_chart_component(categories: list[str], values: list[int], height: int = 260, horizontal: bool = False) -> str:
    return _html_doc(bar_option(categories, values, horizontal=horizontal), height=height)


def gauge_chart_component(value: float, name: str, max_value: float = 100, height: int = 170) -> str:
    return _html_doc(gauge_option(value, name, max_value), height=height)


# --- kpi grid component (count-up + sparklines) ---------------------------------


def kpi_grid_component(cards_html: list[str], columns: int = 4) -> str:
    """Responsive KPI grid with count-up animation. cards_html: kpi_card
    outputs. Self-contained: components render in their own iframe, so
    the card styling must be embedded here (not inherited from theme)."""
    cards = "".join(cards_html)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
<style>
  html, body {{ margin: 0; padding: 0; background: transparent;
    font-family: 'Inter', system-ui, sans-serif; }}
  .grid {{
    display: grid; gap: 12px; padding: 0;
    grid-template-columns: repeat({columns}, minmax(0, 1fr));
  }}
  @media (max-width: 1100px) and (min-width: 721px) {{
    .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  }}
  @media (max-width: 720px) {{
    .grid {{ grid-template-columns: 1fr; }}
  }}
  .nc-card {{
    background: linear-gradient(180deg, rgba(23,34,56,0.65), #10192A);
    border: 1px solid rgba(148,163,184,0.14);
    border-radius: 16px;
    padding: 16px 18px;
    transition: border-color 180ms ease, box-shadow 180ms ease;
    animation: nc-fade-up 320ms ease-out both;
  }}
  .nc-card:hover {{
    border-color: rgba(0,229,255,0.38);
    box-shadow: 0 0 0 1px rgba(0,229,255,0.10), 0 8px 26px rgba(0,0,0,0.35);
  }}
  .nc-kpi {{ display: flex; flex-direction: column; gap: 6px; height: 100%; }}
  .nc-kpi .ico {{
    width: 34px; height: 34px; display: flex; align-items: center; justify-content: center;
    border-radius: 8px; font-size: 16px;
    background: rgba(0,229,255,0.08); border: 1px solid rgba(0,229,255,0.25);
    color: #00E5FF;
  }}
  .nc-kpi .ico.purple {{
    background: rgba(139,92,246,0.10); border-color: rgba(139,92,246,0.35);
    color: #C084FC;
  }}
  .nc-kpi .ico.mint {{
    background: rgba(34,247,165,0.08); border-color: rgba(34,247,165,0.30);
    color: #22F7A5;
  }}
  .nc-kpi .label {{
    font-size: 12px; font-weight: 500; letter-spacing: 0.09em;
    text-transform: uppercase; color: #64748B;
  }}
  .nc-kpi .value {{
    font-family: 'Space Grotesk', 'Inter', sans-serif; font-size: 32px;
    font-weight: 700; color: #F1F5F9; line-height: 1.05;
    font-variant-numeric: tabular-nums;
  }}
  .nc-kpi .value.cyan {{ color: #00E5FF; }}
  .nc-kpi .value.purple {{ color: #C084FC; }}
  .nc-kpi .value.mint {{ color: #22F7A5; }}
  .nc-kpi .sub {{
    font-size: 11.5px; color: #64748B;
    font-family: 'JetBrains Mono', monospace;
  }}
  @keyframes nc-fade-up {{
    from {{ opacity: 0; transform: translateY(10px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .nc-card {{ animation: none; }}
  }}
</style>
</head>
<body>
<div class="grid">{cards}</div>
<script>
(function () {{
  var reduce = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var els = document.querySelectorAll('.value[data-nc-count]');
  els.forEach(function (el) {{
    var target = parseFloat(el.getAttribute('data-nc-count'));
    if (isNaN(target)) {{ return; }}
    if (reduce) {{ el.textContent = String(target); return; }}
    var start = null, dur = 750;
    function step(ts) {{
      if (!start) {{ start = ts; }}
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(target * eased));
      if (p < 1) {{ requestAnimationFrame(step); }}
    }}
    el.textContent = '0';
    requestAnimationFrame(step);
  }});
}})();
</script>
</body>
</html>"""


def kpi_card_countup(label: str, value: int, icon: str, tone: str = "cyan", sub: str = "", spark: list[int] | None = None, spark_color: str | None = None) -> str:
    """Like theme.kpi_card but with count-up + sparkline (for the grid)."""
    spark_html = sparkline_svg(spark, spark_color) if spark else ""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    tone_class = f" {tone}" if tone in ("cyan", "purple", "mint") else ""
    return (
        f'<div class="nc-card nc-kpi">'
        f'<div class="ico{(" " + tone) if tone in ("purple", "mint") else ""}">{icon}</div>'
        f'<div class="label">{label}</div>'
        f'<div class="value{tone_class}" data-nc-count="{int(value)}">{int(value)}</div>'
        f"{sub_html}{spark_html}"
        f"</div>"
    )
