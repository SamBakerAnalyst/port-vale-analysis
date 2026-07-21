const STORAGE_KEY = "squad-planner:v3";
const LEGACY_STORAGE_KEYS = ["squad-planner:v2", "squad-planner:v1"];
const MAX_PLAYERS_PER_POSITION = 5;
const SEARCH_MIN_CHARS = 3;
const SEARCH_DEBOUNCE_MS = 300;

const PLAYER_LABELS = [
  "young player",
  "potential asset",
  "prime player",
  "experienced player",
  "in on loan",
];

const LABEL_CLASS = {
  "young player": "player-row--young",
  "potential asset": "player-row--potential",
  "prime player": "player-row--prime",
  "experienced player": "player-row--experienced",
  "in on loan": "player-row--loan",
};

const LABEL_BOX_CLASS = {
  "young player": "position-slot__box--young",
  "potential asset": "position-slot__box--potential",
  "prime player": "position-slot__box--prime",
  "experienced player": "position-slot__box--experienced",
  "in on loan": "position-slot__box--loan",
};

const LABEL_SHORT = {
  "young player": "Y",
  "potential asset": "P",
  "prime player": "★",
  "experienced player": "E",
  "in on loan": "L",
};

// The backend only has generic CB/CM roles (CENTRAL_DEFENDER / CENTRAL_MIDFIELD).
// This UI splits them into left/right boxes for planning purposes, while mapping
// requests back to the same backend role so profile scores still work.
const POSITION_ALIASES = {
  LEFT_CENTRAL_DEFENDER: "CENTRAL_DEFENDER",
  RIGHT_CENTRAL_DEFENDER: "CENTRAL_DEFENDER",
  LEFT_CENTRAL_MIDFIELD: "CENTRAL_MIDFIELD",
  RIGHT_CENTRAL_MIDFIELD: "CENTRAL_MIDFIELD",
};

const POSITION_UI_META = {
  LEFT_CENTRAL_DEFENDER: { shortLabel: "LCB", label: "Left centre back" },
  RIGHT_CENTRAL_DEFENDER: { shortLabel: "RCB", label: "Right centre back" },
  LEFT_CENTRAL_MIDFIELD: { shortLabel: "LCM", label: "Left centre mid" },
  RIGHT_CENTRAL_MIDFIELD: { shortLabel: "RCM", label: "Right centre mid" },
};

function profileHaystack(profile) {
  return `${profile.apiName || ""} ${profile.label || ""}`.toUpperCase();
}

function profileMatches(profile, needle) {
  return profileHaystack(profile).includes(String(needle).toUpperCase());
}

function filterProfilesForSlot(positionId, profiles) {
  const list = profiles || [];

  if (positionId === "LEFT_CENTRAL_DEFENDER") {
    return list.filter((profile) => !profileMatches(profile, "RIGHT SIDE DUELER"));
  }
  if (positionId === "RIGHT_CENTRAL_DEFENDER") {
    return list.filter((profile) => !profileMatches(profile, "LEFT SIDE DUELER"));
  }
  if (positionId === "DEFENSE_MIDFIELD") {
    return list.filter((profile) => !profileMatches(profile, "RUNNING THREAT"));
  }
  if (positionId === "LEFT_CENTRAL_MIDFIELD" || positionId === "RIGHT_CENTRAL_MIDFIELD") {
    const cmProfiles = state.meta?.positions?.find((p) => p.id === "CENTRAL_MIDFIELD")?.profiles;
    return cmProfiles?.length ? cmProfiles : list;
  }

  return list;
}

function profilesForSlot(positionId) {
  const direct = positionMeta(positionId);
  if (direct?.profiles?.length) {
    return filterProfilesForSlot(positionId, direct.profiles);
  }

  const aliasId = POSITION_ALIASES[positionId];
  if (aliasId) {
    const aliased = positionMeta(aliasId);
    if (aliased?.profiles?.length) {
      return filterProfilesForSlot(positionId, aliased.profiles);
    }
  }

  return [];
}

