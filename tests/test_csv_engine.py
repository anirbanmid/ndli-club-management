"""
Unit tests for thread-safe CSV manipulation engine.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from db.csv_engine import CSVEngine

class TestCSVEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.csv_path = self.temp_dir / "test.csv"
        self.headers = ["id", "name", "email", "role"]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ensure_file_creates_header(self):
        CSVEngine.ensure_file(self.csv_path, self.headers)
        self.assertTrue(self.csv_path.exists())
        rows = CSVEngine.read_all(self.csv_path)
        self.assertEqual(len(rows), 0)

    def test_append_and_read(self):
        CSVEngine.ensure_file(self.csv_path, self.headers)
        CSVEngine.append_row(self.csv_path, self.headers, {
            "id": "1",
            "name": "Arjun",
            "email": "arjun@example.com",
            "role": "EMPLOYEE"
        })
        rows = CSVEngine.read_all(self.csv_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Arjun")

    def test_upsert_row(self):
        CSVEngine.ensure_file(self.csv_path, self.headers)
        # Insert
        updated = CSVEngine.upsert_row(self.csv_path, self.headers, "id", {
            "id": "100",
            "name": "Kavita",
            "email": "kavita@example.com",
            "role": "ADMIN"
        })
        self.assertFalse(updated)

        # Update
        updated2 = CSVEngine.upsert_row(self.csv_path, self.headers, "id", {
            "id": "100",
            "name": "Kavita Sharma",
            "email": "kavita.sharma@example.com",
            "role": "ADMIN"
        })
        self.assertTrue(updated2)

        rows = CSVEngine.read_all(self.csv_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Kavita Sharma")

    def test_search(self):
        CSVEngine.ensure_file(self.csv_path, self.headers)
        CSVEngine.append_row(self.csv_path, self.headers, {"id": "1", "name": "IIT Bombay", "email": "a@iitb.ac.in", "role": "CLUB"})
        CSVEngine.append_row(self.csv_path, self.headers, {"id": "2", "name": "IIT Delhi", "email": "b@iitd.ac.in", "role": "CLUB"})
        CSVEngine.append_row(self.csv_path, self.headers, {"id": "3", "name": "NIT Trichy", "email": "c@nitt.edu", "role": "CLUB"})

        res = CSVEngine.search(self.csv_path, "Delhi")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["name"], "IIT Delhi")

        res_iit = CSVEngine.search(self.csv_path, "IIT")
        self.assertEqual(len(res_iit), 2)

    def test_find_by_key(self):
        CSVEngine.ensure_file(self.csv_path, self.headers)
        CSVEngine.append_row(self.csv_path, self.headers, {"id": "EMP01", "name": "Rohan Sharma", "email": "rohan@ndli.iitkgp.ac.in", "role": "EMPLOYEE"})
        CSVEngine.append_row(self.csv_path, self.headers, {"id": "EMP02", "name": "Pooja Verma", "email": "pooja@ndli.iitkgp.ac.in", "role": "EMPLOYEE"})

        found = CSVEngine.find_by_key(self.csv_path, "id", "emp01")
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Rohan Sharma")

        found_email = CSVEngine.find_by_key(self.csv_path, "email", "POOJA@ndli.iitkgp.ac.in")
        self.assertIsNotNone(found_email)
        self.assertEqual(found_email["id"], "EMP02")

        missing = CSVEngine.find_by_key(self.csv_path, "id", "EMP99")
        self.assertIsNone(missing)

if __name__ == "__main__":
    unittest.main()
