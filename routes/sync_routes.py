"""
routes/sync_routes.py - Sync status / reconcile / Drive sync

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
import json
from config import MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV
from db.csv_engine import CSVEngine
from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS
from db.storage_adapter import get_storage_adapter
from db.sync_engine import SyncEngine

# path == "/api/sync/status"
def get_sync_status(h, path, query_params):
    master_clubs = len(CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS))
    master_acts = len(CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS))
    h._send_json({
        "status": "synchronized",
        "master_clubs_count": master_clubs,
        "master_activities_count": master_acts,
        "storage_mode": get_storage_adapter().get_info()["mode"]
    })
    return

# path == "/api/admin/sync-issues"
def get_admin_sync_issues(h, path, query_params):
    if not h._check_admin_access():
        return
    try:
        adapter = get_storage_adapter()
        log_path = adapter.local.root_dir / "sync_issues.log" if hasattr(adapter, "local") else None
        if not log_path or not log_path.exists():
            h._send_json({"success": True, "entries": [], "message": "No sync issues logged yet."})
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
        h._send_json({"success": True, "count": len(entries), "entries": entries})
    except Exception as e:
        h._send_error(f"Error reading sync issues log: {str(e)}", status=500)
    return

# path == "/api/admin/drive/sync-now"
def get_drive_sync_now(h, path, query_params):
    if not h._check_admin_access():
        return
    adapter = get_storage_adapter()
    if hasattr(adapter, "sync_all_now"):
        res = adapter.sync_all_now()
        h._send_json(res)
    else:
        h._send_json({"success": True, "message": "Storage adapter is running in local sync mode.", "info": adapter.get_info()})
    return

# path == "/api/sync/reconcile"
def post_sync_reconcile(h, path, body):
    if not h._check_admin_access():
        return
    summary = SyncEngine.reconcile_all_nodes()
    h._send_json({
        "success": True,
        "message": "Reconciliation completed successfully.",
        "summary": summary
    })
    return

# path == "/api/admin/drive/sync-now"
def post_drive_sync_now(h, path, body):
    if not h._check_admin_access():
        return
    adapter = get_storage_adapter()
    if hasattr(adapter, "sync_all_now"):
        res = adapter.sync_all_now()
        h._send_json(res)
    else:
        h._send_json({"success": True, "message": "Storage adapter is running in local sync mode.", "info": adapter.get_info()})
    return

# path in ("/api/admin/drive/pull-now", "/api/sync/pull-now")
def post_drive_pull_now(h, path, body):
    if not h._check_admin_access():
        return
    adapter = get_storage_adapter()
    if hasattr(adapter, "pull_all_from_drive"):
        res = adapter.pull_all_from_drive()
        if res.get("success"):
            SyncEngine.reconcile_all_nodes()
        h._send_json(res)
    else:
        h._send_json({"success": True, "message": "Storage adapter is running in local sync mode.", "info": adapter.get_info()})
    return
