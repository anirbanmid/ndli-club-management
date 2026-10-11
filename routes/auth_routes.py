"""
routes/auth_routes.py - Authentication & session endpoints

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from auth import AuthService
from config import MASTER_USERS_CSV
from db.csv_engine import CSVEngine
from db.schemas import USER_FIELDS

# path == "/api/auth/me"
def get_auth_me(h, path, query_params):
    session = h._get_auth_session()
    if not session:
        h._send_error("Unauthorized. Please log in.", status=401)
        return

    # Live sync with master_users.csv
    users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    found_user = None
    for u in users:
        if u.get("id", "").strip().upper() == session.get("user_id", "").strip().upper():
            found_user = u
            break

    auth_token = session.get("token", "")
    if not auth_token:
        auth_hdr = h.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            auth_token = auth_hdr.split(" ", 1)[1].strip()

    if not found_user:
        if auth_token:
            AuthService.logout(auth_token)
        h._send_error("User account no longer exists.", status=401)
        return

    if str(found_user.get("is_active", "1")).strip() != "1":
        if auth_token:
            AuthService.logout(auth_token)
        h._send_error("This account has been disabled or blocked by the Administrator.", status=401)
        return

    session["full_name"] = found_user.get("full_name", "")
    session["email"] = found_user.get("email", "")
    session["zone"] = found_user.get("zone", "")
    session["assigned_states"] = found_user.get("assigned_states", "")
    session["role"] = found_user.get("role", "EMPLOYEE")

    h._send_json({"authenticated": True, "user": session})
    return

# path == "/api/auth/login"
def post_auth_login(h, path, body):
    identifier = str(body.get("email", "") or body.get("user_id", "") or body.get("identifier", "")).strip()
    password = str(body.get("password", "")).strip()
    success, err, session_data = AuthService.authenticate(identifier, password)
    if not success:
        h._send_error(err or "Authentication failed.", status=401)
        return
    h._send_json({
        "success": True,
        "message": "Login successful.",
        "session": session_data
    })
    return

# path == "/api/auth/logout"
def post_auth_logout(h, path, body):
    token = body.get("token", "")
    if not token:
        auth_hdr = h.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr.split(" ", 1)[1].strip()
    AuthService.logout(token)
    h._send_json({"success": True, "message": "Logged out successfully."})
    return

# path == "/api/auth/change-password"
def post_auth_change_password(h, path, body):
    session = h._require_session()
    if not session:
        return
    identifier = str(body.get("user_id", "") or session.get("user_id", "")).strip()
    current_password = str(body.get("current_password", "") or body.get("password", "")).strip()
    new_password = str(body.get("new_password", "")).strip()
    if not current_password or not new_password:
        h._send_error("current_password and new_password are required.", status=400)
        return
    # Non-admins may only change their own password
    if session.get("role") != "ADMIN" and identifier.upper() != str(session.get("user_id", "")).upper():
        h._send_error("You may only change your own password.", status=403)
        return
    ok, err, user_record = AuthService.change_password(identifier, current_password, new_password)
    if not ok:
        h._send_error(err or "Password change failed.", status=400)
        return
    h._send_json({
        "success": True,
        "message": "Password changed successfully.",
        "user_id": user_record.get("id")
    })
    return

# path == "/api/auth/verify-password"
def post_auth_verify_password(h, path, body):
    identifier = str(body.get("user_id", "") or body.get("emp_id", "") or body.get("email", "") or body.get("identifier", "")).strip()
    password = str(body.get("password", "")).strip()

    if not identifier:
        session = h._get_auth_session()
        if session:
            identifier = session.get("user_id") or session.get("email", "")

    if not identifier:
        h._send_error("Employee identifier (user_id / email) is required.", status=400)
        return
    if not password:
        h._send_error("Password is required for verification.", status=400)
        return

    success, err, user_dict = AuthService.authenticate(identifier, password)
    if success and user_dict:
        h._send_json({
            "success": True,
            "valid": True,
            "message": "Password verified successfully.",
            "user_id": user_dict.get("user_id") or user_dict.get("id"),
            "role": user_dict.get("role")
        })
    else:
        h._send_error(err or "Incorrect password. Verification failed.", status=401)
    return
