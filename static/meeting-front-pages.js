(function () {
  "use strict";

  const playerSearch = document.getElementById("playerSearch");
  const searchResults = document.getElementById("searchResults");
  const statusBanner = document.getElementById("statusBanner");
  const workspace = document.getElementById("workspace");
  const editor = document.getElementById("editor");
  const preview = document.getElementById("preview");
  const downloadBtn = document.getElementById("downloadBtn");
  const refreshBtn = document.getElementById("refreshBtn");
  const refreshPhotosBtn = document.getElementById("refreshPhotosBtn");
  const cutoutInput = document.getElementById("cutoutInput");
  const clearCutoutBtn = document.getElementById("clearCutoutBtn");
  const photoPanel = document.getElementById("photoPanel");
  const photoGrid = document.getElementById("photoGrid");
  const photoMeta = document.getElementById("photoMeta");

  const SLIDE_W = 1920;
  const SLIDE_H = 1080;
  const BADGE_URL = "/standalone/port-vale-badge.png";

  let searchTimer = null;
  let pack = null;
  let cutoutDataUrl = null;
  let selectedPlayerId = null;
  let webPhotos = [];
  let selectedPhotoId = null;
  let selectedPhotoIsSoft = true;

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

  function slugify(value) {
    return String(value || "player")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "player";
  }

  function displayStat(value) {
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  function selectedWebPhoto() {
    return webPhotos.find((p) => p.id === selectedPhotoId) || null;
  }

  function photoSrc() {
    if (cutoutDataUrl) return cutoutDataUrl;
    const web = selectedWebPhoto();
    if (web) return web.proxyUrl || web.url;
    return (pack && pack.player && pack.player.photoUrl) || "";
  }

  function photoUsesSoftMask() {
    if (cutoutDataUrl) return false;
    const web = selectedWebPhoto();
    if (web) return !web.cutoutFriendly || web.kind === "action";
    return true;
  }

  async function searchPlayers(query) {
    const q = String(query || "").trim();
    if (q.length < 2) {
      searchResults.hidden = true;
      searchResults.innerHTML = "";
      return;
    }
    try {
      const res = await fetch("/api/players", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ search: q }),
      });
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      const players = Array.isArray(data.players) ? data.players : [];
      if (!players.length) {
        searchResults.innerHTML = "<li><button type='button' disabled>No matches</button></li>";
        searchResults.hidden = false;
        return;
      }
      searchResults.innerHTML = players.slice(0, 12).map((p) => {
        const id = p.impect_player_id || p.id || p.playerId || p.player_id;
        const name = p.name || "Player";
        const season0 = (p.seasons && p.seasons[0]) || {};
        const club = p.club || season0.club || "";
        const league = p.league || season0.competition_name || "";
        return `<li><button type="button" data-id="${escapeAttr(id)}">
          ${escapeHtml(name)}
          <span class="mfp-results__meta">${escapeHtml([club, league].filter(Boolean).join(" · "))}</span>
        </button></li>`;
      }).join("");
      searchResults.hidden = false;
    } catch (err) {
      setStatus(err.message || "Search failed", true);
    }
  }

  async function loadWebPhotos() {
    if (!pack || !pack.player) return;
    const name = pack.player.name;
    const club = pack.player.club && pack.player.club !== "—" ? pack.player.club : "";
    setStatus("Finding photos on the internet…");
    refreshPhotosBtn.disabled = true;
    try {
      const url = `/api/meeting-front-pages/photos?name=${encodeURIComponent(name)}${club ? `&club=${encodeURIComponent(club)}` : ""}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Photo search failed");
      const data = await res.json();
      webPhotos = Array.isArray(data.photos) ? data.photos : [];
      selectedPhotoId = webPhotos[0] ? webPhotos[0].id : null;
      if (webPhotos[0] && pack.player) {
        pack.player.photoUrl = webPhotos[0].proxyUrl;
      }
      renderPhotoGrid();
      renderPreview();
      setStatus(
        webPhotos.length
          ? `Found ${webPhotos.length} photos — click one to use it on the slides.`
          : "No web photos found — upload a cutout or try Find web photos again."
      );
    } catch (err) {
      setStatus(err.message || "Photo search failed", true);
    } finally {
      refreshPhotosBtn.disabled = !pack;
    }
  }

  function renderPhotoGrid() {
    if (!webPhotos.length) {
      photoPanel.hidden = true;
      photoGrid.innerHTML = "";
      return;
    }
    photoPanel.hidden = false;
    photoMeta.textContent = `${webPhotos.length} options · Transfermarkt / Wikipedia / web`;
    photoGrid.innerHTML = webPhotos.map((photo) => `
      <button type="button" class="mfp-photo-card ${photo.id === selectedPhotoId ? "is-selected" : ""}" data-photo-id="${escapeAttr(photo.id)}" title="${escapeAttr(photo.label)}">
        <img src="${escapeAttr(photo.proxyUrl || photo.url)}" alt="" loading="lazy" />
        <span class="mfp-photo-card__tag">${escapeHtml(photo.source)}</span>
      </button>
    `).join("");
  }

  async function loadPack(playerId) {
    selectedPlayerId = playerId;
    cutoutDataUrl = null;
    cutoutInput.value = "";
    clearCutoutBtn.disabled = true;
    webPhotos = [];
    selectedPhotoId = null;
    setStatus("Loading player pack…");
    downloadBtn.disabled = true;
    refreshBtn.disabled = true;
    refreshPhotosBtn.disabled = true;
    try {
      const res = await fetch(`/api/meeting-front-pages/pack?playerId=${encodeURIComponent(playerId)}`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Load failed (${res.status})`);
      }
      pack = await res.json();
      workspace.hidden = false;
      renderEditor();
      renderPreview();
      downloadBtn.disabled = false;
      refreshBtn.disabled = false;
      refreshPhotosBtn.disabled = false;
      setStatus(`Loaded ${pack.player.name} — fetching web photos…`);
      await loadWebPhotos();
    } catch (err) {
      setStatus(err.message || "Could not load player", true);
    }
  }

  function selectedProfiles() {
    return (pack.profiles || []).filter((p) => p.selected);
  }

  function renderEditor() {
    const p = pack.player;
    const c = pack.careerStats || {};
    const profilesHtml = (pack.profiles || []).map((prof, idx) => {
      const bullets = (prof.bullets || []).join("\n");
      const score = prof.scorePct != null ? `${prof.scorePct}% fit` : "no score";
      return `<div class="mfp-profile-card ${prof.selected ? "is-on" : ""}" data-profile-idx="${idx}">
        <div class="mfp-profile-card__head">
          <input type="checkbox" data-field="selected" ${prof.selected ? "checked" : ""} />
          <div>
            <div class="mfp-profile-card__title">${escapeHtml(prof.title)}</div>
            <div class="mfp-profile-card__score">${escapeHtml(score)}</div>
          </div>
        </div>
        <div class="mfp-field">
          <label>Title</label>
          <input data-field="title" value="${escapeAttr(prof.title)}" />
        </div>
        <div class="mfp-field">
          <label>Bullets (one per line)</label>
          <textarea data-field="bullets" rows="3">${escapeHtml(bullets)}</textarea>
        </div>
      </div>`;
    }).join("");

    editor.innerHTML = `
      <h2>Identity</h2>
      <div class="mfp-field"><label>First name</label><input data-id-field="firstName" value="${escapeAttr(p.firstName)}" /></div>
      <div class="mfp-field"><label>Surname</label><input data-id-field="lastName" value="${escapeAttr(p.lastName)}" /></div>
      <div class="mfp-field"><label>Positions line</label><input data-id-field="positionLine" value="${escapeAttr(p.positionLine)}" /></div>
      <div class="mfp-field"><label>Age</label><input data-id-field="ageLine" value="${escapeAttr(p.ageLine)}" /></div>
      <div class="mfp-field"><label>Height</label><input data-id-field="height" value="${escapeAttr(p.height)}" /></div>
      <div class="mfp-field"><label>Foot</label><input data-id-field="foot" value="${escapeAttr(p.foot)}" /></div>
      <div class="mfp-field"><label>Club</label><input data-id-field="club" value="${escapeAttr(p.club)}" /></div>
      <div class="mfp-field"><label>Transfer type</label><input data-id-field="transferType" value="${escapeAttr(p.transferType)}" /></div>

      <h2>Career stats</h2>
      <p class="mfp-hint" style="margin-top:-4px">${escapeHtml(c.note || "")}</p>
      <div class="mfp-stats-grid">
        <div class="mfp-field"><label>Games</label><input data-stat="games" value="${escapeAttr(displayStat(c.games))}" /></div>
        <div class="mfp-field"><label>Starts</label><input data-stat="starts" value="${escapeAttr(displayStat(c.starts))}" /></div>
        <div class="mfp-field"><label>Minutes</label><input data-stat="minutes" value="${escapeAttr(displayStat(c.minutes))}" /></div>
        <div class="mfp-field"><label>Goals</label><input data-stat="goals" value="${escapeAttr(displayStat(c.goals))}" /></div>
        <div class="mfp-field"><label>Assists</label><input data-stat="assists" value="${escapeAttr(displayStat(c.assists))}" /></div>
      </div>

      <h2>Profiles in pack</h2>
      <p class="mfp-hint" style="margin-top:-4px">Tick which profiles get their own title slide. Identity footer always shows the top 3 scores.</p>
      <div class="mfp-profile-list">${profilesHtml || "<p class='mfp-hint'>No PV profiles for this position.</p>"}</div>
    `;

    editor.querySelectorAll("[data-id-field]").forEach((el) => {
      el.addEventListener("input", () => {
        pack.player[el.getAttribute("data-id-field")] = el.value;
        renderPreview();
      });
    });
    editor.querySelectorAll("[data-stat]").forEach((el) => {
      el.addEventListener("input", () => {
        const key = el.getAttribute("data-stat");
        const raw = el.value.trim();
        pack.careerStats[key] = raw === "" || raw === "—" ? null : (/^\d+$/.test(raw) ? Number(raw) : raw);
        renderPreview();
      });
    });
    editor.querySelectorAll(".mfp-profile-card").forEach((card) => {
      const idx = Number(card.getAttribute("data-profile-idx"));
      card.querySelectorAll("[data-field]").forEach((el) => {
        el.addEventListener("input", () => syncProfileField(idx, el));
        el.addEventListener("change", () => syncProfileField(idx, el));
      });
    });
  }

  function syncProfileField(idx, el) {
    const field = el.getAttribute("data-field");
    const prof = pack.profiles[idx];
    if (!prof) return;
    if (field === "selected") {
      prof.selected = el.checked;
    } else if (field === "bullets") {
      prof.bullets = el.value.split(/\n+/).map((s) => s.trim()).filter(Boolean);
    } else {
      prof[field] = el.value;
    }
    const card = el.closest(".mfp-profile-card");
    if (card) card.classList.toggle("is-on", Boolean(prof.selected));
    renderPreview();
  }

  function brandHtml() {
    return `<div class="mfp-slide__brand">
      <img src="${BADGE_URL}" alt="Port Vale FC" />
      <div class="mfp-slide__brand-text">Port Vale FC<span>Scout Report</span></div>
    </div>`;
  }

  function photoHtml() {
    const src = photoSrc();
    if (!src) {
      return `<div class="mfp-slide__photo"><div style="color:#666;font:600 28px Oswald;padding:40px;text-align:center">PICK A PHOTO</div></div>`;
    }
    const soft = photoUsesSoftMask() ? "is-soft" : "";
    return `<div class="mfp-slide__photo ${soft}"><img src="${escapeAttr(src)}" alt="" crossorigin="anonymous" /></div>`;
  }

  function identityScoreBarProfiles() {
    // Identity footer always mirrors the Canva pack: top 3 PV fits by score.
    const scored = (pack.profiles || [])
      .filter((p) => p && p.scorePct != null && !Number.isNaN(Number(p.scorePct)))
      .slice()
      .sort((a, b) => Number(b.scorePct) - Number(a.scorePct));
    if (scored.length) return scored.slice(0, 3);

    // Fallback: selected pack profiles (still show names even without %).
    return selectedProfiles().filter((p) => p && p.title).slice(0, 3);
  }

  function identityScoreBarHtml() {
    const rows = identityScoreBarProfiles();
    if (!rows.length) {
      return `<div class="mfp-id__score-bar mfp-id__score-bar--empty" aria-label="PV profile scores">
        <div class="mfp-id__score-col">
          <div class="mfp-id__score-pct">—</div>
          <div class="mfp-id__score-name">NO PROFILE SCORES</div>
        </div>
      </div>`;
    }
    const cols = rows.map((prof) => {
      const pct = prof.scorePct != null ? `${Math.round(Number(prof.scorePct))}%` : "—";
      // Use human label (DEFENSIVE FULL BACK), not the WIDE presentation title.
      const title = String(prof.label || prof.title || "").toUpperCase();
      return `<div class="mfp-id__score-col">
        <div class="mfp-id__score-pct">${escapeHtml(pct)}</div>
        <div class="mfp-id__score-name">${escapeHtml(title)}</div>
      </div>`;
    }).join("");
    return `<div class="mfp-id__score-bar" aria-label="PV profile scores">${cols}</div>`;
  }

  function identitySlideHtml() {
    const p = pack.player;
    const c = pack.careerStats || {};
    const stats = [
      ["games", "GAMES"],
      ["starts", "STARTS"],
      ["minutes", "MINUTES"],
      ["goals", "GOALS"],
      ["assists", "ASSISTS"],
    ];
    const statsHtml = stats.map(([key, label]) => `
      <div>
        <div class="mfp-id__stat-num">${escapeHtml(displayStat(c[key]))}</div>
        <div class="mfp-id__stat-label">${label}</div>
      </div>`).join("");

    const bio = [
      ["AGE", p.ageLine],
      ["HEIGHT", p.height],
      ["FOOT", p.foot],
      ["CLUB", p.club],
      ["TRANSFER TYPE", p.transferType],
    ].map(([label, value]) => `
      <div class="mfp-id__bio-row">
        <div class="mfp-id__bio-label">${label}</div>
        <div class="mfp-id__bio-value">${escapeHtml(displayStat(value))}</div>
      </div>`).join("");

    const dots = (pack.pitch || []).map((dot) => {
      const cls = dot.state === "primary" ? "is-primary" : dot.state === "secondary" ? "is-secondary" : "";
      const label = dot.state === "primary" ? escapeHtml(dot.label || dot.abbr) : "";
      return `<div class="mfp-pitch__dot ${cls}" style="left:${dot.x}%;top:${dot.y}%">${label}</div>`;
    }).join("");

    return `<div class="mfp-slide mfp-slide--identity" data-slide="identity">
      ${brandHtml()}
      ${photoHtml()}
      <div class="mfp-id__left">
        <p class="mfp-id__first">${escapeHtml(p.firstName)}</p>
        <p class="mfp-id__last">${escapeHtml(p.lastName)}</p>
        <p class="mfp-id__positions">${escapeHtml(p.positionLine)}</p>
        <div class="mfp-id__bio">${bio}</div>
      </div>
      <div class="mfp-id__right">
        <p class="mfp-id__stats-title">CAREER STATS</p>
        <div class="mfp-id__stats">${statsHtml}</div>
        <div class="mfp-pitch">${dots}</div>
      </div>
      ${identityScoreBarHtml()}
    </div>`;
  }

  function profileSlideHtml(prof, idx) {
    const bullets = (prof.bullets || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("");
    return `<div class="mfp-slide mfp-slide--profile" data-slide="profile-${idx}">
      ${brandHtml()}
      ${photoHtml()}
      <div class="mfp-profile__copy">
        <h2 class="mfp-profile__title">${escapeHtml(prof.title)}</h2>
        <ul class="mfp-profile__bullets">${bullets}</ul>
      </div>
    </div>`;
  }

  function scaleSlides() {
    preview.querySelectorAll(".mfp-slide-wrap").forEach((wrap) => {
      const slide = wrap.querySelector(".mfp-slide");
      if (!slide) return;
      const width = wrap.clientWidth || 960;
      const scale = Math.min(1, width / SLIDE_W);
      wrap.style.overflow = "hidden";
      wrap.style.height = `${SLIDE_H * scale}px`;
      slide.style.transformOrigin = "top left";
      slide.style.transform = `scale(${scale})`;
    });
  }

  function renderPreview() {
    if (!pack) return;
    const parts = [];
    parts.push(`<div class="mfp-slide-wrap"><p class="mfp-slide-caption">01 · Identity</p>${identitySlideHtml()}</div>`);
    selectedProfiles().forEach((prof, i) => {
      const idx = pack.profiles.indexOf(prof);
      parts.push(`<div class="mfp-slide-wrap"><p class="mfp-slide-caption">${String(i + 2).padStart(2, "0")} · ${escapeHtml(prof.title)}</p>${profileSlideHtml(prof, idx)}</div>`);
    });
    preview.innerHTML = parts.join("");
    requestAnimationFrame(scaleSlides);
  }

  function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("Could not read image"));
      reader.readAsDataURL(file);
    });
  }

  async function applyCutoutFile(file) {
    if (!file) return;
    cutoutDataUrl = await readFileAsDataUrl(file);
    clearCutoutBtn.disabled = false;
    selectedPhotoId = null;
    renderPhotoGrid();
    if (pack) renderPreview();
    setStatus("Uploaded cutout applied to all slides.");
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  async function waitForImages(root) {
    const imgs = Array.from(root.querySelectorAll("img"));
    await Promise.all(imgs.map((img) => {
      if (img.complete && img.naturalWidth) return Promise.resolve();
      return new Promise((resolve) => {
        img.onload = () => resolve();
        img.onerror = () => resolve();
      });
    }));
  }

  async function captureSlide(slideEl) {
    const cloneHost = document.createElement("div");
    cloneHost.style.cssText = "position:fixed;left:-10000px;top:0;width:1920px;height:1080px;opacity:1;pointer-events:none;z-index:-1;";
    const clone = slideEl.cloneNode(true);
    clone.style.transform = "none";
    cloneHost.appendChild(clone);
    document.body.appendChild(cloneHost);
    await waitForImages(clone);
    try {
      const canvas = await html2canvas(clone, {
        width: SLIDE_W,
        height: SLIDE_H,
        scale: 1,
        backgroundColor: "#cfc9bf",
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
    if (!pack) return;
    if (typeof html2canvas !== "function" || typeof JSZip !== "function") {
      setStatus("Export libraries failed to load — hard refresh and try again.", true);
      return;
    }
    downloadBtn.disabled = true;
    setStatus("Rendering PNG pack…");
    try {
      const zip = new JSZip();
      const folder = slugify(pack.player.name || "player");
      const slides = Array.from(preview.querySelectorAll(".mfp-slide"));
      for (let i = 0; i < slides.length; i += 1) {
        const slide = slides[i];
        const blob = await captureSlide(slide);
        if (!blob) throw new Error("Capture failed — try a different photo");
        const key = slide.getAttribute("data-slide") || `slide-${i + 1}`;
        const title = key === "identity"
          ? "01-identity"
          : `${String(i + 1).padStart(2, "0")}-${slugify(selectedProfiles()[i - 1]?.title || key)}`;
        zip.file(`${folder}/${title}.png`, blob);
        setStatus(`Rendering PNG pack… ${i + 1}/${slides.length}`);
      }
      const out = await zip.generateAsync({ type: "blob" });
      downloadBlob(out, `${folder}-meeting-front-pages.zip`);
      setStatus(`Downloaded ${slides.length} PNGs.`);
    } catch (err) {
      setStatus(err.message || "Export failed", true);
    } finally {
      downloadBtn.disabled = false;
    }
  }

  playerSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchPlayers(playerSearch.value), 220);
  });

  searchResults.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-id]");
    if (!btn) return;
    const id = Number(btn.getAttribute("data-id"));
    searchResults.hidden = true;
    playerSearch.value = btn.childNodes[0].textContent.trim();
    loadPack(id);
  });

  document.addEventListener("click", (event) => {
    if (!searchResults.contains(event.target) && event.target !== playerSearch) {
      searchResults.hidden = true;
    }
  });

  photoGrid.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-photo-id]");
    if (!btn) return;
    selectedPhotoId = btn.getAttribute("data-photo-id");
    cutoutDataUrl = null;
    cutoutInput.value = "";
    clearCutoutBtn.disabled = true;
    const web = selectedWebPhoto();
    if (web && pack) pack.player.photoUrl = web.proxyUrl;
    renderPhotoGrid();
    renderPreview();
    setStatus(`Using ${web ? web.label : "selected"} photo.`);
  });

  refreshBtn.addEventListener("click", () => {
    if (selectedPlayerId) loadPack(selectedPlayerId);
  });

  refreshPhotosBtn.addEventListener("click", () => loadWebPhotos());

  downloadBtn.addEventListener("click", downloadPack);

  cutoutInput.addEventListener("change", () => {
    const file = cutoutInput.files && cutoutInput.files[0];
    applyCutoutFile(file).catch((err) => setStatus(err.message, true));
  });

  clearCutoutBtn.addEventListener("click", () => {
    cutoutDataUrl = null;
    cutoutInput.value = "";
    clearCutoutBtn.disabled = true;
    if (pack) renderPreview();
    setStatus("Upload cleared — using selected web photo.");
  });

  document.addEventListener("paste", (event) => {
    const items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        applyCutoutFile(file).catch((err) => setStatus(err.message, true));
        event.preventDefault();
        break;
      }
    }
  });

  window.addEventListener("resize", () => {
    if (pack) scaleSlides();
  });
})();
