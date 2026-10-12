"""db/sync/dates.py - renewal/date parsing helpers (pure functions).

R46: moved verbatim from db/sync_engine.py (the split of the 1,741-line
monolith).  `_parse_string_date` keeps its R40 lru_cache.  Zero behavior change.
"""



from datetime import date, datetime, timezone

from functools import lru_cache

from typing import Any, Optional



@lru_cache(maxsize=131072)
def _parse_string_date(s: str) -> Optional[date]:
    """Cached core of parse_iso_or_date for string inputs (R40).

    Pure function of its input; the hot paths (renewal attention, metrics year
    discovery) call it O(rows) times per request over the same handful of
    date formats. lru_cache is thread-safe.
    """
    s = s.strip()
    if not s or s == "-":
        return None
    clean = s.split("T")[0].split(" ")[0].strip()
    # Fast-path for standard ISO date: YYYY-MM-DD
    if len(clean) == 10 and clean[4] == '-' and clean[7] == '-':
        try:
            return date(int(clean[0:4]), int(clean[5:7]), int(clean[8:10]))
        except ValueError:
            pass
    # Fast-path for DD-MM-YYYY
    if len(clean) == 10 and clean[2] == '-' and clean[5] == '-':
        try:
            return date(int(clean[6:10]), int(clean[3:5]), int(clean[0:2]))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        pass
    return None


def parse_iso_or_date(val: Any) -> Optional[date]:
    """Safely extracts a calendar date object from an ISO string, date string, or timestamp."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return _parse_string_date(str(val))


def calculate_next_renewal_date(
    establishment_date: Optional[str] = None,
    last_renewal_date: Optional[str] = None,
    date_of_approval: Optional[str] = None,
    renewal_date: Optional[str] = None
) -> str:
    """
    Computes the upcoming renewal date as exactly 1 calendar year (+1 year) from
    the last renewal date (if renewed) or the date of approval / establishment date.
    If renewal_date is supplied, ensures that upcoming renewal date can NEVER be
    earlier than date_of_approval or last_renewal_date. If renewal_date is earlier,
    recalculates it as 1 calendar year (+1 year) from the latest approval / renewal date.
    If neither date is provided or valid, defaults to 1 year from current UTC date.
    """
    ren_d = parse_iso_or_date(last_renewal_date)
    est_d = parse_iso_or_date(date_of_approval) if date_of_approval else parse_iso_or_date(establishment_date)

    latest_date: Optional[date] = None
    if ren_d and est_d:
        latest_date = max(est_d, ren_d)
    elif ren_d:
        latest_date = ren_d
    elif est_d:
        latest_date = est_d
    else:
        latest_date = datetime.now(timezone.utc).date()

    try:
        computed_next = latest_date.replace(year=latest_date.year + 1)
    except ValueError:
        # Handles Feb 29 leap year rollover: strictly Feb 28 of following year
        computed_next = latest_date.replace(year=latest_date.year + 1, month=2, day=28)

    if renewal_date:
        parsed_prop = parse_iso_or_date(renewal_date)
        if parsed_prop:
            # An upcoming renewal date can NEVER be earlier than date_of_approval or last_renewal_date
            if latest_date and parsed_prop <= latest_date:
                return computed_next.isoformat()
            return parsed_prop.isoformat()

    return computed_next.isoformat()


def parse_iso_datetime(val: Any) -> Optional[datetime]:
    """
    Safely parses an ISO datetime string into a UTC-aware datetime.
    Bare dates map to midnight UTC. (Round-2: needed for the duplicate-renewal
    guard — a date-only parse would truncate to midnight and defeat the window.)
    """
    s = str(val or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        d = parse_iso_or_date(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None


def _add_one_year(d: date) -> date:
    """d + 1 calendar year, with Feb 29 rolling to Feb 28."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, month=2, day=28)


def calculate_next_renewal_due(
    previous_renewal_date: Optional[str] = None,
    date_of_approval: Optional[str] = None
) -> str:
    """
    Round-2 renewal policy (2026-09-25, client-approved): the new due date is
    +1 year from the PREVIOUS DUE DATE, so renewing early never shortens the
    cycle and the club keeps its anniversary. If no previous due date is known,
    the date of approval is the base. If the computed date already lies in the
    past (overdue renewal), it is rolled forward in 1-year steps until it is in
    the future, so a renewal always yields a usable validity window.
    """
    today = datetime.now(timezone.utc).date()
    base = parse_iso_or_date(previous_renewal_date) or parse_iso_or_date(date_of_approval) or today
    cand = _add_one_year(base)
    while cand <= today:
        cand = _add_one_year(cand)
    return cand.isoformat()

