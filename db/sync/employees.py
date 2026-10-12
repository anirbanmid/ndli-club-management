"""db/sync/employees.py - employee node provisioning + record updates.

R46: SyncEngine methods moved verbatim from db/sync_engine.py.
`class SyncEmployeesMixin` is assembled into db.sync_engine.SyncEngine.
"""



import shutil

from config import MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV, MASTER_USERS_CSV

from datetime import datetime, timezone

from db.csv_engine import CSVEngine

from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS, ISSUE_FIELDS, QUOTA_FIELDS, USER_FIELDS

from db.sync.state import _SYNC_LOCK

from typing import Any, Dict, Optional



class SyncEmployeesMixin:
    """SyncEmployeesMixin - SyncEngine methods moved verbatim (R46)."""

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

