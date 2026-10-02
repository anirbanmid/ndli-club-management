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
BM25_K1 = 1.5
BM25_B = 0.75

# Heading levels treated as section boundaries.
_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3}

# Tags whose content is noise (never part of a documentation section).
_SKIP_TAGS = {"script", "style", "head", "nav", "footer", "svg", "noscript", "template", "form"}

# Block-ish tags that force a token boundary (so "<td>Club</td><td>5</td>" -> "Club 5",
# while inline tags like <em>al</em> still glue to their neighbour).
_SEP_TAGS = {"p", "div", "tr", "td", "th", "li", "br", "h1", "h2", "h3", "h4",
             "pre", "table", "section", "article", "ul", "ol", "blockquote", "hr", "figcaption"}


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
        self._heading_level: Optional[int] = None
        self._heading_buf: List[str] = []
        self._body_buf: List[str] = []
        self._stack: Dict[int, str] = {}
        self._cur: Optional[Dict[str, Any]] = None
        self.sections: List[Dict[str, Any]] = []

    # -- tag handling ---------------------------------------------------
    def handle_starttag(self, tag: str, attrs: Any) -> None:
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
        if self._skip_depth:
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


def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """
    Split long text into <=max_chars pieces at sentence boundaries where
    possible. Pure. Never returns empty pieces.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: List[str] = []
    buf = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        # A single sentence longer than the budget: hard-split at word boundary.
        while len(sent) > max_chars:
            cut = sent.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            piece = sent[:cut].strip()
            if piece:
                pieces.append(piece)
            sent = sent[cut:].strip()
        if not sent:
            continue
        candidate = f"{buf} {sent}".strip() if buf else sent
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                pieces.append(buf)
            buf = sent
    if buf:
        pieces.append(buf)
    return _coalesce_short(pieces, max_chars)


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


def _get_index() -> Tuple[List[List[str]], Dict[str, int], int, float]:
    """Tokenised index over (title+section+text). Cached + thread-safe."""
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    chunks = load_kb()
    with _KB_LOCK:
        if _INDEX_CACHE is not None:
            return _INDEX_CACHE
        docs = [tokenize(_doc_text(c)) for c in chunks]
        df: Dict[str, int] = {}
        for toks in docs:
            for term in set(toks):
                df[term] = df.get(term, 0) + 1
        total_len = sum(len(d) for d in docs)
        avgdl = (total_len / len(docs)) if docs else 0.0
        _INDEX_CACHE = (docs, df, len(docs), avgdl)
        return _INDEX_CACHE


def search(query: str, k: int = 3) -> List[Dict[str, Any]]:
    """
    BM25 retrieval over the documentation chunks.

    Returns [{chunk, score, rank}] sorted by descending score, at most k items.
    Empty / stopword-only query -> [] (never raises). rank is 1-based.
    """
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    chunks = load_kb()
    docs, doc_freq, n_docs, avgdl = _get_index()
    if n_docs == 0:
        return []
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for chunk, doc_tokens in zip(chunks, docs):
        s = bm25_score(q_tokens, doc_tokens, doc_freq, n_docs, avgdl)
        if s > 0:
            scored.append((s, chunk))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("chunk_id", "")))
    results: List[Dict[str, Any]] = []
    for rank, (s, chunk) in enumerate(scored[: max(0, k)], 1):
        results.append({"chunk": chunk, "score": s, "rank": rank})
    return results


# ---------------------------------------------------------------------------
# Answer-grade retrieval (guard against weak / single-common-term matches)
# ---------------------------------------------------------------------------

MIN_MATCHED_TERMS = 2  # a citation needs >=2 distinct query terms in the chunk


def matched_term_count(query_tokens: Sequence[str], chunk: Dict[str, Any]) -> int:
    """Distinct query terms present in the chunk (title+section+text). Pure."""
    return len(set(query_tokens) & set(tokenize(_doc_text(chunk))))


def retrieve_for_answer(query: str, k: int = 2) -> List[Dict[str, Any]]:
    """
    Chunks worth citing in an answer: they must clear BOTH the BM25 score gate
    (KB_MIN_SCORE) and the matched-term gate (>= MIN_MATCHED_TERMS distinct
    query terms). Weak matches -- e.g. gibberish that happens to share one
    common word like "log" -- are rejected so the orchestrator falls back to
    its honest "template mode" answer instead of over-claiming. Returns at
    most k chunk dicts (the plain chunk dicts, in rank order).
    """
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    accepted: List[Dict[str, Any]] = []
    for r in search(query, k=max(k, 3)):
        if r["score"] < KB_MIN_SCORE:
            continue
        if matched_term_count(q_tokens, r["chunk"]) < MIN_MATCHED_TERMS:
            continue
        accepted.append(r["chunk"])
        if len(accepted) >= k:
            break
    return accepted


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
]
