"""NDLI Club Management - Real-Time Synchronization Engine
Maintains synchronization between Employee Node CSVs and Master CSVs.

R46: this file is the public surface ONLY.  The 1,741-line monolith was split
mechanically into db/sync/ domain modules (bodies moved verbatim, proven byte-
identical by .openclaw/tmp/verify_sync_split.py).  Import everything from here:
`from db.sync_engine import SyncEngine, ...`.  Zero logic may live in this file
(pinned by tests/test_r46_sync_split.py).
"""
from db.sync.state import _SYNC_LOCK, RENEWAL_DEDUPE_WINDOW_SEC
from db.sync.dates import _parse_string_date, parse_iso_or_date, calculate_next_renewal_date, parse_iso_datetime, _add_one_year, calculate_next_renewal_due
from db.sync.paths import SyncPathsMixin
from db.sync.activities import SyncActivitiesMixin
from db.sync.employees import SyncEmployeesMixin
from db.sync.clubs import SyncClubsMixin
from db.sync.quota import SyncQuotaMixin
from db.sync.maintenance import SyncMaintenanceMixin

__all__ = [
    "SyncEngine",
    "parse_iso_or_date",
    "parse_iso_datetime",
    "calculate_next_renewal_date",
    "calculate_next_renewal_due",
    "RENEWAL_DEDUPE_WINDOW_SEC",
]


class SyncEngine(SyncPathsMixin, SyncActivitiesMixin, SyncEmployeesMixin, SyncClubsMixin, SyncQuotaMixin, SyncMaintenanceMixin):
    """Manages transactional updates and reconciliation between employee nodes and master DB."""

