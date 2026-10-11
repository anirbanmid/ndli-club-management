"""
routes/data_admin.py - Destructive data-admin (hard reset)

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
import app as app_module  # late lookup: tests patch app.<CONST>
import hashlib
import re
from auth import AuthService
from config import DEFAULT_ADMIN_EMAIL
from db.backup_engine import BackupEngine
from db.sync_engine import SyncEngine

# path == "/api/admin/data/hard-reset"
def post_hard_reset(h, path, body):
    if not h._check_admin_access():
        return
    confirm = str(body.get("confirm", "")).strip()
    if confirm != "HARD-RESET-FOR-HANDOVER":
        h._send_error(
            "This is a destructive operation that wipes ALL data except the "
            "provisioned accounts. To proceed, resend with body: "
            '{"confirm": "HARD-RESET-FOR-HANDOVER", "password": "<admin password>", "pin": "<6-digit handover PIN>"}',
            status=400
        )
        return
    # Layer 3 first: a wrong PIN must never reach the checkpoint/wipe
    # stages. Checked against the module-level app_module.HANDOVER_PIN_SHA256 digest.
    pin = str(body.get("pin", "")).strip()
    if not pin or hashlib.sha256(pin.encode("utf-8")).hexdigest() != app_module.HANDOVER_PIN_SHA256:
        h._send_error("Invalid handover PIN. Reset aborted.", status=403)
        return
    # Layer 2: Master Admin password re-authentication (a session alone
    # must never authorize a full data wipe).
    password = str(body.get("password", "")).strip()
    admin_email = str(body.get("admin_email") or body.get("email") or DEFAULT_ADMIN_EMAIL).strip()
    if not password:
        h._send_error(
            "Master Admin password is required to authorize the hard reset.",
            status=401,
        )
        return
    auth_ok, auth_err, user = AuthService.authenticate(admin_email, password)
    if not auth_ok or not user or user.get("role") != "ADMIN":
        h._send_error(
            "Authentication failed: Invalid Master Admin password. Reset aborted.",
            status=403,
        )
        return
    # Safety checkpoint (approved shield): full snapshot before wiping.
    # If the checkpoint cannot be written, abort — never destroy without
    # a net. The handover runbook deletes this archive (and the GDrive
    # backups) as its final step.
    checkpoint = None
    checkpoint_err = ""
    try:
        checkpoint = BackupEngine.create_backup(note="Auto Checkpoint before Hard Reset (handover)")
    except Exception as be:
        checkpoint_err = str(be)
    if not checkpoint or not checkpoint.get("success"):
        h._send_error(
            f"Pre-reset safety checkpoint failed ({checkpoint_err or 'backup engine error'}). "
            "Reset aborted — your current data is untouched.",
            status=500,
        )
        return
    try:
        result = SyncEngine.hard_reset_for_handover()
    except Exception as e:
        h._send_error(f"Error during hard reset: {str(e)}", status=500)
        return
    h._send_json({
        "success": True,
        "message": (
            f"Hard Reset complete: {result['accounts_kept']} accounts kept, "
            f"{result['nodes_wiped']} node databases wiped, "
            f"history wiped: {result['history_wiped']}, "
            f"Robu logs wiped: {result['assistant_logs_wiped']}. "
            "No test data was created — the system is blank and ready for the client. "
            f"Pre-reset checkpoint: {checkpoint.get('backup_id', '')}."
        ),
        **result,
        "checkpoint_backup_id": checkpoint.get("backup_id", ""),
    })
    return
