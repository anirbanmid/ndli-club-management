"""
Round 60 -- CI job label honesty: never bake a pin count into a label.

The R59 workflow labeled its gate job "Full test gate (913 pins)" while the
measured gate was 932 -- the same disease class as the 69/68 measured-count
drift (R55/R57): a number copied into an artifact goes stale the moment the
tree moves. The honest home of the pin count is the run output ("Ran N
tests ... OK"), which is measured fresh on every run.

These pins make the fix permanent:
- the `gate` job's human name carries NO digits (a count cannot creep back);
- the label still names the contract ("Full test gate").

Run from the repo root:
    python3 -m unittest discover -s tests -p test_r60_ci_label.py
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")


def _gate_job_name(text):
    """Return the human name of the `gate` job (stdlib-only line parsing)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^  gate:\s*$", line):
            for follow in lines[i + 1:]:
                m = re.match(r"^    name:\s*(.+?)\s*$", follow)
                if m:
                    return m.group(1)
                # any other job-level key or a new job -> the name is absent
                if re.match(r"^  \S", follow) or re.match(r"^    \S", follow):
                    return None
    return None


class TestCiLabelHonesty(unittest.TestCase):
    """A comment/label that states a measured count is stale on arrival."""

    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), ".github/workflows/ci.yml must ship")
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.label = _gate_job_name(self.text)
        self.assertIsNotNone(self.label, "the gate job must carry a name")

    def test_gate_job_label_never_bakes_a_pin_count(self):
        self.assertNotRegex(
            self.label, r"\d",
            "gate job label must not bake a pin count: counts move every round "
            "(913 -> 932 -> ...); the measured count belongs to the run output")

    def test_gate_job_label_still_names_the_contract(self):
        self.assertTrue(
            self.label.startswith("Full test gate"),
            f"gate job label lost the contract name: {self.label!r}")


if __name__ == "__main__":
    unittest.main()
