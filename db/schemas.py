"""
NDLI Club Management - CSV Database Schemas and Field Definitions
"""
from dataclasses import dataclass
from typing import List, Dict, Any
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
    "next_renewal_date"
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
    "clubs_approved_count",
    "support_logs_count",
    "last_activity_timestamp"
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

    # Email validations
    for email_key, label in [
        ("patron_email", "Patron E-Mail"),
        ("president_email", "President E-Mail"),
        ("secretary_email", "Secretary E-Mail")
    ]:
        val = str(payload.get(email_key, "")).strip()
        if val and not validate_email(val):
            errors.append(f"Invalid email address for {label}: '{val}'.")

    return errors
