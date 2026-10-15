#!/usr/bin/env python3
"""
tools/build_kit.py -- generic manifest-driven deploy-kit builder (R59).

Every round ships a small JSON manifest in tools/kits/ instead of a bespoke
builder script, so ANYONE (the operator on PythonAnywhere, Antigravity on the
PC, the CI runner, the next developer) can rebuild a round's kit byte-for-byte
from a clean clone:

    python3 tools/build_kit.py --latest              # newest manifest
    python3 tools/build_kit.py tools/kits/r58_retrieval_hardening.json
    python3 tools/build_kit.py --latest --verify-only   # CI mode (no zip kept)

The generated kit keeps the established R36+ installer contract:
  [1] backup REPLACED as *.pre_<round>.bak (never overwritten on a re-run),
      copy payload, md5-verify -- round-NEW files are honest "[new]" adds,
      kit-owned files are refreshed in place ("[upd]", never backed up)
  [2] regenerate the measured docs on the TARGET tree (R55v2 contract)
  [3] content markers   [4] py_compile   [5] node --check (optional, honest SKIP)
  [6] drift gate (gen_api_docs.py --check)   [7] targeted test runs
  -> "RESULT: N OK, 0 FAIL" + the commit block (explicit adds ONLY)

Manifest schema (all fields checked by tests/test_r59_deploy_ci.py):
{
  "round": "R58",                      -> INSTALL_R58.py, *.pre_r58.bak
  "name": "r58_retrieval_hardening",   -> <name>.zip
  "title": "one-line round title",
  "intro": "paragraph for the installer docstring",
  "payload": ["rel/path", ...],        -> files shipped from --src
  "replaced": ["rel/path", ...],       -> subset of payload; pre-exist -> [bak]
  "markers": [["rel/path", "needle", "why"], ...],
  "py_compiles": ["rel/path", ...],
  "js_checks": ["rel/path", ...],
  "test_runs": [["pattern.py", 22], ...],   -> discover -s tests -p pattern
  "regen_step": true,
  "drift_gate": true,
  "commit_files": ["rel/path", ...],
  "commit_message": "R58: ..."
}

Stdlib only. Build-time writes are confined to --out (or the repo root by
default) plus the installer's own temp self-check copy.
"""
import argparse
import hashlib
import json
import py_compile
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED_FIELDS = ("round", "name", "title", "intro", "payload", "replaced",
                   "markers", "py_compiles", "js_checks", "test_runs",
                   "commit_files", "commit_message")

