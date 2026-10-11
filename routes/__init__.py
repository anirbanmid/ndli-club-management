"""
routes/ - the URL router for the NDLI Club Management server.

app.py owns the request handler (headers, auth, JSON, file IO).
THIS package owns the URL -> handler map: one ordered table per verb,
checked top to bottom exactly like the `if path == ...` chain it replaced.
Domain handlers live in the sibling modules (routes/clubs.py, ...).

R39 (CRITIQUE_AND_ROADMAP.md section 2) - mechanical extraction, no behavior change.
"""
import urllib.parse

from . import portals
from . import health
from . import auth_routes
from . import employees
from . import clubs
from . import migration
from . import metrics
from . import assistant
from . import sync_routes
from . import backup
from . import downloads
from . import issues
from . import certificate
from . import training
from . import activity
from . import data_admin

# A matcher is a tuple of predicates, OR-ed - same semantics as the old
# `path == x or path.startswith(y)` lines. E() = exact path, P() = path prefix.
def E(*keys):
    return tuple(("exact", k) for k in keys)


def P(*keys):
    return tuple(("prefix", k) for k in keys)


def match(table, path):
    """First handler whose matcher accepts path, else None."""
    for predicates, handler in table:
        for op, key in predicates:
            if op == "exact":
                if path == key:
                    return handler
            elif path.startswith(key):
                return handler
    return None

# Ordered exactly like the dispatch chain that lived in app.py.
GET_ROUTES = [
    (E('/favicon.ico'), portals.get_favicon),
    (P('/static/', '/docs/'), portals.get_static_assets),
    (E('/portal', '/index.html'), portals.get_index_portal),
    (E('/'), portals.get_root),
    (E('/manual', '/user-manual', '/documentation', '/user_manual', '/manual/view'), portals.get_user_manual_page),
    (E('/admin'), portals.get_admin_portal),
    (E('/login', '/employee/login'), portals.get_login_portal),
    (E('/employee') + P('/employee/'), portals.get_employee_portal),
    (E('/verify', '/certificate/verify', '/verify-certificate'), portals.get_verify_portal),
    (E('/api/health'), health.get_health),
    (E('/api/state-zone/map', '/api/states', '/api/states-zones'), health.get_state_zone_map),
    (E('/api/state-zone/lookup'), health.get_state_zone_lookup),
    (E('/api/auth/me'), auth_routes.get_auth_me),
    (E('/api/employees/roster'), employees.get_employees_roster),
    (E('/api/employees/profile'), employees.get_employees_profile),
    (E('/api/clubs/search'), clubs.get_clubs_search),
    (E('/api/activity/list'), activity.get_activity_list),
    (E('/api/admin/metrics'), metrics.get_admin_metrics),
    (E('/api/admin/employee-performance'), metrics.get_admin_employee_performance),
    (E('/api/admin/renewal-attention'), metrics.get_admin_renewal_attention),
    (E('/api/clubs/details'), clubs.get_clubs_details),
    (E('/api/admin/employees'), employees.get_admin_employees),
    (E('/api/admin/ai-insights'), metrics.get_admin_ai_insights),
    (E('/api/assistant/nudges'), assistant.get_assistant_nudges),
    (E('/api/assistant/insights'), assistant.get_assistant_insights),
    (E('/api/assistant/interactions'), assistant.get_assistant_interactions),
    (E('/api/assistant/audit'), assistant.get_assistant_audit),
    (E('/api/assistant/privacy'), assistant.get_assistant_privacy),
    (E('/api/sync/status'), sync_routes.get_sync_status),
    (E('/api/download/user-manual', '/api/download/manual', '/download/user-manual', '/download/manual', '/manual.pdf', '/NDLI_Club_Management_User_Manual.pdf', '/user-manual.pdf'), downloads.get_download_user_manual),
    (E('/api/download/promo-video', '/api/download/video', '/download/promo-video', '/download/video', '/ndli_promo_video.mp4', '/promo-video.mp4', '/video.mp4', '/promo-video', '/video'), downloads.get_download_promo_video),
    (E('/api/admin/download/master-clubs', '/api/admin/download/master_clubs.csv'), downloads.get_download_master_clubs),
    (E('/api/admin/sync-issues'), sync_routes.get_admin_sync_issues),
    (E('/api/admin/backup/status'), backup.get_backup_status),
    (E('/api/employee/download/activity-log', '/api/employee/download/activity_log.csv'), downloads.get_download_activity_log),
    (E('/api/employee/download/clubs-log', '/api/employee/download/clubs.csv'), downloads.get_download_clubs_log),
    (E('/api/issues/employee-reminders'), issues.get_issues_employee_reminders),
    (E('/api/issues/admin-reminders'), issues.get_issues_admin_reminders),
    (E('/api/issues/list'), issues.get_issues_list),
    (E('/api/issues/details'), issues.get_issues_details),
    (E('/api/certificate/settings'), certificate.get_certificate_settings),
    (E('/api/certificate/signature'), certificate.get_certificate_signature),
    (E('/api/certificate/verify'), certificate.get_certificate_verify),
    (E('/api/admin/drive/sync-now'), sync_routes.get_drive_sync_now),
    (E('/api/training/files'), training.get_training_files),
    (P('/api/training/download/'), training.get_training_download),
]

