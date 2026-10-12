    // =========================================================================
    // =========================================================================
    // DANGER ZONE: HARD RESET / HANDOVER (triple-layer security: phrase +
    // admin password + owner-only handover PIN)
    // =========================================================================
    function openHardResetModal() {
      const modal = document.getElementById("hard-reset-modal");
      if (!modal) return;
      const cInp = document.getElementById("hard-reset-confirm-input");
      const pInp = document.getElementById("hard-reset-admin-password");
      const kInp = document.getElementById("hard-reset-pin-input");
      const st = document.getElementById("hard-reset-status");
      const pErr = document.getElementById("hard-reset-password-error");
      if (cInp) cInp.value = "";
      if (pInp) pInp.value = "";
      if (kInp) kInp.value = "";
      if (st) { st.style.display = "none"; st.innerHTML = ""; }
      if (pErr) { pErr.style.display = "none"; pErr.innerText = ""; }
      validateHardResetForm();
      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      ndliModalOpened(modal);
      setTimeout(() => { if (cInp) cInp.focus(); }, 100);
    }

    function closeHardResetModal() {
      const modal = document.getElementById("hard-reset-modal");
      if (!modal) return;
      modal.classList.remove("active");
      modal.classList.remove("open");
      modal.style.display = "none";
      ndliModalClosed(modal);
    }

    function validateHardResetForm() {
      const cInp = document.getElementById("hard-reset-confirm-input");
      const pInp = document.getElementById("hard-reset-admin-password");
      const kInp = document.getElementById("hard-reset-pin-input");
      const btn = document.getElementById("btn-execute-hard-reset");
      if (!btn) return;
      const phraseOk = !!(cInp && cInp.value.trim() === "HARD-RESET-FOR-HANDOVER");
      const passOk = !!(pInp && pInp.value.trim());
      const pinOk = !!(kInp && /^\d{6}$/.test(kInp.value.trim()));
      btn.disabled = !(phraseOk && passOk && pinOk);
      btn.style.opacity = btn.disabled ? "0.45" : "1";
    }

    async function executeHardReset() {
      const cInp = document.getElementById("hard-reset-confirm-input");
      const pInp = document.getElementById("hard-reset-admin-password");
      const kInp = document.getElementById("hard-reset-pin-input");
      const st = document.getElementById("hard-reset-status");
      const btn = document.getElementById("btn-execute-hard-reset");
      const pErr = document.getElementById("hard-reset-password-error");
      if (!cInp || cInp.value.trim() !== "HARD-RESET-FOR-HANDOVER") return;
      if (btn) { btn.disabled = true; btn.innerHTML = "<span>⏳</span> Performing Hard Reset..."; }
      if (pErr) { pErr.style.display = "none"; pErr.innerText = ""; }
      try {
        const res = await apiRequest("/api/admin/data/hard-reset", "POST", {
          confirm: cInp.value.trim(),
          password: pInp ? pInp.value : "",
          pin: kInp ? kInp.value.trim() : ""
        });
        if (res.ok && res.data && res.data.success) {
          const d = res.data;
          if (st) {
            st.style.display = "block";
            st.innerHTML = `<div class="alert alert-success" style="margin: 0;"><span>✓</span><div><strong>Hard Reset complete.</strong> ${escapeHtml(d.message || "")}<br>Safety checkpoint <code>${escapeHtml(d.checkpoint_backup_id || "")}</code> — restore it from the archives list if needed.</div></div>`;
          }
          showAlert("admin-alert", "✓ Hard Reset complete — system is blank. Auto-checkpoint: " + (d.checkpoint_backup_id || "n/a"), "success");
          loadDashboardData();
          loadAdminBackupStatus();
          loadEmployeesRoster();
        } else {
          const msg = (res.data && (res.data.message || res.data.error)) || "Hard Reset failed.";
          if ((res.status === 401 || res.status === 403) && pErr) {
            pErr.style.display = "block";
            pErr.innerText = msg;
          }
          if (st) {
            st.style.display = "block";
            st.innerHTML = `<div class="alert alert-danger" style="margin: 0;"><span>⚠️</span><div>${escapeHtml(msg)}</div></div>`;
          }
        }
      } catch (e) {
        if (st) {
          st.style.display = "block";
          st.innerHTML = `<div class="alert alert-danger" style="margin: 0;"><span>⚠️</span><div>Network error: ${escapeHtml(e.message)}</div></div>`;
        }
      } finally {
        if (btn) { btn.innerHTML = "<span>⚠️</span> Perform Hard Reset"; validateHardResetForm(); }
      }
    }

