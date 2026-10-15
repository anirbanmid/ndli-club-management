# Operations Handover — Accounts, Alerts & Incident Playbook

**Purpose:** this is the "who owns what and what to do when it breaks" document.
The user manual explains the *application*; this file explains the *machine room*
around it. Read it before any ownership/operations handover, and keep it updated
when accounts change.

**Related docs:** `HANDOVER_SECURITY_CHECKLIST.md` (password rotation) ·
`PYTHONANYWHERE_DEPLOYMENT.md` (hosting) · `docs/ops/DEPLOY_WORKFLOW.md`
(release process) · `docs/API_REFERENCE.md` + `docs/ARCHITECTURE_MAP.md`
(auto-generated technical references).

---

## 1. Account inventory

Credentials never live in this repo. Each row below is stored in the owner's
password manager / the named platform; the "Transfer" column says what must
change hands at handover.

| Asset | Where it lives | What it does | Transfer at handover |
|---|---|---|---|
| PythonAnywhere account | pythonanywhere.com (`anirbanmid`) | Hosts the live app | Change account email/password; owner adds client as enabled user or hands over account |
| GitHub repository | `anirbanmid/ndli-club-management` | Source of truth for code | Invite client; revoke old PATs |
| Google Drive folder | Shared "NDLI" drive area | CSV backups + weekly zips (GAS mirror) | Share folder to client's Google account |
| Apps Script relay project | `script.google.com` (owner's Google account) | Portal sync relay + weekly backup trigger | Transfer project ownership (or re-create under client account) |
| Telegram bot ("NDLI Club Management Alert") | BotFather (owner's Telegram) | Uptime alerts to the phone | Client sends `/start` to the bot; alert chat re-pointed (see §4) |
| Uptime watcher script | `docs/ops/NDLI_Uptime_Watcher.gs` deployed in owner's Apps Script | 5-min site check → Telegram alerts | See §5 (three transfer options) |
| LLM API key (`NDLI_ASSISTANT_API_KEY`) | PA WSGI env var | Powers the "Robu" assistant | Rotate key; set new value in PA env |

## 2. Data map (where the truth lives)

- **`/home/anirbanmid/ndli_data/`** (PA persistent disk) — the live CSV store.
  `data/` inside the repo is runtime-only and gitignored on purpose
  (see AGENTS.md hard rules — it leaked data once).
- **Google Drive** — weekly zip backups via the frozen GAS backup trigger
  (the DR backbone), plus mirrored CSVs.
- **`<data_dir>/sync_issues.log`** — sync failure log. NOT in the repo. First
  stop when portal data looks wrong.
- **CSV export** — the client's permanent escape hatch: every store is
  human-readable CSV. Any future storage change must preserve this.

## 3. Monitoring & alerts (what the phone messages mean)

The uptime watcher checks `https://anirbanmid.pythonanywhere.com/` every
5 minutes and stays silent when healthy.

| Message | Meaning | First response |
|---|---|---|
| `🚨 NDLI site is DOWN ...` | Site unreachable or non-200 | Run §6 playbook (start with the PA Web tab) |
| Reminder (max 1/hour) | Still down | Same playbook; escalate |
| `✅ ... back UP` | Recovered | Nothing — but note the outage window |
| `✅ NDLI monitor armed` | Setup/test message | None |

## 4. Client-handover checklist — alert re-point (2 minutes)

When ownership moves to the client, the alerts must move to the **client's** phone:

1. Client installs Telegram, sends **`/start`** to the bot ("NDLI Club Management Alert").
2. Find the client's chat id: run `setup()` again (auto-discovers from `getUpdates`),
   or open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read
   `"chat":{"id": <number>}`, or use `@userinfobot` on the client's phone
   (private chat id == user id).
3. Decide the routing (ASK the current owner first):
   - **client only** — replace `CHAT_ID` via the `setChatId()` helper,
   - **group with both parties** — create a Telegram group with client + owner,
     add the bot, use the group's chat id,
   - **owner keeps + client added** — extend `sendTelegram()` to a list of chat ids.
4. Trigger a **test alert** to confirm the client's phone buzzes.
5. Update this file's §1 transfer column + record the change in the ops log.

## 5. Watcher transfer options

The watcher is one small Apps Script file (`docs/ops/NDLI_Uptime_Watcher.gs`).
The BotFather token is pasted inside the deployed copy — **never commit it**
(the repo copy ships with the `PASTE_YOUR_BOT_TOKEN_HERE` placeholder on purpose).

- **Option A — client's own accounts:** client creates their own bot (BotFather),
  pastes the script + their token into *their* `script.google.com`, runs `setup()`,
  adds the 5-minute `checkSite` trigger. Cleanest ownership.
- **Option B — stays with current owner:** nothing to move; only the alert
  chat re-point (§4) changes at handover.
- **Option C — professional second net:** a free UptimeRobot/Healthchecks.io
  monitor with their mobile app, independent of any bot. Good belt-and-braces.

## 6. Incident playbook (site down or misbehaving)

1. **Is the site really down?** Open it in a private browser window.
2. **PA Web tab** → check the app is enabled; **Reload** it (kills most stuck states).
3. **PA error log** (Web tab → Log files): look for the traceback tail.
4. **Sync problems?** Read `<data_dir>/sync_issues.log` — "Relay reported failure"
   lines mean the Apps Script relay rejected a write (auth/config), not a network blip.
5. **Bad deploy?** Roll back with the round's Flow B (`*.pre_rNN.bak` files the
   installer left behind), Reload, then re-run smoke tests.
6. **Data restore (last resort):** `restore_backup.py` + the Drive zip backups.
   Never experiment on the live `ndli_data` — copy it first.
7. **Outage over?** The watcher sends the recovery note automatically; record
   what happened in the ops log.

## 7. Routine maintenance

- **Passwords:** rotate per `HANDOVER_SECURITY_CHECKLIST.md` at every handover.
- **Backups:** weekly GAS trigger writes zips to Drive (verify monthly that the
  newest zip exists and is non-trivial in size).
- **Docs:** `docs/API_REFERENCE.md` + `docs/ARCHITECTURE_MAP.md` regenerate from
  `routes/` (`python3 gen_api_docs.py`) — the drift gate fails if someone edits
  routes and forgets. Run the gate before any release (see `DEPLOY_WORKFLOW.md`).
