"""Lock tests for the R20 polish (2026-10-07) — user-approved variant B + 3 UI fixes.

What the user signed off (webchat, 2026-10-07 23:06):
  * look = variant "B" (DECISIVE density pass) from the A/B pick set
  * fix A: "Lock Admin" button text was INVISIBLE in the admin topbar
  * fix B: the two "Generate Comprehensive Report (PDF|DOC)" buttons are too long
          -> ONE "Create Report" button + a dropdown (1. PDF  2. DOC)
  * fix C: Edit / Block / Unblock in Employee Credential Database were huge and
          ugly -> compact in-table row actions

Static grep-based guards (same style as tests/test_r2_ui_fixes.py).
"""
import os
from admin_view import admin_js_view
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


class TestR20VariantB(unittest.TestCase):
    """The approved look: decisive density + bigger bell dot + sidebar tint."""

    def setUp(self):
        self.style = read("static/css/style.css")

    def test_variant_b_density_tokens(self):
        # DECISIVE block = html 14.5px / body 14px (CONSERVATIVE was 15px/14.5px).
        self.assertIn("R20 POLISH", self.style)
        self.assertIn("html { font-size: 14.5px; }", self.style)
        self.assertIn("body { font-size: 14px; }", self.style)

    def test_bell_dot_enlarged_and_ringed(self):
        self.assertIn("width: 11px; height: 11px; top: 7px; right: 8px;", self.style)
        self.assertIn("box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.22);", self.style)

    def test_sidebar_light_tint(self):
        # R21 (user 2026-10-08): the r20 tint (#F4F8F5 on a #F4F8F6 page) was
        # imperceptible — the sidebar tint must be VISIBLE.
        self.assertIn(".app-sidebar { background: #E2EFE8; border-right: 1px solid #CCDFD5; }",
                      self.style)


class TestR20LockAdminReadable(unittest.TestCase):
    """Fix A: the Lock Admin chip must never be white-on-light again."""

    def setUp(self):
        self.admin = admin_js_view()
        self.style = read("static/css/style.css")

    def test_lock_chip_class(self):
        self.assertIn(".btn-lock", self.style)
        self.assertIn(".btn-lock:hover", self.style)
        self.assertIn('btnEl.className = "btn btn-sm btn-lock"', self.admin)

    def test_lock_chip_clears_the_inline_white(self):
        # The bug: btnEl.style.color = "#ffffff" on a transparent .btn-outline
        # chip. The lock branch must clear the inline colour instead.
        idx = self.admin.index('btnEl.className = "btn btn-sm btn-lock"')
        chunk = self.admin[idx:idx + 220]
        self.assertIn('btnEl.style.color = "";', chunk)
        self.assertNotIn('#ffffff', chunk)


class TestR20CreateReportDropdown(unittest.TestCase):
    """Fix B: one Create Report button + PDF/DOC dropdown (see test_report_gen)."""

    def setUp(self):
        self.admin = admin_js_view()
        self.style = read("static/css/style.css")

    def test_dropdown_markup_present(self):
        self.assertIn('class="report-menu-wrap"', self.admin)
        self.assertIn('id="btn-create-report"', self.admin)
        self.assertIn('id="report-menu"', self.admin)
        self.assertIn("Create Report", self.admin)

    def test_dropdown_items_keep_entry_points(self):
        self.assertIn('id="btn-generate-report-pdf"', self.admin)
        self.assertIn('id="btn-generate-report-doc"', self.admin)
        self.assertIn("generateComprehensiveReportPdf()", self.admin)
        self.assertIn("generateComprehensiveReportDoc()", self.admin)

    def test_dropdown_styled(self):
        self.assertIn(".report-menu", self.style)
        self.assertIn(".report-menu-item", self.style)
        self.assertIn(".report-menu[hidden] { display: none; }", self.style)


class TestR20RowActions(unittest.TestCase):
    """Fix C: compact row actions in the Employee Credential Database table."""

    def setUp(self):
        self.admin = admin_js_view()
        self.style = read("static/css/style.css")

    def test_compact_tier_defined(self):
        self.assertIn(".btn-rowact", self.style)
        self.assertIn(".btn-rowact.btn-danger", self.style)
        self.assertIn(".btn-rowact.btn-success", self.style)

    def test_all_four_row_actions_use_it(self):
        for needle in ['btn-outline btn-sm btn-rowact" onclick="openEditEmployeeModalById',
                       'btn-danger btn-sm btn-rowact" onclick="handleBlockEmployee',
                       'btn-success btn-sm btn-rowact" onclick="handleUnblockEmployee',
                       'btn-outline btn-sm btn-rowact">Open UI']:
            self.assertIn(needle, self.admin)

    def test_compact_metrics(self):
        # The complaint was "huge": the row tier must be visibly smaller than .btn-sm
        idx = self.style.index(".btn-rowact {")
        chunk = self.style[idx:idx + 260]
        self.assertIn("padding: 0.26rem 0.62rem;", chunk)
        self.assertIn("font-size: 0.76rem;", chunk)


if __name__ == "__main__":
    unittest.main()
