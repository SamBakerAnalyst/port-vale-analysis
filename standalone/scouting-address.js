const DEFAULT_SEASON = "26/27";
const ALLOWED_SEASONS = ["26/27", "25/26"];
const STADIUMS_URL = "/standalone/stadiums.json";
const UK_POSTCODE_RE = /^\s*[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\s*$/i;

const LEAGUE_META = {
  Championship: { color: "#ef4444", label: "Championship" },
  "League One": { color: "#3d8bfd", label: "League One" },
  "League Two": { color: "#34d399", label: "League Two" },
  "National League": { color: "#fbbf24", label: "National League" },
  "National League North": { color: "#f97316", label: "NL North" },
  "National League South": { color: "#ec4899", label: "NL South" },
  "Scottish Prem": { color: "#a78bfa", label: "Scottish Prem" },
  "Scottish Champ": { color: "#6366f1", label: "Scottish Champ" },
};

const LEAGUE_TO_FIXTURE = {
  Championship: "Championship",
  "League One": "League One",
  "League Two": "League Two",
  "National League": "National League",
  "Scottish Prem": "Scottish Prem",
};

const state = {
  meta: null,
  allStadiums: [],
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

let els = {};

function bindElements() {
  els = {
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
}

function leagueColor(leagueId) {
  return LEAGUE_META[leagueId]?.color || state.meta?.leagues?.find((row) => row.id === leagueId)?.color || "#34d399";
}

function leagueLabel(leagueId) {
  return LEAGUE_META[leagueId]?.label || state.meta?.leagues?.find((row) => row.id === leagueId)?.label || leagueId;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || payload.error || `Request failed (${response.status})`);
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

function buildMeta(stadiums) {
  const byLeague = {};
  stadiums.forEach((row) => {
    byLeague[row.league] = (byLeague[row.league] || 0) + 1;
  });
  return {
    leagues: Object.keys(LEAGUE_META).map((id) => ({
      id,
      ...LEAGUE_META[id],
      count: byLeague[id] || 0,
    })),
    stadium_count: stadiums.length,
    default_max_minutes: 60,
    seasons: ALLOWED_SEASONS,
  };
}

function normalizePostcode(query) {
  const compact = query.trim().replace(/\s+/g, "").toUpperCase();
  if (compact.length < 5 || compact.length > 8) return null;
  const candidate = `${compact.slice(0, -3)} ${compact.slice(-3)}`;
  return UK_POSTCODE_RE.test(candidate) ? candidate : null;
}

async function geocodePostcode(postcode) {
  const response = await fetch(`https://api.postcodes.io/postcodes/${encodeURIComponent(postcode)}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.result) {
    throw new Error(`Postcode not found: ${postcode}`);
  }
  const row = payload.result;
  const label = [row.admin_ward, row.postcode].filter(Boolean).join(", ");
  return {
    lat: row.latitude,
    lng: row.longitude,
    label: label || postcode,
    source: "postcodes.io",
  };
}

async function geocodeAddress(query) {
  const params = new URLSearchParams({
    q: query,
    limit: "1",
    lang: "en",
  });
  const response = await fetch(`https://photon.komoot.io/api/?${params}`);
  const payload = await response.json().catch(() => ({}));
  const row = (payload.features || []).find((feature) => {
    const country = feature.properties?.countrycode || feature.properties?.country;
    return !country || country === "GB" || country === "United Kingdom";
  });
  if (!row?.geometry?.coordinates) {
    throw new Error(`Address not found: ${query}`);
  }
  const [lng, lat] = row.geometry.coordinates;
  const props = row.properties || {};
  const label = [props.name, props.city, props.postcode].filter(Boolean).join(", ");
  return { lat, lng, label: label || query, source: "photon" };
}

async function geocodeQuery(query) {
  const cleaned = query.trim();
  if (!cleaned) throw new Error("Enter a scout address or postcode.");

  const postcode = normalizePostcode(cleaned);
  if (postcode) {
    try {
      return await geocodePostcode(postcode);
    } catch (error) {
      if (!UK_POSTCODE_RE.test(postcode)) throw error;
    }
  }

  return geocodeAddress(cleaned.includes(",") ? cleaned : `${cleaned}, UK`);
}

function haversineKm(lat1, lng1, lat2, lng2) {
  const radius = 6371;
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const dPhi = ((lat2 - lat1) * Math.PI) / 180;
  const dLambda = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dPhi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function estimateDriveMinutes(distanceKm) {
  if (distanceKm <= 0) return 0;
  return Math.max(1, Math.round((distanceKm / 88) * 60));
}

function computeReachable(origin, stadiums, maxMinutes) {
  return stadiums
    .map((stadium) => {
      const distanceKm = haversineKm(origin.lat, origin.lng, stadium.lat, stadium.lng);
      return {
        ...stadium,
        drive_minutes: estimateDriveMinutes(distanceKm),
        drive_source: "estimate",
      };
    })
    .filter((row) => row.drive_minutes <= maxMinutes)
    .sort((a, b) => a.drive_minutes - b.drive_minutes);
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
  els.mapLegend.innerHTML = (state.meta?.leagues || [])
    .map(
      (league) => `
        <span class="sa-legend__item">
          <span class="sa-legend__dot" style="background:${league.color}"></span>
          ${league.label}
        </span>`
    )
    .join("");
}

function clearMarkers() {
  state.markers.forEach((marker) => marker.remove());
  state.markers = [];
}

function initMap() {
  state.map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: true,
    preferCanvas: true,
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
      const marker = L.circleMarker([stadium.lat, stadium.lng], {
        radius: 6,
        fillColor: color,
        color: "#fff",
        weight: 2,
        fillOpacity: dimmed ? 0.2 : 0.9,
        opacity: dimmed ? 0.35 : 1,
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

  state.originMarker = L.circleMarker([state.origin.lat, state.origin.lng], {
    radius: 8,
    fillColor: "#fff",
    color: "#34d399",
    weight: 3,
    fillOpacity: 1,
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
  state.map.fitBounds(L.latLngBounds(points).pad(0.08));
}

function renderSummary() {
  if (!state.origin) {
    els.summaryPanel.innerHTML =
      '<p class="sa-summary__empty">Enter a scout address to highlight reachable stadiums and upcoming fixtures.</p>';
    return;
  }

  const maxMinutes = Number(els.maxMinutes.value || 60);
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
    ...new Set(state.reachable.map((row) => LEAGUE_TO_FIXTURE[row.league]).filter(Boolean)),
  ];

  if (!fixtureLeagues.length) {
    state.fixtures = [];
    renderFixtures();
    return;
  }

  try {
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
        kickoff: fixture.kickoff_utc
          ? new Date(fixture.kickoff_utc).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
          : "",
        date_label: fixture.date
          ? new Date(fixture.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
          : "TBC",
      }))
      .sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  } catch {
    state.fixtures = [];
  }

  renderFixtures();
}

function applyStadiumFilter() {
  const allowed = new Set(selectedLeagues());
  state.stadiums = state.allStadiums.filter((row) => allowed.has(row.league));
  renderStadiumMarkers();
}

async function loadStadiums() {
  const response = await fetch(STADIUMS_URL);
  if (!response.ok) {
    throw new Error("Stadium database not found. Check that standalone/stadiums.json exists.");
  }
  const stadiums = await response.json();
  state.allStadiums = stadiums.filter((row) => row.lat != null && row.lng != null);
  state.meta = buildMeta(state.allStadiums);
  applyStadiumFilter();
}

function applySearchResults() {
  const maxMinutes = Number(els.maxMinutes.value || 60);
  const allowed = new Set(selectedLeagues());
  const pool = state.allStadiums.filter((row) => allowed.has(row.league));
  state.reachable = computeReachable(state.origin, pool, maxMinutes);
  state.reachableClubs = new Set(state.reachable.map((row) => row.club));
  renderOriginMarker();
  renderStadiumMarkers();
  renderSummary();
}

async function runSearch() {
  const query = els.addressInput.value.trim();
  if (!query) {
    setStatus("Enter a scout address or postcode.", "warn");
    return;
  }

  state.loading = true;
  setStatus("Looking up address and calculating drive times…", "info");
  els.searchBtn.disabled = true;

  try {
    state.origin = await geocodeQuery(query);
    applySearchResults();
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
    applyStadiumFilter();
    if (state.origin) {
      applySearchResults();
      await loadFixturesForReachable();
    }
  });

  els.seasonToggle.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-season]");
    if (!button) return;
    state.season = button.dataset.season;
    renderSeasonToggle();
    if (state.origin) await loadFixturesForReachable();
  });

  els.maxMinutes.addEventListener("change", () => {
    if (state.origin) {
      applySearchResults();
      loadFixturesForReachable();
    }
  });
}

async function init() {
  bindElements();
  initMap();
  bindEvents();
  try {
    state.leagues = [];
    await loadStadiums();
    renderLeagueToggle();
    renderSeasonToggle();
    renderLegend();
    requestAnimationFrame(() => {
      state.map.invalidateSize();
      fitMapToView();
    });
    setStatus(`${state.meta.stadium_count} stadiums loaded across ${state.meta.leagues.length} leagues`);
  } catch (error) {
    setStatus(error.message || "Failed to load scouting address tool.", "error");
  }
}

init();
