"""
NDLI Club Management — R30 Migration Engine (client data migration Phase 2).

PURPOSE (user-approved architecture, 2026-10-09): the client's legacy system
keeps EMPLOYEE ACTIVITY HISTORY as per-period COUNTS (one worksheet per
employee) with NO club identity. We keep past and present strictly separate:

  * migrated history lives in its own read-only table
    (data/master/master_employee_history.csv) at the client's period grain
    (Year/Month/Week — NEVER the entry timestamp, which is when the row was
    logged and mismatches the work period in 100% of the sample rows);
  * Performance Quota / star rating = migrated baseline + live-derived counts
    (the anti-drift property of recompute_and_persist_quota is preserved: the
    live part stays derived fresh from live CSVs, the baseline is only ever
    written here);
  * no fabricated club links are created — history rows never carry club_id;
  * after migration the live app follows its existing rules unchanged.

Client worksheet columns (sample 2026-10-09, 5,518 rows / one employee):
  Timestamp_id, Task_id, State_id, Zone_id, Year_id, Month_id, Week_id,
  Club Approval, No. of User Registration, No. of Local Event,
  No. of Global Event, No. of Physical Workshop, Club Support, Nature of Support

Known client quirks (locked with the user):
  * Task_id ∈ {"Club Approval", "Club support", "Workshop"} — "Workshop" rows
    are ONLINE workshops even though they fill the column the client labelled
    "No. of Physical Workshop" (column misnomer — never call them physical).
  * Nature of Support: AD = Remote support (AnyDesk), OC = On Call,
    AD+OC = Both.
  * Counts may carry thousands separators ("1,116"); blank cells mean 0.
  * Giant single-row counts (e.g. 219/239/369/530 approvals) are LEGITIMATE
    backfill from an earlier bulk migration (client system v1, started 2019) —
    they are flagged as NOTES in the dry-run, never as errors.
"""
import csv
import io
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from db.csv_engine import CSVEngine
from db.schemas import (
    MIGRATION_HISTORY_FIELDS,
    USER_FIELDS,
    ACTIVITY_FIELDS,
)
from config import MASTER_DATA_DIR, MASTER_USERS_CSV, MASTER_ACTIVITIES_CSV, EMPLOYEE_NODES_DIR

MASTER_HISTORY_CSV: Path = MASTER_DATA_DIR / "master_employee_history.csv"

# Canonical task types (history table vocabulary)
TASK_CLUB_APPROVAL = "Club Approval"
TASK_CLUB_SUPPORT = "Club Support"
TASK_ONLINE_WORKSHOP = "Online Workshop"
TASK_TYPES = (TASK_CLUB_APPROVAL, TASK_CLUB_SUPPORT, TASK_ONLINE_WORKSHOP)

TASK_TYPE_MAP = {
    "club approval": TASK_CLUB_APPROVAL,
    "club approvals": TASK_CLUB_APPROVAL,
    "club support": TASK_CLUB_SUPPORT,
    "club supports": TASK_CLUB_SUPPORT,
    "workshop": TASK_ONLINE_WORKSHOP,
    "online workshop": TASK_ONLINE_WORKSHOP,
}

# Nature of Support labels (user-confirmed 2026-10-09)
NATURE_MAP = {
    "ad": "Remote support (AnyDesk)",
    "oc": "On Call",
    "ad+oc": "Both (AnyDesk + On Call)",
    "ad + oc": "Both (AnyDesk + On Call)",
    "": "",
}

# Client worksheet header -> internal column (header keys are the NORMALISED
# form: _norm_header lowercases and collapses non-alphanumerics to spaces)
_HEADER_MAP = {
    "timestamp id": "entry_timestamp",
    "task id": "task_type",
    "state id": "state",
    "zone id": "zone",
    "year id": "period_year",
    "month id": "period_month",
    "week id": "period_week",
    "club approval": "approvals_count",
    "no of user registration": "user_registrations_count",
    "no of local event": "local_events_count",
    "no of global event": "global_events_count",
    "no of physical workshop": "online_workshops_count",  # CLIENT MISNOMER: these are ONLINE workshops
    "club support": "support_count",
    "nature of support": "nature",
}

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# A single row carrying more approvals OR support than this is flagged as a
# backfill/lump (the client's file holds both families: approval catch-ups
# 219/223/239/369/530 and one support catch-up of 1,116 — all legit backfill)
# row (NOTE, not error — the user confirmed these are legitimate migration
# catch-ups from the client's previous system).
LUMP_ROW_THRESHOLD = 100

