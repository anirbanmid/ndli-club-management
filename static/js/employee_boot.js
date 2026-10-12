    // Default initial profiles fallback (dynamically updated from master backend database)
    let EMP_PROFILES = {
      "EMP01": { name: "Rohan Sharma", zone: "North", email: "emp.north@ndli.edu.in", states: "Jammu & Kashmir, Ladakh, Uttarakhand, Himachal Pradesh, Chandigarh, Punjab, Haryana, Delhi, Uttar Pradesh" },
      "EMP02": { name: "Pooja Verma", zone: "Central", email: "emp.central@ndli.edu.in", states: "Madhya Pradesh, Chhattisgarh" },
      "EMP03": { name: "Amit Patel", zone: "West", email: "emp.west@ndli.edu.in", states: "Rajasthan, Gujarat, Maharashtra, Goa, Daman and Diu, Dadar & Nagar Haveli" },
      "EMP04": { name: "Debabrata Ghosh", zone: "East", email: "emp.east@ndli.edu.in", states: "Bihar, Jharkhand, West Bengal, Odisha" },
      "EMP05": { name: "Mayanglambam Singh", zone: "North East", email: "emp.northeast@ndli.edu.in", states: "Sikkim, Assam, Arunachal Pradesh, Meghalaya, Manipur, Tripura, Nagaland, Mizoram" },
      "EMP06": { name: "K. Venkatesh", zone: "South 1", email: "emp.south1@ndli.edu.in", states: "Andhra Pradesh, Telangana, Karnataka" },
      "EMP07": { name: "Ananya Nair", zone: "South 2", email: "emp.south2@ndli.edu.in", states: "Tamil Nadu, Puducherry, Kerala, Andaman & Nicobar Island, Lakshadweep" }
    };

    // Active employee identity comes ONLY from a real signed-in session (normalized to uppercase).
    // No hardcoded fallback: when no employee is signed in there must be no phantom workspace (e.g. auto EMP01).
    let CURRENT_EMP_ID = (sessionStorage.getItem("ndli_employee_id") || sessionStorage.getItem("ndli_current_emp_id") || "").toUpperCase();
    let CURRENT_USER_SESSION = null;

    const DEFAULT_INDIAN_STATES = [
      "Andaman & Nicobar Island", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
      "Chandigarh", "Chhattisgarh", "Dadar & Nagar Haveli", "Daman and Diu", "Delhi",
      "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu & Kashmir",
      "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep",
      "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
      "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan",
      "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
      "Uttarakhand", "West Bengal"
    ];
    let ALL_STATES = [...DEFAULT_INDIAN_STATES];

    // Dual-alias resolution for #sec-c-state, #sec-c-zone, and #c-doa-display
    try {
      if (typeof document !== "undefined") {
        if (document.getElementById) {
          const _origGetById = document.getElementById.bind(document);
          document.getElementById = function(id) {
            let el = _origGetById(id);
            if (!el && id === "sec-c-state") el = _origGetById("c-state");
            if (!el && id === "c-state") el = _origGetById("sec-c-state");
            if (!el && id === "sec-c-zone") el = _origGetById("c-zone");
            if (!el && id === "c-zone") el = _origGetById("sec-c-zone");
            if (!el && id === "c-doa-display") el = _origGetById("c-timestamp-display");
            return el;
          };
        }
        if (document.querySelector) {
          const _origQuerySelector = document.querySelector.bind(document);
          document.querySelector = function(selector) {
            let el = _origQuerySelector(selector);
            if (!el && selector === "#sec-c-state") el = _origQuerySelector("#c-state") || _origQuerySelector('[data-alias="sec-c-state"]');
            if (!el && selector === "#c-state") el = _origQuerySelector("#sec-c-state");
            if (!el && selector === "#sec-c-zone") el = _origQuerySelector("#c-zone") || _origQuerySelector('[data-alias="sec-c-zone"]');
            if (!el && selector === "#c-zone") el = _origQuerySelector("#sec-c-zone");
            if (!el && selector === "#c-doa-display") el = _origQuerySelector("#c-timestamp-display");
            return el;
          };
        }
        if (document.querySelectorAll) {
          const _origQuerySelectorAll = document.querySelectorAll.bind(document);
          document.querySelectorAll = function(selector) {
            const list = _origQuerySelectorAll(selector);
            if ((!list || list.length === 0) && selector === "#sec-c-state") {
              return _origQuerySelectorAll("#c-state");
            }
            if ((!list || list.length === 0) && selector === "#sec-c-zone") {
              return _origQuerySelectorAll("#c-zone");
            }
            return list;
          };
        }
      }
    } catch (e) {}

