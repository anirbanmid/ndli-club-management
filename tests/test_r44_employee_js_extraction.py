"""
tests/test_r44_employee_js_extraction.py

R44 — employee.html inline JS extraction: layout locks.

templates/employee.html now carries MARKUP ONLY; its JS lives in
static/js/employee_*.js loaded in <script src> order (20 modules, cache-busted
?v=20261013). These pins lock the arrangement so it cannot silently regress:

  * the template can never grow inline <script> bodies back;
  * every referenced module exists, is cached, and loads in the pinned order;
  * the 6 pre-existing external scripts keep their exact positions;
  * the template stays a markup file (line budget);
  * the two real order hazards stay co-located (the R44 TDZ contract).

Pure static checks: no server, no data provisioning.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

from admin_view import employee_js_view, employee_module_names

ROOT = Path(__file__).resolve().parent.parent
TMPL = ROOT / "templates" / "employee.html"
JS = ROOT / "static" / "js"

CACHE = "?v=20261013"

# The 20 modules, in the exact <script src> order the template must use.
EXPECTED_ORDER = [
    "employee_head_boot.js",
    "employee_boot.js", "employee_roster.js", "employee_clock.js",
    "employee_auth.js", "employee_profile.js", "employee_downloads.js",
    "employee_reminders.js", "employee_states.js", "employee_add_clubs.js",
    "employee_bulk_import.js", "employee_quota.js", "employee_activities.js",
    "employee_clubs.js", "employee_club_edit.js", "employee_renewal.js",
    "employee_activity_delete.js", "employee_certificate.js",
    "employee_init.js", "employee_training.js",
]

# Scripts that pre-date R44 and must not move relative to each other.
EXTERNALS = [
    "qrcode.min.js", "certificate_engine.js", "app.js", "ui.js",
    "shell.js", "assistant.js",
]

TEMPLATE_LINE_BUDGET = 2200   # measured 2,063 after R44 (was 5,256)


def tmpl_text():
    return TMPL.read_text(encoding="utf-8")


def module_text(name):
    return (JS / name).read_text(encoding="utf-8")


class TestNoInlineScriptLeft(unittest.TestCase):
    """The point of the round: no inline <script> body may come back."""

    def test_employee_html_has_zero_inline_script_blocks(self):
        html = tmpl_text()
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
        self.assertEqual(
            inline, [],
            "employee.html must carry NO inline <script> body (R44 moved them all to "
            "static/js/employee_*.js); found %d inline block(s)" % len(inline))

    def test_template_stays_a_markup_file(self):
        lines = tmpl_text().count("\n") + 1
        self.assertLessEqual(
            lines, TEMPLATE_LINE_BUDGET,
            "employee.html regressed to %d lines (budget %d) - JS has crept back into "
            "the template" % (lines, TEMPLATE_LINE_BUDGET))


class TestModuleLayout(unittest.TestCase):
    """20 modules, referenced, cached, and in the pinned load order."""

    def test_module_names_match_expected_order_exactly(self):
        self.assertEqual(employee_module_names(), EXPECTED_ORDER,
                         "employee_*.js <script src> order changed - order is load-"
                         "bearing (classic scripts share one global scope)")

    def test_every_referenced_module_exists_on_disk(self):
        missing = [n for n in employee_module_names() if not (JS / n).is_file()]
        self.assertEqual(missing, [], "referenced but missing on disk: %s" % missing)

    def test_every_module_is_cache_busted(self):
        html = tmpl_text()
        tags = re.findall(r'<script src="(/static/js/employee_[^"]+)"', html)
        self.assertEqual(len(tags), len(EXPECTED_ORDER))
        stale = [t for t in tags if not t.endswith(CACHE)]
        self.assertEqual(stale, [], "employee module tags missing %s: %s" % (CACHE, stale))

    def test_no_orphan_employee_modules(self):
        """Every employee_*.js on disk must actually be referenced (no dead weight)."""
        on_disk = sorted(p.name for p in JS.glob("employee_*.js"))
        referenced = set(employee_module_names())
        orphans = [n for n in on_disk if n not in referenced]
        self.assertEqual(orphans, [], "unreferenced employee modules: %s" % orphans)

    def test_preexisting_external_scripts_keep_their_positions(self):
        html = tmpl_text()
        # Match the real <script src> tags - a bare path also matches the HTML comment
        # <!-- Certificate Engine: src="/static/js/certificate_engine.js" --> which
        # sits ABOVE the tags and would fake an ordering failure.
        pos = [html.find('<script src="/static/js/%s' % e) for e in EXTERNALS]
        self.assertTrue(all(p > 0 for p in pos),
                        "a pre-R44 external script vanished: %s" % list(zip(EXTERNALS, pos)))
        self.assertEqual(pos, sorted(pos),
                         "pre-R44 external script order changed: %s" % list(zip(EXTERNALS, pos)))

    def test_head_boot_loads_before_the_shared_app_scripts(self):
        """The auth-bootstrap IIFE must run before app.js/ui.js/shell.js."""
        html = tmpl_text()
        boot = html.find('<script src="/static/js/employee_head_boot.js')
        appjs = html.find('<script src="/static/js/app.js"')
        self.assertTrue(0 < boot < appjs,
                        "employee_head_boot.js must load before app.js (got %s vs %s)"
                        % (boot, appjs))


class TestOrderHazardsStayCoLocated(unittest.TestCase):
    """The two real TDZ/order hazards the R44 split was designed around."""

    def test_render_officer_chips_call_stays_with_its_definition(self):
        """employee_auth.js executes renderOfficerChips() at load time. If the call
        ever lands in a module that loads BEFORE the definition, the chips silently
        stop rendering (the try/catch swallows the ReferenceError)."""
        src = module_text("employee_auth.js")
        self.assertIn("function renderOfficerChips(", src)
        self.assertIn("try { renderOfficerChips(); } catch (e) {}", src)

    def test_states_initializer_stays_with_its_source(self):
        """`let ALL_STATES = [...DEFAULT_INDIAN_STATES]` is an immediate statement;
        splitting it from DEFAULT_INDIAN_STATES would be a load-time ReferenceError."""
        src = module_text("employee_boot.js")
        self.assertIn("const DEFAULT_INDIAN_STATES = [", src)
        self.assertIn("let ALL_STATES = [...DEFAULT_INDIAN_STATES];", src)

    def test_window_exports_live_in_a_late_module(self):
        """The `window.* = *` export block references functions declared in EARLIER
        modules; it must never move ahead of them."""
        init = module_text("employee_init.js")
        self.assertIn("window.openEmployeeRemindersListModal = openEmployeeRemindersListModal;", init)
        self.assertIn("window.performUniversalSearch = performUniversalSearch;", init)
        self.assertIn("window.loadEmployeeActivities = loadEmployeeActivities;", init)
        order = employee_module_names()
        self.assertLess(order.index("employee_reminders.js"), order.index("employee_init.js"),
                        "employee_init.js must load AFTER employee_reminders.js")
        self.assertLess(order.index("employee_clubs.js"), order.index("employee_init.js"),
                        "employee_init.js must load AFTER employee_clubs.js")


class TestPinsStillHaveTheirSubject(unittest.TestCase):
    """Guards against the vacuous-pass trap: code that moved must still be covered."""

    def test_combined_view_covers_both_markup_and_modules(self):
        view = employee_js_view()
        self.assertIn('id="migrated-history-strip"', view)     # markup
        self.assertIn("function renderClubsTable(", view)      # moved JS
        self.assertIn("function escapeHtml(", view)            # moved JS
        self.assertIn("function initEmployeePortal(", view)    # moved JS

    def test_moved_code_is_not_still_inline(self):
        html = tmpl_text()
        for moved in ("function renderClubsTable(", "function escapeHtml(",
                      "function initEmployeePortal(", "let EMP_PROFILES = {"):
            self.assertNotIn(moved, html,
                             "%r is inline in employee.html again - it belongs in a "
                             "static/js/employee_*.js module" % moved)


if __name__ == "__main__":
    unittest.main()
