    // =========================================================================
    // FEATURE 5: 30+ DAYS UNRESOLVED ISSUES ADMIN ESCALATION & REMINDERS
    // =========================================================================
    let CURRENT_ADMIN_REMINDERS = [];
    let SELECTED_ADMIN_ISSUE_ID = null;
    let CURRENT_ADMIN_ESCALATIONS_QUERY = "";

    async function loadAdminEscalationReminders() {
      if (!IS_ADMIN_AUTHENTICATED) return;
      try {
        const adminToken = sessionStorage.getItem("ndli_admin_token");
        const res = await apiRequest("/api/issues/admin-reminders", "GET", null, adminToken);
        const container = document.getElementById("admin-issues-escalation-container");
        const kpiVal = document.getElementById("kpi-admin-escalations");
        const kpiDesc = document.getElementById("kpi-admin-escalations-desc");
        const cardEl = document.getElementById("card-admin-escalations");

        if (res.ok && res.data && res.data.reminders) {
          CURRENT_ADMIN_REMINDERS = res.data.reminders;
          const count = CURRENT_ADMIN_REMINDERS.length;

          if (kpiVal) kpiVal.innerText = count;
          if (kpiDesc) kpiDesc.innerText = count > 0 ? `${count} critical unresolved (Click to inspect)` : "0 pending (All clear)";

          if (cardEl) {
            if (count > 0) {
              cardEl.style.boxShadow = "0 0 0 2px #ef4444, 0 4px 12px rgba(239, 68, 68, 0.18)";
            } else {
              cardEl.style.boxShadow = "";
            }
          }

          if (container) {
            if (count > 0) {
              container.innerHTML = `
                <div class="escalation-kpi-stack" id="admin-escalations-kpi-card" role="button" tabindex="0" onclick="openAdminEscalationsListModal()" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openAdminEscalationsListModal();}" style="background: linear-gradient(135deg, #fff5f5 0%, #fee2e2 100%); border: 2px solid #ef4444; border-left: 6px solid #dc2626; border-radius: var(--radius); padding: 0.9rem 1.25rem; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.08);" title="Click to open the 30-day escalated issues list" aria-label="Open the 30-day escalated issues list">
                  <div style="display: flex; align-items: center; gap: 0.85rem;">
                    <div style="background: #dc2626; color: #ffffff; width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.35rem; box-shadow: 0 2px 6px rgba(220, 38, 38, 0.3);">
                      🚨
                    </div>
                    <div>
                      <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                        <strong style="color: #991b1b; font-size: 1.05rem;">30-Day Unresolved Issue Escalations</strong>
                        <span style="background: #dc2626; color: #ffffff; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 12px;">
                          ${count} CRITICAL ESCALATED
                        </span>
                      </div>
                      <p style="color: #b91c1c; font-size: 0.82rem; margin: 0.2rem 0 0 0;">
                        ${count} regional club issue${count > 1 ? 's' : ''} unresolved for 30+ days. Click this KPI card to open the escalated issues list.
                      </p>
                    </div>
                  </div>
                  <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <div style="text-align: right;">
                      <div style="font-size: 1.45rem; font-weight: 800; color: #dc2626; line-height: 1;">${count}</div>
                      <div style="font-size: 0.7rem; color: #991b1b; font-weight: 700; text-transform: uppercase;">Escalations</div>
                    </div>
                    <button type="button" class="btn btn-sm btn-danger" onclick="event.stopPropagation(); openAdminEscalationsListModal()" style="font-weight: 700; padding: 0.45rem 0.95rem;">
                      Open Escalations List ↗
                    </button>
                  </div>
                </div>
              `;
            } else {
              container.innerHTML = "";
            }
          }

          // If list modal is active, update list view
          const listModal = document.getElementById("admin-escalations-list-modal");
          if (listModal && (listModal.classList.contains("active") || listModal.style.display === "flex")) {
            renderAdminEscalationsList();
          }
        }
      } catch (err) {
        console.warn("Could not load admin escalation reminders:", err);
      }
    }

    function openAdminEscalationsListModal() {
      const modal = document.getElementById("admin-escalations-list-modal");
      if (modal) {
        modal.style.display = "flex";
        modal.classList.add("active");
        modal.classList.add("open");
        ndliModalOpened(modal);
      }
      const searchInput = document.getElementById("admin-escalations-search-input");
      if (searchInput) searchInput.value = "";
      CURRENT_ADMIN_ESCALATIONS_QUERY = "";
      renderAdminEscalationsList();
    }

    function closeAdminEscalationsListModal() {
      const modal = document.getElementById("admin-escalations-list-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        modal.classList.remove("open");
        ndliModalClosed(modal);
      }
    }

    function handleAdminEscalationsSearch(q) {
      CURRENT_ADMIN_ESCALATIONS_QUERY = (q || "").trim().toLowerCase();
      renderAdminEscalationsList();
    }

    function renderAdminEscalationsList() {
      const tbody = document.getElementById("admin-escalations-tbody");
      const countEl = document.getElementById("admin-escalations-modal-count");
      if (!tbody) return;

      const total = CURRENT_ADMIN_REMINDERS.length;
      if (countEl) countEl.innerText = `${total} Escalated`;

      let filtered = CURRENT_ADMIN_REMINDERS;
      if (CURRENT_ADMIN_ESCALATIONS_QUERY) {
        const q = CURRENT_ADMIN_ESCALATIONS_QUERY;
        filtered = filtered.filter(i =>
          (i.club_id || "").toLowerCase().includes(q) ||
          (i.institution_name || "").toLowerCase().includes(q) ||
          (i.state || "").toLowerCase().includes(q) ||
          (i.zone || "").toLowerCase().includes(q) ||
          (i.emp_id || "").toLowerCase().includes(q) ||
          (i.issue_note || "").toLowerCase().includes(q)
        );
      }

      if (filtered.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem;">
              <div style="font-size: 2rem; margin-bottom: 0.5rem;">🎉</div>
              <strong>${CURRENT_ADMIN_ESCALATIONS_QUERY ? 'No escalated issues match your search.' : 'No 30-day escalated issues pending.'}</strong>
              <div style="font-size: 0.85rem; margin-top: 0.35rem; color: var(--text-muted);">
                ${CURRENT_ADMIN_ESCALATIONS_QUERY ? 'Try clearing or changing your search terms.' : 'All regional club issues have been resolved or are within their 30-day timeline.'}
              </div>
            </td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = filtered.map(issue => {
        const days = issue.days_unresolved !== undefined ? issue.days_unresolved : 30;
        const idSafe = escapeHtml(issue.issue_id);
        return `
          <tr style="cursor: pointer; transition: background 0.12s;" onclick="selectAdminEscalatedIssue('${idSafe}')">
            <td><code style="font-weight: 700; color: #b91c1c;">${escapeHtml(issue.club_id)}</code></td>
            <td><strong>${escapeHtml(issue.institution_name)}</strong></td>
            <td>${escapeHtml(issue.state)} <span class="pill pill-primary" style="font-size: 0.72rem;">${escapeHtml(issue.zone)}</span></td>
            <td><span class="pill pill-outline" style="font-weight: 700;">${escapeHtml(issue.emp_id)}</span></td>
            <td><span class="pill pill-danger" style="font-weight: 800;">🔴 ${days} Days</span></td>
            <td style="max-width: 320px; font-size: 0.85rem; color: #334155; line-height: 1.35;">${escapeHtml(issue.issue_note)}</td>
            <td>
              <button type="button" class="btn btn-sm btn-danger" onclick="event.stopPropagation(); selectAdminEscalatedIssue('${idSafe}')" style="font-weight: 700; padding: 3px 10px; font-size: 0.78rem;">
                Review & Decide ↗
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }

    function selectAdminEscalatedIssue(issueId) {
      closeAdminEscalationsListModal();
      openAdminIssueResolutionModal(issueId);
    }

    async function openAdminIssueResolutionModal(issueId) {
      SELECTED_ADMIN_ISSUE_ID = issueId;
      let issue = CURRENT_ADMIN_REMINDERS.find(i => i.issue_id === issueId);
      const contentEl = document.getElementById("admin-issue-details-content");
      if (!contentEl) return;

      const renderDetails = (data) => {
        const days = data.days_unresolved !== undefined ? data.days_unresolved : 30;
        contentEl.innerHTML = `
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 0.75rem;">
            <div><strong>Club ID:</strong> <span style="font-family: monospace; color: var(--primary);">${escapeHtml(data.club_id)}</span></div>
            <div><strong>Institution:</strong> ${escapeHtml(data.institution_name)}</div>
            <div><strong>Assigned Employee:</strong> ${escapeHtml(data.emp_id)} (${escapeHtml(data.zone)} Zone)</div>
            <div><strong>State:</strong> ${escapeHtml(data.state)}</div>
            <div><strong>Reported Timestamp:</strong> ${new Date(data.created_at).toLocaleString()}</div>
            <div><strong>Unresolved Duration:</strong> <span style="color: #dc2626; font-weight: 700;">${days} Days</span></div>
          </div>
          <div style="background: #fee2e2; border-left: 3px solid #dc2626; padding: 0.65rem 0.85rem; border-radius: 4px;">
            <strong style="color: #991b1b; font-size: 0.82rem; display: block; margin-bottom: 0.2rem;">Brief Note of Reported Issue:</strong>
            <p style="color: #7f1d1d; font-size: 0.85rem; margin: 0; line-height: 1.4;">${escapeHtml(data.issue_note)}</p>
          </div>
        `;
      };

      if (issue) {
        renderDetails(issue);
      } else {
        contentEl.innerHTML = `<p style="color: var(--text-muted); font-size: 0.85rem;">Loading issue details from database...</p>`;
        try {
          const fetchRes = await apiRequest(`/api/issues/details?issue_id=${encodeURIComponent(issueId)}`);
          if (fetchRes.ok && fetchRes.data && fetchRes.data.issue) {
            issue = fetchRes.data.issue;
            renderDetails(issue);
          } else {
            contentEl.innerHTML = `<p style="color: #dc2626;">Unable to load issue details.</p>`;
          }
        } catch (e) {
          contentEl.innerHTML = `<p style="color: #dc2626;">Network error loading issue details.</p>`;
        }
      }

      const notesEl = document.getElementById("admin-issue-resolution-notes");
      if (notesEl) notesEl.value = "";

      const modal = document.getElementById("admin-issue-resolution-modal");
      if (modal) {
        modal.style.display = "flex";
        modal.classList.add("active");
        ndliModalOpened(modal);
      }
    }

    function closeAdminIssueModal() {
      SELECTED_ADMIN_ISSUE_ID = null;
      const modal = document.getElementById("admin-issue-resolution-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        ndliModalClosed(modal);
      }
    }

    async function submitAdminIssueResolution(statusChoice) {
      if (!SELECTED_ADMIN_ISSUE_ID) return;
      const notesEl = document.getElementById("admin-issue-resolution-notes");
      const resolutionNotes = notesEl ? notesEl.value.trim() : "";
      const adminEmail = sessionStorage.getItem("ndli_admin_email") || "admin@iitkgp.ac.in";

      try {
        const payload = {
          issue_id: SELECTED_ADMIN_ISSUE_ID,
          status: statusChoice,
          resolved_by: adminEmail,
          role: "ADMIN",
          resolution_notes: resolutionNotes
        };
        const res = await apiRequest("/api/issues/resolve", "POST", payload);
        if (res.ok && res.data && res.data.success) {
          closeAdminIssueModal();
          if (statusChoice === "Resolved") {
            showAlert("admin-alert", `✓ Success: Issue ${SELECTED_ADMIN_ISSUE_ID} has been marked as Resolved.`, "success");
          } else {
            showAlert("admin-alert", `⚠ Issue kept as Not Resolved: Next reminder automatically scheduled in 7 days.`, "warning");
          }
          loadAdminEscalationReminders();
          loadDashboardData();
        } else {
          showAlert("admin-alert", "Error: " + (res.data?.message || "Failed to update issue status."), "danger");
        }
      } catch (e) {
        showAlert("admin-alert", "Network error updating issue status: " + e.message, "danger");
      }
    }

