"""
routes/activity.py - Activity log: list, log, delete

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from config import MASTER_ACTIVITIES_CSV
from db.csv_engine import CSVEngine
from db.schemas import ACTIVITY_FIELDS
from db.sync_engine import SyncEngine

# path == "/api/activity/list"
def get_activity_list(h, path, query_params):
    if not h._require_session():
        return
    emp_id = query_params.get("emp_id", [""])[0]
    if emp_id:
        node_act_path = SyncEngine.get_employee_activities_path(emp_id)
        acts = CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS)
    else:
        acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
    h._send_json({"count": len(acts), "activities": list(reversed(acts))})
    return

# path == "/api/activity/log"
def post_activity_log(h, path, body):
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
        h._send_error("Employee ID (emp_id) is required.")
        return
    if not support_type:
        h._send_error("Support type is required.")
        return

    if not h._require_self_or_admin(emp_id):
        return

    if not h._is_employee_active(emp_id):
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
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
    h._send_json({
        "success": True,
        "message": msg,
        "count": count,
        "activity": act_row
    })
    return

# path == "/api/employee/activity/delete"
def post_activity_delete(h, path, body):
    emp_id = str(body.get("emp_id", "")).strip().upper()
    activity_ids = body.get("activity_ids")
    if not activity_ids and body.get("activity_id"):
        activity_ids = [body.get("activity_id")]
    if not emp_id or not activity_ids:
        h._send_error("emp_id and activity_ids (or activity_id) are required.", status=400)
        return

    # Identity check: the authenticated session must belong to this
    # same employee (or be an admin) -- this is a destructive,
    # employee-scoped operation, not something any valid emp_id in
    # the body alone should be able to trigger.
    session = h._get_auth_session()
    if not session:
        h._send_error("Authentication required to delete activity log entries.", status=401)
        return
    session_id = str(session.get("user_id", "")).strip().upper()
    if session.get("role") != "ADMIN" and session_id != emp_id:
        h._send_error("You may only delete your own activity log entries.", status=403)
        return

    if not h._is_employee_active(emp_id):
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
        return

    try:
        result = SyncEngine.delete_activity_log_entries(emp_id, activity_ids)
    except Exception as e:
        h._send_error(f"Error deleting activity log entries: {str(e)}", status=500)
        return

    cascaded_count = sum(1 for c in result["cascaded_clubs"] if c["deleted"])
    msg = f"{result['deleted_count']} activity log entr{'y' if result['deleted_count'] == 1 else 'ies'} deleted"
    if cascaded_count:
        msg += f", including {cascaded_count} club{'s' if cascaded_count != 1 else ''} cascade-deleted from Master DB"
    if result["not_found"]:
        msg += f". {len(result['not_found'])} activity ID(s) were not found in your node log."
    else:
        msg += "."

    h._send_json({
        "success": True,
        "message": msg,
        **result
    })
    return
