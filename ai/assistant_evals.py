"""
NDLI Club Management - Golden-Question Eval Harness (Round 6 · Slice F)

ai/knowledge_base.py keeps GOLDEN_QUESTIONS ("used by tests and Slice F evals"):
real questions whose answers must keep covering the expected keywords. Slice C
wired them through the HTTP API tests; this module makes the SAME check
RUNNABLE OUTSIDE a server, so a human can score Robu after every manual/KB
change. That is the honest half of Slice F's learning loop:

    data (feedback CSV) -> report -> human fixes the docs -> these evals prove it.

Design rules (same discipline as the rest of the assistant stack):
1. READ-ONLY. This module never writes to any data file or CSV. It asks
   ai.assistant_core.ask_assistant() and scores the returned text.
2. DETERMINISTIC GATE. By default the LLM seam (_llm_answer) is forced OFF, so
   the score reflects template + KB quality only and cannot drift between runs.
   use_llm=True scores the live path (providers + template fallback) instead.
3. NO SILENT FAILURES. A question that raises is recorded as FAILED with the
   exception repr -- never skipped and never counted as passed.
4. The eval identity is synthetic and LOCAL. This is a developer/host-side CLI
   run by someone who already has shell access to the data dir; it never serves
   a request, never authenticates anyone and never becomes an API surface.
"""
from typing import Any, Callable, Dict, List, Optional

from ai.knowledge_base import GOLDEN_QUESTIONS

# Synthetic context for the offline harness only (see module docstring #4).
EVAL_SESSION: Dict[str, Any] = {
    "user_id": "EVAL",
    "role": "ADMIN",
    "full_name": "Slice F eval harness",
    "zone": "",
}

AnswerFn = Callable[[str], Any]


def _answer_text(question: str, use_llm: bool = False) -> str:
    """
    Runs one question through the real orchestrator and returns the answer text.
    Template/KB mode by default (LLM seam forced to return None).
    """
    from ai import assistant_core

    if use_llm:
        result = assistant_core.ask_assistant(question, dict(EVAL_SESSION))
        return str(result.get("answer", "") or "")

    original_seam = assistant_core._llm_answer
    assistant_core._llm_answer = lambda q, ctx: None
    try:
        result = assistant_core.ask_assistant(question, dict(EVAL_SESSION))
    finally:
        assistant_core._llm_answer = original_seam
    return str(result.get("answer", "") or "")


def _score_one(golden: Dict[str, Any], answer_fn: AnswerFn) -> Dict[str, Any]:
    gid = str(golden.get("id", "") or "")
    question = str(golden.get("question", "") or "")
    keywords = [str(k) for k in golden.get("expected_keywords", []) or []]
    entry: Dict[str, Any] = {
        "id": gid,
        "question": question,
        "passed": False,
        "missing_keywords": [],
        "error": "",
        "answer_preview": "",
    }
    if not question:
        entry["error"] = "golden question is empty"
        return entry
    try:
        raw = answer_fn(question)
    except Exception as exc:  # loud: the failure IS the report
        entry["error"] = repr(exc)
        return entry
    answer = str(raw.get("answer", "") if isinstance(raw, dict) else raw or "")
    entry["answer_preview"] = answer[:160]
    hay = answer.lower()
    missing = [kw for kw in keywords if kw.lower() not in hay]
    entry["missing_keywords"] = missing
    entry["passed"] = bool(answer.strip()) and not missing
    return entry


def run_evals(goldens: Optional[List[Dict[str, Any]]] = None,
              use_llm: bool = False,
              answer_fn: Optional[AnswerFn] = None) -> Dict[str, Any]:
    """
    Scores every golden question. Returns
    {passed, total, pass_rate, use_llm, results[]}.
    """
    items = list(goldens if goldens is not None else GOLDEN_QUESTIONS)
    fn: AnswerFn = answer_fn if answer_fn is not None else (
        (lambda q: _answer_text(q, use_llm=True)) if use_llm else
        (lambda q: _answer_text(q, use_llm=False))
    )
    results = [_score_one(g, fn) for g in items]
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    return {
        "passed": passed,
        "total": total,
        "pass_rate": (passed / total) if total else 0.0,
        "use_llm": bool(use_llm) and answer_fn is None,
        "results": results,
    }


def format_report(report: Dict[str, Any]) -> str:
    """Human-readable eval report (plain text; safe to paste anywhere)."""
    lines: List[str] = []
    mode = "live LLM path" if report.get("use_llm") else "template + KB (deterministic)"
    lines.append("Robu golden-question evals -- mode: %s" % mode)
    lines.append("passed %d/%d (%.0f%%)" % (
        report.get("passed", 0), report.get("total", 0),
        100.0 * report.get("pass_rate", 0.0)))
    lines.append("")
    for r in report.get("results", []):
        mark = "PASS" if r.get("passed") else "FAIL"
        lines.append("[%s] %s  %s" % (mark, r.get("id", "?"), r.get("question", "")[:70]))
        if r.get("error"):
            lines.append("       error: %s" % r["error"])
        if r.get("missing_keywords"):
            lines.append("       missing keywords: %s" % ", ".join(r["missing_keywords"]))
    return "\n".join(lines)


def main() -> int:
    """CLI gate: `python3 -m ai.assistant_evals` -> exit 0 all green, 1 otherwise."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Robu golden-question evals")
    parser.add_argument("--llm", action="store_true",
                        help="score the live LLM path instead of deterministic template+KB mode")
    args = parser.parse_args()
    report = run_evals(use_llm=args.llm)
    print(format_report(report))
    return 0 if report["passed"] == report["total"] and report["total"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
