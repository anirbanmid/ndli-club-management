    // R26: BULK IMPORT (CSV) — batch entry of legacy clubs with a dry-run preview.
    let BULK_ROWS = [];

    function openBulkImportModal() {
      const modal = document.getElementById("bulk-import-modal");
      if (!modal) return;
      modal.classList.add("active");
      modal.classList.add("open");
      modal.style.display = "flex";
      if (typeof ndliModalOpened === "function") ndliModalOpened(modal);
    }

    function closeBulkImportModal() {
      const modal = document.getElementById("bulk-import-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
      }
      if (typeof ndliModalClosed === "function") ndliModalClosed(modal);
    }

    function downloadBulkTemplate() {
      const header = "club_id,reg_no,institution_name,state,patron_email,president_email,secretary_email,date_of_approval,last_renewal_date,approved_by_emp_id";
      const example = "2051,REG-2026-WB-001,Example New College,West Bengal,patron@example.edu,president@example.edu,secretary@example.edu,,,EMP02";
      const csv = header + "\n" + example + "\n";
      const blob = new Blob([csv], { type: "text/csv" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "ndli_bulk_import_template.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
    }

    // Minimal CSV parser (RFC4180-ish: quoted fields, escaped quotes, commas/newlines).
    function parseBulkCsv(text) {
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

    const BULK_COLS = ["club_id", "reg_no", "institution_name", "state", "patron_email",
      "president_email", "secretary_email", "date_of_approval", "last_renewal_date",
      "approved_by_emp_id"];

    function handleBulkFile(input) {
      const file = input.files && input.files[0];
      const out = document.getElementById("bulk-import-status");
      const btn = document.getElementById("btn-bulk-commit");
      if (btn) { btn.disabled = true; btn.textContent = "✓ Import valid rows"; }
      if (!file) return;
      const reader = new FileReader();
      reader.onload = function () {
        const rows = parseBulkCsv(reader.result);
        if (!rows.length) {
          BULK_ROWS = [];
          if (out) out.textContent = "⚠ The file is empty or unreadable.";
          return;
        }
        const header = rows[0].map(function (h) { return h.trim().toLowerCase(); });
        const missing = BULK_COLS.filter(function (c) { return header.indexOf(c) === -1; });
        if (missing.length) {
          BULK_ROWS = [];
          if (out) out.textContent = "⚠ Missing column(s): " + missing.join(", ") + ". Use the CSV template.";
          return;
        }
        BULK_ROWS = rows.slice(1).map(function (r) {
          const o = {};
          BULK_COLS.forEach(function (c) { o[c] = (r[header.indexOf(c)] || "").trim(); });
          // R30: optional per-row attribution — the client's club log names the
          // officer per club (admin sessions only; the server enforces the gate).
          const oeIdx = header.indexOf("approved_by_emp_id");
          if (oeIdx !== -1) { o.approved_by_emp_id = (r[oeIdx] || "").trim(); }
          return o;
        });
        if (out) out.textContent = String(BULK_ROWS.length) + " data row(s) loaded. Run the dry-run check — nothing is written yet.";
      };
      reader.readAsText(file);
    }

    function renderBulkPreview(results, consequence) {
      const box = document.getElementById("bulk-preview");
      if (!box) return;
      const banner = consequence
        ? '<div style="font-size:0.85rem;font-weight:700;color:#7C2D12;background:#FEF3C7;border:1px solid #F3D9B2;border-radius:8px;padding:0.55rem 0.75rem;margin-bottom:0.7rem;">⚑ ' + escapeHtml(String(consequence)) + '</div>'
        : "";
      const trs = (results || []).map(function (r) {
        const ok = r.status === "ready" || r.status === "created";
        const color = ok ? "#15803d" : "#B91C1C";
        const label = r.status === "ready" ? "READY" : (r.status === "created" ? "CREATED" : "ERROR");
        return "<tr>" +
          '<td style="padding:0.35rem;">' + escapeHtml(String(r.row)) + "</td>" +
          '<td style="padding:0.35rem;font-family:monospace;">' + escapeHtml(String(r.club_id || "")) + "</td>" +
          '<td style="padding:0.35rem;font-family:monospace;">' + escapeHtml(String(r.reg_no || "")) + "</td>" +
          '<td style="padding:0.35rem;">' + escapeHtml(String(r.institution_name || "")) + "</td>" +
          '<td style="padding:0.35rem;color:' + color + ';font-weight:600;">' + label + "</td>" +
          '<td style="padding:0.35rem;color:#B91C1C;font-size:0.75rem;">' + escapeHtml((r.errors || []).join(" ")) + "</td>" +
          "</tr>";
      }).join("");
      box.innerHTML = banner +
        '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:0.8rem;">' +
        '<thead><tr style="border-bottom:2px solid var(--primary);">' +
        '<th style="text-align:left;padding:0.35rem;">#</th>' +
        '<th style="text-align:left;padding:0.35rem;">Club ID</th>' +
        '<th style="text-align:left;padding:0.35rem;">Reg No</th>' +
        '<th style="text-align:left;padding:0.35rem;">Institution</th>' +
        '<th style="text-align:left;padding:0.35rem;">Status</th>' +
        '<th style="text-align:left;padding:0.35rem;">Errors</th>' +
        "</tr></thead><tbody>" + trs + "</tbody></table></div>";
    }

    async function runBulkDryRun() {
      const out = document.getElementById("bulk-import-status");
      if (!BULK_ROWS.length) { if (out) out.textContent = "⚠ Load a CSV file first."; return; }
      if (out) out.textContent = "Validating…";
      try {
        const res = await apiRequest("/api/clubs/bulk-import/validate", "POST", { emp_id: CURRENT_EMP_ID, rows: BULK_ROWS });
        if (res && res.ok && res.data) {
          renderBulkPreview(res.data.results || [], res.data.consequence);
          if (out) out.textContent = "Dry run: " + res.data.valid + " ready, " + res.data.invalid + " with errors. Nothing written yet.";
          const btn = document.getElementById("btn-bulk-commit");
          if (btn) {
            btn.disabled = !(res.data.valid > 0);
            btn.textContent = "✓ Import " + res.data.valid + " valid row(s)";
          }
        } else {
          if (out) out.textContent = "⚠ " + ((res && res.data && res.data.message) || "Validation request failed.");
        }
      } catch (e) {
        if (out) out.textContent = "⚠ Request failed: " + e;
      }
    }

    async function commitBulkImport() {
      const out = document.getElementById("bulk-import-status");
      if (!BULK_ROWS.length) { if (out) out.textContent = "⚠ Load a CSV file first."; return; }
      if (out) out.textContent = "Importing…";
      try {
        const res = await apiRequest("/api/clubs/bulk-import/commit", "POST", { emp_id: CURRENT_EMP_ID, rows: BULK_ROWS });
        if (res && res.ok && res.data) {
          renderBulkPreview(res.data.results || [], res.data.consequence);
          const cloud = res.data.cloud_sync_confirmed;
          const cloudNote = (cloud === true) ? "Cloud sync confirmed."
            : (cloud === null ? "Cloud sync queued (record saved on this server's disk)."
              : "⚠ Cloud sync NOT confirmed — check the backups before relying on this batch.");
          if (out) out.textContent = "Imported " + res.data.created + " of " + res.data.total + " row(s). " + cloudNote;
          if (typeof loadEmployeeQuota === "function") loadEmployeeQuota();
          if (typeof loadEmployeeActivities === "function") loadEmployeeActivities(true);
          if (typeof performUniversalSearch === "function") performUniversalSearch("", true);
        } else {
          if (out) out.textContent = "⚠ " + ((res && res.data && res.data.message) || "Import failed.");
        }
      } catch (e) {
        if (out) out.textContent = "⚠ Request failed: " + e;
      }
    }