const DEFAULT_FORMATIONS = {
  "4-3-3": [
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "LEFT_CENTRAL_DEFENDER",
    "RIGHT_CENTRAL_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "DEFENSE_MIDFIELD",
    "LEFT_CENTRAL_MIDFIELD",
    "RIGHT_CENTRAL_MIDFIELD",
    "LEFT_WINGER",
    "CENTER_FORWARD",
    "RIGHT_WINGER",
  ],
  "4-4-2": [
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "LEFT_CENTRAL_DEFENDER",
    "RIGHT_CENTRAL_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "LEFT_WINGER",
    "LEFT_CENTRAL_MIDFIELD",
    "RIGHT_CENTRAL_MIDFIELD",
    "RIGHT_WINGER",
    "CENTER_FORWARD",
  ],
  "4-2-3-1": [
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "LEFT_CENTRAL_DEFENDER",
    "RIGHT_CENTRAL_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "DEFENSE_MIDFIELD",
    "LEFT_WINGER",
    "ATTACKING_MIDFIELD",
    "RIGHT_WINGER",
    "CENTER_FORWARD",
  ],
  "5-3-2": [
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "LEFT_CENTRAL_DEFENDER",
    "CENTRAL_DEFENDER",
    "RIGHT_CENTRAL_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "DEFENSE_MIDFIELD",
    "LEFT_CENTRAL_MIDFIELD",
    "CENTRAL_MIDFIELD",
    "RIGHT_CENTRAL_MIDFIELD",
    "CENTER_FORWARD",
  ],
  "3-5-2": [
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "LEFT_CENTRAL_DEFENDER",
    "CENTRAL_DEFENDER",
    "RIGHT_CENTRAL_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "DEFENSE_MIDFIELD",
    "LEFT_CENTRAL_MIDFIELD",
    "CENTRAL_MIDFIELD",
    "RIGHT_CENTRAL_MIDFIELD",
    "CENTER_FORWARD",
  ],
  "5-2-2-1": [
    "GOALKEEPER",
    "LEFT_WINGBACK_DEFENDER",
    "LEFT_CENTRAL_DEFENDER",
    "CENTRAL_DEFENDER",
    "RIGHT_CENTRAL_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "DEFENSE_MIDFIELD",
    "CENTRAL_MIDFIELD",
    "CENTER_FORWARD",
  ],
};

const FORMATION_LINES = {
  "4-3-3": [
    { line: "pitch-line--3-wide", positions: ["LEFT_WINGER", "CENTER_FORWARD", "RIGHT_WINGER"] },
    {
      line: "pitch-line--3-inset",
      positions: ["LEFT_CENTRAL_MIDFIELD", "DEFENSE_MIDFIELD", "RIGHT_CENTRAL_MIDFIELD"],
    },
    {
      line: "pitch-line--4",
      positions: [
        "LEFT_WINGBACK_DEFENDER",
        "LEFT_CENTRAL_DEFENDER",
        "RIGHT_CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
      ],
    },
    { line: "pitch-line--1", positions: ["GOALKEEPER"] },
  ],
  "4-4-2": [
    { line: "pitch-line--1", positions: ["CENTER_FORWARD"] },
    {
      line: "pitch-line--4",
      positions: ["LEFT_WINGER", "LEFT_CENTRAL_MIDFIELD", "RIGHT_CENTRAL_MIDFIELD", "RIGHT_WINGER"],
    },
    {
      line: "pitch-line--4",
      positions: [
        "LEFT_WINGBACK_DEFENDER",
        "LEFT_CENTRAL_DEFENDER",
        "RIGHT_CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
      ],
    },
    { line: "pitch-line--1", positions: ["GOALKEEPER"] },
  ],
  "4-2-3-1": [
    { line: "pitch-line--1", positions: ["CENTER_FORWARD"] },
    { line: "pitch-line--3-wide", positions: ["LEFT_WINGER", "ATTACKING_MIDFIELD", "RIGHT_WINGER"] },
    { line: "pitch-line--1", positions: ["DEFENSE_MIDFIELD"] },
    {
      line: "pitch-line--4",
      positions: [
        "LEFT_WINGBACK_DEFENDER",
        "LEFT_CENTRAL_DEFENDER",
        "RIGHT_CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
      ],
    },
    { line: "pitch-line--1", positions: ["GOALKEEPER"] },
  ],
  "5-3-2": [
    { line: "pitch-line--1", positions: ["CENTER_FORWARD"] },
    {
      line: "pitch-line--3",
      positions: ["LEFT_CENTRAL_MIDFIELD", "CENTRAL_MIDFIELD", "RIGHT_CENTRAL_MIDFIELD"],
    },
    { line: "pitch-line--1", positions: ["DEFENSE_MIDFIELD"] },
    {
      line: "pitch-line--5",
      positions: [
        "LEFT_WINGBACK_DEFENDER",
        "LEFT_CENTRAL_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
      ],
    },
    { line: "pitch-line--1", positions: ["GOALKEEPER"] },
  ],
  "3-5-2": [
    { line: "pitch-line--1", positions: ["CENTER_FORWARD"] },
    {
      line: "pitch-line--3",
      positions: ["LEFT_CENTRAL_MIDFIELD", "CENTRAL_MIDFIELD", "RIGHT_CENTRAL_MIDFIELD"],
    },
    { line: "pitch-line--1", positions: ["DEFENSE_MIDFIELD"] },
    {
      line: "pitch-line--5",
      positions: [
        "LEFT_WINGBACK_DEFENDER",
        "LEFT_CENTRAL_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
      ],
    },
    { line: "pitch-line--1", positions: ["GOALKEEPER"] },
  ],
  "5-2-2-1": [
    { line: "pitch-line--1", positions: ["CENTER_FORWARD"] },
    { line: "pitch-line--2", positions: ["CENTRAL_MIDFIELD", "DEFENSE_MIDFIELD"] },
    {
      line: "pitch-line--5",
      positions: [
        "LEFT_WINGBACK_DEFENDER",
        "LEFT_CENTRAL_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
      ],
    },
    { line: "pitch-line--1", positions: ["GOALKEEPER"] },
  ],
};

