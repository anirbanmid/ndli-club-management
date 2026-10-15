"""
tests/test_r57_static_counter.py

R57 pins -- "static-counter hardening" (2026-10-15).

R55v2 made the measured counts junk-proof (backups/caches/droppings never
count). R57 closes the OTHER half of the drift class: GITIGNORED HOST
ARTIFACTS. A clean clone never contains a gitignored file, so a counter that
counts them measures 69 on a deployed tree and 68 on every clean clone --
exactly the 2026-10-15 `static/ndli_promo_video.mp4` incident (PA measured 69,
the PC clean clone 68, drift gate red on clean checkouts until the artifact
was archived by hand).

The contract these pins lock:

  * measured counts == what a clean checkout would count: a gitignored
    artifact dropped into a measured dir never moves a count;
  * real tree content still counts (the skip is not vacuous);
  * `.gitignore` is the source of truth -- its pinned entries are guarded by
    tests/test_repo_hygiene.py, so a new artifact is fixed for every tree the
    moment it is gitignored.

No HTTP server. Pure structural checks over the counter.
"""
import _seed_env  # noqa: F401  (test-env convention; keeps discovery uniform)
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import gen_api_docs  # noqa: E402


class TestGitignorePatterns(unittest.TestCase):
    def test_patterns_load_and_skip_noise(self):
        pats = gen_api_docs._gitignore_patterns()
        self.assertIn(("ndli_promo_video.mp4",), pats,
                      "the pinned dev artifact must drive the counter")
        self.assertIn(("*.zip",), pats)
        self.assertIn(("data",), pats, 'the "data/" dir pattern must parse')
        self.assertIn(("data", "backups", "backup_*"), pats)
        self.assertFalse(any(p[0].startswith("#") for p in pats),
                         "comment lines must never become patterns")
        self.assertFalse(any(p[0].startswith("!") for p in pats),
                         "negation lines are out of scope (documented)")

    def test_artifact_names_are_recognized(self):
        artifacts = [
            "static/ndli_promo_video.mp4",   # the 2026-10-15 incident, verbatim
            "static/r19_shell.zip",          # generic *.zip artifact
            "data/sessions.json",            # under a gitignored dir
            "data/backups/backup_1/admin/x.csv",  # deep under a gitignored dir
            "restore_stable_v2.bat",
            "x.code-workspace",
            "style.css.pre_r20.png",         # matches *.pre_* -> ignored by git
        ]
        for rel in artifacts:
            with self.subTest(rel=rel):
                self.assertTrue(gen_api_docs._is_host_artifact(Path(rel)))

    def test_real_tree_content_is_not_an_artifact(self):
        clean = [
            "static/style.css",
            "static/js/admin.js",
            "static/NDLI_Club_Management_User_Manual.pdf",
            "tests/test_r57_static_counter.py",
            "docs/technical_manual.html",
        ]
        for rel in clean:
            with self.subTest(rel=rel):
                self.assertFalse(gen_api_docs._is_host_artifact(Path(rel)))


class TestCountsMatchCleanClone(unittest.TestCase):
    def test_planted_artifact_never_moves_counts(self):
        """The incident as a regression: video + zip in static/ -> count unchanged."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "static").mkdir()
            (root / "static" / "a.css").write_text("x")
            (root / "static" / "b.js").write_text("x")
            base = gen_api_docs._file_count("static", root=root)
            self.assertEqual(base, 2)
            (root / "static" / "ndli_promo_video.mp4").write_text("vid")
            (root / "static" / "promo_copy.zip").write_text("z")
            self.assertEqual(gen_api_docs._file_count("static", root=root), base,
                             "gitignored host artifacts must never move a count")
            self.assertEqual(gen_api_docs._file_count("static", "**/*.js", root=root), 1)

    def test_skip_is_not_vacuous(self):
        """Real content planted AFTER the artifact still counts (rule is a skip,
        not a breakage)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "static").mkdir()
            (root / "static" / "ndli_promo_video.mp4").write_text("vid")
            self.assertEqual(gen_api_docs._file_count("static", root=root), 0)
            (root / "static" / "c.png").write_text("x")
            (root / "static" / "d.css").write_text("x")
            self.assertEqual(gen_api_docs._file_count("static", root=root), 2,
                             "real files must still be counted beside artifacts")


if __name__ == "__main__":
    unittest.main()
