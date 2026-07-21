const DEFAULT_SEASON = "26/27";
const ALLOWED_SEASONS = ["26/27", "25/26"];

const LEAGUE_TO_FIXTURE = {
  Championship: "Championship",
  "League One": "League One",
  "League Two": "League Two",
  "National League": "National League",
  "Scottish Prem": "Scottish Prem",
};

const state = {
  meta: null,
  stadiums: [],
  leagues: [],
  season: DEFAULT_SEASON,
  origin: null,
  reachable: [],
  reachableClubs: new Set(),
  fixtures: [],
  loading: false,
  map: null,
  markers: [],
  originMarker: null,
  radiusCircle: null,
};

const els = {
  addressInput: document.getElementById("addressInput"),
  searchBtn: document.getElementById("searchBtn"),
  maxMinutes: document.getElementById("maxMinutes"),
  leagueToggle: document.getElementById("leagueToggle"),
  seasonToggle: document.getElementById("seasonToggle"),
  mapLegend: document.getElementById("mapLegend"),
  summaryPanel: document.getElementById("summaryPanel"),
  fixturesList: document.getElementById("fixturesList"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
};

function leagueColor(leagueId) {
  return state.meta?.leagues?.find((row) => row.id === leagueId)?.color || "#34d399";
}

function leagueLabel(leagueId) {
  return state.meta?.leagues?.find((row) => row.id === leagueId)?.label || leagueId;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `Request failed (${response.status})`);
  }
  return payload;
}

function setStatus(message, kind) {
  els.statusBar.textContent = message;
  if (!kind) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.textContent = message;
  els.statusBanner.className = `fp-status fp-status--${kind}`;
  els.statusBanner.classList.remove("hidden");
}

function selectedLeagues() {
  return state.leagues.length ? state.leagues : state.meta?.leagues?.map((row) => row.id) || [];
}

function renderLeagueToggle() {
  if (!state.meta?.leagues) return;
  els.leagueToggle.innerHTML = state.meta.leagues
    .map((league) => {
      const active = state.leagues.includes(league.id) || !state.leagues.length;
      return `
        <button type="button"
          class="fp-league-btn${active ? " fp-league-btn--active" : ""}"
          data-league="${league.id}"
          style="--league-color:${league.color}">
          ${league.label}
          <span class="fp-league-btn__count">${league.count}</span>
        </button>`;
    })
    .join("");
}

function renderSeasonToggle() {
  els.seasonToggle.innerHTML = ALLOWED_SEASONS.map(
    (season) => `
      <button type="button"
        class="fp-season-btn${state.season === season ? " fp-season-btn--active" : ""}"
        data-season="${season}">
        ${season}
      </button>`
  ).join("");
}

function renderLegend() {
  const leagues = state.meta?.leagues || [];
  els.mapLegend.innerHTML = leagues
    .map(
      (league) => `
        <span class="sa-legend__item">
          <span class="sa-legend__dot" style="background:${league.color}"></span>
          ${league.label}
        </span>`
    )
    .join("");
}

function makeMarkerIcon(color, dimmed) {
  const opacity = dimmed ? 0.25 : 1;
  return L.divIcon({
    className: "sa-marker",
    html: `<span style="display:block;width:12px;height:12px;border-radius:50%;background:${color};border:2px solid rgba(255,255,255,.85);box-shadow:0 0 0 1px rgba(0,0,0,.35);opacity:${opacity}"></span>`,
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  });
}

function clearMarkers() {
  state.markers.forEach((marker) => marker.remove());
  state.markers = [];
}

function initMap() {
  state.map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: true,
  }).setView([54.5, -3.5], 6);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
  }).addTo(state.map);
}

function renderStadiumMarkers() {
  if (!state.map) return;
  clearMarkers();
  const allowed = new Set(selectedLeagues());
  const hasReachable = state.reachable.length > 0;

  state.stadiums
    .filter((row) => allowed.has(row.league))
    .forEach((stadium) => {
      const reachable = hasReachable && state.reachableClubs.has(stadium.club);
      const dimmed = hasReachable && !reachable;
      const color = leagueColor(stadium.league);
      const marker = L.marker([stadium.lat, stadium.lng], {
        icon: makeMarkerIcon(color, dimmed),
      }).addTo(state.map);

      const driveInfo = reachable
        ? state.reachable.find((row) => row.club === stadium.club)
        : null;

      marker.bindPopup(`
        <strong>${stadium.club}</strong><br />
        ${stadium.stadium}, ${stadium.city}<br />
        <span style="color:${color};font-weight:600">${leagueLabel(stadium.league)}</span>
        ${driveInfo ? `<br /><span style="color:#34d399">${driveInfo.drive_minutes} min drive</span>` : ""}
      `);
      state.markers.push(marker);
    });
}

