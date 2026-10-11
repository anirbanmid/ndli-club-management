"""
R34 "Hard Reset (Handover)" lock tests.

The hard reset replaces the old "Reset Test Data" flow (user spec 2026-10-11):
- BLANK-BUT-PROVISIONED: ALL data is wiped (master clubs/activities/quotas/
  issues + migrated-history baselines, every node's clubs/activity_log/issues,
  Robu's data logs, sync_issues.log) and NOTHING is reseeded;
- the provisioned skeleton SURVIVES: the Master Admin + the 7 Nodal Officer
  accounts (master_users.csv) and every node's credentials.csv, passwords
  untouched;
- TRIPLE security: typed confirmation phrase + Master Admin password + the
  owner-only handover PIN (the server keeps only a SHA-256 digest — the PIN
  digits appear NOWHERE in the repository);
- the pre-reset safety checkpoint is mandatory (abort if unwritable);
- the old "Reset Test Data" button + endpoint are GONE.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from app import NDLIRequestHandler, HANDOVER_PIN_SHA256
from init_db import initialize_database
from config import (BASE_DIR, DATA_DIR, MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV,
                    MASTER_QUOTAS_CSV, MASTER_ISSUES_CSV, MASTER_USERS_CSV,
                    MASTER_DATA_DIR, EMPLOYEE_NODES_DIR, DEFAULT_ADMIN_PASSWORD)
from db.backup_engine import BackupEngine
from db.csv_engine import CSVEngine
from db.migration_engine import MASTER_HISTORY_CSV
from db.schemas import (CLUB_FIELDS, ACTIVITY_FIELDS, QUOTA_FIELDS, ISSUE_FIELDS,
                        USER_FIELDS, MIGRATION_HISTORY_FIELDS)
from db.sync_engine import SyncEngine

# Test-only PIN stand-in: tests patch app.HANDOVER_PIN_SHA256 with THIS digest,
# so the REAL owner-only handover PIN appears nowhere in the repository.
TEST_PIN = "123456"
TEST_PIN_SHA256 = hashlib.sha256(TEST_PIN.encode("utf-8")).hexdigest()
WRONG_PIN = "999999"

SCRATCH_CLUB_ID = "NDLI-SCRATCH-R34"
MARKER = "SCRATCHR34"
SCRATCH_CLUB = {
    "club_id": SCRATCH_CLUB_ID,
    "reg_no": "REG-SCRATCH-R34",
    "institution_name": f"{MARKER} Hard Reset Test Institute",
    "state": "Delhi",
    "zone": "North",
    "patron_email": "patron@scratch.test",
    "president_email": "president@scratch.test",
    "secretary_email": "secretary@scratch.test",
    "date_of_approval": "2026-01-01T00:00:00Z",
    "last_renewal_date": "",
    "renewal_date": "2027-01-01",
    "status": "Approved",
    "approved_by_emp_id": "EMP01",
    "updated_at": "2026-01-01T00:00:00Z",
    "submission_timestamp": "2026-01-01T00:00:00Z",
    "next_renewal_date": "2027-01-01",
}

ASSISTANT_LOGS = [DATA_DIR / n for n in (
    "assistant_interactions.csv", "assistant_preferences.csv", "assistant_feedback.csv")]


class TestHardResetHandover(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _post(self, path, payload, use_token=True, pin=TEST_PIN):
        token = ""
        if use_token:
            from auth_util import admin_token
            token = admin_token(self.base_url, self.__class__.__name__)
        body = dict(payload)
        if pin is not None:
            body["pin"] = pin
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def _hard_reset(self, **overrides):
        payload = {"confirm": "HARD-RESET-FOR-HANDOVER",
                   "password": DEFAULT_ADMIN_PASSWORD}
        payload.update(overrides)
        with mock.patch("app.HANDOVER_PIN_SHA256", TEST_PIN_SHA256):
            return self._post("/api/admin/data/hard-reset", payload)

    @staticmethod
    def _snapshot_store():
        """Byte snapshot of every store CSV (master + nodes + Robu's logs)."""
        snaps = {}
        for base in (MASTER_DATA_DIR, EMPLOYEE_NODES_DIR):
            for f in base.rglob("*.csv"):
                snaps[f] = f.read_bytes()
        for p in ASSISTANT_LOGS:
            if p.exists():
                snaps[p] = p.read_bytes()
        return snaps

    @staticmethod
    def _restore_store(snaps):
        """Return the store to the exact pre-test bytes (incl. deleting new files)."""
        for base in (MASTER_DATA_DIR, EMPLOYEE_NODES_DIR):
            for f in base.rglob("*.csv"):
                if f not in snaps and f.exists():
                    f.unlink()
        for f, blob in snaps.items():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(blob)

    @staticmethod
    def _node_csv(emp_id, name):
        return EMPLOYEE_NODES_DIR / emp_id / name

    def _seed_scratch(self):
        """Plant one scratch row in every data family the reset must wipe."""
        CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", dict(SCRATCH_CLUB))
        CSVEngine.upsert_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, "activity_id", {
            "activity_id": f"{MARKER}-ACT", "club_id": SCRATCH_CLUB_ID, "emp_id": "EMP01",
            "activity_type": "Online Training", "support_type": "Online Training",
            "activity_date": "2026-01-02", "notes": MARKER, "created_at": "2026-01-02T00:00:00Z"})
        CSVEngine.upsert_row(MASTER_QUOTAS_CSV, QUOTA_FIELDS, "emp_id", {
            "emp_id": "EMP01", "total_clubs": 1, "support_count": 0, "notes": MARKER})
        CSVEngine.upsert_row(MASTER_ISSUES_CSV, ISSUE_FIELDS, "issue_id", {
            "issue_id": f"{MARKER}-ISSUE", "club_id": SCRATCH_CLUB_ID, "emp_id": "EMP01",
            "institution_name": MARKER, "state": "Delhi", "zone": "North",
            "issue_note": MARKER, "status": "Unresolved",
            "created_at": "2026-01-02T00:00:00Z"})
        CSVEngine.upsert_row(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS, "hist_id", {
            "hist_id": f"{MARKER}-HIST", "emp_id": "EMP01", "period_year": "2021",
            "period_month": "01", "period_week": "", "task_type": "Club Support",
            "approvals_count": "1", "support_count": "1", "online_workshops_count": "0",
            "user_registrations_count": "0", "local_events_count": "0",
            "legacy_online_workshops_count": "0"})
        node_issue = self._node_csv("emp01", "issues.csv")
        if node_issue.exists():
            CSVEngine.upsert_row(node_issue, ISSUE_FIELDS, "issue_id", {
                "issue_id": f"{MARKER}-NODEISSUE", "club_id": SCRATCH_CLUB_ID, "emp_id": "EMP01",
                "institution_name": MARKER, "state": "Delhi", "zone": "North",
                "issue_note": MARKER, "status": "Unresolved",
                "created_at": "2026-01-02T00:00:00Z"})
        # Robu's data log: header + one scratch line is enough to prove truncation
        log = DATA_DIR / "assistant_interactions.csv"
        if log.exists():
            with log.open("a", encoding="utf-8") as fh:
                fh.write(f"{MARKER},EMP01,EMPLOYEE,scratch\n")
        else:
            log.write_text(f"timestamp_utc,user_id,role,details\n{MARKER},EMP01,EMPLOYEE,scratch\n",
                           encoding="utf-8")
        sync_log = DATA_DIR / "sync_issues.log"
        with sync_log.open("a", encoding="utf-8") as fh:
            fh.write(f"{MARKER} sync log line\n")

    @staticmethod
    def _row_count(path, fields):
        return len(CSVEngine.read_all(path, fields))

    # ------------------------------------------------------------------
    # wipe scope: blank-but-provisioned (the core contract)
    # ------------------------------------------------------------------
    def test_hard_reset_wipes_everything_but_the_accounts(self):
        snaps = self._snapshot_store()
        creds_before = {}
        for node in sorted(p for p in EMPLOYEE_NODES_DIR.iterdir() if p.is_dir()):
            c = node / "credentials.csv"
            if c.exists():
                creds_before[node.name] = c.read_bytes()
        users_before = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
        self._seed_scratch()
        ckpt_dir = None
        try:
            status, res = self._hard_reset()
            self.assertEqual(status, 200)
            self.assertTrue(res.get("success"))

            # BLANK: every data family is at zero rows
            self.assertEqual(self._row_count(MASTER_CLUBS_CSV, CLUB_FIELDS), 0)
            self.assertEqual(self._row_count(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS), 0)
            self.assertEqual(self._row_count(MASTER_QUOTAS_CSV, QUOTA_FIELDS), 0)
            self.assertEqual(self._row_count(MASTER_ISSUES_CSV, ISSUE_FIELDS), 0)
            self.assertEqual(self._row_count(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS), 0,
                             "Migrated-history baselines must NOT survive (nothing survives)")
            for node in ("emp01", "emp07"):
                self.assertEqual(self._row_count(self._node_csv(node, "clubs.csv"), CLUB_FIELDS), 0)
                self.assertEqual(self._row_count(self._node_csv(node, "activity_log.csv"), ACTIVITY_FIELDS), 0)
                self.assertEqual(self._row_count(self._node_csv(node, "issues.csv"), ISSUE_FIELDS), 0)
            for log in ASSISTANT_LOGS:
                if log.exists():
                    self.assertLessEqual(len(log.read_text(encoding="utf-8").splitlines()), 1,
                                         f"Robu's log must be reduced to its header: {log.name}")
            sync_log = DATA_DIR / "sync_issues.log"
            self.assertNotIn(MARKER, sync_log.read_text(encoding="utf-8") if sync_log.exists() else "")

            # NO RESEED: nothing was created
            self.assertFalse(res.get("reseeded"))
            self.assertEqual(res.get("accounts_kept"), len(users_before))

            # PROVISIONED: accounts + credentials byte-identical
            users_after = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            self.assertEqual(users_before, users_after,
                             "master_users.csv (admin + 7 officers) must be untouched")
            self.assertEqual(len(users_after), 8)
            for node, blob in creds_before.items():
                c = EMPLOYEE_NODES_DIR / node / "credentials.csv"
                self.assertTrue(c.exists(), f"credentials.csv must survive in {node}")
                self.assertEqual(c.read_bytes(), blob,
                                 f"credentials.csv in {node} must be byte-identical")

            # checkpoint identified for the handover runbook
            ckpt_id = res.get("checkpoint_backup_id", "")
            self.assertTrue(ckpt_id)
            ckpt_dir = BackupEngine.get_backup_dir() / ckpt_id
        finally:
            if ckpt_dir and ckpt_dir.exists():
                restore_res = BackupEngine.restore_backup(ckpt_dir)
                self.assertTrue(restore_res.get("success", True))
                SyncEngine.reconcile_all_nodes()
            self._restore_store(snaps)

    # ------------------------------------------------------------------
    # triple security: phrase + Master Admin password + handover PIN
    # ------------------------------------------------------------------
    def test_hard_reset_triple_security_enforced(self):
        rows_before = self._row_count(MASTER_CLUBS_CSV, CLUB_FIELDS)

        # No admin session -> 401 (even with every secret correct)
        st, _ = self._post("/api/admin/data/hard-reset",
                           {"confirm": "HARD-RESET-FOR-HANDOVER",
                            "password": DEFAULT_ADMIN_PASSWORD}, use_token=False)
        self.assertEqual(st, 401)

        # Wrong typed phrase -> 400 (layer 1 blocks)
        st, _ = self._hard_reset(confirm="hard-reset")
        self.assertEqual(st, 400)

        # Missing PIN -> 403 (layer 3 blocks before anything else)
        st, _ = self._post("/api/admin/data/hard-reset",
                           {"confirm": "HARD-RESET-FOR-HANDOVER",
                            "password": DEFAULT_ADMIN_PASSWORD}, pin=None)
        self.assertEqual(st, 403)

        # Wrong PIN -> 403 (layer 3 blocks even with phrase + password correct)
        with mock.patch("app.HANDOVER_PIN_SHA256", TEST_PIN_SHA256):
            st, _ = self._post("/api/admin/data/hard-reset",
                               {"confirm": "HARD-RESET-FOR-HANDOVER",
                                "password": DEFAULT_ADMIN_PASSWORD}, pin=WRONG_PIN)
        self.assertEqual(st, 403)

        # Missing password -> 401 (layer 2 blocks with phrase + PIN correct)
        st, _ = self._hard_reset(password="")
        self.assertEqual(st, 401)

        # Wrong password -> 403
        st, _ = self._hard_reset(password="definitely-wrong-pass")
        self.assertEqual(st, 403)

        self.assertEqual(self._row_count(MASTER_CLUBS_CSV, CLUB_FIELDS), rows_before,
                         "No rejected attempt may alter any data")

    # ------------------------------------------------------------------
    # PIN secrecy: one-way fingerprint only, digits never in the repository
    # ------------------------------------------------------------------
    def test_pin_is_stored_as_one_way_digest_only(self):
        app_src = (BASE_DIR / "app.py").read_text(encoding="utf-8")
        # R39: the hard-reset HANDLER moved to routes/data_admin.py (mechanical router
        # extraction) -- the source scan follows the code it pins, the constant stays
        # in app.py where the tests monkeypatch it.
        hard_reset_src = (BASE_DIR / "routes" / "data_admin.py").read_text(encoding="utf-8")
        admin_html = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        # The digest constant exists and is a real SHA-256 hex digest
        self.assertRegex(app_src, r'HANDOVER_PIN_SHA256 = "[0-9a-f]{64}"')
        # The server hashes whatever the user types — it never compares digits
        self.assertIn("sha256(pin", hard_reset_src)
        self.assertNotIn(HANDOVER_PIN_SHA256, admin_html,
                         "The digest must never be echoed into the browser page")
        # The PIN input ships with no preset value
        pin_lines = [ln for ln in admin_html.splitlines() if 'hard-reset-pin-input' in ln]
        self.assertTrue(pin_lines, "The hard-reset modal must contain the PIN field")
        for ln in pin_lines:
            self.assertNotIn('value="', ln, "The PIN field must never carry a preset value")

    # ------------------------------------------------------------------
    # the old Reset Test Data flow is gone; the Hard Reset UI is in place
    # ------------------------------------------------------------------
    def test_old_reset_test_data_removed_and_hard_reset_present(self):
        admin_html = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        for stale in ("Reset Test Data", "reset-test-data-modal", "RESET-ALL-TEST-DATA",
                      "openResetTestModal", "Wipe &amp; Reseed", "clubs_per_employee"):
            self.assertNotIn(stale, admin_html,
                             f"Old Reset Test Data UI must be gone: {stale}")
        for marker in ("Danger Zone — Hard Reset (Handover)", "openHardResetModal()",
                       "hard-reset-modal", "hard-reset-pin-input", "hard-reset-admin-password",
                       "HARD-RESET-FOR-HANDOVER", "Triple-Layer Security Verification",
                       "Perform Hard Reset"):
            self.assertIn(marker, admin_html,
                          f"Hard Reset UI must contain: {marker}")

    def test_old_reset_endpoint_gone(self):
        st, res = self._post("/api/admin/data/reset-test-data",
                             {"confirm": "RESET-ALL-TEST-DATA",
                              "password": DEFAULT_ADMIN_PASSWORD, "clubs_per_employee": 1})
        self.assertEqual(st, 404, "The old Reset Test Data endpoint must be removed")
        self.assertFalse(res.get("success", False))


if __name__ == "__main__":
    unittest.main()
