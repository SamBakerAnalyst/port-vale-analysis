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

function posterHtml(block) {
  const target = block.target || {};
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
          <div class="ba-aim ba-aim--${escapeHtml(medal)}">
            <p class="ba-aim__label">${escapeHtml(target.label || "SILVER • AUTOMATIC")}</p>
            <span class="ba-aim__points-print">${escapeHtml(target.points)}</span>
            <input class="ba-aim__points ba-export-hide" type="number" min="0" max="18" step="1" value="${escapeHtml(target.points)}" data-block="${block.id}" aria-label="Points target" />
            <p class="ba-aim__cs">
              <span class="ba-aim__cs-print">${escapeHtml(target.cleanSheets)}</span>
              <input class="ba-aim__cs-input ba-export-hide" type="number" min="0" max="6" step="1" value="${escapeHtml(target.cleanSheets)}" data-block="${block.id}" aria-label="Clean sheet target" />
              ${csLabel}
            </p>
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

function selectedStats(block) {
  const filterId = state.filters[block.id];
  if (!filterId || filterId === "all") return { stats: block.totals, label: "All games in this block", single: false };
  const fixture = (block.fixtures || []).find((row) => String(row.matchId) === String(filterId));
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

function benchHtml(key, stats, single) {
  const spec = state.payload?.benchmarks?.[key];
  if (!spec) return "";
  const games = spec.rate ? 1 : (single ? 1 : Math.max(Number(stats.played) || 0, 5));
  const team = spec.team == null ? null : spec.team * games;
  const top7 = spec.top7 == null ? null : spec.top7 * games;
  return `
    <div class="ba-kpi__bench">
      <span>Team avg <b>${formatBenchValue(team, spec)}</b></span>
      <span>Top 7 req <b>${formatBenchValue(top7, spec)}</b></span>
    </div>
  `;
}

function kpiCard(label, value, hint, tone, bench) {
  return `
    <article class="ba-kpi ${tone ? `ba-kpi--${tone}` : ""}">
      <p class="ba-kpi__label">${escapeHtml(label)}</p>
      <p class="ba-kpi__value">${escapeHtml(value)}</p>
      ${bench || ""}
      ${hint ? `<p class="ba-kpi__hint">${escapeHtml(hint)}</p>` : ""}
    </article>
  `;
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

function unitBenchText(metricKey, unit, single, played) {
  const spec = state.payload?.benchmarks?.units?.[unit]?.[metricKey];
  if (!spec) return { team: "—", top7: "—" };
  const games = spec.rate ? 1 : (single ? 1 : Math.max(Number(played) || 0, 5));
  const team = spec.team == null ? null : spec.team * games;
  const top7 = spec.top7 == null ? null : spec.top7 * games;
  return {
    team: formatBenchValue(team, spec),
    top7: formatBenchValue(top7, spec),
  };
}

function unitCard(title, metricKey, hint, stats, single) {
  const units = stats.units || {};
  const rows = ["DEF", "MID", "ATT"].map((unit) => {
    const row = units[unit] || {};
    const bench = unitBenchText(metricKey, unit, single, stats.played);
    const extra = unitSubText(metricKey, row);
    return `
      <tr>
        <th scope="row">${unit}</th>
        <td>
          <span class="ba-unit__val">${escapeHtml(unitValueText(metricKey, row))}</span>
          ${extra ? `<span class="ba-unit__sub">${escapeHtml(extra)}</span>` : ""}
        </td>
        <td>${escapeHtml(bench.team)}</td>
        <td>${escapeHtml(bench.top7)}</td>
      </tr>
    `;
  }).join("");
  return `
    <article class="ba-kpi ba-kpi--units">
      <p class="ba-kpi__label">${escapeHtml(title)}</p>
      <table class="ba-unit">
        <thead>
          <tr>
            <th></th>
            <th>Value</th>
            <th>Team avg</th>
            <th>Top 7 req</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="ba-kpi__hint">${escapeHtml(hint)}</p>
    </article>
  `;
}

const PLAYER_BOARDS = [
  { key: "ppg", label: "Points per game", hint: "Team pts when they played", digits: 2 },
  { key: "xg", label: "Player xG", hint: "Shot xG", digits: 2 },
  { key: "offensiveInterventions", label: "Offensive interventions", hint: "Ball wins by action", digits: 0 },
  { key: "defensiveInterventions", label: "Defensive interventions", hint: "Teammates added by ball wins", digits: 0 },
  { key: "regainsFromDefenders", label: "Regains from defenders", hint: "Removed opposition defenders", digits: 0 },
  { key: "defendersBypassed", label: "Defenders bypassed", hint: "Impect packing", digits: 0 },
  { key: "duelRate", label: "Duel rate", hint: "Won / attempted", digits: 1, rate: true, minDuels: 3 },
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
          <li class="ba-lead__row">
            <span class="ba-lead__rank">${index + 1}</span>
            <img class="ba-lead__photo" src="${escapeHtml(playerPhotoUrl(row.name))}" alt="" onerror="this.removeAttribute('src'); this.style.visibility='hidden'" />
            <span class="ba-lead__name">${escapeHtml(row.name)}</span>
            ${extra}
            <span class="ba-lead__val">${escapeHtml(formatPlayerValue(row, spec))}</span>
          </li>
        `;
      }).join("")
    : `<li class="ba-lead__empty">No player data yet</li>`;
  return `
    <article class="ba-lead">
      <p class="ba-kpi__label">${escapeHtml(spec.label)}</p>
      <ol class="ba-lead__list">${items}</ol>
      <p class="ba-kpi__hint">${escapeHtml(spec.hint)}</p>
    </article>
  `;
}

function sheetHeader({ title, kicker, label, page, single, fixture }) {
  let match = `<p class="ba-sheet__meta">${escapeHtml(label)}</p>`;
  if (single && fixture) {
    const badge = fixture.badgeUrl
      ? `<img class="ba-sheet__badge" src="${escapeHtml(fixture.badgeUrl)}" alt="" crossorigin="anonymous" />`
      : "";
    const ha = fixture.isHome == null ? "" : (fixture.isHome ? "Home" : "Away");
    const score = fixture.played ? scoreLine(fixture) : (fixture.dateLabel || "Not played");
    match = `
      <div class="ba-sheet__match">
        ${badge}
        <div>
          <p class="ba-sheet__opp">${escapeHtml(fixture.opponentName || "TBC")}</p>
          <p class="ba-sheet__meta">${escapeHtml([ha, score].filter(Boolean).join(" · "))}</p>
        </div>
      </div>
    `;
  }
  return `
    <header class="ba-sheet__head">
      <div class="ba-sheet__brand">
        <img class="ba-sheet__crest" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" />
        <div>
          <p class="ba-sheet__kicker">${escapeHtml(kicker)}</p>
          <h3 class="ba-sheet__title">${escapeHtml(title)}</h3>
        </div>
      </div>
      ${match}
      <p class="ba-sheet__page">${page} / 2</p>
    </header>
  `;
}

function dashHtml(block) {
  const { stats, label, single, fixture } = selectedStats(block);
  const filterId = state.filters[block.id] || "all";
  const scheduled = (block.fixtures || []).filter((row) => row.matchId).length;
  const pills = [`<button type="button" class="ba-filter__btn ${filterId === "all" ? "is-active" : ""}" data-filter="all" data-block="${block.id}">All games</button>`]
    .concat(
      (block.fixtures || [])
        .filter((row) => row.matchId)
        .map((row) => {
          const active = String(filterId) === String(row.matchId);
          return `<button type="button" class="ba-filter__btn ${active ? "is-active" : ""}" data-filter="${row.matchId}" data-block="${block.id}">${escapeHtml(row.slot)}. ${escapeHtml(shortOpponent(row.opponentName))}</button>`;
        })
    )
    .join("");

  const target = block.target || {};
  const pointsHint = single
    ? (stats.played ? "This match" : "Kick-off pending")
    : `Target ${target.points} · ${stats.played || 0} played`;
  const csHint = single
    ? (stats.cleanSheets ? "Clean sheet" : stats.played ? "Conceded" : "—")
    : `Target ${target.cleanSheets}`;

  const cards = [
    kpiCard("Points", fmtNum(stats.points), pointsHint, kpiTone("points", stats, target, single, scheduled)),
    kpiCard("Goals", fmtNum(stats.goals), single ? "For" : "Scored in block"),
    kpiCard("Goals against", fmtNum(stats.goalsAgainst), single ? "Against" : "Conceded in block", "", benchHtml("goalsAgainst", stats, single)),
    kpiCard("Clean sheets", fmtNum(stats.cleanSheets), csHint, kpiTone("cleanSheets", stats, target, single, scheduled), benchHtml("cleanSheets", stats, single)),
    kpiCard("Offensive interventions", fmtNum(stats.offensiveInterventions), "Ball wins by action", "", benchHtml("offensiveInterventions", stats, single)),
    kpiCard("Ball wins vs defenders", fmtNum(stats.ballWinsFromOppDefenders), "Removed opposition defenders", "", benchHtml("ballWinsFromOppDefenders", stats, single)),
    kpiCard("Team xG", fmtNum(stats.xg, 2), "Shot xG", "", benchHtml("xg", stats, single)),
  ].join("");
  const unitCards = `
    <div class="ba-unit-pair">
      ${unitCard("Defenders bypassed", "defendersBypassed", "Impect packing · WB 50/50 DEF and ATT", stats, single)}
      ${unitCard("Duel rate", "duelRate", "Won / attempted · WB 50/50 DEF and ATT", stats, single)}
    </div>
  `;
  const payload = state.payload || {};
  const kicker = `Block ${block.id} of 9 · ${payload.competition || "League Two"} ${payload.season || ""}`.trim();
  const pageTitle = single ? "Match Report" : "Block Report";
  const header = { kicker, label, single, fixture };
  const boards = PLAYER_BOARDS.map((spec) => playerBoardHtml(spec, playersForView(block, single, fixture))).join("");

  return `
    <section class="ba-report">
      <div class="ba-report__chrome ba-export-hide">
        <div class="ba-filter" role="group" aria-label="Filter block ${block.id} to one game">${pills}</div>
        <button type="button" class="ba-btn" data-print-report="${block.id}">Print 2-page report</button>
      </div>
      <article class="ba-sheet" data-sheet="1">
        ${sheetHeader({ ...header, title: pageTitle, page: 1 })}
        <div class="ba-kpis">${cards}${unitCards}</div>
      </article>
      <article class="ba-sheet" data-sheet="2">
        ${sheetHeader({ ...header, title: "Players Report", page: 2 })}
        <div class="ba-players__grid">${boards}</div>
        <p class="ba-sheet__foot">Top 5 outfield · live after full time</p>
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
      if (!state.filters[block.id]) state.filters[block.id] = "all";
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
  window.print();
  setTimeout(tidy, 1500);
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
