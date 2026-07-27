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

  const state = {
    loading: false,
    building: false,
    period: "season",
    position: "ALL",
    year: null,
    month: null,
    players: [],
    leagues: [],
    positions: [],
    profilesByPosition: {},
    profiles: [],
    weights: {},
    weightsByPosition: {},
    pollTimer: null,
  };

  const els = {
    seasonLabel: document.getElementById("seasonLabel"),
    pageNote: document.getElementById("pageNote"),
    statusBanner: document.getElementById("statusBanner"),
    leagueGrid: document.getElementById("leagueGrid"),
    periodGroup: document.getElementById("periodGroup"),
    monthWrap: document.getElementById("monthWrap"),
    monthSelect: document.getElementById("monthSelect"),
    positionGroup: document.getElementById("positionGroup"),
    minMinutes: document.getElementById("minMinutes"),
    minAge: document.getElementById("minAge"),
    maxAge: document.getElementById("maxAge"),
    minHeight: document.getElementById("minHeight"),
    clubFilter: document.getElementById("clubFilter"),
    perLeague: document.getElementById("perLeague"),
    weightsGrid: document.getElementById("weightsGrid"),
    weightsHint: document.getElementById("weightsHint"),
    refreshBtn: document.getElementById("refreshBtn"),
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

  function playerHref(p) {
    const id = p.playerId ?? p.player_id ?? null;
    if (id != null && id !== "") return `/player?id=${encodeURIComponent(id)}`;
    const composite = String(p.id || "");
    if (composite.includes(":")) {
      const tail = composite.split(":").pop();
      if (tail) return `/player?id=${encodeURIComponent(tail)}`;
    }
    return "/scouting";
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

  function profilesForCurrentPosition() {
    if (state.position === "ALL") return [];
    return state.profilesByPosition[state.position] || [];
  }

  function syncProfilesForPosition() {
    state.profiles = profilesForCurrentPosition();
    if (state.position === "ALL") {
      state.weights = {};
      return;
    }
    if (!state.weightsByPosition[state.position]) {
      state.weightsByPosition[state.position] = Object.fromEntries(
        state.profiles.map((p) => [p.apiName, DEFAULT_WEIGHT]),
      );
    }
    state.weights = { ...state.weightsByPosition[state.position] };
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

  function computeOverall(profileScores, profiles, weights) {
    let sum = 0;
    let wSum = 0;
    const fallbackValues = [];

    for (const profile of profiles) {
      const value = profileScores?.[profile.apiName];
      if (value == null) continue;
      fallbackValues.push(value);
      const w = weightFor(profile.apiName);
      if (state.position !== "ALL" && w <= 0) continue;
      if (state.position === "ALL") {
        sum += value;
        wSum += 1;
        continue;
      }
      sum += value * w;
      wSum += w;
    }

    if (wSum > 0) return sum / wSum;
    if (!fallbackValues.length) return 0;
    return fallbackValues.reduce((total, value) => total + value, 0) / fallbackValues.length;
  }

  function passesDemographicFilters(player) {
    const minMinutes = parseNum(els.minMinutes) ?? 0;
    const minAge = parseNum(els.minAge);
    const maxAge = parseNum(els.maxAge);
    const minHeight = parseNum(els.minHeight);
    const clubNeedle = (els.clubFilter?.value || "").trim().toLowerCase();

    if (minMinutes > 0) {
      const mins = Number(player.minutes) || 0;
      if (mins < minMinutes) return false;
    }
    if (minAge != null && (player.age == null || player.age < minAge)) return false;
    if (maxAge != null && (player.age == null || player.age > maxAge)) return false;
    if (minHeight != null) {
      const cm = parseHeightCm(player.height);
      if (cm == null || cm < minHeight) return false;
    }
    if (clubNeedle) {
      const club = String(player.club || "").toLowerCase();
      if (!club.includes(clubNeedle)) return false;
    }
    return true;
  }

  function rankedPool() {
    const profiles =
      state.position === "ALL"
        ? []
        : state.profiles.length
          ? state.profiles
          : profilesForCurrentPosition();

    return state.players
      .filter((p) => state.position === "ALL" || p.position === state.position)
      .filter((p) => passesDemographicFilters(p))
      .filter((p) => {
        if (state.position === "ALL") return true;
        return passesProfileFilters(p.profileScores, profiles, state.weights);
      })
      .map((p) => {
        const profileList =
          state.position === "ALL"
            ? state.profilesByPosition[p.position] || []
            : profiles;
        const overall = computeOverall(p.profileScores, profileList, state.weights);
        return { ...p, overall };
      })
      .sort((a, b) => {
        const diff = (b.overall || 0) - (a.overall || 0);
        if (Math.abs(diff) > 1e-9) return diff;
        return String(a.name || "").localeCompare(String(b.name || ""));
      });
  }

  function buildByLeague(pool) {
    const limit = Math.max(5, Math.min(25, parseNum(els.perLeague) || 10));
    const leagues = state.leagues.length ? state.leagues : [...new Set(pool.map((p) => p.league))];
    const blocks = [];

    for (const league of leagues) {
      const leaguePool = pool.filter((p) => p.league === league);
      const highest = leaguePool.length
        ? Math.max(...leaguePool.map((p) => Number(p.overall) || 0))
        : null;
      const thresholdPct = 85;
      const effective =
        highest != null ? Math.max(0, (thresholdPct / 100) * highest) : thresholdPct;

      const qualifying = leaguePool.filter((p) => (Number(p.overall) || 0) >= effective - 1e-9);
      let shown = qualifying.slice(0, limit);
      if (shown.length < limit) {
        const seen = new Set(shown.map((p) => p.id));
        for (const row of leaguePool) {
          if (shown.length >= limit) break;
          if (seen.has(row.id)) continue;
          shown.push(row);
          seen.add(row.id);
        }
      }

      blocks.push({
        league,
        players: shown,
        pool_count: leaguePool.length,
        qualify_count: qualifying.length,
        highest_overall: highest,
        min_score_effective: effective,
      });
    }
    return { blocks, limit };
  }

  function scoutCountCell(count, kind) {
    const value = Number(count) || 0;
    if (!value) return `<td class="col-scout"><span class="scout-dash">—</span></td>`;
    return `<td class="col-scout"><span class="scout-pill scout-pill--${kind}">${value}</span></td>`;
  }

  function playerRows(players) {
    return (players || [])
      .map((p, index) => {
        const mins =
          p.minutes == null || p.minutes === ""
            ? "—"
            : `${Number(p.minutes).toLocaleString()}′`;
        const href = playerHref(p);
        const scout = p.scout || {};
        const scoutTotal = Number(p.scout_total) || 0;
        const pos = posShort(p.positionLabel, p.position);
        const scoutedClass = scoutTotal ? " has-scout" : "";
        return `<tr class="${scoutedClass}">
          <td class="col-rank">${index + 1}</td>
          <td class="col-player"><a href="${href}">${p.name || "—"}</a></td>
          <td class="col-club" title="${p.club || ""}">${p.club || "—"}</td>
          <td class="col-pos" title="${p.positionLabel || p.position || ""}">${pos}</td>
          <td class="col-overall">${fmt(p.overall, 1)}</td>
          <td class="col-mins">${mins}</td>
          ${scoutCountCell(scout.live_watches, "live")}
          ${scoutCountCell(scout.video_watches, "video")}
          ${scoutCountCell(scout.report_count, "report")}
        </tr>`;
      })
      .join("");
  }

  function leagueTable(players) {
    return `<div class="league-scroll"><table class="scout-table">
      <colgroup>
        <col class="col-rank"><col class="col-player"><col class="col-club"><col class="col-pos">
        <col class="col-overall"><col class="col-mins"><col class="col-scout"><col class="col-scout"><col class="col-scout">
      </colgroup>
      <thead>
        <tr>
          <th class="col-rank">#</th>
          <th class="col-player">Player</th>
          <th class="col-club">Club</th>
          <th class="col-pos">Pos</th>
          <th class="col-overall">Ovr</th>
          <th class="col-mins">Mins</th>
          <th class="col-scout">Live</th>
          <th class="col-scout">Vid</th>
          <th class="col-scout">Rep</th>
        </tr>
      </thead>
      <tbody>${playerRows(players)}</tbody>
    </table></div>`;
  }

  function renderWeights() {
    syncProfilesForPosition();
    if (state.position === "ALL") {
      els.weightsHint.textContent =
        "Select a position to adjust profile sliders — all positions use equal-weight overall until then.";
      els.weightsGrid.innerHTML =
        '<p class="empty" style="padding:0.5rem 0">Pick GK, CB, CM, etc. above to weight profiles for that role.</p>';
      return;
    }

    els.weightsHint.textContent =
      "Drag sliders — 0 ignores a profile; higher sets a minimum score and adds weight to overall (same as Player Search).";

    els.weightsGrid.innerHTML = state.profiles
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
      .join("");

    els.weightsGrid.querySelectorAll(".weight-slider").forEach((slider) => {
      slider.addEventListener("input", (event) => {
        const key = event.target.dataset.profile;
        state.weights[key] = Number(event.target.value);
        state.weightsByPosition[state.position] = { ...state.weights };
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

  function renderGrid() {
    if (state.building) {
      els.leagueGrid.innerHTML = '<p class="empty">Building player pool — this can take a minute…</p>';
      return;
    }
    if (!state.players.length) {
      els.leagueGrid.innerHTML = '<p class="empty">No players loaded yet.</p>';
      return;
    }

    const pool = rankedPool();
    const { blocks, limit } = buildByLeague(pool);

    const cards = blocks
      .map((block) => {
        const players = block.players || [];
        const meta = block.highest_overall
          ? `≥85% of pool (= ${fmt(block.min_score_effective, 1)}) · ${block.qualify_count} qualify · pool ${block.pool_count}`
          : `pool ${block.pool_count}`;
        const body = players.length
          ? leagueTable(players)
          : `<p class="league-card__empty">No matches for current filters</p>`;
        return `<section class="league-card">
          <div class="league-card__head">
            <div>
              <h3 class="league-card__title">${block.league || "League"}</h3>
              <p class="league-card__meta">${meta}</p>
            </div>
            <span class="league-card__count">${players.length}/${limit}</span>
          </div>
          ${body}
        </section>`;
      })
      .join("");

    els.leagueGrid.innerHTML = cards || '<p class="empty">No leagues to show.</p>';

    const posLabel =
      state.position === "ALL"
        ? "all positions"
        : state.positions.find((p) => p.value === state.position)?.label || state.position;
    const note =
      state.period === "month"
        ? "Monthly overall uses league-relative profile percentiles."
        : "Season overall uses Impect PV profile ratings (0–100).";
    els.pageNote.textContent = `${note} Showing top ${limit} per league for ${posLabel} after filters. Live / Video / Reports from Fixture Planner — unscouted names are your priority targets.`;
  }

  function updateSeasonLabel(data) {
    const label =
      data?.period_label ||
      (data?.period === "month" ? data?.month_label : data?.season_label) ||
      "Full season";
    const limit = parseNum(els.perLeague) || data?.per_league_limit || 10;
    els.seasonLabel.textContent = `${label} · Top ${limit} per league (fills below 85% cut-off if needed)`;
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
      syncProfilesForPosition();
      updateSeasonLabel(data);
      renderWeights();
      renderGrid();
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

    els.positionGroup?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-position]");
      if (!btn) return;
      state.position = btn.dataset.position || "ALL";
      els.positionGroup.querySelectorAll(".filter__btn").forEach((el) => {
        el.classList.toggle("is-active", el === btn);
      });
      renderWeights();
      renderGrid();
    });

    [els.minMinutes, els.minAge, els.maxAge, els.minHeight, els.clubFilter, els.perLeague].forEach(
      (input) => {
        input?.addEventListener("input", () => {
          updateSeasonLabel({});
          renderGrid();
        });
      },
    );

    els.refreshBtn?.addEventListener("click", () => loadData({ refresh: true }));
  }

  async function init() {
    bindEvents();
    els.monthWrap.hidden = state.period !== "month";
    const options = defaultMonthOptions();
    fillMonths(options, options[0].year, options[0].month);

    try {
      const meta = await fetchJson("/api/who-to-scout/meta");
      state.profilesByPosition = meta.profiles_by_position || {};
      state.leagues = meta.leagues || [];
      state.positions = meta.positions || [];
      fillPositions(state.positions);
    } catch {
      /* meta optional — data endpoint includes profiles */
    }

    loadData();
  }

  init();
})();
