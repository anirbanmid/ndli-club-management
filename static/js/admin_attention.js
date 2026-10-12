    // =============================================================
    // RENEWAL ATTENTION & CLUB DETAILS MODALS CONTROLLER
    // R42: server-side pagination - the browser fetches ONE page at a
    // time (filter + search run server-side). renderRenewalAttentionList
    // stays a PURE renderer of the last response (no fetch inside).
    // =============================================================
    var RENEWAL_ATTENTION_DATA = null;
    var CURRENT_ATTENTION_FILTER = "ALL";
    var CURRENT_ATTENTION_QUERY = "";
    let ATTENTION_PAGE_SIZE = 50;
    let CURRENT_ATTENTION_PAGE = 1;
    let ATTENTION_SEARCH_DEBOUNCE = null;

    async function fetchAttentionPage(page) {
      const tbody = document.getElementById("renewal-attention-tbody");
      const params = new URLSearchParams({
        page: String(page || 1),
        page_size: String(ATTENTION_PAGE_SIZE),
        filter: CURRENT_ATTENTION_FILTER || "ALL",
        q: CURRENT_ATTENTION_QUERY || ""
      });
      try {
        const res = await apiRequest("/api/admin/renewal-attention?" + params.toString());
        if (res.ok && res.data) {
          RENEWAL_ATTENTION_DATA = res.data;
          CURRENT_ATTENTION_PAGE = res.data.page || 1;
          updateAttentionCountsUI(res.data);
          renderRenewalAttentionList();
        } else {
          if (tbody) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--danger); padding: 2rem;">Failed to fetch renewal attention records.</td></tr>';
          }
        }
      } catch (err) {
        if (tbody) {
          tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--danger); padding: 2rem;">Network error fetching renewal attention records.</td></tr>';
        }
      }
    }

    async function openRenewalAttentionModal(initialFilter = "ALL") {
      CURRENT_ATTENTION_FILTER = initialFilter;
      CURRENT_ATTENTION_QUERY = "";
      CURRENT_ATTENTION_PAGE = 1;

      updateAttentionFilterButtons(initialFilter);

      const searchInput = document.getElementById("attn-search-input");
      if (searchInput) searchInput.value = "";

      const modal = document.getElementById("renewal-attention-modal");
      if (modal) {
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.display = "flex";
        ndliModalOpened(modal);
      }

      const tbody = document.getElementById("renewal-attention-tbody");
      if (tbody) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 2.5rem;">Loading renewal attention records...</td></tr>';
      }

      await fetchAttentionPage(1);
    }

    function closeRenewalAttentionModal() {
      const modal = document.getElementById("renewal-attention-modal");
      if (modal) {
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.display = "none";
        ndliModalClosed(modal);
      }
    }

    function updateAttentionCountsUI(data) {
      const total = data.total_attention_count || 0;
      const overdue = data.overdue_count || 0;
      const expiring = data.expiring_soon_count || 0;

      const totalBadge = document.getElementById("attn-total-count");
      const overdueBadge = document.getElementById("attn-overdue-count");
      const expiringBadge = document.getElementById("attn-expiring-count");

      if (totalBadge) totalBadge.innerText = `${total} Total Attention`;
      if (overdueBadge) overdueBadge.innerText = `${overdue} Overdue`;
      if (expiringBadge) expiringBadge.innerText = `${expiring} Expiring Soon`;

      const btnAll = document.getElementById("btn-count-all");
      const btnOvd = document.getElementById("btn-count-overdue");
      const btnExp = document.getElementById("btn-count-expiring");

      if (btnAll) btnAll.innerText = total;
      if (btnOvd) btnOvd.innerText = overdue;
      if (btnExp) btnExp.innerText = expiring;

      const kpiEl = document.getElementById("kpi-renewals");
      if (kpiEl) kpiEl.innerText = total;
    }

    function updateAttentionFilterButtons(activeFilter) {
      document.querySelectorAll(".attn-filter-btn").forEach(btn => {
        const f = btn.getAttribute("data-filter");
        const isActive = f.toLowerCase() === activeFilter.toLowerCase() || (f === "ALL" && activeFilter === "ALL");
        if (isActive) {
          btn.classList.remove("btn-outline");
          btn.classList.add("btn-primary");
        } else {
          btn.classList.remove("btn-primary");
          btn.classList.add("btn-outline");
        }
      });
    }

    function filterAttentionList(filterType) {
      CURRENT_ATTENTION_FILTER = filterType;
      CURRENT_ATTENTION_PAGE = 1;
      updateAttentionFilterButtons(filterType);
      fetchAttentionPage(1);
    }

    function handleAttentionSearch(query) {
      CURRENT_ATTENTION_QUERY = (query || "").trim().toLowerCase();
      CURRENT_ATTENTION_PAGE = 1;
      if (ATTENTION_SEARCH_DEBOUNCE) clearTimeout(ATTENTION_SEARCH_DEBOUNCE);
      ATTENTION_SEARCH_DEBOUNCE = setTimeout(() => { fetchAttentionPage(1); }, 250);
    }

    function changeAttentionPage(page) {
      fetchAttentionPage(page);
      const t = document.getElementById("renewal-attention-tbody");
      if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // Pure renderer of RENEWAL_ATTENTION_DATA (the LAST paged response).
    // Filtering/search/pagination all happen server-side - this function
    // never fetches and never re-slices a full clubs array (R42 source lock).
    function renderRenewalAttentionList() {
      const tbody = document.getElementById("renewal-attention-tbody");
      const pBar = document.getElementById("attention-pagination-bar");
      if (!tbody || !RENEWAL_ATTENTION_DATA) return;

      const data = RENEWAL_ATTENTION_DATA;
      const renderList = data.clubs || [];
      const page = data.page || 1;
      const pageSize = data.page_size || ATTENTION_PAGE_SIZE;
      const totalPages = data.total_pages || 0;
      const totalMatches = (data.total_matches != null) ? data.total_matches : renderList.length;

      if (renderList.length === 0) {
        if (pBar) pBar.style.display = "none";
        tbody.innerHTML = `
          <tr>
            <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 3rem;">
              <div style="font-size: 2rem; margin-bottom: 0.5rem;">📋</div>
              <strong>No clubs found matching filter criteria.</strong>
              <div style="font-size: 0.85rem; margin-top: 0.35rem; color: var(--text-muted);">
                ${CURRENT_ATTENTION_QUERY ? 'Try clearing or changing your search terms.' : 'All club renewal statuses in this category are up-to-date.'}
              </div>
            </td>
          </tr>
        `;
        return;
      }

      if (totalPages > 1) {
        const startIdx = (page - 1) * pageSize;
        const endIdx = Math.min(startIdx + pageSize, totalMatches);
        if (pBar) {
          pBar.style.display = "flex";
          pBar.innerHTML = `
            <div style="font-size: 0.85rem; color: var(--text-muted);">
              Showing <strong>${startIdx + 1}</strong> – <strong>${endIdx}</strong> of <strong>${totalMatches.toLocaleString()}</strong> clubs
            </div>
            <div style="display: flex; gap: 0.35rem; align-items: center;">
              <button type="button" class="btn btn-outline btn-sm" ${page === 1 ? 'disabled style="opacity: 0.45; cursor: not-allowed;"' : ''} onclick="changeAttentionPage(1)">« First</button>
              <button type="button" class="btn btn-outline btn-sm" ${page === 1 ? 'disabled style="opacity: 0.45; cursor: not-allowed;"' : ''} onclick="changeAttentionPage(${page - 1})">‹ Prev</button>
              <span style="font-size: 0.85rem; font-weight: 600; padding: 0 0.5rem;">Page ${page} of ${totalPages}</span>
              <button type="button" class="btn btn-outline btn-sm" ${page === totalPages ? 'disabled style="opacity: 0.45; cursor: not-allowed;"' : ''} onclick="changeAttentionPage(${page + 1})">Next ›</button>
              <button type="button" class="btn btn-outline btn-sm" ${page === totalPages ? 'disabled style="opacity: 0.45; cursor: not-allowed;"' : ''} onclick="changeAttentionPage(${totalPages})">Last »</button>
            </div>
          `;
        }
      } else {
        if (pBar) pBar.style.display = "none";
      }

      tbody.innerHTML = renderList.map(c => {
        const isOverdue = c.attention_type === "Overdue";
        const badgeClass = isOverdue ? "pill-danger" : "pill-warning";
        const urgencyText = c.badge_label || (isOverdue ? `${c.days_overdue || Math.abs(c.days_diff)} days overdue` : `${c.days_left || c.days_diff} days left`);
        const statusType = isOverdue ? "🔴 Overdue" : "🟡 Expiring Soon";
        const cid = c.club_id || "";
        const cidSafe = cid.replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

        const doaVal = c.date_of_approval || c.submission_timestamp || "";
        const doaDisplay = doaVal ? (typeof formatDateDisplay === "function" ? formatDateDisplay(doaVal) : doaVal.split("T")[0]) : "-";
        const lrdVal = c.last_renewal_date || "";
        const lrdDisplay = lrdVal ? (typeof formatDateDisplay === "function" ? formatDateDisplay(lrdVal) : lrdVal.split("T")[0]) : "None (Initial)";
        const renDisplay = c.renewal_date || c.next_renewal_date || c.effective_renewal_date || "-";

        return `
          <tr style="cursor: pointer; transition: background 0.12s;" onclick="openClubDetailsModal('${cidSafe}')" title="Click to view full club properties">
            <td><code style="font-weight: 700; color: var(--primary);">${escapeHtml(cid)}</code></td>
            <td><strong>${escapeHtml(c.institution_name)}</strong></td>
            <td>${escapeHtml(c.state)}</td>
            <td><span class="pill pill-primary" style="font-size: 0.75rem;">${escapeHtml(c.zone)}</span></td>
            <td style="font-family: monospace; font-size: 0.85rem;">${escapeHtml(doaDisplay)}</td>
            <td style="font-family: monospace; font-size: 0.85rem; color: #b45309;">${escapeHtml(lrdDisplay)}</td>
            <td style="font-family: monospace; font-size: 0.85rem; font-weight: 700; color: #15803d;">${escapeHtml(renDisplay)}</td>
            <td><span class="pill ${badgeClass}">${escapeHtml(urgencyText)}</span></td>
            <td><span class="pill ${badgeClass}">${statusType}</span></td>
            <td>
              <button type="button" class="btn btn-outline btn-sm" onclick="event.stopPropagation(); openClubDetailsModal('${cidSafe}')" style="padding: 3px 8px; font-size: 0.78rem;">
                View Details ↗
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }
