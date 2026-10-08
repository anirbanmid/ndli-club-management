/**
 * NDLI Club Management — Comprehensive Report Generator (PDF + DOC)
 * Admin dashboard, client-side only. Zero server dependencies (stdlib-only safe).
 *
 * One-click comprehensive report covering:
 *   1. Executive summary   2. National snapshot   3. Detailed statistical analytics
 *   4. Field-difficulty tier split + fairness advisory
 *   5. AI-powered strategic roadmap (30/90/365-day, dual pacing targets)
 *   6. Employee performance analysis   7. Generation metadata
 *
 * ===================== FAIRNESS FRAME — ADVISORY LAYER ONLY =====================
 * Client requirement: the North zone (especially Jammu & Kashmir and Ladakh) and
 * the North East are materially harder to work / penetrate than other zones, and
 * EVERY report must account for it. This module implements the approved,
 * tiered field-difficulty framework — and ONLY this framework:
 *   (a) Official composite scores / star ratings / the 50-30-20-10 rubric maths
 *       are UNTOUCHED. They are rendered verbatim from the platform engines
 *       ( /api/admin/employee-performance ) and remain the single source of
 *       truth. Nothing here re-weights, re-rounds or recomputes them.
 *   (b) State-level tiers, client-anchored:
 *         HIGH-DIFFICULTY FIELD = Jammu & Kashmir, Ladakh + the 8 North East
 *         states (Arunachal Pradesh, Assam, Manipur, Meghalaya, Mizoram,
 *         Nagaland, Sikkim, Tripura). Every other state / UT = Standard Field.
 *       NO decimal multipliers and NO score adjustments of any kind.
 *   (c) Tier splits are ADDITIVE, clearly-labelled columns/sections, plus a
 *       clearly-labelled "Advisory — Field-Difficulty Context" narrative.
 *   (d) The roadmap carries dual pacing targets (national pace vs
 *       high-difficulty-field pace) so hard zones get realistic velocity
 *       expectations.
 *
 * PDF path: dedicated on-page printable report view + @media print; the print
 * dialog is invoked SYNCHRONOUSLY from the click handler (transient user
 * activation must be preserved — same lesson as the certificate Print fix in
 * static/js/certificate_engine.js), with afterprint cleanup + timeout fallback.
 * Popup windows are NOT used at all.
 * DOC path: the same report HTML exported through an application/msword blob.
 */
