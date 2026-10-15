"""
Round 59 -- the "tiny CI" (gate + md5 kit build) as a permanent contract.

What the critique asked for: "Deploy is manual by design (paste scripts,
click-paths). Fine for one operator, fragile for two -- a tiny CI (gate + md5
kit build) would remove the last human steps." R59 ships:

1. `.github/workflows/ci.yml` -- every push/PR runs the drift gate + the FULL
   test gate on a clean checkout, and the latest kit manifest is rebuilt +
   md5-verified (the uploadable kit is reproducible from a clean clone).
2. `tools/build_kit.py` -- the generic manifest-driven kit builder (the
   R36+ installer convention, generated from tools/kits/*.json).
3. `tools/kits/*.json` -- round manifests (R58's shipped first: its kit is
   now rebuildable from any clean clone).

These pins lock the CI invariants that must never drift:
- ALWAYS `discover -s tests` (bare `discover` = the 199x-401 auth trap,
  hit three times on 2026-10-15).
- CI never commits/pushes back and never runs `git add -A`.
- the builder is stdlib-only and refuses dishonest manifests loudly.

Run from the repo root:
    python3 -m unittest discover -s tests
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")
BUILDER = Path("tools/build_kit.py")
KITS_DIR = Path("tools/kits")

# The three commands the CI contract pins (verbatim, in order).
CI_DRIFT_CMD = "python3 gen_api_docs.py --check"
CI_GATE_CMD = "python3 -m unittest discover -s tests"
CI_KIT_CMD = "python3 tools/build_kit.py --latest --verify-only"

REQUIRED_MANIFEST_FIELDS = (
    "round", "name", "title", "intro", "payload", "replaced", "markers",
    "py_compiles", "js_checks", "test_runs", "commit_files", "commit_message",
)

# tools/build_kit.py may import NOTHING outside this stdlib set.
BUILDER_IMPORT_WHITELIST = {
    "argparse", "hashlib", "json", "os", "pathlib", "py_compile", "shutil",
    "sys", "tempfile", "zipfile",
}


def _run_builder(args):
    return subprocess.run([sys.executable, str(BUILDER)] + args,
                          capture_output=True, text=True)


class TestWorkflowContract(unittest.TestCase):
    """The GitHub Actions workflow is the deploy gate -- its commands are pins."""

    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), ".github/workflows/ci.yml must ship")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_ci_runs_the_three_pinned_commands(self):
        for cmd in (CI_DRIFT_CMD, CI_GATE_CMD, CI_KIT_CMD):
            self.assertIn(cmd, self.text, f"CI lost the command: {cmd}")

    def test_gate_always_discover_s_tests(self):
        # The bare `unittest discover` trap: ai/ imports config before
        # tests/__init__ seeds _seed_env -> every auth-dependent test 401s.
        for line in self.text.splitlines():
            if "unittest discover" in line:
                self.assertIn("-s tests", line,
                              f"every discover invocation needs -s tests: {line!r}")

    def test_drift_gate_runs_before_the_suite(self):
        self.assertLess(self.text.index(CI_DRIFT_CMD), self.text.index(CI_GATE_CMD),
                        "stale measured docs must fail FAST, before the 5-minute suite")

    def test_ci_never_writes_back_to_the_repo(self):
        # Command lines only -- the header comments may NAME the forbidden
        # commands while explaining the rule.
        command_lines = [ln for ln in self.text.splitlines()
                         if not ln.lstrip().startswith("#")]
        body = "\n".join(command_lines)
        for forbidden in ("git push", "git commit", "git add"):
            self.assertNotIn(forbidden, body,
                             f"CI must never run {forbidden!r} (deploy commits stay human)")
        self.assertIn("contents: read", self.text, "CI needs read-only repo permissions")

    def test_triggers_are_narrow(self):
        # push/PR against main + manual dispatch. No schedule, no other branches.
        self.assertIn("workflow_dispatch:", self.text)
        self.assertRegex(self.text, r"pull_request:\s*\n\s*branches: \[main\]")
        self.assertRegex(self.text, r"push:\s*\n\s*branches: \[main\]")
        self.assertNotIn("schedule:", self.text, "no cron burn on Actions minutes")

    def test_gate_job_has_a_timeout(self):
        self.assertIn("timeout-minutes:", self.text, "a hung suite must not burn 6h")


class TestBuilderContract(unittest.TestCase):
    """tools/build_kit.py: stdlib-only, honest-fail, R36+ installer convention."""

    def test_builder_is_stdlib_only(self):
        tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported <= BUILDER_IMPORT_WHITELIST,
                        f"builder imported non-whitelisted modules: {imported - BUILDER_IMPORT_WHITELIST}")

    def test_manifests_declare_the_full_schema(self):
        manifests = sorted(KITS_DIR.glob("*.json"))
        self.assertTrue(manifests, "tools/kits/ must ship at least one manifest")
        for path in manifests:
            with self.subTest(manifest=path.name):
                m = json.loads(path.read_text(encoding="utf-8"))
                for field in REQUIRED_MANIFEST_FIELDS:
                    self.assertIn(field, m, f"{path.name} missing field {field!r}")
                self.assertTrue(m["payload"], f"{path.name}: empty payload")
                self.assertEqual(len(m["payload"]), len(set(m["payload"])))
                for rel in m["payload"]:
                    self.assertTrue(Path(rel).is_file(),
                                    f"{path.name}: payload not in tree: {rel}")
                self.assertTrue(set(m["replaced"]) <= set(m["payload"]),
                                f"{path.name}: replaced must be a subset of payload")
                for entry in m["markers"]:
                    self.assertEqual(len(entry), 3)
                    self.assertIn(entry[0], m["payload"],
                                  f"{path.name}: marker file not in payload: {entry[0]}")
                    self.assertTrue(entry[1], f"{path.name}: empty marker needle")
                for rel in m["py_compiles"] + m["js_checks"] + m["commit_files"]:
                    self.assertIn(rel, m["payload"],
                                  f"{path.name}: {rel} not in payload")
                for pattern, expected in m["test_runs"]:
                    self.assertIsInstance(expected, int)
                    self.assertGreater(expected, 0)
                    self.assertTrue(list(Path("tests").glob(pattern)),
                                    f"{path.name}: test pattern matches nothing: {pattern}")

    def test_round_ids_and_bak_suffixes_agree(self):
        for path in sorted(KITS_DIR.glob("*.json")):
            m = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(manifest=path.name):
                self.assertRegex(m["round"], r"^R\d+$")
                self.assertTrue(m["name"].startswith(m["round"].lower() + "_"),
                                "kit name must carry its round id")

    def test_r58_kit_rebuilds_from_the_clean_clone(self):
        """THE handover property: the shipped R58 kit is reproducible from the
        tree alone (md5s + markers + generated installer all self-checked)."""
        r = _run_builder(["tools/kits/r58_retrieval_hardening.json", "--verify-only"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("post-build self-check PASS", r.stdout)
        self.assertIn("VERIFIED r58_retrieval_hardening.zip", r.stdout)

    def test_ci_kit_command_verbatim_works(self):
        # The exact command ci.yml runs must work as written.
        r = _run_builder(["--latest", "--verify-only"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("post-build self-check PASS", r.stdout)

    def test_builder_refuses_missing_payload_file(self):
        m = json.loads((KITS_DIR / "r58_retrieval_hardening.json").read_text())
        m["payload"][0] = "ai/does_not_exist.py"
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps(m), encoding="utf-8")
            r = _run_builder([str(bad), "--verify-only"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("NOT FOUND", (r.stdout + r.stderr))

    def test_builder_refuses_replaced_outside_payload(self):
        m = json.loads((KITS_DIR / "r58_retrieval_hardening.json").read_text())
        m["replaced"] = ["ai/assistant_core.py", "not/in/payload.py"]
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps(m), encoding="utf-8")
            r = _run_builder([str(bad), "--verify-only"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("replaced files must be in payload", (r.stdout + r.stderr))

    def test_builder_refuses_stale_test_pattern(self):
        m = json.loads((KITS_DIR / "r58_retrieval_hardening.json").read_text())
        m["test_runs"] = [["test_no_such_suite.py", 1]]
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps(m), encoding="utf-8")
            r = _run_builder([str(bad), "--verify-only"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("matches nothing", (r.stdout + r.stderr))


class TestGeneratedInstallerConvention(unittest.TestCase):
    """The generated INSTALL_*.py keeps the R36+ deploy contract."""

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        out = Path(cls._td.name)
        r = _run_builder(["tools/kits/r58_retrieval_hardening.json",
                          "--out", str(out)])
        assert r.returncode == 0, r.stdout + r.stderr
        cls.zip_path = out / "r58_retrieval_hardening.zip"
        with zipfile.ZipFile(cls.zip_path) as zf:
            cls.names = zf.namelist()
            cls.installer = zf.read("INSTALL_R58.py").decode("utf-8")
            cls.install_txt = zf.read("INSTALL.txt").decode("utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_zip_shape_is_payload_plus_installer_plus_txt(self):
        m = json.loads((KITS_DIR / "r58_retrieval_hardening.json").read_text())
        self.assertEqual(self.names, m["payload"] + ["INSTALL_R58.py", "INSTALL.txt"])

    def test_installer_keeps_the_backup_contract(self):
        self.assertIn(".pre_r58.bak", self.installer)
        self.assertIn("(kept -- original preserved)", self.installer)
        self.assertIn('"[new]"', self.installer)
        self.assertIn('"[upd]"', self.installer)

    def test_installer_keeps_the_seven_step_shape(self):
        for step in ("[1/7] Backup + copy", "Regenerate docs on the target tree",
                     "[3/7] Content markers", "[4/7] py_compile", "[5/7] node --check",
                     "[6/7] Drift gate", "[7/7] Targeted test runs"):
            self.assertIn(step, self.installer, f"installer lost step: {step}")
        self.assertIn("RESULT:", self.installer)
        self.assertIn("never `git add -A`", self.installer)

    def test_installer_runs_discover_s_tests(self):
        for line in self.installer.splitlines():
            if line.lstrip().startswith("#"):
                continue  # comments may describe the rule
            if "unittest" in line and "discover" in line:
                # normalize both call forms: shell `discover -s tests` and the
                # argv-list `"discover", "-s", "tests"`
                normalized = re.sub(r"[\"',]", " ", line)
                normalized = re.sub(r"\s+", " ", normalized)
                self.assertIn("-s tests", normalized, f"{line!r} must pass -s tests")

    def test_install_txt_tells_the_wrong_directory_story(self):
        self.assertIn("_seed_env", self.install_txt)
        self.assertIn("wrong directory", self.install_txt)


if __name__ == "__main__":
    unittest.main()
