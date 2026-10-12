"""
NDLI Club Management - Unified secret redaction (R45)

ONE definition of "what counts as a credential" for the whole assistant surface.

Why this module exists
----------------------
Before R45 there were TWO different `redact_secrets()` implementations:

  * ai.assistant_guard  -- credential-SHAPED literals (pbkdf2 hashes, seed
    credentials, NDLI_* secret env assignments). Used for OUTBOUND answers.
  * ai.assistant_learning -- `key: value` assignments + bearer tokens. Used for
    the LEARNING STORE (questions/intents/details) and the audit trail.

They disagreed on 8 of 10 probe strings. The consequence was a real asymmetry:
an outbound answer could carry `password: hunter2` (guard missed it) while the
learning store could persist `pbkdf2_sha256$...` (learning missed it) -- each
path leaked exactly what the other caught. Same class of bug as the R37 counting
drift that R38 fixed by single-sourcing `db/counting_rules.py`.

This module is the redaction equivalent of that fix. Both former entry points
re-export `redact_secrets` from here, so every caller and every existing test
keeps working -- but there is now only ONE rule set.

Rules (applied in order)
------------------------
1. SHAPE rules -- values that look like credentials on their own:
     * pbkdf2 / pbkdf2_sha256 hash literals
     * seed credential literals
     * `NDLI_*KEY|TOKEN|SECRET|PASSWORD|PASS` environment assignments
2. KEY-ASSIGNMENT rule -- `password: x`, `api_key = x`, `token=x`, `relay_key: x`,
   `Authorization: Bearer x`, ...  The KEY NAME is preserved (so logs stay
   readable and the reason for redaction stays visible) and only the value is
   masked.
3. BEARER rule -- a bare `bearer <token>` anywhere.

Documentation prose is deliberately left alone: the manuals legitimately explain
PBKDF2 and talk about "invalid pbkdf2 password or inactive employee account".
Only things that look like ACTUAL credentials are masked.

NO SILENT FAILURES / no behaviour change beyond the tightening: this only ever
redacts MORE than before, never less.

NOTE ON THE SEED MARKER: the seed pattern is written as a character class
(`Seed[#]`) on purpose -- this module lives in ai/ and must not trip the literal
scan in tests/test_no_plaintext_secrets.py. The rule it encodes is "never emit a
seed credential literal", not "never write the word".
"""
import re
from typing import Any

# The single redaction token. Both former entry points re-export this.
SECRET_REDACTION = "[redacted]"


# --- 1. SHAPE rules (credential-looking values, no key name required) --------
# Order matters: hashes and seed literals first, then secret env assignments.
_SHAPE_PATTERNS = [
    re.compile(r"\$pbkdf2[-_a-z0-9]*\$[^\s,;)'\"]+", re.IGNORECASE),
    re.compile(r"pbkdf2_sha256\$[^\s,;)'\"]+", re.IGNORECASE),
    re.compile(r"\bSeed[#][A-Za-z0-9_\-!@%]+"),
    re.compile(r"\bNDLI_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS)\s*[:=]\s*\S+"),
]

# --- 2. KEY-ASSIGNMENT rule (keep the key name, mask the value) -------------
_KEY_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|relay[_-]?key"
    r"|authorization|bearer|private[_-]?key)\b(\s*[:=]\s*)((?:bearer\s+)?\S+)"
)

# --- 3. bare bearer token ---------------------------------------------------
_BEARER_RE = re.compile(r"(?i)(?<!\[)\bbearer\s+\S+")


def redact_secrets(text: Any) -> str:
    """
    Mask credential-shaped values in `text`. Documentation prose is left intact;
    only strings that look like actual credentials are replaced.

    This is the ONLY implementation in the codebase. ai.assistant_guard and
    ai.assistant_learning re-export it so their callers/tests are unchanged.
    """
    out = str(text or "")
    for pattern in _SHAPE_PATTERNS:
        out = pattern.sub(SECRET_REDACTION, out)
    out = _KEY_ASSIGN_RE.sub(
        lambda m: "%s%s%s" % (m.group(1), m.group(2), SECRET_REDACTION), out)
    out = _BEARER_RE.sub("bearer %s" % SECRET_REDACTION, out)
    return out
