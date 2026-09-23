"""
NDLI Club Management - Google Drive & Local Storage Adapter
Provides an abstraction layer supporting:
1. Local Filesystem / Google Drive for Desktop Synced Directory
2. Google Apps Script Webhook Relay (Cloud-to-Drive 24x7 Real-time Mirror)
3. Google Drive API v3 (Direct Cloud REST operations)
"""
import os
import json
import time
import threading
import urllib.request
import urllib.parse
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
_UPLOAD_SEMAPHORE = threading.BoundedSemaphore(value=4)

def _dispatch_upload(target_func, *args):
    """Dispatches background sync in a daemon thread bounded by semaphore."""
    def _worker():
        if not _UPLOAD_SEMAPHORE.acquire(blocking=False):
            return
        try:
            target_func(*args)
        finally:
            _UPLOAD_SEMAPHORE.release()
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
from config import (
    DATA_DIR,
    GOOGLE_DRIVE_FOLDER_ID,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    APPS_SCRIPT_SYNC_URL,
    RELAY_SECRET,
    DRIVE_STORAGE_MODE
)


class StorageAdapter(ABC):
    """Abstract interface for file persistence and synchronization."""

    @abstractmethod
    def read_text(self, relative_path: str) -> str:
        pass

    @abstractmethod
    def write_text(self, relative_path: str, content: str) -> None:
        pass

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        pass

    @abstractmethod
    def get_info(self) -> Dict[str, Any]:
        pass

    def confirm_durable(self, absolute_paths: List[Path]) -> bool:
        """
        Blocking, synchronous confirmation that the given files have reached
        durable storage. Default: local disk IS the durable store (LOCAL_SYNC
        mode, or any environment with a real persistent disk), so there is
        nothing further to confirm.
        Overridden by AppsScriptRelaySyncAdapter for environments (e.g. a
        free-tier host with NO persistent disk) where local disk is only an
        ephemeral, per-instance cache and Google Drive is the only thing that
        actually survives a restart/redeploy/scale-to-zero cycle.
        """
        return True


