const ALLOWED_SEASONS = ["26/27", "25/26"];
const FETCH_TIMEOUT_MS = 90000;

const state = {
  meta: null,
  fixtures: [],
  report: null,
  season: "",
  matchId: "",
  scope: "match",
  view: "summary",
  excludePenalties: false,
  loading: false,
  loadToken: 0,
  abort: null,
  forceRefresh: false,
  league: null,
  leagueSeason: "",
  leagueSide: "created",
  leagueMode: "total",
  leagueSort: { key: "highQuality", dir: "desc" },
  leaguePollTimer: null,
  leagueToken: 0,
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
  penaltiesBtn: document.getElementById("penaltiesBtn"),
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
  scopeGroup: document.getElementById("scopeGroup"),
  leagueView: document.getElementById("leagueView"),
  leaguePanel: document.getElementById("leaguePanel"),
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
  const externalSignal = options.signal || null;
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? FETCH_TIMEOUT_MS;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  try {
    const { signal: _ignore, timeoutMs: _t, ...rest } = options;
    const res = await fetch(bustedUrl, {
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
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        throw new Error("Server returned a non-JSON response. Is the hub running?");
      }
    }
    if (!res.ok) {
      const detail = data.detail;
      const message = Array.isArray(detail)
        ? detail.map((row) => row.msg || JSON.stringify(row)).join("; ")
        : (detail || `Request failed (${res.status})`);
      throw new Error(message);
    }
    return data;
  } catch (err) {
    if (err?.name === "AbortError") {
      if (timedOut) {
        const timeoutErr = new Error("Request timed out. Hit Refresh to try again.");
        timeoutErr.code = "TIMEOUT";
        throw timeoutErr;
      }
      const abortErr = new Error("Request cancelled");
      abortErr.code = "ABORTED";
      throw abortErr;
    }
    throw err;
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
  }
}

function beginLoad() {
  if (state.abort) {
    try {
      state.abort.abort();
    } catch {
      /* ignore */
    }
  }
  state.abort = new AbortController();
  state.loadToken += 1;
  state.loading = true;
  return { token: state.loadToken, signal: state.abort.signal };
}

function endLoad(token) {
  if (token === state.loadToken) {
    state.loading = false;
  }
}

function showLoadingPanels(message) {
  const html = `<p class="xca-empty">${escapeHtml(message)}</p>`;
  if (els.xgCreatedPanel) els.xgCreatedPanel.innerHTML = html;
  if (els.xgAgainstPanel) els.xgAgainstPanel.innerHTML = html;
  if (els.gameStatePanel) els.gameStatePanel.innerHTML = html;
  if (els.periodPanel) els.periodPanel.innerHTML = html;
  if (els.matchHeader) {
    els.matchHeader.classList.remove("hidden");
    els.matchHeader.innerHTML = `<p class="xca-empty">${escapeHtml(message)}</p>`;
  }
  applyViewChrome();
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
      if (state.view === "league") loadLeague();
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
    els.matchSelectGroup.classList.toggle("hidden", state.scope !== "match" || state.view === "league");
  }
}

function renderScopeToggle() {
  document.querySelectorAll(".xca-scope-btn").forEach((btn) => {
    btn.classList.toggle("xca-scope-btn--active", btn.dataset.scope === state.scope);
  });
  if (els.matchSelectGroup) {
    els.matchSelectGroup.classList.toggle("hidden", state.scope !== "match" || state.view === "league");
  }
}

function penaltyPill(count) {
  const n = Number(count);
  if (!Number.isFinite(n) || n <= 0) return "";
  return `<span class="xca-pen-pill">${n > 1 ? `${n}× ` : ""}PEN</span>`;
}

function renderPenaltiesToggle() {
  const btn = els.penaltiesBtn;
  if (!btn) return;
  const count = state.view === "league"
    ? Number(state.league?.penaltyCount || 0)
    : Number(state.report?.penaltySummary?.count || 0);
  btn.disabled = count <= 0 && !state.excludePenalties;
  btn.classList.toggle("xca-scope-btn--active", state.excludePenalties);
  btn.setAttribute("aria-pressed", state.excludePenalties ? "true" : "false");
  if (count <= 0 && !state.excludePenalties) {
    btn.textContent = "No penalties";
    btn.title = "No penalties in this selection";
    return;
  }
  btn.textContent = state.excludePenalties ? "Penalties off" : "Remove penalties";
  btn.title = state.excludePenalties
    ? "Penalties are excluded from xG and shot totals. Scoreline is unchanged."
    : "Hide penalty shots from xG, buckets, and the shot log. Scoreline stays as played.";
}

