/**
 * shell.js — R19 sidebar/topbar shell wiring (sample-C structure).
 *
 * Purely additive, read-mostly UI behaviour for the restructured chrome:
 *   1. Topbar search — filters visible table rows in the active panel
 *      (admin) or drives the REAL Universal Club Search (employee portal).
 *   2. Sidebar count badges — mirror live KPI values that other scripts
 *      already load (no invented numbers; empty badges stay hidden).
 *   3. Date chip — real current month; zone chip mirrors the admin zone
 *      filter selection.
 *
 * No template script is modified; every hook degrades silently when the
 * element or the underlying function is absent.
 */
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ---------- 1. Topbar search ------------------------------------- */
  function wireSearch() {
    var input = $("#topbar-search");
    if (!input) return;
    var mode = input.getAttribute("data-shell-search") || "filter";
    var timer = null;

    function runFilter(q) {
      var panel = $(".tab-panel.active") || document;
      $all("tbody tr", panel).forEach(function (tr) {
        var hit = !q || (tr.textContent || "").toLowerCase().indexOf(q) !== -1;
        tr.style.display = hit ? "" : "none";
      });
    }

    function runUniversal(q) {
      var tabBtn = $('.tab-btn[data-target="tab-search"]');
      if (tabBtn && !tabBtn.classList.contains("active")) tabBtn.click();
      if (typeof window.performUniversalSearch === "function") {
        try { window.performUniversalSearch(q, q === ""); } catch (e) { console.error(e); }
      }
    }

    input.addEventListener("input", function () {
      var q = (input.value || "").trim().toLowerCase();
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        if (mode === "universal") runUniversal((input.value || "").trim());
        else runFilter(q);
      }, 220);
    });

    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { input.value = ""; input.dispatchEvent(new Event("input")); }
    });

    /* ⌘K / Ctrl-K focuses the search — matching the mockup's kbd hint. */
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        var el = $("#topbar-search");
        if (el) { e.preventDefault(); el.focus(); el.select(); }
      }
    });
  }

  /* ---------- 2. Sidebar count badges ------------------------------ */
  function wireCounts() {
    var map = [
      ["#side-count-renewals", "#kpi-renewals"],
      ["#side-count-escalations", "#kpi-admin-escalations"],
      ["#side-count-reminders", "#employee-reminders-modal-count"],
      ["#side-count-reminders", "#employee-reminders-count"]
    ];
    function sync() {
      map.forEach(function (pair) {
        var badge = $(pair[0]);
        if (!badge) return;
        var src = $(pair[1]);
        var txt = src ? (src.textContent || "").trim() : "";
        var num = txt.replace(/[^0-9]/g, "");
        if (num && num !== "0") {
          badge.textContent = num;
          badge.removeAttribute("data-empty");
        } else {
          badge.textContent = "";
          badge.setAttribute("data-empty", "1");
        }
      });
    }
    sync();
    setInterval(sync, 4000);
  }

  /* ---------- 3. Date + zone chips --------------------------------- */
  function wireChips() {
    var dateChip = $("[data-shell-date]");
    if (dateChip) {
      try {
        dateChip.textContent = new Date().toLocaleDateString("en-GB", { month: "short", year: "numeric" });
      } catch (e) { /* keep static fallback text */ }
    }
    var zoneChip = $("[data-shell-zone]");
    var zoneSel = $("#filter-zone");
    if (zoneChip && zoneSel) {
      var syncZone = function () {
        var opt = zoneSel.options[zoneSel.selectedIndex];
        zoneChip.textContent = (zoneSel.value === "ALL")
          ? "All Zones · 6"
          : ((opt ? opt.textContent : zoneSel.value) + " · 6");
      };
      syncZone();
      zoneSel.addEventListener("change", syncZone);
    }
  }

  /* ---------- 4. Mobile nav drawer (R51) ----------------------------
     The sidebar becomes an off-canvas drawer at <=980px (see the media block
     in style.css). This wires the topbar menu button: toggle, scrim click,
     Escape, and auto-close after picking a nav item. Degrades silently when
     the button/aside is absent. */
  function wireNavDrawer() {
    var toggle = $("#nav-toggle");
    var sidebar = $("#app-sidebar") || $(".app-sidebar");
    if (!toggle || !sidebar) return;
    var scrim = $("#nav-scrim") || $(".nav-scrim");

    function setOpen(open) {
      var shell = sidebar.closest ? sidebar.closest(".app-shell") : null;
      if (shell) shell.classList.toggle("nav-open", open);
      else sidebar.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (scrim) scrim.hidden = !open;
    }

    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    if (scrim) scrim.addEventListener("click", function () { setOpen(false); });
    document.addEventListener("keydown", function (e) {
      if ((e.key === "Escape" || e.keyCode === 27)) setOpen(false);
    });
    $all(".app-sidebar .tab-btn, .app-sidebar .side-link").forEach(function (el) {
      el.addEventListener("click", function () { setOpen(false); });
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 980) setOpen(false);
    });
  }

  function init() {
    wireSearch();
    wireCounts();
    wireChips();
    wireNavDrawer();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
