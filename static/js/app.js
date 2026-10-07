/**
 * NDLI Club Management and Employee Activity Tracking System
 * Modern Client-Side Controller (IIT Kharagpur)
 */

// Zone mapping fallback for instant client-side auto-population
const CLIENT_ZONE_MAP = {
  "North": ["Jammu & Kashmir", "Ladakh", "Uttarakhand", "Himachal Pradesh", "Chandigarh", "Punjab", "Haryana", "Delhi", "Uttar Pradesh"],
  "Central": ["Madhya Pradesh", "Chhattisgarh"],
  "West": ["Rajasthan", "Gujarat", "Maharashtra", "Goa", "Daman and Diu", "Dadar & Nagar Haveli"],
  "East": ["Bihar", "Jharkhand", "West Bengal", "Odisha"],
  "North East": ["Sikkim", "Assam", "Arunachal Pradesh", "Meghalaya", "Manipur", "Tripura", "Nagaland", "Mizoram"],
  "South": ["Andhra Pradesh", "Telangana", "Karnataka", "Tamil Nadu", "Puducherry", "Kerala", "Andaman & Nicobar Island", "Lakshadweep"]
};

function normalizeName(name) {
  if (!name) return "";
  return name.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9 ]/g, "").trim().replace(/\s+/g, " ");
}

function clientGetZoneForState(stateName) {
  if (!stateName) return "";
  const norm = normalizeName(stateName);
  for (const [zone, states] of Object.entries(CLIENT_ZONE_MAP)) {
    for (const st of states) {
      if (normalizeName(st) === norm) return zone;
    }
  }
  // Aliases
  if (norm.includes("delhi")) return "North";
  if (norm.includes("jammu") || norm.includes("kashmir") || norm === "j and k") return "North";
  if (norm.includes("pondicherry")) return "South";
  if (norm.includes("orissa")) return "East";
  return "";
}

// Utility: API caller
async function apiRequest(path, method = "GET", body = null, token = null) {
  const headers = { "Content-Type": "application/json" };
  let authTok = token;
  if (!authTok) {
    const isAdminRoute = path.startsWith("/api/admin/") || path.startsWith("/api/sync/") || path.startsWith("/api/issues/admin");
    if (isAdminRoute) {
      authTok = sessionStorage.getItem("ndli_admin_token") || (sessionStorage.getItem("ndli_role") === "ADMIN" ? sessionStorage.getItem("ndli_token") : null);
    } else {
      authTok = sessionStorage.getItem("ndli_employee_token") || (sessionStorage.getItem("ndli_role") === "EMPLOYEE" ? sessionStorage.getItem("ndli_token") : null) || sessionStorage.getItem("ndli_token") || sessionStorage.getItem("ndli_admin_token");
    }
  }
  if (authTok) {
    headers["Authorization"] = `Bearer ${authTok}`;
  }

  const options = { method, headers };
  if (body) {
    options.body = JSON.stringify(body);
  }

  try {
    const res = await fetch(path, options);
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (parseErr) {
      return { ok: false, status: res.status, data: { error: true, message: `Server error (${res.status}): ${text.slice(0, 150)}` } };
    }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: { error: true, message: err.message || "Network error." } };
  }
}

// UI Alert Helper
function showAlert(containerId, message, type = "success") {
  const c = document.getElementById(containerId);
  if (!c) return;
  c.innerHTML = `
    <div class="alert alert-${type}">
      <span>${type === 'success' ? '✓' : '⚠️'}</span>
      <div>${message}</div>
    </div>
  `;
  c.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  if (type === "success") {
    setTimeout(() => { if (c) c.innerHTML = ""; }, 6000);
  }
}

