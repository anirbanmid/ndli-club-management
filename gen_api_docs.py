#!/usr/bin/env python3
"""
gen_api_docs.py -- R55: auto-generated API reference + architecture map.

WHY (R55, user task list 2026-10-14): the technical manual's endpoint lists
(sections 11-12) are hand-written prose. Hand-written endpoint lists drift
from the code the moment a route moves. This generator makes the CODE the
single source of truth: it reads the dispatch tables in `routes/__init__.py`
plus the route modules and emits a complete, machine-checked reference.

Outputs (all deterministic -- no timestamps, no absolute paths):
  docs/API_REFERENCE.md      -- every dispatch entry (GET + POST), in
                                dispatch order (first match wins)
  docs/ARCHITECTURE_MAP.md   -- component map + route module map + dispatch
                                flow, sizes measured from the tree
  docs/technical_manual.html -- "Appendix A" block, regenerated between the
                                BEGIN/END GENERATED markers (page totals are
                                repatched to match the new page count)

Usage:
  python3 gen_api_docs.py            # regenerate all three artifacts
  python3 gen_api_docs.py --check    # drift gate: exit 0 = in sync, exit 1 =
                                     # report which artifact drifted (used by
                                     # tests/test_r55_api_docs.py and CI)

Stdlib only (the repo runs zero third-party dependencies -- keep it that way).
"""
import ast
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROUTES_INIT = BASE / "routes" / "__init__.py"
ROUTES_DIR = BASE / "routes"
MANUAL = BASE / "docs" / "technical_manual.html"
API_MD = BASE / "docs" / "API_REFERENCE.md"
ARCH_MD = BASE / "docs" / "ARCHITECTURE_MAP.md"

GENERATOR_NAME = "gen_api_docs.py"

# Marker strings owned by the generator. Everything between them is replaced
# on every run; everything OUTSIDE them stays hand-written.
MARKER_BEGIN = "<!-- BEGIN GENERATED APPENDIX A (gen_api_docs.py) -->"
MARKER_END = "<!-- END GENERATED APPENDIX A (gen_api_docs.py) -->"

# Rows per generated API page in the manual appendix. Conservative on purpose:
# alias-heavy rows wrap to 2-3 lines, and a page that underflows prints fine
# while a page that overflows spills a stray sheet (the R54 lesson).
API_ROWS_PER_PAGE = 26

BANNER_MD = (
    "<!-- GENERATED FILE -- DO NOT EDIT BY HAND.\n"
    "     Source of truth: routes/ (dispatch tables in routes/__init__.py).\n"
    f"     Regenerate: python3 {GENERATOR_NAME}   |   drift gate: "
    f"python3 {GENERATOR_NAME} --check -->"
)

DISPATCH_PROSE = [
    "Every HTTP request lands in `app.py` (`NDLIRequestHandler`), which parses the",
    "URL / body and hands the path to `routes.match(GET_ROUTES | POST_ROUTES, path)`",
    "(`routes/__init__.py`). The tables are ordered **exactly like the old dispatch",
    "chain**: the first row whose matcher accepts the path wins. A matcher is a set",
    "of OR-ed predicates -- `E(...)` = exact path, `P(...)` = path prefix (marked",
    "`*` below). A handler is `routes/<module>.<function>(h, path, query_params)`",
    "for GET and `(h, path, body)` for POST.",
]

ARCH_FLOW = """\
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
"""


# --------------------------------------------------------------------------
# Collection (AST -- never regex the router: E()+P() concatenations exist)
# --------------------------------------------------------------------------

