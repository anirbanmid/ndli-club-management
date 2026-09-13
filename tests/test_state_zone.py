"""
Unit tests for State and Zone Mapping logic.
Verifies all 36 States and Union Territories match the exact NDLI specification.
"""
import unittest
from state_zone_mapper import (
    get_zone_for_state,
    get_all_states,
    get_all_zones,
    ZONE_STATE_MAP
)

class TestStateZoneMapping(unittest.TestCase):

    def test_all_zones_present(self):
        zones = get_all_zones()
        expected_zones = ["North", "Central", "West", "East", "North East", "South"]
        self.assertEqual(sorted(zones), sorted(expected_zones))

    def test_north_zone_states(self):
        expected = [
            "Jammu & Kashmir", "Ladakh", "Uttarakhand", "Himachal Pradesh",
            "Chandigarh", "Punjab", "Haryana", "Delhi", "Uttar Pradesh"
        ]
        for state in expected:
            zone = get_zone_for_state(state)
            self.assertEqual(zone, "North", f"Failed for state: {state}")

    def test_central_zone_states(self):
        expected = ["Madhya Pradesh", "Chhattisgarh"]
        for state in expected:
            zone = get_zone_for_state(state)
            self.assertEqual(zone, "Central", f"Failed for state: {state}")

    def test_west_zone_states(self):
        expected = [
            "Rajasthan", "Gujarat", "Maharashtra", "Goa",
            "Daman and Diu", "Dadar & Nagar Haveli"
        ]
        for state in expected:
            zone = get_zone_for_state(state)
            self.assertEqual(zone, "West", f"Failed for state: {state}")

    def test_east_zone_states(self):
        expected = ["Bihar", "Jharkhand", "West Bengal", "Odisha"]
        for state in expected:
            zone = get_zone_for_state(state)
            self.assertEqual(zone, "East", f"Failed for state: {state}")

    def test_northeast_zone_states(self):
        expected = [
            "Sikkim", "Assam", "Arunachal Pradesh", "Meghalaya",
            "Manipur", "Tripura", "Nagaland", "Mizoram"
        ]
        for state in expected:
            zone = get_zone_for_state(state)
            self.assertEqual(zone, "North East", f"Failed for state: {state}")

    def test_south_zone_states(self):
        expected = [
            "Andhra Pradesh", "Telangana", "Karnataka", "Tamil Nadu",
            "Puducherry", "Kerala", "Andaman & Nicobar Island", "Lakshadweep"
        ]
        for state in expected:
            zone = get_zone_for_state(state)
            self.assertEqual(zone, "South", f"Failed for state: {state}")

    def test_case_insensitivity_and_whitespace(self):
        self.assertEqual(get_zone_for_state("  delhi  "), "North")
        self.assertEqual(get_zone_for_state("WEST BENGAL"), "East")
        self.assertEqual(get_zone_for_state("maharashtra"), "West")
        self.assertEqual(get_zone_for_state("kerala"), "South")
        self.assertEqual(get_zone_for_state("assam"), "North East")

    def test_aliases(self):
        self.assertEqual(get_zone_for_state("j&k"), "North")
        self.assertEqual(get_zone_for_state("Jammu and Kashmir"), "North")
        self.assertEqual(get_zone_for_state("Daman & Diu"), "West")
        self.assertEqual(get_zone_for_state("Dadra and Nagar Haveli"), "West")
        self.assertEqual(get_zone_for_state("Pondicherry"), "South")

    def test_invalid_state(self):
        self.assertIsNone(get_zone_for_state("Atlantis"))
        self.assertIsNone(get_zone_for_state(""))
        self.assertIsNone(get_zone_for_state(None))

if __name__ == "__main__":
    unittest.main()
