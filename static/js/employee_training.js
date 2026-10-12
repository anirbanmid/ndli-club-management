    // =========================================================================
    // R35: PPT TRAINING LIBRARY — single-click deck download for officers
    // =========================================================================
    function trainingToken() {
      return sessionStorage.getItem("ndli_employee_token") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_token") : null) || sessionStorage.getItem("ndli_token") || localStorage.getItem("ndli_token");
    }

    async function loadTrainingDecks() {
      const wrap = document.getElementById("training-decks");
      if (!wrap) return;
      try {
        const res = await apiRequest("/api/training/files");
        if (!res.ok || !res.data || !res.data.success) throw new Error((res.data && (res.data.message || res.data.error)) || "load failed");
        const d = res.data;
        const fmt = (n) => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
        let html = "";
        for (const slot of ["1", "2"]) {
          const info = d.slots && d.slots[slot];
          if (info && info.filename) {
            html += `<div style="display:flex; justify-content:space-between; align-items:center; gap:0.75rem; background:#fff; border:1px solid var(--border); border-radius:var(--radius-sm); padding:0.7rem 0.95rem; margin-bottom:0.55rem;">
              <div style="min-width:0;"><strong style="display:block; font-size:0.95rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(info.filename)}</strong>
              <small style="color:var(--text-muted); font-size:0.82rem;">${fmt(info.size || 0)} · uploaded ${escapeHtml((info.uploaded_at || "").slice(0, 10))}</small></div>
              <button class="btn btn-primary btn-sm" onclick="trainingDownload('${slot}')" style="white-space:nowrap;"><span>⬇</span> Download</button>
            </div>`;
          } else {
            html += `<div style="background:#fff; border:1px dashed var(--border); border-radius:var(--radius-sm); padding:0.7rem 0.95rem; margin-bottom:0.55rem; color:var(--text-muted); font-size:0.9rem;">Slot ${slot} — no deck uploaded yet.</div>`;
          }
        }
        wrap.innerHTML = html;
      } catch (e) {
        wrap.innerHTML = `<div style="color:var(--text-muted); font-size:0.88rem;">Training materials are unavailable right now.</div>`;
      }
    }

    async function trainingDownload(slot) {
      try {
        const token = trainingToken();
        const resp = await fetch(`/api/training/download/${slot}`, { headers: token ? { "Authorization": `Bearer ${token}` } : {} });
        if (!resp.ok) throw new Error("download failed (HTTP " + resp.status + ")");
        const blob = await resp.blob();
        const cd = resp.headers.get("Content-Disposition") || "";
        let name = "training_deck.pptx";
        const m = cd.match(/filename="?([^";]+)"?/);
        if (m) name = m[1];
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      } catch (e) {
        alert("Could not download the training deck: " + e.message);
      }
    }


