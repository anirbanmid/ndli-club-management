"""
R29 — DISPLAY HONESTY LOCK TESTS ("live + migrated" split on every blended view).

Round rationale (user 2026-10-10: "make it simpler / show the split"): the API has
been sending both halves all along (live_* / legacy_* / migrated_* fields), but the
screens showed ONE blended total, and the employee quota line still used the
backwards "incl." wording the user had already flagged on the admin KPI cards.

Locks:
  1. the employee quota line spells out "X live + Y migrated" (no "incl.")
  2. the admin Performance Matrix labels the split on every blended column
  3. the Activity Distribution Matrix splits clubs + support from the quota rows
  4. the employee roster labels the split (tooltip) and the API sends the halves
  5. the split note is HIDDEN when there is no history (no "0 live + 0 migrated")
  6. anti-regression: the R30v3 KPI split wording and the migrated strip survive
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
from db.migration_engine import commit_employee_history

# Minimal client worksheet: 7 club approvals + 41 support interactions in the
# PERIOD year 2020 (a year with no live activity at all).
HIST_2020 = (
    "Timestamp_id,Task_id,State_id,Zone_id,Year_id,Month_id,Week_id,Club Approval,"
    "No. of User Registration,No. of Local Event,No. of Global Event,"
    "No. of Physical Workshop,Club Support,Nature of Support,\n"
    "03/11/2022 14:18:41,Club Approval,Telangana,South,2020,November,Date: 01-07,7,,,,,,,\n"
    "03/11/2022 14:18:42,Club support,Telangana,South,2020,November,Date: 01-07,,,,,,41,OC,\n"
)


class TestR29SplitDisplay(unittest.TestCase):
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

    # ---------- 1. the employee quota line ----------
    def test_employee_quota_line_spells_out_live_and_migrated(self):
        emp = self._read("templates/employee.html")
        for anchor in ('id="quota-live-clubs"', 'id="quota-live-support"',
                       'id="quota-legacy-clubs"', 'id="quota-legacy-support"'):
            self.assertIn(anchor, emp, f"quota line must carry {anchor}")
        line = emp[emp.index('id="quota-legacy-line"'):][:600]
        self.assertIn("live + ", line)
        self.assertIn("migrated clubs", line)
        self.assertIn("migrated support", line)

    def test_no_backwards_incl_wording_left(self):
        emp = self._read("templates/employee.html")
        adm = admin_js_view()
        self.assertNotIn('incl. <strong id="quota-legacy-clubs"', emp,
                         "the \"incl.\" wording reads backwards — it is gone")
        self.assertNotIn("incl. ${mig", adm,
                         "the \"incl.\" wording must not return on the KPI cards")

    # ---------- 2. the admin performance matrix ----------
    def test_perf_matrix_labels_the_split_on_every_blended_column(self):
        adm = admin_js_view()
        self.assertIn("function splitNote(live, migrated)", adm)
        self.assertIn("function splitTitle(total, live, migrated, label)", adm)
        # 3 performance-matrix columns (clubs / online training / other supports)
        # + 2 activity-matrix columns (clubs / support) = 5 split notes.
        self.assertEqual(adm.count("${splitNote("), 5,
                         "every blended number must render its split note")
        for field in ("off.live_clubs_approved", "off.migrated_clubs_approved",
                      "off.live_other_supports", "off.migrated_support",
                      "off.live_online_training", "off.migrated_online_workshops"):
            self.assertIn(field, adm, f"performance matrix must use {field}")

    # ---------- 3. the activity distribution matrix ----------
    def test_activity_matrix_splits_from_quota_rows(self):
        adm = admin_js_view()
        self.assertIn("q.legacy_clubs_count", adm)
        self.assertIn("q.legacy_support_count", adm)
        self.assertIn("splitNote(r.liveClubs, r.migClubs)", adm)
        self.assertIn("splitNote(r.liveSupport, r.migSupport)", adm)

    # ---------- 4. the employee roster ----------
    def test_roster_labels_the_split(self):
        adm = admin_js_view()
        self.assertIn("emp.legacy_clubs_count", adm)
        self.assertIn("emp.legacy_support_count", adm)
        self.assertIn("splitTitle(emp.clubs_approved_count", adm)

    def test_api_roster_carries_the_split_halves(self):
        commit_employee_history("EMP02", HIST_2020, replace=True,
                                actor=self.__class__.__name__)
        status, data = self._get("/api/admin/employees")
        self.assertEqual(status, 200, data)
        rows = {e["id"]: e for e in data.get("employees", [])}
        self.assertIn("EMP02", rows)
        for e in rows.values():
            for key in ("legacy_clubs_count", "legacy_support_count",
                        "legacy_online_workshops_count"):
                self.assertIn(key, e, f"roster row must carry {key}")
            self.assertGreaterEqual(
                e["clubs_approved_count"] - e["legacy_clubs_count"], 0,
                "the live half can never be negative")
            self.assertGreaterEqual(
                e["support_logs_count"] - e["legacy_support_count"], 0,
                "the live half can never be negative")
        emp02 = rows["EMP02"]
        self.assertEqual(emp02["legacy_clubs_count"], 7, emp02)
        self.assertEqual(emp02["legacy_support_count"], 41, emp02)
        self.assertGreaterEqual(emp02["clubs_approved_count"], 7,
                                "the migrated baseline rides inside the total")

    # ---------- 5. no history, no noise ----------
    def test_split_note_is_hidden_without_history(self):
        adm = admin_js_view()
        self.assertIn("if (mig <= 0) return \"\";", adm,
                      "views with no migrated history must show no split note")

    # ---------- 6. anti-regression: R30v2/v3 work survives ----------
    def test_r30v2_r30v3_pin(self):
        adm = admin_js_view()
        emp = self._read("templates/employee.html")
        self.assertIn("live + ${migApprovals} migrated club approvals (history)", adm)
        self.assertIn('id="migrated-history-strip"', emp)
        self.assertIn("date_of_approval,last_renewal_date,approved_by_emp_id", emp)


if __name__ == "__main__":
    unittest.main()
