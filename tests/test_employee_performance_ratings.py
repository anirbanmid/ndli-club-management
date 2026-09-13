"""
Automated Test Suite for Admin Employee Performance Evaluation & Star Rating System.
Validates:
- Formula: 50% Club Approval + 30% Other Supports + 20% Offline Training + 10% Online Training
- Star Rating bounds: 1 to 5 Stars
- Dynamic Filtering: Year, Month, State
- Synchronized Presence in templates/admin.html, deployment_gas/Admin.html, and deployment_gas/Code.gs
"""
import unittest
import threading
import json
import urllib.request
import urllib.parse
from pathlib import Path
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from config import BASE_DIR


class TestEmployeePerformanceRatings(unittest.TestCase):

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

    def _get(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_default_employee_performance_matrix(self):
        status, data = self._get("/api/admin/employee-performance")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("filters", data)
        self.assertEqual(data["filters"]["year"], "ALL")
        self.assertEqual(data["filters"]["month"], "ALL")
        self.assertEqual(data["filters"]["state"], "ALL")

        # Verify weightages
        weightage = data.get("weightage", {})
        self.assertEqual(weightage.get("club_approval_pct"), 50)
        self.assertEqual(weightage.get("other_supports_pct"), 30)
        self.assertEqual(weightage.get("offline_training_pct"), 20)
        self.assertEqual(weightage.get("online_training_pct"), 10)

        # Verify officers
        officers = data.get("officers", [])
        self.assertGreaterEqual(len(officers), 1)

        # Check ranking and formula accuracy for every officer
        prev_score = float("inf")
        for idx, off in enumerate(officers, start=1):
            self.assertEqual(off["rank"], idx)
            clubs = off["clubs_approved"]
            other = off["other_supports"]
            offline = off["offline_training"]
            online = off["online_training"]

            expected_score = round((0.50 * clubs) + (0.30 * other) + (0.20 * offline) + (0.10 * online), 2)
            self.assertEqual(off["weighted_score"], expected_score)

            # Check star rating bounds (1 to 5 stars)
            self.assertIn(off["stars"], [1, 2, 3, 4, 5])
            self.assertEqual(len(off["stars_display"]), 5)
            self.assertTrue(off["stars_display"].startswith("★"))
            self.assertIn(f"{off['stars']}.0 / 5.0", off["rating_label"])

            # Verify descending sort order
            self.assertLessEqual(off["weighted_score"], prev_score)
            prev_score = off["weighted_score"]

    def test_filter_by_year(self):
        status, data = self._get("/api/admin/employee-performance?year=2026")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["filters"]["year"], "2026")
        self.assertIsInstance(data["officers"], list)

    def test_filter_by_month_numeric_and_name(self):
        status_num, data_num = self._get("/api/admin/employee-performance?month=3")
        self.assertEqual(status_num, 200)
        self.assertEqual(data_num["filters"]["month"], "3")

        status_name, data_name = self._get("/api/admin/employee-performance?month=March")
        self.assertEqual(status_name, 200)
        self.assertEqual(data_name["filters"]["month"], "March")

    def test_filter_by_state(self):
        status, data = self._get("/api/admin/employee-performance?state=West+Bengal")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["filters"]["state"], "West Bengal")

        for off in data["officers"]:
            self.assertIn("covers_selected_state", off)

    def test_templates_markup_integration(self):
        admin_tmpl = BASE_DIR / "templates" / "admin.html"
        self.assertTrue(admin_tmpl.exists())
        content = admin_tmpl.read_text(encoding="utf-8")

        self.assertIn("perf-filter-year", content)
        self.assertIn("perf-filter-month", content)
        self.assertIn("perf-filter-state", content)
        self.assertIn("employee-performance-table", content)
        self.assertIn("loadEmployeePerformance()", content)
        self.assertIn("resetPerformanceFilters()", content)
        self.assertIn("50%", content)
        self.assertIn("30%", content)
        self.assertIn("20%", content)
        self.assertIn("10%", content)

    def test_gas_deployment_sync(self):
        gas_code = BASE_DIR / "deployment_gas" / "Code.gs"
        self.assertTrue(gas_code.exists())
        code_content = gas_code.read_text(encoding="utf-8")
        self.assertIn('path === "admin/employee-performance"', code_content)
        self.assertIn("clubsApproved", code_content)
        self.assertIn("weightedScore", code_content)
        self.assertIn("stars", code_content)

        gas_admin = BASE_DIR / "deployment_gas" / "Admin.html"
        self.assertTrue(gas_admin.exists())
        admin_content = gas_admin.read_text(encoding="utf-8")
        self.assertIn("perf-filter-year", admin_content)
        self.assertIn("perf-filter-month", admin_content)
        self.assertIn("perf-filter-state", admin_content)
        self.assertIn("employee-performance-table", admin_content)
        self.assertIn("loadEmployeePerformance()", admin_content)


if __name__ == "__main__":
    unittest.main()
