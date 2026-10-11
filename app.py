"""
NDLI Club Management and Employee Activity Tracking System
Core Web Application Server (Zero-Dependency Python Standard Library HTTP Server)
Supports full REST API, Sessions, Authentication, State-Zone Mapping, and Drive Sync.
"""
import os
import json
import hashlib
import base64
import urllib.parse
import re
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from config import (
    SERVER_HOST,
    SERVER_PORT,
    BASE_DIR,
    DATA_DIR,
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_QUOTAS_CSV,
    MASTER_USERS_CSV,
    MASTER_ISSUES_CSV,
    SUPPORT_TYPES,
    DEFAULT_ADMIN_EMAIL,
    EMPLOYEE_NODES_DIR,
    BACKUP_DIR
)
from db.schemas import (
    CLUB_FIELDS,
    ACTIVITY_FIELDS,
    QUOTA_FIELDS,
    USER_FIELDS,
    ISSUE_FIELDS,
    validate_club_payload,
    validate_historical_dates,
    normalize_date_fields,
    REG_NO_PATTERN
)
from db.csv_engine import CSVEngine
from db.sync_engine import SyncEngine, parse_iso_or_date, calculate_next_renewal_date

# Handover PIN verification: SHA-256 digest ONLY — the 6-digit owner-only PIN
# itself is NEVER stored in this repository (the digest is a one-way
# fingerprint, so reading the source cannot reveal the digits). Tests
# monkeypatch this constant with a test-only digest.
HANDOVER_PIN_SHA256 = "b2f528d83314a6d2a93027e75a428828db4916c06bc3442df4f68cd739715532"

# ---- R35: PPT TRAINING LIBRARY (2 slots sharing ONE 15 MB budget) ----
# Slot metadata lives in data/training/meta.json; the decks themselves are
# slot1.<ext> / slot2.<ext>. Uploads travel base64-in-JSON (same convention as
# the PI signature upload). Nothing here is public: listing/downloading needs
# any authenticated session, uploading/deleting needs the Master Admin.

TRAINING_MAX_TOTAL_BYTES = 15 * 1024 * 1024  # "15MB TOTAL" (user spec 2026-10-11)
TRAINING_EXTS = (".ppt", ".pptx", ".ppsx")
TRAINING_DIR = DATA_DIR / "training"
TRAINING_META = DATA_DIR / "training" / "meta.json"
TRAINING_SLOTS = ("1", "2")
TRAINING_CONTENT_TYPES = {
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
}


def training_meta_load() -> Dict[str, Any]:
    try:
        if TRAINING_META.exists():
            data = json.loads(TRAINING_META.read_text(encoding="utf-8"))
            slots = data.get("slots", data)
            return {str(k): v for k, v in slots.items() if str(k) in TRAINING_SLOTS}
    except Exception:
        pass
    return {}


def training_meta_save(slots: Dict[str, Any]) -> None:
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_META.write_text(json.dumps({"slots": slots}, indent=2), encoding="utf-8")


def training_slot_file(slot: str) -> Optional[Path]:
    if not TRAINING_DIR.exists():
        return None
    for f in TRAINING_DIR.glob(f"slot{slot}.*"):
        if f.is_file():
            return f
    return None

from db.migration_engine import (
    baselines_for as migration_baselines_for,
    validate_employee_history as migration_validate_history,
    commit_employee_history as migration_commit_history,
    history_grand_totals as migration_grand_totals,
    history_period_years as migration_period_years,
    history_summary as migration_history_summary,
)
from db import counting_rules
from db.storage_adapter import get_storage_adapter
from db.backup_engine import BackupEngine
from db.issue_manager import IssueManager
from auth import AuthService
from state_zone_mapper import (
    get_zone_for_state,
    get_all_states,
    get_all_zones,
    ZONE_STATE_MAP
)
from ai.decision_module import AIDecisionEngine
from ai.assistant_core import ask_assistant, log_assistant_issue, nudges_for, record_feedback
from ai.assistant_tools import ToolAuthError, build_context, call_tool
from ai import assistant_learning
from ai import assistant_guard
from ai import assistant_audit


def assistant_rate_gate(session, action):
    """
    Slice G rate gate for /api/assistant/*: (ctx, allowed, retry_after_seconds).
    Rejections are audited LOUDLY by the callers -- never a silent drop.
    """
    try:
        ctx = build_context(session)
    except ToolAuthError:
        return None, False, 60
    allowed, retry_after = assistant_guard.check_rate(ctx, action)
    return ctx, allowed, retry_after


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """High-concurrency multi-threaded HTTP server engineered for 200+ simultaneous real-time requests."""
    daemon_threads = True
    request_queue_size = 512
    allow_reuse_address = True


