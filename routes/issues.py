"""
routes/issues.py - Issue tracking

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from db.issue_manager import IssueManager

# path == "/api/issues/employee-reminders"
def get_issues_employee_reminders(h, path, query_params):
    emp_id = query_params.get("emp_id", [""])[0]
    if not emp_id:
        session = h._get_auth_session()
        if session and session.get("role") == "EMPLOYEE":
            emp_id = session.get("user_id", "")
    if not emp_id:
        # Listing reminders across all employees is admin-only
        if not h._check_admin_access():
            return
    elif not h._require_self_or_admin(emp_id):
        return
    reminders = IssueManager.get_employee_reminders(emp_id=emp_id if emp_id else None)
    h._send_json({"success": True, "count": len(reminders), "reminders": reminders})
    return

# path == "/api/issues/admin-reminders"
def get_issues_admin_reminders(h, path, query_params):
    if not h._check_admin_access():
        return
    reminders = IssueManager.get_admin_reminders()
    h._send_json({"success": True, "count": len(reminders), "reminders": reminders})
    return

# path == "/api/issues/list"
def get_issues_list(h, path, query_params):
    if not h._require_session():
        return
    emp_id = query_params.get("emp_id", [""])[0]
    club_id = query_params.get("club_id", [""])[0]
    status_param = query_params.get("status", [""])[0]
    issues = IssueManager.get_issues(emp_id=emp_id or None, club_id=club_id or None, status=status_param or None)
    h._send_json({"success": True, "count": len(issues), "issues": issues})
    return

# path == "/api/issues/details"
def get_issues_details(h, path, query_params):
    issue_id = query_params.get("issue_id", [""])[0] or query_params.get("id", [""])[0]
    if not issue_id:
        h._send_error("issue_id parameter is required.", status=400)
        return
    if not h._require_session():
        return
    issue = IssueManager.get_issue_by_id(issue_id)
    if not issue:
        h._send_error(f"Issue with ID '{issue_id}' not found.", status=404)
        return
    h._send_json({"success": True, "found": True, "issue": issue})
    return

# path == "/api/issues/create"
def post_issues_create(h, path, body):
    club_id = str(body.get("club_id", "")).strip().upper()
    emp_id = str(body.get("emp_id", "")).strip().upper()
    issue_note = str(body.get("issue_note", "")).strip()
    created_at = body.get("created_at")
    reminder_due_at = body.get("reminder_due_at")
    admin_reminder_due_at = body.get("admin_reminder_due_at")

    if not club_id:
        h._send_error("club_id is required.", status=400)
        return
    if not emp_id:
        session = h._get_auth_session()
        if session:
            emp_id = session.get("user_id", "")
    if not emp_id:
        h._send_error("emp_id is required.", status=400)
        return
    if not h._require_self_or_admin(emp_id):
        return
    if not issue_note:
        h._send_error("issue_note (brief note of the issue) is required.", status=400)
        return

    issue = IssueManager.create_issue(
        club_id=club_id,
        emp_id=emp_id,
        issue_note=issue_note,
        created_at=created_at,
        reminder_due_at=reminder_due_at,
        admin_reminder_due_at=admin_reminder_due_at
    )
    h._send_json({
        "success": True,
        "message": f"Unresolved issue logged for {club_id}. Reminder scheduled to appear on dashboard after 72 hours.",
        "issue": issue
    })
    return

# path == "/api/issues/resolve"
def post_issues_resolve(h, path, body):
    issue_id = str(body.get("issue_id", "")).strip()
    status_val = str(body.get("status", "")).strip()
    resolved_by = str(body.get("resolved_by", "")).strip()
    resolution_notes = str(body.get("resolution_notes", "")).strip()
    role_param = str(body.get("role", "")).strip().upper()

    if not issue_id:
        h._send_error("issue_id is required.", status=400)
        return
    if not status_val:
        h._send_error("status ('Resolved' or 'Not Resolved') is required.", status=400)
        return

    session = h._require_session()
    if not session:
        return

    existing_issue = IssueManager.get_issue_by_id(issue_id)
    if not existing_issue:
        h._send_error(f"Issue with ID '{issue_id}' not found.", status=404)
        return
    if session.get("role") != "ADMIN" and str(existing_issue.get("emp_id", "")).strip().upper() != str(session.get("user_id", "")).strip().upper():
        h._send_error("Access denied: you may only resolve your own issues.", status=403)
        return

    if not resolved_by:
        resolved_by = session.get("email") or session.get("user_id", "")

    if not role_param:
        role_param = session.get("role", "").strip().upper()

    updated_issue = IssueManager.resolve_issue(
        issue_id=issue_id,
        status=status_val,
        resolved_by=resolved_by,
        resolution_notes=resolution_notes,
        role=role_param if role_param else None
    )
    if not updated_issue:
        h._send_error(f"Issue with ID '{issue_id}' not found.", status=404)
        return

    is_resolved = updated_issue.get("status") == "Resolved"
    msg = (
        f"Issue {issue_id} marked as Resolved."
        if is_resolved
        else f"Issue {issue_id} marked as Not Resolved. Next reminder scheduled in 7 days."
    )
    h._send_json({
        "success": True,
        "message": msg,
        "issue": updated_issue
    })
    return
