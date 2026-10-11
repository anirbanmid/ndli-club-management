"""
routes/assistant.py - Robu - the AI assistant surface

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from ai.assistant_core import ask_assistant, log_assistant_issue, nudges_for, record_feedback
from ai.assistant_tools import ToolAuthError, build_context, call_tool
from ai import assistant_audit, assistant_learning
from app import assistant_rate_gate

# path == "/api/assistant/nudges"
def get_assistant_nudges(h, path, query_params):
    session = h._require_session()
    if not session:
        return
    try:
        result = nudges_for(session)
    except Exception as exc:
        # LOUD: a broken nudge check must never look like "no nudges".
        log_assistant_issue("app.assistant_nudges", f"nudges endpoint error: {exc!r}",
                            {"user": session.get("user_id")})
        h._send_error("Nudge check failed (server error).", status=500)
        return
    h._send_json({"success": True, **result})
    return

# path == "/api/assistant/insights"
def get_assistant_insights(h, path, query_params):
    session = h._require_session()
    if not session:
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "insights")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="insights", ok=False)
        h._send_error("Too many requests — try again in %d seconds." % retry_after,
                         status=429)
        return
    try:
        result = call_tool("learning.insights", build_context(session))
    except ToolAuthError as exc:
        h._send_error(str(exc), status=403)
        return
    except Exception as exc:
        # LOUD: a broken learning report must never look like an empty one.
        log_assistant_issue("app.assistant_insights", f"insights endpoint error: {exc!r}",
                            {"user": session.get("user_id")})
        h._send_error("Learning report failed (server error).", status=500)
        return
    h._send_json({"success": True, **result})
    return

# path == "/api/assistant/interactions"
def get_assistant_interactions(h, path, query_params):
    session = h._require_session()
    if not session:
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "interactions")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="interactions", ok=False)
        h._send_error("Too many requests — try again in %d seconds." % retry_after,
                         status=429)
        return
    try:
        limit = int(query_params.get("limit", ["200"])[0] or 200)
    except (TypeError, ValueError):
        limit = 200
    try:
        ctx = build_context(session)
        rows = assistant_learning.read_interactions(ctx, limit=limit)
    except Exception as exc:
        log_assistant_issue("app.assistant_interactions", f"interactions endpoint error: {exc!r}",
                            {"user": session.get("user_id")})
        h._send_error("Interaction log could not be read (server error).", status=500)
        return
    h._send_json({"success": True,
                     "visibility": assistant_learning.log_visibility(),
                     "interactions": rows})
    return

# path == "/api/assistant/audit"
def get_assistant_audit(h, path, query_params):
    session = h._require_session()
    if not session:
        return
    try:
        ctx = build_context(session)
        rows = assistant_audit.read_audit(ctx, limit=200)
    except PermissionError as exc:
        h._send_error(str(exc), status=403)
        return
    except Exception as exc:
        log_assistant_issue("app.assistant_audit", f"audit endpoint error: {exc!r}",
                            {"user": session.get("user_id")})
        h._send_error("Audit trail could not be read (server error).", status=500)
        return
    h._send_json({"success": True, "audit": rows})
    return

# path == "/api/assistant/privacy"
def get_assistant_privacy(h, path, query_params):
    session = h._require_session()
    if not session:
        return
    try:
        ctx = build_context(session)
        mine = assistant_learning.read_interactions(ctx, limit=500)
        prefs = assistant_learning.get_preferences(ctx.user_id)
    except Exception as exc:
        log_assistant_issue("app.assistant_privacy", f"privacy endpoint error: {exc!r}",
                            {"user": session.get("user_id")})
        h._send_error("Privacy summary could not be built (server error).", status=500)
        return
    h._send_json({
        "success": True,
        "user_id": ctx.user_id,
        "visibility": assistant_learning.log_visibility(),
        "question_text_stored": assistant_learning.log_questions_enabled(),
        "retention_days": assistant_learning.RETENTION_DAYS,
        "max_log_bytes": assistant_learning.MAX_LOG_BYTES,
        "your_interaction_rows": len(mine),
        "your_preferences": prefs,
        "forget_endpoint": "/api/assistant/forget",
    })
    return

# path == "/api/assistant/ask"
def post_assistant_ask(h, path, body):
    session = h._require_session()
    if not session:
        return
    question = str(body.get("question", "") or body.get("q", "")).strip()
    if not question:
        h._send_error("question is required.", status=400)
        return
    if len(question) > 1000:
        h._send_error("question is too long (max 1000 characters).", status=400)
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "ask")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="ask", ok=False)
        log_assistant_issue("app.assistant_ask", "rate limit enforced",
                            {"user": session.get("user_id"), "retry": retry_after})
        h._send_error("Too many questions — try again in %d seconds." % retry_after,
                         status=429)
        return
    result = ask_assistant(question, session)
    h._send_json({"success": True, **result})
    return

# path == "/api/assistant/feedback"
def post_assistant_feedback(h, path, body):
    session = h._require_session()
    if not session:
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "feedback")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="feedback", ok=False)
        h._send_error("Too many requests — try again in %d seconds." % retry_after,
                         status=429)
        return
    question = str(body.get("question", "")).strip()
    verdict = str(body.get("verdict", "")).strip().lower()
    comment = str(body.get("comment", "")).strip()
    try:
        ok, err = record_feedback(session, question, verdict, comment)
    except Exception as exc:
        # record_feedback logs its own write failures; this catches
        # validation-layer crashes and stays LOUD (never 200-on-error).
        log_assistant_issue("app.assistant_feedback", f"feedback endpoint error: {exc!r}",
                            {"user": session.get("user_id"), "question": question[:120]})
        h._send_error("Feedback could not be recorded (server error).", status=500)
        return
    if not ok:
        h._send_error(err, status=400)
        return
    h._send_json({"success": True, "message": "Feedback recorded. Thank you."})
    return

# path == "/api/assistant/outcome"
def post_assistant_outcome(h, path, body):
    session = h._require_session()
    if not session:
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "outcome")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="outcome", ok=False)
        h._send_error("Too many requests — try again in %d seconds." % retry_after,
                         status=429)
        return
    event = str(body.get("event", "")).strip()
    question = str(body.get("question", "")).strip()
    detail = str(body.get("detail", "")).strip()
    try:
        ok = assistant_learning.record_outcome(
            build_context(session), event, question=question, detail=detail)
    except ToolAuthError as exc:
        h._send_error(str(exc), status=401)
        return
    except Exception as exc:
        log_assistant_issue("app.assistant_outcome", f"outcome endpoint error: {exc!r}",
                            {"user": session.get("user_id"), "event": event})
        h._send_error("Outcome could not be recorded (server error).", status=500)
        return
    if not ok:
        h._send_error("Unknown outcome event.", status=400)
        return
    h._send_json({"success": True, "message": "Outcome recorded."})
    return

# path == "/api/assistant/preferences"
def post_assistant_preferences(h, path, body):
    session = h._require_session()
    if not session:
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "preferences")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="preferences", ok=False)
        h._send_error("Too many requests — try again in %d seconds." % retry_after,
                         status=429)
        return
    try:
        ctx = build_context(session)
    except ToolAuthError as exc:
        h._send_error(str(exc), status=401)
        return
    key = str(body.get("key", "")).strip()
    if not key:
        h._send_json({"success": True,
                         "preferences": assistant_learning.get_preferences(ctx.user_id)})
        return
    ok, err = assistant_learning.set_preference(
        ctx, key, str(body.get("value", "")))
    if not ok:
        h._send_error(err, status=400)
        return
    h._send_json({"success": True,
                     "preferences": assistant_learning.get_preferences(ctx.user_id)})
    return

# path == "/api/assistant/forget"
def post_assistant_forget(h, path, body):
    session = h._require_session()
    if not session:
        return
    ctx, allowed, retry_after = assistant_rate_gate(session, "forget")
    if not allowed:
        assistant_audit.record_audit("rate_limited", actor=ctx, target="forget", ok=False)
        h._send_error("Too many requests — try again in %d seconds." % retry_after,
                         status=429)
        return
    target = str(body.get("user_id", "") or session.get("user_id", "")).strip()
    try:
        ok, message = assistant_learning.forget_user(build_context(session), target)
    except ToolAuthError as exc:
        h._send_error(str(exc), status=401)
        return
    except Exception as exc:
        log_assistant_issue("app.assistant_forget", f"forget endpoint error: {exc!r}",
                            {"user": session.get("user_id"), "target": target})
        h._send_error("Forget request failed (server error).", status=500)
        return
    if not ok:
        h._send_error(message, status=403)
        return
    h._send_json({"success": True, "message": message})
    return
