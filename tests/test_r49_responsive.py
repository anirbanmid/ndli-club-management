"""
R49 - small-display responsiveness (entry screens + employee portal).

The user reported the app "has issues in dynamic adjustment in smaller
displays" (laptop + mobile) while large monitors looked good. Vision analysis
of 390px + 1366px screenshots catalogued the breakage; this file pins the
structural fixes so they cannot silently regress:

  * root cause: the app-topbar flex row could not shrink below ~420px -> the
    PAGE overflowed horizontally at 390px and clipped tab titles, the date
    chip and the avatar on the right edge. It now WRAPS.
  * the captcha row on the cover page squeezed the input until its placeholder
    clipped ("ENTER C|"); it now wraps and the input grows to its own line.
  * the 7-officer grid was a fixed 4-col grid -> lopsided half-empty last row
    and cramped phone gutters; it is now a flex wrap whose rows stretch.
  * laptop widths: the sign-in card floated in dead space (600px), the
    password Show toggle was jammed against the input edge, helper text was
    crowded, the directory header row could not wrap, sidebar sections had
    uneven rhythm.
  * the fixed assistant FAB could pin the footer link under it on phones.

Static source pins. No server, no data. Desktop (>1400px) is the user's good
baseline and must stay untouched -- pinned as guard rails below.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def media_block(text, query):
    """Return the body of the FIRST @media block matching `query`, braces counted."""
    marker = "@media (%s) {" % query
    start = text.find(marker)
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


CSS = "static/css/style.css"
INDEX = "templates/index.html"
EMP = "templates/employee.html"
TMPL_FILES = ["templates/admin.html", "templates/employee.html",
              "templates/index.html", "templates/verify.html"]


class TestTopbarNoLongerOverflows(unittest.TestCase):
    """Root cause of the mobile clipping: the topbar could not shrink."""

    def test_topbar_wraps_at_mobile(self):
        blk = media_block(read(CSS), "max-width: 520px")
        self.assertIn(".app-topbar", blk, "no mobile topbar rule")
        self.assertIn("flex-wrap: wrap", blk, "topbar must wrap, not overflow")
        self.assertIn("height: auto", blk, "topbar height must be free when wrapped")

    def test_search_shrinks_instead_of_pushing_the_row(self):
        text = read(CSS)
        blk980 = media_block(text, "max-width: 980px")
        blk520 = media_block(text, "max-width: 520px")
        self.assertIn("min-width: 0", blk980, "app-search must be allowed to shrink at <=980px")
        self.assertIn(".app-search { flex: 1 1 100%; min-width: 0; }", blk520,
                      "at mobile the search takes its own full row")
        self.assertIn(".app-search .kbd { display: none; }", blk520,
                      "keyboard hint is desktop-only")

    def test_top_right_cluster_wraps_too(self):
        blk = media_block(read(CSS), "max-width: 520px")
        self.assertIn(".top-right { flex-wrap: wrap;", blk)

    def test_fab_never_pins_the_footer_link(self):
        blk = media_block(read(CSS), "max-width: 520px")
        self.assertRegex(blk, r"\.system-footer\s*\{[^}]*padding-bottom:\s*4\.5rem",
                         "footer needs bottom clearance from the fixed FAB")


class TestCaptchaRowWraps(unittest.TestCase):
    """The cover-page captcha row squeezed the input into truncation."""

    def test_captcha_container_wraps_at_mobile(self):
        blk = media_block(read(INDEX), "max-width: 520px")
        self.assertIn(".captcha-container", blk)
        self.assertIn("flex-wrap: wrap", blk)
        self.assertIn("#lock-captcha-canvas", blk)
        self.assertIn("flex: 0 0 auto", blk, "the canvas must keep its size")
        self.assertRegex(blk, r"\.captcha-container \.lock-input\s*\{[^}]*flex: 1 1 100%",
                         "the input grows to its own line when the row wraps")

    def test_lock_footer_is_readable_on_phones(self):
        blk = media_block(read(INDEX), "max-width: 520px")
        m = re.search(r"\.lock-footer-info\s*\{[^}]*font-size:\s*([0-9.]+)rem", blk)
        self.assertIsNotNone(m, "mobile rule for .lock-footer-info missing")
        self.assertGreaterEqual(float(m.group(1)), 0.78,
                                "footer disclaimer too small on phones")


class TestOfficerGridFillsEvenly(unittest.TestCase):
    """7 officers in a fixed 4-col grid = lopsided rows and cramped gutters."""

    def test_grid_is_a_flex_wrap(self):
        text = read(EMP)
        m = re.search(r"\.officer-chip-grid\s*\{[^}]*\}", text, re.S)
        self.assertIsNotNone(m, ".officer-chip-grid rule missing")
        body = m.group(0)
        self.assertIn("display: flex", body)
        self.assertIn("flex-wrap: wrap", body)
        self.assertNotIn("grid-template-columns", body,
                         "the fixed column grid is what made rows lopsided")

    def test_chips_stretch_so_the_last_row_is_never_half_empty(self):
        m = re.search(r"\.officer-chip\s*\{[^}]*flex:\s*1 1 130px[^}]*\}", read(EMP), re.S)
        self.assertIsNotNone(m, "chips must flex-grow (flex: 1 1 130px)")

    def test_chip_gutter_is_not_cramped(self):
        m = re.search(r"\.officer-chip-grid\s*\{[^}]*gap:\s*([0-9.]+)rem", read(EMP), re.S)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(float(m.group(1)), 0.5, "gutter below 0.5rem")


class TestLaptopPositioning(unittest.TestCase):
    """1366px: dead-space card, cramped toggle, crowded helper, rigid rows."""

    def test_signin_column_widens_at_laptop_widths(self):
        m = re.search(r"\.login-wrapper\s*\{[^}]*max-width:\s*(\d+)px[^}]*margin:\s*[^;]*auto",
                      read(EMP), re.S)
        self.assertIsNotNone(m, ".login-wrapper must be capped and centred")
        self.assertGreaterEqual(int(m.group(1)), 720,
                                "600px floated in dead space at laptop widths")

    def test_password_toggle_has_breathing_room(self):
        text = read(EMP)
        m = re.search(r"\.password-toggle-btn\s*\{[^}]*right:\s*(\d+)px[^}]*padding:\s*([0-9.]+)rem\s+([0-9.]+)rem",
                      text, re.S)
        self.assertIsNotNone(m, ".password-toggle-btn rule incomplete")
        self.assertGreaterEqual(int(m.group(1)), 6, "toggle jammed against the input edge")
        self.assertGreaterEqual(float(m.group(2)), 0.25)
        self.assertGreaterEqual(float(m.group(3)), 0.55)
        self.assertIn('style="padding-right: 4.7rem;"', text,
                      "login password input keeps room for the toggle")

    def test_helper_text_is_not_crowded(self):
        m = re.search(r'<p style="font-size: 0\.68rem;[^"]*margin-top:\s*([0-9.]+)rem[^"]*line-height:\s*([0-9.]+);?"',
                      read(EMP))
        self.assertIsNotNone(m, "employee-id helper text style not found")
        self.assertGreaterEqual(float(m.group(1)), 0.3, "helper text crowded against its input")
        self.assertGreaterEqual(float(m.group(2)), 1.3)

    def test_directory_header_row_can_wrap(self):
        text = read(EMP)
        i = text.find("7 Nodal Officers Directory (Click to select):")
        self.assertGreater(i, 0, "directory header text moved")
        row = text.rfind('style="display: flex', 0, i)
        seg = text[row:i]
        self.assertIn("flex-wrap: wrap", seg, "the header row must wrap on narrow cards")

    def test_sidebar_section_rhythm_is_uniform(self):
        m = re.search(r"\.side-caption\s*\{[^}]*padding:\s*([0-9]+)px\s+([0-9]+)px\s+([0-9]+)px",
                      read(CSS), re.S)
        self.assertIsNotNone(m, ".side-caption padding not found")
        self.assertEqual([int(g) for g in m.groups()], [14, 14, 7],
                         "section rhythm drifted (want 14px 14px 7px)")


class TestCacheStamp(unittest.TestCase):
    def test_stylesheet_links_carry_the_r49_stamp(self):
        # Pin-follow (R50): the stamp literal moves forward with every style.css
        # change (R50 bumped it d -> f); the invariant is "a stamp is present".
        for rel in TMPL_FILES:
            for m in re.finditer(r'<link rel="stylesheet" href="([^"]+)"', read(rel)):
                self.assertIn("?v=20261013g", m.group(1),
                              "%s: stylesheet link missing the R50 stamp: %s" % (rel, m.group(1)))


class TestDesktopUntouched(unittest.TestCase):
    """Guard rails: the user LIKES the >1400px layout. Do not 'fix' it."""

    def test_shell_geometry_unchanged(self):
        text = read(CSS)
        self.assertIn(".app-sidebar {\n  width: 252px;\n  flex: 0 0 252px;", text)
        self.assertIn(".app-topbar {\n  height: 70px; flex: 0 0 70px;", text)

    def test_r48_anti_tells_did_not_come_back(self):
        text = read(CSS) + read(INDEX) + read(EMP)
        self.assertNotIn("background-clip: text", text)
        self.assertNotIn("backdrop-filter", text)


if __name__ == "__main__":
    unittest.main()
