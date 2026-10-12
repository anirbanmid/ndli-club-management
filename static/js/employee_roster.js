    // Continuous Backend Synchronization
    async function fetchLiveRoster() {
      try {
        const res = await apiRequest("/api/employees/roster");
        if (res.ok && res.data && res.data.employees) {
          const freshProfiles = {};
          res.data.employees.forEach(emp => {
            freshProfiles[emp.id] = {
              name: emp.full_name,
              zone: emp.zone,
              email: emp.email,
              states: emp.assigned_states,
              is_active: emp.is_active
            };
          });
          EMP_PROFILES = freshProfiles;
          renderOfficerChips();
        }
      } catch (e) {
        console.warn("Could not fetch live employee roster:", e);
      } finally {
        renderOfficerChips();
      }
    }

    async function fetchLiveProfile(empId) {
      if (!empId) return null;
      try {
        const res = await apiRequest(`/api/employees/profile?id=${encodeURIComponent(empId)}`);
        if (res.ok && res.data && res.data.found && res.data.employee) {
          const emp = res.data.employee;
          EMP_PROFILES[emp.id] = {
            name: emp.full_name,
            zone: emp.zone,
            email: emp.email,
            states: emp.assigned_states,
            is_active: emp.is_active
          };
          if (CURRENT_USER_SESSION && CURRENT_USER_SESSION.user_id === emp.id) {
            CURRENT_USER_SESSION.full_name = emp.full_name;
            CURRENT_USER_SESSION.zone = emp.zone;
            CURRENT_USER_SESSION.assigned_states = emp.assigned_states;
            CURRENT_USER_SESSION.email = emp.email;
          }
          return EMP_PROFILES[emp.id];
        }
      } catch (e) {
        console.warn("Error fetching live profile:", e);
      }
      return EMP_PROFILES[empId] || null;
    }

