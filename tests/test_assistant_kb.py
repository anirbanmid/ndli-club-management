"""
Round 6 · Slice C — Documentation knowledge base + BM25 retriever + citations.

Covered (per Slice C brief):
1. Chunker: headings -> sections (title + path); no empty chunks; huge sections
   split into <=~800-char pieces; <script>/<style> noise excluded.
2. BM25 core: tokenizer / idf / score sanity (pure functions); ranking puts the
   obviously-relevant chunk first for a seeded question; empty query -> [].
3. Golden questions via the real HTTP API (POST /api/assistant/ask): 200; answer
   contains the expected keywords; sources non-empty with title + detail; the
   inline `[1]` citation marker is present.
4. Additive behaviour: existing Slice B routing/answers are preserved (the KB is
   reached only for app/FAQ/how-does-it-work questions; data + task-guide answers
   and the honest template fallback are unchanged).
5. Loud-failure discipline: a missing manual logs loudly and degrades gracefully
   (task guides still load, no crash); the KB module is read-only (no writes).

Run the whole suite from the repo root:
    python3 -m unittest discover -s tests
"""
import ast
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from app import NDLIRequestHandler
from init_db import initialize_database

from ai import knowledge_base as kb
from ai.assistant_core import ASSISTANT_ISSUES_LOG, ask_assistant
from ai.knowledge_base import (
    GOLDEN_QUESTIONS,
    bm25_score,
    idf,
    load_kb,
    retrieve_for_answer,
    search,
    tokenize,
)

# Mirrors tests/test_assistant_api._AssistantAPITestBase (server + helpers).
class _KBAPITestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        kb.reset_cache()  # ensure a clean real-KB load for the HTTP path
        cls.server = HTTPServer(("127.0.0.1", 0), NDLIRequestHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path: str, payload: dict, token: str = ""):
        import json
        import urllib.request
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _ask(self, question: str, token: str = ""):
        return self._post("/api/assistant/ask", {"question": question}, token=token)

    def _admin_token(self):
        from auth_util import admin_token
        return admin_token(self.base_url, self.__class__.__name__)


def _chunks_from_html(html: str):
    """Parse a manual HTML string into (sections, chunks) via the real parser."""
    parser = kb._SectionExtractor()
    parser.feed(html)
    parser.close()
    chunks = kb._chunk_manual("user manual", parser.sections, 0, "t")
    return parser.sections, chunks


class TestKBChunker(unittest.TestCase):
    """1. HTML -> heading-scoped chunks."""

    def test_headings_become_sections_with_paths(self):
        html = """
        <html><body>
          <h1>1. Alpha</h1><p>Intro alpha text.</p>
          <h2>1.1 Beta</h2><p>Body beta text.</p>
          <h3>1.1.1 Gamma</h3><p>Deep gamma text.</p>
        </body></html>
        """
        sections, chunks = _chunks_from_html(html)
        titles = [s["title"] for s in sections]
        self.assertIn("1. Alpha", titles)
        self.assertIn("1.1 Beta", titles)
        self.assertIn("1.1.1 Gamma", titles)
        # A nested heading's path is a breadcrumb of its ancestors.
        gamma = next(s for s in sections if s["title"] == "1.1.1 Gamma")
        self.assertIn("1. Alpha", gamma["path"])
        self.assertIn("1.1 Beta", gamma["path"])
        # Section bodies are captured.
        beta = next(s for s in sections if s["title"] == "1.1 Beta")
        self.assertIn("Body beta text", beta["text"])

    def test_no_empty_chunks(self):
        html = "<html><body><h1>T</h1><p></p><h2>U</h2><p>real text here</p></body></html>"
        _, chunks = _chunks_from_html(html)
        for c in chunks:
            self.assertTrue(c["text"].strip(), f"empty chunk produced: {c}")
            self.assertTrue(c["title"].strip())

    def test_huge_section_is_split(self):
        sentence = "This is a reasonably long sentence used to build a very large section body. "
        big = sentence * 60  # ~3900 chars, far over one chunk budget
        html = f"<html><body><h1>Big</h1><p>{big}</p></body></html>"
        _, chunks = _chunks_from_html(html)
        self.assertGreater(len(chunks), 1, "huge section must split into multiple chunks")
        for c in chunks:
            # allow the small coalesce overhead over MAX_CHUNK_CHARS
            self.assertLessEqual(len(c["text"]), kb.MAX_CHUNK_CHARS + 150)

    def test_scripts_and_styles_excluded(self):
        html = """
        <html><head><style>.hidden { color: red; }</style>
        <script>var secret = "doNotIncludeMe";</script></head>
        <body><h1>Doc</h1><p>Visible content only.</p>
        <script>anotherSecret();</script><style>.x{}</style></body></html>
        """
        _, chunks = _chunks_from_html(html)
        joined = " ".join(c["text"] for c in chunks)
        self.assertIn("Visible content only", joined)
        self.assertNotIn("doNotIncludeMe", joined)
        self.assertNotIn("anotherSecret", joined)
        self.assertNotIn("color: red", joined)

    def test_task_guides_seeded_as_chunks(self):
        chunks = kb._chunk_task_guides(0)
        self.assertTrue(chunks, "TASK_GUIDES must seed KB chunks")
        self.assertTrue(all(c["source"] == "task guide" for c in chunks))
        self.assertTrue(any("renewal" in c["title"].lower() for c in chunks))


