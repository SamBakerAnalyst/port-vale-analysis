const ALLOWED_SEASONS = ["26/27", "25/26", "ALL"];
const UNDO_DELETE_MS = 8000;
const PERIOD_OPTIONS = [
  { id: "all", label: "All time" },
  { id: "this_week", label: "This week" },
  { id: "last_week", label: "Last week" },
  { id: "next_week", label: "Next week" },
  { id: "this_month", label: "This month" },
  { id: "last_month", label: "Last month" },
  { id: "upcoming", label: "Upcoming" },
];

const PXT_DEFINITION = {
  short: "PXT (Packing Expected Threat)",
  body: "Impect's measure of how much a player or team's actions increased or decreased the likelihood of scoring or conceding in this match. Higher is better; negative values mean actions hurt the team.",
};

const leagueColors = {
  "League One": "#3d8bfd",
  "League Two": "#34d399",
  "National League": "#fbbf24",
  "Scottish Prem": "#a78bfa",
  PL2: "#f97316",
  "Irish Prem": "#22d3ee",
};

const state = {
  meta: null,
  rawPayload: null,
  payload: null,
  season: "ALL",
  staff: "",
  period: "all",
  loading: false,
};

let pendingDelete = null;

const stateMatchData = {
  data: {},
  pending: {},
  errors: {},
  modalFixtureId: null,
};

