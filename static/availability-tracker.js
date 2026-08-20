const DEFAULT_SEASON = "26/27";
const INJURY_TRIGGER_STATUSES = new Set(["INJ"]);
const FALLBACK_MATCH_STATUSES = ["AVAIL", "INJ", "MM", "UN", "N", "INT", "LOAN", "SUB"];

const state = {
  meta: null,
  board: null,
  season: DEFAULT_SEASON,
  view: "log",
  showMatches: true,
  matrixFilter: "all",
  logMode: "match",
  logSessionKey: "friendly:new",
  logMatchSessionId: "",
  logEntries: {},
  injuryPending: null,
  loggingActive: false,
  injuryLoggingActive: false,
  injuryDetailPlayerId: "",
  loading: false,
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  refreshBtn: document.getElementById("refreshBtn"),
  pageSubtitle: document.getElementById("pageSubtitle"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  matrixView: document.getElementById("matrixView"),
  logView: document.getElementById("logView"),
  logLanding: document.getElementById("logLanding"),
  logSessionPanel: document.getElementById("logSessionPanel"),
  submitMatchBtn: document.getElementById("submitMatchBtn"),
  submitInjuryBtn: document.getElementById("submitInjuryBtn"),
  logInjuryPanel: document.getElementById("logInjuryPanel"),
  logInjuryPlayers: document.getElementById("logInjuryPlayers"),
  cancelInjuryLogBtn: document.getElementById("cancelInjuryLogBtn"),
  logLandingIntro: document.getElementById("logLandingIntro"),
  syncRosterLandingBtn: document.getElementById("syncRosterLandingBtn"),
  rosterView: document.getElementById("rosterView"),
  injuriesView: document.getElementById("injuriesView"),
  injuriesListWrap: document.getElementById("injuriesListWrap"),
  injuriesList: document.getElementById("injuriesList"),
  injuryDetailPanel: document.getElementById("injuryDetailPanel"),
  injuryDetailBackBtn: document.getElementById("injuryDetailBackBtn"),
  injuryDetailHead: document.getElementById("injuryDetailHead"),
  injuryDetailBody: document.getElementById("injuryDetailBody"),
  matrixRoot: document.getElementById("matrixRoot"),
  summaryView: document.getElementById("summaryView"),
  summarySlide: document.getElementById("summarySlide"),
  presentSummaryBtn: document.getElementById("presentSummaryBtn"),
  importRosterBtn: document.getElementById("importRosterBtn"),
  purgeInactiveBtn: document.getElementById("purgeInactiveBtn"),
  logTitle: document.getElementById("logTitle"),
  logDescription: document.getElementById("logDescription"),
  logDate: document.getElementById("logDate"),
  logMatchSessionWrap: document.getElementById("logMatchSessionWrap"),
  logSession: document.getElementById("logSession"),
  logOpponentWrap: document.getElementById("logOpponentWrap"),
  logOpponent: document.getElementById("logOpponent"),
  logVenueWrap: document.getElementById("logVenueWrap"),
  logVenue: document.getElementById("logVenue"),
  logPlayers: document.getElementById("logPlayers"),
  saveSessionBtn: document.getElementById("saveSessionBtn"),
  cancelSessionBtn: document.getElementById("cancelSessionBtn"),
  rosterList: document.getElementById("rosterList"),
  addPlayerBtn: document.getElementById("addPlayerBtn"),
  injuryDialog: document.getElementById("injuryDialog"),
  injuryForm: document.getElementById("injuryForm"),
  injuryDialogTitle: document.getElementById("injuryDialogTitle"),
  injuryDialogIntro: document.getElementById("injuryDialogIntro"),
  injuryPlayerId: document.getElementById("injuryPlayerId"),
  injuryStatusWrap: document.getElementById("injuryStatusWrap"),
  injuryStatus: document.getElementById("injuryStatus"),
  injurySince: document.getElementById("injurySince"),
  injuryReturnDate: document.getElementById("injuryReturnDate"),
  injuryNotes: document.getElementById("injuryNotes"),
  injuryAwayFromClub: document.getElementById("injuryAwayFromClub"),
  clearInjuryBtn: document.getElementById("clearInjuryBtn"),
  cancelInjuryBtn: document.getElementById("cancelInjuryBtn"),
  playerDialog: document.getElementById("playerDialog"),
  playerForm: document.getElementById("playerForm"),
  playerDialogTitle: document.getElementById("playerDialogTitle"),
  playerEditId: document.getElementById("playerEditId"),
  playerName: document.getElementById("playerName"),
  playerPosition: document.getElementById("playerPosition"),
  playerHighlight: document.getElementById("playerHighlight"),
  deletePlayerBtn: document.getElementById("deletePlayerBtn"),
};

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `av-status av-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

async function fetchJson(url, options = {}) {
  let res;
  try {
    res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (error) {
    const reason = error?.message || "Failed to fetch";
    throw new Error(
      reason === "Failed to fetch"
        ? "Network error talking to the hub. Check you’re on http://178.128.161.215 and try Refresh."
        : reason
    );
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.map((row) => row.msg || JSON.stringify(row)).join("; ")
      : detail || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function formatDateLabel(iso, { isToday = false } = {}) {
  const date = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  const label = date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return isToday ? `Today · ${label}` : label;
}

function dateDropdownOptions(preferredIso = "") {
  const dates = new Set();
  const today = todayIso();
  const anchor = preferredIso ? new Date(`${preferredIso}T12:00:00`) : new Date();

  for (let offset = -28; offset <= 14; offset += 1) {
    const date = new Date(anchor);
    date.setDate(anchor.getDate() + offset);
    dates.add(date.toISOString().slice(0, 10));
  }

  for (const session of state.board?.sessions || []) {
    if (session.date) dates.add(String(session.date).slice(0, 10));
  }
  if (preferredIso) dates.add(preferredIso);

  return [...dates].sort();
}

function populateDateDropdown(preferredIso = "") {
  if (!els.logDate) return;
  const preferred = (preferredIso || els.logDate.value || todayIso()).slice(0, 10);
  const today = todayIso();
  const options = dateDropdownOptions(preferred);

  els.logDate.innerHTML = options
    .map((iso) => `<option value="${iso}">${formatDateLabel(iso, { isToday: iso === today })}</option>`)
    .join("");

  els.logDate.value = options.includes(preferred) ? preferred : today;
}

function addWeeksIso(weeks) {
  const date = new Date();
  date.setDate(date.getDate() + weeks * 7);
  return date.toISOString().slice(0, 10);
}

function statusLabel(code) {
  return state.meta?.status_codes?.[code]?.label || code;
}

function statusShort(code) {
  const short = state.meta?.status_codes?.[code]?.short;
  if (short) return short;
  return code === "AVAIL" ? "✓" : code;
}

function quickStatusesForMode() {
  return state.meta?.match_statuses || FALLBACK_MATCH_STATUSES;
}

function quickStatusesForSession(session) {
  return state.meta?.match_statuses || FALLBACK_MATCH_STATUSES;
}

function positionLabel(id) {
  return state.meta?.position_groups?.find((row) => row.id === id)?.label || id;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function playerPhoto(player, className = "av-roster-card__photo") {
  if (player.photo_url) {
    return `<img class="${className}" src="${player.photo_url}" alt="" loading="lazy" />`;
  }
  return `<div class="${className}"></div>`;
}

function visibleSessions() {
  return (state.board?.sessions || []).filter((session) => {
    if (session.type === "training") return false;
    if (session.type !== "match") return false;
    if (state.matrixFilter === "league" && session.match_category !== "league") return false;
    return true;
  });
}

function upcomingMatches() {
  return (state.board?.sessions || []).filter((session) => session.type === "match" && !session.complete);
}

function rosterPlayers({ activeOnly = false } = {}) {
  const roster = state.board?.roster || [];
  if (!activeOnly) return roster;
  return roster.filter((player) => player.active !== false);
}

function isInjuredAway(player) {
  return Boolean(
    player?.away_from_club
    || (player?.injury?.away_from_club && player?.injury?.status && player.injury.status !== "AVAIL")
  );
}

function squadAvailabilityPlayers() {
  return rosterPlayers({ activeOnly: true }).filter((player) => !isInjuredAway(player));
}

function injuredAwayPlayers() {
  return rosterPlayers({ activeOnly: true }).filter((player) => isInjuredAway(player));
}

function renderInjuredAwayNote() {
  const away = injuredAwayPlayers();
  if (!away.length) return "";
  const names = away.map((player) => player.name).join(", ");
  const reason = away.length === 1
    ? `${names} is injured away from the club and is tracked in personal availability only.`
    : `${names} are injured away from the club and are tracked in personal availability only.`;
  return `<p class="av-away-note">${escapeHtml(reason)}</p>`;
}

function playersByGroup({ activeOnly = false, squadOnly = false } = {}) {
  const groups = state.meta?.position_groups || [];
  const lookup = Object.fromEntries(groups.map((group) => [group.id, []]));
  const source = squadOnly ? squadAvailabilityPlayers() : rosterPlayers({ activeOnly });
  for (const player of source) {
    const key = player.position_group || "MID";
    if (!lookup[key]) lookup[key] = [];
    lookup[key].push(player);
  }
  return groups
    .map((group) => ({ ...group, players: lookup[group.id] || [] }))
    .filter((group) => group.players.length > 0);
}

function playerById(playerId) {
  return (state.board?.roster || []).find((row) => row.id === playerId);
}

function defaultLogEntries() {
  const entries = {};
  for (const player of squadAvailabilityPlayers()) {
    if (player.injury?.status && player.injury.status !== "AVAIL") {
      entries[player.id] = { status: player.injury.status };
    } else {
      entries[player.id] = { status: "AVAIL" };
    }
  }
  return entries;
}

function sessionById(sessionId) {
  return (state.board?.sessions || []).find((row) => row.id === sessionId);
}

function parseSessionKey(key) {
  const token = String(key || "");
  const splitAt = token.indexOf(":");
  if (splitAt === -1) return { kind: "friendly", payload: "new" };
  return {
    kind: token.slice(0, splitAt),
    payload: token.slice(splitAt + 1),
  };
}

function setLogMode(mode) {
  state.logMode = mode;
  els.logMatchSessionWrap?.classList.remove("hidden");
}

function buildMatchSessionOptions() {
  const league = upcomingMatches();
  let html = "";
  if (league.length) {
    html += '<optgroup label="League fixtures">';
    html += league
      .map((match) => `<option value="league:${match.id}">${match.date} · ${match.label}</option>`)
      .join("");
    html += "</optgroup>";
  }
  html += '<optgroup label="Other matches">';
  html += '<option value="friendly:new">Friendly</option>';
  html += '<option value="cup:new">Cup game</option>';
  html += "</optgroup>";
  return html;
}

function populateMatchSessionDropdown() {
  if (!els.logSession) return;
  const previous = state.logSessionKey || els.logSession.value;
  els.logSession.innerHTML = buildMatchSessionOptions();
  const hasPrevious = [...els.logSession.options].some((opt) => opt.value === previous);
  if (hasPrevious) {
    els.logSession.value = previous;
  } else if (upcomingMatches().length) {
    els.logSession.value = `league:${upcomingMatches()[0].id}`;
  } else {
    els.logSession.value = "friendly:new";
  }
  state.logSessionKey = els.logSession.value;
  onMatchSessionChange({ quiet: true });
}

function populateSessionDropdown() {
  populateMatchSessionDropdown();
}

function onMatchSessionChange({ quiet = false } = {}) {
  state.logSessionKey = els.logSession.value;
  const { kind, payload } = parseSessionKey(state.logSessionKey);

  const needsOpponent = kind === "friendly" || kind === "cup";
  els.logOpponentWrap.classList.toggle("hidden", !needsOpponent);
  els.logVenueWrap.classList.toggle("hidden", !needsOpponent);

  if (kind === "league") {
    state.logMatchSessionId = payload;
    const session = sessionById(payload);
    if (session?.date) {
      populateDateDropdown(session.date);
      els.logDate.value = session.date;
    }
    loadEntriesForSelectedMatch();
  } else {
    state.logMatchSessionId = "";
    populateDateDropdown(els.logDate.value || todayIso());
    if (!quiet) {
      state.logEntries = defaultLogEntries();
    }
  }

  updateLogHeader();
  if (state.loggingActive && !quiet) renderQuickLog();
}

function onSessionChange({ quiet = false } = {}) {
  onMatchSessionChange({ quiet });
}

function sessionSelectionMeta() {
  const { kind, payload } = parseSessionKey(state.logSessionKey || els.logSession?.value);
  if (kind === "league") {
    const session = sessionById(payload);
    const matchId = session?.match_id || (payload.startsWith("m-") ? Number(payload.slice(2)) : null);
    return { kind, payload, session, matchId };
  }
  return { kind, payload, session: null, matchId: null };
}

function updateLogHeader() {
  els.logTitle.textContent = "Match availability";
  els.logDescription.textContent = "Pick the fixture, then log who is out.";
  els.saveSessionBtn.textContent = "Submit match availability";
}

function populateInjurySinceDropdown(preferredIso = "") {
  if (!els.injurySince) return;
  const preferred = (preferredIso || todayIso()).slice(0, 10);
  const options = dateDropdownOptions(preferred);
  const today = todayIso();
  els.injurySince.innerHTML = options
    .map((iso) => `<option value="${iso}">${formatDateLabel(iso, { isToday: iso === today })}</option>`)
    .join("");
  els.injurySince.value = options.includes(preferred) ? preferred : today;
}

function populateReturnDateDropdown(preferredIso = "") {
  if (!els.injuryReturnDate) return;
  const options = ['<option value="">Unknown / TBC</option>'];
  for (let weeks = 1; weeks <= 12; weeks += 1) {
    const iso = addWeeksIso(weeks);
    options.push(`<option value="${iso}">${formatDateLabel(iso)} (${weeks} wk)</option>`);
  }
  els.injuryReturnDate.innerHTML = options.join("");
  if (preferredIso) {
    const exists = [...els.injuryReturnDate.options].some((opt) => opt.value === preferredIso);
    if (!exists) {
      const opt = document.createElement("option");
      opt.value = preferredIso;
      opt.textContent = formatDateLabel(preferredIso);
      els.injuryReturnDate.appendChild(opt);
    }
    els.injuryReturnDate.value = preferredIso;
  }
}

function updateLogLanding() {
  const empty = !rosterPlayers({ activeOnly: true }).length;
  if (els.logLandingIntro) {
    els.logLandingIntro.textContent = empty
      ? `No squad loaded for ${state.season} yet. Sync squad to pull the current first team from port-vale.co.uk.`
      : "Submit match availability ahead of a fixture, or log a longer-term injury. Saved sessions feed the Matrix and Roster.";
  }
  els.submitMatchBtn?.toggleAttribute("disabled", empty);
  els.submitInjuryBtn?.toggleAttribute("disabled", empty);
  els.syncRosterLandingBtn?.classList.toggle("hidden", !empty);
}

function showLogPanels({ session = false, injury = false } = {}) {
  state.loggingActive = session;
  state.injuryLoggingActive = injury;
  els.logLanding.classList.toggle("hidden", session || injury);
  els.logSessionPanel.classList.toggle("hidden", !session);
  els.logInjuryPanel?.classList.toggle("hidden", !injury);
  if (!session && !injury) updateLogLanding();
  if (session) renderQuickLog();
  if (injury) renderInjuryLog();
}

function showLoggingPanel(active) {
  showLogPanels({ session: active, injury: false });
}

async function tryImportRosterIfEmpty({ quiet = false } = {}) {
  if (state.board?.roster?.some((player) => player.active !== false)) return false;
  try {
    if (!quiet) {
      els.statusBar.textContent = state.season === "26/27"
        ? "Loading squad from port-vale.co.uk…"
        : "Importing squad from Impect…";
    }
    const result = await fetchJson(`/api/availability/roster/import?season=${encodeURIComponent(state.season)}`, {
      method: "POST",
    });
    if (!quiet && result.total) {
      const source = result.source === "port-vale.co.uk"
        ? "port-vale.co.uk"
        : (result.source_season && result.source_season !== state.season
          ? `${result.source_season} Impect`
          : "Impect");
      let message = `Loaded ${result.total} players for ${state.season} from ${source}`;
      if (result.warning) message += ` · ${result.warning}`;
      setStatus(message, result.warning ? "warn" : "ok");
    }
    return (result.total || 0) > 0;
  } catch (error) {
    if (!quiet) setStatus(error.message, "error");
    return false;
  }
}

function cancelLoggingSession() {
  state.logEntries = {};
  showLogPanels({ session: false, injury: false });
  setStatus("");
}

function cancelInjuryLog() {
  showLogPanels({ session: false, injury: false });
  setStatus("");
}

function startInjuryLog() {
  if (!rosterPlayers({ activeOnly: true }).length) {
    setStatus("Sync squad first.", "error");
    return;
  }
  state.view = "log";
  state.loggingActive = false;
  state.injuryLoggingActive = true;
  renderView();
  setStatus("Pick a player to log their injury.", "ok");
}

function startGameLog() {
  if (!rosterPlayers({ activeOnly: true }).length) {
    setStatus("Sync or add players in the Roster tab first.", "error");
    return;
  }
  const matches = upcomingMatches();
  state.view = "log";
  setLogMode("match");
  state.logEntries = defaultLogEntries();
  populateDateDropdown(todayIso());
  populateMatchSessionDropdown();
  if (matches.length) {
    state.logSessionKey = `league:${matches[0].id}`;
    els.logSession.value = state.logSessionKey;
    onMatchSessionChange({ quiet: true });
    setStatus("Pick the fixture, then mark each player.", "ok");
  } else {
    state.logSessionKey = "friendly:new";
    els.logSession.value = state.logSessionKey;
    onMatchSessionChange({ quiet: true });
    setStatus("No upcoming league fixtures — log a friendly or cup game.", "ok");
  }
  renderView();
  showLoggingPanel(true);
}

function loadEntriesForSelectedMatch() {
  const { kind, payload } = parseSessionKey(state.logSessionKey);
  if (kind !== "league") return;
  const session = sessionById(payload);
  if (!session) return;
  populateDateDropdown(session.date || todayIso());
  els.logDate.value = session.date || todayIso();
  const entries = { ...defaultLogEntries() };
  for (const player of state.board?.roster || []) {
    const cell = player.cells?.[session.id];
    if (cell?.status) {
      entries[player.id] = { status: cell.status };
    }
  }
  state.logEntries = entries;
  renderQuickLog();
}

function renderSeasonToggle() {
  const seasons = state.meta?.seasons || [];
  els.seasonToggle.innerHTML = seasons
    .map(
      (row) => `
        <button
          type="button"
          class="av-season-btn ${row.season === state.season ? "av-season-btn--active" : ""}"
          data-season="${row.season}"
        >${row.season}</button>
      `
    )
    .join("");

  els.seasonToggle.querySelectorAll("[data-season]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.season = btn.dataset.season;
      renderSeasonToggle();
      loadBoard();
    });
  });
}

function renderMatrix() {
  const sessions = visibleSessions();
  const groups = playersByGroup({ squadOnly: true });

  if (state.loading && !rosterPlayers({ activeOnly: false }).length) {
    els.matrixRoot.innerHTML = `
      <div style="padding:1.25rem;color:var(--text-muted)">
        Loading saved squad…
      </div>
    `;
    return;
  }

  if (!squadAvailabilityPlayers().length) {
    els.matrixRoot.innerHTML = `
      <div style="padding:1.25rem;color:var(--text-muted)">
        No squad roster yet. Use <strong>Sync squad</strong> or add players in the Roster tab.
      </div>
      ${renderInjuredAwayNote()}
    `;
    return;
  }

  const headerCells = sessions
    .map((session) => {
      const resultClass = session.result ? `av-col-result--${session.result}` : "";
      const typeClass = session.match_category === "friendly"
        ? "av-col-head--friendly"
        : session.match_category === "cup"
          ? "av-col-head--cup"
          : "av-col-head--match";
      const resultLine = session.type === "match" && session.result
        ? `<span class="av-col-result ${resultClass}">${session.result} ${session.score || ""}</span>`
        : "";
      return `
        <th class="av-col-head ${typeClass}" title="${session.label}">
          <span class="av-col-date">${session.date || ""}</span>
          <span class="av-col-label">${session.label || session.date}</span>
          ${resultLine}
        </th>
      `;
    })
    .join("");

  const bodyRows = groups
    .flatMap((group) => {
      const groupRow = `
        <tr class="av-group-row">
          <td class="av-sticky-col" colspan="${sessions.length + 1}">${group.label}</td>
        </tr>
      `;
      const playerRows = group.players.map((player) => {
        const injuryBadge = player.injury?.status && player.injury.status !== "AVAIL"
          ? `<span class="av-injury-badge av-injury-badge--${player.injury.status}" title="${player.injury.notes || ""}">${player.injury.status}</span>`
          : "";
        const photo = player.photo_url
          ? `<img class="av-player-photo" src="${player.photo_url}" alt="" loading="lazy" />`
          : `<div class="av-player-photo"></div>`;
        const cells = sessions
          .map((session) => {
            const cell = player.cells?.[session.id] || { status: "AVAIL", display: "", source: "default" };
            const display = cell.display ?? "";
            const status = cell.status || "AVAIL";
            const injuryClass = cell.source === "injury" ? " av-cell--injury" : "";
            const managedClass = cell.managed_minutes || cell.source === "managed" || status === "MM"
              ? " av-cell--managed"
              : "";
            return `
              <td
                class="av-cell av-cell--${status}${injuryClass}${managedClass}"
                data-player-id="${player.id}"
                data-session-id="${session.id}"
                data-status="${status}"
                title="${cell.source || ""}"
              >${display}</td>
            `;
          })
          .join("");
        return `
          <tr>
            <td class="av-sticky-col">
              <div class="av-player-cell ${player.highlight ? `av-player-cell--${player.highlight}` : ""}">
                ${photo}
                <div>
                  <div class="av-player-name">${player.name}${injuryBadge}</div>
                  <div class="av-player-meta">${player.bracket || ""} · ${player.season_minutes || 0} mins</div>
                </div>
              </div>
            </td>
            ${cells}
          </tr>
        `;
      });
      return [groupRow, ...playerRows];
    })
    .join("");

  els.matrixRoot.innerHTML = `
    <table class="av-matrix">
      <thead>
        <tr>
          <th class="av-sticky-col">Player</th>
          ${headerCells}
        </tr>
      </thead>
      <tbody>${bodyRows}</tbody>
    </table>
    ${renderInjuredAwayNote()}
  `;
}

function cycleStatus(current) {
  const sessionId = current.dataset.sessionId;
  const session = sessionById(sessionId);
  const isMatchComplete = session?.type === "match" && session?.complete;
  const currentStatus = current.dataset.status || "AVAIL";

  if (isMatchComplete && /^\d+$/.test(currentStatus)) {
    return currentStatus;
  }

  const options = quickStatusesForSession(session);
  const index = options.indexOf(currentStatus.toUpperCase());
  return options[(index + 1) % options.length];
}

async function setStandingPlayerStatus(playerId, status, { notes = "" } = {}) {
  return fetchJson(`/api/availability/injury/${encodeURIComponent(playerId)}?season=${encodeURIComponent(state.season)}`, {
    method: "PUT",
    body: JSON.stringify({
      status,
      since: todayIso(),
      return_date: null,
      notes,
      away_from_club: false,
    }),
  });
}

async function clearStandingPlayerStatus(playerId) {
  return setStandingPlayerStatus(playerId, "AVAIL");
}

async function applySessionStatus(playerId, sessionId, status) {
  await fetchJson(`/api/availability/session/${encodeURIComponent(sessionId)}?season=${encodeURIComponent(state.season)}`, {
    method: "PATCH",
    body: JSON.stringify({
      entries: {
        [playerId]: { status },
      },
    }),
  });
}

async function openCellEditor(cell) {
  const playerId = cell.dataset.playerId;
  const sessionId = cell.dataset.sessionId;
  const previousStatus = cell.dataset.status || "AVAIL";
  const nextStatus = cycleStatus(cell);

  if (INJURY_TRIGGER_STATUSES.has(nextStatus)) {
    state.injuryPending = {
      playerId,
      previousStatus,
      sessionId,
      source: "matrix",
    };
    state.logEntries[playerId] = { status: "INJ" };
    openInjuryDialog(playerId, { fromStatus: true });
    return;
  }

  try {
    if (nextStatus === "MM") {
      await setStandingPlayerStatus(playerId, "MM");
      setStatus("Managed minutes set — matrix shows MM after games are played.", "ok");
    } else if (previousStatus === "MM" || playerById(playerId)?.injury?.status === "MM") {
      // Cycling away from MM clears the standing flag; also write the cell if needed.
      if (nextStatus === "AVAIL") {
        await clearStandingPlayerStatus(playerId);
      } else {
        await setStandingPlayerStatus(playerId, "AVAIL");
        const session = sessionById(sessionId);
        if (session?.complete || nextStatus !== "AVAIL") {
          await applySessionStatus(playerId, sessionId, nextStatus);
        }
      }
    } else {
      await applySessionStatus(playerId, sessionId, nextStatus);
    }
    await loadBoard({ quiet: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderLogPlayerCard(player) {
  const current = state.logEntries[player.id]?.status || "AVAIL";
  const statuses = quickStatusesForMode();
  const pills = statuses.map((status) => `
    <button
      type="button"
      class="av-status-pill av-status-pill--${status} ${current === status ? "av-status-pill--active" : ""}"
      data-player-id="${player.id}"
      data-status="${status}"
      title="${statusLabel(status)}"
    >${statusShort(status)}</button>
  `).join("");
  const photo = player.photo_url
    ? `<img class="av-log-card__photo" src="${player.photo_url}" alt="" loading="lazy" />`
    : `<div class="av-log-card__photo"></div>`;
  const statusClass = current !== "AVAIL" ? ` av-log-card--${current}` : "";
  const highlightClass = player.highlight ? ` av-log-card--${player.highlight}` : "";
  const injuryHint = player.injury?.status && player.injury.status !== "AVAIL"
    ? `<span class="av-log-card__injury" title="${player.injury.notes || ""}">${player.injury.status}</span>`
    : "";

  return `
    <article class="av-log-card${statusClass}${highlightClass}" data-player-id="${player.id}">
      <div class="av-log-card__head">
        ${photo}
        <div class="av-log-card__identity">
          <div class="av-log-card__name">${player.name}</div>
          ${injuryHint}
        </div>
      </div>
      <div class="av-log-card__pills">${pills}</div>
      <button type="button" class="av-btn av-btn--ghost av-log-card__injury-btn av-injury-btn" data-player-id="${player.id}">Edit injury record</button>
    </article>
  `;
}

function bindQuickLogEvents() {
  els.logPlayers.querySelectorAll("[data-status]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const playerId = btn.dataset.playerId;
      const status = btn.dataset.status;
      const previousStatus = state.logEntries[playerId]?.status || "AVAIL";

      if (INJURY_TRIGGER_STATUSES.has(status)) {
        state.injuryPending = {
          playerId,
          previousStatus,
          source: "log",
        };
        state.logEntries[playerId] = { status: "INJ" };
        renderQuickLog();
        openInjuryDialog(playerId, { fromStatus: true });
        return;
      }

      if (status === "MM") {
        try {
          await setStandingPlayerStatus(playerId, "MM");
          state.logEntries[playerId] = { status: "MM" };
          setStatus("Managed minutes set for this player.", "ok");
          await loadBoard({ quiet: true });
          renderQuickLog();
        } catch (error) {
          setStatus(error.message, "error");
        }
        return;
      }

      if (playerById(playerId)?.injury?.status === "MM" && status === "AVAIL") {
        try {
          await clearStandingPlayerStatus(playerId);
          state.logEntries[playerId] = { status: "AVAIL" };
          await loadBoard({ quiet: true });
          renderQuickLog();
        } catch (error) {
          setStatus(error.message, "error");
        }
        return;
      }

      state.logEntries[playerId] = { status };
      renderQuickLog();
    });
  });

  els.logPlayers.querySelectorAll(".av-injury-btn").forEach((btn) => {
    btn.addEventListener("click", () => openInjuryDialog(btn.dataset.playerId, { manual: true }));
  });
}

function renderQuickLog() {
  if (!state.board?.roster?.length) {
    els.logPlayers.innerHTML = `<p style="color:var(--text-muted)">Sync or add players in the Roster tab first.</p>`;
    return;
  }

  if (!Object.keys(state.logEntries).length) {
    state.logEntries = defaultLogEntries();
  }

  updateLogHeader();

  els.logPlayers.innerHTML = playersByGroup({ squadOnly: true })
    .map((group) => `
      <section class="av-log-group">
        <h3 class="av-log-group__title">${group.label}</h3>
        <div class="av-log-grid">
          ${group.players.map((player) => renderLogPlayerCard(player)).join("")}
        </div>
      </section>
    `)
    .join("") + renderInjuredAwayNote();

  bindQuickLogEvents();
}

function injurySummaryForPlayer(player) {
  const episodes = Array.isArray(player.injury_history) ? player.injury_history : [];
  const active = episodes.find((ep) => ep.active)
    || (player.injury?.status && player.injury.status !== "AVAIL" ? { ...player.injury, active: true } : null);
  const totalDays = player.total_days_injured ?? episodes.reduce((sum, ep) => sum + (ep.days_out || 0), 0);
  return { episodes, active, totalDays };
}

function renderInjuryLog() {
  if (!els.logInjuryPlayers) return;
  const players = rosterPlayers({ activeOnly: true });
  if (!players.length) {
    els.logInjuryPlayers.innerHTML = `<p style="color:var(--text-muted)">Sync squad first.</p>`;
    return;
  }

  els.logInjuryPlayers.innerHTML = playersByGroup({ activeOnly: true })
    .map((group) => `
      <section class="av-log-group">
        <h3 class="av-log-group__title">${escapeHtml(group.label)}</h3>
        <div class="av-log-group__grid">
          ${group.players.map((player) => {
            const { active } = injurySummaryForPlayer(player);
            return `
              <article class="av-injury-log-card ${active ? "av-injury-log-card--active" : ""}">
                <div class="av-injury-log-card__head">
                  ${playerPhoto(player)}
                  <div>
                    <strong>${escapeHtml(player.name)}</strong>
                    <span class="av-muted">${escapeHtml(positionLabel(player.position_group))}</span>
                  </div>
                </div>
                ${active
                  ? `<p class="av-injury-log-card__status">Currently ${escapeHtml(active.status || "INJ")}${active.away_from_club ? " (away from club)" : ""} since ${formatDateLabel(active.since)}</p>`
                  : `<p class="av-injury-log-card__status av-muted">No active injury logged</p>`}
                <button type="button" class="av-btn av-btn--secondary av-injury-log-btn" data-player-id="${escapeHtml(player.id)}">
                  ${active ? "Update injury" : "Log injury"}
                </button>
              </article>
            `;
          }).join("")}
        </div>
      </section>
    `)
    .join("");

  els.logInjuryPlayers.querySelectorAll(".av-injury-log-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      openInjuryDialog(btn.dataset.playerId, { manual: true, longTerm: true });
    });
  });
}

function renderInjuriesList() {
  if (!els.injuriesList) return;
  const players = rosterPlayers({ activeOnly: false });

  if (!players.length) {
    els.injuriesList.innerHTML = `<p class="av-empty">Sync squad first to see injury history.</p>`;
    return;
  }

  els.injuriesList.innerHTML = `<div class="av-injury-board-grid">${players
    .sort((a, b) => {
      const aActive = injurySummaryForPlayer(a).active ? 1 : 0;
      const bActive = injurySummaryForPlayer(b).active ? 1 : 0;
      if (aActive !== bActive) return bActive - aActive;
      return a.name.localeCompare(b.name);
    })
    .map((player) => {
      const { episodes, active, totalDays } = injurySummaryForPlayer(player);
      const missedMatches = episodes.reduce((sum, ep) => sum + (ep.missed_matches || 0), 0);
      return `
        <article class="av-injury-board-card ${active ? "av-injury-board-card--active" : ""}" data-player-id="${escapeHtml(player.id)}">
          <div class="av-injury-board-card__photo">${playerPhoto(player)}</div>
          <div class="av-injury-board-card__body">
            <h3>${escapeHtml(player.name)}</h3>
            <p class="av-muted">${escapeHtml(positionLabel(player.position_group))}</p>
            ${active
              ? `<span class="av-tag av-tag--inj">Out · ${escapeHtml(active.status || "INJ")}${active.away_from_club ? " · Away" : ""}</span>`
              : episodes.length
                ? `<span class="av-tag av-tag--ok">Fit</span>`
                : `<span class="av-tag av-tag--muted">No injuries logged</span>`}
            <dl class="av-injury-board-card__stats">
              <div><dt>Injuries</dt><dd>${episodes.length}</dd></div>
              <div><dt>Days out</dt><dd>${totalDays}</dd></div>
              <div><dt>Matches missed</dt><dd>${missedMatches}</dd></div>
            </dl>
          </div>
        </article>
      `;
    })
    .join("")}</div>`;

  els.injuriesList.querySelectorAll(".av-injury-board-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.injuryDetailPlayerId = card.dataset.playerId;
      renderInjuryDetail(state.injuryDetailPlayerId);
    });
  });
}

function renderInjuryDetail(playerId) {
  const player = rosterPlayers({ activeOnly: false }).find((p) => p.id === playerId);
  if (!player || !els.injuryDetailPanel) return;

  els.injuriesListWrap?.classList.add("hidden");
  els.injuryDetailPanel.classList.remove("hidden");

  const { episodes } = injurySummaryForPlayer(player);
  const sorted = [...episodes].sort((a, b) => (b.since || "").localeCompare(a.since || ""));

  els.injuryDetailHead.innerHTML = `
    <div class="av-injury-detail__player">
      ${playerPhoto(player, "av-injury-detail__photo")}
      <div>
        <h2>${escapeHtml(player.name)}</h2>
        <p class="av-muted">${escapeHtml(positionLabel(player.position_group))} · ${episodes.length} injur${episodes.length === 1 ? "y" : "ies"}</p>
      </div>
    </div>
    <button type="button" class="av-btn av-btn--secondary" id="injuryDetailLogBtn" data-player-id="${escapeHtml(player.id)}">Log injury</button>
  `;

  if (!sorted.length) {
    els.injuryDetailBody.innerHTML = `<p class="av-empty">No recorded injuries for this player.</p>`;
  } else {
    els.injuryDetailBody.innerHTML = sorted
      .map((ep) => {
        const active = ep.active || !ep.ended_at;
        const missed = ep.missed_items || [];
        const missedHtml = missed.length
          ? `<ul class="av-injury-missed">${missed.map((item) => `<li>${escapeHtml(typeof item === "string" ? item : (item.label || item.date || ""))}</li>`).join("")}</ul>`
          : `<p class="av-muted">No sessions missed in this period.</p>`;
        return `
          <article class="av-injury-episode ${active ? "av-injury-episode--active" : ""}">
            <header class="av-injury-episode__head">
              <div>
                <strong>${escapeHtml(ep.status || "INJ")}</strong>
                <span class="av-muted">Since ${formatDateLabel(ep.since)}</span>
              </div>
              <span class="av-tag ${active ? "av-tag--inj" : "av-tag--ok"}">${active ? "Active" : "Returned"}</span>
            </header>
            <dl class="av-injury-episode__meta">
              <div><dt>Days out</dt><dd>${ep.days_out ?? "—"}</dd></div>
              <div><dt>Expected return</dt><dd>${ep.return_date ? formatDateLabel(ep.return_date) : "TBC"}</dd></div>
              <div><dt>Ended</dt><dd>${ep.ended_at ? formatDateLabel(ep.ended_at) : "—"}</dd></div>
              <div><dt>Matches missed</dt><dd>${ep.missed_matches ?? 0}</dd></div>
            </dl>
            ${ep.notes ? `<p class="av-injury-episode__notes">${escapeHtml(ep.notes)}</p>` : ""}
            <div class="av-injury-episode__missed">
              <h4>What they missed</h4>
              ${missedHtml}
            </div>
            ${active ? `<button type="button" class="av-btn av-btn--ghost av-mark-fit-btn" data-player-id="${escapeHtml(player.id)}">Mark fit</button>` : ""}
          </article>
        `;
      })
      .join("");
  }

  document.getElementById("injuryDetailLogBtn")?.addEventListener("click", () => {
    openInjuryDialog(playerId, { manual: true, longTerm: true });
  });

  els.injuryDetailBody.querySelectorAll(".av-mark-fit-btn").forEach((btn) => {
    btn.addEventListener("click", () => clearInjury(btn.dataset.playerId));
  });
}

function renderInjuriesView() {
  if (!els.injuriesView) return;
  if (state.injuryDetailPlayerId) {
    renderInjuryDetail(state.injuryDetailPlayerId);
  } else {
    els.injuryDetailPanel?.classList.add("hidden");
    els.injuriesListWrap?.classList.remove("hidden");
    renderInjuriesList();
  }
}

function pctLabel(pct, available, total) {
  if (pct == null || !total) return "—";
  return `${pct}%`;
}

function signedStat(value) {
  const num = Number(value) || 0;
  if (Number.isInteger(num)) {
    if (num > 0) return `+${num}`;
    return String(num);
  }
  const rounded = Math.round(num * 10) / 10;
  if (rounded > 0) return `+${rounded}`;
  return String(rounded);
}

function plusMinusClass(value) {
  const num = Number(value) || 0;
  if (num > 0) return "av-roster-card__stat--pos";
  if (num < 0) return "av-roster-card__stat--neg";
  return "";
}

function renderRosterStat(label, value, title = "", extraClass = "") {
  return `
    <div class="av-roster-card__stat ${extraClass}" ${title ? `title="${title}"` : ""}>
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `;
}

function rosterStatusBadge(player) {
  if (player.active === false) {
    return `<span class="av-roster-card__badge av-roster-card__badge--left">Not at club</span>`;
  }
  const injury = player.injury;
  if (injury?.status && injury.status !== "AVAIL") {
    const away = Boolean(injury.away_from_club);
    const detail = [
      away ? "Injured away" : statusLabel(injury.status),
      injury.return_date ? `back ${injury.return_date}` : "",
    ].filter(Boolean).join(" · ");
    return `<span class="av-roster-card__badge av-roster-card__badge--${away ? "away" : injury.status}" title="${injury.notes || ""}">${detail}</span>`;
  }
  return `<span class="av-roster-card__badge av-roster-card__badge--fit">Fit</span>`;
}

function formatNum(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const num = Number(value);
  if (Number.isInteger(num)) return String(num);
  return num.toFixed(digits);
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${formatNum(value, 1)}%`;
}