function getFormationLines() {
  return FORMATION_LINES[state.formation] || FORMATION_LINES["4-3-3"];
}

function positionLookup(positions) {
  return Object.fromEntries(positions.map((position) => [position.id, position]));
}

const TAB_TITLES = {
  current: "Current Squad",
  shadow: "Shadow Squad",
};

const state = {
  meta: null,
  formation: "4-3-3",
  activeTab: "current",
  squads: {
    current: {},
    shadow: {},
  },
  selectedPosition: null,
  selectedSearchPlayer: null,
  searchResults: [],
  loading: false,
};

const els = {
  pageSubtitle: document.getElementById("pageSubtitle"),
  formationSelect: document.getElementById("formationSelect"),
  tabCurrent: document.getElementById("tabCurrent"),
  tabShadow: document.getElementById("tabShadow"),
  playerSearch: document.getElementById("playerSearch"),
  searchResults: document.getElementById("searchResults"),
  targetPosition: document.getElementById("targetPosition"),
  addPlayerBtn: document.getElementById("addPlayerBtn"),
  statusBanner: document.getElementById("statusBanner"),
  pitchTitle: document.getElementById("pitchTitle"),
  pitch: document.getElementById("pitch"),
  gapAnalysis: document.getElementById("gapAnalysis"),
  gapSubtitle: document.getElementById("gapSubtitle"),
  clearBtn: document.getElementById("clearBtn"),
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

function normalizeMeta(raw) {
  const meta = { ...raw };
  const lookupFromServer = Object.fromEntries((meta.positions || []).map((p) => [p.id, p]));
  const positions = [...(meta.positions || [])];
  let lookup = { ...lookupFromServer };

  function maybeAddSplitPosition(derivedId, baseId) {
    if (lookup[derivedId]) return;
    const base = lookup[baseId];
    if (!base) return;

    const ui = POSITION_UI_META[derivedId] || {
      shortLabel: derivedId.slice(0, 2).toUpperCase(),
      label: derivedId.replace(/_/g, " ").toLowerCase(),
    };
    positions.push({
      id: derivedId,
      shortLabel: ui.shortLabel,
      label: ui.label,
      profiles: filterProfilesForSlot(derivedId, base.profiles || []),
    });
    lookup = Object.fromEntries(positions.map((p) => [p.id, p]));
  }

  maybeAddSplitPosition("LEFT_CENTRAL_DEFENDER", "CENTRAL_DEFENDER");
  maybeAddSplitPosition("RIGHT_CENTRAL_DEFENDER", "CENTRAL_DEFENDER");
  maybeAddSplitPosition("LEFT_CENTRAL_MIDFIELD", "CENTRAL_MIDFIELD");
  maybeAddSplitPosition("RIGHT_CENTRAL_MIDFIELD", "CENTRAL_MIDFIELD");

  meta.positions = positions;
  lookup = Object.fromEntries(positions.map((p) => [p.id, p]));

  meta.formations = Object.entries(DEFAULT_FORMATIONS).map(([id, positionIds]) => ({
    id,
    label: id,
    positions: positionIds.map((positionId) => {
      const known = lookup[positionId];
      if (known) {
        return { id: known.id, shortLabel: known.shortLabel, label: known.label };
      }
      return {
        id: positionId,
        shortLabel: positionId.slice(0, 2).toUpperCase(),
        label: positionId.replace(/_/g, " ").toLowerCase(),
      };
    }),
  }));

  meta.defaultFormation = meta.defaultFormation || meta.formation || "4-3-3";
  meta.playerLabels = PLAYER_LABELS;
  return meta;
}

function activeFormationMeta() {
  return (
    state.meta?.formations?.find((item) => item.id === state.formation) ||
    state.meta?.formations?.[0] ||
    null
  );
}

function positionMeta(positionId) {
  return state.meta?.positions?.find((item) => item.id === positionId) || null;
}

function apiPositionForBox(positionId) {
  return POSITION_ALIASES[positionId] || positionId;
}

function formationPositionsWithProfiles() {
  const formation = activeFormationMeta();
  return (formation?.positions || []).map((slot) => {
    const full = positionMeta(slot.id);
    const profiles = profilesForSlot(slot.id);
    return full ? { ...full, profiles } : { ...slot, profiles };
  });
}

function buildFormationLines(positions) {
  const lookup = positionLookup(positions);
  return getFormationLines()
    .map((lineDef) => ({
      ...lineDef,
      positions: lineDef.positions.map((id) => lookup[id]).filter(Boolean),
    }))
    .filter((lineDef) => lineDef.positions.length);
}

function activeSquad() {
  return state.squads[state.activeTab] || {};
}

function playersForPosition(positionId) {
  return activeSquad()[positionId] || [];
}

function initSquadForFormation(formationId, existing = null) {
  const formation =
    state.meta?.formations?.find((item) => item.id === formationId) || activeFormationMeta();
  const squad = {};
  (formation?.positions || []).forEach((position) => {
    squad[position.id] = existing?.[position.id] ? [...existing[position.id]] : [];
  });
  return squad;
}

function initSquadsFromMeta() {
  state.squads.current = initSquadForFormation(state.formation);
  state.squads.shadow = initSquadForFormation(state.formation);
}

function migrateSavedPlayers(savedSquad) {
  const migrated = initSquadForFormation(state.formation);
  if (!savedSquad || typeof savedSquad !== "object") return migrated;

  const formatPlayer = (player) => ({
    id: player.id || crypto.randomUUID(),
    playerKey: player.playerKey || "",
    name: player.name || "Unknown",
    age: player.age ?? null,
    club: player.club || "",
    league: player.league || "",
    season: player.season || "",
    minutes: player.minutes || 0,
    iterationId: player.iterationId ?? null,
    impectPlayerId: player.impectPlayerId ?? null,
    profileScores: player.profileScores || {},
    photoDataUrl: player.photoDataUrl || null,
    label: player.label || null,
  });

  Object.keys(migrated).forEach((positionId) => {
    const players = savedSquad[positionId];
    if (!Array.isArray(players)) return;
    migrated[positionId] = players
      .slice(0, MAX_PLAYERS_PER_POSITION)
      .map((player) => formatPlayer(player));
  });

  // Best-effort migration: older saved squads only had generic CENTRAL_DEFENDER and
  // CENTRAL_MIDFIELD keys. Split them across left/right boxes for the current formation.
  const formation =
    state.meta?.formations?.find((item) => item.id === state.formation) ||
    activeFormationMeta();
  const slotIdsInOrder = (formation?.positions || []).map((p) => p.id);

  function splitFromBase(baseId, leftId, rightId) {
    if (!Array.isArray(savedSquad[baseId]) || !savedSquad[baseId].length) return;

    const basePlayers = savedSquad[baseId];
    const slotIdsToFill = [];
    slotIdsInOrder.forEach((id) => {
      if (id === baseId || id === leftId || id === rightId) {
        if (!slotIdsToFill.includes(id)) slotIdsToFill.push(id);
      }
    });
    if (!slotIdsToFill.length) return;

    slotIdsToFill.forEach((slotId, slotIndex) => {
      const hasSavedForSlot = Array.isArray(savedSquad[slotId]) && savedSquad[slotId].length;
      if (hasSavedForSlot) return; // keep already-existing slot values

      const start = slotIndex * MAX_PLAYERS_PER_POSITION;
      const end = start + MAX_PLAYERS_PER_POSITION;
      const slice = basePlayers.slice(start, end);
      migrated[slotId] = slice.map((player) => formatPlayer(player));
    });
  }

  splitFromBase("CENTRAL_DEFENDER", "LEFT_CENTRAL_DEFENDER", "RIGHT_CENTRAL_DEFENDER");
  splitFromBase("CENTRAL_MIDFIELD", "LEFT_CENTRAL_MIDFIELD", "RIGHT_CENTRAL_MIDFIELD");

  return migrated;
}

function loadFromStorage() {
  try {
    const keys = [STORAGE_KEY, ...LEGACY_STORAGE_KEYS];
    const raw = keys.map((key) => localStorage.getItem(key)).find(Boolean);
    if (!raw) return;

    const saved = JSON.parse(raw);

    if (saved.formation && state.meta?.formations?.some((item) => item.id === saved.formation)) {
      state.formation = saved.formation;
    }

    if (saved.activeTab === "current" || saved.activeTab === "shadow") {
      state.activeTab = saved.activeTab;
    }

    if (saved.squads?.current || saved.squads?.shadow) {
      state.squads.current = migrateSavedPlayers(saved.squads.current);
      state.squads.shadow = migrateSavedPlayers(saved.squads.shadow);
    } else if (saved.squad) {
      state.squads.current = migrateSavedPlayers(saved.squad);
      state.squads.shadow = initSquadForFormation(state.formation);
    }

    if (saved.selectedPosition) {
      state.selectedPosition = saved.selectedPosition;
    }
  } catch {
    // ignore corrupt storage
  }
}

function saveToStorage() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      formation: state.formation,
      activeTab: state.activeTab,
      squads: state.squads,
      selectedPosition: state.selectedPosition,
      savedAt: new Date().toISOString(),
    })
  );
}

