"""
NDLI Club Management - Documentation Knowledge Base + BM25 Retriever (Round 6 · Slice C)

PLAN_AI_ASSISTANT.md §2: "RETRIEVER = docs/manual/FAQ chunks + BM25 keyword scoring".
Slice C turns the two shipped HTML manuals plus the task guides into a small,
citation-bearing knowledge base so the assistant can answer app / FAQ /
how-does-it-work questions with inline `[1]`, `[2]` markers pointing at a real
documentation section.

Hard rules honored here:
1. STDLIB ONLY. Structure is extracted from the manuals with html.parser
   (NO new dependencies, no frameworks, no build steps).
2. READ-ONLY BY CONSTRUCTION. This module NEVER writes to any file. The only
   loud side effect is a log line handed to ai.assistant_core.log_assistant_issue
   (imported lazily to avoid a circular import) when a manual is missing or
   unparseable -- never raise at import, never `except: pass`.
3. LAZY + THREAD-SAFE + CACHED. HTML is parsed on first use (PA cold-start
   friendly); the result is cached behind a lock. Nothing is parsed at import
   time.
4. UNIT-TESTABLE PURE CORE. tokenize(), idf(), bm25_score() are pure functions
   with no I/O so tests can pin the scoring maths.

Chunk shape (what load_kb() returns) -- a list of dicts:
    {chunk_id, source, section, title, text}
        chunk_id : stable id ("user:007", "tech:012", "task:003")
        source   : "user manual" | "technical manual" | "task guide"
        section  : heading path ("7. Central Administration Office Portal › 7.8 ...")
        title    : the leaf heading text
        text     : the section body (or the task-guide steps), already cleaned

Prompt-injection hygiene: the chunk text is DATA copied from our own manuals.
It is returned as plain strings and rendered as answer text by the orchestrator
via ordinary string composition (the widget uses textContent). Nothing in this
module interprets query or chunk text as instructions.
"""
import math
import re
import threading
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import BASE_DIR

# ---------------------------------------------------------------------------
# Loud logging (lazy import of assistant_core to avoid a circular dependency).
# Never `except: pass` -- every failure is either logged loudly or printed loud.
# ---------------------------------------------------------------------------


def _log(component: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    try:
        from ai.assistant_core import log_assistant_issue  # lazy: assistant_core imports us
        log_assistant_issue(component, message, context)
    except Exception as exc:  # loud last resort: stderr, never silent
        import sys
        sys.stderr.write(f"KB LOG WIRE FAILED ({component}): {exc} :: {message}\n")


# ---------------------------------------------------------------------------
# Configuration (tunable)
# ---------------------------------------------------------------------------

DOCS_DIR = Path(BASE_DIR) / "docs"

# Both manuals as (source_label, filename). Order is stable -> stable chunk ids.
MANUAL_SOURCES: List[Tuple[str, str]] = [
    ("user manual", "user_manual.html"),
    ("technical manual", "technical_manual.html"),
]

# Lazily resolved absolute paths; monkeypatchable for the missing-manual test.
MANUAL_PATHS: List[Tuple[str, Path]] = [
    (label, DOCS_DIR / fname) for label, fname in MANUAL_SOURCES
]

MAX_CHUNK_CHARS = 800          # split a huge section into ~800-char pieces
SNIPPET_TRIM_CHARS = 280       # orchestrator trims a chunk to this for the answer
KB_MIN_SCORE = 2.0             # tunable relevance gate for answering from the KB
KB_RELAXED_MIN_SCORE = 1.0     # R58 second-pass gate (matched-term gate unchanged)
BM25_K1 = 1.5
BM25_B = 0.75

# R58 (retrieval hardening): consecutive split pieces share a tail of this many
# chars, so a fact near a chunk boundary is present in BOTH neighbours -- adding
# text to a manual can no longer "orphan" a keyword on the wrong side of a
# boundary (the Stage-3 flakiness class). Pieces stay <= MAX_CHUNK_CHARS (+ the
# coalesce overhead), so the chunk-size contract is unchanged.
OVERLAP_CHARS = 120

# R58 hybrid-ranking bonuses (pure scoring additions on top of BM25).
PHRASE_BONUS = 0.6             # per adjacent query-token pair found adjacent in the chunk
PHRASE_BONUS_CAP = 1.8
TITLE_BONUS = 0.8              # per distinct query token found in the chunk's title
TITLE_BONUS_CAP = 1.6

# Heading levels treated as section boundaries.
_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3}