function penaltyBannerHtml(report) {
  const pen = report?.penaltySummary || {};
  const count = Number(pen.count || 0);
  if (!count) return "";
  const shots = (pen.shots || [])
    .map((shot) => {
      const who = shot.playerName || "Unknown";
      const team = shot.team === "vale" ? "Vale" : "Opp";
      const xg = Number(shot.xg || 0).toFixed(3);
      const out = shot.outcome === "goal" || shot.outcomeLabel === "GOAL" ? "GOAL" : "MISS";
      return `${who} (${team}) ${xg} xG · ${out}`;
    })
    .join("  ·  ");
  if (pen.excluded || report.excludePenalties) {
    return `<div class="xca-pen-banner xca-pen-banner--off"><span class="xca-pen-pill">PEN OFF</span> ${count} penalt${count === 1 ? "y" : "ies"} removed from xG. Scoreline unchanged. ${escapeHtml(shots)}</div>`;
  }
  return `<div class="xca-pen-banner"><span class="xca-pen-banner__tag">PENALTY INCLUDED</span> This xG includes ${count} penal${count === 1 ? "ty" : "ties"}: ${escapeHtml(shots)}</div>`;
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
        <td>${Number(row.cumulativeXg || 0).toFixed(3)}</td>
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

function shotIsPenalty(shot) {
  return Boolean(shot?.isPenalty || String(shot?.action || "").toUpperCase().includes("PENALTY"));
}

function chanceId(shot) {
  return String(shot?.chanceRating?.id || "");
}

function buildMatchHeroStats(report, match = {}) {
  const shots = report?.shots || [];
  const vale = shots.filter((shot) => shot.team === "vale");
  const opp = shots.filter((shot) => shot.team === "opp");
  const valeXg = vale.length
    ? vale.reduce((sum, shot) => sum + Number(shot.xg || 0), 0)
    : Number(match.valeXg || 0);
  const oppXg = opp.length
    ? opp.reduce((sum, shot) => sum + Number(shot.xg || 0), 0)
    : Number(match.oppXg || 0);
  const valeShots = vale.length || Number(match.valeShots || 0);
  const created = report?.xgCreated || {};
  const hqFromBuckets = Number(created.grouped?.highQuality?.count);
  const hqFromShots = vale.filter((shot) => ["excellent", "very_good"].includes(chanceId(shot))).length;
  const hq = vale.length ? hqFromShots : (Number.isFinite(hqFromBuckets) ? hqFromBuckets : 0);
  const onTarget = vale.filter((shot) => shot.onTarget || shot.onTargetLabel === "YES").length;
  const inBox = vale.filter((shot) => shot.inBox || shot.inBoxLabel === "IN").length;
  const best = vale.reduce((top, shot) => {
    if (!top || Number(shot.xg || 0) > Number(top.xg || 0)) return shot;
    return top;
  }, null);
  return {
    xgDiff: valeXg - oppXg,
    valeXg,
    oppXg,
    valeShots,
    oppShots: opp.length || Number(match.oppShots || 0),
    valeHighQuality: hq,
    valeOnTarget: vale.length ? onTarget : null,
    valeInBox: vale.length ? inBox : null,
    valeAvgXg: valeShots ? valeXg / valeShots : 0,
    bestChance: best
      ? {
          playerName: best.playerName,
          xg: Number(best.xg || 0),
          isPenalty: shotIsPenalty(best),
          outcome: best.outcome,
        }
      : null,
  };
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
    const stats = buildMatchHeroStats(report, match);
    const best = stats.bestChance;
    const xgDiff = Number(stats.xgDiff);
    const diffLabel = `${xgDiff > 0 ? "+" : ""}${xgDiff.toFixed(3)}`;
    const bestBits = best
      ? `${Number(best.xg).toFixed(3)}${best.isPenalty ? penaltyPill(1) : ""}${best.playerName ? `<span class="xca-match-hero__stat-sub">${escapeHtml(best.playerName)}</span>` : ""}`
      : "—";
    const hq = `${stats.valeHighQuality} of ${stats.valeShots}`;
    const onTgt = stats.valeOnTarget == null ? "—" : `${stats.valeOnTarget} of ${stats.valeShots}`;
    const inBoxLabel = stats.valeInBox == null ? null : `${stats.valeInBox} in the box`;
    const avgLabel = stats.valeShots ? `${stats.valeAvgXg.toFixed(3)} avg xG` : null;

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
        ${penaltyBannerHtml(report)}

        <div class="xca-match-hero__scoreboard">
          <div class="xca-match-hero__team xca-match-hero__team--vale ${valeWon ? "xca-match-hero__team--winner" : ""}">
            <img class="xca-match-hero__crest" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" />
            <div class="xca-match-hero__team-name">Port Vale</div>
            <div class="xca-match-hero__goals">${escapeHtml(valeGoals)}</div>
          </div>

          <div class="xca-match-hero__mid">
            <div class="xca-match-hero__stat">
              <div class="xca-match-hero__stat-label">xG difference</div>
              <div class="xca-match-hero__stat-value">${diffLabel}</div>
            </div>
            <div class="xca-match-hero__stat">
              <div class="xca-match-hero__stat-label">Best chance</div>
              <div class="xca-match-hero__stat-value ${best?.isPenalty ? "xca-match-hero__stat-value--pen" : ""}">${bestBits}</div>
            </div>
            <div class="xca-match-hero__stat">
              <div class="xca-match-hero__stat-label">High quality</div>
              <div class="xca-match-hero__stat-value">${hq}</div>
            </div>
            <div class="xca-match-hero__stat">
              <div class="xca-match-hero__stat-label">On target</div>
              <div class="xca-match-hero__stat-value">${onTgt}</div>
            </div>
          </div>

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
          <span><strong>${stats.valeShots}</strong> Vale shots</span>
          <span><strong>${stats.oppShots}</strong> Opp shots</span>
          ${inBoxLabel ? `<span><strong>${stats.valeInBox}</strong> in the box</span>` : ""}
          ${avgLabel ? `<span><strong>${stats.valeAvgXg.toFixed(3)}</strong> avg Vale xG</span>` : ""}
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
      ${penaltyBannerHtml(report)}
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
      <tr class="${shot.isPenalty ? "xca-shot--pen" : ""}">
        ${matchCols}
        <td>${gameStatePill(shot.gameState, shot.gameStateLabel)}</td>
        <td class="col-left">${shot.playerName}${shot.isPenalty ? penaltyPill(1) : ""}</td>
        <td><span class="xca-team-pill ${teamClass}">${shot.team === "vale" ? "VALE" : "OPP"}</span></td>
        <td>${shot.minute}</td>
        <td>${String(shot.second).padStart(2, "0")}</td>
        <td>${shot.xgDisplay}</td>
        <td>${shot.shotNumber}</td>
        <td><span class="xca-rating-pill" style="background:${shot.chanceRating.color}">${shot.chanceRating.label}</span></td>
        <td>${shot.inBoxLabel}</td>
        <td>${shot.onTargetLabel}</td>
        <td class="${outcomeClass}">${shot.outcomeLabel}${shot.isPenalty ? " · PEN" : ""}</td>
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
      const penBadge = row.penalties ? penaltyPill(row.penalties) : "";
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
                <div class="xca-player-card__name">${escapeHtml(row.playerName)}${penBadge}</div>
                <div class="xca-player-card__sub">
                  ${pluralShots(row.shots)} · ${Number(row.avgXg || 0).toFixed(3)} avg xG
                  ${goalsBadge}
                  ${row.penalties ? `<span class="xca-player-card__goal">includes ${row.penalties} penalt${row.penalties === 1 ? "y" : "ies"}</span>` : ""}
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

function applyViewChrome() {
  const league = state.view === "league";
  els.scopeGroup?.classList.toggle("hidden", league);
  if (els.matchSelectGroup) {
    els.matchSelectGroup.classList.toggle("hidden", league || state.scope !== "match");
  }
  if (league) {
    els.matchHeader.classList.add("hidden");
    els.trendsPanel?.classList.add("hidden");
  }
}

function setView(view) {
  const wasLeague = state.view === "league";
  state.view = view;
  document.querySelectorAll(".xca-view-btn").forEach((btn) => {
    btn.classList.toggle("xca-view-btn--active", btn.dataset.view === view);
  });
  els.summaryView.classList.toggle("hidden", view !== "summary");
  els.shotsView.classList.toggle("hidden", view !== "shots");
  els.playersView.classList.toggle("hidden", view !== "players");
  els.leagueView.classList.toggle("hidden", view !== "league");
  if (view === "league") {
    applyViewChrome();
    renderPenaltiesToggle();
    if (!state.league || state.leagueSeason !== state.season) {
      loadLeague();
    } else {
      renderLeague();
    }
    return;
  }
  if (wasLeague) {
    renderScopeToggle();
    renderMatchHeader();
    renderTrendsPanel();
    renderPenaltiesToggle();
  }
}

const LEAGUE_BUCKETS = [
  { id: "excellent", label: "Excellent", color: "#166534" },
  { id: "very_good", label: "Very Good", color: "#22c55e" },
  { id: "ok", label: "OK", color: "#facc15" },
  { id: "poor", label: "Poor", color: "#f97316" },
  { id: "very_poor", label: "Very Poor", color: "#ef4444" },
];

const LEAGUE_MODES = [
  { id: "total", label: "Totals" },
  { id: "perGame", label: "Per game" },
  { id: "share", label: "% of shots" },
];

function ordinal(n) {
  const v = n % 100;
  if (v >= 11 && v <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th"}`;
}

function leagueCount(row, key) {
  const side = row[state.leagueSide] || {};
  if (key === "highQuality") return Number(side.highQuality || 0);
  if (key === "shots") return Number(side.shots || 0);
  return Number(side.buckets?.[key]?.count || 0);
}

function leagueValue(row, key) {
  const side = row[state.leagueSide] || {};
  const games = Math.max(1, Number(row.games || 0));
  if (key === "name") return String(row.name || "");
  if (key === "games") return Number(row.games || 0);
  if (key === "xgPerShot") return side.shots ? Number(side.xg || 0) / side.shots : 0;
  if (key === "xg") return state.leagueMode === "perGame" ? Number(side.xg || 0) / games : Number(side.xg || 0);
  if (key === "goals") return state.leagueMode === "perGame" ? Number(side.goals || 0) / games : Number(side.goals || 0);
  const count = leagueCount(row, key);
  if (state.leagueMode === "perGame") return count / games;
  if (state.leagueMode === "share" && key !== "shots") return side.shots ? (count / side.shots) * 100 : 0;
  return count;
}

function formatLeagueValue(key, value) {
  if (key === "xg" || key === "xgPerShot") return value.toFixed(key === "xgPerShot" ? 3 : 2);
  if (key === "games") return String(value);
  if (state.leagueMode === "perGame") return value.toFixed(2);
  if (state.leagueMode === "share" && key !== "shots" && key !== "goals") return `${value.toFixed(1)}%`;
  return String(Math.round(value));
}

function sortedLeagueRows(rows, key, dir) {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = leagueValue(a, key);
    const bv = leagueValue(b, key);
    if (key === "name") return sign * av.localeCompare(bv);
    if (av !== bv) return sign * (av - bv);
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
}

function leagueRankOf(rows, key, squadId) {
  const ordered = sortedLeagueRows(rows, key, "desc");
  const target = ordered.find((row) => row.squadId === squadId);
  if (!target) return null;
  const value = leagueValue(target, key);
  return ordered.findIndex((row) => leagueValue(row, key) === value) + 1;
}

function leagueHeat(value, max, color) {
  if (!max || value <= 0) return "";
  const alpha = 0.1 + 0.6 * Math.min(1, value / max);
  const hex = Math.round(alpha * 255).toString(16).padStart(2, "0");
  return `background:${color}${hex}`;
}

function renderLeagueValeStrip(rows) {
  const vale = rows.find((row) => row.isVale);
  if (!vale) return "";
  const of = rows.length;
  const items = [
    ...LEAGUE_BUCKETS.map((b) => ({ key: b.id, label: b.label, color: b.color })),
    { key: "highQuality", label: "Exc + VG", color: "#34d399" },
    { key: "xg", label: "xG", color: "#3d8bfd" },
  ];
  const verb = state.leagueSide === "created" ? "created" : "conceded";
  const cards = items
    .map((item) => {
      const rank = leagueRankOf(rows, item.key, vale.squadId);
      return `
        <div class="xca-league-rank" style="border-top-color:${item.color}">
          <div class="xca-league-rank__label">${escapeHtml(item.label)}</div>
          <div class="xca-league-rank__value">${rank ? ordinal(rank) : "—"}</div>
          <div class="xca-league-rank__sub">${formatLeagueValue(item.key, leagueValue(vale, item.key))} ${verb}</div>
        </div>`;
    })
    .join("");
  return `
    <div class="xca-league-vale">
      <div class="xca-league-vale__title">Port Vale rank of ${of} <span>(1st = most ${verb})</span></div>
      <div class="xca-league-vale__grid">${cards}</div>
    </div>`;
}

function renderLeague() {
  const panel = els.leaguePanel;
  const data = state.league;
  if (!panel) return;
  if (!data || !data.ready) {
    const progress = data?.progress || {};
    const bits = progress.total ? ` (${progress.done || 0} of ${progress.total} matches)` : "";
    panel.innerHTML = `<p class="xca-empty">Building the league table from every ${escapeHtml(state.season)} match${bits}. This fills in on its own — first build takes a few minutes.</p>`;
    return;
  }

  const rows = data.rows || [];
  const { key: sortKey, dir } = state.leagueSort;
  const ordered = sortedLeagueRows(rows, sortKey, dir);
  const maxBy = {};
  for (const bucket of LEAGUE_BUCKETS) {
    maxBy[bucket.id] = Math.max(0, ...rows.map((row) => leagueValue(row, bucket.id)));
  }
  maxBy.highQuality = Math.max(0, ...rows.map((row) => leagueValue(row, "highQuality")));

  const arrow = (key) => (sortKey === key ? (dir === "desc" ? " ▼" : " ▲") : "");
  const th = (key, label, extra = "") =>
    `<th class="xca-league-sort ${sortKey === key ? "is-sorted" : ""} ${extra}" data-sort="${key}">${label}${arrow(key)}</th>`;

  const body = ordered
    .map((row, index) => {
      const crest = row.imageUrl
        ? `<img class="xca-league-crest" src="${escapeHtml(row.imageUrl)}" alt="" loading="lazy" />`
        : `<span class="xca-league-crest xca-league-crest--blank"></span>`;
      const bucketCells = LEAGUE_BUCKETS.map((bucket) => {
        const value = leagueValue(row, bucket.id);
        return `<td class="xca-league-num" style="${leagueHeat(value, maxBy[bucket.id], bucket.color)}">${formatLeagueValue(bucket.id, value)}</td>`;
      }).join("");
      const hq = leagueValue(row, "highQuality");
      return `
        <tr class="${row.isVale ? "xca-league-row--vale" : ""}">
          <td class="xca-league-pos">${index + 1}</td>
          <td class="xca-league-team"><div class="xca-league-team__inner">${crest}<span>${escapeHtml(row.name || "")}</span></div></td>
          <td>${row.games}</td>
          ${bucketCells}
          <td class="xca-league-num xca-league-num--strong" style="${leagueHeat(hq, maxBy.highQuality, "#34d399")}">${formatLeagueValue("highQuality", hq)}</td>
          <td class="xca-league-num">${formatLeagueValue("shots", leagueValue(row, "shots"))}</td>
          <td class="xca-league-num">${formatLeagueValue("goals", leagueValue(row, "goals"))}</td>
          <td class="xca-league-num">${formatLeagueValue("xg", leagueValue(row, "xg"))}</td>
          <td class="xca-league-num">${formatLeagueValue("xgPerShot", leagueValue(row, "xgPerShot"))}</td>
        </tr>`;
    })
    .join("");

  const sideBtns = [
    { id: "created", label: "Chances created" },
    { id: "conceded", label: "Chances conceded" },
  ]
    .map((opt) => `<button type="button" class="xca-scope-btn ${state.leagueSide === opt.id ? "xca-scope-btn--active" : ""}" data-league-side="${opt.id}">${opt.label}</button>`)
    .join("");
  const modeBtns = LEAGUE_MODES
    .map((opt) => `<button type="button" class="xca-scope-btn ${state.leagueMode === opt.id ? "xca-scope-btn--active" : ""}" data-league-mode="${opt.id}">${opt.label}</button>`)
    .join("");

  const partial = data.matchesIncluded < data.matchesTotal
    ? `<span class="xca-league-note--warn">${data.matchesIncluded} of ${data.matchesTotal} matches in${data.building ? " · adding the rest now" : ""}</span>`
    : `<span>${data.matchesTotal} matches</span>`;
  const penNote = data.excludePenalties ? " · penalties removed" : "";

  panel.innerHTML = `
    <div class="xca-league-head">
      <div>
        <h2 class="xca-panel-title">xG league table · ${escapeHtml(data.competition || "")} ${escapeHtml(data.season || "")}</h2>
        <p class="xca-league-note">${partial}${penNote} · click any column to rank by it</p>
      </div>
      <div class="xca-league-controls">
        <div class="xca-scope-toggle">${sideBtns}</div>
        <div class="xca-scope-toggle">${modeBtns}</div>
      </div>
    </div>
    ${renderLeagueValeStrip(rows)}
    <div class="xca-league-scroll">
      <table class="xca-league-table">
        <thead>
          <tr>
            <th>#</th>
            ${th("name", "Team", "col-left")}
            ${th("games", "GP")}
            ${LEAGUE_BUCKETS.map((b) => th(b.id, `<span class="xca-rating-pill" style="background:${b.color}">${b.label}</span>`)).join("")}
            ${th("highQuality", "Exc + VG")}
            ${th("shots", "Shots")}
            ${th("goals", "Goals")}
            ${th("xg", "xG")}
            ${th("xgPerShot", "xG / shot")}
          </tr>
        </thead>
        <tbody>${body || '<tr><td colspan="13">No matches yet</td></tr>'}</tbody>
      </table>
    </div>`;

  panel.querySelectorAll("[data-sort]").forEach((cell) => {
    cell.addEventListener("click", () => {
      const key = cell.dataset.sort;
      if (state.leagueSort.key === key) {
        state.leagueSort = { key, dir: state.leagueSort.dir === "desc" ? "asc" : "desc" };
      } else {
        state.leagueSort = { key, dir: key === "name" ? "asc" : "desc" };
      }
      renderLeague();
    });
  });
  panel.querySelectorAll("[data-league-side]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.leagueSide = btn.dataset.leagueSide;
      renderLeague();
    });
  });
  panel.querySelectorAll("[data-league-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.leagueMode = btn.dataset.leagueMode;
      renderLeague();
    });
  });
}