const stateScoutingReports = {
  byFixture: {},
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  staffToggle: document.getElementById("staffToggle"),
  periodToggle: document.getElementById("periodToggle"),
  kpiPanel: document.getElementById("kpiPanel"),
  leaguePanel: document.getElementById("leaguePanel"),
  staffPanel: document.getElementById("staffPanel"),
  staffSectionTitle: document.getElementById("staffSectionTitle"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  undoToast: document.getElementById("undoToast"),
  undoToastMessage: document.getElementById("undoToastMessage"),
  undoToastBtn: document.getElementById("undoToastBtn"),
  matchModal: document.getElementById("matchModal"),
  matchModalTitle: document.getElementById("matchModalTitle"),
  matchModalMeta: document.getElementById("matchModalMeta"),
  matchModalBody: document.getElementById("matchModalBody"),
};

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

function formatTime(iso) {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
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

function staffFirstName(name) {
  return String(name || "").trim().split(" ")[0] || "Staff";
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function addDays(dateKey, days) {
  const date = new Date(`${dateKey}T12:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function dateKeyFromDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function footballWeekStart(dateKey) {
  const date = new Date(`${dateKey}T12:00:00`);
  const day = date.getDay();
  const saturday = new Date(date);
  const daysBack = day === 6 ? 0 : day + 1;
  saturday.setDate(date.getDate() - daysBack);
  return dateKeyFromDate(saturday);
}

function footballWeekRangeFromStart(startKey) {
  return { start: startKey, end: addDays(startKey, 6) };
}

function periodRange(periodId) {
  const today = todayKey();
  switch (periodId) {
    case "this_week":
      return footballWeekRangeFromStart(footballWeekStart(today));
    case "last_week":
      return footballWeekRangeFromStart(addDays(footballWeekStart(today), -7));
    case "next_week":
      return footballWeekRangeFromStart(addDays(footballWeekStart(today), 7));
    case "this_month": {
      const now = new Date();
      return {
        start: dateKeyFromDate(new Date(now.getFullYear(), now.getMonth(), 1)),
        end: dateKeyFromDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
      };
    }
    case "last_month": {
      const now = new Date();
      return {
        start: dateKeyFromDate(new Date(now.getFullYear(), now.getMonth() - 1, 1)),
        end: dateKeyFromDate(new Date(now.getFullYear(), now.getMonth(), 0)),
      };
    }
    case "upcoming":
      return { start: today, end: null };
    default:
      return null;
  }
}

function periodLabel(periodId) {
  return PERIOD_OPTIONS.find((row) => row.id === periodId)?.label || "All time";
}

function fixtureInPeriod(fixture, periodId) {
  if (!periodId || periodId === "all") {
    return true;
  }
  const date = fixture.date;
  if (!date) {
    return false;
  }
  const range = periodRange(periodId);
  if (!range) {
    return true;
  }
  if (range.start && date < range.start) {
    return false;
  }
  if (range.end && date > range.end) {
    return false;
  }
  return true;
}

function filterPayloadByPeriod(rawPayload, periodId) {
  if (!rawPayload) {
    return null;
  }
  if (!periodId || periodId === "all") {
    return JSON.parse(JSON.stringify(rawPayload));
  }

  const filteredStaff = (rawPayload.staff || [])
    .map((staffRow) => {
      const fixtures = (staffRow.fixtures || []).filter((fixture) => fixtureInPeriod(fixture, periodId));
      if (!fixtures.length) {
        return null;
      }
      const live = fixtures.filter((fixture) => fixture.watch_type === "LIVE").length;
      const video = fixtures.filter((fixture) => fixture.watch_type === "VIDEO").length;
      return {
        ...staffRow,
        fixtures,
        total: fixtures.length,
        live,
        video,
      };
    })
    .filter(Boolean);

  const totals = { assigned: 0, live: 0, video: 0, scouting_reports: 0 };
  const byLeague = {};
  filteredStaff.forEach((staffRow) => {
    staffRow.fixtures.forEach((fixture) => {
      totals.assigned += 1;
      if (fixture.watch_type === "LIVE") totals.live += 1;
      if (fixture.watch_type === "VIDEO") totals.video += 1;
      totals.scouting_reports += Number(fixture.scouting_report_count || 0);
      const league = fixture.league || "Unknown";
      byLeague[league] = (byLeague[league] || 0) + 1;
    });
  });

  return {
    ...rawPayload,
    staff: filteredStaff,
    totals,
    by_league: byLeague,
    period: periodId,
  };
}

function attachScoutingReportsToFixture(fixture) {
  const reports = scoutingReportsForFixture(fixture.fixture_id);
  fixture.scouting_reports = reports;
  fixture.scouting_report_count = reports.length;
  return reports.length;
}

function hydrateRawPayloadReports() {
  if (!state.rawPayload?.staff) {
    return 0;
  }
  let total = 0;
  for (const staffRow of state.rawPayload.staff) {
    for (const fixture of staffRow.fixtures || []) {
      total += attachScoutingReportsToFixture(fixture);
    }
  }
  state.rawPayload.totals = {
    ...(state.rawPayload.totals || {}),
    scouting_reports: total,
  };
  return total;
}

function applyViewPayload() {
  hydrateRawPayloadReports();
  state.payload = filterPayloadByPeriod(state.rawPayload, state.period);
  refreshSummaryViews();
}

function assignmentFixtures() {
  return (state.payload?.staff || []).flatMap((row) => row.fixtures || []);
}

function computePlanningKpis() {
  const fixtures = assignmentFixtures();
  const staffRows = state.payload?.staff || [];
  const allStaff = state.meta?.staff || [];
  const today = todayKey();
  const { end: weekEnd } = footballWeekRangeFromStart(footballWeekStart(today));

  const upcoming = fixtures.filter((row) => row.date && row.date >= today).length;
  const thisWeek = fixtures.filter((row) => row.date && row.date >= today && row.date <= weekEnd).length;

  let busiest = null;
  staffRows.forEach((row) => {
    if (!busiest || row.total > busiest.total) {
      busiest = { name: staffFirstName(row.staff), total: row.total };
    }
  });
  const busiestValue = busiest?.total ? `${busiest.name} · ${busiest.total}` : "—";

  let idleScouts = "—";
  if (!state.staff && allStaff.length) {
    const activeCount = allStaff.filter((name) =>
      staffRows.some((row) => row.staff === name && row.total > 0),
    ).length;
    idleScouts = String(Math.max(0, allStaff.length - activeCount));
  }

  return { upcoming, thisWeek, busiestValue, idleScouts };
}

function fixtureLabel(row) {
  const home = String(row.home || "").trim();
  const away = String(row.away || "").trim();
  const scoreSuffix = row.score ? ` (${row.score})` : "";
  if (home && away) return `${home} vs ${away}${scoreSuffix}`;
  if (home || away) return `${home || away}${scoreSuffix}`;
  return "Fixture details pending";
}

function isPlayedFixture(row) {
  if (row.status === "completed" || row.score) {
    return true;
  }
  const date = row.date;
  return Boolean(date && date < todayKey());
}

function syncScoutingReportsStore(reportsByFixture = {}) {
  stateScoutingReports.byFixture = {};
  Object.entries(reportsByFixture || {}).forEach(([fixtureId, fixtureReports]) => {
    if (!fixtureReports || typeof fixtureReports !== "object") {
      return;
    }
    stateScoutingReports.byFixture[fixtureId] = { ...fixtureReports };
  });
}

function scoutingReportsForFixture(fixtureId) {
  const bucket = stateScoutingReports.byFixture[fixtureId] || {};
  return Object.values(bucket).filter((row) => row && typeof row === "object");
}

function scoutingReportCount(fixtureId) {
  return scoutingReportsForFixture(fixtureId).length;
}

function isPlayerReported(fixtureId, playerId) {
  if (!fixtureId || !playerId) {
    return false;
  }
  return Boolean(stateScoutingReports.byFixture[fixtureId]?.[String(playerId)]);
}

async function loadScoutingReports() {
  try {
    const payload = await fetchJson("/api/fixture-planner/scouting-reports");
    syncScoutingReportsStore(payload.reports || {});
  } catch (error) {
    console.warn("Could not load scouting reports", error);
  }
}

async function togglePlayerReport({ fixtureId, player, side, team, row }) {
  if (!fixtureId || !player?.player_id) {
    return;
  }
  const playerKey = String(player.player_id);
  const reported = !isPlayerReported(fixtureId, player.player_id);
  const fixtureBucket = { ...(stateScoutingReports.byFixture[fixtureId] || {}) };

  if (reported) {
    fixtureBucket[playerKey] = {
      player_id: player.player_id,
      player_name: player.name || "",
      side,
      team,
      position: player.position_code || player.position || "",
      staff: row?.staff || "",
      season: row?.season || "",
      fixture_date: row?.date || "",
      marked_at: new Date().toISOString(),
    };
  } else {
    delete fixtureBucket[playerKey];
  }

  if (Object.keys(fixtureBucket).length) {
    stateScoutingReports.byFixture[fixtureId] = fixtureBucket;
  } else {
    delete stateScoutingReports.byFixture[fixtureId];
  }

  hydrateRawPayloadReports();
  applyViewPayload();
  renderMatchModal();

  try {
    await fetchJson("/api/fixture-planner/scouting-report", {
      method: "PATCH",
      body: JSON.stringify({
        fixture_id: fixtureId,
        player_id: player.player_id,
        player_name: player.name || "",
        side,
        team,
        position: player.position_code || player.position || "",
        season: row?.season || "",
        staff: row?.staff || "",
        fixture_date: row?.date || "",
        reported,
      }),
    });
  } catch (error) {
    console.warn("Could not save scouting report", error);
    await loadScoutingReports();
    hydrateRawPayloadReports();
    applyViewPayload();
    renderMatchModal();
  }
}

function syncRowScoutingReports(fixtureId, reports) {
  const source = state.rawPayload || state.payload;
  if (!source?.staff) {
    return;
  }
  for (const staffRow of source.staff) {
    const fixture = (staffRow.fixtures || []).find((row) => row.fixture_id === fixtureId);
    if (!fixture) {
      continue;
    }
    fixture.scouting_reports = reports;
    fixture.scouting_report_count = reports.length;
    break;
  }
  if (state.payload) {
    state.payload = applyPeriodFilter(source);
  }
}

function playerSurname(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (parts[parts.length - 1] || name || "").toUpperCase();
}

function playerInitials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] || ""}${parts[parts.length - 1][0] || ""}`.toUpperCase();
}

function isGoalkeeper(player) {
  const position = String(player?.position_code || player?.position || "").toUpperCase();
  return position === "GOALKEEPER" || position === "GK";
}

function playerPhotoUrl(player) {
  if (player?.photo_url) {
    return player.photo_url;
  }
  const name = String(player?.name || "").trim();
  if (!name) {
    return null;
  }
  return `/api/player-photo?name=${encodeURIComponent(name)}`;
}

function playerPhotoMarkup(player) {
  const name = String(player?.name || "");
  const photoUrl = playerPhotoUrl(player);
  const shirt = player?.shirt_number ?? "";
  const gkClass = isGoalkeeper(player) ? " so-pitch-player__face--gk" : "";
  if (photoUrl) {
    return `<img class="so-pitch-player__img" src="${escapeHtml(photoUrl)}" alt="${escapeHtml(name)}" loading="lazy" onerror="this.closest('.so-pitch-player__face').classList.add('so-pitch-player__face--fallback'); this.remove();" />`;
  }
  return `<span class="so-pitch-player__initials">${escapeHtml(String(shirt || playerInitials(name)))}</span>`;
}

function pitchPlayerMarkup(player, index, { fixtureId, side }) {
  let left = Number(player.x_pct ?? 50);
  let top = Number(player.y_pct ?? 50);
  left = Math.max(14, Math.min(86, left));
  const goalkeeper = isGoalkeeper(player);
  if (goalkeeper) {
    top = Math.min(top, 80);
  } else if (top <= 16) {
    top = 12;
  } else {
    top = Math.max(12, Math.min(86, top));
  }
  const anchorBottom = false;
  const shirt = player.shirt_number ? String(player.shirt_number) : "";
  const reported = isPlayerReported(fixtureId, player.player_id);
  const pxt =
    player.pxt != null
      ? `<span class="so-pitch-player__pxt${player.pxt < 0 ? " so-pitch-player__pxt--neg" : ""}">${player.pxt}</span>`
      : `<span class="so-pitch-player__pxt so-pitch-player__pxt--na">—</span>`;
  const title = [player.name, player.position, player.pxt != null ? `PXT ${player.pxt}` : ""]
    .filter(Boolean)
    .join(" · ");
  return `<button type="button" class="so-pitch-player${anchorBottom ? " so-pitch-player--anchor-bottom" : ""}${reported ? " so-pitch-player--reported" : ""}" style="left:${left}%;top:${top}%;z-index:${index + 1}" title="${escapeHtml(title)}" data-player-id="${player.player_id}" data-side="${escapeHtml(side)}" aria-pressed="${reported ? "true" : "false"}" aria-label="${escapeHtml(player.name || "Player")}${reported ? " — report marked" : ""}">
    <div class="so-pitch-player__face${goalkeeper ? " so-pitch-player__face--gk" : ""}">${playerPhotoMarkup(player)}</div>
    <div class="so-pitch-player__card">
      ${shirt ? `<span class="so-pitch-player__shirt">${escapeHtml(shirt)}</span>` : ""}
      <span class="so-pitch-player__name">${escapeHtml(playerSurname(player.name))}</span>
      ${pxt}
    </div>
  </button>`;
}

function teamCrestMarkup(team) {
  const name = String(team?.name || "?");
  const src = team?.image_url || team?.imageUrl || "";
  if (src) {
    return `<img class="so-match-team__crest" src="${escapeHtml(src)}" alt="" loading="lazy" />`;
  }
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return `<span class="so-match-team__crest so-match-team__crest--fallback">${escapeHtml(initials)}</span>`;
}

function renderSquadTable(players, { fixtureId, side }) {
  const rows = [...players].sort((a, b) => {
    const aPxt = a.pxt ?? -999;
    const bPxt = b.pxt ?? -999;
    return bPxt - aPxt;
  });
  return `
    <div class="so-match-team__squad">
      <div class="so-match-team__squad-head">
        <span>#</span>
        <span>Player</span>
        <span>Pos</span>
        <span>PXT</span>
      </div>
      ${rows
        .map((player) => {
          const pxtClass =
            player.pxt == null
              ? "so-match-team__pxt-val--na"
              : player.pxt < 0
                ? "so-match-team__pxt-val--neg"
                : "";
          const reported = isPlayerReported(fixtureId, player.player_id);
          return `<div class="so-match-team__squad-row${reported ? " so-match-team__squad-row--reported" : ""}" role="button" tabindex="0" data-player-id="${player.player_id}" data-side="${escapeHtml(side)}" aria-pressed="${reported ? "true" : "false"}">
            <span class="so-match-team__num">${escapeHtml(String(player.shirt_number || "—"))}</span>
            <span class="so-match-team__player">${escapeHtml(player.name || "")}</span>
            <span class="so-match-team__pos">${escapeHtml(player.position || "—")}</span>
            <span class="so-match-team__pxt-val ${pxtClass}">${player.pxt != null ? player.pxt : "—"}</span>
          </div>`;
        })
        .join("")}
    </div>
  `;
}

function renderFormationPitch(sideLabel, team, lineup, teamPxt, { fixtureId, side }) {
  const players = lineup?.players || [];
  if (!players.length) {
    return `<section class="so-match-team"><p class="so-match-team__empty">Lineup not available.</p></section>`;
  }
  const formation = lineup.formation ? lineup.formation : "";
  const pxtLabel = teamPxt != null ? `<span class="so-match-team__pxt">Team PXT ${teamPxt}</span>` : "";
  const markers = players
    .map((player, index) => pitchPlayerMarkup(player, index, { fixtureId, side }))
    .join("");
  return `
    <section class="so-match-team" data-side="${escapeHtml(side)}">
      <header class="so-match-team__head">
        ${teamCrestMarkup(team)}
        <div class="so-match-team__titles">
          <h3 class="so-match-team__name">${escapeHtml(sideLabel)}</h3>
          <div class="so-match-team__sub">
            ${formation ? `<span class="so-match-team__formation">${escapeHtml(formation)}</span>` : ""}
            ${pxtLabel}
          </div>
        </div>
      </header>
      <div class="so-match-pitch">
        <div class="so-match-pitch__markings"></div>
        ${markers}
      </div>
      <details class="so-match-team__details" open>
        <summary class="so-match-team__details-summary">Full squad &amp; PXT</summary>
        ${renderSquadTable(players, { fixtureId, side })}
      </details>
    </section>
  `;
}

function renderPxtDefinition() {
  return `<aside class="so-match-modal__pxt-def" aria-label="PXT definition">
    <p class="so-match-modal__pxt-def-title">${escapeHtml(PXT_DEFINITION.short)}</p>
    <p class="so-match-modal__pxt-def-body">${escapeHtml(PXT_DEFINITION.body)}</p>
  </aside>`;
}

function renderMatchModalContent(row, enrich) {
  const fixtureId = row?.fixture_id || enrich?.fixture_id || "";
  const homeName = row.home || enrich?.home_team?.name || "Home";
  const awayName = row.away || enrich?.away_team?.name || "Away";
  const homePxt = enrich?.pxt?.home;
  const awayPxt = enrich?.pxt?.away;
  const reportedPlayers = scoutingReportsForFixture(fixtureId);
  const venue = enrich?.venue
    ? `<div class="so-match-modal__stat so-match-modal__stat--venue">${escapeHtml(enrich.venue)}</div>`
    : "";
  const teamPxt =
    homePxt != null || awayPxt != null
      ? `<div class="so-match-modal__stat so-match-modal__stat--pxt"><span class="so-match-modal__stat-label">Team PXT</span> <strong>${homePxt ?? "—"}</strong> <span class="so-match-modal__stat-sep">vs</span> <strong>${awayPxt ?? "—"}</strong></div>`
      : "";
  const reportedSummary = reportedPlayers.length
    ? `<div class="so-match-modal__reports"><span class="so-match-modal__reports-label">Reports marked</span> ${reportedPlayers
        .map((entry) => `<span class="so-match-modal__report-chip">${escapeHtml(entry.player_name || "Player")}</span>`)
        .join("")}</div>`
    : `<p class="so-match-modal__reports-hint">Click players on the pitch or in the squad list to mark scouting reports.</p>`;
  return `
    <div class="so-match-modal__stats">${venue}${teamPxt}</div>
    ${renderPxtDefinition()}
    ${reportedSummary}
    <div class="so-match-modal__pitches">
      ${renderFormationPitch(homeName, enrich?.home_team, enrich?.lineups?.home, homePxt, {
        fixtureId,
        side: "home",
      })}
      ${renderFormationPitch(awayName, enrich?.away_team, enrich?.lineups?.away, awayPxt, {
        fixtureId,
        side: "away",
      })}
    </div>
  `;
}

function findPlayerInEnrichment(enrich, playerId, side) {
  const lineup = enrich?.lineups?.[side];
  return (lineup?.players || []).find((player) => Number(player.player_id) === Number(playerId)) || null;
}

function handleMatchModalPlayerClick(event) {
  const target = event.target.closest("[data-player-id]");
  if (!target || !els.matchModalBody?.contains(target)) {
    return;
  }
  const fixtureId = stateMatchData.modalFixtureId;
  if (!fixtureId) {
    return;
  }
  const row = findFixtureRow(state.rawPayload || state.payload, fixtureId);
  const enrich = stateMatchData.data[fixtureId];
  const playerId = Number(target.dataset.playerId);
  const side = target.dataset.side || "home";
  const player = findPlayerInEnrichment(enrich, playerId, side);
  if (!player) {
    return;
  }
  const teamName = side === "away" ? row?.away || enrich?.away_team?.name : row?.home || enrich?.home_team?.name;
  togglePlayerReport({ fixtureId, player, side, team: teamName || "", row });
}

function renderMatchModal() {
  if (!els.matchModal || !els.matchModalBody) return;
  const fixtureId = stateMatchData.modalFixtureId;
  if (!fixtureId) {
    els.matchModal.classList.add("so-match-modal--hidden");
    els.matchModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("so-modal-open");
    return;
  }

  const row = findFixtureRow(state.rawPayload || state.payload, fixtureId);
  const enrich = stateMatchData.data[fixtureId];
  const pending = stateMatchData.pending[fixtureId];

  if (els.matchModalTitle) {
    els.matchModalTitle.textContent = row ? fixtureLabel(row) : "Match data";
  }
  if (els.matchModalMeta) {
    const bits = [row?.league, row?.season, row?.date ? formatShortDate(row.date) : ""].filter(Boolean);
    els.matchModalMeta.textContent = bits.join(" · ");
  }

  if (pending) {
    els.matchModalBody.innerHTML = `<div class="so-match-modal__loading">Loading lineups and player PXT…</div>`;
  } else if (!enrich) {
    const message = stateMatchData.errors[fixtureId] || "Could not load match data.";
    els.matchModalBody.innerHTML = `<div class="so-match-modal__empty">${escapeHtml(message)}</div>`;
  } else {
    els.matchModalBody.innerHTML = renderMatchModalContent(row || {}, enrich);
  }

  els.matchModal.classList.remove("so-match-modal--hidden");
  els.matchModal.setAttribute("aria-hidden", "false");
  document.body.classList.add("so-modal-open");
}

function openMatchModal(row) {
  if (!row?.fixture_id) return;
  stateMatchData.modalFixtureId = row.fixture_id;
  renderMatchModal();
  if (!stateMatchData.data[row.fixture_id] && !stateMatchData.pending[row.fixture_id]) {
    loadMatchData(row);
  }
}

function closeMatchModal() {
  stateMatchData.modalFixtureId = null;
  renderMatchModal();
}

function rowSeason(row) {
  if (row.season) {
    return row.season;
  }
  if (state.season && state.season !== "ALL") {
    return state.season;
  }
  const year = Number.parseInt(String(row.date || "").slice(0, 4), 10);
  if (year >= 2026) {
    return "26/27";
  }
  if (year === 2025) {
    return "25/26";
  }
  return "25/26";
}

async function loadMatchData(row) {
  const fixtureId = row.fixture_id;
  const season = rowSeason(row);
  if (!fixtureId || stateMatchData.pending[fixtureId]) {
    return;
  }
  if (stateMatchData.data[fixtureId]) {
    renderMatchModal();
    return;
  }

  stateMatchData.pending[fixtureId] = true;
  renderMatchModal();
  renderStaffCards();
  try {
    const params = new URLSearchParams({
      season,
      fixture_ids: fixtureId,
    });
    const payload = await fetchJson(`/api/fixture-planner/match-enrichment?${params}`);
    Object.assign(stateMatchData.data, payload.enrichments || {});
    if (!stateMatchData.data[fixtureId]) {
      stateMatchData.errors[fixtureId] = "No Impect match found for this fixture yet.";
    } else {
      delete stateMatchData.errors[fixtureId];
    }
  } catch (error) {
    console.warn("Could not load match data", error);
    stateMatchData.errors[fixtureId] = error.message || "Request failed.";
  } finally {
    delete stateMatchData.pending[fixtureId];
    renderMatchModal();
    renderStaffCards();
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function findFixtureRow(payload, fixtureId) {
  const source = payload || state.rawPayload || state.payload;
  for (const staffRow of source?.staff || []) {
    const match = (staffRow.fixtures || []).find((row) => row.fixture_id === fixtureId);
    if (match) {
      return { ...match, staff: match.staff || staffRow.staff };
    }
  }
  return null;
}

function assignmentRecordFromRow(row) {
  return {
    fixture_id: row.fixture_id,
    staff: row.staff || "",
    watch_type: row.watch_type || "",
    season: row.season || "",
    league: row.league || "",
    home: row.home || "",
    away: row.away || "",
    date: row.date || "",
    kickoff_utc: row.kickoff_utc || null,
  };
}

function payloadWithoutFixture(payload, fixtureId) {
  const row = findFixtureRow(payload, fixtureId);
  if (!row) return payload;

  const next = JSON.parse(JSON.stringify(payload));
  const league = row.league || "Unknown";
  const isLive = row.watch_type === "LIVE";
  const isVideo = row.watch_type === "VIDEO";

  next.totals.assigned = Math.max(0, (next.totals?.assigned || 0) - 1);
  if (isLive) next.totals.live = Math.max(0, (next.totals?.live || 0) - 1);
  if (isVideo) next.totals.video = Math.max(0, (next.totals?.video || 0) - 1);

  if (next.by_league?.[league]) {
    next.by_league[league] -= 1;
    if (next.by_league[league] <= 0) {
      delete next.by_league[league];
    }
  }

  next.staff = (next.staff || [])
    .map((staffRow) => {
      const fixtures = (staffRow.fixtures || []).filter((fixture) => fixture.fixture_id !== fixtureId);
      if (fixtures.length === (staffRow.fixtures || []).length) {
        return staffRow;
      }
      return {
        ...staffRow,
        fixtures,
        total: Math.max(0, staffRow.total - 1),
        live: isLive && staffRow.staff === row.staff ? Math.max(0, staffRow.live - 1) : staffRow.live,
        video: isVideo && staffRow.staff === row.staff ? Math.max(0, staffRow.video - 1) : staffRow.video,
      };
    })
    .filter((staffRow) => staffRow.total > 0);

  return next;
}

function hideUndoToast() {
  els.undoToast?.classList.add("so-toast--hidden");
}

function showUndoToast(message) {
  if (els.undoToastMessage) {
    els.undoToastMessage.textContent = message;
  }
  els.undoToast?.classList.remove("so-toast--hidden");
}

function clearPendingDelete({ commit = false } = {}) {
  if (!pendingDelete) return;
  clearTimeout(pendingDelete.timer);
  const snapshot = pendingDelete;
  pendingDelete = null;
  if (commit) {
    deleteAssignmentOnServer(snapshot.fixtureId).catch((error) => {
      state.rawPayload = snapshot.payloadSnapshot;
      applyViewPayload();
      els.statusBar.textContent = `Could not remove assignment: ${error.message}`;
    });
  }
}

async function deleteAssignmentOnServer(fixtureId) {
  await fetchJson("/api/fixture-planner/assignment", {
    method: "PATCH",
    body: JSON.stringify({ fixture_id: fixtureId, staff: "", watch_type: "" }),
  });
}

async function restoreAssignmentOnServer(record) {
  await fetchJson("/api/fixture-planner/assignment", {
    method: "PATCH",
    body: JSON.stringify(record),
  });
}

function refreshSummaryViews() {
  renderKpis();
  renderLeagueBreakdown();
  renderStaffCards();
  const updated = state.payload?.assignments_updated_at
    ? new Date(state.payload.assignments_updated_at).toLocaleString("en-GB")
    : "not synced yet";
  const staffLabel = state.staff || "All staff";
  const periodText = state.period === "all" ? "" : ` · ${periodLabel(state.period)}`;
  els.statusBar.textContent = `${staffLabel}${periodText} · ${state.payload?.totals?.assigned || 0} covered games · last assignment update ${updated}`;
}

function queueAssignmentRemoval(fixtureId) {
  const row = findFixtureRow(state.rawPayload, fixtureId);
  if (!row?.fixture_id) return;

  if (pendingDelete) {
    clearPendingDelete({ commit: true });
  }

  const payloadSnapshot = JSON.parse(JSON.stringify(state.rawPayload));
  const assignmentRecord = assignmentRecordFromRow(row);
  const label = fixtureLabel(row);

  state.rawPayload = payloadWithoutFixture(state.rawPayload, fixtureId);
  applyViewPayload();

  pendingDelete = {
    fixtureId,
    payloadSnapshot,
    assignmentRecord,
    label,
    timer: setTimeout(() => {
      const current = pendingDelete;
      pendingDelete = null;
      hideUndoToast();
      deleteAssignmentOnServer(current.fixtureId).catch((error) => {
        state.rawPayload = current.payloadSnapshot;
        applyViewPayload();
        els.statusBar.textContent = `Could not remove assignment: ${error.message}`;
      });
    }, UNDO_DELETE_MS),
  };

  showUndoToast(`Removed ${label}. Undo within ${UNDO_DELETE_MS / 1000}s?`);
}

function undoPendingDelete() {
  if (!pendingDelete) return;
  clearTimeout(pendingDelete.timer);
  state.rawPayload = pendingDelete.payloadSnapshot;
  pendingDelete = null;
  hideUndoToast();
  applyViewPayload();
  els.statusBar.textContent = "Removal cancelled.";
}

function syncUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (state.staff) {
    params.set("staff", state.staff);
  } else {
    params.delete("staff");
  }
  if (state.period && state.period !== "all") {
    params.set("period", state.period);
  } else {
    params.delete("period");
  }
  const query = params.toString();
  const next = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState({}, "", next);
}

function syncStaffInUrl() {
  syncUrlParams();
}

function setPeriodFilter(period) {
  state.period = period || "all";
  renderPeriodToggle();
  syncUrlParams();
  applyViewPayload();
}

function renderPeriodToggle() {
  if (!els.periodToggle) return;
  els.periodToggle.innerHTML = PERIOD_OPTIONS.map((option) => {
    const active = state.period === option.id;
    return `<button type="button" class="fp-league-btn so-period-btn${active ? " so-period-btn--active" : ""}" data-period="${option.id}"${state.loading ? " disabled" : ""}>${option.label}</button>`;
  }).join("");

  els.periodToggle.querySelectorAll(".so-period-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const next = btn.dataset.period || "all";
      if (next === state.period) return;
      setPeriodFilter(next);
    });
  });
}

function setStaffFilter(staff) {
  state.staff = staff || "";
  renderStaffToggle();
  syncStaffInUrl();
  loadSummary();
}

function renderStaffToggle() {
  if (!els.staffToggle) return;
  const staffList = state.meta?.staff || [];
  els.staffToggle.innerHTML = [
    `<button type="button" class="fp-league-btn so-staff-btn${!state.staff ? " so-staff-btn--active" : ""}" data-staff=""${state.loading ? " disabled" : ""}>All staff</button>`,
    ...staffList.map((name) => {
      const active = state.staff === name;
      return `<button type="button" class="fp-league-btn so-staff-btn${active ? " so-staff-btn--active" : ""}" data-staff="${name}"${state.loading ? " disabled" : ""}>${staffFirstName(name)}</button>`;
    }),
  ].join("");

  els.staffToggle.querySelectorAll(".so-staff-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const next = btn.dataset.staff || "";
      if (next === state.staff) return;
      setStaffFilter(next);
    });
  });
}

