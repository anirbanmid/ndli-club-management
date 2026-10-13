"""
tests/test_r51_nav_charts.py -- R51: mobile nav drawer + chart polish.

Part A (user report 2026-10-14): on phones the sidebar scroll-strip stacked
above the sticky topbar (145px of chrome over the KPI cards; the two panels
overlapped while scrolling). User order: "the side panel should be placed
within a clickable menu button in mobile". The strip is gone; the sidebar is
now an off-canvas drawer behind a topbar menu button (<=980px).

Part B (chart/infographics polish, all widths -- the explicit chart round):
trajectory axis labels thinned + plot gutters aligned to the card content,
donut legend compact (was stretching the full card width), infographic header
pill top-aligned with the title.

Guard rails:
  * desktop >980px keeps the fixed sidebar verbatim; the menu button hides via
    a min-width media rule (NOT a bare display:none at file end -- that would
    override the <=980 display (cascade trap, cf. R49 .app-search)).
  * R49/R50 locks stay (topbar wrap, .app-main stretch, R50 scoping).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "css" / "style.css"
JS_SHELL = ROOT / "static" / "js" / "shell.js"
JS_AN = ROOT / "static" / "js" / "admin_analytics.js"
TMPL_FILES = ["templates/admin.html", "templates/employee.html",
              "templates/index.html", "templates/verify.html"]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def media_block(text, query, last=False):
    marker = "@media (%s) {" % query
    start = text.rfind(marker) if last else text.find(marker)
    if start < 0:
        return ""
    i = start + len(marker)
    depth = 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start + len(marker):i - 1]


CSS_TEXT = read("static/css/style.css")
BLK_980 = media_block(CSS_TEXT, "max-width: 980px")
# TWO 520 blocks exist: R49's (first -- topbar wrap lock) and R50's (last).
BLK_520_R49 = media_block(CSS_TEXT, "max-width: 520px")
BLK_520 = media_block(CSS_TEXT, "max-width: 520px", last=True)
BLK_MIN_981 = media_block(CSS_TEXT, "min-width: 981px")


class TestMobileNavDrawer(unittest.TestCase):
    """Part A: the side panel lives behind a menu button on mobile."""

    def test_hamburger_button_in_both_portals(self):
        for rel in ("templates/admin.html", "templates/employee.html"):
            text = read(rel)
            self.assertIn('class="nav-toggle icon-btn" id="nav-toggle"', text,
                          "%s: menu button missing" % rel)
            self.assertIn('aria-controls="app-sidebar"', text, rel)
            self.assertIn('aria-expanded="false"', text, rel)

    def test_scrim_in_both_portals(self):
        for rel in ("templates/admin.html", "templates/employee.html"):
            self.assertIn('<div class="nav-scrim" id="nav-scrim" hidden></div>',
                          read(rel), rel)

    def test_sidebar_is_an_off_canvas_drawer(self):
        self.assertIn("position: fixed;", BLK_980)
        self.assertIn("transform: translateX(-100%);", BLK_980)
        self.assertIn(".app-shell.nav-open .app-sidebar { transform: translateX(0); }",
                      BLK_980)

    def test_scrollbackdrop_only_when_open(self):
        self.assertIn(".nav-scrim:not([hidden]) {", BLK_980)
        self.assertIn(".nav-scrim[hidden] { display: none; }", CSS_TEXT)

    def test_the_old_scroll_strip_is_gone(self):
        # The R19/R21-era strip conversions must NOT survive in the 980 block.
        for literal in (".app-sidebar .tab-btn { width: auto; white-space: nowrap;",
                        ".side-caption { display: none; }",
                        "flex-direction: row; align-items: center; gap: 8px;",
                        "overflow-x: auto; padding: 12px 14px;"):
            self.assertNotIn(literal, BLK_980,
                             "strip rule survived the drawer rewrite: %r" % literal)

    def test_menu_button_hide_is_order_proof(self):
        # Cascade-trap lock: bare `display: none` at file end would beat the
        # <=980 rule; the hide must be a min-width media block.
        self.assertIn("@media (min-width: 981px)", CSS_TEXT)
        self.assertIn(".nav-toggle { display: none; }", BLK_MIN_981)
        self.assertIn(".nav-toggle { display: inline-flex; }", BLK_980)

    def test_shell_js_wires_the_drawer(self):
        js = read("static/js/shell.js")
        self.assertIn("function wireNavDrawer()", js)
        self.assertIn('toggle.setAttribute("aria-expanded"', js)
        self.assertIn('(e.key === "Escape" || e.keyCode === 27)', js)
        self.assertIn("scrim.addEventListener(\"click\"", js)
        self.assertIn("wireNavDrawer();", js)

    def test_cross_round_locks_still_present(self):
        self.assertIn(".app-main { align-self: stretch; min-width: 0; }", BLK_980)
        self.assertIn("flex-wrap: wrap; row-gap: 8px;", BLK_520_R49)


class TestChartPolish(unittest.TestCase):
    """Part B: trajectory labels, donut legend, header pill alignment."""

    def test_trajectory_gutters_align_plot_to_card_content(self):
        js = read("static/js/admin_analytics.js")
        self.assertIn("const padLeft = 14;", js)
        self.assertIn("const padRight = 14;", js)
        self.assertNotIn("const padLeft = 40;", js)

    def test_trajectory_axis_labels_thinned(self):
        js = read("static/js/admin_analytics.js")
        self.assertIn("const labelStep = Math.max(1, Math.ceil(pts.length / 8));", js)
        self.assertIn("if (i % labelStep === 0 || i === pts.length - 1)", js)

    def test_r21_chart_locks_survive(self):
        js = read("static/js/admin_analytics.js")
        self.assertIn("const dLine = smoothPath(pts, 0.2);", js)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', js)
        self.assertIn('paint-order="stroke"', js)

    def test_donut_legend_is_compact(self):
        block = CSS_TEXT[CSS_TEXT.index(".donut-legend-col {"):CSS_TEXT.index(".donut-legend-item {")]
        # R51v2 pin-follow: flex: 0 1 300px forced a wrap at card widths under
        # ~468px (donut jumped on top of the zone list, user smoke 2026-10-14).
        # Basis 220 + max-width 300 keeps the pair side-by-side AND capped.
        self.assertIn("flex: 1 1 220px;", block)
        self.assertIn("max-width: 300px;", block)
        self.assertNotIn("flex: 0 1 300px;", block)

    def test_donut_group_is_centered(self):
        block = CSS_TEXT[CSS_TEXT.index(".donut-chart-container {"):]
        block = block[:block.index("}")]
        self.assertIn("justify-content: center;", block)
        self.assertNotIn("justify-content: space-around;", block)

    def test_infographic_pill_top_aligned_with_title(self):
        idx = CSS_TEXT.index(".infographic-card .card-header {")
        block = CSS_TEXT[idx:CSS_TEXT.index("}", idx)]
        self.assertIn("align-items: flex-start;", block)


class TestCacheStampsAndPinFollow(unittest.TestCase):
    STAMP = "?v=20261014c"

    def test_css_links_carry_the_r51_stamp(self):
        total = 0
        for rel in TMPL_FILES:
            for m in re.finditer(r'<link rel="stylesheet" href="([^"]+)"', read(rel)):
                self.assertIn(self.STAMP, m.group(1),
                              "%s: stylesheet link missing the R51 stamp: %s" % (rel, m.group(1)))
                total += 1
        self.assertGreaterEqual(total, 11, "expected the 11 stamped CSS links")

    def test_changed_js_links_carry_the_r51_stamp(self):
        admin = read("templates/admin.html")
        emp = read("templates/employee.html")
        self.assertIn('shell.js%s' % self.STAMP, admin)
        self.assertIn('shell.js%s' % self.STAMP, emp)
        self.assertIn('admin_analytics.js%s' % self.STAMP, admin)

    def test_pin_follow_landed_in_older_pin_files(self):
        for rel in ("tests/test_r41_admin_js_extraction.py",
                    "tests/test_r49_responsive.py",
                    "tests/test_r50_dashboards.py"):
            self.assertIn(self.STAMP, read(rel),
                          "%s must follow the moving stamps" % rel)


class TestDesktopUntouched(unittest.TestCase):
    """>980px keeps the fixed rail exactly as the user likes it."""

    def test_shell_geometry_verbatim(self):
        self.assertIn(".app-shell { display: flex; align-items: flex-start; min-height: 100vh; }", CSS_TEXT)
        self.assertIn(".app-sidebar {\n  width: 252px;\n  flex: 0 0 252px;", CSS_TEXT)
        self.assertIn(".app-topbar {\n  height: 70px; flex: 0 0 70px;", CSS_TEXT)


class TestR51v2SmokeFixes(unittest.TestCase):
    """User smoke 2026-10-14: donut wrap + trajectory gap + topbar/KPI overlap.

    All three were measured in a real browser (probe_r51v2*.py):
      * legend hypothetical size 300px wrapped the donut+list pair at a 479px
        card (donut on TOP, zone list below -- user: "space management issue");
      * .infographic-card space-between pushed the trajectory chart 233px down
        the stretched card (user: "huge blank space on top" of the line graph);
      * .top-right spilled to y=177 inside the 70px topbar box and covered the
        first KPI card by ~91px (user: "top bar overlapping with the KPI card").
    """

    def test_donut_pair_never_forces_a_wrap(self):
        block = CSS_TEXT[CSS_TEXT.index(".donut-legend-col {"):CSS_TEXT.index(".donut-legend-item {")]
        # hypothetical size 220: donut 150 + gap ~18 + 220 = 388 fits every
        # laptop card; shrink floor 150 + max-width 300 keeps the compact look
        self.assertIn("flex: 1 1 220px;", block)
        self.assertIn("min-width: 150px;", block)
        self.assertIn("max-width: 300px;", block)
        self.assertNotIn("flex: 0 1 300px;", block,
                         "the wrapping basis is back -- donut will stack again")

    def test_infographic_chart_hugs_its_header(self):
        idx = CSS_TEXT.index(".infographic-card {")
        block = CSS_TEXT[idx:CSS_TEXT.index("}", idx)]
        self.assertIn("justify-content: flex-start;", block)
        self.assertNotIn("justify-content: space-between;", block,
                         "space-between re-injects the blank gap in stretched rows")

    def test_topbar_auto_height_beats_the_base_rule(self):
        # Cascade-trap lock #3 (same disease as the nav-toggle hide): R49's
        # auto-height rule LOST to the later base `height: 70px; flex: 0 0
        # 70px` (equal specificity, later wins) and the wrapped rows spilled
        # over the first KPI card. The rule now uses the .app-shell descendant
        # selector (0,2,0) so it beats the base (0,1,0) regardless of order.
        base_idx = CSS_TEXT.index(".app-topbar {\n  height: 70px; flex: 0 0 70px;")
        fix_idx = CSS_TEXT.index(".app-shell .app-topbar {\n    height: auto; flex: 0 0 auto;")
        self.assertGreater(fix_idx, -1, "the specificity-proof auto-height rule is gone")
        # it must live in a <=520 media block (mobile-only, never desktop)
        block_start = CSS_TEXT.rfind("@media (max-width: 520px) {", 0, fix_idx)
        self.assertGreater(block_start, -1, "auto-height rule escaped the <=520 block")
        # and the base desktop rule must remain untouched (test_r49's lock)
        self.assertGreater(base_idx, -1)
        self.assertIn(".app-topbar {\n  height: 70px; flex: 0 0 70px;", CSS_TEXT)


if __name__ == "__main__":
    unittest.main()