(function () {
  "use strict";

  /* ============================ Fairness tier map ============================ */
  /** Client-anchored HIGH-DIFFICULTY FIELD states (10). Everything else = Standard. */
  const HIGH_DIFFICULTY_FIELD_STATES = [
    "Jammu & Kashmir",
    "Ladakh",
    "Arunachal Pradesh",
    "Assam",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Sikkim",
    "Tripura"
  ];
  const TIER_HIGH = "High-Difficulty Field";
  const TIER_STANDARD = "Standard Field";
  const TIER_MIXED = "Mixed Field (High-Difficulty + Standard)";
  const CACHE_TTL_MS = 5 * 60 * 1000;
  const STATE_PERF_TIER_SPLIT = true; /* record-level club tier split via per-state engine queries */

  /* ============================== Small helpers ============================== */
  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normState(name) {
    return String(name || "")
      .toLowerCase()
      .replace(/&/g, "and")
      .replace(/[^a-z0-9 ]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  /** "high" | "standard" for a recorded state name. Unknown/empty => "". */
  function tierOfState(stateName) {
    const key = normState(stateName);
    if (!key || key === "unknown") return "";
    const highKeys = HIGH_DIFFICULTY_FIELD_STATES.map(normState);
    return highKeys.indexOf(key) !== -1 ? "high" : "standard";
  }

  /**
   * Advisory tier label for an officer's assigned jurisdiction (comma-separated).
   * Returns { label, highStates, totalStates, highOnly, standardOnly }.
   */
  function classifyJurisdiction(assignedStatesStr) {
    const parts = String(assignedStatesStr || "")
      .split(",")
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
    if (!parts.length) {
      return { label: "Jurisdiction not specified", highStates: [], totalStates: 0, highOnly: false, standardOnly: false };
    }
    const highStates = parts.filter(function (s) { return tierOfState(s) === "high"; });
    const highOnly = highStates.length === parts.length;
    const standardOnly = highStates.length === 0;
    let label = TIER_MIXED;
    if (highOnly) label = TIER_HIGH;
    else if (standardOnly) label = TIER_STANDARD;
    return { label: label, highStates: highStates, totalStates: parts.length, highOnly: highOnly, standardOnly: standardOnly };
  }

  function fmtInt(n) {
    const v = Number(n || 0);
    return isFinite(v) ? String(Math.round(v)) : "0";
  }

  function fmtShare(part, whole) {
    const p = Number(part || 0);
    const w = Number(whole || 0);
    if (w <= 0) return "0.0";
    return ((p / w) * 100).toFixed(1);
  }

  function fmtPace(n) {
    const v = Number(n || 0);
    return isFinite(v) ? v.toFixed(1) : "0.0";
  }

  function nowStamp() {
    const d = new Date();
    return {
      iso: d.toISOString(),
      local: d.toLocaleString()
    };
  }

  function todayFileStamp() {
    const d = new Date();
    const pad = function (x) { return String(x).padStart(2, "0"); };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  /* ============================ Cache & data fetch =========================== */
  let CACHE = null;          /* { data, at } */
  let PREFETCH_PROMISE = null;

  function adminToken() {
    try {
      return (typeof sessionStorage !== "undefined" && sessionStorage.getItem("ndli_admin_token")) || null;
    } catch (err) {
      return null;
    }
  }

  async function fetchJson(path) {
    const res = await apiRequest(path, "GET", null, adminToken());
    if (!res || !res.ok || !res.data || res.data.error) {
      throw new Error((res && res.data && res.data.message) || ("Request failed: " + path));
    }
    return res.data;
  }

  /**
   * Fetch everything the report needs from EXISTING admin endpoints (read-only):
   *   /api/admin/metrics, /api/admin/employee-performance,
   *   /api/admin/ai-insights, /api/admin/renewal-attention
   * plus per-state employee-performance queries for the 10 High-Difficulty Field
   * states (best-effort; used only for the advisory club tier split).
   */
  async function fetchReportData() {
    const [metrics, perf, ai, attn] = await Promise.all([
      fetchJson("/api/admin/metrics"),
      fetchJson("/api/admin/employee-performance"),
      fetchJson("/api/admin/ai-insights"),
      fetchJson("/api/admin/renewal-attention")
    ]);

    let statePerf = null;
    if (STATE_PERF_TIER_SPLIT) {
      try {
        const entries = await Promise.all(HIGH_DIFFICULTY_FIELD_STATES.map(async function (st) {
          const row = await fetchJson("/api/admin/employee-performance?state=" + encodeURIComponent(st));
          const byEmp = {};
          (row.officers || []).forEach(function (o) { byEmp[o.emp_id] = o; });
          return [st, byEmp];
        }));
        statePerf = {};
        entries.forEach(function (pair) { statePerf[pair[0]] = pair[1]; });
      } catch (err) {
        statePerf = null; /* fall back to jurisdiction attribution */
      }
    }

    return {
      metrics: metrics,
      perf: perf,
      ai: ai,
      attn: attn,
      statePerf: statePerf,
      fetchedAt: nowStamp().iso
    };
  }

  function peek() {
    if (!CACHE) return null;
    if (Date.now() - CACHE.at > CACHE_TTL_MS) return null;
    return CACHE.data;
  }

  /** Fire-and-forget cache warm. Silent on failure (no console noise). */
  function prefetch() {
    if (PREFETCH_PROMISE) return PREFETCH_PROMISE;
    if (!adminToken()) return Promise.resolve(null);
    PREFETCH_PROMISE = fetchReportData()
      .then(function (data) {
        CACHE = { data: data, at: Date.now() };
        return data;
      })
      .catch(function () {
        PREFETCH_PROMISE = null;
        return null;
      });
    return PREFETCH_PROMISE;
  }

  function notify(message, kind) {
    if (typeof showAlert === "function") {
      showAlert("admin-alert", message, kind || "success");
    }
  }

  /* ============================== Report model ============================== */

  /** Club counts by field-difficulty tier, attributed by recorded club state. */
  function clubTierSplit(stateClubs) {
    const split = { high: 0, standard: 0, unattributed: 0, total: 0 };
    Object.keys(stateClubs || {}).forEach(function (st) {
      const cnt = Number(stateClubs[st] || 0);
      const tier = tierOfState(st);
      if (tier === "high") split.high += cnt;
      else if (tier === "standard") split.standard += cnt;
      else split.unattributed += cnt;
      split.total += cnt;
    });
    return split;
  }

  /** Per-zone tier rows (official zone column + advisory tier columns by club state). */
  function zoneTierRows(stateClubs, zoneWise, zoneEfficiency) {
    const zones = ["North", "Central", "West", "East", "North East", "South"];
    return zones.map(function (zone) {
      let high = 0;
      let standard = 0;
      (CLIENT_ZONE_MAP[zone] || []).forEach(function (st) {
        const cnt = Number((stateClubs || {})[st] || 0);
        if (tierOfState(st) === "high") high += cnt;
        else standard += cnt;
      });
      const eff = (zoneEfficiency || {})[zone] || {};
      return {
        zone: zone,
        clubsOfficial: Number((zoneWise || {})[zone] || 0),
        clubsHigh: high,
        clubsStandard: standard,
        supportLogs: Number(eff.support_logs || 0),
        ratio: eff.ratio,
        tierNote: zone === "North East"
          ? TIER_HIGH + " (all 8 states)"
          : (zone === "North"
            ? "Mixed — Jammu & Kashmir & Ladakh are " + TIER_HIGH
            : TIER_STANDARD)
      };
    });
  }

  /**
   * Officers with official engine output (verbatim) + additive advisory tier columns.
   * Clubs tier split: record-level by club state (per-state engine queries) when
   *   available; the Standard column is the derived remainder so the split always
   *   ties to the official clubs_approved total. Fallback: jurisdiction attribution.
   * Activities tier split: officer-jurisdiction attribution (the platform APIs do
   *   not expose activity states; mixed-jurisdiction officers cannot be split at
   *   record level and are shown as "—" rather than an invented number).
   */
  function officerRows(perf, statePerf) {
    const officers = (perf && perf.officers) || [];
    return officers.map(function (o) {
      const juris = classifyJurisdiction(o.assigned_states);
      const clubsOfficial = Number(o.clubs_approved || 0);
      const activitiesOfficial = Number(o.total_activities || 0);
      let clubsHigh;
      let clubsMethod;
      if (statePerf) {
        clubsHigh = 0;
        HIGH_DIFFICULTY_FIELD_STATES.forEach(function (st) {
          const row = (statePerf[st] || {})[o.emp_id];
          if (row) clubsHigh += Number(row.clubs_approved || 0);
        });
        clubsMethod = "by club state";
      } else if (juris.highOnly) {
        clubsHigh = clubsOfficial;
        clubsMethod = "by officer jurisdiction";
      } else {
        clubsHigh = 0;
        clubsMethod = "by officer jurisdiction";
      }
      const clubsRemainder = Math.max(0, clubsOfficial - clubsHigh);

      let actsHigh;
      let actsStandard;
      if (juris.highOnly) {
        actsHigh = activitiesOfficial;
        actsStandard = 0;
      } else if (juris.standardOnly) {
        actsHigh = 0;
        actsStandard = activitiesOfficial;
      } else {
        actsHigh = null;
        actsStandard = null;
      }
      return {
        official: o,
        juris: juris,
        clubsHigh: clubsHigh,
        clubsRemainder: clubsRemainder,
        clubsMethod: clubsMethod,
        actsHigh: actsHigh,
        actsStandard: actsStandard
      };
    });
  }

  /** Roadmap pacing baselines derived from the official month-wise club record. */
  function pacingModel(metrics, tierSplit) {
    const months = Object.keys((metrics && metrics.month_wise_clubs) || {});
    const activeMonths = months.length || 1;
    const totalClubs = Number((metrics && metrics.summary && metrics.summary.total_clubs) || 0);
    return {
      activeMonths: activeMonths,
      totalClubs: totalClubs,
      highClubs: tierSplit.high,
      nationalPace: totalClubs / activeMonths,
      highPace: tierSplit.high / activeMonths
    };
  }

  /* ============================ HTML building blocks ======================== */
  function tableHtml(headers, rows, caption, colWidths) {
    const head = headers.map(function (h) { return "<th>" + h + "</th>"; }).join("");
    const body = rows.map(function (cells) {
      return "<tr>" + cells.map(function (c) {
        return "<td" + (c && c.align ? ' style="text-align: ' + c.align + ';"' : "") + ">" +
          (c && Object.prototype.hasOwnProperty.call(c, "html") ? c.html : String(c)) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    /* R22: optional percentage widths let the fixed table layout keep wide
       matrices readable (and printable at A4 width without right-edge clips). */
    const cols = Array.isArray(colWidths) && colWidths.length
      ? "<colgroup>" + colWidths.map(function (w) {
          return '<col style="width: ' + Number(w) + '%;">';
        }).join("") + "</colgroup>"
      : "";
    return (caption ? '<div class="rpt-caption">' + caption + "</div>" : "") +
      '<table class="rpt-table">' + cols + "<thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function cell(html, align) {
    return { html: html, align: align || "" };
  }

  function metricCard(label, value, note) {
    return '<div class="rpt-card"><div class="rpt-card-value">' + esc(value) + "</div>" +
      '<div class="rpt-card-label">' + esc(label) + "</div>" +
      (note ? '<div class="rpt-card-note">' + esc(note) + "</div>" : "") + "</div>";
  }

  function barRow(label, count, maxCount, extra) {
    const width = maxCount > 0 ? Math.max(2, Math.round((Number(count || 0) / maxCount) * 100)) : 2;
    return '<div class="rpt-bar-row"><span class="rpt-bar-label">' + esc(label) + "</span>" +
      '<span class="rpt-bar-track"><span class="rpt-bar-fill" style="width: ' + width + '%;"></span></span>' +
      '<span class="rpt-bar-count">' + esc(count) + "</span>" +
      (extra ? '<span class="rpt-bar-extra">' + esc(extra) + "</span>" : "") + "</div>";
  }

  /* ================== R22 visual summary — inline-SVG chart builders ======= */
  /* Self-contained SVG (inline attributes only) so the same chart renders in
     the print/PDF route and in the on-page report view. The DOC export carries
     the same charts as PNG <img> (see chartsAsImages below) because Word drops
     inline <svg> on HTML import. */
  const ZONE_CHART_COLORS = ["#0D7751", "#34D399", "#1A503E", "#7FD1AE", "#BFE6D3", "#D97706"];
  const RING_ACTIVE = "#0D7751";
  const RING_EXPIRING = "#D97706";
  const RING_OVERDUE = "#DC2626";
  const TIER_BAR_HIGH = "#D97706";
  const TIER_BAR_STANDARD = "#0D7751";
  const TIER_BAR_UNATTRIBUTED = "#94A3B8";

  function donutSvg(segments, centerValue, centerLabel) {
    const total = segments.reduce(function (a, s) { return a + Number(s.value || 0); }, 0) || 1;
    const r = 52, cx = 64, cy = 64, circ = 2 * Math.PI * r;
    let offset = 0;
    const arcs = segments.map(function (s) {
      const frac = Math.max(0, Number(s.value || 0)) / total;
      const dash = frac * circ;
      const seg = '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + s.color +
        '" stroke-width="16" stroke-dasharray="' + dash.toFixed(2) + " " + (circ - dash).toFixed(2) +
        '" stroke-dashoffset="' + (-offset).toFixed(2) + '" transform="rotate(-90 ' + cx + " " + cy + ')"></circle>';
      offset += dash;
      return seg;
    }).join("");
    return '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128" role="img">' +
      arcs +
      '<circle cx="' + cx + '" cy="' + cy + '" r="40" fill="#ffffff"></circle>' +
      '<text x="64" y="61" text-anchor="middle" font-size="15" font-weight="700" fill="#103125">' + esc(String(centerValue)) + "</text>" +
      '<text x="64" y="76" text-anchor="middle" font-size="7.5" fill="#55675e">' + esc(String(centerLabel)) + "</text></svg>";
  }

  function legendHtml(items) {
    return '<div class="rpt-chart-legend">' + items.map(function (it) {
      return '<span class="rpt-legend-item"><span class="rpt-legend-swatch" style="background:' + it.color +
        ';"></span>' + esc(it.label) + (it.value !== undefined ? " (" + esc(fmtInt(it.value)) + ")" : "") + "</span>";
    }).join("") + "</div>";
  }

  function trajectorySvg(months) {
    const pts = months || [];
    const W = 320, H = 118, padL = 24, padR = 8, padT = 10, padB = 20;
    const iw = W - padL - padR, ih = H - padT - padB;
    const vals = pts.map(function (m) { return Number(m.value || 0); });
    const maxV = Math.max.apply(null, vals.concat([1]));
    if (!pts.length) {
      return '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" role="img">' +
        '<text x="' + (W / 2) + '" y="' + (H / 2) + '" text-anchor="middle" font-size="10" fill="#94A3B8">No monthly data</text></svg>';
    }
    const xy = pts.map(function (m, i) {
      const x = padL + (pts.length > 1 ? (i * iw) / (pts.length - 1) : iw / 2);
      const y = padT + ih - (Number(m.value || 0) / maxV) * ih;
      return [x, y];
    });
    const line = xy.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
    const area = "M" + xy[0][0].toFixed(1) + "," + (padT + ih) + " L" + xy.map(function (p) {
      return p[0].toFixed(1) + "," + p[1].toFixed(1);
    }).join(" L") + " L" + xy[xy.length - 1][0].toFixed(1) + "," + (padT + ih) + " Z";
    const grid = [0, 0.5, 1].map(function (f) {
      const y = padT + ih - f * ih;
      return '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) +
        '" stroke="#E2E8F0" stroke-width="1" stroke-dasharray="3 3"></line>';
    }).join("");
    const dots = xy.map(function (p) {
      return '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="2.6" fill="#0D7751"></circle>';
    }).join("");
    const every = Math.max(1, Math.ceil(pts.length / 6));
    const xlabels = pts.map(function (m, i) {
      if (i % every !== 0 && i !== pts.length - 1) return "";
      return '<text x="' + xy[i][0].toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="7" fill="#55675e">' +
        esc(String(m.label || "")) + "</text>";
    }).join("");
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" role="img">' +
      '<defs><linearGradient id="rptTrajFill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#34D399" stop-opacity="0.45"></stop>' +
      '<stop offset="100%" stop-color="#34D399" stop-opacity="0.03"></stop></linearGradient></defs>' +
      grid + '<path d="' + area + '" fill="url(#rptTrajFill)"></path>' +
      '<polyline points="' + line + '" fill="none" stroke="#0D7751" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"></polyline>' +
      dots + xlabels +
      '<text x="2" y="' + (padT + 6) + '" font-size="7" fill="#94A3B8">' + esc(fmtInt(maxV)) + "</text></svg>";
  }

  function stackedTierBar(high, standard, unattributed) {
    const parts = [
      { label: TIER_HIGH, value: Number(high || 0), color: TIER_BAR_HIGH },
      { label: TIER_STANDARD, value: Number(standard || 0), color: TIER_BAR_STANDARD },
      { label: "Unattributed", value: Number(unattributed || 0), color: TIER_BAR_UNATTRIBUTED }
    ];
    const total = parts.reduce(function (a, p) { return a + p.value; }, 0) || 1;
    const W = 320, H = 26;
    let x = 0;
    const rects = parts.map(function (p) {
      const w = (p.value / total) * W;
      const seg = '<rect x="' + x.toFixed(1) + '" y="0" width="' + Math.max(0, w).toFixed(1) + '" height="' + H +
        '" fill="' + p.color + '"></rect>';
      x += w;
      return seg;
    }).join("");
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H +
      '" role="img"><rect x="0" y="0" width="' + W + '" height="' + H + '" rx="6" fill="#F1F5F9"></rect>' +
      rects + '</svg>';
  }

  function chartCard(title, svg, legend, note) {
    return '<div class="rpt-chart-card"><div class="rpt-chart-title">' + esc(title) + "</div>" + svg +
      (legend || "") + (note ? '<div class="rpt-chart-note">' + esc(note) + "</div>" : "") + "</div>";
  }

  /** R22 "easy visual summary" — four charts backed by the verbatim tables. */
  function visualSummary(model) {
    const m = model.metrics || {};
    const rh = m.renewal_health || {};
    const months = m.month_wise_clubs || {};
    const monthKeys = Object.keys(months).sort();
    const traj = monthKeys.map(function (k) {
      return { label: k, value: Number(months[k] || 0) };
    });
    const zoneSegs = (model.zoneRows || []).map(function (z, i) {
      return { label: z.zone, value: Number(z.clubsOfficial || 0), color: ZONE_CHART_COLORS[i % ZONE_CHART_COLORS.length] };
    }).filter(function (s) { return s.value > 0; });
    const tier = model.tier || { high: 0, standard: 0, unattributed: 0, total: 0 };
    const ringSegs = [
      { label: "Active validity", value: Number(rh.active_validity_count || 0), color: RING_ACTIVE },
      { label: "Expiring soon", value: Number(rh.expiring_soon_count || 0), color: RING_EXPIRING },
      { label: "Overdue", value: Number(rh.overdue_count || 0), color: RING_OVERDUE }
    ].filter(function (s) { return s.value > 0; });

    const zoneChart = chartCard("Club share by zone",
      donutSvg(zoneSegs, fmtInt((m.summary || {}).total_clubs), "CLUBS"),
      legendHtml(zoneSegs), "Engine zone counts — see the Section 3a table for the verbatim figures.");
    const trajChart = chartCard("Monthly approval trajectory",
      trajectorySvg(traj), "", "Clubs approved per month (engine output) — verbatim figures in Section 3c.");
    const ringChart = chartCard("Renewal health",
      donutSvg(ringSegs, esc(String(rh.retention_rate_pct || "0")) + "%", "RETENTION"),
      legendHtml(ringSegs), "Renewal health is reproduced verbatim from the metrics engine (Section 3d).");
    const tierChart = chartCard("Field-difficulty tier split (advisory)",
      stackedTierBar(tier.high, tier.standard, tier.unattributed),
      legendHtml([
        { label: TIER_HIGH, value: tier.high, color: TIER_BAR_HIGH },
        { label: TIER_STANDARD, value: tier.standard, color: TIER_BAR_STANDARD },
        { label: "Unattributed", value: tier.unattributed, color: TIER_BAR_UNATTRIBUTED }
      ]), "Advisory layer only — official scores and star ratings stand unchanged (Section 4).");

    return '<section class="rpt-section"><h2>Visual Summary — At a Glance</h2>' +
      '<div class="rpt-note" style="margin-top:2px;">Charts follow the R21 dashboard palette and are backed by the ' +
      "verbatim engine tables in Sections 2–4; where a chart and a table differ, the tables are the source of truth.</div>" +
      '<div class="rpt-chart-grid">' + zoneChart + trajChart + ringChart + tierChart + "</div>" +
      "</section>";
  }

  /* ================= R22b: identical charts in PDF *and* DOC ================
     Word drops inline <svg> when it imports HTML, which is why the DOC export
     used to arrive without any charts. Instead of hiding the charts from Word,
     BOTH export paths now rasterise the same four SVGs to PNG data URIs, so the
     PDF copy and the DOC/Word copy carry the very same chart images (same
     geometry, same colours, same legends). If rasterisation is unavailable the
     SVG markup is kept — the browser path still prints it correctly. */
  const CHART_RASTER_SCALE = 3;

  function svgChartSize(svgHtml) {
    const w = /width="([\d.]+)"/.exec(svgHtml);
    const h = /height="([\d.]+)"/.exec(svgHtml);
    return { w: w ? Math.round(Number(w[1])) : 320, h: h ? Math.round(Number(h[1])) : 200 };
  }

  function svgToPngUri(svgHtml) {
    return new Promise(function (resolve) {
      const size = svgChartSize(svgHtml);
      const img = new Image();
      img.onload = function () {
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(size.w * CHART_RASTER_SCALE));
        canvas.height = Math.max(1, Math.round(size.h * CHART_RASTER_SCALE));
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        try {
          resolve({ uri: canvas.toDataURL("image/png"), w: size.w, h: size.h });
        } catch (e) {
          resolve(null);
        }
      };
      img.onerror = function () { resolve(null); };
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgHtml);
    });
  }

  /** Replace every inline chart <svg> with a PNG <img> (for Word parity). */
  function chartsAsImages(contentHtml) {
    const re = /<svg\b[^>]*>[\s\S]*?<\/svg>/g;
    const found = contentHtml.match(re);
    if (!found || !found.length) return Promise.resolve(contentHtml);
    return Promise.all(found.map(svgToPngUri)).then(function (res) {
      let i = 0;
      return contentHtml.replace(re, function () {
        const r = res[i++];
        return r
          ? '<img class="rpt-chart-img" width="' + r.w + '" height="' + r.h +
            '" alt="report chart" src="' + r.uri + '">'
          : "";
      });
    });
  }

  /** Build report content with chart images; falls back to the SVG build if the
      raster step cannot finish (keeps the click path from ever hanging). */
  function buildReportContentWithCharts(data, timeoutMs) {
    const html = buildReportContent(data);
    return Promise.race([
      chartsAsImages(html),
      new Promise(function (resolve) {
        setTimeout(function () { resolve(html); }, timeoutMs || 4000);
      })
    ]);
  }

  /* ================================ Sections ================================ */

  function section1Executive(model) {
    const m = model.metrics;
    const summary = (m && m.summary) || {};
    const cov = (m && m.coverage_index) || {};
    const rh = (m && m.renewal_health) || {};
    const perf = model.perf || {};
    const top = perf.summary && perf.summary.top_officer;
    const tier = model.tier;
    const zoneRows = model.zoneRows.slice().sort(function (a, b) { return b.clubsOfficial - a.clubsOfficial; });
    const topZone = zoneRows[0] || { zone: "—", clubsOfficial: 0 };

    const cards = [
      metricCard("Total Clubs (record)", fmtInt(summary.total_clubs), "master club records"),
      metricCard("Support Logs (record)", fmtInt(summary.total_activities), "activities & support logs"),
      metricCard("Active Nodal Officers", fmtInt(summary.total_employees), "employee nodal officers"),
      metricCard("Renewal Attention", fmtInt(summary.renewal_attention_count), "expiring soon + overdue"),
      metricCard("State Coverage", fmtShare(cov.represented_count, cov.total_states) + "%",
        fmtInt(cov.represented_count) + " / " + fmtInt(cov.total_states) + " States & UTs"),
      metricCard("High-Difficulty Field Clubs", fmtInt(tier.high),
        fmtShare(tier.high, tier.total) + "% of all clubs (advisory)")
    ];

    const findings = [
      "National footprint: <strong>" + esc(fmtInt(summary.total_clubs)) + "</strong> clubs and <strong>" +
        esc(fmtInt(summary.total_activities)) + "</strong> support logs across <strong>" +
        esc(fmtInt(cov.represented_count)) + "</strong> of <strong>" + esc(fmtInt(cov.total_states)) +
        "</strong> States &amp; UTs (" + esc(fmtInt(cov.deficit_count)) + " deficit).",
      "Leading zone by club count: <strong>" + esc(topZone.zone) + "</strong> (" +
        esc(fmtInt(topZone.clubsOfficial)) + " clubs).",
      "Renewal health: retention rate <strong>" + esc(rh.retention_rate_pct) + "%</strong> — " +
        esc(fmtInt(rh.expiring_soon_count)) + " clubs expiring within 90 days, <strong>" +
        esc(fmtInt(rh.overdue_count)) + "</strong> overdue.",
      "Field-difficulty frame (advisory): <strong>" + esc(fmtInt(tier.high)) + "</strong> of <strong>" +
        esc(fmtInt(tier.total)) + "</strong> clubs (" + esc(fmtShare(tier.high, tier.total)) +
        "%) are recorded in High-Difficulty Field states (Jammu &amp; Kashmir, Ladakh and the North East). " +
        "Output in these states is expected to trail the national pace — the roadmap and dual pacing targets " +
        "in Section 5 account for this explicitly.",
      top
        ? "Top-rated officer (official rubric): <strong>" + esc(top.full_name || top.emp_id) + "</strong> — weighted score " +
          esc(Number(top.weighted_score).toFixed(2)) + ", " + esc(top.rating_label || "") + "."
        : "No officer evaluation available for the current scope."
    ];

    return '<section class="rpt-section"><h2>1. Executive Summary</h2>' +
      '<div class="rpt-card-grid">' + cards.join("") + "</div>" +
      '<h3>Headline findings</h3><ul class="rpt-list">' +
      findings.map(function (f) { return "<li>" + f + "</li>"; }).join("") + "</ul>" +
      '<div class="rpt-note">Fairness frame: the North zone — especially Jammu &amp; Kashmir and Ladakh — and the ' +
      "North East are significantly harder to work and penetrate than other zones. Every section of this report " +
      "reads performance against that reality. Official composite scores, star ratings and the 50/30/20/10 rubric " +
      "output remain the single source of truth and are reproduced unchanged.</div></section>";
  }

  function section2Snapshot(model) {
    const m = model.metrics;
    const summary = (m && m.summary) || {};
    const cov = (m && m.coverage_index) || {};
    const statusRows = Object.keys((m && m.status_wise_clubs) || {}).map(function (k) {
      return [k, fmtInt(m.status_wise_clubs[k])];
    });
    const yearRows = Object.keys((m && m.year_wise_clubs) || {}).sort().reverse().map(function (k) {
      return [k, fmtInt(m.year_wise_clubs[k])];
    });

    return '<section class="rpt-section"><h2>2. National Snapshot</h2>' +
      '<div class="rpt-card-grid">' +
      metricCard("Clubs", fmtInt(summary.total_clubs)) +
      metricCard("Activities & Support Logs", fmtInt(summary.total_activities)) +
      metricCard("Active Nodal Officers", fmtInt(summary.total_employees)) +
      metricCard("Quota Records", fmtInt(((summary.quotas || []).length))) +
      "</div>" +
      "<p><strong>Geographic coverage:</strong> " + esc(fmtInt(cov.represented_count)) + " of " +
      esc(fmtInt(cov.total_states)) + " States &amp; UTs represented (" + esc(cov.coverage_percentage) +
      "% coverage index); " + esc(fmtInt(cov.deficit_count)) + " deficit States/UTs" +
      (cov.deficit_states && cov.deficit_states.length
        ? " (" + esc(cov.deficit_states.slice(0, 8).join(", ")) + (cov.deficit_states.length > 8 ? " …" : "") + ")"
        : "") + ".</p>" +
      '<div class="rpt-two-col">' +
      tableHtml(["Registration Status", "Clubs"], statusRows, "Club status distribution (engine output)") +
      tableHtml(["Year", "Clubs Approved"], yearRows, "Year-wise approvals (engine output)") +
      "</div></section>";
  }

  function section3Analytics(model) {
    const m = model.metrics;
    const stateClubs = (m && m.state_wise_clubs) || {};
    const support = (m && m.support_type_breakdown) || {};
    const months = (m && m.month_wise_clubs) || {};
    const rh = (m && m.renewal_health) || {};
    const attn = model.attn || {};

    /* 3a. Zone / state penetration & density */
    const zoneTable = tableHtml(
      ["Zone", "Clubs (official)", "Support Logs", "Logs / Club"],
      model.zoneRows.map(function (z) {
        return [z.zone, fmtInt(z.clubsOfficial), fmtInt(z.supportLogs), z.ratio !== undefined ? esc(z.ratio) : "—"];
      }),
      "Zone efficiency (engine output)"
    );

    const stateRows = Object.keys(stateClubs).map(function (st) {
      return { state: st, count: Number(stateClubs[st] || 0) };
    }).sort(function (a, b) { return b.count - a.count || a.state.localeCompare(b.state); });
    const maxState = stateRows.length ? stateRows[0].count : 1;
    const stateTable = tableHtml(
      ["State / UT", "Zone", "Clubs", "Density", "Penetration"],
      stateRows.map(function (r) {
        return [
          esc(r.state),
          esc(clientGetZoneForState(r.state) || "—"),
          fmtInt(r.count),
          barRow("", r.count, maxState, ""),
          '<span class="rpt-tag">' + esc(penetrationLabel(r.count)) + "</span>"
        ];
      }),
      "State-wise club penetration &amp; density (engine output)"
    );

    /* 3b. Support mix (50/30/20/10 rubric components) */
    const supportTotal = Object.keys(support).reduce(function (acc, k) { return acc + Number(support[k] || 0); }, 0);
    const supportTable = tableHtml(
      ["Support Type", "Logs", "Share"],
      Object.keys(support).map(function (k) {
        return [esc(k), fmtInt(support[k]), fmtShare(support[k], supportTotal) + "%"];
      }),
      "Support mix — 50/30/20/10 rubric components (engine output)"
    );

    /* 3c. Monthly trajectory */
    const monthKeys = Object.keys(months).sort();
    const maxMonth = monthKeys.reduce(function (acc, k) { return Math.max(acc, Number(months[k] || 0)); }, 1);
    const monthTable = tableHtml(
      ["Month", "Clubs Approved", "Trajectory"],
      monthKeys.map(function (k) {
        return [esc(k), fmtInt(months[k]), barRow("", months[k], maxMonth, "")];
      }),
      "Monthly approval trajectory (engine output)"
    );

    /* 3d. Renewal health */
    const attentionClubs = (attn.clubs || []).slice(0, 12);
    const attnTable = tableHtml(
      ["Club ID", "Institution", "State", "Field Tier (Advisory)", "Attention", "Due"],
      attentionClubs.map(function (c) {
        const tier = tierOfState(c.state);
        return [
          esc(c.club_id),
          esc(c.institution_name),
          esc(c.state || "—"),
          '<span class="rpt-tag">' + esc(tier === "high" ? TIER_HIGH : (tier === "standard" ? TIER_STANDARD : "Unattributed")) + "</span>",
          esc(c.attention_type),
          esc(c.next_renewal_due_date || c.renewal_date || "—")
        ];
      }),
      "Renewal attention — highest-risk clubs (AI renewal-attention scan; top " + attentionClubs.length + ")"
    );

    return '<section class="rpt-section"><h2>3. Detailed Statistical Analytics</h2>' +
      "<h3>3a. Zone &amp; State Penetration and Density</h3>" + zoneTable + stateTable +
      "<h3>3b. Support Mix (50/30/20/10 components)</h3>" + supportTable +
      "<h3>3c. Monthly Trajectory</h3>" + monthTable +
      "<h3>3d. Renewal Health</h3>" +
      '<div class="rpt-card-grid">' +
      metricCard("Total Clubs", fmtInt(rh.total_clubs)) +
      metricCard("Active Validity", fmtInt(rh.active_validity_count)) +
      metricCard("Expiring Soon (90 days)", fmtInt(rh.expiring_soon_count)) +
      metricCard("Overdue", fmtInt(rh.overdue_count)) +
      metricCard("Retention Rate", esc(rh.retention_rate_pct) + "%") +
      metricCard("Renewal Attention (scan)", fmtInt(attn.total_attention_count),
        fmtInt(attn.overdue_count) + " overdue · " + fmtInt(attn.expiring_soon_count) + " expiring") +
      "</div>" +
      '<div class="rpt-note">Renewal health figures are reproduced verbatim from the admin metrics engine. ' +
      "The attention list is produced by the AI renewal-attention scan, which additionally merges " +
      "employee-node club records; counts may therefore exceed the master-CSV renewal health figures. " +
      "Both sources are shown as-is, without reconciliation maths.</div>" +
      attnTable + "</section>";
  }

  function penetrationLabel(count) {
    const c = Number(count || 0);
    if (c >= 4) return "High Density";
    if (c >= 2) return "Moderate Density";
    if (c === 1) return "Initial Presence";
    return "Deficit (0 clubs)";
  }

  function section4Tiers(model) {
    const tier = model.tier;
    const pacing = model.pacing;

    const nationalTable = tableHtml(
      ["Field-Difficulty Tier (Advisory)", "States / UTs", "Clubs", "Share of Clubs"],
      [
        [TIER_HIGH + " — Jammu &amp; Kashmir, Ladakh + 8 North East states", "10", fmtInt(tier.high), fmtShare(tier.high, tier.total) + "%"],
        [TIER_STANDARD + " — all other States/UTs", "26", fmtInt(tier.standard), fmtShare(tier.standard, tier.total) + "%"],
        ["Records without a recorded state (unattributed)", "—", fmtInt(tier.unattributed), fmtShare(tier.unattributed, tier.total) + "%"]
      ],
      "National club split by field-difficulty tier — attributed by recorded club state (advisory, additive)"
    );

    const zoneTable = tableHtml(
      ["Zone", "Clubs (official)", "Clubs — High-Difficulty Field (Advisory)", "Clubs — Standard Field (Advisory)", "Activities (official)", "Zone Tier Note (Advisory)"],
      model.zoneRows.map(function (z) {
        return [
          z.zone,
          fmtInt(z.clubsOfficial),
          fmtInt(z.clubsHigh),
          fmtInt(z.clubsStandard),
          fmtInt(z.supportLogs),
          esc(z.tierNote)
        ];
      }),
      "Zone split by field-difficulty tier — additive advisory columns beside the official zone figures"
    );

    return '<section class="rpt-section"><h2>4. Field-Difficulty Tier Split (Advisory)</h2>' +
      nationalTable + zoneTable +
      "<h3>Advisory — Field-Difficulty Context</h3>" +
      '<div class="rpt-advisory">' +
      "<p><strong>Why this frame exists.</strong> The North zone — especially Jammu &amp; Kashmir and Ladakh — " +
      "and the North East are significantly harder to work and penetrate than other zones: longer travel times, " +
      "terrain and connectivity constraints, thinner institutional networks and slower administrative cycles. " +
      "Reading their output against the national pace alone would systematically underrate the officers and zones " +
      "working that terrain. This report therefore permanently carries this advisory frame in its analysis, in its " +
      "expected-velocity benchmarks (Section 5) and in its roadmap prioritization.</p>" +
      "<p><strong>What this frame is not.</strong> Advisory layer only — official composite scores, star ratings " +
      "and the 50/30/20/10 rubric output remain the single source of truth. No score is re-weighted, adjusted, " +
      "multiplied or re-rounded anywhere in this report; the tier columns are additive context beside the official " +
      "figures, never a replacement for them.</p>" +
      "<p><strong>Tier definitions (client-anchored, state-level).</strong> <em>" + esc(TIER_HIGH) + "</em> = " +
      "Jammu &amp; Kashmir, Ladakh + all 8 North East states (Arunachal Pradesh, Assam, Manipur, Meghalaya, " +
      "Mizoram, Nagaland, Sikkim, Tripura) — 10 States/UTs in total. Every other State/UT is <em>" +
      esc(TIER_STANDARD) + "</em>.</p>" +
      "<p><strong>Where the record stands today.</strong> " + esc(fmtInt(tier.high)) + " of " +
      esc(fmtInt(tier.total)) + " clubs (" + esc(fmtShare(tier.high, tier.total)) + "%) are recorded in " +
      esc(TIER_HIGH) + " states, against " + esc(fmtInt(tier.standard)) + " (" +
      esc(fmtShare(tier.standard, tier.total)) + "%) in " + esc(TIER_STANDARD) + " states. Observed club-approval " +
      "pace runs at about " + esc(fmtPace(pacing.highPace)) + " clubs/month in " + esc(TIER_HIGH) +
      " states versus " + esc(fmtPace(pacing.nationalPace)) + " clubs/month nationally — the gap is expected, " +
      "not underperformance.</p>" +
      "</div>" +
      '<div class="rpt-note">Method: club tier columns attribute each club by its recorded state (exact, record-level). ' +
      "Activity tier columns — where shown — attribute each officer's activities to the field-difficulty tier of " +
      "their assigned jurisdiction, because the platform APIs expose no per-activity state; officers with mixed " +
      "jurisdictions are shown as &ldquo;—&rdquo; rather than an invented split.</div>" +
      "</section>";
  }

  function section5Roadmap(model) {
    const ai = model.ai || {};
    const recs = ai.strategic_recommendations || [];
    const pacing = model.pacing;
    const metrics = (ai.metrics) || {};
    const cov = (model.metrics && model.metrics.coverage_index) || {};

    const recItems = recs.length
      ? recs.map(function (r) {
          return '<div class="rpt-rec"><div class="rpt-rec-head">' +
            '<span class="rpt-tag">' + esc(r.priority) + " Priority • " + esc(r.category) + "</span>" +
            '<strong class="rpt-rec-title">' + esc(r.title) + "</strong></div>" +
            "<p><em>Analysis (engine, verbatim):</em> " + esc(r.insight) + "</p>" +
            "<p><em>Recommended policy (engine, verbatim):</em> " + esc(r.action) + "</p></div>";
        }).join("")
      : "<p>The AI Decision Engine returned no strategic recommendations for the current record.</p>";

    const rows = [];
    recs.forEach(function (r) {
      const horizon = r.priority === "High" ? "30 days" : (r.priority === "Medium" ? "90 days" : "365 days");
      rows.push([
        horizon,
        "Deliver engine recommendation: &ldquo;" + esc(r.title) + "&rdquo; — " + esc(r.action),
        "AI Decision Engine — " + esc(r.category) + " (" + esc(r.priority) + " Priority)",
        "High-Difficulty Field states run at the high-difficulty-field pacing target, never the national pace."
      ]);
    });
    rows.push([
      "30 days",
      "Stabilize renewal health: " + esc(fmtInt(metrics.overdue_count)) + " overdue and " +
        esc(fmtInt(metrics.expiring_soon_count)) + " expiring-soon clubs are under renewal attention (engine metrics).",
      "Derived from AI Decision Engine metrics",
      "Renewal outreach is scheduled first for High-Difficulty Field states where travel and administrative lead times are longest."
    ]);
    rows.push([
      "90 days",
      "Open structured outreach across the " + esc(fmtInt(cov.deficit_count)) +
        " deficit States/UTs, sequencing Jammu &amp; Kashmir, Ladakh and the North East ahead of comparable " +
        esc(TIER_STANDARD) + " gaps (difficulty-aware prioritization).",
      "Derived from AI Decision Engine penetration metrics",
      "Progress measured per-tier against the dual pacing targets below."
    ]);
    rows.push([
      "365 days",
      "Advance toward full national coverage — " + esc(fmtInt(cov.represented_count)) + " / " +
        esc(fmtInt(cov.total_states)) + " States &amp; UTs represented today (engine metrics) — while sustaining " +
        "both pacing curves through the cycle.",
      "Derived from AI Decision Engine penetration metrics",
      "Annual review re-baselines both pacing targets from the next year's observed record."
    ]);

    const pacingTable = tableHtml(
      ["Pacing Target", "Observed Baseline", "Expected Velocity"],
      [
        [
          "National pacing target",
          esc(fmtPace(pacing.nationalPace)) + " clubs/month (" + esc(fmtInt(pacing.totalClubs)) +
            " clubs over " + esc(fmtInt(pacing.activeMonths)) + " active months)",
          "Sustain at or above the observed national baseline across Standard Field states."
        ],
        [
          "High-difficulty-field pacing target",
          esc(fmtPace(pacing.highPace)) + " clubs/month (" + esc(fmtInt(pacing.highClubs)) +
            " clubs over " + esc(fmtInt(pacing.activeMonths)) + " active months)",
          "Sustain at or above the observed High-Difficulty Field baseline across Jammu &amp; Kashmir, Ladakh and the North East — evaluated on its own curve."
        ]
      ],
      "Dual pacing targets — derived from the platform's own month-wise club record (no external multipliers)"
    );

    return '<section class="rpt-section"><h2>5. AI-Powered Strategic Roadmap</h2>' +
      "<h3>5a. AI Decision Engine — Strategic Recommendations (verbatim)</h3>" + recItems +
      "<h3>5b. Difficulty-aware roadmap — 30 / 90 / 365-day milestones</h3>" +
      tableHtml(["Horizon", "Milestone", "Engine Basis", "Difficulty-aware Pacing"], rows) +
      "<h3>5c. Dual pacing targets</h3>" + pacingTable +
      '<div class="rpt-note">Milestone horizons map engine recommendations by their engine priority ' +
      "(High → 30 days, Medium → 90 days, otherwise → 365 days); gaps are filled only with milestones derived " +
      "from engine metrics, and never contradict the engine&rsquo;s recommendations. Pacing baselines are derived " +
      "from the platform&rsquo;s own observed monthly record — no decimal multipliers or score adjustments are " +
      "applied anywhere.</div></section>";
  }

  function section6Employees(model) {
    const perf = model.perf || {};
    const weight = perf.weightage || {};
    const summary = perf.summary || {};
    const rows = model.officers;

    const matrixTable = tableHtml(
      ["Rank", "Officer &amp; Zone", "Assigned Jurisdiction", "Clubs Approved (50% Wt)", "Online Training (10% Wt)",
        "Offline Training (20% Wt)", "Other Supports (30% Wt)", "Weighted Score", "Star Rating (1 to 5 ★)"],
      rows.map(function (r) {
        const o = r.official;
        return [
          "#" + esc(o.rank),
          esc(o.full_name || o.emp_id) + ' <span class="rpt-tag">' + esc(o.emp_id) + "</span> " + esc(o.zone || ""),
          esc(o.assigned_states || "All India"),
          fmtInt(o.clubs_approved),
          fmtInt(o.online_training),
          fmtInt(o.offline_training),
          fmtInt(o.other_supports),
          "<strong>" + esc(Number(o.weighted_score).toFixed(2)) + "</strong>",
          esc(o.stars_display) + " " + esc(o.rating_label)
        ];
      }),
      "Star matrix — official engine output (Scoring Rubric: 50% Club Approval + 30% Other Supports + 20% Offline Training + 10% Online Training); reproduced verbatim",
      [5, 15, 19, 9, 9, 9, 9, 9, 16]
    );

    const tierTable = tableHtml(
      ["Officer", "Field-Difficulty Jurisdiction (Advisory)",
        "Clubs — High-Difficulty Field (Advisory, by club state)",
        "Clubs — Standard Field / Unattributed (Advisory, derived remainder)",
        "Activities — High-Difficulty Field (Advisory, by jurisdiction)",
        "Activities — Standard Field (Advisory, by jurisdiction)"],
      rows.map(function (r) {
        return [
          esc(r.official.full_name || r.official.emp_id),
          esc(r.juris.label) + (r.juris.highOnly
            ? " (" + esc(fmtInt(r.juris.highStates.length)) + "/" + esc(fmtInt(r.juris.totalStates)) + " states)"
            : (r.juris.totalStates
              ? " (" + esc(fmtInt(r.juris.highStates.length)) + "/" + esc(fmtInt(r.juris.totalStates)) + " High-Difficulty)"
              : "")),
          fmtInt(r.clubsHigh) + ' <span class="rpt-mini">(' + esc(r.clubsMethod) + ")</span>",
          fmtInt(r.clubsRemainder),
          r.actsHigh === null ? "—" : fmtInt(r.actsHigh),
          r.actsStandard === null ? "—" : fmtInt(r.actsStandard)
        ];
      }),
      "Field-difficulty tier split by officer — additive advisory columns beside the official matrix above",
      [12, 23, 17, 16, 16, 16]
    );

    const detailCards = rows.map(function (r) {
      const o = r.official;
      const actsSplitLine = r.actsHigh === null
        ? "Activities cannot be split at record level for a mixed jurisdiction (the platform APIs expose no activity state); see the zone analysis in Section 4."
        : "Activities are attributed to " + esc(r.juris.label) + " by assigned jurisdiction: " +
          esc(fmtInt(r.actsHigh)) + " in " + esc(TIER_HIGH) + " terrain, " + esc(fmtInt(r.actsStandard)) +
          " in " + esc(TIER_STANDARD) + " terrain.";
      return '<div class="rpt-officer"><h4>' + esc(o.full_name || o.emp_id) + " · " + esc(o.emp_id) +
        ' <span class="rpt-tag">' + esc(o.zone || "") + "</span></h4>" +
        "<p><strong>Assigned jurisdiction:</strong> " + esc(o.assigned_states || "All India") + "</p>" +
        "<p><strong>Official engine output (verbatim):</strong> clubs approved " + esc(fmtInt(o.clubs_approved)) +
        " · online training " + esc(fmtInt(o.online_training)) + " · offline training " +
        esc(fmtInt(o.offline_training)) + " · other supports " + esc(fmtInt(o.other_supports)) +
        " · weighted score " + esc(Number(o.weighted_score).toFixed(2)) + " · " + esc(o.rating_label) +
        " (" + esc(o.stars_display) + ") · rank #" + esc(o.rank) + ".</p>" +
        "<p><strong>Difficulty-tier narrative (advisory):</strong> " +
        (r.juris.highOnly
          ? "This officer's entire assigned jurisdiction lies in " + esc(TIER_HIGH) +
            " states (" + esc(r.juris.highStates.join(", ")) + "). Their output is expected to track the " +
            "high-difficulty-field pacing target, not the national pace, and is not comparable one-to-one with " +
            esc(TIER_STANDARD) + " jurisdictions."
          : (r.juris.standardOnly
            ? "This officer's assigned jurisdiction lies entirely in " + esc(TIER_STANDARD) +
              " states, benchmarked against the national pacing target."
            : "This officer carries a mixed jurisdiction (" + esc(fmtInt(r.juris.highStates.length)) + " of " +
              esc(fmtInt(r.juris.totalStates)) + " assigned states are " + esc(TIER_HIGH) + ": " +
              esc(r.juris.highStates.join(", ")) + "). Their record blends both terrains; the hard-terrain " +
              "share must be read at the high-difficulty-field pacing target before any comparative judgment.")) +
        " " + actsSplitLine +
        " " + esc(fmtInt(r.clubsHigh)) + " of " + esc(fmtInt(o.clubs_approved)) +
        " clubs are recorded in " + esc(TIER_HIGH) + " states (" + esc(r.clubsMethod) + "). " +
        "<em>Advisory only — the official score and star rating above stand unchanged.</em></p></div>";
    }).join("");

    return '<section class="rpt-section"><h2>6. Employee Performance Analysis</h2>' +
      '<div class="rpt-note">Weightage (engine declaration): ' +
      esc(weight.club_approval_pct) + "% Club Approval · " + esc(weight.other_supports_pct) +
      "% Other Supports · " + esc(weight.offline_training_pct) + "% Offline Training · " +
      esc(weight.online_training_pct) + "% Online Training. Officers evaluated: " +
      esc(fmtInt(summary.total_officers)) + " · maximum weighted score (engine): " +
      esc(Number(summary.max_score).toFixed(2)) + ".</div>" +
      "<h3>6a. Star Rating Matrix (official engine output)</h3>" + matrixTable +
      "<h3>6b. Field-Difficulty Tier Split by Officer (Advisory)</h3>" + tierTable +
      "<h3>6c. Per-Officer Detail &amp; Difficulty-Tier Narrative</h3>" + detailCards +
      '<div class="rpt-note">Official composite scores, star ratings and the 50/30/20/10 rubric output are ' +
      "reproduced exactly as computed by the platform decision engine. The tier columns and narratives are an " +
      "additive advisory layer: they contextualize field difficulty and never adjust, re-weight or replace the " +
      "official figures.</div></section>";
  }

  function section7Metadata(model) {
    const m = model.metrics || {};
    const summary = m.summary || {};
    const ai = model.ai || {};
    return '<section class="rpt-section"><h2>7. Generation Metadata</h2>' +
      tableHtml(["Item", "Value"], [
        ["Report generated at", esc(model.generatedAt.local) + " (" + esc(model.generatedAt.iso) + ")"],
        ["Data as of (AI Decision Engine snapshot)", esc(ai.timestamp || model.data.fetchedAt)],
        ["Scope", "All operational zones · all inception years (complete present record)"],
        ["Club records", fmtInt(summary.total_clubs)],
        ["Activity &amp; support-log records", fmtInt(summary.total_activities)],
        ["Officer records evaluated", fmtInt((model.perf && model.perf.summary && model.perf.summary.total_officers) || 0)],
        ["Renewal-attention records", fmtInt(summary.renewal_attention_count)],
        ["Sources", "Existing admin engine endpoints: /api/admin/metrics, /api/admin/employee-performance, /api/admin/ai-insights, /api/admin/renewal-attention (read-only)"],
        ["Fairness frame", "Advisory layer only — official composite scores, star ratings and the 50/30/20/10 rubric output remain the single source of truth."]
      ]) + "</section>";
  }

  /* ============================== Report assembly =========================== */

  const REPORT_STYLE =
    '<style class="rpt-style">' +
    ".rpt-doc{font-family:\"Segoe UI\",Roboto,Helvetica,Arial,sans-serif;color:#1c2b24;font-size:12.5px;line-height:1.5;}" +
    ".rpt-doc h1{font-size:21px;margin:0 0 2px;color:#103125;}" +
    ".rpt-doc h2{font-size:16px;margin:22px 0 8px;padding-bottom:4px;border-bottom:2px solid #1A503E;color:#103125;}" +
    ".rpt-doc h3{font-size:13.5px;margin:15px 0 6px;color:#1A503E;}" +
    ".rpt-doc h4{font-size:12.5px;margin:0 0 4px;color:#103125;}" +
    ".rpt-head{border-bottom:3px solid #1A503E;padding-bottom:8px;margin-bottom:10px;}" +
    ".rpt-sub{color:#3d5449;font-size:12px;margin:2px 0;}" +
    ".rpt-section{margin-bottom:8px;}" +
    ".rpt-card-grid{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0;}" +
    ".rpt-card{flex:1 1 150px;min-width:140px;border:1px solid #c7d6cf;border-radius:8px;padding:8px 10px;background:#f6faf8;}" +
    ".rpt-card-value{font-size:18px;font-weight:700;color:#103125;}" +
    ".rpt-card-label{font-size:10.5px;text-transform:uppercase;letter-spacing:0.4px;color:#41564c;font-weight:600;}" +
    ".rpt-card-note{font-size:10px;color:#55675e;margin-top:2px;}" +
    ".rpt-table{width:100%;table-layout:fixed;border-collapse:collapse;margin:8px 0 16px;font-size:11px;}" +
    ".rpt-table th,.rpt-table td{overflow-wrap:break-word;word-break:normal;}" +
    ".rpt-table th{background:#e9f2ee;border:1px solid #b9cdc4;padding:5px 6px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:0.3px;color:#22332b;white-space:normal;}" +
    ".rpt-table td{border:1px solid #cfdcd6;padding:4px 6px;vertical-align:top;}" +
    /* R22b: style.css `tbody tr:last-child td{border-bottom:none}` (specificity
       0-1-3) BEATS `.rpt-table td` (0-1-1) and was stripping the closing edge
       off every report table — the "no breathing room under the last row"
       defect. This rule outranks it (0-2-3) and restores the bottom border. */
    ".rpt-table tbody tr:last-child td{border-bottom:1px solid #cfdcd6;}" +
    ".rpt-caption{font-size:10.5px;font-weight:700;color:#41564c;margin:10px 0 3px;text-transform:uppercase;letter-spacing:0.3px;}" +
    /* R22 visual summary — chart cards (PDF + on-page as SVG, DOC as PNG) */
    ".rpt-chart-grid{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0 6px;}" +
    ".rpt-chart-card{flex:1 1 300px;min-width:280px;border:1px solid #c7d6cf;border-radius:8px;padding:8px 10px;background:#ffffff;}" +
    ".rpt-chart-img{display:block;max-width:100%;height:auto;margin:2px auto;}" +
    ".rpt-chart-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;color:#41564c;margin:0 0 4px;}" +
    ".rpt-chart-note{font-size:9px;color:#55675e;margin:4px 0 0;}" +
    ".rpt-chart-legend{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px;}" +
    ".rpt-legend-item{display:flex;align-items:center;gap:4px;font-size:9px;color:#22332b;}" +
    ".rpt-legend-swatch{width:9px;height:9px;border-radius:2px;display:inline-block;flex:0 0 auto;}" +
    ".rpt-two-col{display:flex;gap:14px;flex-wrap:wrap;}" +
    ".rpt-two-col>*{flex:1 1 320px;}" +
    ".rpt-note{border-left:4px solid #1A503E;background:#f2f7f4;padding:7px 10px;margin:10px 0;font-size:10.8px;color:#2c3f36;}" +
    ".rpt-advisory{border:1px dashed #B45309;border-radius:8px;background:#fdf7ee;padding:10px 12px;}" +
    ".rpt-advisory p{margin:6px 0;}" +
    ".rpt-tag{display:inline-block;background:#e9f2ee;border:1px solid #b9cdc4;border-radius:999px;padding:1px 7px;font-size:9.5px;font-weight:700;color:#22332b;white-space:nowrap;}" +
    ".rpt-mini{font-size:9px;color:#55675e;}" +
    ".rpt-list{margin:6px 0 6px 18px;padding:0;}" +
    ".rpt-list li{margin:4px 0;}" +
    ".rpt-rec{border:1px solid #cfdcd6;border-radius:8px;padding:8px 10px;margin:7px 0;}" +
    ".rpt-rec p{margin:4px 0;font-size:11px;}" +
    ".rpt-rec-head{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:3px;}" +
    ".rpt-officer{border:1px solid #cfdcd6;border-radius:8px;padding:8px 10px;margin:8px 0;}" +
    ".rpt-officer p{margin:4px 0;font-size:11px;}" +
    ".rpt-bar-row{display:flex;align-items:center;gap:5px;}" +
    ".rpt-bar-track{flex:1 1 90px;min-width:70px;height:8px;background:#e2e8f0;border-radius:999px;overflow:hidden;}" +
    ".rpt-bar-fill{display:block;height:100%;background:#1A503E;border-radius:999px;}" +
    ".rpt-bar-count{font-size:10px;font-weight:700;color:#22332b;}" +
    ".rpt-bar-label,.rpt-bar-extra{font-size:10px;color:#41564c;}" +
    "@media print{.rpt-doc{font-size:10.5px;}.rpt-card-grid{gap:6px;}.rpt-section{page-break-inside:auto;}" +
    /* R22 print fidelity: tables fit the printable width (no right-edge clip),
       keep breathing room below, and never split a row across pages. */
    ".rpt-table{margin:10px 0 22px;font-size:8.6px;}.rpt-table th{font-size:7.8px;padding:4px 4px;}" +
    ".rpt-table td{padding:4px 5px;}.rpt-table tr{page-break-inside:avoid;break-inside:avoid;}" +
    ".rpt-table tbody tr:last-child td{padding-bottom:8px;}" +
    ".rpt-chart-card{page-break-inside:avoid;break-inside:avoid;}}" +
    "</style>";

  function buildReportContent(data) {
    const model = buildModel(data);
    const stamp = model.generatedAt;
    const summary = (model.metrics && model.metrics.summary) || {};
    return REPORT_STYLE +
      '<div class="rpt-doc">' +
      '<div class="rpt-head"><h1>NDLI Club Management — Comprehensive Report</h1>' +
      '<div class="rpt-sub">National Digital Library of India Club Management System · IIT Kharagpur — Central Administration Office · 6 Regional Nodal Zones</div>' +
      '<div class="rpt-sub">Present-record report with statistical analytics, roadmap and employee performance analysis — including the permanent Field-Difficulty fairness frame (advisory).</div>' +
      '<div class="rpt-sub">Generated ' + esc(stamp.local) + " · Scope: All zones · All years · " +
      esc(fmtInt(summary.total_clubs)) + " club records · " + esc(fmtInt(summary.total_activities)) +
      " activity records</div></div>" +
      section1Executive(model) +
      visualSummary(model) +
      section2Snapshot(model) +
      section3Analytics(model) +
      section4Tiers(model) +
      section5Roadmap(model) +
      section6Employees(model) +
      section7Metadata(model) +
      "</div>";
  }

  function buildModel(data) {
    const tier = clubTierSplit(data.metrics && data.metrics.state_wise_clubs);
    return {
      metrics: data.metrics,
      perf: data.perf,
      ai: data.ai,
      attn: data.attn,
      data: data,
      generatedAt: nowStamp(),
      tier: tier,
      zoneRows: zoneTierRows(
        (data.metrics && data.metrics.state_wise_clubs) || {},
        (data.metrics && data.metrics.zone_wise_clubs) || {},
        (data.metrics && data.metrics.zone_efficiency) || {}
      ),
      officers: officerRows(data.perf, data.statePerf),
      pacing: pacingModel(data.metrics, tier)
    };
  }

  /* ============================ PDF (print) route =========================== */

  /**
   * Print the open report view. MUST be invoked synchronously from the user's
   * click handler so window.print() runs under the click's transient user
   * activation (see static/js/certificate_engine.js — activation is lost in
   * async continuations, and modern browsers then silently skip printing).
   * Cleans up the transient print state on afterprint (1500ms fallback).
   */
  function printReport() {
    const root = typeof document !== "undefined" && document.getElementById("report-print-root");
    if (!root) return;
    document.body.classList.add("report-printing");
    const cleanup = function () {
      document.body.classList.remove("report-printing");
      window.removeEventListener("afterprint", cleanup);
    };
    window.addEventListener("afterprint", cleanup);
    window.print();
    setTimeout(cleanup, 1500); /* fallback if afterprint never fires */
  }

  function openReportView(contentHtml) {
    const root = document.getElementById("report-print-root");
    if (!root) return;
    root.innerHTML = contentHtml;
    document.body.classList.add("report-view-open");
    const status = document.getElementById("report-view-status");
    if (status) status.textContent = "Report ready";
  }

  function closeReportView() {
    document.body.classList.remove("report-view-open");
    document.body.classList.remove("report-printing");
    const root = document.getElementById("report-print-root");
    if (root) root.innerHTML = "";
  }

  /* ============================== DOC export ================================ */

  function wrapWordDocument(contentHtml, title) {
    return '<html xmlns:o="urn:schemas-microsoft-com:office:office" ' +
      'xmlns:w="urn:schemas-microsoft-com:office:word" ' +
      'xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8">' +
      "<title>" + esc(title) + "</title>" +
      "<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View>" +
      "<w:Zoom>100</w:Zoom></w:WordDocument></xml><![endif]-->" +
      "</head><body>" + contentHtml + "</body></html>";
  }

  function downloadDoc(data) {
    const title = "NDLI Club Management — Comprehensive Report";
    /* chartsAsImages: the DOC carries the SAME chart pictures as the PDF
       (Word cannot draw inline <svg>, so the SVGs are rasterised first). */
    return chartsAsImages(buildReportContent(data)).then(function (body) {
      const html = wrapWordDocument(body, title);
      const blob = new Blob(["\ufeff", html], { type: "application/msword" });
      const a = document.createElement("a");
      const objUrl = URL.createObjectURL(blob);
      a.href = objUrl;
      a.download = "NDLI_Comprehensive_Report_" + todayFileStamp() + ".doc";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objUrl);
      notify("Comprehensive report DOC downloaded (NDLI_Comprehensive_Report_" + todayFileStamp() + ".doc).", "success");
      return true;
    });
  }

  /* ============================ Public entry points ========================= */

  /** Async fallback when the cache is cold: fetch, open the view, let the user print/download. */
  function openWhenReady(intent) {
    const status = document.getElementById("report-view-status");
    if (status) status.textContent = "Compiling report data…";
    document.body.classList.add("report-view-open");
    prefetch().then(function (data) {
      if (!data) {
        closeReportView();
        notify("Comprehensive report could not be compiled. Please sign in as Administrator and try again.", "danger");
        return;
      }
      buildReportContentWithCharts(data).then(function (html) {
        openReportView(html);
        if (intent === "doc") {
          downloadDoc(data);
        } else {
          notify("Report data compiled. Use “Print / Save as PDF” in the report toolbar to produce the PDF.", "success");
        }
      });
    });
  }

  /**
   * Button hook — Generate Comprehensive Report (PDF).
   * Synchronous click path: when the cache is warm the report is built and
   * window.print() runs within this click (user activation preserved).
   */
  function generateComprehensiveReportPdf() {
    prefetch(); /* warm the cache for the next click (fire-and-forget) */
    const data = peek();
    if (!data) {
      openWhenReady("pdf");
      return;
    }
    /* same chart images as the DOC export (falls back to SVG if rasterising
       is unavailable) so both copies of the report are identical. */
    buildReportContentWithCharts(data).then(function (html) {
      openReportView(html);
      printReport();
    });
  }

  /** Button hook — Generate Comprehensive Report (DOC, application/msword). */
  function generateComprehensiveReportDoc() {
    prefetch(); /* warm the cache for the next click (fire-and-forget) */
    const data = peek();
    if (!data) {
      openWhenReady("doc");
      return;
    }
    downloadDoc(data);
  }

  /**
   * R20: "Create Report" split dropdown (PDF / DOC) — replaces the two long
   * toolbar buttons. Menu chrome lives in style.css (.report-menu*), markup in
   * templates/admin.html. Keyboard: Enter/Space on the button toggles, Escape
   * dismisses, focus returns to the trigger.
   */
  function toggleReportMenu(evt) {
    if (evt && evt.stopPropagation) evt.stopPropagation();
    const menu = document.getElementById("report-menu");
    const btn = document.getElementById("btn-create-report");
    if (!menu) return;
    const willOpen = menu.hasAttribute("hidden");
    if (willOpen) {
      menu.removeAttribute("hidden");
    } else {
      menu.setAttribute("hidden", "");
    }
    if (btn) btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  }

  function closeReportMenu() {
    const menu = document.getElementById("report-menu");
    const btn = document.getElementById("btn-create-report");
    if (!menu || menu.hasAttribute("hidden")) return;
    menu.setAttribute("hidden", "");
    if (btn) {
      btn.setAttribute("aria-expanded", "false");
      btn.focus();
    }
  }

  const ReportGenerator = {
    /* entry points */
    generatePdf: generateComprehensiveReportPdf,
    generateDoc: generateComprehensiveReportDoc,
    toggleReportMenu: toggleReportMenu,
    closeReportMenu: closeReportMenu,
    printReport: printReport,
    closeReportView: closeReportView,
    downloadDoc: function () {
      prefetch().then(function (data) {
        if (data) downloadDoc(data);
        else notify("Comprehensive report data unavailable. Please sign in as Administrator and try again.", "danger");
      });
    },
    prefetch: prefetch,
    /* exported for testability (pure helpers + tier constants) */
    HIGH_DIFFICULTY_FIELD_STATES: HIGH_DIFFICULTY_FIELD_STATES,
    TIER_HIGH: TIER_HIGH,
    TIER_STANDARD: TIER_STANDARD,
    tierOfState: tierOfState,
    classifyJurisdiction: classifyJurisdiction
  };

  if (typeof window !== "undefined") {
    window.ReportGenerator = ReportGenerator;
    window.generateComprehensiveReportPdf = generateComprehensiveReportPdf;
    window.generateComprehensiveReportDoc = generateComprehensiveReportDoc;
    window.toggleReportMenu = toggleReportMenu;
    window.closeReportMenu = closeReportMenu;
    if (typeof document !== "undefined") {
      const init = function () {
        prefetch();
        /* R20 dropdown: dismiss on outside click / Escape */
        document.addEventListener("click", function (e) {
          const menu = document.getElementById("report-menu");
          if (!menu || menu.hasAttribute("hidden")) return;
          const trigger = document.getElementById("btn-create-report");
          if (trigger && trigger.contains(e.target)) return;
          closeReportMenu();
        });
        document.addEventListener("keydown", function (e) {
          if (e.key === "Escape") closeReportMenu();
        });
      };
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
      } else {
        init();
      }
    }
  }
})();
