    // Opens Certificate Terminal for Active Club
    function openCertificateTerminalForActiveClub() {
      let club = CURRENT_ACTIVE_CLUB;
      const clubId = document.getElementById("edit-club-id") ? document.getElementById("edit-club-id").value : "";
      if (!club && clubId && CURRENT_SEARCH_RESULTS) {
        club = CURRENT_SEARCH_RESULTS.find(c => c.club_id === clubId);
      }
      if (!club && clubId) {
        club = {
          club_id: clubId,
          institution_name: document.getElementById("edit-inst-name").value || clubId,
          reg_no: (document.getElementById("edit-reg-no") ? document.getElementById("edit-reg-no").value.trim() : "") || "",
          date_of_approval: document.getElementById("modal-date-of-approval-full") ? document.getElementById("modal-date-of-approval-full").innerText : "",
          renewal_date: document.getElementById("modal-upcoming-renewal") ? document.getElementById("modal-upcoming-renewal").innerText : ""
        };
      }
      if (club) {
        openCertificateTerminal(club);
      } else {
        showAlert("modal-alert", "No club selected to generate certificate.", "danger");
      }
    }

    // Opens the Renewal Certificate Generation and Download Terminal
    async function openCertificateTerminal(club) {
      try {
        console.log("[NDLI Terminal] Opening Renewal Certificate Terminal for:", club);
        ACTIVE_CERT_CLUB = club;
        const modal = document.getElementById("renewal-certificate-terminal-modal");
        if (!modal) {
          console.error("Modal #renewal-certificate-terminal-modal not found in DOM!");
          return;
        }

        // Populate metadata from master_clubs.csv
        const badgeEl = document.getElementById("cert-club-badge");
        if (badgeEl) badgeEl.innerText = `Club: ${(club && club.club_id) || '-'}`;

        const instEl = document.getElementById("cert-display-inst-name");
        if (instEl) instEl.innerText = (club && club.institution_name) || "-";

        const regEl = document.getElementById("cert-display-reg-no");
        if (regEl) regEl.innerText = (club && club.reg_no) || "Pending";

        const rawDoa = (club && (club.date_of_approval || club.submission_timestamp)) || "";
        const doaEl = document.getElementById("cert-display-doa");
        if (doaEl) {
          doaEl.innerText = typeof CertificateEngine !== "undefined" ? CertificateEngine.formatFormalDate(rawDoa) : (String(rawDoa).split("T")[0] || "-");
        }

        const rawRen = (club && (club.renewal_date || club.next_renewal_date)) || "";
        const renEl = document.getElementById("cert-display-renewal");
        if (renEl) {
          renEl.innerText = typeof CertificateEngine !== "undefined" ? CertificateEngine.formatFormalDate(rawRen) : (String(rawRen) || "-");
        }

        // Initialize certificate engine & fetch persistent settings
        if (typeof CertificateEngine !== "undefined") {
          const settings = await CertificateEngine.init();
          const piNameInput = document.getElementById("cert-pi-name-input");
          const piAffilInput = document.getElementById("cert-pi-affil-input");
          if (piNameInput && settings.pi_name) piNameInput.value = settings.pi_name;
          if (piAffilInput && settings.pi_affiliation) piAffilInput.value = settings.pi_affiliation;

          const thumb = document.getElementById("sig-preview-thumbnail");
          const statusLabel = document.getElementById("sig-status-label");
          if (settings.has_signature && settings.signature_url) {
            if (thumb) {
              thumb.src = settings.signature_url;
              thumb.style.display = "inline-block";
            }
            if (statusLabel) statusLabel.innerText = "Custom Signature Active";
          } else {
            if (thumb) thumb.style.display = "none";
            if (statusLabel) statusLabel.innerText = "Default Script Signature";
          }
        }

        // CRITICAL: Must add .active and .open classes and set inline opacity/visibility
        modal.style.display = "flex";
        modal.classList.add("active");
        modal.classList.add("open");
        modal.style.opacity = "1";
        modal.style.visibility = "visible";
        modal.style.zIndex = "var(--z-modal-terminal)";
        ndliModalOpened(modal);

        updateCertificateLivePreview();
      } catch (err) {
        console.error("Error in openCertificateTerminal:", err);
        UI.toast("Certificate terminal error: " + err.message, { type: "danger" });
      }
    }

    function closeCertificateTerminal() {
      const modal = document.getElementById("renewal-certificate-terminal-modal");
      if (modal) {
        modal.style.display = "none";
        modal.classList.remove("active");
        modal.classList.remove("open");
        modal.style.opacity = "";
        modal.style.visibility = "";
        ndliModalClosed(modal);
      }
      ACTIVE_CERT_CLUB = null;
    }

    let CURRENT_CERT_RENDER_PROMISE = null;
    // R3 #16a: tracks whether the in-flight render has settled, so the print
    // click can run synchronously (keeping user activation) when the canvas is
    // already rendered instead of awaiting a long-resolved promise.
    let CURRENT_CERT_RENDER_SETTLED = false;

    // Live update certificate canvas
    function updateCertificateLivePreview() {
      if (!ACTIVE_CERT_CLUB) return null;
      const canvas = document.getElementById("certificate-canvas");
      if (!canvas || typeof CertificateEngine === "undefined") return null;

      const piName = document.getElementById("cert-pi-name-input") ? document.getElementById("cert-pi-name-input").value : "";
      const piAffiliation = document.getElementById("cert-pi-affil-input") ? document.getElementById("cert-pi-affil-input").value : "";

      CURRENT_CERT_RENDER_SETTLED = false;
      CURRENT_CERT_RENDER_PROMISE = CertificateEngine.renderCertificate(canvas, ACTIVE_CERT_CLUB, {
        pi_name: piName,
        pi_affiliation: piAffiliation
      });
      CURRENT_CERT_RENDER_PROMISE.then(
        () => { CURRENT_CERT_RENDER_SETTLED = true; },
        () => { CURRENT_CERT_RENDER_SETTLED = true; }
      );
      return CURRENT_CERT_RENDER_PROMISE;
    }

    function handleCertificateInputChanged() {
      updateCertificateLivePreview();
    }

    // Handles New PI Signature file upload
    async function handleSignatureUpload(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;

      const statusEl = document.getElementById("sig-upload-status");
      if (statusEl) statusEl.innerText = "⏳ Uploading signature image...";

      const reader = new FileReader();
      reader.onload = async (e) => {
        const base64Data = e.target.result;
        try {
          const res = await apiRequest("/api/certificate/signature", "POST", {
            image_data: base64Data,
            filename: file.name
          });
          if (res.ok && res.data) {
            if (statusEl) statusEl.innerHTML = `<span style="color: #166534; font-weight: 600;">✓ Signature uploaded & saved!</span>`;

            // Update CertificateEngine signature cache
            const img = new Image();
            img.onload = () => {
              if (typeof CertificateEngine !== "undefined") {
                CertificateEngine.setCachedSignatureImage(img);
              }
              const thumb = document.getElementById("sig-preview-thumbnail");
              const statusLabel = document.getElementById("sig-status-label");
              if (thumb) {
                thumb.src = base64Data;
                thumb.style.display = "inline-block";
              }
              if (statusLabel) statusLabel.innerText = "Uploaded Custom Signature";
              updateCertificateLivePreview();
            };
            img.src = base64Data;
          } else {
            if (statusEl) statusEl.innerHTML = `<span style="color: #dc2626;">Upload error: ${res.data.message || 'Failed to save.'}</span>`;
          }
        } catch (err) {
          if (statusEl) statusEl.innerHTML = `<span style="color: #dc2626;">Upload failed: ${err.message}</span>`;
        }
      };
      reader.readAsDataURL(file);
    }

    // Saves PI Name and Affiliation settings to backend
    async function saveDefaultPISettings() {
      const piName = document.getElementById("cert-pi-name-input") ? document.getElementById("cert-pi-name-input").value : "";
      const piAffiliation = document.getElementById("cert-pi-affil-input") ? document.getElementById("cert-pi-affil-input").value : "";

      try {
        const res = await apiRequest("/api/certificate/settings", "POST", {
          pi_name: piName,
          pi_affiliation: piAffiliation
        });
        if (res.ok) {
          UI.toast("Default PI credentials saved successfully!", { type: "success" });
        } else {
          UI.toast(`Save error: ${res.data.message || 'Failed to save.'}`, { type: "danger" });
        }
      } catch (e) {
        UI.toast(`Save error: ${e.message}`, { type: "danger" });
      }
    }

    // High-Resolution JPG Download
    async function downloadActiveCertificateJPG() {
      if (CURRENT_CERT_RENDER_PROMISE) {
        await CURRENT_CERT_RENDER_PROMISE;
      }
      const canvas = document.getElementById("certificate-canvas");
      if (!canvas || !ACTIVE_CERT_CLUB || typeof CertificateEngine === "undefined") {
        UI.toast("Certificate canvas not ready.", { type: "danger" });
        return;
      }
      const filename = `NDLI_Renewal_Certificate_${ACTIVE_CERT_CLUB.club_id}.jpg`;
      await CertificateEngine.downloadCertificateJPG(canvas, filename);
    }

    // High-Resolution PDF Download
    async function downloadActiveCertificatePDF() {
      if (CURRENT_CERT_RENDER_PROMISE) {
        await CURRENT_CERT_RENDER_PROMISE;
      }
      const canvas = document.getElementById("certificate-canvas");
      if (!canvas || !ACTIVE_CERT_CLUB || typeof CertificateEngine === "undefined") {
        UI.toast("Certificate canvas not ready.", { type: "danger" });
        return;
      }
      const filename = `NDLI_Renewal_Certificate_${ACTIVE_CERT_CLUB.club_id}.pdf`;
      await CertificateEngine.downloadCertificatePDF(canvas, filename);
    }

    // Print Certificate (R3 #16a fix)
    // The old flow delegated to CertificateEngine.printCertificate() which opened
    // a popup and called window.print() from the popup img's onload handler — by
    // then the click's transient user activation is gone (and not inherited by
    // the new window), so modern browsers silently ignored window.print() and
    // NOTHING happened (popup blockers could also eat window.open).
    // Fix: run the on-page print route SYNCHRONOUSLY inside this click so the
    // activation is preserved. The popup route is kept only as a fallback when
    // the on-page route cannot run.
    function printActiveCertificate() {
      const canvas = document.getElementById("certificate-canvas");
      if (!canvas || !ACTIVE_CERT_CLUB || typeof CertificateEngine === "undefined") {
        UI.toast("Certificate canvas not ready.", { type: "danger" });
        return;
      }
      const runPrint = () => {
        const c = document.getElementById("certificate-canvas");
        if (!c || !ACTIVE_CERT_CLUB || typeof CertificateEngine === "undefined") {
          UI.toast("Certificate canvas not ready.", { type: "danger" });
          return;
        }
        if (typeof CertificateEngine.printCertificateOnPage === "function" && CertificateEngine.printCertificateOnPage(c)) {
          return; // on-page A4 route succeeded
        }
        // Secondary fallback: legacy popup route (only if the on-page route could not run)
        CertificateEngine.printCertificate(c);
      };
      if (CURRENT_CERT_RENDER_PROMISE && !CURRENT_CERT_RENDER_SETTLED) {
        // Render still in flight: proceed best-effort once it settles.
        CURRENT_CERT_RENDER_PROMISE.then(runPrint).catch((err) => {
          if (typeof UI !== "undefined" && UI.toast) {
            UI.toast("Print failed: " + err.message, { type: "danger" });
          } else {
            alert("Print failed: " + err.message);
          }
        });
        return;
      }
      runPrint();
    }

