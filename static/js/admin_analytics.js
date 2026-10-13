    function renderKPIs(data) {
      // R30v3: headline = live + migrated (the combined programme total).
      // live_clubs excludes imported records, so bulk-importing the club log
      // can never double-count.
      // R38: the arithmetic lives server-side (db/counting_rules.py) — this
      // renders the fields it is given and never re-derives them.
      const migTotals = (data.summary && data.summary.migrated_totals) || {};
      const liveClubs = (data.summary.live_clubs !== undefined)
        ? data.summary.live_clubs : (data.summary.total_clubs || 0);
      const migApprovals = (data.summary.migrated_approvals !== undefined)
        ? data.summary.migrated_approvals : (migTotals.approvals || 0);
      const migSupport = migTotals.support || 0;
      const programmeTotal = data.summary.programme_total || 0;
      document.getElementById("kpi-clubs").innerText = programmeTotal;
      document.getElementById("kpi-activities").innerText = data.summary.programme_activities || 0;
      document.getElementById("kpi-nodes").innerText = data.summary.total_employees !== undefined ? data.summary.total_employees : 7;
      if (data.summary.renewal_attention_count !== undefined) {
        document.getElementById("kpi-renewals").innerText = data.summary.renewal_attention_count;
      }

      // Update descriptions based on active filter scope
      const filterZ = document.getElementById("filter-zone") ? document.getElementById("filter-zone").value : "ALL";
      const filterY = document.getElementById("filter-year") ? document.getElementById("filter-year").value : "ALL";

      let scopeDesc = "Across all 36 States & UTs";
      let actsDesc = "Real-time sync from 6 zones";
      let nodesDesc = "Dedicated CSV Node DBs";

      if (filterZ !== "ALL" || filterY !== "ALL") {
        const parts = [];
        if (filterZ !== "ALL") parts.push(`${filterZ} Zone`);
        if (filterY !== "ALL") parts.push(`${filterY}`);
        scopeDesc = `Filtered: ${parts.join(" • ")}`;
        actsDesc = `Support logs for ${parts.join(" • ")}`;
        nodesDesc = filterZ !== "ALL" ? `Officers in ${filterZ} Zone` : "Dedicated CSV Node DBs";
      }

      const clubsDescEl = document.getElementById("kpi-clubs-desc");
      if (clubsDescEl) clubsDescEl.innerText = scopeDesc;
      const actsDescEl = document.getElementById("kpi-activities-desc");
      if (actsDescEl) actsDescEl.innerText = actsDesc;

      // R30v3: explicit split wording ("incl." was misleading — the migrated
      // history is not a subset of the live count; the headline sums both)
      const migClubsEl = document.getElementById("kpi-clubs-migrated");
      if (migClubsEl) {
        if (migApprovals > 0) {
          migClubsEl.style.display = "block";
          migClubsEl.innerText = `${liveClubs} live + ${migApprovals} migrated club approvals (history)`;
        } else {
          migClubsEl.style.display = "none";
        }
      }
      const migActsEl = document.getElementById("kpi-activities-migrated");
      if (migActsEl) {
        if (migSupport > 0) {
          migActsEl.style.display = "block";
          migActsEl.innerText = `${data.summary.total_activities || 0} live logs + ${migSupport} migrated support interactions (history)`;
        } else {
          migActsEl.style.display = "none";
        }
      }
      const nodesDescEl = document.getElementById("kpi-nodes-desc");
      if (nodesDescEl) nodesDescEl.innerText = nodesDesc;
    }

    // 1. Detailed Statistical Analytics Metric Cards
    function renderStatisticalAnalytics(data) {
      const filterZ = document.getElementById("filter-zone") ? document.getElementById("filter-zone").value : "ALL";
      const filterY = document.getElementById("filter-year") ? document.getElementById("filter-year").value : "ALL";

      // Coverage Index
      const cov = data.coverage_index || {};
      const repCount = cov.represented_count !== undefined ? cov.represented_count : 0;
      const totalStates = cov.total_states || (filterZ !== "ALL" && CLIENT_ZONE_MAP[filterZ] ? CLIENT_ZONE_MAP[filterZ].length : 36);
      const covPct = cov.coverage_percentage !== undefined ? cov.coverage_percentage : 0;

      const covBadge = document.getElementById("badge-coverage-ratio");
      if (covBadge) covBadge.innerText = `${repCount} / ${totalStates} States`;
      const covVal = document.getElementById("stat-coverage-pct");
      if (covVal) covVal.innerText = `${covPct}%`;
      const covDesc = document.getElementById("stat-coverage-desc");
      if (covDesc) {
        covDesc.innerText = filterZ !== "ALL"
          ? `${cov.deficit_count || 0} States in deficit in ${filterZ} Zone`
          : `${cov.deficit_count || 0} States/UTs in deficit nationally`;
      }

      // Retention Health
      const ren = data.renewal_health || {};
      const retRate = ren.retention_rate_pct !== undefined ? ren.retention_rate_pct : 100;
      const retVal = document.getElementById("stat-retention-rate");
      if (retVal) retVal.innerText = `${retRate}%`;
      const retDesc = document.getElementById("stat-retention-desc");
      if (retDesc) retDesc.innerText = `${ren.active_validity_count || 0} active, ${ren.overdue_count || 0} overdue`;

      // Support Density Ratio
      const totalClubs = data.summary?.total_clubs || 0;
      const totalActs = data.summary?.total_activities || 0;
      const density = totalClubs > 0 ? (totalActs / totalClubs).toFixed(1) : "0.0";
      const supVal = document.getElementById("stat-support-ratio");
      if (supVal) supVal.innerText = `${density}`;

      // Leading Regional Zone / Scope Indicator
      const zCounts = data.zone_wise_clubs || {};
      const zlVal = document.getElementById("stat-zone-leader");
      const zlDesc = document.getElementById("stat-zone-leader-desc");

      if (filterZ !== "ALL") {
        if (zlVal) zlVal.innerText = `${filterZ} Zone`;
        if (zlDesc) zlDesc.innerText = `${totalClubs} approved clubs in ${filterZ} Zone scope`;
      } else {
        let topZone = "North";
        let topCount = -1;
        for (const [z, c] of Object.entries(zCounts)) {
          if (c > topCount) {
            topCount = c;
            topZone = z;
          }
        }
        if (zlVal) zlVal.innerText = `${topZone} Zone`;
        if (zlDesc) zlDesc.innerText = `${topCount >= 0 ? topCount : 0} clubs approved (${totalClubs > 0 ? Math.round((topCount/totalClubs)*100) : 0}% share)`;
      }
    }

    // 2. Zone Donut Chart SVG
    function renderZoneDonutChart(zoneWiseClubs, stateWiseClubs) {
      const container = document.getElementById("zone-donut-container");
      if (!container) return;

      const filterZ = document.getElementById("filter-zone") ? document.getElementById("filter-zone").value : "ALL";
      const titleEl = document.getElementById("zone-donut-title");
      const subtitleEl = document.getElementById("zone-donut-subtitle");

      let items = {};
      let chartLabel = "Clubs";

      if (filterZ !== "ALL" && filterZ) {
        if (titleEl) titleEl.innerText = `${filterZ} Zone: State Club Share`;
        if (subtitleEl) subtitleEl.innerText = `Distribution across states within ${filterZ} operational command`;

        const zoneStates = CLIENT_ZONE_MAP[filterZ] || [];
        zoneStates.forEach(st => {
          items[st] = (stateWiseClubs && stateWiseClubs[st]) || 0;
        });
      } else {
        if (titleEl) titleEl.innerText = "Zone-Wise Club Share";
        if (subtitleEl) subtitleEl.innerText = "Proportional distribution across 6 operational zonal commands";

        items = { "North": 0, "Central": 0, "West": 0, "East": 0, "North East": 0, "South": 0 };
        if (zoneWiseClubs && Object.keys(zoneWiseClubs).length > 0) {
          for (const [z, c] of Object.entries(zoneWiseClubs)) {
            if (items[z] !== undefined) items[z] = c;
          }
        } else {
          for (const [st, cnt] of Object.entries(stateWiseClubs || {})) {
            const z = clientGetZoneForState(st) || "Other";
            if (items[z] !== undefined) items[z] += cnt;
          }
        }
      }

      const total = Object.values(items).reduce((a, b) => a + b, 0);

      /* R21: harmonised modern palette (green family first, then sky / amber /
         lavender / coral) — the all-green ramp read flat in the ring. */
      const colorPalette = [
        "#0D7751", "#2FA97B", "#57C7A0", "#1E5F8C", "#4B9BC9",
        "#D97706", "#E9A23B", "#8B5CF6", "#BE123C", "#647B70"
      ];
      /* R21v2: lighter gradient ends for the two-tone segment strokes */
      const lightPalette = [
        "#3BCB98", "#5AD9AC", "#8FE3C6", "#55A9DC", "#7FC2E6",
        "#F2B255", "#F7CD86", "#B79CF8", "#EC6A80", "#93A89D"
      ];

      const radius = 70;
      const cx = 95;
      const cy = 95;
      const circumference = 2 * Math.PI * radius;

      if (total === 0) {
        container.innerHTML = `
          <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 2rem; color: var(--text-muted); width: 100%;">
            <svg width="120" height="120" viewBox="0 0 190 190">
              <circle cx="${cx}" cy="${cy}" r="${radius}" fill="transparent" stroke="#e2e8f0" stroke-width="22"/>
            </svg>
            <span style="font-size: 0.85rem; margin-top: 0.5rem; font-weight: 600;">No clubs found for selected scope</span>
          </div>
        `;
        return;
      }

      // Sort items descending by value
      let sortedEntries = Object.entries(items).filter(([k, v]) => v > 0).sort((a, b) => b[1] - a[1]);
      if (sortedEntries.length === 0) {
        sortedEntries = Object.entries(items);
      }

      let accumulatedAngle = 0;
      let paths = "";
      let defs = "";
      let legendHtml = "";

      sortedEntries.forEach(([name, val], idx) => {
        const pct = total > 0 ? (val / total) : 0;
        const strokeDash = pct * circumference;
        const offset = -accumulatedAngle;
        accumulatedAngle += strokeDash;
        const color = colorPalette[idx % colorPalette.length];
        const lightColor = lightPalette[idx % lightPalette.length];
        /* R21: small segment gaps give the ring a modern segmented look */
        const segGap = 5;
        const dash = Math.max(strokeDash - segGap, 1);
        /* R21v2: two-tone gradient stroke per segment */
        defs += `
          <linearGradient id="dzg${idx}" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="${color}"/>
            <stop offset="100%" stop-color="${lightColor}"/>
          </linearGradient>`;

        paths += `
          <circle
            cx="${cx}"
            cy="${cy}"
            r="${radius}"
            fill="transparent"
            stroke="url(#dzg${idx})"
            stroke-width="26"
            stroke-dasharray="${dash} ${circumference - dash}"
            stroke-dashoffset="${offset}"
            style="transition: stroke-dasharray 0.5s ease, stroke-dashoffset 0.5s ease; cursor: default;"
            title="${name}: ${val} clubs (${Math.round(pct * 100)}%)"
          />
        `;

        legendHtml += `
          <div class="donut-legend-item">
            <div style="display: flex; align-items: center;">
              <span class="donut-legend-dot" style="background: ${color};"></span>
              <strong>${name}</strong>
            </div>
            <span><strong>${val}</strong> (${Math.round(pct * 100)}%)</span>
            <div class="legend-mini-bar"><span style="width: ${Math.round(pct * 100)}%; background: linear-gradient(90deg, ${color}, ${lightColor});"></span></div>
          </div>
        `;
      });

      container.innerHTML = `
        <div class="donut-svg-wrapper">
          <svg class="donut-svg" viewBox="0 0 190 190">
            <defs>${defs}</defs>
            <circle cx="${cx}" cy="${cy}" r="${radius}" fill="transparent" stroke="#EAF2ED" stroke-width="26" />
            ${paths}
          </svg>
          <div class="donut-center-text">
            <div class="donut-center-number">${total}</div>
            <div class="donut-center-label">${chartLabel}</div>
          </div>
        </div>
        <div class="donut-legend-col" style="max-height: 180px; overflow-y: auto;">
          ${legendHtml}
        </div>
      `;
    }

    // 3. Monthly Registration Trajectory Area Graph
    function renderTrajectoryAreaChart(monthWiseClubs) {
      const container = document.getElementById("trajectory-svg-container");
      if (!container) return;

      const entries = Object.entries(monthWiseClubs || {});
      if (entries.length === 0) {
        container.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 3rem;">No registration timeline data captured yet.</div>`;
        return;
      }

      const labels = entries.map(e => e[0]);
      const values = entries.map(e => e[1]);
      const maxVal = Math.max(...values, 1);

      const width = 500;
      const height = 180;
      /* R51: tight gutters -- no y-axis labels exist, so the old 40px left pad
         just misaligned the plot from the card title. The curve now starts at
         the card's content edge. */
      const padLeft = 14;
      const padRight = 14;
      const padTop = 20;
      const padBottom = 30;

      const plotW = width - padLeft - padRight;
      const plotH = height - padTop - padBottom;

      const pts = values.map((v, i) => {
        const x = padLeft + (i / Math.max(1, values.length - 1)) * plotW;
        const y = padTop + plotH - (v / maxVal) * plotH;
        return { x, y, val: v, label: labels[i] };
      });

      // Construct SVG curve path (R21v2: Catmull-Rom smoothing — modern flow)
      function smoothPath(points, tension) {
        if (points.length < 2) return points.length ? `M ${points[0].x},${points[0].y}` : "";
        let d = `M ${points[0].x},${points[0].y}`;
        for (let i = 0; i < points.length - 1; i++) {
          const p0 = points[Math.max(0, i - 1)], p1 = points[i], p2 = points[i + 1], p3 = points[Math.min(points.length - 1, i + 2)];
          const c1x = p1.x + (p2.x - p0.x) * tension, c1y = p1.y + (p2.y - p0.y) * tension;
          const c2x = p2.x - (p3.x - p1.x) * tension, c2y = p2.y - (p3.y - p1.y) * tension;
          d += ` C ${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`;
        }
        return d;
      }
      const dLine = smoothPath(pts, 0.2);
      const dArea = `${dLine} L ${pts[pts.length - 1].x},${padTop + plotH} L ${pts[0].x},${padTop + plotH} Z`;

      // Data dots and labels
      let dotsHtml = "";
      let labelsHtml = "";
      const labelStep = Math.max(1, Math.ceil(pts.length / 8));
      pts.forEach((p, i) => {
        dotsHtml += `
          <circle cx="${p.x}" cy="${p.y}" r="5.5" fill="#ffffff" stroke="#0D7751" stroke-width="3" style="cursor: default; filter: drop-shadow(0 2px 4px rgba(13, 119, 81, 0.35));">
            <title>${p.label}: ${p.val} clubs approved</title>
          </circle>
          <text x="${p.x}" y="${p.y - 11}" font-size="11" font-weight="700" fill="#103125" text-anchor="middle" stroke="#ffffff" stroke-width="3.5" paint-order="stroke">${p.val}</text>
        `;
        const shortLabel = p.label;
        /* R51: thin the axis labels so they never collide (dense month series
           cramped and truncated them). Dots + hover titles keep every point. */
        if (i % labelStep === 0 || i === pts.length - 1) {
          labelsHtml += `
            <text x="${p.x}" y="${height - 8}" font-size="10" font-weight="700" fill="#64748b" text-anchor="middle">${shortLabel}</text>
          `;
        }
      });

      container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" style="width: 100%; height: auto;">
          <defs>
            <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#0D7751" stop-opacity="0.45"/>
              <stop offset="100%" stop-color="#0D7751" stop-opacity="0.02"/>
            </linearGradient>
            <linearGradient id="trajLine" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="#0D7751"/>
              <stop offset="100%" stop-color="#57C7A0"/>
            </linearGradient>
          </defs>
          <!-- Soft dashed grid (R21v2) -->
          ${[0.25, 0.5, 0.75].map(f => `<line x1="${padLeft}" y1="${padTop + plotH * f}" x2="${width - padRight}" y2="${padTop + plotH * f}" stroke="#DCE9E2" stroke-width="1" stroke-dasharray="4 6"/>`).join("")}
          <line x1="${padLeft}" y1="${padTop + plotH}" x2="${width - padRight}" y2="${padTop + plotH}" stroke="#C9DED4" stroke-width="1.5"/>
          <!-- Gradient Area -->
          <path d="${dArea}" fill="url(#areaGradient)"/>
          <!-- Glow + Gradient Trajectory Line (R21v2) -->
          <path d="${dLine}" fill="none" stroke="url(#trajLine)" stroke-width="12" stroke-linecap="round" opacity="0.16"/>
          <path d="${dLine}" fill="none" stroke="url(#trajLine)" stroke-width="3.5" stroke-linecap="round"/>
          <!-- Data Points & Labels -->
          ${dotsHtml}
          ${labelsHtml}
        </svg>
      `;
    }

    // 4. Support Activity Types Breakdown
    function renderSupportBreakdown(supportTypeBreakdown) {
      const container = document.getElementById("support-split-grid");
      if (!container) return;

      const types = [
        { key: "Phone call and remote assistance", title: "Phone & Remote Assistance", icon: "📞", style: "primary" },
        { key: "Closing of OS Ticket", title: "OS Ticket Resolutions", icon: "🎫", style: "accent" },
        { key: "Online training", title: "Online Workshops / Webinars", icon: "💻", style: "info" },
        { key: "Offline training", title: "On-Premises / Offline Training", icon: "🏫", style: "warning" }
      ];

      const counts = supportTypeBreakdown || {};
      const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;

      container.innerHTML = types.map(t => {
        const count = counts[t.key] || 0;
        const pct = Math.round((count / total) * 100);

        return `
          <div class="support-type-tile ${t.style}">
            <div class="tile-icon">${t.icon}</div>
            <div class="tile-title">${t.title}</div>
            <div class="tile-value-row">
              <span class="tile-count">${count}</span>
              <span class="tile-pct">${pct}%</span>
            </div>
            <div class="bar-track" style="height: 6px;">
              <div class="bar-fill" style="width: ${pct}%;"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    // 5. Renewal Health Donut & Color Scale Gauge
    //    (R21: the flat pie became a segmented ring — same data, modern form.
    //     The name generateRenewalPieSvg is kept because tests lock it.)
    function generateRenewalPieSvg(active, expiring, overdue) {
      const slices = [
        { label: "Active Validity", value: active, color: "#17A273", light: "#5AD9AC" },
        { label: "Expiring Soon", value: expiring, color: "#E9A23B", light: "#F7CD86" },
        { label: "Overdue", value: overdue, color: "#BE123C", light: "#EC6A80" }
      ];
      const total = slices.reduce((sum, s) => sum + s.value, 0);
      const size = 150, cx = size / 2, cy = size / 2, r = 54, ring = 20;
      const circumference = 2 * Math.PI * r;

      const track = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="transparent" stroke="#EDF3F0" stroke-width="${ring}" />`;
      const centre = `
        <div style="position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); text-align:center; line-height:1.05;">
          <div style="font-size:1.55rem; font-weight:900; letter-spacing:-0.035em; color:var(--primary-dark); font-variant-numeric:tabular-nums;">${total}</div>
          <div style="font-size:0.62rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--text-muted); font-weight:800;">Clubs</div>
        </div>`;

      if (total === 0) {
        return `<div class="retention-pie-svg" style="position:relative; width:${size}px; height:${size}px;">
          <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${track}</svg>
          ${centre}
        </div>`;
      }

      let accumulated = 0;
      let rnwDefs = "";
      const segs = slices.filter(s => s.value > 0).map((s, i) => {
        const rawDash = (s.value / total) * circumference;
        const offset = -accumulated;
        accumulated += rawDash;
        const gap = 5;
        const dash = Math.max(rawDash - gap, 1);
        /* R21v2: two-tone gradient segment strokes */
        rnwDefs += `
          <linearGradient id="rnwGrad${i}" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="${s.color}"/>
            <stop offset="100%" stop-color="${s.light}"/>
          </linearGradient>`;
        return `
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="transparent" stroke="url(#rnwGrad${i})" stroke-width="${ring}"
            stroke-dasharray="${dash} ${circumference - dash}"
            stroke-dashoffset="${offset}"
            style="transition: stroke-dasharray 0.5s ease, stroke-dashoffset 0.5s ease;">
            <title>${s.label}: ${s.value} (${Math.round((s.value / total) * 100)}%)</title>
          </circle>`;
      }).join("");

      return `
        <div class="retention-pie-svg" style="position:relative; width:${size}px; height:${size}px;">
          <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="filter: drop-shadow(0 4px 10px rgba(16,49,37,0.12));">
            <defs>${rnwDefs}</defs>${track}${segs}
          </svg>
          ${centre}
        </div>`;
    }

    function renderRenewalHealthGauge(renewalHealth) {
      const container = document.getElementById("retention-gauge-container");
      if (!container) return;

      const rh = renewalHealth || {};
      const total = rh.total_clubs || 1;
      const active = rh.active_validity_count || 0;
      const expiring = rh.expiring_soon_count || 0;
      const overdue = rh.overdue_count || 0;

      const actPct = Math.round((active / total) * 100);
      const expPct = Math.round((expiring / total) * 100);
      const ovdPct = Math.round((overdue / total) * 100);

      const pieSvg = generateRenewalPieSvg(active, expiring, overdue);

      container.innerHTML = `
        <div style="display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap;">
          <!-- SVG Pie Chart Visualization -->
          <div style="flex-shrink: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 150px;">
            ${pieSvg}
            <span style="font-size: 0.72rem; color: var(--text-muted); margin-top: 0.45rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;">Status Distribution</span>
          </div>

          <!-- Color Scale Bar & Numerical Indicators -->
          <div style="flex: 1; min-width: 230px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.45rem;">
              <span style="font-size: 0.78rem; font-weight: 700; color: var(--primary);">Color Scale Spectrum</span>
              <span class="pill pill-primary" style="font-size: 0.72rem;">${active} / ${total} Active Validity</span>
            </div>

            <!-- Existing Color Scale Stacked Bar -->
            <div class="stacked-gauge-bar" style="margin-bottom: 0.75rem;">
              <div class="gauge-segment active" style="width: ${actPct}%;" title="Active Validity: ${active} clubs (${actPct}%)"></div>
              <div class="gauge-segment expiring" style="width: ${expPct}%;" title="Expiring Soon: ${expiring} clubs (${expPct}%)"></div>
              <div class="gauge-segment overdue" style="width: ${ovdPct}%;" title="Overdue: ${overdue} clubs (${ovdPct}%)"></div>
            </div>

            <!-- Existing Color Scale Legend Indicators -->
            <div class="retention-legend-row" style="margin-bottom: 0.85rem; font-size: 0.78rem;">
              <span style="font-weight: 600; color: var(--text-main);"><span style="display:inline-block; width:9px; height:9px; border-radius:50%; background:#17A273; margin-right:6px;"></span>Active: <strong>${active}</strong> (${actPct}%)</span>
              <span style="font-weight: 600; color: var(--text-main);"><span style="display:inline-block; width:9px; height:9px; border-radius:50%; background:#E9A23B; margin-right:6px;"></span>Expiring (&le;90d): <strong>${expiring}</strong> (${expPct}%)</span>
              <span style="font-weight: 600; color: var(--text-main);"><span style="display:inline-block; width:9px; height:9px; border-radius:50%; background:#BE123C; margin-right:6px;"></span>Overdue: <strong>${overdue}</strong> (${ovdPct}%)</span>
            </div>

            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; padding-top: 0.5rem; border-top: 1px dashed var(--border);">
              <span style="font-size: 0.82rem; color: var(--text-muted);">
                Retention Rate: <strong style="color: var(--primary-light); font-size: 1.05rem;">${rh.retention_rate_pct || 100}%</strong>
              </span>
              <button type="button" class="btn btn-outline btn-sm" onclick="openRenewalAttentionModal()" style="font-size: 0.78rem; border-color: #f59e0b; color: #b45309;">
                ⚡ Inspect Attention (${expiring + overdue}) &rarr;
              </button>
            </div>
          </div>
        </div>
      `;
    }

    // 6. Activity Distribution Matrix (R21v3 — replaced the plain volume bars:
    //    a contribution share ribbon (who owns what share of total activity) over
    //    heat-tinted matrix rows with clubs / support / share / recency columns.
    //    Relative distribution is now readable at a glance AND per-dimension.)
    // R29: "live + migrated" split note. The API already sent these halves
    // (live_* / legacy_* / migrated_* fields) — the views showed one blended
    // total. Wording matches the admin KPI cards: "X live + Y migrated".
    function splitNote(live, migrated) {
      const mig = parseInt(migrated || 0, 10) || 0;
      if (mig <= 0) return "";
      const lv = parseInt(live || 0, 10) || 0;
      return `<div style="font-size: 0.62rem; color: var(--text-muted); margin-top: 2px; white-space: nowrap;">${lv} live + ${mig} migrated</div>`;
    }
    function splitTitle(total, live, migrated, label) {
      const mig = parseInt(migrated || 0, 10) || 0;
      const lv = parseInt(live || 0, 10) || 0;
      return mig > 0 ? `${label}: ${total} (${lv} live + ${mig} migrated)` : `${label}: ${total}`;
    }

    function renderActivityMatrix(quotas) {
      const container = document.getElementById("activity-matrix-container");
      if (!container) return;
      if (!quotas || quotas.length === 0) {
        container.innerHTML = "<p style='color: var(--text-muted);'>No activity recorded yet.</p>";
        return;
      }

      const ZONE_CHIP = {
        "North":     { bg: "#E7F6EE", fg: "#0D7751" },
        "Central":   { bg: "#EFEAFB", fg: "#6D4FC4" },
        "West":      { bg: "#FDF2E3", fg: "#B45309" },
        "East":      { bg: "#E7F0FB", fg: "#1E5F8C" },
        "North East":{ bg: "#FDEBF0", fg: "#BE123C" },
        "South":     { bg: "#E2F7EE", fg: "#17A273" }
      };
      const RIBBON_SHADES = [
        "linear-gradient(135deg, #0B3B2A, #0D7751)",
        "linear-gradient(135deg, #0D7751, #2FA97B)",
        "linear-gradient(135deg, #2FA97B, #57C7A0)",
        "linear-gradient(135deg, #4B9BC9, #7FC2E6)",
        "linear-gradient(135deg, #8B5CF6, #B79CF8)",
        "linear-gradient(135deg, #D97706, #F2B255)",
        "linear-gradient(135deg, #647B70, #93A89D)"
      ];

      const rows = quotas.map(q => {
        const clubs = parseInt(q.clubs_approved_count || 0, 10) || 0;
        const support = parseInt(q.support_logs_count || 0, 10) || 0;
        let recency = null;
        if (q.last_activity_timestamp) {
          // ISO strings may carry microseconds — trim to milliseconds for Date.parse
          const iso = String(q.last_activity_timestamp).replace(/(\.\d{3})\d+/, "$1");
          const ts = Date.parse(iso);
          if (!isNaN(ts)) recency = Math.max(0, Math.floor((Date.now() - ts) / 86400000));
        }
        // R29: split the total into live work vs migrated history (the quota
        // rows carry the baseline in legacy_* columns).
        // R38: the live halves arrive computed from db/counting_rules.py
        // (live_clubs_count / live_support_count) — never subtract here.
        const migClubs = parseInt(q.legacy_clubs_count || 0, 10) || 0;
        const migSupport = parseInt(q.legacy_support_count || 0, 10) || 0;
        const liveClubs = parseInt(q.live_clubs_count || 0, 10) || 0;
        const liveSupport = parseInt(q.live_support_count || 0, 10) || 0;
        return {
          name: q.employee_name || q.emp_id,
          empId: q.emp_id,
          zone: q.zone || "",
          clubs, support,
          liveClubs, migClubs,
          liveSupport, migSupport,
          total: clubs + support,
          recency
        };
      });

      const grandTotal = rows.reduce((a, r) => a + r.total, 0) || 1;
      const maxClubs = Math.max(...rows.map(r => r.clubs), 1);
      const maxSupport = Math.max(...rows.map(r => r.support), 1);
      rows.sort((a, b) => b.total - a.total);

      /* 1. Contribution share ribbon — the at-a-glance picture */
      const ribbon = rows.map((r, i) => {
        const share = (r.total / grandTotal) * 100;
        const shade = RIBBON_SHADES[i % RIBBON_SHADES.length];
        const label = share >= 11
          ? `<span class="ribbon-label">${r.name.split(" ")[0]} ${Math.round(share)}%</span>` : "";
        return `<div class="ribbon-seg" style="flex: 0 0 ${share.toFixed(2)}%; background: ${shade};" title="${r.name}: ${r.total} activities (${share.toFixed(1)}% of total)">${label}</div>`;
      }).join("");

      /* 2. Heat-tinted matrix rows */
      const rowHtml = rows.map((r, i) => {
        const share = (r.total / grandTotal) * 100;
        const zone = ZONE_CHIP[r.zone] || { bg: "#EDF3F0", fg: "#647B70" };
        const clubPct = Math.round((r.clubs / maxClubs) * 100);
        const suppPct = Math.round((r.support / maxSupport) * 100);
        const clubAlpha = (0.06 + 0.22 * (r.clubs / maxClubs)).toFixed(2);
        const suppAlpha = (0.06 + 0.22 * (r.support / maxSupport)).toFixed(2);
        let recChip = `<span class="recency-chip recency-unknown">no data</span>`;
        if (r.recency !== null) {
          const d = r.recency;
          const cls = d <= 7 ? "recency-fresh" : (d <= 30 ? "recency-warm" : "recency-stale");
          const word = d === 0 ? "today" : d + "d ago";
          recChip = `<span class="recency-chip ${cls}">${word}</span>`;
        }
        return `
          <div class="activity-row">
            <div class="activity-officer">
              <span class="activity-rank">#${i + 1}</span>
              <span class="activity-name">${r.name} <span class="zone-chip" style="background:${zone.bg}; color:${zone.fg};">${r.zone}</span></span>
            </div>
            <div class="activity-cell" style="background: rgba(13, 119, 81, ${clubAlpha});" title="${splitTitle(r.clubs, r.liveClubs, r.migClubs, 'Clubs approved')}">
              <strong>${r.clubs}</strong>${splitNote(r.liveClubs, r.migClubs)}
              <div class="cell-mini-track"><div class="cell-mini-fill" style="width:${clubPct}%;"></div></div>
            </div>
            <div class="activity-cell" style="background: rgba(30, 95, 140, ${suppAlpha});" title="${splitTitle(r.support, r.liveSupport, r.migSupport, 'Support logs')}">
              <strong>${r.support}</strong>${splitNote(r.liveSupport, r.migSupport)}
              <div class="cell-mini-track"><div class="cell-mini-fill sky" style="width:${suppPct}%;"></div></div>
            </div>
            <div class="activity-share"><span class="share-pill">${share.toFixed(1)}%</span></div>
            <div class="activity-recency">${recChip}</div>
          </div>`;
      }).join("");

      container.innerHTML = `
        <div class="activity-ribbon-wrap">
          <div class="activity-ribbon">${ribbon}</div>
          <div class="activity-ribbon-caption">Share of total recorded activity (${grandTotal} actions) — darker = higher rank · hover a segment for detail</div>
        </div>
        <div class="activity-matrix">
          <div class="activity-row activity-head">
            <div>Nodal Officer</div><div>Clubs Approved</div><div>Support Logs</div><div>Share</div><div>Last Activity</div>
          </div>
          ${rowHtml}
        </div>
      `;
    }

    // 6B. Employee Performance Evaluation & Star Rating Matrix Loader
    async function loadEmployeePerformance() {
      const yearEl = document.getElementById("perf-filter-year");
      const monthEl = document.getElementById("perf-filter-month");
      const stateEl = document.getElementById("perf-filter-state");

      const year = yearEl ? yearEl.value : "ALL";
      const month = monthEl ? monthEl.value : "ALL";
      const state = stateEl ? stateEl.value : "ALL";

      const q = new URLSearchParams();
      if (year && year !== "ALL") q.append("year", year);
      if (month && month !== "ALL") q.append("month", month);
      if (state && state !== "ALL") q.append("state", state);

      const qs = q.toString();
      const endpoint = qs ? `/api/admin/employee-performance?${qs}` : "/api/admin/employee-performance";

      const tbody = document.getElementById("employee-performance-tbody");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">Evaluating performance metrics (${year !== 'ALL' ? year : 'All Years'}, ${month !== 'ALL' ? 'Month ' + month : 'All Months'}, ${state !== 'ALL' ? state : 'All States'})...</td></tr>`;
      }

      if (!IS_ADMIN_AUTHENTICATED) {
        if (tbody) {
          tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">🔒 Administrator sign-in required to view employee performance matrix.</td></tr>`;
        }
        return;
      }

      try {
        const adminToken = sessionStorage.getItem("ndli_admin_token");
        const res = await withSkeleton(tbody, apiRequest(endpoint, "GET", null, adminToken));
        if (res.ok && res.data && res.data.success) {
          // Populate available years dynamically if provided
          if (res.data.available_years && yearEl) {
            const curY = yearEl.value;
            const existingY = new Set(Array.from(yearEl.options).map(o => o.value));
            res.data.available_years.forEach(yr => {
              if (!existingY.has(yr)) {
                const opt = document.createElement("option");
                opt.value = yr;
                opt.textContent = yr;
                yearEl.appendChild(opt);
                existingY.add(yr);
              }
            });
            yearEl.value = curY;
          }

          // Populate available states dynamically if provided
          if (res.data.available_states && stateEl && stateEl.options.length <= 1) {
            const curS = stateEl.value;
            res.data.available_states.forEach(st => {
              const opt = document.createElement("option");
              opt.value = st;
              opt.textContent = st;
              stateEl.appendChild(opt);
            });
            stateEl.value = curS;
          }

          renderEmployeePerformanceTable(res.data.officers, state);
        } else {
          if (tbody) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 1.5rem; color: #ef4444;">Failed to load employee performance matrix: ${(res.data && res.data.message) || 'Unknown error'}</td></tr>`;
          }
        }
      } catch (err) {
        if (tbody) {
          tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 1.5rem; color: #ef4444;">Error evaluating performance: ${err.message}</td></tr>`;
        }
      }
    }

    function resetPerformanceFilters() {
      const yearEl = document.getElementById("perf-filter-year");
      const monthEl = document.getElementById("perf-filter-month");
      const stateEl = document.getElementById("perf-filter-state");
      if (yearEl) yearEl.value = "ALL";
      if (monthEl) monthEl.value = "ALL";
      if (stateEl) stateEl.value = "ALL";
      loadEmployeePerformance();
    }

    function renderEmployeePerformanceTable(officers, selectedState) {
      const tbody = document.getElementById("employee-performance-tbody");
      if (!tbody) return;
      tbody.innerHTML = "";

      if (!officers || officers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--text-muted);">No officers found matching the selected filters.</td></tr>`;
        return;
      }

      officers.forEach((off, idx) => {
        const tr = document.createElement("tr");
        tr.style.borderBottom = "1px solid #e2e8f0";

        let rankBadge = `<span style="font-weight: 700; color: var(--text-muted); font-size: 0.85rem;">#${off.rank || (idx + 1)}</span>`;
        if (off.rank === 1) rankBadge = `<span style="font-size: 1.15rem;" title="Rank 1 - Top Performer">🥇</span>`;
        else if (off.rank === 2) rankBadge = `<span style="font-size: 1.1rem;" title="Rank 2">🥈</span>`;
        else if (off.rank === 3) rankBadge = `<span style="font-size: 1.05rem;" title="Rank 3">🥉</span>`;

        const starsNum = off.stars || 1;
        const starDisplay = `
          <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1.1;">
            <span style="color: #eab308; font-size: 0.95rem; letter-spacing: 1px; text-shadow: 0 1px 2px rgba(0,0,0,0.1);">${off.stars_display || '★☆☆☆☆'}</span>
            <span style="font-size: 0.68rem; font-weight: 700; color: #475569; margin-top: 1px;">${off.rating_label || (starsNum + '.0 / 5.0')}</span>
          </div>
        `;

        const coversState = off.covers_selected_state !== undefined ? off.covers_selected_state : true;
        const stateHighlightStyle = (selectedState && selectedState !== "ALL" && coversState)
          ? "background: #f0fdf4; font-weight: 600;"
          : "";

        tr.innerHTML = `
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">${rankBadge}</td>
          <td style="padding: 0.5rem; vertical-align: middle; text-align: left;">
            <div style="font-weight: 700; color: var(--text); font-size: 0.84rem; line-height: 1.2;">${escapeHtml(off.full_name || off.emp_id)}</div>
            <div style="display: flex; gap: 0.3rem; align-items: center; margin-top: 2px;">
              <span class="badge-tag" style="background: var(--primary); color: #fff; font-size: 0.62rem; padding: 1px 5px;">${escapeHtml(off.emp_id)}</span>
              <span style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(off.zone || '')}</span>
            </div>
          </td>
          <td style="padding: 0.5rem; font-size: 0.75rem; color: #475569; vertical-align: middle; text-align: left; ${stateHighlightStyle}">
            <div style="overflow: hidden; text-overflow: ellipsis; white-space: normal; line-height: 1.2; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;" title="${escapeHtml(off.assigned_states || '')}">
              ${escapeHtml(off.assigned_states || 'All India')}
            </div>
            ${(selectedState && selectedState !== "ALL" && coversState) ? '<span style="display: inline-block; font-size: 0.65rem; color: #166534; margin-top: 1px;">✓ Selected State</span>' : ''}
          </td>
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">
            <span style="display: inline-block; font-size: 0.88rem; font-weight: 700; color: #166534; background: #dcfce7; padding: 2px 6px; border-radius: 10px;" title="${splitTitle(off.clubs_approved || 0, off.live_clubs_approved, off.migrated_clubs_approved, 'Club approvals')}">
              ${off.clubs_approved || 0}
            </span>${splitNote(off.live_clubs_approved, off.migrated_clubs_approved)}
          </td>
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">
            <span style="display: inline-block; font-size: 0.84rem; font-weight: 600; color: #6b21a8; background: #f3e8ff; padding: 2px 6px; border-radius: 10px;" title="${splitTitle(off.online_training || 0, off.live_online_training, off.migrated_online_workshops, 'Online training')}">
              ${off.online_training || 0}
            </span>${splitNote(off.live_online_training, off.migrated_online_workshops)}
          </td>
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">
            <span style="display: inline-block; font-size: 0.84rem; font-weight: 600; color: #c2410c; background: #ffedd5; padding: 2px 6px; border-radius: 10px;">
              ${off.offline_training || 0}
            </span>
          </td>
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">
            <span style="display: inline-block; font-size: 0.84rem; font-weight: 600; color: #0369a1; background: #e0f2fe; padding: 2px 6px; border-radius: 10px;" title="${splitTitle(off.other_supports || 0, off.live_other_supports, off.migrated_support, 'Phone Call & Remote + OS Ticket')}">
              ${off.other_supports || 0}
            </span>${splitNote(off.live_other_supports, off.migrated_support)}
          </td>
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">
            <span style="display: inline-block; font-size: 0.92rem; font-weight: 800; color: var(--primary); background: #ecfdf5; border: 1px solid #a7f3d0; padding: 2px 7px; border-radius: 12px;">
              ${(off.weighted_score !== undefined ? off.weighted_score.toFixed(2) : '0.00')}
            </span>
          </td>
          <td style="padding: 0.5rem 0.25rem; text-align: center; vertical-align: middle;">
            ${starDisplay}
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    // 7. Interactive State-Wise Table with Map Filter Binding
    // 7. National State-Wise Penetration & Density Roster
    function getPenetrationStatus(cnt) {
      if (cnt >= 4) return { text: "High Density", pillClass: "pill-primary" };
      if (cnt >= 2) return { text: "Moderate Density", pillClass: "pill-accent" };
      if (cnt === 1) return { text: "Initial Presence", pillClass: "pill-success" };
      return { text: "Deficit (0 clubs)", pillClass: "pill-danger" };
    }

    function filterTableByState(stateName) {
      CURRENT_TABLE_STATE_FILTER = stateName;
      const badge = document.getElementById("table-filter-badge");
      if (badge) {
        if (stateName) {
          badge.style.display = "inline-block";
          badge.innerText = `Filtered: ${stateName} (Click to reset)`;
          badge.onclick = () => filterTableByState(null);
          badge.style.cursor = "pointer";
        } else {
          badge.style.display = "none";
        }
      }

      if (GLOBAL_METRICS) {
        renderStateBreakdown(GLOBAL_METRICS.state_wise_clubs);
      }

      const tblCard = document.getElementById("state-breakdown-container");
      if (tblCard && stateName) {
        tblCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }

    function renderStateBreakdown(stateCounts) {
      const tbody = document.getElementById("state-breakdown-tbody");
      if (!tbody) return;
      tbody.innerHTML = "";

      const filterZ = document.getElementById("filter-zone") ? document.getElementById("filter-zone").value : "ALL";

      // Consolidate States to display
      let targetStates = [];
      if (filterZ !== "ALL" && CLIENT_ZONE_MAP[filterZ]) {
        targetStates = CLIENT_ZONE_MAP[filterZ];
      } else {
        const allStatesSet = new Set(Object.keys(CLIENT_ZONE_MAP).flatMap(z => CLIENT_ZONE_MAP[z]));
        for (const st of Object.keys(stateCounts || {})) { allStatesSet.add(st); }
        targetStates = Array.from(allStatesSet);
      }

      const sortedStates = targetStates.map(st => ({
        state: st,
        count: (stateCounts && stateCounts[st]) || 0,
        zone: clientGetZoneForState(st) || filterZ || "Unknown"
      })).sort((a, b) => b.count - a.count || a.state.localeCompare(b.state));

      const totalClubs = (GLOBAL_METRICS && GLOBAL_METRICS.summary && GLOBAL_METRICS.summary.total_clubs) || 0;
      const maxCount = Math.max(1, ...sortedStates.map(s => s.count));

      sortedStates.forEach(item => {
        const st = item.state;
        const cnt = item.count;
        const zone = item.zone;

        // Single State filter
        if (CURRENT_TABLE_STATE_FILTER && st.toLowerCase() !== CURRENT_TABLE_STATE_FILTER.toLowerCase()) return;

        const isFilteredState = CURRENT_TABLE_STATE_FILTER && st.toLowerCase() === CURRENT_TABLE_STATE_FILTER.toLowerCase();
        const tr = document.createElement("tr");
        if (isFilteredState) {
          tr.style.background = "#edfcf4";
          tr.style.borderLeft = "4px solid var(--primary-light)";
        }

        const pen = getPenetrationStatus(cnt);
        const pctOfMax = Math.round((cnt / maxCount) * 100);
        const sharePct = totalClubs > 0 ? ((cnt / totalClubs) * 100).toFixed(1) : "0.0";

        let densityMeterHtml = "";
        if (cnt > 0) {
          densityMeterHtml = `
            <div style="display: flex; align-items: center; gap: 0.5rem; width: 100%; max-width: 150px;">
              <div style="flex: 1; min-width: 35px; height: 8px; background: #e2e8f0; border-radius: 999px; overflow: hidden;">
                <div style="width: ${Math.max(12, pctOfMax)}%; height: 100%; background: linear-gradient(90deg, #10b981 0%, #0D7751 55%, #103125 100%); border-radius: 999px;"></div>
              </div>
              <span style="font-size: 0.76rem; font-weight: 700; color: var(--primary-dark); white-space: nowrap;">${sharePct}%</span>
            </div>
          `;
        } else {
          densityMeterHtml = `
            <div style="display: flex; align-items: center; gap: 0.5rem; width: 100%; max-width: 150px;">
              <div style="flex: 1; min-width: 35px; height: 8px; background: #fef2f2; border: 1px solid #fee2e2; border-radius: 999px;"></div>
              <span style="font-size: 0.74rem; color: var(--text-light); white-space: nowrap;">0.0%</span>
            </div>
          `;
        }

        tr.innerHTML = `
          <td style="padding: 0.55rem 0.75rem; font-size: 0.84rem;"><strong>${escapeHtml(st)}</strong></td>
          <td style="padding: 0.55rem 0.5rem; text-align: center;"><span class="pill pill-primary" style="font-size: 0.72rem; padding: 2px 8px;">${escapeHtml(zone)}</span></td>
          <td style="padding: 0.55rem 0.5rem; text-align: center;"><strong style="font-size: 0.95rem; color: var(--primary);">${cnt}</strong></td>
          <td style="padding: 0.55rem 0.75rem;">${densityMeterHtml}</td>
          <td style="padding: 0.55rem 0.75rem; text-align: center;"><span class="pill ${pen.pillClass}" style="font-size: 0.72rem; padding: 2px 8px;">${pen.text}</span></td>
        `;
        tbody.appendChild(tr);
      });
    }

    async function applyFilters() {
      await loadDashboardData();
    }

    // AI Decision Module
    async function loadAIDecisions() {
      const container = document.getElementById("ai-recommendations-list");
      if (!container) return;
      if (!IS_ADMIN_AUTHENTICATED) {
        container.innerHTML = "<p style='text-align: center; color: #cbd5e1; padding: 1.5rem;'>🔒 Administrator sign-in required to synthesize AI roadmap insights.</p>";
        return;
      }
      container.innerHTML = "<p style='text-align: center; color: #c7d2fe;'>Synthesizing AI roadmap insights...</p>";

      const adminToken = sessionStorage.getItem("ndli_admin_token");
      const res = await apiRequest("/api/admin/ai-insights", "GET", null, adminToken);
      if (res.ok && res.data) {
        const ai = res.data;
        document.getElementById("kpi-renewals").innerText = (ai.metrics.expiring_soon_count || 0) + (ai.metrics.overdue_count || 0);

        const recs = ai.strategic_recommendations || [];
        container.innerHTML = recs.map(r => `
          <div class="ai-rec-box">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
              <span class="pill ${r.priority === 'High' ? 'pill-danger' : 'pill-warning'}">${r.priority} Priority • ${r.category}</span>
              <span style="font-size: 0.75rem; color: #cbd5e1;">Target Action</span>
            </div>
            <h4 style="font-size: 1.05rem; font-weight: 700; color: #ffffff; margin-bottom: 0.25rem;">${r.title}</h4>
            <p style="font-size: 0.85rem; color: #e0e7ff; margin-bottom: 0.4rem;"><strong>Analysis:</strong> ${r.insight}</p>
            <p style="font-size: 0.85rem; color: #fde68a;"><strong>Recommended Policy:</strong> ${r.action}</p>
            ${r.category === 'Retention & Renewal' ? `
              <div style="margin-top: 0.65rem;">
                <button type="button" class="btn btn-accent btn-sm" onclick="openRenewalAttentionModal()" style="font-weight: 600;">
                  ⚡ View Attention Clubs (${(ai.metrics.expiring_soon_count || 0) + (ai.metrics.overdue_count || 0)}) &rarr;
                </button>
              </div>
            ` : ''}
          </div>
        `).join("");

        // Render deficit table
        const pTbody = document.getElementById("penetration-tbody");
        const unrep = ai.unrepresented_states || [];
        pTbody.innerHTML = `
          <tr>
            <td><span class="pill pill-danger">Zero Representation</span></td>
            <td><strong>${unrep.length}</strong> States/UTs</td>
            <td style="font-size: 0.85rem;">${unrep.slice(0, 10).join(", ")}${unrep.length > 10 ? ' ...' : ''}</td>
            <td style="font-size: 0.85rem;">Initiate Higher Education Directorate contact campaigns.</td>
          </tr>
          <tr style="cursor: pointer;" onclick="openRenewalAttentionModal('Overdue')" title="Click to view clubs past renewal validity">
            <td><span class="pill pill-danger">Renewal Risk</span></td>
            <td><strong>${ai.metrics.overdue_count || 0}</strong> Overdue <span style="font-size: 0.72rem; color: var(--danger); font-weight: 700;">↗ View</span></td>
            <td style="font-size: 0.85rem;">Clubs past renewal validity deadline</td>
            <td style="font-size: 0.85rem;">
              Trigger automated email reminders to Presidents & Secretaries.
              <button type="button" class="btn btn-outline btn-sm" style="margin-left: 0.5rem; padding: 2px 8px; font-size: 0.75rem;" onclick="event.stopPropagation(); openRenewalAttentionModal('Overdue')">Inspect Overdue</button>
            </td>
          </tr>
        `;
      }
    }

