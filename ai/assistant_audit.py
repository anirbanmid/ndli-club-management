"""
NDLI Club Management - Assistant Audit Trail (Round 6 · Slice G)

Append-only audit of SECURITY- and PRIVACY-relevant assistant events: who did
what, to whom, and whether it was allowed. Slice G ("audit, privacy controls").
Distinct from assistant_issues.log (errors) and the interaction log (learning):
this is the accountability record.

1. APPEND-ONLY. <NDLI_DATA_DIR>/assistant_audit.csv, one row per event.
2. READABLE BY ADMINISTRATORS ONLY (they are the data controller; the
   visibility mode of the interaction log does NOT weaken this gate).
3. NO SECRETS: detail text is redacted + clipped with the same helper the
   learning store uses. No question text, no answers.
4. NO SILENT FAILURES: a failed append is logged LOUDLY and the caller is told
   (the calling endpoint then fails loudly too when the audit is mandatory).
"""
import csv
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR

AUDIT_FIELDS = ("timestamp_utc", "actor", "role", "action", "target", "ok", "detail")
ASSISTANT_AUDIT_CSV = Path(DATA_DIR) / "assistant_audit.csv"

_MAX_DETAIL = 200
_LOCK = threading.Lock()


def _log(component: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    try:
        from ai.assistant_core import log_assistant_issue  # lazy: core imports us
        log_assistant_issue(component, message, context)
    except Exception as exc:  # loud last resort
        import sys
        sys.stderr.write(f"AUDIT LOG WIRE FAILED ({component}): {exc} :: {message}\n")


def record_audit(action: str, actor: Any = None, target: str = "",
                 ok: bool = True, detail: str = "") -> bool:
    """Appends one audit row. Returns False (loudly) when the write fails."""
    from ai.assistant_learning import redact_secrets  # shared redaction, no cycle

    actor_id = str(getattr(actor, "user_id", "") or actor or "").strip().upper()[:40]
    role = str(getattr(actor, "role", "") or "").strip().upper()[:20]
    row = [
        datetime.now(timezone.utc).isoformat(),
        actor_id or "-",
        role or "-",
        str(action or "")[:60],
        str(target or "")[:60],
        "1" if ok else "0",
        redact_secrets(str(detail or ""))[:_MAX_DETAIL],
    ]
    try:
        ASSISTANT_AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            new_file = not ASSISTANT_AUDIT_CSV.exists()
            with open(ASSISTANT_AUDIT_CSV, "a", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                if new_file:
                    writer.writerow(AUDIT_FIELDS)
                writer.writerow(row)
        return True
    except Exception as exc:
        _log("assistant_audit.write", f"audit append FAILED: {exc}", {"action": row[3]})
        return False


def read_audit(ctx: Any, limit: int = 200) -> List[Dict[str, str]]:
    """ADMIN-only read (raises PermissionError otherwise). Newest first."""
    if not bool(getattr(ctx, "is_admin", False)):
        _log("assistant_audit.read", "role-scope denial",
             {"actor": str(getattr(ctx, "user_id", ""))})
        raise PermissionError("the audit trail is administrator-only.")
    if not ASSISTANT_AUDIT_CSV.exists():
        return []
    try:
        with open(ASSISTANT_AUDIT_CSV, "r", encoding="utf-8", newline="") as fh:
            rows = [{k: str(r.get(k, "") or "") for k in AUDIT_FIELDS}
                    for r in csv.DictReader(fh)]
    except Exception as exc:
        _log("assistant_audit.read", f"audit read FAILED: {exc}", {})
        raise RuntimeError(f"audit read failed: {exc}") from exc
    rows.reverse()
    return rows[: max(1, min(int(limit or 200), 500))]