# Tags whose content is noise (never part of a documentation section).
_SKIP_TAGS = {"script", "style", "head", "nav", "footer", "svg", "noscript", "template", "form"}

# Block-ish tags that force a token boundary (so "<td>Club</td><td>5</td>" -> "Club 5",
# while inline tags like <em>al</em> still glue to their neighbour).
_SEP_TAGS = {"p", "div", "tr", "td", "th", "li", "br", "h1", "h2", "h3", "h4",
             "pre", "table", "section", "article", "ul", "ol", "blockquote", "hr", "figcaption"}

# R62 (B1): cover pages are wrapped in these HTML comments in both manuals.
# Everything between them (author contact, marketing pills, cover title) is
# deliberately NOT part of the retrieval KB: vague queries used to be answered
# with cover-page dumps (incl. personal contact details). Marker-driven, not
# title/regex heuristics -- renaming a heading can never re-open the hole.
KB_EXCLUDE_START = "KB-EXCLUDE-START"
KB_EXCLUDE_END = "KB-EXCLUDE-END"


# ---------------------------------------------------------------------------
# Pure tokenisation + BM25 scoring (unit-testable, no I/O)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset("""
a an the and or but if then than that this these those is are was were be been being am
do does did doing have has had having i me my we our you your it its of in on at to for
with by from as into about over after before between out up down off again further once
here there when where why how all any both each few more most other some such no nor not
only own same so too very can will just should now what which who whom his her their
""".split())


def _normalize_token(token: str) -> str:
    """
    Very light morphological normalization: fold a common English plural back
    to its singular so "backups"~"backup", "clubs"~"club", "issues"~"issue"
    match. Deliberately conservative (no full stemmer): only a trailing "s" is
    stripped, and only for words longer than 3 chars that don't already end in
    ss/us/is (so "class"/"status"/"analysis" are left alone). Pure.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> List[str]:
    """
    Lowercase alphanumeric tokens, stopword-filtered, length > 1, with light
    plural folding. Pure (unit-testable).
    """
    if not text:
        return []
    raw = re.findall(r"[a-z0-9]+", text.lower())
    out: List[str] = []
    for t in raw:
        if len(t) > 1 and t not in _STOPWORDS:
            out.append(_normalize_token(t))
    return out


# R58: post-tokenize canonicalisation so spelling variants and abbreviations
# hit the same index term. Deliberately SMALL and domain-scoped: variants of the
# same word only -- never fuzzy semantics (a synonym guess is worse than no
# match). Applied to BOTH sides (query and docs) by _index_tokens(); the
# tokenize() contract above is untouched. The exact map is pinned by
# tests/test_r58_retrieval.py -- additions are deliberate, not incidental.
ALIAS_MAP = {
    "synchronisation": "sync",
    "synchronization": "sync",
    "synchronize": "sync",
    "synchronized": "sync",
    "synchronizes": "sync",
    "synchronizing": "sync",
    "synchronise": "sync",
    "synchronised": "sync",
    "sync": "sync",
    "authentication": "authentication",
    "authorize": "authorization",
    "authorized": "authorization",
    "customise": "customize",
    "customised": "customize",
    "initialise": "initialize",
    "initialised": "initialize",
    "analyse": "analyze",
    "behaviour": "behavior",
    "favourite": "favorite",
    "config": "configuration",
    "renew": "renewal",
    "renewed": "renewal",
    "renewing": "renewal",
    "renewal": "renewal",
}


def _index_tokens(text: str) -> List[str]:
    """
    tokenize() + ALIAS_MAP canonicalisation. The single token stream used by the
    index AND the query (so variants match symmetrically). Pure.
    """
    return [ALIAS_MAP.get(t, t) for t in tokenize(text)]


def idf(n_docs: int, doc_freq: int) -> float:
    """Robertson/Sparck-Jones BM25 idf. Pure."""
    if n_docs <= 0:
        return 0.0
    df = max(0, min(doc_freq, n_docs))
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def bm25_score(query_tokens: Sequence[str], doc_tokens: Sequence[str],
               doc_freq: Dict[str, int], n_docs: int, avgdl: float,
               k1: float = BM25_K1, b: float = BM25_B) -> float:
    """
    BM25 score of ONE document against an already-tokenised query. Pure.

    query_tokens : tokenised query
    doc_tokens   : tokenised document (term frequencies are derived from it)
    doc_freq     : term -> number of documents containing the term (for idf)
    """
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    denom_norm = (1.0 - b + b * (dl / (avgdl or 1.0)))
    score = 0.0
    for term in query_tokens:
        freq = tf.get(term, 0)
        if not freq:
            continue
        term_idf = idf(n_docs, doc_freq.get(term, 0))
        denom = freq + k1 * denom_norm
        if denom <= 0:
            continue
        score += term_idf * (freq * (k1 + 1.0)) / denom
    return score


