/**
 * NDLI Club Management System
 * Official Renewal Certificate Generation & Export Engine
 * 
 * Faithfully reproduces the official template from:
 * "D:\Download\Club Renewal Certificate - Copy.docx"
 * 
 * Features:
 * - Exact official background from reference docx template (static/img/template_reference_bg.jpg)
 * - Native 300 DPI A4 Portrait Resolution (2480 x 3508 px)
 * - Dynamic data replacement:
 *     <institution_name>  -> from master_clubs.csv (formatted centered citation)
 *     <reg_no>            -> from master_clubs.csv (Registration No.: ...)
 *     <date_of_approval>  -> from master_clubs.csv (Date of Registration: ...)
 *     <renewal_date>      -> from master_clubs.csv (Validity Extended Up to: ...)
 * - New PI Signature upload (PNG / JPG) and placement on bottom-right signature block
 * - New PI Name and Affiliation live editing and symmetrical rendering across from Joint PI
 * - High-Resolution 300 DPI JPG Download (2480 x 3508 px)
 * - Zero-Dependency Valid A4 Portrait PDF 1.4 Exporter (DCTDecode JPEG Stream)
 * - Print-ready layout
 * 
 * Author: Dr. Anirban Mukherjee | NDLI IIT Kharagpur
 */

const CertificateEngine = (function () {
  // Official A4 Portrait at 300 DPI standard
  const CANVAS_WIDTH = 2480;
  const CANVAS_HEIGHT = 3508;

  // Cached state
  let preloadedTemplateBg = null;
  let cachedSignatureImage = null;
  let cachedSettings = {
    pi_name: "Prof. Partha Pratim Chakrabarti",
    pi_affiliation: "Principal Investigator\nNational Digital Library of India Project\nCentral Library, IIT Kharagpur",
    has_signature: false,
    signature_url: null
  };

  /**
   * Preloads the official background image extracted from docx template
   */
  function preloadTemplateBg() {
    return new Promise((resolve) => {
      if (preloadedTemplateBg && preloadedTemplateBg.complete && preloadedTemplateBg.naturalWidth > 0) {
        return resolve(preloadedTemplateBg);
      }
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        preloadedTemplateBg = img;
        resolve(img);
      };
      img.onerror = () => {
        console.warn("[CertificateEngine] Could not load template background from /static/img/template_reference_bg.jpg");
        resolve(null);
      };
      img.src = "/static/img/template_reference_bg.jpg?v=2026";
    });
  }

  /**
   * Fetches saved certificate settings from backend
   */
  async function fetchSettings() {
    try {
      const res = await fetch("/api/certificate/settings");
      if (res.ok) {
        const data = await res.json();
        if (data.success && data.settings) {
          cachedSettings = { ...cachedSettings, ...data.settings };
          if (cachedSettings.signature_url) {
            await loadSignatureFromUrl(cachedSettings.signature_url);
          }
        }
      }
    } catch (e) {
      console.warn("[CertificateEngine] Could not fetch certificate settings:", e);
    }
    return cachedSettings;
  }

  /**
   * Loads signature Image object from a URL or data URL
   */
  function loadSignatureFromUrl(url) {
    return new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        cachedSignatureImage = img;
        resolve(img);
      };
      img.onerror = () => {
        console.warn("[CertificateEngine] Failed to load signature from:", url);
        cachedSignatureImage = null;
        resolve(null);
      };
      img.src = url;
    });
  }

  /**
   * Helper: Formats ISO date or string into clean Indian standard DD-MM-YYYY format
   * e.g., "2024-08-15T10:00:00Z" -> "15-08-2024"
   */
  function formatFormalDate(val) {
    if (!val || val === "-" || val === "None") return "N/A";
    try {
      const clean = String(val).split("T")[0].trim();
      const parts = clean.split(/[-/]/);
      if (parts.length === 3) {
        // If YYYY-MM-DD
        if (parts[0].length === 4) {
          return `${parts[2].padStart(2, '0')}-${parts[1].padStart(2, '0')}-${parts[0]}`;
        }
        // If DD-MM-YYYY
        if (parts[2].length === 4) {
          return `${parts[0].padStart(2, '0')}-${parts[1].padStart(2, '0')}-${parts[2]}`;
        }
      }
    } catch (e) {
      // Fallback
    }
    return String(val);
  }

  /**
   * Helper: Renders centered paragraph with mixed bold/regular word styling
   * Used for:
   * “<institution_name>” for registering as an NDLI Club under the National Digital Library of India. This certificate of institutional registration is valid for 1 year.
   */
  function drawCenteredFormattedCitation(ctx, institutionName, centerX, startY, maxWidth, lineHeight) {
    const cleanInst = String(institutionName || "National Digital Library of India Partner Institution").trim();

    // Word tokens with bold/regular flags
    const tokens = [];

    // Prefix quote + institution words + suffix quote
    const instWords = cleanInst.split(/\s+/).filter(Boolean);
    for (let i = 0; i < instWords.length; i++) {
      let word = instWords[i];
      if (i === 0) word = "“" + word;
      if (i === instWords.length - 1) word = word + "”";
      tokens.push({ text: word, bold: true, isInst: true });
    }

    // Subsequent text from docx template
    tokens.push({ text: "for", bold: false });
    tokens.push({ text: "registering", bold: false });
    tokens.push({ text: "as", bold: false });
    tokens.push({ text: "an", bold: false });
    tokens.push({ text: "NDLI", bold: true });
    tokens.push({ text: "Club", bold: true });
    tokens.push({ text: "under", bold: false });
    tokens.push({ text: "the", bold: false });
    tokens.push({ text: "National", bold: false });
    tokens.push({ text: "Digital", bold: false });
    tokens.push({ text: "Library", bold: false });
    tokens.push({ text: "of", bold: false });
    tokens.push({ text: "India.", bold: false });
    tokens.push({ text: "This", bold: false });
    tokens.push({ text: "certificate", bold: false });
    tokens.push({ text: "of", bold: false });
    tokens.push({ text: "institutional", bold: false });
    tokens.push({ text: "registration", bold: false });
    tokens.push({ text: "is", bold: false });
    tokens.push({ text: "valid", bold: true });
    tokens.push({ text: "for", bold: true });
    tokens.push({ text: "1", bold: true });
    tokens.push({ text: "year.", bold: true });

    // Font definitions
    const boldFont = "bold 52px 'Arial Nova Cond', 'Arial', Helvetica, sans-serif";
    const regularFont = "50px 'Arial Nova Cond', 'Arial', Helvetica, sans-serif";

    // Measure space width
    ctx.font = regularFont;
    const spaceWidth = ctx.measureText(" ").width;

    // Group into lines fitting maxWidth
    const lines = [];
    let currentLine = [];
    let currentLineWidth = 0;

    for (const token of tokens) {
      ctx.font = token.bold ? boldFont : regularFont;
      const w = ctx.measureText(token.text).width;
      token.width = w;

      const spaceNeeded = currentLine.length > 0 ? spaceWidth : 0;
      if (currentLineWidth + spaceNeeded + w > maxWidth && currentLine.length > 0) {
        lines.push({ tokens: currentLine, totalWidth: currentLineWidth });
        currentLine = [token];
        currentLineWidth = w;
      } else {
        currentLine.push(token);
        currentLineWidth += spaceNeeded + w;
      }
    }
    if (currentLine.length > 0) {
      lines.push({ tokens: currentLine, totalWidth: currentLineWidth });
    }

    // Draw lines centered
    let y = startY;
    ctx.textBaseline = "middle";

    for (const line of lines) {
      let x = centerX - (line.totalWidth / 2);
      for (const token of line.tokens) {
        ctx.font = token.bold ? boldFont : regularFont;
        ctx.fillStyle = token.isInst ? "#0f2942" : (token.bold ? "#0f172a" : "#1e293b");
        ctx.fillText(token.text, x, y);
        x += token.width + spaceWidth;
      }
      y += lineHeight;
    }

    return y;
  }

  /**
   * Helper: Fallback script signature if no custom signature is uploaded
   */
  function drawCalligraphicSignature(ctx, name, x, y) {
    ctx.save();
    ctx.font = "italic 76px 'Brush Script MT', 'Lucida Handwriting', 'Segoe Script', cursive";
    ctx.fillStyle = "#1e3a8a"; // Ink blue matching Dr. B. Sutradhar's signature
    ctx.textAlign = "center";
    ctx.fillText(name || "P. P. Chakrabarti", x, y);
    ctx.restore();
  }

  /**
   * Main Render Method: Renders the entire renewal certificate onto the canvas
   * matching D:\Download\Club Renewal Certificate - Copy.docx 1:1
   * 
   * @param {HTMLCanvasElement} canvas
   * @param {Object} clubData - from master_clubs.csv:
   *   - institution_name
   *   - reg_no
   *   - date_of_approval
   *   - renewal_date
   *   - club_id
   * @param {Object} options:
   *   - pi_name: string
   *   - pi_affiliation: string
   *   - signature_img: HTMLImageElement or dataUrl
   */
  async function renderCertificate(canvas, clubData = {}, options = {}) {
    if (!canvas) throw new Error("Canvas element is required for rendering.");

    // Standard A4 Portrait 300 DPI
    canvas.width = CANVAS_WIDTH;
    canvas.height = CANVAS_HEIGHT;
    const ctx = canvas.getContext("2d");

    // Preload background image extracted from docx template
    const bgImg = await preloadTemplateBg();

    // Data from master_clubs.csv
    const institutionName = (clubData.institution_name || "National Digital Library of India Partner Institution").trim();
    const regNo = (clubData.reg_no || "NDLI/REG/2024/001").trim();
    const rawDoa = clubData.date_of_approval || clubData.submission_timestamp || "";
    const rawRenewal = clubData.renewal_date || clubData.next_renewal_date || "";

    const dateOfApproval = formatFormalDate(rawDoa);
    const renewalDate = formatFormalDate(rawRenewal);

    // Options / settings
    const piName = (options.pi_name || cachedSettings.pi_name || "Prof. Partha Pratim Chakrabarti").trim();
    const piAffiliation = (options.pi_affiliation || cachedSettings.pi_affiliation || "Principal Investigator\nNational Digital Library of India Project\nCentral Library, IIT Kharagpur").trim();
    const sigImg = options.signature_img || cachedSignatureImage;

    // -------------------------------------------------------------
    // 1. DRAW OFFICIAL TEMPLATE BACKGROUND
    // -------------------------------------------------------------
    if (bgImg && bgImg.complete && bgImg.naturalWidth > 0) {
      ctx.drawImage(bgImg, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    } else {
      // Fallback background in case image is still loading
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      ctx.strokeStyle = "#103125";
      ctx.lineWidth = 16;
      ctx.strokeRect(40, 40, CANVAS_WIDTH - 80, CANVAS_HEIGHT - 80);
    }

    // -------------------------------------------------------------
    // 2. BLOCK 1: DYNAMIC INSTITUTION NAME & CITATION STATEMENT
    // Exactly matches Paragraph 7 of docx:
    // “<institution_name>” for registering as an NDLI Club under the National Digital Library of India. This certificate of institutional registration is valid for 1 year.
    // -------------------------------------------------------------
    const citationCenterY = 1620; // 46.2% of page height, directly beneath "is issued to"
    const citationCenterX = CANVAS_WIDTH / 2;
    const citationMaxWidth = 1960;
    const citationLineHeight = 82;

    drawCenteredFormattedCitation(ctx, institutionName, citationCenterX, citationCenterY, citationMaxWidth, citationLineHeight);

    // -------------------------------------------------------------
    // 3. BLOCK 2: DYNAMIC REGISTRATION DETAILS (NEXT TO NDLI CLUB PARTNER BADGE)
    // Exactly matches Paragraph 4, 5, 6 of docx:
    // Registration No.: <reg_no>
    // Date of Registration: <date_of_approval>
    // Validity Extended Up to: <renewal_date>
    // -------------------------------------------------------------
    // 3. BLOCK 2: DYNAMIC REGISTRATION DETAILS (NEXT TO NDLI CLUB PARTNER BADGE)
    // Registration NO.: <reg_no>
    // Date of Registration: <date_of_approval>
    // Validity Extended Up to: <renewal_date>
    // - Increased font size (50px) for prominent readability
    // - Symmetrically and vertically aligned with partner badge on the left
    // -------------------------------------------------------------
    const detailsX = 1290; // Aligned cleanly to the right of the vertical divider at x=1239
    const detailsLineSpacing = 82; // Increased spacing for larger font
    const detailsCenterY = 2264;   // Exact vertical center of logo partner badge [2115, 2413]
    let detailsY = detailsCenterY - detailsLineSpacing; // Starts at 2182, centering row 2 at 2264

    const metadataRows = [
      { label: "Registration NO.: ", val: regNo },
      { label: "Date of Registration: ", val: dateOfApproval },
      { label: "Validity Extended Up to: ", val: renewalDate }
    ];

    const labelFont = "bold 50px 'Calibri', 'Segoe UI', Arial, sans-serif";
    const valueFont = "500 50px 'Calibri', 'Segoe UI', Arial, sans-serif";

    ctx.textAlign = "left";
    ctx.textBaseline = "middle";

    for (const row of metadataRows) {
      // Draw bold label
      ctx.font = labelFont;
      ctx.fillStyle = "#0f172a";
      ctx.fillText(row.label, detailsX, detailsY);
      const labelW = ctx.measureText(row.label).width;

      // Draw value
      ctx.font = valueFont;
      ctx.fillStyle = "#1e293b";
      ctx.fillText(row.val, detailsX + labelW, detailsY);

      detailsY += detailsLineSpacing;
    }

    // -------------------------------------------------------------
    // 4. BLOCK 3: PI SIGNATURE & AFFILIATION (LOWER-LEFT SIDE)
    // Placed at the lower-left, replacing Dr. B. Sutradhar:
    // - Clear background rect for pristine white canvas in lower-left
    // - PI Signature above horizontal line
    // - Horizontal signature line (x = 240 to 980, y = 2835)
    // - PI Name (Bold 54px, highly prominent)
    // - PI Affiliation (Semi-bold 40px, highly prominent)
    // -------------------------------------------------------------
    // Safety clear of lower-left signature area
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(200, 2580, 860, 620);

    const sigLineStartX = 240;
    const sigLineEndX = 980;
    const sigLineY = 2835; // Standard signature rule Y
    const sigCenterX = (sigLineStartX + sigLineEndX) / 2;

    // Draw uploaded PI signature image or calligraphic script fallback
    // Increased input signature bounding box up to 600 x 220 px
    if (sigImg && (sigImg.complete || sigImg.naturalWidth > 0)) {
      const maxSigW = 600;
      const maxSigH = 220;
      const sigAspect = (sigImg.naturalWidth || sigImg.width || 2) / (sigImg.naturalHeight || sigImg.height || 1);
      let targetW = maxSigW;
      let targetH = targetW / sigAspect;
      if (targetH > maxSigH) {
        targetH = maxSigH;
        targetW = targetH * sigAspect;
      }
      const sigImgX = sigCenterX - (targetW / 2);
      const sigImgY = sigLineY - targetH - 2;
      ctx.drawImage(sigImg, sigImgX, sigImgY, targetW, targetH);
    } else {
      drawCalligraphicSignature(ctx, piName, sigCenterX, sigLineY - 18);
    }

    // Horizontal signature line
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 3.5;
    ctx.beginPath();
    ctx.moveTo(sigLineStartX, sigLineY);
    ctx.lineTo(sigLineEndX, sigLineY);
    ctx.stroke();

    // PI Name - Bold slab serif (Rockwell / Cambria / Georgia) matching Dr. B. Sutradhar's style
    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 48px 'Rockwell', 'Roboto Slab', 'Cambria', 'Georgia', serif";
    ctx.textAlign = "left";
    ctx.fillText(piName, sigLineStartX, sigLineY + 54);

    // PI Affiliation - Clean sans-serif 35px matching Dr. B. Sutradhar's affiliation typography
    const affilLines = piAffiliation.split(/[\r\n]+/).map(s => s.trim()).filter(Boolean);
    let affilY = sigLineY + 104;
    ctx.font = "35px 'Calibri', 'Segoe UI', Arial, sans-serif";
    ctx.fillStyle = "#1e293b";
    ctx.textAlign = "left";

    for (const aLine of affilLines) {
      ctx.fillText(aLine, sigLineStartX, affilY);
      affilY += 48;
    }

    // -------------------------------------------------------------
    // 5. BLOCK 4: SUBTLE VERIFICATION FOOTER
    // -------------------------------------------------------------
    const certSerial = `NDLI-REN-${(clubData.club_id || 'CLUB')}-${regNo.replace(/[^A-Za-z0-9]/g, '')}`;
    ctx.font = "18px 'Calibri', monospace";
    ctx.fillStyle = "rgba(100, 116, 139, 0.65)";
    ctx.textAlign = "right";
    ctx.fillText(`Ref: ${certSerial}`, CANVAS_WIDTH - 90, CANVAS_HEIGHT - 35);

    return canvas;
  }

  /**
   * Generates a 300 DPI High-Resolution JPEG Blob from canvas
   */
  function getCertificateJpegBlob(canvas) {
    return new Promise((resolve, reject) => {
      try {
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("Canvas failed to export as JPEG blob."));
        }, "image/jpeg", 0.98);
      } catch (e) {
        reject(e);
      }
    });
  }

  /**
   * Triggers download of high-resolution JPG (2480 x 3508 px at 300 DPI)
   */
  async function downloadCertificateJPG(canvas, filename) {
    const blob = await getCertificateJpegBlob(canvas);
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename.endsWith(".jpg") ? filename : `${filename}.jpg`;
    document.body.appendChild(link);
    link.click();
    setTimeout(() => {
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);
    }, 1000);
  }

  /**
   * Pure zero-dependency PDF 1.4 A4 Portrait Generator from JPEG Blob
   * Embeds 2480 x 3508 px JPEG as standard DCTDecode XObject.
   */
  async function createPdf14FromJpegBlob(jpegBlob, wPx = CANVAS_WIDTH, hPx = CANVAS_HEIGHT) {
    const arrayBuffer = await jpegBlob.arrayBuffer();
    const jpegBytes = new Uint8Array(arrayBuffer);

    // Standard A4 Portrait in PDF PostScript Points (72 pt / inch)
    const pw = 595.28;
    const ph = 841.89;

    const encoder = new TextEncoder();
    const byteChunks = [];
    const offsets = [0];

    function addChunk(strOrUint8) {
      const u8 = typeof strOrUint8 === "string" ? encoder.encode(strOrUint8) : strOrUint8;
      byteChunks.push(u8);
    }

    function getCurrentOffset() {
      let total = 0;
      for (const ch of byteChunks) total += ch.length;
      return total;
    }

    // PDF Header
    addChunk("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");

    // 1 0 obj: Catalog
    offsets.push(getCurrentOffset());
    addChunk("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");

    // 2 0 obj: Pages
    offsets.push(getCurrentOffset());
    addChunk("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n");

    // 3 0 obj: Page (A4 Portrait)
    offsets.push(getCurrentOffset());
    addChunk(
      `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw.toFixed(2)} ${ph.toFixed(2)}] ` +
      `/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n`
    );

    // 4 0 obj: Contents Stream
    const streamContent = `q\n${pw.toFixed(2)} 0 0 ${ph.toFixed(2)} 0 0 cm\n/Im1 Do\nQ\n`;
    offsets.push(getCurrentOffset());
    addChunk(
      `4 0 obj\n<< /Length ${streamContent.length} >>\nstream\n${streamContent}endstream\nendobj\n`
    );

    // 5 0 obj: Image XObject (Embedded DCTDecode JPEG)
    offsets.push(getCurrentOffset());
    const obj5Header =
      `5 0 obj\n<< /Type /XObject /Subtype /Image /Width ${wPx} /Height ${hPx} ` +
      `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`;
    addChunk(obj5Header);
    addChunk(jpegBytes);
    addChunk("\nendstream\nendobj\n");

    // 6 0 obj: Document Info
    offsets.push(getCurrentOffset());
    addChunk(
      "6 0 obj\n<< /Title (NDLI Club Renewal Certificate) " +
      "/Author (National Digital Library of India, IIT Kharagpur) " +
      "/Creator (NDLI Club Portal) >>\nendobj\n"
    );

    // xref table
    const startXref = getCurrentOffset();
    let xref = "xref\n0 7\n0000000000 65535 f \n";
    for (let i = 1; i <= 6; i++) {
      const offStr = String(offsets[i]).padStart(10, "0");
      xref += `${offStr} 00000 n \n`;
    }
    addChunk(xref);

    // trailer
    addChunk(
      `trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R >>\nstartxref\n${startXref}\n%%EOF\n`
    );

    // Concatenate all chunks
    let totalLen = 0;
    for (const c of byteChunks) totalLen += c.length;
    const finalBuffer = new Uint8Array(totalLen);
    let cur = 0;
    for (const c of byteChunks) {
      finalBuffer.set(c, cur);
      cur += c.length;
    }

    return new Blob([finalBuffer], { type: "application/pdf" });
  }

  /**
   * Triggers download of high-resolution A4 Portrait PDF
   */
  async function downloadCertificatePDF(canvas, filename) {
    const jpegBlob = await getCertificateJpegBlob(canvas);
    const pdfBlob = await createPdf14FromJpegBlob(jpegBlob, CANVAS_WIDTH, CANVAS_HEIGHT);
    const downloadUrl = URL.createObjectURL(pdfBlob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename.endsWith(".pdf") ? filename : `${filename}.pdf`;
    document.body.appendChild(link);
    link.click();
    setTimeout(() => {
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);
    }, 1000);
  }

  /**
   * Triggers clean print view for A4 portrait certificate
   */
  async function printCertificate(canvas) {
    const dataUrl = canvas.toDataURL("image/jpeg", 0.98);
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      alert("Popup blocked! Please allow popups for this site to print the certificate.");
      return;
    }
    printWindow.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Print NDLI Club Renewal Certificate</title>
        <style>
          @page {
            size: A4 portrait;
            margin: 0;
          }
          body {
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #ffffff;
          }
          img {
            width: 100vw;
            height: 100vh;
            object-fit: contain;
          }
        </style>
      </head>
      <body>
        <img src="${dataUrl}" onload="window.print(); window.close();" />
      </body>
      </html>
    `);
    printWindow.document.close();
  }

  /**
   * Public API
   */
  return {
    init: fetchSettings,
    preloadTemplateBg: preloadTemplateBg,
    loadSignatureFromUrl: loadSignatureFromUrl,
    setCachedSignatureImage: (img) => { cachedSignatureImage = img; },
    getCachedSignatureImage: () => cachedSignatureImage,
    renderCertificate: renderCertificate,
    downloadCertificateJPG: downloadCertificateJPG,
    downloadCertificatePDF: downloadCertificatePDF,
    printCertificate: printCertificate,
    getCachedSettings: () => cachedSettings,
    formatFormalDate: formatFormalDate
  };
})();
