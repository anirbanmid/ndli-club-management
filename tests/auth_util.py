"""
Shared HTTP authentication helper for the test suite.

Since the API now enforces session auth on data/admin endpoints (security
hardening, 2026-09-23), test helpers auto-attach a Master Admin token unless
an explicit token is provided. Tests that exercise authz semantics pass their
own tokens explicitly and are unaffected.
"""
import json
import threading
import urllib.request

from config import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, INITIAL_EMPLOYEES

_TOKEN_CACHE = {}
_CACHE_LOCK = threading.Lock()


def admin_token(base_url: str, scope: str = "default") -> str:
    """Logs in the seeded Master Admin once per (server, caller) and caches the token."""
    key = (base_url, scope)
    with _CACHE_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached:
            return cached
        payload = json.dumps({
            "email": DEFAULT_ADMIN_EMAIL,
            "password": DEFAULT_ADMIN_PASSWORD
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        token = data["session"]["token"]
        _TOKEN_CACHE[key] = token
        return token


def employee_token(base_url: str, scope: str = "default", emp_id: str = "EMP01") -> str:
    """Logs in a seeded employee once per (server, caller, emp) and caches the token."""
    key = (base_url, scope, emp_id)
    with _CACHE_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached:
            return cached
        emp = next(e for e in INITIAL_EMPLOYEES if e["id"] == emp_id)
        # Python's login handler reads email/user_id/identifier (not "id").
        payload = json.dumps({"email": emp_id, "password": emp["password"]}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        token = data["session"]["token"]
        _TOKEN_CACHE[key] = token
        return token
