"""
NDLI Club Management - Database Initialization and Seeding Script
Creates Master DB and all 7 Employee Node DBs with Initial Users and Benchmark Records.
"""
import shutil
from config import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_NAME,
    INITIAL_EMPLOYEES,
    EMPLOYEE_NODES_DIR,
    MASTER_USERS_CSV,
    MASTER_QUOTAS_CSV,
    MASTER_CLUBS_CSV,
    MASTER_ACTIVITIES_CSV,
    MASTER_ISSUES_CSV
)
from auth import AuthService
from db.sync_engine import SyncEngine
from db.csv_engine import CSVEngine
from db.schemas import USER_FIELDS, QUOTA_FIELDS, CLUB_FIELDS, ACTIVITY_FIELDS, ISSUE_FIELDS
from state_zone_mapper import get_zone_for_state

# Benchmark Seed Clubs to populate initial dashboards and test search/edit
BENCHMARK_CLUBS = [
    {
        "club_id": "NDLI-EMP01-002",
        "reg_no": "REG-2025-EMP01-002",
        "institution_name": "Delhi Advanced Technical Institute",
        "state": "Delhi",
        "patron_email": "director@dati.ac.in",
        "president_email": "pres.dati@dati.ac.in",
        "secretary_email": "sec.dati@dati.ac.in",
        "emp_id": "EMP01",
        "date_of_approval": "2024-08-15T10:00:00Z",
        "last_renewal_date": "",
        "renewal_date": "2025-08-15"
    },
    {
        "club_id": "NDLI-WB-101",
        "reg_no": "REG-2024-WB-001",
        "institution_name": "Indian Institute of Technology Kharagpur",
        "state": "West Bengal",
        "patron_email": "director@iitkgp.ac.in",
        "president_email": "president.club@iitkgp.ac.in",
        "secretary_email": "secretary.club@iitkgp.ac.in",
        "emp_id": "EMP04",
        "date_of_approval": "2025-03-31T10:00:00Z",
        "last_renewal_date": "2026-03-31T10:00:00Z",
        "renewal_date": "2027-03-31"
    },
    {
        "club_id": "NDLI-DL-102",
        "reg_no": "REG-2024-DL-002",
        "institution_name": "Delhi Technological University",
        "state": "Delhi",
        "patron_email": "vc@dtu.ac.in",
        "president_email": "ndli.pres@dtu.ac.in",
        "secretary_email": "ndli.sec@dtu.ac.in",
        "emp_id": "EMP01",
        "date_of_approval": "2024-12-15T11:30:00Z",
        "last_renewal_date": "2025-12-15T11:30:00Z",
        "renewal_date": "2026-12-15"
    },
    {
        "club_id": "NDLI-MH-103",
        "reg_no": "REG-2024-MH-003",
        "institution_name": "College of Engineering Pune (COEP)",
        "state": "Maharashtra",
        "patron_email": "director@coeptech.ac.in",
        "president_email": "club.head@coeptech.ac.in",
        "secretary_email": "club.sec@coeptech.ac.in",
        "emp_id": "EMP03",
        "date_of_approval": "2025-11-20T11:00:00Z",
        "last_renewal_date": "",
        "renewal_date": "2026-11-20"
    },
    {
        "club_id": "NDLI-TN-104",
        "reg_no": "REG-2024-TN-004",
        "institution_name": "Anna University Chennai",
        "state": "Tamil Nadu",
        "patron_email": "vc@annauniv.edu",
        "president_email": "pres.ndli@annauniv.edu",
        "secretary_email": "sec.ndli@annauniv.edu",
        "emp_id": "EMP07",
        "date_of_approval": "2025-01-10T12:00:00Z",
        "last_renewal_date": "2026-01-10T12:00:00Z",
        "renewal_date": "2027-01-10"
    },
    {
        "club_id": "NDLI-AS-105",
        "reg_no": "REG-2024-AS-005",
        "institution_name": "Gauhati University",
        "state": "Assam",
        "patron_email": "vc@gauhati.ac.in",
        "president_email": "ndli.gu@gauhati.ac.in",
        "secretary_email": "secretary.gu@gauhati.ac.in",
        "emp_id": "EMP05",
        "date_of_approval": "2025-09-30T09:15:00Z",
        "last_renewal_date": "",
        "renewal_date": "2026-09-30"
    },
    {
        "club_id": "NDLI-MP-106",
        "reg_no": "REG-2024-MP-006",
        "institution_name": "Maulana Azad National Institute of Technology Bhopal",
        "state": "Madhya Pradesh",
        "patron_email": "director@manit.ac.in",
        "president_email": "ndli.head@manit.ac.in",
        "secretary_email": "ndli.coord@manit.ac.in",
        "emp_id": "EMP02",
        "date_of_approval": "2025-10-15T14:20:00Z",
        "last_renewal_date": "",
        "renewal_date": "2026-10-15"
    },
    {
        "club_id": "NDLI-KA-107",
        "reg_no": "REG-2024-KA-007",
        "institution_name": "Indian Institute of Science Bengaluru",
        "state": "Karnataka",
        "patron_email": "director@iisc.ac.in",
        "president_email": "pres.ndli@iisc.ac.in",
        "secretary_email": "sec.ndli@iisc.ac.in",
        "emp_id": "EMP06",
        "date_of_approval": "2025-05-01T10:30:00Z",
        "last_renewal_date": "2026-05-01T10:30:00Z",
        "renewal_date": "2027-05-01"
    },
    {
        "club_id": "NDLI-TEST-999",
        "reg_no": "REG-TEST-999",
        "institution_name": "Test Engineering College Raipur",
        "state": "Chhattisgarh",
        "patron_email": "patron@test.edu",
        "president_email": "pres@test.edu",
        "secretary_email": "sec@test.edu",
        "emp_id": "EMP02",
        "date_of_approval": "2026-09-12T17:53:12.028679+00:00",
        "last_renewal_date": "",
        "renewal_date": "2027-09-12"
    },
    {
        "club_id": "NDLI-AUTO-REN-01",
        "reg_no": "REG-AUTO-01",
        "institution_name": "Automated Renewal University",
        "state": "Assam",
        "patron_email": "patron@auto.edu",
        "president_email": "pres@auto.edu",
        "secretary_email": "sec@auto.edu",
        "emp_id": "EMP05",
        "date_of_approval": "2026-09-12T17:53:12.098579+00:00",
        "last_renewal_date": "2026-09-12T17:53:12.121991+00:00",
        "renewal_date": "2027-09-12"
    }
]


