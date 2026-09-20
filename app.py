"""
NDLI Club Management and Employee Activity Tracking System
Core Web Application Server (Zero-Dependency Python Standard Library HTTP Server)
Supports full REST API, Sessions, Authentication, State-Zone Mapping, and Drive Sync.
"""
import os
import json
import base64
import urllib.parse
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
    validate_club_payload
)
from db.csv_engine import CSVEngine
from db.sync_engine import SyncEngine, parse_iso_or_date, calculate_next_renewal_date
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, x-session-token")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()

    def _serve_file(self, file_path: Path, content_type: str = "text/html; charset=utf-8"):
        """Serves a static or template file with correct MIME type, caching headers, and directory traversal immunity."""
        try:
            resolved = file_path.resolve()
            allowed_roots = [
                (BASE_DIR / "static").resolve(),
                (BASE_DIR / "docs").resolve(),
                (BASE_DIR / "templates").resolve(),
                (BASE_DIR / "data").resolve(),
                DATA_DIR.resolve()
            ]
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
            self.send_header("Access-Control-Allow-Origin", "*")
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
            try:
                parsed_q = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed_q.query)
                token = qs.get("token", [""])[0].strip()
            except Exception:
                pass

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
                "POST /api/clubs/update",
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
                "POST /api/sync/reconcile"
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
        """Routing for GET requests."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Static assets serving (static/ and docs/)
        if path.startswith("/static/") or path.startswith("/docs/"):
            rel_path = path.lstrip("/")
            file_path = BASE_DIR / rel_path
            content_type = "application/octet-stream"
            if path.endswith(".css"):
                content_type = "text/css; charset=utf-8"
            elif path.endswith(".js"):
                content_type = "application/javascript; charset=utf-8"
            elif path.endswith(".html"):
                content_type = "text/html; charset=utf-8"
            elif path.endswith(".svg"):
                content_type = "image/svg+xml"
            elif path.endswith(".png"):
                content_type = "image/png"
            elif path.endswith(".jpg") or path.endswith(".jpeg"):
                content_type = "image/jpeg"
            elif path.endswith(".json"):
                content_type = "application/json; charset=utf-8"
            elif path.endswith(".pdf"):
                content_type = "application/pdf"
            self._serve_file(file_path, content_type)
            return

        # HTML Portal Routes
        if path in ["/portal", "/index.html"]:
            self._serve_file(BASE_DIR / "templates" / "index.html")
            return

        if path == "/":
            accept_header = self.headers.get("Accept", "")
            user_agent = self.headers.get("User-Agent", "")
            is_json_requested = (
                "application/json" in accept_header
                or query_params.get("format") == ["json"]
                or query_params.get("api") == ["1"]
                or (user_agent.startswith("Python-urllib") and "text/html" not in accept_header)
            )
            if is_json_requested:
                self._send_health_status()
                return

            self._serve_file(BASE_DIR / "templates" / "index.html")
            return

        if path in ["/manual", "/user-manual", "/documentation", "/user_manual", "/manual/view"]:
            self._serve_file(BASE_DIR / "docs" / "user_manual.html", "text/html; charset=utf-8")
            return

        if path == "/admin":
            self._serve_file(BASE_DIR / "templates" / "admin.html")
            return

        if path in ["/login", "/employee/login"]:
            self._serve_file(BASE_DIR / "templates" / "employee.html")
            return

        if path == "/employee" or path.startswith("/employee/"):
            self._serve_file(BASE_DIR / "templates" / "employee.html")
            return

        # Health / Root endpoint
        if path == "/api/health":
            self._send_health_status()
            return

        # State and Zone Mapping (Dual support for /api/state-zone/map, /api/states, /api/states-zones)
        if path in ("/api/state-zone/map", "/api/states", "/api/states-zones"):
            all_st = get_all_states()
            self._send_json({
                "success": True,
                "zones": get_all_zones(),
                "zone_to_states": ZONE_STATE_MAP,
                "map": ZONE_STATE_MAP,
                "all_states": all_st,
                "states": all_st,
                "support_types": SUPPORT_TYPES,
                "total": len(all_st)
            })
            return

        if path == "/api/state-zone/lookup":
            state_param = query_params.get("state", [""])[0]
            zone = get_zone_for_state(state_param)
            self._send_json({
                "state": state_param,
                "zone": zone or "Unknown",
                "found": zone is not None
            })
            return

        # Current User Session (Dynamically Synced with Master DB)
        if path == "/api/auth/me":
            session = self._get_auth_session()
            if not session:
                self._send_error("Unauthorized. Please log in.", status=401)
                return

            # Live sync with master_users.csv
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            found_user = None
            for u in users:
                if u.get("id", "").strip().upper() == session.get("user_id", "").strip().upper():
                    found_user = u
                    break

            auth_token = session.get("token", "")
            if not auth_token:
                auth_hdr = self.headers.get("Authorization", "")
                if auth_hdr.startswith("Bearer "):
                    auth_token = auth_hdr.split(" ", 1)[1].strip()

            if not found_user:
                if auth_token:
                    AuthService.logout(auth_token)
                self._send_error("User account no longer exists.", status=401)
                return

            if str(found_user.get("is_active", "1")).strip() != "1":
                if auth_token:
                    AuthService.logout(auth_token)
                self._send_error("This account has been disabled or blocked by the Administrator.", status=401)
                return

            session["full_name"] = found_user.get("full_name", "")
            session["email"] = found_user.get("email", "")
            session["zone"] = found_user.get("zone", "")
            session["assigned_states"] = found_user.get("assigned_states", "")
            session["role"] = found_user.get("role", "EMPLOYEE")

            self._send_json({"authenticated": True, "user": session})
            return

        # Public / Regional Directory of Active Employees (No Passwords or Hashes)
        if path == "/api/employees/roster":
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            roster = []
            for u in users:
                if u.get("role") == "EMPLOYEE":
                    roster.append({
                        "id": u.get("id"),
                        "full_name": u.get("full_name"),
                        "email": u.get("email"),
                        "zone": u.get("zone"),
                        "assigned_states": u.get("assigned_states"),
                        "is_active": str(u.get("is_active", "1"))
                    })
            self._send_json({"count": len(roster), "employees": roster})
            return

        # Individual Employee Live Profile (Dynamic Node & Master Sync)
        if path == "/api/employees/profile":
            emp_id = query_params.get("id", [""])[0] or query_params.get("emp_id", [""])[0]
            clean_id = emp_id.strip().upper()
            if not clean_id:
                self._send_error("emp_id or id parameter is required.")
                return

            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            target = None
            for u in users:
                if u.get("id", "").strip().upper() == clean_id:
                    target = u
                    break

            if not target:
                self._send_error(f"Employee with ID '{clean_id}' not found.", status=404)
                return

            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            q = next((item for item in quotas if item.get("emp_id", "").strip().upper() == clean_id), {})

            # Dynamic node & master verification & healing for accurate live quota
            approved_club_ids = set()
            node_clubs_path = SyncEngine.get_employee_clubs_path(clean_id)
            if node_clubs_path.exists():
                for c in CSVEngine.read_all(node_clubs_path, CLUB_FIELDS):
                    cid = c.get("club_id", "").strip().upper()
                    if cid and (not c.get("approved_by_emp_id") or c.get("approved_by_emp_id", "").strip().upper() == clean_id):
                        approved_club_ids.add(cid)

            for c in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS):
                if c.get("approved_by_emp_id", "").strip().upper() == clean_id:
                    cid = c.get("club_id", "").strip().upper()
                    if cid:
                        approved_club_ids.add(cid)

            node_act_path = SyncEngine.get_employee_activities_path(clean_id)
            node_acts = CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS) if node_act_path.exists() else []
            master_acts = [a for a in CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS) if a.get("emp_id", "").strip().upper() == clean_id]
            combined_acts = {a.get("activity_id", "").strip(): a for a in (node_acts + master_acts) if a.get("activity_id")}.values()

            club_approval_acts = 0
            standalone_approvals = 0
            support_logs = 0
            latest_ts = q.get("last_activity_timestamp", "")

            for a in combined_acts:
                ts = a.get("timestamp", "")
                if ts and ts > latest_ts:
                    latest_ts = ts
                stype = a.get("support_type", "").strip()
                aid = a.get("activity_id", "").strip()
                if stype == "Club Approval" or a.get("priority_flag") == "1" or aid.startswith(f"ACT-PRIORITY-{clean_id}"):
                    club_approval_acts += 1
                    if a.get("club_id"):
                        approved_club_ids.add(a.get("club_id").strip().upper())
                    else:
                        standalone_approvals += 1
                else:
                    support_logs += 1

            stored_clubs = int(q.get("clubs_approved_count", "0") or "0")
            computed_clubs = max(len(approved_club_ids) + standalone_approvals, club_approval_acts)
            final_clubs = max(stored_clubs, computed_clubs)

            stored_support = int(q.get("support_logs_count", "0") or "0")
            final_support = max(stored_support, support_logs)

            if not q or final_clubs != stored_clubs or final_support != stored_support:
                q = {
                    "emp_id": clean_id,
                    "employee_name": target.get("full_name") or clean_id,
                    "zone": target.get("zone", ""),
                    "clubs_approved_count": str(final_clubs),
                    "support_logs_count": str(final_support),
                    "last_activity_timestamp": latest_ts or target.get("created_at", "")
                }
                CSVEngine.upsert_row(MASTER_QUOTAS_CSV, QUOTA_FIELDS, "emp_id", q)

            self._send_json({
                "found": True,
                "employee": {
                    "id": target.get("id"),
                    "full_name": target.get("full_name"),
                    "email": target.get("email"),
                    "zone": target.get("zone"),
                    "assigned_states": target.get("assigned_states"),
                    "is_active": str(target.get("is_active", "1")),
                    "created_at": target.get("created_at"),
                    "clubs_approved_count": final_clubs,
                    "support_logs_count": final_support,
                    "last_activity_timestamp": q.get("last_activity_timestamp", "")
                }
            })
            return

        # Universal Search for Clubs
        if path == "/api/clubs/search":
            query = query_params.get("q", [""])[0]
            emp_id = query_params.get("emp_id", [""])[0]
            limit_param = query_params.get("limit", [""])[0]
            limit = int(limit_param) if limit_param.isdigit() else (5000 if not query else None)

            # If emp_id specified, search that node first or fall back to master
            if emp_id:
                node_clubs_path = SyncEngine.get_employee_clubs_path(emp_id)
                results = CSVEngine.search(node_clubs_path, query, limit=limit) if node_clubs_path.exists() else []
            else:
                results = CSVEngine.search(MASTER_CLUBS_CSV, query, limit=limit)

            normalized_results = []
            for r in results:
                r_copy = dict(r)
                doa = r_copy.get("date_of_approval", "").strip() or r_copy.get("submission_timestamp", "").strip()
                r_copy["date_of_approval"] = doa
                r_copy["submission_timestamp"] = doa
                lrd = r_copy.get("last_renewal_date", "").strip()
                r_copy["last_renewal_date"] = lrd
                ren = r_copy.get("renewal_date", "").strip() or r_copy.get("next_renewal_date", "").strip()
                if not ren:
                    if lrd:
                        ren = calculate_next_renewal_date(last_renewal_date=lrd)
                    elif doa:
                        ren = calculate_next_renewal_date(date_of_approval=doa)
                r_copy["renewal_date"] = ren
                r_copy["next_renewal_date"] = ren
                if not r_copy.get("zone") or r_copy.get("zone") == "Unknown":
                    r_copy["zone"] = get_zone_for_state(r_copy.get("state", "")) or "Unknown"
                normalized_results.append(r_copy)

            self._send_json({"query": query, "count": len(normalized_results), "results": normalized_results, "clubs": normalized_results})
            return

        # Activity List
        if path == "/api/activity/list":
            emp_id = query_params.get("emp_id", [""])[0]
            if emp_id:
                node_act_path = SyncEngine.get_employee_activities_path(emp_id)
                acts = CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS)
            else:
                acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            self._send_json({"count": len(acts), "activities": list(reversed(acts))})
            return

        # Admin Performance Dashboard Metrics
        if path == "/api/admin/metrics":
            session = self._get_auth_session()
            all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS, copy=False)
            all_activities = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, copy=False)
            all_quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, copy=False)
            all_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS, copy=False)

            # Query Filters: Scope by Zone and/or Year
            raw_zone = query_params.get("zone", ["ALL"])[0].strip()
            raw_year = query_params.get("year", ["ALL"])[0].strip()
            filter_zone = raw_zone if raw_zone.upper() != "ALL" and raw_zone else "ALL"
            filter_year = raw_year if raw_year.upper() != "ALL" and raw_year else "ALL"

            # Discover all available years dynamically across database
            available_years_set = {"2026", "2025", "2024"}
            for c in all_clubs:
                ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
                if ts:
                    dp = parse_iso_or_date(ts)
                    if dp:
                        available_years_set.add(str(dp.year))
            for a in all_activities:
                ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
                if ts:
                    dp = parse_iso_or_date(ts)
                    if dp:
                        available_years_set.add(str(dp.year))
            available_years = sorted(list(available_years_set), reverse=True)

            # Build employee to zone mapping
            emp_to_zone = {u.get("id"): u.get("zone", "Other") for u in all_users if u.get("role") == "EMPLOYEE"}

            # Filter clubs by zone and year
            filtered_clubs = []
            for c in all_clubs:
                c_st = c.get("state", "").strip()
                c_zone = c.get("zone", "").strip() or get_zone_for_state(c_st)
                ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
                dp = parse_iso_or_date(ts) if ts else None
                c_year = str(dp.year) if dp else ""

                if filter_zone != "ALL" and c_zone != filter_zone:
                    continue
                if filter_year != "ALL" and c_year != filter_year:
                    continue
                filtered_clubs.append(c)

            # Filter activities by zone and year
            filtered_activities = []
            for a in all_activities:
                emp_id = a.get("emp_id", "")
                act_zone = emp_to_zone.get(emp_id, "Other")
                ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
                dp = parse_iso_or_date(ts) if ts else None
                a_year = str(dp.year) if dp else ""

                if filter_zone != "ALL" and act_zone != filter_zone:
                    continue
                if filter_year != "ALL" and a_year != filter_year:
                    continue
                filtered_activities.append(a)

            # Filter quotas and users by zone
            if filter_zone != "ALL":
                zone_emp_ids = {u.get("id") for u in all_users if u.get("zone") == filter_zone}
                quotas = [q for q in all_quotas if q.get("emp_id") in zone_emp_ids]
                filtered_emp_users = [u for u in all_users if u.get("role") == "EMPLOYEE" and u.get("zone") == filter_zone]
            else:
                quotas = all_quotas
                filtered_emp_users = [u for u in all_users if u.get("role") == "EMPLOYEE"]

            # Calculate breakdown metrics from filtered clubs
            state_counts: Dict[str, int] = {}
            zone_counts: Dict[str, int] = {}
            year_counts: Dict[str, int] = {}
            month_counts: Dict[str, int] = {}
            status_counts: Dict[str, int] = {}

            for c in filtered_clubs:
                st = c.get("state", "Unknown")
                zn = c.get("zone", "Unknown") or get_zone_for_state(st)
                stat = c.get("status", "Approved")
                ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")

                state_counts[st] = state_counts.get(st, 0) + 1
                zone_counts[zn] = zone_counts.get(zn, 0) + 1
                status_counts[stat] = status_counts.get(stat, 0) + 1

                if ts:
                    d_parsed = parse_iso_or_date(ts)
                    if d_parsed:
                        yr = str(d_parsed.year)
                        mo = f"{d_parsed.year:04d}-{d_parsed.month:02d}"
                        year_counts[yr] = year_counts.get(yr, 0) + 1
                        month_counts[mo] = month_counts.get(mo, 0) + 1

            attention_data = AIDecisionEngine.get_renewal_attention_data(clubs=filtered_clubs)

            # Detailed Analytics: 1. Support Type Breakdown
            support_type_counts = {st: 0 for st in SUPPORT_TYPES}
            for a in filtered_activities:
                stype = a.get("support_type", "")
                if stype in support_type_counts:
                    support_type_counts[stype] += 1
                elif stype:
                    support_type_counts[stype] = support_type_counts.get(stype, 0) + 1

            # Detailed Analytics: 2. Renewal & Retention Health
            total_clubs_count = len(filtered_clubs)
            overdue_count = attention_data.get("overdue_count", 0)
            expiring_soon_count = attention_data.get("expiring_soon_count", 0)
            active_validity_count = max(0, total_clubs_count - overdue_count)
            retention_rate_pct = round(((total_clubs_count - overdue_count) / max(1, total_clubs_count)) * 100, 1) if total_clubs_count > 0 else 100.0
            renewal_health = {
                "total_clubs": total_clubs_count,
                "active_validity_count": active_validity_count,
                "expiring_soon_count": expiring_soon_count,
                "overdue_count": overdue_count,
                "retention_rate_pct": retention_rate_pct
            }

            # Detailed Analytics: 3. National / Regional State Coverage Index
            if filter_zone != "ALL":
                target_states = ZONE_STATE_MAP.get(filter_zone, [])
            else:
                target_states = get_all_states()

            total_states = len(target_states)
            represented_states = [s for s in target_states if state_counts.get(s, 0) > 0]
            deficit_states = [s for s in target_states if state_counts.get(s, 0) == 0]
            coverage_pct = round((len(represented_states) / max(1, total_states)) * 100, 1) if total_states > 0 else 0.0
            coverage_index = {
                "total_states": total_states,
                "represented_count": len(represented_states),
                "deficit_count": len(deficit_states),
                "coverage_percentage": coverage_pct,
                "deficit_states": deficit_states,
                "represented_states": represented_states,
                "zone_scope": filter_zone
            }

            # Detailed Analytics: 4. Zone Efficiency & Activity Distribution
            all_zones = get_all_zones()
            zone_support_counts: Dict[str, int] = {z: 0 for z in all_zones}
            for a in filtered_activities:
                emp_id = a.get("emp_id")
                z = emp_to_zone.get(emp_id)
                if z and z in zone_support_counts:
                    zone_support_counts[z] += 1
                elif z:
                    zone_support_counts[z] = zone_support_counts.get(z, 0) + 1

            zone_efficiency = {}
            for z in (all_zones if filter_zone == "ALL" else [filter_zone]):
                c_cnt = zone_counts.get(z, 0)
                s_cnt = zone_support_counts.get(z, 0)
                zone_efficiency[z] = {
                    "clubs": c_cnt,
                    "support_logs": s_cnt,
                    "ratio": round(s_cnt / max(1, c_cnt), 2)
                }

            self._send_json({
                "summary": {
                    "total_clubs": len(filtered_clubs),
                    "total_activities": len(filtered_activities),
                    "total_employees": len(filtered_emp_users),
                    "quotas": quotas,
                    "renewal_attention_count": attention_data["total_attention_count"]
                },
                "filters": {
                    "zone": filter_zone,
                    "year": filter_year
                },
                "available_years": available_years,
                "state_wise_clubs": state_counts,
                "zone_wise_clubs": zone_counts,
                "year_wise_clubs": dict(sorted(year_counts.items())),
                "month_wise_clubs": dict(sorted(month_counts.items())),
                "status_wise_clubs": status_counts,
                "support_type_breakdown": support_type_counts,
                "renewal_health": renewal_health,
                "coverage_index": coverage_index,
                "zone_efficiency": zone_efficiency,
                "users": [{k: v for k, v in u.items() if k not in ["password_hash", "salt"]} for u in all_users]
            })
            return

        # Admin Employee Performance Evaluation & Star Rating Matrix
        if path == "/api/admin/employee-performance":
            raw_year = query_params.get("year", ["ALL"])[0].strip()
            raw_month = query_params.get("month", ["ALL"])[0].strip()
            raw_state = query_params.get("state", ["ALL"])[0].strip() or query_params.get("states", ["ALL"])[0].strip()

            filter_year = raw_year if raw_year.upper() != "ALL" and raw_year else "ALL"
            filter_month = raw_month if raw_month.upper() != "ALL" and raw_month else "ALL"
            filter_state = raw_state if raw_state.upper() != "ALL" and raw_state else "ALL"

            month_map = {
                "january": 1, "jan": 1, "01": 1, "1": 1,
                "february": 2, "feb": 2, "02": 2, "2": 2,
                "march": 3, "mar": 3, "03": 3, "3": 3,
                "april": 4, "apr": 4, "04": 4, "4": 4,
                "may": 5, "05": 5, "5": 5,
                "june": 6, "jun": 6, "06": 6, "6": 6,
                "july": 7, "jul": 7, "07": 7, "7": 7,
                "august": 8, "aug": 8, "08": 8, "8": 8,
                "september": 9, "sep": 9, "sept": 9, "09": 9, "9": 9,
                "october": 10, "oct": 10, "10": 10,
                "november": 11, "nov": 11, "11": 11,
                "december": 12, "dec": 12, "12": 12
            }
            target_month_num = month_map.get(filter_month.lower()) if filter_month != "ALL" else None

            all_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            all_activities = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)

            # Build club lookup for activity state resolution
            club_lookup = {c.get("club_id", "").strip().upper(): c for c in all_clubs if c.get("club_id")}

            # Discover available years dynamically
            available_years_set = {"2026", "2025", "2024"}
            for c in all_clubs:
                ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
                if ts:
                    dp = parse_iso_or_date(ts)
                    if dp:
                        available_years_set.add(str(dp.year))
            for a in all_activities:
                ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
                if ts:
                    dp = parse_iso_or_date(ts)
                    if dp:
                        available_years_set.add(str(dp.year))
            available_years = sorted(list(available_years_set), reverse=True)

            all_states_list = get_all_states()

            # Active employee officers
            officers = [u for u in all_users if u.get("role") == "EMPLOYEE"]

            # Pre-compute officer covers_state mapping and zone fallback mapping
            covers_state_by_emp: Dict[str, bool] = {}
            zone_to_default_emp: Dict[str, str] = {}
            for u in officers:
                eid = u.get("id", "").strip().upper()
                ezn = u.get("zone", "").strip()
                if ezn and ezn not in zone_to_default_emp:
                    zone_to_default_emp[ezn] = eid
                assigned_states_list = [s.strip().lower() for s in (u.get("assigned_states", "")).split(",") if s.strip()]
                covers_state_by_emp[eid] = (filter_state == "ALL") or (filter_state.lower() in assigned_states_list)

            # Clubs approval aggregation across master clubs and priority club approval activities
            clubs_approved_by_emp_set: Dict[str, set] = {u.get("id", "").strip().upper(): set() for u in officers}
            club_approvals_standalone: Dict[str, int] = {u.get("id", "").strip().upper(): 0 for u in officers}

            for c in all_clubs:
                c_state = c.get("state", "").strip()
                if filter_state != "ALL" and c_state.lower() != filter_state.lower():
                    continue

                ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
                dp = parse_iso_or_date(ts) if ts else None
                if filter_year != "ALL":
                    if not dp or str(dp.year) != filter_year:
                        continue
                if target_month_num is not None:
                    if not dp or dp.month != target_month_num:
                        continue

                c_emp = c.get("approved_by_emp_id", "").strip().upper()
                if not c_emp:
                    c_zn = c.get("zone", "").strip() or get_zone_for_state(c_state)
                    c_emp = zone_to_default_emp.get(c_zn, "")

                cid = c.get("club_id", "").strip().upper()
                if c_emp in clubs_approved_by_emp_set:
                    if cid:
                        clubs_approved_by_emp_set[c_emp].add(cid)
                    else:
                        club_approvals_standalone[c_emp] += 1

            # Single-pass O(N) activities aggregation
            act_stats_by_emp: Dict[str, Dict[str, int]] = {
                u.get("id", "").strip().upper(): {"online": 0, "offline": 0, "other": 0} for u in officers
            }
            for a in all_activities:
                a_emp = a.get("emp_id", "").strip().upper()
                if a_emp not in act_stats_by_emp:
                    continue

                cid = a.get("club_id", "").strip().upper()
                ref_club = club_lookup.get(cid)
                act_state = ref_club.get("state", "").strip() if ref_club else ""

                # State filtering for activities
                if filter_state != "ALL":
                    if act_state:
                        if act_state.lower() != filter_state.lower():
                            continue
                    else:
                        if not covers_state_by_emp.get(a_emp, False):
                            continue

                ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
                dp = parse_iso_or_date(ts) if ts else None
                ts_club = ref_club.get("date_of_approval", "") if ref_club else ""
                dp_club = parse_iso_or_date(ts_club) if ts_club else None

                date_match = True
                if filter_year != "ALL":
                    act_yr = str(dp.year) if dp else ""
                    club_yr = str(dp_club.year) if dp_club else ""
                    if act_yr != filter_year and club_yr != filter_year:
                        date_match = False
                if date_match and target_month_num is not None:
                    act_m = dp.month if dp else 0
                    club_m = dp_club.month if dp_club else 0
                    if act_m != target_month_num and club_m != target_month_num:
                        date_match = False

                if not date_match:
                    continue

                stype = a.get("support_type", "").strip()
                aid = a.get("activity_id", "").strip()
                is_club_approval = (
                    stype == "Club Approval"
                    or a.get("priority_flag") == "1"
                    or aid.startswith(f"ACT-PRIORITY-{a_emp}")
                )

                if is_club_approval:
                    if a_emp in clubs_approved_by_emp_set:
                        if cid:
                            clubs_approved_by_emp_set[a_emp].add(cid)
                        else:
                            club_approvals_standalone[a_emp] += 1
                elif stype == "Online training":
                    act_stats_by_emp[a_emp]["online"] += 1
                elif stype == "Offline training":
                    act_stats_by_emp[a_emp]["offline"] += 1
                elif stype in ["Phone call and remote assistance", "Closing of OS Ticket"]:
                    act_stats_by_emp[a_emp]["other"] += 1

            evaluations = []
            for u in officers:
                emp_id = u.get("id", "").strip().upper()
                emp_name = u.get("full_name", "") or u.get("name", "") or emp_id
                emp_zone = u.get("zone", "") or "Other"
                assigned_states_str = u.get("assigned_states", "")
                covers_state = covers_state_by_emp.get(emp_id, True)

                clubs_approved = len(clubs_approved_by_emp_set.get(emp_id, set())) + club_approvals_standalone.get(emp_id, 0)
                a_counts = act_stats_by_emp.get(emp_id, {"online": 0, "offline": 0, "other": 0})
                online_training = a_counts["online"]
                offline_training = a_counts["offline"]
                other_supports = a_counts["other"]

                # 3. 50/30/20/10 Weighted Score Calculation
                # 50% Club Approval + 30% Other Supports + 20% Offline Training + 10% Online Training
                weighted_score = round(
                    (0.50 * clubs_approved) +
                    (0.30 * other_supports) +
                    (0.20 * offline_training) +
                    (0.10 * online_training),
                    2
                )

                evaluations.append({
                    "emp_id": emp_id,
                    "full_name": emp_name,
                    "zone": emp_zone,
                    "assigned_states": assigned_states_str,
                    "clubs_approved": clubs_approved,
                    "online_training": online_training,
                    "offline_training": offline_training,
                    "other_supports": other_supports,
                    "total_activities": online_training + offline_training + other_supports,
                    "weighted_score": weighted_score,
                    "covers_selected_state": covers_state
                })

            # Sort officers descending by weighted_score, then clubs_approved, then total_activities
            evaluations.sort(key=lambda x: (x["weighted_score"], x["clubs_approved"], x["total_activities"]), reverse=True)

            # Assign Ranks and Star Ratings (1 to 5 Stars)
            max_score = max((e["weighted_score"] for e in evaluations), default=0.0)
            for idx, e in enumerate(evaluations, start=1):
                e["rank"] = idx
                w_score = e["weighted_score"]
                if max_score > 0 and w_score > 0:
                    ratio = w_score / max_score
                    if ratio >= 0.80:
                        stars = 5
                    elif ratio >= 0.60:
                        stars = 4
                    elif ratio >= 0.40:
                        stars = 3
                    elif ratio >= 0.20:
                        stars = 2
                    else:
                        stars = 1
                else:
                    stars = 1
                e["stars"] = stars
                e["stars_display"] = "★" * stars + "☆" * (5 - stars)
                e["rating_label"] = f"{stars}.0 / 5.0"

            self._send_json({
                "success": True,
                "filters": {
                    "year": filter_year,
                    "month": filter_month,
                    "state": filter_state
                },
                "available_years": available_years,
                "available_states": all_states_list,
                "weightage": {
                    "club_approval_pct": 50,
                    "other_supports_pct": 30,
                    "offline_training_pct": 20,
                    "online_training_pct": 10
                },
                "summary": {
                    "total_officers": len(evaluations),
                    "max_score": max_score,
                    "top_officer": evaluations[0] if evaluations else None
                },
                "officers": evaluations
            })
            return

        # Admin Renewal Attention Clubs List
        if path == "/api/admin/renewal-attention":
            attention_data = AIDecisionEngine.get_renewal_attention_data()
            self._send_json({"success": True, **attention_data})
            return

        # Single Club Full Details View
        if path == "/api/clubs/details":
            club_id = query_params.get("club_id", [""])[0] or query_params.get("id", [""])[0]
            clean_cid = club_id.strip().upper()
            if not clean_cid:
                self._send_error("club_id parameter is required.")
                return

            target = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", clean_cid, CLUB_FIELDS)
            if not target and EMPLOYEE_NODES_DIR.exists():
                for emp_dir in EMPLOYEE_NODES_DIR.iterdir():
                    if emp_dir.is_dir():
                        target = CSVEngine.find_by_key(emp_dir / "clubs.csv", "club_id", clean_cid, CLUB_FIELDS)
                        if target:
                            break

            if not target:
                self._send_error(f"Club with ID '{clean_cid}' not found.", status=404)
                return

            today = datetime.now(timezone.utc).date()
            est_ts = target.get("date_of_approval", "") or target.get("submission_timestamp", "")
            last_ren = target.get("last_renewal_date", "")
            ren_date = target.get("renewal_date", "") or target.get("next_renewal_date", "")

            if not ren_date:
                ren_date = calculate_next_renewal_date(date_of_approval=est_ts, last_renewal_date=last_ren)
            parsed_ren = parse_iso_or_date(ren_date)

            days_diff = None
            urgency = "Normal"
            attention_type = "Normal"
            badge_class = "pill-success"
            days_overdue = 0
            days_left = 0
            if parsed_ren:
                days_diff = (parsed_ren - today).days
                if days_diff < 0:
                    days_overdue = abs(days_diff)
                    urgency = f"Overdue by {abs(days_diff)} days"
                    attention_type = "Overdue"
                    badge_class = "pill-danger"
                elif days_diff <= 90:
                    days_left = days_diff
                    urgency = f"Expiring in {days_diff} days" if days_diff > 0 else "Expires today"
                    attention_type = "Expiring Soon"
                    badge_class = "pill-warning"
                else:
                    days_left = days_diff

            c_info = dict(target)
            if not c_info.get("zone") or c_info.get("zone") == "Unknown":
                c_info["zone"] = get_zone_for_state(c_info.get("state", "")) or "Unknown"
            c_info["date_of_approval"] = est_ts
            c_info["submission_timestamp"] = est_ts
            c_info["last_renewal_date"] = last_ren
            c_info["renewal_date"] = ren_date
            c_info["next_renewal_date"] = ren_date
            c_info["effective_renewal_date"] = ren_date
            c_info["next_renewal_due_date"] = ren_date
            c_info["days_diff"] = days_diff
            c_info["days_overdue"] = days_overdue
            c_info["days_left"] = days_left
            c_info["urgency"] = urgency
            c_info["attention_type"] = attention_type
            c_info["badge_class"] = badge_class

            self._send_json({
                "success": True,
                "found": True,
                "club": c_info
            })
            return

        # Admin Employee Roster & Status
        if path == "/api/admin/employees":
            if not self._check_admin_access():
                return
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            quota_map = {q.get("emp_id"): q for q in quotas}

            employees = []
            for u in users:
                if u.get("role") == "EMPLOYEE":
                    q = quota_map.get(u.get("id"), {})
                    employees.append({
                        "id": u.get("id"),
                        "full_name": u.get("full_name"),
                        "email": u.get("email"),
                        "zone": u.get("zone"),
                        "assigned_states": u.get("assigned_states"),
                        "is_active": str(u.get("is_active", "1")),
                        "created_at": u.get("created_at"),
                        "clubs_approved_count": int(q.get("clubs_approved_count", "0") or "0"),
                        "support_logs_count": int(q.get("support_logs_count", "0") or "0"),
                        "last_activity_timestamp": q.get("last_activity_timestamp", "")
                    })
            self._send_json({"count": len(employees), "employees": employees})
            return

        # AI Strategic Decision Module
        if path == "/api/admin/ai-insights":
            insights = AIDecisionEngine.generate_strategic_report()
            self._send_json(insights)
            return

        # Sync Status
        if path == "/api/sync/status":
            master_clubs = len(CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS))
            master_acts = len(CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS))
            self._send_json({
                "status": "synchronized",
                "master_clubs_count": master_clubs,
                "master_activities_count": master_acts,
                "storage_mode": get_storage_adapter().get_info()["mode"]
            })
            return

        # DOWNLOAD USER MANUAL (PDF)
        if path in [
            "/api/download/user-manual",
            "/api/download/manual",
            "/download/user-manual",
            "/download/manual",
            "/manual.pdf",
            "/NDLI_Club_Management_User_Manual.pdf",
            "/user-manual.pdf"
        ]:
            user_manual_file = BASE_DIR / "NDLI_Club_Management_User_Manual.pdf"
            if not user_manual_file.exists():
                alt_path = BASE_DIR / "docs" / "NDLI_Club_Management_User_Manual.pdf"
                if alt_path.exists():
                    user_manual_file = alt_path
                else:
                    alt_static = BASE_DIR / "static" / "NDLI_Club_Management_User_Manual.pdf"
                    if alt_static.exists():
                        user_manual_file = alt_static

            if not user_manual_file.exists():
                self._send_error("User Manual PDF not found. Please compile it first.", status=404)
                return

            try:
                with open(user_manual_file, "rb") as f:
                    pdf_bytes = f.read()

                disp_type = "inline" if ("inline" in query_params or "view" in query_params) else "attachment"
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'{disp_type}; filename="NDLI_Club_Management_User_Manual.pdf"')
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(pdf_bytes)
            except Exception as e:
                self._send_error(f"Error serving User Manual PDF: {str(e)}", status=500)
            return

        # PROMOTIONAL ADVERTISEMENT VIDEO (MP4)
        if path in [
            "/api/download/promo-video",
            "/api/download/video",
            "/download/promo-video",
            "/download/video",
            "/ndli_promo_video.mp4",
            "/promo-video.mp4",
            "/video.mp4",
            "/promo-video",
            "/video"
        ]:
            video_file = BASE_DIR / "ndli_promo_video.mp4"
            if not video_file.exists():
                alt_path = BASE_DIR / "static" / "ndli_promo_video.mp4"
                if alt_path.exists():
                    video_file = alt_path

            if not video_file.exists():
                self._send_error("Promotional Video MP4 not found.", status=404)
                return

            try:
                with open(video_file, "rb") as f:
                    video_bytes = f.read()

                disp_type = "attachment" if ("download" in query_params or path.startswith("/api/download")) else "inline"
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Disposition", f'{disp_type}; filename="NDLI_Promo_Video.mp4"')
                self.send_header("Content-Length", str(len(video_bytes)))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(video_bytes)
            except Exception as e:
                self._send_error(f"Error serving promo video: {str(e)}", status=500)
            return

        # FEATURE 1: Download Master CSV (master_clubs.csv) from Admin Dashboard
        if path in ["/api/admin/download/master-clubs", "/api/admin/download/master_clubs.csv"]:
            if not MASTER_CLUBS_CSV.exists():
                CSVEngine.ensure_file(MASTER_CLUBS_CSV, CLUB_FIELDS)
            try:
                with open(MASTER_CLUBS_CSV, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="master_clubs.csv"')
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self._send_error(f"Error serving master CSV: {str(e)}", status=500)
            return

        # DIAGNOSTIC: Read the durable sync-failure log directly (the
        # per-request adapter instance from get_storage_adapter() has no
        # memory of past requests, so this file -- written straight to disk
        # by _log_sync_event -- is the only reliable place to see what a
        # background/confirm_durable sync actually failed with).
        if path == "/api/admin/sync-issues":
            if not self._check_admin_access():
                return
            try:
                adapter = get_storage_adapter()
                log_path = adapter.local.root_dir / "sync_issues.log" if hasattr(adapter, "local") else None
                if not log_path or not log_path.exists():
                    self._send_json({"success": True, "entries": [], "message": "No sync issues logged yet."})
                    return
                lines = log_path.read_text(encoding="utf-8").strip().split("\n")
                tail_param = query_params.get("tail", ["50"])[0]
                tail_n = int(tail_param) if tail_param.isdigit() else 50
                recent = lines[-tail_n:]
                entries = []
                for line in recent:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        entries.append({"raw": line})
                self._send_json({"success": True, "count": len(entries), "entries": entries})
            except Exception as e:
                self._send_error(f"Error reading sync issues log: {str(e)}", status=500)
            return

        # FEATURE 2: 7-Day Auto Backup Status Check (Admin End & Employee End)
        if path == "/api/admin/backup/status":
            BackupEngine.check_and_run_auto_backup()
            status_data = BackupEngine.get_backup_status()
            self._send_json({"success": True, **status_data})
            return

        # FEATURE 3: Download Activity Log (activity_log.csv for Employee)
        if path in ["/api/employee/download/activity-log", "/api/employee/download/activity_log.csv"]:
            emp_id = query_params.get("emp_id", [""])[0]
            if not emp_id:
                session = self._get_auth_session()
                if session:
                    emp_id = session.get("user_id", "")
            if not emp_id:
                self._send_error("Employee ID (emp_id) is required.", status=400)
                return
            clean_emp = emp_id.strip().upper()
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            emp_user = next((u for u in users if u.get("id", "").strip().upper() == clean_emp), None)
            if not emp_user:
                self._send_error(f"Employee account '{emp_id}' does not exist.", status=404)
                return
            if str(emp_user.get("is_active", "1")).strip() == "0":
                self._send_error(f"Employee account '{emp_id}' is blocked or inactive. Download access denied.", status=403)
                return

            act_path = SyncEngine.get_employee_activities_path(clean_emp)
            if not act_path.exists():
                CSVEngine.ensure_file(act_path, ACTIVITY_FIELDS)
            try:
                with open(act_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="activity_log.csv"')
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self._send_error(f"Error serving employee activity log: {str(e)}", status=500)
            return

        # FEATURE 3: Download Clubs Log (clubs.csv for Employee)
        if path in ["/api/employee/download/clubs-log", "/api/employee/download/clubs.csv"]:
            emp_id = query_params.get("emp_id", [""])[0]
            if not emp_id:
                session = self._get_auth_session()
                if session:
                    emp_id = session.get("user_id", "")
            if not emp_id:
                self._send_error("Employee ID (emp_id) is required.", status=400)
                return
            clean_emp = emp_id.strip().upper()
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            emp_user = next((u for u in users if u.get("id", "").strip().upper() == clean_emp), None)
            if not emp_user:
                self._send_error(f"Employee account '{emp_id}' does not exist.", status=404)
                return
            if str(emp_user.get("is_active", "1")).strip() == "0":
                self._send_error(f"Employee account '{emp_id}' is blocked or inactive. Download access denied.", status=403)
                return

            clubs_path = SyncEngine.get_employee_clubs_path(clean_emp)
            if not clubs_path.exists():
                CSVEngine.ensure_file(clubs_path, CLUB_FIELDS)
            try:
                with open(clubs_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="clubs.csv"')
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self._send_error(f"Error serving employee clubs log: {str(e)}", status=500)
            return

        # FEATURE 4: Employee Reminders Query (Appears after 72 hours, or +7 days if not resolved)
        if path == "/api/issues/employee-reminders":
            emp_id = query_params.get("emp_id", [""])[0]
            if not emp_id:
                session = self._get_auth_session()
                if session and session.get("role") == "EMPLOYEE":
                    emp_id = session.get("user_id", "")
            reminders = IssueManager.get_employee_reminders(emp_id=emp_id if emp_id else None)
            self._send_json({"success": True, "count": len(reminders), "reminders": reminders})
            return

        # FEATURE 5: Admin Escalation Reminders Query (Unresolved for 30 days, or +7 days if not resolved)
        if path == "/api/issues/admin-reminders":
            reminders = IssueManager.get_admin_reminders()
            self._send_json({"success": True, "count": len(reminders), "reminders": reminders})
            return

        # Issues List Query
        if path == "/api/issues/list":
            emp_id = query_params.get("emp_id", [""])[0]
            club_id = query_params.get("club_id", [""])[0]
            status_param = query_params.get("status", [""])[0]
            issues = IssueManager.get_issues(emp_id=emp_id or None, club_id=club_id or None, status=status_param or None)
            self._send_json({"success": True, "count": len(issues), "issues": issues})
            return

        # Single Issue Details
        if path == "/api/issues/details":
            issue_id = query_params.get("issue_id", [""])[0] or query_params.get("id", [""])[0]
            if not issue_id:
                self._send_error("issue_id parameter is required.", status=400)
                return
            issue = IssueManager.get_issue_by_id(issue_id)
            if not issue:
                self._send_error(f"Issue with ID '{issue_id}' not found.", status=404)
                return
            self._send_json({"success": True, "found": True, "issue": issue})
            return

        # Certificate Settings Query
        if path == "/api/certificate/settings":
            sig_dir = DATA_DIR / "signatures"
            sig_dir.mkdir(parents=True, exist_ok=True)
            settings_file = sig_dir / "settings.json"
            sig_png = sig_dir / "pi_signature.png"
            sig_jpg = sig_dir / "pi_signature.jpg"
            sig_exists = sig_png.exists() or sig_jpg.exists()

            settings_data = {
                "pi_name": "Prof. Partha Pratim Chakrabarti",
                "pi_affiliation": "Principal Investigator, NDLI Project, Central Library, IIT Kharagpur",
                "has_signature": sig_exists,
                "signature_url": "/api/certificate/signature" if sig_exists else None
            }
            if settings_file.exists():
                try:
                    with open(settings_file, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                        settings_data.update(saved)
                        settings_data["has_signature"] = sig_exists
                        settings_data["signature_url"] = "/api/certificate/signature" if sig_exists else None
                except Exception:
                    pass
            self._send_json({"success": True, "settings": settings_data})
            return

        # Serve Uploaded PI Signature Image
        if path == "/api/certificate/signature":
            sig_dir = DATA_DIR / "signatures"
            sig_path = sig_dir / "pi_signature.png"
            if not sig_path.exists():
                sig_path = sig_dir / "pi_signature.jpg"
            if sig_path.exists():
                ext = sig_path.suffix.lower()
                ctype = "image/png" if ext == ".png" else "image/jpeg"
                self._serve_file(sig_path, ctype)
            else:
                self._send_error("No PI signature uploaded yet.", status=404)
            return

        # Trigger Immediate Google Drive Sync
        if path == "/api/admin/drive/sync-now":
            adapter = get_storage_adapter()
            if hasattr(adapter, "sync_all_now"):
                res = adapter.sync_all_now()
                self._send_json(res)
            else:
                self._send_json({"success": True, "message": "Storage adapter is running in local sync mode.", "info": adapter.get_info()})
            return

        self._send_error(f"Endpoint not found: {path}", status=404)

    def do_POST(self):
        """Routing for POST requests with emergency crash recovery boundary."""
        try:
            self._handle_do_POST()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._send_error(f"Internal server error: {str(exc)}", status=500)

    def _handle_do_POST(self):
        """Routing for POST requests."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        body = self._parse_json_body()

        # Authentication: Login
        if path == "/api/auth/login":
            identifier = str(body.get("email", "") or body.get("user_id", "") or body.get("identifier", "")).strip()
            password = str(body.get("password", "")).strip()
            success, err, session_data = AuthService.authenticate(identifier, password)
            if not success:
                self._send_error(err or "Authentication failed.", status=401)
                return
            self._send_json({
                "success": True,
                "message": "Login successful.",
                "session": session_data
            })
            return

        # Authentication: Logout
        if path == "/api/auth/logout":
            token = body.get("token", "")
            if not token:
                auth_hdr = self.headers.get("Authorization", "")
                if auth_hdr.startswith("Bearer "):
                    token = auth_hdr.split(" ", 1)[1].strip()
            AuthService.logout(token)
            self._send_json({"success": True, "message": "Logged out successfully."})
            return

        # Security Verification: Verify Login Password (Renewal Confirmation Second Layer)
        if path == "/api/auth/verify-password":
            identifier = str(body.get("user_id", "") or body.get("emp_id", "") or body.get("email", "") or body.get("identifier", "")).strip()
            password = str(body.get("password", "")).strip()

            if not identifier:
                session = self._get_auth_session()
                if session:
                    identifier = session.get("user_id") or session.get("email", "")

            if not identifier:
                self._send_error("Employee identifier (user_id / email) is required.", status=400)
                return
            if not password:
                self._send_error("Password is required for verification.", status=400)
                return

            success, err, user_dict = AuthService.authenticate(identifier, password)
            if success and user_dict:
                self._send_json({
                    "success": True,
                    "valid": True,
                    "message": "Password verified successfully.",
                    "user_id": user_dict.get("user_id") or user_dict.get("id"),
                    "role": user_dict.get("role")
                })
            else:
                self._send_error(err or "Incorrect password. Verification failed.", status=401)
            return

        # SEC A: Log Daily Support Activity
        if path == "/api/activity/log":
            emp_id = str(body.get("emp_id", "")).strip().upper()
            support_type = str(body.get("support_type", "")).strip()
            notes = str(body.get("notes", "")).strip()
            club_id = str(body.get("club_id", "")).strip()
            raw_count = body.get("count", 1) or body.get("entry_count", 1) or body.get("call_count", 1)
            try:
                count = int(raw_count)
                if count < 1:
                    count = 1
            except (ValueError, TypeError):
                count = 1

            if not emp_id:
                self._send_error("Employee ID (emp_id) is required.")
                return
            if not support_type:
                self._send_error("Support type is required.")
                return

            if not self._is_employee_active(emp_id):
                self._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
                return

            # Bulk entry facility is made available for Phone Call and Remote Assistance only
            if support_type != "Phone call and remote assistance":
                count = 1
            elif count > 100:
                count = 100

            act_row = SyncEngine.log_support_activity(
                emp_id=emp_id,
                support_type=support_type,
                notes=notes,
                club_id=club_id,
                count=count
            )
            msg = (
                f"{count} Phone call & remote assistance entries recorded in bulk successfully."
                if count > 1
                else "Support activity recorded successfully."
            )
            self._send_json({
                "success": True,
                "message": msg,
                "count": count,
                "activity": act_row
            })
            return

        # SEC C: Approve New Club Details
        if path == "/api/clubs/create":
            emp_id = str(body.get("emp_id", "")).strip().upper()
            if not emp_id:
                self._send_error("Approving Employee ID (emp_id) is required.")
                return

            if not self._is_employee_active(emp_id):
                self._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
                return

            errors = validate_club_payload(body)
            if errors:
                self._send_json({
                    "error": True,
                    "validation_errors": errors,
                    "message": "Form validation failed. Please correct the highlighted fields."
                }, status=422)
                return

            # Auto-map zone if not provided or to ensure strict compliance
            state = str(body.get("state", "")).strip()
            body["zone"] = get_zone_for_state(state) or "Unknown"

            created_club = SyncEngine.approve_new_club(emp_id=emp_id, club_data=body)
            cloud_confirmed = created_club.get("cloud_sync_confirmed", True)
            self._send_json({
                "success": True,
                "message": (
                    f"NDLI Club {created_club['club_id']} approved successfully."
                    if cloud_confirmed else
                    f"NDLI Club {created_club['club_id']} saved, but cloud backup "
                    f"could not be confirmed. This server has no persistent disk, "
                    f"so this record may be lost if the server restarts before the "
                    f"sync succeeds. Please notify an administrator and avoid "
                    f"relying on this save until confirmed."
                ),
                "cloud_sync_confirmed": cloud_confirmed,
                "club": created_club
            })
            return

        # Admin: Permanently Delete a Club (Master + Employee Node + Drive)
        if path == "/api/admin/clubs/delete":
            if not self._check_admin_access():
                return
            club_id = str(body.get("club_id", "")).strip().upper()
            if not club_id:
                self._send_error("club_id is required.")
                return
            try:
                result = SyncEngine.delete_club(club_id)
            except Exception as e:
                self._send_error(f"Error deleting club: {str(e)}", status=500)
                return
            if not result.get("deleted"):
                self._send_error(result.get("message", f"Club '{club_id}' not found."), status=404)
                return
            self._send_json({
                "success": True,
                "message": f"Club {club_id} permanently deleted.",
                **result
            })
            return

        # Update Club Details (Universal Search Edit)
        if path == "/api/clubs/update":
            emp_id = str(body.get("emp_id", "")).strip().upper()
            club_id = str(body.get("club_id", "")).strip().upper()
            if not club_id:
                self._send_error("club_id is required.")
                return

            if emp_id and not self._is_employee_active(emp_id):
                self._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
                return

            updated = SyncEngine.update_club(emp_id=emp_id, club_id=club_id, updated_fields=body)
            if not updated:
                self._send_error(f"Club with ID '{club_id}' not found.", status=404)
                return

            self._send_json({
                "success": True,
                "message": f"Club {club_id} updated successfully.",
                "club": updated
            })
            return

        # Registration Renewal ("Renewal Approved")
        if path == "/api/clubs/renew":
            emp_id = str(body.get("emp_id", "")).strip().upper()
            club_id = str(body.get("club_id", "")).strip().upper()
            renewal_date = str(body.get("renewal_date", "")).strip()
            last_renewal_date = str(body.get("last_renewal_date", "")).strip()

            if not emp_id or not club_id:
                self._send_error("emp_id and club_id are required.")
                return

            if not self._is_employee_active(emp_id):
                self._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
                return

            updated = SyncEngine.renew_club_registration(
                emp_id=emp_id,
                club_id=club_id,
                renewal_date=renewal_date if renewal_date else None,
                last_renewal_date=last_renewal_date if last_renewal_date else None
            )
            if not updated:
                self._send_error(f"Club with ID '{club_id}' not found.", status=404)
                return

            final_renewal_date = updated.get("renewal_date", renewal_date)
            final_last_renewal = updated.get("last_renewal_date", "")
            self._send_json({
                "success": True,
                "message": f"Renewal Approved for club {club_id}. Last Renewal Date logged as {final_last_renewal}, upcoming renewal valid until {final_renewal_date}.",
                "club": updated
            })
            return

        # Block / Unblock Employee Access (Admin Only)
        if path == "/api/admin/employees/status":
            if not self._check_admin_access():
                return

            user_id = str(body.get("user_id", "")).strip().upper()
            is_active_val = body.get("is_active", True)
            if not user_id:
                self._send_error("user_id is required.")
                return

            success = AuthService.set_user_status(user_id=user_id, is_active=is_active_val)
            if not success:
                self._send_error(f"User '{user_id}' not found.", status=404)
                return

            status_str = "active" if str(is_active_val).lower() in ["1", "true", "yes"] else "blocked"
            self._send_json({
                "success": True,
                "message": f"User {user_id} status updated to {status_str}.",
                "user_id": user_id,
                "is_active": "1" if status_str == "active" else "0"
            })
            return

        # Single-Click Provision New Employee (Admin Only)
        if path == "/api/admin/employees/create":
            if not self._check_admin_access():
                return

            emp_id = str(body.get("emp_id", "")).strip().upper()
            email = str(body.get("email", "")).strip().lower()
            password = str(body.get("password", "")).strip()
            full_name = str(body.get("full_name", "")).strip()
            zone = str(body.get("zone", "")).strip()
            assigned_states = str(body.get("assigned_states", "")).strip()

            if not emp_id or not email or not password or not full_name:
                self._send_error("emp_id, email, password, and full_name are required.")
                return

            # Check duplicate ID or email before creation
            existing_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            for u in existing_users:
                if u.get("id", "").strip().upper() == emp_id:
                    self._send_error(f"Employee ID '{emp_id}' already exists. Use Edit to modify existing employees.", status=400)
                    return
                if u.get("email", "").strip().lower() == email:
                    self._send_error(f"Email '{email}' is already in use by another user.", status=400)
                    return

            user_record = AuthService.register_or_update_user(
                user_id=emp_id,
                email=email,
                password=password,
                full_name=full_name,
                role="EMPLOYEE",
                zone=zone,
                assigned_states=assigned_states,
                is_active="1"
            )
            self._send_json({
                "success": True,
                "message": f"Employee {emp_id} provisioned with dedicated node database.",
                "employee": {k: v for k, v in user_record.items() if k not in ["password_hash", "salt"]}
            })
            return

        # Update Existing Employee Details & Synchronize Node DB (Admin Only)
        if path == "/api/admin/employees/update":
            if not self._check_admin_access():
                return

            old_emp_id = str(body.get("old_emp_id", "") or body.get("emp_id", "")).strip().upper()
            new_emp_id = str(body.get("new_emp_id", "") or body.get("emp_id", "")).strip().upper()
            email = str(body.get("email", "")).strip().lower()
            password = str(body.get("password", "") or "").strip()
            full_name = str(body.get("full_name", "")).strip()
            zone = str(body.get("zone", "")).strip()
            assigned_states = str(body.get("assigned_states", "")).strip()
            is_active = body.get("is_active")

            if not old_emp_id:
                self._send_error("old_emp_id is required.")
                return
            if not new_emp_id:
                self._send_error("new_emp_id (or emp_id) is required.")
                return
            if not email:
                self._send_error("email is required.")
                return
            if not full_name:
                self._send_error("full_name is required.")
                return

            success, err_msg, updated_user = AuthService.update_employee(
                old_emp_id=old_emp_id,
                new_emp_id=new_emp_id,
                email=email,
                full_name=full_name,
                zone=zone,
                assigned_states=assigned_states,
                password=password if password else None,
                is_active=is_active
            )

            if not success:
                self._send_error(err_msg or "Failed to update employee.", status=400)
                return

            safe_emp = {k: v for k, v in updated_user.items() if k not in ["password_hash", "salt"]}
            self._send_json({
                "success": True,
                "message": f"Employee {new_emp_id} updated successfully and synchronized across node database.",
                "employee": safe_emp
            })
            return

        # Trigger Manual Reconcile
        if path == "/api/sync/reconcile":
            summary = SyncEngine.reconcile_all_nodes()
            self._send_json({
                "success": True,
                "message": "Reconciliation completed successfully.",
                "summary": summary
            })
            return

        # FEATURE 2: Trigger Database Backup Manually (Admin)
        if path in ["/api/admin/backup/trigger", "/api/admin/backup/create"]:
            try:
                note_param = body.get("note", "Manual Admin Trigger")
                res = BackupEngine.create_backup(note=note_param)
                self._send_json(res)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({
                    "success": False,
                    "error": True,
                    "message": f"Backup operation failed: {str(e)}"
                }, status=500)
            return

        # FEATURE 2: Emergency Database Restore (Admin)
        if path in ["/api/admin/backup/restore", "/api/admin/backup/emergency-restore"]:
            password = str(body.get("password", "")).strip()
            admin_email = str(body.get("admin_email") or body.get("email") or DEFAULT_ADMIN_EMAIL).strip()

            if not password:
                self._send_error("Master Admin password is required to authorize emergency database restoration.", status=401)
                return

            auth_ok, auth_err, user = AuthService.authenticate(admin_email, password)
            if not auth_ok or not user or user.get("role") != "ADMIN":
                self._send_error("Authentication failed: Invalid Master Admin password. Restoration aborted.", status=403)
                return

            target_source = body.get("source") or body.get("backup_id") or body.get("filename")
            if not target_source:
                existing = BackupEngine.get_existing_backups()
                if existing:
                    target_source = str(existing[0])
                else:
                    self._send_error("No backup available to restore.", status=400)
                    return
            try:
                res = BackupEngine.restore_backup(target_source)
                self._send_json(res)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._send_json({
                    "success": False,
                    "error": True,
                    "message": f"Restoration failed: {str(e)}"
                }, status=500)
            return

        # FEATURE 4: Log Unresolved Issue & Set 72-Hour Reminder
        if path == "/api/issues/create":
            club_id = str(body.get("club_id", "")).strip().upper()
            emp_id = str(body.get("emp_id", "")).strip().upper()
            issue_note = str(body.get("issue_note", "")).strip()
            created_at = body.get("created_at")
            reminder_due_at = body.get("reminder_due_at")
            admin_reminder_due_at = body.get("admin_reminder_due_at")

            if not club_id:
                self._send_error("club_id is required.", status=400)
                return
            if not emp_id:
                session = self._get_auth_session()
                if session:
                    emp_id = session.get("user_id", "")
            if not emp_id:
                self._send_error("emp_id is required.", status=400)
                return
            if not issue_note:
                self._send_error("issue_note (brief note of the issue) is required.", status=400)
                return

            issue = IssueManager.create_issue(
                club_id=club_id,
                emp_id=emp_id,
                issue_note=issue_note,
                created_at=created_at,
                reminder_due_at=reminder_due_at,
                admin_reminder_due_at=admin_reminder_due_at
            )
            self._send_json({
                "success": True,
                "message": f"Unresolved issue logged for {club_id}. Reminder scheduled to appear on dashboard after 72 hours.",
                "issue": issue
            })
            return

        # FEATURES 4 & 5: Mark Issue Resolved or Not Resolved (Auto-generate 7-day recurrent reminder)
        if path == "/api/issues/resolve":
            issue_id = str(body.get("issue_id", "")).strip()
            status_val = str(body.get("status", "")).strip()
            resolved_by = str(body.get("resolved_by", "")).strip()
            resolution_notes = str(body.get("resolution_notes", "")).strip()
            role_param = str(body.get("role", "")).strip().upper()

            if not issue_id:
                self._send_error("issue_id is required.", status=400)
                return
            if not status_val:
                self._send_error("status ('Resolved' or 'Not Resolved') is required.", status=400)
                return

            session = self._get_auth_session()
            if not resolved_by:
                if session:
                    resolved_by = session.get("email") or session.get("user_id", "")
                else:
                    resolved_by = "Portal User"

            if not role_param and session:
                role_param = session.get("role", "").strip().upper()

            updated_issue = IssueManager.resolve_issue(
                issue_id=issue_id,
                status=status_val,
                resolved_by=resolved_by,
                resolution_notes=resolution_notes,
                role=role_param if role_param else None
            )
            if not updated_issue:
                self._send_error(f"Issue with ID '{issue_id}' not found.", status=404)
                return

            is_resolved = updated_issue.get("status") == "Resolved"
            msg = (
                f"Issue {issue_id} marked as Resolved."
                if is_resolved
                else f"Issue {issue_id} marked as Not Resolved. Next reminder scheduled in 7 days."
            )
            self._send_json({
                "success": True,
                "message": msg,
                "issue": updated_issue
            })
            return

        # Certificate Signature Upload
        if path == "/api/certificate/signature":
            image_data = body.get("image_data", "")
            if not image_data:
                self._send_error("image_data (base64 string or data URL) is required.", status=400)
                return

            ext = ".png"
            b64_str = image_data
            if "," in image_data:
                header, b64_str = image_data.split(",", 1)
                if "image/jpeg" in header or "image/jpg" in header:
                    ext = ".jpg"
            elif body.get("extension") in [".jpg", ".jpeg"]:
                ext = ".jpg"

            try:
                raw_bytes = base64.b64decode(b64_str)
            except Exception as e:
                self._send_error(f"Invalid base64 image data: {e}", status=400)
                return

            sig_dir = DATA_DIR / "signatures"
            sig_dir.mkdir(parents=True, exist_ok=True)
            # Remove any alternate format to avoid confusion
            alt_ext = ".jpg" if ext == ".png" else ".png"
            alt_file = sig_dir / f"pi_signature{alt_ext}"
            if alt_file.exists():
                try:
                    alt_file.unlink()
                except Exception:
                    pass

            target_file = sig_dir / f"pi_signature{ext}"
            with open(target_file, "wb") as f:
                f.write(raw_bytes)

            settings_file = sig_dir / "settings.json"
            saved = {}
            if settings_file.exists():
                try:
                    with open(settings_file, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                except Exception:
                    pass
            saved["has_signature"] = True
            saved["signature_filename"] = f"pi_signature{ext}"
            if body.get("pi_name"):
                saved["pi_name"] = str(body.get("pi_name")).strip()
            if body.get("pi_affiliation"):
                saved["pi_affiliation"] = str(body.get("pi_affiliation")).strip()

            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)

            self._send_json({
                "success": True,
                "message": "PI signature uploaded and saved successfully.",
                "signature_url": f"/api/certificate/signature?t={int(datetime.now().timestamp())}",
                "filename": f"pi_signature{ext}"
            })
            return

        # Certificate Settings Update
        if path == "/api/certificate/settings":
            sig_dir = DATA_DIR / "signatures"
            sig_dir.mkdir(parents=True, exist_ok=True)
            settings_file = sig_dir / "settings.json"
            saved = {
                "pi_name": "Prof. Partha Pratim Chakrabarti",
                "pi_affiliation": "Principal Investigator, NDLI Project, Central Library, IIT Kharagpur"
            }
            if settings_file.exists():
                try:
                    with open(settings_file, "r", encoding="utf-8") as f:
                        saved.update(json.load(f))
                except Exception:
                    pass

            if "pi_name" in body and body["pi_name"] is not None:
                saved["pi_name"] = str(body["pi_name"]).strip()
            if "pi_affiliation" in body and body["pi_affiliation"] is not None:
                saved["pi_affiliation"] = str(body["pi_affiliation"]).strip()

            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)

            sig_png = sig_dir / "pi_signature.png"
            sig_jpg = sig_dir / "pi_signature.jpg"
            sig_exists = sig_png.exists() or sig_jpg.exists()

            saved["has_signature"] = sig_exists
            saved["signature_url"] = "/api/certificate/signature" if sig_exists else None

            self._send_json({
                "success": True,
                "message": "Certificate settings updated successfully.",
                "settings": saved
            })
            return

        # Trigger Immediate Google Drive Sync (Push)
        if path == "/api/admin/drive/sync-now":
            adapter = get_storage_adapter()
            if hasattr(adapter, "sync_all_now"):
                res = adapter.sync_all_now()
                self._send_json(res)
            else:
                self._send_json({"success": True, "message": "Storage adapter is running in local sync mode.", "info": adapter.get_info()})
            return

        # Trigger Immediate Google Drive Pull (Restore from Cloud)
        if path in ("/api/admin/drive/pull-now", "/api/sync/pull-now"):
            adapter = get_storage_adapter()
            if hasattr(adapter, "pull_all_from_drive"):
                res = adapter.pull_all_from_drive()
                if res.get("success"):
                    SyncEngine.reconcile_all_nodes()
                self._send_json(res)
            else:
                self._send_json({"success": True, "message": "Storage adapter is running in local sync mode.", "info": adapter.get_info()})
            return

        self._send_error(f"Endpoint not found: {path}", status=404)


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


if __name__ == "__main__":
    run_server()

