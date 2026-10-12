    function initModalEventListeners() {
      // Escape key listener for closing modals
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const detailsModal = document.getElementById("club-details-modal");
          const registerModal = document.getElementById("club-register-modal");
          const attnModal = document.getElementById("renewal-attention-modal");
          const editEmpModal = document.getElementById("edit-employee-modal");
          const adminIssueModal = document.getElementById("admin-issue-resolution-modal");
          const adminEscalationsModal = document.getElementById("admin-escalations-list-modal");
          const migrationModal = document.getElementById("migration-modal");
          const migrationGateModal = document.getElementById("migration-gate-modal");
          const emergencyRestoreModal = document.getElementById("emergency-restore-modal");
          const hardResetModal = document.getElementById("hard-reset-modal");
          const changePasswordModal = document.getElementById("change-password-modal");
          const adminLoginModal = document.getElementById("admin-login-modal");

          // Esc closes the topmost open modal first — checked in z-index-ladder
          // order: admin-login (2500) → hard-reset / change-password (1260) →
          // emergency-restore (1250) → issue (1200) → escalations (1150) →
          // club-details (1100) → renewal-attention (1000) → edit-employee (base).
          if (adminLoginModal && (adminLoginModal.style.display === "flex" || adminLoginModal.classList.contains("active"))) {
            closeAdminLoginModal();
          } else if (hardResetModal && (hardResetModal.classList.contains("active") || hardResetModal.style.display === "flex")) {
            closeHardResetModal();
          } else if (changePasswordModal && (changePasswordModal.classList.contains("active") || changePasswordModal.style.display === "flex")) {
            closeChangePasswordModal();
          } else if (emergencyRestoreModal && (emergencyRestoreModal.classList.contains("active") || emergencyRestoreModal.style.display === "flex")) {
            closeEmergencyRestoreModal();
          } else if (adminIssueModal && (adminIssueModal.classList.contains("active") || adminIssueModal.style.display === "flex")) {
            closeAdminIssueModal();
          } else if (migrationGateModal && (migrationGateModal.classList.contains("active") || migrationGateModal.style.display === "flex")) {
            closeMigrationGateModal();
          } else if (migrationModal && (migrationModal.classList.contains("active") || migrationModal.style.display === "flex")) {
            closeMigrationModal();
          } else if (adminEscalationsModal && (adminEscalationsModal.classList.contains("active") || adminEscalationsModal.style.display === "flex")) {
            closeAdminEscalationsListModal();
          } else if (detailsModal && (detailsModal.classList.contains("active") || detailsModal.classList.contains("open"))) {
            backToAttentionList();
          } else if (registerModal && (registerModal.classList.contains("active") || registerModal.style.display === "flex")) {
            closeClubRegisterModal();
          } else if (attnModal && (attnModal.classList.contains("active") || attnModal.classList.contains("open"))) {
            closeRenewalAttentionModal();
          } else if (editEmpModal && (editEmpModal.classList.contains("active") || editEmpModal.classList.contains("open"))) {
            closeEditEmployeeModal();
          }
        }
      });

      // Click outside modal content to close
      document.querySelectorAll(".modal-overlay").forEach(overlay => {
        overlay.addEventListener("click", (e) => {
          if (e.target === overlay) {
            if (overlay.id === "admin-login-modal") {
              closeAdminLoginModal();
            } else if (overlay.id === "club-details-modal") {
              backToAttentionList();
            } else if (overlay.id === "club-register-modal") {
              closeClubRegisterModal();
            } else if (overlay.id === "migration-modal") {
              closeMigrationModal();
            } else if (overlay.id === "renewal-attention-modal") {
              closeRenewalAttentionModal();
            } else if (overlay.id === "edit-employee-modal") {
              closeEditEmployeeModal();
            } else if (overlay.id === "admin-escalations-list-modal") {
              closeAdminEscalationsListModal();
            } else if (overlay.id === "admin-issue-resolution-modal") {
              closeAdminIssueModal();
            } else if (overlay.id === "emergency-restore-modal") {
              closeEmergencyRestoreModal();
            } else if (overlay.id === "hard-reset-modal") {
              closeHardResetModal();
            } else if (overlay.id === "change-password-modal") {
              closeChangePasswordModal();
            }
          }
        });
      });
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initModalEventListeners);
    } else {
      initModalEventListeners();
    }

    window.onload = async () => {
      updateEmployeePortalNavLink();
      await checkAdminAuth();
      await loadDashboardData();
      await loadAIDecisions();
      document.getElementById("tab-btn-employees")?.addEventListener("click", () => {
        checkAdminAuth();
      });

      // Periodic refresh of dashboard, roster, backup status, and escalation reminders
      setInterval(() => {
        if (IS_ADMIN_AUTHENTICATED) {
          loadEmployeesRoster();
        }
        loadAdminEscalationReminders();
        loadAdminBackupStatus();
      }, 10000);

      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
          loadDashboardData();
          loadAdminEscalationReminders();
          loadAdminBackupStatus();
          if (IS_ADMIN_AUTHENTICATED) loadEmployeesRoster();
        }
      });
    };

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
