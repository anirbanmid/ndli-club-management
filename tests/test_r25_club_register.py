"""
R25 — Admin Club Register (direct club list) — LOCK TESTS.

User requisition (2026-10-09): the admin portal had NO direct club list — the
details modal + "Correct Historical Dates" block were reachable only via the
Renewal Attention list. The Club Register opens from the Total NDLI Clubs KPI
card, lists all clubs (searchable) and each row opens full club details.

Locked here:
  * admin can list all master clubs via /api/clubs/search?q= (normalized dates)
  * provenance visible in the register rows (record_origin imported vs created)
  * server-side search filtering works
  * markup locks: KPI card wiring, register modal, filter, row action,
    context-aware back navigation (register vs attention)
  * anti-regression: renewal-attention flow + r24 correction block pins intact
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
import threading
import json
import urllib.request
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database


class TestR25ClubRegister(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    # ---------- harness ----------
    def _token(self, role="admin", emp_id="EMP01"):
        from auth_util import admin_token, employee_token
        if role == "admin":
            return admin_token(self.base_url, self.__class__.__name__)
        return employee_token(self.base_url, self.__class__.__name__, emp_id=emp_id)

    def _get_raw(self, path, headers=None):
        req = urllib.request.Request(f"{self.base_url}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def _get_json(self, path, role="admin"):
        token = self._token(role)
        status, body = self._get_raw(path, {"Authorization": f"Bearer {token}"})
        return status, json.loads(body)

    def _post(self, path, payload, role="admin", emp_id="EMP01"):
        token = self._token(role, emp_id)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    @staticmethod
    def _club_payload(cid, **kw):
        b = {
            "emp_id": "EMP01",
            "club_id": cid,
            "reg_no": "REG-" + cid,
            "institution_name": "Register Test College " + cid,
            "state": "Gujarat",
            "patron_email": "patron@r25.edu",
            "president_email": "pres@r25.edu",
            "secretary_email": "sec@r25.edu",
        }
        b.update(kw)
        return b

    # ---------- API behaviour ----------
    def test_admin_lists_all_clubs_with_normalized_dates(self):
        # one imported + one created club must both show in the register feed
        s1, d1 = self._post("/api/clubs/create", self._club_payload(
            "252501", record_mode="import",
            date_of_approval="2024-06-15", last_renewal_date="2025-07-20"))
        self.assertEqual(s1, 200, d1)
        s2, d2 = self._post("/api/clubs/create", self._club_payload("252502", record_mode="new"))
        self.assertEqual(s2, 200, d2)

        status, data = self._get_json("/api/clubs/search?q=")
        self.assertEqual(status, 200)
        rows = data.get("results") or data.get("clubs") or []
        self.assertTrue(rows, "register feed must not be empty")
        by_id = {str(r.get("club_id", "")).strip(): r for r in rows}
        imp = by_id.get("252501")
        new = by_id.get("252502")
        self.assertTrue(imp, "imported club missing from register feed")
        self.assertTrue(new, "created club missing from register feed")
        # normalized historical dates preserved (the register shows real history)
        self.assertTrue(imp["date_of_approval"].startswith("2024-06-15"), imp["date_of_approval"])
        self.assertTrue(imp["last_renewal_date"].startswith("2025-07-20"), imp["last_renewal_date"])
        self.assertEqual(imp["renewal_date"], "2026-07-20")
        self.assertEqual(imp.get("record_origin"), "imported")
        self.assertEqual(new.get("record_origin"), "created")
        # rows carry the columns the register table renders
        for key in ("reg_no", "institution_name", "state", "zone", "status"):
            self.assertIn(key, imp)

    def test_server_side_search_filtering(self):
        status, data = self._get_json("/api/clubs/search?q=Register%20Test%20College%20252501")
        self.assertEqual(status, 200)
        rows = data.get("results") or data.get("clubs") or []
        self.assertTrue(any(r.get("club_id") == "252501" for r in rows), rows[:3])
        status, data = self._get_json("/api/clubs/search?q=zzz-no-such-club-zzz")
        self.assertEqual(status, 200)
        rows = data.get("results") or data.get("clubs") or []
        self.assertEqual(len(rows), 0)

    # ---------- UI markup locks ----------
    def test_register_markup_locks(self):
        status, html = self._get_raw("/admin")
        self.assertEqual(status, 200)
        for marker in (
            'id="card-club-register"', 'onclick="openClubRegisterModal()"',
            'id="club-register-modal"', 'id="club-register-body"',
            'id="club-register-filter"', "filterClubRegister", "renderClubRegisterList",
            "openClubDetailsFromRegister", "backToClubRegister", "goBackFromClubDetails",
            "clubDetailsBackLabel", "Back to Club Register",
            "window.openClubRegisterModal = openClubRegisterModal",
            "window.closeClubRegisterModal = closeClubRegisterModal",
        ):
            self.assertIn(marker, html)

    def test_kpi_card_accessibility(self):
        status, html = self._get_raw("/admin")
        self.assertEqual(status, 200)
        self.assertIn('id="card-club-register" role="button" tabindex="0"', html)
        self.assertIn('aria-label="Open Club Register"', html)
        self.assertIn("event.key==='Enter'", html)

    def test_details_back_navigation_is_context_aware(self):
        status, html = self._get_raw("/admin")
        self.assertEqual(status, 200)
        # the choke-point back handler routes to the register when in register context
        self.assertIn("backToAttentionList()", html)
        self.assertIn('CLUB_DETAILS_RETURN = (returnTo === "register")', html)
        # the details modal can be opened from the register with returnTo="register"
        self.assertIn('openClubDetailsModal(clubId, "register")', html)
        # Esc ladder knows the register modal (closes topmost first)
        self.assertIn("closeClubRegisterModal();", html)

    def test_anti_regression_pins(self):
        status, html = self._get_raw("/admin")
        self.assertEqual(status, 200)
        # renewal-attention flow intact
        self.assertIn('id="card-renewal-attention"', html)
        self.assertIn("openRenewalAttentionModal", html)
        self.assertIn("backToAttentionList", html)
        # r24 correction block + pinned strings intact
        self.assertIn("Correct Historical Dates", html)
        self.assertIn("submitClubDateCorrection", html)
        self.assertIn('colspan="10"', html)
        self.assertNotIn('colspan="8"', html)
        self.assertIn("Upcoming Renewal Due Date", html)
        self.assertIn("Date of Approval", html)
        self.assertIn("Last Renewal Date", html)


if __name__ == "__main__":
    unittest.main()