class TestKBTokenizerAndBM25(unittest.TestCase):
    """2a. Pure BM25 building blocks."""

    def test_tokenize_lowercases_and_drops_stopwords(self):
        toks = tokenize("The QUICK Brown Fox and the lazy dog")
        self.assertIn("quick", toks)
        self.assertIn("brown", toks)
        self.assertNotIn("the", toks)
        self.assertNotIn("and", toks)

    def test_tokenize_folds_common_plurals(self):
        self.assertIn("backup", tokenize("Backups"))
        self.assertIn("club", tokenize("Clubs"))
        # conservative: leaves analysis/status/class alone
        self.assertIn("analysis", tokenize("analysis"))
        self.assertIn("status", tokenize("status"))

    def test_tokenize_empty_and_stopword_only(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("the is of a"), [])

    def test_idf_sanity(self):
        # Rarer terms carry higher idf; clamp is sane.
        self.assertGreater(idf(10, 1), idf(10, 9))
        self.assertGreaterEqual(idf(10, 0), idf(10, 10))
        self.assertEqual(idf(0, 0), 0.0)

    def test_bm25_score_relevant_beats_irrelevant(self):
        doc_freq = {"backup": 2, "drive": 2, "banana": 1}
        relevant = tokenize("rolling backup to google drive snapshot")
        irrelevant = tokenize("banana banana banana")
        q = tokenize("backup drive")
        s_rel = bm25_score(q, relevant, doc_freq, 3, 5.0)
        s_irr = bm25_score(q, irrelevant, doc_freq, 3, 5.0)
        self.assertGreater(s_rel, s_irr)
        self.assertEqual(s_irr, 0.0)  # no overlapping terms -> 0

    def test_bm25_empty_query_or_doc_is_zero(self):
        self.assertEqual(bm25_score([], tokenize("some text"), {}, 1, 1.0), 0.0)
        self.assertEqual(bm25_score(tokenize("some"), [], {}, 1, 1.0), 0.0)


# Small deterministic corpus for ranking tests (injected into the KB cache).
_SYNTH = [
    {"chunk_id": "syn:000", "source": "test", "section": "t1",
     "title": "Rolling Backup Daemon",
     "text": "The rolling backup daemon writes a zip snapshot every seven days to Google Drive."},
    {"chunk_id": "syn:001", "source": "test", "section": "t2",
     "title": "Star Rating Formula",
     "text": "Employee performance star rating weights club approvals and support tickets."},
    {"chunk_id": "syn:002", "source": "test", "section": "t3",
     "title": "State Zone Map",
     "text": "State zone mapping assigns each state to a regional nodal zone."},
]


