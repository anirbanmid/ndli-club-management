    async function loadStates() {
      try {
        let res = await apiRequest("/api/state-zone/map");
        if (!res || !res.ok || !res.data || (!res.data.all_states && !res.data.states && !res.data.zone_to_states && !res.data.map)) {
          res = await apiRequest("/api/states");
        }
        if (!res || !res.ok || !res.data || (!res.data.all_states && !res.data.states && !res.data.zone_to_states && !res.data.map)) {
          res = await apiRequest("/api/states-zones");
        }
        if (res && res.ok && res.data) {
          let fetched = res.data.all_states || res.data.states;
          if (!fetched || !Array.isArray(fetched) || fetched.length === 0) {
            const zMap = res.data.zone_to_states || res.data.map;
            if (zMap && typeof zMap === "object") {
              fetched = Object.values(zMap).flat();
            }
          }
          if (Array.isArray(fetched) && fetched.length > 0) {
            ALL_STATES = Array.from(new Set(fetched.map(s => typeof s === "string" ? s : (s.name || s.state || String(s))))).sort();
          }
        }
      } catch (e) {
        console.warn("Could not fetch states from server, using fallback list:", e);
      } finally {
        if (!ALL_STATES || ALL_STATES.length === 0) {
          ALL_STATES = (typeof CLIENT_ZONE_MAP !== "undefined")
            ? Array.from(new Set(Object.values(CLIENT_ZONE_MAP).flat())).sort()
            : [...DEFAULT_INDIAN_STATES];
        }
        populateStateSelect("c-state");
        populateStateSelect("sec-c-state");
        populateStateSelect("edit-state");
      }
    }

    function populateStateSelect(elemId) {
      const el = document.getElementById(elemId) || (typeof document.querySelector === "function" ? (document.querySelector(`#${elemId}`) || document.querySelector(`[data-alias="${elemId}"]`)) : null);
      if (!el) return;
      const currentVal = el.value;
      const list = (ALL_STATES && ALL_STATES.length > 0) ? ALL_STATES : DEFAULT_INDIAN_STATES;

      // If already populated with the full options list and matching first state, avoid disruptive redraw
      if (el.options && el.options.length === list.length + 1 && el.options[1] && el.options[1].value === list[0]) {
        if (currentVal && el.value !== currentVal) {
          el.value = currentVal;
        }
        return;
      }

      el.innerHTML = '<option value="">-- Select State / Union Territory --</option>';
      list.forEach(stItem => {
        const st = (typeof stItem === "string") ? stItem : (stItem.name || stItem.state || String(stItem));
        if (!st || st === "[object Object]") return;
        const opt = document.createElement("option");
        opt.value = st;
        opt.textContent = st;
        opt.text = st;
        if (currentVal && currentVal === st) {
          opt.selected = true;
        }
        el.appendChild(opt);
      });
      if (currentVal) el.value = currentVal;
    }

    // Defensive client-side zone mapping fallback
    if (typeof clientGetZoneForState !== "function") {
      window.clientGetZoneForState = function(stateName) {
        if (!stateName) return "";
        const map = (typeof CLIENT_ZONE_MAP !== "undefined") ? CLIENT_ZONE_MAP : {
          "North": ["Jammu & Kashmir", "Ladakh", "Uttarakhand", "Himachal Pradesh", "Chandigarh", "Punjab", "Haryana", "Delhi", "Uttar Pradesh"],
          "Central": ["Madhya Pradesh", "Chhattisgarh"],
          "West": ["Rajasthan", "Gujarat", "Maharashtra", "Goa", "Daman and Diu", "Dadar & Nagar Haveli"],
          "East": ["Bihar", "Jharkhand", "West Bengal", "Odisha"],
          "North East": ["Sikkim", "Assam", "Arunachal Pradesh", "Meghalaya", "Manipur", "Tripura", "Nagaland", "Mizoram"],
          "South": ["Andhra Pradesh", "Telangana", "Karnataka", "Tamil Nadu", "Puducherry", "Kerala", "Andaman & Nicobar Island", "Lakshadweep"]
        };
        const norm = stateName.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9 ]/g, "").trim().replace(/\s+/g, " ");
        for (const [zone, states] of Object.entries(map)) {
          for (const st of states) {
            const stNorm = st.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9 ]/g, "").trim().replace(/\s+/g, " ");
            if (stNorm === norm) return zone;
          }
        }
        if (norm.includes("delhi")) return "North";
        if (norm.includes("jammu") || norm.includes("kashmir") || norm === "j and k") return "North";
        if (norm.includes("pondicherry")) return "South";
        if (norm.includes("orissa")) return "East";
        return "";
      };
    }

    // Auto-map zone on state selection
    function handleStateSelection(stateName) {
      const zone = (typeof clientGetZoneForState === "function")
        ? clientGetZoneForState(stateName)
        : "";
      const zoneEl = document.getElementById("c-zone") || document.getElementById("sec-c-zone");
      if (zoneEl) zoneEl.value = zone || "Unknown Zone";
    }

    function handleEditStateSelection(stateName) {
      const zone = (typeof clientGetZoneForState === "function")
        ? clientGetZoneForState(stateName)
        : "";
      const zoneEl = document.getElementById("edit-zone");
      if (zoneEl) zoneEl.value = zone || "Unknown Zone";
    }