# ---------------------------------------------------------------------------
# HTML -> heading-scoped sections (stdlib html.parser)
# ---------------------------------------------------------------------------


class _SectionExtractor(HTMLParser):
    """
    Splits manual HTML into heading-scoped sections.

    Each section = {level, title, path, text}. The heading stack builds a
    breadcrumb "path" ("h1 › h2 › h3"). script/style/nav/head/footer noise is
    dropped. Heading text is the section title; the body between headings is the
    section text (whitespace-collapsed).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._excluded = False
        self._heading_level: Optional[int] = None
        self._heading_buf: List[str] = []
        self._body_buf: List[str] = []
        self._stack: Dict[int, str] = {}
        self._cur: Optional[Dict[str, Any]] = None
        self.sections: List[Dict[str, Any]] = []

    # -- tag handling ---------------------------------------------------
    def handle_comment(self, data: str) -> None:
        # R62 (B1): KB-EXCLUDE markers wrap cover pages. Inside a marker EVERYTHING
        # (headings included) is dropped, so no cover section ever forms.
        if KB_EXCLUDE_START in data:
            self._excluded = True
        elif KB_EXCLUDE_END in data:
            self._excluded = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if self._excluded:
            return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_LEVELS:
            # A new heading closes the previous section body first.
            self._flush_section()
            self._heading_level = _HEADING_LEVELS[tag]
            self._heading_buf = []
            return
        if tag in _SEP_TAGS and self._heading_level is None:
            self._body_buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._excluded:
            return
        if tag in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_LEVELS and self._heading_level is not None:
            title = _clean_text(" ".join(self._heading_buf))
            level = self._heading_level
            self._heading_level = None
            self._heading_buf = []
            if title:
                self._start_section(level, title)
            return
        if tag in _SEP_TAGS and self._heading_level is None:
            self._body_buf.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._excluded:
            return
        if self._heading_level is not None:
            self._heading_buf.append(data)
        else:
            self._body_buf.append(data)

    # -- section bookkeeping --------------------------------------------
    def _start_section(self, level: int, title: str) -> None:
        self._stack[level] = title
        for lv in [lv for lv in self._stack if lv > level]:
            del self._stack[lv]
        path = " \u203a ".join(self._stack[lv] for lv in sorted(self._stack))
        self._cur = {"level": level, "title": title, "path": path}
        self._body_buf = []

    def _flush_section(self) -> None:
        if self._cur is not None:
            self._cur["text"] = _clean_text("".join(self._body_buf))
            self.sections.append(self._cur)
        self._cur = None
        self._body_buf = []

    def close(self) -> None:
        super().close()
        self._flush_section()


def _clean_text(raw: str) -> str:
    """Collapse all whitespace runs to single spaces and strip. Pure."""
    return re.sub(r"\s+", " ", raw).strip()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _tail_overlap(prev: str, overlap: int) -> str:
    """Last <=overlap chars of prev, starting at a word boundary. Pure."""
    if overlap <= 0 or not prev:
        return ""
    if len(prev) <= overlap:
        return prev
    # First space at/after the overlap window start -> the tail begins on a
    # word boundary and is <= overlap chars long.
    cut = prev.find(" ", len(prev) - overlap)
    return prev[cut + 1:] if cut >= 0 else prev[-overlap:]


def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """
    Split long text into <=max_chars pieces at sentence boundaries where
    possible, with an R58 overlap tail: every piece after the first starts with
    the tail of its predecessor (<= OVERLAP_CHARS, word-aligned) so a fact that
    lands near a split boundary is present in BOTH pieces -- boundary drift from
    manual edits can no longer orphan it. Pure. Never returns empty pieces.
    Bounds: a piece is <= max_chars + the coalesce overhead (150), unchanged.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    overlap = min(OVERLAP_CHARS, max_chars // 4)
    budget = max_chars - overlap
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: List[str] = []
    buf = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        # A single sentence longer than the budget: hard-split at word boundary.
        while len(sent) > budget:
            cut = sent.rfind(" ", 0, budget)
            if cut <= 0:
                cut = budget
            piece = sent[:cut].strip()
            if piece:
                pieces.append(piece)
            sent = sent[cut:].strip()
        if not sent:
            continue
        candidate = f"{buf} {sent}".strip() if buf else sent
        if len(candidate) <= budget:
            buf = candidate
        else:
            if buf:
                pieces.append(buf)
            buf = sent
    if buf:
        pieces.append(buf)
    pieces = _coalesce_short(pieces, budget)
    if overlap > 0 and len(pieces) > 1:
        with_tail = [pieces[0]]
        for i in range(1, len(pieces)):
            tail = _tail_overlap(pieces[i - 1], overlap)
            with_tail.append(f"{tail} {pieces[i]}".strip() if tail else pieces[i])
        pieces = with_tail
    return pieces


def _coalesce_short(pieces: List[str], max_chars: int,
                    min_chars: int = 150) -> List[str]:
    """
    Fold tiny fragments (table/list tails that split out as their own piece)
    into their successor so we never rank an isolated 70-char row above the
    prose it belongs to. Keeps every piece <= max_chars + min_chars. Pure.
    """
    if not pieces:
        return []
    out: List[str] = []
    i = 0
    n = len(pieces)
    while i < n:
        cur = pieces[i]
        # Absorb following short pieces (or fold this short one forward).
        while i + 1 < n and (len(cur) < min_chars or len(pieces[i + 1]) < min_chars):
            merged = f"{cur} {pieces[i + 1]}".strip()
            if len(merged) > max_chars + min_chars and len(cur) >= min_chars:
                break
            cur = merged
            i += 1
        out.append(cur)
        i += 1
    return out


def _chunk_manual(source: str, sections: List[Dict[str, Any]],
                  start_idx: int, prefix: str) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    idx = start_idx
    for sec in sections:
        text = (sec.get("text") or "").strip()
        title = sec.get("title") or "(untitled section)"
        path = sec.get("path") or title
        if not text:
            continue  # empty chunks are never produced
        for piece in _split_text(text):
            chunks.append({
                "chunk_id": f"{prefix}:{idx:03d}",
                "source": source,
                "section": path,
                "title": title,
                "text": piece,
            })
            idx += 1
    return chunks


def _chunk_task_guides(start_idx: int) -> List[Dict[str, Any]]:
    """
    Reuse TASK_GUIDES from ai.assistant_tools as seeded chunks (source
    "task guide"). Imported lazily to keep this module importable standalone.
    """
    try:
        from ai.assistant_tools import TASK_GUIDES
    except Exception as exc:
        _log("knowledge_base.chunk_task_guides", f"could not import TASK_GUIDES: {exc}", {})
        return []
    chunks: List[Dict[str, Any]] = []
    idx = start_idx
    for task_id, guide in TASK_GUIDES.items():
        title = str(guide.get("title") or task_id)
        steps = guide.get("steps") or []
        body = title + ". " + " ".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        text = _clean_text(body)
        if not text:
            continue
        chunks.append({
            "chunk_id": f"task:{idx:03d}",
            "source": "task guide",
            "section": task_id,
            "title": title,
            "text": text,
        })
        idx += 1
    return chunks


# ---------------------------------------------------------------------------
# KB assembly (lazy, cached, thread-safe) + loud-failure handling
# ---------------------------------------------------------------------------

_KB_CACHE: Optional[List[Dict[str, Any]]] = None
_INDEX_CACHE: Optional[Tuple[List[List[str]], Dict[str, int], int, float]] = None
_KB_LOCK = threading.Lock()


def reset_cache() -> None:
    """Drop cached KB + index (test helper). Read-only w.r.t. the filesystem."""
    global _KB_CACHE, _INDEX_CACHE
    with _KB_LOCK:
        _KB_CACHE = None
        _INDEX_CACHE = None


def _parse_manual(source: str, path: Path, prefix: str, start_idx: int) -> List[Dict[str, Any]]:
    """Parse one manual into chunks. Logs loudly and returns [] on any failure."""
    if not path.exists():
        _log("knowledge_base.build", f"manual MISSING: {path}", {"source": source})
        return []
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
        parser = _SectionExtractor()
        parser.feed(html)
        parser.close()
    except Exception as exc:
        _log("knowledge_base.build", f"manual UNPARSEABLE: {path}: {exc!r}", {"source": source})
        return []
    sections = parser.sections
    if not sections:
        _log("knowledge_base.build", f"manual produced ZERO sections: {path}", {"source": source})
        return []
    return _chunk_manual(source, sections, start_idx, prefix)


def _build_kb() -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    prefix_for = {"user manual": "user", "technical manual": "tech"}
    idx = 0
    for source, path in MANUAL_PATHS:
        prefix = prefix_for.get(source, "doc")
        parsed = _parse_manual(source, path, prefix, idx)
        chunks.extend(parsed)
        idx += len(parsed)
    chunks.extend(_chunk_task_guides(idx))
    if not chunks:
        # Loud, honest empty-KB situation -- never a silent failure.
        _log("knowledge_base.build", "KNOWLEDGE BASE IS EMPTY (no manuals, no task guides)", {})
    return chunks


def load_kb() -> List[Dict[str, Any]]:
    """
    Return the full chunk list. Cached + thread-safe + lazy (HTML is parsed on
    first call only). Never raises for a missing manual (logs loudly instead).
    """
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE
    with _KB_LOCK:
        if _KB_CACHE is not None:
            return _KB_CACHE
        _KB_CACHE = _build_kb()
        return _KB_CACHE


def _doc_text(chunk: Dict[str, Any]) -> str:
    return f"{chunk.get('title', '')} {chunk.get('section', '')} {chunk.get('text', '')}"


def _build_index(chunks: Sequence[Dict[str, Any]]) -> Tuple[List[List[str]], Dict[str, int], int, float]:
    """Tokenised index over (title+section+text). Pure (no caching)."""
    docs = [_index_tokens(_doc_text(c)) for c in chunks]
    df: Dict[str, int] = {}
    for toks in docs:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    total_len = sum(len(d) for d in docs)
    avgdl = (total_len / len(docs)) if docs else 0.0
    return docs, df, len(docs), avgdl


def _get_index() -> Tuple[List[List[str]], Dict[str, int], int, float]:
    """Tokenised index over (title+section+text). Cached + thread-safe."""
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    chunks = load_kb()
    with _KB_LOCK:
        if _INDEX_CACHE is not None:
            return _INDEX_CACHE
        _INDEX_CACHE = _build_index(chunks)
        return _INDEX_CACHE


def _rank(query: str, chunks: Sequence[Dict[str, Any]],
          index: Tuple[List[List[str]], Dict[str, int], int, float],
          k: int) -> List[Dict[str, Any]]:
    """
    R58 hybrid ranking core: BM25 + phrase/adjacency bonus + title bonus.
    Deterministic (score desc, then chunk_id). Pure. Shared by search() (the
    cached real-KB path) and rank_chunks() (the testable chunk-list path).
    """
    q_tokens = _index_tokens(query)
    if not q_tokens or not chunks:
        return []
    docs, doc_freq, n_docs, avgdl = index
    if n_docs == 0:
        return []
    q_set = set(q_tokens)
    q_pairs = set(zip(q_tokens, q_tokens[1:]))
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for chunk, doc_tokens in zip(chunks, docs):
        s = bm25_score(q_tokens, doc_tokens, doc_freq, n_docs, avgdl)
        if s <= 0:
            continue
        # Phrase/adjacency bonus: query token pairs adjacent in the doc chunk
        # (order-preserving) are a much stronger relevance signal than scattered
        # term hits. Capped so BM25 still dominates.
        if q_pairs:
            adj = sum(1 for a, b in zip(doc_tokens, doc_tokens[1:]) if (a, b) in q_pairs)
            s += min(PHRASE_BONUS * adj, PHRASE_BONUS_CAP)
        # Title bonus: the heading names the topic -- a query term in the title
        # is worth more than a passing mention in the body. Capped.
        title_hits = len(q_set & set(_index_tokens(str(chunk.get("title") or ""))))
        if title_hits:
            s += min(TITLE_BONUS * title_hits, TITLE_BONUS_CAP)
        scored.append((s, chunk))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("chunk_id", "")))
    results: List[Dict[str, Any]] = []
    for rank, (s, chunk) in enumerate(scored[: max(0, k)], 1):
        results.append({"chunk": chunk, "score": s, "rank": rank})
    return results


