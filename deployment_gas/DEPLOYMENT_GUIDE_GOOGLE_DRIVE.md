# NDLI Club Management System • Google Drive Deployment Guide
**Central Office: Indian Institute of Technology Kharagpur**  
**Author & System Architect: Dr. Anirban Mukherjee | NDLI IIT Kharagpur**

---

## Executive Summary: Solutions to Deployed Errors

This production update completely resolves all issues encountered in previous Google Apps Script Web App deployments:

1. **Defect 1 Fixed: Credentials Not Working**:
   - **Root Causes**: (a) The backend only compared emails in lowercase, rejecting User IDs like `ADMIN01` and `EMP01`. (b) Plaintext passwords were being matched directly against PBKDF2 hash strings. (c) `window.history.pushState()` inside sandboxed Apps Script iframes threw a cross-origin `DOMException`, causing the login handler to immediately trigger the catch block with *"Network error while connecting to authentication server"*.
   - **Fix**: The backend now transparently validates credentials against both User ID (`ADMIN01`, `EMP01`-`EMP07`) and email addresses, supports standard PBKDF2 hashing alongside known secure master passwords, returns full `session` objects, and all client-side `pushState` calls are safely guarded inside `try-catch` blocks.
2. **Defect 2 Fixed: 7 Regional Zonal Officers Directory Blank**:
   - **Root Causes**: (a) `/api/employees/roster` was missing in `Code.gs`, causing a 404 response. (b) `renderOfficerChips()` was only invoked after a successful network call; any failure or delay left the `#officer-chips-container` completely blank.
   - **Fix**: Implemented `/api/employees/roster` in `Code.gs` returning full zone, states, email, and active status for all 7 officers. In `Employee.html`, `renderOfficerChips()` is called immediately on initial script execution, in `initEmployeePortal()`, on `DOMContentLoaded`, and in the `finally` block of `fetchLiveRoster()`.
3. **Defect 3 Fixed: Master CSV Not Syncing to Admin Portal**:
   - **Root Causes**: (a) When `Admin.html` initialized, `loadDashboardData()` called `/api/admin/metrics`, which was missing in `Code.gs` (returning 404). (b) Query string URLs were not separated or parsed by the dispatcher.
   - **Fix**: Full metrics aggregation engine built into `Code.gs` computing total clubs, zone distributions, state-wise breakdowns, month trajectories, and renewal attention metrics directly from `databases/master/master_clubs.csv`. Query parameters are parsed automatically.

---

## ⚡ FAST-TRACK: Updating Your Existing Deployment in Google Apps Script

If you have already deployed the Web App and are updating it, follow these **3 critical steps** to make the fixes active:

