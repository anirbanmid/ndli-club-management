"""
Round-2 UI sweep guard tests (r14) - lock the clear-win fixes against regression.

Static template/CSS assertions only; no server, no data provisioning.
Every assertion here corresponds to a fix delivered in the Round-2
implementation phase (changelogs: r2_impl_css.md / r2_impl_emp_changelog.md /
r2_impl_aiv_changelog.md).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
from admin_view import admin_js_view
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel_path):
    with open(os.path.join(ROOT, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def tag_with(html, tag, marker):
    """Return the full <tag ...> element containing marker, or '' if absent."""
    for m in re.finditer(r"<" + tag + r"\b[^>]*>", html):
        if marker in m.group(0):
            return m.group(0)
    return ""


class TestR2AdminFixes(unittest.TestCase):
    """admin.html - duplicate footer, silent CSV failures, keyboard cards,
    SVG distortion, roster escaping, restore CAPTCHA, login label drift."""

    @classmethod
    def setUpClass(cls):
        cls.html = admin_js_view()

    def test_single_system_footer(self):
        self.assertEqual(self.html.count('class="system-footer"'), 1,
                         "admin.html must have exactly one system-footer (duplicate stacked footer P1)")

    def test_no_global_alert_target(self):
        self.assertNotIn('showAlert("global-alert"', self.html,
                         "CSV failure alerts must target an existing container (admin-alert)")

    def test_kpi_cards_keyboard_accessible(self):
        for marker in ('id="card-renewal-attention"', 'id="card-admin-escalations"',
                       'id="admin-escalations-kpi-card"'):
            tag = tag_with(self.html, "div", marker)
            self.assertTrue(tag, f"{marker} missing")
            self.assertIn('role="button"', tag, f"{marker} lacks role=button")
            self.assertIn('tabindex="0"', tag, f"{marker} lacks tabindex=0")
            self.assertIn('aria-label=', tag, f"{marker} lacks aria-label")

    def test_trajectory_svg_not_distorted(self):
        self.assertNotIn('preserveAspectRatio="none"', self.html,
                         "trajectory SVG must not stretch (use xMidYMid meet)")
        self.assertIn('preserveAspectRatio="xMidYMid meet"', self.html)

    def test_roster_escaping(self):
        self.assertIn("escapeHtml(emp.id)", self.html)
        self.assertIn("nameSafe", self.html)
        self.assertNotIn("safeEscapePerf", self.html)

    def test_restore_captcha_visible_five_char(self):
        self.assertNotIn("line-through", self.html,
                         "restore CAPTCHA display must not be struck through")
        tag = tag_with(self.html, "input", 'id="restore-captcha-input"')
        self.assertTrue(tag, "restore-captcha-input missing")
        self.assertIn('maxlength="5"', tag)

    def test_change_password_modal_dismissible(self):
        self.assertGreaterEqual(self.html.count("closeChangePasswordModal"), 2,
                                "change-password modal must be in Escape AND backdrop chains")


class TestR2EmployeeFixes(unittest.TestCase):
    """employee.html - duplicate footer, digits-only SEC C, dead code removal."""

    @classmethod
    def setUpClass(cls):
        cls.html = read("templates/employee.html")

    def test_single_system_footer(self):
        self.assertEqual(self.html.count('class="system-footer"'), 1,
                         "employee.html must have exactly one system-footer")

    def test_sec_c_reg_input_digits_only(self):
        self.assertIn('inputmode="numeric"', self.html,
                      "SEC C registration input must be numeric-keypad / digits-only")
        self.assertIn("e.g., 2051", self.html)

    def test_dead_switch_employee_removed(self):
        self.assertNotIn("function switchEmployee", self.html)


class TestR2VerifyFixes(unittest.TestCase):
    """verify.html - transport errors must not read as 'not authentic'."""

    @classmethod
    def setUpClass(cls):
        cls.html = read("templates/verify.html")

    def test_unavailable_state_exists(self):
        self.assertIn('id="state-unavailable"', self.html,
                      "verify.html needs a distinct SERVICE UNAVAILABLE state")
        self.assertIn("This is not a verdict on the certificate", self.html)

    def test_not_found_copy_preserved(self):
        self.assertIn("RECORD NOT FOUND OR UNVERIFIED", self.html)

    def test_print_styles(self):
        self.assertIn("@media print", self.html)


class TestR2StyleTokens(unittest.TestCase):
    """style.css / assistant.css - dead tokens and phantom classes."""

    @classmethod
    def setUpClass(cls):
        cls.style = read("static/css/style.css")
        cls.asst = read("static/css/assistant.css")

    def test_accent_token_defined(self):
        self.assertRegex(self.style, r"--accent:\s*#D97706",
                         "--accent must be defined (was referenced but undefined x6)")

    def test_phantom_button_classes_defined(self):
        self.assertIn(".btn-warning", self.style)
        self.assertIn(".btn-md", self.style)
        self.assertIn(".pill-accent", self.style)
        self.assertIn(".pill-outline", self.style)

    def test_sticky_navbar_overflow_fix(self):
        self.assertIn("overflow-x: clip", self.style,
                      "html,body overflow-x must use clip (hidden kills position:sticky)")

    def test_long_words_wrap_in_widget(self):
        self.assertIn("overflow-wrap: anywhere", self.asst)


if __name__ == "__main__":
    unittest.main()
