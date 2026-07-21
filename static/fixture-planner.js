const DEFAULT_SEASON = "26/27";
const ALLOWED_SEASONS = ["26/27", "25/26"];
const ASSIGNMENTS_KEY = "fixture-planner-assignments-v1";

const state = {
  meta: null,
  payload: null,
  season: DEFAULT_SEASON,
  leagues: [],
  staffFilter: "",
  monthFilter: "",
  view: "list",
  hidePast: true,
  loading: false,
  assignments: {},
  enrichment: {},
  enrichmentPending: {},
  assignModal: null,
};

const leagueColors = {
  "League One": "#3d8bfd",
  "League Two": "#34d399",
  "National League": "#fbbf24",
  "Scottish Prem": "#a78bfa",
  PL2: "#f97316",
  "Irish Prem": "#22d3ee",
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  leagueToggle: document.getElementById("leagueToggle"),
  staffFilter: document.getElementById("staffFilter"),
  monthFilter: document.getElementById("monthFilter"),
  summaryPanel: document.getElementById("summaryPanel"),
  calendarRoot: document.getElementById("calendarRoot"),
  listRoot: document.getElementById("listRoot"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  pageSubtitle: document.getElementById("pageSubtitle"),
  hidePastToggle: document.getElementById("hidePastToggle"),
  coveragePanel: document.getElementById("coveragePanel"),
  assignModal: document.getElementById("assignModal"),
  assignModalTitle: document.getElementById("assignModalTitle"),
  assignModalMeta: document.getElementById("assignModalMeta"),
  assignModalStaff: document.getElementById("assignModalStaff"),
  assignModalWatch: document.getElementById("assignModalWatch"),
  assignModalBody: document.getElementById("assignModalBody"),
  assignConfirmBtn: document.getElementById("assignConfirmBtn"),
};

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `fp-status fp-status--${kind}`;
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

function fixtureFromState(id) {
  return (state.payload?.fixtures || []).find((row) => fixtureId(row) === id);
}

async function loadAssignmentsFromServer() {
  try {
    const data = await fetchJson("/api/fixture-planner/assignments");
    if (data.assignments && Object.keys(data.assignments).length) {
      state.assignments = data.assignments;
      localStorage.setItem(ASSIGNMENTS_KEY, JSON.stringify(state.assignments));
      return;
    }
  } catch {
    // fall back to local cache below
  }

  loadAssignments();
  if (Object.keys(state.assignments).length) {
    try {
      await fetchJson("/api/fixture-planner/assignments", {
        method: "PUT",
        body: JSON.stringify({ assignments: state.assignments }),
      });
    } catch {
      // local-only mode
    }
  }
}

function loadAssignments() {
  try {
    state.assignments = JSON.parse(localStorage.getItem(ASSIGNMENTS_KEY) || "{}");
  } catch {
    state.assignments = {};
  }
}

function saveAssignments() {
  localStorage.setItem(ASSIGNMENTS_KEY, JSON.stringify(state.assignments));
}

let persistTimer = null;

function enrichAssignment(id) {
  const fixture = fixtureFromState(id);
  if (!state.assignments[id] || !fixture) return;
  state.assignments[id] = {
    ...state.assignments[id],
    season: state.season,
    league: fixture.league || "",
    home: fixture.home?.name || "",
    away: fixture.away?.name || "",
    date: fixtureDateKey(fixture),
    kickoff_utc: fixture.kickoff_utc || fixture.scheduled_date || null,
  };
}

async function flushPersistQueue() {
  try {
    await fetchJson("/api/fixture-planner/assignments", {
      method: "PUT",
      body: JSON.stringify({ assignments: state.assignments }),
    });
  } catch (error) {
    console.warn("Could not sync assignments to server", error);
  }
}

function schedulePersist() {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(flushPersistQueue, 400);
}

function assignmentFor(fixtureId) {
  return state.assignments[fixtureId] || { staff: "", watch_type: "" };
}

function setAssignment(id, patch) {
  const current = assignmentFor(id);
  const next = { ...current, ...patch };
  if (!next.staff && !next.watch_type) {
    delete state.assignments[id];
  } else {
    state.assignments[id] = next;
    enrichAssignment(id);
  }
  saveAssignments();
  renderSummary();
  renderView();
  persistAssignment(id);
}

async function persistAssignment(id) {
  const assignment = state.assignments[id];
  const fixture = fixtureFromState(id);
  const body = assignment
    ? {
        fixture_id: id,
        staff: assignment.staff || "",
        watch_type: assignment.watch_type || "",
        season: assignment.season || state.season || "",
        league: assignment.league || fixture?.league || "",
        home: assignment.home || fixture?.home?.name || "",
        away: assignment.away || fixture?.away?.name || "",
        date: assignment.date || fixtureDateKey(fixture) || "",
        kickoff_utc: assignment.kickoff_utc || fixture?.kickoff_utc || fixture?.scheduled_date || null,
        watched_players: assignment.watched_players || [],
      }
    : {
        fixture_id: id,
        staff: "",
        watch_type: "",
        watched_players: [],
      };

  try {
    const data = await fetchJson("/api/fixture-planner/assignment", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    if (data.assignments) {
      state.assignments = data.assignments;
      saveAssignments();
    }
    if (data.email?.sent) {
      setStatus(`Assignment saved · email sent to ${data.email.to}`, "ok");
    } else if (data.email && !data.email.sent && data.email.reason) {
      setStatus(`Assignment saved · email not sent: ${data.email.reason}`, "error");
    }
  } catch (error) {
    console.warn("Could not persist assignment", error);
    setStatus(error.message || "Could not save assignment", "error");
    schedulePersist();
  }
}

function formatTime(iso) {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDateLabel(dateKey) {
  if (!dateKey) return "Unknown date";
  const date = new Date(`${dateKey}T12:00:00`);
  return date.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function formatShortDate(dateKey) {
  if (!dateKey) return "";
  const date = new Date(`${dateKey}T12:00:00`);
  return date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function fixtureDateKey(fixture) {
  return fixture.date || (fixture.scheduled_date || "").slice(0, 10);
}

function footballWeekendKey(dateKey) {
  if (!dateKey) return "";
  const date = new Date(`${dateKey}T12:00:00`);
  const day = date.getDay();
  const saturday = new Date(date);
  if (day === 6) {
    // Saturday anchor
  } else if (day === 0) {
    saturday.setDate(date.getDate() - 1);
  } else if (day === 5) {
    saturday.setDate(date.getDate() + 1);
  } else if (day === 1) {
    saturday.setDate(date.getDate() - 2);
  } else {
    return dateKey;
  }
  const year = saturday.getFullYear();
  const month = String(saturday.getMonth() + 1).padStart(2, "0");
  const dayNum = String(saturday.getDate()).padStart(2, "0");
  return `${year}-${month}-${dayNum}`;
}

function formatMonthLabel(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return date.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isCompletedFixture(fixture) {
  return fixture.status === "completed";
}

function renderLineupBlock(label, lineup) {
  if (!lineup?.players?.length) {
    return "";
  }
  const formation = lineup.formation ? ` · ${lineup.formation}` : "";
  const players = lineup.players
    .map((player) => {
      const shirt = player.shirt_number ? `${player.shirt_number} ` : "";
      const pos = player.position ? ` (${player.position})` : "";
      const pxt =
        player.pxt != null ? ` · PXT ${player.pxt}` : "";
      return `<li>${escapeHtml(`${shirt}${player.name}${pos}${pxt}`)}</li>`;
    })
    .join("");
  return `
    <details class="fp-fixture-lineup">
      <summary>${escapeHtml(label)}${formation}</summary>
      <ol class="fp-fixture-lineup__list">${players}</ol>
    </details>
  `;
}

function renderEnrichmentBody(fixture, enrich) {
  if (!enrich) {
    return `<p class="fp-fixture-enrich__hint">Venue, PXT ratings and lineups will load here.</p>`;
  }
  const venue = enrich.venue
    ? `<p class="fp-fixture-enrich__venue">${escapeHtml(enrich.venue)}</p>`
    : "";
  const homePxt = enrich.pxt?.home;
  const awayPxt = enrich.pxt?.away;
  const pxtLine =
    homePxt != null || awayPxt != null
      ? `<p class="fp-fixture-enrich__pxt">PXT <span>${homePxt ?? "—"}</span> – <span>${awayPxt ?? "—"}</span></p>`
      : "";
  const homeName = fixture.home?.name || "Home";
  const awayName = fixture.away?.name || "Away";
  const lineups = [
    renderLineupBlock(homeName, enrich.lineups?.home),
    renderLineupBlock(awayName, enrich.lineups?.away),
  ].join("");
  return `${venue}${pxtLine}${lineups}`;
}

function renderCompletedExtras(fixture) {
  if (!isCompletedFixture(fixture)) {
    return "";
  }
  if (!fixture.match_id) {
    return `<p class="fp-fixture-enrich__hint">Match details need Impect data for this fixture.</p>`;
  }

  const id = fixtureId(fixture);
  const enrich = state.enrichment[id];
  const pending = state.enrichmentPending[id];
  const summaryHint = enrich
    ? [enrich.venue, enrich.pxt?.home != null ? `PXT ${enrich.pxt.home}–${enrich.pxt.away}` : ""]
        .filter(Boolean)
        .join(" · ")
    : pending
      ? "Loading…"
      : "Tap to load venue, PXT & lineups";

  const body = pending
    ? `<p class="fp-fixture-enrich fp-fixture-enrich--loading">Loading lineups &amp; ratings…</p>`
    : `<div class="fp-fixture-enrich">${renderEnrichmentBody(fixture, enrich)}</div>`;

  return `
    <details class="fp-fixture-details"${enrich ? " open" : ""} data-fixture-id="${escapeHtml(id)}">
      <summary class="fp-fixture-details__summary">
        <span class="fp-fixture-details__title">Match details</span>
        <span class="fp-fixture-details__hint">${escapeHtml(summaryHint)}</span>
      </summary>
      ${body}
    </details>
  `;
}

async function loadEnrichmentForIds(ids) {
  const needed = ids.filter((id) => id && !state.enrichment[id] && !state.enrichmentPending[id]).slice(0, 24);
  if (!needed.length) {
    return;
  }

  needed.forEach((id) => {
    state.enrichmentPending[id] = true;
  });
  refreshEnrichmentPanels(needed);

  try {
    const params = new URLSearchParams({
      season: state.season,
      fixture_ids: needed.join(","),
    });
    const data = await fetchJson(`/api/fixture-planner/match-enrichment?${params}`);
    Object.assign(state.enrichment, data.enrichments || {});
  } catch (error) {
    console.warn("Could not load match enrichment", error);
  } finally {
    needed.forEach((id) => {
      delete state.enrichmentPending[id];
    });
    refreshEnrichmentPanels(needed);
  }
}

function refreshEnrichmentPanels(ids) {
  ids.forEach((id) => {
    const details = els.listRoot?.querySelector(`.fp-fixture-details[data-fixture-id="${CSS.escape(id)}"]`);
    if (!details) return;
    const fixture = fixtureFromState(id);
    if (!fixture) return;
    const enrich = state.enrichment[id];
    const pending = state.enrichmentPending[id];
    const body = pending
      ? `<p class="fp-fixture-enrich fp-fixture-enrich--loading">Loading lineups &amp; ratings…</p>`
      : `<div class="fp-fixture-enrich">${renderEnrichmentBody(fixture, enrich)}</div>`;
    const summary = details.querySelector(".fp-fixture-details__hint");
    if (summary) {
      const summaryHint = enrich
        ? [enrich.venue, enrich.pxt?.home != null ? `PXT ${enrich.pxt.home}–${enrich.pxt.away}` : ""]
            .filter(Boolean)
            .join(" · ")
        : pending
          ? "Loading…"
          : "Tap to load venue, PXT & lineups";
      summary.textContent = summaryHint;
    }
    const content = details.querySelector(".fp-fixture-enrich, .fp-fixture-enrich--loading");
    if (content) {
      content.outerHTML = body;
    } else if (details.open) {
      details.insertAdjacentHTML("beforeend", body);
    }
    if (enrich) {
      details.open = true;
    }
  });
}

function fixtureTeams(fixture) {
  const home = fixture.home?.name || "TBC";
  const away = fixture.away?.name || "TBC";
  const score = fixture.score ? ` (${fixture.score})` : "";
  return `${home} vs ${away}${score}`;
}

function fixtureId(fixture) {
  return fixture.fixture_id || `${fixture.league}|${fixture.date}|${fixture.home?.name}|${fixture.away?.name}`;
}

function todayKey() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isValidDateKey(dateKey) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(dateKey || ""));
}

const MAX_UNFILTERED_FIXTURES = 320;

function fixturesForLeagues(all = state.payload?.fixtures || []) {
  const leagues = state.leagues.length ? state.leagues : (state.meta?.default_leagues || []);
  return all.filter((fixture) => leagues.includes(fixture.league));
}

function defaultMonthForPastView() {
  const today = todayKey();
  const dated = fixturesForLeagues()
    .map((fixture) => fixtureDateKey(fixture))
    .filter(isValidDateKey)
    .sort();
  if (!dated.length) {
    return today.slice(0, 7);
  }
  const upcoming = dated.find((dateKey) => dateKey >= today);
  if (upcoming) {
    return upcoming.slice(0, 7);
  }
  return dated[dated.length - 1].slice(0, 7);
}

function visibleFixtures() {
  const all = state.payload?.fixtures || [];
  const today = todayKey();
  let fixtures = fixturesForLeagues(all).filter((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (state.hidePast && isValidDateKey(dateKey) && dateKey < today) {
      return false;
    }
    if (state.monthFilter && dateKey.slice(0, 7) !== state.monthFilter) {
      return false;
    }
    if (state.staffFilter) {
      const assignment = assignmentFor(fixtureId(fixture));
      return assignment.staff === state.staffFilter;
    }
    return true;
  });

  if (!state.hidePast && !state.monthFilter && fixtures.length > MAX_UNFILTERED_FIXTURES) {
    const monthKey = defaultMonthForPastView();
    fixtures = fixtures.filter((fixture) => fixtureDateKey(fixture).slice(0, 7) === monthKey);
  }

  return fixtures;
}

function visibleFixtureHint() {
  if (state.hidePast) {
    const all = fixturesForLeagues();
    const today = todayKey();
    const upcoming = all.filter((fixture) => {
      const dateKey = fixtureDateKey(fixture);
      return !isValidDateKey(dateKey) || dateKey >= today;
    }).length;
    if (!upcoming) {
      return "No upcoming fixtures in this season. Uncheck “Upcoming only” and pick a month to browse past games.";
    }
  }
  if (!state.hidePast && !state.monthFilter) {
    const count = fixturesForLeagues().length;
    if (count > MAX_UNFILTERED_FIXTURES) {
      const monthKey = defaultMonthForPastView();
      return `Showing ${formatMonthLabel(monthKey)} only — pick a month above to browse the full season (${count} fixtures loaded).`;
    }
  }
  return "";
}

function staffTeams() {
  if (state.meta?.staff_teams?.length) {
    return state.meta.staff_teams;
  }
  const fallback = state.meta?.staff || [];
  return fallback.length
    ? [{ id: "recruitment", label: "Recruitment Team", members: fallback }]
    : [
        { id: "recruitment", label: "Recruitment Team", members: [] },
        { id: "coaching", label: "Coaching Team", members: [] },
        { id: "scouting", label: "Scouting Team", members: [] },
      ];
}

function teamSelectOptions(team, selected = "") {
  const members = team?.members || [];
  const emptyLabel = members.length ? "Unassigned" : "No one listed yet";
  return [
    `<option value="">${emptyLabel}</option>`,
    ...members.map(
      (name) =>
        `<option value="${escapeHtml(name)}"${name === selected ? " selected" : ""}>${escapeHtml(name)}</option>`,
    ),
  ].join("");
}

function assignmentControls(fixture) {
  const id = fixtureId(fixture);
  const assignment = assignmentFor(id);
  const watchTypes = state.meta?.watch_types || ["LIVE", "VIDEO"];
  const teams = staffTeams();

  const teamSelects = teams
    .map((team) => {
      const selected = (team.members || []).includes(assignment.staff) ? assignment.staff : "";
      const disabled = !(team.members || []).length ? " disabled" : "";
      return `
        <label class="fp-team-assign">
          <span class="fp-team-assign__label">${escapeHtml(team.label)}</span>
          <select
            class="fp-staff-select fp-team-assign__select"
            data-fixture-id="${id}"
            data-team-id="${escapeHtml(team.id)}"
            aria-label="${escapeHtml(team.label)}"
            ${disabled}
          >
            ${teamSelectOptions(team, selected)}
          </select>
        </label>
      `;
    })
    .join("");

  const watchButtons = watchTypes
    .map((type) => {
      const active = assignment.watch_type === type ? " fp-watch-btn--active" : "";
      const cls = type === "LIVE" ? "fp-watch-btn--live" : "fp-watch-btn--video";
      return `<button type="button" class="fp-watch-btn ${cls}${active}" data-fixture-id="${id}" data-watch="${type}">${type}</button>`;
    })
    .join("");

  const editPlayers =
    assignment.staff
      ? `<button type="button" class="fp-btn fp-btn--ghost fp-assign-edit" data-fixture-id="${id}" data-staff="${escapeHtml(assignment.staff)}">Players</button>`
      : "";

  return `
    <div class="fp-assignment" data-fixture-id="${id}">
      <div class="fp-team-assigns">${teamSelects}</div>
      <div class="fp-watch-toggle">${watchButtons}</div>
      ${editPlayers}
    </div>
  `;
}

function closeAssignModal() {
  state.assignModal = null;
  if (els.assignModal) {
    els.assignModal.classList.add("fp-assign-modal--hidden");
    els.assignModal.setAttribute("aria-hidden", "true");
  }
}

function selectedWatchedPlayersFromModal() {
  if (!els.assignModalBody) return [];
  return [...els.assignModalBody.querySelectorAll('input[type="checkbox"][data-player-id]:checked')].map((input) => ({
    player_id: Number(input.dataset.playerId),
    player_name: input.dataset.playerName || "",
    team: input.dataset.team || "",
    side: input.dataset.side || "",
  }));
}

function renderAssignSquadColumn(side, team) {
  const players = team?.players || [];
  const selected = new Set((state.assignModal?.selectedIds || []).map(String));
  const list = players.length
    ? players
        .map((player) => {
          const checked = selected.has(String(player.player_id)) ? " checked" : "";
          return `
          <li>
            <label class="fp-assign-player">
              <input type="checkbox" data-player-id="${player.player_id}" data-player-name="${escapeHtml(player.player_name || "")}" data-team="${escapeHtml(team?.name || "")}" data-side="${side}"${checked} />
              <span class="fp-assign-player__name">${escapeHtml(player.player_name || "Player")}</span>
            </label>
          </li>
        `;
        })
        .join("")
    : `<li class="fp-assign-modal__empty" style="padding:.65rem">No squad list available</li>`;

  return `
    <section class="fp-assign-squad">
      <header class="fp-assign-squad__head">
        <strong>${escapeHtml(team?.name || (side === "home" ? "Home" : "Away"))}</strong>
        <span class="fp-assign-squad__count">${players.length} players</span>
      </header>
      <ul class="fp-assign-squad__list">${list}</ul>
    </section>
  `;
}

function renderAssignModalBody(squads) {
  if (!els.assignModalBody) return;
  if (!squads) {
    els.assignModalBody.innerHTML = `<p class="fp-assign-modal__loading">Loading squad lists…</p>`;
    return;
  }
  if (!squads.available) {
    els.assignModalBody.innerHTML = `
      <p class="fp-assign-modal__empty">Squad lists aren't available for this fixture yet. You can still assign the scout for a full-game watch.</p>
    `;
    return;
  }
  els.assignModalBody.innerHTML = `
    <div class="fp-assign-squads">
      ${renderAssignSquadColumn("home", squads.home)}
      ${renderAssignSquadColumn("away", squads.away)}
    </div>
  `;
}

function renderAssignModalChrome() {
  const modal = state.assignModal;
  if (!modal) return;
  const fixture = fixtureFromState(modal.fixtureId);
  const home = fixture?.home?.name || modal.home || "Home";
  const away = fixture?.away?.name || modal.away || "Away";
  if (els.assignModalTitle) {
    els.assignModalTitle.textContent = `${home} vs ${away}`;
  }
  if (els.assignModalMeta) {
    const kickoff = formatTime(fixture?.kickoff_utc || fixture?.scheduled_date);
    const dateLabel = formatShortDate(fixtureDateKey(fixture) || modal.date || "");
    els.assignModalMeta.textContent = `${fixture?.league || modal.league || ""} · ${dateLabel} · ${kickoff} · Assigning ${modal.staff}`;
  }
  if (els.assignModalStaff) {
    els.assignModalStaff.textContent = modal.staff;
  }
  if (els.assignModalWatch) {
    const watchTypes = state.meta?.watch_types || ["LIVE", "VIDEO"];
    els.assignModalWatch.innerHTML = watchTypes
      .map((type) => {
        const active = modal.watchType === type ? " fp-watch-btn--active" : "";
        const cls = type === "LIVE" ? "fp-watch-btn--live" : "fp-watch-btn--video";
        return `<button type="button" class="fp-watch-btn ${cls}${active}" data-assign-watch="${type}">${type}</button>`;
      })
      .join("");
  }
}

async function openAssignModal(fixtureIdValue, staffName) {
  const fixture = fixtureFromState(fixtureIdValue);
  if (!fixture || !staffName) return;
  const current = assignmentFor(fixtureIdValue);
  state.assignModal = {
    fixtureId: fixtureIdValue,
    staff: staffName,
    watchType: current.watch_type || "LIVE",
    selectedIds: (current.watched_players || []).map((row) => row.player_id),
    home: fixture.home?.name || "",
    away: fixture.away?.name || "",
    league: fixture.league || "",
    date: fixtureDateKey(fixture),
    squads: null,
  };
  renderAssignModalChrome();
  renderAssignModalBody(null);
  els.assignModal?.classList.remove("fp-assign-modal--hidden");
  els.assignModal?.setAttribute("aria-hidden", "false");

  try {
    const params = new URLSearchParams({
      season: state.season,
      fixture_id: fixtureIdValue,
    });
    const squads = await fetchJson(`/api/fixture-planner/fixture-squads?${params}`);
    if (state.assignModal?.fixtureId !== fixtureIdValue) return;
    state.assignModal.squads = squads;
    renderAssignModalBody(squads);
  } catch (error) {
    if (state.assignModal?.fixtureId !== fixtureIdValue) return;
    els.assignModalBody.innerHTML = `<p class="fp-assign-modal__empty">${escapeHtml(error.message || "Could not load squads.")}</p>`;
  }
}

function confirmAssignModal() {
  const modal = state.assignModal;
  if (!modal) return;
  const watched = selectedWatchedPlayersFromModal();
  setAssignment(modal.fixtureId, {
    staff: modal.staff,
    watch_type: modal.watchType || "LIVE",
    watched_players: watched,
  });
  closeAssignModal();
}

function bindAssignmentEvents(root) {
  root.querySelectorAll(".fp-staff-select").forEach((select) => {
    select.addEventListener("change", () => {
      const id = select.dataset.fixtureId;
      const next = select.value || "";
      const current = assignmentFor(id);
      const teamMembers = [...select.options]
        .map((opt) => opt.value)
        .filter(Boolean);

      if (!next) {
        if (current.staff && teamMembers.includes(current.staff)) {
          setAssignment(id, { staff: "", watched_players: [] });
        } else {
          renderView();
        }
        return;
      }

      openAssignModal(id, next);
      // Keep showing the previous assignee until modal confirms
      renderView();
    });
  });

  root.querySelectorAll(".fp-assign-edit").forEach((btn) => {
    btn.addEventListener("click", () => {
      openAssignModal(btn.dataset.fixtureId, btn.dataset.staff);
    });
  });

  root.querySelectorAll(".fp-watch-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.fixtureId;
      const current = assignmentFor(id);
      const next = current.watch_type === btn.dataset.watch ? "" : btn.dataset.watch;
      setAssignment(id, { watch_type: next });
    });
  });
}

function renderSeasonToggle() {
  const seasons = state.meta?.seasons || ALLOWED_SEASONS;

  els.seasonToggle.innerHTML = seasons
    .map((season) => {
      const active = season === state.season;
      const label = season === "26/27" ? `This season (${season})` : `Last season (${season})`;
      return `<button type="button" class="fp-season-btn${active ? " fp-season-btn--active" : ""}" data-season="${season}"${state.loading ? " disabled" : ""}>${label}</button>`;
    })
    .join("");

  els.seasonToggle.querySelectorAll(".fp-season-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled || btn.classList.contains("fp-season-btn--active")) return;
      state.season = btn.dataset.season;
      state.monthFilter = "";
      loadFixtures();
    });
  });
}

