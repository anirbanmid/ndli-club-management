"""
Round-2 improvements (2026-09-25) — regression tests.

1. Renewal policy: +1 year from the PREVIOUS due date (early renewal keeps the
   anniversary); overdue renewals roll forward until the due date is in the future.
2. Double-click Renew guard: a second renewal within the dedupe window is not
   logged again and earns no second quota credit.
3. Duplicate-entry checkpoint (client requirement): re-entry of an already
   approved club is blocked at /api/clubs/create AND /api/clubs/update when the
   Registration Number (or Club ID) already exists — with a warning naming the
   existing club. Verification keys: Club ID + Registration Number.
4. Identifier charset whitelists (club_id / reg_no) — kills the stored-XSS class.
5. Emergency restore takes a pre-restore checkpoint (undo point) first.
"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer

from app import NDLIRequestHandler
from auth import AuthService
from config import (
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_QUOTAS_CSV,
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
)
from db.backup_engine import BackupEngine
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS, ACTIVITY_FIELDS, QUOTA_FIELDS
from db.sync_engine import SyncEngine, calculate_next_renewal_due, parse_iso_or_date
from init_db import initialize_database

E3 = ("emp.west@ndli.edu.in", "Seed#EMP03-Rotated2026")   # EMP03
E4 = ("emp.east@ndli.edu.in", "Seed#EMP04-Rotated2026")   # EMP04


def _club(cid, emp, reg_no=None, state="Gujarat", **kw):
    b = dict(club_id=cid, reg_no=reg_no or ("REG-" + cid),
             institution_name="Inst " + cid, state=state,
             patron_email="p@x.edu", president_email="pr@x.edu",
             secretary_email="s@x.edu", emp_id=emp)
    b.update(kw)
    return b


def _quota(emp_id):
    for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS):
        if q.get("emp_id") == emp_id:
            return int(q.get("support_logs_count", "0") or "0"), int(q.get("clubs_approved_count", "0") or "0")
    return 0, 0


def _renewal_activity_count(club_id):
    acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
    return sum(1 for a in acts
               if a.get("club_id") == club_id and a.get("support_type") == "Registration Renewal")


class Round2TestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.created = []

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for cid in cls.created:
            try:
                SyncEngine.delete_club(cid)
            except Exception:
                pass

    def _call(self, path, body, hdr=None):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {hdr}"} if hdr else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def _login(self, email, pw):
        s, j = self._call("/api/auth/login", {"email": email, "password": pw}, hdr=None)
        self.assertEqual(s, 200)
        return j["session"]["token"]


class TestRenewalPolicy(Round2TestBase):
    """1. +1 year from the previous DUE date; overdue rolls forward."""

    def test_early_renewal_keeps_anniversary(self):
        t3 = self._login(*E3)
        cid = "940101"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03"), t3)[0], 200)
        # Model a mid-cycle club: due ~400 days from today, renewed early today
        import datetime as _dt
        today = datetime.now(timezone.utc).date()
        future_due = today + _dt.timedelta(days=400)
        SyncEngine.update_club("EMP03", cid, {"renewal_date": future_due.isoformat(),
                                             "next_renewal_date": future_due.isoformat()})
        s, j = self._call("/api/clubs/renew", {"emp_id": "EMP03", "club_id": cid}, t3)
        self.assertEqual(s, 200)
        try:
            expected = future_due.replace(year=future_due.year + 1).isoformat()
        except ValueError:
            expected = future_due.replace(year=future_due.year + 1, month=2, day=28).isoformat()
        self.assertEqual(j["club"]["renewal_date"], expected)   # +1y from the DUE date, not from today
        self.assertEqual(j["club"]["next_renewal_date"], expected)
        self.assertGreater(parse_iso_or_date(expected), future_due)

    def test_overdue_renewal_rolls_forward(self):
        t3 = self._login(*E3)
        cid = "940102"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03"), t3)[0], 200)
        # Model an overdue club realistically (due date in the past, approved &
        # renewed before that): ~1100 days since approval, ~700 since renewal,
        # ~400 days overdue.
        today = datetime.now(timezone.utc).date()
        import datetime as _dt
        past_doa = today - _dt.timedelta(days=1100)
        past_lrd = today - _dt.timedelta(days=700)
        past_due = today - _dt.timedelta(days=400)
        SyncEngine.update_club("EMP03", cid, {
            "date_of_approval": past_doa.isoformat() + "T10:00:00Z",
            "last_renewal_date": past_lrd.isoformat() + "T10:00:00Z",
            "renewal_date": past_due.isoformat(),
            "next_renewal_date": past_due.isoformat()})
        s, j = self._call("/api/clubs/renew", {"emp_id": "EMP03", "club_id": cid}, t3)
        self.assertEqual(s, 200)
        due = parse_iso_or_date(j["club"]["renewal_date"])
        self.assertGreater(due, today)          # always yields a usable validity window
        # and it is the anniversary chain: past_due + n years, never a fresh +1y from today
        expected_md = (2, 28) if (past_due.month, past_due.day) == (2, 29) else (past_due.month, past_due.day)
        self.assertEqual((due.month, due.day), expected_md)

    def test_calculate_next_renewal_due_helper(self):
        self.assertEqual(calculate_next_renewal_due(previous_renewal_date="2027-01-10"), "2028-01-10")
        # Leap-day anniversary rolls to Feb 28
        self.assertEqual(calculate_next_renewal_due(previous_renewal_date="2028-02-29"), "2029-02-28")
        # No due date: anniversary of approval
        today = datetime.now(timezone.utc).date()
        try:
            expected = today.replace(year=today.year + 1).isoformat()
        except ValueError:
            expected = today.replace(year=today.year + 1, month=2, day=28).isoformat()
        self.assertEqual(
            calculate_next_renewal_due(previous_renewal_date="",
                                      date_of_approval=today.isoformat() + "T10:00:00Z"),
            expected)


class TestDoubleRenewalGuard(Round2TestBase):
    """2. Double-click Renew counts once."""

    def test_double_click_renew_counts_once(self):
        t3 = self._login(*E3)
        cid = "940103"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03"), t3)[0], 200)

        before_support, _ = _quota("EMP03")
        acts_before = _renewal_activity_count(cid)

        s1, j1 = self._call("/api/clubs/renew", {"emp_id": "EMP03", "club_id": cid}, t3)
        self.assertEqual(s1, 200)
        self.assertNotEqual(j1.get("renewal_duplicate_skipped"), True)

        # Immediate second click (double click / retry)
        s2, j2 = self._call("/api/clubs/renew", {"emp_id": "EMP03", "club_id": cid}, t3)
        self.assertEqual(s2, 200)
        self.assertEqual(j2.get("renewal_duplicate_skipped"), True)
        self.assertIn("duplicate click ignored", j2.get("message", "").lower())

        self.assertEqual(_renewal_activity_count(cid), acts_before + 1)   # exactly ONE renewal activity
        after_support, _ = _quota("EMP03")
        self.assertEqual(after_support, before_support + 1)               # exactly ONE quota credit


class TestDuplicateEntryCheckpoint(Round2TestBase):
    """3. Re-entry of an already approved club is blocked with a warning."""

    def test_duplicate_reg_no_blocked_on_create(self):
        t3, t4 = self._login(*E3), self._login(*E4)
        cid = "940104"; self.created.append(cid)
        self.assertEqual(
            self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="R2-REG-777", state="Gujarat"), t3)[0], 200)

        # Different Club ID, SAME Registration Number -> blocked with warning naming the clash
        cid2 = "940105"; self.created.append(cid2)
        s, j = self._call("/api/clubs/create", _club(cid2, "EMP04", reg_no="R2-REG-777", state="Bihar"), t4)
        self.assertEqual(s, 409)
        msg = j.get("message", "")
        self.assertIn("DUPLICATE", msg.upper())
        self.assertIn("R2-REG-777", msg)
        self.assertIn(cid, msg)                    # warning names the existing club
        # ...and nothing was written
        row = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", cid2, CLUB_FIELDS)
        self.assertFalse(row)

        # Case/whitespace-insensitive match -> still blocked
        s2, j2 = self._call("/api/clubs/create", _club(cid2, "EMP04", reg_no=" r2-reg-777 ", state="Bihar"), t4)
        self.assertEqual(s2, 409)

        # A different Registration Number is fine
        s3, _ = self._call("/api/clubs/create", _club(cid2, "EMP04", reg_no="R2-REG-888", state="Bihar"), t4)
        self.assertEqual(s3, 200)

    def test_duplicate_club_id_still_blocked(self):
        t3, t4 = self._login(*E3), self._login(*E4)
        cid = "940106"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="R2-REG-901"), t3)[0], 200)
        s, j = self._call("/api/clubs/create", _club(cid, "EMP04", reg_no="R2-REG-902", state="Bihar"), t4)
        self.assertEqual(s, 409)
        self.assertIn("already exists", j.get("message", ""))

    def test_same_club_resubmission_still_allowed(self):
        t3 = self._login(*E3)
        cid = "940107"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="R2-REG-903"), t3)[0], 200)
        s, _ = self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="R2-REG-903"), t3)
        self.assertEqual(s, 200)   # same owner + same club: explicit resubmission kept

    def test_duplicate_reg_no_blocked_on_update(self):
        t3, t4 = self._login(*E3), self._login(*E4)
        cid = "940108"; self.created.append(cid)
        cid2 = "940109"; self.created.append(cid2)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="R2-REG-551"), t3)[0], 200)
        self.assertEqual(self._call("/api/clubs/create", _club(cid2, "EMP04", reg_no="R2-REG-552", state="Bihar"), t4)[0], 200)

        # EMP04 edits own club but reuses EMP03's reg_no -> blocked
        s, j = self._call("/api/clubs/update",
                          {"emp_id": "EMP04", "club_id": cid2, "reg_no": "R2-REG-551"}, t4)
        self.assertEqual(s, 409)
        self.assertIn("DUPLICATE", j.get("message", "").upper())
        # Editing to a fresh reg_no works
        s2, _ = self._call("/api/clubs/update",
                           {"emp_id": "EMP04", "club_id": cid2, "reg_no": "R2-REG-553"}, t4)
        self.assertEqual(s2, 200)


class TestIdentifierCharset(Round2TestBase):
    """4. club_id / reg_no charset whitelists (stored-XSS class)."""

    def test_hostile_club_id_rejected(self):
        t3 = self._login(*E3)
        s, j = self._call("/api/clubs/create", _club('X"><img src=x>', "EMP03", reg_no="R2-REG-601"), t3)
        self.assertEqual(s, 422)
        self.assertTrue(j.get("validation_errors"))
        # A hostile club_id must never reach the master DB
        row = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", 'X"><IMG SRC=X>', CLUB_FIELDS)
        self.assertFalse(row)

    def test_hostile_reg_no_rejected(self):
        t3 = self._login(*E3)
        cid = "940110"; self.created.append(cid)
        s, j = self._call("/api/clubs/create", _club(cid, "EMP03", reg_no='R"><script>'), t3)
        self.assertEqual(s, 422)
        self.assertTrue(any("Registration Number" in e for e in j.get("validation_errors", [])))

    def test_club_id_must_be_whole_number(self):
        """Client requisition (2026-09-26): Club ID is a WHOLE NUMBER — digits only."""
        t3 = self._login(*E3)
        bad_ids = ["NDLI-UP-205", "20A5", "20 51", "-2051", 'X"><img src=x>', "9" * 16, ""]
        for i, bad in enumerate(bad_ids):
            if bad == "":
                continue  # empty is covered by 'required' validation
            s, j = self._call("/api/clubs/create", _club(bad, "EMP03", reg_no=f"R2-REG-N{i}"), t3)
            self.assertEqual(s, 422, f"club_id {bad!r} must be rejected")
            self.assertTrue(any("whole number" in e for e in j.get("validation_errors", [])))
        # A plain whole number is accepted
        cid = "940112"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="R2-REG-912"), t3)[0], 200)

    def test_normal_formats_accepted(self):
        t3 = self._login(*E3)
        cid = "940111"; self.created.append(cid)
        s, _ = self._call("/api/clubs/create", _club(cid, "EMP03", reg_no="REG-2026/R2 001"), t3)
        self.assertEqual(s, 200)


class TestEmergencyRestoreCheckpoint(Round2TestBase):
    """5. Emergency restore takes an undo point first."""

    def test_restore_creates_pre_restore_checkpoint(self):
        ta = self._login(DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)
        snap = BackupEngine.create_backup(note="round2-test-snapshot")
        self.assertTrue(snap.get("success"))
        source = snap.get("backup_id", "")

        s, j = self._call("/api/admin/backup/emergency-restore",
                          {"password": DEFAULT_ADMIN_PASSWORD, "source": source}, ta)
        self.assertEqual(s, 200)
        self.assertTrue(j.get("success"))
        self.assertTrue(j.get("checkpoint_backup_id"))      # undo point exists
        self.assertIn("Pre-restore checkpoint", j.get("message", ""))


if __name__ == "__main__":
    unittest.main()