def rank_chunks(query: str, chunks: Sequence[Dict[str, Any]], k: int = 3) -> List[Dict[str, Any]]:
    """
    Rank an arbitrary chunk list (the testable entry point). Same semantics as
    search() but without the global cache. Pure w.r.t. the filesystem.
    """
    return _rank(query, chunks, _build_index(chunks), k)


def search(query: str, k: int = 3) -> List[Dict[str, Any]]:
    """
    Hybrid retrieval over the documentation chunks (BM25 + phrase + title).

    Returns [{chunk, score, rank}] sorted by descending score, at most k items.
    Empty / stopword-only query -> [] (never raises). rank is 1-based.
    """
    if not _index_tokens(query):
        return []
    chunks = load_kb()
    return _rank(query, chunks, _get_index(), k)


# ---------------------------------------------------------------------------
# Answer-grade retrieval (guard against weak / single-common-term matches)
# ---------------------------------------------------------------------------

MIN_MATCHED_TERMS = 2  # a citation needs >=2 distinct query terms in the chunk


def matched_term_count(query_tokens: Sequence[str], chunk: Dict[str, Any]) -> int:
    """Distinct query terms present in the chunk (title+section+text). Pure."""
    return len(set(query_tokens) & set(_index_tokens(_doc_text(chunk))))


