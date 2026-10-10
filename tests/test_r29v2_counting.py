"""
R29v2 — COUNTING HONESTY LOCK TESTS (the EMP01 "26,663 vs 26,655" fix).

The bug (found by the user's smoke on R29, 2026-10-10): the employee quota card
and the admin Performance Matrix could show DIFFERENT support numbers for the
same employee. Root causes, both verified in code:

  (A) the matrix bucketed activities against a 5-label allowlist and silently
      DROPPED every row it did not recognise — "Registration Renewal",
      "Data Correction" (both created by the app itself!) and anything new —
      while the quota counted every non-approval row. Rows vanished.
  (B) the quota derived from the node log UNION the master log, the matrix read
      master only — node-vs-master drift inflated one side invisibly.

The fix (R29v2): ONE bucketing rule (SyncEngine.bucket_activity — catch-all
"other", nothing can fall through) + ONE activity source
(SyncEngine.combined_activities_for — node ∪ master) + the quota card showing
the matrix's own four cells.

Locks:
  1. a stray/unseen support_type lands in the "other" bucket — counted, visible
  2. the "Data Migration" audit-marker row counts NOWHERE (never live work)
  3. a row that exists ONLY in the employee node file still shows in the matrix
  4. THE invariant: the quota card's cells == the admin matrix's cells, and
     live support == online + offline + other (per employee, always)
  5. no activity row is uncounted: rows == approval + online + offline +
     other + skipped
  6. the quota card carries the four-cell wording
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer

from app import NDLIRequestHandler
from init_db import initialize_database

EMP = "EMP07"          # seeded employee, untouched by other test modules
PREFIX = "ACT-R29V2-"  # unique activity_id prefix -> cheap, reliable cleanup

# (suffix, support_type) fixture. "Carrier Pigeon Service" is a type that does
# not exist anywhere in the app: if it can still land in a visible bucket, no
# future support_type can ever vanish.
MASTER_FIXTURE = [
    ("RR1", "Registration Renewal"),
    ("RR2", "Registration Renewal"),
    ("DC1", "Data Correction"),
    ("CP1", "Carrier Pigeon Service"),
    ("PH1", "Phone call and remote assistance"),
    ("ON1", "Online training"),
    ("OF1", "Offline training"),
    ("DM1", "Data Migration"),
]

# Expected bucket delta for MASTER_FIXTURE (everything except the marker row).
EXPECT_OTHER = 5      # RR1, RR2, DC1, CP1, PH1
EXPECT_ONLINE = 1     # ON1
EXPECT_OFFLINE = 1    # OF1
EXPECT_LIVE_SUPPORT = EXPECT_OTHER + EXPECT_ONLINE + EXPECT_OFFLINE


class TestR29v2Counting(unittest.TestCase):
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

    # ---------- plumbing ----------
    def _get(self, path):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _matrix(self):
        data = self._get("/api/admin/employee-performance")
        rows = {o["emp_id"]: o for o in data.get("officers", [])}
        self.assertIn(EMP, rows, f"{EMP} must be an officer in every test store")
        return rows

    def _profile(self):
        data = self._get(f"/api/employees/profile?id={EMP}")
        self.assertTrue(data.get("found"), data)
        return data["employee"]

    def _rows(self):
        from config import MASTER_ACTIVITIES_CSV
        from db.csv_engine import CSVEngine
        from db.schemas import ACTIVITY_FIELDS
        return CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)

    def _write_master(self, rows):
        from config import MASTER_ACTIVITIES_CSV
        from db.csv_engine import CSVEngine
        from db.schemas import ACTIVITY_FIELDS
        CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, rows)

    def _node_path(self):
        from db.sync_engine import SyncEngine
        return SyncEngine.get_employee_activities_path(EMP)

    def _node_rows(self):
        from db.csv_engine import CSVEngine
        from db.schemas import ACTIVITY_FIELDS
        p = self._node_path()
        return CSVEngine.read_all(p, ACTIVITY_FIELDS) if p.exists() else []

    def _write_node(self, rows):
        from db.csv_engine import CSVEngine
        from db.schemas import ACTIVITY_FIELDS
        CSVEngine.write_all(self._node_path(), ACTIVITY_FIELDS, rows)

    @staticmethod
    def _row(suffix, support_type, emp=EMP):
        return {
            "activity_id": f"{PREFIX}{suffix}",
            "emp_id": emp,
            "timestamp": "2026-10-10T10:00:00+00:00",
            "support_type": support_type,
            "priority_flag": "",
            "club_id": "",
            "notes": "r29v2 lock-test fixture row",
        }

    def _cleanup(self):
        """Self-sufficient: also sweeps leftovers of a crashed earlier run."""
        self._write_master([r for r in self._rows()
                           if not (r.get("activity_id") or "").startswith(PREFIX)])
        self._write_node([r for r in self._node_rows()
                          if not (r.get("activity_id") or "").startswith(PREFIX)])

    def setUp(self):
        self._cleanup()
        self.base_matrix = self._matrix()[EMP]
        self.base_profile = self._profile()

    def tearDown(self):
        self._cleanup()
        from db.sync_engine import SyncEngine
        SyncEngine.recompute_and_persist_quota(EMP)

    def _add_master_fixture(self):
        self._write_master(self._rows() + [self._row(s, t) for s, t in MASTER_FIXTURE])

    def _delta_matrix(self, after):
        b, a = self.base_matrix, after
        return {
            "online": a["live_online_training"] - b["live_online_training"],
            "offline": a["live_offline_training"] - b["live_offline_training"],
            "other": a["live_other_supports"] - b["live_other_supports"],
            "total": (a["online_training"] + a["offline_training"] + a["other_supports"])
                     - (b["online_training"] + b["offline_training"] + b["other_supports"]),
        }

    # ---------- 1. nothing may fall through ----------
    def test_stray_support_types_land_in_the_other_bucket(self):
        self._add_master_fixture()
        d = self._delta_matrix(self._matrix()[EMP])
        self.assertEqual(d["other"], EXPECT_OTHER,
                         "Registration Renewal / Data Correction / unknown types "
                         "must land in the 'other' bucket, not vanish")
        self.assertEqual(d["online"], EXPECT_ONLINE)
        self.assertEqual(d["offline"], EXPECT_OFFLINE)
        self.assertEqual(d["total"], EXPECT_LIVE_SUPPORT,
                         "the marker row must not add to any visible total")

        p = self._profile()
        self.assertEqual(p["live_online_training"] - self.base_profile["live_online_training"], EXPECT_ONLINE)
        self.assertEqual(p["live_offline_training"] - self.base_profile["live_offline_training"], EXPECT_OFFLINE)
        self.assertEqual(p["live_other_supports"] - self.base_profile["live_other_supports"], EXPECT_OTHER)
        self.assertEqual(p["live_support_logs_count"] - self.base_profile["live_support_logs_count"],
                         EXPECT_LIVE_SUPPORT,
                         "the quota card's live support must include every stray type too")

    # ---------- 2. the marker row is bookkeeping, not work ----------
    def test_data_migration_marker_is_counted_nowhere(self):
        self._write_master(self._rows() + [self._row("DM1", "Data Migration")])
        d = self._delta_matrix(self._matrix()[EMP])
        self.assertEqual(d, {"online": 0, "offline": 0, "other": 0, "total": 0},
                         "a 'Data Migration' summary row is history bookkeeping")
        p = self._profile()
        self.assertEqual(p["live_support_logs_count"], self.base_profile["live_support_logs_count"])
        self.assertEqual(p["live_other_supports"], self.base_profile["live_other_supports"])

    # ---------- 3. node-vs-master drift may not hide rows ----------
    def test_node_only_row_shows_in_the_matrix(self):
        self._write_node(self._node_rows() + [self._row("NODE1", "Data Correction")])
        d = self._delta_matrix(self._matrix()[EMP])
        self.assertEqual(d["other"], 1,
                         "the matrix must read the same node+master union as the quota")
        p = self._profile()
        self.assertEqual(p["live_other_supports"] - self.base_profile["live_other_supports"], 1)

    # ---------- 4. THE invariant ----------
    def test_quota_card_cells_equal_matrix_cells(self):
        officers = self._matrix()
        for emp_id, off in officers.items():
            p = self._get(f"/api/employees/profile?id={emp_id}")["employee"]
            self.assertEqual(p["live_online_training"], off["live_online_training"],
                             f"{emp_id}: online cell drifted between card and matrix")
            self.assertEqual(p["live_offline_training"], off["live_offline_training"],
                             f"{emp_id}: offline cell drifted between card and matrix")
            self.assertEqual(p["live_other_supports"], off["live_other_supports"],
                             f"{emp_id}: other cell drifted between card and matrix")
            live_sum = p["live_online_training"] + p["live_offline_training"] + p["live_other_supports"]
            self.assertEqual(p["live_support_logs_count"], live_sum,
                             f"{emp_id}: live support must be exactly online+offline+other")
            self.assertEqual(off["other_supports"],
                             off["live_other_supports"] + off["migrated_support"])
            self.assertEqual(off["online_training"],
                             off["live_online_training"] + off["migrated_online_workshops"])

    # ---------- 5. every row is in exactly one bucket ----------
    def test_no_activity_row_is_uncounted(self):
        from db.sync_engine import SyncEngine
        self._add_master_fixture()
        rows = [r for r in self._rows() if (r.get("activity_id") or "").startswith(PREFIX)]
        buckets = [SyncEngine.bucket_activity(r) for r in rows]
        self.assertEqual(buckets.count("skip"), 1, buckets)
        self.assertEqual(buckets.count("online"), EXPECT_ONLINE, buckets)
        self.assertEqual(buckets.count("offline"), EXPECT_OFFLINE, buckets)
        self.assertEqual(buckets.count("other"), EXPECT_OTHER, buckets)
        self.assertEqual(buckets.count("approval"), 0, buckets)
        self.assertEqual(len(rows), len(buckets),
                         "every fixture row must receive exactly one bucket")
        self.assertIn("skip", buckets, "the marker row must be the only 'skip'")

    # ---------- 6. the card must SAY what it shows ----------
    def test_quota_card_carries_the_four_matrix_cells(self):
        with open("templates/employee.html", encoding="utf-8") as fh:
            emp_html = fh.read()
        for anchor in ('id="quota-clubs-count"', 'id="quota-online-count"',
                       'id="quota-offline-count"', 'id="quota-support-count"',
                       'id="quota-live-online"', 'id="quota-legacy-online"'):
            self.assertIn(anchor, emp_html, f"quota card must carry {anchor}")
        self.assertIn("Other Support", emp_html,
                      "the 4th cell is labelled like the matrix column")
        p = self.base_profile
        for key in ("live_online_training", "live_offline_training",
                    "live_other_supports", "legacy_online_workshops_count",
                    "legacy_support_count"):
            self.assertIn(key, p, f"profile payload must carry {key}")


if __name__ == "__main__":
    unittest.main()
