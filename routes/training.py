"""
routes/training.py - PPT Training Library (2 slots)

Moved verbatim from app.py by the R39 router extraction
(CRITIQUE_AND_ROADMAP.md section 2 - mechanical, no behavior change).

    def <route>(h, path, query_params)   # GET
    def <route>(h, path, body)           # POST

`h` is the NDLIRequestHandler (app.py): `self.` became `h.` and nothing else.
"""
import app as app_module  # late lookup: tests patch app.<CONST>
from datetime import datetime, timezone
from pathlib import Path
import base64
from app import TRAINING_CONTENT_TYPES, TRAINING_DIR, TRAINING_EXTS, TRAINING_SLOTS, training_meta_load, training_meta_save, training_slot_file

# path == "/api/training/files"
def get_training_files(h, path, query_params):
    if not h._require_session():
        return
    slots = training_meta_load()
    total = sum(int(i.get("size", 0) or 0) for i in slots.values())
    h._send_json({
        "success": True,
        "slots": slots,
        "total_bytes": total,
        "max_total_bytes": app_module.TRAINING_MAX_TOTAL_BYTES,
    })
    return

# path.startswith("/api/training/download/")
def get_training_download(h, path, query_params):
    if not h._require_session():
        return
    slot = path.rsplit("/", 1)[-1].strip()
    if slot not in TRAINING_SLOTS:
        h._send_error("Unknown training slot (only 1 and 2 exist).", status=404)
        return
    f = training_slot_file(slot)
    if not f or not f.exists():
        h._send_error("No training deck uploaded to this slot yet.", status=404)
        return
    slots = training_meta_load()
    orig = (slots.get(slot) or {}).get("filename") or f.name
    orig = str(orig).replace('"', "").replace("\n", "").replace("\r", "") or f.name
    try:
        content = f.read_bytes()
        h.send_response(200)
        h.send_header("Content-Type", TRAINING_CONTENT_TYPES.get(f.suffix.lower(), "application/octet-stream"))
        h.send_header("Content-Disposition", f'attachment; filename="{orig}"')
        h.send_header("Content-Length", str(len(content)))
        h.end_headers()
        h.wfile.write(content)
    except Exception as e:
        h._send_error(f"Error serving training deck: {str(e)}", status=500)
    return

# path == "/api/admin/training/upload"
def post_training_upload(h, path, body):
    if not h._check_admin_access():
        return
    slot = str(body.get("slot", "")).strip()
    if slot not in TRAINING_SLOTS:
        h._send_error("slot must be 1 or 2.", status=400)
        return
    filename = str(body.get("filename", "")).strip()
    ext = Path(filename).suffix.lower()
    if ext not in TRAINING_EXTS:
        h._send_error("Only .ppt, .pptx and .ppsx files are accepted.", status=422)
        return
    b64_str = body.get("data", "")
    if not isinstance(b64_str, str) or not b64_str.strip():
        h._send_error("Missing file data (expected a base64 'data' field).", status=400)
        return
    try:
        raw_bytes = base64.b64decode(b64_str)
    except Exception as e:
        h._send_error(f"Invalid base64 file data: {e}", status=400)
        return
    if not raw_bytes:
        h._send_error("Uploaded file is empty.", status=400)
        return
    # Content sanity: OOXML decks (.pptx/.ppsx) are ZIP containers
    if ext in (".pptx", ".ppsx") and not raw_bytes.startswith(b"PK"):
        h._send_error("This file is not a valid .pptx/.ppsx deck.", status=422)
        return
    # ONE 15 MB budget shared by both slots — the OTHER slot's size counts
    slots = training_meta_load()
    other = sum(int(i.get("size", 0) or 0) for s, i in slots.items() if s != slot)
    if other + len(raw_bytes) > app_module.TRAINING_MAX_TOTAL_BYTES:
        h._send_error(
            f"Training library is full: both decks must fit in "
            f"{app_module.TRAINING_MAX_TOTAL_BYTES // (1024 * 1024)} MB COMBINED "
            f"(slot {slot} would need {len(raw_bytes)} bytes on top of "
            f"{other} already used).", status=413)
        return
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    # Replace semantics: any previous file for this slot is removed first
    for old in TRAINING_DIR.glob(f"slot{slot}.*"):
        if old.is_file():
            old.unlink()
    target = TRAINING_DIR / f"slot{slot}{ext}"
    target.write_bytes(raw_bytes)
    session = h._get_auth_session() or {}
    slots[slot] = {
        "filename": filename,
        "size": len(raw_bytes),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": str(session.get("email") or session.get("id") or ""),
    }
    training_meta_save(slots)
    used = sum(int(i.get("size", 0) or 0) for i in slots.values())
    h._send_json({
        "success": True,
        "message": (f"Training deck saved to slot {slot} — "
                    f"{used} of {app_module.TRAINING_MAX_TOTAL_BYTES} bytes used."),
        "slots": slots,
        "total_bytes": used,
        "max_total_bytes": app_module.TRAINING_MAX_TOTAL_BYTES,
    })
    return

# path == "/api/admin/training/delete"
def post_training_delete(h, path, body):
    if not h._check_admin_access():
        return
    slot = str(body.get("slot", "")).strip()
    if slot not in TRAINING_SLOTS:
        h._send_error("slot must be 1 or 2.", status=400)
        return
    slots = training_meta_load()
    removed = False
    if TRAINING_DIR.exists():
        for old in TRAINING_DIR.glob(f"slot{slot}.*"):
            if old.is_file():
                old.unlink()
                removed = True
    slots.pop(slot, None)
    training_meta_save(slots)
    h._send_json({
        "success": True,
        "message": f"Slot {slot} cleared." if removed else f"Slot {slot} was already empty.",
        "slots": slots,
    })
    return
