"""
Unit and Integration Tests for:
1. Employee Editing (ID, Name, Email, Password, Zone, State) with Node DB Sync.
2. Employee ID Rename and Node Directory Renaming & Activity/Club Relinking.
3. Master and Node Continuous Synchronization.
4. Admin ID and Password Security Gating on Employee Management Endpoints.
5. Live Dynamic Employee Roster and Profile Endpoints.
"""
import shutil
import unittest
import threading
import json
import urllib.request
import urllib.parse
from pathlib import Path
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from config import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    INITIAL_EMPLOYEES,
    MASTER_USERS_CSV,
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_QUOTAS_CSV,
    EMPLOYEE_NODES_DIR
)
from auth import AuthService, hash_password, verify_password
from db.sync_engine import SyncEngine
from db.csv_engine import CSVEngine
from db.schemas import USER_FIELDS, CLUB_FIELDS, ACTIVITY_FIELDS, QUOTA_FIELDS


class TestEmployeeEditAndSync(unittest.TestCase):

    @classmethod
    def _cleanup_test_ids(cls, test_ids):
        clean_set = {tid.upper() for tid in test_ids}
        for tid in clean_set:
            emp_dir = SyncEngine.get_employee_dir(tid)
            if emp_dir.exists():
                shutil.rmtree(str(emp_dir), ignore_errors=True)

        if MASTER_USERS_CSV.exists():
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            clean_users = [u for u in users if u.get("id", "").strip().upper() not in clean_set]
            CSVEngine.write_all(MASTER_USERS_CSV, USER_FIELDS, clean_users)

        if MASTER_QUOTAS_CSV.exists():
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            clean_quotas = [q for q in quotas if q.get("emp_id", "").strip().upper() not in clean_set]
            CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, clean_quotas)

        if MASTER_ACTIVITIES_CSV.exists():
            acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            clean_acts = [a for a in acts if a.get("emp_id", "").strip().upper() not in clean_set]
            CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, clean_acts)

        if MASTER_CLUBS_CSV.exists():
            clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            clean_clubs = [c for c in clubs if c.get("approved_by_emp_id", "").strip().upper() not in clean_set]
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, clean_clubs)

    @classmethod
    def setUpClass(cls):
        cls._cleanup_test_ids(["EMP99", "EMP99_NEW"])
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
        cls._cleanup_test_ids(["EMP99", "EMP99_NEW"])
        initialize_database()

    def _post_json(self, path: str, payload: dict, token: str = ""):
        from auth_util import admin_token
        token = token or admin_token(self.base_url, self.__class__.__name__)
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get_json(self, path: str, token: str = ""):
        from auth_util import admin_token
        token = token or admin_token(self.base_url, self.__class__.__name__)
        url = f"{self.base_url}{path}"
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get_admin_token(self):
        status, res = self._post_json("/api/auth/login", {
            "email": DEFAULT_ADMIN_EMAIL,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        self.assertEqual(status, 200)
        return res["session"]["token"]

    def _get_employee_token(self, emp_id="EMP01", password="Seed#EMP01-Rotated2026"):
        status, res = self._post_json("/api/auth/login", {
            "email": emp_id,
            "password": password
        })
        self.assertEqual(status, 200)
        return res["session"]["token"]

    # -------------------------------------------------------------
    # 1. Test Employee Edit & Dual Node DB Sync
    # -------------------------------------------------------------
    def test_employee_edit_details_and_node_sync(self):
        admin_token = self._get_admin_token()

        try:
            # Update EMP02: name, email, zone, states
            update_payload = {
                "old_emp_id": "EMP02",
                "new_emp_id": "EMP02",
                "full_name": "Pooja V. Verma",
                "email": "pooja.verma@ndli.edu.in",
                "zone": "Central",
                "assigned_states": "Madhya Pradesh, Chhattisgarh, Vidarbha",
                "is_active": "1"
            }

            status, res = self._post_json("/api/admin/employees/update", update_payload, token=admin_token)
            self.assertEqual(status, 200)
            self.assertTrue(res.get("success"))
            self.assertEqual(res["employee"]["full_name"], "Pooja V. Verma")

            # 1. Verify in Master Users CSV
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            emp02_m = next((u for u in users if u["id"] == "EMP02"), None)
            self.assertIsNotNone(emp02_m)
            self.assertEqual(emp02_m["full_name"], "Pooja V. Verma")
            self.assertEqual(emp02_m["email"], "pooja.verma@ndli.edu.in")
            self.assertIn("Vidarbha", emp02_m["assigned_states"])

            # 2. Verify in dedicated Node credentials.csv
            node_cred = SyncEngine.get_employee_credentials_path("EMP02")
            self.assertTrue(node_cred.exists())
            node_users = CSVEngine.read_all(node_cred, USER_FIELDS)
            self.assertEqual(len(node_users), 1)
            self.assertEqual(node_users[0]["full_name"], "Pooja V. Verma")
            self.assertEqual(node_users[0]["email"], "pooja.verma@ndli.edu.in")

            # 3. Verify in Master Quotas (Quota counts preserved!)
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            emp02_q = next((q for q in quotas if q["emp_id"] == "EMP02"), None)
            self.assertIsNotNone(emp02_q)
            self.assertEqual(emp02_q["employee_name"], "Pooja V. Verma")
        finally:
            # Restore EMP02's seed profile: startup no longer re-seeds existing
            # accounts (bughunt fix), so tests must clean up after themselves.
            # Leaving the renamed email behind broke test_auth's seed-email
            # logins in every subsequent run (verified: 2 cascading failures).
            self._post_json("/api/admin/employees/update", {
                "old_emp_id": "EMP02", "new_emp_id": "EMP02", "full_name": "Pooja Verma (Central Zone)",
                "email": "emp.central@ndli.edu.in", "zone": "Central",
                "assigned_states": "Madhya Pradesh, Chhattisgarh"
            }, token=admin_token)

    # -------------------------------------------------------------
    # 2. Test Password Change & Retention
    # -------------------------------------------------------------
    def test_employee_password_change_and_retention(self):
        admin_token = self._get_admin_token()

        try:

            # Update EMP03 with new password
            new_pwd = "NewWestPass#2026!"
            update_payload = {
                "old_emp_id": "EMP03",
                "new_emp_id": "EMP03",
                "full_name": "Amit Patel",
                "email": "emp.west@ndli.edu.in",
                "password": new_pwd,
                "zone": "West",
                "assigned_states": "Rajasthan, Gujarat, Maharashtra, Goa"
            }

            status, res = self._post_json("/api/admin/employees/update", update_payload, token=admin_token)
            self.assertEqual(status, 200)

            # Verify old password fails
            old_status, old_res = self._post_json("/api/auth/login", {
                "email": "EMP03",
                "password": "Seed#EMP03-Rotated2026"
            })
            self.assertEqual(old_status, 401)

            # Verify new password succeeds
            new_status, new_res = self._post_json("/api/auth/login", {
                "email": "EMP03",
                "password": new_pwd
            })
            self.assertEqual(new_status, 200)
            self.assertTrue(new_res.get("success"))

            # Now edit EMP03 WITHOUT password field — verify password is retained
            update_payload2 = {
                "old_emp_id": "EMP03",
                "new_emp_id": "EMP03",
                "full_name": "Amit K. Patel",
                "email": "emp.west@ndli.edu.in",
                "password": "",  # Empty password must keep existing hash!
                "zone": "West",
                "assigned_states": "Rajasthan, Gujarat, Maharashtra, Goa"
            }
            status2, res2 = self._post_json("/api/admin/employees/update", update_payload2, token=admin_token)
            self.assertEqual(status2, 200)

            # Verify new password STILL works
            new_status2, new_res2 = self._post_json("/api/auth/login", {
                "email": "EMP03",
                "password": new_pwd
            })
            self.assertEqual(new_status2, 200)
        finally:
            # Restore EMP03's seed credentials/profile: startup no longer re-seeds
            # existing accounts (bughunt fix), so tests must clean up after themselves.
            self._post_json("/api/admin/employees/update", {
                "old_emp_id": "EMP03", "new_emp_id": "EMP03", "full_name": "Amit Patel (West Zone)",
                "email": "emp.west@ndli.edu.in", "password": "Seed#EMP03-Rotated2026", "zone": "West",
                "assigned_states": "Rajasthan, Gujarat, Maharashtra, Goa, Daman and Diu, Dadar & Nagar Haveli"
            }, token=admin_token)

    # -------------------------------------------------------------
    # 3. Test Employee Code/ID Change & Folder Rename & Relinking
    # -------------------------------------------------------------
    def test_employee_id_change_and_folder_rename(self):
        admin_token = self._get_admin_token()
        test_ids = ["EMP99", "EMP99_NEW"]
        self._cleanup_test_ids(test_ids)

        try:
            # Provision a test employee EMP99 first
            prov_status, prov_res = self._post_json("/api/admin/employees/create", {
                "emp_id": "EMP99",
                "full_name": "Test Rename Officer",
                "email": "test.rename@ndli.edu.in",
                "password": "TestPass#2026",
                "zone": "North",
                "assigned_states": "Delhi"
            }, token=admin_token)
            self.assertEqual(prov_status, 200)

            # Verify initial directory exists
            old_dir = SyncEngine.get_employee_dir("EMP99")
            self.assertTrue(old_dir.exists())

            # Log a support activity under EMP99
            act_row = SyncEngine.log_support_activity("EMP99", "Online training", notes="Initial EMP99 note")
            self.assertEqual(act_row["emp_id"], "EMP99")

            # Now Rename EMP99 to EMP99_NEW
            rename_payload = {
                "old_emp_id": "EMP99",
                "new_emp_id": "EMP99_NEW",
                "full_name": "Test Rename Officer Updated",
                "email": "test.rename.updated@ndli.edu.in",
                "zone": "North",
                "assigned_states": "Delhi, Punjab"
            }

            r_status, r_res = self._post_json("/api/admin/employees/update", rename_payload, token=admin_token)
            self.assertEqual(r_status, 200)
            self.assertTrue(r_res.get("success"))
            self.assertEqual(r_res["employee"]["id"], "EMP99_NEW")

            # Verify old folder no longer exists and new folder exists
            new_dir = SyncEngine.get_employee_dir("EMP99_NEW")
            self.assertTrue(new_dir.exists())
            self.assertFalse(old_dir.exists())

            # Verify credentials in new folder
            node_cred = SyncEngine.get_employee_credentials_path("EMP99_NEW")
            self.assertTrue(node_cred.exists())
            node_users = CSVEngine.read_all(node_cred, USER_FIELDS)
            self.assertEqual(node_users[0]["id"], "EMP99_NEW")

            # Verify master activities updated
            m_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            emp99_acts = [a for a in m_acts if a["emp_id"] == "EMP99_NEW"]
            self.assertGreaterEqual(len(emp99_acts), 1)

            # Verify master quotas updated
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            q_new = next((q for q in quotas if q["emp_id"] == "EMP99_NEW"), None)
            self.assertIsNotNone(q_new)
            self.assertEqual(q_new["employee_name"], "Test Rename Officer Updated")
            q_old = next((q for q in quotas if q["emp_id"] == "EMP99"), None)
            self.assertIsNone(q_old)
        finally:
            self._cleanup_test_ids(test_ids)

    # -------------------------------------------------------------
    # 4. Test Collision Prevention
    # -------------------------------------------------------------
    def test_collision_prevention(self):
        admin_token = self._get_admin_token()

        # Try to change EMP01's email to EMP04's email
        status, res = self._post_json("/api/admin/employees/update", {
            "old_emp_id": "EMP01",
            "new_emp_id": "EMP01",
            "full_name": "Rohan Sharma",
            "email": "emp.east@ndli.edu.in",  # EMP04's email
            "zone": "North",
            "assigned_states": "Delhi"
        }, token=admin_token)
        self.assertEqual(status, 400)
        self.assertIn("already in use", res.get("message", "").lower())

        # Try to change EMP01's ID to EMP04's ID
        status2, res2 = self._post_json("/api/admin/employees/update", {
            "old_emp_id": "EMP01",
            "new_emp_id": "EMP04",  # Already exists
            "full_name": "Rohan Sharma",
            "email": "emp.north@ndli.edu.in",
            "zone": "North",
            "assigned_states": "Delhi"
        }, token=admin_token)
        self.assertEqual(status2, 400)
        self.assertIn("already exists", res2.get("message", "").lower())

    # -------------------------------------------------------------
    # 5. Security Gating: Employees Cannot Access Admin Management
    # -------------------------------------------------------------
    def test_employee_forbidden_from_admin_management(self):
        # 1. Login as standard employee EMP01
        emp_token = self._get_employee_token("EMP01", "Seed#EMP01-Rotated2026")

        # 2. Employee attempts GET /api/admin/employees
        status1, res1 = self._get_json("/api/admin/employees", token=emp_token)
        self.assertEqual(status1, 403)
        self.assertTrue(res1.get("error"))
        self.assertIn("access denied", res1.get("message", "").lower())

        # 3. Employee attempts POST /api/admin/employees/status (tamper with access)
        status2, res2 = self._post_json("/api/admin/employees/status", {
            "user_id": "EMP02",
            "is_active": False
        }, token=emp_token)
        self.assertEqual(status2, 403)
        self.assertTrue(res2.get("error"))

        # 4. Employee attempts POST /api/admin/employees/create
        status3, res3 = self._post_json("/api/admin/employees/create", {
            "emp_id": "EMP_HACK",
            "full_name": "Hacker",
            "email": "hack@ndli.edu.in",
            "password": "HackPass#2026",
            "zone": "North",
            "assigned_states": "Delhi"
        }, token=emp_token)
        self.assertEqual(status3, 403)

        # 5. Employee attempts POST /api/admin/employees/update
        status4, res4 = self._post_json("/api/admin/employees/update", {
            "old_emp_id": "EMP02",
            "new_emp_id": "EMP02",
            "full_name": "Tampered Name",
            "email": "tampered@ndli.edu.in",
            "zone": "Central",
            "assigned_states": "Madhya Pradesh"
        }, token=emp_token)
        self.assertEqual(status4, 403)

        # 6. Unauthenticated (no token / anonymous) attempts MUST be rejected with 401
        anon_status1, _ = self._get_json("/api/admin/employees", token="invalid-anon-session")
        self.assertEqual(anon_status1, 401)

        anon_status2, _ = self._post_json("/api/admin/employees/status", {
            "user_id": "EMP02",
            "is_active": False
        }, token="invalid-anon-session")
        self.assertEqual(anon_status2, 401)

        anon_status3, _ = self._post_json("/api/admin/employees/create", {
            "emp_id": "EMP_ANON",
            "full_name": "Anon",
            "email": "anon@ndli.edu.in",
            "password": "AnonPass#2026",
            "zone": "North",
            "assigned_states": "Delhi"
        }, token="invalid-anon-session")
        self.assertEqual(anon_status3, 401)

        anon_status4, _ = self._post_json("/api/admin/employees/update", {
            "old_emp_id": "EMP02",
            "new_emp_id": "EMP02",
            "full_name": "Anon Update",
            "email": "anon@ndli.edu.in",
            "zone": "Central",
            "assigned_states": "Madhya Pradesh"
        }, token="invalid-anon-session")
        self.assertEqual(anon_status4, 401)

    def test_admin_authorized_for_admin_management(self):
        admin_token = self._get_admin_token()

        # Admin GET /api/admin/employees -> 200
        status, res = self._get_json("/api/admin/employees", token=admin_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(res["count"], 7)

    def test_duplicate_creation_rejected(self):
        admin_token = self._get_admin_token()

        # Duplicate ID on create
        status1, res1 = self._post_json("/api/admin/employees/create", {
            "emp_id": "EMP01",
            "full_name": "Duplicate Rohan",
            "email": "unique.rohan@ndli.edu.in",
            "password": "Pass#2026",
            "zone": "North",
            "assigned_states": "Delhi"
        }, token=admin_token)
        self.assertEqual(status1, 400)
        self.assertIn("already exists", res1.get("message", "").lower())

        # Duplicate email on create
        status2, res2 = self._post_json("/api/admin/employees/create", {
            "emp_id": "EMP98",
            "full_name": "Duplicate Email Guy",
            "email": "emp.north@ndli.edu.in",
            "password": "Pass#2026",
            "zone": "North",
            "assigned_states": "Delhi"
        }, token=admin_token)
        self.assertEqual(status2, 400)
        self.assertIn("already in use", res2.get("message", "").lower())

    # -------------------------------------------------------------
    # 6. Live Dynamic Employee Roster & Profile Endpoints
    # -------------------------------------------------------------
    def test_employees_roster_and_profile_endpoints(self):
        # 1. Directory list of active employees (No credentials/passwords leaked!)
        status, res = self._get_json("/api/employees/roster")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(res["count"], 7)
        for emp in res["employees"]:
            self.assertNotIn("password_hash", emp)
            self.assertNotIn("salt", emp)
            self.assertIn("id", emp)
            self.assertIn("full_name", emp)
            self.assertIn("zone", emp)

        # 2. Individual Employee Profile
        status_p, res_p = self._get_json("/api/employees/profile?id=EMP01")
        self.assertEqual(status_p, 200)
        self.assertTrue(res_p.get("found"))
        self.assertEqual(res_p["employee"]["id"], "EMP01")
        self.assertIn("clubs_approved_count", res_p["employee"])
        self.assertIn("support_logs_count", res_p["employee"])

        # 3. Dynamic reflect in /api/auth/me after admin update
        emp_token = self._get_employee_token("EMP04", "Seed#EMP04-Rotated2026")
        status_me, res_me = self._get_json("/api/auth/me", token=emp_token)
        self.assertEqual(status_me, 200)

        # Admin modifies EMP04's name
        admin_token = self._get_admin_token()
        self._post_json("/api/admin/employees/update", {
            "old_emp_id": "EMP04",
            "new_emp_id": "EMP04",
            "full_name": "Debabrata D. Ghosh",
            "email": "emp.east@ndli.edu.in",
            "zone": "East",
            "assigned_states": "Bihar, Jharkhand, West Bengal, Odisha"
        }, token=admin_token)

        # Employee calls /api/auth/me again — must dynamically reflect updated name!
        status_me2, res_me2 = self._get_json("/api/auth/me", token=emp_token)
        self.assertEqual(status_me2, 200)
        self.assertEqual(res_me2["user"]["full_name"], "Debabrata D. Ghosh")

    # -------------------------------------------------------------
    # 7. Test Active Session Propagation on Employee ID Rename
    # -------------------------------------------------------------
    def test_employee_id_rename_propagates_to_active_session(self):
        admin_token = self._get_admin_token()
        test_ids = ["EMP88", "EMP88_RENAMED"]
        self._cleanup_test_ids(test_ids)

        try:
            # 1. Provision EMP88
            p_status, _ = self._post_json("/api/admin/employees/create", {
                "emp_id": "EMP88",
                "full_name": "Suresh Raina",
                "email": "suresh.raina@ndli.edu.in",
                "password": "RainaPass#2026",
                "zone": "North",
                "assigned_states": "Uttar Pradesh"
            }, token=admin_token)
            self.assertEqual(p_status, 200)

            # 2. Login as EMP88 to obtain active session
            l_status, l_res = self._post_json("/api/auth/login", {
                "email": "EMP88",
                "password": "RainaPass#2026"
            })
            self.assertEqual(l_status, 200)
            emp_token = l_res["session"]["token"]

            # 3. Admin renames EMP88 to EMP88_RENAMED and updates Zone to Central
            u_status, u_res = self._post_json("/api/admin/employees/update", {
                "old_emp_id": "EMP88",
                "new_emp_id": "EMP88_RENAMED",
                "full_name": "Suresh K. Raina",
                "email": "suresh.raina@ndli.edu.in",
                "zone": "Central",
                "assigned_states": "Madhya Pradesh"
            }, token=admin_token)
            self.assertEqual(u_status, 200)

            # 4. Existing employee session calls /api/auth/me — must reflect EMP88_RENAMED!
            me_status, me_res = self._get_json("/api/auth/me", token=emp_token)
            self.assertEqual(me_status, 200)
            self.assertEqual(me_res["user"]["user_id"], "EMP88_RENAMED")
            self.assertEqual(me_res["user"]["full_name"], "Suresh K. Raina")
            self.assertEqual(me_res["user"]["zone"], "Central")
        finally:
            self._cleanup_test_ids(test_ids)

    # -------------------------------------------------------------
    # 8. Test Blocked Employee Operations Rejected Across All Endpoints
    # -------------------------------------------------------------
    def test_blocked_employee_operations_rejected(self):
        admin_token = self._get_admin_token()
        test_ids = ["EMP77"]
        self._cleanup_test_ids(test_ids)

        try:
            # 1. Provision EMP77
            self._post_json("/api/admin/employees/create", {
                "emp_id": "EMP77",
                "full_name": "Blocked Worker",
                "email": "blocked.worker@ndli.edu.in",
                "password": "WorkerPass#2026",
                "zone": "East",
                "assigned_states": "Bihar"
            }, token=admin_token)

            # 2. Block EMP77
            b_status, _ = self._post_json("/api/admin/employees/status", {
                "user_id": "EMP77",
                "is_active": False
            }, token=admin_token)
            self.assertEqual(b_status, 200)

            # 3. Attempt activity log under blocked EMP77 -> 403
            act_status, act_res = self._post_json("/api/activity/log", {
                "emp_id": "EMP77",
                "support_type": "Phone call",
                "notes": "Attempt while blocked"
            })
            self.assertEqual(act_status, 403)
            self.assertIn("blocked", act_res.get("message", "").lower())

            # 4. Attempt club creation under blocked EMP77 -> 403
            club_status, club_res = self._post_json("/api/clubs/create", {
                "emp_id": "EMP77",
                "club_id": "NDLI-EMP77-101",
                "reg_no": "REG-77-001",
                "institution_name": "Test Institute",
                "state": "Bihar",
                "patron_email": "patron@test.edu",
                "president_email": "pres@test.edu",
                "secretary_email": "sec@test.edu"
            })
            self.assertEqual(club_status, 403)
            self.assertIn("blocked", club_res.get("message", "").lower())
        finally:
            self._cleanup_test_ids(test_ids)


if __name__ == "__main__":
    unittest.main()
