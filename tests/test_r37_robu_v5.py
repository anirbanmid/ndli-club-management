"""
R37/R37v2 v5.0 — Robu counting-honesty locks (the "X live + Y migrated" rule).

User report 1 (2026-10-11): Robu answered "There are 29 clubs across 11 states…"
with no live/migrated split, while every dashboard view shows "X live + Y
migrated" since R29.

User report 2 (2026-10-11, R37v2): Robu then answered "29 clubs (23 live + 6
migrated)" — counting club REGISTER ROWS. The dashboard counts differently and
is the source of truth: "23 live + 2289 migrated club approvals (history)",
i.e. the migrated half is the migrated history BASELINE (worksheet approvals),
never the imported record rows. These tests lock the dashboard rule:

1. `_split_origin` provenance rule — the REGISTER's record-level split.
2. clubs.list returns BOTH views: the headline (live + migrated approvals)
   and the record-level register split, and they never mix.
3. The spoken answer carries the dashboard headline + the counting rule.
4. metrics.get carries the same split wording.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
from unittest import mock

import ai.assistant_tools as assistant_tools
from ai.assistant_core import _compose_clubs_list, _compose_metrics
from ai.assistant_tools import ToolContext, _split_origin, call_tool

_FIXTURE_CLUBS = [
    {"club_id": "C1", "state": "WB", "zone": "East", "record_origin": "created"},
    {"club_id": "C2", "state": "KL", "zone": "South", "record_origin": "created"},
    {"club_id": "C3", "state": "MH", "zone": "West", "record_origin": "imported"},
]

_FIXTURE_MIGRATED = {"approvals": 100, "support": 40, "online_workshops": 7,
                     "employees_migrated": 3, "first_year": "2019", "last_year": "2025"}


def _admin_ctx():
    return ToolContext(user_id="ADMIN01", role="ADMIN")


def _patch_world(clubs=None, migrated=None):
    """Fixture world: register rows + migrated history baseline."""
    return mock.patch.multiple(
        assistant_tools,
        _read_master_clubs=mock.Mock(return_value=list(clubs or _FIXTURE_CLUBS)),
        _migrated_totals=mock.Mock(return_value=dict(migrated or _FIXTURE_MIGRATED)),
    )


class TestSplitOriginRule(unittest.TestCase):
    def test_provenance_rule(self):
        live, migrated = _split_origin(_FIXTURE_CLUBS)
        self.assertEqual((live, migrated), (2, 1))

    def test_imported_is_case_and_space_insensitive(self):
        rows = [
            {"club_id": "A", "record_origin": "IMPORTED"},
            {"club_id": "B", "record_origin": " imported "},
            {"club_id": "C", "record_origin": ""},
            {"club_id": "D"},  # missing field entirely -> live
        ]
        self.assertEqual(_split_origin(rows), (2, 2))

    def test_split_always_adds_up(self):
        for rows in ([], _FIXTURE_CLUBS, [{"club_id": "X"}] * 7):
            live, migrated = _split_origin(rows)
            self.assertEqual(live + migrated, len(rows))


class TestClubsListSplit(unittest.TestCase):
    def test_tool_returns_dashboard_and_register_views(self):
        with _patch_world():
            res = call_tool("clubs.list", _admin_ctx())
        # dashboard headline rule: live rows + migrated APPROVALS baseline
        self.assertEqual(res["live_clubs"], 2)
        self.assertEqual(res["migrated_approvals"], 100)
        self.assertEqual(res["programme_total"], 102)
        # record-level register view (never mixed into the headline)
        self.assertEqual(res["register_rows"], 3)
        self.assertEqual(res["register_migrated_rows"], 1)

    def test_answer_shows_live_plus_migrated_and_rule(self):
        with _patch_world():
            res = call_tool("clubs.list", _admin_ctx())
        answer = _compose_clubs_list(res)
        self.assertIn("2 live + 100 migrated club approvals (history)", answer)
        self.assertIn("102 in total", answer)
        self.assertIn("Counting rule", answer)
        self.assertIn("never counted as new work", answer)
        # the register rows must not leak into the headline numbers
        self.assertNotIn("3 clubs (2 live + 1 migrated)", answer)


class TestMetricsSplit(unittest.TestCase):
    def test_metrics_answer_shows_split_and_adds_up(self):
        with _patch_world():
            res = call_tool("metrics.get", _admin_ctx())
        self.assertEqual(res["programme_total"],
                         res["live_clubs"] + res["migrated_approvals"])
        answer = _compose_metrics(res)
        self.assertIn("(2 live + 100 migrated club approvals (history))", answer)

    def test_metrics_employee_still_denied(self):
        from ai.assistant_tools import ToolAuthError
        with self.assertRaises(ToolAuthError):
            call_tool("metrics.get", ToolContext(user_id="EMP01", role="EMPLOYEE"))


class TestV5CountRuleRouting(unittest.TestCase):
    def test_count_rule_intent(self):
        from ai.assistant_core import _route
        for q in ("How are clubs counted?",
                  "what is the counting rule for live and migrated clubs?",
                  "why does the count include migrated clubs?"):
            self.assertEqual(_route(q)[0], "count_rule", q)

    def test_existing_routing_pins_unchanged(self):
        from ai.assistant_core import _route
        self.assertEqual(_route("What is a renewal certificate?")[0], "app_help")
        self.assertEqual(_route("How does synchronization work?")[0], "app_help")
        self.assertEqual(_route("what is my quota")[0], "quota")
        self.assertEqual(_route("how do I approve a renewal?")[0], "help")
        self.assertEqual(_route("how many clubs")[0], "clubs_list")

    def test_count_rule_composer(self):
        from ai.assistant_core import _compose_count_rule
        ans = _compose_count_rule({"live_clubs": 21, "migrated_approvals": 8,
                                   "programme_total": 29})
        self.assertIn("21 live + 8 migrated club approvals (history)", ans)
        self.assertIn("Bulk Club History", ans)
        self.assertIn("never counted as new work", ans)


class TestV5TaskGuides(unittest.TestCase):
    def test_new_guides_present_and_accurate(self):
        from ai.assistant_tools import TASK_GUIDES
        for gid in ("bulk_new_clubs", "bulk_history_upload", "hard_reset", "training_materials"):
            self.assertIn(gid, TASK_GUIDES)
        # The stale pre-R31 door description must be gone.
        self.assertNotIn("bulk_import_csv", TASK_GUIDES)
        self.assertIn("HARD-RESET-FOR-HANDOVER", " ".join(TASK_GUIDES["hard_reset"]["steps"]))
        hist = " ".join(TASK_GUIDES["bulk_history_upload"]["steps"])
        self.assertIn("history", hist.lower())
        self.assertIn("Master Admin", hist)
        new = " ".join(TASK_GUIDES["bulk_new_clubs"]["steps"])
        self.assertIn("today or later", new)
        self.assertIn("REFUSED", new)
        trn = " ".join(TASK_GUIDES["training_materials"]["steps"])
        self.assertIn("15 MB", trn)

    def test_task_matchers_route_to_new_guides(self):
        from ai.assistant_core import _help_task
        self.assertEqual(_help_task("how do I upload club history in bulk?"), "bulk_history_upload")
        self.assertEqual(_help_task("how do I bulk add new clubs from a CSV?"), "bulk_new_clubs")
        self.assertEqual(_help_task("how do I run the hard reset for handover?"), "hard_reset")
        self.assertEqual(_help_task("how do I upload training materials?"), "training_materials")

    def test_task_matchers_regressions(self):
        from ai.assistant_core import _help_task
        self.assertEqual(_help_task("how do I import an existing club?"), "import_existing_club")
        self.assertEqual(_help_task("how do I correct wrong historical dates?"), "correct_historical_dates")
        self.assertEqual(_help_task("how do I approve a renewal?"), "approve_renewal")


if __name__ == "__main__":
    unittest.main()