class TestKBSearchRanking(unittest.TestCase):
    """2b. BM25 retrieval ordering + empty-query behaviour."""

    def setUp(self):
        kb.reset_cache()
        self._saved = kb._KB_CACHE
        kb._KB_CACHE = list(_SYNTH)
        kb._INDEX_CACHE = None

    def tearDown(self):
        kb._KB_CACHE = None
        kb._INDEX_CACHE = None
        kb.reset_cache()

    def test_ranking_puts_relevant_chunk_first(self):
        results = search("rolling backup google drive snapshot", k=3)
        self.assertTrue(results)
        self.assertEqual(results[0]["chunk"]["chunk_id"], "syn:000")
        self.assertEqual(results[0]["rank"], 1)
        self.assertGreater(results[0]["score"], 0)

    def test_empty_query_returns_empty(self):
        self.assertEqual(search("", k=3), [])
        self.assertEqual(search("   the is of  ", k=3), [])

    def test_retrieve_for_answer_rejects_weak_single_term_match(self):
        # "backup" is present in exactly ONE chunk -> only 1 distinct query term
        # matches, so the matched-term gate (< 2) rejects it (no over-claiming).
        self.assertEqual(retrieve_for_answer("backup", k=2), [])
        # A query with no matching term at all is also rejected.
        self.assertEqual(retrieve_for_answer("banana zzz", k=2), [])

    def test_retrieve_for_answer_accepts_strong_match(self):
        accepted = retrieve_for_answer("star rating performance", k=2)
        self.assertTrue(accepted)
        self.assertEqual(accepted[0]["chunk_id"], "syn:001")


class TestKBReadOnlyAndFailureLogging(unittest.TestCase):
    """5. Read-only module + loud-failure handling."""

    def test_knowledge_base_is_read_only(self):
        """AST check: the KB must never write/mutate the filesystem.
        (sys.stderr.write is the allowed LOUD logging path, so a generic
        ".write" is not forbidden -- only real file writes and fs mutations.)"""
        src = Path("ai/knowledge_base.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = set()
        names_used = set()
        bad_open_modes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names_used.add(node.id)
            if isinstance(node, ast.Call):
                fn = node.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                called.add(fname)
                if fname == "open":
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Constant) and any(m in str(arg.value) for m in ("w", "a", "x")):
                            bad_open_modes.append(str(arg.value))
        forbidden = {"remove", "unlink", "rmdir", "rename", "mkdir", "makedirs",
                     "rmtree", "write_text", "write_bytes", "writelines", "touch"}
        self.assertFalse(forbidden & called, f"KB must not call write APIs: {forbidden & called}")
        self.assertEqual(bad_open_modes, [], f"KB must not open files for writing: {bad_open_modes}")
        self.assertNotIn("shutil", names_used, "KB must not use shutil")

    def test_missing_manual_logs_loudly_and_degrades_gracefully(self):
        marker = "kb_marker_xyzzy_missing"
        orig_paths = kb.MANUAL_PATHS
        try:
            kb.MANUAL_PATHS = [
                ("user manual", Path(f"/nonexistent/{marker}/user_manual.html")),
                ("technical manual", Path(f"/nonexistent/{marker}/technical_manual.html")),
            ]
            kb.reset_cache()
            chunks = load_kb()  # must NOT raise
            # Graceful: task guides still load even with both manuals missing.
            self.assertTrue(any(c["source"] == "task guide" for c in chunks))
            # Loud: a knowledge_base line naming the missing path was logged.
            self.assertTrue(ASSISTANT_ISSUES_LOG.exists(), "loud log file must exist")
            content = ASSISTANT_ISSUES_LOG.read_text(encoding="utf-8")
            self.assertIn("knowledge_base", content)
            self.assertIn(marker, content)
            self.assertIn("MISSING", content)
        finally:
            kb.MANUAL_PATHS = orig_paths
            kb.reset_cache()  # restore the real KB for subsequent tests

    def test_search_on_empty_kb_is_graceful(self):
        orig_paths = kb.MANUAL_PATHS
        try:
            kb.MANUAL_PATHS = []  # no manuals at all
            kb.reset_cache()
            kb._KB_CACHE = []     # simulate fully-empty KB
            kb._INDEX_CACHE = None
            self.assertEqual(search("anything at all", k=3), [])
        finally:
            kb.MANUAL_PATHS = orig_paths
            kb._KB_CACHE = None
            kb._INDEX_CACHE = None
            kb.reset_cache()


