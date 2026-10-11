"""
routes/clubs.py - Club register: search, details, create, update, renew, delete

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from datetime import datetime, timezone
import re
from config import EMPLOYEE_NODES_DIR, MASTER_CLUBS_CSV
from db.backup_engine import BackupEngine
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS, REG_NO_PATTERN, validate_club_payload, validate_historical_dates
from db.sync_engine import SyncEngine, calculate_next_renewal_date, parse_iso_or_date
from state_zone_mapper import get_zone_for_state

# path == "/api/clubs/search"
def get_clubs_search(h, path, query_params):
    if not h._require_session():
        return
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

    h._send_json({"query": query, "count": len(normalized_results), "results": normalized_results, "clubs": normalized_results})
    return

# path == "/api/clubs/details"
def get_clubs_details(h, path, query_params):
    if not h._require_session():
        return
    club_id = query_params.get("club_id", [""])[0] or query_params.get("id", [""])[0]
    clean_cid = club_id.strip().upper()
    if not clean_cid:
        h._send_error("club_id parameter is required.")
        return

    target = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", clean_cid, CLUB_FIELDS)
    if not target and EMPLOYEE_NODES_DIR.exists():
        for emp_dir in EMPLOYEE_NODES_DIR.iterdir():
            if emp_dir.is_dir():
                target = CSVEngine.find_by_key(emp_dir / "clubs.csv", "club_id", clean_cid, CLUB_FIELDS)
                if target:
                    break

    if not target:
        h._send_error(f"Club with ID '{clean_cid}' not found.", status=404)
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

    h._send_json({
        "success": True,
        "found": True,
        "club": c_info
    })
    return

# path == "/api/clubs/create"
def post_clubs_create(h, path, body):
    emp_id = str(body.get("emp_id", "")).strip().upper()
    if not emp_id:
        h._send_error("Approving Employee ID (emp_id) is required.")
        return

    if not h._require_self_or_admin(emp_id):
        return

    if not h._is_employee_active(emp_id):
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
        return

    errors = validate_club_payload(body)
    if errors:
        h._send_json({
            "error": True,
            "validation_errors": errors,
            "message": "Form validation failed. Please correct the highlighted fields."
        }, status=422)
        return

    # BUG-FIX (bughunt): never silently overwrite a club that belongs to
    # ANOTHER employee (previously any employee could hijack an existing
    # club_id and double-log an approval). Same-owner resubmission is kept.
    _existing = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", str(body.get("club_id", "")).strip().upper(), CLUB_FIELDS, copy=False)
    if _existing:
        _owner = str(_existing.get("approved_by_emp_id", "")).strip().upper()
        if _owner and _owner != emp_id:
            h._send_error(
                f"Club ID '{str(body.get('club_id', '')).strip().upper()}' already exists and belongs to {_owner}. "
                f"Use Universal Club Search to edit it.", status=409)
            return

    # Round-2 duplicate-entry checkpoint (client requirement): match the
    # submitted Club ID AND Registration Number against already approved
    # clubs and stop accidental re-entry with a clear warning.
    _reg = str(body.get("reg_no", "")).strip()
    _dup = SyncEngine.find_club_by_reg_no(_reg, exclude_club_id=str(body.get("club_id", "")).strip().upper())
    if _dup:
        h._send_error(
            f"⚠ DUPLICATE ENTRY BLOCKED: Registration Number '{_reg}' is already approved for club "
            f"{_dup.get('club_id', '')} — { _dup.get('institution_name', '') } "
            f"(approved by {_dup.get('approved_by_emp_id', '')}). Please verify the details before "
            f"submitting; if this is the same club, use Universal Club Search to edit it instead.",
            status=409)
        return

    # Auto-map zone if not provided or to ensure strict compliance
    state = str(body.get("state", "")).strip()
    body["zone"] = get_zone_for_state(state) or "Unknown"

    created_club = SyncEngine.approve_new_club(emp_id=emp_id, club_data=body)
    cloud_confirmed = created_club.get("cloud_sync_confirmed", True)
    if cloud_confirmed is True:
        _msg = f"NDLI Club {created_club['club_id']} approved successfully. Cloud sync confirmed."
    elif cloud_confirmed is None:
        # Non-blocking sync mode (PythonAnywhere): saved locally, upload queued.
        _msg = (f"NDLI Club {created_club['club_id']} approved and saved locally. "
                f"Cloud sync queued — the record is safe on this server's disk.")
    else:
        _msg = (f"NDLI Club {created_club['club_id']} saved, but cloud backup "
                f"could not be confirmed. This server has no persistent disk, "
                f"so this record may be lost if the server restarts before the "
                f"sync succeeds. Please notify an administrator and avoid "
                f"relying on this save until confirmed.")
    h._send_json({
        "success": True,
        "message": _msg,
        "cloud_sync_confirmed": cloud_confirmed,
        "club": created_club
    })
    return

# path == "/api/admin/clubs/delete"
def post_admin_clubs_delete(h, path, body):
    if not h._check_admin_access():
        return
    club_id = str(body.get("club_id", "")).strip().upper()
    if not club_id:
        h._send_error("club_id is required.")
        return
    if not CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", club_id, CLUB_FIELDS, copy=False):
        h._send_error(f"Club '{club_id}' not found.", status=404)
        return
    # Safety checkpoint before permanent deletion (master + node + Drive).
    # If the checkpoint cannot be written, abort — never destroy without a net.
    checkpoint = None
    checkpoint_err = ""
    try:
        checkpoint = BackupEngine.create_backup(note=f"Auto Checkpoint before Club Delete ({club_id})")
    except Exception as be:
        checkpoint_err = str(be)
    if not checkpoint or not checkpoint.get("success"):
        h._send_error(
            f"Pre-delete safety checkpoint failed ({checkpoint_err or 'backup engine error'}). "
            f"Delete aborted — club '{club_id}' is untouched.",
            status=500,
        )
        return
    try:
        result = SyncEngine.delete_club(club_id)
    except Exception as e:
        h._send_error(f"Error deleting club: {str(e)}", status=500)
        return
    if not result.get("deleted"):
        h._send_error(result.get("message", f"Club '{club_id}' not found."), status=404)
        return
    h._send_json({
        "success": True,
        "message": f"Club {club_id} permanently deleted (pre-delete checkpoint: {checkpoint.get('backup_id', '')}).",
        **result,
        "checkpoint_backup_id": checkpoint.get("backup_id", ""),
    })
    return

# path == "/api/clubs/update"
def post_clubs_update(h, path, body):
    emp_id = str(body.get("emp_id", "")).strip().upper()
    club_id = str(body.get("club_id", "")).strip().upper()
    if not club_id:
        h._send_error("club_id is required.")
        return

    if emp_id:
        if not h._require_self_or_admin(emp_id):
            return
    elif not h._check_admin_access():
        return

    if emp_id and not h._is_employee_active(emp_id):
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
        return

    # BUG-FIX (bughunt): mass-assignment. Non-admin sessions may only edit
    # descriptive fields; ownership, status, renewal dates and audit fields
    # change only through their dedicated, logged workflows (or by an Admin).
    _sess = h._get_auth_session() or {}
    if _sess.get("role") != "ADMIN":
        _allowed = {"institution_name", "state", "zone", "reg_no",
                    "patron_email", "president_email", "secretary_email"}
        body = {k: v for k, v in body.items() if k in _allowed}

    # R24: historical dates (date_of_approval / last_renewal_date) are
    # immutable on the general club-update path for EVERY role — blank
    # values are ignored silently (existing pinned contract). Corrections
    # go through the dedicated, logged POST /api/clubs/correct-dates
    # workflow (admin-only).
    if _sess.get("role") == "ADMIN":
        _date_touch = [k for k in ("date_of_approval", "last_renewal_date")
                       if str(body.get(k, "") or "").strip()]
        if _date_touch:
            h._send_error(
                "Historical dates cannot be changed via club update "
                f"({', '.join(_date_touch)}). Use POST /api/clubs/correct-dates "
                "(admin-only, logged, validates and recomputes the renewal).",
                status=422)
            return
        body = {k: v for k, v in body.items()
                if k not in ("date_of_approval", "last_renewal_date")}

    # Round-2 duplicate-entry checkpoint: an edited Registration Number
    # must stay unique across approved clubs (and keep its charset).
    _new_reg = str(body.get("reg_no", "")).strip()
    if _new_reg:
        if not REG_NO_PATTERN.match(_new_reg):
            h._send_error(
                "Registration Number may only contain letters, digits, spaces, dots, "
                "underscores, hyphens and slashes (max 64 characters).", status=422)
            return
        _dup = SyncEngine.find_club_by_reg_no(_new_reg, exclude_club_id=club_id)
        if _dup:
            h._send_error(
                f"⚠ DUPLICATE ENTRY BLOCKED: Registration Number '{_new_reg}' is already approved for club "
                f"{_dup.get('club_id', '')} — { _dup.get('institution_name', '') } "
                f"(approved by {_dup.get('approved_by_emp_id', '')}).", status=409)
            return

    updated = SyncEngine.update_club(emp_id=emp_id, club_id=club_id, updated_fields=body)
    if not updated:
        h._send_error(f"Club with ID '{club_id}' not found.", status=404)
        return

    h._send_json({
        "success": True,
        "message": f"Club {club_id} updated successfully.",
        "club": updated
    })
    return

# path == "/api/clubs/correct-dates"
def post_clubs_correct_dates(h, path, body):
    if not h._check_admin_access():
        return
    _sess = h._get_auth_session() or {}
    club_id = str(body.get("club_id", "") or "").strip().upper()
    doa_raw = str(body.get("date_of_approval", "") or "").strip()
    lrd_raw = str(body.get("last_renewal_date", "") or "").strip()
    errors = validate_historical_dates(doa_raw, lrd_raw)
    if not club_id:
        errors.insert(0, "club_id is required.")
    if errors:
        h._send_json({
            "error": True,
            "validation_errors": errors,
            "message": "Date correction validation failed. Please correct the highlighted fields."
        }, status=422)
        return
    updated = SyncEngine.correct_club_dates(
        club_id=club_id,
        date_of_approval=doa_raw,
        last_renewal_date=lrd_raw,
        admin_id=str(_sess.get("user_id", "") or _sess.get("email", ""))
    )
    if not updated:
        h._send_error(f"Club '{club_id}' not found.", status=404)
        return
    h._send_json({
        "success": True,
        "message": (f"Historical dates corrected for {updated.get('institution_name', club_id)}. "
                    f"Upcoming renewal recomputed to {updated.get('renewal_date', '')}."),
        "club": updated
    })
    return

# path == "/api/clubs/renew"
def post_clubs_renew(h, path, body):
    emp_id = str(body.get("emp_id", "")).strip().upper()
    club_id = str(body.get("club_id", "")).strip().upper()
    renewal_date = str(body.get("renewal_date", "")).strip()
    last_renewal_date = str(body.get("last_renewal_date", "")).strip()

    if not emp_id or not club_id:
        h._send_error("emp_id and club_id are required.")
        return

    if not h._require_self_or_admin(emp_id):
        return

    if not h._is_employee_active(emp_id):
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
        return

    updated = SyncEngine.renew_club_registration(
        emp_id=emp_id,
        club_id=club_id,
        renewal_date=renewal_date if renewal_date else None,
        last_renewal_date=last_renewal_date if last_renewal_date else None
    )
    if not updated:
        h._send_error(f"Club with ID '{club_id}' not found.", status=404)
        return

    if updated.get("renewal_duplicate_skipped"):
        h._send_json({
            "success": True,
            "message": (f"Renewal for club {club_id} was already recorded moments ago — "
                        f"duplicate click ignored, no extra renewal activity logged."),
            "renewal_duplicate_skipped": True,
            "club": updated
        })
        return

    final_renewal_date = updated.get("renewal_date", renewal_date)
    final_last_renewal = updated.get("last_renewal_date", "")
    h._send_json({
        "success": True,
        "message": f"Renewal Approved for club {club_id}. Last Renewal Date logged as {final_last_renewal}, upcoming renewal valid until {final_renewal_date}.",
        "club": updated
    })
    return
