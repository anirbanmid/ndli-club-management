"""
NDLI Club Management - Assistant Learning Store (Round 6 · Slice F)

PLAN_AI_ASSISTANT.md slice F: "Learning loop: interaction log, feedback,
preference memory, outcome signals" (goal line: "learns honestly ... no fake
fine-tuning claims"). HANDOFF_ROUND6_CHATBOT.md §2 decision #5 is LOCKED and
implemented exactly:

    "Learning data: interaction log visible to ALL users (user's explicit call;
     flagged for privacy, reversible by config toggle). Retention 60 days,
     nightly auto-purge, 30MB size cap with oldest-first rotation."

and hard constraint §6.5: "Privacy: retention + 'forget this user' ship WITH
slice F, not after."

This module is the ONLY place in the assistant stack that WRITES learning data.
The orchestrator and the tool layer read through the functions here.

1. APPEND-ONLY in normal operation (interactions + preferences rows are appended,
   never edited). The only rewrites are the two sanctioned maintenance/privacy
   operations: forget_user() (§6.5) and retention enforcement (decision #5).
2. SECRETS NEVER PERSIST: question text and outcome detail pass through
   redact_secrets() and are truncated before storage. No answer text is stored.
3. NO SILENT FAILURES: there is no bare `except: pass`; write failures are logged
   LOUDLY to <NDLI_DATA_DIR>/assistant_issues.log and the caller is told the
   write failed (never a fake success).
4. VISIBILITY IS SERVER-SIDE ONLY. env NDLI_ASSISTANT_LOG_VISIBILITY = all|admin|self
   (default `self`, per the user's Slice F re-confirmation 2026-10-03: each user sees
   only their own rows; administrators retain oversight -- they already see all club
   data and the audit slice needs it). It is NEVER taken from a client request.
5. RETENTION (decision #5): rows older than RETENTION_DAYS are purged and the log
   is rotated oldest-first above MAX_LOG_BYTES. Enforcement is opportunistic at
   write time (cheap header/size probes; full rewrite only when needed), plus a
   callable purge_expired() for a nightly job / manual run.
"""
import csv
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR

# ---------------------------------------------------------------------------
# Loud logging (lazy import of assistant_core to avoid a circular dependency)
# ---------------------------------------------------------------------------

_LOG_LOCK = threading.Lock()
_STORE_LOCK = threading.Lock()


def _log(component: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    try:
        from ai.assistant_core import log_assistant_issue  # lazy: core imports us
        log_assistant_issue(component, message, context)
    except Exception as exc:  # loud last resort: stderr, never silent
        import sys
        sys.stderr.write(f"LEARNING LOG WIRE FAILED ({component}): {exc} :: {message}\n")


# ---------------------------------------------------------------------------
# Storage locations + tuning (HANDOFF §2 decision #5)
# ---------------------------------------------------------------------------

ASSISTANT_INTERACTIONS_CSV = Path(DATA_DIR) / "assistant_interactions.csv"
ASSISTANT_PREFERENCES_CSV = Path(DATA_DIR) / "assistant_preferences.csv"
ASSISTANT_FEEDBACK_CSV = Path(DATA_DIR) / "assistant_feedback.csv"  # owned by assistant_core

INTERACTION_FIELDS = (
    "timestamp_utc", "user_id", "role", "event", "question",
    "intent", "mode", "answered", "latency_ms", "detail",
)
PREFERENCE_FIELDS = ("user_id", "pref_key", "pref_value", "updated_at")

RETENTION_DAYS = 60
MAX_LOG_BYTES = 30 * 1024 * 1024  # 30 MB cap, oldest-first rotation

VISIBILITY_ENV = "NDLI_ASSISTANT_LOG_VISIBILITY"
VISIBILITY_DEFAULT = "self"          # user's Slice F re-confirm (2026-10-03): own rows only
VISIBILITY_MODES = ("all", "admin", "self")

_MAX_QUESTION_CHARS = 240
_MAX_DETAIL_CHARS = 200
_MAX_PREF_KEY = 40
_MAX_PREF_VALUE = 200

EVENT_ASK = "ask"
OUTCOME_EVENTS = ("suggestion_click", "deep_link_open", "nudge_open", "nudge_dismiss")


# ---------------------------------------------------------------------------
# Secret redaction (never persist a credential-shaped fragment)
# ---------------------------------------------------------------------------

_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|relay[_-]?key"
    r"|authorization|bearer|private[_-]?key)\b(\s*[:=]\s*)((?:bearer\s+)?\S+)"
)
_BEARER_RE = re.compile(r"(?i)(?<!\[)\bbearer\s+\S+")