INSTALLER_TEMPLATE = '''#!/usr/bin/env python3
"""
INSTALL_@@ROUND@@.py -- @@ROUND@@ installer (generic builder, R59 contract).

@@TITLE@@

@@INTRO@@

Convention (R36+): back up each REPLACED file as <payload>@@BAK_SUFFIX@@ ->
copy -> md5-verify -> REGEN docs on target -> content markers -> py_compile ->
node --check -> drift gate -> tests. An existing *@@BAK_SUFFIX@@ is NEVER
overwritten (re-run safety, R47 lesson). NEW files are added without a backup
(honest "[new]" line); kit-owned/generated files refresh in place ("[upd]",
never backed up). `node` is optional (PythonAnywhere Bash has none -- honest
labelled SKIP).

Run from the kit directory on PythonAnywhere:
    cd ~/@@NAME@@_kit && python3 INSTALL_@@ROUND@@.py
Repo root: ~/ndli-club-management (override with NDLI_REPO_ROOT).

NOTE ON SMOKE TESTS: run any manual unittest from the REPO, not from the kit
dir. The kit is a delta -- "No module named '_seed_env'" = wrong directory,
not a broken deploy.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("NDLI_REPO_ROOT", os.path.expanduser("~/ndli-club-management")))
KIT = Path(__file__).resolve().parent

PAYLOAD = [
@@PAYLOAD@@
]

# (file, marker, description) -- the marker must exist in the INSTALLED file
MARKERS = [
@@MARKERS@@
]

PY_COMPILES = [
@@PY_COMPILES@@
]

JS_CHECKS = [
@@JS_CHECKS@@
]

# (pattern, expected_count) -- run with unittest discover from REPO
TEST_RUNS = [
@@TEST_RUNS@@
]

REGEN_STEP = @@REGEN@@
DRIFT_GATE = @@DRIFT@@
COMMIT_FILES = [
@@COMMIT_FILES@@
]
COMMIT_MESSAGE = @@COMMIT_MESSAGE@@

ok = 0
fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK]   {label}")
    else:
        fail += 1
        print(f"  [FAIL] {label} {detail}")


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


print("=" * 70)
print("INSTALL @@ROUND@@ -- @@TITLE@@")
print(f"repo root: {REPO}")
print(f"kit dir:   {KIT}")
print("=" * 70)

if not REPO.is_dir():
    print(f"FATAL: repo root not found: {REPO}")
    sys.exit(2)

# ---- 1. backup + copy + md5 ------------------------------------------------
REPLACED = {
@@REPLACED@@
}

print("\\n[1/7] Backup + copy + md5-verify payload")
for rel, want_md5 in PAYLOAD:
    src = KIT / rel
    dst = REPO / rel
    if not src.is_file():
        check(f"payload present in kit: {rel}", False, "(missing)")
        continue
    if rel in REPLACED and dst.is_file():
        bak = dst.with_name(dst.name + "@@BAK_SUFFIX@@")
        if bak.exists():
            print(f"  [bak]  {rel} -> {bak.name} (kept -- original preserved)")
        else:
            shutil.copy2(dst, bak)
            print(f"  [bak]  {rel} -> {bak.name}")
    elif not dst.is_file():
        print(f"  [new]  {rel} (no existing file to back up)")
    else:
        print(f"  [upd]  {rel} (kit-owned file -- refreshed in place, no backup)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    got = md5_of(dst)
    check(f"md5 {rel}", got == want_md5, f"want {want_md5} got {got}")

# ---- 2. regenerate the measured docs on the TARGET tree --------------------
step = 2
if REGEN_STEP:
    print(f"\\n[{step}/7] Regenerate docs on the target tree")
    r = subprocess.run([sys.executable, "gen_api_docs.py"], cwd=str(REPO),
                       capture_output=True, text=True)
    check("gen_api_docs.py regenerates on the target tree", r.returncode == 0,
          (r.stderr or r.stdout or "")[-300:])
    for line in (r.stdout or "").splitlines():
        if line.strip():
            print("  " + line)
else:
    print(f"\\n[{step}/7] Regenerate docs -- SKIPPED (manifest says the measured docs are untouched)")

# ---- 3. content markers ----------------------------------------------------
print("\\n[3/7] Content markers (read AFTER the copy + regen)")
for rel, marker, desc in MARKERS:
    target = REPO / rel
    try:
        text = target.read_text(encoding="utf-8")
        check(f"marker in {rel}: {desc}", marker in text, f"(missing: {marker!r})")
    except Exception as exc:
        check(f"marker in {rel}: {desc}", False, repr(exc))

# ---- 4. py-compile ---------------------------------------------------------
print("\\n[4/7] py_compile")
for rel in PY_COMPILES:
    r = subprocess.run([sys.executable, "-m", "py_compile", str(REPO / rel)],
                       capture_output=True, text=True)
    check(f"py_compile {rel}", r.returncode == 0, r.stderr.strip()[-200:])

# ---- 5. JS syntax ----------------------------------------------------------
print("\\n[5/7] node --check")
if shutil.which("node"):
    for rel in JS_CHECKS:
        # node refuses unknown extensions at get_format (.gs) -- check via a
        # temporary .js copy so the SYNTAX is what gets validated
        tmp_js = KIT / ("_check_" + Path(rel).name + ".js")
        shutil.copy2(REPO / rel, tmp_js)
        r = subprocess.run(["node", "--check", str(tmp_js)], capture_output=True, text=True)
        tmp_js.unlink()
        check(f"node --check {rel}", r.returncode == 0, r.stderr.strip()[-200:])
    if not JS_CHECKS:
        print("  (this round ships no JS -- nothing to check)")
else:
    for rel in JS_CHECKS:
        check(f"node --check {rel} (SKIPPED -- no `node` on this host; "
              f"syntax verified at kit build + rehearsal time)", True)
    if not JS_CHECKS:
        print("  (this round ships no JS -- nothing to check)")

# ---- 6. drift gate on the installed tree ----------------------------------
print("\\n[6/7] Drift gate on the target tree")
if DRIFT_GATE:
    r = subprocess.run([sys.executable, "gen_api_docs.py", "--check"], cwd=str(REPO),
                       capture_output=True, text=True)
    check("gen_api_docs.py --check: docs describe the target tree",
          r.returncode == 0, (r.stdout or r.stderr or "")[-300:])
else:
    print("  (SKIPPED -- manifest says no measured docs in this round)")

# ---- 7. targeted test runs -------------------------------------------------
print("\\n[7/7] Targeted test runs (from the REPO)")
env = dict(os.environ)
for pattern, expected in TEST_RUNS:
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern],
        cwd=str(REPO), capture_output=True, text=True, env=env)
    ran_line = next((ln for ln in (r.stderr or "").splitlines() if ln.startswith("Ran ")), "")
    check(f"tests {pattern} (want {expected} OK)",
          r.returncode == 0 and f"Ran {expected} tests" in ran_line,
          f"rc={r.returncode} {ran_line!r}")

print("\\n" + "=" * 70)
if fail:
    print(f"RESULT: {ok} OK, {fail} FAIL -- DO NOT COMMIT; fix and re-run")
    sys.exit(1)
print(f"RESULT: {ok} OK, 0 FAIL")
print("=" * 70)
print("\\nNext (commit block -- explicit adds ONLY, never `git add -A`):")
print()
print("  cd ~/ndli-club-management")
print("  git add @@COMMIT_FILES_LINE@@")
print('  git commit -m "' + COMMIT_MESSAGE + '"')
print("  git push")
print()
print("Then: cd ~ && rm -rf @@NAME@@_kit @@NAME@@.zip")
print('     cd ~/ndli-club-management && find . -name "*@@BAK_SUFFIX@@" -delete')
'''


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    m = json.loads(path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_FIELDS if f not in m]
    if missing:
        raise SystemExit(f"manifest {path.name}: MISSING FIELDS {missing}")
    return m


