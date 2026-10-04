# Contributing — NDLI Club Management App

## 0. Before you touch anything: `git pull`

Always pull first. **Never upload whole files from a local clone onto the
deployment** (PythonAnywhere Files tab or elsewhere). A stale-clone upload in
2026-10-03 silently clobbered a deployed feature that was never committed —
deployed-but-uncommitted work is invisible to stale clones. If you changed a
file locally and the deployment differs, diff first, then decide.

## 1. Repository hygiene — hard rules

These exist because each one caused a real incident:

- **`data/` is runtime data, not source.** It is gitignored wholesale: accounts
  (with password hashes), club/issue data, institution contact emails and the
  PI signature image live there. Tracking it leaked all of that into the repo
  (2026-09 → fixed 2026-10-04). Never `git add -f data/...`. A fresh clone is
  code-only — `init_db.py` (also run automatically on app start) provisions the
  data tree and generates initial credentials (see `data/.seed_credentials.json`,
  gitignored).
- **Never `git add -A` or `git add .`** — stage explicit paths only. A blanket
  add sweeps runtime churn, rollback scratch and test litter into commits.
- **Never commit rollback scratch**: deploy-kit installers leave
  `*.bak` / `*.pre_*` files next to the files they touch. They are local-only
  rollback material (gitignored) and must never enter a commit.
- **Secrets never live in code.** Seed passwords come from environment
  variables (`NDLI_ADMIN_PASSWORD`, `NDLI_EMP01..07_PASSWORD`) or are generated
  once into `data/.seed_credentials.json` (chmod 600, gitignored). The QR
  signing key comes from `NDLI_QR_SIGNING_KEY` or is generated into
  `data/.qr_signing_key`. Nothing to commit, ever.
- **Dev tooling artifacts stay out** (`*.code-workspace`, `*.mp4` promo material,
  one-off `.bat` helpers) — all gitignored.

## 2. Running the tests

From the repo root:

```
python3 -m unittest discover -s tests
```

- Never use module-style runs (`python3 -m unittest tests.x`) — the suite is
  wired for flat discovery.
- A fresh clone self-provisions: test modules call `initialize_database()` so
  no tracked seed data is needed.
- The perf benchmarks are wall-clock assertions made host-tolerant by
  `tests/_bench.py` (budgets scale with a measured host factor; hopeless hosts
  skip the timing check loudly while correctness assertions still gate). Set
  `NDLI_BENCH_STRICT=1` to hunt real performance regressions on a quiet machine.
- On a free PythonAnywhere account the full suite costs hundreds of CPU-seconds
  and will trip the daily-tarpit; deploy kits therefore support `--lite`
  (targeted test files only) plus a deferred full-suite step.

## 3. Deploying to PythonAnywhere

- Deploy via the project's deploy kits (they back up every file they touch,
  run marker checks + the test gate, and print a ready-to-paste commit block).
- **Deploy is not done until the commit block is pasted and pushed.** An
  uncommitted deployment will be clobbered by the next stale-clone upload.
- Only ever run `git rm` / `git add` with explicit paths on the PA repo.
