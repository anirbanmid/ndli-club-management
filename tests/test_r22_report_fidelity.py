"""Lock tests for the R22 report-fidelity round (2026-10-08).

Client defects (PDF export only — DOC export was fine and stays fine):
  (a) tables lost their bottom margin / breathing room in the printed PDF,
  (b) wide matrices (Section 6 star matrix + tier split) were TRUNCATED at the
      right page edge — they rendered at screen min-content width inside an
      A4 print page,
  (c) NEW FEATURE: the report must carry charts/graphs for an easy visual
      summary (donut zone share, monthly trajectory, renewal ring, tier bar).

Fix shape (static lock style, mirroring tests/test_report_gen.py):
  * .rpt-table gets table-layout:fixed + percentage <colgroup> widths so wide
    matrices wrap INSIDE the printable width instead of being clipped,
  * print block: smaller table type, row-level break-inside:avoid (keeps the
    bottom border/margin intact at page breaks) and a real bottom margin,
  * the report view lives inside admin.html, whose global `thead th` rule
    forces white-space:nowrap — the report's th override MUST set
    white-space:normal or the headers blow the fixed layout back up,
  * visual summary = four inline-SVG charts, MSO-conditional so the DOC export
    keeps its table-only layout in Word,
  * every chart is explicitly backed by the verbatim engine tables — the
    no-maths-change rule stands.
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


class TestPrintTableFidelity(unittest.TestCase):
    """Client defects (a) + (b): margins below tables, no right-edge truncation."""

    def setUp(self):
        self.js = read("static/js/report_generator.js")

    def test_table_fixed_layout_and_full_width(self):
        # Fixed layout + width:100% keeps every table inside the printable
        # width; wide matrices wrap instead of being clipped at the page edge.
        self.assertIn(".rpt-table{width:100%;table-layout:fixed;", self.js)

    def test_cell_wrapping_allowed(self):
        # overflow-wrap lets long state lists / words wrap inside fixed columns.
        self.assertIn(".rpt-table th,.rpt-table td{overflow-wrap:break-word;", self.js)

    def test_th_overrides_global_nowrap(self):
        # THE trap: style.css `thead th{white-space:nowrap}` leaks into the
        # report view and forces min-content blowout. The report's th rule must
        # explicitly reset it.
        self.assertIn("white-space:normal;", self.js)
        self.assertIn(".rpt-table th{", self.js)

    def test_print_block_fidelity_rules(self):
        # Print-only: smaller table type, generous bottom margin, rows never
        # split across pages (keeps bottom borders/margins intact).
        self.assertIn(".rpt-table{margin:10px 0 22px;font-size:8.6px;", self.js)
        self.assertIn(".rpt-table tr{page-break-inside:avoid;break-inside:avoid;}", self.js)

    def test_last_row_keeps_its_bottom_border(self):
        # REGRESSION (client smoke, 2026-10-08): style.css carries
        # `tbody tr:last-child td{border-bottom:none}` at specificity 0-1-3,
        # which BEATS `.rpt-table td` (0-1-1) and stripped the closing edge off
        # every report table -> "no breathing room under the last row". The
        # report must re-assert the border with a rule that wins.
        self.assertIn(".rpt-table tbody tr:last-child td{border-bottom:1px solid #cfdcd6;}", self.js)
        self.assertIn(".rpt-table tbody tr:last-child td{padding-bottom:8px;}", self.js)

    def test_colgroup_width_emission(self):
        # tableHtml(headers, rows, caption, colWidths) emits a colgroup when
        # percentage widths are supplied.
        self.assertIn("function tableHtml(headers, rows, caption, colWidths)", self.js)
        self.assertIn("<colgroup>", self.js)
        self.assertIn('<col style="width: ', self.js)

    def test_wide_matrix_col_widths_locked(self):
        # The two client-flagged matrices carry explicit column widths.
        self.assertIn("[5, 15, 19, 9, 9, 9, 9, 9, 16]", self.js)  # 6a star matrix
        self.assertIn("[12, 23, 17, 16, 16, 16]", self.js)  # 6b tier split


class TestVisualSummaryCharts(unittest.TestCase):
    """Client feature (c): charts for an easy visual summary."""

    def setUp(self):
        self.js = read("static/js/report_generator.js")

    def test_visual_summary_wired_into_report(self):
        self.assertIn("function visualSummary(model)", self.js)
        self.assertIn("visualSummary(model) +", self.js)

    def test_chart_builders_present(self):
        for fn in ["function donutSvg(", "function trajectorySvg(",
                   "function stackedTierBar(", "function legendHtml(",
                   "function chartCard("]:
            self.assertIn(fn, self.js)

    def test_chart_titles_locked(self):
        for title in ["Club share by zone", "Monthly approval trajectory",
                      "Renewal health", "Field-difficulty tier split (advisory)"]:
            self.assertIn(title, self.js)

    def test_r21_palette_constants(self):
        # Charts echo the R21 dashboard look (gradient greens + amber + alert).
        for const in ["ZONE_CHART_COLORS", "RING_ACTIVE", "RING_EXPIRING",
                      "RING_OVERDUE", "TIER_BAR_HIGH", "TIER_BAR_STANDARD"]:
            self.assertIn(const, self.js)

    def test_charts_present_in_doc_export_as_images(self):
        # Client requirement (2026-10-08): the DOC copy must carry the SAME
        # charts as the PDF copy. Word drops inline <svg> on HTML import, so
        # both export paths rasterise the four charts to PNG data URIs.
        self.assertIn("function chartsAsImages(", self.js)
        self.assertIn('toDataURL("image/png")', self.js)
        self.assertIn("chartsAsImages(buildReportContent(data))", self.js)  # DOC path
        self.assertIn("buildReportContentWithCharts(data)", self.js)        # PDF path
        # the old "hide the charts from Word" wrapper is gone
        self.assertNotIn("<!--[if !mso]><!-->", self.js)

    def test_chart_raster_fallback_is_safe(self):
        # If canvas rasterising is unavailable the SVG build must still be
        # returned — the click path may never hang or drop the report.
        self.assertIn("Promise.race([", self.js)
        self.assertIn("function svgToPngUri(", self.js)

    def test_charts_backed_by_verbatim_tables(self):
        # No-maths-change discipline: charts are presentation only; the engine
        # tables remain the single source of truth.
        self.assertIn("the tables are the source of truth", self.js)


if __name__ == "__main__":
    unittest.main()
