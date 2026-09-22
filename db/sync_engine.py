"""
NDLI Club Management - Real-Time Synchronization Engine
Maintains synchronization between Employee Node CSVs and Master CSVs.
"""
import os
import shutil
import threading
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from config import (
    DATA_DIR,
    MASTER_USERS_CSV,
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_QUOTAS_CSV,
    MASTER_ISSUES_CSV,
    EMPLOYEE_NODES_DIR,
    BACKUP_DIR
)
from db.schemas import (
    USER_FIELDS,
    CLUB_FIELDS,
    ACTIVITY_FIELDS,
    QUOTA_FIELDS,
    ISSUE_FIELDS
)
from db.csv_engine import CSVEngine
from state_zone_mapper import get_zone_for_state

_SYNC_LOCK = threading.RLock()


def parse_iso_or_date(val: Any) -> Optional[date]:
    """Safely extracts a calendar date object from an ISO string, date string, or timestamp."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s == "-":
        return None
    clean = s.split("T")[0].split(" ")[0].strip()
    # Fast-path for standard ISO date: YYYY-MM-DD
    if len(clean) == 10 and clean[4] == '-' and clean[7] == '-':
        try:
            return date(int(clean[0:4]), int(clean[5:7]), int(clean[8:10]))
        except ValueError:
            pass
    # Fast-path for DD-MM-YYYY
    if len(clean) == 10 and clean[2] == '-' and clean[5] == '-':
        try:
            return date(int(clean[6:10]), int(clean[3:5]), int(clean[0:2]))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        pass
    return None


def calculate_next_renewal_date(
    establishment_date: Optional[str] = None,
    last_renewal_date: Optional[str] = None,
    date_of_approval: Optional[str] = None,
    renewal_date: Optional[str] = None
) -> str:
    """
    Computes the upcoming renewal date as exactly 1 calendar year (+1 year) from
    the last renewal date (if renewed) or the date of approval / establishment date.
    If renewal_date is supplied, ensures that upcoming renewal date can NEVER be
    earlier than date_of_approval or last_renewal_date. If renewal_date is earlier,
    recalculates it as 1 calendar year (+1 year) from the latest approval / renewal date.
    If neither date is provided or valid, defaults to 1 year from current UTC date.
    """
    ren_d = parse_iso_or_date(last_renewal_date)
    est_d = parse_iso_or_date(date_of_approval) if date_of_approval else parse_iso_or_date(establishment_date)

    latest_date: Optional[date] = None
    if ren_d and est_d:
        latest_date = max(est_d, ren_d)
    elif ren_d:
        latest_date = ren_d
    elif est_d:
        latest_date = est_d
    else:
        latest_date = datetime.now(timezone.utc).date()

    try:
        computed_next = latest_date.replace(year=latest_date.year + 1)
    except ValueError:
        # Handles Feb 29 leap year rollover: strictly Feb 28 of following year
        computed_next = latest_date.replace(year=latest_date.year + 1, month=2, day=28)

    if renewal_date:
        parsed_prop = parse_iso_or_date(renewal_date)
        if parsed_prop:
            # An upcoming renewal date can NEVER be earlier than date_of_approval or last_renewal_date
            if latest_date and parsed_prop <= latest_date:
                return computed_next.isoformat()
            return parsed_prop.isoformat()

    return computed_next.isoformat()


class SyncEngine:
    """Manages transactional updates and reconciliation between employee nodes and master DB."""

    @staticmethod
    def get_employee_dir(emp_id: str) -> Path:
        """Returns the base directory for an employee's node database."""
        clean_id = os.path.basename(str(emp_id).strip().lower())
        target = (EMPLOYEE_NODES_DIR / clean_id).resolve()
        if not target.is_relative_to(EMPLOYEE_NODES_DIR.resolve()):
            raise ValueError(f"Directory traversal detected in employee ID: {emp_id}")
        return target

    @staticmethod
    def get_employee_credentials_path(emp_id: str) -> Path:
        return SyncEngine.get_employee_dir(emp_id) / "credentials.csv"

    @staticmethod
    def get_employee_clubs_path(emp_id: str) -> Path:
        return SyncEngine.get_employee_dir(emp_id) / "clubs.csv"

    @staticmethod
    def get_employee_activities_path(emp_id: str) -> Path:
        return SyncEngine.get_employee_dir(emp_id) / "activity_log.csv"

    @staticmethod
    def get_employee_issues_path(emp_id: str) -> Path:
        return SyncEngine.get_employee_dir(emp_id) / "issues.csv"

    @classmethod
    def _migrate_club_csv_headers(cls, file_path: Path) -> None:
        """Ensures club CSV has the latest CLUB_FIELDS headers and populates date_of_approval/last_renewal_date."""
        if not file_path.exists() or file_path.stat().st_size == 0:
            CSVEngine.ensure_file(file_path, CLUB_FIELDS)
            return
        rows = CSVEngine.read_all(file_path)
        migrated_rows = []
        for r in rows:
            doa = str(r.get("date_of_approval", "")).strip() or str(r.get("submission_timestamp", "")).strip()
            lrd = str(r.get("last_renewal_date", "")).strip()
            ren = str(r.get("renewal_date", "")).strip() or str(r.get("next_renewal_date", "")).strip()

            parsed_ren = parse_iso_or_date(ren)
            parsed_doa = parse_iso_or_date(doa)

            # Fix historical/benchmark clubs where date_of_approval was mistakenly stamped
            # with runtime date (> renewal_date) for an unrenewed overdue club
            if parsed_ren and not lrd:
                if not parsed_doa or parsed_doa >= parsed_ren:
                    try:
                        derived = parsed_ren.replace(year=parsed_ren.year - 1)
                    except ValueError:
                        derived = parsed_ren.replace(year=parsed_ren.year - 1, month=2, day=28)
                    doa = f"{derived.isoformat()}T10:00:00Z"

            if not doa and r.get("updated_at"):
                doa = str(r.get("updated_at")).strip()

            ren = calculate_next_renewal_date(date_of_approval=doa, last_renewal_date=lrd, renewal_date=ren)
            r["date_of_approval"] = doa
            r["submission_timestamp"] = doa
            r["last_renewal_date"] = lrd
            r["renewal_date"] = ren
            r["next_renewal_date"] = ren
            migrated_rows.append(r)
        CSVEngine.write_all(file_path, CLUB_FIELDS, migrated_rows)

    @classmethod
    def initialize_storage_hierarchy(cls) -> None:
        """Creates directory trees, migrates schemas, and initializes headers for all master files."""
        with _SYNC_LOCK:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            CSVEngine.ensure_file(MASTER_USERS_CSV, USER_FIELDS)
            cls._migrate_club_csv_headers(MASTER_CLUBS_CSV)
            CSVEngine.ensure_file(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            CSVEngine.ensure_file(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            CSVEngine.ensure_file(MASTER_ISSUES_CSV, ISSUE_FIELDS)

    @classmethod
    def provision_employee_node(
        cls,
        emp_id: str,
        email: str,
        password_hash: str,
        salt: str,
        full_name: str,
        zone: str,
        assigned_states: str,
        is_active: str = "1",
        created_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates the dedicated node directory and CSVs for an employee,
        and registers them in both the node and master credentials database.
        """
        with _SYNC_LOCK:
            cls.initialize_storage_hierarchy()
            emp_dir = cls.get_employee_dir(emp_id)
            emp_dir.mkdir(parents=True, exist_ok=True)

            cred_path = cls.get_employee_credentials_path(emp_id)
            clubs_path = cls.get_employee_clubs_path(emp_id)
            act_path = cls.get_employee_activities_path(emp_id)
            issues_path = cls.get_employee_issues_path(emp_id)

            CSVEngine.ensure_file(cred_path, USER_FIELDS)
            CSVEngine.ensure_file(clubs_path, CLUB_FIELDS)
            CSVEngine.ensure_file(act_path, ACTIVITY_FIELDS)
            CSVEngine.ensure_file(issues_path, ISSUE_FIELDS)

            if not created_at:
                created_at = datetime.now(timezone.utc).isoformat()

            user_record = {
                "id": emp_id,
                "email": email.strip().lower(),
                "password_hash": password_hash,
                "salt": salt,
                "full_name": full_name,
                "role": "EMPLOYEE",
                "zone": zone,
                "assigned_states": assigned_states,
                "is_active": str(is_active),
                "created_at": created_at
            }

            # Write node credentials
            CSVEngine.write_all(cred_path, USER_FIELDS, [user_record])

            # Upsert into Master Users CSV
            CSVEngine.upsert_row(MASTER_USERS_CSV, USER_FIELDS, "id", user_record)

            # Initialize Master Quota record if not already present (preserve existing quota)
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            if not any(q.get("emp_id", "").strip().upper() == emp_id.strip().upper() for q in quotas):
                quota_record = {
                    "emp_id": emp_id,
                    "employee_name": full_name,
                    "zone": zone,
                    "clubs_approved_count": "0",
                    "support_logs_count": "0",
                    "last_activity_timestamp": created_at
                }
                CSVEngine.upsert_row(MASTER_QUOTAS_CSV, QUOTA_FIELDS, "emp_id", quota_record)

            return user_record

    @classmethod
    def update_employee_records(
        cls,
        old_emp_id: str,
        new_emp_id: str,
        full_name: str,
        email: str,
        zone: str,
        assigned_states: str,
        password_hash: Optional[str] = None,
        salt: Optional[str] = None,
        is_active: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Updates an existing employee's details across:
        1. Node directory (renames folder if employee code changed).
        2. Node credentials.csv.
        3. Master master_users.csv.
        4. Master master_quotas.csv (preserves existing quota counts).
        5. Master & Node clubs.csv (updates approved_by_emp_id if ID changed).
        6. Master & Node activity_log.csv (updates emp_id if ID changed).
        """
        with _SYNC_LOCK:
            cls.initialize_storage_hierarchy()
            clean_old = old_emp_id.strip().upper()
            clean_new = (new_emp_id or old_emp_id).strip().upper()
            clean_email = email.strip().lower()

            old_dir = cls.get_employee_dir(clean_old)
            new_dir = cls.get_employee_dir(clean_new)

            # 1. Handle directory rename if employee code / ID changed
            if clean_old != clean_new and old_dir.exists():
                if not new_dir.exists():
                    try:
                        old_dir.rename(new_dir)
                    except Exception:
                        try:
                            shutil.move(str(old_dir), str(new_dir))
                        except Exception:
                            shutil.copytree(str(old_dir), str(new_dir), dirs_exist_ok=True)
                            shutil.rmtree(str(old_dir), ignore_errors=True)
                else:
                    for item in list(old_dir.iterdir()):
                        dest = new_dir / item.name
                        if not dest.exists():
                            try:
                                shutil.move(str(item), str(dest))
                            except Exception:
                                if item.is_dir():
                                    shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                                else:
                                    shutil.copy2(str(item), str(dest))
                    shutil.rmtree(str(old_dir), ignore_errors=True)
            elif not new_dir.exists():
                new_dir.mkdir(parents=True, exist_ok=True)

            # Ensure new node directory structure
            cred_path = cls.get_employee_credentials_path(clean_new)
            clubs_path = cls.get_employee_clubs_path(clean_new)
            act_path = cls.get_employee_activities_path(clean_new)

            CSVEngine.ensure_file(cred_path, USER_FIELDS)
            CSVEngine.ensure_file(clubs_path, CLUB_FIELDS)
            CSVEngine.ensure_file(act_path, ACTIVITY_FIELDS)

            # 2. Update master_users.csv
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            user_record = None
            for u in users:
                if u.get("id", "").strip().upper() == clean_old:
                    u["id"] = clean_new
                    u["email"] = clean_email
                    u["full_name"] = full_name.strip()
                    u["zone"] = zone.strip()
                    u["assigned_states"] = assigned_states.strip()
                    if password_hash and salt:
                        u["password_hash"] = password_hash
                        u["salt"] = salt
                    if is_active is not None:
                        is_active_flag = str(is_active).strip().lower() in ["1", "true", "yes"]
                        u["is_active"] = "1" if is_active_flag else "0"
                    user_record = u
                    break

            if not user_record:
                return None

            CSVEngine.write_all(MASTER_USERS_CSV, USER_FIELDS, users)

            # 3. Write to employee node credentials.csv
            CSVEngine.write_all(cred_path, USER_FIELDS, [user_record])

            # 4. Update master_quotas.csv (PRESERVING existing quotas)
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            quota_found = False
            for q in quotas:
                if q.get("emp_id", "").strip().upper() == clean_old:
                    q["emp_id"] = clean_new
                    q["employee_name"] = full_name.strip()
                    q["zone"] = zone.strip()
                    quota_found = True
                    break
            if not quota_found:
                quotas.append({
                    "emp_id": clean_new,
                    "employee_name": full_name.strip(),
                    "zone": zone.strip(),
                    "clubs_approved_count": "0",
                    "support_logs_count": "0",
                    "last_activity_timestamp": datetime.now(timezone.utc).isoformat()
                })
            CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, quotas)

            # 5. If ID changed, sync referenced employee ID in clubs and activities
            if clean_old != clean_new:
                # Update node clubs
                if clubs_path.exists():
                    n_clubs = CSVEngine.read_all(clubs_path, CLUB_FIELDS)
                    for c in n_clubs:
                        if c.get("approved_by_emp_id", "").strip().upper() == clean_old:
                            c["approved_by_emp_id"] = clean_new
                    CSVEngine.write_all(clubs_path, CLUB_FIELDS, n_clubs)

                # Update master clubs
                m_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
                for c in m_clubs:
                    if c.get("approved_by_emp_id", "").strip().upper() == clean_old:
                        c["approved_by_emp_id"] = clean_new
                CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, m_clubs)

                # Update node activities
                if act_path.exists():
                    n_acts = CSVEngine.read_all(act_path, ACTIVITY_FIELDS)
                    for a in n_acts:
                        if a.get("emp_id", "").strip().upper() == clean_old:
                            a["emp_id"] = clean_new
                    CSVEngine.write_all(act_path, ACTIVITY_FIELDS, n_acts)

                # Update master activities
                m_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
                for a in m_acts:
                    if a.get("emp_id", "").strip().upper() == clean_old:
                        a["emp_id"] = clean_new
                CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, m_acts)

            return user_record

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
    def approve_new_club(
        cls,
        emp_id: str,
        club_data: Dict[str, Any],
        confirm_cloud_sync: bool = True
    ) -> Dict[str, Any]:
        """
        SEC B & C: Club Approval.
        - Captures exact Date of Approval (date_of_approval) upon initial creation
        - Automatically computes 1-year registration validity (renewal_date) from Date of Approval
        - Sets initial last_renewal_date as blank ("")
        - Writes to Employee Node clubs.csv
        - Real-time upsert to Master master_clubs.csv
        - Logs a priority activity in both Employee and Master activity logs
        - Increments employee's performance quota for priority activity

        `confirm_cloud_sync` (default True): block synchronously until the
        Google Drive mirror is confirmed for this club's files, so a normal
        single-club API call can honestly report whether it's durable. Bulk
        operations (e.g. reset_all_and_reseed) pass False here and instead
        perform ONE synchronous confirmation pass across every affected file
        at the very end -- doing a full synchronous Drive round-trip for
        every single club in a large batch is what previously made a 28-club
        reseed take minutes (near-)hanging the request; batching the
        confirmation into one pass is the fix.
        """
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()
            club_id = str(club_data.get("club_id", "")).strip().upper()

            ren_input = str(club_data.get("renewal_date", "")).strip() or str(club_data.get("next_renewal_date", "")).strip()
            parsed_ren_input = parse_iso_or_date(ren_input) if ren_input else None

            # Date of Approval: auto-captured exact date and time of club creation/formation
            raw_doa = str(club_data.get("date_of_approval", "")).strip() or str(club_data.get("submission_timestamp", "")).strip()
            last_renewal_date = str(club_data.get("last_renewal_date", "")).strip()

            if raw_doa:
                date_of_approval = raw_doa
            elif parsed_ren_input and not last_renewal_date:
                # If approval date was not provided but a renewal date was specified:
                # For overdue / historical clubs, date_of_approval must logically have been
                # 1 year prior to the renewal date.
                try:
                    derived_doa = parsed_ren_input.replace(year=parsed_ren_input.year - 1)
                except ValueError:
                    derived_doa = parsed_ren_input.replace(year=parsed_ren_input.year - 1, month=2, day=28)
                date_of_approval = f"{derived_doa.isoformat()}T10:00:00Z"
            else:
                date_of_approval = now_iso

            # Ensure upcoming renewal date can NEVER be earlier than date_of_approval or last_renewal_date
            ren_date = calculate_next_renewal_date(
                date_of_approval=date_of_approval,
                last_renewal_date=last_renewal_date,
                renewal_date=ren_input
            )

            st_val = str(club_data.get("state", "")).strip()
            zn_val = str(club_data.get("zone", "")).strip() or get_zone_for_state(st_val) or "Unknown"

            club_record = {
                "club_id": club_id,
                "reg_no": str(club_data.get("reg_no", "")).strip(),
                "institution_name": str(club_data.get("institution_name", "")).strip(),
                "state": st_val,
                "zone": zn_val,
                "patron_email": str(club_data.get("patron_email", "")).strip().lower(),
                "president_email": str(club_data.get("president_email", "")).strip().lower(),
                "secretary_email": str(club_data.get("secretary_email", "")).strip().lower(),
                "date_of_approval": date_of_approval,
                "last_renewal_date": last_renewal_date,
                "renewal_date": ren_date,
                "status": str(club_data.get("status", "")).strip() or "Approved",
                "approved_by_emp_id": emp_id,
                "updated_at": now_iso,
                "submission_timestamp": date_of_approval,
                "next_renewal_date": ren_date
            }

            # 1. Write to Employee Node DB
            emp_clubs_path = cls.get_employee_clubs_path(emp_id)
            CSVEngine.upsert_row(emp_clubs_path, CLUB_FIELDS, "club_id", club_record)

            # 2. Real-time sync to Master DB
            CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", club_record)

            # 3. Log priority activity in Node & Master -- but only ONCE per
            # club_id. Re-submitting/re-saving the same club (a double
            # click, retried request, or repeat testing) must not mint a
            # fresh "Club Approval" activity_id every time: that is exactly
            # what let a single club accumulate many duplicate log rows,
            # which in turn inflated an employee's quota (before the
            # unique-club-count fix) and cluttered their activity log with
            # noise unrelated to any real, distinct approval.
            emp_act_path = cls.get_employee_activities_path(emp_id)
            existing_acts = CSVEngine.read_all(emp_act_path, ACTIVITY_FIELDS) if emp_act_path.exists() else []
            already_logged = any(
                a.get("club_id", "").strip().upper() == club_id
                and (
                    a.get("support_type", "").strip() == "Club Approval"
                    or a.get("activity_id", "").strip().startswith(f"ACT-PRIORITY-{emp_id}")
                )
                for a in existing_acts
            )
            if not already_logged:
                act_id = f"ACT-PRIORITY-{emp_id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
                activity_row = {
                    "activity_id": act_id,
                    "emp_id": emp_id,
                    "timestamp": now_iso,
                    "support_type": "Club Approval",
                    "priority_flag": "1",  # Priority activity
                    "club_id": club_id,
                    "notes": f"Approved new NDLI Club: {club_record['institution_name']} ({club_id})"
                }
                CSVEngine.append_row(emp_act_path, ACTIVITY_FIELDS, activity_row)
                CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)

            # 4. Increment performance quota -- only for a genuinely new
            # approval, not a resubmission of an already-logged club.
            if not already_logged:
                cls._increment_quota(emp_id, clubs_inc=1, now_iso=now_iso)

            # 5. On hosts with no persistent disk (e.g. Render free tier),
            # local disk does not survive a restart/redeploy/scale-to-zero
            # cycle -- only a confirmed Google Drive mirror does. Block here
            # until the affected files are durably confirmed, so a caller
            # that gets "success" back can trust the record will still be
            # there after the next restart, rather than finding out 30
            # minutes later that it silently vanished.
            cloud_sync_confirmed = True
            if confirm_cloud_sync:
                try:
                    from db.storage_adapter import get_storage_adapter
                    adapter = get_storage_adapter()
                    if hasattr(adapter, "confirm_durable"):
                        cloud_sync_confirmed = adapter.confirm_durable([
                            emp_clubs_path,
                            MASTER_CLUBS_CSV,
                            emp_act_path,
                            MASTER_ACTIVITIES_CSV,
                        ])
                except Exception:
                    cloud_sync_confirmed = False
            else:
                # Caller will confirm sync in one batched pass later; the
                # local write above already fired the normal async
                # background mirror upload as a best-effort head start.
                cloud_sync_confirmed = None

            club_record = dict(club_record)
            club_record["cloud_sync_confirmed"] = cloud_sync_confirmed
            return club_record

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

        approved_club_ids = set()
        node_clubs_path = cls.get_employee_clubs_path(clean_id)
        if node_clubs_path.exists():
            for c in CSVEngine.read_all(node_clubs_path, CLUB_FIELDS):
                cid = c.get("club_id", "").strip().upper()
                if cid and (not c.get("approved_by_emp_id") or c.get("approved_by_emp_id", "").strip().upper() == clean_id):
                    approved_club_ids.add(cid)
        for c in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS):
            if c.get("approved_by_emp_id", "").strip().upper() == clean_id:
                cid = c.get("club_id", "").strip().upper()
                if cid:
                    approved_club_ids.add(cid)

        node_act_path = cls.get_employee_activities_path(clean_id)
        node_acts = CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS) if node_act_path.exists() else []
        master_acts = [a for a in CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS) if a.get("emp_id", "").strip().upper() == clean_id]
        combined_acts = {a.get("activity_id", "").strip(): a for a in (node_acts + master_acts) if a.get("activity_id")}.values()

        club_approval_acts = 0
        standalone_approvals = 0
        support_logs = 0
        latest_ts = ""
        for a in combined_acts:
            ts = a.get("timestamp", "")
            if ts and ts > latest_ts:
                latest_ts = ts
            stype = a.get("support_type", "").strip()
            aid = a.get("activity_id", "").strip()
            if stype == "Club Approval" or aid.startswith(f"ACT-PRIORITY-{clean_id}"):
                club_approval_acts += 1
                if a.get("club_id"):
                    approved_club_ids.add(a.get("club_id").strip().upper())
                else:
                    standalone_approvals += 1
            else:
                support_logs += 1

        # No max()/ratchet: this computed value IS the truth. If a club (and
        # its activity entries) were deleted, this number drops accordingly.
        # IMPORTANT: club_approval_acts (raw activity-log row count) is
        # deliberately NOT used here via max() anymore. It used to be
        # `max(len(approved_club_ids) + standalone_approvals, club_approval_acts)`,
        # which meant duplicate "Club Approval" log entries for the SAME
        # club_id (e.g. from re-submitting/re-testing the same club) could
        # inflate the count far above the true number of distinct clubs --
        # exactly how EMP01 ended up showing 92 when only 8 real clubs
        # existed. The unique-club-id count is the authoritative truth.
        final_clubs = len(approved_club_ids) + standalone_approvals
        final_support = support_logs

        q = {
            "emp_id": clean_id,
            "employee_name": (target.get("full_name") if target else None) or clean_id,
            "zone": target.get("zone", "") if target else "",
            "clubs_approved_count": str(final_clubs),
            "support_logs_count": str(final_support),
            "last_activity_timestamp": latest_ts
        }
        CSVEngine.upsert_row(MASTER_QUOTAS_CSV, QUOTA_FIELDS, "emp_id", q)
        return {"clubs_approved_count": final_clubs, "support_logs_count": final_support}

    @classmethod
    def delete_club(cls, club_id: str) -> Dict[str, Any]:
        """
        Permanently removes a club from both the master DB and whichever
        employee node it belongs to, then synchronously confirms the
        removal reached Google Drive -- so a deleted club doesn't silently
        reappear after a restart pulls a stale (pre-deletion) Drive copy,
        the same class of bug this file's confirm_durable was built to
        catch on the write side.

        Also purges matching activity-log entries for this club (both the
        owning employee's node and master logs) and recomputes that
        employee's quota counters from scratch, so deleting a club can never
        leave a stale, inflated "clubs approved" count behind -- the exact
        drift that previously made an employee's dashboard disagree with
        the live master club count.
        """
        club_id = str(club_id).strip().upper()
        if not club_id:
            raise ValueError("club_id is required")

        with _SYNC_LOCK:
            master_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            target = next((c for c in master_clubs if c.get("club_id", "").strip().upper() == club_id), None)
            if target is None:
                return {"deleted": False, "message": f"No club found with club_id '{club_id}'."}

            approved_by = str(target.get("approved_by_emp_id", "")).strip().upper()

            # 1. Remove from Master DB
            remaining_master = [c for c in master_clubs if c.get("club_id", "").strip().upper() != club_id]
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, remaining_master)

            # 2. Remove from the owning employee's node, if known
            emp_clubs_path = None
            if approved_by:
                emp_clubs_path = cls.get_employee_clubs_path(approved_by)
                if emp_clubs_path.exists():
                    node_clubs = CSVEngine.read_all(emp_clubs_path, CLUB_FIELDS)
                    remaining_node = [c for c in node_clubs if c.get("club_id", "").strip().upper() != club_id]
                    CSVEngine.write_all(emp_clubs_path, CLUB_FIELDS, remaining_node)

            # 2b. Purge matching activity-log entries (master + node) so
            # quota recomputation below reflects the truth, not stale
            # "Club Approval" entries still pointing at a now-deleted club.
            master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            remaining_master_acts = [a for a in master_acts if a.get("club_id", "").strip().upper() != club_id]
            if len(remaining_master_acts) != len(master_acts):
                CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, remaining_master_acts)

            emp_act_path = None
            if approved_by:
                emp_act_path = cls.get_employee_activities_path(approved_by)
                if emp_act_path.exists():
                    node_acts = CSVEngine.read_all(emp_act_path, ACTIVITY_FIELDS)
                    remaining_node_acts = [a for a in node_acts if a.get("club_id", "").strip().upper() != club_id]
                    if len(remaining_node_acts) != len(node_acts):
                        CSVEngine.write_all(emp_act_path, ACTIVITY_FIELDS, remaining_node_acts)

            # 3. Recompute the owning employee's quota from scratch -- the
            # permanent fix, replacing any stale incremented/ratcheted value.
            if approved_by:
                cls.recompute_and_persist_quota(approved_by)

            # 4. Synchronously confirm the deletion reached Drive, same as
            # approve_new_club does for a write -- otherwise a stale Drive
            # copy could restore the "deleted" club on the next restart.
            cloud_sync_confirmed = True
            try:
                from db.storage_adapter import get_storage_adapter
                adapter = get_storage_adapter()
                if hasattr(adapter, "confirm_durable"):
                    paths_to_confirm = [MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV]
                    if emp_clubs_path:
                        paths_to_confirm.append(emp_clubs_path)
                    if emp_act_path:
                        paths_to_confirm.append(emp_act_path)
                    cloud_sync_confirmed = adapter.confirm_durable(paths_to_confirm)
            except Exception:
                cloud_sync_confirmed = False

            return {
                "deleted": True,
                "club_id": club_id,
                "institution_name": target.get("institution_name", ""),
                "cloud_sync_confirmed": cloud_sync_confirmed
            }

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
        reset_all_and_reseed for why that matters once more than a couple
        of items are involved.
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

    @classmethod
    def reset_all_and_reseed(cls, clubs_per_employee: int = 4) -> Dict[str, Any]:
        """
        Full, controlled reset for testing: wipes ALL club and activity data
        (master + every employee node) while explicitly preserving employee
        accounts/credentials, then creates exactly `clubs_per_employee` fresh,
        clearly-labeled test clubs for every employee, with quotas recomputed
        from scratch (never incremented/ratcheted). Intended for an
        explicit, admin-confirmed reset -- not for routine use.
        """
        with _SYNC_LOCK:
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            emp_ids = sorted({u.get("id", "").strip().upper() for u in users if u.get("id", "").strip()})

            # 1. Wipe master club/activity data (headers only)
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, [])
            CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, [])
            CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, [])

            # 2. Wipe each employee's clubs.csv and activity_log.csv only --
            # credentials.csv and issues.csv are NEVER touched here.
            for emp_id in emp_ids:
                clubs_path = cls.get_employee_clubs_path(emp_id)
                if clubs_path.exists():
                    CSVEngine.write_all(clubs_path, CLUB_FIELDS, [])
                acts_path = cls.get_employee_activities_path(emp_id)
                if acts_path.exists():
                    CSVEngine.write_all(acts_path, ACTIVITY_FIELDS, [])

            # 3. Reseed exactly `clubs_per_employee` clean test clubs per employee.
            # confirm_cloud_sync=False: skip the per-club synchronous Drive
            # round-trip here (that's what made a 28-club reset take minutes
            # of sequential network calls) -- confirmed once, in a single
            # batched pass, in step 4 below instead.
            created: Dict[str, List[str]] = {}
            now = datetime.now(timezone.utc)
            for emp_id in emp_ids:
                created[emp_id] = []
                for n in range(1, clubs_per_employee + 1):
                    club_id = f"NDLI-{emp_id}-SEEDTEST{n}"
                    club_data = {
                        "club_id": club_id,
                        "reg_no": f"REG-SEEDTEST-{emp_id}-{n}",
                        "institution_name": f"{emp_id} Seed Test Institution {n}",
                        "state": "Delhi",
                        "patron_email": f"seed.patron.{emp_id.lower()}.{n}@example.com",
                        "president_email": f"seed.president.{emp_id.lower()}.{n}@example.com",
                        "secretary_email": f"seed.secretary.{emp_id.lower()}.{n}@example.com",
                        "date_of_approval": now.isoformat(),
                        "renewal_date": (now.replace(year=now.year + 1)).date().isoformat()
                    }
                    cls.approve_new_club(emp_id=emp_id, club_data=club_data, confirm_cloud_sync=False)
                    created[emp_id].append(club_id)

            # 4. One single, final, batched confirmation pass -- confirms
            # every master file plus every employee's node files together,
            # instead of a synchronous Drive round-trip per club (which is
            # what previously made a large reseed hang for minutes).
            cloud_sync_confirmed = True
            try:
                from db.storage_adapter import get_storage_adapter
                adapter = get_storage_adapter()
                if hasattr(adapter, "confirm_durable"):
                    paths_to_confirm = [MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV]
                    for emp_id in emp_ids:
                        paths_to_confirm.append(cls.get_employee_clubs_path(emp_id))
                        paths_to_confirm.append(cls.get_employee_activities_path(emp_id))
                    cloud_sync_confirmed = adapter.confirm_durable(paths_to_confirm)
            except Exception:
                cloud_sync_confirmed = False

            # 5. Final confirmation pass: recompute every employee's quota
            # fresh (approve_new_club already does this incrementally, this
            # just guarantees consistency after a bulk reseed).
            for emp_id in emp_ids:
                cls.recompute_and_persist_quota(emp_id)

            total_created = sum(len(v) for v in created.values())
            return {
                "employees_reset": len(emp_ids),
                "clubs_per_employee": clubs_per_employee,
                "total_clubs_created": total_created,
                "cloud_sync_confirmed": cloud_sync_confirmed,
                "created": created
            }

    @classmethod
    def update_club(
        cls,
        emp_id: str,
        club_id: str,
        updated_fields: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Updates an existing club record across both employee node and master CSV."""
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()

            # Check master clubs using O(1) key index
            target_record = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", club_id, CLUB_FIELDS)
            if not target_record:
                return None

            # Apply updates
            for k, v in updated_fields.items():
                if k in CLUB_FIELDS and k != "club_id":
                    # date_of_approval is immutable inception timestamp: do not allow blanking or overwriting an existing value
                    if k == "date_of_approval" and target_record.get("date_of_approval"):
                        if not str(v).strip():
                            continue
                    target_record[k] = str(v).strip()

            # Synchronize compatibility aliases
            if target_record.get("date_of_approval"):
                target_record["submission_timestamp"] = target_record["date_of_approval"]
            elif target_record.get("submission_timestamp"):
                target_record["date_of_approval"] = target_record["submission_timestamp"]

            if "renewal_date" in updated_fields or "next_renewal_date" in updated_fields:
                doa = target_record.get("date_of_approval", "")
                lrd = target_record.get("last_renewal_date", "")
                cur_ren = target_record.get("renewal_date", "") or target_record.get("next_renewal_date", "")
                valid_ren = calculate_next_renewal_date(date_of_approval=doa, last_renewal_date=lrd, renewal_date=cur_ren)
                target_record["renewal_date"] = valid_ren
                target_record["next_renewal_date"] = valid_ren

            # If state was updated or zone is empty/Unknown, auto-map zone
            c_state = target_record.get("state", "").strip()
            if not target_record.get("zone") or target_record.get("zone") == "Unknown" or ("state" in updated_fields and c_state):
                target_record["zone"] = get_zone_for_state(c_state) or target_record.get("zone", "") or "Unknown"

            target_record["updated_at"] = now_iso

            # Sync to Master
            CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", target_record)

            # Sync to original approving employee node if applicable
            orig_emp = target_record.get("approved_by_emp_id", "").strip().upper()
            if orig_emp and orig_emp.startswith("EMP"):
                orig_path = cls.get_employee_clubs_path(orig_emp)
                if orig_path.parent.exists():
                    CSVEngine.upsert_row(orig_path, CLUB_FIELDS, "club_id", target_record)

            # Sync to updater's node if different employee
            clean_updater = emp_id.strip().upper()
            if clean_updater and clean_updater.startswith("EMP") and clean_updater != orig_emp:
                updater_path = cls.get_employee_clubs_path(clean_updater)
                if updater_path.parent.exists():
                    CSVEngine.upsert_row(updater_path, CLUB_FIELDS, "club_id", target_record)

            return target_record

    @classmethod
    def renew_club_registration(
        cls,
        emp_id: str,
        club_id: str,
        renewal_date: Optional[str] = None,
        last_renewal_date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        SEC B & C: Registration Renewal Approval ("Renewal Approved").
        Employee checks conditions and approves renewal for another year.
        1. Instantly captures current submission timestamp and logs it as 'Last Renewal Date' (last_renewal_date).
        2. Based on 'Last Renewal Date', automatically calculates upcoming renewal due date (+1 year).
        3. Updates club record in node and master CSVs.
        4. Logs priority renewal activity in activity_log.csv and master_activities.csv.
        5. Increments employee quota counters.
        """
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()
            clean_cid = club_id.strip().upper()

            # 1. Instantly capture current date and time as Last Renewal Date
            clean_last_renewal = str(last_renewal_date or "").strip() or now_iso

            # 2. Re-compute upcoming renewal date as +1 year from that Last Renewal Date
            clean_renewal = str(renewal_date or "").strip()
            if not clean_renewal:
                clean_renewal = calculate_next_renewal_date(last_renewal_date=clean_last_renewal)

            updated = cls.update_club(emp_id, clean_cid, {
                "last_renewal_date": clean_last_renewal,
                "renewal_date": clean_renewal,
                "next_renewal_date": clean_renewal,
                "status": "Active (Renewed)"
            })
            if not updated:
                return None

            # Log renewal activity
            act_id = f"ACT-RENEW-{emp_id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            activity_row = {
                "activity_id": act_id,
                "emp_id": emp_id,
                "timestamp": now_iso,
                "support_type": "Registration Renewal",
                "priority_flag": "1",
                "club_id": clean_cid,
                "notes": f"Renewal Approved for Club {clean_cid}. Last Renewal Date: {clean_last_renewal}, Upcoming Renewal Due Date: {clean_renewal}"
            }
            if emp_id.strip().upper().startswith("EMP"):
                CSVEngine.append_row(cls.get_employee_activities_path(emp_id), ACTIVITY_FIELDS, activity_row)
            CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)
            cls._increment_quota(emp_id, support_inc=1, now_iso=now_iso)

            return updated

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

            # 4b. Deduplicate Club Approval activities: keep only ONE entry
            # per (employee, club_id) pair. Before a fix to approve_new_club,
            # every resubmission of the same club_id minted a brand-new,
            # technically-unique activity_id -- so the SAME club could
            # accumulate many "Club Approval" rows through repeated
            # testing/edits. Those duplicates are all genuinely unique by ID
            # (so step 2/3's merge-by-activity_id above does not catch them),
            # which is exactly what made an employee's activity log show far
            # more entries than their real distinct club count. This runs on
            # every reconciliation (i.e. every server startup), so it keeps
            # actively cleaning up any duplicates already sitting on disk,
            # not just preventing new ones going forward. Keeps the earliest
            # entry per pair (the true original approval date/time) and
            # removes the rest from all_activities -- so they are physically
            # deleted from both node and master activity_log CSVs when this
            # function writes them out in steps 5 and 6 below, not merely
            # excluded from a computed number.
            approval_by_key: Dict[tuple, Dict[str, str]] = {}
            duplicate_activity_ids = set()
            for aid, a in all_activities.items():
                stype = a.get("support_type", "").strip()
                a_emp = a.get("emp_id", "").strip().upper()
                cid = a.get("club_id", "").strip().upper()
                is_club_approval = (
                    stype == "Club Approval"
                    or aid.startswith(f"ACT-PRIORITY-{a_emp}")
                )
                if not is_club_approval or not cid:
                    continue
                key = (a_emp, cid)
                existing = approval_by_key.get(key)
                if existing is None:
                    approval_by_key[key] = a
                    continue
                existing_ts = existing.get("timestamp", "")
                this_ts = a.get("timestamp", "")
                if this_ts and (not existing_ts or this_ts < existing_ts):
                    duplicate_activity_ids.add(existing.get("activity_id", "").strip())
                    approval_by_key[key] = a
                else:
                    duplicate_activity_ids.add(aid)
            for dup_id in duplicate_activity_ids:
                all_activities.pop(dup_id, None)

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
            master_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
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

            for emp_id, q_rec in quota_by_id.items():
                # A) Clubs approved: unique clubs where approved_by_emp_id == emp_id,
                # plus any club approval activities
                approved_club_ids = set()
                for cid, c in all_clubs.items():
                    if c.get("approved_by_emp_id", "").strip().upper() == emp_id:
                        approved_club_ids.add(cid)

                club_approval_act_count = 0
                standalone_approvals = 0
                support_logs_count = 0
                latest_ts = q_rec.get("last_activity_timestamp", "")

                for a in all_activities.values():
                    if a.get("emp_id", "").strip().upper() == emp_id:
                        ts = a.get("timestamp", "")
                        if ts and ts > latest_ts:
                            latest_ts = ts
                        stype = a.get("support_type", "").strip()
                        aid = a.get("activity_id", "").strip()
                        is_club_approval = (
                            stype == "Club Approval"
                            or aid.startswith(f"ACT-PRIORITY-{emp_id}")
                        )
                        if is_club_approval:
                            club_approval_act_count += 1
                            cid = a.get("club_id", "").strip().upper()
                            if cid:
                                approved_club_ids.add(cid)
                            else:
                                standalone_approvals += 1
                        else:
                            support_logs_count += 1

                for cid in approved_club_ids:
                    c = all_clubs.get(cid)
                    if c:
                        c_ts = c.get("updated_at", "") or c.get("date_of_approval", "")
                        if c_ts and c_ts > latest_ts:
                            latest_ts = c_ts

                # Unique-club-count is the truth (see the identical fix and
                # rationale in recompute_and_persist_quota above). Combined
                # with the 4b deduplication step, this ensures the persisted
                # quota can never exceed the real number of distinct clubs.
                total_clubs_approved = len(approved_club_ids) + standalone_approvals

                q_rec["clubs_approved_count"] = str(total_clubs_approved)
                q_rec["support_logs_count"] = str(support_logs_count)
                if latest_ts:
                    q_rec["last_activity_timestamp"] = latest_ts

            CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, list(quota_by_id.values()))

            return {
                "total_master_clubs": len(all_clubs),
                "total_master_activities": len(all_activities),
                "employees_synced": len(synced_emp_ids)
            }
