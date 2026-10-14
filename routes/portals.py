"""
routes/portals.py - HTML portals + static assets

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
import json
import urllib.parse
from config import BASE_DIR

# path == "/favicon.ico"
def get_favicon(h, path, query_params):
    h._serve_file(BASE_DIR / "static" / "favicon.ico", "image/x-icon")
    return

# path.startswith("/static/") or path.startswith("/docs/")
def get_static_assets(h, path, query_params):
    rel_path = urllib.parse.unquote(path).lstrip("/")
    # Reject traversal attempts before any filesystem mapping
    if ".." in rel_path.split("/") or "\x00" in rel_path:
        h._send_error("Access denied: Invalid resource path.", status=403)
        return
    file_path = BASE_DIR / rel_path
    content_type = "application/octet-stream"
    if path.endswith(".css"):
        content_type = "text/css; charset=utf-8"
    elif path.endswith(".js"):
        content_type = "application/javascript; charset=utf-8"
    elif path.endswith(".html"):
        content_type = "text/html; charset=utf-8"
    elif path.endswith(".svg"):
        content_type = "image/svg+xml"
    elif path.endswith(".ico"):
        content_type = "image/x-icon"
    elif path.endswith(".png"):
        content_type = "image/png"
    elif path.endswith(".jpg") or path.endswith(".jpeg"):
        content_type = "image/jpeg"
    elif path.endswith(".webmanifest"):
        content_type = "application/manifest+json"
    elif path.endswith(".json"):
        content_type = "application/json; charset=utf-8"
    elif path.endswith(".pdf"):
        content_type = "application/pdf"
    h._serve_file(file_path, content_type)
    return

# path in ["/portal", "/index.html"]
def get_index_portal(h, path, query_params):
    h._serve_file(BASE_DIR / "templates" / "index.html")
    return

# path == "/"
def get_root(h, path, query_params):
    accept_header = h.headers.get("Accept", "")
    user_agent = h.headers.get("User-Agent", "")
    is_json_requested = (
        "application/json" in accept_header
        or query_params.get("format") == ["json"]
        or query_params.get("api") == ["1"]
        or (user_agent.startswith("Python-urllib") and "text/html" not in accept_header)
    )
    if is_json_requested:
        h._send_health_status()
        return

    h._serve_file(BASE_DIR / "templates" / "index.html")
    return

# path in ["/manual", "/user-manual", "/documentation", "/user_manual", "/manual/view"]
def get_user_manual_page(h, path, query_params):
    h._serve_file(BASE_DIR / "docs" / "user_manual.html", "text/html; charset=utf-8")
    return

# path == "/admin"
def get_admin_portal(h, path, query_params):
    h._serve_file(BASE_DIR / "templates" / "admin.html")
    return

# path in ["/login", "/employee/login"]
def get_login_portal(h, path, query_params):
    h._serve_file(BASE_DIR / "templates" / "employee.html")
    return

# path == "/employee" or path.startswith("/employee/")
def get_employee_portal(h, path, query_params):
    h._serve_file(BASE_DIR / "templates" / "employee.html")
    return

# path in ["/verify", "/certificate/verify", "/verify-certificate"]
def get_verify_portal(h, path, query_params):
    h._serve_file(BASE_DIR / "templates" / "verify.html", "text/html; charset=utf-8")
    return
