"""
Safety-net tests for destructive admin operations.

Verifies the automatic pre-destructive backup checkpoints:
- POST /api/admin/clubs/delete        -> takes a checkpoint before deleting
- POST /api/admin/data/reset-test-data -> takes a checkpoint before wiping
and that BOTH operations abort (leaving data untouched) when the safety
checkpoint cannot be written. Also verifies the rolling retention policy
keeps multiple archives (safety headroom beyond the historical 2).
"""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from app import NDLIRequestHandler
from init_db import initialize_database
from config import MASTER_CLUBS_CSV, EMPLOYEE_NODES_DIR
from db.backup_engine import BackupEngine, MAX_RETAINED_BACKUPS
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS
from db.sync_engine import SyncEngine

SCRATCH_CLUB_ID = "NDLI-SCRATCH-9001"
SCRATCH_ROW = {
    "club_id": SCRATCH_CLUB_ID,
    "reg_no": "REG-SCRATCH-9001",
    "institution_name": "Scratch Safety Test Institute",
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


class TestBackupSafetyCheckpoints(unittest.TestCase):

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
        # Leave the shared test database exactly as we found it
        try:
            SyncEngine.delete_club(SCRATCH_CLUB_ID)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _admin_token(self):
        from auth_util import admin_token
        return admin_token(self.base_url, self.__class__.__name__)

    def _post(self, path, payload, use_token=True):
        token = self._admin_token() if use_token else ""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def _get_json(self, path):
        token = self._admin_token()
        req = urllib.request.Request(self.base_url + path)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _seed_scratch_club():
        CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", dict(SCRATCH_ROW))

    @staticmethod
    def _scratch_club_exists():
        return CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", SCRATCH_CLUB_ID, CLUB_FIELDS, copy=False) is not None

    @staticmethod
    def _backup_ids():
        return [d.name for d in BackupEngine.get_existing_backups()]

    # ------------------------------------------------------------------
    # club delete: checkpoint + abort semantics
    # ------------------------------------------------------------------
    def test_club_delete_aborts_when_checkpoint_fails(self):
        """If the pre-delete checkpoint cannot be written, the delete must NOT happen."""
        self._seed_scratch_club()
        try:
            with mock.patch.object(BackupEngine, "create_backup", side_effect=OSError("simulated backup failure")):
                status, res = self._post("/api/admin/clubs/delete", {"club_id": SCRATCH_CLUB_ID})
            self.assertGreaterEqual(status, 500, "Checkpoint failure must surface as an error")
            self.assertFalse(res.get("success", False))
            self.assertIn("checkpoint", (res.get("message") or res.get("error") or "").lower())
            self.assertTrue(self._scratch_club_exists(),
                            "Club must remain untouched when the safety checkpoint fails")
        finally:
            try:
                SyncEngine.delete_club(SCRATCH_CLUB_ID)
            except Exception:
                pass

    def test_club_delete_takes_pre_delete_checkpoint(self):
        """A successful delete must leave a checkpoint capturing the pre-delete state."""
        self._seed_scratch_club()
        before = set(self._backup_ids())
        try:
            status, res = self._post("/api/admin/clubs/delete", {"club_id": SCRATCH_CLUB_ID})
            self.assertEqual(status, 200)
            self.assertTrue(res.get("success"))
            self.assertFalse(self._scratch_club_exists(), "Club must be deleted on success")

            ckpt_id = res.get("checkpoint_backup_id", "")
            self.assertTrue(ckpt_id, "Response must identify the pre-delete checkpoint")
            self.assertNotIn(ckpt_id, before, "A fresh checkpoint must have been created")
            manifest_file = BackupEngine.get_backup_dir() / ckpt_id / "manifest.json"
            self.assertTrue(manifest_file.exists())
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertIn("Checkpoint", manifest.get("note", ""))
            self.assertIn(SCRATCH_CLUB_ID, manifest.get("note", ""))
        finally:
            try:
                SyncEngine.delete_club(SCRATCH_CLUB_ID)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # data reset: checkpoint + abort semantics
    # ------------------------------------------------------------------
    def test_data_reset_aborts_when_checkpoint_fails(self):
        """If the pre-reset checkpoint cannot be written, the wipe must NOT happen."""
        before_rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        with mock.patch.object(BackupEngine, "create_backup", side_effect=OSError("simulated backup failure")):
            status, res = self._post("/api/admin/data/reset-test-data",
                                     {"confirm": "RESET-ALL-TEST-DATA", "clubs_per_employee": 1})
        self.assertGreaterEqual(status, 500, "Checkpoint failure must surface as an error")
        after_rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertEqual(len(after_rows), len(before_rows),
                         "Master data must remain untouched when the safety checkpoint fails")

    def test_data_reset_takes_pre_reset_checkpoint_and_restores(self):
        """A successful reset must leave a checkpoint from which the data can be restored."""
        before = set(self._backup_ids())
        ckpt_dir = None
        try:
            status, res = self._post("/api/admin/data/reset-test-data",
                                     {"confirm": "RESET-ALL-TEST-DATA", "clubs_per_employee": 1})
            self.assertEqual(status, 200)
            self.assertTrue(res.get("success"))

            # Regression: a reset must treat ONLY real zonal employees as seed
            # targets. An admin-owned seeded club (ADMIN01) breaks the invariant
            # Sum(quotas) == master total clubs (employee-vs-admin count mismatch).
            self.assertEqual(res.get("employees_reset"), 7,
                             "Reset must target exactly the 7 employees (never the admin account)")
            node_dirs = sorted(p.name for p in EMPLOYEE_NODES_DIR.iterdir() if p.is_dir())
            self.assertEqual(node_dirs, [f"emp0{i}" for i in range(1, 8)],
                             "No node directory may be provisioned for non-employee accounts")
            clubs_after = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            owners = {(c.get("approved_by_emp_id") or "").strip().upper() for c in clubs_after}
            self.assertTrue(owners <= {f"EMP0{i}" for i in range(1, 8)},
                            f"All master clubs must be employee-owned, found: {owners}")

            ckpt_id = res.get("checkpoint_backup_id", "")
            self.assertTrue(ckpt_id, "Response must identify the pre-reset checkpoint")
            self.assertNotIn(ckpt_id, before, "A fresh checkpoint must have been created")
            ckpt_dir = BackupEngine.get_backup_dir() / ckpt_id
            manifest = json.loads((ckpt_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("Test Data Reset", manifest.get("note", ""))
        finally:
            # Undo the wipe using the very checkpoint this feature created
            if ckpt_dir and ckpt_dir.exists():
                restore_res = BackupEngine.restore_backup(ckpt_dir)
                self.assertTrue(restore_res.get("success", True))
                SyncEngine.reconcile_all_nodes()

    # ------------------------------------------------------------------
    # retention policy intent
    # ------------------------------------------------------------------
    def test_retention_policy_keeps_multiple_weekly_archives(self):
        """Rolling retention must keep safety headroom beyond the historical 2 archives."""
        self.assertGreaterEqual(MAX_RETAINED_BACKUPS, 4,
                                "Retention must keep at least 4 archives (≈4 weeks of history)")
        status, data = self._get_json("/api/admin/backup/status")
        self.assertEqual(status, 200)
        self.assertEqual(data["max_retained_backups"], MAX_RETAINED_BACKUPS)


if __name__ == "__main__":
    unittest.main()
