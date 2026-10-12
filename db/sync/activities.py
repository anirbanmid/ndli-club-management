"""db/sync/activities.py - activity rows: bucketing, combined views, logs.

R46: SyncEngine methods moved verbatim from db/sync_engine.py.
`class SyncActivitiesMixin` is assembled into db.sync_engine.SyncEngine.
`bucket_activity` still delegates to db/counting_rules.py (the single source).
"""



from config import EMPLOYEE_NODES_DIR, MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV

from datetime import datetime, timezone

from db import counting_rules

from db.csv_engine import CSVEngine

from db.schemas import ACTIVITY_FIELDS

from db.sync.state import _SYNC_LOCK

from typing import Any, Dict, List



class SyncActivitiesMixin:
    """SyncActivitiesMixin - SyncEngine methods moved verbatim (R46)."""

    # ------------------------------------------------------------------
    # R29v2: ONE bucketing rule + ONE activity source for EVERY performance
    # view (quota card, admin performance matrix, rebuild sync).
    #
    # Why this exists (the EMP01 "26,663 vs 26,655" mismatch, 2026-10-10):
    # the performance matrix only recognised 5 support_type labels and
    # silently DROPPED every other row ("Registration Renewal",
    # "Data Correction", anything new), while the quota counted every
    # non-approval row -- so rows could be counted in one screen and
    # invisible in the other. The catch-all below makes that impossible:
    # every activity row lands in exactly one visible bucket.
    # ------------------------------------------------------------------
    @staticmethod
    def bucket_activity(a: Dict[str, Any]) -> str:
        """Classify one activity row for performance counting.

        R38: the rule itself lives in db/counting_rules.bucket_activity (the
        single source); this stays as the engine's well-known entry point.
        Returns 'approval' | 'online' | 'offline' | 'other' | 'skip'.
        """
        return counting_rules.bucket_activity(a)


    @classmethod
    def combined_activities_for(cls, emp_id: str = "") -> List[Dict[str, Any]]:
        """The activity rows a performance view may see: the employee node
        log UNION the master log, deduped by activity_id (master wins).

        This is exactly the set recompute_and_persist_quota derives from.
        R29v2: the admin performance matrix reads the SAME set (it used to
        read master-only), so node-vs-master drift can no longer make the
        quota and the matrix disagree.
        """
        clean = str(emp_id).strip().upper()
        master = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        if clean:
            master = [a for a in master
                      if (a.get("emp_id") or "").strip().upper() == clean]
            node_paths = [cls.get_employee_activities_path(clean)]
        else:
            node_paths = []
            if EMPLOYEE_NODES_DIR.exists():
                for emp_dir in sorted(EMPLOYEE_NODES_DIR.iterdir()):
                    p = cls.get_employee_activities_path(emp_dir.name)
                    if p.exists():
                        node_paths.append(p)
        node_rows: List[Dict[str, Any]] = []
        for p in node_paths:
            if p.exists():
                node_rows.extend(CSVEngine.read_all(p, ACTIVITY_FIELDS))
        merged: Dict[str, Dict[str, Any]] = {}
        for a in node_rows + master:
            aid = (a.get("activity_id") or "").strip()
            if aid:
                merged[aid] = a
        return list(merged.values())


    @classmethod
    def log_support_activity(
        cls,
        emp_id: str,
        support_type: str,
        notes: str = "",
        club_id: str = "",
        count: int = 1
    ) -> Dict[str, Any]:
        """
        SEC A: Daily Activity Tracker - Logs nature of support.
        Real-time dual-write to Employee Node activity_log.csv and Master master_activities.csv.
        Supports bulk entry for 'Phone call and remote assistance' only.
        """
        # Bulk entry facility is made available for Phone Call and Remote Assistance only
        if support_type != "Phone call and remote assistance":
            clean_count = 1
        else:
            try:
                clean_count = int(count)
                if clean_count < 1:
                    clean_count = 1
                elif clean_count > 100:
                    clean_count = 100
            except (ValueError, TypeError):
                clean_count = 1

        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()
            ts_base = int(datetime.now(timezone.utc).timestamp() * 1000)

            node_act_path = cls.get_employee_activities_path(emp_id)
            CSVEngine.ensure_file(node_act_path, ACTIVITY_FIELDS)

            activities = []
            for i in range(1, clean_count + 1):
                suffix = f"-{i}" if clean_count > 1 else ""
                activity_id = f"ACT-{emp_id}-{ts_base}{suffix}"

                note_str = notes
                if clean_count > 1:
                    note_str = f"{notes} [Bulk Call {i}/{clean_count}]".strip() if notes else f"[Bulk Phone/Remote Call {i}/{clean_count}]"

                row = {
                    "activity_id": activity_id,
                    "emp_id": emp_id,
                    "timestamp": now_iso,
                    "support_type": support_type,
                    "priority_flag": "0",
                    "club_id": club_id,
                    "notes": note_str
                }
                activities.append(row)
                CSVEngine.append_row(node_act_path, ACTIVITY_FIELDS, row)
                CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, row)

            # Quota update: increment by total clean_count
            cls._increment_quota(emp_id, support_inc=clean_count, now_iso=now_iso)

            ret = dict(activities[0])
            ret["count"] = clean_count
            ret["bulk_count"] = clean_count
            ret["activities_created"] = [a["activity_id"] for a in activities]
            return ret


    @classmethod
    def delete_activity_log_entries(cls, emp_id: str, activity_ids: List[str]) -> Dict[str, Any]:
        """
        Deletes one or more of an employee's own activity log entries
        (single or bulk). If a deleted entry represents a Club Approval,
        the corresponding club is cascade-deleted from both the Master DB
        and the employee's node via delete_club() -- so a club can never be
        left dangling in Clubs/Master CSV after its approval log entry is
        removed, which is exactly the mismatch this feature exists to
        prevent. Plain (non-approval/support) entries are removed directly.

        A single batched Drive confirmation covers every file touched by
        the whole batch, not one confirmation per entry -- see
        hard_reset_for_handover's predecessor (bulk reseed) for why that
        matters once more than a couple of items are involved.
        """
        clean_id = str(emp_id).strip().upper()
        ids_wanted = {str(a).strip() for a in activity_ids if str(a).strip()}
        if not clean_id or not ids_wanted:
            return {"deleted_count": 0, "cascaded_clubs": [], "not_found": sorted(ids_wanted), "results": [], "cloud_sync_confirmed": True}

        with _SYNC_LOCK:
            node_act_path = cls.get_employee_activities_path(clean_id)
            node_acts = CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS) if node_act_path.exists() else []
            # Only entries that actually belong to this employee's own node
            # are eligible -- prevents deleting another employee's log entry
            # by guessing/passing an activity_id that isn't theirs.
            target_acts = [a for a in node_acts if a.get("activity_id", "").strip() in ids_wanted]
            found_ids = {a.get("activity_id", "").strip() for a in target_acts}
            not_found = sorted(ids_wanted - found_ids)

            results = []
            cascaded_clubs = []
            direct_delete_ids = set()

            for a in target_acts:
                aid = a.get("activity_id", "").strip()
                stype = a.get("support_type", "").strip()
                club_id = a.get("club_id", "").strip()
                is_approval = (
                    stype == "Club Approval"
                    or aid.startswith(f"ACT-PRIORITY-{clean_id}")
                )
                if is_approval and club_id:
                    # delete_club() already purges every activity entry
                    # (node + master) referencing this club_id, so this
                    # covers the current entry (and any duplicates) in one go.
                    del_result = cls.delete_club(club_id)
                    cascaded_clubs.append({"club_id": club_id, "deleted": del_result.get("deleted", False)})
                    results.append({
                        "activity_id": aid,
                        "deleted": del_result.get("deleted", False),
                        "cascaded_club_id": club_id if del_result.get("deleted") else None
                    })
                else:
                    direct_delete_ids.add(aid)
                    results.append({"activity_id": aid, "deleted": True, "cascaded_club_id": None})

            # Remove plain (non-approval) entries directly, node + master.
            if direct_delete_ids:
                node_acts_fresh = CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS) if node_act_path.exists() else []
                remaining_node = [a for a in node_acts_fresh if a.get("activity_id", "").strip() not in direct_delete_ids]
                if len(remaining_node) != len(node_acts_fresh):
                    CSVEngine.write_all(node_act_path, ACTIVITY_FIELDS, remaining_node)

                master_acts_fresh = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
                remaining_master = [a for a in master_acts_fresh if a.get("activity_id", "").strip() not in direct_delete_ids]
                if len(remaining_master) != len(master_acts_fresh):
                    CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, remaining_master)

            # Recompute the employee's quota once, after all deletions in
            # this batch -- never incremented/decremented piecemeal.
            cls.recompute_and_persist_quota(clean_id)

            # One batched Drive confirmation for everything this whole
            # operation touched, instead of one confirmation per activity.
            cloud_sync_confirmed = True
            try:
                from db.storage_adapter import get_storage_adapter
                adapter = get_storage_adapter()
                if hasattr(adapter, "confirm_durable"):
                    paths_to_confirm = [
                        MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV,
                        cls.get_employee_clubs_path(clean_id), node_act_path
                    ]
                    cloud_sync_confirmed = adapter.confirm_durable(paths_to_confirm)
            except Exception:
                cloud_sync_confirmed = False

            return {
                "deleted_count": len(direct_delete_ids) + sum(1 for c in cascaded_clubs if c["deleted"]),
                "cascaded_clubs": cascaded_clubs,
                "not_found": not_found,
                "cloud_sync_confirmed": cloud_sync_confirmed,
                "results": results
            }