function renderRosterPlayerCard(player) {
  const photo = player.photo_url
    ? `<img class="av-roster-card__photo" src="${player.photo_url}" alt="" loading="lazy" />`
    : `<div class="av-roster-card__photo"></div>`;
  const avail = player.availability || {};
  const impact = player.impact || {};
  const highlightClass = player.highlight ? ` av-roster-card--${player.highlight}` : "";
  const inactiveClass = player.active === false ? " av-roster-card--inactive" : "";
  const injuryClass = player.injury?.status && player.injury.status !== "AVAIL"
    ? ` av-roster-card--${player.injury.status}`
    : "";

  return `
    <article class="av-roster-card${highlightClass}${inactiveClass}${injuryClass}" data-player-id="${player.id}">
      <div class="av-roster-card__head">
        ${photo}
        <div class="av-roster-card__identity">
          <div class="av-roster-card__name">${player.name}</div>
          <div class="av-roster-card__meta">${player.bracket || "Squad"} · ${positionLabel(player.position_group)}</div>
        </div>
        ${rosterStatusBadge(player)}
      </div>

      <div class="av-roster-card__section">
        <div class="av-roster-card__section-title">Minutes played</div>
        <div class="av-roster-card__stats av-roster-card__stats--5">
          ${renderRosterStat("Total mins", impact.minutes ?? 0, "Total minutes played (league + cup)")}
          ${renderRosterStat("% of mins", formatPct(impact.pct_of_l1_mins), "Share of all possible minutes across completed fixtures (team × 90)")}
          ${renderRosterStat("/Game played", formatNum(impact.mins_per_game_played), "Average minutes per appearance")}
          ${renderRosterStat("/Available", formatNum(impact.mins_per_available), "Average minutes across games marked available")}
          ${renderRosterStat("/Possible", formatNum(impact.mins_per_possible), "Average minutes across all completed fixtures")}
        </div>
      </div>

      <div class="av-roster-card__section">
        <div class="av-roster-card__section-title">Points earned</div>
        <div class="av-roster-card__stats av-roster-card__stats--3">
          ${renderRosterStat("Played", impact.appearances ?? 0, "Appearances (league + cup)")}
          ${renderRosterStat("Points", impact.points ?? 0, "Team points from league matches this player appeared in")}
          ${renderRosterStat("PPG", formatNum(impact.ppg), "Points per league appearance")}
        </div>
      </div>

      <div class="av-roster-card__section">
        <div class="av-roster-card__section-title">Mins &amp; points</div>
        <div class="av-roster-card__stats av-roster-card__stats--4">
          ${renderRosterStat("Mins in wins", impact.mins_in_wins ?? 0)}
          ${renderRosterStat("% of wins", formatPct(impact.pct_of_wins), "Share of team wins this player appeared in")}
          ${renderRosterStat("Mins in points", impact.mins_in_points ?? 0, "Minutes in wins and draws")}
          ${renderRosterStat("% of points", formatPct(impact.pct_of_points), "Share of team points from matches this player appeared in")}
        </div>
      </div>

      <div class="av-roster-card__section">
        <div class="av-roster-card__section-title">Availability</div>
        <div class="av-roster-card__stats av-roster-card__stats--3">
          ${renderRosterStat("Avail", pctLabel(avail.games_available_pct, avail.games_available, avail.games_available_total), `${avail.games_available ?? 0}/${avail.games_available_total ?? 0} games available`)}
          ${renderRosterStat("Gms", pctLabel(avail.games_played_when_fit_pct, avail.games_played_when_fit, avail.games_fit_total), `${avail.games_played_when_fit ?? 0}/${avail.games_fit_total ?? 0} played when fit`)}
          ${renderRosterStat("Days inj", player.days_injured != null ? player.days_injured : "—")}
        </div>
      </div>

      <div class="av-roster-card__actions">
        <button type="button" class="av-btn av-btn--ghost av-edit-player-btn" data-player-id="${player.id}">Edit</button>
        <button type="button" class="av-btn av-btn--ghost av-injury-roster-btn" data-player-id="${player.id}">Injury</button>
        <button type="button" class="av-btn av-btn--danger av-delete-player-btn" data-player-id="${player.id}">Remove</button>
      </div>
    </article>
  `;
}

