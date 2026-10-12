    let GLOBAL_METRICS = null;
    let CURRENT_TABLE_STATE_FILTER = null;

    function renderUnauthenticatedKPIs(status = 401) {
      const alertContainer = document.getElementById("admin-alert");
      if (alertContainer && !document.getElementById("admin-auth-prompt-banner")) {
        const isEmployee = status === 403;
        alertContainer.innerHTML = `
          <div class="alert alert-warning" id="admin-auth-prompt-banner" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; padding: 1rem 1.25rem; margin-bottom: 1.25rem; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; box-shadow: var(--shadow-sm);">
            <div style="display: flex; align-items: center; gap: 0.85rem;">
              <span style="font-size: 1.8rem; line-height: 1;">🔐</span>
              <div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #92400e;">Administrator Authentication Required</div>
                <div style="font-size: 0.85rem; color: #b45309; margin-top: 2px;">
                  Master KPIs, national club totals, and zonal analytics require verified Central Administrator privileges.
                  ${isEmployee ? '<br><span style="color:#b91c1c; font-weight:600;">(Notice: You are currently logged in with an Employee account. Please sign in with Central Admin credentials.)</span>' : 'Please sign in with administrator credentials to reveal real-time database counts.'}
                </div>
              </div>
            </div>
            <button class="btn btn-amber" onclick="openAdminLoginModal()" style="font-weight: 700; white-space: nowrap; padding: 0.55rem 1.15rem; display: inline-flex; align-items: center; gap: 0.4rem; box-shadow: var(--shadow-sm); cursor: pointer;">
              <span>🔑</span> Admin Sign-In
            </button>
          </div>
        `;
      }
      const kpiClubs = document.getElementById("kpi-clubs");
      const kpiActs = document.getElementById("kpi-activities");
      if (kpiClubs && !IS_ADMIN_AUTHENTICATED) {
        kpiClubs.innerHTML = '<span style="font-size:1.6rem; color:#dc2626;" title="Admin sign-in required to view master clubs">🔒</span>';
      }
      if (kpiActs && !IS_ADMIN_AUTHENTICATED) {
        kpiActs.innerHTML = '<span style="font-size:1.6rem; color:#dc2626;" title="Admin sign-in required to view support logs">🔒</span>';
      }
    }

    async function loadDashboardData() {
      const zoneEl = document.getElementById("filter-zone");
      const yearEl = document.getElementById("filter-year");
      const zone = zoneEl ? zoneEl.value : "ALL";
      const year = yearEl ? yearEl.value : "ALL";

      const queryParams = new URLSearchParams();
      if (zone && zone !== "ALL") queryParams.append("zone", zone);
      if (year && year !== "ALL") queryParams.append("year", year);
      const qs = queryParams.toString();
      const endpoint = qs ? `/api/admin/metrics?${qs}` : "/api/admin/metrics";

      const adminToken = sessionStorage.getItem("ndli_admin_token");
      // UI/UX leftovers R33 — P3 skeleton first-paint: the big dashboard tables
      // used to flash empty then fill; they shimmer while the fetch is pending.
      const res = await withSkeleton(
        [document.getElementById("state-breakdown-tbody"), document.getElementById("penetration-tbody")],
        apiRequest(endpoint, "GET", null, adminToken));
      if (res.ok && res.data) {
        GLOBAL_METRICS = res.data;

        const banner = document.getElementById("admin-auth-prompt-banner");
        if (banner) banner.remove();

        // Dynamically sync available database years into dropdown
        if (res.data.available_years && Array.isArray(res.data.available_years)) {
          populateYearFilterOptions(res.data.available_years, year);
        }

        renderKPIs(res.data);
        renderStatisticalAnalytics(res.data);
        renderZoneDonutChart(res.data.zone_wise_clubs, res.data.state_wise_clubs);
        renderTrajectoryAreaChart(res.data.month_wise_clubs);
        renderSupportBreakdown(res.data.support_type_breakdown);
        renderRenewalHealthGauge(res.data.renewal_health);
        renderActivityMatrix(res.data.summary.quotas);
        renderStateBreakdown(res.data.state_wise_clubs);
      } else {
        renderUnauthenticatedKPIs(res.status || 401);
      }
      // Trigger live updates for automated backups and 30-day escalation reminders
      loadAdminBackupStatus();
      loadTrainingSlots();
      loadAdminEscalationReminders();
      loadEmployeePerformance();
    }

    function populateYearFilterOptions(years, currentSelected) {
      const select = document.getElementById("filter-year");
      if (!select) return;
      const existingVals = new Set(Array.from(select.options).map(o => o.value));
      years.forEach(yr => {
        if (!existingVals.has(yr)) {
          const opt = document.createElement("option");
          opt.value = yr;
          opt.textContent = `${yr}`;
          select.appendChild(opt);
          existingVals.add(yr);
        }
      });
      if (currentSelected && existingVals.has(currentSelected)) {
        select.value = currentSelected;
      }
    }

