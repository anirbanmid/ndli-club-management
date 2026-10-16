"""
Round 62 -- manual readability + Robu's mastery of the manual.

Two user-reported problems (2026-10-16), one bundle:

A. "The technical manual has lots of blank (only black screen's pic)
   screenshots." Root cause measured: the black rectangles are CODE BLOCKS --
   `code { color: #0F172A }` (dark navy) beat the inherited `pre { color:
   #E2E8F0 }` inside `pre { background: #0B151F }` boxes, so the code text was
   dark-on-dark and invisible. Fixes + diagrams + honest pagination:
   A1 pre code colour fix (black boxes can never return -- pin 1)
   A2 front-matter pages: System Overview & End-to-End Process Flow (SVG) +
      System Mindmap & Manual Map (SVG + chapter map) (pins 2-3)
   A3 honest pagination: every "Page X of N" label + every TOC row agrees
      with the page that carries the chapter (pins 4-5)

B. Robu answered real user chats badly: "technical manual" -> cover-page
   dump (incl. personal contact details), "Full NDLI Club Management manual"
   -> live club counts (club-data routing steal), pasted manual URL ->
   cover-page dump again. Fixes:
   B1 cover pages wrapped in KB-EXCLUDE markers -> never indexed (pins 6-7)
   B2 the overview pages are the retrieval anchor for process/architecture
      questions (pin 8)
   B3 bare manual requests route to the orientation answer BEFORE the data
      intents; "manual entry" (real app feature) is not hijacked (pins 9-11)
   B4 pasted manual URLs get the orientation answer, never a cover dump
      (pins 9, 12)
   B5 the three real chat failures live on as golden-question regressions
      (pin 13; also enforced by `python3 -m ai.assistant_evals`)

Run from the repo root:
    python3 -m unittest discover -s tests
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

from ai import assistant_core, knowledge_base as kb

DOCS = Path(__file__).resolve().parent.parent / "docs"
TECH = (DOCS / "technical_manual.html").read_text(encoding="utf-8")
USER = (DOCS / "user_manual.html").read_text(encoding="utf-8")

R62_IDS = ("r62_manual_map_vague", "r62_manual_map_full_title", "r62_manual_url_paste")


class TestCodeBlockReadability(unittest.TestCase):
    """A1: dark-on-dark code blocks (the "black screenshots") can never return."""

    def test_pre_code_rule_sets_light_text(self):
        m = re.search(r"pre code \{([^}]*)\}", TECH)
        self.assertIsNotNone(m, "pre code CSS rule missing")
        body = m.group(1)
        colours = dict(re.findall(r"(color|background)\s*:\s*(#[0-9A-Fa-f]{3,8})", body))
        self.assertIn("color", colours, "pre code must set its own text colour")
        self.assertEqual(colours["color"].upper(), "#E2E8F0",
                         "pre code text must stay light on the dark pre background")

    def test_every_pre_block_is_the_dark_theme(self):
        # The dark theme is a deliberate design: pre bg must remain #0B151F so
        # the pinned light text colour is the one that makes it readable.
        m = re.search(r"pre \{([^}]*)\}", TECH)
        self.assertIsNotNone(m)
        self.assertIn("#0B151F", m.group(1))


class TestDiagramAndOverviewSections(unittest.TestCase):
    """A2: the two SVG figures + front-matter sections exist, exactly once."""

    def test_both_svgs_present_exactly_once(self):
        for svg_id in ("fig-process-flow", "fig-system-mindmap"):
            self.assertEqual(TECH.count(f'id="{svg_id}"'), 1, svg_id)

    def test_front_matter_headings_present(self):
        self.assertIn("System Overview &amp; End-to-End Process Flow (Start Here)", TECH)
        self.assertIn("System Mindmap &amp; Manual Map", TECH)
        self.assertIn("Manual Map &mdash; which chapter answers your question", TECH)

    def test_manual_map_table_covers_the_book(self):
        # The chapter-map table must point at the real chapter span.
        for row in ("Ch. 3", "Ch. 8", "Ch. 11&ndash;12 + Appendix A", "Ch. 18", "Ch. 20"):
            self.assertIn(row, TECH, row)


class TestHonestPagination(unittest.TestCase):
    """A3: designed page labels + TOC rows agree with each other, always."""

    def test_page_labels_are_honest(self):
        labels = [(int(n), int(tot)) for n, tot in
                  re.findall(r"class=\"header-tag-right\">Page (\d+) of (\d+)</span>", TECH)]
        self.assertTrue(labels, "no page labels found")
        self.assertEqual(len(labels), 31, "expected 31 labelled pages (cover unlabelled)")
        totals = {tot for _, tot in labels}
        self.assertEqual(totals, {32}, f"mixed totals: {totals}")
        nums = [n for n, _ in labels]
        self.assertEqual(nums, sorted(nums), "labels out of order")
        self.assertEqual(len(set(nums)), len(nums), "duplicate page labels")
        self.assertEqual(nums[0], 2, "first labelled page is the TOC")
        self.assertEqual(nums[-1], 32, "last labelled page must equal the total")

    def test_toc_rows_match_their_pages(self):
        # Split the body into labelled page segments, then assert every TOC
        # row's page number equals the label of the segment carrying that h1.
        parts = re.split(r"class=\"header-tag-right\">Page (\d+) of \d+</span>", TECH)

        def unescape(s: str) -> str:
            return (s.replace("&amp;", "&").replace("&ndash;", "\u2013")
                     .replace("&mdash;", "\u2014").replace("&#9733;", "\u2605")
                     .replace("&bull;", "\u2022").replace("&times;", "\u00d7"))

        segs = {}  # label -> unescaped segment html
        for i in range(1, len(parts) - 1, 2):
            segs[int(parts[i])] = unescape(parts[i + 1])

        rows = re.findall(r"class=\"toc-chapter\">([^<]+)</span>"
                          r"<span class=\"toc-dots\"></span>"
                          r"<span class=\"toc-page-num\">Page (\d+)</span>", TECH)
        self.assertEqual(len(rows), 23, "expected 23 TOC rows (21 chapters + 2 front-matter)")
        for title, page in rows:
            # TOC front-matter rows carry a "\u2605" prefix the h1 does not have.
            want = unescape(title).strip().lstrip("\u2605 ")
            found = [n for n, seg in segs.items()
                     if re.search(r"<h1>\s*" + re.escape(want), seg)]
            self.assertTrue(found, f"TOC row not found in any page: {want!r}")
            self.assertIn(int(page), found,
                          f"TOC says {want!r} is on page {page}, found on {found}")


class TestKbCoverExclusion(unittest.TestCase):
    """B1: cover pages (author contact, marketing pills) are not retrievable."""

    def test_extractor_honors_kb_exclude_markers(self):
        html = ("<html><body>"
                + "<!-- " + kb.KB_EXCLUDE_START + " -->" +
                "<h1>Secret Cover Title</h1><p>Private contact 555-0100</p>"
                + "<!-- " + kb.KB_EXCLUDE_END + " -->" +
                "<h1>Real Chapter</h1><p>Real content.</p></body></html>")
        p = kb._SectionExtractor()
        p.feed(html)
        p.close()
        titles = [s["title"] for s in p.sections]
        self.assertEqual(titles, ["Real Chapter"], titles)

    def test_covers_are_not_indexed(self):
        chunks = kb.load_kb()
        self.assertTrue(chunks)
        bad = [c["chunk_id"] for c in chunks
               if c["title"].startswith("NDLI Club Management & Regional Employee Activity")
               or c["title"].startswith("NDLI Club Management System: Technical Architecture")]
        self.assertEqual(bad, [], f"cover sections leaked into the KB: {bad}")

    def test_contact_details_only_in_the_attribution_chapter(self):
        # The cover's contact box must not be quotable; ch. 20.2 (attribution)
        # is legitimate handover content and keeps its own copy.
        offenders = [c["chunk_id"] for c in kb.load_kb()
                     if ("anirbanmid@gmail.com" in c["text"]
                         and not c["title"].startswith("20.2"))]
        self.assertEqual(offenders, [], offenders)


class TestOverviewRetrievalAnchor(unittest.TestCase):
    """B2: process/architecture questions land on the overview pages."""

    def test_process_questions_hit_the_overview(self):
        for q in ("how does the entire process work",
                  "how does data flow through the system",
                  "process flow of an activity"):
            hits = kb.retrieve_for_answer(q, k=2)
            self.assertTrue(hits, q)
            self.assertTrue(hits[0]["title"].startswith("System Overview"), (q, hits[0]["title"]))


class TestManualMapRouting(unittest.TestCase):
    """B3/B4: bare manual requests + pasted URLs -> orientation, never data."""

    def test_bare_manual_requests_route_to_manual_map(self):
        for q in ("technical manual", "user manual", "Full NDLI Club Management manual",
                  "https://anirbanmid.pythonanywhere.com/docs/technical_manual.html",
                  "https://anirbanmid.pythonanywhere.com/manual"):
            intent, _ = assistant_core._route(q)
            self.assertEqual(intent, "manual_map", (q, intent))

    def test_app_feature_phrases_not_hijacked(self):
        for q in ("how do I do manual entry", "show me my quota", "how many clubs"):
            intent, _ = assistant_core._route(q)
            self.assertNotEqual(intent, "manual_map", (q, intent))

    def test_specific_doc_questions_keep_retrieval(self):
        q = "What does the user manual say about Import Existing Club and its historical dates?"
        intent, _ = assistant_core._route(q)
        self.assertEqual(intent, "app_help", intent)

    def test_count_rule_intent_unmoved(self):
        intent, _ = assistant_core._route("How are clubs counted \u2014 live versus migrated?")
        self.assertEqual(intent, "count_rule", intent)

    def test_compose_manual_map_quotes_front_matter(self):
        res = assistant_core._compose_manual_map("technical manual")
        answer = res["answer"]
        self.assertIn("System Overview", answer)
        self.assertIn("Manual Map", answer)
        self.assertIn("process flow", answer.lower())
        self.assertNotIn("anirbanmid", answer, "orientation answer must not dump contact details")
        self.assertNotIn("Lead System Architect", answer)


class TestGoldenRegressions(unittest.TestCase):
    """B5: the three real chat failures are permanent eval regressions."""

    def test_r62_goldens_all_pass(self):
        from ai import assistant_evals
        goldens = [g for g in kb.GOLDEN_QUESTIONS if g.get("id") in R62_IDS]
        self.assertEqual(len(goldens), 3, [g.get("id") for g in goldens])
        report = assistant_evals.run_evals(goldens=goldens)
        self.assertEqual(report.get("passed", 0), 3, report)
        self.assertEqual(report.get("total", 0), 3, report)


if __name__ == "__main__":
    unittest.main()
