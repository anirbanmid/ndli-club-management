    let ALL_CLUBS_CACHE = null;
    let LAST_CLUBS_FETCH_TIME = 0;
    let IS_CLUBS_FETCHING = false;
    let PENDING_SEARCH_QUERY = null;
    let CURRENT_SEARCH_RESULTS = [];

    let CLUBS_PAGE_SIZE = 50;
    let CURRENT_CLUBS_PAGE = 1;

    function changeClubsPage(page) {
      CURRENT_CLUBS_PAGE = page;
      if (CURRENT_SEARCH_RESULTS) {
        renderClubsTable(CURRENT_SEARCH_RESULTS, page);
        const t = document.getElementById("search-results-tbody");
        if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }

    function renderClubsTable(results, page = 1) {
      const tbody = document.getElementById("search-results-tbody");
      const pBar = document.getElementById("clubs-pagination-bar");
      if (!tbody) return;
      if (!results || results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 2rem;">No clubs found matching your search.</td></tr>';
        if (pBar) pBar.style.display = "none";
        return;
      }

      let renderList = results;
      if (results.length > CLUBS_PAGE_SIZE) {
        const totalPages = Math.ceil(results.length / CLUBS_PAGE_SIZE);
        CURRENT_CLUBS_PAGE = Math.max(1, Math.min(page, totalPages));
        const startIdx = (CURRENT_CLUBS_PAGE - 1) * CLUBS_PAGE_SIZE;
        renderList = results.slice(startIdx, startIdx + CLUBS_PAGE_SIZE);

        if (pBar) {
          const endIdx = Math.min(startIdx + CLUBS_PAGE_SIZE, results.length);
          pBar.style.display = "flex";
          pBar.innerHTML = `
            <div style="font-size: 0.85rem; color: var(--text-muted);">
              Showing <strong>${startIdx + 1}</strong> – <strong>${endIdx}</strong> of <strong>${results.length.toLocaleString()}</strong> clubs
            </div>
            <div style="display: flex; gap: 0.35rem; align-items: center;">
              <button type="button" class="btn btn-outline btn-sm" ${CURRENT_CLUBS_PAGE === 1 ? 'disabled' : ''} onclick="changeClubsPage(1)">« First</button>
              <button type="button" class="btn btn-outline btn-sm" ${CURRENT_CLUBS_PAGE === 1 ? 'disabled' : ''} onclick="changeClubsPage(${CURRENT_CLUBS_PAGE - 1})">‹ Prev</button>
              <span style="font-size: 0.85rem; font-weight: 600; padding: 0 0.5rem;">Page ${CURRENT_CLUBS_PAGE} of ${totalPages}</span>
              <button type="button" class="btn btn-outline btn-sm" ${CURRENT_CLUBS_PAGE === totalPages ? 'disabled' : ''} onclick="changeClubsPage(${CURRENT_CLUBS_PAGE + 1})">Next ›</button>
              <button type="button" class="btn btn-outline btn-sm" ${CURRENT_CLUBS_PAGE === totalPages ? 'disabled' : ''} onclick="changeClubsPage(${totalPages})">Last »</button>
            </div>
          `;
        }
      } else {
        if (pBar) pBar.style.display = "none";
      }

      tbody.innerHTML = renderList.map(c => {
        const doaVal = c.date_of_approval || c.submission_timestamp || "";
        const doaDisplay = doaVal ? (typeof formatDateDisplay === "function" ? formatDateDisplay(doaVal) : doaVal.split("T")[0]) : "-";
        const lrdVal = c.last_renewal_date || "";
        const lrdDisplay = lrdVal ? (typeof formatDateDisplay === "function" ? formatDateDisplay(lrdVal) : lrdVal.split("T")[0]) : "None (Initial)";
        const renDisplay = c.renewal_date || c.next_renewal_date || "-";

        return `
          <tr>
            <td><code>${escapeHtml(c.club_id)}</code></td>
            <td><code>${escapeHtml(c.reg_no || 'Pending')}</code></td>
            <td><a href="https://admin.club.ndl.iitkgp.ac.in/club-details/${encodeURIComponent(c.club_id || '')}" target="_blank" rel="noopener noreferrer" class="club-name-link" onclick="event.stopPropagation();" title="View details for ${escapeHtml(c.institution_name || c.club_id || 'club')} on NDLI Admin Portal"><strong>${escapeHtml(c.institution_name || c.club_id || '-')}</strong></a></td>
            <td>${escapeHtml(c.state)}</td>
            <td><span class="pill pill-primary">${escapeHtml(c.zone)}</span></td>
            <td style="font-family: monospace; font-size: 0.85rem;">${escapeHtml(doaDisplay)}</td>
            <td style="font-family: monospace; font-size: 0.85rem; color: #b45309;">${escapeHtml(lrdDisplay)}</td>
            <td style="font-family: monospace; font-size: 0.85rem; font-weight: 700; color: #15803d;">${escapeHtml(renDisplay)}</td>
            <td><span class="pill ${((s) => /^(pending|expiring)/i.test(s) ? 'pill-warning' : /^(overdue|expired|unresolved|blocked|suspended|reject)/i.test(s) ? 'pill-danger' : /^(inactive)/i.test(s) ? 'pill-outline' : /^(approved|active)/i.test(s) ? 'pill-success' : 'pill-outline')(c.status || 'Approved')}">${escapeHtml(c.status || 'Approved')}</span></td>
            <td>
              <div style="display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap;">
                <button class="btn btn-outline btn-sm" data-club-id="${escapeHtml(c.club_id)}" onclick="openEditModalById(this.dataset.clubId)">
                  Edit / Renew
                </button>
                <button class="btn btn-warning btn-sm" data-club-id="${escapeHtml(c.club_id)}" onclick="openEditModalById(this.dataset.clubId, true)" title="Report unresolved issue and set reminder">
                  Report Issue
                </button>
              </div>
            </td>
          </tr>
        `;
      }).join("");
    }

    function filterClubsInMemory(clubs, query) {
      if (!clubs || !clubs.length) return [];
      if (!query || !query.trim()) return clubs;
      const q = query.trim().toLowerCase();
      return clubs.filter(c => {
        return (c.club_id && String(c.club_id).toLowerCase().includes(q)) ||
               (c.institution_name && String(c.institution_name).toLowerCase().includes(q)) ||
               (c.state && String(c.state).toLowerCase().includes(q)) ||
               (c.zone && String(c.zone).toLowerCase().includes(q)) ||
               (c.reg_no && String(c.reg_no).toLowerCase().includes(q)) ||
               (c.patron_email && String(c.patron_email).toLowerCase().includes(q)) ||
               (c.president_email && String(c.president_email).toLowerCase().includes(q)) ||
               (c.secretary_email && String(c.secretary_email).toLowerCase().includes(q));
      });
    }

    function openEditModalById(clubId, focusIssue = false) {
      const club = (CURRENT_SEARCH_RESULTS && CURRENT_SEARCH_RESULTS.find(c => c.club_id === clubId)) ||
                   (ALL_CLUBS_CACHE && ALL_CLUBS_CACHE.find(c => c.club_id === clubId));
      if (club) {
        openEditModal(club);
        if (focusIssue) {
          setTimeout(() => {
            const noteEl = document.getElementById("issue-note-input");
            if (noteEl) {
              noteEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
              noteEl.focus();
            }
          }, 200);
        }
      }
    }

    // Tab Activation Hook for Universal Club Search & Edit
    function onSearchTabActivated() {
      const currentInput = (document.getElementById("search-input")?.value || "").trim();
      if (ALL_CLUBS_CACHE && ALL_CLUBS_CACHE.length > 0) {
        // Instant 0ms cached render!
        if (currentInput) {
          const filtered = filterClubsInMemory(ALL_CLUBS_CACHE, currentInput);
          CURRENT_SEARCH_RESULTS = filtered;
          renderClubsTable(filtered);
        } else {
          CURRENT_SEARCH_RESULTS = ALL_CLUBS_CACHE;
          renderClubsTable(ALL_CLUBS_CACHE);
        }
        // Non-blocking background revalidation if cache is older than 45s
        if (Date.now() - LAST_CLUBS_FETCH_TIME > 45000) {
          performUniversalSearch(currentInput, false);
        }
      } else {
        performUniversalSearch(currentInput, false);
      }
    }

    function onTabActivated(targetId) {
      if (targetId === "tab-search") {
        onSearchTabActivated();
      } else if (targetId === "tab-history") {
        onHistoryTabActivated();
      }
    }

    // Universal Search with In-Memory Caching & Instant 0ms Filtering
    async function performUniversalSearch(query = "", forceRefresh = false) {
      const tbody = document.getElementById("search-results-tbody");
      const cleanQ = String(query || "").trim();

      if (forceRefresh) {
        ALL_CLUBS_CACHE = null;
      }

      // Fast-path: Instant client-side filtering from memory if cache exists
      if (ALL_CLUBS_CACHE && ALL_CLUBS_CACHE.length > 0 && !forceRefresh) {
        const filtered = filterClubsInMemory(ALL_CLUBS_CACHE, cleanQ);
        CURRENT_SEARCH_RESULTS = filtered;
        renderClubsTable(filtered);

        if (Date.now() - LAST_CLUBS_FETCH_TIME < 45000) {
          return;
        }
      }

      if (IS_CLUBS_FETCHING) {
        PENDING_SEARCH_QUERY = cleanQ;
        return;
      }

      // Show animated spinner only if table currently has no cached rows displayed
      if (tbody && (!ALL_CLUBS_CACHE || ALL_CLUBS_CACHE.length === 0)) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--primary); padding: 2rem;"><span style="display: inline-block; animation: spin 1s linear infinite; margin-right: 0.5rem;">⏳</span> Loading clubs database...</td></tr>';
      }

      IS_CLUBS_FETCHING = true;
      try {
        const fetchUrl = cleanQ ? `/api/clubs/search?q=${encodeURIComponent(cleanQ)}` : `/api/clubs/search?q=`;
        const res = await apiRequest(fetchUrl);
        const data = (res && res.data) || {};
        const results = data.results || data.clubs || [];

        if (res.ok) {
          if (!cleanQ) {
            ALL_CLUBS_CACHE = results;
            LAST_CLUBS_FETCH_TIME = Date.now();
            CURRENT_SEARCH_RESULTS = results;
            renderClubsTable(results);
          } else {
            CURRENT_SEARCH_RESULTS = results;
            renderClubsTable(results);
            // Also seed full cache in background if missing
            if (!ALL_CLUBS_CACHE) {
              setTimeout(() => {
                apiRequest('/api/clubs/search?q=').then(r => {
                  if (r.ok) {
                    const allClubs = (r.data && (r.data.results || r.data.clubs)) || [];
                    if (allClubs.length) {
                      ALL_CLUBS_CACHE = allClubs;
                      LAST_CLUBS_FETCH_TIME = Date.now();
                    }
                  }
                }).catch(() => {});
              }, 100);
            }
          }
        } else {
          if (tbody && (!ALL_CLUBS_CACHE || ALL_CLUBS_CACHE.length === 0)) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #dc2626; padding: 1.5rem;"><span>⚠️ Unable to load clubs database.</span> <button class="btn btn-outline btn-sm" style="margin-left: 0.75rem;" onclick="performUniversalSearch(\'\', true)">↻ Retry</button></td></tr>';
          }
        }
      } catch (err) {
        if (tbody && (!ALL_CLUBS_CACHE || ALL_CLUBS_CACHE.length === 0)) {
          tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #dc2626; padding: 1.5rem;"><span>⚠️ Connection error while loading clubs.</span> <button class="btn btn-outline btn-sm" style="margin-left: 0.75rem;" onclick="performUniversalSearch(\'\', true)">↻ Retry</button></td></tr>';
        }
      } finally {
        IS_CLUBS_FETCHING = false;
        if (PENDING_SEARCH_QUERY !== null) {
          const nextQ = PENDING_SEARCH_QUERY;
          PENDING_SEARCH_QUERY = null;
          performUniversalSearch(nextQ, false);
        }
      }
    }

    function escapeHtml(str) {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

