(function () {
  "use strict";

  const clubSearch = document.getElementById("clubSearch");
  const searchResults = document.getElementById("searchResults");
  const meetingTitle = document.getElementById("meetingTitle");
  const statusBanner = document.getElementById("statusBanner");
  const workspace = document.getElementById("workspace");
  const editor = document.getElementById("editor");
  const preview = document.getElementById("preview");
  const downloadBtn = document.getElementById("downloadBtn");
  const saveBtn = document.getElementById("saveBtn");
  const valePhotosBtn = document.getElementById("valePhotosBtn");
  const oppPhotosBtn = document.getElementById("oppPhotosBtn");
  const cutoutInput = document.getElementById("cutoutInput");
  const clearCutoutBtn = document.getElementById("clearCutoutBtn");
  const cutoutFileName = document.getElementById("cutoutFileName");
  const photoPanel = document.getElementById("photoPanel");
  const photoGrid = document.getElementById("photoGrid");
  const photoMeta = document.getElementById("photoMeta");
  const photoQuery = document.getElementById("photoQuery");
  const photoQueryBtn = document.getElementById("photoQueryBtn");
  const packPills = document.getElementById("packPills");
  const clubChips = document.getElementById("clubChips");

  const SLIDE_W = 1920;
  const SLIDE_H = 1080;
  const VALE_BADGE = "/standalone/port-vale-badge.png?v=2";

  let searchTimer = null;
  let searchAbort = null;
  let searchSeq = 0;
  let meta = null;
  let packs = [];
  let packId = "set-plays";
  let opponent = null;
  let slides = [];
  let webPhotos = [];
  let slidePhotos = {};
  let activeSlideId = "cover";
  let leagueTwoClubs = [];
  const failedPhotoIds = new Set();

  function setStatus(message, isError) {
    if (!message) {
      statusBanner.classList.add("hidden");
      statusBanner.classList.remove("is-error", "is-ok");
      statusBanner.textContent = "";
      return;
    }
    statusBanner.classList.remove("hidden", "is-error", "is-ok");
    statusBanner.classList.add(isError ? "is-error" : "is-ok");
    statusBanner.textContent = message;
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

  function slugify(value) {
    return String(value || "slide")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "slide";
  }

  function currentPack() {
    return packs.find((p) => p.id === packId) || packs[0] || { topics: [], extraTopics: [], label: "Set Plays" };
  }

  function selectedSlides() {
    return slides.filter((s) => s.selected !== false);
  }

  function slideById(id) {
    return slides.find((s) => s.id === id) || null;
  }

  function badgeSrc(club) {
    if (!club) return "";
    return club.badgeProxyUrl || club.badgeUrl || "";
  }

  function ensureSlidePhoto(id) {
    if (!slidePhotos[id]) slidePhotos[id] = { photoId: null, cutout: null };
    return slidePhotos[id];
  }

  function webPhotoById(id) {
    return webPhotos.find((p) => p.id === id) || null;
  }

  function photoSrc(slideId) {
    const slot = ensureSlidePhoto(slideId || activeSlideId);
    if (slot.cutout) return slot.cutout;
    const web = webPhotoById(slot.photoId);
    if (web) return web.proxyUrl || web.url;
    return "";
  }

  function assignPhotoToActive(photoId) {
    const slot = ensureSlidePhoto(activeSlideId);
    slot.photoId = photoId;
    slot.cutout = null;
    clearCutoutBtn.disabled = !Object.values(slidePhotos).some((s) => s.cutout);
  }

  function buildDefaultSlides(title, extraTopics) {
    const pack = currentPack();
    const heading = title || pack.label || "Set Plays";
    const next = [
      {
        id: "cover",
        kind: "cover",
        title: heading,
        subtitle: opponent ? opponent.name : "",
        selected: true,
      },
    ];
    const topics = (pack.topics || []).concat(extraTopics || []);
    topics.forEach((topic, index) => {
      const existing = slides.find((s) => s.kind === "topic" && s.title === topic);
      next.push({
        id: existing && existing.id ? existing.id : `topic-${index + 1}`,
        kind: "topic",
        title: topic,
        subtitle: heading,
        selected: existing ? existing.selected !== false : true,
      });
    });
    slides.filter((s) => s.kind === "topic" && s.custom).forEach((s) => {
      if (!next.some((row) => row.title === s.title)) next.push(s);
    });
    slides = next;
    if (!slideById(activeSlideId)) activeSlideId = "cover";
  }

  function setButtons() {
    const ready = Boolean(opponent);
    downloadBtn.disabled = !ready || !selectedSlides().length;
    saveBtn.disabled = !ready;
    oppPhotosBtn.disabled = !ready;
    valePhotosBtn.disabled = false;
  }

  function renderPacks() {
    packPills.innerHTML = packs.map((pack) => `
      <button type="button" class="pams-pill ${pack.id === packId ? "is-active" : ""}" data-pack="${escapeAttr(pack.id)}">
        ${escapeHtml(pack.label)}
      </button>`).join("");
  }

  function renderClubChips() {
    if (!leagueTwoClubs.length) {
      clubChips.innerHTML = "";
      return;
    }
    const featured = leagueTwoClubs.slice();
    featured.sort((a, b) => {
      const aEx = /exeter/i.test(a.name) ? 0 : 1;
      const bEx = /exeter/i.test(b.name) ? 0 : 1;
      if (aEx !== bEx) return aEx - bEx;
      return String(a.name).localeCompare(String(b.name));
    });
    clubChips.innerHTML = `<div class="pams-club-row">${featured.slice(0, 24).map((club) => `
      <button type="button" class="pams-club-chip ${opponent && opponent.id === club.id ? "is-active" : ""}" data-club-id="${escapeAttr(club.id)}">
        ${club.badgeProxyUrl || club.badgeUrl ? `<img src="${escapeAttr(club.badgeProxyUrl || club.badgeUrl)}" alt="" />` : ""}
        ${escapeHtml(club.name)}
      </button>`).join("")}</div>`;
  }

  function renderEditor() {
    if (!opponent) {
      editor.innerHTML = `<p class="pams-hint">Pick Exeter (or any club) to build the meeting pack.</p>`;
      return;
    }
    const pack = currentPack();
    const extras = (pack.extraTopics || []).filter((title) => !slides.some((s) => s.title === title));
    const vale = (meta && meta.portVale) || { name: "Port Vale", badgeUrl: VALE_BADGE };
    editor.innerHTML = `
      <h2>Slides</h2>
      <div class="pams-matchup">
        <div>
          <img src="${escapeAttr(vale.badgeUrl || VALE_BADGE)}" alt="Port Vale" />
          <span class="pams-matchup__name">Port Vale</span>
        </div>
        <span class="pams-matchup__vs">VS</span>
        <div>
          <img src="${escapeAttr(badgeSrc(opponent))}" alt="${escapeAttr(opponent.name)}" />
          <span class="pams-matchup__name">${escapeHtml(opponent.name)}</span>
        </div>
      </div>
      <div class="pams-topic-list">
        ${slides.map((slide) => `
          <label class="pams-topic-edit">
            <input type="checkbox" data-toggle="${escapeAttr(slide.id)}" ${slide.selected !== false ? "checked" : ""} />
            <input type="text" data-title="${escapeAttr(slide.id)}" value="${escapeAttr(slide.title)}" />
            ${slide.id === "cover" ? "" : `<button type="button" class="pams-btn pams-btn--ghost pams-btn--small" data-remove="${escapeAttr(slide.id)}">Remove</button>`}
          </label>`).join("")}
      </div>
      <div class="pams-add-row">
        <input id="customTopic" class="pams-input" type="text" placeholder="Add a topic — e.g. Long Throws" />
        <button type="button" class="pams-btn pams-btn--ghost" id="addTopicBtn">Add</button>
      </div>
      ${extras.length ? `<p class="pams-label" style="margin-top:14px">Quick add</p><div class="pams-extras">${extras.map((title) => `<button type="button" data-extra="${escapeAttr(title)}">+ ${escapeHtml(title)}</button>`).join("")}</div>` : ""}
    `;
  }

  function photoHtml(slideId) {
    const src = photoSrc(slideId);
    if (!src) {
      return `<div class="pams-slide__photo"><div class="pams-slide__photo-empty">No photo — click a picture below</div></div>`;
    }
    return `<div class="pams-slide__photo"><img src="${escapeAttr(src)}" alt="" crossorigin="anonymous" data-photo-id="${escapeAttr((slidePhotos[slideId] || {}).photoId || "")}" /></div>`;
  }

  function badgesHtml() {
    const vale = (meta && meta.portVale) || { name: "Port Vale", badgeUrl: VALE_BADGE };
    const opp = opponent || { name: "Opponent", badgeUrl: "" };
    return `<div class="pams-slide__badges">
      <div class="pams-slide__club">
        <img class="pams-slide__crest" src="${escapeAttr(vale.badgeUrl || VALE_BADGE)}" alt="Port Vale" />
        <span>Port Vale</span>
      </div>
      <div class="pams-slide__vs">VS</div>
      <div class="pams-slide__club">
        ${opp.badgeProxyUrl || opp.badgeUrl ? `<img class="pams-slide__crest" src="${escapeAttr(badgeSrc(opp))}" alt="${escapeAttr(opp.name)}" />` : ""}
        <span>${escapeHtml(opp.name)}</span>
      </div>
    </div>`;
  }

  function slideHtml(slide) {
    const packLabel = meetingTitle.value.trim() || currentPack().label || "Set Plays";
    const kicker = slide.kind === "cover" ? "Performance analysis" : packLabel;
    const sub = slide.kind === "cover" && opponent ? opponent.name : "";
    const active = slide.id === activeSlideId ? " is-active-target" : "";
    return `<div class="pams-slide pams-slide--${escapeAttr(slide.kind)}${active}" data-slide="${escapeAttr(slide.id)}">
      ${photoHtml(slide.id)}
      <div class="pams-slide__veil" aria-hidden="true"></div>
      <div class="pams-slide__stage">
        ${badgesHtml()}
        <div class="pams-slide__copy">
          <p class="pams-slide__kicker">${escapeHtml(kicker)}</p>
          <h2 class="pams-slide__title">${escapeHtml(slide.title)}</h2>
          ${sub ? `<p class="pams-slide__sub">${escapeHtml(sub)}</p>` : ""}
        </div>
      </div>
    </div>`;
  }

  function scaleSlides() {
    preview.querySelectorAll(".pams-slide-wrap").forEach((wrap) => {
      const slide = wrap.querySelector(".pams-slide");
      if (!slide) return;
      const width = wrap.getBoundingClientRect().width || wrap.clientWidth || 960;
      const scale = Math.min(1, width / SLIDE_W);
      wrap.style.overflow = "hidden";
      wrap.style.height = `${SLIDE_H * scale}px`;
      slide.style.transformOrigin = "top left";
      slide.style.transform = `scale(${scale})`;
    });
  }

  function renderPreview() {
    if (!opponent) return;
    const parts = selectedSlides().map((slide, index) => `
      <div class="pams-slide-wrap">
        <p class="pams-slide-caption">${String(index + 1).padStart(2, "0")} · ${escapeHtml(slide.title)}</p>
        ${slideHtml(slide)}
      </div>`);
    preview.innerHTML = parts.join("");
    scaleSlides();
    requestAnimationFrame(() => {
      scaleSlides();
      requestAnimationFrame(scaleSlides);
    });
  }

  function renderPhotoGrid() {
    if (!webPhotos.length) {
      photoPanel.hidden = true;
      photoGrid.innerHTML = "";
      return;
    }
    photoPanel.hidden = false;
    const activeId = (slidePhotos[activeSlideId] || {}).photoId;
    const targets = selectedSlides().map((slide) => `
      <button type="button" class="pams-slide-target ${slide.id === activeSlideId ? "is-active" : ""}" data-slide-target="${escapeAttr(slide.id)}">
        ${escapeHtml(slide.title)}
      </button>`).join("");
    photoMeta.textContent = `${webPhotos.length} photos · slides start blank — click a slide, then a picture`;
    photoGrid.innerHTML = `
      <div class="pams-slide-targets">${targets}</div>
      <p class="pams-hint">Assigning to <strong>${escapeHtml((slideById(activeSlideId) || {}).title || "Cover")}</strong></p>
      <div class="pams-photo-grid__cards">
        ${webPhotos.map((photo) => {
          const usedOn = selectedSlides().filter((s) => (slidePhotos[s.id] || {}).photoId === photo.id);
          const usedTag = usedOn.length ? usedOn.map((s) => s.title).join(", ") : "";
          return `<button type="button" class="pams-photo-card ${photo.id === activeId ? "is-selected" : ""}" data-photo-id="${escapeAttr(photo.id)}" title="${escapeAttr(photo.label || "")}">
            <img src="${escapeAttr(photo.proxyUrl || photo.url)}" alt="" loading="lazy" />
            ${usedTag ? `<span class="pams-photo-card__used">${escapeHtml(usedTag)}</span>` : ""}
          </button>`;
        }).join("")}
      </div>`;
  }

  function renderAll() {
    renderPacks();
    renderClubChips();
    renderEditor();
    renderPreview();
    renderPhotoGrid();
    setButtons();
    workspace.hidden = !opponent;
  }

  async function searchClubs(query) {
    const q = String(query || "").trim();
    if (q.length < 2) {
      if (searchAbort) searchAbort.abort();
      searchResults.hidden = true;
      searchResults.innerHTML = "";
      return;
    }
    const seq = ++searchSeq;
    if (searchAbort) searchAbort.abort();
    searchAbort = new AbortController();
    try {
      const res = await fetch(`/api/pa-meeting-slides/clubs?q=${encodeURIComponent(q)}`, {
        signal: searchAbort.signal,
      });
      if (!res.ok) throw new Error("Club search failed");
      const data = await res.json();
      if (seq !== searchSeq) return;
      const clubs = data.clubs || [];
      if (!clubs.length) {
        searchResults.innerHTML = `<li><div class="pams-results__empty">No clubs match that name.</div></li>`;
        searchResults.hidden = false;
        return;
      }
      searchResults.innerHTML = clubs.slice(0, 14).map((club) => `
        <li><button type="button" data-club-id="${escapeAttr(club.id)}">
          ${club.badgeProxyUrl || club.badgeUrl ? `<img src="${escapeAttr(club.badgeProxyUrl || club.badgeUrl)}" alt="" />` : ""}
          <span>${escapeHtml(club.name)}<span class="pams-results__meta">${escapeHtml(club.league || "")}</span></span>
        </button></li>`).join("");
      searchResults.hidden = false;
    } catch (err) {
      if (err && err.name === "AbortError") return;
      searchResults.innerHTML = `<li><div class="pams-results__empty">${escapeHtml(err.message || "Search unavailable")}</div></li>`;
      searchResults.hidden = false;
    }
  }

  async function selectClub(club) {
    opponent = club;
    clubSearch.value = club.name;
    searchResults.hidden = true;
    const title = meetingTitle.value.trim() || currentPack().label || "Set Plays";
    buildDefaultSlides(title);
    slidePhotos = {};
    activeSlideId = "cover";
    renderAll();
    if (webPhotos.length) {
      setStatus(`${club.name} loaded — slides are blank. Click a slide, then a picture.`);
      return;
    }
    await loadPhotos("Port Vale", "", { refresh: false });
  }

  async function selectClubById(id) {
    const fromChips = leagueTwoClubs.find((c) => c.id === id);
    if (fromChips) {
      await selectClub(fromChips);
      return;
    }
    const res = await fetch(`/api/pa-meeting-slides/clubs?q=${encodeURIComponent(id)}`);
    const data = await res.json();
    const club = (data.clubs || []).find((c) => c.id === id) || (data.clubs || [])[0];
    if (club) await selectClub(club);
  }

  async function loadPhotos(clubName, query, options) {
    const club = clubName || "Port Vale";
    const refresh = options && options.refresh === false ? "0" : "1";
    setStatus(`Finding 26/27 match photos for ${club}…`);
    valePhotosBtn.disabled = true;
    oppPhotosBtn.disabled = true;
    try {
      const params = new URLSearchParams({ club, refresh });
      if (query) params.set("q", query);
      const res = await fetch(`/api/pa-meeting-slides/photos?${params.toString()}`);
      if (!res.ok) throw new Error("Photo search failed");
      const data = await res.json();
      webPhotos = Array.isArray(data.photos) ? data.photos : [];
      renderPhotoGrid();
      renderPreview();
      setStatus(
        webPhotos.length
          ? `Found ${webPhotos.length} 26/27 match photos — slides stay blank until you pick one.`
          : "No 26/27 match photos found — try Refresh 26/27 match photos or upload your own."
      );
    } catch (err) {
      setStatus(err.message || "Photo search failed", true);
    } finally {
      setButtons();
    }
  }

  async function saveDeck() {
    if (!opponent) return;
    const id = `${slugify(opponent.name)}-${slugify(meetingTitle.value || packId)}`;
    saveBtn.disabled = true;
    try {
      const res = await fetch(`/api/pa-meeting-slides/decks/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: meetingTitle.value.trim(),
          packId,
          opponent,
          slides,
          photoAssignments: slidePhotos,
        }),
      });
      if (!res.ok) throw new Error("Could not save deck");
      setStatus("Deck saved.");
    } catch (err) {
      setStatus(err.message || "Save failed", true);
    } finally {
      setButtons();
    }
  }

  function waitForImages(root, timeoutMs) {
    const images = [...(root.querySelectorAll("img") || [])];
    if (!images.length) return Promise.resolve();
    return Promise.all(
      images.map(
        (image) =>
          new Promise((resolve) => {
            if (image.complete && image.naturalWidth > 0) {
              resolve();
              return;
            }
            const timer = window.setTimeout(resolve, timeoutMs || 6000);
            const done = () => {
              window.clearTimeout(timer);
              resolve();
            };
            image.addEventListener("load", done, { once: true });
            image.addEventListener("error", done, { once: true });
          })
      )
    );
  }

  async function captureSlideHtml2Canvas(slideEl) {
    const cloneHost = document.createElement("div");
    cloneHost.style.cssText = "position:fixed;left:-10000px;top:0;width:1920px;height:1080px;z-index:-1;";
    const clone = slideEl.cloneNode(true);
    clone.style.transform = "none";
    clone.style.width = `${SLIDE_W}px`;
    clone.style.height = `${SLIDE_H}px`;
    cloneHost.appendChild(clone);
    document.body.appendChild(cloneHost);
    await waitForImages(clone);
    try {
      const canvas = await html2canvas(clone, {
        width: SLIDE_W,
        height: SLIDE_H,
        scale: 2,
        backgroundColor: "#12100e",
        useCORS: true,
        allowTaint: false,
        logging: false,
      });
      return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    } finally {
      cloneHost.remove();
    }
  }

  async function downloadPack() {
    downloadBtn.disabled = true;
    setStatus("Rendering PNG pack…");
    try {
      const slideEls = Array.from(preview.querySelectorAll(".pams-slide"));
      if (!slideEls.length) throw new Error("No slides to export");
      const folder = slugify(`${opponent.name}-${meetingTitle.value || packId}`);
      const filenames = slideEls.map((slide, i) => {
        const key = slide.getAttribute("data-slide") || `slide-${i + 1}`;
        const title = (slideById(key) || {}).title || key;
        return `${String(i + 1).padStart(2, "0")}-${slugify(title)}`;
      });

      if (window.PortValeWysiwygExport && typeof window.PortValeWysiwygExport.captureSlideHtmlPages === "function") {
        const packHtml = await window.PortValeWysiwygExport.captureSlideHtmlPages({
          slides: slideEls,
          forceNativeSize: true,
          nativeWidth: SLIDE_W,
          nativeHeight: SLIDE_H,
          background: "#12100e",
          stripClasses: ["is-active-target"],
          onProgress: (msg) => setStatus(msg),
        });
        packHtml.htmlFilenames = filenames;
        const result = await window.PortValeWysiwygExport.downloadPngZip({
          ...packHtml,
          filename: `${folder}-pa-meeting-slides.zip`,
          documentTitle: folder,
          opponentName: opponent.name,
          endpoint: "/api/wysiwyg-export-png-zip",
        });
        setStatus(
          result.savedPath
            ? `Downloaded ${result.pageCount} sharp PNGs · ${result.sizeMb} MB · also on Desktop`
            : `Downloaded ${result.pageCount} sharp PNGs · ${result.sizeMb} MB`
        );
        return;
      }

      if (typeof html2canvas !== "function" || typeof JSZip !== "function") {
        throw new Error("Export libraries failed to load — hard refresh and try again.");
      }
      setStatus("Chrome export unavailable — using browser fallback…");
      const zip = new JSZip();
      for (let i = 0; i < slideEls.length; i += 1) {
        const blob = await captureSlideHtml2Canvas(slideEls[i]);
        if (!blob) throw new Error("Capture failed — try a different photo");
        zip.file(`${folder}/${filenames[i]}.png`, blob);
        setStatus(`Rendering PNG pack… ${i + 1}/${slideEls.length}`);
      }
      const out = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(out);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${folder}-pa-meeting-slides.zip`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus(`Downloaded ${slideEls.length} PNGs`);
    } catch (err) {
      setStatus(err.message || "Download failed", true);
    } finally {
      setButtons();
    }
  }

  clubSearch.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => searchClubs(clubSearch.value), 180);
  });

  searchResults.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-club-id]");
    if (!btn) return;
    selectClubById(btn.getAttribute("data-club-id"));
  });

  clubChips.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-club-id]");
    if (!btn) return;
    selectClubById(btn.getAttribute("data-club-id"));
  });

  packPills.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-pack]");
    if (!btn) return;
    packId = btn.getAttribute("data-pack");
    const pack = currentPack();
    if (!meetingTitle.dataset.userEdited) meetingTitle.value = pack.label || "Set Plays";
    buildDefaultSlides(meetingTitle.value);
    renderAll();
  });

  meetingTitle.addEventListener("input", () => {
    meetingTitle.dataset.userEdited = "1";
    const cover = slideById("cover");
    if (cover) cover.title = meetingTitle.value.trim() || currentPack().label;
    slides.forEach((slide) => {
      if (slide.kind === "topic") slide.subtitle = meetingTitle.value;
    });
    renderPreview();
    renderEditor();
  });

  editor.addEventListener("change", (event) => {
    const toggle = event.target.getAttribute("data-toggle");
    if (toggle) {
      const slide = slideById(toggle);
      if (slide) slide.selected = event.target.checked;
      renderPreview();
      renderPhotoGrid();
      setButtons();
    }
  });

  editor.addEventListener("input", (event) => {
    const id = event.target.getAttribute("data-title");
    if (!id) return;
    const slide = slideById(id);
    if (!slide) return;
    slide.title = event.target.value;
    if (id === "cover") {
      meetingTitle.value = event.target.value;
      meetingTitle.dataset.userEdited = "1";
    }
    renderPreview();
    renderPhotoGrid();
  });

  editor.addEventListener("click", (event) => {
    const extra = event.target.getAttribute("data-extra");
    if (extra) {
      slides.push({
        id: `topic-${Date.now()}`,
        kind: "topic",
        title: extra,
        subtitle: meetingTitle.value,
        selected: true,
        custom: true,
      });
      renderAll();
      return;
    }
    const remove = event.target.getAttribute("data-remove");
    if (remove) {
      slides = slides.filter((s) => s.id !== remove);
      if (activeSlideId === remove) activeSlideId = "cover";
      renderAll();
      return;
    }
    if (event.target.id === "addTopicBtn") {
      const input = document.getElementById("customTopic");
      const title = String(input && input.value || "").trim();
      if (!title) return;
      slides.push({
        id: `topic-${Date.now()}`,
        kind: "topic",
        title,
        subtitle: meetingTitle.value,
        selected: true,
        custom: true,
      });
      renderAll();
    }
  });

  photoGrid.addEventListener("click", (event) => {
    const target = event.target.closest("[data-slide-target]");
    if (target) {
      activeSlideId = target.getAttribute("data-slide-target");
      renderPhotoGrid();
      renderPreview();
      return;
    }
    const card = event.target.closest("[data-photo-id]");
    if (!card) return;
    assignPhotoToActive(card.getAttribute("data-photo-id"));
    renderPhotoGrid();
    renderPreview();
  });

  photoGrid.addEventListener("error", (event) => {
    const img = event.target;
    if (!img || img.tagName !== "IMG") return;
    const card = img.closest("[data-photo-id]");
    if (!card) return;
    const deadId = card.getAttribute("data-photo-id");
    if (deadId) failedPhotoIds.add(deadId);
    card.hidden = true;
  }, true);

  preview.addEventListener("click", (event) => {
    const slide = event.target.closest("[data-slide]");
    if (!slide) return;
    activeSlideId = slide.getAttribute("data-slide");
    renderPhotoGrid();
    renderPreview();
  });

  preview.addEventListener("error", (event) => {
    const img = event.target;
    if (!img || img.tagName !== "IMG") return;
    const deadId = img.getAttribute("data-photo-id");
    if (!deadId || failedPhotoIds.has(deadId)) return;
    failedPhotoIds.add(deadId);
    const slide = img.closest("[data-slide]");
    const key = slide && slide.getAttribute("data-slide");
    if (key && slidePhotos[key] && slidePhotos[key].photoId === deadId) {
      slidePhotos[key].photoId = null;
    }
    renderPreview();
    renderPhotoGrid();
  }, true);

  valePhotosBtn.addEventListener("click", () => loadPhotos("Port Vale", photoQuery.value.trim()));
  oppPhotosBtn.addEventListener("click", () => {
    if (!opponent) return;
    loadPhotos(opponent.name, photoQuery.value.trim());
  });
  photoQueryBtn.addEventListener("click", () => loadPhotos("Port Vale", photoQuery.value.trim()));
  photoQuery.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadPhotos("Port Vale", photoQuery.value.trim());
    }
  });

  cutoutInput.addEventListener("change", () => {
    const file = cutoutInput.files && cutoutInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const slot = ensureSlidePhoto(activeSlideId);
      slot.cutout = String(reader.result || "");
      slot.photoId = null;
      cutoutFileName.textContent = file.name;
      clearCutoutBtn.disabled = false;
      renderPreview();
      renderPhotoGrid();
    };
    reader.readAsDataURL(file);
  });

  clearCutoutBtn.addEventListener("click", () => {
    const slot = ensureSlidePhoto(activeSlideId);
    slot.cutout = null;
    cutoutInput.value = "";
    cutoutFileName.textContent = "PNG / JPG — applies to selected slide";
    clearCutoutBtn.disabled = !Object.values(slidePhotos).some((s) => s.cutout);
    renderPreview();
  });

  saveBtn.addEventListener("click", saveDeck);
  downloadBtn.addEventListener("click", downloadPack);
  window.addEventListener("resize", scaleSlides);
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(scaleSlides).observe(preview);
  }

  async function boot() {
    try {
      const [metaRes, clubsRes] = await Promise.all([
        fetch("/api/pa-meeting-slides/meta"),
        fetch("/api/pa-meeting-slides/clubs?league=league-two"),
      ]);
      meta = metaRes.ok ? await metaRes.json() : { packs: [], portVale: { badgeUrl: VALE_BADGE } };
      packs = meta.packs || [];
      packId = meta.defaultPack || "set-plays";
      meetingTitle.value = currentPack().label || "Set Plays";
      const clubData = clubsRes.ok ? await clubsRes.json() : { clubs: [] };
      leagueTwoClubs = clubData.clubs || [];
      renderAll();
      loadPhotos("Port Vale", "", { refresh: false }).catch(() => {});
      const params = new URLSearchParams(window.location.search);
      const preset = params.get("club") || params.get("opponent");
      if (preset) {
        await searchClubs(preset);
        const first = searchResults.querySelector("button[data-club-id]");
        if (first) await selectClubById(first.getAttribute("data-club-id"));
      }
    } catch (err) {
      setStatus(err.message || "Could not load meeting slides", true);
    }
  }

  boot();
})();
