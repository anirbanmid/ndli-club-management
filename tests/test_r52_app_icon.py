"""
tests/test_r52_app_icon.py

R52 Part B -- the app icon / favicon set (user picked design D: open book +
3 signal arcs, brand-continuity successor of the old book+sparkle icon).

What changed vs the old set:
  * every asset re-rendered from the same 4096px supersample (crisp at 16px);
  * favicon.ico is now MULTI-FRAME (16/32/48) -- before R52 it was a
    single-frame 16px file, so a 32px request got an upscaled blur;
  * apple-touch-icon.png is opaque RGB (iOS applies its own mask; transparent
    corners would render BLACK on the home screen).

Pins:
  1. the five assets exist at their exact pixel sizes / modes;
  2. favicon.ico really carries the 16/32/48 frames;
  3. all four templates still link exactly these assets (paths pinned);
  4. the pixels are the D design: green background, white glyph mass present
    (a swapped-in foreign icon must fail, not pass silently).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

ASSETS = {
    "favicon-16x16.png": (16, 16),
    "favicon-32x32.png": (32, 32),
    "favicon-48x48.png": (48, 48),
    "apple-touch-icon.png": (180, 180),
}

LINKS = [
    '<link rel="icon" type="image/x-icon" href="/static/favicon.ico?v=20261014d">',
    '<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=20261014d">',
    '<link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png?v=20261014d">',
    '<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png?v=20261014d">',
]


class TestIconAssets(unittest.TestCase):

    def test_png_assets_exist_at_exact_sizes(self):
        for name, size in ASSETS.items():
            with self.subTest(asset=name):
                p = STATIC / name
                self.assertTrue(p.is_file(), "missing %s" % name)
                im = Image.open(p)
                self.assertEqual(im.size, size, "%s must be %sx%s" % (name, *size))

    def test_apple_touch_icon_is_opaque_rgb(self):
        # iOS masks the icon itself: RGBA transparent corners render BLACK
        im = Image.open(STATIC / "apple-touch-icon.png")
        self.assertEqual(im.mode, "RGB",
                         "apple-touch-icon must be opaque RGB (transparent "
                         "corners go black on iOS home screens)")

    def test_favicon_ico_carries_three_frames(self):
        p = STATIC / "favicon.ico"
        self.assertTrue(p.is_file(), "missing favicon.ico")
        im = Image.open(p)
        self.assertEqual(im.info.get("sizes"),
                         {(16, 16), (32, 32), (48, 48)},
                         "favicon.ico must carry 16/32/48 frames (a "
                         "single-frame ico upscales to blur at 32px)")

    def test_ico_declares_image_x_icon_type(self):
        # format sanity: the file PIL wrote is really an ICO
        im = Image.open(STATIC / "favicon.ico")
        self.assertEqual(im.format, "ICO")


class TestIconPixels(unittest.TestCase):
    """The bytes must BE the D design: green field + white glyph mass."""

    def _sample(self, name):
        im = Image.open(STATIC / name).convert("RGB")
        px = im.load()
        w, h = im.size
        return im, px, w, h

    def test_background_is_brand_green(self):
        # corner pixel (inside the squircle at 48px+) must be green-dominant
        im, px, w, h = self._sample("favicon-48x48.png")
        r, g, b = px[3, 3]
        self.assertGreater(g, r, "background must be green-dominant")
        self.assertGreater(g, b, "background must be green-dominant")

    def test_white_glyph_mass_present(self):
        # the book+arcs glyph is a solid white mass in the center region
        im, px, w, h = self._sample("favicon-48x48.png")
        white = 0
        for y in range(12, 36):
            for x in range(12, 36):
                r, g, b = px[x, y]
                if r > 225 and g > 225 and b > 225:
                    white += 1
        self.assertGreater(white, 60,
                           "expected a substantial white glyph mass in the "
                           "center (got %d white px)" % white)

    def test_small_size_keeps_contrast(self):
        # 16px must still separate glyph from background (no muddy single blob)
        im, px, w, h = self._sample("favicon-16x16.png")
        vals = set()
        for y in range(2, 14):
            for x in range(2, 14):
                r, g, b = px[x, y]
                vals.add(r > 200 and g > 200 and b > 200)
        self.assertIn(True, vals, "16px icon lost the white glyph")
        self.assertIn(False, vals, "16px icon lost the green background")


class TestTemplateLinks(unittest.TestCase):

    def test_icon_links_carry_a_cache_stamp(self):
        # browsers pin favicons HARD (even hard-refresh keeps them): every
        # icon URL must carry the R52 cache stamp ?v=20261014d so a deploy
        # visibly changes the tab icon. Bump the stamp when the art changes.
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            for line in src.splitlines():
                if ("favicon" in line or "apple-touch-icon" in line) and "href=" in line:
                    with self.subTest(template=tpl.name, line=line.strip()):
                        self.assertIn("?v=20261014d", line,
                                      "%s: icon URL missing cache stamp" % tpl.name)

    def test_every_template_links_the_icon_assets(self):
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            for link in LINKS:
                with self.subTest(template=tpl.name, link=link):
                    self.assertIn(link, src,
                                  "%s must link %s" % (tpl.name, link))

    def test_no_foreign_icon_references(self):
        # exactly the four link lines -- no second/old icon path may linger
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            hits = [l.strip() for l in src.splitlines()
                    if 'rel="icon"' in l or "rel='icon'" in l
                    or "apple-touch-icon" in l]
            with self.subTest(template=tpl.name):
                self.assertEqual(sorted(hits), sorted(LINKS),
                                 "%s icon links drifted" % tpl.name)


if __name__ == "__main__":
    unittest.main()
