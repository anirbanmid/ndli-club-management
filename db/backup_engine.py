"""
NDLI Club Management - Automated Database Backup Engine
Handles 7-day automated backups of Admin and Employee databases with strict rolling retention (MAX_RETAINED_BACKUPS archives).
"""
import os
import sys
import json
import shutil
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

from config import (
    BASE_DIR,
    DATA_DIR,
    MASTER_DATA_DIR,
    EMPLOYEE_NODES_DIR,
    BACKUP_DIR
)

_BACKUP_LOCK = threading.RLock()
_SCHEDULER_THREAD: Optional[threading.Thread] = None
_SCHEDULER_RUNNING = False

BACKUP_INTERVAL_DAYS = 7
# Rolling retention: how many backup archives to keep. Each archive is a tiny
# CSV snapshot (~40KB: master dual-copy + 7 employee nodes), so 6 archives cost
# ~250KB — about 0.05% of the 512MB PythonAnywhere free tier. Six weekly
# archives give ~6 weeks of recovery history instead of the old 2 (~14 days).
MAX_RETAINED_BACKUPS = 6
SCHEDULE_FILE_NAME = "backup_schedule.json"


class BackupEngine:
    """Manages creation, scheduled checks, and strict rotation of database backups."""

    @staticmethod
    def get_backup_dir() -> Path:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        return BACKUP_DIR

    @staticmethod
    def get_schedule_file() -> Path:
        return BackupEngine.get_backup_dir() / SCHEDULE_FILE_NAME

    @classmethod
    def get_existing_backups(cls) -> List[Path]:
        """Returns all backup directories sorted newest to oldest."""
        backup_dir = cls.get_backup_dir()
        if not backup_dir.exists():
            return []
        dirs = [p for p in backup_dir.iterdir() if p.is_dir() and p.name.startswith("backup_")]

        def _get_sort_time(p: Path) -> float:
            manifest = p / "manifest.json"
            if manifest.exists():
                try:
                    with open(manifest, "r", encoding="utf-8") as mf:
                        mdata = json.load(mf)
                    ts = mdata.get("created_at")
                    if ts:
                        return datetime.fromisoformat(ts).timestamp()
                except Exception:
                    pass
            try:
                return p.stat().st_mtime
            except Exception:
                return 0.0

        dirs.sort(key=lambda p: (_get_sort_time(p), p.name), reverse=True)
        return dirs

    @classmethod
    def rotate_backups(cls, keep: int = MAX_RETAINED_BACKUPS) -> Tuple[List[str], List[str]]:
        """
        Retains only the latest `keep` backups (default 2) and deletes all older backups.
        Returns (retained_names, deleted_names).
        """
        with _BACKUP_LOCK:
            existing = cls.get_existing_backups()
            retained = existing[:keep]
            to_delete = existing[keep:]

            deleted_names = []
            for d in to_delete:
                try:
                    shutil.rmtree(str(d), ignore_errors=True)
                    deleted_names.append(d.name)
                except Exception as e:
                    print(f"[!] Error deleting old backup {d.name}: {e}")

            retained_names = [d.name for d in retained]
            return retained_names, deleted_names

    @classmethod
    def create_backup(cls, note: str = "Automated 7-Day Backup") -> Dict[str, Any]:
        """
        Creates a complete snapshot of both Admin database (data/master) and
        Employee database (data/employees), writes a manifest, and rotates backups.
        """
        with _BACKUP_LOCK:
            backup_base = cls.get_backup_dir()
            now = datetime.now(timezone.utc)
            timestamp_str = now.strftime("%Y%m%d_%H%M%S_%f")
            backup_id = f"backup_{timestamp_str}"
            target_dir = backup_base / backup_id
            target_dir.mkdir(parents=True, exist_ok=True)

            admin_target = target_dir / "admin"
            master_target = target_dir / "master"
            employee_target = target_dir / "employees"

            # 1. Copy Admin Master Database (write to both admin and master for dual compatibility)
            admin_files = []
            if MASTER_DATA_DIR.exists():
                admin_target.mkdir(parents=True, exist_ok=True)
                master_target.mkdir(parents=True, exist_ok=True)
                for f in MASTER_DATA_DIR.iterdir():
                    if f.is_file() and f.suffix == ".csv" and not f.name.startswith("."):
                        shutil.copy2(str(f), str(admin_target / f.name))
                        shutil.copy2(str(f), str(master_target / f.name))
                        admin_files.append(f.name)

            # 2. Copy Employee Node Databases
            employee_nodes = []
            if EMPLOYEE_NODES_DIR.exists():
                employee_target.mkdir(parents=True, exist_ok=True)
                for emp_dir in EMPLOYEE_NODES_DIR.iterdir():
                    if emp_dir.is_dir():
                        dest_emp = employee_target / emp_dir.name
                        dest_emp.mkdir(parents=True, exist_ok=True)
                        employee_nodes.append(emp_dir.name)
                        for f in emp_dir.iterdir():
                            if f.is_file() and f.suffix == ".csv" and not f.name.startswith("."):
                                shutil.copy2(str(f), str(dest_emp / f.name))

            # 3. Create Manifest
            manifest = {
                "backup_id": backup_id,
                "created_at": now.isoformat(),
                "note": note,
                "admin_files": admin_files,
                "employee_nodes": employee_nodes,
                "status": "SUCCESS"
            }
            manifest_file = target_dir / "manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2)

            # 4. Enforce strict rolling retention (keep newest MAX_RETAINED_BACKUPS, delete older)
            retained, deleted = cls.rotate_backups(keep=MAX_RETAINED_BACKUPS)

            # 5. Update Schedule Metadata
            schedule_info = {
                "last_backup_time": now.isoformat(),
                "last_backup_id": backup_id,
                "next_backup_due": (now + timedelta(days=BACKUP_INTERVAL_DAYS)).isoformat(),
                "interval_days": BACKUP_INTERVAL_DAYS,
                "max_retained_backups": MAX_RETAINED_BACKUPS,
                "retained_backups": retained,
                "deleted_previous_backups": deleted
            }

            # 6. Mirror Backup to Google Drive
            drive_res = cls.sync_backup_to_drive(backup_id=backup_id, note=note)
            schedule_info["drive_sync"] = drive_res

            with open(cls.get_schedule_file(), "w", encoding="utf-8") as sf:
                json.dump(schedule_info, sf, indent=2)

            return {
                "success": True,
                "backup_id": backup_id,
                "path": str(target_dir),
                "created_at": now.isoformat(),
                "admin_files_count": len(admin_files),
                "employee_nodes_count": len(employee_nodes),
                "retained_backups": retained,
                "deleted_backups": deleted,
                "drive_sync": drive_res,
                "drive_file": drive_res.get("filename")
            }

    @classmethod
    def sync_backup_to_drive(cls, backup_id: str, note: str = "", async_relay: bool = True) -> Dict[str, Any]:
        """
        Relays the backup creation to Google Drive via the Google Apps Script Webhook Relay
        or mounted Drive directory, ensuring the backup ZIP archive is stored in Google Drive
        and the rolling retention policy is enforced directly in Google Drive.
        """
        try:
            from config import DRIVE_STORAGE_MODE, APPS_SCRIPT_SYNC_URL
            import urllib.request

            # Skip live HTTP network calls during automated test suites
            if os.getenv("NDLI_TESTING") == "true" or "unittest" in sys.modules:
                return {
                    "mode": DRIVE_STORAGE_MODE,
                    "status": "SUCCESS",
                    "filename": f"{backup_id}.zip",
                    "message": "[Testing Mode] Google Drive mirror simulated"
                }

            drive_info = {
                "mode": DRIVE_STORAGE_MODE,
                "status": "pending_mirror" if (DRIVE_STORAGE_MODE == "APPS_SCRIPT_RELAY" and APPS_SCRIPT_SYNC_URL) else "skipped",
                "message": "Mirroring to Google Drive /backups folder"
            }

            if DRIVE_STORAGE_MODE == "APPS_SCRIPT_RELAY" and APPS_SCRIPT_SYNC_URL:
                def _do_relay():
                    try:
                        payload = {
                            "path": "admin/backup/trigger",
                            "data": {
                                "backup_id": backup_id,
                                "note": note
                            }
                        }
                        req = urllib.request.Request(
                            APPS_SCRIPT_SYNC_URL,
                            data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            resp_content = resp.read().decode("utf-8")
                            if resp_content:
                                try:
                                    data = json.loads(resp_content)
                                    drive_data = data.get("data", {})
                                    schedule_file = cls.get_schedule_file()
                                    if schedule_file.exists():
                                        try:
                                            with open(schedule_file, "r", encoding="utf-8") as sf:
                                                sdata = json.load(sf)
                                            sdata["drive_sync"] = {
                                                "status": "SUCCESS",
                                                "filename": drive_data.get("filename"),
                                                "timestamp": drive_data.get("timestamp")
                                            }
                                            with open(schedule_file, "w", encoding="utf-8") as sf:
                                                json.dump(sdata, sf, indent=2)
                                        except Exception:
                                            pass
                                except Exception as parse_err:
                                    print(f"[!] Warning: Could not parse GAS response as JSON: {parse_err}")
                    except Exception as e:
                        print(f"[!] Error in async Google Drive backup relay: {e}")

                if async_relay:
                    t = threading.Thread(target=_do_relay, daemon=True)
                    t.start()
                else:
                    _do_relay()

            return drive_info
        except Exception as e:
            print(f"[!] Warning: Failed to initialize Google Drive backup sync: {e}")
            return {
                "mode": "ERROR",
                "status": "FAILED",
                "message": f"Drive mirror initialization skipped: {str(e)}"
            }

    @classmethod
    def check_and_run_auto_backup(cls, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        Checks if 7 days have passed since the last backup or if no backup exists.
        If due or forced, triggers a new backup and prunes old ones.
        """
        with _BACKUP_LOCK:
            now = datetime.now(timezone.utc)
            schedule_file = cls.get_schedule_file()

            # Always maintain strict retention invariant (only last 2 stored, delete older)
            cls.rotate_backups(keep=MAX_RETAINED_BACKUPS)

            last_backup_dt: Optional[datetime] = None
            if schedule_file.exists():
                try:
                    with open(schedule_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    ts = data.get("last_backup_time")
                    if ts:
                        last_backup_dt = datetime.fromisoformat(ts)
                except Exception:
                    pass

            existing = cls.get_existing_backups()

            # If schedule file is missing/invalid but backups exist on disk, recover timestamp from latest
            if last_backup_dt is None and existing:
                latest_dir = existing[0]
                manifest_file = latest_dir / "manifest.json"
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r", encoding="utf-8") as mf:
                            mdata = json.load(mf)
                        mts = mdata.get("created_at")
                        if mts:
                            last_backup_dt = datetime.fromisoformat(mts)
                    except Exception:
                        pass
                if last_backup_dt is None:
                    try:
                        last_backup_dt = datetime.fromtimestamp(latest_dir.stat().st_mtime, tz=timezone.utc)
                    except Exception:
                        pass
                # Save recovered schedule
                if last_backup_dt:
                    try:
                        schedule_info = {
                            "last_backup_time": last_backup_dt.isoformat(),
                            "last_backup_id": latest_dir.name,
                            "next_backup_due": (last_backup_dt + timedelta(days=BACKUP_INTERVAL_DAYS)).isoformat(),
                            "interval_days": BACKUP_INTERVAL_DAYS,
                            "max_retained_backups": MAX_RETAINED_BACKUPS,
                            "retained_backups": [d.name for d in existing[:MAX_RETAINED_BACKUPS]],
                            "deleted_previous_backups": []
                        }
                        with open(schedule_file, "w", encoding="utf-8") as sf:
                            json.dump(schedule_info, sf, indent=2)
                    except Exception:
                        pass

            if not existing and not last_backup_dt:
                # No backup exists at all -> Run initial baseline backup
                return cls.create_backup(note="Initial Baseline Auto-Backup")

            if force:
                return cls.create_backup(note="Manual / Force Triggered Backup")

            if last_backup_dt is not None:
                elapsed = now - last_backup_dt
                if elapsed >= timedelta(days=BACKUP_INTERVAL_DAYS):
                    return cls.create_backup(note="Automated 7-Day Scheduled Backup")

            return None

    @classmethod
    def get_backup_status(cls) -> Dict[str, Any]:
        """Returns comprehensive status of backup configuration, schedules, and stored archives."""
        with _BACKUP_LOCK:
            # Enforce strict rolling retention
            cls.rotate_backups(keep=MAX_RETAINED_BACKUPS)
            now = datetime.now(timezone.utc)
            schedule_file = cls.get_schedule_file()
            schedule_data = {}
            if schedule_file.exists():
                try:
                    with open(schedule_file, "r", encoding="utf-8") as f:
                        schedule_data = json.load(f)
                except Exception:
                    pass

            existing_dirs = cls.get_existing_backups()
            backups_list = []
            for d in existing_dirs[:MAX_RETAINED_BACKUPS]:
                manifest_file = d / "manifest.json"
                info = {"backup_id": d.name, "directory": str(d)}
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r", encoding="utf-8") as mf:
                            manifest_data = json.load(mf)
                            info.update(manifest_data)
                    except Exception:
                        pass
                backups_list.append(info)

            last_time_str = schedule_data.get("last_backup_time")
            next_due_str = schedule_data.get("next_backup_due")
            if not next_due_str and last_time_str:
                try:
                    last_dt = datetime.fromisoformat(last_time_str)
                    next_due_str = (last_dt + timedelta(days=BACKUP_INTERVAL_DAYS)).isoformat()
                except Exception:
                    pass

            return {
                "interval_days": BACKUP_INTERVAL_DAYS,
                "max_retained_backups": MAX_RETAINED_BACKUPS,
                "total_stored_backups": len(backups_list),
                "last_backup_time": last_time_str,
                "next_backup_due": next_due_str,
                "backups": backups_list,
                "status": "HEALTHY"
            }

    @classmethod
    def restore_backup(cls, source_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Emergency database restoration from a local directory or ZIP archive.
        Accepts:
        - A Path/str pointing to a .zip archive (downloaded from Google Drive or local)
        - A Path/str pointing to a backup snapshot directory (e.g. data/backups/backup_...)
        Replaces active CSVs in data/master/ and data/employees/ and executes full reconciliation.
        """
        import zipfile
        from db.sync_engine import SyncEngine

        src = Path(source_path)
        if not src.exists():
            candidate_dir = BACKUP_DIR / str(source_path)
            candidate_zip = BACKUP_DIR / f"{source_path}.zip"
            if candidate_dir.exists():
                src = candidate_dir
            elif candidate_zip.exists():
                src = candidate_zip
            else:
                matches = list(BACKUP_DIR.glob(f"*{source_path}*"))
                if matches:
                    src = matches[0]
                else:
                    raise FileNotFoundError(f"Backup source does not exist: {src}")

        with _BACKUP_LOCK:
            restored_master_files = []
            restored_employee_nodes = []

            # Case A: ZIP archive (e.g. downloaded from Google Drive backups folder)
            if src.is_file() and (src.suffix.lower() == ".zip" or zipfile.is_zipfile(src)):
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    with zipfile.ZipFile(src, "r") as zf:
                        zf.extractall(tmpdir)
                    tmp_path = Path(tmpdir)

                    master_src = tmp_path / "master"
                    if not master_src.exists():
                        for sub in tmp_path.glob("**/master"):
                            if sub.is_dir():
                                master_src = sub
                                break
                    if not master_src or not master_src.exists():
                        master_src = tmp_path / "admin"
                        if not master_src.exists():
                            for sub in tmp_path.glob("**/admin"):
                                if sub.is_dir():
                                    master_src = sub
                                    break

                    emp_src = tmp_path / "employees"
                    if not emp_src.exists():
                        for sub in tmp_path.glob("**/employees"):
                            if sub.is_dir():
                                emp_src = sub
                                break

                    if master_src and master_src.exists():
                        MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                        for f in master_src.iterdir():
                            if f.is_file() and f.suffix == ".csv":
                                shutil.copy2(str(f), str(MASTER_DATA_DIR / f.name))
                                restored_master_files.append(f.name)

                    if emp_src and emp_src.exists():
                        EMPLOYEE_NODES_DIR.mkdir(parents=True, exist_ok=True)
                        for e_dir in emp_src.iterdir():
                            if e_dir.is_dir():
                                dest_node = EMPLOYEE_NODES_DIR / e_dir.name.lower()
                                dest_node.mkdir(parents=True, exist_ok=True)
                                restored_employee_nodes.append(e_dir.name)
                                for f in e_dir.iterdir():
                                    if f.is_file() and f.suffix == ".csv":
                                        shutil.copy2(str(f), str(dest_node / f.name))

            # Case B: Local backup directory
            elif src.is_dir():
                master_src = (src / "master") if (src / "master").exists() else (src / "admin")
                emp_src = src / "employees"

                if master_src and master_src.exists():
                    MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
                    for f in master_src.iterdir():
                        if f.is_file() and f.suffix == ".csv":
                            shutil.copy2(str(f), str(MASTER_DATA_DIR / f.name))
                            restored_master_files.append(f.name)

                if emp_src and emp_src.exists():
                    EMPLOYEE_NODES_DIR.mkdir(parents=True, exist_ok=True)
                    for e_dir in emp_src.iterdir():
                        if e_dir.is_dir():
                            dest_node = EMPLOYEE_NODES_DIR / e_dir.name.lower()
                            dest_node.mkdir(parents=True, exist_ok=True)
                            restored_employee_nodes.append(e_dir.name)
                            for f in e_dir.iterdir():
                                if f.is_file() and f.suffix == ".csv":
                                    shutil.copy2(str(f), str(dest_node / f.name))
            else:
                raise ValueError(f"Unrecognized backup format for source: {src}")

            # Invalidate memory cache so subsequent reads reflect restored files
            from db.csv_engine import CSVEngine
            CSVEngine.clear_cache()

            # Run full reconciliation to rebuild all indexes, schemas, and performance quotas
            reconcile_summary = SyncEngine.reconcile_all_nodes()

            return {
                "success": True,
                "message": "Emergency restoration completed successfully.",
                "source": str(src),
                "restored_from": str(src.name),
                "restored_files_count": len(restored_master_files) + len(restored_employee_nodes),
                "restored_master_files": restored_master_files,
                "restored_employee_nodes": restored_employee_nodes,
                "reconciliation": reconcile_summary,
                "reconciliation_summary": reconcile_summary
            }

    @classmethod
    def start_scheduler(cls, poll_interval_seconds: int = 3600) -> None:
        """Starts a background daemon thread that periodically checks the 7-day backup schedule."""
        global _SCHEDULER_THREAD, _SCHEDULER_RUNNING
        with _BACKUP_LOCK:
            if _SCHEDULER_RUNNING:
                return
            _SCHEDULER_RUNNING = True

        def _worker():
            # Initial run check upon startup
            try:
                cls.check_and_run_auto_backup()
            except Exception as e:
                print(f"[!] Error in initial auto backup check: {e}")

            while _SCHEDULER_RUNNING:
                time.sleep(poll_interval_seconds)
                try:
                    cls.check_and_run_auto_backup()
                except Exception as e:
                    print(f"[!] Error in auto backup scheduler check: {e}")

        _SCHEDULER_THREAD = threading.Thread(target=_worker, daemon=True, name="NDLIBackupScheduler")
        _SCHEDULER_THREAD.start()