function scheduleLeaguePoll(ms) {
  if (state.leaguePollTimer) window.clearTimeout(state.leaguePollTimer);
  state.leaguePollTimer = window.setTimeout(() => {
    state.leaguePollTimer = null;
    if (state.view === "league") loadLeague({ quiet: true });
  }, ms);
}

async function loadLeague({ quiet = false } = {}) {
  const token = ++state.leagueToken;
  const season = state.season;
  if (!quiet) {
    state.league = null;
    if (els.leaguePanel) els.leaguePanel.innerHTML = '<p class="xca-empty">Loading league table…</p>';
  }
  try {
    const params = new URLSearchParams({ season });
    if (state.excludePenalties) params.set("excludePenalties", "true");
    const data = await fetchJson(`/api/xg-chance-analysis/league-table?${params}`);
    if (token !== state.leagueToken) return;
    state.league = data;
    state.leagueSeason = season;
    renderLeague();
    renderPenaltiesToggle();
    if (data.building) scheduleLeaguePoll(data.ready ? 10000 : 4000);
  } catch (err) {
    if (token !== state.leagueToken) return;
    if (els.leaguePanel) {
      els.leaguePanel.innerHTML = `<p class="xca-empty">${escapeHtml(err.message || "Could not load the league table")}</p>`;
    }
  }
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
  renderPenaltiesToggle();
  applyViewChrome();

  const penNote = report.penaltySummary?.count
    ? report.excludePenalties
      ? ` · ${report.penaltySummary.count} penalt${report.penaltySummary.count === 1 ? "y" : "ies"} removed`
      : ` · includes ${report.penaltySummary.count} penalt${report.penaltySummary.count === 1 ? "y" : "ies"}`
    : "";
  els.statusBar.textContent = `Updated ${new Date(report.updatedAt).toLocaleString("en-GB")} · ${report.shots?.length || 0} shots${penNote}`;
}

