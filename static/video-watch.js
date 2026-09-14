(() => {
  "use strict";

  const LEAGUES = [
    { name: "League Two", country: "England", flag: "gb-eng", fotmob: 109 },
    { name: "League One", country: "England", flag: "gb-eng", fotmob: 108 },
    { name: "National League", country: "England", flag: "gb-eng", fotmob: 117 },
    { name: "Scottish Prem", country: "Scotland", flag: "gb-sct", fotmob: 64 },
    { name: "PL2", country: "England", flag: "gb-eng", fotmob: 9084 },
    { name: "Irish Prem", country: "Ireland", flag: "ie", fotmob: 126 },
  ];

  function leagueMeta(name) {
    return LEAGUES.find((row) => row.name === name) || { name, country: "", flag: "", fotmob: 0 };
  }

  function leagueFlagUrl(meta) {
    return meta?.flag ? `https://flagcdn.com/w80/${meta.flag}.png` : "";
  }

  function leagueBadgeUrl(meta) {
    return meta?.fotmob
      ? `https://images.fotmob.com/image_resources/logo/leaguelogo/${meta.fotmob}.png`
      : "";
  }

  function leagueMarks(name) {
    const meta = leagueMeta(name);
    const flag = leagueFlagUrl(meta);
    const badge = leagueBadgeUrl(meta);
    return `<span class="vw-marks">
      ${flag ? `<img class="vw-flag" src="${escapeHtml(flag)}" alt="" />` : ""}
      ${badge ? `<img class="vw-league-badge" src="${escapeHtml(badge)}" alt="" />` : ""}
    </span>`;
  }

  const els = {
    app: document.getElementById("vwApp"),
    title: document.getElementById("vwTitle"),
    tools: document.getElementById("vwTools"),
    status: document.getElementById("vwStatus"),
    leagues: document.getElementById("vwLeagues"),
    fixtures: document.getElementById("vwFixtures"),
    clubs: document.getElementById("vwClubs"),
    matchesHead: document.getElementById("vwMatchesHead"),
    matches: document.getElementById("vwMatches"),
    desk: document.getElementById("vwDesk"),
    tip: document.getElementById("vwTip"),
    match: document.getElementById("vwMatchMeta"),
    home: document.getElementById("vwHome"),
    away: document.getElementById("vwAway"),
    empty: document.getElementById("vwEmpty"),
    profile: document.getElementById("vwProfile"),
  };

  const state = {
    view: "leagues",
    payload: null,
    query: "",
    phase: "played",
    league: "",
    club: "",
    fixtureId: "",
    sheet: null,
    playerId: null,
    player: null,
    kind: "comment",
    tab: "write",
    ca: 0,
    pa: 0,
    draft: { text: "", minute: "", title: "" },
    loadingSheet: false,
    loadError: "",
    sortKey: "date",
    sortDir: "desc",
    deskView: "formation",
    formations: { home: "", away: "" },
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(message, cls) {
    if (!els.status) return;
    if (!message) {
      els.status.className = "vw-status hidden";
      els.status.textContent = "";
      return;
    }
    els.status.className = `vw-status ${cls || ""}`;
    els.status.textContent = message;
  }

  function friendlyFetchError(error) {
    const msg = String(error?.message || "");
    if (error?.name === "AbortError" || /aborted|too long/i.test(msg)) {
      return "Fixtures are taking too long to load. Tap Retry.";
    }
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      return "Could not load fixtures. The list may still be building — tap Retry.";
    }
    return msg || "Could not load games";
  }

  async function fetchJson(url, options) {
    const timeoutMs = options?.timeoutMs;
    const ctrl = timeoutMs ? new AbortController() : null;
    const timer = ctrl ? window.setTimeout(() => ctrl.abort(), timeoutMs) : 0;
    const { timeoutMs: _ignored, headers, ...rest } = options || {};
    try {
      const res = await fetch(url, {
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(headers || {}) },
        ...(ctrl ? { signal: ctrl.signal } : {}),
        ...rest,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail || data.message || `HTTP ${res.status}`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      return data;
    } catch (error) {
      throw new Error(friendlyFetchError(error));
    } finally {
      if (timer) window.clearTimeout(timer);
    }
  }

  async function fetchJsonRetry(url, options) {
    try {
      return await fetchJson(url, options);
    } catch (error) {
      await new Promise((resolve) => window.setTimeout(resolve, 800));
      return fetchJson(url, options);
    }
  }

  function allGames() {
    return state.payload?.games || [];
  }

  function watchPct(game) {
    if (game?.both_pct != null) return Number(game.both_pct);
    const score = game?.score_pct != null ? Number(game.score_pct) : game?.quality_pct;
    const young = game?.young_pct != null ? Number(game.young_pct) : game?.youth_pct;
    if (score != null && young != null) return Math.round((Number(score) + Number(young)) / 2);
    if (score != null) return Number(score);
    if (game?.watch_pct != null) return Number(game.watch_pct);
    return null;
  }

  function watchMeta(pct) {
    if (pct == null) return { text: "No score yet", cls: "", color: "#6b7280" };
    if (pct >= 70) return { text: "Must watch", cls: "is-must", color: "#059669" };
    if (pct >= 40) return { text: "Worth a look", cls: "is-mid", color: "#d97706" };
    if (pct >= 20) return { text: "Low yield", cls: "is-low", color: "#b45309" };
    return { text: "Skip", cls: "is-skip", color: "#9ca3af" };
  }

  function leagueList() {
    return LEAGUES.map((row) => row.name);
  }

  function gamesInLeague(league) {
    return allGames().filter((row) => String(row.league || "") === league);
  }

  function visibleGames() {
    const needle = state.query.trim().toLowerCase();
    return gamesInLeague(state.league).filter((row) => {
      if (state.phase === "played" && !row.played) return false;
      if (state.phase === "upcoming" && row.played) return false;
      if (state.club) {
        const home = String(row.home?.name || "").toLowerCase();
        const away = String(row.away?.name || "").toLowerCase();
        const club = state.club.toLowerCase();
        if (!home.includes(club) && !away.includes(club)) return false;
      }
      if (!needle) return true;
      const hay = `${row.home?.name || ""} ${row.away?.name || ""} ${row.score || ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }

  function parseDate(value) {
    const raw = String(value || "").slice(0, 10);
    if (!raw) return null;
    const date = new Date(`${raw}T00:00:00`);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDate(value, mode) {
    const date = parseDate(value);
    if (!date) return String(value || "").slice(0, 10);
    if (mode === "long") {
      return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
    }
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  function formatDateParts(value) {
    const date = parseDate(value);
    if (!date) {
      const raw = String(value || "").slice(0, 10);
      return { weekday: "", date: raw };
    }
    return {
      weekday: date.toLocaleDateString("en-GB", { weekday: "short" }),
      date: date.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
    };
  }

  function sideName(side) {
    return String(side?.name || side || "").replace(/^FC\s+/i, "").trim();
  }

  function playerInitials(name) {
    return String(name || "?")
      .split(/\s+/)
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  function photoUrl(player, club) {
    if (player?.photo_url) return player.photo_url;
    const name = String(player?.name || "").trim();
    const team = String(club || player?.club || player?.team_name || "").trim();
    if (!name) return "";
    const params = new URLSearchParams({ name });
    if (team) params.set("club", team);
    return `/api/pre-match/player-photo?${params}`;
  }

  function bindPhotos(root) {
    (root || document).querySelectorAll("img[data-photo-fallback]").forEach((img) => {
      img.addEventListener("error", () => {
        const fallback = img.parentElement?.querySelector("[data-photo-slot]");
        img.hidden = true;
        if (fallback) fallback.hidden = false;
      });
    });
  }

  function captureDraft() {
    const text = document.getElementById("vwText");
    const minute = document.getElementById("vwMinute");
    const title = document.getElementById("vwNoteTitle");
    if (!text && !minute && !title) return;
    state.draft = {
      text: text?.value ?? state.draft.text,
      minute: minute?.value ?? state.draft.minute,
      title: title?.value ?? state.draft.title,
    };
  }

  function fixtureLabel(row) {
    if (!row) return "";
    return `${sideName(row.home)} vs ${sideName(row.away)}`;
  }

  function badge(url, name) {
    if (url) return `<img class="vw-badge" src="${escapeHtml(url)}" alt="" />`;
    const letter = String(name || "?").replace(/^FC\s+/i, "").charAt(0).toUpperCase();
    return `<span class="vw-badge" style="display:grid;place-items:center;font-size:0.7rem;font-weight:800;color:#6b7280">${escapeHtml(letter)}</span>`;
  }

  function writeUrl() {
    const params = new URLSearchParams();
    if (state.league) params.set("league", state.league);
    if (state.club) params.set("club", state.club);
    if (state.phase && state.phase !== "played") params.set("phase", state.phase);
    if (state.sortKey && state.sortKey !== "date") params.set("sort", state.sortKey);
    if (state.sortDir && state.sortDir !== "desc") params.set("dir", state.sortDir);
    if (state.fixtureId) params.set("fixture", state.fixtureId);
    if (state.playerId) params.set("player", String(state.playerId));
    if (state.deskView && state.deskView !== "formation") params.set("desk", state.deskView);
    const next = params.toString();
    window.history.replaceState({}, "", next ? `${window.location.pathname}?${next}` : window.location.pathname);
  }

  function showView(view) {
    state.view = view;
    els.app.dataset.view = view;
    els.leagues.classList.toggle("hidden", view !== "leagues");
    els.fixtures.classList.toggle("hidden", view !== "fixtures");
    els.desk.classList.toggle("hidden", view !== "desk");
    if (view === "leagues") els.title.textContent = "Which league are you watching?";
    if (view === "fixtures") els.title.textContent = "Which match interests you?";
    if (view === "desk") els.title.textContent = fixtureLabel(state.sheet) || "Player Reports";
    renderTools();
  }

  function renderTools() {
    if (state.view === "leagues") {
      els.tools.innerHTML = state.loadError
        ? `<button type="button" class="vw-chip" data-retry>Retry fixtures</button>`
        : "";
      els.tools.querySelector("[data-retry]")?.addEventListener("click", () => loadGames());
      return;
    }
    if (state.view === "fixtures") {
      els.tools.innerHTML = `
        <button type="button" class="vw-chip" data-back="leagues">← Leagues</button>
        <button type="button" class="vw-chip ${state.phase === "played" ? "is-on" : ""}" data-phase="played">Played</button>
        <button type="button" class="vw-chip ${state.phase === "upcoming" ? "is-on" : ""}" data-phase="upcoming">Upcoming</button>
        <input class="vw-search" id="vwSearch" type="search" placeholder="Search matches" value="${escapeHtml(state.query)}" autocomplete="off" />
      `;
      els.tools.querySelector("[data-back]")?.addEventListener("click", () => {
        state.league = "";
        state.club = "";
        writeUrl();
        showView("leagues");
        renderLeagues();
      });
      els.tools.querySelectorAll("[data-phase]").forEach((btn) => {
        btn.addEventListener("click", () => {
          state.phase = btn.dataset.phase || "played";
          writeUrl();
          renderFixtures();
        });
      });
      els.tools.querySelector("#vwSearch")?.addEventListener("input", (event) => {
        state.query = event.target.value || "";
        renderMatches();
      });
      return;
    }
    els.tools.innerHTML = `
      <button type="button" class="vw-chip" data-back="fixtures">← Fixtures</button>
      <button type="button" class="vw-chip ${state.deskView === "formation" ? "is-on" : ""}" data-desk="formation">Formation</button>
      <button type="button" class="vw-chip ${state.deskView === "sheet" ? "is-on" : ""}" data-desk="sheet">Team sheet</button>
    `;
    els.tools.querySelector("[data-back]")?.addEventListener("click", () => {
      state.fixtureId = "";
      state.sheet = null;
      state.playerId = null;
      state.player = null;
      writeUrl();
      showView("fixtures");
      renderFixtures();
    });
    els.tools.querySelectorAll("[data-desk]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.deskView = btn.dataset.desk || "formation";
        writeUrl();
        renderSheets();
        renderTools();
      });
    });
  }

  function renderLeagues() {
    showView("leagues");
    const ready = gamesReady();
    els.leagues.className = "vw-screen vw-leagues";
    els.leagues.innerHTML = leagueList()
      .map((name) => {
        const rows = gamesInLeague(name);
        const must = rows.filter((row) => (watchPct(row) || 0) >= 70).length;
        const played = rows.filter((row) => row.played).length;
        const sub = ready
          ? `${rows.length} games${played ? ` · ${played} played` : ""}`
          : "Loading fixtures…";
        const watch = !ready ? "" : must ? `${must} must watch` : "No must-watch yet";
        const meta = leagueMeta(name);
        const detail = ready
          ? `${meta.country ? `${meta.country} · ` : ""}${sub}`
          : sub;
        return `<button type="button" class="vw-league ${ready ? "" : "is-wait"}" data-league="${escapeHtml(name)}" ${ready ? "" : "disabled"}>
          ${leagueMarks(name)}
          <span class="vw-league__copy">
            <strong>${escapeHtml(name)}</strong>
            <span>${escapeHtml(detail)}</span>
          </span>
          <em>${escapeHtml(watch)}</em>
        </button>`;
      })
      .join("");
    els.leagues.querySelectorAll("[data-league]").forEach((btn) => {
      btn.addEventListener("click", () => openLeague(btn.dataset.league || ""));
    });
  }

  function clubOptions() {
    const map = new Map();
    for (const row of gamesInLeague(state.league)) {
      for (const side of [row.home, row.away]) {
        const name = sideName(side);
        if (!name) continue;
        if (!map.has(name)) map.set(name, side?.image_url || "");
      }
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  function renderClubs() {
    const clubs = clubOptions();
    els.clubs.innerHTML = `
      <h2>Squads</h2>
      <button type="button" class="vw-club ${state.club ? "" : "is-on"}" data-club="">
        <span>All clubs</span>
      </button>
      ${clubs
        .map(
          ([name, image]) => `<button type="button" class="vw-club ${state.club === name ? "is-on" : ""}" data-club="${escapeHtml(name)}">
            ${badge(image, name)}
            <span>${escapeHtml(name)}</span>
          </button>`
        )
        .join("")}
    `;
    els.clubs.querySelectorAll("[data-club]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.club = btn.dataset.club || "";
        writeUrl();
        renderFixtures();
      });
    });
  }

  function sortArrow(key) {
    if (state.sortKey !== key) return "↕";
    return state.sortDir === "asc" ? "↑" : "↓";
  }

  function compareGames(a, b) {
    const dir = state.sortDir === "asc" ? 1 : -1;
    if (state.sortKey === "watch") {
      const av = watchPct(a);
      const bv = watchPct(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av !== bv) return (av - bv) * dir;
    } else if (state.sortKey === "match") {
      const cmp = fixtureLabel(a).localeCompare(fixtureLabel(b), undefined, { sensitivity: "base" });
      if (cmp) return cmp * dir;
    } else {
      const cmp = String(a.date || "").localeCompare(String(b.date || ""));
      if (cmp) return cmp * dir;
    }
    return fixtureLabel(a).localeCompare(fixtureLabel(b), undefined, { sensitivity: "base" });
  }

  function setSort(key) {
    if (state.sortKey === key) {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = key;
      state.sortDir = key === "match" ? "asc" : "desc";
    }
    writeUrl();
    renderMatches();
  }

  function renderMatchCols() {
    const keys = [
      ["date", "Date"],
      ["match", "Match"],
      ["watch", "Watch score"],
    ];
    return `<div class="vw-cols" role="row">
      ${keys
        .map(
          ([key, label]) => `<button type="button" class="vw-col ${state.sortKey === key ? "is-on" : ""}" data-sort="${key}" aria-sort="${state.sortKey === key ? (state.sortDir === "asc" ? "ascending" : "descending") : "none"}">
            ${escapeHtml(label)} <i>${sortArrow(key)}</i>
          </button>`
        )
        .join("")}
      <span class="vw-col vw-col--action">Watch</span>
    </div>`;
  }

  function renderMatches() {
    const rows = visibleGames().sort(compareGames);
    els.matchesHead.innerHTML = `
      <div class="vw-matches__title">
        <h2>${leagueMarks(state.league)}<span>Matches of ${escapeHtml(state.league || "this league")}</span></h2>
        <span>${rows.length}</span>
      </div>
      ${renderMatchCols()}
    `;
    els.matchesHead.querySelectorAll("[data-sort]").forEach((btn) => {
      btn.addEventListener("click", () => setSort(btn.dataset.sort || "date"));
    });
    if (!state.payload) {
      els.matches.innerHTML = `<p class="vw-empty-list">Loading fixtures…</p>`;
      return;
    }
    if (!rows.length) {
      els.matches.innerHTML = `<p class="vw-empty-list">No ${state.phase} games in this league yet.</p>`;
      return;
    }
    els.matches.innerHTML = rows
      .map((row) => {
        const pct = watchPct(row);
        const watch = watchMeta(pct);
        const when = formatDateParts(row.date);
        return `<button type="button" class="vw-row" data-open="${escapeHtml(row.fixture_id || "")}">
          <span class="vw-row__date">
            <small>${escapeHtml(when.weekday)}</small>
            <strong>${escapeHtml(when.date)}</strong>
          </span>
          <span class="vw-row__teams">
            <span class="vw-side">${badge(row.home?.image_url, sideName(row.home))}<span>${escapeHtml(sideName(row.home))}</span></span>
            <span class="vw-row__score">${escapeHtml(row.score || "v")}</span>
            <span class="vw-side is-away">${badge(row.away?.image_url, sideName(row.away))}<span>${escapeHtml(sideName(row.away))}</span></span>
          </span>
          <span class="vw-watch ${watch.cls}">
            <b>${escapeHtml(watch.text)}</b>
            <small>${pct == null ? "—" : `${pct}%`}</small>
          </span>
          <span class="vw-go">Watch</span>
        </button>`;
      })
      .join("");
    els.matches.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => openFixture(btn.dataset.open || ""));
    });
  }

  function renderFixtures() {
    showView("fixtures");
    renderClubs();
    renderMatches();
  }

  function gamesReady() {
    if (!state.payload) return false;
    if ((state.payload.games || []).length) return true;
    return !state.payload.building;
  }

  function openLeague(league) {
    if (!gamesReady()) {
      setStatus("Fixtures are still loading…");
      return;
    }
    state.league = league;
    state.club = "";
    writeUrl();
    renderFixtures();
  }

  const POSITION_SHORT = {
    GOALKEEPER: "GK",
    LEFT_WINGBACK_DEFENDER: "LB",
    RIGHT_WINGBACK_DEFENDER: "RB",
    CENTRAL_DEFENDER: "CB",
    DEFENSE_MIDFIELD: "DM",
    CENTRAL_MIDFIELD: "CM",
    ATTACKING_MIDFIELD: "AM",
    LEFT_WINGER: "LW",
    RIGHT_WINGER: "RW",
    CENTER_FORWARD: "CF",
    Goalkeeper: "GK",
    "Left back": "LB",
    "Right back": "RB",
    "Left wing-back": "LB",
    "Right wing-back": "RB",
    "Centre-back": "CB",
    "Defensive midfield": "DM",
    "Central midfield": "CM",
    "Attacking midfield": "AM",
    "Left winger": "LW",
    "Right winger": "RW",
    "Centre-forward": "CF",
  };

  const FORMATIONS = {
    "4-3-3": [
      ["GOALKEEPER", 50, 92, "any"],
      ["LEFT_WINGBACK_DEFENDER", 10, 74, "left"],
      ["CENTRAL_DEFENDER", 34, 76, "left"],
      ["CENTRAL_DEFENDER", 66, 76, "right"],
      ["RIGHT_WINGBACK_DEFENDER", 90, 74, "right"],
      ["DEFENSE_MIDFIELD", 50, 56, "center"],
      ["CENTRAL_MIDFIELD", 30, 42, "left"],
      ["CENTRAL_MIDFIELD", 70, 42, "right"],
      ["LEFT_WINGER", 14, 16, "left"],
      ["CENTER_FORWARD", 50, 10, "center"],
      ["RIGHT_WINGER", 86, 16, "right"],
    ],
    "4-2-3-1": [
      ["GOALKEEPER", 50, 92, "any"],
      ["LEFT_WINGBACK_DEFENDER", 10, 74, "left"],
      ["CENTRAL_DEFENDER", 34, 76, "left"],
      ["CENTRAL_DEFENDER", 66, 76, "right"],
      ["RIGHT_WINGBACK_DEFENDER", 90, 74, "right"],
      ["DEFENSE_MIDFIELD", 34, 54, "left"],
      ["DEFENSE_MIDFIELD", 66, 54, "right"],
      ["LEFT_WINGER", 12, 24, "left"],
      ["ATTACKING_MIDFIELD", 50, 34, "center"],
      ["RIGHT_WINGER", 88, 24, "right"],
      ["CENTER_FORWARD", 50, 10, "center"],
    ],
    "4-4-2": [
      ["GOALKEEPER", 50, 92, "any"],
      ["LEFT_WINGBACK_DEFENDER", 10, 74, "left"],
      ["CENTRAL_DEFENDER", 34, 76, "left"],
      ["CENTRAL_DEFENDER", 66, 76, "right"],
      ["RIGHT_WINGBACK_DEFENDER", 90, 74, "right"],
      ["LEFT_WINGER", 12, 46, "left"],
      ["CENTRAL_MIDFIELD", 36, 48, "left"],
      ["CENTRAL_MIDFIELD", 64, 48, "right"],
      ["RIGHT_WINGER", 88, 46, "right"],
      ["CENTER_FORWARD", 36, 12, "left"],
      ["CENTER_FORWARD", 64, 12, "right"],
    ],
    "5-3-2": [
      ["GOALKEEPER", 50, 92, "any"],
      ["LEFT_WINGBACK_DEFENDER", 8, 60, "left"],
      ["CENTRAL_DEFENDER", 28, 76, "left"],
      ["CENTRAL_DEFENDER", 50, 78, "center"],
      ["CENTRAL_DEFENDER", 72, 76, "right"],
      ["RIGHT_WINGBACK_DEFENDER", 92, 60, "right"],
      ["DEFENSE_MIDFIELD", 50, 52, "center"],
      ["CENTRAL_MIDFIELD", 32, 40, "left"],
      ["CENTRAL_MIDFIELD", 68, 40, "right"],
      ["CENTER_FORWARD", 36, 12, "left"],
      ["CENTER_FORWARD", 64, 12, "right"],
    ],
  };

  const SLOT_ALIASES = {
    LEFT_WINGER: ["LEFT_WINGER", "LEFT_MIDFIELD"],
    RIGHT_WINGER: ["RIGHT_WINGER", "RIGHT_MIDFIELD"],
    CENTRAL_MIDFIELD: ["CENTRAL_MIDFIELD", "DEFENSE_MIDFIELD", "ATTACKING_MIDFIELD"],
    DEFENSE_MIDFIELD: ["DEFENSE_MIDFIELD", "CENTRAL_MIDFIELD"],
    ATTACKING_MIDFIELD: ["ATTACKING_MIDFIELD", "CENTRAL_MIDFIELD"],
    CENTER_FORWARD: ["CENTER_FORWARD", "SECOND_STRIKER"],
    LEFT_WINGBACK_DEFENDER: ["LEFT_WINGBACK_DEFENDER", "LEFT_BACK"],
    RIGHT_WINGBACK_DEFENDER: ["RIGHT_WINGBACK_DEFENDER", "RIGHT_BACK"],
  };

  function positionCode(player) {
    return String(player?.position || player?.formation_slot || "").toUpperCase();
  }

  function positionBand(code) {
    const value = String(code || "").toUpperCase();
    if (value.includes("GOAL")) return "gk";
    if (value.includes("FORWARD") || value.includes("STRIKER") || value.includes("WINGER")) return "attack";
    if (value.includes("MID")) return "mid";
    if (value.includes("DEF") || value.includes("BACK")) return "def";
    return "mid";
  }

  function playerSideHint(player) {
    const code = positionCode(player);
    if (code.includes("LEFT")) return "left";
    if (code.includes("RIGHT")) return "right";
    return "center";
  }

  function slotMatchScore(player, slot, side) {
    const playerCode = positionCode(player);
    let score = 0;
    if (playerCode === slot) score += 120;
    else if ((SLOT_ALIASES[slot] || [slot]).includes(playerCode)) score += 80;
    else if (positionBand(playerCode) === positionBand(slot)) score += 35;
    else score -= 40;
    const hint = playerSideHint(player);
    if (side === "any") score += 15;
    else if (hint === side) score += 25;
    else if (side === "center" && hint === "center") score += 20;
    score += Math.min(Number(player.minutes) || 0, 800) / 80;
    score += Math.min(Number(player.overall) || 0, 80) / 20;
    return score;
  }

  function assignFormation(players, formation) {
    const slots = FORMATIONS[formation] || FORMATIONS["4-3-3"];
    const pool = [...(players || [])]
      .filter((row) => Number(row.player_id))
      .sort((a, b) => (Number(b.minutes) || 0) - (Number(a.minutes) || 0) || (Number(b.overall) || 0) - (Number(a.overall) || 0));
    const used = new Set();
    const xi = [];
    for (const [slot, x, y, side] of slots) {
      let best = null;
      let bestScore = -10000;
      for (const player of pool) {
        const id = Number(player.player_id);
        if (used.has(id)) continue;
        const score = slotMatchScore(player, slot, side);
        if (score > bestScore) {
          bestScore = score;
          best = player;
        }
      }
      if (!best) best = pool.find((player) => !used.has(Number(player.player_id)));
      if (!best) break;
      used.add(Number(best.player_id));
      xi.push({ ...best, x_pct: x, y_pct: y, formation_slot: slot, slot_side: side });
    }
    return xi;
  }

  function sideFormation(side) {
    const picked = state.formations[side];
    if (picked && FORMATIONS[picked]) return picked;
    return state.sheet?.[side]?.formation || "4-3-3";
  }

  function hasMatchLineup(team) {
    return (team?.players || []).some((row) => row.started || row.subbed_on);
  }

  function sideXi(side) {
    const team = state.sheet?.[side];
    const starters = (team?.players || []).filter((row) => row.started);
    if (hasMatchLineup(team)) {
      if (state.formations[side] && starters.length) {
        return assignFormation(starters, state.formations[side]);
      }
      return starters;
    }
    return [];
  }

  function sideSubs(side) {
    return (state.sheet?.[side]?.players || []).filter((row) => row.subbed_on);
  }

  function lineupEmptyCopy(team) {
    if (team?.lineup_status === "upcoming") {
      return "Kick-off hasn't happened. After the game this lists who started and who came on.";
    }
    if (team?.lineup_status === "missing") {
      return "No match XI in yet for this fixture.";
    }
    return "No players from this match.";
  }

  function playerMeta(player) {
    return [
      player.started ? "Started" : "",
      player.subbed_on ? (player.match_minute ? `On ${player.match_minute}'` : "Sub on") : "",
      player.position_label || player.position,
      player.age != null ? `${player.age}y` : "",
      player.u27 ? "U27" : "",
    ]
      .filter(Boolean)
      .join(" · ");
  }

  function positionShort(player) {
    if (player?.formation_slot && POSITION_SHORT[player.formation_slot]) {
      return POSITION_SHORT[player.formation_slot];
    }
    if (player?.position_short) return player.position_short;
    return (
      POSITION_SHORT[player?.position] ||
      POSITION_SHORT[player?.position_label] ||
      "—"
    );
  }

  function positionGroup(short) {
    if (short === "GK") return "Goalkeepers";
    if (["CB", "LB", "RB", "LWB", "RWB"].includes(short)) return "Defence";
    if (["DM", "CM", "AM"].includes(short)) return "Midfield";
    return "Attack";
  }

  function scoreTone(score) {
    if (score == null || Number.isNaN(Number(score))) {
      return { cls: "is-none", label: "No score" };
    }
    const value = Number(score);
    if (value >= 70) return { cls: "is-hot", label: "Strong" };
    if (value >= 55) return { cls: "is-good", label: "Useful" };
    if (value >= 40) return { cls: "is-mid", label: "Average" };
    return { cls: "is-low", label: "Low" };
  }

  function shirtNo(player) {
    const raw = player?.shirt_number ?? player?.shirtNumber;
    if (raw == null || raw === "") return "";
    return String(raw);
  }

  function slotRank(player) {
    const pos = positionShort(player);
    const order = { GK: 0, LB: 1, LWB: 1, CB: 2, RB: 3, RWB: 3, DM: 4, CM: 5, AM: 6, LW: 7, CF: 8, ST: 8, RW: 9 };
    let rank = order[pos] ?? 20;
    if (pos === "CB") {
      const hint = playerSideHint(player);
      if (hint === "left") rank -= 0.2;
      if (hint === "right") rank += 0.2;
    }
    return rank;
  }

  function sortBenchPlayers(players) {
    return [...players].sort((a, b) => {
      if (slotRank(a) !== slotRank(b)) return slotRank(a) - slotRank(b);
      return (Number(b.minutes) || Number(b.overall) || 0) - (Number(a.minutes) || Number(a.overall) || 0);
    });
  }

  function playerRow(player, side, club) {
    const id = String(player.player_id || "");
    const on = id && Number(id) === Number(state.playerId) ? " is-on" : "";
    const src = photoUrl(player, club);
    const initials = playerInitials(player.name);
    const pos = positionShort(player);
    const score = player.overall == null ? null : Math.round(Number(player.overall));
    const tone = scoreTone(score);
    const shirt = shirtNo(player);
    const note = player.has_scout_note
      ? `<span class="vw-dot" title="${escapeHtml(player.scout_comment || "Has a note")}"></span>`
      : "";
    return `<button type="button" class="vw-player${on}${player.u27 ? " is-u27" : ""}${player.has_scout_note ? " has-note" : ""} ${tone.cls}" data-player="${escapeHtml(id)}" data-side="${side}">
      <span class="vw-player__no">${shirt ? escapeHtml(shirt) : "—"}</span>
      <span class="vw-player__face">
        ${src ? `<img class="vw-player__photo" src="${escapeHtml(src)}" alt="" data-photo-fallback />` : ""}
        <span class="vw-player__photo is-fallback" data-photo-slot ${src ? "hidden" : ""}>${escapeHtml(initials)}</span>
      </span>
      <span class="vw-player__name">${note}${escapeHtml(player.name || "—")}<small>${escapeHtml(player.scout_comment || playerMeta(player))}</small></span>
      <span class="vw-player__pos">${escapeHtml(pos)}</span>
      <span class="vw-player__score">${score == null ? "—" : score}</span>
    </button>`;
  }

  function sheetColumn(side, team) {
    const players = team?.players || [];
    const xi = sideXi(side);
    const bench = sideSubs(side);
    const noted = players.filter((row) => row.has_scout_note).length;
    const u27 = players.filter((row) => row.u27).length;
    if (!players.length) {
      return `
        <div class="vw-sheet__head">
          <h2>${badge(team?.image_url, sideName(team))}${escapeHtml(sideName(team) || (side === "home" ? "Home" : "Away"))}</h2>
          <span>Match XI</span>
        </div>
        <div class="vw-sheet__list"><p class="vw-sheet__empty">${escapeHtml(lineupEmptyCopy(team))}</p></div>
      `;
    }
    const html = [`<div class="vw-unit is-xi">Starting XI</div>`];
    for (const player of xi) html.push(playerRow(player, side, team?.name));
    if (bench.length) {
      html.push(`<div class="vw-unit is-sub">Substitutes</div>`);
      for (const player of bench) html.push(playerRow(player, side, team?.name));
    }
    return `
      <div class="vw-sheet__head">
        <h2>${badge(team?.image_url, sideName(team))}${escapeHtml(sideName(team) || (side === "home" ? "Home" : "Away"))}</h2>
        <span>${xi.length} start · ${bench.length} sub${u27 ? ` · ${u27} U27` : ""}${noted ? ` · ${noted} notes` : ""}</span>
      </div>
      <label class="vw-shape">
        <span>Formation</span>
        <select data-formation="${side}">${formationOptions(side)}</select>
      </label>
      <div class="vw-sheet__list">${html.join("")}</div>
    `;
  }

  function lastName(name) {
    const parts = String(name || "").trim().split(/\s+/);
    return parts[parts.length - 1] || name || "—";
  }

  function minutesPct(player, squad) {
    const minutes = Number(player?.minutes) || 0;
    const max = Math.max(1, ...((squad || []).map((row) => Number(row.minutes) || 0)));
    if (!minutes) return null;
    return Math.round((minutes / max) * 100);
  }

  function formationOptions(side) {
    const current = sideFormation(side);
    return Object.keys(FORMATIONS)
      .map((name) => `<option value="${escapeHtml(name)}" ${name === current ? "selected" : ""}>${escapeHtml(name)}</option>`)
      .join("");
  }

  function fieldMarkings() {
    return `<div class="vw-field__marks" aria-hidden="true">
      <b class="vw-field__box vw-field__box--top"></b>
      <b class="vw-field__six vw-field__six--top"></b>
      <b class="vw-field__box vw-field__box--bot"></b>
      <b class="vw-field__six vw-field__six--bot"></b>
      <b class="vw-field__half"></b>
      <b class="vw-field__circle"></b>
    </div>`;
  }

  function fieldPlayer(player, side, squad) {
    const id = String(player.player_id || "");
    const on = id && Number(id) === Number(state.playerId) ? " is-on" : "";
    const src = photoUrl(player, state.sheet?.[side]?.name);
    const initials = playerInitials(player.name);
    const shirt = shirtNo(player);
    const pct = minutesPct(player, squad);
    const score = player.overall == null ? null : Math.round(Number(player.overall));
    const tone = scoreTone(score);
    return `<button type="button" class="vw-dot${on} ${tone.cls}" data-player="${escapeHtml(id)}" data-side="${side}" style="left:${Number(player.x_pct) || 50}%;top:${Number(player.y_pct) || 50}%">
      <span class="vw-dot__face">
        ${src ? `<img class="vw-player__photo" src="${escapeHtml(src)}" alt="" data-photo-fallback />` : ""}
        <span class="vw-player__photo is-fallback" data-photo-slot ${src ? "hidden" : ""}>${escapeHtml(initials)}</span>
        <em>${pct == null ? "n.a." : `${pct}%`}</em>
      </span>
      ${shirt ? `<small class="vw-dot__no">${escapeHtml(shirt)}</small>` : ""}
      <strong>${escapeHtml(lastName(player.name))}</strong>
    </button>`;
  }

  function formationColumn(side, team) {
    const players = team?.players || [];
    const xi = sideXi(side);
    const bench = sideSubs(side);
    const noted = players.filter((row) => row.has_scout_note).length;
    const u27 = players.filter((row) => row.u27).length;
    if (!players.length) {
      return `
        <div class="vw-sheet__head">
          <h2>${badge(team?.image_url, sideName(team))}${escapeHtml(sideName(team) || (side === "home" ? "Home" : "Away"))}</h2>
          <span>Match XI</span>
        </div>
        <p class="vw-sheet__empty">${escapeHtml(lineupEmptyCopy(team))}</p>
      `;
    }
    return `
      <div class="vw-sheet__head">
        <h2>${badge(team?.image_url, sideName(team))}${escapeHtml(sideName(team) || (side === "home" ? "Home" : "Away"))}</h2>
        <span>${xi.length} start · ${bench.length} on${u27 ? ` · ${u27} U27` : ""}${noted ? ` · ${noted} notes` : ""}</span>
      </div>
      <label class="vw-shape">
        <span>Formation</span>
        <select data-formation="${side}">${formationOptions(side)}</select>
      </label>
      <div class="vw-field">${fieldMarkings()}${xi.map((player) => fieldPlayer(player, side, players)).join("")}</div>
    `;
  }

  function bindDeskPlayers(root) {
    root.querySelectorAll("[data-player]").forEach((btn) => {
      btn.addEventListener("click", () => openPlayer(Number(btn.dataset.player)));
      btn.addEventListener("mouseenter", () => showPlayerTip(btn));
      btn.addEventListener("mouseleave", hidePlayerTip);
      btn.addEventListener("focus", () => showPlayerTip(btn));
      btn.addEventListener("blur", hidePlayerTip);
    });
  }

  function renderSheets() {
    hidePlayerTip();
    const sheet = state.sheet;
    const formation = state.deskView === "formation";
    els.desk?.classList.toggle("is-sheet", !formation);
    document.querySelector(".vw-pitch")?.classList.toggle("is-formation", formation);
    if (!sheet) {
      els.home.innerHTML = `<div class="vw-sheet__empty">Pick a game</div>`;
      els.away.innerHTML = `<div class="vw-sheet__empty">Pick a game</div>`;
      els.match.innerHTML = "";
      return;
    }
    const pct = watchPct(sheet);
    const watch = watchMeta(pct);
    els.match.innerHTML = `
      ${leagueMarks(sheet.league)}
      <strong>${escapeHtml(fixtureLabel(sheet))}</strong>
      <span>${escapeHtml(sheet.league || "")}</span>
      <span>${escapeHtml(formatDate(sheet.date, "long"))}${sheet.played ? " · Played" : " · Upcoming"}</span>
      ${sheet.score ? `<span>${escapeHtml(sheet.score)}</span>` : ""}
      <span style="color:${watch.color}">${escapeHtml(watch.text)}${pct != null ? ` · ${pct}%` : ""}</span>
    `;
    els.home.innerHTML = formation ? formationColumn("home", sheet.home) : sheetColumn("home", sheet.home);
    els.away.innerHTML = formation ? formationColumn("away", sheet.away) : sheetColumn("away", sheet.away);
    bindPhotos(els.home);
    bindPhotos(els.away);
    document.querySelectorAll(".vw-sheet__list").forEach((list) => {
      list.addEventListener("scroll", hidePlayerTip, { passive: true });
    });
    bindDeskPlayers(els.home);
    bindDeskPlayers(els.away);
    document.querySelectorAll("[data-formation]").forEach((select) => {
      select.addEventListener("change", () => {
        state.formations[select.dataset.formation] = select.value;
        renderSheets();
      });
    });
    if (els.empty) {
      els.empty.querySelector("p").textContent = formation
        ? "Pick a player from either formation"
        : "Pick a player from either team sheet";
    }
  }

  function hidePlayerTip() {
    if (!els.tip) return;
    els.tip.classList.add("hidden");
    els.tip.innerHTML = "";
  }

  function showPlayerTip(btn) {
    if (!els.tip) return;
    const player = findSheetPlayer(Number(btn.dataset.player));
    if (!player) return;
    const score = player.overall == null ? null : Math.round(Number(player.overall));
    const tone = scoreTone(score);
    const pos = positionShort(player);
    const shirt = shirtNo(player);
    const src = photoUrl(player);
    const profiles = (player.profiles || [])
      .slice(0, 4)
      .map((row) => `<span>${escapeHtml(row.label)} <b>${row.score}</b></span>`)
      .join("");
    els.tip.className = `vw-tip ${tone.cls}`;
    els.tip.innerHTML = `
      <div class="vw-tip__top">
        ${src ? `<img src="${escapeHtml(src)}" alt="" />` : `<span>${escapeHtml(playerInitials(player.name))}</span>`}
        <div>
          <strong>${escapeHtml(player.name || "Player")}</strong>
          <p>${shirt ? `#${escapeHtml(shirt)} · ` : ""}${escapeHtml(pos)}${player.age != null ? ` · ${player.age}y` : ""}${player.u27 ? " · U27" : ""}</p>
        </div>
        <em>${score == null ? "—" : score}</em>
      </div>
      ${profiles ? `<div class="vw-tip__profiles">${profiles}</div>` : ""}
      ${player.scout_comment ? `<p class="vw-tip__note">${escapeHtml(player.scout_comment)}</p>` : ""}
      <p class="vw-tip__meta">${escapeHtml(tone.label)}${player.minutes ? ` · ${player.minutes}′` : ""}</p>
    `;
    const box = btn.getBoundingClientRect();
    const width = 280;
    let left = box.right + 10;
    if (left + width > window.innerWidth - 12) left = box.left - width - 10;
    let top = box.top;
    els.tip.style.left = `${Math.max(12, left)}px`;
    els.tip.style.top = `${Math.max(12, top)}px`;
    const tipBox = els.tip.getBoundingClientRect();
    if (tipBox.bottom > window.innerHeight - 12) {
      els.tip.style.top = `${Math.max(12, window.innerHeight - tipBox.height - 12)}px`;
    }
  }

  function starPicker(kind, value) {
    return Array.from({ length: 5 }, (_, idx) => {
      const score = idx + 1;
      return `<button type="button" class="${score <= value ? "is-on" : ""}" data-star="${kind}" data-score="${score}" aria-label="${score} stars">★</button>`;
    }).join("");
  }

  function entryCard(row) {
    const kind = row.kind === "report" ? "Report" : "Note";
    return `<article class="vw-entry">
      <h3>${escapeHtml(row.fixture || kind)}</h3>
      <small>${[kind, row.staff, row.date].filter(Boolean).map(escapeHtml).join(" · ")}</small>
      ${row.summary ? `<p>${escapeHtml(row.summary)}</p>` : ""}
    </article>`;
  }

  function renderProfile() {
    const player = state.player;
    if (!player) {
      els.empty.classList.remove("hidden");
      els.profile.classList.add("hidden");
      els.profile.innerHTML = "";
      return;
    }
    els.empty.classList.add("hidden");
    els.profile.classList.remove("hidden");
    const initials = playerInitials(player.name);
    const src = photoUrl(player);
    const profiles = (player.profiles || [])
      .slice(0, 8)
      .map((row) => `<span class="vw-profile-score">${escapeHtml(row.label)}<strong>${row.score}</strong></span>`)
      .join("");
    const history = [...(player.reports || []), ...(player.notes || [])].sort((a, b) =>
      String(b.marked_at || b.date || "").localeCompare(String(a.marked_at || a.date || ""))
    );
    const writing = state.tab !== "notes";
    const draftText =
      state.draft.text ||
      (state.kind === "comment" ? player.scout_comment || "" : "");
    const reportFields =
      writing && state.kind === "report"
        ? `<div class="vw-form__row">
            <label>CA
              <div class="vw-stars" id="vwCa">${starPicker("ca", state.ca)}</div>
            </label>
            <label>PA
              <div class="vw-stars" id="vwPa">${starPicker("pa", state.pa)}</div>
            </label>
            <span></span>
          </div>`
        : "";
    const placeholder =
      state.kind === "report"
        ? "What did you see? Strengths, weaknesses, role fit…"
        : state.kind === "note"
          ? "Work update, agent chat, chasing, or a longer look…"
          : "Quick comment on this player — saved to Scoutable Teams and the player page.";
    const formHint =
      state.kind === "report"
        ? "Full report — saved on the player page with CA / PA."
        : state.kind === "note"
          ? "Longer note — stays on the player page."
          : "Latest comment on Scoutable Teams and Who to Scout.";
    els.profile.innerHTML = `
      <div class="vw-hero">
        <div class="vw-photo-wrap">
          ${src ? `<img class="vw-photo" src="${escapeHtml(src)}" alt="${escapeHtml(player.name || "")}" data-photo-fallback />` : ""}
          <div class="vw-photo-fallback" data-photo-slot ${src ? "hidden" : ""}>${escapeHtml(initials)}</div>
        </div>
        <div>
          <p>${escapeHtml(player.club || player.team_name || "")}${player.league ? ` · ${escapeHtml(player.league)}` : ""}</p>
          <h2>${escapeHtml(player.name || "Player")}</h2>
          <p>${escapeHtml(playerMeta(player))}${player.overall != null ? ` · Score ${Math.round(Number(player.overall))}` : ""}</p>
          <div class="vw-tags">
            ${player.pipeline ? `<span class="vw-tag">${escapeHtml(player.pipeline.stage_title)}</span>` : ""}
            ${player.u27 ? `<span class="vw-tag">U27</span>` : ""}
            ${player.has_scout_note ? `<span class="vw-tag">Has notes</span>` : ""}
          </div>
        </div>
      </div>
      ${profiles ? `<div class="vw-profiles">${profiles}</div>` : ""}
      <div class="vw-tabs" role="tablist">
        <button type="button" data-tab="write" data-kind="comment" class="${writing && state.kind === "comment" ? "is-on" : ""}">Comment</button>
        <button type="button" data-tab="write" data-kind="note" class="${writing && state.kind === "note" ? "is-on" : ""}">Note</button>
        <button type="button" data-tab="write" data-kind="report" class="${writing && state.kind === "report" ? "is-on" : ""}">Report</button>
        <button type="button" data-tab="notes" class="${writing ? "" : "is-on"}">Notes${history.length ? ` · ${history.length}` : ""}</button>
      </div>
      <div class="vw-body">
        ${
          writing
            ? `<form class="vw-form" id="vwNoteForm">
          <label>${escapeHtml(formHint)}
            <textarea id="vwText" maxlength="2000" placeholder="${escapeHtml(placeholder)}">${escapeHtml(draftText)}</textarea>
          </label>
          <div class="vw-form__row">
            <label>Minute
              <input id="vwMinute" type="number" min="0" max="130" inputmode="numeric" placeholder="—" value="${escapeHtml(state.draft.minute)}" />
            </label>
            <label>Title
              <input id="vwNoteTitle" type="text" maxlength="80" placeholder="${escapeHtml(fixtureLabel(state.sheet) || "Video look")}" value="${escapeHtml(state.draft.title)}" />
            </label>
            <button type="submit" class="vw-save" id="vwSave">Save ${escapeHtml(state.kind)}</button>
          </div>
          ${reportFields}
          <div class="vw-links">
            <a href="${escapeHtml(player.dossier_href || `/player/${player.player_id}`)}">Player page →</a>
            <a href="${escapeHtml(player.scoutable_href || "/scoutable-teams")}">Scoutable Teams →</a>
            <a href="${escapeHtml(player.who_to_scout_href || "/who-to-scout")}">Who to Scout →</a>
          </div>
        </form>`
            : `<div class="vw-history">
          ${history.length ? history.map(entryCard).join("") : `<p class="vw-empty">No notes or reports on this player yet.</p>`}
        </div>`
        }
      </div>
    `;
    bindPhotos(els.profile);
    els.profile.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        captureDraft();
        state.tab = btn.dataset.tab || "write";
        if (btn.dataset.kind) state.kind = btn.dataset.kind;
        renderProfile();
      });
    });
    els.profile.querySelectorAll("[data-star]").forEach((btn) => {
      btn.addEventListener("click", () => {
        captureDraft();
        const next = Number(btn.dataset.score) || 0;
        if (btn.dataset.star === "ca") state.ca = state.ca === next ? 0 : next;
        if (btn.dataset.star === "pa") state.pa = state.pa === next ? 0 : next;
        renderProfile();
      });
    });
    document.getElementById("vwNoteForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      saveCurrent();
    });
  }

  function findSheetPlayer(playerId) {
    const sheet = state.sheet;
    if (!sheet) return null;
    for (const side of ["home", "away"]) {
      const match = (sheet[side]?.players || []).find((row) => Number(row.player_id) === Number(playerId));
      if (match) return match;
    }
    return null;
  }

  function markSheetNote(playerId, comment) {
    const row = findSheetPlayer(playerId);
    if (!row) return;
    row.scout_comment = comment || "";
    row.has_scout_note = Boolean(String(comment || "").trim());
  }

  async function saveCurrent() {
    const player = state.player;
    if (!player) return;
    const text = document.getElementById("vwText")?.value.trim() || "";
    if (!text) {
      setStatus("Write a comment, note, or report first.", "is-error");
      return;
    }
    const btn = document.getElementById("vwSave");
    if (btn) btn.disabled = true;
    setStatus("Saving to Scoutable Teams and the player page…");
    try {
      const minuteRaw = document.getElementById("vwMinute")?.value;
      const data = await fetchJson("/api/video-watch/notes", {
        method: "POST",
        body: JSON.stringify({
          player_id: player.player_id,
          kind: state.kind,
          text,
          title: document.getElementById("vwNoteTitle")?.value.trim() || "",
          match_minute: minuteRaw === "" ? null : Number(minuteRaw),
          fixture_id: state.fixtureId,
          fixture_label: fixtureLabel(state.sheet),
          name: player.name,
          club: player.club || player.team_name || "",
          league: player.league || state.sheet?.league || "",
          position: player.position || "",
          position_label: player.position_label || "",
          age: player.age ?? null,
          current_ability: state.kind === "report" ? state.ca || null : null,
          potential_ability: state.kind === "report" ? state.pa || null : null,
        }),
      });
      state.player = data.player || player;
      markSheetNote(player.player_id, data.scout_comment);
      state.kind = "comment";
      state.tab = "notes";
      state.ca = 0;
      state.pa = 0;
      state.draft = { text: "", minute: "", title: "" };
      setStatus("Saved on Scoutable Teams, Who to Scout, and the player page.", "is-ok");
      renderSheets();
      renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not save", "is-error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function openPlayer(playerId) {
    if (!playerId) return;
    const sheetPlayer = findSheetPlayer(playerId) || {};
    state.playerId = playerId;
    state.player = { ...sheetPlayer, player_id: playerId };
    state.kind = "comment";
    state.tab = "write";
    state.ca = 0;
    state.pa = 0;
    state.draft = { text: sheetPlayer.scout_comment || "", minute: "", title: "" };
    writeUrl();
    renderSheets();
    renderProfile();
    try {
      const params = new URLSearchParams({ player_id: String(playerId) });
      if (sheetPlayer.name) params.set("name", sheetPlayer.name);
      if (sheetPlayer.club || sheetPlayer.team_name) {
        params.set("club", sheetPlayer.club || sheetPlayer.team_name);
      }
      if (sheetPlayer.league || state.sheet?.league) {
        params.set("league", sheetPlayer.league || state.sheet.league);
      }
      if (sheetPlayer.position) params.set("position", sheetPlayer.position);
      if (sheetPlayer.position_label) params.set("position_label", sheetPlayer.position_label);
      if (sheetPlayer.age != null) params.set("age", String(sheetPlayer.age));
      const data = await fetchJson(`/api/video-watch/player?${params}`);
      state.player = {
        ...sheetPlayer,
        ...(data.player || {}),
        profiles: data.player?.profiles?.length ? data.player.profiles : sheetPlayer.profiles || [],
      };
      if (!state.draft.text && state.player.scout_comment) {
        state.draft.text = state.player.scout_comment;
      }
      renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not load player", "is-error");
    }
  }

  async function openFixture(fixtureId) {
    if (!fixtureId) return;
    state.fixtureId = fixtureId;
    writeUrl();
    showView("desk");
    els.home.innerHTML = `<p class="vw-sheet__empty">Loading team sheet…</p>`;
    els.away.innerHTML = `<p class="vw-sheet__empty">Loading team sheet…</p>`;
    els.empty.classList.remove("hidden");
    els.profile.classList.add("hidden");
    state.loadingSheet = true;
    try {
      const sheet = await fetchJson(`/api/video-watch/fixture?fixture_id=${encodeURIComponent(fixtureId)}`);
      state.sheet = sheet;
      if (!state.league) state.league = sheet.league || "";
      showView("desk");
      renderSheets();
      if (state.playerId) await openPlayer(state.playerId);
      else renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not load fixture", "is-error");
      els.home.innerHTML = `<p class="vw-sheet__empty">${escapeHtml(error.message || "Could not load fixture.")}</p>`;
      els.away.innerHTML = `<p class="vw-sheet__empty">Try another game.</p>`;
    } finally {
      state.loadingSheet = false;
    }
  }

  let gamesPoll = 0;

  function scheduleGamesPoll(delayMs) {
    window.clearTimeout(gamesPoll);
    gamesPoll = window.setTimeout(() => loadGames({ silent: true }), delayMs);
  }

  async function loadGames({ silent } = {}) {
    if (!silent) {
      state.loadError = "";
      setStatus("Loading fixtures…");
      renderLeagues();
      renderTools();
    }
    try {
      const payload = await fetchJsonRetry("/api/video-watch/games", { timeoutMs: 20000 });
      state.payload = payload;
      state.loadError = "";
      if (!gamesReady()) {
        setStatus("Building the fixture list… this can take a minute after a restart.");
        scheduleGamesPoll(2500);
        renderLeagues();
        renderTools();
        return;
      }
      window.clearTimeout(gamesPoll);
      setStatus("");
      if (state.fixtureId) {
        await openFixture(state.fixtureId);
      } else if (state.league) {
        renderFixtures();
      } else {
        renderLeagues();
      }
      renderTools();
    } catch (error) {
      state.loadError = friendlyFetchError(error);
      setStatus(state.loadError, "is-error");
      scheduleGamesPoll(4000);
      showView("leagues");
      renderLeagues();
      renderTools();
    }
  }

  async function boot() {
    const params = new URLSearchParams(window.location.search);
    state.league = params.get("league") || "";
    state.club = params.get("club") || "";
    state.phase = params.get("phase") || "played";
    state.sortKey = ["date", "match", "watch"].includes(params.get("sort") || "") ? params.get("sort") : "date";
    state.sortDir = params.get("dir") === "asc" ? "asc" : "desc";
    state.deskView = params.get("desk") === "sheet" ? "sheet" : "formation";
    state.fixtureId = params.get("fixture") || params.get("fixture_id") || "";
    state.playerId = Number(params.get("player") || params.get("player_id") || 0) || null;
    renderLeagues();
    await loadGames();
  }

  boot();
})();