function monthOptionsFromFixtures(fixtures) {
  const months = new Set();
  fixtures.forEach((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (dateKey) months.add(dateKey.slice(0, 7));
  });
  return [...months].sort();
}

function renderMonthFilter() {
  if (!els.monthFilter) return;
  const all = state.payload?.fixtures || [];
  const leagues = state.leagues.length ? state.leagues : (state.meta?.default_leagues || []);
  const months = monthOptionsFromFixtures(all.filter((f) => leagues.includes(f.league)));

  if (state.monthFilter && !months.includes(state.monthFilter)) {
    state.monthFilter = "";
  }

  els.monthFilter.innerHTML = [
    `<option value="">All months</option>`,
    ...months.map(
      (monthKey) =>
        `<option value="${monthKey}"${monthKey === state.monthFilter ? " selected" : ""}>${formatMonthLabel(monthKey)}</option>`,
    ),
  ].join("");
  els.monthFilter.disabled = state.loading || !months.length;
}

function allLeagueUis() {
  return (state.meta?.leagues || []).map((row) => row.ui);
}

function renderLeagueToggle() {
  const leagues = state.meta?.leagues || [];
  if (!state.leagues.length) {
    state.leagues = leagues.map((row) => row.ui);
  }

  const allSelected = leagues.length > 0 && leagues.every((row) => state.leagues.includes(row.ui));

  els.leagueToggle.innerHTML = [
    `<button type="button" class="fp-league-btn fp-league-btn--all${allSelected ? " fp-league-btn--active" : ""}" data-league-action="all"${state.loading ? " disabled" : ""}>All leagues</button>`,
    ...leagues.map((league) => {
      const active = state.leagues.includes(league.ui);
      const color = league.color || leagueColors[league.ui] || "#34d399";
      return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-league="${league.ui}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${league.ui}</button>`;
    }),
  ].join("");

  els.leagueToggle.querySelectorAll(".fp-league-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      if (btn.dataset.leagueAction === "all") {
        state.leagues = allLeagueUis();
      } else {
        const league = btn.dataset.league;
        if (state.leagues.includes(league)) {
          state.leagues = state.leagues.filter((item) => item !== league);
        } else {
          state.leagues = [...state.leagues, league];
        }
        if (!state.leagues.length) {
          state.leagues = [league];
        }
      }
      renderLeagueToggle();
      renderMonthFilter();
      renderSummary();
      renderView();
    });
  });
}

