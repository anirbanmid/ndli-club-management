"""
Round 6 · Slice F — learning loop tests (golden eval harness + learning store).

Run the way the suite MUST be run (see the hard-won lessons):
    python3 -m unittest discover -s tests
(module-style `python3 -m unittest tests.x` breaks the auth_util imports.)

F1: eval harness scoring knowledge_base.GOLDEN_QUESTIONS outside a server.
F2/F3/F5: interaction log (redaction, retention, rotation), visibility toggle,
preference memory, outcome signals, and the "forget this user" privacy control
that HANDOFF_ROUND6_CHATBOT.md §6.5 says must ship WITH Slice F.
"""
import csv
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ai import assistant_evals, assistant_learning
from ai.assistant_tools import ToolContext
from ai.knowledge_base import GOLDEN_QUESTIONS


class TestGoldenQuestionEvals(unittest.TestCase):
    """1. Deterministic golden-question scoring."""

    def test_all_goldens_pass_in_deterministic_mode(self):
        report = assistant_evals.run_evals()
        self.assertGreaterEqual(report["total"], 8)
        failed = [r for r in report["results"] if not r["passed"]]
        self.assertEqual(
            failed, [],
            "golden questions must all pass in template+KB mode; failed: %r" % failed)
        self.assertEqual(report["passed"], report["total"])
        self.assertFalse(report["use_llm"])

    def test_missing_keyword_marks_failure(self):
        def dumb_fn(question):
            return {"answer": "I am not going to mention anything useful."}

        report = assistant_evals.run_evals(goldens=GOLDEN_QUESTIONS[:3], answer_fn=dumb_fn)
        self.assertEqual(report["passed"], 0)
        for r in report["results"]:
            self.assertFalse(r["passed"])
            self.assertTrue(r["missing_keywords"])

    def test_crash_is_recorded_not_swallowed(self):
        def boom(question):
            raise RuntimeError("eval explosion")

        report = assistant_evals.run_evals(goldens=GOLDEN_QUESTIONS[:2], answer_fn=boom)
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["total"], 2)
        for r in report["results"]:
            self.assertFalse(r["passed"])
            self.assertIn("eval explosion", r["error"])

    def test_empty_answer_never_passes(self):
        report = assistant_evals.run_evals(
            goldens=GOLDEN_QUESTIONS[:2], answer_fn=lambda q: "")
        self.assertEqual(report["passed"], 0)
        for r in report["results"]:
            self.assertFalse(r["passed"])

    def test_custom_answer_fn_scores_keywords(self):
        def good_fn(question):
            for g in GOLDEN_QUESTIONS:
                if g["question"] == question:
                    return {"answer": " ".join(g["expected_keywords"])}
            return {"answer": ""}

        report = assistant_evals.run_evals(answer_fn=good_fn)
        self.assertEqual(report["passed"], report["total"])


