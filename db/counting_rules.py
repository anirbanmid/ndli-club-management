"""
db/counting_rules.py — THE single source of truth for the counting rules.

WHY THIS MODULE EXISTS (roadmap problem #1, R38):

Before R38 the counting rules were expressed independently in at least three
layers: the admin dashboard JS (templates/admin.html renderKPIs / quota card),
the assistant tools (ai/assistant_tools.py), and the quota engine
(db/sync_engine.py recompute_and_persist_quota) — and they drifted once already
(R37 v1: Robu counted register ROWS while the dashboard counted migrated
APPROVALS). Anything expressed twice will disagree twice.

From R38 on, every counting decision is made HERE and only here:

  1. RECORD PROVENANCE — is_imported_record() / split_register_rows():
     a club RECORD is migrated iff record_origin == "imported".
  2. THE HEADLINE — headline(): every club figure is reported as
     "X live + Y migrated club approvals (history) — N in total" where
     live = created through the portal (the only thing counted as new work)
     and migrated = the history BASELINE approvals from the client worksheets
     (db.migration_engine.history_grand_totals). Register rows are reported
     separately — never added to the headline.
  3. EMPLOYEE SPLIT — split_total(): a blended quota total = live + baseline;
     the live half is derived HERE (total - baseline), never in JS or callers.
  4. ACTIVITY BUCKETING — bucket_activity(): 'approval' | 'online' |
     'offline' | 'other' | 'skip'; 'other' is a catch-all so no row can ever
     fall through uncounted (R29v2 rule, moved here from SyncEngine).

Callers (app.py, ai/assistant_tools.py, db/sync_engine.py, and the API fields
templates/admin.html renders) MUST read these functions instead of re-deriving
any of the four rules. tests/test_counting_rules.py enforces this with
cross-surface sameness invariants.

Read-only module: it never writes to the data store.
"""
from typing import Any, Dict, List, Optional, Tuple

from db.csv_engine import CSVEngine
from db.migration_engine import (
    MIGRATION_HISTORY_FIELDS,
    MASTER_HISTORY_CSV,
    history_grand_totals,
    _parse_count,
)

# The one provenance marker: club rows written by the bulk club-history import
# (R24/R30/R31). PA rows map 1:1 to worksheet lines.
IMPORTED_MARKER = "imported"


# ---------------------------------------------------------------------------
# 1. Record provenance
# ---------------------------------------------------------------------------

def is_imported_record(row: Dict[str, Any]) -> bool:
    """True iff this club RECORD is migrated history (record_origin == the
    import marker). This is the REGISTER's record-level view — NOT the
    headline count (see headline(): history is numbers-first from the client
    worksheets; adding the imported records on top of the baseline would
    double-count)."""
    return str((row or {}).get("record_origin", "") or "").strip().lower() == IMPORTED_MARKER


def split_register_rows(clubs: List[Dict[str, Any]]) -> Tuple[int, int]:
    """(live_rows, migrated_rows) for a list of club records — the REGISTER
    record-level split. live_rows + migrated_rows == len(clubs), always."""
    migrated = sum(1 for c in (clubs or []) if is_imported_record(c))
    return len(clubs or []) - migrated, migrated


# ---------------------------------------------------------------------------
# 2. The headline (dashboard rule)
# ---------------------------------------------------------------------------

def migrated_history_totals(filter_year: str = "", filter_zone: str = "") -> Dict[str, Any]:
    """Migrated HISTORY grand totals — the same source the admin KPI's
    "X live + Y migrated club approvals (history)" line reads
    (db.migration_engine.history_grand_totals). Optional year/zone filters
    match the dashboard scope (PERIOD year, worksheet zone) so filtered views
    stay honest. Read-only."""
    return history_grand_totals(filter_year=filter_year, filter_zone=filter_zone)


def headline(clubs: Optional[List[Dict[str, Any]]] = None,
             filter_year: str = "", filter_zone: str = "",
             migrated_totals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """THE headline counts, computed in exactly one place.

    `migrated_totals` may be injected (the assistant tool layer passes its own
    read seam so tests can stub it); when omitted the history store is read.

    Returns:
      register_rows          — club records in the register (all provenances)
      live_clubs             — records created through the portal (new work)
      register_migrated_rows — imported HISTORY records visible in the register
      migrated_approvals     — history BASELINE approvals (client worksheets)
      programme_total        — live_clubs + migrated_approvals (the headline)
      migrated_support       — history BASELINE support interactions
      migrated_online_workshops — history BASELINE online workshops
      + the raw migrated_history_totals() payload (employees_migrated,
        first_year, last_year) so callers need no second lookup.
    """
    if clubs is None:
        from config import MASTER_CLUBS_CSV
        from db.schemas import CLUB_FIELDS
        clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
    live, migrated_rows = split_register_rows(clubs)
    mig = migrated_totals if migrated_totals is not None else migrated_history_totals(
        filter_year=filter_year, filter_zone=filter_zone)
    migrated_approvals = _parse_count(mig.get("approvals", 0))
    out = {
        "register_rows": len(clubs or []),
        "live_clubs": live,
        "register_migrated_rows": migrated_rows,
        "migrated_approvals": migrated_approvals,
        "programme_total": live + migrated_approvals,
        "migrated_support": _parse_count(mig.get("support", 0)),
        "migrated_online_workshops": _parse_count(mig.get("online_workshops", 0)),
    }
    out.update(mig)
    return out


# ---------------------------------------------------------------------------
# 3. Employee split (blended total = live + migrated baseline)
# ---------------------------------------------------------------------------

def split_total(total: int, baseline: int) -> Tuple[int, int]:
    """Split one blended employee number into (live, migrated).

    The baseline is immutable history; the live half is whatever the blended
    total adds on top. The arithmetic lives HERE so the quota card, the
    roster, and the API can never derive it differently (R38: admin.html used
    to subtract in JS)."""
    t = _parse_count(total)
    b = _parse_count(baseline)
    if b > t:
        # A baseline larger than its blended total means a stale total (the
        # R30 negative-live bug). Never return a negative "live" half.
        return 0, t
    return t - b, b


def blended_total(live: int, migrated: int) -> int:
    """THE blended headline for any metric = live + migrated. The one place
    the addition happens (R38: JS used to add)."""
    return _parse_count(live) + _parse_count(migrated)


# ---------------------------------------------------------------------------
# 4. Activity bucketing (R29v2 rule, relocated from SyncEngine)
# ---------------------------------------------------------------------------

def bucket_activity(a: Dict[str, Any]) -> str:
    """Classify one activity row for performance counting.

    Returns 'approval' | 'online' | 'offline' | 'other' | 'skip'.

    - 'skip' is ONLY the "Data Migration" audit-marker row (the bulk-number
      summary row): history bookkeeping, never live work.
    - 'other' is deliberately a CATCH-ALL: phone/OS-ticket support,
      "Registration Renewal", "Data Correction", and any support_type added
      in the future — nothing may fall through uncounted.
    """
    stype = ((a or {}).get("support_type") or "").strip()
    aid = ((a or {}).get("activity_id") or "").strip()
    a_emp = ((a or {}).get("emp_id") or "").strip().upper()
    if stype == "Data Migration":
        return "skip"
    if stype == "Club Approval" or (a_emp and aid.startswith(f"ACT-PRIORITY-{a_emp}")):
        return "approval"
    if stype == "Online training":
        return "online"
    if stype == "Offline training":
        return "offline"
    return "other"
