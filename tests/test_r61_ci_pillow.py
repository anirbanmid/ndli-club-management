"""
Round 61 -- CI installs the test suite's one third-party dependency.

The R59 workflow shipped with "the app is stdlib-only: no pip install needed"
-- true for the APP, false for the TESTS: `tests/test_r52_app_icon.py`
imports PIL at module level (the R52/R53 icon pixel pins). On a clean CI
runner Pillow is absent -> the module dies at import -> unittest reports ONE
loader error and the 13 icon pins silently VANISH from the gate
(`Ran 922 tests`, `FAILED (errors=1)` -- both CI runs, 934-13+1 and 932-13+1).

R61 installs Pillow in the gate job and pins three things:
- the gate job installs Pillow;
- the install runs BEFORE the full-gate step;
- the icon pins keep their module-level PIL import -- a missing Pillow must
  stay a LOUD error, never a skip (a skipped pin is a vacuous gate).

Run from the repo root:
    python3 -m unittest discover -s tests -p test_r61_ci_pillow.py
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")
ICON_TEST = Path("tests/test_r52_app_icon.py")


def _gate_job_text(text):
    """Return the body of the `gate` job (stdlib-only line parsing)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^  gate:\s*$", line):
            body = []
            for follow in lines[i + 1:]:
                if re.match(r"^  \S", follow):
                    break
                body.append(follow)
            return "\n".join(body)
    return ""


class TestCiTestDeps(unittest.TestCase):
    """The gate must see ALL pins -- including the ones that need Pillow."""

    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), ".github/workflows/ci.yml must ship")
        self.gate = _gate_job_text(WORKFLOW.read_text(encoding="utf-8"))
        self.assertTrue(self.gate, "ci.yml must keep a gate job")

    def test_gate_job_installs_pillow(self):
        self.assertRegex(
            self.gate, r"pip install .*Pillow",
            "the gate job must install Pillow: tests/test_r52_app_icon.py "
            "imports PIL at module level; without it the icon pins vanish "
            "from the gate behind one loader error (922 != 934)")

    def test_pillow_install_precedes_the_full_gate(self):
        install = self.gate.find("pip install")
        gate_run = self.gate.find("unittest discover -s tests")
        self.assertNotEqual(install, -1, "no pip install step in the gate job")
        self.assertNotEqual(gate_run, -1, "no full-gate step in the gate job")
        self.assertLess(install, gate_run,
                        "Pillow must be installed BEFORE the suite runs")

    def test_icon_pins_never_silently_skip(self):
        src = ICON_TEST.read_text(encoding="utf-8")
        header = src.split("class ")[0]
        self.assertIn(
            "from PIL import Image", header,
            "the icon pins must keep a MODULE-LEVEL PIL import -- a missing "
            "Pillow must stay a loud loader error, never a skipTest")


if __name__ == "__main__":
    unittest.main()
