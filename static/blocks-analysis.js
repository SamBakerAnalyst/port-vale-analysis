const FETCH_TIMEOUT_MS = 90000;

const state = {
  payload: null,
  filters: {},
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
  if (value == null || top7 == null || Number.isNaN(Number(value)) || Number.isNaN(Number(top7))) return "";
  const v = Number(value);
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

function meterHtml(value, bench, { higherBetter = true, rate = false, digits = 1 } = {}) {
  const team = bench?.team;
  const top7 = bench?.top7;
  if (value == null || (team == null && top7 == null)) return "";
  const nums = [Number(value) || 0];
  if (team != null) nums.push(Number(team));
  if (top7 != null) nums.push(Number(top7));
  const max = Math.max(...nums, 0.01) * 1.18;
  const pct = (n) => Math.max(0, Math.min(100, (Number(n) / max) * 100));
  const tone = meterTone(value, top7 ?? team, higherBetter);
  return `
    <div class="ba-meter ba-meter--${tone}">
      <span class="ba-meter__track">
        <span class="ba-meter__fill" style="width:${pct(value)}%"></span>
        ${team == null ? "" : `<span class="ba-meter__mark ba-meter__mark--avg" style="left:${pct(team)}%" title="Vale average"></span>`}
        ${top7 == null ? "" : `<span class="ba-meter__mark ba-meter__mark--req" style="left:${pct(top7)}%" title="League requirement"></span>`}
      </span>
      <div class="ba-meter__keys">
        ${team == null ? "" : `<span class="ba-meter__key ba-meter__key--avg">Vale avg ${escapeHtml(formatBench(team, { rate, digits }))}</span>`}
        ${top7 == null ? "" : `<span class="ba-meter__key ba-meter__key--req">League req ${escapeHtml(formatBench(top7, { rate, digits }))}</span>`}
      </div>
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
  return fmtNum(row?.defendersBypassed, 1);
}

function unitSubText(metricKey, row) {
  if (metricKey === "duelRate" && row?.duelTotal) {
    return `${fmtNum(row.duelWon)} / ${fmtNum(row.duelTotal)}`;
  }
  return "";
}

function unitBenchValues(metricKey, unit, single, played) {
  const spec = state.payload?.benchmarks?.units?.[unit]?.[metricKey];
  if (!spec) return { team: null, top7: null, spec: null };
  const games = spec.rate ? 1 : (single ? 1 : Math.max(Number(played) || 0, 5));
  return {
    team: spec.team == null ? null : spec.team * games,
    top7: spec.top7 == null ? null : spec.top7 * games,
    spec,
  };
}

function unitPanelHtml(title, metricKey, hint, stats, single) {
  const units = stats.units || {};
  const rate = metricKey === "duelRate";
  const rows = ["DEF", "MID", "ATT"].map((unit) => {
    const row = units[unit] || {};
    const bench = unitBenchValues(metricKey, unit, single, stats.played);
    const value = rate ? row.duelRate : row.defendersBypassed;
    const extra = unitSubText(metricKey, row);
    const tone = meterTone(value, bench.top7, true);
    return `
      <div class="ba-unitrow">
        <span class="ba-unitrow__unit">${unit}</span>
        <div class="ba-unitrow__mid">
          <div class="ba-unitrow__nums">
            <span class="ba-unitrow__val ${tone ? `is-${tone}` : ""}">${escapeHtml(unitValueText(metricKey, row))}</span>
            ${extra ? `<span class="ba-unitrow__sub">${escapeHtml(extra)}</span>` : ""}
          </div>
          ${meterHtml(value, bench, { higherBetter: true, rate, digits: rate ? 1 : 1 })}
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
  { key: "xg", label: "Expected goals", hint: "Shot xG created", digits: 2 },
  { key: "offensiveInterventions", label: "Attacking ball wins", hint: "Turnovers in attacking areas", digits: 0 },
  { key: "defensiveInterventions", label: "Defensive ball wins", hint: "Teammates added by winning it", digits: 0 },
  { key: "regainsFromDefenders", label: "Regains vs their defence", hint: "Won it against opposition defenders", digits: 0 },
  { key: "defendersBypassed", label: "Defenders taken out", hint: "Opponents taken out of the game", digits: 0 },
  { key: "duelRate", label: "Duels won", hint: "Won of attempted", digits: 1, rate: true, minDuels: 3 },
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
      byId[id] = row;
    });
  });
  return Object.values(byId).map((row) => {
    row.ppg = row.appearances ? row.points / row.appearances : null;
    row.xg = Math.round(row.xg * 100) / 100;
    row.duelRate = row.duelTotal > 0 ? Math.round((row.duelWon / row.duelTotal) * 1000) / 10 : null;
    return row;
  });
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
  return [...players]
    .filter((row) => {
      const value = row[spec.key];
      if (value == null || Number.isNaN(Number(value))) return false;
      if (minDuels && Number(row.duelTotal || 0) < minDuels) return false;
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
  return `/api/player-photo?name=${encodeURIComponent(name || "")}`;
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
          : (row.unit ? `<span class="ba-lead__sub">${escapeHtml(row.unit)}</span>` : "");
        return `
          <li class="ba-lead__row ${index === 0 ? "is-first" : ""}">
            <span class="ba-lead__rank">${index + 1}</span>
            <img class="ba-lead__photo" src="${escapeHtml(playerPhotoUrl(row.name))}" alt="" onerror="this.removeAttribute('src')" />
            <span class="ba-lead__name">${escapeHtml(row.name)}</span>
            ${extra}
            <span class="ba-lead__val">${escapeHtml(formatPlayerValue(row, spec))}</span>
          </li>
        `;
      }).join("")
    : `<li class="ba-lead__empty">No player data yet</li>`;
  return `
    <article class="ba-lead">
      <p class="ba-lead__label">${escapeHtml(spec.label)}</p>
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

function sheetMasthead({ title, kicker, page, single, fixture, stats, block }) {
  let center = "";
  if (single && fixture) {
    const gf = fixture.played ? fmtNum(stats.goals) : "–";
    const ga = fixture.played ? fmtNum(stats.goalsAgainst) : "–";
    const outcome = fixture.outcome || "tbc";
    center = `
      <div class="ba-sheet__scoreboard">
        <div class="ba-sheet__club">
          ${clubBadge("/standalone/port-vale-badge.png?v=2", "PV", "Port Vale")}
          <span class="ba-sheet__club-name">Port Vale</span>
        </div>
        <div class="ba-sheet__score">
          <div class="ba-sheet__score-row">
            <span class="ba-sheet__goals">${escapeHtml(gf)}</span>
            <span class="ba-sheet__score-sep">–</span>
            <span class="ba-sheet__goals">${escapeHtml(ga)}</span>
          </div>
          <span class="ba-sheet__result ba-sheet__result--${escapeHtml(outcome)}">${escapeHtml(outcomeLabel(outcome))}</span>
        </div>
        <div class="ba-sheet__club ba-sheet__club--opp">
          ${clubBadge(fixture.badgeUrl, fixture.opponentInitials, fixture.opponentName)}
          <span class="ba-sheet__club-name">${escapeHtml(shortOpponent(fixture.opponentName))}</span>
        </div>
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

  return `
    <header class="ba-sheet__mast">
      <div class="ba-sheet__brand">
        <p class="ba-sheet__kicker">${escapeHtml(kicker)}</p>
        <h3 class="ba-sheet__title">${escapeHtml(title)}</h3>
        ${meta.filter(Boolean).length ? `<p class="ba-sheet__meta">${escapeHtml(meta.filter(Boolean).join("  ·  "))}</p>` : ""}
      </div>
      ${center}
      <p class="ba-sheet__page"><b>${page}</b><span>/2</span></p>
    </header>
  `;
}

