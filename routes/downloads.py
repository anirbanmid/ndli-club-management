"""
routes/downloads.py - File downloads (manuals, promo video, CSV exports)

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from config import BASE_DIR, MASTER_CLUBS_CSV, MASTER_USERS_CSV
from db.csv_engine import CSVEngine
from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS, USER_FIELDS
from db.sync_engine import SyncEngine

# path in [ "/api/download/user-manual", "/api/download/manual", "/download/user-manual", "/download/manual", "/manual.pdf", "/NDLI_Club_Management_User_Manual.pdf", "/user-manual.pdf" ]
def get_download_user_manual(h, path, query_params):
    user_manual_file = BASE_DIR / "NDLI_Club_Management_User_Manual.pdf"
    if not user_manual_file.exists():
        alt_path = BASE_DIR / "docs" / "NDLI_Club_Management_User_Manual.pdf"
        if alt_path.exists():
            user_manual_file = alt_path
        else:
            alt_static = BASE_DIR / "static" / "NDLI_Club_Management_User_Manual.pdf"
            if alt_static.exists():
                user_manual_file = alt_static

    if not user_manual_file.exists():
        h._send_error("User Manual PDF not found. Please compile it first.", status=404)
        return

    try:
        with open(user_manual_file, "rb") as f:
            pdf_bytes = f.read()

        disp_type = "inline" if ("inline" in query_params or "view" in query_params) else "attachment"
        h.send_response(200)
        h.send_header("Content-Type", "application/pdf")
        h.send_header("Content-Disposition", f'{disp_type}; filename="NDLI_Club_Management_User_Manual.pdf"')
        h.send_header("Content-Length", str(len(pdf_bytes)))
        h.send_header("Cache-Control", "public, max-age=3600")
        h.end_headers()
        h.wfile.write(pdf_bytes)
    except Exception as e:
        h._send_error(f"Error serving User Manual PDF: {str(e)}", status=500)
    return

# path in [ "/api/download/promo-video", "/api/download/video", "/download/promo-video", "/download/video", "/ndli_promo_video.mp4", "/promo-video.mp4", "/video.mp4", "/promo-video", "/video" ]
def get_download_promo_video(h, path, query_params):
    video_file = BASE_DIR / "ndli_promo_video.mp4"
    if not video_file.exists():
        alt_path = BASE_DIR / "static" / "ndli_promo_video.mp4"
        if alt_path.exists():
            video_file = alt_path

    if not video_file.exists():
        h._send_error("Promotional Video MP4 not found.", status=404)
        return

    try:
        with open(video_file, "rb") as f:
            video_bytes = f.read()

        disp_type = "attachment" if ("download" in query_params or path.startswith("/api/download")) else "inline"
        h.send_response(200)
        h.send_header("Content-Type", "video/mp4")
        h.send_header("Content-Disposition", f'{disp_type}; filename="NDLI_Promo_Video.mp4"')
        h.send_header("Content-Length", str(len(video_bytes)))
        h.send_header("Accept-Ranges", "bytes")
        h.send_header("Cache-Control", "public, max-age=86400")
        h.end_headers()
        h.wfile.write(video_bytes)
    except Exception as e:
        h._send_error(f"Error serving promo video: {str(e)}", status=500)
    return

# path in ["/api/admin/download/master-clubs", "/api/admin/download/master_clubs.csv"]
def get_download_master_clubs(h, path, query_params):
    if not h._check_admin_access():
        return
    if not MASTER_CLUBS_CSV.exists():
        CSVEngine.ensure_file(MASTER_CLUBS_CSV, CLUB_FIELDS)
    try:
        with open(MASTER_CLUBS_CSV, "rb") as f:
            content = f.read()
        h.send_response(200)
        h.send_header("Content-Type", "text/csv; charset=utf-8")
        h.send_header("Content-Disposition", 'attachment; filename="master_clubs.csv"')
        h.send_header("Content-Length", str(len(content)))
        h.end_headers()
        h.wfile.write(content)
    except Exception as e:
        h._send_error(f"Error serving master CSV: {str(e)}", status=500)
    return

# path in ["/api/employee/download/activity-log", "/api/employee/download/activity_log.csv"]
def get_download_activity_log(h, path, query_params):
    emp_id = query_params.get("emp_id", [""])[0]
    if not emp_id:
        session = h._get_auth_session()
        if session:
            emp_id = session.get("user_id", "")
    if not emp_id:
        h._send_error("Employee ID (emp_id) is required.", status=400)
        return
    clean_emp = emp_id.strip().upper()
    if not h._require_self_or_admin(clean_emp):
        return
    users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    emp_user = next((u for u in users if u.get("id", "").strip().upper() == clean_emp), None)
    if not emp_user:
        h._send_error(f"Employee account '{emp_id}' does not exist.", status=404)
        return
    if str(emp_user.get("is_active", "1")).strip() == "0":
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Download access denied.", status=403)
        return

    act_path = SyncEngine.get_employee_activities_path(clean_emp)
    if not act_path.exists():
        CSVEngine.ensure_file(act_path, ACTIVITY_FIELDS)
    try:
        with open(act_path, "rb") as f:
            content = f.read()
        h.send_response(200)
        h.send_header("Content-Type", "text/csv; charset=utf-8")
        h.send_header("Content-Disposition", 'attachment; filename="activity_log.csv"')
        h.send_header("Content-Length", str(len(content)))
        h.end_headers()
        h.wfile.write(content)
    except Exception as e:
        h._send_error(f"Error serving employee activity log: {str(e)}", status=500)
    return

# path in ["/api/employee/download/clubs-log", "/api/employee/download/clubs.csv"]
def get_download_clubs_log(h, path, query_params):
    emp_id = query_params.get("emp_id", [""])[0]
    if not emp_id:
        session = h._get_auth_session()
        if session:
            emp_id = session.get("user_id", "")
    if not emp_id:
        h._send_error("Employee ID (emp_id) is required.", status=400)
        return
    clean_emp = emp_id.strip().upper()
    if not h._require_self_or_admin(clean_emp):
        return
    users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    emp_user = next((u for u in users if u.get("id", "").strip().upper() == clean_emp), None)
    if not emp_user:
        h._send_error(f"Employee account '{emp_id}' does not exist.", status=404)
        return
    if str(emp_user.get("is_active", "1")).strip() == "0":
        h._send_error(f"Employee account '{emp_id}' is blocked or inactive. Download access denied.", status=403)
        return

    clubs_path = SyncEngine.get_employee_clubs_path(clean_emp)
    if not clubs_path.exists():
        CSVEngine.ensure_file(clubs_path, CLUB_FIELDS)
    try:
        with open(clubs_path, "rb") as f:
            content = f.read()
        h.send_response(200)
        h.send_header("Content-Type", "text/csv; charset=utf-8")
        h.send_header("Content-Disposition", 'attachment; filename="clubs.csv"')
        h.send_header("Content-Length", str(len(content)))
        h.end_headers()
        h.wfile.write(content)
    except Exception as e:
        h._send_error(f"Error serving employee clubs log: {str(e)}", status=500)
    return
