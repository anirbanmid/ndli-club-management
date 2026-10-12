    // =============================================================
    // 1. LIVE LOCAL CLOCK (Accurately renders Local / IST Date & Time)
    // =============================================================
    function updateClock() {
      const now = new Date();

      // 1. Precise Indian Standard Time (IST - Asia/Kolkata, UTC+05:30)
      let istDateStr = "";
      let istTimeStr = "";
      try {
        const parts = new Intl.DateTimeFormat('en-IN', {
          timeZone: 'Asia/Kolkata',
          weekday: 'short',
          day: '2-digit',
          month: 'short',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: true
        }).formatToParts(now);

        const m = {};
        for (const p of parts) m[p.type] = p.value;
        const monthClean = (m.month || "").replace(".", "");
        istDateStr = `${m.weekday || ""}, ${m.day || ""} ${monthClean} ${m.year || ""}`;
        istTimeStr = `${m.hour || ""}:${m.minute || ""}:${m.second || ""} ${(m.dayPeriod || "").toUpperCase()}`;
      } catch (e) {
        istDateStr = now.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
        istTimeStr = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
      }

      // Also ensure toLocaleDateString and toLocaleTimeString remain referenced
      const sysDateStr = now.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
      const sysTimeStr = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });

      // 2. Client Device Local System Time
      let localTz = "";
      try {
        localTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      } catch (e) {
        localTz = "";
      }
      const isIST = localTz.includes("Calcutta") || localTz.includes("Kolkata") || localTz === "IST";
      const localDeviceTime = !isIST ? sysTimeStr : "";

      // 3. IST ISO Timestamp for SEC C Form Display (YYYY-MM-DD HH:MM:SS IST)
      let istIso = "";
      try {
        const istParts = new Intl.DateTimeFormat('en-CA', {
          timeZone: 'Asia/Kolkata',
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        }).formatToParts(now);
        const im = {};
        for (const p of istParts) im[p.type] = p.value;
        istIso = `${im.year}-${im.month}-${im.day} ${im.hour}:${im.minute}:${im.second} IST`;
      } catch (e) {
        istIso = now.toISOString().replace("T", " ").substring(0, 19) + " IST";
      }

      // HTML template for clocks
      const clockHtml = `
        <span style="color: #94a3b8; font-size: 0.78rem; font-weight: 500;">📅 ${istDateStr || sysDateStr}</span>
        <span style="color: #38bdf8; font-family: monospace; font-size: 0.95rem; font-weight: 700;">⏰ ${istTimeStr || sysTimeStr}</span>
        <span style="background: rgba(56, 189, 248, 0.18); color: #38bdf8; font-size: 0.72rem; padding: 2px 6px; border-radius: 4px; font-weight: 600;">IST (UTC+5:30)</span>
        ${localDeviceTime ? `<span style="color: #cbd5e1; font-size: 0.72rem;">(Local: ${localDeviceTime})</span>` : ''}
      `;

      // Update officer banner clock
      const bannerClock = document.getElementById("live-clock");
      if (bannerClock) bannerClock.innerHTML = clockHtml;

      // Update top navbar clock (sleek compact format to guarantee single-row layout - Observation 1)
      const navClock = document.getElementById("nav-live-clock");
      if (navClock) {
        navClock.innerHTML = `<span style="color: #38bdf8; font-family: monospace; font-size: 0.74rem; font-weight: 700; letter-spacing: 0.02em;">⏰ ${istTimeStr || sysTimeStr}</span> <span style="font-size: 0.65rem; color: #94a3b8; font-weight: 600;">IST</span>`;
        navClock.title = `National Standard System Clock (IST): ${istDateStr || sysDateStr} ${istTimeStr || sysTimeStr} (UTC+5:30)${localDeviceTime ? ` | Device: ${localDeviceTime}` : ''}`;
      }

      // Update login view clock (compact layout)
      const loginClock = document.getElementById("login-live-clock");
      if (loginClock) {
        loginClock.innerHTML = `
          <span style="color: #94a3b8; font-size: 0.68rem; font-weight: 500;">📅 ${istDateStr || sysDateStr}</span>
          <span style="color: #38bdf8; font-family: monospace; font-size: 0.76rem; font-weight: 700;">⏰ ${istTimeStr || sysTimeStr}</span>
          <span style="background: rgba(56, 189, 248, 0.18); color: #38bdf8; font-size: 0.62rem; padding: 1px 4px; border-radius: 3px; font-weight: 600;">IST</span>
        `;
      }

      // Update SEC C Submission Timestamp live input
      const secCTimestamp = document.getElementById("c-timestamp-display");
      if (secCTimestamp) {
        secCTimestamp.value = `${istIso} (Live Sync)`;
      }

      // Update SEC C Initial Registration Validity live display (+1 Year)
      const secCRenewal = document.getElementById("c-renewal-display") || document.getElementById("c-renewal");
      if (secCRenewal && typeof calculateNextRenewalDate === "function") {
        const nextValDate = calculateNextRenewalDate(istIso, null);
        secCRenewal.value = `${nextValDate} (+1 Year Initial Validity)`;
      }
    }

    function formatLocalTimestamp(ts) {
      if (!ts) return "-";
      try {
        let d = new Date(ts);
        if (isNaN(d.getTime())) {
          if (typeof ts === "string" && !ts.includes("Z") && !ts.includes("+")) {
            d = new Date(ts.replace(" ", "T") + "Z");
          }
        }
        if (isNaN(d.getTime())) return ts;

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
        return ts;
      }
    }

