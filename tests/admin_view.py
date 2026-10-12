"""R41 follow-the-code helper: the admin JS view.

After the R41 extraction (roadmap #4), templates/admin.html carries markup only;
its JS lives in static/js/admin_*.js modules loaded in <script src> order.
Pins that assert on admin JS must read the combined view (HTML + modules), so
assertIn / assertNotIn / count assertions stay meaningful — no vacuous passes
and no pin silently following dead code.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODULE_TAG = re.compile(r'<script[^>]*src="/static/js/(admin_[^"?]+\.js)')


def admin_module_names():
    """admin_*.js module names in the template's <script src> order."""
    html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
    return MODULE_TAG.findall(html)


def admin_js_view():
    """admin.html + every admin_*.js module body, in template order."""
    html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
    parts = [html]
    for name in admin_module_names():
        parts.append((ROOT / "static" / "js" / name).read_text(encoding="utf-8"))
    return "\n".join(parts)