def retrieve_for_answer(query: str, k: int = 2) -> List[Dict[str, Any]]:
    """
    Chunks worth citing in an answer: they must clear BOTH the BM25 score gate
    (KB_MIN_SCORE) and the matched-term gate (>= MIN_MATCHED_TERMS distinct
    query terms). Weak matches -- e.g. gibberish that happens to share one
    common word like "log" -- are rejected so the orchestrator falls back to
    its honest "template mode" answer instead of over-claiming. Returns at
    most k chunk dicts (the plain chunk dicts, in rank order).

    R58 second pass: if NOTHING clears the strict score gate but a chunk still
    matches >= MIN_MATCHED_TERMS distinct terms at KB_RELAXED_MIN_SCORE, it is
    accepted (the strict gate can under-shoot on short queries whose terms sit
    far apart in a chunk). The matched-term gate is NEVER relaxed -- gibberish
    and single-common-term queries stay rejected in both passes.
    """
    q_tokens = _index_tokens(query)
    if not q_tokens:
        return []

    def _accept(min_score: float) -> List[Dict[str, Any]]:
        accepted: List[Dict[str, Any]] = []
        for r in search(query, k=max(k, 3)):
            if r["score"] < min_score:
                continue
            if matched_term_count(q_tokens, r["chunk"]) < MIN_MATCHED_TERMS:
                continue
            accepted.append(r["chunk"])
            if len(accepted) >= k:
                break
        return accepted

    got = _accept(KB_MIN_SCORE)
    if got:
        return got
    return _accept(KB_RELAXED_MIN_SCORE)


