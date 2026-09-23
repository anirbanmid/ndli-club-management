"""
NDLI Club Management - Authentication and Session Management Engine
Supports Salted SHA-256 / PBKDF2 Password Hashing, Role Validation, and Token Management.
"""
import hashlib
import secrets
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple

from config import (
    MASTER_USERS_CSV,
    SESSION_EXPIRY_HOURS
)
from db.schemas import USER_FIELDS
from db.csv_engine import CSVEngine
from db.sync_engine import SyncEngine

_AUTH_LOCK = threading.RLock()

# In-memory Active Session Store: session_token -> session_data
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Generates PBKDF2-HMAC-SHA256 password hash with 100,000 iterations."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    ).hex()
    return hashed, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verifies cleartext password against stored hash and salt."""
    test_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(test_hash, stored_hash)


MIN_PASSWORD_LENGTH = 8


class AuthService:
    """Authentication and Session Management Service."""

    @classmethod
    def _find_and_verify(cls, identifier: str, password: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Core credential verification against master_users.csv.
        Returns: (success, error_message_or_none, user_record_or_none).
        The stored PBKDF2 hash is the single source of truth for every role --
        there are NO hardcoded/fallback password shortcuts in this path.
        """
        clean_input = str(identifier or "").strip()
        if not clean_input or not password:
            return False, "Email and password are required.", None

        clean_lower = clean_input.lower()
        clean_upper = clean_input.upper()

        users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
        user_record = None
        for u in users:
            u_email = u.get("email", "").strip().lower()
            u_id = u.get("id", "").strip().upper()
            if u_email == clean_lower or u_id == clean_upper:
                user_record = u
                break

        if not user_record:
            return False, "Invalid email or password.", None

        # Check if active
        if str(user_record.get("is_active", "1")).strip() != "1":
            return False, "This account has been disabled or blocked by the Administrator.", None

        # Verify hash (strict for every role -- no plaintext fallbacks)
        stored_hash = user_record.get("password_hash", "")
        salt = user_record.get("salt", "")
        if not verify_password(password, stored_hash, salt):
            return False, "Invalid email or password.", None

        return True, None, user_record

    @classmethod
    def authenticate(cls, email: str, password: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Authenticates an email or user ID and password against master_users.csv.
        Returns: (success: bool, error_message_or_none, session_dict_or_none)
        """
        ok, err, user_record = cls._find_and_verify(email, password)
        if not ok:
            return False, err, None

        # Create session
        token = secrets.token_hex(24)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_EXPIRY_HOURS)

        session_info = {
            "token": token,
            "user_id": user_record["id"],
            "email": user_record["email"],
            "full_name": user_record["full_name"],
            "role": user_record["role"],
            "zone": user_record.get("zone", ""),
            "assigned_states": user_record.get("assigned_states", ""),
            "expires_at": expires_at.isoformat()
        }

        with _AUTH_LOCK:
            _ACTIVE_SESSIONS[token] = session_info

        return True, None, session_info

    @classmethod
    def validate_session(cls, token: str) -> Optional[Dict[str, Any]]:
        """Validates session token, ensuring it exists and has not expired."""
        if not token:
            return None
        with _AUTH_LOCK:
            session = _ACTIVE_SESSIONS.get(token)
            if not session:
                return None
            # Check expiration
            expires_at = datetime.fromisoformat(session["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                del _ACTIVE_SESSIONS[token]
                return None
            return session.copy()

    @classmethod
    def logout(cls, token: str) -> bool:
        """Invalidates a session token."""
        with _AUTH_LOCK:
            if token in _ACTIVE_SESSIONS:
                del _ACTIVE_SESSIONS[token]
                return True
            return False

    @classmethod
    def register_or_update_user(
        cls,
        user_id: str,
        email: str,
        password: str,
        full_name: str,
        role: str = "EMPLOYEE",
        zone: str = "",
        assigned_states: str = "",
        is_active: str = "1"
    ) -> Dict[str, Any]:
        """Creates or updates a user in Master and Employee Node databases."""
        with _AUTH_LOCK:
            pwd_hash, salt = hash_password(password)
            now_iso = datetime.now(timezone.utc).isoformat()

            user_record = {
                "id": user_id,
                "email": email.strip().lower(),
                "password_hash": pwd_hash,
                "salt": salt,
                "full_name": full_name,
                "role": role,
                "zone": zone,
                "assigned_states": assigned_states,
                "is_active": str(is_active),
                "created_at": now_iso
            }

            # Update master users
            CSVEngine.upsert_row(MASTER_USERS_CSV, USER_FIELDS, "id", user_record)

            # If employee, also write to their node
            if role.upper() == "EMPLOYEE":
                SyncEngine.provision_employee_node(
                    emp_id=user_id,
                    email=email,
                    password_hash=pwd_hash,
                    salt=salt,
                    full_name=full_name,
                    zone=zone,
                    assigned_states=assigned_states,
                    is_active=is_active,
                    created_at=now_iso
                )

            return user_record

    @classmethod
    def set_user_status(cls, user_id: str, is_active: Any) -> bool:
        """Blocks or unblocks user access."""
        with _AUTH_LOCK:
            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            target = None
            is_active_flag = str(is_active).strip().lower() in ["1", "true", "yes"]
            for u in users:
                if u.get("id") == user_id:
                    u["is_active"] = "1" if is_active_flag else "0"
                    target = u
                    break
            if not target:
                return False

            CSVEngine.write_all(MASTER_USERS_CSV, USER_FIELDS, users)

            # Also update node if employee
            if target.get("role") == "EMPLOYEE":
                node_cred = SyncEngine.get_employee_credentials_path(user_id)
                if node_cred.exists():
                    CSVEngine.upsert_row(node_cred, USER_FIELDS, "id", target)

            # If blocking, invalidate active sessions for this user
            if not is_active_flag:
                for token, sess in list(_ACTIVE_SESSIONS.items()):
                    if sess.get("user_id") == user_id:
                        del _ACTIVE_SESSIONS[token]

            return True

    @classmethod
    def update_employee(
        cls,
        old_emp_id: str,
        new_emp_id: str,
        email: str,
        full_name: str,
        zone: str,
        assigned_states: str,
        password: Optional[str] = None,
        is_active: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Updates employee fields and syncs with node database and active sessions."""
        with _AUTH_LOCK:
            clean_old = str(old_emp_id or "").strip().upper()
            clean_new = str(new_emp_id or old_emp_id or "").strip().upper()
            clean_email = str(email or "").strip().lower()

            if not clean_old:
                return False, "Original employee ID is required.", None
            if not clean_new:
                return False, "New employee ID cannot be blank.", None
            if not clean_email:
                return False, "Email cannot be blank.", None
            if not str(full_name or "").strip():
                return False, "Full name cannot be blank.", None

            users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
            target = None
            for u in users:
                if u.get("id", "").strip().upper() == clean_old:
                    target = u
                    break
            if not target:
                return False, f"Employee with ID '{old_emp_id}' not found.", None

            # Check collision if ID changed
            if clean_new != clean_old:
                for u in users:
                    if u.get("id", "").strip().upper() == clean_new:
                        return False, f"Employee ID '{clean_new}' already exists.", None

            # Check collision if email changed
            if clean_email != target.get("email", "").strip().lower():
                for u in users:
                    if u.get("id", "").strip().upper() != clean_old and u.get("email", "").strip().lower() == clean_email:
                        return False, f"Email '{clean_email}' is already in use by another user.", None

            pwd_hash = None
            salt = None
            if password and str(password).strip():
                pwd_hash, salt = hash_password(str(password).strip())

            updated_record = SyncEngine.update_employee_records(
                old_emp_id=clean_old,
                new_emp_id=clean_new,
                full_name=str(full_name).strip(),
                email=clean_email,
                zone=str(zone or "").strip(),
                assigned_states=str(assigned_states or "").strip(),
                password_hash=pwd_hash,
                salt=salt,
                is_active=is_active
            )

            if not updated_record:
                return False, "Failed to update employee records.", None

            # Sync active sessions for this user
            for token, sess in list(_ACTIVE_SESSIONS.items()):
                if sess.get("user_id", "").strip().upper() == clean_old:
                    if str(updated_record.get("is_active", "1")).strip() != "1":
                        del _ACTIVE_SESSIONS[token]
                    else:
                        sess["user_id"] = clean_new
                        sess["full_name"] = updated_record["full_name"]
                        sess["email"] = updated_record["email"]
                        sess["zone"] = updated_record["zone"]
                        sess["assigned_states"] = updated_record["assigned_states"]

            return True, None, updated_record

    @classmethod
    def change_password(
        cls,
        identifier: str,
        current_password: str,
        new_password: str
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Self-service password change for any role (ADMIN or EMPLOYEE).
        Requires the CURRENT password (proves account ownership), then stores a
        fresh PBKDF2 hash + new salt into master_users.csv and -- for employees --
        into their node credentials file. This is the provision used at client
        handover to rotate every seeded/dummy credential.
        Returns: (success, error_message_or_none, updated_user_record_or_none)
        """
        clean_new = str(new_password or "").strip()
        if len(clean_new) < MIN_PASSWORD_LENGTH:
            return False, f"New password must be at least {MIN_PASSWORD_LENGTH} characters long.", None
        if str(current_password or "") == clean_new:
            return False, "New password must be different from the current password.", None

        with _AUTH_LOCK:
            ok, err, user_record = cls._find_and_verify(identifier, current_password)
            if not ok:
                return False, "Current password is incorrect.", None

            pwd_hash, salt = hash_password(clean_new)
            user_record["password_hash"] = pwd_hash
            user_record["salt"] = salt

            CSVEngine.upsert_row(MASTER_USERS_CSV, USER_FIELDS, "id", user_record)

            if str(user_record.get("role", "")).upper() == "EMPLOYEE":
                node_cred = SyncEngine.get_employee_credentials_path(user_record.get("id", ""))
                if node_cred.exists():
                    CSVEngine.upsert_row(node_cred, USER_FIELDS, "id", user_record)

            return True, None, user_record