class TestKBGoldenQuestionsAPI(_KBAPITestBase):
    """3. Golden questions answered from the KB via the real HTTP API."""

    def test_golden_questions_have_unique_ids(self):
        ids = [g["id"] for g in GOLDEN_QUESTIONS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(GOLDEN_QUESTIONS), 8)

    def test_each_golden_question_cited_answer(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        for g in GOLDEN_QUESTIONS:
            with self.subTest(golden=g["id"]):
                status, data = self._ask(g["question"], token=token)
                self.assertEqual(status, 200)
                self.assertTrue(data["success"])
                answer = data["answer"]
                # Answer contains the expected keywords (substring, case-insensitive).
                for kw in g["expected_keywords"]:
                    self.assertIn(kw.lower(), answer.lower(),
                                  f"[{g['id']}] answer missing keyword {kw!r}: {answer!r}")
                # Inline citation marker present (citations are claimed).
                self.assertIn("[1]", answer)
                # Response shape: sources non-empty with title + detail.
                self.assertTrue(data["sources"], f"[{g['id']}] sources must be non-empty")
                for s in data["sources"]:
                    self.assertIn("title", s)
                    self.assertIn("detail", s)
                    self.assertTrue(s["title"])
                    self.assertTrue(s["detail"])
                # Suggestions present (manual deep-link allowed).
                self.assertIsInstance(data["suggestions"], list)

    def test_citations_are_our_own_docs_not_injected_code(self):
        """KB text is DATA: the answer is plain text, no markup/script smuggled."""
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("What is the state-zone mapping?", token=token)
        self.assertEqual(status, 200)
        answer = data["answer"]
        self.assertNotIn("<script", answer.lower())
        self.assertNotIn("</", answer)

    def test_response_shape_exact(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("How does the automatic backup system work?", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(data["success"])
        self.assertIn("answer", data)
        self.assertIsInstance(data["answer"], str)
        self.assertIsInstance(data["sources"], list)
        self.assertIsInstance(data["suggestions"], list)


class TestKBAdditiveBehaviour(_KBAPITestBase):
    """4. Existing Slice B routing/answers preserved (KB is additive)."""

    def test_fallback_still_honest_for_gibberish(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("quantum flux capacitor banana??", token=token)
        self.assertEqual(status, 200)
        self.assertIn("template mode", data["answer"])  # KB did not hijack gibberish

    def test_unmatched_question_still_logged(self):
        from auth_util import admin_token
        token = admin_token(self.base_url, self.__class__.__name__)
        status, data = self._ask("log-tripwire-unique-xyzzy what even is this", token=token)
        self.assertEqual(status, 200)
        content = ASSISTANT_ISSUES_LOG.read_text(encoding="utf-8")
        self.assertIn("unmatched question", content)

    def test_task_guide_answer_unchanged(self):
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("how do I approve a renewal?", token=token)
        self.assertEqual(status, 200)
        self.assertIn("approve a club registration renewal", data["answer"])

    def test_data_question_not_stolen_by_kb(self):
        """'what is my quota' is a DATA request -> live figures, not a KB quote."""
        from auth_util import employee_token
        token = employee_token(self.base_url, self.__class__.__name__, emp_id="EMP01")
        status, data = self._ask("what is my quota", token=token)
        self.assertEqual(status, 200)
        self.assertIn("club approvals", data["answer"])  # live quota figure path
        self.assertNotIn("Here's what the NDLI documentation says", data["answer"])

    def test_app_help_routing_definitional(self):
        # Pure routing sanity: definitional app questions reach the KB path.
        from ai.assistant_core import _route
        self.assertEqual(_route("What is a renewal certificate?")[0], "app_help")
        self.assertEqual(_route("How does synchronization work?")[0], "app_help")
        # Personal data requests do NOT.
        self.assertEqual(_route("what is my quota")[0], "quota")
        self.assertEqual(_route("how do I approve a renewal?")[0], "help")


if __name__ == "__main__":
    unittest.main()
