# Handover Security Checklist — Securing Passwords & Secrets at Final Deployment

Use this checklist when the system is handed over to the client / goes into
production. Everything here can be done without code changes.

---

## 1. Rotate ALL account passwords (15 min)

The repo ships with TEST-ONLY seed credentials. They must all be replaced.

| Account | Where to rotate | How |
|---|---|---|
| Master Admin (`admin@iitkgp.ac.in`) | Admin portal | top nav → **🔑 Change Password** |
| Each of the 7 employees | Admin portal | Employee Management → **Edit → new password → Save** |
| Any employees created later | Admin portal | same Edit dialog |

Rules for the new passwords:
- ≥ 16 random characters from a password manager (or `python -c "import secrets; print(secrets.token_urlsafe(20))"`)
- Unique per account; never reuse the demo pattern (`Seed#EMP01-Rotated2026`-style)
- Store in the client's password manager, hand over out-of-band

Verify afterwards: old passwords rejected at both portals; new ones work.

> The change-password API (`POST /api/auth/change-password`) requires the
> current password and enforces a minimum of 8 characters, so a stray session
> cannot silently reset an account.

## 2. Fresh-deploy password hygiene

When provisioning a NEW instance (e.g. the PythonAnywhere deployment):

- Set `NDLI_ADMIN_PASSWORD` in the WSGI config **before first boot**
  (see PYTHONANYWHERE_DEPLOYMENT.md). It seeds the admin account once;
  the TEST-ONLY default is never used when the variable is present.
- Immediately after first login, rotate it again via **🔑 Change Password**
  so even the deploy-time value is retired.
- Employee seeds (`config.py` → `INITIAL_EMPLOYEES`) are demo fixtures:
  have the admin set real per-employee passwords in Employee Management
  before real staff use the system.

## 3. Rotate the Apps Script relay URL (10 min)

The `.../macros/s/AKfyc.../exec` URL is a credential — it is in git history.

1. Open the Apps Script project → **Deploy → New deployment → Web app**
   (same "Execute as: Me" / "Anyone" settings) → copy the **new** `/exec` URL.
2. **Deploy → Manage deployments → old deployment → Delete** (retires the leaked URL).
3. Put the new URL ONLY in the host's environment
   (`NDLI_APPS_SCRIPT_SYNC_URL` in the PythonAnywhere WSGI file).
   Do not commit it anywhere.
4. Set the Apps Script project sharing to **Private**.

## 4. Enable the relay shared secret (recommended, 15 min)

Defense-in-depth if the URL ever leaks again.

**Server side (your app):** set in the WSGI config before first boot:
```python
os.environ.setdefault("NDLI_RELAY_SECRET", "<32+ random chars>")
```
Every relay payload then carries a `relay_key` field.

**Apps Script side:** at the top of the relay's `doPost(e)`:

```javascript
function doPost(e) {
  var expected = PropertiesService.getScriptProperties().getProperty("RELAY_SECRET");
  if (expected) {
    var body = JSON.parse(e.postData.contents || "{}");
    if (body.relay_key !== expected) {
      return ContentService.createTextOutput(
        JSON.stringify({ success: false, error: "unauthorized" })
      ).setMimeType(ContentService.MimeType.JSON);
    }
  }
  // ... existing handler code unchanged ...
}
```

Then in the Apps Script editor: **Project Settings → Script Properties** →
add `RELAY_SECRET` = the same value as in the WSGI config. Redeploy.

## 5. Git hygiene (30 min)

1. **Repo visibility → Private** (do this first; stops further exposure).
2. Purge secrets from history (old passwords, `data/*.csv` credential files,
   old webhook URL):
   ```bash
   git filter-repo --invert-paths --path data/ --path deployment_gas/Code.gs
   # plus a path/text scrub for the old literal values in config.py history
   ```
   (Or ask GitHub Support to run it.) Force-push afterwards and rotate
   everything in sections 1–3 again, since purging history does not
   un-leak anything already cloned.
3. Confirm `.gitignore` covers `data/`, `service_account.json`, `.env`.

## 6. Final verification

- [ ] Old admin + employee demo passwords rejected
- [ ] `GET /static/../data/master/master_users.csv` → 403
- [ ] `GET /api/admin/metrics` without token → 401
- [ ] `POST /api/activity/log` without token → 401
- [ ] `POST /api/admin/backup/trigger` without token → 401
- [ ] Old webhook URL dead (curl it → error), new URL syncs (Drive shows files)
- [ ] Repo private, history purged
- [ ] Backups visible in `~/ndli_data/backups/` and in Drive

---
*All of the above was designed so no code change is ever needed at handover —
the provisions (change-password API + UI, env-based seeds, relay secret,
admin gates) ship with the application.*