function renderRoster() {
  if (state.loading && !state.board?.roster?.length) {
    els.rosterList.innerHTML = `<p style="color:var(--text-muted)">Loading saved squad…</p>`;
    els.purgeInactiveBtn?.classList.add("hidden");
    return;
  }
  if (!state.board?.roster?.length) {
    els.rosterList.innerHTML = `<p style="color:var(--text-muted)">No players yet. Sync squad or add players manually.</p>`;
    els.purgeInactiveBtn?.classList.add("hidden");
    return;
  }

  const inactiveCount = rosterPlayers().filter((player) => player.active === false).length;
  els.purgeInactiveBtn?.classList.toggle("hidden", inactiveCount === 0);

  const activeGroups = playersByGroup({ activeOnly: true });
  const inactivePlayers = rosterPlayers().filter((player) => player.active === false);

  els.rosterList.innerHTML = `
    <div class="av-roster-cards">
      ${activeGroups.map((group) => `
        <section class="av-roster-group">
          <h3 class="av-roster-group__title">${group.label}</h3>
          <div class="av-roster-grid">
            ${group.players.map((player) => renderRosterPlayerCard(player)).join("")}
          </div>
        </section>
      `).join("")}
      ${inactivePlayers.length ? `
        <section class="av-roster-group">
          <h3 class="av-roster-group__title">Not at club / departed</h3>
          <div class="av-roster-grid">
            ${inactivePlayers.map((player) => renderRosterPlayerCard(player)).join("")}
          </div>
        </section>
      ` : ""}
    </div>
    <p class="av-roster-footnote">26/27 squad + headshots from port-vale.co.uk. Use Remove on anyone who has left.</p>
  `;

  els.rosterList.querySelectorAll(".av-edit-player-btn").forEach((btn) => {
    btn.addEventListener("click", () => openPlayerDialog(btn.dataset.playerId));
  });
  els.rosterList.querySelectorAll(".av-injury-roster-btn").forEach((btn) => {
    btn.addEventListener("click", () => openInjuryDialog(btn.dataset.playerId, { manual: true }));
  });
  els.rosterList.querySelectorAll(".av-delete-player-btn").forEach((btn) => {
    btn.addEventListener("click", () => deletePlayerById(btn.dataset.playerId));
  });
}

