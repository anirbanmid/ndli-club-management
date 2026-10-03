"""
NDLI Club Management - AI Assistant Read-Only Tool Layer (Round 6 · Slice B)

PLAN_AI_ASSISTANT.md §2 (TOOL LAYER) + §3 (role-scoped by construction) +
§7.6 (tools are read-only whitelisted).

Design rules enforced here (and asserted by tests/test_assistant_api.py):

1. READ-ONLY BY CONSTRUCTION. Every tool only calls CSVEngine.read_all /
   CSVEngine.search / read-only helpers. This module NEVER writes to any CSV.
   The only filesystem write the assistant stack may perform is the append-only
   feedback CSV and the assistant_issues.log, and both live in
   ai/assistant_core.py -- not here. `FORBIDDEN_WRITE_CALLS` lists the CSV write
   APIs and the test suite asserts none of them appear in this module's source.

2. ROLE SCOPING SERVER-SIDE. Every tool receives a ToolContext built from the
   VERIFIED session (AuthService.validate_session result) -- never from client
   input and never defaulted (no hard-coded employee identity):
     - EMPLOYEE -> own data only, plus aggregates the portal already shows
       (master club search is open to every signed-in portal user).
     - ADMIN    -> everything.
   Attempting to cross that line raises ToolAuthError; the assistant core turns
   that into a polite denial, and the attempt is logged to assistant_issues.log.

3. NO SILENT FAILURES. There is no bare `except: pass` in this module. Every
   caught exception is re-raised as ToolError with context so the orchestrator
   can log it LOUDLY to <NDLI_DATA_DIR>/assistant_issues.log.

Tool whitelist (exactly these names, nothing else is reachable):
    clubs.list                    clubs.search
    activities.summary            quota.get
    issues.list                   renewals.due
    metrics.get                   analytics.strategic_report
    help.steps                    advisor.nudges
"""
from typing import Any, Callable, Dict, List, Optional

from config import (
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_USERS_CSV,
)
from db.schemas import (
    CLUB_FIELDS,
    ACTIVITY_FIELDS,
    USER_FIELDS,
)
from db.csv_engine import CSVEngine
from db.issue_manager import IssueManager
from db.sync_engine import SyncEngine, calculate_next_renewal_date, parse_iso_or_date
from ai.decision_module import AIDecisionEngine