def _matcher_predicates(node):
    """Flatten E('..') / P('..') (+ concatenations) into [(op, key), ...]."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_matcher_predicates(node.left)
                + _matcher_predicates(node.right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        kind = node.func.id
        if kind not in ("E", "P"):
            raise ValueError(f"unknown matcher call: {kind}")
        op = "exact" if kind == "E" else "prefix"
        return [(op, ast.literal_eval(arg)) for arg in node.args]
    raise ValueError(f"unsupported matcher node: {ast.dump(node)}")


def collect_routes():
    """Return the dispatch entries in table order.

    Each entry: {"verb": "GET"|"POST", "predicates": [(op, key), ...],
                 "module": str, "handler": str, "index": int}
    """
    tree = ast.parse(ROUTES_INIT.read_text(encoding="utf-8"))
    entries = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name)
                    and target.id in ("GET_ROUTES", "POST_ROUTES")):
                continue
            verb = "GET" if target.id == "GET_ROUTES" else "POST"
            for item in node.value.elts:
                matcher, handler_ref = item.elts
                if not isinstance(handler_ref, ast.Attribute) or \
                        not isinstance(handler_ref.value, ast.Name):
                    raise ValueError(f"unsupported handler ref: {ast.dump(handler_ref)}")
                entries.append({
                    "verb": verb,
                    "predicates": _matcher_predicates(matcher),
                    "module": handler_ref.value.id,
                    "handler": handler_ref.attr,
                    "index": 0,
                })
    # number per verb in dispatch order
    counters = {"GET": 0, "POST": 0}
    for e in entries:
        counters[e["verb"]] += 1
        e["index"] = counters[e["verb"]]
    return entries


def collect_route_modules():
    """Per routes/*.py: responsibility (docstring), line count, defined handlers."""
    modules = {}
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        doc = (ast.get_docstring(tree) or "").strip().split("\n")[0].strip()
        resp = re.sub(r"^routes/[\w.]+\s*-\s*", "", doc) or doc
        handlers = sorted(
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef)
            and (n.name.startswith("get_") or n.name.startswith("post_"))
        )
        modules[path.stem] = {
            "file": f"routes/{path.name}",
            "responsibility": resp,
            "lines": len(text.splitlines()),
            "defined_handlers": handlers,
        }
    return modules


def defined_handler_index(modules):
    """{(module, handler): module_name} for every get_/post_ def in routes/."""
    index = {}
    for name, info in modules.items():
        for handler in info["defined_handlers"]:
            index[(name, handler)] = name
    return index


# --------------------------------------------------------------------------
# Small measured helpers for the architecture map
# --------------------------------------------------------------------------

def _py_lines(rel):
    path = BASE / rel
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


# Files that are NOT tree content: backups from deploy kits, bytecode caches,
# editor droppings, dotfiles. They differ between hosts (a clean checkout vs a
# live deployed tree) and must never move a measured count -- R55's first PA
# install tripped exactly this (same-size stale docs: one count off because a
# `*.pre_r20` backup sat in static/ on the build host only).
JUNK_SUFFIXES = (".pyc", ".pyo", ".bak", ".orig", ".rej", "~")

# deploy-kit backups look like `style.css.pre_r20` or `x.pre_r55.bak`
BACKUP_RE = re.compile(r"\.pre_r\d+(?:\.bak)?$")


def _is_junk(path):
    """True for backup/cache/droppings paths -- never counted, never listed."""
    if "__pycache__" in path.parts:
        return True
    name = path.name
    return (name.startswith(".")
            or name.endswith(JUNK_SUFFIXES)
            or BACKUP_RE.search(name) is not None)


def _py_package_lines(pkg):
    total = 0
    count = 0
    for path in sorted((BASE / pkg).glob("*.py")):
        if _is_junk(path):
            continue
        total += len(path.read_text(encoding="utf-8").splitlines())
        count += 1
    return count, total


def _file_count(rel, pattern="**/*", root=None):
    root = (BASE if root is None else root) / rel
    return sum(1 for p in root.glob(pattern)
               if p.is_file() and not _is_junk(p)) if root.is_dir() else 0


