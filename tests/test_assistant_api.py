"""
Round 6 · Slice B — AI Assistant API tests (/api/assistant/ask · /api/assistant/feedback).

Covered (per Slice B brief):
1. Auth gates: 401 unauthenticated; employee is scoped to SELF (cross-employee
   reads are denied and leak nothing); admin can read everything.
2. Read-only tool surface: the whitelisted tool layer contains no CSV write
   APIs; unknown tool names are rejected.
3. Numeric-accuracy tripwires: for 5 questions the figures printed in the
   answer must equal the figures the tools return (single source of truth).
4. Feedback validation + append-only CSV persistence.
"""
import csv
import json
import threading
import unittest
import urllib.request
import uuid
from http.server import HTTPServer
from pathlib import Path

from app import NDLIRequestHandler
from init_db import initialize_database
from config import DATA_DIR

from ai.assistant_core import (
    ASSISTANT_FEEDBACK_CSV,
    FEEDBACK_FIELDS,
    ask_assistant,
    record_feedback,
)
from ai.assistant_tools import (
    FORBIDDEN_WRITE_CALLS,
    TOOL_NAMES,
    ToolAuthError,
    ToolContext,
    build_context,
    call_tool,
    derived_quota,
)


class _AssistantAPITestBase(unittest.TestCase):
    """Shared HTTP server + helpers (pattern matches tests/test_api.py)."""

    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _admin_ctx(self):
        return ToolContext(user_id="ADMIN01", role="ADMIN")

    def _employee_ctx(self, emp_id):
        return ToolContext(user_id=emp_id, role="EMPLOYEE")

    def _post(self, path: str, payload: dict, token: str = ""):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _ask(self, question: str, token: str = ""):
        return self._post("/api/assistant/ask", {"question": question}, token=token)


