"""
Unit and Integration Tests for Features 1 through 5:
1. Download Master CSV in ADMIN Dashboard
2. 7-Day Auto Backup of Admin and Employee DBs with 2-Backup Retention
3. Download Activity Log and Download Clubs Log in NDLI Employee Portal
4. Unresolved Issue 72h Reminder & 7-day recurrent reminder in Employee Portal
5. Unresolved Issue 30-Day Escalation Reminder & 7-day recurrent reminder in Admin Office Portal
"""
import unittest
import json
import urllib.request
import urllib.parse
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from config import (
    BASE_DIR,
    MASTER_CLUBS_CSV,
    MASTER_ISSUES_CSV,
    BACKUP_DIR,
    EMPLOYEE_NODES_DIR,
    CLUB_FIELDS,
    ISSUE_FIELDS
)
from db.csv_engine import CSVEngine
from db.backup_engine import BackupEngine
from db.issue_manager import IssueManager


class TestFeatures1To5(unittest.TestCase):

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

    def _post(self, path: str, payload: dict, token: str = ""):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get_json(self, path: str, token: str = ""):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get_raw(self, path: str, token: str = ""):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                headers = dict(resp.headers)
                return resp.status, headers, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8")

    # =========================================================================
    # FEATURE 1 TESTS
    # =========================================================================
    def test_feature_1_download_master_csv_endpoint(self):
        """Feature 1: Verify /api/admin/download/master-clubs serves master_clubs.csv with attachment header."""
        status, headers, content = self._get_raw("/api/admin/download/master-clubs")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn('filename="master_clubs.csv"', headers.get("Content-Disposition", ""))

        # Verify content matches what is on disk
        with open(MASTER_CLUBS_CSV, "rb") as f:
            expected = f.read().decode("utf-8")
        self.assertEqual(content, expected)
        self.assertIn("club_id", content)
        self.assertIn("institution_name", content)

    def test_feature_1_ui_button_exists(self):
        """Feature 1: Verify the 'Download Master CSV' button exists in templates/admin.html."""
        admin_html = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        self.assertIn("Download Master CSV", admin_html)
        self.assertIn("downloadMasterCSV()", admin_html)

    # =========================================================================
    # FEATURE 2 TESTS
    # =========================================================================
    def test_feature_2_backup_creation_and_strict_two_backup_retention(self):
        """
        Feature 2: Verify backup covers both admin end and employee end database,
        and strictly retains only the last 2 backups while deleting all previous backups.
        """
        # Clean any old test backups first
        b_dir = BackupEngine.get_backup_dir()
        for d in b_dir.iterdir():
            if d.is_dir() and d.name.startswith("backup_"):
                import shutil
                shutil.rmtree(str(d), ignore_errors=True)

        # Create 1st backup
        b1 = BackupEngine.create_backup(note="Backup 1")
        self.assertTrue(b1["success"])
        existing = BackupEngine.get_existing_backups()
        self.assertEqual(len(existing), 1)

        # Verify admin end and employee end folders exist inside backup
        b1_path = Path(b1["path"])
        self.assertTrue((b1_path / "admin").exists())
        self.assertTrue((b1_path / "employees").exists())
        self.assertTrue((b1_path / "manifest.json").exists())
        self.assertTrue((b1_path / "admin" / "master_clubs.csv").exists())
        self.assertTrue((b1_path / "employees" / "emp01" / "clubs.csv").exists())

        # Create 2nd backup
        time.sleep(0.05)
        b2 = BackupEngine.create_backup(note="Backup 2")
        self.assertTrue(b2["success"])
        existing = BackupEngine.get_existing_backups()
        self.assertEqual(len(existing), 2)

        # Create 3rd backup -> Must delete oldest backup (Backup 1) and keep exactly 2
        time.sleep(0.05)
        b3 = BackupEngine.create_backup(note="Backup 3")
        self.assertTrue(b3["success"])
        existing = BackupEngine.get_existing_backups()
        self.assertEqual(len(existing), 2, "Must strictly retain only the last 2 backups")

        # The retained backups must be b3 and b2, b1 must be deleted
        retained_ids = [d.name for d in existing]
        self.assertIn(b3["backup_id"], retained_ids)
        self.assertIn(b2["backup_id"], retained_ids)
        self.assertNotIn(b1["backup_id"], retained_ids)
        self.assertFalse(b1_path.exists(), "Previous backup 1 must be deleted automatically by system")

        # Create 4th backup -> Keeps b4 and b3, deletes b2
        time.sleep(0.05)
        b4 = BackupEngine.create_backup(note="Backup 4")
        self.assertTrue(b4["success"])
        existing = BackupEngine.get_existing_backups()
        self.assertEqual(len(existing), 2)
        retained_ids = [d.name for d in existing]
        self.assertIn(b4["backup_id"], retained_ids)
        self.assertIn(b3["backup_id"], retained_ids)
        self.assertNotIn(b2["backup_id"], retained_ids)

    def test_feature_2_auto_backup_schedule_logic(self):
        """Feature 2: Verify 7-day auto backup triggers only after 7 days have elapsed."""
        now = datetime.now(timezone.utc)
        schedule_file = BackupEngine.get_schedule_file()

        # Simulate last backup was taken 3 days ago -> should NOT trigger
        fake_schedule = {
            "last_backup_time": (now - timedelta(days=3)).isoformat(),
            "next_backup_due": (now + timedelta(days=4)).isoformat()
        }
        with open(schedule_file, "w", encoding="utf-8") as f:
            json.dump(fake_schedule, f)

        res = BackupEngine.check_and_run_auto_backup(force=False)
        self.assertIsNone(res, "Should not trigger auto backup when less than 7 days have elapsed")

        # Simulate last backup was taken 8 days ago (>= 7 days) -> MUST trigger auto backup
        fake_schedule["last_backup_time"] = (now - timedelta(days=8)).isoformat()
        with open(schedule_file, "w", encoding="utf-8") as f:
            json.dump(fake_schedule, f)

        res = BackupEngine.check_and_run_auto_backup(force=False)
        self.assertIsNotNone(res, "Must trigger auto backup when >= 7 days have elapsed")
        self.assertTrue(res["success"])

    def test_feature_2_rest_api_and_admin_ui(self):
        """Feature 2: Test /api/admin/backup/status and /api/admin/backup/trigger endpoints."""
        status, data = self._get_json("/api/admin/backup/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["interval_days"], 7)
        self.assertEqual(data["max_retained_backups"], 2)
        self.assertLessEqual(len(data["backups"]), 2)

        # Trigger manual backup via API
        status, trig_data = self._post("/api/admin/backup/trigger", {"note": "Test API Trigger"})
        self.assertEqual(status, 200)
        self.assertTrue(trig_data["success"])

        # Check admin.html contains backup UI
        admin_html = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        self.assertIn("Automated Database Backup Engine", admin_html)
        self.assertIn("Every 7 Days", admin_html)
        self.assertIn("Last 2 Backups Stored", admin_html)

    # =========================================================================
    # FEATURE 3 TESTS
    # =========================================================================
    def test_feature_3_download_employee_logs(self):
        """
        Feature 3: Verify 'Download Activity Log' and 'Download Clubs Log' endpoints
        serve activity_log.csv and clubs.csv from that particular employee account database.
        """
        # Test EMP01
        status, headers, content = self._get_raw("/api/employee/download/activity-log?emp_id=EMP01")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn('filename="activity_log.csv"', headers.get("Content-Disposition", ""))
        emp01_act_path = EMPLOYEE_NODES_DIR / "emp01" / "activity_log.csv"
        with open(emp01_act_path, "rb") as f:
            self.assertEqual(content, f.read().decode("utf-8"))

        status, headers, content = self._get_raw("/api/employee/download/clubs-log?emp_id=EMP01")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn('filename="clubs.csv"', headers.get("Content-Disposition", ""))
        emp01_clubs_path = EMPLOYEE_NODES_DIR / "emp01" / "clubs.csv"
        with open(emp01_clubs_path, "rb") as f:
            self.assertEqual(content, f.read().decode("utf-8"))

        # Test EMP02
        status, headers, content = self._get_raw("/api/employee/download/activity-log?emp_id=EMP02")
        self.assertEqual(status, 200)
        emp02_act_path = EMPLOYEE_NODES_DIR / "emp02" / "activity_log.csv"
        with open(emp02_act_path, "rb") as f:
            self.assertEqual(content, f.read().decode("utf-8"))

    def test_feature_3_ui_buttons_exist(self):
        """Feature 3: Verify 'Download Activity Log' and 'Download Clubs Log' buttons exist in templates/employee.html."""
        emp_html = (BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        self.assertIn("Download Activity Log", emp_html)
        self.assertIn("Download Clubs Log", emp_html)
        self.assertIn("downloadEmployeeActivityLog()", emp_html)
        self.assertIn("downloadEmployeeClubsLog()", emp_html)

    # =========================================================================
    # FEATURE 4 TESTS
    # =========================================================================
    def test_feature_4_unresolved_issue_72h_and_7d_recurrent_reminder(self):
        """
        Feature 4: Test employee logs unresolved issue, reminder appears after 72h,
        clicking token allows marking Resolved or Not Resolved (re-generating after 7 days).
        """
        now = datetime.now(timezone.utc)
        club_id = "NDLI-DL-102"
        emp_id = "EMP01"

        # 1. Employee creates unresolved issue
        status, create_data = self._post("/api/issues/create", {
            "club_id": club_id,
            "emp_id": emp_id,
            "issue_note": "Patron reported issue with membership renewal confirmation.",
            "created_at": now.isoformat(),
            "reminder_due_at": (now + timedelta(hours=72)).isoformat()
        })
        self.assertEqual(status, 200)
        self.assertTrue(create_data["success"])
        issue_id = create_data["issue"]["issue_id"]
        self.assertEqual(create_data["issue"]["status"], "Unresolved")

        # 2. After 50 hours (< 72h): Reminder should NOT be due yet
        as_of_50h = now + timedelta(hours=50)
        reminders = IssueManager.get_employee_reminders(emp_id=emp_id, as_of=as_of_50h)
        self.assertNotIn(issue_id, [r["issue_id"] for r in reminders], "Reminder should not appear before 72 hours")

        # 3. After 73 hours (>= 72h): Reminder MUST appear in employee dashboard
        as_of_73h = now + timedelta(hours=73)
        reminders = IssueManager.get_employee_reminders(emp_id=emp_id, as_of=as_of_73h)
        matching = [r for r in reminders if r["issue_id"] == issue_id]
        self.assertEqual(len(matching), 1, "Reminder must appear on dashboard after 72 hours")
        self.assertEqual(matching[0]["status"], "Unresolved")

        # 4. Employee clicks reminder token and marks "Not Resolved"
        status, res_data = self._post("/api/issues/resolve", {
            "issue_id": issue_id,
            "status": "Not Resolved",
            "resolved_by": emp_id,
            "resolution_notes": "Awaiting updated documents from patron."
        })
        self.assertEqual(status, 200)
        self.assertTrue(res_data["success"])
        updated = res_data["issue"]
        self.assertEqual(updated["status"], "Unresolved")

        # Verify next reminder is scheduled for 7 days from resolution
        expected_next = datetime.fromisoformat(updated["reminder_due_at"])
        diff_days = round((expected_next - now).total_seconds() / 86400)
        self.assertEqual(diff_days, 7, "Next reminder must be auto-generated after 7 days")

        # 5. Check at 3 days later (< 7 days): should NOT appear
        as_of_3d = now + timedelta(days=3)
        reminders_3d = IssueManager.get_employee_reminders(emp_id=emp_id, as_of=as_of_3d)
        self.assertNotIn(issue_id, [r["issue_id"] for r in reminders_3d])

        # 6. Check at 8 days later (>= 7 days): MUST appear again
        as_of_8d = now + timedelta(days=8)
        reminders_8d = IssueManager.get_employee_reminders(emp_id=emp_id, as_of=as_of_8d)
        self.assertIn(issue_id, [r["issue_id"] for r in reminders_8d], "Reminder must reappear after 7 days")

        # 7. Employee clicks reminder token and marks "Resolved"
        status, resolved_data = self._post("/api/issues/resolve", {
            "issue_id": issue_id,
            "status": "Resolved",
            "resolved_by": emp_id,
            "resolution_notes": "Patron submitted valid documentation; issue closed."
        })
        self.assertEqual(status, 200)
        self.assertEqual(resolved_data["issue"]["status"], "Resolved")

        # 8. Should NEVER appear in reminders again
        as_of_100d = now + timedelta(days=100)
        reminders_100d = IssueManager.get_employee_reminders(emp_id=emp_id, as_of=as_of_100d)
        self.assertNotIn(issue_id, [r["issue_id"] for r in reminders_100d], "Resolved issue must never appear again")

    def test_feature_4_ui_elements_exist(self):
        """Feature 4: Verify issue reporting button and resolution modal exist in templates/employee.html."""
        emp_html = (BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        self.assertIn("SET A REMINDER", emp_html)
        self.assertIn("employee-reminders-container", emp_html)
        self.assertIn("employee-issue-modal", emp_html)
        self.assertIn("submitEmployeeIssueResolution('Resolved')", emp_html)
        self.assertIn("submitEmployeeIssueResolution('Not Resolved')", emp_html)

    # =========================================================================
    # FEATURE 5 TESTS
    # =========================================================================
    def test_feature_5_admin_escalation_30d_and_7d_recurrent_reminder(self):
        """
        Feature 5: If any issue remains unresolved for 30 days, highlight it on ADMIN dashboard
        by generating a reminder. Upon clicking, ADMIN marks 'Resolved' or 'Not Resolved'.
        If not resolved, auto generate reminder after 7 days until marked Resolved.
        """
        now = datetime.now(timezone.utc)
        club_id = "NDLI-WB-101"
        emp_id = "EMP04"

        # 1. Create an issue reported in the past
        # Case A: Created 25 days ago (< 30 days) -> Admin reminder should NOT appear
        issue_25d = IssueManager.create_issue(
            club_id=club_id,
            emp_id=emp_id,
            issue_note="Minor ticket synchronization delay.",
            created_at=(now - timedelta(days=25)).isoformat(),
            admin_reminder_due_at=(now - timedelta(days=25) + timedelta(days=30)).isoformat()
        )
        admin_reminders = IssueManager.get_admin_reminders(as_of=now)
        self.assertNotIn(issue_25d["issue_id"], [r["issue_id"] for r in admin_reminders],
                         "Admin reminder must not appear if unresolved for less than 30 days")

        # Case B: Created 32 days ago (>= 30 days) -> Admin reminder MUST appear
        issue_32d = IssueManager.create_issue(
            club_id=club_id,
            emp_id=emp_id,
            issue_note="Critical server timeout during registration batch upload.",
            created_at=(now - timedelta(days=32)).isoformat(),
            admin_reminder_due_at=(now - timedelta(days=32) + timedelta(days=30)).isoformat()
        )
        admin_reminders = IssueManager.get_admin_reminders(as_of=now)
        matching = [r for r in admin_reminders if r["issue_id"] == issue_32d["issue_id"]]
        self.assertEqual(len(matching), 1, "Issue unresolved for 30+ days must generate reminder on admin dashboard")
        self.assertGreaterEqual(matching[0]["days_unresolved"], 30)

        # 2. Test via HTTP REST endpoint GET /api/issues/admin-reminders
        status, api_reminders = self._get_json("/api/issues/admin-reminders")
        self.assertEqual(status, 200)
        self.assertTrue(api_reminders["success"])
        api_matching = [r for r in api_reminders["reminders"] if r["issue_id"] == issue_32d["issue_id"]]
        self.assertEqual(len(api_matching), 1)

        # 3. Admin clicks reminder token and marks "Not Resolved"
        status, res_data = self._post("/api/issues/resolve", {
            "issue_id": issue_32d["issue_id"],
            "status": "Not Resolved",
            "resolved_by": "admin@iitkgp.ac.in",
            "resolution_notes": "Followed up with nodal officer; issue still open at zonal end."
        })
        self.assertEqual(status, 200)
        self.assertEqual(res_data["issue"]["status"], "Unresolved")

        # Verify admin reminder rescheduled for +7 days
        next_admin_due = datetime.fromisoformat(res_data["issue"]["admin_reminder_due_at"])
        diff_days = round((next_admin_due - now).total_seconds() / 86400)
        self.assertEqual(diff_days, 7, "Next admin reminder must be auto-generated after 7 days")

        # 4. Check 3 days later (< 7 days): Should NOT appear
        as_of_3d = now + timedelta(days=3)
        reminders_3d = IssueManager.get_admin_reminders(as_of=as_of_3d)
        self.assertNotIn(issue_32d["issue_id"], [r["issue_id"] for r in reminders_3d])

        # 5. Check 8 days later (>= 7 days): MUST appear again
        as_of_8d = now + timedelta(days=8)
        reminders_8d = IssueManager.get_admin_reminders(as_of=as_of_8d)
        self.assertIn(issue_32d["issue_id"], [r["issue_id"] for r in reminders_8d],
                      "Admin reminder must reappear after 7 days until resolved")

        # 6. Admin marks "Resolved"
        status, resolved_data = self._post("/api/issues/resolve", {
            "issue_id": issue_32d["issue_id"],
            "status": "Resolved",
            "resolved_by": "admin@iitkgp.ac.in",
            "resolution_notes": "Central admin resolved server timeout and re-indexed batch."
        })
        self.assertEqual(status, 200)
        self.assertEqual(resolved_data["issue"]["status"], "Resolved")

        # 7. Cleared completely
        as_of_50d = now + timedelta(days=50)
        reminders_50d = IssueManager.get_admin_reminders(as_of=as_of_50d)
        self.assertNotIn(issue_32d["issue_id"], [r["issue_id"] for r in reminders_50d],
                         "Resolved issue must no longer generate admin reminders")

    def test_feature_5_ui_elements_exist(self):
        """Feature 5: Verify 30+ days escalation reminder container and admin modal exist in templates/admin.html."""
        admin_html = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        self.assertIn("admin-issues-escalation-container", admin_html)
        self.assertIn("admin-issue-resolution-modal", admin_html)
        self.assertIn("submitAdminIssueResolution('Resolved')", admin_html)
        self.assertIn("submitAdminIssueResolution('Not Resolved')", admin_html)

    # =========================================================================
    # DEEP VERIFICATION & EDGE CASE TESTS (Step 2 & Step 4 Fixes)
    # =========================================================================
    def test_employee_not_resolved_does_not_delay_admin_30d_escalation(self):
        """
        Critical Fix Verification:
        When an employee marks 'Not Resolved' at day 28, the employee reminder is set to day 35,
        but the Admin 30-day escalation reminder MUST NOT be delayed and must appear on day 30.
        """
        now = datetime.now(timezone.utc)
        club_id = "NDLI-WB-101"
        emp_id = "EMP04"

        # Create issue originally reported 28 days ago
        iss = IssueManager.create_issue(
            club_id=club_id,
            emp_id=emp_id,
            issue_note="Special edge case: Employee follow-up near 30d escalation boundary.",
            created_at=(now - timedelta(days=28)).isoformat()
        )
        issue_id = iss["issue_id"]

        # Employee marks "Not Resolved" at day 28 (as_of=now)
        status, res_data = self._post("/api/issues/resolve", {
            "issue_id": issue_id,
            "status": "Not Resolved",
            "resolved_by": emp_id,
            "role": "EMPLOYEE",
            "resolution_notes": "Employee still working on zonal issue."
        })
        self.assertEqual(status, 200)
        self.assertTrue(res_data["success"])

        updated = res_data["issue"]
        # Employee reminder must be +7 days from now (day 35)
        emp_due = datetime.fromisoformat(updated["reminder_due_at"])
        self.assertEqual(round((emp_due - now).total_seconds() / 86400), 7)

        # Admin reminder MUST still be due at day 30 (now + 2 days)
        adm_reminders_at_30d = IssueManager.get_admin_reminders(as_of=now + timedelta(days=2, hours=1))
        matching = [r for r in adm_reminders_at_30d if r["issue_id"] == issue_id]
        self.assertEqual(len(matching), 1, "Admin reminder must appear at day 30 even if employee marked Not Resolved at day 28!")

    def test_admin_not_resolved_preserves_employee_reminder_schedule(self):
        """
        Critical Fix Verification:
        When the Admin marks 'Not Resolved' on an escalated issue, the Admin's reminder
        is rescheduled for +7 days, and the Employee's separate reminder schedule is preserved.
        """
        now = datetime.now(timezone.utc)
        club_id = "NDLI-DL-102"
        emp_id = "EMP01"

        # Create issue 32 days ago
        iss = IssueManager.create_issue(
            club_id=club_id,
            emp_id=emp_id,
            issue_note="32-day overdue issue for dual-schedule verification.",
            created_at=(now - timedelta(days=32)).isoformat(),
            reminder_due_at=(now + timedelta(days=3)).isoformat(),  # Employee scheduled in 3 days
            admin_reminder_due_at=(now - timedelta(days=2)).isoformat()  # Admin due now
        )
        issue_id = iss["issue_id"]

        # Admin marks "Not Resolved" (role ADMIN)
        status, res_data = self._post("/api/issues/resolve", {
            "issue_id": issue_id,
            "status": "Not Resolved",
            "resolved_by": "admin@iitkgp.ac.in",
            "role": "ADMIN",
            "resolution_notes": "Admin reviewed; follow up in 7 days."
        })
        self.assertEqual(status, 200)

        updated = res_data["issue"]
        # Admin reminder must be +7 days from now
        adm_due = datetime.fromisoformat(updated["admin_reminder_due_at"])
        self.assertEqual(round((adm_due - now).total_seconds() / 86400), 7)

        # Employee reminder must be preserved (+3 days, untouched)
        emp_due = datetime.fromisoformat(updated["reminder_due_at"])
        self.assertEqual(round((emp_due - now).total_seconds() / 86400), 3)

    def test_missing_schedule_file_recovers_without_redundant_backup(self):
        """
        Robustness Fix Verification:
        If backup_schedule.json is missing or corrupted, but valid backups exist on disk
        taken less than 7 days ago, the system recovers schedule metadata without triggering
        a redundant backup.
        """
        # Ensure at least 1 backup exists
        b_info = BackupEngine.create_backup(note="Baseline for recovery test")
        self.assertTrue(b_info["success"])

        # Delete schedule file
        schedule_file = BackupEngine.get_schedule_file()
        schedule_file.unlink(missing_ok=True)
        self.assertFalse(schedule_file.exists())

        # Calling check_and_run_auto_backup must NOT trigger a new backup
        res = BackupEngine.check_and_run_auto_backup(force=False)
        self.assertIsNone(res, "Must not trigger auto backup when recent backup exists on disk")
        self.assertTrue(schedule_file.exists(), "Schedule file must be automatically recovered")

    def test_retention_invariant_prunes_stale_backups_on_status_check(self):
        """
        Retention Invariant Verification:
        If extra backup directories exist on disk, get_backup_status() prunes them
        so that strictly only the last 2 backups are stored.
        """
        b_dir = BackupEngine.get_backup_dir()
        dummy_dirs = []
        for i in [1, 2, 3, 4]:
            d = b_dir / f"backup_2020010{i}_000000_000000"
            d.mkdir(parents=True, exist_ok=True)
            dummy_dirs.append(d)

        # Status check must enforce retention
        status_data = BackupEngine.get_backup_status()
        self.assertEqual(status_data["max_retained_backups"], 2)
        existing = BackupEngine.get_existing_backups()
        self.assertLessEqual(len(existing), 2, "Must strictly retain at most 2 backups")

    def test_download_employee_logs_invalid_or_blocked_employee(self):
        """
        Security / Validation Verification:
        Querying logs for a non-existent or blocked employee must return 404 or 403
        and must not pollute the filesystem.
        """
        # 1. Non-existent employee
        status, data = self._get_json("/api/employee/download/activity-log?emp_id=NONEXISTENT_EMP_99")
        self.assertEqual(status, 404)
        self.assertFalse(data.get("success", True))

        # Check no bogus folder created
        bogus_dir = EMPLOYEE_NODES_DIR / "nonexistent_emp_99"
        self.assertFalse(bogus_dir.exists())

    def test_concurrent_issue_creation_unique_ids(self):
        """
        Concurrency / ID Uniqueness:
        Creating multiple issues in rapid succession produces distinct, non-colliding IDs.
        """
        created_ids = []
        for i in range(5):
            iss = IssueManager.create_issue(
                club_id="NDLI-WB-101",
                emp_id="EMP04",
                issue_note=f"Rapid concurrent note {i}"
            )
            created_ids.append(iss["issue_id"])

        self.assertEqual(len(created_ids), len(set(created_ids)), "All created issue IDs must be strictly unique")

    def test_emergency_restore_requires_admin_password(self):
        """
        Security Verification:
        Emergency database restore requires second-layer Master Admin password verification.
        Missing password -> 401, Invalid password -> 403.
        """
        # 1. Missing password
        status, data = self._post("/api/admin/backup/restore", {})
        self.assertEqual(status, 401)
        self.assertFalse(data.get("success", True))
        self.assertIn("password is required", data.get("message", "").lower())

        # 2. Invalid password
        status, data = self._post("/api/admin/backup/restore", {"password": "WrongPassword123!"})
        self.assertEqual(status, 403)
        self.assertFalse(data.get("success", True))
        self.assertIn("invalid master admin password", data.get("message", "").lower())

    def test_emergency_restore_with_valid_password_success(self):
        """
        Emergency Restore Execution:
        Restores database from backup snapshot upon valid Master Admin password verification.
        """
        # Ensure at least one backup exists
        backup_res = BackupEngine.create_backup(note="Test Pre-Restore Snapshot")
        backup_id = backup_res["backup_id"]

        status, data = self._post("/api/admin/backup/restore", {
            "password": "Seed#Admin-Rotated2026",
            "backup_id": backup_id
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("restored_from", data)
        self.assertGreaterEqual(data.get("restored_files_count", 0), 1)

    def test_admin_html_has_one_click_restore_and_security_modal(self):
        """
        UI Elements Verification:
        Templates must contain One-Click Restore button, Emergency Restore Modal,
        dynamic CAPTCHA challenge, and Admin Password input.
        """
        html_path = BASE_DIR / "templates" / "admin.html"
        self.assertTrue(html_path.exists())
        content = html_path.read_text(encoding="utf-8")

        self.assertIn("openEmergencyRestoreModal", content)
        self.assertIn("One-Click Restore Database", content)
        self.assertIn('id="emergency-restore-modal"', content)
        self.assertIn('id="restore-captcha-display"', content)
        self.assertIn('id="restore-captcha-input"', content)
        self.assertIn('id="restore-admin-password"', content)
    def test_user_manual_pdf_exists_and_valid(self):
        """Verify User Manual PDF is present in root, docs, and static with valid PDF structure."""
        pdf_root = BASE_DIR / "NDLI_Club_Management_User_Manual.pdf"
        pdf_docs = BASE_DIR / "docs" / "NDLI_Club_Management_User_Manual.pdf"
        pdf_static = BASE_DIR / "static" / "NDLI_Club_Management_User_Manual.pdf"

        self.assertTrue(pdf_root.exists(), "Root User Manual PDF must exist.")
        self.assertTrue(pdf_docs.exists(), "Docs User Manual PDF must exist.")
        self.assertTrue(pdf_static.exists(), "Static User Manual PDF must exist.")

        # Check binary signature (%PDF-) and size > 1 MB
        with open(pdf_root, "rb") as f:
            header = f.read(5)
            self.assertEqual(header, b"%PDF-", "File must have standard PDF magic bytes.")
        self.assertGreater(pdf_root.stat().st_size, 1_000_000, "PDF should be compiled with all 14 pages and figures.")

    def test_user_manual_download_endpoint(self):
        """Verify GET /api/download/user-manual returns valid PDF payload."""
        req = urllib.request.Request(f"{self.base_url}/api/download/user-manual")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "application/pdf")
            self.assertIn("NDLI_Club_Management_User_Manual.pdf", resp.headers.get("Content-Disposition", ""))
            body = resp.read()
            self.assertTrue(body.startswith(b"%PDF-"))

    def test_user_manual_html_view_endpoint(self):
        """Verify GET /manual and /user-manual serve the interactive HTML edition."""
        for path in ["/manual", "/user-manual", "/documentation"]:
            req = urllib.request.Request(f"{self.base_url}{path}")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                html = resp.read().decode("utf-8")
                self.assertIn("NDLI Club Management System", html)
                self.assertIn("Dr. Anirban Mukherjee", html)
                self.assertIn("One-Click Emergency Database Restoration", html)

    def test_docs_static_assets_serving(self):
        """Verify embedded manual screenshots in docs/images are served without broken links."""
        test_img = BASE_DIR / "docs" / "images" / "06_automated_backups.png"
        if test_img.exists():
            req = urllib.request.Request(f"{self.base_url}/docs/images/06_automated_backups.png")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Content-Type"), "image/png")
                data = resp.read()
                self.assertTrue(data.startswith(b"\x89PNG"))

    def test_ui_templates_and_gas_have_user_manual_links(self):
        """Verify templates and deployment_gas have user manual download link and no Read Online references."""
        idx_content = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/api/download/user-manual", idx_content)
        self.assertNotIn("Read Online", idx_content)
        self.assertNotIn("Manual Online", idx_content)
        self.assertIn("NDLI Club Management System User Manual", idx_content)

        admin_content = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        self.assertIn("/api/download/user-manual", admin_content)
        self.assertNotIn("Read Online", admin_content)
        self.assertNotIn("Manual Online", admin_content)

        employee_content = (BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        self.assertIn("/api/download/user-manual", employee_content)
        self.assertNotIn("Read Online", employee_content)
        self.assertNotIn("Manual Online", employee_content)

        gas_code = (BASE_DIR / "deployment_gas" / "Code.gs").read_text(encoding="utf-8")
        self.assertIn('download === "user-manual"', gas_code)
        self.assertNotIn("Read Online", gas_code)

    def test_master_lock_screen_cover_aesthetics_and_glowing_logo(self):
        """Verify templates/index.html has master lock screen matching user manual cover page aesthetics, glowing light trail, and captcha."""
        idx_content = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
        # Cover aesthetics & Gate elements
        self.assertIn('id="app-lock-gate"', idx_content)
        self.assertIn("Secure Enterprise Access Gateway", idx_content)
        self.assertIn("National Digital Library of India", idx_content)
        self.assertIn("IIT Kharagpur Central Master Administration Office", idx_content)
        
        # Central Logo with Glowing Light Trail
        self.assertIn("logo-trail-container", idx_content)
        self.assertIn("trail-light-runner", idx_content)
        self.assertIn("orbitLightTrail", idx_content)
        self.assertIn("lightTrailGrad", idx_content)
        self.assertIn("/static/img/ndli_club_logo.png", idx_content)

        # Credentials and Anti-bot Captcha Form
        self.assertIn('id="master-lock-form"', idx_content)
        self.assertIn('id="lock-identifier"', idx_content)
        self.assertIn('id="lock-password"', idx_content)
        self.assertIn('id="lock-captcha-canvas"', idx_content)
        self.assertIn('id="lock-captcha-input"', idx_content)
        self.assertIn("handleMasterLogin", idx_content)

        # Fluidic Transition logic
        self.assertIn("unlocked-exit", idx_content)
        self.assertIn("content-locked", idx_content)
        self.assertIn("content-unlocked", idx_content)
        self.assertIn("unlockSystemFluidTransition", idx_content)
        self.assertIn("lockApplication", idx_content)

    def test_ndli_main_site_shortcut_on_navbars(self):
        """Verify NDLI Main Site shortcut link (https://ndl.iitkgp.ac.in) is present on Admin, Employee, and Index navbars."""
        admin_content = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        self.assertIn("https://ndl.iitkgp.ac.in", admin_content)
        self.assertIn("Main Site", admin_content)

        emp_content = (BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        self.assertIn("https://ndl.iitkgp.ac.in", emp_content)
        self.assertIn("Main Site", emp_content)

        idx_content = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("https://ndl.iitkgp.ac.in", idx_content)
        self.assertIn("Main Site", idx_content)

    def test_employee_dashboard_toolbox_tab_and_seven_tools(self):
        """Verify Employee Dashboard has a Tool Box tab providing access to all 11 tools with clickable links."""
        emp_content = (BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        self.assertIn('data-target="tab-toolbox"', emp_content)
        self.assertIn('id="tab-toolbox"', emp_content)
        self.assertIn("Regional Officer Operational Tool Box", emp_content)

        # 11 Tools verification
        tools = [
            ("Google Meet", "https://meet.google.com"),
            ("Google Drive", "https://drive.google.com"),
            ("Google Docs", "https://docs.google.com"),
            ("Google Sheets", "https://sheets.google.com"),
            ("Zoom Meeting", "https://zoom.us"),
            ("Microsoft Teams", "https://teams.microsoft.com"),
            ("StreamYard", "https://streamyard.com"),
            ("Gmail", "https://mail.google.com"),
            ("Google Slides", "https://slides.google.com"),
            ("Google Keep", "https://keep.google.com"),
            ("YouTube (NDL India)", "https://www.youtube.com/@NDLIndia")
        ]
        for name, url in tools:
            self.assertIn(name, emp_content)
            self.assertIn(url, emp_content)

        # Also verify GAS Employee.html
        gas_emp = (BASE_DIR / "deployment_gas" / "Employee.html").read_text(encoding="utf-8")
        self.assertIn('data-target="tab-toolbox"', gas_emp)
        self.assertIn('id="tab-toolbox"', gas_emp)
        for name, url in tools:
            self.assertIn(name, gas_emp)
            self.assertIn(url, gas_emp)


if __name__ == "__main__":
    unittest.main()