def collect_components():
    """(path, role, measured size) rows -- numbers measured, roles authored."""
    routes_mods = collect_route_modules()
    route_files = len(routes_mods) + 1  # + __init__.py
    route_lines = sum(m["lines"] for m in routes_mods.values()) + _py_lines("routes/__init__.py")
    entries = collect_routes()
    db_n, db_lines = _py_package_lines("db")
    ai_n, ai_lines = _py_package_lines("ai")
    test_n = _file_count("tests", "*.py")
    static_n = _file_count("static")
    static_js = _file_count("static", "**/*.js")
    tmpl_n = _file_count("templates", "*.html")
    docs_n = _file_count("docs", "*.html") + _file_count("docs", "*.pdf")
    return [
        ("app.py", "HTTP request handler + startup wiring (no dispatch chain)",
         f"{_py_lines('app.py')} lines"),
        ("routes/", f"URL router: ordered dispatch tables + {len(routes_mods)} domain modules",
         f"{route_files} files, {route_lines} lines, {len(entries)} dispatch entries"),
        ("db/", "flat-file CSV storage engine (mutex, backup, migration, counting)",
         f"{db_n} modules, {db_lines} lines"),
        ("ai/", "Robu assistant (KB retrieval, tools, LLM gateway, guard, audit)",
         f"{ai_n} modules, {ai_lines} lines"),
        ("auth.py", "PBKDF2 password hashing + session tokens",
         f"{_py_lines('auth.py')} lines"),
        ("config.py", "environment-driven configuration + seed accounts",
         f"{_py_lines('config.py')} lines"),
        ("state_zone_mapper.py", "state/zone normalization + alias matching",
         f"{_py_lines('state_zone_mapper.py')} lines"),
        ("qr_tokens.py", "certificate QR token signing / verification",
         f"{_py_lines('qr_tokens.py')} lines"),
        ("wsgi.py", "WSGI entry point for cloud hosting",
         f"{_py_lines('wsgi.py')} lines"),
        ("init_db.py", "storage hierarchy + master schema bootstrap",
         f"{_py_lines('init_db.py')} lines"),
        ("restore_backup.py", "CLI disaster-recovery restore utility",
         f"{_py_lines('restore_backup.py')} lines"),
        ("templates/", "portal HTML pages (admin, employee, index, verify)",
         f"{tmpl_n} files"),
        ("static/", "front-end assets (css / js / images)",
         f"{static_n} files, {static_js} JS"),
        ("docs/", "technical + user manuals (Robu KB sources) + figures",
         f"{docs_n} manual files + figures"),
        ("tests/", "the pinned gate (unittest, zero third-party deps)",
         f"{test_n} test modules"),
        ("data/", "runtime flat-file store (CSV, sessions, backups, logs) -- "
                   "runtime state, deliberately not counted",
         "runtime state"),
    ]


# --------------------------------------------------------------------------
# Rendering -- API reference
# --------------------------------------------------------------------------

def _paths_cell(predicates, html=False):
    sep = "<br>" if html else ", "
    parts = []
    for op, key in predicates:
        label = key + ("*" if op == "prefix" else "")
        parts.append(f"<code>{label}</code>" if html else f"`{label}`")
    return sep.join(parts)


def _match_cell(predicates):
    ops = {op for op, _ in predicates}
    return {("exact",): "exact", ("prefix",): "prefix"}.get(tuple(sorted(ops)), "exact+prefix")


def _module_responsibility(modules, name):
    return modules.get(name, {}).get("responsibility", "")


def _api_rows(entries, modules, html=False):
    rows = []
    for e in entries:
        handler = f"{e['module']}.{e['handler']}"
        if html:
            rows.append("| {i} | {paths} | {match} | <code>{h}</code> | <code>{m}</code> |".format(
                i=e["index"], paths=_paths_cell(e["predicates"], html=True),
                match=_match_cell(e["predicates"]), h=handler, m=e["module"]))
        else:
            rows.append("| {i} | {paths} | {match} | `{h}` | `{m}` |".format(
                i=e["index"], paths=_paths_cell(e["predicates"], html=False),
                match=_match_cell(e["predicates"]), h=handler, m=e["module"]))
    return rows


API_TABLE_HEADER = ("| # | Path | Match | Handler | Module |",
                    "|---|------|-------|---------|--------|")