function nextLabel(currentLabel) {
  const labels = state.meta?.playerLabels || PLAYER_LABELS;
  if (!currentLabel) return labels[0];
  const index = labels.indexOf(currentLabel);
  if (index === -1) return labels[0];
  return labels[(index + 1) % labels.length];
}

function scoreColorClass(value) {
  if (value == null || Number.isNaN(value)) return "gap-profile__value--low";
  if (value >= 66) return "gap-profile__value--high";
  if (value >= 33) return "gap-profile__value--mid";
  return "gap-profile__value--low";
}

function scoreBarColor(value) {
  if (value == null || Number.isNaN(value)) return "var(--red)";
  if (value >= 66) return "var(--green)";
  if (value >= 33) return "var(--amber)";
  return "var(--red)";
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

function overallAverage(averages) {
  const values = Object.values(averages).filter((value) => value != null);
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function updateTabUi() {
  const isCurrent = state.activeTab === "current";
  els.tabCurrent.classList.toggle("tab-bar__tab--active", isCurrent);
  els.tabCurrent.setAttribute("aria-selected", String(isCurrent));
  els.tabShadow.classList.toggle("tab-bar__tab--active", !isCurrent);
  els.tabShadow.setAttribute("aria-selected", String(!isCurrent));
  els.pitchTitle.textContent = `${state.formation} · ${TAB_TITLES[state.activeTab]}`;
  els.pageSubtitle.textContent = isCurrent
    ? "Build your current squad · profile gap analysis on the right · click names to cycle labels"
    : "Plan potential signings · profile gap analysis on the right · click names to cycle labels";
}

function renderGapAnalysis() {
  const positions = formationPositionsWithProfiles();
  els.gapAnalysis.innerHTML = "";
  els.gapAnalysis.className = "gap-analysis gap-analysis--formation";

  if (!positions.length) {
    els.gapAnalysis.className = "gap-analysis";
    els.gapAnalysis.innerHTML = `<p class="gap-empty">Loading positions…</p>`;
    return;
  }

  const activeLabel = state.selectedPosition
    ? positionMeta(state.selectedPosition)?.label
    : null;
  els.gapSubtitle.textContent = activeLabel
    ? `Showing ${activeLabel} · profile averages across assigned players`
    : "Profile averages in formation · click a position to select";

  const lines = buildFormationLines(positions);

  lines.forEach((lineDef) => {
    const line = document.createElement("div");
    line.className = `gap-line ${lineDef.line}`;

    lineDef.positions.forEach((position) => {
      const players = playersForPosition(position.id);
      const profiles = position.profiles || [];
      const averages = averageProfileScores(players, profiles);
      const overall = overallAverage(averages);
      const isActive = position.id === state.selectedPosition;

      const slot = document.createElement("div");
      slot.className = "gap-slot";

      const section = document.createElement("section");
      section.className = `gap-position${isActive ? " gap-position--active" : ""}`;
      section.dataset.position = position.id;
      section.setAttribute("role", "button");
      section.tabIndex = 0;
      section.title = `Select ${position.label}`;

      const overallText = overall == null ? "—" : `${Math.round(overall)}%`;

      const head = document.createElement("div");
      head.className = "gap-position__head";
      head.innerHTML = `
        <span class="gap-position__title">${position.shortLabel}</span>
        <span class="gap-position__avg">${overallText}</span>
      `;

      const profilesWrap = document.createElement("div");
      profilesWrap.className = "gap-profiles";

      if (!profiles.length) {
        profilesWrap.innerHTML = `<p class="gap-empty gap-empty--inline">No benchmarks</p>`;
      } else {
        profiles.forEach((profile) => {
          const value = averages[profile.apiName];
          const display = value == null ? "—" : `${Math.round(value)}%`;
          const width = value == null ? 0 : Math.max(0, Math.min(100, value));

          const rowEl = document.createElement("div");
          rowEl.className = "gap-profile";
          rowEl.innerHTML = `
            <span class="gap-profile__label">${profile.label}</span>
            <div class="gap-profile__bar-wrap">
              <div class="gap-profile__bar" aria-hidden="true">
                <div class="gap-profile__fill" style="width:${width}%;background:${scoreBarColor(value)}"></div>
              </div>
              <span class="gap-profile__value ${scoreColorClass(value)}">${display}</span>
            </div>
          `;
          profilesWrap.appendChild(rowEl);
        });
      }

      section.appendChild(head);
      section.appendChild(profilesWrap);
      section.addEventListener("click", () => selectPosition(position.id));
      section.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectPosition(position.id);
        }
      });

      slot.appendChild(section);
      line.appendChild(slot);
    });

    els.gapAnalysis.appendChild(line);
  });
}

