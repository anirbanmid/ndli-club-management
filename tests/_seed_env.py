"""
Test-environment seed credentials -- import BEFORE config.

WHY: config.py derives every seed password from environment variables (no
repo-visible literals). The test database's stored hashes match these
historical seed values, and several tests authenticate with them explicitly,
so the TEST environment pins them here.

This module must run before anything imports config. Every test module starts
with `import _seed_env` to guarantee that in EVERY discovery mode -- flat
`python3 -m unittest discover -s tests` does NOT execute tests/__init__.py.
Production code never imports this module; values here are test-only.
"""
import os

os.environ["NDLI_TESTING"] = "true"
os.environ.setdefault("NDLI_ADMIN_PASSWORD", "Seed#Admin-Rotated2026")
os.environ.setdefault("NDLI_EMP01_PASSWORD", "Seed#EMP01-Rotated2026")
os.environ.setdefault("NDLI_EMP02_PASSWORD", "Seed#EMP02-Rotated2026")
os.environ.setdefault("NDLI_EMP03_PASSWORD", "Seed#EMP03-Rotated2026")
os.environ.setdefault("NDLI_EMP04_PASSWORD", "Seed#EMP04-Rotated2026")
os.environ.setdefault("NDLI_EMP05_PASSWORD", "Seed#EMP05-Rotated2026")
os.environ.setdefault("NDLI_EMP06_PASSWORD", "Seed#EMP06-Rotated2026")
os.environ.setdefault("NDLI_EMP07_PASSWORD", "Seed#EMP07-Rotated2026")

os.environ.setdefault("NDLI_QR_SIGNING_KEY", "test-qr-key-not-for-production-use")
