"""
NDLI Club Management System - Emergency Database Restore Utility
Usage:
    python restore_backup.py [path/to/backup.zip or path/to/backup_dir]
"""
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from db.backup_engine import BackupEngine

def main():
    print("=" * 70)
    print("NDLI Club Management - Emergency Database Restore Console")
    print("Central Administration Office • IIT Kharagpur")
    print("=" * 70)

    target_source = None
    if len(sys.argv) > 1:
        target_source = sys.argv[1].strip()
    else:
        existing = BackupEngine.get_existing_backups()
        print("\nAvailable Local Historical Backups:")
        if not existing:
            print("  [No local backup snapshots found on disk]")
        else:
            for i, bdir in enumerate(existing, 1):
                print(f"  [{i}] {bdir.name}")

        print("\nOptions:")
        print("  - Enter the number of a local backup to restore (e.g. 1)")
        print("  - OR enter the path to a Google Drive backup ZIP file (e.g. ndli_backup_2026-09-14.zip)")
        print("  - OR press Enter to cancel\n")

        try:
            choice = input("Enter choice or path: ").strip()
        except EOFError:
            choice = ""

        if not choice:
            if existing:
                choice = "1"
                print(f"Defaulting to latest local backup: {existing[0].name}")
            else:
                print("No source specified. Exiting.")
                return

        if choice.isdigit() and 1 <= int(choice) <= len(existing):
            target_source = str(existing[int(choice) - 1])
        else:
            target_source = choice

    target_path = Path(target_source)
    if not target_path.exists():
        print(f"\n[ERROR] Target backup file or directory does not exist: {target_path}")
        sys.exit(1)

    print(f"\n[*] Initiating restoration from: {target_path}...")
    try:
        res = BackupEngine.restore_backup(target_path)
        print("\n" + "=" * 70)
        print("✓ RESTORATION COMPLETED SUCCESSFULLY!")
        print("=" * 70)
        print(f"Source: {res['source']}")
        print(f"Restored Master Files ({len(res['restored_master_files'])}): {', '.join(res['restored_master_files'])}")
        print(f"Restored Employee Nodes ({len(res['restored_employee_nodes'])}): {', '.join(res['restored_employee_nodes'])}")
        s = res['reconciliation_summary']
        print(f"Reconciliation: Synced {s['employees_synced']} nodes | Verified {s['total_master_clubs']} clubs & {s['total_master_activities']} activities.")
        print("\nThe database is now active, fully reconciled, and ready for operations.")
        print("=" * 70)
    except Exception as e:
        print(f"\n[ERROR] Restoration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
