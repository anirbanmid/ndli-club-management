"""
Regression tests for the 2026-09-25 bug-hunt (see commit message).

1. Drive pull must never overwrite/resurrect local state on persistent-disk hosts.
2. An employee cannot overwrite a club owned by another employee via /api/clubs/create.
3. /api/clubs/update ignores privileged fields for non-admin sessions (mass-assignment).
4. Login throttling stops rapid password guessing (correct login still works afterwards).
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from app import NDLIRequestHandler
from init_db import initialize_database
from auth import AuthService, _LOGIN_FAILS
from config import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
from db.storage_adapter import AppsScriptRelaySyncAdapter, LocalSyncStorageAdapter
from db.sync_engine import SyncEngine

E3 = ("emp.west@ndli.edu.in", "Seed#EMP03-Rotated2026")
E4 = ("emp.east@ndli.edu.in", "Seed#EMP04-Rotated2026")


def _club(cid, emp, state="Gujarat", **kw):
    b = dict(club_id=cid, reg_no="R-" + cid, institution_name="Inst " + cid, state=state,
             patron_email="p@x.edu", president_email="pr@x.edu", secretary_email="s@x.edu", emp_id=emp)
    b.update(kw)
    return b


class TestBugHuntRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.created = []

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        for cid in cls.created:
            try: SyncEngine.delete_club(cid)
            except Exception: pass

    def _call(self, path, body, token=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def _login(self, email, pw):
        s, j = self._call("/api/auth/login", {"email": email, "password": pw})
        self.assertEqual(s, 200); return j["session"]["token"]

    # 2
    def test_create_cannot_overwrite_other_employees_club(self):
        t3, t4 = self._login(*E3), self._login(*E4)
        cid = "BH-DUP-1"; self.created.append(cid)
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03"), t3)[0], 200)
        s, j = self._call("/api/clubs/create", _club(cid, "EMP04", state="Bihar", institution_name="HIJACK"), t4)
        self.assertEqual(s, 409)
        from db.csv_engine import CSVEngine
        from config import MASTER_CLUBS_CSV
        from db.schemas import CLUB_FIELDS
        row = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", cid, CLUB_FIELDS)
        self.assertEqual(row["approved_by_emp_id"], "EMP03"); self.assertNotEqual(row["institution_name"], "HIJACK")
        # same-owner resubmission is still allowed
        self.assertEqual(self._call("/api/clubs/create", _club(cid, "EMP03"), t3)[0], 200)

    # 3
    def test_update_ignores_privileged_fields_for_employees(self):
        t3, t4 = self._login(*E3), self._login(*E4)
        cid = "BH-MASS-1"; self.created.append(cid)
        self._call("/api/clubs/create", _club(cid, "EMP03"), t3)
        s, j = self._call("/api/clubs/update", {"emp_id": "EMP04", "club_id": cid, "institution_name": "Renamed OK",
                          "approved_by_emp_id": "EMP04", "status": "Hacked", "last_renewal_date": "2026-09-01"}, t4)
        self.assertEqual(s, 200)
        club = j["club"]
        self.assertEqual(club["institution_name"], "Renamed OK")
        self.assertEqual(club["approved_by_emp_id"], "EMP03")
        self.assertNotEqual(club["status"], "Hacked")
        self.assertEqual(club["last_renewal_date"], "")
        # Admin keeps full control
        ta = self._login(DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)
        s, j = self._call("/api/clubs/update", {"club_id": cid, "status": "Suspended"}, ta)
        self.assertEqual(s, 200); self.assertEqual(j["club"]["status"], "Suspended")

    # 4
    def test_login_throttle(self):
        _LOGIN_FAILS.clear()
        try:
            codes = [self._call("/api/auth/login", {"email": E4[0], "password": f"bad{i}"})[0] for i in range(12)]
            self.assertTrue(all(c == 401 for c in codes))
            s, j = self._call("/api/auth/login", {"email": E4[0], "password": E4[1]})
            self.assertEqual(s, 401)
            self.assertIn("Too many", j.get("message", "") + j.get("error", "") if isinstance(j.get("error"), str) else j.get("message", ""))
            # another account is unaffected
            self.assertEqual(self._call("/api/auth/login", {"email": E3[0], "password": E3[1]})[0], 200)
        finally:
            _LOGIN_FAILS.clear()
        self.assertEqual(self._call("/api/auth/login", {"email": E4[0], "password": E4[1]})[0], 200)


class TestRestartKeepsRotatedCredentials(unittest.TestCase):
    """0. A restart/Reload (initialize_database, force=False) must NOT reset rotated passwords or profile edits."""

    def test_restart_does_not_reseed_existing_accounts(self):
        initialize_database()
        from auth import AuthService
        self.assertTrue(AuthService.change_password("EMP06", "Seed#EMP06-Rotated2026", "Rotated-Once-2026!")[0])
        try:
            initialize_database()   # what every server start / PythonAnywhere Reload does
            self.assertTrue(AuthService.authenticate("EMP06", "Rotated-Once-2026!")[0])
            self.assertFalse(AuthService.authenticate("EMP06", "Seed#EMP06-Rotated2026")[0])
        finally:
            AuthService.change_password("EMP06", "Rotated-Once-2026!", "Seed#EMP06-Rotated2026")
            _LOGIN_FAILS.clear()


class TestDrivePullNeverRegressesLocal(unittest.TestCase):
    """1. Stale Drive snapshot must not resurrect deleted rows / revert edits on persistent hosts."""

    def _run_pull(self, marker_exists, persistent=True):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "master").mkdir()
            local = root / "master" / "master_clubs.csv"
            local.write_text("club_id,institution_name\nA,Alpha\n", encoding="utf-8")
            if marker_exists:
                (root / ".drive_pull_done").write_text("x")
            stale = "club_id,institution_name\nA,Alpha\nDELETED,Ghost\n"
            adapter = AppsScriptRelaySyncAdapter("http://relay.test/exec", LocalSyncStorageAdapter(root))
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps({"ok": True, "data": {"success": True,
                                    "files": {"master/master_clubs.csv": stale, "master/new_file.csv": "a,b\n1,2\n"}}}).encode()
            resp.__enter__.return_value = resp
            env = {"NDLI_DATA_DIR": td} if persistent else {}
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch("urllib.request.urlopen", return_value=resp):
                if not persistent:
                    os.environ.pop("NDLI_DATA_DIR", None); os.environ.pop("PYTHONANYWHERE_DOMAIN", None)
                adapter.pull_all_from_drive(force=True)
            return local.read_text(encoding="utf-8"), (root / "master" / "new_file.csv").exists(), (root / ".drive_pull_done").exists()

    def test_after_first_pull_local_is_authoritative(self):
        text, new_file, _ = self._run_pull(marker_exists=True)
        self.assertNotIn("DELETED", text)          # deleted row is NOT resurrected
        self.assertTrue(new_file)                  # missing files are still recovered

    def test_first_boot_still_merges_and_sets_marker(self):
        text, _, marker = self._run_pull(marker_exists=False)
        self.assertIn("DELETED", text)             # first boot: legacy merge (DR bootstrap)
        self.assertTrue(marker)


if __name__ == "__main__":
    unittest.main()
