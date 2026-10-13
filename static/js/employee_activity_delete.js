    // =============================================================
    // ACTIVITY LOG DELETION (single or bulk) — with security modal
    // =============================================================

    // R47: bulk entries delete as ONE unit. A bulk row's id is
    // `ACT-<emp>-<ts_base>-<i>`; every sibling row sharing the same
    // `<base>` is part of the same bulk entry. Suffix-less ids (single
    // rows) never form a group, so they are never swept along.
    function getActivityBulkGroupIds(activityId) {
      const id = String(activityId || "").trim();
      const m = id.match(/^(ACT-.+-\d+)-\d+$/);
      if (!m) return [];
      const base = m[1];
      return (ALL_ACTIVITIES_CACHE || [])
        .map(a => (a && a.activity_id) ? String(a.activity_id).trim() : "")
        .filter(aid => aid && aid !== id && aid.indexOf(base + "-") === 0 && /^\d+$/.test(aid.slice(base.length + 1)));
    }

    function openActivityDeleteSecurityModal(singleActivityId) {
      try {
        ACTIVITY_DELETE_PENDING_IDS = singleActivityId
          ? [singleActivityId]
          : Array.from(SELECTED_ACTIVITY_IDS);

        if (ACTIVITY_DELETE_PENDING_IDS.length === 0) {
          return;
        }

        // R47: expand each requested bulk member to its WHOLE group before
        // confirming -- the modal must show the true number of rows that
        // will go, and the request must match what the engine will do.
        const bulkGroupBases = new Set();
        const expandedIds = new Set();
        ACTIVITY_DELETE_PENDING_IDS.forEach(id => {
          expandedIds.add(id);
          const gid = getActivityBulkGroupIds(id);
          if (gid.length > 0) {
            const gm = String(id).match(/^(ACT-.+-\d+)-\d+$/);
            if (gm) bulkGroupBases.add(gm[1]);
            gid.forEach(s => expandedIds.add(s));
          }
        });
        ACTIVITY_DELETE_PENDING_IDS = Array.from(expandedIds);

        const modal = document.getElementById("activity-delete-security-modal");
        if (!modal) {
          console.error("Modal #activity-delete-security-modal not found in DOM!");
          return;
        }

        const alertEl = document.getElementById("activity-delete-confirm-alert");
        if (alertEl) alertEl.innerHTML = "";
        const capInput = document.getElementById("activity-delete-captcha-input");
        if (capInput) capInput.value = "";
        const pwdInput = document.getElementById("activity-delete-confirm-password");
        if (pwdInput) pwdInput.value = "";

        const n = ACTIVITY_DELETE_PENDING_IDS.length;
        const countEl = document.getElementById("activity-delete-count-text");
        if (countEl) countEl.innerText = `${n} activity log entr${n === 1 ? 'y' : 'ies'}`;

        // R47: warn up front when a bulk entry is involved -- "1 entry"
        // silently becoming 3 deletions was exactly the reported bug.
        const bulkWarnEl = document.getElementById("activity-delete-bulk-warning");
        if (bulkWarnEl) bulkWarnEl.style.display = bulkGroupBases.size > 0 ? "inline" : "none";

        // Detect whether any selected entry is a Club Approval, to show
        // the cascade-deletion warning up front rather than as a surprise.
        const cache = ALL_ACTIVITIES_CACHE || [];
        const targetActs = cache.filter(a => ACTIVITY_DELETE_PENDING_IDS.includes(a.activity_id));
        const hasApproval = targetActs.some(a =>
          a.support_type === "Club Approval" ||
          (a.activity_id && a.activity_id.startsWith(`ACT-PRIORITY-${CURRENT_EMP_ID}`))
        );
        const cascadeWarnEl = document.getElementById("activity-delete-cascade-warning");
        if (cascadeWarnEl) cascadeWarnEl.style.display = hasApproval ? "inline" : "none";

        const listEl = document.getElementById("activity-delete-target-list");
        if (listEl) {
          listEl.innerHTML = ACTIVITY_DELETE_PENDING_IDS.map(id => {
            const match = targetActs.find(a => a.activity_id === id);
            const isApproval = match && match.support_type === "Club Approval";
            const clubTag = match && match.club_id ? ` — Club: ${escapeHtml(match.club_id)}${isApproval ? ' (will be cascade-deleted)' : ''}` : '';
            const gm = String(id).match(/^(ACT-.+-\d+)-\d+$/);
            const bulkTag = (gm && bulkGroupBases.has(gm[1])) ? ' (bulk entry — deleted together)' : '';
            return `<li>${escapeHtml(id)}${clubTag}${bulkTag}</li>`;
          }).join("");
        }

        const confirmBtn = document.getElementById("btn-confirm-activity-delete");
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = `<span>🗑</span> Confirm Permanent Deletion →`;
        }

        modal.style.display = "flex";
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.opacity = "1";
        modal.style.visibility = "visible";
        modal.style.zIndex = "var(--z-modal-confirm)";
        ndliModalOpened(modal);

        generateActivityDeleteCaptchaCode();

        setTimeout(() => {
          if (capInput) capInput.focus();
        }, 150);
      } catch (err) {
        console.error("Error in openActivityDeleteSecurityModal:", err);
        UI.toast("Security confirmation error: " + err.message, { type: "danger" });
      }
    }

    function closeActivityDeleteSecurityModal() {
      const modal = document.getElementById("activity-delete-security-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.opacity = "";
        modal.style.visibility = "";
        ndliModalClosed(modal);
      }
      ACTIVITY_DELETE_PENDING_IDS = [];
    }

    function generateActivityDeleteCaptchaCode() {
      const canvas = document.getElementById("activity-delete-captcha-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
      let code = "";
      for (let i = 0; i < 5; i++) {
        code += chars.charAt(Math.floor(Math.random() * chars.length));
      }
      ACTIVITY_DELETE_CAPTCHA_CODE = code;

      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const colors = ["#38bdf8", "#4ade80", "#facc15", "#f472b6", "#a78bfa", "#fdba74"];
      for (let i = 0; i < 5; i++) {
        ctx.strokeStyle = colors[i % colors.length];
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(Math.random() * canvas.width, Math.random() * canvas.height);
        ctx.bezierCurveTo(
          Math.random() * canvas.width, Math.random() * canvas.height,
          Math.random() * canvas.width, Math.random() * canvas.height,
          Math.random() * canvas.width, Math.random() * canvas.height
        );
        ctx.stroke();
      }

      for (let i = 0; i < 28; i++) {
        ctx.fillStyle = colors[Math.floor(Math.random() * colors.length)];
        ctx.beginPath();
        ctx.arc(Math.random() * canvas.width, Math.random() * canvas.height, 1.2, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.font = "bold 22px 'Courier New', monospace";
      ctx.textBaseline = "middle";
      const startX = 14;
      const spacing = 26;
      for (let i = 0; i < code.length; i++) {
        ctx.save();
        const charX = startX + (i * spacing);
        const charY = canvas.height / 2;
        ctx.translate(charX, charY);
        ctx.rotate((Math.random() - 0.5) * 0.3);
        ctx.fillStyle = colors[i % colors.length];
        ctx.fillText(code[i], 0, 0);
        ctx.restore();
      }
    }

    function toggleActivityDeletePasswordVisibility() {
      const pwd = document.getElementById("activity-delete-confirm-password");
      if (pwd) {
        pwd.type = pwd.type === "password" ? "text" : "password";
      }
    }

    async function confirmActivityDeletion() {
      if (!ACTIVITY_DELETE_PENDING_IDS || ACTIVITY_DELETE_PENDING_IDS.length === 0) {
        showAlert("activity-delete-confirm-alert", "No pending deletion found. Please retry.", "danger");
        return;
      }

      const capInput = document.getElementById("activity-delete-captcha-input");
      const enteredCap = capInput ? capInput.value.trim().toUpperCase() : "";
      const pwdInput = document.getElementById("activity-delete-confirm-password");
      const enteredPwd = pwdInput ? pwdInput.value.trim() : "";

      if (!enteredCap && !enteredPwd) {
        showAlert("activity-delete-confirm-alert", "Security confirmation required: Please type the CAPTCHA code above OR enter your login password.", "danger");
        return;
      }

      const confirmBtn = document.getElementById("btn-confirm-activity-delete");
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = `<span>⏳</span> Verifying Security & Deleting...`;
      }

      if (enteredPwd) {
        try {
          const verifyRes = await apiRequest("/api/auth/verify-password", "POST", {
            user_id: CURRENT_EMP_ID,
            password: enteredPwd
          });
          if (!verifyRes.ok) {
            showAlert("activity-delete-confirm-alert", `Security verification failed: ${verifyRes.data.message || 'Incorrect password.'}`, "danger");
            if (confirmBtn) {
              confirmBtn.disabled = false;
              confirmBtn.innerHTML = `<span>🗑</span> Confirm Permanent Deletion →`;
            }
            return;
          }
        } catch (e) {
          showAlert("activity-delete-confirm-alert", `Password verification error: ${e.message}`, "danger");
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<span>🗑</span> Confirm Permanent Deletion →`;
          }
          return;
        }
      } else if (enteredCap) {
        if (enteredCap !== ACTIVITY_DELETE_CAPTCHA_CODE) {
          showAlert("activity-delete-confirm-alert", "Incorrect CAPTCHA code entered. Please try again or use your password.", "danger");
          generateActivityDeleteCaptchaCode();
          if (capInput) capInput.value = "";
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<span>🗑</span> Confirm Permanent Deletion →`;
          }
          return;
        }
      }

      // Security passed -> Execute deletion
      try {
        const res = await apiRequest("/api/employee/activity/delete", "POST", {
          emp_id: CURRENT_EMP_ID,
          activity_ids: ACTIVITY_DELETE_PENDING_IDS
        });

        if (res.ok && res.data && res.data.success) {
          closeActivityDeleteSecurityModal();
          showAlert("activity-tab-alert", res.data.message || "Activity log entries deleted.", "success");
          SELECTED_ACTIVITY_IDS.clear();
          loadEmployeeQuota();
          loadEmployeeActivities(true);
          performUniversalSearch(document.getElementById("search-input").value, true);
        } else {
          showAlert("activity-delete-confirm-alert", `Deletion failed: ${(res.data && res.data.message) || 'Unknown error.'}`, "danger");
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<span>🗑</span> Confirm Permanent Deletion →`;
          }
        }
      } catch (err) {
        showAlert("activity-delete-confirm-alert", `Deletion failed: ${err.message}`, "danger");
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = `<span>🗑</span> Confirm Permanent Deletion →`;
        }
      }
    }