async function loadFixtures(signal) {
  const data = await fetchJson(
    `/api/xg-chance-analysis/fixtures?season=${encodeURIComponent(state.season)}`,
    signal ? { signal } : {}
  );
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
  const { token, signal } = beginLoad();
  const scopeLabel = selectedScopeLabel();
  setStatus(`Loading shot analysis for ${scopeLabel}…`, "loading");
  els.statusBar.textContent = `Loading ${scopeLabel}…`;
  showLoadingPanels(`Loading ${scopeLabel}…`);
  try {
    const params = new URLSearchParams({ season: state.season, scope: state.scope });
    if (state.scope === "match" && state.matchId) {
      params.set("matchId", state.matchId);
    }
    if (state.excludePenalties) {
      params.set("excludePenalties", "true");
    }
    const report = await fetchJson(`/api/xg-chance-analysis/report?${params}`, { signal });
    if (token !== state.loadToken) return;
    if (report?.building) {
      setStatus("No saved xG report for this view yet — Refresh pulls it when Impect has the match.", "");
      els.statusBar.textContent = "No saved report for this view.";
      showLoadingPanels("No saved xG report in the cache yet.");
      return;
    }
    state.report = report;
    setStatus("");
    renderAll();
  } catch (err) {
    if (token !== state.loadToken) return;
    if (err?.code === "ABORTED") return;
    if (err?.code === "TIMEOUT") {
      setStatus(err.message, "error");
      els.statusBar.textContent = "Load timed out";
      showLoadingPanels("Load timed out — hit Refresh.");
      return;
    }
    setStatus(err.message || "Failed to load report", "error");
    els.statusBar.textContent = "Error loading data";
    showLoadingPanels(err.message || "Failed to load report");
  } finally {
    endLoad(token);
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
    if (state.excludePenalties) {
      params.set("excludePenalties", "true");
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
  setStatus("Connecting to analysis hub…", "loading");
  showLoadingPanels("Loading match data…");
  try {
    state.meta = await fetchJson("/api/xg-chance-analysis/meta");
    if (!(state.meta.seasons || []).length) {
      state.meta.seasons = ALLOWED_SEASONS.map((value) => ({ value, label: value }));
      state.meta.defaultSeason = state.meta.defaultSeason || ALLOWED_SEASONS[0];
    }
    const seasons = filteredSeasons();
    state.season = ALLOWED_SEASONS.find((s) => seasons.some((row) => row.value === s))
      || state.meta.defaultSeason
      || ALLOWED_SEASONS[0]
      || "";
    renderSeasonToggle();
    renderScopeToggle();
    const { token, signal } = beginLoad();
    try {
      await loadFixtures(signal);
      if (token !== state.loadToken) return;
      // Re-enter loadReport via its own token so UI messaging stays consistent.
      endLoad(token);
      await loadReport();
    } catch (err) {
      if (token !== state.loadToken) return;
      endLoad(token);
      throw err;
    }
  } catch (err) {
    setStatus(err.message || "Failed to initialise", "error");
    els.statusBar.textContent = "Initialisation failed";
    showLoadingPanels(err.message || "Failed to initialise");
  }
}

els.matchSelect.addEventListener("change", async () => {
  state.matchId = els.matchSelect.value;
  state.scope = "match";
  renderScopeToggle();
  await loadReport();
});

els.refreshBtn.addEventListener("click", async () => {
  setStatus("Pulling latest match data in the background…", "loading");
  els.statusBar.textContent = "Refreshing snapshot…";
  els.refreshBtn.disabled = true;
  try {
    await fetchJson("/api/hub-snapshots/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: "analysis" }),
    });
    const started = Date.now();
    const poll = async () => {
      try {
        const status = await fetchJson("/api/hub-snapshots/status");
        if (status.refreshing || status.last_refresh_status === "running") {
          if (Date.now() - started < 180000) {
            window.setTimeout(poll, 2500);
            return;
          }
        }
        await loadFixtures();
        await loadReport();
        setStatus("Snapshot updated.", "");
      } catch (err) {
        setStatus(err.message || "Refresh failed", "error");
        els.statusBar.textContent = "Refresh failed";
      } finally {
        els.refreshBtn.disabled = false;
      }
    };
    window.setTimeout(poll, 800);
  } catch (err) {
    setStatus(err.message || "Could not start refresh.", "error");
    els.refreshBtn.disabled = false;
  }
});

els.exportPdfBtn?.addEventListener("click", () => exportPdf());

els.penaltiesBtn?.addEventListener("click", async () => {
  if (els.penaltiesBtn.disabled) return;
  state.excludePenalties = !state.excludePenalties;
  renderPenaltiesToggle();
  if (state.view === "league") {
    state.leagueSeason = "";
    await loadLeague({ quiet: true });
  }
  await loadReport();
});

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
