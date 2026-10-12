    // =========================================================================
    // FEATURE 1: DOWNLOAD MASTER CSV (master_clubs.csv)
    // =========================================================================
    function downloadMasterCSV() {
      fetchMasterCSVAsBlob();
    }

    async function fetchMasterCSVAsBlob() {
      const adminToken = sessionStorage.getItem("ndli_admin_token");
      try {
        const res = await fetch("/api/admin/download/master-clubs", {
          headers: adminToken ? { "Authorization": `Bearer ${adminToken}` } : {}
        });
        if (!res.ok) {
          showAlert("admin-alert", "Master CSV download failed. Please sign in as Administrator and try again.", "danger");
          return;
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        const objUrl = URL.createObjectURL(blob);
        a.href = objUrl;
        a.download = "master_clubs.csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(objUrl);
      } catch (err) {
        showAlert("admin-alert", "Master CSV download failed: " + err.message, "danger");
      }
    }