class NDLIRequestHandler(BaseHTTPRequestHandler):
    """Custom HTTP Request Handler with REST routing, JSON parsing, and CORS support."""

    def _set_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, x-session-token")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()

    def _serve_file(self, file_path: Path, content_type: str = "text/html; charset=utf-8", extra_root: Optional[Path] = None):
        """Serves a static or template file with correct MIME type, caching headers, and directory traversal immunity."""
        try:
            resolved = file_path.resolve()
            # Only web-servable roots. The database directories (data/, DATA_DIR)
            # are deliberately NOT roots here -- database files must only travel
            # through authenticated API endpoints. `extra_root` allows narrowly
            # scoped exceptions (e.g. the signatures folder).
            allowed_roots = [
                (BASE_DIR / "static").resolve(),
                (BASE_DIR / "docs").resolve(),
                (BASE_DIR / "templates").resolve(),
            ]
            if extra_root is not None:
                allowed_roots.append(Path(extra_root).resolve())
            if not any(resolved == r or r in resolved.parents for r in allowed_roots):
                self._send_error("Access denied: Invalid resource path.", status=403)
                return
        except Exception:
            self._send_error("Invalid file path specification.", status=400)
            return

        if not file_path.exists():
            self._send_error(f"File not found: {file_path.name}", status=404)
            return
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            if "/static/" in str(file_path).replace("\\", "/"):
                self.send_header("Cache-Control", "public, max-age=3600")
            else:
                self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_error(f"Error serving file: {str(e)}", status=500)

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests."""
        self._set_headers(HTTPStatus.NO_CONTENT)

    def log_message(self, fmt, *args):
        """Access log with query strings redacted so tokens never reach server logs."""
        try:
            path_only = str(self.path).split("?", 1)[0]
            print(f"[{self.log_date_time_string()}] {self.command} {path_only}")
        except Exception:
            pass

    def _send_json(self, data: Any, status: int = 200):
        self._set_headers(status, "application/json; charset=utf-8")
        payload = json.dumps(data, indent=2, default=str)
        self.wfile.write(payload.encode("utf-8"))

    def _send_error(self, message: str, status: int = 400):
        self._send_json({"success": False, "error": True, "message": message}, status=status)

    def _parse_json_body(self) -> Dict[str, Any]:
        """Parses incoming JSON body safely with memory protection and encoding fallback."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                return {}
            if content_length > 50 * 1024 * 1024:
                return {}
            raw_body = self.rfile.read(content_length).decode("utf-8", errors="replace")
            return json.loads(raw_body)
        except Exception:
            return {}

    def _get_auth_session(self) -> Optional[Dict[str, Any]]:
        """Extracts and validates Bearer token from Authorization header."""
        auth_header = self.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif "x-session-token" in self.headers:
            token = self.headers.get("x-session-token", "").strip()

        if not token:
            return None
        return AuthService.validate_session(token)

    def _check_admin_access(self) -> bool:
        """
        Validates Admin role for protected administrative endpoints.
        Strictly requires an authenticated Admin role (admin@iitkgp.ac.in or role == 'ADMIN').
        Rejects unauthenticated requests (401) and non-admin employee accounts (403).
        """
        auth_header = self.headers.get("Authorization", "")
        token_hdr = self.headers.get("x-session-token", "")
        if not auth_header and not token_hdr:
            self._send_error("Admin authorization required. Please provide a valid admin session token.", status=401)
            return False

        session = self._get_auth_session()
        if not session:
            self._send_error("Invalid or expired session token. Admin authorization required.", status=401)
            return False

        if session.get("role") != "ADMIN" and session.get("email") != DEFAULT_ADMIN_EMAIL:
            self._send_error("Access denied. Administrator privileges required. Employees cannot access employee management.", status=403)
            return False

        return True

    def _require_session(self) -> Optional[Dict[str, Any]]:
        """Returns the authenticated session, or sends 401 and returns None."""
        session = self._get_auth_session()
        if not session:
            self._send_error("Authentication required. Please log in.", status=401)
            return None
        return session

    def _require_self_or_admin(self, emp_id: str) -> Optional[Dict[str, Any]]:
        """
        Identity gate for employee-scoped operations: the authenticated session
        must belong to the same employee, or the caller must be an Admin.
        Sends 401/403 and returns None on failure.
        """
        session = self._require_session()
        if not session:
            return None
        if session.get("role") == "ADMIN":
            return session
        if str(session.get("user_id", "")).strip().upper() == str(emp_id or "").strip().upper():
            return session
        self._send_error("Access denied: you may only operate on your own employee records.", status=403)
        return None

    def _is_employee_active(self, emp_id: str) -> bool:
        """Checks if the employee ID exists and has active status (is_active == '1'). O(1) indexed lookup."""
        if not emp_id:
            return False
        clean_id = emp_id.strip().upper()
        u = CSVEngine.find_by_key(MASTER_USERS_CSV, "id", clean_id, USER_FIELDS, copy=False)
        if u:
            return str(u.get("is_active", "1")).strip() == "1"
        return False

    def _send_health_status(self):
        """Sends the system health and REST API endpoints status payload."""
        storage_info = get_storage_adapter().get_info()
        self._send_json({
            "system": "NDLI Club Management and Employee Activity Tracking System",
            "organization": "IIT Kharagpur",
            "developer": "Dr. Anirban Mukherjee",
            "status": "online",
            "version": "1.0.0 (Phase 1 Foundational Architecture)",
            "storage": storage_info,
            "endpoints": [
                "POST /api/auth/login",
                "GET  /api/auth/me",
                "POST /api/auth/logout",
                "GET  /api/state-zone/map",
                "GET  /api/states",
                "GET  /api/states-zones",
                "GET  /api/state-zone/lookup?state=<name>",
                "GET  /api/clubs/search?q=<query>",
                "POST /api/clubs/create",
                "POST /api/clubs/bulk-import/validate",
                "POST /api/clubs/bulk-import/commit",
                "POST /api/admin/migration/history/validate",
                "POST /api/admin/migration/history/commit",
                "POST /api/admin/migration/clubs/validate",
                "POST /api/admin/migration/clubs/commit",
                "POST /api/clubs/update",
                "POST /api/clubs/correct-dates",
                "POST /api/clubs/renew",
                "POST /api/activity/log",
                "GET  /api/activity/list",
                "GET  /api/admin/metrics",
                "GET  /api/admin/employee-performance",
                "GET  /api/admin/renewal-attention",
                "GET  /api/admin/ai-insights",
                "GET  /api/admin/employees",
                "POST /api/admin/employees/create",
                "POST /api/admin/employees/update",
                "POST /api/admin/employees/status",
                "GET  /api/employees/roster",
                "GET  /api/employees/profile?id=<emp_id>",
                "GET  /manual",
                "GET  /manual.pdf",
                "GET  /api/download/user-manual",
                "GET  /api/download/promo-video",
                "GET  /promo-video",
                "GET  /api/admin/download/master-clubs",
                "GET  /api/admin/backup/status",
                "POST /api/admin/backup/trigger",
                "GET  /api/employee/download/activity-log",
                "GET  /api/employee/download/clubs-log",
                "POST /api/issues/create",
                "POST /api/issues/resolve",
                "GET  /api/issues/employee-reminders",
                "GET  /api/issues/admin-reminders",
                "GET  /api/issues/list",
                "POST /api/sync/reconcile",
                "POST /api/assistant/ask",
                "POST /api/assistant/feedback",
                "GET /api/assistant/nudges"
            ]
        })

    def do_GET(self):
        """Routing for GET requests with emergency crash recovery boundary."""
        try:
            self._handle_do_GET()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_error(f"Internal server error: {str(exc)}", status=500)

    def _handle_do_GET(self):
        """Routing for GET requests - table-driven, see routes/__init__.py."""
        routes.handle_get(self)

    def do_POST(self):
        """Routing for POST requests with emergency crash recovery boundary."""
        try:
            self._handle_do_POST()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_error(f"Internal server error: {str(exc)}", status=500)

    def _handle_do_POST(self):
        """Routing for POST requests - table-driven, see routes/__init__.py."""
        routes.handle_post(self)