# ---------------------------------------------------------------------------
# R58 relevance-centered snippets (kills the "keywords must sit early in a
# chunk" fragility: the orchestrator shows the best-matching window verbatim).
# ---------------------------------------------------------------------------


def best_snippet(chunk: Dict[str, Any], query: str,
                 limit: int = SNIPPET_TRIM_CHARS) -> str:
    """
    The verbatim window of chunk text (up to limit chars) with the highest
    density of query-term matches -- NOT the first limit chars. Pure.

    Contract:
    - VERBATIM: the result is a substring of the (whitespace-collapsed) chunk
      text, optionally wrapped in "..." ellipses when the window is interior.
      Every word shown is still a quote from the manual (single source of truth).
    - Short chunks (<= limit) are returned whole, unchanged (pre-R58 behaviour).
    - Ties prefer the EARLIEST window, so chunks whose keywords already sit
      early produce exactly the old head-trim answer.
    """
    text = _clean_text(str(chunk.get("text") or ""))
    if not text:
        return ""
    if len(text) <= limit:
        return text
    q_set = set(_index_tokens(query))
    # Word spans as (start, end) char offsets in the collapsed text.
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not spans:
        return ""
    best_score = -1.0
    best_start = 0
    best_end = len(text)
    for i, (start, _s) in enumerate(spans):
        end = start
        hits: List[str] = []
        occ = 0
        j = i
        while j < len(spans):
            w_start, w_end = spans[j]
            if w_end - start > limit:
                break
            end = w_end
            toks = set(_index_tokens(text[w_start:w_end]))
            matched = toks & q_set
            if matched:
                hits.extend(matched)
                occ += 1
            j += 1
        score = float(len(set(hits))) + 0.2 * occ
        if score > best_score:  # ties keep the EARLIEST window (old head-trim)
            best_score = score
            best_start = start
            best_end = end
    if best_score <= 0.0:
        # No query hit anywhere in the text: keep the head window (the
        # pre-R58 behaviour) so unretrieved snippets render unchanged.
        best_start = 0
        best_end = text.find(" ", limit)
        if best_end <= 0:
            best_end = limit
    window = text[best_start:best_end].strip()
    prefix = "..." if best_start > 0 else ""
    suffix = "..." if best_end < len(text) else ""
    return f"{prefix}{window}{suffix}"


