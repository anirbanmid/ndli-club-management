"""
Unit and Integration Tests for:
1. Second-layer security confirmation on "Renewal Approved" (password verification, visual captcha markup)
2. Renewal certificate generation and download terminal (settings API, signature upload/download API)
3. Template bindings: <institution_name>, <reg_no>, <date_of_approval>, <renewal_date>
4. Certificate Engine high-DPI 300 DPI canvas & PDF/JPG export
"""
import unittest
import json
import base64
from pathlib import Path
from http.server import HTTPServer
import threading
import urllib.request
import urllib.parse
import urllib.error

from config import BASE_DIR, SERVER_HOST
from app import NDLIRequestHandler
from auth import AuthService

# Minimal 1x1 PNG in base64
MINIMAL_PNG_B64 = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class TestRenewalCertificateAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Pick an ephemeral test port
        cls.server_port = 8991
        cls.server = HTTPServer((SERVER_HOST, cls.server_port), NDLIRequestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://{SERVER_HOST}:{cls.server_port}"

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
        except Exception:
            pass

    def _get(self, path, token: str = ""):
        from auth_util import admin_token
        token = token or admin_token(self.base_url, self.__class__.__name__)
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = resp.read()
                headers = dict(resp.headers)
                return status, body, headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def _post(self, path, payload, token: str = ""):
        from auth_util import admin_token
        token = token or admin_token(self.base_url, self.__class__.__name__)
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = resp.read()
                headers = dict(resp.headers)
                return status, json.loads(body.decode("utf-8")), headers
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"raw": raw}
            return e.code, parsed, dict(e.headers)

    # -------------------------------------------------------------
    # 1. Test POST /api/auth/verify-password
    # -------------------------------------------------------------
    def test_verify_password_success(self):
        # EMP01 demo password is "Seed#EMP01-Rotated2026"
        status, data, _ = self._post("/api/auth/verify-password", {
            "user_id": "EMP01",
            "password": "Seed#EMP01-Rotated2026"
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("valid"))
        self.assertEqual(data.get("user_id"), "EMP01")

    def test_verify_password_failure_wrong_password(self):
        status, data, _ = self._post("/api/auth/verify-password", {
            "user_id": "EMP01",
            "password": "WrongPassword123!"
        })
        self.assertEqual(status, 401)
        self.assertFalse(data.get("success", True))

    def test_verify_password_missing_fields(self):
        status, data, _ = self._post("/api/auth/verify-password", {
            "user_id": "",
            "password": ""
        })
        self.assertEqual(status, 400)

    # -------------------------------------------------------------
    # 2. Test Certificate Settings API
    # -------------------------------------------------------------
    def test_certificate_settings_get_and_post(self):
        # 1. GET settings
        status, body, _ = self._get("/api/certificate/settings")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertIn("settings", data)
        self.assertIn("pi_name", data["settings"])
        self.assertIn("pi_affiliation", data["settings"])

        # 2. POST settings update
        new_name = "Prof. Partha Pratim Chakrabarti (New PI)"
        new_affil = "Director Emeritus & Principal Investigator, NDLI Project, IIT Kharagpur"
        status, data, _ = self._post("/api/certificate/settings", {
            "pi_name": new_name,
            "pi_affiliation": new_affil
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data["settings"]["pi_name"], new_name)
        self.assertEqual(data["settings"]["pi_affiliation"], new_affil)

        # 3. GET again and verify persistence
        status, body, _ = self._get("/api/certificate/settings")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["settings"]["pi_name"], new_name)
        self.assertEqual(data["settings"]["pi_affiliation"], new_affil)

    # -------------------------------------------------------------
    # 3. Test Certificate Signature Upload & Retrieval API
    # -------------------------------------------------------------
    def test_certificate_signature_upload_and_serve(self):
        # Upload signature image
        status, data, _ = self._post("/api/certificate/signature", {
            "image_data": MINIMAL_PNG_B64,
            "filename": "test_signature.png"
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("/api/certificate/signature", data.get("signature_url", ""))

        # Retrieve served image
        status, img_bytes, headers = self._get("/api/certificate/signature")
        self.assertEqual(status, 200)
        self.assertIn("image/png", headers.get("Content-Type", ""))
        self.assertGreater(len(img_bytes), 0)

        # Verify settings now show has_signature: True
        status, body, _ = self._get("/api/certificate/settings")
        settings_data = json.loads(body.decode("utf-8"))
        self.assertTrue(settings_data["settings"]["has_signature"])

    def test_certificate_signature_missing_data(self):
        status, data, _ = self._post("/api/certificate/signature", {
            "image_data": ""
        })
        self.assertEqual(status, 400)

    # -------------------------------------------------------------
    # 4. Test Frontend HTML Markup in templates/employee.html
    # -------------------------------------------------------------
    def test_employee_template_modals_and_script(self):
        tmpl_file = BASE_DIR / "templates" / "employee.html"
        self.assertTrue(tmpl_file.exists())
        html = tmpl_file.read_text(encoding="utf-8")

        # Security Confirmation Modal
        self.assertIn('id="renewal-security-modal"', html)
        self.assertIn('id="captcha-canvas"', html)
        self.assertIn('id="captcha-input"', html)
        self.assertIn('id="sec-confirm-password"', html)
        self.assertIn('id="btn-confirm-renewal-approval"', html)
        self.assertIn('confirmRenewalApproval()', html)
        self.assertIn('generateCaptchaCode()', html)

        # Renewal Certificate Terminal Modal
        self.assertIn('id="renewal-certificate-terminal-modal"', html)
        self.assertIn('id="certificate-canvas"', html)
        self.assertIn('width="2480"', html)
        self.assertIn('height="3508"', html)
        self.assertIn('id="cert-pi-signature-file"', html)
        self.assertIn('id="cert-pi-name-input"', html)
        self.assertIn('id="cert-pi-affil-input"', html)
        self.assertIn('downloadActiveCertificateJPG()', html)
        self.assertIn('downloadActiveCertificatePDF()', html)
        self.assertIn('printActiveCertificate()', html)

        # Certificate Terminal Launch Button in Edit section
        self.assertIn('id="btn-open-cert-terminal"', html)
        self.assertIn('openCertificateTerminalForActiveClub()', html)

        # Certificate Engine JS inclusion
        self.assertIn('src="/static/js/certificate_engine.js"', html)

    # -------------------------------------------------------------
    # 5. Test static/js/certificate_engine.js
    # -------------------------------------------------------------
    def test_certificate_engine_script_file(self):
        js_file = BASE_DIR / "static" / "js" / "certificate_engine.js"
        self.assertTrue(js_file.exists())
        code = js_file.read_text(encoding="utf-8")

        self.assertIn("CertificateEngine", code)
        self.assertIn("CANVAS_WIDTH = 2480", code)
        self.assertIn("CANVAS_HEIGHT = 3508", code)
        self.assertIn("renderCertificate", code)
        self.assertIn("downloadCertificateJPG", code)
        self.assertIn("downloadCertificatePDF", code)
        self.assertIn("createPdf14FromJpegBlob", code)
        self.assertIn("printCertificate", code)
        self.assertIn("Dr. Anirban Mukherjee", code)

        # Assertions for the 4 certificate modifications:
        # 1. Font size of registration details block (50px)
        self.assertIn("bold 50px", code)
        self.assertIn("Registration NO.:", code)
        # 2. Alignment with left side's logo
        self.assertIn("detailsCenterY = 2264", code)
        self.assertIn("detailsX = 1290", code)
        # 3. Input signature size of PI (enlarged to 600 x 220 px)
        self.assertIn("maxSigW = 600", code)
        self.assertIn("maxSigH = 220", code)
        self.assertIn("italic 76px", code)
        # 4. Typography matching Dr. B. Sutradhar's style (Rockwell bold 48px, sans-serif 35px)
        self.assertIn("bold 48px 'Rockwell'", code)
        self.assertIn("35px 'Calibri'", code)
        # 5. Lower-left signature and details placement
        self.assertIn("LOWER-LEFT", code)
        self.assertIn("sigLineStartX = 240", code)


if __name__ == "__main__":
    unittest.main()
