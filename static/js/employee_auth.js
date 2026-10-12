    // =============================================================
    // 2. AUTHENTICATION & LOGIN SCREEN CONTROLLER
    // =============================================================
    function renderOfficerChips() {
      const container = document.getElementById("officer-chips-container");
      if (!container) return;

      container.innerHTML = Object.entries(EMP_PROFILES).map(([empId, prof]) => {
        const isBlocked = String(prof.is_active) === "0";
        const zoneStr = prof.zone.endsWith("Zone") ? prof.zone : `${prof.zone} Zone`;
        const cleanName = (prof.name || '').replace(/\s*\([^)]*\)/g, '').trim();
        return `
          <button
            type="button"
            class="officer-chip ${empId === CURRENT_EMP_ID ? 'active' : ''}"
            data-emp="${empId}"
            onclick="fillLoginCredentials('${empId}')"
            title="${isBlocked ? 'Account Blocked by Administrator' : `Click to select ${cleanName} (${empId})`}"
            style="${isBlocked ? 'opacity: 0.65; border-color: #fca5a5; background: #fff5f5;' : ''}"
          >
            <span class="chip-code">${empId}${isBlocked ? ' 🔒' : ''}</span>
            <span class="chip-name">${cleanName}</span>
            <span class="chip-zone" style="${isBlocked ? 'color: var(--danger); font-weight: 700;' : ''}">${isBlocked ? 'Access Blocked' : zoneStr}</span>
          </button>
        `;
      }).join("");
    }
    // Render chips immediately on script execution using default profiles
    try { renderOfficerChips(); } catch (e) {}

    function fillLoginCredentials(empId) {
      const prof = EMP_PROFILES[empId];
      if (!prof) return;

      const isBlocked = String(prof.is_active) === "0";
      const zoneStr = prof.zone && prof.zone.endsWith('Zone') ? prof.zone : `${prof.zone || ''} Zone`;
      const cleanName = (prof.name || '').replace(/\s*\([^)]*Zone\)/gi, '').trim();
      const identInput = document.getElementById("login-identifier");
      const passInput = document.getElementById("login-password");
      if (identInput) identInput.value = empId;
      if (passInput) {
        passInput.value = "";
        passInput.focus();
      }

      document.querySelectorAll(".officer-chip").forEach(c => {
        c.classList.toggle("active", c.getAttribute("data-emp") === empId);
      });

      if (isBlocked) {
        showLoginAlert(`
          <div>
            <strong>Access Blocked:</strong> Officer <strong>${empId} — ${cleanName}</strong> has been disabled or blocked by the Administrator. Sign-in is restricted.
          </div>
        `, "danger");
        return;
      }

      showLoginAlert(`
        <div>
          Selected Officer: <strong>${empId} — ${cleanName} (${zoneStr})</strong>.
          <br>Please enter your password to sign in.
        </div>
      `, "success");
    }

    function togglePasswordVisibility(inputId, btn) {
      const id = (typeof inputId === "string" && inputId) ? inputId : "login-password";
      const input = document.getElementById(id);
      const toggleBtn = (btn && btn.nodeType) ? btn : document.getElementById("btn-password-toggle");
      if (!input) return;
      if (input.type === "password") {
        input.type = "text";
        if (toggleBtn) toggleBtn.innerText = "🙈 Hide";
      } else {
        input.type = "password";
        if (toggleBtn) toggleBtn.innerText = "👁️ Show";
      }
    }

    function showLoginAlert(message, type = "danger") {
      const c = document.getElementById("login-alert");
      if (!c) return;
      c.innerHTML = `
        <div class="alert alert-${type}" style="margin-bottom: 1.25rem;">
          <span>${type === 'success' ? '✓' : '⚠️'}</span>
          <div>${message}</div>
        </div>
      `;
    }

    async function handleLoginSubmit(e) {
      e.preventDefault();
      const identifier = document.getElementById("login-identifier").value.trim();
      const password = document.getElementById("login-password").value.trim();
      const submitBtn = document.getElementById("btn-login-submit");

      if (!identifier || !password) {
        showLoginAlert("Please enter both Employee User ID / Email and password.", "danger");
        return;
      }

      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span>⏳</span> Verifying credentials...`;

      try {
        const res = await apiRequest("/api/auth/login", "POST", { email: identifier, password: password });
        if (res.ok && res.data.success && res.data.session) {
          const session = res.data.session;
          sessionStorage.setItem("ndli_token", session.token);
          sessionStorage.setItem("ndli_employee_token", session.token);
          sessionStorage.setItem("ndli_employee_id", session.user_id);
          sessionStorage.setItem("ndli_current_emp_id", session.user_id);
          sessionStorage.setItem("ndli_employee_session", JSON.stringify(session));
          sessionStorage.setItem("ndli_auth_session", JSON.stringify(session));
          sessionStorage.setItem("ndli_user_id", session.user_id);
          sessionStorage.setItem("ndli_role", session.role || "EMPLOYEE");

          CURRENT_USER_SESSION = session;
          if (session.role === "EMPLOYEE") {
            CURRENT_EMP_ID = session.user_id;
          }
          window.history.pushState({}, "", `/employee/${CURRENT_EMP_ID}`);

          showPortalView(session);
          showAlert("global-alert", `✓ Welcome, ${session.full_name}! Regional Portal active for ${session.zone || 'Assigned'} Zone.`, "success");
        } else {
          showLoginAlert(res.data.message || "Invalid credentials. Please verify your User ID and password.", "danger");
        }
      } catch (err) {
        showLoginAlert("Network error while connecting to authentication server.", "danger");
      } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `<span>🔐</span> Sign In to Regional Portal →`;
      }
    }

    async function handleLogout() {
      // Only ever terminate the EMPLOYEE session server-side. If the viewer is an
      // Administrator previewing a workspace, the admin session must stay intact.
      const token = sessionStorage.getItem("ndli_employee_token") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_token") : null);
      if (token) {
        try {
          await apiRequest("/api/auth/logout", "POST", { token: token });
        } catch (e) {
          console.warn("Logout error:", e);
        }
      }
      sessionStorage.removeItem("ndli_token");
      sessionStorage.removeItem("ndli_employee_token");
      sessionStorage.removeItem("ndli_employee_id");
      sessionStorage.removeItem("ndli_current_emp_id");
      sessionStorage.removeItem("ndli_employee_session");
      sessionStorage.removeItem("ndli_auth_session");
      sessionStorage.removeItem("ndli_user_id");
      sessionStorage.removeItem("ndli_role");
      localStorage.removeItem("ndli_token");
      document.documentElement.classList.remove("auth-portal-unlocked");
      CURRENT_USER_SESSION = null;

      showLoginView(token ? "You have signed out successfully." : "Workspace closed. No zonal employee session is active.");
    }

    function promptSwitchOfficer() {
      showLoginView("Please enter credentials for the regional officer you wish to sign in as.");
    }

    async function showLoginView(optionalMessage = "") {
      // The flash-guard CSS uses display:!important — only dropping its class makes the
      // sign-in view actually visible again whenever a non-employee session was detected.
      document.documentElement.classList.remove("auth-portal-unlocked");
      const loginView = document.getElementById("employee-login-view");
      const portalView = document.getElementById("employee-portal-view");

      if (portalView) portalView.style.display = "none";
      if (loginView) {
        loginView.style.display = "block";
        loginView.classList.remove("view-fade-in");
        void loginView.offsetWidth;
        loginView.classList.add("view-fade-in");
        if (window.UI && UI.enter) UI.enter(loginView);
      }

      updateNavAuth(false);
      await fetchLiveRoster();

      // Password field must ALWAYS be empty on load — user must enter password!
      const passInput = document.getElementById("login-password");
      if (passInput) passInput.value = "";

      // Only pre-fill User ID if explicitly requested via specific route e.g. /employee/EMP02 or /employee/<id>
      const identInput = document.getElementById("login-identifier");
      if (identInput) {
        const pathParts = window.location.pathname.split("/").filter(Boolean);
        if (pathParts.length >= 2 && pathParts[0].toLowerCase() === "employee" && pathParts[1].toLowerCase() !== "login") {
          identInput.value = decodeURIComponent(pathParts[1]).toUpperCase();
        } else if (!identInput.value) {
          identInput.value = "";
        }
      }

      if (optionalMessage) {
        showLoginAlert(optionalMessage, "success");
      } else {
        const c = document.getElementById("login-alert");
        if (c) c.innerHTML = "";
      }
    }

    async function showPortalView(session) {
      // Hard guard: a workspace may only render with a resolved, known employee identity.
      if (!CURRENT_EMP_ID) {
        showLoginView("No active employee session found. Please sign in as a zonal officer.");
        return;
      }
      CURRENT_USER_SESSION = session;
      loadTrainingDecks();
      document.documentElement.classList.add("auth-portal-unlocked");
      const loginView = document.getElementById("employee-login-view");
      const portalView = document.getElementById("employee-portal-view");

      if (loginView) loginView.style.display = "none";
      if (portalView) {
        portalView.style.display = "block";
        portalView.classList.remove("view-fade-in");
        void portalView.offsetWidth;
        portalView.classList.add("view-fade-in");
        if (window.UI && UI.enter) UI.enter(portalView);
      }

      // Preload clubs database and node activities concurrently in background (non-blocking)
      performUniversalSearch("");
      loadEmployeeActivities();

      await fetchLiveProfile(CURRENT_EMP_ID);
      updateNavAuth(true, session);

      // Populate States dropdown
      await loadStates();
      await renderEmployeeProfile();
      loadEmployeeQuota();
      loadEmployeeReminders();

      // Set default renewal date in SEC C to 1 year ahead
      const renEl = document.getElementById("c-renewal-display") || document.getElementById("c-renewal");
      if (renEl && typeof calculateNextRenewalDate === "function") {
        renEl.value = `${calculateNextRenewalDate(new Date().toISOString(), null)} (+1 Year Initial Validity)`;
      }
    }

    function updateNavAuth(isLoggedIn, session = null) {
      const container = document.getElementById("nav-auth-section");
      if (!container) return;

      if (!isLoggedIn || !session) {
        container.innerHTML = `
          <a href="/login" class="btn btn-primary btn-sm" style="padding: 0.22rem 0.55rem; font-size: 0.74rem; text-decoration: none; white-space: nowrap;">
            🔐 Sign In
          </a>
        `;
        return;
      }

      const prof = EMP_PROFILES[CURRENT_EMP_ID] || { name: session.full_name, zone: session.zone };
      const firstName = (prof.name || session.full_name || 'Officer').split(" ")[0];
      const zoneStr = prof.zone || session.zone || 'Regional';
      container.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.3rem; flex-wrap: nowrap; flex-shrink: 0;">
          <span class="badge-tag" style="background: var(--warning); font-size: 0.7rem; padding: 0.18rem 0.45rem; white-space: nowrap;" title="Authenticated: ${prof.name || session.full_name} (${zoneStr} Zone)">
            👤 ${CURRENT_EMP_ID} (${firstName})
          </span>
          <button type="button" class="btn btn-outline btn-sm" onclick="promptSwitchOfficer()" style="color: #ffffff; border-color: rgba(255,255,255,0.4); padding: 0.18rem 0.45rem; font-size: 0.72rem; white-space: nowrap;" title="Sign in as another zonal officer">
            Switch
          </button>
          <button type="button" class="btn btn-outline btn-sm" onclick="handleLogout()" style="color: #ffffff; border-color: rgba(255,255,255,0.4); padding: 0.18rem 0.45rem; font-size: 0.72rem; white-space: nowrap;" title="Sign Out">
            Sign Out
          </button>
        </div>
      `;
    }