function xgVsHtml(stats, fixture) {
  const vale = stats.xg;
  const opp = stats.facts?.oppXg;
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
  return `
    <article class="ba-xgvs">
      <p class="ba-xgvs__label">Expected goals</p>
      <div class="ba-xgvs__fight">
        <div class="ba-xgvs__side ba-xgvs__side--vale ${valeAhead ? "is-ahead" : ""}">
          <span class="ba-xgvs__who">Vale</span>
          <span class="ba-xgvs__num">${escapeHtml(fmtNum(vale, 2))}</span>
        </div>
        <span class="ba-xgvs__badge">VS</span>
        <div class="ba-xgvs__side ba-xgvs__side--opp ${oppAhead ? "is-ahead" : ""}">
          <span class="ba-xgvs__who">${escapeHtml(oppName)}</span>
          <span class="ba-xgvs__num">${escapeHtml(fmtNum(opp, 2))}</span>
        </div>
      </div>
      <div class="ba-xgvs__bar" aria-hidden="true">
        <span class="ba-xgvs__fill ba-xgvs__fill--vale" style="width:${valeShare}%"></span>
      </div>
      <div class="ba-xgvs__foot">
        <span class="ba-xgvs__edge">${escapeHtml(edge)}</span>
        ${bench?.team == null ? "" : `<span class="ba-xgvs__key ba-xgvs__key--avg">Vale avg ${escapeHtml(formatBench(bench.team, { digits: 2 }))}</span>`}
        ${bench?.top7 == null ? "" : `<span class="ba-xgvs__key ba-xgvs__key--req">League req ${escapeHtml(formatBench(bench.top7, { digits: 2 }))}</span>`}
      </div>
    </article>
  `;
}

