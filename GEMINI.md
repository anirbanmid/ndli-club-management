# NDLI Club Management App — Antigravity Project Constitution & Architecture Specification

## Project Identity
- **Official Name**: NDLI Club Management App
- **Lead System Architect & Full-Stack Developer**: Dr. Anirban Mukherjee
- **Governing Institution**: National Digital Library of India (NDLI), Central Administration Office, Indian Institute of Technology Kharagpur (IIT Kharagpur)
- **Project Directory**: `C:\Users\HP\.gemini\antigravity\scratch\ndli_club_management`
- **Certified Baseline**: Edition v3.1 (Enterprise Handover Release) / Most Stable Version 2 (tag `stable-v2`, commit `3cc5329`)

---

## Core Architectural Invariants
1. **Application Name**: The official application name must strictly remain `"NDLI Club Management App"`.
2. **Zero External Dependency Kernel**: Built exclusively on Python 3.10+ standard library (HTTP server, JSON, CSV engines). Do not introduce external pip web frameworks (e.g., Flask, Django, FastAPI) or database engines without explicit instruction.
3. **Dual-Deployment Parity**: 100% synchronization and schema compatibility must be maintained between the local Python environment (`app.py`, `templates/`) and Google Apps Script (`deployment_gas/Code.gs`, `deployment_gas/*.html`).
4. **UI Ergonomics & Layout Invariants**:
   - Container widths, responsive flex rules, grid structures, and full-width layouts must remain undisturbed.
   - Navigation action buttons ("Employee Login" and "Employee Portals") use vibrant complementary color highlighting.
   - The Employee Login interface features equalized officer chip grids, compact field spacing, and zero vertical scrolling on standard viewports.
5. **Business Logic & Statutory Rules**:
   - 48-hour response window, 7-day resolution deadlines, 24-hour quota resets, and renewal calculations of +1 year from the PREVIOUS DUE DATE (rolled forward if in the past; the anniversary from Date of Approval is kept) are strict system invariants.

---

## Enterprise Scalability & High-Throughput Standards
- **50,000+ Club Records**: `CSVEngine` utilizes in-memory primary key hash indexing (`key_indices`) for sub-millisecond ($O(1)$) lookups (0.64ms avg), fast-path $O(1)$ row appending for new records (~13ms), zero-allocation aggregations (`copy=False`), and client-side 50-row pagination.
- **200 Real-Time Concurrent Requests**: `ThreadedHTTPServer` configured with 512 queue slots, `allow_reuse_address = True`, and `daemon_threads = True`. Thread-safe `threading.RLock()` guards all atomic file operations. Drive cloud sync is bounded by `_UPLOAD_SEMAPHORE = 4`.
- **Instant 0ms Portal Tab Caching**: Employee Portal Universal Search (Tab 2) and Node Activity Logs (Tab 3) utilize client-side in-memory caches (`ALL_CLUBS_CACHE`, `ALL_ACTIVITIES_CACHE`) with background preloading on login, animated loaders (`⏳`), and inline retry actions.
- **Crash Shield & Error Boundaries**: Global UI error boundaries across all portals intercept client exceptions without white-screening. Atomic writes use 10-iteration exponential backoff loops for Windows file locks.

---

## Key Operational & Maintenance Commands
- **Start Local Server**:
  ```bash
  python app.py
  ```
  Serves on `http://127.0.0.1:8080` (or dynamic `$PORT`).
- **Run Python Test Matrix**:
  ```bash
  git checkout -- data/ ; python -m unittest discover tests ; git checkout -- data/
  ```
- **Run Google Apps Script Test Suite**:
  ```bash
  node test_code_gs.js
  ```
- **Execute Scalability Benchmarks**:
  ```bash
  python -m unittest tests/test_scaling_benchmark.py
  python -m unittest tests/test_scale_50k_and_concurrency.py
  ```
- **Emergency Codebase Restore**:
  Run `restore_to_stable_v2.bat` (Windows) or `python restore_stable_v2.py`.
