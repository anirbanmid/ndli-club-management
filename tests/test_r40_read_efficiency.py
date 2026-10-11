"""
tests/test_r40_read_efficiency.py

R40 "kill the O(n) wall" pins (CRITIQUE_AND_ROADMAP.md section 3):

1. READ EFFICIENCY: one /api/admin/employee-performance request reads
   master_employee_history.csv AT MOST TWICE (pre-R40: once per employee + 1
   more = 8 reads measured at 7 officers / 100k history rows). One
   /api/admin/metrics request reads it AT MOST TWICE (pre-R40: 2).
2. SEAM PARITY: the injectable `rows=` seam on the history foundation
   functions returns results IDENTICAL to the file-read path, and injected
   rows are never mutated (read-only contract).
3. PARSE MEMO PARITY: parse_iso_or_date (R40 memoized) is result-identical to
   the pre-R40 semantics for every input class, and the memo actually engages.
4. UPLOAD QUEUE HONESTY: a busy queue COALESCES (latest content wins per
   file) instead of the pre-R40 silent drop; pending overflow logs a LOUD
   event; the backlog drains through free workers.
"""
import _seed_env  # noqa: F401  (seed test env before config import)
import _bench  # noqa: F401  (host-tolerant wall-clock budgets; test-only)
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.csv_engine import CSVEngine
from db import migration_engine
from db.migration_engine import (
    MIGRATION_HISTORY_FIELDS,
    baselines_for,
    existing_history_count,
    history_grand_totals,
    history_period_years,
    history_rows,
    history_summary,
)
from db.sync_engine import parse_iso_or_date, _parse_string_date
from db import storage_adapter

import app as app_mod
from auth_util import admin_token

CLUB = {
    "hist_id": "", "emp_id": "", "period_year": "2023", "period_month": "04",
    "period_week": "", "task_type": "Club Support", "approvals_count": "3",
    "support_count": "5", "online_workshops_count": "1",
    "user_registrations_count": "10", "local_events_count": "2",
    "global_events_count": "0", "nature": "Remote support (AnyDesk)",
    "state": "Delhi", "zone": "North", "entry_timestamp": "2023-07-01T10:00:00Z",
    "batch_id": "B1",
}


def _fixture_rows():
    rows = []
    for emp, years in (("EMP01", ("2022", "2023", "2024")), ("EMP02", ("2023",))):
        for y in years:
            r = dict(CLUB)
            r["hist_id"] = f"H-{emp}-{y}"
            r["emp_id"] = emp
            r["period_year"] = y
            rows.append(r)
    return rows


