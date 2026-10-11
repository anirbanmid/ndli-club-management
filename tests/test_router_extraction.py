"""
tests/test_router_extraction.py

Anti-regression pins for R39 -- "carve app.py into routers"
(CRITIQUE_AND_ROADMAP.md section 2).

R39 moved every `if path == "/api/..."` block out of app.py into the routes/
package with NO behavior change (proven by .openclaw/tmp/verify_extraction.py:
81/81 handler bodies byte-identical). These tests pin the NEW SHAPE so app.py
cannot quietly grow routes again:

  * app.py stays a request handler + startup module (line budget, no dispatch).
  * routes/ owns the URL map, and every registered route resolves to a callable.
  * the router is used (app.py delegates) and unknown paths still 404.
  * both import orders work (routes->app and app->routes).
  * route modules hold the logic; app.py does not.

Pure structural checks + two subprocess import-order checks. No HTTP server.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_PY = BASE_DIR / "app.py"
ROUTES_DIR = BASE_DIR / "routes"

# Measured 2026-10-12 (R39): app.py is 510 lines. The budget is the tripwire --
# if someone drops a route back into the handler, this fires.
APP_PY_LINE_BUDGET = 560

# Measured 2026-10-12 (R39): 46 GET + 35 POST dispatch blocks.
EXPECTED_GET_ROUTES = 46
EXPECTED_POST_ROUTES = 35


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestRouterShape(unittest.TestCase):
    """The new layout itself is the contract."""

    def test_routes_package_exists(self):
        self.assertTrue((ROUTES_DIR / "__init__.py").is_file())
        modules = sorted(p.name for p in ROUTES_DIR.glob("*.py") if p.name != "__init__.py")
        self.assertGreaterEqual(len(modules), 12,
                                "R39 split app.py into ~16 domain route modules")

    def test_app_py_is_handler_and_startup_only(self):
        lines = _read(APP_PY).split("\n")
        self.assertLessEqual(len(lines), APP_PY_LINE_BUDGET,
                             f"app.py grew back past {APP_PY_LINE_BUDGET} lines -- "
                             "new endpoints belong in routes/, not in the handler")
        # no dispatch chain may come back
        self.assertIsNone(re.search(r'^        (?:el)?if path (==| in |\.startswith)',
                                   _read(APP_PY), re.M),
                          "inline `if path ==` dispatch must stay in routes/__init__.py")

    def test_app_py_delegates_to_the_router(self):
        src = _read(APP_PY)
        self.assertIn("routes.handle_get(self)", src)
        self.assertIn("routes.handle_post(self)", src)
        self.assertIsNotNone(re.search(r"^import routes  # noqa: E402$", src, re.M),
                             "the router import must stay an explicit, commented one")

    def test_route_modules_hold_the_logic(self):
        app_src = _read(APP_PY)
        for fn in ("_send_health_status",):
            self.assertIn(f"def {fn}", app_src, "handler helpers stay in app.py")
        # a route body must never come back to app.py
        self.assertNotIn("def get_", app_src)
        self.assertNotIn("def post_", app_src)


class TestRouteTable(unittest.TestCase):
    """Every registered endpoint resolves; the map is complete and unambiguous."""

    @classmethod
    def setUpClass(cls):
        import routes
        cls.routes = routes

    def test_every_route_resolves(self):
        for table, expected, verb in ((self.routes.GET_ROUTES, EXPECTED_GET_ROUTES, "GET"),
                                      (self.routes.POST_ROUTES, EXPECTED_POST_ROUTES, "POST")):
            self.assertEqual(len(table), expected,
                             f"{verb} route count changed -- update the pin if the API grew")
            for predicates, handler in table:
                self.assertTrue(predicates, "a matcher needs at least one predicate")
                self.assertTrue(callable(handler), f"{verb} handler not callable: {handler}")
                self.assertTrue(handler.__module__.startswith("routes."),
                                f"{verb} handler must live in routes/: {handler.__module__}")
                for op, key in predicates:
                    self.assertIn(op, ("exact", "prefix"))
                    self.assertIsInstance(key, str)

    def test_matchers_are_unique_per_verb(self):
        for table, verb in ((self.routes.GET_ROUTES, "GET"), (self.routes.POST_ROUTES, "POST")):
            seen = [predicates for predicates, _ in table]
            self.assertEqual(len(seen), len(set(seen)),
                             f"duplicate {verb} matcher -- two routes claim the same path")

    def test_match_semantics(self):
        match = self.routes.match
        table = [
            (self.routes.E("/api/health"), "health"),
            (self.routes.E("/employee") + self.routes.P("/employee/"), "employee_portal"),
            (self.routes.P("/api/training/download/"), "training_download"),
        ]
        self.assertEqual(match(table, "/api/health"), "health")
        self.assertEqual(match(table, "/employee"), "employee_portal")
        self.assertEqual(match(table, "/employee/x"), "employee_portal")
        self.assertEqual(match(table, "/api/training/download/1"), "training_download")
        self.assertIsNone(match(table, "/api/nope"))

    def test_dispatch_unknown_path_404s(self):
        """The dispatcher's fallback is the old endpoint-not-found error."""
        calls = []

        class FakeHandler:
            path = "/api/definitely-not-a-route"

            def _parse_json_body(self):
                return {}

            def _send_error(self, message, status=200):
                calls.append((message, status))

        self.routes.handle_get(FakeHandler())
        self.assertEqual(calls, [("Endpoint not found: /api/definitely-not-a-route", 404)])

    def test_dispatch_hits_the_named_handler(self):
        """The table drives dispatch: swapping the /api/health entry swaps the handler."""
        calls = []
        table = self.routes.GET_ROUTES
        idx = next(i for i, (predicates, _) in enumerate(table)
                   if predicates == self.routes.E("/api/health"))
        predicates, original = table[idx]

        class FakeHandler:
            path = "/api/health"

            def _parse_json_body(self):
                return {}

            def _send_error(self, message, status=200):
                calls.append(message)

        try:
            table[idx] = (predicates, lambda h, path, query_params: calls.append("hit"))
            self.routes.handle_get(FakeHandler())
            self.assertEqual(calls, ["hit"])
        finally:
            table[idx] = (predicates, original)


class TestImportOrder(unittest.TestCase):
    """routes/* take their shared names from app (`from app import ...`),
    and app imports the router -- so BOTH import orders must work."""

    def _run(self, order):
        code = (
            "import sys; sys.path.insert(0, 'tests'); import _seed_env\n"
            + "\n".join(f"import {m}" for m in order) + "\n"
            + "import app, routes\n"
            + "assert callable(routes.handle_get) and callable(routes.handle_post)\n"
            + "assert app.NDLIRequestHandler is not None\n"
            + "print('OK')\n"
        )
        res = subprocess.run([sys.executable, "-c", code], cwd=str(BASE_DIR),
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0,
                         f"import order {order} failed:\n{res.stdout}\n{res.stderr}")
        self.assertIn("OK", res.stdout)

    def test_routes_imported_first(self):
        self._run(["routes"])

    def test_app_imported_first(self):
        self._run(["app"])


if __name__ == "__main__":
    unittest.main()
