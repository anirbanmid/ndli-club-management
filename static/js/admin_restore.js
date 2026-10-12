    // =========================================================================
    // EMERGENCY ONE-CLICK DATABASE RESTORE WITH DUAL-LAYER SECURITY
    // =========================================================================
    let currentRestoreCaptcha = "";

    function generateRestoreCaptcha() {
      const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
      let code = "";
      for (let i = 0; i < 5; i++) {
        code += chars.charAt(Math.floor(Math.random() * chars.length));
      }
      currentRestoreCaptcha = code;
      const display = document.getElementById("restore-captcha-display");
      if (display) display.innerText = code;
      const input = document.getElementById("restore-captcha-input");
      if (input) input.value = "";
      const err = document.getElementById("restore-captcha-error");
      if (err) { err.style.display = "none"; err.innerText = ""; }
      return code;
    }

    function openEmergencyRestoreModal(targetBackupId = "") {
      const modal = document.getElementById("emergency-restore-modal");
      if (!modal) return;

      generateRestoreCaptcha();

      const passInput = document.getElementById("restore-admin-password");
      if (passInput) passInput.value = "";
      const passErr = document.getElementById("restore-password-error");
      if (passErr) { passErr.style.display = "none"; passErr.innerText = ""; }

      // Populate select dropdown with available backups
      const select = document.getElementById("restore-target-select");
      if (select) {
        select.innerHTML = '<option value="">Latest Available Backup Snapshot (Default)</option>';
        if (window._cachedAdminBackups && window._cachedAdminBackups.length > 0) {
          window._cachedAdminBackups.forEach(b => {
            const opt = document.createElement("option");
            opt.value = b.backup_id || b.filename;
            opt.innerText = `${b.backup_id || b.filename} (${b.created_at ? new Date(b.created_at).toLocaleDateString() : 'Snapshot'})`;
            if (targetBackupId && (b.backup_id === targetBackupId || b.filename === targetBackupId)) {
              opt.selected = true;
            }
            select.appendChild(opt);
          });
        } else if (targetBackupId) {
          const opt = document.createElement("option");
          opt.value = targetBackupId;
          opt.innerText = `${targetBackupId} (Selected Archive)`;
          opt.selected = true;
          select.appendChild(opt);
        }
      }

      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      ndliModalOpened(modal);

      setTimeout(() => {
        const cInp = document.getElementById("restore-captcha-input");
        if (cInp) cInp.focus();
      }, 100);
    }

    function closeEmergencyRestoreModal() {
      const modal = document.getElementById("emergency-restore-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
        ndliModalClosed(modal);
      }
    }

    async function executeEmergencyRestore() {
      const captchaInput = (document.getElementById("restore-captcha-input")?.value || "").trim().toUpperCase();
      const passInput = (document.getElementById("restore-admin-password")?.value || "").trim();
      const targetBackup = document.getElementById("restore-target-select")?.value || "";

      const captchaErr = document.getElementById("restore-captcha-error");
      const passErr = document.getElementById("restore-password-error");

      let hasError = false;
      if (captchaErr) { captchaErr.style.display = "none"; captchaErr.innerText = ""; }
      if (passErr) { passErr.style.display = "none"; passErr.innerText = ""; }

      if (!captchaInput) {
        if (captchaErr) {
          captchaErr.innerText = "Please enter the 5-character CAPTCHA security code.";
          captchaErr.style.display = "block";
        }
        hasError = true;
      } else if (captchaInput !== currentRestoreCaptcha) {
        if (captchaErr) {
          captchaErr.innerText = "Incorrect CAPTCHA code. Please re-enter.";
          captchaErr.style.display = "block";
        }
        generateRestoreCaptcha();
        hasError = true;
      }

      if (!passInput) {
        if (passErr) {
          passErr.innerText = "Administrator password is required.";
          passErr.style.display = "block";
        }
        hasError = true;
      }

      if (hasError) return;

      const confirmBtn = document.getElementById("btn-execute-restore");
      const cancelBtn = document.getElementById("btn-cancel-restore");
      const originalText = confirmBtn ? confirmBtn.innerHTML : "";

      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = "<span>⏳</span> Restoring Databases &amp; Reconciling...";
      }
      if (cancelBtn) cancelBtn.disabled = true;

      try {
        const payload = {
          password: passInput,
          source: targetBackup || undefined,
          backup_id: targetBackup || undefined
        };

        const res = await apiRequest("/api/admin/backup/restore", "POST", payload);

        if (res.ok && res.data && res.data.success) {
          closeEmergencyRestoreModal();
          const recInfo = res.data.reconciliation ? `\n🔄 Reconciled ${res.data.reconciliation.reconciled_clubs || 0} clubs & ${res.data.reconciliation.reconciled_activities || 0} activities across nodes.` : '';
          alert(`✅ EMERGENCY DATABASE RESTORATION SUCCESSFUL!\n\n📦 Restored from: ${res.data.restored_from || targetBackup || 'Latest Snapshot'}\n📁 Files Restored: ${res.data.restored_files_count || 'All database files'}${recInfo}\n\nSystem data is synchronized and active.`);
          loadDashboardData();
          loadAdminBackupStatus();
        } else {
          const errMsg = res.data?.message || res.message || "Failed to restore database.";
          if (errMsg.toLowerCase().includes("password") || errMsg.toLowerCase().includes("authentication")) {
            if (passErr) {
              passErr.innerText = errMsg;
              passErr.style.display = "block";
            } else {
              showAlert("admin-alert", "Restoration Failed: " + errMsg, "danger");
            }
          } else {
            showAlert("admin-alert", "Restoration Failed: " + errMsg, "danger");
          }
          generateRestoreCaptcha();
        }
      } catch (err) {
        showAlert("admin-alert", "Error during restoration: " + err.message, "danger");
        generateRestoreCaptcha();
      } finally {
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = originalText;
        }
        if (cancelBtn) cancelBtn.disabled = false;
      }
    }

