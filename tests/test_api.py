"""
Integration tests for the NDLI HTTP Server and REST API endpoints.
"""
import unittest
import threading
import json
import urllib.request
import urllib.parse
from http.server import HTTPServer
from app import NDLIRequestHandler
from init_db import initialize_database
from config import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, INITIAL_EMPLOYEES

class TestAPIEndpoints(unittest.TestCase):

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
        from auth_util import admin_token
        token = token or admin_token(self.base_url, self.__class__.__name__)
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

    def _get(self, path: str, token: str = ""):
        from auth_util import admin_token
        token = token or admin_token(self.base_url, self.__class__.__name__)
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_root_health(self):
        status, data = self._get("/")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "online")

    def test_state_zone_map(self):
        status, data = self._get("/api/state-zone/map")
        self.assertEqual(status, 200)
        self.assertIn("North", data["zones"])
        self.assertIn("West Bengal", data["zone_to_states"]["East"])
        self.assertIn("all_states", data)
        self.assertIn("states", data)
        self.assertEqual(len(data["all_states"]), 37)
        self.assertEqual(len(data["states"]), 37)

    def test_states_endpoint(self):
        status, data = self._get("/api/states")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("states", data)
        self.assertIn("all_states", data)
        self.assertEqual(len(data["states"]), 37)
        self.assertIn("West Bengal", data["states"])

    def test_states_zones_endpoint(self):
        status, data = self._get("/api/states-zones")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("zones", data)
        self.assertIn("zone_to_states", data)
        self.assertIn("states", data)
        self.assertEqual(len(data["states"]), 37)

    def test_state_zone_lookup(self):
        status, data = self._get("/api/state-zone/lookup?state=Gujarat")
        self.assertEqual(status, 200)
        self.assertEqual(data["zone"], "West")

    def test_auth_login_and_me(self):
        status, data = self._post("/api/auth/login", {
            "email": DEFAULT_ADMIN_EMAIL,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        token = data["session"]["token"]

        # Validate with /api/auth/me
        status_me, data_me = self._get("/api/auth/me", token=token)
        self.assertEqual(status_me, 200)
        self.assertEqual(data_me["user"]["email"], DEFAULT_ADMIN_EMAIL)

    def test_club_approval_flow_and_quota_update(self):
        emp = INITIAL_EMPLOYEES[0]
        emp_id = emp["id"]

        # SEC C payload
        payload = {
            "emp_id": emp_id,
            "club_id": "NDLI-UP-201",
            "reg_no": "REG-2026-UP-201",
            "institution_name": "Aligarh Muslim University",
            "state": "Uttar Pradesh",
            "patron_email": "vc@amu.ac.in",
            "president_email": "ndli.pres@amu.ac.in",
            "secretary_email": "ndli.sec@amu.ac.in"
        }

        status, data = self._post("/api/clubs/create", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["club"]["zone"], "North")

        # Test Universal Search includes the new club
        s_status, s_data = self._get("/api/clubs/search?q=Aligarh")
        self.assertEqual(s_status, 200)
        self.assertGreaterEqual(s_data["count"], 1)

    def test_renewal_flow(self):
        payload = {
            "emp_id": "EMP01",
            "club_id": "NDLI-DL-102",
            "renewal_date": "2029-01-01"
        }
        status, data = self._post("/api/clubs/renew", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["club"]["renewal_date"], "2029-01-01")

    def test_renewal_flow_auto_calculate(self):
        # Omit renewal_date so it is calculated automatically
        payload = {
            "emp_id": "EMP01",
            "club_id": "NDLI-DL-102"
        }
        status, data = self._post("/api/clubs/renew", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertIn("renewal_date", data["club"])
        self.assertTrue(len(data["club"]["renewal_date"]) == 10)

    def test_admin_metrics_and_ai_insights(self):
        m_status, m_data = self._get("/api/admin/metrics")
        self.assertEqual(m_status, 200)
        self.assertIn("total_clubs", m_data["summary"])
        self.assertIn("renewal_attention_count", m_data["summary"])

        ai_status, ai_data = self._get("/api/admin/ai-insights")
        self.assertEqual(ai_status, 200)
        self.assertIn("strategic_recommendations", ai_data)
        self.assertIn("renewal_attention", ai_data)
        self.assertGreater(len(ai_data["strategic_recommendations"]), 0)

    def test_admin_renewal_attention_endpoint(self):
        status, data = self._get("/api/admin/renewal-attention")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("total_attention_count", data)
        self.assertIn("overdue_count", data)
        self.assertIn("expiring_soon_count", data)
        self.assertIn("clubs", data)

    def test_club_details_endpoint(self):
        status, data = self._get("/api/clubs/details?club_id=NDLI-AS-105")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("found"))
        club = data["club"]
        self.assertEqual(club["club_id"], "NDLI-AS-105")
        self.assertEqual(club["state"], "Assam")
        self.assertEqual(club["zone"], "North East")
        self.assertIn("reg_no", club)
        self.assertIn("institution_name", club)
        self.assertIn("patron_email", club)
        self.assertIn("president_email", club)
        self.assertIn("secretary_email", club)
        self.assertIn("approved_by_emp_id", club)
        self.assertIn("submission_timestamp", club)
        self.assertIn("renewal_date", club)
        self.assertIn("next_renewal_due_date", club)
        self.assertIn("status", club)
        self.assertIn("urgency", club)
        self.assertIn("attention_type", club)
        self.assertIn("days_overdue", club)
        self.assertIn("days_left", club)

        # 404 for non-existent club
        status_404, data_404 = self._get("/api/clubs/details?club_id=NON-EXISTENT-XYZ")
        self.assertEqual(status_404, 404)
        self.assertTrue(data_404.get("error"))

        # 400 when parameter missing
        status_400, data_400 = self._get("/api/clubs/details")
        self.assertEqual(status_400, 400)
        self.assertTrue(data_400.get("error"))

if __name__ == "__main__":
    unittest.main()
