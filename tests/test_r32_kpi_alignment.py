"""Lock tests for R32 KPI number alignment (2026-10-10, cosmetic).

User report: "Counts/Numbers on KPI Counters, placed in the 1st row of ADMIN
portal, are not aligned well which is giving a visually unpleasant feel."

Measured in the DOM before the fix: the big numbers of the top kpi-row sat at
y=176/176/176/202 — the pill-header cards pushed their values ~26px lower.
Root causes (all CSS, fixed in the R32 block at the end of static/css/style.css):
  1. label rows grew 1-3 lines depending on wrap  -> uniform 48px label band;
  2. "View List" pills wrapped to 2 lines        -> white-space: nowrap;
  3. one card's value had an inline margin-top   -> margin-top: 0 !important.

These are static grep guards (same style as test_r20_polish / test_r21): they
pin the CSS contract the alignment depends on, plus the card anatomy the
selectors rely on (label/value spans, header-div pills, .stat-icon must stay
excluded from the header-row overrides).
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


class TestR32KpiNumberAlignment(unittest.TestCase):
    def setUp(self):
        self.style = read("static/css/style.css")

    def test_uniform_label_band(self):
        # The numbers share one baseline because every label row reserves
        # 3 lines — whatever the label wraps to.
        self.assertIn(".kpi-row .stat-card > .stat-label,", self.style)
        self.assertIn(".kpi-row .stat-card > div:not(.stat-icon) > .stat-label", self.style)
        self.assertIn("min-height: 48px", self.style)

    def test_icon_tiles_excluded_from_header_overrides(self):
        # The .stat-icon is itself a DIV child of the card — the header-row
        # overrides must not touch it (it would knock the glyph off-centre).
        self.assertIn(".kpi-row .stat-card > div:not(.stat-icon) {", self.style)
        self.assertIn("align-items: flex-start !important;", self.style)

    def test_pills_never_wrap(self):
        self.assertIn(".kpi-row .stat-card > div:not(.stat-icon) > span:not(.stat-label)", self.style)
        self.assertIn("white-space: nowrap;", self.style)

    def test_value_top_margin_zeroed(self):
        self.assertIn(".kpi-row .stat-card > .stat-value {", self.style)
        idx = self.style.index(".kpi-row .stat-card > .stat-value {")
        self.assertIn("margin-top: 0 !important;", self.style[idx:idx + 120])

    def test_admin_card_anatomy_matches_selectors(self):
        # The CSS assumes: .kpi-row > .stat-card with .stat-label + .stat-value
        # spans, and (for pill cards) a plain header div. Guard the anatomy.
        html = read("templates/admin.html")
        row = html[html.index('<div class="kpi-row">'):]
        row = row[:row.index("</div>\n\n    <!-- Global Alert -->")] if "</div>\n\n    <!-- Global Alert -->" in row else row[:6000]
        self.assertGreaterEqual(row.count('class="stat-card'), 5, "top KPI row lost cards")
        self.assertIn('class="stat-label"', row)
        self.assertIn('class="stat-value"', row)
        self.assertIn("View List ↗", row, "pill-header cards must keep their pills")
        self.assertIn('class="stat-icon', row)


if __name__ == "__main__":
    unittest.main()
