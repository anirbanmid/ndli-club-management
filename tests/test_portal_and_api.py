"""
Comprehensive Integration Tests for NDLI Web Portals, Static Files, and Extended REST API Endpoints.
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
from auth import AuthService
from db.sync_engine import SyncEngine
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS


class TestPortalAndExtendedAPI(unittest.TestCase):

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

    def _get_raw(self, path: str, headers: dict = None):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read()

    def _get_json(self, path: str, token: str = ""):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        status, _, body = self._get_raw(path, headers)
        return status, json.loads(body.decode("utf-8"))

    def _post_json(self, path: str, payload: dict, token: str = ""):
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

    # 1. Test Static Files & Web Portal HTML Delivery
    def test_html_portal_serving(self):
        # Browser request with Accept: text/html to /
        status, ctype, body = self._get_raw("/", headers={"Accept": "text/html,application/xhtml+xml"})
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("NDLI Club Management System", body.decode("utf-8"))

        # Explicit /portal and /index.html
        status_p, _, body_p = self._get_raw("/portal")
        self.assertEqual(status_p, 200)
        self.assertIn("NDLI Club Management System", body_p.decode("utf-8"))

    def test_admin_portal_serving(self):
        status, ctype, body = self._get_raw("/admin")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("IIT Kharagpur", body.decode("utf-8"))
        self.assertIn("Performance Dashboard", body.decode("utf-8"))

    def test_employee_portal_and_regional_routes(self):
        # Generic employee portal
        status, ctype, body = self._get_raw("/employee")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        html = body.decode("utf-8")
        self.assertIn("NDLI Club Employee Portal", html)
        self.assertIn("employee-login-view", html)
        self.assertIn("Regional Employee Officer Sign-In", html)
        self.assertIn("live-clock", html)

        # Dedicated employee routes
        for emp in ["EMP01", "EMP02", "EMP03", "EMP04", "EMP05", "EMP06", "EMP07"]:
            status_e, _, body_e = self._get_raw(f"/employee/{emp}")
            self.assertEqual(status_e, 200)
            self.assertIn("NDLI Club Employee Portal", body_e.decode("utf-8"))

    def test_sec_c_state_dropdown_options_and_dual_deployment_parity(self):
        # 1. Verify python template employee.html
        status, _, body = self._get_raw("/employee")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="c-state"', html)
        self.assertIn('data-alias="sec-c-state"', html)
        self.assertIn('id="c-zone"', html)
        self.assertIn('data-alias="sec-c-zone"', html)
        self.assertIn('id="edit-state"', html)
        self.assertIn('value="West Bengal"', html)
        self.assertIn('value="Maharashtra"', html)
        self.assertIn('value="Delhi"', html)
        self.assertIn('value="Tamil Nadu"', html)
        self.assertIn('value="Dadar &amp; Nagar Haveli"', html)
        self.assertIn('value="Daman and Diu"', html)
        self.assertIn('DEFAULT_INDIAN_STATES', html)
        self.assertIn('sec-c-state', html)
        self.assertIn('_origQuerySelector', html)

        # 2. Verify Google Apps Script Employee.html dual-deployment parity
        with open("deployment_gas/Employee.html", "r", encoding="utf-8") as f:
            gas_html = f.read()
        self.assertIn('id="c-state"', gas_html)
        self.assertIn('data-alias="sec-c-state"', gas_html)
        self.assertIn('id="c-zone"', gas_html)
        self.assertIn('data-alias="sec-c-zone"', gas_html)
        self.assertIn('id="edit-state"', gas_html)
        self.assertIn('value="West Bengal"', gas_html)
        self.assertIn('value="Maharashtra"', gas_html)
        self.assertIn('value="Delhi"', gas_html)
        self.assertIn('value="Tamil Nadu"', gas_html)
        self.assertIn('value="Dadar &amp; Nagar Haveli"', gas_html)
        self.assertIn('value="Daman and Diu"', gas_html)
        self.assertIn('DEFAULT_INDIAN_STATES', gas_html)
        self.assertIn('_origQuerySelector', gas_html)

        # 3. Verify Code.gs handles state-zone/map, states, states-zones and has all 37 canonical states
        with open("deployment_gas/Code.gs", "r", encoding="utf-8") as f:
            code_gs = f.read()
        self.assertIn('states-zones', code_gs)
        self.assertIn('ALL_INDIAN_STATES', code_gs)
        self.assertIn('"Dadar & Nagar Haveli"', code_gs)
        self.assertIn('"Daman and Diu"', code_gs)

    def test_login_routes(self):
        # /login route
        status, ctype, body = self._get_raw("/login")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("Regional Employee Officer Sign-In", body.decode("utf-8"))

        # /employee/login route
        status2, _, body2 = self._get_raw("/employee/login")
        self.assertEqual(status2, 200)
        self.assertIn("Regional Employee Officer Sign-In", body2.decode("utf-8"))

    def test_auth_login_api_with_user_id_and_identifier(self):
        # Login using email field set to user_id 'EMP01'
        status, res = self._post_json("/api/auth/login", {"email": "EMP01", "password": "Seed#EMP01-Rotated2026"})
        self.assertEqual(status, 200)
        self.assertTrue(res.get("success"))
        self.assertEqual(res["session"]["user_id"], "EMP01")

        # Login using lowercase 'emp01'
        status2, res2 = self._post_json("/api/auth/login", {"email": "emp01", "password": "Seed#EMP01-Rotated2026"})
        self.assertEqual(status2, 200)
        self.assertTrue(res2.get("success"))

        # Login using explicit 'user_id' key in JSON body
        status3, res3 = self._post_json("/api/auth/login", {"user_id": "EMP02", "password": "Seed#EMP02-Rotated2026"})
        self.assertEqual(status3, 200)
        self.assertTrue(res3.get("success"))
        self.assertEqual(res3["session"]["user_id"], "EMP02")

    def test_static_assets_serving(self):
        # CSS
        status_css, ctype_css, body_css = self._get_raw("/static/css/style.css")
        self.assertEqual(status_css, 200)
        self.assertIn("text/css", ctype_css)
        self.assertIn(":root", body_css.decode("utf-8"))

        # JS
        status_js, ctype_js, body_js = self._get_raw("/static/js/app.js")
        self.assertEqual(status_js, 200)
        self.assertIn("application/javascript", ctype_js)
        self.assertIn("CLIENT_ZONE_MAP", body_js.decode("utf-8"))

    # 2. Test Club Update Endpoint (/api/clubs/update)
    def test_club_update_and_state_zone_resync(self):
        emp_id = "EMP03"
        club_id = "NDLI-MH-103"  # COEP Pune

        # Update institution name and change state to Karnataka (should auto-map to South Zone!)
        payload = {
            "emp_id": emp_id,
            "club_id": club_id,
            "institution_name": "COEP Technological University Pune",
            "state": "Karnataka",
            "patron_email": "director.coep@coeptech.ac.in"
        }

        status, data = self._post_json("/api/clubs/update", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["club"]["institution_name"], "COEP Technological University Pune")
        self.assertEqual(data["club"]["zone"], "South")  # Karnataka auto-mapped to South!

        # Verify updated record in master DB
        s_status, s_data = self._get_json("/api/clubs/search?q=Technological+University")
        self.assertEqual(s_status, 200)
        self.assertGreaterEqual(s_data["count"], 1)
        found = next((c for c in s_data["results"] if c["club_id"] == club_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["zone"], "South")

    def test_club_update_nonexistent_fails(self):
        payload = {
            "emp_id": "EMP01",
            "club_id": "NDLI-NONEXISTENT-9999",
            "institution_name": "Ghost University"
        }
        status, data = self._post_json("/api/clubs/update", payload)
        self.assertEqual(status, 404)
        self.assertTrue(data["error"])

    # 3. Test Admin Employee Access Control (/api/admin/employees/status & list)
    def test_admin_employee_roster_and_blocking_flow(self):
        # 0. Authenticate as Master Admin
        a_status, a_data = self._post_json("/api/auth/login", {
            "email": DEFAULT_ADMIN_EMAIL,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        self.assertEqual(a_status, 200)
        admin_token = a_data["session"]["token"]

        # 1. Get employee roster (Admin Authenticated)
        status, data = self._get_json("/api/admin/employees", token=admin_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(data["count"], 7)
        emp04 = next((e for e in data["employees"] if e["id"] == "EMP04"), None)
        self.assertIsNotNone(emp04)
        self.assertEqual(emp04["zone"], "East")

        # 2. Login as EMP04 to obtain active session
        l_status, l_data = self._post_json("/api/auth/login", {
            "email": "emp.east@ndli.edu.in",
            "password": "Seed#EMP04-Rotated2026"
        })
        self.assertEqual(l_status, 200)
        emp_token = l_data["session"]["token"]

        # Verify session is valid
        m_status, m_data = self._get_json("/api/auth/me", token=emp_token)
        self.assertEqual(m_status, 200)
        self.assertEqual(m_data["user"]["user_id"], "EMP04")

        # 3. Admin Blocks EMP04
        b_status, b_data = self._post_json("/api/admin/employees/status", {
            "user_id": "EMP04",
            "is_active": False
        }, token=admin_token)
        self.assertEqual(b_status, 200)
        self.assertEqual(b_data["is_active"], "0")

        # 4. Verify existing session is immediately revoked
        m2_status, _ = self._get_json("/api/auth/me", token=emp_token)
        self.assertEqual(m2_status, 401)

        # 5. Verify EMP04 cannot log in while blocked
        l2_status, l2_data = self._post_json("/api/auth/login", {
            "email": "emp.east@ndli.edu.in",
            "password": "Seed#EMP04-Rotated2026"
        })
        self.assertEqual(l2_status, 401)
        self.assertIn("blocked", l2_data["message"].lower())

        # 5b. Verify blocked EMP04 is forbidden from logging activities or creating clubs
        b_act_status, b_act_data = self._post_json("/api/activity/log", {
            "emp_id": "EMP04",
            "support_type": "Phone call and remote assistance",
            "notes": "Attempted activity while blocked"
        })
        self.assertEqual(b_act_status, 403)
        self.assertTrue(b_act_data.get("error"))

        # 6. Admin Unblocks EMP04
        u_status, u_data = self._post_json("/api/admin/employees/status", {
            "user_id": "EMP04",
            "is_active": True
        }, token=admin_token)
        self.assertEqual(u_status, 200)
        self.assertEqual(u_data["is_active"], "1")

        # 7. EMP04 can log in again
        l3_status, l3_data = self._post_json("/api/auth/login", {
            "email": "emp.east@ndli.edu.in",
            "password": "Seed#EMP04-Rotated2026"
        })
        self.assertEqual(l3_status, 200)
        self.assertTrue(l3_data["success"])

    # 4. Test Enriched Admin Metrics (Month-wise, Year-wise, Zone-wise, Support Types, Renewal Health, Coverage Index)
    def test_enriched_admin_metrics(self):
        status, data = self._get_json("/api/admin/metrics")
        self.assertEqual(status, 200)
        self.assertIn("year_wise_clubs", data)
        self.assertIn("month_wise_clubs", data)
        self.assertIn("zone_wise_clubs", data)
        self.assertIn("status_wise_clubs", data)
        self.assertIn("support_type_breakdown", data)
        self.assertIn("renewal_health", data)
        self.assertIn("coverage_index", data)
        self.assertIn("zone_efficiency", data)

        # Confirm zone counts contain expected keys
        self.assertIn("North", data["zone_wise_clubs"])
        self.assertGreaterEqual(len(data["year_wise_clubs"]), 1)

        # Confirm extended statistical analytics
        cov = data["coverage_index"]
        self.assertGreaterEqual(cov["total_states"], 36)
        self.assertGreaterEqual(cov["represented_count"], 1)
        self.assertGreaterEqual(cov["coverage_percentage"], 0.0)

        ren = data["renewal_health"]
        self.assertIn("active_validity_count", ren)
        self.assertIn("retention_rate_pct", ren)
        self.assertGreaterEqual(ren["retention_rate_pct"], 0.0)

        stypes = data["support_type_breakdown"]
        self.assertIn("Phone call and remote assistance", stypes)
        self.assertIn("Closing of OS Ticket", stypes)
        self.assertIn("Online training", stypes)
        self.assertIn("Offline training", stypes)

    # 5. Test All 7 Regional Employees User ID Logins
    def test_all_7_employees_user_id_authentication(self):
        for emp in INITIAL_EMPLOYEES:
            emp_id = emp["id"]
            pwd = emp["password"]
            status, res = self._post_json("/api/auth/login", {"user_id": emp_id, "password": pwd})
            self.assertEqual(status, 200, f"Login failed for {emp_id}")
            self.assertTrue(res.get("success"))
            self.assertEqual(res["session"]["user_id"], emp_id)
            self.assertEqual(res["session"]["role"], "EMPLOYEE")

            # Validate session token
            v_status, v_res = self._get_json("/api/auth/me", token=res["session"]["token"])
            self.assertEqual(v_status, 200)
            self.assertTrue(v_res["authenticated"])
            self.assertEqual(v_res["user"]["user_id"], emp_id)

    # 6. Test Clock & Local Time Rendering on Employee Portal
    def test_employee_portal_local_clock_template_rendering(self):
        status, _, body = self._get_raw("/employee")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")

        # Live clock badge elements exist across views (banner, navbar, login screen)
        self.assertIn('id="live-clock"', html)
        self.assertIn('id="nav-live-clock"', html)
        self.assertIn('id="login-live-clock"', html)
        self.assertIn('id="c-timestamp-display"', html)

        # Ensure obsolete UTC clock string is removed
        self.assertNotIn('toISOString().replace("T", " ").substring(0, 19) + " UTC"', html)

        # Ensure Indian Standard Time (IST - Asia/Kolkata) formatting and local date/time formatting exist
        self.assertIn("Asia/Kolkata", html)
        self.assertIn("IST", html)
        self.assertIn("toLocaleDateString", html)
        self.assertIn("toLocaleTimeString", html)
        self.assertIn("formatLocalTimestamp", html)
        self.assertIn("Date & Time (Local)", html)

    # 7. Test Explicit Login Screen, Form Blank State, and Navigation Links
    def test_employee_login_screen_and_navigation_links(self):
        # /login delivers explicit login screen
        status_l, _, body_l = self._get_raw("/login")
        self.assertEqual(status_l, 200)
        html_l = body_l.decode("utf-8")
        self.assertIn("employee-login-view", html_l)
        self.assertIn("Regional Employee Officer Sign-In", html_l)
        self.assertIn('id="login-identifier"', html_l)
        self.assertIn('id="login-password"', html_l)
        # Ensure password field is never pre-filled automatically
        self.assertIn('passInput.value = ""', html_l)

        # Index page contains direct Employee Login links
        status_idx, _, body_idx = self._get_raw("/portal")
        self.assertEqual(status_idx, 200)
        html_idx = body_idx.decode("utf-8")
        self.assertIn('href="/login"', html_idx)
        self.assertIn("Employee Sign-In", html_idx)

        # Admin page contains direct Employee Login link in navbar
        status_adm, _, body_adm = self._get_raw("/admin")
        self.assertEqual(status_adm, 200)
        html_adm = body_adm.decode("utf-8")
        self.assertIn('href="/login"', html_adm)

    # 8. Test Admin Renewal Attention & Club Details Modal Template Rendering & Scripts
    def test_admin_renewal_attention_and_club_details_modal_integration(self):
        status, _, body = self._get_raw("/admin")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")

        # Master Performance Dashboard Renewal Attention KPI Card
        self.assertIn('id="card-renewal-attention"', html)
        self.assertIn('onclick="openRenewalAttentionModal()"', html)
        self.assertIn('id="kpi-renewals"', html)

        # Renewal Attention List Modal markup
        self.assertIn('id="renewal-attention-modal"', html)
        self.assertIn('id="renewal-attention-tbody"', html)
        self.assertIn('id="attn-overdue-count"', html)
        self.assertIn('id="attn-expiring-count"', html)
        self.assertIn('id="attn-total-count"', html)
        self.assertIn('id="attn-search-input"', html)

        # Club Details Modal markup
        self.assertIn('id="club-details-modal"', html)
        self.assertIn('id="club-details-body"', html)
        self.assertIn('onclick="closeClubDetailsModal()"', html)

        # Modal controllers, handlers and formatters in script
        self.assertIn("openRenewalAttentionModal", html)
        self.assertIn("closeRenewalAttentionModal", html)
        self.assertIn("openClubDetailsModal", html)
        self.assertIn("closeClubDetailsModal", html)
        self.assertIn("backToAttentionList", html)
        self.assertIn("renderClubDetailsView", html)
        self.assertIn("formatLocalTimestamp", html)
        self.assertIn("calculateNextRenewalDate", html)

        # CSS modal and z-index specifications
        self.assertIn('z-index: 1000', html)
        self.assertIn('z-index: 1100', html)

    # 9. Test Static Assets (app.js & style.css) Modal & Formatter Rules
    def test_static_assets_modal_and_timestamp_definitions(self):
        # Verify app.js defines formatLocalTimestamp and exposes helpers globally
        s_js, _, body_js = self._get_raw("/static/js/app.js")
        self.assertEqual(s_js, 200)
        js_code = body_js.decode("utf-8")
        self.assertIn("function formatLocalTimestamp(ts)", js_code)
        self.assertIn("function calculateNextRenewalDate(estDateStr, lastRenDateStr)", js_code)
        self.assertIn("window.formatLocalTimestamp = formatLocalTimestamp", js_code)
        self.assertIn("Asia/Kolkata", js_code)

        # Verify style.css contains both .active and .open modal overlay styles and z-indices
        s_css, _, body_css = self._get_raw("/static/css/style.css")
        self.assertEqual(s_css, 200)
        css_code = body_css.decode("utf-8")
        self.assertIn(".modal-overlay.active", css_code)
        self.assertIn(".modal-overlay.open", css_code)
        self.assertIn("#club-details-modal", css_code)
        self.assertIn("z-index: 1100", css_code)
        self.assertIn(".support-split-grid", css_code)
        self.assertIn(".donut-svg", css_code)
        self.assertIn(".trajectory-svg-container", css_code)
        self.assertIn(".retention-gauge-wrapper", css_code)
        self.assertIn(".pill-highlight-amber", css_code)
        self.assertIn(".retention-pie-svg", css_code)

    def test_admin_infographics_and_analytics_integration(self):
        # 1. Verify /admin template contains modern Infographics and detailed analytics markup
        s_adm, _, body_adm = self._get_raw("/admin")
        self.assertEqual(s_adm, 200)
        html = body_adm.decode("utf-8")
        self.assertIn('id="zone-donut-container"', html)
        self.assertIn('id="trajectory-svg-container"', html)
        self.assertIn('id="support-split-grid"', html)
        self.assertIn('id="retention-gauge-container"', html)
        self.assertIn('id="card-coverage-index"', html)
        self.assertIn('id="card-retention-rate"', html)
        self.assertIn('id="card-support-density"', html)
        self.assertIn('id="card-zone-leader"', html)
        self.assertIn('id="state-breakdown-tbody"', html)

        # 2. Verify Pie Chart generator and existing color scale in Renewal infographic
        self.assertIn("generateRenewalPieSvg", html)
        self.assertIn("stacked-gauge-bar", html)
        self.assertIn("retention-legend-row", html)

        # 3. Verify security cleanup: Auto-Fill Credentials removed from both Admin and Employee portals
        self.assertNotIn("Auto-Fill Admin Credentials", html)
        self.assertNotIn("autoFillAdminCredentials", html)

        # 4. Verify Dr. Anirban Mukherjee is NOT in the top hero banner/navbar
        s_emp, _, body_emp = self._get_raw("/employee")
        s_idx, _, body_idx = self._get_raw("/")
        emp_html = body_emp.decode("utf-8")
        idx_html = body_idx.decode("utf-8")

        self.assertNotIn("Auto-Fill Password", emp_html)
        self.assertNotIn("autoFillDemoPassword", emp_html)
        self.assertNotIn("Demo password:", emp_html)

        self.assertNotIn('<span class="developer-badge"', html)
        self.assertNotIn('<span class="developer-badge"', emp_html)
        self.assertNotIn('<span class="developer-badge"', idx_html)

        # 5. Verify inaccurate geographic choropleth map has been cleanly removed
        self.assertNotIn('id="india-map-container"', html)
        self.assertNotIn('/static/js/india_map.js', html)

        # 6. Verify Employee Credential Database has explicit Block and Unblock options
        self.assertIn("handleBlockEmployee", html)
        self.assertIn("handleUnblockEmployee", html)
        self.assertIn("Active / Unblocked", html)
        self.assertIn("🔓 Unblock", html)

    # 10. Test Renewal Attention Data and Full Club Details API Workflow
    def test_renewal_attention_and_club_details_api_workflow(self):
        # 1. Fetch renewal attention list
        status_attn, data_attn = self._get_json("/api/admin/renewal-attention")
        self.assertEqual(status_attn, 200)
        self.assertTrue(data_attn.get("success"))
        self.assertIn("clubs", data_attn)
        clubs = data_attn["clubs"]
        self.assertGreaterEqual(len(clubs), 1)

        # 2. Inspect first club from the list (e.g. NDLI-AS-105)
        club_to_inspect = clubs[0]
        cid = club_to_inspect["club_id"]
        self.assertTrue(cid)

        # 3. Call club details endpoint with this club_id
        status_det, data_det = self._get_json(f"/api/clubs/details?club_id={urllib.parse.quote(cid)}")
        self.assertEqual(status_det, 200)
        self.assertTrue(data_det.get("success"))
        self.assertTrue(data_det.get("found"))
        club = data_det["club"]
        self.assertEqual(club["club_id"].upper(), cid.upper())
        self.assertTrue(club.get("institution_name"))
        self.assertTrue(club.get("state"))
        self.assertTrue(club.get("zone"))
        self.assertTrue(club.get("next_renewal_due_date"))

        # 4. Test case-insensitive lookup
        status_lower, data_lower = self._get_json(f"/api/clubs/details?club_id={urllib.parse.quote(cid.lower())}")
        self.assertEqual(status_lower, 200)
        self.assertEqual(data_lower["club"]["club_id"].upper(), cid.upper())

        # 5. Test with id parameter alias
        status_alias, data_alias = self._get_json(f"/api/clubs/details?id={urllib.parse.quote(cid)}")
        self.assertEqual(status_alias, 200)
        self.assertTrue(data_alias.get("found"))

    def test_environment_and_js_syntax(self):
        import shutil
        import subprocess
        import tempfile
        node_bin = shutil.which("node")
        if node_bin:
            # Test app.js syntax with node
            res = subprocess.run([node_bin, "--check", "static/js/app.js"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"app.js syntax error: {res.stderr}")
            
            # Extract script from admin.html and test syntax
            with open("templates/admin.html", "r", encoding="utf-8") as f:
                content = f.read()
            import re
            scripts = re.findall(r"<script(?:\s+[^>]*?)?>([\s\S]*?)</script>", content)
            for idx, sc in enumerate(scripts):
                if not sc.strip(): continue
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
                    tmp.write(sc)
                    tmp_path = tmp.name
                try:
                    res = subprocess.run([node_bin, "--check", tmp_path], capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, f"Script {idx} in admin.html has JS syntax error: {res.stderr}")
                finally:
                    import os
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

    # 11. Test Regional Employee Node Clubs (NDLI-EMP01-002, NDLI-EMP04-001) in Renewal Attention & Details API
    def test_regional_employee_node_club_details_and_overdue_workflow(self):
        # 1. Create Overdue club on EMP01
        payload_emp01 = {
            "club_id": "NDLI-EMP01-002",
            "reg_no": "REG-2025-EMP01-002",
            "institution_name": "Delhi Advanced Technical Institute",
            "state": "Delhi",
            "zone": "North",
            "patron_email": "director@dati.ac.in",
            "president_email": "pres.dati@dati.ac.in",
            "secretary_email": "sec.dati@dati.ac.in",
            "date_of_approval": "2024-08-15T10:00:00Z",
            "renewal_date": "2025-08-15"  # Past date: Overdue
        }
        SyncEngine.approve_new_club("EMP01", payload_emp01)

        # 2. Create Expiring Soon club on EMP04
        from datetime import datetime, timezone, timedelta
        exp_soon_date = (datetime.now(timezone.utc).date() + timedelta(days=25)).isoformat()
        doa_emp04 = (datetime.now(timezone.utc).date() + timedelta(days=25) - timedelta(days=365)).isoformat()
        payload_emp04 = {
            "club_id": "NDLI-EMP04-001",
            "reg_no": "REG-2026-EMP04-001",
            "institution_name": "Kolkata Engineering & Research Institute",
            "state": "West Bengal",
            "zone": "East",
            "patron_email": "patron@keri.edu.in",
            "president_email": "president@keri.edu.in",
            "secretary_email": "secretary@keri.edu.in",
            "date_of_approval": f"{doa_emp04}T10:00:00Z",
            "renewal_date": exp_soon_date  # Within 90 days: Expiring Soon
        }
        SyncEngine.approve_new_club("EMP04", payload_emp04)

        # 3. Check /api/admin/renewal-attention includes both clubs
        status_attn, data_attn = self._get_json("/api/admin/renewal-attention")
        self.assertEqual(status_attn, 200)
        self.assertTrue(data_attn.get("success"))
        clubs = data_attn.get("clubs", [])
        cids = [c["club_id"].upper() for c in clubs]
        self.assertIn("NDLI-EMP01-002", cids)
        self.assertIn("NDLI-EMP04-001", cids)

        # Inspect Overdue club data structure
        club_overdue = next(c for c in clubs if c["club_id"].upper() == "NDLI-EMP01-002")
        self.assertEqual(club_overdue["attention_type"], "Overdue")
        self.assertGreater(club_overdue["days_overdue"], 0)
        self.assertEqual(club_overdue["badge_class"], "pill-danger")
        self.assertTrue(club_overdue.get("next_renewal_due_date"))

        # Inspect Expiring Soon club data structure
        club_expiring = next(c for c in clubs if c["club_id"].upper() == "NDLI-EMP04-001")
        self.assertEqual(club_expiring["attention_type"], "Expiring Soon")
        self.assertGreater(club_expiring["days_left"], 0)
        self.assertEqual(club_expiring["badge_class"], "pill-warning")
        self.assertTrue(club_expiring.get("next_renewal_due_date"))

        # 4. Fetch full details for NDLI-EMP01-002
        status_c1, data_c1 = self._get_json("/api/clubs/details?club_id=NDLI-EMP01-002")
        self.assertEqual(status_c1, 200)
        self.assertTrue(data_c1.get("found"))
        c1 = data_c1["club"]
        self.assertEqual(c1["club_id"], "NDLI-EMP01-002")
        self.assertEqual(c1["institution_name"], "Delhi Advanced Technical Institute")
        self.assertEqual(c1["state"], "Delhi")
        self.assertEqual(c1["zone"], "North")
        self.assertEqual(c1["patron_email"], "director@dati.ac.in")
        self.assertEqual(c1["president_email"], "pres.dati@dati.ac.in")
        self.assertEqual(c1["secretary_email"], "sec.dati@dati.ac.in")
        self.assertTrue(c1["submission_timestamp"])
        self.assertTrue(c1["next_renewal_due_date"])
        self.assertEqual(c1["attention_type"], "Overdue")

        # 5. Fetch full details for NDLI-EMP04-001
        status_c2, data_c2 = self._get_json("/api/clubs/details?club_id=NDLI-EMP04-001")
        self.assertEqual(status_c2, 200)
        self.assertTrue(data_c2.get("found"))
        c2 = data_c2["club"]
        self.assertEqual(c2["club_id"], "NDLI-EMP04-001")
        self.assertEqual(c2["institution_name"], "Kolkata Engineering & Research Institute")
        self.assertEqual(c2["state"], "West Bengal")
        self.assertEqual(c2["zone"], "East")
        self.assertEqual(c2["patron_email"], "patron@keri.edu.in")
        self.assertTrue(c2["next_renewal_due_date"])
        self.assertEqual(c2["attention_type"], "Expiring Soon")

    # 12. Test Admin JavaScript Modal Controller Execution via Headless Node Context
    def test_admin_modal_js_execution_flow(self):
        import shutil
        import subprocess
        import tempfile
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node.exe not available")

        # Create a Node.js simulation script that tests openClubDetailsModal, renderClubDetailsView,
        # backToAttentionList, and closeClubDetailsModal against admin.html and app.js logic
        test_script = r"""
        const fs = require('fs');
        const path = require('path');

        // Mock DOM
        const elements = {};
        function getEl(id) {
          if (!elements[id]) {
            const classSet = new Set();
            elements[id] = {
              id: id,
              classList: {
                add: (...cls) => cls.forEach(c => classSet.add(c)),
                remove: (...cls) => cls.forEach(c => classSet.delete(c)),
                contains: (c) => classSet.has(c),
                toString: () => Array.from(classSet).join(' ')
              },
              style: {},
              innerHTML: '',
              innerText: '',
              value: '',
              querySelectorAll: () => [],
              addEventListener: () => {}
            };
          }
          return elements[id];
        }

        global.window = global;
        global.document = {
          getElementById: (id) => getEl(id),
          querySelectorAll: (sel) => [],
          addEventListener: () => {},
          readyState: 'complete'
        };
        global.sessionStorage = {
          getItem: () => null,
          setItem: () => {},
          removeItem: () => {}
        };
        global.fetch = async (url) => {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              success: true,
              found: true,
              club: {
                club_id: 'NDLI-EMP01-002',
                institution_name: 'Delhi Advanced Technical Institute',
                state: 'Delhi',
                zone: 'North',
                status: 'Approved',
                submission_timestamp: '2025-08-15T10:00:00Z',
                renewal_date: '2025-08-15',
                patron_email: 'director@dati.ac.in',
                president_email: 'pres.dati@dati.ac.in',
                secretary_email: 'sec.dati@dati.ac.in',
                days_diff: -390,
                days_overdue: 390,
                attention_type: 'Overdue',
                badge_class: 'pill-danger',
                next_renewal_due_date: '2026-08-15'
              }
            })
          };
        };

        // Load static/js/app.js
        const appJsCode = fs.readFileSync('static/js/app.js', 'utf8');
        eval(appJsCode);

        // Extract inline script from templates/admin.html
        const adminHtml = fs.readFileSync('templates/admin.html', 'utf8');
        const scriptBlocks = adminHtml.match(/<script(?:\s+[^>]*)?>([\s\S]*?)<\/script>/gi) || [];
        const inlineBlock = scriptBlocks.find(b => !b.includes('src=') && b.includes('renderRenewalAttentionList')) || scriptBlocks[scriptBlocks.length - 1];
        const adminScript = inlineBlock.replace(/^<script(?:\s+[^>]*)?>/i, '').replace(/<\/script>$/i, '');
        eval(adminScript);

        // Populate sample attention dataset
        RENEWAL_ATTENTION_DATA = {
          total_attention_count: 2,
          overdue_count: 1,
          expiring_soon_count: 1,
          clubs: [
            {
              club_id: 'NDLI-EMP01-002',
              institution_name: 'Delhi Advanced Technical Institute',
              state: 'Delhi',
              zone: 'North',
              status: 'Approved',
              submission_timestamp: '2025-08-15T10:00:00Z',
              renewal_date: '2025-08-15',
              patron_email: 'director@dati.ac.in',
              president_email: 'pres.dati@dati.ac.in',
              secretary_email: 'sec.dati@dati.ac.in',
              days_diff: -390,
              days_overdue: 390,
              attention_type: 'Overdue',
              badge_class: 'pill-danger',
              next_renewal_due_date: '2026-08-15'
            }
          ]
        };

        (async () => {
          // 1. Render Renewal Attention list rows
          renderRenewalAttentionList();
          const tbody = document.getElementById('renewal-attention-tbody');
          if (!tbody.innerHTML.includes('NDLI-EMP01-002')) {
            throw new Error('Table body does not contain NDLI-EMP01-002');
          }
          if (!tbody.innerHTML.includes('openClubDetailsModal')) {
            throw new Error('Table body row does not contain openClubDetailsModal handler');
          }

          // 2. Open Club Details Modal
          await openClubDetailsModal('NDLI-EMP01-002');
          const detailsModal = document.getElementById('club-details-modal');
          const attnModal = document.getElementById('renewal-attention-modal');
          const detailsBody = document.getElementById('club-details-body');

          if (!detailsModal.classList.contains('active') || !detailsModal.classList.contains('open')) {
            throw new Error('club-details-modal did not receive active and open classes');
          }
          if (detailsModal.style.display !== 'flex') {
            throw new Error('club-details-modal display is not flex');
          }
          if (attnModal.style.display !== 'none') {
            throw new Error('renewal-attention-modal was not hidden when details modal opened');
          }
          if (!detailsBody.innerHTML.includes('Delhi Advanced Technical Institute')) {
            throw new Error('club-details-body missing institution name');
          }
          if (!detailsBody.innerHTML.includes('Next Renewal Due Date')) {
            throw new Error('club-details-body missing Next Renewal Due Date');
          }

          // 3. Test Navigation Back to Renewal Attention List
          backToAttentionList();
          if (detailsModal.style.display !== 'none' || detailsModal.classList.contains('active')) {
            throw new Error('club-details-modal still active after backToAttentionList');
          }
          if (attnModal.style.display !== 'flex' || !attnModal.classList.contains('active')) {
            throw new Error('renewal-attention-modal not restored after backToAttentionList');
          }

          // 4. Test Clean Close of Details Modal
          await openClubDetailsModal('NDLI-EMP01-002');
          closeClubDetailsModal();
          if (detailsModal.style.display !== 'none' || detailsModal.classList.contains('active')) {
            throw new Error('club-details-modal still active after closeClubDetailsModal');
          }

          console.log('SUCCESS_MODAL_FLOW_VERIFIED');
        })();
        """;

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(test_script)
            tmp_path = tmp.name

        try:
            res = subprocess.run([node_bin, tmp_path], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"JS execution failed: {res.stderr}\nOutput: {res.stdout}")
            self.assertIn("SUCCESS_MODAL_FLOW_VERIFIED", res.stdout)
        finally:
            import os
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_bulk_phone_call_activity_api_flow(self):
        # 1. Verify UI markup in employee.html
        status, _, body = self._get_raw("/employee")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="bulk-calls-group"', html)
        self.assertIn('id="support-count"', html)
        self.assertIn('handleSupportTypeChange', html)
        self.assertIn('Bulk Entry', html)

        # 2. Test Bulk Entry API with count = 4
        act_status, act_data = self._post_json("/api/activity/log", {
            "emp_id": "EMP01",
            "support_type": "Phone call and remote assistance",
            "notes": "Bulk phone assistance to regional schools",
            "count": 4
        })
        self.assertEqual(act_status, 200)
        self.assertTrue(act_data["success"])
        self.assertEqual(act_data["count"], 4)
        self.assertIn("4 Phone call & remote assistance entries recorded in bulk", act_data["message"])

        # 3. Test that non-phone support type strictly ignores bulk count (clamps to 1)
        non_phone_status, non_phone_data = self._post_json("/api/activity/log", {
            "emp_id": "EMP01",
            "support_type": "Closing of OS Ticket",
            "notes": "Ticket resolved",
            "count": 5
        })
        self.assertEqual(non_phone_status, 200)
        self.assertEqual(non_phone_data["count"], 1)

if __name__ == "__main__":
    unittest.main()

