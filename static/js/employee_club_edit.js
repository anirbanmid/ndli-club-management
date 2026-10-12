    // Modal Handlers
    let CURRENT_ACTIVE_CLUB = null;
    let RENEWAL_PENDING_CLUB = null;
    let CURRENT_CAPTCHA_CODE = "";
    let ACTIVE_CERT_CLUB = null;

    function openEditModal(club) {
      CURRENT_ACTIVE_CLUB = club;
      document.getElementById("modal-club-id").innerText = `${club.institution_name} (${club.club_id})`;
      // R3: status pill semantic mapping (approved/active → success, pending/expiring
      // → warning, overdue/expired/unresolved/blocked/suspended → danger,
      // inactive/unknown → outline). Display-only; default "Approved" path is unchanged.
      const modalStatusText = club.status || "Approved";
      const modalStatusEl = document.getElementById("modal-status");
      if (modalStatusEl) {
        modalStatusEl.innerText = modalStatusText;
        modalStatusEl.className = "pill " + (
          /^(pending|expiring)/i.test(modalStatusText) ? "pill-warning" :
          /^(overdue|expired|unresolved|blocked|suspended|reject)/i.test(modalStatusText) ? "pill-danger" :
          /^(inactive)/i.test(modalStatusText) ? "pill-outline" :
          /^(approved|active)/i.test(modalStatusText) ? "pill-success" : "pill-outline");
      }
      document.getElementById("edit-club-id").value = club.club_id;
      document.getElementById("edit-inst-name").value = club.institution_name;
      const regNoEl = document.getElementById("edit-reg-no");
      if (regNoEl) regNoEl.value = club.reg_no || "";
      const editStateEl = document.getElementById("edit-state");
      if (editStateEl && editStateEl.options.length <= 1) {
        populateStateSelect("edit-state");
      }
      if (editStateEl) editStateEl.value = club.state || "";
      document.getElementById("edit-zone").value = club.zone;
      const noteEl = document.getElementById("issue-note-input");
      if (noteEl) noteEl.value = "";
      document.getElementById("edit-patron").value = club.patron_email;
      document.getElementById("edit-president").value = club.president_email;
      document.getElementById("edit-secretary").value = club.secretary_email;

      // Date of Approval display
      const doa = club.date_of_approval || club.submission_timestamp || "";
      const doaShort = doa ? (typeof formatDateDisplay === "function" ? formatDateDisplay(doa) : doa.split("T")[0]) : "-";
      const doaFull = doa ? (typeof formatLocalTimestamp === "function" ? formatLocalTimestamp(doa) : doa) : "Inception timestamp";
      const doaEl = document.getElementById("modal-date-of-approval");
      const doaFullEl = document.getElementById("modal-date-of-approval-full");
      if (doaEl) doaEl.innerText = doaShort;
      if (doaFullEl) doaFullEl.innerText = doaFull;

      // Last Renewal Date display
      const lrd = club.last_renewal_date || "";
      const lrdEl = document.getElementById("modal-last-renewal-date");
      const lrdFullEl = document.getElementById("modal-last-renewal-date-full");
      if (lrd && lrd !== "-") {
        const lrdShort = typeof formatDateDisplay === "function" ? formatDateDisplay(lrd) : lrd.split("T")[0];
        const lrdFull = typeof formatLocalTimestamp === "function" ? formatLocalTimestamp(lrd) : lrd;
        if (lrdEl) lrdEl.innerText = lrdShort;
        if (lrdFullEl) lrdFullEl.innerText = lrdFull;
      } else {
        if (lrdEl) lrdEl.innerText = "None (Initial)";
        if (lrdFullEl) lrdFullEl.innerText = "Not Renewed Yet (Initial Inception)";
      }

      // Upcoming Renewal Due Date display
      const upcomingRen = club.renewal_date || club.next_renewal_date || (typeof calculateNextRenewalDate === "function" ? calculateNextRenewalDate(doa, lrd) : "-");
      const upEl = document.getElementById("modal-upcoming-renewal");
      if (upEl) upEl.innerText = upcomingRen;

      // Status badge
      const todayStr = new Date().toISOString().split("T")[0];
      const statusEl = document.getElementById("modal-renewal-validity-status");
      if (statusEl) {
        if (upcomingRen && upcomingRen < todayStr) {
          statusEl.className = "pill pill-danger";
          statusEl.innerText = "🔴 Overdue - Renewal Required";
        } else if (upcomingRen) {
          const diffDays = Math.round((new Date(upcomingRen) - new Date(todayStr)) / (1000 * 60 * 60 * 24));
          if (diffDays <= 90) {
            statusEl.className = "pill pill-warning";
            statusEl.innerText = `🟡 Expiring in ${diffDays} days`;
          } else {
            statusEl.className = "pill pill-success";
            statusEl.innerText = "🟢 Active Validity";
          }
        }
      }

      document.getElementById("modal-alert").innerHTML = "";
      const editModalEl = document.getElementById("edit-modal");
      editModalEl.classList.add("active");
      ndliModalOpened(editModalEl);
    }

    function closeEditModal() {
      const editModalEl = document.getElementById("edit-modal");
      editModalEl.classList.remove("active");
      ndliModalClosed(editModalEl);
    }

    // Handle Club Update
    async function handleClubUpdate(e) {
      e.preventDefault();
      const clubId = document.getElementById("edit-club-id").value;
      const payload = {
        emp_id: CURRENT_EMP_ID,
        club_id: clubId,
        institution_name: document.getElementById("edit-inst-name").value.trim(),
        state: document.getElementById("edit-state").value,
        zone: document.getElementById("edit-zone").value,
        patron_email: document.getElementById("edit-patron").value.trim(),
        president_email: document.getElementById("edit-president").value.trim(),
        secretary_email: document.getElementById("edit-secretary").value.trim(),
        reg_no: document.getElementById("edit-reg-no").value.trim()
      };

      const res = await apiRequest("/api/clubs/update", "POST", payload);
      if (res.ok) {
        showAlert("modal-alert", "Club details updated and synchronized with Master DB!", "success");
        performUniversalSearch(document.getElementById("search-input").value, true);
        setTimeout(closeEditModal, 1500);
      } else {
        showAlert("modal-alert", `Update error: ${res.data.message || 'Failed to update club.'}`, "danger");
      }
    }

