"""Lock tests for the Comprehensive Report feature (PDF + DOC).

Added with the report feature (2026-10-07). Locks:
  * the two admin buttons + wiring
  * the fairness framework copy ("Advisory — Field-Difficulty Context") and the
    exact 10-state HIGH-DIFFICULTY FIELD tier map (J&K, Ladakh + 8 NE states)
  * the no-maths-change rule: official engine numbers are rendered verbatim —
    no multipliers/adjustments may be applied to official scores
  * the synchronous print route (user-activation lesson from the cert fix)
  * the DOC export via application/msword blob

Static grep-based guards, mirroring tests/test_r2_ui_fixes.py style.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


class TestReportWiring(unittest.TestCase):
    def setUp(self):
        self.admin = read("templates/admin.html")
        self.js = read("static/js/report_generator.js")

    def test_buttons_present_and_labeled(self):
        self.assertIn('id="btn-generate-report-pdf"', self.admin)
        self.assertIn('id="btn-generate-report-doc"', self.admin)
        self.assertIn("Generate Comprehensive Report (PDF)", self.admin)
        self.assertIn("Generate Comprehensive Report (DOC)", self.admin)

    def test_script_wired(self):
        self.assertIn('<script src="/static/js/report_generator.js"></script>', self.admin)
        self.assertIn("generateComprehensiveReportPdf", self.admin)
        self.assertIn("generateComprehensiveReportDoc", self.admin)

    def test_entry_functions_defined(self):
        self.assertIn("function generateComprehensiveReportPdf", self.js)
        self.assertIn("function generateComprehensiveReportDoc", self.js)


class TestFairnessFrame(unittest.TestCase):
    def setUp(self):
        self.js = read("static/js/report_generator.js")

    def test_advisory_label_copy(self):
        self.assertIn("Advisory \u2014 Field-Difficulty Context", self.js)

    def test_high_difficulty_tier_map_exact(self):
        # The 10 client-anchored HIGH-DIFFICULTY FIELD states, nothing else.
        for st in ["Jammu", "Ladakh", "Arunachal", "Assam", "Manipur", "Meghalaya",
                   "Mizoram", "Nagaland", "Sikkim", "Tripura"]:
            self.assertIn(st, self.js)
        m = re.search(r"HIGH[_-]DIFFICULTY[^=]*=\s*\[([^\]]+)\]", self.js)
        self.assertIsNotNone(m, "HIGH-DIFFICULTY tier map literal not found")
        body = m.group(1)
        for st in ["Jammu", "Ladakh", "Arunachal", "Assam", "Manipur", "Meghalaya",
                   "Mizoram", "Nagaland", "Sikkim", "Tripura"]:
            self.assertIn(st, body)
        # nothing beyond the 10 (+ J&K spelled with ampersand counts as one entry)
        entries = [e for e in re.split(r",\s*", body) if e.strip()]
        self.assertEqual(len(entries), 10, "tier map must contain exactly 10 states: %r" % entries)

    def test_no_decimal_multipliers_on_official_scores(self):
        # Advisory layer only: no `official * factor` style maths on scores/stars.
        self.assertIsNone(re.search(r"weighted_score\s*[\*/]\s*\d",
                                    self.js), "official score multiplied")
        self.assertIsNone(re.search(r"stars\s*[\*/]\s*\d", self.js), "official stars adjusted")
        self.assertIsNone(re.search(r"adjustScore\s*\(|rescale\s*\(", self.js),
                          "score adjustment helper introduced")
        # note: the word 'multiplier' appears only in honest copy ("NO decimal multipliers")
        self.assertLessEqual(self.js.lower().count("multiplier"), 3,
                             "multiplier mentions exploded — check for real rescaling")

    def test_dual_pacing_present(self):
        self.assertTrue(re.search(r"dual|pacing", self.js, re.I), "dual pacing targets missing")


class TestExportRoutes(unittest.TestCase):
    def setUp(self):
        self.js = read("static/js/report_generator.js")

    def test_print_called_synchronously_in_click_path(self):
        # User-activation rule (cert print fix #16): window.print() must be reached
        # from the click handler before any await in that handler.
        fn = re.search(r"function generateComprehensiveReportPdf\b.*?\n\}", self.js, re.S)
        self.assertIsNotNone(fn)
        head = fn.group(0).split("await")[0]
        self.assertIn("print", head.lower(),
                      "print must be reachable synchronously from the PDF click handler")

    def test_afterprint_cleanup(self):
        self.assertIn("afterprint", self.js)

    def test_doc_export_blob(self):
        self.assertIn("application/msword", self.js)

    def test_report_view_ids(self):
        self.js_ids = re.findall(r'id="(report-[a-z-]+)"', self.js) + \
            re.findall(r'id="(report-[a-z-]+)"', read("templates/admin.html"))
        self.assertIn("report-view-root", self.js_ids)


if __name__ == "__main__":
    unittest.main()
