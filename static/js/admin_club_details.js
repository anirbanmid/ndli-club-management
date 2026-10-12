    // =============================================================
    // CLUB DETAILS VIEW MODAL CONTROLLER
    // =============================================================
    // R25: context-aware back navigation for the details modal (register vs attention).
    let CLUB_DETAILS_RETURN = "attention";
    let CLUB_REGISTER_DATA = null;

    function clubDetailsBackLabel() {
      return (typeof CLUB_DETAILS_RETURN !== "undefined" && CLUB_DETAILS_RETURN === "register")
        ? "← Back to Club Register" : "← Back to Renewal Attention List";
    }

    function goBackFromClubDetails() {
      if (typeof CLUB_DETAILS_RETURN !== "undefined" && CLUB_DETAILS_RETURN === "register") {
        backToClubRegister();
      } else {
        backToAttentionList();
      }
    }

    async function openClubDetailsModal(clubId, returnTo) {
      if (!clubId) return;
      const cleanId = String(clubId).trim();
      if (!cleanId) return;
      CLUB_DETAILS_RETURN = (returnTo === "register") ? "register" : "attention";

      const modal = document.getElementById("club-details-modal");
      const attnModal = document.getElementById("renewal-attention-modal");

      // Instantly show the Club Details Modal with all active classes and flex display
      if (modal) {
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.display = "flex";
        ndliModalOpened(modal);
      }

      // Temporarily hide attention list to prevent modal overlap
      if (attnModal) {
        attnModal.classList.remove("active");
        attnModal.classList.remove("open");
        attnModal.style.display = "none";
      }

      let cachedClub = null;
      if (RENEWAL_ATTENTION_DATA && Array.isArray(RENEWAL_ATTENTION_DATA.clubs)) {
        cachedClub = RENEWAL_ATTENTION_DATA.clubs.find(c => (c.club_id || "").trim().toUpperCase() === cleanId.toUpperCase());
      }

      // If cached club record is available from attention dataset, render immediately for instant feedback
      if (cachedClub) {
        renderClubDetailsView(cachedClub);
      } else {
        const body = document.getElementById("club-details-body");
        if (body) {
          body.innerHTML = `
            <div style="text-align: center; padding: 3rem; color: var(--text-muted);">
              <div style="font-size: 2rem; margin-bottom: 0.5rem;">⏳</div>
              <p>Loading full properties for Club <strong>${escapeHtml(cleanId)}</strong>...</p>
            </div>
          `;
        }
      }

      // Fetch latest synced details from API
      try {
        const res = await apiRequest(`/api/clubs/details?club_id=${encodeURIComponent(cleanId)}`);
        if (res.ok && res.data && res.data.club) {
          renderClubDetailsView(res.data.club);
        } else if (!cachedClub) {
          const body = document.getElementById("club-details-body");
          if (body) {
            body.innerHTML = `
              <div style="padding: 1.5rem;">
                <div class="alert alert-danger">
                  <span>⚠️</span>
                  <div>Could not load club details for Club ID: <strong>${escapeHtml(cleanId)}</strong></div>
                </div>
                <div style="margin-top: 1rem; text-align: right;">
                  <button type="button" class="btn btn-outline btn-sm" onclick="backToAttentionList()">${clubDetailsBackLabel()}</button>
                  <button type="button" class="btn btn-primary btn-sm" onclick="closeClubDetailsModal()">Close</button>
                </div>
              </div>
            `;
          }
        }
      } catch (err) {
        console.error("Error fetching club details:", err);
        if (!cachedClub) {
          const body = document.getElementById("club-details-body");
          if (body) {
            body.innerHTML = `
              <div style="padding: 1.5rem;">
                <div class="alert alert-danger">
                  <span>⚠️</span>
                  <div>Network error fetching club properties.</div>
                </div>
                <div style="margin-top: 1rem; text-align: right;">
                  <button type="button" class="btn btn-outline btn-sm" onclick="backToAttentionList()">${clubDetailsBackLabel()}</button>
                  <button type="button" class="btn btn-primary btn-sm" onclick="closeClubDetailsModal()">Close</button>
                </div>
              </div>
            `;
          }
        }
      }
    }

    function closeClubDetailsModal(returnToList = false) {
      const modal = document.getElementById("club-details-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
      }
      if (returnToList) {
        const attnModal = document.getElementById("renewal-attention-modal");
        if (attnModal) {
          attnModal.classList.add("active");
          attnModal.classList.add("open");
          attnModal.style.display = "flex";
        }
      }
      // Focus return runs after the attention list is visible again so the
      // opener (a row inside that list) is focusable when we hand focus back.
      ndliModalClosed(modal);
    }

    function backToAttentionList() {
      // Context-aware (R25): when details were opened from the Club Register,
      // going back returns to the register instead of the attention list.
      if (typeof CLUB_DETAILS_RETURN !== "undefined" && CLUB_DETAILS_RETURN === "register") {
        backToClubRegister();
        return;
      }
      closeClubDetailsModal(true);
    }

    // R25: CLUB REGISTER — the admin portal's direct club list (user requisition
    // 2026-10-09): details + "Correct Historical Dates" were previously reachable
    // only via Renewal Attention. Opens from the Total NDLI Clubs KPI card.
    function renderClubRegisterList(rows) {
      const body = document.getElementById("club-register-body");
      if (!body) return;
      if (!rows || !rows.length) {
        body.innerHTML = '<div style="padding: 1.5rem; color: var(--text-muted); text-align: center;">No clubs found.</div>';
        return;
      }
      const trs = rows.map(function (c) {
        const cid = escapeHtml(String(c.club_id || ""));
        return "<tr>" +
          '<td style="font-family: monospace; padding: 0.4rem;">' + cid + "</td>" +
          '<td style="font-family: monospace; padding: 0.4rem;">' + escapeHtml(String(c.reg_no || "")) + "</td>" +
          '<td style="padding: 0.4rem;">' + escapeHtml(String(c.institution_name || "")) + "</td>" +
          '<td style="padding: 0.4rem; white-space: nowrap;">' + escapeHtml(String(c.state || "")) + ' <small style="color: var(--text-muted);">(' + escapeHtml(String(c.zone || "")) + ")</small></td>" +
          '<td style="font-family: monospace; white-space: nowrap; padding: 0.4rem;">' + escapeHtml(String(c.date_of_approval || c.submission_timestamp || "").split("T")[0]) + "</td>" +
          '<td style="font-family: monospace; white-space: nowrap; padding: 0.4rem;">' + (escapeHtml(String(c.last_renewal_date || "").split("T")[0]) || "-") + "</td>" +
          '<td style="font-family: monospace; white-space: nowrap; color: #15803d; font-weight: 600; padding: 0.4rem;">' + escapeHtml(String(c.renewal_date || c.next_renewal_date || "").split("T")[0]) + "</td>" +
          '<td style="padding: 0.4rem;"><span class="pill ' + clubStatusPillClass(c.status) + '">' + escapeHtml(String(c.status || "Approved")) + "</span></td>" +
          '<td style="text-align: right; padding: 0.4rem;"><button type="button" class="btn btn-outline btn-sm" onclick="openClubDetailsFromRegister(&quot;' + cid + '&quot;)">Open Details</button></td>' +
          "</tr>";
      }).join("");
      body.innerHTML =
        '<div style="overflow-x: auto;"><table style="width: 100%; border-collapse: collapse; font-size: 0.82rem;">' +
        '<thead><tr style="border-bottom: 2px solid var(--primary);">' +
        '<th style="text-align: left; padding: 0.45rem;">Club ID</th>' +
        '<th style="text-align: left; padding: 0.45rem;">Reg No</th>' +
        '<th style="text-align: left; padding: 0.45rem;">Institution</th>' +
        '<th style="text-align: left; padding: 0.45rem;">State / Zone</th>' +
        '<th style="text-align: left; padding: 0.45rem;">Date of Approval</th>' +
        '<th style="text-align: left; padding: 0.45rem;">Last Renewal</th>' +
        '<th style="text-align: left; padding: 0.45rem;">Upcoming Renewal</th>' +
        '<th style="text-align: left; padding: 0.45rem;">Status</th>' +
        '<th></th></tr></thead><tbody>' + trs + "</tbody></table></div>" +
        '<p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.6rem;">' +
        String(rows.length) + ' club(s) shown. "Open Details" shows full properties, including the admin "Correct Historical Dates" block.</p>';
    }

    function filterClubRegister(q) {
      const query = String(q || "").trim().toLowerCase();
      const rows = CLUB_REGISTER_DATA || [];
      if (!query) { renderClubRegisterList(rows); return; }
      renderClubRegisterList(rows.filter(function (c) {
        return [c.club_id, c.reg_no, c.institution_name, c.state, c.zone, c.status, c.approved_by_emp_id]
          .some(function (v) { return String(v || "").toLowerCase().indexOf(query) !== -1; });
      }));
    }

    async function openClubRegisterModal() {
      const modal = document.getElementById("club-register-modal");
      if (!modal) return;
      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      if (typeof ndliModalOpened === "function") ndliModalOpened(modal);
      const body = document.getElementById("club-register-body");
      if (body && !CLUB_REGISTER_DATA) {
        body.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--text-muted);">⏳ Loading club register...</div>';
      }
      try {
        const res = await apiRequest("/api/clubs/search?q=");
        const rows = (res && res.ok && res.data) ? (res.data.results || res.data.clubs || []) : [];
        CLUB_REGISTER_DATA = rows;
        const filterEl = document.getElementById("club-register-filter");
        renderClubRegisterList(rows);
        if (filterEl && filterEl.value) filterClubRegister(filterEl.value);
      } catch (e) {
        if (body) body.innerHTML = '<div class="alert alert-danger">Could not load the club register.</div>';
      }
    }

    function closeClubRegisterModal() {
      const modal = document.getElementById("club-register-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
      }
      if (typeof ndliModalClosed === "function") ndliModalClosed(modal);
    }

    function openClubDetailsFromRegister(clubId) {
      const regModal = document.getElementById("club-register-modal");
      if (regModal) {
        regModal.classList.remove("active");
        regModal.classList.remove("open");
        regModal.style.display = "none";
      }
      openClubDetailsModal(clubId, "register");
    }

    function backToClubRegister() {
      closeClubDetailsModal(false);
      openClubRegisterModal();
    }

    // Status-pill semantic map (Round-3 #8): positive/approved → pill-success,
    // danger (blocked/suspended) → pill-danger, inactive → pill-outline,
    // pending/unknown → pill-warning. Keeps pill classes untouched.
    function clubStatusPillClass(status) {
      const s = String(status || "Approved").toLowerCase();
      if (s === "approved" || s.indexOf("renewed") !== -1) return "pill-success";
      if (s === "blocked" || s === "suspended") return "pill-danger";
      if (s === "inactive") return "pill-outline";
      return "pill-warning";
    }

    // R24: Admin-only historical date correction — dedicated logged workflow.
    // POST /api/clubs/correct-dates validates (2019-01-01 <= DOA <= today,
    // DOA <= Last Renewal <= today), recomputes the upcoming renewal (+1y anchor)
    // and writes a "Data Correction" activity entry.
    async function submitClubDateCorrection(clubId) {
      const doaEl = document.getElementById("cd-date-of-approval");
      const lrdEl = document.getElementById("cd-last-renewal");
      const fb = document.getElementById("cd-feedback");
      const doa = doaEl && doaEl.value ? String(doaEl.value).trim() : "";
      const lrd = lrdEl && lrdEl.value ? String(lrdEl.value).trim() : "";
      const todayStr = new Date().toISOString().split("T")[0];
      const fail = function (msg) {
        if (fb) { fb.style.color = "#B91C1C"; fb.textContent = "⚠ " + msg; }
      };
      if (!clubId) return fail("Club ID missing — close and reopen the details view.");
      if (!doa) return fail("Date of Approval is required.");
      if (doa < "2019-01-01") return fail("Date of Approval cannot be earlier than 2019-01-01.");
      if (doa > todayStr) return fail("Date of Approval cannot be in the future.");
      if (lrd) {
        if (lrd < doa) return fail("Last Renewal Date cannot be earlier than the Date of Approval.");
        if (lrd > todayStr) return fail("Last Renewal Date cannot be in the future.");
      }
      try {
        const res = await apiRequest("/api/clubs/correct-dates", "POST", {
          club_id: clubId,
          date_of_approval: doa,
          last_renewal_date: lrd
        });
        if (res && res.ok && res.data && res.data.success) {
          if (fb) {
            fb.style.color = "#15803d";
            fb.textContent = "✓ " + (res.data.message || "Historical dates corrected.") +
              " Close and reopen the details view to refresh the cards.";
          }
        } else {
          const d = (res && res.data) || {};
          fail(d.validation_errors ? d.validation_errors.join(" ") : (d.message || "Correction failed."));
        }
      } catch (e) {
        fail("Request failed: " + e);
      }
    }

    function renderClubDetailsView(club) {
      const body = document.getElementById("club-details-body");
      if (!body || !club) return;

      try {
        const isOverdue = (club.days_diff !== null && club.days_diff !== undefined && club.days_diff < 0) || club.attention_type === "Overdue";
        const isExpiring = (club.days_diff !== null && club.days_diff !== undefined && club.days_diff >= 0 && club.days_diff <= 90) || club.attention_type === "Expiring Soon";

        let urgencyBadge = '<span class="pill pill-success">Normal Validity</span>';
        if (isOverdue) {
          const dOver = club.days_overdue || (club.days_diff !== null && club.days_diff !== undefined ? Math.abs(club.days_diff) : 0);
          urgencyBadge = `<span class="pill pill-danger">🔴 Overdue by ${dOver} days</span>`;
        } else if (isExpiring) {
          const dLeft = club.days_left !== undefined ? club.days_left : (club.days_diff !== null && club.days_diff !== undefined ? club.days_diff : 0);
          urgencyBadge = `<span class="pill pill-warning">🟡 ${dLeft === 0 ? 'Expires today' : `Expiring in ${dLeft} days`}</span>`;
        }

        const doaVal = club.date_of_approval || club.submission_timestamp || "";
        const estDateFormatted = (doaVal && typeof formatLocalTimestamp === "function")
          ? formatLocalTimestamp(doaVal)
          : (doaVal || "-");
        const estDateShort = doaVal
          ? (typeof formatDateDisplay === "function" ? formatDateDisplay(doaVal) : String(doaVal).split("T")[0].split(" ")[0])
          : "-";

        const lrdVal = club.last_renewal_date || "";
        const lastRenFormatted = (lrdVal && typeof formatLocalTimestamp === "function")
          ? formatLocalTimestamp(lrdVal)
          : (lrdVal || "None (Initial Inception)");
        const lastRenShort = lrdVal
          ? (typeof formatDateDisplay === "function" ? formatDateDisplay(lrdVal) : String(lrdVal).split("T")[0].split(" ")[0])
          : "None (Initial)";

        let nextRenewalDue = club.renewal_date || club.next_renewal_date || club.next_renewal_due_date || club.effective_renewal_date;
        if (!nextRenewalDue && typeof calculateNextRenewalDate === "function") {
          nextRenewalDue = calculateNextRenewalDate(doaVal, lrdVal);
        }
        if (!nextRenewalDue) nextRenewalDue = "-";

        const emailRecipients = [club.president_email, club.secretary_email].filter(Boolean).join(",");
        const mailtoUrl = emailRecipients
          ? `mailto:${emailRecipients}?subject=NDLI%20Club%20Renewal%20Notice%20-%20${encodeURIComponent(club.institution_name || '')}&body=Dear%20Club%20Officers,%0A%0AYour%20NDLI%20Club%20registration%20validity%20is%20${isOverdue ? 'overdue' : 'due%20soon'}%20(Expiry:%20${club.effective_renewal_date || nextRenewalDue}).%20Please%20log%20in%20to%20the%20NDLI%20Portal%20or%20contact%20your%20regional%20nodal%20officer%20for%20the%201-year%20annual%20renewal.%0A%0AOffice%20of%20NDLI,%20IIT%20Kharagpur`
          : "#";

        body.innerHTML = `
          <!-- Header -->
          <div style="border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.25rem;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.5rem;">
              <div>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                  <span class="badge-tag" style="background: var(--primary);">NDLI Club Profile</span>
                  <code style="font-size: 0.9rem; font-weight: 700; color: var(--primary);">${escapeHtml(club.club_id || '-')}</code>
                </div>
                <h2 style="font-size: 1.35rem; font-weight: 700; color: var(--primary); line-height: 1.3;">
                  ${escapeHtml(club.institution_name || '-')}
                </h2>
                <p style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.2rem;">
                  ${escapeHtml(club.state || '-')} • ${escapeHtml(club.zone || '-')} Zone
                </p>
              </div>
              <div style="display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center;">
                ${urgencyBadge}
                <span class="pill ${clubStatusPillClass(club.status)}">${escapeHtml(club.status || 'Approved')}</span>
              </div>
            </div>
          </div>

          <!-- 2-Column Property Grid -->
          <div class="grid-2" style="gap: 1rem; margin-bottom: 1.25rem;">
            <!-- Identification Card -->
            <div style="background: #f8fafc; border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem;">
              <h4 style="font-size: 0.88rem; font-weight: 700; color: var(--primary); margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
                <span>🆔</span> Club Identification & Geography
              </h4>
              <table style="width: 100%; font-size: 0.85rem;">
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0; width: 45%;">Club ID:</td>
                  <td><code style="font-weight: 700; color: var(--primary);">${escapeHtml(club.club_id || '-')}</code></td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">Registration No:</td>
                  <td><strong style="font-family: monospace;">${escapeHtml(club.reg_no || '-')}</strong></td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">Institution Name:</td>
                  <td><strong>${escapeHtml(club.institution_name || '-')}</strong></td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">State / UT:</td>
                  <td><strong>${escapeHtml(club.state || '-')}</strong></td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">Regional Zone:</td>
                  <td><span class="pill pill-primary" style="font-size: 0.75rem;">${escapeHtml(club.zone || '-')} Zone</span></td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">Account Status:</td>
                  <td><span class="pill ${clubStatusPillClass(club.status)}" style="font-size: 0.75rem;">${escapeHtml(club.status || 'Approved')}</span></td>
                </tr>
              </table>
            </div>

            <!-- Administration & Officers Card -->
            <div style="background: #f8fafc; border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem;">
              <h4 style="font-size: 0.88rem; font-weight: 700; color: var(--primary); margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
                <span>👤</span> Official Contacts & Approver
              </h4>
              <table style="width: 100%; font-size: 0.85rem;">
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0; width: 45%;">Approved By:</td>
                  <td><code>${escapeHtml(club.approved_by_emp_id || 'IIT KGP Master')}</code></td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">Patron E-Mail:</td>
                  <td>
                    ${club.patron_email ? `<a href="mailto:${encodeURIComponent(club.patron_email)}" style="color: var(--primary); text-decoration: underline; word-break: break-all;">${escapeHtml(club.patron_email)}</a>` : '-'}
                  </td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">President E-Mail:</td>
                  <td>
                    ${club.president_email ? `<a href="mailto:${encodeURIComponent(club.president_email)}" style="color: var(--primary); text-decoration: underline; word-break: break-all;">${escapeHtml(club.president_email)}</a>` : '-'}
                  </td>
                </tr>
                <tr>
                  <td style="color: var(--text-muted); padding: 0.35rem 0;">Secretary E-Mail:</td>
                  <td>
                    ${club.secretary_email ? `<a href="mailto:${encodeURIComponent(club.secretary_email)}" style="color: var(--primary); text-decoration: underline; word-break: break-all;">${escapeHtml(club.secretary_email)}</a>` : '-'}
                  </td>
                </tr>
              </table>
            </div>
          </div>

          <!-- Renewal & Registration Lifecycle Card -->
          <div style="background: #fffdf5; border: 1px solid #fde68a; border-radius: var(--radius); padding: 1.25rem; margin-bottom: 1.25rem;">
            <h4 style="font-size: 0.95rem; font-weight: 700; color: #92400e; margin-bottom: 0.85rem; display: flex; align-items: center; gap: 0.4rem;">
              <span>📅</span> Renewal Lifecycle (Automated 1-Year Cycle)
            </h4>

            <div class="grid-3" style="gap: 1rem;">
              <div style="background: #ffffff; padding: 0.85rem; border-radius: var(--radius); border: 1px solid #fef3c7;">
                <span style="font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; display: block;">Date of Approval</span>
                <strong style="font-size: 0.95rem; color: var(--primary); margin-top: 0.25rem; display: block; font-family: monospace;">
                  ${escapeHtml(estDateShort)}
                </strong>
                <small style="font-size: 0.72rem; color: var(--text-muted); display: block; margin-top: 0.2rem;">${escapeHtml(estDateFormatted)}</small>
              </div>

              <div style="background: #ffffff; padding: 0.85rem; border-radius: var(--radius); border: 1px solid #fef3c7;">
                <span style="font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; display: block;">Last Renewal Date</span>
                <strong style="font-size: 0.95rem; color: #b45309; margin-top: 0.25rem; display: block; font-family: monospace;">
                  ${escapeHtml(lastRenShort)}
                </strong>
                <small style="font-size: 0.72rem; color: var(--text-muted); display: block; margin-top: 0.2rem;">${escapeHtml(lastRenFormatted)}</small>
              </div>

              <div style="background: #ffffff; padding: 0.85rem; border-radius: var(--radius); border: 1px solid #bbf7d0;">
                <span style="font-size: 0.72rem; text-transform: uppercase; color: #166534; font-weight: 700; display: block;">Upcoming Renewal Due Date (Next Renewal Due Date)</span>
                <strong style="font-size: 1rem; color: #15803d; margin-top: 0.25rem; display: block; font-family: monospace;" id="club-details-next-renewal">
                  ${escapeHtml(nextRenewalDue)}
                </strong>
                <small style="font-size: 0.72rem; color: #15803d; display: block; margin-top: 0.2rem;">+1 Year automatically computed</small>
              </div>
            </div>

            <p style="font-size: 0.78rem; color: #78350f; margin-top: 0.85rem;">
              ℹ️ <em>Rule Applied: Initial 1-year registration validity is logged upon club creation (Date of Approval). On renewal approval, the employee checks conditions and clicks "Renewal Approved", instantly logging the timestamp as Last Renewal Date and calculating the upcoming renewal date (+1 year).</em>
            </p>

            <!-- R24: Admin-only historical date correction (dedicated, logged workflow) -->
            <div style="margin-top: 0.85rem; border: 1px dashed #D97706; border-radius: var(--radius); padding: 0.85rem; background: #FFFBEF;">
              <span style="font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; color: #92400E; font-weight: 700; display: block; margin-bottom: 0.55rem;">
                🛠 Admin: Correct Historical Dates (logged)
              </span>
              <div style="display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end;">
                <div style="flex: 1 1 180px;">
                  <label style="font-size: 0.72rem; font-weight: 700; color: var(--text-muted); display: block; margin-bottom: 0.25rem;" for="cd-date-of-approval">Date of Approval</label>
                  <input type="date" id="cd-date-of-approval" min="2019-01-01" max="${new Date().toISOString().split('T')[0]}" value="${escapeHtml(String(club.date_of_approval || club.submission_timestamp || '').split('T')[0])}" style="width: 100%; font-family: monospace; font-weight: 600; padding: 0.35rem 0.5rem; border: 1px solid #E5E7EB; border-radius: 8px;">
                </div>
                <div style="flex: 1 1 180px;">
                  <label style="font-size: 0.72rem; font-weight: 700; color: var(--text-muted); display: block; margin-bottom: 0.25rem;" for="cd-last-renewal">Last Renewal Date (optional)</label>
                  <input type="date" id="cd-last-renewal" min="2019-01-01" max="${new Date().toISOString().split('T')[0]}" value="${escapeHtml(String(club.last_renewal_date || '').split('T')[0])}" style="width: 100%; font-family: monospace; font-weight: 600; padding: 0.35rem 0.5rem; border: 1px solid #E5E7EB; border-radius: 8px;">
                </div>
                <button type="button" class="btn btn-primary btn-sm" onclick="submitClubDateCorrection('${escapeHtml(String(club.club_id || ''))}')">
                  ✓ Correct Dates
                </button>
              </div>
              <small id="cd-feedback" style="font-size: 0.72rem; color: #92400E; display: block; margin-top: 0.5rem;">
                For legacy clubs whose real formation / renewal dates were recorded wrongly. Rules: 2019-01-01 ≤ Date of Approval ≤ today, Date of Approval ≤ Last Renewal ≤ today. The upcoming renewal is recomputed (+1 year anchor) and a "Data Correction" entry is written to the activity log.
              </small>
            </div>
          </div>

          <!-- Modal Footer Actions -->
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem;">
            <button type="button" class="btn btn-outline" onclick="backToAttentionList()">
              ${clubDetailsBackLabel()}
            </button>
            <div style="display: flex; gap: 0.5rem;">
              ${emailRecipients ? `
                <a href="${mailtoUrl}" class="btn btn-accent btn-sm" style="text-decoration: none;">
                  📧 Send Renewal Notice E-Mail
                </a>
              ` : ''}
              <button type="button" class="btn btn-primary btn-sm" onclick="closeClubDetailsModal()">
                Close Details
              </button>
            </div>
          </div>
        `;
      } catch (err) {
        console.error("Error rendering club details view:", err);
        body.innerHTML = `
          <div style="padding: 1.5rem;">
            <div class="alert alert-danger">
              <span>⚠️</span>
              <div>An unexpected error occurred while displaying club properties.</div>
            </div>
            <div style="margin-top: 1rem; text-align: right;">
              <button type="button" class="btn btn-outline btn-sm" onclick="backToAttentionList()">${clubDetailsBackLabel()}</button>
              <button type="button" class="btn btn-primary btn-sm" onclick="closeClubDetailsModal()">Close</button>
            </div>
          </div>
        `;
      }
    }

