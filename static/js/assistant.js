/* ==========================================================================
   NDLI CLUB MANAGEMENT — AI ASSISTANT WIDGET (Round 6 · Slices A+B)
   PLAN_AI_ASSISTANT.md §5 UX + §7 hard constraints · vanilla JS, no build step

   Structure of this file
     1. AssistantAPI  — the transport. Slice B: LIVE fetch() against
                        /api/assistant/ask with the portal session token, with
                        a graceful FALLBACK to the Slice A mock backend
                        (canned answers) when the server is unreachable; the
                        UI only consumes the contract:
                          ask(question: string) ->
                            Promise<{answer: string,
                                     sources: Array<{title, detail}>,
                                     suggestions: Array<{title, detail, href, label}>}>
     2. Widget UI     — FAB + popup wiring, rendering, focus trap, ARIA live
                        region, Esc-to-close, 👍/👎 feedback, quick chips.
     3. Public handle — window.NDLIAssistant = { open, close, toggle, ask,
                        showBadge, hideBadge, version } (test + Slice E seam).

   Safety notes (plan §7.6 — prompt-injection hygiene):
     - all payload strings are rendered with textContent / createElement, NEVER
       innerHTML, so retrieved data can never become markup or script.
     - suggestion deep links are placeholder hrefs; navigation is intercepted
       and re-emitted as a `ndli:assistant-deep-link` CustomEvent so Slice B/E
       can route them server-side aware instead of the widget guessing.
   ========================================================================== */
