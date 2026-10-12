    // Quota and Activities loader
    async function loadEmployeeQuota() {
      let clubsCount = 0;
      let supportCount = 0;
      // R29v2: the quota card mirrors the admin performance matrix columns
      let onlineShown = 0;
      let offlineShown = 0;
      let otherShown = 0;

      const pRes = await apiRequest(`/api/employees/profile?id=${encodeURIComponent(CURRENT_EMP_ID)}`);
      if (pRes.ok && pRes.data && pRes.data.employee) {
        const emp = pRes.data.employee;
        clubsCount = parseInt(emp.clubs_approved_count !== undefined ? emp.clubs_approved_count : 0, 10) || 0;
        supportCount = parseInt(emp.support_logs_count !== undefined ? emp.support_logs_count : 0, 10) || 0;
        // R30: migrated-history split — shown only when history exists
        const legacyClubs = parseInt(emp.legacy_clubs_count || 0, 10) || 0;
        const legacySupport = parseInt(emp.legacy_support_count || 0, 10) || 0;
        // R29v2: the four cells are exactly the admin performance matrix
        // columns (clubs / online training / offline training / other
        // supports), each cell being live work + migrated history.
        const liveOnline = parseInt(emp.live_online_training || 0, 10) || 0;
        const liveOffline = parseInt(emp.live_offline_training || 0, 10) || 0;
        const liveOther = parseInt(emp.live_other_supports !== undefined ? emp.live_other_supports : 0, 10) || 0;
        const migWorkshops = parseInt(emp.legacy_online_workshops_count || 0, 10) || 0;
        onlineShown = liveOnline + migWorkshops;
        offlineShown = liveOffline;
        otherShown = liveOther + legacySupport;
        const onlineCellEl = document.getElementById("quota-online-count");
        const offlineCellEl = document.getElementById("quota-offline-count");
        if (onlineCellEl) onlineCellEl.innerText = String(onlineShown);
        if (offlineCellEl) offlineCellEl.innerText = String(offlineShown);
        const legacyLine = document.getElementById("quota-legacy-line");
        if (legacyLine) {
          if (legacyClubs > 0 || legacySupport > 0 || migWorkshops > 0) {
            legacyLine.style.display = "block";
            const lc = document.getElementById("quota-legacy-clubs");
            const ls = document.getElementById("quota-legacy-support");
            if (lc) lc.innerText = String(legacyClubs);
            if (ls) ls.innerText = String(legacySupport);
            // R29: also show the LIVE half so the line reads "X live + Y migrated"
            // (the old "incl." wording made the migrated part look contained in
            // the headline number, which it is not).
            // R38: live halves arrive computed from db/counting_rules.py —
            // never derived by subtraction here.
            const liveClubsShown = parseInt(emp.live_clubs_approved_count !== undefined ? emp.live_clubs_approved_count : 0, 10) || 0;
            const liveSupportShown = parseInt(emp.live_support_logs_count !== undefined ? emp.live_support_logs_count : 0, 10) || 0;
            const lvc = document.getElementById("quota-live-clubs");
            const lvs = document.getElementById("quota-live-support");
            if (lvc) lvc.innerText = String(liveClubsShown);
            if (lvs) lvs.innerText = String(liveSupportShown);
            // R29v2: the online workshops half gets the same split treatment
            const lo = document.getElementById("quota-legacy-online");
            const lvo = document.getElementById("quota-live-online");
            if (lo) lo.innerText = String(migWorkshops);
            if (lvo) lvo.innerText = String(liveOnline);
          } else {
            legacyLine.style.display = "none";
          }
        }
        // R30v2: migrated-history strip in the Activity History tab
        const mhStrip = document.getElementById("migrated-history-strip");
        if (mhStrip) {
          const legacyWorkshops = parseInt(emp.legacy_online_workshops_count || 0, 10) || 0;
          if (legacyClubs > 0 || legacySupport > 0) {
            mhStrip.style.display = "block";
            const fy = emp.legacy_first_year, ly = emp.legacy_last_year;
            const spanTxt = (fy && ly) ? ` (${fy}-${ly})` : "";
            const mhSum = document.getElementById("mig-hist-summary");
            if (mhSum) mhSum.innerText = `${legacyClubs} club approvals / ${legacySupport} support interactions / ${legacyWorkshops} online workshops${spanTxt}`;
          } else {
            mhStrip.style.display = "none";
          }
        }
      }

      const clubsEl = document.getElementById("quota-clubs-count");
      const supportEl = document.getElementById("quota-support-count");
      const onlineCell = document.getElementById("quota-online-count");
      const offlineCell = document.getElementById("quota-offline-count");
      if (clubsEl) clubsEl.innerText = String(clubsCount);
      // R29v2: this cell is "Other Support" now (the matrix's other column)
      if (supportEl) supportEl.innerText = String(otherShown);
      if (onlineCell) onlineCell.innerText = String(onlineShown);
      if (offlineCell) offlineCell.innerText = String(offlineShown);
    }