function standingStatus(player) {
  const status = String(player?.injury?.status || "AVAIL").toUpperCase();
  if (!status || status === "AVAIL") return "AVAIL";
  return status;
}

function playerLastName(name) {
  const parts = String(name || "").trim().split(/\s+/);
  return parts[parts.length - 1] || name || "";
}

function formatReturnShort(iso) {
  if (!iso) return "";
  const date = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function nextUpcomingMatch() {
  return upcomingMatches()[0] || null;
}

function lastCompletedMatch() {
  const done = (state.board?.sessions || []).filter((session) => session.type === "match" && session.complete);
  return done[done.length - 1] || null;
}

function summaryBuckets() {
  const players = rosterPlayers({ activeOnly: true });
  const buckets = {
    available: [],
    injured: [],
    mm: [],
    other: [],
    away: [],
  };
  for (const player of players) {
    if (isInjuredAway(player)) {
      buckets.away.push(player);
      continue;
    }
    const status = standingStatus(player);
    if (status === "INJ") buckets.injured.push(player);
    else if (status === "MM") buckets.mm.push(player);
    else if (["UN", "LOAN", "INT"].includes(status)) buckets.other.push(player);
    else buckets.available.push(player);
  }
  return buckets;
}

function summaryStatusTag(player) {
  if (isInjuredAway(player)) return { code: "AWAY", label: "Away" };
  const status = standingStatus(player);
  if (status === "AVAIL") return { code: "FIT", label: "Fit" };
  if (status === "INJ") {
    const back = player.injury?.return_date ? ` · ${formatReturnShort(player.injury.return_date)}` : "";
    return { code: "INJ", label: `INJ${back}` };
  }
  if (status === "MM") return { code: "MM", label: "MM" };
  return { code: status, label: status };
}

function playerWasAvailableOn(player, sessionDate) {
  const blockers = [];
  if (Array.isArray(player.injury_history)) blockers.push(...player.injury_history);
  if (player.injury?.status && player.injury.status !== "AVAIL") blockers.push(player.injury);
  for (const rec of blockers) {
    const status = String(rec.status || "").toUpperCase();
    if (!["INJ", "UN", "LOAN", "INT"].includes(status)) continue;
    const since = String(rec.since || "").slice(0, 10);
    const ended = String(rec.ended_at || "").slice(0, 10);
    if (since && sessionDate < since) continue;
    if (ended && sessionDate > ended) continue;
    if (!ended && rec.active === false) continue;
    return false;
  }
  return true;
}

function summaryDaysInjured(player) {
  if (player.days_injured != null) return player.days_injured;
  if (player.total_days_injured != null) return player.total_days_injured;
  return 0;
}

function summaryMinuteShares(player) {
  const completedSessions = (state.board?.sessions || []).filter(
    (session) => session.type === "match" && session.complete
  );
  const possible = completedSessions.length * 90;
  const played = Number(player.impact?.minutes || 0);
  const availableGames = completedSessions.filter((session) => (
    playerWasAvailableOn(player, String(session.date || "").slice(0, 10))
  )).length;
  const availableMins = availableGames * 90;
  const unused = Math.max(0, availableMins - played);
  const pct = (value) => (possible > 0 ? (100 * value) / possible : null);
  return {
    played,
    unused,
    playedPct: pct(played),
    availablePct: pct(availableMins),
    unusedPct: pct(unused),
  };
}

function pctHeatColor(pct, invert) {
  if (pct == null) return { bar: "transparent", text: "var(--text-muted)" };
  const t = Math.max(0, Math.min(100, Number(pct))) / 100;
  const v = invert ? 1 - t : t;
  const hue = Math.round(v * 128);
  return {
    bar: `hsla(${hue}, 82%, 40%, .78)`,
    text: `hsl(${hue}, 72%, 78%)`,
  };
}

function renderSummaryBar(pct, variant, title) {
  const width = pct == null ? 0 : Math.max(0, Math.min(100, Number(pct)));
  const heat = pctHeatColor(pct, variant === "unused");
  return `
    <div class="av-slide-avail av-slide-avail--${variant}" title="${escapeHtml(title)}">
      <span class="av-slide-avail__bar" style="width:${width}%;background:${heat.bar}"></span>
      <strong style="color:${heat.text}">${formatPct(pct)}</strong>
    </div>
  `;
}

function renderSummaryRow(player) {
  const impact = player.impact || {};
  const shares = summaryMinuteShares(player);
  const tag = summaryStatusTag(player);
  return `
    <tr class="av-slide-row av-slide-row--${tag.code}">
      <td class="av-slide-player">
        ${playerPhoto(player, "av-slide-chip__photo")}
        <span>${escapeHtml(playerLastName(player.name))}</span>
      </td>
      <td>${shares.played}</td>
      <td>${impact.appearances ?? 0}</td>
      <td>${renderSummaryBar(shares.playedPct, "played", `Played ${shares.played} of possible minutes`)}</td>
      <td>${renderSummaryBar(shares.availablePct, "available", "Share of possible minutes they were available to play")}</td>
      <td>${renderSummaryBar(shares.unusedPct, "unused", `${shares.unused} minutes available but not involved`)}</td>
      <td>${summaryDaysInjured(player) || "—"}</td>
      <td><span class="av-slide-tag av-slide-tag--${tag.code}">${escapeHtml(tag.label)}</span></td>
    </tr>
  `;
}

function renderSummary() {
  if (!els.summarySlide) return;
  const buckets = summaryBuckets();
  const next = nextUpcomingMatch();
  const last = lastCompletedMatch();
  const today = formatDateLabel(todayIso(), { isToday: true });
  const nextLine = next
    ? `Next · ${next.date} ${next.label || ""}`
    : "No upcoming fixture";
  const lastLine = last
    ? `Last · ${last.label || last.date}${last.score ? ` ${last.result || ""} ${last.score}` : ""}`
    : "";
  const completed = state.board?.competition?.complete_matches || 0;
  const possible = state.board?.competition?.possible_mins || completed * 90;
  const groups = playersByGroup({ activeOnly: true }).map((group) => ({
    ...group,
    players: [...group.players].sort((a, b) => (b.impact?.minutes || 0) - (a.impact?.minutes || 0)),
  }));
  const outBits = [...buckets.injured, ...buckets.mm, ...buckets.other, ...buckets.away]
    .map((player) => {
      const tag = summaryStatusTag(player);
      return `${playerLastName(player.name)} ${tag.label}`;
    });
  const awayNote = buckets.away.length
    ? buckets.away.map((player) => player.name).join(", ") +
      (buckets.away.length === 1
        ? " is injured away from the club — personal record only."
        : " are injured away from the club — personal record only.")
    : "";

  els.summarySlide.innerHTML = `
    <header class="av-slide__head">
      <div>
        <p class="av-slide__kicker">Port Vale · ${escapeHtml(state.season)}</p>
        <h2>Minutes &amp; availability</h2>
      </div>
      <div class="av-slide__meta">
        <p>${escapeHtml(today)}</p>
        <p>${escapeHtml(nextLine)}</p>
        ${lastLine ? `<p>${escapeHtml(lastLine)}</p>` : ""}
      </div>
    </header>
    <div class="av-slide__stats">
      <div><strong>${completed}</strong><span>Completed</span></div>
      <div><strong>${possible}</strong><span>Possible mins</span></div>
      <div class="av-slide__stat--out"><strong>${buckets.injured.length}</strong><span>Injured</span></div>
      <div class="av-slide__stat--mm"><strong>${buckets.mm.length}</strong><span>Managed mins</span></div>
    </div>
    <div class="av-slide-table-wrap">
      <table class="av-slide-table">
        <thead>
          <tr>
            <th>Player</th>
            <th>Mins</th>
            <th>Apps</th>
            <th title="Minutes played ÷ possible minutes">Played</th>
            <th title="Minutes they were available ÷ possible minutes">Available</th>
            <th title="Available minutes they did not play">Unused</th>
            <th title="Days out in the current / logged injury spell">Days inj</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${groups.map((group) => `
            <tr class="av-slide-group-row"><td colspan="8">${escapeHtml(group.label)}</td></tr>
            ${group.players.map((player) => renderSummaryRow(player)).join("")}
          `).join("")}
        </tbody>
      </table>
    </div>
    ${outBits.length ? `<p class="av-slide__out">Out now · ${escapeHtml(outBits.join("  ·  "))}</p>` : ""}
    ${awayNote ? `<p class="av-slide__away">${escapeHtml(awayNote)}</p>` : ""}
  `;
}

function setPresentMode(on) {
  document.body.classList.toggle("av-present", Boolean(on));
  if (on && state.view !== "summary") {
    state.view = "summary";
    renderView();
  }
}

function renderView() {
  document.querySelectorAll(".av-tab").forEach((tab) => {
    tab.classList.toggle("av-tab--active", tab.dataset.view === state.view);
  });
  els.matrixView.classList.toggle("hidden", state.view !== "matrix");
  els.logView.classList.toggle("hidden", state.view !== "log");
  els.rosterView.classList.toggle("hidden", state.view !== "roster");
  els.injuriesView?.classList.toggle("hidden", state.view !== "injuries");
  els.summaryView?.classList.toggle("hidden", state.view !== "summary");

  if (state.view === "matrix") renderMatrix();
  if (state.view === "summary") renderSummary();
  if (state.view === "log") {
    if (state.loggingActive) {
      showLogPanels({ session: true, injury: false });
    } else if (state.injuryLoggingActive) {
      showLogPanels({ session: false, injury: true });
    } else {
      showLogPanels({ session: false, injury: false });
    }
    updateLogLanding();
  }
  if (state.view === "roster") renderRoster();
  if (state.view === "injuries") renderInjuriesView();
}

function populateSelects() {
  const injuryOptions = ["INJ", "MM", "UN", "LOAN", "INT"].map((code) => `<option value="${code}">${statusLabel(code)}</option>`).join("");
  els.injuryStatus.innerHTML = injuryOptions;

  const positionOptions = (state.meta?.position_groups || [])
    .map((group) => `<option value="${group.id}">${group.label}</option>`)
    .join("");
  els.playerPosition.innerHTML = positionOptions;
}

function openInjuryDialog(playerId, options = {}) {
  const player = playerById(playerId);
  if (!player) return;

  const fromStatus = Boolean(options.fromStatus);
  els.injuryPlayerId.value = playerId;
  els.injuryDialogTitle.textContent = `Record injury — ${player.name}`;
  els.injuryDialogIntro.textContent = fromStatus
    ? "Add expected return and comments to track this injury."
    : "Record when the injury started and when they’re expected back.";
  els.injuryStatusWrap.classList.toggle("hidden", fromStatus);
  els.injuryStatus.value = player.injury?.status || "INJ";
  populateInjurySinceDropdown(player.injury?.since || todayIso());
  populateReturnDateDropdown(player.injury?.return_date || "");
  els.injuryNotes.value = player.injury?.notes || "";
  if (els.injuryAwayFromClub) {
    els.injuryAwayFromClub.checked = Boolean(player.injury?.away_from_club);
  }
  const hasActiveInjury = Boolean(player.injury?.status && player.injury.status !== "AVAIL");
  els.clearInjuryBtn.classList.toggle("hidden", fromStatus || !hasActiveInjury);
  els.injuryDialog.showModal();
}

function cancelInjuryDialog() {
  const pending = state.injuryPending;
  if (pending) {
    if (pending.source === "log") {
      state.logEntries[pending.playerId] = { status: pending.previousStatus || "AVAIL" };
      renderQuickLog();
    }
    state.injuryPending = null;
  }
  els.injuryDialog.close();
}

function openPlayerDialog(playerId = "") {
  const player = playerId ? playerById(playerId) : null;
  els.playerEditId.value = playerId || "";
  els.playerDialogTitle.textContent = player ? `Edit ${player.name}` : "Add player";
  els.playerName.value = player?.name || "";
  els.playerPosition.value = player?.position_group || "MID";
  els.playerHighlight.value = player?.highlight || "";
  els.deletePlayerBtn.classList.toggle("hidden", !playerId);
  els.playerDialog.showModal();
}

async function loadMeta() {
  state.meta = await fetchJson("/api/availability/meta");
  if (!state.meta.seasons?.some((row) => row.season === state.season)) {
    state.season = state.meta.default_season || DEFAULT_SEASON;
  }
  populateSelects();
  renderSeasonToggle();
}

async function loadBoard({ quiet = false, refresh = false } = {}) {
  if (!quiet) {
    state.loading = true;
    els.statusBar.textContent = "Loading availability board…";
  }
  try {
    state.board = await fetchJson(
      `/api/availability/board?season=${encodeURIComponent(state.season)}${refresh ? "&refresh=1" : ""}`
    );

    if (!state.board?.roster?.some((player) => player.active !== false)) {
      const imported = await tryImportRosterIfEmpty({ quiet: true });
      if (imported) {
        state.board = await fetchJson(
          `/api/availability/board?season=${encodeURIComponent(state.season)}${refresh ? "&refresh=1" : ""}`
        );
        if (!quiet) {
          const activeCount = rosterPlayers({ activeOnly: true }).length;
          setStatus(`Loaded ${activeCount} players for ${state.season}`, "ok");
        }
      }
    }

    if (state.loggingActive) {
      if (!Object.keys(state.logEntries).length) {
        state.logEntries = defaultLogEntries();
      }
    } else {
      state.logEntries = {};
    }
    const allCount = state.board.match_count || 0;
    const leagueCount = state.board.league_match_count ?? allCount;
    const completed = state.board.competition?.complete_matches || 0;
    const completedLeague = state.board.competition?.complete_league_matches;
    const completedLabel = completedLeague != null && completedLeague !== completed
      ? `${completed} completed (${completedLeague} league)`
      : `${completed} completed`;
    els.pageSubtitle.textContent = `${allCount} fixtures · ${leagueCount} league · ${completedLabel} · FotMob`;
    els.statusBar.textContent = `Updated ${state.board.updated_at ? new Date(state.board.updated_at).toLocaleString() : "just now"}`;
    if (!quiet) setStatus("");
    renderSeasonToggle();
    if (state.loggingActive) {
      populateMatchSessionDropdown();
    }
    renderView();
  } catch (error) {
    setStatus(error.message, "error");
    els.statusBar.textContent = "Failed to load board.";
  } finally {
    state.loading = false;
  }
}

async function saveSession() {
  const date = els.logDate.value || todayIso();
  const { kind, payload, session, matchId } = sessionSelectionMeta();

  try {
    const opponent = els.logOpponent.value.trim();
    const venue = els.logVenue.value || "H";
    const body = {
      date,
      entries: state.logEntries,
      apply_injuries: false,
    };

    if (kind === "league") {
      body.match_category = "league";
      body.session_id = payload;
      body.match_id = matchId;
      body.label = session?.label || payload;
    } else if (kind === "friendly") {
      body.match_category = "friendly";
      body.opponent = opponent;
      body.venue = venue;
      if (!opponent) {
        setStatus("Enter an opponent for the friendly.", "error");
        return;
      }
    } else if (kind === "cup") {
      body.match_category = "cup";
      body.opponent = opponent;
      body.venue = venue;
      if (!opponent) {
        setStatus("Enter an opponent for the cup game.", "error");
        return;
      }
    } else {
      setStatus("Pick a fixture first.", "error");
      return;
    }

    const saved = await fetchJson(`/api/availability/match?season=${encodeURIComponent(state.season)}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    setStatus(`Saved availability for ${saved.label || "fixture"}`, "ok");

    await loadBoard({ quiet: true });
    cancelLoggingSession();
    state.view = "log";
    renderView();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function syncPositionsFromImpect({ quiet = false } = {}) {
  try {
    const result = await fetchJson(
      `/api/availability/roster/sync-positions?season=${encodeURIComponent(state.season)}`,
      { method: "POST" }
    );
    if (result.updated > 0) {
      await loadBoard({ quiet: true, refresh: true });
      if (!quiet) {
        setStatus(`Updated positions for ${result.updated} players from Impect`, "ok");
      }
    }
    return result;
  } catch (error) {
    if (!quiet) setStatus(error.message, "error");
    return null;
  }
}

async function importRoster() {
  try {
    const result = await fetchJson(`/api/availability/roster/import?season=${encodeURIComponent(state.season)}`, {
      method: "POST",
    });
    const parts = [];
    if (result.added) parts.push(`${result.added} added`);
    if (result.updated) parts.push(`${result.updated} updated`);
    if (result.reactivated) parts.push(`${result.reactivated} back`);
    if (result.left_club) parts.push(`${result.left_club} marked not at club`);
    if (result.impect_linked) parts.push(`${result.impect_linked} linked to Impect`);
    const source = result.source === "port-vale.co.uk"
      ? "port-vale.co.uk"
      : (result.source_season && result.source_season !== state.season
        ? `${result.source_season} Impect`
        : "Impect");
    let message = `Synced squad from ${source} — ${parts.join(", ") || "no changes"} (${result.total} active)`;
    if (result.warning) message += ` · ${result.warning}`;
    setStatus(message, result.warning ? "warn" : "ok");
    await loadBoard({ quiet: true, refresh: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function saveInjury(event) {
  event.preventDefault();
  const playerId = els.injuryPlayerId.value;
  const pending = state.injuryPending;
  const fromQuickLog = els.injuryStatusWrap.classList.contains("hidden");
  const status = fromQuickLog ? "INJ" : (els.injuryStatus.value || "INJ");
  const awayFromClub = Boolean(els.injuryAwayFromClub?.checked) && status === "INJ";
  try {
    await fetchJson(`/api/availability/injury/${encodeURIComponent(playerId)}?season=${encodeURIComponent(state.season)}`, {
      method: "PUT",
      body: JSON.stringify({
        status,
        since: els.injurySince?.value || todayIso(),
        return_date: els.injuryReturnDate.value || null,
        notes: els.injuryNotes.value || "",
        away_from_club: awayFromClub,
      }),
    });

    if (pending?.source === "matrix" && pending.sessionId && !awayFromClub) {
      await applySessionStatus(playerId, pending.sessionId, status);
    } else if ((pending?.source === "log" || state.logEntries[playerId]) && !awayFromClub) {
      state.logEntries[playerId] = { status };
    } else if (awayFromClub) {
      delete state.logEntries[playerId];
    }

    state.injuryPending = null;
    els.injuryDialog.close();
    setStatus(awayFromClub ? "Injured away from club saved." : "Injury saved.", "ok");
    await loadBoard({ quiet: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function clearInjury(playerId = "") {
  const targetId = playerId || els.injuryPlayerId.value;
  if (!targetId) return;
  try {
    await fetchJson(`/api/availability/injury/${encodeURIComponent(targetId)}?season=${encodeURIComponent(state.season)}`, {
      method: "DELETE",
    });
    state.injuryPending = null;
    els.injuryDialog.close();
    setStatus("Player marked fit.", "ok");
    await loadBoard({ quiet: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function savePlayer(event) {
  event.preventDefault();
  const playerId = els.playerEditId.value;
  const payload = {
    name: els.playerName.value.trim(),
    position_group: els.playerPosition.value,
    highlight: els.playerHighlight.value || null,
  };
  try {
    if (playerId) {
      await fetchJson(`/api/availability/roster/${encodeURIComponent(playerId)}?season=${encodeURIComponent(state.season)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    } else {
      await fetchJson(`/api/availability/roster?season=${encodeURIComponent(state.season)}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    els.playerDialog.close();
    await loadBoard({ quiet: true, refresh: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function deletePlayerById(playerId) {
  if (!playerId || !window.confirm("Remove this player from the roster?")) return;
  try {
    await fetchJson(`/api/availability/roster/${encodeURIComponent(playerId)}?season=${encodeURIComponent(state.season)}`, {
      method: "DELETE",
    });
    els.playerDialog?.close();
    setStatus("Player removed.", "ok");
    await loadBoard({ quiet: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function deletePlayer() {
  await deletePlayerById(els.playerEditId.value);
}

async function purgeInactivePlayers() {
  const inactiveCount = rosterPlayers().filter((player) => player.active === false).length;
  if (!inactiveCount) return;
  if (!window.confirm(`Permanently remove ${inactiveCount} departed player${inactiveCount === 1 ? "" : "s"}?`)) return;
  try {
    const result = await fetchJson(`/api/availability/roster/inactive?season=${encodeURIComponent(state.season)}`, {
      method: "DELETE",
    });
    setStatus(`Removed ${result.removed} departed player${result.removed === 1 ? "" : "s"}.`, "ok");
    await loadBoard({ quiet: true });
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function bindEvents() {
  document.querySelectorAll(".av-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.view = tab.dataset.view;
      if (tab.dataset.view === "log") {
        state.loggingActive = false;
        state.injuryLoggingActive = false;
      }
      if (tab.dataset.view !== "injuries") {
        state.injuryDetailPlayerId = "";
      }
      if (tab.dataset.view !== "summary") {
        setPresentMode(false);
      }
      renderView();
    });
  });

  els.refreshBtn.addEventListener("click", () => loadBoard({ refresh: true }));
  els.presentSummaryBtn?.addEventListener("click", () => setPresentMode(true));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setPresentMode(false);
  });
  els.submitMatchBtn.addEventListener("click", startGameLog);
  els.submitInjuryBtn?.addEventListener("click", startInjuryLog);
  els.syncRosterLandingBtn?.addEventListener("click", importRoster);
  els.purgeInactiveBtn?.addEventListener("click", purgeInactivePlayers);
  document.querySelectorAll("[data-matrix-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.matrixFilter = btn.dataset.matrixFilter || "all";
      document.querySelectorAll("[data-matrix-filter]").forEach((other) => {
        other.classList.toggle("av-matrix-filter__btn--active", other === btn);
      });
      renderMatrix();
    });
  });
  els.importRosterBtn.addEventListener("click", importRoster);
  els.saveSessionBtn.addEventListener("click", saveSession);
  els.cancelSessionBtn.addEventListener("click", cancelLoggingSession);
  els.cancelInjuryLogBtn?.addEventListener("click", cancelInjuryLog);
  els.injuryDetailBackBtn?.addEventListener("click", () => {
    state.injuryDetailPlayerId = "";
    renderInjuriesView();
  });
  els.addPlayerBtn.addEventListener("click", () => openPlayerDialog());
  els.injuryForm.addEventListener("submit", saveInjury);
  els.clearInjuryBtn.addEventListener("click", () => clearInjury());
  els.cancelInjuryBtn.addEventListener("click", cancelInjuryDialog);
  els.injuryDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    cancelInjuryDialog();
  });
  els.logSession.addEventListener("change", () => onMatchSessionChange());
  document.querySelectorAll(".av-injury-week-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const weeks = Number(btn.dataset.weeks) || 1;
      populateReturnDateDropdown(addWeeksIso(weeks));
    });
  });
  els.playerForm.addEventListener("submit", savePlayer);
  els.deletePlayerBtn.addEventListener("click", deletePlayer);
}

async function init() {
  populateDateDropdown(todayIso());
  populateReturnDateDropdown();
  bindEvents();
  // Load the board immediately — roster lives on the hub disk and must not wait on Impect.
  const boardPromise = loadBoard();
  try {
    await loadMeta();
  } catch (error) {
    setStatus(error.message, "error");
  }
  try {
    await boardPromise;
  } catch (error) {
    setStatus(error.message, "error");
  }
}

init();
