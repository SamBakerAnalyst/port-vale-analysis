const PLAYER_COLORS = [
  { main: "#4a90d9", bg: "rgba(74, 144, 217, 0.18)" },
  { main: "#e573a8", bg: "rgba(229, 115, 168, 0.18)" },
  { main: "#4db6ac", bg: "rgba(77, 182, 172, 0.18)" },
  { main: "#f5c518", bg: "rgba(245, 197, 24, 0.18)" },
  { main: "#a78bfa", bg: "rgba(167, 139, 250, 0.18)" },
];

const AUTO_REFRESH_MS = 5 * 60 * 1000;

const state = {
  meta: null,
  deck: null,
  loading: false,
  selections: new Map(),
  season: "",
};

const els = {
  minMinutes: document.getElementById("minMinutes"),
  seasonToggle: document.getElementById("seasonToggle"),
  positionNav: document.getElementById("positionNav"),
  exportBtn: document.getElementById("exportBtn"),
  exportPdfBtn: document.getElementById("exportPdfBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusBanner: document.getElementById("statusBanner"),
  lastUpdated: document.getElementById("lastUpdated"),
  seasonSubtitle: document.getElementById("seasonSubtitle"),
  comparisonDeck: document.getElementById("comparisonDeck"),
};

function selectedSeason() {
  return state.season || state.meta?.defaultSeason || state.meta?.season || "";
}

function renderSeasonToggle() {
  const seasons = (state.meta?.seasons || []).slice(0, 2);
  const activeSeason = selectedSeason();
  if (!els.seasonToggle) return;

  if (!seasons.length) {
    els.seasonToggle.innerHTML = `<span class="season-toggle__empty">No seasons</span>`;
    return;
  }

  els.seasonToggle.innerHTML = seasons
    .map((season) => {
      const isActive = season.value === activeSeason;
      const pendingClass = season.hasData === false ? " season-toggle__btn--pending" : "";
      const title =
        season.hasData === false
          ? "Impect profile data is not loaded for this season yet"
          : `${season.competition || "Port Vale"} · ${season.label}`;
      return `<button type="button" class="season-toggle__btn${
        isActive ? " season-toggle__btn--active" : ""
      }${pendingClass}" data-season="${season.value}" title="${title}">${season.label}</button>`;
    })
    .join("");
}

function setSeason(seasonValue) {
  if (!seasonValue || seasonValue === state.season) return;
  state.season = seasonValue;
  renderSeasonToggle();
  loadAllComparisons();
}

function comparisonPayloadBase() {
  const payload = {
    min_minutes: Number(els.minMinutes.value || 0),
    max_players: maxComparePlayers(),
    selections: exportSelectionsPayload(),
  };
  const season = selectedSeason();
  if (season) payload.season = season;
  return payload;
}

function maxComparePlayers() {
  return state.meta?.maxComparePlayers || 5;
}

function minComparePlayers() {
  return 2;
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

function formatUpdatedAt(iso) {
  if (!iso) return "Not loaded yet";
  const date = new Date(iso);
  return `Updated ${date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

function updateActionState() {
  const hasDeck = Boolean(state.deck?.comparisons?.length);
  els.exportBtn.disabled = state.loading || !hasDeck;
  els.exportPdfBtn.disabled = state.loading || !hasDeck;
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

function playerInitials(name) {
  return String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

function playerPhotoMarkup(
  player,
  { className = "player-photo__image", fallbackClass = "player-photo__placeholder" } = {}
) {
  if (player.photoUrl) {
    return `<img class="${className}" src="${player.photoUrl}" alt="${player.name}" loading="lazy" crossorigin="anonymous" />`;
  }
  return `<div class="${fallbackClass}" aria-hidden="true">${playerInitials(player.name)}</div>`;
}

function profileLabelParts(label) {
  const text = String(label || "").trim();
  const parts = text.split(" - ").map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) {
    const main = parts[0].toUpperCase();
    const sub = parts.slice(1).join(" - ");
    if (sub.toUpperCase() === main) {
      return { main, sub: null };
    }
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

function comparisonTitle(data) {
  return `${String(data.positionLabel || "Player").toUpperCase()} COMPARISON`;
}

function rosterForComparison(comparison) {
  return comparison.roster || comparison.players || [];
}

function selectedPlayerIds(position) {
  return state.selections.get(position) || new Set();
}

function comparisonWithSelection(comparison) {
  const roster = rosterForComparison(comparison);
  const selected = selectedPlayerIds(comparison.position);
  const players = roster.filter((player) => selected.has(player.id));
  return { ...comparison, players };
}

function initSelectionsFromDeck(comparisons, previousSelections = new Map()) {
  comparisons.forEach((comparison) => {
    const roster = rosterForComparison(comparison);
    const rosterIds = new Set(roster.map((player) => player.id));
    const previous = previousSelections.get(comparison.position);
    if (previous) {
      const valid = [...previous].filter((id) => rosterIds.has(id));
      if (valid.length >= minComparePlayers()) {
        state.selections.set(comparison.position, new Set(valid));
        return;
      }
    }
    const fromApi = comparison.selectedPlayerIds || comparison.players?.map((player) => player.id) || [];
    const defaultIds = fromApi.filter((id) => rosterIds.has(id));
    if (defaultIds.length >= minComparePlayers()) {
      state.selections.set(comparison.position, new Set(defaultIds));
      return;
    }
    state.selections.set(
      comparison.position,
      new Set(roster.slice(0, maxComparePlayers()).map((player) => player.id))
    );
  });
}

function exportSelectionsPayload() {
  const selections = {};
  state.selections.forEach((ids, position) => {
    selections[position] = [...ids];
  });
  return selections;
}

function renderPositionNav(comparisons) {
  els.positionNav.innerHTML = comparisons
    .map((comparison) => {
      const shortLabel = comparison.positionShortLabel || comparison.position;
      return `<a class="position-nav__link" href="#comparison-${comparison.position}">${shortLabel}</a>`;
    })
    .join("");
}

function createComparisonFrame(data) {
  const players = data.players || [];
  const profiles = data.profiles || [];

  const frame = document.createElement("div");
  frame.className = "comparison-frame comparison-frame--keynote";
  frame.dataset.position = data.position;
  frame.dataset.players = String(players.length);
  frame.dataset.profiles = String(profiles.length);
  if (players.length >= 5 && profiles.length >= 5) {
    frame.classList.add("comparison-frame--dense");
  }

  const head = document.createElement("div");
  head.className = "comparison-frame__head";
  head.innerHTML = `
    <div class="comparison-frame__titles">
      <p class="comparison-frame__club">PORT VALE F.C.</p>
      <h2 class="comparison-frame__title">${comparisonTitle(data)}</h2>
      <p class="comparison-frame__season">${data.competition} · ${data.season}</p>
    </div>
    <span class="comparison-frame__badge">${data.positionShortLabel || data.position}</span>
  `;
  frame.appendChild(head);

  const body = document.createElement("div");
  body.className = "comparison-frame__body";
  body.style.setProperty("--player-cols", String(players.length));

  const table = document.createElement("div");
  table.className = "comparison-table";
  table.style.setProperty("--player-cols", String(players.length));

  const corner = document.createElement("div");
  corner.className = "comparison-table__corner";
  corner.setAttribute("aria-hidden", "true");
  table.appendChild(corner);

  players.forEach((player, index) => {
    const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
    const photo = document.createElement("div");
    photo.className = "player-photo";
    photo.style.gridColumn = String(index + 2);
    photo.innerHTML = `
      <div class="player-photo__image-wrap" style="border-color: color-mix(in srgb, ${color.main} 55%, rgba(245, 197, 24, 0.35))">
        ${playerPhotoMarkup(player)}
      </div>
      <p class="player-photo__name" style="color:${color.main}">${player.name}</p>
      <p class="player-photo__minutes">(${player.minutes}′)</p>
    `;
    table.appendChild(photo);
  });

  profiles.forEach((profile) => {
    const rowValues = players.map((player) => player.profileScores?.[profile.apiName] ?? null);
    const numericValues = rowValues.filter((value) => value != null);
    const leaderValue =
      numericValues.length > 0 ? Math.max(...numericValues.map((value) => Number(value))) : null;

    const row = document.createElement("div");
    row.className = "comparison-row";

    const labelCell = document.createElement("div");
    labelCell.className = "comparison-row__label";
    labelCell.innerHTML = profileLabelMarkup(profile.label);
    row.appendChild(labelCell);

    players.forEach((player, index) => {
      const value = player.profileScores?.[profile.apiName];
      const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
      const cell = document.createElement("div");
      const isLeader = value != null && leaderValue != null && Number(value) === leaderValue;
      cell.className = `comparison-cell${isLeader ? " comparison-cell--leader" : ""}`;
      cell.style.setProperty("--cell-color", color.main);
      if (isLeader) cell.style.setProperty("--cell-bg", color.bg);
      cell.innerHTML = `<span class="comparison-cell__value">${value == null ? "—" : `${Math.round(value)}%`}</span>`;
      row.appendChild(cell);
    });

    table.appendChild(row);
  });

  body.appendChild(table);

  const legend = document.createElement("div");
  legend.className = "comparison-legend";
  legend.innerHTML = players
    .map((player, index) => {
      const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
      const photo = player.photoUrl
        ? `<img class="legend-item__photo" src="${player.photoUrl}" alt="" loading="lazy" crossorigin="anonymous" />`
        : `<span class="legend-item__photo legend-item__photo--fallback">${playerInitials(player.name)}</span>`;
      return `
        <div class="legend-item">
          ${photo}
          <span class="legend-item__line" style="background:${color.main}"></span>
          <p class="legend-item__name">${player.name}</p>
          <p class="legend-item__meta">${player.positionLabel}<br>${player.club}</p>
        </div>
      `;
    })
    .join("");
  body.appendChild(legend);

  const note = document.createElement("p");
  note.className = "comparison-note";
  note.textContent = data.scoring?.note || "";
  body.appendChild(note);

  frame.appendChild(body);
  return frame;
}

function chipAvatarMarkup(player) {
  if (player.photoUrl) {
    return `<img class="player-chip__avatar" src="${player.photoUrl}" alt="" loading="lazy" crossorigin="anonymous" />`;
  }
  return `<span class="player-chip__avatar player-chip__avatar--fallback">${playerInitials(player.name)}</span>`;
}

function buildPlayerPicker(comparison) {
  const position = comparison.position;
  const roster = rosterForComparison(comparison);
  const selected = selectedPlayerIds(position);
  const selectedList = roster.filter((player) => selected.has(player.id));

  const picker = document.createElement("div");
  picker.className = "comparison-picker no-export";
  picker.dataset.position = position;

  const label = document.createElement("div");
  label.className = "comparison-picker__head";
  label.innerHTML = `
    <span class="comparison-picker__label">Players on slide</span>
    <span class="comparison-picker__hint">${minComparePlayers()}–${maxComparePlayers()} selected · not included in export</span>
  `;
  picker.appendChild(label);

  const chips = document.createElement("div");
  chips.className = "player-chips";

  roster.forEach((player) => {
    const isSelected = selected.has(player.id);
    const colorIndex = selectedList.findIndex((item) => item.id === player.id);
    const color = isSelected && colorIndex >= 0 ? PLAYER_COLORS[colorIndex % PLAYER_COLORS.length] : null;

    const chip = document.createElement("label");
    chip.className = `player-chip${isSelected ? " player-chip--selected" : ""}`;
    if (color) chip.style.setProperty("--chip-color", color.main);

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = isSelected;
    input.addEventListener("change", (event) => {
      togglePlayer(position, player.id, event.target.checked, event.target);
    });

    chip.appendChild(input);
    chip.appendChild(document.createRange().createContextualFragment(chipAvatarMarkup(player)));
    const name = document.createElement("span");
    name.textContent = player.name;
    chip.appendChild(name);
    const minutes = document.createElement("span");
    minutes.className = "player-chip__minutes";
    minutes.textContent = `${player.minutes}′`;
    chip.appendChild(minutes);

    chips.appendChild(chip);
  });

  picker.appendChild(chips);
  return picker;
}

function refreshSlideFrame(position) {
  const comparison = state.deck?.comparisons?.find((item) => item.position === position);
  if (!comparison) return;

  const shell = document.getElementById(`comparison-${position}`);
  const mount = shell?.querySelector(".comparison-export-target");
  if (!mount) return;

  const visible = comparisonWithSelection(comparison);
  mount.replaceChildren(createComparisonFrame(visible));
}

function refreshSlidePicker(position) {
  const comparison = state.deck?.comparisons?.find((item) => item.position === position);
  if (!comparison) return;

  const shell = document.getElementById(`comparison-${position}`);
  const existing = shell?.querySelector(".comparison-picker");
  const next = buildPlayerPicker(comparison);
  if (existing) {
    existing.replaceWith(next);
  }
}

function togglePlayer(position, playerId, checked, input) {
  const selected = new Set(selectedPlayerIds(position));
  const max = maxComparePlayers();
  const min = minComparePlayers();

  if (checked) {
    if (selected.size >= max) {
      input.checked = false;
      setStatus(`You can compare up to ${max} players per position.`, "error");
      return;
    }
    selected.add(playerId);
  } else {
    if (selected.size <= min) {
      input.checked = true;
      setStatus(`Keep at least ${min} players on each slide.`, "error");
      return;
    }
    selected.delete(playerId);
  }

  state.selections.set(position, selected);
  setStatus("");
  refreshSlidePicker(position);
  refreshSlideFrame(position);
}

function buildComparisonShell(comparison) {
  const shell = document.createElement("section");
  shell.className = "comparison-shell card";
  shell.id = `comparison-${comparison.position}`;

  shell.appendChild(buildPlayerPicker(comparison));

  const mount = document.createElement("div");
  mount.className = "comparison-export-target";
  mount.appendChild(createComparisonFrame(comparisonWithSelection(comparison)));
  shell.appendChild(mount);

  return shell;
}

function renderDeck(data) {
  const comparisons = data.comparisons || [];
  els.comparisonDeck.innerHTML = "";

  if (!comparisons.length) {
    els.comparisonDeck.innerHTML = `<p class="comparison-empty">No position groups have enough players to compare.</p>`;
    renderPositionNav([]);
    return;
  }

  comparisons.forEach((comparison) => {
    els.comparisonDeck.appendChild(buildComparisonShell(comparison));
  });

  renderPositionNav(comparisons);
  els.seasonSubtitle.textContent = `Live ${data.competition} squad profiles · ${data.season} · ${comparisons.length} position groups`;
  els.lastUpdated.textContent = formatUpdatedAt(data.updatedAt);
}

async function loadAllComparisons() {
  const previousSelections = new Map(state.selections);

  state.loading = true;
  updateActionState();
  setStatus("Loading all position groups from Impect…", "loading");

  try {
    const data = await fetchJson("/api/squad-review/comparison-all", {
      method: "POST",
      body: JSON.stringify(comparisonPayloadBase()),
    });
    state.deck = data;
    initSelectionsFromDeck(data.comparisons || [], previousSelections);
    renderDeck(data);
    setStatus("");
  } catch (error) {
    state.deck = null;
    els.comparisonDeck.innerHTML = "";
    renderPositionNav([]);
    setStatus(error.message, "error");
  } finally {
    state.loading = false;
    updateActionState();
  }
}

function downloadBlob(blob, filename) {
  const link = document.createElement("a");
  link.download = filename;
  link.href = URL.createObjectURL(blob);
  link.click();
  URL.revokeObjectURL(link.href);
}

function filenameFromDisposition(headerValue, fallback) {
  if (!headerValue) return fallback;
  const match = headerValue.match(/filename="?([^";]+)"?/i);
  return match?.[1] || fallback;
}

async function exportAllSlidesPng() {
  if (!state.deck?.comparisons?.length || typeof html2canvas !== "function") return;

  els.exportBtn.disabled = true;
  setStatus("Saving slide graphics…", "loading");

  try {
    const frames = [...document.querySelectorAll(".comparison-export-target .comparison-frame--keynote")];
    for (const frame of frames) {
      const position = frame.dataset.position || "comparison";
      const canvas = await html2canvas(frame, {
        backgroundColor: "#0d0d0d",
        scale: 2,
        useCORS: true,
        allowTaint: false,
      });
      const link = document.createElement("a");
      const shortLabel =
        state.deck.comparisons.find((item) => item.position === position)?.positionShortLabel ||
        position;
      link.download = `port-vale-${String(shortLabel).toLowerCase()}-comparison.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    setStatus("");
  } catch (error) {
    setStatus(error.message || "Failed to save slide graphics.", "error");
  } finally {
    updateActionState();
  }
}

async function exportAllPositionsPdf() {
  els.exportPdfBtn.disabled = true;
  setStatus("Building Keynote PDF…", "loading");

  try {
    const res = await fetch("/api/squad-review/export-pdf-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(comparisonPayloadBase()),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `PDF export failed (${res.status})`);
    }

    const blob = await res.blob();
    const filename = filenameFromDisposition(
      res.headers.get("Content-Disposition"),
      "port-vale-all-positions-comparison.pdf"
    );
    downloadBlob(blob, filename);
    setStatus("");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    updateActionState();
  }
}

async function init() {
  try {
    state.meta = await fetchJson("/api/squad-review/meta");
    state.season = state.meta.defaultSeason || state.meta.season || "";
    els.minMinutes.value = String(state.meta.defaultMinMinutes ?? 0);
    renderSeasonToggle();
    await loadAllComparisons();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

els.minMinutes.addEventListener("change", loadAllComparisons);
els.seasonToggle?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-season]");
  if (!button) return;
  setSeason(button.dataset.season);
});
els.refreshBtn.addEventListener("click", loadAllComparisons);
els.exportBtn.addEventListener("click", exportAllSlidesPng);
els.exportPdfBtn.addEventListener("click", exportAllPositionsPdf);

setInterval(() => {
  if (state.loading || document.hidden) return;
  loadAllComparisons();
}, AUTO_REFRESH_MS);

init();
