"""
Tests for Public Certificate Verification & Signed QR Tokens (Option B).

Green field (2026-10-04): the public QR carries a SERVER-MINTED HMAC token.
Free-text lookup params (reg/reg_no/id/club_id) and the fuzzy matcher are gone
-- this file locks that: no query surface for enumeration, signatures verified,
exact registration lookup only.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
import json
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
import threading
import time

from config import BASE_DIR, DATA_DIR, MASTER_CLUBS_CSV
from db.schemas import CLUB_FIELDS
from db.csv_engine import CSVEngine
from app import ThreadedHTTPServer, NDLIRequestHandler
import qr_tokens


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

    def _post(self, path, payload, token=None):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    # ---------- public page ----------

    def test_01_public_verify_html_page_served(self):
        """GET /verify and /certificate/verify should serve the public verification portal without auth."""
        status, body, headers = self._get("/verify")
        self.assertEqual(status, 200)
        self.assertIn(b"Official Certificate Verification", body)
        self.assertIn(b"National Digital Library of India", body)

        status2, body2, _ = self._get("/certificate/verify")
        self.assertEqual(status2, 200)
        self.assertIn(b"Official Certificate Verification", body2)

    def test_01b_public_page_is_qr_only_no_search_no_staff_links(self):
        """Public window verifies ONLY the scanned certificate (club privacy, 2026-10-04):
        no editable search box, no staff/office login entry points."""
        status, body, _ = self._get("/verify")
        self.assertEqual(status, 200)
        # No search facility of any kind.
        self.assertNotIn(b'id="reg-input"', body)
        self.assertNotIn(b'search-form', body)
        self.assertNotIn(b'handleVerifySubmit', body)
        self.assertNotIn(b'Enter Registration No.', body)
        # No staff access from the public window.
        self.assertNotIn(b'Staff Portal', body)
        self.assertNotIn(b'Officer Login', body)
        self.assertNotIn(b'href="/login"', body)
        # The QR auto-verify path stays intact (signed token arrives in the QR link).
        self.assertIn(b'params.get("token")', body)
        self.assertIn(b'performVerification', body)
        self.assertIn(b'/api/certificate/verify?token=', body)
        # Legacy free-text lookup channel must be gone from the page.
        self.assertNotIn(b'params.get("reg")', body)
        self.assertNotIn(b'/api/certificate/verify?reg=', body)
        # Privacy stance is stated on the page.
        self.assertIn(b'club privacy', body)

    # ---------- signed token semantics ----------

    def test_02_public_api_verify_missing_token_400(self):
        """GET /api/certificate/verify without a signed token returns 400 (no free-text lookup)."""
        status, body, _ = self._get("/api/certificate/verify")
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_02b_legacy_free_text_params_rejected(self):
        """The old ?reg= / ?id= enumeration channel is removed, not aliased."""
        for q in [f"reg={self.test_reg}", f"id={self.test_cid}", "reg_no=NDLI-ANY", "club_id=9999"]:
            status, body, _ = self._get(f"/api/certificate/verify?{q}")
            self.assertEqual(status, 400, f"legacy param must be rejected: {q}")

    def test_03_signed_token_verifies_exact_club(self):
        """A server-minted token verifies publicly and returns exact club details."""
        token = qr_tokens.mint_qr_token(self.test_reg, self.test_cid)
        status, body, _ = self._get(f"/api/certificate/verify?token={urllib.parse.quote(token)}")
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

    def test_03b_mint_endpoint_requires_auth(self):
        """POST /api/certificate/qr-token is staff-only (401 anonymous)."""
        status, data = self._post("/api/certificate/qr-token", {"reg_no": self.test_reg})
        self.assertEqual(status, 401)

    def test_03c_mint_endpoint_scoped_and_exact(self):
        """Authenticated staff mint for exact registrations only; unknown reg -> 404."""
        from auth_util import admin_token
        tok = admin_token(self.base_url, scope="qrcert")
        status, data = self._post("/api/certificate/qr-token",
                                  {"reg_no": self.test_reg}, token=tok)
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertIn("token", data)
        self.assertTrue(data.get("verification_url", "").startswith("/verify?token="))

        status2, data2 = self._post("/api/certificate/qr-token",
                                    {"reg_no": "NDLI-NONEXISTENT-999"}, token=tok)
        self.assertEqual(status2, 404)

    def test_03d_employee_mint_scoped_to_own_clubs(self):
        """An employee may mint only for own/node clubs: EMP02 cannot mint EMP01's club."""
        from auth_util import employee_token
        tok = employee_token(self.base_url, scope="qrcert", emp_id="EMP02")
        status, data = self._post("/api/certificate/qr-token",
                                  {"reg_no": self.test_reg}, token=tok)
        self.assertEqual(status, 403)
        # ...but the owning employee (EMP01) can.
        tok1 = employee_token(self.base_url, scope="qrcert", emp_id="EMP01")
        status2, data2 = self._post("/api/certificate/qr-token",
                                    {"reg_no": self.test_reg}, token=tok1)
        self.assertEqual(status2, 200)
        self.assertTrue(data2.get("success"))

    def test_04_tampered_token_rejected(self):
        """Any signature/payload tampering yields UNVERIFIED, never club data."""
        token = qr_tokens.mint_qr_token(self.test_reg, self.test_cid)
        head, kid, payload, sig = token.split(".")
        for bad in [
            ".".join([head, kid, payload, sig[:-2] + "xx"]),        # bad sig
            ".".join([head, kid, payload + "AAAA", sig]),           # bad payload
            ".".join([head, "0" * 10, payload, sig]),               # foreign key id
            ".".join(["v0", kid, payload, sig]),                    # bad version
            "not-a-token",
        ]:
            status, body, _ = self._get(f"/api/certificate/verify?token={urllib.parse.quote(bad)}")
            self.assertEqual(status, 200)
            data = json.loads(body.decode("utf-8"))
            self.assertFalse(data.get("valid"))
            self.assertNotIn("club", data)

    def test_04b_token_for_unknown_reg_unverified(self):
        """A correctly-signed token whose registration no longer exists -> UNVERIFIED."""
        token = qr_tokens.mint_qr_token("NDLI-NONEXISTENT-999", "")
        status, body, _ = self._get(f"/api/certificate/verify?token={urllib.parse.quote(token)}")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertFalse(data.get("valid"))
        self.assertEqual(data.get("status"), "UNVERIFIED")

    def test_05_token_unit_roundtrip_and_key_rotation_hint(self):
        """qr_tokens unit semantics: roundtrip fields, key_id prefix, no expiry field."""
        token = qr_tokens.mint_qr_token(self.test_reg, self.test_cid)
        parts = token.split(".")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "v1")
        _, kid = qr_tokens.get_qr_key()
        self.assertEqual(parts[1], kid)  # key_id prefix enables later rotation
        verdict = qr_tokens.verify_qr_token(token)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["reg_no"], self.test_reg)
        self.assertEqual(verdict["club_id"], self.test_cid)
        # Long/no expiry by design: token has iat but verification never expires.
        self.assertIn("iat", verdict)

    # ---------- assets / engine integration ----------

    def test_06_qrcode_js_asset_and_certificate_engine_integration(self):
        """Verify qrcode.min.js asset is served and certificate_engine.js mints server-side tokens."""
        status, body, headers = self._get("/static/js/qrcode.min.js")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 1000)

        engine_file = BASE_DIR / "static" / "js" / "certificate_engine.js"
        self.assertTrue(engine_file.exists())
        code = engine_file.read_text(encoding="utf-8")
        self.assertIn("drawVerificationQRCode", code)
        self.assertIn("SCAN TO VERIFY", code)
        # Option B: QR URL is built from a SERVER-minted token, never from raw reg.
        self.assertIn("/api/certificate/qr-token", code)
        self.assertIn("verification_url", code)
        self.assertNotIn("/verify?reg=", code)


if __name__ == "__main__":
    unittest.main()
