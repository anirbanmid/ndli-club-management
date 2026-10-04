"""
Source guard: production code must never contain credential literals.

Precedent: tests/test_backup_signatures.py. Seed passwords live ONLY in
tests/_seed_env.py (test environment) and in data/.seed_credentials.json on a
fresh deployment (generated, chmod 600, gitignored).
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_GLOBS = ["*.py", "db/*.py", "ai/*.py"]
FORBIDDEN_PATTERNS = [
    ("Seed#", "seed credential literal"),
    ("ndli_kgp_secret_key", "hardcoded SECRET_KEY fallback"),
]


def _prod_python_files():
    files = set()
    for g in PROD_GLOBS:
        for f in ROOT.glob(g):
            if f.is_file() and "__pycache__" not in str(f):
                files.add(f)
    return sorted(files)


class TestNoPlaintextSecrets(unittest.TestCase):

    def test_prod_code_has_no_credential_literals(self):
        offenders = []
        for f in _prod_python_files():
            text = f.read_text()
            for needle, label in FORBIDDEN_PATTERNS:
                if needle in text:
                    offenders.append(f"{f.relative_to(ROOT)}: {label}")
        self.assertEqual(offenders, [], "credential literals in production code: %r" % offenders)

    def test_config_has_no_secret_key(self):
        import config
        self.assertFalse(hasattr(config, "SECRET_KEY"),
                         "config.py must not define SECRET_KEY (dead code + QR forgeability risk)")

    def test_seed_passwords_resolve_from_env(self):
        import config
        self.assertTrue(config.DEFAULT_ADMIN_PASSWORD)
        self.assertEqual(config.DEFAULT_ADMIN_PASSWORD,
                         os.environ.get("NDLI_ADMIN_PASSWORD"))
        for i, emp in enumerate(config.INITIAL_EMPLOYEES, start=1):
            self.assertTrue(emp["password"], "seed password must resolve")
            self.assertEqual(emp["password"],
                             os.environ.get("NDLI_EMP%02d_PASSWORD" % i))

    def test_seed_credentials_file_is_gitignored(self):
        gitignore = (ROOT / ".gitignore").read_text()
        self.assertIn("data/.seed_credentials.json", gitignore)
        self.assertIn("data/.qr_signing_key", gitignore)

    def test_qr_module_has_no_fallback_key(self):
        src = (ROOT / "qr_tokens.py").read_text()
        self.assertNotIn("Seed#", src)
        # The key must come from env or the generated file -- never a literal.
        self.assertIn("NDLI_QR_SIGNING_KEY", src)
        self.assertIn(".qr_signing_key", src)


if __name__ == "__main__":
    unittest.main()
