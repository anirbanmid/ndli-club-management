"""
Regression Test Suite: Data Persistence Across Server Restarts & Re-initialization
Validates fix for:
Issue: EMP01 formed club id 26 (total clubs = 11). Server restart wiped club data back to 10.
Tests non-destructive initialize_database(), cold boot auto-recovery, persistent disk detection,
and Google Drive sync parity.
"""
import os
import sys
import json
import unittest
import shutil
import tempfile
from pathlib import Path

from config import (
    BASE_DIR,
    DATA_DIR,
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_USERS_CSV,
    MASTER_QUOTAS_CSV,
    EMPLOYEE_NODES_DIR,
    CLUB_FIELDS,
    ACTIVITY_FIELDS,
    USER_FIELDS,
    _resolve_data_dir
)
from db.schemas import QUOTA_FIELDS
from db.csv_engine import CSVEngine
from db.sync_engine import SyncEngine
from db.backup_engine import BackupEngine
from db.storage_adapter import get_storage_adapter, AppsScriptRelaySyncAdapter, LocalSyncStorageAdapter
from init_db import initialize_database
from auth import AuthService
import app


class TestRestartAndPersistenceRegression(unittest.TestCase):

    def setUp(self):
        # Baseline check
        SyncEngine.initialize_storage_hierarchy()

    def tearDown(self):
        # Clean up test club 26 if present to keep data directory clean
        self._cleanup_test_club("NDLI-EMP01-026")
        self._cleanup_test_club("26")

    def _cleanup_test_club(self, test_cid: str):
        if MASTER_CLUBS_CSV.exists():
            clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            clean = [c for c in clubs if c.get("club_id", "").strip().upper() != test_cid.upper()]
            if len(clean) != len(clubs):
                CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, clean)

        emp01_clubs = SyncEngine.get_employee_clubs_path("EMP01")
        if emp01_clubs.exists():
            n_clubs = CSVEngine.read_all(emp01_clubs, CLUB_FIELDS)
            clean_n = [c for c in n_clubs if c.get("club_id", "").strip().upper() != test_cid.upper()]
            if len(clean_n) != len(n_clubs):
                CSVEngine.write_all(emp01_clubs, CLUB_FIELDS, clean_n)

        SyncEngine.reconcile_all_nodes()

    def test_club_26_persists_across_initialize_database(self):
        """
        Tests that forming club id 26 results in 11 clubs, and subsequent
        execution of initialize_database(force=False) does NOT wipe it back to 10.
        """
        initial_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        initial_count = len(initial_clubs)

        # 1. EMP01 forms and saves a new club with club id 26
        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }
        created = SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)
        self.assertEqual(created["club_id"], "NDLI-EMP01-026")

        # Verify club 26 exists in Master CSV
        master_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertEqual(len(master_clubs), initial_count + 1)
        found_in_master = any(c.get("club_id") == "NDLI-EMP01-026" for c in master_clubs)
        self.assertTrue(found_in_master, "Club 26 must exist in master_clubs.csv")

        # Verify club 26 exists in EMP01 Node CSV
        node_clubs = CSVEngine.read_all(SyncEngine.get_employee_clubs_path("EMP01"), CLUB_FIELDS)
        found_in_node = any(c.get("club_id") == "NDLI-EMP01-026" for c in node_clubs)
        self.assertTrue(found_in_node, "Club 26 must exist in emp01/clubs.csv")

        # Verify activity log captured creation
        master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        found_act = any(a.get("club_id") == "NDLI-EMP01-026" for a in master_acts)
        self.assertTrue(found_act, "Activity log must contain club approval record for club 26")

        # 2. Simulate server restart: Run initialize_database()
        initialize_database(force=False)

        # 3. VERIFY CLUB 26 WAS NOT WIPED OUT!
        post_restart_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertEqual(
            len(post_restart_clubs),
            initial_count + 1,
            f"Club count must remain {initial_count + 1} across initialize_database, got {len(post_restart_clubs)}"
        )
        persisted_club = next((c for c in post_restart_clubs if c.get("club_id") == "NDLI-EMP01-026"), None)
        self.assertIsNotNone(persisted_club, "Club 26 must strictly persist across initialize_database")
        self.assertEqual(persisted_club["institution_name"], "Delhi Institute of Advanced Scientific Studies")

        # Verify activity log also persisted
        post_restart_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        self.assertTrue(
            any(a.get("club_id") == "NDLI-EMP01-026" for a in post_restart_acts),
            "Activity log for club 26 must strictly persist across initialize_database"
        )

    def test_club_26_persists_across_app_init_system(self):
        """
        Tests that app.init_system() preserves existing clubs without wiping.
        """
        initial_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        initial_count = len(initial_clubs)

        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }
        SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

        # Call app.init_system() (runs on HTTP server startup)
        res = app.init_system()
        self.assertEqual(res["status"], "ready")

        post_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertEqual(len(post_clubs), initial_count + 1)
        self.assertTrue(any(c.get("club_id") == "NDLI-EMP01-026" for c in post_clubs))

    def test_cold_boot_auto_recovery_from_backup(self):
        """
        Tests that if local database files are missing on cold boot,
        init_system automatically restores from the latest available backup snapshot.
        """
        # Form club 26
        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }
        SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

        # Create a backup containing club 26
        b_res = BackupEngine.create_backup(note="Test Backup with Club 26")
        self.assertTrue(b_res["success"])

        # Simulate cold boot wipeout: clear master_clubs.csv
        CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, [])
        self.assertEqual(len(CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)), 0)

        # Run init_system() -> Must detect missing data and auto-restore from backup snapshot
        init_res = app.init_system()
        self.assertTrue(init_res["restored_from_backup"], "Must auto-restore from backup snapshot on cold boot")

        # Verify club 26 is recovered
        recovered_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertTrue(any(c.get("club_id") == "NDLI-EMP01-026" for c in recovered_clubs))

    def test_persistent_disk_env_detection(self):
        """
        Tests that config.py correctly detects NDLI_DATA_DIR or RENDER_DISK_PATH.
        """
        temp_dir = Path(tempfile.mkdtemp())
        try:
            old_env = os.environ.get("NDLI_DATA_DIR")
            os.environ["NDLI_DATA_DIR"] = str(temp_dir)
            resolved = _resolve_data_dir()
            self.assertEqual(resolved, temp_dir.resolve())
        finally:
            if old_env is not None:
                os.environ["NDLI_DATA_DIR"] = old_env
            else:
                os.environ.pop("NDLI_DATA_DIR", None)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_idempotent_multiple_runs_no_data_loss_or_duplication(self):
        """
        Tests that calling initialize_database 5 times consecutively produces
        consistent row counts without duplicate rows or data corruption.
        """
        initial_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        initial_count = len(initial_clubs)

        for _ in range(5):
            initialize_database(force=False)

        final_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertEqual(len(final_clubs), initial_count, "Multiple initialize_database runs must not duplicate or lose clubs")

        # Verify all club IDs are unique
        cids = [c.get("club_id") for c in final_clubs]
        self.assertEqual(len(cids), len(set(cids)), "All club IDs must remain unique")


    def test_backup_engine_restores_all_master_files(self):
        """
        Tests that BackupEngine.create_backup and BackupEngine.restore_backup
        properly restore all 5 master CSV files (master_clubs, master_activities,
        master_quotas, master_users, master_issues) without leaving restored_master_files empty.
        """
        # Form club 26
        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }
        SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

        # Create backup
        b_res = BackupEngine.create_backup(note="Test Master Restore Parity")
        self.assertTrue(b_res["success"])
        b_id = b_res["backup_id"]

        # Restore from this backup
        r_res = BackupEngine.restore_backup(b_id)
        self.assertTrue(r_res["success"])
        self.assertGreater(len(r_res.get("restored_master_files", [])), 0, "restored_master_files must not be empty")
        self.assertIn("master_clubs.csv", r_res["restored_master_files"])
        self.assertIn("master_activities.csv", r_res["restored_master_files"])

    def test_remote_drive_pull_and_merge_parity(self):
        """
        Tests that AppsScriptRelaySyncAdapter.pull_all_from_drive() merges incoming
        remote clubs and activities cleanly into local storage without wiping existing records.
        """
        import json
        from unittest.mock import patch, MagicMock
        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"
        adapter._allow_test_pull = True

        # Initial clubs
        initial_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        initial_count = len(initial_clubs)

        # Prepare mock response with Club 26 from Google Drive
        club26_csv = "club_id,reg_no,institution_name,state,zone,patron_email,president_email,secretary_email,date_of_approval,last_renewal_date,renewal_date,status,approved_by_emp_id,updated_at,submission_timestamp,next_renewal_date\n"
        club26_csv += "NDLI-EMP01-026,REG-2026-EMP01-026,Delhi Institute of Advanced Scientific Studies,Delhi,North,director@diass.edu.in,president.club@diass.edu.in,secretary.club@diass.edu.in,2026-09-19T10:00:00Z,,2027-09-19,Approved,EMP01,2026-09-19T10:00:00.000000+00:00,2026-09-19T10:00:00Z,2027-09-19\n"

        mock_payload = {
            "ok": True,
            "status": 200,
            "data": {
                "success": True,
                "total_files": 1,
                "files": {
                    "master/master_clubs.csv": club26_csv
                }
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = adapter.pull_all_from_drive(force=True)
            self.assertTrue(res["success"])
            self.assertIn("master/master_clubs.csv", res["files"])

        # Verify Club 26 was merged and initial clubs preserved
        merged_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertEqual(len(merged_clubs), initial_count + 1)
        self.assertTrue(any(c.get("club_id") == "NDLI-EMP01-026" for c in merged_clubs))

    def test_user_status_preserved_across_reinit(self):
        """
        Tests that if an employee's status is toggled (e.g. blocked is_active=0),
        running initialize_database(force=False) does NOT unblock them.
        """
        # Set EMP07 status to inactive (blocked)
        AuthService.set_user_status("EMP07", is_active=False)
        u_before = CSVEngine.find_by_key(MASTER_USERS_CSV, "id", "EMP07", USER_FIELDS)
        self.assertEqual(str(u_before.get("is_active")), "0")

        # Run initialize_database (simulating restart)
        initialize_database(force=False)

        # Verify status is still 0
        u_after = CSVEngine.find_by_key(MASTER_USERS_CSV, "id", "EMP07", USER_FIELDS)
        self.assertEqual(str(u_after.get("is_active")), "0", "User status must be preserved across initialize_database")

        # Restore EMP07 status
        AuthService.set_user_status("EMP07", is_active=True)

    def test_merge_exception_preserves_local_not_incoming(self):
        """
        Regression for the silent-wipe bug: if _merge_csv_content hits an
        exception (e.g. malformed/garbled incoming CSV from a stale or
        partial Google Drive snapshot), it must fall back to the LOCAL
        copy (which has club 26), never the incoming remote copy (which
        doesn't). The old code's `except Exception: return incoming_csv_text`
        was the exact root cause of a locally-saved club vanishing after a
        server restart.
        """
        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }
        SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

        local_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        local_count = len(local_clubs)
        self.assertTrue(any(c.get("club_id") == "NDLI-EMP01-026" for c in local_clubs))

        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"

        # Deliberately garbled incoming content that will raise inside the
        # merge (e.g. a truncated/corrupted Drive snapshot).
        garbled_incoming = "\x00\x01not,a,valid\ncsv\x02\x03"

        result = adapter._merge_csv_content(
            "master/master_clubs.csv", MASTER_CLUBS_CSV, garbled_incoming
        )

        # The merge must have returned the LOCAL content (still has club 26),
        # not the garbled/incoming content.
        self.assertIn("NDLI-EMP01-026", result)
        self.assertNotEqual(result, garbled_incoming)

    def test_merge_row_count_regression_keeps_local(self):
        """
        Regression: if a merge somehow produces FEWER rows than what's
        already safely on local disk, the merge must refuse to shrink the
        dataset and keep the local copy instead.
        """
        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }
        SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

        local_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        local_count = len(local_clubs)

        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"

        # Incoming CSV that is valid but stale (missing club 26 and possibly
        # other rows) -- simulates a Drive snapshot from before club 26 was
        # ever successfully relayed.
        headers = "club_id,reg_no,institution_name,state,zone,patron_email,president_email,secretary_email,date_of_approval,last_renewal_date,renewal_date,status,approved_by_emp_id,updated_at,submission_timestamp,next_renewal_date\n"
        stale_incoming = headers  # zero data rows: strictly fewer than local

        result = adapter._merge_csv_content(
            "master/master_clubs.csv", MASTER_CLUBS_CSV, stale_incoming
        )
        result_rows = list(__import__("csv").DictReader(__import__("io").StringIO(result)))
        self.assertGreaterEqual(
            len(result_rows), local_count,
            "Merge must never reduce row count below what was already safely on local disk"
        )
        self.assertTrue(any(r.get("club_id") == "NDLI-EMP01-026" for r in result_rows))

    def test_upload_retries_and_logs_after_exhausting_attempts(self):
        """
        Regression: a relay upload failure must retry, and after exhausting
        retries must be recorded in a durable, inspectable log (not just an
        in-memory attribute that's lost on restart / never checked).
        """
        from unittest.mock import patch

        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"
        log_path = adapter.local.root_dir / "sync_issues.log"
        if log_path.exists():
            log_path.unlink()

        call_count = {"n": 0}

        def _always_fail(*args, **kwargs):
            call_count["n"] += 1
            raise ConnectionError("simulated relay failure")

        with patch("urllib.request.urlopen", side_effect=_always_fail), \
             patch("time.sleep", return_value=None):
            ok = adapter._upload_file_to_drive("master/master_clubs.csv", "irrelevant", max_attempts=3)

        self.assertFalse(ok)
        self.assertEqual(call_count["n"], 3, "Must retry up to max_attempts before giving up")
        self.assertEqual(adapter.failed_uploads_count, 1)
        self.assertTrue(log_path.exists(), "A failed-after-retries event must be durably logged")
        log_contents = log_path.read_text(encoding="utf-8")
        self.assertIn("upload_failed_after_retries", log_contents)

        log_path.unlink()

    def test_approve_new_club_confirms_cloud_sync_before_returning_success(self):
        """
        Regression for the free-tier-no-disk reality: on a host with no
        persistent disk, local writes alone are NOT durable. approve_new_club
        must synchronously confirm the Drive mirror before reporting success,
        and must clearly flag it when that confirmation fails, instead of
        reporting "approved successfully" for a record that could vanish on
        the next restart.
        """
        from unittest.mock import patch
        import db.sync_engine as sync_engine_module

        club_payload = {
            "club_id": "NDLI-EMP01-026",
            "reg_no": "REG-2026-EMP01-026",
            "institution_name": "Delhi Institute of Advanced Scientific Studies",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@diass.edu.in",
            "president_email": "president.club@diass.edu.in",
            "secretary_email": "secretary.club@diass.edu.in",
            "date_of_approval": "2026-09-19T10:00:00Z",
            "renewal_date": "2027-09-19"
        }

        # Case 1: relay confirms successfully -> cloud_sync_confirmed True
        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"
        adapter._allow_test_confirm = True
        with patch("db.storage_adapter.get_storage_adapter", return_value=adapter), \
             patch.object(AppsScriptRelaySyncAdapter, "_upload_file_to_drive", return_value=True):
            created = SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)
        self.assertTrue(created["cloud_sync_confirmed"])
        self._cleanup_test_club("NDLI-EMP01-026")

        # Case 2: relay fails every attempt -> cloud_sync_confirmed False,
        # so the caller (app.py) knows NOT to tell the user this is safely saved.
        adapter2 = AppsScriptRelaySyncAdapter()
        adapter2.relay_url = "https://mock.relay.url/exec"
        adapter2._allow_test_confirm = True
        with patch("db.storage_adapter.get_storage_adapter", return_value=adapter2), \
             patch.object(AppsScriptRelaySyncAdapter, "_upload_file_to_drive", return_value=False):
            created2 = SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)
        self.assertFalse(created2["cloud_sync_confirmed"])

    def test_upload_treats_http_200_ok_false_as_failure_not_success(self):
        """
        Regression for the actual root cause of the false-positive
        confirmation bug: Google Apps Script web apps return HTTP 200 even
        when the operation failed -- the real result is the `ok`/`success`
        field inside the JSON body (see deployment_gas/Code.gs's doPost).
        A version of _upload_file_to_drive that only checked "did urlopen()
        raise" treated this as success, so approve_new_club could report
        cloud_sync_confirmed=True for a record that was never actually
        written to Drive. This must not happen again.
        """
        from unittest.mock import patch, MagicMock

        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"
        log_path = adapter.local.root_dir / "sync_issues.log"
        if log_path.exists():
            log_path.unlink()

        fake_body = json.dumps({
            "ok": False,
            "status": 500,
            "data": {"error": True, "message": "Simulated: Drive folder reference is invalid"}
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_body
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("time.sleep", return_value=None):
            ok = adapter._upload_file_to_drive("master/master_clubs.csv", "irrelevant", max_attempts=2)

        self.assertFalse(
            ok,
            "An HTTP-200 response with ok:false in the body must be treated as a failed sync, not a success"
        )
        self.assertTrue(log_path.exists())
        self.assertIn("upload_failed_after_retries", log_path.read_text(encoding="utf-8"))
        log_path.unlink()

    def test_delete_club_removes_from_master_and_node_and_confirms_cloud(self):
        """
        A deleted club must actually disappear from both the master CSV and
        the owning employee's node CSV, and (like approve_new_club) must
        synchronously confirm the removal reached Drive so a stale Drive
        snapshot can't silently restore it on the next restart.
        """
        from unittest.mock import patch

        club_payload = {
            "club_id": "NDLI-EMP01-DELTEST1",
            "reg_no": "REG-DELTEST-1",
            "institution_name": "Deletion Test School",
            "state": "Delhi",
            "patron_email": "del@example.com",
            "president_email": "delpres@example.com",
            "secretary_email": "delsec@example.com",
            "date_of_approval": "2026-09-20T10:00:00Z",
            "renewal_date": "2027-09-20"
        }
        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"
        with patch("db.storage_adapter.get_storage_adapter", return_value=adapter), \
             patch.object(AppsScriptRelaySyncAdapter, "_upload_file_to_drive", return_value=True):
            SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

            master_before = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            self.assertTrue(any(c.get("club_id") == "NDLI-EMP01-DELTEST1" for c in master_before))

            result = SyncEngine.delete_club("NDLI-EMP01-DELTEST1")

        self.assertTrue(result["deleted"])
        self.assertTrue(result["cloud_sync_confirmed"])

        master_after = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertFalse(any(c.get("club_id") == "NDLI-EMP01-DELTEST1" for c in master_after))

        node_after = CSVEngine.read_all(SyncEngine.get_employee_clubs_path("EMP01"), CLUB_FIELDS)
        self.assertFalse(any(c.get("club_id") == "NDLI-EMP01-DELTEST1" for c in node_after))

    def test_delete_club_not_found_returns_deleted_false(self):
        """Deleting a nonexistent club_id must not raise or fabricate success."""
        result = SyncEngine.delete_club("NDLI-DOES-NOT-EXIST-999")
        self.assertFalse(result["deleted"])

    def test_delete_club_purges_activity_log_and_fixes_quota_drift(self):
        """
        Regression for the actual live-production bug: EMP01's dashboard
        showed 32 "clubs approved" while the master DB genuinely had 18.
        The cause was twofold: (1) _increment_quota only ever adds, never
        subtracts, and (2) delete_club previously left stale "Club Approval"
        activity-log rows behind, which the old max(stored, computed)
        reconciliation would use to justify keeping the inflated number
        forever. This test proves both are now fixed: after deleting a
        club, its activity-log rows are gone and the employee's quota
        reflects the true, current count -- not the old high-water mark.
        """
        from unittest.mock import patch

        adapter = AppsScriptRelaySyncAdapter()
        adapter.relay_url = "https://mock.relay.url/exec"
        with patch("db.storage_adapter.get_storage_adapter", return_value=adapter), \
             patch.object(AppsScriptRelaySyncAdapter, "_upload_file_to_drive", return_value=True):

            quota_before = SyncEngine.recompute_and_persist_quota("EMP01")
            baseline_clubs = quota_before.get("clubs_approved_count", 0)

            club_payload = {
                "club_id": "NDLI-EMP01-QUOTADRIFT1",
                "reg_no": "REG-QUOTADRIFT-1",
                "institution_name": "Quota Drift Test School",
                "state": "Delhi",
                "patron_email": "qd@example.com",
                "president_email": "qdpres@example.com",
                "secretary_email": "qdsec@example.com",
                "date_of_approval": "2026-09-20T10:00:00Z",
                "renewal_date": "2027-09-20"
            }
            SyncEngine.approve_new_club(emp_id="EMP01", club_data=club_payload)

            quota_after_create = SyncEngine.recompute_and_persist_quota("EMP01")
            self.assertEqual(
                quota_after_create["clubs_approved_count"], baseline_clubs + 1,
                "Quota should reflect exactly one more club after creation"
            )

            # Confirm the activity log actually has an entry for this club
            master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            self.assertTrue(any(a.get("club_id") == "NDLI-EMP01-QUOTADRIFT1" for a in master_acts))

            result = SyncEngine.delete_club("NDLI-EMP01-QUOTADRIFT1")
            self.assertTrue(result["deleted"])

            # Activity log entries for the deleted club must be gone
            master_acts_after = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            self.assertFalse(any(a.get("club_id") == "NDLI-EMP01-QUOTADRIFT1" for a in master_acts_after))

            # The quota must have dropped back to baseline -- NOT stayed at
            # baseline+1 (which is what the old max()-ratchet logic would do).
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            persisted = next((q for q in quotas if q.get("emp_id") == "EMP01"), {})
            self.assertEqual(
                int(persisted.get("clubs_approved_count", "-1")), baseline_clubs,
                "Quota must return to baseline after the club is deleted -- no ratchet, no drift"
            )

    def test_recompute_quota_never_uses_stale_higher_stored_value(self):
        """
        Directly proves the ratchet is gone: manually inflate the stored
        clubs_approved_count far above the true live count, then confirm
        recompute_and_persist_quota overwrites it with the true (lower)
        value instead of preserving the inflated one via max().
        """
        quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        if_version_quotas = [q for q in quotas if q.get("emp_id") != "EMP02"]
        inflated = {
            "emp_id": "EMP02",
            "employee_name": "Inflated Test",
            "zone": "",
            "clubs_approved_count": "99999",
            "support_logs_count": "0",
            "last_activity_timestamp": ""
        }
        CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, if_version_quotas + [inflated])

        result = SyncEngine.recompute_and_persist_quota("EMP02")
        self.assertLess(
            result["clubs_approved_count"], 99999,
            "recompute_and_persist_quota must overwrite an artificially inflated stored value with the truth"
        )

        quotas_after = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        persisted = next((q for q in quotas_after if q.get("emp_id") == "EMP02"), {})
        self.assertEqual(int(persisted.get("clubs_approved_count", "-1")), result["clubs_approved_count"])


if __name__ == "__main__":
    unittest.main()