def redact_secrets(text: str) -> str:
    """`password: hunter2` -> `password: [redacted]`; leaves ordinary text alone."""
    cleaned = _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", str(text or ""))
    return _BEARER_RE.sub("bearer [redacted]", cleaned)


def _clip(text: str, limit: int) -> str:
    clean = redact_secrets(text).replace("\r", " ").replace("\n", " ").strip()
    return clean[:limit]


# ---------------------------------------------------------------------------
# Visibility (server-side only; see module docstring #4)
# ---------------------------------------------------------------------------

def log_visibility() -> str:
    raw = str(os.environ.get(VISIBILITY_ENV, "") or "").strip().lower()
    if not raw:
        return VISIBILITY_DEFAULT
    if raw not in VISIBILITY_MODES:
        _log("assistant_learning.visibility",
             f"invalid {VISIBILITY_ENV}={raw!r}; falling back to default",
             {"value": raw, "fallback": VISIBILITY_DEFAULT})
        return VISIBILITY_DEFAULT
    return raw


def _can_read(ctx: Any, row_user_id: str) -> bool:
    """
    Role scoping for one interaction/preference row (server-side).
    `self` = own rows only, with administrative oversight (admins see everything,
    as they already do across the portal).
    """
    mode = log_visibility()
    if mode == "admin":
        return bool(getattr(ctx, "is_admin", False))
    if mode == "self":
        return (bool(getattr(ctx, "is_admin", False))
                or str(getattr(ctx, "user_id", "")) == str(row_user_id))
    return True  # mode == "all": any verified portal user


# ---------------------------------------------------------------------------
# CSV helpers (append-only; rewrites only for retention + forget_user)
# ---------------------------------------------------------------------------

