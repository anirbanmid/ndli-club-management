"""
NDLI Club Management - AI Assistant Orchestrator (Round 6 · Slice B)

PLAN_AI_ASSISTANT.md §2 (orchestrator) + §3 (role-scoped tools) + Slice B brief.

Responsibilities:
1. Route a natural-language question to exactly one whitelisted read-only tool
   (ai/assistant_tools.call_tool) or to a template/guide answer.
2. Compose the answer in TEMPLATE mode only. Every figure in an answer comes
   from the tool result dict -- never recomputed here -- so the
   numeric-accuracy tripwires in tests/test_assistant_api.py hold by
   construction.
3. Return {answer, sources[], suggestions[]} in the exact shape
   static/js/assistant.js expects.

Slice D LLM SEAM (clearly marked, inert until Slice D):
   `_llm_answer()` is the single swap point. In Slice B it ALWAYS returns None
   (template mode). Slice D replaces its body with the Gemini-adapter call
   (NDLI_ASSISTANT_API_KEY env, >=60s timeout, explicit retry accounting) with
   Groq fallback, and template answers remain the last-resort fallback. The
   seam is exercised by tests (returns None => template path) so the switch
   cannot silently change the response shape.

Hard rules honored here (handoff §2 "amendments" + §6):
- NEVER-TRUST-200 / NO SILENT FAILURES: there is no bare `except: pass`.
  Every caught exception is logged LOUDLY to
  <NDLI_DATA_DIR>/assistant_issues.log via log_assistant_issue().
- Identity comes from the VERIFIED session only (build_context refuses to
  default one; never EMP01).
- The only filesystem writes in the assistant stack live in THIS module:
  the append-only feedback CSV and assistant_issues.log. The tool layer is
  read-only by construction (asserted by tests).
- Retrieved/tool data is rendered as DATA in answers (quoted values), never as
  instructions. Questions are treated as data too; there is no code path that
  executes question content.
"""
import csv
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import DATA_DIR

from ai.assistant_tools import (
    TASK_GUIDES,
    ToolAuthError,
    ToolContext,
    ToolError,
    build_context,
    call_tool,
)
from ai import knowledge_base

# ---------------------------------------------------------------------------
# Loud logging (never-trust-200 discipline)
# ---------------------------------------------------------------------------

_LOG_LOCK = threading.Lock()
_FEEDBACK_LOCK = threading.Lock()

ASSISTANT_ISSUES_LOG = Path(DATA_DIR) / "assistant_issues.log"
ASSISTANT_FEEDBACK_CSV = Path(DATA_DIR) / "assistant_feedback.csv"

FEEDBACK_FIELDS = ("timestamp_utc", "user_id", "role", "verdict", "question", "comment")

_MAX_QUESTION_LEN = 1000
_MAX_COMMENT_LEN = 500


