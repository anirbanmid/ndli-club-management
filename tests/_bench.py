"""
tests/_bench.py -- host-tolerant wall-clock budgets for the perf benchmarks.

WHY THIS EXISTS
---------------
`test_scale_50k_and_concurrency.py` and `test_scaling_benchmark.py` assert
wall-clock budgets (cold read < 2.5s, parse < 0.25s, > 20 req/s, ...).  On
shared/virtualised hosts the unchanged code runs several times slower under
transient CPU load -- measured on the PythonAnywhere Bash console: the very
same suite took 608s there vs ~220s on the reference box, and four one-shot
timing budgets failed with no code regression at all.  Wall-clock assertions
on an unknown box must therefore separate "the code got slower" from "the
host is slow right now".

WHAT THESE HELPERS DO
---------------------
* `measure(fn)` runs the timed operation several times and keeps the FASTEST
  attempt, so one scheduler stall cannot fail a run.
* Every budget is scaled by `host_factor()` (>= 1.0), measured at import time
  from a fixed CPU + file-IO workload (min-of-3) versus the reference box.
* `NDLI_BENCH_FACTOR` (env) multiplies every budget further -- an operator
  knob for a known-slow host.
* If the host is pathologically slow (`host_factor() >= SKIP_FACTOR`) a budget
  overrun SKIPS the timing check with a loud message instead of failing --
  the correctness assertions in those tests still run and still gate.
* `NDLI_BENCH_STRICT=1` disables ALL tolerance: fixed original budgets,
  single-shot semantics stay with the caller, and nothing is ever skipped.
  Use it when regression-hunting on a quiet machine.

This module is TEST-ONLY.  Production code never imports it.  Import it the
same way as `_seed_env` (flat `unittest discover -s tests` does not execute
tests/__init__.py, so every test module imports it directly).
"""
import csv as _csv
import os as _os
import tempfile as _tempfile
import time as _time

# ---------------------------------------------------------------------------
# Operator knobs
# ---------------------------------------------------------------------------
STRICT = _os.environ.get("NDLI_BENCH_STRICT", "").strip().lower() in ("1", "true", "yes")
try:
    ENV_FACTOR = float(_os.environ.get("NDLI_BENCH_FACTOR", "1") or 1)
except ValueError:
    ENV_FACTOR = 1.0
if ENV_FACTOR <= 0:
    ENV_FACTOR = 1.0

# Host slower than this x reference -> wall-clock checks are skipped (loudly),
# not failed.  Correctness checks are unaffected.
SKIP_FACTOR = 8.0

# ---------------------------------------------------------------------------
# Host-speed calibration (fixed workloads, min-of-3, vs reference box)
# ---------------------------------------------------------------------------
_CPU_LOOPS = 600000
_IO_ROWS = 10000
# min-of-3 on the reference box (Linux x64, CPython 3.12) -- re-measure and
# update if the workload below ever changes.
_CPU_BASELINE_S = 0.0268
_IO_BASELINE_S = 0.0197

_factor_cache = None


def _cpu_work():
    s = 0.0
    x = 1.0000001
    for _ in range(_CPU_LOOPS):
        s += x
        x = (x * 1.0000001) % 1000.0
    return s


def _io_work():
    tmp = _tempfile.mkdtemp(prefix="ndli_bench_calib_")
    path = _os.path.join(tmp, "calib.csv")
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["a", "b"])
            w.writeheader()
            w.writerows({"a": f"v{i}", "b": str(i)} for i in range(_IO_ROWS))
        with open(path, newline="", encoding="utf-8") as f:
            return len(list(_csv.DictReader(f)))
    finally:
        try:
            _os.remove(path)
            _os.rmdir(tmp)
        except OSError:
            pass


def _best_of(fn, n):
    best = None
    for _ in range(max(1, n)):
        t0 = _time.perf_counter()
        fn()
        dt = _time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    return best


def host_factor():
    """How slow this host is versus the reference box (always >= 1.0)."""
    global _factor_cache
    if _factor_cache is None:
        cpu = _best_of(_cpu_work, 3)
        io = _best_of(_io_work, 3)
        raw = max(cpu / _CPU_BASELINE_S, io / _IO_BASELINE_S)
        _factor_cache = max(1.0, raw)
        print(
            "[bench] host factor %.2f (cpu %.3f x ref, io %.3f x ref; "
            "budgets scaled, strict=%s)"
            % (_factor_cache, cpu / _CPU_BASELINE_S, io / _IO_BASELINE_S, STRICT)
        )
    return _factor_cache


def budget(base_seconds):
    """Effective wall-clock budget for a base budget in seconds."""
    if STRICT:
        return base_seconds
    return base_seconds * host_factor() * ENV_FACTOR


def measure(fn, attempts=3):
    """Run `fn` `attempts` times; return (fastest elapsed, result of that run).

    The operation must be repeatable and side-effect safe at the caller's
    discretion (attempts=1 for mutating operations).  Taking the fastest
    attempt absorbs single scheduler stalls on a loaded host.
    """
    if STRICT:
        attempts = 1
    best_t, best_r = None, None
    for _ in range(max(1, attempts)):
        t0 = _time.perf_counter()
        r = fn()
        dt = _time.perf_counter() - t0
        if best_t is None or dt < best_t:
            best_t, best_r = dt, r
    return best_t, best_r


def _label_budget(base):
    if STRICT:
        return "base %.4fs (STRICT)" % base
    return "base %.4fs x host %.2f x env %.2f" % (base, host_factor(), ENV_FACTOR)


def assert_time(tc, measured, base, label):
    """Assert `measured` seconds fits the (host-scaled) budget `base` seconds.

    Never lies: prints measured vs budget either way.  On a host slower than
    SKIP_FACTOR an overrun is reported as SKIP, not as a failure.
    """
    eff = budget(base)
    if measured < eff:
        print("[bench] PASS %s: %.4fs <= %.4fs (%s)" % (label, measured, eff, _label_budget(base)))
        return True
    if not STRICT and host_factor() >= SKIP_FACTOR:
        print(
            "[bench] SKIP %s: %.4fs > %.4fs (%s) -- host factor %.2f >= %.1f, "
            "host too slow to judge wall clock; timing check skipped, "
            "correctness checks still gate"
            % (label, measured, eff, _label_budget(base), host_factor(), SKIP_FACTOR)
        )
        return True
    tc.fail(
        "[BENCH] %s took %.4fs, over budget %.4fs (%s)"
        % (label, measured, eff, _label_budget(base))
    )
    return False


def assert_rate(tc, rps, min_rps, label):
    """Assert `rps` requests/sec clears `min_rps` (host-scaled downwards)."""
    if STRICT:
        eff = min_rps
        how = "min %.1f req/s (STRICT)" % min_rps
    else:
        eff = min_rps / (host_factor() * ENV_FACTOR)
        how = "min %.1f req/s / host %.2f / env %.2f" % (min_rps, host_factor(), ENV_FACTOR)
    if rps >= eff:
        print("[bench] PASS %s: %.1f req/s >= %.1f req/s (%s)" % (label, rps, eff, how))
        return True
    if not STRICT and host_factor() >= SKIP_FACTOR:
        print(
            "[bench] SKIP %s: %.1f req/s < %.1f req/s (%s) -- host factor %.2f >= %.1f, "
            "timing check skipped, correctness checks still gate"
            % (label, rps, eff, how, host_factor(), SKIP_FACTOR)
        )
        return True
    tc.fail(
        "[BENCH] %s throughput %.1f req/s below required %.1f req/s (%s)"
        % (label, rps, eff, how)
    )
    return False