def initialize_database() -> None:
    """Initializes master schemas, registers admin and 7 employee nodes, and seeds records."""
    print("=" * 70)
    print("NDLI Club Management System: Initializing Database & Auth...")
    print("=" * 70)

    # 1. Initialize Storage Directories & Clean Non-initial Nodes
    SyncEngine.initialize_storage_hierarchy()
    valid_emp_ids = {emp["id"].lower() for emp in INITIAL_EMPLOYEES}
    if EMPLOYEE_NODES_DIR.exists():
        for item in EMPLOYEE_NODES_DIR.iterdir():
            if item.is_dir() and item.name.lower() not in valid_emp_ids:
                shutil.rmtree(str(item), ignore_errors=True)

    valid_user_ids = {"ADMIN01"}.union({emp["id"].upper() for emp in INITIAL_EMPLOYEES})
    if MASTER_USERS_CSV.exists():
        users = CSVEngine.read_all(MASTER_USERS_CSV, USER_FIELDS)
        cleaned_users = [u for u in users if u.get("id", "").strip().upper() in valid_user_ids]
        CSVEngine.write_all(MASTER_USERS_CSV, USER_FIELDS, cleaned_users)

    if MASTER_QUOTAS_CSV.exists():
        quotas = CSVEngine.read_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS)
        cleaned_quotas = [q for q in quotas if q.get("emp_id", "").strip().upper() in valid_user_ids]
        CSVEngine.write_all(MASTER_QUOTAS_CSV, QUOTA_FIELDS, cleaned_quotas)

    # Clean clubs, activities, and issues so benchmark records are re-seeded cleanly
    CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, [])
    CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, [])
    CSVEngine.write_all(MASTER_ISSUES_CSV, ISSUE_FIELDS, [])
    for emp in INITIAL_EMPLOYEES:
        emp_id = emp["id"]
        SyncEngine.get_employee_dir(emp_id).mkdir(parents=True, exist_ok=True)
        CSVEngine.write_all(SyncEngine.get_employee_clubs_path(emp_id), CLUB_FIELDS, [])
        CSVEngine.write_all(SyncEngine.get_employee_activities_path(emp_id), ACTIVITY_FIELDS, [])
        CSVEngine.write_all(SyncEngine.get_employee_issues_path(emp_id), ISSUE_FIELDS, [])

    print("[1/5] Initialized storage hierarchy and master CSV schemas.")

    # 2. Provision Admin User (IIT Kharagpur)
    AuthService.register_or_update_user(
        user_id="ADMIN01",
        email=DEFAULT_ADMIN_EMAIL,
        password=DEFAULT_ADMIN_PASSWORD,
        full_name=DEFAULT_ADMIN_NAME,
        role="ADMIN",
        zone="Central Coordination (IIT KGP)",
        assigned_states="All India",
        is_active="1"
    )
    print(f"[2/5] Registered IIT Kharagpur Master Admin: {DEFAULT_ADMIN_EMAIL}")

    # 3. Provision 7 Employee Nodes
    for emp in INITIAL_EMPLOYEES:
        AuthService.register_or_update_user(
            user_id=emp["id"],
            email=emp["email"],
            password=emp["password"],
            full_name=emp["full_name"],
            role="EMPLOYEE",
            zone=emp["zone"],
            assigned_states=emp["assigned_states"],
            is_active="1"
        )
        print(f"[3/5] Provisioned node for {emp['id']}: {emp['full_name']} ({emp['zone']} Zone)")

    # 4. Seed Benchmark Clubs and Activities
    for club in BENCHMARK_CLUBS:
        state = club["state"]
        zone = get_zone_for_state(state) or "Unknown"
        payload = {
            "club_id": club["club_id"],
            "reg_no": club["reg_no"],
            "institution_name": club["institution_name"],
            "state": state,
            "zone": zone,
            "patron_email": club["patron_email"],
            "president_email": club["president_email"],
            "secretary_email": club["secretary_email"],
            "date_of_approval": club.get("date_of_approval", ""),
            "last_renewal_date": club.get("last_renewal_date", ""),
            "renewal_date": club["renewal_date"]
        }
        SyncEngine.approve_new_club(emp_id=club["emp_id"], club_data=payload)

    # Seed some support logs
    SyncEngine.log_support_activity("EMP01", "Phone call and remote assistance", "Assisted Delhi college with registration portal")
    SyncEngine.log_support_activity("EMP01", "Closing of OS Ticket", "Ticket #4491 resolved")
    SyncEngine.log_support_activity("EMP02", "Online training", "Conducted webinar for 15 MP schools")
    SyncEngine.log_support_activity("EMP03", "Offline training", "Workshop at Pune University")
    SyncEngine.log_support_activity("EMP04", "Closing of OS Ticket", "Ticket #4502 resolved")
    SyncEngine.log_support_activity("EMP06", "Phone call and remote assistance", "Assisted Bangalore tech campus")

    print(f"[4/5] Seeded benchmark clubs and support activity logs.")

    # 5. Full Reconciliation Run
    summary = SyncEngine.reconcile_all_nodes()
    print(f"[5/5] Reconciled all nodes with Master DB: {summary}")
    print("=" * 70)
    print("Database & Auth Initialization Complete!")
    print("=" * 70)


if __name__ == "__main__":
    initialize_database()
