"""
NDLI Club Management - AI Decision and Strategic Roadmap Module
Analyzes node data and master databases to provide actionable strategic recommendations,
state penetration metrics, activity velocity, and roadmap planning for IIT Kharagpur Admins.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from config import MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV, EMPLOYEE_NODES_DIR
from db.schemas import CLUB_FIELDS, ACTIVITY_FIELDS, QUOTA_FIELDS
from db.csv_engine import CSVEngine
from state_zone_mapper import ZONE_STATE_MAP, get_all_states, get_zone_for_state


class AIDecisionEngine:
    """Foundational AI Analytics and Strategic Decision-Making Engine."""

    @classmethod
    def generate_strategic_report(cls) -> Dict[str, Any]:
        """
        Runs analytical pipelines across master databases to synthesize:
        - Regional Penetration Index
        - Activity Distribution & Support Quality
        - Renewal Vulnerability Index
        - Strategic AI Recommendations and Roadmap
        """
        clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
        activities = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
        quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)

        # 1. State and Zone Penetration
        all_states = get_all_states()
        clubs_by_state: Dict[str, int] = {s: 0 for s in all_states}
        clubs_by_zone: Dict[str, int] = {z: 0 for z in ZONE_STATE_MAP.keys()}

        for c in clubs:
            st = c.get("state", "").strip()
            zn = c.get("zone", "").strip()
            if st in clubs_by_state:
                clubs_by_state[st] += 1
            else:
                clubs_by_state[st] = 1

            if zn in clubs_by_zone:
                clubs_by_zone[zn] += 1
            else:
                clubs_by_zone[zn] = 1

        unrepresented_states = [s for s, count in clubs_by_state.items() if count == 0]
        top_states = sorted(clubs_by_state.items(), key=lambda x: x[1], reverse=True)[:5]

        # 2. Activity breakdown
        activity_type_counts: Dict[str, int] = {}
        for a in activities:
            stype = a.get("support_type", "Other")
            activity_type_counts[stype] = activity_type_counts.get(stype, 0) + 1

        # 3. Renewal Health
        attention_data = cls.get_renewal_attention_data()
        expiring_soon_clubs = attention_data["expiring_soon_clubs"]
        overdue_clubs = attention_data["overdue_clubs"]

        # 4. Strategic Recommendations Generation
        recommendations: List[Dict[str, str]] = []

        # Rec 1: Underrepresented states
        if unrepresented_states:
            sample_unrep = ", ".join(unrepresented_states[:4])
            recommendations.append({
                "category": "Regional Outreach",
                "priority": "High",
                "title": "Establish Foothold in Unrepresented States",
                "insight": f"{len(unrepresented_states)} out of {len(all_states)} States/UTs currently have zero registered NDLI clubs (e.g., {sample_unrep}).",
                "action": "Task corresponding regional employees to initiate outreach to State Directorate of Higher Education in these states."
            })

        # Rec 2: Zone balancing
        lowest_zone = min(clubs_by_zone.items(), key=lambda x: x[1]) if clubs_by_zone else ("None", 0)
        highest_zone = max(clubs_by_zone.items(), key=lambda x: x[1]) if clubs_by_zone else ("None", 0)
        if lowest_zone[1] < highest_zone[1]:
            recommendations.append({
                "category": "Resource Allocation",
                "priority": "Medium",
                "title": f"Expand Capacity in {lowest_zone[0]} Zone",
                "insight": f"{lowest_zone[0]} Zone currently trails with {lowest_zone[1]} clubs compared to {highest_zone[0]} Zone with {highest_zone[1]} clubs.",
                "action": f"Schedule targeted online awareness sessions and allocate secondary support to {lowest_zone[0]} Zone nodal officer."
            })

        # Rec 3: Training format optimization
        online_train = activity_type_counts.get("Online training", 0)
        offline_train = activity_type_counts.get("Offline training", 0)
        total_train = online_train + offline_train
        if total_train > 0 and (offline_train / total_train) < 0.25:
            recommendations.append({
                "category": "Capacity Building",
                "priority": "Medium",
                "title": "Increase High-Impact Offline Workshops",
                "insight": f"Offline training accounts for only {offline_train} out of {total_train} training sessions ({int(offline_train/total_train*100)}%).",
                "action": "Incentivize on-campus physical training visits to increase institutional engagement and executive buy-in."
            })

        # Rec 4: Renewal alerts
        if expiring_soon_clubs or overdue_clubs:
            recommendations.append({
                "category": "Retention & Renewal",
                "priority": "High",
                "title": "Prevent Registration Churn",
                "insight": f"{len(expiring_soon_clubs)} clubs have renewals due within 90 days, and {len(overdue_clubs)} are overdue.",
                "action": "Trigger automated renewal notification reminders to President and Secretary email addresses."
            })

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "total_clubs": len(clubs),
                "total_activities": len(activities),
                "unrepresented_states_count": len(unrepresented_states),
                "active_employees_count": len(quotas),
                "expiring_soon_count": len(expiring_soon_clubs),
                "overdue_count": len(overdue_clubs),
                "renewal_attention_count": len(expiring_soon_clubs) + len(overdue_clubs)
            },
            "zone_distribution": clubs_by_zone,
            "activity_distribution": activity_type_counts,
            "top_states": top_states,
            "unrepresented_states": unrepresented_states,
            "strategic_recommendations": recommendations,
            "suggested_quarterly_target": max(len(clubs) * 2, 25),
            "renewal_attention": attention_data
        }

    @classmethod
    def get_renewal_attention_data(cls, clubs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Scans clubs in database to identify those requiring renewal attention:
        1. Overdue clubs: renewal date is in the past (< today).
        2. Expiring soon clubs: renewal date is within 90 days (0 <= delta <= 90 days).
        If renewal_date is empty, calculates automatically as establishment date + 1 year.
        Includes computed days_diff, days_overdue / days_left, badges, and next renewal dates.
        """
        from db.sync_engine import calculate_next_renewal_date, parse_iso_or_date

        if clubs is None:
            clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            seen_ids = {c.get("club_id", "").strip().upper() for c in clubs if c.get("club_id")}
            if EMPLOYEE_NODES_DIR.exists():
                for emp_dir in EMPLOYEE_NODES_DIR.iterdir():
                    if emp_dir.is_dir():
                        node_clubs = CSVEngine.read_all(emp_dir / "clubs.csv", CLUB_FIELDS)
                        for nc in node_clubs:
                            nid = nc.get("club_id", "").strip().upper()
                            if nid and nid not in seen_ids:
                                clubs.append(nc)
                                seen_ids.add(nid)
        today = datetime.now(timezone.utc).date()

        overdue_clubs: List[Dict[str, Any]] = []
        expiring_soon_clubs: List[Dict[str, Any]] = []

        for c in clubs:
            doa_str = c.get("date_of_approval", "").strip() or c.get("submission_timestamp", "").strip()
            last_ren_str = c.get("last_renewal_date", "").strip()
            ren_date_str = c.get("renewal_date", "").strip() or c.get("next_renewal_date", "").strip()

            if not ren_date_str:
                if last_ren_str:
                    ren_date_str = calculate_next_renewal_date(last_renewal_date=last_ren_str)
                elif doa_str:
                    ren_date_str = calculate_next_renewal_date(date_of_approval=doa_str)
                else:
                    continue

            ren_date = parse_iso_or_date(ren_date_str)
            if not ren_date:
                continue

            delta = (ren_date - today).days
            club_data = dict(c)
            club_data["date_of_approval"] = doa_str
            club_data["submission_timestamp"] = doa_str
            club_data["last_renewal_date"] = last_ren_str
            club_data["renewal_date"] = ren_date_str
            club_data["next_renewal_date"] = ren_date_str
            club_data["effective_renewal_date"] = ren_date.isoformat()
            club_data["next_renewal_due_date"] = ren_date.isoformat()
            club_data["days_diff"] = delta

            if delta < 0:
                club_data["attention_type"] = "Overdue"
                club_data["days_overdue"] = abs(delta)
                club_data["days_left"] = 0
                club_data["badge_label"] = f"{abs(delta)} days overdue"
                club_data["badge_class"] = "pill-danger"
                overdue_clubs.append(club_data)
            elif delta <= 90:
                club_data["attention_type"] = "Expiring Soon"
                club_data["days_overdue"] = 0
                club_data["days_left"] = delta
                club_data["badge_label"] = f"{delta} days left" if delta > 0 else "Expires today"
                club_data["badge_class"] = "pill-warning"
                expiring_soon_clubs.append(club_data)

        # Sort overdue by oldest overdue first (smallest/most negative delta)
        overdue_clubs.sort(key=lambda x: x["days_diff"])
        # Sort expiring soon by soonest first
        expiring_soon_clubs.sort(key=lambda x: x["days_diff"])

        all_attention = overdue_clubs + expiring_soon_clubs

        return {
            "today": today.isoformat(),
            "total_attention_count": len(all_attention),
            "overdue_count": len(overdue_clubs),
            "expiring_soon_count": len(expiring_soon_clubs),
            "clubs": all_attention,
            "overdue_clubs": overdue_clubs,
            "expiring_soon_clubs": expiring_soon_clubs
        }
