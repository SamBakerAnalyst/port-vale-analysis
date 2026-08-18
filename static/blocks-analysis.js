const FETCH_TIMEOUT_MS = 90000;

const state = {
  payload: null,
  filters: {},
  reportTabs: {},
  loading: false,
  saving: false,
};

const els = {
  pageSubtitle: document.getElementById("pageSubtitle"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  jumpNav: document.getElementById("jumpNav"),
  blocksRoot: document.getElementById("blocksRoot"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportAllBtn: document.getElementById("exportAllBtn"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `ba-status ba-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

async function fetchJson(url, options = {}) {
  const busted = url.includes("?") ? `${url}&_=${Date.now()}` : `${url}?_=${Date.now()}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? FETCH_TIMEOUT_MS);
  try {
    const { timeoutMs: _t, ...rest } = options;
    const res = await fetch(busted, {
      cache: "no-store",
      headers: { Accept: "application/json", ...(rest.headers || {}) },
      ...rest,
      signal: controller.signal,
    });
    const raw = await res.text();
    let data = {};
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: raw.slice(0, 240) };
      }
    }
    if (!res.ok) {
      const detail = data.detail || data.message || res.statusText;
      throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function fmtNum(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function shortOpponent(name) {
  const text = String(name || "").replace(/\s+FC$/i, "").trim();
  if (/wolverhampton/i.test(text)) return "Wolves";
  const parts = text.split(/\s+/);
  if (parts.length <= 2) return text;
  return parts.slice(0, 2).join(" ");
}

function resultClass(outcome) {
  if (outcome === "win") return "ba-fix--win";
  if (outcome === "draw") return "ba-fix--draw";
  if (outcome === "loss") return "ba-fix--loss";
  return "";
}

function scoreLine(fixture) {
  const stats = fixture.stats || {};
  if (!fixture.played) return "";
  return `${stats.goals ?? "?"}–${stats.goalsAgainst ?? "?"}`;
}

function fixtureCard(fixture, filterId) {
  const tbc = !fixture.matchId;
  const focus = filterId && String(filterId) === String(fixture.matchId);
  const ha = fixture.isHome == null
    ? ""
    : `<span class="ba-fix__ha ${fixture.isHome ? "ba-fix__ha--home" : ""}">${fixture.isHome ? "HOME" : "AWAY"}</span>`;
  const badge = fixture.badgeUrl
    ? `<img class="ba-fix__badge" src="${escapeHtml(fixture.badgeUrl)}" alt="" crossorigin="anonymous" />`
    : `<span class="ba-fix__initials">${escapeHtml(fixture.opponentInitials || "?")}</span>`;
  const score = fixture.played
    ? `<p class="ba-fix__score">${escapeHtml(scoreLine(fixture))}</p>`
    : "";
  const date = fixture.dateLabel
    ? `${fixture.slot}. ${fixture.dateLabel}`
    : `${fixture.slot}. TBC`;
  return `
    <article class="ba-fix ${resultClass(fixture.outcome)} ${tbc ? "ba-fix--tbc" : ""} ${focus ? "ba-fix--focus" : ""}" data-match-id="${escapeHtml(fixture.matchId || "")}">
      <div class="ba-fix__top">
        <span class="ba-fix__date">${escapeHtml(date)}</span>
        ${ha}
      </div>
      ${badge}
      <p class="ba-fix__name">${escapeHtml(fixture.opponentName || "FIXTURE TBC")}</p>
      ${score}
    </article>
  `;
}

function medalPills(block) {
  const current = block.target?.medal || "silver";
  return ["gold", "silver", "bronze"].map((medal) => {
    const label = medal.toUpperCase();
    return `<button type="button" class="ba-medal-pill ${medal === current ? "is-active" : ""}" data-medal="${medal}" data-block="${block.id}">${label}</button>`;
  }).join("");
}

function progressPct(got, target) {
  const t = Number(target) || 0;
  const g = Number(got) || 0;
  if (t <= 0) return g > 0 ? 100 : 0;
  return Math.max(0, Math.min(100, (g / t) * 100));
}

function progressTrack(label, got, target) {
  const pct = progressPct(got, target);
  const hit = Number(target) > 0 && Number(got) >= Number(target);
  return `
    <div class="ba-track ${hit ? "is-hit" : ""}">
      <div class="ba-track__head">
        <span class="ba-track__label">${escapeHtml(label)}</span>
        <span class="ba-track__nums"><b>${escapeHtml(fmtNum(got))}</b> / ${escapeHtml(fmtNum(target))}</span>
      </div>
      <div class="ba-track__bar" role="progressbar" aria-label="${escapeHtml(label)}" aria-valuenow="${escapeHtml(got)}" aria-valuemin="0" aria-valuemax="${escapeHtml(target)}">
        <span class="ba-track__fill" style="width:${pct}%"></span>
      </div>
    </div>
  `;
}

function posterHtml(block) {
  const target = block.target || {};
  const totals = block.totals || {};
  const medal = target.medal || "silver";
  const csLabel = Number(target.cleanSheets) === 1 ? "clean sheet" : "clean sheets";
  return `
    <section class="ba-poster" data-poster="${block.id}">
      <header class="ba-poster__head">
        <div class="ba-poster__head-left">
          <img class="ba-poster__crest" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" />
          <p class="ba-poster__kicker">BLOCK ${block.id} OF 9 • ${escapeHtml(block.title)}</p>
        </div>
        <p class="ba-poster__score">${escapeHtml(block.pointsLabel)}</p>
      </header>
      <div class="ba-poster__body">
        <h2 class="ba-poster__heading">${escapeHtml(block.heading)}</h2>
        <div class="ba-fixtures">
          ${(block.fixtures || []).map((row) => fixtureCard(row, state.filters[block.id])).join("")}
        </div>
        <div class="ba-aim-wrap">
          <p class="ba-aim-wrap__title">What are we aiming for?</p>
          <div class="ba-medal-pills ba-export-hide">${medalPills(block)}</div>
          <div class="ba-aim-row">
            <div class="ba-aim ba-aim--${escapeHtml(medal)}">
              <p class="ba-aim__stamp">Target</p>
              <p class="ba-aim__label">${escapeHtml(target.label || "SILVER • AUTOMATIC")}</p>
              <span class="ba-aim__points-print">${escapeHtml(target.points)}</span>
              <input class="ba-aim__points ba-export-hide" type="number" min="0" max="18" step="1" value="${escapeHtml(target.points)}" data-block="${block.id}" aria-label="Points target" />
              <p class="ba-aim__cs">
                <span class="ba-aim__cs-print">${escapeHtml(target.cleanSheets)}</span>
                <input class="ba-aim__cs-input ba-export-hide" type="number" min="0" max="6" step="1" value="${escapeHtml(target.cleanSheets)}" data-block="${block.id}" aria-label="Clean sheet target" />
                ${csLabel}
              </p>
            </div>
            <div class="ba-tracks">
              ${progressTrack("Points", totals.points || 0, target.points)}
              ${progressTrack("Clean sheets", totals.cleanSheets || 0, target.cleanSheets)}
            </div>
          </div>
        </div>
      </div>
      <footer class="ba-poster__foot">
        <p class="ba-poster__foot-text">${escapeHtml(block.footer)}</p>
        <div class="ba-poster__export ba-export-hide">
          <button type="button" class="ba-btn" data-export="${block.id}">PNG</button>
        </div>
      </footer>
    </section>
  `;
}

function reportFixtures(block) {
  return [...(block.fixtures || []), ...(block.demoFixtures || [])];
}

function selectedStats(block) {
  const filterId = state.filters[block.id];
  if (!filterId || filterId === "all") return { stats: block.totals, label: "All games in this block", single: false };
  const fixture = reportFixtures(block).find((row) => String(row.matchId) === String(filterId));
  if (!fixture) return { stats: block.totals, label: "All games in this block", single: false };
  const stats = { ...(fixture.stats || {}) };
  stats.played = fixture.played ? 1 : 0;
  stats.cleanSheets = fixture.stats?.cleanSheet ? 1 : 0;
  return {
    stats,
    label: fixture.played
      ? `${fixture.opponentName} (${scoreLine(fixture)})`
      : `${fixture.opponentName} · not played`,
    single: true,
    fixture,
  };
}

function kpiTone(key, stats, target, single, scheduled) {
  if (single || !stats.played) return "";
  const complete = scheduled > 0 && stats.played >= scheduled;
  if (key === "points") {
    if (complete && stats.points >= (target?.points || 0)) return "hot";
    if (complete) return "cold";
    return "warn";
  }
  if (key === "cleanSheets" && complete) {
    return stats.cleanSheets >= (target?.cleanSheets || 0) ? "hot" : "cold";
  }
  return "";
}

function formatBenchValue(raw, spec) {
  if (raw == null || Number.isNaN(Number(raw))) return "—";
  const digits = spec?.digits ?? 1;
  if (spec?.rate) return `${fmtNum(raw, digits)}%`;
  return fmtNum(raw, digits);
}

function scaledBench(key, stats, single) {
  const spec = state.payload?.benchmarks?.[key];
  if (!spec) return null;
  const games = spec.rate ? 1 : (single ? 1 : Math.max(Number(stats.played) || 0, 5));
  return {
    team: spec.team == null ? null : spec.team * games,
    top7: spec.top7 == null ? null : spec.top7 * games,
    spec,
  };
}

function meterTone(value, top7, higherBetter) {
  if (value == null || Number.isNaN(Number(value))) return "";
  const v = Number(value);
  if (higherBetter && v < 0) return "cold";
  if (top7 == null || Number.isNaN(Number(top7))) return "";
  const t = Number(top7);
  if (higherBetter) {
    if (v >= t) return "hot";
    if (v >= t * 0.8) return "warn";
    return "cold";
  }
  if (v <= t) return "hot";
  if (v <= t * 1.2) return "warn";
  return "cold";
}

function formatBench(value, { rate = false, digits = 1 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return rate ? `${fmtNum(value, digits)}%` : fmtNum(value, digits);
}

function benchMatchesValue(benchValue, value) {
  if (benchValue == null || value == null) return true;
  const a = Number(benchValue);
  const b = Number(value);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return true;
  const tol = Math.max(0.05, Math.abs(b) * 0.02);
  return Math.abs(a - b) <= tol;
}

function meterHtml(value, bench, { higherBetter = true } = {}) {
  const team = bench?.team;
  const top7 = bench?.top7;
  if (value == null || (team == null && top7 == null)) return "";
  const nums = [Number(value) || 0];
  if (team != null && !benchMatchesValue(team, value)) nums.push(Number(team));
  if (top7 != null) nums.push(Number(top7));
  const max = Math.max(...nums, 0.01) * 1.18;
  const pct = (n) => Math.max(1.5, Math.min(98.5, (Number(n) / max) * 100));
  const tone = meterTone(value, top7, higherBetter);
  const reqPct = top7 == null ? null : pct(top7);
  const avgPct = team == null || benchMatchesValue(team, value) ? null : pct(team);
  return `
    <div class="ba-meter ba-meter--compact ba-meter--${tone}">
      <span class="ba-meter__track">
        <span class="ba-meter__fill" style="width:${pct(value)}%"></span>
        ${avgPct == null ? "" : `<i class="ba-meter__tick ba-meter__tick--avg" style="left:${avgPct}%"></i>`}
        ${reqPct == null ? "" : `<i class="ba-meter__tick ba-meter__tick--req" style="left:${reqPct}%"></i>`}
      </span>
    </div>
  `;
}

function formatMetric(value, { rate = false, digits = 0 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return rate ? `${fmtNum(value, digits)}%` : fmtNum(value, digits);
}

function unitValueText(metricKey, row) {
  if (metricKey === "duelRate") {
    return row?.duelRate == null ? "—" : `${fmtNum(row.duelRate, 1)}%`;
  }
  if (metricKey === "aerialRate") {
    return row?.aerialRate == null ? "—" : `${fmtNum(row.aerialRate, 1)}%`;
  }
  if (metricKey === "xg" || metricKey === "packingXg") return fmtNum(row?.[metricKey], 2);
  if (metricKey === "crossPxt") {
    return row?.crossPxt == null ? "—" : `${fmtNum(row.crossPxt, 1)}%`;
  }
  if (metricKey === "shots" || metricKey === "assists") return fmtNum(row?.[metricKey], 0);
  if (metricKey === "pxtShot" || metricKey === "pxtDribble") return fmtNum(row?.[metricKey], 1);
  return fmtNum(row?.[metricKey], 1);
}

function unitSubText(metricKey, row) {
  if (metricKey === "duelRate" && row?.duelTotal) {
    return `${fmtNum(row.duelWon)} / ${fmtNum(row.duelTotal)}`;
  }
  if (metricKey === "aerialRate" && row?.aerialTotal) {
    return `${fmtNum(row.aerialWon)} / ${fmtNum(row.aerialTotal)}`;
  }
  return "";
}

function unitBenchValues(metricKey, unit, single, played, unitRow) {
  const spec = state.payload?.benchmarks?.units?.[unit]?.[metricKey];
  if (!spec) return { team: null, top7: null, spec: null };
  const games = spec.rate ? 1 : (single ? 1 : Math.max(Number(played) || 0, 5));
  const baseline = Number(spec.baselineStarters || { DEF: 4, MID: 3, ATT: 3 }[unit] || 3);
  const starters = Number(unitRow?.starters || 0) || baseline;
  const scale = spec.rate ? 1 : (baseline > 0 ? starters / baseline : 1);
  return {
    team: spec.team == null ? null : spec.team * games,
    top7: spec.top7 == null ? null : spec.top7 * games * scale,
    spec,
    starters,
    baseline,
  };
}

function unitPanelHtml(title, metricKey, hint, stats, single) {
  const units = stats.units || {};
  const rate = metricKey === "duelRate";
  const digits = rate ? 1 : 1;
  const rows = ["DEF", "MID", "ATT"].map((unit) => {
    const row = units[unit] || {};
    const bench = unitBenchValues(metricKey, unit, single, stats.played, units[unit]);
    const value = rate ? row.duelRate : row.defendersBypassed;
    const extra = unitSubText(metricKey, row);
    const tone = meterTone(value, bench.top7, true);
    const reqText = bench.top7 == null
      ? ""
      : `<span class="ba-unitrow__req"><em>Req</em><b>${escapeHtml(formatBench(bench.top7, { rate, digits }))}</b></span>`;
    return `
      <div class="ba-unitrow">
        <span class="ba-unitrow__unit">${unit}</span>
        <div class="ba-unitrow__mid">
          <div class="ba-unitrow__nums">
            <span class="ba-unitrow__val ${tone ? `is-${tone}` : ""}">${escapeHtml(unitValueText(metricKey, row))}</span>
            ${extra ? `<span class="ba-unitrow__sub">${escapeHtml(extra)}</span>` : ""}
            ${reqText}
          </div>
          ${meterHtml(value, bench, { higherBetter: true })}
        </div>
      </div>
    `;
  }).join("");
  return `
    <article class="ba-unitpanel">
      <header class="ba-unitpanel__head">
        <h4>${escapeHtml(title)}</h4>
        <p>${escapeHtml(hint)}</p>
      </header>
      ${rows}
    </article>
  `;
}

const PLAYER_BOARDS = [
  { key: "ppg", label: "Points per game", hint: "Team points when they played", digits: 2 },
  { key: "xg", label: "Expected goals", hint: "Open-play shot xG (excl. pens & DFKs)", digits: 2 },
  { key: "offensiveInterventions", label: "Aggressive regains", hint: "Opponents removed when you win the ball", digits: 0 },
  { key: "defensiveInterventions", label: "Defensive ball wins", hint: "Teammates added when you win the ball", digits: 0 },
  { key: "regainsFromDefenders", label: "Regains from opp defenders", hint: "Won it vs one of their four deepest", digits: 0 },
  { key: "defendersBypassed", label: "Backline beaten", hint: "Passes or dribbles that beat a defender", digits: 1 },
  { key: "duelRate", label: "Duels won", hint: "Won of attempted", digits: 1, rate: true, minDuels: 3 },
];

const UNIT_SLIDES = [
  {
    id: "DEF",
    title: "Defence",
    who: "Centre-backs & full-backs",
    note: "Full-backs count here. Wing-backs in a back three do not.",
    groups: [
      {
        label: "Out of possession",
        metrics: [
          { key: "duelRate", label: "Duels won", hint: "Ground + aerial combined", digits: 1, rate: true },
          { key: "defensiveInterventions", label: "Defensive ball wins", hint: "Teammates added when we win it", digits: 1 },
          { key: "offensiveInterventions", label: "Aggressive regains", hint: "Opponents removed on ball wins", digits: 1 },
        ],
      },
      {
        label: "In possession",
        metrics: [
          { key: "defendersBypassed", label: "Backline beaten", hint: "Beat a defender on the ball", digits: 1 },
          { key: "ballProgression", label: "Ball progression", hint: "Opponents beaten on the ball", digits: 1 },
        ],
      },
    ],
    goldLeaders: [
      { key: "goals", label: "Most goals", digits: 0, allowZero: false },
      { key: "assists", label: "Most assists", digits: 0, allowZero: false },
      { key: "defensiveInterventions", label: "Defensive interventions", digits: 0 },
    ],
  },
  {
    id: "MID",
    title: "Midfield",
    who: "Holding & central midfielders",
    note: "Only midfielders in the standout.",
    groups: [
      {
        label: "Out of possession",
        metrics: [
          { key: "offensiveInterventions", label: "Aggressive regains", hint: "Opponents removed on ball wins", digits: 1 },
          { key: "duelRate", label: "Duels won", hint: "Ground + aerial", digits: 1, rate: true },
          { key: "defensiveInterventions", label: "Defensive ball wins", hint: "Teammates added when we win it", digits: 1 },
        ],
      },
      {
        label: "In possession",
        metrics: [
          { key: "defendersBypassed", label: "Backline beaten", hint: "Beat a defender on the ball", digits: 1 },
          { key: "ballProgression", label: "Ball progression", hint: "Opponents beaten on the ball", digits: 1 },
          { key: "xg", label: "Expected goals", hint: "Open play · no pens / DFKs", digits: 2 },
        ],
      },
    ],
    goldLeaders: [
      { key: "goals", label: "Most goals", digits: 0, allowZero: false },
      { key: "assists", label: "Most assists", digits: 0, allowZero: false },
      { key: "offensiveInterventions", label: "Offensive interventions", digits: 0 },
    ],
  },
  {
    id: "ATT",
    title: "Attack",
    who: "Forwards & wingers",
    note: "Forwards and wingers. Shots and xG exclude pens and DFKs.",
    groups: [
      {
        label: "Chance",
        metrics: [
          { key: "xg", label: "Expected goals", hint: "Open play · no pens / DFKs", digits: 2 },
          { key: "shots", label: "Total shots", hint: "Open play · no pens / DFKs", digits: 0 },
          { key: "defendersBypassed", label: "Backline beaten", hint: "Beat a defender on the ball", digits: 1 },
          { key: "crossPxt", label: "Crossed expected threat", hint: "Altered threat from high & low crosses", digits: 1, rate: true },
        ],
      },
      {
        label: "Out of possession",
        metrics: [
          { key: "offensiveInterventions", label: "Aggressive regains", hint: "Opponents removed when we win it", digits: 1 },
          { key: "regainsFromDefenders", label: "Regains from opp defenders", hint: "Won it vs one of their four deepest", digits: 1 },
          { key: "duelRate", label: "Duels won", hint: "Ground + aerial", digits: 1, rate: true },
        ],
      },
    ],
    goldLeaders: [
      { key: "goals", label: "Most goals", digits: 0, allowZero: false },
      { key: "assists", label: "Most assists", digits: 0, allowZero: false },
      { key: "shots", label: "Most shots", digits: 0 },
    ],
  },
];

function aggregatePlayers(fixtures) {
  const byId = {};
  (fixtures || []).filter((row) => row.played).forEach((fixture) => {
    const teamPoints = Number(fixture.stats?.points) || 0;
    (fixture.stats?.players || []).forEach((player) => {
      const id = player.playerId;
      if (!id) return;
      const row = byId[id] || {
        playerId: id,
        name: player.name,
        unit: player.unit || "",
        appearances: 0,
        minutes: 0,
        points: 0,
        xg: 0,
        offensiveInterventions: 0,
        defensiveInterventions: 0,
        regainsFromDefenders: 0,
        defendersBypassed: 0,
        duelWon: 0,
        duelTotal: 0,
        aerialWon: 0,
        aerialTotal: 0,
        ballProgression: 0,
        shots: 0,
        assists: 0,
        packingXg: 0,
        crossPxt: 0,
        pxtShot: 0,
        pxtDribble: 0,
        goals: 0,
      };
      row.name = player.name || row.name;
      row.unit = player.unit || row.unit;
      row.appearances += 1;
      row.minutes += Number(player.minutes) || 0;
      row.points += teamPoints;
      row.xg += Number(player.xg) || 0;
      row.offensiveInterventions += Number(player.offensiveInterventions) || 0;
      row.defensiveInterventions += Number(player.defensiveInterventions) || 0;
      row.regainsFromDefenders += Number(player.regainsFromDefenders) || 0;
      row.defendersBypassed += Number(player.defendersBypassed) || 0;
      row.duelWon += Number(player.duelWon) || 0;
      row.duelTotal += Number(player.duelTotal) || 0;
      row.aerialWon += Number(player.aerialWon) || 0;
      row.aerialTotal += Number(player.aerialTotal) || 0;
      row.ballProgression += Number(player.ballProgression) || 0;
      row.shots += Number(player.shots) || 0;
      row.packingXg += Number(player.packingXg) || 0;
      row.crossPxt += Number(player.crossPxt) || 0;
      row.pxtShot += Number(player.pxtShot) || 0;
      row.pxtDribble += Number(player.pxtDribble) || 0;
      row.goals += Number(player.goals) || 0;
      row.assists += Number(player.assists) || 0;
      byId[id] = row;
    });
  });
  return Object.values(byId).map((row) => {
    row.ppg = row.appearances ? row.points / row.appearances : null;
    row.xg = Math.round(row.xg * 100) / 100;
    row.duelRate = row.duelTotal > 0 ? Math.round((row.duelWon / row.duelTotal) * 1000) / 10 : null;
    row.aerialRate = row.aerialTotal > 0 ? Math.round((row.aerialWon / row.aerialTotal) * 1000) / 10 : null;
    row.ballProgression = Math.round(row.ballProgression * 10) / 10;
    return row;
  });
}

function playersForUnit(players, unit) {
  return (players || []).filter((row) => row.unit === unit);
}

function vsReqText(value, top7, spec, higherBetter) {
  if (value == null || top7 == null || Number.isNaN(Number(value)) || Number.isNaN(Number(top7))) return "";
  const diff = Number(value) - Number(top7);
  const digits = spec.rate ? 1 : spec.digits;
  const signed = `${diff > 0 ? "+" : ""}${fmtNum(diff, digits)}`;
  const ok = higherBetter ? diff >= 0 : diff <= 0;
  return { text: signed, ok };
}

function slideMetricSpecs(slide) {
  return (slide.groups || [{ metrics: slide.metrics || [] }]).flatMap((group) => group.metrics || []);
}

function unitPulse(slide, stats, single) {
  const specs = slideMetricSpecs(slide);
  let hit = 0;
  const dots = specs.map((spec) => {
    const row = (stats.units || {})[slide.id] || {};
    const bench = unitBenchValues(spec.key, slide.id, single, stats.played, row);
    const higherBetter = bench?.spec?.higherBetter !== false;
    const tone = meterTone(row[spec.key], bench?.top7, higherBetter) || "mute";
    if (tone === "hot") hit += 1;
    return `<i class="ba-unitpulse__dot is-${tone}" title="${escapeHtml(spec.label)}"></i>`;
  });
  return { hit, total: specs.length, dots: dots.join("") };
}

function unitMetricRowHtml(unit, spec, stats, single) {
  const row = (stats.units || {})[unit] || {};
  const value = row[spec.key];
  const extra = unitSubText(spec.key, row);
  const bench = unitBenchValues(spec.key, unit, single, stats.played, row);
  const higherBetter = bench?.spec?.higherBetter !== false;
  const tone = meterTone(value, bench?.top7, higherBetter);
  const delta = vsReqText(value, bench?.top7, spec, higherBetter);
  return `
    <article class="ba-unitstat">
      <div class="ba-unitstat__head">
        <p class="ba-unitstat__label">${escapeHtml(spec.label)}</p>
        <p class="ba-unitstat__hint">${escapeHtml(spec.hint || "")}</p>
      </div>
      <div class="ba-unitstat__nums">
        <span class="ba-unitstat__val ${tone ? `is-${tone}` : ""}">${escapeHtml(unitValueText(spec.key, row))}</span>
        ${extra ? `<span class="ba-unitstat__sub">${escapeHtml(extra)}</span>` : ""}
        ${bench?.top7 == null ? "" : `<span class="ba-unitstat__req"><em>Req</em><b>${escapeHtml(formatBench(bench.top7, { rate: spec.rate, digits: spec.digits }))}</b></span>`}
        ${delta ? `<span class="ba-unitstat__delta ${delta.ok ? "is-hot" : "is-cold"}">${escapeHtml(delta.text)}</span>` : ""}
      </div>
      ${meterHtml(value, bench, { higherBetter })}
    </article>
  `;
}

function groupVerdictHtml(group, unit, stats, single) {
  if ((group.metrics || []).length >= 4) return "";
  let hit = 0;
  (group.metrics || []).forEach((spec) => {
    const row = (stats.units || {})[unit] || {};
    const bench = unitBenchValues(spec.key, unit, single, stats.played, row);
    if (meterTone(row[spec.key], bench?.top7, bench?.spec?.higherBetter !== false) === "hot") hit += 1;
  });
  const total = (group.metrics || []).length;
  const tone = hit === total && total ? "hot" : hit === 0 ? "cold" : "warn";
  const line = hit === total
    ? "Every metric at or above Req."
    : hit === 0
      ? "Every metric below the top-7 line."
      : `${hit} of ${total} at Req.`;
  return `
    <aside class="ba-unitverdict is-${tone}">
      <strong>${hit} / ${total}</strong>
      <span>at Req</span>
      <p>${escapeHtml(line)}</p>
    </aside>
  `;
}

function unitWhoCopy(slide, stats) {
  const row = (stats.units || {})[slide.id] || {};
  const starters = Number(row.starters) || 0;
  const starterNames = (row.starterNames || []).filter(Boolean);
  const benchNames = (row.benchNames || []).filter(Boolean);
  const countWord = { 1: "one", 2: "two", 3: "three", 4: "four", 5: "five" }[starters];
  const unitWord = { DEF: "defence", MID: "midfield", ATT: "attack" }[slide.id] || slide.title.toLowerCase();
  const title = starters
    ? `${countWord || starters}-man ${unitWord}`
    : slide.who;
  const bits = [];
  if (starterNames.length) bits.push(`${starterNames.join(", ")} started`);
  if (benchNames.length) bits.push(`${benchNames.join(", ")} off the bench`);
  const note = bits.length ? bits.join(" · ") : (slide.note || "");
  return { title, note };
}

const PE_UNIT_HEADINGS = {
  DEF: "DEFENCE TARGETS",
  MID: "MIDFIELD TARGETS",
  ATT: "ATTACK TARGETS",
};

const PE_ICONS_LEFT = [
  `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M31 8l-10 18h8l-4 14 18-23h-8l5-9z" fill="currentColor"/></svg>`,
  `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M18 50c9-5 16-13 20-23 3 4 7 8 12 11-7 2-13 6-18 12-2-1-8 0-14 0z" fill="currentColor"/><circle cx="30" cy="18" r="7" fill="currentColor"/></svg>`,
  `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M32 18c-8 0-14 6-14 14 0 10 14 24 14 24s14-14 14-24c0-8-6-14-14-14z" fill="currentColor"/></svg>`,
  `<svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="22" fill="none" stroke="currentColor" stroke-width="5"/><path d="M32 18v16l10 8" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>`,
];

const PE_ICONS_RIGHT = [
  `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M10 18h12l4 28 8-36 8 36 4-28h12" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M16 42l12-12 8 8 12-14" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><path d="M42 24h10v10" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  `<svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="18" cy="18" r="6" fill="currentColor"/><circle cx="46" cy="18" r="6" fill="currentColor"/><circle cx="32" cy="46" r="6" fill="currentColor"/><path d="M22 22l8 18M42 22l-8 18" fill="none" stroke="currentColor" stroke-width="4"/></svg>`,
  `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M10 32c6-9 13-13 22-13s16 4 22 13c-6 9-13 13-22 13S16 41 10 32z" fill="none" stroke="currentColor" stroke-width="5"/><circle cx="32" cy="32" r="7" fill="currentColor"/></svg>`,
];

function reportTab(blockId) {
  return state.reportTabs[blockId] || "staff";
}

function metricAtReq(spec, unit, stats, single) {
  const row = (stats.units || {})[unit] || {};
  const bench = unitBenchValues(spec.key, unit, single, stats.played, row);
  const higherBetter = bench?.spec?.higherBetter !== false;
  return meterTone(row[spec.key], bench?.top7, higherBetter) === "hot";
}

function playerExportTargetRow(spec, unit, stats, single, index) {
  const row = (stats.units || {})[unit] || {};
  const bench = unitBenchValues(spec.key, unit, single, stats.played, row);
  const hit = metricAtReq(spec, unit, stats, single);
  const reqPart = bench?.top7 == null
    ? ""
    : ` - REQ ${formatBench(bench.top7, { rate: spec.rate, digits: spec.digits })}`;
  const label = `${spec.label.toUpperCase()}${reqPart}`;
  const mark = hit
    ? `<span class="ba-pe__mark ba-pe__mark--hit" aria-label="Target met">✓</span>`
    : `<span class="ba-pe__mark ba-pe__mark--miss" aria-label="Target missed">✕</span>`;
  return `
    <div class="ba-pe__row">
      <div class="ba-pe__icon ba-pe__icon--left">${PE_ICONS_LEFT[index % PE_ICONS_LEFT.length]}</div>
      <p class="ba-pe__label">${escapeHtml(label)}</p>
      ${mark}
      <div class="ba-pe__icon ba-pe__icon--right">${PE_ICONS_RIGHT[index % PE_ICONS_RIGHT.length]}</div>
    </div>
  `;
}

function playerExportSlideHtml(slide, { stats, single, fixture, page, totalPages }) {
  const specs = slideMetricSpecs(slide);
  const hit = specs.filter((spec) => metricAtReq(spec, slide.id, stats, single)).length;
  const opponent = fixture?.opponentName
    ? String(fixture.opponentName).replace(/\s+FC$/i, "").trim().toUpperCase()
    : "";
  const rows = specs.map((spec, index) => playerExportTargetRow(spec, slide.id, stats, single, index)).join("");
  const vsHtml = opponent ? `<span class="ba-pe-slide__vs">(v ${escapeHtml(opponent)})</span>` : "";
  return `
    <article class="ba-pe-slide ba-pe-slide--${slide.id.toLowerCase()} ba-pe-slide--rows-${specs.length}">
      <div class="ba-pe-slide__grit" aria-hidden="true"></div>
      <div class="ba-pe-slide__slash ba-pe-slide__slash--one" aria-hidden="true"></div>
      <div class="ba-pe-slide__slash ba-pe-slide__slash--two" aria-hidden="true"></div>
      <header class="ba-pe-slide__hero">
        <div class="ba-pe-slide__hero-left">
          <img class="ba-pe-slide__badge" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" crossorigin="anonymous" />
          <div class="ba-pe-slide__avatar" aria-hidden="true"></div>
          <div class="ba-pe-slide__titles">
            <div class="ba-pe-slide__club">PORT VALE</div>
            <h2 class="ba-pe-slide__title">${escapeHtml(PE_UNIT_HEADINGS[slide.id] || slide.title.toUpperCase())}${vsHtml}</h2>
          </div>
        </div>
        <div class="ba-pe-slide__chip">${escapeHtml(slide.id)}</div>
      </header>
      <div class="ba-pe-slide__body">
        <div class="ba-pe-slide__targets">${rows}</div>
        <footer class="ba-pe-slide__strap">
          <span>${hit} OF ${specs.length} TARGETS AT REQ</span>
          <span>${page} / ${totalPages}</span>
        </footer>
      </div>
    </article>
  `;
}

function playerExportHtml(block) {
  const { stats, single, fixture } = selectedStats(block);
  if (!single) {
    return `
      <section class="ba-pe ba-pe--empty">
        <p class="ba-pe__hint">Select one game above to open the player export — each unit target shows a tick or cross vs the League Two top-7 Req line.</p>
      </section>
    `;
  }
  const slides = UNIT_SLIDES.map((slide, index) => playerExportSlideHtml(slide, {
    stats,
    single,
    fixture,
    page: index + 1,
    totalPages: UNIT_SLIDES.length,
  })).join("");
  return `<section class="ba-pe">${slides}</section>`;
}

function unitSheetHtml(slide, { mast, stats, single, players, page, outcome, foot }) {
  const who = unitWhoCopy(slide, stats);
  const unitPlayers = playersForUnit(players, slide.id);
  const pulse = unitPulse(slide, stats, single);
  const groups = (slide.groups || [{ label: "", metrics: slide.metrics || [] }]).map((group) => `
    <section class="ba-unitcol">
      <h3 class="ba-unitcol__label">${escapeHtml(group.label)}</h3>
      <div class="ba-unitcol__metrics">
        ${group.metrics.map((spec) => unitMetricRowHtml(slide.id, spec, stats, single)).join("")}
        ${groupVerdictHtml(group, slide.id, stats, single)}
      </div>
    </section>
  `).join("");
  return `
    <article class="ba-sheet ba-sheet--unit ba-sheet--unit-${slide.id.toLowerCase()} ${outcome ? `ba-sheet--${outcome}` : ""}" data-sheet="${page}">
      ${sheetMasthead({ ...mast, title: slide.title, page })}
      <div class="ba-sheet__body ba-sheet__body--unit">
        <div class="ba-unitpage__who">
          <b>${escapeHtml(who.title)}</b>
          ${who.note ? `<span>${escapeHtml(who.note)}</span>` : ""}
          <span class="ba-unitpulse" title="Metrics at Req">
            ${pulse.dots}
            <em>${pulse.hit}/${pulse.total} at Req</em>
          </span>
        </div>
        <div class="ba-unitpage">
          <div class="ba-unitpage__cols">${groups}</div>
          ${unitStarHtml(slide, unitPlayers)}
        </div>
      </div>
      <footer class="ba-sheet__bar"><span>Port Vale Analysis · ${escapeHtml(slide.title)}</span><span>${escapeHtml(foot)}</span></footer>
    </article>
  `;
}

function unitLeader(players, spec) {
  const first = topPlayers(players, spec)[0];
  if (!first) return null;
  if (spec.allowZero === false && Number(first[spec.key]) <= 0) return null;
  return first;
}

function unitGoldSlotHtml(spec, players) {
  const player = unitLeader(players, spec);
  if (!player) {
    return `
      <article class="ba-unitgold ba-unitgold--empty">
        <p class="ba-unitgold__label">${escapeHtml(spec.label)}</p>
        <p class="ba-unitgold__name">None</p>
        <p class="ba-unitgold__val">0</p>
      </article>
    `;
  }
  return `
    <article class="ba-unitgold">
      <p class="ba-unitgold__label">${escapeHtml(spec.label)}</p>
      <div class="ba-unitgold__row">
        ${playerPhotoHtml(player.name, "ba-photo ba-unitgold__photo")}
        <p class="ba-unitgold__name">${escapeHtml(player.name)}</p>
        <p class="ba-unitgold__val">${escapeHtml(formatPlayerValue(player, spec))}</p>
      </div>
    </article>
  `;
}

function unitStarHtml(slide, players) {
  const specs = slide.goldLeaders || [];
  return `
    <aside class="ba-unitstar">
      <p class="ba-unitstar__kicker">${escapeHtml(slide.title)} leaders</p>
      <div class="ba-unitstar__leaders">
        ${specs.map((spec) => unitGoldSlotHtml(spec, players)).join("")}
      </div>
    </aside>
  `;
}

function playersForView(block, single, fixture) {
  if (single) {
    if (!fixture?.played) return [];
    const teamPoints = Number(fixture.stats?.points) || 0;
    return (fixture.stats?.players || []).map((player) => ({
      ...player,
      appearances: 1,
      points: teamPoints,
      ppg: teamPoints,
    }));
  }
  return aggregatePlayers(block.fixtures);
}

function topPlayers(players, spec) {
  const minDuels = spec.minDuels || 0;
  const minAerials = spec.minAerials || 0;
  return [...players]
    .filter((row) => {
      const value = row[spec.key];
      if (value == null || Number.isNaN(Number(value))) return false;
      if (minDuels && Number(row.duelTotal || 0) < minDuels) return false;
      if (minAerials && Number(row.aerialTotal || 0) < minAerials) return false;
      return true;
    })
    .sort((a, b) => {
      const diff = Number(b[spec.key]) - Number(a[spec.key]);
      if (diff) return diff;
      return (Number(b.minutes) || 0) - (Number(a.minutes) || 0);
    })
    .slice(0, 5);
}

function playerPhotoUrl(name) {
  return `/api/player-photo?name=${encodeURIComponent(name || "")}&v=43`;
}

function playerPhotoHtml(name, className) {
  return `
    <span class="${escapeHtml(className)}" aria-hidden="true">
      <img src="${escapeHtml(playerPhotoUrl(name))}" alt="" onerror="this.closest('.ba-photo')?.classList.add('is-empty')" />
    </span>
  `;
}

function formatPlayerValue(row, spec) {
  const value = row[spec.key];
  if (value == null || Number.isNaN(Number(value))) return "—";
  if (spec.rate) return `${fmtNum(value, spec.digits)}%`;
  return fmtNum(value, spec.digits);
}

function playerBoardHtml(spec, players) {
  const rows = topPlayers(players, spec);
  const items = rows.length
    ? rows.map((row, index) => {
        const extra = spec.key === "duelRate" && row.duelTotal
          ? `<span class="ba-lead__sub">${escapeHtml(`${fmtNum(row.duelWon)} / ${fmtNum(row.duelTotal)}`)}</span>`
          : spec.key === "aerialRate" && row.aerialTotal
            ? `<span class="ba-lead__sub">${escapeHtml(`${fmtNum(row.aerialWon)} / ${fmtNum(row.aerialTotal)}`)}</span>`
          : (row.unit ? `<span class="ba-lead__sub">${escapeHtml(row.unit)}</span>` : "");
        return `
          <li class="ba-lead__row ${index === 0 ? "is-first" : ""}">
            <span class="ba-lead__rank">${index + 1}</span>
            ${playerPhotoHtml(row.name, "ba-photo ba-lead__photo")}
            <span class="ba-lead__name">${escapeHtml(row.name)}</span>
            ${extra}
            <span class="ba-lead__val">${escapeHtml(formatPlayerValue(row, spec))}</span>
          </li>
        `;
      }).join("")
    : `<li class="ba-lead__empty">No player data yet</li>`;
    const minNote = spec.minDuels
      ? `<span class="ba-lead__min">min. ${escapeHtml(String(spec.minDuels))} duels</span>`
      : spec.minAerials
        ? `<span class="ba-lead__min">min. ${escapeHtml(String(spec.minAerials))} aerials</span>`
      : "";
  return `
    <article class="ba-lead">
      <p class="ba-lead__label">${escapeHtml(spec.label)}${minNote}</p>
      <ol class="ba-lead__list">${items}</ol>
    </article>
  `;
}

function outcomeLabel(outcome) {
  if (outcome === "win") return "Win";
  if (outcome === "draw") return "Draw";
  if (outcome === "loss") return "Loss";
  return "Upcoming";
}

function clubBadge(src, initials, alt) {
  if (src) {
    return `<img class="ba-sheet__club-badge" src="${escapeHtml(src)}" alt="${escapeHtml(alt || "")}" crossorigin="anonymous" />`;
  }
  return `<span class="ba-sheet__club-init">${escapeHtml(initials || "?")}</span>`;
}

function sheetMasthead({ title, kicker, page, totalPages = 2, single, fixture, stats, block, phases }) {
  let center = "";
  if (single && fixture) {
    const gf = fixture.played ? fmtNum(stats.goals) : "–";
    const ga = fixture.played ? fmtNum(stats.goalsAgainst) : "–";
    const outcome = fixture.outcome || "tbc";
    const valeHome = fixture.isHome !== false;
    const valeClub = `
        <div class="ba-sheet__club">
          ${clubBadge("/standalone/port-vale-badge.png?v=2", "PV", "Port Vale")}
          <span class="ba-sheet__club-name">Port Vale</span>
        </div>`;
    const oppClub = `
        <div class="ba-sheet__club">
          ${clubBadge(fixture.badgeUrl, fixture.opponentInitials, fixture.opponentName)}
          <span class="ba-sheet__club-name">${escapeHtml(shortOpponent(fixture.opponentName))}</span>
        </div>`;
    const homeGoals = valeHome ? gf : ga;
    const awayGoals = valeHome ? ga : gf;
    center = `
      <div class="ba-sheet__scoreboard">
        ${valeHome ? valeClub : oppClub}
        <div class="ba-sheet__score">
          <div class="ba-sheet__score-row">
            <span class="ba-sheet__goals">${escapeHtml(homeGoals)}</span>
            <span class="ba-sheet__score-sep">–</span>
            <span class="ba-sheet__goals">${escapeHtml(awayGoals)}</span>
          </div>
          <span class="ba-sheet__result ba-sheet__result--${escapeHtml(outcome)}">${escapeHtml(outcomeLabel(outcome))}</span>
        </div>
        ${valeHome ? oppClub : valeClub}
      </div>
    `;
  } else {
    center = `
      <div class="ba-sheet__scoreboard ba-sheet__scoreboard--block">
        <div class="ba-sheet__score">
          <div class="ba-sheet__score-row">
            <span class="ba-sheet__goals">${escapeHtml(fmtNum(stats.points))}</span>
            <span class="ba-sheet__score-sep">/</span>
            <span class="ba-sheet__goals ba-sheet__goals--muted">${escapeHtml(fmtNum(block?.target?.points))}</span>
          </div>
          <span class="ba-sheet__result">${escapeHtml(fmtNum(stats.played))} played · ${escapeHtml(fmtNum(stats.goals))}–${escapeHtml(fmtNum(stats.goalsAgainst))}</span>
        </div>
      </div>
    `;
  }

  const meta = [];
  if (single && fixture) {
    if (fixture.dateLabel) meta.push(fixture.dateLabel);
    if (fixture.isHome != null) meta.push(fixture.isHome ? "Home" : "Away");
    if (fixture.demo) meta.push("Cup demo · not in league totals");
  }

  const phaseBar = phases ? mastPhasesHtml(phases) : "";
  return `
    <header class="ba-sheet__mast ${phaseBar ? "ba-sheet__mast--phases" : ""}">
      <div class="ba-sheet__brand">
        <p class="ba-sheet__kicker">${escapeHtml(kicker)}</p>
        <h3 class="ba-sheet__title">${escapeHtml(title)}</h3>
        ${meta.filter(Boolean).length ? `<p class="ba-sheet__meta">${escapeHtml(meta.filter(Boolean).join("  ·  "))}</p>` : ""}
      </div>
      ${center}
      <p class="ba-sheet__page"><b>${page}</b><span>/${totalPages}</span></p>
      ${phaseBar}
    </header>
  `;
}

function guideNum(n) {
  return `<span class="ba-gnum">${n}</span>`;
}

function guideCard(n, title, lead, text) {
  return `
    <article class="ba-gcard">
      ${guideNum(n)}
      <div class="ba-gcard__body">
        <h5>${escapeHtml(title)}</h5>
        <p class="ba-gcard__lead">${escapeHtml(lead)}</p>
        <p>${escapeHtml(text)}</p>
      </div>
    </article>
  `;
}

function guideDef(title, text) {
  return `
    <div class="ba-gdef">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(text)}</span>
    </div>
  `;
}

function guideBoardRows(count = 5) {
  return Array.from({ length: count }, (_, i) => `<i>${i + 1}.</i>`).join("");
}

function guideMapPage1() {
  return `
    <div class="ba-gmap ba-gmap--p1" aria-hidden="true">
      <div class="ba-gmap__label">Page 1 layout</div>
      <div class="ba-gmap__mast">
        ${guideNum(1)}
        <span class="ba-gmap__mast-score">Port Vale <b>1 – 2</b> Wolves</span>
        <div class="ba-gmap__mast-phase-wrap">
          ${guideNum(2)}
          <span class="ba-gmap__mast-phase">
          <i class="ba-phase__fill ba-phase__fill--IN_POSSESSION"></i>
          <i class="ba-phase__fill ba-phase__fill--ATTACKING_TRANSITION"></i>
          <i class="ba-phase__fill ba-phase__fill--SECOND_BALL"></i>
          <i class="ba-phase__fill ba-phase__fill--SET_PIECE"></i>
          <i class="ba-phase__fill ba-phase__fill--DEFENSIVE_TRANSITION"></i>
          <i class="ba-phase__fill ba-phase__fill--OUT_OF_POSSESSION"></i>
        </span>
        </div>
      </div>
      <div class="ba-gmap__strip">
        ${guideNum(3)}
        <span class="ba-gmap__pill ba-gmap__pill--xg">xG VS</span>
        <span class="ba-gmap__pill">Regains</span>
        <span class="ba-gmap__pill">Opp DEF</span>
        <span class="ba-gmap__pill">Backline</span>
        <span class="ba-gmap__pill">Duels</span>
      </div>
      <div class="ba-gmap__charts">
        <div class="ba-gmap__chart">${guideNum(4)}<span>Chance race</span><svg viewBox="0 0 80 48"><polyline points="2,46 22,38 40,20 58,14 78,8" fill="none" stroke="#111" stroke-width="2.2"/><polyline points="2,46 22,42 40,28 58,24 78,22" fill="none" stroke="#FDB913" stroke-width="2.2"/><line x1="40" y1="4" x2="40" y2="46" stroke="#c5bfb2" stroke-dasharray="3 3"/></svg></div>
        <div class="ba-gmap__chart">${guideNum(5)}<span>Territory</span><div class="ba-gmap__bars"><i></i><i></i><i></i><i></i><i></i><i></i></div></div>
        <div class="ba-gmap__chart ba-gmap__chart--pitch">${guideNum(6)}<span>In behind</span><div class="ba-gmap__pitch"><b></b><b class="hot"></b><b></b></div><div class="ba-gmap__recv"><span>Receiver</span><span>Receiver</span></div></div>
      </div>
      <div class="ba-gmap__units">
        <div class="ba-gmap__unit">${guideNum(7)}<em>Backline beaten</em><div class="ba-gmap__unit-bars"><span style="width:72%"></span><span style="width:55%"></span><span style="width:48%"></span></div><span>DEF · MID · ATT</span></div>
        <div class="ba-gmap__unit">${guideNum(8)}<em>Duels won</em><div class="ba-gmap__unit-bars"><span style="width:58%"></span><span style="width:62%"></span><span style="width:44%"></span></div><span>DEF · MID · ATT</span></div>
      </div>
    </div>
  `;
}

function guideMapPage2() {
  return `
    <div class="ba-gmap ba-gmap--p2" aria-hidden="true">
      <div class="ba-gmap__label">Page 2 layout</div>
      <div class="ba-gmap__stars">
        ${guideNum(1)}
        <div class="ba-gmap__star"><span></span><b>Player</b><em>xG</em></div>
        <div class="ba-gmap__star"><span></span><b>Player</b><em>Backline</em></div>
        <div class="ba-gmap__star"><span></span><b>Player</b><em>Duels</em></div>
      </div>
      <div class="ba-gmap__boards">
        ${guideNum(2)}
        <div class="ba-gmap__board"><em>xG</em>${guideBoardRows()}</div>
        <div class="ba-gmap__board"><em>Regains</em>${guideBoardRows()}</div>
        <div class="ba-gmap__board"><em>Def wins</em>${guideBoardRows()}</div>
        <div class="ba-gmap__board"><em>Opp DEF</em>${guideBoardRows()}</div>
        <div class="ba-gmap__board"><em>Backline</em>${guideBoardRows()}</div>
        <div class="ba-gmap__board"><em>Duels</em>${guideBoardRows()}</div>
      </div>
    </div>
  `;
}

function guideMeterDemo() {
  return `
    <div class="ba-gdemo">
      <p class="ba-gdemo__title">Reading the colours</p>
      <p class="ba-gdemo__intro">Every headline number has a bar underneath. The black mark is Req — the League Two top-7 line.</p>
      <div class="ba-gdemo__samples">
        <div class="ba-gdemo__sample">
          <span class="ba-gdemo__sample-val is-hot">52%</span>
          <span class="ba-gdemo__sample-track is-hot"><i style="width:82%"></i></span>
          <span class="ba-gdemo__sample-cap is-hot"><b>Green</b> — at or above Req</span>
        </div>
        <div class="ba-gdemo__sample">
          <span class="ba-gdemo__sample-val is-warn">41%</span>
          <span class="ba-gdemo__sample-track is-warn"><i style="width:65%"></i></span>
          <span class="ba-gdemo__sample-cap is-warn"><b>Amber</b> — close to Req</span>
        </div>
        <div class="ba-gdemo__sample">
          <span class="ba-gdemo__sample-val is-cold">28%</span>
          <span class="ba-gdemo__sample-track is-cold"><i style="width:44%"></i></span>
          <span class="ba-gdemo__sample-cap is-cold"><b>Red</b> — below Req</span>
        </div>
      </div>
      <div class="ba-gdemo__ref">
        <p><span class="ba-gdemo__pill ba-gdemo__pill--req">Req</span> Top 7 in League Two — promotion benchmark.</p>
        <p><span class="ba-gdemo__pill ba-gdemo__pill--avg">Avg</span> Vale’s usual level — only shown when it differs from this match.</p>
        <p><span class="ba-gdemo__pill ba-gdemo__pill--wb">WB</span> Full-backs count in DEF. Wing-backs in a back three do not.</p>
      </div>
    </div>
  `;
}

function guideSheetShell({ kicker, page, totalPages, title, bodyHtml, footNote }) {
  return `
    <article class="ba-sheet ba-sheet--guide" data-sheet="guide-${page}">
      <header class="ba-sheet__mast ba-sheet__mast--guide">
        <div class="ba-sheet__brand">
          <p class="ba-sheet__kicker">${escapeHtml(kicker)}</p>
          <h3 class="ba-sheet__title">${escapeHtml(title)}</h3>
          <p class="ba-sheet__meta">Match the yellow numbers on the map</p>
        </div>
        <p class="ba-sheet__page"><b>${page}</b><span>/${totalPages}</span></p>
      </header>
      <div class="ba-sheet__body ba-sheet__body--guide">${bodyHtml}</div>
      <footer class="ba-sheet__bar"><span>Port Vale Analysis</span><span>${escapeHtml(footNote)}</span></footer>
    </article>
  `;
}

function guideSheetsHtml({ kicker, fixture, totalPages = 4 }) {
  const opp = shortOpponent(fixture?.opponentName || "the opponent");
  const page1Body = `
    <div class="ba-guide ba-guide--visual">
      ${guideMapPage1()}
      <div class="ba-guide__legend ba-guide__legend--fill">
        <h4 class="ba-guide__legend-head">Match page 1 — what to look at</h4>
        <div class="ba-guide__cards ba-guide__cards--2 ba-guide__cards--fill">
          ${guideCard(1, "Scoreboard", "Who won and the final score.", "Club badges, goals and Win / Draw / Loss.")}
          ${guideCard(2, "Time in phase", "How the game actually felt.", "Coloured bar — in possession, defending, transitions, set pieces and second balls.")}
          ${guideCard(3, "Headline numbers", "Our five key team stats.", "xG, aggressive regains (opponents removed on ball wins), regains vs their deepest players, backline beaten and duels won — each with Req and Avg bars.")}
          ${guideCard(4, "Chance race", "Who built the better chances.", "Two lines through the game. Steeper = stronger spell. Football icons = goals.")}
          ${guideCard(5, "Territory", "Who lived in the final third.", `Attacking-third share overall and in 15-minute blocks vs ${opp}.`)}
          ${guideCard(6, "Balls in behind", "Did we get in behind their last line?", "Touches beyond their deepest defenders — left, centre, right. Brighter = more. Names = who received.")}
          ${guideCard(7, "Backline beaten", "Who broke their shape?", "Passes or dribbles that beat a defender — split by DEF, MID and ATT.")}
          ${guideCard(8, "Duels won", "Who won the physical battle?", "Duel success % for defenders, midfielders and attackers.")}
        </div>
      </div>
    </div>
  `;
  const page2Body = `
    <div class="ba-guide ba-guide--triple">
      ${guideMapPage2()}
      <div class="ba-guide__legend ba-guide__legend--fill">
        <h4 class="ba-guide__legend-head">Player page — who stood out</h4>
        <div class="ba-guide__cards ba-guide__cards--1">
          ${guideCard(1, "Standouts", "Three names to discuss first.", "Best expected goals, most backline beaten and best duel % in this match — with photos.")}
          ${guideCard(2, "Six leaderboards", "Full top-five lists.", "Every player ranked for xG, aggressive regains, defensive ball wins, regains off opp defenders, backline beaten and duels won.")}
          ${guideCard(3, "Unit target slides", "DEF, MID and ATT each have their own page.", "Five unit stats vs Req (top 7) and Vale Avg, plus the unit’s own leaderboards. Full-backs sit in DEF; wing-backs in a back three do not.")}
        </div>
        <div class="ba-guide__defs ba-guide__defs--fill">
          ${guideDef("Expected goals", "Shot quality added up — open play only (penalties and direct free kicks excluded), same as the VS card.")}
          ${guideDef("Aggressive regains", "Win the ball and remove opponents from the play — who you take out when you win it, not just the turnover.")}
          ${guideDef("Defensive ball wins", "Win the ball and add a teammate to the play.")}
          ${guideDef("Regains from opp defenders", "Ball wins where you beat one of their four deepest players — not only centre-backs and full-backs.")}
          ${guideDef("Backline beaten", "Line-breaking passes and dribbles — each time you beat a defender and take them out of the play.")}
          ${guideDef("Duels won", "Need at least 3 duels in the game to make the board.")}
        </div>
      </div>
      <div class="ba-guide__meter-col">${guideMeterDemo()}</div>
    </div>
  `;
  return guideSheetShell({
    kicker,
    page: 7,
    totalPages,
    title: "Guide · match overview (page 1)",
    bodyHtml: page1Body,
    footNote: "Pages 4–6 are DEF / MID / ATT unit targets",
  }) + guideSheetShell({
    kicker,
    page: 8,
    totalPages,
    title: "Guide · players & colours (page 2)",
    bodyHtml: page2Body,
    footNote: "Print all 8 pages for the full match pack",
  });
}

function xgVsHtml(stats, fixture) {
  const facts = stats.facts || {};
  const vale = facts.valeXg != null ? facts.valeXg : stats.xg;
  const opp = facts.oppXg;
  if (vale == null && opp == null) return "";
  const v = Number(vale) || 0;
  const o = Number(opp) || 0;
  const total = v + o;
  const valeShare = total > 0 ? (v / total) * 100 : 50;
  const delta = v - o;
  const valeAhead = delta > 0.004;
  const oppAhead = delta < -0.004;
  const bench = scaledBench("xg", stats, true);
  const oppName = shortOpponent(fixture?.opponentName || "Opp");
  const edge = total <= 0
    ? "No shots"
    : `${delta >= 0 ? "Vale" : oppName} +${fmtNum(Math.abs(delta), 2)}`;
  const exclNote = facts.xgExcludes
    ? `(excl. ${escapeHtml(facts.xgExcludes)})`
    : "(excl. PK &amp; DFK)";
  return `
    <article class="ba-xgvs">
      <p class="ba-xgvs__label">Expected goals <span class="ba-xgvs__excl">${exclNote}</span></p>
      <div class="ba-xgvs__fight">
        <div class="ba-xgvs__side ba-xgvs__side--vale ${valeAhead ? "is-ahead" : ""}">
          <span class="ba-xgvs__who">Vale</span>
          <span class="ba-xgvs__num">${escapeHtml(fmtNum(vale, 2))}</span>
          ${bench?.team == null || benchMatchesValue(bench.team, vale) ? "" : `<span class="ba-xgvs__avg">Avg ${escapeHtml(formatBench(bench.team, { digits: 2 }))}</span>`}
        </div>
        <span class="ba-xgvs__badge">VS</span>
        <div class="ba-xgvs__side ba-xgvs__side--opp ${oppAhead ? "is-ahead" : ""}">
          <span class="ba-xgvs__who">${escapeHtml(oppName)}</span>
          <span class="ba-xgvs__num">${escapeHtml(fmtNum(opp, 2))}</span>
          ${bench?.top7 == null ? "" : `<span class="ba-xgvs__req">Req against ${escapeHtml(formatBench(bench.top7, { digits: 2 }))}</span>`}
        </div>
      </div>
      <div class="ba-xgvs__bar" aria-hidden="true">
        <span class="ba-xgvs__fill ba-xgvs__fill--vale" style="width:${valeShare}%"></span>
      </div>
      <div class="ba-xgvs__foot">
        <span class="ba-xgvs__edge">${escapeHtml(edge)}</span>
        <span class="ba-xgvs__scope">Open play · no pens / direct free kicks</span>
      </div>
    </article>
  `;
}

function metricStrip(stats, single, fixture) {
  const items = single
    ? [
        { label: "Aggressive regains", key: "offensiveInterventions", digits: 0 },
        { label: "Regains from opp defenders", key: "ballWinsFromOppDefenders", digits: 0 },
        { label: "Backline beaten", key: "defendersBypassed", digits: 1 },
        { label: "Duels won", key: "duelRate", digits: 1, rate: true },
      ]
    : [
        { label: "Our xG", key: "xg", digits: 2 },
        { label: "Aggressive regains", key: "offensiveInterventions", digits: 0 },
        { label: "Regains from opp defenders", key: "ballWinsFromOppDefenders", digits: 0 },
        { label: "Backline beaten", key: "defendersBypassed", digits: 1 },
        { label: "Duels won", key: "duelRate", digits: 1, rate: true },
        { label: "Goals against", key: "goalsAgainst", digits: 0, invert: true },
      ];
  const vs = single ? xgVsHtml(stats, fixture) : "";
  return `
    <div class="ba-strip ${vs ? "ba-strip--vs" : ""}">
      ${vs}
      ${items.map((item) => {
        const value = item.value != null ? item.value : stats[item.key];
        const bench = item.skipBench ? null : scaledBench(item.key, stats, single);
        const higherBetter = item.invert ? false : (bench?.spec?.higherBetter !== false);
        const tone = meterTone(value, bench?.top7, higherBetter);
        const reqText = bench?.top7 == null
          ? ""
          : `<span class="ba-strip__req"><em>Req</em><b>${escapeHtml(formatBench(bench.top7, { rate: Boolean(item.rate || bench.spec?.rate), digits: item.digits }))}</b></span>`;
        return `
          <article class="ba-strip__cell">
            <p class="ba-strip__label">${escapeHtml(item.label)}</p>
            <div class="ba-strip__nums">
              <p class="ba-strip__value ${tone ? `is-${tone}` : ""}">${escapeHtml(formatMetric(value, item))}</p>
              ${reqText}
            </div>
            ${bench ? meterHtml(value, bench, { higherBetter }) : ""}
          </article>
        `;
      }).join("")}
    </div>
  `;
}

const PHASE_STRIP_ORDER = [
  "IN_POSSESSION",
  "ATTACKING_TRANSITION",
  "SECOND_BALL",
  "SET_PIECE",
  "DEFENSIVE_TRANSITION",
  "OUT_OF_POSSESSION",
];

function niceXgMax(value) {
  const padded = Math.max(Number(value) || 0, 0.01) * 1.12;
  if (padded <= 1) return 1;
  if (padded <= 1.5) return 1.5;
  if (padded <= 2) return 2;
  if (padded <= 3) return 3;
  if (padded <= 4) return 4;
  return Math.ceil(padded);
}

function racePolyline(series, endMinute, maxXg, box) {
  if (!series.length) return "";
  return series.map((point) => {
    const x = box.l + (Number(point.minute) / endMinute) * box.w;
    const y = box.t + box.h - (Number(point.xg) / maxXg) * box.h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function footballIconSvg() {
  return `
    <svg class="ba-ball" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10.5" fill="#fff" stroke="#111" stroke-width="1.45"/>
      <polygon points="12,7.15 15.25,9.55 14,13.65 10,13.65 8.75,9.55" fill="#111"/>
      <path d="M8.75 9.55 4.45 8.15M15.25 9.55 19.55 8.15M14 13.65 16.15 18.55M10 13.65 7.85 18.55M12 7.15V3.9M4.45 8.15 3.85 12.15 7.85 18.55M19.55 8.15 20.15 12.15 16.15 18.55"
        fill="none" stroke="#111" stroke-width="1.15" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>
  `;
}

function raceGoalBalls(side, series, endMinute, maxXg, box, vb) {
  return (series || [])
    .filter((point) => point.isGoal)
    .map((point) => {
      const x = box.l + (Number(point.minute) / endMinute) * box.w;
      const y = box.t + box.h - (Number(point.xg) / maxXg) * box.h;
      const left = (x / vb.w) * 100;
      const top = (y / vb.h) * 100;
      return `<span class="ba-race__ball ba-race__ball--${side}" style="left:${left.toFixed(2)}%;top:${top.toFixed(2)}%">${footballIconSvg()}</span>`;
    })
    .join("");
}

function xgRaceHtml(race) {
  if (!race?.vale?.series || !race?.opp?.series) return "";
  const endMinute = Math.max(Number(race.endMinute) || 90, 90);
  const htMinute = Number(race.htMinute) || 45;
  const maxXg = niceXgMax(Math.max(Number(race.vale.totalXg) || 0, Number(race.opp.totalXg) || 0));
  const vb = { w: 640, h: 280 };
  const box = { l: 36, t: 12, w: 586, h: 232 };
  const valePts = racePolyline(race.vale.series, endMinute, maxXg, box);
  const oppPts = racePolyline(race.opp.series, endMinute, maxXg, box);
  const htX = box.l + (htMinute / endMinute) * box.w;
  const yTicks = maxXg <= 1.5 ? [0, 0.5, 1, maxXg] : [0, maxXg / 2, maxXg];
  const uniqueTicks = [...new Set(yTicks.map((n) => Number(n.toFixed(2))))];
  const colour = opponentBarColour(race.opp.name);
  const oppStroke = colour.light ? "#c9a227" : colour.fill;
  const yGrid = uniqueTicks.map((tick) => {
    const y = box.t + box.h - (tick / maxXg) * box.h;
    return `
      <line class="ba-race__grid" x1="${box.l}" y1="${y.toFixed(1)}" x2="${box.l + box.w}" y2="${y.toFixed(1)}" />
      <text class="ba-race__tick" x="${box.l - 6}" y="${y.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${tick}</text>
    `;
  }).join("");
  const balls = raceGoalBalls("opp", race.opp.series, endMinute, maxXg, box, vb)
    + raceGoalBalls("vale", race.vale.series, endMinute, maxXg, box, vb);
  return `
    <article class="ba-chart ba-race" style="--race-opp:${oppStroke};--opp-fill:${colour.fill}">
      <header class="ba-chart__head ba-race__head">
        <div>
          <h4>Chance race</h4>
          <p>Expected goals over time</p>
        </div>
        <div class="ba-race__key">
          <p class="ba-race__key-item">
            <i class="ba-race__key-line ba-race__key-line--vale"></i>
            <span>Vale</span>
            <b>${escapeHtml(fmtNum(race.vale.totalXg, 2))}</b>
          </p>
          <p class="ba-race__key-item">
            <i class="ba-race__key-line ba-race__key-line--opp"></i>
            <span>${escapeHtml(shortOpponent(race.opp.name))}</span>
            <b>${escapeHtml(fmtNum(race.opp.totalXg, 2))}</b>
          </p>
          <p class="ba-race__key-item ba-race__key-item--goal">
            <span class="ba-race__key-ball">${footballIconSvg()}</span>
            <span>Goal</span>
          </p>
        </div>
      </header>
      <div class="ba-race__plot">
        <svg class="ba-race__svg" viewBox="0 0 ${vb.w} ${vb.h}" preserveAspectRatio="none" role="img" aria-label="Expected goals race">
          ${yGrid}
          <line class="ba-race__ht" x1="${htX.toFixed(1)}" y1="${box.t}" x2="${htX.toFixed(1)}" y2="${box.t + box.h}" />
          <text class="ba-race__ht-label" x="${htX.toFixed(1)}" y="${vb.h - 6}" text-anchor="middle">HT</text>
          <polyline class="ba-race__line ba-race__line--opp" points="${oppPts}" />
          <polyline class="ba-race__line ba-race__line--vale" points="${valePts}" />
        </svg>
        <div class="ba-race__balls">${balls}</div>
      </div>
    </article>
  `;
}

function avgGamesLabel(count) {
  const n = Number(count) || 0;
  return n > 0 ? `avg last ${n}` : "avg —";
}

function opponentBarColour(name) {
  const text = String(name || "").toLowerCase();
  const rows = [
    ["wolverhampton", "#FDB913", "#111"],
    ["wolves", "#FDB913", "#111"],
    ["walsall", "#E31C23", "#fff"],
    ["bradford", "#A3192F", "#fff"],
    ["notts", "#FFFFFF", "#111"],
    ["swindon", "#E20E0E", "#fff"],
    ["salford", "#E31C23", "#fff"],
    ["colchester", "#0055A4", "#fff"],
    ["tranmere", "#FFFFFF", "#111"],
    ["chesterfield", "#0033A0", "#fff"],
    ["bromley", "#FFFFFF", "#111"],
    ["grimsby", "#000040", "#fff"],
    ["crewe", "#E31C23", "#fff"],
    ["newport", "#F5C518", "#111"],
    ["cheltenham", "#D0103A", "#fff"],
    ["gillingham", "#0000A0", "#fff"],
    ["barrow", "#FFFFFF", "#111"],
    ["harrogate", "#F5C518", "#111"],
    ["accrington", "#E31C23", "#fff"],
    ["fleetwood", "#E31C23", "#fff"],
    ["barnet", "#000080", "#F5C518"],
    ["oldham", "#0033A0", "#fff"],
    ["carlisle", "#0033A0", "#fff"],
    ["morecambe", "#E31C23", "#fff"],
    ["mk dons", "#FFFFFF", "#111"],
    ["milton keynes", "#FFFFFF", "#111"],
    ["rotherham", "#E30613", "#fff"],
    ["lincoln", "#E4002B", "#fff"],
    ["bolton", "#FFFFFF", "#003087"],
    ["peterborough", "#0057B8", "#fff"],
    ["wycombe", "#009FE3", "#fff"],
  ];
  for (const [key, fill, ink] of rows) {
    if (text.includes(key)) {
      const light = Number.parseInt(fill.slice(1, 3), 16) * 0.299
        + Number.parseInt(fill.slice(3, 5), 16) * 0.587
        + Number.parseInt(fill.slice(5, 7), 16) * 0.114 > 170;
      return { fill, ink, light };
    }
  }
  return { fill: "#9a1f1f", ink: "#fff", light: false };
}

function fieldTiltHtml(tilt, fixture) {
  if (!tilt) {
    return `
      <article class="ba-chart ba-tilt">
        <header class="ba-chart__head">
          <div>
            <h4>Territory</h4>
            <p>Share of attacking-third play</p>
          </div>
        </header>
        <p class="ba-chart__empty">No attacking-third data</p>
      </article>
    `;
  }
  const focus = Math.min(100, Math.max(0, Number(tilt.focusPercent) || 0));
  const opp = Math.max(0, 100 - focus);
  const avg = tilt.avgPercent == null ? null : Number(tilt.avgPercent);
  const oppName = shortOpponent(fixture?.opponentName || "Opp");
  const colour = opponentBarColour(fixture?.opponentName);
  const light = colour.light ? " is-light" : "";
  const rows = (tilt.blocks || []).map((block) => {
    const value = Math.min(100, Math.max(0, Number(block.focus) || 0));
    const blockAvg = block.avg == null ? null : Math.min(100, Math.max(0, Number(block.avg)));
    return `
      <div class="ba-tilt__row">
        <span class="ba-tilt__row-lab">${escapeHtml(block.label || "")}</span>
        <div class="ba-tilt__row-track${light}">
          <span class="ba-tilt__row-vale" style="width:${value}%"></span>
          <span class="ba-tilt__row-opp" style="width:${Math.max(0, 100 - value)}%"></span>
          ${blockAvg == null ? "" : `<i class="ba-tilt__row-avg" style="left:${blockAvg}%"></i>`}
        </div>
        <span class="ba-tilt__row-val">${escapeHtml(fmtNum(value, 0))}</span>
      </div>
    `;
  }).join("");
  return `
    <article class="ba-chart ba-tilt" style="--opp-fill:${colour.fill};--opp-ink:${colour.ink}">
      <header class="ba-chart__head">
        <div>
          <h4>Territory</h4>
          <p>Attacking-third share · ${escapeHtml(avgGamesLabel(tilt.avgGames))}</p>
        </div>
        <p class="ba-chart__legend ba-tilt__legend">
          <span><i class="ba-tilt__swatch ba-tilt__swatch--vale"></i> Vale ${escapeHtml(fmtNum(focus, 1))}%</span>
          <span><i class="ba-tilt__swatch ba-tilt__swatch--opp"></i> ${escapeHtml(oppName)} ${escapeHtml(fmtNum(opp, 0))}%</span>
          ${avg == null ? "" : `<span class="ba-chart__avg">avg ${escapeHtml(fmtNum(avg, 1))}%</span>`}
        </p>
      </header>
      <div class="ba-tilt__rows">${rows}</div>
    </article>
  `;
}

function phaseStripSegments(rows, key) {
  return rows.map((row) => {
    const value = Math.min(100, Math.max(0, Number(row[key]) || 0));
    if (value <= 0) return "";
    return `<span class="ba-phasestrip__seg ba-phase__fill--${escapeHtml(row.id)}" style="width:${value}%" title="${escapeHtml(row.label)} ${fmtNum(value, 0)}%"></span>`;
  }).join("");
}

const MAST_PHASE_LABELS = {
  IN_POSSESSION: "In poss",
  ATTACKING_TRANSITION: "Att trans",
  SECOND_BALL: "2nd ball",
  SET_PIECE: "Set piece",
  DEFENSIVE_TRANSITION: "Def trans",
  OUT_OF_POSSESSION: "Out poss",
};

function mastPhasesHtml(phases) {
  if (!phases?.phases?.length) return "";
  const byId = Object.fromEntries((phases.phases || []).map((row) => [row.id, row]));
  const rows = PHASE_STRIP_ORDER.map((id) => byId[id]).filter(Boolean);
  if (!rows.length) return "";
  const parts = rows.map((row) => {
    const value = Math.min(100, Math.max(0, Number(row.percent) || 0));
    if (value <= 0) return "";
    return `
      <div class="ba-mastphase__part" style="flex:${value} 1 0%">
        <span class="ba-mastphase__seg ba-phase__fill--${escapeHtml(row.id)}"></span>
        <span class="ba-mastphase__cap">
          <em>${escapeHtml(MAST_PHASE_LABELS[row.id] || row.label)}</em>
          <b>${escapeHtml(fmtNum(value, 0))}%</b>
        </span>
      </div>
    `;
  }).join("");
  return `
    <div class="ba-mastphase">
      <p class="ba-mastphase__label">Time in phase</p>
      <div class="ba-mastphase__parts">${parts}</div>
    </div>
  `;
}

const BA_IB_LAYOUT = {
  IBWL: { x: 10, y: 14, w: 70, h: 142, cx: 45, valY: 86, name: "Left" },
  IB: { x: 80, y: 14, w: 80, h: 142, cx: 120, valY: 86, name: "Centre" },
  IBWR: { x: 160, y: 14, w: 70, h: 142, cx: 195, valY: 86, name: "Right" },
};

function behindHeat(value, maxVal, variant) {
  if (value <= 0) return { fill: "rgba(8, 28, 18, 0.72)", text: "#94a3b8" };
  const t = Math.min(1, Math.max(0, value / Math.max(maxVal, 1)));
  if (variant === "ib") {
    const r = Math.round(18 + t * 56);
    const g = Math.round(68 + t * 160);
    const b = Math.round(48 + t * 80);
    return { fill: `rgb(${r}, ${g}, ${b})`, text: t > 0.38 ? "#0f172a" : "#f8fafc" };
  }
  const r = Math.round(110 + t * 110);
  const g = Math.round(82 + t * 88);
  const b = Math.round(12 + t * 8);
  return { fill: `rgb(${r}, ${g}, ${b})`, text: t > 0.32 ? "#0f172a" : "#fef9c3" };
}

function behindPlayerList(title, rows, empty) {
  const items = (rows || []).map((row) => `
    <li>
      <span>${escapeHtml(row.name)}</span>
      <b>${escapeHtml(fmtNum(row.count, Number.isInteger(Number(row.count)) ? 0 : 1))}</b>
    </li>
  `).join("");
  return `
    <div class="ba-behind__list">
      <p>${escapeHtml(title)}</p>
      ${items ? `<ol>${items}</ol>` : `<span class="ba-behind__empty">${escapeHtml(empty)}</span>`}
    </div>
  `;
}

function behindHtml(data) {
  if (!data) {
    return `
      <article class="ba-chart ba-behind">
        <header class="ba-chart__head">
          <div>
            <h4>Balls in behind</h4>
            <p>Touches beyond the last line</p>
          </div>
        </header>
        <p class="ba-chart__empty">No in-behind data</p>
      </article>
    `;
  }
  const ibById = Object.fromEntries((data.ibZones || []).map((z) => [z.id, z]));
  const maxTouch = Math.max(1, ...(data.ibZones || []).map((z) => Number(z.value) || 0));
  const zones = ["IBWL", "IB", "IBWR"].map((id) => {
    const layout = BA_IB_LAYOUT[id];
    const value = Number(ibById[id]?.value) || 0;
    const colors = behindHeat(value, maxTouch, "ib");
    const shown = fmtNum(value, Number.isInteger(value) ? 0 : 1);
    return `
      <g>
        <rect x="${layout.x}" y="${layout.y}" width="${layout.w}" height="${layout.h}" fill="${colors.fill}" stroke="rgba(255,255,255,.2)" stroke-width="0.7"/>
        <text x="${layout.cx}" y="${layout.valY}" text-anchor="middle" fill="${colors.text}" class="ba-behind__zval">${shown}</text>
        <text x="${layout.cx}" y="${layout.valY + 16}" text-anchor="middle" fill="${colors.text}" class="ba-behind__zname">${layout.name}</text>
      </g>
    `;
  }).join("");
  return `
    <article class="ba-chart ba-behind">
      <header class="ba-chart__head">
        <div>
          <h4>Balls in behind</h4>
          <p>Touches beyond the last line</p>
        </div>
        <p class="ba-chart__legend">${escapeHtml(fmtNum(data.touches))} touches</p>
      </header>
      <div class="ba-behind__body">
        <div class="ba-behind__pitch">
          <svg class="ba-behind__svg" viewBox="0 0 240 170" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Balls in behind">
            <rect x="6" y="6" width="228" height="158" rx="6" fill="#145a35"/>
            ${zones}
            <rect x="88" y="14" width="64" height="52" fill="none" stroke="rgba(255,255,255,.55)" stroke-width="1"/>
            <rect x="102" y="14" width="36" height="18" fill="none" stroke="rgba(255,255,255,.4)" stroke-width="0.8"/>
            <rect x="6" y="6" width="228" height="158" rx="6" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1.1"/>
          </svg>
        </div>
        ${behindPlayerList("Who received", data.touchPlayers, "Nobody recorded")}
      </div>
    </article>
  `;
}

function playerStandouts(players) {
  const specs = [
    { key: "xg", label: "Highest expected goals", digits: 2 },
    { key: "defendersBypassed", label: "Most backline beaten", digits: 1 },
    { key: "duelRate", label: "Best duel success", digits: 1, rate: true, minDuels: 3 },
  ];
  const used = new Set();
  return specs.map((spec) => {
    const player = topPlayers(players.filter((row) => !used.has(row.playerId)), spec)[0] || null;
    if (player) used.add(player.playerId);
    return { spec, player };
  });
}

function standoutsHtml(players) {
  const cards = playerStandouts(players).map(({ spec, player }) => {
    if (!player) {
      return `<article class="ba-star ba-star--empty"><p class="ba-star__label">${escapeHtml(spec.label)}</p><p class="ba-star__empty">—</p></article>`;
    }
    return `
      <article class="ba-star">
        <p class="ba-star__label">${escapeHtml(spec.label)}</p>
        ${playerPhotoHtml(player.name, "ba-photo ba-star__photo")}
        <div class="ba-star__copy">
          <p class="ba-star__name">${escapeHtml(player.name)}</p>
          <p class="ba-star__val">${escapeHtml(formatPlayerValue(player, spec))}</p>
          ${player.unit ? `<p class="ba-star__unit">${escapeHtml(player.unit)}</p>` : ""}
        </div>
      </article>
    `;
  }).join("");
  return `<div class="ba-stars">${cards}</div>`;
}

function dashHtml(block) {
  const { stats, single, fixture } = selectedStats(block);
  const filterId = state.filters[block.id] || "all";
  const pills = [`<button type="button" class="ba-filter__btn ${filterId === "all" ? "is-active" : ""}" data-filter="all" data-block="${block.id}">All games</button>`]
    .concat(
      (block.fixtures || [])
        .filter((row) => row.matchId)
        .map((row) => {
          const active = String(filterId) === String(row.matchId);
          return `<button type="button" class="ba-filter__btn ${active ? "is-active" : ""}" data-filter="${row.matchId}" data-block="${block.id}">${escapeHtml(row.slot)}. ${escapeHtml(shortOpponent(row.opponentName))}</button>`;
        })
    )
    .concat(
      (block.demoFixtures || [])
        .filter((row) => row.matchId)
        .map((row) => {
          const active = String(filterId) === String(row.matchId);
          return `<button type="button" class="ba-filter__btn ba-filter__btn--demo ${active ? "is-active" : ""}" data-filter="${row.matchId}" data-block="${block.id}">Demo · ${escapeHtml(shortOpponent(row.opponentName))}</button>`;
        })
    )
    .join("");

  const payload = state.payload || {};
  const isDemo = Boolean(fixture?.demo);
  const kicker = isDemo
    ? `EFL Cup · ${payload.season || ""}`.trim()
    : `Block ${block.id} of 9 · ${payload.competition || "League Two"} ${payload.season || ""}`.trim();
  const pageTitle = single ? "Match Report" : "Block Report";
  const sheetPages = single ? 8 : 6;
  const mast = { kicker, single, fixture, stats, block, totalPages: sheetPages };
  const players = playersForView(block, single, fixture);
  const boards = (single ? PLAYER_BOARDS.filter((spec) => spec.key !== "ppg") : PLAYER_BOARDS)
    .map((spec) => playerBoardHtml(spec, players))
    .join("");
  const outcome = (single && fixture?.outcome) || "";
  const foot = "Req = League Two top-7 line, scaled to this XI";
  const unitSheets = UNIT_SLIDES.map((slide, index) => unitSheetHtml(slide, {
    mast,
    stats,
    single,
    players,
    page: 4 + index,
    outcome,
    foot,
  })).join("");

  const tab = reportTab(block.id);
  const playerExport = tab === "player-export";
  const staffSheets = `
      <p class="ba-print-hint ba-export-hide">A4 landscape · ${single ? "eight pages (block, match, players, three unit targets, staff guide)" : "six pages (block, overview, players, three unit targets)"}</p>
      <article class="ba-sheet ba-sheet--team ${outcome ? `ba-sheet--${outcome}` : ""}" data-sheet="2">
        ${sheetMasthead({ ...mast, title: pageTitle, page: 2, phases: single ? stats.phases : null })}
        <div class="ba-sheet__body">
          ${metricStrip(stats, single, fixture)}
          ${single ? `
            <div class="ba-charts">
              ${xgRaceHtml(stats.xgRace) || `<article class="ba-chart ba-race"><header class="ba-chart__head"><div><h4>Chance race</h4><p>Expected goals over time</p></div></header><p class="ba-chart__empty">No shot data</p></article>`}
              ${fieldTiltHtml(stats.fieldTilt, fixture)}
              ${behindHtml(stats.inBehind)}
            </div>
          ` : ""}
          <div class="ba-sheet__main ${single ? "ba-sheet__main--compact" : ""}">
            ${unitPanelHtml("Backline beaten", "defendersBypassed", "Passes or dribbles that beat a defender", stats, single)}
            ${unitPanelHtml("Duels won", "duelRate", "Success rate by unit", stats, single)}
          </div>
        </div>
        <footer class="ba-sheet__bar"><span>Port Vale Analysis</span><span>${escapeHtml(foot)}</span></footer>
      </article>
      <article class="ba-sheet ba-sheet--players ${outcome ? `ba-sheet--${outcome}` : ""}" data-sheet="3">
        ${sheetMasthead({ ...mast, title: "Players", page: 3 })}
        <div class="ba-sheet__body">
          ${single && players.length ? standoutsHtml(players) : ""}
          <div class="ba-players__grid ${single ? "ba-players__grid--six" : ""}">${boards}</div>
        </div>
        <footer class="ba-sheet__bar"><span>Port Vale Analysis</span><span>Live after full time</span></footer>
      </article>
      ${unitSheets}
      ${single ? guideSheetsHtml({ kicker, fixture, totalPages: sheetPages }) : ""}
  `;

  return `
    <section class="ba-report">
      <div class="ba-report__chrome ba-export-hide">
        <div class="ba-report__tabs" role="tablist" aria-label="Report view for block ${block.id}">
          <button type="button" role="tab" class="ba-report__tab ${tab === "staff" ? "is-active" : ""}" data-report-tab="staff" data-block="${block.id}" aria-selected="${tab === "staff"}">Staff report</button>
          <button type="button" role="tab" class="ba-report__tab ${playerExport ? "is-active" : ""}" data-report-tab="player-export" data-block="${block.id}" aria-selected="${playerExport}">Player export</button>
        </div>
        <div class="ba-report__tools">
          <div class="ba-filter" role="group" aria-label="Filter block ${block.id} to one game">${pills}</div>
          <div class="ba-report__actions">
            ${playerExport ? `
              <button type="button" class="ba-btn" data-print-player="${block.id}" ${single ? "" : "disabled"}>Print</button>
              <button type="button" class="ba-btn ba-btn--print" data-pdf-player="${block.id}" ${single ? "" : "disabled"}>Export PDF</button>
            ` : `
              <button type="button" class="ba-btn" data-print-report="${block.id}">Print</button>
              <button type="button" class="ba-btn ba-btn--print" data-pdf-report="${block.id}">Export PDF</button>
            `}
          </div>
        </div>
      </div>
      ${playerExport ? playerExportHtml(block) : staffSheets}
    </section>
  `;
}

function renderJump(blocks, currentBlockId) {
  els.jumpNav.innerHTML = blocks.map((block) => {
    const current = block.id === currentBlockId ? "is-current" : "";
    const done = block.status === "complete" ? "is-complete" : "";
    return `<button type="button" class="ba-jump__btn ${current} ${done}" data-jump="${block.id}">Block ${block.id}</button>`;
  }).join("");
}

function render() {
  const payload = state.payload;
  if (!payload) return;
  const y = window.scrollY;
  const blocks = payload.blocks || [];
  els.pageSubtitle.textContent = `${payload.competition || "League Two"} ${payload.season || ""} · ${payload.playedCount || 0} / ${payload.matchCount || 0} league games played`;
  renderJump(blocks, payload.currentBlockId);
  els.blocksRoot.innerHTML = blocks.map((block) => `
    <article class="ba-block" id="block-${block.id}">
      ${posterHtml(block)}
      ${dashHtml(block)}
    </article>
  `).join("");
  window.scrollTo(0, y);
}

async function load(refresh = false) {
  if (state.loading) return;
  state.loading = true;
  els.refreshBtn.disabled = true;
  setStatus(refresh ? "Refreshing live block data…" : "Loading blocks…", "loading");
  els.statusBar.textContent = "Loading…";
  try {
    const payload = await fetchJson(`/api/blocks-analysis${refresh ? "?refresh=true" : ""}`);
    state.payload = payload;
    (payload.blocks || []).forEach((block) => {
      if (state.filters[block.id]) return;
      const leaguePlayed = (block.fixtures || []).some((row) => row.played);
      const demo = (block.demoFixtures || []).find((row) => row.played && row.matchId);
      state.filters[block.id] = (!leaguePlayed && demo) ? String(demo.matchId) : "all";
    });
    render();
    setStatus("");
    els.statusBar.textContent = `Updated ${new Date(payload.generatedAt || Date.now()).toLocaleTimeString("en-GB")} · Block ${payload.currentBlockId} of 9`;
  } catch (err) {
    setStatus(err.message || "Failed to load Blocks Analysis", "error");
    els.statusBar.textContent = "Load failed";
  } finally {
    state.loading = false;
    els.refreshBtn.disabled = false;
  }
}

function medalDefaults(medal) {
  const spec = (state.payload?.medals || []).find((row) => row.id === medal);
  if (spec) return spec;
  return { points: 9, cleanSheets: 2, label: "SILVER • AUTOMATIC" };
}

async function saveTarget(blockId, patch) {
  const block = (state.payload?.blocks || []).find((row) => row.id === blockId);
  if (!block) return;
  const next = {
    medal: patch.medal ?? block.target.medal,
    points: patch.points ?? block.target.points,
    cleanSheets: patch.cleanSheets ?? block.target.cleanSheets,
  };
  block.target = {
    ...block.target,
    ...next,
    label: medalDefaults(next.medal).label || block.target.label,
  };
  block.pointsLabel = `${block.totals.points} / ${next.points}`;
  render();
  try {
    await fetchJson("/api/blocks-analysis/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        blockId,
        medal: next.medal,
        points: Number(next.points),
        cleanSheets: Number(next.cleanSheets),
      }),
    });
  } catch (err) {
    setStatus(err.message || "Could not save target", "error");
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load export library"));
    document.head.appendChild(script);
  });
}

function downloadDataUrl(dataUrl, filename) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function slug(value) {
  return String(value || "block")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

const SHEET_EXPORT_WIDTH = 1123;
const SHEET_EXPORT_HEIGHT = 794;
const SHEET_EXPORT_SCALE = 2;

function tidyMetersForPdf() {}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function reportPdfName(blockId) {
  const block = (state.payload?.blocks || []).find((row) => row.id === Number(blockId));
  if (!block) return "port-vale-match-report.pdf";
  const { single, fixture } = selectedStats(block);
  if (single && fixture?.opponentName) {
    return `Port-Vale-vs-${slug(shortOpponent(fixture.opponentName))}-match-report.pdf`;
  }
  return `Block-${blockId}-${slug(block.title || "report")}.pdf`;
}

function playerPdfName(blockId) {
  const block = (state.payload?.blocks || []).find((row) => row.id === Number(blockId));
  if (!block) return "port-vale-unit-targets.pdf";
  const { single, fixture } = selectedStats(block);
  if (single && fixture?.opponentName) {
    return `Port-Vale-${slug(shortOpponent(fixture.opponentName))}-unit-targets.pdf`;
  }
  return `Block-${blockId}-unit-targets.pdf`;
}

async function exportPlayerPdf(blockId) {
  const root = document.getElementById(`block-${blockId}`);
  const slides = [...(root?.querySelectorAll(".ba-pe-slide") || [])];
  if (!slides.length) throw new Error("Pick one game, then open Player export");
  await loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
  if (typeof html2canvas !== "function") throw new Error("PDF export failed to load");
  if (document.fonts?.ready) await document.fonts.ready;

  document.body.classList.add("is-pdf-capturing");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const pages = [];
  try {
    for (const slide of slides) {
      const canvas = await html2canvas(slide, {
        backgroundColor: "#13161b",
        scale: SHEET_EXPORT_SCALE,
        logging: false,
        useCORS: true,
        allowTaint: false,
        width: SHEET_EXPORT_WIDTH,
        height: SHEET_EXPORT_HEIGHT,
        windowWidth: SHEET_EXPORT_WIDTH,
        windowHeight: SHEET_EXPORT_HEIGHT,
        scrollX: 0,
        scrollY: 0,
        onclone: (_doc, cloned) => {
          cloned.classList.add("ba-pe-slide--pdf-capture");
          cloned.style.width = `${SHEET_EXPORT_WIDTH}px`;
          cloned.style.maxWidth = `${SHEET_EXPORT_WIDTH}px`;
          cloned.style.height = `${SHEET_EXPORT_HEIGHT}px`;
          cloned.style.minHeight = `${SHEET_EXPORT_HEIGHT}px`;
          cloned.style.aspectRatio = "auto";
          cloned.style.margin = "0";
          cloned.style.border = "0";
          cloned.style.borderRadius = "0";
          cloned.style.boxShadow = "none";
          cloned.style.overflow = "hidden";
        },
      });
      pages.push({
        imageData: canvas.toDataURL("image/png"),
        width: canvas.width,
        height: canvas.height,
      });
    }
  } finally {
    document.body.classList.remove("is-pdf-capturing");
  }

  const filename = playerPdfName(blockId);
  const response = await fetch("/api/blocks-analysis/export-pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pages,
      filename,
      document_title: "Port Vale Unit Targets",
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "PDF export failed");
  }
  downloadBlob(await response.blob(), filename);
}

async function exportReportPdf(blockId) {
  const root = document.getElementById(`block-${blockId}`);
  const poster = root?.querySelector(".ba-poster");
  const sheets = [poster, ...(root?.querySelectorAll(".ba-sheet") || [])].filter(Boolean);
  if (!sheets.length) throw new Error("Match report not found");
  await loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
  if (typeof html2canvas !== "function") throw new Error("PDF export failed to load");
  if (document.fonts?.ready) await document.fonts.ready;

  document.body.classList.add("is-pdf-capturing");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const pages = [];
  try {
    for (const sheet of sheets) {
      const canvas = await html2canvas(sheet, {
        backgroundColor: "#f3efe6",
        scale: SHEET_EXPORT_SCALE,
        logging: false,
        useCORS: true,
        allowTaint: false,
        width: SHEET_EXPORT_WIDTH,
        height: SHEET_EXPORT_HEIGHT,
        windowWidth: SHEET_EXPORT_WIDTH,
        windowHeight: SHEET_EXPORT_HEIGHT,
        scrollX: 0,
        scrollY: 0,
        onclone: (_doc, cloned) => {
          cloned.classList.add("ba-sheet--pdf-capture");
          cloned.querySelectorAll(".ba-export-hide").forEach((el) => { el.style.display = "none"; });
          tidyMetersForPdf(cloned);
          cloned.style.width = `${SHEET_EXPORT_WIDTH}px`;
          cloned.style.maxWidth = `${SHEET_EXPORT_WIDTH}px`;
          cloned.style.height = `${SHEET_EXPORT_HEIGHT}px`;
          cloned.style.minHeight = `${SHEET_EXPORT_HEIGHT}px`;
          cloned.style.aspectRatio = "auto";
          cloned.style.margin = "0";
          cloned.style.border = "0";
          cloned.style.borderRadius = "0";
          cloned.style.boxShadow = "none";
          cloned.style.overflow = "hidden";
        },
      });
      const trimmed = document.createElement("canvas");
      trimmed.width = Math.round(SHEET_EXPORT_WIDTH * SHEET_EXPORT_SCALE);
      trimmed.height = Math.round(SHEET_EXPORT_HEIGHT * SHEET_EXPORT_SCALE);
      const ctx = trimmed.getContext("2d");
      ctx.fillStyle = "#f3efe6";
      ctx.fillRect(0, 0, trimmed.width, trimmed.height);
      ctx.drawImage(canvas, 0, 0, trimmed.width, trimmed.height);
      pages.push({
        imageData: trimmed.toDataURL("image/png"),
        width: trimmed.width,
        height: trimmed.height,
      });
    }
  } finally {
    document.body.classList.remove("is-pdf-capturing");
  }

  const filename = reportPdfName(blockId);
  const response = await fetch("/api/blocks-analysis/export-pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pages,
      filename,
      document_title: "Port Vale Match Report",
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "PDF export failed");
  }
  downloadBlob(await response.blob(), filename);
}

function printReport(blockId) {
  const block = document.getElementById(`block-${blockId}`);
  if (!block) return;
  const playerDeck = block.querySelector(".ba-pe:not(.ba-pe--empty)");
  document.querySelectorAll(".ba-block.is-print-target").forEach((el) => el.classList.remove("is-print-target"));
  block.classList.add("is-print-target");
  document.body.classList.toggle("is-printing-player", Boolean(playerDeck));
  document.body.classList.add("is-printing");
  const tidy = () => {
    document.body.classList.remove("is-printing", "is-printing-player");
    block.classList.remove("is-print-target");
    window.removeEventListener("afterprint", tidy);
  };
  window.addEventListener("afterprint", tidy);
  requestAnimationFrame(() => {
    window.print();
    setTimeout(tidy, 2000);
  });
}

async function exportPoster(blockId) {
  await loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
  if (typeof html2canvas !== "function") throw new Error("PNG export failed to load");
  if (document.fonts?.ready) await document.fonts.ready;
  const poster = document.querySelector(`[data-poster="${blockId}"]`);
  if (!poster) throw new Error("Block poster not found");
  document.body.classList.add("is-exporting");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  try {
    const canvas = await html2canvas(poster, {
      backgroundColor: "#d7dbe2",
      scale: 2,
      logging: false,
      useCORS: true,
    });
    const block = (state.payload?.blocks || []).find((row) => row.id === Number(blockId));
    const name = `Block-${blockId}-${slug(block?.title || "league")}.png`;
    downloadDataUrl(canvas.toDataURL("image/png"), name);
  } finally {
    document.body.classList.remove("is-exporting");
  }
}

els.refreshBtn.addEventListener("click", () => load(true));
els.exportAllBtn.addEventListener("click", async () => {
  if (!state.payload?.blocks?.length) return;
  els.exportAllBtn.disabled = true;
  setStatus("Exporting posters…", "loading");
  try {
    for (const block of state.payload.blocks) {
      await exportPoster(block.id);
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    setStatus("PNGs downloaded.", "ok");
  } catch (err) {
    setStatus(err.message || "Export failed", "error");
  } finally {
    els.exportAllBtn.disabled = false;
  }
});

els.jumpNav.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-jump]");
  if (!btn) return;
  document.getElementById(`block-${btn.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
});

els.blocksRoot.addEventListener("click", async (event) => {
  const medalBtn = event.target.closest("[data-medal]");
  if (medalBtn) {
    const blockId = Number(medalBtn.dataset.block);
    const medal = medalBtn.dataset.medal;
    const defaults = medalDefaults(medal);
    await saveTarget(blockId, {
      medal,
      points: defaults.points,
      cleanSheets: defaults.cleanSheets,
    });
    return;
  }
  const filterBtn = event.target.closest("[data-filter]");
  if (filterBtn) {
    const blockId = Number(filterBtn.dataset.block);
    state.filters[blockId] = filterBtn.dataset.filter;
    render();
    return;
  }
  const tabBtn = event.target.closest("[data-report-tab]");
  if (tabBtn) {
    state.reportTabs[Number(tabBtn.dataset.block)] = tabBtn.dataset.reportTab;
    render();
    return;
  }
  const printBtn = event.target.closest("[data-print-report], [data-print-player]");
  if (printBtn) {
    printReport(Number(printBtn.dataset.printReport || printBtn.dataset.printPlayer));
    return;
  }
  const pdfBtn = event.target.closest("[data-pdf-report], [data-pdf-player]");
  if (pdfBtn) {
    pdfBtn.disabled = true;
    setStatus(pdfBtn.dataset.pdfPlayer ? "Building unit targets PDF…" : "Building A4 landscape PDF…", "loading");
    try {
      if (pdfBtn.dataset.pdfPlayer) {
        await exportPlayerPdf(Number(pdfBtn.dataset.pdfPlayer));
      } else {
        await exportReportPdf(Number(pdfBtn.dataset.pdfReport));
      }
      setStatus("PDF downloaded.", "ok");
    } catch (err) {
      setStatus(err.message || "PDF export failed", "error");
    } finally {
      pdfBtn.disabled = false;
    }
    return;
  }
  const exportBtn = event.target.closest("[data-export]");
  if (exportBtn) {
    exportBtn.disabled = true;
    try {
      await exportPoster(exportBtn.dataset.export);
    } catch (err) {
      setStatus(err.message || "Export failed", "error");
    } finally {
      exportBtn.disabled = false;
    }
  }
});

els.blocksRoot.addEventListener("change", async (event) => {
  const points = event.target.closest(".ba-aim__points");
  const cs = event.target.closest(".ba-aim__cs-input");
  const input = points || cs;
  if (!input) return;
  const blockId = Number(input.dataset.block);
  const value = Number(input.value);
  if (!Number.isFinite(value)) return;
  if (points) await saveTarget(blockId, { points: value });
  if (cs) await saveTarget(blockId, { cleanSheets: value });
});

load(false);
