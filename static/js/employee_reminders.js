    // =========================================================================
    // FEATURE 4: UNRESOLVED ISSUES, 72-HOUR REMINDERS & 7-DAY RECURRENT REMINDERS
    // =========================================================================
    let CURRENT_EMPLOYEE_REMINDERS = [];
    let SELECTED_EMPLOYEE_ISSUE_ID = null;
    let CURRENT_EMPLOYEE_REMINDERS_QUERY = "";

    async function loadEmployeeReminders() {
      try {
        const res = await apiRequest(`/api/issues/employee-reminders?emp_id=${encodeURIComponent(CURRENT_EMP_ID)}`);
        const container = document.getElementById("employee-reminders-container");
        if (!container) return;

        if (res.ok && res.data && res.data.reminders) {
          CURRENT_EMPLOYEE_REMINDERS = res.data.reminders;
          const count = CURRENT_EMPLOYEE_REMINDERS.length;

          if (count > 0) {
            container.innerHTML = `
              <div class="employee-reminders-kpi-stack" id="employee-reminders-kpi-card" role="button" tabindex="0" onclick="openEmployeeRemindersListModal()" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openEmployeeRemindersListModal();}" aria-label="Open due issue reminders list" style="background: linear-gradient(135deg, #fff5f5 0%, #fee2e2 100%); border: 2px solid #ef4444; border-left: 6px solid #dc2626; border-radius: var(--radius); padding: 0.9rem 1.25rem; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.08); margin-bottom: 1.25rem;" title="Click to open the unresolved issue reminders list">
                <div style="display: flex; align-items: center; gap: 0.85rem;">
                  <div style="background: #dc2626; color: #ffffff; width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.35rem; box-shadow: 0 2px 6px rgba(220, 38, 38, 0.3);">
                    ⏰
                  </div>
                  <div>
                    <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                      <strong style="color: #991b1b; font-size: 1.05rem;">Due Issue Reminders (72-Hour / 7-Day Alert)</strong>
                      <span style="background: #dc2626; color: #ffffff; font-size: 0.72rem; font-weight: 800; padding: 2px 8px; border-radius: 12px;">
                        ${count} ACTION REQUIRED
                      </span>
                    </div>
                    <p style="color: #b91c1c; font-size: 0.82rem; margin: 0.2rem 0 0 0;">
                      ${count} unresolved club issue reminder${count > 1 ? 's' : ''} awaiting review. Click this KPI card to open the issue list and update resolution status.
                    </p>
                  </div>
                </div>
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                  <div style="text-align: right;">
                    <div style="font-size: 1.45rem; font-weight: 800; color: #dc2626; line-height: 1;">${count}</div>
                    <div style="font-size: 0.7rem; color: #991b1b; font-weight: 700; text-transform: uppercase;">Due Reminders</div>
                  </div>
                  <button type="button" class="btn btn-sm btn-danger" tabindex="-1" aria-hidden="true" style="font-weight: 700; padding: 0.45rem 0.95rem; pointer-events: none; background: #dc2626; border-color: #dc2626; color: #ffffff;">
                    Open Issue List ↗
                  </button>
                </div>
              </div>
            `;
          } else {
            container.innerHTML = "";
          }

          // If list modal is active, update list view
          const listModal = document.getElementById("employee-reminders-list-modal");
          if (listModal && (listModal.classList.contains("active") || listModal.style.display === "flex")) {
            renderEmployeeRemindersList();
          }
        }
      } catch (err) {
        console.warn("Could not load employee reminders:", err);
      }
    }

    function openEmployeeRemindersListModal() {
      const modal = document.getElementById("employee-reminders-list-modal");
      if (modal) {
        modal.style.display = "flex";
        modal.classList.add("active");
        modal.classList.add("open");
        ndliModalOpened(modal);
      }
      const searchInput = document.getElementById("employee-reminders-search-input");
      if (searchInput) searchInput.value = "";
      CURRENT_EMPLOYEE_REMINDERS_QUERY = "";
      renderEmployeeRemindersList();
    }

    function closeEmployeeRemindersListModal() {
      const modal = document.getElementById("employee-reminders-list-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        modal.classList.remove("open");
        ndliModalClosed(modal);
      }
    }

    function handleEmployeeRemindersSearch(q) {
      CURRENT_EMPLOYEE_REMINDERS_QUERY = (q || "").trim().toLowerCase();
      renderEmployeeRemindersList();
    }

    function renderEmployeeRemindersList() {
      const tbody = document.getElementById("employee-reminders-tbody");
      const countEl = document.getElementById("employee-reminders-modal-count");
      if (!tbody) return;

      const total = CURRENT_EMPLOYEE_REMINDERS.length;
      if (countEl) countEl.innerText = `${total} Due Reminders`;

      let filtered = CURRENT_EMPLOYEE_REMINDERS;
      if (CURRENT_EMPLOYEE_REMINDERS_QUERY) {
        const q = CURRENT_EMPLOYEE_REMINDERS_QUERY;
        filtered = filtered.filter(i =>
          (i.club_id || "").toLowerCase().includes(q) ||
          (i.institution_name || "").toLowerCase().includes(q) ||
          (i.state || "").toLowerCase().includes(q) ||
          (i.zone || "").toLowerCase().includes(q) ||
          (i.issue_note || "").toLowerCase().includes(q)
        );
      }

      if (filtered.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 3rem;">
              <div style="font-size: 2rem; margin-bottom: 0.5rem;">🎉</div>
              <strong>${CURRENT_EMPLOYEE_REMINDERS_QUERY ? 'No due reminders match your search.' : 'No due reminders pending for your operational jurisdiction.'}</strong>
              <div style="font-size: 0.85rem; margin-top: 0.35rem; color: var(--text-muted);">
                ${CURRENT_EMPLOYEE_REMINDERS_QUERY ? 'Try clearing or changing your search terms.' : 'All reported issues have been resolved or are within their scheduled intervals.'}
              </div>
            </td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = filtered.map(issue => {
        const idSafe = escapeHtml(issue.issue_id);
        const reportedDate = new Date(issue.created_at).toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
          year: "numeric"
        });
        return `
          <tr style="cursor: pointer; transition: background 0.12s;" onclick="selectEmployeeReminder('${idSafe}')">
            <td><code style="font-weight: 700; color: #b91c1c;">${escapeHtml(issue.club_id)}</code></td>
            <td><strong>${escapeHtml(issue.institution_name)}</strong></td>
            <td>${escapeHtml(issue.state)} <span class="pill pill-primary" style="font-size: 0.72rem;">${escapeHtml(issue.zone || '')}</span></td>
            <td style="font-size: 0.85rem; color: var(--text-muted);">${reportedDate}</td>
            <td style="max-width: 320px; font-size: 0.85rem; color: #334155; line-height: 1.35;">${escapeHtml(issue.issue_note)}</td>
            <td>
              <button type="button" class="btn btn-sm btn-danger" onclick="event.stopPropagation(); selectEmployeeReminder('${idSafe}')" style="font-weight: 700; padding: 3px 10px; font-size: 0.78rem; background: #dc2626; border-color: #dc2626; color: #ffffff;">
                Review & Decide ↗
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }

    function selectEmployeeReminder(issueId) {
      closeEmployeeRemindersListModal();
      openEmployeeIssueResolutionModal(issueId);
    }

    async function openEmployeeIssueResolutionModal(issueId) {
      SELECTED_EMPLOYEE_ISSUE_ID = issueId;
      let issue = CURRENT_EMPLOYEE_REMINDERS.find(i => i.issue_id === issueId);
      const contentEl = document.getElementById("employee-issue-details-content");
      if (!contentEl) return;

      const renderDetails = (data) => {
        contentEl.innerHTML = `
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 0.75rem;">
            <div><strong>Club ID:</strong> <span style="font-family: monospace; color: var(--primary);">${escapeHtml(data.club_id)}</span></div>
            <div><strong>Institution:</strong> ${escapeHtml(data.institution_name)}</div>
            <div><strong>State / Zone:</strong> ${escapeHtml(data.state)} (${escapeHtml(data.zone || '')})</div>
            <div><strong>Reported Date:</strong> ${new Date(data.created_at).toLocaleString()}</div>
          </div>
          <div style="background: #fef9c3; border-left: 3px solid #ca8a04; padding: 0.65rem 0.85rem; border-radius: 4px;">
            <strong style="color: #854d0e; font-size: 0.82rem; display: block; margin-bottom: 0.2rem;">Brief Note of Reported Issue:</strong>
            <p style="color: #713f12; font-size: 0.85rem; margin: 0; line-height: 1.4;">${escapeHtml(data.issue_note)}</p>
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

      const notesEl = document.getElementById("employee-issue-notes-input");
      if (notesEl) notesEl.value = "";

      const modal = document.getElementById("employee-issue-modal");
      if (modal) {
        modal.style.display = "flex";
        modal.classList.add("active");
        ndliModalOpened(modal);
      }
    }

    function closeEmployeeIssueModal() {
      SELECTED_EMPLOYEE_ISSUE_ID = null;
      const modal = document.getElementById("employee-issue-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        ndliModalClosed(modal);
      }
    }

    async function submitEmployeeIssueResolution(statusChoice) {
      if (!SELECTED_EMPLOYEE_ISSUE_ID) return;
      const issueId = SELECTED_EMPLOYEE_ISSUE_ID;
      const notesEl = document.getElementById("employee-issue-notes-input");
      const resolutionNotes = notesEl ? notesEl.value.trim() : "";

      try {
        const payload = {
          issue_id: SELECTED_EMPLOYEE_ISSUE_ID,
          status: statusChoice,
          resolved_by: CURRENT_EMP_ID,
          role: "EMPLOYEE",
          resolution_notes: resolutionNotes
        };
        const res = await apiRequest("/api/issues/resolve", "POST", payload);
        if (res.ok && res.data && res.data.success) {
          closeEmployeeIssueModal();
          if (statusChoice === "Resolved") {
            showAlert("global-alert", `✓ Success: Issue ${issueId} has been marked as Resolved.`, "success");
          } else {
            showAlert("global-alert", `⚠ Issue marked as Not Resolved: System has automatically scheduled the next reminder in 7 days.`, "warning");
          }
          loadEmployeeReminders();
        } else {
          UI.toast("Error: " + (res.data?.message || "Failed to update issue status."), { type: "danger" });
        }
      } catch (e) {
        UI.toast("Network error updating issue status: " + e.message, { type: "danger" });
      }
    }

    async function handleSetClubIssueReminder() {
      const clubId = document.getElementById("edit-club-id")?.value;
      const noteEl = document.getElementById("issue-note-input");
      const issueNote = noteEl ? noteEl.value.trim() : "";

      if (!clubId) {
        showAlert("modal-alert", "Please select a valid club first.", "danger");
        return;
      }
      if (!issueNote) {
        showAlert("modal-alert", "Please enter a brief note of the reported issue before setting a reminder.", "danger");
        if (noteEl) noteEl.focus();
        return;
      }

      try {
        const payload = {
          club_id: clubId,
          emp_id: CURRENT_EMP_ID,
          issue_note: issueNote
        };
        const res = await apiRequest("/api/issues/create", "POST", payload);
        if (res.ok && res.data && res.data.success) {
          showAlert("global-alert", `✓ Unresolved issue logged for ${clubId}! Reminder scheduled to appear in your dashboard after 72 hours.`, "success");
          if (noteEl) noteEl.value = "";
          closeEditModal();
          loadEmployeeReminders();
        } else {
          showAlert("modal-alert", "Failed to set reminder: " + (res.data?.message || "Unknown error"), "danger");
        }
      } catch (e) {
        showAlert("modal-alert", "Error logging issue: " + e.message, "danger");
      }
    }

