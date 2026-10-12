    /* Immediate synchronous auth resolution to eliminate jerky login-card flash when navigating to employee portal */
    (function() {
      try {
        var path = window.location.pathname.toLowerCase();
        var isExplicitLogin = path === "/login" || path === "/employee/login";
        // Only an ACTIVE EMPLOYEE session may pre-unlock the workspace. An admin (or any
        // non-employee) token must never flash the portal view open with its placeholder content.
        var t = sessionStorage.getItem("ndli_employee_token")
             || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_token") : null)
             || sessionStorage.getItem("ndli_employee_session");
        if (t && !isExplicitLogin) {
          document.documentElement.classList.add("auth-portal-unlocked");
        }
      } catch(e) {}
    })();