_MIGRATION_LOCK = threading.RLock()


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(h or "").strip().lower()).strip()


def _parse_count(raw: Any) -> int:
    s = str(raw or "").strip().replace(",", "").replace(" ", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return -1  # caller treats -1 as unparseable


def parse_employee_history_csv(csv_text: str) -> Dict[str, Any]:
    """
    Parses + statically validates ONE client employee worksheet.
    Pure/dry-run: writes nothing anywhere.

    Returns:
      {
        "file_errors": [str, ...],          # whole-file problems
        "rows": [ {"line": int, "data": {...}, "errors": [...], "notes": [...]} ],
        "summary": {
            "total_rows": int, "ok_rows": int, "error_rows": int,
            "totals": {"approvals": n, "support": n, "online_workshops": n,
                       "user_registrations": n, "local_events": n, "global_events": n},
            "span": {"first_year": .., "last_year": ..},
            "task_types": {...}, "notes": [...]
        }
      }
    """
    text = str(csv_text or "").lstrip("\ufeff")
    file_errors: List[str] = []
    rows: List[Dict[str, Any]] = []

    reader = list(csv.reader(io.StringIO(text)))
    reader = [r for r in reader if any(str(c or "").strip() for c in r)]
    if not reader:
        return {"file_errors": ["The CSV is empty — expected the client worksheet "
                                "with a header row and at least one data row."],
                "rows": [], "summary": _empty_summary()}

    header = [_norm_header(h) for h in reader[0]]
    cols: List[Optional[str]] = []
    unknown: List[str] = []
    for h in header:
        if h in _HEADER_MAP:
            cols.append(_HEADER_MAP[h])
        elif h == "":
            cols.append(None)  # trailing empty column tolerated
        else:
            cols.append(None)
            unknown.append(h)
    if unknown:
        file_errors.append(
            "Unrecognised column(s): %s. Expected the client worksheet columns "
            "(Timestamp_id, Task_id, State_id, Zone_id, Year_id, Month_id, Week_id, "
            "Club Approval, No. of User Registration, No. of Local Event, "
            "No. of Global Event, No. of Physical Workshop, Club Support, "
            "Nature of Support)." % ", ".join(sorted(set(unknown))))
    needed = ["task_type", "period_year"]
    have = {c for c in cols if c}
    for n in needed:
        if n not in have:
            file_errors.append("Required column missing: %s" % {
                "task_type": "Task_id", "period_year": "Year_id"}[n])
    if file_errors:
        return {"file_errors": file_errors, "rows": [], "summary": _empty_summary()}

    years: List[int] = []
    totals = {"approvals": 0, "support": 0, "online_workshops": 0,
              "user_registrations": 0, "local_events": 0, "global_events": 0}
    task_counter: Dict[str, int] = {}
    file_notes: List[str] = []

    for idx, raw in enumerate(reader[1:], start=2):
        errors: List[str] = []
        notes: List[str] = []
        data: Dict[str, Any] = {}
        for cell, col in zip(raw, cols):
            if col:
                data[col] = str(cell or "").strip()
        if len(raw) != len(cols):
            errors.append(f"Expected {len(cols)} columns, got {len(raw)}.")

        # task type
        tt_raw = data.get("task_type", "")
        tt = TASK_TYPE_MAP.get(tt_raw.strip().lower())
        if not tt_raw.strip():
            errors.append("Task_id is required.")
        elif not tt:
            errors.append(
                f"Unknown Task_id '{tt_raw}' — expected 'Club Approval', "
                f"'Club support' or 'Workshop'.")
        data["task_type"] = tt or tt_raw

        # period (event time — never the entry timestamp)
        yr = _parse_count(data.get("period_year", ""))
        if yr < 2000 or yr > 2100:
            errors.append(f"Year_id must be a 4-digit year, got "
                          f"'{data.get('period_year', '')}'.")
        else:
            years.append(yr)
        data["period_year"] = str(yr) if yr > 0 else ""
        mo_raw = data.get("period_month", "")
        mo = _MONTHS.get(mo_raw.strip().lower(), 0)
        data["period_month"] = f"{mo:02d}" if mo else mo_raw
        if mo_raw.strip() and not mo:
            notes.append(f"Month '{mo_raw}' kept verbatim (not a known month name).")

        # counts
        for src, dst in (("approvals_count", "approvals"),
                         ("support_count", "support"),
                         ("online_workshops_count", "online_workshops"),
                         ("user_registrations_count", "user_registrations"),
                         ("local_events_count", "local_events"),
                         ("global_events_count", "global_events")):
            n = _parse_count(data.get(src, ""))
            if n < 0:
                errors.append(f"Unparseable count '{data.get(src, '')}' in "
                              f"{src.replace('_count', '')}.")
                n = 0
            data[src] = str(n)
            totals[dst] += n

        # backfill lump rows: legitimate, but always surfaced
        row_total = max(
            _parse_count(data.get("approvals_count", "")),
            _parse_count(data.get("support_count", "")))
        if row_total >= LUMP_ROW_THRESHOLD:
            notes.append(f"Large single-row count ({row_total}) — backfill/lump "
                         f"entry from the client's previous system migration "
                         f"(legitimate; confirm in preview).")
            file_notes.append(f"line {idx}: lump/backfill count {row_total}")

        # nature of support
        nat_raw = data.get("nature", "")
        nat = NATURE_MAP.get(nat_raw.strip().lower())
        if nat is None:
            nat = nat_raw
            notes.append(f"Unknown Nature of Support '{nat_raw}' kept verbatim.")
        data["nature"] = nat

        data.setdefault("state", "")
        data.setdefault("zone", "")
        data.setdefault("period_week", "")
        data.setdefault("entry_timestamp", "")
        task_counter[data["task_type"]] = task_counter.get(data["task_type"], 0) + 1

        rows.append({"line": idx, "data": data, "errors": errors, "notes": notes})

    ok_rows = sum(1 for r in rows if not r["errors"])
    return {
        "file_errors": file_errors,
        "rows": rows,
        "summary": {
            "total_rows": len(rows),
            "ok_rows": ok_rows,
            "error_rows": len(rows) - ok_rows,
            "totals": totals,
            "span": {"first_year": min(years) if years else None,
                     "last_year": max(years) if years else None},
            "task_types": task_counter,
            "notes": file_notes,
        },
    }


def _empty_summary() -> Dict[str, Any]:
    return {"total_rows": 0, "ok_rows": 0, "error_rows": 0,
            "totals": {"approvals": 0, "support": 0, "online_workshops": 0,
                       "user_registrations": 0, "local_events": 0,
                       "global_events": 0},
            "span": {"first_year": None, "last_year": None},
            "task_types": {}, "notes": []}


def validate_employee_history(emp_id: str, csv_text: str) -> Dict[str, Any]:
    """Dry-run report for one employee worksheet. Writes nothing."""
    clean = str(emp_id or "").strip().upper()
    parsed = parse_employee_history_csv(csv_text)
    errors = list(parsed["file_errors"])
    user = CSVEngine.find_by_key(MASTER_USERS_CSV, "id", clean, USER_FIELDS, copy=False)
    if not user:
        errors.append(f"Employee '{clean}' does not exist.")
    elif str(user.get("is_active", "1")).strip() != "1":
        errors.append(f"Employee '{clean}' is blocked or inactive.")
    existing = existing_history_count(clean)
    notes = list(parsed["summary"].get("notes", []))
    if existing:
        notes.append(f"{existing} migrated history row(s) already present for "
                     f"{clean} — committing with replace=true will overwrite them.")
    return {
        "emp_id": clean,
        "dry_run": True,
        "ready": not errors and parsed["summary"]["error_rows"] == 0
                 and parsed["summary"]["total_rows"] > 0,
        "file_errors": errors,
        "rows": parsed["rows"],
        "summary": {**parsed["summary"], "notes": notes},
        "existing_history_rows": existing,
    }


def existing_history_count(emp_id: str) -> int:
    clean = str(emp_id or "").strip().upper()
    if not MASTER_HISTORY_CSV.exists():
        return 0
    return sum(1 for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS)
               if r.get("emp_id", "").strip().upper() == clean)