def render_api_reference_md(entries, modules):
    get_entries = [e for e in entries if e["verb"] == "GET"]
    post_entries = [e for e in entries if e["verb"] == "POST"]
    paths = sum(len(e["predicates"]) for e in entries)
    lines = [
        "# NDLI Club Management -- Auto-Generated API Reference",
        "",
        BANNER_MD,
        "",
        f"**{len(entries)} dispatch entries** "
        f"({len(get_entries)} GET + {len(post_entries)} POST) across "
        f"**{len(modules)} route modules**, covering **{paths} distinct paths**. "
        "Counts and rows below are measured from `routes/__init__.py` at generation "
        "time -- if the router changes, `python3 gen_api_docs.py --check` fails until "
        "this file is regenerated.",
        "",
        "## Dispatch model",
        "",
    ]
    lines += [f"{p}  " for p in DISPATCH_PROSE]
    lines += [
        "",
        "Path legend: no suffix = exact match (`E(...)`), `*` = path-prefix match "
        "(`P(...)`).",
        "",
        "## GET endpoints (dispatch order)",
        "",
        API_TABLE_HEADER[0],
        API_TABLE_HEADER[1],
    ]
    lines += _api_rows(get_entries, modules)
    lines += [
        "",
        "## POST endpoints (dispatch order)",
        "",
        API_TABLE_HEADER[0],
        API_TABLE_HEADER[1],
    ]
    lines += _api_rows(post_entries, modules)
    lines += [
        "",
        "## Related hand-written sections",
        "",
        "The manual keeps request/response semantics in **sections 11-12** "
        "(REST API Specification) and per-module prose in **section 7** -- those are "
        "hand-authored. This file is the complete machine-generated index and never "
        "carries semantics, so it cannot disagree with the router.",
        "",
    ]
    return "\n".join(lines)


