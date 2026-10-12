    // =========================================================================
    // R35: PPT TRAINING LIBRARY (admin upload/replace/delete; 2 slots sharing
    // ONE 15 MB budget)
    // =========================================================================
    let trainingPendingSlot = null;

    async function loadTrainingSlots() {
      const wrap = document.getElementById("training-slots");
      if (!wrap) return;
      try {
        const res = await apiRequest("/api/training/files");
        if (!res.ok || !res.data || !res.data.success) throw new Error((res.data && (res.data.message || res.data.error)) || "load failed");
        const d = res.data;
        const fmt = (n) => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
        const used = d.total_bytes || 0;
        const max = d.max_total_bytes || 15728640;
        let html = "";
        for (const slot of ["1", "2"]) {
          const info = d.slots && d.slots[slot];
          if (info && info.filename) {
            html += `<div style="display:flex; justify-content:space-between; align-items:center; gap:0.75rem; background:#fff; border:1px solid var(--border); border-radius:var(--radius-sm); padding:0.65rem 0.9rem;">
              <div style="min-width:0;"><strong style="display:block; font-size:0.92rem; color:var(--text-main, #1e293b); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">Slot ${slot} — ${escapeHtml(info.filename)}</strong>
              <small style="color:var(--text-muted); font-size:0.8rem;">${fmt(info.size || 0)} · total used ${fmt(used)} of ${fmt(max)} · uploaded ${escapeHtml((info.uploaded_at || "").slice(0, 10))}</small></div>
              <div style="display:flex; gap:0.45rem; flex-shrink:0;">
                <button class="btn btn-outline btn-sm" onclick="trainingPickUpload('${slot}')">Replace</button>
                <button class="btn btn-danger btn-sm" onclick="trainingDelete('${slot}')">Delete</button>
              </div></div>`;
          } else {
            html += `<div style="display:flex; justify-content:space-between; align-items:center; gap:0.75rem; background:#fff; border:1px dashed var(--border); border-radius:var(--radius-sm); padding:0.65rem 0.9rem;">
              <div><strong style="display:block; font-size:0.92rem; color:var(--text-muted);">Slot ${slot} — empty</strong>
              <small style="color:var(--text-muted); font-size:0.8rem;">Budget used: ${fmt(used)} of ${fmt(max)}</small></div>
              <button class="btn btn-primary btn-sm" onclick="trainingPickUpload('${slot}')"><span>⬆</span> Upload deck</button>
            </div>`;
          }
        }
        wrap.innerHTML = html;
      } catch (e) {
        wrap.innerHTML = `<div class="alert alert-danger" style="margin:0;"><span>⚠️</span><div>Could not load training slots: ${escapeHtml(e.message)}</div></div>`;
      }
    }

    function trainingPickUpload(slot) {
      trainingPendingSlot = slot;
      const inp = document.getElementById("training-file-input");
      if (inp) { inp.value = ""; inp.click(); }
    }

    async function trainingFileChosen() {
      const inp = document.getElementById("training-file-input");
      const wrap = document.getElementById("training-slots");
      if (!inp || !inp.files || !inp.files[0] || !trainingPendingSlot) return;
      const file = inp.files[0];
      const slot = trainingPendingSlot;
      trainingPendingSlot = null;
      const name = file.name || "deck.pptx";
      const ext = name.toLowerCase().slice(name.lastIndexOf("."));
      if (![".ppt", ".pptx", ".ppsx"].includes(ext)) {
        showAlert("admin-alert", "⚠ Only .ppt, .pptx and .ppsx files are accepted.", "danger");
        return;
      }
      try {
        const listRes = await apiRequest("/api/training/files");
        const d = (listRes.data && listRes.data.success) ? listRes.data : { slots: {}, total_bytes: 0, max_total_bytes: 15728640 };
        let other = 0;
        for (const s of ["1", "2"]) { if (s !== slot && d.slots && d.slots[s]) other += (d.slots[s].size || 0); }
        const max = d.max_total_bytes || 15728640;
        if (other + file.size > max) {
          showAlert("admin-alert", `⚠ Too big: both decks must fit in ${(max / 1048576).toFixed(0)} MB COMBINED (the other slot already uses ${other} bytes).`, "danger");
          return;
        }
        const b64 = await new Promise((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(String(r.result).split(",")[1] || "");
          r.onerror = () => reject(new Error("file could not be read"));
          r.readAsDataURL(file);
        });
        const res = await apiRequest("/api/admin/training/upload", "POST", { slot: slot, filename: name, data: b64 });
        if (res.ok && res.data && res.data.success) {
          showAlert("admin-alert", "✓ " + (res.data.message || "Training deck saved."), "success");
        } else {
          showAlert("admin-alert", "⚠ " + ((res.data && (res.data.message || res.data.error)) || "Upload failed."), "danger");
        }
      } catch (e) {
        showAlert("admin-alert", "⚠ Upload error: " + e.message, "danger");
      }
      loadTrainingSlots();
    }

    async function trainingDelete(slot) {
      if (!window.confirm(`Delete the training deck in slot ${slot}? Employees will no longer see it.`)) return;
      try {
        const res = await apiRequest("/api/admin/training/delete", "POST", { slot: slot });
        if (res.ok && res.data && res.data.success) {
          showAlert("admin-alert", "✓ " + (res.data.message || "Slot cleared."), "success");
        } else {
          showAlert("admin-alert", "⚠ " + ((res.data && (res.data.message || res.data.error)) || "Delete failed."), "danger");
        }
      } catch (e) {
        showAlert("admin-alert", "⚠ Delete error: " + e.message, "danger");
      }
      loadTrainingSlots();
    }