function renderPlayerCard(positionId, player, index) {
  const row = document.createElement("div");
  row.className = "player-row";
  if (index === 0) row.classList.add("player-row--first");
  if (player.label && LABEL_CLASS[player.label]) {
    row.classList.add(LABEL_CLASS[player.label]);
  } else {
    row.classList.add("player-row--neutral");
  }
  row.dataset.position = positionId;
  row.dataset.index = String(index);

  const icon = document.createElement("div");
  icon.className = "player-row__icon";
  icon.tabIndex = 0;
  icon.title = "Click then paste headshot (Ctrl/Cmd+V)";
  icon.setAttribute("role", "button");
  icon.setAttribute("aria-label", `Headshot for ${player.name}. Paste image from clipboard.`);

  if (player.photoDataUrl) {
    const img = document.createElement("img");
    img.src = player.photoDataUrl;
    img.alt = "";
    icon.appendChild(img);
  } else if (player.label && LABEL_SHORT[player.label]) {
    const mark = document.createElement("span");
    mark.className = "player-row__mark";
    mark.textContent = LABEL_SHORT[player.label];
    icon.appendChild(mark);
  } else {
    const mark = document.createElement("span");
    mark.className = "player-row__mark player-row__mark--muted";
    mark.textContent = "·";
    icon.appendChild(mark);
  }

  icon.addEventListener("paste", (event) => {
    event.preventDefault();
    event.stopPropagation();
    handlePhotoPaste(positionId, index, event);
  });
  icon.addEventListener("click", (event) => event.stopPropagation());

  const mainBtn = document.createElement("button");
  mainBtn.type = "button";
  mainBtn.className = "player-row__main";
  mainBtn.title = [player.name, player.club, player.league].filter(Boolean).join(" · ");
  mainBtn.setAttribute("aria-label", `Cycle label for ${player.name}`);

  const nameEl = document.createElement("span");
  nameEl.className = "player-row__name";
  nameEl.textContent = player.name;
  mainBtn.appendChild(nameEl);

  const metaParts = [];
  if (player.age != null) metaParts.push(`${player.age}y`);
  if (player.minutes) metaParts.push(`${player.minutes}′`);
  if (metaParts.length) {
    const metaEl = document.createElement("span");
    metaEl.className = "player-row__meta";
    metaEl.textContent = metaParts.join(" · ");
    mainBtn.appendChild(metaEl);
  }

  mainBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    cyclePlayerLabel(positionId, index);
  });

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "player-row__remove";
  removeBtn.title = "Remove player";
  removeBtn.setAttribute("aria-label", `Remove ${player.name}`);
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    removePlayer(positionId, index);
  });

  row.addEventListener("click", (event) => event.stopPropagation());

  row.appendChild(icon);
  row.appendChild(mainBtn);
  row.appendChild(removeBtn);
  return row;
}

