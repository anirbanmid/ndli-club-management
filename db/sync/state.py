"""db/sync/state.py - the ONE home for shared engine state/constants.

R46: `_SYNC_LOCK` (the engine-wide transaction lock) and
`RENEWAL_DEDUPE_WINDOW_SEC` (the duplicate-renewal guard window) moved here from
db/sync_engine.py so every domain module shares exactly one object/definition.
Nothing else may create an engine lock (pinned by tests/test_r46_sync_split.py).
"""



import threading



_SYNC_LOCK = threading.RLock()


# Round-2 duplicate-renewal guard: a second "Renewal Approved" for the same club
# inside this window (seconds) is treated as the same click — logged once, credited once.
# 60s comfortably covers double-clicks while never blocking a deliberate correction.
RENEWAL_DEDUPE_WINDOW_SEC = 60