function renderSeasonToggle() {
  const seasons = ["ALL", ...(state.meta?.seasons || ALLOWED_SEASONS.filter((s) => s !== "ALL"))];
  els.seasonToggle.innerHTML = seasons
    .map((season) => {
      const active = season === state.season;
      const label =
        season === "ALL" ? "Both seasons" : season === "26/27" ? `This season (${season})` : `Last season (${season})`;
      return `<button type="button" class="fp-season-btn${active ? " fp-season-btn--active" : ""}" data-season="${season}"${state.loading ? " disabled" : ""}>${label}</button>`;
    })
    .join("");

  els.seasonToggle.querySelectorAll(".fp-season-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled || btn.classList.contains("fp-season-btn--active")) return;
      state.season = btn.dataset.season;
      loadSummary();
    });
  });
}

function scoutingReportsKpiLabel() {
  if (!state.period || state.period === "all") {
    return "Player reports marked";
  }
  return `Player reports (${periodLabel(state.period).toLowerCase()})`;
}

function renderKpis() {
  const totals = state.payload?.totals || { assigned: 0, live: 0, video: 0, scouting_reports: 0 };
  const planning = computePlanningKpis();
  const showPlanning = state.period === "all";
  const periodTiles = showPlanning
    ? `
    <div class="fp-summary__item">
      <span class="so-kpi__value">${planning.upcoming}</span>
      <span class="so-kpi__label">Upcoming games</span>
    </div>
    <div class="fp-summary__item">
      <span class="so-kpi__value">${planning.thisWeek}</span>
      <span class="so-kpi__label">This week</span>
    </div>`
    : "";
  els.kpiPanel.innerHTML = `
    <div class="fp-summary__item">
      <span class="so-kpi__value">${totals.assigned}</span>
      <span class="so-kpi__label">Games covered</span>
    </div>
    <div class="fp-summary__item">
      <span class="so-kpi__value">${totals.live}</span>
      <span class="so-kpi__label">Live assignments</span>
    </div>
    <div class="fp-summary__item">
      <span class="so-kpi__value">${totals.video}</span>
      <span class="so-kpi__label">Video assignments</span>
    </div>
    <div class="fp-summary__item">
      <span class="so-kpi__value">${totals.scouting_reports || 0}</span>
      <span class="so-kpi__label">${scoutingReportsKpiLabel()}</span>
    </div>
    ${periodTiles}
    <div class="fp-summary__item">
      <span class="so-kpi__value so-kpi__value--text">${planning.busiestValue}</span>
      <span class="so-kpi__label">Busiest scout</span>
    </div>
    <div class="fp-summary__item">
      <span class="so-kpi__value">${planning.idleScouts}</span>
      <span class="so-kpi__label">Scouts without games</span>
    </div>
  `;
}