function countAssignments() {
  const assigned = Object.values(state.assignments).filter((row) => row.staff).length;
  const live = Object.values(state.assignments).filter((row) => row.watch_type === "LIVE").length;
  const video = Object.values(state.assignments).filter((row) => row.watch_type === "VIDEO").length;
  return { assigned, live, video };
}

function coverageFromFixtures(fixtures) {
  const byLeague = new Map();
  fixtures.forEach((fixture) => {
    const league = fixture.league;
    const dateKey = fixtureDateKey(fixture);
    if (!league || !dateKey) return;
    if (!byLeague.has(league)) {
      byLeague.set(league, {
        fixture_count: 0,
        first_date: dateKey,
        last_date: dateKey,
      });
    }
    const row = byLeague.get(league);
    row.fixture_count += 1;
    if (dateKey < row.first_date) row.first_date = dateKey;
    if (dateKey > row.last_date) row.last_date = dateKey;
  });
  return Object.fromEntries(byLeague);
}

function renderCoveragePanel() {
  if (!els.coveragePanel) return;
  const fixtures = state.payload?.fixtures || [];
  const apiCoverage = state.payload?.coverage || {};
  const computedCoverage = coverageFromFixtures(fixtures);
  const rows = activeLeagueOrder().map((league) => {
    const row = apiCoverage[league]?.fixture_count ? apiCoverage[league] : computedCoverage[league] || {};
    const color = leagueColors[league] || "#34d399";
    if (!row.fixture_count) {
      return `<div class="fp-coverage__item fp-coverage__item--empty" style="--league-color:${color}"><strong>${league}</strong><span>No ${state.season} fixtures in loaded data</span></div>`;
    }
    const start = formatShortDate(row.first_date);
    const end = formatShortDate(row.last_date);
    return `<div class="fp-coverage__item" style="--league-color:${color}"><strong>${league}</strong><span>${row.fixture_count} fixtures · ${start} – ${end}</span></div>`;
  });
  els.coveragePanel.innerHTML = rows.join("");
  els.coveragePanel.classList.remove("hidden");
}

