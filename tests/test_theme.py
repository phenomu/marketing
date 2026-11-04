"""NEON COMMAND design-system tests (hermetic, no Streamlit runtime).

theme.py and charts.py are pure modules: tokens, CSS, HTML builders and
ECharts option dicts. The only rule under test: the design system must
never crash on empty/odd data (dashboard renders with zero rows too)
and every color/font value must exist in the token set.
"""

from __future__ import annotations

import json

import pytest

from dashboard import charts, docs, theme


class TestTokens:
    def test_all_required_colors_defined(self):
        for key in theme.REQUIRED_TOKEN_KEYS:
            assert theme.COLORS.get(key), f"missing token: {key}"
            assert theme.COLORS[key].startswith("#")

    def test_status_colors_map_to_known_tones(self):
        valid = {"cyan", "purple", "success", "warning", "error", "neutral"}
        for status, tone in theme.STATUS_COLORS.items():
            assert tone in valid, f"{status} -> unknown tone {tone}"

    def test_font_stacks_present(self):
        for stack in theme.FONT_STACKS.values():
            assert "sans-serif" in stack or "monospace" in stack


class TestThemeCss:
    def test_css_contains_core_selectors(self):
        css = theme.theme_css()
        for needle in (
            ":root",
            ".stApp",
            "data-testid=\"stSidebar\"",
            ".nc-card",
            ".nc-badge",
            ".nc-kpi",
            "prefers-reduced-motion",
            "@media (max-width: 720px)",
            theme.COLORS["cyan"],
            theme.COLORS["bg_app"],
        ):
            assert needle in css, f"css missing: {needle}"

    def test_css_responsive_breakpoints(self):
        css = theme.theme_css()
        assert "1100px" in css and "720px" in css


class TestHtmlBuilders:
    def test_badge_escapes(self):
        out = theme.badge("<script>", "cyan")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_badge_tones(self):
        for tone in ("cyan", "purple", "success", "warning", "error", "neutral"):
            assert f"nc-{tone}" in theme.badge("x", tone)

    def test_status_badge_known_and_unknown(self):
        assert "nc-success" in theme.status_badge("running")
        assert "nc-warning" in theme.status_badge("unknown")
        assert "nc-neutral" in theme.status_badge("totally-new-status")

    def test_kpi_card_escapes_and_structure(self):
        out = theme.kpi_card("Leads", 17, "◉", "cyan", sub="new 8")
        assert "Leads" in out and "17" in out and "nc-card" in out
        bad = theme.kpi_card("<b>", 1)
        assert "<b>" not in bad

    def test_topbar_and_side_status(self):
        out = theme.topbar("Overview", [theme.badge("dev", "cyan")])
        assert "OVERVIEW" in out and "nc-topbar" in out
        side = theme.side_status([("env", "dev")])
        assert "env" in side and "nc-side-status" in side


class TestChartOptions:
    def test_area_option_shape(self):
        opt = charts.area_option(
            ["Mon", "Tue"],
            [{"name": "sent-dry", "values": [1, 2]}],
        )
        assert opt["series"][0]["type"] == "line"
        assert opt["series"][0]["smooth"] is not False
        assert opt["tooltip"]["trigger"] == "axis"
        assert opt["backgroundColor"] == "transparent"

    def test_area_empty_series(self):
        opt = charts.area_option([], [])
        assert opt["series"] == []

    def test_donut_option(self):
        opt = charts.donut_option([("email", 10), ("phone", 44)])
        data = opt["series"][0]["data"]
        assert [d["value"] for d in data] == [10, 44]

    def test_donut_empty(self):
        opt = charts.donut_option([])
        assert opt["series"][0]["data"] == []

    def test_bar_option_and_horizontal(self):
        opt = charts.bar_option(["done", "failed"], [21, 8])
        assert opt["series"][0]["type"] == "bar"
        hopt = charts.bar_option(["a", "b"], [1, 2], horizontal=True)
        assert hopt["yAxis"]["inverse"] is True

    def test_gauge_option_bounds(self):
        opt = charts.gauge_option(21, "done", max_value=29)
        val = opt["series"][0]["data"][0]["value"]
        assert 0 <= val <= 100

    def test_gauge_zero_max(self):
        opt = charts.gauge_option(0, "x", max_value=0)
        assert opt["series"][0]["data"][0]["value"] == 0