function renderLeagueBreakdown() {
  const byLeague = state.payload?.by_league || {};
  const entries = Object.entries(byLeague).sort((a, b) => b[1] - a[1]);
  const staffLabel = state.staff ? `${state.staff}'s coverage` : "Coverage by league";
  const periodHint = state.period !== "all" ? ` (${periodLabel(state.period)})` : "";
  if (!entries.length) {
    els.leaguePanel.innerHTML = `<p class="so-empty">${state.staff ? `${staffFirstName(state.staff)} has no assignments for these filters yet.` : `No league breakdown for ${periodLabel(state.period).toLowerCase()} — try another period or assign scouts in the fixture planner.`}</p>`;
    return;
  }

  els.leaguePanel.innerHTML = `
    <h2 class="so-section-title">${staffLabel}${periodHint}</h2>
    <div class="fp-league-toggle">
      ${entries
        .map(([league, count]) => {
          const color = leagueColors[league] || "#34d399";
          return `<span class="fp-league-btn fp-league-btn--active" style="--league-color:${color};cursor:default">${league} · ${count}</span>`;
        })
        .join("")}
    </div>
  `;
}

function renderFixtureRow(row) {
  const color = leagueColors[row.league] || "#34d399";
  const watchClass = row.watch_type === "LIVE" ? "so-pill--live" : "so-pill--video";
  const fixtureId = escapeHtml(row.fixture_id || "");
  const played = isPlayedFixture(row);
  const dataLoaded = Boolean(stateMatchData.data[row.fixture_id]);
  const loadLabel = stateMatchData.pending[row.fixture_id]
    ? "Loading…"
    : dataLoaded
      ? "View match data"
      : "Load match data";
  const matchDataButton = played
    ? `<button type="button" class="so-fixture-row__load${dataLoaded ? " so-fixture-row__load--active" : ""}" data-fixture-id="${fixtureId}" data-season="${escapeHtml(row.season || "")}"${stateMatchData.pending[row.fixture_id] ? " disabled" : ""}>${loadLabel}</button>`
    : "";
  const reportCount = Number(row.scouting_report_count || scoutingReportCount(row.fixture_id) || 0);
  const reportBadge = reportCount
    ? `<span class="so-pill so-pill--report" title="${reportCount} player report${reportCount === 1 ? "" : "s"} marked">${reportCount} report${reportCount === 1 ? "" : "s"}</span>`
    : "";
  const reportNames = (row.scouting_reports || scoutingReportsForFixture(row.fixture_id))
    .map((entry) => entry.player_name)
    .filter(Boolean)
    .slice(0, 4);
  const reportList = reportNames.length
    ? `<p class="so-fixture-row__reports">${reportNames.map((name) => escapeHtml(name)).join(" · ")}</p>`
    : "";
  return `
    <article class="so-fixture-row${played ? " so-fixture-row--played" : ""}" style="--league-color:${color}" data-fixture-id="${fixtureId}">
      <div class="so-fixture-row__time">${formatTime(row.kickoff_utc)}<br />${formatShortDate(row.date)}</div>
      <div class="so-fixture-row__body">
        <div class="so-fixture-row__teams">${fixtureLabel(row)}</div>
        <div class="so-fixture-row__meta so-fixture-row__meta--league">${row.league || "League TBC"} · ${row.season || "—"}</div>
        ${matchDataButton}
        ${reportList}
      </div>
      <div class="so-fixture-row__meta">
        <span class="so-pill ${watchClass}">${row.watch_type || "—"}</span>
        ${reportBadge}
      </div>
      <button type="button" class="so-fixture-row__remove" data-fixture-id="${fixtureId}" aria-label="Remove assignment">Remove</button>
    </article>
  `;
}

