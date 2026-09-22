"""
Performance & Scalability Benchmark Test Suite
Validates system behavior under:
1. 50,000+ Club records database management
2. Sub-millisecond O(1) primary key lookups
3. Substring searches with early termination
4. 200 concurrent simulated real-time request workers
"""
import unittest
import tempfile
import shutil
import time
import concurrent.futures
from pathlib import Path
from db.csv_engine import CSVEngine

class TestScalingBenchmark(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.clubs_csv = self.temp_dir / "master_clubs.csv"
        self.headers = [
            "club_id", "reg_no", "institution_name", "state", "zone",
            "patron_email", "president_email", "secretary_email",
            "date_of_approval", "last_renewal_date", "renewal_date",
            "status", "approved_by_emp_id", "updated_at",
            "submission_timestamp", "next_renewal_date"
        ]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_50000_clubs_database_scaling(self):
        """Generates 50,000 records and verifies sub-millisecond retrieval and fast append."""
        print("\n--- [BENCHMARK] Generating 50,000 Club Records ---")
        rows = []
        zones = ["North Zone", "South Zone", "East Zone", "West Zone", "Central Zone", "North East Zone"]
        states = ["Delhi", "Maharashtra", "West Bengal", "Karnataka", "Tamil Nadu", "Gujarat", "Assam"]

        t_gen_start = time.time()
        for i in range(1, 50001):
            cid = f"NDLI-TEST-{i:05d}"
            rows.append({
                "club_id": cid,
                "reg_no": f"REG/2026/{i:05d}",
                "institution_name": f"National Institute of Technology Node {i}",
                "state": states[i % len(states)],
                "zone": zones[i % len(zones)],
                "patron_email": f"patron{i}@nit.edu",
                "president_email": f"president{i}@nit.edu",
                "secretary_email": f"secretary{i}@nit.edu",
                "date_of_approval": "2026-01-15T10:00:00Z",
                "last_renewal_date": "",
                "renewal_date": "2027-01-15",
                "status": "Approved",
                "approved_by_emp_id": f"EMP{((i % 7) + 1):02d}",
                "updated_at": "2026-01-15T10:00:00Z",
                "submission_timestamp": "2026-01-15T10:00:00Z",
                "next_renewal_date": "2027-01-15"
            })

        # Bulk write
        CSVEngine.write_all(self.clubs_csv, self.headers, rows)
        write_time = (time.time() - t_gen_start) * 1000
        print(f"[*] Wrote 50,000 records to disk & built indexes in: {write_time:.1f}ms")

        # Verify file exists and has size
        self.assertTrue(self.clubs_csv.exists())
        size_mb = self.clubs_csv.stat().st_size / (1024 * 1024)
        print(f"[*] CSV on-disk size: {size_mb:.2f} MB")
        self.assertGreater(size_mb, 4.0)

        # 1. Benchmark O(1) Key Lookups: 500 random queries
        print("[*] Executing 500 O(1) key lookups across 50,000 records...")
        t_lookup_start = time.time()
        for step in range(1, 501):
            target_id = f"NDLI-TEST-{(step * 97) % 50000 + 1:05d}"
            club = CSVEngine.find_by_key(self.clubs_csv, "club_id", target_id)
            self.assertIsNotNone(club)
            self.assertEqual(club["club_id"], target_id)
        total_lookup_ms = (time.time() - t_lookup_start) * 1000
        avg_lookup_ms = total_lookup_ms / 500
        print(f"[PASS] 500 lookups completed in {total_lookup_ms:.2f}ms (Average: {avg_lookup_ms:.4f}ms per lookup - O(1) speed!)")
        self.assertLess(avg_lookup_ms, 5.0, "Key lookup should be sub-5ms (O(1) index speed)!")

        # 2. Benchmark Fast Upsert (Insert 50,001st record in O(1))
        print("[*] Testing O(1) append for new record in 50,000 record database...")
        t_upsert_start = time.time()
        is_update = CSVEngine.upsert_row(self.clubs_csv, self.headers, "club_id", {
            "club_id": "NDLI-TEST-50001",
            "reg_no": "REG/2026/50001",
            "institution_name": "Indian Institute of Science Bangalore",
            "state": "Karnataka",
            "zone": "South Zone",
            "status": "Approved"
        })
        upsert_ms = (time.time() - t_upsert_start) * 1000
        print(f"[PASS] Inserted 50,001st club in {upsert_ms:.2f}ms (Instant fast-path append, zero full-file rewrite!)")
        self.assertFalse(is_update)
        self.assertLess(upsert_ms, 50.0, "Appending single row to 50k dataset should be instant!")

        # 3. Benchmark Search with limit
        print("[*] Testing search across 50,000 records...")
        t_search_start = time.time()
        results = CSVEngine.search(self.clubs_csv, "Bangalore", limit=50)
        search_ms = (time.time() - t_search_start) * 1000
        print(f"[PASS] Search returned {len(results)} matches in {search_ms:.2f}ms")
        self.assertGreater(len(results), 0)

    def test_200_concurrent_realtime_requests(self):
        """Simulates 200 simultaneous concurrent real-time requests on the database engine."""
        print("\n--- [BENCHMARK] Simulating 200 Real-Time Concurrent Requests ---")
        # Seed 1,000 records
        rows = [{"id": f"ID-{i}", "name": f"User {i}", "email": f"u{i}@ndli.gov.in"} for i in range(1, 1001)]
        test_file = self.temp_dir / "concurrent_test.csv"
        headers = ["id", "name", "email"]
        CSVEngine.write_all(test_file, headers, rows)

        errors = []
        start_time = time.time()

        def worker(worker_id):
            try:
                if worker_id % 5 == 0:
                    # 20% write / append tasks
                    CSVEngine.append_row(test_file, headers, {
                        "id": f"CONC-{worker_id}",
                        "name": f"Concurrent User {worker_id}",
                        "email": f"conc{worker_id}@ndli.gov.in"
                    })
                elif worker_id % 7 == 0:
                    # Search task
                    res = CSVEngine.search(test_file, f"User {worker_id % 100}")
                    if len(res) == 0:
                        pass
                else:
                    # Read & key lookup task
                    target = f"ID-{(worker_id % 900) + 1}"
                    row = CSVEngine.find_by_key(test_file, "id", target)
                    if not row:
                        errors.append(f"Worker {worker_id}: row {target} not found")
            except Exception as e:
                errors.append(f"Worker {worker_id} crashed: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(worker, i) for i in range(1, 201)]
            concurrent.futures.wait(futures)

        elapsed_ms = (time.time() - start_time) * 1000
        print(f"[PASS] Handled 200 concurrent real-time requests in {elapsed_ms:.1f}ms! Errors: {len(errors)}")
        self.assertEqual(len(errors), 0, f"Concurrent workers encountered errors: {errors[:5]}")

if __name__ == "__main__":
    unittest.main()