class TestEvalHarnessHygiene(unittest.TestCase):
    """2. The harness is read-only and honest."""

    def test_harness_source_has_no_write_calls(self):
        src = Path(assistant_evals.__file__).read_text(encoding="utf-8")
        for forbidden in ("write_all", "upsert_row", "append_row", "delete_row",
                          "shutil", "os.remove", ".unlink(", 'open(..., "w"',
                          'open("'):
            self.assertNotIn(forbidden, src,
                             "assistant_evals.py must stay read-only: found %r" % forbidden)

    def test_goldens_have_keywords_and_unique_ids(self):
        ids = [g["id"] for g in GOLDEN_QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        for g in GOLDEN_QUESTIONS:
            self.assertTrue(g["question"].strip())
            self.assertTrue(g["expected_keywords"])

    def test_format_report_names_failures(self):
        report = {
            "passed": 1, "total": 2, "pass_rate": 0.5, "use_llm": False,
            "results": [
                {"id": "ok", "question": "q1", "passed": True,
                 "missing_keywords": [], "error": "", "answer_preview": ""},
                {"id": "bad", "question": "q2", "passed": False,
                 "missing_keywords": ["quota"], "error": "", "answer_preview": ""},
            ],
        }
        text = assistant_evals.format_report(report)
        self.assertIn("[PASS] ok", text)
        self.assertIn("[FAIL] bad", text)
        self.assertIn("missing keywords: quota", text)


class _LearningStoreBase(unittest.TestCase):
    """Points the learning store at throwaway files for every test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.interactions = root / "assistant_interactions.csv"
        self.preferences = root / "assistant_preferences.csv"
        self.feedback = root / "assistant_feedback.csv"
        for name, path in (("ASSISTANT_INTERACTIONS_CSV", self.interactions),
                           ("ASSISTANT_PREFERENCES_CSV", self.preferences),
                           ("ASSISTANT_FEEDBACK_CSV", self.feedback)):
            patcher = mock.patch.object(assistant_learning, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(assistant_learning.VISIBILITY_ENV, None)

    @staticmethod
    def _ctx(user_id, role):
        return ToolContext(user_id=user_id, role=role)

    def _write_raw(self, path, fields, rows, stamps=None):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(fields)
            writer.writerows(rows)
        if stamps:
            self._backdate(path, stamps)

    @staticmethod
    def _backdate(path, stamps):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(rows[0])
            for row, stamp in zip(rows[1:], stamps):
                row[0] = stamp
                writer.writerow(row)


class TestRedaction(_LearningStoreBase):
    """F2 · secrets must never persist in the learning data."""

    def test_credential_shaped_fragments_are_redacted(self):
        cases = {
            "my password: hunter2 is wrong": "my password: [redacted] is wrong",
            "token=abc123xyz": "token=[redacted]",
            "api_key: sk-live-999": "api_key: [redacted]",
            "relay_key = RK42": "relay_key = [redacted]",
            "Authorization: Bearer eyJhbGciOi": "Authorization: [redacted]",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(assistant_learning.redact_secrets(raw), expected)

    def test_ordinary_text_untouched(self):
        text = "how many renewals are due in the East zone?"
        self.assertEqual(assistant_learning.redact_secrets(text), text)

    def test_record_interaction_persists_redacted_question_only(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        ok = assistant_learning.record_interaction(
            ctx, question="reset password: hunter2 for EMP02", intent="fallback")
        self.assertTrue(ok)
        rows = assistant_learning.read_interactions(ctx)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("hunter2", rows[0]["question"])
        self.assertIn("[redacted]", rows[0]["question"])


class TestInteractionLog(_LearningStoreBase):
    """F2 · append-only interaction log (asks + outcome signals)."""

    def test_record_and_read_roundtrip(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        self.assertTrue(assistant_learning.record_interaction(
            ctx, question="show my renewals", intent="renewals", mode="template",
            answered=True, latency_ms=12))
        self.assertTrue(assistant_learning.record_outcome(
            ctx, "suggestion_click", question="show my renewals", detail="renewals tab"))
        rows = assistant_learning.read_interactions(ctx)
        self.assertEqual([r["event"] for r in rows], ["suggestion_click", "ask"])
        self.assertEqual(rows[1]["intent"], "renewals")
        self.assertEqual(rows[1]["answered"], "1")
        self.assertEqual(rows[0]["detail"], "renewals tab")

    def test_refuses_unverified_identity(self):
        self.assertFalse(assistant_learning.record_interaction(None, question="hi"))
        self.assertFalse(assistant_learning.record_interaction(
            self._ctx("", ""), question="hi"))
        self.assertFalse(self.interactions.exists())

    def test_unknown_events_refused(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        self.assertFalse(assistant_learning.record_interaction(
            ctx, question="x", event="drop_table"))
        self.assertFalse(assistant_learning.record_outcome(ctx, "not_an_event"))
        self.assertFalse(self.interactions.exists())

    def test_question_is_truncated(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        assistant_learning.record_interaction(ctx, question="q" * 5000)
        rows = assistant_learning.read_interactions(ctx)
        self.assertLessEqual(len(rows[0]["question"]), assistant_learning._MAX_QUESTION_CHARS)


class TestRetentionAndRotation(_LearningStoreBase):
    """F2 · locked decision #5: 60-day retention + 30 MB oldest-first rotation."""

    def _stamp(self, days_ago):
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    def test_purge_drops_rows_older_than_60_days(self):
        self._write_raw(
            self.interactions, assistant_learning.INTERACTION_FIELDS,
            [["", "EMP01", "EMPLOYEE", "ask", "old question", "x", "template", "1", "1", ""],
             ["", "EMP01", "EMPLOYEE", "ask", "fresh question", "x", "template", "1", "1", ""]],
            stamps=[self._stamp(90), self._stamp(1)])
        result = assistant_learning.purge_expired()
        self.assertEqual(result["purged_interactions"], 1)
        rows = assistant_learning.read_interactions(self._ctx("EMP01", "EMPLOYEE"))
        self.assertEqual([r["question"] for r in rows], ["fresh question"])

    def test_rotation_keeps_newest_rows_oldest_first_drop(self):
        rows = [[self._stamp(i), "EMP01", "EMPLOYEE", "ask", "q%d" % i, "x", "t", "1", "1", ""]
                for i in range(10, 0, -1)]  # oldest first
        self._write_raw(self.interactions, assistant_learning.INTERACTION_FIELDS, rows)
        with mock.patch.object(assistant_learning, "MAX_LOG_BYTES", 1):
            assistant_learning.purge_expired()
        kept = assistant_learning.read_interactions(self._ctx("EMP01", "EMPLOYEE"))
        questions = [r["question"] for r in kept]  # newest first after rotation
        self.assertEqual(questions, ["q1", "q2", "q3", "q4", "q5"])

    def test_write_enforces_retention_opportunistically(self):
        self._write_raw(
            self.interactions, assistant_learning.INTERACTION_FIELDS,
            [["", "EMP01", "EMPLOYEE", "ask", "stale", "x", "t", "1", "1", ""]],
            stamps=[self._stamp(120)])
        assistant_learning.record_interaction(self._ctx("EMP02", "EMPLOYEE"), question="new")
        rows = assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN"))
        self.assertEqual([r["question"] for r in rows], ["new"])


class TestVisibilityModes(_LearningStoreBase):
    """F2 · visibility toggle (Slice F re-confirm: default `self`)."""

    def test_default_is_self(self):
        self.assertEqual(assistant_learning.log_visibility(), "self")

    def test_invalid_value_falls_back_to_default_and_stays_validated(self):
        os.environ[assistant_learning.VISIBILITY_ENV] = "everyone"
        self.assertEqual(assistant_learning.log_visibility(), "self")
        os.environ[assistant_learning.VISIBILITY_ENV] = "ADMIN"
        self.assertEqual(assistant_learning.log_visibility(), "admin")

    def test_admin_mode_restricts_reads_to_admins(self):
        assistant_learning.record_interaction(self._ctx("EMP01", "EMPLOYEE"), question="mine")
        assistant_learning.record_interaction(self._ctx("EMP02", "EMPLOYEE"), question="theirs")
        os.environ[assistant_learning.VISIBILITY_ENV] = "admin"
        self.assertEqual(
            assistant_learning.read_interactions(self._ctx("EMP01", "EMPLOYEE")), [])
        self.assertEqual(
            len(assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN"))), 2)

    def test_all_mode_lets_any_signed_in_user_read(self):
        assistant_learning.record_interaction(self._ctx("EMP01", "EMPLOYEE"), question="mine")
        assistant_learning.record_interaction(self._ctx("EMP02", "EMPLOYEE"), question="theirs")
        os.environ[assistant_learning.VISIBILITY_ENV] = "all"
        self.assertEqual(
            len(assistant_learning.read_interactions(self._ctx("EMP01", "EMPLOYEE"))), 2)

    def test_self_mode_scopes_to_own_rows_with_admin_oversight(self):
        assistant_learning.record_interaction(self._ctx("EMP01", "EMPLOYEE"), question="mine")
        assistant_learning.record_interaction(self._ctx("EMP02", "EMPLOYEE"), question="theirs")
        mine = assistant_learning.read_interactions(self._ctx("EMP01", "EMPLOYEE"))
        self.assertEqual([r["question"] for r in mine], ["mine"])
        # Admin oversight: administrators still see every row (as across the portal).
        admin = assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN"))
        self.assertEqual({r["question"] for r in admin}, {"mine", "theirs"})

    def test_summary_respects_visibility_and_aggregates(self):
        assistant_learning.record_interaction(
            self._ctx("EMP01", "EMPLOYEE"), question="quota rules?", intent="quota", answered=True)
        assistant_learning.record_interaction(
            self._ctx("EMP01", "EMPLOYEE"), question="quota rules?", intent="quota", answered=False)
        assistant_learning.record_outcome(self._ctx("EMP01", "EMPLOYEE"), "deep_link_open")
        summary = assistant_learning.interactions_summary(self._ctx("EMP01", "EMPLOYEE"))
        self.assertEqual(summary["visibility"], "self")
        self.assertEqual(summary["total_questions"], 2)
        self.assertEqual(summary["total_outcomes"], 1)
        self.assertEqual(summary["unanswered"], 1)
        self.assertEqual(summary["top_questions"][0], {"question": "quota rules?", "count": 2})
        self.assertEqual(summary["intents"], {"quota": 2})
        self.assertEqual(summary["outcome_events"]["deep_link_open"], 1)


class TestPreferenceMemory(_LearningStoreBase):
    """F3 · preference memory (own rows only, validated keys)."""

    def test_set_and_get_own_preference(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        ok, err = assistant_learning.set_preference(ctx, "detail.level", "brief")
        self.assertTrue(ok, err)
        self.assertEqual(assistant_learning.get_preferences("EMP01"), {"detail.level": "brief"})
        self.assertEqual(assistant_learning.get_preferences("EMP02"), {})

    def test_bad_keys_and_values_rejected(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        for key, value in (("Bad Key", "x"), ("", "x"), ("ok", ""), ("k" * 60, "x")):
            with self.subTest(key=key, value=value):
                ok, err = assistant_learning.set_preference(ctx, key, value)
                self.assertFalse(ok)
                self.assertTrue(err)
        self.assertEqual(assistant_learning.get_preferences("EMP01"), {})

    def test_preference_value_redacted_and_clipped(self):
        ctx = self._ctx("EMP01", "EMPLOYEE")
        assistant_learning.set_preference(ctx, "note", "password: hunter2 " + "x" * 500)
        stored = assistant_learning.get_preferences("EMP01")["note"]
        self.assertNotIn("hunter2", stored)
        self.assertLessEqual(len(stored), assistant_learning._MAX_PREF_VALUE)


class TestForgetUser(_LearningStoreBase):
    """F5 · hard constraint §6.5: "forget this user" ships WITH Slice F."""

    def _seed(self, user):
        assistant_learning.record_interaction(self._ctx(user, "EMPLOYEE"), question="q of " + user)
        assistant_learning.set_preference(self._ctx(user, "EMPLOYEE"), "k", "v")
        self._write_raw(
            self.feedback,
            ("timestamp_utc", "user_id", "role", "verdict", "question", "comment"),
            [["2026-10-01T00:00:00+00:00", user, "EMPLOYEE", "up", "q", ""],
             ["2026-10-01T00:00:00+00:00", "EMP02", "EMPLOYEE", "down", "q2", ""]])

    def test_admin_forgets_another_user_everywhere(self):
        self._seed("EMP01")
        ok, message = assistant_learning.forget_user(self._ctx("ADMIN01", "ADMIN"), "EMP01")
        self.assertTrue(ok, message)
        self.assertIn("EMP01", message)
        self.assertEqual(assistant_learning.get_preferences("EMP01"), {})
        self.assertEqual(assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN")), [])
        with open(self.feedback, "r", encoding="utf-8", newline="") as fh:
            feedback_rows = list(csv.DictReader(fh))
        self.assertEqual([r["user_id"] for r in feedback_rows], ["EMP02"])

    def test_employee_may_forget_self_only(self):
        self._seed("EMP01")
        ok, err = assistant_learning.forget_user(self._ctx("EMP01", "EMPLOYEE"), "EMP02")
        self.assertFalse(ok)
        self.assertIn("administrator", err)
        ok, _ = assistant_learning.forget_user(self._ctx("EMP01", "EMPLOYEE"), "EMP01")
        self.assertTrue(ok)
        self.assertEqual(assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN")), [])

    def test_non_admin_cannot_forget_an_admin(self):
        self._seed("ADMIN02")
        ok, err = assistant_learning.forget_user(self._ctx("EMP01", "EMPLOYEE"), "ADMIN02")
        self.assertFalse(ok)
        self.assertIn("administrator", err)


class TestLearningWiring(_LearningStoreBase):
    """F2/F4 · the orchestrator logs asks; learning.insights is role-gated."""

    def test_ask_assistant_records_one_interaction_row(self):
        from ai.assistant_core import ask_assistant
        session = {"user_id": "EMP01", "role": "EMPLOYEE", "full_name": "Test", "zone": ""}
        result = ask_assistant("hello", session)
        self.assertTrue(result["answer"])
        rows = assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "ask")
        self.assertEqual(rows[0]["user_id"], "EMP01")
        self.assertEqual(rows[0]["intent"], "greeting")
        self.assertEqual(rows[0]["answered"], "1")
        self.assertEqual(rows[0]["mode"], "template")

    def test_ask_assistant_records_fallback_as_unanswered(self):
        from ai.assistant_core import ask_assistant
        session = {"user_id": "EMP01", "role": "EMPLOYEE"}
        ask_assistant("what is the airspeed velocity of an unladen swallow?", session)
        rows = assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN"))
        self.assertEqual(rows[0]["mode"], "template")
        self.assertEqual(rows[0]["answered"], "0")

    def test_unverified_session_is_not_attributed(self):
        from ai.assistant_core import ask_assistant
        result = ask_assistant("hello", {})
        self.assertTrue(result["answer"])
        self.assertEqual(assistant_learning.read_interactions(self._ctx("ADMIN01", "ADMIN")), [])

    def test_learning_insights_tool_is_whitelisted_and_gated(self):
        from ai.assistant_tools import ToolAuthError, call_tool
        assistant_learning.record_interaction(
            self._ctx("EMP01", "EMPLOYEE"), question="how do quotas work?", intent="quota")
        report = call_tool("learning.insights", self._ctx("ADMIN01", "ADMIN"))
        self.assertEqual(report["tool"], "learning.insights")
        self.assertEqual(report["interactions"]["total_questions"], 1)
        os.environ[assistant_learning.VISIBILITY_ENV] = "admin"
        with self.assertRaises(ToolAuthError):
            call_tool("learning.insights", self._ctx("EMP01", "EMPLOYEE"))
        self.assertEqual(
            call_tool("learning.insights", self._ctx("ADMIN01", "ADMIN"))["scope"], "admin")


class TestLearningEndpoints(unittest.TestCase):
    """F2/F4/F5 - HTTP surface: auth gates, role scoping, privacy control."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import HTTPServer

        from app import NDLIRequestHandler
        from init_db import initialize_database

        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base_url = "http://127.0.0.1:%d" % cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _req(self, path, payload=None, token=""):
        import json
        import urllib.request

        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _admin(self):
        from auth_util import admin_token
        return admin_token(self.base_url, self.__class__.__name__)

    def _emp(self, emp_id="EMP01"):
        from auth_util import employee_token
        return employee_token(self.base_url, self.__class__.__name__, emp_id)

    def test_learning_endpoints_require_sessions(self):
        for path, payload in (("/api/assistant/insights", None),
                              ("/api/assistant/interactions", None),
                              ("/api/assistant/outcome", {"event": "suggestion_click"}),
                              ("/api/assistant/preferences", {"key": "tone", "value": "brief"}),
                              ("/api/assistant/forget", {"user_id": "EMP01"})):
            with self.subTest(path=path):
                status, data = self._req(path, payload)
                self.assertEqual(status, 401)
                self.assertFalse(data.get("success", False))

    def test_insights_works_for_admin(self):
        status, data = self._req("/api/assistant/insights", token=self._admin())
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["tool"], "learning.insights")
        self.assertIn("interactions", data)
        self.assertIn("feedback", data)

    def test_interactions_scoped_to_self_by_default(self):
        marker = "slice-f-visibility-check"
        status, _ = self._req("/api/assistant/ask", {"question": marker}, token=self._emp("EMP01"))
        self.assertEqual(status, 200)
        status, data = self._req("/api/assistant/interactions", token=self._emp("EMP01"))
        self.assertEqual(status, 200)
        self.assertEqual(data["visibility"], "self")
        self.assertTrue(data["interactions"])
        self.assertTrue(all(r["user_id"] == "EMP01" for r in data["interactions"]))
        status, other = self._req("/api/assistant/interactions", token=self._emp("EMP02"))
        self.assertEqual(status, 200)
        self.assertTrue(all(r["user_id"] == "EMP02" for r in other["interactions"]))

    def test_outcome_event_validation(self):
        status, data = self._req("/api/assistant/outcome", {"event": "drop_table"},
                                 token=self._emp("EMP01"))
        self.assertEqual(status, 400)
        status, data = self._req("/api/assistant/outcome",
                                 {"event": "suggestion_click", "detail": "quota tab"},
                                 token=self._emp("EMP01"))
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])

    def test_preferences_roundtrip_and_validation(self):
        status, data = self._req("/api/assistant/preferences",
                                 {"key": "tone", "value": "brief"}, token=self._emp("EMP01"))
        self.assertEqual(status, 200)
        self.assertEqual(data["preferences"].get("tone"), "brief")
        status, data = self._req("/api/assistant/preferences",
                                 {"key": "Bad Key", "value": "x"}, token=self._emp("EMP01"))
        self.assertEqual(status, 400)

    def test_forget_gates(self):
        status, data = self._req("/api/assistant/forget", {"user_id": "EMP02"},
                                 token=self._emp("EMP01"))
        self.assertEqual(status, 403)
        self.assertIn("administrator", str(data.get("message", "")))
        status, data = self._req("/api/assistant/forget", {"user_id": "EMP03"},
                                 token=self._emp("EMP03"))
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertIn("EMP03", data["message"])


if __name__ == "__main__":
    unittest.main()
