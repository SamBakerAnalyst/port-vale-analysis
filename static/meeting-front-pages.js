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

  const cutoutFileName = document.getElementById("cutoutFileName");

  const SLIDE_W = 1920;
  const SLIDE_H = 1080;
  const BADGE_URL = "/standalone/port-vale-badge.png";
  const FORMATION_KEYS = ["4-2-3-1", "4-4-2", "3-5-2", "3-4-3"];
  const FORMATION_LAYOUTS = {
    "4-2-3-1": [
      { code: "GOALKEEPER", abbr: "GK", x: 50, y: 92 },
      { code: "LEFT_WINGBACK_DEFENDER", abbr: "LB", x: 12, y: 74 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 34, y: 78 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 66, y: 78 },
      { code: "RIGHT_WINGBACK_DEFENDER", abbr: "RB", x: 88, y: 74 },
      { code: "DEFENSE_MIDFIELD", abbr: "DM", x: 34, y: 52 },
      { code: "DEFENSE_MIDFIELD", abbr: "DM", x: 66, y: 52 },
      { code: "LEFT_WINGER", abbr: "LW", x: 12, y: 24 },
      { code: "ATTACKING_MIDFIELD", abbr: "AM", x: 50, y: 28 },
      { code: "RIGHT_WINGER", abbr: "RW", x: 88, y: 24 },
      { code: "CENTER_FORWARD", abbr: "ST", x: 50, y: 10 },
    ],
    "4-4-2": [
      { code: "GOALKEEPER", abbr: "GK", x: 50, y: 92 },
      { code: "LEFT_WINGBACK_DEFENDER", abbr: "LB", x: 12, y: 74 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 34, y: 78 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 66, y: 78 },
      { code: "RIGHT_WINGBACK_DEFENDER", abbr: "RB", x: 88, y: 74 },
      { code: "LEFT_MIDFIELD", abbr: "LM", x: 12, y: 46 },
      { code: "CENTRAL_MIDFIELD", abbr: "CM", x: 36, y: 48 },
      { code: "CENTRAL_MIDFIELD", abbr: "CM", x: 64, y: 48 },
      { code: "RIGHT_MIDFIELD", abbr: "RM", x: 88, y: 46 },
      { code: "CENTER_FORWARD", abbr: "ST", x: 36, y: 12 },
      { code: "CENTER_FORWARD", abbr: "ST", x: 64, y: 12 },
    ],
    "3-5-2": [
      { code: "GOALKEEPER", abbr: "GK", x: 50, y: 92 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 26, y: 78 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 50, y: 80 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 74, y: 78 },
      { code: "LEFT_WINGBACK_DEFENDER", abbr: "WB", x: 10, y: 52 },
      { code: "DEFENSE_MIDFIELD", abbr: "DM", x: 50, y: 54 },
      { code: "CENTRAL_MIDFIELD", abbr: "CM", x: 34, y: 40 },
      { code: "CENTRAL_MIDFIELD", abbr: "CM", x: 66, y: 40 },
      { code: "RIGHT_WINGBACK_DEFENDER", abbr: "WB", x: 90, y: 52 },
      { code: "CENTER_FORWARD", abbr: "ST", x: 36, y: 12 },
      { code: "CENTER_FORWARD", abbr: "ST", x: 64, y: 12 },
    ],
    "3-4-3": [
      { code: "GOALKEEPER", abbr: "GK", x: 50, y: 92 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 26, y: 78 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 50, y: 80 },
      { code: "CENTRAL_DEFENDER", abbr: "CB", x: 74, y: 78 },
      { code: "LEFT_MIDFIELD", abbr: "LM", x: 12, y: 48 },
      { code: "CENTRAL_MIDFIELD", abbr: "CM", x: 36, y: 50 },
      { code: "CENTRAL_MIDFIELD", abbr: "CM", x: 64, y: 50 },
      { code: "RIGHT_MIDFIELD", abbr: "RM", x: 88, y: 48 },
      { code: "LEFT_WINGER", abbr: "LW", x: 16, y: 16 },
      { code: "CENTER_FORWARD", abbr: "ST", x: 50, y: 10 },
      { code: "RIGHT_WINGER", abbr: "RW", x: 84, y: 16 },
    ],
  };
  const POSITION_ALIASES = {
    LEFT_BACK: ["LEFT_WINGBACK_DEFENDER", "LEFT_MIDFIELD"],
    RIGHT_BACK: ["RIGHT_WINGBACK_DEFENDER", "RIGHT_MIDFIELD"],
    LEFT_WINGBACK_DEFENDER: ["LEFT_BACK", "LEFT_MIDFIELD", "LEFT_WINGER"],
    RIGHT_WINGBACK_DEFENDER: ["RIGHT_BACK", "RIGHT_MIDFIELD", "RIGHT_WINGER"],
    LEFT_WINGER: ["LEFT_MIDFIELD", "LEFT_WINGBACK_DEFENDER"],
    RIGHT_WINGER: ["RIGHT_MIDFIELD", "RIGHT_WINGBACK_DEFENDER"],
    LEFT_MIDFIELD: ["LEFT_WINGER", "LEFT_WINGBACK_DEFENDER"],
    RIGHT_MIDFIELD: ["RIGHT_WINGER", "RIGHT_WINGBACK_DEFENDER"],
    SECOND_STRIKER: ["CENTER_FORWARD", "ATTACKING_MIDFIELD"],
    CENTER_FORWARD: ["SECOND_STRIKER"],
    ATTACKING_MIDFIELD: ["CENTRAL_MIDFIELD", "SECOND_STRIKER"],
    CENTRAL_MIDFIELD: ["DEFENSE_MIDFIELD", "ATTACKING_MIDFIELD"],
    DEFENSE_MIDFIELD: ["CENTRAL_MIDFIELD"],
  };

  let searchTimer = null;
  let searchAbort = null;
  let searchSeq = 0;
  let pack = null;
  let selectedPlayerId = null;
  let webPhotos = [];
  /** @type {Record<string, {photoId: string|null, cutout: string|null, soft: boolean}>} */
  let slidePhotos = {};
  let activeSlideKey = "identity";
  let selectedFormation = localStorage.getItem("mfp-formation") || "4-2-3-1";
  if (!FORMATION_KEYS.includes(selectedFormation)) selectedFormation = "4-2-3-1";
  let includeDataSlide = localStorage.getItem("mfp-data-slide") !== "0";

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

  function selectedProfiles() {
    return (pack && pack.profiles || []).filter((p) => p.selected);
  }

  function slideKeyList() {
    const keys = ["identity"];
    if (includeDataSlide && pack && pack.dataSummary) keys.push("data");
    selectedProfiles().forEach((prof) => {
      const idx = pack.profiles.indexOf(prof);
      keys.push(`profile-${idx}`);
    });
    return keys;
  }

  function photoSlideKeys() {
    return slideKeyList().filter((key) => key !== "data");
  }

  function slideLabel(key) {
    if (key === "identity") return "Identity";
    if (key === "data") return "Data summary";
    const idx = Number(String(key).replace("profile-", ""));
    const prof = pack && pack.profiles ? pack.profiles[idx] : null;
    return (prof && prof.title) || key;
  }

  function ensureSlidePhoto(key) {
    if (!slidePhotos[key]) {
      slidePhotos[key] = { photoId: null, cutout: null, soft: true };
    }
    return slidePhotos[key];
  }

  function webPhotoById(id) {
    return webPhotos.find((p) => p.id === id) || null;
  }

  function photoSrc(slideKey) {
    const slot = ensureSlidePhoto(slideKey || activeSlideKey);
    if (slot.cutout) return slot.cutout;
    const web = webPhotoById(slot.photoId);
    if (web) return web.proxyUrl || web.url;
    return (pack && pack.player && pack.player.photoUrl) || "";
  }

  function photoUsesSoftMask(slideKey) {
    const slot = ensureSlidePhoto(slideKey || activeSlideKey);
    if (slot.cutout) return false;
    const web = webPhotoById(slot.photoId);
    if (web) return !web.cutoutFriendly || web.kind === "action";
    return slot.soft !== false;
  }

  function assignPhotoToActive(photoId) {
    const slot = ensureSlidePhoto(activeSlideKey);
    slot.photoId = photoId;
    slot.cutout = null;
    const web = webPhotoById(photoId);
    slot.soft = web ? (!web.cutoutFriendly || web.kind === "action") : true;
    clearCutoutBtn.disabled = !Object.values(slidePhotos).some((s) => s.cutout);
  }

  function autoAssignDistinctPhotos() {
    const keys = photoSlideKeys();
    keys.forEach((key) => ensureSlidePhoto(key));
    if (!webPhotos.length) {
      keys.forEach((key) => {
        const slot = slidePhotos[key];
        if (!slot.photoId && !slot.cutout && pack && pack.player) {
          slot.soft = true;
        }
      });
      return;
    }
    // Prefer clean portraits first for identity; spread remaining across profile slides.
    const ranked = webPhotos.slice().sort((a, b) => {
      const score = (p) => {
        let s = 0;
        if (p.source === "transfermarkt") s += 8;
        if (p.source === "fotmob") s += 6;
        if (p.cutoutFriendly) s += 3;
        if (p.kind === "portrait") s += 2;
        if (p.kind === "action") s -= 1;
        return s;
      };
      return score(b) - score(a);
    });
    const used = new Set();
    keys.forEach((key, i) => {
      const slot = slidePhotos[key];
      if (slot.cutout) return;
      // Keep an existing pick if still in the gallery.
      if (slot.photoId && webPhotoById(slot.photoId)) {
        used.add(slot.photoId);
        return;
      }
      let pick = ranked.find((p) => !used.has(p.id));
      if (!pick && ranked.length) pick = ranked[i % ranked.length];
      if (pick) {
        slot.photoId = pick.id;
        slot.soft = !pick.cutoutFriendly || pick.kind === "action";
        used.add(pick.id);
      }
    });
  }

  async function searchPlayers(query) {
    const q = String(query || "").trim();
    if (q.length < 2) {
      if (searchAbort) searchAbort.abort();
      searchResults.hidden = true;
      searchResults.innerHTML = "";
      return;
    }

    if (searchAbort) searchAbort.abort();
    searchAbort = new AbortController();
    const seq = ++searchSeq;
    const signal = searchAbort.signal;

    searchResults.innerHTML = "<li><div class='mfp-results__empty'>Searching…</div></li>";
    searchResults.hidden = false;

    try {
      const res = await fetch(
        `/api/meeting-front-pages/players?q=${encodeURIComponent(q)}`,
        { credentials: "same-origin", signal, cache: "no-store" }
      );
      if (seq !== searchSeq) return;
      if (!res.ok) {
        let detail = `Search failed (${res.status})`;
        try {
          const errBody = await res.json();
          if (errBody && errBody.detail) detail = String(errBody.detail);
        } catch (_) { /* ignore */ }
        searchResults.innerHTML = `<li><div class="mfp-results__empty">${escapeHtml(detail)}</div></li>`;
        searchResults.hidden = false;
        return;
      }
      const data = await res.json();
      if (seq !== searchSeq) return;
      const players = Array.isArray(data.players) ? data.players : [];
      if (!players.length) {
        const msg = data.message || "No matches — check spelling.";
        searchResults.innerHTML = `<li><div class="mfp-results__empty">${escapeHtml(msg)}</div></li>`;
        searchResults.hidden = false;
        setStatus("");
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
      setStatus("");
    } catch (err) {
      if (err && err.name === "AbortError") return;
      if (seq !== searchSeq) return;
      searchResults.innerHTML = `<li><div class="mfp-results__empty">${escapeHtml(err.message || "Search unavailable — try again")}</div></li>`;
      searchResults.hidden = false;
    }
  }

  async function loadWebPhotos() {
    if (!pack || !pack.player) return;
    const name = pack.player.name;
    let club = pack.player.club && pack.player.club !== "—" ? pack.player.club : "";
    // Drop academy suffixes so Transfermarkt / Bing find the senior profile photos.
    club = String(club).replace(/\s*(U\d{2}|Under[-\s]?\d{2}|Youth|Academy|Reserves?|II|B)\s*$/i, "").trim();
    setStatus("Finding photos on the internet…");
    refreshPhotosBtn.disabled = true;
    try {
      const url = `/api/meeting-front-pages/photos?name=${encodeURIComponent(name)}${club ? `&club=${encodeURIComponent(club)}` : ""}&refresh=1`;
      const res = await fetch(url);
      if (!res.ok) throw new Error("Photo search failed");
      const data = await res.json();
      webPhotos = Array.isArray(data.photos) ? data.photos : [];
      autoAssignDistinctPhotos();
      renderPhotoGrid();
      renderPreview();
      const assigned = photoSlideKeys().filter((k) => photoSrc(k)).length;
      setStatus(
        webPhotos.length
          ? `Found ${webPhotos.length} photos — assigned across ${assigned} slides. Click a slide target, then a photo.`
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
    const activeId = (slidePhotos[activeSlideKey] || {}).photoId;
    const targets = photoSlideKeys().map((key) => `
      <button type="button" class="mfp-slide-target ${key === activeSlideKey ? "is-active" : ""}" data-slide-target="${escapeAttr(key)}">
        ${escapeHtml(slideLabel(key))}
      </button>`).join("");
    photoMeta.innerHTML = `${webPhotos.length} options · click a slide, then a photo`;
    photoGrid.innerHTML = `
      <div class="mfp-slide-targets">${targets}</div>
      <p class="mfp-hint mfp-photo-assign-hint">Assigning to <strong>${escapeHtml(slideLabel(activeSlideKey))}</strong> — each slide can use a different picture.</p>
      <div class="mfp-photo-grid__cards">
        ${webPhotos.map((photo) => {
          const usedOn = photoSlideKeys().filter((k) => (slidePhotos[k] || {}).photoId === photo.id);
          const usedTag = usedOn.length ? usedOn.map(slideLabel).join(", ") : "";
          return `<button type="button" class="mfp-photo-card ${photo.id === activeId ? "is-selected" : ""}" data-photo-id="${escapeAttr(photo.id)}" title="${escapeAttr(photo.label)}">
            <img src="${escapeAttr(photo.proxyUrl || photo.url)}" alt="" loading="lazy" />
            <span class="mfp-photo-card__tag">${escapeHtml(photo.source)}${usedTag ? ` · ${escapeHtml(usedTag)}` : ""}</span>
          </button>`;
        }).join("")}
      </div>`;
  }

  async function loadPack(playerId, positionCode, options = {}) {
    const keepPhotos = Boolean(options.keepPhotos);
    const previousPhotos = keepPhotos ? { ...slidePhotos } : null;
    const previousWeb = keepPhotos ? webPhotos.slice() : null;
    const iterationId = options.iterationId != null && options.iterationId !== ""
      ? Number(options.iterationId)
      : null;
    selectedPlayerId = playerId;
    cutoutInput.value = "";
    clearCutoutBtn.disabled = true;
    if (!keepPhotos) {
      webPhotos = [];
      slidePhotos = {};
      activeSlideKey = "identity";
    }
    const statusBits = [];
    if (iterationId) statusBits.push("season");
    if (positionCode) statusBits.push("position");
    setStatus(statusBits.length ? `Updating ${statusBits.join(" + ")}…` : "Loading player pack…");
    downloadBtn.disabled = true;
    refreshBtn.disabled = true;
    refreshPhotosBtn.disabled = true;
    try {
      const qs = new URLSearchParams({ playerId: String(playerId) });
      if (positionCode) qs.set("position", String(positionCode));
      if (Number.isFinite(iterationId) && iterationId > 0) qs.set("iterationId", String(iterationId));
      const res = await fetch(`/api/meeting-front-pages/pack?${qs.toString()}`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Load failed (${res.status})`);
      }
      pack = await res.json();
      workspace.hidden = false;
      if (keepPhotos && previousPhotos) {
        slidePhotos = previousPhotos;
        webPhotos = previousWeb || [];
      }
      slideKeyList().forEach((key) => {
        if (key === "data") return;
        ensureSlidePhoto(key);
      });
      renderEditor();
      renderPreview();
      if (keepPhotos && webPhotos.length) renderPhotoGrid();
      downloadBtn.disabled = false;
      refreshBtn.disabled = false;
      refreshPhotosBtn.disabled = false;
      if (keepPhotos) {
        const seasonBit = [pack.player.league, pack.player.season].filter(Boolean).join(" ");
        const posBit = pack.player.positionLine || positionCode || "";
        setStatus(`Loaded ${[posBit, seasonBit].filter(Boolean).join(" · ")}`);
      } else {
        setStatus(`Loaded ${pack.player.name} — fetching web photos…`);
        await loadWebPhotos();
      }
    } catch (err) {
      setStatus(err.message || "Could not load player", true);
    }
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
      <div class="mfp-field">
        <label>Season / competition</label>
        <select id="seasonSelect" class="mfp-input mfp-select">
          ${(pack.availableSeasons || []).map((row) => {
            const id = row.iterationId;
            const selected = Number(p.iterationId) === Number(id);
            const label = row.label || [row.competition, row.season, row.club].filter(Boolean).join(" · ");
            return `<option value="${escapeAttr(id)}" ${selected ? "selected" : ""}>${escapeHtml(label)}</option>`;
          }).join("") || `<option value="">No seasons in catalog</option>`}
        </select>
      </div>
      <p class="mfp-hint" style="margin-top:-8px">Pulls Impect minutes, profiles and P90s from that competition season (e.g. PL2 25/26).</p>
      <div class="mfp-field">
        <label>Playing position</label>
        <select id="positionSelect" class="mfp-input mfp-select">
          ${(pack.availablePositions || []).map((pos) => {
            const code = pos.code || "";
            const selected = String(p.primaryPosition || "").toUpperCase() === String(code).toUpperCase();
            return `<option value="${escapeAttr(code)}" ${selected ? "selected" : ""}>${escapeHtml(pos.label || code)}</option>`;
          }).join("")}
        </select>
      </div>
      <p class="mfp-hint" style="margin-top:-8px">Sets the pitch highlight, profile slides, radar and P90 stats.</p>
      <div class="mfp-field"><label>Positions line (display)</label><input data-id-field="positionLine" value="${escapeAttr(p.positionLine)}" /></div>
      <div class="mfp-field"><label>Age</label><input data-id-field="ageLine" value="${escapeAttr(p.ageLine)}" /></div>
      <div class="mfp-field"><label>Height</label><input data-id-field="height" value="${escapeAttr(p.height)}" /></div>
      <div class="mfp-field"><label>Foot</label><input data-id-field="foot" value="${escapeAttr(p.foot)}" /></div>
      <div class="mfp-field"><label>Club</label><input data-id-field="club" value="${escapeAttr(p.club)}" /></div>
      <div class="mfp-field"><label>Transfer type</label><input data-id-field="transferType" value="${escapeAttr(p.transferType)}" /></div>

      <h2>Position map</h2>
      <p class="mfp-hint" style="margin-top:-4px">Shows an 11-man shape — pick the formation that matches how you’ll discuss him.</p>
      ${formationPickerHtml(false)}

      <h2>Pack slides</h2>
      <label class="mfp-check">
        <input type="checkbox" id="dataSlideToggle" ${includeDataSlide ? "checked" : ""} />
        Include data summary slide (best / worst · positions · seasons)
      </label>

      <h2>Career stats</h2>
      <p class="mfp-hint" style="margin-top:-4px">${escapeHtml(c.note || "")}</p>
      <div class="mfp-field">
        <label>Stats label</label>
        <input data-stat="title" value="${escapeAttr(c.title || "CAREER")}" placeholder="CAREER / 25/26 SEASON…" />
      </div>
      <div class="mfp-stats-grid">
        <div class="mfp-field"><label>Games</label><input data-stat="games" value="${escapeAttr(displayStat(c.games))}" /></div>
        <div class="mfp-field"><label>Starts</label><input data-stat="starts" value="${escapeAttr(displayStat(c.starts))}" /></div>
        <div class="mfp-field"><label>Minutes</label><input data-stat="minutes" value="${escapeAttr(displayStat(c.minutes))}" /></div>
        <div class="mfp-field"><label>Goals</label><input data-stat="goals" value="${escapeAttr(displayStat(c.goals))}" /></div>
        <div class="mfp-field"><label>Assists</label><input data-stat="assists" value="${escapeAttr(displayStat(c.assists))}" /></div>
      </div>

      <h2>Profiles in pack</h2>
      <p class="mfp-hint" style="margin-top:-4px">All PV profiles for this position load as slides. Untick any you don’t need. Identity footer shows every selected profile.</p>
      <div class="mfp-profile-list">${profilesHtml || "<p class='mfp-hint'>No PV profiles for this position.</p>"}</div>
    `;

    editor.querySelectorAll("[data-id-field]").forEach((el) => {
      el.addEventListener("input", () => {
        pack.player[el.getAttribute("data-id-field")] = el.value;
        renderPreview();
      });
    });
    const positionSelect = editor.querySelector("#positionSelect");
    if (positionSelect) {
      positionSelect.addEventListener("change", () => {
        const code = positionSelect.value;
        if (!selectedPlayerId || !code) return;
        loadPack(selectedPlayerId, code, {
          keepPhotos: true,
          iterationId: pack.player && pack.player.iterationId,
        });
      });
    }
    const seasonSelect = editor.querySelector("#seasonSelect");
    if (seasonSelect) {
      seasonSelect.addEventListener("change", () => {
        const iter = seasonSelect.value;
        if (!selectedPlayerId || !iter) return;
        loadPack(selectedPlayerId, pack.player && pack.player.primaryPosition, {
          keepPhotos: true,
          iterationId: iter,
        });
      });
    }
    editor.querySelectorAll("[data-formation]").forEach((el) => {
      el.addEventListener("click", () => {
        setFormation(el.getAttribute("data-formation"));
      });
    });
    const dataToggle = editor.querySelector("#dataSlideToggle");
    if (dataToggle) {
      dataToggle.addEventListener("change", () => {
        includeDataSlide = Boolean(dataToggle.checked);
        try { localStorage.setItem("mfp-data-slide", includeDataSlide ? "1" : "0"); } catch (_) { /* ignore */ }
        renderPreview();
      });
    }
    editor.querySelectorAll("[data-stat]").forEach((el) => {
      el.addEventListener("input", () => {
        const key = el.getAttribute("data-stat");
        const raw = el.value.trim();
        if (key === "title") {
          pack.careerStats.title = raw || "CAREER";
        } else {
          pack.careerStats[key] = raw === "" || raw === "—" ? null : (/^\d+$/.test(raw) ? Number(raw) : raw);
        }
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
      // Keep photo slots for newly selected profiles.
      autoAssignDistinctPhotos();
      if (webPhotos.length) renderPhotoGrid();
    } else if (field === "bullets") {
      prof.bullets = el.value.split(/\n+/).map((s) => s.trim()).filter(Boolean);
    } else {
      prof[field] = el.value;
    }
    const card = el.closest(".mfp-profile-card");
    if (card) card.classList.toggle("is-on", Boolean(prof.selected));
    renderPreview();
  }

  function brandHtml(variant) {
    const cls = variant === "light" ? "mfp-slide__brand mfp-slide__brand--light" : "mfp-slide__brand";
    return `<div class="${cls}">
      <img src="${BADGE_URL}" alt="Port Vale FC" />
      <div class="mfp-slide__brand-text">Port Vale FC<span>Scout Report</span></div>
    </div>`;
  }

  function photoHtml(slideKey, extraClass) {
    const src = photoSrc(slideKey);
    const soft = photoUsesSoftMask(slideKey) ? "is-soft" : "";
    const extra = extraClass ? ` ${extraClass}` : "";
    if (!src) {
      return `<div class="mfp-slide__photo ${soft}${extra}"><div class="mfp-slide__photo-empty">PICK A PHOTO</div></div>`;
    }
    return `<div class="mfp-slide__photo ${soft}${extra}"><img src="${escapeAttr(src)}" alt="" crossorigin="anonymous" /></div>`;
  }

  function codesMatch(slotCode, playerCode) {
    const a = String(slotCode || "").toUpperCase();
    const b = String(playerCode || "").toUpperCase();
    if (!a || !b) return false;
    if (a === b) return true;
    const aliases = POSITION_ALIASES[b] || [];
    if (aliases.includes(a)) return true;
    const reverse = POSITION_ALIASES[a] || [];
    return reverse.includes(b);
  }

  function playerPitchRoles() {
    const roles = [];
    const seen = new Set();
    const push = (code, state, abbr) => {
      const key = String(code || "").toUpperCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      roles.push({ code: key, state: state || "primary", abbr: abbr || key.slice(0, 2) });
    };
    (pack && pack.pitchRoles || []).forEach((row) => {
      if (!row || row.state === "idle") return;
      push(row.code, row.state, row.abbr);
    });
    (pack && pack.pitch || []).forEach((dot) => {
      if (!dot || dot.state === "idle" || !dot.code) return;
      let code = String(dot.code).toUpperCase();
      if (code.endsWith("_R") || code.endsWith("_WB")) {
        code = code.replace(/_R$/, "").replace(/_WB$/, "");
      }
      push(code, dot.state, dot.abbr || dot.label);
    });
    if (pack && pack.player && pack.player.primaryPosition) {
      push(pack.player.primaryPosition, "primary");
    }
    // Primary roles first so they claim the best slot.
    roles.sort((a, b) => (a.state === "primary" ? 0 : 1) - (b.state === "primary" ? 0 : 1));
    return roles;
  }

  function formationDots() {
    const layout = FORMATION_LAYOUTS[selectedFormation] || FORMATION_LAYOUTS["4-2-3-1"];
    const roles = playerPitchRoles();
    const claimed = new Set();
    const dots = layout.map((slot) => ({
      ...slot,
      state: "idle",
      label: "",
    }));

    roles.forEach((role) => {
      let bestIdx = -1;
      let bestScore = -1;
      dots.forEach((slot, idx) => {
        if (claimed.has(idx) || !codesMatch(slot.code, role.code)) return;
        // Prefer exact code, then side-ish x for L/R roles.
        let score = slot.code === role.code ? 40 : 20;
        const code = role.code;
        if (code.includes("LEFT") && slot.x < 40) score += 10;
        if (code.includes("RIGHT") && slot.x > 60) score += 10;
        if (!code.includes("LEFT") && !code.includes("RIGHT") && slot.x > 35 && slot.x < 65) score += 8;
        if (score > bestScore) {
          bestScore = score;
          bestIdx = idx;
        }
      });
      if (bestIdx < 0) return;
      claimed.add(bestIdx);
      dots[bestIdx].state = role.state;
      dots[bestIdx].label = role.abbr || dots[bestIdx].abbr;
    });
    return dots;
  }

  function setFormation(key) {
    if (!FORMATION_KEYS.includes(key)) return;
    selectedFormation = key;
    try { localStorage.setItem("mfp-formation", key); } catch (_) { /* ignore */ }
    renderEditor();
    renderPreview();
  }

  function formationPickerHtml(compact) {
    const cls = compact ? "mfp-formation-pills mfp-formation-pills--compact" : "mfp-formation-pills";
    return `<div class="${cls}" role="group" aria-label="Formation">
      ${FORMATION_KEYS.map((key) => `
        <button type="button" class="mfp-formation-pill ${selectedFormation === key ? "is-active" : ""}" data-formation="${escapeAttr(key)}">${escapeHtml(key)}</button>
      `).join("")}
    </div>`;
  }

  function identityScoreBarProfiles() {
    // Full positional set on the identity footer — not just top 3.
    const selected = selectedProfiles().filter((p) => p && p.title);
    const withScores = selected
      .filter((p) => p.scorePct != null && !Number.isNaN(Number(p.scorePct)))
      .slice()
      .sort((a, b) => Number(b.scorePct) - Number(a.scorePct));
    if (!withScores.length) return selected;
    const seen = new Set(withScores.map((p) => p.apiName || p.title));
    const unscored = selected.filter((p) => !seen.has(p.apiName || p.title));
    return withScores.concat(unscored);
  }

  function identityScoreBarHtml() {
    const rows = identityScoreBarProfiles();
    if (!rows.length) {
      return `<div class="mfp-id__score-bar mfp-id__score-bar--empty" aria-label="PV profile scores">
        <div class="mfp-id__score-col">
          <div class="mfp-id__score-pct">—</div>
          <div class="mfp-id__score-meta">
            <span class="mfp-id__score-name">NO PROFILE SCORES</span>
          </div>
        </div>
      </div>`;
    }
    const cols = rows.map((prof, i) => {
      const pct = prof.scorePct != null ? `${Math.round(Number(prof.scorePct))}%` : "—";
      const title = String(prof.title || prof.label || "PROFILE").toUpperCase();
      const lead = i === 0 ? " is-lead" : "";
      return `<div class="mfp-id__score-col${lead}">
        <div class="mfp-id__score-pct">${escapeHtml(pct)}</div>
        <div class="mfp-id__score-meta">
          <span class="mfp-id__score-index">${String(i + 1).padStart(2, "0")}</span>
          <span class="mfp-id__score-name">${escapeHtml(title)}</span>
        </div>
      </div>`;
    }).join("");
    return `<div class="mfp-id__score-bar" style="grid-template-columns: repeat(${rows.length}, minmax(0, 1fr))" aria-label="PV profile scores">${cols}</div>`;
  }

  function identitySlideHtml() {
    const p = pack.player;
    const c = pack.careerStats || {};
    const ghost = String(p.lastName || p.name || "").toUpperCase();
    const stats = [
      ["games", "GAMES"],
      ["starts", "STARTS"],
      ["minutes", "MINS"],
      ["goals", "GOALS"],
      ["assists", "ASSISTS"],
    ];
    const statsTitle = String(c.title || "CAREER").trim() || "CAREER";
    const statsHtml = stats.map(([key, label]) => `
      <div class="mfp-id__stat">
        <div class="mfp-id__stat-num">${escapeHtml(displayStat(c[key]))}</div>
        <div class="mfp-id__stat-label">${label}</div>
      </div>`).join("");

    const bio = [
      ["AGE", p.ageLine],
      ["HEIGHT", p.height],
      ["FOOT", p.foot],
      ["CLUB", p.club],
      ["TYPE", p.transferType],
    ].map(([label, value]) => `
      <div class="mfp-id__bio-row">
        <div class="mfp-id__bio-label">${label}</div>
        <div class="mfp-id__bio-value">${escapeHtml(displayStat(value))}</div>
      </div>`).join("");

    const dots = formationDots().map((dot) => {
      const cls = dot.state === "primary" ? "is-primary" : dot.state === "secondary" ? "is-secondary" : "";
      const label = (dot.state === "primary" || dot.state === "secondary")
        ? escapeHtml(dot.label || dot.abbr)
        : "";
      return `<div class="mfp-pitch__dot ${cls}" style="left:${dot.x}%;top:${dot.y}%">${label}</div>`;
    }).join("");

    return `<div class="mfp-slide mfp-slide--identity" data-slide="identity">
      <div class="mfp-slide__atmosphere" aria-hidden="true"></div>
      <div class="mfp-slide__ghost" aria-hidden="true">${escapeHtml(ghost)}</div>
      <div class="mfp-slide__rail"></div>
      ${photoHtml("identity", "mfp-slide__photo--hero")}
      <div class="mfp-slide__photo-frame" aria-hidden="true"></div>
      ${brandHtml("light")}
      <div class="mfp-id__left">
        <p class="mfp-id__kicker">Identity</p>
        <p class="mfp-id__first">${escapeHtml(p.firstName)}</p>
        <p class="mfp-id__last">${escapeHtml(p.lastName)}</p>
        <p class="mfp-id__positions"><span>${escapeHtml(p.positionLine)}</span></p>
        <div class="mfp-id__bio">${bio}</div>
      </div>
      <div class="mfp-id__right">
        <div class="mfp-id__stats-card">
          <div class="mfp-id__stats">
            <div class="mfp-id__stat mfp-id__stat--title">
              <div class="mfp-id__stats-title">${escapeHtml(statsTitle)}</div>
            </div>
            ${statsHtml}
          </div>
        </div>
        <div class="mfp-pitch-wrap">
          <div class="mfp-pitch-head">
            <p class="mfp-pitch-label">Position map · ${escapeHtml(selectedFormation)}</p>
          </div>
          <div class="mfp-pitch">${dots}</div>
        </div>
      </div>
      ${identityScoreBarHtml()}
    </div>`;
  }

  function scoreBarHtml(profiles, limit) {
    const rows = (profiles || []).slice(0, limit || 6);
    if (!rows.length) return `<p class="mfp-data__empty">No scores</p>`;
    return rows.map((row) => {
      const pct = Math.max(0, Math.min(100, Math.round(Number(row.scorePct) || 0)));
      const tone = pct >= 55 ? "is-hot" : pct >= 40 ? "is-mid" : "is-cold";
      return `<div class="mfp-data__bar ${tone}">
        <div class="mfp-data__bar-top">
          <span class="mfp-data__bar-name">${escapeHtml(row.title || row.label || "PROFILE")}</span>
          <span class="mfp-data__bar-pct">${pct}%</span>
        </div>
        <div class="mfp-data__bar-track"><span style="width:${pct}%"></span></div>
      </div>`;
    }).join("");
  }

  function radarAxisLabel(title) {
    return String(title || "")
      .replace(/^WIDE\s+/i, "")
      .replace(/^CENTRAL\s+/i, "")
      .trim() || "PROFILE";
  }

  function profileScoreMap(profiles) {
    const map = new Map();
    (profiles || []).forEach((row) => {
      const key = String(row.apiName || row.title || row.label || "").toUpperCase();
      if (!key) return;
      map.set(key, Math.max(0, Math.min(100, Number(row.scorePct) || 0)));
      const titleKey = String(row.title || row.label || "").toUpperCase();
      if (titleKey) map.set(titleKey, Math.max(0, Math.min(100, Number(row.scorePct) || 0)));
    });
    return map;
  }

  function radarPolygonPoints(values, cx, cy, radius) {
    const n = values.length;
    if (!n) return "";
    return values.map((v, i) => {
      const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / n;
      const r = radius * (Math.max(0, Math.min(100, v)) / 100);
      return `${(cx + Math.cos(angle) * r).toFixed(1)},${(cy + Math.sin(angle) * r).toFixed(1)}`;
    }).join(" ");
  }

  function dataRadarHtml(primaryProfiles, overlayProfiles, primaryLabel, overlayLabel) {
    const axes = (primaryProfiles || []).slice(0, 6);
    if (axes.length < 3) return `<p class="mfp-data__empty">Need 3+ profiles for radar</p>`;

    const size = 460;
    const cx = size / 2;
    const cy = size / 2;
    const radius = 152;
    const labelR = 192;
    const rings = [0.25, 0.5, 0.75, 1];
    const primaryVals = axes.map((row) => Math.max(0, Math.min(100, Number(row.scorePct) || 0)));
    const overlayMap = profileScoreMap(overlayProfiles);
    const hasOverlay = Boolean(overlayProfiles && overlayProfiles.length);
    const overlayVals = hasOverlay
      ? axes.map((row) => {
          const keys = [
            String(row.apiName || "").toUpperCase(),
            String(row.title || "").toUpperCase(),
            String(row.label || "").toUpperCase(),
          ];
          for (const key of keys) {
            if (key && overlayMap.has(key)) return overlayMap.get(key);
          }
          return 0;
        })
      : [];

    const grid = rings.map((t) => {
      const pts = Array.from({ length: axes.length }, (_, i) => {
        const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / axes.length;
        return `${(cx + Math.cos(angle) * radius * t).toFixed(1)},${(cy + Math.sin(angle) * radius * t).toFixed(1)}`;
      }).join(" ");
      return `<polygon points="${pts}" class="mfp-radar__ring" />`;
    }).join("");

    const spokes = axes.map((_, i) => {
      const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / axes.length;
      const x = (cx + Math.cos(angle) * radius).toFixed(1);
      const y = (cy + Math.sin(angle) * radius).toFixed(1);
      return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" class="mfp-radar__spoke" />`;
    }).join("");

    const labels = axes.map((row, i) => {
      const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / axes.length;
      const x = cx + Math.cos(angle) * labelR;
      const y = cy + Math.sin(angle) * labelR;
      const anchor = Math.abs(Math.cos(angle)) < 0.2 ? "middle" : Math.cos(angle) > 0 ? "start" : "end";
      const short = radarAxisLabel(row.title || row.label);
      const pct = Math.round(primaryVals[i]);
      return `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${anchor}" class="mfp-radar__label">
        <tspan x="${x.toFixed(1)}" dy="-0.2em">${escapeHtml(short)}</tspan>
        <tspan x="${x.toFixed(1)}" dy="1.15em" class="mfp-radar__label-pct">${pct}%</tspan>
      </text>`;
    }).join("");

    const primaryPts = radarPolygonPoints(primaryVals, cx, cy, radius);
    const overlayPts = hasOverlay ? radarPolygonPoints(overlayVals, cx, cy, radius) : "";

    return `<div class="mfp-radar">
      <svg class="mfp-radar__svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="Profile radar">
        ${grid}
        ${spokes}
        ${hasOverlay ? `<polygon points="${overlayPts}" class="mfp-radar__poly mfp-radar__poly--overlay" />` : ""}
        <polygon points="${primaryPts}" class="mfp-radar__poly mfp-radar__poly--primary" />
        ${labels}
      </svg>
      <div class="mfp-radar__legend">
        <span class="mfp-radar__legend-item mfp-radar__legend-item--primary">${escapeHtml(primaryLabel || "Current")}</span>
        ${hasOverlay ? `<span class="mfp-radar__legend-item mfp-radar__legend-item--overlay">${escapeHtml(overlayLabel || "Compare")}</span>` : ""}
      </div>
    </div>`;
  }

  function dataSlideHtml() {
    const p = pack.player || {};
    const d = pack.dataSummary || {};
    const bestStats = (d.bestStats || []).slice(0, 5);
    const worstStats = (d.worstStats || []).slice(0, 5);
    const byPos = (d.byPosition || []).slice(0, 2);
    const bySeason = (d.bySeason || []).slice(0, 3);
    const primaryProfiles = d.profiles || [];
    const overlayPos = byPos.length > 1 ? byPos[1] : null;
    const radarPrimaryLabel = [
      byPos[0]?.label || p.positionLine || "Primary",
      byPos[0]?.season || d.season,
    ].filter(Boolean).join(" · ");
    const radarOverlayLabel = overlayPos
      ? [overlayPos.label, overlayPos.season].filter(Boolean).join(" · ")
      : "";

    const bestHtml = bestStats.map((row, i) => `
      <div class="mfp-data__chip mfp-data__chip--best mfp-data__chip--stat">
        <span class="mfp-data__chip-idx">${String(i + 1).padStart(2, "0")}</span>
        <span class="mfp-data__chip-name">${escapeHtml(row.label || "STAT")}</span>
        <span class="mfp-data__chip-pct">${escapeHtml(row.valueLabel || "—")}<small>P90</small></span>
      </div>`).join("") || `<p class="mfp-data__empty">No P90 stats yet</p>`;

    const worstHtml = worstStats.map((row, i) => `
      <div class="mfp-data__chip mfp-data__chip--worst mfp-data__chip--stat">
        <span class="mfp-data__chip-idx">${String(i + 1).padStart(2, "0")}</span>
        <span class="mfp-data__chip-name">${escapeHtml(row.label || "STAT")}</span>
        <span class="mfp-data__chip-pct">${escapeHtml(row.valueLabel || "—")}<small>P90</small></span>
      </div>`).join("") || `<p class="mfp-data__empty">—</p>`;

    const posHtml = byPos.map((pos) => `
      <article class="mfp-data__panel">
        <header class="mfp-data__panel-head">
          <div>
            <p class="mfp-data__panel-kicker">Position</p>
            <h3 class="mfp-data__panel-title">${escapeHtml(pos.label || pos.code)}</h3>
          </div>
          <div class="mfp-data__panel-meta">
            ${pos.season ? `<span>${escapeHtml(String(pos.season))}</span>` : ""}
            ${pos.minutes != null ? `<span>${escapeHtml(String(pos.minutes))}′</span>` : ""}
          </div>
        </header>
        <div class="mfp-data__bars mfp-data__bars--compact">${scoreBarHtml(pos.profiles, 4)}</div>
      </article>`).join("") || `<p class="mfp-data__empty">No position splits yet</p>`;

    const seasonHtml = bySeason.map((row) => `
      <article class="mfp-data__season">
        <div class="mfp-data__season-top">
          <div>
            <p class="mfp-data__season-label">${escapeHtml(row.season || row.label)}</p>
            <p class="mfp-data__season-club">${escapeHtml([row.club, row.competition].filter(Boolean).join(" · "))}</p>
          </div>
          <div class="mfp-data__season-score">
            <span class="mfp-data__season-avg">${row.avgPct != null ? `${row.avgPct}%` : "—"}</span>
            <span class="mfp-data__season-avg-label">AVG</span>
          </div>
        </div>
        <p class="mfp-data__season-top-line">Top · ${escapeHtml(row.topTitle || "—")} · ${row.topPct != null ? `${row.topPct}%` : "—"}</p>
        <div class="mfp-data__bars mfp-data__bars--compact">${scoreBarHtml(row.profiles, 4)}</div>
      </article>`).join("") || `<p class="mfp-data__empty">No multi-season scores yet</p>`;

    return `<div class="mfp-slide mfp-slide--data" data-slide="data">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--data" aria-hidden="true"></div>
      <div class="mfp-data">
        <header class="mfp-data__header">
          <div>
            <p class="mfp-data__kicker">Data summary</p>
            <h2 class="mfp-data__name">${escapeHtml(p.firstName || "")} <span>${escapeHtml(p.lastName || p.name || "")}</span></h2>
            <p class="mfp-data__sub">${escapeHtml([p.positionLine, d.season, d.league].filter(Boolean).join(" · "))}</p>
          </div>
          <p class="mfp-data__footnote">${escapeHtml(d.note || "Impect P90 player scores")}</p>
        </header>
        <div class="mfp-data__grid">
          <section class="mfp-data__col mfp-data__col--radar">
            <h3 class="mfp-data__block-title">Profile shape</h3>
            ${dataRadarHtml(primaryProfiles, overlayPos && overlayPos.profiles, radarPrimaryLabel, radarOverlayLabel)}
          </section>
          <section class="mfp-data__col mfp-data__col--highlights">
            <div class="mfp-data__block">
              <h3 class="mfp-data__block-title">Best stats</h3>
              <div class="mfp-data__chips">${bestHtml}</div>
            </div>
            <div class="mfp-data__block">
              <h3 class="mfp-data__block-title">Room to grow</h3>
              <div class="mfp-data__chips">${worstHtml}</div>
            </div>
          </section>
          <section class="mfp-data__col mfp-data__col--seasons">
            <h3 class="mfp-data__block-title">Across seasons</h3>
            <div class="mfp-data__season-grid">${seasonHtml}</div>
          </section>
          <section class="mfp-data__col mfp-data__col--positions">
            <h3 class="mfp-data__block-title">By position</h3>
            <div class="mfp-data__pos-grid">${posHtml}</div>
          </section>
        </div>
      </div>
    </div>`;
  }

  function profileSlideHtml(prof, idx) {
    const bullets = (prof.bullets || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("");
    const key = `profile-${idx}`;
    const pct = prof.scorePct != null ? `${Math.round(Number(prof.scorePct))}%` : "";
    return `<div class="mfp-slide mfp-slide--profile" data-slide="${escapeAttr(key)}">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--profile" aria-hidden="true"></div>
      <div class="mfp-profile__ghost" aria-hidden="true">${escapeHtml(String(prof.title || "").split(" ").pop() || "")}</div>
      ${photoHtml(key, "mfp-slide__photo--profile")}
      <div class="mfp-profile__veil" aria-hidden="true"></div>
      ${brandHtml("light")}
      <div class="mfp-profile__copy">
        ${pct ? `<p class="mfp-profile__fit">${escapeHtml(pct)} FIT</p>` : ""}
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
    let n = 1;
    parts.push(`<div class="mfp-slide-wrap"><p class="mfp-slide-caption">${String(n).padStart(2, "0")} · Identity</p>${identitySlideHtml()}</div>`);
    n += 1;
    if (includeDataSlide && pack.dataSummary) {
      parts.push(`<div class="mfp-slide-wrap"><p class="mfp-slide-caption">${String(n).padStart(2, "0")} · Data summary</p>${dataSlideHtml()}</div>`);
      n += 1;
    }
    selectedProfiles().forEach((prof) => {
      const idx = pack.profiles.indexOf(prof);
      parts.push(`<div class="mfp-slide-wrap"><p class="mfp-slide-caption">${String(n).padStart(2, "0")} · ${escapeHtml(prof.title)}</p>${profileSlideHtml(prof, idx)}</div>`);
      n += 1;
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
    const dataUrl = await readFileAsDataUrl(file);
    const slot = ensureSlidePhoto(activeSlideKey);
    slot.cutout = dataUrl;
    slot.photoId = null;
    slot.soft = false;
    clearCutoutBtn.disabled = false;
    renderPhotoGrid();
    renderPreview();
    setStatus(`Uploaded cutout applied to ${slideLabel(activeSlideKey)}.`);
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

  async function captureSlideHtml2Canvas(slideEl) {
    // Fallback only — Playwright WYSIWYG is the real export path.
    const cloneHost = document.createElement("div");
    cloneHost.style.cssText = "position:fixed;left:-10000px;top:0;width:1920px;height:1080px;opacity:1;pointer-events:none;z-index:-1;";
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
    if (!pack) return;
    downloadBtn.disabled = true;
    setStatus("Rendering PNG pack in Chrome…");
    try {
      const slides = Array.from(preview.querySelectorAll(".mfp-slide"));
      if (!slides.length) throw new Error("No slides to export");

      const folder = slugify(pack.player.name || "player");
      const filenames = slides.map((slide, i) => {
        const key = slide.getAttribute("data-slide") || `slide-${i + 1}`;
        if (key === "identity") return "01-identity";
        if (key === "data") return `${String(i + 1).padStart(2, "0")}-data-summary`;
        return `${String(i + 1).padStart(2, "0")}-${slugify(slideLabel(key))}`;
      });

      if (window.PortValeWysiwygExport && typeof window.PortValeWysiwygExport.captureSlideHtmlPages === "function") {
        const packHtml = await window.PortValeWysiwygExport.captureSlideHtmlPages({
          slides,
          forceNativeSize: true,
          nativeWidth: SLIDE_W,
          nativeHeight: SLIDE_H,
          background: "#12100e",
          stripClasses: [],
          onProgress: (msg) => setStatus(msg),
        });
        // Override filenames to our meeting-pack naming.
        packHtml.htmlFilenames = filenames;
        setStatus("Screenshotting slides in Chrome…");
        const result = await window.PortValeWysiwygExport.downloadPngZip({
          ...packHtml,
          filename: `${folder}-meeting-front-pages.zip`,
          documentTitle: folder,
          opponentName: pack.player.name || "player",
          endpoint: "/api/wysiwyg-export-png-zip",
        });
        setStatus(
          result.savedPath
            ? `Downloaded ${result.pageCount} sharp PNGs · ${result.sizeMb} MB · also on Desktop`
            : `Downloaded ${result.pageCount} sharp PNGs · ${result.sizeMb} MB`
        );
        return;
      }

      // Fallback if WYSIWYG helper failed to load.
      if (typeof html2canvas !== "function" || typeof JSZip !== "function") {
        throw new Error("Export libraries failed to load — hard refresh and try again.");
      }
      setStatus("Chrome export unavailable — using browser fallback…");
      const zip = new JSZip();
      for (let i = 0; i < slides.length; i += 1) {
        const blob = await captureSlideHtml2Canvas(slides[i]);
        if (!blob) throw new Error("Capture failed — try a different photo");
        zip.file(`${folder}/${filenames[i]}.png`, blob);
        setStatus(`Rendering PNG pack… ${i + 1}/${slides.length}`);
      }
      const out = await zip.generateAsync({ type: "blob" });
      downloadBlob(out, `${folder}-meeting-front-pages.zip`);
      setStatus(`Downloaded ${slides.length} PNGs (fallback).`);
    } catch (err) {
      setStatus(err.message || "Export failed", true);
    } finally {
      downloadBtn.disabled = false;
    }
  }

  playerSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchPlayers(playerSearch.value), 280);
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
    const targetBtn = event.target.closest("button[data-slide-target]");
    if (targetBtn) {
      activeSlideKey = targetBtn.getAttribute("data-slide-target") || "identity";
      renderPhotoGrid();
      setStatus(`Assigning photos to ${slideLabel(activeSlideKey)}.`);
      return;
    }
    const btn = event.target.closest("button[data-photo-id]");
    if (!btn) return;
    const photoId = btn.getAttribute("data-photo-id");
    assignPhotoToActive(photoId);
    cutoutInput.value = "";
    const web = webPhotoById(photoId);
    renderPhotoGrid();
    renderPreview();
    setStatus(`Set ${slideLabel(activeSlideKey)} photo → ${web ? web.label : "selected"}.`);
  });

  refreshBtn.addEventListener("click", () => {
    if (!selectedPlayerId) return;
    const code = pack && pack.player && pack.player.primaryPosition;
    const iter = pack && pack.player && pack.player.iterationId;
    loadPack(selectedPlayerId, code || undefined, {
      keepPhotos: Boolean(webPhotos.length),
      iterationId: iter,
    });
  });

  refreshPhotosBtn.addEventListener("click", () => loadWebPhotos());

  downloadBtn.addEventListener("click", downloadPack);

  cutoutInput.addEventListener("change", () => {
    const file = cutoutInput.files && cutoutInput.files[0];
    if (cutoutFileName) {
      cutoutFileName.textContent = file
        ? file.name
        : "PNG / JPG — applies to selected slide";
    }
    applyCutoutFile(file).catch((err) => setStatus(err.message, true));
  });

  clearCutoutBtn.addEventListener("click", () => {
    const slot = ensureSlidePhoto(activeSlideKey);
    slot.cutout = null;
    cutoutInput.value = "";
    if (cutoutFileName) cutoutFileName.textContent = "PNG / JPG — applies to selected slide";
    clearCutoutBtn.disabled = !Object.values(slidePhotos).some((s) => s.cutout);
    if (pack) {
      renderPhotoGrid();
      renderPreview();
    }
    setStatus(`Cleared cutout on ${slideLabel(activeSlideKey)}.`);
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
