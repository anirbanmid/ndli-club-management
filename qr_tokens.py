"""
Signed QR verification tokens (Round 7 - Option B, green field 2026-10-04).

Why: the old public verify API accepted ?reg=/<anything> and did fuzzy
(normalized-alphanumeric + employee-node fallback) lookups -- an enumeration
hazard. Since NO real certificate has been despatched yet (all test certs),
the QR is now a SERVER-MINTED signed token; scanning proves the certificate
was issued by this system for that exact registration.

Token format (long/no expiry -- printed certificates must keep verifying):
    v1.<key_id>.<payload_b64url>.<sig_b64url>
    payload = {"reg": "<reg_no>", "cid": "<club_id>", "iat": <epoch>}
    sig     = HMAC-SHA256(key, "v1.<key_id>.<payload_b64url>")   (base64url)

Key management: NDLI_QR_SIGNING_KEY env var first (operator control). If
unset, a strong random key is generated ONCE and persisted to
data/.qr_signing_key (chmod 600, gitignored) with a LOUD banner. There is NO
repo-visible fallback -- a token is never forgeable from public sources.
key_id = sha256(key)[:10] so the key can be rotated later while old tokens
stay attributable to the key that signed them.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional, Tuple

TOKEN_VERSION = "v1"
KEY_ENV = "NDLI_QR_SIGNING_KEY"

_key_cache: Optional[bytes] = None


class QrTokenError(Exception):
    """Raised when a verification token cannot be authenticated."""


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64u(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:10]


def _resolve_key_path():
    from config import DATA_DIR
    return DATA_DIR / ".qr_signing_key"


def get_qr_key() -> Tuple[bytes, str]:
    """Return (key_bytes, key_id). Env var first; else generated + persisted."""
    global _key_cache
    env_val = os.getenv(KEY_ENV, "").strip()
    if env_val:
        key = env_val.encode("utf-8")
        _key_cache = key
        return key, _key_id(key)

    if _key_cache is not None:
        return _key_cache, _key_id(_key_cache)

    key_path = _resolve_key_path()
    if key_path.exists():
        key = key_path.read_text().strip().encode("utf-8")
        _key_cache = key
        return key, _key_id(key)

    # Generate ONCE, atomically (O_EXCL: concurrent workers converge on one key).
    import secrets
    new_key = secrets.token_urlsafe(32)
    try:
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(new_key + "\n")
        print("!" * 70)
        print("! QR SIGNING KEY GENERATED -> " + str(key_path))
        print("! Set " + KEY_ENV + " in the environment for explicit control.")
        print("! Back this key up: losing it invalidates printed QR codes.")
        print("!" * 70)
    except FileExistsError:
        new_key = key_path.read_text().strip()
    try:
        os.chmod(str(key_path), 0o600)
    except Exception:
        pass
    key = new_key.encode("utf-8")
    _key_cache = key
    return key, _key_id(key)


def mint_qr_token(reg_no: str, club_id: str = "") -> str:
    """Mint a signed verification token for one exact club record."""
    reg = str(reg_no or "").strip()
    if not reg:
        raise QrTokenError("reg_no is required to mint a verification token.")
    key, kid = get_qr_key()
    payload = {"reg": reg, "cid": str(club_id or "").strip(), "iat": int(time.time())}
    body = TOKEN_VERSION + "." + kid + "." + _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64u(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + sig


def verify_qr_token(token: str) -> dict:
    """
    Verify a signed token. Returns {ok, reason, reg_no, club_id, iat, key_id}.
    Never raises on bad input -- ok=False with a reason instead.
    """
    raw = str(token or "").strip()
    if not raw:
        return {"ok": False, "reason": "empty token"}
    parts = raw.split(".")
    if len(parts) != 4:
        return {"ok": False, "reason": "malformed token"}
    ver, kid, payload_b64, sig_b64 = parts
    if ver != TOKEN_VERSION:
        return {"ok": False, "reason": "unsupported token version"}
    key, current_kid = get_qr_key()
    if not hmac.compare_digest(kid, current_kid):
        # Signed with a key this deployment does not hold (rotated away / foreign).
        return {"ok": False, "reason": "unknown signing key", "key_id": kid}
    body = ver + "." + kid + "." + payload_b64
    try:
        expected = hmac.new(key, body.encode("ascii"), hashlib.sha256).digest()
        given = _unb64u(sig_b64)
    except Exception:
        return {"ok": False, "reason": "malformed signature"}
    if not hmac.compare_digest(expected, given):
        return {"ok": False, "reason": "signature mismatch"}
    try:
        payload = json.loads(_unb64u(payload_b64))
    except Exception:
        return {"ok": False, "reason": "malformed payload"}
    reg = str(payload.get("reg", "")).strip()
    if not reg:
        return {"ok": False, "reason": "token carries no registration"}
    return {
        "ok": True,
        "reason": "verified",
        "reg_no": reg,
        "club_id": str(payload.get("cid", "")).strip(),
        "iat": payload.get("iat"),
        "key_id": kid,
    }
