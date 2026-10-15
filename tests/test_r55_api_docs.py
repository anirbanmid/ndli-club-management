"""
tests/test_r55_api_docs.py

R55 pins -- "API reference + architecture map" (user task list 2026-10-14).

The endpoint reference and the architecture map are GENERATED from the router
by `gen_api_docs.py` (docs/API_REFERENCE.md, docs/ARCHITECTURE_MAP.md and
Appendix A of docs/technical_manual.html). Hand-written endpoint lists drift
from code; generated ones only drift if the GENERATOR is broken or someone
hand-edits the output. These pins close both holes:

  * the three artifacts match `routes/` exactly (drift gate, incl. CLI mode);
  * every dispatch entry <-> exactly one documented row (bijection, paths too);
  * every documented handler really exists in the named module (AST);
  * the architecture map covers every route module with measured counts;
  * the manual's generated appendix is marker-owned and its page totals are
    internally consistent (the "of N" bookkeeping is the fragile part);
  * the generator is deterministic, stdlib-only and outputs carry no
    timestamps / absolute paths.

No HTTP server. Pure structural checks + one subprocess (--check CLI).
"""
import _seed_env  # noqa: F401  (test-env convention; keeps discovery uniform)
import ast
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePath

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import gen_api_docs  # noqa: E402

API_MD = BASE_DIR / "docs" / "API_REFERENCE.md"
ARCH_MD = BASE_DIR / "docs" / "ARCHITECTURE_MAP.md"
MANUAL = BASE_DIR / "docs" / "technical_manual.html"

# One markdown row of the generated endpoint tables.
ROW_RE = re.compile(
    r"^\| (\d+) \| (.+?) \| (exact|prefix|exact\+prefix) \| `(\w+\.\w+)` \| `(\w+)` \|$")


def _read(path):
    return path.read_text(encoding="utf-8")


def _doc_rows(md_text, verb):
    """Rows of the GET/POST endpoint table -> dicts."""
    marker = f"## {verb} endpoints"
    section = md_text.split(marker, 1)[1]
    section = section.split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append({
                "index": int(m.group(1)),
                "paths": m.group(2),
                "match": m.group(3),
                "handler": m.group(4),
                "module": m.group(5),
            })
    return rows


def _paths_of(cell):
    """'| `/a`, `/b*` |' -> [(op, path), ...]"""
    out = []
    for token in re.findall(r"`([^`]+)`", cell):
        if token.endswith("*"):
            out.append(("prefix", token[:-1]))
        else:
            out.append(("exact", token))
    return out