function scrollListToUpcoming() {
  if (state.view !== "list" || !els.listRoot) return;
  requestAnimationFrame(() => {
    const today = todayKey();
    const sections = [...els.listRoot.querySelectorAll(".fp-list-day")];
    const target =
      sections.find((section) => section.dataset.weekendStart && section.dataset.weekendStart >= today) ||
      sections.find((section) => section.dataset.weekendStart) ||
      sections[0];
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
function renderSummary() {
  const fixtures = visibleFixtures();
  const all = state.payload?.fixtures || [];
  const { assigned, live, video } = countAssignments();

  els.summaryPanel.innerHTML = `
    <div class="fp-summary__item">
      <span class="fp-summary__value">${fixtures.length}</span>
      <span class="fp-summary__label">Fixtures shown</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${state.leagues.length}</span>
      <span class="fp-summary__label">Leagues selected</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${assigned}</span>
      <span class="fp-summary__label">Assigned to staff</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${live} / ${video}</span>
      <span class="fp-summary__label">Live / Video</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${state.season}</span>
      <span class="fp-summary__label">Season (${all.length} total loaded)</span>
    </div>
  `;

  const leagueLabel = state.leagues.join(", ") || "All leagues";
  els.pageSubtitle.textContent = `${state.season} fixtures · ${leagueLabel} · assign scouts as Live or Video`;
  renderCoveragePanel();
}

function groupFixturesByMonth(fixtures) {
  const months = new Map();
  fixtures.forEach((fixture) => {
    const dateKey = fixture.date || (fixture.scheduled_date || "").slice(0, 10);
    if (!dateKey) return;
    const monthKey = dateKey.slice(0, 7);
    if (!months.has(monthKey)) months.set(monthKey, []);
    months.get(monthKey).push({ ...fixture, date: dateKey });
  });
  return [...months.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function groupFixturesByDate(fixtures) {
  const days = new Map();
  fixtures.forEach((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (!dateKey) return;
    if (!days.has(dateKey)) days.set(dateKey, []);
    days.get(dateKey).push({ ...fixture, date: dateKey });
  });
  return [...days.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function groupFixturesByWeekend(fixtures) {
  const weekends = new Map();
  fixtures.forEach((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (!dateKey) return;
    const key = footballWeekendKey(dateKey);
    if (!weekends.has(key)) weekends.set(key, []);
    weekends.get(key).push({ ...fixture, date: dateKey });
  });
  return [...weekends.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function formatWeekendLabel(weekendKey, fixtures) {
  const dates = [...new Set(fixtures.map((fixture) => fixtureDateKey(fixture)))].sort();
  if (dates.length === 1) {
    return formatDateLabel(dates[0]);
  }
  const anchor = formatDateLabel(weekendKey);
  const span = `${formatShortDate(dates[0])} – ${formatShortDate(dates[dates.length - 1])}`;
  return `Weekend of ${anchor} (${span})`;
}

function assignmentBadge(fixture) {
  const assignment = assignmentFor(fixtureId(fixture));
  if (!assignment.staff && !assignment.watch_type) {
    return "";
  }
  const parts = [];
  if (assignment.staff) {
    parts.push(`<span class="fp-assignment-badge fp-assignment-badge--staff">${assignment.staff.split(" ")[0]}</span>`);
  }
  if (assignment.watch_type) {
    const cls = assignment.watch_type === "LIVE" ? "fp-assignment-badge--live" : "fp-assignment-badge--video";
    parts.push(`<span class="fp-assignment-badge ${cls}">${assignment.watch_type}</span>`);
  }
  const watchedCount = (assignment.watched_players || []).length;
  if (watchedCount) {
    parts.push(`<span class="fp-assignment-badge fp-assignment-badge--players">${watchedCount} player${watchedCount === 1 ? "" : "s"}</span>`);
  }
  return `<div class="fp-assignment-badges">${parts.join("")}</div>`;
}

function buildMonthGrid(monthKey, fixtures) {
  const [year, month] = monthKey.split("-").map(Number);
  const startOffset = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = todayKey();

  const byDate = new Map();
  fixtures.forEach((fixture) => {
    if (!byDate.has(fixture.date)) byDate.set(fixture.date, []);
    byDate.get(fixture.date).push(fixture);
  });

  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const weekdayHtml = weekdays.map((day) => `<div class="fp-weekday">${day}</div>`).join("");

  const cells = [];
  for (let i = 0; i < startOffset; i += 1) {
    cells.push('<div class="fp-day fp-day--muted"></div>');
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const dayFixtures = byDate.get(dateKey) || [];
    const todayClass = dateKey === today ? " fp-day__num--today" : "";
    cells.push(`
      <div class="fp-day">
        <div class="fp-day__num${todayClass}">${day}</div>
        ${dayFixtures
          .slice(0, 3)
          .map((fixture) => {
            const color = leagueColors[fixture.league] || "#34d399";
            return `
              <article class="fp-fixture" style="--league-color:${color}">
                <div class="fp-fixture__teams">${fixtureTeams(fixture)}</div>
                <div class="fp-fixture__meta">
                  <span class="fp-fixture__league">${fixture.league}</span>
                  <span>${formatTime(fixture.kickoff_utc || fixture.scheduled_date)}</span>
                </div>
                ${assignmentBadge(fixture)}
              </article>
            `;
          })
          .join("")}
        ${dayFixtures.length > 3 ? `<div class="fp-fixture__meta">+${dayFixtures.length - 3} more</div>` : ""}
      </div>
    `);
  }

  return `
    <section class="fp-month">
      <header class="fp-month__head">
        <h2 class="fp-month__title">${formatMonthLabel(monthKey)}</h2>
        <span class="fp-month__count">${fixtures.length} fixtures</span>
      </header>
      <div class="fp-month-grid">
        ${weekdayHtml}
        ${cells.join("")}
      </div>
    </section>
  `;
}

function renderCalendar() {
  const fixtures = visibleFixtures();
  if (!fixtures.length) {
    els.calendarRoot.innerHTML = `<div class="card" style="padding:1rem">No fixtures for the selected leagues.</div>`;
    return;
  }
  els.calendarRoot.innerHTML = groupFixturesByMonth(fixtures)
    .map(([monthKey, monthFixtures]) => buildMonthGrid(monthKey, monthFixtures))
    .join("");
}

function groupFixturesByLeague(fixtures) {
  const byLeague = new Map();
  fixtures.forEach((fixture) => {
    if (!byLeague.has(fixture.league)) {
      byLeague.set(fixture.league, []);
    }
    byLeague.get(fixture.league).push(fixture);
  });
  byLeague.forEach((rows) => {
    rows.sort((a, b) => {
      const ta = a.kickoff_utc || a.scheduled_date || "";
      const tb = b.kickoff_utc || b.scheduled_date || "";
      return ta.localeCompare(tb);
    });
  });
  return byLeague;
}

function activeLeagueOrder() {
  const selected = state.leagues.length ? state.leagues : Object.keys(leagueColors);
  return (state.meta?.default_leagues || Object.keys(leagueColors)).filter((league) =>
    selected.includes(league),
  );
}

function renderFixtureCard(fixture, { showDate = false } = {}) {
  const color = leagueColors[fixture.league] || "#34d399";
  const completed = isCompletedFixture(fixture);
  const showDateLine = showDate || completed;
  const dateLine = showDateLine
    ? `<span class="fp-list-fixture__date">${formatShortDate(fixtureDateKey(fixture))}</span>`
    : "";
  return `
    <article class="fp-list-fixture fp-list-fixture--stacked${completed ? " fp-list-fixture--completed" : ""}" style="--league-color:${color}">
      <div class="fp-list-fixture__schedule">
        <span class="fp-list-fixture__time">${formatTime(fixture.kickoff_utc || fixture.scheduled_date)}</span>
        ${dateLine}
      </div>
      <div class="fp-list-fixture__main">
        <div class="fp-list-fixture__head">
          ${assignmentBadge(fixture)}
        </div>
        <div class="fp-list-fixture__teams">${fixtureTeams(fixture)}</div>
        ${renderCompletedExtras(fixture)}
        ${assignmentControls(fixture)}
      </div>
    </article>
  `;
}

function renderLeagueColumn(league, fixtures, { showDate = false } = {}) {
  const color = leagueColors[league] || "#34d399";
  const body = fixtures.length
    ? fixtures.map((fixture) => renderFixtureCard(fixture, { showDate })).join("")
    : `<p class="fp-league-column__empty">No fixtures</p>`;
  return `
    <div class="fp-league-column${fixtures.length ? "" : " fp-league-column--empty"}" style="--league-color:${color}">
      <header class="fp-league-column__head">
        <span>${league}</span>
        <span class="fp-league-column__count">${fixtures.length}</span>
      </header>
      <div class="fp-league-column__body">
        ${body}
      </div>
    </div>
  `;
}

function renderList() {
  const fixtures = visibleFixtures();
  const hint = visibleFixtureHint();
  if (!fixtures.length) {
    const message = hint || "No fixtures for the selected leagues and filters.";
    els.listRoot.innerHTML = `<div class="card fp-list-empty"><p>${escapeHtml(message)}</p></div>`;
    return;
  }

  const leagueOrder = activeLeagueOrder();
  const hintHtml = hint
    ? `<div class="fp-list-hint card"><p>${escapeHtml(hint)}</p></div>`
    : "";

  els.listRoot.innerHTML =
    hintHtml +
    groupFixturesByWeekend(fixtures)
      .map(([weekendKey, weekendFixtures]) => {
        const byLeague = groupFixturesByLeague(weekendFixtures);
        const showDate = new Set(weekendFixtures.map((fixture) => fixtureDateKey(fixture))).size > 1;
        const columns = leagueOrder
          .map((league) => renderLeagueColumn(league, byLeague.get(league) || [], { showDate }))
          .join("");

        return `
        <section class="fp-list-day" data-weekend-start="${escapeHtml(weekendKey)}">
          <header class="fp-list-day__head">${formatWeekendLabel(weekendKey, weekendFixtures)} · ${weekendFixtures.length} fixtures</header>
          <div class="fp-list-day__columns" style="--fp-league-count:${leagueOrder.length}">${columns}</div>
        </section>
      `;
      })
      .join("");

  bindAssignmentEvents(els.listRoot);
  scrollListToUpcoming();
}

function renderView() {
  const isMonth = state.view === "month";
  els.calendarRoot.classList.toggle("hidden", !isMonth);
  els.listRoot.classList.toggle("hidden", isMonth);
  if (isMonth) renderCalendar();
  else renderList();
}

async function loadFixtures() {
  state.loading = true;
  state.enrichment = {};
  state.enrichmentPending = {};
  renderSeasonToggle();
  renderLeagueToggle();
  setStatus(`Loading ${state.season} fixtures…`, "loading");
  els.statusBar.textContent = "Fetching fixtures from Impect, FotMob and BBC…";

  try {
    state.payload = await fetchJson(
      `/api/fixture-planner/fixtures?season=${encodeURIComponent(state.season)}`,
    );
    renderMonthFilter();
    renderSummary();
    renderView();
    setStatus("");
    const coverage = state.payload?.coverage || {};
    const missing = activeLeagueOrder().filter((league) => !(coverage[league]?.fixture_count));
    if (state.season === "26/27" && missing.length) {
      els.statusBar.textContent = `Loaded ${state.payload.fixtures?.length || 0} fixtures for ${state.season}. League One/Two start 15 Aug 2026; Scottish Prem starts 31 Jul 2026. ${missing.join(", ")} ${missing.length === 1 ? "has" : "have"} no published 26/27 schedule yet.`;
    } else {
      els.statusBar.textContent = `Loaded ${state.payload.fixtures?.length || 0} fixtures for ${state.season}. Use league filters and assign staff below.`;
    }
  } catch (error) {
    setStatus(error.message, "error");
    els.statusBar.textContent = "Could not load fixtures.";
  } finally {
    state.loading = false;
    renderSeasonToggle();
    renderLeagueToggle();
    renderMonthFilter();
  }
}

async function init() {
  await loadAssignmentsFromServer();

  document.querySelectorAll(".fp-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.classList.contains("fp-view-btn--active")) return;
      document.querySelectorAll(".fp-view-btn").forEach((item) => item.classList.remove("fp-view-btn--active"));
      btn.classList.add("fp-view-btn--active");
      state.view = btn.dataset.view;
      renderView();
    });
  });

  els.staffFilter?.addEventListener("change", () => {
    state.staffFilter = els.staffFilter.value;
    renderSummary();
    renderView();
  });

  els.monthFilter?.addEventListener("change", () => {
    state.monthFilter = els.monthFilter.value;
    renderSummary();
    renderView();
  });

  els.hidePastToggle?.addEventListener("change", () => {
    state.hidePast = els.hidePastToggle.checked;
    if (!state.hidePast && !state.monthFilter) {
      const count = fixturesForLeagues().length;
      if (count > MAX_UNFILTERED_FIXTURES) {
        state.monthFilter = defaultMonthForPastView();
        if (els.monthFilter) {
          els.monthFilter.value = state.monthFilter;
        }
      }
    }
    renderMonthFilter();
    renderSummary();
    renderView();
  });

  els.refreshBtn.addEventListener("click", () => loadFixtures());

  els.assignModal?.querySelectorAll("[data-assign-close]").forEach((btn) => {
    btn.addEventListener("click", closeAssignModal);
  });
  els.assignConfirmBtn?.addEventListener("click", confirmAssignModal);
  els.assignModalWatch?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-assign-watch]");
    if (!btn || !state.assignModal) return;
    state.assignModal.watchType = btn.dataset.assignWatch || "LIVE";
    renderAssignModalChrome();
  });

  els.listRoot?.addEventListener("toggle", (event) => {
    const details = event.target.closest(".fp-fixture-details");
    if (!details || !details.open) return;
    const fixtureIdValue = details.dataset.fixtureId;
    if (fixtureIdValue) {
      loadEnrichmentForIds([fixtureIdValue]);
    }
  });

  try {
    state.meta = await fetchJson("/api/fixture-planner/meta");
    state.season = state.meta.season || DEFAULT_SEASON;
    state.leagues = [...(state.meta.default_leagues || [])];

    if (els.staffFilter) {
      const teams = staffTeams();
      const grouped = teams
        .map((team) => {
          const members = team.members || [];
          if (!members.length) {
            return `<optgroup label="${escapeHtml(team.label)}"><option value="" disabled>No one listed yet</option></optgroup>`;
          }
          return `<optgroup label="${escapeHtml(team.label)}">${members
            .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
            .join("")}</optgroup>`;
        })
        .join("");
      els.staffFilter.innerHTML = `<option value="">All staff</option>${grouped}`;
    }

    renderSeasonToggle();
    renderLeagueToggle();
    await loadFixtures();
  } catch (error) {
    setStatus(error.message, "error");
    els.statusBar.textContent = "Could not load fixture planner.";
  }
}

init();
