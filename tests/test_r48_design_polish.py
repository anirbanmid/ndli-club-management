"""
R48 - design polish: remove the "AI-uniform" visual tells.

The 8.5/10 critique (2026-10-13) named four tells of generic AI-generated
UI: gradient text, glassmorphism, decorative glow shadows, and monospace
overload. R48 removes them with taste rather than a chainsaw:

  * gradient text  -> solid ink (the brand green/amber stays as solid color);
  * glassmorphism  -> solid surfaces (blur panels were translucency theater);
  * glow shadows   -> elevation or focus RINGS (rings are functional and
                      stay: `0 0 0 <spread>px`; a glow is `0 0 <blur>px`);
  * monospace      -> only for MACHINE tokens (ids, captchas, clocks, code,
                      tabular data cells). Human data (stat-card values,
                      date inputs, spec prose) is sans + tabular-nums.

Static source pins. No server, no data.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CSS_FILES = ["static/css/style.css", "static/css/ui.css", "static/css/assistant.css"]
TMPL_FILES = ["templates/admin.html", "templates/employee.html",
              "templates/index.html", "templates/verify.html"]
JS_FILES = ["static/js/admin_club_details.js", "static/js/employee_activity_delete.js"]

# a shadow "term" is glow-shaped when it is `0 0 <blur>px` with blur > 0.
# Splitting terms on commas is safe: rgba() fragments are too short to fake it.
GLOW_TERM = re.compile(r"\s*(?:inset\s+)?0 0 ([1-9][0-9]*)px\s")
SHADOW_PROP = re.compile(r"((?:box|text)-shadow)\s*:\s*([^;]+)")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def all_texts():
    return {rel: read(rel) for rel in CSS_FILES + TMPL_FILES + JS_FILES}


def glow_hits():
    hits = []
    for rel, text in all_texts().items():
        for m in SHADOW_PROP.finditer(text):
            for piece in m.group(2).split(","):
                g = GLOW_TERM.match(piece)
                if g:
                    hits.append((rel, m.group(1), piece.strip()))
    return hits


class TestNoGradientText(unittest.TestCase):
    """Gradient text was tell #1 -- no background-clip:text may come back."""

    def test_no_background_clip_text_anywhere(self):
        for rel, text in all_texts().items():
            self.assertNotIn("background-clip: text", text, rel)
            self.assertNotIn("-webkit-background-clip: text", text, rel)

    def test_no_transparent_text_fill_anywhere(self):
        for rel, text in all_texts().items():
            self.assertNotIn("-webkit-text-fill-color: transparent", text, rel)


class TestNoGlass(unittest.TestCase):
    """Glassmorphism was tell #2 -- surfaces are solid now."""

    def test_no_backdrop_filter_anywhere(self):
        for rel, text in all_texts().items():
            self.assertNotIn("backdrop-filter", text, rel)

    def test_surfaces_stay_solid(self):
        # the navbar token that used to be translucent glass must be opaque
        self.assertIn("--surface-glass:  #FFFFFF;", read("static/css/style.css"))


class TestNoGlow(unittest.TestCase):
    """Tell #3: decorative glows. Focus/pulse RINGS (`0 0 0 <spread>px`) are
    functional and stay -- the matcher distinguishes them term-by-term."""

    def test_zero_glow_shaped_shadow_terms(self):
        hits = glow_hits()
        self.assertEqual(hits, [], "glow shadow terms found: %s" % hits[:5])

    def test_rings_are_still_present(self):
        # the guard-rail pair of the test above: rings must NOT be removed
        text = read("static/css/style.css")
        self.assertIn("0 0 0 3px rgba(13, 119, 81, 0.18)", text,
                      "focus rings are functional -- do not chainsaw them out")


class TestMonoIsForMachineTokens(unittest.TestCase):
    """Tell #4: monospace overload. Mono is reserved for machine tokens
    (ids, captchas, clocks, code); human data is sans + tabular-nums."""

    def test_date_inputs_are_never_monospace(self):
        for rel, text in all_texts().items():
            for m in re.finditer(r"<input[^>]*type=\"date\"[^>]*>", text):
                self.assertNotIn("monospace", m.group(0),
                                 "%s: date input carries mono: %s" % (rel, m.group(0)[:80]))

    def test_stat_card_values_are_never_monospace(self):
        html = read("templates/employee.html")
        # the DATE value cards swapped to sans + tabular-nums -- machine-token
        # ids (cert-display-reg-no, sec-confirm-ids) deliberately keep mono.
        for m in re.finditer(r"<strong[^>]*>", html):
            tag = m.group(0)
            if re.search(r'id="(modal-|cert-display-(doa|renewal))', tag):
                self.assertNotIn("monospace", tag,
                                 "stat-card value still mono: %s" % tag[:90])

    def test_machine_tokens_keep_their_mono(self):
        html = read("templates/employee.html")
        # club/reg ids + captcha + the delete target list are machine tokens
        self.assertRegex(html, r'<[^>]*monospace[^>]*id="sec-confirm-ids"')
        self.assertRegex(html, r'<[^>]*id="cert-display-reg-no"[^>]*monospace')
        self.assertRegex(html, r'<input[^>]*captcha[^>]*monospace')

    def test_human_data_got_tabular_nums_instead(self):
        html = read("templates/employee.html")
        self.assertIn("font-variant-numeric: tabular-nums", html,
                      "the mono->sans swaps must keep digit alignment")


class TestStylesheetsAreCacheBusted(unittest.TestCase):
    """R48 touches CSS that was linked WITHOUT any cache stamp -- a deploy
    could silently serve stale CSS. Every stylesheet link must carry ?v=."""

    def test_every_stylesheet_link_has_a_cache_stamp(self):
        for rel in TMPL_FILES:
            for m in re.finditer(r'<link rel="stylesheet" href="([^"]+)"', read(rel)):
                self.assertIn("?v=", m.group(1),
                              "%s: stylesheet link without cache stamp: %s" % (rel, m.group(1)))


if __name__ == "__main__":
    unittest.main()
