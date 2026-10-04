# Multi-Agent Coordination Guidelines — NDLI Club Management App

## Operational Directives
- **System Context**: You are operating within the official NDLI Club Management App codebase for the Central Administration Office, IIT Kharagpur.
- **Strict Invariants**:
  1. The application name must strictly remain `"NDLI Club Management App"`.
  2. Maintain 100% dual-deployment parity between Python (`app.py`, `templates/`) and Google Apps Script (`deployment_gas/Code.gs`, `deployment_gas/*.html`).
  3. Never introduce external pip web frameworks into the core runtime; adhere strictly to Python's standard library.
  4. Preserve container widths, layouts, quotas, star ratings, and complementary navbar styling.
- **GAS status (owner decision, 2026-10-04): FROZEN.** The Google Apps Script twin is DEAD
  except the weekly backup / Drive mirroring (the DR backbone). Do NOT build GAS parity
  features or edit `deployment_gas/*` unless the owner explicitly asks; keep the backup/
  signature-restore paths working.
- **Git hygiene — HARD RULES (violating these caused real incidents):**
  1. ALWAYS `git pull` before editing. NEVER upload whole files from a stale clone onto
     the deployment (a stale-clone upload once clobbered a deployed feature).
  2. NEVER `git add -A` / `git add .` — it sweeps runtime churn and scratch files.
     Stage explicit paths only.
  3. NEVER commit `*.bak` / `*.pre_*` rollback scratch produced by deploy-kit installers.
  4. `data/` is RUNTIME data (gitignored on purpose: it leaked accounts + the PI signature
     into the repo in 2026-09). Never force-add anything under `data/`. A fresh clone is
     code-only; `init_db.py` provisions the data tree on first run.
- **Testing Standard**:
  - Python tests: `python3 -m unittest discover -s tests` (from the repo root; NEVER
    module-style `python3 -m unittest tests.X`). A fresh clone self-provisions its test DB.
  - Wall-clock benchmarks are host-tolerant (`tests/_bench.py`); use `NDLI_BENCH_STRICT=1`
    when hunting real performance regressions on a quiet machine.
  - GAS backend simulation: `node test_code_gs.js`
