"""db/sync/quota.py - quota derivation + the incremental counter.

R46: SyncEngine methods moved verbatim from db/sync_engine.py.
`class SyncQuotaMixin` is assembled into db.sync_engine.SyncEngine.
Counting rules come from db/counting_rules.py -- never re-implemented here.
"""



from db.migration_engine import baselines_for as _migration_baselines_for

from config import MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV, MASTER_USERS_CSV

from datetime import datetime, timezone

from db import counting_rules

from db.csv_engine import CSVEngine

from db.schemas import CLUB_FIELDS, QUOTA_FIELDS, USER_FIELDS

from typing import Any, Dict



class SyncQuotaMixin:
    """SyncQuotaMixin - SyncEngine methods moved verbatim (R46)."""

    @classmethod
    def recompute_and_persist_quota(cls, emp_id: str) -> Dict[str, Any]:
        """
        THE PERMANENT FIX for quota drift (e.g. an employee's "clubs approved"
        count staying inflated after clubs are deleted, or generally
        disagreeing with the live club count).

        Previous behavior (still present in some call sites) treated
        `clubs_approved_count` as a ratchet: it was only ever incremented
        (_increment_quota), and reconciliation used `max(stored, computed)`,
        which meant the number could climb during testing/cleanup but could
        never come back down -- exactly what caused EMP01 to show 32 while
        the real, live club count was 18.

        This method is the single source of truth going forward: it always
        derives clubs_approved_count and support_logs_count FRESH from the
        current, live clubs.csv/activity_log.csv content (no stored ratchet,
        no max()), and overwrites master_quotas.csv with that truth. Call
        this after ANY operation that changes an employee's clubs or
        activities (create, delete, update) so the stored quota can never
        drift from reality again.
        """
        clean_id = str(emp_id).strip().upper()
        if not clean_id:
            return {}

        users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
        target = next((u for u in users if u.get("id", "").strip().upper() == clean_id), None)

        master_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        master_club_ids = {c.get("club_id", "").strip().upper(): c for c in master_clubs if c.get("club_id")}

        approved_club_ids = set()
        node_clubs_path = cls.get_employee_clubs_path(clean_id)
        if node_clubs_path.exists():
            for c in CSVEngine.read_all(node_clubs_path, CLUB_FIELDS):
                # R30: migrated/imported clubs are history — their performance
                # credit lives in the migrated baseline, never here (the
                # anti-double-count switch: past and present stay separate).
                if counting_rules.is_imported_record(c):
                    continue
                cid = c.get("club_id", "").strip().upper()
                if cid and cid in master_club_ids:
                    c_owner = master_club_ids[cid].get("approved_by_emp_id", "").strip().upper()
                    if not c_owner or c_owner == clean_id:
                        approved_club_ids.add(cid)
        for c in master_clubs:
            if counting_rules.is_imported_record(c):
                continue
            if c.get("approved_by_emp_id", "").strip().upper() == clean_id:
                cid = c.get("club_id", "").strip().upper()
                if cid:
                    approved_club_ids.add(cid)

        combined_acts = cls.combined_activities_for(clean_id)

        club_approval_acts = 0
        live_online = 0
        live_offline = 0
        live_other = 0
        latest_ts = ""
        for a in combined_acts:
            ts = a.get("timestamp", "")
            if ts and ts > latest_ts:
                latest_ts = ts
            # R29v2: the SAME bucketing rule as the performance matrix
            # (SyncEngine.bucket_activity) — "Data Migration" markers are
            # skipped, every other row lands in exactly one bucket.
            bucket = cls.bucket_activity(a)
            if bucket == "skip":
                continue
            if bucket == "approval":
                cid = a.get("club_id", "").strip().upper()
                if cid and cid in master_club_ids:
                    c_owner = master_club_ids[cid].get("approved_by_emp_id", "").strip().upper()
                    if (not counting_rules.is_imported_record(master_club_ids[cid])) and (not c_owner or c_owner == clean_id):
                        approved_club_ids.add(cid)
                        club_approval_acts += 1
            elif bucket == "online":
                live_online += 1
            elif bucket == "offline":
                live_offline += 1
            else:
                live_other += 1
        support_logs = live_online + live_offline + live_other

        # R30: Performance Quota = migrated baseline (immutable history from the
        # client worksheets) + live-derived counts (anti-drift preserved: only
        # the live part is derived here; the baseline lives in
        # master_employee_history.csv and is only written by the migration
        # engine).
        _base = _migration_baselines_for(clean_id)
        live_clubs = len(approved_club_ids)
        live_support = support_logs
        final_clubs = live_clubs + _base["approvals"]
        final_support = live_support + _base["support"]

        q = {
            "emp_id": clean_id,
            "employee_name": (target.get("full_name") if target else None) or clean_id,
            "zone": target.get("zone", "") if target else "",
            "clubs_approved_count": str(final_clubs),
            "support_logs_count": str(final_support),
            "last_activity_timestamp": latest_ts,
            "legacy_clubs_count": str(_base["approvals"]),
            "legacy_support_count": str(_base["support"]),
            "legacy_online_workshops_count": str(_base["online_workshops"]),
        }
        CSVEngine.upsert_row(MASTER_QUOTAS_CSV, QUOTA_FIELDS, "emp_id", q)
        return {
            "clubs_approved_count": final_clubs,
            "support_logs_count": final_support,
            "live_clubs_approved_count": live_clubs,
            "live_support_logs_count": live_support,
            "legacy_clubs_count": _base["approvals"],
            "legacy_support_count": _base["support"],
            "legacy_online_workshops_count": _base["online_workshops"],
            # R29v2: the SAME four numbers the admin performance matrix shows
            # (clubs / online / offline / other) so no two screens can disagree.
            "live_online_training": live_online,
            "live_offline_training": live_offline,
            "live_other_supports": live_other,
        }


    @classmethod
    def _increment_quota(cls, emp_id: str, clubs_inc: int = 0, support_inc: int = 0, now_iso: str = "") -> None:
        """Helper to increment employee quota counters in master_quotas.csv."""
        if not now_iso:
            now_iso = datetime.now(timezone.utc).isoformat()
        quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        found = False
        for q in quotas:
            if q.get("emp_id") == emp_id:
                curr_clubs = int(q.get("clubs_approved_count", "0") or "0")
                curr_support = int(q.get("support_logs_count", "0") or "0")
                q["clubs_approved_count"] = str(curr_clubs + clubs_inc)
                q["support_logs_count"] = str(curr_support + support_inc)
                q["last_activity_timestamp"] = now_iso
                found = True
                break

        if not found:
            quotas.append({
                "emp_id": emp_id,
                "employee_name": f"Employee {emp_id}",
                "zone": "",
                "clubs_approved_count": str(clubs_inc),
                "support_logs_count": str(support_inc),
                "last_activity_timestamp": now_iso
            })

        CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, quotas)