def init_system() -> Dict[str, Any]:
    """
    Guarantees seamless non-destructive startup initialization and cold-boot restoration:
    1. Detects persistent disk mount (e.g. /var/data on Render) and bootstraps from repo data if empty.
    2. Remote Google Drive Pull: Checks for remote cloud snapshot from Google Drive and synchronizes
       new clubs, activities, and quotas non-destructively so that dyno restarts and cold boots never wipe data.
    3. Backup Snapshot Auto-Restore: If local database files are missing or empty, restores latest backup snapshot.
    4. Executes non-destructive initialize_database(force=False).
    5. Runs SyncEngine.reconcile_all_nodes() to heal indexes and synchronize master and node databases.
    6. Starts BackupEngine automated scheduler.
    """
    import shutil
    from init_db import initialize_database

    # 1. Bootstrap persistent storage if DATA_DIR is outside BASE_DIR/data and empty
    base_data = (BASE_DIR / "data").resolve()
    if DATA_DIR.resolve() != base_data and base_data.exists():
        if not (DATA_DIR / "master" / "master_clubs.csv").exists():
            try:
                for item in base_data.iterdir():
                    dest = DATA_DIR / item.name
                    if not dest.exists():
                        if item.is_dir():
                            shutil.copytree(str(item), str(dest))
                        else:
                            shutil.copy2(str(item), str(dest))
            except Exception as e:
                print(f"[!] Warning: Failed to bootstrap persistent disk from {base_data}: {e}")
        # Ensure signatures exist in DATA_DIR
        base_sig = base_data / "signatures"
        data_sig = DATA_DIR / "signatures"
        if base_sig.exists() and not (data_sig / "pi_signature.png").exists() and (base_sig / "pi_signature.png").exists():
            try:
                data_sig.mkdir(parents=True, exist_ok=True)
                for sf in base_sig.iterdir():
                    dest_sf = data_sig / sf.name
                    if not dest_sf.exists():
                        shutil.copy2(str(sf), str(dest_sf))
            except Exception as se:
                print(f"[!] Warning: Failed to bootstrap signatures: {se}")

    # 2. Synchronize remote cloud state from Google Drive (Cold boot & restart recovery)
    pulled_from_drive = False
    adapter = get_storage_adapter()
    if hasattr(adapter, "pull_all_from_drive"):
        try:
            drive_res = adapter.pull_all_from_drive()
            if drive_res.get("success") and drive_res.get("total_pulled", 0) > 0:
                pulled_from_drive = True
                print(f"[*] Cloud Sync: Successfully synchronized {drive_res.get('total_pulled')} database files from Google Drive.")
        except Exception as de:
            print(f"[!] Warning: Failed to pull from Google Drive on startup: {de}")

    # 3. Check if local data is missing or cold boot has occurred
    is_missing = (
        not MASTER_CLUBS_CSV.exists()
        or MASTER_CLUBS_CSV.stat().st_size == 0
        or len(CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)) == 0
    )

    restored_from_backup = False
    if is_missing:
        existing_backups = BackupEngine.get_existing_backups()
        if existing_backups:
            try:
                print(f"[*] Cold boot recovery: Restoring latest backup {existing_backups[0].name}...")
                BackupEngine.restore_backup(existing_backups[0])
                restored_from_backup = True
                is_missing = False
            except Exception as be:
                print(f"[!] Warning: Failed to restore backup on cold boot: {be}")

    # 4. Idempotent non-destructive database initialization
    initialize_database(force=False)

    # 5. Full reconciliation to heal indexes and verify all clubs and activities
    summary = SyncEngine.reconcile_all_nodes()

    # 6. Start automated backup scheduler
    try:
        BackupEngine.start_scheduler()
    except Exception as e:
        print(f"[!] Warning: Could not start backup scheduler: {e}")

    return {
        "status": "ready",
        "restored_from_backup": restored_from_backup,
        "pulled_from_drive": pulled_from_drive,
        "reconciliation": summary
    }


def run_server(host: str = SERVER_HOST, port: int = SERVER_PORT):
    """Starts the NDLI HTTP server with multi-threaded high-concurrency architecture."""
    # Ensure safe startup initialization and cold-boot recovery
    try:
        init_system()
    except Exception as e:
        print(f"[!] Warning: System initialization encountered an error: {e}")

    server_address = (host, port)
    httpd = ThreadedHTTPServer(server_address, NDLIRequestHandler)
    print(f"[*] NDLI Club Management Server listening on http://{host}:{port} (Multi-threaded, request_queue_size=512)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server stopping...")
        httpd.server_close()


# The router lives in routes/. Imported HERE on purpose: the route modules take
# their shared names from this module (`from app import ...`), so this import
# must run once the names above exist. Plain `import` (not `from ... import`)
# keeps both import orders safe.
import routes  # noqa: E402

if __name__ == "__main__":
    run_server()