def commit_employee_history(emp_id: str, csv_text: str,
                            batch_id: str = "",
                            replace: bool = False,
                            actor: str = "") -> Dict[str, Any]:
    """
    Writes the migrated history for ONE employee (idempotent replace semantics)
    and records the migration in the activity log as ONE clearly-marked
    'Data Migration' summary row (the user's "bulk number" row — never a
    fabricated per-club approval).
    """
    clean = str(emp_id or "").strip().upper()
    report = validate_employee_history(clean, csv_text)
    if not report["ready"]:
        return {"success": False, "error": True, "message":
                "Migration dry-run failed — nothing was written.", **report}

    with _MIGRATION_LOCK:
        existing = existing_history_count(clean)
        if existing and not replace:
            return {"success": False, "error": True, "status": 409, "message":
                    f"{clean} already has {existing} migrated history row(s). "
                    f"Resend with replace=true to overwrite them.", **report}

        now_iso = datetime.now(timezone.utc).isoformat()
        batch = str(batch_id or "").strip() or \
            f"MIG-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        if MASTER_HISTORY_CSV.exists() and existing:
            kept = [r for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS)
                    if r.get("emp_id", "").strip().upper() != clean]
            CSVEngine.write_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS, kept)

        # Replace semantics cover the audit marker too: a re-run must leave
        # exactly ONE "Data Migration" summary row per employee (idempotent),
        # never a stack of stale summaries from earlier attempts.
        if existing:
            for act_path in (MASTER_ACTIVITIES_CSV,
                             EMPLOYEE_NODES_DIR / clean / "activity_log.csv"):
                if not act_path.exists():
                    continue
                rows = CSVEngine.read_all(act_path, ACTIVITY_FIELDS)
                kept_acts = [r for r in rows if not (
                    r.get("emp_id", "").strip().upper() == clean
                    and r.get("support_type", "").strip() == "Data Migration")]
                if len(kept_acts) != len(rows):
                    CSVEngine.write_all(act_path, ACTIVITY_FIELDS, kept_acts)

        written = 0
        for i, row in enumerate(report["rows"], start=1):
            if row["errors"]:
                continue
            d = row["data"]
            hist_id = f"HIST-{clean}-{batch}-{i:04d}"
            CSVEngine.append_row(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS, {
                "hist_id": hist_id,
                "emp_id": clean,
                "period_year": d.get("period_year", ""),
                "period_month": d.get("period_month", ""),
                "period_week": d.get("period_week", ""),
                "task_type": d.get("task_type", ""),
                "approvals_count": d.get("approvals_count", "0"),
                "support_count": d.get("support_count", "0"),
                "online_workshops_count": d.get("online_workshops_count", "0"),
                "user_registrations_count": d.get("user_registrations_count", "0"),
                "local_events_count": d.get("local_events_count", "0"),
                "global_events_count": d.get("global_events_count", "0"),
                "nature": d.get("nature", ""),
                "state": d.get("state", ""),
                "zone": d.get("zone", ""),
                "entry_timestamp": d.get("entry_timestamp", ""),
                "batch_id": batch,
            })
            written += 1

        totals = report["summary"]["totals"]
        # ONE marked summary row in the employee's activity log (bulk number) +
        # master log. support_type "Data Migration" is excluded from support
        # counting so it can never inflate any metric.
        act_id = f"ACT-MIGRATION-{clean}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        span = report["summary"]["span"]
        span_txt = (f"{span.get('first_year')}–{span.get('last_year')}"
                    if span.get("first_year") else "n/a")
        activity_row = {
            "activity_id": act_id,
            "emp_id": clean,
            "timestamp": now_iso,
            "support_type": "Data Migration",
            "priority_flag": "0",
            "club_id": "",
            "notes": (f"Migrated history recorded by {actor or 'ADMIN'} (batch {batch}): "
                      f"{totals['approvals']} club approvals, {totals['support']} support "
                      f"interactions, {totals['online_workshops']} online workshops "
                      f"({span_txt}). Past and present are kept separate — see the "
                      f"Migrated History summary."),
        }
        emp_dir = EMPLOYEE_NODES_DIR / clean
        emp_act = emp_dir / "activity_log.csv"
        if emp_dir.exists():
            CSVEngine.append_row(emp_act, ACTIVITY_FIELDS, activity_row)
        CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)

    return {"success": True, "error": False, "batch_id": batch,
            "rows_written": written, "replaced_existing": bool(existing),
            "totals": totals, "emp_id": clean,
            "message": (f"Migrated history recorded for {clean}: {written} row(s), "
                        f"{totals['approvals']} approvals / {totals['support']} support "
                        f"({span_txt}).")}


