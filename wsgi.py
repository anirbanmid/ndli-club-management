"""
NDLI Club Management - WSGI entry point (PythonAnywhere and any WSGI host).

Adapts the battle-tested NDLIRequestHandler route logic from app.py to the
WSGI protocol with zero third-party dependencies. The stdlib HTTP server in
app.py remains the entry point for local development and the test suite; both
frontends execute the exact same route code, so behavior stays identical.

IMPORTANT: environment variables (NDLI_DATA_DIR, NDLI_STORAGE_MODE,
NDLI_APPS_SCRIPT_SYNC_URL, NDLI_ADMIN_PASSWORD, ...) must be set BEFORE this
module is imported -- set them in the host's WSGI configuration file.
See PYTHONANYWHERE_DEPLOYMENT.md for the exact setup.
"""
import io
import threading
from email.message import Message
from http import HTTPStatus

import app as ndli_app
from app import NDLIRequestHandler

_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def _ensure_initialized() -> None:
    """Runs the standard startup chain once (cold-boot restore, reconcile)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        ndli_app.init_system()
        _INITIALIZED = True


class _WsgiCaptureHandler(NDLIRequestHandler):
    """
    Request handler that captures the HTTP response into memory instead of a
    socket. Bypasses BaseHTTPRequestHandler.__init__/setup on purpose (there is
    no connection object in WSGI).
    """

    def __init__(self):
        self._status = 500
        self._headers = []
        self._body = io.BytesIO()
        self.wfile = self._body
        self.rfile = io.BytesIO(b"")
        self.headers = Message()
        self.path = "/"
        self.command = "GET"
        self.request_version = "HTTP/1.0"
        self.client_address = ("wsgi", 0)

    def send_response(self, code, message=None):
        self._status = code

    def send_header(self, keyword, value):
        self._headers.append((str(keyword), str(value)))

    def end_headers(self):
        pass

    def send_error(self, code, message=None, explain=None):
        self._status = code

    def log_message(self, fmt, *args):
        pass


def _build_headers(environ) -> Message:
    """Reconstructs an email.message.Message request header object from WSGI environ."""
    msg = Message()
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].replace("_", "-").title()
            msg[header_name] = value
    if environ.get("CONTENT_TYPE"):
        msg["Content-Type"] = environ["CONTENT_TYPE"]
    if environ.get("CONTENT_LENGTH"):
        msg["Content-Length"] = environ["CONTENT_LENGTH"]
    return msg


def application(environ, start_response):
    """Standard WSGI application object dispatching into app.py route logic."""
    _ensure_initialized()

    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/") or "/"
    query = environ.get("QUERY_STRING", "")
    full_path = path + ("?" + query if query else "")

    try:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    body = environ["wsgi.input"].read(content_length) if content_length > 0 else b""

    handler = _WsgiCaptureHandler()
    handler.command = method
    handler.path = full_path
    handler.headers = _build_headers(environ)
    handler.rfile = io.BytesIO(body)

    if method == "GET":
        handler.do_GET()
    elif method == "POST":
        handler.do_POST()
    elif method == "OPTIONS":
        handler.do_OPTIONS()
    else:
        handler._send_error(f"Method not allowed: {method}", status=405)

    status_code = handler._status
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "Unknown"
    response_body = handler._body.getvalue()

    headers = list(handler._headers)
    if not any(k.lower() == "content-length" for k, _ in headers):
        headers.append(("Content-Length", str(len(response_body))))

    start_response(f"{status_code} {phrase}", headers)
    return [response_body]
