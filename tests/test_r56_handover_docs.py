"""
tests/test_r56_handover_docs.py

R56 pins -- "Handover package" (critique 2026-10-15 weak pillar #1: the
machine-room knowledge lived outside the repo).

R56 ships three ops docs into docs/ops/ and links them from README:
  * OPERATIONS_HANDOVER.md  -- account inventory, data map, alert meanings,
    the client-handover alert re-point checklist, watcher transfer options,
    incident playbook, maintenance.
  * DEPLOY_WORKFLOW.md      -- the round release workflow, smoke rules,
    rollback (Flow B), quota rules (references AGENTS.md, no duplication).
  * NDLI_Uptime_Watcher.gs  -- the Telegram uptime watcher source, shipped
    with the token PLACEHOLDER only.

The pins assert the docs exist and still carry the load-bearing content
(the exact things a future reader must not lose), the README links them, the
watcher keeps its placeholder and carries NO live token fragment, and none of
the new files were hit by the credential-censor "***" corruption trap.
"""
import _seed_env  # noqa: F401  (test-env convention; keeps discovery uniform)
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPS = os.path.join(REPO_ROOT, "docs", "ops")
HANDOVER = os.path.join(OPS, "OPERATIONS_HANDOVER.md")
WORKFLOW = os.path.join(OPS, "DEPLOY_WORKFLOW.md")
WATCHER = os.path.join(OPS, "NDLI_Uptime_Watcher.gs")
README = os.path.join(REPO_ROOT, "README.md")


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestHandoverDocsExist(unittest.TestCase):
    def test_all_three_ops_docs_present_and_nontrivial(self):
        for path in (HANDOVER, WORKFLOW, WATCHER):
            self.assertTrue(os.path.isfile(path), "missing: %s" % path)
            self.assertGreater(len(_read(path)), 800, "stub file? %s" % path)


class TestOperationsHandover(unittest.TestCase):
    def test_account_inventory_covers_every_external_asset(self):
        text = _read(HANDOVER)
        for marker in ("PythonAnywhere", "GitHub", "Google Drive", "Apps Script",
                       "Telegram bot", "NDLI_ASSISTANT_API_KEY"):
            self.assertIn(marker, text, "account inventory missing: %s" % marker)

    def test_client_handover_alert_checklist_is_actionable(self):
        text = _read(HANDOVER)
        for marker in ("/start", "setChatId", "getUpdates", "test alert"):
            self.assertIn(marker, text, "alert re-point checklist missing: %s" % marker)

    def test_watcher_transfer_options_named(self):
        text = _read(HANDOVER)
        for marker in ("Option A", "Option B", "Option C", "UptimeRobot"):
            self.assertIn(marker, text, "transfer option missing: %s" % marker)

    def test_incident_playbook_names_the_real_tools(self):
        text = _read(HANDOVER)
        for marker in ("sync_issues.log", "restore_backup.py", "Reload"):
            self.assertIn(marker, text, "incident playbook missing: %s" % marker)


class TestDeployWorkflow(unittest.TestCase):
    def test_smoke_rules_keep_the_hard_won_discipline(self):
        text = _read(WORKFLOW)
        for marker in ("Never commit a smoke-failed deploy", "git add -A",
                       "RESULT: N OK, 0 FAIL", "_seed_env", "100 CPU-s"):
            self.assertIn(marker, text, "smoke rule missing: %s" % marker)

    def test_rollback_and_agents_md_cross_reference(self):
        text = _read(WORKFLOW)
        for marker in ("Flow B", ".pre_rNN.bak", "AGENTS.md"):
            self.assertIn(marker, text, "workflow missing: %s" % marker)


class TestUptimeWatcherShipment(unittest.TestCase):
    def test_watcher_keeps_placeholder_and_no_live_token(self):
        text = _read(WATCHER)
        self.assertIn("PASTE_YOUR_BOT_TOKEN_HERE", text)
        self.assertNotIn("887308", text, "live token fragment shipped!")
        self.assertIn("checkSite", text)
        self.assertIn("getUpdates", text)
        self.assertIn("sendMessage", text)

    def test_new_files_carry_no_censor_glitches(self):
        for path in (HANDOVER, WORKFLOW, WATCHER, README):
            self.assertNotIn("***", _read(path),
                             "censor corruption in %s (memory lesson)" % path)


class TestReadmeLinks(unittest.TestCase):
    def test_readme_links_all_three_ops_docs(self):
        text = _read(README)
        for marker in ("docs/ops/OPERATIONS_HANDOVER.md",
                       "docs/ops/DEPLOY_WORKFLOW.md",
                       "docs/ops/NDLI_Uptime_Watcher.gs"):
            self.assertIn(marker, text, "README missing link: %s" % marker)


if __name__ == "__main__":
    unittest.main()
