"""db/sync/maintenance.py - handover reset, training wipe, node reconciliation.

R46: SyncEngine methods moved verbatim from db/sync_engine.py.
`class SyncMaintenanceMixin` is assembled into db.sync_engine.SyncEngine.
"""



from config import DATA_DIR, EMPLOYEE_NODES_DIR, MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_ISSUES_CSV, MASTER_QUOTAS_CSV, MASTER_USERS_CSV

from datetime import datetime, timezone

from db.csv_engine import CSVEngine

from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS, ISSUE_FIELDS, QUOTA_FIELDS, USER_FIELDS

from db.sync.dates import calculate_next_renewal_date, parse_iso_or_date

from db.sync.state import _SYNC_LOCK

from pathlib import Path

from state_zone_mapper import get_zone_for_state

from typing import Any, Dict



class SyncMaintenanceMixin:
    """SyncMaintenanceMixin - SyncEngine methods moved verbatim (R46)."""

    @classmethod
    def hard_reset_for_handover(cls) -> Dict[str, Any]:
        """
        HARD RESET (HANDOVER): wipe ALL application data down to a
        blank-but-provisioned state so the system can be handed to the client,
        who then starts entering from zero.

        Preserved (the provisioned skeleton — the client keeps these and
        changes the passwords later):
          * master_users.csv  — the Master Admin + the 7 Nodal Officer accounts
          * every node's credentials.csv — officer login credentials

        Wiped (headers-only CSVs / truncated logs):
          * master: clubs, activities, quotas (incl. migrated-history
            baselines), issues, employee history (master_employee_history.csv)
          * every node dir: clubs.csv, activity_log.csv, issues.csv
          * Robu's data logs: assistant_interactions / assistant_preferences /
            assistant_feedback (his capabilities live in code + the manual KB,
            never in these logs, so this cannot degrade him)
          * sync_issues.log
          * R35: both PPT training decks (data/training/)

        NO reseed of any kind: no test clubs, no quotas. This intentionally
        replaces the old `reset_all_and_reseed` ("Reset Test Data") semantics.
        """
        with _SYNC_LOCK:
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            accounts_kept = sum(1 for u in users if u.get("id", "").strip())

            # 1. Wipe master data CSVs (headers only).
            #    master_users.csv is NEVER touched here.
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, [])
            CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, [])
            CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, [])
            CSVEngine.write_all(MASTER_ISSUES_CSV, ISSUE_FIELDS, [])

            # 2. Wipe the migrated-history baselines — nothing survives the
            #    handover (client-confirmed 2026-10-11).
            history_wiped = False
            try:
                from db.migration_engine import MASTER_HISTORY_CSV
                from db.schemas import MIGRATION_HISTORY_FIELDS
                CSVEngine.write_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS, [])
                history_wiped = True
            except Exception:
                history_wiped = False

            # 3. Wipe every node dir: clubs + activity_log + issues.
            #    credentials.csv is NEVER touched. Iterating the actual node
            #    directories (not just emp_ids) also clears artifacts of
            #    historical bugs (e.g. a stray admin01 node).
            nodes_wiped = 0
            if EMPLOYEE_NODES_DIR.exists():
                for node_dir in EMPLOYEE_NODES_DIR.iterdir():
                    if not node_dir.is_dir():
                        continue
                    for _name, _fields in (("clubs.csv", CLUB_FIELDS),
                                           ("activity_log.csv", ACTIVITY_FIELDS),
                                           ("issues.csv", ISSUE_FIELDS)):
                        _p = node_dir / _name
                        if _p.exists():
                            CSVEngine.write_all(_p, _fields, [])
                    nodes_wiped += 1

            # 4. Wipe Robu's data logs (interactions / preferences / feedback)
            #    and the sync failure log. Each file is reduced to its own
            #    existing header row (schema preserved, rows gone).
            def _header_only(path: Path) -> bool:
                if not path.exists():
                    return True
                try:
                    first = path.read_text(encoding="utf-8").splitlines()[:1]
                    path.write_text(("\n".join(first) + "\n") if first else "", encoding="utf-8")
                    return True
                except Exception:
                    return False

            try:
                from ai.assistant_learning import (
                    ASSISTANT_INTERACTIONS_CSV,
                    ASSISTANT_PREFERENCES_CSV,
                    ASSISTANT_FEEDBACK_CSV,
                )
                assistant_logs_wiped = all([
                    _header_only(Path(ASSISTANT_INTERACTIONS_CSV)),
                    _header_only(Path(ASSISTANT_PREFERENCES_CSV)),
                    _header_only(Path(ASSISTANT_FEEDBACK_CSV)),
                ])
            except Exception:
                assistant_logs_wiped = False

            #    sync_issues.log is a plain log (no header) — truncate it fully.
            sync_log_path = DATA_DIR / "sync_issues.log"
            sync_log_wiped = True
            try:
                if sync_log_path.exists():
                    sync_log_path.write_text("", encoding="utf-8")
            except Exception:
                sync_log_wiped = False

            # 5. R35 tie-in: the two training decks do NOT survive the handover
            #    (nothing but the provisioned accounts does — client re-uploads).
            training = cls.wipe_training_slots()

            return {
                "accounts_kept": accounts_kept,
                "nodes_wiped": nodes_wiped,
                "history_wiped": history_wiped,
                "assistant_logs_wiped": assistant_logs_wiped,
                "sync_log_wiped": sync_log_wiped,
                "training_slots_wiped": training.get("training_slots_wiped", 0),
                "reseeded": False,
            }


    @staticmethod
    def wipe_training_slots() -> Dict[str, Any]:
        """
        Hard-reset helper (R35): remove both PPT training decks and their
        metadata — the training library never survives the handover.
        """
        removed = []
        tdir = DATA_DIR / "training"
        if tdir.exists():
            for f in tdir.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        removed.append(f.name)
                    except Exception:
                        pass
        return {"training_slots_wiped": len(removed)}


    @classmethod
    def reconcile_all_nodes(cls) -> Dict[str, int]:
        """
        Reconciles the Master Database from all Employee Node databases bi-directionally.
        - Synchronizes clubs and activities between master and employee nodes.
        - Automatically heals any missing or empty zones using state_zone_mapper.
        - Accurately recomputes quota performance (clubs approved vs support activities)
          ensuring club approvals recorded in activity logs are never lost or zeroed out.
        """
        with _SYNC_LOCK:
            cls.initialize_storage_hierarchy()
            all_clubs: Dict[str, Dict[str, str]] = {}
            all_activities: Dict[str, Dict[str, str]] = {}

            # 1. Read and heal all existing master clubs
            for c in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS):
                cid = c.get("club_id", "").strip().upper()
                if cid:
                    st = c.get("state", "").strip()
                    zn = c.get("zone", "").strip()
                    if not zn or zn == "Unknown":
                        zn = get_zone_for_state(st) or "Unknown"
                    c["zone"] = zn

                    doa = c.get("date_of_approval", "").strip() or c.get("submission_timestamp", "").strip()
                    lrd = c.get("last_renewal_date", "").strip()
                    ren = c.get("renewal_date", "").strip() or c.get("next_renewal_date", "").strip()

                    parsed_ren = parse_iso_or_date(ren)
                    parsed_doa = parse_iso_or_date(doa)
                    if parsed_ren and not lrd:
                        if not parsed_doa or parsed_doa >= parsed_ren:
                            try:
                                derived = parsed_ren.replace(year=parsed_ren.year - 1)
                            except ValueError:
                                derived = parsed_ren.replace(year=parsed_ren.year - 1, month=2, day=28)
                            doa = f"{derived.isoformat()}T10:00:00Z"

                    ren = calculate_next_renewal_date(date_of_approval=doa, last_renewal_date=lrd, renewal_date=ren)
                    c["date_of_approval"] = doa
                    c["submission_timestamp"] = doa
                    c["last_renewal_date"] = lrd
                    c["renewal_date"] = ren
                    c["next_renewal_date"] = ren
                    all_clubs[cid] = c

            # 2. Read existing master activities
            for a in CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS):
                aid = a.get("activity_id", "").strip()
                if aid:
                    all_activities[aid] = a

            # 3. Scan all employee node folders
            synced_emp_ids = set()
            if EMPLOYEE_NODES_DIR.exists():
                for emp_dir in EMPLOYEE_NODES_DIR.iterdir():
                    if not emp_dir.is_dir():
                        continue
                    emp_id = emp_dir.name.upper()
                    synced_emp_ids.add(emp_id)

                    # Read node clubs
                    node_clubs_path = emp_dir / "clubs.csv"
                    cls._migrate_club_csv_headers(node_clubs_path)
                    for c in CSVEngine.read_all(node_clubs_path, CLUB_FIELDS):
                        cid = c.get("club_id", "").strip().upper()
                        if cid:
                            st = c.get("state", "").strip()
                            zn = c.get("zone", "").strip()
                            if not zn or zn == "Unknown":
                                zn = get_zone_for_state(st) or "Unknown"
                            c["zone"] = zn

                            if not c.get("approved_by_emp_id"):
                                c["approved_by_emp_id"] = emp_id

                            doa = c.get("date_of_approval", "").strip() or c.get("submission_timestamp", "").strip()
                            lrd = c.get("last_renewal_date", "").strip()
                            ren = c.get("renewal_date", "").strip() or c.get("next_renewal_date", "").strip()

                            if cid in all_clubs:
                                if not doa and all_clubs[cid].get("date_of_approval"):
                                    doa = all_clubs[cid]["date_of_approval"]
                                if not lrd and all_clubs[cid].get("last_renewal_date"):
                                    lrd = all_clubs[cid]["last_renewal_date"]

                            parsed_ren = parse_iso_or_date(ren)
                            parsed_doa = parse_iso_or_date(doa)
                            if parsed_ren and not lrd:
                                if not parsed_doa or parsed_doa >= parsed_ren:
                                    try:
                                        derived = parsed_ren.replace(year=parsed_ren.year - 1)
                                    except ValueError:
                                        derived = parsed_ren.replace(year=parsed_ren.year - 1, month=2, day=28)
                                    doa = f"{derived.isoformat()}T10:00:00Z"

                            ren = calculate_next_renewal_date(date_of_approval=doa, last_renewal_date=lrd, renewal_date=ren)

                            c["date_of_approval"] = doa
                            c["submission_timestamp"] = doa
                            c["last_renewal_date"] = lrd
                            c["renewal_date"] = ren
                            c["next_renewal_date"] = ren

                            if cid not in all_clubs or (c.get("updated_at", "") >= all_clubs[cid].get("updated_at", "")):
                                all_clubs[cid] = c

                    # Read node activities
                    node_act_path = emp_dir / "activity_log.csv"
                    for a in CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS):
                        aid = a.get("activity_id", "").strip()
                        if aid:
                            all_activities[aid] = a

            # Ensure all employee users from master_users.csv are included in synced_emp_ids
            master_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            for u in master_users:
                if u.get("role") == "EMPLOYEE":
                    uid = u.get("id", "").strip().upper()
                    if uid:
                        synced_emp_ids.add(uid)

            # 4. Infer club approvals and link clubs from activities
            for a in all_activities.values():
                stype = a.get("support_type", "").strip()
                aid = a.get("activity_id", "").strip()
                a_emp = a.get("emp_id", "").strip().upper()
                is_club_approval = (
                    stype == "Club Approval"
                    or aid.startswith(f"ACT-PRIORITY-{a_emp}")
                )
                if is_club_approval:
                    cid = a.get("club_id", "").strip().upper()
                    if cid and cid in all_clubs:
                        if not all_clubs[cid].get("approved_by_emp_id"):
                            all_clubs[cid]["approved_by_emp_id"] = a_emp

            # Ensure every club in all_clubs is assigned to an employee
            master_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            employee_ids = {u.get("id", "").strip().upper()
                            for u in master_users if u.get("role", "").strip().upper() == "EMPLOYEE"}
            zone_to_emp = {u.get("zone", "").strip(): u.get("id", "").strip().upper() 
                           for u in master_users if u.get("role") == "EMPLOYEE" and u.get("zone")}
            for cid, c in all_clubs.items():
                owner = (c.get("approved_by_emp_id") or "").strip().upper()
                # Reassign missing owners AND owners that are not real employees
                # (e.g. ADMIN01 seeding artifacts): every master club must belong
                # to an employee so that Sum(clubs_approved_count) strictly equals
                # the master total club count (no employee-vs-admin count drift).
                if not owner or owner not in employee_ids:
                    c_zn = c.get("zone", "").strip() or get_zone_for_state(c.get("state", "").strip())
                    c["approved_by_emp_id"] = zone_to_emp.get(c_zn, "EMP01")

            # 4b. Clean and deduplicate Club Approval activities:
            # - Purge orphan approval activities for clubs that DO NOT EXIST in all_clubs (e.g. deleted clubs)
            # - Purge approval activities with no club_id (phantoms)
            # - Keep only the earliest approval activity per club_id
            # - Ensure the approval activity's emp_id matches the club's approved_by_emp_id
            orphan_or_dup_ids = set()
            approval_by_club: Dict[str, Dict[str, str]] = {}
            for aid, a in list(all_activities.items()):
                stype = a.get("support_type", "").strip()
                a_emp = a.get("emp_id", "").strip().upper()
                cid = a.get("club_id", "").strip().upper()
                is_club_approval = (
                    stype == "Club Approval"
                    or aid.startswith(f"ACT-PRIORITY-{a_emp}")
                )
                if not is_club_approval:
                    continue
                # If club_id is missing or points to a club that no longer exists in all_clubs:
                # It is an orphan/phantom activity for a deleted or non-existent club!
                if not cid or cid not in all_clubs:
                    orphan_or_dup_ids.add(aid)
                    continue

                # Align activity emp_id with the club's true owner
                correct_emp = all_clubs[cid].get("approved_by_emp_id", "").strip().upper() or a_emp
                a["emp_id"] = correct_emp
                a["club_id"] = cid

                existing = approval_by_club.get(cid)
                if existing is None:
                    approval_by_club[cid] = a
                else:
                    existing_ts = existing.get("timestamp", "")
                    this_ts = a.get("timestamp", "")
                    if this_ts and (not existing_ts or this_ts < existing_ts):
                        orphan_or_dup_ids.add(existing.get("activity_id", "").strip())
                        approval_by_club[cid] = a
                    else:
                        orphan_or_dup_ids.add(aid)

            for bad_id in orphan_or_dup_ids:
                all_activities.pop(bad_id, None)

            # 4c. Ensure every club in all_clubs has a matching Club Approval activity log entry
            now_iso = datetime.now(timezone.utc).isoformat()
            for cid, c in all_clubs.items():
                if cid not in approval_by_club:
                    c_emp = c.get("approved_by_emp_id", "").strip().upper()
                    doa = c.get("date_of_approval", "").strip() or c.get("submission_timestamp", "").strip() or now_iso
                    auto_aid = f"ACT-PRIORITY-{c_emp}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
                    new_act = {
                        "activity_id": auto_aid,
                        "emp_id": c_emp,
                        "timestamp": doa,
                        "support_type": "Club Approval",
                        "priority_flag": "1",
                        "club_id": cid,
                        "notes": f"Approved new NDLI Club: {c.get('institution_name', '')} ({cid})"
                    }
                    all_activities[auto_aid] = new_act
                    approval_by_club[cid] = new_act

            # 5. Bi-directional sync back to employee nodes
            for emp_id in synced_emp_ids:
                emp_dir = cls.get_employee_dir(emp_id)
                emp_dir.mkdir(parents=True, exist_ok=True)

                # Clubs belonging to this employee
                node_clubs_path = emp_dir / "clubs.csv"
                emp_clubs = [c for c in all_clubs.values() if c.get("approved_by_emp_id", "").strip().upper() == emp_id]
                CSVEngine.write_all(node_clubs_path, CLUB_FIELDS, emp_clubs)

                # Activities belonging to this employee
                node_act_path = emp_dir / "activity_log.csv"
                node_acts = [a for a in all_activities.values() if a.get("emp_id", "").strip().upper() == emp_id]
                node_acts.sort(key=lambda x: x.get("timestamp", ""))
                CSVEngine.write_all(node_act_path, ACTIVITY_FIELDS, node_acts)

                # Ensure node credentials and issues files exist
                cred_path = cls.get_employee_credentials_path(emp_id)
                CSVEngine.ensure_file(cred_path, USER_FIELDS)
                issues_path = cls.get_employee_issues_path(emp_id)
                CSVEngine.ensure_file(issues_path, ISSUE_FIELDS)

            # 6. Write master clubs and master activities
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, list(all_clubs.values()))
            sorted_acts = sorted(all_activities.values(), key=lambda x: x.get("timestamp", ""))
            CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, sorted_acts)

            # 7. Recompute quotas accurately for all employees
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            quota_by_id = {q["emp_id"].strip().upper(): q for q in quotas if q.get("emp_id")}

            # Also ensure all officers from master users are represented in quotas
            for u in master_users:
                if u.get("role") == "EMPLOYEE":
                    uid = u.get("id", "").strip().upper()
                    if uid and uid not in quota_by_id:
                        quota_by_id[uid] = {
                            "emp_id": uid,
                            "employee_name": u.get("full_name") or uid,
                            "zone": u.get("zone", ""),
                            "clubs_approved_count": "0",
                            "support_logs_count": "0",
                            "last_activity_timestamp": ""
                        }

            for emp_id in quota_by_id:
                # R29v2: quotas are ALWAYS derived by the one true method
                # (recompute_and_persist_quota = live node∪master union +
                # migrated baseline). The old inline count here mixed
                # "Data Migration" marker rows into support and wrote
                # live-only totals over the baseline columns, so quota rows
                # read straight from master_quotas.csv could disagree with
                # every screen that derives fresh numbers -- exactly the
                # class of bug behind the EMP01 26,663-vs-26,655 mismatch.
                cls.recompute_and_persist_quota(emp_id)

            return {
                "total_master_clubs": len(all_clubs),
                "total_master_activities": len(all_activities),
                "employees_synced": len(synced_emp_ids)
            }