# Ordered exactly like the dispatch chain that lived in app.py.
POST_ROUTES = [
    (E('/api/assistant/ask'), assistant.post_assistant_ask),
    (E('/api/assistant/feedback'), assistant.post_assistant_feedback),
    (E('/api/assistant/outcome'), assistant.post_assistant_outcome),
    (E('/api/assistant/preferences'), assistant.post_assistant_preferences),
    (E('/api/assistant/forget'), assistant.post_assistant_forget),
    (E('/api/auth/login'), auth_routes.post_auth_login),
    (E('/api/auth/logout'), auth_routes.post_auth_logout),
    (E('/api/auth/change-password'), auth_routes.post_auth_change_password),
    (E('/api/auth/verify-password'), auth_routes.post_auth_verify_password),
    (E('/api/activity/log'), activity.post_activity_log),
    (E('/api/employee/activity/delete'), activity.post_activity_delete),
    (E('/api/clubs/bulk-import/validate', '/api/clubs/bulk-import/commit'), migration.post_bulk_import),
    (E('/api/admin/migration/clubs/validate', '/api/admin/migration/clubs/commit'), migration.post_migration_clubs),
    (E('/api/admin/migration/history/validate', '/api/admin/migration/history/commit'), migration.post_migration_history),
    (E('/api/clubs/create'), clubs.post_clubs_create),
    (E('/api/admin/data/hard-reset'), data_admin.post_hard_reset),
    (E('/api/admin/clubs/delete'), clubs.post_admin_clubs_delete),
    (E('/api/clubs/update'), clubs.post_clubs_update),
    (E('/api/clubs/correct-dates'), clubs.post_clubs_correct_dates),
    (E('/api/clubs/renew'), clubs.post_clubs_renew),
    (E('/api/admin/employees/status'), employees.post_admin_employees_status),
    (E('/api/admin/employees/create'), employees.post_admin_employees_create),
    (E('/api/admin/employees/update'), employees.post_admin_employees_update),
    (E('/api/sync/reconcile'), sync_routes.post_sync_reconcile),
    (E('/api/admin/backup/trigger', '/api/admin/backup/create'), backup.post_backup_trigger),
    (E('/api/admin/backup/restore', '/api/admin/backup/emergency-restore'), backup.post_backup_restore),
    (E('/api/issues/create'), issues.post_issues_create),
    (E('/api/issues/resolve'), issues.post_issues_resolve),
    (E('/api/certificate/qr-token'), certificate.post_certificate_qr_token),
    (E('/api/certificate/signature'), certificate.post_certificate_signature),
    (E('/api/certificate/settings'), certificate.post_certificate_settings),
    (E('/api/admin/drive/sync-now'), sync_routes.post_drive_sync_now),
    (E('/api/admin/drive/pull-now', '/api/sync/pull-now'), sync_routes.post_drive_pull_now),
    (E('/api/admin/training/upload'), training.post_training_upload),
    (E('/api/admin/training/delete'), training.post_training_delete),
]


def handle_get(h):
    """Dispatch a GET request. Mirrors the old _handle_do_GET exactly."""
    parsed_url = urllib.parse.urlparse(h.path)
    path = parsed_url.path
    query_params = urllib.parse.parse_qs(parsed_url.query)

    # /images/ alias for the user manual figures: docs/user_manual.html references
    # images/<file>; those files live in docs/images/, so map /images/* to /docs/images/*
    if path.startswith("/images/"):
        path = "/docs" + path

    handler = match(GET_ROUTES, path)
    if handler is None:
        h._send_error(f"Endpoint not found: {path}", status=404)
        return
    handler(h, path, query_params)


def handle_post(h):
    """Dispatch a POST request. Mirrors the old _handle_do_POST exactly."""
    parsed_url = urllib.parse.urlparse(h.path)
    path = parsed_url.path
    body = h._parse_json_body()

    handler = match(POST_ROUTES, path)
    if handler is None:
        h._send_error(f"Endpoint not found: {path}", status=404)
        return
    handler(h, path, body)