(function () {
  "use strict";

  /* ========================================================================
     1. AssistantAPI — transport seam (Slice A: mock only)
     ==================================================================== */
  var MOCK_LATENCY_MS = 650;

  var MOCK = {
    "my week": {
      answer:
        "Here's your week at a glance (sample data — live numbers arrive with the real assistant API):\n" +
        "• 4 club activities logged, 2 of them student-led\n" +
        "• 2 renewals entering the 30-day window\n" +
        "• 1 open issue awaiting your review\n" +
        "• Approval turnaround: 2.3 days on average (down 18%)\n" +
        "You're on track overall — the two upcoming renewals are the only items that need a decision this week.",
      sources: [
        { title: "Your activity log", detail: "rolling 7 days · sample" },
        { title: "Renewal tracker", detail: "30-day look-ahead · sample" }
      ],
      suggestions: [
        {
          title: "Open my dashboard",
          detail: "Full week breakdown with charts",
          href: "/portal#dashboard",
          label: "Open"
        },
        {
          title: "Log a new activity",
          detail: "Record a club event in under a minute",
          href: "/portal#activities",
          label: "Start"
        }
      ]
    },
    "renewals due": {
      answer:
        "3 clubs need renewal attention in the next 14 days (sample data):\n" +
        "• NDLI-EMP01-002 · Delhi Advanced Technical Institute — due in 6 days\n" +
        "• NDLI-EMP04-001 · Kolkata Engineering & Research Institute — due in 11 days\n" +
        "• NDLI-EMP02-003 · Pune Community College — due in 14 days\n" +
        "Tip: renewals filed before the due date keep the club's active streak unbroken; overdue ones start an escalation clock.",
      sources: [
        { title: "Renewal tracker", detail: "renewals.due ≤ 14 days · sample" },
        { title: "Escalation rules", detail: "docs · 30-day reminder ladder" }
      ],
      suggestions: [
        {
          title: "Renewal attention screen",
          detail: "Open the due & overdue renewal queue",
          href: "/portal#renewal-attention",
          label: "Open"
        },
        {
          title: "How renewals work",
          detail: "Step-by-step approval journey (4 steps)",
          href: "/help#renewals",
          label: "Guide"
        }
      ]
    },
    "how do i…?": {
      answer:
        "Pick a journey and I'll walk you through it (sample steps):\n" +
        "• Approve a renewal — 4 steps, about 2 minutes\n" +
        "• Raise & track an issue — 3 steps\n" +
        "• Download the master CSV — 1 step\n" +
        "• Read the strategic report — 3 steps\n" +
        "You can also just ask, e.g. “How do I approve a renewal?” for the full walkthrough with the right screen linked.",
      sources: [
        { title: "User manual", detail: "docs/user_manual.html · journey index" }
      ],
      suggestions: [
        {
          title: "Approve a renewal",
          detail: "Walkthrough with the approval screen linked",
          href: "/help#approve-renewal",
          label: "Steps"
        },
        {
          title: "Raise & track an issue",
          detail: "From report to resolution in 3 steps",
          href: "/help#issues",
          label: "Steps"
        },
        {
          title: "Download the master CSV",
          detail: "One click on the admin dashboard",
          href: "/help#master-csv",
          label: "Steps"
        }
      ]
    },
    "strategy summary": {
      answer:
        "Strategic snapshot (sample output modelled on AIDecisionEngine.generate_strategic_report()):\n" +
        "• Penetration index: 68 / 100 — steady, +4 points vs last month\n" +
        "• Activity velocity: 12.4 activities/week across 31 clubs\n" +
        "• Renewal vulnerability: 3 clubs in the amber band (due ≤ 14 days)\n" +
        "• Roadmap nudge: Zone East support-load is 2× the average — a zone clinic there would lift activity velocity fastest.",
      sources: [
        { title: "ai/decision_module.py", detail: "generate_strategic_report() · sample" }
      ],
      suggestions: [
        {
          title: "Full strategic report",
          detail: "Penetration, velocity & vulnerability detail",
          href: "/admin#ai-insights",
          label: "Open"
        },
        {
          title: "Zone performance",
          detail: "Compare support-load across zones",
          href: "/admin#zones",
          label: "Open"
        }
      ]
    }
  };

  var FALLBACK = {
    answer:
      "I'm running on canned demo answers in Slice A, so I can't see live data yet — that lands with the assistant API in Slice B.\n" +
      "Meanwhile I can demo: “My week”, “Renewals due”, “How do I…?” and “Strategy summary” (try the chips above), and I understand a few topics already: renewals, quotas, issues, clubs and strategy.",
    sources: [
      { title: "Assistant demo knowledge base", detail: "Slice A mock · no live data" }
    ],
    suggestions: [
      {
        title: "See the quick actions",
        detail: "Tap a chip above for the canned demo answers",
        href: "#quick-actions",
        label: "Show"
      }
    ]
  };

  var TOPIC_ANSWERS = [
    {
      match: /(renew|re-?new)/i,
      reply: {
        answer:
          "On renewals (sample data): each club's renewal date comes from its approval date + 1 year, and the renewal attention queue lists anything due within 30 days or already overdue.\n" +
          "• Due ≤ 14 days → amber band, worth filing now\n" +
          "• Overdue → escalation clock starts, with reminders at 30 days\n" +
          "Want the queue? The “Renewals due” chip above shows the demo version.",
        sources: [
          { title: "Renewal tracker", detail: "renewal lifecycle docs · sample" }
        ],
        suggestions: [
          {
            title: "Renewal attention screen",
            detail: "Due & overdue renewal queue",
            href: "/portal#renewal-attention",
            label: "Open"
          }
        ]
      }
    },
    {
      match: /(quota|target)/i,
      reply: {
        answer:
          "On quotas (sample data): every employee node tracks approved clubs vs target and activities vs target, and the KPI stack turns both into a health band.\n" +
          "• Your sample quota: 8 approved clubs of a 10 target (80%)\n" +
          "• Activities: 21 of 25 this quarter (84%)\n" +
          "Anything below 60% of target flags as at-risk on the dashboard.",
        sources: [
          { title: "Quota engine", detail: "quota.get · sample" }
        ],
        suggestions: [
          {
            title: "KPI & quota dashboard",
            detail: "Targets, bands and trends",
            href: "/portal#kpi",
            label: "Open"
          }
        ]
      }
    },
    {
      match: /(issue|escalat|problem|complaint)/i,
      reply: {
        answer:
          "On issues (sample data): you report an issue from the employee portal, it lands in the shared issue queue with a priority, and admins resolve or escalate it.\n" +
          "• Open now: 1 (medium priority, 2 days old)\n" +
          "• Escalation triggers at 30 days unresolved → automatic reminder ladder\n" +
          "Every state change is logged in the clubs/activities logs for audit.",
        sources: [
          { title: "Issue queue", detail: "issues.list · sample" },
          { title: "Escalation rules", detail: "30-day ladder · docs" }
        ],
        suggestions: [
          {
            title: "Report an issue",
            detail: "Opens the issue form in the employee portal",
            href: "/portal#issues",
            label: "Open"
          }
        ]
      }
    },
    {
      match: /(club|activit)/i,
      reply: {
        answer:
          "On clubs & activities (sample data): the master DB currently tracks 31 clubs and 271 activities across 7 employee nodes.\n" +
          "• Each club stores its zone/state, patron & officer contacts and renewal dates\n" +
          "• Activities roll up per club into the activity velocity metric\n" +
          "All figures here are illustrative — Slice B answers from the live CSV engine, with the source cited on every number.",
        sources: [
          { title: "Master DB", detail: "clubs.list · activities.summary · sample" }
        ],
        suggestions: [
          {
            title: "Clubs directory",
            detail: "Search and inspect any club",
            href: "/portal#clubs",
            label: "Open"
          }
        ]
      }
    },
    {
      match: /(strateg|insight|analytic|report|roadmap)/i,
      reply: {
        answer:
          "On strategy (sample data): the analytics brain behind the assistant is ai/decision_module.py — penetration index, activity velocity, renewal vulnerability and roadmap recommendations.\n" +
          "The “Strategy summary” chip above shows the demo snapshot; in later slices I'll explain any figure in the report and suggest what to focus on this week.",
        sources: [
          { title: "ai/decision_module.py", detail: "AIDecisionEngine · sample" }
        ],
        suggestions: [
          {
            title: "Strategic report",
            detail: "The full generated report",
            href: "/admin#ai-insights",
            label: "Open"
          }
        ]
      }
    },
    {
      match: /^(hi|hey|hello|namaste|good (morning|afternoon|evening))\b/i,
      reply: {
        answer:
          "Hello! I'm Robu, the NDLI Club assistant (demo mode — canned answers for now). Try a quick action above, or ask me about renewals, quotas, issues or strategy.",
        sources: [
          { title: "Assistant demo knowledge base", detail: "Slice A mock · no live data" }
        ],
        suggestions: []
      }
    },
    {
      match: /(thank|thanks|dhanyavaad)/i,
      reply: {
        answer: "You're welcome! Anything else you'd like to look at — renewals, quotas or the strategy snapshot?",
        sources: [
          { title: "Assistant demo knowledge base", detail: "Slice A mock · no live data" }
        ],
        suggestions: []
      }
    }
  ];

  function pickMockAnswer(question) {
    var key = String(question || "").trim().toLowerCase();
    if (Object.prototype.hasOwnProperty.call(MOCK, key)) {
      return MOCK[key];
    }
    if (/(how do i|how to|how can i)/i.test(question)) {
      return MOCK["how do i…?"];
    }
    for (var i = 0; i < TOPIC_ANSWERS.length; i++) {
      if (TOPIC_ANSWERS[i].match.test(question)) {
        return TOPIC_ANSWERS[i].reply;
      }
    }
    return FALLBACK;
  }

  function askMock(question) {
    return new Promise(function (resolve) {
      window.setTimeout(function () {
        // Deep-copy so the UI can safely mutate (e.g. render order) the payload.
        var picked = pickMockAnswer(question);
        resolve({
          answer: picked.answer,
          sources: (picked.sources || []).map(function (s) {
            return { title: s.title, detail: s.detail };
          }),
          suggestions: (picked.suggestions || []).map(function (s) {
            return { title: s.title, detail: s.detail, href: s.href, label: s.label };
          })
        });
      }, MOCK_LATENCY_MS);
    });
  }

  /*
   * ---- SLICE B TRANSPORT -------------------------------------------------
   * AssistantAPI.ask() calls POST /api/assistant/ask with the verified portal
   * session token (same sessionStorage keys the portal itself uses). On ANY
   * failure -- network error, non-2xx, or a 200 with a malformed payload
   * (never-trust-200) -- it logs a console warning and FALLS BACK to the mock
   * answers below, so the widget never goes silent.
   * -----------------------------------------------------------------------
   */
  function authToken() {
    try {
      return sessionStorage.getItem("ndli_employee_token")
          || sessionStorage.getItem("ndli_admin_token")
          || sessionStorage.getItem("ndli_token")
          || "";
    } catch (e) {
      return "";
    }
  }

  function normalizePayload(data) {
    if (!data || typeof data.answer !== "string" || !data.answer.trim()) {
      return null; /* never trust a 200: empty/absent answer => caller falls back */
    }
    return {
      answer: data.answer,
      sources: (Array.isArray(data.sources) ? data.sources : []).map(function (s) {
        return { title: s && s.title, detail: s && s.detail };
      }),
      suggestions: (Array.isArray(data.suggestions) ? data.suggestions : []).map(function (s) {
        return { title: s && s.title, detail: s && s.detail, href: s && s.href, label: s && s.label };
      })
    };
  }

  function askLive(question) {
    return fetch("/api/assistant/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + authToken()
      },
      body: JSON.stringify({ question: question })
    }).then(function (r) {
      if (!r.ok) {
        throw new Error("assistant ask HTTP " + r.status);
      }
      return r.json();
    }).then(function (data) {
      var normalized = normalizePayload(data);
      if (!normalized) {
        throw new Error("assistant ask returned a malformed payload");
      }
      return normalized;
    });
  }

  function nudgesLive() {
    return fetch("/api/assistant/nudges", {
      headers: { "Authorization": "Bearer " + authToken() }
    }).then(function (r) {
      if (!r.ok) {
        throw new Error("assistant nudges HTTP " + r.status);
      }
      return r.json();
    });
  }

  var AssistantAPI = {
    version: "slice-b-live",
    ask: function (question) {
      var text = String(question == null ? "" : question);
      return askLive(text).catch(function (err) {
        if (window.console && console.warn) {
          console.warn("[NDLI Assistant] live /api/assistant/ask failed — using offline demo answers:", err);
        }
        return askMock(text);
      });
    },
    nudges: function () {
      // Best-effort: a failed nudge check just means no badge this load.
      return nudgesLive().catch(function (err) {
        if (window.console && console.warn) {
          console.warn("[NDLI Assistant] nudge check failed (badge stays hidden):", err);
        }
        return { nudge: null };
      });
    }
  };
  window.AssistantAPI = AssistantAPI;

  /* Feedback: the 👍/👎 buttons dispatch `ndli:assistant-feedback`; we relay
     it to POST /api/assistant/feedback (append-only log). Best-effort: a
     failed send is logged loudly but never breaks the chat UI. */
  var lastAskedQuestion = "";
  document.addEventListener("ndli:assistant-feedback", function (event) {
    var verdict = event && event.detail && event.detail.verdict;
    var payload = {
      question: lastAskedQuestion.slice(0, 1000),
      verdict: verdict === "down" ? "down" : "up",
      comment: ""
    };
    fetch("/api/assistant/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + authToken()
      },
      body: JSON.stringify(payload)
    }).then(function (r) {
      if (!r.ok) {
        throw new Error("assistant feedback HTTP " + r.status);
      }
    }).catch(function (err) {
      if (window.console && console.warn) {
        console.warn("[NDLI Assistant] feedback POST failed:", err);
      }
    });
  });

  /* ========================================================================
     2. Widget UI
     ==================================================================== */
  var root = null;
  var fab = null;
  var panel = null;
  var logEl = null;
  var typingEl = null;
  var form = null;
  var input = null;
  var closeBtn = null;
  var chipsEl = null;
  var liveRegion = null;
  var isOpen = false;
  var greeted = false;
  var pending = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function announce(text) {
    if (!liveRegion) return;
    // Clear-then-set so screen readers re-announce identical strings.
    liveRegion.textContent = "";
    window.setTimeout(function () {
      liveRegion.textContent = text;
    }, 60);
  }

  /* ---- open / close ----------------------------------------------------- */
  function open() {
    if (isOpen || !panel) return;
    isOpen = true;
    panel.hidden = false;
    panel.classList.remove("ndli-asst-closing");
    fab.setAttribute("aria-expanded", "true");
    root.setAttribute("data-asst-state", "open");
    if (!greeted) {
      greeted = true;
      appendAssistant({
        answer:
          "Hi! I'm Robu, the NDLI Club assistant — I answer from live portal data (and fall back " +
          "to demo answers if the server is unreachable). Try a quick action below, or ask " +
          "about renewals, quotas, issues or strategy.",
        sources: [{ title: "Robu · NDLI Club assistant", detail: "Slice B · live data with offline fallback" }],
        suggestions: []
      });
    }
    flushPendingNudge();
    window.setTimeout(function () {
      if (input) input.focus();
    }, 40);
  }

  function close() {
    if (!isOpen || !panel) return;
    isOpen = false;
    panel.classList.add("ndli-asst-closing");
    window.setTimeout(function () {
      panel.classList.remove("ndli-asst-closing");
      panel.hidden = true;
    }, 180);
    fab.setAttribute("aria-expanded", "false");
    root.setAttribute("data-asst-state", "closed");
    fab.focus();
    announce("Assistant closed.");
  }

  function toggle() {
    if (isOpen) close();
    else open();
  }

  /* ---- focus trap (plan §5 accessibility) ------------------------------- */
  var FOCUSABLE =
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), ' +
    'select:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function trapTab(event) {
    if (!isOpen || event.key !== "Tab") return;
    var items = Array.prototype.filter.call(
      panel.querySelectorAll(FOCUSABLE),
      function (node) {
        return node.offsetWidth > 0 || node.offsetHeight > 0 || node === document.activeElement;
      }
    );
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    } else if (!panel.contains(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  }

  /* ---- rendering (textContent only — never innerHTML) ------------------- */
  function appendUser(text) {
    var msg = el("div", "ndli-asst-msg ndli-asst-msg-user");
    msg.appendChild(el("p", null, text));
    logEl.appendChild(msg);
    scrollLog();
  }

  function buildSources(sources) {
    var wrap = el("div", "ndli-asst-sources");
    wrap.appendChild(el("span", "ndli-asst-sources-title", "Sources"));
    var ul = el("ul");
    sources.forEach(function (s) {
      var li = el("li");
      li.appendChild(document.createTextNode(s.title || "Source"));
      if (s.detail) li.appendChild(el("em", null, " — " + s.detail));
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    return wrap;
  }

  function buildFeedback() {
    var row = el("div", "ndli-asst-feedback");
    var up = el("button", "ndli-asst-fb-btn");
    up.type = "button";
    up.textContent = "👍";
    up.setAttribute("aria-label", "Helpful answer");
    up.setAttribute("aria-pressed", "false");
    up.setAttribute("data-asst-fb", "up");

    var down = el("button", "ndli-asst-fb-btn");
    down.type = "button";
    down.textContent = "👎";
    down.setAttribute("aria-label", "Not helpful");
    down.setAttribute("aria-pressed", "false");
    down.setAttribute("data-asst-fb", "down");

    var note = el("span", "ndli-asst-fb-note");
    note.hidden = true;

    [up, down].forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (up.disabled) return;
        up.disabled = true;
        down.disabled = true;
        btn.setAttribute("aria-pressed", "true");
        note.hidden = false;
        note.textContent = "Thanks — feedback recorded (demo).";
        announce("Thanks — feedback recorded.");
        // Slice F seam: learning loop listens for this event.
        document.dispatchEvent(
          new CustomEvent("ndli:assistant-feedback", {
            detail: { verdict: btn.getAttribute("data-asst-fb") }
          })
        );
      });
    });

    row.appendChild(up);
    row.appendChild(down);
    row.appendChild(note);
    return row;
  }

  function buildSuggestionCard(s) {
    var card = el("div", "ndli-asst-card");
    var text = el("div", "ndli-asst-card-text");
    text.appendChild(el("span", "ndli-asst-card-title", s.title || "Suggestion"));
    if (s.detail) text.appendChild(el("span", "ndli-asst-card-detail", s.detail));
    card.appendChild(text);

    var link = el("a", "ndli-asst-card-link", s.label || "Open");
    link.href = s.href || "#"; // real target; navigation is routed below
    link.setAttribute("data-deep-link", s.href || "#");
    link.setAttribute("aria-label", (s.label || "Open") + ": " + (s.title || "suggestion"));
    link.addEventListener("click", function (event) {
      event.preventDefault();
      var target = link.getAttribute("data-deep-link") || "#";
      // Slice B/E seam: still emitted for listeners, but the router below
      // performs the actual navigation now (Slice E: real deep links).
      document.dispatchEvent(
        new CustomEvent("ndli:assistant-deep-link", { detail: { href: target } })
      );
      executeDeepLink(target);
    });
    card.appendChild(link);
    return card;
  }

  function appendAssistant(payload) {
    var msg = el("div", "ndli-asst-msg ndli-asst-msg-bot");
    msg.appendChild(el("p", null, payload.answer || ""));
    if (payload.sources && payload.sources.length) {
      msg.appendChild(buildSources(payload.sources));
    }
    msg.appendChild(buildFeedback());
    if (payload.suggestions && payload.suggestions.length) {
      var cards = el("div", "ndli-asst-suggestions");
      payload.suggestions.forEach(function (s) {
        cards.appendChild(buildSuggestionCard(s));
      });
      msg.appendChild(cards);
    }
    logEl.appendChild(msg);
    scrollLog();
    announce("Assistant replied: " + (payload.answer || ""));
  }

  function scrollLog() {
    logEl.scrollTop = logEl.scrollHeight;
  }

  function showTyping() {
    pending += 1;
    typingEl.hidden = false; /* role="status" announces “Assistant is typing…” */
    scrollLog();
  }

  function hideTyping() {
    pending = Math.max(0, pending - 1);
    if (pending === 0) typingEl.hidden = true;
  }

  /* ---- send flow -------------------------------------------------------- */
  function send(question) {
    var text = String(question == null ? "" : question).trim();
    if (!text) return;
    lastAskedQuestion = text;
    appendUser(text);
    if (input) {
      input.value = "";
      autosize();
    }
    showTyping();
    AssistantAPI.ask(text).then(
      function (res) {
        hideTyping();
        appendAssistant(res || { answer: "", sources: [], suggestions: [] });
      },
      function () {
        hideTyping();
        appendAssistant({
          answer: "Sorry — I hit a snag answering that. Please try again.",
          sources: [],
          suggestions: []
        });
      }
    );
  }

  function autosize() {
    if (!input) return;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 96) + "px";
  }

  /* ---- wiring ----------------------------------------------------------- */
  /* ---- Slice E: proactive nudge badge ----------------------------------
     At most one nudge (the server picks by priority). Dismissible: opening
     the chat records the nudge's id in localStorage, and because the id is a
     signature of the flagged set, the badge only comes back when that set
     changes. Silent during quiet hours (21:00-08:00 local). */
  var pendingNudge = null;

  function nudgeDismissed(id) {
    try {
      return !!window.localStorage && localStorage.getItem("ndli-asst-nudge-dismissed") === id;
    } catch (e) {
      return false;
    }
  }

  function nudgeDismiss(id) {
    try {
      if (window.localStorage) localStorage.setItem("ndli-asst-nudge-dismissed", id);
    } catch (e) { /* storage unavailable: the badge simply reappears next load */ }
    pendingNudge = null;
    window.NDLIAssistant.hideBadge();
  }

  function nudgeQuietHours() {
    var h = new Date().getHours();
    return h >= 21 || h < 8;
  }

  function loadNudge() {
    AssistantAPI.nudges().then(function (data) {
      var n = data && data.nudge;
      if (!n || !n.id) return;
      if (nudgeDismissed(n.id) || nudgeQuietHours()) return;
      pendingNudge = n;
      window.NDLIAssistant.showBadge(1);
    });
  }

  function flushPendingNudge() {
    if (!pendingNudge || !logEl) return;
    var n = pendingNudge;
    appendAssistant({
      answer: "Heads up — " + n.title + ": " + n.detail +
        (n.suggested_question ? " Ask me: \u201c" + n.suggested_question + "\u201d" : ""),
      sources: [{ title: "Proactive check", detail: "role-scoped live signals" }],
      suggestions: [{
        title: n.title,
        detail: "Open the list this points to",
        href: n.href,
        label: "Open"
      }]
    });
    nudgeDismiss(n.id);
  }

  function init() {
    root = $("ndli-asst-root");
    if (!root) return; // widget markup not present on this page — nothing to do
    fab = $("ndli-asst-fab");
    panel = $("ndli-asst-panel");
    logEl = $("ndli-asst-log");
    typingEl = $("ndli-asst-typing");
    form = $("ndli-asst-form");
    input = $("ndli-asst-input");
    closeBtn = $("ndli-asst-close");
    chipsEl = $("ndli-asst-chips");
    liveRegion = $("ndli-asst-live");

    fab.addEventListener("click", toggle);
    closeBtn.addEventListener("click", close);

    document.addEventListener("keydown", function (event) {
      if (!isOpen) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      trapTab(event);
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      send(input.value);
    });

    input.addEventListener("input", autosize);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        send(input.value);
      }
    });

    chipsEl.addEventListener("click", function (event) {
      var chip = event.target && event.target.closest ? event.target.closest(".ndli-asst-chip") : null;
      if (!chip || !chipsEl.contains(chip)) return;
      send(chip.getAttribute("data-asst-chip") || chip.textContent);
    });

    autosize();

    // Slice E: run any deep link that arrived via the URL hash
    // (cross-portal links and login-gate passes land here).
    processDeepLinkHash();
    // Slice E: check for one high-value nudge (badge only; quiet hours +
    // localStorage dismissal apply).
    loadNudge();
  }

  /* ========================================================================
     2c. Deep-link router (Slice E) — suggestion cards navigate for real.

     Card hrefs look like /portal#renewal-attention, /admin#dashboard or
     /manual. The router maps each key to the right SPA tab + scroll/modal
     action on the page it belongs to, and navigates across portals (and
     through the login gate) via the URL hash, which is re-processed on load.
     ==================================================================== */
  function toastNote(message) {
    if (window.UI && typeof window.UI.toast === "function") {
      window.UI.toast(message, { type: "info", title: "Assistant", dur: 3200 });
    }
  }

  function currentPortal() {
    var p = window.location.pathname || "";
    if (p.indexOf("/employee") === 0) return "employee";
    if (p.indexOf("/admin") === 0) return "admin";
    return "landing";
  }

  function activateTab(target) {
    if (!target) return;
    var btn = document.querySelector('.tab-btn[data-target="' + target + '"]');
    if (btn && !btn.classList.contains("active")) btn.click();
  }

  function scrollToEl(elx) {
    if (elx && elx.scrollIntoView) elx.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function nearestCard(elx) {
    return elx && elx.closest ? (elx.closest(".card") || elx) : elx;
  }

  function focusEl(elx) {
    if (!elx) return;
    setTimeout(function () {
      try { elx.focus({ preventScroll: true }); } catch (e) { try { elx.focus(); } catch (e2) {} }
    }, 350);
  }

  // Slice E fix (2026-10-03): these two keys used to share one handler, so the
  // renewal card opened the employee issue-reminders queue ("Due Unresolved
  // Issue Reminders Queue"). Each key now opens the list it actually names.
  function openRenewalAttention(portal) {
    if (portal === "admin") {
      if (typeof window.openRenewalAttentionModal === "function") {
        window.openRenewalAttentionModal("ALL");
      } else {
        scrollToEl(document.getElementById("card-renewal-attention"));
      }
      return;
    }
    // Employee renewal work happens in the clubs table (Last / Upcoming Renewal
    // Date columns; clicking a row opens the Edit & Renewal panel).
    var table = document.querySelector("#tab-search .table-scroll-container")
      || document.getElementById("search-results-tbody")
      || document.getElementById("search-input");
    scrollToEl(table);
    toastNote("Renewal dates for your clubs are in this table (Last / Upcoming Renewal Date). Click a row to open its renewal panel.");
  }

  function openIssuesList(portal) {
    if (portal === "admin") {
      if (typeof window.openAdminEscalationsListModal === "function") {
        window.openAdminEscalationsListModal();
      } else {
        scrollToEl(document.getElementById("card-admin-escalations"));
      }
      return;
    }
    if (typeof window.openEmployeeRemindersListModal === "function") {
      window.openEmployeeRemindersListModal();
    } else {
      scrollToEl(document.getElementById("employee-reminders-kpi-card"));
    }
  }

  var DEEP_LINK_ACTIONS = {
    "renewal-attention": {
      portals: ["employee", "admin"],
      tab: { employee: "tab-search", admin: "tab-dashboard" },
      run: openRenewalAttention
    },
    "issues": {
      portals: ["employee", "admin"],
      tab: { employee: "tab-activity", admin: "tab-dashboard" },
      run: openIssuesList
    },
    "help-renewal": {
      portals: ["employee", "admin", "landing"],
      open: "/manual"
    },
    "my-quota": {
      portals: ["employee"],
      tab: { employee: "tab-activity" },
      run: function () { scrollToEl(nearestCard(document.getElementById("quota-clubs-count"))); }
    },
    "log-activity": {
      portals: ["employee"],
      tab: { employee: "tab-activity" },
      run: function () {
        var form = document.getElementById("sec-a-form");
        scrollToEl(nearestCard(form));
        focusEl(form && form.querySelector("input, select, textarea"));
      }
    },
    "activities": {
      portals: ["employee"],
      tab: { employee: "tab-history" },
      run: function () {
        scrollToEl(nearestCard(document.getElementById("activities-tbody")));
      }
    },
    "clubs": {
      portals: ["employee"],
      tab: { employee: "tab-search" },
      run: function () {
        scrollToEl(nearestCard(document.getElementById("search-input")));
        focusEl(document.getElementById("search-input"));
      }
    },
    "new-issue": {
      portals: ["employee"],
      tab: { employee: "tab-search" },
      run: function () {
        scrollToEl(nearestCard(document.getElementById("search-input")));
        focusEl(document.getElementById("search-input"));
        toastNote("Find the club, open it, then use 'Report Issue' to log an unresolved issue.");
      }
    },
    "dashboard": {
      portals: ["admin"],
      tab: { admin: "tab-dashboard" },
      run: function () { scrollToEl(document.getElementById("tab-dashboard")); }
    },
    "ai-insights": {
      portals: ["admin"],
      tab: { admin: "tab-ai" },
      run: function () { scrollToEl(document.getElementById("tab-ai")); }
    }
  };

  function parseDeepLink(href) {
    var h = String(href || "");
    if (h.indexOf("/manual") === 0) return { kind: "manual" };
    var hashIdx = h.indexOf("#");
    var key = hashIdx >= 0 ? h.slice(hashIdx + 1) : "";
    if (h.indexOf("/admin") === 0) return { kind: "route", portal: "admin", key: key };
    if (h.indexOf("/portal") === 0 || h.indexOf("/employee") === 0) {
      return { kind: "route", portal: "employee", key: key };
    }
    if (key) return { kind: "route", portal: null, key: key };
    return { kind: "url", href: h };
  }

  function executeDeepLink(href) {
    var parsed = parseDeepLink(href);
    if (parsed.kind === "manual") {
      window.open("/manual", "_blank", "noopener");
      return;
    }
    if (parsed.kind === "url") {
      if (parsed.href && parsed.href !== "#") window.location.href = parsed.href;
      return;
    }
    var key = parsed.key;
    var action = DEEP_LINK_ACTIONS[key];
    if (!action) {
      toastNote("That link is not available yet.");
      return;
    }
    var here = currentPortal();
    var target = parsed.portal || here;
    // Slice E fix: suggestion cards carry generic hrefs (/portal#key) even when
    // shown on the admin portal. If THIS portal can handle the key, do it here
    // instead of bouncing the user to the other portal's login gate.
    if (here !== "landing" && action.portals.indexOf(here) >= 0) {
      runDeepLinkAction(key, here);
      return;
    }
    // Landing page (or wrong portal) -> navigate; the hash is processed on load
    // (retries until the portal view is past its login gate).
    if (here === "landing" || (target !== here && action.portals.indexOf(target) >= 0)) {
      var page = target === "admin" ? "/admin" : "/employee";
      window.location.href = page + "#" + key;
      return;
    }
    runDeepLinkAction(key, here);
  }

  function runDeepLinkAction(key, portal) {
    var action = DEEP_LINK_ACTIONS[key];
    if (!action) return false;
    if (action.open) {
      window.open(action.open, "_blank", "noopener");
      return true;
    }
    if (action.portals.indexOf(portal) < 0) return false;
    activateTab((action.tab || {})[portal]);
    action.run(portal);
    return true;
  }

  function portalReady(portal) {
    var probe = portal === "admin"
      ? document.getElementById("tab-dashboard")
      : document.getElementById("employee-portal-view");
    return !!probe && probe.offsetParent !== null;
  }

  function processDeepLinkHash(attempt) {
    var key = String(window.location.hash || "").replace(/^#/, "");
    if (!key || !DEEP_LINK_ACTIONS[key]) return;
    var portal = currentPortal();
    if (portal === "landing") return;
    if (!portalReady(portal)) {
      if ((attempt || 0) < 40) {
        setTimeout(function () { processDeepLinkHash((attempt || 0) + 1); }, 1500);
      }
      return;
    }
    if (runDeepLinkAction(key, portal)) {
      history.replaceState(null, "", window.location.pathname);
    }
  }

  /* ========================================================================
     3. Public handle (tests, quick actions, Slice E proactive badge)
     ==================================================================== */
  window.NDLIAssistant = {
    version: "slice-e-advisor",
    open: open,
    close: close,
    toggle: toggle,
    ask: send,
    deepLink: executeDeepLink,
    showBadge: function (count) {
      var badge = $("ndli-asst-badge");
      if (!badge) return;
      badge.textContent = String(count == null ? 1 : count);
      badge.hidden = false;
    },
    hideBadge: function () {
      var badge = $("ndli-asst-badge");
      if (badge) badge.hidden = true;
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
