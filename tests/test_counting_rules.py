"""
R38 — SINGLE-SOURCE COUNTING RULES: cross-surface sameness invariants.

The R37v1 bug (Robu said "29 clubs (23 live + 6 migrated)" while the dashboard
said "23 live + 2289 migrated club approvals") happened because the counting
rule was written out in several layers and drifted. The fix (roadmap #1):
db/counting_rules.py is THE module; every surface reads it.

These tests assert SAMENESS ACROSS SURFACES, not just per-surface values:

  1. db.counting_rules is the only place that may compare record_origin
     against the import marker (grep-style source lock on the callers).
  2. The dashboard API summary == the assistant tool output == the module's
     own headline() for the SAME data (clubs.list / metrics.get /
     /api/admin/metrics).
  3. Every quota row's live halves == counting_rules.split_total() and the
     live half is never negative (the R30 negative-live bug stays dead).
  4. The JS never re-derives the split (no subtraction/arithmetic left in
     admin.html quota card / KPI headline paths).
  5. The activity bucketing rule still resolves from the single module
     (SyncEngine.bucket_activity delegates).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
from admin_view import admin_js_view
import re
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from app import NDLIRequestHandler
from init_db import initialize_database

from db import counting_rules
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS
from config import MASTER_CLUBS_CSV

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class _ServerBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.httpd = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path, token=None):
        req = urllib.request.Request(self.base_url + path)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, __import__("json").loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, __import__("json").loads(e.read().decode() or "{}")


class TestSingleSourceLocks(unittest.TestCase):
    """Only db/counting_rules.py may hold the provenance comparison."""

    CALLERS = ("app.py", "db/sync_engine.py", "ai/assistant_tools.py",
               "ai/assistant_core.py", "db/migration_engine.py")

    def test_no_caller_re_implements_the_imported_marker_comparison(self):
        # Any `record_origin` string comparison outside counting_rules.py is
        # a re-implementation of the rule (docstrings/comments excluded by
        # requiring a comparison operator on the same line).
        pat = re.compile(r"record_origin.*[=!]=\s*[\"']imported[\"']|[\"']imported[\"'].*[=!]=.*record_origin")
        for rel in self.CALLERS:
            for n, line in enumerate(_read(rel).splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("*") or stripped.startswith('"""'):
                    continue
                self.assertIsNone(pat.search(line),
                                  f"{rel}:{n} re-implements the provenance rule: {line.strip()}")

    def test_no_js_re_derives_the_split(self):
        # R41: the JS lives in static/js/admin_*.js - scan the combined view.
        adm = admin_js_view()
        # The quota card used to compute live = total - baseline in JS.
        self.assertNotIn("clubs - migClubs", adm,
                         "the live half comes from the API (counting_rules), never JS subtraction")
        self.assertNotIn("support - migSupport", adm,
                         "the live support half comes from the API, never JS subtraction")
        self.assertNotIn("liveClubs + migApprovals", adm,
                         "the headline total comes from the API (programme_total), never JS addition")

    def test_all_surfaces_import_the_module(self):
        self.assertIn("from db import counting_rules", _read("app.py"))
        self.assertIn("from db import counting_rules", _read("db/sync_engine.py"))
        self.assertIn("from db import counting_rules", _read("ai/assistant_tools.py"))


