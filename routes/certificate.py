"""
routes/certificate.py - Certificates: settings, signatures, QR tokens, public verification

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
from datetime import datetime, timezone
import base64
import json
import urllib.parse
from config import DATA_DIR, EMPLOYEE_NODES_DIR, MASTER_CLUBS_CSV
from db.csv_engine import CSVEngine
from db.schemas import CLUB_FIELDS
from db.sync_engine import parse_iso_or_date

# path == "/api/certificate/settings"
def get_certificate_settings(h, path, query_params):
    sig_dir = DATA_DIR / "signatures"
    sig_dir.mkdir(parents=True, exist_ok=True)
    settings_file = sig_dir / "settings.json"
    sig_png = sig_dir / "pi_signature.png"
    sig_jpg = sig_dir / "pi_signature.jpg"
    sig_exists = sig_png.exists() or sig_jpg.exists()

    settings_data = {
        "pi_name": "Prof. Partha Pratim Chakrabarti",
        "pi_affiliation": "Principal Investigator, NDLI Project, Central Library, IIT Kharagpur",
        "has_signature": sig_exists,
        "signature_url": "/api/certificate/signature" if sig_exists else None
    }
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                settings_data.update(saved)
                settings_data["has_signature"] = sig_exists
                settings_data["signature_url"] = "/api/certificate/signature" if sig_exists else None
        except Exception:
            pass
    h._send_json({"success": True, "settings": settings_data})
    return

# path == "/api/certificate/signature"
def get_certificate_signature(h, path, query_params):
    sig_dir = DATA_DIR / "signatures"
    sig_path = sig_dir / "pi_signature.png"
    if not sig_path.exists():
        sig_path = sig_dir / "pi_signature.jpg"
    if sig_path.exists():
        ext = sig_path.suffix.lower()
        ctype = "image/png" if ext == ".png" else "image/jpeg"
        h._serve_file(sig_path, ctype, extra_root=sig_dir)
    else:
        h._send_error("No PI signature uploaded yet.", status=404)
    return

# path == "/api/certificate/verify"
def get_certificate_verify(h, path, query_params):
    # OPTION B (2026-10-04, green field): the public QR is a SERVER-MINTED
    # signed token (see qr_tokens.py). The old free-text ?reg=/id=/club_id=
    # lookups (incl. the normalized-alphanumeric + employee-node fallback
    # matcher) are REMOVED -- enumeration-friendly and no longer needed once
    # the HMAC signature is the gate. EXACT registration lookup only.
    token_val = query_params.get("token", [""])[0].strip()
    if not token_val:
        h._send_error(
            "A signed verification token is required. Scan the QR code printed on the certificate.",
            status=400)
        return

    from qr_tokens import verify_qr_token
    verdict = verify_qr_token(token_val)
    if not verdict.get("ok"):
        h._send_json({
            "success": True,
            "valid": False,
            "status": "UNVERIFIED",
            "message": "This QR code could not be authenticated as an official NDLI certificate.",
            "reason": verdict.get("reason", "invalid token"),
            "verified_at": datetime.now(timezone.utc).isoformat()
        })
        return

    clean_q = verdict["reg_no"].upper()
    clean_cid = verdict.get("club_id", "").upper()
    all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS, copy=False)
    matched_club = None
    for c in all_clubs:
        c_reg = str(c.get("reg_no", "")).strip().upper()
        c_cid = str(c.get("club_id", "")).strip().upper()
        if clean_q == c_reg or (clean_cid and clean_cid == c_cid):
            matched_club = c
            break

    if not matched_club:
        h._send_json({
            "success": True,
            "valid": False,
            "status": "UNVERIFIED",
            "message": "No registered NDLI Club matches this certificate's registration number.",
            "verified_at": datetime.now(timezone.utc).isoformat()
        })
        return

    raw_ren = matched_club.get("renewal_date", "").strip() or matched_club.get("next_renewal_date", "").strip()
    parsed_ren = parse_iso_or_date(raw_ren) if raw_ren else None
    now_date = datetime.now(timezone.utc).date()

    is_active = True
    status_text = "ACTIVE & VALID"
    if parsed_ren and parsed_ren < now_date:
        is_active = False
        status_text = "EXPIRED (RENEWAL DUE)"

    if str(matched_club.get("status", "")).strip().lower() in ("blocked", "inactive", "suspended"):
        is_active = False
        status_text = "SUSPENDED"

    h._send_json({
        "success": True,
        "valid": True,
        "is_active": is_active,
        "status": status_text,
        "club": {
            "club_id": matched_club.get("club_id", ""),
            "reg_no": matched_club.get("reg_no", ""),
            "institution_name": matched_club.get("institution_name", ""),
            "state": matched_club.get("state", ""),
            "zone": matched_club.get("zone", ""),
            "date_of_approval": matched_club.get("date_of_approval", "") or matched_club.get("submission_timestamp", ""),
            "renewal_date": raw_ren,
            "last_renewal_date": matched_club.get("last_renewal_date", ""),
            "issuing_authority": "National Digital Library of India Project, Central Library, IIT Kharagpur"
        },
        "verified_at": datetime.now(timezone.utc).isoformat()
    })
    return

# path == "/api/certificate/qr-token"
def post_certificate_qr_token(h, path, body):
    session = h._require_session()
    if not session:
        return
    query_val = (str(body.get("reg_no", "")).strip() or str(body.get("club_id", "")).strip())
    if not query_val:
        h._send_error("reg_no (or club_id) is required to mint a verification token.", status=400)
        return
    clean_q = query_val.upper()
    all_clubs = CSVEngine.read_all(MASTER_CLUBS_CSV, CLUB_FIELDS, copy=False)
    target = None
    for c in all_clubs:
        if clean_q in (str(c.get("reg_no", "")).strip().upper(), str(c.get("club_id", "")).strip().upper()):
            target = c
            break
    if not target:
        h._send_error("No registered club with that exact registration number.", status=404)
        return
    owner = str(target.get("approved_by_emp_id", "")).strip().upper()
    if session.get("role") != "ADMIN":
        me = str(session.get("user_id", "")).strip().upper()
        in_my_node = False
        node_csv = EMPLOYEE_NODES_DIR / me.lower() / "clubs.csv"
        if me and node_csv.exists():
            for nc in CSVEngine.read_all(node_csv, CLUB_FIELDS, copy=False):
                if clean_q in (str(nc.get("reg_no", "")).strip().upper(),
                               str(nc.get("club_id", "")).strip().upper()):
                    in_my_node = True
                    break
        if not in_my_node and owner != me:
            h._send_error(
                "Access denied: you may only mint verification tokens for your own clubs.",
                status=403)
            return
    from qr_tokens import mint_qr_token, QrTokenError
    try:
        token = mint_qr_token(target.get("reg_no", ""), target.get("club_id", ""))
    except QrTokenError as exc:
        h._send_error(str(exc), status=500)
        return
    h._send_json({
        "success": True,
        "token": token,
        "verification_url": f"/verify?token={urllib.parse.quote(token)}",
        "reg_no": target.get("reg_no", ""),
        "club_id": target.get("club_id", "")
    })
    return

# path == "/api/certificate/signature"
def post_certificate_signature(h, path, body):
    # CLIENT REQUIREMENT (2026-09-26): employees must be able to generate
    # certificates and upload/modify the PI signature — every authenticated
    # session may use the certificate APIs (previously admin-only).
    if not h._require_session():
        return
    image_data = body.get("image_data", "")
    if not image_data:
        h._send_error("image_data (base64 string or data URL) is required.", status=400)
        return

    ext = ".png"
    b64_str = image_data
    if "," in image_data:
        header, b64_str = image_data.split(",", 1)
        if "image/jpeg" in header or "image/jpg" in header:
            ext = ".jpg"
    elif body.get("extension") in [".jpg", ".jpeg"]:
        ext = ".jpg"

    try:
        raw_bytes = base64.b64decode(b64_str)
    except Exception as e:
        h._send_error(f"Invalid base64 image data: {e}", status=400)
        return

    # BUG-FIX (bughunt round 5): now that every employee may replace the PI
    # signature printed on official certificates, the upload is validated
    # (real PNG/JPEG bytes, max 2 MB) and the change is attributed.
    if len(raw_bytes) > 2 * 1024 * 1024:
        h._send_error("Signature image is too large (max 2 MB).", status=413)
        return
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif raw_bytes.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    else:
        h._send_error("Signature must be a valid PNG or JPEG image.", status=422)
        return

    sig_dir = DATA_DIR / "signatures"
    sig_dir.mkdir(parents=True, exist_ok=True)
    # Remove any alternate format to avoid confusion
    alt_ext = ".jpg" if ext == ".png" else ".png"
    alt_file = sig_dir / f"pi_signature{alt_ext}"
    if alt_file.exists():
        try:
            alt_file.unlink()
        except Exception:
            pass

    target_file = sig_dir / f"pi_signature{ext}"
    with open(target_file, "wb") as f:
        f.write(raw_bytes)

    settings_file = sig_dir / "settings.json"
    saved = {}
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            pass
    saved["has_signature"] = True
    saved["signature_filename"] = f"pi_signature{ext}"
    _who = h._get_auth_session() or {}
    saved["signature_updated_by"] = str(_who.get("user_id", ""))
    saved["signature_updated_at"] = datetime.now(timezone.utc).isoformat()
    if body.get("pi_name"):
        saved["pi_name"] = str(body.get("pi_name")).strip()
    if body.get("pi_affiliation"):
        saved["pi_affiliation"] = str(body.get("pi_affiliation")).strip()

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2)

    h._send_json({
        "success": True,
        "message": "PI signature uploaded and saved successfully.",
        "signature_url": f"/api/certificate/signature?t={int(datetime.now().timestamp())}",
        "filename": f"pi_signature{ext}"
    })
    return

# path == "/api/certificate/settings"
def post_certificate_settings(h, path, body):
    sig_dir = DATA_DIR / "signatures"
    sig_dir.mkdir(parents=True, exist_ok=True)
    settings_file = sig_dir / "settings.json"
    # CLIENT REQUIREMENT (2026-09-26): certificate PI settings are
    # editable by every authenticated session (previously admin-only).
    if not h._require_session():
        return
    saved = {
        "pi_name": "Prof. Partha Pratim Chakrabarti",
        "pi_affiliation": "Principal Investigator, NDLI Project, Central Library, IIT Kharagpur"
    }
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                saved.update(json.load(f))
        except Exception:
            pass

    if "pi_name" in body and body["pi_name"] is not None:
        saved["pi_name"] = str(body["pi_name"]).strip()
    if "pi_affiliation" in body and body["pi_affiliation"] is not None:
        saved["pi_affiliation"] = str(body["pi_affiliation"]).strip()

    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(saved, f, indent=2)

    sig_png = sig_dir / "pi_signature.png"
    sig_jpg = sig_dir / "pi_signature.jpg"
    sig_exists = sig_png.exists() or sig_jpg.exists()

    saved["has_signature"] = sig_exists
    saved["signature_url"] = "/api/certificate/signature" if sig_exists else None

    h._send_json({
        "success": True,
        "message": "Certificate settings updated successfully.",
        "settings": saved
    })
    return
