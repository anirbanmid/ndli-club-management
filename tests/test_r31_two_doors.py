"""
R31 "TWO DOORS" + the Layer-2 migration gate — LOCK TESTS.

Club entry is split into two doors (user-approved design 2026-10-10):
  * ADMIN Data Migration portal "Bulk Club History Upload" (/api/admin/migration/clubs/*)
    = HISTORY door: record_mode="import" -> record_origin="imported". Rows are
    VISIBLE in the Club Register + the "history" half of every split but add ZERO
    live credit (counters unchanged). Dry-run states the consequence and cross-checks
    the uploaded club counts against the R30 worksheet baselines (gap warning).
  * EMPLOYEE bulk door (/api/clubs/bulk-import/*) = NEW WORK door: record_mode="new"
    -> record_origin="created", counted live. Historical (old-looking) rows are
    REFUSED with a pointer to the Admin Data Migration portal.

Also locks the R31 Layer-2 security gate: both migration COMMIT endpoints require a
Master Admin password re-authentication server-side (missing -> 401, wrong -> 403);
the dry-run /validate endpoints stay password-free.

NOTE: ids are UNIQUE PER RUN (timestamp tag) so re-runs against a persistent store
are safe (bulk doors block existing club ids/reg-nos by design).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
import threading
import json
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS, QUOTA_FIELDS, MIGRATION_HISTORY_FIELDS
from db.migration_engine import MASTER_HISTORY_CSV
from db.sync_engine import SyncEngine
from config import (
    MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV,
    DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD,
)


class TestR31TwoDoors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.tag = str(int(datetime.now(timezone.utc).timestamp() * 1000))[-5:]

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

    def _post(self, path, payload, token=None, role="admin", emp_id="EMP01"):
        if token is None:
            token = self._token(role, emp_id)
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _cid(self, n):
        return "31" + self.tag + str(n)

    def _club_row(self, cid, emp="EMP01", **kw):
        b = {
            "club_id": cid,
            "reg_no": "REG-R31-" + cid,
            "institution_name": "R31 History College " + cid,
            "state": "West Bengal",
            "patron_email": "patron@r31.edu",
            "president_email": "pres@r31.edu",
            "secretary_email": "sec@r31.edu",
            "date_of_approval": "2021-03-04",
            "last_renewal_date": "2022-03-04",
            "approved_by_emp_id": emp,
        }
        b.update(kw)
        return b

    def _seed_worksheet_baseline(self, emp, approvals, hist_id=None):
        """Write one migrated-history row so baselines_for(emp)['approvals'] == approvals.
        Pass a hist_id and call _clear_worksheet_baseline to undo it (keeps tests
        independent of run order)."""
        hid = hist_id or f"HIST-R31-{self.tag}-{emp}"
        row = {f: "" for f in MIGRATION_HISTORY_FIELDS}
        row.update({
            "hist_id": hid,
            "emp_id": emp,
            "period_year": "2022",
            "period_month": "05",
            "task_type": "Club Approval",
            "approvals_count": str(approvals),
            "support_count": "0",
            "online_workshops_count": "0",
            "entry_timestamp": "",
            "batch_id": "r31-test",
        })
        CSVEngine.upsert_row(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS, "hist_id", row)
        return hid

    def _clear_worksheet_baseline(self, emp, hist_id):
        """Neutralise a seeded baseline row (approvals -> 0) so it can't leak into
        another test's quota arithmetic."""
        self._seed_worksheet_baseline(emp, 0, hist_id=hist_id)
        try:
            SyncEngine.recompute_and_persist_quota(emp)
        except Exception:
            pass

    @staticmethod
    def _quota_clubs(emp="EMP01"):
        for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS):
            if q.get("emp_id") == emp:
                return int(q.get("clubs_approved_count", "0") or "0")
        return 0

    @staticmethod
    def _master_club(cid):
        for c in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS):
            if c.get("club_id") == cid:
                return c
        return None

    # ================= Layer-2 security gate =================
    def test_history_commit_requires_master_password(self):
        self._post("/api/admin/migration/history/commit",
                   {"emp_id": "EMP01", "csv_text": "task_id,year_id,club approval\nClub Approval,2022,3\n"},
                   role="admin")  # no password
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP01", "csv_text": "task_id,year_id,club approval\nClub Approval,2022,3\n"})
        self.assertEqual(status, 401, data)
        self.assertIn("password", str(data.get("message", "")).lower())

    def test_history_commit_rejects_wrong_password(self):
        status, data = self._post("/api/admin/migration/history/commit",
                                  {"emp_id": "EMP01", "csv_text": "x", "password": "definitely-wrong"})
        self.assertEqual(status, 403, data)

    def test_history_validate_is_password_free(self):
        status, data = self._post("/api/admin/migration/history/validate",
                                  {"emp_id": "EMP01", "csv_text": "task_id,year_id,club approval\nClub Approval,2022,3\n"})
        self.assertEqual(status, 200, data)

    def test_clubs_commit_requires_master_password(self):
        status, data = self._post("/api/admin/migration/clubs/commit",
                                  {"rows": [self._club_row(self._cid("50"))]})
        self.assertEqual(status, 401, data)
        self.assertIn("password", str(data.get("message", "")).lower())

    def test_clubs_commit_rejects_wrong_password(self):
        status, data = self._post("/api/admin/migration/clubs/commit",
                                  {"rows": [self._club_row(self._cid("51"))], "password": "nope"})
        self.assertEqual(status, 403, data)

    def test_clubs_validate_is_password_free(self):
        status, data = self._post("/api/admin/migration/clubs/validate",
                                  {"rows": [self._club_row(self._cid("52"))]})
        self.assertEqual(status, 200, data)

    # ================= Admin HISTORY door =================
    def test_admin_clubs_import_is_history_not_counted(self):
        SyncEngine.recompute_and_persist_quota("EMP01")   # settle quota first
        q_before = self._quota_clubs()
        cid = self._cid("20")
        status, data = self._post("/api/admin/migration/clubs/commit",
                                  {"rows": [self._club_row(cid)], "password": DEFAULT_ADMIN_PASSWORD})
        self.assertEqual(status, 200, data)
        self.assertEqual(data.get("created"), 1, data)
        club = self._master_club(cid)
        self.assertIsNotNone(club, "history row must be saved")
        # HISTORY door: provenance imported, zero live credit
        self.assertEqual(club["record_origin"], "imported", club)
        self.assertEqual(self._quota_clubs(), q_before,
                         "history import must add ZERO live club credit")

    def test_admin_clubs_dry_run_states_history_consequence(self):
        cid = self._cid("21")
        status, data = self._post("/api/admin/migration/clubs/validate",
                                  {"rows": [self._club_row(cid)]})
        self.assertEqual(status, 200, data)
        self.assertTrue(data.get("dry_run"))
        cons = data.get("consequence", "")
        self.assertIn("HISTORY", cons)
        self.assertIn("counters unchanged", cons)
        self.assertEqual(data.get("door"), "history")
        # dry-run writes nothing
        self.assertIsNone(self._master_club(cid))

    def test_admin_clubs_requires_officer_attribution(self):
        cid = self._cid("22")
        row = self._club_row(cid)
        row.pop("approved_by_emp_id")
        status, data = self._post("/api/admin/migration/clubs/validate", {"rows": [row]})
        self.assertEqual(status, 200, data)
        r = data["results"][0]
        self.assertEqual(r["status"], "error")
        self.assertTrue(any("approved_by_emp_id" in e for e in r["errors"]), data)

    def test_admin_clubs_gap_warning_vs_worksheet(self):
        # worksheet says EMP01 approved 57; upload 2 club rows -> gap flagged
        hid = self._seed_worksheet_baseline("EMP01", 57)
        rows = [self._club_row(self._cid("23"), emp="EMP01"),
                self._club_row(self._cid("24"), emp="EMP01")]
        try:
            status, data = self._post("/api/admin/migration/clubs/validate", {"rows": rows})
            self.assertEqual(status, 200, data)
            gaps = data.get("gap_warnings", [])
            self.assertTrue(gaps, data)
            self.assertTrue(any("EMP01" in g and "gap" in g for g in gaps), gaps)
        finally:
            self._clear_worksheet_baseline("EMP01", hid)

    def test_admin_history_rows_visible_in_master_clubs(self):
        cid = self._cid("25")
        self._post("/api/admin/migration/clubs/commit",
                   {"rows": [self._club_row(cid)], "password": DEFAULT_ADMIN_PASSWORD})
        # visible in the register (present in master clubs) with imported provenance
        club = self._master_club(cid)
        self.assertIsNotNone(club)
        self.assertEqual(club["record_origin"], "imported")

    # ================= Two-doors contract =================
    def test_employee_door_refuses_historical_with_pointer(self):
        cid = self._cid("30")
        row = self._club_row(cid, emp="EMP01")
        status, data = self._post("/api/clubs/bulk-import/validate",
                                  {"emp_id": "EMP01", "rows": [row]}, role="employee", emp_id="EMP01")
        self.assertEqual(status, 200, data)
        r = data["results"][0]
        self.assertEqual(r["status"], "error")
        self.assertTrue(any("Data Migration" in e for e in r["errors"]), data)

    def test_employee_door_new_work_is_counted(self):
        SyncEngine.recompute_and_persist_quota("EMP01")   # settle quota first
        q_before = self._quota_clubs()
        cid = self._cid("31")
        row = self._club_row(cid, emp="EMP01")
        row.pop("date_of_approval")
        row.pop("last_renewal_date")
        status, data = self._post("/api/clubs/bulk-import/commit",
                                  {"emp_id": "EMP01", "rows": [row]}, role="employee", emp_id="EMP01")
        self.assertEqual(status, 200, data)
        self.assertEqual(data.get("created"), 1, data)
        club = self._master_club(cid)
        self.assertEqual(club["record_origin"], "created", club)
        self.assertEqual(self._quota_clubs(), q_before + 1,
                         "new work must be counted live")

    def test_same_shape_two_doors_different_provenance(self):
        # The SAME club record shape goes through both doors and lands differently.
        hist_id, new_id = self._cid("32"), self._cid("33")
        self._post("/api/admin/migration/clubs/commit",
                   {"rows": [self._club_row(hist_id)], "password": DEFAULT_ADMIN_PASSWORD})
        new_row = self._club_row(new_id, emp="EMP01")
        new_row.pop("date_of_approval")
        new_row.pop("last_renewal_date")
        self._post("/api/clubs/bulk-import/commit",
                   {"emp_id": "EMP01", "rows": [new_row]}, role="employee", emp_id="EMP01")
        self.assertEqual(self._master_club(hist_id)["record_origin"], "imported")
        self.assertEqual(self._master_club(new_id)["record_origin"], "created")

    # ================= UI markup locks =================
    def test_admin_ui_has_migration_gate_and_clubs_panel(self):
        req = urllib.request.Request(f"{self.base_url}/admin")
        try:
            with urllib.request.urlopen(req) as resp:
                html = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            html = e.read().decode("utf-8")
        for marker in (
            'id="migration-gate-modal"', "unlockMigrationGate", 'id="migration-modal"',
            "Bulk Club History Upload", "handleMigClubFile", "runMigClubDryRun",
            "commitMigClubHistory", "/api/admin/migration/clubs/validate",
            "/api/admin/migration/clubs/commit", 'id="mig-club-preview"',
        ):
            self.assertIn(marker, html)

    def test_employee_ui_states_new_work_door(self):
        req = urllib.request.Request(f"{self.base_url}/employee")
        try:
            with urllib.request.urlopen(req) as resp:
                html = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            html = e.read().decode("utf-8")
        for marker in ("Bulk Add New Clubs", "NEW clubs only", "Data Migration portal"):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
