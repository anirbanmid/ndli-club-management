# Deploy Workflow — how changes reach production

**Audience:** the next developer (human or agent) shipping a change.
**Scope:** the release process on PythonAnywhere. Code conventions and hard
git rules live in `AGENTS.md`; hosting details in `PYTHONANYWHERE_DEPLOYMENT.md`.
Do not duplicate those — read them first.

---

## The round workflow (proven over 50+ releases)

Every change ships as a **round** (`RNN`), small and single-concern:

1. **Survey → scope ONE concern.** Mixed rounds hide regressions.
2. **Build in a testbed copy**, never on the live tree.
3. **Pins:** every behavior change gets a test that would fail without it.
   Assert across surfaces (HTML + API + docs) where a value appears twice.
4. **Full gate:** `python3 -m unittest discover -s tests` from the **repo root**
   (never `python3 -m unittest tests.X`). Know your expected count and compare
   to the measured count — a mismatch is information, not noise.
5. **Build the deploy kit** = a DELTA zip: only the changed files + an
   `INSTALL_RNN.py` + `INSTALL.txt`. The installer:
   - backs up each REPLACED file as `*.pre_rNN.bak` (never clobber an existing
     backup on a re-run),
   - reports honest `[new]` / `[upd]` per file,
   - prints `RESULT: N OK, 0 FAIL` with checks that MEASURE what they verify
     (expected counts are measured at build time, never remembered),
   - prints an explicit `git add` commit block (NEVER `git add -A`).
6. **Dress-rehearse the kit** from the zip bytes on a clean base (fresh install)
   and a PA-like base (replaced files present) + a re-run (idempotent) + a
   no-`node` leg (PA skips JS checks) before delivering anything.
7. **Runbook** (`DEPLOY_RNN_STEP_BY_STEP.md`): upload → install → Reload →
   smoke checks → commit block → push → clean → rollback (Flow B).
8. **Operator runs Flow A on PA**, smoke-tests, commits the exact block,
   pushes, cleans. Only then the round is CLOSED.

## Smoke rules (learned the hard way)

- **Never commit a smoke-failed deploy.** Install the fix over it (the
  installer keeps the true `*.pre_*.bak`), smoke again, then ONE commit.
  The commit certifies what passed smoke.
- Run tests from `~/ndli-club-management`, never from inside a kit folder —
  `No module named '_seed_env'` means wrong directory, not a broken deploy.
- **PA free tier = ~100 CPU-s/day.** The installer's own targeted test runs are
  enough; a full in-installer suite is OPTIONAL and default-OFF (it tarpits the
  account). Run the full suite on PA only when a round touched broad logic or
  smoke looks wrong.
- PA console pastes: big heredocs hang the console. Working method: create the
  file via the Files editor, paste there, save, then run it.

## Rollback (Flow B, every runbook)

Installers leave `*.pre_rNN.bak` next to every file they replace. Rollback =
copy the `.bak` back (or `git checkout` the file if already committed),
delete round-new files, Reload. Keep backups until the round is CLOSED and
pushed; cleanup is `find . -name "*.pre_rNN.bak" -delete` plus any kit folders.

## Release hygiene

- Old kit zips are disposable (rebuildable from the kit script) — keep the
  workspace lean; the git history is the rollback source of truth.
- Generated docs (`gen_api_docs.py`) must be regenerated on the **target** tree
  at install time if the tree's measured counts can differ from the build host
  (junk: `*.pre_*`, `*.pyc`, `__pycache__`, dotfiles — never counted).
- Dual-deployment parity with GAS is FROZEN (see AGENTS.md) except the backup
  path. Do not touch `deployment_gas/*` unless the owner asks.