def log_assistant_issue(component: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    """
    Appends one LOUD line to <NDLI_DATA_DIR>/assistant_issues.log.
    Never raises into the caller's happy path; if the log write itself fails,
    the failure is printed to stderr (visible in the PA error log) -- it is
    never swallowed silently.
    """
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        ctx_text = json.dumps(context or {}, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        ctx_text = repr(context)
    line = f"[{stamp}] [{component}] {message} | ctx={ctx_text}\n"
    try:
        ASSISTANT_ISSUES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            with open(ASSISTANT_ISSUES_LOG, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as log_exc:  # loud last resort: stderr, never silent
        import sys
        sys.stderr.write(f"ASSISTANT_ISSUES_LOG WRITE FAILED: {log_exc} :: {line}")


def _llm_answer(question: str, ctx: ToolContext) -> Optional[str]:
    """
    >>> SLICE D LLM SEAM -- SINGLE SWAP POINT <<<

    Slice D (live): Gemini (gemini-flash) -> Groq (llama-3.3-70b) -> None
    (template fallback stays) via ai/llm_gateway. Timeouts >=60s, explicit
    retry accounting, retrieved/tool data rendered as DATA in the prompt
    (never as instructions). Response shape does not change.

    Contract (unchanged): returning None routes the orchestrator to the
    template composers below, byte-compatible with Slice B/C.

    Safety rails enforced here:
    - Kill switch: no NDLI_ASSISTANT_API_KEY -> instant None (zero network).
    - The persona ("about") and greeting paths NEVER touch the network --
      they stay byte-stable template answers.
    - Tool figures are gathered first (read-only, same call_tool as the
      template path). A denial (ToolAuthError) or tool failure keeps the
      honest template answer -- the LLM is never allowed to fabricate data
      the role may not see.
    - Numeric-accuracy post-check: if the LLM answer quotes figures the
      tool/KB source cannot vouch for, the template/tool answer wins
      (we return None) and the conflict is logged LOUDLY.
    - Any gateway crash is logged and degrades to template mode; it can
      never break the assistant or change the response shape.
    """
    from ai import llm_gateway  # lazy: keeps the dependency one-way

    try:
        if llm_gateway.is_disabled():
            return None  # kill switch: template mode, no network, no delay

        intent, params = _route(question)
        if intent in ("greeting", "about"):
            return None  # persona + greeting are template answers; never network

        chunks: Tuple[Dict[str, Any], ...] = ()
        try:
            chunks = tuple(knowledge_base.retrieve_for_answer(question, k=2) or ())
        except Exception as exc:  # loud, never a bare pass
            log_assistant_issue("assistant_core.llm",
                                f"KB retrieval for LLM context FAILED: {exc!r}",
                                {"question": question[:120]})

        figures_text = ""
        if intent not in ("app_help", "fallback", "help_index"):
            tool_name, tool_params, composer = _plan(intent, params, ctx)
            if tool_name:
                try:
                    result = call_tool(tool_name, ctx, **tool_params)
                    figures_text = composer(result, ctx)  # authoritative figures
                except Exception as exc:  # incl. ToolAuthError -> keep honest denial
                    log_assistant_issue(
                        "assistant_core.llm",
                        f"tool figures for LLM unavailable -> template path: {exc}",
                        {"tool": tool_name, "user": ctx.user_id})
                    return None
        if not figures_text and chunks:
            figures_text = "\n".join(str(c.get("text") or "") for c in chunks)

        answer, figures_ok = llm_gateway.ask_llm_checked(
            question, context_chunks=chunks, figures_text=figures_text,
            user_id=ctx.user_id, log=log_assistant_issue)
        if answer and figures_ok:
            return answer
        if answer and not figures_ok:
            # Numeric conflict: prefer the exact template/tool answer.
            log_assistant_issue("assistant_core.llm",
                                "LLM numeric conflict -> preferring template/tool answer",
                                {"question": question[:120], "user": ctx.user_id})
            return None
        return None
    except Exception as exc:  # the gateway must never break the assistant
        log_assistant_issue("assistant_core.llm", f"LLM gateway CRASHED: {exc!r}",
                            {"question": question[:120], "user": ctx.user_id})
        return None


# ---------------------------------------------------------------------------
# Feedback (append-only CSV under the data dir; shipped early so Slice F's
# learning loop can consume a real dataset from day one)
# ---------------------------------------------------------------------------

def record_feedback(session: Dict[str, Any], question: str, verdict: str,
                    comment: str = "") -> Tuple[bool, str]:
    """
    Validates and appends one feedback row to <NDLI_DATA_DIR>/assistant_feedback.csv.
    Returns (ok, error_message). Rows are written with the csv module (proper
    quoting) and the file is append-only.
    """
    clean_question = str(question or "").strip()
    clean_verdict = str(verdict or "").strip().lower()
    clean_comment = str(comment or "").strip()

    if clean_verdict not in ("up", "down"):
        log_assistant_issue("assistant_core.record_feedback", "invalid verdict", {"verdict": verdict})
        return False, "verdict must be 'up' or 'down'."
    if not clean_question:
        log_assistant_issue("assistant_core.record_feedback", "empty question", {})
        return False, "question is required."
    if len(clean_question) > _MAX_QUESTION_LEN:
        log_assistant_issue("assistant_core.record_feedback", "question too long", {"len": len(clean_question)})
        return False, f"question is too long (max {_MAX_QUESTION_LEN} characters)."
    if len(clean_comment) > _MAX_COMMENT_LEN:
        log_assistant_issue("assistant_core.record_feedback", "comment too long", {"len": len(clean_comment)})
        return False, f"comment is too long (max {_MAX_COMMENT_LEN} characters)."

    ctx = build_context(session)  # raises ToolAuthError if session unverified
    row = [
        datetime.now(timezone.utc).isoformat(),
        ctx.user_id,
        ctx.role,
        clean_verdict,
        clean_question,
        clean_comment,
    ]
    try:
        ASSISTANT_FEEDBACK_CSV.parent.mkdir(parents=True, exist_ok=True)
        with _FEEDBACK_LOCK:
            new_file = not ASSISTANT_FEEDBACK_CSV.exists()
            with open(ASSISTANT_FEEDBACK_CSV, "a", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                if new_file:
                    writer.writerow(FEEDBACK_FIELDS)
                writer.writerow(row)
        return True, ""
    except Exception as exc:
        log_assistant_issue("assistant_core.record_feedback", f"feedback write FAILED: {exc}", {"row": row})
        return False, "feedback could not be recorded (server-side write failed)."


# ---------------------------------------------------------------------------
# Question routing (template/rules mode). The question is DATA -- patterns
# only classify it; nothing from it is ever executed or interpolated into a
# shell/code context.
# ---------------------------------------------------------------------------

_EMP_ID_RE = re.compile(r"\b(EMP\d{2,}|ADMIN\d{2,})\b", re.IGNORECASE)
_QUOTED_RE = re.compile(r"[\"'“”‘’«»]([^\"'“”‘’«»]{2,80})[\"'“”‘’«»]")

_GREETING_RE = re.compile(r"^\s*(hi|hii+|hello|hey|namaste|thanks|thank you|ok|okay|bye|good (morning|afternoon|evening))\s*[!.?]*\s*$", re.IGNORECASE)

# "Who are you" / name-origin questions -> Robu persona answer. Checked
# BEFORE the KB path so "who is Robu" never gets scraped from the manuals.
_ABOUT_RE = re.compile(
    r"\bwho (?:are|r|is) (?:you|u|robu)\b|\bwhat(?:'s| is) your name\b|"
    r"\b(?:about|tell me about) (?:you|yourself|robu)\b|\bintroduce yourself\b|"
    r"\bwhat are you\b|\babout robu\b|\bwho made you\b|\bwho created you\b|\byour (?:name|creator|origin)\b",
    re.IGNORECASE)

# Strong "teach me" phrasings -> task guides. Checked BEFORE the data intents
# so "how do I approve a renewal?" returns the guide, not the attention list.
_STRONG_HELP_RE = re.compile(
    r"\bhow (do|does|can|should|to)\b|^\s*how to\b|\bsteps? (to|for)\b|\bguide me\b|"
    r"\bwalk me through\b|\bshow me how\b|\bexplain how\b", re.IGNORECASE)

# Weak "where is it" phrasings -> task guides only if no data intent matched.
_WEAK_HELP_RE = re.compile(r"\bwhere (do|does|can|is|are|to)\b", re.IGNORECASE)

# Slice C: app/FAQ/how-does-it-work questions ("what is X", "how does X work",
# "where can I find X") -> documentation knowledge base with citations.
# Definitional/explanatory phrasings only. The "how do" branch deliberately
# excludes first-person task phrasing ("how do I ..." -> task guide) via a
# negative lookahead for I/we/you/my/our/your.
_APP_HELP_DEF_RE = re.compile(
    r"\bwhat (?:is|are|was|were|does|do)\b|\bwhat's\b|"
    r"\bhow (?:does|do(?!\s+(?:I|we|you|my|our|your)\b)|is|are)\b|"
    r"\bwhere (?:can i find|is the|are the)\b|\bwhat happens (?:when|if)\b",
    re.IGNORECASE)

# First-person / live-data markers: if present the question is a DATA request
# ("what is MY quota", "HOW MANY clubs", "SHOW ME ..."), so it must NOT be
# stolen by the KB path and must route to the read-only data tools instead.
_PERSONAL_DATA_RE = re.compile(
    r"\bmy\b|\bour\b|\bfor\s+(?:me|us|EMP\d+)\b|\bhow many\b|\bshow me\b|\bgive me\b|"
    r"\blist\b|\bcount\b|\btotals?\b|\bsummary\b|\bwhich\b.*\b(?:need|due|overdue|expir)\b|"
    r"\bneed(?:s|ed)?\b.*\b(?:attention|action)\b|\boverdue\b|\bexpiring\b|"
    # live-output verbs: "what does the report recommend" is a DATA fetch, not a
    # conceptual "what is X" question -- so it must route to the report tool.
    r"\brecommend(?:ation|ations|ed|s)?\b|\bsuggest(?:ion|ions|ed|s)?\b",
    re.IGNORECASE)

_EXPLAIN_REPORT_RE = re.compile(
    r"\bexplain\b[^?]*\b(strategic\w*|report|roadmap|recommend\w*|insight\w*|analytics)\b"
    r"|\bwhat does (?:the |this )?(?:strategic |ai )?(?:report|roadmap|recommend\w*) (?:mean|say|show)\b"
    r"|\bwhy (?:do|did|does|is|are)\b[^?]*\brecommend\w*\b"
    r"|\b(walk|talk|guide)\s+me\s+through\b[^?]*\b(report|recommend\w*|insight\w*)\b"
    r"|\bbreak\s+(?:it|this|the report|the recommendations|things)\s+down\b",
    re.IGNORECASE)

_REC_INDEX_RE = re.compile(
    r"\b(?:recommendation|rec|point|item|suggestion)\s*#?\s*(\d+)\b", re.IGNORECASE)

# Section explainers: ordered so "unrepresented" beats "states".
_EXPLAIN_SECTION_RES: List[Tuple[str, re.Pattern]] = [
    ("unrepresented", re.compile(r"\bunrepresented\b", re.IGNORECASE)),
    ("top_states", re.compile(r"\btop states?\b|\bstate (?:spread|coverage|ranking)\b", re.IGNORECASE)),
    ("zone", re.compile(r"\bzone\b", re.IGNORECASE)),
    ("activity", re.compile(r"\bactivit\w*\b", re.IGNORECASE)),
    ("target", re.compile(r"\btarget\b|\bquarterly\b", re.IGNORECASE)),
    ("renewal", re.compile(r"\brenewal\w*\b|\bchurn\b", re.IGNORECASE)),
]

_INTENT_RULES: List[Tuple[str, re.Pattern]] = [
    ("renewals", re.compile(
        r"\brenew(al|als|ed|ing)?\b|\bexpir(e|es|ed|ing|y|ies)?\b|\boverdue\b|\battention window\b", re.IGNORECASE)),
    ("strategy", re.compile(
        r"\bstrateg(y|ic|ies)\b|\binsights?\b|\broadmap\b|\brecommend(ation|ations|ed)?\b|\bstrategic report\b|\banalytics\b", re.IGNORECASE)),
    ("metrics", re.compile(
        r"\bdashboard\b|\bmetrics?\b|\bhow many employees\b|\bemployees (do|does|are)\b|\bstates represented\b|\bpenetration\b|\boverview\b|\bheadline\b", re.IGNORECASE)),
    ("issues", re.compile(
        r"\bissues?\b|\bunresolved\b|\bblock(er|ers|ed|ing)?\b|\bescalat(e|ed|ion|ions)?\b", re.IGNORECASE)),
    ("quota", re.compile(
        r"\bquota\b|\bsupport logs?\b|\bclubs? (have i|did i|i have|approved)\b|\bapproved by me\b|\bmy (count|counts|numbers|totals|clubs)\b|\bi approved\b", re.IGNORECASE)),
    ("activities", re.compile(
        r"\bactivit(y|ies)\b|\blogged?\b|\btraining\b|\bsupport (calls?|sessions?)\b", re.IGNORECASE)),
    ("clubs_search", re.compile(
        r"\b(find|search|look for|look up|show me|tell me about|called|named)\b|\bclubs?\s+(in|at|near|from)\s+\w+", re.IGNORECASE)),
    ("clubs_list", re.compile(
        r"\bclubs?\b|\bzone(s)?\b|\bstate(s)?\b|\bdistribution\b", re.IGNORECASE)),
]

# Ordered: view_renewals first (needs a view-word AND a renew-word, so it does
# not steal plain "renew" questions), then the broader approval/registration rule.
_HELP_TASK_RULES: List[Tuple[str, re.Pattern]] = [
    ("view_renewals", re.compile(r"\b(view|see|show|check|where)\b.*\brenew\w*\b|\brenew\w*\b.*\b(view|see|show|check|where)\b", re.IGNORECASE)),
    ("approve_renewal", re.compile(r"\b(approve|approval|register|registration|renew)\w*\b", re.IGNORECASE)),
    ("log_activity", re.compile(r"\b(log|record|add)\b.*\bactivit\w*\b|\bactivit\w*\b.*\b(log|record|add)\b", re.IGNORECASE)),
    ("create_issue", re.compile(r"\b(raise|create|open|report|file)\b.*\bissue\w*\b|\bissue\w*\b.*\b(raise|create|open|report|file)\b", re.IGNORECASE)),
    ("change_password", re.compile(r"\bpassword\b", re.IGNORECASE)),
]

_SUGGESTIONS_BY_INTENT: Dict[str, List[Dict[str, str]]] = {
    "renewals": [
        {"title": "Renewal attention list", "detail": "See every overdue / expiring club",
         "href": "/portal#renewal-attention", "label": "Open"},
        {"title": "Renewal approval guide", "detail": "Step-by-step: approving a renewal",
         "href": "/portal#help-renewal", "label": "Guide"},
    ],
    "quota": [
        {"title": "My quota dashboard", "detail": "Club approvals and support-log counters",
         "href": "/portal#my-quota", "label": "Open"},
        {"title": "Log a support activity", "detail": "Counters update immediately",
         "href": "/portal#log-activity", "label": "Open"},
    ],
    "activities": [
        {"title": "Activity log", "detail": "Your full activity history",
         "href": "/portal#activities", "label": "Open"},
        {"title": "Quota counters", "detail": "How activities map to your quota",
         "href": "/portal#my-quota", "label": "Open"},
    ],
    "issues": [
        {"title": "Issues screen", "detail": "Open, resolve and track issues",
         "href": "/portal#issues", "label": "Open"},
        {"title": "Raise an issue", "detail": "Report a blocking registration/renewal problem",
         "href": "/portal#new-issue", "label": "Open"},
    ],
    "clubs_list": [
        {"title": "Club search", "detail": "Find a club by institution or ID",
         "href": "/portal#clubs", "label": "Open"},
    ],
    "clubs_search": [
        {"title": "Club details", "detail": "Open the clubs screen for full records",
         "href": "/portal#clubs", "label": "Open"},
        {"title": "Renewal attention", "detail": "Clubs needing renewal action",
         "href": "/portal#renewal-attention", "label": "Open"},
    ],
    "metrics": [
        {"title": "Admin dashboard", "detail": "Headline metrics and charts",
         "href": "/admin#dashboard", "label": "Open"},
        {"title": "Renewal attention", "detail": "Overdue and expiring clubs",
         "href": "/admin#renewal-attention", "label": "Open"},
    ],
    "strategy": [
        {"title": "Strategic report", "detail": "Full AI analytics report",
         "href": "/admin#ai-insights", "label": "Open"},
    ],
    "explain_report": [
        {"title": "Strategic report", "detail": "Full AI analytics report",
         "href": "/admin#ai-insights", "label": "Open"},
        {"title": "Renewal attention", "detail": "Clubs needing renewal action",
         "href": "/portal#renewal-attention", "label": "Open"},
    ],
    "help": [
        {"title": "User manual", "detail": "Full NDLI Club Management manual",
         "href": "/manual", "label": "Open"},
    ],
    "app_help": [
        {"title": "User manual", "detail": "Full NDLI Club Management manual",
         "href": "/manual", "label": "Open"},
        {"title": "Technical manual", "detail": "Architecture, security & engineering reference",
         "href": "/manual", "label": "Open"},
    ],
    "greeting": [],
    "fallback": [
        {"title": "User manual", "detail": "Full NDLI Club Management manual",
         "href": "/manual", "label": "Open"},
        {"title": "Renewal attention", "detail": "Clubs needing renewal action",
         "href": "/portal#renewal-attention", "label": "Open"},
    ],
}


def _help_task(question: str) -> Optional[str]:
    for task_id, task_pattern in _HELP_TASK_RULES:
        if task_pattern.search(question):
            return task_id
    return None


def _route(question: str) -> Tuple[str, Dict[str, Any]]:
    """Classifies the question (DATA) into exactly one intent + params."""
    q = question.strip()
    if _GREETING_RE.match(q):
        return "greeting", {}
    if _ABOUT_RE.search(q):
        return "about", {}
    # Slice E: explain-shaped questions about the strategic report win BEFORE
    # the app-help gate (they are live-data explainers, not manual lookups).
    if _EXPLAIN_REPORT_RE.search(q):
        ep: Dict[str, Any] = {}
        rm = _REC_INDEX_RE.search(q)
        if rm:
            ep["rec_index"] = int(rm.group(1))
        for section, pattern in _EXPLAIN_SECTION_RES:
            if pattern.search(q):
                ep["section"] = section
                break
        return "explain_report", ep
    # Slice C: app/FAQ/how-does-it-work phrasing (definitional/explanatory and
    # NOT a first-person live-data request) -> documentation knowledge base.
    # Checked before the data intents so "what is a renewal certificate" is
    # answered from the manuals (with citations) while "what is my quota"
    # (personal) still routes to the quota tool below.
    if _APP_HELP_DEF_RE.search(q) and not _PERSONAL_DATA_RE.search(q):
        return "app_help", {}
    params: Dict[str, Any] = {}
    m = _EMP_ID_RE.search(q)
    if m:
        params["emp_id"] = m.group(1).upper()

    # Strong help phrasing wins over data intents ("how do I approve a renewal"
    # should teach, not report). Weak phrasing only fires if no data intent did.
    if _STRONG_HELP_RE.search(q):
        task = _help_task(q)
        if task:
            params["task_id"] = task
            return "help", params
        return "help_index", params

    for intent, pattern in _INTENT_RULES:
        if pattern.search(q):
            if intent == "clubs_search":
                query = ""
                qm = _QUOTED_RE.search(q)
                if qm:
                    query = qm.group(1)
                else:
                    tail = re.split(r"\b(find|search|look for|look up|show me|tell me about|called|named)\b",
                                    q, maxsplit=1, flags=re.IGNORECASE)
                    if len(tail) == 3:
                        query = tail[2]
                    else:
                        query = q
                    query = re.sub(r"\b(a|an|the|club|clubs|please|for me|called|named|in|near|at|from)\b",
                                   " ", query, flags=re.IGNORECASE)
                query = re.sub(r"[?.!]+$", "", query).strip(" ,:;-")
                if len(query) >= 2:
                    params["query"] = query
                    params["limit"] = 5
                else:
                    # Not enough signal for a real search -> general club stats.
                    intent = "clubs_list"
            return intent, params

    if _WEAK_HELP_RE.search(q):
        task = _help_task(q)
        if task:
            params["task_id"] = task
            return "help", params
        return "help_index", params

    return "fallback", params


# ---------------------------------------------------------------------------
# Answer composers (TEMPLATE mode). Figures come from tool results only.
# ---------------------------------------------------------------------------

def _src(title: str, detail: str) -> Dict[str, str]:
    return {"title": title, "detail": detail}


def _fmt_activity_types(by_type: Dict[str, int]) -> str:
    if not by_type:
        return "none yet"
    return ", ".join(f"{k} ({v})" for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0])))


def _compose_quota(result: Dict[str, Any], target_emp: str, ctx: ToolContext) -> str:
    if result.get("scope") == "team":
        return (
            f"Team quota snapshot ({result['total_employees']} employees): "
            f"{result['total_clubs_approved']} club approvals and "
            f"{result['total_support_logs']} support logs in total."
        )
    name = result.get("employee_name") or result.get("emp_id") or ctx.user_id
    owner = "You have" if result.get("emp_id", "").upper() == ctx.user_id.upper() else f"{name} ({result.get('emp_id')}) has"
    last = result.get("last_activity_timestamp") or "no activity recorded yet"
    return (
        f"{owner} {result['clubs_approved_count']} club approvals and "
        f"{result['support_logs_count']} support logs. "
        f"Last activity: {last}."
    )


def _compose_renewals(result: Dict[str, Any]) -> str:
    lines = [
        f"Renewal attention over the next {result['window_days']} days (as of {result['today']}): "
        f"{result['total_attention_count']} clubs need attention — "
        f"{result['overdue_count']} overdue, {result['expiring_soon_count']} expiring soon."
    ]
    clubs = result.get("clubs") or []
    for c in clubs[:3]:
        name = c.get("institution_name") or c.get("club_id") or "unknown club"
        rid = c.get("club_id", "")
        # badge_label is the decision module's own wording ("414 days overdue" /
        # "12 days left"); days_overdue is 0 (not None) for expiring clubs, so
        # it must NOT be used to decide "overdue".
        badge = (c.get("badge_label") or c.get("attention_type")
                 or ("overdue" if (c.get("days_overdue") or 0) else "expiring soon"))
        lines.append(f"- {name} ({rid}): {badge}.")
    if len(clubs) > 3:
        lines.append(f"...and {len(clubs) - 3} more in the attention list.")
    return "\n".join(lines)


def _compose_issues(result: Dict[str, Any], ctx: ToolContext) -> str:
    who = "You have" if result.get("emp_id", "").upper() == ctx.user_id.upper() and result.get("emp_id") \
        else f"{result.get('emp_id') or 'Everyone'} has"
    if result.get("scope") == "all":
        who = "Across the organization there are"
    return (
        f"{who} {result['count']} issues — {result['open_count']} open, "
        f"{result['resolved_count']} resolved."
    )


def _compose_activities(result: Dict[str, Any], ctx: ToolContext) -> str:
    scope = result.get("scope", "")
    who = f"Your activity summary ({scope})" if scope == f"employee:{ctx.user_id}" \
        else f"Activity summary ({scope})"
    return (
        f"{who}: {result['total_activities']} activities total, "
        f"{result['priority_count']} flagged priority. "
        f"Breakdown: {_fmt_activity_types(result.get('by_support_type') or {})}. "
        f"Last activity: {result.get('last_activity_timestamp') or 'none recorded yet'}."
    )


def _compose_clubs_list(result: Dict[str, Any]) -> str:
    dist = result.get("zone_distribution") or {}
    dist_text = ", ".join(f"{z}: {n}" for z, n in sorted(dist.items(), key=lambda kv: (-kv[1], kv[0])))
    return (
        f"There are {result['total_clubs']} clubs across {result['states_represented']} states. "
        f"Zone distribution: {dist_text or 'none recorded'}. "
        f"Largest zone: {result['top_zone']} ({result['top_zone_clubs']} clubs)."
    )


def _compose_clubs_search(result: Dict[str, Any], ctx: ToolContext) -> str:
    clubs = result.get("clubs") or []
    if not clubs:
        return f"No clubs matched \"{result['query']}\". Try part of the institution name or the club ID."
    lines = [f"Found {result['count']} club(s) matching \"{result['query']}\":"]
    for c in clubs:
        ren = c.get("renewal_date") or "not computed"
        lines.append(
            f"- {c.get('institution_name') or '(unnamed)'} ({c.get('club_id', '?')}, "
            f"{c.get('state') or '?'}, {c.get('status') or '?'}): renewal {ren}."
        )
    return "\n".join(lines)


def _compose_metrics(result: Dict[str, Any]) -> str:
    return (
        f"Dashboard snapshot: {result['total_clubs']} clubs, {result['total_activities']} activities, "
        f"{result['total_employees']} employees, {result['states_represented']} states represented. "
        f"Renewal attention: {result['renewal_attention_count']} clubs "
        f"({result['overdue_count']} overdue, {result['expiring_soon_count']} expiring soon)."
    )


def _compose_strategy(result: Dict[str, Any]) -> str:
    report = result.get("report") or {}
    m = report.get("metrics") or {}
    recs = report.get("strategic_recommendations") or []
    lines = [
        f"Strategic report snapshot ({report.get('timestamp', '')[:19]} UTC): "
        f"{m.get('total_clubs', 0)} clubs, {m.get('total_activities', 0)} activities, "
        f"{m.get('unrepresented_states_count', 0)} states with zero clubs, "
        f"renewal attention {m.get('renewal_attention_count', 0)} "
        f"({m.get('overdue_count', 0)} overdue, {m.get('expiring_soon_count', 0)} expiring soon)."
    ]
    for r in recs[:3]:
        lines.append(f"- [{r.get('priority', '?')}] {r.get('title', 'Recommendation')}: {r.get('insight', '')}")
    if not recs:
        lines.append("- No outstanding strategic recommendations right now.")
    return "\n".join(lines)


# --- Slice E: strategic report EXPLAINERS -------------------------------

def _report_headline(report: Dict[str, Any]) -> str:
    m = report.get("metrics") or {}
    ts = str(report.get("timestamp", ""))[:19]
    return (
        f"Strategic report, explained ({ts} UTC). "
        f"Headline: {m.get('total_clubs', 0)} clubs, {m.get('total_activities', 0)} activities, "
        f"{m.get('unrepresented_states_count', 0)} states with zero clubs, "
        f"{m.get('renewal_attention_count', 0)} clubs need renewal attention "
        f"({m.get('overdue_count', 0)} overdue, {m.get('expiring_soon_count', 0)} expiring soon)."
    )


def _compose_report_explainer(result: Dict[str, Any], params: Dict[str, Any]) -> str:
    """Plain-language walkthrough of the strategic report: WHAT each
    recommendation means and WHAT to do about it (grounded in the report
    data -- never invented). Supports numbered zoom-in and section explainers."""
    report = result.get("report") or {}
    m = report.get("metrics") or {}
    recs = report.get("strategic_recommendations") or []
    ts = str(report.get("timestamp", ""))[:19]

    idx = params.get("rec_index")
    if idx:
        if 1 <= int(idx) <= len(recs):
            r = recs[int(idx) - 1]
            return "\n".join([
                f"Recommendation {idx} of {len(recs)} \u2014 "
                f"[{r.get('priority', '?')}] {r.get('title', 'Recommendation')} "
                f"(category: {r.get('category', '?')})",
                f"What it means: {r.get('insight', '')}",
                f"What to do: {r.get('action', '')}",
                f"Context ({ts} UTC): {m.get('total_clubs', 0)} clubs, "
                f"{m.get('renewal_attention_count', 0)} need renewal attention.",
            ])
        top = max(len(recs), 1)
        return f"The report has {len(recs)} recommendations right now \u2014 ask for recommendation 1 to {top}."

    section = params.get("section")
    if section == "zone":
        dist = report.get("zone_distribution") or {}
        rows = ", ".join(f"{z}: {n} clubs" for z, n in sorted(dist.items(), key=lambda kv: -kv[1]))
        return (f"Zone distribution \u2014 how the clubs are spread across zones: {rows}. "
                "Zones with few or no clubs are the expansion opportunities the "
                "recommendations target.")
    if section == "activity":
        dist = report.get("activity_distribution") or {}
        rows = ", ".join(f"{a}: {n}" for a, n in sorted(dist.items(), key=lambda kv: -kv[1]))
        return (f"Activity distribution \u2014 what the team has been logging: {rows}. "
                "A healthy mix needs trainings and offline workshops too, not just "
                "remote support \u2014 that is what the capacity-building recommendation is about.")
    if section == "top_states":
        top = report.get("top_states") or []
        rows = ", ".join(f"{s} ({n} clubs)" for s, n in top[:5]) or "none yet"
        return (f"Top states \u2014 strongest club presence: {rows}. These anchor the "
                "footprint; the growth plays target the opposite end (unrepresented states).")
    if section == "unrepresented":
        missing = report.get("unrepresented_states") or []
        rows = ", ".join(missing[:8]) or "none \u2014 every state has a club"
        more = f" (and {len(missing) - 8} more)" if len(missing) > 8 else ""
        return (f"Unrepresented states \u2014 states with zero NDLI clubs: {rows}{more}. "
                "Each one is an outreach opportunity \u2014 that is the core of the "
                "Regional Outreach recommendation.")
    if section == "target":
        return (f"Suggested quarterly target: {report.get('suggested_quarterly_target', 0)} "
                "\u2014 a pacing goal derived from current activity levels, meant to keep "
                "the quarter's growth on trend (not a hard quota per person).")
    if section == "renewal":
        ra = report.get("renewal_attention") or {}
        return (f"Renewal attention window \u2014 as of {ra.get('today', ts[:10])}: "
                f"{ra.get('total_attention_count', 0)} clubs need attention "
                f"({ra.get('overdue_count', 0)} already overdue, "
                f"{ra.get('expiring_soon_count', 0)} expiring soon). Overdue clubs risk "
                "registration churn \u2014 the Retention & Renewal recommendation targets these.")

    lines = [_report_headline(report), "What the report recommends, and why:"]
    if not recs:
        lines.append("- No outstanding strategic recommendations right now.")
    for i, r in enumerate(recs, 1):
        lines.append(f"{i}. [{r.get('priority', '?')}] {r.get('title', 'Recommendation')} "
                     f"(category: {r.get('category', '?')})")
        lines.append(f"   What it means: {r.get('insight', '')}")
        lines.append(f"   What to do: {r.get('action', '')}")
    lines.append("Ask \"explain recommendation 2\" to zoom into one, or ask about a "
                 "part (zone distribution, top states, unrepresented states, "
                 "activity distribution, quarterly target, renewal window).")
    return "\n".join(lines)


# --- Slice E: proactive nudge -------------------------------------------

_NUDGE_PRIORITY = ("renewals", "escalations", "quota")


def _nudge_signature(*ids: str) -> str:
    """Stable signature of the underlying condition: the nudge id changes only
    when the set of flagged items changes, so a dismissed nudge does not come
    back while nothing changed (no nagging)."""
    import hashlib
    return hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:10]


