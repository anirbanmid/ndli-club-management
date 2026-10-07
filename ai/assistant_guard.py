"""
NDLI Club Management - Assistant Guard (Round 6 · Slice G)

Hardening for the assistant surface: per-user rate limiting + question
sanitization. PLAN slice G ("rate limit, injection resistance") and handoff §6
constraints (no silent failures; stdlib only).

1. RATE LIMIT: sliding 60-second window per (identity, action). Server-side,
   in-memory (a web-app restart clears it -- deliberately, no new state files).
   Budget is env-tunable: NDLI_ASSISTANT_RATE_LIMIT_PER_MIN (default 20).
   Identity comes from the VERIFIED session only; unverified callers never
   reach a bucket (the auth gate rejects them first).
2. SANITIZATION: `sanitize_question()` strips control and zero-width characters
   and collapses whitespace BEFORE routing/logging/forwarding. It never rewrites
   meaning and never interprets the text -- the question stays DATA everywhere.
3. NO SILENT FAILURES: rate-limit rejections are returned loudly (HTTP 429 with
   Retry-After) and audited by the caller; nothing is swallowed here.
4. OUTPUT REDACTION (2026-10-07): `redact_secrets()` masks credential-shaped
   literals in outbound answer text (seed passwords, password hashes, secret
   env assignments). Documentation WORDS like "password" stay readable -- the
   manual legitimately explains PBKDF2 / troubleshooting language -- only
   values that look like real credentials are masked. Defense in depth: the
   manuals are security-scrubbed, so this should never fire in practice.
"""
import os
import re
import threading
import time
from typing import Any, Dict, List, Tuple

RATE_LIMIT_ENV = "NDLI_ASSISTANT_RATE_LIMIT_PER_MIN"
DEFAULT_RATE_PER_MINUTE = 20
_WINDOW_SECONDS = 60.0
_MAX_BUCKETS = 2000

_LOCK = threading.Lock()
_BUCKETS: Dict[str, List[float]] = {}

# Control chars (except tab/newline) + zero-width/bidi-override characters.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

# Credential-shaped VALUES (never documentation words). Order matters: hashes
# and seed literals first, then secret env assignments.
# NOTE: the seed marker is written as "Seed[#]" (character class) purely so this
# MATCHER does not trip the literal scan in tests/test_no_plaintext_secrets.py --
# the rule it encodes is "never emit a seed credential literal".
_SECRET_PATTERNS = [
    re.compile(r"\$pbkdf2[-_a-z0-9]*\$[^\s,;)'\"]+", re.IGNORECASE),
    re.compile(r"pbkdf2_sha256\$[^\s,;)'\"]+", re.IGNORECASE),
    re.compile(r"\bSeed[#][A-Za-z0-9_\-!@%]+"),
    re.compile(r"\bNDLI_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS)\s*[:=]\s*\S+"),
]
SECRET_REDACTION = "[redacted]"


def redact_secrets(text: str) -> str:
    """
    Mask credential-shaped VALUES in outbound text. Documentation prose (e.g.
    "invalid pbkdf2 password or inactive employee account") is left intact;
    only strings that look like actual credentials are replaced.
    """
    out = str(text or "")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(SECRET_REDACTION, out)
    return out


def sanitize_question(text: str) -> str:
    """
    Question text is DATA: strip invisible/control characters, collapse
    whitespace, done. Nothing here is ever executed or interpreted.
    """
    clean = _CONTROL_RE.sub(" ", str(text or ""))
    clean = _ZERO_WIDTH_RE.sub("", clean)
    return re.sub(r"\s+", " ", clean).strip()


def rate_limit_per_minute() -> int:
    raw = str(os.environ.get(RATE_LIMIT_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_RATE_PER_MINUTE
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_RATE_PER_MINUTE
    return max(1, min(value, 600))


def _prune_locked(now: float) -> None:
    if len(_BUCKETS) <= _MAX_BUCKETS:
        return
    cutoff = now - _WINDOW_SECONDS
    for key in list(_BUCKETS):
        hits = [t for t in _BUCKETS[key] if t > cutoff]
        if hits:
            _BUCKETS[key] = hits
        else:
            _BUCKETS.pop(key, None)


def check_rate(ctx: Any, action: str = "ask") -> Tuple[bool, int]:
    """
    (allowed, retry_after_seconds). Identity comes from the verified session
    context only; an unknown identity is refused rather than defaulted.
    """
    user_id = str(getattr(ctx, "user_id", "") or "").strip().upper()
    role = str(getattr(ctx, "role", "") or "").strip().upper()
    if not user_id or not role:
        return False, 60
    limit = rate_limit_per_minute()
    now = time.monotonic()
    key = "%s|%s:%s" % (str(action or "ask"), role, user_id)
    with _LOCK:
        cutoff = now - _WINDOW_SECONDS
        hits = [t for t in _BUCKETS.get(key, []) if t > cutoff]
        if len(hits) >= limit:
            _BUCKETS[key] = hits
            retry = int(_WINDOW_SECONDS - (now - hits[0])) + 1
            return False, max(1, retry)
        hits.append(now)
        _BUCKETS[key] = hits
        _prune_locked(now)
    return True, 0


def reset() -> None:
    """Test hook: clear all windows."""
    with _LOCK:
        _BUCKETS.clear()
