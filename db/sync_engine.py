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

            # Initialize Master Quota record
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
        club_data: Dict[str, Any]
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

            club_record = {
                "club_id": club_id,
                "reg_no": str(club_data.get("reg_no", "")).strip(),
                "institution_name": str(club_data.get("institution_name", "")).strip(),
                "state": str(club_data.get("state", "")).strip(),
                "zone": str(club_data.get("zone", "")).strip(),
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

            # 3. Log priority activity in Node & Master
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
            emp_act_path = cls.get_employee_activities_path(emp_id)
            CSVEngine.append_row(emp_act_path, ACTIVITY_FIELDS, activity_row)
            CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)

            # 4. Increment performance quota
            cls._increment_quota(emp_id, clubs_inc=1, now_iso=now_iso)

            return club_record

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

            # If state was updated, auto-remap zone to ensure strict consistency
            if "state" in updated_fields and target_record.get("state"):
                new_zone = get_zone_for_state(target_record["state"])
                if new_zone:
                    target_record["zone"] = new_zone

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
        Reconciles the Master Database from all Employee Node databases.
        Can be invoked anytime to guarantee full data integrity without data loss.
        """
        with _SYNC_LOCK:
            cls.initialize_storage_hierarchy()
            all_clubs: Dict[str, Dict[str, str]] = {}
            all_activities: Dict[str, Dict[str, str]] = {}
            employee_counts: Dict[str, Dict[str, int]] = {}

            # Read all existing master clubs first
            for c in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS):
                cid = c.get("club_id", "").strip().upper()
                if cid:
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

            # Scan employee node folders
            if EMPLOYEE_NODES_DIR.exists():
                for emp_dir in EMPLOYEE_NODES_DIR.iterdir():
                    if not emp_dir.is_dir():
                        continue
                    emp_id = emp_dir.name.upper()
                    employee_counts[emp_id] = {"clubs": 0, "activities": 0}

                    # Read node clubs
                    node_clubs_path = emp_dir / "clubs.csv"
                    cls._migrate_club_csv_headers(node_clubs_path)
                    for c in CSVEngine.read_all(node_clubs_path, CLUB_FIELDS):
                        cid = c.get("club_id", "").strip().upper()
                        if cid:
                            doa = c.get("date_of_approval", "").strip() or c.get("submission_timestamp", "").strip()
                            lrd = c.get("last_renewal_date", "").strip()
                            ren = c.get("renewal_date", "").strip() or c.get("next_renewal_date", "").strip()

                            # Preserve master's date_of_approval or last_renewal_date if node record lacks it
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

                            # Keep most recently updated
                            if cid not in all_clubs or (c.get("updated_at", "") >= all_clubs[cid].get("updated_at", "")):
                                all_clubs[cid] = c
                            employee_counts[emp_id]["clubs"] += 1

                    # Read node activities
                    node_act_path = emp_dir / "activity_log.csv"
                    for a in CSVEngine.read_all(node_act_path, ACTIVITY_FIELDS):
                        aid = a.get("activity_id", "").strip()
                        if aid:
                            all_activities[aid] = a
                            employee_counts[emp_id]["activities"] += 1

            # Rewrite master clubs
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, list(all_clubs.values()))

            # Read existing master activities to merge
            for a in CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS):
                aid = a.get("activity_id", "").strip()
                if aid and aid not in all_activities:
                    all_activities[aid] = a

            # Rewrite master activities
            sorted_acts = sorted(all_activities.values(), key=lambda x: x.get("timestamp", ""))
            CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, sorted_acts)

            # Recompute quotas
            quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
            quota_by_id = {q["emp_id"]: q for q in quotas}

            for emp_id, counts in employee_counts.items():
                if emp_id in quota_by_id:
                    quota_by_id[emp_id]["clubs_approved_count"] = str(counts["clubs"])
                    quota_by_id[emp_id]["support_logs_count"] = str(counts["activities"])

            CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, list(quota_by_id.values()))

            return {
                "total_master_clubs": len(all_clubs),
                "total_master_activities": len(all_activities),
                "employees_synced": len(employee_counts)
            }