def baselines_for(emp_id: str, filter_year: Optional[str] = None,
                  filter_month: Optional[int] = None,
                  filter_state: Optional[str] = None) -> Dict[str, int]:
    """
    Sums the migrated baseline for one employee, optionally sliced by the same
    period/state filters the live performance endpoint supports. This is what
    makes baseline + live arithmetic honest under filtering.
    """
    clean = str(emp_id or "").strip().upper()
    out = {"approvals": 0, "support": 0, "online_workshops": 0,
           "user_registrations": 0, "local_events": 0, "global_events": 0}
    if not clean or not MASTER_HISTORY_CSV.exists():
        return out
    fy = str(filter_year or "").strip()
    fs = str(filter_state or "").strip().lower()
    for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS):
        if r.get("emp_id", "").strip().upper() != clean:
            continue
        if fy and fy.upper() != "ALL" and r.get("period_year", "").strip() != fy:
            continue
        if filter_month is not None:
            try:
                if int(r.get("period_month", "0") or 0) != int(filter_month):
                    continue
            except ValueError:
                continue
        if fs and fs != "all" and r.get("state", "").strip().lower() != fs:
            continue
        out["approvals"] += _parse_count(r.get("approvals_count", "0"))
        out["support"] += _parse_count(r.get("support_count", "0"))
        out["online_workshops"] += _parse_count(r.get("online_workshops_count", "0"))
        out["user_registrations"] += _parse_count(r.get("user_registrations_count", "0"))
        out["local_events"] += _parse_count(r.get("local_events_count", "0"))
        out["global_events"] += _parse_count(r.get("global_events_count", "0"))
    return out