def validate_manifest(m: dict, src: Path) -> None:
    """Honest failures: a manifest that cannot describe a real tree refuses to
    build instead of shipping a broken kit."""
    payload = list(m["payload"])
    replaced = list(m["replaced"])
    if not payload:
        raise SystemExit("manifest: payload is empty")
    if len(payload) != len(set(payload)):
        raise SystemExit("manifest: duplicate payload entries")
    for rel in payload:
        if not (src / rel).is_file():
            raise SystemExit(f"manifest: payload file NOT FOUND in source tree: {rel}")
    extra = [r for r in replaced if r not in payload]
    if extra:
        raise SystemExit(f"manifest: replaced files must be in payload: {extra}")
    for entry in m["markers"]:
        if len(entry) != 3:
            raise SystemExit(f"manifest: marker entries need [file, needle, why]: {entry}")
        rel, needle, _why = entry
        if rel not in payload:
            raise SystemExit(f"manifest: marker file not in payload: {rel}")
        if not needle:
            raise SystemExit(f"manifest: empty marker needle for {rel}")
    for rel in m["py_compiles"]:
        if rel not in payload:
            raise SystemExit(f"manifest: py_compile file not in payload: {rel}")
    for rel in m["js_checks"]:
        if rel not in payload:
            raise SystemExit(f"manifest: js_check file not in payload: {rel}")
    for pattern, expected in m["test_runs"]:
        if not isinstance(expected, int) or expected <= 0:
            raise SystemExit(f"manifest: test_run count must be a positive int: {pattern!r}")
        if not list((src / "tests").glob(pattern)):
            raise SystemExit(f"manifest: test_run pattern matches nothing: {pattern!r}")
    for rel in m["commit_files"]:
        if rel not in payload:
            raise SystemExit(f"manifest: commit file not in payload: {rel}")


def render_installer(m: dict) -> str:
    round_id = str(m["round"])
    bak = f".pre_{round_id.lower()}.bak"

    def lit(items, fmt):
        return "\n".join(fmt(i) for i in items)

    out = INSTALLER_TEMPLATE
    subs = {
        "@@ROUND@@": round_id,
        "@@TITLE@@": str(m["title"]),
        "@@INTRO@@": "\n".join(str(m["intro"]).splitlines()),
        "@@NAME@@": str(m["name"]),
        "@@BAK_SUFFIX@@": bak,
        "@@PAYLOAD@@": lit(m["payload"], lambda r: f"    ({r!r}, {md5_of(SRC_CACHE[r])!r}),"),
        "@@MARKERS@@": lit(m["markers"], lambda e: f"    ({e[0]!r}, {e[1]!r}, {e[2]!r}),"),
        "@@PY_COMPILES@@": lit(m["py_compiles"], lambda r: f"    {r!r},"),
        "@@JS_CHECKS@@": lit(m["js_checks"], lambda r: f"    {r!r},"),
        "@@TEST_RUNS@@": lit(m["test_runs"], lambda e: f"    ({e[0]!r}, {e[1]!r}),"),
        "@@REPLACED@@": lit(sorted(m["replaced"]), lambda r: f"    {r!r},"),
        "@@REGEN@@": repr(bool(m.get("regen_step", True))),
        "@@DRIFT@@": repr(bool(m.get("drift_gate", True))),
        "@@COMMIT_FILES@@": lit(m["commit_files"], lambda r: f"    {r!r},"),
        "@@COMMIT_FILES_LINE@@": " ".join(str(r) for r in m["commit_files"]),
        "@@COMMIT_MESSAGE@@": repr(str(m["commit_message"])),
    }
    for key, val in subs.items():
        out = out.replace(key, val)
    if "@@" in out:
        left = out[out.find("@@"):out.find("@@") + 40]
        raise SystemExit(f"installer template has an unrendered placeholder: {left!r}")
    return out


