# NDLI Club Management -- Auto-Generated API Reference

<!-- GENERATED FILE -- DO NOT EDIT BY HAND.
     Source of truth: routes/ (dispatch tables in routes/__init__.py).
     Regenerate: python3 gen_api_docs.py   |   drift gate: python3 gen_api_docs.py --check -->

**81 dispatch entries** (46 GET + 35 POST) across **16 route modules**, covering **116 distinct paths**. Counts and rows below are measured from `routes/__init__.py` at generation time -- if the router changes, `python3 gen_api_docs.py --check` fails until this file is regenerated.

## Dispatch model

Every HTTP request lands in `app.py` (`NDLIRequestHandler`), which parses the  
URL / body and hands the path to `routes.match(GET_ROUTES | POST_ROUTES, path)`  
(`routes/__init__.py`). The tables are ordered **exactly like the old dispatch  
chain**: the first row whose matcher accepts the path wins. A matcher is a set  
of OR-ed predicates -- `E(...)` = exact path, `P(...)` = path prefix (marked  
`*` below). A handler is `routes/<module>.<function>(h, path, query_params)`  
for GET and `(h, path, body)` for POST.  

Path legend: no suffix = exact match (`E(...)`), `*` = path-prefix match (`P(...)`).

## GET endpoints (dispatch order)

| # | Path | Match | Handler | Module |
|---|------|-------|---------|--------|
| 1 | `/favicon.ico` | exact | `portals.get_favicon` | `portals` |
| 2 | `/static/*`, `/docs/*` | prefix | `portals.get_static_assets` | `portals` |
| 3 | `/portal`, `/index.html` | exact | `portals.get_index_portal` | `portals` |
| 4 | `/` | exact | `portals.get_root` | `portals` |
| 5 | `/manual`, `/user-manual`, `/documentation`, `/user_manual`, `/manual/view` | exact | `portals.get_user_manual_page` | `portals` |
| 6 | `/admin` | exact | `portals.get_admin_portal` | `portals` |
| 7 | `/login`, `/employee/login` | exact | `portals.get_login_portal` | `portals` |
| 8 | `/employee`, `/employee/*` | exact+prefix | `portals.get_employee_portal` | `portals` |
| 9 | `/verify`, `/certificate/verify`, `/verify-certificate` | exact | `portals.get_verify_portal` | `portals` |
| 10 | `/api/health` | exact | `health.get_health` | `health` |
| 11 | `/api/state-zone/map`, `/api/states`, `/api/states-zones` | exact | `health.get_state_zone_map` | `health` |
| 12 | `/api/state-zone/lookup` | exact | `health.get_state_zone_lookup` | `health` |
| 13 | `/api/auth/me` | exact | `auth_routes.get_auth_me` | `auth_routes` |
| 14 | `/api/employees/roster` | exact | `employees.get_employees_roster` | `employees` |
| 15 | `/api/employees/profile` | exact | `employees.get_employees_profile` | `employees` |
| 16 | `/api/clubs/search` | exact | `clubs.get_clubs_search` | `clubs` |
| 17 | `/api/activity/list` | exact | `activity.get_activity_list` | `activity` |
| 18 | `/api/admin/metrics` | exact | `metrics.get_admin_metrics` | `metrics` |
| 19 | `/api/admin/employee-performance` | exact | `metrics.get_admin_employee_performance` | `metrics` |
| 20 | `/api/admin/renewal-attention` | exact | `metrics.get_admin_renewal_attention` | `metrics` |
| 21 | `/api/clubs/details` | exact | `clubs.get_clubs_details` | `clubs` |
| 22 | `/api/admin/employees` | exact | `employees.get_admin_employees` | `employees` |
| 23 | `/api/admin/ai-insights` | exact | `metrics.get_admin_ai_insights` | `metrics` |
| 24 | `/api/assistant/nudges` | exact | `assistant.get_assistant_nudges` | `assistant` |
| 25 | `/api/assistant/insights` | exact | `assistant.get_assistant_insights` | `assistant` |
| 26 | `/api/assistant/interactions` | exact | `assistant.get_assistant_interactions` | `assistant` |
| 27 | `/api/assistant/audit` | exact | `assistant.get_assistant_audit` | `assistant` |
| 28 | `/api/assistant/privacy` | exact | `assistant.get_assistant_privacy` | `assistant` |
| 29 | `/api/sync/status` | exact | `sync_routes.get_sync_status` | `sync_routes` |
| 30 | `/api/download/user-manual`, `/api/download/manual`, `/download/user-manual`, `/download/manual`, `/manual.pdf`, `/NDLI_Club_Management_User_Manual.pdf`, `/user-manual.pdf` | exact | `downloads.get_download_user_manual` | `downloads` |
| 31 | `/api/download/promo-video`, `/api/download/video`, `/download/promo-video`, `/download/video`, `/ndli_promo_video.mp4`, `/promo-video.mp4`, `/video.mp4`, `/promo-video`, `/video` | exact | `downloads.get_download_promo_video` | `downloads` |
| 32 | `/api/admin/download/master-clubs`, `/api/admin/download/master_clubs.csv` | exact | `downloads.get_download_master_clubs` | `downloads` |
| 33 | `/api/admin/sync-issues` | exact | `sync_routes.get_admin_sync_issues` | `sync_routes` |
| 34 | `/api/admin/backup/status` | exact | `backup.get_backup_status` | `backup` |
| 35 | `/api/employee/download/activity-log`, `/api/employee/download/activity_log.csv` | exact | `downloads.get_download_activity_log` | `downloads` |
| 36 | `/api/employee/download/clubs-log`, `/api/employee/download/clubs.csv` | exact | `downloads.get_download_clubs_log` | `downloads` |
| 37 | `/api/issues/employee-reminders` | exact | `issues.get_issues_employee_reminders` | `issues` |
| 38 | `/api/issues/admin-reminders` | exact | `issues.get_issues_admin_reminders` | `issues` |
| 39 | `/api/issues/list` | exact | `issues.get_issues_list` | `issues` |
| 40 | `/api/issues/details` | exact | `issues.get_issues_details` | `issues` |
| 41 | `/api/certificate/settings` | exact | `certificate.get_certificate_settings` | `certificate` |
| 42 | `/api/certificate/signature` | exact | `certificate.get_certificate_signature` | `certificate` |
| 43 | `/api/certificate/verify` | exact | `certificate.get_certificate_verify` | `certificate` |
| 44 | `/api/admin/drive/sync-now` | exact | `sync_routes.get_drive_sync_now` | `sync_routes` |
| 45 | `/api/training/files` | exact | `training.get_training_files` | `training` |
| 46 | `/api/training/download/*` | prefix | `training.get_training_download` | `training` |

