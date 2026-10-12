    // =========================================================================
    // FEATURE 2: 7-DAY AUTOMATED DATABASE BACKUP STATUS & TRIGGER
    // =========================================================================
    async function loadAdminBackupStatus() {
      if (!IS_ADMIN_AUTHENTICATED) return;
      try {
        const adminToken = sessionStorage.getItem("ndli_admin_token");
        const res = await apiRequest("/api/admin/backup/status", "GET", null, adminToken);
        if (res.ok && res.data) {
          const d = res.data;
          const countEl = document.getElementById("backup-count-display");
          if (countEl) countEl.innerText = `${d.total_stored_backups || 0} / ${d.max_retained_backups || 6} Backups`;

          const lastEl = document.getElementById("backup-last-time");
          if (lastEl) {
            if (d.last_backup_time) {
              const dt = new Date(d.last_backup_time);
              lastEl.innerText = dt.toLocaleString();
            } else {
              lastEl.innerText = "Never";
            }
          }

          const nextEl = document.getElementById("backup-next-due");
          if (nextEl) {
            if (d.next_backup_due) {
              const dt = new Date(d.next_backup_due);
              nextEl.innerText = dt.toLocaleDateString();
            } else {
              nextEl.innerText = "Pending";
            }
          }

          window._cachedAdminBackups = d.backups || [];

          const listEl = document.getElementById("backup-archives-list");
          if (listEl) {
            if (!d.backups || d.backups.length === 0) {
              listEl.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 0.75rem;">No stored backups yet. Initial backup will run automatically.</div>';
            } else {
              let html = '<div style="display: flex; flex-direction: column; gap: 0.5rem;">';
              d.backups.forEach((b, idx) => {
                const dateStr = b.created_at ? new Date(b.created_at).toLocaleString() : b.backup_id;
                const adminCount = b.admin_files ? b.admin_files.length : (b.admin_files_count || 0);
                const empCount = b.employee_nodes ? b.employee_nodes.length : (b.employee_nodes_count || 0);
                html += `
                  <div style="display: flex; justify-content: space-between; align-items: center; background: #f8fafc; padding: 0.6rem 0.85rem; border-radius: 4px; border-left: 3px solid #0D7751;">
                    <div>
                      <strong style="color: var(--primary); font-size: 0.85rem;">📦 ${escapeHtml(b.backup_id)}</strong>
                      <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.5rem;">${dateStr}</span>
                      <div style="font-size: 0.75rem; color: #475569; margin-top: 0.15rem;">
                        Admin Master Files: <strong>${adminCount}</strong> • Employee Nodes: <strong>${empCount}</strong>
                      </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                      <span class="pill pill-success" style="font-size: 0.7rem;">Stored ✓</span>
                      <button class="btn btn-outline btn-sm" onclick="openEmergencyRestoreModal('${escapeHtml(b.backup_id)}')" style="font-size: 0.72rem; padding: 0.25rem 0.6rem; border-color: #dc2626; color: #dc2626; font-weight: 600;">↺ Restore</button>
                    </div>
                  </div>
                `;
              });
              html += '</div>';
              listEl.innerHTML = html;
            }
          }
        }
      } catch (err) {
        console.warn("Could not load backup status:", err);
      }
    }

    async function triggerManualBackup() {
      try {
        const res = await apiRequest("/api/admin/backup/trigger", "POST", { note: "Manual Admin Trigger" });
        if (res.ok && res.data && res.data.success) {
          const driveMsg = res.data.drive_file
            ? `\n☁️ Google Drive Archive: ${res.data.drive_file} (Saved in Google Drive /backups)`
            : (res.data.drive_sync && res.data.drive_sync.status !== 'FAILED' ? `\n☁️ Google Drive: Mirrored to Drive /backups folder` : '');
          alert(`Backup completed successfully!\n📦 Local Backup ID: ${res.data.backup_id}${driveMsg}\n🔄 Retained Backups: ${res.data.retained_backups.join(', ')}`);
          loadAdminBackupStatus();
        } else {
          showAlert("admin-alert", "Backup failed: " + (res.data?.message || "Unknown error"), "danger");
        }
      } catch (e) {
        showAlert("admin-alert", "Error triggering backup: " + e.message, "danger");
      }
    }

