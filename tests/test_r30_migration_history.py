"""
R30 — "Migration Phase 2: employee history baseline + club attribution" — LOCK TESTS.

Client-migration architecture (user-approved 2026-10-09):
  * Client worksheets = per-period COUNTS, no club identity. Past and present
    are kept separate: migrated history lives in its own table at PERIOD grain
    (Year/Month — never the entry timestamp), feeding a Performance Quota
    baseline (baseline + live-derived; anti-drift preserved).
  * Star rating = migrated baseline + live (user decision).
  * No fabricated links: history rows never touch clubs; no per-club approval
    rows are synthesised — only ONE marked "Data Migration" summary row.
  * Client quirks locked: "Workshop" rows are ONLINE workshops (the client's
    "No. of Physical Workshop" column is a misnomer); AD=Remote support
    (AnyDesk), OC=On Call, AD+OC=Both; giant single rows = legitimate
    backfill lumps (flagged as notes, never errors).
  * Bulk club import accepts an optional per-row approved_by_emp_id (client
    club log names the officer) — ADMIN-only.

Locked here: dry-run writes nothing, period-not-timestamp bucketing, task/nature
mapping, lump notes, replace semantics, baseline survives recompute (anti-drift),
imported clubs are NOT double-counted in performance, attribution gate, UI locks.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import os
import time
import unittest
import threading
import json
import urllib.request
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from db.migration_engine import (
    parse_employee_history_csv,
    baselines_for,
    MASTER_HISTORY_CSV,
)
from db.csv_engine import CSVEngine
from db.schemas import MIGRATION_HISTORY_FIELDS
from config import MASTER_QUOTAS_CSV
from db.schemas import QUOTA_FIELDS

GOOD_CSV = (
    "Timestamp_id,Task_id,State_id,Zone_id,Year_id,Month_id,Week_id,Club Approval,"
    "No. of User Registration,No. of Local Event,No. of Global Event,"
    "No. of Physical Workshop,Club Support,Nature of Support,\n"
    "03/11/2022 14:18:41,Club Approval,Telangana,South,2022,November,Date: 01-07,1,,,,,,,\n"
    "15/09/2023 10:26:40,Club support,Andhra Pradesh,South,2022,October,Date: 24-31,,,,,,\"1,116\",OC,\n"
    "01/06/2024 09:00:00,Workshop,Karnataka,South,2024,June,Date: 01-07,,,,,3,,,\n"
    "05/02/2025 12:00:00,Club Approval,Odisha,East,2025,February,Date: 01-07,219,,,,,,,\n"
)

BAD_CSV = GOOD_CSV + "05/02/2025 12:00:00,Club Renewal,Odisha,East,2025,February,Date: 01-07,1,,,,,,,\n"


class TestR30MigrationHistory(unittest.TestCase):
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

    # ---------- harness ----------
    def _token(self, role="admin", emp_id="EMP01"):
        from auth_util import admin_token, employee_token
        if role == "admin":
            return admin_token(self.base_url, self.__class__.__name__)
        return employee_token(self.base_url, self.__class__.__name__, emp_id=emp_id)

    def _post(self, path, payload, role="admin", emp_id="EMP01"):
        token = self._token(role, emp_id)
        payload = dict(payload)
        # R31 layer-2 gate: the migration history COMMIT endpoint now requires a
        # Master Admin password re-auth. Auto-attach it here (mirrors admin_token)
        # so these tests keep exercising migration behaviour, not the gate itself.
        # Dedicated gate tests live in tests/test_r31_two_doors.py.
        if path in ("/api/admin/migration/history/commit", "/api/admin/migration/clubs/commit") and "password" not in payload:
            from config import DEFAULT_ADMIN_PASSWORD
            payload["password"] = DEFAULT_ADMIN_PASSWORD
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get(self, path, role="admin", emp_id="EMP01"):
        token = self._token(role, emp_id)
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    @staticmethod
    def _history_rows(emp_id):
        clean = emp_id.strip().upper()
        if not MASTER_HISTORY_CSV.exists():
            return []
        return [r for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS)
                if r.get("emp_id", "").strip().upper() == clean]

    # ---------- parser (pure) ----------
    def test_parser_totals_and_period_not_timestamp(self):
        """Sums use the count columns; bucketing uses Year_id (2022 row whose entry timestamp is 2023)."""
        rep = parse_employee_history_csv(GOOD_CSV)
        self.assertEqual(rep["file_errors"], [])
        self.assertEqual(rep["summary"]["total_rows"], 4)
        self.assertEqual(rep["summary"]["error_rows"], 0)
        t = rep["summary"]["totals"]
        self.assertEqual(t["approvals"], 220)          # 1 + 219 (lump)
        self.assertEqual(t["support"], 1116)           # thousands separator "1,116"
        self.assertEqual(t["online_workshops"], 3)     # from the misnamed "Physical Workshop" column
        self.assertEqual(rep["summary"]["span"], {"first_year": 2022, "last_year": 2025})
        # the 2023-stamped row must bucket under its PERIOD year 2022
        by_year = {}
        for r in rep["rows"]:
            y = r["data"]["period_year"]
            by_year[y] = by_year.get(y, 0) + int(r["data"]["approvals_count"] or 0)
        self.assertEqual(by_year.get("2022"), 1)

    def test_parser_task_and_nature_mapping(self):
        rep = parse_employee_history_csv(GOOD_CSV)
        types = [r["data"]["task_type"] for r in rep["rows"]]
        self.assertIn("Online Workshop", types)        # "Workshop" never lands as physical
        self.assertIn("Club Support", types)
        natures = {r["data"]["nature"] for r in rep["rows"]}
        self.assertIn("On Call", natures)              # OC decoded per user
        for r in rep["rows"]:
            self.assertNotEqual(r["data"]["task_type"], "Physical Workshop")

    def test_parser_unknown_task_is_error_lump_is_note(self):
        rep = parse_employee_history_csv(BAD_CSV)
        self.assertEqual(rep["summary"]["error_rows"], 1)
        bad = [r for r in rep["rows"] if r["errors"]]
        self.assertEqual(len(bad), 1)
        self.assertIn("Unknown Task_id", bad[0]["errors"][0])
        # BOTH outlier families are real client backfills (approval catch-ups
        # 219/223/239/369/530 + one support catch-up row of 1,116 — verified on
        # client_activity_log_sample.csv: all stamped 03-04 Nov 2022 entry-time
        # clusters; support runner-up is 82). The dry-run must surface BOTH.
        lump = [r for r in rep["rows"] if any("backfill/lump" in n for n in r["notes"])]
        self.assertEqual(len(lump), 2)
        lump_app = [r for r in lump if r["data"]["approvals_count"] == "219"]
        self.assertEqual(len(lump_app), 1)
        lump_sup = [r for r in lump if r["data"]["support_count"] == "1116"]
        self.assertEqual(len(lump_sup), 1)

    # ---------- dry-run API ----------
    def test_validate_is_dry_run_and_writes_nothing(self):
        before = len(self._history_rows("EMP02"))
        status, data = self._post("/api/admin/migration/history/validate",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["dry_run"])
        self.assertTrue(data["ready"], data)
        self.assertEqual(data["summary"]["totals"]["approvals"], 220)
        self.assertEqual(len(self._history_rows("EMP02")), before)

    def test_validate_flags_unknown_employee_and_bad_rows(self):
        status, data = self._post("/api/admin/migration/history/validate",
                                  {"emp_id": "EMP99", "csv_text": GOOD_CSV})
        self.assertEqual(status, 200)
        self.assertFalse(data["ready"])
        self.assertTrue(any("does not exist" in e for e in data["file_errors"]), data)
        status, data = self._post("/api/admin/migration/history/validate",
                                  {"emp_id": "EMP02", "csv_text": BAD_CSV})
        self.assertFalse(data["ready"])

    def test_migration_endpoints_require_admin(self):
        status, data = self._post("/api/admin/migration/history/validate",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV},
                                  role="employee", emp_id="EMP02")
        self.assertEqual(status, 403, data)
        tokenless = urllib.request.Request(
            f"{self.base_url}/api/admin/migration/history/commit",
            data=json.dumps({"emp_id": "EMP02", "csv_text": GOOD_CSV}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(tokenless) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 401)

    # ---------- commit + quota arithmetic ----------
    def test_commit_writes_history_baseline_and_summary_row(self):
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV, "replace": True})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["success"])
        self.assertEqual(data["rows_written"], 4)
        rows = self._history_rows("EMP02")
        self.assertEqual(len(rows), 4)
        # NO fabricated links: history rows carry no club identity at all
        self.assertNotIn("club_id", MIGRATION_HISTORY_FIELDS)
        # ONE marked summary row (bulk number) — never per-club approval rows
        from config import MASTER_ACTIVITIES_CSV
        from db.schemas import ACTIVITY_FIELDS
        acts = [a for a in CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
                if a.get("emp_id", "").strip().upper() == "EMP02"
                and a.get("support_type", "").strip() == "Data Migration"]
        self.assertTrue(acts, "expected one marked 'Data Migration' summary row")
        self.assertEqual(acts[-1].get("club_id", ""), "")
        self.assertIn("220 club approvals", acts[-1].get("notes", ""))

    def test_quota_is_baseline_plus_live_and_split_exposed(self):
        # Self-sufficient: commit this test's own baseline first — never rely on
        # another test's write or on leftover store state (the fresh-store run
        # proved order/pollution dependence fails exactly like a PA re-run).
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV, "replace": True})
        self.assertEqual(status, 200, data)
        status, data = self._get("/api/employees/profile?id=EMP02")
        self.assertEqual(status, 200, data)
        emp = data["employee"]
        self.assertEqual(int(emp["legacy_clubs_count"]), 220)
        self.assertEqual(int(emp["legacy_support_count"]), 1116)
        self.assertEqual(int(emp["legacy_online_workshops_count"]), 3)
        self.assertEqual(int(emp["clubs_approved_count"]),
                         int(emp["live_clubs_approved_count"]) + 220)
        self.assertEqual(int(emp["support_logs_count"]),
                         int(emp["live_support_logs_count"]) + 1116)

    def test_baseline_survives_recompute_anti_drift(self):
        """The anti-drift recompute must ADD to the baseline, never wipe it."""
        from db.sync_engine import SyncEngine
        # Self-sufficient setup: commit this test's own baseline first (this
        # test sorts BEFORE the commit test — on a fresh store it must not
        # depend on any other test having written EMP02's history).
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV, "replace": True})
        self.assertEqual(status, 200, data)
        res1 = SyncEngine.recompute_and_persist_quota("EMP02")
        res2 = SyncEngine.recompute_and_persist_quota("EMP02")
        for res in (res1, res2):
            self.assertEqual(res["legacy_clubs_count"], 220, res)
            self.assertEqual(res["clubs_approved_count"],
                             res["live_clubs_approved_count"] + 220)
        self.assertEqual(res1["clubs_approved_count"], res2["clubs_approved_count"])
        qrows = [q for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
                 if q.get("emp_id", "").strip().upper() == "EMP02"]
        self.assertTrue(qrows)
        self.assertEqual(qrows[-1].get("legacy_clubs_count"), "220")

    def test_replace_semantics_idempotent(self):
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV})
        self.assertEqual(status, 409, data)  # no silent double-count
        self.assertEqual(len(self._history_rows("EMP02")), 4)
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV, "replace": True})
        self.assertEqual(status, 200, data)
        self.assertEqual(len(self._history_rows("EMP02")), 4)  # replaced, not doubled
        # Replace semantics cover the audit marker: exactly ONE "Data
        # Migration" summary row survives an idempotent re-run.
        from config import MASTER_ACTIVITIES_CSV
        from db.schemas import ACTIVITY_FIELDS
        acts = [a for a in CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
                if a.get("emp_id", "").strip().upper() == "EMP02"
                and a.get("support_type", "").strip() == "Data Migration"]
        self.assertEqual(len(acts), 1, acts)

    def test_data_migration_rows_do_not_inflate_support(self):
        from db.sync_engine import SyncEngine
        before = SyncEngine.recompute_and_persist_quota("EMP02")
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV, "replace": True})
        self.assertEqual(status, 200, data)
        res = SyncEngine.recompute_and_persist_quota("EMP02")
        # the "Data Migration" summary row must never count as support work
        self.assertEqual(res["live_support_logs_count"],
                         before["live_support_logs_count"], data)
        self.assertEqual(res["support_logs_count"],
                         res["live_support_logs_count"] + 1116)

    # ---------- performance / star rating ----------
    def test_star_rating_includes_baseline_and_splits(self):
        # Self-sufficient: commit this test's own baseline first.
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP02", "csv_text": GOOD_CSV, "replace": True})
        self.assertEqual(status, 200, data)
        status, data = self._get("/api/admin/employee-performance?year=ALL&month=ALL&state=ALL")
        self.assertEqual(status, 200, data)
        officers = {o["emp_id"]: o for o in data.get("officers", [])}
        self.assertIn("EMP02", officers)
        o = officers["EMP02"]
        self.assertEqual(o["migrated_clubs_approved"], 220)
        self.assertEqual(o["migrated_support"], 1116)
        self.assertEqual(o["clubs_approved"], o["live_clubs_approved"] + 220)
        self.assertEqual(o["other_supports"], o["live_other_supports"] + 1116)
        self.assertEqual(o["online_training"], o["live_online_training"] + 3)

    def test_imported_clubs_never_double_count(self):
        """A migrated club attributed to the officer must NOT add live credit
        (its history credit lives in the baseline) — the anti-double-count switch."""
        status, data = self._get("/api/admin/employee-performance?year=ALL&month=ALL&state=ALL")
        before = {o["emp_id"]: o["clubs_approved"] for o in data.get("officers", [])}["EMP02"]
        tag = str(int(time.time() * 1000))
        cid = "930" + tag[-6:]
        row = {"club_id": cid, "reg_no": "R30-REG-" + tag,
               "institution_name": "R30 Migrated History College",
               "state": "Odisha", "patron_email": "p@r30.edu",
               "president_email": "pr@r30.edu", "secretary_email": "s@r30.edu",
               "date_of_approval": "2021-03-04", "last_renewal_date": "2024-03-04",
               "approved_by_emp_id": "EMP02"}
        # R31 two-doors: historical/migrated clubs are imported via the ADMIN
        # Data Migration door (/api/admin/migration/clubs) -> record_origin="imported".
        status, data = self._post("/api/admin/migration/clubs/commit", {"rows": [row]})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["created"], 1, data)
        status, data = self._get("/api/admin/employee-performance?year=ALL&month=ALL&state=ALL")
        after = {o["emp_id"]: o["clubs_approved"] for o in data.get("officers", [])}["EMP02"]
        self.assertEqual(after, before,
                         "imported/migrated clubs must not add live performance credit")

    # ---------- bulk-import attribution ----------
    def test_bulk_attribution_admin_only_and_validated(self):
        tag = str(int(time.time() * 1000))[-6:]
        base = {"club_id": "931" + tag, "reg_no": "R30-ATTR-" + tag,
                "institution_name": "R30 Attribution College", "state": "Kerala",
                "patron_email": "p@r30.edu", "president_email": "pr@r30.edu",
                "secretary_email": "s@r30.edu"}  # R31: dateless = NEW work (employee door)
        # non-admin may not attribute to someone else
        status, data = self._post("/api/clubs/bulk-import/validate",
                                  {"emp_id": "EMP01",
                                   "rows": [dict(base, approved_by_emp_id="EMP02")]},
                                  role="employee", emp_id="EMP01")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["invalid"], 1, data)
        self.assertTrue(any("Only admins" in e for e in data["results"][0]["errors"]), data)
        # unknown employee attribution is rejected (admin included)
        status, data = self._post("/api/clubs/bulk-import/validate",
                                  {"emp_id": "EMP01",
                                   "rows": [dict(base, approved_by_emp_id="EMP99")]})
        self.assertEqual(data["invalid"], 1, data)
        self.assertTrue(any("EMP99" in e for e in data["results"][0]["errors"]), data)
        # admin attribution to a real employee is READY
        status, data = self._post("/api/clubs/bulk-import/validate",
                                  {"emp_id": "EMP01",
                                   "rows": [dict(base, approved_by_emp_id="EMP02")]})
        self.assertEqual(data["valid"], 1, data)
        self.assertEqual(data["results"][0]["approved_by_emp_id"], "EMP02")

    # ---------- UI locks ----------
    def test_ui_markup_locks(self):
        with open("templates/admin.html", encoding="utf-8") as fh:
            admin = fh.read()
        with open("templates/employee.html", encoding="utf-8") as fh:
            emp = fh.read()
        self.assertIn('id="migration-modal"', admin)
        self.assertIn('role="dialog"', admin[admin.find('id="migration-modal"'):][:200])
        self.assertIn('id="btn-open-migration"', admin)
        self.assertIn('id="mig-emp-id"', admin)
        self.assertIn('id="mig-replace"', admin)
        self.assertIn("runMigrationDryRun", admin)
        self.assertIn("/api/admin/migration/history/validate", admin)
        self.assertIn("/api/admin/migration/history/commit", admin)
        # employee side: the migrated-history split line (hidden until history
        # exists) — past vs present kept separate, per the locked architecture
        self.assertIn('id="quota-legacy-line"', emp)
        self.assertIn('id="quota-legacy-clubs"', emp)
        self.assertIn('id="quota-legacy-support"', emp)
        # R29 (user 2026-10-10): the old "incl." wording read backwards (the
        # migrated part looked contained in the headline). The line now spells
        # out BOTH halves: "X live + Y migrated". Pin follows the intended UI.
        _legacy_line = emp[emp.find('id="quota-legacy-line"'):][:600]
        self.assertIn("live + ", _legacy_line)
        self.assertIn("migrated clubs", _legacy_line)
        self.assertIn("migrated support", _legacy_line)
        self.assertNotIn("incl.", _legacy_line)
        self.assertIn('id="quota-legacy-line"', emp)
        self.assertIn('id="quota-legacy-clubs"', emp)
        self.assertIn("approved_by_emp_id", emp)  # bulk CSV attribution passthrough


if __name__ == "__main__":
    unittest.main()
