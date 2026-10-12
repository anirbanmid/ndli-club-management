    // =============================================================
    // RENEWAL WORKFLOW: SECURITY CONFIRMATION & CERTIFICATE ENGINE
    // =============================================================

    // Intercept "Renewal Approved": Check prerequisite conditions and open Security Confirmation Modal
    async function handleRenewalApproved(e) {
      if (e) e.preventDefault();
      const clubId = document.getElementById("edit-club-id").value;
      const chk = document.getElementById("renew-check-conditions");
      if (chk && !chk.checked) {
        showAlert("modal-alert", "Please verify that the required renewal conditions have been fulfilled by the club before approving.", "danger");
        return;
      }

      // Retrieve target club
      let targetClub = CURRENT_ACTIVE_CLUB;
      if (!targetClub || targetClub.club_id !== clubId) {
        if (CURRENT_SEARCH_RESULTS && CURRENT_SEARCH_RESULTS.length) {
          targetClub = CURRENT_SEARCH_RESULTS.find(c => c.club_id === clubId);
        }
      }
      if (!targetClub) {
        targetClub = {
          club_id: clubId,
          institution_name: document.getElementById("edit-inst-name").value || clubId,
          state: document.getElementById("edit-state").value || "",
          zone: document.getElementById("edit-zone").value || "",
          reg_no: (document.getElementById("edit-reg-no") ? document.getElementById("edit-reg-no").value.trim() : "") || "",
          date_of_approval: document.getElementById("modal-date-of-approval-full") ? document.getElementById("modal-date-of-approval-full").innerText : "",
          renewal_date: document.getElementById("modal-upcoming-renewal") ? document.getElementById("modal-upcoming-renewal").innerText : ""
        };
      }

      // Open Second-Layer Security Confirmation Modal
      openRenewalSecurityModal(targetClub);
    }

    // Opens Second-Layer Security Confirmation Modal with target club summary & CAPTCHA
    function openRenewalSecurityModal(club) {
      try {
        console.log("[NDLI Renewal] Opening Security Confirmation Modal for:", club);
        RENEWAL_PENDING_CLUB = club;
        const modal = document.getElementById("renewal-security-modal");
        if (!modal) {
          console.error("Modal #renewal-security-modal not found in DOM!");
          return;
        }

        const alertEl = document.getElementById("sec-confirm-alert");
        if (alertEl) alertEl.innerHTML = "";
        const capInput = document.getElementById("captcha-input");
        if (capInput) capInput.value = "";
        const pwdInput = document.getElementById("sec-confirm-password");
        if (pwdInput) pwdInput.value = "";

        const instEl = document.getElementById("sec-confirm-inst-name");
        if (instEl) instEl.innerText = (club && club.institution_name) || (club && club.club_id) || "NDLI Club";

        const idsEl = document.getElementById("sec-confirm-ids");
        if (idsEl) idsEl.innerText = `${(club && club.club_id) || '-'} | Reg No: ${(club && club.reg_no) || 'Pending'}`;

        const doaEl = document.getElementById("sec-confirm-doa");
        if (doaEl) {
          const rawDoa = (club && (club.date_of_approval || club.submission_timestamp)) || "";
          doaEl.innerText = rawDoa ? (typeof formatDateDisplay === "function" ? formatDateDisplay(rawDoa) : String(rawDoa).split("T")[0]) : "Inception date";
        }

        const newRenEl = document.getElementById("sec-confirm-new-renewal");
        if (newRenEl) {
          const rawDoa = (club && (club.date_of_approval || club.submission_timestamp)) || "";
          const rawLrd = (club && club.last_renewal_date) || "";
          let nextRen = "+1 Year Extended";
          try {
            if (typeof calculateNextRenewalDate === "function") {
              nextRen = calculateNextRenewalDate(rawDoa, new Date().toISOString());
            }
          } catch (e) {
            console.warn("Could not calculate next renewal date:", e);
          }
          newRenEl.innerText = `${nextRen} (+1 Year Extension)`;
        }

        const confirmBtn = document.getElementById("btn-confirm-renewal-approval");
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = `<span>✓</span> Authorize & Confirm Renewal Approval →`;
        }

        // CRITICAL: Must add .active and .open classes and set inline opacity/visibility
        // so .modal-overlay rules don't hide it with opacity: 0 and visibility: hidden
        modal.style.display = "flex";
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.opacity = "1";
        modal.style.visibility = "visible";
        modal.style.zIndex = "var(--z-modal-security)";
        ndliModalOpened(modal);

        generateCaptchaCode();

        setTimeout(() => {
          if (capInput) capInput.focus();
        }, 150);
      } catch (err) {
        console.error("Error in openRenewalSecurityModal:", err);
        UI.toast("Security confirmation error: " + err.message, { type: "danger" });
      }
    }

    function closeRenewalSecurityModal() {
      const modal = document.getElementById("renewal-security-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.opacity = "";
        modal.style.visibility = "";
        ndliModalClosed(modal);
      }
      RENEWAL_PENDING_CLUB = null;
    }

    // Generates 5-character high-contrast alphanumeric CAPTCHA
    function generateCaptchaCode() {
      const canvas = document.getElementById("captcha-canvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
      let code = "";
      for (let i = 0; i < 5; i++) {
        code += chars.charAt(Math.floor(Math.random() * chars.length));
      }
      CURRENT_CAPTCHA_CODE = code;

      // Dark slate background
      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Squiggle lines
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

      // Noise dots
      for (let i = 0; i < 28; i++) {
        ctx.fillStyle = colors[Math.floor(Math.random() * colors.length)];
        ctx.beginPath();
        ctx.arc(Math.random() * canvas.width, Math.random() * canvas.height, 1.2, 0, Math.PI * 2);
        ctx.fill();
      }

      // Characters
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

    function toggleSecPasswordVisibility() {
      const pwd = document.getElementById("sec-confirm-password");
      if (pwd) {
        pwd.type = pwd.type === "password" ? "text" : "password";
      }
    }

    // Submits security authorization and executes renewal approval
    async function confirmRenewalApproval() {
      if (!RENEWAL_PENDING_CLUB) {
        showAlert("sec-confirm-alert", "No pending renewal found. Please retry.", "danger");
        return;
      }

      const capInput = document.getElementById("captcha-input");
      const enteredCap = capInput ? capInput.value.trim().toUpperCase() : "";
      const pwdInput = document.getElementById("sec-confirm-password");
      const enteredPwd = pwdInput ? pwdInput.value.trim() : "";

      if (!enteredCap && !enteredPwd) {
        showAlert("sec-confirm-alert", "Security confirmation required: Please type the CAPTCHA code above OR enter your login password.", "danger");
        return;
      }

      const confirmBtn = document.getElementById("btn-confirm-renewal-approval");
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = `<span>⏳</span> Verifying Security & Authorizing...`;
      }

      // Validate Password if provided
      if (enteredPwd) {
        try {
          const verifyRes = await apiRequest("/api/auth/verify-password", "POST", {
            user_id: CURRENT_EMP_ID,
            password: enteredPwd
          });
          if (!verifyRes.ok) {
            showAlert("sec-confirm-alert", `Security verification failed: ${verifyRes.data.message || 'Incorrect password.'}`, "danger");
            if (confirmBtn) {
              confirmBtn.disabled = false;
              confirmBtn.innerHTML = `<span>✓</span> Authorize & Confirm Renewal Approval →`;
            }
            return;
          }
        } catch (e) {
          showAlert("sec-confirm-alert", `Password verification error: ${e.message}`, "danger");
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<span>✓</span> Authorize & Confirm Renewal Approval →`;
          }
          return;
        }
      } else if (enteredCap) {
        // Validate CAPTCHA
        if (enteredCap !== CURRENT_CAPTCHA_CODE) {
          showAlert("sec-confirm-alert", "Incorrect CAPTCHA code entered. Please try again or use your password.", "danger");
          generateCaptchaCode();
          if (capInput) capInput.value = "";
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<span>✓</span> Authorize & Confirm Renewal Approval →`;
          }
          return;
        }
      }

      // Security passed -> Execute Renewal in Master Database
      const clubId = RENEWAL_PENDING_CLUB.club_id;
      const payload = {
        emp_id: CURRENT_EMP_ID,
        club_id: clubId
      };

      try {
        const res = await apiRequest("/api/clubs/renew", "POST", payload);
        if (res.ok && res.data && res.data.club) {
          const updated = res.data.club;
          const newLrd = updated.last_renewal_date;
          const newRen = updated.renewal_date;
          const formattedLrd = typeof formatLocalTimestamp === "function" ? formatLocalTimestamp(newLrd) : newLrd;

          closeRenewalSecurityModal();

          showAlert("modal-alert", `★ Registration Renewal Approved! Last Renewal Date logged as ${formattedLrd}. Upcoming renewal due date set to ${newRen} (+1 Year).`, "success");

          const lrdEl = document.getElementById("modal-last-renewal-date");
          const lrdFullEl = document.getElementById("modal-last-renewal-date-full");
          const upEl = document.getElementById("modal-upcoming-renewal");
          const statusEl = document.getElementById("modal-renewal-validity-status");

          if (lrdEl) lrdEl.innerText = typeof formatDateDisplay === "function" ? formatDateDisplay(newLrd) : (newLrd ? newLrd.split("T")[0] : "-");
          if (lrdFullEl) lrdFullEl.innerText = formattedLrd;
          if (upEl) upEl.innerText = newRen;
          if (statusEl) {
            statusEl.className = "pill pill-success";
            statusEl.innerText = "🟢 Active Validity (Renewed)";
          }

          CURRENT_ACTIVE_CLUB = updated;

          loadEmployeeQuota();
          loadEmployeeActivities(true);
          performUniversalSearch(document.getElementById("search-input").value, true);

          // AUTOMATICALLY OPEN RENEWAL CERTIFICATE GENERATION & DOWNLOAD TERMINAL
          openCertificateTerminal(updated);
        } else {
          showAlert("sec-confirm-alert", `Renewal failed: ${res.data.message || 'Error renewing.'}`, "danger");
          if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `<span>✓</span> Authorize & Confirm Renewal Approval →`;
          }
        }
      } catch (err) {
        showAlert("sec-confirm-alert", `Renewal failed: ${err.message}`, "danger");
        if (confirmBtn) {
          confirmBtn.disabled = false;
          confirmBtn.innerHTML = `<span>✓</span> Authorize & Confirm Renewal Approval →`;
        }
      }
    }