// Global Tab Switching (ARIA tablist protocol)
// - .tabs containers carry role="tablist", .tab-btn buttons role="tab" with
//   aria-selected / aria-controls (template-side), .tab-panel panels
//   role="tabpanel" + aria-labelledby (template-side).
// - Roving tabindex: only the active tab is tabbable; ArrowLeft/ArrowRight
//   move focus+selection through the strip (wrapping), Home/End jump to the
//   first/last tab. The existing onTabActivated(targetId) hook keeps firing on
//   every activation (click and keyboard alike) — unchanged contract.
function initTabs() {
  document.querySelectorAll(".tabs").forEach(tabContainer => {
    const btns = tabContainer.querySelectorAll(".tab-btn");

    const activateTab = (btn) => {
      const targetId = btn.getAttribute("data-target");
      btns.forEach(b => {
        b.classList.remove("active");
        if (typeof b.setAttribute === "function") {
          b.setAttribute("aria-selected", "false");
          b.setAttribute("tabindex", "-1");
        }
      });
      btn.classList.add("active");
      if (typeof btn.setAttribute === "function") {
        btn.setAttribute("aria-selected", "true");
        btn.setAttribute("tabindex", "0");
      }

      // R19: the tab strip now lives in the sidebar shell while the panels stay
      // in the content column, so the old parentElement scope may contain no
      // panels. Prefer the nearest shell/content root, then fall back to the
      // legacy parent scope, then document — first scope that has panels wins.
      const scopes = [];
      if (typeof tabContainer.closest === "function") {
        const shell = tabContainer.closest(".app-shell");
        if (shell) scopes.push(shell);
      }
      scopes.push(tabContainer.parentElement, document);
      let panelScope = null;
      for (let si = 0; si < scopes.length; si++) {
        const cand = scopes[si];
        if (cand && cand.querySelector(".tab-panel")) { panelScope = cand; break; }
      }
      (panelScope || document).querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) targetPanel.classList.add("active");

      if (typeof onTabActivated === "function") {
        try { onTabActivated(targetId); } catch (e) { console.error(e); }
      }
    };

    btns.forEach(btn => {
      btn.addEventListener("click", () => {
        activateTab(btn);
      });

      // Keyboard: ArrowLeft/ArrowRight/Home/End move focus AND selection.
      btn.addEventListener("keydown", (e) => {
        const key = e.key;
        if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" && key !== "End") return;
        if (typeof e.preventDefault === "function") e.preventDefault();
        const list = Array.prototype.slice.call(btns);
        const idx = list.indexOf(btn);
        let next = null;
        if (key === "ArrowLeft") next = list[(idx - 1 + list.length) % list.length];
        else if (key === "ArrowRight") next = list[(idx + 1) % list.length];
        else if (key === "Home") next = list[0];
        else next = list[list.length - 1];
        if (!next) return;
        activateTab(next);
        if (typeof next.focus === "function") next.focus();
      });
    });

    // Sync initial ARIA + roving-tabindex state with the .active tab.
    btns.forEach(b => {
      if (typeof b.setAttribute !== "function") return;
      const isActive = b.classList.contains("active");
      b.setAttribute("aria-selected", isActive ? "true" : "false");
      b.setAttribute("tabindex", isActive ? "0" : "-1");
    });
  });

  const urlTab = new URLSearchParams(window.location.search).get("tab");
  if (urlTab) {
    const target = urlTab.startsWith("tab-") ? urlTab : "tab-" + urlTab;
    const btn = document.querySelector(`.tab-btn[data-target="${target}"]`);
    if (btn) btn.click();
  }
}

// Auto-run on DOMContentLoaded
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initRippleEffect();
  initScrollReveal();
});

/**
 * Adds a CSS ripple effect to all .btn elements on click.
 * Non-destructive: attaches once per button.
 */
function initRippleEffect() {
  if (typeof document === "undefined") return;
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn");
    if (!btn) return;
    const ripple = document.createElement("span");
    ripple.classList.add("ripple");
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    ripple.style.width = ripple.style.height = size + "px";
    ripple.style.left  = (e.clientX - rect.left - size / 2) + "px";
    ripple.style.top   = (e.clientY - rect.top  - size / 2) + "px";
    btn.appendChild(ripple);
    ripple.addEventListener("animationend", () => ripple.remove(), { once: true });
  }, { passive: true });
}

/**
 * Lightweight IntersectionObserver scroll-reveal for .reveal-card elements.
 * Adds .reveal-visible class when the element enters the viewport.
 */