# ---------------------------------------------------------------------------
# Errors (never swallowed -- the orchestrator logs every one of them)
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base error for assistant tool failures (bad input, missing data, IO)."""


class ToolAuthError(ToolError):
    """The verified session may not see the requested data (role scoping)."""


# ---------------------------------------------------------------------------
# Verified-session context (identity comes from the session ONLY)
# ---------------------------------------------------------------------------


class ToolContext:
    """Role context derived strictly from an authenticated session dict."""

    def __init__(self, user_id: str, role: str, full_name: str = "", zone: str = ""):
        self.user_id = user_id
        self.role = role
        self.full_name = full_name
        self.zone = zone

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"

    def __repr__(self) -> str:  # debugging aid; no secrets live in this object
        return f"ToolContext(user_id={self.user_id!r}, role={self.role!r})"


def build_context(session: Dict[str, Any]) -> ToolContext:
    """
    Builds a ToolContext from the VERIFIED session returned by
    AuthService.validate_session(). Identity is taken from the session only;
    there is deliberately NO default employee fallback (never EMP01).
    """
    if not isinstance(session, dict):
        raise ToolAuthError("Assistant tools require a verified session dict.")
    user_id = str(session.get("user_id", "") or "").strip().upper()
    role = str(session.get("role", "") or "").strip().upper()
    if not user_id or not role:
        # Loudly refuse rather than guessing an identity.
        raise ToolAuthError(
            "Session is missing a verified identity (user_id/role); refusing to default one."
        )
    return ToolContext(
        user_id=user_id,
        role=role,
        full_name=str(session.get("full_name", "") or ""),
        zone=str(session.get("zone", "") or ""),
    )


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


def _read_master_clubs() -> List[Dict[str, Any]]:
    return CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)


def _read_master_activities() -> List[Dict[str, Any]]:
    return CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)


def _merged_activities(emp_id: str) -> List[Dict[str, Any]]:
    """
    Node + master activity rows for one employee, deduped by activity_id --
    the SAME merge SyncEngine.recompute_and_persist_quota derives support-log
    counts from, but read-only (the sync method persists; this one never does).
    """
    clean_id = emp_id.strip().upper()
    node_path = SyncEngine.get_employee_activities_path(clean_id)
    node_acts = CSVEngine.read_all(node_path, ACTIVITY_FIELDS) if node_path.exists() else []
    master_acts = [a for a in _read_master_activities() if a.get("emp_id", "").strip().upper() == clean_id]
    merged: Dict[str, Dict[str, Any]] = {}
    for a in node_acts + master_acts:
        aid = a.get("activity_id", "").strip()
        if aid and aid not in merged:
            merged[aid] = a
    return list(merged.values())


def derived_quota(emp_id: str) -> Dict[str, Any]:
    """
    READ-ONLY mirror of SyncEngine.recompute_and_persist_quota's derivation:
    identical numbers (same club-ownership and support-log rules), but it never
    touches any CSV write path. Required because the project hard rule for the
    assistant tool layer is "tools must never write to any CSV".
    """
    clean_id = str(emp_id or "").strip().upper()
    if not clean_id:
        raise ToolError("quota.get: emp_id is required.")

    users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    target = next((u for u in users if u.get("id", "").strip().upper() == clean_id), None)

    master_clubs = _read_master_clubs()
    master_club_ids = {
        c.get("club_id", "").strip().upper(): c for c in master_clubs if c.get("club_id")
    }

    approved_club_ids = set()
    node_clubs_path = SyncEngine.get_employee_clubs_path(clean_id)
    if node_clubs_path.exists():
        for c in CSVEngine.read_all(node_clubs_path, CLUB_FIELDS):
            cid = c.get("club_id", "").strip().upper()
            if cid and cid in master_club_ids:
                c_owner = master_club_ids[cid].get("approved_by_emp_id", "").strip().upper()
                if not c_owner or c_owner == clean_id:
                    approved_club_ids.add(cid)
    for c in master_clubs:
        if c.get("approved_by_emp_id", "").strip().upper() == clean_id:
            cid = c.get("club_id", "").strip().upper()
            if cid:
                approved_club_ids.add(cid)

    combined_acts = _merged_activities(clean_id)
    support_logs = 0
    latest_ts = ""
    for a in combined_acts:
        ts = a.get("timestamp", "")
        if ts and ts > latest_ts:
            latest_ts = ts
        stype = a.get("support_type", "").strip()
        aid = a.get("activity_id", "").strip()
        if stype == "Club Approval" or aid.startswith(f"ACT-PRIORITY-{clean_id}"):
            cid = a.get("club_id", "").strip().upper()
            if cid and cid in master_club_ids:
                c_owner = master_club_ids[cid].get("approved_by_emp_id", "").strip().upper()
                if not c_owner or c_owner == clean_id:
                    approved_club_ids.add(cid)
        else:
            support_logs += 1

    return {
        "emp_id": clean_id,
        "employee_name": (target.get("full_name") if target else None) or clean_id,
        "zone": (target.get("zone", "") if target else ""),
        "clubs_approved_count": len(approved_club_ids),
        "support_logs_count": support_logs,
        "last_activity_timestamp": latest_ts,
    }


# ---------------------------------------------------------------------------
# The whitelisted tools (read-only)
# ---------------------------------------------------------------------------


def _clubs_list(ctx: ToolContext, **_params: Any) -> Dict[str, Any]:
    """Aggregate club counts. Aggregate-only data the portal already shows
    to every signed-in user (clubs/search is session-only, not admin-only)."""
    clubs = _read_master_clubs()
    state_counts: Dict[str, int] = {}
    zone_counts: Dict[str, int] = {}
    for c in clubs:
        st = c.get("state", "").strip() or "Unknown"
        zn = c.get("zone", "").strip() or "Unknown"
        state_counts[st] = state_counts.get(st, 0) + 1
        zone_counts[zn] = zone_counts.get(zn, 0) + 1
    top_zone = max(zone_counts.items(), key=lambda kv: kv[1]) if zone_counts else ("", 0)
    return {
        "tool": "clubs.list",
        "scope": "aggregate",
        "total_clubs": len(clubs),
        "states_represented": len([s for s, n in state_counts.items() if n > 0 and s != "Unknown"]),
        "zone_distribution": zone_counts,
        "top_zone": top_zone[0],
        "top_zone_clubs": top_zone[1],
    }


def _clubs_search(ctx: ToolContext, query: str = "", limit: int = 10, **_params: Any) -> Dict[str, Any]:
    """Master club search -- same data surface as GET /api/clubs/search,
    which the portal exposes to every authenticated role."""
    clean_q = str(query or "").strip()
    if not clean_q:
        raise ToolError("clubs.search: query is required.")
    try:
        max_rows = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        raise ToolError("clubs.search: limit must be an integer.")
    results = CSVEngine.search(MASTER_CLUBS_CSV, clean_q, limit=max_rows)
    clubs = []
    for r in results[:max_rows]:
        doa = r.get("date_of_approval", "").strip() or r.get("submission_timestamp", "").strip()
        ren = r.get("renewal_date", "").strip() or r.get("next_renewal_date", "").strip()
        if not ren:
            lrd = r.get("last_renewal_date", "").strip()
            if lrd:
                ren = calculate_next_renewal_date(last_renewal_date=lrd)
            elif doa:
                ren = calculate_next_renewal_date(date_of_approval=doa)
        clubs.append({
            "club_id": r.get("club_id", ""),
            "institution_name": r.get("institution_name", ""),
            "state": r.get("state", ""),
            "zone": r.get("zone", ""),
            "status": r.get("status", ""),
            "renewal_date": ren,
        })
    return {
        "tool": "clubs.search",
        "query": clean_q,
        "count": len(clubs),
        "clubs": clubs,
    }


def _activities_summary(ctx: ToolContext, emp_id: Optional[str] = None, **_params: Any) -> Dict[str, Any]:
    """Activity totals. Employee -> own records only. Admin -> any employee
    or the master aggregate (the same aggregate /api/admin/metrics shows)."""
    if emp_id:
        clean_id = str(emp_id).strip().upper()
        if not ctx.is_admin and clean_id != ctx.user_id:
            raise ToolAuthError(
                f"activities.summary: employee {ctx.user_id} may not view activities of {clean_id}."
            )
        acts = _merged_activities(clean_id)
        scope = f"employee:{clean_id}"
    elif ctx.is_admin:
        acts = _read_master_activities()
        scope = "aggregate"
    else:
        clean_id = ctx.user_id
        acts = _merged_activities(clean_id)
        scope = f"employee:{clean_id}"

    by_type: Dict[str, int] = {}
    priority = 0
    latest_ts = ""
    for a in acts:
        stype = a.get("support_type", "").strip() or "Other"
        by_type[stype] = by_type.get(stype, 0) + 1
        if str(a.get("priority_flag", "")).strip() == "1":
            priority += 1
        ts = a.get("timestamp", "")
        if ts and ts > latest_ts:
            latest_ts = ts
    return {
        "tool": "activities.summary",
        "scope": scope,
        "emp_id": (str(emp_id).strip().upper() if emp_id else ""),
        "total_activities": len(acts),
        "priority_count": priority,
        "by_support_type": by_type,
        "last_activity_timestamp": latest_ts,
    }


def _quota_get(ctx: ToolContext, emp_id: Optional[str] = None, **_params: Any) -> Dict[str, Any]:
    """Quota counters (live-derived, read-only). Employee -> own quota only.
    Admin -> any employee, or the team roll-up when no emp_id is given."""
    if emp_id:
        clean_id = str(emp_id).strip().upper()
        if not ctx.is_admin and clean_id != ctx.user_id:
            raise ToolAuthError(
                f"quota.get: employee {ctx.user_id} may not view the quota of {clean_id}."
            )
        return {"tool": "quota.get", "scope": f"employee:{clean_id}", **derived_quota(clean_id)}

    if not ctx.is_admin:
        # Employee asking without a target always resolves to SELF (from the
        # verified session -- never a defaulted identity).
        return {"tool": "quota.get", "scope": f"employee:{ctx.user_id}", **derived_quota(ctx.user_id)}

    quotas = [derived_quota(u.get("id", "")) for u in CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
              if u.get("role") == "EMPLOYEE" and u.get("id", "")]
    return {
        "tool": "quota.get",
        "scope": "team",
        "total_employees": len(quotas),
        "total_clubs_approved": sum(q["clubs_approved_count"] for q in quotas),
        "total_support_logs": sum(q["support_logs_count"] for q in quotas),
        "quotas": quotas,
    }


def _issues_list(ctx: ToolContext, emp_id: Optional[str] = None, status: Optional[str] = None,
                 **_params: Any) -> Dict[str, Any]:
    """Unresolved-issue tracker. Employee -> own issues only (emp_id is forced
    to SELF regardless of what was asked). Admin -> any employee / all."""
    target = str(emp_id).strip().upper() if emp_id else ""
    if not ctx.is_admin:
        if target and target != ctx.user_id:
            raise ToolAuthError(
                f"issues.list: employee {ctx.user_id} may not view issues of {target}."
            )
        target = ctx.user_id
    issues = IssueManager.get_issues(emp_id=target or None, status=str(status).strip() or None)
    open_count = sum(1 for i in issues if i.get("status", "").strip().lower() != "resolved")
    return {
        "tool": "issues.list",
        "scope": f"employee:{target}" if target else "all",
        "emp_id": target,
        "count": len(issues),
        "open_count": open_count,
        "resolved_count": len(issues) - open_count,
        "issues": issues,
    }


def _renewals_due(ctx: ToolContext, window_days: int = 90, **_params: Any) -> Dict[str, Any]:
    """Renewal attention window (overdue + expiring). Employee -> only clubs
    they approved. Admin -> every club (master + employee nodes, as the admin
    portal dashboard shows)."""
    try:
        window = max(1, min(int(window_days), 365))
    except (TypeError, ValueError):
        raise ToolError("renewals.due: window_days must be an integer.")
    if ctx.is_admin:
        attention = AIDecisionEngine.get_renewal_attention_data()
    else:
        my_clubs = [c for c in _read_master_clubs()
                    if c.get("approved_by_emp_id", "").strip().upper() == ctx.user_id]
        attention = AIDecisionEngine.get_renewal_attention_data(clubs=my_clubs)
    return {
        "tool": "renewals.due",
        "scope": "all" if ctx.is_admin else f"employee:{ctx.user_id}",
        "window_days": window,
        "today": attention.get("today", ""),
        "total_attention_count": attention.get("total_attention_count", 0),
        "overdue_count": attention.get("overdue_count", 0),
        "expiring_soon_count": attention.get("expiring_soon_count", 0),
        "clubs": attention.get("clubs", []),
    }


def _metrics_get(ctx: ToolContext, **_params: Any) -> Dict[str, Any]:
    """Headline dashboard metrics. ADMIN ONLY -- identical access rule to
    GET /api/admin/metrics (the portal never shows these to employees)."""
    if not ctx.is_admin:
        raise ToolAuthError("metrics.get: dashboard metrics are admin-only (same as /api/admin/metrics).")

    clubs = _read_master_clubs()
    activities = _read_master_activities()
    users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    state_counts: Dict[str, int] = {}
    zone_counts: Dict[str, int] = {}
    for c in clubs:
        st = c.get("state", "").strip() or "Unknown"
        zn = c.get("zone", "").strip() or "Unknown"
        state_counts[st] = state_counts.get(st, 0) + 1
        zone_counts[zn] = zone_counts.get(zn, 0) + 1
    attention = AIDecisionEngine.get_renewal_attention_data()
    return {
        "tool": "metrics.get",
        "scope": "aggregate",
        "total_clubs": len(clubs),
        "total_activities": len(activities),
        "total_employees": sum(1 for u in users if u.get("role") == "EMPLOYEE"),
        "states_represented": len([s for s, n in state_counts.items() if n > 0 and s != "Unknown"]),
        "renewal_attention_count": attention.get("total_attention_count", 0),
        "overdue_count": attention.get("overdue_count", 0),
        "expiring_soon_count": attention.get("expiring_soon_count", 0),
        "zone_distribution": zone_counts,
    }


def _analytics_strategic_report(ctx: ToolContext, **_params: Any) -> Dict[str, Any]:
    """Strategic report -- thin wrapper over the existing AIDecisionEngine.
    ADMIN ONLY (mirrors GET /api/admin/ai-insights exactly)."""
    if not ctx.is_admin:
        raise ToolAuthError("analytics.strategic_report: the strategic report is admin-only (same as /api/admin/ai-insights).")
    report = AIDecisionEngine.generate_strategic_report()
    return {"tool": "analytics.strategic_report", "scope": "aggregate", "report": report}


# Journey guidance: curated step-by-step task guides (Slice C/E extend this
# into the knowledge base; the numbers below are process steps rendered as
# bullets, not data figures).
TASK_GUIDES: Dict[str, Dict[str, Any]] = {
    "approve_renewal": {
        "title": "How to approve a club registration renewal",
        "steps": [
            "Open the club in the Clubs screen (search by institution name or club ID).",
            "Check the current renewal date and the officer contact emails are up to date.",
            "Use the Renew action on the club row and confirm the new renewal date.",
            "The certificate engine picks up the new date; download it from the club details view.",
        ],
    },
    "log_activity": {
        "title": "How to log a support activity",
        "steps": [
            "Go to the Activities screen and open the log form.",
            "Pick the support type (phone/remote help, ticket closure, online or offline training).",
            "Link the club if the activity is about a specific club, add notes, and save.",
            "Your quota counters update immediately on your dashboard.",
        ],
    },
    "create_issue": {
        "title": "How to raise an unresolved issue",
        "steps": [
            "Open the Issues screen from your dashboard.",
            "Create a new issue against the club, describing what is blocking registration or renewal.",
            "The reminder schedule starts automatically for both you and the admin desk.",
            "When it is fixed, resolve the issue with a short resolution note.",
        ],
    },
    "change_password": {
        "title": "How to change your password",
        "steps": [
            "Open the account menu and choose Change Password.",
            "Enter your current password (this proves the account is yours).",
            "Choose a new password of at least eight characters and save.",
            "Sign in again with the new password on your next session.",
        ],
    },
    "view_renewals": {
        "title": "Where to see renewals that need attention",
        "steps": [
            "Open the dashboard; the renewal attention panel lists overdue and expiring clubs.",
            "Overdue clubs are sorted most-overdue first; expiring clubs are sorted soonest first.",
            "Act on the club row to renew, or raise an issue if the institution is unresponsive.",
        ],
    },
}


def _help_steps(ctx: ToolContext, task_id: str = "", **_params: Any) -> Dict[str, Any]:
    """Step-by-step journey guidance for a known task id (both roles)."""
    clean_id = str(task_id or "").strip().lower()
    guide = TASK_GUIDES.get(clean_id)
    if not guide:
        raise ToolError(
            f"help.steps: unknown task_id {task_id!r}. Known tasks: {', '.join(sorted(TASK_GUIDES))}."
        )
    return {
        "tool": "help.steps",
        "scope": "static",
        "task_id": clean_id,
        "title": guide["title"],
        "steps": list(guide["steps"]),
    }


# ---------------------------------------------------------------------------
# Slice E — proactive nudge signals
# ---------------------------------------------------------------------------

# Renewals inside this window (or already overdue) trigger the nudge.
NUDGE_RENEWAL_WINDOW_DAYS = 14
# No logged activity for this long => "quota at risk".
NUDGE_STALE_ACTIVITY_DAYS = 30


def _advisor_nudges(ctx: ToolContext, **_params: Any) -> Dict[str, Any]:
    """Proactive-nudge RAW signals (Slice E). Employee -> own clubs / own
    issues / own quota only. Admin -> org-wide. Read-only. Priority selection
    and wording live in assistant_core.nudges_for().

    Signals:
      renewals   — clubs overdue, or renewing within NUDGE_RENEWAL_WINDOW_DAYS
      escalations — unresolved issues past their 30-day admin reminder date
      quota      — employees with no logged activity in 30+ days
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    today = now.date()

    # 1. Renewal risk (same role scoping as renewals.due).
    if ctx.is_admin:
        attention = AIDecisionEngine.get_renewal_attention_data()
    else:
        my_clubs = [c for c in _read_master_clubs()
                    if c.get("approved_by_emp_id", "").strip().upper() == ctx.user_id]
        attention = AIDecisionEngine.get_renewal_attention_data(clubs=my_clubs)
    renewal_clubs = []
    for c in attention.get("clubs", []):
        # SEMANTICS (verified against get_renewal_attention_data output):
        # "Overdue" rows carry days_overdue > 0 and days_left == 0; "Expiring
        # Soon" rows carry days_overdue == 0 (NOT None!) and days_left > 0.
        # So overdue must be detected via attention_type / days_overdue > 0.
        atype = str(c.get("attention_type", "")).strip().lower()
        days_overdue = c.get("days_overdue")
        days_left = c.get("days_left")
        try:
            is_overdue = atype == "overdue" or (
                isinstance(days_overdue, (int, float)) and days_overdue > 0)
            soon = (not is_overdue) and days_left is not None \
                and int(days_left) <= NUDGE_RENEWAL_WINDOW_DAYS
        except (TypeError, ValueError):
            raise ToolError(f"advisor.nudges: unparseable days_left {days_left!r} in {c.get('club_id')}")
        if is_overdue or soon:
            c = dict(c)
            c["_nudge_overdue"] = is_overdue
            renewal_clubs.append(c)

    # 2. Escalations: unresolved issues past their 30-day admin reminder date.
    issues = IssueManager.get_issues(emp_id=None if ctx.is_admin else ctx.user_id)
    escalations = []
    for i in issues:
        if str(i.get("status", "")).strip().lower() == "resolved":
            continue
        due_raw = str(i.get("admin_reminder_due_at", "")).strip()
        if not due_raw:
            continue
        due_date = parse_iso_or_date(due_raw)
        if due_date is None:
            raise ToolError(
                f"advisor.nudges: unparseable admin_reminder_due_at {due_raw!r} in {i.get('issue_id')}")
        if due_date <= today:
            escalations.append(i)

    # 3. Quota at risk: no logged activity in NUDGE_STALE_ACTIVITY_DAYS days.
    if ctx.is_admin:
        emp_ids = [u.get("id", "").strip().upper()
                   for u in CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
                   if u.get("role") == "EMPLOYEE" and u.get("id", "")]
    else:
        emp_ids = [ctx.user_id]
    stale = []
    for eid in emp_ids:
        q = derived_quota(eid)
        ts = str(q.get("last_activity_timestamp", "")).strip()
        is_stale = True
        if ts:
            last_date = parse_iso_or_date(ts)
            if last_date is None:
                raise ToolError(
                    f"advisor.nudges: unparseable last_activity_timestamp {ts!r} for {eid}")
            is_stale = (today - last_date).days >= NUDGE_STALE_ACTIVITY_DAYS
        if is_stale:
            stale.append({"emp_id": eid, "employee_name": q.get("employee_name", "") or eid})

    return {
        "tool": "advisor.nudges",
        "scope": "all" if ctx.is_admin else f"employee:{ctx.user_id}",
        "today": today.isoformat(),
        "renewals": {
            "count": len(renewal_clubs),
            "overdue_count": sum(1 for c in renewal_clubs if c.get("_nudge_overdue")),
            "club_ids": sorted({c.get("club_id", "") for c in renewal_clubs if c.get("club_id")}),
            "clubs": renewal_clubs[:3],
        },
        "escalations": {
            "count": len(escalations),
            "issue_ids": sorted({i.get("issue_id", "") for i in escalations if i.get("issue_id")}),
            "issues": escalations[:3],
        },
        "quota": {
            "count": len(stale),
            "emp_ids": sorted(s["emp_id"] for s in stale),
            "employees": stale[:3],
        },
    }


