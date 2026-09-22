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
    tab: "general",
    kind: "comment",
    ca: 0,
    pa: 0,
    draft: { text: "", minute: "", title: "" },
    generalDraft: {
      weather: "",
      weather_note: "",
      pitch: "",
      pitch_note: "",
      notes: "",
      position_in_game: "",
      physical: {},
      profiles: {},
      next_steps: "",
      match_rating: "",
      pvfc_level: "",
      add_to_pipeline: false,
      pipeline_stage: "video_scouted",
      next_action: "",
    },
    detailedDraft: {
      position_in_game: "",
      physical: {},
      profiles: {},
      psychology: {},
      write_up: "",
      next_steps: "",
      match_rating: "",
      pvfc_level: "",
      add_to_pipeline: false,
      pipeline_stage: "video_scouted",
      next_action: "",
    },
    cmsDraft: {
      agent_name: "",
      agent_notes: "",
      contract_expires: "",
      contract_notes: "",
      wages_notes: "",
      other_notes: "",
    },
    loadingSheet: false,
    loadError: "",
    sortKey: "date",
    sortDir: "desc",
    deskView: "sheet",
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
    if (text || minute || title) {
      state.draft = {
        text: text?.value ?? state.draft.text,
        minute: minute?.value ?? state.draft.minute,
        title: title?.value ?? state.draft.title,
      };
    }
    const weather = document.getElementById("vwWeather");
    const generalForm = document.getElementById("vwGeneralForm");
    if (weather || generalForm) {
      state.generalDraft = {
        ...state.generalDraft,
        weather: document.getElementById("vwWeather")?.value ?? state.generalDraft.weather,
        weather_note: document.getElementById("vwWeatherNote")?.value ?? state.generalDraft.weather_note,
        pitch: document.getElementById("vwPitch")?.value ?? state.generalDraft.pitch,
        pitch_note: document.getElementById("vwPitchNote")?.value ?? state.generalDraft.pitch_note,
        notes: document.getElementById("vwGeneralNotes")?.value ?? state.generalDraft.notes,
        position_in_game: document.getElementById("vwGamePosition")?.value ?? state.generalDraft.position_in_game,
        physical: collectKeyedFields("data-physical"),
        profiles: { ...state.generalDraft.profiles, ...collectKeyedFields("data-profile") },
        next_steps: document.getElementById("vwGeneralNextSteps")?.value ?? state.generalDraft.next_steps,
        add_to_pipeline: Boolean(document.getElementById("vwGeneralAddPipeline")?.checked),
        pipeline_stage: document.getElementById("vwGeneralPipelineStage")?.value ?? state.generalDraft.pipeline_stage,
      };
    }
    const detailedForm = document.getElementById("vwDetailedForm");
    if (detailedForm) {
      state.detailedDraft = {
        ...state.detailedDraft,
        position_in_game: document.getElementById("vwDetailedPosition")?.value ?? state.detailedDraft.position_in_game,
        physical: collectKeyedFields("data-detailed-physical"),
        profiles: { ...state.detailedDraft.profiles, ...collectKeyedFields("data-detailed-profile") },
        psychology: {
          ...state.detailedDraft.psychology,
          notes: document.getElementById("vwPsychNotes")?.value ?? state.detailedDraft.psychology?.notes ?? "",
        },
        write_up: document.getElementById("vwWriteUp")?.value ?? state.detailedDraft.write_up,
        next_steps: document.getElementById("vwNextSteps")?.value ?? state.detailedDraft.next_steps,
        add_to_pipeline: Boolean(document.getElementById("vwAddPipeline")?.checked),
        pipeline_stage: document.getElementById("vwPipelineStage")?.value ?? state.detailedDraft.pipeline_stage,
      };
    }
    const agentName = document.getElementById("vwAgentName");
    if (agentName) {
      state.cmsDraft = {
        agent_name: agentName.value,
        agent_notes: document.getElementById("vwAgentNotes")?.value ?? "",
        contract_expires: document.getElementById("vwContractExpires")?.value ?? "",
        contract_notes: document.getElementById("vwContractNotes")?.value ?? "",
        wages_notes: document.getElementById("vwWagesNotes")?.value ?? "",
        other_notes: document.getElementById("vwOtherNotes")?.value ?? "",
      };
    }
  }

  function collectKeyedFields(attr) {
    const out = {};
    document.querySelectorAll(`[${attr}]`).forEach((node) => {
      out[node.getAttribute(attr)] = node.value || "";
    });
    return out;
  }

  function fixtureLabel(row) {
    if (!row) return "";
    return `${sideName(row.home)} vs ${sideName(row.away)}`;
  }

  function fixtureContext() {
    const sheet = state.sheet || {};
    const player = state.player || {};
    return {
      fixture_id: state.fixtureId || sheet.fixture_id || "",
      fixture_label: fixtureLabel(sheet),
      home_name: sideName(sheet.home),
      away_name: sideName(sheet.away),
      sheet_side: player.sheet_side || "",
    };
  }

  const DEFAULT_WEATHER = [
    ["dry", "Dry"],
    ["light-rain", "Light rain"],
    ["heavy-rain", "Heavy rain"],
    ["snow", "Snow"],
    ["windy", "Windy"],
    ["cold", "Cold"],
    ["hot", "Hot"],
    ["mixed", "Mixed"],
  ];
  const DEFAULT_PITCH = [
    ["excellent", "Excellent"],
    ["good", "Good"],
    ["average", "Average"],
    ["soft", "Soft / wet"],
    ["heavy", "Heavy"],
    ["worn", "Worn / patchy"],
    ["uneven", "Uneven / bobbly"],
    ["hard", "Hard / frozen"],
  ];

  function reportOptions(kind) {
    const rows = state.player?.options?.[kind] || [];
    if (rows.length) return rows.map((row) => [row.id, row.label]);
    return kind === "pitch" ? DEFAULT_PITCH : DEFAULT_WEATHER;
  }

  function selectOptions(kind, selected) {
    const value = selected || "";
    const options = reportOptions(kind)
      .map(([id, label]) => `<option value="${escapeHtml(id)}" ${id === value ? "selected" : ""}>${escapeHtml(label)}</option>`)
      .join("");
    return `<option value="">Select…</option>${options}`;
  }

  function matchConditions() {
    return state.player?.match_conditions || state.sheet?.match_conditions || {};
  }

  function applyMatchConditions(conditions) {
    if (!conditions) return;
    if (state.sheet) state.sheet.match_conditions = conditions;
    if (state.player) state.player.match_conditions = conditions;
  }

  function defaultPosition(player) {
    return (
      state.generalDraft.position_in_game ||
      player?.general_report?.position_in_game ||
      player?.position ||
      player?.formation_slot ||
      ""
    );
  }

  function fillGeneralDraft(player) {
    const conditions = player?.match_conditions || state.sheet?.match_conditions || {};
    const general = player?.general_report || {};
    state.generalDraft = {
      weather: conditions.weather || "",
      weather_note: conditions.weather_note || "",
      pitch: conditions.pitch || "",
      pitch_note: conditions.pitch_note || "",
      notes: general.notes || "",
      position_in_game: general.position_in_game || player?.position || "",
      physical: { ...(general.physical || {}) },
      profiles: { ...(general.profiles || {}) },
      next_steps: general.next_steps || "",
      match_rating: general.match_rating == null ? "" : String(general.match_rating),
      pvfc_level: general.pvfc_level || "",
      add_to_pipeline: Boolean(general.add_to_pipeline),
      pipeline_stage: general.pipeline_stage || "video_scouted",
      next_action: general.next_action || "",
    };
  }

  function fillCmsDraft(player) {
    const cms = player?.cms || {};
    state.cmsDraft = {
      agent_name: cms.agent_name || "",
      agent_notes: cms.agent_notes || "",
      contract_expires: cms.contract_expires || "",
      contract_notes: cms.contract_notes || "",
      wages_notes: cms.wages_notes || "",
      other_notes: cms.other_notes || "",
    };
  }

  function fillDetailedDraft(player) {
    const detailed = player?.detailed_report || {};
    const general = player?.general_report || {};
    state.detailedDraft = {
      position_in_game: detailed.position_in_game || general.position_in_game || player?.position || "",
      physical: { ...(detailed.physical || general.physical || {}) },
      profiles: { ...(detailed.profiles || general.profiles || {}) },
      psychology: { ...(detailed.psychology || {}) },
      write_up: detailed.write_up || "",
      next_steps: detailed.next_steps || general.next_steps || "",
      match_rating:
        detailed.match_rating == null
          ? general.match_rating == null
            ? ""
            : String(general.match_rating)
          : String(detailed.match_rating),
      pvfc_level: detailed.pvfc_level || general.pvfc_level || "",
      add_to_pipeline: Boolean(detailed.add_to_pipeline || general.add_to_pipeline),
      pipeline_stage: detailed.pipeline_stage || general.pipeline_stage || "video_scouted",
      next_action: detailed.next_action || general.next_action || "",
    };
  }

  function homeAwayCopy(player) {
    const row = player?.home_away || {};
    if (row.label) {
      const source = row.source === "match title" ? "auto from match title" : row.source || "auto";
      return { label: row.label, source };
    }
    if (player?.sheet_side === "home" || player?.sheet_side === "away") {
      return {
        label: player.sheet_side === "home" ? "Home" : "Away",
        source: "team sheet",
      };
    }
    return { label: "—", source: "set from the match title" };
  }

  function conditionsChips(conditions) {
    const bits = [];
    if (conditions?.weather_label) bits.push(conditions.weather_label);
    if (conditions?.pitch_label) bits.push(conditions.pitch_label);
    return bits;
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
    if (state.deskView && state.deskView !== "sheet") params.set("desk", state.deskView);
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
        state.deskView = btn.dataset.desk || "sheet";
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
    const conditions = matchConditions();
    const chips = conditionsChips(conditions);
    els.match.innerHTML = `
      ${leagueMarks(sheet.league)}
      <strong>${escapeHtml(fixtureLabel(sheet))}</strong>
      <span>${escapeHtml(sheet.league || "")}</span>
      <span>${escapeHtml(formatDate(sheet.date, "long"))}${sheet.played ? " · Played" : " · Upcoming"}</span>
      ${sheet.score ? `<span>${escapeHtml(sheet.score)}</span>` : ""}
      <span style="color:${watch.color}">${escapeHtml(watch.text)}${pct != null ? ` · ${pct}%` : ""}</span>
      ${chips.map((chip) => `<span class="vw-meta-chip">${escapeHtml(chip)}</span>`).join("")}
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

  function entryCard(row) {
    const kind = row.kind === "report" ? "Report" : "Note";
    return `<article class="vw-entry">
      <h3>${escapeHtml(row.fixture || kind)}</h3>
      <small>${[kind, row.staff, row.date].filter(Boolean).map(escapeHtml).join(" · ")}</small>
      ${row.summary ? `<p>${escapeHtml(row.summary)}</p>` : ""}
    </article>`;
  }

  function playerHistory(player) {
    return [...(player.reports || []), ...(player.notes || [])].sort((a, b) =>
      String(b.marked_at || b.date || "").localeCompare(String(a.marked_at || a.date || ""))
    );
  }

  function optionList(kind) {
    return state.player?.options?.[kind] || [];
  }

  function positionChoices() {
    const rows = optionList("positions");
    if (rows.length) return rows;
    return [
      { id: "GOALKEEPER", short: "GK", label: "Goalkeeper" },
      { id: "LEFT_WINGBACK_DEFENDER", short: "LB", label: "Left back / wing-back" },
      { id: "CENTRAL_DEFENDER", short: "CB", label: "Centre-back" },
      { id: "RIGHT_WINGBACK_DEFENDER", short: "RB", label: "Right back / wing-back" },
      { id: "DEFENSE_MIDFIELD", short: "DM", label: "Defensive midfield" },
      { id: "CENTRAL_MIDFIELD", short: "CM", label: "Central midfield" },
      { id: "ATTACKING_MIDFIELD", short: "AM", label: "Attacking midfield" },
      { id: "LEFT_WINGER", short: "LW", label: "Left winger" },
      { id: "RIGHT_WINGER", short: "RW", label: "Right winger" },
      { id: "CENTER_FORWARD", short: "ST", label: "Centre-forward" },
    ];
  }

  function positionSelect(id, selected) {
    const value = selected || "";
    const options = positionChoices()
      .map((row) => `<option value="${escapeHtml(row.id)}" ${row.id === value ? "selected" : ""}>${escapeHtml(row.short)} · ${escapeHtml(row.label)}</option>`)
      .join("");
    return `<select id="${id}"><option value="">Select position in game</option>${options}</select>`;
  }

  const LOCKED_PROFILES = {
    GOALKEEPER: ["shot-stopping", "box-goalkeeper", "sweeper", "ball-playing"],
    CENTRAL_DEFENDER: ["defensive", "defender", "progressor", "ball-playing"],
    LEFT_WINGBACK_DEFENDER: ["defender", "offensive", "deep-creator", "wide-presser", "wide-ball-carrier", "wide-creator"],
    RIGHT_WINGBACK_DEFENDER: ["defender", "offensive", "deep-creator", "wide-presser", "wide-ball-carrier", "wide-creator"],
    DEFENSE_MIDFIELD: ["ball-winner", "ball-progressor", "deep-creator", "presser", "ball-carrier"],
    CENTRAL_MIDFIELD: ["goal-threat", "running-threat", "ball-winner", "creator", "ball-progressor"],
    ATTACKING_MIDFIELD: ["creator", "goal-threat", "presser", "ball-carrier", "threat-in-behind"],
    LEFT_WINGER: ["wide-creator", "wide-goal-threat", "wide-presser", "wide-ball-carrier", "threat-in-behind"],
    RIGHT_WINGER: ["wide-creator", "wide-goal-threat", "wide-presser", "wide-ball-carrier", "threat-in-behind"],
    CENTER_FORWARD: ["goal-threat", "hold-up", "presser", "threat-in-behind", "ball-carrier"],
  };
  const PROFILE_LABELS = {
    "shot-stopping": "Shot Stopping",
    "box-goalkeeper": "Box Goalkeeper",
    "sweeper": "Sweeper",
    "ball-playing": "Ball Playing",
    defensive: "Defensive",
    defender: "Defender",
    progressor: "Progressor",
    offensive: "Offensive",
    "deep-creator": "Deep Creator",
    "wide-presser": "Wide Presser",
    "wide-ball-carrier": "Wide Ball Carrier",
    "wide-creator": "Wide Creator",
    "ball-winner": "Ball Winner",
    "ball-progressor": "Ball Progressor",
    presser: "Presser",
    "ball-carrier": "Ball Carrier",
    "goal-threat": "Goal Threat",
    "running-threat": "Running Threat",
    creator: "Creator",
    "threat-in-behind": "Threat In Behind",
    "wide-goal-threat": "Wide Goal Threat",
    "hold-up": "Hold Up",
  };

  function profilesFor(position, player) {
    const wanted = position || "";
    if (!wanted) return [];
    const lockedIds = LOCKED_PROFILES[wanted] || [];
    const byPos = player?.options?.profiles_by_position
      || state.player?.options?.profiles_by_position
      || {};
    const fromApi = byPos[wanted] || [];
    const byId = {};
    fromApi.forEach((row) => {
      if (row?.id) byId[row.id] = row;
    });
    (player?.report_profiles || []).forEach((row) => {
      if (row?.id && lockedIds.includes(row.id)) byId[row.id] = { ...byId[row.id], ...row };
    });
    if (lockedIds.length) {
      return lockedIds.map((id) => byId[id] || {
        id,
        key: id,
        label: PROFILE_LABELS[id] || id,
        score: null,
        general_prompt: "What did you see in this part of his game?",
        detailed_prompt: "Break this profile down. Why did it look good or poor?",
      });
    }
    return fromApi;
  }

  function keepProfilesForPosition(profiles, position, player) {
    const allowed = new Set(profilesFor(position, player).map((row) => row.id));
    const source = profiles || {};
    if (!allowed.size) return {};
    return Object.fromEntries(
      Object.entries(source).filter(([key]) => allowed.has(key))
    );
  }

  function chipRow(kind, value, rows) {
    return `<div class="vw-chips" role="group">${rows
      .map((row) => {
        const on = String(value || "") === String(row.id);
        const title = row.hint ? ` title="${escapeHtml(row.hint)}"` : "";
        return `<button type="button" class="${on ? "is-on" : ""}" data-chip="${escapeHtml(kind)}" data-value="${escapeHtml(row.id)}"${title}>${escapeHtml(row.label)}</button>`;
      })
      .join("")}</div>`;
  }

  function physicalFields(fields, values, attr, promptKey) {
    const rows = fields.length ? fields : [
      { id: "size", label: "Size", prompt: "Frame, height, strength in duels and hold-up.", detailed_prompt: "How big vs the opponent? Who wins aerials and hold-up, and how?" },
      { id: "mobility", label: "Mobility", prompt: "Pace, recovery runs, agility.", detailed_prompt: "Pace over 10 yards, recovery, agility. Did they last, or drop off late?" },
      { id: "foot", label: "Foot", prompt: "Preferred foot — range of pass, cross, shot.", detailed_prompt: "Preferred foot in this game — what actions did they actually play with it?" },
      { id: "weak_foot", label: "Weak foot", prompt: "Can they use it under pressure?", detailed_prompt: "Can they use the weak foot under pressure, or did they hide it?" },
      { id: "physical_ability", label: "Physical ability", prompt: "Stamina, repeated sprints, how they lasted.", detailed_prompt: "Stamina, repeated sprints, duels. How they lasted — and what dropped off after 70?" },
    ];
    return rows
      .map((row) => {
        const prompt = row[promptKey] || row.prompt || "";
        return `<label>${escapeHtml(row.label)}
        <textarea ${attr}="${escapeHtml(row.id)}" class="vw-notes-box ${promptKey === "detailed_prompt" ? "vw-notes-box--long" : ""}" maxlength="2000" placeholder="${escapeHtml(prompt)}">${escapeHtml(values[row.id] || "")}</textarea>
      </label>`;
      })
      .join("");
  }

  function profileFields(profiles, values, attr, promptKey) {
    if (!profiles.length) {
      return `<p>Pick a position in the game to load the data profiles for that role.</p>`;
    }
    return profiles
      .map((row) => {
        const prompt = row[promptKey] || row.general_prompt || (promptKey === "detailed_prompt"
          ? "How do they progress the ball? What sort of headers do they win? Why did this look good or poor?"
          : "What did you see in this part of his game?");
        const score = row.score != null ? `<em>${escapeHtml(String(row.score))}</em>` : "";
        return `<label>
          <span class="vw-profile-head">${escapeHtml(row.label)}${score}</span>
          <textarea ${attr}="${escapeHtml(row.id)}" class="vw-notes-box ${promptKey === "detailed_prompt" ? "vw-notes-box--long" : ""}" maxlength="4000" placeholder="${escapeHtml(prompt)}">${escapeHtml(values[row.id] || "")}</textarea>
        </label>`;
      })
      .join("");
  }

  function matchConditionsBlock(player, draft) {
    const conditions = matchConditions();
    const homeAway = homeAwayCopy(player);
    const matchName = fixtureLabel(state.sheet) || conditions.fixture_label || "this match";
    const sharedHint = conditions.filled
      ? `Loaded from ${matchName} — change it here and every other report on this game updates.`
      : `Once saved, weather and pitch auto-load on every other report for ${matchName}.`;
    return `<div class="vw-report-grid">
          <label>Home / Away
            <div class="vw-homeaway">
              <strong>${escapeHtml(homeAway.label)}</strong>
              <span>${escapeHtml(homeAway.source)}</span>
            </div>
          </label>
          <label>Match
            <div class="vw-homeaway">
              <strong>${escapeHtml(matchName)}</strong>
            </div>
          </label>
        </div>
        <p>${escapeHtml(sharedHint)}</p>
        <div class="vw-report-grid">
          <label>Weather conditions
            <select id="vwWeather">${selectOptions("weather", draft.weather)}</select>
          </label>
          <label>Pitch conditions
            <select id="vwPitch">${selectOptions("pitch", draft.pitch)}</select>
          </label>
        </div>
        <div class="vw-report-grid">
          <label>Weather note
            <input id="vwWeatherNote" type="text" maxlength="160" placeholder="Wind, temperature, anything else" value="${escapeHtml(draft.weather_note || "")}" />
          </label>
          <label>Pitch note
            <input id="vwPitchNote" type="text" maxlength="160" placeholder="Cut, bobble, heavy areas" value="${escapeHtml(draft.pitch_note || "")}" />
          </label>
        </div>`;
  }

  function decisionOptions() {
    const levels = optionList("pvfc_levels").length
      ? optionList("pvfc_levels")
      : [
          { id: "A", label: "A · Starter" },
          { id: "B", label: "B · Challenger" },
          { id: "C", label: "C · Emerging talent" },
          { id: "D", label: "D · Not to standard" },
        ];
    const actions = optionList("next_actions").length
      ? optionList("next_actions")
      : [
          { id: "not_to_standard", label: "Not to standard" },
          { id: "low_priority", label: "Low priority" },
          { id: "high_priority", label: "High priority" },
          { id: "sign", label: "Sign" },
        ];
    const stages = optionList("pipeline_stages");
    return { levels, actions, stages };
  }

  function decisionBlock(draft, player, prefix) {
    const { levels, actions, stages } = decisionOptions();
    const ratingId = prefix === "general" ? "match_rating_general" : "match_rating";
    const ratingButtons = Array.from({ length: 11 }, (_, idx) => {
      const on = String(draft.match_rating) === String(idx);
      return `<button type="button" class="${on ? "is-on" : ""}" data-chip="${ratingId}" data-value="${idx}">${idx}</button>`;
    }).join("");
    const nextStepsId = prefix === "general" ? "vwGeneralNextSteps" : "vwNextSteps";
    const pipelineId = prefix === "general" ? "vwGeneralAddPipeline" : "vwAddPipeline";
    const stageId = prefix === "general" ? "vwGeneralPipelineStage" : "vwPipelineStage";
    const saveId = prefix === "general" ? "vwSaveGeneral" : "vwSaveDetailed";
    const saveLabel = prefix === "general" ? "Save general report" : "Save detailed report";
    const extraWriteUp = prefix === "detailed"
      ? `<label>General write up
          <textarea id="vwWriteUp" class="vw-notes-box vw-notes-box--long" maxlength="4000" placeholder="The match in full — what he is, what he is not, and whether he fits us.">${escapeHtml(draft.write_up || "")}</textarea>
        </label>`
      : "";
    return `
        ${extraWriteUp}
        <label>Next step recommendations
          <textarea id="${nextStepsId}" class="vw-notes-box" maxlength="4000" placeholder="Watch again live, compare vs our 8, leave, or push to the board.">${escapeHtml(draft.next_steps || "")}</textarea>
        </label>
        <label>Match rating · 0–10
          <div class="vw-chips vw-rating">${ratingButtons}</div>
        </label>
        <label>PVFC player level
          ${chipRow(prefix === "general" ? "pvfc_level_general" : "pvfc_level", draft.pvfc_level, levels.map((row) => ({ id: row.id, label: `${row.id} · ${row.label}`, hint: row.hint })))}
        </label>
        <label>Next action
          ${chipRow(prefix === "general" ? "next_action_general" : "next_action", draft.next_action, actions)}
        </label>
        <label class="vw-check">
          <input id="${pipelineId}" type="checkbox" ${draft.add_to_pipeline ? "checked" : ""} />
          Add to pipeline
        </label>
        <label>Pipeline stage
          <select id="${stageId}">${(stages.length ? stages : [{ id: "video_scouted", label: "Video scouted" }])
            .map((row) => `<option value="${escapeHtml(row.id)}" ${row.id === (draft.pipeline_stage || "video_scouted") ? "selected" : ""}>${escapeHtml(row.label)}</option>`)
            .join("")}</select>
        </label>
        ${player.pipeline ? `<p>Currently on ${escapeHtml(player.pipeline.stage_title)} · <a href="/player-pipelines">Open pipelines →</a></p>` : `<p><a href="/player-pipelines">Player Pipelines →</a></p>`}
        <div class="vw-form__row vw-form__row--save">
          <span></span>
          <button type="submit" class="vw-save" id="${saveId}">${saveLabel}</button>
        </div>`;
  }

  function generalReportBody(player) {
    const draft = state.generalDraft;
    const position = draft.position_in_game || "";
    const profiles = profilesFor(position, player);
    return `<form class="vw-report" id="vwGeneralForm">
      <section class="vw-report-block">
        <div>
          <h3>General</h3>
          <p>Asked on every position. Match conditions are shared across every player report on this game. Set the position to load that role’s profiles only.</p>
        </div>
        ${matchConditionsBlock(player, draft)}
        <label>Position in game
          ${positionSelect("vwGamePosition", position)}
        </label>
      </section>
      <section class="vw-report-block">
        <div>
          <h3>Physical</h3>
          <p>Size, mobility, foot, weak foot, physical ability — same questions for every role.</p>
        </div>
        ${physicalFields(optionList("physical"), draft.physical || {}, "data-physical", "prompt")}
      </section>
      <section class="vw-report-block">
        <div>
          <h3>Data profiles</h3>
          <p>Titles match the data profiles for the position you set. A CM only gets Goal Threat, Running Threat, Ball Winner, Creator and Ball Progressor.</p>
        </div>
        ${profileFields(profiles, draft.profiles || {}, "data-profile", "general_prompt")}
      </section>
      <section class="vw-report-block">
        <label>Anything else for this match
          <textarea id="vwGeneralNotes" class="vw-notes-box" maxlength="2000" placeholder="First look, role, anything that is not position-specific yet.">${escapeHtml(draft.notes || "")}</textarea>
        </label>
        ${decisionBlock(draft, player, "general")}
      </section>
    </form>`;
  }

  function detailedReportBody(player) {
    const conditions = matchConditions();
    const chips = conditionsChips(conditions);
    const homeAway = homeAwayCopy(player);
    const draft = state.detailedDraft;
    const position = draft.position_in_game || state.generalDraft.position_in_game || "";
    const profiles = profilesFor(position, player);
    const psych = optionList("psychology");
    const psychValues = draft.psychology || {};
    const yesNo = optionList("yes_mixed_no").length
      ? optionList("yes_mixed_no")
      : [{ id: "yes", label: "Yes" }, { id: "mixed", label: "Mixed" }, { id: "no", label: "No" }];
    const psychBlock = (psych.length ? psych : [
      { id: "work_hard", label: "Worked hard", prompt: "Did he work for the team off the ball?" },
      { id: "leader", label: "Leader", prompt: "Did he organise, demand, or take responsibility?" },
      { id: "booked", label: "Booked", prompt: "Yellow / red, or lucky not to be?" },
      { id: "frustrated", label: "Frustrated", prompt: "Body language when it went against him." },
      { id: "spoke_to_coach", label: "Spoke to the coach", prompt: "Sideline chat, instructions, argument?" },
    ])
      .map((row) => `<div class="vw-psych">
        <p><strong>${escapeHtml(row.label)}</strong> ${escapeHtml(row.prompt || "")}</p>
        ${chipRow(`psych:${row.id}`, psychValues[row.id] || "", row.id === "booked" || row.id === "spoke_to_coach" ? [{ id: "yes", label: "Yes" }, { id: "no", label: "No" }] : yesNo)}
      </div>`)
      .join("");
    return `<form class="vw-report" id="vwDetailedForm">
      <section class="vw-report-block">
        <div>
          <h3>Detailed report</h3>
          <p>Same headings as General, with prompts that push for actions — how they progress the ball, what headers they win, why a profile looked good or poor.</p>
        </div>
        <div class="vw-chip-row">
          ${homeAway.label !== "—" ? `<span class="vw-meta-chip">${escapeHtml(homeAway.label)}</span>` : ""}
          ${chips.map((chip) => `<span class="vw-meta-chip">${escapeHtml(chip)}</span>`).join("")}
          ${!chips.length ? `<span class="vw-meta-chip">Set weather / pitch on General</span>` : ""}
        </div>
        <label>Position in game
          ${positionSelect("vwDetailedPosition", position)}
        </label>
      </section>
      <section class="vw-report-block">
        <div>
          <h3>Physical</h3>
          <p>Size, mobility, foot, weak foot, physical ability — more detail than the first look.</p>
        </div>
        ${physicalFields(optionList("physical"), draft.physical || {}, "data-detailed-physical", "detailed_prompt")}
      </section>
      <section class="vw-report-block">
        <div>
          <h3>Break down the profiles</h3>
          <p>Why did he progress the ball well? Weaknesses? Be specific, not just the data score.</p>
        </div>
        ${profileFields(profiles, draft.profiles || {}, "data-detailed-profile", "detailed_prompt")}
      </section>
      <section class="vw-report-block">
        <div>
          <h3>Psychology</h3>
          <p>Work rate, leadership, bookings, frustration, and whether he spoke to the coach.</p>
        </div>
        ${psychBlock}
        <label>Psychology notes
          <textarea id="vwPsychNotes" class="vw-notes-box" maxlength="4000" placeholder="How did he behave? Body language, reactions, communication with teammates and staff.">${escapeHtml(psychValues.notes || "")}</textarea>
        </label>
      </section>
      <section class="vw-report-block">
        ${decisionBlock(draft, player, "detailed")}
      </section>
    </form>`;
  }

  function notesBody(player) {
    const history = playerHistory(player);
    const draftText = state.draft.text || player.scout_comment || "";
    return `<form class="vw-form" id="vwNoteForm">
      <label>Latest comment on Scoutable Teams and Who to Scout.
        <textarea id="vwText" maxlength="2000" placeholder="Quick comment on this player — saved to Scoutable Teams and the player page.">${escapeHtml(draftText)}</textarea>
      </label>
      <div class="vw-form__row">
        <label>Minute
          <input id="vwMinute" type="number" min="0" max="130" inputmode="numeric" placeholder="—" value="${escapeHtml(state.draft.minute)}" />
        </label>
        <label>Title
          <input id="vwNoteTitle" type="text" maxlength="80" placeholder="${escapeHtml(fixtureLabel(state.sheet) || "Video look")}" value="${escapeHtml(state.draft.title)}" />
        </label>
        <button type="submit" class="vw-save" id="vwSave">Save comment</button>
      </div>
      <div class="vw-links">
        <a href="${escapeHtml(player.dossier_href || `/player/${player.player_id}`)}">Player page →</a>
        <a href="${escapeHtml(player.scoutable_href || "/scoutable-teams")}">Scoutable Teams →</a>
        <a href="${escapeHtml(player.who_to_scout_href || "/who-to-scout")}">Who to Scout →</a>
      </div>
      <div class="vw-history">
        ${history.length ? history.map(entryCard).join("") : `<p class="vw-empty">No notes on Scoutable Teams or the player page yet.</p>`}
      </div>
    </form>`;
  }

  function cmsBody(player) {
    const draft = state.cmsDraft;
    const source = player.cms?.contract_expires_source || "";
    return `<form class="vw-cms-grid" id="vwCmsForm">
      <section class="vw-report-block">
        <div>
          <h3>Player CMS</h3>
          <p>Agent notes, contract info, and internal chasing — stays on this player.</p>
        </div>
        <label>Agent
          <input id="vwAgentName" type="text" maxlength="80" placeholder="Agency / agent name" value="${escapeHtml(draft.agent_name)}" />
        </label>
        <label>Agent notes
          <textarea id="vwAgentNotes" class="vw-notes-box" maxlength="2000" placeholder="Conversations, mandate, who we speak to…">${escapeHtml(draft.agent_notes)}</textarea>
        </label>
        <label>Contract expires
          <input id="vwContractExpires" type="text" maxlength="80" placeholder="${escapeHtml(source || "Jun 2027")}" value="${escapeHtml(draft.contract_expires)}" />
        </label>
        ${source ? `<p>Transfermarkt has ${escapeHtml(source)} on file.</p>` : ""}
        <label>Contract notes
          <textarea id="vwContractNotes" class="vw-notes-box" maxlength="2000" placeholder="Option, release clause, out of contract…">${escapeHtml(draft.contract_notes)}</textarea>
        </label>
        <label>Wages / deal notes
          <textarea id="vwWagesNotes" class="vw-notes-box" maxlength="2000" placeholder="Wage band, add-ons, loan fee…">${escapeHtml(draft.wages_notes)}</textarea>
        </label>
        <label>Other CMS notes
          <textarea id="vwOtherNotes" class="vw-notes-box" maxlength="4000" placeholder="Anything else recruitment need on file.">${escapeHtml(draft.other_notes)}</textarea>
        </label>
        <div class="vw-form__row vw-form__row--save">
          <span></span>
          <button type="submit" class="vw-save" id="vwSaveCms">Save CMS</button>
        </div>
      </section>
    </form>`;
  }

  function profileTabBody(player) {
    if (state.tab === "detailed") return detailedReportBody(player);
    if (state.tab === "notes") return notesBody(player);
    if (state.tab === "cms") return cmsBody(player);
    return generalReportBody(player);
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
    const history = playerHistory(player);
    const tabs = [
      ["general", "General report"],
      ["detailed", "Detailed report"],
      ["notes", `Player notes${history.length ? ` · ${history.length}` : ""}`],
      ["cms", "Player CMS"],
    ];
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
            ${homeAwayCopy(player).label !== "—" ? `<span class="vw-tag">${escapeHtml(homeAwayCopy(player).label)}</span>` : ""}
          </div>
        </div>
      </div>
      ${profiles ? `<div class="vw-profiles">${profiles}</div>` : ""}
      <div class="vw-tabs" role="tablist">
        ${tabs
          .map(
            ([id, label]) =>
              `<button type="button" data-tab="${id}" class="${state.tab === id ? "is-on" : ""}">${escapeHtml(label)}</button>`
          )
          .join("")}
      </div>
      <div class="vw-body">${profileTabBody(player)}</div>
    `;
    bindPhotos(els.profile);
    els.profile.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        captureDraft();
        state.tab = btn.dataset.tab || "general";
        if (state.tab === "detailed") {
          const detailedEmpty = !Object.values(state.detailedDraft.physical || {}).some(Boolean)
            && !Object.values(state.detailedDraft.profiles || {}).some(Boolean);
          if (detailedEmpty) {
            state.detailedDraft.physical = { ...(state.generalDraft.physical || {}) };
            state.detailedDraft.profiles = { ...(state.generalDraft.profiles || {}) };
            state.detailedDraft.position_in_game =
              state.detailedDraft.position_in_game || state.generalDraft.position_in_game;
          }
          if (!state.detailedDraft.next_steps) state.detailedDraft.next_steps = state.generalDraft.next_steps || "";
          if (!state.detailedDraft.match_rating) state.detailedDraft.match_rating = state.generalDraft.match_rating || "";
          if (!state.detailedDraft.pvfc_level) state.detailedDraft.pvfc_level = state.generalDraft.pvfc_level || "";
          if (!state.detailedDraft.next_action) state.detailedDraft.next_action = state.generalDraft.next_action || "";
          if (!state.detailedDraft.add_to_pipeline && state.generalDraft.add_to_pipeline) {
            state.detailedDraft.add_to_pipeline = true;
          }
          if (!state.detailedDraft.pipeline_stage || state.detailedDraft.pipeline_stage === "video_scouted") {
            state.detailedDraft.pipeline_stage = state.generalDraft.pipeline_stage || state.detailedDraft.pipeline_stage;
          }
        }
        renderProfile();
      });
    });
    document.getElementById("vwGeneralForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      saveGeneralReport();
    });
    document.getElementById("vwDetailedForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      saveDetailedReport();
    });
    document.getElementById("vwNoteForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      saveCurrent();
    });
    document.getElementById("vwCmsForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      saveCms();
    });
    document.getElementById("vwGamePosition")?.addEventListener("change", (event) => {
      captureDraft();
      state.generalDraft.position_in_game = event.target.value;
      state.generalDraft.profiles = keepProfilesForPosition(
        state.generalDraft.profiles,
        state.generalDraft.position_in_game,
        state.player
      );
      renderProfile();
    });
    document.getElementById("vwDetailedPosition")?.addEventListener("change", (event) => {
      captureDraft();
      state.detailedDraft.position_in_game = event.target.value;
      state.detailedDraft.profiles = keepProfilesForPosition(
        state.detailedDraft.profiles,
        state.detailedDraft.position_in_game,
        state.player
      );
      renderProfile();
    });
    els.profile.querySelectorAll("[data-chip]").forEach((btn) => {
      btn.addEventListener("click", () => {
        captureDraft();
        const kind = btn.dataset.chip || "";
        const value = btn.dataset.value || "";
        const applyDecision = (draft, field, next) => {
          draft[field] = next;
          if (field === "next_action") {
            if (next === "sign") {
              draft.add_to_pipeline = true;
              draft.pipeline_stage = "scout_identified";
            }
            if (next === "not_to_standard") {
              draft.pvfc_level = draft.pvfc_level || "D";
              draft.pipeline_stage = "not_the_right_fit";
            }
          }
        };
        if (kind === "match_rating") applyDecision(state.detailedDraft, "match_rating", value);
        else if (kind === "match_rating_general") applyDecision(state.generalDraft, "match_rating", value);
        else if (kind === "pvfc_level") applyDecision(state.detailedDraft, "pvfc_level", value);
        else if (kind === "pvfc_level_general") applyDecision(state.generalDraft, "pvfc_level", value);
        else if (kind === "next_action") applyDecision(state.detailedDraft, "next_action", value);
        else if (kind === "next_action_general") applyDecision(state.generalDraft, "next_action", value);
        else if (kind.startsWith("psych:")) {
          const key = kind.slice(6);
          state.detailedDraft.psychology = {
            ...(state.detailedDraft.psychology || {}),
            [key]: value,
          };
        }
        renderProfile();
      });
    });
  }

  function findSheetPlayer(playerId) {
    const sheet = state.sheet;
    if (!sheet) return null;
    for (const side of ["home", "away"]) {
      const match = (sheet[side]?.players || []).find((row) => Number(row.player_id) === Number(playerId));
      if (match) return { ...match, sheet_side: match.sheet_side || side };
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
      setStatus("Write a comment first.", "is-error");
      return;
    }
    const btn = document.getElementById("vwSave");
    if (btn) btn.disabled = true;
    setStatus("Saving to Scoutable Teams and the player page…");
    try {
      const minuteRaw = document.getElementById("vwMinute")?.value;
      const ctx = fixtureContext();
      const data = await fetchJson("/api/video-watch/notes", {
        method: "POST",
        body: JSON.stringify({
          player_id: player.player_id,
          kind: "comment",
          text,
          title: document.getElementById("vwNoteTitle")?.value.trim() || "",
          match_minute: minuteRaw === "" ? null : Number(minuteRaw),
          fixture_id: ctx.fixture_id,
          fixture_label: ctx.fixture_label,
          name: player.name,
          club: player.club || player.team_name || "",
          league: player.league || state.sheet?.league || "",
          position: player.position || "",
          position_label: player.position_label || "",
          age: player.age ?? null,
        }),
      });
      state.player = { ...player, ...(data.player || {}) };
      markSheetNote(player.player_id, data.scout_comment);
      state.tab = "notes";
      state.draft = { text: data.scout_comment || text, minute: "", title: "" };
      setStatus("Saved on Scoutable Teams, Who to Scout, and the player page.", "is-ok");
      renderSheets();
      renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not save", "is-error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveGeneralReport() {
    const player = state.player;
    if (!player) return;
    captureDraft();
    const ctx = fixtureContext();
    if (!ctx.fixture_id) {
      setStatus("Open a match before saving match conditions.", "is-error");
      return;
    }
    const btn = document.getElementById("vwSaveGeneral");
    if (btn) btn.disabled = true;
    setStatus("Saving match conditions…");
    try {
      const data = await fetchJson("/api/video-watch/general-report", {
        method: "POST",
        body: JSON.stringify({
          player_id: player.player_id,
          fixture_id: ctx.fixture_id,
          fixture_label: ctx.fixture_label,
          weather: state.generalDraft.weather,
          weather_note: state.generalDraft.weather_note,
          pitch: state.generalDraft.pitch,
          pitch_note: state.generalDraft.pitch_note,
          notes: state.generalDraft.notes,
          position_in_game: state.generalDraft.position_in_game,
          physical: state.generalDraft.physical,
          profiles: keepProfilesForPosition(
            state.generalDraft.profiles,
            state.generalDraft.position_in_game,
            player
          ),
          next_steps: state.generalDraft.next_steps,
          match_rating: state.generalDraft.match_rating === "" ? null : Number(state.generalDraft.match_rating),
          pvfc_level: state.generalDraft.pvfc_level,
          add_to_pipeline: state.generalDraft.add_to_pipeline,
          pipeline_stage: state.generalDraft.pipeline_stage,
          next_action: state.generalDraft.next_action,
          name: player.name || "",
          club: player.club || player.team_name || "",
          league: player.league || state.sheet?.league || "",
          position: player.position || "",
          position_label: player.position_label || "",
          age: player.age ?? null,
          home_name: ctx.home_name,
          away_name: ctx.away_name,
          sheet_side: ctx.sheet_side,
        }),
      });
      applyMatchConditions(data.match_conditions);
      state.player = {
        ...player,
        ...(data.player || {}),
        position: player.position || data.player?.position || "",
        position_label: player.position_label || data.player?.position_label || "",
        profiles: data.player?.profiles?.length ? data.player.profiles : player.profiles || [],
        sheet_side: player.sheet_side || data.player?.sheet_side || "",
      };
      fillGeneralDraft(state.player);
      const pipeline = data.pipeline?.target;
      const extra = data.pipeline_error
        ? ` Report saved, but pipeline: ${data.pipeline_error}`
        : pipeline
          ? ` On the pipeline.`
          : "";
      setStatus(`General report saved.${extra} Weather and pitch will load on every other report for this game.`, "is-ok");
      renderSheets();
      renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not save general report", "is-error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveDetailedReport() {
    const player = state.player;
    if (!player) return;
    captureDraft();
    const ctx = fixtureContext();
    if (!ctx.fixture_id) {
      setStatus("Open a match before saving a detailed report.", "is-error");
      return;
    }
    const btn = document.getElementById("vwSaveDetailed");
    if (btn) btn.disabled = true;
    setStatus("Saving detailed report…");
    try {
      const ratingRaw = state.detailedDraft.match_rating;
      const data = await fetchJson("/api/video-watch/detailed-report", {
        method: "POST",
        body: JSON.stringify({
          player_id: player.player_id,
          fixture_id: ctx.fixture_id,
          fixture_label: ctx.fixture_label,
          name: player.name || "",
          club: player.club || player.team_name || "",
          league: player.league || state.sheet?.league || "",
          home_name: ctx.home_name,
          away_name: ctx.away_name,
          sheet_side: ctx.sheet_side,
          position: player.position || "",
          position_label: player.position_label || "",
          age: player.age ?? null,
          position_in_game: state.detailedDraft.position_in_game,
          physical: state.detailedDraft.physical,
          profiles: keepProfilesForPosition(
            state.detailedDraft.profiles,
            state.detailedDraft.position_in_game,
            player
          ),
          psychology: state.detailedDraft.psychology,
          write_up: state.detailedDraft.write_up,
          next_steps: state.detailedDraft.next_steps,
          match_rating: ratingRaw === "" ? null : Number(ratingRaw),
          pvfc_level: state.detailedDraft.pvfc_level,
          add_to_pipeline: state.detailedDraft.add_to_pipeline,
          pipeline_stage: state.detailedDraft.pipeline_stage,
          next_action: state.detailedDraft.next_action,
        }),
      });
      state.player = {
        ...player,
        ...(data.player || {}),
        position: player.position || data.player?.position || "",
        position_label: player.position_label || data.player?.position_label || "",
        profiles: data.player?.profiles?.length ? data.player.profiles : player.profiles || [],
        sheet_side: player.sheet_side || data.player?.sheet_side || "",
      };
      fillGeneralDraft(state.player);
      const pipeline = data.pipeline?.target;
      const extra = data.pipeline_error
        ? ` Report saved, but pipeline: ${data.pipeline_error}`
        : pipeline
          ? ` On the pipeline.`
          : "";
      setStatus(`Detailed report saved.${extra}`, "is-ok");
      renderSheets();
      renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not save detailed report", "is-error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveCms() {
    const player = state.player;
    if (!player) return;
    captureDraft();
    const btn = document.getElementById("vwSaveCms");
    if (btn) btn.disabled = true;
    setStatus("Saving player CMS…");
    try {
      const data = await fetchJson("/api/video-watch/cms", {
        method: "POST",
        body: JSON.stringify({
          player_id: player.player_id,
          name: player.name || "",
          club: player.club || player.team_name || "",
          ...state.cmsDraft,
        }),
      });
      if (state.player) state.player.cms = data.cms || state.cmsDraft;
      fillCmsDraft(state.player);
      setStatus("Player CMS saved.", "is-ok");
      renderProfile();
    } catch (error) {
      setStatus(error.message || "Could not save CMS", "is-error");
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
    if (!["general", "detailed", "notes", "cms"].includes(state.tab)) state.tab = "general";
    state.ca = 0;
    state.pa = 0;
    state.draft = { text: sheetPlayer.scout_comment || "", minute: "", title: "" };
    fillGeneralDraft({
      match_conditions: sheetPlayer.match_conditions || state.sheet?.match_conditions,
      general_report: {},
    });
    fillDetailedDraft(sheetPlayer);
    fillCmsDraft(sheetPlayer);
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
      const ctx = fixtureContext();
      if (ctx.fixture_id) params.set("fixture_id", ctx.fixture_id);
      if (ctx.fixture_label) params.set("fixture_label", ctx.fixture_label);
      if (ctx.home_name) params.set("home_name", ctx.home_name);
      if (ctx.away_name) params.set("away_name", ctx.away_name);
      if (sheetPlayer.sheet_side) params.set("sheet_side", sheetPlayer.sheet_side);
      const data = await fetchJson(`/api/video-watch/player?${params}`);
      state.player = {
        ...sheetPlayer,
        ...(data.player || {}),
        profiles: data.player?.profiles?.length ? data.player.profiles : sheetPlayer.profiles || [],
        sheet_side: sheetPlayer.sheet_side || data.player?.sheet_side || "",
      };
      if (state.player.match_conditions) applyMatchConditions(state.player.match_conditions);
      if (!state.draft.text && state.player.scout_comment) {
        state.draft.text = state.player.scout_comment;
      }
      fillGeneralDraft(state.player);
      fillDetailedDraft(state.player);
      fillCmsDraft(state.player);
      renderSheets();
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
    state.deskView = params.get("desk") === "formation" ? "formation" : "sheet";
    state.fixtureId = params.get("fixture") || params.get("fixture_id") || "";
    state.playerId = Number(params.get("player") || params.get("player_id") || 0) || null;
    renderLeagues();
    await loadGames();
  }

  boot();
})();
