    // =============================================================
    // HTML ESCAPING UTILITY
    // =============================================================
    function escapeHtml(str) {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    // =============================================================
    // LOCAL TIMESTAMP FORMATTER (IST - ASIA/KOLKATA)
    // =============================================================
    function formatLocalTimestamp(ts) {
      if (!ts) return "-";
      try {
        let d = new Date(ts);
        if (isNaN(d.getTime())) {
          if (typeof ts === "string" && !ts.includes("Z") && !ts.includes("+")) {
            d = new Date(ts.replace(" ", "T") + "Z");
          }
        }
        if (isNaN(d.getTime())) return String(ts);

        const parts = new Intl.DateTimeFormat('en-IN', {
          timeZone: 'Asia/Kolkata',
          day: '2-digit',
          month: 'short',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: true
        }).formatToParts(d);
        const m = {};
        for (const p of parts) m[p.type] = p.value;
        const monthClean = (m.month || "").replace(".", "");
        return `${m.day} ${monthClean} ${m.year}, ${m.hour}:${m.minute}:${m.second} ${(m.dayPeriod || '').toUpperCase()} IST`;
      } catch (e) {
        return String(ts);
      }
    }

    // =============================================================
    // NEXT RENEWAL DATE CALCULATOR (1-YEAR CYCLE)
    // =============================================================
    function calculateNextRenewalDate(estDateStr, lastRenDateStr) {
      function parseDate(s) {
        if (!s || s === "-" || !String(s).trim()) return null;
        const clean = String(s).split("T")[0].split(" ")[0].trim();
        let m = clean.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
        if (m) {
          const dt = new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
          return isNaN(dt.getTime()) ? null : dt;
        }
        m = clean.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
        if (m) {
          const dt = new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10));
          return isNaN(dt.getTime()) ? null : dt;
        }
        const dt = new Date(clean);
        return isNaN(dt.getTime()) ? null : dt;
      }

      const est = parseDate(estDateStr);
      const ren = parseDate(lastRenDateStr);

      let latest = null;
      if (est && ren) {
        latest = est.getTime() >= ren.getTime() ? est : ren;
      } else if (ren) {
        latest = ren;
      } else if (est) {
        latest = est;
      } else {
        latest = new Date();
      }

      let nextYear = latest.getFullYear() + 1;
      let nextMonth = latest.getMonth();
      let nextDay = latest.getDate();

      if (nextMonth === 1 && nextDay === 29) {
        const isLeap = (nextYear % 4 === 0 && nextYear % 100 !== 0) || (nextYear % 400 === 0);
        if (!isLeap) nextDay = 28;
      }

      const next = new Date(nextYear, nextMonth, nextDay);
      const yr = next.getFullYear();
      const mo = String(next.getMonth() + 1).padStart(2, "0");
      const day = String(next.getDate()).padStart(2, "0");
      return `${yr}-${mo}-${day}`;
    }

