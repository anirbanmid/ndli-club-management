"""
Unit and Integration tests for Synchronization Engine between Employee Node CSVs and Master CSVs.
"""
import unittest
from datetime import datetime, timezone, timedelta
from config import (
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_QUOTAS_CSV
)
from db.schemas import CLUB_FIELDS, ACTIVITY_FIELDS, QUOTA_FIELDS
from db.csv_engine import CSVEngine
from db.sync_engine import SyncEngine
from init_db import initialize_database

class TestSyncEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        initialize_database()

    def test_log_support_activity_sync(self):
        emp_id = "EMP01"
        activity = SyncEngine.log_support_activity(
            emp_id=emp_id,
            support_type="Closing of OS Ticket",
            notes="Ticket #9999 resolved"
        )
        self.assertIsNotNone(activity["activity_id"])
        self.assertEqual(activity["priority_flag"], "0")

        # Verify in Node CSV
        node_path = SyncEngine.get_employee_activities_path(emp_id)
        node_acts = CSVEngine.read_all(node_path, ACTIVITY_FIELDS)
        self.assertTrue(any(a["activity_id"] == activity["activity_id"] for a in node_acts))

        # Verify in Master CSV
        master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        self.assertTrue(any(a["activity_id"] == activity["activity_id"] for a in master_acts))

    def test_approve_new_club_sync_and_priority_quota(self):
        emp_id = "EMP02"
        club_id = "NDLI-TEST-999"
        club_payload = {
            "club_id": club_id,
            "reg_no": "REG-TEST-999",
            "institution_name": "Test Engineering College Raipur",
            "state": "Chhattisgarh",
            "zone": "Central",
            "patron_email": "patron@test.edu",
            "president_email": "pres@test.edu",
            "secretary_email": "sec@test.edu"
        }

        # Pre-check quotas
        pre_quotas = {q["emp_id"]: int(q.get("clubs_approved_count", "0")) for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)}
        initial_count = pre_quotas.get(emp_id, 0)

        # Approve club
        created = SyncEngine.approve_new_club(emp_id=emp_id, club_data=club_payload)
        self.assertEqual(created["club_id"], club_id)
        self.assertEqual(created["status"], "Approved")

        # 1. Verify in Employee Node clubs.csv
        node_clubs = CSVEngine.read_all(SyncEngine.get_employee_clubs_path(emp_id), CLUB_FIELDS)
        self.assertTrue(any(c["club_id"] == club_id for c in node_clubs))

        # 2. Verify in Master clubs.csv
        master_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        self.assertTrue(any(c["club_id"] == club_id for c in master_clubs))

        # 3. Verify Priority Activity Logged in Master and Node
        master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        priority_act = next((a for a in master_acts if a.get("club_id") == club_id and a.get("priority_flag") == "1"), None)
        self.assertIsNotNone(priority_act, "Priority activity log must be created for new club approval")

        # 4. Verify Quota incremented
        post_quotas = {q["emp_id"]: int(q.get("clubs_approved_count", "0")) for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)}
        self.assertEqual(post_quotas.get(emp_id, 0), initial_count + 1)

    def test_registration_renewal(self):
        emp_id = "EMP03"
        club_id = "NDLI-MH-103"
        new_renewal_date = "2028-12-31"

        updated = SyncEngine.renew_club_registration(emp_id=emp_id, club_id=club_id, renewal_date=new_renewal_date)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["renewal_date"], new_renewal_date)

        # Check Master
        master_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        m_club = next((c for c in master_clubs if c["club_id"] == club_id), None)
        self.assertIsNotNone(m_club)
        self.assertEqual(m_club["renewal_date"], new_renewal_date)

    def test_calculate_next_renewal_date_unit(self):
        from db.sync_engine import calculate_next_renewal_date, parse_iso_or_date
        # 1. From establishment date only (YYYY-MM-DD)
        r1 = calculate_next_renewal_date(establishment_date="2025-04-10")
        self.assertEqual(r1, "2026-04-10")

        # 2. From last renewal date (latest)
        r2 = calculate_next_renewal_date(establishment_date="2024-01-15", last_renewal_date="2026-03-20")
        self.assertEqual(r2, "2027-03-20")

        # 3. Whichever is latest: establishment date newer than last renewal
        r3 = calculate_next_renewal_date(establishment_date="2026-07-01", last_renewal_date="2025-07-01")
        self.assertEqual(r3, "2027-07-01")

        # 4. Leap year Feb 29 rollover to Feb 28
        r4 = calculate_next_renewal_date(establishment_date="2024-02-29")
        self.assertEqual(r4, "2025-02-28")

        r4_2020 = calculate_next_renewal_date(establishment_date="2020-02-29")
        self.assertEqual(r4_2020, "2021-02-28")

        # 5. Alternate formats: DD-MM-YYYY, DD/MM/YYYY, YYYY/MM/DD, ISO timestamp with timezone
        r5_dash = calculate_next_renewal_date(establishment_date="15-08-2025")
        self.assertEqual(r5_dash, "2026-08-15")

        r5_slash = calculate_next_renewal_date(establishment_date="15/08/2025")
        self.assertEqual(r5_slash, "2026-08-15")

        r5_iso = calculate_next_renewal_date(establishment_date="2025-08-15T10:30:00+05:30")
        self.assertEqual(r5_iso, "2026-08-15")

        # 6. Fallback when dates are None or empty
        from datetime import datetime, timezone
        now_d = datetime.now(timezone.utc).date()
        try:
            expected_fallback = now_d.replace(year=now_d.year + 1).isoformat()
        except ValueError:
            expected_fallback = (now_d + timedelta(days=365)).isoformat()
        r6 = calculate_next_renewal_date(establishment_date="", last_renewal_date=None)
        self.assertEqual(r6, expected_fallback)

    def test_automated_renewal_calculation_in_sync_engine(self):
        from db.sync_engine import calculate_next_renewal_date
        emp_id = "EMP05"
        club_id = "NDLI-AUTO-REN-01"
        club_payload = {
            "club_id": club_id,
            "reg_no": "REG-AUTO-01",
            "institution_name": "Automated Renewal University",
            "state": "Assam",
            "patron_email": "patron@auto.edu",
            "president_email": "pres@auto.edu",
            "secretary_email": "sec@auto.edu"
            # Note: renewal_date intentionally omitted to test automatic 1-year calculation!
        }

        created = SyncEngine.approve_new_club(emp_id=emp_id, club_data=club_payload)
        self.assertIsNotNone(created["renewal_date"])
        self.assertTrue(len(created["renewal_date"]) == 10)  # YYYY-MM-DD
        expected_ren = calculate_next_renewal_date(establishment_date=created["submission_timestamp"])
        self.assertEqual(created["renewal_date"], expected_ren)

        # Verify date_of_approval is logged and last_renewal_date is initially blank
        self.assertEqual(created["date_of_approval"], created["submission_timestamp"])
        self.assertEqual(created.get("last_renewal_date", ""), "")

        # Now approve renewal without passing renewal_date ("Renewal Approved" action)
        # Should instantly capture submission timestamp as last_renewal_date and calculate renewal_date as +1 year from that timestamp
        renewed = SyncEngine.renew_club_registration(emp_id=emp_id, club_id=club_id, renewal_date=None)
        self.assertIsNotNone(renewed)
        self.assertTrue(len(renewed.get("last_renewal_date", "")) > 0)
        self.assertEqual(renewed["date_of_approval"], created["date_of_approval"])
        expected_next = calculate_next_renewal_date(last_renewal_date=renewed["last_renewal_date"])
        self.assertEqual(renewed["renewal_date"], expected_next)

    def test_ai_decision_renewal_attention(self):
        from ai.decision_module import AIDecisionEngine
        data = AIDecisionEngine.get_renewal_attention_data()
        self.assertIn("total_attention_count", data)
        self.assertIn("overdue_count", data)
        self.assertIn("expiring_soon_count", data)
        self.assertIn("clubs", data)
        self.assertGreaterEqual(data["total_attention_count"], 0)

        # Check structure of clubs in attention list if any
        for c in data["clubs"]:
            self.assertIn("club_id", c)
            self.assertIn("institution_name", c)
            self.assertIn("state", c)
            self.assertIn("zone", c)
            self.assertIn("attention_type", c)
            self.assertIn("badge_label", c)
            self.assertIn("effective_renewal_date", c)

    def test_phone_call_bulk_entry_sync_and_quota(self):
        emp_id = "EMP01"
        # Get baseline quota
        quotas_before = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        base_count = 0
        for q in quotas_before:
            if q.get("emp_id") == emp_id:
                base_count = int(q.get("support_logs_count", "0") or "0")
                break

        res = SyncEngine.log_support_activity(
            emp_id=emp_id,
            support_type="Phone call and remote assistance",
            notes="Bulk assistance to northern regional clubs",
            club_id="NDLI-EMP01-001",
            count=5
        )
        self.assertEqual(res["count"], 5)
        self.assertEqual(len(res["activities_created"]), 5)

        # Verify 5 distinct rows written to node CSV
        node_path = SyncEngine.get_employee_activities_path(emp_id)
        node_acts = CSVEngine.read_all(node_path, ACTIVITY_FIELDS)
        created_ids = set(res["activities_created"])
        found_in_node = [a for a in node_acts if a["activity_id"] in created_ids]
        self.assertEqual(len(found_in_node), 5)

        # Verify 5 distinct rows in master CSV
        master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        found_in_master = [a for a in master_acts if a["activity_id"] in created_ids]
        self.assertEqual(len(found_in_master), 5)

        # Verify quota incremented by 5
        quotas_after = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        new_count = 0
        for q in quotas_after:
            if q.get("emp_id") == emp_id:
                new_count = int(q.get("support_logs_count", "0") or "0")
                break
        self.assertEqual(new_count, base_count + 5)

    def test_non_phone_call_bulk_entry_is_clamped_to_1(self):
        emp_id = "EMP02"
        quotas_before = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        base_count = 0
        for q in quotas_before:
            if q.get("emp_id") == emp_id:
                base_count = int(q.get("support_logs_count", "0") or "0")
                break

        # Attempt bulk entry on Online training (disallowed)
        res = SyncEngine.log_support_activity(
            emp_id=emp_id,
            support_type="Online training",
            notes="Webinar with colleges",
            count=10
        )
        self.assertEqual(res["count"], 1)
        self.assertEqual(len(res["activities_created"]), 1)

        # Verify quota incremented by only 1
        quotas_after = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        new_count = 0
        for q in quotas_after:
            if q.get("emp_id") == emp_id:
                new_count = int(q.get("support_logs_count", "0") or "0")
                break
        self.assertEqual(new_count, base_count + 1)

if __name__ == "__main__":
    unittest.main()
