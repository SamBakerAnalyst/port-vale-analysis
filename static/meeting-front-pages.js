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
  const valeBar = document.getElementById("valeBar");
  const valeComps = document.getElementById("valeComps");
  const valeMatchesEl = document.getElementById("valeMatches");
  const matchPackBar = document.getElementById("matchPackBar");
  const matchPackPills = document.getElementById("matchPackPills");
  const playerSearchPanel = document.getElementById("playerSearchPanel");
  const cutoutLabel = document.getElementById("cutoutLabel");

  const cutoutFileName = document.getElementById("cutoutFileName");
  const MATCH_PACK_DEFAULTS = [
    { id: "pre-match", label: "Pre-Match" },
    { id: "post-match", label: "Post-Match" },
    { id: "set-plays", label: "Set Plays" },
  ];

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
  let valeMatches = [];
  let valeCompetitions = [];
  let valeActiveComp = "League";
  let valeActiveMatchId = null;
  let valePhotos = [];
  let valeNextStart = null;
  let valeTotal = 0;
  let valeLoading = false;
  let photoSource = "vale";
  /** @type {Record<string, {photoId: string|null, cutout: string|null, soft: boolean}>} */
  let slidePhotos = {};
  let activeSlideKey = "identity";
  let selectedFormation = localStorage.getItem("mfp-formation") || "4-2-3-1";
  if (!FORMATION_KEYS.includes(selectedFormation)) selectedFormation = "4-2-3-1";
  let includeDataSlide = localStorage.getItem("mfp-data-slide") !== "0";
  function normalizeMode(mode) {
    if (mode === "dossier") return "dossier";
    if (mode === "match") return "match";
    return "meeting";
  }
  let appMode = normalizeMode(localStorage.getItem("mfp-mode"));
  let matchPack = null;
  let matchPackId = localStorage.getItem("mfp-match-pack") || "pre-match";
  if (!MATCH_PACK_DEFAULTS.some((row) => row.id === matchPackId)) matchPackId = "pre-match";
  let dossier = null;
  let dossierDirty = false;
  let dossierSaveTimer = null;
  const saveDossierBtn = document.getElementById("saveDossierBtn");
  const cutoutPanel = document.getElementById("cutoutPanel");

  const DOSSIER_SECTIONS = [
    {
      key: "bio",
      title: "Biographical",
      fields: [
        { key: "name", label: "Name", kind: "input" },
        { key: "dob", label: "DOB", kind: "input" },
        { key: "age", label: "Age", kind: "input" },
        { key: "nationality", label: "Nationality", kind: "input" },
        { key: "height", label: "Height", kind: "input" },
        { key: "weight", label: "Weight", kind: "input" },
        { key: "foot", label: "Preferred foot", kind: "input" },
        { key: "birthPlace", label: "Birth place", kind: "input" },
        { key: "languages", label: "Languages", kind: "input" },
        { key: "positions", label: "Position(s)", kind: "input" },
      ],
    },
    {
      key: "player",
      title: "Player",
      fields: [
        { key: "backgroundNarrative", label: "Background information (narrative)", kind: "textarea", rows: 7 },
        { key: "playingHistory", label: "Playing history", kind: "textarea", rows: 5 },
        { key: "technicalDataReport", label: "Technical data report", kind: "textarea", rows: 6 },
        { key: "benchmarkPvfc", label: "Benchmark v PVFC", kind: "textarea", rows: 4 },
        { key: "scoutingSummary", label: "Scouting summary", kind: "textarea", rows: 5 },
      ],
    },
    {
      key: "personal",
      title: "Personal / Character",
      fields: [
        { key: "character", label: "Character", kind: "textarea", rows: 4 },
        { key: "maritalStatus", label: "Marital status", kind: "input" },
        { key: "otherFamily", label: "Other family / relationships", kind: "textarea", rows: 3 },
        { key: "references", label: "References", kind: "textarea", rows: 3 },
        { key: "socialMedia", label: "Social media profile", kind: "textarea", rows: 3 },
        { key: "locationFamily", label: "Location / family situation", kind: "textarea", rows: 3 },
      ],
    },
    {
      key: "negotiations",
      title: "Negotiations",
      fields: [
        { key: "transferType", label: "Transfer type", kind: "input" },
        { key: "contractStatus", label: "Contract status", kind: "input" },
        { key: "atClubSince", label: "At club since", kind: "input" },
        { key: "workPermit", label: "Work permit", kind: "input" },
        { key: "agentDetails", label: "Agent details", kind: "textarea", rows: 3 },
        { key: "currentSalary", label: "Current salary", kind: "input" },
        { key: "salaryExpectations", label: "Salary expectations / contributions", kind: "textarea", rows: 3 },
      ],
    },
    {
      key: "medical",
      title: "Medical assessment & recommendation",
      fields: [
        { key: "availabilityHistory", label: "Availability history", kind: "textarea", rows: 3 },
        { key: "physicalDataReport", label: "Physical data report", kind: "textarea", rows: 4 },
        { key: "benchmarkPvfc", label: "Benchmark v PVFC", kind: "textarea", rows: 3 },
        { key: "riskAssessment", label: "Medical risk assessment", kind: "textarea", rows: 4 },
        { key: "recommendations", label: "Medical recommendations for integration / adaptation", kind: "textarea", rows: 4 },
      ],
    },
    {
      key: "summary",
      title: "Summary & recruitment team recommendation",
      fields: [
        { key: "keyStrengths", label: "Key strengths", kind: "textarea", rows: 4 },
        { key: "areasToDevelop", label: "Areas to develop → IDPs", kind: "textarea", rows: 4 },
        { key: "thingsToConsider", label: "Things to consider", kind: "textarea", rows: 4 },
        { key: "overallRecommendation", label: "Overall recommendation for adaptation & tactical fit", kind: "textarea", rows: 5 },
      ],
    },
    {
      key: "scoutOverview",
      title: "Scout overview",
      fields: [
        { key: "totalReports", label: "Total reports", kind: "input" },
        { key: "liveReports", label: "Live reports", kind: "input" },
        { key: "videoReports", label: "Video reports", kind: "input" },
        { key: "averageGrade", label: "Average grade", kind: "input" },
        { key: "reportsNotes", label: "Report notes / log", kind: "textarea", rows: 5 },
      ],
    },
  ];

  function friendlyNetworkError(err, fallback) {
    const raw = (err && err.message) || "";
    if (/failed to fetch/i.test(raw)) return fallback;
    return raw || fallback;
  }

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

  function hasMatchSlides() {
    return appMode === "match" && matchPack && Array.isArray(matchPack.slides);
  }

  function hasAssignableSlides() {
    return Boolean(pack) || hasMatchSlides();
  }

  function slideKeyList() {
    if (hasMatchSlides()) {
      return matchPack.slides.map((slide) => slide.id);
    }
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
    if (hasMatchSlides()) {
      const slide = matchPack.slides.find((row) => row.id === key);
      return (slide && slide.title) || key;
    }
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

  function catalogPhotoById(id) {
    return valePhotos.find((p) => p.id === id) || webPhotos.find((p) => p.id === id) || null;
  }

  function webPhotoById(id) {
    return catalogPhotoById(id);
  }

  function photoSrc(slideKey) {
    const slot = ensureSlidePhoto(slideKey || activeSlideKey);
    if (slot.cutout) return slot.cutout;
    const web = webPhotoById(slot.photoId);
    if (web) return web.proxyUrl || web.url;
    if (appMode === "match") return "";
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

  async function loadWebPhotos(options = {}) {
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
      if (options.switchTab || !valePhotos.length) {
        autoAssignDistinctPhotos();
      }
      if (options.switchTab) {
        photoSource = "web";
        document.querySelectorAll(".mfp-source").forEach((btn) => {
          btn.classList.toggle("is-active", btn.getAttribute("data-photo-source") === "web");
        });
      }
      renderPhotoGrid();
      renderPreview();
      if (options.switchTab || photoSource === "web") {
        const assigned = photoSlideKeys().filter((k) => photoSrc(k)).length;
        setStatus(
          webPhotos.length
            ? `Found ${webPhotos.length} photos — assigned across ${assigned} slides. Click a slide target, then a photo.`
            : "No web photos found — upload a cutout or try Find web photos again."
        );
      }
    } catch (err) {
      setStatus(err.message || "Photo search failed", true);
    } finally {
      refreshPhotosBtn.disabled = !pack;
    }
  }

  function visiblePhotoList() {
    return photoSource === "vale" ? valePhotos : webPhotos;
  }

  function valeMatchesForComp() {
    return valeMatches.filter((row) => row.competition === valeActiveComp);
  }

  function activeValeMatch() {
    return valeMatches.find((row) => row.id === valeActiveMatchId) || null;
  }

  function renderValeBar() {
    if (!valeBar || !valeComps || !valeMatchesEl) return;
    if (photoSource !== "vale" || !valeMatches.length) {
      valeBar.hidden = true;
      return;
    }
    valeBar.hidden = false;
    const comps = valeCompetitions.length
      ? valeCompetitions.map((row) => row.name)
      : [...new Set(valeMatches.map((row) => row.competition))];
    valeComps.innerHTML = comps.map((name) => `
      <button type="button" class="mfp-vale-comp ${name === valeActiveComp ? "is-active" : ""}" data-vale-comp="${escapeAttr(name)}">${escapeHtml(name)}</button>
    `).join("");
    const rows = valeMatchesForComp();
    valeMatchesEl.innerHTML = rows.map((row) => {
      const thumb = row.thumbUrl
        ? `<img src="${escapeAttr("/api/meeting-front-pages/image-proxy?url=" + encodeURIComponent(row.thumbUrl))}" alt="" />`
        : `<div class="mfp-vale-match__ph">PVFC</div>`;
      return `<button type="button" class="mfp-vale-match ${row.id === valeActiveMatchId ? "is-active" : ""}" data-vale-match="${escapeAttr(row.id)}" title="${escapeAttr(row.name)}">
        ${thumb}
        <span>${escapeHtml(row.name)}</span>
      </button>`;
    }).join("");
  }

  async function loadValeGalleries() {
    try {
      const res = await fetch("/api/meeting-front-pages/vale-photos/matches");
      if (!res.ok) throw new Error("Through a Lens unavailable");
      const data = await res.json();
      valeMatches = Array.isArray(data.matches) ? data.matches : [];
      valeCompetitions = Array.isArray(data.competitions) ? data.competitions : [];
      if (valeCompetitions.some((row) => row.name === "League")) valeActiveComp = "League";
      else if (valeCompetitions[0]) valeActiveComp = valeCompetitions[0].name;
      if ((appMode === "meeting" || appMode === "match") && valeMatches.length) {
        photoPanel.hidden = false;
        renderValeBar();
        if (photoSource === "vale") renderPhotoGrid();
        if (appMode === "match" && !matchPack) {
          setStatus("Pick a 26/27 game — Pre-match, Post-match and Set plays templates load with both badges.");
        }
      }
    } catch (_err) {
      valeMatches = [];
    }
  }

  async function loadValePhotos(matchId, options = {}) {
    const match = valeMatches.find((row) => row.id === matchId);
    if (!match) return;
    const append = Boolean(options.append);
    const start = append && valeNextStart ? valeNextStart : 1;
    valeLoading = true;
    valeActiveMatchId = matchId;
    renderValeBar();
    if (!append) {
      valePhotos = [];
      valeNextStart = null;
      valeTotal = 0;
      setStatus(`Loading ${match.name} photos from Through a Lens…`);
    }
    renderPhotoGrid();
    try {
      const qs = new URLSearchParams({
        nodeId: match.id,
        match: match.name,
        kind: match.kind || "action",
        start: String(start),
        count: "40",
      });
      if (match.albumKey) qs.set("albumKey", match.albumKey);
      const res = await fetch(`/api/meeting-front-pages/vale-photos?${qs.toString()}`);
      if (!res.ok) throw new Error("Could not load match photos");
      const data = await res.json();
      const incoming = Array.isArray(data.photos) ? data.photos : [];
      valePhotos = append ? valePhotos.concat(incoming) : incoming;
      valeNextStart = data.nextStart || null;
      valeTotal = Number(data.total || valePhotos.length);
      photoPanel.hidden = appMode === "dossier";
      renderPhotoGrid();
      const how = hasMatchSlides()
        ? "Drag a picture onto a slide, or click a slide then a photo. Titles are editable."
        : "Click a slide, then a picture — or open Match slides to build a fixture deck.";
      setStatus(
        valePhotos.length
          ? `${match.name} — ${valePhotos.length}${valeTotal ? ` of ${valeTotal}` : ""} Through a Lens photos. ${how}`
          : `No photos in ${match.name} yet.`
      );
    } catch (err) {
      setStatus(friendlyNetworkError(err, "Could not load Through a Lens photos"), true);
      renderPhotoGrid();
    } finally {
      valeLoading = false;
    }
  }

  function renderPhotoGrid() {
    const photos = visiblePhotoList();
    const showPanel = appMode !== "dossier" && (valeMatches.length || webPhotos.length || photos.length);
    if (photoPanel) photoPanel.hidden = !showPanel;
    renderValeBar();
    if (!photoGrid) return;
    if (!showPanel) {
      photoGrid.innerHTML = "";
      return;
    }
    const activeId = (slidePhotos[activeSlideKey] || {}).photoId;
    const targets = hasAssignableSlides()
      ? photoSlideKeys().map((key) => `
      <button type="button" class="mfp-slide-target ${key === activeSlideKey ? "is-active" : ""}" data-slide-target="${escapeAttr(key)}">
        ${escapeHtml(slideLabel(key))}
      </button>`).join("")
      : "";
    if (photoSource === "vale") {
      const match = activeValeMatch();
      photoMeta.innerHTML = match
        ? `<a href="${escapeAttr(match.galleryUrl)}" target="_blank" rel="noopener">${escapeHtml(match.name)}</a> on Through a Lens`
        : "Pick a 26/27 game";
    } else {
      photoMeta.innerHTML = `${webPhotos.length} web options · click a slide, then a photo`;
    }
    const emptyVale = photoSource === "vale" && !photos.length
      ? `<p class="mfp-hint mfp-photo-assign-hint">${valeLoading ? "Loading match photos…" : "Pick a game above — League, cups, friendlies and headshots from Through a Lens."}</p>`
      : "";
    const emptyWeb = photoSource === "web" && !photos.length
      ? `<p class="mfp-hint mfp-photo-assign-hint">${pack ? "No web photos yet — try Find web photos." : "Load a player to search the web, or pick a Through a Lens game."}</p>`
      : "";
    const more = photoSource === "vale" && valeNextStart
      ? `<button type="button" class="mfp-btn mfp-btn--ghost mfp-btn--small mfp-photo-more" id="valeMoreBtn">Load more photos</button>`
      : "";
    const assignHint = hasAssignableSlides()
      ? `<p class="mfp-hint mfp-photo-assign-hint">${hasMatchSlides() ? "Drag onto a slide, or assigning to" : "Assigning to"} <strong>${escapeHtml(slideLabel(activeSlideKey))}</strong> — each slide can use a different picture.</p>`
      : "";
    photoGrid.innerHTML = `
      ${targets ? `<div class="mfp-slide-targets">${targets}</div>` : ""}
      ${assignHint}
      ${emptyVale}${emptyWeb}
      <div class="mfp-photo-grid__cards">
        ${photos.map((photo) => {
          const usedOn = hasAssignableSlides() ? photoSlideKeys().filter((k) => (slidePhotos[k] || {}).photoId === photo.id) : [];
          const usedTag = usedOn.length ? usedOn.map(slideLabel).join(", ") : "";
          return `<button type="button" class="mfp-photo-card ${photo.id === activeId ? "is-selected" : ""}" data-photo-id="${escapeAttr(photo.id)}" title="${escapeAttr(photo.label)}" ${hasAssignableSlides() ? 'draggable="true"' : ""}>
            <img src="${escapeAttr(photo.proxyThumbUrl || photo.proxyUrl || photo.url)}" alt="" loading="lazy" draggable="false" />
            <span class="mfp-photo-card__tag">${escapeHtml(photo.source === "through-a-lens" ? "vale" : photo.source)}${usedTag ? ` · ${escapeHtml(usedTag)}` : ""}</span>
          </button>`;
        }).join("")}
      </div>
      ${more}`;
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
      if (keepPhotos && (webPhotos.length || valePhotos.length || valeMatches.length)) renderPhotoGrid();
      downloadBtn.disabled = false;
      refreshBtn.disabled = false;
      refreshPhotosBtn.disabled = false;
      if (saveDossierBtn) saveDossierBtn.disabled = false;
      if (appMode === "dossier") {
        await loadDossier({ keepStatus: true });
      } else if (keepPhotos) {
        const seasonBit = [pack.player.league, pack.player.season].filter(Boolean).join(" ");
        const posBit = pack.player.positionLine || positionCode || "";
        setStatus(`Loaded ${[posBit, seasonBit].filter(Boolean).join(" · ")}`);
        renderPhotoGrid();
      } else {
        setStatus(`Loaded ${pack.player.name} — pick a Through a Lens game or find web photos.`);
        renderPhotoGrid();
        loadWebPhotos({ switchTab: false });
      }
    } catch (err) {
      setStatus(err.message || "Could not load player", true);
    }
  }

  function applyModeChrome() {
    document.querySelectorAll(".mfp-mode").forEach((btn) => {
      btn.classList.toggle("is-active", btn.getAttribute("data-mode") === appMode);
    });
    document.body.classList.toggle("mfp-mode-dossier", appMode === "dossier");
    document.body.classList.toggle("mfp-mode-meeting", appMode === "meeting");
    document.body.classList.toggle("mfp-mode-match", appMode === "match");
    if (playerSearchPanel) playerSearchPanel.hidden = appMode === "match";
    if (matchPackBar) matchPackBar.hidden = appMode !== "match";
    if (appMode === "match") renderMatchPackPills();
    if (cutoutPanel) cutoutPanel.hidden = appMode === "dossier";
    if (cutoutLabel) {
      cutoutLabel.innerHTML = appMode === "match"
        ? 'Own photo <span class="mfp-label__optional">optional</span>'
        : 'Own cutout <span class="mfp-label__optional">optional</span>';
    }
    if (photoPanel) {
      const showPhotos = appMode !== "dossier" && (valeMatches.length || webPhotos.length || valePhotos.length);
      photoPanel.hidden = !showPhotos;
      if (showPhotos) renderPhotoGrid();
    }
    if (downloadBtn) {
      downloadBtn.hidden = appMode === "dossier";
      downloadBtn.disabled = appMode === "match" ? !matchPack : !pack;
    }
    if (refreshPhotosBtn) refreshPhotosBtn.hidden = appMode === "dossier" || appMode === "match";
    if (refreshBtn) refreshBtn.hidden = appMode === "match";
    if (saveDossierBtn) {
      saveDossierBtn.hidden = appMode !== "dossier";
      saveDossierBtn.disabled = !selectedPlayerId;
    }
  }

  async function setAppMode(mode) {
    appMode = normalizeMode(mode);
    try { localStorage.setItem("mfp-mode", appMode); } catch (_) { /* ignore */ }
    applyModeChrome();
    if (appMode === "dossier") {
      if (pack) await loadDossier();
      else {
        workspace.hidden = true;
        renderEditor();
        renderPreview();
      }
      return;
    }
    if (appMode === "match") {
      const match = activeValeMatch();
      if (!matchPack && match) {
        await loadMatchPack(match);
        return;
      }
      workspace.hidden = !matchPack;
      if (matchPack) {
        if (!(matchPack.slides || []).some((s) => s.id === activeSlideKey)) {
          activeSlideKey = (matchPack.slides[0] && matchPack.slides[0].id) || "cover";
        }
        downloadBtn.disabled = false;
      } else {
        setStatus("Pick a Through a Lens game — Pre-match, Post-match and Set plays templates load with both badges.");
      }
      renderEditor();
      renderPreview();
      if (valeMatches.length || valePhotos.length) {
        photoPanel.hidden = false;
        renderPhotoGrid();
      }
      return;
    }
    if (!pack) {
      workspace.hidden = true;
      renderEditor();
      renderPreview();
      return;
    }
    workspace.hidden = false;
    renderEditor();
    renderPreview();
    if (webPhotos.length || valePhotos.length || valeMatches.length) {
      photoPanel.hidden = false;
      renderPhotoGrid();
    }
  }

  function renderMatchPackPills() {
    if (!matchPackPills) return;
    const packs = (matchPack && matchPack.packs) || MATCH_PACK_DEFAULTS;
    matchPackPills.innerHTML = packs.map((row) => `
      <button type="button" class="mfp-pill ${row.id === matchPackId ? "is-active" : ""}" data-match-pack="${escapeAttr(row.id)}">${escapeHtml(row.label)}</button>
    `).join("");
  }

  async function loadMatchPack(match, options = {}) {
    if (!match || !match.name) return;
    const packId = options.packId || matchPackId || "pre-match";
    const keepPhotos = Boolean(options.keepPhotos);
    const previous = keepPhotos ? { ...slidePhotos } : null;
    const extras = keepPhotos && matchPack && Array.isArray(matchPack.slides)
      ? matchPack.slides.filter((row) => row && (row.kind === "stat" || row.kind === "stats" || String(row.id || "").startsWith("topic-custom-")))
      : [];
    setStatus(`Building ${packId.replace(/-/g, " ")} slides vs ${match.name}…`);
    try {
      const qs = new URLSearchParams({
        name: match.name,
        competition: match.competition || "",
        pack: packId,
      });
      const res = await fetch(`/api/meeting-front-pages/match-pack?${qs.toString()}`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Could not build match slides (${res.status})`);
      }
      matchPack = await res.json();
      matchPackId = (matchPack.pack && matchPack.pack.id) || packId;
      try { localStorage.setItem("mfp-match-pack", matchPackId); } catch (_) { /* ignore */ }
      if (extras.length) {
        const seen = new Set((matchPack.slides || []).map((row) => row.id));
        extras.forEach((row) => {
          if (row && row.id && !seen.has(row.id)) matchPack.slides.push(row);
        });
      }
      if (previous) slidePhotos = previous;
      else {
        slidePhotos = {};
        activeSlideKey = "cover";
      }
      (matchPack.slides || []).forEach((slide) => ensureSlidePhoto(slide.id));
      if (!(matchPack.slides || []).some((s) => s.id === activeSlideKey)) {
        activeSlideKey = (matchPack.slides[0] && matchPack.slides[0].id) || "cover";
      }
      workspace.hidden = false;
      downloadBtn.disabled = false;
      renderMatchPackPills();
      renderEditor();
      renderPreview();
      renderPhotoGrid();
      setStatus(`${match.name} — drag photos onto slides. Click a title to edit it.`);
    } catch (err) {
      setStatus(friendlyNetworkError(err, "Could not build match slides"), true);
    }
  }

  async function loadDossier(options = {}) {
    if (!selectedPlayerId || !pack) return;
    if (!options.keepStatus) setStatus("Loading dossier…");
    try {
      const qs = new URLSearchParams({ playerId: String(selectedPlayerId) });
      if (pack.player && pack.player.iterationId) qs.set("iterationId", String(pack.player.iterationId));
      if (pack.player && pack.player.primaryPosition) qs.set("position", String(pack.player.primaryPosition));
      const res = await fetch(`/api/meeting-front-pages/dossier?${qs.toString()}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Dossier failed (${res.status})`);
      }
      dossier = await res.json();
      dossierDirty = false;
      renderDossierEditor();
      renderDossierPreview();
      if (saveDossierBtn) {
        saveDossierBtn.disabled = false;
        saveDossierBtn.textContent = dossier.saved ? "Save dossier" : "Save dossier";
      }
      if (!options.keepStatus) {
        setStatus(dossier.saved ? "Dossier loaded (saved notes found)" : "Dossier loaded — blanks are ready for scout notes");
      }
    } catch (err) {
      setStatus(err.message || "Could not load dossier", true);
    }
  }

  function scheduleDossierSave() {
    dossierDirty = true;
    if (saveDossierBtn) saveDossierBtn.textContent = "Save dossier*";
    if (dossierSaveTimer) clearTimeout(dossierSaveTimer);
    dossierSaveTimer = setTimeout(() => {
      saveDossier().catch(() => {});
    }, 900);
  }

  async function saveDossier() {
    if (!selectedPlayerId || !dossier) return;
    if (saveDossierBtn) {
      saveDossierBtn.disabled = true;
      saveDossierBtn.textContent = "Saving…";
    }
    try {
      const res = await fetch(`/api/meeting-front-pages/dossier?playerId=${encodeURIComponent(selectedPlayerId)}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dossier),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Save failed (${res.status})`);
      }
      dossier = await res.json();
      dossierDirty = false;
      renderDossierPreview();
      setStatus("Dossier saved");
      if (saveDossierBtn) saveDossierBtn.textContent = "Save dossier";
    } catch (err) {
      setStatus(err.message || "Could not save dossier", true);
      if (saveDossierBtn) saveDossierBtn.textContent = "Save dossier*";
    } finally {
      if (saveDossierBtn) saveDossierBtn.disabled = !selectedPlayerId;
    }
  }

  function dossierFieldValue(sectionKey, fieldKey) {
    const section = dossier && dossier[sectionKey];
    if (!section || typeof section !== "object") return "";
    return section[fieldKey] || "";
  }

  function renderDossierEditor() {
    if (!dossier) {
      editor.innerHTML = `<p class="mfp-hint">Load a player to open the dossier.</p>`;
      return;
    }
    const src = dossier.source || {};
    editor.innerHTML = `
      <h2>Player dossier</h2>
      <p class="mfp-hint">Six-page deck (cover → scout). Cover + narrative auto-draft from Impect/FBref when blank — edit anytime. Appearance history merges Impect seasons with deeper FBref rows.</p>
      <div class="mfp-dossier-meta">
        <div><span>Club</span>${escapeHtml(src.club || "—")}</div>
        <div><span>Role</span>${escapeHtml(src.positionLine || "—")}</div>
        <div><span>Season</span>${escapeHtml([src.league, src.season].filter(Boolean).join(" · ") || "—")}</div>
        <div><span>Market</span>${escapeHtml(src.marketValue || "—")}</div>
      </div>
      ${DOSSIER_SECTIONS.map((section) => `
        <section class="mfp-dossier-section" data-section="${escapeAttr(section.key)}">
          <h2>${escapeHtml(section.title)}</h2>
          ${section.fields.map((field) => {
            const val = dossierFieldValue(section.key, field.key);
            if (field.kind === "textarea") {
              return `<div class="mfp-field">
                <label>${escapeHtml(field.label)}</label>
                <textarea data-dossier-section="${escapeAttr(section.key)}" data-dossier-field="${escapeAttr(field.key)}" rows="${field.rows || 4}" placeholder="Add notes…">${escapeHtml(val)}</textarea>
              </div>`;
            }
            return `<div class="mfp-field">
              <label>${escapeHtml(field.label)}</label>
              <input data-dossier-section="${escapeAttr(section.key)}" data-dossier-field="${escapeAttr(field.key)}" value="${escapeAttr(val)}" placeholder="—" />
            </div>`;
          }).join("")}
        </section>
      `).join("")}
    `;
    editor.querySelectorAll("[data-dossier-field]").forEach((el) => {
      const handler = () => {
        const section = el.getAttribute("data-dossier-section");
        const field = el.getAttribute("data-dossier-field");
        if (!dossier[section]) dossier[section] = {};
        dossier[section][field] = el.value;
        renderDossierPreview();
        scheduleDossierSave();
      };
      el.addEventListener("input", handler);
    });
  }

  function dossierVal(value, emptyLabel) {
    const text = String(value || "").trim();
    return {
      text: text || (emptyLabel || "—"),
      empty: !text,
    };
  }

  function dossierCell(value, emptyLabel) {
    const v = dossierVal(value, emptyLabel);
    return `<span class="${v.empty ? "is-empty" : ""}">${escapeHtml(v.text)}</span>`;
  }

  function dossierBulletList(text, tone) {
    const lines = String(text || "")
      .split(/\n+/)
      .map((s) => s.replace(/^[-•*]\s*/, "").trim())
      .filter(Boolean);
    if (!lines.length) {
      return `<li class="is-empty">Add notes in the editor</li>`;
    }
    return lines.map((line) => `<li class="${tone || ""}">${escapeHtml(line)}</li>`).join("");
  }

  function dossierBrandHtml() {
    return `<div class="mfp-slide__brand mfp-slide__brand--light">
      <img src="${BADGE_URL}" alt="Port Vale FC" />
      <div class="mfp-slide__brand-text">Port Vale FC<span>Recruitment dossier</span></div>
    </div>`;
  }

  function dossierPitchHtml() {
    if (!pack) return `<p class="mfp-dossier-empty">Load a player pack for the pitch map</p>`;
    const dots = formationDots().map((dot) => {
      const cls = dot.state === "primary" ? "is-primary" : dot.state === "secondary" ? "is-secondary" : "";
      const label = (dot.state === "primary" || dot.state === "secondary")
        ? escapeHtml(dot.label || dot.abbr)
        : "";
      return `<div class="mfp-pitch__dot ${cls}" style="left:${dot.x}%;top:${dot.y}%">${label}</div>`;
    }).join("");
    return `<div class="mfp-pitch-wrap mfp-dossier-pitch">
      <div class="mfp-pitch-head">
        <p class="mfp-pitch-label">Position map · ${escapeHtml(selectedFormation)}</p>
      </div>
      <div class="mfp-pitch">${dots}</div>
    </div>`;
  }

  function dossierClubListHtml(rows) {
    const clubs = [];
    const seen = new Set();
    (rows || []).forEach((row) => {
      const club = String(row.club || "").trim();
      if (!club) return;
      const key = club.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      const seasons = (rows || [])
        .filter((r) => String(r.club || "").trim().toLowerCase() === key)
        .map((r) => r.season)
        .filter(Boolean);
      const range = seasons.length ? [...new Set(seasons)].slice(0, 4).join(" · ") : "";
      clubs.push({ club, range });
    });
    if (!clubs.length) return `<p class="mfp-dossier-empty">No club history in Impect seasons yet</p>`;
    return clubs.slice(0, 8).map((row) => `
      <div class="mfp-dossier-club">
        <span class="mfp-dossier-club__name">${escapeHtml(row.club)}</span>
        <span class="mfp-dossier-club__years">${escapeHtml(row.range || "—")}</span>
      </div>`).join("");
  }

  function dossierMinutesChartHtml(rows) {
    const withMins = (rows || [])
      .filter((r) => r && r.minutes != null && Number(r.minutes) > 0)
      .slice()
      .sort((a, b) => {
        const ya = String(a.season || "");
        const yb = String(b.season || "");
        return ya.localeCompare(yb);
      })
      .slice(-10);
    if (!withMins.length) {
      return `<p class="mfp-dossier-empty">Minutes chart fills when season scores are available</p>`;
    }
    const max = Math.max(...withMins.map((r) => Number(r.minutes) || 0), 1);
    return `<div class="mfp-dossier-mins" aria-label="League minutes">
      ${withMins.map((row) => {
        const mins = Number(row.minutes) || 0;
        const pct = Math.max(8, Math.round((mins / max) * 100));
        return `<div class="mfp-dossier-mins__col">
          <div class="mfp-dossier-mins__bar" style="height:${pct}%">
            <span>${escapeHtml(String(Math.round(mins)))}</span>
          </div>
          <p class="mfp-dossier-mins__label">${escapeHtml(row.season || "—")}</p>
          <p class="mfp-dossier-mins__club">${escapeHtml(row.club || row.competition || "")}</p>
        </div>`;
      }).join("")}
    </div>`;
  }

  function dossierCoverSlideHtml() {
    const bio = dossier.bio || {};
    const src = dossier.source || {};
    const impect = dossier.impect || {};
    const career = impect.careerStats || (pack && pack.careerStats) || {};
    const p = (pack && pack.player) || {};
    const photo = src.photoUrl || p.photoUrl || "";
    const ghost = String(bio.name || p.lastName || p.name || "PLAYER").split(" ").pop() || "PLAYER";
    const blurb = String(impect.coverBlurb || "").trim()
      || String((dossier.player && dossier.player.backgroundNarrative) || "").split(/\n\n/)[0]
      || "Recruitment dossier ready for scout notes.";
    const best = ((impect.dataSummary || {}).bestStats || [])[0];
    const rows = impect.appearanceRows || [];
    const seasonSpan = (() => {
      const seasons = [...new Set(rows.map((r) => r.season).filter(Boolean))];
      if (seasons.length >= 2) return `${seasons[seasons.length - 1]} → ${seasons[0]}`;
      return seasons[0] || src.season || "";
    })();

    return `<div class="mfp-slide mfp-slide--dossier mfp-slide--dossier-cover" data-slide="dossier-cover">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--cover" aria-hidden="true"></div>
      <div class="mfp-dossier-cover__glow" aria-hidden="true"></div>
      <div class="mfp-dossier-cover__ghost" aria-hidden="true">${escapeHtml(ghost.toUpperCase())}</div>
      ${dossierBrandHtml()}
      <div class="mfp-dossier-cover">
        <div class="mfp-dossier-cover__copy">
          <p class="mfp-dossier-cover__eyebrow">Port Vale recruitment · Player dossier</p>
          <p class="mfp-dossier-cover__first">${escapeHtml(p.firstName || (bio.name || "").split(" ")[0] || "")}</p>
          <h2 class="mfp-dossier-cover__last">${escapeHtml(p.lastName || ghost)}</h2>
          <p class="mfp-dossier-cover__role">${escapeHtml([bio.positions || src.positionLine, src.club, src.league].filter(Boolean).join(" · "))}</p>
          <p class="mfp-dossier-cover__blurb">${escapeHtml(blurb)}</p>
          <div class="mfp-dossier-cover__pills">
            <div><span>Age</span><strong>${escapeHtml(displayStat(bio.age || p.ageLine))}</strong></div>
            <div><span>Foot</span><strong>${escapeHtml(displayStat(bio.foot || p.foot))}</strong></div>
            <div><span>Height</span><strong>${escapeHtml(displayStat(bio.height || p.height))}</strong></div>
            <div><span>Sample</span><strong>${escapeHtml(seasonSpan || "—")}</strong></div>
          </div>
          <div class="mfp-dossier-cover__stats">
            <div><span>Games</span><strong>${escapeHtml(displayStat(career.games))}</strong></div>
            <div><span>Mins</span><strong>${escapeHtml(displayStat(career.minutes))}</strong></div>
            <div><span>Goals</span><strong>${escapeHtml(displayStat(career.goals))}</strong></div>
            <div><span>Assists</span><strong>${escapeHtml(displayStat(career.assists))}</strong></div>
          </div>
          ${best ? `<p class="mfp-dossier-cover__flag">Impect flag · ${escapeHtml(best.label || "Stat")} · ${escapeHtml(best.valueLabel || "—")} P90</p>` : ""}
        </div>
        <div class="mfp-dossier-cover__media">
          ${photo
            ? `<div class="mfp-dossier-cover__photo"><img src="${escapeAttr(photo)}" alt="" /></div>`
            : `<div class="mfp-dossier-cover__photo is-empty">Photo</div>`}
          <div class="mfp-dossier-cover__frame" aria-hidden="true"></div>
        </div>
      </div>
    </div>`;
  }

  function dossierOverviewSlideHtml() {
    const bio = dossier.bio || {};
    const personal = dossier.personal || {};
    const neg = dossier.negotiations || {};
    const src = dossier.source || {};
    const impect = dossier.impect || {};
    const rows = impect.appearanceRows || [];
    const photo = src.photoUrl || (pack && pack.player && pack.player.photoUrl) || "";
    const infoRows = [
      ["Name", bio.name],
      ["Age", bio.age || bio.dob],
      ["Position(s)", bio.positions || src.positionLine],
      ["Leading foot", bio.foot],
      ["Height", bio.height],
      ["Birth place", bio.birthPlace],
      ["Nationality", bio.nationality],
      ["Languages", bio.languages],
      ["Club", src.club],
      ["Division", [src.league, src.season].filter(Boolean).join(" · ")],
      ["Agent", neg.agentDetails],
      ["Contract", neg.contractStatus],
      ["At club since", neg.atClubSince],
      ["Work permit", neg.workPermit],
    ].map(([label, value]) => {
      const v = dossierVal(value);
      return `<tr><th>${escapeHtml(label)}</th><td class="${v.empty ? "is-empty" : ""}">${escapeHtml(v.text)}</td></tr>`;
    }).join("");

    return `<div class="mfp-slide mfp-slide--dossier mfp-slide--dossier-overview" data-slide="dossier-overview">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--data" aria-hidden="true"></div>
      <div class="mfp-dossier-cover__ghost mfp-dossier-cover__ghost--soft" aria-hidden="true">${escapeHtml(String(bio.name || "PLAYER").split(" ").pop() || "PLAYER")}</div>
      ${dossierBrandHtml()}
      <div class="mfp-dossier-page">
        <header class="mfp-dossier-page__head">
          <div>
            <p class="mfp-dossier-page__kicker">Player overview</p>
            <h2>${escapeHtml(bio.name || (pack && pack.player && pack.player.name) || "Player")}</h2>
            <p class="mfp-dossier-page__sub">${escapeHtml([src.positionLine, src.club, src.league, src.season].filter(Boolean).join(" · "))}</p>
          </div>
          ${photo ? `<img class="mfp-dossier-page__photo" src="${escapeAttr(photo)}" alt="" />` : ""}
        </header>
        <div class="mfp-dossier-overview">
          <section class="mfp-dossier-panel">
            <h3>Player information</h3>
            <table class="mfp-dossier-table">${infoRows}</table>
          </section>
          <div class="mfp-dossier-overview__side">
            <section class="mfp-dossier-panel">
              <h3>Relationships</h3>
              <div class="mfp-dossier-kv">
                <div><span>Marital status</span>${dossierCell(personal.maritalStatus, "— editable")}</div>
                <div><span>Other family</span>${dossierCell(personal.otherFamily || personal.locationFamily, "— editable")}</div>
              </div>
            </section>
            <section class="mfp-dossier-panel mfp-dossier-panel--pitch">
              <h3>Tactical map</h3>
              ${dossierPitchHtml()}
            </section>
          </div>
          <section class="mfp-dossier-panel mfp-dossier-panel--wide">
            <h3>Previous clubs</h3>
            <div class="mfp-dossier-clubs">${dossierClubListHtml(rows)}</div>
          </section>
        </div>
      </div>
    </div>`;
  }

  function dossierBackgroundSlideHtml() {
    const player = dossier.player || {};
    const src = dossier.source || {};
    const rows = (dossier.impect && dossier.impect.appearanceRows) || [];
    const narrative = dossierVal(player.backgroundNarrative, "Write the career pathway narrative here — academy, breakthroughs, moves.");
    const autoNote = (dossier.impect && dossier.impect.autoNarrative)
      && String(player.backgroundNarrative || "").trim() === String(dossier.impect.autoNarrative || "").trim();
    const historyRows = rows.slice(0, 14).map((row) => `
      <tr>
        <td>${escapeHtml(row.season || "—")}</td>
        <td>${escapeHtml(row.club || "—")}</td>
        <td>${escapeHtml(row.competition || "—")}</td>
        <td>${row.minutes != null ? escapeHtml(String(row.minutes)) + "′" : "—"}</td>
        <td class="mfp-dossier-src">${escapeHtml(String(row.source || "").replace("+", " · ") || "—")}</td>
      </tr>`).join("") || `<tr><td colspan="5" class="is-empty">No season rows yet</td></tr>`;

    return `<div class="mfp-slide mfp-slide--dossier mfp-slide--dossier-background" data-slide="dossier-background">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--data" aria-hidden="true"></div>
      ${dossierBrandHtml()}
      <div class="mfp-dossier-page">
        <header class="mfp-dossier-page__head">
          <div>
            <p class="mfp-dossier-page__kicker">Background &amp; pathway</p>
            <h2>Background information</h2>
            <p class="mfp-dossier-page__sub">${escapeHtml(src.club || "")}${autoNote ? " · Auto-drafted from available data" : ""}</p>
          </div>
        </header>
        <div class="mfp-dossier-split">
          <section class="mfp-dossier-panel">
            <h3>Narrative ${autoNote ? "<small>auto</small>" : ""}</h3>
            <p class="mfp-dossier-narrative ${narrative.empty ? "is-empty" : ""}">${escapeHtml(narrative.text)}</p>
            <h3 class="mfp-dossier-subhead">Scouting summary</h3>
            <p class="mfp-dossier-narrative ${String(player.scoutingSummary || "").trim() ? "" : "is-empty"}">${escapeHtml(String(player.scoutingSummary || "").trim() || "Add a short scouting summary")}</p>
          </section>
          <section class="mfp-dossier-panel">
            <h3>Season pathway <small>Impect + FBref</small></h3>
            <table class="mfp-dossier-table mfp-dossier-table--grid">
              <thead><tr><th>Season</th><th>Club</th><th>Competition</th><th>Mins</th><th>Src</th></tr></thead>
              <tbody>${historyRows}</tbody>
            </table>
          </section>
        </div>
      </div>
    </div>`;
  }

  function dossierAppearancesSlideHtml() {
    const rows = (dossier.impect && dossier.impect.appearanceRows) || [];
    const career = (dossier.impect && dossier.impect.careerStats) || (pack && pack.careerStats) || {};
    const sources = [...new Set(rows.map((r) => r.source).filter(Boolean))];
    const tableRows = rows.slice(0, 18).map((row) => `
      <tr>
        <td>${escapeHtml(row.season || "—")}</td>
        <td>${escapeHtml(row.club || "—")}</td>
        <td>${escapeHtml(row.competition || "—")}</td>
        <td>${row.apps != null ? escapeHtml(String(row.apps)) : "—"}</td>
        <td>${row.starts != null ? escapeHtml(String(row.starts)) : "—"}</td>
        <td>${row.minutes != null ? escapeHtml(String(row.minutes)) : "—"}</td>
        <td>${row.goals != null ? escapeHtml(String(row.goals)) : "—"}</td>
        <td>${row.assists != null ? escapeHtml(String(row.assists)) : "—"}</td>
        <td>${row.avgPct != null ? escapeHtml(String(row.avgPct)) + "%" : "—"}</td>
        <td class="mfp-dossier-src">${escapeHtml(String(row.source || "impect").replace("+", " · "))}</td>
      </tr>`).join("") || `<tr><td colspan="10" class="is-empty">No appearance seasons yet</td></tr>`;

    return `<div class="mfp-slide mfp-slide--dossier mfp-slide--dossier-apps" data-slide="dossier-apps">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--data" aria-hidden="true"></div>
      ${dossierBrandHtml()}
      <div class="mfp-dossier-page">
        <header class="mfp-dossier-page__head">
          <div>
            <p class="mfp-dossier-page__kicker">League appearance history</p>
            <h2>Appearance history</h2>
            <p class="mfp-dossier-page__sub">${escapeHtml(career.title || "Career sample")} · ${rows.length} rows · ${escapeHtml(sources.join(" + ") || "impect")}</p>
          </div>
          <div class="mfp-dossier-career-pills">
            <div><span>Games</span><strong>${escapeHtml(displayStat(career.games))}</strong></div>
            <div><span>Mins</span><strong>${escapeHtml(displayStat(career.minutes))}</strong></div>
            <div><span>Goals</span><strong>${escapeHtml(displayStat(career.goals))}</strong></div>
            <div><span>Assists</span><strong>${escapeHtml(displayStat(career.assists))}</strong></div>
          </div>
        </header>
        <div class="mfp-dossier-apps">
          <section class="mfp-dossier-panel">
            <table class="mfp-dossier-table mfp-dossier-table--grid mfp-dossier-table--dense">
              <thead>
                <tr>
                  <th>Season</th><th>Club</th><th>Competition</th><th>Apps</th><th>Starts</th><th>Mins</th><th>G</th><th>A</th><th>Fit</th><th>Src</th>
                </tr>
              </thead>
              <tbody>${tableRows}</tbody>
            </table>
          </section>
          <section class="mfp-dossier-panel">
            <h3>Minutes by season</h3>
            ${dossierMinutesChartHtml(rows)}
          </section>
        </div>
      </div>
    </div>`;
  }

  function dossierPerformanceSlideHtml() {
    const src = dossier.source || {};
    const summary = (dossier.impect && dossier.impect.dataSummary) || (pack && pack.dataSummary) || {};
    const profiles = summary.profiles || (dossier.impect && dossier.impect.profiles) || (pack && pack.profiles) || [];
    const bestStats = (summary.bestStats || []).slice(0, 5);
    const worstStats = (summary.worstStats || []).slice(0, 5);
    const byPos = (summary.byPosition || []).slice(0, 2);
    const overlayPos = byPos.length > 1 ? byPos[1] : null;
    const bestHtml = bestStats.map((row, i) => `
      <div class="mfp-data__chip mfp-data__chip--best mfp-data__chip--stat">
        <span class="mfp-data__chip-idx">${String(i + 1).padStart(2, "0")}</span>
        <span class="mfp-data__chip-name">${escapeHtml(row.label || "STAT")}</span>
        <span class="mfp-data__chip-pct">${escapeHtml(row.valueLabel || "—")}<small>P90</small></span>
      </div>`).join("") || `<p class="mfp-dossier-empty">No P90s yet — pick a season with minutes</p>`;
    const worstHtml = worstStats.map((row, i) => `
      <div class="mfp-data__chip mfp-data__chip--worst mfp-data__chip--stat">
        <span class="mfp-data__chip-idx">${String(i + 1).padStart(2, "0")}</span>
        <span class="mfp-data__chip-name">${escapeHtml(row.label || "STAT")}</span>
        <span class="mfp-data__chip-pct">${escapeHtml(row.valueLabel || "—")}<small>P90</small></span>
      </div>`).join("") || `<p class="mfp-dossier-empty">—</p>`;

    return `<div class="mfp-slide mfp-slide--dossier mfp-slide--dossier-perf" data-slide="dossier-perf">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--data" aria-hidden="true"></div>
      ${dossierBrandHtml()}
      <div class="mfp-dossier-page">
        <header class="mfp-dossier-page__head">
          <div>
            <p class="mfp-dossier-page__kicker">Performance data</p>
            <h2>Impect performance</h2>
            <p class="mfp-dossier-page__sub">${escapeHtml([src.positionLine, src.league, src.season].filter(Boolean).join(" · "))}</p>
          </div>
          <p class="mfp-dossier-page__note">${escapeHtml(summary.note || "Statistics P90 where appropriate · Impect")}</p>
        </header>
        <div class="mfp-dossier-perf">
          <section class="mfp-dossier-panel mfp-dossier-panel--radar">
            <h3>Profile shape</h3>
            ${dataRadarHtml(
              profiles,
              overlayPos && overlayPos.profiles,
              byPos[0] ? [byPos[0].label, byPos[0].season].filter(Boolean).join(" · ") : "Primary",
              overlayPos ? [overlayPos.label, overlayPos.season].filter(Boolean).join(" · ") : ""
            )}
          </section>
          <div class="mfp-dossier-perf__stats">
            <section class="mfp-dossier-panel">
              <h3>Best stats</h3>
              <div class="mfp-data__chips">${bestHtml}</div>
            </section>
            <section class="mfp-dossier-panel">
              <h3>Room to grow</h3>
              <div class="mfp-data__chips">${worstHtml}</div>
            </section>
          </div>
        </div>
      </div>
    </div>`;
  }

  function dossierScoutSlideHtml() {
    const summary = dossier.summary || {};
    const scout = dossier.scoutOverview || {};
    const medical = dossier.medical || {};
    const player = dossier.player || {};
    const photo = (dossier.source && dossier.source.photoUrl) || (pack && pack.player && pack.player.photoUrl) || "";

    return `<div class="mfp-slide mfp-slide--dossier mfp-slide--dossier-scout" data-slide="dossier-scout">
      <div class="mfp-slide__atmosphere mfp-slide__atmosphere--data" aria-hidden="true"></div>
      ${dossierBrandHtml()}
      <div class="mfp-dossier-page">
        <header class="mfp-dossier-page__head">
          <div>
            <p class="mfp-dossier-page__kicker">Scout overview</p>
            <h2>Recruitment judgment</h2>
          </div>
          <div class="mfp-dossier-scout-stats">
            <div><span>Total</span><strong>${dossierCell(scout.totalReports, "—")}</strong></div>
            <div><span>Live</span><strong>${dossierCell(scout.liveReports, "—")}</strong></div>
            <div><span>Video</span><strong>${dossierCell(scout.videoReports, "—")}</strong></div>
            <div><span>Avg grade</span><strong>${dossierCell(scout.averageGrade, "—")}</strong></div>
          </div>
        </header>
        <div class="mfp-dossier-scout">
          <section class="mfp-dossier-panel">
            <h3 class="is-good">Strengths</h3>
            <ul class="mfp-dossier-list">${dossierBulletList(summary.keyStrengths, "is-good")}</ul>
            <h3 class="mfp-dossier-subhead">Technical seed</h3>
            <p class="mfp-dossier-narrative ${String(player.technicalDataReport || "").trim() ? "" : "is-empty"}">${escapeHtml(String(player.technicalDataReport || "").trim() || "Impect technical seed appears once seasons load")}</p>
          </section>
          <section class="mfp-dossier-panel">
            <h3 class="is-warn">Things to consider</h3>
            <ul class="mfp-dossier-list">${dossierBulletList(summary.thingsToConsider || summary.areasToDevelop, "is-warn")}</ul>
            <h3 class="mfp-dossier-subhead">Overall recommendation</h3>
            <p class="mfp-dossier-narrative ${String(summary.overallRecommendation || "").trim() ? "" : "is-empty"}">${escapeHtml(String(summary.overallRecommendation || "").trim() || "Add the recruitment recommendation")}</p>
            <h3 class="mfp-dossier-subhead">Medical risk</h3>
            <p class="mfp-dossier-narrative ${String(medical.riskAssessment || "").trim() ? "" : "is-empty"}">${escapeHtml(String(medical.riskAssessment || "").trim() || "Medical assessment still blank")}</p>
          </section>
          ${photo ? `<img class="mfp-dossier-scout__photo" src="${escapeAttr(photo)}" alt="" />` : ""}
        </div>
      </div>
    </div>`;
  }

  function renderDossierPreview() {
    if (!dossier) {
      preview.innerHTML = "";
      return;
    }
    const parts = [
      ["00 · Cover", dossierCoverSlideHtml()],
      ["01 · Player overview", dossierOverviewSlideHtml()],
      ["02 · Background", dossierBackgroundSlideHtml()],
      ["03 · Appearances", dossierAppearancesSlideHtml()],
      ["04 · Performance", dossierPerformanceSlideHtml()],
      ["05 · Scout overview", dossierScoutSlideHtml()],
    ];
    preview.innerHTML = parts.map(([caption, html]) =>
      `<div class="mfp-slide-wrap"><p class="mfp-slide-caption">${escapeHtml(caption)}</p>${html}</div>`
    ).join("");
    requestAnimationFrame(scaleSlides);
  }

  function matchSlideById(id) {
    return (matchPack && matchPack.slides || []).find((row) => row.id === id) || null;
  }

  function matchSlideKindLabel(slide, index) {
    if (slide.kind === "cover") return "Cover";
    if (slide.kind === "stat") return "Stat";
    if (slide.kind === "stats") return "Stats board";
    return `Slide ${String(index).padStart(2, "0")}`;
  }

  function emptyStatRow(index) {
    return {
      id: `row-${Date.now()}-${index || 0}-${Math.random().toString(36).slice(2, 5)}`,
      title: "Write the stat",
      statValue: "0",
      verdict: "positive",
    };
  }

  function newMatchTopicSlide() {
    return {
      id: `topic-custom-${Date.now()}`,
      kind: "topic",
      title: "New slide",
      subtitle: (matchPack.match && matchPack.match.fixture) || "",
      kicker: (matchPack.pack && matchPack.pack.label) || "Match",
      selected: true,
    };
  }

  function newMatchStatSlide() {
    return {
      id: `stat-${Date.now()}`,
      kind: "stat",
      title: "Write the stat",
      statValue: "0",
      subtitle: (matchPack.match && matchPack.match.fixture) || "",
      kicker: "Stat",
      verdict: "positive",
      selected: true,
    };
  }

  function newMatchStatsSlide() {
    return {
      id: `stats-${Date.now()}`,
      kind: "stats",
      title: "Key numbers",
      subtitle: (matchPack.match && matchPack.match.fixture) || "",
      kicker: "Stats",
      stats: [emptyStatRow(1), emptyStatRow(2), emptyStatRow(3)],
      selected: true,
    };
  }

  function isPositiveStat(slide) {
    return !slide || slide.verdict !== "negative";
  }

  function statGridCols(count) {
    if (count <= 1) return 1;
    if (count === 2 || count === 4) return 2;
    return 3;
  }

  function htmlWithBreaks(value) {
    return escapeHtml(value).replace(/\n/g, "<br>");
  }

  function matchEditorSlideCard(slide, i) {
    const rows = Array.isArray(slide.stats) ? slide.stats : [];
    const statsRows = slide.kind === "stats"
      ? rows.map((row, idx) => `
          <div class="mfp-stat-edit" data-stat-row="${escapeAttr(row.id)}">
            <div class="mfp-stat-edit__head">Stat ${idx + 1}</div>
            <div class="mfp-field"><label>What is the stat</label><input data-row-title value="${escapeAttr(row.title || "")}" /></div>
            <div class="mfp-field"><label>Number / result</label><input data-row-value value="${escapeAttr(row.statValue || "")}" placeholder="e.g. 12 or 3/11" /></div>
            <div class="mfp-verdict" role="group" aria-label="Stat result">
              <button type="button" class="mfp-verdict__btn is-good ${isPositiveStat(row) ? "is-on" : ""}" data-row-verdict="positive">Achieved</button>
              <button type="button" class="mfp-verdict__btn is-bad ${isPositiveStat(row) ? "" : "is-on"}" data-row-verdict="negative">Not achieved</button>
            </div>
            ${rows.length > 1 ? `<button type="button" class="mfp-btn mfp-btn--ghost mfp-btn--small" data-remove-row="${escapeAttr(row.id)}">Remove</button>` : ""}
          </div>
        `).join("")
      : "";
    return `
        <div class="mfp-profile-card ${slide.id === activeSlideKey ? "is-on" : ""}" data-match-slide="${escapeAttr(slide.id)}">
          <div class="mfp-profile-card__head">
            <div>
              <div class="mfp-profile-card__title">${escapeHtml(matchSlideKindLabel(slide, i))}</div>
            </div>
          </div>
          <div class="mfp-field"><label>${slide.kind === "stat" ? "What is the stat" : "Title"}</label><input data-slide-title value="${escapeAttr(slide.title || "")}" /></div>
          ${slide.kind === "stat" ? `
          <div class="mfp-field"><label>Number / result</label><input data-slide-value value="${escapeAttr(slide.statValue || "")}" placeholder="e.g. 62% or 3/11" /></div>
          <div class="mfp-field"><label>Note</label><input data-slide-sub value="${escapeAttr(slide.subtitle || "")}" /></div>
          <div class="mfp-verdict" role="group" aria-label="Stat result">
            <button type="button" class="mfp-verdict__btn is-good ${isPositiveStat(slide) ? "is-on" : ""}" data-slide-verdict="positive">Achieved</button>
            <button type="button" class="mfp-verdict__btn is-bad ${isPositiveStat(slide) ? "" : "is-on"}" data-slide-verdict="negative">Not achieved</button>
          </div>
          ` : ""}
          ${slide.kind === "stats" ? `
          <div class="mfp-field"><label>Note</label><input data-slide-sub value="${escapeAttr(slide.subtitle || "")}" /></div>
          ${statsRows}
          ${rows.length < 6 ? `<button type="button" class="mfp-btn mfp-btn--ghost mfp-btn--small" data-add-row>Add another stat</button>` : ""}
          ` : ""}
          ${slide.kind !== "stat" && slide.kind !== "stats" ? `<div class="mfp-field"><label>Subtitle</label><input data-slide-sub value="${escapeAttr(slide.subtitle || "")}" /></div>` : ""}
          <button type="button" class="mfp-btn mfp-btn--ghost mfp-btn--small" data-select-slide="${escapeAttr(slide.id)}">${slide.kind === "stat" || slide.kind === "stats" ? "Optional photo" : "Assign photos here"}</button>
        </div>`;
  }

  function renderMatchEditor() {
    if (!matchPack) {
      editor.innerHTML = `<h2>Match slides</h2><p class="mfp-hint">Pick a Through a Lens game. Pre-match, Post-match and Set plays templates load with the Vale badge, the opponent badge, and empty photo slots you can drag into.</p>`;
      return;
    }
    const match = matchPack.match || {};
    const opp = matchPack.opponent || {};
    const slides = matchPack.slides || [];
    editor.innerHTML = `
      <h2>${escapeHtml((matchPack.pack && matchPack.pack.label) || "Match slides")}</h2>
      <p class="mfp-hint">${escapeHtml(match.fixture || opp.name || "")} — drag photos onto the slides. Titles edit on the slide or here.</p>
      <div class="mfp-field"><label>Opponent</label><input data-match-opp value="${escapeAttr(opp.name || "")}" /></div>
      <div class="mfp-field"><label>Competition</label><input data-match-comp value="${escapeAttr(match.competition || "")}" /></div>
      ${slides.map((slide, i) => matchEditorSlideCard(slide, i)).join("")}
      <div class="mfp-editor-actions">
        <button type="button" class="mfp-btn mfp-btn--ghost" id="addMatchSlideBtn">Add slide</button>
        <button type="button" class="mfp-btn mfp-btn--ghost" id="addStatSlideBtn">Add stat slide</button>
        <button type="button" class="mfp-btn mfp-btn--ghost" id="addStatsSlideBtn">Add multiple stats</button>
      </div>
    `;
    const oppInput = editor.querySelector("[data-match-opp]");
    if (oppInput) {
      oppInput.addEventListener("input", () => {
        if (!matchPack.opponent) matchPack.opponent = {};
        matchPack.opponent.name = oppInput.value;
        renderPreview();
      });
    }
    const compInput = editor.querySelector("[data-match-comp]");
    if (compInput) {
      compInput.addEventListener("input", () => {
        if (!matchPack.match) matchPack.match = {};
        matchPack.match.competition = compInput.value;
        const cover = matchSlideById("cover");
        if (cover) cover.kicker = compInput.value;
        renderPreview();
      });
    }
    editor.querySelectorAll("[data-match-slide]").forEach((card) => {
      const id = card.getAttribute("data-match-slide");
      const slide = matchSlideById(id);
      if (!slide) return;
      const titleEl = card.querySelector("[data-slide-title]");
      const subEl = card.querySelector("[data-slide-sub]");
      const valueEl = card.querySelector("[data-slide-value]");
      if (titleEl) {
        titleEl.addEventListener("input", () => {
          slide.title = titleEl.value;
          renderPreview();
          renderPhotoGrid();
        });
      }
      if (subEl) {
        subEl.addEventListener("input", () => {
          slide.subtitle = subEl.value;
          renderPreview();
        });
      }
      if (valueEl) {
        valueEl.addEventListener("input", () => {
          slide.statValue = valueEl.value;
          renderPreview();
        });
      }
      card.querySelectorAll("[data-slide-verdict]").forEach((btn) => {
        btn.addEventListener("click", () => {
          slide.verdict = btn.getAttribute("data-slide-verdict") === "negative" ? "negative" : "positive";
          renderEditor();
          renderPreview();
        });
      });
      card.querySelectorAll("[data-stat-row]").forEach((rowEl) => {
        const rowId = rowEl.getAttribute("data-stat-row");
        const row = (slide.stats || []).find((item) => item.id === rowId);
        if (!row) return;
        const rowTitle = rowEl.querySelector("[data-row-title]");
        const rowValue = rowEl.querySelector("[data-row-value]");
        if (rowTitle) {
          rowTitle.addEventListener("input", () => {
            row.title = rowTitle.value;
            renderPreview();
          });
        }
        if (rowValue) {
          rowValue.addEventListener("input", () => {
            row.statValue = rowValue.value;
            renderPreview();
          });
        }
        rowEl.querySelectorAll("[data-row-verdict]").forEach((btn) => {
          btn.addEventListener("click", () => {
            row.verdict = btn.getAttribute("data-row-verdict") === "negative" ? "negative" : "positive";
            renderEditor();
            renderPreview();
          });
        });
      });
      const addRowBtn = card.querySelector("[data-add-row]");
      if (addRowBtn) {
        addRowBtn.addEventListener("click", () => {
          if (!Array.isArray(slide.stats)) slide.stats = [];
          if (slide.stats.length >= 6) return;
          slide.stats.push(emptyStatRow(slide.stats.length + 1));
          renderEditor();
          renderPreview();
        });
      }
      card.querySelectorAll("[data-remove-row]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const rowId = btn.getAttribute("data-remove-row");
          slide.stats = (slide.stats || []).filter((item) => item.id !== rowId);
          renderEditor();
          renderPreview();
        });
      });
    });
    editor.querySelectorAll("[data-select-slide]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeSlideKey = btn.getAttribute("data-select-slide") || activeSlideKey;
        renderEditor();
        renderPreview();
        renderPhotoGrid();
        setStatus(`Assigning photos to ${slideLabel(activeSlideKey)}.`);
      });
    });
    const addBtn = editor.querySelector("#addMatchSlideBtn");
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        const slide = newMatchTopicSlide();
        matchPack.slides.push(slide);
        ensureSlidePhoto(slide.id);
        activeSlideKey = slide.id;
        renderEditor();
        renderPreview();
        renderPhotoGrid();
        setStatus("Added a slide — rename it, then drop a photo on.");
      });
    }
    const addStatBtn = editor.querySelector("#addStatSlideBtn");
    if (addStatBtn) {
      addStatBtn.addEventListener("click", () => {
        const slide = newMatchStatSlide();
        matchPack.slides.push(slide);
        ensureSlidePhoto(slide.id);
        activeSlideKey = slide.id;
        renderEditor();
        renderPreview();
        renderPhotoGrid();
        setStatus("Stat slide added — write the number, then mark Achieved or Not achieved.");
      });
    }
    const addStatsBtn = editor.querySelector("#addStatsSlideBtn");
    if (addStatsBtn) {
      addStatsBtn.addEventListener("click", () => {
        const slide = newMatchStatsSlide();
        matchPack.slides.push(slide);
        ensureSlidePhoto(slide.id);
        activeSlideKey = slide.id;
        renderEditor();
        renderPreview();
        renderPhotoGrid();
        setStatus("Stats board added — fill each number, then mark Achieved or Not achieved.");
      });
    }
  }

  function matchSlideHtml(slide) {
    const src = photoSrc(slide.id);
    const vale = matchPack.portVale || {};
    const opp = matchPack.opponent || {};
    const valeBadge = vale.badgeProxyUrl || vale.badgeUrl || BADGE_URL;
    const oppBadge = opp.badgeProxyUrl || opp.badgeUrl || "";
    const oppName = opp.name || "Opponent";
    const ghost = String(oppName).split(/\s+/)[0] || "VALE";
    if (slide.kind === "stat") {
      return matchStatSlideHtml(slide, {
        src, valeBadge, oppBadge, oppName,
      });
    }
    if (slide.kind === "stats") {
      return matchStatsSlideHtml(slide, {
        src, valeBadge, oppBadge, oppName,
      });
    }
    const photoInner = src
      ? `<img src="${escapeAttr(src)}" alt="" crossorigin="anonymous" />`
      : `<div class="mfp-match-drop"><span>Drop a photo</span><small>Drag from Through a Lens</small></div>`;
    return `<div class="mfp-slide mfp-slide--match ${slide.kind === "cover" ? "is-cover" : "is-topic"} ${slide.id === activeSlideKey ? "is-active-target" : ""}" data-slide="${escapeAttr(slide.id)}" data-drop-slide="${escapeAttr(slide.id)}">
      <div class="mfp-match__atmosphere" aria-hidden="true"></div>
      <p class="mfp-match__ghost" aria-hidden="true">${escapeHtml(ghost)}</p>
      <div class="mfp-match__photo">${photoInner}</div>
      <div class="mfp-match__photo-edge" aria-hidden="true"></div>
      <div class="mfp-match__goldbar" aria-hidden="true"></div>
      <div class="mfp-match__stage">
        <p class="mfp-match__kicker">${escapeHtml(slide.kicker || "")}</p>
        <h2 class="mfp-match__title" contenteditable="true" spellcheck="false" data-edit-field="title">${htmlWithBreaks(slide.title || "")}</h2>
        <p class="mfp-match__sub" contenteditable="true" spellcheck="false" data-edit-field="subtitle">${escapeHtml(slide.subtitle || "")}</p>
        <div class="mfp-match__badges">
          <div class="mfp-match__club">
            <span class="mfp-match__crest"><img src="${escapeAttr(valeBadge)}" alt="Port Vale" /></span>
            <span>Port Vale</span>
          </div>
          <span class="mfp-match__vs">VS</span>
          <div class="mfp-match__club">
            <span class="mfp-match__crest">${oppBadge ? `<img src="${escapeAttr(oppBadge)}" alt="${escapeAttr(oppName)}" />` : `<span class="mfp-match__crest-ph"></span>`}</span>
            <span>${escapeHtml(oppName)}</span>
          </div>
        </div>
      </div>
    </div>`;
  }

  function matchClubStrip(art) {
    return `<div class="mfp-match__badges">
          <div class="mfp-match__club">
            <span class="mfp-match__crest"><img src="${escapeAttr(art.valeBadge)}" alt="Port Vale" /></span>
            <span>Port Vale</span>
          </div>
          <span class="mfp-match__vs">VS</span>
          <div class="mfp-match__club">
            <span class="mfp-match__crest">${art.oppBadge ? `<img src="${escapeAttr(art.oppBadge)}" alt="${escapeAttr(art.oppName)}" />` : `<span class="mfp-match__crest-ph"></span>`}</span>
            <span>${escapeHtml(art.oppName)}</span>
          </div>
        </div>`;
  }

  function matchStatSlideHtml(slide, art) {
    const positive = isPositiveStat(slide);
    const value = slide.statValue || "0";
    const hasPhoto = Boolean(art.src);
    const photoInner = hasPhoto
      ? `<img src="${escapeAttr(art.src)}" alt="" crossorigin="anonymous" />`
      : `<div class="mfp-match-drop is-optional"><span>Photo optional</span></div>`;
    return `<div class="mfp-slide mfp-slide--match is-stat ${positive ? "is-positive" : "is-negative"} ${hasPhoto ? "has-photo" : "no-photo"} ${slide.id === activeSlideKey ? "is-active-target" : ""}" data-slide="${escapeAttr(slide.id)}" data-drop-slide="${escapeAttr(slide.id)}">
      <div class="mfp-match__atmosphere" aria-hidden="true"></div>
      ${hasPhoto ? `<div class="mfp-match__photo">${photoInner}</div><div class="mfp-match__photo-edge" aria-hidden="true"></div>` : ""}
      <div class="mfp-match__goldbar" aria-hidden="true"></div>
      <div class="mfp-match__stage">
        <div class="mfp-match__verdict" role="group" aria-label="Stat result">
          <button type="button" class="mfp-match__stamp ${positive ? "is-on" : ""}" data-verdict="positive">Achieved</button>
          <button type="button" class="mfp-match__stamp ${positive ? "" : "is-on"}" data-verdict="negative">Not achieved</button>
        </div>
        <p class="mfp-match__value" contenteditable="true" spellcheck="false" data-edit-field="statValue">${escapeHtml(value)}</p>
        <h2 class="mfp-match__title" contenteditable="true" spellcheck="false" data-edit-field="title">${htmlWithBreaks(slide.title || "")}</h2>
        <p class="mfp-match__sub" contenteditable="true" spellcheck="false" data-edit-field="subtitle">${escapeHtml(slide.subtitle || "")}</p>
        ${matchClubStrip(art)}
      </div>
    </div>`;
  }

  function matchStatsSlideHtml(slide, art) {
    const rows = Array.isArray(slide.stats) && slide.stats.length ? slide.stats : [emptyStatRow(1)];
    const hasPhoto = Boolean(art.src);
    const photoInner = hasPhoto
      ? `<img src="${escapeAttr(art.src)}" alt="" crossorigin="anonymous" />`
      : "";
    const cards = rows.map((row) => {
      const positive = isPositiveStat(row);
      return `<article class="mfp-stat-card ${positive ? "is-positive" : "is-negative"}">
          <div class="mfp-match__verdict" role="group" aria-label="Stat result">
            <button type="button" class="mfp-match__stamp ${positive ? "is-on" : ""}" data-stat-id="${escapeAttr(row.id)}" data-verdict="positive">Achieved</button>
            <button type="button" class="mfp-match__stamp ${positive ? "" : "is-on"}" data-stat-id="${escapeAttr(row.id)}" data-verdict="negative">Not achieved</button>
          </div>
          <p class="mfp-stat-card__value" contenteditable="true" spellcheck="false" data-stat-id="${escapeAttr(row.id)}" data-edit-field="statValue">${escapeHtml(row.statValue || "0")}</p>
          <h3 class="mfp-stat-card__title" contenteditable="true" spellcheck="false" data-stat-id="${escapeAttr(row.id)}" data-edit-field="title">${htmlWithBreaks(row.title || "")}</h3>
        </article>`;
    }).join("");
    const good = rows.filter(isPositiveStat).length;
    const mood = good === rows.length ? "is-positive" : good === 0 ? "is-negative" : "is-mixed";
    return `<div class="mfp-slide mfp-slide--match is-stats ${mood} ${hasPhoto ? "has-photo" : "no-photo"} ${slide.id === activeSlideKey ? "is-active-target" : ""}" data-slide="${escapeAttr(slide.id)}" data-drop-slide="${escapeAttr(slide.id)}">
      <div class="mfp-match__atmosphere" aria-hidden="true"></div>
      ${hasPhoto ? `<div class="mfp-match__photo">${photoInner}</div><div class="mfp-match__photo-edge" aria-hidden="true"></div>` : ""}
      <div class="mfp-match__goldbar" aria-hidden="true"></div>
      <div class="mfp-match__stage">
        <p class="mfp-match__kicker">${escapeHtml(slide.kicker || "Stats")}</p>
        <h2 class="mfp-match__title" contenteditable="true" spellcheck="false" data-edit-field="title">${htmlWithBreaks(slide.title || "")}</h2>
        <p class="mfp-match__sub" contenteditable="true" spellcheck="false" data-edit-field="subtitle">${escapeHtml(slide.subtitle || "")}</p>
        <div class="mfp-stat-grid mfp-stat-grid--${statGridCols(rows.length)}">${cards}</div>
        ${matchClubStrip(art)}
      </div>
    </div>`;
  }

  function bindMatchPreviewEvents() {
    preview.querySelectorAll("[data-drop-slide]").forEach((slideEl) => {
      const id = slideEl.getAttribute("data-drop-slide");
      slideEl.addEventListener("click", (event) => {
        if (event.target.closest("[contenteditable], [data-verdict]")) return;
        if (id && id !== activeSlideKey) {
          activeSlideKey = id;
          renderEditor();
          renderPreview();
          renderPhotoGrid();
        }
      });
      slideEl.querySelectorAll("[data-verdict]").forEach((btn) => {
        btn.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          const slide = matchSlideById(id);
          if (!slide) return;
          const verdict = btn.getAttribute("data-verdict") === "negative" ? "negative" : "positive";
          const rowId = btn.getAttribute("data-stat-id");
          if (rowId && Array.isArray(slide.stats)) {
            const row = slide.stats.find((item) => item.id === rowId);
            if (row) row.verdict = verdict;
          } else {
            slide.verdict = verdict;
          }
          renderEditor();
          renderPreview();
          renderPhotoGrid();
        });
      });
      slideEl.querySelectorAll("[data-edit-field]").forEach((el) => {
        el.addEventListener("keydown", (event) => {
          const field = el.getAttribute("data-edit-field");
          if (event.key === "Enter" && field !== "title") {
            event.preventDefault();
            el.blur();
          }
        });
        el.addEventListener("input", () => {
          const slide = matchSlideById(id);
          if (!slide) return;
          const field = el.getAttribute("data-edit-field");
          const rowId = el.getAttribute("data-stat-id");
          const multiline = field === "title";
          const text = multiline
            ? String(el.innerText || "").replace(/\n{3,}/g, "\n\n").replace(/^\n+|\n+$/g, "")
            : String(el.textContent || "").replace(/\s+/g, " ").trim();
          const target = rowId && Array.isArray(slide.stats)
            ? slide.stats.find((item) => item.id === rowId)
            : slide;
          if (!target) return;
          if (field === "statValue") target.statValue = text;
          else target[field] = text;
        });
        el.addEventListener("blur", () => {
          renderEditor();
          renderPhotoGrid();
        });
      });
    });
  }

  function renderMatchPreview() {
    if (!matchPack) {
      preview.innerHTML = "";
      return;
    }
    preview.innerHTML = (matchPack.slides || []).map((slide, i) =>
      `<div class="mfp-slide-wrap"><p class="mfp-slide-caption">${String(i + 1).padStart(2, "0")} · ${escapeHtml(slide.title || "Slide")}</p>${matchSlideHtml(slide)}</div>`
    ).join("");
    bindMatchPreviewEvents();
    requestAnimationFrame(scaleSlides);
  }

  function renderEditor() {
    if (appMode === "dossier") {
      if (!dossier) {
        editor.innerHTML = `<h2>Dossier</h2><p class="mfp-hint">Load a player first.</p>`;
        return;
      }
      renderDossierEditor();
      return;
    }
    if (appMode === "match") {
      renderMatchEditor();
      return;
    }
    if (!pack) {
      editor.innerHTML = "";
      return;
    }
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
    if (appMode === "dossier") {
      renderDossierPreview();
      return;
    }
    if (appMode === "match") {
      renderMatchPreview();
      return;
    }
    if (!pack) {
      preview.innerHTML = "";
      return;
    }
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
    if (appMode === "match") renderEditor();
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
    const ready = appMode === "match" ? matchPack : pack;
    if (!ready) return;
    downloadBtn.disabled = true;
    setStatus("Rendering PNG pack in Chrome…");
    try {
      const slides = Array.from(preview.querySelectorAll(".mfp-slide"));
      if (!slides.length) throw new Error("No slides to export");

      const folder = appMode === "match"
        ? slugify(`${(matchPack.pack && matchPack.pack.id) || "match"}-${(matchPack.opponent && matchPack.opponent.name) || "vale"}`)
        : slugify(pack.player.name || "player");
      const filenames = slides.map((slide, i) => {
        const key = slide.getAttribute("data-slide") || `slide-${i + 1}`;
        if (key === "identity") return "01-identity";
        if (key === "data") return `${String(i + 1).padStart(2, "0")}-data-summary`;
        return `${String(i + 1).padStart(2, "0")}-${slugify(slideLabel(key))}`;
      });
      const zipName = appMode === "match"
        ? `${folder}-match-slides.zip`
        : `${folder}-meeting-front-pages.zip`;
      const opponentName = appMode === "match"
        ? ((matchPack.opponent && matchPack.opponent.name) || "match")
        : (pack.player.name || "player");

      const canFallback = typeof html2canvas === "function" && typeof JSZip === "function";
      if (window.PortValeWysiwygExport && typeof window.PortValeWysiwygExport.captureSlideHtmlPages === "function") {
        try {
          const packHtml = await window.PortValeWysiwygExport.captureSlideHtmlPages({
            slides,
            forceNativeSize: true,
            nativeWidth: SLIDE_W,
            nativeHeight: SLIDE_H,
            background: "#12100e",
            stripClasses: ["is-active-target", "is-drop"],
            onProgress: (msg) => setStatus(msg),
          });
          // Override filenames to our meeting-pack naming.
          packHtml.htmlFilenames = filenames;
          setStatus("Screenshotting slides in Chrome…");
          const result = await window.PortValeWysiwygExport.downloadPngZip({
            ...packHtml,
            filename: zipName,
            documentTitle: folder,
            opponentName,
            endpoint: "/api/wysiwyg-export-png-zip",
            pagesPerRequest: 1,
            onProgress: (msg) => setStatus(msg),
          });
          setStatus(
            result.savedPath
              ? `Downloaded ${result.pageCount} sharp PNGs · ${result.sizeMb} MB · also on Desktop`
              : `Downloaded ${result.pageCount} sharp PNGs · ${result.sizeMb} MB`
          );
          return;
        } catch (wysiwygErr) {
          if (!canFallback) throw wysiwygErr;
          setStatus("Chrome pack failed — capturing slides in the browser instead…");
        }
      }

      if (!canFallback) {
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
      downloadBlob(out, zipName);
      setStatus(`Downloaded ${slides.length} PNGs (fallback).`);
    } catch (err) {
      setStatus(
        friendlyNetworkError(err, "Could not download the PNG pack. Refresh and try again."),
        true,
      );
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
    const moreBtn = event.target.closest("#valeMoreBtn");
    if (moreBtn) {
      if (valeActiveMatchId && valeNextStart && !valeLoading) {
        loadValePhotos(valeActiveMatchId, { append: true });
      }
      return;
    }
    const targetBtn = event.target.closest("button[data-slide-target]");
    if (targetBtn) {
      activeSlideKey = targetBtn.getAttribute("data-slide-target") || "identity";
      renderPhotoGrid();
      setStatus(`Assigning photos to ${slideLabel(activeSlideKey)}.`);
      return;
    }
    const btn = event.target.closest("button[data-photo-id]");
    if (!btn) return;
    if (!hasAssignableSlides()) {
      setStatus(
        appMode === "match"
          ? "Pick a Through a Lens game first so the slides appear."
          : "Load a player, or open Match slides and pick a game, then drop a picture on.",
        true
      );
      return;
    }
    const photoId = btn.getAttribute("data-photo-id");
    assignPhotoToActive(photoId);
    cutoutInput.value = "";
    const web = catalogPhotoById(photoId);
    renderPhotoGrid();
    renderPreview();
    if (appMode === "match") renderEditor();
    setStatus(`Set ${slideLabel(activeSlideKey)} photo → ${web ? web.label : "selected"}.`);
  });

  if (valeComps) {
    valeComps.addEventListener("click", (event) => {
      const btn = event.target.closest("button[data-vale-comp]");
      if (!btn) return;
      valeActiveComp = btn.getAttribute("data-vale-comp") || valeActiveComp;
      valeActiveMatchId = null;
      valePhotos = [];
      valeNextStart = null;
      renderPhotoGrid();
    });
  }
  if (valeMatchesEl) {
    valeMatchesEl.addEventListener("click", (event) => {
      const btn = event.target.closest("button[data-vale-match]");
      if (!btn) return;
      const id = btn.getAttribute("data-vale-match");
      if (!id) return;
      const match = valeMatches.find((row) => row.id === id);
      const openMatch = appMode === "match" || (appMode === "meeting" && !pack);
      if (openMatch && match) {
        appMode = "match";
        try { localStorage.setItem("mfp-mode", "match"); } catch (_) { /* ignore */ }
        applyModeChrome();
        loadMatchPack(match).then(() => loadValePhotos(id));
        return;
      }
      loadValePhotos(id);
    });
  }
  if (matchPackPills) {
    matchPackPills.addEventListener("click", (event) => {
      const btn = event.target.closest("button[data-match-pack]");
      if (!btn) return;
      const packId = btn.getAttribute("data-match-pack") || "pre-match";
      matchPackId = packId;
      try { localStorage.setItem("mfp-match-pack", matchPackId); } catch (_) { /* ignore */ }
      renderMatchPackPills();
      const match = activeValeMatch();
      if (match) loadMatchPack(match, { keepPhotos: true, packId });
    });
  }
  if (photoGrid) {
    photoGrid.addEventListener("dragstart", (event) => {
      const card = event.target.closest("[data-photo-id]");
      if (!card || !hasAssignableSlides()) return;
      event.dataTransfer.setData("text/plain", card.getAttribute("data-photo-id") || "");
      event.dataTransfer.setData("text/mfp-photo", card.getAttribute("data-photo-id") || "");
      event.dataTransfer.effectAllowed = "copy";
    });
  }
  if (preview) {
    preview.addEventListener("dragover", (event) => {
      const slide = event.target.closest("[data-drop-slide]");
      if (!slide) return;
      event.preventDefault();
      slide.classList.add("is-drop");
    });
    preview.addEventListener("dragleave", (event) => {
      const slide = event.target.closest("[data-drop-slide]");
      if (!slide) return;
      if (slide.contains(event.relatedTarget)) return;
      slide.classList.remove("is-drop");
    });
    preview.addEventListener("drop", (event) => {
      const slide = event.target.closest("[data-drop-slide]");
      if (!slide) return;
      event.preventDefault();
      slide.classList.remove("is-drop");
      const key = slide.getAttribute("data-drop-slide");
      if (key) activeSlideKey = key;
      const photoId = event.dataTransfer.getData("text/mfp-photo") || event.dataTransfer.getData("text/plain");
      if (photoId) {
        assignPhotoToActive(photoId);
        renderPhotoGrid();
        renderPreview();
        renderEditor();
        setStatus(`Set ${slideLabel(activeSlideKey)} photo.`);
        return;
      }
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file && file.type.startsWith("image/")) {
        applyCutoutFile(file).catch((err) => setStatus(err.message, true));
      }
    });
  }
  document.querySelectorAll(".mfp-source").forEach((btn) => {
    btn.addEventListener("click", () => {
      photoSource = btn.getAttribute("data-photo-source") === "web" ? "web" : "vale";
      document.querySelectorAll(".mfp-source").forEach((other) => {
        other.classList.toggle("is-active", other === btn);
      });
      renderPhotoGrid();
    });
  });

  document.querySelectorAll(".mfp-mode").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-mode") || "meeting";
      setAppMode(mode);
    });
  });
  if (saveDossierBtn) {
    saveDossierBtn.addEventListener("click", () => {
      saveDossier().catch(() => {});
    });
  }
  applyModeChrome();
  loadValeGalleries();

  refreshBtn.addEventListener("click", () => {
    if (!selectedPlayerId) return;
    const code = pack && pack.player && pack.player.primaryPosition;
    const iter = pack && pack.player && pack.player.iterationId;
    loadPack(selectedPlayerId, code || undefined, {
      keepPhotos: Boolean(webPhotos.length || valePhotos.length),
      iterationId: iter,
    });
  });

  refreshPhotosBtn.addEventListener("click", () => loadWebPhotos({ switchTab: true }));

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
    if (pack || matchPack) {
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
    if (pack || matchPack) scaleSlides();
  });
})();