function metricStrip(stats, single, fixture) {
  const items = single
    ? [
        { label: "Attacking ball wins", key: "offensiveInterventions", digits: 0 },
        { label: "Regains vs defence", key: "ballWinsFromOppDefenders", digits: 0 },
        { label: "Defenders taken out", key: "defendersBypassed", digits: 0 },
        { label: "Duels won", key: "duelRate", digits: 1, rate: true },
      ]
    : [
        { label: "Our xG", key: "xg", digits: 2 },
        { label: "Attacking ball wins", key: "offensiveInterventions", digits: 0 },
        { label: "Regains vs defence", key: "ballWinsFromOppDefenders", digits: 0 },
        { label: "Defenders taken out", key: "defendersBypassed", digits: 0 },
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
        return `
          <article class="ba-strip__cell">
            <p class="ba-strip__label">${escapeHtml(item.label)}</p>
            <p class="ba-strip__value ${tone ? `is-${tone}` : ""}">${escapeHtml(formatMetric(value, item))}</p>
            ${bench ? meterHtml(value, bench, {
              higherBetter,
              rate: Boolean(item.rate || bench.spec?.rate),
              digits: item.digits,
            }) : ""}
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
  const goalDots = (side, cls) => (side.series || [])
    .filter((point) => point.isGoal)
    .map((point) => {
      const x = box.l + (Number(point.minute) / endMinute) * box.w;
      const y = box.t + box.h - (Number(point.xg) / maxXg) * box.h;
      return `<circle class="${cls}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" />`;
    })
    .join("");
  const yGrid = uniqueTicks.map((tick) => {
    const y = box.t + box.h - (tick / maxXg) * box.h;
    return `
      <line class="ba-race__grid" x1="${box.l}" y1="${y.toFixed(1)}" x2="${box.l + box.w}" y2="${y.toFixed(1)}" />
      <text class="ba-race__tick" x="${box.l - 6}" y="${y.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${tick}</text>
    `;
  }).join("");
  return `
    <article class="ba-chart ba-race">
      <header class="ba-chart__head">
        <div>
          <h4>Chance race</h4>
          <p>Expected goals over time · dots are goals</p>
        </div>
        <p class="ba-chart__legend">
          <span class="ba-race__swatch ba-race__swatch--vale"></span>
          Vale ${escapeHtml(fmtNum(race.vale.totalXg, 2))}
          <span class="ba-race__swatch ba-race__swatch--opp"></span>
          ${escapeHtml(shortOpponent(race.opp.name))} ${escapeHtml(fmtNum(race.opp.totalXg, 2))}
        </p>
      </header>
      <svg class="ba-race__svg" viewBox="0 0 ${vb.w} ${vb.h}" preserveAspectRatio="none" role="img" aria-label="Expected goals race">
        ${yGrid}
        <line class="ba-race__ht" x1="${htX.toFixed(1)}" y1="${box.t}" x2="${htX.toFixed(1)}" y2="${box.t + box.h}" />
        <text class="ba-race__ht-label" x="${htX.toFixed(1)}" y="${vb.h - 6}" text-anchor="middle">HT</text>
        <polyline class="ba-race__line ba-race__line--opp" points="${oppPts}" />
        <polyline class="ba-race__line ba-race__line--vale" points="${valePts}" />
        ${goalDots(race.opp, "ba-race__goal ba-race__goal--opp")}
        ${goalDots(race.vale, "ba-race__goal ba-race__goal--vale")}
      </svg>
    </article>
  `;
}

function avgGamesLabel(count) {
  const n = Number(count) || 0;
  return n > 0 ? `avg last ${n}` : "avg —";
}

function fieldTiltHtml(tilt) {
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
  const focus = Number(tilt.focusPercent);
  const opp = Math.max(0, 100 - focus);
  const avg = tilt.avgPercent == null ? null : Number(tilt.avgPercent);
  const avgMark = avg == null ? "" : `<i class="ba-tilt__mark" style="left:${Math.min(100, Math.max(0, avg))}%" title="Average ${fmtNum(avg, 1)}%"></i>`;
  const cols = (tilt.blocks || []).map((block) => {
    const value = Math.min(100, Math.max(0, Number(block.focus) || 0));
    const blockAvg = block.avg == null ? null : Math.min(100, Math.max(0, Number(block.avg)));
    return `
      <div class="ba-tilt__col">
        <span class="ba-tilt__col-val">${escapeHtml(fmtNum(value, 0))}</span>
        <div class="ba-tilt__col-track">
          ${blockAvg == null ? "" : `<i class="ba-tilt__col-avg" style="bottom:${blockAvg}%"></i>`}
          <span class="ba-tilt__col-fill" style="height:${value}%"></span>
        </div>
        <span class="ba-tilt__col-lab">${escapeHtml(block.label || "")}</span>
      </div>
    `;
  }).join("");
  return `
    <article class="ba-chart ba-tilt">
      <header class="ba-chart__head">
        <div>
          <h4>Territory</h4>
          <p>Attacking-third share · ${escapeHtml(avgGamesLabel(tilt.avgGames))}</p>
        </div>
        <p class="ba-chart__legend">
          Vale ${escapeHtml(fmtNum(focus, 1))}%
          ${avg == null ? "" : `<span class="ba-chart__avg">avg ${escapeHtml(fmtNum(avg, 1))}%</span>`}
        </p>
      </header>
      <div class="ba-tilt__overall">
        <span>Vale</span>
        <div class="ba-tilt__split">
          <span class="ba-tilt__split-fill" style="width:${Math.min(100, Math.max(0, focus))}%"></span>
          ${avgMark}
        </div>
        <span>Opp ${escapeHtml(fmtNum(opp, 0))}%</span>
      </div>
      <div class="ba-tilt__cols">${cols}</div>
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

function phasesHtml(phases) {
  if (!phases?.phases?.length) return "";
  const byId = Object.fromEntries((phases.phases || []).map((row) => [row.id, row]));
  const rows = PHASE_STRIP_ORDER.map((id) => byId[id]).filter(Boolean);
  if (!rows.length) return "";
  const hasAvg = rows.some((row) => row.avg != null);
  const legend = rows.map((row) => {
    const value = Number(row.percent) || 0;
    const avg = row.avg == null ? null : Number(row.avg);
    const delta = avg == null ? null : value - avg;
    const deltaText = delta == null
      ? ""
      : `<span class="ba-phasestrip__delta ${delta >= 0.5 ? "is-up" : delta <= -0.5 ? "is-down" : ""}">${delta >= 0 ? "+" : ""}${fmtNum(delta, 0)}</span>`;
    return `
      <li>
        <i class="ba-phase__fill--${escapeHtml(row.id)}"></i>
        <span>${escapeHtml(row.label)}</span>
        <b>${escapeHtml(fmtNum(value, 0))}%</b>
        ${avg == null ? "" : `<em>avg ${escapeHtml(fmtNum(avg, 0))} ${deltaText}</em>`}
      </li>
    `;
  }).join("");
  return `
    <article class="ba-phasestrip">
      <header class="ba-phasestrip__head">
        <div>
          <h4>How the game was spent</h4>
          <p>Share of time in each phase · ${escapeHtml(avgGamesLabel(phases.avgGames))}</p>
        </div>
      </header>
      <div class="ba-phasestrip__bars">
        <div class="ba-phasestrip__row">
          <span>This match</span>
          <div class="ba-phasestrip__track">${phaseStripSegments(rows, "percent")}</div>
        </div>
        ${hasAvg ? `
          <div class="ba-phasestrip__row">
            <span>Vale avg</span>
            <div class="ba-phasestrip__track">${phaseStripSegments(rows, "avg")}</div>
          </div>
        ` : ""}
      </div>
      <ul class="ba-phasestrip__legend">${legend}</ul>
    </article>
  `;
}

const BA_PITCH = { mx: 120, lx: 48, rx: 192, top: 14, seam: 90, amBase: 126 };
BA_PITCH.ibTop = BA_PITCH.top + 8;
BA_PITCH.seamCurve = BA_PITCH.seam - 6;

const BA_ZONE_LAYOUT = {
  IBWL: {
    d: `M8,${BA_PITCH.ibTop} Q18,${BA_PITCH.top} ${BA_PITCH.lx},${BA_PITCH.ibTop} L${BA_PITCH.lx},${BA_PITCH.seam} L8,${BA_PITCH.seam} Z`,
    cx: 28, valY: 52, name: "L", variant: "ib",
  },
  IBWR: {
    d: `M${BA_PITCH.rx},${BA_PITCH.ibTop} Q222,${BA_PITCH.top} 232,${BA_PITCH.ibTop} L232,${BA_PITCH.seam} L${BA_PITCH.rx},${BA_PITCH.seam} Z`,
    cx: 212, valY: 52, name: "R", variant: "ib",
  },
  IB: {
    d: `M${BA_PITCH.lx},${BA_PITCH.ibTop} Q${BA_PITCH.mx},${BA_PITCH.top} ${BA_PITCH.rx},${BA_PITCH.ibTop} L${BA_PITCH.rx},${BA_PITCH.seam} Q${BA_PITCH.mx},${BA_PITCH.seamCurve} ${BA_PITCH.lx},${BA_PITCH.seam} Z`,
    cx: BA_PITCH.mx, valY: 52, name: "C", variant: "ib",
  },
  WL: {
    d: `M8,${BA_PITCH.seam} L${BA_PITCH.lx},${BA_PITCH.seam} L${BA_PITCH.lx},162 L8,162 Z`,
    cx: 28, valY: 124, name: "WL", variant: "pass",
  },
  WR: {
    d: `M${BA_PITCH.rx},${BA_PITCH.seam} L232,${BA_PITCH.seam} L232,162 L${BA_PITCH.rx},162 Z`,
    cx: 212, valY: 124, name: "WR", variant: "pass",
  },
  AM: {
    d: `M${BA_PITCH.lx},${BA_PITCH.seam} Q${BA_PITCH.mx},${BA_PITCH.seamCurve} ${BA_PITCH.rx},${BA_PITCH.seam} L${BA_PITCH.rx},${BA_PITCH.amBase} Q${BA_PITCH.mx},136 ${BA_PITCH.lx},${BA_PITCH.amBase} Z`,
    cx: BA_PITCH.mx, valY: 104, name: "AM", variant: "pass",
  },
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
            <p>Touches and passes into the last line</p>
          </div>
        </header>
        <p class="ba-chart__empty">No in-behind data</p>
      </article>
    `;
  }
  const ibById = Object.fromEntries((data.ibZones || []).map((z) => [z.id, z]));
  const fromById = Object.fromEntries((data.fromZones || []).map((z) => [z.id, z]));
  const maxTouch = Math.max(1, ...(data.ibZones || []).map((z) => Number(z.value) || 0));
  const maxPass = Math.max(1, ...(data.fromZones || []).map((z) => Number(z.value) || 0));
  const zones = ["WL", "WR", "AM", "IBWL", "IBWR", "IB"].map((id) => {
    const layout = BA_ZONE_LAYOUT[id];
    const row = layout.variant === "ib" ? ibById[id] : fromById[id];
    const value = Number(row?.value) || 0;
    const colors = behindHeat(value, layout.variant === "ib" ? maxTouch : maxPass, layout.variant);
    const shown = fmtNum(value, Number.isInteger(value) ? 0 : 1);
    return `
      <g>
        <path d="${layout.d}" fill="${colors.fill}" stroke="rgba(255,255,255,.18)" stroke-width="0.6"/>
        <text x="${layout.cx}" y="${layout.valY}" text-anchor="middle" fill="${colors.text}" class="ba-behind__zval">${shown}</text>
        <text x="${layout.cx}" y="${layout.valY + 11}" text-anchor="middle" fill="${colors.text}" class="ba-behind__zname">${layout.name}</text>
      </g>
    `;
  }).join("");
  const how = (data.fromZones || []).map((row) => `
    <span class="ba-behind__how-chip">
      ${escapeHtml(row.label)} <b>${escapeHtml(fmtNum(row.value, Number.isInteger(Number(row.value)) ? 0 : 1))}</b>
    </span>
  `).join("");
  return `
    <article class="ba-chart ba-behind">
      <header class="ba-chart__head">
        <div>
          <h4>Balls in behind</h4>
          <p>Green = who received · gold = where the pass came from</p>
        </div>
        <p class="ba-chart__legend">
          ${escapeHtml(fmtNum(data.touches))} touches
          <span class="ba-chart__avg">${escapeHtml(fmtNum(data.passes))} passes in</span>
        </p>
      </header>
      <div class="ba-behind__body">
        <div class="ba-behind__pitch">
          <svg class="ba-behind__svg" viewBox="0 0 240 170" preserveAspectRatio="xMidYMid meet" role="img" aria-label="In-behind touches and pass origins">
            <rect x="6" y="6" width="228" height="158" rx="8" fill="#145a35"/>
            <rect x="6" y="6" width="228" height="158" rx="8" fill="none" stroke="rgba(255,255,255,.22)" stroke-width="0.8"/>
            ${zones}
          </svg>
          <div class="ba-behind__how">
            <p>How the passes were played</p>
            <div class="ba-behind__how-row">${how || `<span class="ba-behind__empty">No passes into in-behind</span>`}</div>
          </div>
        </div>
        <div class="ba-behind__lists">
          ${behindPlayerList("Who received", data.touchPlayers, "Nobody recorded")}
          ${behindPlayerList("Who played the pass", data.passPlayers, "Nobody recorded")}
        </div>
      </div>
    </article>
  `;
}

function playerStandouts(players) {
  const specs = [
    { key: "xg", label: "Highest expected goals", digits: 2 },
    { key: "defendersBypassed", label: "Most defenders taken out", digits: 0 },
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
        <img class="ba-star__photo" src="${escapeHtml(playerPhotoUrl(player.name))}" alt="" onerror="this.removeAttribute('src')" />
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
  const mast = { kicker, single, fixture, stats, block };
  const players = playersForView(block, single, fixture);
  const boards = (single ? PLAYER_BOARDS.filter((spec) => spec.key !== "ppg") : PLAYER_BOARDS)
    .map((spec) => playerBoardHtml(spec, players))
    .join("");
  const outcome = (single && fixture?.outcome) || "";
  const foot = single
    ? "Gold tick = Vale average · black tick = league requirement (top 7) · wing-backs 50/50 DEF and ATT"
    : "Gold tick = Vale average · black tick = league requirement (top 7) · wing-backs 50/50 DEF and ATT";

  return `
    <section class="ba-report">
      <div class="ba-report__chrome ba-export-hide">
        <div class="ba-filter" role="group" aria-label="Filter block ${block.id} to one game">${pills}</div>
        <div class="ba-report__actions">
          <button type="button" class="ba-btn" data-print-report="${block.id}">Print</button>
          <button type="button" class="ba-btn ba-btn--print" data-pdf-report="${block.id}">Export PDF</button>
        </div>
      </div>
      <p class="ba-print-hint ba-export-hide">A4 landscape · two pages</p>
      <article class="ba-sheet ba-sheet--team ${outcome ? `ba-sheet--${outcome}` : ""}" data-sheet="1">
        ${sheetMasthead({ ...mast, title: pageTitle, page: 1 })}
        <div class="ba-sheet__body">
          ${metricStrip(stats, single, fixture)}
          ${single ? phasesHtml(stats.phases) : ""}
          ${single ? `
            <div class="ba-charts">
              ${xgRaceHtml(stats.xgRace) || `<article class="ba-chart ba-race"><header class="ba-chart__head"><div><h4>Chance race</h4><p>Expected goals over time</p></div></header><p class="ba-chart__empty">No shot data</p></article>`}
              ${fieldTiltHtml(stats.fieldTilt)}
              ${behindHtml(stats.inBehind)}
            </div>
          ` : ""}
          <div class="ba-sheet__main ${single ? "ba-sheet__main--compact" : ""}">
            ${unitPanelHtml("Defenders taken out", "defendersBypassed", "Opponents removed from the play", stats, single)}
            ${unitPanelHtml("Duels won", "duelRate", "Success rate by unit", stats, single)}
          </div>
        </div>
        <footer class="ba-sheet__bar"><span>Port Vale Analysis</span><span>${escapeHtml(foot)}</span></footer>
      </article>
      <article class="ba-sheet ba-sheet--players ${outcome ? `ba-sheet--${outcome}` : ""}" data-sheet="2">
        ${sheetMasthead({ ...mast, title: "Players", page: 2 })}
        <div class="ba-sheet__body">
          ${single && players.length ? standoutsHtml(players) : ""}
          <div class="ba-players__grid ${single ? "ba-players__grid--six" : ""}">${boards}</div>
        </div>
        <footer class="ba-sheet__bar"><span>Port Vale Analysis</span><span>Live after full time</span></footer>
      </article>
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

async function exportReportPdf(blockId) {
  const root = document.getElementById(`block-${blockId}`);
  const sheets = [...(root?.querySelectorAll(".ba-sheet") || [])];
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
  document.querySelectorAll(".ba-block.is-print-target").forEach((el) => el.classList.remove("is-print-target"));
  block.classList.add("is-print-target");
  document.body.classList.add("is-printing");
  const tidy = () => {
    document.body.classList.remove("is-printing");
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
  const printBtn = event.target.closest("[data-print-report]");
  if (printBtn) {
    printReport(Number(printBtn.dataset.printReport));
    return;
  }
  const pdfBtn = event.target.closest("[data-pdf-report]");
  if (pdfBtn) {
    pdfBtn.disabled = true;
    setStatus("Building A4 landscape PDF…", "loading");
    try {
      await exportReportPdf(Number(pdfBtn.dataset.pdfReport));
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
