"""
tests/test_r42_attention_pagination.py

R42 "renewal attention pagination" pins (PLAN_RENEWAL_ATTENTION_PAGINATION.md):

1. PAGED CORRECTNESS: slicing, totals math, out-of-range page -> empty list
   (never an error), page_size cap (<= 200) enforced, default page_size 50,
   unknown filter falls back to ALL.
2. ORDER CONTRACT: paged concatenation across pages == the un-paginated compat
   `clubs` order (Overdue by days_diff asc, then Expiring Soon by days_diff asc).
3. FILTER/SEARCH PARITY: server-side filter/q == the pre-R42 client-side
   filtering logic (mirrored in this test) - same rows AND same enrichment
   dicts as the compat path.
4. BOUNDED PAYLOAD (the wall lock): at 5,000 attention rows a page_size=50
   response stays bounded and INDEPENDENT of dataset size (O(page), not
   O(rows)) while the compat one-shot response is MBs. Calibration note: the
   plan's 25KB estimate assumed ~500B rows; measured enriched rows are ~786B
   (3 emails + institution name), so the per-page bound is pinned at 64KB -
   the dataset-independence pin below is the real lock against reintroducing
   full-list mode.
5. SHAPES: the compat response keeps every existing key incl. the duplicate
   arrays; the paged response carries the exact contract keys and NO
   overdue_clubs / expiring_soon_clubs duplicates.
6. NO JS RE-DERIVATION: admin_attention.js never slices/filters a full clubs
   array (the wall cannot come back client-side) and renderRenewalAttentionList
   never fetches (pure renderer of the last response - R41 Node harness keeps
   working).
7. ROUTE WIRING: zero params keeps the compat shape byte-for-shape; any
   attention param (page / page_size / filter / q) switches to the paged mode.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import json
import os
import threading
import unittest
import urllib.request
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer
from pathlib import Path

from ai.decision_module import AIDecisionEngine

TODAY = datetime.now(timezone.utc).date()

COMPAT_KEYS = {"today", "total_attention_count", "overdue_count",
               "expiring_soon_count", "clubs", "overdue_clubs", "expiring_soon_clubs"}
PAGED_KEYS = {"total_attention_count", "overdue_count", "expiring_soon_count",
              "page", "page_size", "total_pages", "total_matches", "clubs"}
ROW_ENRICH_KEYS = {"attention_type", "days_diff", "days_overdue", "days_left",
                   "badge_label", "badge_class", "effective_renewal_date",
                   "next_renewal_due_date"}


def _club(i, days, **over):
    """Synthetic club whose renewal lands `days` from today (neg = overdue)."""
    ren = (TODAY + timedelta(days=days)).isoformat()
    c = {
        "club_id": f"NDLI-R42-{i:05d}",
        "reg_no": f"REG-R42-{i:05d}",
        "institution_name": f"R42 Test Institute {i:05d}",
        "state": "Delhi" if i % 2 else "Maharashtra",
        "zone": "North" if i % 2 else "West",
        "patron_email": f"patron{i:05d}@r42.edu",
        "president_email": f"pres{i:05d}@r42.edu",
        "secretary_email": f"sec{i:05d}@r42.edu",
        "date_of_approval": "2024-01-01T10:00:00Z",
        "last_renewal_date": "2025-01-01",
        "renewal_date": ren,
        "status": "Approved",
        "approved_by_emp_id": "EMP01",
        "updated_at": "2026-10-12T10:00:00Z",
        "submission_timestamp": "2024-01-01T10:00:00Z",
        "next_renewal_date": ren,
        "record_origin": "created",
    }
    c.update(over)
    return c


def _mixed_dataset(n):
    """n attention clubs, overdue/expiring interleaved so scan order != sorted."""
    return [_club(i, -(1 + i % 300) if i % 2 == 0 else (i % 91)) for i in range(n)]


def _old_client_filter(clubs, filter_type, query):
    """Mirror of the PRE-R42 client-side JS filtering (admin_attention.js
    before R42): type filter then case-insensitive substring search over
    club_id / institution_name / state / zone / reg_no / patron_email."""
    lst = list(clubs)
    ft = (filter_type or "ALL").strip().lower()
    if ft == "overdue":
        lst = [c for c in lst if c.get("attention_type") == "Overdue"]
    elif "expiring" in ft:
        lst = [c for c in lst if c.get("attention_type") == "Expiring Soon"]
    q = (query or "").strip().lower()
    if q:
        lst = [c for c in lst if any(
            q in str(c.get(f, "") or "").lower()
            for f in ("club_id", "institution_name", "state", "zone", "reg_no", "patron_email"))]
    return lst


class TestPagedCorrectness(unittest.TestCase):
    def test_slicing_totals_cap_default_and_unknown_filter(self):
        clubs = _mixed_dataset(120)
        page1 = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=50, clubs=clubs)
        self.assertEqual(len(page1["clubs"]), 50)
        self.assertEqual(page1["page"], 1)
        self.assertEqual(page1["page_size"], 50)
        self.assertEqual(page1["total_matches"], 120)
        self.assertEqual(page1["total_pages"], 3)
        self.assertEqual(page1["total_attention_count"], 120)
        self.assertEqual(page1["overdue_count"] + page1["expiring_soon_count"], 120)

        page3 = AIDecisionEngine.get_renewal_attention_page(page=3, page_size=50, clubs=clubs)
        self.assertEqual(len(page3["clubs"]), 20)

        # Out-of-range page: empty list, NEVER an error; totals stay intact.
        page99 = AIDecisionEngine.get_renewal_attention_page(page=99, page_size=50, clubs=clubs)
        self.assertEqual(page99["clubs"], [])
        self.assertEqual(page99["total_matches"], 120)
        self.assertEqual(page99["total_pages"], 3)

        # page_size default is 50; cap is 200 (never above, never zero/neg).
        default_page = AIDecisionEngine.get_renewal_attention_page(page=1, clubs=clubs)
        self.assertEqual(default_page["page_size"], 50)
        self.assertEqual(len(default_page["clubs"]), 50)
        capped = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=9999, clubs=clubs)
        self.assertEqual(capped["page_size"], 200)
        self.assertEqual(len(capped["clubs"]), 120)  # 120 rows fit one 200-cap page
        self.assertEqual(capped["total_pages"], 1)
        zero = AIDecisionEngine.get_renewal_attention_page(page=0, page_size=0, clubs=clubs)
        self.assertEqual(zero["page"], 1)
        self.assertEqual(zero["page_size"], 1)

        # Unknown filter falls back to ALL (same rows as filter=ALL).
        all_rows = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=200, filter="ALL", clubs=clubs)
        bogus = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=200, filter="bogus-filter", clubs=clubs)
        self.assertEqual([c["club_id"] for c in bogus["clubs"]],
                         [c["club_id"] for c in all_rows["clubs"]])

        # Non-numeric page/page_size never explode.
        coerced = AIDecisionEngine.get_renewal_attention_page(page="abc", page_size="xyz", clubs=clubs)
        self.assertEqual(coerced["page"], 1)
        self.assertEqual(coerced["page_size"], 50)


class TestOrderContract(unittest.TestCase):
    def test_paged_concat_equals_compat_order(self):
        clubs = _mixed_dataset(60)
        compat = AIDecisionEngine.get_renewal_attention_data(clubs=list(clubs))
        ground_truth = [c["club_id"] for c in compat["clubs"]]

        paged_ids = []
        page = 1
        while True:
            resp = AIDecisionEngine.get_renewal_attention_page(page=page, page_size=7, clubs=clubs)
            if not resp["clubs"]:
                break
            paged_ids.extend(c["club_id"] for c in resp["clubs"])
            if page >= resp["total_pages"]:
                break
            page += 1

        self.assertEqual(paged_ids, ground_truth,
                         "paged concatenation must equal the compat clubs order exactly")

        # And the order really is: Overdue by days_diff asc, then Expiring Soon.
        rows = compat["clubs"]
        types = [c["attention_type"] for c in rows]
        self.assertEqual(types, sorted(types, key=lambda t: 0 if t == "Overdue" else 1))
        for group in ("Overdue", "Expiring Soon"):
            diffs = [c["days_diff"] for c in rows if c["attention_type"] == group]
            self.assertEqual(diffs, sorted(diffs), f"{group} must be sorted by days_diff asc")


class TestFilterSearchParity(unittest.TestCase):
    def test_server_side_matches_old_client_logic(self):
        clubs = _mixed_dataset(120)
        compat = AIDecisionEngine.get_renewal_attention_data(clubs=list(clubs))
        compat_rows = compat["clubs"]

        cases = [
            ("ALL", ""),
            ("Overdue", ""),
            ("Expiring Soon", ""),
            ("overdue", ""),
            ("ALL", "r42 test institute 00002"),
            ("ALL", "MAHARASHTRA"),
            ("Overdue", "00004"),
            ("Expiring Soon", "delhi"),
            ("ALL", "patron00006"),
            ("ALL", "reg-r42-00008"),
            ("ALL", "zzz-no-such-club"),
        ]
        for filter_type, q in cases:
            with self.subTest(filter=filter_type, q=q):
                expected = _old_client_filter(compat_rows, filter_type, q)
                resp = AIDecisionEngine.get_renewal_attention_page(
                    page=1, page_size=200, filter=filter_type, q=q, clubs=clubs)
                got = resp["clubs"]
                self.assertEqual([c["club_id"] for c in got],
                                 [c["club_id"] for c in expected])
                self.assertEqual(resp["total_matches"], len(expected))
                # Row dicts must be IDENTICAL to the compat enrichment (no drift).
                self.assertEqual(got, expected)

    def test_counts_stay_unfiltered_summary(self):
        clubs = _mixed_dataset(120)
        compat = AIDecisionEngine.get_renewal_attention_data(clubs=list(clubs))
        resp = AIDecisionEngine.get_renewal_attention_page(
            page=1, page_size=50, filter="Overdue", q="00001", clubs=clubs)
        self.assertEqual(resp["total_attention_count"], compat["total_attention_count"])
        self.assertEqual(resp["overdue_count"], compat["overdue_count"])
        self.assertEqual(resp["expiring_soon_count"], compat["expiring_soon_count"])


class TestBoundedPayloadWallLock(unittest.TestCase):
    def test_page_payload_is_bounded_and_dataset_independent(self):
        big = _mixed_dataset(5000)

        page_big = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=50, clubs=big)
        payload = json.dumps({"success": True, **page_big}).encode("utf-8")
        # Calibration: ~786B/enriched row x 50 rows ~= 39-48KB measured; the
        # plan's 25KB estimate assumed shorter rows. 64KB is the honest bound.
        self.assertLess(len(payload), 64 * 1024,
                        "a 50-row page must stay bounded (full-list mode is back!)")

        # The real wall lock: page payload does NOT grow with dataset size.
        small = _mixed_dataset(100)
        page_small = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=50, clubs=small)
        payload_small = json.dumps({"success": True, **page_small}).encode("utf-8")
        self.assertLess(len(payload), len(payload_small) * 1.1,
                        "page payload must be O(page_size), not O(rows)")
        self.assertGreater(len(payload), len(payload_small) * 0.9,
                           "page payload must be O(page_size), not O(rows)")

        # The wall being avoided: today's one-shot response at this scale is MBs.
        compat = AIDecisionEngine.get_renewal_attention_data(clubs=list(big))
        compat_payload = json.dumps({"success": True, **compat}).encode("utf-8")
        self.assertGreater(len(compat_payload), 1024 * 1024)
        self.assertGreater(len(compat_payload), 20 * len(payload))


class TestResponseShapes(unittest.TestCase):
    def test_compat_shape_unchanged_paged_shape_pinned(self):
        clubs = _mixed_dataset(30)

        compat = AIDecisionEngine.get_renewal_attention_data(clubs=list(clubs))
        self.assertEqual(set(compat.keys()), COMPAT_KEYS)
        self.assertEqual(len(compat["clubs"]),
                         len(compat["overdue_clubs"]) + len(compat["expiring_soon_clubs"]))
        for row in compat["clubs"]:
            self.assertTrue(ROW_ENRICH_KEYS <= set(row.keys()))

        paged = AIDecisionEngine.get_renewal_attention_page(page=1, page_size=10, clubs=clubs)
        self.assertEqual(set(paged.keys()), PAGED_KEYS,
                         "paged mode ships NO overdue_clubs/expiring_soon_clubs duplicates")
        for row in paged["clubs"]:
            self.assertTrue(ROW_ENRICH_KEYS <= set(row.keys()))
        # Paged row dicts are the same objects the compat path builds.
        self.assertEqual(paged["clubs"], compat["clubs"][:10])


class TestNoJsReDerivation(unittest.TestCase):
    def test_admin_attention_js_never_slices_or_filters_full_list(self):
        src = Path("static/js/admin_attention.js").read_text(encoding="utf-8")
        self.assertNotIn(".filter(", src,
                         "filtering runs server-side; JS must not re-filter the list")
        self.assertNotIn(".slice(", src,
                         "pagination runs server-side; JS must not re-slice the list")
        self.assertIn('"/api/admin/renewal-attention?"', src,
                      "the modal fetches ONE page at a time from the paged API")

    def test_renderer_is_pure_no_fetch_inside(self):
        src = Path("static/js/admin_attention.js").read_text(encoding="utf-8")
        head, rend = src.split("function renderRenewalAttentionList", 1)
        rend = rend.split("function ", 1)[0]
        self.assertNotIn("apiRequest", rend, "renderRenewalAttentionList must not fetch")
        self.assertNotIn("await", rend, "renderRenewalAttentionList must be a pure renderer")
        self.assertIn("function fetchAttentionPage", head,
                      "fetching lives in fetchAttentionPage only")


class TestRouteWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from init_db import initialize_database
        initialize_database()
        from app import NDLIRequestHandler
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        req = urllib.request.Request(self.base_url + path)
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_zero_params_stays_compat_shape(self):
        status, data = self._get("/api/admin/renewal-attention")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(set(data.keys()), COMPAT_KEYS | {"success"})
        self.assertIn("overdue_clubs", data)
        self.assertIn("expiring_soon_clubs", data)
        self.assertNotIn("page", data)

    def test_params_switch_to_paged_mode(self):
        status, data = self._get("/api/admin/renewal-attention?page=1&page_size=50")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(set(data.keys()), PAGED_KEYS | {"success"})
        self.assertNotIn("overdue_clubs", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 50)
        self.assertEqual(len(data["clubs"]), min(50, data["total_matches"]))

        # filter/q alone also switch to paged mode.
        status2, data2 = self._get("/api/admin/renewal-attention?filter=Overdue&q=")
        self.assertEqual(status2, 200)
        self.assertEqual(set(data2.keys()), PAGED_KEYS | {"success"})

    def test_cap_and_out_of_range_over_http(self):
        status, data = self._get("/api/admin/renewal-attention?page=1&page_size=9999")
        self.assertEqual(status, 200)
        self.assertEqual(data["page_size"], 200)

        status2, data2 = self._get("/api/admin/renewal-attention?page=99999&page_size=50")
        self.assertEqual(status2, 200)
        self.assertEqual(data2["clubs"], [])
        self.assertEqual(data2["total_matches"], data2["total_attention_count"])


if __name__ == "__main__":
    unittest.main()
