"""
R47 - bulk-group deletion semantics (user-reported bug, 2026-10-13).

Symptom (user): logging 3 bulk phone-call activities raised "Other Support"
by 3 (correct), but deleting "that activity" dropped the count by only 1
(26,670 -> 26,669) and left sibling rows ([Bulk Phone/Remote Call 2/3])
behind -- bulk rows were deleted one by one, not as one unit.

Requirement (user, verbatim): "If a entry is in bulk then deletion should be
performed in bulk."

=> a bulk entry is ONE unit: deleting ANY of its rows deletes the WHOLE group
(all sibling rows sharing the bulk base id `ACT-<emp>-<ts_base>-<i>`) in one
action -- node + master, ONE quota recompute -- and the count returns to its
pre-bulk value.  Suffix-less ids (single rows) never form a group and are
NEVER swept along by a cascade.

Pure engine + static source pins.  No server needed.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
from pathlib import Path

from config import MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV
from db.csv_engine import CSVEngine
from db.schemas import ACTIVITY_FIELDS, QUOTA_FIELDS
from db.sync.activities import bulk_group_base
from db.sync_engine import SyncEngine
from init_db import initialize_database

from admin_view import employee_js_view

ROOT = Path(__file__).resolve().parent.parent
EMP = "EMP01"
BULK_TYPE = "Phone call and remote assistance"


def _support_count(emp_id):
    for q in CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS):
        if q.get("emp_id") == emp_id:
            return int(q.get("support_logs_count", "0") or "0")
    return 0


def _group_rows(emp_id, base):
    """(node_rows, master_rows) whose activity_id belongs to this bulk group."""
    node = CSVEngine.read_all(SyncEngine.get_employee_activities_path(emp_id), ACTIVITY_FIELDS)
    master = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
    node_hits = [a for a in node if bulk_group_base(a.get("activity_id", ""), emp_id) == base]
    master_hits = [a for a in master if bulk_group_base(a.get("activity_id", ""), emp_id) == base]
    return node_hits, master_hits


class TestBulkGroupBaseShape(unittest.TestCase):
    """The group key: `<base>-<i>` groups, everything else does not."""

    def test_bulk_member_ids_group_under_their_base(self):
        self.assertEqual(bulk_group_base("ACT-EMP01-1728800000000-1", "EMP01"),
                         "ACT-EMP01-1728800000000")
        self.assertEqual(bulk_group_base("ACT-EMP01-1728800000000-12", "EMP01"),
                         "ACT-EMP01-1728800000000")
        # case-tolerant on both sides (ids are built from the caller's emp_id)
        self.assertEqual(bulk_group_base("ACT-emp01-1728800000000-3", "emp01"),
                         "ACT-EMP01-1728800000000")

    def test_suffixless_single_ids_never_form_a_group(self):
        # THE trap: a suffix-less single row must never be swept by a cascade.
        self.assertEqual(bulk_group_base("ACT-EMP01-1728800000000", "EMP01"), "")

    def test_priority_and_cross_employee_ids_never_group(self):
        self.assertEqual(bulk_group_base("ACT-PRIORITY-EMP01-1728800000000", "EMP01"), "")
        self.assertEqual(bulk_group_base("ACT-EMP02-1728800000000-1", "EMP01"), "")


class TestBulkDeleteIsOneUnit(unittest.TestCase):
    """The reported bug: delete one bulk row -> the WHOLE entry goes."""

    @classmethod
    def setUpClass(cls):
        initialize_database()

    def test_delete_via_one_member_removes_the_whole_group_and_restores_quota(self):
        base_count = _support_count(EMP)
        res = SyncEngine.log_support_activity(
            emp_id=EMP, support_type=BULK_TYPE,
            notes="R47 bulk unit probe", count=3)
        ids = res["activities_created"]
        self.assertEqual(len(ids), 3)
        grp = bulk_group_base(ids[0], EMP)
        self.assertEqual(_support_count(EMP), base_count + 3)

        del_res = SyncEngine.delete_activity_log_entries(EMP, [ids[0]])

        # THE bug pin: one click on one bulk row -> count back to PRE-bulk.
        self.assertEqual(_support_count(EMP), base_count)
        self.assertEqual(del_res["deleted_count"], 3)
        self.assertEqual(del_res["not_found"], [])
        node_hits, master_hits = _group_rows(EMP, grp)
        self.assertEqual(node_hits, [], "bulk siblings left in the node log")
        self.assertEqual(master_hits, [], "bulk siblings left in master_activities.csv")

    def test_delete_via_any_member_is_the_same_action(self):
        # The user may click the first, middle or last row of the entry.
        for pick in (2, 1, 0):
            base_count = _support_count(EMP)
            res = SyncEngine.log_support_activity(
                emp_id=EMP, support_type=BULK_TYPE,
                notes="R47 any-member probe", count=3)
            ids = res["activities_created"]
            grp = bulk_group_base(ids[pick], EMP)

            del_res = SyncEngine.delete_activity_log_entries(EMP, [ids[pick]])

            self.assertEqual(del_res["deleted_count"], 3)
            self.assertEqual(_support_count(EMP), base_count)
            node_hits, master_hits = _group_rows(EMP, grp)
            self.assertEqual(node_hits + master_hits, [])

    def test_multi_member_request_deletes_the_group_exactly_once(self):
        base_count = _support_count(EMP)
        res = SyncEngine.log_support_activity(
            emp_id=EMP, support_type=BULK_TYPE,
            notes="R47 multi-select probe", count=3)
        ids = res["activities_created"]

        del_res = SyncEngine.delete_activity_log_entries(EMP, [ids[0], ids[1]])

        # honest count: 3 rows removed -- not 5 (double-counted) and not 2
        self.assertEqual(del_res["deleted_count"], 3)
        self.assertEqual(_support_count(EMP), base_count)

    def test_results_carry_the_bulk_group_marker(self):
        res = SyncEngine.log_support_activity(
            emp_id=EMP, support_type=BULK_TYPE,
            notes="R47 marker probe", count=3)
        ids = res["activities_created"]
        grp = bulk_group_base(ids[0], EMP)

        del_res = SyncEngine.delete_activity_log_entries(EMP, [ids[0]])

        self.assertEqual(del_res["bulk_groups"],
                         [{"base": grp, "deleted_ids": sorted(ids)}])
        marked = [r for r in del_res["results"] if r.get("bulk_group") == grp]
        self.assertEqual(len(marked), 3, "every removed sibling must report its group")

    def test_not_found_stays_honest_alongside_a_cascade(self):
        res = SyncEngine.log_support_activity(
            emp_id=EMP, support_type=BULK_TYPE,
            notes="R47 not_found probe", count=3)
        ids = res["activities_created"]
        ghost = "ACT-EMP01-9999999999999-9"

        del_res = SyncEngine.delete_activity_log_entries(EMP, [ids[0], ghost])

        self.assertEqual(del_res["not_found"], [ghost])
        self.assertEqual(del_res["deleted_count"], 3)


class TestSinglesAndIsolation(unittest.TestCase):
    """What the cascade must NOT touch."""

    @classmethod
    def setUpClass(cls):
        initialize_database()

    def test_single_row_delete_still_removes_exactly_one(self):
        a = SyncEngine.log_support_activity(
            emp_id=EMP, support_type="Closing of OS Ticket", notes="R47 single A")
        b = SyncEngine.log_support_activity(
            emp_id=EMP, support_type="Closing of OS Ticket", notes="R47 single B")
        base_count = _support_count(EMP)

        del_res = SyncEngine.delete_activity_log_entries(EMP, [a["activity_id"]])

        self.assertEqual(del_res["deleted_count"], 1)
        self.assertEqual(del_res["bulk_groups"], [])
        self.assertEqual(_support_count(EMP), base_count - 1)
        node = CSVEngine.read_all(SyncEngine.get_employee_activities_path(EMP), ACTIVITY_FIELDS)
        remaining = {x.get("activity_id") for x in node}
        self.assertNotIn(a["activity_id"], remaining)
        self.assertIn(b["activity_id"], remaining)

    def test_suffixless_single_sharing_a_timestamp_base_is_never_swept(self):
        # Handcrafted edge: a single row ACT-<emp>-<ts> plus bulk members
        # ACT-<emp>-<ts>-1..2 sharing the same timestamp base. The single's
        # id has no -<i> suffix, so it is NOT part of the bulk group.
        ts = "9999999999999"
        base = f"ACT-{EMP}-{ts}"
        single_id = base
        member_ids = [f"{base}-1", f"{base}-2"]
        node_path = SyncEngine.get_employee_activities_path(EMP)

        # pre-clean (idempotence if a previous run died mid-test)
        SyncEngine.delete_activity_log_entries(EMP, member_ids + [single_id])

        for aid in [single_id] + member_ids:
            row = {
                "activity_id": aid, "emp_id": EMP,
                "timestamp": "2026-10-13T00:00:00+00:00",
                "support_type": BULK_TYPE, "priority_flag": "0",
                "club_id": "", "notes": "R47 handcrafted"
            }
            CSVEngine.append_row(node_path, ACTIVITY_FIELDS, row)
            CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, row)

        del_res = SyncEngine.delete_activity_log_entries(EMP, [member_ids[0]])

        self.assertEqual(del_res["deleted_count"], 2)
        self.assertEqual(del_res["bulk_groups"],
                         [{"base": base, "deleted_ids": sorted(member_ids)}])
        node = CSVEngine.read_all(node_path, ACTIVITY_FIELDS)
        ids_left = {x.get("activity_id") for x in node}
        self.assertIn(single_id, ids_left,
                      "suffix-less single row must NEVER be swept by a bulk cascade")
        self.assertNotIn(member_ids[0], ids_left)
        self.assertNotIn(member_ids[1], ids_left)

        # cleanup: the single row goes through a plain single delete
        tail = SyncEngine.delete_activity_log_entries(EMP, [single_id])
        self.assertEqual(tail["deleted_count"], 1)

    def test_another_employees_bulk_group_is_untouched(self):
        e2_count = _support_count("EMP02")
        res2 = SyncEngine.log_support_activity(
            emp_id="EMP02", support_type=BULK_TYPE,
            notes="R47 EMP02 group", count=3)
        ids2 = res2["activities_created"]
        grp2 = bulk_group_base(ids2[0], "EMP02")

        res1 = SyncEngine.log_support_activity(
            emp_id=EMP, support_type=BULK_TYPE,
            notes="R47 EMP01 group", count=2)
        ids1 = res1["activities_created"]

        SyncEngine.delete_activity_log_entries(EMP, [ids1[0]])

        # EMP02's entry survives in full, node + master
        node_hits, master_hits = _group_rows("EMP02", grp2)
        self.assertEqual(len(node_hits), 3)
        self.assertEqual(len(master_hits), 3)

        # cleanup: deleting ONE member removes EMP02's entry as one unit
        tail = SyncEngine.delete_activity_log_entries("EMP02", [ids2[0]])
        self.assertEqual(tail["deleted_count"], 3)
        self.assertEqual(_support_count("EMP02"), e2_count)


class TestUiAndRouteHonesty(unittest.TestCase):
    """The confirmation UI must show the true number, and the route must say
    when a bulk entry went in full (1 request -> N rows was the surprise)."""

    def test_ui_expands_the_group_and_warns_before_confirming(self):
        js = employee_js_view()
        self.assertIn("getActivityBulkGroupIds", js,
                      "the delete modal must expand bulk members to their group")
        self.assertIn("activity-delete-bulk-warning", js,
                      "the delete modal must carry the bulk-entry warning hook")
        self.assertIn("ACTIVITY_DELETE_PENDING_IDS = Array.from(expandedIds)", js,
                      "the request must carry the expanded group, not one id")
        self.assertIn("bulk entry — deleted together", js,
                      "the target list must tag rows that go as one unit")

    def test_template_carries_the_bulk_warning_span(self):
        html = (ROOT / "templates" / "employee.html").read_text(encoding="utf-8")
        self.assertIn('id="activity-delete-bulk-warning"', html,
                      "the delete modal markup must carry the bulk warning span")

    def test_route_message_reports_bulk_groups_honestly(self):
        src = (ROOT / "routes" / "activity.py").read_text(encoding="utf-8")
        self.assertIn("bulk entry deleted in full", src,
                      "the delete route must say when a bulk entry was removed in full")
        self.assertIn('result.get("bulk_groups")', src)


if __name__ == "__main__":
    unittest.main()