def render_architecture_map_md(entries, modules):
    comps = collect_components()
    lines = [
        "# NDLI Club Management -- Auto-Generated Architecture Map",
        "",
        BANNER_MD,
        "",
        "Sizes are **measured from the tree** at generation time. Roles are the "
        "stable one-line descriptions; numbers move whenever the code does.",
        "",
        "## Component map",
        "",
        "| Path | Role | Size |",
        "|------|------|------|",
    ]
    for path, role, size in comps:
        lines.append(f"| `{path}` | {role} | {size} |")
    lines += [
        "",
        "## Route module map (`routes/`)",
        "",
        "| Module | Responsibility | Dispatch entries | Lines |",
        "|--------|----------------|------------------|-------|",
    ]
    counts = {}
    for e in entries:
        counts[e["module"]] = counts.get(e["module"], 0) + 1
    for name in sorted(modules):
        info = modules[name]
        lines.append("| `{f}` | {resp} | {n} | {loc} |".format(
            f=info["file"], resp=info["responsibility"],
            n=counts.get(name, 0), loc=info["lines"]))
    lines += [
        "",
        f"**Total: {len(entries)} dispatch entries** "
        f"({sum(1 for e in entries if e['verb'] == 'GET')} GET + "
        f"{sum(1 for e in entries if e['verb'] == 'POST')} POST).",
        "",
        "## Request dispatch flow",
        "",
        "```text",
        ARCH_FLOW.rstrip("\n"),
        "```",
        "",
        "## Router invariants (pinned)",
        "",
        "- `app.py` must stay a request handler + startup module -- the dispatch "
        "chain cannot grow back into it (line-budget tripwire in "
        "`tests/test_router_extraction.py`).",
        "- Every registered route resolves to a callable in `routes/` -- pinned by "
        "`tests/test_router_extraction.py` and re-checked by "
        "`tests/test_r55_api_docs.py` against this document.",
        "- Both artifacts here + the manual appendix must match `routes/` exactly "
        f"-- `python3 {GENERATOR_NAME} --check` is the drift gate.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Rendering -- technical manual appendix
# --------------------------------------------------------------------------

def _html_table(header, rows):
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{h}</th>" for h in header]
    out.append("</tr></thead><tbody>")
    out += [f"<tr>{row}</tr>" for row in rows]
    out.append("</tbody></table>")
    return "\n".join(out)


def _api_rows_html(entries, modules):
    rows = []
    for e in entries:
        handler = f"{e['module']}.{e['handler']}"
        rows.append("<td>{i}</td><td>{paths}</td><td>{match}</td>"
                    "<td><code>{h}</code></td><td><code>{m}</code></td>".format(
                        i=e["index"], paths=_paths_cell(e["predicates"], html=True),
                        match=_match_cell(e["predicates"]), h=handler, m=e["module"]))
    return rows


def _chunk(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def build_appendix_pages(total_placeholder="{TOTAL}"):
    """Return the list of appendix page divs (strings), totals filled in later."""
    entries = collect_routes()
    modules = collect_route_modules()
    comps = collect_components()
    get_entries = [e for e in entries if e["verb"] == "GET"]
    post_entries = [e for e in entries if e["verb"] == "POST"]
    paths = sum(len(e["predicates"]) for e in entries)
    pages = []

    def page(body_parts, tag):
        return "\n".join([
            '  <div class="page-break"></div>',
            '  <div class="doc-page">',
            '    <div class="header-bar">',
            '      <span class="header-title-left">NDLI Technical Architecture Manual '
            '&bull; Client Handover Edition</span>',
            f'      <span class="header-tag-right">{tag}</span>',
            '    </div>',
            *body_parts,
            '  </div>',
        ])

    # -- page 1: title + component map ------------------------------------
    comp_rows = ["<td><code>{p}</code></td><td>{r}</td><td>{s}</td>".format(
        p=p, r=r, s=s) for p, r, s in comps]
    pages.append(page([
        '    <h1>Appendix A. Auto-Generated API Reference &amp; Architecture Map</h1>',
        '    <p>This appendix is <strong>generated from the code</strong> by '
        f'<code>{GENERATOR_NAME}</code> straight from the dispatch tables in '
        '<code>routes/</code> -- it can never disagree with the router. '
        'Hand-written request/response semantics stay in sections 11-12; '
        'module prose stays in section 7. Regenerate after any route change '
        f'(<code>python3 {GENERATOR_NAME}</code>), and run the drift gate '
        f'(<code>--check</code>) in CI / the test suite.</p>',
        '    <h2>A.1 Component Map (measured from the tree)</h2>',
        _html_table(["Path", "Role", "Size"], comp_rows),
    ], f"Page {{N}} of {total_placeholder}"))

    # -- page 2: route module map + dispatch flow -------------------------
    counts = {}
    for e in entries:
        counts[e["module"]] = counts.get(e["module"], 0) + 1
    mod_rows = ["<td><code>{f}</code></td><td>{resp}</td><td>{n}</td><td>{loc}</td>".format(
        f=info["file"], resp=info["responsibility"], n=counts.get(name, 0),
        loc=info["lines"]) for name, info in sorted(modules.items())]
    pages.append(page([
        '    <h2>A.2 Route Module Map (generated from routes/)</h2>',
        _html_table(["Module", "Responsibility", "Dispatch entries", "Lines"], mod_rows),
        '    <p><strong>Total: %d dispatch entries</strong> (%d GET + %d POST) '
        'covering %d distinct paths.</p>' % (
            len(entries), len(get_entries), len(post_entries), paths),
        '    <h2>A.3 Request Dispatch Flow</h2>',
        '    <pre style="font-size: 7.4pt; line-height: 1.35;">'
        + ARCH_FLOW.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + '</pre>',
    ], f"Page {{N}} of {total_placeholder}"))

    # -- API pages: GET then POST, chunked -------------------------------
    for title, subset in (("A.4 GET Endpoints (dispatch order)", get_entries),
                          ("A.5 POST Endpoints (dispatch order)", post_entries)):
        chunks = _chunk(subset, API_ROWS_PER_PAGE)
        for i, part in enumerate(chunks):
            lead = [
                f'    <h2>{title}{"" if not chunks or len(chunks) == 1 else f" ({i+1}/{len(chunks)})"}</h2>',
            ]
            if i == 0:
                lead.append(
                    '    <p>Path legend: no suffix = exact match, '
                    '<code>*</code> = path-prefix match. Rows are in dispatch '
                    'order -- the first matching row wins.</p>')
            lead.append(_html_table(
                ["#", "Path", "Match", "Handler", "Module"],
                _api_rows_html(part, modules)))
            pages.append(page(lead, f"Page {{N}} of {total_placeholder}"))

    return pages


def render_manual(manual_source):
    """Return the full expected technical_manual.html for this tree."""
    if MARKER_BEGIN not in manual_source or MARKER_END not in manual_source:
        raise ValueError(
            f"manual is missing the generated markers ({MARKER_BEGIN!r}) -- "
            "add the scaffold once, then regenerate")
    head, rest = manual_source.split(MARKER_BEGIN, 1)
    _old_block, tail = rest.split(MARKER_END, 1)

    # pages OUTSIDE the generated block + the cover = the base page count
    base_pages = (head + tail).count('class="doc-page"') + 1
    pages = build_appendix_pages()
    total = base_pages + len(pages)

    block = "\n\n".join(
        p.replace("{N}", str(base_pages + 1 + i)).replace("{TOTAL}", str(total))
        for i, p in enumerate(pages))
    merged = head + MARKER_BEGIN + "\n\n" + block + "\n\n" + MARKER_END + tail

    # repatch every page total (header tags + the @page CSS counter)
    merged = re.sub(r"(Page \d+ )of \d+", r"\g<1>of %d" % total, merged)
    merged = re.sub(r'(counter\(page\) " of )\d+', r"\g<1>%d" % total, merged)
    return merged


# --------------------------------------------------------------------------
# Artifact orchestration
# --------------------------------------------------------------------------

def compute_outputs(manual_source):
    """{relative_path: expected_content} for every generated artifact."""
    entries = collect_routes()
    modules = collect_route_modules()
    return {
        str(API_MD.relative_to(BASE)): render_api_reference_md(entries, modules),
        str(ARCH_MD.relative_to(BASE)): render_architecture_map_md(entries, modules),
        str(MANUAL.relative_to(BASE)): render_manual(manual_source),
    }


def diff_outputs(expected, actual_by_rel):
    """[(path, detail), ...] for artifacts that differ from the code's truth.

    Pure comparison -- `actual_by_rel` maps relative path to on-disk content
    (None / absent = file missing). Kept separate from file IO so the honesty
    of the drift gate is unit-testable (tests/test_r55_api_docs.py).
    """
    problems = []
    for rel, expected_content in expected.items():
        actual = actual_by_rel.get(rel)
        if actual is None:
            problems.append((rel, "MISSING (never generated?)"))
        elif actual != expected_content:
            problems.append((rel, f"STALE (on disk {len(actual)} bytes, "
                                  f"code says {len(expected_content)} bytes)"))
    return problems


def drift_report(manual_source):
    """[(path, detail), ...] for artifacts that differ from the code's truth."""
    expected = compute_outputs(manual_source)
    actual = {}
    for rel in expected:
        path = BASE / rel
        actual[rel] = path.read_text(encoding="utf-8") if path.is_file() else None
    return diff_outputs(expected, actual)


def main(argv):
    check_mode = "--check" in argv
    manual_source = MANUAL.read_text(encoding="utf-8") if MANUAL.is_file() else ""
    try:
        outputs = compute_outputs(manual_source)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    if check_mode:
        problems = drift_report(manual_source)
        if problems:
            print(f"{GENERATOR_NAME} --check: DRIFT DETECTED")
            for rel, detail in problems:
                print(f"  [STALE] {rel}: {detail}")
            print(f"run `python3 {GENERATOR_NAME}` to regenerate")
            return 1
        print(f"{GENERATOR_NAME} --check: all {len(outputs)} artifacts in sync "
              f"with routes/")
        return 0

    for rel, content in outputs.items():
        path = BASE / rel
        old = path.read_text(encoding="utf-8") if path.is_file() else None
        if old == content:
            print(f"  [same] {rel}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        verb = "wrote" if old is None else "updated"
        print(f"  [{verb}] {rel} ({len(content)} bytes)")
    print(f"done -- {len(outputs)} artifacts. drift gate: "
          f"`python3 {GENERATOR_NAME} --check`")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
