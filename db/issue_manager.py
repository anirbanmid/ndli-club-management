"""
NDLI Club Management - Club Unresolved Issues & Escalation Reminders Manager
Handles employee issue logging with 72h reminder, 7-day recurrent reminders if unresolved,
and 30-day escalation reminders to the Admin Dashboard.
"""
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import (
    MASTER_ISSUES_CSV,
    MASTER_CLUBS_CSV,
    EMPLOYEE_NODES_DIR,
    ISSUE_FIELDS,
    CLUB_FIELDS
)
from db.csv_engine import CSVEngine

_ISSUE_LOCK = threading.RLock()


def _parse_iso(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s or s == "-":
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class IssueManager:
    """Manages unresolved issue tracking, 72h employee reminders, and 30d admin escalations."""

    @classmethod
    def ensure_files(cls) -> None:
        """Ensures master issues CSV exists with proper headers."""
        CSVEngine.ensure_file(MASTER_ISSUES_CSV, ISSUE_FIELDS)

    @classmethod
    def get_employee_issues_path(cls, emp_id: str) -> Path:
        clean_id = emp_id.strip().lower()
        node_dir = EMPLOYEE_NODES_DIR / clean_id
        node_dir.mkdir(parents=True, exist_ok=True)
        return node_dir / "issues.csv"

    @classmethod
    def create_issue(
        cls,
        club_id: str,
        emp_id: str,
        issue_note: str,
        created_at: Optional[str] = None,
        reminder_due_at: Optional[str] = None,
        admin_reminder_due_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a new unresolved club issue and sets initial 72-hour reminder.
        """
        cls.ensure_files()
        clean_club_id = str(club_id).strip().upper()
        clean_emp_id = str(emp_id).strip().upper()
        clean_note = str(issue_note).strip()

        with _ISSUE_LOCK:
            # 1. Lookup Club metadata
            clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            club_data = next((c for c in clubs if c.get("club_id", "").strip().upper() == clean_club_id), None)
            if not club_data and EMPLOYEE_NODES_DIR.exists():
                for ed in EMPLOYEE_NODES_DIR.iterdir():
                    if ed.is_dir():
                        nc_path = ed / "clubs.csv"
                        if nc_path.exists():
                            found = next((c for c in CSVEngine.read_all(nc_path, CLUB_FIELDS) if c.get("club_id", "").strip().upper() == clean_club_id), None)
                            if found:
                                club_data = found
                                break

            inst_name = club_data.get("institution_name", "Unknown Institution") if club_data else "Unknown Institution"
            state = club_data.get("state", "Unknown") if club_data else "Unknown"
            zone = club_data.get("zone", "Unknown") if club_data else "Unknown"

            # 2. Timing calculations
            now = datetime.now(timezone.utc)
            c_dt = _parse_iso(created_at) or now
            r_dt = _parse_iso(reminder_due_at) or (c_dt + timedelta(hours=72))
            adm_r_dt = _parse_iso(admin_reminder_due_at) or (c_dt + timedelta(days=30))

            issue_id = f"ISS-{clean_club_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6].upper()}"

            row = {
                "issue_id": issue_id,
                "club_id": clean_club_id,
                "emp_id": clean_emp_id,
                "institution_name": inst_name,
                "state": state,
                "zone": zone,
                "issue_note": clean_note,
                "status": "Unresolved",
                "created_at": c_dt.isoformat(),
                "reminder_due_at": r_dt.isoformat(),
                "admin_reminder_due_at": adm_r_dt.isoformat(),
                "last_reminded_at": "",
                "resolved_at": "",
                "resolved_by": "",
                "resolution_notes": "",
                "updated_at": now.isoformat()
            }

            # 3. Dual-write to Master and Employee Node
            CSVEngine.append_row(MASTER_ISSUES_CSV, ISSUE_FIELDS, row)
            emp_issues_path = cls.get_employee_issues_path(clean_emp_id)
            CSVEngine.ensure_file(emp_issues_path, ISSUE_FIELDS)
            CSVEngine.append_row(emp_issues_path, ISSUE_FIELDS, row)

            return row

    @classmethod
    def get_employee_reminders(
        cls,
        emp_id: Optional[str] = None,
        as_of: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Returns all unresolved issues where reminder_due_at <= as_of (default now).
        If emp_id provided, filters for that specific employee.
        """
        cls.ensure_files()
        cur_dt = as_of or datetime.now(timezone.utc)
        clean_emp = str(emp_id).strip().upper() if emp_id else None

        with _ISSUE_LOCK:
            issues = CSVEngine.read_all(MASTER_ISSUES_CSV, ISSUE_FIELDS)
            due_reminders = []
            for item in issues:
                stat = item.get("status", "").strip().lower()
                if stat != "unresolved":
                    continue

                if clean_emp and item.get("emp_id", "").strip().upper() != clean_emp:
                    continue

                r_due = _parse_iso(item.get("reminder_due_at", ""))
                c_at = _parse_iso(item.get("created_at", ""))
                if r_due and cur_dt >= r_due:
                    item_copy = dict(item)
                    days_unresolved = (cur_dt - c_at).days if c_at else 0
                    hours_unresolved = round((cur_dt - c_at).total_seconds() / 3600, 1) if c_at else 0
                    item_copy["days_unresolved"] = max(0, days_unresolved)
                    item_copy["hours_unresolved"] = max(0, hours_unresolved)
                    item_copy["is_due"] = True
                    due_reminders.append(item_copy)

            due_reminders.sort(key=lambda x: x.get("reminder_due_at", ""))
            return due_reminders

    @classmethod
    def get_admin_reminders(cls, as_of: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Returns unresolved issues that have remained unresolved for 30+ days
        and where admin_reminder_due_at <= as_of.
        """
        cls.ensure_files()
        cur_dt = as_of or datetime.now(timezone.utc)

        with _ISSUE_LOCK:
            issues = CSVEngine.read_all(MASTER_ISSUES_CSV, ISSUE_FIELDS)
            admin_reminders = []
            for item in issues:
                stat = item.get("status", "").strip().lower()
                if stat != "unresolved":
                    continue

                c_at = _parse_iso(item.get("created_at", ""))
                adm_due = _parse_iso(item.get("admin_reminder_due_at", ""))
                if not c_at:
                    continue

                total_seconds_unresolved = (cur_dt - c_at).total_seconds()
                is_30_days = total_seconds_unresolved >= (30 * 86400)

                if is_30_days:
                    # Check if admin reminder is due (or if adm_due is not set or passed)
                    if adm_due is None or cur_dt >= adm_due:
                        item_copy = dict(item)
                        days_unres = int(total_seconds_unresolved // 86400)
                        item_copy["days_unresolved"] = days_unres
                        item_copy["is_admin_escalated"] = True
                        item_copy["is_due"] = True
                        admin_reminders.append(item_copy)

            admin_reminders.sort(key=lambda x: x.get("created_at", ""))
            return admin_reminders

    @classmethod
    def resolve_issue(
        cls,
        issue_id: str,
        status: str,
        resolved_by: str = "",
        resolution_notes: str = "",
        as_of: Optional[datetime] = None,
        role: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Marks an issue either 'Resolved' or 'Not Resolved'.
        If 'Not Resolved', automatically reschedules the reminder for 7 days later (+7 days)
        for the relevant actor (Employee 7d reminder or Admin 7d escalation reminder)
        and keeps doing so until marked 'Resolved'.
        """
        cls.ensure_files()
        clean_id = str(issue_id).strip()
        clean_stat = str(status).strip().title()  # e.g. "Resolved" or "Not Resolved"
        now = as_of or datetime.now(timezone.utc)

        with _ISSUE_LOCK:
            issues = CSVEngine.read_all(MASTER_ISSUES_CSV, ISSUE_FIELDS)
            target = None
            for item in issues:
                if item.get("issue_id", "").strip() == clean_id:
                    target = item
                    break

            if not target:
                return None

            is_marking_resolved = clean_stat.lower() in ["resolved", "closed", "fixed"]

            if is_marking_resolved:
                target["status"] = "Resolved"
                target["resolved_at"] = now.isoformat()
                target["resolved_by"] = resolved_by
                if resolution_notes:
                    target["resolution_notes"] = resolution_notes
                target["updated_at"] = now.isoformat()
            else:
                # Mark Not Resolved: Auto-generate reminder after 7 days
                target["status"] = "Unresolved"
                next_reminder_dt = now + timedelta(days=7)
                target["last_reminded_at"] = now.isoformat()
                if resolution_notes:
                    target["resolution_notes"] = resolution_notes
                target["updated_at"] = now.isoformat()

                # Determine actor role: "ADMIN", "EMPLOYEE", or inferred
                det_role = (role or "").strip().upper()
                if not det_role:
                    if "@" in resolved_by or "admin" in resolved_by.lower():
                        det_role = "ADMIN"
                    elif resolved_by.strip().upper().startswith("EMP"):
                        det_role = "EMPLOYEE"

                if det_role == "ADMIN":
                    # Admin marked Not Resolved: auto-generate next admin reminder after 7 days
                    target["admin_reminder_due_at"] = next_reminder_dt.isoformat()
                    # Do not clobber employee reminder schedule
                elif det_role == "EMPLOYEE":
                    # Employee marked Not Resolved: auto-generate next employee reminder after 7 days
                    target["reminder_due_at"] = next_reminder_dt.isoformat()
                    # Preserve admin_reminder_due_at (so 30-day escalation is not postponed!)
                    c_at = _parse_iso(target.get("created_at")) or now
                    curr_adm = _parse_iso(target.get("admin_reminder_due_at"))
                    if curr_adm is None:
                        target["admin_reminder_due_at"] = (c_at + timedelta(days=30)).isoformat()
                else:
                    # Role unknown: update both/due reminders
                    c_at = _parse_iso(target.get("created_at")) or now
                    curr_adm = _parse_iso(target.get("admin_reminder_due_at"))
                    is_30d = (now - c_at).total_seconds() >= (30 * 86400)
                    if is_30d and (curr_adm is None or now >= curr_adm):
                        target["admin_reminder_due_at"] = next_reminder_dt.isoformat()
                    target["reminder_due_at"] = next_reminder_dt.isoformat()

            # Update Master CSV
            CSVEngine.upsert_row(MASTER_ISSUES_CSV, ISSUE_FIELDS, "issue_id", target)

            # Update Employee Node CSV
            emp_id = target.get("emp_id", "").strip()
            if emp_id:
                emp_path = cls.get_employee_issues_path(emp_id)
                CSVEngine.upsert_row(emp_path, ISSUE_FIELDS, "issue_id", target)

            return target

    @classmethod
    def get_issues(
        cls,
        emp_id: Optional[str] = None,
        club_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Queries all issues filtered by optional employee, club, or status."""
        cls.ensure_files()
        with _ISSUE_LOCK:
            issues = CSVEngine.read_all(MASTER_ISSUES_CSV, ISSUE_FIELDS)
            res = []
            for item in issues:
                if emp_id and item.get("emp_id", "").strip().upper() != emp_id.strip().upper():
                    continue
                if club_id and item.get("club_id", "").strip().upper() != club_id.strip().upper():
                    continue
                if status and item.get("status", "").strip().lower() != status.strip().lower():
                    continue
                res.append(item)
            return res

    @classmethod
    def get_issue_by_id(cls, issue_id: str) -> Optional[Dict[str, Any]]:
        cls.ensure_files()
        clean_id = str(issue_id).strip()
        with _ISSUE_LOCK:
            issues = CSVEngine.read_all(MASTER_ISSUES_CSV, ISSUE_FIELDS)
            for item in issues:
                if item.get("issue_id", "").strip() == clean_id:
                    return item
            return None
