"""db/sync/clubs.py - club lifecycle: approve, update, correct, renew, delete.

R46: SyncEngine methods moved verbatim from db/sync_engine.py.
`class SyncClubsMixin` is assembled into db.sync_engine.SyncEngine.
"""



from config import MASTER_ACTIVITIES_CSV, MASTER_CLUBS_CSV, MASTER_QUOTAS_CSV

from datetime import datetime, timezone

from db.csv_engine import CSVEngine

from db.schemas import ACTIVITY_FIELDS, CLUB_FIELDS

from db.sync.dates import calculate_next_renewal_date, calculate_next_renewal_due, parse_iso_datetime, parse_iso_or_date

from db.sync.state import RENEWAL_DEDUPE_WINDOW_SEC, _SYNC_LOCK

from state_zone_mapper import get_zone_for_state

from typing import Any, Dict, Optional



class SyncClubsMixin:
    """SyncClubsMixin - SyncEngine methods moved verbatim (R46)."""

    @classmethod
    def approve_new_club(
        cls,
        emp_id: str,
        club_data: Dict[str, Any],
        confirm_cloud_sync: bool = True
    ) -> Dict[str, Any]:
        """
        SEC B & C: Club Approval.
        - Captures exact Date of Approval (date_of_approval) upon initial creation
        - Automatically computes 1-year registration validity (renewal_date) from Date of Approval
        - Sets initial last_renewal_date as blank ("")
        - Writes to Employee Node clubs.csv
        - Real-time upsert to Master master_clubs.csv
        - Logs a priority activity in both Employee and Master activity logs
        - Increments employee's performance quota for priority activity

        `confirm_cloud_sync` (default True): block synchronously until the
        Google Drive mirror is confirmed for this club's files, so a normal
        single-club API call can honestly report whether it's durable. Bulk
        operations (e.g. bulk import commits) pass False here and instead
        perform ONE synchronous confirmation pass across every affected file
        at the very end -- doing a full synchronous Drive round-trip for
        every single club in a large batch is what previously made a 28-club
        reseed take minutes (near-)hanging the request; batching the
        confirmation into one pass is the fix.
        """
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()
            club_id = str(club_data.get("club_id", "")).strip().upper()

            ren_input = str(club_data.get("renewal_date", "")).strip() or str(club_data.get("next_renewal_date", "")).strip()
            parsed_ren_input = parse_iso_or_date(ren_input) if ren_input else None

            # Date of Approval: auto-captured exact date and time of club creation/formation
            raw_doa = str(club_data.get("date_of_approval", "")).strip() or str(club_data.get("submission_timestamp", "")).strip()
            last_renewal_date = str(club_data.get("last_renewal_date", "")).strip()

            # R24 record provenance, R30-corrected: "imported" follows the
            # EXPLICIT import action (record_mode="import" — the R24 import
            # flow, the R26 bulk import, the whole migration toolkit).
            # Everything else is "created" (live app, existing rules).
            # The old dates heuristic (explicit dates => "imported") mis-tagged
            # engine-level creations that legitimately carry real dates
            # (init_db benchmark seeds, internal callers) and R30's
            # anti-double-count switch then swallowed their live quota credit.
            # Through the validated HTTP flows provenance is unchanged:
            # historical dates are accepted ONLY with record_mode="import"
            # (schemas.validate_club_payload), so "imported" there is exactly
            # the import path — PA's persisted rows map 1:1, no re-tagging.
            _mode = str(club_data.get("record_mode", "")).strip().lower()
            record_origin = "imported" if _mode == "import" else "created"

            if raw_doa:
                date_of_approval = raw_doa
            elif parsed_ren_input and not last_renewal_date:
                # If approval date was not provided but a renewal date was specified:
                # For overdue / historical clubs, date_of_approval must logically have been
                # 1 year prior to the renewal date.
                try:
                    derived_doa = parsed_ren_input.replace(year=parsed_ren_input.year - 1)
                except ValueError:
                    derived_doa = parsed_ren_input.replace(year=parsed_ren_input.year - 1, month=2, day=28)
                date_of_approval = f"{derived_doa.isoformat()}T10:00:00Z"
            else:
                date_of_approval = now_iso

            # Ensure upcoming renewal date can NEVER be earlier than date_of_approval or last_renewal_date
            ren_date = calculate_next_renewal_date(
                date_of_approval=date_of_approval,
                last_renewal_date=last_renewal_date,
                renewal_date=ren_input
            )

            st_val = str(club_data.get("state", "")).strip()
            zn_val = str(club_data.get("zone", "")).strip() or get_zone_for_state(st_val) or "Unknown"

            club_record = {
                "club_id": club_id,
                "reg_no": str(club_data.get("reg_no", "")).strip(),
                "institution_name": str(club_data.get("institution_name", "")).strip(),
                "state": st_val,
                "zone": zn_val,
                "patron_email": str(club_data.get("patron_email", "")).strip().lower(),
                "president_email": str(club_data.get("president_email", "")).strip().lower(),
                "secretary_email": str(club_data.get("secretary_email", "")).strip().lower(),
                "date_of_approval": date_of_approval,
                "last_renewal_date": last_renewal_date,
                "renewal_date": ren_date,
                "status": str(club_data.get("status", "")).strip() or "Approved",
                "approved_by_emp_id": emp_id,
                "updated_at": now_iso,
                "submission_timestamp": date_of_approval,
                "next_renewal_date": ren_date,
                "record_origin": record_origin
            }

            # 1. Write to Employee Node DB
            emp_clubs_path = cls.get_employee_clubs_path(emp_id)
            CSVEngine.upsert_row(emp_clubs_path, CLUB_FIELDS, "club_id", club_record)

            # 2. Real-time sync to Master DB
            CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", club_record)

            # 3. Log priority activity in Node & Master -- but only ONCE per
            # club_id. Re-submitting/re-saving the same club (a double
            # click, retried request, or repeat testing) must not mint a
            # fresh "Club Approval" activity_id every time: that is exactly
            # what let a single club accumulate many duplicate log rows,
            # which in turn inflated an employee's quota (before the
            # unique-club-count fix) and cluttered their activity log with
            # noise unrelated to any real, distinct approval.
            emp_act_path = cls.get_employee_activities_path(emp_id)
            existing_acts = CSVEngine.read_all(emp_act_path, ACTIVITY_FIELDS) if emp_act_path.exists() else []
            already_logged = any(
                a.get("club_id", "").strip().upper() == club_id
                and (
                    a.get("support_type", "").strip() == "Club Approval"
                    or a.get("activity_id", "").strip().startswith(f"ACT-PRIORITY-{emp_id}")
                )
                for a in existing_acts
            )
            if not already_logged:
                act_id = f"ACT-PRIORITY-{emp_id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
                activity_row = {
                    "activity_id": act_id,
                    "emp_id": emp_id,
                    "timestamp": now_iso,
                    "support_type": "Club Approval",
                    "priority_flag": "1",  # Priority activity
                    "club_id": club_id,
                    "notes": f"Approved new NDLI Club: {club_record['institution_name']} ({club_id})"
                }
                CSVEngine.append_row(emp_act_path, ACTIVITY_FIELDS, activity_row)
                CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)

            # 4. Increment performance quota -- only for a genuinely new
            # approval, not a resubmission of an already-logged club.
            if not already_logged:
                cls._increment_quota(emp_id, clubs_inc=1, now_iso=now_iso)

            # 5. On hosts with no persistent disk (e.g. Render free tier),
            # local disk does not survive a restart/redeploy/scale-to-zero
            # cycle -- only a confirmed Google Drive mirror does. Block here
            # until the affected files are durably confirmed, so a caller
            # that gets "success" back can trust the record will still be
            # there after the next restart, rather than finding out 30
            # minutes later that it silently vanished.
            cloud_sync_confirmed = True
            if confirm_cloud_sync:
                try:
                    from db.storage_adapter import get_storage_adapter
                    adapter = get_storage_adapter()
                    if hasattr(adapter, "confirm_durable"):
                        cloud_sync_confirmed = adapter.confirm_durable([
                            emp_clubs_path,
                            MASTER_CLUBS_CSV,
                            emp_act_path,
                            MASTER_ACTIVITIES_CSV,
                        ])
                except Exception:
                    cloud_sync_confirmed = False
            else:
                # Caller will confirm sync in one batched pass later; the
                # local write above already fired the normal async
                # background mirror upload as a best-effort head start.
                cloud_sync_confirmed = None

            club_record = dict(club_record)
            club_record["cloud_sync_confirmed"] = cloud_sync_confirmed
            return club_record


    @classmethod
    def delete_club(cls, club_id: str) -> Dict[str, Any]:
        """
        Permanently removes a club from both the master DB and whichever
        employee node it belongs to, then synchronously confirms the
        removal reached Google Drive -- so a deleted club doesn't silently
        reappear after a restart pulls a stale (pre-deletion) Drive copy,
        the same class of bug this file's confirm_durable was built to
        catch on the write side.

        Also purges matching activity-log entries for this club (both the
        owning employee's node and master logs) and recomputes that
        employee's quota counters from scratch, so deleting a club can never
        leave a stale, inflated "clubs approved" count behind -- the exact
        drift that previously made an employee's dashboard disagree with
        the live master club count.
        """
        club_id = str(club_id).strip().upper()
        if not club_id:
            raise ValueError("club_id is required")

        with _SYNC_LOCK:
            master_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS)
            target = next((c for c in master_clubs if c.get("club_id", "").strip().upper() == club_id), None)
            if target is None:
                return {"deleted": False, "message": f"No club found with club_id '{club_id}'."}

            approved_by = str(target.get("approved_by_emp_id", "")).strip().upper()

            # 1. Remove from Master DB
            remaining_master = [c for c in master_clubs if c.get("club_id", "").strip().upper() != club_id]
            CSVEngine.write_all(MASTER_CLUBS_CSV, CLUB_FIELDS, remaining_master)

            # 2. Remove from the owning employee's node, if known
            emp_clubs_path = None
            if approved_by:
                emp_clubs_path = cls.get_employee_clubs_path(approved_by)
                if emp_clubs_path.exists():
                    node_clubs = CSVEngine.read_all(emp_clubs_path, CLUB_FIELDS)
                    remaining_node = [c for c in node_clubs if c.get("club_id", "").strip().upper() != club_id]
                    CSVEngine.write_all(emp_clubs_path, CLUB_FIELDS, remaining_node)

            # 2b. Purge matching activity-log entries (master + node) so
            # quota recomputation below reflects the truth, not stale
            # "Club Approval" entries still pointing at a now-deleted club.
            master_acts = CSVEngine.read_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS)
            remaining_master_acts = [a for a in master_acts if a.get("club_id", "").strip().upper() != club_id]
            if len(remaining_master_acts) != len(master_acts):
                CSVEngine.write_all(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, remaining_master_acts)

            emp_act_path = None
            if approved_by:
                emp_act_path = cls.get_employee_activities_path(approved_by)
                if emp_act_path.exists():
                    node_acts = CSVEngine.read_all(emp_act_path, ACTIVITY_FIELDS)
                    remaining_node_acts = [a for a in node_acts if a.get("club_id", "").strip().upper() != club_id]
                    if len(remaining_node_acts) != len(node_acts):
                        CSVEngine.write_all(emp_act_path, ACTIVITY_FIELDS, remaining_node_acts)

            # 3. Recompute the owning employee's quota from scratch -- the
            # permanent fix, replacing any stale incremented/ratcheted value.
            if approved_by:
                cls.recompute_and_persist_quota(approved_by)

            # 4. Synchronously confirm the deletion reached Drive, same as
            # approve_new_club does for a write -- otherwise a stale Drive
            # copy could restore the "deleted" club on the next restart.
            cloud_sync_confirmed = True
            try:
                from db.storage_adapter import get_storage_adapter
                adapter = get_storage_adapter()
                if hasattr(adapter, "confirm_durable"):
                    paths_to_confirm = [MASTER_CLUBS_CSV, MASTER_ACTIVITIES_CSV, MASTER_QUOTAS_CSV]
                    if emp_clubs_path:
                        paths_to_confirm.append(emp_clubs_path)
                    if emp_act_path:
                        paths_to_confirm.append(emp_act_path)
                    cloud_sync_confirmed = adapter.confirm_durable(paths_to_confirm)
            except Exception:
                cloud_sync_confirmed = False

            return {
                "deleted": True,
                "club_id": club_id,
                "institution_name": target.get("institution_name", ""),
                "cloud_sync_confirmed": cloud_sync_confirmed
            }


    @classmethod
    def update_club(
        cls,
        emp_id: str,
        club_id: str,
        updated_fields: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Updates an existing club record across both employee node and master CSV."""
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()

            # Check master clubs using O(1) key index
            target_record = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", club_id, CLUB_FIELDS)
            if not target_record:
                return None

            # Apply updates
            for k, v in updated_fields.items():
                if k in CLUB_FIELDS and k != "club_id":
                    # date_of_approval is immutable inception timestamp: do not allow blanking or overwriting an existing value
                    if k == "date_of_approval" and target_record.get("date_of_approval"):
                        if not str(v).strip():
                            continue
                    target_record[k] = str(v).strip()

            # Synchronize compatibility aliases
            if target_record.get("date_of_approval"):
                target_record["submission_timestamp"] = target_record["date_of_approval"]
            elif target_record.get("submission_timestamp"):
                target_record["date_of_approval"] = target_record["submission_timestamp"]

            if "renewal_date" in updated_fields or "next_renewal_date" in updated_fields:
                doa = target_record.get("date_of_approval", "")
                lrd = target_record.get("last_renewal_date", "")
                cur_ren = target_record.get("renewal_date", "") or target_record.get("next_renewal_date", "")
                valid_ren = calculate_next_renewal_date(date_of_approval=doa, last_renewal_date=lrd, renewal_date=cur_ren)
                target_record["renewal_date"] = valid_ren
                target_record["next_renewal_date"] = valid_ren

            # If state was updated or zone is empty/Unknown, auto-map zone
            c_state = target_record.get("state", "").strip()
            if not target_record.get("zone") or target_record.get("zone") == "Unknown" or ("state" in updated_fields and c_state):
                target_record["zone"] = get_zone_for_state(c_state) or target_record.get("zone", "") or "Unknown"

            target_record["updated_at"] = now_iso

            # Sync to Master
            CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", target_record)

            # Sync to original approving employee node if applicable
            orig_emp = target_record.get("approved_by_emp_id", "").strip().upper()
            if orig_emp and orig_emp.startswith("EMP"):
                orig_path = cls.get_employee_clubs_path(orig_emp)
                if orig_path.parent.exists():
                    CSVEngine.upsert_row(orig_path, CLUB_FIELDS, "club_id", target_record)

            # Sync to updater's node if different employee
            clean_updater = emp_id.strip().upper()
            if clean_updater and clean_updater.startswith("EMP") and clean_updater != orig_emp:
                updater_path = cls.get_employee_clubs_path(clean_updater)
                if updater_path.parent.exists():
                    CSVEngine.upsert_row(updater_path, CLUB_FIELDS, "club_id", target_record)

            return target_record


    @classmethod
    def correct_club_dates(
        cls,
        club_id: str,
        date_of_approval: str,
        last_renewal_date: str = "",
        admin_id: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        R24: Admin-only historical date correction — the dedicated, logged path.
        The general club-update route never alters these dates (immutability);
        the API layer validates the window (2019-01-01 <= doa <= today and
        doa <= last_renewal <= today) before this method is reached. The upcoming
        renewal is recomputed from the corrected anchor (+1 year, Renewal
        Protocol rule) and a "Data Correction" activity row is logged in the
        owning employee node and the master activity log.
        """
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()
            target_record = CSVEngine.find_by_key(
                MASTER_CLUBS_CSV, "club_id", str(club_id).strip().upper(), CLUB_FIELDS)
            if not target_record:
                return None

            target_record["date_of_approval"] = str(date_of_approval).strip()
            lrd = str(last_renewal_date or "").strip()
            target_record["last_renewal_date"] = lrd
            # Compatibility alias (existing convention: submission_timestamp mirrors DOA).
            target_record["submission_timestamp"] = target_record["date_of_approval"]
            ren = calculate_next_renewal_date(
                date_of_approval=target_record["date_of_approval"],
                last_renewal_date=lrd
            )
            target_record["renewal_date"] = ren
            target_record["next_renewal_date"] = ren
            target_record["updated_at"] = now_iso

            # Sync to Master + original approving employee node (same write
            # pattern as update_club).
            CSVEngine.upsert_row(MASTER_CLUBS_CSV, CLUB_FIELDS, "club_id", target_record)
            orig_emp = target_record.get("approved_by_emp_id", "").strip().upper()
            if orig_emp and orig_emp.startswith("EMP"):
                orig_path = cls.get_employee_clubs_path(orig_emp)
                if orig_path.parent.exists():
                    CSVEngine.upsert_row(orig_path, CLUB_FIELDS, "club_id", target_record)

                # Logged correction activity (priority_flag 0 = standard, no quota
                # effect; quotas are only incremented by explicit workflow calls).
                act_id = f"ACT-CORRECTION-{orig_emp}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
                activity_row = {
                    "activity_id": act_id,
                    "emp_id": orig_emp,
                    "timestamp": now_iso,
                    "support_type": "Data Correction",
                    "priority_flag": "0",
                    "club_id": target_record.get("club_id", ""),
                    "notes": (
                        f"Admin {admin_id or 'ADMIN'} corrected historical dates: "
                        f"Date of Approval {target_record['date_of_approval']}, "
                        f"Last Renewal Date {lrd or '(none)'}; "
                        f"upcoming renewal recomputed to {ren}."
                    )
                }
                emp_act_path = cls.get_employee_activities_path(orig_emp)
                CSVEngine.append_row(emp_act_path, ACTIVITY_FIELDS, activity_row)
                CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)

            return target_record


    @staticmethod
    def find_club_by_reg_no(reg_no: str, exclude_club_id: str = "") -> Optional[Dict[str, str]]:
        """
        Round-2 duplicate-entry checkpoint: finds an approved master club whose
        Registration Number matches (case-insensitive, whitespace-trimmed),
        optionally excluding one club_id (for edit/resubmission flows).
        """
        clean_reg = str(reg_no or "").strip().upper()
        if not clean_reg:
            return None
        clean_excl = str(exclude_club_id or "").strip().upper()
        for c in CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS):
            if c.get("reg_no", "").strip().upper() == clean_reg and \
                    c.get("club_id", "").strip().upper() != clean_excl:
                return c
        return None


    @classmethod
    def renew_club_registration(
        cls,
        emp_id: str,
        club_id: str,
        renewal_date: Optional[str] = None,
        last_renewal_date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        SEC B & C: Registration Renewal Approval ("Renewal Approved").
        Employee checks conditions and approves renewal for another year.
        1. Instantly captures current submission timestamp and logs it as 'Last Renewal Date' (last_renewal_date).
        2. Upcoming renewal due date = +1 year from the PREVIOUS DUE date
           (calculate_next_renewal_due; round-2 policy — renewing early never
           shortens the cycle); an explicit renewal_date from the caller wins.
        3. Updates club record in node and master CSVs.
        4. Logs priority renewal activity in activity_log.csv and master_activities.csv.
        5. Increments employee quota counters.
        6. Duplicate guard: a second renewal for the same club inside
           RENEWAL_DEDUPE_WINDOW_SEC returns the unchanged club with
           renewal_duplicate_skipped=True (no activity, no quota credit).
        """
        with _SYNC_LOCK:
            now_iso = datetime.now(timezone.utc).isoformat()
            clean_cid = club_id.strip().upper()

            # 0. Current club record: due-date base + duplicate-renewal guard.
            existing = CSVEngine.find_by_key(MASTER_CLUBS_CSV, "club_id", clean_cid, CLUB_FIELDS, copy=False)
            if not existing:
                return None

            prev_lrd_dt = parse_iso_datetime(existing.get("last_renewal_date", ""))
            if prev_lrd_dt:
                delta_sec = (datetime.now(timezone.utc) - prev_lrd_dt).total_seconds()
                if 0 <= delta_sec < RENEWAL_DEDUPE_WINDOW_SEC:
                    skipped = dict(existing)
                    skipped["renewal_duplicate_skipped"] = True
                    return skipped

            # 1. Instantly capture current date and time as Last Renewal Date
            clean_last_renewal = str(last_renewal_date or "").strip() or now_iso

            # 2. New due date = +1 year from the previous DUE date (anniversary
            #    kept; rolled forward if it would land in the past).
            clean_renewal = str(renewal_date or "").strip()
            if not clean_renewal:
                clean_renewal = calculate_next_renewal_due(
                    previous_renewal_date=(existing.get("renewal_date", "").strip()
                                           or existing.get("next_renewal_date", "").strip()),
                    date_of_approval=existing.get("date_of_approval", "").strip()
                )

            updated = cls.update_club(emp_id, clean_cid, {
                "last_renewal_date": clean_last_renewal,
                "renewal_date": clean_renewal,
                "next_renewal_date": clean_renewal,
                "status": "Active (Renewed)"
            })
            if not updated:
                return None

            # Log renewal activity
            act_id = f"ACT-RENEW-{emp_id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            activity_row = {
                "activity_id": act_id,
                "emp_id": emp_id,
                "timestamp": now_iso,
                "support_type": "Registration Renewal",
                "priority_flag": "1",
                "club_id": clean_cid,
                "notes": f"Renewal Approved for Club {clean_cid}. Last Renewal Date: {clean_last_renewal}, Upcoming Renewal Due Date: {clean_renewal}"
            }
            if emp_id.strip().upper().startswith("EMP"):
                CSVEngine.append_row(cls.get_employee_activities_path(emp_id), ACTIVITY_FIELDS, activity_row)
            CSVEngine.append_row(MASTER_ACTIVITIES_CSV, ACTIVITY_FIELDS, activity_row)
            cls._increment_quota(emp_id, support_inc=1, now_iso=now_iso)

            return updated

