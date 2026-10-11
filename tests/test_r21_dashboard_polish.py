"""Lock tests for the R21 dashboard polish v2 (2026-10-08).

User request (second pass): "I don't notice any noticeable changes in KPIs and
infographics including charts and graphs design improvement. Those should have
more modern looks." v1 was surface-only; v2 locks the BOLD design language:

  * KPI cards: tinted gradient surfaces + floating accent pills + tone halos
  * KPI icon chips: saturated gradient tiles with white glyphs
  * urgency-tinted KPI numbers
  * infographic cards: gradient chrome + gradient-clipped titles
  * donut: two-tone gradient segments + legend mini progress bars
  * trajectory: smooth Catmull-Rom curve + gradient line + glow + dashed grid
  * renewal health: gradient segmented RING (not a flat pie) + colour-dot legend
  * support tiles: saturated gradient chips + per-tone gradient bars
  * gauge: segmented pill (gaps) with gradient fills

Static grep-based guards (same style as tests/test_r20_polish.py).
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


class TestR21SidebarTint(unittest.TestCase):
    def setUp(self):
        self.style = read("static/css/style.css")

    def test_tint_is_visible(self):
        # #E2EFE8 vs the #F4F8F6 page = a real, noticeable mint tinge.
        self.assertIn(".app-sidebar { background: #E2EFE8; border-right: 1px solid #CCDFD5; }",
                      self.style)


class TestR21KpiCards(unittest.TestCase):
    def setUp(self):
        self.style = read("static/css/style.css")

    def test_tinted_gradient_surface(self):
        self.assertIn(".stat-card {\n  border-radius: 20px;", self.style)
        self.assertIn("background: linear-gradient(135deg, #FFFFFF 0%, #E9F6EE 100%);", self.style)
        self.assertIn("0 16px 32px -18px rgba(16, 49, 37, 0.24)", self.style)

    def test_variant_tints(self):
        for tint in ("#E7F0FB", "#E2F7EE", "#FDF2E3", "#FDEBF0"):
            self.assertIn(tint, self.style)

    def test_accent_pills(self):
        self.assertIn(".stat-card::before {", self.style)
        self.assertIn("background: linear-gradient(90deg, #0D7751 0%, #43CFA0 100%);", self.style)
        self.assertIn(".stat-card.danger::before", self.style)

    def test_tone_halos(self):
        for tone in (".stat-card.accent::after", ".stat-card.success::after",
                     ".stat-card.warning::after", ".stat-card.danger::after"):
            self.assertIn(tone, self.style)

    def test_gradient_icon_chips(self):
        idx = self.style.index("/* --- KPI icon chips")
        chunk = self.style[idx:idx + 1600]
        self.assertIn("width: 46px !important", chunk)
        self.assertIn("height: 46px !important", chunk)
        self.assertIn("border-radius: 15px !important", chunk)
        self.assertIn("stroke: #ffffff !important", chunk)
        self.assertIn("background: linear-gradient(135deg, #0D7751 0%, #3BCB98 100%) !important", chunk)
        self.assertIn(".stat-icon.ic-lav", chunk)
        self.assertIn(".stat-icon.ic-amber", chunk)

    def test_type_hierarchy(self):
        self.assertIn(".stat-value {\n  font-size: 1.62rem;", self.style)
        self.assertIn(".stat-label { font-size: var(--text-xs); letter-spacing: 0.12em;", self.style)

    def test_urgency_tinted_values(self):
        self.assertIn(".stat-card.warning .stat-value { color: #B45309; }", self.style)
        self.assertIn(".stat-card.danger  .stat-value { color: #BE123C; }", self.style)


class TestR21InfographicChrome(unittest.TestCase):
    def setUp(self):
        self.style = read("static/css/style.css")

    def test_card_chrome(self):
        self.assertIn(".infographic-card {\n  border-radius: 20px;", self.style)
        self.assertIn("background: linear-gradient(165deg, #FFFFFF 0%, #F3FAF6 55%, #ECF6F0 100%);", self.style)
        self.assertIn("border-bottom: 1px solid #E7F1EB;", self.style)

    def test_gradient_titles(self):
        self.assertIn("-webkit-background-clip: text;", self.style)
        self.assertIn("background: linear-gradient(120deg, #0B3B2A 0%, #0D7751 75%);", self.style)

    def test_soft_plot_surface(self):
        self.assertIn("background: linear-gradient(180deg, #FFFFFF 0%, #F2F9F5 100%);", self.style)
        self.assertIn(".donut-chart-container,\n.trajectory-svg-container {", self.style)

    def test_tiles_bars_gauge(self):
        self.assertIn(".support-type-tile {\n  border-radius: 16px;", self.style)
        self.assertIn(".support-type-tile.info    .tile-icon { background: linear-gradient(135deg, #1E5F8C 0%, #55A9DC 100%);", self.style)
        self.assertIn(".support-type-tile.warning .bar-fill { background: linear-gradient(90deg, #D97706 0%, #F2B255 100%);", self.style)
        self.assertIn(".stacked-gauge-bar {\n  height: 12px;", self.style)
        self.assertIn("display: flex;\n  gap: 3px;", self.style)
        self.assertIn(".bar-track {\n  background: #EDF3F0;", self.style)
        self.assertIn(".bar-fill {\n  border-radius: 999px;\n  background: linear-gradient(90deg, #0D7751 0%, #43CFA0 100%);", self.style)


class TestR21Charts(unittest.TestCase):
    def setUp(self):
        self.admin = read("templates/admin.html")

    def test_donut_modern_palette(self):
        self.assertIn('"#0D7751", "#2FA97B", "#57C7A0", "#1E5F8C", "#4B9BC9"', self.admin)

    def test_donut_gradient_segments(self):
        self.assertIn("const lightPalette", self.admin)
        self.assertIn('stroke="url(#dzg${idx})"', self.admin)
        self.assertIn("<defs>${defs}</defs>", self.admin)

    def test_donut_segments_have_gaps_and_track(self):
        self.assertIn("const segGap = 5;", self.admin)
        self.assertIn('stroke="#EAF2ED" stroke-width="26"', self.admin)

    def test_trajectory_smooth_gradient_glow(self):
        self.assertIn("function smoothPath(points, tension)", self.admin)
        self.assertIn("const dLine = smoothPath(pts, 0.2);", self.admin)
        self.assertIn('id="trajLine"', self.admin)
        self.assertIn('stroke-width="12" stroke-linecap="round" opacity="0.16"', self.admin)
        self.assertIn('stroke="url(#trajLine)" stroke-width="3.5"', self.admin)
        # r2_ui_fixes lock: the trajectory SVG must not stretch
        self.assertIn('preserveAspectRatio="xMidYMid meet"', self.admin)

    def test_trajectory_labels_have_halos(self):
        self.assertIn('paint-order="stroke"', self.admin)

    def test_renewal_is_a_ring_not_a_pie(self):
        # the flat pie paths are gone; segmented ring circles take their place
        self.assertNotIn('class="pie-slice"', self.admin)
        self.assertIn("const size = 150, cx = size / 2, cy = size / 2, r = 54, ring = 20;", self.admin)
        self.assertIn('stroke="url(#rnwGrad${i})"', self.admin)
        # tests/test_portal_and_api.py locks this name — must survive
        self.assertIn("function generateRenewalPieSvg", self.admin)

    def test_legend_uses_colour_dots_not_emoji(self):
        # scoped to the renewal-health legend block (🔴/🟡 are still used as
        # status emoji elsewhere in admin.html — those are a different feature)
        idx = self.admin.index('class="retention-legend-row"')
        chunk = self.admin[idx:idx + 1200]
        self.assertNotIn("\U0001F7E2", chunk)  # 🟢
        self.assertNotIn("\U0001F7E1", chunk)  # 🟡
        self.assertNotIn("\U0001F534", chunk)  # 🔴
        self.assertIn('border-radius:50%; background:#17A273;', self.admin)
        self.assertIn('border-radius:50%; background:#E9A23B;', self.admin)
        self.assertIn('border-radius:50%; background:#BE123C;', self.admin)

    def test_donut_legend_mini_bars(self):
        self.assertIn("legend-mini-bar", self.admin)
        self.assertIn(".legend-mini-bar {", read("static/css/style.css"))

    def test_test_locked_names_survive(self):
        for needle in ('id="zone-donut-title"', 'id="zone-donut-container"',
                       "stacked-gauge-bar", ".retention-pie-svg"):
            if needle.startswith("id=") or needle == "stacked-gauge-bar":
                self.assertIn(needle, self.admin)
            else:
                self.assertIn(needle, read("static/css/style.css"))


class TestR21ActivityMatrix(unittest.TestCase):
    """R21v3: the plain volume bars are gone; the Activity Distribution Matrix
    (share ribbon + heat rows) delivers relative distribution at a glance."""

    def setUp(self):
        self.admin = read("templates/admin.html")
        self.style = read("static/css/style.css")

    def test_volume_bars_replaced(self):
        self.assertNotIn("Relative Activity Distribution (Volume Bars)", self.admin)
        self.assertNotIn("renderEmployeeBars", self.admin)
        self.assertNotIn('id="employee-bars-container"', self.admin)

    def test_matrix_wired(self):
        self.assertIn("function renderActivityMatrix(quotas)", self.admin)
        self.assertIn("renderActivityMatrix(res.data.summary.quotas);", self.admin)
        self.assertIn('id="activity-matrix-container"', self.admin)
        self.assertIn("Activity Distribution Matrix", self.admin)

    def test_share_ribbon(self):
        self.assertIn("activity-ribbon", self.admin)
        self.assertIn("ribbon-seg", self.admin)
        self.assertIn(".activity-ribbon {", self.style)
        self.assertIn(".ribbon-seg {", self.style)

    def test_heat_cells_and_dimensions(self):
        self.assertIn("rgba(13, 119, 81, ${clubAlpha})", self.admin)
        self.assertIn("rgba(30, 95, 140, ${suppAlpha})", self.admin)
        for col in ("Clubs Approved", "Support Logs", "Share", "Last Activity"):
            self.assertIn(col, self.admin)

    def test_recency_and_zone_chips(self):
        self.assertIn("recency-chip", self.admin)
        self.assertIn(".recency-fresh", self.style)
        self.assertIn(".recency-stale", self.style)
        self.assertIn("zone-chip", self.admin)

    def test_microsecond_iso_timestamps_parse(self):
        # master CSV timestamps carry microseconds (Date.parse would return NaN)
        self.assertIn('String(q.last_activity_timestamp).replace(/(\\.\\d{3})\\d+/, "$1")', self.admin)


if __name__ == "__main__":
    unittest.main()