function renderStaffCards() {
  const staff = state.payload?.staff || [];
  if (els.staffSectionTitle) {
    els.staffSectionTitle.textContent = state.staff ? `${state.staff}` : "By scout";
  }

  if (!staff.length) {
    els.staffPanel.innerHTML = `<div class="card so-empty">${state.staff ? `${state.staff} has no assignments for these filters.` : state.period === "all" ? "No assignments yet. Head to the fixture planner to assign scouts to games." : `No assignments in ${periodLabel(state.period).toLowerCase()}.`}</div>`;
    return;
  }

  els.staffPanel.innerHTML = staff
    .map((row) => {
      const fixtures = (row.fixtures || []).slice().reverse();
      return `
        <article class="so-staff-card">
          <header class="so-staff-card__head">
            <h3 class="so-staff-card__name">${row.staff}</h3>
            <div class="so-staff-card__counts">
              <span class="so-pill so-pill--total">${row.total} total</span>
              <span class="so-pill so-pill--live">${row.live} live</span>
              <span class="so-pill so-pill--video">${row.video} video</span>
            </div>
          </header>
          <div class="so-staff-card__body">
            ${fixtures.length ? fixtures.map(renderFixtureRow).join("") : `<p class="so-empty">No fixtures</p>`}
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadSummary() {
  if (pendingDelete) {
    clearPendingDelete({ commit: true });
    hideUndoToast();
  }

  state.loading = true;
  renderSeasonToggle();
  renderStaffToggle();
  renderPeriodToggle();
  els.statusBar.textContent = "Loading scout summary…";

  try {
    const params = new URLSearchParams({
      include_past: "true",
    });
    if (state.season !== "ALL") {
      params.set("season", state.season);
    }
    if (state.staff) {
      params.set("staff", state.staff);
    }
    state.rawPayload = await fetchJson(`/api/fixture-planner/scout-summary?${params}`);
    await loadScoutingReports();
    applyViewPayload();
  } catch (error) {
    els.statusBar.textContent = error.message;
    els.staffPanel.innerHTML = `<div class="card so-empty">${error.message}</div>`;
  } finally {
    state.loading = false;
    renderSeasonToggle();
    renderStaffToggle();
    renderPeriodToggle();
  }
}

async function init() {
  const params = new URLSearchParams(window.location.search);
  const staffParam = params.get("staff");
  const periodParam = params.get("period");
  if (staffParam) {
    state.staff = staffParam;
  }
  if (periodParam && PERIOD_OPTIONS.some((row) => row.id === periodParam)) {
    state.period = periodParam;
  }

  els.refreshBtn?.addEventListener("click", () => loadSummary());

  els.matchModal?.addEventListener("click", (event) => {
    if (event.target.closest("[data-close-modal]")) {
      closeMatchModal();
      return;
    }
    handleMatchModalPlayerClick(event);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && stateMatchData.modalFixtureId) {
      closeMatchModal();
    }
  });

  els.staffPanel?.addEventListener("click", (event) => {
    const loadBtn = event.target.closest(".so-fixture-row__load");
    if (loadBtn && !loadBtn.disabled) {
      const fixtureId = loadBtn.dataset.fixtureId;
      const row = findFixtureRow(state.rawPayload || state.payload, fixtureId);
      if (!row) return;
      openMatchModal(row);
      return;
    }

    const btn = event.target.closest(".so-fixture-row__remove");
    if (!btn || btn.disabled || state.loading) return;
    const fixtureId = btn.dataset.fixtureId;
    if (!fixtureId) return;
    queueAssignmentRemoval(fixtureId);
  });

  els.undoToastBtn?.addEventListener("click", () => undoPendingDelete());

  try {
    state.meta = await fetchJson("/api/fixture-planner/meta");
    renderStaffToggle();
    renderPeriodToggle();
    syncUrlParams();
    renderSeasonToggle();
    await loadScoutingReports();
    await loadSummary();
  } catch (error) {
    els.statusBar.textContent = error.message;
  }
}

init();