# ---------------------------------------------------------------------------
# Golden questions (app/FAQ/how-does-it-work) -- used by tests and Slice F evals
# ---------------------------------------------------------------------------

GOLDEN_QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "password_encryption",
        "question": "What is the password encryption used by the system?",
        "expected_keywords": ["PBKDF2", "password"],
    },
    {
        "id": "renewal_certificate",
        "question": "What is a renewal certificate and how is it customized?",
        "expected_keywords": ["certificate", "renewal"],
    },
    {
        "id": "quota_rules",
        "question": "How does the quota system track officer performance?",
        "expected_keywords": ["quota", "officer"],
    },
    {
        "id": "sync_reconciliation",
        "question": "How does synchronization work between node and master databases?",
        "expected_keywords": ["master", "reconcil"],
    },
    {
        "id": "backup",
        "question": "How do the rolling backups and Google Drive mirroring work?",
        "expected_keywords": ["backup", "drive"],
    },
    {
        "id": "issue_reminders",
        "question": "How do reminders and escalations work for unresolved issues?",
        "expected_keywords": ["reminder", "issue"],
    },
    {
        "id": "state_zone",
        "question": "What is the state-zone mapping?",
        "expected_keywords": ["zone", "state"],
    },
    {
        "id": "scaling",
        "question": "How does the system scale to 50,000 clubs?",
        "expected_keywords": ["50,000", "scale"],
    },
    {
        "id": "dual_layer_restore",
        "question": "What is the dual-layer security challenge for disaster recovery?",
        "expected_keywords": ["security", "restore"],
    },
    {
        "id": "star_rating",
        "question": "How does the employee performance star rating work?",
        "expected_keywords": ["star", "performance"],
    },
    {
        "id": "import_existing_club",
        "question": "What does the user manual say about Import Existing Club and its historical dates?",
        "expected_keywords": ["Import Existing Club", "Date of Approval"],
    },
    {
        "id": "bulk_new_clubs",
        "question": "How does the Bulk Add New Clubs CSV door work?",
        "expected_keywords": ["Bulk Add New Clubs", "dry-run"],
    },
    {
        "id": "counting_rule",
        "question": "How are clubs counted — live versus migrated?",
        "expected_keywords": ["live", "migrated"],
    },
    {
        "id": "two_doors",
        "question": "What is the difference between Bulk Club History Upload and Bulk Add New Clubs?",
        "expected_keywords": ["history", "new work"],
    },
    {
        "id": "hard_reset_handover",
        "question": "What does the Hard Reset for handover do?",
        "expected_keywords": ["Hard Reset", "wipe"],
    },
    {
        "id": "training_library",
        "question": "How do the PPT training materials work?",
        "expected_keywords": ["training", "PPT"],
    },
    {
        "id": "club_register",
        "question": "What is the Admin Club Register and how is it opened?",
        "expected_keywords": ["Club Register", "Total NDLI Clubs"],
    },
    {
        "id": "correct_historical_dates",
        "question": "How does an administrator correct wrongly recorded historical dates?",
        "expected_keywords": ["Correct Historical Dates", "admin-only"],
    },
    # R62 (B5): the three real user-chat failures (2026-10-16) as permanent
    # regression goldens. All three used to be answered with cover-page dumps
    # or live club counts instead of a documentation orientation.
    {
        "id": "r62_manual_map_vague",
        "question": "technical manual",
        "expected_keywords": ["overview", "process flow"],
    },
    {
        "id": "r62_manual_map_full_title",
        "question": "Full NDLI Club Management manual",
        "expected_keywords": ["overview", "manual map"],
    },
    {
        "id": "r62_manual_url_paste",
        "question": "https://anirbanmid.pythonanywhere.com/docs/technical_manual.html",
        "expected_keywords": ["overview", "process flow"],
    },
]
