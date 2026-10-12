    // =============================================================
    // EMPLOYEE MANAGEMENT ROSTER, MODAL EDIT & ACTIONS
    // =============================================================
    async function loadEmployeesRoster() {
      const tbody = document.getElementById("employee-roster-tbody");
      if (!IS_ADMIN_AUTHENTICATED) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--danger); padding: 2rem;">🔒 Authentication required. Unlock above to view employee roster.</td></tr>';
        return;
      }

      const adminToken = sessionStorage.getItem("ndli_admin_token");
      const res = await apiRequest("/api/admin/employees", "GET", null, adminToken);
      if (res.ok && res.data.employees) {
        CURRENT_ROSTER = res.data.employees;
        tbody.innerHTML = res.data.employees.map(emp => {
          const isActive = String(emp.is_active) === "1";
          const idSafe = String(emp.id || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
          const nameSafe = String(emp.full_name || emp.id || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
          return `
            <tr>
              <td><code>${escapeHtml(emp.id)}</code></td>
              <td><strong>${escapeHtml(emp.full_name)}</strong></td>
              <td>${escapeHtml(emp.email)}</td>
              <td><span class="pill pill-primary">${emp.zone || '-'}</span></td>
              <td title="${splitTitle(emp.clubs_approved_count || 0, (emp.clubs_approved_count || 0) - (emp.legacy_clubs_count || 0), emp.legacy_clubs_count, 'Club approvals')}"><strong>${emp.clubs_approved_count || 0}</strong></td>
              <td title="${splitTitle(emp.support_logs_count || 0, (emp.support_logs_count || 0) - (emp.legacy_support_count || 0), emp.legacy_support_count, 'Support logs')}">${emp.support_logs_count || 0}</td>
              <td>
                ${isActive ? '<span class="pill pill-success">Active</span>' : '<span class="pill pill-danger">Blocked</span>'}
              </td>
              <td>
                <div style="display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap;">
                  <button class="btn btn-outline btn-sm btn-rowact" onclick="openEditEmployeeModalById('${idSafe}')" title="Edit employee credentials & regional zone">
                    ✏️ Edit
                  </button>
                  <button class="btn btn-danger btn-sm btn-rowact" onclick="handleBlockEmployee('${idSafe}', '${nameSafe}')" ${!isActive ? 'disabled style="opacity: 0.45; cursor: not-allowed;"' : ''} title="${isActive ? 'Block employee access' : 'Employee is already blocked'}">
                    🚫 Block
                  </button>
                  <button class="btn btn-success btn-sm btn-rowact" onclick="handleUnblockEmployee('${idSafe}', '${nameSafe}')" ${isActive ? 'disabled style="opacity: 0.45; cursor: not-allowed;"' : ''} title="${!isActive ? 'Unblock employee and restore access' : 'Employee is already active'}">
                    🔓 Unblock
                  </button>
                </div>
              </td>
              <td>
                <a href="/employee/${emp.id}" target="_blank" rel="noopener noreferrer" class="btn btn-outline btn-sm btn-rowact">Open UI ↗</a>
              </td>
            </tr>
          `;
        }).join("");
      } else if (res.status === 403 || res.status === 401) {
        IS_ADMIN_AUTHENTICATED = false;
        showAdminGateView(false);
      }
    }

    function openEditEmployeeModalById(empId) {
      const emp = CURRENT_ROSTER.find(e => e.id === empId);
      if (!emp) return;
      openEditEmployeeModal(emp);
    }

    function openEditEmployeeModal(emp) {
      document.getElementById("edit-emp-original-id").value = emp.id;
      document.getElementById("edit-emp-id").value = emp.id;
      document.getElementById("edit-emp-name").value = emp.full_name;
      document.getElementById("edit-emp-email").value = emp.email;
      document.getElementById("edit-emp-pass").value = "";

      // Normalize zone for select matching
      let cleanZone = (emp.zone || "North").replace(/ Zone.*/i, "").replace(/ \d+/, "").trim();
      if (cleanZone === "NE" || cleanZone === "North-East") cleanZone = "North East";
      const zoneSelect = document.getElementById("edit-emp-zone");
      if (zoneSelect) {
        let matched = false;
        for (let opt of zoneSelect.options) {
          if (opt.value.toLowerCase() === cleanZone.toLowerCase()) {
            zoneSelect.value = opt.value;
            matched = true;
            break;
          }
        }
        if (!matched) zoneSelect.value = "North";
      }

      document.getElementById("edit-emp-states").value = emp.assigned_states || "";
      document.getElementById("edit-emp-active").value = String(emp.is_active) === "0" ? "0" : "1";
      document.getElementById("modal-edit-alert").innerHTML = "";
      const editModalEl = document.getElementById("edit-employee-modal");
      editModalEl.classList.add("active");
      ndliModalOpened(editModalEl);
    }

    function closeEditEmployeeModal() {
      const editModalEl = document.getElementById("edit-employee-modal");
      editModalEl.classList.remove("active");
      ndliModalClosed(editModalEl);
    }

    async function handleUpdateEmployee(e) {
      e.preventDefault();
      const oldId = document.getElementById("edit-emp-original-id").value.trim().toUpperCase();
      const newId = document.getElementById("edit-emp-id").value.trim().toUpperCase();
      const name = document.getElementById("edit-emp-name").value.trim();
      const email = document.getElementById("edit-emp-email").value.trim().toLowerCase();
      const pass = document.getElementById("edit-emp-pass").value;
      const zone = document.getElementById("edit-emp-zone").value;
      const states = document.getElementById("edit-emp-states").value.trim();
      const active = document.getElementById("edit-emp-active").value;
      const submitBtn = document.getElementById("btn-save-emp-update");
      const adminToken = sessionStorage.getItem("ndli_admin_token");

      const payload = {
        old_emp_id: oldId,
        new_emp_id: newId,
        full_name: name,
        email: email,
        zone: zone,
        assigned_states: states,
        is_active: active
      };
      if (pass.trim()) {
        payload.password = pass.trim();
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span>⏳</span> Synchronizing DB...`;

      try {
        const res = await apiRequest("/api/admin/employees/update", "POST", payload, adminToken);
        if (res.ok && res.data.success) {
          showAlert("admin-alert", `✓ Employee ${name} (${newId}) updated and synchronized across backend node DB!`, "success");
          closeEditEmployeeModal();
          loadEmployeesRoster();
          loadDashboardData();
        } else {
          const msg = res.data?.message || "Failed to update employee.";
          const c = document.getElementById("modal-edit-alert");
          if (c) {
            c.innerHTML = `<div class="alert alert-danger"><span>⚠️</span><div>${msg}</div></div>`;
          }
        }
      } catch (err) {
        const c = document.getElementById("modal-edit-alert");
        if (c) {
          c.innerHTML = `<div class="alert alert-danger"><span>⚠️</span><div>Network error while updating employee.</div></div>`;
        }
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>✓</span> Save & Sync with Backend DB`;
      }
    }

    async function handleBlockEmployee(userId, name) {
      if (!confirm(`Are you sure you want to BLOCK ${name || userId}?\n\nTheir active sessions will be terminated immediately and they will not be able to log into the NDLI portal.`)) {
        return;
      }
      await toggleEmployeeStatus(userId, false);
    }

    async function handleUnblockEmployee(userId, name) {
      if (!confirm(`UNBLOCK ${name || userId}?\n\nThis will immediately restore their full portal access and permit them to log in again.`)) {
        return;
      }
      await toggleEmployeeStatus(userId, true);
    }

    async function toggleEmployeeStatus(userId, newActiveStatus) {
      const adminToken = sessionStorage.getItem("ndli_admin_token");
      const res = await apiRequest("/api/admin/employees/status", "POST", {
        user_id: userId,
        is_active: newActiveStatus
      }, adminToken);
      if (res.ok) {
        const actionText = newActiveStatus ? "UNBLOCKED and access restored" : "BLOCKED";
        showAlert("admin-alert", `✓ Employee ${userId} successfully ${actionText}!`, "success");
        loadEmployeesRoster();
      } else {
        showAlert("admin-alert", `Error: ${res.data?.message || 'Failed to update status.'}`, "danger");
      }
    }

    // Handle Create Employee
    async function handleCreateEmployee(e) {
      e.preventDefault();
      const empId = document.getElementById("new-emp-id").value.trim().toUpperCase();
      const name = document.getElementById("new-emp-name").value.trim();
      const email = document.getElementById("new-emp-email").value.trim().toLowerCase();
      const pass = document.getElementById("new-emp-pass").value;
      const zone = document.getElementById("new-emp-zone").value;
      const states = document.getElementById("new-emp-states").value.trim();
      const adminToken = sessionStorage.getItem("ndli_admin_token");

      const payload = {
        emp_id: empId,
        full_name: name,
        email: email,
        password: pass,
        zone: zone,
        assigned_states: states
      };

      const res = await apiRequest("/api/admin/employees/create", "POST", payload, adminToken);
      if (res.ok) {
        showAlert("admin-alert", `✓ Employee ${name} (${empId}) provisioned with dedicated node database and credentials!`, "success");
        document.getElementById("create-employee-form").reset();
        loadEmployeesRoster();
        loadDashboardData();
      } else {
        showAlert("admin-alert", `Error: ${res.data?.message || 'Could not provision employee.'}`, "danger");
      }
    }

    // Trigger Node Reconcile
    async function triggerReconcile() {
      const res = await apiRequest("/api/sync/reconcile", "POST", {});
      if (res.ok) {
        const s = res.data.summary;
        showAlert("admin-alert", `✓ Master Reconciliation Complete! Synced ${s.employees_synced} nodes, verified ${s.total_master_clubs} clubs & ${s.total_master_activities} activities.`, "success");
        loadDashboardData();
      } else {
        showAlert("admin-alert", "Reconciliation failed.", "danger");
      }
    }

