const ALLOWED_SEASONS = ["26/27", "25/26"];

const state = {
  meta: null,
  fixtures: [],
  report: null,
  season: "",
  matchId: "",
  scope: "match",
  view: "summary",
  loading: false,
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  matchSelect: document.getElementById("matchSelect"),
  matchSelectGroup: document.getElementById("matchSelectGroup"),
  pageSubtitle: document.getElementById("pageSubtitle"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportPdfBtn: document.getElementById("exportPdfBtn"),
  matchHeader: document.getElementById("matchHeader"),
  trendsPanel: document.getElementById("trendsPanel"),
  summaryView: document.getElementById("summaryView"),
  shotsView: document.getElementById("shotsView"),
  playersView: document.getElementById("playersView"),
  xgCreatedPanel: document.getElementById("xgCreatedPanel"),
  xgAgainstPanel: document.getElementById("xgAgainstPanel"),
  gameStatePanel: document.getElementById("gameStatePanel"),
  periodPanel: document.getElementById("periodPanel"),
  shotTable: document.getElementById("shotTable"),
  valePlayersPanel: document.getElementById("valePlayersPanel"),
  oppPlayersPanel: document.getElementById("oppPlayersPanel"),
};

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `xca-status xca-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

async function fetchJson(url, options = {}) {
  const bustedUrl = url.includes("?") ? `${url}&_=${Date.now()}` : `${url}?_=${Date.now()}`;
  const res = await fetch(bustedUrl, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function filteredSeasons() {
  const allowed = new Set(ALLOWED_SEASONS);
  return (state.meta?.seasons || []).filter((row) => allowed.has(row.value));
}

function renderSeasonToggle() {
  const seasons = filteredSeasons();
  els.seasonToggle.innerHTML = seasons
    .map(
      (row) => `
      <button
        type="button"
        class="xca-season-btn ${row.value === state.season ? "xca-season-btn--active" : ""}"
        data-season="${row.value}"
        title="${row.hasData ? "" : "No score data yet"}"
      >${row.label || row.value}${row.hasData ? "" : " *"}</button>`
    )
    .join("");

  els.seasonToggle.querySelectorAll("[data-season]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.season = btn.dataset.season;
      state.matchId = "";
      renderSeasonToggle();
      await loadFixtures();
      await loadReport();
    });
  });
}

function usesZeroBasedMatchDays(fixtures = state.fixtures) {
  return fixtures.some((row) => Number(row.matchDay) === 0);
}

function formatMatchDay(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "?";
  return usesZeroBasedMatchDays() ? n + 1 : n;
}

function renderMatchSelect() {
  const options = [];
  for (const fixture of state.fixtures) {
    const label = `MD${formatMatchDay(fixture.matchDay)} · ${fixture.opponent?.name || "Opponent"} (${fixture.venue})${fixture.score ? ` · ${fixture.score}` : ""}`;
    options.push(`<option value="${fixture.matchId}" ${String(fixture.matchId) === String(state.matchId) ? "selected" : ""}>${label}</option>`);
  }
  els.matchSelect.innerHTML = options.join("") || '<option value="">No completed matches</option>';
  if (els.matchSelectGroup) {
    els.matchSelectGroup.classList.toggle("hidden", state.scope !== "match");
  }
}

function renderScopeToggle() {
  document.querySelectorAll(".xca-scope-btn").forEach((btn) => {
    btn.classList.toggle("xca-scope-btn--active", btn.dataset.scope === state.scope);
  });
  if (els.matchSelectGroup) {
    els.matchSelectGroup.classList.toggle("hidden", state.scope !== "match");
  }
}

function renderBucketPanel(container, title, summary) {
  if (!summary) {
    container.innerHTML = "";
    return;
  }

  const rows = (summary.buckets || [])
    .map(
      (row) => `
      <tr>
        <td><span class="xca-rating-pill" style="background:${row.color}">${row.label}</span></td>
        <td>${row.goals}</td>
        <td>${row.count}</td>
        <td>${row.pct}%</td>
        <td>${row.cumulativeXg.toFixed(3)}</td>
      </tr>`
    )
    .join("");

  const grouped = summary.grouped || {};
  const totals = summary.totals || {};

  container.innerHTML = `
    <h2 class="xca-panel-title">${title}</h2>
    <table class="xca-bucket-table">
      <thead>
        <tr>
          <th>Chance rating</th>
          <th>Goals</th>
          <th>Count</th>
          <th>%</th>
          <th>Cumulative xG</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
        <tr class="xca-grouped-row">
          <td>${grouped.highQuality?.label || "Excellent / Very Good"}</td>
          <td>${grouped.highQuality?.goals ?? 0}</td>
          <td>${grouped.highQuality?.count ?? 0}</td>
          <td>—</td>
          <td>${(grouped.highQuality?.cumulativeXg ?? 0).toFixed(3)}</td>
        </tr>
        <tr class="xca-grouped-row">
          <td>${grouped.lowQuality?.label || "Poor / Very Poor"}</td>
          <td>${grouped.lowQuality?.goals ?? 0}</td>
          <td>${grouped.lowQuality?.count ?? 0}</td>
          <td>—</td>
          <td>${(grouped.lowQuality?.cumulativeXg ?? 0).toFixed(3)}</td>
        </tr>
      </tbody>
      <tfoot>
        <tr>
          <td>Total</td>
          <td>${totals.goals ?? 0}</td>
          <td>${totals.shots ?? 0}</td>
          <td>100%</td>
          <td>${(totals.cumulativeXg ?? 0).toFixed(3)}</td>
        </tr>
      </tfoot>
    </table>`;
}

function gameStatePill(stateId, label) {
  return `<span class="xca-state-pill xca-state-pill--${stateId}">${label}</span>`;
}

function renderGameStatePanel() {
  const report = state.report;
  if (!report) return;

  const valeRows = (report.gameStateBreakdown?.vale || [])
    .map(
      (row) => `
      <tr>
        <td>${gameStatePill(row.id, row.label)}</td>
        <td>${row.shots}</td>
        <td>${row.goals}</td>
        <td>${row.xg.toFixed(3)}</td>
      </tr>`
    )
    .join("");

  els.gameStatePanel.innerHTML = `
    <h2 class="xca-panel-title">Game state when shooting (Vale)</h2>
    <table class="xca-mini-table">
      <thead>
        <tr><th>State</th><th>Shots</th><th>Goals</th><th>xG</th></tr>
      </thead>
      <tbody>${valeRows || '<tr><td colspan="4">No shots</td></tr>'}</tbody>
    </table>`;
}

function renderPeriodPanel() {
  const report = state.report;
  if (!report) return;

  const halves = (report.periodBreakdown?.halves || [])
    .map(
      (row) => `
      <tr>
        <td>${row.label}</td>
        <td>${row.valeShots}</td>
        <td>${row.valeXg.toFixed(3)}</td>
        <td>${row.oppShots}</td>
        <td>${row.oppXg.toFixed(3)}</td>
      </tr>`
    )
    .join("");

  const manpower = (report.periodBreakdown?.manpower || [])
    .map(
      (row) => `
      <tr>
        <td>${row.label}</td>
        <td>${row.valeShots}</td>
        <td>${row.valeXg.toFixed(3)}</td>
        <td>${row.oppShots}</td>
        <td>${row.oppXg.toFixed(3)}</td>
      </tr>`
    )
    .join("");

  els.periodPanel.innerHTML = `
    <h2 class="xca-panel-title">Half &amp; manpower splits</h2>
    <h3 class="xca-panel-title" style="font-size:1rem;margin-top:0">By half</h3>
    <table class="xca-mini-table">
      <thead>
        <tr><th>Period</th><th>Vale shots</th><th>Vale xG</th><th>Opp shots</th><th>Opp xG</th></tr>
      </thead>
      <tbody>${halves}</tbody>
    </table>
    <h3 class="xca-panel-title" style="font-size:1rem;margin-top:1rem">By manpower</h3>
    <table class="xca-mini-table">
      <thead>
        <tr><th>State</th><th>Vale shots</th><th>Vale xG</th><th>Opp shots</th><th>Opp xG</th></tr>
      </thead>
      <tbody>${manpower}</tbody>
    </table>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function xgBarWidth(value, maxValue) {
  const max = Math.max(maxValue, 0.01);
  return Math.max(8, Math.round((Number(value) / max) * 100));
}

function renderMatchHeader() {
  const report = state.report;
  if (!report) {
    els.matchHeader.classList.add("hidden");
    return;
  }

  if (report.scope === "match" && report.matches?.length) {
    const match = report.matches[0];
    const valeGoals = match.valeGoals ?? "—";
    const oppGoals = match.oppGoals ?? "—";
    const valeXg = Number(match.valeXg || 0);
    const oppXg = Number(match.oppXg || 0);
    const maxXg = Math.max(valeXg, oppXg, 0.01);
    const valeWon = Number.isFinite(match.valeGoals) && Number.isFinite(match.oppGoals) && match.valeGoals > match.oppGoals;
    const oppWon = Number.isFinite(match.valeGoals) && Number.isFinite(match.oppGoals) && match.oppGoals > match.valeGoals;
    const opponentCrest = match.opponent?.imageUrl
      ? `<img class="xca-match-hero__crest" src="${escapeHtml(match.opponent.imageUrl)}" alt="" />`
      : `<div class="xca-match-hero__crest xca-match-hero__crest--placeholder" aria-hidden="true">${escapeHtml((match.opponent?.name || "Opp").slice(0, 2))}</div>`;

    els.matchHeader.classList.remove("hidden");
    els.matchHeader.innerHTML = `
      <div class="xca-match-hero">
        <div class="xca-match-hero__top">
          <div class="xca-match-hero__chips">
            <span class="xca-match-hero__chip xca-match-hero__chip--accent">MD${formatMatchDay(match.matchDay)}</span>
            <span class="xca-match-hero__chip">${escapeHtml(match.dateLabel || "")}</span>
            <span class="xca-match-hero__chip">${escapeHtml(match.venue || "")}</span>
          </div>
          <div class="xca-match-hero__comp">${escapeHtml(report.competition || "")} ${escapeHtml(report.season || "")}</div>
        </div>

        <div class="xca-match-hero__scoreboard">
          <div class="xca-match-hero__team xca-match-hero__team--vale ${valeWon ? "xca-match-hero__team--winner" : ""}">
            <img class="xca-match-hero__crest" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" />
            <div class="xca-match-hero__team-name">Port Vale</div>
            <div class="xca-match-hero__goals">${escapeHtml(valeGoals)}</div>
          </div>

          <div class="xca-match-hero__versus" aria-hidden="true">–</div>

          <div class="xca-match-hero__team xca-match-hero__team--opp ${oppWon ? "xca-match-hero__team--winner" : ""}">
            ${opponentCrest}
            <div class="xca-match-hero__team-name">${escapeHtml(match.opponent?.name || "Opponent")}</div>
            <div class="xca-match-hero__goals">${escapeHtml(oppGoals)}</div>
          </div>
        </div>

        <div class="xca-match-hero__xg">
          <div class="xca-match-hero__xg-row">
            <div class="xca-match-hero__xg-label">Vale xG</div>
            <div class="xca-match-hero__xg-track">
              <div class="xca-match-hero__xg-fill xca-match-hero__xg-fill--vale" style="width:${xgBarWidth(valeXg, maxXg)}%"></div>
            </div>
            <div class="xca-match-hero__xg-value">${valeXg.toFixed(3)}</div>
          </div>
          <div class="xca-match-hero__xg-row">
            <div class="xca-match-hero__xg-label">Opp xG</div>
            <div class="xca-match-hero__xg-track">
              <div class="xca-match-hero__xg-fill xca-match-hero__xg-fill--opp" style="width:${xgBarWidth(oppXg, maxXg)}%"></div>
            </div>
            <div class="xca-match-hero__xg-value">${oppXg.toFixed(3)}</div>
          </div>
        </div>

        <div class="xca-match-hero__footer">
          <span><strong>${match.valeShots ?? 0}</strong> Vale shots</span>
          <span><strong>${match.shotCount ?? 0}</strong> total shots</span>
          <span><strong>${match.oppShots ?? 0}</strong> Opp shots</span>
        </div>
      </div>`;
    return;
  }

  const averages = report.averages || {};
  els.matchHeader.classList.remove("hidden");
  els.matchHeader.innerHTML = `
    <div class="xca-match-hero xca-match-hero--multi">
      <div class="xca-match-hero__top">
        <div class="xca-match-hero__chips">
          <span class="xca-match-hero__chip xca-match-hero__chip--accent">${escapeHtml(report.scopeLabel || "Multi-match")}</span>
          <span class="xca-match-hero__chip">${averages.games || report.matchCount || 0} games</span>
        </div>
        <div class="xca-match-hero__comp">${escapeHtml(report.competition || "")} ${escapeHtml(report.season || "")}</div>
      </div>
      <div class="xca-avg-grid">
        <div class="xca-avg-card">
          <div class="xca-avg-card__label">xG for / game</div>
          <div class="xca-avg-card__value">${Number(averages.valeXg || 0).toFixed(3)}</div>
        </div>
        <div class="xca-avg-card">
          <div class="xca-avg-card__label">xG against / game</div>
          <div class="xca-avg-card__value">${Number(averages.oppXg || 0).toFixed(3)}</div>
        </div>
        <div class="xca-avg-card">
          <div class="xca-avg-card__label">xG difference</div>
          <div class="xca-avg-card__value">${Number(averages.xgDiff || 0).toFixed(3)}</div>
        </div>
        <div class="xca-avg-card">
          <div class="xca-avg-card__label">HQ shot share</div>
          <div class="xca-avg-card__value">${Number(averages.valeHighQualityPct || 0).toFixed(1)}%</div>
        </div>
      </div>
    </div>`;
}

function renderTrendsPanel() {
  const report = state.report;
  if (!els.trendsPanel) return;
  if (!report || report.scope === "match" || !(report.trends?.insights || []).length) {
    els.trendsPanel.classList.add("hidden");
    els.trendsPanel.innerHTML = "";
    return;
  }

  const trends = report.trends || {};
  const insights = (trends.insights || [])
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");
  const metrics = (trends.metrics || [])
    .map((row) => {
      const dirClass = row.direction === "up"
        ? "xca-trend--up"
        : row.direction === "down"
          ? "xca-trend--down"
          : "xca-trend--flat";
      const kind = String(row.id || "").includes("Pct") ? "pct" : "num";
      const fmt = (value) => {
        if (value == null) return "—";
        return kind === "pct" ? `${Number(value).toFixed(1)}%` : Number(value).toFixed(3);
      };
      return `
        <div class="xca-trend-metric ${dirClass}">
          <div class="xca-trend-metric__label">${escapeHtml(row.label)}</div>
          <div class="xca-trend-metric__values">
            <span>${fmt(row.earlier)}</span>
            <span aria-hidden="true">→</span>
            <span>${fmt(row.recent)}</span>
          </div>
          <div class="xca-trend-metric__dir">${escapeHtml((row.direction || "flat").toUpperCase())}</div>
        </div>`;
    })
    .join("");

  const matchRows = (report.matchTrends || [])
    .map((row) => `
      <tr>
        <td>MD${formatMatchDay(row.matchDay)}</td>
        <td class="col-left">${escapeHtml(row.opponent?.name || "")}</td>
        <td>${escapeHtml(row.score || "—")}</td>
        <td>${Number(row.valeXg || 0).toFixed(3)}</td>
        <td>${Number(row.oppXg || 0).toFixed(3)}</td>
        <td>${Number(row.valeHighQualityPct || 0).toFixed(1)}%</td>
      </tr>`)
    .join("");

  els.trendsPanel.classList.remove("hidden");
  els.trendsPanel.innerHTML = `
    <div class="xca-trends">
      <div class="xca-trends__copy">
        <h2 class="xca-panel-title">${report.scope === "last6" ? "Recent form & trends" : "Season trends"}</h2>
        <ul class="xca-trends__insights">${insights}</ul>
      </div>
      <div class="xca-trends__metrics">${metrics}</div>
      <div class="xca-trends__table-wrap">
        <table class="xca-mini-table">
          <thead>
            <tr>
              <th>MD</th>
              <th class="col-left">Opponent</th>
              <th>Score</th>
              <th>Vale xG</th>
              <th>Opp xG</th>
              <th>HQ%</th>
            </tr>
          </thead>
          <tbody>${matchRows || '<tr><td colspan="6">No matches</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function renderShotTable() {
  const report = state.report;
  if (!report) return;

  const showMatchCols = report.scope !== "match";

  const thead = showMatchCols
    ? `
    <tr>
      <th class="col-left">MD</th>
      <th class="col-left">Opponent</th>
      <th>State</th>
      <th class="col-left">Player</th>
      <th>Team</th>
      <th>Min</th>
      <th>Sec</th>
      <th>xG</th>
      <th>#</th>
      <th>Rating</th>
      <th>Box</th>
      <th>On tgt</th>
      <th>Outcome</th>
      <th>Cum xG</th>
      <th>Half</th>
      <th>MP</th>
    </tr>`
    : `
    <tr>
      <th>State</th>
      <th class="col-left">Player</th>
      <th>Team</th>
      <th>Min</th>
      <th>Sec</th>
      <th>xG</th>
      <th>#</th>
      <th>Rating</th>
      <th>Box</th>
      <th>On tgt</th>
      <th>Outcome</th>
      <th>Cum xG</th>
      <th>Half</th>
      <th>MP</th>
    </tr>`;

  const colCount = showMatchCols ? 16 : 14;
  const timeline = [];

  for (const dismissal of report.dismissals || []) {
    timeline.push({ kind: "dismissal", seconds: dismissal.seconds, dismissal });
  }
  for (const shot of report.shots || []) {
    timeline.push({ kind: "shot", seconds: shot.seconds, shot });
  }
  timeline.sort((a, b) => a.seconds - b.seconds);

  const rows = [];
  for (const item of timeline) {
    if (item.kind === "dismissal") {
      const d = item.dismissal;
      rows.push(`
        <tr class="xca-dismissal-marker">
          <td colspan="${colCount}">${d.playerName.toUpperCase()} RED · ${d.minute}'</td>
        </tr>`);
      continue;
    }

    const shot = item.shot;
    const teamClass = shot.team === "vale" ? "xca-team-pill--vale" : "xca-team-pill--opp";
    const outcomeClass = shot.outcome === "goal" ? "xca-outcome--goal" : "xca-outcome--miss";
    const matchCols = showMatchCols
      ? `<td class="col-left">MD${formatMatchDay(shot.matchDay)}</td><td class="col-left">${shot.opponentName || ""}</td>`
      : "";

    rows.push(`
      <tr>
        ${matchCols}
        <td>${gameStatePill(shot.gameState, shot.gameStateLabel)}</td>
        <td class="col-left">${shot.playerName}</td>
        <td><span class="xca-team-pill ${teamClass}">${shot.team === "vale" ? "VALE" : "OPP"}</span></td>
        <td>${shot.minute}</td>
        <td>${String(shot.second).padStart(2, "0")}</td>
        <td>${shot.xgDisplay}</td>
        <td>${shot.shotNumber}</td>
        <td><span class="xca-rating-pill" style="background:${shot.chanceRating.color}">${shot.chanceRating.label}</span></td>
        <td>${shot.inBoxLabel}</td>
        <td>${shot.onTargetLabel}</td>
        <td class="${outcomeClass}">${shot.outcomeLabel}</td>
        <td>${shot.cumulativeXg.toFixed(3)}</td>
        <td>${shot.halfLabel}</td>
        <td>${shot.manpower}</td>
      </tr>`);
  }

  els.shotTable.querySelector("thead").innerHTML = thead;
  els.shotTable.querySelector("tbody").innerHTML = rows.join("") || `<tr><td colspan="${colCount}">No shots recorded</td></tr>`;
}

function pluralShots(count) {
  const n = Number(count) || 0;
  return `${n} shot${n === 1 ? "" : "s"}`;
}

const CHANCE_TAG_SPECS = [
  { id: "excellent", label: "Excellent", className: "xca-player-tag--excellent" },
  { id: "very_good", label: "Very Good", className: "xca-player-tag--very-good" },
  { id: "ok", label: "OK", className: "xca-player-tag--ok" },
  { id: "poor", label: "Poor", className: "xca-player-tag--poor" },
  { id: "very_poor", label: "Very Poor", className: "xca-player-tag--very-poor" },
];

function chanceCount(row, id) {
  return Number(row?.chanceCounts?.[id] || 0);
}

function renderPlayerPanel(container, title, players, variant = "vale") {
  const list = players || [];
  const accentClass = variant === "vale" ? "xca-player-panel--vale" : "xca-player-panel--opp";

  if (!list.length) {
    container.innerHTML = `
      <div class="xca-player-panel ${accentClass}">
        <h2 class="xca-panel-title">${escapeHtml(title)}</h2>
        <p class="xca-player-panel__empty">No shots recorded</p>
      </div>`;
    return;
  }

  const maxXg = Math.max(...list.map((row) => Number(row.xg) || 0), 0.01);
  const totalXg = list.reduce((sum, row) => sum + (Number(row.xg) || 0), 0);
  const totalShots = list.reduce((sum, row) => sum + (Number(row.shots) || 0), 0);
  const totalGoals = list.reduce((sum, row) => sum + (Number(row.goals) || 0), 0);
  const totalExcellent = list.reduce((sum, row) => sum + chanceCount(row, "excellent"), 0);
  const totalVeryGood = list.reduce((sum, row) => sum + chanceCount(row, "very_good"), 0);

  const rows = list
    .map((row, index) => {
      const barWidth = Math.max(10, Math.round(((Number(row.xg) || 0) / maxXg) * 100));
      const goalsBadge = row.goals
        ? `<span class="xca-player-card__goal">${row.goals} goal${row.goals === 1 ? "" : "s"}</span>`
        : "";
      const tags = CHANCE_TAG_SPECS.map(
        (spec) =>
          `<span class="xca-player-tag ${spec.className}">${chanceCount(row, spec.id)} ${spec.label}</span>`
      ).join("");

      return `
        <article class="xca-player-card">
          <div class="xca-player-card__head">
            <div class="xca-player-card__identity">
              <span class="xca-player-card__rank">#${index + 1}</span>
              <div>
                <div class="xca-player-card__name">${escapeHtml(row.playerName)}</div>
                <div class="xca-player-card__sub">
                  ${pluralShots(row.shots)} · ${Number(row.avgXg || 0).toFixed(3)} avg xG
                  ${goalsBadge}
                </div>
              </div>
            </div>
            <div class="xca-player-card__xg">${Number(row.xg || 0).toFixed(3)}</div>
          </div>
          <div class="xca-player-card__bar" aria-hidden="true">
            <div class="xca-player-card__bar-fill" style="width:${barWidth}%"></div>
          </div>
          <div class="xca-player-card__tags">${tags}</div>
        </article>`;
    })
    .join("");

  container.innerHTML = `
    <div class="xca-player-panel ${accentClass}">
      <div class="xca-player-panel__header">
        <h2 class="xca-panel-title">${escapeHtml(title)}</h2>
        <div class="xca-player-panel__summary">
          <span><strong>${totalShots}</strong> shots</span>
          <span><strong>${totalXg.toFixed(3)}</strong> xG</span>
          <span><strong>${totalGoals}</strong> goals</span>
          <span><strong>${totalExcellent + totalVeryGood}</strong> Exc/VG</span>
        </div>
      </div>
      <div class="xca-player-panel__list">${rows}</div>
    </div>`;
}

function renderPlayersView() {
  const report = state.report;
  if (!report) return;
  renderPlayerPanel(els.valePlayersPanel, "Vale — shot quality by player", report.playerBreakdown?.vale, "vale");
  renderPlayerPanel(els.oppPlayersPanel, "Opposition — shot quality by player", report.playerBreakdown?.opp, "opp");
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".xca-view-btn").forEach((btn) => {
    btn.classList.toggle("xca-view-btn--active", btn.dataset.view === view);
  });
  els.summaryView.classList.toggle("hidden", view !== "summary");
  els.shotsView.classList.toggle("hidden", view !== "shots");
  els.playersView.classList.toggle("hidden", view !== "players");
}

function renderAll() {
  const report = state.report;
  if (!report) return;

  const scopeText = report.scope === "match"
    ? `Latest / selected match · ${report.scopeLabel}`
    : report.scope === "last6"
      ? `Last 6 game averages · ${report.matchCount} matches`
      : `Full season · ${report.matchCount} matches`;
  els.pageSubtitle.textContent = `${report.competition} ${report.season} · ${scopeText}`;

  renderMatchHeader();
  renderTrendsPanel();
  renderBucketPanel(els.xgCreatedPanel, "xG Created (Vale)", report.xgCreated);
  renderBucketPanel(els.xgAgainstPanel, "xG Against (Opposition)", report.xgAgainst);
  renderGameStatePanel();
  renderPeriodPanel();
  renderShotTable();
  renderPlayersView();

  els.statusBar.textContent = `Updated ${new Date(report.updatedAt).toLocaleString("en-GB")} · ${report.shots?.length || 0} shots`;
}

async function loadFixtures() {
  const data = await fetchJson(`/api/xg-chance-analysis/fixtures?season=${encodeURIComponent(state.season)}`);
  state.fixtures = data.fixtures || [];
  const validIds = new Set(
    state.fixtures
      .map((row) => String(row.matchId))
      .filter((id) => id && id !== "0")
  );
  if (!state.matchId || !validIds.has(String(state.matchId))) {
    state.matchId = data.defaultMatchId ? String(data.defaultMatchId) : "";
  }
  if (!state.matchId && state.fixtures.length) {
    const latest = [...state.fixtures].reverse().find((row) => row.matchId && String(row.matchId) !== "0");
    if (latest) state.matchId = String(latest.matchId);
  }
  renderMatchSelect();
  renderScopeToggle();
}

function selectedScopeLabel() {
  if (state.scope === "last6") return "last 6 games";
  if (state.scope === "season") return "full season";
  const fixture = state.fixtures.find((row) => String(row.matchId) === String(state.matchId));
  if (!fixture) return "selected match";
  return `MD${formatMatchDay(fixture.matchDay)} vs ${fixture.opponent?.name || "Opponent"}`;
}

async function loadReport() {
  if (state.loading) return;
  state.loading = true;
  const scopeLabel = selectedScopeLabel();
  setStatus(`Loading shot analysis for ${scopeLabel}…`, "loading");
  els.statusBar.textContent = `Loading ${scopeLabel}…`;
  try {
    const params = new URLSearchParams({ season: state.season, scope: state.scope });
    if (state.scope === "match" && state.matchId) {
      params.set("matchId", state.matchId);
    }
    state.report = await fetchJson(`/api/xg-chance-analysis/report?${params}`);
    setStatus("");
    renderAll();
  } catch (err) {
    setStatus(err.message || "Failed to load report", "error");
    els.statusBar.textContent = "Error loading data";
  } finally {
    state.loading = false;
  }
}

async function exportPdf() {
  if (!state.season) {
    els.statusBar.textContent = "Pick a season first.";
    return;
  }
  const scopeLabels = {
    match: "latest match",
    last6: "last 6 games",
    season: "full season",
  };
  const scopeLabel = scopeLabels[state.scope] || "selected scope";
  if (els.exportPdfBtn) els.exportPdfBtn.disabled = true;
  setStatus(`Building PDF — ${scopeLabel}…`, "loading");
  els.statusBar.textContent = `Exporting ${scopeLabel} PDF…`;
  try {
    const params = new URLSearchParams({
      season: state.season,
      scope: state.scope,
      _: String(Date.now()),
    });
    if (state.scope === "match" && state.matchId) {
      params.set("matchId", state.matchId);
    }
    const res = await fetch(`/api/xg-chance-analysis/export-pdf?${params}`, { cache: "no-store" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const detail = data.detail;
      const message = Array.isArray(detail)
        ? detail.map((row) => row.msg || JSON.stringify(row)).join("; ")
        : (detail || `Export failed (${res.status})`);
      throw new Error(message);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] || `xg-chance-analysis-${state.season.replace("/", "-")}-${state.scope}.pdf`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("");
    els.statusBar.textContent = `${scopeLabel} PDF downloaded.`;
  } catch (err) {
    setStatus(err.message || "PDF export failed", "error");
    els.statusBar.textContent = "PDF export failed";
  } finally {
    if (els.exportPdfBtn) els.exportPdfBtn.disabled = false;
  }
}

async function init() {
  els.statusBar.textContent = "Initialising…";
  try {
    state.meta = await fetchJson("/api/xg-chance-analysis/meta");
    const seasons = filteredSeasons();
    const withData = seasons.find((row) => row.hasData);
    state.season = ALLOWED_SEASONS.find((s) => seasons.some((row) => row.value === s && row.hasData))
      || state.meta.defaultSeason
      || withData?.value
      || ALLOWED_SEASONS[0]
      || "";
    renderSeasonToggle();
    renderScopeToggle();
    await loadFixtures();
    await loadReport();
  } catch (err) {
    setStatus(err.message || "Failed to initialise", "error");
    els.statusBar.textContent = "Initialisation failed";
  }
}

els.matchSelect.addEventListener("change", async () => {
  state.matchId = els.matchSelect.value;
  state.scope = "match";
  renderScopeToggle();
  await loadReport();
});

els.refreshBtn.addEventListener("click", async () => {
  await loadFixtures();
  await loadReport();
});

els.exportPdfBtn?.addEventListener("click", () => exportPdf());

document.querySelectorAll(".xca-view-btn").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

document.querySelectorAll(".xca-scope-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    state.scope = btn.dataset.scope || "match";
    renderScopeToggle();
    await loadReport();
  });
});

init();