function cyclePlayerLabel(positionId, index) {
  const players = playersForPosition(positionId);
  const player = players[index];
  if (!player) return;
  player.label = nextLabel(player.label);
  saveToStorage();
  renderPitch();
}

function handlePhotoPaste(positionId, index, event) {
  const items = event.clipboardData?.items;
  if (!items) return;

  for (const item of items) {
    if (!item.type.startsWith("image/")) continue;
    const file = item.getAsFile();
    if (!file) continue;

    const reader = new FileReader();
    reader.onload = () => {
      const players = playersForPosition(positionId);
      if (!players[index]) return;
      players[index].photoDataUrl = reader.result;
      saveToStorage();
      renderPitch();
    };
    reader.readAsDataURL(file);
    setStatus("Headshot updated.", "success");
    return;
  }
  setStatus("Clipboard does not contain an image.", "warn");
}

function removePlayer(positionId, index) {
  const players = playersForPosition(positionId);
  players.splice(index, 1);
  saveToStorage();
  renderPitch();
}

function createPositionSlot(position) {
  const players = playersForPosition(position.id);
  const isSelected = state.selectedPosition === position.id;

  const slot = document.createElement("div");
  slot.className = [
    "position-slot",
    isSelected ? "position-slot--selected" : "",
    players.length ? "" : "position-slot--empty",
  ]
    .filter(Boolean)
    .join(" ");

  const box = document.createElement("div");
  box.className = "position-slot__box";
  if (players[0]?.label && LABEL_BOX_CLASS[players[0].label]) {
    box.classList.add(LABEL_BOX_CLASS[players[0].label]);
  }
  box.dataset.position = position.id;
  box.addEventListener("click", () => selectPosition(position.id));

  const label = document.createElement("div");
  label.className = "position-slot__label";
  label.innerHTML = `
    <span class="position-slot__name">${position.shortLabel}</span>
    <span class="position-slot__count">${players.length}/${MAX_PLAYERS_PER_POSITION}</span>
  `;

  const list = document.createElement("div");
  list.className = "position-slot__players";

  if (!players.length) {
    const empty = document.createElement("p");
    empty.className = "position-slot__empty";
    empty.textContent = "No players";
    list.appendChild(empty);
  } else {
    players.forEach((player, index) => {
      list.appendChild(renderPlayerCard(position.id, player, index));
    });
  }

  box.appendChild(label);
  box.appendChild(list);
  slot.appendChild(box);
  return slot;
}