class TestHistorySeamParity(unittest.TestCase):
    """R40 pin 2: injected rows == file reads; injected rows never mutated."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.hist_path = Path(self._tmp.name) / "master_employee_history.csv"
        self.rows = _fixture_rows()
        CSVEngine.write_all(self.hist_path, MIGRATION_HISTORY_FIELDS, self.rows)
        patcher = mock.patch.object(
            migration_engine, "MASTER_HISTORY_CSV", self.hist_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_01_baselines_for_parity_and_no_mutation(self):
        injected = history_rows()
        pristine = copy.deepcopy(injected)
        for args in (("EMP01",), ("EMP02",), ("EMP99",),
                     ("EMP01", "2023"), ("EMP01", "ALL", None, "delhi"),
                     ("EMP01", "2023", 4, "Delhi")):
            emp, *rest = args
            fy = rest[0] if len(rest) > 0 else None
            fm = rest[1] if len(rest) > 1 else None
            fs = rest[2] if len(rest) > 2 else None
            from_file = baselines_for(emp, fy, fm, fs)
            from_seam = baselines_for(emp, fy, fm, fs, rows=injected)
            self.assertEqual(from_file, from_seam,
                             f"seam must match file reads for {args}")
        self.assertEqual(pristine, injected, "injected rows must never be mutated")

    def test_02_summary_grand_years_parity_and_no_mutation(self):
        injected = history_rows()
        pristine = copy.deepcopy(injected)
        for emp in ("EMP01", "EMP02", "EMP99"):
            self.assertEqual(history_summary(emp), history_summary(emp, rows=injected))
            self.assertEqual(existing_history_count(emp),
                             existing_history_count(emp, rows=injected))
        for fy, fz in (("", ""), ("2023", ""), ("2023", "North"), ("ALL", "ALL")):
            self.assertEqual(history_grand_totals(fy, fz),
                             history_grand_totals(fy, fz, rows=injected))
        self.assertEqual(history_period_years(), history_period_years(rows=injected))
        self.assertEqual(pristine, injected, "injected rows must never be mutated")

    def test_03_seam_returns_injected_object(self):
        injected = history_rows()
        self.assertIs(history_rows(injected), injected)


class TestReadEfficiencyPins(unittest.TestCase):
    """R40 pin 1: the per-employee fan-out must not re-read the history file."""

    @classmethod
    def setUpClass(cls):
        cls.server = app_mod.ThreadedHTTPServer(("127.0.0.1", 0),
                                               app_mod.NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever,
                                             daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path, token):
        req = urllib.request.Request(self.base_url + path)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    def _count_history_reads(self, fn, hist_path):
        orig = CSVEngine.read_all
        counter = {"n": 0}
        hist_resolved = str(Path(hist_path).resolve())

        def counting(file_path, headers=None, copy=True):
            try:
                if str(Path(str(file_path)).resolve()) == hist_resolved:
                    counter["n"] += 1
            except Exception:
                pass
            return orig(file_path, headers, copy)

        with mock.patch.object(CSVEngine, "read_all",
                               staticmethod(counting)):
            fn()
        return counter["n"]

    def test_01_employee_performance_reads_history_at_most_twice(self):
        rows = _fixture_rows()
        with tempfile.TemporaryDirectory() as td:
            hist_path = Path(td) / "master_employee_history.csv"
            CSVEngine.write_all(hist_path, MIGRATION_HISTORY_FIELDS, rows)
            token = admin_token(self.base_url, scope="r40perf")
            with mock.patch.object(migration_engine, "MASTER_HISTORY_CSV",
                                   hist_path):
                # Meaningful-precondition: the fan-out loop must actually run
                # over several employees (or the pin below is vacuous).
                payload = self._get("/api/admin/employee-performance", token)
                emps = payload.get("officers") or []
                self.assertGreaterEqual(len(emps), 3,
                                        "fixture must exercise the per-employee fan-out")
                reads = self._count_history_reads(
                    lambda: self._get("/api/admin/employee-performance", token),
                    hist_path)
        self.assertGreaterEqual(reads, 1, "the request must read history at all")
        self.assertLessEqual(
            reads, 2,
            f"employee-performance re-read the history file {reads}x per request "
            f"(R40 budget: <= 2 — pre-R40 measured 8)")

    def test_02_admin_metrics_reads_history_at_most_twice(self):
        rows = _fixture_rows()
        with tempfile.TemporaryDirectory() as td:
            hist_path = Path(td) / "master_employee_history.csv"
            CSVEngine.write_all(hist_path, MIGRATION_HISTORY_FIELDS, rows)
            token = admin_token(self.base_url, scope="r40perf")
            with mock.patch.object(migration_engine, "MASTER_HISTORY_CSV",
                                   hist_path):
                payload = self._get("/api/admin/metrics", token)
                self.assertIn("summary", payload)
                reads = self._count_history_reads(
                    lambda: self._get("/api/admin/metrics", token), hist_path)
        self.assertGreaterEqual(reads, 1)
        self.assertLessEqual(
            reads, 2,
            f"admin metrics re-read the history file {reads}x per request "
            f"(R40 budget: <= 2 — pre-R40 measured 2 with double-read helpers)")


class TestParseMemoParity(unittest.TestCase):
    """R40 pin 3: the memoized parser is semantically identical + engages."""

    def test_01_battery_parity(self):
        battery = [
            "2025-01-15", "2025-01-15T10:00:00Z", "2025-01-15 10:00:00",
            "15-01-2025", "15/01/2025", "2025/01/15", "2025-1-5",
            "", "-", "  ", "garbage", "0000-00-00", "2025-13-40",
            "2025-02-30", None, 20250115, 0,
        ]
        for v in battery:
            first = parse_iso_or_date(v)
            _parse_string_date.cache_clear()
            second = parse_iso_or_date(v)
            self.assertEqual(first, second, f"memo must not change results for {v!r}")
        self.assertEqual(parse_iso_or_date("2025-01-15"), date(2025, 1, 15))
        self.assertEqual(parse_iso_or_date("15-01-2025"), date(2025, 1, 15))
        self.assertIsNone(parse_iso_or_date("garbage"))
        self.assertEqual(parse_iso_or_date(datetime(2025, 1, 15, 10, 0)),
                         date(2025, 1, 15))
        self.assertEqual(parse_iso_or_date(date(2025, 1, 15)), date(2025, 1, 15))

    def test_02_memo_engages_and_handles_unhashable(self):
        _parse_string_date.cache_clear()
        for _ in range(5):
            parse_iso_or_date("2025-01-15")
        info = _parse_string_date.cache_info()
        self.assertGreaterEqual(info.hits, 4, "the memo must actually serve repeats")
        # unhashable input must never crash (it is str()-ed before the cache)
        self.assertIsNone(parse_iso_or_date(["not", "a", "date"]))


class TestUploadQueueHonesty(unittest.TestCase):
    """R40 pin 4: busy = coalesce + drain, overflow = LOUD, never a silent drop."""

    def setUp(self):
        self._orig_sem = storage_adapter._UPLOAD_SEMAPHORE
        storage_adapter._UPLOAD_SEMAPHORE = threading.BoundedSemaphore(value=4)
        with storage_adapter._PENDING_LOCK:
            storage_adapter._PENDING.clear()
            storage_adapter._QUEUE_EVENTS.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        storage_adapter._UPLOAD_SEMAPHORE = self._orig_sem
        with storage_adapter._PENDING_LOCK:
            storage_adapter._PENDING.clear()
            storage_adapter._QUEUE_EVENTS.clear()

    def _events(self):
        with storage_adapter._PENDING_LOCK:
            return list(storage_adapter._QUEUE_EVENTS)

    def test_01_busy_queue_coalesces_and_drains(self):
        started = threading.Event()
        release = threading.Event()
        done = []
        lock = threading.Lock()
        blockers_running = [0]

        def target(rel, content):
            with lock:
                done.append((rel, content))
                if rel.startswith("blocker"):
                    blockers_running[0] += 1
                    if blockers_running[0] == 4:
                        started.set()
            if rel.startswith("blocker"):
                release.wait(10)

        for i in range(4):
            storage_adapter._dispatch_upload(target, f"blocker{i}.csv", "x")
        self.assertTrue(started.wait(10), "4 blockers must occupy all slots")

        # All workers busy: these must NOT vanish (pre-R40: silent drop).
        storage_adapter._dispatch_upload(target, "f1.csv", "v1")
        storage_adapter._dispatch_upload(target, "f1.csv", "v2")
        storage_adapter._dispatch_upload(target, "f2.csv", "v3")
        time.sleep(0.2)
        release.set()

        deadline = time.time() + 10
        while time.time() < deadline:
            with storage_adapter._PENDING_LOCK:
                if not storage_adapter._PENDING:
                    break
            time.sleep(0.05)

        with lock:
            got = dict(done)
        self.assertIn("f1.csv", got, "coalesced upload must eventually run")
        self.assertIn("f2.csv", got, "pending upload must eventually run")
        self.assertEqual(got["f1.csv"], "v2", "latest content must win on coalesce")
        self.assertEqual(got["f2.csv"], "v3")
        ev = self._events()
        self.assertFalse(any("OVERFLOW" in e for e in ev),
                         f"no overflow expected: {ev}")
        self.assertTrue(any("queued upload f1.csv" in e for e in ev),
                        f"queueing must be visible: {ev}")

    def test_02_overflow_is_loud_never_silent(self):
        orig_max = storage_adapter._PENDING_MAX
        storage_adapter._PENDING_MAX = 2
        self.addCleanup(setattr, storage_adapter, "_PENDING_MAX", orig_max)
        started = threading.Event()
        release = threading.Event()
        blockers_running = [0]
        lock = threading.Lock()

        def target(rel, content):
            if rel.startswith("blocker"):
                with lock:
                    blockers_running[0] += 1
                    if blockers_running[0] == 4:
                        started.set()
                release.wait(10)

        for i in range(4):
            storage_adapter._dispatch_upload(target, f"blocker{i}.csv", "x")
        self.assertTrue(started.wait(10))

        storage_adapter._dispatch_upload(target, "p1.csv", "a")
        storage_adapter._dispatch_upload(target, "p2.csv", "b")
        storage_adapter._dispatch_upload(target, "p3.csv", "c")  # over the bound
        time.sleep(0.2)
        release.set()

        deadline = time.time() + 10
        while time.time() < deadline:
            with storage_adapter._PENDING_LOCK:
                if not storage_adapter._PENDING:
                    break
            time.sleep(0.05)

        ev = self._events()
        self.assertTrue(any("OVERFLOW" in e for e in ev),
                        f"overflow must be LOUD: {ev}")
        self.assertTrue(any("dropped upload p3.csv" in e for e in ev),
                        f"the dropped file must be named: {ev}")


if __name__ == "__main__":
    unittest.main()
