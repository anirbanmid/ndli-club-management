"""
Tests for Public Certificate Verification & QR Code Landing Endpoints
"""
import unittest
import json
import urllib.request
import urllib.error
from pathlib import Path
import threading
import time

from config import BASE_DIR, DATA_DIR, MASTER_CLUBS_CSV
from db.schemas import CLUB_FIELDS
from db.csv_engine import CSVEngine
from app import ThreadedHTTPServer, NDLIRequestHandler


class TestCertificateVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 18099
        cls.server = ThreadedHTTPServer(("127.0.0.1", cls.port), NDLIRequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        time.sleep(0.5)

        # Seed a test club if not present
        all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS, copy=False)
        cls.test_reg = "NDLI-TEST-VERIFY-01"
        cls.test_cid = "9999"
        cls.test_name = "Indian Institute of Science & Technology Verification Test"

        has_test_club = any(c.get("reg_no") == cls.test_reg for c in all_clubs)
        if not has_test_club:
            CSVEngine.append_row(MASTER_CLUBS_CSV, CLUB_FIELDS, {
                "club_id": cls.test_cid,
                "reg_no": cls.test_reg,
                "institution_name": cls.test_name,
                "state": "West Bengal",
                "zone": "East",
                "patron_email": "patron@test.ac.in",
                "president_email": "pres@test.ac.in",
                "secretary_email": "sec@test.ac.in",
                "date_of_approval": "2024-01-15",
                "last_renewal_date": "2025-01-15",
                "renewal_date": "2027-01-15",
                "status": "Active",
                "approved_by_emp_id": "EMP01",
                "updated_at": "2026-01-01T00:00:00",
                "submission_timestamp": "2024-01-10T10:00:00",
                "next_renewal_date": "2027-01-15"
            })

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_01_public_verify_html_page_served(self):
        """GET /verify and /certificate/verify should serve the public verification portal without auth."""
        status, body, headers = self._get("/verify")
        self.assertEqual(status, 200)
        self.assertIn(b"text/html", headers.get("Content-Type", b"").encode("utf-8") if isinstance(headers.get("Content-Type"), str) else headers.get("Content-Type", b""))
        self.assertIn(b"Official Certificate Verification", body)
        self.assertIn(b"National Digital Library of India", body)

        # Alternative alias
        status2, body2, _ = self._get("/certificate/verify")
        self.assertEqual(status2, 200)
        self.assertIn(b"Official Certificate Verification", body2)

    def test_02_public_api_verify_missing_params(self):
        """GET /api/certificate/verify without reg or id returns 400 Bad Request."""
        status, body, _ = self._get("/api/certificate/verify")
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_03_public_api_verify_valid_club(self):
        """GET /api/certificate/verify?reg=<valid> returns valid: True and verified details publicly."""
        status, body, _ = self._get(f"/api/certificate/verify?reg={self.test_reg}")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("valid"))
        self.assertTrue(data.get("is_active"))
        self.assertEqual(data.get("status"), "ACTIVE & VALID")

        club = data.get("club", {})
        self.assertEqual(club.get("reg_no"), self.test_reg)
        self.assertEqual(club.get("club_id"), self.test_cid)
        self.assertEqual(club.get("institution_name"), self.test_name)
        self.assertEqual(club.get("state"), "West Bengal")
        self.assertEqual(club.get("zone"), "East")
        self.assertIn("IIT Kharagpur", club.get("issuing_authority", ""))

    def test_04_public_api_verify_by_club_id(self):
        """Lookup by club_id parameter also succeeds."""
        status, body, _ = self._get(f"/api/certificate/verify?id={self.test_cid}")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("valid"))
        self.assertEqual(data["club"]["reg_no"], self.test_reg)

    def test_05_public_api_verify_unregistered_club(self):
        """Query for a non-existent registration returns valid: False with an unverified badge."""
        status, body, _ = self._get("/api/certificate/verify?reg=NDLI-NONEXISTENT-999")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertFalse(data.get("valid"))
        self.assertEqual(data.get("status"), "UNVERIFIED")

    def test_06_qrcode_js_asset_and_certificate_engine_integration(self):
        """Verify qrcode.min.js asset is served and certificate_engine.js includes QR rendering."""
        status, body, headers = self._get("/static/js/qrcode.min.js")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 1000)

        # Check CertificateEngine includes QR code rendering block
        engine_file = BASE_DIR / "static" / "js" / "certificate_engine.js"
        self.assertTrue(engine_file.exists())
        code = engine_file.read_text(encoding="utf-8")
        self.assertIn("drawVerificationQRCode", code)
        self.assertIn("SCAN TO VERIFY", code)
        self.assertIn("/verify?reg=", code)


if __name__ == "__main__":
    unittest.main()