function renderPitch() {
  const positions = formationPositionsWithProfiles();
  els.pitch.innerHTML = "";

  if (!positions.length) {
    els.pitch.innerHTML = `<p class="gap-empty">Loading positions…</p>`;
    return;
  }

  const lines = buildFormationLines(positions);

  lines.forEach((lineDef) => {
    const line = document.createElement("div");
    line.className = `pitch-line ${lineDef.line}`;

    lineDef.positions.forEach((position) => {
      line.appendChild(createPositionSlot(position));
    });

    els.pitch.appendChild(line);
  });

  renderGapAnalysis();
}

function selectPosition(positionId) {
  state.selectedPosition = positionId;
  els.targetPosition.value = positionId;
  renderPitch();
}

function populateFormationSelect() {
  const formations = state.meta?.formations || [];
  els.formationSelect.innerHTML = formations
    .map(
      (formation) =>
        `<option value="${formation.id}"${formation.id === state.formation ? " selected" : ""}>${formation.label}</option>`
    )
    .join("");
}

function populatePositionSelect() {
  const positions = formationPositionsWithProfiles();
  els.targetPosition.innerHTML = positions
    .map(
      (position) =>
        `<option value="${position.id}">${position.shortLabel} — ${position.label}</option>`
    )
    .join("");

  if (!state.selectedPosition && positions.length) {
    state.selectedPosition = positions[0].id;
  }
  if (
    state.selectedPosition &&
    positions.some((position) => position.id === state.selectedPosition)
  ) {
    els.targetPosition.value = state.selectedPosition;
  } else if (positions.length) {
    state.selectedPosition = positions[0].id;
    els.targetPosition.value = state.selectedPosition;
  }
}

