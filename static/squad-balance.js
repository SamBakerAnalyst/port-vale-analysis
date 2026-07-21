const STORAGE_KEY = "squad-balance:v1";
const MAX_PLAYERS_PER_POSITION = 5;
const SEARCH_MIN_CHARS = 3;
const SEARCH_DEBOUNCE_MS = 300;

const PLAYER_COLORS = [
  { main: "#4a90d9", bg: "rgba(74, 144, 217, 0.18)" },
  { main: "#e573a8", bg: "rgba(229, 115, 168, 0.18)" },
  { main: "#4db6ac", bg: "rgba(77, 182, 172, 0.18)" },
  { main: "#f5c518", bg: "rgba(245, 197, 24, 0.18)" },
  { main: "#a78bfa", bg: "rgba(167, 139, 250, 0.18)" },
];

const state = {
  meta: null,
  squad: {},
  activePosition: null,
  selectedSearchPlayer: null,
  searchResults: [],
  loading: false,
  pasteTarget: null,
};

const els = {
  playerSearch: document.getElementById("playerSearch"),
  searchResults: document.getElementById("searchResults"),
  targetPosition: document.getElementById("targetPosition"),
  addPlayerBtn: document.getElementById("addPlayerBtn"),
  statusBanner: document.getElementById("statusBanner"),
  positionNav: document.getElementById("positionNav"),
  comparisonDeck: document.getElementById("comparisonDeck"),
  clearBtn: document.getElementById("clearBtn"),
  exportPdfBtn: document.getElementById("exportPdfBtn"),
  saveBtn: document.getElementById("saveBtn"),
};

let searchTimer = null;
let lastSearchQuery = "";

