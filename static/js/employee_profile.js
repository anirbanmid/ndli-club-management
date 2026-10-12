    // =============================================================
    // 3. PORTAL CORE CONTROLLER (Profile, Quota, SEC A/B/C, Search)
    // =============================================================
    async function renderEmployeeProfile() {
      const liveProf = (EMP_PROFILES && EMP_PROFILES[CURRENT_EMP_ID]) || await fetchLiveProfile(CURRENT_EMP_ID);
      const prof = liveProf || EMP_PROFILES[CURRENT_EMP_ID] || (CURRENT_USER_SESSION ? {
        name: CURRENT_USER_SESSION.full_name,
        zone: CURRENT_USER_SESSION.zone,
        states: CURRENT_USER_SESSION.assigned_states
      } : {
        name: `Employee ${CURRENT_EMP_ID}`,
        zone: "Regional",
        states: "Assigned Jurisdiction"
      });
      const empIdEl = document.getElementById("current-emp-id");
      const nameEl = document.getElementById("current-name");
      const zoneEl = document.getElementById("current-zone");
      const statesEl = document.getElementById("current-states");
      const exportEmpEl = document.getElementById("export-emp-id-label");

      if (empIdEl) empIdEl.innerText = CURRENT_EMP_ID;
      if (nameEl) nameEl.innerText = prof.name;
      if (exportEmpEl) exportEmpEl.innerText = CURRENT_EMP_ID;
      const zoneText = (prof.zone || "Regional").endsWith("Zone") ? prof.zone : `${prof.zone} Zone`;
      if (zoneEl) zoneEl.innerText = zoneText;
      if (statesEl) statesEl.innerHTML = `<strong>Assigned States:</strong> ${prof.states}`;
    }

