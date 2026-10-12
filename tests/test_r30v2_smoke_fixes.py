"""
R30v2 — SMOKE-FOLLOWUP LOCK TESTS (user findings 2026-10-10 01:28).

Locks the four follow-up fixes:
  #5 the bulk-import CSV template DOCUMENTS the optional approved_by_emp_id
     attribution column (it was accepted by the parser but invisible in the UI)
  #3 the analytics year filter unions MIGRATED HISTORY period years (Year_id)
     with club/activity years — historical ranges slice correctly
  #2 the admin dashboard metrics expose migrated grand totals (honest
     live-vs-migrated split on the KPI cards) — the numbers stay non-inflated
  #1 the employee Activity History tab carries a "Migrated history" summary
     strip (visible history without fabricating per-event rows)
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
from admin_view import admin_js_view
import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from db.migration_engine import (
    commit_employee_history,
    history_grand_totals,
    history_period_years,
    MASTER_HISTORY_CSV,
)
from db.csv_engine import CSVEngine
from db.schemas import MIGRATION_HISTORY_FIELDS

# One worksheet row whose PERIOD year (2020) exists in no club/activity date —
# it must still surface in the analytics year filter.
HIST_2020 = (
    "Timestamp_id,Task_id,State_id,Zone_id,Year_id,Month_id,Week_id,Club Approval,"
    "No. of User Registration,No. of Local Event,No. of Global Event,"
    "No. of Physical Workshop,Club Support,Nature of Support,\n"
    "03/11/2022 14:18:41,Club Approval,Telangana,South,2020,November,Date: 01-07,7,,,,,,,\n"
    "03/11/2022 14:18:42,Club support,Telangana,South,2020,November,Date: 01-07,,,,,,41,OC,\n"
)


class TestR30V2SmokeFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    @staticmethod
    def _read(rel):
        with open(rel, encoding="utf-8") as fh:
            return fh.read()

    def _token(self):
        from auth_util import admin_token
        return admin_token(self.base_url, self.__class__.__name__)

    def _get(self, path):
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self._token()}"})
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _commit_2020(self):
        res = commit_employee_history("EMP02", HIST_2020, replace=True,
                                      actor=self.__class__.__name__)
        self.assertTrue(res.get("success"), res)
        return res

    # ---------- #5: template documents the attribution column ----------
    def test_bulk_template_documents_attribution_column(self):
        emp = self._read("templates/employee.html")
        self.assertIn(
            "date_of_approval,last_renewal_date,approved_by_emp_id", emp,
            "the CSV template header must show the optional attribution column")
        self.assertIn("approved_by_emp_id", emp[emp.index("const BULK_COLS"):][:400],
                      "BULK_COLS must accept the attribution column")
        self.assertIn("approved_by_emp_id", emp[emp.index('id="bulk-import-modal"'):][:1800],
                      "the bulk-import modal must document the optional column")

    # ---------- #3: year filter unions migrated history period years ----------
    def test_year_filter_includes_migrated_history_period_years(self):
        self._commit_2020()
        self.assertIn("2020", history_period_years())
        status, data = self._get("/api/admin/metrics")
        self.assertEqual(status, 200, data)
        self.assertIn("2020", data.get("available_years", []),
                      "metrics year filter must include migrated PERIOD years")
        status, data = self._get("/api/admin/employee-performance?year=ALL&month=ALL&state=ALL")
        self.assertEqual(status, 200, data)
        self.assertIn("2020", data.get("available_years", []),
                      "performance year filter must include migrated PERIOD years")

    def test_year_filter_slices_migrated_baseline_by_period(self):
        self._commit_2020()
        status, data = self._get("/api/admin/employee-performance?year=2020&month=ALL&state=ALL")
        self.assertEqual(status, 200, data)
        officers = {o["emp_id"]: o for o in data.get("officers", [])}
        self.assertIn("EMP02", officers)
        self.assertEqual(officers["EMP02"]["migrated_clubs_approved"], 7)
        self.assertEqual(officers["EMP02"]["migrated_support"], 41)

    # ---------- #2: metrics expose migrated totals (KPI split) ----------
    def test_metrics_expose_migrated_totals(self):
        self._commit_2020()
        status, data = self._get("/api/admin/metrics")
        self.assertEqual(status, 200, data)
        mig = data.get("summary", {}).get("migrated_totals", {})
        self.assertGreaterEqual(mig.get("approvals", 0), 7, mig)
        self.assertGreaterEqual(mig.get("support", 0), 41, mig)
        self.assertGreaterEqual(mig.get("employees_migrated", 0), 1, mig)
        self.assertEqual(mig.get("first_year"), "2020", mig)
        gt = history_grand_totals()
        self.assertEqual(gt["approvals"], mig["approvals"])
        # R30v3: the LIVE club count is exposed separately and must exclude
        # imported records (anti-double-count once the club log lands)
        self.assertIn("live_clubs", data.get("summary", {}), data.get("summary", {}))
        self.assertLessEqual(data["summary"]["live_clubs"],
                             data["summary"]["total_clubs"])

    def test_migrated_totals_follow_dashboard_scope(self):
        self._commit_2020()
        scoped = history_grand_totals(filter_year="2020")
        self.assertEqual(scoped["approvals"], 7, scoped)
        other = history_grand_totals(filter_year="2021")
        self.assertEqual(other["approvals"], 0, other)
        status, data = self._get("/api/admin/metrics?year=2020")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["summary"]["migrated_totals"]["approvals"], 7)

    def test_admin_kpi_split_markup(self):
        adm = admin_js_view()
        self.assertIn('id="kpi-clubs-migrated"', adm)
        self.assertIn('id="kpi-activities-migrated"', adm)
        self.assertIn("migrated_totals", adm)
        # R38: the headline total comes from the API (counting_rules module),
        # never JS addition (this pin replaced the R30v3 "liveClubs +
        # migApprovals" pin when the rule went single-source).
        self.assertIn("data.summary.programme_total", adm)
        self.assertNotIn("liveClubs + migApprovals", adm)
        self.assertIn("live + ${migApprovals} migrated club approvals (history)", adm)
        self.assertIn("live logs + ${migSupport} migrated support interactions (history)", adm)
        self.assertNotIn("incl. ${mig", adm)

    # ---------- R30v3: continuous programme year range (gap years show) ----------
    def test_year_filter_is_continuous_range(self):
        self._commit_2020()
        for endpoint in ("/api/admin/metrics", "/api/admin/employee-performance?year=ALL&month=ALL&state=ALL"):
            status, data = self._get(endpoint)
            self.assertEqual(status, 200, data)
            years = [int(y) for y in data.get("available_years", [])]
            self.assertTrue(years, endpoint)
            lo, hi = min(years), max(years)
            self.assertLessEqual(lo, 2020, f"{endpoint}: range must start at 2020 (programme floor)")
            self.assertGreaterEqual(hi, 2026, f"{endpoint}: range must reach the current year")
            for gap in range(lo, hi + 1):
                self.assertIn(gap, years,
                              f"{endpoint}: gap year {gap} missing from the continuous range")

    # ---------- #1: employee history tab shows the migrated summary ----------
    def test_employee_history_strip_and_profile_span(self):
        self._commit_2020()
        status, data = self._get("/api/employees/profile?id=EMP02")
        self.assertEqual(status, 200, data)
        emp = data["employee"]
        self.assertEqual(str(emp.get("legacy_first_year")), "2020", emp)
        self.assertEqual(str(emp.get("legacy_last_year")), "2020", emp)
        html = self._read("templates/employee.html")
        self.assertIn('id="migrated-history-strip"', html)
        self.assertIn('id="mig-hist-summary"', html)
        self.assertIn('getElementById("migrated-history-strip")', html,
                      "the strip must be populated from the profile data")

    # ---------- no-fabrication invariant holds after the patch ----------
    def test_history_rows_never_carry_club_identity(self):
        self.assertNotIn("club_id", MIGRATION_HISTORY_FIELDS)
        if MASTER_HISTORY_CSV.exists():
            for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS):
                self.assertEqual(str(r.get("club_id", "")).strip(), "")


if __name__ == "__main__":
    unittest.main()
