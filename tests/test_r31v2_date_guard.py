"""
R31v2 DATE GUARD — LOCK TESTS (Issue-1, 2026-10-10).

Bug reported by the user: a bulk CSV at the EMPLOYEE door (EMP01 portal) carrying
clubs with approval dates 10.10.2026 (today) and 11.10.2026 (tomorrow) was refused
with "Historical (past) dates are not accepted here…" — but those dates are NOT
historical. The guard rejected ANY explicit date instead of checking its value.

Intended contract (fix):
  * The employee door records NEW clubs. Explicit dates are ACCEPTED when they are
    not in the past (today or later) — in any of the accepted CSV formats
    (YYYY-MM-DD, YYYY/MM/DD, DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY).
  * Only genuinely PAST dates are refused, with the pointer to the Admin Data
    Migration portal (Bulk Club History Upload).
  * Malformed dates get a FORMAT error (never the misleading "historical" blame).
  * last_renewal_date may not precede date_of_approval.
  * Accepted dates are NORMALIZED to ISO (YYYY-MM-DD) before storage, so the club
    record never carries dotted/slash dates (year filters read date[:4]).
  * The HISTORY door (Admin Data Migration) also accepts the dotted/slash formats
    (client worksheet convention) and normalizes to ISO.

NOTE: ids are UNIQUE PER RUN (timestamp tag); dates are computed relative to the
server's UTC "today" so the suite is deterministic any day it runs.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
import threading
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS
from config import (
    MASTER_CLUBS_CSV,
    DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD,
)


class TestR31v2DateGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.tag = str(int(datetime.now(timezone.utc).timestamp() * 1000))[-5:]
        cls.today = datetime.now(timezone.utc).date()

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
        return "32" + self.tag + str(n)

    def _club_row(self, cid, emp="EMP01", **kw):
        b = {
            "club_id": cid,
            "reg_no": "REG-R31V2-" + cid,
            "institution_name": "R31v2 Date Guard College " + cid,
            "state": "West Bengal",
            "patron_email": "patron@r31v2.edu",
            "president_email": "pres@r31v2.edu",
            "secretary_email": "sec@r31v2.edu",
            "approved_by_emp_id": emp,
        }
        b.update(kw)
        return b

    def _validate(self, row, emp="EMP01"):
        status, data = self._post("/api/clubs/bulk-import/validate",
                                  {"emp_id": emp, "rows": [row]}, role="employee", emp_id=emp)
        self.assertEqual(status, 200, data)
        return data["results"][0]

    def _master_club(self, cid):
        return CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", cid, CLUB_FIELDS, copy=False)

    # ================= the reported bug: today / tomorrow must be accepted =================
    def test_employee_door_accepts_todays_date_iso(self):
        r = self._validate(self._club_row(
            self._cid("1"), date_of_approval=self.today.isoformat()))
        self.assertEqual(r["status"], "ready", r)

    def test_employee_door_accepts_tomorrow_dotted(self):
        # EXACT Issue-1 shape: "11.10.2026" (day-first dotted) = tomorrow.
        tomorrow = self.today + timedelta(days=1)
        r = self._validate(self._club_row(
            self._cid("2"), date_of_approval=tomorrow.strftime("%d.%m.%Y")))
        self.assertEqual(r["status"], "ready", r)

    def test_employee_door_accepts_today_dotted(self):
        # EXACT Issue-1 shape: "10.10.2026" (day-first dotted) = today.
        r = self._validate(self._club_row(
            self._cid("3"), date_of_approval=self.today.strftime("%d.%m.%Y")))
        self.assertEqual(r["status"], "ready", r)

    def test_employee_door_accepts_slash_dayfirst(self):
        r = self._validate(self._club_row(
            self._cid("4"), date_of_approval=self.today.strftime("%d/%m/%Y")))
        self.assertEqual(r["status"], "ready", r)

    # ================= only GENUINELY past dates are refused =================
    def test_employee_door_refuses_yesterday_with_pointer(self):
        yesterday = self.today - timedelta(days=1)
        r = self._validate(self._club_row(
            self._cid("5"), date_of_approval=yesterday.strftime("%d.%m.%Y")))
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(any("Data Migration" in e for e in r["errors"]), r)
        self.assertTrue(any("Bulk Club History Upload" in e for e in r["errors"]), r)

    def test_employee_door_refuses_old_iso_date_with_pointer(self):
        r = self._validate(self._club_row(
            self._cid("6"), date_of_approval="2021-03-04"))
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(any("Data Migration" in e for e in r["errors"]), r)

    def test_employee_door_refuses_past_last_renewal(self):
        # A past LAST RENEWAL is historical too — even with no approval date.
        r = self._validate(self._club_row(
            self._cid("7"), last_renewal_date=(self.today - timedelta(days=3)).isoformat()))
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(any("Data Migration" in e for e in r["errors"]), r)

    # ================= format problems are NOT blamed on history =================
    def test_malformed_date_gets_format_error_not_historical_blame(self):
        r = self._validate(self._club_row(
            self._cid("8"), date_of_approval="not-a-date"))
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(any("valid date" in e for e in r["errors"]), r)
        self.assertFalse(any("Data Migration" in e for e in r["errors"]),
                         "a format problem must not be blamed on history: %s" % r)

    def test_last_renewal_before_approval_is_refused(self):
        r = self._validate(self._club_row(
            self._cid("9"),
            date_of_approval=(self.today + timedelta(days=2)).isoformat(),
            last_renewal_date=self.today.isoformat()))
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(any("cannot be earlier" in e for e in r["errors"]), r)

    # ================= storage: accepted dates land as ISO =================
    def test_commit_normalizes_dotted_date_to_iso_and_counts_live(self):
        from db.sync_engine import SyncEngine
        SyncEngine.recompute_and_persist_quota("EMP01")
        tomorrow = self.today + timedelta(days=1)
        cid = self._cid("10")
        row = self._club_row(cid, date_of_approval=tomorrow.strftime("%d.%m.%Y"))
        status, data = self._post("/api/clubs/bulk-import/commit",
                                  {"emp_id": "EMP01", "rows": [row]},
                                  role="employee", emp_id="EMP01")
        self.assertEqual(status, 200, data)
        self.assertEqual(data.get("created"), 1, data)
        club = self._master_club(cid)
        self.assertEqual(club["record_origin"], "created", club)
        self.assertEqual(club["date_of_approval"], tomorrow.isoformat(),
                         "dotted CSV dates must be stored as ISO: %s" % club)
        self.assertEqual(data["results"][0].get("date_of_approval"), tomorrow.isoformat(), data)

    def test_history_door_accepts_and_normalizes_dotted_dates(self):
        cid = self._cid("11")
        row = self._club_row(cid, date_of_approval="04.03.2021", last_renewal_date="04.03.2024")
        status, data = self._post("/api/admin/migration/clubs/commit",
                                  {"rows": [row], "password": DEFAULT_ADMIN_PASSWORD})
        self.assertEqual(status, 200, data)
        club = self._master_club(cid)
        self.assertEqual(club["record_origin"], "imported", club)
        self.assertEqual(club["date_of_approval"], "2021-03-04", club)
        self.assertEqual(club["last_renewal_date"], "2024-03-04", club)

    # ================= UI wording pins =================
    def test_employee_ui_documents_the_date_contract(self):
        req = urllib.request.Request(f"{self.base_url}/employee")
        try:
            with urllib.request.urlopen(req) as resp:
                html = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            html = e.read().decode("utf-8")
        modal = html[html.index('id="bulk-import-modal"'):]
        modal = modal[:4000]
        self.assertIn("DD.MM.YYYY", modal,
                      "the bulk modal must document the accepted date formats")
        self.assertIn("Bulk Club History Upload", modal,
                      "the bulk modal must keep the pointer to the history door")
        self.assertIn("approved_by_emp_id", modal,
                      "the bulk modal must keep documenting the attribution column")


if __name__ == "__main__":
    unittest.main()
