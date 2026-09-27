/* ==========================================================================
   NDLI CLUB MANAGEMENT — UI MOTION RUNTIME (Round 5, slice B)
   PLAN_UI_OVERHAUL.md §3 "motion vocabulary" · zero dependencies, vanilla JS
   Exposes window.UI = { enter, exit, swap, modal, toast, countUp, staggerIn,
                         rowsIn, progress, flashSuccess, shake, reduced }
   Everything is transform/opacity only and honours prefers-reduced-motion.
   ========================================================================== */
(function () {
  "use strict";

  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  function reduced() {
    return !!(mq && mq.matches);
  }

  function anim(el, frames, opts) {
    if (!el) return null;
    opts = opts || {};
    if (reduced() || typeof el.animate !== "function") {
      if (opts.done) opts.done();
      return null;
    }
    var a = el.animate(frames, {
      duration: opts.duration || 250,
      easing: opts.easing || "cubic-bezier(.22,1,.36,1)",
      fill: "both",
      delay: opts.delay || 0
    });
    if (opts.done) {
      a.onfinish = opts.done;
    }
    return a;
  }

  /* --- 1. View transitions ------------------------------------------------ */
  function enter(el, opts) {
    opts = opts || {};
    if (!el) return;
    el.classList.remove("ui-view-exit");
    void el.offsetWidth;
    el.classList.add("ui-view-enter");
    anim(el, [
      { opacity: 0, transform: "translateY(12px)" },
      { opacity: 1, transform: "translateY(0)" }
    ], { duration: opts.duration || 250, easing: "cubic-bezier(.22,1,.36,1)" });
    if (opts.stagger !== false) {
      staggerIn(el, true);
    }
  }

  function exit(el, done) {
    if (!el) { if (done) done(); return; }
    el.classList.remove("ui-view-enter");
    void el.offsetWidth;
    el.classList.add("ui-view-exit");
    anim(el, [
      { opacity: 1, transform: "translateY(0)" },
      { opacity: 0, transform: "translateY(-8px)" }
    ], {
      duration: 180,
      easing: "cubic-bezier(.65,0,.35,1)",
      done: function () {
        el.classList.remove("ui-view-exit");
        if (done) done();
      }
    });
  }

  /* Crossfade/swap two views without ever touching display (flash-guard safe:
     the caller keeps owning display + the auth-portal-unlocked class). */
  function swap(outEl, inEl, opts) {
    opts = opts || {};
    exit(outEl, function () {
      if (opts.hideOut !== false && outEl) outEl.style.visibility = "hidden";
      if (inEl) inEl.style.visibility = "";
      enter(inEl, opts);
    });
    if (inEl) inEl.style.visibility = "hidden";
  }

  /* --- 2. Staggered children (30ms apart, capped at 8) -------------------- */
  function staggerIn(container, instant) {
    if (!container) return;
    var targets = container.querySelectorAll(".ui-stagger");
    if (container.classList && container.classList.contains("ui-stagger")) {
      targets = [container];
    }
    Array.prototype.forEach.call(targets, function (t) {
      if (instant) {
        t.classList.add("ui-in");
        return;
      }
      requestAnimationFrame(function () {
        t.classList.add("ui-in");
      });
    });
  }

  /* --- 3. Table rows fade+slide (25ms stagger) ---------------------------- */
  function rowsIn(tbody) {
    if (!tbody) return;
    tbody.classList.remove("ui-rows-in");
    void tbody.offsetWidth;
    tbody.classList.add("ui-rows-in");
  }

  /* --- 4. Modal choreography ---------------------------------------------- */
  var modal = {
    open: function (backdropEl, panelEl) {
      if (!backdropEl) return;
      backdropEl.classList.remove("ui-closing");
      backdropEl.classList.add("ui-modal-backdrop");
      if (panelEl) {
        panelEl.classList.remove("ui-closing");
        panelEl.classList.add("ui-modal-panel");
      }
    },
    close: function (backdropEl, panelEl, done) {
      if (!backdropEl) { if (done) done(); return; }
      backdropEl.classList.add("ui-closing");
      if (panelEl) panelEl.classList.add("ui-closing");
      window.setTimeout(function () {
        backdropEl.classList.remove("ui-modal-backdrop", "ui-closing");
        if (panelEl) panelEl.classList.remove("ui-modal-panel", "ui-closing");
        if (done) done();
      }, reduced() ? 150 : 180);
    }
  };

  /* --- 5. Toasts ---------------------------------------------------------- */
  var region = null;
  function toastRegion() {
    if (!region) {
      region = document.createElement("div");
      region.className = "ui-toast-region";
      region.setAttribute("aria-live", "polite");
      document.body.appendChild(region);
    }
    return region;
  }

  function toast(message, opts) {
    opts = opts || {};
    var type = opts.type || "info";
    var dur = typeof opts.duration === "number" ? opts.duration : 4000;
    var el = document.createElement("div");
    el.className = "ui-toast ui-toast-" + type;

    var title = document.createElement("div");
    title.className = "ui-toast-title";
    title.textContent = opts.title || ({
      success: "Done",
      warning: "Attention",
      danger: "Something went wrong",
      info: "Notice"
    })[type];

    var body = document.createElement("div");
    body.className = "ui-toast-msg";
    body.textContent = String(message == null ? "" : message);

    var closeBtn = document.createElement("button");
    closeBtn.className = "ui-toast-close";
    closeBtn.setAttribute("aria-label", "Dismiss");
    closeBtn.innerHTML = "&times;";
    closeBtn.addEventListener("click", function () { dismiss(); });

    var timer = document.createElement("div");
    timer.className = "ui-toast-timer";
    timer.style.animationDuration = dur + "ms";

    el.appendChild(title);
    el.appendChild(body);
    el.appendChild(closeBtn);
    el.appendChild(timer);
    toastRegion().appendChild(el);

    var killTimer = null;
    function dismiss() {
      if (killTimer) window.clearTimeout(killTimer);
      el.classList.add("ui-toast-out");
      window.setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, reduced() ? 150 : 180);
    }
    if (dur > 0) killTimer = window.setTimeout(dismiss, dur);
    return { dismiss: dismiss, el: el };
  }

  /* --- 6. KPI count-up (300ms, ease-out) ---------------------------------- */
  function countUp(el, to, opts) {
    if (!el) return;
    opts = opts || {};
    var target = typeof to === "number" ? to : parseFloat(to);
    if (isNaN(target)) return;
    var dur = opts.duration || 300;
    if (reduced()) {
      el.textContent = format(target, opts);
      return;
    }
    var start = null;
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3); /* ease-out cubic */
      el.textContent = format(target * eased, opts);
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = format(target, opts);
    }
    requestAnimationFrame(step);
  }

  function format(v, opts) {
    opts = opts || {};
    var n = opts.decimals ? v.toFixed(opts.decimals) : Math.round(v).toString();
    if (opts.prefix) n = opts.prefix + n;
    if (opts.suffix) n = n + opts.suffix;
    return n;
  }

  /* --- 7. Success flash + error shake ------------------------------------- */
  function flashSuccess(el) {
    if (!el) return;
    el.classList.remove("ui-flash-success");
    void el.offsetWidth;
    el.classList.add("ui-flash-success");
    window.setTimeout(function () {
      el.classList.remove("ui-flash-success");
    }, 650);
  }

  function shake(el) {
    if (!el) return;
    el.classList.remove("ui-shake");
    void el.offsetWidth;
    el.classList.add("ui-shake");
    window.setTimeout(function () {
      el.classList.remove("ui-shake");
    }, 260);
  }

  /* --- 8. Slim top progress bar (wired to fetch + XHR) -------------------- */
  var progressEl = null;
  var progressCount = 0;

  function ensureProgress() {
    if (!progressEl) {
      progressEl = document.createElement("div");
      progressEl.className = "ui-progress";
      document.body.appendChild(progressEl);
    }
    return progressEl;
  }

  var progress = {
    start: function () {
      progressCount += 1;
      ensureProgress().classList.add("ui-active");
    },
    done: function () {
      progressCount = Math.max(0, progressCount - 1);
      if (progressCount === 0 && progressEl) {
        progressEl.classList.remove("ui-active");
      }
    }
  };

  function wrapFetch() {
    if (typeof window.fetch !== "function") return;
    var nativeFetch = window.fetch;
    window.fetch = function () {
      progress.start();
      var finish = function (v) { progress.done(); return v; };
      var fail = function (e) { progress.done(); throw e; };
      try {
        return nativeFetch.apply(this, arguments).then(finish, fail);
      } catch (e) {
        progress.done();
        throw e;
      }
    };
  }

  function wrapXhr() {
    if (typeof window.XMLHttpRequest !== "function") return;
    var proto = window.XMLHttpRequest.prototype;
    var open = proto.open;
    var send = proto.send;
    proto.open = function () {
      this.__uiTracked = true;
      return open.apply(this, arguments);
    };
    proto.send = function () {
      if (this.__uiTracked) {
        progress.start();
        var done = false;
        var finish = function () {
          if (done) return;
          done = true;
          progress.done();
        };
        this.addEventListener("loadend", finish);
      }
      return send.apply(this, arguments);
    };
  }

  /* --- 8b. Automatic modal choreography ------------------------------------
     Any element whose id/class looks like a modal/overlay and becomes visible
     gets the backdrop + panel animation. No template surgery required. */
  function isVisible(el) {
    if (!el || !window.getComputedStyle) return false;
    var cs = window.getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden";
  }

  function watchModals() {
    if (typeof window.MutationObserver !== "function") return;
    var obs = new window.MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var el = m.target;
        if (!el || !el.getAttribute) return;
        var id = el.id || "";
        var cls = (typeof el.className === "string" ? el.className : "") || "";
        if (!/modal|overlay|lock-screen/i.test(id + " " + cls)) return;
        var visible = isVisible(el);
        if (visible && !el.__uiModalShown) {
          el.__uiModalShown = true;
          var panel = el.querySelector(".modal-content, .modal-box, .modal-card, .modal-dialog");
          modal.open(el, panel || el.firstElementChild);
        } else if (!visible && el.__uiModalShown) {
          el.__uiModalShown = false;
          el.classList.remove("ui-modal-backdrop", "ui-modal-panel", "ui-closing");
        }
      });
    });
    obs.observe(document.documentElement, {
      attributes: true,
      subtree: true,
      attributeFilter: ["style", "class"]
    });
  }

  /* --- 9. alert() routing: non-critical -> toast, critical stays native ---- */
  var CRITICAL = /(error|fail(ed|ure)?|denied|invalid|unable|cannot|unable to|exception|expired|wrong|incorrect|not allowed|forbidden|unauthori[sz]ed)/i;

  function routeAlerts() {
    var nativeAlert = window.alert ? window.alert.bind(window) : null;
    if (!nativeAlert) return;
    window.alert = function (msg) {
      var text = String(msg == null ? "" : msg);
      if (CRITICAL.test(text)) {
        nativeAlert(text);           /* critical errors keep the blocking dialog */
      } else {
        toast(text, { type: "info", title: "Notice", duration: 5000 });
      }
    };
    window.alert.native = nativeAlert;
  }

  /* --- 10b. Auto behaviours: KPI count-up, row stagger, error shake -------- */

  /* Numbers rendered by the app count up whenever their text value changes. */
  var NUMBER_SEL = ".stat-value, .stat-number, .kpi-value, .metric-value, [data-countup]," +
                   "#quota-clubs-count, #quota-support-count," +
                   "#attn-total-count, #attn-expiring-count, #attn-overdue-count";

  function parseNum(s) {
    var t = String(s || "").replace(/[,\s]/g, "");
    return /^-?\d+(\.\d+)?$/.test(t) ? parseFloat(t) : null;
  }

  function watchNumbers() {
    if (typeof window.MutationObserver !== "function") return;
    var obs = new window.MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var el = m.target;
        while (el && el.nodeType !== 1) el = el.parentNode;
        if (!el) return;
        var host = el.closest ? el.closest(NUMBER_SEL) : null;
        if (!host) return;
        var next = parseNum(host.textContent);
        if (next === null) return;
        var prev = host.__uiNum;
        host.__uiNum = next;
        if (prev === undefined || prev === next) return;
        countUp(host, next, { duration: 300 });
      });
    });
    obs.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true
    });
    /* seed initial values so the first real change animates */
    Array.prototype.forEach.call(document.querySelectorAll(NUMBER_SEL), function (el) {
      var n = parseNum(el.textContent);
      if (n !== null) el.__uiNum = n;
    });
  }

  /* Table rows fade + slide whenever a tbody receives new rows (25ms stagger). */
  function watchRows() {
    if (typeof window.MutationObserver !== "function") return;
    var queued = [];
    var scheduled = false;
    var obs = new window.MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var t = m.target;
        if (t && t.nodeType === 1 && String(t.tagName).toUpperCase() === "TBODY") {
          if (queued.indexOf(t) === -1) queued.push(t);
        }
      });
      if (!scheduled) {
        scheduled = true;
        requestAnimationFrame(function () {
          scheduled = false;
          queued.forEach(function (tb) {
            rowsIn(tb);
          });
          queued = [];
        });
      }
    });
    obs.observe(document.body, { subtree: true, childList: true });
  }

  /* Form-level error shake: when an alert box fills with an error, shake its form. */
  function watchAlerts() {
    if (typeof window.MutationObserver !== "function") return;
    var obs = new window.MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var el = m.target;
        while (el && el.nodeType !== 1) el = el.parentNode;
        if (!el || !el.id || !/-alert$/.test(el.id)) return;
        if (!String(el.textContent || "").trim()) return;
        var form = el.querySelector("form") ||
                   (el.closest ? el.closest("form") : null) ||
                   (el.parentNode ? el.parentNode.querySelector("form") : null);
        shake(form || el);
      });
    });
    obs.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributeFilter: ["style", "class"]
    });
  }

  /* --- 11. Auto-init ------------------------------------------------------ */
  function autoInit() {
    /* count-up elements: <span data-countup="42"></span> */
    Array.prototype.forEach.call(document.querySelectorAll("[data-countup]"), function (el) {
      var to = parseFloat(el.getAttribute("data-countup"));
      if (!isNaN(to)) {
        countUp(el, to, {
          decimals: parseInt(el.getAttribute("data-countup-decimals") || "0", 10),
          prefix: el.getAttribute("data-countup-prefix") || "",
          suffix: el.getAttribute("data-countup-suffix") || ""
        });
      }
    });
    staggerIn(document, false);
  }

  wrapFetch();
  wrapXhr();
  routeAlerts();
  watchModals();
  watchNumbers();
  watchRows();
  watchAlerts();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoInit);
  } else {
    autoInit();
  }

  window.UI = {
    enter: enter,
    exit: exit,
    swap: swap,
    modal: modal,
    toast: toast,
    countUp: countUp,
    staggerIn: staggerIn,
    rowsIn: rowsIn,
    progress: progress,
    flashSuccess: flashSuccess,
    shake: shake,
    reduced: reduced
  };
})();