def nudges_for(session: Dict[str, Any]) -> Dict[str, Any]:
    """Slice E: compute at most ONE proactive nudge for the badge.
    Priority: renewals (deadline) > escalations (30+ day unresolved) > quota
    at risk (30+ days inactive). Raises ToolAuthError for unverified sessions
    and ToolError loudly on bad data -- callers must NOT swallow either."""
    ctx = build_context(session)
    signals = call_tool("advisor.nudges", ctx)
    nudge: Optional[Dict[str, Any]] = None

    ren = signals.get("renewals") or {}
    esc = signals.get("escalations") or {}
    quota = signals.get("quota") or {}

    if ren.get("count"):
        nudge = {
            "id": "renewals-" + _nudge_signature(*ren.get("club_ids", [])),
            "kind": "renewals",
            "title": "Renewals need attention",
            "detail": (f"{ren['count']} club(s) are overdue or renewing within 14 days "
                       f"({ren.get('overdue_count', 0)} already overdue)."),
            "href": "/portal#renewal-attention",
            "suggested_question": "which renewals need attention?",
        }
    elif esc.get("count"):
        nudge = {
            "id": "escalations-" + _nudge_signature(*esc.get("issue_ids", [])),
            "kind": "escalations",
            "title": "Issues are escalating",
            "detail": f"{esc['count']} unresolved issue(s) have been open past 30 days.",
            "href": "/portal#issues",
            "suggested_question": "which issues need attention?",
        }
    elif quota.get("count"):
        if ctx.is_admin:
            nudge = {
                "id": "quota-" + _nudge_signature(*quota.get("emp_ids", [])),
                "kind": "quota",
                "title": "Team quota at risk",
                "detail": (f"{quota['count']} employee(s) have logged no activity in 30+ "
                           "days \u2014 their quarterly quota is at risk."),
                "href": "/admin#dashboard",
                "suggested_question": "how is the team quota doing?",
            }
        else:
            nudge = {
                "id": "quota-" + _nudge_signature(ctx.user_id),
                "kind": "quota",
                "title": "Your quota is at risk",
                "detail": "You have logged no activity in 30+ days \u2014 your quarterly quota is at risk.",
                "href": "/portal#my-quota",
                "suggested_question": "how is my quota doing?",
            }

    return {"nudge": nudge, "checked_at": signals.get("today", ""), "scope": signals.get("scope", "")}


