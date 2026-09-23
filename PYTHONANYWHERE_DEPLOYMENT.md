# PythonAnywhere Deployment Guide (Free "Beginner" Plan)

This app runs on PythonAnywhere's free tier via the WSGI adapter in `wsgi.py`.
Free-tier properties this deployment relies on (verified against PythonAnywhere
docs on 2026-09-23):

- **Persistent filesystem** — `/home/<user>/...` survives restarts and redeploys
  (this replaces Render free's disk-less problem).
- **Web apps do not spin down** — no cold starts, no forced logouts from idle.
- **Outbound HTTP is allowlist-restricted**, but `script.google.com`
  (the Apps Script relay) and Google domains **are on the allowlist**, so
  Drive sync keeps working.
- Limits: 1 web app, 1 worker, 512 MB storage, browser console only (no SSH),
  CPU fair-use throttling.

---

## 1. Upload the code

In the PythonAnywhere **Bash console** (Dashboard → Consoles):

```bash
cd ~
git clone <your-private-repo-url> ndli-club-management
```

(Or upload a zip via the Files tab and unzip it.)

## 2. Create the persistent data directory

```bash
mkdir -p ~/ndli_data
```

This directory holds the CSV databases, backups, and signatures. Keeping it
**outside** the code folder means redeploys can never clobber live data.

## 3. Configure the web app (Web tab)

1. **Add a new web app** → Manual configuration → **Python 3.10** (or later) →
   set the source code path to `/home/<user>/ndli-club-management`.
2. Leave the virtualenv field **blank** (the app is 100% stdlib; no pip needed).
3. Edit the WSGI configuration file (link at the top of the Web tab,
   `/var/www/<user>_pythonanywhere_com_wsgi.py`) and replace its contents with:

```python
import os
import sys

# --- Environment (set BEFORE importing the app) ---
os.environ.setdefault("NDLI_DATA_DIR", "/home/<user>/ndli_data")
os.environ.setdefault("NDLI_STORAGE_MODE", "APPS_SCRIPT_RELAY")
os.environ.setdefault("NDLI_APPS_SCRIPT_SYNC_URL", "https://script.google.com/macros/s/<NEW_WEBAPP_ID>/exec")
# Optional: shared secret for the relay (see HANDOVER_SECURITY_CHECKLIST.md)
# os.environ.setdefault("NDLI_RELAY_SECRET", "<long random string>")
# Test-seed admin password used ONLY when the admin account is first created.
# Change the password in-app right after first login (see handover checklist).
os.environ.setdefault("NDLI_ADMIN_PASSWORD", "<strong password of your choice>")

# --- Application ---
project_path = "/home/<user>/ndli-club-management"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

from wsgi import application  # noqa: E402
```

4. **Static files (optional but recommended):** in the Web tab add a mapping
   `/static/` → `/home/<user>/ndli-club-management/static`. Free-tier nginx
   then serves CSS/JS/images directly. Everything still works without it
   (the app serves its own static files).

5. Click **Reload**. The site is live at `https://<user>.pythonanywhere.com`.

## 4. Verify

```bash
curl -s https://<user>.pythonanywhere.com/api/health
```

Then check in a browser: landing page (`/`), admin portal (`/admin`),
employee portal (`/employee`). Log in as admin and confirm the
**🔑 Change Password** item appears in the top navigation.

## 5. Notes & limits

- **Sessions are disk-backed**: sessions are saved in `~/ndli_data/sessions.json` so worker restarts, uWSGI recycling, or web app reloads do not log active users out.
- **High performance non-blocking sync**: on PythonAnywhere, form submissions (new club approvals and deletions) write to local disk instantly (< 1ms) and queue Drive uploads to background threads without hanging the UI.
- **CPU throttling & Polling**: Polling interval is set to 30 seconds to conserve PythonAnywhere CPU quota while maintaining real-time accuracy.
- **Backups** land in `~/ndli_data/backups/` and also sync to Drive via the relay.
- **Redeploys** (`git pull` in the project folder + Reload) never touch `~/ndli_data` — your database and sessions are safe.
- The WSGI adapter and the local `python app.py` server share all route code, so the 180-test suite validates exactly what runs in production.
