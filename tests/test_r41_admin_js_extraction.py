"""R41 — admin.html inline JS extraction (roadmap #4): layout locks.

R41 moved every inline <script> body of templates/admin.html into static/js
admin_*.js modules (byte-verbatim; proven by .openclaw/tmp/verify_admin_js.py
reconstruction). These pins lock the layout against drift:

  1. admin.html carries NO inline script bodies (markup only).
  2. The admin_*.js modules are referenced in the template in exactly the
     expected order (load order is semantics: cross-module references).
  3. Every referenced module exists on disk and parses (node --check when
     node is available).
  4. Feature functions live in exactly ONE module (definition-location pins
     — a follow-the-code guard for future extractions).
"""
import re
import shutil
import subprocess
import unittest

from admin_view import ROOT, admin_module_names

EXPECTED_ORDER = [
    "admin_boot.js", "admin_dashboard.js", "admin_master_csv.js", "admin_backup.js",
    "admin_hard_reset.js", "admin_training.js", "admin_restore.js", "admin_escalations.js",
    "admin_analytics.js", "admin_auth.js", "admin_employees.js", "admin_attention.js",
    "admin_utils.js", "admin_club_details.js", "admin_migration.js", "admin_init.js",
    "admin_password.js",
]

# feature function -> the module that must define it (exactly once across modules)
DEFINITIONS = {
    "function renderKPIs(data)": "admin_analytics.js",
    "function renderActivityMatrix(quotas)": "admin_analytics.js",
    "function splitNote(live, migrated)": "admin_analytics.js",
    "async function loadDashboardData()": "admin_dashboard.js",
    "async function loadEmployeePerformance()": "admin_analytics.js",
    "function renderRenewalAttentionList(page = 1)": "admin_attention.js",
    "async function openClubDetailsModal(clubId, returnTo)": "admin_club_details.js",
    "function renderClubDetailsView(club)": "admin_club_details.js",
    "async function commitMigration()": "admin_migration.js",
    "function initModalEventListeners()": "admin_init.js",
    "function openChangePasswordModal()": "admin_password.js",
    "async function checkAdminAuth()": "admin_auth.js",
}


class TestR41AdminJsExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
        cls.names = admin_module_names()

    def test_no_inline_script_bodies_left(self):
        bodies = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", self.html)
        self.assertEqual([b for b in bodies if b.strip()], [],
                         "admin.html must carry markup only — JS lives in static/js/admin_*.js")

    def test_module_order_matches_load_semantics(self):
        self.assertEqual(self.names, EXPECTED_ORDER,
                         "script src order is load order = semantics; change it only on purpose")

    def test_modules_exist_and_parse(self):
        for name in self.names:
            path = ROOT / "static" / "js" / name
            self.assertTrue(path.exists(), f"missing {name}")
            self.assertGreater(path.stat().st_size, 0, f"empty {name}")
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        for name in self.names:
            res = subprocess.run([node, "--check", str(ROOT / "static" / "js" / name)],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"{name} has JS syntax error: {res.stderr}")

    def test_feature_definitions_live_in_one_module(self):
        for needle, home in DEFINITIONS.items():
            found = []
            for name in self.names:
                text = (ROOT / "static" / "js" / name).read_text(encoding="utf-8")
                if needle in text:
                    found.append(name)
            self.assertEqual(found, [home],
                             f"{needle!r} must be defined exactly once, in {home}")

    def test_existing_external_scripts_untouched(self):
        # pre-R41 external modules keep their place/relative order
        for tag in ('<script src="/static/js/app.js"></script>',
                    '<script src="/static/js/ui.js"></script>',
                    '<script src="/static/js/shell.js?v=20261007"></script>',
                    '<script src="/static/js/assistant.js"></script>',
                    '<script src="/static/js/report_generator.js"></script>'):
            self.assertIn(tag, self.html)
        self.assertLess(self.html.index("/static/js/app.js"), self.html.index("admin_dashboard.js"))
        self.assertLess(self.html.index("admin_init.js"), self.html.index("/static/js/assistant.js"))


if __name__ == "__main__":
    unittest.main()
