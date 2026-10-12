    // SEC B: Open SEC C Form
    let SEC_C_MODE = "new";

    function applySecCMode() {
      const isImport = SEC_C_MODE === "import";
      const importFields = document.getElementById("sec-c-import-fields");
      const autoDates = document.getElementById("sec-c-auto-dates");
      const badge = document.getElementById("sec-c-mode-badge");
      if (importFields) importFields.style.display = isImport ? "block" : "none";
      if (autoDates) autoDates.style.display = isImport ? "none" : "grid";
      if (badge) {
        badge.textContent = isImport
          ? "IMPORT MODE — historical dates editable (legacy club record)"
          : "NEW CLUB MODE — dates auto-captured on submit";
        badge.style.background = isImport ? "#FDE68A" : "#D1FAE5";
        badge.style.color = isImport ? "#92400E" : "#065F46";
      }
      const btn = document.querySelector("#sec-c-form button[type='submit']");
      if (btn) {
        btn.innerHTML = isImport
          ? "<span>📥</span> Import Club Record (Priority Activity)"
          : "<span>★</span> Submit & Approve Club (Priority Activity)";
      }
      const todayStr = new Date().toISOString().split("T")[0];
      ["c-formation-date", "c-last-renewal-date"].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.max = todayStr;
      });
    }

    // R24: derived preview — upcoming renewal = (last renewal || formation) + 1 year
    function updateImportPreview() {
      const f = document.getElementById("c-formation-date");
      const l = document.getElementById("c-last-renewal-date");
      const p = document.getElementById("c-upcoming-preview");
      if (!p) return;
      const anchorStr = (l && l.value) ? l.value : (f && f.value ? f.value : "");
      if (!anchorStr || !/^\d{4}-\d{2}-\d{2}$/.test(anchorStr)) {
        p.value = "Select formation / last renewal date";
        return;
      }
      const anchor = new Date(anchorStr + "T00:00:00Z");
      if (isNaN(anchor.getTime())) {
        p.value = "Select formation / last renewal date";
        return;
      }
      anchor.setUTCFullYear(anchor.getUTCFullYear() + 1);
      p.value = anchor.toISOString().split("T")[0] + " (+1 Year)";
    }

    function toggleSecC(mode) {
      const container = document.getElementById("sec-c-card");
      if (container) {
        if (mode === "import" || mode === "new") {
          SEC_C_MODE = mode;
          container.classList.add("open");
        } else {
          container.classList.toggle("open");
        }
        if (container.classList.contains("open")) {
          applySecCMode();
          container.scrollIntoView({ behavior: 'smooth' });
          const cidInput = document.getElementById("c-club-id");
          if (!cidInput.value) {
            // Club ID is a whole number per client requisition (digits only)
            cidInput.value = String(Math.floor(1000 + Math.random() * 9000));
          }
          const renInput = document.getElementById("c-renewal-display") || document.getElementById("c-renewal");
          if (renInput && typeof calculateNextRenewalDate === "function") {
            renInput.value = `${calculateNextRenewalDate(new Date().toISOString(), null)} (+1 Year Initial Validity)`;
          }
          // Ensure SEC C State dropdown is populated immediately upon opening
          const stateEl = document.getElementById("c-state") || document.getElementById("sec-c-state");
          if (stateEl && stateEl.options.length <= 1) {
            populateStateSelect("c-state");
            loadStates();
          }
        }
      }
    }

    // SEC A Support Type Change & Bulk Call Display
    function handleSupportTypeChange() {
      const typeEl = document.getElementById("support-type");
      const bulkGroup = document.getElementById("bulk-calls-group");
      const countInput = document.getElementById("support-count");
      const submitBtn = document.getElementById("btn-submit-sec-a");

      if (!typeEl || !bulkGroup) return;

      const isPhoneRemote = typeEl.value === "Phone call and remote assistance";
      if (isPhoneRemote) {
        bulkGroup.style.display = "block";
        if (countInput && (!countInput.value || parseInt(countInput.value) < 1)) {
          countInput.value = "1";
        }
        updateSecASubmitButtonLabel();
      } else {
        bulkGroup.style.display = "none";
        if (countInput) countInput.value = "1";
        if (submitBtn) {
          submitBtn.innerHTML = `<span>✓</span> Log Support Activity (Real-Time)`;
        }
      }
    }

    function updateSecASubmitButtonLabel() {
      const typeEl = document.getElementById("support-type");
      const countInput = document.getElementById("support-count");
      const submitBtn = document.getElementById("btn-submit-sec-a");
      if (!typeEl || !countInput || !submitBtn) return;

      if (typeEl.value === "Phone call and remote assistance") {
        const val = parseInt(countInput.value) || 1;
        if (val > 1) {
          submitBtn.innerHTML = `<span>⚡</span> Log ${val} Support Calls in Bulk (At Once)`;
        } else {
          submitBtn.innerHTML = `<span>✓</span> Log Support Activity (Real-Time)`;
        }
      } else {
        submitBtn.innerHTML = `<span>✓</span> Log Support Activity (Real-Time)`;
      }
    }

    // SEC A Submit
    async function handleSecASubmit(e) {
      e.preventDefault();
      const supportType = document.getElementById("support-type").value;
      const clubId = document.getElementById("support-club-id").value.trim();
      const notes = document.getElementById("support-notes").value.trim();

      let count = 1;
      if (supportType === "Phone call and remote assistance") {
        const countInput = document.getElementById("support-count");
        if (countInput) {
          count = parseInt(countInput.value) || 1;
          if (count < 1) count = 1;
          if (count > 100) count = 100;
        }
      }

      const payload = {
        emp_id: CURRENT_EMP_ID,
        support_type: supportType,
        club_id: clubId,
        notes: notes,
        count: count
      };

      const res = await apiRequest("/api/activity/log", "POST", payload);
      if (res.ok) {
        const localNow = new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
        const successMsg = count > 1
          ? `✓ Bulk Success: ${count} Phone call & remote assistance entries recorded in one go at ${localNow}!`
          : `Support activity logged successfully at ${localNow}!`;
        showAlert("global-alert", successMsg, "success");
        document.getElementById("sec-a-form").reset();
        handleSupportTypeChange();
        loadEmployeeQuota();
        loadEmployeeActivities(true);
      } else {
        showAlert("global-alert", `Error: ${res.data.message || 'Could not log activity.'}`, "danger");
      }
    }

    // SEC C Submit
    async function handleSecCSubmit(e) {
      e.preventDefault();
      const clubId = document.getElementById("c-club-id").value.trim().toUpperCase();
      const regNo = document.getElementById("c-reg-no").value.trim();
      const instName = document.getElementById("c-inst-name").value.trim();
      const state = document.getElementById("c-state").value;
      const zone = document.getElementById("c-zone").value;
      const patron = document.getElementById("c-patron").value.trim();
      const president = document.getElementById("c-president").value.trim();
      const secretary = document.getElementById("c-secretary").value.trim();

      if (!clubId || !regNo || !instName || !state || !patron || !president || !secretary) {
        showAlert("global-alert", "Please fill in all required fields marked with *.", "danger");
        return;
      }

      // Client requisition (2026-09-26): Club ID is a WHOLE NUMBER — digits only.
      if (!/^[0-9]{1,15}$/.test(clubId)) {
        showAlert("global-alert", "⚠ Club ID must be a whole number (digits only, e.g. 2051) as per client requisition. No letters, spaces or symbols.", "danger");
        return;
      }

      // R24 import mode: client-side historical date validation (server re-validates).
      const isImport = SEC_C_MODE === "import";
      let formation = "";
      let lastRenewal = "";
      if (isImport) {
        const fEl = document.getElementById("c-formation-date");
        const lEl = document.getElementById("c-last-renewal-date");
        formation = (fEl && fEl.value ? fEl.value : "").trim();
        lastRenewal = (lEl && lEl.value ? lEl.value : "").trim();
        const todayStr = new Date().toISOString().split("T")[0];
        if (!formation) {
          showAlert("global-alert", "Please enter the actual Date of Approval / Formation date of the club (from the old register).", "danger");
          return;
        }
        if (formation < "2019-01-01") {
          showAlert("global-alert", "⚠ Date of Approval cannot be earlier than 2019-01-01.", "danger");
          return;
        }
        if (formation > todayStr) {
          showAlert("global-alert", "⚠ Date of Approval cannot be in the future.", "danger");
          return;
        }
        if (lastRenewal) {
          if (lastRenewal < formation) {
            showAlert("global-alert", "⚠ Last Renewal Date cannot be earlier than the Date of Approval.", "danger");
            return;
          }
          if (lastRenewal > todayStr) {
            showAlert("global-alert", "⚠ Last Renewal Date cannot be in the future.", "danger");
            return;
          }
        }
      }

      const payload = {
        emp_id: CURRENT_EMP_ID,
        club_id: clubId,
        reg_no: regNo,
        institution_name: instName,
        state: state,
        zone: zone,
        patron_email: patron,
        president_email: president,
        secretary_email: secretary,
        record_mode: SEC_C_MODE
      };
      if (isImport) {
        payload.date_of_approval = formation;
        payload.last_renewal_date = lastRenewal;
      }

      const res = await apiRequest("/api/clubs/create", "POST", payload);
      if (res.ok) {
        const createdClub = res.data.club || {};
        const approvalDate = createdClub.date_of_approval || "Logged Now";
        const initialValidity = createdClub.renewal_date || "1 Year";
        if (isImport) {
          showAlert("global-alert", `★ Priority Success! Legacy NDLI Club "${instName}" (${clubId}) imported with its true history. Date of Approval: ${approvalDate}. Last Renewal: ${createdClub.last_renewal_date || "(none)"}. Next renewal due: ${initialValidity}.`, "success");
        } else {
          showAlert("global-alert", `★ Priority Success! NDLI Club "${instName}" (${clubId}) approved! Date of Approval logged: ${approvalDate}. Initial validity granted until: ${initialValidity}.`, "success");
        }
        document.getElementById("sec-c-form").reset();
        document.getElementById("sec-c-card").classList.remove("open");
        loadEmployeeQuota();
        loadEmployeeActivities(true);
        performUniversalSearch("", true);
      } else {
        const errorMsg = res.data.validation_errors ? res.data.validation_errors.join("<br>") : (res.data.message || "Failed to approve club.");
        showAlert("global-alert", `Validation Error:<br>${errorMsg}`, "danger");
      }
    }

