# Multi-Agent Coordination Guidelines — NDLI Club Management App

## Operational Directives
- **System Context**: You are operating within the official NDLI Club Management App codebase for the Central Administration Office, IIT Kharagpur.
- **Strict Invariants**:
  1. The application name must strictly remain `"NDLI Club Management App"`.
  2. Maintain 100% dual-deployment parity between Python (`app.py`, `templates/`) and Google Apps Script (`deployment_gas/Code.gs`, `deployment_gas/*.html`).
  3. Never introduce external pip web frameworks into the core runtime; adhere strictly to Python's standard library.
  4. Preserve container widths, layouts, quotas, star ratings, and complementary navbar styling.
- **Testing Standard**:
  - Python tests: `git checkout -- data/ ; python -m unittest discover tests ; git checkout -- data/`
  - GAS backend simulation: `node test_code_gs.js`
