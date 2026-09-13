"""
NDLI Club Management - Thread-Safe CSV Storage Engine
Provides atomic writes, schema-enforced reads/writes, and file locking.
"""
import os
import csv
import time
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

# Global lock dictionary to ensure thread-safe access per file
_FILE_LOCKS: Dict[str, threading.RLock] = {}
_GLOBAL_META_LOCK = threading.RLock()


def _get_lock(file_path: Path) -> threading.RLock:
    resolved = str(file_path.resolve())
    with _GLOBAL_META_LOCK:
        if resolved not in _FILE_LOCKS:
            _FILE_LOCKS[resolved] = threading.RLock()
        return _FILE_LOCKS[resolved]


class CSVEngine:
    """High-level thread-safe CSV manipulation engine with atomic write operations."""

    @staticmethod
    def ensure_file(file_path: Path, headers: List[str]) -> None:
        """Ensures that the CSV file exists with the specified header row."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        lock = _get_lock(file_path)
        with lock:
            if not file_path.exists() or file_path.stat().st_size == 0:
                with open(file_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    writer.writeheader()

    @staticmethod
    def read_all(file_path: Path, headers: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Reads all rows from CSV into a list of dictionaries."""
        if not file_path.exists():
            return []
        lock = _get_lock(file_path)
        with lock:
            with open(file_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = []
                for r in reader:
                    # Clean any trailing nulls or missing fields
                    cleaned = {k: (v if v is not None else "") for k, v in r.items() if k is not None}
                    rows.append(cleaned)
                return rows

    @staticmethod
    def write_all(file_path: Path, headers: List[str], rows: List[Dict[str, Any]]) -> None:
        """Atomically writes all rows to a CSV file using a temporary replacement strategy."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        lock = _get_lock(file_path)
        with lock:
            temp_path = file_path.parent / f"{file_path.name}.tmp.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}"
            try:
                with open(temp_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                    writer.writeheader()
                    for row in rows:
                        # Ensure all headers exist in row
                        normalized_row = {k: str(row.get(k, "")) for k in headers}
                        writer.writerow(normalized_row)
                # Atomic swap on POSIX, atomic replace on Windows with os.replace
                replaced = False
                for attempt in range(5):
                    try:
                        os.replace(temp_path, file_path)
                        replaced = True
                        break
                    except PermissionError:
                        time.sleep(0.05 * (attempt + 1))
                if not replaced:
                    # Fallback: if replace failed (e.g. transient Windows file handle lock), write directly
                    with open(file_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                        writer.writeheader()
                        for row in rows:
                            normalized_row = {k: str(row.get(k, "")) for k in headers}
                            writer.writerow(normalized_row)
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
        CSVEngine._notify_storage_adapter(file_path)

    @staticmethod
    def append_row(file_path: Path, headers: List[str], row: Dict[str, Any]) -> None:
        """Appends a single row to the CSV file safely."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        lock = _get_lock(file_path)
        with lock:
            file_exists = file_path.exists() and file_path.stat().st_size > 0
            with open(file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                if not file_exists:
                    writer.writeheader()
                normalized_row = {k: str(row.get(k, "")) for k in headers}
                writer.writerow(normalized_row)
        CSVEngine._notify_storage_adapter(file_path)

    @staticmethod
    def _notify_storage_adapter(file_path: Path) -> None:
        try:
            from db.storage_adapter import get_storage_adapter
            from config import DATA_DIR
            adapter = get_storage_adapter()
            if hasattr(adapter, "_upload_file_to_drive"):
                rel_path = str(file_path.relative_to(DATA_DIR))
                content = file_path.read_text(encoding="utf-8")
                threading.Thread(
                    target=adapter._upload_file_to_drive,
                    args=(rel_path, content),
                    daemon=True
                ).start()
        except Exception:
            pass

    @staticmethod
    def upsert_row(file_path: Path, headers: List[str], key_field: str, row: Dict[str, Any]) -> bool:
        """
        Inserts or updates a row matching key_field.
        Returns True if updated, False if inserted as new row.
        """
        CSVEngine.ensure_file(file_path, headers)
        lock = _get_lock(file_path)
        with lock:
            rows = CSVEngine.read_all(file_path, headers)
            updated = False
            target_key_val = str(row.get(key_field, "")).strip().lower()

            for i, r in enumerate(rows):
                if str(r.get(key_field, "")).strip().lower() == target_key_val:
                    # Update fields while preserving existing untouched fields
                    r.update({k: str(v) for k, v in row.items() if k in headers})
                    rows[i] = r
                    updated = True
                    break

            if not updated:
                normalized_row = {k: str(row.get(k, "")) for k in headers}
                rows.append(normalized_row)

            CSVEngine.write_all(file_path, headers, rows)
            return updated

    @staticmethod
    def search(file_path: Path, query: str, fields: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """
        Universal search: searches for query substring (case-insensitive) across all fields
        or specified fields.
        """
        if not file_path.exists():
            return []
        q = query.strip().lower()
        rows = CSVEngine.read_all(file_path)
        if not q:
            return rows

        matched = []
        for r in rows:
            searchable_text = " ".join([str(v) for k, v in r.items() if fields is None or k in fields]).lower()
            if q in searchable_text:
                matched.append(r)
        return matched