class TestDriftGate(unittest.TestCase):
    """The docs may not disagree with the router, in-process or via the CLI."""

    def test_all_artifacts_are_in_sync_with_routes(self):
        problems = gen_api_docs.drift_report(_read(MANUAL))
        self.assertEqual(problems, [],
                         "generated artifacts drifted from routes/: "
                         f"{problems} -- run `python3 gen_api_docs.py`")

    def test_check_mode_cli_is_clean(self):
        r = subprocess.run([sys.executable, gen_api_docs.GENERATOR_NAME, "--check"],
                           cwd=str(BASE_DIR), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("in sync", r.stdout)

    def test_drift_detection_is_honest(self):
        """A tampered artifact must be flagged -- the gate cannot pass vacuously."""
        expected = gen_api_docs.compute_outputs(_read(MANUAL))
        actual = dict(expected)
        rel = str(API_MD.relative_to(BASE_DIR))
        actual[rel] = actual[rel].replace("| 1 | ", "| 99 | ", 1)
        self.assertNotEqual(actual[rel], expected[rel], "tamper must change bytes")

        flagged = gen_api_docs.diff_outputs(expected, actual)
        self.assertEqual([p for p, _ in flagged], [rel],
                         "exactly the tampered artifact must be reported")

    def test_renderer_is_sensitive_to_router_changes(self):
        """Dropping a route must change the rendered docs (not static text)."""
        entries = gen_api_docs.collect_routes()
        modules = gen_api_docs.collect_route_modules()
        full = gen_api_docs.render_api_reference_md(entries, modules)
        shorter = gen_api_docs.render_api_reference_md(entries[:-1], modules)
        self.assertNotEqual(full, shorter)
        self.assertIn(f"`{entries[-1]['module']}.{entries[-1]['handler']}`", full)
        self.assertNotIn(f"`{entries[-1]['module']}.{entries[-1]['handler']}`", shorter)


class TestRouterBijection(unittest.TestCase):
    """Every dispatch entry <-> exactly one documented row (and vice versa)."""

    def setUp(self):
        self.entries = gen_api_docs.collect_routes()
        self.md = _read(API_MD)

    def test_dispatch_counts_match_the_router(self):
        for verb in ("GET", "POST"):
            with self.subTest(verb=verb):
                want = [e for e in self.entries if e["verb"] == verb]
                rows = _doc_rows(self.md, verb)
                self.assertEqual(len(rows), len(want))
                self.assertEqual([r["index"] for r in rows],
                                 [e["index"] for e in want],
                                 "documented rows must keep dispatch order")

    def test_every_documented_handler_is_the_router_handler(self):
        for verb in ("GET", "POST"):
            want = [e for e in self.entries if e["verb"] == verb]
            rows = _doc_rows(self.md, verb)
            for row, entry in zip(rows, want):
                self.assertEqual(row["handler"],
                                 f"{entry['module']}.{entry['handler']}")
                self.assertEqual(row["module"], entry["module"])

    def test_every_documented_path_is_a_router_path(self):
        for verb in ("GET", "POST"):
            with self.subTest(verb=verb):
                want = [e for e in self.entries if e["verb"] == verb]
                rows = _doc_rows(self.md, verb)
                for row, entry in zip(rows, want):
                    self.assertEqual(_paths_of(row["paths"]), entry["predicates"],
                                     "path cell must list every matcher key "
                                     "exactly (prefix keys with *)")

    def test_every_documented_handler_exists_in_its_module(self):
        index = gen_api_docs.defined_handler_index(gen_api_docs.collect_route_modules())
        for e in self.entries:
            with self.subTest(handler=e["handler"]):
                self.assertIn((e["module"], e["handler"]), index,
                              f"{e['module']}.{e['handler']} is dispatched but "
                              "not defined in its module")

    def test_no_handler_is_dispatched_twice_unless_documented(self):
        seen = {}
        for e in self.entries:
            key = (e["module"], e["handler"])
            seen.setdefault(key, []).append(e)
        documented = [r["handler"] for r in _doc_rows(self.md, "GET")
                      + _doc_rows(self.md, "POST")]
        for (module, handler), group in seen.items():
            with self.subTest(handler=handler):
                self.assertEqual(documented.count(f"{module}.{handler}"), len(group),
                                 "one documented row per dispatch entry")


class TestArchitectureMap(unittest.TestCase):
    """The map covers the tree it claims to cover, with measured numbers."""

    def setUp(self):
        self.md = _read(ARCH_MD)
        self.entries = gen_api_docs.collect_routes()
        self.modules = gen_api_docs.collect_route_modules()

    def test_covers_every_route_module(self):
        for name, info in self.modules.items():
            with self.subTest(module=name):
                self.assertIn(info["file"], self.md)

    def test_module_entry_counts_are_measured(self):
        counts = {}
        for e in self.entries:
            counts[e["module"]] = counts.get(e["module"], 0) + 1
        for name, n in counts.items():
            with self.subTest(module=name):
                row = next(ln for ln in self.md.splitlines()
                           if ln.startswith(f"| `routes/{name}.py`"))
                self.assertIn(f"| {n} |", row)

    def test_totals_are_measured_not_waved_through(self):
        self.assertIn(f"{len(self.entries)} dispatch entries", self.md)
        gets = sum(1 for e in self.entries if e["verb"] == "GET")
        posts = sum(1 for e in self.entries if e["verb"] == "POST")
        self.assertIn(f"{gets} GET + {posts} POST", self.md)

    def test_dispatch_flow_documents_first_match_wins(self):
        self.assertIn("FIRST match wins", self.md)
        self.assertIn("routes.match(GET_ROUTES | POST_ROUTES, path)", self.md)


class TestManualAppendix(unittest.TestCase):
    """Appendix A is marker-owned and its page bookkeeping is consistent."""

    def setUp(self):
        self.html = _read(MANUAL)

    def test_generated_markers_appear_exactly_once(self):
        self.assertEqual(self.html.count(gen_api_docs.MARKER_BEGIN), 1)
        self.assertEqual(self.html.count(gen_api_docs.MARKER_END), 1)
        self.assertLess(self.html.index(gen_api_docs.MARKER_BEGIN),
                        self.html.index(gen_api_docs.MARKER_END))

    def test_appendix_heading_and_nav_entry_exist(self):
        self.assertIn("Appendix A. Auto-Generated API Reference", self.html)
        self.assertIn("Appendix A. Auto-Generated API Reference "
                      "&amp; Architecture Map</span>", self.html)

    def test_page_totals_are_internally_consistent(self):
        tags = re.findall(r"Page (\d+) of (\d+)", self.html)
        self.assertTrue(tags, "no page tags found")
        totals = {int(t[1]) for t in tags}
        self.assertEqual(len(totals), 1,
                         f"page totals disagree: {sorted(totals)}")
        total = totals.pop()
        pages = {int(t[0]) for t in tags}
        self.assertEqual(pages, set(range(2, total + 1)),
                         "header tags must number pages 2..N (page 1 = cover)")
        doc_pages = self.html.count('class="doc-page"')
        self.assertEqual(total, doc_pages + 1,
                         "total = cover + doc-page count")
        css = re.findall(r'counter\(page\) " of (\d+)"', self.html)
        self.assertEqual(css, [str(total)],
                         "@page CSS total must match the header tags")

    def test_appendix_documents_every_dispatch_entry(self):
        block = self.html.split(gen_api_docs.MARKER_BEGIN, 1)[1] \
                         .split(gen_api_docs.MARKER_END, 1)[0]
        for e in gen_api_docs.collect_routes():
            with self.subTest(handler=e["handler"]):
                self.assertIn(f"{e['module']}.{e['handler']}", block)

    def test_appendix_does_not_swallow_hand_written_sections(self):
        # sections 11-12 (hand-written semantics) must survive generation
        self.assertIn("11. REST API Specification", self.html)
        self.assertIn("12. REST API Specification", self.html)


class TestJunkProofMeasurements(unittest.TestCase):
    """R55v2: measured counts must never move because of backups/caches.

    Regression pin for the first R55 PA install: a `style.css.pre_r20` backup
    sat in static/ on the BUILD host only -> the shipped counts disagreed
    with the deployed tree -> same-size stale docs. Backups, bytecode caches
    and editor droppings are not tree content.
    """

    def test_is_junk_knows_the_offenders(self):
        junk = ["style.css.pre_r20", "x.bak", "x.pyc", "x.pyo",
                ".DS_Store", "y~", "z.pre_r55.bak", "w.orig", "w.rej"]
        clean = ["style.css", "app.py", "site.webmanifest",
                 "test_r55_api_docs.py", "style.css.pre_r20.png"]
        for name in junk:
            with self.subTest(name=name):
                self.assertTrue(gen_api_docs._is_junk(Path("static") / name))
        for name in clean:
            with self.subTest(name=name):
                self.assertFalse(gen_api_docs._is_junk(Path("static") / name))
        self.assertTrue(gen_api_docs._is_junk(Path("static/__pycache__/x.py")))

    def test_measured_counts_ignore_junk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "static").mkdir()
            for name in ("a.css", "b.css",              # counted
                         "style.css.pre_r20", ".DS_Store", "c.bak"):
                (root / "static" / name).write_text("x")
            (root / "static" / "__pycache__").mkdir()
            (root / "static" / "__pycache__" / "d.pyc").write_text("x")
            self.assertEqual(gen_api_docs._file_count("static", root=root), 2,
                             "backups / caches / droppings must not count")
            self.assertEqual(gen_api_docs._file_count("static", "**/*.css", root=root), 2)

    def test_arch_map_counts_exclude_junk_independent_recount(self):
        """Arch map's static/ count == a recount with a RE-IMPLEMENTED rule.

        The rule is duplicated here on purpose: a regression in
        gen_api_docs._is_junk must not be able to hide behind itself.
        R57: the clean-clone contract also excludes GITIGNORED host
        artifacts (a deployed tree can carry them; a clean clone never does)
        -- the artifact half is re-implemented here too, straight from
        .gitignore, without calling the generator's rule.
        """
        gi_pats = []
        for ln in (BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith(("#", "!")):
                segs = [s for s in ln.strip("/").split("/") if s]
                if len(segs) == 1:      # any-level name patterns suffice here
                    gi_pats.append(segs[0])
        row = next(ln for ln in _read(ARCH_MD).splitlines()
                   if ln.startswith("| `static/`"))
        documented = int(re.search(r"\| (\d+) files", row).group(1))

        def is_artifact(rel):
            return any(PurePath(seg).match(pat)
                       for seg in rel.parts for pat in gi_pats)

        clean = [p for p in (BASE_DIR / "static").glob("**/*")
                 if p.is_file()
                 and "__pycache__" not in p.parts
                 and not p.name.startswith(".")
                 and not p.name.endswith((".pyc", ".pyo", ".bak", ".orig", ".rej", "~"))
                 and not re.search(r"\.pre_r\d+(?:\.bak)?$", p.name)
                 and not is_artifact(p.relative_to(BASE_DIR))]
        self.assertEqual(documented, len(clean))


class TestGeneratorHygiene(unittest.TestCase):
    """Deterministic, stdlib-only, and boring outputs."""

    def test_outputs_are_deterministic(self):
        first = gen_api_docs.compute_outputs(_read(MANUAL))
        second = gen_api_docs.compute_outputs(_read(MANUAL))
        self.assertEqual(first, second)

    def test_generator_is_stdlib_only(self):
        tree = ast.parse(_read(BASE_DIR / gen_api_docs.GENERATOR_NAME))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        stdlib = getattr(sys, "stdlib_module_names", frozenset(
            {"ast", "re", "sys", "pathlib", "unittest", "subprocess", "typing",
             "collections", "json", "os", "math", "hashlib", "tempfile", "shutil"}))
        self.assertEqual(imported - set(stdlib), set(),
                         "the repo runs zero third-party dependencies")

    def test_outputs_carry_no_timestamps_or_absolute_paths(self):
        for rel, content in gen_api_docs.compute_outputs(_read(MANUAL)).items():
            with self.subTest(artifact=rel):
                self.assertNotIn(str(BASE_DIR), content)
                self.assertNotIn("\r", content)

    def test_generated_docs_carry_the_banner(self):
        for md in (API_MD, ARCH_MD):
            with self.subTest(artifact=md.name):
                self.assertIn(gen_api_docs.BANNER_MD, _read(md))


if __name__ == "__main__":
    unittest.main()