# ---------------------------------------------------------------------------
# Registry + single entry point
# ---------------------------------------------------------------------------

# The whitelisted, read-only tool surface. NOTHING outside this dict is
# reachable through AssistantTools.call().
TOOL_WHITELIST: Dict[str, Callable[..., Dict[str, Any]]] = {
    "clubs.list": _clubs_list,
    "clubs.search": _clubs_search,
    "activities.summary": _activities_summary,
    "quota.get": _quota_get,
    "issues.list": _issues_list,
    "renewals.due": _renewals_due,
    "metrics.get": _metrics_get,
    "analytics.strategic_report": _analytics_strategic_report,
    "help.steps": _help_steps,
    "advisor.nudges": _advisor_nudges,
}

TOOL_NAMES = frozenset(TOOL_WHITELIST.keys())

# CSV / filesystem write APIs that must NEVER appear in this module's source.
# tests/test_assistant_api.py asserts exactly this (read-only by construction).
FORBIDDEN_WRITE_CALLS = (
    "write_all",
    "upsert_row",
    "append_row",
    "delete_row",
    "delete_club",
    "recompute_and_persist_quota",
    "ensure_file",
    "shutil",
    "os.remove",
    ".unlink(",
    'open(..., "w"',
)


def call_tool(name: str, ctx: ToolContext, **params: Any) -> Dict[str, Any]:
    """
    The ONLY entry point into the tool layer. Unknown tool names are rejected
    before any lookup; every call is authorized inside the tool itself.
    """
    clean_name = str(name or "").strip()
    if clean_name not in TOOL_WHITELIST:
        raise ToolError(f"Unknown or non-whitelisted tool: {name!r}. Allowed: {sorted(TOOL_NAMES)}.")
    if not isinstance(ctx, ToolContext):
        raise ToolAuthError("call_tool requires a ToolContext built from a verified session.")
    return TOOL_WHITELIST[clean_name](ctx, **params)
