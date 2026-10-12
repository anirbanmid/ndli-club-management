"""
tests/test_r43_report_trim.py

R43 "report trim" pins (user request 2026-10-12): the one-click report must NOT
carry the "Renewal attention — highest-risk clubs" club-listing table — at scale
it dumps the whole attention list into the report (the caption even scaled with
the row count) and bloats the document. The summary FIGURES stay (no figure
moves): the Renewal Health metric cards incl. "Renewal Attention (scan)" and the
honest source note remain.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest
from pathlib import Path


def read(rel):
    return Path(rel).read_text(encoding="utf-8")


class TestAttentionTableGone(unittest.TestCase):
    def setUp(self):
        self.js = read("static/js/report_generator.js")

    def test_club_listing_table_removed(self):
        # The listing table and its machinery must not come back.
        self.assertNotIn("highest-risk clubs", self.js,
                         "the attention club-listing table returned to the report")
        self.assertNotIn("attentionClubs", self.js)
        self.assertNotIn("attnTable", self.js)

    def test_no_club_id_listing_table_in_section3(self):
        # After the 3d heading, up to the section end, no table may be built
        # (the Renewal Health block is cards + source note only).
        tail = self.js.split("3d. Renewal Health", 1)[1].split("</section>", 1)[0]
        self.assertNotIn("tableHtml(", tail)
        self.assertNotIn("Club ID", tail)


class TestRenewalHealthSummaryKept(unittest.TestCase):
    def setUp(self):
        self.js = read("static/js/report_generator.js")

    def test_summary_cards_still_render(self):
        # Figures do not move: the Renewal Health card grid stays as-is.
        self.assertIn('metricCard("Renewal Attention (scan)"', self.js)
        self.assertIn('metricCard("Overdue"', self.js)
        self.assertIn('metricCard("Expiring Soon (90 days)"', self.js)

    def test_source_honesty_note_kept(self):
        # The scan-vs-master merge disclaimer survives (wording follows the
        # counts now that the club list is gone).
        self.assertIn("attention-scan counts are produced by the AI renewal-attention scan", self.js)
        self.assertIn("without reconciliation maths", self.js)


if __name__ == "__main__":
    unittest.main()
