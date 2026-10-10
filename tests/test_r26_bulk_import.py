"""
R26 (as re-purposed by R31 "two doors") — EMPLOYEE bulk CSV import = NEW WORK —
LOCK TESTS.

R31 split club entry into two doors: the EMPLOYEE bulk door records NEW clubs
only (counted live), while historical / pre-system clubs are imported by the
ADMIN through the Data Migration portal (Bulk Club History Upload) as history
(counters unchanged) — covered in tests/test_r31_two_doors.py.

Locked here:
  * dry-run reports per-row status and writes NOTHING
  * historical (old-looking) dates are REFUSED with a pointer to the migration portal
  * duplicate reg-no / club-id blocked against the master DB AND within the batch
  * commit creates rows as NEW work: record_origin="created", auto-stamped dates,
    counted live (quota increments)
  * invalid rows are reported, never created
  * batch limit 200 rows
  * auth: employee session required
  * durable-sync confirmation reported (batched)
  * UI markup locks + anti-regression pins (r24/r25 surfaces intact)

NOTE: ids are UNIQUE PER RUN (timestamp tag) — bulk commit blocks existing club
ids/reg-nos by design, so fixed ids would fail on a second run against the same
data store (measured: created=0). This also keeps PA re-runs safe.
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
from db.schemas import CLUB_FIELDS, QUOTA_FIELDS
from config import MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV


class TestR26BulkImport(unittest.TestCase):
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
    def _token(self, role="employee", emp_id="EMP01"):
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

    def _post(self, path, payload, token=None, role="employee", emp_id="EMP01"):
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
        """Unique-per-run club id (digits only): 26 + tag + n."""
        return "26" + self.tag + str(n)

    def _row(self, cid, **kw):
        # R31 two-doors: the EMPLOYEE bulk door records NEW work only, so the
        # default row carries NO historical dates (dates are auto-stamped). Pass
        # date_of_approval / last_renewal_date explicitly to build a historical
        # (old-looking) row — those are refused here with a pointer to the Admin
        # Data Migration portal (covered in tests/test_r31_two_doors.py).
        b = {
            "club_id": cid,
            "reg_no": "REG-BULK-" + cid,
            "institution_name": "Bulk New College " + cid,
            "state": "West Bengal",
            "patron_email": "patron@bulk.edu",
            "president_email": "pres@bulk.edu",
            "secretary_email": "sec@bulk.edu",
        }
        b.update(kw)
        return b

    @staticmethod
    def _master_count():
        return len(CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS))

    # ---------- 1: dry-run is read-only + per-row report ----------
    def test_dry_run_reports_per_row_and_writes_nothing(self):
        before = self._master_count()
        c_ok, c_hist, c_noname = self._cid("01"), self._cid("02"), self._cid("03")
        rows = [
            self._row(c_ok),                                          # valid new work
            self._row(c_hist, date_of_approval="2018-01-01"),        # historical -> refused
            self._row(c_noname, institution_name=""),                 # missing name
        ]
        status, data = self._post("/api/clubs/bulk-import/validate",
                                  {"emp_id": "EMP01", "rows": rows})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["valid"], 1)
        self.assertEqual(data["invalid"], 2)
        # consequence states the door semantics
        self.assertIn("NEW WORK", data.get("consequence", ""))
        by_cid = {r["club_id"]: r for r in data["results"]}
        self.assertEqual(by_cid[c_ok]["status"], "ready")
        self.assertEqual(by_cid[c_hist]["status"], "error")
        # historical dates are refused with a pointer to the migration portal
        self.assertTrue(any("Data Migration" in e for e in by_cid[c_hist]["errors"]), data)
        self.assertEqual(by_cid[c_noname]["status"], "error")
        self.assertTrue(any("Institution Name" in e for e in by_cid[c_noname]["errors"]), data)
        # NOTHING written
        self.assertEqual(self._master_count(), before)

    # ---------- 2: duplicate detection ----------
    def test_dry_run_detects_duplicates(self):
        c_exist, c_base, c_dupid = self._cid("04"), self._cid("05"), self._cid("06")
        c_regn1, c_regn2 = self._cid("07"), self._cid("08")
        exist_reg = "REG-BULK-EXIST-" + self.tag
        shared_reg = "REG-BULK-SHARED-" + self.tag
        # a real club first
        status, _ = self._post("/api/clubs/bulk-import/commit",
                               {"emp_id": "EMP01", "rows": [self._row(c_exist, reg_no=exist_reg)]})
        self.assertEqual(status, 200)
        # vs-DB dup reg_no + within-batch dup club_id + within-batch dup reg_no
        batch = [
            self._row(c_dupid, reg_no=exist_reg),                 # dup vs DB
            self._row(c_base, reg_no=shared_reg),                 # ok (first use)
            self._row(c_base, reg_no="REG-BULK-X-" + self.tag),   # dup club_id in batch
            self._row(c_regn1, reg_no=shared_reg),                # dup reg in batch
            self._row(c_regn2, reg_no=shared_reg),                # dup reg in batch
        ]
        status, data = self._post("/api/clubs/bulk-import/validate", {"emp_id": "EMP01", "rows": batch})
        self.assertEqual(status, 200, data)
        self.assertTrue(data.get("valid", 0) >= 1, data)

        def errs_of(cid):
            return [e for r in data["results"] if r["club_id"] == cid for e in r["errors"]]

        self.assertTrue(any("already approved" in e for e in errs_of(c_dupid)), data)
        self.assertTrue(any("Duplicate Club ID" in e for e in errs_of(c_base)), data)
        dup_reg_errors = [e for r in data["results"] for e in r["errors"]
                          if "Duplicate Registration Number" in e]
        self.assertTrue(dup_reg_errors, data)

    # ---------- 3/4: commit ----------
    def test_commit_creates_new_work_rows_counted_live(self):
        def _quota():
            for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS):
                if q.get("emp_id") == "EMP01":
                    return int(q.get("clubs_approved_count", "0") or "0")
            return 0

        q_before = _quota()
        c1_id, c2_id = self._cid("10"), self._cid("11")
        rows = [
            self._row(c1_id),
            self._row(c2_id),
        ]
        status, data = self._post("/api/clubs/bulk-import/commit", {"emp_id": "EMP01", "rows": rows})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["created"], 2)
        self.assertIn("cloud_sync_confirmed", data)
        self.assertIn("NEW WORK", data.get("consequence", ""))
        by_cid = {r["club_id"]: r for r in data["results"]}
        self.assertEqual(by_cid[c1_id]["status"], "created")
        self.assertEqual(by_cid[c2_id]["status"], "created")
        master = {r["club_id"]: r for r in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)}
        c1, c2 = master[c1_id], master[c2_id]
        # R31 two-doors: the employee door records NEW work -> provenance "created",
        # dates auto-stamped (not smuggled historical dates), and COUNTED live.
        self.assertEqual(c1["record_origin"], "created")
        self.assertEqual(c2["record_origin"], "created")
        self.assertTrue(c1["date_of_approval"], c1)   # auto-stamped
        self.assertTrue(c1["renewal_date"], c1)       # derived
        # quota counts the two approvals (new work is counted live)
        self.assertEqual(_quota(), q_before + 2)

    def test_commit_skips_invalid_rows_and_reports(self):
        c_ok, c_bad = self._cid("12"), self._cid("13")
        rows = [
            self._row(c_ok),                                        # valid new work
            self._row(c_bad, date_of_approval="2020-01-01"),        # historical -> refused
        ]
        status, data = self._post("/api/clubs/bulk-import/commit", {"emp_id": "EMP01", "rows": rows})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["created"], 1)
        by_cid = {r["club_id"]: r for r in data["results"]}
        self.assertEqual(by_cid[c_ok]["status"], "created")
        self.assertEqual(by_cid[c_bad]["status"], "error")
        master = {r["club_id"]: r for r in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)}
        self.assertIn(c_ok, master)
        self.assertNotIn(c_bad, master)

    # ---------- 5: batch limit ----------
    def test_batch_limit_200(self):
        rows = [self._row(self._cid("9%02d" % (i % 100)), reg_no="REG-LIMIT-%s-%d" % (self.tag, i))
                for i in range(201)]
        status, data = self._post("/api/clubs/bulk-import/validate", {"emp_id": "EMP01", "rows": rows})
        self.assertEqual(status, 422)
        self.assertIn("200", str(data.get("message", "")))

    # ---------- 6: auth ----------
    def test_auth_required(self):
        status, _ = self._post("/api/clubs/bulk-import/validate",
                               {"emp_id": "EMP01", "rows": [self._row(self._cid("19"))]}, token="")
        self.assertIn(status, (401, 403))

    # ---------- 8: UI markup locks ----------
    def test_ui_markup_locks(self):
        status, html = self._get_raw("/employee")
        self.assertEqual(status, 200)
        for marker in (
            'id="btn-open-bulk-import"', "openBulkImportModal", 'id="bulk-import-modal"',
            "downloadBulkTemplate", "parseBulkCsv", "handleBulkFile", "runBulkDryRun",
            "commitBulkImport", 'id="btn-bulk-commit"', 'id="bulk-preview"',
            'id="bulk-csv-file"', "/api/clubs/bulk-import/validate",
            "/api/clubs/bulk-import/commit", "ndli_bulk_import_template.csv",
            "date_of_approval,last_renewal_date",
        ):
            self.assertIn(marker, html)
        # Esc ladder + backdrop know the modal
        self.assertIn("closeBulkImportModal();", html)
        self.assertIn('overlay.id === "bulk-import-modal"', html)

    # ---------- 9: anti-regression pins ----------
    def test_anti_regression_pins(self):
        status, html = self._get_raw("/employee")
        self.assertEqual(status, 200)
        # r24 import-mode surfaces intact
        self.assertIn('id="btn-open-sec-c-import"', html)
        self.assertIn('id="sec-c-import-fields"', html)
        self.assertIn("updateImportPreview", html)
        # older pinned strings intact
        self.assertIn('id="c-timestamp-display"', html)
        self.assertIn("c-renewal-display", html)
        self.assertIn("renew-check-conditions", html)
        self.assertIn("btn-renewal-approved", html)
        self.assertIn("Renewal Approved", html)


if __name__ == "__main__":
    unittest.main()
