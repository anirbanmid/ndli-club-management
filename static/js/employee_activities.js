    let ALL_ACTIVITIES_CACHE = null;
    let LAST_ACTIVITIES_FETCH_TIME = 0;
    let IS_ACTIVITIES_FETCHING = false;
    let SELECTED_ACTIVITY_IDS = new Set();
    let ACTIVITY_DELETE_PENDING_IDS = [];
    let ACTIVITY_DELETE_CAPTCHA_CODE = "";

    function updateBulkDeleteButtonState() {
      const btn = document.getElementById("btn-bulk-delete-activities");
      if (!btn) return;
      const n = SELECTED_ACTIVITY_IDS.size;
      btn.innerText = `🗑 Delete Selected (${n})`;
      btn.disabled = n === 0;
      btn.title = n === 0 ? "Select one or more entries below to enable bulk delete" : `Delete ${n} selected entr${n === 1 ? 'y' : 'ies'}`;
      btn.onclick = n === 0 ? null : () => openActivityDeleteSecurityModal(null);
    }

    function toggleActivitySelection(activityId, checked) {
      if (checked) {
        SELECTED_ACTIVITY_IDS.add(activityId);
      } else {
        SELECTED_ACTIVITY_IDS.delete(activityId);
      }
      updateBulkDeleteButtonState();
      const selectAll = document.getElementById("activity-select-all");
      if (selectAll) {
        const totalCheckboxes = document.querySelectorAll(".activity-row-checkbox").length;
        selectAll.checked = totalCheckboxes > 0 && SELECTED_ACTIVITY_IDS.size === totalCheckboxes;
      }
    }

    function toggleAllActivitySelection(checked) {
      SELECTED_ACTIVITY_IDS.clear();
      document.querySelectorAll(".activity-row-checkbox").forEach(cb => {
        cb.checked = checked;
        if (checked) SELECTED_ACTIVITY_IDS.add(cb.dataset.activityId);
      });
      updateBulkDeleteButtonState();
    }

    function renderActivitiesTable(acts) {
      const tbody = document.getElementById("activities-tbody");
      if (!tbody) return;
      SELECTED_ACTIVITY_IDS.clear();
      updateBulkDeleteButtonState();
      const selectAll = document.getElementById("activity-select-all");
      if (selectAll) selectAll.checked = false;

      if (!acts || acts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No activity logs recorded yet.</td></tr>';
        return;
      }
      tbody.innerHTML = acts.map(a => {
        const timeDisplay = typeof formatLocalTimestamp === "function" ? formatLocalTimestamp(a.timestamp) : (a.timestamp || "-");
        const actId = typeof escapeHtml === "function" ? escapeHtml(a.activity_id) : (a.activity_id || "");
        const suppType = typeof escapeHtml === "function" ? escapeHtml(a.support_type) : (a.support_type || "");
        const priorityBadge = a.priority_flag === '1' ? '<span class="pill pill-priority">★ Priority</span>' : '<span class="pill pill-primary">Standard</span>';
        const clubRef = a.club_id ? `<code>${typeof escapeHtml === "function" ? escapeHtml(a.club_id) : a.club_id}</code>` : '-';
        const notes = typeof escapeHtml === "function" ? escapeHtml(a.notes || '-') : (a.notes || '-');
        const rawActId = a.activity_id || "";

        return `
          <tr>
            <td><input type="checkbox" class="activity-row-checkbox" data-activity-id="${rawActId.replace(/"/g, '&quot;')}" onchange="toggleActivitySelection('${rawActId.replace(/'/g, "\\'")}', this.checked)"></td>
            <td style="font-family: monospace; font-size: 0.8rem;">${timeDisplay}</td>
            <td><code>${actId}</code></td>
            <td><strong>${suppType}</strong></td>
            <td>${priorityBadge}</td>
            <td>${clubRef}</td>
            <td style="font-size: 0.85rem;">${notes}</td>
            <td><button class="btn btn-outline btn-sm" style="color: #b91c1c; border-color: #fecaca; padding: 0.2rem 0.5rem;" title="Delete this activity log entry" onclick="openActivityDeleteSecurityModal('${rawActId.replace(/'/g, "\\'")}')">🗑</button></td>
          </tr>
        `;
      }).join("");
    }

    function onHistoryTabActivated() {
      if (ALL_ACTIVITIES_CACHE && ALL_ACTIVITIES_CACHE.length > 0) {
        // Instant 0ms cached render!
        renderActivitiesTable(ALL_ACTIVITIES_CACHE);
        if (Date.now() - LAST_ACTIVITIES_FETCH_TIME > 45000) {
          loadEmployeeActivities(false);
        }
      } else {
        loadEmployeeActivities(false);
      }
    }

    async function loadEmployeeActivities(forceRefresh = false) {
      const tbody = document.getElementById("activities-tbody");

      if (forceRefresh) {
        ALL_ACTIVITIES_CACHE = null;
      }

      // Fast-path: Instant render from cache if available
      if (ALL_ACTIVITIES_CACHE && ALL_ACTIVITIES_CACHE.length > 0 && !forceRefresh) {
        renderActivitiesTable(ALL_ACTIVITIES_CACHE);
        if (Date.now() - LAST_ACTIVITIES_FETCH_TIME < 45000) {
          return;
        }
      }

      if (IS_ACTIVITIES_FETCHING) {
        return;
      }

      // Show animated spinner only if table currently has no cached rows displayed
      if (tbody && (!ALL_ACTIVITIES_CACHE || ALL_ACTIVITIES_CACHE.length === 0)) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--primary); padding: 2rem;"><span style="display: inline-block; animation: spin 1s linear infinite; margin-right: 0.5rem;">⏳</span> Loading activity history...</td></tr>';
      }

      IS_ACTIVITIES_FETCHING = true;
      try {
        const res = await apiRequest(`/api/activity/list?emp_id=${encodeURIComponent(CURRENT_EMP_ID)}`);
        const data = (res && res.data) || {};
        const acts = data.activities || [];

        if (res.ok) {
          ALL_ACTIVITIES_CACHE = acts;
          LAST_ACTIVITIES_FETCH_TIME = Date.now();
          renderActivitiesTable(acts);
          const currentClubsCount = parseInt(document.getElementById("quota-clubs-count")?.innerText || "0", 10);
          if (currentClubsCount === 0) {
            loadEmployeeQuota();
          }
        } else {
          if (tbody && (!ALL_ACTIVITIES_CACHE || ALL_ACTIVITIES_CACHE.length === 0)) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #dc2626; padding: 1.5rem;"><span>⚠️ Unable to load activity logs.</span> <button class="btn btn-outline btn-sm" style="margin-left: 0.75rem;" onclick="loadEmployeeActivities(true)">↻ Retry</button></td></tr>';
          }
        }
      } catch (err) {
        if (tbody && (!ALL_ACTIVITIES_CACHE || ALL_ACTIVITIES_CACHE.length === 0)) {
          tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #dc2626; padding: 1.5rem;"><span>⚠️ Connection error while loading activity logs.</span> <button class="btn btn-outline btn-sm" style="margin-left: 0.75rem;" onclick="loadEmployeeActivities(true)">↻ Retry</button></td></tr>';
        }
      } finally {
        IS_ACTIVITIES_FETCHING = false;
      }
    }

