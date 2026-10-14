"""
tests/test_r52_app_icon.py

The app icon / favicon set.

History:
  * R52 shipped the "design D" set (open book + 3 arcs) from one 4096px
    supersample, made favicon.ico multi-frame (16/32/48) and locked the
    opaque apple-touch-icon rule.
  * R53 swapped the ART (user's order: apply Claude's icon package --
    deep-green field + white shield/book/figures line art) and wired the
    package's extras: android icons + site.webmanifest, msapplication tile.
    The cache stamp moved ?v=20261014d -> ?v=20261014e (art changed; the
    stamp is the only thing that beats a pinned browser favicon cache).

Pins:
  1. every shipped asset exists at its exact pixel size (and apple-touch is
     opaque RGB -- transparent corners render BLACK on iOS home screens);
  2. favicon.ico really carries the 16/32/48 frames;
  3. all four templates expose exactly the pinned icon surface (paths +
     cache stamps pinned; a stale unstamped URL must fail);
  4. the pixels are genuinely icon art: green field + white glyph mass with
     16px contrast (a swapped-in foreign icon must fail, not pass silently);
  5. the package extras: site.webmanifest parses, references the android
     icons with matching sizes + stamps, and the server serves .webmanifest
     with the manifest MIME type browsers require.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import json
import re
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
    "android-icon-72x72.png": (72, 72),
    "android-icon-96x96.png": (96, 96),
    "android-icon-144x144.png": (144, 144),
    "android-icon-192x192.png": (192, 192),
    "android-icon-512x512.png": (512, 512),
    "mstile-150x150.png": (150, 150),
    "mstile-310x310.png": (310, 310),
}

STAMP = "20261014e"

# The exact icon surface every template must expose (nothing more, nothing
# less): 3 favicon links + apple-touch + manifest + the Windows tile meta.
LINKS = [
    '<link rel="icon" type="image/x-icon" href="/static/favicon.ico?v=%s">' % STAMP,
    '<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32x32.png?v=%s">' % STAMP,
    '<link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16x16.png?v=%s">' % STAMP,
    '<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png?v=%s">' % STAMP,
    '<link rel="manifest" href="/static/site.webmanifest?v=%s">' % STAMP,
    '<meta name="msapplication-TileImage" content="/static/mstile-150x150.png?v=%s">' % STAMP,
]

# Any template line touching the icon family (the pin surface the stamp and
# no-drift checks walk).
ICON_LINE = re.compile(
    r"/static/(favicon|apple-touch-icon|android-icon|mstile|site\.webmanifest)"
)


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
    """The bytes must BE icon art: green field + white glyph mass."""

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
        # the glyph (shield + book + figures line art) is a white mass in
        # the center region -- measured 114 white px at 48px on the R53 art
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
        # icon-family URL must carry the R53 cache stamp ?v=20261014e so a
        # deploy visibly changes the tab icon. Bump the stamp when art
        # changes -- and follow this pin when it moves.
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            for line in src.splitlines():
                if ICON_LINE.search(line):
                    with self.subTest(template=tpl.name, line=line.strip()):
                        self.assertIn("?v=" + STAMP, line,
                                      "%s: icon URL missing the cache stamp" % tpl.name)

    def test_every_template_links_the_icon_assets(self):
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            for link in LINKS:
                with self.subTest(template=tpl.name, link=link):
                    self.assertIn(link, src,
                                  "%s must link %s" % (tpl.name, link))

    def test_no_foreign_icon_references(self):
        # exactly the pinned surface -- no second/old icon path may linger
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            hits = [l.strip() for l in src.splitlines() if ICON_LINE.search(l)]
            with self.subTest(template=tpl.name):
                self.assertEqual(sorted(hits), sorted(LINKS),
                                 "%s icon links drifted" % tpl.name)


class TestIconPackageExtras(unittest.TestCase):
    """R53: the android icons + site.webmanifest + Windows tile wiring."""

    def test_site_webmanifest_is_valid_and_complete(self):
        p = STATIC / "site.webmanifest"
        self.assertTrue(p.is_file(), "missing site.webmanifest")
        try:
            manifest = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            self.fail("site.webmanifest is not valid JSON: %s" % exc)
        self.assertEqual(manifest.get("name"), "NDLI Club Management")
        self.assertEqual(manifest.get("short_name"), "NDLI Club")
        self.assertEqual(manifest.get("start_url"), "/")
        self.assertEqual(manifest.get("display"), "standalone")
        self.assertEqual(manifest.get("theme_color"), "#103125")

        icons = manifest.get("icons", [])
        sizes = {i.get("sizes") for i in icons}
        self.assertEqual(sizes,
                         {"72x72", "96x96", "144x144", "192x192", "512x512"},
                         "manifest must declare the five android icon sizes")
        for icon in icons:
            src = icon.get("src", "")
            self.assertIn("?v=" + STAMP, src,
                          "manifest icon src must carry the cache stamp")
            file_part = src.split("?")[0]
            self.assertTrue((ROOT / file_part.lstrip("/")).is_file(),
                            "manifest icon %s does not exist on disk" % file_part)

    def test_webmanifest_served_with_manifest_mime(self):
        # browsers reject a manifest served as octet-stream; the static
        # handler must map .webmanifest -> application/manifest+json
        src = (ROOT / "routes" / "portals.py").read_text(encoding="utf-8")
        self.assertIn('.webmanifest"', src,
                      "routes/portals.py lost the .webmanifest MIME branch")
        self.assertIn('"application/manifest+json"', src,
                      "routes/portals.py lost the manifest MIME type")

    def test_manifest_link_and_tile_meta_stay_pinned(self):
        # both extra surface lines live in LINKS; this catches a template
        # that kept icons but silently dropped the manifest wiring
        for tpl in sorted((ROOT / "templates").glob("*.html")):
            src = tpl.read_text(encoding="utf-8")
            with self.subTest(template=tpl.name):
                self.assertIn('<link rel="manifest"', src,
                              "%s lost the manifest link" % tpl.name)
                self.assertIn('<meta name="msapplication-TileImage"', src,
                              "%s lost the tile meta" % tpl.name)


if __name__ == "__main__":
    unittest.main()
