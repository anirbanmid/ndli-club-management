"""
R35 "PPT Training Library" lock tests.

Spec (user 2026-10-11): the admin may keep exactly 2 PowerPoint decks on the
server for employees to download (online training). `.ppt`/`.pptx`/`.ppsx`
only; BOTH decks share ONE 15 MB budget in TOTAL; upload/replace/delete is
Master-Admin-only; listing + single-click download is for any authenticated
session; the Hard Reset wipes the library (nothing survives the handover).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import base64
import json
import shutil
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest import mock

import app as app_module
from app import NDLIRequestHandler, TRAINING_MAX_TOTAL_BYTES, TRAINING_DIR
from init_db import initialize_database
from config import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
from db.sync_engine import SyncEngine

PPTX_BYTES = b"PK\x03\x04" + b"fake-ooxml-deck-payload" * 4
PPT_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"fake-legacy-ppt-payload" * 4


def b64(blob: bytes) -> str:
    return base64.b64encode(blob).decode("ascii")


class TestTrainingPptLibrary(unittest.TestCase):

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

    def setUp(self):
        self._clear_training()

    def tearDown(self):
        self._clear_training()

    @staticmethod
    def _clear_training():
        if TRAINING_DIR.exists():
            shutil.rmtree(TRAINING_DIR)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _token(self, kind="admin"):
        from auth_util import admin_token
        if kind == "admin":
            return admin_token(self.base_url, self.__class__.__name__)
        status, res = self._post_json("/api/auth/login",
                                      {"email": "EMP01", "password": "Seed#EMP01-Rotated2026"},
                                      token="")
        self.assertEqual(status, 200)
        return res["session"]["token"]

    def _post_json(self, path, payload, token=None):
        if token is None:
            token = self._token("admin")
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def _get(self, path, token=None, raw=False):
        if token is None:
            token = self._token("admin")
        req = urllib.request.Request(self.base_url + path)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read()
                if raw:
                    return resp.status, body, dict(resp.headers)
                return resp.status, json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read()
            if raw:
                return e.code, body, dict(e.headers)
            return e.code, json.loads(body.decode("utf-8") or "{}")

    def _upload(self, slot, filename, blob, token=None):
        return self._post_json("/api/admin/training/upload",
                               {"slot": slot, "filename": filename, "data": b64(blob)},
                               token=token)

    # ------------------------------------------------------------------
    # round trip: upload -> list -> download -> replace -> delete
    # ------------------------------------------------------------------
    def test_upload_list_download_replace_delete_roundtrip(self):
        st, res = self._upload("1", "Deck One.pptx", PPTX_BYTES)
        self.assertEqual(st, 200)
        self.assertTrue(res.get("success"))
        st, res = self._upload("2", "Deck Two.ppt", PPT_BYTES)
        self.assertEqual(st, 200)

        # list (admin view)
        st, res = self._get("/api/training/files")
        self.assertEqual(st, 200)
        self.assertEqual(res["slots"]["1"]["filename"], "Deck One.pptx")
        self.assertEqual(res["slots"]["2"]["filename"], "Deck Two.ppt")
        self.assertEqual(res["total_bytes"], len(PPTX_BYTES) + len(PPT_BYTES))
        self.assertEqual(res["max_total_bytes"], TRAINING_MAX_TOTAL_BYTES)

        # single-click download as an EMPLOYEE (any authenticated session)
        st, body, headers = self._get("/api/training/download/1",
                                      token=self._token("employee"), raw=True)
        self.assertEqual(st, 200)
        self.assertEqual(body, PPTX_BYTES, "Downloaded bytes must be identical")
        self.assertIn("Deck One.pptx", headers.get("Content-Disposition", ""))

        # replace slot 1 -> the old file must be gone
        st, res = self._upload("1", "Deck One v2.pptx", PPTX_BYTES + b"v2")
        self.assertEqual(st, 200)
        st, body, headers = self._get("/api/training/download/1", raw=True)
        self.assertEqual(body, PPTX_BYTES + b"v2")
        self.assertIn("Deck One v2.pptx", headers.get("Content-Disposition", ""))
        slot1_files = [p.name for p in TRAINING_DIR.glob("slot1.*")]
        self.assertEqual(len(slot1_files), 1, "Replace must leave exactly one file per slot")

        # delete slot 2 -> empty, budget freed
        st, res = self._post_json("/api/admin/training/delete", {"slot": "2"})
        self.assertEqual(st, 200)
        st, res = self._get("/api/training/files")
        self.assertNotIn("2", res["slots"])
        st, _, _ = self._get("/api/training/download/2", raw=True)
        self.assertEqual(st, 404)

    # ------------------------------------------------------------------
    # upload validation (extension + content + base64 + slot)
    # ------------------------------------------------------------------
    def test_upload_validation(self):
        st, res = self._upload("1", "evil.pdf", PPTX_BYTES)
        self.assertEqual(st, 422, "Only .ppt/.pptx/.ppsx are accepted")
        st, res = self._upload("1", "noext", PPTX_BYTES)
        self.assertEqual(st, 422)
        st, res = self._upload("1", "fake.pptx", b"not a zip container at all")
        self.assertEqual(st, 422, "OOXML decks must be real ZIP-based files")
        st, res = self._post_json("/api/admin/training/upload",
                                  {"slot": "1", "filename": "a.pptx", "data": "!!not-base64!!"})
        self.assertEqual(st, 400)
        st, res = self._post_json("/api/admin/training/upload",
                                  {"slot": "3", "filename": "a.pptx", "data": b64(PPTX_BYTES)})
        self.assertEqual(st, 400, "Only slots 1 and 2 exist")
        st, res = self._get("/api/training/files")
        self.assertEqual(res.get("slots") or {}, {}, "Rejected uploads must store nothing")

    # ------------------------------------------------------------------
    # the shared 15 MB TOTAL budget
    # ------------------------------------------------------------------
    def test_shared_budget_is_15mb_total_and_enforced(self):
        self.assertEqual(TRAINING_MAX_TOTAL_BYTES, 15 * 1024 * 1024,
                         "Spec pin: BOTH decks share ONE 15 MB budget (2026-10-11)")
        with mock.patch.object(app_module, "TRAINING_MAX_TOTAL_BYTES", 100):
            st, res = self._upload("1", "a.pptx", PPTX_BYTES[:60])
            self.assertEqual(st, 200)
            st, res = self._upload("2", "b.pptx", PPTX_BYTES[:60])
            self.assertEqual(st, 413, "60 + 60 > 100: the second deck must be refused")
            self.assertIn("COMBINED", str(res.get("message") or ""))
            # replacing the SAME slot only competes with the other slot's size
            st, res = self._upload("1", "a2.pptx", PPTX_BYTES[:100])
            self.assertEqual(st, 200, "Replacing slot 1 with a file that fits alone is allowed")

    # ------------------------------------------------------------------
    # auth gates: admin-only writes, any-session reads
    # ------------------------------------------------------------------
    def test_auth_gates(self):
        # unauthenticated -> 401 everywhere
        st, _ = self._get("/api/training/files", token="")
        self.assertEqual(st, 401)
        st, _, _ = self._get("/api/training/download/1", token="", raw=True)
        self.assertEqual(st, 401)
        st, _ = self._upload("1", "a.pptx", PPTX_BYTES, token="")
        self.assertEqual(st, 401)

        # employee -> reads allowed, writes refused
        emp = self._token("employee")
        st, _ = self._upload("1", "a.pptx", PPTX_BYTES, token=emp)
        self.assertEqual(st, 403, "Only the Master Admin may upload")
        st, _ = self._post_json("/api/admin/training/delete", {"slot": "1"}, token=emp)
        self.assertEqual(st, 403, "Only the Master Admin may delete")
        st, res = self._get("/api/training/files", token=emp)
        self.assertEqual(st, 200, "Employees may list the library")
        self._upload("1", "a.pptx", PPTX_BYTES)
        st, body, _ = self._get("/api/training/download/1", token=emp, raw=True)
        self.assertEqual(st, 200, "Employees may download with one click")
        self.assertEqual(body, PPTX_BYTES)

    # ------------------------------------------------------------------
    # hard reset tie-in: the library never survives the handover
    # ------------------------------------------------------------------
    def test_hard_reset_wipes_training_slots(self):
        self._upload("1", "a.pptx", PPTX_BYTES)
        self._upload("2", "b.ppt", PPT_BYTES)
        self.assertTrue(TRAINING_DIR.exists())
        result = SyncEngine.wipe_training_slots()
        self.assertGreaterEqual(result.get("training_slots_wiped", 0), 2,
                                "Both decks must be removed")
        leftovers = [p.name for p in TRAINING_DIR.iterdir() if p.is_file()] if TRAINING_DIR.exists() else []
        self.assertEqual(leftovers, [],
                         "Nothing (not even slot metadata) may survive the hard reset")

    # ------------------------------------------------------------------
    # UI markers (both portals) — no new DOM modals (test_r3 pins stay)
    # ------------------------------------------------------------------
    def test_ui_markers_present(self):
        admin_html = (app_module.BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        for marker in ("📚 Training Materials (PPT)", "training-file-input", "training-slots",
                       "loadTrainingSlots()", "trainingPickUpload", "/api/admin/training/upload",
                       "15 MB budget"):
            self.assertIn(marker, admin_html, f"Admin training UI must contain: {marker}")
        emp_html = (app_module.BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        for marker in ("📚 Training Materials (PPT)", "training-decks", "loadTrainingDecks()",
                       "trainingDownload", "/api/training/download/"):
            self.assertIn(marker, emp_html, f"Employee training UI must contain: {marker}")


if __name__ == "__main__":
    unittest.main()