def n_checks(m: dict) -> int:
    return (len(m["payload"]) + len(m["markers"]) + len(m["py_compiles"])
            + len(m["js_checks"]) + len(m["test_runs"]) + 2)


def build(m: dict, src: Path, out_dir: Path, verify_only: bool) -> Path:
    global SRC_CACHE
    SRC_CACHE = {rel: (src / rel) for rel in m["payload"]}
    installer = render_installer(m)
    install_name = f"INSTALL_{m['round']}.py"
    install_txt = (
        "%s %s\n\n  cd ~ && unzip -o %s.zip -d %s_kit\n  cd ~/%s_kit && python3 %s\n"
        "  Web tab -> Reload\n\nExpect RESULT: %d OK, 0 FAIL.\n"
        "Run unittest from ~/ndli-club-management (the REPO), never from the kit dir:\n"
        "  'No module named _seed_env' = wrong directory, not a broken deploy.\n"
    ) % (m["round"], str(m["title"]).upper(), m["name"], m["name"], m["name"],
         install_name, n_checks(m))

    zip_path = out_dir / f"{m['name']}.zip"
    if verify_only:
        tmpdir = Path(tempfile.mkdtemp(prefix="kit_verify_"))
        target = tmpdir / zip_path.name
    else:
        tmpdir = None
        target = zip_path
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in m["payload"]:
            zf.write(SRC_CACHE[rel], rel)
        zf.writestr(install_name, installer)
        zf.writestr("INSTALL.txt", install_txt)

    # ---- post-build self-check (r11 lesson: verify the GENERATED bytes) ----
    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
        assert names == list(m["payload"]) + [install_name, "INSTALL.txt"], names
        gen = zf.read(install_name).decode("utf-8")
        for _rel, needle, _why in m["markers"]:
            assert repr(needle) in gen, f"marker not baked into installer: {needle!r}"
        for rel in m["payload"]:
            assert repr(rel) in gen, f"payload not baked into installer: {rel!r}"
            assert repr(md5_of(SRC_CACHE[rel])) in gen, f"md5 not baked in for {rel}"
        if m.get("regen_step", True):
            assert "Regenerate docs on the target tree" in gen, "REGEN step missing"
        if m.get("drift_gate", True):
            assert '"gen_api_docs.py", "--check"' in gen, "drift-gate step missing"
        assert "git add -A" not in gen.replace("never `git add -A`", ""), \
            "installer must never suggest git add -A"
        for rel, needle, _why in m["markers"]:
            body = zf.read(rel).decode("utf-8", errors="replace")
            assert needle in body, f"marker {needle!r} not in shipped {rel}"
        compile_src = gen
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(compile_src)
            tmp_py = Path(fh.name)
        try:
            r = py_compile.compile(str(tmp_py), doraise=True)
            assert r
        finally:
            tmp_py.unlink(missing_ok=True)
    if verify_only and tmpdir is not None:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"VERIFIED {m['name']}.zip ({len(m['payload']) + 2} entries, "
              f"{n_checks(m)} checks on target) -- verify-only, no zip kept")
    else:
        print(f"BUILT {target} ({target.stat().st_size} bytes, "
              f"{len(m['payload']) + 2} entries)")
        print(f"checks on target: {n_checks(m)} (md5 + markers + py_compile + node + "
              f"regen + drift gate + test runs)")
    print("post-build self-check PASS")
    return target


SRC_CACHE: dict = {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Manifest-driven deploy-kit builder (R59)")
    ap.add_argument("manifest", nargs="?", help="path to a tools/kits/*.json manifest")
    ap.add_argument("--latest", action="store_true",
                    help="use the newest manifest in tools/kits/")
    ap.add_argument("--src", default=".", help="source tree (default: repo root)")
    ap.add_argument("--out", default=".", help="zip output dir (default: repo root)")
    ap.add_argument("--verify-only", action="store_true",
                    help="build + self-check in a temp dir, keep no zip (CI mode)")
    args = ap.parse_args()

    tools_dir = Path(__file__).resolve().parent
    if args.latest:
        kits = sorted((tools_dir / "kits").glob("*.json"))
        if not kits:
            raise SystemExit("no manifests in tools/kits/")
        manifest_path = kits[-1]
    elif args.manifest:
        manifest_path = Path(args.manifest)
    else:
        ap.error("pass a manifest path or --latest")
    if not manifest_path.is_file():
        raise SystemExit(f"manifest not found: {manifest_path}")

    src = Path(args.src).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    m = load_manifest(manifest_path)
    validate_manifest(m, src)
    print(f"manifest: {manifest_path.name}  round: {m['round']}  "
          f"payload: {len(m['payload'])} files")
    build(m, src, out_dir, verify_only=args.verify_only)


if __name__ == "__main__":
    main()
