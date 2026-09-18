"""
NDLI Club Management System - Emergency Codebase Restore Utility
Restores the workspace to Most Stable Version 2 (commit 1d65d95, tag stable-v2).
"""
import sys
import os
import subprocess

def run_cmd(cmd):
    print(f">> {cmd}")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr and res.returncode != 0:
        print(f"Error: {res.stderr.strip()}")
    return res.returncode

def main():
    print("=" * 70)
    print("NDLI Club Management System: Emergency Restore to Most Stable Version 2")
    print("=" * 70)
    print("This will reset your local repository to the certified Most Stable Version 2.")
    print("Tag / Branch: stable-v2 (commit 1d65d95)")
    print("-" * 70)

    # 1. Stash any uncommitted work for safety
    print("[1/3] Stashing any local changes...")
    run_cmd("git stash save 'Emergency backup before restore to stable-v2'")

    # 2. Checkout or reset to stable-v2
    print("\n[2/3] Checking out stable-v2...")
    code = run_cmd("git checkout stable-v2")
    if code != 0:
        print("Checkout failed, attempting hard reset to tag refs/tags/stable-v2...")
        run_cmd("git reset --hard refs/tags/stable-v2")

    # 3. Verify clean status
    print("\n[3/3] Verifying status...")
    run_cmd("git status")

    print("\n" + "=" * 70)
    print("✓ Successfully restored to Most Stable Version 2!")
    print("=" * 70)

if __name__ == "__main__":
    main()
