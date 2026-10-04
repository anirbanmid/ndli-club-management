"""
tests/test_repo_hygiene.py

Guards for the repo-hygiene contract (fixed 2026-10-04 after the tracked-data
leak): runtime data/ NEVER in git, deploy-kit rollback scratch never committed,
dev tooling artifacts ignored, and the stale-clone coordination rules stay
documented. These tests read repository files only -- no git required.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class TestRepoHygiene(unittest.TestCase):

    def setUp(self):
        self.lines = [
            ln.strip() for ln in
            (BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
        ]

    def test_runtime_data_never_in_git(self):
        # data/ must be ignored wholesale: accounts+hashes, club contact emails
        # and the PI signature leaked through tracked data/ in 2026-09.
        self.assertIn("data/", self.lines,
                      "data/ must be ignored wholesale (leak fix 2026-10-04)")
        for secret in ("data/.seed_credentials.json", "data/.qr_signing_key"):
            self.assertIn(secret, self.lines, secret + " must stay gitignored")

    def test_deploy_kit_scratch_never_committed(self):
        self.assertIn("*.bak", self.lines, "rollback scratch must be ignored")
        self.assertIn("*.pre_*", self.lines, "kit backups must be ignored")

    def test_dev_artifacts_ignored(self):
        for art in ("*.code-workspace", "ndli_promo_video.mp4", "restore_stable_v2.bat"):
            self.assertIn(art, self.lines, art + " must stay ignored")

    def test_coordination_rules_documented(self):
        contrib = (BASE_DIR / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("git pull", contrib, "stale-clone rule must stay documented")
        self.assertRegex(contrib.lower(), r"never.{0,24}git add -a",
                         "the never-git-add-A rule must stay documented")
        agents = (BASE_DIR / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("git pull", agents, "AGENTS.md must carry the pull-first rule")


if __name__ == "__main__":
    unittest.main()
