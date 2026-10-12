    // ================= R30: Data Migration (employee activity history) =================
    // Client legacy worksheets: per-period COUNTS, no club identity (sample 2026-10-09:
    // 5,518 rows / one employee). Past and present stay separate — the dry-run writes
    // nothing; commit records the migrated history + quota baselines + ONE marked
    // "Data Migration" summary row. No club links are ever fabricated.
    let MIG_CSV_TEXT = "";
    let MIG_LAST_REPORT = null;
    // R31: 2nd-layer gate state. MIG_ADMIN_PWD is the verified Master Admin
    // password, held only in page memory and re-sent to the commit endpoint
    // so the server can re-verify (Layer 2) before any write.
    let MIG_ADMIN_PWD = "";
    let MIG_GATE_UNLOCKED = false;

    function openMigrationModal() {
      // R31: the Data Migration tools sit behind a 2nd-layer admin gate.
      // If already unlocked this session, open the modal directly.
      if (MIG_GATE_UNLOCKED) {
        showMigrationModal();
        return;
      }
      const modal = document.getElementById("migration-gate-modal");
      if (!modal) return;
      const pInp = document.getElementById("migration-gate-password");
      const err = document.getElementById("migration-gate-error");
      if (pInp) pInp.value = "";
      if (err) { err.style.display = "none"; err.innerText = ""; }
      validateMigrationGate();
      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      if (typeof ndliModalOpened === "function") ndliModalOpened(modal);
      setTimeout(() => { if (pInp) pInp.focus(); }, 120);
    }

    function showMigrationModal() {
      const modal = document.getElementById("migration-modal");
      if (!modal) return;
      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      if (typeof ndliModalOpened === "function") ndliModalOpened(modal);
    }

    function closeMigrationGateModal() {
      const modal = document.getElementById("migration-gate-modal");
      if (!modal) return;
      modal.classList.remove("active");
      modal.classList.remove("open");
      modal.style.display = "none";
      if (typeof ndliModalClosed === "function") ndliModalClosed(modal);
    }

    function validateMigrationGate() {
      const pInp = document.getElementById("migration-gate-password");
      const btn = document.getElementById("btn-unlock-migration");
      if (!btn) return;
      const ok = !!(pInp && pInp.value.trim());
      btn.disabled = !ok;
      btn.style.opacity = ok ? "1" : "0.45";
      btn.style.cursor = ok ? "pointer" : "not-allowed";
    }

    function toggleMigrationGatePasswordVisibility() {
      const pwd = document.getElementById("migration-gate-password");
      if (pwd) pwd.type = pwd.type === "password" ? "text" : "password";
    }

    async function unlockMigrationGate() {
      const pInp = document.getElementById("migration-gate-password");
      const err = document.getElementById("migration-gate-error");
      const btn = document.getElementById("btn-unlock-migration");
      const pwd = pInp ? pInp.value.trim() : "";
      if (!pwd) return;
      if (err) { err.style.display = "none"; err.innerText = ""; }
      if (btn) { btn.disabled = true; btn.innerHTML = "<span>⏳</span> Verifying…"; }
      try {
        // Layer 2 (server-verified): confirm the Master Admin password and
        // that the account really is an ADMIN (admin access only).
        const res = await apiRequest("/api/auth/verify-password", "POST", {
          identifier: "admin@iitkgp.ac.in",
          password: pwd
        });
        const ok = res && res.ok && res.data && res.data.valid && res.data.role === "ADMIN";
        if (!ok) {
          const msg = (res && res.data && (res.data.message || res.data.error)) || "Incorrect Master Admin password.";
          if (err) { err.style.display = "block"; err.innerText = "⛔ " + msg + " Only the Master Administrator may open the Data Migration tools."; }
          return;
        }
        MIG_ADMIN_PWD = pwd;
        MIG_GATE_UNLOCKED = true;
        closeMigrationGateModal();
        showMigrationModal();
      } catch (e) {
        if (err) { err.style.display = "block"; err.innerText = "⛔ Verification error: " + (e && e.message ? e.message : e); }
      } finally {
        if (btn) { btn.innerHTML = "<span>🔓</span> Verify &amp; Open Data Migration →"; validateMigrationGate(); }
      }
    }

    function closeMigrationModal() {
      const modal = document.getElementById("migration-modal");
      if (!modal) return;
      modal.classList.remove("active");
      modal.classList.remove("open");
      modal.style.display = "none";
    }

    function handleMigrationFile(input) {
      const file = input.files && input.files[0];
      const out = document.getElementById("mig-status");
      const btn = document.getElementById("btn-mig-commit");
      MIG_CSV_TEXT = "";
      MIG_LAST_REPORT = null;
      if (btn) btn.disabled = true;
      const preview = document.getElementById("mig-preview");
      if (preview) preview.innerHTML = "";
      if (!file) return;
      const reader = new FileReader();
      reader.onload = function () {
        MIG_CSV_TEXT = String(reader.result || "");
        if (out) out.textContent = "Worksheet loaded. Run the dry run — nothing is written yet.";
      };
      reader.readAsText(file);
    }

    function renderMigrationPreview(rep) {
      const box = document.getElementById("mig-preview");
      if (!box) return;
      const s = (rep && rep.summary) || {};
      const t = s.totals || {};
      const span = s.span || {};
      const notes = (s.notes || []).concat((rep && rep.file_errors) || []);
      const errRows = (rep && rep.rows || []).filter(function (r) { return (r.errors || []).length; });
      let html = '<div style="display:flex;gap:1.2rem;flex-wrap:wrap;font-size:0.85rem;margin-bottom:0.7rem;">' +
        '<div><strong style="color:var(--success);">' + escapeHtml(String(t.approvals || 0)) + '</strong> club approvals</div>' +
        '<div><strong style="color:var(--warning);">' + escapeHtml(String(t.support || 0)) + '</strong> support</div>' +
        '<div><strong>' + escapeHtml(String(t.online_workshops || 0)) + '</strong> online workshops</div>' +
        '<div>span: <strong>' + escapeHtml(String(span.first_year || "?")) + '–' + escapeHtml(String(span.last_year || "?")) + '</strong></div>' +
        '<div>' + escapeHtml(String(s.total_rows || 0)) + ' rows (' + escapeHtml(String(s.ok_rows || 0)) + ' ok)</div>' +
        '</div>';
      if (notes.length) {
        html += '<div style="font-size:0.78rem;color:#92400E;background:#FEF3C7;border:1px solid #F3D9B2;border-radius:8px;padding:0.5rem 0.7rem;margin-bottom:0.7rem;"><strong>Notes:</strong> ' +
          notes.map(escapeHtml).join(' · ') + '</div>';
      }
      if (errRows.length) {
        html += '<div style="font-size:0.78rem;color:#B91C1C;"><strong>Rows needing fixes:</strong><ul>' +
          errRows.slice(0, 20).map(function (r) {
            return '<li>line ' + escapeHtml(String(r.line)) + ': ' + escapeHtml((r.errors || []).join(' ')) + '</li>';
          }).join('') + '</ul></div>';
      }
      box.innerHTML = html;
    }

    async function runMigrationDryRun() {
      const out = document.getElementById("mig-status");
      const empEl = document.getElementById("mig-emp-id");
      const empId = (empEl && empEl.value || "").trim().toUpperCase();
      if (!empId) { if (out) out.textContent = "⚠ Enter the employee ID first."; return; }
      if (!MIG_CSV_TEXT) { if (out) out.textContent = "⚠ Load the worksheet CSV first."; return; }
      if (out) out.textContent = "Validating…";
      try {
        const res = await apiRequest("/api/admin/migration/history/validate", "POST", { emp_id: empId, csv_text: MIG_CSV_TEXT });
        if (res && res.ok && res.data) {
          MIG_LAST_REPORT = res.data;
          renderMigrationPreview(res.data);
          const btn = document.getElementById("btn-mig-commit");
          if (btn) btn.disabled = !res.data.ready;
          if (out) out.textContent = res.data.ready
            ? "Dry run OK — review the totals above, then commit. Nothing written yet."
            : "⚠ Dry run found problems — fix the worksheet and retry. Nothing written.";
        } else {
          if (out) out.textContent = "⚠ " + ((res && res.data && res.data.message) || "Validation request failed.");
        }
      } catch (e) {
        if (out) out.textContent = "⚠ Request failed: " + e;
      }
    }

    async function commitMigration() {
      const out = document.getElementById("mig-status");
      const empEl = document.getElementById("mig-emp-id");
      const empId = (empEl && empEl.value || "").trim().toUpperCase();
      const replace = !!(document.getElementById("mig-replace") || {}).checked;
      if (!empId || !MIG_CSV_TEXT) { if (out) out.textContent = "⚠ Load a worksheet and run the dry run first."; return; }
      const s = (MIG_LAST_REPORT && MIG_LAST_REPORT.summary) || {};
      const t = s.totals || {};
      if (!confirm("Record migrated history for " + empId + "?\n\n" +
        (t.approvals || 0) + " club approvals, " + (t.support || 0) + " support, " + (t.online_workshops || 0) + " online workshops" +
        (replace ? "\n\nThis REPLACES any existing migrated history for this employee." : ""))) return;
      if (out) out.textContent = "Importing…";
      try {
        const res = await apiRequest("/api/admin/migration/history/commit", "POST", {
          emp_id: empId, csv_text: MIG_CSV_TEXT, replace: replace, password: MIG_ADMIN_PWD
        });
        if (res && res.ok && res.data && res.data.success) {
          if (out) out.textContent = "✓ " + (res.data.message || "Migrated history recorded.");
          const btn = document.getElementById("btn-mig-commit");
          if (btn) btn.disabled = true;
          if (typeof loadDashboardData === "function") loadDashboardData();
        } else {
          if (out) out.textContent = "⚠ " + ((res && res.data && res.data.message) || "Commit failed — nothing changed.");
        }
      } catch (e) {
        if (out) out.textContent = "⚠ Request failed: " + e;
      }
    }

    // ---- R31 TWO DOORS: Admin Data Migration — Bulk Club History Upload (HISTORY door) ----
    // Rows uploaded here are pre-system clubs recorded as record_origin="imported":
    // VISIBLE in the Club Register + the "history" half of every split, ZERO live
    // credit (counters unchanged). Opposite of the employee bulk door (NEW work).
    let MIG_CLUB_ROWS = [];
    const MIG_CLUB_COLS = ["club_id", "reg_no", "institution_name", "state", "patron_email",
      "president_email", "secretary_email", "date_of_approval", "last_renewal_date",
      "approved_by_emp_id"];

    function parseMigClubCsv(text) {
      const rows = [];
      let cur = [], field = "", inQ = false;
      const s = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      for (let i = 0; i < s.length; i++) {
        const ch = s[i];
        if (inQ) {
          if (ch === '"') {
            if (s[i + 1] === '"') { field += '"'; i++; } else { inQ = false; }
          } else { field += ch; }
        } else if (ch === '"') {
          inQ = true;
        } else if (ch === ",") {
          cur.push(field); field = "";
        } else if (ch === "\n") {
          cur.push(field); rows.push(cur); cur = []; field = "";
        } else {
          field += ch;
        }
      }
      if (field.length || cur.length) { cur.push(field); rows.push(cur); }
      return rows.filter(function (r) { return r.some(function (c) { return String(c).trim() !== ""; }); });
    }

    function handleMigClubFile(input) {
      const out = document.getElementById("mig-club-status");
      const btn = document.getElementById("btn-mig-club-commit");
      const vbtn = document.getElementById("btn-mig-club-validate");
      MIG_CLUB_ROWS = [];
      if (btn) btn.disabled = true;
      const f = input && input.files && input.files[0];
      if (!f) { if (out) out.textContent = ""; return; }
      const reader = new FileReader();
      reader.onload = function () {
        const grid = parseMigClubCsv(reader.result);
        if (!grid.length) { if (out) out.textContent = "⚠ The CSV looks empty."; return; }
        // First row = header. Map columns by name (tolerant of extra/missing cols).
        const header = grid[0].map(function (h) { return String(h).trim().toLowerCase(); });
        MIG_CLUB_ROWS = grid.slice(1).map(function (r) {
          const o = {};
          MIG_CLUB_COLS.forEach(function (c) {
            const ix = header.indexOf(c);
            o[c] = ix >= 0 ? String(r[ix] || "").trim() : "";
          });
          return o;
        });
        if (out) out.textContent = "Loaded " + MIG_CLUB_ROWS.length + " club rows. Run the dry run — nothing is written until you commit.";
        if (vbtn) vbtn.disabled = false;
      };
      reader.readAsText(f);
    }

    function renderMigClubPreview(data) {
      const box = document.getElementById("mig-club-preview");
      if (!box) return;
      const t = data || {};
      const rows = (t.results || []);
      const errRows = rows.filter(function (r) { return (r.errors || []).length; });
      let html = "";
      if (t.consequence) {
        html += '<div style="font-size:0.85rem;font-weight:700;color:#7C2D12;background:#FEF3C7;border:1px solid #F3D9B2;border-radius:8px;padding:0.55rem 0.75rem;margin-bottom:0.7rem;">⚑ ' + escapeHtml(String(t.consequence)) + '</div>';
      }
      if (t.gap_warnings && t.gap_warnings.length) {
        html += '<div style="font-size:0.8rem;color:#92400E;background:#FFF7ED;border:1px solid #FDBA74;border-radius:8px;padding:0.5rem 0.75rem;margin-bottom:0.7rem;"><strong>⚠ Worksheet gap check:</strong><ul style="margin:0.3rem 0 0 1.1rem;">' +
          t.gap_warnings.map(function (w) { return '<li>' + escapeHtml(String(w)) + '</li>'; }).join('') + '</ul></div>';
      }
      html += '<div style="display:flex;gap:1.2rem;flex-wrap:wrap;font-size:0.85rem;margin-bottom:0.7rem;">' +
        '<div><strong style="color:var(--success);">' + escapeHtml(String(t.valid || 0)) + '</strong> ready</div>' +
        '<div><strong style="color:#b91c1c;">' + escapeHtml(String(t.invalid || 0)) + '</strong> need fixes</div>' +
        '<div>' + escapeHtml(String(t.total || 0)) + ' rows total</div></div>';
      if (errRows.length) {
        html += '<div style="font-size:0.78rem;color:#B91C1C;"><strong>Rows needing fixes:</strong><ul>' +
          errRows.slice(0, 20).map(function (r) {
            return '<li>row ' + escapeHtml(String(r.row)) + ' (' + escapeHtml(String(r.club_id || r.reg_no || '?')) + '): ' + escapeHtml((r.errors || []).join(' ')) + '</li>';
          }).join('') + '</ul></div>';
      }
      box.innerHTML = html;
    }

    async function runMigClubDryRun() {
      const out = document.getElementById("mig-club-status");
      if (!MIG_CLUB_ROWS.length) { if (out) out.textContent = "⚠ Load the club history CSV first."; return; }
      if (out) out.textContent = "Validating…";
      try {
        const res = await apiRequest("/api/admin/migration/clubs/validate", "POST", { rows: MIG_CLUB_ROWS });
        if (res && res.ok && res.data) {
          renderMigClubPreview(res.data);
          const btn = document.getElementById("btn-mig-club-commit");
          if (btn) btn.disabled = !(res.data.valid > 0);
          if (out) out.textContent = res.data.valid > 0
            ? "Dry run OK — review the consequence + gap check above, then commit. Nothing written yet."
            : "⚠ Dry run found problems — fix the CSV and retry. Nothing written.";
        } else {
          if (out) out.textContent = "⚠ " + ((res && res.data && res.data.message) || "Validation request failed.");
        }
      } catch (e) {
        if (out) out.textContent = "⚠ Request failed: " + e;
      }
    }

    async function commitMigClubHistory() {
      const out = document.getElementById("mig-club-status");
      if (!MIG_CLUB_ROWS.length) { if (out) out.textContent = "⚠ Load the club history CSV and run the dry run first."; return; }
      const valid = (MIG_CLUB_ROWS || []).length;
      if (!confirm("Save these clubs as HISTORY (counters unchanged)?\n\nThey will appear in the Club Register as migrated/imported clubs but add NO new-work credit.")) return;
      if (out) out.textContent = "Importing…";
      try {
        const res = await apiRequest("/api/admin/migration/clubs/commit", "POST", {
          rows: MIG_CLUB_ROWS, password: MIG_ADMIN_PWD
        });
        if (res && res.ok && res.data && res.data.success) {
          if (out) out.textContent = "✓ " + (res.data.consequence || res.data.message || "Club history recorded.");
          renderMigClubPreview(res.data);
          const btn = document.getElementById("btn-mig-club-commit");
          if (btn) btn.disabled = true;
          if (typeof loadDashboardData === "function") loadDashboardData();
        } else {
          if (out) out.textContent = "⚠ " + ((res && res.data && res.data.message) || "Commit failed — nothing changed.");
        }
      } catch (e) {
        if (out) out.textContent = "⚠ Request failed: " + e;
      }
    }

    if (typeof window !== "undefined") {
      window.openClubDetailsModal = openClubDetailsModal;
      window.closeClubDetailsModal = closeClubDetailsModal;
      window.backToAttentionList = backToAttentionList;
      window.openClubRegisterModal = openClubRegisterModal;
      window.closeClubRegisterModal = closeClubRegisterModal;
      window.openMigrationModal = openMigrationModal;
      window.closeMigrationModal = closeMigrationModal;
      window.showMigrationModal = showMigrationModal;
      window.closeMigrationGateModal = closeMigrationGateModal;
      window.validateMigrationGate = validateMigrationGate;
      window.toggleMigrationGatePasswordVisibility = toggleMigrationGatePasswordVisibility;
      window.unlockMigrationGate = unlockMigrationGate;
      window.handleMigClubFile = handleMigClubFile;
      window.runMigClubDryRun = runMigClubDryRun;
      window.commitMigClubHistory = commitMigClubHistory;
      window.handleMigrationFile = handleMigrationFile;
      window.runMigrationDryRun = runMigrationDryRun;
      window.commitMigration = commitMigration;
      window.filterClubRegister = filterClubRegister;
      window.openClubDetailsFromRegister = openClubDetailsFromRegister;
      window.backToClubRegister = backToClubRegister;
      window.goBackFromClubDetails = goBackFromClubDetails;
      window.clubDetailsBackLabel = clubDetailsBackLabel;
      window.openRenewalAttentionModal = openRenewalAttentionModal;
      window.closeRenewalAttentionModal = closeRenewalAttentionModal;
      window.renderRenewalAttentionList = renderRenewalAttentionList;
      window.filterAttentionList = filterAttentionList;
      window.handleAttentionSearch = handleAttentionSearch;
      window.formatLocalTimestamp = formatLocalTimestamp;
      window.calculateNextRenewalDate = calculateNextRenewalDate;
      window.escapeHtml = escapeHtml;
      window.renderClubDetailsView = renderClubDetailsView;
      window.openAdminEscalationsListModal = openAdminEscalationsListModal;
      window.closeAdminEscalationsListModal = closeAdminEscalationsListModal;
      window.handleAdminEscalationsSearch = handleAdminEscalationsSearch;
      window.renderAdminEscalationsList = renderAdminEscalationsList;
      window.selectAdminEscalatedIssue = selectAdminEscalatedIssue;
      window.openAdminIssueResolutionModal = openAdminIssueResolutionModal;
      window.closeAdminIssueModal = closeAdminIssueModal;
      window.submitAdminIssueResolution = submitAdminIssueResolution;
    }