## POST endpoints (dispatch order)

| # | Path | Match | Handler | Module |
|---|------|-------|---------|--------|
| 1 | `/api/assistant/ask` | exact | `assistant.post_assistant_ask` | `assistant` |
| 2 | `/api/assistant/feedback` | exact | `assistant.post_assistant_feedback` | `assistant` |
| 3 | `/api/assistant/outcome` | exact | `assistant.post_assistant_outcome` | `assistant` |
| 4 | `/api/assistant/preferences` | exact | `assistant.post_assistant_preferences` | `assistant` |
| 5 | `/api/assistant/forget` | exact | `assistant.post_assistant_forget` | `assistant` |
| 6 | `/api/auth/login` | exact | `auth_routes.post_auth_login` | `auth_routes` |
| 7 | `/api/auth/logout` | exact | `auth_routes.post_auth_logout` | `auth_routes` |
| 8 | `/api/auth/change-password` | exact | `auth_routes.post_auth_change_password` | `auth_routes` |
| 9 | `/api/auth/verify-password` | exact | `auth_routes.post_auth_verify_password` | `auth_routes` |
| 10 | `/api/activity/log` | exact | `activity.post_activity_log` | `activity` |
| 11 | `/api/employee/activity/delete` | exact | `activity.post_activity_delete` | `activity` |
| 12 | `/api/clubs/bulk-import/validate`, `/api/clubs/bulk-import/commit` | exact | `migration.post_bulk_import` | `migration` |
| 13 | `/api/admin/migration/clubs/validate`, `/api/admin/migration/clubs/commit` | exact | `migration.post_migration_clubs` | `migration` |
| 14 | `/api/admin/migration/history/validate`, `/api/admin/migration/history/commit` | exact | `migration.post_migration_history` | `migration` |
| 15 | `/api/clubs/create` | exact | `clubs.post_clubs_create` | `clubs` |
| 16 | `/api/admin/data/hard-reset` | exact | `data_admin.post_hard_reset` | `data_admin` |
| 17 | `/api/admin/clubs/delete` | exact | `clubs.post_admin_clubs_delete` | `clubs` |
| 18 | `/api/clubs/update` | exact | `clubs.post_clubs_update` | `clubs` |
| 19 | `/api/clubs/correct-dates` | exact | `clubs.post_clubs_correct_dates` | `clubs` |
| 20 | `/api/clubs/renew` | exact | `clubs.post_clubs_renew` | `clubs` |
| 21 | `/api/admin/employees/status` | exact | `employees.post_admin_employees_status` | `employees` |
| 22 | `/api/admin/employees/create` | exact | `employees.post_admin_employees_create` | `employees` |
| 23 | `/api/admin/employees/update` | exact | `employees.post_admin_employees_update` | `employees` |
| 24 | `/api/sync/reconcile` | exact | `sync_routes.post_sync_reconcile` | `sync_routes` |
| 25 | `/api/admin/backup/trigger`, `/api/admin/backup/create` | exact | `backup.post_backup_trigger` | `backup` |
| 26 | `/api/admin/backup/restore`, `/api/admin/backup/emergency-restore` | exact | `backup.post_backup_restore` | `backup` |
| 27 | `/api/issues/create` | exact | `issues.post_issues_create` | `issues` |
| 28 | `/api/issues/resolve` | exact | `issues.post_issues_resolve` | `issues` |
| 29 | `/api/certificate/qr-token` | exact | `certificate.post_certificate_qr_token` | `certificate` |
| 30 | `/api/certificate/signature` | exact | `certificate.post_certificate_signature` | `certificate` |
| 31 | `/api/certificate/settings` | exact | `certificate.post_certificate_settings` | `certificate` |
| 32 | `/api/admin/drive/sync-now` | exact | `sync_routes.post_drive_sync_now` | `sync_routes` |
| 33 | `/api/admin/drive/pull-now`, `/api/sync/pull-now` | exact | `sync_routes.post_drive_pull_now` | `sync_routes` |
| 34 | `/api/admin/training/upload` | exact | `training.post_training_upload` | `training` |
| 35 | `/api/admin/training/delete` | exact | `training.post_training_delete` | `training` |

## Related hand-written sections

The manual keeps request/response semantics in **sections 11-12** (REST API Specification) and per-module prose in **section 7** -- those are hand-authored. This file is the complete machine-generated index and never carries semantics, so it cannot disagree with the router.