def _append_row(path: Path, fields: Tuple[str, ...], row: List[Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _STORE_LOCK:
            new_file = not path.exists()
            with open(path, "a", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                if new_file:
                    writer.writerow(fields)
                writer.writerow(row)
        return True
    except Exception as exc:
        _log("assistant_learning.write", f"append FAILED: {exc}", {"path": str(path)})
        return False


def _read_rows(path: Path, fields: Tuple[str, ...]) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                rows.append({k: str(raw.get(k, "") or "") for k in fields})
    except Exception as exc:
        _log("assistant_learning.read", f"read FAILED: {exc}", {"path": str(path)})
        raise RuntimeError(f"learning store read failed: {exc}") from exc
    return rows


def _rewrite_rows(path: Path, fields: Tuple[str, ...], rows: List[List[Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(fields)
        writer.writerows(rows)
    tmp.replace(path)


def _parse_ts(stamp: str) -> Optional[datetime]:
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Retention: 60 days + 30 MB oldest-first rotation (locked decision #5)
# ---------------------------------------------------------------------------

def _enforce_retention(path: Path, fields: Tuple[str, ...]) -> None:
    """
    Cheap probes first (file size + first data row's timestamp); the O(n) rewrite
    runs only when something is actually due. Called after every successful write.
    """
    try:
        if not path.exists():
            return
        size = path.stat().st_size
        rotate = size > MAX_LOG_BYTES
        purge_due = False
        if not rotate:
            cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
            with open(path, "r", encoding="utf-8", newline="") as fh:
                fh.readline()  # header
                first = fh.readline()
            if first:
                stamp = next(csv.reader([first]), [""])[0]
                parsed = _parse_ts(stamp)
                purge_due = bool(parsed and parsed < cutoff)
        if not (rotate or purge_due):
            return

        rows = [r for r in _read_rows(path, fields)]
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        kept = [r for r in rows
                if not (parsed := _parse_ts(r.get("timestamp_utc") or r.get("updated_at", ""))) or parsed >= cutoff]
        dropped = len(rows) - len(kept)
        if rotate and len(kept) > 1:
            # Oldest-first rotation: keep the newest half of the cap's worth of rows.
            kept = kept[len(kept) // 2:]
        with _STORE_LOCK:
            _rewrite_rows(path, fields, [[r.get(f, "") for f in fields] for r in kept])
        _log("assistant_learning.retention",
             "retention enforced", {"path": str(path), "dropped": dropped,
                                    "rotated": rotate, "kept": len(kept)})
    except Exception as exc:
        _log("assistant_learning.retention",
             f"retention enforcement FAILED: {exc}", {"path": str(path)})


def purge_expired(now: Optional[datetime] = None) -> Dict[str, int]:
    """
    Explicit maintenance entry point (nightly job / manual):
    `python3 -m ai.assistant_learning --purge`.
    """
    del now  # cutoffs are computed inside the retention pass
    before = {
        "interactions": len(_read_rows(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS)),
        "preferences": len(_read_rows(ASSISTANT_PREFERENCES_CSV, PREFERENCE_FIELDS)),
    }
    _enforce_retention(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS)
    _enforce_retention(ASSISTANT_PREFERENCES_CSV, PREFERENCE_FIELDS)
    after = {
        "interactions": len(_read_rows(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS)),
        "preferences": len(_read_rows(ASSISTANT_PREFERENCES_CSV, PREFERENCE_FIELDS)),
    }
    return {
        "purged_interactions": before["interactions"] - after["interactions"],
        "purged_preferences": before["preferences"] - after["preferences"],
    }


# ---------------------------------------------------------------------------
# Interactions (ask rows + outcome rows in one append-only log)
# ---------------------------------------------------------------------------

def record_interaction(ctx: Any, question: str, intent: str = "", mode: str = "",
                       answered: bool = True, latency_ms: int = 0,
                       event: str = EVENT_ASK, detail: str = "") -> bool:
    """
    Appends one interaction row. Returns False (and logs LOUDLY) on write failure
    -- the caller must never pretend the row was stored.
    """
    user_id = str(getattr(ctx, "user_id", "") or "").strip()
    role = str(getattr(ctx, "role", "") or "").strip()
    if not user_id or not role:
        _log("assistant_learning.record", "refused: unverified identity", {})
        return False
    clean_event = str(event or EVENT_ASK).strip()
    if clean_event != EVENT_ASK and clean_event not in OUTCOME_EVENTS:
        _log("assistant_learning.record", "refused: unknown event", {"event": clean_event})
        return False
    try:
        latency = int(latency_ms or 0)
    except (TypeError, ValueError):
        latency = 0
    row = [
        datetime.now(timezone.utc).isoformat(),
        user_id,
        role,
        clean_event,
        _clip(question, _MAX_QUESTION_CHARS),
        _clip(intent, 60),
        _clip(mode, 40),
        "1" if answered else "0",
        str(max(0, latency)),
        _clip(detail, _MAX_DETAIL_CHARS),
    ]
    ok = _append_row(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS, row)
    if ok:
        _enforce_retention(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS)
    return ok


def record_outcome(ctx: Any, event: str, question: str = "", detail: str = "") -> bool:
    """Outcome signal row (suggestion click / journey followed / nudge action)."""
    if event not in OUTCOME_EVENTS:
        _log("assistant_learning.outcome", "refused: unknown outcome event", {"event": event})
        return False
    return record_interaction(ctx, question=question, intent="outcome", mode="",
                              answered=True, latency_ms=0, event=event, detail=detail)


def read_interactions(ctx: Any, limit: int = 200, event: str = "") -> List[Dict[str, str]]:
    """
    Role-scoped read (visibility mode; see module docstring #4). Read-only.
    Newest first, capped at `limit`.
    """
    rows = _read_rows(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS)
    rows = [r for r in rows if _can_read(ctx, r.get("user_id", ""))]
    if event:
        rows = [r for r in rows if r.get("event") == event]
    rows.reverse()
    return rows[: max(1, min(int(limit or 200), 500))]


# ---------------------------------------------------------------------------
# Preference memory (what Robu remembers about a user -- own rows only)
# ---------------------------------------------------------------------------

def get_preferences(user_id: str) -> Dict[str, str]:
    rows = _read_rows(ASSISTANT_PREFERENCES_CSV, PREFERENCE_FIELDS)
    return {r["pref_key"]: r["pref_value"] for r in rows
            if r.get("user_id") == str(user_id).strip().upper()}


def set_preference(ctx: Any, key: str, value: str) -> Tuple[bool, str]:
    """A user may only set their OWN preferences (identity from the session)."""
    user_id = str(getattr(ctx, "user_id", "") or "").strip().upper()
    clean_key = str(key or "").strip().lower()
    clean_value = _clip(value, _MAX_PREF_VALUE)
    if not user_id:
        return False, "unverified identity."
    if not re.fullmatch(r"[a-z0-9_.-]{1,%d}" % _MAX_PREF_KEY, clean_key):
        return False, "preference key must be 1-40 chars: lowercase letters, digits, . _ -"
    if not clean_value:
        return False, "preference value is required."
    row = [user_id, clean_key, clean_value, datetime.now(timezone.utc).isoformat()]
    if not _append_row(ASSISTANT_PREFERENCES_CSV, PREFERENCE_FIELDS, row):
        return False, "preference could not be stored (server-side write failed)."
    _enforce_retention(ASSISTANT_PREFERENCES_CSV, PREFERENCE_FIELDS)
    return True, ""


# ---------------------------------------------------------------------------
# Feedback view (read-only; the feedback CSV itself is owned by assistant_core)
# ---------------------------------------------------------------------------

FEEDBACK_FIELDS = ("timestamp_utc", "user_id", "role", "verdict", "question", "comment")


def feedback_summary(ctx: Any) -> Dict[str, Any]:
    """
    Aggregates the Slice B feedback dataset (same visibility rule as the
    interaction log). Comments are an ADMIN-only detail; counts and the
    question-level gap list follow the configured visibility mode.
    """
    rows = [r for r in _read_rows(ASSISTANT_FEEDBACK_CSV, FEEDBACK_FIELDS)
            if _can_read(ctx, r.get("user_id", ""))]
    up = sum(1 for r in rows if r.get("verdict") == "up")
    down = len(rows) - up
    down_questions: Dict[str, int] = {}
    for r in rows:
        if r.get("verdict") != "down":
            continue
        key = re.sub(r"\s+", " ", r.get("question", "").strip().lower())[:80]
        if key:
            down_questions[key] = down_questions.get(key, 0) + 1
    summary: Dict[str, Any] = {
        "total": len(rows),
        "up": up,
        "down": down,
        "up_rate": (up / len(rows)) if rows else 0.0,
        "down_questions": [
            {"question": q, "count": c}
            for q, c in sorted(down_questions.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        ],
    }
    if bool(getattr(ctx, "is_admin", False)):
        summary["down_comments"] = [
            {"question": r.get("question", "")[:120], "comment": r.get("comment", "")[:200]}
            for r in rows if r.get("verdict") == "down" and r.get("comment", "").strip()
        ][-5:]
    return summary


# ---------------------------------------------------------------------------
# Learning report data (read-only; feeds the learning.insights tool)
# ---------------------------------------------------------------------------

def interactions_summary(ctx: Any) -> Dict[str, Any]:
    """
    Aggregates the learning data the caller may see. Read-only, role-scoped by
    the same visibility rule as read_interactions().
    """
    rows = [r for r in _read_rows(ASSISTANT_INTERACTIONS_CSV, INTERACTION_FIELDS)
            if _can_read(ctx, r.get("user_id", ""))]
    asks = [r for r in rows if r.get("event") == EVENT_ASK]
    outcomes = [r for r in rows if r.get("event") != EVENT_ASK]

    question_counts: Dict[str, int] = {}
    for r in asks:
        key = re.sub(r"\s+", " ", r.get("question", "").strip().lower())[:80]
        if key:
            question_counts[key] = question_counts.get(key, 0) + 1
    top_questions = sorted(question_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    intent_counts: Dict[str, int] = {}
    for r in asks:
        intent = r.get("intent", "") or "unknown"
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    return {
        "visibility": log_visibility(),
        "total_interactions": len(rows),
        "total_questions": len(asks),
        "total_outcomes": len(outcomes),
        "unanswered": sum(1 for r in asks if r.get("answered") == "0"),
        "unique_users": len({r.get("user_id", "") for r in rows if r.get("user_id")}),
        "top_questions": [{"question": q, "count": c} for q, c in top_questions],
        "intents": dict(sorted(intent_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "outcome_events": dict(sorted(
            ((e, sum(1 for r in outcomes if r.get("event") == e)) for e in OUTCOME_EVENTS),
            key=lambda kv: (-kv[1], kv[0]))),
    }


# ---------------------------------------------------------------------------
# Privacy control (§6.5): "forget this user" -- ships WITH Slice F
# ---------------------------------------------------------------------------

def forget_user(ctx: Any, target_user_id: str) -> Tuple[bool, str]:
    """
    Removes one user's learning data: interactions + preferences + their feedback
    rows. ADMIN may forget anyone; a user may forget themselves. This is the one
    sanctioned rewrite of otherwise append-only files (hard constraint §6.5).
    """
    actor = str(getattr(ctx, "user_id", "") or "").strip().upper()
    target = str(target_user_id or "").strip().upper()
    is_admin = bool(getattr(ctx, "is_admin", False))
    if not actor or not target:
        return False, "a verified identity and a target user are required."
    if not is_admin and actor != target:
        _log("assistant_learning.forget", "role-scope denial",
             {"actor": actor, "target": target})
        return False, "only an administrator may forget another user's data."
    if target.startswith("ADMIN") and not is_admin:
        return False, "only an administrator may forget an administrator's data."

    removed = {"interactions": 0, "preferences": 0, "feedback": 0}
    try:
        with _STORE_LOCK:
            for path, counter in (
                (ASSISTANT_INTERACTIONS_CSV, "interactions"),
                (ASSISTANT_PREFERENCES_CSV, "preferences"),
                (ASSISTANT_FEEDBACK_CSV, "feedback"),
            ):
                if not path.exists():
                    continue
                with open(path, "r", encoding="utf-8", newline="") as fh:
                    rows = list(csv.reader(fh))
                if not rows:
                    continue
                header, body = rows[0], rows[1:]
                try:
                    idx = header.index("user_id")
                except ValueError:
                    _log("assistant_learning.forget", "no user_id column; skipped",
                         {"path": str(path)})
                    continue
                kept = [r for r in body if str(r[idx] if idx < len(r) else "").strip().upper() != target]
                removed[counter] = len(body) - len(kept)
                _rewrite_rows(path, tuple(header), kept)
        _log("assistant_learning.forget", "forget_user completed",
             {"actor": actor, "target": target, **removed})
        return True, (f"Forgot {target}: {removed['interactions']} interaction rows, "
                      f"{removed['preferences']} preference rows, "
                      f"{removed['feedback']} feedback rows removed.")
    except Exception as exc:
        _log("assistant_learning.forget", f"forget_user FAILED: {exc}",
             {"actor": actor, "target": target})
        return False, "forget request failed on the server (see assistant_issues.log)."


# ---------------------------------------------------------------------------
# CLI: `python3 -m ai.assistant_learning --purge`
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Assistant learning store maintenance")
    parser.add_argument("--purge", action="store_true",
                        help="enforce 60-day retention + 30MB rotation now")
    args = parser.parse_args()
    if args.purge:
        result = purge_expired()
        print(f"purge complete: {result}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
