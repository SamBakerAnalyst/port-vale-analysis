(() => {
  "use strict";

  const DEFAULT_WEIGHT = 0;
  const POS_SHORT = {
    GOALKEEPER: "GK",
    LEFT_WINGBACK_DEFENDER: "LB",
    RIGHT_WINGBACK_DEFENDER: "RB",
    CENTRAL_DEFENDER: "CB",
    DEFENSE_MIDFIELD: "DM",
    CENTRAL_MIDFIELD: "CM",
    ATTACKING_MIDFIELD: "AM",
    LEFT_WINGER: "LW",
    RIGHT_WINGER: "RW",
    CENTER_FORWARD: "ST",
  };

  const WATCH_STAGE = "watch_list";
  const WATCH_TAG = "Watching";
  /** Already on the pipeline board — unticking removes them from Pipelines. */
  const PIPELINE_STAGES = new Set([
    "watched",
    "data_identified",
    "scout_identified",
    "video_scouted",
    "live_scouted",
    "gone_elsewhere",
    "not_the_right_fit",
  ]);
  const STAGE_CHIP = {
    watch_list: {
      kind: "watch",
      label: "Watch",
      title: "On the Watch list — click to remove",
    },
    watched: {
      kind: "pipe",
      label: "Watched",
      title: "On Pipelines · Watched — click to remove",
    },
    data_identified: {
      kind: "pipe",
      label: "Data",
      title: "On Pipelines · Data identified — click to remove",
    },
    scout_identified: {
      kind: "pipe",
      label: "Scout",
      title: "On Pipelines · Scout identified — click to remove",
    },
    video_scouted: {
      kind: "pipe",
      label: "Video",
      title: "On Pipelines · Video scouted — click to remove",
    },
    live_scouted: {
      kind: "pipe",
      label: "Live",
      title: "On Pipelines · Live scouted — click to remove",
    },
    gone_elsewhere: {
      kind: "closed",
      label: "Gone",
      title: "On Pipelines · Gone / turned us down — click to remove",
    },
    not_the_right_fit: {
      kind: "closed",
      label: "Out",
      title: "On Pipelines · Not the right fit — click to remove",
    },
  };

  function stageChipMeta(stage) {
    return (
      STAGE_CHIP[stage] || {
        kind: "pipe",
        label: "Pipe",
        title: `On Pipelines · ${String(stage || "").replaceAll("_", " ")} — click to remove`,
      }
    );
  }

  const state = {
    loading: false,
    building: false,
    period: "season",
    groupBy: "league",
    league: "ALL",
    position: "ALL",
    weightEditPosition: null,
    year: null,
    month: null,
    players: [],
    leagues: [],
    positions: [],
    profilesByPosition: {},
    profiles: [],
    weights: {},
    weightsByPosition: {},
    seasonLabel: "",
    squadByClub: {},
    loansByClub: {},
    ageBand: "all",
    loanFilter: "all",
    loanLoading: false,
    /** @type {Map<number, {id: string, stage: string, name: string}>} */
    watchByPlayerId: new Map(),
    watchBusy: new Set(),
    /** @type {{pid: number, wantOn: boolean, playerName: string} | null} */
    watchPrompt: null,
    // Pipelines is held back until every scout has a personal login.
    pipelinesLive: false,
  };

  let lastGrouped = { blocks: [] };

  const els = {
    seasonLabel: document.getElementById("seasonLabel"),
    pageNote: document.getElementById("pageNote"),
    statusBanner: document.getElementById("statusBanner"),
    leagueGrid: document.getElementById("leagueGrid"),
    periodGroup: document.getElementById("periodGroup"),
    monthWrap: document.getElementById("monthWrap"),
    monthSelect: document.getElementById("monthSelect"),
    groupByControl: document.getElementById("groupByControl"),
    leagueFilterWrap: document.getElementById("leagueFilterWrap"),
    leagueGroup: document.getElementById("leagueGroup"),
    positionFilterWrap: document.getElementById("positionFilterWrap"),
    positionGroup: document.getElementById("positionGroup"),
    minMinutes: document.getElementById("minMinutes"),
    minAge: document.getElementById("minAge"),
    maxAge: document.getElementById("maxAge"),
    ageBandGroup: document.getElementById("ageBandGroup"),
    loanFilterGroup: document.getElementById("loanFilterGroup"),
    minHeight: document.getElementById("minHeight"),
    clubFilter: document.getElementById("clubFilter"),
    clearClub: document.getElementById("clearClub"),
    oppoFilter: document.getElementById("oppoFilter"),
    clearOppo: document.getElementById("clearOppo"),
    clubOptions: document.getElementById("clubOptions"),
    perLeague: document.getElementById("perLeague"),
    perGroupLabel: document.getElementById("perGroupLabel"),
    weightsGrid: document.getElementById("weightsGrid"),
    weightsPanel: document.getElementById("weightsPanel"),
    weightsHint: document.getElementById("weightsHint"),
    refreshBtn: document.getElementById("refreshBtn"),
    exportPdfBtn: document.getElementById("exportPdfBtn"),
    exportRoot: document.getElementById("exportRoot"),
    watchLink: document.getElementById("watchListLink"),
    watchCount: document.getElementById("watchListCount"),
  };

  function fmt(value, digits = 1) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n.toFixed(digits);
  }

  function parseNum(input) {
    if (input == null || input.value === "") return null;
    const n = Number(input.value);
    return Number.isFinite(n) ? n : null;
  }

  function parseHeightCm(height) {
    if (height == null || height === "") return null;
    if (typeof height === "number") return height;
    const str = String(height).trim();
    const cmMatch = str.match(/(\d{3})\s*cm/i);
    if (cmMatch) return Number(cmMatch[1]);
    const feetMatch = str.match(/(\d)\s*['′]\s*(\d{1,2})/);
    if (feetMatch) {
      const inches = Number(feetMatch[1]) * 12 + Number(feetMatch[2]);
      return Math.round(inches * 2.54);
    }
    const plain = Number(str);
    return Number.isFinite(plain) ? plain : null;
  }

  function clubNeedle() {
    return (els.clubFilter?.value || "").trim();
  }

  function oppoNeedle() {
    return (els.oppoFilter?.value || "").trim();
  }

  function isTeamSheetMode() {
    return clubNeedle().length > 0 || oppoNeedle().length > 0;
  }

  let clubNameCache = { players: null, names: [] };

  function uniqueClubs() {
    if (clubNameCache.players === state.players) return clubNameCache.names;
    const names = [
      ...new Set(
        (state.players || [])
          .map((p) => String(p.club || "").trim())
          .filter(Boolean),
      ),
    ];
    names.sort((a, b) => a.localeCompare(b));
    clubNameCache = { players: state.players, names };
    return names;
  }

  function fillClubOptions() {
    if (!els.clubOptions) return;
    els.clubOptions.innerHTML = uniqueClubs()
      .map((name) => `<option value="${String(name).replace(/"/g, "&quot;")}"></option>`)
      .join("");
  }

  function clubsMatchingNeedle(needle) {
    const query = String(needle || "").trim().toLowerCase();
    if (!query) return [];
    return uniqueClubs().filter((name) => name.toLowerCase().includes(query));
  }

  function resolveClubName(needle) {
    const query = String(needle || "").trim().toLowerCase();
    if (!query) return null;
    const clubs = uniqueClubs();
    const exact = clubs.find((name) => name.toLowerCase() === query);
    if (exact) return exact;
    const starts = clubs.filter((name) => name.toLowerCase().startsWith(query));
    if (starts.length === 1) return starts[0];
    const includes = clubs.filter((name) => name.toLowerCase().includes(query));
    if (includes.length === 1) return includes[0];
    return null;
  }

  function lastNameKey(value) {
    const parts = String(value || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    return nameKey(parts[parts.length - 1] || "");
  }

  function nameKey(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "");
  }

  function loanInfoForPlayer(player) {
    const club = String(player?.club || "").trim();
    const maps = [];
    const seen = new Set();
    const addMap = (key) => {
      const map = state.loansByClub[key];
      if (!map || seen.has(map)) return;
      seen.add(map);
      maps.push(map);
    };
    addMap(club);
    for (const key of Object.keys(state.loansByClub)) {
      if (nameKey(key) === nameKey(club)) addMap(key);
    }
    if (!maps.length) {
      Object.keys(state.loansByClub).forEach(addMap);
    }
    const playerKey = nameKey(player?.name);
    const last = lastNameKey(player?.name);
    for (const clubMap of maps) {
      const direct = clubMap.byName[playerKey];
      if (direct) return direct;
    }
    const lastHits = [];
    for (const clubMap of maps) {
      lastHits.push(...(clubMap.byLast[last] || []));
    }
    const unique = [];
    const seenFrom = new Set();
    for (const hit of lastHits) {
      const stamp = nameKey(hit.name);
      if (seenFrom.has(stamp)) continue;
      seenFrom.add(stamp);
      unique.push(hit);
    }
    return unique.length === 1 ? unique[0] : null;
  }

  async function loadLoansForClubs(clubNames, { statusMessage = "", silent = false } = {}) {
    const clubs = [...new Set((clubNames || []).map((name) => String(name || "").trim()).filter(Boolean))];
    const missing = clubs.filter((name) => !state.loansByClub[name]);
    if (!missing.length) return;

    if (!silent && statusMessage) setStatus(statusMessage, "loading");
    state.loanLoading = true;
    const chunkSize = 8;
    try {
      for (let i = 0; i < missing.length; i += chunkSize) {
        const chunk = missing.slice(i, i + chunkSize);
        const params = new URLSearchParams();
        chunk.forEach((name) => params.append("club", name));
        if (state.seasonLabel) params.set("season", state.seasonLabel);
        try {
          const data = await fetchJson(`/api/who-to-scout/loans?${params}`);
          for (const [club, rows] of Object.entries(data.clubs || {})) {
            const byName = {};
            const byLast = {};
            for (const row of rows || []) {
              const info = { from: row.from, name: row.name };
              byName[nameKey(row.name)] = info;
              const last = lastNameKey(row.name);
              if (last) (byLast[last] ||= []).push(info);
            }
            state.loansByClub[club] = { byName, byLast };
          }
        } catch {
          chunk.forEach((name) => {
            if (!state.loansByClub[name]) state.loansByClub[name] = { byName: {}, byLast: {} };
          });
        }
      }
    } finally {
      state.loanLoading = false;
      if (!silent && statusMessage) setStatus("");
    }
  }

  async function tagLoansOnScreen() {
    if (isTeamSheetMode() || state.loanLoading) return;
    const clubs = new Set();
    for (const block of lastGrouped?.blocks || []) {
      for (const player of block.players || []) {
        const club = String(player?.club || "").trim();
        if (club) clubs.add(club);
      }
    }
    const missing = [...clubs].filter((name) => !state.loansByClub[name]);
    if (!missing.length) return;

    await loadLoansForClubs(missing, { silent: true });
    let foundLoan = false;
    for (const block of lastGrouped?.blocks || []) {
      for (const player of block.players || []) {
        if (loanInfoForPlayer(player)) {
          foundLoan = true;
          break;
        }
      }
      if (foundLoan) break;
    }
    if (foundLoan) renderGrid({ skipLoanTag: true });
  }

  function clubsForLoanFilter() {
    // Only clubs on the current screen / filtered pool — not every club in the season dump.
    const pool = rankedPool();
    const clubs = new Set();
    for (const player of pool.slice(0, 120)) {
      const club = String(player.club || "").trim();
      if (club) clubs.add(club);
    }
    return [...clubs];
  }

  async function ensureLoanFilterReady() {
    if (state.loanFilter !== "loan") return;
    const clubs = clubsForLoanFilter();
    await loadLoansForClubs(clubs, {
      statusMessage: clubs.length ? `Checking loans (${clubs.length} clubs)…` : "",
      silent: false,
    });
  }

  async function loadTeamSheetExtras() {
    const clubs = selectedClubOrder()
      .filter((row) => !row.unmatched)
      .map((row) => row.name);
    const missingSquads = clubs.filter((name) => !state.squadByClub[name]);
    const missingLoans = clubs.filter((name) => !state.loansByClub[name]);

    const jobs = [];
    if (missingSquads.length) {
      setStatus("Loading full squad from Impect…", "loading");
      jobs.push(
        Promise.all(
          missingSquads.map(async (name) => {
            try {
              const data = await fetchJson(`/api/who-to-scout/squad?club=${encodeURIComponent(name)}`);
              state.squadByClub[data.club || name] = data.players || [];
              if (data.club && data.club !== name) state.squadByClub[name] = data.players || [];
            } catch {
              state.squadByClub[name] = [];
            }
          }),
        ),
      );
    }
    if (missingLoans.length) {
      jobs.push(loadLoansForClubs(missingLoans, { silent: true }));
    }
    if (jobs.length) await Promise.all(jobs);
    setStatus("");
    renderGrid();
  }

  function matchingClubNames(needle = clubNeedle()) {
    const resolved = resolveClubName(needle);
    return resolved ? [resolved] : [];
  }

  function shortProfileLabel(label) {
    return String(label || "")
      .replace(/^PV\s*[-–]\s*/i, "")
      .replace(/Goal Keeper/gi, "GK")
      .replace(/Goalkeeper/gi, "GK")
      .replace(/Centre[- ]?back/gi, "CB")
      .replace(/Midfield/gi, "MF")
      .replace(/Play Maker/gi, "PM")
      .replace(/  +/g, " ")
      .trim();
  }

  function selectedClubOrder() {
    const watch = matchingClubNames(clubNeedle());
    const oppo = matchingClubNames(oppoNeedle());
    const seen = new Set();
    const order = [];
    for (const name of watch) {
      if (seen.has(name)) continue;
      seen.add(name);
      order.push({ name, side: "watch" });
    }
    if (clubNeedle() && !order.some((row) => row.side === "watch")) {
      order.push({ name: clubNeedle(), side: "watch", unmatched: true });
    }
    for (const name of oppo) {
      if (seen.has(name)) continue;
      seen.add(name);
      order.push({ name, side: "oppo" });
    }
    if (oppoNeedle() && !order.some((row) => row.side === "oppo")) {
      order.push({ name: oppoNeedle(), side: "oppo", unmatched: true });
    }
    return order;
  }

  function syncTeamSheetUi() {
    const active = isTeamSheetMode();
    if (els.clearClub) els.clearClub.disabled = !clubNeedle();
    if (els.clearOppo) els.clearOppo.disabled = !oppoNeedle();
    const wrap = els.perLeague?.closest(".filter");
    if (wrap) wrap.hidden = active;
    if (els.weightsPanel) els.weightsPanel.hidden = active;
  }

  async function fetchJson(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  function setStatus(message, kind = "loading") {
    if (!message) {
      els.statusBanner.classList.add("hidden");
      els.statusBanner.textContent = "";
      return;
    }
    els.statusBanner.textContent = message;
    els.statusBanner.className = `status-banner status-banner--${kind}`;
  }

  function posShort(label, value) {
    return POS_SHORT[value] || label || value || "—";
  }

  function pipelinePlayerId(p) {
    const raw = p?.playerId ?? p?.player_id ?? null;
    if (raw != null && raw !== "") {
      const n = Number(raw);
      return Number.isFinite(n) && n > 0 ? n : null;
    }
    const composite = String(p?.id || "");
    if (composite.includes(":")) {
      const parts = composite.split(":");
      const mid = Number(parts[1]);
      if (Number.isFinite(mid) && mid > 0) return mid;
      const tail = Number(parts[parts.length - 1]);
      return Number.isFinite(tail) && tail > 0 ? tail : null;
    }
    return null;
  }

  function updateWatchCount() {
    let count = 0;
    for (const row of state.watchByPlayerId.values()) {
      if (row.stage === WATCH_STAGE) count += 1;
    }
    if (els.watchCount) {
      els.watchCount.textContent = String(count);
      els.watchCount.hidden = count === 0;
    }
    if (els.watchLink) {
      els.watchLink.title =
        count === 0
          ? "Open Watch list"
          : `${count} player${count === 1 ? "" : "s"} on the Watch list`;
    }
  }

  async function loadWatchList() {
    try {
      const data = await fetchJson("/api/player-pipelines/track-index");
      state.pipelinesLive = Boolean(data.pipelines_live);
      const pipelinesLink = document.getElementById("pipelinesLink");
      if (pipelinesLink) pipelinesLink.hidden = !state.pipelinesLive;
      const next = new Map();
      for (const target of data.targets || []) {
        const pid = Number(target.player_id || 0);
        if (!pid) continue;
        next.set(pid, {
          id: String(target.id || ""),
          stage: String(target.stage || ""),
          name: String(target.name || ""),
        });
      }
      state.watchByPlayerId = next;
      updateWatchCount();
      // Don't rewrite every chip here — next renderGrid paints correct state.
    } catch {
      /* watch list optional — tables still work */
    }
  }

  function watchCell(p, { exportMode = false } = {}) {
    if (exportMode) return "";
    const pid = pipelinePlayerId(p);
    if (!pid) {
      return `<td class="col-watch"><span class="watch-chip watch-chip--disabled" title="No Impect id">—</span></td>`;
    }
    const existing = state.watchByPlayerId.get(pid);
    const busy = state.watchBusy.has(pid);
    return `<td class="col-watch">${watchChipHtml(pid, existing, busy)}</td>`;
  }

  function watchChipHtml(pid, existing, busy) {
    if (!existing) {
      return `<button type="button"
        class="watch-chip watch-chip--idle${busy ? " is-busy" : ""}"
        data-player-id="${pid}"
        ${busy ? "disabled" : ""}
        title="Add to Watch list"
        aria-label="Add to Watch list">
        <span class="watch-chip__mark" aria-hidden="true">+</span>
        <span class="watch-chip__label">Add</span>
      </button>`;
    }
    const meta = stageChipMeta(existing.stage);
    const hrefNote =
      meta.kind === "pipe" || meta.kind === "closed"
        ? " · open Pipelines from the header if you want the board"
        : "";
    return `<button type="button"
      class="watch-chip watch-chip--${meta.kind}${busy ? " is-busy" : ""}"
      data-player-id="${pid}"
      data-stage="${escAttr(existing.stage || "")}"
      ${busy ? "disabled" : ""}
      title="${escAttr(meta.title)}${hrefNote}"
      aria-label="${escAttr(meta.title)}">
      <span class="watch-chip__mark" aria-hidden="true"></span>
      <span class="watch-chip__label">${escAttr(meta.label)}</span>
    </button>`;
  }

  function escAttr(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function ensureWatchChrome() {
    if (!document.getElementById("watchToast")) {
      const toast = document.createElement("div");
      toast.id = "watchToast";
      toast.className = "watch-toast hidden";
      toast.setAttribute("role", "status");
      document.body.appendChild(toast);
    }
    if (!document.getElementById("watchPrompt")) {
      const prompt = document.createElement("div");
      prompt.id = "watchPrompt";
      prompt.className = "watch-prompt hidden";
      prompt.innerHTML = `
        <div class="watch-prompt__card" role="dialog" aria-modal="true" aria-labelledby="watchPromptTitle">
          <p class="watch-prompt__eyebrow" id="watchPromptEyebrow"></p>
          <p class="watch-prompt__title" id="watchPromptTitle">Watch list</p>
          <p class="watch-prompt__sub" id="watchPromptSub"></p>
          <div class="watch-prompt__actions">
            <button type="button" class="btn btn--ghost" data-watch-cancel>Cancel</button>
            <a class="btn btn--ghost" data-watch-open href="/player-pipelines" hidden>Open Pipelines</a>
            <button type="button" class="btn btn--primary" data-watch-confirm>Add to Watch list</button>
          </div>
        </div>`;
      document.body.appendChild(prompt);
      prompt.addEventListener("click", (event) => {
        if (event.target === prompt || event.target.closest("[data-watch-cancel]")) {
          closeWatchPrompt();
        }
      });
      prompt.querySelector("[data-watch-confirm]")?.addEventListener("click", () => {
        const pending = state.watchPrompt;
        closeWatchPrompt();
        if (!pending) return;
        void applyWatch(pending.pid, pending.wantOn, pending.playerName);
      });
    }
  }

  function showWatchToast(message, isError) {
    ensureWatchChrome();
    const toast = document.getElementById("watchToast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("is-error", Boolean(isError));
    toast.classList.remove("hidden");
    clearTimeout(showWatchToast._timer);
    showWatchToast._timer = setTimeout(() => toast.classList.add("hidden"), 3200);
  }

  function closeWatchPrompt() {
    state.watchPrompt = null;
    const prompt = document.getElementById("watchPrompt");
    prompt?.classList.add("hidden");
  }

  function openWatchPrompt(button) {
    const pid = Number(button.dataset.playerId || 0);
    if (!pid || state.watchBusy.has(pid)) return;

    const existing = state.watchByPlayerId.get(pid);
    const player =
      state.players.find((row) => pipelinePlayerId(row) === pid) || null;
    const name = player?.name || existing?.name || `Player ${pid}`;
    const club = player?.club || "";
    const wantOn = !existing;

    // Add is one click — confirm only when removing.
    if (wantOn) {
      void applyWatch(pid, true, name);
      return;
    }

    ensureWatchChrome();
    state.watchPrompt = { pid, wantOn, playerName: name };
    const prompt = document.getElementById("watchPrompt");
    const eyebrow = document.getElementById("watchPromptEyebrow");
    const title = document.getElementById("watchPromptTitle");
    const sub = document.getElementById("watchPromptSub");
    const confirmBtn = prompt?.querySelector("[data-watch-confirm]");
    const openLink = prompt?.querySelector("[data-watch-open]");

    if (existing.stage === WATCH_STAGE) {
      if (eyebrow) eyebrow.textContent = "Already on Watch list";
      if (title) title.textContent = "Remove from Watch list?";
      if (sub) sub.textContent = club ? `${name} · ${club}` : name;
      if (confirmBtn) {
        confirmBtn.hidden = false;
        confirmBtn.textContent = "Remove";
        confirmBtn.classList.add("btn--danger");
        confirmBtn.classList.remove("btn--primary");
      }
      if (openLink) {
        openLink.hidden = false;
        openLink.href = "/watch-list";
        openLink.textContent = "Open Watch list";
      }
    } else {
      const meta = stageChipMeta(existing.stage);
      if (eyebrow) eyebrow.textContent = "Already on Player Pipelines";
      if (title) title.textContent = meta.title.replace(" — click to remove", "");
      if (sub) {
        sub.textContent = club
          ? `${name} · ${club} · stage: ${meta.label}`
          : `${name} · stage: ${meta.label}`;
      }
      if (confirmBtn) {
        confirmBtn.hidden = false;
        confirmBtn.textContent = "Remove from Pipelines";
        confirmBtn.classList.add("btn--danger");
        confirmBtn.classList.remove("btn--primary");
      }
      if (openLink) {
        openLink.hidden = !state.pipelinesLive;
        openLink.href = "/player-pipelines";
        openLink.textContent = "Open Pipelines";
      }
    }
    prompt?.classList.remove("hidden");
  }

  function syncWatchButtons(pid) {
    const existing = state.watchByPlayerId.get(pid) || null;
    const busy = state.watchBusy.has(pid);
    document.querySelectorAll(`.watch-chip[data-player-id="${pid}"]`).forEach((node) => {
      const wrap = document.createElement("div");
      wrap.innerHTML = watchChipHtml(pid, existing, busy);
      const next = wrap.firstElementChild;
      if (next) node.replaceWith(next);
    });
  }

  function bestProfileSeed(player) {
    const scores = player?.profileScores || {};
    let topName = "";
    let topScore = null;
    for (const [name, value] of Object.entries(scores)) {
      if (value == null || value === "") continue;
      const num = Number(value);
      if (!Number.isFinite(num)) continue;
      if (topScore == null || num > topScore) {
        topScore = num;
        topName = name;
      }
    }
    return {
      top_profile: topName
        ? String(topName)
            .replace(/^PV\s*[-–]\s*/i, "")
            .replace(/\s*\([^)]*\)\s*/g, " ")
            .replace(/\s+/g, " ")
            .trim()
        : "",
      top_profile_score: topScore,
    };
  }

  async function applyWatch(pid, wantOn, playerName) {
    if (!pid || state.watchBusy.has(pid)) return;

    const existing = state.watchByPlayerId.get(pid);
    const player =
      state.players.find((row) => pipelinePlayerId(row) === pid) || null;

    state.watchBusy.add(pid);
    // Optimistic chip update — don't wait on the network to feel done.
    if (wantOn) {
      state.watchByPlayerId.set(pid, {
        id: existing?.id || `pending-${pid}`,
        stage: WATCH_STAGE,
        name: player?.name || existing?.name || playerName || `Player ${pid}`,
      });
    } else {
      state.watchByPlayerId.delete(pid);
    }
    updateWatchCount();
    syncWatchButtons(pid);

    try {
      if (wantOn) {
        const seed = bestProfileSeed(player);
        const overall =
          player?.overall != null && player.overall !== ""
            ? Number(player.overall)
            : playerOverall(player);
        const res = await fetch("/api/player-pipelines/targets", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            player_id: pid,
            name: player?.name || existing?.name || playerName || `Player ${pid}`,
            club: player?.club || "",
            league: player?.league || "",
            position: player?.position || "",
            position_label: player?.positionLabel || "",
            age: player?.age ?? null,
            stage: WATCH_STAGE,
            tags: [WATCH_TAG],
            overall_score: Number.isFinite(overall) ? overall : null,
            minutes: player?.minutes ?? null,
            top_profile: seed.top_profile,
            top_profile_score: seed.top_profile_score,
            enrich: false,
          }),
        });
        if (!res.ok) {
          const raw = await res.text();
          let message = `Could not add to watch list (${res.status}).`;
          try {
            message = JSON.parse(raw).detail || message;
          } catch {
            if (raw) message = raw.slice(0, 160);
          }
          throw new Error(message);
        }
        const data = await res.json();
        const target = data.target || {};
        state.watchByPlayerId.set(pid, {
          id: String(target.id || existing?.id || ""),
          stage: String(target.stage || WATCH_STAGE),
          name: String(target.name || player?.name || playerName || ""),
        });
        const msg = `Added ${target.name || playerName || "player"} to the Watch list.`;
        setStatus(msg, "ok");
        showWatchToast(msg, false);
      } else {
        const targetId = existing?.id;
        if (targetId && !String(targetId).startsWith("pending-")) {
          const res = await fetch(
            `/api/player-pipelines/targets/${encodeURIComponent(targetId)}`,
            { method: "DELETE", credentials: "same-origin" },
          );
          if (!res.ok && res.status !== 404) {
            throw new Error(`Could not remove from watch list (${res.status}).`);
          }
        }
        state.watchByPlayerId.delete(pid);
        const msg = `Removed ${existing?.name || playerName || "player"} from tracking.`;
        setStatus(msg, "ok");
        showWatchToast(msg, false);
      }
      updateWatchCount();
      syncWatchButtons(pid);
    } catch (err) {
      // Roll back optimistic chip.
      if (wantOn) {
        if (existing) state.watchByPlayerId.set(pid, existing);
        else state.watchByPlayerId.delete(pid);
      } else if (existing) {
        state.watchByPlayerId.set(pid, existing);
      }
      const msg = err.message || "Watch list update failed.";
      setStatus(msg, "error");
      showWatchToast(msg, true);
      syncWatchButtons(pid);
    } finally {
      state.watchBusy.delete(pid);
      syncWatchButtons(pid);
    }
  }

  function playerHref(p) {
    const id = p.playerId ?? p.player_id ?? null;
    if (id != null && id !== "") return `/player/${encodeURIComponent(id)}`;
    const composite = String(p.id || "");
    if (composite.includes(":")) {
      const tail = composite.split(":").pop();
      if (tail) return `/player/${encodeURIComponent(tail)}`;
    }
    return "#";
  }

  function defaultMonthOptions() {
    const options = [];
    const now = new Date();
    let year = now.getFullYear();
    let month = now.getMonth() + 1;
    for (let i = 0; i < 12; i += 1) {
      const value = `${year}-${String(month).padStart(2, "0")}`;
      const label = new Date(year, month - 1, 1).toLocaleString(undefined, {
        month: "short",
        year: "numeric",
      });
      options.push({ value, label, year, month });
      month -= 1;
      if (month < 1) {
        month = 12;
        year -= 1;
      }
    }
    return options;
  }

  function fillMonths(options, selectedYear, selectedMonth) {
    if (!els.monthSelect || !options?.length) return;
    const selectedValue = `${selectedYear}-${String(selectedMonth).padStart(2, "0")}`;
    els.monthSelect.innerHTML = options
      .map(
        (opt) =>
          `<option value="${opt.value}"${opt.value === selectedValue ? " selected" : ""}>${opt.label}</option>`,
      )
      .join("");
    state.year = selectedYear;
    state.month = selectedMonth;
  }

  function posLabel(value) {
    const row = state.positions.find((p) => p.value === value);
    return row?.label || value || "—";
  }

  function fillLeagues(leagues) {
    if (!els.leagueGroup || !leagues?.length) return;
    const buttons = [
      `<button type="button" class="filter__btn${state.league === "ALL" ? " is-active" : ""}" data-league="ALL">All</button>`,
    ].concat(
      leagues.map((name) => {
        const safe = String(name).replace(/"/g, "&quot;");
        return `<button type="button" class="filter__btn${state.league === name ? " is-active" : ""}" data-league="${safe}">${name}</button>`;
      }),
    );
    els.leagueGroup.innerHTML = buttons.join("");
  }

  function fillPositions(positions) {
    if (!els.positionGroup || !positions?.length) return;
    const buttons = [
      `<button type="button" class="filter__btn${state.position === "ALL" ? " is-active" : ""}" data-position="ALL" title="All positions">All</button>`,
    ].concat(
      positions.map((row) => {
        const value = row.value || "";
        const label = posShort(row.label, value);
        const full = row.label || value;
        return `<button type="button" class="filter__btn${state.position === value ? " is-active" : ""}" data-position="${value}" title="${full}">${label}</button>`;
      }),
    );
    els.positionGroup.innerHTML = buttons.join("");
  }

  function syncFilterVisibility() {
    if (els.leagueFilterWrap) els.leagueFilterWrap.hidden = false;
    if (els.positionFilterWrap) els.positionFilterWrap.hidden = false;
    updatePerGroupLabel();
  }

  function resolveViewMode() {
    if (isTeamSheetMode()) return "team";
    if (state.position !== "ALL") return "profiles";
    if (state.groupBy === "league" && state.league !== "ALL") return "positions";
    if (state.groupBy === "position") return "positions";
    return "leagues";
  }

  function updatePerGroupLabel() {
    if (!els.perGroupLabel) return;
    const mode = resolveViewMode();
    const labels = {
      leagues: "Top per league",
      positions: "Top per position",
      profiles: "Top per profile",
    };
    els.perGroupLabel.textContent = labels[mode] || "Top per group";
  }

  function activeWeightPosition() {
    if (state.position !== "ALL") return state.position;
    if (state.groupBy === "league") return null;
    return state.weightEditPosition || state.positions[0]?.value || null;
  }

  function profilesForCurrentPosition() {
    const key = activeWeightPosition();
    if (!key) return [];
    return state.profilesByPosition[key] || [];
  }

  function syncProfilesForPosition() {
    const key = activeWeightPosition();
    state.profiles = profilesForCurrentPosition();
    if (!key) {
      state.weights = {};
      return;
    }
    if (!state.weightsByPosition[key]) {
      state.weightsByPosition[key] = Object.fromEntries(
        state.profiles.map((p) => [p.apiName, DEFAULT_WEIGHT]),
      );
    }
    state.weights = { ...state.weightsByPosition[key] };
  }

  function weightFor(apiName) {
    const w = state.weights[apiName];
    return w == null ? DEFAULT_WEIGHT : w;
  }

  function activeWeightTotal() {
    return state.profiles.reduce(
      (sum, p) => sum + Math.max(0, state.weights[p.apiName] ?? 0),
      0,
    );
  }

  function mixPercent(apiName) {
    const w = state.weights[apiName] ?? 0;
    const total = activeWeightTotal();
    if (w <= 0 || total <= 0) return 0;
    return Math.round((w / total) * 100);
  }

  function passesProfileFilters(profileScores, profiles, weights) {
    for (const profile of profiles) {
      const minimum = weights[profile.apiName] ?? 0;
      if (minimum <= 0) continue;
      const value = profileScores?.[profile.apiName];
      if (value == null || value < minimum) return false;
    }
    return true;
  }

  function computeOverall(profileScores, profiles, weights, { equalWeight = false } = {}) {
    let sum = 0;
    let wSum = 0;
    const fallbackValues = [];

    for (const profile of profiles) {
      const value = profileScores?.[profile.apiName];
      if (value == null) continue;
      fallbackValues.push(value);
      if (equalWeight) {
        sum += value;
        wSum += 1;
        continue;
      }
      const w = weights?.[profile.apiName] ?? 0;
      if (w <= 0) continue;
      sum += value * w;
      wSum += w;
    }

    if (wSum > 0) return sum / wSum;
    if (!fallbackValues.length) return 0;
    return fallbackValues.reduce((total, value) => total + value, 0) / fallbackValues.length;
  }

  function playerOverall(player, profilesOverride, weightsOverride) {
    const profiles =
      profilesOverride ||
      state.profilesByPosition[player.position] ||
      [];
    const weights =
      weightsOverride ||
      state.weightsByPosition[player.position] ||
      {};
    const equalWeight =
      state.groupBy === "league"
        ? state.position === "ALL"
        : !Object.values(weights).some((w) => w > 0);
    return computeOverall(player.profileScores, profiles, weights, { equalWeight });
  }

  function passesDemographicFilters(player) {
    const minMinutes = parseNum(els.minMinutes) ?? 0;
    const minAge = parseNum(els.minAge);
    const maxAge = parseNum(els.maxAge);
    const minHeight = parseNum(els.minHeight);
    const age = player.age == null || player.age === "" ? null : Number(player.age);

    if (minMinutes > 0) {
      const mins = Number(player.minutes) || 0;
      if (mins < minMinutes) return false;
    }
    if (state.ageBand === "u21" && (age == null || !(age < 21))) return false;
    if (state.ageBand === "u25" && (age == null || !(age < 25))) return false;
    if (minAge != null && (age == null || age < minAge)) return false;
    if (maxAge != null && (age == null || age > maxAge)) return false;
    if (minHeight != null) {
      const cm = parseHeightCm(player.height);
      if (cm == null || cm < minHeight) return false;
    }
    if (state.loanFilter === "loan" && !loanInfoForPlayer(player)) return false;
    const watchNeedle = clubNeedle().toLowerCase();
    const awayNeedle = oppoNeedle().toLowerCase();
    if (watchNeedle || awayNeedle) {
      const allowed = new Set(selectedClubOrder().map((row) => row.name));
      const club = String(player.club || "");
      if (allowed.size) {
        if (!allowed.has(club)) return false;
      } else {
        const hay = club.toLowerCase();
        const watchHit = watchNeedle && hay.includes(watchNeedle);
        const oppoHit = awayNeedle && hay.includes(awayNeedle);
        if (!watchHit && !oppoHit) return false;
      }
    }
    return true;
  }

  function rankedPool() {
    const weightPos = activeWeightPosition();
    const profiles =
      weightPos && state.groupBy === "league"
        ? state.profiles.length
          ? state.profiles
          : profilesForCurrentPosition()
        : [];

    const clubSet = isTeamSheetMode()
      ? new Set(selectedClubOrder().filter((row) => !row.unmatched).map((row) => row.name))
      : null;

    let source = state.players;
    if (clubSet && clubSet.size) {
      const overlay = [];
      for (const name of clubSet) {
        const rows = state.squadByClub[name];
        if (rows && rows.length) overlay.push(...rows);
      }
      if (overlay.length) source = overlay;
    }

    return source
      .filter((p) => state.league === "ALL" || p.league === state.league)
      .filter((p) => !clubSet || clubSet.size === 0 || clubSet.has(String(p.club || "").trim()) || source !== state.players)
      .filter((p) => state.groupBy !== "league" || state.position === "ALL" || p.position === state.position)
      .filter((p) => passesDemographicFilters(p))
      .filter((p) => {
        if (resolveViewMode() === "profiles" || resolveViewMode() === "team") return true;
        if (state.groupBy === "league") {
          if (state.position === "ALL") return true;
          return passesProfileFilters(p.profileScores, profiles, state.weights);
        }
        const posProfiles = state.profilesByPosition[p.position] || [];
        const posWeights = state.weightsByPosition[p.position] || {};
        return passesProfileFilters(p.profileScores, posProfiles, posWeights);
      })
      .map((p) => ({ ...p, overall: playerOverall(p) }))
      .sort((a, b) => {
        const diff = (b.overall || 0) - (a.overall || 0);
        if (Math.abs(diff) > 1e-9) return diff;
        return String(a.name || "").localeCompare(String(b.name || ""));
      });
  }

  function topFromPool(pool, limit) {
    const highest = pool.length
      ? Math.max(...pool.map((p) => Number(p.overall) || 0))
      : null;
    const thresholdPct = 85;
    const effective =
      highest != null ? Math.max(0, (thresholdPct / 100) * highest) : thresholdPct;

    const qualifying = pool.filter((p) => (Number(p.overall) || 0) >= effective - 1e-9);
    let shown = qualifying.slice(0, limit);
    if (shown.length < limit) {
      const seen = new Set(shown.map((p) => p.id));
      for (const row of pool) {
        if (shown.length >= limit) break;
        if (seen.has(row.id)) continue;
        shown.push(row);
        seen.add(row.id);
      }
    }

    return {
      players: shown,
      pool_count: pool.length,
      qualify_count: qualifying.length,
      highest_overall: highest,
      min_score_effective: effective,
    };
  }

  function buildByLeague(pool) {
    const limit = Math.max(5, Math.min(25, parseNum(els.perLeague) || 10));
    const leagues = state.leagues.length
      ? state.leagues
      : [...new Set(pool.map((p) => p.league))];
    const blocks = leagues.map((league) => {
      const slice = topFromPool(
        pool.filter((p) => p.league === league),
        limit,
      );
      return { key: league, title: league, kind: "league", ...slice };
    });
    return { blocks, limit, groupLabel: "league", viewMode: "leagues" };
  }

  function buildPositionsInContext(pool) {
    const limit = Math.max(5, Math.min(25, parseNum(els.perLeague) || 10));
    const positionOrder = state.positions.map((p) => p.value);
    const blocks = positionOrder.map((position) => {
        const positionPool = pool
          .filter((p) => p.position === position)
          .map((p) => {
            const profiles = state.profilesByPosition[position] || [];
            const overall = computeOverall(p.profileScores, profiles, {}, { equalWeight: true });
            return { ...p, overall };
          })
          .sort((a, b) => {
            const diff = (b.overall || 0) - (a.overall || 0);
            if (Math.abs(diff) > 1e-9) return diff;
            return String(a.name || "").localeCompare(String(b.name || ""));
          });
        const slice = topFromPool(positionPool, limit);
        return {
          key: position,
          title: posLabel(position),
          titleShort: posShort(posLabel(position), position),
          kind: "position",
          ...slice,
        };
      });
    return { blocks, limit, groupLabel: "position", viewMode: "positions" };
  }

  function buildByProfile(pool, position) {
    const limit = Math.max(5, Math.min(25, parseNum(els.perLeague) || 10));
    const profiles = state.profilesByPosition[position] || [];
    const positionPool = pool.filter((p) => p.position === position);

    const blocks = profiles.map((profile) => {
      const scored = positionPool
        .filter((p) => p.profileScores?.[profile.apiName] != null)
        .map((p) => ({
          ...p,
          overall: Number(p.profileScores[profile.apiName]),
          highlightProfile: profile.apiName,
        }))
        .sort((a, b) => {
          const diff = (b.overall || 0) - (a.overall || 0);
          if (Math.abs(diff) > 1e-9) return diff;
          return String(a.name || "").localeCompare(String(b.name || ""));
        });
      const slice = topFromPool(scored, limit);
      return {
        key: profile.apiName,
        title: profile.label,
        profileApiName: profile.apiName,
        kind: "profile",
        ...slice,
      };
    });

    return { blocks, limit, groupLabel: "profile", viewMode: "profiles" };
  }

  function buildTeamSheet(pool) {
    const selected = selectedClubOrder();
    const clubOrder = selected.length
      ? selected
      : [...new Set(pool.map((p) => String(p.club || "").trim()).filter(Boolean))].map((name) => ({
          name,
          side: "watch",
        }));
    const bothSides = clubOrder.some((row) => row.side === "watch") && clubOrder.some((row) => row.side === "oppo");
    const hideEmptyRoles = bothSides;
    const positionOrder = state.positions.length ? state.positions : [];
    const blocks = [];

    const squads = clubOrder.map((entry) => {
      const query = String(entry.name || "").trim();
      const clubPlayers = pool.filter((p) => {
        const club = String(p.club || "").trim();
        if (entry.unmatched) return club.toLowerCase().includes(query.toLowerCase());
        return club === query;
      });
      const uniqueById = new Map();
      for (const player of clubPlayers) {
        const key = String(player.playerId ?? player.id ?? player.name);
        const overall = playerOverall(player);
        const scored = { ...player, overall };
        const prev = uniqueById.get(key);
        if (!prev || (Number(scored.overall) || 0) > (Number(prev.overall) || 0)) {
          uniqueById.set(key, scored);
        }
      }
      const squad = [...uniqueById.values()].sort((a, b) => {
        const diff = (b.overall || 0) - (a.overall || 0);
        if (Math.abs(diff) > 1e-9) return diff;
        return String(a.name || "").localeCompare(String(b.name || ""));
      });
      return { entry, clubPlayers, squad };
    });

    for (const { entry, squad } of squads) {
      const sideLabel = entry.side === "oppo" ? "Opposition" : bothSides ? "Watch" : "";
      const squadTitle = sideLabel
        ? `${sideLabel} · ${entry.name}`
        : clubOrder.length > 1
          ? `${entry.name} · Full squad`
          : "Full squad";
      blocks.push({
        key: `${entry.side}:${entry.name}:squad`,
        title: squadTitle,
        club: entry.name,
        side: entry.side,
        kind: "team-squad",
        players: squad,
        pool_count: squad.length,
        profileCols: [],
        empty: !squad.length,
        unmatched: Boolean(entry.unmatched),
      });
    }

    const positions =
      state.position === "ALL" ? positionOrder : positionOrder.filter((row) => row.value === state.position);
    for (const { entry, clubPlayers } of squads) {
      const sideLabel = entry.side === "oppo" ? "Opposition" : bothSides ? "Watch" : "";
      for (const row of positions) {
        const position = row.value;
        const profiles = state.profilesByPosition[position] || [];
        const players = clubPlayers
          .filter((p) => p.position === position)
          .map((p) => ({
            ...p,
            overall: computeOverall(p.profileScores, profiles, {}, { equalWeight: true }),
          }))
          .sort((a, b) => {
            const diff = (b.overall || 0) - (a.overall || 0);
            if (Math.abs(diff) > 1e-9) return diff;
            return String(a.name || "").localeCompare(String(b.name || ""));
          });
        if (hideEmptyRoles && !players.length) continue;
        const posTitle = sideLabel
          ? `${sideLabel} · ${posLabel(position)}`
          : clubOrder.length > 1
            ? `${entry.name} · ${posLabel(position)}`
            : posLabel(position);
        blocks.push({
          key: `${entry.side}:${entry.name}:${position}`,
          title: posTitle,
          club: entry.name,
          side: entry.side,
          kind: "team-position",
          players,
          pool_count: players.length,
          profileCols: profiles,
          empty: !players.length,
        });
      }
    }

    return {
      blocks,
      limit: null,
      groupLabel: "squad",
      viewMode: "team",
      clubs: clubOrder.map((row) => row.name),
    };
  }

  function buildGrouped(pool) {
    if (isTeamSheetMode()) return buildTeamSheet(pool);
    const viewMode = resolveViewMode();
    if (viewMode === "profiles") {
      return buildByProfile(pool, state.position);
    }
    if (viewMode === "positions") {
      return buildPositionsInContext(pool);
    }
    if (state.groupBy === "position") {
      return buildPositionsInContext(pool);
    }
    return buildByLeague(pool);
  }

  function scoutCountCell(count, kind) {
    const value = Number(count) || 0;
    if (!value) return `<td class="col-scout"><span class="scout-dash">—</span></td>`;
    return `<td class="col-scout"><span class="scout-pill scout-pill--${kind}">${value}</span></td>`;
  }

  function ageBandClass(age) {
    const n = Number(age);
    if (!Number.isFinite(n)) return "";
    if (n < 23) return "is-age-u23";
    if (n > 30) return "is-age-o30";
    return "";
  }

  function rowClasses(p, scoutTotal) {
    const parts = [];
    if (scoutTotal) parts.push("has-scout");
    if (loanInfoForPlayer(p)) parts.push("is-loan");
    if (Number(p.age) > 30) parts.push("row-veteran");
    return parts.join(" ");
  }

  function updateExportButton(grouped) {
    if (!els.exportPdfBtn) return;
    const blocks = grouped?.blocks;
    const hasRows = (blocks || []).some((block) => (block.players || []).length);
    els.exportPdfBtn.disabled = state.loading || state.building || !hasRows;
  }

  function playerRows(
    players,
    {
      showPos = true,
      showLeague = true,
      scoreLabel = "Ovr",
      showScout = true,
      exportMode = false,
      rankStart = 0,
      profileCols = [],
      showClub = true,
      compactLeague = false,
    } = {},
  ) {
    return (players || [])
      .map((p, index) => {
        const mins =
          p.minutes == null || p.minutes === ""
            ? "—"
            : `${Number(p.minutes).toLocaleString()}′`;
        const age =
          p.age == null || p.age === "" ? "—" : String(Math.round(Number(p.age)));
        const ageClass = ageBandClass(p.age);
        const href = playerHref(p);
        const scout = p.scout || {};
        const scoutTotal = Number(p.scout_total) || 0;
        const pos = posShort(p.positionLabel, p.position);
        const rowClass = rowClasses(p, scoutTotal);
        const loan = loanInfoForPlayer(p);
        const loanTitle = loan?.from ? `On loan from ${loan.from}` : "";
        const nameCell = exportMode
          ? `<td class="col-player"${loanTitle ? ` title="${loanTitle}"` : ""}>${p.name || "—"}</td>`
          : `<td class="col-player"><a href="${href}"${loanTitle ? ` title="${loanTitle}"` : ""}>${p.name || "—"}</a></td>`;
        const profileCells = (profileCols || [])
          .map((profile) => {
            const value = p.profileScores?.[profile.apiName];
            return `<td class="col-profile-score">${fmt(value, 0)}</td>`;
          })
          .join("");
        const overallCell = `<td class="col-overall" title="${scoreLabel}">${fmt(p.overall, 1)}</td>`;
        if (compactLeague) {
          return `<tr${rowClass ? ` class="${rowClass}"` : ""}>
            ${watchCell(p, { exportMode })}
            <td class="col-rank">${rankStart + index + 1}</td>
            ${nameCell}
            ${overallCell}
            ${showPos ? `<td class="col-pos" title="${p.positionLabel || p.position || ""}">${pos}</td>` : ""}
            ${showClub ? `<td class="col-club" title="${p.club || ""}">${p.club || "—"}</td>` : ""}
            <td class="col-age${ageClass ? ` ${ageClass}` : ""}">${age}</td>
            <td class="col-mins">${mins}</td>
          </tr>`;
        }
        return `<tr${rowClass ? ` class="${rowClass}"` : ""}>
          ${watchCell(p, { exportMode })}
          <td class="col-rank">${rankStart + index + 1}</td>
          ${nameCell}
          ${showClub ? `<td class="col-club" title="${p.club || ""}">${p.club || "—"}</td>` : ""}
          ${showLeague ? `<td class="col-league" title="${p.league || ""}">${p.league || "—"}</td>` : ""}
          ${showPos ? `<td class="col-pos" title="${p.positionLabel || p.position || ""}">${pos}</td>` : ""}
          <td class="col-age${ageClass ? ` ${ageClass}` : ""}">${age}</td>
          ${overallCell}
          ${profileCells}
          <td class="col-mins">${mins}</td>
          ${showScout ? scoutCountCell(scout.live_watches, "live") : ""}
          ${showScout ? scoutCountCell(scout.video_watches, "video") : ""}
          ${showScout ? scoutCountCell(scout.report_count, "report") : ""}
        </tr>`;
      })
      .join("");
  }

  function resultsTable(
    players,
    {
      showPos = true,
      showLeague = true,
      scoreLabel = "Ovr",
      showScout = true,
      exportMode = false,
      rankStart = 0,
      profileCols = [],
      showClub = true,
      compactLeague = false,
    } = {},
  ) {
    const watchCol = exportMode ? "" : '<col class="col-watch">';
    const watchHead = exportMode
      ? ""
      : '<th class="col-watch" title="Watch list / Pipelines status">Track</th>';
    const clubCol = showClub ? '<col class="col-club">' : "";
    const leagueCol = showLeague ? '<col class="col-league">' : "";
    const posCol = showPos ? '<col class="col-pos">' : "";
    const clubHead = showClub ? '<th class="col-club">Club</th>' : "";
    const leagueHead = showLeague ? '<th class="col-league">League</th>' : "";
    const posHead = showPos ? '<th class="col-pos">Pos</th>' : "";
    const scoutCols = showScout && !compactLeague
      ? '<col class="col-scout"><col class="col-scout"><col class="col-scout">'
      : "";
    const scoutHead = showScout && !compactLeague
      ? `<th class="col-scout">Live</th><th class="col-scout">Vid</th><th class="col-scout">Rep</th>`
      : "";
    const profileColMarkup = compactLeague
      ? ""
      : (profileCols || [])
          .map(() => '<col class="col-profile-score">')
          .join("");
    const profileHead = compactLeague
      ? ""
      : (profileCols || [])
          .map(
            (profile) =>
              `<th class="col-profile-score" title="${profile.apiName || profile.label}">${shortProfileLabel(profile.label)}</th>`,
          )
          .join("");
    const viewClass = profileCols?.length
      ? "team"
      : compactLeague
        ? "league"
        : showPos
          ? "league"
          : showLeague
            ? "position"
            : "profile";
    const colgroup = compactLeague
      ? `${watchCol}<col class="col-rank"><col class="col-player"><col class="col-overall">${posCol}${clubCol}<col class="col-age"><col class="col-mins">`
      : `${watchCol}<col class="col-rank"><col class="col-player">${clubCol}${leagueCol}${posCol}<col class="col-age"><col class="col-overall">${profileColMarkup}<col class="col-mins">${scoutCols}`;
    const headRow = compactLeague
      ? `${watchHead}<th class="col-rank">#</th><th class="col-player">Player</th><th class="col-overall">${scoreLabel}</th>${posHead}${clubHead}<th class="col-age">Age</th><th class="col-mins">Mins</th>`
      : `${watchHead}<th class="col-rank">#</th><th class="col-player">Player</th>${clubHead}${leagueHead}${posHead}<th class="col-age">Age</th><th class="col-overall">${scoreLabel}</th>${profileHead}<th class="col-mins">Mins</th>${scoutHead}`;
    return `<div class="league-scroll"><table class="scout-table scout-table--${viewClass}-view">
      <colgroup>
        ${colgroup}
      </colgroup>
      <thead>
        <tr>
          ${headRow}
        </tr>
      </thead>
      <tbody>${playerRows(players, { showPos, showLeague, scoreLabel, showScout, exportMode, rankStart, profileCols, showClub, compactLeague })}</tbody>
    </table></div>`;
  }

  function renderWeights() {
    syncProfilesForPosition();
    const weightPos = activeWeightPosition();

    if (!weightPos) {
      if (state.groupBy === "position") {
        els.weightsHint.textContent =
          "Pick a position below to adjust profile sliders — each position box uses its own weights.";
        els.weightsGrid.innerHTML = renderWeightPositionPicker();
        bindWeightPositionPicker();
        return;
      }
      els.weightsHint.textContent =
        "Select a position filter to adjust profile sliders — all positions use equal-weight overall until then.";
      els.weightsGrid.innerHTML =
        '<p class="empty" style="padding:0.5rem 0">Pick GK, CB, CM, etc. in the position filter to weight profiles for that role.</p>';
      return;
    }

    els.weightsHint.textContent =
      `Editing ${posLabel(weightPos)} — drag sliders (0 ignores, higher = min score + weight in overall).`;

    const picker =
      state.groupBy === "position"
        ? `<div class="weights__picker">${renderWeightPositionPicker()}</div>`
        : "";

    els.weightsGrid.innerHTML =
      picker +
      `<div class="weights__cards">${state.profiles
        .map((profile) => {
          const stored = state.weights[profile.apiName] ?? DEFAULT_WEIGHT;
          const cls =
            stored > 0 ? "weight-card weight-card--active" : "weight-card weight-card--muted";
          return `<div class="${cls}">
          <span class="weight-card__name" title="${profile.apiName}">${profile.label}</span>
          <input type="range" min="0" max="100" step="1" value="${stored}" class="weight-slider" data-profile="${profile.apiName}" />
          <div class="weight-card__values">
            <span class="weight-card__value">${stored}</span>
            <span class="weight-card__mix">${stored > 0 ? `min ${stored} · ` : ""}${mixPercent(profile.apiName)}% of mix</span>
          </div>
        </div>`;
        })
        .join("")}</div>`;

    if (state.groupBy === "position") bindWeightPositionPicker();

    els.weightsGrid.querySelectorAll(".weight-slider").forEach((slider) => {
      slider.addEventListener("input", (event) => {
        const key = event.target.dataset.profile;
        const posKey = activeWeightPosition();
        if (!posKey) return;
        state.weights[key] = Number(event.target.value);
        state.weightsByPosition[posKey] = { ...state.weights };
        const card = event.target.closest(".weight-card");
        card.className =
          state.weights[key] > 0
            ? "weight-card weight-card--active"
            : "weight-card weight-card--muted";
        card.querySelector(".weight-card__value").textContent = String(state.weights[key]);
        card.querySelector(".weight-card__mix").textContent =
          `${state.weights[key] > 0 ? `min ${state.weights[key]} · ` : ""}${mixPercent(key)}% of mix`;
        renderGrid();
      });
    });
  }

  function renderWeightPositionPicker() {
    return state.positions
      .map((row) => {
        const value = row.value || "";
        const label = posShort(row.label, value);
        const active = state.weightEditPosition === value ? " is-active" : "";
        return `<button type="button" class="filter__btn${active}" data-weight-position="${value}" title="${row.label || value}">${label}</button>`;
      })
      .join("");
  }

  function bindWeightPositionPicker() {
    els.weightsGrid?.querySelectorAll("[data-weight-position]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.weightEditPosition = btn.dataset.weightPosition || null;
        renderWeights();
      });
    });
  }

  function clubSearchHints() {
    const hints = [];
    for (const [label, needle] of [
      ["Team sheet", clubNeedle()],
      ["Opposition", oppoNeedle()],
    ]) {
      if (!needle || resolveClubName(needle)) continue;
      const matches = clubsMatchingNeedle(needle);
      if (!matches.length) continue;
      const shown = matches.slice(0, 6).join(", ");
      const extra = matches.length > 6 ? ` (+${matches.length - 6} more)` : "";
      hints.push(`${label}: ${shown}${extra}`);
    }
    return hints;
  }

  function renderGrid({ skipLoanTag = false } = {}) {
    if (state.building) {
      els.leagueGrid.innerHTML = '<p class="empty">Building player pool — this can take a minute…</p>';
      updateExportButton({ blocks: [] });
      return;
    }
    if (!state.players.length) {
      els.leagueGrid.innerHTML = '<p class="empty">No players loaded yet.</p>';
      updateExportButton({ blocks: [] });
      return;
    }

    const hints = clubSearchHints();
    if (hints.length) {
      els.leagueGrid.classList.add("is-team-sheet");
      syncTeamSheetUi();
      updateSeasonLabel({});
      els.leagueGrid.innerHTML = `<p class="empty">Keep typing or pick from the list — too many clubs still match.<br>${hints.join("<br>")}</p>`;
      lastGrouped = { blocks: [] };
      updateExportButton(lastGrouped);
      return;
    }

    const pool = rankedPool();
    const grouped = buildGrouped(pool);
    const { blocks, limit, groupLabel, viewMode } = grouped;
    const teamMode = viewMode === "team";

    els.leagueGrid.classList.toggle("is-team-sheet", teamMode);
    syncTeamSheetUi();

    const showPos = viewMode === "leagues";
    const showLeague = !teamMode && viewMode !== "leagues" && state.league === "ALL";
    const showScout = !teamMode && viewMode !== "leagues" && (viewMode === "positions" && state.league === "ALL");
    const showClub = !teamMode || (grouped.clubs || []).length > 1;
    const compactLeague = !teamMode && viewMode === "leagues";

    const cards = blocks
      .map((block) => {
        const players = block.players || [];
        const meta = teamMode
          ? block.kind === "team-squad"
            ? `${players.length} unique player${players.length === 1 ? "" : "s"} · strongest Impect overall first`
            : players.length
              ? `${players.length} with enough minutes in this role`
              : "Nobody in the pool hit 25% of their minutes in this role"
          : block.highest_overall
            ? `≥85% of pool (= ${fmt(block.min_score_effective, 1)}) · ${block.qualify_count} qualify · pool ${block.pool_count}`
            : `pool ${block.pool_count}`;
        const scoreLabel = block.kind === "profile" ? "Score" : "Ovr";
        const body = players.length
          ? resultsTable(players, {
              showPos: teamMode ? block.kind === "team-squad" : showPos,
              showLeague,
              scoreLabel,
              showScout,
              showClub,
              compactLeague: compactLeague && block.kind === "league",
              profileCols: block.profileCols || [],
            })
          : `<p class="league-card__empty">${
              teamMode
                ? block.unmatched
                  ? `No club matching “${block.club}” in this player pool. Pick the name from the list.`
                  : "No players here — they may be listed under another role, or Impect has no profile minutes at this position."
                : "No matches for current filters"
            }</p>`;
        const drillBtn =
          teamMode
            ? ""
            : block.kind === "league"
              ? `<button type="button" class="league-card__edit-weights" data-drill-league="${block.key}" title="Top 10 per position">Positions</button>`
              : block.kind === "position"
                ? `<button type="button" class="league-card__edit-weights" data-drill-position="${block.key}" title="Top 10 per profile">Profiles</button>`
                : "";
        const countLabel = teamMode
          ? `${players.length}`
          : `${players.length}/${limit}`;
        return `<section class="league-card${block.empty ? " is-empty" : ""}${block.kind === "team-squad" ? " is-squad" : ""}${block.side === "oppo" ? " is-oppo" : ""}">
          <div class="league-card__head">
            <div>
              <h3 class="league-card__title">${block.title || block.key || "Group"}</h3>
              <p class="league-card__meta">${meta}</p>
            </div>
            <div class="league-card__actions">
              ${drillBtn}
              <span class="league-card__count">${countLabel}</span>
            </div>
          </div>
          ${body}
        </section>`;
      })
      .join("");

    els.leagueGrid.innerHTML = cards || (teamMode
      ? `<p class="empty">No players found for “${clubNeedle()}”. Try the club’s full name from the list.</p>`
      : `<p class="empty">No ${groupLabel}s to show.</p>`);
    lastGrouped = grouped;

    if (!skipLoanTag && !teamMode) {
      void tagLoansOnScreen();
    }

    els.leagueGrid.querySelectorAll("[data-drill-league]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.league = btn.dataset.drillLeague || "ALL";
        state.position = "ALL";
        fillLeagues(state.leagues);
        fillPositions(state.positions);
        updatePerGroupLabel();
        updateSeasonLabel({});
        renderWeights();
        renderGrid();
      });
    });

    els.leagueGrid.querySelectorAll("[data-drill-position]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.position = btn.dataset.drillPosition || "ALL";
        fillPositions(state.positions);
        updatePerGroupLabel();
        updateSeasonLabel({});
        renderWeights();
        renderGrid();
      });
    });

    els.leagueGrid.querySelectorAll("[data-weight-position].league-card__edit-weights").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.weightEditPosition = btn.dataset.weightPosition || null;
        renderWeights();
        els.weightsPanel?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });

    const leagueLabel = state.league === "ALL" ? "all leagues" : state.league;
    const posLabelText =
      state.position === "ALL"
        ? viewMode === "positions" || viewMode === "team"
          ? "each position"
          : "all positions"
        : posLabel(state.position);
    if (teamMode) {
      const clubs = grouped.clubs || selectedClubOrder().map((row) => row.name);
      const watch = clubNeedle();
      const oppo = oppoNeedle();
      const vs = watch && oppo ? `${watch} vs ${oppo}` : clubs.length === 1 ? clubs[0] : clubs.join(" · ");
      els.pageNote.textContent = `${vs} — full squads plus all 10 roles. Empty role = nobody played 25%+ of their minutes there. Names in blue are on loan at that club.`;
      updateExportButton(grouped);
      return;
    }
    const viewText =
      viewMode === "profiles"
        ? "profile"
        : viewMode === "positions"
          ? "position"
          : state.groupBy === "league"
            ? "league"
            : "position";
    const note =
      state.period === "month"
        ? "Monthly overall uses league-relative profile percentiles."
        : viewMode === "profiles"
          ? "Ranked by raw Impect profile score (0–100) for each PV profile."
          : "Season overall uses Impect PV profile ratings (0–100).";
    els.pageNote.textContent = `${note} Top ${limit} per ${viewText} · ${leagueLabel} · ${posLabelText}${
      state.ageBand === "u21" ? " · U21" : state.ageBand === "u25" ? " · U25" : ""
    }${state.loanFilter === "loan" ? " · on loan only" : ""}. Names in blue are on loan. Live / Video / Reports from Fixture Planner — unscouted names are your priority targets.`;
    updateExportButton(grouped);
  }

  function exportContextMeta() {
    return {
      seasonLabel: els.seasonLabel?.textContent || "Who To Scout",
      pageNote: els.pageNote?.textContent || "",
      generatedAt: new Date().toLocaleString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    };
  }

  function exportViewOptions() {
    const viewMode = resolveViewMode();
    const clubs = selectedClubOrder().map((row) => row.name);
    return {
      showPos: viewMode === "leagues",
      showLeague: viewMode !== "leagues" && viewMode !== "team" && state.league === "ALL",
      showScout: viewMode === "leagues" || (viewMode === "positions" && state.league === "ALL"),
      showClub: viewMode !== "team" || clubs.length > 1,
      scoreLabel: viewMode === "profiles" ? "Score" : "Ovr",
    };
  }

  function isTwoClubSheet() {
    const order = selectedClubOrder().filter((row) => !row.unmatched);
    return order.some((row) => row.side === "watch") && order.some((row) => row.side === "oppo");
  }

  function exportBlocks() {
    const pool = rankedPool();
    if (!pool.length) return [];
    const grouped = buildGrouped(pool);
    const blocks = (grouped.blocks || []).filter((block) => (block.players || []).length);
    if (isTwoClubSheet()) {
      return blocks.filter((block) => block.kind === "team-squad");
    }
    return blocks;
  }

  function rowsPerExportPage(firstPage) {
    return firstPage ? 14 : 18;
  }

  function buildExportPageHtml({
    firstPage,
    blockTitle,
    players,
    rankStart,
    pageNum,
    totalPages,
    meta,
    viewOptions,
    compactList = false,
  }) {
    const rankEnd = rankStart + players.length;
    const rankRange = players.length ? `Ranks ${rankStart + 1}–${rankEnd}` : "";
    const pageLabel = `Page ${pageNum}/${totalPages}`;
    const header = firstPage || compactList
      ? `<header class="export-head">
          <div class="export-head__brand">
            <span class="export-head__logo">Port Vale</span>
            <h1 class="export-head__title">Who To Scout</h1>
          </div>
          <p class="export-head__sub">${meta.seasonLabel}</p>
          ${firstPage ? `<p class="export-head__meta">${meta.pageNote}</p>` : ""}
          ${firstPage ? `<p class="export-head__meta">${meta.generatedAt}</p>` : `<p class="export-head__meta">${pageLabel}</p>`}
        </header>`
      : `<header class="export-head">
          <p class="export-head__meta">Who To Scout · ${pageLabel}${rankRange ? ` · ${rankRange}` : ""}</p>
        </header>`;
    return `<div class="export-page${compactList ? " export-page--list" : ""}">
      ${header}
      <p class="export-head__block">${blockTitle}${compactList ? ` · ${players.length} players` : ""}${firstPage || compactList ? "" : ` · ${pageLabel}`}${!compactList && rankRange ? ` · ${rankRange}` : ""}</p>
      ${resultsTable(players, {
        ...viewOptions,
        exportMode: true,
        rankStart,
        profileCols: viewOptions.profileCols || [],
      })}
    </div>`;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) {
        resolve();
        return;
      }
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = () => reject(new Error("Could not load export library."));
      document.head.appendChild(script);
    });
  }

  function slugify(text) {
    return String(text || "export")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60);
  }

  function exportFileName() {
    const stamp = new Date().toISOString().slice(0, 10);
    const mode = state.period === "month" ? `month-${state.year || ""}-${state.month || ""}` : "season";
    if (isTeamSheetMode()) {
      const clubs = selectedClubOrder().map((row) => row.name);
      const club = clubs.length ? clubs.map(slugify).join("-vs-") : slugify(clubNeedle() || oppoNeedle());
      return `who-to-scout-team-${club}-${mode}-${stamp}.pdf`;
    }
    const league = state.league === "ALL" ? "all-leagues" : slugify(state.league);
    return `who-to-scout-${league}-${mode}-${stamp}.pdf`;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function captureExportPages() {
    await loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
    if (!window.html2canvas) throw new Error("Export capture failed.");
    if (document.fonts?.ready) await document.fonts.ready;

    const blocks = exportBlocks();
    if (!blocks.length) throw new Error("Nothing to export — adjust filters or wait for data.");

    const meta = exportContextMeta();
    const viewOptions = exportViewOptions();
    const root = els.exportRoot;
    const pages = [];
    const twoClubList = isTwoClubSheet();

    if (twoClubList) {
      const totalPages = blocks.length;
      for (let i = 0; i < blocks.length; i += 1) {
        const block = blocks[i];
        setStatus(`Rendering PDF page ${i + 1}/${totalPages}…`, "loading");
        root.innerHTML = buildExportPageHtml({
          firstPage: i === 0,
          blockTitle: block.title || block.key || "Squad",
          players: block.players || [],
          rankStart: 0,
          pageNum: i + 1,
          totalPages,
          meta,
          compactList: true,
          viewOptions: {
            showPos: true,
            showLeague: false,
            showScout: false,
            showClub: false,
            scoreLabel: "Ovr",
            profileCols: [],
          },
        });

        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

        const canvas = await window.html2canvas(root.firstElementChild, {
          backgroundColor: "#0c0f14",
          scale: 2,
          logging: false,
          useCORS: true,
          width: 1123,
          height: 794,
          windowWidth: 1123,
          windowHeight: 794,
        });
        pages.push({ imageData: canvas.toDataURL("image/jpeg", 0.94) });
      }
      root.innerHTML = "";
      return pages;
    }

    let pageCount = 0;

    blocks.forEach((block) => {
      const players = block.players || [];
      const firstRows = rowsPerExportPage(true);
      const otherRows = rowsPerExportPage(false);
      const blockPages =
        players.length <= firstRows
          ? 1
          : 1 + Math.ceil((players.length - firstRows) / otherRows);
      pageCount += blockPages;
    });

    let rendered = 0;
    for (const block of blocks) {
      const players = block.players || [];
      const blockTitle = block.title || block.key || "Group";
      const firstRows = rowsPerExportPage(true);
      const otherRows = rowsPerExportPage(false);
      const blockPages =
        players.length <= firstRows
          ? 1
          : 1 + Math.ceil((players.length - firstRows) / otherRows);
      let offset = 0;

      for (let page = 0; page < blockPages; page += 1) {
        const perPage = page === 0 ? firstRows : otherRows;
        const chunk = players.slice(offset, offset + perPage);
        rendered += 1;
        setStatus(`Rendering PDF page ${rendered}/${pageCount}…`, "loading");
        root.innerHTML = buildExportPageHtml({
          firstPage: page === 0 && rendered === 1,
          blockTitle,
          players: chunk,
          rankStart: offset,
          pageNum: page + 1,
          totalPages: blockPages,
          meta,
          viewOptions: {
            ...viewOptions,
            profileCols: block.profileCols || viewOptions.profileCols || [],
          },
        });

        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

        const canvas = await window.html2canvas(root.firstElementChild, {
          backgroundColor: "#0c0f14",
          scale: 2,
          logging: false,
          useCORS: true,
          width: 1123,
          height: 794,
          windowWidth: 1123,
          windowHeight: 794,
        });
        pages.push({ imageData: canvas.toDataURL("image/jpeg", 0.94) });
        offset += perPage;
      }
    }

    root.innerHTML = "";
    return pages;
  }

  async function exportPdf() {
    if (els.exportPdfBtn?.disabled) return;
    els.exportPdfBtn.disabled = true;
    setStatus("Preparing PDF export…", "loading");
    try {
      const pages = await captureExportPages();
      setStatus("Building PDF…", "loading");
      const payload = {
        filename: exportFileName(),
        pages,
      };
      const res = await fetch("/api/scouting/export-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const raw = await res.text();
        let message = `Export failed (${res.status}).`;
        try {
          const data = raw ? JSON.parse(raw) : {};
          message = data.detail || message;
        } catch {
          if (raw) message = raw.slice(0, 160);
        }
        throw new Error(message);
      }
      const blob = await res.blob();
      const savedDesktopPath = res.headers.get("X-Saved-Desktop-Path");
      downloadBlob(blob, payload.filename);
      if (savedDesktopPath) {
        setStatus(`PDF saved to Desktop and downloaded.`, "warn");
      } else {
        setStatus("PDF downloaded.", "warn");
      }
    } catch (error) {
      setStatus(error.message || "PDF export failed.", "error");
    } finally {
      updateExportButton(lastGrouped);
    }
  }

  function updateSeasonLabel(data) {
    if (data?.season_label) state.seasonLabel = String(data.season_label);
    else if (data?.period_label) {
      const match = String(data.period_label).match(/(\d{2}\/\d{2})/);
      if (match) state.seasonLabel = match[1];
    }
    const label =
      data?.period_label ||
      (data?.period === "month" ? data?.month_label : data?.season_label) ||
      "Full season";
    const limit = parseNum(els.perLeague) || data?.per_league_limit || 10;
    if (isTeamSheetMode()) {
      const watch = clubNeedle();
      const oppo = oppoNeedle();
      const vs = watch && oppo ? `${watch} vs ${oppo}` : watch || oppo;
      els.seasonLabel.textContent = `${label} · ${vs} · match brief`;
      return;
    }
    const mode = resolveViewMode();
    const groupWord =
      mode === "profiles" ? "profile" : mode === "positions" ? "position" : "league";
    const context =
      state.league !== "ALL"
        ? state.position !== "ALL"
          ? `${state.league} · ${posLabel(state.position)}`
          : state.league
        : state.position !== "ALL"
          ? posLabel(state.position)
          : null;
    els.seasonLabel.textContent = context
      ? `${label} · ${context} · Top ${limit} per ${groupWord}`
      : `${label} · Top ${limit} per ${groupWord} (fills below 85% cut-off if needed)`;
  }

  function schedulePoll() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(() => loadData({ silent: true }), 4000);
  }

  async function loadData({ refresh = false, silent = false } = {}) {
    if (state.loading && !silent) return;
    state.loading = true;
    if (!silent) setStatus(state.building ? "Still building player pool…" : "Loading…", "loading");

    try {
      const params = new URLSearchParams({ period: state.period });
      if (state.period === "month" && state.year != null && state.month != null) {
        params.set("year", String(state.year));
        params.set("month", String(state.month));
      }
      if (refresh) params.set("refresh", "true");

      const data = await fetchJson(`/api/who-to-scout/data?${params}`);

      if (data.building) {
        state.building = true;
        if (!silent) setStatus("Building player pool in the background — checking again shortly…", "loading");
        if (data.positions) fillPositions(data.positions);
        if (data.leagues?.length) fillLeagues(data.leagues);
        syncFilterVisibility();
        if (data.month_options?.length) {
          const first = data.month_options[0];
          fillMonths(data.month_options, data.year ?? first.year, data.month ?? first.month);
        }
        updateSeasonLabel(data);
        renderWeights();
        renderGrid();
        schedulePoll();
        return;
      }

      state.building = false;
      state.players = data.players || [];
      state.leagues = data.leagues || [];
      state.positions = data.positions || [];
      state.profilesByPosition = data.profiles_by_position || {};

      if (data.month_options?.length) {
        fillMonths(
          data.month_options,
          data.year ?? state.year ?? data.month_options[0].year,
          data.month ?? state.month ?? data.month_options[0].month,
        );
      }
      fillPositions(state.positions);
      fillLeagues(state.leagues);
      fillClubOptions();
      syncFilterVisibility();
      syncTeamSheetUi();
      syncProfilesForPosition();
      updateSeasonLabel(data);
      renderWeights();
      if (isTeamSheetMode()) {
        loadTeamSheetExtras();
      } else if (state.loanFilter === "loan") {
        void (async () => {
          await ensureLoanFilterReady();
          renderGrid();
        })();
      } else {
        renderGrid();
      }
      setStatus("");
    } catch (error) {
      setStatus(`Could not load data: ${error.message}`, "error");
      els.leagueGrid.innerHTML = '<p class="empty">Failed to load — try Refresh data.</p>';
    } finally {
      state.loading = false;
    }
  }

  function bindEvents() {
    els.periodGroup?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-period]");
      if (!btn) return;
      state.period = btn.dataset.period || "season";
      els.periodGroup.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      els.monthWrap.hidden = state.period !== "month";
      loadData();
    });

    els.monthSelect?.addEventListener("change", () => {
      const match = /^(\d{4})-(\d{2})$/.exec(els.monthSelect.value || "");
      if (!match) return;
      state.year = Number(match[1]);
      state.month = Number(match[2]);
      loadData();
    });

    els.groupByControl?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-group-by]");
      if (!btn) return;
      state.groupBy = btn.dataset.groupBy || "league";
      els.groupByControl.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      if (state.groupBy === "position" && !state.weightEditPosition && state.positions[0]) {
        state.weightEditPosition = state.positions[0].value;
      }
      syncFilterVisibility();
      updateSeasonLabel({});
      renderWeights();
      renderGrid();
    });

    els.leagueGroup?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-league]");
      if (!btn) return;
      state.league = btn.dataset.league || "ALL";
      if (state.league === "ALL" && state.position !== "ALL" && state.groupBy === "league") {
        /* keep position drill-down across all leagues */
      }
      els.leagueGroup.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      updatePerGroupLabel();
      updateSeasonLabel({});
      renderGrid();
    });

    els.positionGroup?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-position]");
      if (!btn) return;
      state.position = btn.dataset.position || "ALL";
      els.positionGroup.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      updatePerGroupLabel();
      updateSeasonLabel({});
      renderWeights();
      renderGrid();
    });

    els.ageBandGroup?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-age-band]");
      if (!btn) return;
      state.ageBand = btn.dataset.ageBand || "all";
      els.ageBandGroup.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      updateSeasonLabel({});
      renderGrid();
    });

    els.loanFilterGroup?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-loan]");
      if (!btn) return;
      state.loanFilter = btn.dataset.loan || "all";
      els.loanFilterGroup.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      void (async () => {
        if (state.loanFilter === "loan") {
          await ensureLoanFilterReady();
        }
        updateSeasonLabel({});
        renderGrid();
      })();
    });

    function debounce(fn, ms) {
      let timer = 0;
      return () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(fn, ms);
      };
    }

    function applyClubSearch() {
      syncTeamSheetUi();
      updateSeasonLabel({});
      loadTeamSheetExtras();
    }

    function applyNumericFilters() {
      syncTeamSheetUi();
      updateSeasonLabel({});
      renderWeights();
      renderGrid();
    }

    const scheduleClubSearch = debounce(applyClubSearch, 200);
    const scheduleNumericFilters = debounce(applyNumericFilters, 150);

    [els.clubFilter, els.oppoFilter].forEach((input) => {
      input?.addEventListener("input", scheduleClubSearch);
      input?.addEventListener("change", applyClubSearch);
    });

    [els.minMinutes, els.minAge, els.maxAge, els.minHeight, els.perLeague].forEach((input) => {
      input?.addEventListener("input", scheduleNumericFilters);
    });

    els.clearClub?.addEventListener("click", () => {
      if (!els.clubFilter) return;
      els.clubFilter.value = "";
      applyClubSearch();
    });

    els.clearOppo?.addEventListener("click", () => {
      if (!els.oppoFilter) return;
      els.oppoFilter.value = "";
      applyClubSearch();
    });

    els.refreshBtn?.addEventListener("click", () => loadData({ refresh: true }));
    els.exportPdfBtn?.addEventListener("click", exportPdf);

    els.leagueGrid?.addEventListener("click", (event) => {
      const button = event.target.closest("button.watch-chip");
      if (!button) return;
      event.preventDefault();
      openWatchPrompt(button);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeWatchPrompt();
    });
  }

  async function init() {
    bindEvents();
    syncFilterVisibility();
    els.monthWrap.hidden = state.period !== "month";
    const options = defaultMonthOptions();
    fillMonths(options, options[0].year, options[0].month);

    try {
      const meta = await fetchJson("/api/who-to-scout/meta");
      state.profilesByPosition = meta.profiles_by_position || {};
      state.leagues = meta.leagues || [];
      state.positions = meta.positions || [];
      fillLeagues(state.leagues);
      fillPositions(state.positions);
      syncFilterVisibility();
    } catch {
      /* meta optional — data endpoint includes profiles */
    }

    void loadWatchList();
    loadData();
  }

  init();
})();
