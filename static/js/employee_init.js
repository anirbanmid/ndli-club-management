    // =============================================================
    // 4. CONTINUOUS SYNCHRONIZATION WITH ADMIN & SESSION VALIDATION
    // =============================================================
    async function syncEmployeeWithAdmin() {
      // Resolve the token exactly like portal init (employee session first), so an
      // Administrator previewing a workspace can never hijack the employee identity.
      const token = sessionStorage.getItem("ndli_employee_token") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_token") : null) || sessionStorage.getItem("ndli_token") || localStorage.getItem("ndli_token");
      const portalView = document.getElementById("employee-portal-view");
      const isPortalVisible = portalView && portalView.style.display !== "none";

      if (isPortalVisible && token) {
        try {
          const res = await apiRequest("/api/auth/me", "GET", null, token);
          if (res.status === 401) {
            sessionStorage.removeItem("ndli_token");
            sessionStorage.removeItem("ndli_employee_token");
            sessionStorage.removeItem("ndli_employee_session");
            showLoginView(res.data && res.data.message ? res.data.message : "Your employee account has been suspended or session expired. Access denied.");
            return;
          }
          if (!res.ok || !res.data || !res.data.authenticated) {
            console.warn("Continuous sync temporary response:", res.status, res.data);
            return;
          }

          const u = res.data.user;
          // If Admin renamed employee ID (only an EMPLOYEE session may re-identify the
          // workspace — an admin's own user_id must never replace the employee identity)
          if (u.role === "EMPLOYEE" && u.user_id && u.user_id.toUpperCase() !== CURRENT_EMP_ID) {
            CURRENT_EMP_ID = u.user_id.toUpperCase();
            window.history.pushState({}, "", `/employee/${CURRENT_EMP_ID}`);
          }

          // Fetch fresh profile details dynamically
          const liveProf = await fetchLiveProfile(CURRENT_EMP_ID);
          if (liveProf) {
            await renderEmployeeProfile();
            updateNavAuth(true, u);
          }

          // Sync quota
          await loadEmployeeQuota();

          // Refresh active issue reminders
          loadEmployeeReminders();
        } catch (err) {
          console.warn("Continuous sync error:", err);
        }
      } else {
        // On login view, refresh live roster dynamically
        await fetchLiveRoster();
      }
    }

    async function initEmployeePortal() {
      // Start live local clock ticking immediately
      updateClock();
      setInterval(updateClock, 1000);

      // Modal dismissal (Esc key + backdrop click) — registered up front so it
      // stays wired on the login-first path where this init returns early.
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const editModal = document.getElementById("edit-modal");
          const issueModal = document.getElementById("employee-issue-modal");
          const remindersModal = document.getElementById("employee-reminders-list-modal");
          const renewalSecModal = document.getElementById("renewal-security-modal");
          const activityDeleteModal = document.getElementById("activity-delete-security-modal");
          const certTerminalModal = document.getElementById("renewal-certificate-terminal-modal");
          const bulkImportModal = document.getElementById("bulk-import-modal");

          // Esc closes the topmost open modal first — z-index-ladder order:
          // certificate terminal (1300) → bulk import (1280) → activity-delete
          // (1260) → renewal security (1250) → issue (1200) → reminders (1150)
          // → edit (base).
          if (certTerminalModal && (certTerminalModal.classList.contains("active") || certTerminalModal.style.display === "flex")) {
            closeCertificateTerminal();
          } else if (bulkImportModal && (bulkImportModal.classList.contains("active") || bulkImportModal.style.display === "flex")) {
            closeBulkImportModal();
          } else if (activityDeleteModal && (activityDeleteModal.classList.contains("active") || activityDeleteModal.style.display === "flex")) {
            closeActivityDeleteSecurityModal();
          } else if (renewalSecModal && (renewalSecModal.classList.contains("active") || renewalSecModal.style.display === "flex")) {
            closeRenewalSecurityModal();
          } else if (issueModal && (issueModal.classList.contains("active") || issueModal.style.display === "flex")) {
            closeEmployeeIssueModal();
          } else if (remindersModal && (remindersModal.classList.contains("active") || remindersModal.style.display === "flex")) {
            closeEmployeeRemindersListModal();
          } else if (editModal && (editModal.classList.contains("active") || editModal.style.display === "flex")) {
            closeEditModal();
          }
        }
      });

      // Click outside modal content to close (security/terminal modals included —
      // backdrop dismissal is a cancel action, same as their Cancel buttons)
      document.querySelectorAll(".modal-overlay").forEach(overlay => {
        overlay.addEventListener("click", (e) => {
          if (e.target === overlay) {
            if (overlay.id === "employee-issue-modal") {
              closeEmployeeIssueModal();
            } else if (overlay.id === "employee-reminders-list-modal") {
              closeEmployeeRemindersListModal();
            } else if (overlay.id === "edit-modal") {
              closeEditModal();
            } else if (overlay.id === "renewal-security-modal") {
              closeRenewalSecurityModal();
            } else if (overlay.id === "activity-delete-security-modal") {
              closeActivityDeleteSecurityModal();
            } else if (overlay.id === "renewal-certificate-terminal-modal") {
              closeCertificateTerminal();
            } else if (overlay.id === "bulk-import-modal") {
              closeBulkImportModal();
            }
          }
        });
      });

      // Continuous synchronization with Admin Master Control (every 30 seconds)
      setInterval(syncEmployeeWithAdmin, 30000);
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) syncEmployeeWithAdmin();
      });

      // Render cached / default chips immediately for zero delay
      renderOfficerChips();

      // Populate States dropdown immediately on portal init (public reference data, non-blocking)
      populateStateSelect("c-state");
      populateStateSelect("sec-c-state");
      loadStates();

      // Fetch live employee roster immediately from master database
      await fetchLiveRoster();

      const path = window.location.pathname.toLowerCase();
      const isExplicitLoginRoute = path === "/login" || path === "/employee/login";
      const pathParts = window.location.pathname.split("/").filter(Boolean);
      let routeEmpId = null;
      if (pathParts.length >= 2 && pathParts[0].toLowerCase() === "employee" && pathParts[1].toLowerCase() !== "login") {
        routeEmpId = decodeURIComponent(pathParts[1]).toUpperCase();
        CURRENT_EMP_ID = routeEmpId;
        // Only persist the identity while a real employee session is active. A bare URL
        // visit must never mint a phantom "active employee" for other portals to pick up.
        if (sessionStorage.getItem("ndli_employee_token") || sessionStorage.getItem("ndli_role") === "EMPLOYEE") {
          sessionStorage.setItem("ndli_current_emp_id", CURRENT_EMP_ID);
          sessionStorage.setItem("ndli_employee_id", CURRENT_EMP_ID);
        }
      } else {
        const savedEmpId = sessionStorage.getItem("ndli_employee_id") || sessionStorage.getItem("ndli_current_emp_id") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_user_id") : null);
        if (savedEmpId && EMP_PROFILES[savedEmpId]) {
          CURRENT_EMP_ID = savedEmpId;
        }
      }

      // Check for active authentication session
      const searchStr = (typeof window !== "undefined" && window.location && window.location.search) ? window.location.search : "";
      const urlParams = new URLSearchParams(searchStr);
      const urlToken = urlParams.get("token");
      if (urlToken) {
        sessionStorage.setItem("ndli_token", urlToken);
        sessionStorage.setItem("ndli_employee_token", urlToken);
      }
      const token = sessionStorage.getItem("ndli_employee_token") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_token") : null) || sessionStorage.getItem("ndli_token") || localStorage.getItem("ndli_token");

      // Handle explicit login routes (/login, /employee/login)
      if (isExplicitLoginRoute) {
        document.title = "Employee Sign-In | NDLI Regional Portal • IIT Kharagpur";
        if (token) {
          try {
            const res = await apiRequest("/api/auth/me", "GET", null, token);
            if (res.ok && res.data.authenticated) {
              const u = res.data.user;
              if (u.role === "EMPLOYEE") {
                showLoginView(`
                  <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem;">
                    <span>Currently signed in as <strong>${u.full_name} (${u.user_id} - ${u.zone} Zone)</strong>.</span>
                    <a href="/employee/${u.user_id}" class="btn btn-sm btn-primary" style="text-decoration: none; padding: 0.35rem 0.75rem;">Launch Workspace →</a>
                  </div>
                `);
                return;
              }
              // Admin (or any non-employee) session: never offer a phantom employee workspace.
              showLoginView(`You are currently signed in as <strong>Administrator (${u.user_id})</strong>. No zonal employee session is active — please sign in below as a zonal officer to open an employee workspace.`);
              return;
            }
          } catch (e) {}
        }
        showLoginView();
        return;
      }

      // If user directly opened /employee or /employee/<id> without active session
      if (!token) {
        showLoginView();
        return;
      }

      try {
        const res = await apiRequest("/api/auth/me", "GET", null, token);
        if (res.ok && res.data.authenticated) {
          const user = res.data.user;
          if (user.role === "EMPLOYEE") {
            CURRENT_EMP_ID = user.user_id.toUpperCase();
            sessionStorage.setItem("ndli_employee_id", CURRENT_EMP_ID);
            sessionStorage.setItem("ndli_current_emp_id", CURRENT_EMP_ID);
            showPortalView(user);
          } else if (user.role === "ADMIN") {
            // An Administrator may preview an EXPLICITLY requested workspace (/employee/<id>,
            // e.g. the admin roster "Open UI" action). With no employee signed in and no
            // explicit target, the portal must fall back to the sign-in screen — it must
            // NEVER default to a phantom dashboard such as EMP01.
            const previewEmpId = (routeEmpId && EMP_PROFILES[routeEmpId]) ? routeEmpId : null;
            if (previewEmpId) {
              CURRENT_EMP_ID = previewEmpId;
              showPortalView(user);
            } else {
              showLoginView("You are signed in as Administrator and no zonal employee session is active. Please sign in as a zonal officer to open an employee workspace.");
            }
          } else {
            showLoginView("Your account role cannot access a zonal employee workspace.");
          }
        } else {
          sessionStorage.removeItem("ndli_token");
          sessionStorage.removeItem("ndli_employee_token");
          sessionStorage.removeItem("ndli_employee_session");
          showLoginView("Your previous session has expired. Please sign in to continue.");
        }
      } catch (e) {
        showLoginView();
      }
    }

    if (typeof window !== "undefined") {
      window.openEmployeeRemindersListModal = openEmployeeRemindersListModal;
      window.closeEmployeeRemindersListModal = closeEmployeeRemindersListModal;
      window.handleEmployeeRemindersSearch = handleEmployeeRemindersSearch;
      window.renderEmployeeRemindersList = renderEmployeeRemindersList;
      window.selectEmployeeReminder = selectEmployeeReminder;
      window.openEmployeeIssueResolutionModal = openEmployeeIssueResolutionModal;
      window.closeEmployeeIssueModal = closeEmployeeIssueModal;
      window.submitEmployeeIssueResolution = submitEmployeeIssueResolution;
      window.onTabActivated = onTabActivated;
      window.onSearchTabActivated = onSearchTabActivated;
      window.onHistoryTabActivated = onHistoryTabActivated;
      window.performUniversalSearch = performUniversalSearch;
      window.loadEmployeeActivities = loadEmployeeActivities;
    }

    // Immediate and robust lifecycle initialization of Employee Portal and State dropdown
    if (typeof document !== "undefined") {
      const runImmediateStatePop = () => {
        populateStateSelect("c-state");
        populateStateSelect("sec-c-state");
        populateStateSelect("edit-state");
        const sEl = document.getElementById("c-state") || document.getElementById("sec-c-state");
        if (sEl) {
          sEl.addEventListener("focus", () => {
            if (sEl.options.length <= 1) {
              populateStateSelect("c-state");
              loadStates();
            }
          });
          sEl.addEventListener("click", () => {
            if (sEl.options.length <= 1) {
              populateStateSelect("c-state");
              loadStates();
            }
          });
        }
        loadStates();
      };

      const startPortal = () => {
        runImmediateStatePop();
        initEmployeePortal();
      };

      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", startPortal);
      } else {
        startPortal();
      }

      window.addEventListener("load", () => {
        runImmediateStatePop();
      });
    }

    // Resilient Global UI Error Boundary
    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
      window.addEventListener('error', function(e) {
        console.error('[NDLI UI Boundary error]', e.message, e.filename, e.lineno);
        const b = document.getElementById('ui-error-boundary-banner');
        if (b) {
          b.style.display = 'flex';
          b.innerHTML = '<span>⚠️ An unexpected interface glitch was safely intercepted.</span><button onclick="window.location.reload()" style="background:#fff;color:#be123c;border:none;padding:3px 10px;border-radius:4px;font-weight:700;cursor:pointer;margin-left:8px;">Reload</button>';
        }
      });
      window.addEventListener('unhandledrejection', function(e) {
        console.warn('[NDLI UI Boundary unhandled promise]', e.reason);
      });
    }
