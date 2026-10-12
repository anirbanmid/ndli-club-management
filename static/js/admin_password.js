    // ===== Self-service password change (credential rotation provision) =====
    function openChangePasswordModal() {
      const modal = document.getElementById("change-password-modal");
      if (modal) {
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.display = "flex";
        modal.style.opacity = "1";
        modal.style.visibility = "visible";
        ndliModalOpened(modal);
      }
      document.getElementById("chg-current-password").value = "";
      document.getElementById("chg-new-password").value = "";
      document.getElementById("chg-confirm-password").value = "";
      document.getElementById("chg-password-error").style.display = "none";
      document.getElementById("chg-password-success").style.display = "none";
      document.getElementById("btn-submit-change-password").disabled = false;
    }

    function closeChangePasswordModal() {
      const modal = document.getElementById("change-password-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
        modal.style.opacity = "0";
        modal.style.visibility = "hidden";
        ndliModalClosed(modal);
      }
    }

    async function submitChangePassword() {
      const cur = document.getElementById("chg-current-password").value;
      const nw = document.getElementById("chg-new-password").value;
      const cf = document.getElementById("chg-confirm-password").value;
      const errEl = document.getElementById("chg-password-error");
      const okEl = document.getElementById("chg-password-success");
      errEl.style.display = "none";
      okEl.style.display = "none";
      const fail = (msg) => { errEl.textContent = msg; errEl.style.display = "block"; };
      if (!cur || !nw) { fail("Both current and new password are required."); return; }
      if (nw.length < 8) { fail("New password must be at least 8 characters long."); return; }
      if (nw !== cf) { fail("New passwords do not match."); return; }
      const btn = document.getElementById("btn-submit-change-password");
      btn.disabled = true;
      try {
        const res = await apiRequest("/api/auth/change-password", "POST", {
          current_password: cur,
          new_password: nw
        });
        if (res.ok && res.data && res.data.success) {
          okEl.textContent = "✓ Password changed successfully. Please use the new password at next sign-in.";
          okEl.style.display = "block";
          document.getElementById("chg-current-password").value = "";
          document.getElementById("chg-new-password").value = "";
          document.getElementById("chg-confirm-password").value = "";
        } else {
          fail((res.data && res.data.message) || "Password change failed.");
        }
      } catch (err) {
        fail("Password change failed: " + err.message);
      } finally {
        btn.disabled = false;
      }
    }
    window.openChangePasswordModal = openChangePasswordModal;
    window.closeChangePasswordModal = closeChangePasswordModal;
    window.submitChangePassword = submitChangePassword;
