"""
routes/metrics.py - Admin metrics, performance, renewal attention, AI insights

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from ai.decision_module import AIDecisionEngine
from config import MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV, MASTER_USERS_CSV, SUPPORT_TYPES
from db import counting_rules
from db.csv_engine import CSVEngine
from db.migration_engine import (
    baselines_for as migration_baselines_for,
    history_rows as migration_history_rows,
    validate_employee_history as migration_validate_history,
    commit_employee_history as migration_commit_history,
    history_grand_totals as migration_grand_totals,
    history_period_years as migration_period_years,
    history_summary as migration_history_summary,
)
from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS, QUOTA_FIELDS, USER_FIELDS
from db.sync_engine import SyncEngine, parse_iso_or_date
from state_zone_mapper import ZONE_STATE_MAP, get_all_states, get_all_zones, get_zone_for_state

# path == "/api/admin/metrics"
def get_admin_metrics(h, path, query_params):
    if not h._check_admin_access():
        return
    all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS, copy=False)
    all_activities = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, copy=False)
    all_quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, copy=False)
    all_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS, copy=False)
    # R40: read the migrated history ONCE per request (read-only seam) —
    # pre-R40 this file was re-read by every history helper in the chain.
    hist_rows = migration_history_rows()

    # Query Filters: Scope by Zone and/or Year
    raw_zone = query_params.get("zone", ["ALL"])[0].strip()
    raw_year = query_params.get("year", ["ALL"])[0].strip()
    filter_zone = raw_zone if raw_zone.upper() != "ALL" and raw_zone else "ALL"
    filter_year = raw_year if raw_year.upper() != "ALL" and raw_year else "ALL"

    # Discover all available years dynamically across database
    # (R30v2: incl. MIGRATED HISTORY period years — the worksheets
    # bucket by Year_id, never the entry timestamp)
    available_years_set = {"2026", "2025", "2024"}
    for _hy in migration_period_years(rows=hist_rows):
        available_years_set.add(_hy)
    for c in all_clubs:
        ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
        if ts:
            dp = parse_iso_or_date(ts)
            if dp:
                available_years_set.add(str(dp.year))
    for a in all_activities:
        ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
        if ts:
            dp = parse_iso_or_date(ts)
            if dp:
                available_years_set.add(str(dp.year))
    available_years = sorted(list(available_years_set), reverse=True)
    # R30v3: the year filter is a CONTINUOUS programme range — gap
    # years must not vanish (the client expects 2020..current even
    # where a year like 2021 has zero entries), and earlier years
    # appear automatically when historical data reaches further back.
    _yrs = [int(y) for y in available_years_set if str(y).isdigit()]
    _lo = min(_yrs + [2020])
    _hi = max(_yrs + [datetime.now().year])
    available_years = [str(y) for y in range(_hi, _lo - 1, -1)]

    # Build employee to zone mapping
    emp_to_zone = {u.get("id"): u.get("zone", "Other") for u in all_users if u.get("role") == "EMPLOYEE"}

    # Filter clubs by zone and year
    filtered_clubs = []
    for c in all_clubs:
        c_st = c.get("state", "").strip()
        c_zone = c.get("zone", "").strip() or get_zone_for_state(c_st)
        ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
        dp = parse_iso_or_date(ts) if ts else None
        c_year = str(dp.year) if dp else ""

        if filter_zone != "ALL" and c_zone != filter_zone:
            continue
        if filter_year != "ALL" and c_year != filter_year:
            continue
        filtered_clubs.append(c)

    # Filter activities by zone and year
    filtered_activities = []
    for a in all_activities:
        emp_id = a.get("emp_id", "")
        act_zone = emp_to_zone.get(emp_id, "Other")
        ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
        dp = parse_iso_or_date(ts) if ts else None
        a_year = str(dp.year) if dp else ""

        if filter_zone != "ALL" and act_zone != filter_zone:
            continue
        if filter_year != "ALL" and a_year != filter_year:
            continue
        filtered_activities.append(a)

    # Filter quotas and users by zone
    if filter_zone != "ALL":
        zone_emp_ids = {u.get("id") for u in all_users if u.get("zone") == filter_zone}
        quotas = [q for q in all_quotas if q.get("emp_id") in zone_emp_ids]
        filtered_emp_users = [u for u in all_users if u.get("role") == "EMPLOYEE" and u.get("zone") == filter_zone]
    else:
        quotas = all_quotas
        filtered_emp_users = [u for u in all_users if u.get("role") == "EMPLOYEE"]

    # Calculate breakdown metrics from filtered clubs
    state_counts: Dict[str, int] = {}
    zone_counts: Dict[str, int] = {}
    year_counts: Dict[str, int] = {}
    month_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}

    for c in filtered_clubs:
        st = c.get("state", "Unknown")
        zn = c.get("zone", "Unknown") or get_zone_for_state(st)
        stat = c.get("status", "Approved")
        ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")

        state_counts[st] = state_counts.get(st, 0) + 1
        zone_counts[zn] = zone_counts.get(zn, 0) + 1
        status_counts[stat] = status_counts.get(stat, 0) + 1

        if ts:
            d_parsed = parse_iso_or_date(ts)
            if d_parsed:
                yr = str(d_parsed.year)
                mo = f"{d_parsed.year:04d}-{d_parsed.month:02d}"
                year_counts[yr] = year_counts.get(yr, 0) + 1
                month_counts[mo] = month_counts.get(mo, 0) + 1

    attention_data = AIDecisionEngine.get_renewal_attention_data(clubs=filtered_clubs)

    # Detailed Analytics: 1. Support Type Breakdown
    support_type_counts = {st: 0 for st in SUPPORT_TYPES}
    for a in filtered_activities:
        stype = a.get("support_type", "")
        if stype in support_type_counts:
            support_type_counts[stype] += 1
        elif stype:
            support_type_counts[stype] = support_type_counts.get(stype, 0) + 1

    # Detailed Analytics: 2. Renewal & Retention Health
    total_clubs_count = len(filtered_clubs)
    overdue_count = attention_data.get("overdue_count", 0)
    expiring_soon_count = attention_data.get("expiring_soon_count", 0)
    active_validity_count = max(0, total_clubs_count - overdue_count)
    retention_rate_pct = round(((total_clubs_count - overdue_count) / max(1, total_clubs_count)) * 100, 1) if total_clubs_count > 0 else 100.0
    renewal_health = {
        "total_clubs": total_clubs_count,
        "active_validity_count": active_validity_count,
        "expiring_soon_count": expiring_soon_count,
        "overdue_count": overdue_count,
        "retention_rate_pct": retention_rate_pct
    }

    # Detailed Analytics: 3. National / Regional State Coverage Index
    if filter_zone != "ALL":
        target_states = ZONE_STATE_MAP.get(filter_zone, [])
    else:
        target_states = get_all_states()

    total_states = len(target_states)
    represented_states = [s for s in target_states if state_counts.get(s, 0) > 0]
    deficit_states = [s for s in target_states if state_counts.get(s, 0) == 0]
    coverage_pct = round((len(represented_states) / max(1, total_states)) * 100, 1) if total_states > 0 else 0.0
    coverage_index = {
        "total_states": total_states,
        "represented_count": len(represented_states),
        "deficit_count": len(deficit_states),
        "coverage_percentage": coverage_pct,
        "deficit_states": deficit_states,
        "represented_states": represented_states,
        "zone_scope": filter_zone
    }

    # Detailed Analytics: 4. Zone Efficiency & Activity Distribution
    all_zones = get_all_zones()
    zone_support_counts: Dict[str, int] = {z: 0 for z in all_zones}
    for a in filtered_activities:
        emp_id = a.get("emp_id")
        z = emp_to_zone.get(emp_id)
        if z and z in zone_support_counts:
            zone_support_counts[z] += 1
        elif z:
            zone_support_counts[z] = zone_support_counts.get(z, 0) + 1

    zone_efficiency = {}
    for z in (all_zones if filter_zone == "ALL" else [filter_zone]):
        c_cnt = zone_counts.get(z, 0)
        s_cnt = zone_support_counts.get(z, 0)
        zone_efficiency[z] = {
            "clubs": c_cnt,
            "support_logs": s_cnt,
            "ratio": round(s_cnt / max(1, c_cnt), 2)
        }

    # R38: THE counting module computes the headline (single source —
    # db/counting_rules.py). live excludes imported records on purpose
    # — those ARE the migrated clubs (counting both the records and the
    # baseline would double-count the moment the client club log is bulk
    # imported). Migrated totals follow the dashboard's zone/year scope.
    _h = counting_rules.headline(filtered_clubs,
                                 filter_year=filter_year,
                                 filter_zone=filter_zone,
                                 # R40: the migrated half comes from the
                                 # request's single history snapshot.
                                 migrated_totals=migration_grand_totals(
                                     filter_year=filter_year,
                                     filter_zone=filter_zone,
                                     rows=hist_rows))
    # R38: quota rows carry their live halves from the SAME module so
    # the JS never does split arithmetic (it used to subtract).
    quota_rows = []
    for q in quotas:
        _ql, _qm = counting_rules.split_total(
            q.get("clubs_approved_count", 0), q.get("legacy_clubs_count", 0))
        _sl, _sm = counting_rules.split_total(
            q.get("support_logs_count", 0), q.get("legacy_support_count", 0))
        quota_rows.append({**q,
                           "live_clubs_count": _ql,
                           "live_support_count": _sl})
    h._send_json({
        "summary": {
            "total_clubs": _h["register_rows"],
            "live_clubs": _h["live_clubs"],
            "register_migrated_rows": _h["register_migrated_rows"],
            "migrated_approvals": _h["migrated_approvals"],
            "programme_total": _h["programme_total"],
            "total_activities": len(filtered_activities),
            "programme_activities": counting_rules.blended_total(
                len(filtered_activities), _h["migrated_support"]),
            "total_employees": len(filtered_emp_users),
            "quotas": quota_rows,
            "renewal_attention_count": attention_data["total_attention_count"],
            # the pre-R38 shape of the history totals (callers read
            # these keys); the headline fields live one level up now.
            "migrated_totals": {k: _h[k] for k in
                                ("approvals", "support", "online_workshops",
                                 "employees_migrated", "first_year", "last_year")}
        },
        "filters": {
            "zone": filter_zone,
            "year": filter_year
        },
        "available_years": available_years,
        "state_wise_clubs": state_counts,
        "zone_wise_clubs": zone_counts,
        "year_wise_clubs": dict(sorted(year_counts.items())),
        "month_wise_clubs": dict(sorted(month_counts.items())),
        "status_wise_clubs": status_counts,
        "support_type_breakdown": support_type_counts,
        "renewal_health": renewal_health,
        "coverage_index": coverage_index,
        "zone_efficiency": zone_efficiency,
        "users": [{k: v for k, v in u.items() if k not in ["password_hash", "salt"]} for u in all_users]
    })
    return

# path == "/api/admin/employee-performance"
def get_admin_employee_performance(h, path, query_params):
    if not h._check_admin_access():
        return
    raw_year = query_params.get("year", ["ALL"])[0].strip()
    raw_month = query_params.get("month", ["ALL"])[0].strip()
    raw_state = query_params.get("state", ["ALL"])[0].strip() or query_params.get("states", ["ALL"])[0].strip()

    filter_year = raw_year if raw_year.upper() != "ALL" and raw_year else "ALL"
    filter_month = raw_month if raw_month.upper() != "ALL" and raw_month else "ALL"
    filter_state = raw_state if raw_state.upper() != "ALL" and raw_state else "ALL"

    month_map = {
        "january": 1, "jan": 1, "01": 1, "1": 1,
        "february": 2, "feb": 2, "02": 2, "2": 2,
        "march": 3, "mar": 3, "03": 3, "3": 3,
        "april": 4, "apr": 4, "04": 4, "4": 4,
        "may": 5, "05": 5, "5": 5,
        "june": 6, "jun": 6, "06": 6, "6": 6,
        "july": 7, "jul": 7, "07": 7, "7": 7,
        "august": 8, "aug": 8, "08": 8, "8": 8,
        "september": 9, "sep": 9, "sept": 9, "09": 9, "9": 9,
        "october": 10, "oct": 10, "10": 10,
        "november": 11, "nov": 11, "11": 11,
        "december": 12, "dec": 12, "12": 12
    }
    target_month_num = month_map.get(filter_month.lower()) if filter_month != "ALL" else None

    all_users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
    all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
    all_activities = SyncEngine.combined_activities_for()
    # R40: one history snapshot per request feeds every helper below.
    hist_rows = migration_history_rows()

    # Build club lookup for activity state resolution
    club_lookup = {c.get("club_id", "").strip().upper(): c for c in all_clubs if c.get("club_id")}

    # Discover available years dynamically
    # (R30v2: incl. MIGRATED HISTORY period years)
    available_years_set = {"2026", "2025", "2024"}
    for _hy in migration_period_years(rows=hist_rows):
        available_years_set.add(_hy)
    for c in all_clubs:
        ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
        if ts:
            dp = parse_iso_or_date(ts)
            if dp:
                available_years_set.add(str(dp.year))
    for a in all_activities:
        ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
        if ts:
            dp = parse_iso_or_date(ts)
            if dp:
                available_years_set.add(str(dp.year))
    available_years = sorted(list(available_years_set), reverse=True)
    # R30v3: the year filter is a CONTINUOUS programme range — gap
    # years must not vanish (the client expects 2020..current even
    # where a year like 2021 has zero entries), and earlier years
    # appear automatically when historical data reaches further back.
    _yrs = [int(y) for y in available_years_set if str(y).isdigit()]
    _lo = min(_yrs + [2020])
    _hi = max(_yrs + [datetime.now().year])
    available_years = [str(y) for y in range(_hi, _lo - 1, -1)]

    all_states_list = get_all_states()

    # Active employee officers
    officers = [u for u in all_users if u.get("role") == "EMPLOYEE"]

    # Pre-compute officer covers_state mapping and zone fallback mapping
    covers_state_by_emp: Dict[str, bool] = {}
    zone_to_default_emp: Dict[str, str] = {}
    for u in officers:
        eid = u.get("id", "").strip().upper()
        ezn = u.get("zone", "").strip()
        if ezn and ezn not in zone_to_default_emp:
            zone_to_default_emp[ezn] = eid
        assigned_states_list = [s.strip().lower() for s in (u.get("assigned_states", "")).split(",") if s.strip()]
        covers_state_by_emp[eid] = (filter_state == "ALL") or (filter_state.lower() in assigned_states_list)

    # Clubs approval aggregation across master clubs and priority club approval activities
    clubs_approved_by_emp_set: Dict[str, set] = {u.get("id", "").strip().upper(): set() for u in officers}
    club_approvals_standalone: Dict[str, int] = {u.get("id", "").strip().upper(): 0 for u in officers}

    for c in all_clubs:
        # R30: migrated/imported clubs are HISTORY — their performance
        # credit lives in the migrated baseline (injected below), never
        # in the live approval sets (anti-double-count: the club log and
        # the activity worksheets are separate sources by design).
        if counting_rules.is_imported_record(c):
            continue
        c_state = c.get("state", "").strip()
        if filter_state != "ALL" and c_state.lower() != filter_state.lower():
            continue

        ts = c.get("date_of_approval", "") or c.get("submission_timestamp", "") or c.get("updated_at", "")
        dp = parse_iso_or_date(ts) if ts else None
        if filter_year != "ALL":
            if not dp or str(dp.year) != filter_year:
                continue
        if target_month_num is not None:
            if not dp or dp.month != target_month_num:
                continue

        c_emp = c.get("approved_by_emp_id", "").strip().upper()
        if not c_emp:
            c_zn = c.get("zone", "").strip() or get_zone_for_state(c_state)
            c_emp = zone_to_default_emp.get(c_zn, "")

        cid = c.get("club_id", "").strip().upper()
        if c_emp in clubs_approved_by_emp_set:
            if cid:
                clubs_approved_by_emp_set[c_emp].add(cid)
            else:
                club_approvals_standalone[c_emp] += 1

    # Single-pass O(N) activities aggregation
    act_stats_by_emp: Dict[str, Dict[str, int]] = {
        u.get("id", "").strip().upper(): {"online": 0, "offline": 0, "other": 0} for u in officers
    }
    for a in all_activities:
        a_emp = a.get("emp_id", "").strip().upper()
        if a_emp not in act_stats_by_emp:
            continue

        cid = a.get("club_id", "").strip().upper()
        ref_club = club_lookup.get(cid)
        act_state = ref_club.get("state", "").strip() if ref_club else ""

        # State filtering for activities
        if filter_state != "ALL":
            if act_state:
                if act_state.lower() != filter_state.lower():
                    continue
            else:
                if not covers_state_by_emp.get(a_emp, False):
                    continue

        ts = a.get("timestamp", "") or a.get("submission_timestamp", "") or a.get("created_at", "")
        dp = parse_iso_or_date(ts) if ts else None
        ts_club = ref_club.get("date_of_approval", "") if ref_club else ""
        dp_club = parse_iso_or_date(ts_club) if ts_club else None

        date_match = True
        if filter_year != "ALL":
            act_yr = str(dp.year) if dp else ""
            club_yr = str(dp_club.year) if dp_club else ""
            if act_yr != filter_year and club_yr != filter_year:
                date_match = False
        if date_match and target_month_num is not None:
            act_m = dp.month if dp else 0
            club_m = dp_club.month if dp_club else 0
            if act_m != target_month_num and club_m != target_month_num:
                date_match = False

        if not date_match:
            continue

        # R29v2: the SAME bucketing rule as the quota card
        # (SyncEngine.bucket_activity) — catch-all "other" so a row
        # can never vanish from this matrix ("Registration Renewal",
        # "Data Correction", any future type all land in "other").
        bucket = SyncEngine.bucket_activity(a)

        if bucket == "skip":
            continue
        if bucket == "approval":
            if a_emp in clubs_approved_by_emp_set and cid and cid in club_lookup:
                if not counting_rules.is_imported_record(club_lookup.get(cid, {})):
                    clubs_approved_by_emp_set[a_emp].add(cid)
        elif bucket == "online":
            act_stats_by_emp[a_emp]["online"] += 1
        elif bucket == "offline":
            act_stats_by_emp[a_emp]["offline"] += 1
        else:
            act_stats_by_emp[a_emp]["other"] += 1

    evaluations = []
    for u in officers:
        emp_id = u.get("id", "").strip().upper()
        emp_name = u.get("full_name", "") or u.get("name", "") or emp_id
        emp_zone = u.get("zone", "") or "Other"
        assigned_states_str = u.get("assigned_states", "")
        covers_state = covers_state_by_emp.get(emp_id, True)

        clubs_approved = len(clubs_approved_by_emp_set.get(emp_id, set()))
        a_counts = act_stats_by_emp.get(emp_id, {"online": 0, "offline": 0, "other": 0})
        online_training = a_counts["online"]
        offline_training = a_counts["offline"]
        other_supports = a_counts["other"]

        # R30 (user decision: star rating = migrated baseline + live):
        # the client-worksheet baseline rides alongside live counts,
        # sliced by the SAME period/state filters as the live numbers.
        _base = migration_baselines_for(emp_id, filter_year,
                                        target_month_num, filter_state,
                                        rows=hist_rows)
        live_clubs_approved = clubs_approved
        live_other_supports = other_supports
        live_online_training = online_training
        clubs_approved += _base["approvals"]
        other_supports += _base["support"]
        online_training += _base["online_workshops"]

        # 3. 50/30/20/10 Weighted Score Calculation
        # 50% Club Approval + 30% Other Supports + 20% Offline Training + 10% Online Training
        weighted_score = round(
            (0.50 * clubs_approved) +
            (0.30 * other_supports) +
            (0.20 * offline_training) +
            (0.10 * online_training),
            2
        )

        evaluations.append({
            "emp_id": emp_id,
            "full_name": emp_name,
            "zone": emp_zone,
            "assigned_states": assigned_states_str,
            "clubs_approved": clubs_approved,
            "online_training": online_training,
            "offline_training": offline_training,
            "other_supports": other_supports,
            "total_activities": online_training + offline_training + other_supports,
            "weighted_score": weighted_score,
            "covers_selected_state": covers_state,
            # R30: honest split (live work vs migrated history)
            "live_clubs_approved": live_clubs_approved,
            "migrated_clubs_approved": _base["approvals"],
            "migrated_support": _base["support"],
            "migrated_online_workshops": _base["online_workshops"],
            "live_other_supports": live_other_supports,
            "live_online_training": live_online_training,
            "live_offline_training": offline_training
        })

    # Sort officers descending by weighted_score, then clubs_approved, then total_activities
    evaluations.sort(key=lambda x: (x["weighted_score"], x["clubs_approved"], x["total_activities"]), reverse=True)

    # Assign Ranks and Star Ratings (1 to 5 Stars)
    max_score = max((e["weighted_score"] for e in evaluations), default=0.0)
    for idx, e in enumerate(evaluations, start=1):
        e["rank"] = idx
        w_score = e["weighted_score"]
        if max_score > 0 and w_score > 0:
            ratio = w_score / max_score
            if ratio >= 0.80:
                stars = 5
            elif ratio >= 0.60:
                stars = 4
            elif ratio >= 0.40:
                stars = 3
            elif ratio >= 0.20:
                stars = 2
            else:
                stars = 1
        else:
            stars = 1
        e["stars"] = stars
        e["stars_display"] = "★" * stars + "☆" * (5 - stars)
        e["rating_label"] = f"{stars}.0 / 5.0"

    h._send_json({
        "success": True,
        "filters": {
            "year": filter_year,
            "month": filter_month,
            "state": filter_state
        },
        "available_years": available_years,
        "available_states": all_states_list,
        "weightage": {
            "club_approval_pct": 50,
            "other_supports_pct": 30,
            "offline_training_pct": 20,
            "online_training_pct": 10
        },
        "summary": {
            "total_officers": len(evaluations),
            "max_score": max_score,
            "top_officer": evaluations[0] if evaluations else None
        },
        "officers": evaluations
    })
    return

# path == "/api/admin/renewal-attention"
def get_admin_renewal_attention(h, path, query_params):
    if not h._check_admin_access():
        return
    # R42: opt-in paged mode - any attention query param (page / page_size /
    # filter / q) switches to the bounded paged response. Zero params keeps
    # today's response byte-compatible (existing callers and tests untouched).
    if any(k in query_params for k in ("page", "page_size", "filter", "q")):
        def _qp(name, default=""):
            vals = query_params.get(name) or []
            return vals[0] if vals else default
        page_data = AIDecisionEngine.get_renewal_attention_page(
            page=_qp("page", "1"),
            page_size=_qp("page_size", None),
            filter=_qp("filter", "ALL"),
            q=_qp("q", ""),
        )
        h._send_json({"success": True, **page_data})
        return
    attention_data = AIDecisionEngine.get_renewal_attention_data()
    h._send_json({"success": True, **attention_data})
    return

# path == "/api/admin/ai-insights"
def get_admin_ai_insights(h, path, query_params):
    if not h._check_admin_access():
        return
    insights = AIDecisionEngine.generate_strategic_report()
    h._send_json(insights)
    return
