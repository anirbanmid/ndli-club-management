"""
Round 6 · Slice E — analytics advisor tests (strategic report explainers +
proactive nudge endpoint).

Covered (per Slice E brief):
1. Nudge endpoint: 401 unauthenticated; role-scoped signals (employee sees own
   clubs/issues/quota only, admin org-wide); AT MOST ONE nudge; priority order
   renewals > escalations > quota; stable ids (same flagged set -> same id).
2. Nudge signal semantics: overdue vs expiring-soon discrimination (the
   days_overdue==0 trap), the 14-day window, escalation aging, quota staleness.
3. Strategic report explainers: full walkthrough grounded in the report data,
   numbered recommendation zoom-in, section explainers, honest role denial.
4. Renewal answer badge wording (badge_label, not the days_overdue trap).
"""
import json
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from threading import Thread

from app import NDLIRequestHandler
from init_db import initialize_database

from ai import assistant_tools
from ai.assistant_core import ask_assistant, nudges_for
from ai.assistant_tools import ToolContext, call_tool
from ai.decision_module import AIDecisionEngine


class _SliceEBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str, token: str = ""):
        req = urllib.request.Request(f"{self.base_url}{path}")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class TestNudgeAuthAndScope(_SliceEBase):
    def test_nudges_requires_auth(self):
        status, data = self._get("/api/assistant/nudges", token="")
        self.assertEqual(status, 401)
        self.assertFalse(data.get("success"))

    def test_nudges_admin_scope_is_org_wide(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._get("/api/assistant/nudges", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("scope"), "all")
        self.assertIn("nudge", data)

    def test_nudges_employee_scope_is_self(self):
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._get("/api/assistant/nudges", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data.get("scope"), "employee:EMP01")

    def test_employee_signals_never_contain_other_employees(self):
        sig = call_tool("advisor.nudges", ToolContext(user_id="EMP01", role="EMPLOYEE"))
        # every flagged club must be one EMP01 approved (role scoping)
        emp01 = AIDecisionEngine.get_renewal_attention_data(
            clubs=[c for c in assistant_tools._read_master_clubs()
                   if c.get("approved_by_emp_id", "").strip().upper() == "EMP01"])
        allowed_ids = {c.get("club_id") for c in emp01.get("clubs", [])}
        self.assertTrue(set(sig["renewals"]["club_ids"]) <= allowed_ids)
        self.assertEqual(sig["quota"]["emp_ids"], sorted(sig["quota"]["emp_ids"]))
        self.assertEqual(sig["quota"]["count"], len(sig["quota"]["emp_ids"]))
        self.assertEqual(sig["scope"], "employee:EMP01")


class TestNudgeSignals(_SliceEBase):
    def test_renewal_window_excludes_far_future(self):
        """The 14-day window must NOT swallow expiring-soon clubs beyond it
        (the days_overdue==0 trap: expiring rows carry days_overdue 0)."""
        sig = call_tool("advisor.nudges", ToolContext(user_id="ADMIN01", role="ADMIN"))
        attention = AIDecisionEngine.get_renewal_attention_data()
        expected_ids = set()
        expected_overdue = 0
        for c in attention.get("clubs", []):
            atype = str(c.get("attention_type", "")).strip().lower()
            overdue = atype == "overdue" or (c.get("days_overdue") or 0) > 0
            soon = (not overdue) and (c.get("days_left") is not None
                                      and int(c["days_left"]) <= assistant_tools.NUDGE_RENEWAL_WINDOW_DAYS)
            if overdue or soon:
                expected_ids.add(c.get("club_id"))
            if overdue:
                expected_overdue += 1
        self.assertEqual(set(sig["renewals"]["club_ids"]), expected_ids)
        self.assertEqual(sig["renewals"]["overdue_count"], expected_overdue)
        self.assertEqual(sig["renewals"]["count"], len(expected_ids))

    def test_escalations_only_past_30_day_reminder_and_unresolved(self):
        fake_issues = [
            {"issue_id": "I-OLD", "status": "Unresolved",
             "admin_reminder_due_at": "2020-01-01T00:00:00+00:00"},
            {"issue_id": "I-NEW", "status": "Unresolved",
             "admin_reminder_due_at": "2999-01-01T00:00:00+00:00"},
            {"issue_id": "I-DONE", "status": "Resolved",
             "admin_reminder_due_at": "2020-01-01T00:00:00+00:00"},
        ]
        orig = assistant_tools.IssueManager.__dict__["get_issues"]
        assistant_tools.IssueManager.get_issues = classmethod(
            lambda cls, **kw: list(fake_issues))
        try:
            sig = call_tool("advisor.nudges", ToolContext(user_id="ADMIN01", role="ADMIN"))
        finally:
            assistant_tools.IssueManager.get_issues = orig
        self.assertEqual(sig["escalations"]["issue_ids"], ["I-OLD"])
        self.assertEqual(sig["escalations"]["count"], 1)

    def test_quota_staleness_threshold(self):
        fresh = {"emp_id": "EMP01", "employee_name": "x",
                 "last_activity_timestamp": "2999-01-01T00:00:00+00:00",
                 "clubs_approved_count": 1, "support_logs_count": 1, "zone": "North"}
        stale = dict(fresh, last_activity_timestamp="2020-01-01T00:00:00+00:00")
        orig = assistant_tools.derived_quota
        try:
            assistant_tools.derived_quota = lambda eid: dict(fresh)
            sig = call_tool("advisor.nudges", ToolContext(user_id="EMP01", role="EMPLOYEE"))
            self.assertEqual(sig["quota"]["count"], 0)

            assistant_tools.derived_quota = lambda eid: dict(stale)
            sig = call_tool("advisor.nudges", ToolContext(user_id="EMP01", role="EMPLOYEE"))
            self.assertEqual(sig["quota"]["count"], 1)
            self.assertEqual(sig["quota"]["emp_ids"], ["EMP01"])
        finally:
            assistant_tools.derived_quota = orig


class TestNudgeComposition(_SliceEBase):
    def _session(self, user_id, role):
        return {"user_id": user_id, "role": role}

    def test_at_most_one_nudge_with_full_shape(self):
        n = nudges_for(self._session("ADMIN01", "ADMIN"))
        self.assertIn("nudge", n)
        self.assertIn("checked_at", n)
        if n["nudge"] is None:
            self.skipTest("seed data produced no signals today")
        nd = n["nudge"]
        for key in ("id", "kind", "title", "detail", "href", "suggested_question"):
            self.assertIn(key, nd)
        self.assertIn(nd["kind"], ("renewals", "escalations", "quota"))

    def test_priority_renewals_first(self):
        """When renewals and other signals coexist, the nudge must be renewals."""
        n = nudges_for(self._session("ADMIN01", "ADMIN"))
        sig = call_tool("advisor.nudges", ToolContext(user_id="ADMIN01", role="ADMIN"))
        if sig["renewals"]["count"]:
            self.assertEqual(n["nudge"]["kind"], "renewals")
        elif sig["escalations"]["count"]:
            self.assertEqual(n["nudge"]["kind"], "escalations")

    def test_nudge_id_stable_and_set_sensitive(self):
        from ai.assistant_core import _nudge_signature
        self.assertEqual(_nudge_signature("A", "B"), _nudge_signature("A", "B"))
        self.assertNotEqual(_nudge_signature("A", "B"), _nudge_signature("A", "C"))


class TestExplainReport(_SliceEBase):
    def test_full_walkthrough_covers_every_recommendation(self):
        session = {"user_id": "ADMIN01", "role": "ADMIN"}
        result = ask_assistant("explain the strategic report", session)
        report = AIDecisionEngine.generate_strategic_report()
        recs = report.get("strategic_recommendations") or []
        answer = result["answer"]
        self.assertIn("What it means:", answer)
        self.assertIn("What to do:", answer)
        for r in recs:
            self.assertIn(r["title"], answer)
        self.assertEqual(answer.count("What it means:"), max(len(recs), 1))

    def test_numbered_zoom_in(self):
        session = {"user_id": "ADMIN01", "role": "ADMIN"}
        report = AIDecisionEngine.generate_strategic_report()
        recs = report.get("strategic_recommendations") or []
        self.assertTrue(recs, "seed data must produce recommendations")
        result = ask_assistant("explain recommendation 2", session)
        self.assertIn(f"Recommendation 2 of {len(recs)}", result["answer"])
        self.assertIn(recs[1]["title"], result["answer"])
        self.assertIn("What to do:", result["answer"])

    def test_out_of_range_recommendation_is_honest(self):
        session = {"user_id": "ADMIN01", "role": "ADMIN"}
        result = ask_assistant("explain recommendation 99", session)
        self.assertIn("recommendation 1 to", result["answer"])

    def test_section_explainer_zone(self):
        session = {"user_id": "ADMIN01", "role": "ADMIN"}
        result = ask_assistant("explain the zone distribution in the report", session)
        report = AIDecisionEngine.generate_strategic_report()
        answer = result["answer"]
        self.assertIn("Zone distribution", answer)
        for zone in (report.get("zone_distribution") or {}):
            self.assertIn(zone, answer)

    def test_employee_gets_honest_denial(self):
        session = {"user_id": "EMP01", "role": "EMPLOYEE"}
        result = ask_assistant("explain the strategic report", session)
        self.assertIn("isn't available for your role", result["answer"])

    def test_routing(self):
        from ai.assistant_core import _route
        intent, params = _route("explain the strategic report")
        self.assertEqual(intent, "explain_report")
        intent, params = _route("explain recommendation 2")
        self.assertEqual(intent, "explain_report")
        self.assertEqual(params.get("rec_index"), 2)
        # doc questions must NOT be stolen from the knowledge base pipeline
        self.assertNotEqual(_route("what is a renewal certificate")[0], "explain_report")
        # live-data snapshot questions stay on the strategy intent
        self.assertEqual(_route("what does the report recommend")[0], "strategy")


class TestRenewalAnswerBadges(_SliceEBase):
    def test_answer_uses_badge_label_not_overdue_trap(self):
        session = {"user_id": "ADMIN01", "role": "ADMIN"}
        tool = call_tool("renewals.due", ToolContext(user_id="ADMIN01", role="ADMIN"))
        result = ask_assistant("which renewals need attention?", session)
        for c in (tool.get("clubs") or [])[:3]:
            label = c.get("badge_label") or c.get("attention_type") or ""
            self.assertIn(f"({c.get('club_id')}): {label}", result["answer"])


if __name__ == "__main__":
    unittest.main()
