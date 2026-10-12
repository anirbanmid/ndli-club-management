    // =============================================================
    // ADMIN AUTHENTICATION GATE & ACCESS CONTROL (EMPLOYEE MANAGEMENT)
    // =============================================================
    let IS_ADMIN_AUTHENTICATED = false;
    let CURRENT_ROSTER = [];

    async function checkAdminAuth() {
      const searchStr = (typeof window !== "undefined" && window.location && window.location.search) ? window.location.search : "";
      const urlParams = new URLSearchParams(searchStr);
      const urlToken = urlParams.get("token") || urlParams.get("admin_token");
      if (urlToken) {
        sessionStorage.setItem("ndli_admin_token", urlToken);
        sessionStorage.setItem("ndli_admin_role", "ADMIN");
      }
      const token = sessionStorage.getItem("ndli_admin_token");
      if (!token) {
        IS_ADMIN_AUTHENTICATED = false;
        showAdminGateView(false);
        return false;
      }

      try {
        const res = await apiRequest("/api/auth/me", "GET", null, token);
        if (res.ok && res.data && res.data.user && res.data.user.role === "ADMIN") {
          IS_ADMIN_AUTHENTICATED = true;
          sessionStorage.setItem("ndli_admin_token", token);
          sessionStorage.setItem("ndli_admin_role", "ADMIN");
          sessionStorage.setItem("ndli_admin_user_id", res.data.user.user_id || res.data.user.email);
          if (!sessionStorage.getItem("ndli_employee_token") && sessionStorage.getItem("ndli_role") !== "EMPLOYEE") {
            sessionStorage.setItem("ndli_token", token);
            sessionStorage.setItem("ndli_role", "ADMIN");
            sessionStorage.setItem("ndli_user_id", res.data.user.user_id || res.data.user.email);
          }
          showAdminGateView(true, res.data.user);
          loadEmployeesRoster();
          return true;
        } else {
          sessionStorage.removeItem("ndli_admin_token");
          sessionStorage.removeItem("ndli_admin_role");
          sessionStorage.removeItem("ndli_admin_user_id");
          if (sessionStorage.getItem("ndli_role") === "ADMIN") {
            sessionStorage.removeItem("ndli_token");
            sessionStorage.removeItem("ndli_role");
          }
          IS_ADMIN_AUTHENTICATED = false;
          showAdminGateView(false);
          return false;
        }
      } catch (err) {
        IS_ADMIN_AUTHENTICATED = false;
        showAdminGateView(false);
        return false;
      }
    }

    function showAdminGateView(isAuthenticated, user = null) {
      const gateEl = document.getElementById("admin-auth-gate");
      const contentEl = document.getElementById("admin-employee-content");
      const badgeEl = document.getElementById("nav-admin-badge");
      const userEl = document.getElementById("nav-admin-user");
      const btnEl = document.getElementById("nav-admin-auth-btn");

      if (isAuthenticated) {
        if (gateEl) gateEl.style.display = "none";
        if (contentEl) contentEl.style.display = "block";
        if (badgeEl) {
          badgeEl.innerText = "ADMIN VERIFIED";
          badgeEl.style.background = "var(--success)";
        }
        if (userEl) userEl.innerText = user?.email || "admin@iitkgp.ac.in";
        if (btnEl) {
          // R20 fix A: white text on the transparent btn-outline chip was invisible
          // on the light topbar. Use the readable .btn-lock chip + drop the inline white.
          btnEl.innerText = "Lock Admin";
          btnEl.className = "btn btn-sm btn-lock";
          btnEl.style.color = "";
        }
      } else {
        if (gateEl) gateEl.style.display = "block";
        if (contentEl) contentEl.style.display = "none";
        if (badgeEl) {
          badgeEl.innerText = "ADMIN LOCKED 🔒";
          badgeEl.style.background = "#dc2626";
        }
        if (userEl) userEl.innerText = "Access Restricted";
        if (btnEl) {
          btnEl.innerText = "Admin Sign-In";
          btnEl.className = "btn btn-sm btn-accent";
          btnEl.style.color = "#ffffff";
        }
      }
    }

    async function executeAdminLogin(id, pass, alertElId, unlockBtnId) {
      const alertEl = document.getElementById(alertElId);
      const unlockBtn = document.getElementById(unlockBtnId);
      const originalLabel = unlockBtn ? unlockBtn.innerHTML : "";

      if (!id || !pass) {
        if (alertEl) alertEl.innerHTML = `<div class="alert alert-danger" style="margin-bottom:0.75rem;"><span>⚠️</span><div>Admin User ID and Password are required.</div></div>`;
        return false;
      }

      if (unlockBtn) {
        unlockBtn.disabled = true;
        unlockBtn.innerHTML = `<span>⏳</span> Verifying Admin Credentials...`;
      }

      try {
        const res = await apiRequest("/api/auth/login", "POST", { email: id, password: pass });
        if (res.ok && res.data.success && res.data.session) {
          if (res.data.session.role !== "ADMIN") {
            if (alertEl) alertEl.innerHTML = `
              <div class="alert alert-danger" style="margin-bottom:0.75rem;">
                <span>🚫</span>
                <div><strong>Access Denied:</strong> Employee credentials detected (${res.data.session.user_id}). Only Central IIT Kharagpur Administrators (admin@iitkgp.ac.in / ADMIN01) have permission to unlock the Master Administration Dashboard.</div>
              </div>
            `;
            return false;
          }
          const token = res.data.session.token;
          sessionStorage.setItem("ndli_admin_token", token);
          sessionStorage.setItem("ndli_admin_session", JSON.stringify(res.data.session));
          sessionStorage.setItem("ndli_admin_user_id", res.data.session.user_id || "admin@iitkgp.ac.in");
          sessionStorage.setItem("ndli_admin_role", "ADMIN");
          if (!sessionStorage.getItem("ndli_employee_token") && sessionStorage.getItem("ndli_role") !== "EMPLOYEE") {
            sessionStorage.setItem("ndli_token", token);
            sessionStorage.setItem("ndli_auth_session", JSON.stringify(res.data.session));
            sessionStorage.setItem("ndli_user_id", res.data.session.user_id || "admin@iitkgp.ac.in");
            sessionStorage.setItem("ndli_role", "ADMIN");
          }
          IS_ADMIN_AUTHENTICATED = true;

          showAdminGateView(true, res.data.session);
          closeAdminLoginModal();
          updateEmployeePortalNavLink();

          const banner = document.getElementById("admin-auth-prompt-banner");
          if (banner) banner.remove();

          showAlert("admin-alert", "✓ Central Administrator authenticated. Master Dashboard & Employee Management unlocked!", "success");

          // IMMEDIATELY RELOAD ALL MASTER VIEWS AND DATA
          await loadDashboardData();
          await loadAIDecisions();
          loadEmployeesRoster();
          loadEmployeePerformance();
          loadAdminBackupStatus();
          loadAdminEscalationReminders();
          return true;
        } else {
          const msg = res.data?.message || "Invalid Admin User ID or Password.";
          if (alertEl) alertEl.innerHTML = `<div class="alert alert-danger" style="margin-bottom:0.75rem;"><span>⚠️</span><div>${msg}</div></div>`;
          return false;
        }
      } catch (err) {
        if (alertEl) alertEl.innerHTML = `<div class="alert alert-danger" style="margin-bottom:0.75rem;"><span>⚠️</span><div>Network error connecting to authentication server.</div></div>`;
        return false;
      } finally {
        if (unlockBtn) {
          unlockBtn.disabled = false;
          unlockBtn.innerHTML = originalLabel;
        }
      }
    }

    async function handleAdminGateLogin(e) {
      e.preventDefault();
      const id = document.getElementById("admin-gate-id").value.trim();
      const pass = document.getElementById("admin-gate-pass").value;
      await executeAdminLogin(id, pass, "admin-gate-alert", "btn-admin-unlock");
    }

    function openAdminLoginModal() {
      const modal = document.getElementById("admin-login-modal");
      if (!modal) {
        const tabBtn = document.getElementById("tab-btn-employees");
        if (tabBtn) tabBtn.click();
        const gate = document.getElementById("admin-auth-gate");
        if (gate) gate.scrollIntoView({ behavior: "smooth" });
        return;
      }
      const alertEl = document.getElementById("admin-modal-alert");
      if (alertEl) alertEl.innerHTML = "";
      const passInp = document.getElementById("admin-modal-pass");
      if (passInp) passInp.value = "";
      const idInp = document.getElementById("admin-modal-id");
      if (idInp && !idInp.value) idInp.value = "admin@iitkgp.ac.in";

      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      modal.style.opacity = "1";
      modal.style.visibility = "visible";
      ndliModalOpened(modal);

      setTimeout(() => { if (passInp) passInp.focus(); }, 100);
    }

    function closeAdminLoginModal() {
      const modal = document.getElementById("admin-login-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
        modal.style.opacity = "0";
        modal.style.visibility = "hidden";
        ndliModalClosed(modal);
      }
    }

    window.openAdminLoginModal = openAdminLoginModal;
    window.closeAdminLoginModal = closeAdminLoginModal;
    window.handleAdminModalLogin = handleAdminModalLogin;
    window.toggleModalAdminPassVisibility = toggleModalAdminPassVisibility;
    window.toggleAdminAuthAction = toggleAdminAuthAction;

    function toggleModalAdminPassVisibility() {
      const input = document.getElementById("admin-modal-pass");
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
    }

    async function handleAdminModalLogin(e) {
      e.preventDefault();
      const id = document.getElementById("admin-modal-id").value.trim();
      const pass = document.getElementById("admin-modal-pass").value;
      await executeAdminLogin(id, pass, "admin-modal-alert", "btn-admin-modal-unlock");
    }

    function toggleAdminPassVisibility() {
      const input = document.getElementById("admin-gate-pass");
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
    }

    function lockAdminSection() {
      sessionStorage.removeItem("ndli_admin_token");
      sessionStorage.removeItem("ndli_admin_session");
      sessionStorage.removeItem("ndli_admin_user_id");
      sessionStorage.removeItem("ndli_admin_role");
      if (sessionStorage.getItem("ndli_role") === "ADMIN") {
        sessionStorage.removeItem("ndli_token");
        sessionStorage.removeItem("ndli_role");
        sessionStorage.removeItem("ndli_auth_session");
        sessionStorage.removeItem("ndli_user_id");
      }
      IS_ADMIN_AUTHENTICATED = false;
      showAdminGateView(false);
      const formEl = document.getElementById("admin-gate-form");
      if (formEl) formEl.reset();
      const alertEl = document.getElementById("admin-gate-alert");
      if (alertEl) alertEl.innerHTML = "";
      renderUnauthenticatedKPIs(401);
      showAlert("admin-alert", "Employee Management section has been locked. Admin authentication required to re-enter.", "info");
    }

    function toggleAdminAuthAction() {
      if (IS_ADMIN_AUTHENTICATED) {
        lockAdminSection();
      } else {
        openAdminLoginModal();
      }
    }

    function updateEmployeePortalNavLink() {
      // The Employee Portal link may only target a concrete workspace while an ACTIVE
      // employee session exists in this tab. An admin-only session (or a stale id with no
      // employee session) must fall back to the employee sign-in entry — never to a
      // default employee dashboard such as EMP01.
      const hasEmployeeSession = !!sessionStorage.getItem("ndli_employee_token") || sessionStorage.getItem("ndli_role") === "EMPLOYEE";
      const empId = hasEmployeeSession
        ? (sessionStorage.getItem("ndli_employee_id") || sessionStorage.getItem("ndli_current_emp_id") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_user_id") : null) || "").toUpperCase()
        : "";
      document.querySelectorAll(".nav-link-employee").forEach(el => {
        if (empId) {
          el.href = `/employee/${empId}`;
          el.title = `Return to ${empId} Zonal Employee Portal`;
        } else {
          el.href = "/employee";
          el.title = "Employee Portal — Sign-In Required";
        }
      });
    }