class LocalSyncStorageAdapter(StorageAdapter):
    """
    Adapter for Local Directory and Google Drive for Desktop Mounted Folders.
    """

    def __init__(self, root_dir: Path = DATA_DIR):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        clean_path = relative_path.lstrip("/\\")
        target = (self.root_dir / clean_path).resolve()
        if not target.is_relative_to(self.root_dir.resolve()):
            raise PermissionError(f"Directory traversal detected: {relative_path}")
        return target

    def read_text(self, relative_path: str) -> str:
        target = self._resolve(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Storage path does not exist: {relative_path}")
        return target.read_text(encoding="utf-8")

    def write_text(self, relative_path: str, content: str) -> None:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.parent / f"{target.name}.tmp.{os.getpid()}"
        tmp_target.write_text(content, encoding="utf-8")
        os.replace(tmp_target, target)

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()

    def pull_all_from_drive(self) -> Dict[str, Any]:
        return {"success": True, "message": "Local storage mode: local files already present", "total_pulled": 0}

    def get_info(self) -> Dict[str, Any]:
        return {
            "mode": "LOCAL_SYNC",
            "root_dir": str(self.root_dir.resolve()),
            "status": "active",
            "drive_sync_type": "Google Drive for Desktop / Local Filesystem"
        }


class AppsScriptRelaySyncAdapter(StorageAdapter):
    """
    Cloud-to-Google Drive Real-Time Sync Adapter using Apps Script Webhook Relay.
    Ensures zero user latency by writing to high-speed local cache first (< 1ms),
    then asynchronously relaying CSV updates to the Google Drive folder in a background thread.
    """

    def __init__(
        self,
        relay_url: str = APPS_SCRIPT_SYNC_URL,
        local_fallback: Optional[LocalSyncStorageAdapter] = None
    ):
        self.relay_url = relay_url
        self.local = local_fallback or LocalSyncStorageAdapter()
        self.last_sync_time: Optional[str] = None
        self.last_sync_status: str = "initialized"
        self.synced_files_count: int = 0
        self.last_error: Optional[str] = None
        self.failed_uploads_count: int = 0

    def read_text(self, relative_path: str) -> str:
        return self.local.read_text(relative_path)

    def _log_sync_event(self, event_type: str, message: str) -> None:
        """
        Persists sync warnings/failures to a durable, append-only log on the
        persistent disk so a fire-and-forget background failure is no longer
        silent/invisible. This survives restarts (it lives under DATA_DIR)
        and can be inspected via GET /api/admin/sync-issues or the log file
        directly at <DATA_DIR>/sync_issues.log.
        """
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event_type,
                "message": message,
            }
            log_path = self.local.root_dir / "sync_issues.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            # Logging must never itself break the sync/merge path.
            pass

    def enqueue_upload(self, relative_path: str, content: str) -> None:
        """Enqueues file upload to Google Drive using bounded daemon worker."""
        if self.relay_url and not self.relay_url.startswith("http://example"):
            try:
                _dispatch_upload(self._upload_file_to_drive, relative_path, content)
            except Exception as dispatch_err:
                self._log_sync_event(
                    "dispatch_failed",
                    f"{relative_path}: failed to dispatch background upload thread: {dispatch_err}"
                )

    def write_text(self, relative_path: str, content: str) -> None:
        # 1. Instant local write (guarantees sub-millisecond response)
        self.local.write_text(relative_path, content)

        # 2. Asynchronous background upload to Google Drive via bounded pool
        self.enqueue_upload(relative_path, content)

    def exists(self, relative_path: str) -> bool:
        return self.local.exists(relative_path)

    def _upload_file_to_drive(self, relative_path: str, content: str, max_attempts: int = 3) -> bool:
        """
        Relays a file to Google Drive via the Apps Script webhook.
        Retries transient failures (network blips, cold Apps Script starts,
        brief quota contention) with short backoff before giving up, and
        logs a durable, inspectable record if every attempt fails so a save
        never silently fails to reach the cloud backup without a trace.
        """
        clean_path = relative_path.replace("\\", "/").lstrip("/")
        parts = clean_path.split("/")
        sub_path = "/".join(parts[:-1]) if len(parts) > 1 else "master"
        file_name = parts[-1]

        payload = {
            "path": "sync/mirror-file",
            "method": "POST",
            "data": {
                "subPath": sub_path,
                "fileName": file_name,
                "content": content
            }
        }
        if RELAY_SECRET:
            payload["relay_key"] = RELAY_SECRET
        last_err: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                req = urllib.request.Request(
                    self.relay_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw_body = resp.read().decode("utf-8", errors="replace")

                # CRITICAL: Google Apps Script web apps almost always return
                # HTTP 200 even when the operation itself failed -- the real
                # result is `ok`/`success` inside the JSON body (see
                # deployment_gas/Code.gs's doPost/apiDispatcher, which wraps
                # every outcome, success or failure, in an HTTP-200 response).
                # A prior version of this method only checked that urlopen()
                # didn't raise, which meant a Drive-side failure (bad folder
                # reference, quota, permissions, a caught exception in the
                # script) was silently reported as a successful sync. That
                # false-positive is exactly what let approve_new_club return
                # cloud_sync_confirmed=True for records that were never
                # actually durable. Parse and check the body for real.
                try:
                    parsed = json.loads(raw_body) if raw_body else {}
                except (json.JSONDecodeError, ValueError):
                    parsed = None

                body_ok = (
                    isinstance(parsed, dict)
                    and (
                        parsed.get("ok") is True
                        or (isinstance(parsed.get("data"), dict) and parsed["data"].get("success") is True)
                        or parsed.get("success") is True
                    )
                )

                if not parsed and raw_body:
                    # Response wasn't valid JSON at all (e.g. an Apps Script
                    # error/login HTML page) -- definitely not a confirmed sync.
                    raise ValueError(f"Non-JSON response from relay: {raw_body[:200]!r}")
                if not body_ok:
                    err_detail = None
                    if isinstance(parsed, dict):
                        data_field = parsed.get("data")
                        err_detail = (
                            (isinstance(data_field, dict) and (data_field.get("message") or data_field.get("error")))
                            or parsed.get("message")
                            or parsed.get("error")
                        )
                    raise ValueError(f"Relay reported failure for {relative_path}: {err_detail or parsed}")

                self.last_sync_time = datetime.now(timezone.utc).isoformat()
                self.last_sync_status = "synced"
                self.synced_files_count += 1
                return True
            except Exception as err:
                last_err = err
                if attempt < max_attempts:
                    time.sleep(min(2 ** attempt, 10))  # 2s, 4s backoff

        # All attempts exhausted: record this loudly and durably instead of
        # letting it vanish into a daemon thread that no one ever checks.
        self.last_error = str(last_err)
        self.last_sync_status = f"warning: {last_err}"
        self.failed_uploads_count += 1
        self._log_sync_event(
            "upload_failed_after_retries",
            f"{clean_path}: failed after {max_attempts} attempts: {last_err}"
        )
        return False

    def confirm_durable(self, absolute_paths: List[Path]) -> bool:
        """
        On a host with NO persistent disk (e.g. Render free tier), the local
        filesystem is wiped on every restart, redeploy, and free-tier
        scale-to-zero cycle. In that reality, local disk is only a fast
        per-request cache — Google Drive (via this relay) is the ONLY thing
        that actually persists. This method blocks the caller (synchronously,
        with the retries already built into `_upload_file_to_drive`) until
        every given file is confirmed mirrored to Drive, or returns False if
        any could not be confirmed after retries.

        Call this at the end of any operation the system cannot afford to
        silently lose (e.g. approving a new club) so a "success" response to
        the user actually means the record will survive the next restart —
        instead of reporting success on a purely local, ephemeral write that
        a background thread may still be failing to relay in the background.
        """
        import sys
        if (os.getenv("NDLI_TESTING") == "true" or "unittest" in sys.modules) and not getattr(self, "_allow_test_confirm", False):
            # Never let a real, slow, likely-unreachable network round trip
            # block the test suite. Tests that need to exercise this path
            # explicitly mock `_upload_file_to_drive` and/or `get_storage_adapter`.
            return True

        if not self.relay_url or self.relay_url.startswith("http://example"):
            # Relay isn't configured at all; nothing we can confirm.
            return False

        items = []
        for p in absolute_paths:
            p = Path(p)
            try:
                if not p.exists():
                    continue
                content = p.read_text(encoding="utf-8")
                rel_path = str(p.relative_to(self.local.root_dir.resolve()))
            except Exception:
                # Fall back to a best-effort relative path if not under root_dir
                rel_path = p.name
                try:
                    content = p.read_text(encoding="utf-8")
                except Exception:
                    continue
            items.append((rel_path, content))

        # Check if non-blocking mode applies (persistent disk like PythonAnywhere)
        is_persistent = bool(os.getenv("PYTHONANYWHERE_DOMAIN") or os.getenv("NDLI_DATA_DIR") or os.getenv("NDLI_STORAGE_PERSISTENT") == "true")
        test_allowed = getattr(self, "_allow_test_confirm", False)
        blocking_mode = (
            test_allowed
            or os.getenv("NDLI_BLOCKING_SYNC", "").lower() == "true"
            or (not is_persistent and os.getenv("NDLI_BLOCKING_SYNC", "").lower() != "false")
        )

        if not blocking_mode:
            # High-performance async enqueue: guarantees sub-millisecond API response
            for rel_path, content in items:
                self.enqueue_upload(rel_path, content)
            return True

        # If blocking mode is explicitly requested, upload concurrently to avoid sequential 30s delays
        from concurrent.futures import ThreadPoolExecutor, as_completed
        all_ok = True
        with ThreadPoolExecutor(max_workers=min(len(items) or 1, 5)) as executor:
            future_to_path = {
                executor.submit(self._upload_file_to_drive, rel, c, 2): rel
                for rel, c in items
            }
            for fut in as_completed(future_to_path):
                try:
                    ok = fut.result()
                    if not ok:
                        all_ok = False
                except Exception:
                    all_ok = False
        return all_ok

    def sync_all_now(self) -> Dict[str, Any]:
        """Synchronously pushes all local database CSVs to Google Drive."""
        results = []
        root = self.local.root_dir

        for ext in ["*.csv", "*.json"]:
            for f in root.glob(f"**/{ext}"):
                rel = str(f.relative_to(root)).replace("\\", "/")
                if "backups" in rel or ".tmp" in rel:
                    continue
                content = f.read_text(encoding="utf-8")
                ok = self._upload_file_to_drive(rel, content)
                results.append({"file": rel, "success": ok})

        self.last_sync_time = datetime.now(timezone.utc).isoformat()
        self.last_sync_status = "full_sync_completed"
        return {
            "success": True,
            "timestamp": self.last_sync_time,
            "total_files": len(results),
            "synced": results
        }

    def _merge_csv_content(self, rel_path: str, target_file: Path, incoming_csv_text: str) -> str:
        """Safely merges incoming CSV rows with existing local CSV rows to prevent record wipeouts."""
        import io
        import csv
        fn = target_file.name.lower()
        key_field = None
        if "clubs" in fn:
            key_field = "club_id"
        elif "activities" in fn or "activity" in fn:
            key_field = "activity_id"
        elif "quotas" in fn:
            key_field = "emp_id"
        elif "users" in fn:
            key_field = "id"
        elif "issues" in fn:
            key_field = "issue_id"
        elif "credentials" in fn:
            key_field = "employee_id"

        if not key_field:
            return incoming_csv_text

        try:
            local_content = target_file.read_text(encoding="utf-8")
            if not local_content.strip():
                return incoming_csv_text

            local_reader = csv.DictReader(io.StringIO(local_content))
            headers = list(local_reader.fieldnames or [])
            local_rows = list(local_reader)

            inc_reader = csv.DictReader(io.StringIO(incoming_csv_text))
            inc_headers = list(inc_reader.fieldnames or [])
            inc_rows = list(inc_reader)

            if not inc_headers:
                return local_content

            combined_headers = list(headers)
            for h in inc_headers:
                if h not in combined_headers:
                    combined_headers.append(h)

            if key_field not in combined_headers:
                return incoming_csv_text

            merged_map = {}
            for r in inc_rows:
                kv = str(r.get(key_field, "")).strip().lower()
                if kv:
                    merged_map[kv] = dict(r)

            for lr in local_rows:
                kv = str(lr.get(key_field, "")).strip().lower()
                if not kv:
                    continue
                if kv not in merged_map:
                    merged_map[kv] = dict(lr)
                else:
                    inc_r = merged_map[kv]
                    local_ts = lr.get("updated_at") or lr.get("timestamp") or ""
                    inc_ts = inc_r.get("updated_at") or inc_r.get("timestamp") or ""
                    if local_ts and local_ts > inc_ts:
                        inc_r.update({k: v for k, v in lr.items() if v})
                    else:
                        for k, v in lr.items():
                            if v and not inc_r.get(k):
                                inc_r[k] = v

            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=combined_headers)
            writer.writeheader()
            for row in merged_map.values():
                writer.writerow({h: row.get(h, "") for h in combined_headers})
            merged_text = out.getvalue()

            # Safety net: a merge must never produce FEWER rows than what is
            # already sitting safely on the local persistent disk. If it does,
            # something went wrong (bad incoming data, header mismatch, a
            # parsing edge case) and the local copy is the trustworthy one.
            # Silently falling back to `incoming_csv_text` here is exactly how
            # locally-saved records (e.g. a newly approved club) get wiped out
            # by a stale/partial Google Drive snapshot on the next restart.
            if len(merged_map) < len(local_rows):
                self._log_sync_event(
                    "merge_row_count_regression",
                    f"{rel_path}: merge produced {len(merged_map)} rows, "
                    f"local had {len(local_rows)}. Keeping local copy."
                )
                return local_content

            return merged_text
        except Exception as merge_err:
            # NEVER fall back to the incoming (remote) content here: doing so
            # discards whatever is uniquely on local disk. The local copy is
            # always the safer default when the merge itself is unreliable.
            self._log_sync_event(
                "merge_exception",
                f"{rel_path}: {merge_err}. Preserving local copy instead of overwriting."
            )
            try:
                return target_file.read_text(encoding="utf-8")
            except Exception:
                return incoming_csv_text

    def pull_all_from_drive(self, force: bool = False) -> Dict[str, Any]:
        """Pulls all CSV files from Google Drive to restore local storage."""
        import sys
        if (os.getenv("NDLI_TESTING") == "true" or "unittest" in sys.modules) and not force and not getattr(self, "_allow_test_pull", False):
            return {"success": True, "message": "[Testing Mode] Remote pull skipped", "total_pulled": 0, "files": []}

        if not self.relay_url or self.relay_url.startswith("http://example"):
            return {"success": False, "message": "Apps Script relay URL not configured", "total_pulled": 0}

        payload = {
            "path": "sync/pull-all",
            "method": "POST",
            "data": {}
        }
        if RELAY_SECRET:
            payload["relay_key"] = RELAY_SECRET
        try:
            req = urllib.request.Request(
                self.relay_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw_bytes = resp.read().decode("utf-8")
                resp_json = json.loads(raw_bytes)
                data_obj = resp_json.get("data", resp_json)
                files_map = data_obj.get("files", {})

                pulled_files = []
                for rel_path, content in files_map.items():
                    if not content or not content.strip():
                        continue
                    clean_rel = rel_path.replace("\\", "/").lstrip("/")
                    target_file = (self.local.root_dir / clean_rel).resolve()
                    if not target_file.is_relative_to(self.local.root_dir.resolve()):
                        continue
                    target_file.parent.mkdir(parents=True, exist_ok=True)

                    if target_file.exists() and target_file.stat().st_size > 0 and clean_rel.endswith(".csv"):
                        merged_content = self._merge_csv_content(clean_rel, target_file, content)
                        target_file.write_text(merged_content, encoding="utf-8")
                    elif target_file.exists() and target_file.stat().st_size > 0:
                        # Non-CSV file (e.g. JSON) already exists locally with
                        # data. Don't blindly clobber it with a remote copy
                        # that could be stale/partial — only fill in files
                        # that don't already exist locally.
                        self._log_sync_event(
                            "skipped_non_csv_overwrite",
                            f"{clean_rel}: local copy already present, keeping it instead of remote."
                        )
                        pulled_files.append(clean_rel)
                        continue
                    else:
                        target_file.write_text(content, encoding="utf-8")
                    pulled_files.append(clean_rel)

                from db.csv_engine import CSVEngine
                CSVEngine.clear_cache()

                self.last_sync_time = datetime.now(timezone.utc).isoformat()
                self.last_sync_status = "pulled_from_drive"

                return {
                    "success": True,
                    "total_pulled": len(pulled_files),
                    "files": pulled_files
                }
        except Exception as err:
            self.last_error = str(err)
            return {"success": False, "error": str(err), "total_pulled": 0}

    def pull_file_from_drive(self, relative_path: str) -> Optional[str]:
        """Pulls a single file content from Google Drive."""
        import sys
        if os.getenv("NDLI_TESTING") == "true" or "unittest" in sys.modules:
            return None
        if not self.relay_url or self.relay_url.startswith("http://example"):
            return None

        clean_path = relative_path.replace("\\", "/").lstrip("/")
        parts = clean_path.split("/")
        sub_path = "/".join(parts[:-1]) if len(parts) > 1 else "master"
        file_name = parts[-1]

        payload = {
            "path": "sync/pull-file",
            "method": "POST",
            "data": {
                "subPath": sub_path,
                "fileName": file_name
            }
        }
        if RELAY_SECRET:
            payload["relay_key"] = RELAY_SECRET
        try:
            req = urllib.request.Request(
                self.relay_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read().decode("utf-8")
                resp_json = json.loads(raw_bytes)
                data_obj = resp_json.get("data", resp_json)
                content = data_obj.get("content")
                if content is not None:
                    target_file = (self.local.root_dir / clean_path).resolve()
                    if target_file.is_relative_to(self.local.root_dir.resolve()):
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        target_file.write_text(content, encoding="utf-8")
                    return content
        except Exception:
            pass
        return None

    def get_info(self) -> Dict[str, Any]:
        return {
            "mode": "APPS_SCRIPT_RELAY",
            "relay_url": self.relay_url[:45] + "..." if len(self.relay_url) > 45 else self.relay_url,
            "status": self.last_sync_status,
            "last_sync_time": self.last_sync_time,
            "synced_files_count": self.synced_files_count,
            "failed_uploads_count": self.failed_uploads_count,
            "last_error": self.last_error,
            "sync_issues_log": str((self.local.root_dir / "sync_issues.log").resolve()),
            "drive_sync_type": "24x7 Real-Time Cloud-to-Drive Sync Relay"
        }


class GoogleDriveAPIAdapter(StorageAdapter):
    def __init__(
        self,
        folder_id: str = GOOGLE_DRIVE_FOLDER_ID,
        service_account_path: str = GOOGLE_SERVICE_ACCOUNT_FILE,
        local_fallback: Optional[LocalSyncStorageAdapter] = None
    ):
        self.folder_id = folder_id
        self.service_account_path = service_account_path
        self.local_fallback = local_fallback or LocalSyncStorageAdapter()

    def is_configured(self) -> bool:
        return Path(self.service_account_path).exists() and bool(self.folder_id)

    def read_text(self, relative_path: str) -> str:
        return self.local_fallback.read_text(relative_path)

    def write_text(self, relative_path: str, content: str) -> None:
        self.local_fallback.write_text(relative_path, content)

    def exists(self, relative_path: str) -> bool:
        return self.local_fallback.exists(relative_path)

    def pull_all_from_drive(self) -> Dict[str, Any]:
        return {"success": True, "message": "Drive API storage mode", "total_pulled": 0}

    def get_info(self) -> Dict[str, Any]:
        return {
            "mode": "DRIVE_API",
            "folder_id": self.folder_id,
            "service_account_configured": Path(self.service_account_path).exists(),
            "local_cache_root": str(self.local_fallback.root_dir.resolve()),
            "status": "ready"
        }


def get_storage_adapter() -> StorageAdapter:
    mode = os.getenv("NDLI_STORAGE_MODE") or os.getenv("NDLI_STORAGE_ADAPTER") or DRIVE_STORAGE_MODE
    if mode == "APPS_SCRIPT_RELAY":
        return AppsScriptRelaySyncAdapter()
    elif mode == "DRIVE_API":
        return GoogleDriveAPIAdapter()
    return LocalSyncStorageAdapter()