"""
NDLI Club Management - CSV Database Schemas and Field Definitions
"""
from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import date, datetime, timezone
import re

# Master & Employee Users Schema
USER_FIELDS: List[str] = [
    "id",
    "email",
    "password_hash",
    "salt",
    "full_name",
    "role",             # "ADMIN" or "EMPLOYEE"
    "zone",             # Zone responsibility
    "assigned_states",  # Comma-separated or description
    "is_active",        # "1" or "0"
    "created_at"        # ISO 8601 string
]

# Clubs Database Schema (Used in both Master and Employee Nodes)
CLUB_FIELDS: List[str] = [
    "club_id",
    "reg_no",
    "institution_name",
    "state",
    "zone",
    "patron_email",
    "president_email",
    "secretary_email",
    "date_of_approval",
    "last_renewal_date",
    "renewal_date",
    "status",
    "approved_by_emp_id",
    "updated_at",
    "submission_timestamp",
    "next_renewal_date",
    "record_origin"     # R24: "created" (new club) | "imported" (legacy club historical entry)
]

# R30 (2026-10-09, client migration Phase 2): EMPLOYEE ACTIVITY HISTORY baselines.
# The client's legacy worksheets record per-period COUNTS with no club identity.
# Past and present are kept separate: migrated history lives in its own table,
# and Performance Quota = migrated baseline + live-derived counts. History rows
# NEVER carry club_id — no fabricated links (user-approved architecture).
MIGRATION_HISTORY_FIELDS: List[str] = [
    "hist_id",
    "emp_id",
    "period_year",           # event period (Year_id) — NEVER the entry timestamp
    "period_month",          # 01-12 when the client's month name parsed, else verbatim
    "period_week",           # client free text (e.g. "Date: 24-31"), kept verbatim
    "task_type",             # "Club Approval" | "Club Support" | "Online Workshop"
    "approvals_count",
    "support_count",
    "online_workshops_count",     # client column "No. of Physical Workshop" = ONLINE
    "user_registrations_count",
    "local_events_count",
    "global_events_count",
    "nature",                # "Remote support (AnyDesk)" | "On Call" | "Both (...)"
    "state",
    "zone",
    "entry_timestamp",       # client Timestamp_id (data-entry time; metadata only)
    "batch_id",
]

# Activity Log Schema (Daily Activity Tracker & SEC A Support Logs)
ACTIVITY_FIELDS: List[str] = [
    "activity_id",
    "emp_id",
    "timestamp",
    "support_type",       # "Phone call and remote assistance", "Closing of OS Ticket", "Online training", "Offline training", "Club Approval", "Registration Renewal"
    "priority_flag",      # "1" for Priority (Club approvals), "0" for Standard
    "club_id",           # Referenced Club ID if applicable
    "notes"               # Support notes / ticket number / institution name
]

# Performance Quotas Schema
QUOTA_FIELDS: List[str] = [
    "emp_id",
    "employee_name",
    "zone",
    "clubs_approved_count",      # R30: live-derived + migrated baseline
    "support_logs_count",         # R30: live-derived + migrated baseline
    "last_activity_timestamp",
    "legacy_clubs_count",         # R30: migrated baseline (from master_employee_history.csv)
    "legacy_support_count",
    "legacy_online_workshops_count"
]

