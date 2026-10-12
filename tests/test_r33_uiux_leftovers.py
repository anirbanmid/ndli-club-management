"""Lock tests for R33 "UI/UX leftovers" (2026-10-11) — the previously NOT-deployed
proposals from UIUX_AUDIT_LEFTOVERS.md.

Status at build time (checked against the deployed code first, per user's order):
  * P2 (elevation tokens)   — ALREADY deployed ("Polish P2" comments)  -> anti-regression pins
  * P4 (tablet KPI step)    — ALREADY deployed ("Polish P4")           -> anti-regression pins
  * P5 (tabs scroll hint)   — ALREADY deployed ("Polish P5" + ui.js)   -> anti-regression pins
  * P1 (CTA hierarchy)      — NOT real: btn-primary and btn-accent rendered the
                              IDENTICAL gradient + shadow ("two names, one look").
                              NOW: btn-primary = solid deep-green (--primary-dark),
                              btn-accent keeps the gradient. btn-amber stays hero.
  * P3 (skeleton first-paint) — NOT deployed (no ui-skeleton usage existed).
                              NOW: window.withSkeleton() helper (static/js/ui.js)
                              wraps table containers in the existing shimmer while
                              the admin dashboard + performance fetches are pending.
  * P6 (type ramp)          — PARTIAL. NOW completed for the audit's named targets:
                              stat-label / stat-desc / infographic card-subtitle
                              onto --text-xs / --text-md tokens.
"""
import os
from admin_view import admin_js_view
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


class TestR33P1CtaHierarchy(unittest.TestCase):
    def setUp(self):
        self.style = read("static/css/style.css")

    def test_btn_primary_is_solid_dark_green(self):
        idx = self.style.index(".btn-primary {")
        block = self.style[idx:idx + 300]
        self.assertIn("background: var(--primary-dark);", block)
        self.assertNotIn("linear-gradient", block,
                         "P1: btn-primary must be the SOLID tier, not a gradient")

    def test_btn_primary_hover_goes_lighter_solid(self):
        idx = self.style.index(".btn-primary:hover")
        block = self.style[idx:idx + 300]
        self.assertIn("background: var(--primary);", block)
        self.assertIn("filter: none;", block)

    def test_btn_accent_keeps_the_gradient(self):
        idx = self.style.index(".btn-accent {")
        block = self.style[idx:idx + 300]
        self.assertIn("background: var(--gradient-accent);", block)


class TestR33P3SkeletonFirstPaint(unittest.TestCase):
    def test_withskeleton_helper_ships(self):
        ui = read("static/js/ui.js")
        self.assertIn("window.withSkeleton", ui)
        self.assertIn('w.classList.add("ui-skeleton")', ui)
        self.assertIn('w.classList.remove("ui-skeleton")', ui)

    def test_admin_dashboard_tables_use_skeletons(self):
        html = admin_js_view()
        self.assertGreaterEqual(html.count("withSkeleton("), 2,
                                "dashboard + performance fetches must both shimmer")
        self.assertIn('document.getElementById("state-breakdown-tbody")', html)
        self.assertIn('document.getElementById("penetration-tbody")', html)
        self.assertIn("withSkeleton(tbody,", html)

    def test_skeleton_css_exists(self):
        ui = read("static/css/ui.css")
        self.assertIn(".ui-skeleton {", ui)


class TestR33P6TypeRamp(unittest.TestCase):
    def setUp(self):
        self.style = read("static/css/style.css")

    def test_tokens_defined(self):
        for token in ("--text-xs:", "--text-sm:", "--text-md:", "--text-lg:"):
            self.assertIn(token, self.style)

    def test_named_targets_on_tokens(self):
        self.assertIn(".stat-label { font-size: var(--text-xs);", self.style)
        self.assertIn(".stat-desc  { font-size: var(--text-md); }", self.style)
        self.assertIn(".infographic-card .card-subtitle { font-size: var(--text-md); }", self.style)


class TestR33AntiRegressionPolishP2P4P5(unittest.TestCase):
    """The already-deployed polish must stay deployed."""

    def setUp(self):
        self.style = read("static/css/style.css")

    def test_p2_elevation_and_motion_contract(self):
        self.assertIn("box-shadow: var(--shadow-xl), 0 0 0 1px rgba(255, 255, 255, 0.5);", self.style)
        self.assertIn("transition: background-color var(--transition-fast),", self.style)

    def test_p4_tablet_step(self):
        idx = self.style.index("Polish P4")
        self.assertIn("repeat(auto-fit, minmax(180px, 1fr))", self.style[idx:idx + 700])

    def test_p5_tabs_scroll_affordance(self):
        self.assertIn("Polish P5", self.style)
        self.assertIn(".tabs.ui-scroll-right", self.style)
        ui = read("static/js/ui.js")
        self.assertIn("ui-scroll-right", ui)


if __name__ == "__main__":
    unittest.main()