function playerInitials(name) {
  return String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `status-banner status-banner--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function positionMeta(positionId) {
  return state.meta?.positions?.find((item) => item.id === positionId) || null;
}

function playersForPosition(positionId) {
  return state.squad[positionId] || [];
}

function initSquadFromMeta() {
  state.squad = {};
  (state.meta?.positions || []).forEach((position) => {
    state.squad[position.id] = [];
  });
}

function loadSquadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (!saved?.squad || typeof saved.squad !== "object") return;
    Object.keys(state.squad).forEach((positionId) => {
      const players = saved.squad[positionId];
      if (Array.isArray(players)) {
        state.squad[positionId] = players.slice(0, MAX_PLAYERS_PER_POSITION);
      }
    });
    if (saved.activePosition && state.squad[saved.activePosition]) {
      state.activePosition = saved.activePosition;
    }
  } catch {
    // ignore corrupt storage
  }
}

function saveSquadToStorage() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      squad: state.squad,
      activePosition: state.activePosition,
      savedAt: new Date().toISOString(),
    })
  );
}

function profileLabelParts(label) {
  const text = String(label || "").trim();
  const parts = text.split(" - ").map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) {
    const main = parts[0].toUpperCase();
    const sub = parts.slice(1).join(" - ");
    if (sub.toUpperCase() === main) return { main, sub: null };
    return { main, sub };
  }
  return { main: text.toUpperCase(), sub: null };
}

function profileLabelMarkup(label) {
  const parts = profileLabelParts(label);
  if (parts.sub) {
    return `
      <p class="comparison-row__label-main">${parts.main}</p>
      <p class="comparison-row__label-sub">${parts.sub}</p>
    `;
  }
  return `<p class="comparison-row__label-main">${parts.main}</p>`;
}

function averageClass(value) {
  if (value == null || Number.isNaN(value)) return "comparison-cell--avg-low";
  if (value >= 66) return "comparison-cell--avg-high";
  if (value >= 33) return "comparison-cell--avg-mid";
  return "comparison-cell--avg-low";
}

function averageProfileScores(players, profiles) {
  const averages = {};
  profiles.forEach((profile) => {
    const values = players
      .map((player) => player.profileScores?.[profile.apiName])
      .filter((value) => value != null)
      .map(Number);
    averages[profile.apiName] = values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : null;
  });
  return averages;
}

function playerPhotoMarkup(player) {
  if (player.photoDataUrl) {
    return `<img class="player-photo__image" src="${player.photoDataUrl}" alt="${player.name}" />`;
  }
  return `<div class="player-photo__placeholder" aria-hidden="true">${playerInitials(player.name)}</div>`;
}

function setPasteTarget(positionId, playerIndex, wrap) {
  state.pasteTarget = { positionId, playerIndex };
  document.querySelectorAll(".player-photo__image-wrap--pasteable").forEach((el) => {
    el.classList.toggle("player-photo__image-wrap--active", el === wrap);
  });
  wrap?.focus();
}

function applyPastedImage(file) {
  const target = state.pasteTarget;
  if (!target || !file) return false;

  const reader = new FileReader();
  reader.onload = () => {
    const players = playersForPosition(target.positionId);
    if (!players[target.playerIndex]) return;
    players[target.playerIndex].photoDataUrl = reader.result;
    saveSquadToStorage();
    renderDeck();
    setStatus("Headshot updated.", "");
  };
  reader.readAsDataURL(file);
  return true;
}

function attachPhotoPaste(wrap, positionId, playerIndex) {
  wrap.tabIndex = 0;
  wrap.title = "Click then paste an image (Ctrl/Cmd+V)";
  wrap.classList.add("player-photo__image-wrap--pasteable");
  wrap.setAttribute("role", "button");
  wrap.setAttribute("aria-label", "Paste headshot from clipboard");

  const hint = document.createElement("span");
  hint.className = "player-photo__paste-hint";
  hint.textContent = "Click · paste image";
  wrap.appendChild(hint);

  wrap.addEventListener("click", (event) => {
    event.stopPropagation();
    setPasteTarget(positionId, playerIndex, wrap);
  });

  wrap.addEventListener("paste", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const items = event.clipboardData?.items;
    if (!items) return;

    for (const item of items) {
      if (!item.type.startsWith("image/")) continue;
      const file = item.getAsFile();
      if (!file) continue;
      setPasteTarget(positionId, playerIndex, wrap);
      applyPastedImage(file);
      return;
    }
    setStatus("Clipboard does not contain an image.", "warn");
  });
}

function createComparisonFrame(position) {
  const players = playersForPosition(position.id);
  const profiles = position.profiles || [];
  const averages = averageProfileScores(players, profiles);
  const playerCount = Math.max(players.length, 1);

  const frame = document.createElement("div");
  frame.className = "comparison-frame comparison-frame--keynote";
  frame.dataset.position = position.id;
  frame.dataset.players = String(players.length || 0);
  frame.dataset.profiles = String(profiles.length);
  if (players.length >= 4 && profiles.length >= 4) {
    frame.classList.add("comparison-frame--dense");
  }

  const head = document.createElement("div");
  head.className = "comparison-frame__head";
  head.innerHTML = `
    <div class="comparison-frame__titles">
      <p class="comparison-frame__club">SQUAD BALANCE</p>
      <h2 class="comparison-frame__title">${String(position.label).toUpperCase()} COMPARISON</h2>
      <p class="comparison-frame__season">4-3-3 recruitment plan · last 2 seasons combined at role</p>
    </div>
    <span class="comparison-frame__badge">${position.shortLabel}</span>
  `;
  frame.appendChild(head);

  const body = document.createElement("div");
  body.className = "comparison-frame__body";
  body.style.setProperty("--player-cols", String(playerCount));

  const table = document.createElement("div");
  table.className = "comparison-table";
  table.style.setProperty("--player-cols", String(playerCount));

  const corner = document.createElement("div");
  corner.className = "comparison-table__corner";
  corner.setAttribute("aria-hidden", "true");
  table.appendChild(corner);

  if (!players.length) {
    const emptyPhoto = document.createElement("div");
    emptyPhoto.className = "player-photo";
    emptyPhoto.style.gridColumn = "2";
    emptyPhoto.innerHTML = `
      <div class="player-photo__image-wrap">
        <div class="player-photo__placeholder">?</div>
      </div>
      <p class="player-photo__name" style="color:var(--text-muted)">Add players</p>
    `;
    table.appendChild(emptyPhoto);
  } else {
    players.forEach((player, index) => {
      const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
      const photo = document.createElement("div");
      photo.className = "player-photo";
      photo.style.gridColumn = String(index + 2);

      const wrap = document.createElement("div");
      wrap.className = "player-photo__image-wrap";
      wrap.style.borderColor = `color-mix(in srgb, ${color.main} 55%, rgba(245, 197, 24, 0.35))`;
      wrap.innerHTML = playerPhotoMarkup(player);
      attachPhotoPaste(wrap, position.id, index);

      photo.appendChild(wrap);
      const name = document.createElement("p");
      name.className = "player-photo__name";
      name.style.color = color.main;
      name.textContent = player.name;
      photo.appendChild(name);

      const minutes = document.createElement("p");
      minutes.className = "player-photo__minutes";
      minutes.textContent = `(${player.minutes || 0}′)`;
      if (player.scoring?.note) {
        minutes.title = player.scoring.note;
      }
      photo.appendChild(minutes);

      table.appendChild(photo);
    });
  }

  const avgPhoto = document.createElement("div");
  avgPhoto.className = "player-photo player-photo--average";
  avgPhoto.style.gridColumn = String(playerCount + 2);
  avgPhoto.innerHTML = `
    <div class="player-photo__image-wrap player-photo__image-wrap--average">
      <img class="player-photo__badge" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale FC crest" />
    </div>
    <p class="player-photo__name" style="color:var(--gold)">Average</p>
    <p class="player-photo__minutes">${players.length} player${players.length === 1 ? "" : "s"}</p>
  `;
  table.appendChild(avgPhoto);

  profiles.forEach((profile) => {
    const row = document.createElement("div");
    row.className = "comparison-row";

    const labelCell = document.createElement("div");
    labelCell.className = "comparison-row__label";
    labelCell.innerHTML = profileLabelMarkup(profile.label);
    row.appendChild(labelCell);

    const rowValues = players.map((player) => player.profileScores?.[profile.apiName] ?? null);
    const numericValues = rowValues.filter((value) => value != null);
    const leaderValue =
      numericValues.length > 0 ? Math.max(...numericValues.map((value) => Number(value))) : null;

    if (!players.length) {
      const emptyCell = document.createElement("div");
      emptyCell.className = "comparison-cell comparison-cell--bar";
      emptyCell.style.gridColumn = "2";
      emptyCell.innerHTML = `<span class="comparison-cell__value">—</span>`;
      row.appendChild(emptyCell);
    } else {
      players.forEach((player, index) => {
        const value = player.profileScores?.[profile.apiName];
        const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
        const cell = document.createElement("div");
        const isLeader = value != null && leaderValue != null && Number(value) === leaderValue;
        cell.className = `comparison-cell comparison-cell--bar${isLeader ? " comparison-cell--leader" : ""}`;
        cell.style.setProperty("--cell-color", color.main);
        cell.style.setProperty("--bar-color", color.main);
        if (value != null) {
          cell.style.setProperty("--bar-width", `${Math.max(0, Math.min(100, Number(value)))}%`);
        }
        cell.innerHTML = `<span class="comparison-cell__value">${value == null ? "—" : `${Math.round(value)}%`}</span>`;
        row.appendChild(cell);
      });
    }

    const avgValue = averages[profile.apiName];
    const avgCell = document.createElement("div");
    avgCell.className = `comparison-cell comparison-cell--bar comparison-cell--average ${averageClass(avgValue)}`;
    if (avgValue != null) {
      avgCell.style.setProperty("--bar-width", `${Math.max(0, Math.min(100, avgValue))}%`);
    }
    avgCell.innerHTML = `<span class="comparison-cell__value">${avgValue == null ? "—" : `${Math.round(avgValue)}%`}</span>`;
    row.appendChild(avgCell);

    table.appendChild(row);
  });

  body.appendChild(table);

  const legend = document.createElement("div");
  legend.className = "comparison-legend";
  legend.style.setProperty("--player-cols", String(playerCount));

  if (!players.length) {
    legend.innerHTML = `<div class="legend-item"><p class="legend-item__name" style="color:var(--text-muted)">Search and add players above</p></div>`;
  } else {
    legend.innerHTML = players
      .map((player, index) => {
        const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
        const photo = player.photoDataUrl
          ? `<img class="legend-item__photo" src="${player.photoDataUrl}" alt="" />`
          : `<span class="legend-item__photo legend-item__photo--fallback">${playerInitials(player.name)}</span>`;
        return `
          <div class="legend-item">
            ${photo}
            <span class="legend-item__line" style="background:${color.main}"></span>
            <p class="legend-item__name">${player.name}</p>
            <p class="legend-item__meta">${position.label}<br>${[player.club, player.league].filter(Boolean).join(" · ")}</p>
          </div>
        `;
      })
      .join("");
    legend.innerHTML += `
      <div class="legend-item legend-item--average">
        <img class="legend-item__photo legend-item__photo--badge" src="/standalone/port-vale-badge.png?v=2" alt="" />
        <span class="legend-item__line" style="background:var(--gold)"></span>
        <p class="legend-item__name">Average</p>
        <p class="legend-item__meta">Combined profile<br>scores for role</p>
      </div>
    `;
  }

  body.appendChild(legend);

  const note = document.createElement("p");
  note.className = "comparison-note";
  note.textContent =
    state.meta?.scoring?.note ||
    "Squad average column combines profile percentiles across players in this position group.";
  body.appendChild(note);

  frame.appendChild(body);
  return frame;
}

function buildPositionShell(position) {
  const players = playersForPosition(position.id);
  const shell = document.createElement("section");
  shell.className = "comparison-shell card";
  shell.id = `comparison-${position.id}`;

  const toolbar = document.createElement("div");
  toolbar.className = "comparison-shell__toolbar";
  toolbar.innerHTML = `
    <span class="comparison-shell__count">${players.length}/${MAX_PLAYERS_PER_POSITION} players · average on the right</span>
  `;

  const roster = document.createElement("div");
  roster.className = "comparison-shell__roster";
  if (!players.length) {
    roster.innerHTML = `<span class="comparison-shell__count">No players yet — search above to add</span>`;
  } else {
    players.forEach((player, index) => {
      const chip = document.createElement("span");
      chip.className = "roster-chip";
      chip.innerHTML = `
        <span>${player.name}</span>
        <button type="button" class="roster-chip__remove" title="Remove ${player.name}" aria-label="Remove ${player.name}">×</button>
      `;
      chip.querySelector(".roster-chip__remove").addEventListener("click", () => {
        removePlayer(position.id, index);
      });
      roster.appendChild(chip);
    });
  }

  toolbar.appendChild(roster);
  shell.appendChild(toolbar);
  shell.appendChild(createComparisonFrame(position));
  return shell;
}

function renderPositionNav() {
  const positions = state.meta?.positions || [];
  els.positionNav.innerHTML = positions
    .map((position) => {
      const count = playersForPosition(position.id).length;
      const active = position.id === state.activePosition ? " position-nav__link--active" : "";
      return `<a class="position-nav__link${active}" href="#comparison-${position.id}" data-position="${position.id}">${position.shortLabel}${count ? ` (${count})` : ""}</a>`;
    })
    .join("");

  els.positionNav.querySelectorAll("[data-position]").forEach((link) => {
    link.addEventListener("click", () => {
      state.activePosition = link.dataset.position;
      els.targetPosition.value = state.activePosition;
      renderPositionNav();
    });
  });
}

function renderDeck() {
  const positions = state.meta?.positions || [];
  els.comparisonDeck.innerHTML = "";

  if (!positions.length) {
    els.comparisonDeck.innerHTML = `<p class="comparison-empty">Loading position groups…</p>`;
    return;
  }

  positions.forEach((position) => {
    els.comparisonDeck.appendChild(buildPositionShell(position));
  });

  renderPositionNav();
}

function populatePositionSelect() {
  els.targetPosition.innerHTML = (state.meta?.positions || [])
    .map(
      (position) =>
        `<option value="${position.id}">${position.shortLabel} — ${position.label}</option>`
    )
    .join("");

  if (!state.activePosition && state.meta?.positions?.length) {
    state.activePosition = state.meta.positions[0].id;
  }
  if (state.activePosition) {
    els.targetPosition.value = state.activePosition;
  }
}

function parseImpectPlayerId(playerKey) {
  const suffix = String(playerKey || "").split("|").pop();
  return suffix && /^\d+$/.test(suffix) ? Number(suffix) : null;
}

function bestSeasonForPlayer(player) {
  const seasons = player.seasons || [];
  const chartable = seasons.filter((season) => season.chartable);
  return (chartable.length ? chartable : seasons)[0] || null;
}

function chartableIterationIds(player) {
  return (player.seasons || [])
    .filter((season) => season.chartable && season.iteration_id != null)
    .map((season) => season.iteration_id);
}

function renderSearchResults() {
  if (!state.searchResults.length) {
    els.searchResults.classList.add("hidden");
    els.searchResults.innerHTML = "";
    return;
  }

  els.searchResults.innerHTML = state.searchResults
    .map((player, index) => {
      const season = bestSeasonForPlayer(player);
      const meta = [season?.competition_name, season?.club].filter(Boolean).join(" · ");
      return `
        <button type="button" class="search-result" data-index="${index}" role="option">
          <div class="search-result__name">${player.name}</div>
          <div class="search-result__meta">${meta || "No season data"}</div>
        </button>
      `;
    })
    .join("");

  els.searchResults.classList.remove("hidden");
  els.searchResults.querySelectorAll(".search-result").forEach((button) => {
    button.addEventListener("click", () => {
      selectSearchPlayer(state.searchResults[Number(button.dataset.index)]);
    });
  });
}

function selectSearchPlayer(player) {
  state.selectedSearchPlayer = player;
  els.addPlayerBtn.disabled = !player;
  els.searchResults.classList.add("hidden");
  if (player) els.playerSearch.value = player.name;
}

async function searchPlayers(query) {
  const search = query.trim();
  if (search.length < SEARCH_MIN_CHARS) {
    state.searchResults = [];
    state.selectedSearchPlayer = null;
    els.addPlayerBtn.disabled = true;
    renderSearchResults();
    return;
  }
  if (search === lastSearchQuery) return;
  lastSearchQuery = search;

  try {
    const data = await fetchJson("/api/players", {
      method: "POST",
      body: JSON.stringify({ search }),
    });
    state.searchResults = data.players || [];
    state.selectedSearchPlayer = null;
    els.addPlayerBtn.disabled = true;
    renderSearchResults();
    setStatus(
      state.searchResults.length ? "" : data.message || `No players matched "${search}".`,
      state.searchResults.length ? "" : "warn"
    );
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function addSelectedPlayer() {
  const player = state.selectedSearchPlayer;
  const positionId = els.targetPosition.value || state.activePosition;
  if (!player || !positionId) return;

  const existing = playersForPosition(positionId);
  if (existing.length >= MAX_PLAYERS_PER_POSITION) {
    setStatus(`Maximum ${MAX_PLAYERS_PER_POSITION} players per position.`, "error");
    return;
  }

  const season = bestSeasonForPlayer(player);
  if (!season?.iteration_id) {
    setStatus("No chartable season found for this player.", "error");
    return;
  }

  const impectPlayerId = parseImpectPlayerId(player.key);
  if (!impectPlayerId) {
    setStatus("Could not resolve player ID.", "error");
    return;
  }

  const duplicate = existing.some(
    (entry) => entry.playerKey === player.key && entry.iterationId === season.iteration_id
  );
  if (duplicate) {
    setStatus("Player already in this position group.", "warn");
    return;
  }

  state.loading = true;
  els.addPlayerBtn.disabled = true;
  setStatus(`Loading profiles for ${player.name}…`, "loading");

  try {
    const squadId = player.squad_ids_by_iteration?.[String(season.iteration_id)] ?? null;
    const profileData = await fetchJson("/api/squad-balance/player", {
      method: "POST",
      body: JSON.stringify({
        position: positionId,
        player_key: player.key,
        iteration_id: season.iteration_id,
        iteration_ids: chartableIterationIds(player),
        impect_player_id: impectPlayerId,
        squad_id: squadId != null ? Number(squadId) : null,
        name: player.name,
      }),
    });

    existing.push({
      id: profileData.id,
      playerKey: profileData.playerKey,
      name: profileData.name,
      club: profileData.club,
      league: profileData.league,
      season: profileData.season,
      minutes: profileData.minutes,
      iterationId: profileData.iterationId,
      iterationIds: chartableIterationIds(player),
      impectPlayerId: profileData.impectPlayerId,
      squadId: squadId != null ? Number(squadId) : null,
      profileScores: profileData.profileScores,
      scoring: profileData.scoring || null,
      photoDataUrl: null,
    });

    state.activePosition = positionId;
    saveSquadToStorage();
    renderDeck();
    const minuteNote = profileData.scoring?.note
      ? ` · ${profileData.scoring.note}`
      : "";
    setStatus(`${player.name} added to ${positionMeta(positionId)?.label || positionId}${minuteNote}`, "");
    els.playerSearch.value = "";
    state.selectedSearchPlayer = null;
    state.searchResults = [];
    lastSearchQuery = "";
    renderSearchResults();
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.loading = false;
    els.addPlayerBtn.disabled = !state.selectedSearchPlayer;
  }
}

function removePlayer(positionId, index) {
  playersForPosition(positionId).splice(index, 1);
  saveSquadToStorage();
  renderDeck();
}

function clearSquad() {
  if (!confirm("Clear all players from Squad Balance?")) return;
  initSquadFromMeta();
  saveSquadToStorage();
  renderDeck();
  setStatus("Squad cleared.", "");
}

function downloadBlob(blob, filename) {
  const link = document.createElement("a");
  link.download = filename;
  link.href = URL.createObjectURL(blob);
  link.click();
  URL.revokeObjectURL(link.href);
}

function buildExportPayload() {
  return {
    title: "Squad Balance",
    subtitle: "4-3-3 recruitment plan · last 2 seasons combined at role",
    positions: (state.meta?.positions || []).map((position) => ({
      id: position.id,
      shortLabel: position.shortLabel,
      label: position.label,
      profiles: position.profiles,
      players: playersForPosition(position.id).map((player) => ({
        id: player.id,
        name: player.name,
        club: player.club || "",
        league: player.league || "",
        season: player.season || "",
        minutes: player.minutes || 0,
        profileScores: player.profileScores || {},
        photoDataUrl: player.photoDataUrl || null,
      })),
    })),
  };
}

async function exportPdf() {
  const payload = buildExportPayload();
  const playerCount = payload.positions.reduce(
    (sum, position) => sum + (position.players?.length || 0),
    0
  );
  if (!playerCount) {
    setStatus("Add at least one player before exporting a PDF.", "warn");
    return;
  }

  els.exportPdfBtn.disabled = true;
  setStatus("Building PDF with front page…", "loading");

  try {
    const res = await fetch("/api/squad-balance/export-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `PDF export failed (${res.status})`);
    }
    const blob = await res.blob();
    downloadBlob(blob, "squad-balance.pdf");
    setStatus("PDF exported.", "");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    els.exportPdfBtn.disabled = false;
  }
}

async function enrichPlayerCatalog(player) {
  if (player.iterationIds?.length && player.playerKey && player.impectPlayerId) {
    return player;
  }

  try {
    const data = await fetchJson("/api/players", {
      method: "POST",
      body: JSON.stringify({ search: player.name }),
    });
    const match =
      data.players?.find((entry) => entry.key === player.playerKey) ||
      data.players?.find((entry) => entry.name === player.name);
    if (!match) return player;

    player.playerKey = match.key;
    player.impectPlayerId = parseImpectPlayerId(match.key);
    player.iterationIds = chartableIterationIds(match);
    if (!player.squadId && match.squad_ids_by_iteration) {
      const season = bestSeasonForPlayer(match);
      const squadRaw = season
        ? match.squad_ids_by_iteration?.[String(season.iteration_id)]
        : null;
      if (squadRaw != null) player.squadId = Number(squadRaw);
    }
  } catch {
    // Keep stored values if lookup fails.
  }

  return player;
}

async function refreshStoredPlayers() {
  const positions = state.meta?.positions || [];
  let refreshed = 0;

  for (const position of positions) {
    const players = playersForPosition(position.id);
    for (const player of players) {
      await enrichPlayerCatalog(player);
      if (!player.playerKey || !player.impectPlayerId) continue;
      const iterationIds = player.iterationIds?.length
        ? player.iterationIds
        : player.iterationId
          ? [player.iterationId]
          : [];
      if (!iterationIds.length) continue;

      try {
        const profileData = await fetchJson("/api/squad-balance/player", {
          method: "POST",
          body: JSON.stringify({
            position: position.id,
            player_key: player.playerKey,
            iteration_id: iterationIds[0],
            iteration_ids: iterationIds,
            impect_player_id: player.impectPlayerId,
            squad_id: player.squadId ?? null,
            name: player.name,
          }),
        });
        const photoDataUrl = player.photoDataUrl;
        Object.assign(player, {
          minutes: profileData.minutes,
          season: profileData.season,
          club: profileData.club,
          league: profileData.league,
          profileScores: profileData.profileScores,
          scoring: profileData.scoring || null,
          iterationId: profileData.iterationId,
          iterationIds,
          photoDataUrl,
        });
        refreshed += 1;
      } catch {
        // Keep existing row if refresh fails.
      }
    }
  }

  if (refreshed) {
    saveSquadToStorage();
    renderDeck();
  }
  return refreshed;
}

async function init() {
  try {
    state.meta = await fetchJson("/api/squad-balance/meta");
    initSquadFromMeta();
    loadSquadFromStorage();
    populatePositionSelect();
    renderDeck();
    const refreshed = await refreshStoredPlayers();
    if (refreshed) {
      setStatus(`Updated ${refreshed} player${refreshed === 1 ? "" : "s"} with combined minutes.`, "");
    } else {
      setStatus("");
    }
  } catch (error) {
    setStatus(error.message, "error");
  }
}

els.playerSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => searchPlayers(els.playerSearch.value), SEARCH_DEBOUNCE_MS);
});

els.playerSearch.addEventListener("focus", () => {
  if (state.searchResults.length) els.searchResults.classList.remove("hidden");
});

els.targetPosition.addEventListener("change", () => {
  state.activePosition = els.targetPosition.value;
  renderPositionNav();
});

els.addPlayerBtn.addEventListener("click", addSelectedPlayer);
els.clearBtn.addEventListener("click", clearSquad);
els.exportPdfBtn?.addEventListener("click", exportPdf);
els.saveBtn.addEventListener("click", () => {
  saveSquadToStorage();
  setStatus("Squad saved to this browser.", "");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    els.searchResults.classList.add("hidden");
    state.pasteTarget = null;
  }
});

document.addEventListener("paste", (event) => {
  if (!state.pasteTarget) return;
  const items = event.clipboardData?.items;
  if (!items) return;

  for (const item of items) {
    if (!item.type.startsWith("image/")) continue;
    const file = item.getAsFile();
    if (!file) continue;
    event.preventDefault();
    applyPastedImage(file);
    return;
  }
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".player-photo__image-wrap--pasteable")) {
    state.pasteTarget = null;
    document.querySelectorAll(".player-photo__image-wrap--pasteable").forEach((el) => {
      el.classList.remove("player-photo__image-wrap--active");
    });
  }
  if (!event.target.closest(".search-wrap")) {
    els.searchResults.classList.add("hidden");
  }
});

init();
