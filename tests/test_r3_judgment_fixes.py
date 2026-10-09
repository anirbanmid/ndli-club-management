"""
Round-3 judgment-call guard tests (r15) - lock the R15 fixes against regression.

Static template/CSS/JS assertions only; no server, no data provisioning.
Covers: certificate print fix + Verify-button removal (#16), NDLI main-logo
links (#17), zones->6 copy + "Active Nodal Officers" relabel + rubric copy,
reminders red-tint header, --accent call-site contrast swap, alert hybrid,
Phase-2 a11y (tabs ARIA, modal protocol, z-index ladder).
Changelogs: r3_aiv_changelog.md / r3_css_changelog.md / r3_phase2_changelog.md.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel_path):
    with open(os.path.join(ROOT, rel_path), "r", encoding="utf-8") as f:
        return f.read()


TEMPLATES = ["templates/admin.html", "templates/index.html",
             "templates/employee.html", "templates/verify.html"]


class TestR3CertificatePrintFix(unittest.TestCase):
    """#16a print route (synchronous, user-activation safe) + #16b Verify button removal."""

    @classmethod
    def setUpClass(cls):
        cls.engine = read("static/js/certificate_engine.js")
        cls.emp = read("templates/employee.html")

    def test_onpage_print_route_exists_and_exported(self):
        self.assertIn("function printCertificateOnPage(canvas)", self.engine)
        self.assertIn("printCertificateOnPage: printCertificateOnPage", self.engine)

    def test_print_route_uses_media_print_a4(self):
        self.assertIn("@media print", self.engine)
        self.assertIn("size: A4 portrait", self.engine)
        self.assertIn("certificate-print-style", self.engine)

    def test_employee_print_calls_onpage_route(self):
        # synchronous path must invoke the on-page route from the click handler
        self.assertIn("CertificateEngine.printCertificateOnPage(c)", self.emp)
        self.assertIn("function printActiveCertificate()", self.emp)

    def test_popup_route_kept_as_fallback_only(self):
        self.assertIn("printCertificate: printCertificate", self.engine)

    def test_render_settled_flag_tracks_sync_path(self):
        self.assertIn("CURRENT_CERT_RENDER_SETTLED", self.emp)

    def test_verify_online_button_and_handler_removed(self):
        self.assertNotIn("openActiveCertificateVerificationLink", self.emp)
        self.assertNotIn("Verify Online", self.emp)
        # removed from every template + static js, not just employee.html
        for rel in TEMPLATES + ["static/js/certificate_engine.js", "static/js/app.js"]:
            self.assertNotIn("openActiveCertificateVerificationLink", read(rel), rel)


class TestR3NdlILogos(unittest.TestCase):
    """#17 NDLI MAIN logos (not the club logo) link to the NDLI main site."""

    LOGO_ANCHOR = re.compile(
        r'<a href="https://ndl\.iitkgp\.ac\.in"[^>]*>\s*<img[^>]*NDLI_Main_Logo')

    def test_four_main_logo_wraps(self):
        counts = {rel: len(self.LOGO_ANCHOR.findall(read(rel))) for rel in TEMPLATES}
        self.assertEqual(counts["templates/admin.html"], 1, counts)
        self.assertEqual(counts["templates/index.html"], 2, counts)
        self.assertEqual(counts["templates/verify.html"], 1, counts)

    def test_logo_links_secure_rel(self):
        for rel in TEMPLATES:
            html = read(rel)
            for m in re.finditer(r'<a href="https://ndl\.iitkgp\.ac\.in"[^>]*>', html):
                self.assertIn('rel="noopener noreferrer"', m.group(0), rel)
                self.assertIn('target="_blank"', m.group(0), rel)


class TestR3ZonesRelabelRubric(unittest.TestCase):
    """Zones->6 copy, "Active Nodal Officers" relabel, honest rubric wording."""

    @classmethod
    def setUpClass(cls):
        cls.files = {rel: read(rel) for rel in TEMPLATES}

    def test_no_ambiguous_7_regional_literal(self):
        for rel, html in self.files.items():
            self.assertNotIn("7 Regional", html, rel)

    def test_zone_counts_are_six(self):
        self.assertIn("6 Regional Nodal Zones", self.files["templates/admin.html"])
        self.assertGreaterEqual(
            self.files["templates/index.html"].count("6 Regional Nodal Zones"), 2)
        self.assertIn("6 Regional Operational Zones", self.files["templates/index.html"])

    def test_active_nodal_officers_relabel(self):
        self.assertIn("Active Nodal Officers", self.files["templates/admin.html"])
        self.assertIn("Active Nodal Officers", self.files["templates/index.html"])
        for rel, html in self.files.items():
            self.assertNotIn("Active Regional Nodes", html, rel)

    def test_rubric_copy(self):
        admin = self.files["templates/admin.html"]
        self.assertIn("Scoring Rubric (50/30/20/10 points)", admin)
        self.assertNotIn("Official Evaluation Formula", admin)