function switchTab(tabId) {
  if (tabId !== "current" && tabId !== "shadow") return;
  state.activeTab = tabId;
  updateTabUi();
  populatePositionSelect();
  saveToStorage();
  renderPitch();
}

function changeFormation(formationId) {
  if (formationId === state.formation) return;
  state.formation = formationId;

  ["current", "shadow"].forEach((tab) => {
    state.squads[tab] = initSquadForFormation(formationId, state.squads[tab]);
  });

  populatePositionSelect();
  updateTabUi();
  saveToStorage();
  renderPitch();
  setStatus(`Formation set to ${formationId}.`, "success");
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
      const ageText = player.age != null ? `${player.age} yrs` : null;
      const meta = [ageText, season?.competition_name, season?.club].filter(Boolean).join(" · ");
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
  if (player) {
    els.playerSearch.value = player.name;
  }
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
  const positionId = els.targetPosition.value || state.selectedPosition;
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

  const duplicate = existing.some((entry) => entry.playerKey === player.key);
  if (duplicate) {
    setStatus("Player already in this position.", "warn");
    return;
  }

  state.loading = true;
  els.addPlayerBtn.disabled = true;
  setStatus(`Loading profiles for ${player.name}…`, "loading");

  try {
    const squadId = player.squad_ids_by_iteration?.[String(season.iteration_id)] ?? null;
    const profileData = await fetchJson("/api/squad-planner/player", {
      method: "POST",
      body: JSON.stringify({
        position: apiPositionForBox(positionId),
        player_key: player.key,
        iteration_id: season.iteration_id,
        iteration_ids: chartableIterationIds(player),
        impect_player_id: impectPlayerId,
        squad_id: squadId != null ? Number(squadId) : null,
        name: player.name,
      }),
    });

    existing.push({
      id: profileData.id || crypto.randomUUID(),
      playerKey: profileData.playerKey || player.key,
      name: profileData.name || player.name,
      age: player.age ?? null,
      club: profileData.club,
      league: profileData.league,
      season: profileData.season,
      minutes: profileData.minutes,
      iterationId: profileData.iterationId,
      impectPlayerId: profileData.impectPlayerId,
      profileScores: profileData.profileScores,
      photoDataUrl: null,
      label: null,
    });

    state.selectedPosition = positionId;
    saveToStorage();
    renderPitch();
    setStatus(`${player.name} added to ${positionMeta(positionId)?.label || positionId}.`, "success");
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

function clearActiveSquad() {
  const tabLabel = TAB_TITLES[state.activeTab].toLowerCase();
  if (!confirm(`Clear all players from the ${tabLabel}?`)) return;
  state.squads[state.activeTab] = initSquadForFormation(state.formation);
  saveToStorage();
  renderPitch();
  setStatus(`${TAB_TITLES[state.activeTab]} cleared.`, "success");
}

async function init() {
  try {
    state.meta = normalizeMeta(await fetchJson("/api/squad-planner/meta"));
    state.formation = state.meta.defaultFormation || "4-3-3";
    initSquadsFromMeta();
    loadFromStorage();
    populateFormationSelect();
    populatePositionSelect();
    updateTabUi();
    renderPitch();
    setStatus("");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

els.playerSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => searchPlayers(els.playerSearch.value), SEARCH_DEBOUNCE_MS);
});

els.playerSearch.addEventListener("focus", () => {
  if (state.searchResults.length) {
    els.searchResults.classList.remove("hidden");
  }
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".search-bar__input-wrap")) {
    els.searchResults.classList.add("hidden");
  }
});

els.targetPosition.addEventListener("change", () => {
  state.selectedPosition = els.targetPosition.value;
  renderPitch();
});

els.formationSelect.addEventListener("change", () => {
  changeFormation(els.formationSelect.value);
});

els.tabCurrent.addEventListener("click", () => switchTab("current"));
els.tabShadow.addEventListener("click", () => switchTab("shadow"));

els.addPlayerBtn.addEventListener("click", addSelectedPlayer);
els.clearBtn.addEventListener("click", clearActiveSquad);
els.saveBtn.addEventListener("click", () => {
  saveToStorage();
  setStatus("Squad saved to this browser.", "success");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    els.searchResults.classList.add("hidden");
  }
});

init();
