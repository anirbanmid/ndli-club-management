"""
tests/test_r54_cert_print.py

R54 -- certificate print hardening (the app's most fragile feature).

What the round fixes (root causes, measured in code):
  * The on-page print route MOVED the live canvas into a print root and
    restored it from an `afterprint` handler with a 1.5s fallback timer.
    On browsers whose window.print() returns before the dialog closes
    (async print), that timer could rip the print root out WHILE the preview
    was open -> clipped/blank certificates and a displaced canvas.
  * The popup fallback printed from the image's onload and closed the window
    immediately after: the click's user activation was gone (print silently
    ignored) and the auto-close raced the print job.

The fixes: the on-page route now pixel-CLONES the canvas into a print-only
element (the live canvas never moves) and cleans up on afterprint + the print
media query + a 30s guard; the popup fallback is now button-triggered inside
the popup (fresh activation, no auto-close) and popup-blockers get an honest
pointer to Download PDF.

Pins (source-structure locks on the engine + the employee caller):
  1. the onload/auto-close race pattern is GONE and can never come back;
  2. the clone approach (no DOM relocation of the live canvas);
  3. cleanup listens to afterprint + matchMedia("print"); guard is 30s;
  4. the popup fallback is button-triggered with an honest blocked-popup path;
  5. the R3 #16a contract (synchronous on-page route + A4 print CSS) holds.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
from pathlib import Path

from admin_view import employee_js_view

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class TestPrintRacesRemoved(unittest.TestCase):
    """The two known races must be gone -- a swapped-in old engine fails."""

    @classmethod
    def setUpClass(cls):
        cls.engine = read("static/js/certificate_engine.js")

    def test_no_onload_print_autoclose_race(self):
        # the popup used to print from img.onload and close itself at once
        self.assertNotIn('onload="window.print()', self.engine,
                         "popup prints from img.onload again (activation race)")
        self.assertNotIn("window.print(); window.close();", self.engine,
                         "auto-close after print() races/cancels the print job")

    def test_no_stale_1500ms_cleanup_timer(self):
        self.assertNotIn("setTimeout(cleanup, 1500)", self.engine,
                         "1.5s cleanup timer can rip the print root out while "
                         "the dialog is still open (async-print browsers)")

    def test_no_live_canvas_relocation(self):
        # the old route moved the original canvas into the print root and
        # restored it later; the clone route never touches the live DOM node
        self.assertNotIn("root.appendChild(canvas)", self.engine,
                         "live canvas is being relocated again")
        self.assertNotIn("insertBefore(canvas", self.engine,
                         "canvas restore dance is back")


class TestPrintHardenedRoutes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = read("static/js/certificate_engine.js")

    def test_onpage_route_clones_pixels(self):
        self.assertIn("drawImage(canvas, 0, 0)", self.engine,
                      "on-page route must pixel-clone, not relocate")
        self.assertIn("root.appendChild(printCanvas)", self.engine)

    def test_cleanup_uses_afterprint_and_print_media(self):
        self.assertIn('addEventListener("afterprint", cleanup)', self.engine)
        self.assertIn('matchMedia("print")', self.engine,
                      "print media query listener is the async-print cleanup path")
        self.assertIn("setTimeout(cleanup, 30000)", self.engine,
                      "long guard timer must stay (webviews where neither "
                      "afterprint nor the media query fires)")

    def test_popup_fallback_is_button_triggered(self):
        # a click INSIDE the popup = fresh activation -> window.print() cannot
        # be silently ignored, and nothing closes under the dialog
        self.assertIn('<button onclick="window.print()">Print Certificate</button>',
                      self.engine)
        self.assertIn("use the Download PDF button instead", self.engine,
                      "blocked popups must point at the download path")

    def test_print_css_contract(self):
        self.assertIn("@media print", self.engine)
        self.assertIn("size: A4 portrait", self.engine)
        self.assertIn("certificate-print-style", self.engine)
        self.assertIn("body.printing-certificate > *:not(", self.engine)

    def test_print_box_is_pinned_to_one_sheet(self):
        # the 2-sheet spill (user smoke 2026-10-15): site body has
        # min-height:100vh + flex column, and the print canvas is inline-level
        # (line-height adds a gap below it). The print box must neutralize
        # both or a blank sheet 2 reappears.
        self.assertIn("    display: block !important;", self.engine,
                      "print canvas rule must be block-level (inline line-box "
                      "gap pushes a blank sheet)")
        self.assertIn("min-height: 0 !important", self.engine,
                      "site body min-height:100vh must be neutralized in print")
        self.assertIn("overflow: hidden !important", self.engine)
        self.assertIn("position: absolute", self.engine,
                      "print root must leave the flow (cannot push page 2)")


class TestR3ContractStillHeld(unittest.TestCase):
    """R3 #16a anti-regression: synchronous on-page route stays first."""

    def test_onpage_export_and_synchronous_call(self):
        engine = read("static/js/certificate_engine.js")
        self.assertIn("function printCertificateOnPage(canvas)", engine)
        self.assertIn("printCertificateOnPage: printCertificateOnPage", engine)
        self.assertIn("printCertificate: printCertificate", engine)
        emp = employee_js_view()
        self.assertIn("CertificateEngine.printCertificateOnPage(c)", emp,
                      "the click handler must call the on-page route synchronously")
        self.assertIn("function printActiveCertificate()", emp)


if __name__ == "__main__":
    unittest.main()
