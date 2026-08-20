(() => {
  const API = window.location.origin;
  const SEASON_GAMES = 46;
  const DEFAULT_METRIC = "points";

  const els = {
    status: document.getElementById("statusBanner"),
    subtitle: document.getElementById("pageSubtitle"),
    updated: document.getElementById("lastUpdated"),
    refresh: document.getElementById("refreshBtn"),
    present: document.getElementById("presentBtn"),
    exportBtn: document.getElementById("exportBtn"),
    deck: document.getElementById("stDeck"),
    deckStage: document.getElementById("deckStage"),
    deckFit: document.getElementById("deckFit"),
    deckPrev: document.getElementById("deckPrev"),
    deckNext: document.getElementById("deckNext"),
    deckExit: document.getElementById("deckExit"),
    deckCounter: document.getElementById("deckCounter"),
    badge: document.getElementById("summaryBadge"),
    headline: document.getElementById("summaryHeadline"),
    meta: document.getElementById("summaryMeta"),
    kpiPlayed: document.getElementById("kpiPlayed"),
    kpiPoints: document.getElementById("kpiPoints"),
    kpiProj: document.getElementById("kpiProj"),
    kpiPos: document.getElementById("kpiPos"),
    paceTitle: document.getElementById("paceTitle"),
    paceHint: document.getElementById("paceHint"),
    pills: document.getElementById("metricPills"),
    chart: document.getElementById("pointsChart"),
    metrics: document.getElementById("metricsGrid"),
    styleGrid: document.getElementById("styleGrid"),
    playersHint: document.getElementById("playersHint"),
    playersHead: document.getElementById("playersHead"),
    playersBody: document.getElementById("playersBody"),
    minMinutes: document.getElementById("minMinutes"),
    legend: document.querySelector(".st-legend"),
    timingChart: document.getElementById("timingChart"),
    timingSide: document.getElementById("timingSide"),
    goalsHint: document.getElementById("goalsHint"),
    extras: document.getElementById("extrasRow"),
    resultsBody: document.getElementById("resultsBody"),
    source: document.getElementById("sourceNote"),
  };

  const PLAYER_COLS = [
    { key: "name", label: "Player", sort: "name" },
    { key: "position_short", label: "Pos", sort: "position_short" },
    { key: "minutes", label: "Mins", sort: "minutes", digits: 0 },
    { key: "appearances", label: "Apps", sort: "appearances", digits: 0 },
    { key: "defenders_bypassed", label: "Def byp", sort: "defenders_bypassed", digits: 0, p90: true },
    { key: "ball_progression", label: "Prog", sort: "ball_progression", digits: 0, p90: true },
    { key: "xg_for", label: "xG", sort: "xg_for", digits: 1, p90: true },
    { key: "duel_rate", label: "Duel %", sort: "duel_rate", digits: 1 },
    { key: "offensive_interventions", label: "OI", sort: "offensive_interventions", digits: 0, p90: true },
    { key: "defensive_interventions", label: "DI", sort: "defensive_interventions", digits: 0, p90: true },
    { key: "ball_wins_defenders", label: "Vs DEF", sort: "ball_wins_defenders", digits: 0, p90: true },
    { key: "altered_threat", label: "PXT", sort: "altered_threat", digits: 1, p90: true },
    { key: "packing_xg", label: "PxG", sort: "packing_xg", digits: 1, p90: true },
  ];

  const state = {
    data: null,
    metric: hashMetric(),
    competition: new URLSearchParams(location.search).get("competition") || "League Two",
    playerSort: { key: "minutes", dir: "desc" },
    presenting: false,
    slide: 0,
    exporting: false,
  };

  function hashMetric() {
    const raw = (location.hash || "").replace(/^#/, "").trim();
    return raw || DEFAULT_METRIC;
  }

  function setStatus(message, kind = "") {
    if (!message) {
      els.status.className = "st-status hidden";
      els.status.textContent = "";
      return;
    }
    els.status.className = `st-status${kind ? ` st-status--${kind}` : ""}`;
    els.status.textContent = message;
  }

  function statusLabel(status, benchmarkSet) {
    const pack = benchmarkSet === "league_pack";
    if (status === "ahead") return pack ? "Ahead of top 7" : "Ahead of auto";
    if (status === "behind") return pack ? "Behind top 7" : "Behind auto";
    if (status === "awaiting") return "Kick-off ready";
    return pack ? "On track vs top 7" : "On track vs auto";
  }

  function statusClass(status) {
    if (status === "ahead") return "ahead";
    if (status === "behind") return "behind";
    if (status === "awaiting") return "awaiting";
    return "track";
  }

  function fmt(value, digits = 0) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    return digits > 0 ? n.toFixed(digits) : String(Math.round(n));
  }

  function signed(value, digits = 1) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toFixed(digits)}`;
  }

  function metricById(data, id) {
    const rows = data.metrics || [];
    return rows.find((row) => row.id === id) || rows[0] || null;
  }

  function pillHtml(metric) {
    const active = metric.id === state.metric ? " is-active" : "";
    return `<button type="button" class="st-pill${active}" data-metric="${metric.id}" role="tab" aria-selected="${metric.id === state.metric}">${metric.label}</button>`;
  }

  function syncUrl() {
    const params = new URLSearchParams(location.search);
    if (state.competition) params.set("competition", state.competition);
    else params.delete("competition");
    if (state.presenting) params.set("present", "1");
    else params.delete("present");
    const query = params.toString();
    const hash = state.metric && state.metric !== DEFAULT_METRIC ? `#${state.metric}` : "";
    const next = `${location.pathname}${query ? `?${query}` : ""}${hash || (state.metric === DEFAULT_METRIC ? "#points" : "")}`;
    history.replaceState(null, "", next);
  }

  function selectMetric(id, { skipUrl } = {}) {
    if (!id) return;
    state.metric = id;
    if (!skipUrl) syncUrl();
    if (!state.data) return;
    renderPills(state.data);
    renderPaceChart(state.data);
    renderMetrics(state.data);
  }

  function renderSummary(data) {
    const s = data.summary || {};
    const status = s.status || "on_track";
    els.badge.textContent = statusLabel(status, "promotion");
    els.badge.className = `st-summary__badge is-${statusClass(status)}`;
    const competition = data.competition || "League";
    const club = data.club || "Port Vale";
    if (data.kickoff_ready) {
      els.headline.textContent = `${club} · ${competition} ${data.season || ""} · waiting for kick-off · auto target ${fmt(s.auto_target, 1)} pts`;
    } else {
      const proj = s.projected_points;
      const auto = s.auto_target;
      const delta = s.delta_vs_auto;
      els.headline.textContent =
        proj == null
          ? `${club} · waiting for league fixtures`
          : `Projected ${fmt(proj, 1)} pts · auto target ${fmt(auto, 1)} (${signed(delta)})`;
    }
    els.meta.textContent = `${competition} ${data.season || ""} · ${data.played}/${SEASON_GAMES} played · ${data.games_remaining} remaining · pos ${data.position ?? "—"}`;
    els.kpiPlayed.textContent = fmt(data.played);
    els.kpiPoints.textContent = fmt(metricById(data, "points")?.current);
    els.kpiProj.textContent = data.kickoff_ready ? "—" : fmt(s.projected_points, 1);
    els.kpiPos.textContent = data.position != null ? String(data.position) : "—";
    els.subtitle.textContent = `${club} · ${competition} pace vs promotion benchmarks`;
  }

  function renderPills(data) {
    els.pills.innerHTML = (data.metrics || []).map(pillHtml).join("");
  }

  function renderPaceChart(data) {
    const metric = metricById(data, state.metric) || metricById(data, DEFAULT_METRIC);
    if (!metric) {
      els.chart.innerHTML = "";
      return;
    }
    const series = data.series || data.points_series || [];
    const bench = metric.benchmarks || {};
    const labels = metric.benchmark_labels || { playoff: "PO", auto: "Auto", champion: "Champ" };
    const rateChart = metric.chart === "running_rate";
    const played = data.played || 0;
    const key = metric.id;
    const values = series.map((row) => Number(row[key] ?? 0));
    const current = values.length ? values[values.length - 1] : Number(metric.current || 0);
    const projected = !rateChart && metric.project && played > 0 ? (current / played) * SEASON_GAMES : null;

    els.paceTitle.textContent = `${metric.label} pace · season track`;
    const packNote = metric.benchmark_set === "league_pack"
      ? " Dashed = this season’s league / top-7 / top-3."
      : " Dashed = season targets.";
    const lowerNote = metric.lower_is_better ? " Lower is better — finishing below the target line is good." : "";
    els.paceHint.textContent = data.kickoff_ready
      ? `No league games yet. Target lines are ready for kick-off.${lowerNote}`
      : `${metric.hint || "Cumulative pace through the season."}${packNote}${lowerNote}`;
    if (els.legend) {
      els.legend.innerHTML = `
        <span class="st-legend__item st-legend__item--vale"><i></i>Port Vale actual</span>
        ${rateChart ? "" : `<span class="st-legend__item st-legend__item--proj"><i></i>Projected finish</span>`}
        <span class="st-legend__item st-legend__item--champ"><i></i>${labels.champion}</span>
        <span class="st-legend__item st-legend__item--auto"><i></i>${labels.auto}</span>
        <span class="st-legend__item st-legend__item--po"><i></i>${labels.playoff}</span>`;
    }

    els.chart.innerHTML = buildPaceSvg(data, metric, { w: 1000, h: 320 });
  }

  function buildPaceSvg(data, metric, { w = 1000, h = 320 } = {}) {
    const series = data.series || data.points_series || [];
    const bench = metric.benchmarks || {};
    const rateChart = metric.chart === "running_rate";
    const played = data.played || 0;
    const key = metric.id;
    const values = series.map((row) => Number(row[key] ?? 0));
    const current = values.length ? values[values.length - 1] : Number(metric.current || 0);
    const projected = !rateChart && metric.project && played > 0 ? (current / played) * SEASON_GAMES : null;
    const W = w;
    const H = h;
    const pad = { l: 48, r: 18, t: 22, b: 36 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;

    let yMin = Math.min(0, ...values, projected ?? 0, bench.champion || 0, bench.auto || 0, bench.playoff || 0);
    let yMax = Math.max(1, ...values, projected ?? 0, bench.champion || 0, bench.auto || 0, bench.playoff || 0, current);
    if (rateChart) {
      yMin = 0;
      yMax = Math.max(yMax, 40, metric.unit === "%" ? 100 : yMax);
    } else if (metric.lower_is_better) {
      yMin = 0;
    }
    if (yMin === yMax) yMax = yMin + 1;
    const padY = Math.max(1, (yMax - yMin) * 0.08);
    yMax += padY;
    if (yMin < 0) yMin -= padY;

    const x = (game) => pad.l + (game / SEASON_GAMES) * innerW;
    const y = (val) => pad.t + innerH - ((val - yMin) / (yMax - yMin)) * innerH;

    const yStep = yMax - yMin > 80 ? 20 : yMax - yMin > 30 ? 10 : yMax - yMin > 12 ? 5 : 2;
    const grid = [];
    for (let g = 0; g <= SEASON_GAMES; g += 5) {
      grid.push(`<line x1="${x(g)}" y1="${pad.t}" x2="${x(g)}" y2="${pad.t + innerH}" stroke="rgba(255,255,255,0.05)" />`);
      grid.push(`<text x="${x(g)}" y="${H - 10}" fill="#8b9bb0" font-size="11" text-anchor="middle">${g}</text>`);
    }
    const startTick = Math.ceil(yMin / yStep) * yStep;
    for (let p = startTick; p <= yMax; p += yStep) {
      grid.push(`<line x1="${pad.l}" y1="${y(p)}" x2="${pad.l + innerW}" y2="${y(p)}" stroke="rgba(255,255,255,0.05)" />`);
      grid.push(`<text x="${pad.l - 8}" y="${y(p) + 3}" fill="#8b9bb0" font-size="11" text-anchor="end">${Number.isInteger(p) ? p : p.toFixed(1)}</text>`);
    }

    function targetLine(value, color) {
      if (value == null) return "";
      if (rateChart) {
        return `<line x1="${x(0)}" y1="${y(value)}" x2="${x(SEASON_GAMES)}" y2="${y(value)}" stroke="${color}" stroke-width="2" stroke-dasharray="6 5" opacity="0.9" />`;
      }
      return `<line x1="${x(0)}" y1="${y(0)}" x2="${x(SEASON_GAMES)}" y2="${y(value)}" stroke="${color}" stroke-width="2" stroke-dasharray="6 5" opacity="0.9" />`;
    }

    let valePath = "";
    if (series.length) {
      const pts = (rateChart ? [] : [`${x(0)},${y(0)}`]).concat(
        series.map((row) => `${x(row.played)},${y(Number(row[key] ?? 0))}`),
      );
      valePath = `<polyline fill="none" stroke="#f5c518" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" points="${pts.join(" ")}" />`;
    }

    let projPath = "";
    if (projected != null && played > 0) {
      projPath = `<line x1="${x(played)}" y1="${y(current)}" x2="${x(SEASON_GAMES)}" y2="${y(projected)}" stroke="#fde68a" stroke-width="2.5" stroke-dasharray="5 4" />`;
      projPath += `<circle cx="${x(SEASON_GAMES)}" cy="${y(projected)}" r="4.5" fill="#fde68a" />`;
    }

    const lastDot = series.length
      ? `<circle cx="${x(played)}" cy="${y(current)}" r="5" fill="#f5c518" stroke="#0c0f14" stroke-width="2" />`
      : "";

    const empty = !series.length
      ? `<text x="${W / 2}" y="${H / 2}" fill="#8b9bb0" font-size="14" text-anchor="middle">Season track starts after game 1</text>`
      : "";

    return `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${metric.label} pace versus promotion targets">
        <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" />
        ${grid.join("")}
        ${targetLine(bench.playoff, "#94a3b8")}
        ${targetLine(bench.auto, "#3d8bfd")}
        ${targetLine(bench.champion, "#34d399")}
        ${valePath}
        ${projPath}
        ${lastDot}
        ${empty}
        <text x="${pad.l}" y="14" fill="#8b9bb0" font-size="11">${metric.unit || metric.label}</text>
        <text x="${W / 2}" y="${H - 2}" fill="#8b9bb0" font-size="11" text-anchor="middle">Games played</text>
      </svg>`;
  }

  function metricCardHtml(metric) {
    const bench = metric.benchmarks || {};
    const digits = metric.digits != null ? metric.digits : metric.project ? 1 : 0;
    const compare = Number(metric.compare ?? metric.current ?? 0);
    const max = Math.max(
      Math.abs(compare),
      Math.abs(bench.champion || 0),
      Math.abs(bench.auto || 0),
      Math.abs(bench.playoff || 0),
      1,
    ) * 1.12;
    const pct = (value) => {
      const n = Number(value);
      if (metric.lower_is_better) return Math.max(0, Math.min(100, (n / max) * 100));
      if (n < 0) return Math.max(0, Math.min(100, ((n - (-max)) / (max * 2)) * 100));
      return Math.max(0, Math.min(100, (n / max) * 100));
    };
    const fill = pct(compare);
    const delta = metric.delta_vs_auto;
    const compareLabel = metric.project ? "Season proj." : "Current";
    const active = metric.id === state.metric ? " is-active" : "";
    const versus = metric.benchmark_set === "league_pack" ? "vs top-7 pace" : "vs auto-promotion average";
    const deltaCopy =
      metric.status === "awaiting"
        ? "Line unlocks after the first league match"
        : `<strong>${signed(delta)}</strong> ${versus}`;
    const nowDigits = metric.chart === "running_rate" || digits > 0 ? Math.max(digits, 1) : 0;
    return `
      <button type="button" class="st-metric${active}" data-metric="${metric.id}">
        <div class="st-metric__head">
          <h3 class="st-metric__title">${metric.label}</h3>
          <span class="st-metric__status is-${statusClass(metric.status)}">${statusLabel(metric.status, metric.benchmark_set)}</span>
        </div>
        <div class="st-metric__values">
          <span>Now <strong>${fmt(metric.current, nowDigits)}</strong></span>
          <span>${compareLabel} <strong>${fmt(compare, metric.project ? 1 : nowDigits)}</strong></span>
        </div>
        <div class="st-rail" aria-hidden="true">
          <div class="st-rail__fill" style="width:${fill}%"></div>
          <span class="st-rail__mark st-rail__mark--playoff" style="left:${pct(bench.playoff)}%"></span>
          <span class="st-rail__mark st-rail__mark--auto" style="left:${pct(bench.auto)}%"></span>
          <span class="st-rail__mark st-rail__mark--champ" style="left:${pct(bench.champion)}%"></span>
        </div>
        <div class="st-rail__labels">
          <span>${(metric.benchmark_labels || {}).playoff || "PO"} ${fmt(bench.playoff, 1)}</span>
          <span>${(metric.benchmark_labels || {}).auto || "Auto"} ${fmt(bench.auto, 1)}</span>
          <span>${(metric.benchmark_labels || {}).champion || "Champ"} ${fmt(bench.champion, 1)}</span>
        </div>
        <p class="st-rail__delta">${deltaCopy}</p>
        <span class="st-metric__link">Open ${metric.label.toLowerCase()} line →</span>
      </button>`;
  }

  function renderMetrics(data) {
    els.metrics.innerHTML = (data.metrics || []).map(metricCardHtml).join("");
    renderStyleTiles(data);
  }

  const STYLE_GROUPS = [
    {
      id: "attack",
      label: "Attack",
      ids: ["defenders_bypassed", "ball_progression", "xg_for", "xg_diff", "offensive_interventions", "altered_threat", "packing_xg"],
    },
    {
      id: "defend",
      label: "Defend",
      ids: ["xg_against", "duel_rate", "defensive_interventions", "ball_wins_defenders", "defenders_bypassed_against"],
    },
  ];

  function styleTileHtml(metric) {
    const bench = metric.benchmarks || {};
    const digits = metric.digits != null ? metric.digits : 1;
    const rate = metric.chart === "running_rate";
    const valePg = rate ? Number(metric.current || 0) : Number(metric.per_game || 0);
    const scale = rate || !metric.project ? 1 : SEASON_GAMES;
    const league = bench.playoff == null ? null : Number(bench.playoff) / scale;
    const top7 = bench.auto == null ? null : Number(bench.auto) / scale;
    const top3 = bench.champion == null ? null : Number(bench.champion) / scale;
    const max = Math.max(
      Math.abs(valePg) || 0,
      Math.abs(league || 0),
      Math.abs(top7 || 0),
      Math.abs(top3 || 0),
      0.01,
    ) * 1.15;
    const width = (value) => {
      if (value == null || Number.isNaN(Number(value))) return 0;
      return Math.max(2, Math.min(100, (Math.abs(Number(value)) / max) * 100));
    };
    const awaiting = metric.status === "awaiting";
    const tone = statusClass(metric.status);
    const delta = metric.delta_vs_auto;
    const deltaCopy = awaiting
      ? "Waiting for kick-off"
      : `${signed(delta)} vs top 7`;
    const big = rate
      ? fmt(metric.current, 1)
      : fmt(metric.current, digits);
    const sub = awaiting
      ? "No league games yet"
      : rate
        ? "Season-to-date win rate"
        : `${fmt(valePg, 2)} per game`;
    function bar(label, value, kind) {
      if (value == null || Number.isNaN(Number(value))) {
        return `<div class="st-tile__bar is-${kind}"><span>${label}</span><div class="st-tile__track"></div><b>—</b></div>`;
      }
      return `<div class="st-tile__bar is-${kind}"><span>${label}</span><div class="st-tile__track"><i style="width:${width(value)}%"></i></div><b>${fmt(value, digits || 1)}</b></div>`;
    }
    return `
      <article class="st-tile is-${tone}">
        <div class="st-tile__top">
          <h3>${metric.label}</h3>
          <span class="st-tile__badge">${statusLabel(metric.status, "league_pack")}</span>
        </div>
        <p class="st-tile__value">${awaiting ? "—" : big}${rate && !awaiting ? "<small>%</small>" : ""}</p>
        <p class="st-tile__sub">${sub}</p>
        <div class="st-tile__bars">
          ${bar("Vale", awaiting ? null : valePg, "vale")}
          ${bar("Top 7", top7, "top7")}
          ${bar("League", league, "league")}
        </div>
        <p class="st-tile__delta">${deltaCopy}</p>
      </article>`;
  }

  function renderStyleTiles(data) {
    if (!els.styleGrid) return;
    const byId = Object.fromEntries((data.style_metrics || []).map((row) => [row.id, row]));
    els.styleGrid.innerHTML = STYLE_GROUPS.map((group) => {
      const tiles = group.ids.map((id) => byId[id]).filter(Boolean);
      if (!tiles.length) return "";
      return `
        <div class="st-style-group">
          <h3>${group.label}</h3>
          <div class="st-tiles">${tiles.map(styleTileHtml).join("")}</div>
        </div>`;
    }).join("");
  }

  function renderPlayers(data) {
    if (!els.playersBody || !els.playersHead) return;
    const minOn = Boolean(els.minMinutes?.checked);
    let rows = [...(data.players || [])];
    if (minOn) rows = rows.filter((row) => Number(row.minutes || 0) >= 90);
    const sortKey = state.playerSort.key;
    const dir = state.playerSort.dir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av || "").localeCompare(String(bv || ""), "en", { sensitivity: "base" });
      }
      return dir * ((Number(av) || 0) - (Number(bv) || 0));
    });
    els.playersHead.innerHTML = `<tr>${PLAYER_COLS.map((col) => {
      const active = col.sort === sortKey ? ` aria-sort="${state.playerSort.dir === "asc" ? "ascending" : "descending"}"` : "";
      const mark = col.sort === sortKey ? (state.playerSort.dir === "asc" ? " ▲" : " ▼") : "";
      return `<th data-sort="${col.sort}"${active}>${col.label}${mark}</th>`;
    }).join("")}</tr>`;
    if (!rows.length) {
      const msg = data.kickoff_ready
        ? "Player board unlocks after the first league match."
        : minOn
          ? "No players over 90 minutes yet — uncheck the filter."
          : "No player KPI rows in Impect for these matches.";
      els.playersBody.innerHTML = `<tr><td colspan="${PLAYER_COLS.length}" class="st-muted">${msg}</td></tr>`;
      if (els.playersHint) {
        els.playersHint.textContent = "Season totals and per 90. Click a heading to sort.";
      }
      return;
    }
    els.playersBody.innerHTML = rows.map((row) => {
      return `<tr>${PLAYER_COLS.map((col) => {
        if (col.key === "name") return `<td class="st-player-name">${row.name || "—"}</td>`;
        if (col.key === "position_short") return `<td>${row.position_short || "—"}</td>`;
        const value = row[col.key];
        const extra = col.p90 && row[`${col.key}_p90`] != null
          ? `<span class="st-p90">${fmt(row[`${col.key}_p90`], col.digits || 1)}/90</span>`
          : "";
        return `<td>${fmt(value, col.digits || 0)}${extra}</td>`;
      }).join("")}</tr>`;
    }).join("");
    if (els.playersHint) {
      els.playersHint.textContent = `${rows.length} player${rows.length === 1 ? "" : "s"} · click headings to sort · gold /90 is per 90 minutes`;
    }
  }

  function buildTimingSvg(data, { w = 720, h = 280 } = {}) {
    const times = data.goal_times || {};
    const order = times.bucket_order || [];
    const labels = times.bucket_labels || {};
    const scored = times.for || { total: 0, buckets: {} };
    const conceded = times.against || { total: 0, buckets: {} };
    const W = w;
    const H = h;
    const pad = { l: 36, r: 12, t: 18, b: 52 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    const n = Math.max(order.length, 1);
    const groupW = innerW / n;
    const barW = Math.max(6, groupW * 0.32);
    const maxVal = Math.max(
      1,
      ...order.map((key) => Number((scored.buckets?.[key] || {}).total || 0)),
      ...order.map((key) => Number((conceded.buckets?.[key] || {}).total || 0)),
    );
    const y = (val) => pad.t + innerH - (val / maxVal) * innerH;
    const bars = [];
    order.forEach((key, i) => {
      const gf = Number((scored.buckets?.[key] || {}).total || 0);
      const ga = Number((conceded.buckets?.[key] || {}).total || 0);
      const cx = pad.l + i * groupW + groupW / 2;
      const gfH = Math.max(gf ? 3 : 0, (gf / maxVal) * innerH);
      const gaH = Math.max(ga ? 3 : 0, (ga / maxVal) * innerH);
      bars.push(`<rect x="${cx - barW - 2}" y="${y(gf)}" width="${barW}" height="${gfH}" rx="2" fill="#f5c518" />`);
      bars.push(`<rect x="${cx + 2}" y="${y(ga)}" width="${barW}" height="${gaH}" rx="2" fill="#f87171" />`);
      if (gf) bars.push(`<text x="${cx - barW / 2 - 2}" y="${y(gf) - 4}" fill="#f5c518" font-size="11" text-anchor="middle">${gf}</text>`);
      if (ga) bars.push(`<text x="${cx + barW / 2 + 2}" y="${y(ga) - 4}" fill="#f87171" font-size="11" text-anchor="middle">${ga}</text>`);
      bars.push(`<text x="${cx}" y="${H - 18}" fill="#8b9bb0" font-size="11" text-anchor="middle">${labels[key] || key}</text>`);
    });
    const timedTotal = order.reduce((sum, key) => {
      return sum
        + Number((scored.buckets?.[key] || {}).total || 0)
        + Number((conceded.buckets?.[key] || {}).total || 0);
    }, 0);
    const empty = !timedTotal
      ? `<text x="${W / 2}" y="${H / 2 - 8}" fill="#8b9bb0" font-size="16" text-anchor="middle">${scored.total || conceded.total ? "Goals recorded — minutes not in Impect yet" : "No timed goals yet"}</text>`
      : "";
    return `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Goals scored and conceded by time bucket">
        <line x1="${pad.l}" y1="${pad.t + innerH}" x2="${pad.l + innerW}" y2="${pad.t + innerH}" stroke="rgba(255,255,255,0.12)" />
        ${bars.join("")}
        ${empty}
      </svg>`;
  }

  function renderTiming(data) {
    const times = data.goal_times || {};
    const order = times.bucket_order || [];
    const labels = times.bucket_labels || {};
    const scored = times.for || { total: 0, buckets: {} };
    const conceded = times.against || { total: 0, buckets: {} };
    const missing = Number(times.matches_missing_events || 0);
    const withEvents = Number(times.matches_with_events || 0);

    if (data.kickoff_ready || (!scored.total && !conceded.total && !data.played)) {
      els.goalsHint.textContent = "Timing splits unlock after the first league goal.";
    } else {
      els.goalsHint.textContent = missing
        ? `When Vale score and concede · ${withEvents} matches with event times · ${missing} still missing minutes.`
        : `When Vale score and concede — 15-minute windows plus 1H / 2H added time.`;
    }

    els.timingChart.innerHTML = buildTimingSvg(data, { w: 720, h: 280 });

    const spot = data.goal_spotlight || {};
    const net = (scored.total || 0) - (conceded.total || 0);
    els.timingSide.innerHTML = `
      <div class="st-side-kpis">
        <article class="st-side-kpi">
          <span class="st-side-kpi__lbl">Scored</span>
          <strong>${fmt(scored.total)}</strong>
          <span>${fmt(scored.home)} home · ${fmt(scored.away)} away</span>
        </article>
        <article class="st-side-kpi st-side-kpi--against">
          <span class="st-side-kpi__lbl">Conceded</span>
          <strong>${fmt(conceded.total)}</strong>
          <span>${fmt(conceded.home)} home · ${fmt(conceded.away)} away</span>
        </article>
        <article class="st-side-kpi">
          <span class="st-side-kpi__lbl">Net</span>
          <strong>${signed(net, 0)}</strong>
          <span>For minus against</span>
        </article>
      </div>
      <div class="st-split">
        <div>
          <h3>First half</h3>
          <p><b>${fmt(spot.first_half_for)}</b> for · <b>${fmt(spot.first_half_against)}</b> against</p>
        </div>
        <div>
          <h3>Second half</h3>
          <p><b>${fmt(spot.second_half_for)}</b> for · <b>${fmt(spot.second_half_against)}</b> against</p>
        </div>
        <div>
          <h3>Added time</h3>
          <p><b>${fmt(spot.added_for)}</b> for · <b>${fmt(spot.added_against)}</b> against</p>
        </div>
      </div>
      <div class="st-spot">
        ${spot.best_scoring ? `<p><span class="st-spot__tag">Best scoring window</span> ${spot.best_scoring.label} · ${spot.best_scoring.total} goals</p>` : ""}
        ${spot.most_conceded ? `<p><span class="st-spot__tag is-bad">Most conceded</span> ${spot.most_conceded.label} · ${spot.most_conceded.total} against</p>` : `<p class="st-muted">Windows populate once goals have event times.</p>`}
        ${missing ? `<p class="st-muted">${missing} match${missing === 1 ? "" : "es"} without event times — those goals sit in the totals, not the bars.</p>` : ""}
      </div>`;
  }

  function renderExtras(data) {
    const form = data.form || [];
    const gf = Number(metricById(data, "goals_for")?.current || 0);
    const ga = Number(metricById(data, "goals_against")?.current || 0);
    const xgFor = data.xg_for;
    const xgAgainst = data.xg_against;
    const xp = data.xp_vs_actual;
    const formDots = form.length
      ? form.map((result) => `<span class="st-form__dot is-${result}">${result}</span>`).join("")
      : `<span class="st-muted">Form strip starts after game 1</span>`;
    const xgForDelta = xgFor == null ? null : gf - Number(xgFor);
    const xgAgDelta = xgAgainst == null ? null : Number(xgAgainst) - ga;
    els.extras.innerHTML = `
      <article class="card st-extra">
        <h3>Last six</h3>
        <div class="st-form">${formDots}</div>
        <p class="st-muted">Newest on the right</p>
      </article>
      <article class="card st-extra">
        <h3>Goals vs shot xG</h3>
        <p class="st-extra__row"><span>Scored</span><strong>${fmt(gf)}</strong><span class="st-muted">xG ${fmt(xgFor, 1)} · ${signed(xgForDelta)}</span></p>
        <p class="st-extra__row"><span>Conceded</span><strong>${fmt(ga)}</strong><span class="st-muted">xGA ${fmt(xgAgainst, 1)} · prevented ${signed(xgAgDelta)}</span></p>
      </article>
      <article class="card st-extra">
        <h3>Pts vs shot xPts</h3>
        <p class="st-extra__big">${signed(xp)}</p>
        <p class="st-muted">Actual minus expected — green overperformance in Club Strategy</p>
      </article>`;
  }

  function renderResults(data) {
    const series = (data.series || []).slice(-10).reverse();
    if (!series.length) {
      els.resultsBody.innerHTML = `<tr><td colspan="7" class="st-muted">League results will land here after kick-off.</td></tr>`;
      return;
    }
    els.resultsBody.innerHTML = series.map((row) => {
      const score = `${row.scored ?? "—"}–${row.conceded ?? "—"}`;
      return `<tr>
        <td>${row.played}</td>
        <td>${row.date || "—"}</td>
        <td>${row.opponent || "—"}</td>
        <td><span class="st-form__dot is-${row.result}">${row.venue || ""} ${row.result || ""}</span></td>
        <td>${score}</td>
        <td>${row.points}</td>
        <td>${signed(row.goal_difference, 0)}</td>
      </tr>`;
    }).join("");
  }

  function renderCompetitionToggle() {
    document.querySelectorAll(".st-toggle__btn").forEach((btn) => {
      const value = btn.getAttribute("data-competition") || "";
      btn.classList.toggle("is-active", value === (state.competition || ""));
    });
  }

  function renderAll(data) {
    state.data = data;
    if (!metricById(data, state.metric)) state.metric = DEFAULT_METRIC;
    renderCompetitionToggle();
    renderSummary(data);
    renderPills(data);
    renderPaceChart(data);
    renderMetrics(data);
    renderPlayers(data);
    renderTiming(data);
    renderExtras(data);
    renderResults(data);
    els.source.textContent = data.source_note || "";
    const when = data.generated_at ? new Date(data.generated_at) : new Date();
    els.updated.textContent = `Updated ${when.toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    })}`;
    try {
      buildDeck(data);
    } catch (err) {
      console.error("Deck build failed", err);
    }
    if (state.presenting) {
      showSlide(state.slide);
      layoutDeck();
    }
  }

  async function load(refresh = false) {
    els.refresh.disabled = true;
    const label = state.competition || "current season";
    setStatus(refresh ? `Refreshing ${label}…` : "");
    try {
      const params = new URLSearchParams({ refresh: refresh ? "true" : "false" });
      if (state.competition) params.set("competition", state.competition);
      const res = await fetch(`${API}/api/strategy-tracker?${params}`);
      const raw = await res.text();
      let data;
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        throw new Error(raw.slice(0, 160) || `Request failed (${res.status})`);
      }
      if (!res.ok) throw new Error(data.detail || `Failed to load tracker (${res.status})`);
      renderAll(data);
      setStatus("");
    } catch (err) {
      setStatus(err.message || "Could not load strategy tracker.", "error");
    } finally {
      els.refresh.disabled = false;
    }
  }

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function slideHead(data, title, kicker) {
    return `<header class="st-slide__head"><span>${esc(kicker || "Port Vale F.C.")}</span><span>${esc(data.competition || "")}  |  ${esc(data.season || "")}</span></header>
      <h2 class="st-slide__title">${esc(title)}</h2>`;
  }

  function barRowHtml(label, value, kind, digits, maxAbs) {
    const missing = value == null || Number.isNaN(Number(value));
    const n = missing ? 0 : Math.abs(Number(value));
    const pct = !missing && maxAbs > 0 ? Math.max(2, Math.min(100, (n / maxAbs) * 100)) : 0;
    return `<div class="st-deck-bar is-${kind}">
      <span class="st-deck-bar__label">${esc(label)}</span>
      <div class="st-deck-bar__track">${pct ? `<i style="width:${pct}%"></i>` : ""}</div>
      <b class="st-deck-bar__val">${missing ? "—" : fmt(value, digits)}</b>
    </div>`;
  }

  function outcomeBarSlide(data, metric) {
    const bench = metric.benchmarks || {};
    const labels = metric.benchmark_labels || { playoff: "Play-off", auto: "Auto", champion: "Champions" };
    const digits = metric.digits != null ? metric.digits : 0;
    const nowDigits = metric.chart === "running_rate" || digits > 0 ? Math.max(digits, 1) : 0;
    const awaiting = metric.status === "awaiting";
    const rows = [
      { label: "Port Vale now", value: awaiting ? null : metric.current, kind: "vale", digits: nowDigits },
    ];
    if (metric.project) {
      rows.push({ label: "Season proj.", value: awaiting ? null : metric.compare, kind: "proj", digits: 1 });
    }
    rows.push(
      { label: labels.playoff || "Play-off", value: bench.playoff, kind: "playoff", digits: 1 },
      { label: labels.auto || "Auto", value: bench.auto, kind: "auto", digits: 1 },
      { label: labels.champion || "Champions", value: bench.champion, kind: "champ", digits: 1 },
    );
    const maxAbs = Math.max(0.01, ...rows.map((row) => Math.abs(Number(row.value) || 0))) * 1.12;
    const versus = metric.benchmark_set === "league_pack" ? "top 7" : "auto";
    const copy = awaiting
      ? (metric.lower_is_better ? "Lower is better. Bars fill after game 1." : "Bars fill after the first league match.")
      : `${signed(metric.delta_vs_auto)} vs ${versus}${metric.lower_is_better ? " · lower is better" : ""}`;
    return `<article class="st-slide">
      ${slideHead(data, metric.label, "Outcome")}
      <div class="st-slide__body">
        <div class="st-deck-headline">
          <span class="st-deck-status is-${statusClass(metric.status)}">${statusLabel(metric.status, metric.benchmark_set)}</span>
          <p>${copy}</p>
        </div>
        <div class="st-deck-bars">${rows.map((row) => barRowHtml(row.label, row.value, row.kind, row.digits, maxAbs)).join("")}</div>
      </div>
    </article>`;
  }

  function styleBarSlide(data, metric, groupLabel) {
    const bench = metric.benchmarks || {};
    const digits = metric.digits != null ? metric.digits : 1;
    const rate = metric.chart === "running_rate";
    const valePg = rate ? Number(metric.current || 0) : Number(metric.per_game || 0);
    const scale = rate || !metric.project ? 1 : SEASON_GAMES;
    const league = bench.playoff == null ? null : Number(bench.playoff) / scale;
    const top7 = bench.auto == null ? null : Number(bench.auto) / scale;
    const top3 = bench.champion == null ? null : Number(bench.champion) / scale;
    const awaiting = metric.status === "awaiting";
    const rows = [
      { label: "Port Vale", value: awaiting ? null : valePg, kind: "vale" },
      { label: "Top 7", value: top7, kind: "auto" },
      { label: "Top 3", value: top3, kind: "champ" },
      { label: "League", value: league, kind: "playoff" },
    ];
    const maxAbs = Math.max(0.01, ...rows.map((row) => Math.abs(Number(row.value) || 0))) * 1.15;
    const barDigits = rate ? 1 : Math.max(digits, 1);
    const copy = awaiting
      ? (metric.lower_is_better ? "Lower is better. Per-game bars after kick-off." : "Per-game bars vs this season’s pack after kick-off.")
      : `${signed(metric.delta_vs_auto)} vs top 7${metric.lower_is_better ? " · lower is better" : ""}${rate ? "" : " · per game"}`;
    return `<article class="st-slide">
      ${slideHead(data, metric.label, groupLabel)}
      <div class="st-slide__body">
        <div class="st-deck-headline">
          <span class="st-deck-status is-${statusClass(metric.status)}">${statusLabel(metric.status, "league_pack")}</span>
          <p>${copy}</p>
        </div>
        <div class="st-deck-bars">${rows.map((row) => barRowHtml(row.label, row.value, row.kind, barDigits, maxAbs)).join("")}</div>
      </div>
    </article>`;
  }

  function styleByGroup(data, groupId) {
    const group = STYLE_GROUPS.find((row) => row.id === groupId);
    const byId = Object.fromEntries((data.style_metrics || []).map((row) => [row.id, row]));
    return (group?.ids || []).map((id) => byId[id]).filter(Boolean);
  }

  function buildDeck(data) {
    if (!els.deckFit) return;
    const s = data.summary || {};
    const status = s.status || "awaiting";
    const points = metricById(data, "points");
    const headline = data.kickoff_ready
      ? `Waiting for kick-off — auto target ${fmt(s.auto_target, 1)} pts`
      : `Projected ${fmt(s.projected_points, 1)} pts · auto ${fmt(s.auto_target, 1)} (${signed(s.delta_vs_auto)})`;
    const times = data.goal_times || {};
    const scored = times.for || {};
    const conceded = times.against || {};
    const spot = data.goal_spotlight || {};
    const players = [...(data.players || [])]
      .filter((row) => Number(row.minutes || 0) >= 90)
      .sort((a, b) => (Number(b.minutes) || 0) - (Number(a.minutes) || 0))
      .slice(0, 10);
    const form = data.form || [];
    const series = [...(data.series || [])].slice(-8).reverse();
    const ahead = [...(data.metrics || []), ...(data.style_metrics || [])]
      .filter((row) => row.status === "ahead")
      .map((row) => row.label)
      .slice(0, 4);
    const behind = [...(data.metrics || []), ...(data.style_metrics || [])]
      .filter((row) => row.status === "behind")
      .map((row) => row.label)
      .slice(0, 4);
    const closeBody = data.kickoff_ready
      ? "Season not started. After each league game this pack updates: points pace vs auto, style numbers vs the top 7, and the player board."
      : `Keep going: ${ahead.join(", ") || "the metrics already at promotion pace"}. Fix next: ${behind.join(", ") || "nothing currently behind the auto / top-7 line"}.`;
    const goalsEmpty = data.kickoff_ready || (!(scored.total || 0) && !(conceded.total || 0));
    const playerCols = PLAYER_COLS.filter((col) => col.key !== "packing_xg" && col.key !== "ball_wins_defenders" && col.key !== "appearances");
    const playerTable = players.length
      ? `<table class="st-deck-table"><thead><tr>${playerCols.map((col) => `<th>${col.label}</th>`).join("")}</tr></thead>
         <tbody>${players.map((row) => `<tr>${playerCols.map((col) => {
           if (col.key === "name") return `<td>${esc(row.name || "—")}</td>`;
           if (col.key === "position_short") return `<td>${esc(row.position_short || "—")}</td>`;
           return `<td>${fmt(row[col.key], col.digits || 0)}</td>`;
         }).join("")}</tr>`).join("")}</tbody></table>`
      : `<p class="st-deck-empty">Player board unlocks after the first league match (90+ minutes).</p>`;
    const formDots = form.length
      ? form.map((result) => `<span class="st-form__dot is-${result}">${result}</span>`).join("")
      : `<span class="st-muted">Form strip starts after game 1</span>`;
    const resultRows = series.length
      ? series.map((row) => `<tr>
          <td>${row.played}</td>
          <td>${esc(row.date || "—")}</td>
          <td>${esc(row.opponent || "—")}</td>
          <td>${esc(row.venue || "")} ${esc(row.result || "")}</td>
          <td>${row.scored ?? "—"}–${row.conceded ?? "—"}</td>
          <td>${row.points}</td>
        </tr>`).join("")
      : `<tr><td colspan="6">Results land here after kick-off.</td></tr>`;
    const gf = metricById(data, "goals_for")?.current;
    const ga = metricById(data, "goals_against")?.current;

    els.deckFit.innerHTML = `
      <article class="st-slide st-slide--cover">
        <img src="/standalone/port-vale-badge.png?v=2" width="72" height="88" alt="" />
        <p class="st-slide__kicker">Port Vale F.C.</p>
        <h2>Season Progress Report</h2>
        <p class="st-slide__sub">${esc(data.competition || "")}  |  ${esc(data.season || "")}</p>
        <p class="st-slide__lede">Board pack: promotion pace, style numbers that win games, and the player board.</p>
        <p class="st-slide__foot">Present in the room  ·  PDF is the leave-behind</p>
      </article>
      <article class="st-slide">
        ${slideHead(data, "Where we are")}
        <div class="st-slide__body">
          <div class="st-deck-headline">
            <span class="st-deck-status is-${statusClass(status)}">${statusLabel(status, "promotion")}</span>
            <p>${esc(headline)}</p>
          </div>
          <div class="st-deck-kpis">
            <div class="st-deck-kpi"><b>${fmt(data.played)}</b><span>Played</span></div>
            <div class="st-deck-kpi"><b>${fmt(points?.current)}</b><span>Points</span></div>
            <div class="st-deck-kpi"><b>${data.kickoff_ready ? "—" : fmt(s.projected_points, 1)}</b><span>Season proj.</span></div>
            <div class="st-deck-kpi"><b>${data.position != null ? data.position : "—"}</b><span>Position</span></div>
            <div class="st-deck-kpi"><b>${fmt(s.auto_target, 1)}</b><span>Auto</span></div>
            <div class="st-deck-kpi"><b>${fmt(s.champion_target, 1)}</b><span>Champions</span></div>
          </div>
          <p class="st-deck-note">${fmt(data.played)}/${SEASON_GAMES} league games · ${fmt(data.games_remaining)} remaining · next: one slide per metric, as bars.</p>
        </div>
      </article>
      ${(data.metrics || []).map((metric) => outcomeBarSlide(data, metric)).join("")}
      <article class="st-slide">
        ${slideHead(data, "Goals by time", "Scoring")}
        <div class="st-slide__body">
          ${goalsEmpty
            ? `<p class="st-deck-empty">Timing splits unlock after the first league goal.</p>`
            : `<div class="st-deck-goals">
                <div class="st-deck-chart">${buildTimingSvg(data, { w: 760, h: 480 })}</div>
                <div class="st-deck-side">
                  <p>Scored <b>${fmt(scored.total)}</b></p>
                  <p>Conceded <b>${fmt(conceded.total)}</b></p>
                  <p>1H <b>${fmt(spot.first_half_for)}</b> for / <b>${fmt(spot.first_half_against)}</b> against</p>
                  <p>2H <b>${fmt(spot.second_half_for)}</b> for / <b>${fmt(spot.second_half_against)}</b> against</p>
                  ${spot.best_scoring ? `<p>Best window <b>${esc(spot.best_scoring.label)}</b> (${spot.best_scoring.total})</p>` : ""}
                </div>
              </div>`}
        </div>
      </article>
      ${styleByGroup(data, "attack").map((metric) => styleBarSlide(data, metric, "Attack")).join("")}
      ${styleByGroup(data, "defend").map((metric) => styleBarSlide(data, metric, "Defend")).join("")}
      <article class="st-slide">
        ${slideHead(data, "Player board", "Squad")}
        <div class="st-slide__body">${playerTable}</div>
      </article>
      <article class="st-slide">
        ${slideHead(data, "Form and recent results", "Results")}
        <div class="st-slide__body">
          <div class="st-deck-split">
            <div>
              <p class="st-deck-note" style="margin:0 0 8px">Last six</p>
              <div class="st-deck-form">${formDots}</div>
              <p>Goals vs xG <b>${fmt(gf)}</b> / ${fmt(data.xg_for, 1)}</p>
              <p>Conceded vs xGA <b>${fmt(ga)}</b> / ${fmt(data.xg_against, 1)}</p>
              <p>Pts vs xPts <b>${signed(data.xp_vs_actual)}</b></p>
            </div>
            <table class="st-deck-table">
              <thead><tr><th>#</th><th>Date</th><th>Opp</th><th></th><th>Score</th><th>Pts</th></tr></thead>
              <tbody>${resultRows}</tbody>
            </table>
          </div>
        </div>
      </article>
      <article class="st-slide">
        ${slideHead(data, "How we use this", "Board pack")}
        <div class="st-slide__body">
          <div class="st-deck-close">
            <p>${esc(closeBody)}</p>
            <span>Present this deck in the room. Export PDF is the same story for the board pack.</span>
          </div>
        </div>
      </article>`;
    showSlide(state.slide);
  }

  function layoutDeck() {
    if (!els.deckStage || !els.deckFit) return;
    const sw = els.deckStage.clientWidth || 1;
    const sh = els.deckStage.clientHeight || 1;
    const scale = Math.min(sw / 1280, sh / 720);
    els.deckFit.style.transform = `scale(${scale})`;
  }

  function showSlide(index) {
    const slides = els.deckFit ? [...els.deckFit.querySelectorAll(".st-slide")] : [];
    if (!slides.length) return;
    state.slide = ((index % slides.length) + slides.length) % slides.length;
    slides.forEach((slide, i) => slide.classList.toggle("is-on", i === state.slide));
    if (els.deckCounter) els.deckCounter.textContent = `${state.slide + 1} / ${slides.length}`;
  }

  function setPresent(on) {
    state.presenting = Boolean(on);
    document.body.classList.toggle("is-present", state.presenting);
    if (els.deck) els.deck.setAttribute("aria-hidden", state.presenting ? "false" : "true");
    const btn = document.getElementById("presentBtn");
    if (btn) btn.textContent = state.presenting ? "Exit present" : "Present";
    syncUrl();
    if (!state.presenting) {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      return;
    }
    try {
      if (state.data) buildDeck(state.data);
    } catch (err) {
      console.error("Deck build failed", err);
    }
    showSlide(state.slide || 0);
    requestAnimationFrame(() => {
      layoutDeck();
      requestAnimationFrame(layoutDeck);
    });
    const root = document.documentElement;
    const fs = root.requestFullscreen || root.webkitRequestFullscreen;
    if (typeof fs === "function") {
      Promise.resolve(fs.call(root)).catch(() => {});
    }
  }

  async function exportPdf() {
    if (state.exporting) return;
    state.exporting = true;
    if (els.exportBtn) els.exportBtn.disabled = true;
    setStatus("Building board PDF…");
    try {
      const params = new URLSearchParams();
      if (state.competition) params.set("competition", state.competition);
      const res = await fetch(`${API}/api/strategy-tracker/export-pdf?${params}`, {
        signal: AbortSignal.timeout(180000),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.detail || `Export failed (${res.status})`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match?.[1] || "season-progress.pdf";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setStatus("");
    } catch (err) {
      setStatus(err.message || "Could not export PDF.", "error");
    } finally {
      state.exporting = false;
      if (els.exportBtn) els.exportBtn.disabled = false;
    }
  }

  window.stTogglePresent = () => setPresent(!state.presenting);
  window.stExportPdf = exportPdf;

  els.refresh.addEventListener("click", () => load(true));
  function onMetricClick(event) {
    const btn = event.target.closest("[data-metric]");
    if (!btn) return;
    selectMetric(btn.getAttribute("data-metric"));
    if (event.currentTarget === els.metrics) {
      els.chart.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
  els.pills.addEventListener("click", onMetricClick);
  els.metrics.addEventListener("click", onMetricClick);
  els.playersHead?.addEventListener("click", (event) => {
    const th = event.target.closest("[data-sort]");
    if (!th || !state.data) return;
    const key = th.getAttribute("data-sort");
    if (state.playerSort.key === key) {
      state.playerSort.dir = state.playerSort.dir === "desc" ? "asc" : "desc";
    } else {
      state.playerSort = { key, dir: key === "name" || key === "position_short" ? "asc" : "desc" };
    }
    renderPlayers(state.data);
  });
  els.minMinutes?.addEventListener("change", () => {
    if (state.data) renderPlayers(state.data);
  });
  document.querySelector(".st-toggle")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-competition]");
    if (!btn) return;
    state.competition = btn.getAttribute("data-competition") || "";
    syncUrl();
    load(false);
  });
  window.addEventListener("hashchange", () => {
    selectMetric(hashMetric(), { skipUrl: true });
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("#presentBtn")) {
      event.preventDefault();
      setPresent(!state.presenting);
      return;
    }
    if (event.target.closest("#exportBtn")) {
      event.preventDefault();
      exportPdf();
      return;
    }
    if (event.target.closest("#deckPrev")) {
      event.preventDefault();
      showSlide(state.slide - 1);
      return;
    }
    if (event.target.closest("#deckNext")) {
      event.preventDefault();
      showSlide(state.slide + 1);
      return;
    }
    if (event.target.closest("#deckExit")) {
      event.preventDefault();
      setPresent(false);
      return;
    }
    if (!state.presenting || !els.deckFit || !els.deckFit.contains(event.target)) return;
    if (event.target.closest("button, a")) return;
    const rect = els.deckStage.getBoundingClientRect();
    if (event.clientX > rect.left + rect.width * 0.55) showSlide(state.slide + 1);
    else showSlide(state.slide - 1);
  });
  window.addEventListener("resize", () => {
    if (state.presenting) layoutDeck();
  });
  window.addEventListener("keydown", (event) => {
    const tag = (event.target && event.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable) return;
    if ((event.key === "p" || event.key === "P") && !event.metaKey && !event.ctrlKey) {
      event.preventDefault();
      setPresent(!state.presenting);
      return;
    }
    if (!state.presenting) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setPresent(false);
    } else if (["ArrowRight", " ", "PageDown", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
      showSlide(state.slide + 1);
    } else if (["ArrowLeft", "PageUp", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      showSlide(state.slide - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      showSlide(0);
    } else if (event.key === "End") {
      event.preventDefault();
      showSlide(-1);
    }
  });

  syncUrl();
  load(false);
})();
