"""
Round 58 -- Robu retrieval hardening (better chunking + a proper retriever).

Closes the critique's last weak pillar ("Robu retrieval is brittle: keyword
chunk retrieval without embeddings; golden answers depend on keywords sitting
'early' in chunks; adding manual text shifts chunk boundaries -> retrieval
[flaky]"). The three structural fixes and their regression pins:

1. RELEVANCE-CENTERED SNIPPETS (best_snippet): the quoted answer shows the
   best-matching verbatim window of a chunk, not its first 280 chars -- a
   keyword no longer has to sit early in its chunk (the Stage-3 lesson).
2. BOUNDARY-SAFE CHUNKING (overlap tails): consecutive split pieces share a
   ~120-char tail, so a fact near a chunk boundary lives in BOTH pieces --
   manual edits that shift boundaries can no longer orphan it.
3. HYBRID RETRIEVER (rank_chunks): BM25 + phrase/adjacency bonus + title bonus
   + a small deliberate ALIAS_MAP (spelling variants), plus an honest relaxed
   second pass in retrieve_for_answer (score gate relaxed to
   KB_RELAXED_MIN_SCORE; the matched-term gate is NEVER relaxed).

Numeric tripwires (test_r37_robu_v5 etc.) are untouched by design.

Run from the repo root:
    python3 -m unittest discover -s tests
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import unittest

from ai import knowledge_base as kb
from ai.knowledge_base import (
    ALIAS_MAP,
    GOLDEN_QUESTIONS,
    KB_RELAXED_MIN_SCORE,
    KB_MIN_SCORE,
    MIN_MATCHED_TERMS,
    OVERLAP_CHARS,
    SNIPPET_TRIM_CHARS,
    best_snippet,
    matched_term_count,
    rank_chunks,
    retrieve_for_answer,
    search,
    tokenize,
)


def _chunk(chunk_id, title, text, section="t", source="test"):
    return {"chunk_id": chunk_id, "source": source, "section": section,
            "title": title, "text": text}


def _use_synth(chunks):
    """Swap the cached KB for a synthetic chunk list (test-local, restored)."""
    kb.reset_cache()
    kb._KB_CACHE = list(chunks)
    kb._INDEX_CACHE = None


def _restore_kb():
    kb._KB_CACHE = None
    kb._INDEX_CACHE = None
    kb.reset_cache()


class TestAliasCanonicalisation(unittest.TestCase):
    """The alias map is a deliberate contract, not incidental drift."""

    def test_alias_map_is_pinned(self):
        # Additions are allowed -- but only as a VISIBLE test change (that is
        # the pin: retrieval behaviour may not drift silently).
        self.assertEqual(
            sorted(ALIAS_MAP.items()),
            sorted([
                ("synchronisation", "sync"), ("synchronization", "sync"),
                ("synchronize", "sync"), ("synchronized", "sync"),
                ("synchronizes", "sync"), ("synchronizing", "sync"),
                ("synchronise", "sync"), ("synchronised", "sync"),
                ("sync", "sync"),
                ("authentication", "authentication"),
                ("authorize", "authorization"), ("authorized", "authorization"),
                ("customise", "customize"), ("customised", "customize"),
                ("initialise", "initialize"), ("initialised", "initialize"),
                ("analyse", "analyze"), ("behaviour", "behavior"),
                ("favourite", "favorite"), ("config", "configuration"),
                ("renew", "renewal"), ("renewed", "renewal"),
                ("renewing", "renewal"), ("renewal", "renewal"),
            ]))

    def test_variants_map_to_the_same_index_token(self):
        self.assertEqual(kb._index_tokens("Synchronisation"),
                         kb._index_tokens("synchronization"))
        self.assertEqual(kb._index_tokens("renew"), kb._index_tokens("renewal"))
        self.assertIn("sync", kb._index_tokens("How does synchronization work?"))

    def test_tokenize_contract_unchanged(self):
        # tokenize() itself stays pure and alias-free (the canon layer is above it).
        self.assertEqual(tokenize("The class status analysis"), ["class", "status", "analysis"])


class TestHybridRanking(unittest.TestCase):
    """BM25 + phrase/adjacency bonus + title bonus over synthetic chunks."""

    def test_phrase_bonus_ranks_adjacent_terms_first(self):
        chunks = [
            _chunk("syn:000", "Scattered", "rolling snapshots happen daily. "
                   "The google drive mirror is separate. A backup runs weekly."),
            _chunk("syn:001", "Adjacent", "The rolling backup snapshot goes to google drive."),
        ]
        results = rank_chunks("rolling backup snapshot", chunks, k=2)
        self.assertEqual(results[0]["chunk"]["chunk_id"], "syn:001",
                         "adjacent query terms must outrank scattered ones")

    def test_title_bonus_ranks_topic_heading_first(self):
        body = ("This paragraph mentions performance in passing among other topics. "
                "It discusses club approvals and support tickets at length.")
        chunks = [
            _chunk("syn:000", "Misc Notes", body),
            _chunk("syn:001", "Performance Review Process", body),
        ]
        results = rank_chunks("performance review", chunks, k=2)
        self.assertEqual(results[0]["chunk"]["chunk_id"], "syn:001",
                         "a query term in the title must outrank a body mention")

    def test_alias_variants_match_across_spellings(self):
        chunks = [
            _chunk("syn:000", "Sync", "Node synchronisation reconciles records with the master."),
            _chunk("syn:001", "Other", "The training library holds PPT presentations."),
        ]
        results = rank_chunks("synchronization master", chunks, k=2)
        self.assertTrue(results, "British spelling in the doc must match an American query")
        self.assertEqual(results[0]["chunk"]["chunk_id"], "syn:000")
        self.assertGreaterEqual(
            matched_term_count(kb._index_tokens("synchronization master"), results[0]["chunk"]),
            MIN_MATCHED_TERMS)

    def test_rank_chunks_is_deterministic_on_ties(self):
        chunks = [
            _chunk("syn:001", "B", "zone mapping text about zones and states."),
            _chunk("syn:000", "A", "zone mapping text about zones and states."),
        ]
        ids = [r["chunk"]["chunk_id"] for r in rank_chunks("zone mapping", chunks, k=2)]
        self.assertEqual(ids, ["syn:000", "syn:001"], "ties break by chunk_id")


class TestBoundarySafeChunking(unittest.TestCase):
    """Overlap tails: a boundary can no longer split a query's evidence apart."""

    # 12 sentences of EXACTLY 99 chars each -> greedy packing at budget 680
    # puts exactly 6 sentences in piece 1; sentence 6 = "zephyr", sentence 7 =
    # "quokka" -> the split boundary falls BETWEEN them (the flaky case).
    @staticmethod
    def _sentence(i, tail=""):
        base = f"Routine filler sentence describing ordinary club workflow number {i:02d}"
        body = (base + " " + tail).strip()
        return body.ljust(98, "w") + "."

    def _long_text(self):
        sents = [self._sentence(i) for i in range(1, 13)]
        sents[5] = self._sentence(6, "the zephyr marker applies here")
        sents[6] = ("Quokka handling rules follow the standard retention policy "
                    "for ordinary records").ljust(98, "w") + "."
        return " ".join(sents)

    def test_split_geometry_is_as_designed(self):
        text = self._long_text()
        pieces = kb._split_text(text)
        self.assertEqual(len(pieces), 2, f"expected 2 pieces, got {len(pieces)}")
        self.assertIn("zephyr", pieces[0])
        self.assertNotIn("quokka", pieces[0])

    def test_overlapping_piece_keeps_the_boundary_fact(self):
        # NON-VACUOUS: "zephyr" lives in sentence 6 (piece 1) and "quokka" in
        # sentence 7 (piece 2). Piece 2 contains BOTH only because of the
        # overlap tail -- remove the overlap and this assert fails.
        pieces = kb._split_text(self._long_text())
        self.assertIn("zephyr", pieces[1], "overlap tail lost the boundary fact")
        self.assertIn("quokka", pieces[1].lower())

    def test_every_piece_after_the_first_starts_with_predecessor_tail(self):
        text = self._long_text()
        pieces = kb._split_text(text)
        overlap = min(OVERLAP_CHARS, kb.MAX_CHUNK_CHARS // 4)
        for prev, cur in zip(pieces, pieces[1:]):
            tail = kb._tail_overlap(prev, overlap)
            self.assertTrue(tail, "overlap tail must be non-empty")
            self.assertTrue(cur.startswith(tail),
                            "piece must begin with the verbatim tail of its predecessor")

    def test_boundary_straddling_query_is_retrievable(self):
        # The two query terms live in DIFFERENT sentences of the source text,
        # on opposite sides of the split boundary -- only the overlap lets one
        # chunk vouch for both (the pre-R58 failure class).
        text = self._long_text()
        self.assertNotIn("quokka zephyr", text.lower())
        pieces = kb._split_text(text)
        chunks = [_chunk(f"syn:{i:03d}", f"Part {i}", p) for i, p in enumerate(pieces)]
        hits = [c for c in chunks
                if matched_term_count(kb._index_tokens("zephyr quokka"), c) >= MIN_MATCHED_TERMS]
        self.assertTrue(hits, "no chunk vouches for both boundary terms")
        # Behavioural: with a small realistic corpus around it, the answer-grade
        # retrieval must accept that overlapped chunk.
        filler = ("Routine club housekeeping prose about ordinary weekly workflows "
                  "and standard administrative maintenance procedures.")
        corpus = chunks + [_chunk(f"syn:9{i}", f"Filler {i}", filler) for i in range(6)]
        _use_synth(corpus)
        try:
            got = retrieve_for_answer("zephyr quokka", k=2)
        finally:
            _restore_kb()
        self.assertTrue(got, "boundary-straddling query must be answerable")
        self.assertIn("zephyr", got[0]["text"])
        self.assertIn("quokka", got[0]["text"].lower())

    def test_short_sections_split_unchanged(self):
        # Unchanged pre-R58 behaviour for sections that fit one piece.
        self.assertEqual(kb._split_text("Short section text."), ["Short section text."])


class TestRelevanceCenteredSnippets(unittest.TestCase):
    """best_snippet: the quoted window follows the query, not the chunk head."""

    def test_late_keyword_survives_in_the_snippet(self):
        filler = "Routine procedural wording about ordinary club maintenance tasks. " * 9
        text = filler + "The azurite rule is documented here." + " " + filler
        chunk = _chunk("syn:000", "Late Fact", text)
        self.assertGreater(text.find("azurite"), SNIPPET_TRIM_CHARS,
                           "fixture must place the keyword LATE (past the old trim)")
        snip = best_snippet(chunk, "what is the azurite rule", SNIPPET_TRIM_CHARS)
        self.assertIn("azurite", snip, "late keyword must survive into the snippet")
        self.assertLessEqual(len(snip), SNIPPET_TRIM_CHARS + 10)

    def test_snippet_is_verbatim(self):
        filler = "Procedural wording about routine operations repeats here often. " * 12
        text = filler + "The wonderword appears in this sentence among others."
        chunk = _chunk("syn:000", "Verbatim", text)
        snip = best_snippet(chunk, "wonderword", SNIPPET_TRIM_CHARS)
        core = snip.strip(".")
        self.assertIn(core, text, "snippet must be a verbatim substring (plus ellipses)")
        self.assertTrue(snip.startswith("...") or snip == text[:len(snip)],
                        "interior windows carry a head ellipsis")
        self.assertTrue(snip.endswith("...") or snip.endswith(text[-1]))

    def test_short_chunk_returned_whole(self):
        chunk = _chunk("syn:000", "Short", "A short chunk text.")
        self.assertEqual(best_snippet(chunk, "anything", SNIPPET_TRIM_CHARS), "A short chunk text.")

    def test_no_hit_keeps_head_window(self):
        filler = "Procedural wording about routine operations repeats here often. " * 12
        chunk = _chunk("syn:000", "NoHit", filler)
        snip = best_snippet(chunk, "xylophone quantum", SNIPPET_TRIM_CHARS)
        self.assertTrue(filler.startswith(snip.rstrip(".")),
                        "unmatched queries keep the old head trim")
        self.assertTrue(snip.endswith("..."))

    def test_early_keyword_answers_are_unchanged(self):
        # The pre-R58 head trim stays byte-identical when the hit IS early.
        filler = "Procedural wording about routine operations repeats here often. " * 12
        text = "The cobalt procedure. " + filler
        chunk = _chunk("syn:000", "Early", text)
        snip = best_snippet(chunk, "cobalt procedure", SNIPPET_TRIM_CHARS)
        self.assertTrue(text.startswith(snip.rstrip(".")),
                        "an early hit must render exactly like the old head trim")


class TestHonestFallbackGates(unittest.TestCase):
    """The relaxed second pass never weakens the matched-term gate."""

    def setUp(self):
        self._saved_min = kb.KB_MIN_SCORE

    def tearDown(self):
        kb.KB_MIN_SCORE = self._saved_min
        _restore_kb()

    def test_relaxed_second_pass_rescues_low_score_match(self):
        # Two rare terms, each once, far apart in a LONG chunk -> BM25 lands
        # between KB_RELAXED_MIN_SCORE and KB_MIN_SCORE. Strict gate says no,
        # matched terms say yes (2) -> the R58 second pass answers.
        filler = ("routine ordinary procedural wording about club maintenance "
                  "and administrative housekeeping tasks ") * 4
        chunks = [
            _chunk("syn:000", "Long", f"{filler}kumquat {filler}narwhal {filler}"),
            _chunk("syn:001", "Long2", f"{filler}kumquat {filler}narwhal {filler}"),
            _chunk("syn:002", "Filler A", filler),
            _chunk("syn:003", "Filler B", filler),
            _chunk("syn:004", "Filler C", filler),
        ]
        _use_synth(chunks)
        got = retrieve_for_answer("kumquat narwhal", k=2)
        self.assertTrue(got, "matched-but-under-gate chunk must be rescued")
        self.assertEqual(got[0]["chunk_id"], "syn:000")
        # Prove the strict gate alone would have said NO (non-vacuous rescue).
        top = search("kumquat narwhal", k=1)[0]["score"]
        self.assertLess(top, self._saved_min,
                        "fixture must actually sit under the strict gate")

    def test_single_term_match_still_rejected_in_both_passes(self):
        chunks = [
            _chunk("syn:000", "Backup", "The rolling backup daemon writes a zip snapshot."),
            _chunk("syn:001", "Star", "Employee performance star rating weights approvals."),
        ]
        _use_synth(chunks)
        self.assertEqual(retrieve_for_answer("backup", k=2), [],
                         "single-term matches stay rejected (over-claiming guard)")

    def test_gibberish_still_rejected_in_both_passes(self):
        chunks = [_chunk("syn:000", "Real", "Ordinary club workflow documentation text.")]
        _use_synth(chunks)
        self.assertEqual(retrieve_for_answer("quantum flux capacitor banana", k=2), [])

    def test_relaxed_constant_is_below_strict(self):
        self.assertLess(KB_RELAXED_MIN_SCORE, KB_MIN_SCORE)


class TestGoldenCoverage(unittest.TestCase):
    """Every golden question's top hit quotes at least one expected keyword."""

    def test_golden_snippets_still_carry_expected_keywords(self):
        for g in GOLDEN_QUESTIONS:
            with self.subTest(golden=g["id"]):
                hits = retrieve_for_answer(g["question"], k=2)
                self.assertTrue(hits, f"[{g['id']}] retrieval found nothing")
                snippet = best_snippet(hits[0], g["question"], SNIPPET_TRIM_CHARS)
                joined = (snippet + " " + str(hits[0].get("title") or "")).lower()
                self.assertTrue(
                    any(kw.lower() in joined for kw in g["expected_keywords"]),
                    f"[{g['id']}] snippet lost the expected keywords: {snippet[:120]!r}")


if __name__ == "__main__":
    unittest.main()