def _compose_help(result: Dict[str, Any]) -> str:
    lines = [f"{result['title']}:"]
    for i, step in enumerate(result["steps"], 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)


def _compose_help_index(_result: Dict[str, Any]) -> str:
    guides = ", ".join(sorted(TASK_GUIDES.keys()))
    return (
        "I can walk you through these tasks step by step: "
        f"{guides}. Ask for example \"how do I approve a renewal?\" or \"steps to log an activity\"."
    )


def _compose_fallback(_result: Dict[str, Any]) -> str:
    return (
        "I'm not sure I understand that yet — I'm running in template mode with a fixed set of "
        "answer patterns (the language-model gateway arrives in a later update). I can answer "
        "questions about renewals, quotas, support activities, clubs, issues, dashboard metrics "
        "and the strategic report, and I can walk you through common tasks."
    )


def _trim(text: str, limit: int) -> str:
    """Collapse whitespace and trim to ~limit chars at a word boundary."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return text[:cut].rstrip(" ,;:-") + "…"


def _answer_from_kb(question: str) -> Optional[Dict[str, Any]]:
    """
    Slice C: answer an app/FAQ/how-does-it-work question from the documentation
    knowledge base with INLINE CITATION MARKERS `[1]`, `[2]`.

    Returns {answer, sources, suggestions} or None when the KB has no confident,
    relevant hit (score gate + matched-term gate inside knowledge_base), so the
    caller can fall back to the honest template answer. The chunk text is DATA
    copied from our own manuals and is rendered via ordinary string composition
    (the widget uses textContent) -- never interpreted as instructions. Every
    figure/word shown is a verbatim quote from the chunk (single source of truth);
    nothing is recomputed here.
    """
    try:
        chunks = knowledge_base.retrieve_for_answer(question, k=2)
    except Exception as exc:  # loud, never a bare pass -- then honest fallback
        log_assistant_issue("assistant_core.kb", f"KB retrieval FAILED: {exc!r}",
                            {"question": question[:120]})
        return None
    if not chunks:
        return None
    lines = ["Here's what the NDLI documentation says:"]
    sources: List[Dict[str, str]] = []
    for i, chunk in enumerate(chunks, 1):
        title = str(chunk.get("title") or "documentation")
        text = _trim(str(chunk.get("text") or ""), knowledge_base.SNIPPET_TRIM_CHARS)
        lines.append(f"[{i}] {title}: {text}")
        sources.append(_src(title, f"{chunk.get('source', '')} \u203a {chunk.get('section', '')}"))
    suggestions = [
        {"title": "User manual", "detail": "Full NDLI Club Management manual",
         "href": "/manual", "label": "Open"},
    ]
    return {"answer": "\n".join(lines), "sources": sources, "suggestions": suggestions}


# intent -> (tool name or None, tool params fn, composer)
def _plan(intent: str, params: Dict[str, Any], ctx: ToolContext) -> Tuple[Optional[str], Dict[str, Any], Callable[[Dict[str, Any], ToolContext], str]]:
    # Explicit targets (e.g. "quota for EMP05") are passed through VERBATIM:
    # the tool layer enforces role scoping and raises ToolAuthError for a
    # cross-employee read, which becomes an honest denial -- never a silent
    # swap to the caller's own data. Omitted targets resolve to self (employee)
    # or the team/aggregate (admin) inside the tools themselves.
    if intent == "quota":
        emp = params.get("emp_id")
        return "quota.get", ({"emp_id": emp} if emp else {}), lambda r, c: _compose_quota(r, emp or c.user_id, c)
    if intent == "renewals":
        return "renewals.due", {"window_days": 90}, lambda r, c: _compose_renewals(r)
    if intent == "issues":
        emp = params.get("emp_id")
        return "issues.list", ({"emp_id": emp} if emp else {}), lambda r, c: _compose_issues(r, c)
    if intent == "activities":
        emp = params.get("emp_id")
        return "activities.summary", ({"emp_id": emp} if emp else {}), lambda r, c: _compose_activities(r, c)
    if intent == "clubs_list":
        return "clubs.list", {}, lambda r, c: _compose_clubs_list(r)
    if intent == "clubs_search":
        return "clubs.search", {"query": params.get("query", ""), "limit": params.get("limit", 5)}, \
            lambda r, c: _compose_clubs_search(r, c)
    if intent == "metrics":
        return "metrics.get", {}, lambda r, c: _compose_metrics(r)
    if intent == "strategy":
        return "analytics.strategic_report", {}, lambda r, c: _compose_strategy(r)
    if intent == "explain_report":
        return "analytics.strategic_report", {}, lambda r, c: _compose_report_explainer(r, params)
    if intent == "help":
        return "help.steps", {"task_id": params.get("task_id", "")}, lambda r, c: _compose_help(r)
    return None, {}, lambda r, c: ""


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def ask_assistant(question: str, session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Orchestrates one question. Returns {answer, sources, suggestions}.
    Raises nothing at the caller: every internal failure is logged LOUDLY to
    assistant_issues.log and answered honestly.
    """
    clean_q = str(question or "").strip()

    # LLM seam first (Slice D): None in Slice B -> template mode.
    try:
        ctx = build_context(session)
    except ToolAuthError as exc:
        log_assistant_issue("assistant_core.ask", f"unverified session rejected: {exc}", {"question": clean_q[:120]})
        return {
            "answer": "I couldn't verify your session, so I can't answer with live data. Please sign in again.",
            "sources": [_src("Assistant security gate", "session unverified")],
            "suggestions": [],
        }

    llm_text = _llm_answer(clean_q, ctx)
    if llm_text:
        return {
            "answer": llm_text,
            "sources": [_src("Robu — NDLI Club assistant (language model)", "generated answer")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get("fallback", [])),
        }

    intent, params = _route(clean_q)

    if intent == "greeting":
        return {
            "answer": ("Hello! Ask me about renewals, quotas, support activities, clubs or issues — "
                       "or say \"how do I ...\" for step-by-step guidance."),
            "sources": [_src("Robu — NDLI Club assistant", "template mode")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get("greeting", [])),
        }

    # Robu persona / name origin (serious professional, per the user's pick).
    if intent == "about":
        return {
            "answer": (
                "I'm Robu, the NDLI Club assistant. I answer questions about your club data — "
                "renewals, quotas, support activities, clubs and issues — and explain how the app "
                "works, using live portal data and the user manual. I'm named after Professor "
                "Shonku's robot from Satyajit Ray's stories: assembled for ₹333 and 7 annas, and "
                "worth considerably more — proof that good help isn't about the budget."
            ),
            "sources": [_src("Robu — name origin",
                             "after Professor Trilokeshwar Shonku's robot (Satyajit Ray, 'Professor Shonku o Robu', Sandesh 1965)")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get("help", [])),
        }

    # Slice C: app/FAQ/how-does-it-work -> documentation KB with citations.
    if intent == "app_help":
        kb = _answer_from_kb(clean_q)
        if kb:
            return kb
        log_assistant_issue("assistant_core.ask", "app_help with no confident KB hit",
                            {"question": clean_q[:200], "user": ctx.user_id})
        return {
            "answer": _compose_fallback({}),
            "sources": [_src("Robu — NDLI Club assistant", "template mode (no matching documentation section)")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get("app_help", [])),
        }

    if intent == "help_index":
        return {
            "answer": _compose_help_index({}),
            "sources": [_src("NDLI user manual", "task guide index")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get("help", [])),
        }

    if intent == "fallback":
        # Slice C: give the documentation KB a chance before the honest
        # template fallback. Weak/gibberish matches are rejected inside the KB
        # (score + matched-term gates) and land here instead.
        kb = _answer_from_kb(clean_q)
        if kb:
            return kb
        log_assistant_issue("assistant_core.ask", "unmatched question (template fallback)",
                            {"question": clean_q[:200], "user": ctx.user_id})
        return {
            "answer": _compose_fallback({}),
            "sources": [_src("Robu — NDLI Club assistant", "template mode (no matching answer pattern)")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get("fallback", [])),
        }

    tool_name, tool_params, composer = _plan(intent, params, ctx)
    try:
        result = call_tool(tool_name, ctx, **tool_params)
    except ToolAuthError as exc:
        log_assistant_issue("assistant_core.ask", f"role-scope denial via tool: {exc}",
                            {"tool": tool_name, "user": ctx.user_id, "question": clean_q[:120]})
        return {
            "answer": ("That information isn't available for your role — this data is visible to "
                       "administrators only (the same rule as the portal screens)."),
            "sources": [_src("Assistant access control", f"{tool_name} denied for role {ctx.role}")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get(intent, [])),
        }
    except ToolError as exc:
        log_assistant_issue("assistant_core.ask", f"tool failure: {exc}",
                            {"tool": tool_name, "params": tool_params, "question": clean_q[:120]})
        return {
            "answer": ("I couldn't compute that right now — the data lookup failed on the server. "
                       "The failure has been logged; please try again shortly."),
            "sources": [_src("Assistant tool layer", f"{tool_name} failed (logged)")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get(intent, [])),
        }
    except Exception as exc:  # unexpected -- still loud, never a bare pass
        log_assistant_issue("assistant_core.ask", f"UNEXPECTED tool error: {exc!r}",
                            {"tool": tool_name, "params": tool_params, "question": clean_q[:120]})
        return {
            "answer": ("I hit an unexpected error while looking that up. It has been logged for review — "
                       "please try again shortly."),
            "sources": [_src("Assistant tool layer", f"{tool_name} crashed (logged)")],
            "suggestions": list(_SUGGESTIONS_BY_INTENT.get(intent, [])),
        }

    answer_text = composer(result, ctx)
    sources = [_src("Live portal data (read-only)", f"{tool_name} · scope {result.get('scope', '?')}")]
    if intent == "strategy":
        sources.append(_src("NDLI analytics engine", "ai/decision_module.py · AIDecisionEngine"))
    if intent == "help":
        sources = [_src("NDLI task guide", f"help.steps · {params.get('task_id', '')}")]

    return {
        "answer": answer_text,
        "sources": sources,
        "suggestions": [dict(s) for s in _SUGGESTIONS_BY_INTENT.get(intent, [])],
    }
