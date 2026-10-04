"""
NDLI Club Management and Employee Activity Tracking System
Configuration Module
"""
import os
from pathlib import Path

# Base Directories
BASE_DIR = Path(__file__).resolve().parent

def _resolve_data_dir() -> Path:
    """
    Detects persistent storage location across deployment environments.
    1. NDLI_DATA_DIR / RENDER_DISK_PATH / PERSISTENT_STORAGE_DIR environment variables.
    2. Render persistent disk standard mount /var/data or /data if available and writable.
    3. Default to project data directory BASE_DIR / data.
    """
    env_dir = (
        os.getenv("NDLI_DATA_DIR")
        or os.getenv("RENDER_DISK_PATH")
        or os.getenv("PERSISTENT_STORAGE_DIR")
    )
    if env_dir:
        p = Path(env_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    for candidate in (Path("/var/data"), Path("/data")):
        try:
            if candidate.exists() and os.access(str(candidate), os.W_OK):
                return candidate.resolve()
        except Exception:
            pass

    default_dir = (BASE_DIR / "data").resolve()
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir

DATA_DIR = _resolve_data_dir()

# Google Drive Deployment Configuration
# Supports:
# 1. "LOCAL_SYNC": Local filesystem and Google Drive for Desktop
# 2. "APPS_SCRIPT_RELAY": Real-time 24x7 cloud sync to Google Drive via Apps Script Webhook
# 3. "DRIVE_API": Direct Google Drive API v3 via Service Account
DRIVE_STORAGE_MODE = os.getenv("NDLI_STORAGE_MODE") or os.getenv("NDLI_STORAGE_ADAPTER") or "APPS_SCRIPT_RELAY"
GOOGLE_DRIVE_FOLDER_ID = os.getenv("NDLI_DRIVE_FOLDER_ID", "ndli_drive_root_folder_id")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("NDLI_SERVICE_ACCOUNT_JSON", str(BASE_DIR / "service_account.json"))
APPS_SCRIPT_SYNC_URL = os.getenv(
    "NDLI_APPS_SCRIPT_SYNC_URL",
    "http://example.invalid/REPLACE_RELAY_URL_AT_HANDOVER"
)
# Optional shared secret appended to every relay payload. When set, the Apps
# Script relay should reject requests without it (see HANDOVER_SECURITY_CHECKLIST.md).
# Leave empty to keep legacy relay behavior.
RELAY_SECRET = os.getenv("NDLI_RELAY_SECRET", "")
AUTO_SYNC_INTERVAL_SEC = int(os.getenv("NDLI_AUTO_SYNC_INTERVAL_SEC", 300))

# Master Database Paths (CSV Files)
MASTER_DATA_DIR = DATA_DIR / "master"
MASTER_USERS_CSV = MASTER_DATA_DIR / "master_users.csv"
MASTER_CLUBS_CSV = MASTER_DATA_DIR / "master_clubs.csv"
MASTER_ACTIVITIES_CSV = MASTER_DATA_DIR / "master_activities.csv"
MASTER_QUOTAS_CSV = MASTER_DATA_DIR / "master_quotas.csv"
MASTER_ISSUES_CSV = MASTER_DATA_DIR / "master_issues.csv"

# Employee Node Base Directory, Signatures & Backups
EMPLOYEE_NODES_DIR = DATA_DIR / "employees"
BACKUP_DIR = DATA_DIR / "backups"
SIGNATURES_DIR = DATA_DIR / "signatures"

# Server Configuration (Supports 0.0.0.0 binding via NDLI_HOST and cloud $PORT for Render/Railway/Heroku/PythonAnywhere)
SERVER_HOST = os.getenv("NDLI_HOST") or ("0.0.0.0" if os.getenv("RENDER") or os.getenv("PORT") else "127.0.0.1")
SERVER_PORT = int(os.environ.get("PORT", os.getenv("NDLI_PORT", 8080)))
SESSION_EXPIRY_HOURS = 12

# --- Seed credentials (SECURITY: no credential literals live in this file) ---
# A fresh deployment gets its seed passwords from the NDLI_*_PASSWORD environment
# variables. Anything unset is GENERATED (secrets module) and persisted once to
# data/.seed_credentials.json (chmod 600, gitignored) so it stays stable across
# processes. Change those passwords after first login. See HANDOVER_SECURITY_CHECKLIST.md.
import json as _json
import secrets as _secrets

SEED_CREDENTIALS_FILE = DATA_DIR / ".seed_credentials.json"
SEED_CREDENTIALS_GENERATED = False


def _seed_password(env_var: str, user_id: str) -> str:
    """Resolve a seed credential: env var first, else generated + persisted."""
    global SEED_CREDENTIALS_GENERATED
    env_val = os.getenv(env_var)
    if env_val:
        return env_val
    store = {}
    if SEED_CREDENTIALS_FILE.exists():
        try:
            store = _json.loads(SEED_CREDENTIALS_FILE.read_text())
        except Exception:
            store = {}
    if store.get(user_id):
        return store[user_id]
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%^*-_=+"
    pwd = "".join(_secrets.choice(alphabet) for _ in range(24))
    store[user_id] = pwd
    SEED_CREDENTIALS_FILE.write_text(_json.dumps(store, indent=2) + "\n")
    try:
        os.chmod(SEED_CREDENTIALS_FILE, 0o600)
    except Exception:
        pass
    SEED_CREDENTIALS_GENERATED = True
    return pwd


# Admin Seed Account (IIT Kharagpur)
# NOTE: the default below is a TEST-ONLY seed. For a production/client
# deployment set the NDLI_ADMIN_PASSWORD environment variable before first
# boot (or use the in-app "Change Password" feature right after first login).
# See HANDOVER_SECURITY_CHECKLIST.md.
DEFAULT_ADMIN_EMAIL = "admin@iitkgp.ac.in"
DEFAULT_ADMIN_PASSWORD = _seed_password("NDLI_ADMIN_PASSWORD", "ADMIN01")
DEFAULT_ADMIN_NAME = "IIT Kharagpur Admin Office"

# 7 Initial Employees Mapping across India
INITIAL_EMPLOYEES = [
    {
        "id": "EMP01",
        "email": "emp.north@ndli.edu.in",
        "password": _seed_password("NDLI_EMP01_PASSWORD", "EMP01"),
        "full_name": "Rohan Sharma (North Zone)",
        "zone": "North",
        "assigned_states": "Jammu & Kashmir, Ladakh, Uttarakhand, Himachal Pradesh, Chandigarh, Punjab, Haryana, Delhi, Uttar Pradesh"
    },
    {
        "id": "EMP02",
        "email": "emp.central@ndli.edu.in",
        "password": _seed_password("NDLI_EMP02_PASSWORD", "EMP02"),
        "full_name": "Pooja Verma (Central Zone)",
        "zone": "Central",
        "assigned_states": "Madhya Pradesh, Chhattisgarh"
    },
    {
        "id": "EMP03",
        "email": "emp.west@ndli.edu.in",
        "password": _seed_password("NDLI_EMP03_PASSWORD", "EMP03"),
        "full_name": "Amit Patel (West Zone)",
        "zone": "West",
        "assigned_states": "Rajasthan, Gujarat, Maharashtra, Goa, Daman and Diu, Dadar & Nagar Haveli"
    },
    {
        "id": "EMP04",
        "email": "emp.east@ndli.edu.in",
        "password": _seed_password("NDLI_EMP04_PASSWORD", "EMP04"),
        "full_name": "Debabrata Ghosh (East Zone)",
        "zone": "East",
        "assigned_states": "Bihar, Jharkhand, West Bengal, Odisha"
    },
    {
        "id": "EMP05",
        "email": "emp.northeast@ndli.edu.in",
        "password": _seed_password("NDLI_EMP05_PASSWORD", "EMP05"),
        "full_name": "Mayanglambam Singh (North East Zone)",
        "zone": "North East",
        "assigned_states": "Sikkim, Assam, Arunachal Pradesh, Meghalaya, Manipur, Tripura, Nagaland, Mizoram"
    },
    {
        "id": "EMP06",
        "email": "emp.south1@ndli.edu.in",
        "password": _seed_password("NDLI_EMP06_PASSWORD", "EMP06"),
        "full_name": "K. Venkatesh (South Zone 1)",
        "zone": "South",
        "assigned_states": "Andhra Pradesh, Telangana, Karnataka"
    },
    {
        "id": "EMP07",
        "email": "emp.south2@ndli.edu.in",
        "password": _seed_password("NDLI_EMP07_PASSWORD", "EMP07"),
        "full_name": "Ananya Nair (South Zone 2)",
        "zone": "South",
        "assigned_states": "Tamil Nadu, Puducherry, Kerala, Andaman & Nicobar Island, Lakshadweep"
    }
]

# Support Log Types for SEC A
SUPPORT_TYPES = [
    "Phone call and remote assistance",
    "Closing of OS Ticket",
    "Online training",
    "Offline training"
]

# Re-export CSV Schemas
from db.schemas import (
    USER_FIELDS,
    CLUB_FIELDS,
    ACTIVITY_FIELDS,
    QUOTA_FIELDS,
    ISSUE_FIELDS
)

