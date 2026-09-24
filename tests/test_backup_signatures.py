"""
Backup/restore coverage for digital signature assets (data/signatures/).

The backup engine is CSV-oriented; signature assets (pi_signature.png,
settings.json) need explicit handling or a disaster restore silently loses
the PI signature used by the certificate engine.
"""
import json
import shutil
import unittest
from pathlib import Path

from config import SIGNATURES_DIR
from db.backup_engine import BackupEngine


class TestBackupSignatures(unittest.TestCase):

    def setUp(self):
        SIGNATURES_DIR.mkdir(parents=True, exist_ok=True)
        self.marker = SIGNATURES_DIR / "roundtrip_marker.bin"
        self.extra = SIGNATURES_DIR / "test_marker_asset.json"
        self.marker.write_bytes(b"ORIGINAL-BYTES")
        self.extra.write_text('{"marker": true}', encoding="utf-8")

    def tearDown(self):
        self.marker.unlink(missing_ok=True)
        self.extra.unlink(missing_ok=True)

    def test_backup_captures_signature_assets(self):
        """create_backup must archive everything in data/signatures/ and list it in the manifest."""
        res = BackupEngine.create_backup(note="signatures capture test")
        self.assertTrue(res["success"])
        bdir = Path(res["path"])
        sig = bdir / "signatures"
        self.assertTrue(sig.is_dir(), "Archive must contain a signatures/ folder")
        self.assertTrue((sig / "roundtrip_marker.bin").exists())
        self.assertTrue((sig / "test_marker_asset.json").exists())
        self.assertTrue((sig / "pi_signature.png").exists(),
                        "The real PI signature asset must be archived")
        manifest = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("roundtrip_marker.bin", manifest.get("signatures_files", []))

    def test_restore_round_trip_restores_signature_assets(self):
        """A restore must bring signature assets back byte-for-byte."""
        res = BackupEngine.create_backup(note="signatures roundtrip test")
        bdir = Path(res["path"])
        self.marker.write_bytes(b"CORRUPTED-STATE")
        self.extra.unlink()
        restore_res = BackupEngine.restore_backup(bdir)
        self.assertTrue(restore_res.get("success", True))
        self.assertEqual(self.marker.read_bytes(), b"ORIGINAL-BYTES",
                         "Restore must recover the exact signature asset bytes")
        self.assertTrue(self.extra.exists())
        self.assertIn("roundtrip_marker.bin", restore_res.get("restored_signature_files", []))

    def test_restore_tolerates_archives_without_signatures(self):
        """Old archives (CSV-only) must restore fine — signatures skipped, not fatal."""
        res = BackupEngine.create_backup(note="legacy archive without signatures")
        bdir = Path(res["path"])
        shutil.rmtree(bdir / "signatures")  # simulate a pre-signatures archive
        restore_res = BackupEngine.restore_backup(bdir)
        self.assertTrue(restore_res.get("success", True))
        self.assertEqual(restore_res.get("restored_signature_files", []), [])
        self.assertEqual(self.marker.read_bytes(), b"ORIGINAL-BYTES",
                         "Legacy restores must leave current signature assets untouched")


if __name__ == "__main__":
    unittest.main()
