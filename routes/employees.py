"""
routes/employees.py - Employee roster / profile / admin employee management

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from auth import AuthService
from config import MASTER_QUOTAS_CSV, MASTER_USERS_CSV
from db.csv_engine import CSVEngine
from db.migration_engine import (
    baselines_for as migration_baselines_for,
    validate_employee_history as migration_validate_history,
    commit_employee_history as migration_commit_history,
    history_grand_totals as migration_grand_totals,
    history_period_years as migration_period_years,
    history_summary as migration_history_summary,
)
from db.schemas import QUOTA_FIELDS, USER_FIELDS
from db.sync_engine import SyncEngine

# path == "/api/employees/roster"
def get_employees_roster(h, path, query_params):
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
    h._send_json({"count": len(roster), "employees": roster})
    return

# path == "/api/employees/profile"
def get_employees_profile(h, path, query_params):
    emp_id = query_params.get("id", [""])[0] or query_params.get("emp_id", [""])[0]
    clean_id = emp_id.strip().upper()
    if not clean_id:
        h._send_error("emp_id or id parameter is required.")
        return
    if not h._require_session():
        return

    users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    target = None
    for u in users:
        if u.get("id", "").strip().upper() == clean_id:
            target = u
            break

    if not target:
        h._send_error(f"Employee with ID '{clean_id}' not found.", status=404)
        return

    # PERMANENT FIX: quota is now always derived fresh from live data
    # (no stored ratchet, no max()) via SyncEngine.recompute_and_persist_quota,
    # so it can never drift upward and stay stuck after clubs/activities
    # are deleted -- see that method's docstring for the history of why
    # this replaced the previous max(stored, computed) logic here.
    quota_result = SyncEngine.recompute_and_persist_quota(clean_id)
    final_clubs = quota_result.get("clubs_approved_count", 0)
    final_support = quota_result.get("support_logs_count", 0)
    quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
    q = next((item for item in quotas if item.get("emp_id", "").strip().upper() == clean_id), {})

    h._send_json({
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
            # R30: honest split — live work vs migrated history baseline
            "live_clubs_approved_count": quota_result.get("live_clubs_approved_count", final_clubs),
            "live_support_logs_count": quota_result.get("live_support_logs_count", final_support),
            # R29v2: the SAME four cells the admin performance matrix
            # shows (online / offline / other + clubs) so the quota
            # card and the matrix can never disagree.
            "live_online_training": quota_result.get("live_online_training", 0),
            "live_offline_training": quota_result.get("live_offline_training", 0),
            "live_other_supports": quota_result.get("live_other_supports", 0),
            "legacy_clubs_count": quota_result.get("legacy_clubs_count", 0),
            "legacy_support_count": quota_result.get("legacy_support_count", 0),
            "legacy_online_workshops_count": quota_result.get("legacy_online_workshops_count", 0),
            "legacy_first_year": (migration_history_summary(str(target.get("id", "")).strip().upper()) or {}).get("first_year"),
            "legacy_last_year": (migration_history_summary(str(target.get("id", "")).strip().upper()) or {}).get("last_year"),
            "last_activity_timestamp": q.get("last_activity_timestamp", "")
        }
    })
    return

# path == "/api/admin/employees"
def get_admin_employees(h, path, query_params):
    if not h._check_admin_access():
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
                # R29: the split halves travel with the row so the roster
                # can label "X live + Y migrated" instead of one blended
                # number (legacy_* = migrated baseline from the worksheets).
                "legacy_clubs_count": int(q.get("legacy_clubs_count", "0") or "0"),
                "legacy_support_count": int(q.get("legacy_support_count", "0") or "0"),
                "legacy_online_workshops_count": int(q.get("legacy_online_workshops_count", "0") or "0"),
                "last_activity_timestamp": q.get("last_activity_timestamp", "")
            })
    h._send_json({"count": len(employees), "employees": employees})
    return

# path == "/api/admin/employees/status"
def post_admin_employees_status(h, path, body):
    if not h._check_admin_access():
        return

    user_id = str(body.get("user_id", "")).strip().upper()
    is_active_val = body.get("is_active", True)
    if not user_id:
        h._send_error("user_id is required.")
        return

    success = AuthService.set_user_status(user_id=user_id, is_active=is_active_val)
    if not success:
        h._send_error(f"User '{user_id}' not found.", status=404)
        return

    status_str = "active" if str(is_active_val).lower() in ["1", "true", "yes"] else "blocked"
    h._send_json({
        "success": True,
        "message": f"User {user_id} status updated to {status_str}.",
        "user_id": user_id,
        "is_active": "1" if status_str == "active" else "0"
    })
    return

# path == "/api/admin/employees/create"
def post_admin_employees_create(h, path, body):
    if not h._check_admin_access():
        return

    emp_id = str(body.get("emp_id", "")).strip().upper()
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", "")).strip()
    full_name = str(body.get("full_name", "")).strip()
    zone = str(body.get("zone", "")).strip()
    assigned_states = str(body.get("assigned_states", "")).strip()

    if not emp_id or not email or not password or not full_name:
        h._send_error("emp_id, email, password, and full_name are required.")
        return

    # Check duplicate ID or email before creation
    existing_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    for u in existing_users:
        if u.get("id", "").strip().upper() == emp_id:
            h._send_error(f"Employee ID '{emp_id}' already exists. Use Edit to modify existing employees.", status=400)
            return
        if u.get("email", "").strip().lower() == email:
            h._send_error(f"Email '{email}' is already in use by another user.", status=400)
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
    h._send_json({
        "success": True,
        "message": f"Employee {emp_id} provisioned with dedicated node database.",
        "employee": {k: v for k, v in user_record.items() if k not in ["password_hash", "salt"]}
    })
    return

# path == "/api/admin/employees/update"
def post_admin_employees_update(h, path, body):
    if not h._check_admin_access():
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
        h._send_error("old_emp_id is required.")
        return
    if not new_emp_id:
        h._send_error("new_emp_id (or emp_id) is required.")
        return
    if not email:
        h._send_error("email is required.")
        return
    if not full_name:
        h._send_error("full_name is required.")
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
        h._send_error(err_msg or "Failed to update employee.", status=400)
        return

    safe_emp = {k: v for k, v in updated_user.items() if k not in ["password_hash", "salt"]}
    h._send_json({
        "success": True,
        "message": f"Employee {new_emp_id} updated successfully and synchronized across node database.",
        "employee": safe_emp
    })
    return
