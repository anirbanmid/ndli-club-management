# NDLI Club Management -- Auto-Generated Architecture Map

<!-- GENERATED FILE -- DO NOT EDIT BY HAND.
     Source of truth: routes/ (dispatch tables in routes/__init__.py).
     Regenerate: python3 gen_api_docs.py   |   drift gate: python3 gen_api_docs.py --check -->

Sizes are **measured from the tree** at generation time. Roles are the stable one-line descriptions; numbers move whenever the code does.

## Component map

| Path | Role | Size |
|------|------|------|
| `app.py` | HTTP request handler + startup wiring (no dispatch chain) | 509 lines |
| `routes/` | URL router: ordered dispatch tables + 16 domain modules | 17 files, 3595 lines, 81 dispatch entries |
| `db/` | flat-file CSV storage engine (mutex, backup, migration, counting) | 9 modules, 3227 lines |
| `ai/` | Robu assistant (KB retrieval, tools, LLM gateway, guard, audit) | 11 modules, 4404 lines |
| `auth.py` | PBKDF2 password hashing + session tokens | 430 lines |
| `config.py` | environment-driven configuration + seed accounts | 200 lines |
| `state_zone_mapper.py` | state/zone normalization + alias matching | 147 lines |
| `qr_tokens.py` | certificate QR token signing / verification | 151 lines |
| `wsgi.py` | WSGI entry point for cloud hosting | 129 lines |
| `init_db.py` | storage hierarchy + master schema bootstrap | 325 lines |
| `restore_backup.py` | CLI disaster-recovery restore utility | 81 lines |
| `templates/` | portal HTML pages (admin, employee, index, verify) | 4 files |
| `static/` | front-end assets (css / js / images) | 69 files, 44 JS |
| `docs/` | technical + user manuals (Robu KB sources) + figures | 4 manual files + figures |
| `tests/` | the pinned gate (unittest, zero third-party deps) | 75 test modules |
| `data/` | runtime flat-file store (CSV, sessions, backups, logs) -- runtime state, deliberately not counted | runtime state |

## Route module map (`routes/`)

| Module | Responsibility | Dispatch entries | Lines |
|--------|----------------|------------------|-------|
| `routes/activity.py` | Activity log: list, log, delete | 3 | 135 |
| `routes/assistant.py` | Robu - the AI assistant surface | 10 | 272 |
| `routes/auth_routes.py` | Authentication & session endpoints | 5 | 139 |
| `routes/backup.py` | Backup status / trigger / restore | 3 | 94 |
| `routes/certificate.py` | Certificates: settings, signatures, QR tokens, public verification | 6 | 319 |
| `routes/clubs.py` | Club register: search, details, create, update, renew, delete | 7 | 407 |
| `routes/data_admin.py` | Destructive data-admin (hard reset) | 1 | 91 |
| `routes/downloads.py` | File downloads (manuals, promo video, CSV exports) | 5 | 171 |
| `routes/employees.py` | Employee roster / profile / admin employee management | 6 | 260 |
| `routes/health.py` | Health + state/zone mapping | 3 | 44 |
| `routes/issues.py` | Issue tracking | 6 | 160 |
| `routes/metrics.py` | Admin metrics, performance, renewal attention, AI insights | 4 | 587 |
| `routes/migration.py` | Bulk import + data migration (the two doors) | 3 | 398 |
| `routes/portals.py` | HTML portals + static assets | 9 | 98 |
| `routes/sync_routes.py` | Sync status / reconcile / Drive sync | 6 | 104 |
| `routes/training.py` | PPT Training Library (2 slots) | 4 | 146 |

**Total: 81 dispatch entries** (46 GET + 35 POST).

## Request dispatch flow

```text
HTTP request
  |
  v
app.py  NDLIRequestHandler.handle_get / handle_post        [app.py]
  |        parse URL + query / JSON body
  v
routes.match(GET_ROUTES | POST_ROUTES, path)               [routes/__init__.py]
  |        ordered table, FIRST match wins (E = exact, P = prefix)
  v
routes/<module>.<handler>(h, path, query_params | body)    [routes/<domain>.py]
  |        domain logic: db/ (CSV store), ai/ (Robu), auth.py, ...
  v
h._send_json(...)  /  h._send_file(...)  /  h._send_error(...)   -> response
```

## Router invariants (pinned)

- `app.py` must stay a request handler + startup module -- the dispatch chain cannot grow back into it (line-budget tripwire in `tests/test_router_extraction.py`).
- Every registered route resolves to a callable in `routes/` -- pinned by `tests/test_router_extraction.py` and re-checked by `tests/test_r55_api_docs.py` against this document.
- Both artifacts here + the manual appendix must match `routes/` exactly -- `python3 gen_api_docs.py --check` is the drift gate.
