"""
R24 — "Import existing club" (SEC-C historical date entry) — LOCK TESTS.

Business rules (user-confirmed 2026-10-08):
  1. Renewal anchor = last renewal date, or original approval date if never
     renewed; upcoming renewal = anchor + 1 year (Renewal Protocol).
  2. Overdue on import is fine (truth-telling); the normal renewal cycle follows.
  3. Earliest allowed formation date = 2019-01-01.
  4. Reg numbers are fully free-form (REG_NO_PATTERN charset only).

Locked here:
  * import create preserves historical dates (never auto-stamps today)
  * import date validation (required DOA, 2019 bound, no future dates, ordering)
  * derived upcoming renewal (anchor rule) + record_origin provenance
  * new-mode create still auto-stamps; explicit dates are REJECTED there
  * duplicate reg-no blocked on import (existing behaviour pinned)
  * historical dates immutable on /api/clubs/update for every role
  * admin-only /api/clubs/correct-dates: validation + renewal recompute + logged
    "Data Correction" activity row
  * UI markup locks (two SEC-C entry buttons, historical dates group, admin
    correction block)
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
from db.sync_engine import SyncEngine
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS, ACTIVITY_FIELDS, validate_club_payload
from config import MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV


class TestR24ImportExisting(unittest.TestCase):
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

    def _get_raw(self, path, headers=None):
        req = urllib.request.Request(f"{self.base_url}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def _post(self, path, payload, role="admin", emp_id="EMP01"):
        token = self._token(role, emp_id)
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

    @staticmethod
    def _club_payload(cid, **kw):
        b = {
            "emp_id": "EMP01",
            "club_id": cid,
            "reg_no": "REG-" + cid,
            "institution_name": "Import Test College " + cid,
            "state": "Gujarat",
            "patron_email": "patron@r24.edu",
            "president_email": "pres@r24.edu",
            "secretary_email": "sec@r24.edu",
        }
        b.update(kw)
        return b

    # ---------- 1/2/3/4/5: import create + validation ----------
    def test_import_create_preserves_historical_dates(self):
        """A 2024 club renewed in 2025 must keep BOTH real dates and derive 2026 renewal."""
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242401", record_mode="import",
            date_of_approval="2024-06-15", last_renewal_date="2025-07-20"))
        self.assertEqual(status, 200, data)
        club = data["club"]
        self.assertTrue(club["date_of_approval"].startswith("2024-06-15"), club["date_of_approval"])
        self.assertTrue(club["last_renewal_date"].startswith("2025-07-20"), club["last_renewal_date"])
        self.assertEqual(club["renewal_date"], "2026-07-20")
        self.assertEqual(club["next_renewal_date"], "2026-07-20")
        self.assertEqual(club["record_origin"], "imported")
        # entry-time metadata convention: submission_timestamp mirrors DOA (legacy alias)
        self.assertEqual(club["submission_timestamp"], club["date_of_approval"])

    def test_import_requires_formation_date(self):
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242402", record_mode="import", last_renewal_date="2025-07-20"))
        self.assertEqual(status, 422)
        self.assertTrue(any("Date of Approval" in e for e in data.get("validation_errors", [])), data)

    def test_import_formation_date_bounds(self):
        # before 2019 -> 422 (business rule 3)
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242403", record_mode="import", date_of_approval="2018-12-31"))
        self.assertEqual(status, 422)
        self.assertTrue(any("2019-01-01" in e for e in data.get("validation_errors", [])), data)
        # future -> 422
        from datetime import date
        future_s = date.fromordinal(datetime.now(timezone.utc).date().toordinal() + 30).isoformat()
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242404", record_mode="import", date_of_approval=future_s))
        self.assertEqual(status, 422)
        self.assertTrue(any("future" in e for e in data.get("validation_errors", [])), data)

    def test_import_last_renewal_bounds(self):
        # lrd before doa -> 422
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242405", record_mode="import",
            date_of_approval="2024-06-15", last_renewal_date="2024-06-14"))
        self.assertEqual(status, 422)
        self.assertTrue(any("Last Renewal Date" in e for e in data.get("validation_errors", [])), data)
        # lrd in the future -> 422
        from datetime import date
        future_s = date.fromordinal(datetime.now(timezone.utc).date().toordinal() + 30).isoformat()
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242406", record_mode="import",
            date_of_approval="2024-06-15", last_renewal_date=future_s))
        self.assertEqual(status, 422)

    def test_import_upcoming_renewal_anchor_rule(self):
        """Business rule 1: never-renewed club anchors on formation; renewed club on LRD."""
        # never renewed -> formation + 1y (and yes, it can land overdue = rule 2, fine)
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242407", record_mode="import", date_of_approval="2024-01-10"))
        self.assertEqual(status, 200, data)
        self.assertEqual(data["club"]["renewal_date"], "2025-01-10")
        self.assertEqual(data["club"]["last_renewal_date"], "")
        # renewed -> lrd + 1y
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242408", record_mode="import",
            date_of_approval="2024-01-10", last_renewal_date="2025-01-12"))
        self.assertEqual(status, 200, data)
        self.assertEqual(data["club"]["renewal_date"], "2026-01-12")

    # ---------- 6/7/8: new-mode contract ----------
    def test_new_mode_auto_stamps_and_origin_created(self):
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242409", record_mode="new"))
        self.assertEqual(status, 200, data)
        club = data["club"]
        today = datetime.now(timezone.utc).date().isoformat()
        self.assertTrue(club["date_of_approval"].startswith(today), club["date_of_approval"])
        self.assertEqual(club["last_renewal_date"], "")
        self.assertEqual(club["record_origin"], "created")

    def test_new_mode_rejects_explicit_dates(self):
        """No smuggling historical dates through the new-club path."""
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242410", record_mode="new", date_of_approval="2024-06-15"))
        self.assertEqual(status, 422)
        self.assertTrue(any("Import existing club" in e for e in data.get("validation_errors", [])), data)
        # legacy (no record_mode) with dates is equally rejected
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242411", date_of_approval="2024-06-15"))
        self.assertEqual(status, 422)

    def test_unknown_record_mode_rejected(self):
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242412", record_mode="bogus"))
        self.assertEqual(status, 422)
        self.assertTrue(any("record_mode" in e for e in data.get("validation_errors", [])), data)

    # ---------- 9: duplicate reg-no pinned ----------
    def test_duplicate_reg_no_blocked_on_import(self):
        status, _ = self._post("/api/clubs/create", self._club_payload(
            "242413", reg_no="REG-R24-DUP", record_mode="import", date_of_approval="2024-02-02"))
        self.assertEqual(status, 200)
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242414", reg_no="REG-R24-DUP", record_mode="import", date_of_approval="2023-03-03"))
        self.assertEqual(status, 409)
        self.assertIn("DUPLICATE", str(data.get("message", "")))

    # ---------- 10/11: update-path immutability ----------
    def test_non_admin_update_strips_date_fields(self):
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242415", record_mode="import", date_of_approval="2024-05-05"))
        self.assertEqual(status, 200, data)
        original = data["club"]["date_of_approval"]
        status, data = self._post("/api/clubs/update", {
            "emp_id": "EMP01", "club_id": "242415",
            "date_of_approval": "2020-01-01", "last_renewal_date": "2021-01-01",
            "institution_name": "Import Test College 242415 (Renamed)",
        }, role="employee", emp_id="EMP01")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["club"]["date_of_approval"], original)
        self.assertEqual(data["club"]["last_renewal_date"], "")
        self.assertEqual(data["club"]["institution_name"], "Import Test College 242415 (Renamed)")

    def test_admin_update_cannot_change_dates(self):
        """Historical dates are immutable on the general update path for EVERY role."""
        status, data = self._post("/api/clubs/create", self._club_payload(
            "242416", record_mode="import", date_of_approval="2024-04-04"))
        self.assertEqual(status, 200, data)
        original = data["club"]["date_of_approval"]
        status, data = self._post("/api/clubs/update", {
            "emp_id": "EMP01", "club_id": "242416", "date_of_approval": "2020-01-01"})
        self.assertEqual(status, 422)
        self.assertTrue(any("correct-dates" in e for e in data.get("validation_errors", []))
                        or "correct-dates" in str(data.get("message", "")), data)
        rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        row = next(r for r in rows if r.get("club_id") == "242416")
        self.assertEqual(row.get("date_of_approval"), original)

    # ---------- 12: admin correction workflow ----------
    def test_admin_date_correction_workflow(self):
        status, data = self._post("/api/clubs/create", self._club_payload("242417", record_mode="new"))
        self.assertEqual(status, 200, data)
        status, data = self._post("/api/clubs/correct-dates", {
            "club_id": "242417",
            "date_of_approval": "2024-03-05",
            "last_renewal_date": "2025-03-06"})
        self.assertEqual(status, 200, data)
        club = data["club"]
        self.assertTrue(club["date_of_approval"].startswith("2024-03-05"))
        self.assertTrue(club["last_renewal_date"].startswith("2025-03-06"))
        self.assertEqual(club["renewal_date"], "2026-03-06")  # anchor: LRD + 1y
        # logged correction activity row
        acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        hit = [a for a in acts if a.get("club_id") == "242417"
               and a.get("support_type") == "Data Correction"]
        self.assertTrue(hit, "expected a 'Data Correction' activity row")
        self.assertIn("corrected historical dates", hit[-1].get("notes", ""))
        # validation on the correction path
        status, data = self._post("/api/clubs/correct-dates", {
            "club_id": "242417", "date_of_approval": "2030-01-01"})
        self.assertEqual(status, 422)
        # employees are not allowed
        status, data = self._post("/api/clubs/correct-dates", {
            "club_id": "242417", "date_of_approval": "2024-03-05"}, role="employee", emp_id="EMP01")
        self.assertEqual(status, 403)
        # missing club -> 404
        status, data = self._post("/api/clubs/correct-dates", {
            "club_id": "999999999", "date_of_approval": "2024-03-05"})
        self.assertEqual(status, 404)

    # ---------- 13: UI markup locks ----------
    def test_ui_markup_locks(self):
        status, html_emp = self._get_raw("/employee")
        self.assertEqual(status, 200)
        for marker in ("btn-open-sec-c-import", "sec-c-import-fields", "c-formation-date",
                       "c-last-renewal-date", "c-upcoming-preview", "sec-c-mode-badge",
                       "2019-01-01", "toggleSecC('import')", "updateImportPreview",
                       "record_mode"):
            self.assertIn(marker, html_emp)
        status, html_adm = self._get_raw("/admin")
        self.assertEqual(status, 200)
        for marker in ("submitClubDateCorrection", "cd-date-of-approval", "cd-last-renewal",
                       "Correct Historical Dates", "/api/clubs/correct-dates"):
            self.assertIn(marker, html_adm)

    # ---------- unit: validator contract ----------
    def test_validate_club_payload_mode_aware(self):
        base = self._club_payload("242418")
        errors = validate_club_payload(dict(base, record_mode="import",
                                            date_of_approval="2024-06-15"))
        self.assertEqual(errors, [])
        errors = validate_club_payload(dict(base, record_mode="import"))
        self.assertTrue(any("required" in e for e in errors))
        errors = validate_club_payload(dict(base, record_mode="new",
                                            last_renewal_date="2024-01-01"))
        self.assertTrue(any("Import existing club" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
