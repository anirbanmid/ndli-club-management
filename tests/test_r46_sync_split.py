"""
tests/test_r46_sync_split.py

Anti-regression pins for R46 -- "split db/sync_engine.py (1,741 lines) into
domain modules" (the last big monolith, same mechanical recipe as the R39
app.py -> routes/ extraction).

The split is PROVEN mechanical by .openclaw/tmp/verify_sync_split.py (byte-
identical segments + inverse-transform round-trip + helper equality).  These
tests pin the NEW SHAPE so the monolith cannot quietly grow back:

  * db/sync_engine.py is a zero-logic facade: re-exports + class assembly only
    (line budget + zero `def` lock).
  * db/sync/state.py is the ONE home for the engine lock and the dedupe window.
  * no definition may exist twice across the sync surface (drift = the R37
    disease R38 fixed; R45 fixed its redaction twin -- same principle).
  * the historical public surface keeps working from db.sync_engine.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import ast
import re
import unittest
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FACADE = BASE_DIR / "db" / "sync_engine.py"
SYNC_DIR = BASE_DIR / "db" / "sync"

# Measured 2026-10-13 (R46): the facade is 31 lines.  The budget is the
# tripwire -- new logic belongs in db/sync/, never in the facade.
FACADE_LINE_BUDGET = 45

DOMAIN_MODULES = ("paths", "activities", "employees", "clubs", "quota", "maintenance")
MIXIN_CLASSES = ("SyncPathsMixin", "SyncActivitiesMixin", "SyncEmployeesMixin",
                 "SyncClubsMixin", "SyncQuotaMixin", "SyncMaintenanceMixin")

DATE_HELPERS = ("_parse_string_date", "parse_iso_or_date", "calculate_next_renewal_date",
                "parse_iso_datetime", "_add_one_year", "calculate_next_renewal_due")

METHODS = ("get_employee_dir", "get_employee_credentials_path", "get_employee_clubs_path",
           "get_employee_activities_path", "get_employee_issues_path", "bucket_activity",
           "combined_activities_for", "_migrate_club_csv_headers", "initialize_storage_hierarchy",
           "provision_employee_node", "update_employee_records", "log_support_activity",
           "approve_new_club", "recompute_and_persist_quota", "delete_club",
           "delete_activity_log_entries", "hard_reset_for_handover", "wipe_training_slots",
           "update_club", "correct_club_dates", "find_club_by_reg_no",
           "renew_club_registration", "_increment_quota", "reconcile_all_nodes")


def _read(rel: str) -> str:
    return (BASE_DIR / rel).read_text(encoding="utf-8")


def _sync_surface() -> dict:
    texts = {"db/sync_engine.py": _read("db/sync_engine.py")}
    for p in sorted(SYNC_DIR.glob("*.py")):
        texts[f"db/sync/{p.name}"] = p.read_text(encoding="utf-8")
    return texts


class TestSplitShape(unittest.TestCase):
    """The new layout itself is the contract."""

    def test_sync_package_layout(self):
        self.assertTrue((SYNC_DIR / "__init__.py").is_file())
        modules = sorted(p.name for p in SYNC_DIR.glob("*.py") if p.name != "__init__.py")
        expected = sorted(f"{m}.py" for m in (*DOMAIN_MODULES, "dates", "state"))
        self.assertEqual(expected, modules,
                         "db/sync/ must hold exactly the R46 modules "
                         "(6 mixins + dates + state)")

    def test_facade_is_a_zero_logic_surface(self):
        text = _read("db/sync_engine.py")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), FACADE_LINE_BUDGET,
                             f"db/sync_engine.py grew past {FACADE_LINE_BUDGET} lines -- "
                             "logic belongs in db/sync/, not in the facade")
        tree = ast.parse(text)
        self.assertFalse(any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                             for n in ast.walk(tree)),
                         "the facade must carry ZERO function definitions")

    def test_facade_assembles_the_six_mixins(self):
        tree = ast.parse(_read("db/sync_engine.py"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        self.assertEqual(1, len(classes))
        self.assertEqual("SyncEngine", classes[0].name)
        bases = [b.id for b in classes[0].bases if isinstance(b, ast.Name)]
        self.assertEqual(list(MIXIN_CLASSES), bases)

    def test_each_domain_module_defines_exactly_one_mixin(self):
        for mod, mixin in zip(DOMAIN_MODULES, MIXIN_CLASSES):
            tree = ast.parse(_read(f"db/sync/{mod}.py"))
            classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
            self.assertEqual([mixin], [c.name for c in classes],
                             f"db/sync/{mod}.py must define exactly {mixin}")


class TestPublicSurface(unittest.TestCase):
    """The 35 importer files must not need a single edit."""

    def test_historical_surface_imports_from_the_facade(self):
        import db.sync_engine as facade
        for name in ("SyncEngine", "_SYNC_LOCK", "RENEWAL_DEDUPE_WINDOW_SEC",
                     *DATE_HELPERS):
            self.assertTrue(hasattr(facade, name), f"db.sync_engine.{name} must stay importable")

    def test_all_historical_methods_on_sync_engine(self):
        from db.sync_engine import SyncEngine
        for m in METHODS:
            self.assertTrue(hasattr(SyncEngine, m), f"SyncEngine.{m} disappeared in the split")

    def test_reexports_are_the_same_function_objects(self):
        import db.sync_engine as facade
        from db.sync import dates
        for name in DATE_HELPERS:
            self.assertIs(getattr(facade, name), getattr(dates, name),
                          f"{name} must be ONE function object, re-exported (no copy)")

    def test_getters_work_through_the_assembled_class(self):
        from db.sync_engine import SyncEngine
        base = SyncEngine.get_employee_dir("EMP01")
        self.assertEqual(base / "credentials.csv", SyncEngine.get_employee_credentials_path("EMP01"))
        self.assertEqual(base / "clubs.csv", SyncEngine.get_employee_clubs_path("EMP01"))
        self.assertEqual(base / "activity_log.csv", SyncEngine.get_employee_activities_path("EMP01"))
        self.assertEqual(base / "issues.csv", SyncEngine.get_employee_issues_path("EMP01"))


class TestSingleSourceLocks(unittest.TestCase):
    """One definition per rule -- the drift disease dies here."""

    def test_exactly_one_engine_lock(self):
        hits = [rel for rel, text in _sync_surface().items() if "threading.RLock()" in text]
        self.assertEqual(["db/sync/state.py"], hits,
                         "the engine lock may be created in exactly one place")

    def test_exactly_one_dedupe_window_constant(self):
        pat = re.compile(r"^RENEWAL_DEDUPE_WINDOW_SEC\s*=", re.M)
        hits = [rel for rel, text in _sync_surface().items() if pat.search(text)]
        self.assertEqual(["db/sync/state.py"], hits,
                         "the renewal dedupe window must have ONE home")

    def test_no_definition_lives_twice(self):
        texts = _sync_surface()
        for name in (*METHODS, *DATE_HELPERS):
            pat = re.compile(rf"^(\s*)def {re.escape(name)}\(", re.M)
            hits = [rel for rel, text in texts.items() if pat.search(text)]
            self.assertEqual(1, len(hits), f"`def {name}` must exist exactly once, found in {hits}")

    def test_no_code_references_the_class_object(self):
        # The old static getters called `SyncEngine.get_employee_dir(...)`; after
        # the split they are classmethods (`cls.`).  No module may reach back for
        # the assembled class object -- that was the circular-import trap.
        for rel, text in _sync_surface().items():
            if rel == "db/sync_engine.py":
                continue
            tree = ast.parse(text)
            refs = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                    and n.id == "SyncEngine"]
            self.assertFalse(refs, f"{rel} references the SyncEngine class object in code")


class TestBehaviourAnchors(unittest.TestCase):
    """Spot equivalence anchors (the full gate is the real proof)."""

    def test_bucket_activity_delegates_to_the_single_source(self):
        from db.sync_engine import SyncEngine
        from db import counting_rules
        for row in ({"support_type": "Registration"}, {"support_type": "Data Migration"},
                    {"support_type": "Online Session"}, {}):
            self.assertEqual(counting_rules.bucket_activity(row), SyncEngine.bucket_activity(row))

    def test_date_helpers_still_parse(self):
        from db.sync_engine import parse_iso_or_date, calculate_next_renewal_date
        self.assertEqual(date(2026, 9, 19), parse_iso_or_date("2026-09-19"))
        self.assertEqual(date(2026, 9, 19), parse_iso_or_date("19-09-2026"))
        self.assertIsNone(parse_iso_or_date("-"))
        self.assertRegex(calculate_next_renewal_date(date_of_approval="2026-09-19"),
                         r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
