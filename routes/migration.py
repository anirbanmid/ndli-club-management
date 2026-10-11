"""
routes/migration.py - Bulk import + data migration (the two doors)

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
import re
from auth import AuthService
from config import DEFAULT_ADMIN_EMAIL, MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV
from db.csv_engine import CSVEngine
from db.migration_engine import (
    baselines_for as migration_baselines_for,
    validate_employee_history as migration_validate_history,
    commit_employee_history as migration_commit_history,
    history_grand_totals as migration_grand_totals,
    history_period_years as migration_period_years,
    history_summary as migration_history_summary,
)
from db.schemas import CLUB_FIELDS, normalize_date_fields, validate_club_payload
from db.storage_adapter import get_storage_adapter
from db.sync_engine import SyncEngine

# path in ("/api/clubs/bulk-import/validate", "/api/clubs/bulk-import/commit")
def post_bulk_import(h, path, body):
    commit_mode = path.endswith("/commit")
    emp_id = str(body.get("emp_id", "")).strip().upper()
    if not emp_id:
        h._send_error("emp_id is required.")
        return
    if not h._require_self_or_admin(emp_id):
        return
    if not h._is_employee_active(emp_id):
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Operation not permitted.", status=403)
        return
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        h._send_error("rows must be a non-empty JSON array of club records.", status=400)
        return
    if len(rows) > 200:
        h._send_error("Bulk import is limited to 200 rows per batch. Split the CSV and retry.", status=422)
        return

    results = []
    seen_reg = set()
    seen_cid = set()
    valid_rows = 0
    created = 0
    session = h._get_auth_session()
    for idx, raw in enumerate(rows):
        row = normalize_date_fields(
            {k: str(v or "").strip() for k, v in raw.items()} if isinstance(raw, dict) else {})
        cid = row.get("club_id", "").strip().upper()
        reg_clean = row.get("reg_no", "").strip()
        # R30: optional per-row attribution — the client's club log names
        # the officer per club, so a single migrated file can carry real
        # attribution. Admin-only: employee sessions may only import
        # clubs under their own name.
        row_emp = row.get("approved_by_emp_id", "").strip().upper() or emp_id
        entry = {
            "row": idx + 1,
            "club_id": cid,
            "reg_no": reg_clean,
            "institution_name": row.get("institution_name", ""),
            "approved_by_emp_id": row_emp,
            "status": "error",
            "errors": []
        }
        errors = validate_club_payload(dict(row, emp_id=emp_id, record_mode="new"))
        if row_emp != emp_id and (not session or session.get("role") != "ADMIN"):
            errors.append("Only admins may attribute imported clubs to another employee.")
        elif not h._is_employee_active(row_emp):
            errors.append(f"Attribution employee '{row_emp}' does not exist or is inactive.")
        if cid:
            if cid in seen_cid:
                errors.append(f"Duplicate Club ID '{cid}' earlier in this batch.")
            seen_cid.add(cid)
            if CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", cid, CLUB_FIELDS, copy=False):
                errors.append(f"Club ID '{cid}' already exists in the master database.")
        if reg_clean:
            reg_up = reg_clean.upper()
            if reg_up in seen_reg:
                errors.append(f"Duplicate Registration Number '{reg_clean}' earlier in this batch.")
            seen_reg.add(reg_up)
            _dup = SyncEngine.find_club_by_reg_no(reg_clean)
            if _dup:
                errors.append(
                    f"Registration Number '{reg_clean}' is already approved for club "
                    f"{_dup.get('club_id', '')} — {_dup.get('institution_name', '')}.")
        if errors:
            entry["errors"] = errors
            results.append(entry)
            continue
        entry["status"] = "ready"
        valid_rows += 1
        results.append(entry)

    if not commit_mode:
        h._send_json({
            "success": True,
            "dry_run": True,
            "door": "new_work",
            "total": len(rows),
            "valid": valid_rows,
            "invalid": len(rows) - valid_rows,
            "consequence": (f"{valid_rows} rows will count as NEW WORK (new clubs on the "
                            f"dashboard). Historical/pre-system clubs are refused here — "
                            f"use the Admin Data Migration portal for those."),
            "results": results
        })
        return

    # COMMIT: create each ready row through the standard approval path
    # (record_mode="new" -> record_origin="created": NEW work, counted
    # live) with the per-club durable-sync confirmation deferred to ONE
    # batched pass.
    for entry, raw in zip(results, rows):
        if entry["status"] != "ready":
            continue
        row = normalize_date_fields({k: str(v or "").strip() for k, v in raw.items()})
        row["record_mode"] = "new"
        row_emp = entry.get("approved_by_emp_id") or emp_id
        row["emp_id"] = row_emp
        try:
            created_club = SyncEngine.approve_new_club(
                emp_id=row_emp, club_data=row, confirm_cloud_sync=False)
        except Exception as exc:
            entry["status"] = "error"
            entry["errors"] = [f"Create failed: {exc}"]
            continue
        entry["status"] = "created"
        entry["date_of_approval"] = created_club.get("date_of_approval", "")
        entry["renewal_date"] = created_club.get("renewal_date", "")
        created += 1

    cloud_confirmed = True
    try:
        from db.storage_adapter import get_storage_adapter
        adapter = get_storage_adapter()
        if hasattr(adapter, "confirm_durable"):
            confirm_paths = [
                MASTER_CLUBS_CSV,
                MASTER_ACTIVITIES_CSV,
                MASTER_QUOTAS_CSV,
            ]
            for _e in {e.get("approved_by_emp_id") or emp_id for e in results if e.get("status") == "created"}:
                confirm_paths.append(SyncEngine.get_employee_clubs_path(_e))
                confirm_paths.append(SyncEngine.get_employee_activities_path(_e))
            cloud_confirmed = adapter.confirm_durable(confirm_paths)
    except Exception:
        cloud_confirmed = False

    h._send_json({
        "success": True,
        "dry_run": False,
        "door": "new_work",
        "total": len(rows),
        "created": created,
        "valid": valid_rows,
        "invalid": len(rows) - valid_rows,
        "cloud_sync_confirmed": cloud_confirmed,
        "consequence": f"{created} new clubs recorded as NEW WORK (counted on the dashboard).",
        "results": results
    })
    return

# path in ("/api/admin/migration/clubs/validate", "/api/admin/migration/clubs/commit")
def post_migration_clubs(h, path, body):
    if not h._check_admin_access():
        return
    commit_mode = path.endswith("/commit")
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        h._send_error("rows must be a non-empty JSON array of club records.", status=400)
        return
    if len(rows) > 200:
        h._send_error("Bulk club history import is limited to 200 rows per batch. Split the CSV and retry.", status=422)
        return

    # Dual-layer security (layer 2): Master Admin password re-authentication,
    # mirroring /api/admin/migration/history/commit. Dry-run stays free.
    if commit_mode:
        password = str(body.get("password", "")).strip()
        admin_email = str(body.get("admin_email") or body.get("email") or DEFAULT_ADMIN_EMAIL).strip()
        if not password:
            h._send_error(
                "Master Admin password is required to authorize club history migration.",
                status=401,
            )
            return
        auth_ok, auth_err, user = AuthService.authenticate(admin_email, password)
        if not auth_ok or not user or user.get("role") != "ADMIN":
            h._send_error(
                "Authentication failed: Invalid Master Admin password. Migration aborted.",
                status=403,
            )
            return

    results = []
    seen_reg = set()
    seen_cid = set()
    valid_rows = 0
    created = 0
    per_emp_ready = {}
    for idx, raw in enumerate(rows):
        row = normalize_date_fields(
            {k: str(v or "").strip() for k, v in raw.items()} if isinstance(raw, dict) else {})
        cid = row.get("club_id", "").strip().upper()
        reg_clean = row.get("reg_no", "").strip()
        row_emp = row.get("approved_by_emp_id", "").strip().upper()
        entry = {
            "row": idx + 1,
            "club_id": cid,
            "reg_no": reg_clean,
            "institution_name": row.get("institution_name", ""),
            "approved_by_emp_id": row_emp,
            "status": "error",
            "errors": []
        }
        if not row_emp:
            entry["errors"].append(
                "approved_by_emp_id (the officer who approved this club) is required for each historical club row.")
            results.append(entry)
            continue
        errors = validate_club_payload(dict(row, emp_id=row_emp, record_mode="import"))
        if not h._is_employee_active(row_emp):
            errors.append(f"Attribution employee '{row_emp}' does not exist or is inactive.")
        if cid:
            if cid in seen_cid:
                errors.append(f"Duplicate Club ID '{cid}' earlier in this batch.")
            seen_cid.add(cid)
            if CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", cid, CLUB_FIELDS, copy=False):
                errors.append(f"Club ID '{cid}' already exists in the master database.")
        if reg_clean:
            reg_up = reg_clean.upper()
            if reg_up in seen_reg:
                errors.append(f"Duplicate Registration Number '{reg_clean}' earlier in this batch.")
            seen_reg.add(reg_up)
            _dup = SyncEngine.find_club_by_reg_no(reg_clean)
            if _dup:
                errors.append(
                    f"Registration Number '{reg_clean}' is already approved for club "
                    f"{_dup.get('club_id', '')} — {_dup.get('institution_name', '')}.")
        if errors:
            entry["errors"] = errors
            results.append(entry)
            continue
        entry["status"] = "ready"
        valid_rows += 1
        per_emp_ready[row_emp] = per_emp_ready.get(row_emp, 0) + 1
        results.append(entry)

    # Gap warning: compare uploaded club rows (per officer) against the R30
    # worksheet baselines (master_employee_history approvals) so an incomplete
    # club list is flagged, not silently accepted. e.g. "2,300 rows vs 2,289
    # approved — gap 11". Employees with no worksheet baseline are skipped.
    gap_warnings = []
    for _emp, _cnt in sorted(per_emp_ready.items()):
        _base = migration_baselines_for(_emp) or {}
        _approvals = int(_base.get("approvals", 0) or 0)
        if _approvals and _cnt != _approvals:
            gap_warnings.append(
                f"{_emp}: {_cnt} club rows vs {_approvals} approved in the worksheet — gap {_cnt - _approvals:+d}.")

    consequence = (f"{valid_rows} rows will be saved as HISTORY (counters unchanged). "
                   f"They appear in the Club Register as migrated/imported clubs but add "
                   f"no new-work credit.")

    if not commit_mode:
        h._send_json({
            "success": True,
            "dry_run": True,
            "door": "history",
            "total": len(rows),
            "valid": valid_rows,
            "invalid": len(rows) - valid_rows,
            "consequence": consequence,
            "gap_warnings": gap_warnings,
            "results": results
        })
        return

    # COMMIT: create each ready row through the standard club path with
    # record_mode="import" -> record_origin="imported" (HISTORY, zero live
    # credit). Per-club durable-sync confirm deferred to ONE batched pass.
    for entry, raw in zip(results, rows):
        if entry["status"] != "ready":
            continue
        row = normalize_date_fields({k: str(v or "").strip() for k, v in raw.items()})
        row["record_mode"] = "import"
        row_emp = entry.get("approved_by_emp_id")
        row["emp_id"] = row_emp
        try:
            created_club = SyncEngine.approve_new_club(
                emp_id=row_emp, club_data=row, confirm_cloud_sync=False)
        except Exception as exc:
            entry["status"] = "error"
            entry["errors"] = [f"Create failed: {exc}"]
            continue
        entry["status"] = "created"
        entry["date_of_approval"] = created_club.get("date_of_approval", "")
        entry["renewal_date"] = created_club.get("renewal_date", "")
        created += 1

    # Refresh each touched employee's stored quota so the ratchet left by
    # approve_new_club is replaced with fresh CSV truth (imported rows are
    # excluded from live counts inside recompute, so this keeps the stored
    # quota honest rather than inflated).
    for _e in {e.get("approved_by_emp_id") for e in results if e.get("status") == "created"}:
        try:
            SyncEngine.recompute_and_persist_quota(_e)
        except Exception:
            pass

    cloud_confirmed = True
    try:
        adapter = get_storage_adapter()
        if hasattr(adapter, "confirm_durable"):
            confirm_paths = [MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV]
            for _e in {e.get("approved_by_emp_id") for e in results if e.get("status") == "created"}:
                confirm_paths.append(SyncEngine.get_employee_clubs_path(_e))
                confirm_paths.append(SyncEngine.get_employee_activities_path(_e))
            cloud_confirmed = adapter.confirm_durable(confirm_paths)
    except Exception:
        cloud_confirmed = False

    h._send_json({
        "success": True,
        "dry_run": False,
        "door": "history",
        "total": len(rows),
        "created": created,
        "valid": valid_rows,
        "invalid": len(rows) - valid_rows,
        "cloud_sync_confirmed": cloud_confirmed,
        "consequence": f"{created} rows saved as HISTORY (counters unchanged).",
        "gap_warnings": gap_warnings,
        "results": results
    })
    return

# path in ("/api/admin/migration/history/validate", "/api/admin/migration/history/commit")
def post_migration_history(h, path, body):
    if not h._check_admin_access():
        return
    commit_mode = path.endswith("/commit")
    mig_emp = str(body.get("emp_id", "")).strip().upper()
    csv_text = body.get("csv_text")
    if not mig_emp:
        h._send_error("emp_id is required.")
        return
    if not isinstance(csv_text, str) or not csv_text.strip():
        h._send_error("csv_text (the raw worksheet contents) is required.", status=400)
        return
    # Dual-layer security (layer 2): Master Admin password re-authentication,
    # mirroring /api/admin/data/hard-reset. The dry-run /validate stays
    # password-free (it writes nothing); only /commit persists history, so only
    # /commit requires the Master Admin password.
    if commit_mode:
        password = str(body.get("password", "")).strip()
        admin_email = str(body.get("admin_email") or body.get("email") or DEFAULT_ADMIN_EMAIL).strip()
        if not password:
            h._send_error(
                "Master Admin password is required to authorize history migration.",
                status=401,
            )
            return
        auth_ok, auth_err, user = AuthService.authenticate(admin_email, password)
        if not auth_ok or not user or user.get("role") != "ADMIN":
            h._send_error(
                "Authentication failed: Invalid Master Admin password. Migration aborted.",
                status=403,
            )
            return
    if not commit_mode:
        h._send_json({"success": True,
                         **migration_validate_history(mig_emp, csv_text)})
        return
    result = migration_commit_history(
        mig_emp, csv_text,
        batch_id=str(body.get("batch_id", "") or "").strip(),
        replace=bool(body.get("replace", False)),
        actor=str(body.get("actor", "") or "ADMIN"))
    if not result.get("success"):
        h._send_json(result, status=result.get("status", 422))
        return
    # refresh master_quotas so baseline + live counts show immediately
    SyncEngine.recompute_and_persist_quota(mig_emp)
    h._send_json(result)
    return
