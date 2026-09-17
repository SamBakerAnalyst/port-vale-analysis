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
  charts: new Map(),
  chartLoads: new Map(),
  chartObserver: null,
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
  document.querySelectorAll(".comparison-picker__export").forEach((button) => {
    button.disabled = state.loading || !hasDeck;
  });
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

function playerShortLabel(name, allNames = []) {
  const first = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)[0];
  if (!first) return playerInitials(name);
  const firstKey = first.toLowerCase();
  const clash = allNames.filter((other) => {
    const otherFirst = String(other || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)[0]
      ?.toLowerCase();
    return otherFirst === firstKey;
  }).length > 1;
  return clash ? playerInitials(name) : first;
}

function formatProfileName(name) {
  const stripped = String(name || "")
    .replace(/^PV\s*[-:]?\s*/i, "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!stripped) return "Profile";
  const abbrevs = new Set(["CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "CF", "GK", "WB"]);
  return stripped
    .split(" ")
    .map((word) => {
      const upper = word.toUpperCase();
      if (abbrevs.has(upper)) return upper;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

function profileChartTitle(comparison, entry) {
  const profile = comparison.profiles?.find((item) => item.apiName === entry.profile);
  return formatProfileName(entry.profile || profile?.apiName || profile?.label || "Profile");
}

const TOP_WEIGHTED_FACTORS = 3;

const FULL_STAT_LABELS = {
  "aerial duel success rate": "Aerial duel win %",
  "ground duel success rate": "Ground duel win %",
  "aerial duel win %": "Aerial duel win %",
  "ground duel win %": "Ground duel win %",
  "aerial duels in central zone": "Number of aerial duels in packing zone CB",
  "teammates added": "Ratio — add teammates",
  "opponents removed": "Ratio — remove opponents",
  "opponents bypassed": "Opponents bypassed",
  "defensive headers": "Defensive header score",
  "attacking headers": "Offensive header score",
  "headers on target": "Header shot score",
  "ground duels": "Ground duel score",
  "interceptions": "Interception score",
  "loose ball regains": "Loose ball regain score",
  "touches in left channel": "Total touches FBL",
  "touches in right channel": "Total touches FBR",
  "touches centrally": "Total touches CB",
};

function wrapRadarLabel(label) {
  const text = factorDisplayLabel(label);
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) return [text];
  const lines = [];
  let current = "";
  words.forEach((word) => {
    const next = current ? `${current} ${word}` : word;
    if (current && next.length > 16) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  });
  if (current) lines.push(current);
  return lines;
}

function playerInitials(name) {
  return String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

function uniquePlayerInitials(name, allNames = []) {
  const partsOf = (value) =>
    String(value || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
  const schemes = [
    (value) => {
      const parts = partsOf(value);
      if (!parts.length) return "?";
      if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
      return `${parts[0][0] || ""}${parts[parts.length - 1][0] || ""}`.toUpperCase();
    },
    (value) => {
      const first = partsOf(value)[0] || "";
      return first.slice(0, 2).toUpperCase() || "?";
    },
    (value) => {
      const parts = partsOf(value);
      const first = parts[0] || "";
      const last = parts[parts.length - 1] || "";
      return `${(first[0] || "").toUpperCase()}${last.slice(0, 2).toUpperCase()}`;
    },
  ];
  for (const make of schemes) {
    const label = make(name);
    const clash = allNames.filter((other) => make(other) === label).length > 1;
    if (!clash) return label;
  }
  return playerInitials(name);
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
    <div class="comparison-picker__titles">
      <span class="comparison-picker__label">Players on slide</span>
      <span class="comparison-picker__hint">${minComparePlayers()}–${maxComparePlayers()} selected · not included in export</span>
    </div>
  `;
  const exportBtn = document.createElement("button");
  exportBtn.type = "button";
  exportBtn.className = "btn btn--primary comparison-picker__export";
  exportBtn.textContent = "Full export";
  exportBtn.title = `Full export for ${comparison.positionLabel || "this position"} — overview plus a factor breakdown of each profile`;
  exportBtn.addEventListener("click", () => exportPositionFullPdf(position));
  label.appendChild(exportBtn);
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
  enqueuePositionCharts(position);
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

  const charts = document.createElement("div");
  charts.className = "comparison-charts";
  charts.dataset.position = comparison.position;
  charts.innerHTML = `<p class="comparison-charts__status">Loading radar and factor charts…</p>`;
  shell.appendChild(charts);

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
  const origin = data.source === "impect" ? "Live" : "Cached";
  els.seasonSubtitle.textContent = `${origin} ${data.competition} squad profiles · ${data.season} · ${comparisons.length} position groups`;
  els.lastUpdated.textContent = formatUpdatedAt(data.updatedAt);
  watchComparisonCharts();
}

async function loadAllComparisons({ forceRefresh = false } = {}) {
  const previousSelections = new Map(state.selections);

  state.loading = true;
  updateActionState();
  setStatus(
    forceRefresh ? "Refreshing from Impect…" : "Loading squad comparison…",
    "loading"
  );

  try {
    const payload = comparisonPayloadBase();
    if (forceRefresh) payload.force_refresh = true;
    const data = await fetchJson("/api/squad-review/comparison-all", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (forceRefresh) {
      state.charts.clear();
      state.chartLoads.clear();
    }
    state.deck = data;
    initSelectionsFromDeck(data.comparisons || [], previousSelections);
    renderDeck(data);
    setStatus("");
  } catch (error) {
    if (state.deck?.comparisons?.length) {
      setStatus(error.message, "error");
    } else {
      state.deck = null;
      els.comparisonDeck.innerHTML = "";
      renderPositionNav([]);
      setStatus(error.message, "error");
    }
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

function playerKey(name, playerId) {
  return `${String(name || "").toLowerCase().trim()}|${playerId}`;
}

function percentileBandKey(value) {
  const numeric = Number(value);
  if (value == null || !Number.isFinite(numeric)) return "na";
  if (numeric >= 80) return "elite";
  if (numeric >= 60) return "good";
  if (numeric >= 40) return "fair";
  if (numeric >= 25) return "poor";
  return "weak";
}

function drilldownBarLabels(entry) {
  if (entry.bar_labels?.length) return entry.bar_labels;
  return entry.labels || [];
}

function preferredFactor(label) {
  return /aerial duel win\s*%/i.test(String(label || ""));
}

function topWeightedDrilldown(entry) {
  const labels = drilldownBarLabels(entry).map((label) => String(label || "").trim()).filter(Boolean);
  const weights = entry.bar_weights || [];
  const ranked = labels.map((label, index) => ({
    index,
    label,
    weight: Number(weights[index]) || 0,
  }));
  ranked.sort((left, right) => {
    if (right.weight !== left.weight) return right.weight - left.weight;
    const pref = Number(preferredFactor(right.label)) - Number(preferredFactor(left.label));
    if (pref) return pref;
    return left.index - right.index;
  });
  const top = ranked.slice(0, TOP_WEIGHTED_FACTORS);
  const order = top.map((item) => item.index);
  const remap = (values) =>
    order.map((index) => (Array.isArray(values) && values[index] != null ? values[index] : null));
  return {
    ...entry,
    labels: top.map((item) => factorDisplayLabel(item.label)),
    bar_labels: top.map((item) => factorDisplayLabel(item.label)),
    bar_weights: top.map((item) => item.weight),
    players: (entry.players || []).map((player) => {
      const standings = player.bar_radar_values || player.radar_values || [];
      const raw = player.bar_raw_values || player.raw_values || [];
      const metrics = player.bar_metric_values || player.metric_values || raw;
      return {
        ...player,
        labels: top.map((item) => factorDisplayLabel(item.label)),
        bar_labels: top.map((item) => factorDisplayLabel(item.label)),
        radar_values: remap(standings),
        bar_radar_values: remap(standings),
        raw_values: remap(raw),
        bar_raw_values: remap(raw),
        metric_values: remap(metrics),
        bar_metric_values: remap(metrics),
      };
    }),
  };
}

function drilldownStanding(player, factorIndex) {
  const fromBars = Number(player.bar_radar_values?.[factorIndex]);
  if (Number.isFinite(fromBars)) return fromBars;
  const fromRadar = Number(player.radar_values?.[factorIndex]);
  return Number.isFinite(fromRadar) ? fromRadar : null;
}

function drilldownRaw(player, factorIndex) {
  const fromBars = Number(player.bar_raw_values?.[factorIndex]);
  if (Number.isFinite(fromBars)) return fromBars;
  const fromRadar = Number(player.raw_values?.[factorIndex]);
  return Number.isFinite(fromRadar) ? fromRadar : null;
}

function drilldownMetric(player, factorIndex) {
  const fromRaw = Number(player.bar_raw_values?.[factorIndex]);
  if (Number.isFinite(fromRaw)) return fromRaw;
  const fromMetric = Number(player.bar_metric_values?.[factorIndex]);
  if (Number.isFinite(fromMetric)) {
    return fromMetric <= 1 && fromMetric >= -1 ? fromMetric * 100 : fromMetric;
  }
  const fromSeries = Number(player.metric_values?.[factorIndex]);
  if (Number.isFinite(fromSeries)) {
    return fromSeries <= 1 && fromSeries >= -1 ? fromSeries * 100 : fromSeries;
  }
  return drilldownRaw(player, factorIndex);
}

function factorValueKind(label) {
  const text = String(label || "").toLowerCase();
  if (/%|win %|success rate/.test(text)) return "percent";
  return "number";
}

function formatFactorMetric(label, value) {
  if (!Number.isFinite(value)) return "—";
  const kind = factorValueKind(label);
  if (kind === "percent") {
    const pct = value <= 1 && value >= 0 ? value * 100 : value;
    return `${Math.round(pct)}%`;
  }
  const abs = Math.abs(value);
  if (abs >= 100) return String(Math.round(value));
  if (abs >= 10) return String(Number(value.toFixed(1)));
  return String(Number(value.toFixed(1)));
}

function groupMaxMetric(players, factorIndex) {
  const values = players
    .map((player) => drilldownMetric(player, factorIndex))
    .filter((value) => Number.isFinite(value));
  return values.length ? Math.max(...values.map((value) => Math.abs(value))) : 0;
}

function scaledMetricShare(players, factorIndex, value) {
  if (!Number.isFinite(value)) return 0;
  const max = groupMaxMetric(players, factorIndex);
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (Math.abs(value) / max) * 100));
}

function factorDisplayLabel(label) {
  const text = String(label || "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "";
  const lowered = text.toLowerCase();
  if (FULL_STAT_LABELS[lowered]) return FULL_STAT_LABELS[lowered];
  const prefix = Object.keys(FULL_STAT_LABELS).find(
    (key) => lowered.startsWith(`${key} — `) || lowered.startsWith(`${key} - `)
  );
  if (prefix) {
    const rest = text.slice(prefix.length).replace(/^\s*[—-]\s*/, "").trim();
    return rest ? `${FULL_STAT_LABELS[prefix]} — ${rest}` : FULL_STAT_LABELS[prefix];
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function chartRequestForComparison(comparison, playerIds) {
  const selected = (comparison.roster || comparison.players || []).filter((player) =>
    playerIds.includes(player.id)
  );
  const iterationId = Number(comparison.iterationId);
  const squadId = comparison.squadId != null ? Number(comparison.squadId) : null;
  const position = comparison.position;
  const profiles = (comparison.profiles || []).map((profile) => profile.apiName).filter(Boolean);
  const playerKeys = [];
  const playerCatalog = {};
  const playerSeasons = {};
  const playerPositions = {};
  selected.forEach((player) => {
    const key = playerKey(player.name, player.id);
    playerKeys.push(key);
    const catalog = {
      name: player.name,
      ids_by_iteration: { [iterationId]: player.id },
    };
    if (squadId != null) {
      catalog.squad_ids_by_iteration = { [iterationId]: squadId };
    }
    playerCatalog[key] = catalog;
    playerSeasons[key] = [iterationId];
    playerPositions[key] = [position];
  });
  return {
    iteration_ids: [iterationId],
    competition_name: comparison.competition || null,
    player_keys: playerKeys,
    player_catalog: playerCatalog,
    player_seasons: playerSeasons,
    player_positions: playerPositions,
    positions: [position],
    profiles,
    chart_source: "profiles",
    include_drilldowns: true,
    min_games: 0,
  };
}

function radarPoint(cx, cy, radius, index, count, value) {
  const t = (index / count) * 2 * Math.PI;
  const r = radius * (Math.max(0, Math.min(100, Number(value) || 0)) / 100);
  return [cx + r * Math.sin(t), cy - r * Math.cos(t)];
}

function buildProfileRadarSvg(entry, players) {
  const labels = drilldownBarLabels(entry).filter(Boolean);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "keynote-radar-svg");
  svg.setAttribute("viewBox", "0 0 320 320");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Profile radar");
  if (labels.length < 3) {
    return svg;
  }

  const cx = 160;
  const cy = 160;
  const radius = 64;
  const ns = "http://www.w3.org/2000/svg";

  [20, 40, 60, 80, 100].forEach((pct) => {
    const ring = document.createElementNS(ns, "circle");
    ring.setAttribute("class", "radar-ring");
    ring.setAttribute("cx", String(cx));
    ring.setAttribute("cy", String(cy));
    ring.setAttribute("r", String(radius * (pct / 100)));
    svg.appendChild(ring);
  });

  labels.forEach((label, index) => {
    const [x, y] = radarPoint(cx, cy, radius, index, labels.length, 100);
    const spoke = document.createElementNS(ns, "line");
    spoke.setAttribute("class", "radar-spoke");
    spoke.setAttribute("x1", String(cx));
    spoke.setAttribute("y1", String(cy));
    spoke.setAttribute("x2", String(x));
    spoke.setAttribute("y2", String(y));
    svg.appendChild(spoke);

    const [lx, ly] = radarPoint(cx, cy, radius + 38, index, labels.length, 100);
    const text = document.createElementNS(ns, "text");
    text.setAttribute("class", "radar-label");
    text.setAttribute("x", String(lx));
    text.setAttribute("y", String(ly));
    const lines = wrapRadarLabel(label);
    lines.forEach((line, lineIndex) => {
      const tspan = document.createElementNS(ns, "tspan");
      tspan.setAttribute("x", String(lx));
      tspan.setAttribute(
        "dy",
        lineIndex === 0 ? `${-((lines.length - 1) * 0.55)}em` : "1.1em"
      );
      tspan.textContent = line;
      text.appendChild(tspan);
    });
    svg.appendChild(text);
  });

  players.forEach((player) => {
    const points = labels
      .map((label, index) => {
        const metric = drilldownMetric(player, index);
        const share = scaledMetricShare(players, index, metric);
        return radarPoint(cx, cy, radius, index, labels.length, share);
      })
      .concat(
        (() => {
          const metric = drilldownMetric(player, 0);
          return [radarPoint(cx, cy, radius, 0, labels.length, scaledMetricShare(players, 0, metric))];
        })()
      );
    const shape = document.createElementNS(ns, "polygon");
    shape.setAttribute("class", "radar-shape");
    shape.setAttribute("points", points.map((pair) => pair.join(",")).join(" "));
    shape.setAttribute("fill", player.color.main);
    shape.setAttribute("stroke", player.color.main);
    svg.appendChild(shape);
  });

  return svg;
}

function buildKeynoteFactorBars(entry, players, { compact = false } = {}) {
  const grid = document.createElement("div");
  grid.className = "keynote-factors";
  const labels = drilldownBarLabels(entry);
  const weights = entry.bar_weights || [];
  grid.dataset.factors = String(labels.length);
  grid.dataset.players = String(Math.min(players.length, 5));

  labels.forEach((label, factorIndex) => {
    const factor = document.createElement("div");
    factor.className = "keynote-factor";
    const head = document.createElement("div");
    head.className = "keynote-factor__head";
    const name = document.createElement("p");
    name.className = "keynote-factor__name";
    name.textContent = factorDisplayLabel(label);
    name.title = factorDisplayLabel(label);
    head.appendChild(name);
    if (weights[factorIndex] != null) {
      const weight = document.createElement("span");
      weight.className = "keynote-factor__weight";
      weight.textContent = `${Math.round(weights[factorIndex])}% of profile`;
      head.appendChild(weight);
    }
    factor.appendChild(head);

    const rows = document.createElement("div");
    rows.className = "keynote-factor__rows";
    const names = players.map((player) => player.player || player.name || "");
    players.forEach((player, playerIndex) => {
      const metric = drilldownMetric(player, factorIndex);
      const share = scaledMetricShare(players, factorIndex, metric);
      const inverted = Boolean(entry.bar_inverted?.[factorIndex]);
      const band = inverted ? 100 - share : share;
      const row = document.createElement("div");
      row.className = `keynote-factor__row keynote-band--${percentileBandKey(
        Number.isFinite(metric) ? band : null
      )}`;
      if (players.length > 1) {
        const initial = document.createElement("span");
        initial.className = "keynote-factor__initial";
        initial.title = player.player || player.name || "";
        initial.style.background = PLAYER_COLORS[playerIndex % PLAYER_COLORS.length].main;
        initial.textContent = uniquePlayerInitials(player.player || player.name || "", names);
        row.appendChild(initial);
      }
      const track = document.createElement("div");
      track.className = "keynote-factor__track";
      if (Number.isFinite(metric)) {
        const fill = document.createElement("span");
        fill.className = "keynote-factor__fill";
        fill.style.width = `${Math.max(2, share)}%`;
        track.appendChild(fill);
      }
      row.appendChild(track);
      const value = document.createElement("span");
      value.className = "keynote-factor__value";
      value.textContent = formatFactorMetric(label, metric);
      row.appendChild(value);
      rows.appendChild(row);
    });
    factor.appendChild(rows);
    grid.appendChild(factor);
  });
  return grid;
}

function chartsCacheKey(position, playerIds) {
  return `${position}|${[...playerIds]
    .map(Number)
    .sort((left, right) => left - right)
    .join(",")}`;
}

function decorateDrilldownPlayers(comparison, entry, chartPlayers) {
  const byName = new Map(
    (comparison.roster || comparison.players || []).map((player) => [
      String(player.name || "").toLowerCase(),
      player,
    ])
  );
  return (entry.players || chartPlayers || []).map((player, index) => {
    const local = byName.get(String(player.player || "").toLowerCase());
    return {
      ...player,
      player: player.player || local?.name || "Player",
      photoUrl: local?.photoUrl || player.photo_url,
      minutes: local?.minutes ?? player.play_duration_minutes,
      color: PLAYER_COLORS[index % PLAYER_COLORS.length],
    };
  });
}

function buildLivePlayerStrip(players) {
  const row = document.createElement("div");
  row.className = "profile-chart-card__players";
  row.dataset.count = String(Math.min(players.length, 5));
  players.forEach((player) => {
    const cell = document.createElement("div");
    cell.className = "profile-chart-card__player";
    cell.style.setProperty("--player-color", player.color.main);
    const photo = document.createElement("div");
    photo.className = "profile-chart-card__photo";
    photo.style.borderColor = player.color.main;
    photo.innerHTML = playerPhotoMarkup(
      { name: player.player, photoUrl: player.photoUrl },
      { fallbackClass: "profile-chart-card__photo-fallback" }
    );
    cell.appendChild(photo);
    const name = document.createElement("p");
    name.className = "profile-chart-card__player-name";
    const parts = String(player.player || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    const first = document.createElement("span");
    first.textContent = parts[0] || player.player;
    name.appendChild(first);
    if (parts.length > 1) {
      const last = document.createElement("span");
      last.textContent = parts.slice(1).join(" ");
      name.appendChild(last);
    }
    cell.appendChild(name);
    row.appendChild(cell);
  });
  return row;
}

function buildLiveProfileChartCard(comparison, entry, chartPlayers) {
  entry = topWeightedDrilldown(entry);
  const players = decorateDrilldownPlayers(comparison, entry, chartPlayers);
  const card = document.createElement("section");
  card.className = "profile-chart-card";

  const head = document.createElement("header");
  head.className = "profile-chart-card__head";
  const title = document.createElement("div");
  title.innerHTML = `
    <p class="profile-chart-card__eyebrow">Profile chart</p>
    <h3 class="profile-chart-card__title">${profileChartTitle(comparison, entry)}</h3>
  `;
  head.appendChild(title);

  const profileIndex = (comparison.profiles || []).findIndex(
    (profile) => profile.apiName === entry.profile
  );
  if (profileIndex >= 0) {
    const scores = document.createElement("div");
    scores.className = "profile-chart-card__scores";
    const names = players.map((player) => player.player || player.name || "");
    players.slice(0, 5).forEach((player) => {
      const local = (comparison.roster || comparison.players || []).find(
        (item) => String(item.name || "").toLowerCase() === String(player.player || "").toLowerCase()
      );
      const value = Number(local?.profileScores?.[entry.profile]);
      if (!Number.isFinite(value)) return;
      const chip = document.createElement("div");
      chip.className = `profile-chart-card__score keynote-band--${percentileBandKey(value)}`;
      chip.innerHTML = `<span title="${player.player}">${playerShortLabel(player.player, names)}</span><strong>${Math.round(value)}</strong>`;
      scores.appendChild(chip);
    });
    if (scores.childElementCount) head.appendChild(scores);
  }
  card.appendChild(head);

  const body = document.createElement("div");
  body.className = "profile-chart-card__body";
  const radarCol = document.createElement("div");
  radarCol.className = "profile-chart-card__radar";
  radarCol.appendChild(buildProfileRadarSvg(entry, players));
  radarCol.appendChild(buildLivePlayerStrip(players));
  const bars = document.createElement("div");
  bars.className = "profile-chart-card__bars";
  bars.appendChild(buildKeynoteFactorBars(entry, players, { compact: true }));
  body.appendChild(radarCol);
  body.appendChild(bars);
  card.appendChild(body);
  return card;
}

function renderPositionCharts(position, charts) {
  const comparison = state.deck?.comparisons?.find((item) => item.position === position);
  const mount = document.querySelector(`#comparison-${position} .comparison-charts`);
  if (!comparison || !mount) return;

  const drilldowns = (charts?.profile_drilldowns || []).filter(
    (entry) => (entry.labels || entry.bar_labels || []).length
  );
  if (!drilldowns.length) {
    mount.innerHTML = `<p class="comparison-charts__status">No radar or factor charts for this selection.</p>`;
    return;
  }

  const heading = document.createElement("p");
  heading.className = "comparison-charts__label";
  heading.textContent = "Radar and factor breakdowns";
  const cards = drilldowns.map((entry) =>
    buildLiveProfileChartCard(comparison, entry, charts.players || [])
  );
  mount.replaceChildren(heading, ...cards);
}

async function loadPositionCharts(position) {
  const comparison = state.deck?.comparisons?.find((item) => item.position === position);
  const mount = document.querySelector(`#comparison-${position} .comparison-charts`);
  if (!comparison || !mount) return;

  const ids = [...selectedPlayerIds(position)];
  if (ids.length < minComparePlayers()) {
    mount.innerHTML = `<p class="comparison-charts__status">Select at least two players to load charts.</p>`;
    return;
  }

  const key = chartsCacheKey(position, ids);
  if (state.charts.has(key)) {
    renderPositionCharts(position, state.charts.get(key));
    return;
  }

  const inflight = state.chartLoads.get(key);
  if (inflight) {
    try {
      renderPositionCharts(position, await inflight);
    } catch (error) {
      if (chartsCacheKey(position, selectedPlayerIds(position)) === key) {
        mount.innerHTML = `<p class="comparison-charts__status comparison-charts__status--error">${error.message}</p>`;
      }
    }
    return;
  }

  mount.innerHTML = `<p class="comparison-charts__status">Loading radar and factor charts…</p>`;
  const payload = {
    position,
    player_ids: ids,
    min_minutes: Number(els.minMinutes.value || 0),
  };
  const season = selectedSeason();
  if (season) payload.season = season;

  const promise = fetchJson("/api/squad-review/charts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.chartLoads.set(key, promise);
  try {
    const charts = await promise;
    if (chartsCacheKey(position, selectedPlayerIds(position)) !== key) return;
    state.charts.set(key, charts);
    renderPositionCharts(position, charts);
  } catch (error) {
    if (
      mount.isConnected &&
      chartsCacheKey(position, selectedPlayerIds(position)) === key
    ) {
      mount.innerHTML = `<p class="comparison-charts__status comparison-charts__status--error">${error.message}</p>`;
    }
  } finally {
    if (state.chartLoads.get(key) === promise) state.chartLoads.delete(key);
  }
}

let chartQueue = Promise.resolve();

function enqueuePositionCharts(position) {
  if (!position) return;
  chartQueue = chartQueue.then(() => loadPositionCharts(position)).catch(() => {});
}

function watchComparisonCharts() {
  state.chartObserver?.disconnect();
  const mounts = [...document.querySelectorAll(".comparison-charts")];
  if (!mounts.length) return;

  if (typeof IntersectionObserver !== "function") {
    mounts.forEach((node) => enqueuePositionCharts(node.dataset.position));
    return;
  }

  state.chartObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        enqueuePositionCharts(entry.target.getAttribute("data-position"));
      });
    },
    { rootMargin: "240px 0px", threshold: 0.01 }
  );
  mounts.forEach((node) => state.chartObserver.observe(node));
  const hashPosition = String(location.hash || "").replace(/^#comparison-/, "");
  const preferred =
    (hashPosition && mounts.some((node) => node.dataset.position === hashPosition)
      ? hashPosition
      : mounts[0]?.dataset.position) || "";
  enqueuePositionCharts(preferred);
}

function buildPlayerComparisonDrilldownSlide(comparison, entry, chartPlayers) {
  entry = topWeightedDrilldown(entry);
  const players = decorateDrilldownPlayers(comparison, entry, chartPlayers);

  const slide = document.createElement("div");
  slide.className = "keynote-slide keynote-drilldown";
  slide.dataset.slideTitle = entry.profile || "Profile";

  const head = document.createElement("header");
  head.className = "keynote-drilldown__head";
  const headText = document.createElement("div");
  headText.className = "keynote-drilldown__head-text";
  headText.innerHTML = `
    <p class="keynote-drilldown__eyebrow">Player Comparison</p>
    <h2 class="keynote-drilldown__title">${profileChartTitle(comparison, entry)}</h2>
    <p class="keynote-drilldown__sub">${comparison.positionLabel} · ${
      comparison.competition
    } · ${comparison.season}. Top 3 weighted factors. Numbers are Impect factor scores (win rates as %). Bars scaled to the highest player here.</p>
  `;
  head.appendChild(headText);

  const profileIndex = (comparison.profiles || []).findIndex(
    (profile) => profile.apiName === entry.profile
  );
  if (profileIndex >= 0) {
    const scores = document.createElement("div");
    scores.className = "keynote-drilldown__scores";
    players.slice(0, 5).forEach((player) => {
      const local = (comparison.roster || comparison.players || []).find(
        (item) => String(item.name || "").toLowerCase() === String(player.player || "").toLowerCase()
      );
      const value = Number(local?.profileScores?.[entry.profile]);
      if (!Number.isFinite(value)) return;
      const chip = document.createElement("div");
      chip.className = `keynote-drilldown__score keynote-band--${percentileBandKey(value)}`;
      chip.innerHTML = `
        <span class="keynote-drilldown__score-name">${player.player}</span>
        <span class="keynote-drilldown__score-value">${Math.round(value)}</span>
      `;
      scores.appendChild(chip);
    });
    if (scores.childElementCount) head.appendChild(scores);
  }

  const crest = document.createElement("img");
  crest.className = "keynote-crest";
  crest.src = "/standalone/port-vale-badge.png?v=2";
  crest.alt = "Port Vale";
  head.appendChild(crest);
  slide.appendChild(head);

  const playersRow = document.createElement("div");
  playersRow.className = "keynote-drilldown__players";
  playersRow.dataset.count = String(Math.min(players.length, 5));
  players.forEach((player) => {
    const cell = document.createElement("div");
    cell.className = "keynote-drilldown__player";
    cell.style.setProperty("--player-color", player.color.main);
    const photo = document.createElement("div");
    photo.className = "keynote-drilldown__photo";
    photo.style.borderColor = player.color.main;
    photo.innerHTML = playerPhotoMarkup(
      { name: player.player, photoUrl: player.photoUrl },
      { fallbackClass: "keynote-drilldown__photo-placeholder" }
    );
    cell.appendChild(photo);
    const identity = document.createElement("div");
    identity.className = "keynote-drilldown__player-identity";
    identity.innerHTML = `
      <p class="keynote-drilldown__player-name">${player.player}</p>
      <p class="keynote-drilldown__player-meta">${
        player.minutes ? `${player.minutes} min` : ""
      }</p>
    `;
    cell.appendChild(identity);
    playersRow.appendChild(cell);
  });

  const radarCol = document.createElement("div");
  radarCol.className = "keynote-drilldown__radar";
  const chartWrap = document.createElement("div");
  chartWrap.className = "keynote-drilldown__chart-wrap";
  chartWrap.appendChild(buildProfileRadarSvg(entry, players));
  radarCol.appendChild(chartWrap);
  radarCol.appendChild(playersRow);

  const body = document.createElement("div");
  body.className = "keynote-drilldown__body";
  const bars = document.createElement("div");
  bars.className = "keynote-drilldown__bars";
  bars.appendChild(buildKeynoteFactorBars(entry, players));
  body.appendChild(radarCol);
  body.appendChild(bars);
  slide.appendChild(body);

  const footer = document.createElement("footer");
  footer.className = "keynote-drilldown__footer";
  footer.innerHTML =
    '<p class="keynote-footnote">Per 90 (win % and scores keep their own units). Bar length is scaled to the highest player on this slide, not a 100% league rank.</p>';
  slide.appendChild(footer);
  return slide;
}

async function exportPositionFullPdf(position) {
  const ids = [...selectedPlayerIds(position)];
  if (ids.length < minComparePlayers()) {
    setStatus("Select at least two players before a full export.", "error");
    return;
  }
  if (!window.PortValeWysiwygExport?.captureSlideHtmlPages) {
    setStatus("PDF exporter failed to load — refresh and try again.", "error");
    return;
  }

  const comparison = state.deck?.comparisons?.find((item) => item.position === position);
  const frame = document.querySelector(
    `#comparison-${position} .comparison-export-target .comparison-frame--keynote`
  );
  if (!comparison || !frame) {
    setStatus("That comparison slide is not on screen yet.", "error");
    return;
  }

  const label = comparison.positionLabel || "this position";
  document.querySelectorAll(".comparison-picker__export").forEach((button) => {
    button.disabled = true;
  });
  els.exportPdfBtn.disabled = true;
  setStatus(`Building Player Comparison PDF for ${label}…`, "loading");

  const host = document.createElement("div");
  host.style.cssText =
    "position:fixed;left:-14000px;top:0;width:1920px;height:1080px;overflow:hidden;pointer-events:none;";
  document.body.appendChild(host);

  try {
    const wysiwyg = window.PortValeWysiwygExport;
    const front = await wysiwyg.captureSlideHtmlPages({
      slides: [frame],
      background: "#0d0d0d",
      onProgress: (message) => setStatus(message, "loading"),
    });

    let drilldownPages = { htmlPages: [], htmlFilenames: [] };
    try {
      setStatus("Pulling radar and factor charts…", "loading");
      const cacheKey = chartsCacheKey(position, ids);
      let charts = state.charts.get(cacheKey);
      if (!charts) {
        const payload = {
          position,
          player_ids: ids,
          min_minutes: Number(els.minMinutes.value || 0),
        };
        const season = selectedSeason();
        if (season) payload.season = season;
        charts = await fetchJson("/api/squad-review/charts", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        state.charts.set(cacheKey, charts);
      }
      const drilldowns = charts.profile_drilldowns || [];
      const slides = drilldowns
        .filter((entry) => (entry.labels || entry.bar_labels || []).length)
        .map((entry) =>
          buildPlayerComparisonDrilldownSlide(comparison, entry, charts.players || [])
        );
      slides.forEach((slide) => host.appendChild(slide));
      if (slides.length) {
        drilldownPages = await wysiwyg.captureSlideHtmlPages({
          slides,
          forceNativeSize: true,
          nativeWidth: 1920,
          nativeHeight: 1080,
          background: "#0b0b0b",
          onProgress: (message) => setStatus(message, "loading"),
        });
      }
    } catch (chartError) {
      if (!front.htmlPages.length) throw chartError;
    }

    const htmlPages = [...front.htmlPages, ...drilldownPages.htmlPages];
    if (!htmlPages.length) {
      throw new Error("No slides were ready to export.");
    }
    setStatus("Screenshotting Player Comparison slides in Chrome…", "loading");
    const shortLabel = String(comparison.positionShortLabel || label)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    await wysiwyg.downloadPdf({
      htmlPages,
      htmlFilenames: [...front.htmlFilenames, ...drilldownPages.htmlFilenames],
      filename: `port-vale-${shortLabel || "comparison"}-comparison-full.pdf`,
      documentTitle: `${label} Player Comparison`,
      background: "#0b0b0b",
    });
    setStatus("");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    host.remove();
    updateActionState();
  }
}

async function init() {
  state.season = "26/27";
  const metaPromise = fetchJson("/api/squad-review/meta")
    .then((meta) => {
      state.meta = meta;
      state.season = meta.defaultSeason || meta.season || state.season;
      els.minMinutes.value = String(meta.defaultMinMinutes ?? 0);
      renderSeasonToggle();
    })
    .catch((error) => {
      if (!state.deck?.comparisons?.length) {
        setStatus(error.message, "error");
      }
    });
  await Promise.all([metaPromise, loadAllComparisons()]);
}

els.minMinutes.addEventListener("change", loadAllComparisons);
els.seasonToggle?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-season]");
  if (!button) return;
  setSeason(button.dataset.season);
});
els.refreshBtn.addEventListener("click", () => loadAllComparisons({ forceRefresh: true }));
els.exportBtn.addEventListener("click", exportAllSlidesPng);
els.exportPdfBtn.addEventListener("click", exportAllPositionsPdf);

setInterval(() => {
  if (state.loading || document.hidden) return;
  loadAllComparisons();
}, AUTO_REFRESH_MS);

init();
