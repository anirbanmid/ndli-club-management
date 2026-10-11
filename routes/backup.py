"""
routes/backup.py - Backup status / trigger / restore

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from auth import AuthService
from config import DEFAULT_ADMIN_EMAIL
from db.backup_engine import BackupEngine

# path == "/api/admin/backup/status"
def get_backup_status(h, path, query_params):
    if not h._check_admin_access():
        return
    BackupEngine.check_and_run_auto_backup()
    status_data = BackupEngine.get_backup_status()
    h._send_json({"success": True, **status_data})
    return

# path in ["/api/admin/backup/trigger", "/api/admin/backup/create"]
def post_backup_trigger(h, path, body):
    if not h._check_admin_access():
        return
    try:
        note_param = body.get("note", "Manual Admin Trigger")
        res = BackupEngine.create_backup(note=note_param)
        h._send_json(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        h._send_json({
            "success": False,
            "error": True,
            "message": f"Backup operation failed: {str(e)}"
        }, status=500)
    return

# path in ["/api/admin/backup/restore", "/api/admin/backup/emergency-restore"]
def post_backup_restore(h, path, body):
    password = str(body.get("password", "")).strip()
    admin_email = str(body.get("admin_email") or body.get("email") or DEFAULT_ADMIN_EMAIL).strip()

    if not password:
        h._send_error("Master Admin password is required to authorize emergency database restoration.", status=401)
        return

    auth_ok, auth_err, user = AuthService.authenticate(admin_email, password)
    if not auth_ok or not user or user.get("role") != "ADMIN":
        h._send_error("Authentication failed: Invalid Master Admin password. Restoration aborted.", status=403)
        return

    target_source = body.get("source") or body.get("backup_id") or body.get("filename")
    if not target_source:
        existing = BackupEngine.get_existing_backups()
        if existing:
            target_source = str(existing[0])
        else:
            h._send_error("No backup available to restore.", status=400)
            return
    # Round-2 safety: take an undo point BEFORE restoring. A restore is
    # destructive (it replaces live data with an older snapshot); without
    # a pre-restore checkpoint the post-backup data would be unrecoverable.
    checkpoint = None
    try:
        checkpoint = BackupEngine.create_backup(note="Auto Checkpoint before Restore (undo point)")
    except Exception:
        checkpoint = None
    if not checkpoint or not checkpoint.get("success"):
        h._send_error(
            "Pre-restore safety checkpoint failed — restoration aborted so the current "
            "data is never replaced without an undo point.", status=500)
        return
    try:
        res = BackupEngine.restore_backup(target_source)
        res["checkpoint_backup_id"] = checkpoint.get("backup_id", "")
        res["message"] = (
            f"{res.get('message', 'Restoration complete.') } "
            f"Pre-restore checkpoint (undo point): {checkpoint.get('backup_id', '')}."
        )
        h._send_json(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        h._send_json({
            "success": False,
            "error": True,
            "message": f"Restoration failed: {str(e)}"
        }, status=500)
    return