class TestAssistantAuthGates(_AssistantAPITestBase):
    """1. Auth gates."""

    def test_ask_requires_auth(self):
        status, data = self._ask("what is my quota", token="")
        self.assertEqual(status, 401)
        self.assertFalse(data.get("success"))

    def test_feedback_requires_auth(self):
        status, data = self._post("/api/assistant/feedback",
                                  {"question": "q", "verdict": "up"}, token="")
        self.assertEqual(status, 401)

    def test_ask_empty_question_rejected(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("   ", token=token)
        self.assertEqual(status, 400)

    def test_ask_overlong_question_rejected(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("x" * 1001, token=token)
        self.assertEqual(status, 400)

    def test_employee_cannot_read_other_employee_quota(self):
        """EMP01 asking about EMP05 must be denied AND leak no EMP05 figures."""
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("what is the quota for EMP05", token=token)
        self.assertEqual(status, 200)
        answer = data["answer"]
        self.assertIn("isn't available for your role", answer)
        emp05 = derived_quota("EMP05")
        # The denial must not embed the other employee's counters.
        self.assertNotIn(f"{emp05['clubs_approved_count']} club approvals", answer)
        self.assertNotIn("EMP05 has", answer)

    def test_employee_cannot_read_admin_metrics(self):
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("show the dashboard metrics", token=token)
        self.assertEqual(status, 200)
        self.assertIn("administrators only", data["answer"])

    def test_employee_cannot_read_strategic_report(self):
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP02")
        status, data = self._ask("what does the strategic report recommend", token=token)
        self.assertEqual(status, 200)
        self.assertIn("administrators only", data["answer"])

    def test_admin_can_read_any_employee(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("what is the quota for EMP05", token=token)
        self.assertEqual(status, 200)
        emp05 = derived_quota("EMP05")
        self.assertIn(str(emp05["clubs_approved_count"]), data["answer"])
        self.assertIn("EMP05", data["answer"])

    def test_build_context_never_defaults_identity(self):
        """Identity must come from a verified session — never EMP01 by default."""
        with self.assertRaises(ToolAuthError):
            build_context({})
        with self.assertRaises(ToolAuthError):
            build_context("not-a-dict")


class TestAssistantReadOnlyTools(_AssistantAPITestBase):
    """2. Read-only tool surface."""

    def test_tool_layer_has_no_write_calls(self):
        """AST-level check: no CALL to a write API anywhere in the tool layer.
        (Text scanning false-positives on the module's own docstrings, which
        legitimately *name* the forbidden APIs when explaining the rule.)"""
        import ast
        src = Path("ai/assistant_tools.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = set()
        names_used = set()
        bad_open_modes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names_used.add(node.id)
            if isinstance(node, ast.Call):
                fn = node.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                called.add(fname)
                if fname == "open":
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Constant) and any(m in str(arg.value) for m in ("w", "a", "x")):
                            bad_open_modes.append(str(arg.value))
        forbidden_calls = {name for name in FORBIDDEN_WRITE_CALLS
                           if not name.startswith(".") and "." not in name and "(" not in name}
        forbidden_calls |= {"remove", "unlink", "rmdir", "rename"}
        self.assertFalse(forbidden_calls & called,
                         f"tool layer must not CALL write APIs: {forbidden_calls & called}")
        self.assertNotIn("shutil", names_used, "tool layer must not use shutil")
        self.assertEqual(bad_open_modes, [], f"tool layer must not open files for writing: {bad_open_modes}")

    def test_tool_whitelist_is_exactly_the_planned_surface(self):
        self.assertEqual(TOOL_NAMES, frozenset({
            "clubs.list", "clubs.search", "activities.summary", "quota.get",
            "issues.list", "renewals.due", "metrics.get",
            "analytics.strategic_report", "help.steps",
            "advisor.nudges",  # Slice E: proactive nudge signals
            "learning.insights",  # Slice F: learning-loop report (visibility-gated)
        }))

    def test_unknown_tool_rejected(self):
        ctx = ToolContext(user_id="EMP01", role="EMPLOYEE")
        with self.assertRaises(Exception):
            call_tool("os.system", ctx)
        with self.assertRaises(Exception):
            call_tool("__class__", ctx)

    def test_feedback_is_the_only_write_surface(self):
        """The assistant stack may write exactly one CSV: assistant_feedback.csv."""
        core_src = Path("ai/assistant_core.py").read_text(encoding="utf-8")
        self.assertNotIn("CSVEngine.upsert_row", core_src)
        self.assertNotIn("CSVEngine.write_all", core_src)
        self.assertNotIn("CSVEngine.delete_row", core_src)


class TestAssistantNumericTripwires(_AssistantAPITestBase):
    """3. Answer figures must equal tool figures (no recomputation drift)."""

    def test_tripwire_employee_quota(self):
        """Q: 'what is my quota' -> figures == derived_quota(EMP01)."""
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("what is my quota", token=token)
        self.assertEqual(status, 200)
        expected = call_tool("quota.get", self._employee_ctx("EMP01"))
        answer = data["answer"]
        self.assertIn(f"{expected['clubs_approved_count']} club approvals", answer)
        self.assertIn(f"{expected['support_logs_count']} support logs", answer)

    def test_tripwire_admin_team_quota(self):
        """Q: 'team quota' -> totals == quota.get team roll-up."""
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("give me the team quota totals", token=token)
        self.assertEqual(status, 200)
        expected = call_tool("quota.get", self._admin_ctx())
        answer = data["answer"]
        self.assertIn(f"{expected['total_employees']} employees", answer)
        self.assertIn(f"{expected['total_clubs_approved']} club approvals", answer)
        self.assertIn(f"{expected['total_support_logs']} support logs", answer)

    def test_tripwire_renewals(self):
        """Q: 'renewals needing attention' -> counts == renewals.due."""
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("which renewals need attention soon", token=token)
        self.assertEqual(status, 200)
        expected = call_tool("renewals.due", self._admin_ctx(), window_days=90)
        answer = data["answer"]
        self.assertIn(f"{expected['total_attention_count']} clubs need attention", answer)
        self.assertIn(f"{expected['overdue_count']} overdue", answer)
        self.assertIn(f"{expected['expiring_soon_count']} expiring soon", answer)

    def test_tripwire_clubs_list(self):
        """Q: 'how many clubs' -> total == clubs.list total."""
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("how many clubs are there in total", token=token)
        self.assertEqual(status, 200)
        expected = call_tool("clubs.list", self._admin_ctx())
        answer = data["answer"]
        self.assertIn(f"{expected['total_clubs']} clubs", answer)
        self.assertIn(f"{expected['states_represented']} states", answer)

    def test_tripwire_activities(self):
        """Q: 'activities summary' -> totals == activities.summary."""
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("give me my activities summary", token=token)
        self.assertEqual(status, 200)
        expected = call_tool("activities.summary", self._employee_ctx("EMP01"))
        answer = data["answer"]
        self.assertIn(f"{expected['total_activities']} activities total", answer)
        self.assertIn(f"{expected['priority_count']} flagged priority", answer)

    def test_tripwire_admin_metrics(self):
        """Q: 'dashboard metrics' -> figures == metrics.get."""
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("give me the headline dashboard metrics", token=token)
        self.assertEqual(status, 200)
        expected = call_tool("metrics.get", self._admin_ctx())
        answer = data["answer"]
        self.assertIn(f"{expected['total_clubs']} clubs", answer)
        self.assertIn(f"{expected['total_activities']} activities", answer)
        self.assertIn(f"{expected['total_employees']} employees", answer)
        self.assertIn(f"{expected['renewal_attention_count']} clubs", answer)


class TestAssistantAnswers(_AssistantAPITestBase):
    """Answer shape, journey guidance, search."""

    def test_response_shape(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("hello", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertIn("answer", data)
        self.assertIsInstance(data["sources"], list)
        self.assertIsInstance(data["suggestions"], list)
        for s in data["sources"]:
            self.assertIn("title", s)
            self.assertIn("detail", s)
        for s in data["suggestions"]:
            self.assertIn("title", s)
            self.assertIn("href", s)

    def test_help_steps_renewal_guide(self):
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("how do I approve a renewal?", token=token)
        self.assertEqual(status, 200)
        answer = data["answer"]
        self.assertIn("approve a club registration renewal", answer)
        self.assertIn("1. ", answer)
        self.assertIn("4. ", answer)

    def test_help_steps_password_guide(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("steps to change my password", token=token)
        self.assertEqual(status, 200)
        self.assertIn("change your password", data["answer"])

    def test_help_index_lists_guides(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("guide me please", token=token)
        self.assertEqual(status, 200)
        self.assertIn("approve_renewal", data["answer"])

    def test_clubs_search_returns_match(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        probe = call_tool("clubs.search", self._admin_ctx(), query="delhi", limit=5)
        if not probe["clubs"]:
            self.skipTest("no club rows searchable with 'delhi' in this dataset")
        status, data = self._ask("find club delhi", token=token)
        self.assertEqual(status, 200)
        self.assertIn(probe["clubs"][0]["club_id"], data["answer"])

    def test_fallback_is_honest(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("quantum flux capacitor banana??", token=token)
        self.assertEqual(status, 200)
        self.assertIn("template mode", data["answer"])

    def test_about_intent_robu_origin(self):
        """'Who are you' -> Robu persona answer with the name origin (user 2026-10-01)."""
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        for question in ("who are you", "what is your name", "who made you"):
            status, data = self._ask(question, token=token)
            self.assertEqual(status, 200)
            self.assertIn("Robu", data["answer"])
            self.assertIn("333", data["answer"])

    def test_greeting_short_circuits(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("hello", token=token)
        self.assertEqual(status, 200)
        self.assertIn("Ask me about", data["answer"])


class TestAssistantFeedback(_AssistantAPITestBase):
    """4. Feedback validation + append-only persistence."""

    def _admin(self):
        from auth_util import admin_token
        return admin_token(self.base_url, self.__class__.__name__)

    def test_feedback_validation_bad_verdict(self):
        status, data = self._post("/api/assistant/feedback",
                                  {"question": "hello", "verdict": "meh"},
                                  token=self._admin())
        self.assertEqual(status, 400)
        self.assertIn("verdict", data["message"])

    def test_feedback_validation_missing_question(self):
        status, data = self._post("/api/assistant/feedback",
                                  {"question": "", "verdict": "up"},
                                  token=self._admin())
        self.assertEqual(status, 400)

    def test_feedback_validation_comment_too_long(self):
        status, data = self._post("/api/assistant/feedback",
                                  {"question": "hello", "verdict": "up", "comment": "x" * 501},
                                  token=self._admin())
        self.assertEqual(status, 400)

    def test_feedback_validation_question_too_long(self):
        status, data = self._post("/api/assistant/feedback",
                                  {"question": "x" * 1001, "verdict": "up"},
                                  token=self._admin())
        self.assertEqual(status, 400)

    def test_feedback_appends_csv_row(self):
        marker = f"tripwire-feedback-marker-{uuid.uuid4().hex}"
        status, data = self._post("/api/assistant/feedback",
                                  {"question": marker, "verdict": "down", "comment": "was stale"},
                                  token=self._admin())
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertTrue(ASSISTANT_FEEDBACK_CSV.exists(), "feedback CSV must be created")
        with open(ASSISTANT_FEEDBACK_CSV, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(tuple(rows[0]), FEEDBACK_FIELDS)
        matches = [r for r in rows[1:] if r and r[4] == marker]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][3], "down")
        self.assertEqual(matches[0][5], "was stale")

    def test_feedback_csv_survives_commas_and_quotes(self):
        marker = f'comma,"quoted",marker-{uuid.uuid4().hex}'
        status, data = self._post("/api/assistant/feedback",
                                  {"question": marker, "verdict": "up"},
                                  token=self._admin())
        self.assertEqual(status, 200)
        with open(ASSISTANT_FEEDBACK_CSV, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        matches = [r for r in rows[1:] if r and r[4] == marker]
        self.assertEqual(len(matches), 1)

    def test_record_feedback_rejects_bad_verdict_directly(self):
        ok, err = record_feedback({"user_id": "EMP01", "role": "EMPLOYEE"}, "q", "sideways")
        self.assertFalse(ok)
        self.assertIn("verdict", err)


class TestAssistantIssueLogging(_AssistantAPITestBase):
    """Never-trust-200 discipline: failures land in assistant_issues.log."""

    def test_unmatched_question_is_logged(self):
        from ai.assistant_core import ASSISTANT_ISSUES_LOG, log_assistant_issue
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        marker = "log-tripwire-unique-xyzzy"
        status, data = self._ask(f"{marker} what even is this", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(ASSISTANT_ISSUES_LOG.exists(), "unmatched questions must be logged")
        content = ASSISTANT_ISSUES_LOG.read_text(encoding="utf-8")
        self.assertIn("unmatched question", content)

    def test_log_assistant_issue_never_raises_on_bad_context(self):
        from ai.assistant_core import log_assistant_issue
        # Unserializable context must not explode the caller.
        log_assistant_issue("test", "probe", {"bad": object()})
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
