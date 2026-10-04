"""
Backup/restore coverage for digital signature assets (data/signatures/).

The backup engine is CSV-oriented; signature assets (pi_signature.png,
settings.json) need explicit handling or a disaster restore silently loses
the PI signature used by the certificate engine.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import json
import shutil
import unittest
from pathlib import Path

from config import SIGNATURES_DIR
from db.backup_engine import BackupEngine


class TestGasRestoreBinarySafety(unittest.TestCase):
    """Source guard (2026-10-04, bug found by Claude): the GAS-side restore path
    in deployment_gas/Code.gs must never round-trip signature IMAGES through
    UTF-8 text (getDataAsString + PLAIN_TEXT) -- that corrupts PNG/JPEG bytes.
    It must restore the raw blob, the same way the backup side archives it."""

    @staticmethod
    def _signatures_branch():
        src = (Path(__file__).resolve().parent.parent / "deployment_gas" / "Code.gs").read_text(
            encoding="utf-8")
        start = src.index('entryPath.indexOf("signatures/")')
        end = src.index("restoredFilesCount++", start)
        branch = src[start:end]
        # Strip // comments: a comment may DESCRIBE the old bug without using it.
        return "\n".join(line.split("//", 1)[0] for line in branch.splitlines())

    def test_signature_restore_is_binary_safe(self):
        branch = self._signatures_branch()
        self.assertIn("setBlob(", branch, "existing signature files must be replaced via setBlob")
        self.assertIn("createFile(sigBlob)", branch, "new signature files must be created from the raw blob")
        self.assertNotIn("getDataAsString", branch,
                         "signature images must never pass through UTF-8 text")
        self.assertNotIn("PLAIN_TEXT", branch,
                         "signature images must never be written as plain text")

    def test_backup_side_archives_raw_blobs(self):
        src = (Path(__file__).resolve().parent.parent / "deployment_gas" / "Code.gs").read_text(
            encoding="utf-8")
        start = src.index("Gather Digital Signature Assets")
        end = src.index("blobs.push(sb)", start)
        self.assertIn("sf.getBlob()", src[start:end],
                      "the backup side must archive the raw blob (unchanged)")


class TestBackupSignatures(unittest.TestCase):

    def setUp(self):
        SIGNATURES_DIR.mkdir(parents=True, exist_ok=True)
        self.marker = SIGNATURES_DIR / "roundtrip_marker.bin"
        self.extra = SIGNATURES_DIR / "test_marker_asset.json"
        self.marker.write_bytes(b"ORIGINAL-BYTES")
        self.extra.write_text('{"marker": true}', encoding="utf-8")
        # pi_signature.png is RUNTIME data (gitignored -- never shipped in git).
        # On a fresh clone the asset does not exist yet, so provision a
        # placeholder to keep the "signature assets get archived" invariant
        # testable everywhere. Deployments with the real asset are untouched.
        self.pisig = SIGNATURES_DIR / "pi_signature.png"
        self._made_pisig = False
        if not self.pisig.exists():
            self.pisig.write_bytes(b"\x89PNG\r\n\x1a\ntest-placeholder-not-a-real-signature")
            self._made_pisig = True

    def tearDown(self):
        self.marker.unlink(missing_ok=True)
        self.extra.unlink(missing_ok=True)
        if getattr(self, "_made_pisig", False):
            self.pisig.unlink(missing_ok=True)

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
                        "The PI signature asset must be archived")
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