function initScrollReveal() {
  if (typeof IntersectionObserver === "undefined") return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("reveal-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08 });
  document.querySelectorAll(".reveal-card").forEach(el => observer.observe(el));
}

/**
 * Automatically computes the next renewal date as exactly 1 calendar year (+1 year)
 * from either the establishment/approval date or the last renewal date, whichever is latest.
 */
function calculateNextRenewalDate(estDateStr, lastRenDateStr) {
  function parseDate(s) {
    if (!s || s === "-" || !String(s).trim()) return null;
    const clean = String(s).split("T")[0].split(" ")[0].trim();
    // YYYY-MM-DD or YYYY/MM/DD
    let m = clean.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
    if (m) {
      const dt = new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
      return isNaN(dt.getTime()) ? null : dt;
    }
    // DD-MM-YYYY or DD/MM/YYYY
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
  if (ren) {
    latest = ren;
  } else if (est) {
    latest = est;
  } else {
    latest = new Date();
  }

  let nextYear = latest.getFullYear() + 1;
  let nextMonth = latest.getMonth();
  let nextDay = latest.getDate();

  // Exactly handle Feb 29 leap year rollover (matches Python: 2024-02-29 + 1 yr = 2025-02-28)
  if (nextMonth === 1 && nextDay === 29) {
    const isLeap = (nextYear % 4 === 0 && nextYear % 100 !== 0) || (nextYear % 400 === 0);
    if (!isLeap) {
      nextDay = 28;
    }
  }

  const next = new Date(nextYear, nextMonth, nextDay);
  const yr = next.getFullYear();
  const mo = String(next.getMonth() + 1).padStart(2, "0");
  const day = String(next.getDate()).padStart(2, "0");
  return `${yr}-${mo}-${day}`;
}

function formatDateDisplay(dStr) {
  if (!dStr) return "-";
  try {
    const clean = String(dStr).split("T")[0].split(" ")[0].trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(clean)) {
      const [y, m, d] = clean.split("-");
      return `${d}-${m}-${y}`;
    }
    return dStr;
  } catch (e) {
    return dStr;
  }
}

/**
 * Formats an ISO or standard timestamp string to local IST date and time string.
 */
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

if (typeof window !== "undefined") {
  window.formatLocalTimestamp = formatLocalTimestamp;
  window.calculateNextRenewalDate = calculateNextRenewalDate;
  window.formatDateDisplay = formatDateDisplay;
}

// =============================================================================
// Instant Navigation & Hover Prefetching for Fast Portal Transitions
// =============================================================================
function initFluidPageTransitions() {
  if (typeof document === "undefined" || typeof document.addEventListener !== "function") return;
  if (document.body && document.body.classList) {
    document.body.classList.remove("page-leaving");
  }

  // Pre-warm and prefetch target portals on hover / touchstart for 0ms navigation
  const prefetchedUrls = new Set();
  const prefetchTarget = (url) => {
    if (!url || prefetchedUrls.has(url)) return;
    prefetchedUrls.add(url);
    try {
      const linkEl = document.createElement("link");
      linkEl.rel = "prefetch";
      linkEl.href = url;
      document.head.appendChild(linkEl);
    } catch (err) {}
  };

  document.addEventListener("mouseover", (e) => {
    if (!e || !e.target || typeof e.target.closest !== "function") return;
    const a = e.target.closest("a");
    if (!a) return;
    const href = a.getAttribute ? a.getAttribute("href") : null;
    if (href && (href === "/" || href === "/admin" || href === "/employee" || href.startsWith("/employee/"))) {
      prefetchTarget(href);
    }
  }, { passive: true });

  document.addEventListener("touchstart", (e) => {
    if (!e || !e.target || typeof e.target.closest !== "function") return;
    const a = e.target.closest("a");
    if (!a) return;
    const href = a.getAttribute ? a.getAttribute("href") : null;
    if (href && (href === "/" || href === "/admin" || href === "/employee" || href.startsWith("/employee/"))) {
      prefetchTarget(href);
    }
  }, { passive: true });
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading" && typeof document.addEventListener === "function") {
    document.addEventListener("DOMContentLoaded", initFluidPageTransitions);
  } else {
    initFluidPageTransitions();
  }
}

// =============================================================================
// Modal Dialog Focus Management (a11y)
// On open: remember which element opened the dialog and move focus into it
// (first focusable inside the modal, else the dialog element itself — the
// modal-overlay divs carry tabindex="-1" for that fallback). On close: hand
// focus back to the opener. Templates call ndliModalOpened(modal) /
// ndliModalClosed(modal) from their existing open/close functions.
// Every DOM touch is individually guarded, so these helpers are safe no-ops in
// stripped-down DOM mocks and can never break a modal flow.
// =============================================================================
var ndliModalOpeners = (typeof WeakMap === "function") ? new WeakMap() : null;

function ndliModalFocusables(modal) {
  if (!modal || typeof modal.querySelectorAll !== "function") return [];
  const nodes = modal.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  );
  return Array.prototype.slice.call(nodes);
}

function ndliModalOpened(modal) {
  if (!modal) return;
  try {
    const opener = (typeof document !== "undefined" && document.activeElement) || null;
    if (ndliModalOpeners) ndliModalOpeners.set(modal, opener);
    const focusables = ndliModalFocusables(modal);
    const target = focusables.length > 0 ? focusables[0] : modal;
    if (target && typeof target.focus === "function") target.focus();
  } catch (err) {
    console.warn("[NDLI a11y] focus-on-open skipped:", err);
  }
}

function ndliModalClosed(modal) {
  if (!modal) return;
  try {
    const opener = ndliModalOpeners ? ndliModalOpeners.get(modal) : null;
    if (ndliModalOpeners) ndliModalOpeners.delete(modal);
    if (opener && opener.isConnected !== false && typeof opener.focus === "function") {
      opener.focus();
    }
  } catch (err) {
    console.warn("[NDLI a11y] focus-return skipped:", err);
  }
}

if (typeof window !== "undefined") {
  window.ndliModalOpened = ndliModalOpened;
  window.ndliModalClosed = ndliModalClosed;
}