function renderOriginMarker() {
  if (state.originMarker) {
    state.originMarker.remove();
    state.originMarker = null;
  }
  if (state.radiusCircle) {
    state.radiusCircle.remove();
    state.radiusCircle = null;
  }
  if (!state.origin || !state.map) return;

  state.originMarker = L.marker([state.origin.lat, state.origin.lng], {
    icon: L.divIcon({
      className: "sa-origin-marker",
      html: `<span style="display:block;width:16px;height:16px;border-radius:50%;background:#fff;border:3px solid #34d399;box-shadow:0 0 0 2px rgba(52,211,153,.35)"></span>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    }),
  })
    .addTo(state.map)
    .bindPopup(`<strong>Scout location</strong><br />${state.origin.label || ""}`);

  const maxMinutes = Number(els.maxMinutes.value || 60);
  const radiusKm = (maxMinutes / 60) * 88;
  state.radiusCircle = L.circle([state.origin.lat, state.origin.lng], {
    radius: radiusKm * 1000,
    color: "#34d399",
    fillColor: "#34d399",
    fillOpacity: 0.08,
    weight: 1.5,
    dashArray: "6 4",
  }).addTo(state.map);
}

function fitMapToView() {
  if (!state.map) return;
  const points = [];
  if (state.origin) points.push([state.origin.lat, state.origin.lng]);
  state.stadiums
    .filter((row) => selectedLeagues().includes(row.league))
    .forEach((row) => points.push([row.lat, row.lng]));
  if (!points.length) return;
  const bounds = L.latLngBounds(points);
  state.map.fitBounds(bounds.pad(0.08));
}

function renderSummary() {
  if (!state.origin) {
    els.summaryPanel.innerHTML =
      '<p class="sa-summary__empty">Enter a scout address to highlight reachable stadiums and upcoming fixtures.</p>';
    return;
  }

  const maxMinutes = Number(els.maxMinutes.value || 60);
  const byLeague = {};
  state.reachable.forEach((row) => {
    byLeague[row.league] = (byLeague[row.league] || 0) + 1;
  });

  els.summaryPanel.innerHTML = `
    <p class="sa-origin-label">${state.origin.label || "Scout location"}</p>
    <div class="sa-summary__stats">
      <div class="sa-stat">
        <span class="sa-stat__label">Reachable within ${maxMinutes} min</span>
        <span class="sa-stat__value">${state.reachable.length}</span>
      </div>
      <div class="sa-stat">
        <span class="sa-stat__label">Upcoming fixtures</span>
        <span class="sa-stat__value">${state.fixtures.length}</span>
      </div>
    </div>
    <div class="sa-reachable-list">
      ${state.reachable
        .slice(0, 30)
        .map(
          (row) => `
            <div class="sa-reachable-item">
              <div>
                <div class="sa-reachable-item__club">${row.club}</div>
                <div class="sa-reachable-item__meta">${row.stadium} · <span class="sa-league-pill" style="background:${leagueColor(row.league)}">${leagueLabel(row.league)}</span></div>
              </div>
              <div class="sa-reachable-item__time">${row.drive_minutes}m</div>
            </div>`
        )
        .join("")}
      ${state.reachable.length > 30 ? `<p class="sa-summary__empty">+ ${state.reachable.length - 30} more stadiums</p>` : ""}
    </div>
  `;
}

function normalizeClub(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/fc|afc|town|city|united|athletic|rovers|county|borough|&/g, "")
    .replace(/[^a-z0-9]/g, "");
}

function clubMatchesFixtureHome(homeTeam, club) {
  const a = normalizeClub(homeTeam);
  const b = normalizeClub(club);
  return a.includes(b) || b.includes(a);
}

function renderFixtures() {
  if (!state.origin) {
    els.fixturesList.innerHTML =
      '<p class="sa-summary__empty">Fixtures at reachable grounds will appear here.</p>';
    return;
  }

  const fixtureLeagues = new Set(
    state.reachable.map((row) => LEAGUE_TO_FIXTURE[row.league]).filter(Boolean)
  );

  if (!fixtureLeagues.size) {
    els.fixturesList.innerHTML =
      '<p class="sa-summary__empty">Fixture data is available for League One, League Two, National League and Scottish Prem. EFL Championship, NL North/South and Scottish Champ show reachable stadiums on the map only.</p>';
    return;
  }

  if (!state.fixtures.length) {
    els.fixturesList.innerHTML =
      '<p class="sa-summary__empty">No upcoming fixtures at reachable grounds for the selected season.</p>';
    return;
  }

  els.fixturesList.innerHTML = state.fixtures
    .slice(0, 80)
    .map((fixture) => {
      const color = leagueColor(fixture.league);
      const reachable = state.reachable.find((row) => clubMatchesFixtureHome(fixture.home, row.club));
      return `
        <article class="sa-fixture-row${reachable ? "" : " sa-fixture-row--dim"}">
          <div class="sa-fixture-date">${fixture.date_label || fixture.date || "TBC"}</div>
          <div>
            <div class="sa-fixture-match">${fixture.home} vs ${fixture.away}</div>
            <div class="sa-fixture-meta">
              <span class="sa-league-pill" style="background:${color}">${leagueLabel(fixture.league)}</span>
              ${fixture.kickoff ? ` · ${fixture.kickoff}` : ""}
            </div>
          </div>
          <div class="sa-fixture-time">${reachable ? `${reachable.drive_minutes}m` : ""}</div>
        </article>`;
    })
    .join("");
}

async function loadFixturesForReachable() {
  const fixtureLeagues = [
    ...new Set(
      state.reachable
        .map((row) => LEAGUE_TO_FIXTURE[row.league])
        .filter(Boolean)
    ),
  ];

  if (!fixtureLeagues.length) {
    state.fixtures = [];
    renderFixtures();
    return;
  }

  const payload = await fetchJson(`/api/fixture-planner/fixtures?season=${encodeURIComponent(state.season)}`);
  const fixtures = payload.fixtures || [];
  const now = Date.now();

  state.fixtures = fixtures
    .filter((fixture) => {
      if (!fixtureLeagues.includes(fixture.league)) return false;
      const homeName = fixture.home?.name || fixture.home || "";
      const homeReachable = state.reachable.some((row) => clubMatchesFixtureHome(homeName, row.club));
      if (!homeReachable) return false;
      if (!fixture.date) return true;
      const when = new Date(fixture.date).getTime();
      return Number.isNaN(when) || when >= now - 86400000;
    })
    .map((fixture) => ({
      ...fixture,
      home: fixture.home?.name || fixture.home || "TBC",
      away: fixture.away?.name || fixture.away || "TBC",
      kickoff: fixture.kickoff_utc ? new Date(fixture.kickoff_utc).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "",
      date_label: fixture.date ? new Date(fixture.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : "TBC",
    }))
    .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));

  renderFixtures();
}

async function loadStadiums() {
  const leagues = selectedLeagues();
  const params = leagues.length ? `?leagues=${encodeURIComponent(leagues.join(","))}` : "";
  const payload = await fetchJson(`/api/scouting-address/stadiums${params}`);
  state.stadiums = payload.stadiums || [];
  renderStadiumMarkers();
}

async function runSearch() {
  const query = els.addressInput.value.trim();
  if (!query) {
    setStatus("Enter a scout address or postcode.", "warn");
    return;
  }

  state.loading = true;
  setStatus("Geocoding address and calculating drive times…", "info");
  els.searchBtn.disabled = true;

  try {
    const geocoded = await fetchJson(`/api/scouting-address/geocode?q=${encodeURIComponent(query)}`);
    state.origin = geocoded;

    const reachablePayload = await fetchJson("/api/scouting-address/reachable", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lat: geocoded.lat,
        lng: geocoded.lng,
        max_minutes: Number(els.maxMinutes.value || 60),
        leagues: selectedLeagues(),
      }),
    });

    state.reachable = reachablePayload.reachable || [];
    state.reachableClubs = new Set(state.reachable.map((row) => row.club));

    renderOriginMarker();
    renderStadiumMarkers();
    renderSummary();
    await loadFixturesForReachable();

    if (state.origin && state.reachable.length) {
      const bounds = L.latLngBounds([
        [state.origin.lat, state.origin.lng],
        ...state.reachable.map((row) => [row.lat, row.lng]),
      ]);
      state.map.fitBounds(bounds.pad(0.1));
    }

    setStatus(
      `${state.reachable.length} stadiums reachable within ${els.maxMinutes.value} minutes · ${state.fixtures.length} upcoming fixtures`,
      "ok"
    );
  } catch (error) {
    setStatus(error.message || "Search failed.", "error");
  } finally {
    state.loading = false;
    els.searchBtn.disabled = false;
  }
}

function bindEvents() {
  els.searchBtn.addEventListener("click", runSearch);
  els.addressInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") runSearch();
  });

  els.leagueToggle.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-league]");
    if (!button) return;
    const league = button.dataset.league;
    const all = state.meta.leagues.map((row) => row.id);
    if (!state.leagues.length) {
      state.leagues = all.filter((id) => id !== league);
    } else if (state.leagues.includes(league)) {
      state.leagues = state.leagues.filter((id) => id !== league);
    } else {
      state.leagues = [...state.leagues, league];
    }
    if (state.leagues.length === all.length) state.leagues = [];
    renderLeagueToggle();
    await loadStadiums();
    if (state.origin) await runSearch();
  });

  els.seasonToggle.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-season]");
    if (!button) return;
    state.season = button.dataset.season;
    renderSeasonToggle();
    if (state.origin) await loadFixturesForReachable();
  });

  els.maxMinutes.addEventListener("change", () => {
    if (state.origin) runSearch();
  });
}

async function init() {
  initMap();
  bindEvents();
  try {
    state.meta = await fetchJson("/api/scouting-address/meta");
    state.leagues = [];
    renderLeagueToggle();
    renderSeasonToggle();
    renderLegend();
    await loadStadiums();
    fitMapToView();
    setStatus(`${state.meta.stadium_count} stadiums loaded across ${state.meta.leagues.length} leagues`);
  } catch (error) {
    setStatus(error.message || "Failed to load scouting address tool.", "error");
  }
}

init();
