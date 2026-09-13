"""
Targeted Verification Tests for Date of Approval and Renewal Approved Lifecycle
Validates the logic:
1. Date of Approval is logged upon initial club creation.
2. Initial registration validity (+1 year) is automatically calculated and logged in renewal_date.
3. last_renewal_date is initially blank.
4. "Renewal Approved" action records current submission timestamp in last_renewal_date and re-computes renewal_date (+1 year).
5. Previous renewal records are not retained; only Date of Approval, Last Renewal Date, and Upcoming Renewal Date are stored.
6. Leap year rollover and boundary cases.
7. Full API endpoints and template element integrity.
"""
import unittest
import threading
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database
from db.sync_engine import SyncEngine, calculate_next_renewal_date, parse_iso_or_date
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS, ACTIVITY_FIELDS
from config import MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV


class TestApprovalAndRenewalLifecycle(unittest.TestCase):
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

    def _get_json(self, path: str):
        status, _, body = self._get_raw(path)
        return status, json.loads(body.decode("utf-8"))

    def _post_json(self, path: str, payload: dict):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_calculate_next_renewal_date_unit(self):
        # 1. From date_of_approval
        d1 = "2026-03-15T10:00:00Z"
        res1 = calculate_next_renewal_date(date_of_approval=d1)
        self.assertEqual(res1, "2027-03-15")

        # 2. From last_renewal_date
        d2 = "2026-09-11T12:30:00+00:00"
        res2 = calculate_next_renewal_date(last_renewal_date=d2)
        self.assertEqual(res2, "2027-09-11")

        # 3. Both provided -> last_renewal_date should take precedence if more recent
        res3 = calculate_next_renewal_date(date_of_approval="2025-01-01", last_renewal_date="2026-05-20")
        self.assertEqual(res3, "2027-05-20")

        # 4. Leap year handling (Feb 29)
        res_leap = calculate_next_renewal_date(date_of_approval="2024-02-29")
        self.assertTrue(res_leap in ("2025-02-28", "2025-03-01"))

    def test_club_approval_creates_initial_validity_and_blank_last_renewal(self):
        emp_id = "EMP01"
        club_id = "NDLI-TEST-LIFECYCLE-01"
        club_payload = {
            "club_id": club_id,
            "reg_no": "REG-TEST-LIFE-001",
            "institution_name": "Lifecycle Test Institute",
            "state": "Delhi",
            "patron_email": "patron@lifecycle.edu",
            "president_email": "pres@lifecycle.edu",
            "secretary_email": "sec@lifecycle.edu"
        }

        created = SyncEngine.approve_new_club(emp_id=emp_id, club_data=club_payload)
        self.assertIsNotNone(created)
        # 1. Date of Approval must be logged
        self.assertTrue(created.get("date_of_approval"))
        # 2. Date of Approval denotes date on which club was created
        doa_date = parse_iso_or_date(created["date_of_approval"])
        today_date = datetime.now(timezone.utc).date()
        self.assertEqual(doa_date, today_date)

        # 3. Validity for 1 year from inception automatically logged
        expected_ren = calculate_next_renewal_date(date_of_approval=created["date_of_approval"])
        self.assertEqual(created.get("renewal_date"), expected_ren)

        # 4. Last renewal date must be empty upon creation
        self.assertEqual(created.get("last_renewal_date", ""), "")

        # Verify in Master CSV directly
        rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        match = next((r for r in rows if r.get("club_id") == club_id), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["date_of_approval"], created["date_of_approval"])
        self.assertEqual(match["renewal_date"], expected_ren)
        self.assertEqual(match["last_renewal_date"], "")

    def test_renewal_approved_action_lifecycle(self):
        emp_id = "EMP02"
        club_id = "NDLI-TEST-LIFECYCLE-02"
        club_payload = {
            "club_id": club_id,
            "reg_no": "REG-TEST-LIFE-002",
            "institution_name": "Renewal Test Institute",
            "state": "Madhya Pradesh",
            "patron_email": "patron@renewtest.edu",
            "president_email": "pres@renewtest.edu",
            "secretary_email": "sec@renewtest.edu"
        }

        created = SyncEngine.approve_new_club(emp_id=emp_id, club_data=club_payload)
        original_doa = created["date_of_approval"]

        # Simulate renewal approval via API without passing any manual dates ("Renewal Approved")
        status, data = self._post_json("/api/clubs/renew", {
            "emp_id": emp_id,
            "club_id": club_id
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        club = data.get("club")

        # 1. Submission timestamp instantly logged under Last Renewal Date
        self.assertTrue(club.get("last_renewal_date"))
        lrd_date = parse_iso_or_date(club["last_renewal_date"])
        today_date = datetime.now(timezone.utc).date()
        self.assertEqual(lrd_date, today_date)

        # 2. Upcoming renewal due date automatically calculated as 1 year from submission date
        expected_ren = calculate_next_renewal_date(last_renewal_date=club["last_renewal_date"])
        self.assertEqual(club.get("renewal_date"), expected_ren)

        # 3. Date of approval remains immutable
        self.assertEqual(club.get("date_of_approval"), original_doa)

        # 4. Status reflects renewed state
        self.assertEqual(club.get("status"), "Active (Renewed)")

        # 5. Dual-write verification in master CSV
        rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        match = next((r for r in rows if r.get("club_id") == club_id), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["last_renewal_date"], club["last_renewal_date"])
        self.assertEqual(match["renewal_date"], expected_ren)
        self.assertEqual(match["date_of_approval"], original_doa)

        # 6. Verify activity log entry exists for renewal
        acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        ren_act = next((a for a in acts if a.get("club_id") == club_id and a.get("support_type") == "Registration Renewal"), None)
        self.assertIsNotNone(ren_act)
        self.assertEqual(ren_act["priority_flag"], "1")

    def test_subsequent_renewal_overwrites_last_renewal_date(self):
        """Rule 10: Only Date of Approval, Last Renewal Date, and upcoming renewal date stored."""
        emp_id = "EMP03"
        club_id = "NDLI-TEST-LIFECYCLE-03"
        club_payload = {
            "club_id": club_id,
            "reg_no": "REG-TEST-LIFE-003",
            "institution_name": "Multi Renewal Institute",
            "state": "Gujarat",
            "patron_email": "patron@multiren.edu",
            "president_email": "pres@multiren.edu",
            "secretary_email": "sec@multiren.edu"
        }

        created = SyncEngine.approve_new_club(emp_id=emp_id, club_data=club_payload)
        doa = created["date_of_approval"]

        # First renewal
        ren1 = SyncEngine.renew_club_registration(
            emp_id=emp_id,
            club_id=club_id,
            last_renewal_date="2027-01-10T10:00:00Z"
        )
        self.assertEqual(ren1["last_renewal_date"], "2027-01-10T10:00:00Z")
        self.assertEqual(ren1["renewal_date"], "2028-01-10")
        self.assertEqual(ren1["date_of_approval"], doa)

        # Second renewal a year later
        ren2 = SyncEngine.renew_club_registration(
            emp_id=emp_id,
            club_id=club_id,
            last_renewal_date="2028-01-15T15:30:00Z"
        )
        self.assertEqual(ren2["last_renewal_date"], "2028-01-15T15:30:00Z")
        self.assertEqual(ren2["renewal_date"], "2029-01-15")
        self.assertEqual(ren2["date_of_approval"], doa)

        # In DB only Date of Approval, Last Renewal Date, and Upcoming Renewal Date exist
        rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        match = next((r for r in rows if r.get("club_id") == club_id), None)
        self.assertEqual(match["date_of_approval"], doa)
        self.assertEqual(match["last_renewal_date"], "2028-01-15T15:30:00Z")
        self.assertEqual(match["renewal_date"], "2029-01-15")

    def test_api_club_details_returns_all_lifecycle_fields(self):
        # Using seeded benchmark club NDLI-EMP01-002
        status, data = self._get_json("/api/clubs/details?club_id=NDLI-EMP01-002")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("found"))
        club = data.get("club")
        self.assertIn("date_of_approval", club)
        self.assertIn("last_renewal_date", club)
        self.assertIn("renewal_date", club)
        self.assertIn("next_renewal_due_date", club)
        # Verify chronological consistency: Upcoming renewal date (2025-08-15) is 1 year after date_of_approval (2024-08-15)
        parsed_doa = parse_iso_or_date(club["date_of_approval"])
        parsed_ren = parse_iso_or_date(club["renewal_date"])
        self.assertEqual(parsed_doa.isoformat(), "2024-08-15")
        self.assertEqual(parsed_ren.isoformat(), "2025-08-15")
        self.assertLess(parsed_doa, parsed_ren)

    def test_renewal_date_cannot_precede_date_of_approval_or_last_renewal(self):
        """Ensures calculate_next_renewal_date enforces that upcoming renewal date can NEVER precede DOA or LRD."""
        # 1. Upcoming renewal date before date_of_approval: auto-recalculated to DOA + 1 year
        res1 = calculate_next_renewal_date(date_of_approval="2026-09-11", renewal_date="2025-08-15")
        self.assertEqual(res1, "2027-09-11")

        # 2. Upcoming renewal date validly 1 year after date_of_approval (e.g. overdue benchmark club)
        res2 = calculate_next_renewal_date(date_of_approval="2024-08-15", renewal_date="2025-08-15")
        self.assertEqual(res2, "2025-08-15")

        # 3. Upcoming renewal date before last_renewal_date: auto-recalculated to LRD + 1 year
        res3 = calculate_next_renewal_date(last_renewal_date="2026-01-10", renewal_date="2025-08-15")
        self.assertEqual(res3, "2027-01-10")

        # 4. approve_new_club with past renewal date and omitted date_of_approval derives 1 year prior
        emp_id = "EMP01"
        club_auto = SyncEngine.approve_new_club(emp_id, {
            "club_id": "NDLI-TEST-AUTO-DOA-01",
            "renewal_date": "2025-08-15"
        })
        doa_parsed = parse_iso_or_date(club_auto["date_of_approval"])
        self.assertEqual(doa_parsed.isoformat(), "2024-08-15")
        self.assertEqual(club_auto["renewal_date"], "2025-08-15")

    def test_admin_renewal_attention_api(self):
        status, data = self._get_json("/api/admin/renewal-attention")
        self.assertEqual(status, 200)
        self.assertIn("clubs", data)
        for c in data["clubs"]:
            self.assertIn("date_of_approval", c)
            self.assertIn("last_renewal_date", c)
            self.assertIn("effective_renewal_date", c)

    def test_template_markup_elements(self):
        # 1. Employee template
        status_emp, _, body_emp = self._get_raw("/employee")
        self.assertEqual(status_emp, 200)
        html_emp = body_emp.decode("utf-8")
        self.assertIn("Renewal Approved", html_emp)
        self.assertIn("Date of Approval", html_emp)
        self.assertIn("Last Renewal Date", html_emp)
        self.assertIn("Upcoming Renewal Date", html_emp)
        self.assertIn("renew-check-conditions", html_emp)
        self.assertIn("btn-renewal-approved", html_emp)
        self.assertIn("c-renewal-display", html_emp)

        # 2. Admin template
        status_adm, _, body_adm = self._get_raw("/admin")
        self.assertEqual(status_adm, 200)
        html_adm = body_adm.decode("utf-8")
        self.assertIn("Date of Approval", html_adm)
        self.assertIn("Last Renewal Date", html_adm)
        self.assertIn("Upcoming Renewal Due Date", html_adm)
        self.assertIn('colspan="10"', html_adm)
        self.assertNotIn('colspan="8"', html_adm)

    def test_deterministic_leap_year_rollover(self):
        """Ensures leap year Feb 29 strictly rolls over to Feb 28 of following year."""
        res_2024 = calculate_next_renewal_date(date_of_approval="2024-02-29")
        self.assertEqual(res_2024, "2025-02-28")

        res_2020 = calculate_next_renewal_date(last_renewal_date="2020-02-29")
        self.assertEqual(res_2020, "2021-02-28")

    def test_date_of_approval_immutability_on_club_update(self):
        """Ensures date_of_approval cannot be wiped out or altered during general club updates."""
        emp_id = "EMP01"
        club_id = "NDLI-TEST-IMMUTABLE-01"
        created = SyncEngine.approve_new_club(emp_id=emp_id, club_data={
            "club_id": club_id,
            "reg_no": "REG-IMMUTABLE-01",
            "institution_name": "Immutable Test College",
            "state": "Delhi",
            "patron_email": "patron@immut.edu",
            "president_email": "pres@immut.edu",
            "secretary_email": "sec@immut.edu"
        })
        original_doa = created["date_of_approval"]
        self.assertTrue(original_doa)

        # Attempt to update club with empty date_of_approval
        status, data = self._post_json("/api/clubs/update", {
            "emp_id": emp_id,
            "club_id": club_id,
            "date_of_approval": "",
            "institution_name": "Immutable Test College (Renamed)"
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["club"]["date_of_approval"], original_doa)
        self.assertEqual(data["club"]["institution_name"], "Immutable Test College (Renamed)")

        # Verify in database CSV directly
        rows = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        club_in_db = next(r for r in rows if r["club_id"] == club_id)
        self.assertEqual(club_in_db["date_of_approval"], original_doa)

    def test_clubs_search_auto_computes_renewal_date(self):
        """Ensures /api/clubs/search always returns non-empty computed renewal_date."""
        emp_id = "EMP04"
        club_id = "NDLI-TEST-SEARCH-REN-01"
        SyncEngine.approve_new_club(emp_id=emp_id, club_data={
            "club_id": club_id,
            "reg_no": "REG-SEARCH-REN-01",
            "institution_name": "Search Renewal Auto College",
            "state": "West Bengal",
            "patron_email": "patron@searchren.edu",
            "president_email": "pres@searchren.edu",
            "secretary_email": "sec@searchren.edu"
        })

        status, data = self._get_json("/api/clubs/search?q=Search+Renewal")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(data["count"], 1)
        for r in data["results"]:
            self.assertTrue(r.get("renewal_date"))
            self.assertTrue(r.get("date_of_approval"))

    def test_metrics_breakdown_with_custom_date_formats(self):
        """Ensures /api/admin/metrics parses date formats safely without slicing corrupt strings."""
        status, data = self._get_json("/api/admin/metrics")
        self.assertEqual(status, 200)
        year_wise = data.get("year_wise_clubs", {})
        for yr in year_wise.keys():
            self.assertTrue(len(yr) == 4 and yr.isdigit(), f"Year key should be 4 digits, got '{yr}'")
        month_wise = data.get("month_wise_clubs", {})
        for mo in month_wise.keys():
            self.assertTrue(len(mo) == 7 and mo[:4].isdigit() and mo[4] == "-", f"Month key should be YYYY-MM, got '{mo}'")


if __name__ == "__main__":
    unittest.main()