def history_period_years() -> List[str]:
    """Distinct PERIOD years across ALL migrated history — for analytics year
    filters (the client worksheets bucket by Year_id, never the entry time)."""
    years: set = set()
    if MASTER_HISTORY_CSV.exists():
        for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS):
            y = str(r.get("period_year", "")).strip()
            if y.isdigit():
                years.add(y)
    return sorted(years, reverse=True)


def history_grand_totals(filter_year: str = "", filter_zone: str = "") -> Dict[str, Any]:
    """Grand totals across ALL migrated employees (read-only) — feeds the
    admin dashboard's honest live-vs-migrated split display. The optional year /
    zone filters match the dashboard scope (PERIOD year, worksheet zone) so
    filtered views stay honest."""
    fy = str(filter_year or "").strip()
    fz = str(filter_zone or "").strip()
    use_year = bool(fy) and fy.upper() != "ALL"
    use_zone = bool(fz) and fz.upper() != "ALL"
    out = {"approvals": 0, "support": 0, "online_workshops": 0,
           "employees_migrated": 0, "first_year": "", "last_year": ""}
    emps: set = set()
    years: List[int] = []
    if MASTER_HISTORY_CSV.exists():
        for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS):
            if use_year and str(r.get("period_year", "")).strip() != fy:
                continue
            if use_zone and (r.get("zone", "") or "").strip().lower() != fz.lower():
                continue
            e = r.get("emp_id", "").strip().upper()
            if e:
                emps.add(e)
            out["approvals"] += _parse_count(r.get("approvals_count", "0"))
            out["support"] += _parse_count(r.get("support_count", "0"))
            out["online_workshops"] += _parse_count(r.get("online_workshops_count", "0"))
            y = _parse_count(r.get("period_year", "0"))
            if y > 0:
                years.append(y)
    out["employees_migrated"] = len(emps)
    if years:
        out["first_year"] = str(min(years))
        out["last_year"] = str(max(years))
    return out


def history_summary(emp_id: str) -> Dict[str, Any]:
    """UI summary: totals + span + row count for one employee (read-only)."""
    clean = str(emp_id or "").strip().upper()
    totals = baselines_for(clean)
    rows = existing_history_count(clean)
    years: List[int] = []
    if MASTER_HISTORY_CSV.exists():
        for r in CSVEngine.read_all(MASTER_HISTORY_CSV, MIGRATION_HISTORY_FIELDS):
            if r.get("emp_id", "").strip().upper() != clean:
                continue
            y = _parse_count(r.get("period_year", "0"))
            if y > 0:
                years.append(y)
    return {"emp_id": clean, "rows": rows, "totals": totals,
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None}
