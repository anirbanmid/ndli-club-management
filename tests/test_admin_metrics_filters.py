"""
Tests for Admin Dashboard 'Analytics & Geographic Scope' Zone and Year Filtering.
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
from state_zone_mapper import ZONE_STATE_MAP


class TestAdminMetricsFilters(unittest.TestCase):

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

    def test_default_metrics_returns_national_scope(self):
        status, data = self._get("/api/admin/metrics")
        self.assertEqual(status, 200)
        self.assertIn("filters", data)
        self.assertEqual(data["filters"]["zone"], "ALL")
        self.assertEqual(data["filters"]["year"], "ALL")
        self.assertIn("available_years", data)
        self.assertIn("2026", data["available_years"])

        cov = data["coverage_index"]
        self.assertGreaterEqual(cov["total_states"], 36)
        self.assertEqual(cov["zone_scope"], "ALL")
        self.assertGreaterEqual(data["summary"]["total_clubs"], 1)

    def test_filter_by_zone_north(self):
        status, data = self._get("/api/admin/metrics?zone=North")
        self.assertEqual(status, 200)
        self.assertEqual(data["filters"]["zone"], "North")

        cov = data["coverage_index"]
        self.assertEqual(cov["zone_scope"], "North")
        self.assertEqual(cov["total_states"], len(ZONE_STATE_MAP["North"]))

        north_states = set(ZONE_STATE_MAP["North"])
        for state, count in data["state_wise_clubs"].items():
            if count > 0:
                self.assertIn(state, north_states)

        for q in data["summary"]["quotas"]:
            self.assertEqual(q["emp_id"], "EMP01")

    def test_filter_by_year(self):
        status, data = self._get("/api/admin/metrics?year=2026")
        self.assertEqual(status, 200)
        self.assertEqual(data["filters"]["year"], "2026")
        self.assertIn("summary", data)

    def test_filter_by_zone_and_year_intersection(self):
        status, data = self._get("/api/admin/metrics?zone=Central&year=2026")
        self.assertEqual(status, 200)
        self.assertEqual(data["filters"]["zone"], "Central")
        self.assertEqual(data["filters"]["year"], "2026")

        central_states = set(ZONE_STATE_MAP["Central"])
        for state, count in data["state_wise_clubs"].items():
            if count > 0:
                self.assertIn(state, central_states)

        for q in data["summary"]["quotas"]:
            self.assertEqual(q["emp_id"], "EMP02")

    def test_invalid_filter_fallback(self):
        status, data = self._get("/api/admin/metrics?zone=NonExistentZone&year=1899")
        self.assertEqual(status, 200)
        self.assertEqual(data["summary"]["total_clubs"], 0)
        self.assertEqual(data["summary"]["total_activities"], 0)

    def test_frontend_markup_and_event_handlers(self):
        templates_to_check = [
            BASE_DIR / "templates" / "admin.html",
            BASE_DIR / "deployment_gas" / "Admin.html"
        ]
        for tmpl_path in templates_to_check:
            self.assertTrue(tmpl_path.exists())
            html = tmpl_path.read_text(encoding="utf-8")

            self.assertIn('id="filter-zone"', html)
            self.assertIn('onchange="applyFilters()"', html)
            self.assertIn('id="filter-year"', html)
            self.assertIn("populateYearFilterOptions", html)
            self.assertIn("loadDashboardData()", html)
            self.assertIn('id="zone-donut-title"', html)
            self.assertIn('id="kpi-clubs-desc"', html)


if __name__ == "__main__":
    unittest.main()
