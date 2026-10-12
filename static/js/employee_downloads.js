    // =========================================================================
    // FEATURE 3: DOWNLOAD ACTIVITY LOG & DOWNLOAD CLUBS LOG
    // =========================================================================
    async function downloadEmployeeActivityLog() {
      await downloadEmployeeCSV(
        `/api/employee/download/activity-log?emp_id=${encodeURIComponent(CURRENT_EMP_ID)}`,
        "activity_log.csv"
      );
    }

    async function downloadEmployeeClubsLog() {
      await downloadEmployeeCSV(
        `/api/employee/download/clubs-log?emp_id=${encodeURIComponent(CURRENT_EMP_ID)}`,
        "clubs.csv"
      );
    }

    async function downloadEmployeeCSV(url, filename) {
      const token = sessionStorage.getItem("ndli_employee_token") || sessionStorage.getItem("ndli_token");
      try {
        const res = await fetch(url, {
          headers: token ? { "Authorization": `Bearer ${token}` } : {}
        });
        if (!res.ok) {
          showAlert("global-alert", "Download failed. Please log in again and retry.", "danger");
          return;
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        const objUrl = URL.createObjectURL(blob);
        a.href = objUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(objUrl);
      } catch (err) {
        showAlert("global-alert", "Download failed: " + err.message, "danger");
      }
    }

