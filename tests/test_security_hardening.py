"""
Security hardening regression tests.

Locks in the fixes from the 2026-09-23 security review:
  1. Path traversal to database files is blocked (hash-leak fix)
  2. The hardcoded admin password backdoor is gone
  3. Self-service password change works and actually rotates credentials
  4. Unauthenticated writes are rejected (401)
  5. Admin endpoints reject anonymous and non-admin callers
  6. Cross-employee identity spoofing is rejected (403)
  7. Session tokens in query strings are no longer accepted
"""
import http.client
import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer

from app import NDLIRequestHandler
from auth import AuthService
from init_db import initialize_database

SEC_EMP_A = "SECEMPA"
SEC_EMP_B = "SECEMPB"
SEC_ADMIN = "SECADM1"


class TestSecurityHardening(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        initialize_database()
        # Dedicated test identities with known passwords (reset every run so
        # the suite is idempotent regardless of previous runs).
        AuthService.register_or_update_user(
            SEC_EMP_A, "secepa@ndli.test", "EmpA#2026pass", "Security Probe A",
            role="EMPLOYEE", zone="North", assigned_states="Delhi")
        AuthService.register_or_update_user(
            SEC_EMP_B, "secepb@ndli.test", "EmpB#2026pass", "Security Probe B",
            role="EMPLOYEE", zone="West", assigned_states="Goa")
        AuthService.register_or_update_user(
            SEC_ADMIN, "secadm@ndli.test", "Adm1#2026pass", "Security Probe Admin",
            role="ADMIN", zone="Central", assigned_states="All India")

        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        # Clean up probe test users so other test suites maintain pristine state
        from config import MASTER_USERS_CSV, USER_FIELDS, BASE_DIR
        from db.csv_engine import CSVEngine
        import shutil
        users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
        clean_users = [u for u in users if u.get("id") not in (SEC_EMP_A, SEC_EMP_B, SEC_ADMIN)]
        CSVEngine.write_all(MASTER_USERS_CSV, USER_FIELDS, clean_users)
        for emp in (SEC_EMP_A.lower(), SEC_EMP_B.lower()):
            p = BASE_DIR / "data" / "employees" / emp
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

    def setUp(self):
        # Reset probe identities every test so execution order never matters
        # (change-password tests rotate these credentials mid-run).
        AuthService.register_or_update_user(
            SEC_EMP_A, "secepa@ndli.test", "EmpA#2026pass", "Security Probe A",
            role="EMPLOYEE", zone="North", assigned_states="Delhi")
        AuthService.register_or_update_user(
            SEC_EMP_B, "secepb@ndli.test", "EmpB#2026pass", "Security Probe B",
            role="EMPLOYEE", zone="West", assigned_states="Goa")

    # ---------- helpers ----------
    def _login(self, identifier, password):
        data = json.dumps({"email": identifier, "password": password}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/auth/login", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode())
        return payload["session"]["token"]

    def _request(self, method, path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode() or "{}"
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"raw": raw}

    def _raw_get(self, raw_path):
        """Sends a request line verbatim (no client-side path normalization)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("GET", raw_path, skip_host=False, skip_accept_encoding=True)
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    # ---------- 1. path traversal ----------
    def test_path_traversal_to_database_blocked(self):
        for raw_path in [
            "/static/../data/master/master_users.csv",
            "/docs/../data/employees/emp01/credentials.csv",
            "/static/../data/master/master_users.csv",
            "/static/..%2fdata/master/master_users.csv",
        ]:
            status, body = self._raw_get(raw_path)
            self.assertNotEqual(status, 200, f"{raw_path} was served!")
            self.assertNotIn(b"password_hash", body, f"{raw_path} leaked hashes!")

    def test_static_assets_still_served(self):
        status, body = self._raw_get("/static/css/style.css")
        self.assertEqual(status, 200)

    # ---------- 2. backdoor removed ----------
    def test_no_hardcoded_admin_backdoor(self):
        legacy_strings = ["Admin@" + "NDLI#" + "2026", "Admin@" + "IITKGP" + "2026"]
        for legacy in legacy_strings:
            status, data = self._request("POST", "/api/auth/login", {
                "email": "secadm@ndli.test", "password": legacy})
            self.assertEqual(status, 401, f"legacy password '{legacy}' was accepted!")
        # sanity: the real password still works
        status, data = self._request("POST", "/api/auth/login", {
            "email": "secadm@ndli.test", "password": "Adm1#2026pass"})
        self.assertEqual(status, 200)

    # ---------- 3. change-password provision ----------
    def test_change_password_flow(self):
        AuthService.register_or_update_user(
            SEC_EMP_A, "secepa@ndli.test", "EmpA#2026pass", "Security Probe A",
            role="EMPLOYEE", zone="North", assigned_states="Delhi")
        token = self._login("secepa@ndli.test", "EmpA#2026pass")

        # wrong current password rejected
        status, _ = self._request("POST", "/api/auth/change-password", {
            "current_password": "Wrong#2026pass", "new_password": "Newer#2026pass"}, token=token)
        self.assertIn(status, (400, 401))

        # too-short new password rejected
        status, _ = self._request("POST", "/api/auth/change-password", {
            "current_password": "EmpA#2026pass", "new_password": "short"}, token=token)
        self.assertEqual(status, 400)

        # successful rotation
        status, data = self._request("POST", "/api/auth/change-password", {
            "current_password": "EmpA#2026pass", "new_password": "Rotated#2026pass"}, token=token)
        self.assertEqual(status, 200, data)

        # old password dead, new password live
        status, _ = self._request("POST", "/api/auth/login", {
            "email": "secepa@ndli.test", "password": "EmpA#2026pass"})
        self.assertEqual(status, 401)
        status, _ = self._request("POST", "/api/auth/login", {
            "email": "secepa@ndli.test", "password": "Rotated#2026pass"})
        self.assertEqual(status, 200)

        # unauthenticated callers cannot change passwords
        status, _ = self._request("POST", "/api/auth/change-password", {
            "current_password": "Rotated#2026pass", "new_password": "Attacker#2026x"})
        self.assertEqual(status, 401)

    # ---------- 4. unauthenticated writes ----------
    def test_unauthenticated_writes_rejected(self):
        write_attempts = [
            ("POST", "/api/activity/log", {"emp_id": SEC_EMP_A, "support_type": "Online training", "notes": "x"}),
            ("POST", "/api/clubs/create", {"emp_id": SEC_EMP_A, "institution_name": "X", "state": "Delhi"}),
            ("POST", "/api/clubs/renew", {"emp_id": SEC_EMP_A, "club_id": "NDLI-TEST-1"}),
            ("POST", "/api/issues/create", {"club_id": "NDLI-TEST-1", "emp_id": SEC_EMP_A, "issue_note": "x"}),
            ("POST", "/api/admin/backup/trigger", {}),
            ("POST", "/api/sync/reconcile", {}),
        ]
        for method, path, body in write_attempts:
            status, _ = self._request(method, path, body)
            self.assertEqual(status, 401, f"{path} accepted an unauthenticated write")

    # ---------- 5. admin endpoints ----------
    def test_admin_endpoints_require_admin(self):
        admin_token = self._login("secadm@ndli.test", "Adm1#2026pass")
        emp_token = self._login("secepa@ndli.test", "EmpA#2026pass")

        # anonymous -> 401
        for path in ["/api/admin/metrics", "/api/admin/ai-insights",
                     "/api/admin/download/master-clubs", "/api/admin/backup/status"]:
            status, _ = self._request("GET", path)
            self.assertEqual(status, 401, f"{path} served anonymous admin data")

        # employee -> 403
        status, _ = self._request("GET", "/api/admin/metrics", token=emp_token)
        self.assertEqual(status, 403)

        # admin -> 200
        status, _ = self._request("GET", "/api/admin/metrics", token=admin_token)
        self.assertEqual(status, 200)

    def test_query_string_tokens_rejected(self):
        admin_token = self._login("secadm@ndli.test", "Adm1#2026pass")
        status, _ = self._raw_get(f"/api/admin/metrics?token={admin_token}")
        self.assertEqual(status, 401, "query-string token was accepted")

    # ---------- 6. identity spoofing ----------
    def test_cross_employee_identity_rejected(self):
        token_a = self._login("secepa@ndli.test", "EmpA#2026pass")
        status, _ = self._request("POST", "/api/activity/log", {
            "emp_id": SEC_EMP_B, "support_type": "Online training", "notes": "spoof"}, token=token_a)
        self.assertEqual(status, 403, "employee A logged activity as employee B")

    def test_club_reads_require_session(self):
        status, _ = self._request("GET", "/api/clubs/search?q=test")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