# Unresolved Issues & Reminders Schema (72h employee reminder, 30d admin escalation, 7d recurrent)
ISSUE_FIELDS: List[str] = [
    "issue_id",
    "club_id",
    "emp_id",
    "institution_name",
    "state",
    "zone",
    "issue_note",
    "status",                   # "Unresolved" or "Resolved"
    "created_at",               # ISO 8601 string
    "reminder_due_at",          # ISO 8601 string (initial: created_at + 72 hours)
    "admin_reminder_due_at",    # ISO 8601 string (initial: created_at + 30 days)
    "last_reminded_at",         # ISO 8601 string
    "resolved_at",              # ISO 8601 string
    "resolved_by",              # emp_id or admin email
    "resolution_notes",         # Optional resolution notes
    "updated_at"                # ISO 8601 string
]

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def validate_email(email: str) -> bool:
    """Validates basic email formatting."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))

import re

# Round-2 (2026-09-25): strict server-side charset whitelists. Free-form text in
# these identifiers previously allowed stored-XSS payloads (inline onclick
# contexts) and made club IDs unreliable as keys.
# Round-3 (2026-09-26, CLIENT REQUISITION): Club ID is a WHOLE NUMBER — digits
# only (e.g. 2051). Applied strictly on NEW club entries; legacy club IDs that
# predate this rule remain editable so existing records never become orphans.
CLUB_ID_PATTERN = re.compile(r"^[0-9]{1,15}$")
LEGACY_CLUB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{2,63}$")
REG_NO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-/]{0,63}$")

# R24 (2026-10-08, CLIENT REQUIREMENT): "Import existing club" — historical date
# entry for legacy clubs migrating from the official NDLI portal. Event dates
# (formation/approval + last renewal) are validated strictly; the record-entry
# timestamp is separate metadata (updated_at / activity log).
# Business rule (user-confirmed): earliest allowed formation date = 2019-01-01.
MIN_FORMATION_DATE = date(2019, 1, 1)


def _parse_date_lenient(val: str) -> "date | None":
    """Extracts a calendar date from YYYY-MM-DD (or ISO datetime) input; None if unparseable."""
    s = str(val or "").strip()
    if not s:
        return None
    clean = s.split("T")[0].split(" ")[0].strip()
    try:
        return datetime.strptime(clean, "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_historical_dates(date_of_approval: str, last_renewal_date: str) -> List[str]:
    """
    R24 import/correction rules (user-confirmed business rules):
      - Date of Approval REQUIRED, 2019-01-01 <= doa <= today
      - Last Renewal Date optional; if present: doa <= lrd <= today
    Returns a list of error messages (empty = valid).
    """
    errors: List[str] = []
    today = datetime.now(timezone.utc).date()
    doa_raw = str(date_of_approval or "").strip()
    lrd_raw = str(last_renewal_date or "").strip()

    doa = _parse_date_lenient(doa_raw)
    if not doa_raw:
        errors.append("Date of Approval (club formation date) is required when importing an existing club.")
    elif doa is None:
        errors.append(f"Date of Approval must be a valid date (YYYY-MM-DD): '{doa_raw}'.")
    else:
        if doa < MIN_FORMATION_DATE:
            errors.append("Date of Approval cannot be earlier than 2019-01-01.")
        if doa > today:
            errors.append("Date of Approval cannot be in the future.")

    if lrd_raw:
        lrd = _parse_date_lenient(lrd_raw)
        if lrd is None:
            errors.append(f"Last Renewal Date must be a valid date (YYYY-MM-DD): '{lrd_raw}'.")
        else:
            if lrd > today:
                errors.append("Last Renewal Date cannot be in the future.")
            if doa and lrd < doa:
                errors.append("Last Renewal Date cannot be earlier than the Date of Approval.")
    return errors


def validate_club_payload(payload: Dict[str, Any]) -> List[str]:
    """Validates SEC C club details and returns a list of error messages."""
    errors = []
    required_fields = [
        ("club_id", "Club ID"),
        ("reg_no", "Registration Number"),
        ("institution_name", "Institution Name"),
        ("state", "State"),
        ("patron_email", "Patron E-Mail"),
        ("president_email", "President E-Mail"),
        ("secretary_email", "Secretary E-Mail")
    ]
    for key, label in required_fields:
        val = str(payload.get(key, "")).strip()
        if not val:
            errors.append(f"{label} is required.")

    # Identifier charset whitelists (round 2/3)
    club_id_val = str(payload.get("club_id", "")).strip()
    if club_id_val and not CLUB_ID_PATTERN.match(club_id_val):
        errors.append(
            "Club ID must be a whole number (digits only, e.g. 2051) as per client requisition. "
            "No letters, spaces or symbols."
        )
    reg_no_val = str(payload.get("reg_no", "")).strip()
    if reg_no_val and not REG_NO_PATTERN.match(reg_no_val):
        errors.append(
            "Registration Number may only contain letters, digits, spaces, dots, "
            "underscores, hyphens and slashes (max 64 characters)."
        )

    # Email validations
    for email_key, label in [
        ("patron_email", "Patron E-Mail"),
        ("president_email", "President E-Mail"),
        ("secretary_email", "Secretary E-Mail")
    ]:
        val = str(payload.get(email_key, "")).strip()
        if val and not validate_email(val):
            errors.append(f"Invalid email address for {label}: '{val}'.")

    # R24: record-mode-aware historical date validation.
    #  - "import": explicit formation/last-renewal dates REQUIRED and validated.
    #  - "new"/legacy: dates are auto-stamped server-side; explicit dates are
    #    REJECTED (no smuggling historical dates through the new-club path).
    mode = str(payload.get("record_mode", "")).strip().lower()
    if mode not in ("", "new", "import"):
        errors.append(f"Unknown record_mode '{mode}' — expected 'new' or 'import'.")
    else:
        doa_raw = str(payload.get("date_of_approval", "")).strip()
        lrd_raw = str(payload.get("last_renewal_date", "")).strip()
        if mode == "import":
            errors.extend(validate_historical_dates(doa_raw, lrd_raw))
        else:
            if doa_raw or lrd_raw:
                errors.append(
                    "Historical (past) dates are not accepted here — this door records NEW clubs only. "
                    "To import existing/pre-system clubs with their real dates, use the Admin Data "
                    "Migration portal (Bulk Club History Upload) instead."
                )

    return errors