class TestR3RemindersTintAndAccentContrast(unittest.TestCase):
    """Reminders red-tint header stays (urgency idiom) + --accent call-site contrast swap."""

    @classmethod
    def setUpClass(cls):
        cls.emp = read("templates/employee.html")

    def test_reminders_thead_red_tint(self):
        self.assertIn('thead class="reminders-thead"', self.emp)
        self.assertIn(".reminders-thead th", self.emp)

    def test_no_white_on_accent_call_sites(self):
        # token value itself is test-locked in test_r2_ui_fixes; call sites
        # switched to var(--warning) (#B45309 = 5.05:1) for text/badge uses
        self.assertNotIn("color: var(--accent)", self.emp)
        self.assertNotIn("background: var(--accent)", self.emp)
        self.assertIn("var(--warning)", self.emp)


class TestR3AlertHybrid(unittest.TestCase):
    """Short alerts -> showAlert/UI.toast; long backup/restore payloads stay native (admin)."""

    @classmethod
    def setUpClass(cls):
        cls.emp = read("templates/employee.html")

    def test_employee_success_path_uses_global_container(self):
        self.assertIn('showAlert("global-alert"', self.emp)
        self.assertIn("Unresolved issue logged", self.emp)

    def test_no_template_literal_native_alerts_in_employee(self):
        self.assertNotIn("alert(`", self.emp)


class TestR3Phase2A11y(unittest.TestCase):
    """Tabs ARIA + modal dialog protocol + z-index ladder."""

    @classmethod
    def setUpClass(cls):
        cls.app = read("static/js/app.js")
        cls.style = read("static/css/style.css")
        cls.admin = read("templates/admin.html")
        cls.emp = read("templates/employee.html")

    def test_tabs_keyboard_and_aria(self):
        self.assertIn("role=\"tablist\"", self.admin)
        self.assertIn("role=\"tablist\"", self.emp)
        self.assertIn("ArrowLeft", self.app)
        self.assertIn("aria-selected", self.app)

    def test_tabpanels_labelled(self):
        self.assertEqual(self.admin.count('role="tabpanel"'), 4)
        self.assertEqual(self.emp.count('role="tabpanel"'), 4)
        self.assertEqual(self.admin.count('role="tab"'), 4)
        self.assertEqual(self.emp.count('role="tab"'), 4)

    def test_modals_dialog_protocol(self):
        # R25: the admin Club Register modal joined the ladder (+1 admin modal).
        # R26: the employee Bulk Import modal joined the ladder (+1 employee modal).
        # R30: the admin Data Migration modal joined the ladder (+1 admin modal):
        # 10 base dialogs + Club Register + Data Migration = 12, every dialog
        # paired 1:1 with aria-modal="true" (pre-R30 pin was 11/11 — verified
        # against the deployed PA copy of admin.html).
        self.assertEqual(self.admin.count('aria-modal="true"'), 12)
        self.assertEqual(self.emp.count('aria-modal="true"'), 8)
        self.assertEqual(self.admin.count('role="dialog"'), 12)
        self.assertEqual(self.emp.count('role="dialog"'), 8)

    def test_modal_focus_helpers_defined_and_exported(self):
        self.assertIn("function ndliModalOpened(modal)", self.app)
        self.assertIn("function ndliModalClosed(modal)", self.app)
        self.assertIn("window.ndliModalOpened = ndliModalOpened", self.app)
        self.assertIn("window.ndliModalClosed = ndliModalClosed", self.app)

    def test_z_index_ladder_tokens(self):
        self.assertIn("--z-modal-top", self.style)
        self.assertIn("--z-toast", self.style)
        self.assertIn("--z-sticky-head", self.style)
        # ladder consumption: style.css on stacking rules, ui.css toast on --z-toast
        self.assertIn("z-index: var(--z-sticky-head)", self.style)
        self.assertIn("z-index: var(--z-toast", read("static/css/ui.css"))


if __name__ == "__main__":
    unittest.main()
