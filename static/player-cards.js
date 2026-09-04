(function () {
  "use strict";

  const clubSelect = document.getElementById("clubSelect");
  const leagueSelect = document.getElementById("leagueSelect");
  const clubMeta = document.getElementById("clubMeta");
  const cardsBoard = document.getElementById("cardsBoard");
  const statusBanner = document.getElementById("statusBanner");
  const refreshBtn = document.getElementById("refreshBtn");
  const exportPdfBtn = document.getElementById("exportPdfBtn");
  const printBtn = document.getElementById("printBtn");
  const exportRoot = document.getElementById("exportRoot");
  const editCardsToggle = document.getElementById("editCardsToggle") || document.getElementById("editHeightToggle");

  const SEASON = "26/27";
  const DEFAULT_LEAGUE = "League Two";
  const LEAGUES = ["Championship", "League One", "League Two"];
  const FOOT_OPTIONS = ["?", "RIGHT", "LEFT"];
  const CARDS_PER_PAGE = 6;
  const EXPORT_PAGE_WIDTH = 1123;
  const EXPORT_PAGE_HEIGHT = 794;
  const EXPORT_CAPTURE_SCALE = 2;
  const EXPORT_JPEG_QUALITY = 0.92;

  let meta = null;
  let loading = false;
  let loadToken = 0;
  let currentPlayers = [];
  let pasteTargetPlayer = null;

  const PHOTO_MAX_WIDTH = 480;
  const PHOTO_MAX_HEIGHT = 520;
  const PHOTO_JPEG_QUALITY = 0.88;

  function setStatus(message, isError) {
    if (!message) {
      statusBanner.classList.add("hidden");
      statusBanner.textContent = "";
      return;
    }
    statusBanner.classList.remove("hidden");
    statusBanner.textContent = message;
    statusBanner.style.background = isError ? "#fef2f2" : "#fff7ed";
    statusBanner.style.borderColor = isError ? "#fca5a5" : "#fdba74";
    statusBanner.style.color = isError ? "#991b1b" : "#9a3412";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }

  function overridesKey() {
    return `pc-overrides:${SEASON}:${clubSelect.value || ""}`;
  }

  function loadOverrides() {
    try {
      const raw = localStorage.getItem(overridesKey());
      return raw ? JSON.parse(raw) : {};
    } catch (_) {
      return {};
    }
  }

  function saveOverrides(data) {
    try {
      localStorage.setItem(overridesKey(), JSON.stringify(data));
    } catch (_) {
      /* ignore quota errors */
    }
  }

  function normalizeFoot(value) {
    const raw = String(value || "").trim().toUpperCase();
    if (raw === "LEFT" || raw === "L") return "LEFT";
    if (raw === "RIGHT" || raw === "R") return "RIGHT";
    return "?";
  }

  function nextFoot(value) {
    const current = normalizeFoot(value);
    const index = FOOT_OPTIONS.indexOf(current);
    return FOOT_OPTIONS[(index + 1) % FOOT_OPTIONS.length];
  }

  function resolveFoot(player, override) {
    if (override && Object.prototype.hasOwnProperty.call(override, "foot")) {
      return normalizeFoot(override.foot);
    }
    return normalizeFoot(player.foot);
  }

  function isLeftFoot(foot) {
    return normalizeFoot(foot) === "LEFT";
  }

  function isUnknownFoot(foot) {
    return normalizeFoot(foot) === "?";
  }

  function isUnknownValue(value) {
    const raw = String(value == null ? "" : value).trim();
    if (!raw) return true;
    const upper = raw.toUpperCase();
    if (
      upper === "—" ||
      upper === "–" ||
      upper === "-" ||
      upper === "?" ||
      upper === "N/A" ||
      upper === "NA" ||
      upper === "UNKNOWN" ||
      upper === "TBC" ||
      upper === "TBD"
    ) {
      return true;
    }
    // Bad / missing age from data sources
    if (/^0(\s*Y\/?O)?$/i.test(raw)) return true;
    return false;
  }

  function unknownClassSuffix(value) {
    return isUnknownValue(value) ? " pc-card__stat--unknown" : "";
  }

  function unknownPositionClass(value) {
    return isUnknownValue(value) ? " pc-card__position--unknown" : "";
  }

  function fieldBackground(value, foot) {
    if (foot !== undefined) return footBackground(foot);
    return isUnknownValue(value) ? "#2563eb" : "#e52320";
  }

  function footClass(foot) {
    if (isLeftFoot(foot)) {
      return "pc-card__stat pc-card__stat--foot pc-card__stat--left";
    }
    if (isUnknownFoot(foot)) {
      return "pc-card__stat pc-card__stat--foot pc-card__stat--unknown";
    }
    return "pc-card__stat pc-card__stat--foot";
  }

  function footBackground(foot) {
    if (isLeftFoot(foot)) return "#22b14c";
    if (isUnknownFoot(foot)) return "#2563eb";
    return "#e52320";
  }

  function applyUnknownClass(el, value, kind) {
    if (!el) return;
    const unknownClass = kind === "position" ? "pc-card__position--unknown" : "pc-card__stat--unknown";
    el.classList.toggle(unknownClass, isUnknownValue(value));
  }

  function editCardsEnabled() {
    return editCardsToggle && editCardsToggle.checked;
  }

  function setToggleUi(toggle, enabled) {
    if (!toggle) return;
    toggle.checked = enabled;
    const label = toggle.closest(".pc-toggle");
    if (label) {
      label.classList.toggle("is-active", enabled);
    }
  }

  function overrideOr(player, override, key, fallback) {
    if (override && Object.prototype.hasOwnProperty.call(override, key)) {
      const value = override[key];
      if (value === null || value === undefined) return fallback;
      return value;
    }
    if (player[key] === null || player[key] === undefined || player[key] === "") {
      return fallback;
    }
    return player[key];
  }

  function resolveHeader(player, override) {
    if (override && Object.prototype.hasOwnProperty.call(override, "header") && override.header) {
      return String(override.header);
    }
    const surname = String(player.surname || player.name || "").toUpperCase();
    let shirt = null;
    if (override && Object.prototype.hasOwnProperty.call(override, "shirt_number")) {
      shirt = override.shirt_number;
    } else if (player.shirt_number !== null && player.shirt_number !== undefined) {
      shirt = player.shirt_number;
    }
    if (shirt !== null && shirt !== undefined && String(shirt).trim() !== "" && String(shirt) !== "—") {
      return `${String(shirt).trim()}. ${surname}`;
    }
    return surname || player.header || player.name || "—";
  }

  function chunkPlayers(players, size) {
    const chunks = [];
    for (let index = 0; index < players.length; index += size) {
      chunks.push(players.slice(index, index + size));
    }
    return chunks;
  }

  function slugifyClubName(value) {
    return String(value || "opponent")
      .trim()
      .toLowerCase()
      .replace(/[^\w\s\-]+/g, "")
      .replace(/\s+/g, "-")
      .replace(/^-+|-+$/g, "") || "opponent";
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  function liveCardDisplayedImg(liveCard) {
    if (!liveCard) return null;
    const img = liveCard.querySelector("img.pc-card__photo");
    if (!img || !img.naturalWidth || !img.naturalHeight) return null;
    return img;
  }

  function canvasDataUrlFromImage(img) {
    if (!img || !img.naturalWidth || !img.naturalHeight) return null;
    try {
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(img, 0, 0);
      return canvas.toDataURL("image/jpeg", 0.92);
    } catch (_) {
      return null;
    }
  }

  function blobToDataUrl(blob) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        resolve(reader.result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function fetchExactUrlAsDataUrl(url) {
    if (!url) return null;
    if (String(url).indexOf("data:") === 0) return url;

    // Same-origin / relative first
    try {
      const direct = await fetch(url, {
        mode: "cors",
        credentials: "same-origin",
        cache: "force-cache",
      });
      if (direct.ok) {
        const blob = await direct.blob();
        if (blob && String(blob.type || "").indexOf("image/") === 0) {
          return await blobToDataUrl(blob);
        }
      }
    } catch (_) {
      /* try proxy */
    }

    // Absolute remote — use our proxy so we never swap to a different fallback photo
    if (String(url).indexOf("http://") === 0 || String(url).indexOf("https://") === 0) {
      try {
        const proxied = await fetch(
          `/api/player-cards/image-proxy?url=${encodeURIComponent(url)}`,
          { cache: "force-cache" }
        );
        if (!proxied.ok) return null;
        const blob = await proxied.blob();
        if (!blob || String(blob.type || "").indexOf("image/") !== 0) return null;
        return await blobToDataUrl(blob);
      } catch (_) {
        return null;
      }
    }
    return null;
  }

  async function lockDisplayedPhotoDataUrl(liveCard, override) {
    if (override && override.photo) return override.photo;

    const img = liveCardDisplayedImg(liveCard);
    if (!img) return null;

    // 1) Exact pixels already on screen (works for pasted / same-origin)
    const fromCanvas = canvasDataUrlFromImage(img);
    if (fromCanvas) return fromCanvas;

    // 2) Re-fetch ONLY the URL currently displayed — never photo_fallbacks
    const displayed = img.currentSrc || img.getAttribute("src") || "";
    return fetchExactUrlAsDataUrl(displayed);
  }

  async function freezeCardForExport(liveCard, override) {
    const clone = liveCard.cloneNode(true);
    clone.querySelectorAll("button, input").forEach(function (el) {
      const div = document.createElement("div");
      div.className = el.className
        .replace(/\bpc-card__stat--clickable\b/g, "")
        .replace(/\bpc-card__stat--edit\b/g, "")
        .replace(/\bpc-card__stat--foot-toggle\b/g, "")
        .replace(/\bpc-card__header--clickable\b/g, "")
        .replace(/\bpc-card__header--edit\b/g, "")
        .replace(/\bpc-card__position--clickable\b/g, "")
        .replace(/\bpc-card__position--edit\b/g, "")
        .replace(/\bpc-card__photo--pasteable\b/g, "")
        .replace(/\bpc-card__photo--paste-active\b/g, "")
        .trim();
      if (el.tagName === "INPUT") {
        div.textContent = el.value || "—";
      } else {
        div.textContent = el.textContent || "—";
      }
      if (el.classList.contains("pc-card__stat--left") || div.classList.contains("pc-card__stat--left")) {
        div.classList.add("pc-card__stat--left");
      }
      if (el.classList.contains("pc-card__stat--unknown") || div.classList.contains("pc-card__stat--unknown")) {
        div.classList.add("pc-card__stat--unknown");
      }
      if (el.classList.contains("pc-card__position--unknown") || div.classList.contains("pc-card__position--unknown")) {
        div.classList.add("pc-card__position--unknown");
      }
      if (el.classList.contains("pc-card__header") || el.classList.contains("pc-card__header--edit") || el.classList.contains("pc-card__header--clickable")) {
        div.classList.add("pc-card__header");
      }
      if (el.classList.contains("pc-card__position") || el.classList.contains("pc-card__position--edit") || el.classList.contains("pc-card__position--clickable")) {
        div.classList.add("pc-card__position");
      }
      if (el.classList.contains("pc-card__photo--placeholder")) {
        div.className = "pc-card__photo pc-card__photo--placeholder";
        div.textContent = "No photo";
      }
      el.replaceWith(div);
    });

    const wrap = clone.querySelector(".pc-card__photo-wrap");
    const locked = await lockDisplayedPhotoDataUrl(liveCard, override || {});
    if (wrap) {
      if (locked) {
        wrap.innerHTML = `<img class="pc-card__photo" src="${escapeAttr(locked)}" alt="" />`;
      } else if (!wrap.querySelector("img.pc-card__photo")) {
        wrap.innerHTML = `<div class="pc-card__photo pc-card__photo--placeholder">No photo</div>`;
      } else {
        // Could not lock remote pixels — show placeholder rather than a different photo
        wrap.innerHTML = `<div class="pc-card__photo pc-card__photo--placeholder">No photo</div>`;
      }
    }
    return clone;
  }

  function renderExportCard(player, overrides) {
    const override = overrides[player.name] || {};
    const header = resolveHeader(player, override);
    const height = overrideOr(player, override, "height", "—");
    const age = overrideOr(player, override, "age", "—");
    const position = overrideOr(player, override, "position", "—");
    const foot = resolveFoot(player, override);
    const heightBg = fieldBackground(height);
    const ageBg = fieldBackground(age);
    const positionBg = fieldBackground(position);
    const footBg = footBackground(foot);
    const photo = override.photo
      ? `<img class="pc-card__photo" src="${escapeAttr(override.photo)}" alt="" />`
      : `<div class="pc-card__photo pc-card__photo--placeholder">No photo</div>`;

    return `
      <article class="pc-card" style="display:flex;flex-direction:column;min-height:0;height:100%;background:#fff;overflow:hidden;">
        <div class="pc-card__header" style="background:#000;color:#fff;font-family:Barlow Condensed,Impact,Arial Narrow,sans-serif;font-size:28px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;text-align:center;padding:10px 8px;line-height:1.05;">${escapeHtml(header)}</div>
        <div class="pc-card__photo-wrap">${photo}</div>
        <div class="pc-card__footer" style="display:flex;flex-direction:column;gap:4px;padding:0 2px 2px;background:#fff;">
          <div class="pc-card__stats-row" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;">
            <div class="pc-card__stat" style="background:${heightBg};color:#fff;font-family:Barlow Condensed,Impact,Arial Narrow,sans-serif;font-size:22px;font-weight:800;text-transform:uppercase;text-align:center;padding:10px 4px;line-height:1.05;display:flex;align-items:center;justify-content:center;">${escapeHtml(height)}</div>
            <div class="pc-card__stat" style="background:${ageBg};color:#fff;font-family:Barlow Condensed,Impact,Arial Narrow,sans-serif;font-size:22px;font-weight:800;text-transform:uppercase;text-align:center;padding:10px 4px;line-height:1.05;display:flex;align-items:center;justify-content:center;">${escapeHtml(age)}</div>
            <div class="pc-card__stat" style="background:${footBg};color:#fff;font-family:Barlow Condensed,Impact,Arial Narrow,sans-serif;font-size:22px;font-weight:800;text-transform:uppercase;text-align:center;padding:10px 4px;line-height:1.05;display:flex;align-items:center;justify-content:center;">${escapeHtml(foot)}</div>
          </div>
          <div class="pc-card__position" style="background:${positionBg};color:#fff;font-family:Barlow Condensed,Impact,Arial Narrow,sans-serif;font-size:20px;font-weight:800;text-transform:uppercase;text-align:center;padding:10px 8px;line-height:1.1;">${escapeHtml(position)}</div>
        </div>
      </article>
    `;
  }

  async function buildPageElement(chunk, overrides, className) {
    const page = document.createElement("div");
    page.className = className;
    page.style.cssText = [
      `width:${EXPORT_PAGE_WIDTH}px`,
      `height:${EXPORT_PAGE_HEIGHT}px`,
      "box-sizing:border-box",
      "display:grid",
      "grid-template-columns:repeat(3,minmax(0,1fr))",
      "grid-template-rows:repeat(2,minmax(0,1fr))",
      "gap:18px",
      "padding:18px",
      "background:#fff",
    ].join(";");

    for (let i = 0; i < chunk.length; i += 1) {
      const player = chunk[i];
      const override = overrides[player.name] || {};
      const live = cardsBoard.querySelector(
        `.pc-card[data-player="${CSS.escape(player.name)}"]`
      );
      if (live) {
        const clone = await freezeCardForExport(live, override);
        clone.style.minHeight = "0";
        clone.style.height = "100%";
        page.appendChild(clone);
      } else {
        const wrap = document.createElement("div");
        wrap.innerHTML = renderExportCard(player, overrides);
        page.appendChild(wrap.firstElementChild);
      }
    }
    return page;
  }

  async function waitForExportImages(container, timeoutMs) {
    const images = Array.from(container.querySelectorAll("img"));
    if (!images.length) return;

    await Promise.all(
      images.map(function (img) {
        if (img.complete && img.naturalWidth > 0) return Promise.resolve();
        return new Promise(function (resolve) {
          const timer = window.setTimeout(resolve, timeoutMs);
          img.addEventListener(
            "load",
            function () {
              window.clearTimeout(timer);
              resolve();
            },
            { once: true }
          );
          img.addEventListener(
            "error",
            function () {
              window.clearTimeout(timer);
              resolve();
            },
            { once: true }
          );
        });
      })
    );
  }

  async function captureExportPages() {
    if (typeof html2canvas !== "function") {
      throw new Error("Export unavailable — reload the page.");
    }
    if (!exportRoot) {
      throw new Error("Export container missing.");
    }

    const overrides = loadOverrides();
    const chunks = chunkPlayers(currentPlayers, CARDS_PER_PAGE);
    const pages = [];

    exportRoot.hidden = false;
    exportRoot.setAttribute("aria-hidden", "false");
    document.body.classList.add("is-exporting");

    if (document.fonts && document.fonts.ready) {
      try {
        await document.fonts.ready;
      } catch (_) {
        /* ignore */
      }
    }

    try {
      for (let index = 0; index < chunks.length; index += 1) {
        exportRoot.innerHTML = "";
        setStatus(`Capturing page ${index + 1} of ${chunks.length}…`, false);
        const pageEl = await buildPageElement(chunks[index], overrides, "pc-export-page");
        exportRoot.appendChild(pageEl);

        await waitForExportImages(pageEl, 4000);
        await new Promise(function (resolve) {
          requestAnimationFrame(function () {
            requestAnimationFrame(resolve);
          });
        });

        const canvas = await html2canvas(pageEl, {
          backgroundColor: "#ffffff",
          scale: EXPORT_CAPTURE_SCALE,
          useCORS: true,
          allowTaint: false,
          logging: false,
          width: EXPORT_PAGE_WIDTH,
          height: EXPORT_PAGE_HEIGHT,
          windowWidth: EXPORT_PAGE_WIDTH,
          windowHeight: EXPORT_PAGE_HEIGHT,
          x: 0,
          y: 0,
          scrollX: 0,
          scrollY: 0,
          onclone: function (clonedDoc, clonedEl) {
            clonedDoc.body.style.background = "#ffffff";
            clonedDoc.body.style.margin = "0";
            clonedDoc.body.style.padding = "0";
            const root = clonedDoc.querySelector(".pc-export-root");
            if (root) {
              root.style.cssText =
                "position:static;visibility:visible;opacity:1;left:0;top:0;z-index:1;pointer-events:none;";
            }
            if (clonedEl) {
              clonedEl.style.width = `${EXPORT_PAGE_WIDTH}px`;
              clonedEl.style.height = `${EXPORT_PAGE_HEIGHT}px`;
              clonedEl.style.display = "grid";
              clonedEl.style.gridTemplateColumns = "repeat(3, minmax(0, 1fr))";
              clonedEl.style.gridTemplateRows = "repeat(2, minmax(0, 1fr))";
              clonedEl.style.gap = "18px";
              clonedEl.style.padding = "18px";
              clonedEl.style.background = "#ffffff";
              clonedEl.style.boxSizing = "border-box";
            }
          },
        });

        pages.push({
          imageData: canvas.toDataURL("image/jpeg", EXPORT_JPEG_QUALITY),
          width: canvas.width,
          height: canvas.height,
        });
      }
      return pages;
    } finally {
      exportRoot.innerHTML = "";
      exportRoot.hidden = true;
      exportRoot.setAttribute("aria-hidden", "true");
      document.body.classList.remove("is-exporting");
    }
  }

  async function exportPdf() {
    if (!currentPlayers.length) {
      setStatus("Load a squad before exporting.", true);
      return;
    }
    if (exportPdfBtn) exportPdfBtn.disabled = true;
    if (printBtn) printBtn.disabled = true;
    refreshBtn.disabled = true;

    try {
      const pages = await captureExportPages();
      const club = clubSelect.value || "opponent";
      const filename = `player-cards-${slugifyClubName(club)}.pdf`;
      setStatus("Building PDF…", false);

      const response = await fetch("/api/player-cards/export-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pages,
          filename,
          club_name: club,
        }),
      });

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "PDF export failed.");
      }

      const blob = await response.blob();
      downloadBlob(blob, filename);
      const sizeMb = (blob.size / (1024 * 1024)).toFixed(1);
      setStatus(`PDF downloaded · ${pages.length} pages · ${sizeMb} MB`, false);
    } catch (error) {
      setStatus(error.message || "PDF export failed.", true);
    } finally {
      if (exportPdfBtn) exportPdfBtn.disabled = false;
      if (printBtn) printBtn.disabled = false;
      refreshBtn.disabled = false;
    }
  }

  async function printLandscape() {
    if (!currentPlayers.length) {
      setStatus("Load a squad before printing.", true);
      return;
    }

    const overrides = loadOverrides();
    const existing = document.getElementById("printRoot");
    if (existing) existing.remove();

    const printRoot = document.createElement("div");
    printRoot.id = "printRoot";
    document.body.appendChild(printRoot);

    setStatus("Preparing print pages…", false);
    const chunks = chunkPlayers(currentPlayers, CARDS_PER_PAGE);
    for (let i = 0; i < chunks.length; i += 1) {
      printRoot.appendChild(await buildPageElement(chunks[i], overrides, "pc-print-page"));
    }
    await waitForExportImages(printRoot, 4000);

    const cleanup = function () {
      printRoot.remove();
      window.removeEventListener("afterprint", cleanup);
      setStatus("", false);
    };
    window.addEventListener("afterprint", cleanup);
    window.setTimeout(function () {
      window.print();
    }, 150);
  }

  function photoPlaceholderHtml(playerName) {
    return `<div class="pc-card__photo pc-card__photo--placeholder pc-card__photo--pasteable" data-player="${escapeAttr(playerName)}" tabindex="0" role="button" aria-label="Paste or upload headshot for ${escapeAttr(playerName)}"><span class="pc-card__photo-hint">Click · Cmd/Ctrl+V to paste</span></div>`;
  }

  function compressImageFile(file) {
    return new Promise(function (resolve, reject) {
      const objectUrl = URL.createObjectURL(file);
      const image = new Image();
      image.onload = function () {
        URL.revokeObjectURL(objectUrl);
        const scale = Math.min(
          PHOTO_MAX_WIDTH / image.naturalWidth,
          PHOTO_MAX_HEIGHT / image.naturalHeight,
          1
        );
        const width = Math.max(1, Math.round(image.naturalWidth * scale));
        const height = Math.max(1, Math.round(image.naturalHeight * scale));
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error("Canvas unavailable"));
          return;
        }
        ctx.fillStyle = "#f8fafc";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(image, 0, 0, width, height);
        resolve(canvas.toDataURL("image/jpeg", PHOTO_JPEG_QUALITY));
      };
      image.onerror = function () {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("Image load failed"));
      };
      image.src = objectUrl;
    });
  }

  function setPhotoPasteTarget(playerName, element) {
    pasteTargetPlayer = playerName || null;
    cardsBoard.querySelectorAll(".pc-card__photo--pasteable").forEach(function (node) {
      node.classList.toggle(
        "pc-card__photo--paste-active",
        playerName && node.getAttribute("data-player") === playerName
      );
    });
    if (element && typeof element.focus === "function") {
      element.focus({ preventScroll: true });
    }
  }

  function clearPhotoPasteTarget() {
    pasteTargetPlayer = null;
    cardsBoard.querySelectorAll(".pc-card__photo--pasteable").forEach(function (node) {
      node.classList.remove("pc-card__photo--paste-active");
    });
  }

  function applyPhotoPaste(playerName, file) {
    if (!playerName || !file) return;
    compressImageFile(file)
      .then(function (dataUrl) {
        const overrides = loadOverrides();
        overrides[playerName] = overrides[playerName] || {};
        overrides[playerName].photo = dataUrl;
        saveOverrides(overrides);
        clearPhotoPasteTarget();
        renderBoard();
        setStatus("Headshot pasted — saved for this club in your browser.", false);
      })
      .catch(function () {
        setStatus("Could not read that image.", true);
      });
  }

  function clipboardImageFile(clipboardData) {
    if (!clipboardData) return null;

    const items = clipboardData.items;
    if (items && items.length) {
      for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        const type = String(item.type || "");
        if (item.kind === "file" && type.indexOf("image/") === 0) {
          const file = item.getAsFile();
          if (file) return file;
        }
      }
      for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        const type = String(item.type || "");
        if (type.indexOf("image/") === 0) {
          const file = item.getAsFile();
          if (file) return file;
        }
      }
    }

    const files = clipboardData.files;
    if (files && files.length) {
      for (let index = 0; index < files.length; index += 1) {
        if (String(files[index].type || "").indexOf("image/") === 0) {
          return files[index];
        }
      }
    }
    return null;
  }

  async function readClipboardImageViaApi() {
    if (!navigator.clipboard || typeof navigator.clipboard.read !== "function") {
      return null;
    }
    try {
      const entries = await navigator.clipboard.read();
      for (let i = 0; i < entries.length; i += 1) {
        const entry = entries[i];
        const types = entry.types || [];
        for (let t = 0; t < types.length; t += 1) {
          if (String(types[t]).indexOf("image/") === 0) {
            const blob = await entry.getType(types[t]);
            if (blob) {
              return new File([blob], "pasted-headshot.png", {
                type: blob.type || "image/png",
              });
            }
          }
        }
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  function ensurePhotoFileInput() {
    let input = document.getElementById("pcPhotoFileInput");
    if (input) return input;
    input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.id = "pcPhotoFileInput";
    input.hidden = true;
    input.addEventListener("change", function () {
      const file = input.files && input.files[0];
      const playerName = input.dataset.player || pasteTargetPlayer;
      input.value = "";
      if (!file || !playerName) return;
      applyPhotoPaste(playerName, file);
    });
    document.body.appendChild(input);
    return input;
  }

  function openPhotoFilePicker(playerName) {
    const input = ensurePhotoFileInput();
    input.dataset.player = playerName || "";
    input.click();
  }

  function photoHtml(player, override) {
    const pasted = override && override.photo;
    if (pasted) {
      return `<img class="pc-card__photo" src="${escapeAttr(pasted)}" alt="${escapeAttr(player.name)}" data-player="${escapeAttr(player.name)}" />`;
    }

    const fallbacks = Array.isArray(player.photo_fallbacks)
      ? player.photo_fallbacks.filter(Boolean)
      : [];
    const primary = player.photo_url || player.fotmob_photo_url || fallbacks[0];
    if (!primary) {
      return photoPlaceholderHtml(player.name);
    }
    const dataFallbacks = fallbacks
      .filter(function (url) {
        return url && url !== primary;
      })
      .join("|");
    return `<img class="pc-card__photo" src="${escapeAttr(primary)}" alt="${escapeAttr(player.name)}" loading="lazy" referrerpolicy="no-referrer" data-player="${escapeAttr(player.name)}" data-fallbacks="${escapeAttr(dataFallbacks)}" onerror="window.pcPhotoFallback(this)" />`;
  }

  window.pcPhotoFallback = function (img) {
    const playerName = img.getAttribute("data-player") || img.alt || "";
    const raw = String(img.dataset.fallbacks || "");
    if (!raw) {
      img.replaceWith(
        (function () {
          const button = document.createElement("div");
          button.className =
            "pc-card__photo pc-card__photo--placeholder pc-card__photo--pasteable";
          button.setAttribute("data-player", playerName);
          button.tabIndex = 0;
          button.setAttribute("role", "button");
          button.setAttribute("aria-label", `Paste or upload headshot for ${playerName}`);
          const hint = document.createElement("span");
          hint.className = "pc-card__photo-hint";
          hint.textContent = "Click · Cmd/Ctrl+V to paste";
          button.appendChild(hint);
          bindPhotoPasteHandlers();
          return button;
        })()
      );
      return;
    }
    const parts = raw.split("|").filter(Boolean);
    if (!parts.length) {
      img.replaceWith(
        (function () {
          const button = document.createElement("div");
          button.className =
            "pc-card__photo pc-card__photo--placeholder pc-card__photo--pasteable";
          button.setAttribute("data-player", playerName);
          button.tabIndex = 0;
          button.setAttribute("role", "button");
          button.setAttribute("aria-label", `Paste or upload headshot for ${playerName}`);
          const hint = document.createElement("span");
          hint.className = "pc-card__photo-hint";
          hint.textContent = "Click · Cmd/Ctrl+V to paste";
          button.appendChild(hint);
          bindPhotoPasteHandlers();
          return button;
        })()
      );
      return;
    }
    const next = parts.shift();
    img.dataset.fallbacks = parts.join("|");
    img.src = next;
  };

  function renderCard(player, overrides, editMode) {
    const override = overrides[player.name] || {};
    const header = resolveHeader(player, override);
    const height = overrideOr(player, override, "height", "—");
    const age = overrideOr(player, override, "age", "—");
    const position = overrideOr(player, override, "position", "—");
    const foot = resolveFoot(player, override);
    const footCellClass = footClass(foot);
    const heightUnknown = unknownClassSuffix(height);
    const ageUnknown = unknownClassSuffix(age);
    const positionUnknown = unknownPositionClass(position);

    const headerCell = editMode
      ? `<input type="text" class="pc-card__header pc-card__header--edit" data-player="${escapeAttr(player.name)}" data-field="header" value="${escapeAttr(header)}" aria-label="Name and number" />`
      : `<button type="button" class="pc-card__header pc-card__header--clickable" data-player="${escapeAttr(player.name)}" data-field="header" aria-label="Edit name and number">${escapeHtml(header)}</button>`;

    const heightCell = editMode
      ? `<input type="text" class="pc-card__stat pc-card__stat--height pc-card__stat--edit${heightUnknown}" data-player="${escapeAttr(player.name)}" data-field="height" value="${escapeAttr(height)}" aria-label="Height" />`
      : `<button type="button" class="pc-card__stat pc-card__stat--height pc-card__stat--clickable${heightUnknown}" data-player="${escapeAttr(player.name)}" data-field="height" aria-label="Edit height">${escapeHtml(height)}</button>`;

    const ageCell = editMode
      ? `<input type="text" class="pc-card__stat pc-card__stat--age pc-card__stat--edit${ageUnknown}" data-player="${escapeAttr(player.name)}" data-field="age" value="${escapeAttr(age)}" aria-label="Age" />`
      : `<button type="button" class="pc-card__stat pc-card__stat--age pc-card__stat--clickable${ageUnknown}" data-player="${escapeAttr(player.name)}" data-field="age" aria-label="Edit age">${escapeHtml(age)}</button>`;

    const footCell = `<button type="button" class="${footCellClass} pc-card__stat--foot-toggle" data-player="${escapeAttr(player.name)}" data-foot="${escapeAttr(foot)}" aria-label="Foot ${escapeAttr(foot)}. Click to change.">${escapeHtml(foot)}</button>`;

    const positionCell = editMode
      ? `<input type="text" class="pc-card__position pc-card__position--edit${positionUnknown}" data-player="${escapeAttr(player.name)}" data-field="position" value="${escapeAttr(position)}" aria-label="Position" />`
      : `<button type="button" class="pc-card__position pc-card__position--clickable${positionUnknown}" data-player="${escapeAttr(player.name)}" data-field="position" aria-label="Edit position">${escapeHtml(position)}</button>`;

    return `
      <article class="pc-card" data-player="${escapeAttr(player.name)}">
        ${headerCell}
        <div class="pc-card__photo-wrap">${photoHtml(player, override)}</div>
        <div class="pc-card__footer">
          <div class="pc-card__stats-row">
            ${heightCell}
            ${ageCell}
            ${footCell}
          </div>
          ${positionCell}
        </div>
      </article>
    `;
  }

  function focusPlayerField(playerName, field) {
    if (!playerName || !field) return;
    const selector = `[data-player="${CSS.escape(playerName)}"][data-field="${field}"].pc-card__stat--edit, [data-player="${CSS.escape(playerName)}"][data-field="${field}"].pc-card__header--edit, [data-player="${CSS.escape(playerName)}"][data-field="${field}"].pc-card__position--edit`;
    const input = cardsBoard.querySelector(selector);
    if (input) {
      input.focus();
      if (typeof input.select === "function") {
        input.select();
      }
    }
  }

  function bindPhotoPasteHandlers() {
    cardsBoard.querySelectorAll(".pc-card__photo--pasteable").forEach(function (slot) {
      if (slot.dataset.pasteBound === "1") return;
      slot.dataset.pasteBound = "1";

      slot.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        const playerName = slot.getAttribute("data-player");
        if (!playerName) return;
        setPhotoPasteTarget(playerName, slot);
        setStatus("Selected — press Cmd+V / Ctrl+V to paste, or click again to upload a file.", false);
      });

      slot.addEventListener("dblclick", function (event) {
        event.preventDefault();
        event.stopPropagation();
        const playerName = slot.getAttribute("data-player");
        if (!playerName) return;
        setPhotoPasteTarget(playerName, slot);
        openPhotoFilePicker(playerName);
      });

      slot.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        const playerName = slot.getAttribute("data-player");
        if (!playerName) return;
        setPhotoPasteTarget(playerName, slot);
        openPhotoFilePicker(playerName);
      });
    });
  }

  function bindEditHandlers() {
    cardsBoard
      .querySelectorAll(".pc-card__stat--edit, .pc-card__header--edit, .pc-card__position--edit")
      .forEach(function (input) {
        input.addEventListener("input", function () {
          const playerName = input.getAttribute("data-player");
          const field = input.getAttribute("data-field");
          if (!playerName || !field) return;

          const overrides = loadOverrides();
          overrides[playerName] = overrides[playerName] || {};
          overrides[playerName][field] = input.value;
          saveOverrides(overrides);
          if (field === "height" || field === "age" || field === "position") {
            applyUnknownClass(input, input.value, field);
          }
        });
      });

    cardsBoard
      .querySelectorAll(".pc-card__stat--clickable, .pc-card__header--clickable, .pc-card__position--clickable")
      .forEach(function (button) {
        button.addEventListener("click", function () {
          const playerName = button.getAttribute("data-player");
          const field = button.getAttribute("data-field");
          if (!playerName || !field) return;
          setToggleUi(editCardsToggle, true);
          renderBoard();
          focusPlayerField(playerName, field);
        });
      });

    cardsBoard.querySelectorAll(".pc-card__stat--foot-toggle").forEach(function (button) {
      button.addEventListener("click", function () {
        const playerName = button.getAttribute("data-player");
        if (!playerName) return;
        const currentFoot = button.getAttribute("data-foot") || "?";
        const updatedFoot = nextFoot(currentFoot);

        const overrides = loadOverrides();
        overrides[playerName] = overrides[playerName] || {};
        overrides[playerName].foot = updatedFoot;
        saveOverrides(overrides);

        button.setAttribute("data-foot", updatedFoot);
        button.textContent = updatedFoot;
        button.setAttribute("aria-label", `Foot ${updatedFoot}. Click to change.`);
        button.classList.remove("pc-card__stat--left", "pc-card__stat--unknown");
        if (isLeftFoot(updatedFoot)) {
          button.classList.add("pc-card__stat--left");
        } else if (isUnknownFoot(updatedFoot)) {
          button.classList.add("pc-card__stat--unknown");
        }
      });
    });
  }

  function renderBoard() {
    if (!currentPlayers.length) {
      cardsBoard.innerHTML = `<div class="pc-empty">No players loaded for this club.</div>`;
      return;
    }
    const overrides = loadOverrides();
    const editMode = editCardsEnabled();
    document.body.classList.toggle("pc-edit-cards", editMode);
    cardsBoard.innerHTML = currentPlayers
      .map(function (player) {
        return renderCard(player, overrides, editMode);
      })
      .join("");
    bindEditHandlers();
    bindPhotoPasteHandlers();
  }

  function currentLeague() {
    const value = leagueSelect && leagueSelect.value ? leagueSelect.value : DEFAULT_LEAGUE;
    return LEAGUES.indexOf(value) >= 0 ? value : DEFAULT_LEAGUE;
  }

  function updateClubMeta(opponent, payload) {
    const parts = [];
    parts.push(`${currentLeague()} · ${SEASON}`);
    if (payload && payload.player_count != null) {
      parts.push(`${payload.player_count} players`);
    }
    if (payload && payload.club_site_available && payload.club_site_url) {
      parts.push(`<a href="${escapeHtml(payload.club_site_url)}" target="_blank" rel="noopener">Club website roster</a>`);
    } else {
      parts.push("FotMob roster + headshots");
    }
    if (payload && payload.iteration_id) {
      parts.push(`Impect ${payload.iteration_id}`);
    }
    clubMeta.innerHTML = parts.join(" · ");
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return response.json();
  }

  function populateLeagues(leagues, selected) {
    if (!leagueSelect) return;
    const list = leagues && leagues.length ? leagues : LEAGUES;
    const current = selected || currentLeague();
    leagueSelect.innerHTML = list
      .map(function (name) {
        const selectedAttr = name === current ? " selected" : "";
        return `<option value="${escapeHtml(name)}"${selectedAttr}>${escapeHtml(name)}</option>`;
      })
      .join("");
  }

  function populateClubs(opponents, preferredClub) {
    const list = opponents || meta.opponents || meta.clubs || [];
    const names = list.map(function (club) {
      return club.name;
    });
    let defaultClub = preferredClub || meta.default_club || meta.upcoming_opponent || null;
    if (!defaultClub || names.indexOf(defaultClub) < 0) {
      defaultClub = names[0] || "";
    }
    clubSelect.innerHTML = list
      .map(function (club) {
        const selected = club.name === defaultClub ? " selected" : "";
        return `<option value="${escapeHtml(club.name)}"${selected}>${escapeHtml(club.name)}</option>`;
      })
      .join("");
    if (defaultClub) {
      clubSelect.value = defaultClub;
    }
  }

  async function loadMeta(preferredClub) {
    const league = currentLeague();
    meta = await fetchJson(
      `/api/player-cards/meta?season=${encodeURIComponent(SEASON)}&league=${encodeURIComponent(league)}`
    );
    populateLeagues(meta.leagues || LEAGUES, meta.league || league);
    populateClubs(meta.opponents || meta.clubs, preferredClub);
  }

  async function loadSquad(options) {
    const opts = options || {};
    const force = !!opts.force;
    if (loading && !force) return;

    const token = ++loadToken;
    loading = true;
    setStatus("Loading squad cards…", false);
    refreshBtn.disabled = true;

    const league = currentLeague();
    const clubs = meta && (meta.opponents || meta.clubs) ? meta.opponents || meta.clubs : [];
    let club = clubSelect.value;
    const inList = clubs.some(function (row) {
      return row.name === club;
    });
    if (!club || !inList) {
      club = clubs[0] ? clubs[0].name : "";
      if (club) clubSelect.value = club;
    }

    const opponent = clubs.find(function (row) {
      return row.name === club;
    });

    if (!club) {
      currentPlayers = [];
      renderBoard();
      updateClubMeta(null, null);
      setStatus("No clubs found for this league.", true);
      loading = false;
      refreshBtn.disabled = false;
      return;
    }

    try {
      const params = new URLSearchParams({
        club: club,
        season: SEASON,
        league: league,
      });
      if (opponent && opponent.squad_id) params.set("squadId", String(opponent.squad_id));
      if (opponent && opponent.iteration_id) params.set("iterationId", String(opponent.iteration_id));
      if (opponent && opponent.fotmob_id) params.set("fotmobId", String(opponent.fotmob_id));
      const payload = await fetchJson(`/api/player-cards/squad?${params.toString()}`);
      if (token !== loadToken) return;
      currentPlayers = payload.players || [];
      renderBoard();
      updateClubMeta(opponent, payload);
      setStatus(
        payload.building
          ? "No saved squad cards yet — Refresh pulls them when the data is ready."
          : "",
        Boolean(payload.building),
      );
    } catch (error) {
      if (token !== loadToken) return;
      currentPlayers = [];
      renderBoard();
      updateClubMeta(opponent, null);
      setStatus(error.message || "Could not load squad.", true);
    } finally {
      if (token === loadToken) {
        loading = false;
        refreshBtn.disabled = false;
      }
    }
  }

  async function onLeagueChange() {
    currentPlayers = [];
    renderBoard();
    clubSelect.innerHTML = "";
    setStatus("Loading clubs…", false);
    try {
      await loadMeta();
      await loadSquad({ force: true });
    } catch (error) {
      setStatus(error.message || "Could not load league.", true);
      loading = false;
      refreshBtn.disabled = false;
    }
  }

  function onEditToggleChange() {
    setToggleUi(editCardsToggle, editCardsToggle && editCardsToggle.checked);
    renderBoard();
  }

  if (editCardsToggle) {
    editCardsToggle.addEventListener("change", onEditToggleChange);
  }

  if (leagueSelect) {
    leagueSelect.addEventListener("change", onLeagueChange);
  }
  clubSelect.addEventListener("change", function () {
    loadSquad({ force: true });
  });
  refreshBtn.addEventListener("click", async function () {
    refreshBtn.disabled = true;
    setStatus("Pulling latest match data in the background…", false);
    try {
      const startedRefresh = await fetch("/api/hub-snapshots/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "analysis" }),
      });
      if (!startedRefresh.ok) {
        throw new Error("Could not start refresh.");
      }
      const started = Date.now();
      const poll = async () => {
        try {
          const status = await fetchJson("/api/hub-snapshots/status");
          if (status.refreshing || status.last_refresh_status === "running") {
            if (Date.now() - started < 180000) {
              window.setTimeout(poll, 2500);
              return;
            }
          }
          await loadSquad({ force: true });
        } catch (error) {
          setStatus(error.message || "Refresh failed", true);
        } finally {
          refreshBtn.disabled = false;
        }
      };
      window.setTimeout(poll, 800);
    } catch (error) {
      setStatus(error.message || "Could not start refresh.", true);
      refreshBtn.disabled = false;
    }
  });
  if (exportPdfBtn) {
    exportPdfBtn.addEventListener("click", exportPdf);
  }
  if (printBtn) {
    printBtn.addEventListener("click", printLandscape);
  }

  document.addEventListener(
    "paste",
    function (event) {
      if (!pasteTargetPlayer) return;
      const file = clipboardImageFile(event.clipboardData);
      if (file) {
        event.preventDefault();
        event.stopPropagation();
        applyPhotoPaste(pasteTargetPlayer, file);
        return;
      }
      // Keep target selected; async clipboard API may still recover the image.
      event.preventDefault();
      readClipboardImageViaApi().then(function (apiFile) {
        if (apiFile) {
          applyPhotoPaste(pasteTargetPlayer, apiFile);
          return;
        }
        setStatus("Clipboard does not contain an image — copy a screenshot/photo first, then Cmd+V.", true);
      });
    },
    true
  );

  document.addEventListener("keydown", function (event) {
    const isPaste = (event.metaKey || event.ctrlKey) && String(event.key || "").toLowerCase() === "v";
    if (!isPaste || !pasteTargetPlayer) return;
    // Some Mac setups only expose the image via clipboard.read()
    window.setTimeout(function () {
      if (!pasteTargetPlayer) return;
      readClipboardImageViaApi().then(function (apiFile) {
        if (apiFile) applyPhotoPaste(pasteTargetPlayer, apiFile);
      });
    }, 0);
  });

  document.addEventListener("click", function (event) {
    if (!pasteTargetPlayer) return;
    if (event.target.closest(".pc-card__photo--pasteable")) return;
    if (event.target.closest("#pcPhotoFileInput")) return;
    clearPhotoPasteTarget();
  });

  loadMeta()
    .then(loadSquad)
    .catch(function (error) {
      setStatus(error.message || "Could not load app.", true);
    });
})();