class TestChartComponents:
    def test_activity_component_inlines_echarts_and_option(self):
        doc = charts.activity_chart_component(
            [{"day": "2026-11-01", "event_type": "sent-dry", "n": 5}]
        )
        assert "echarts.init" in doc
        assert "2026-11-01" in doc
        assert "sent-dry" in doc
        # local bundle embedded, not a CDN src
        assert "src=\"http" not in doc

    def test_activity_component_empty_rows(self):
        doc = charts.activity_chart_component([])
        assert "echarts.init" in doc  # renders an empty chart, no crash

    def test_component_respects_reduced_motion(self):
        doc = charts.activity_chart_component(
            [{"day": "d", "event_type": "e", "n": 1}]
        )
        assert "prefers-reduced-motion" in doc

    def test_kpi_grid_countup_attrs(self):
        doc = charts.kpi_grid_component(
            [charts.kpi_card_countup("Leads", 17, "◉", "cyan")]
        )
        assert 'data-nc-count="17"' in doc
        assert "grid-template-columns: repeat(4" in doc

    def test_kpi_grid_responsive_columns(self):
        doc = charts.kpi_grid_component([], columns=3)
        assert "repeat(3" in doc

    def test_kpi_grid_component_embeds_card_css(self):
        # components render in their own iframe — styling must be embedded
        doc = charts.kpi_grid_component([charts.kpi_card_countup("L", 1, "◈")])
        assert ".nc-card" in doc
        assert "#10192A" in doc
        assert "Space Grotesk" in doc

    def test_sparkline_svg(self):
        svg = charts.sparkline_svg([1, 2, 3, 2])
        assert svg.startswith("<svg") and "polyline" in svg
        assert charts.sparkline_svg([]) == ""
        # flat series must not divide by zero
        assert "polyline" in charts.sparkline_svg([5, 5, 5])

    def test_option_json_serializable(self):
        # every builder output must survive json round-trip
        docs = [
            charts.area_option(["a"], [{"name": "n", "values": [1]}]),
            charts.donut_option([("a", 1)]),
            charts.bar_option(["a"], [1], horizontal=True),
            charts.gauge_option(1, "n", max_value=2),
        ]
        for doc in docs:
            json.dumps(doc)


class TestEchartsBundle:
    def test_bundle_ships_locally(self):
        path = charts._ECHARTS_PATH
        assert path.exists(), f"missing local echarts bundle: {path}"
        assert path.stat().st_size > 500_000  # real minified build, not a stub

    def test_missing_bundle_raises_clear_error(self):
        class FakePath:
            exists = lambda self: False  # noqa: E731

        original = charts._ECHARTS_PATH
        charts._ECHARTS_PATH = FakePath()  # type: ignore[assignment]
        try:
            with pytest.raises(FileNotFoundError):
                charts._echarts_js()
        finally:
            charts._ECHARTS_PATH = original


class TestDocsReader:
    def test_split_sections_basic(self):
        md = "# Title\nintro\n## Alpha\nbody a\n## Beta\nbody b"
        secs = docs.split_sections(md)
        assert secs == [("Alpha", "body a"), ("Beta", "body b")]

    def test_split_sections_empty(self):
        assert docs.split_sections("") == []
        assert docs.split_sections("no headings") == []

    def test_split_sections_drops_preamble(self):
        md = "preamble junk\n## One\nx"
        assert docs.split_sections(md) == [("One", "x")]

    def test_guide_exists_and_sections(self):
        md = docs.load_guide()
        assert len(md) > 2000
        titles = [t for t, _ in docs.split_sections(md)]
        assert len(titles) == 10

    def test_build_groups_covers_all_guide_sections(self):
        md = docs.load_guide()
        grouped = {n for g in docs.DOC_GROUPS for n in g[1]}
        titles = {t for t, _ in docs.split_sections(md)}
        # every guide section must be reachable from a docs tab
        missing = titles - grouped
        assert not missing, f"sections missing from docs tabs: {missing}"

    def test_missing_file_never_raises(self):
        assert docs.load_guide("/nonexistent/guide.md") == ""

    def test_guide_is_feature_usage_not_readme(self):
        # the guide documents how to USE features (verbs, page names)
        md = docs.load_guide()
        for needle in ("Memulai", "Tambah job", "Enqueue job", "DRY RUN",
                       "placeholder", "unsubscri"):
            assert needle.lower() in md.lower(), f"guide missing usage doc: {needle}"


class TestFlashAlert:
    """theme.flash_alert — SweetAlert-style modal (parent DOM, CSS-only)."""

    def test_ok_card_structure(self):
        html = theme.flash_alert("ok", "Job #13 masuk antrian", "worker memproses ±30s")
        assert 'class="nc-flash nc-flash-ok"' in html
        assert "Job #13 masuk antrian" in html
        assert "worker memproses" in html
        assert 'role="status"' in html
        assert "✓" in html

    def test_err_card_structure(self):
        html = theme.flash_alert("err", "Gagal enqueue job", "Error: boom")
        assert 'class="nc-flash nc-flash-err"' in html
        assert "✕" in html
        assert "Error: boom" in html

    def test_message_is_escaped(self):
        html = theme.flash_alert("ok", "t", "<script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_css_keyframes_present(self):
        css = theme.theme_css()
        for kf in ("nc-flash-in", "nc-flash-life", "nc-flash-drain"):
            assert kf in css, f"missing keyframes: {kf}"
