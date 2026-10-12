    // Immediate global bootstrap for Admin Sign-In modal
    // NOTE: the full definition in the main script below reassigns
    // window.openAdminLoginModal later — that later assignment wins at runtime.
    window.openAdminLoginModal = function() {
      const modal = document.getElementById("admin-login-modal");
      if (modal) {
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.display = "flex";
        modal.style.opacity = "1";
        modal.style.visibility = "visible";
        const passInp = document.getElementById("admin-modal-pass");
        if (passInp) passInp.focus();
      } else {
        const tabBtn = document.getElementById("tab-btn-employees");
        if (tabBtn) tabBtn.click();
        const gate = document.getElementById("admin-auth-gate");
        if (gate) gate.scrollIntoView({ behavior: "smooth" });
      }
    };
    window.closeAdminLoginModal = function() {
      const modal = document.getElementById("admin-login-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
        modal.style.opacity = "0";
        modal.style.visibility = "hidden";
      }
    };
    window.toggleAdminAuthAction = function() {
      if (window.IS_ADMIN_AUTHENTICATED) {
        if (typeof lockAdminSection === "function") lockAdminSection();
      } else {
        window.openAdminLoginModal();
      }
    };