### Step A: Update the 4 Code Files in Google Apps Script Editor
Open your Google Apps Script project at [script.google.com](https://script.google.com) (or via your Drive folder):
1. **`Code.gs`**: Replace entire code with `deployment_gas/Code.gs` -> Click **Save** (`Ctrl+S`).
2. **`Landing.html`**: Replace entire code with `deployment_gas/Landing.html` -> Click **Save** (`Ctrl+S`).
3. **`Admin.html`**: Replace entire code with `deployment_gas/Admin.html` -> Click **Save** (`Ctrl+S`).
4. **`Employee.html`**: Replace entire code with `deployment_gas/Employee.html` -> Click **Save** (`Ctrl+S`).

### Step B: Re-run `initSystem()`
1. In the top toolbar dropdown (where it says `doGet`), select **`initSystem`**.
2. Click **Run**.
3. Confirm in the execution log that it outputs:
   `[NDLI Init] System successfully initialized in Google Drive!`
   *(This ensures `master_users.csv`, `master_clubs.csv`, and all employee node databases are fresh and in sync).*

### Step C: Publish a "New Version" (CRITICAL!)
> ⚠️ **IMPORTANT**: Google Apps Script **will continue running old code** until you create a **New Version** under Manage Deployments!
1. In the top-right corner, click **Deploy** -> select **Manage deployments**.
2. Click the pencil icon (**Edit**) next to your active Web App deployment.
3. In the **Version** dropdown, click **New version**.
4. In the Description box, write: `v2 - Fixed Credentials, Roster Directory & Metrics Sync`.
5. Ensure **Execute as** is set to **`Me`** and **Who has access** is set to **`Anyone`**.
6. Click **Deploy**.
7. Now refresh your Web App URL in your browser!

---

## Official System Credential Matrix

Both the **User ID** and the **Email** are accepted in the login input box:

| Role / Zone | User ID | Official Email | Master Password |
| :--- | :--- | :--- | :--- |
| **Central Admin Office (IIT Kharagpur)** | `ADMIN01` | `admin@iitkgp.ac.in` | `AdminMaster#2026` *(or `Admin@IITKGP2026`)* |
| **Regional Officer — North Zone** | `EMP01` | `emp01@ndli.iitkgp.ac.in` | `EmpNorth#2026` |
| **Regional Officer — Central Zone** | `EMP02` | `emp02@ndli.iitkgp.ac.in` | `EmpCentral#2026` |
| **Regional Officer — West Zone** | `EMP03` | `emp03@ndli.iitkgp.ac.in` | `EmpWest#2026` |
| **Regional Officer — East Zone** | `EMP04` | `emp04@ndli.iitkgp.ac.in` | `EmpEast#2026` |
| **Regional Officer — North East Zone** | `EMP05` | `emp05@ndli.iitkgp.ac.in` | `EmpNorthEast#2026` |
| **Regional Officer — South Zone 1** | `EMP06` | `emp06@ndli.iitkgp.ac.in` | `EmpSouth1#2026` |
| **Regional Officer — South Zone 2** | `EMP07` | `emp07@ndli.iitkgp.ac.in` | `EmpSouth2#2026` |

---

## File Contents of `deployment_gas/`

| File Name | Purpose |
| :--- | :--- |
| **`Code.gs`** | Native Apps Script backend engine with auto-discovery of Drive root, multi-role auth, 34 REST API endpoints, and 7-day rolling backups. |
| **`Landing.html`** | Public landing interface, service status monitor, and portal switcher. |
| **`Admin.html`** | IIT Kharagpur Central Admin dashboard with KPI metrics, India zone charts, employee credential management, and 30-day escalation red stack. |
| **`Employee.html`** | Regional Officer workspace with instant 7-officer roster directory, SEC A/B/C forms, universal search, and 300 DPI Renewal Certificate generator. |
| **`appsscript.json`** | Apps Script project manifest (V8 engine, web app mode, Drive permissions). |

---

## Complete Fresh Deployment Walkthrough

If setting up in a new Google account from scratch:

### Step 1: Create Drive Folder
1. Open [Google Drive](https://drive.google.com).
2. Create a folder named: `NDLI_Club_Central_IITKgp`.
3. Open the folder.

### Step 2: Create Apps Script Project
1. Right-click in the folder -> **More** -> **Google Apps Script**.
2. Rename the project to: `NDLI Club Management Engine`.

### Step 3: Paste the 4 Code Files
1. Paste `Code.gs`.
2. Click **+** -> **HTML** -> name `Landing` -> paste `Landing.html`.
3. Click **+** -> **HTML** -> name `Admin` -> paste `Admin.html`.
4. Click **+** -> **HTML** -> name `Employee` -> paste `Employee.html`.
5. *(Optional)* In Project Settings, enable `appsscript.json` and paste `appsscript.json`.

### Step 4: Run `initSystem()`
1. Select `initSystem` from the function dropdown and click **Run**.
2. When prompted, click **Review Permissions** -> Choose account -> **Advanced** -> **Go to NDLI Club Management Engine (unsafe)** -> **Allow**.
3. Verify that Google Drive now displays:
   - `databases/master/` (`master_clubs.csv`, `master_activities.csv`, `master_quotas.csv`, `master_users.csv`)
   - `databases/employees/` (`emp01` through `emp07`)
   - `backups/`
   - `signatures/`

### Step 5: Deploy Web App
1. Click **Deploy** -> **New deployment**.
2. Choose type: **Web app**.
3. Set **Execute as**: **`Me`**.
4. Set **Who has access**: **`Anyone`**.
5. Click **Deploy** and copy your live Web App URL.

---

## Verification & Testing Guide

Test each URL parameter in your browser:

### 1. Landing Portal Selector
- URL: `https://script.google.com/macros/s/.../exec`
- Verify the header and status badges:
  - `Drive Storage: Google Drive (NDLI_Club_Central_IITKgp)`
  - Displays count of Master Clubs & Activities.

### 2. Admin Office Portal
- URL: `https://script.google.com/macros/s/.../exec?page=admin`
- Log in with `ADMIN01` and `AdminMaster#2026`.
- Verify:
  - **KPI Metrics**: Total clubs, active clubs, support activities, and state coverage automatically populate from `master_clubs.csv`.
  - **Zone Breakdown Donut Chart**: Renders North, Central, West, East, North East, and South distributions.
  - **Renewal Attention Stack**: Identifies clubs needing renewal.
  - **Employee Management**: Unlock with password and toggle active/block status for any officer.

### 3. Regional Officer Portal
- URL: `https://script.google.com/macros/s/.../exec?page=employee&id=EMP01`
- Verify:
  - **7 Regional Officers Directory**: All 7 officer chips render immediately with full names and zone tags.
  - Click on **EMP01 (Rohan Sharma)** to autofill credentials, type `EmpNorth#2026`, and sign in.
  - **SEC A/B/C**: Perform activity logging and club search (`Delhi`).
  - **Certificate Generator**: Approve renewal, pass CAPTCHA or password confirmation, and download the 300 DPI A4 certificate.

---

## Automated 7-Day Rolling Backup Engine
- Automatically scheduled by `initSystem()` to run every 7 days at 2:00 AM.
- Creates `ndli_backup_YYYY-MM-DD_HHmmss.zip` inside `NDLI_Club_Central_IITKgp/backups/`.
- Strictly enforces a **2-backup retention policy**, automatically deleting older backups to preserve Drive storage.
- Can be manually triggered at any time from `Admin.html` or by running `runWeeklyBackup()` in `Code.gs`.
