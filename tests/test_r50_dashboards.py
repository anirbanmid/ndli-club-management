"""
tests/test_r50_dashboards.py -- R50: authenticated dashboards at small widths.

Scope (user's R49/R50 split): admin + employee dashboard KPI stacks, tables and
toolbars at laptop (<=1400px) and phone (<=520px) widths.

The root cause (measured): the <=980px stacked shell left `.app-main`
width-auto (= min-content via align-items: flex-start), so the admin dashboard
laid out at 822px inside a 390px viewport and every card/table squeezed.

Guard rails:
  * desktop >1400px stays pixel-identical -- every R50 rule must live inside a
    max-width media block (structural check), and the base (unscoped) shell/KPI
    definitions must remain verbatim.
  * R49/R48 locks stay in their own files; the cache-stamp pin moved forward in
    test_r49_responsive (pin-follow: d -> g with this round's style.css).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "css" / "style.css"
ADMIN = ROOT / "templates" / "admin.html"
EMPLOYEE = ROOT / "templates" / "employee.html"
TMPL_FILES = ["templates/admin.html", "templates/employee.html",
              "templates/index.html", "templates/verify.html"]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def media_block(text, query, last=False):
    """Return the body of @media (<query>) { ... } (balanced braces)."""
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


def media_block_span(text, query, last=False):
    """Return (start, end) offsets of the media block body."""
    marker = "@media (%s) {" % query
    start = text.rfind(marker) if last else text.find(marker)
    if start < 0:
        return (-1, -1)
    i = start + len(marker)
    depth = 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return (start + len(marker), i - 1)


CSS_TEXT = read("static/css/style.css")
BLK_980 = media_block(CSS_TEXT, "max-width: 980px")
BLK_1400 = media_block(CSS_TEXT, "max-width: 1400px")
# There are TWO @media (max-width: 520px) blocks (R49's, then R50's) -- the
# R50 one is the last.
BLK_520_R50 = media_block(CSS_TEXT, "max-width: 520px", last=True)
R50_SPANS = [media_block_span(CSS_TEXT, "max-width: 980px"),
             media_block_span(CSS_TEXT, "max-width: 1400px"),
             media_block_span(CSS_TEXT, "max-width: 520px", last=True)]


class TestRootCauseAppMainFitsViewport(unittest.TestCase):
    """The dashboard page must fit the viewport when the shell stacks."""

    def test_app_main_stretches_in_stacked_shell(self):
        self.assertIn("/* R50 root cause", BLK_980,
                      "the <=980px block lost the R50 root-cause comment")
        self.assertIn(".app-main { align-self: stretch; min-width: 0; }", BLK_980)

    def test_root_fix_is_inside_the_980_media_block(self):
        idx = CSS_TEXT.find(".app-main { align-self: stretch; min-width: 0; }")
        self.assertGreater(idx, 0)
        self.assertIn("max-width: 980px", CSS_TEXT[max(0, idx - 2500):idx],
                      "root-cause fix escaped its media block")


class TestR50RulesScopedToSmallWidths(unittest.TestCase):
    """Desktop >1400px untouched: every R50 rule sits in a max-width block."""

    def test_r50_block_markers_present(self):
        self.assertIn("R50: dashboard small-display fixes", CSS_TEXT)
        self.assertIn("R50 root cause", BLK_980)
        self.assertIn("JS-rendered alert banners", BLK_1400)
        self.assertIn("SEC B action buttons", BLK_520_R50)

    def test_every_r50_rule_lives_in_a_media_block(self):
        # Every distinctive R50 rule must sit inside one of the three extracted
        # media blocks -- nothing may leak into the unscoped (desktop) CSS.
        rules = [
            ".app-main { align-self: stretch; min-width: 0; }",
            ".escalation-kpi-stack,",
            ".filter-bar > div:last-child {",
            "#state-breakdown-table { min-width: 680px; }",
            "#quota-legacy-line { font-size: 11px !important; }",
            ".footer-credit-box .dev-role { font-size: 0.72rem; }",
            # block-indented forms so base-rule lookalikes (.top-user at top
            # level, etc.) cannot satisfy these find() calls
            "#live-clock {\n    flex-wrap: wrap !important;",
            "#live-clock span { white-space: nowrap; }",
            ".top-user {\n    flex-wrap: wrap;",
            ".activity-matrix { overflow-x: auto; }",
            "#btn-open-sec-c-import,",
        ]
        for rule in rules:
            idx = CSS_TEXT.find(rule)
            self.assertGreaterEqual(idx, 0, "R50 rule missing: %s" % rule)
            inside = any(a <= idx <= b for a, b in R50_SPANS)
            self.assertTrue(inside,
                            "R50 rule escaped its @media block: %s" % rule)

    def test_base_shell_definitions_verbatim(self):
        self.assertIn(".app-shell { display: flex; align-items: flex-start; min-height: 100vh; }", CSS_TEXT)
        self.assertIn(".app-main { flex: 1; min-width: 0; display: flex; flex-direction: column; font-size: 12.5px; }", CSS_TEXT)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));", CSS_TEXT)
        self.assertIn(".stat-card {\n  background: #ffffff;", CSS_TEXT)


class TestBannersWrapInsteadOfSqueezing(unittest.TestCase):
    """JS-rendered alert banners (inline flex rows) must wrap at small widths."""

    def test_banner_rows_wrap(self):
        self.assertIn(".escalation-kpi-stack,\n  .employee-reminders-kpi-stack {\n    flex-wrap: wrap !important;", BLK_1400)
        self.assertIn("gap: 0.75rem 1rem !important;", BLK_1400)

    def test_banner_text_blocks_shrink(self):
        self.assertIn(".escalation-kpi-stack > div,\n  .employee-reminders-kpi-stack > div { min-width: 0; }", BLK_1400)

    def test_banner_action_button_never_stacks(self):
        self.assertIn(".escalation-kpi-stack .btn,\n  .employee-reminders-kpi-stack .btn { white-space: nowrap; }", BLK_1400)


class TestAnalyticsToolbar(unittest.TestCase):
    def test_action_cluster_stops_floating_mid_bar(self):
        self.assertIn(".filter-bar > div:last-child {\n    margin-left: 0 !important;\n    width: 100%;\n  }", BLK_1400)
        self.assertIn(".filter-bar { row-gap: 0.75rem; }", BLK_1400)


class TestTablesScrollInsteadOfCrushing(unittest.TestCase):
    def test_matrix_min_widths(self):
        self.assertIn("#state-breakdown-table { min-width: 680px; }", BLK_1400)
        self.assertIn("#employee-performance-table { min-width: 920px; }", BLK_1400)

    def test_cells_share_a_vertical_axis(self):
        self.assertIn("#state-breakdown-table th, #state-breakdown-table td,\n  #employee-performance-table th, #employee-performance-table td {\n    vertical-align: middle;\n  }", BLK_1400)


class TestMicroTypeFloors(unittest.TestCase):
    def test_quota_breakdown_line_readable(self):
        self.assertIn("#quota-legacy-line { font-size: 11px !important; }", BLK_1400)

    def test_footer_credit_line_readable(self):
        self.assertIn(".footer-credit-box .dev-role { font-size: 0.72rem; }", BLK_1400)


class TestPhoneClockKeepsSegmentsIntact(unittest.TestCase):
    """The IST badge is an inline-flex of 4 segments: wrap BETWEEN segments."""

    def test_clock_flex_wraps_but_segments_do_not(self):
        self.assertIn("#live-clock {\n    flex-wrap: wrap !important;", BLK_520_R50)
        self.assertIn("#live-clock span { white-space: nowrap; }", BLK_520_R50)


class TestTopUserClusterShrinks(unittest.TestCase):
    def test_top_user_wraps_and_ellipsizes(self):
        self.assertIn(".top-user {\n    flex-wrap: wrap;\n    min-width: 0;\n    padding-left: 0;\n  }", BLK_520_R50)
        self.assertIn(".top-user .nm {\n    min-width: 0;\n    overflow: hidden;\n    text-overflow: ellipsis;\n    white-space: nowrap;\n  }", BLK_520_R50)


class TestActivityMatrixScrolls(unittest.TestCase):
    def test_matrix_scrolls_rows_keep_their_chips(self):
        self.assertIn(".activity-matrix { overflow-x: auto; }", BLK_520_R50)
        self.assertIn(".activity-row { min-width: 480px; }", BLK_520_R50)


class TestSecBButtonsWrapWithBalance(unittest.TestCase):
    def test_three_action_buttons_balanced(self):
        for bid in ("#btn-open-sec-c-import", "#btn-open-sec-c", "#btn-open-bulk-import"):
            self.assertIn(bid, BLK_520_R50)
        self.assertIn("text-wrap: balance;\n    line-height: 1.4;", BLK_520_R50)


class TestEmployeeQuotaPairsNoWrap(unittest.TestCase):
    """Number + label pairs stay together; JS still finds the ids it sets."""

    def test_pairs_wrapped_in_nowrap_spans(self):
        text = read("templates/employee.html")
        for qid in ("quota-clubs-count", "quota-online-count",
                    "quota-offline-count", "quota-support-count"):
            self.assertIn('<span style="white-space: nowrap;"><span id="%s"' % qid, text,
                          "quota pair %s is not nowrap-grouped" % qid)

    def test_js_contract_ids_still_unique(self):
        text = read("templates/employee.html")
        for qid in ("quota-clubs-count", "quota-online-count",
                    "quota-offline-count", "quota-support-count",
                    "quota-legacy-line", "live-clock"):
            self.assertEqual(text.count('id="%s"' % qid), 1,
                             "id %s must appear exactly once" % qid)


class TestCacheStampsMovedForward(unittest.TestCase):
    def test_all_stylesheet_links_carry_the_r50_stamp(self):
        total = 0
        for rel in TMPL_FILES:
            for m in re.finditer(r'<link rel="stylesheet" href="([^"]+)"', read(rel)):
                self.assertIn("?v=20261014c", m.group(1),
                              "%s: stylesheet link missing the R50 stamp: %s" % (rel, m.group(1)))
                total += 1
        self.assertGreaterEqual(total, 11, "expected the 11 stamped links from R49/R50")

    def test_pin_follow_stamp_updated_in_r49_file(self):
        text = read("tests/test_r49_responsive.py")
        self.assertIn("?v=20261014c", text,
                      "test_r49 stamp pin must follow the moving stamp")


if __name__ == "__main__":
    unittest.main()
