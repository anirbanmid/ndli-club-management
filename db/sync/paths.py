"""db/sync/paths.py - employee-node paths + storage hierarchy init.

R46: SyncEngine methods moved verbatim from db/sync_engine.py.
`class SyncPathsMixin` is assembled into db.sync_engine.SyncEngine; `self`/`cls`
semantics unchanged.  The four `..._path` getters were `@staticmethod`s that
called `SyncEngine.get_employee_dir(...)`; as mixin methods they are
`@classmethod`s calling `cls.get_employee_dir(...)` (the R39-style mechanical
transform -- byte-identity proven by .openclaw/tmp/verify_sync_split.py).
"""



import os

from config import BACKUP_DIR, DATA_DIR, EMPLOYEE_NODES_DIR, MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_ISSUES_CSV, MASTER_QUOTAS_CSV, MASTER_USERS_CSV

from db.csv_engine import CSVEngine

from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS, ISSUE_FIELDS, QUOTA_FIELDS, USER_FIELDS

from db.sync.dates import calculate_next_renewal_date, parse_iso_or_date

from db.sync.state import _SYNC_LOCK

from pathlib import Path



class SyncPathsMixin:
    """SyncPathsMixin - SyncEngine methods moved verbatim (R46)."""

    @staticmethod
    def get_employee_dir(emp_id: str) -> Path:
        """Returns the base directory for an employee's node database."""
        clean_id = os.path.basename(str(emp_id).strip().lower())
        target = (EMPLOYEE_NODES_DIR / clean_id).resolve()
        if not target.is_relative_to(EMPLOYEE_NODES_DIR.resolve()):
            raise ValueError(f"Directory traversal detected in employee ID: {emp_id}")
        return target


    @classmethod
    def get_employee_credentials_path(cls, emp_id: str) -> Path:
        return cls.get_employee_dir(emp_id) / "credentials.csv"


    @classmethod
    def get_employee_clubs_path(cls, emp_id: str) -> Path:
        return cls.get_employee_dir(emp_id) / "clubs.csv"


    @classmethod
    def get_employee_activities_path(cls, emp_id: str) -> Path:
        return cls.get_employee_dir(emp_id) / "activity_log.csv"


    @classmethod
    def get_employee_issues_path(cls, emp_id: str) -> Path:
        return cls.get_employee_dir(emp_id) / "issues.csv"


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