class TestModuleRules(unittest.TestCase):
    """The four rules, unit-level."""

    def test_provenance_split_sums_to_total(self):
        clubs = [{"record_origin": "created"}, {"record_origin": "imported"},
                 {"record_origin": ""}, {"record_origin": " IMPORTED "}]
        live, migrated = counting_rules.split_register_rows(clubs)
        self.assertEqual(live + migrated, len(clubs))
        self.assertEqual((live, migrated), (2, 2))

    def test_split_total_never_returns_negative_live(self):
        self.assertEqual(counting_rules.split_total(10, 4), (6, 4))
        self.assertEqual(counting_rules.split_total(4, 4), (0, 4))
        self.assertEqual(counting_rules.split_total(3, 9), (0, 3),
                         "a stale total smaller than its baseline never yields negative live")

    def test_split_total_accepts_numeric_strings(self):
        self.assertEqual(counting_rules.split_total("10", "4"), (6, 4))

    def test_bucket_activity_catch_all_and_skip(self):
        self.assertEqual(counting_rules.bucket_activity({"support_type": "Data Migration"}), "skip")
        self.assertEqual(counting_rules.bucket_activity({"support_type": "Club Approval",
                                                         "emp_id": "EMP01",
                                                         "activity_id": "ACT-X"}), "approval")
        self.assertEqual(counting_rules.bucket_activity({"support_type": "Something New",
                                                         "emp_id": "EMP01",
                                                         "activity_id": "ACT-X"}), "other",
                         "an unseen support_type lands in 'other' — never dropped")

    def test_headline_arithmetic_is_the_dashboard_rule(self):
        clubs = [{"record_origin": "created"}, {"record_origin": "created"},
                 {"record_origin": "imported"}]
        h = counting_rules.headline(clubs, migrated_totals={"approvals": 100,
                                                            "support": 5,
                                                            "online_workshops": 2,
                                                            "employees_migrated": 1,
                                                            "first_year": "2020",
                                                            "last_year": "2020"})
        self.assertEqual(h["register_rows"], 3)
        self.assertEqual(h["live_clubs"], 2)
        self.assertEqual(h["register_migrated_rows"], 1)
        self.assertEqual(h["migrated_approvals"], 100)
        self.assertEqual(h["programme_total"], 102,
                         "headline = live portal rows + migrated APPROVALS baseline")

    def test_sync_engine_bucket_delegates_to_the_module(self):
        from db.sync_engine import SyncEngine
        row = {"support_type": "Offline training", "emp_id": "EMP01", "activity_id": "ACT-1"}
        self.assertEqual(SyncEngine.bucket_activity(row), counting_rules.bucket_activity(row))


class TestCrossSurfaceSameness(_ServerBase):
    """Dashboard API == assistant tools == the module, on the SAME store."""

    def test_dashboard_summary_matches_module_headline(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._get("/api/admin/metrics", token=token)
        self.assertEqual(status, 200, data)
        s = data.get("summary", {})
        h = counting_rules.headline(CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS))
        self.assertEqual(s.get("live_clubs"), h["live_clubs"])
        self.assertEqual(s.get("total_clubs"), h["register_rows"])
        self.assertEqual(s.get("register_migrated_rows"), h["register_migrated_rows"])
        self.assertEqual(s.get("migrated_approvals"), h["migrated_approvals"])
        self.assertEqual(s.get("programme_total"), h["programme_total"])
        self.assertEqual(s.get("programme_total"),
                         s.get("live_clubs", 0) + s.get("migrated_approvals", 0),
                         "the API fields must be internally consistent")

    def test_dashboard_matches_assistant_tools(self):
        from auth_util import admin_token
        from ai.assistant_tools import ToolContext, call_tool
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._get("/api/admin/metrics", token=token)
        self.assertEqual(status, 200, data)
        s = data.get("summary", {})
        ctx = ToolContext(user_id="ADMIN", role="ADMIN")
        for tool in ("clubs.list", "metrics.get"):
            res = call_tool(tool, ctx)
            self.assertEqual(res["live_clubs"], s.get("live_clubs"), tool)
            self.assertEqual(res["migrated_approvals"], s.get("migrated_approvals"), tool)
            self.assertEqual(res["programme_total"], s.get("programme_total"), tool)
            self.assertEqual(res["register_rows"], s.get("total_clubs"), tool)
            self.assertEqual(res["register_migrated_rows"],
                             s.get("register_migrated_rows"), tool)

    def test_quota_rows_carry_module_computed_live_halves(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._get("/api/admin/metrics", token=token)
        self.assertEqual(status, 200, data)
        for q in data.get("summary", {}).get("quotas", []):
            self.assertIn("live_clubs_count", q, q)
            self.assertIn("live_support_count", q, q)
            exp_live, exp_mig = counting_rules.split_total(
                q.get("clubs_approved_count", 0), q.get("legacy_clubs_count", 0))
            self.assertEqual(q["live_clubs_count"], exp_live, q)
            self.assertGreaterEqual(q["live_clubs_count"], 0, q)
            exp_sl, exp_sm = counting_rules.split_total(
                q.get("support_logs_count", 0), q.get("legacy_support_count", 0))
            self.assertEqual(q["live_support_count"], exp_sl, q)
            self.assertGreaterEqual(q["live_support_count"], 0, q)


if __name__ == "__main__":
    unittest.main()
