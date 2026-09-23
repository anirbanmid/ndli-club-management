# NDLI Club Management and Employee Activity Tracking System
**National Digital Library of India (IIT Kharagpur)**
**Lead System Architect & Developer:** Dr. Anirban Mukherjee

A high-performance, modern, minimalist web application engineered for tracking employee activities, club approvals, renewals, and performance analytics across India, backed by Google Drive and structured CSV databases.

---

> **Deployment & Security Docs**
> - `PYTHONANYWHERE_DEPLOYMENT.md` — free-tier deployment via `wsgi.py` (persistent disk, no cold starts)
> - `HANDOVER_SECURITY_CHECKLIST.md` — password/secret rotation procedure for client handover
> - Security note: API endpoints enforce session auth (admin gates + self-or-admin identity checks); the
>   in-app **🔑 Change Password** provision rotates any account credential.

---

## 1. System Architecture Overview

```
                          +------------------------------------------+
                          |        IIT Kharagpur Master Admin        |
                          |  - Real-time Regional Infographics       |
                          |  - AI Strategic Decision Engine          |
                          |  - Employee Node Provisioning & Control  |
                          +--------------------+---------------------+
                                               |
                                               v
                          +--------------------+---------------------+
                          |           REST API / Server              |
                          |  (Zero-Dependency Python Stdlib Server)  |
                          +----+---------------+---------------+-----+
                               |               |               |
             +-----------------+               |               +-----------------+
             |                                 |                                 |
             v                                 v                                 v
+------------------------+        +------------------------+        +------------------------+
|  Employee 01 (North)   |        |  Employee 02 (Central) |        |   Employees 03 - 07    |
|  - SEC A: Support Log  |        |  - SEC A: Support Log  |        |  (West, East, NE,      |
|  - SEC B/C: Club Appr. |        |  - SEC B/C: Club Appr. |        |   South 1, South 2)    |
|  - Quota / Search/Edit |        |  - Quota / Search/Edit |        |                        |
+-----------+------------+        +-----------+------------+        +-----------+------------+
            |                                 |                                 |
            +----------------+                |                +----------------+
                             |                |                |
                             v                v                v
                  +--------------------------------------------------+
                  |               Storage & Sync Layer               |
                  |                                                  |
                  |  [Google Drive Synced Folder / Direct Drive API] |
                  |                                                  |
                  |  Node Databases:                                 |
                  |  - data/employees/emp01/credentials.csv          |
                  |  - data/employees/emp01/activity_log.csv         |
                  |  - data/employees/emp01/clubs.csv                |
                  |  ... (7 independent employee node databases)     |
                  |                                                  |
                  |  Master Database (Real-time Dual Write & Sync):  |
                  |  - data/master/master_users.csv                  |
                  |  - data/master/master_clubs.csv                  |
                  |  - data/master/master_activities.csv             |
                  |  - data/master/master_quotas.csv                 |
                  +--------------------------------------------------+
```

---

## 2. Google Drive Deployment Options

