"""
tests/test_regno_ui.py

Locks the Registration No visibility requirement (user request, 2026-10-05):
the employee portal's universal club search list must SHOW the registration
number, and the club details edit form must carry an editable reg-no field
(submitted to /api/clubs/update, which already validates charset + uniqueness).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
from pathlib import Path

from admin_view import employee_js_view

BASE_DIR = Path(__file__).resolve().parent.parent
EMPLOYEE_HTML = BASE_DIR / "templates" / "employee.html"


class TestRegNoUi(unittest.TestCase):

    def setUp(self):
        self.html = employee_js_view()

    def _has(self, marker):
        return marker in self.html

    def test_search_list_shows_registration_no(self):
        self.assertTrue(self._has("<th>Registration No</th>"),
                        "universal search table header must show Registration No")
        self.assertTrue(self._has("escapeHtml(c.reg_no || 'Pending')"),
                        "universal search rows must render the reg number")
        self.assertTrue(self._has('colspan="10"'),
                        "clubs table state rows must span the new column count")
        self.assertFalse(self._has('colspan="9"'),
                         "no clubs-table state row may still span the old column count")

    def test_edit_form_has_reg_no_field(self):
        self.assertTrue(self._has('id="edit-reg-no"'),
                        "club edit modal must carry the reg-no field")
        self.assertTrue(self._has('const regNoEl = document.getElementById("edit-reg-no");'),
                        "the edit modal must look up the reg-no field")
        self.assertTrue(self._has('regNoEl.value = club.reg_no || "";'),
                        "the edit modal must populate the reg-no field from the club")

    def test_update_payload_sends_reg_no(self):
        self.assertTrue(
            self._has('reg_no: document.getElementById("edit-reg-no").value.trim()'),
            "handleClubUpdate must submit reg_no to /api/clubs/update")


if __name__ == "__main__":
    unittest.main()