### Option A: Google Drive for Desktop Synced Folder (Recommended for Local/Server Nodes)
1. Install [Google Drive for Desktop](https://www.google.com/drive/download/).
2. Create a folder in your Drive named `NDLI_Club_System`.
3. Set the `NDLI_STORAGE_MODE=LOCAL_SYNC` environment variable, or link `ndli_club_management/data` to `G:\My Drive\NDLI_Club_System\data`.
4. Any CSV write operation performed by the server is immediately synchronized by Google's native sync daemon to the cloud.

### Option B: Direct Cloud Google Drive API v3
1. Create a Google Cloud Project and enable the Google Drive API.
2. Generate a Service Account JSON key and place it as `service_account.json`.
3. Share your target Google Drive folder with the service account email.
4. Set `NDLI_STORAGE_MODE=DRIVE_API` and `NDLI_DRIVE_FOLDER_ID=<folder_id>`.

### Option C: Pure Google Apps Script (Serverless in Drive)
1. Open Google Drive -> New -> More -> Google Apps Script.
2. Paste the provided [`google_apps_script/Code.gs`](file:///C:/Users/HP/.gemini/antigravity/scratch/ndli_club_management/google_apps_script/Code.gs).
3. Deploy as a Web App to run completely inside Google Drive without an external server.

---

## 3. State-to-Zone Automatic Mapping Logic

The system strictly enforces the official NDLI regional grouping:

| Zone | Indian States & Union Territories |
| :--- | :--- |
| **North** | Jammu & Kashmir, Ladakh, Uttarakhand, Himachal Pradesh, Chandigarh, Punjab, Haryana, Delhi, Uttar Pradesh |
| **Central** | Madhya Pradesh, Chhattisgarh |
| **West** | Rajasthan, Gujarat, Maharashtra, Goa, Daman and Diu, Dadar & Nagar Haveli |
| **East** | Bihar, Jharkhand, West Bengal, Odisha |
| **North East** | Sikkim, Assam, Arunachal Pradesh, Meghalaya, Manipur, Tripura, Nagaland, Mizoram |
| **South** | Andhra Pradesh, Telangana, Karnataka, Tamil Nadu, Puducherry, Kerala, Andaman & Nicobar Island, Lakshadweep |

---

## 4. Default Seed Credentials

### Master Admin (IIT Kharagpur Office)
- **Email:** `admin@iitkgp.ac.in`
- **Password:** `Seed#Admin-Rotated2026`
- **Role:** `ADMIN`

### 7 Regional Employees
| Employee ID | Name | Zone | Email | Pre-generated Password |
| :--- | :--- | :--- | :--- | :--- |
| `EMP01` | Rohan Sharma | North | `emp.north@ndli.edu.in` | `Seed#EMP01-Rotated2026` |
| `EMP02` | Pooja Verma | Central | `emp.central@ndli.edu.in` | `Seed#EMP02-Rotated2026` |
| `EMP03` | Amit Patel | West | `emp.west@ndli.edu.in` | `Seed#EMP03-Rotated2026` |
| `EMP04` | Debabrata Ghosh | East | `emp.east@ndli.edu.in` | `Seed#EMP04-Rotated2026` |
| `EMP05` | Mayanglambam Singh | North East | `emp.northeast@ndli.edu.in` | `Seed#EMP05-Rotated2026` |
| `EMP06` | K. Venkatesh | South 1 | `emp.south1@ndli.edu.in` | `Seed#EMP06-Rotated2026` |
| `EMP07` | Ananya Nair | South 2 | `emp.south2@ndli.edu.in` | `Seed#EMP07-Rotated2026` |

---

## 5. System Features & Modules

- **Web Portals & Interactive UIs:**
  - **Main Portal Gateway (`/` or `/portal`):** System status, Google Drive mode, links to Admin and 7 Regional Portals.
  - **7 Regional Employee Portals (`/employee` or `/employee/<EMP_ID>`):**
    - **SEC A:** Real-time Daily Support Log with automated UTC timestamps.
    - **SEC B & C:** Instant modal/form for New Club Details with strict automatic State-to-Zone mapping, validation error prompts, and performance quota tracking.
    - **Universal Search & Edit:** Real-time search across any database field with in-place modal editing and synchronization to master and node databases.
    - **Registration Renewal:** One-click renewal validity extension with automated renewal activity logging.
  - **IIT Kharagpur Admin Master Control Center (`/admin`):**
    - **Interactive Performance Dashboard:** Infographics, zone-wise club bars, individual employee performance quotas, state-wise representation, and year/month registration trajectories.
    - **AI Decision & Strategic Roadmap Module:** Automated analysis of state penetration deficits, capacity balancing warnings, and retention suggestions.
    - **Employee Management Console:** Single-click employee onboarding (generates credentials, dedicated CSV node database, and portal route) + one-click account blocking/unblocking.
    - **Drive Sync Health Monitor:** Displays storage sync mode (`LOCAL_SYNC` / `DRIVE_API`) and triggers master reconciliation.

---

## 6. How to Run

### 1. Initialize Database & Seed Benchmark Records:
```bash
python init_db.py
```

### 2. Run Comprehensive Automated Test Suite (38 Tests):
```bash
python -m unittest discover -s tests -v
```

### 3. Start the Web Server:
```bash
python app.py
```
Then open in any browser:
- **Central Portal Gateway:** `http://127.0.0.1:8080/`
- **Master Admin UI:** `http://127.0.0.1:8080/admin`
- **Regional Employee Portal:** `http://127.0.0.1:8080/employee` (or e.g. `/employee/EMP01`, `/employee/EMP02`, etc.)
- **REST API Health & Endpoints:** `http://127.0.0.1:8080/api/health`

