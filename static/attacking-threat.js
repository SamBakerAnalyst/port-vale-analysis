const state = { season: "", scope: "season", matchId: null, fixtures: [], report: null, family: "all", minPxt: 0.05, zoneSide: "end", mapPlayer: "all", chainId: null, netFocus: null, pairFocus: null };
const FAMILY_LABELS = { all: "All", cross: "Crosses", pass: "Passes", dribble: "Dribbles", shot: "Shots", setPiece: "Set pieces", regain: "Regains", other: "Other" };
const FAMILY_COLORS = { cross: "#38bdf8", pass: "#34d399", dribble: "#f97316", shot: "#ef4444", setPiece: "#c084fc", regain: "#fbbf24", other: "#94a3b8" };
const $ = (id) => document.getElementById(id);
let lakeTimer = null;
let svgSeq = 0;

function escapeHtml(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function fmt(value, digits = 2) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(digits) : "—"; }
function pct(value) { const number = Number(value); return Number.isFinite(number) ? `${Math.round(number)}%` : "—"; }
function surname(name) { const parts = String(name || "").trim().split(/\s+/); return parts.length > 1 ? parts.slice(1).join(" ") : parts[0] || ""; }
function rankTier(rank, of) {
  if (!rank) return "none";
  const size = Number(of) || 24;
  if (rank <= Math.ceil(size / 4)) return "t1";
  if (rank <= Math.ceil(size / 2)) return "t2";
  if (rank <= Math.ceil((size * 3) / 4)) return "t3";
  return "t4";
}
function rankChip(rank, of) { return rank ? `<span class="at-rank at-rank--${rankTier(rank, of)}">${rank} of ${of || 24}</span>` : `<span class="at-rank at-rank--none">—</span>`; }
async function getJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (body.detail) detail = String(body.detail); } catch (_err) {}
    throw new Error(detail);
  }
  return response.json();
}
function setStatus(text) { $("statusBar").textContent = text; }
function panelHead(kicker, title, extra = "") { return `<div class="at-panel__head"><p class="at-panel__kicker">${escapeHtml(kicker)}</p><h2 class="at-panel__title">${escapeHtml(title)}</h2>${extra}</div>`; }
function barRow(label, share, meta, color, delay = 0) {
  const width = Math.max(0, Math.min(100, Number(share) || 0));
  return `<div class="at-row"><div class="at-row__label">${escapeHtml(label)}</div><div class="at-bar"><span style="width:${width}%;background:${color};animation-delay:${delay}ms"></span></div><div class="at-row__meta">${meta}</div></div>`;
}
function countUp(root = document) {
  root.querySelectorAll("[data-count]").forEach((el) => {
    const target = Number(el.dataset.count);
    const digits = Number(el.dataset.digits || 0);
    if (!Number.isFinite(target)) return;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 900);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = (target * eased).toFixed(digits);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* ---------- pitch ---------- */
function toSvg(x, y) { return { x: ((Number(x) + 52.5) / 105) * 1050, y: ((34 - Number(y)) / 68) * 680 }; }
function pitch(inner, label, defsExtra = "") {
  const id = `p${++svgSeq}`;
  const stripes = Array.from({ length: 10 }, (_, i) => `<rect x="${i * 105}" y="0" width="105" height="680" fill="${i % 2 ? "#123222" : "#143826"}"/>`).join("");
  const line = "rgba(226,245,233,0.55)";
  return `<svg class="at-pitch" viewBox="0 0 1050 680" role="img" aria-label="${escapeHtml(label)}">
    <defs>
      <radialGradient id="${id}v" cx="50%" cy="50%" r="75%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity="0.45"/></radialGradient>
      <filter id="${id}g" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      ${defsExtra.replaceAll("{id}", id)}
    </defs>
    ${stripes}<rect width="1050" height="680" fill="url(#${id}v)"/>
    <g fill="none" stroke="${line}" stroke-width="2.5">
      <rect x="8" y="8" width="1034" height="664" rx="2"/><line x1="525" y1="8" x2="525" y2="672"/><circle cx="525" cy="340" r="70"/>
      <rect x="8" y="186" width="130" height="308"/><rect x="912" y="186" width="130" height="308"/>
      <rect x="8" y="258" width="48" height="164"/><rect x="994" y="258" width="48" height="164"/>
      <path d="M138 290 A70 70 0 0 1 138 390"/><path d="M912 290 A70 70 0 0 0 912 390"/>
    </g>
    <circle cx="525" cy="340" r="4" fill="${line}"/>
    <path d="M960 24 l30 0 m-10 -8 l10 8 l-10 8" stroke="rgba(245,197,24,0.8)" stroke-width="3" fill="none"/>
    <text x="950" y="30" text-anchor="end" fill="rgba(245,197,24,0.8)" font-size="15" font-family="Manrope" font-weight="700">ATTACK</text>
    <g filter="url(#${id}g)">${inner.replaceAll("{id}", id)}</g>
  </svg>`;
}
function arrowDefs(colors) {
  return colors.map((color, i) => `<marker id="{id}a${i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${color}"/></marker>`).join("");
}

/* ---------- controls ---------- */
function renderSeasons(meta) {
  $("seasonToggle").innerHTML = (meta.seasons || []).map((row) => {
    const active = row.value === state.season ? " at-toggle__btn--active" : "";
    return `<button type="button" class="at-toggle__btn${active}" data-season="${escapeHtml(row.value)}">${escapeHtml(row.label || row.value)}</button>`;
  }).join("");
}
function renderFixtures() {
  $("matchSelect").innerHTML = [...state.fixtures].reverse().map((row) => {
    const place = row.home ? "H" : "A";
    const score = row.score ? ` ${row.score}` : "";
    return `<option value="${row.matchId}">${escapeHtml(row.opponent)} (${place})${escapeHtml(score)}</option>`;
  }).join("");
  if (state.matchId) $("matchSelect").value = String(state.matchId);
  $("matchSelectGroup").hidden = state.scope !== "match";
}

/* ---------- overview ---------- */
function renderHero(report) {
  const h = report.headline || {};
  const of = Number(h.of) || 24;
  const rank = Number(h.rank) || of;
  const fill = of > 1 ? (of - rank) / (of - 1) : 0;
  const circ = 2 * Math.PI * 80;
  const diff = Number(h.attack) - Number(h.leagueAvg);
  const gap = h.leader ? Number(h.leader.attack) - Number(h.attack) : null;
  const chains = report.chains?.summary || {};
  const windowLabel = report.scope === "season" ? `${report.season} season` : report.scope === "last6" ? "last 6 games" : (report.fixtures?.[0] ? `vs ${report.fixtures[0].opponent}` : "this match");
  const rows = (report.table || []).filter((row) => Number.isFinite(Number(row.attack)));
  const values = rows.map((row) => Number(row.attack));
  const lo = values.length ? Math.min(...values) : 0;
  const hi = values.length ? Math.max(...values) : 1;
  const at = (v) => (hi > lo ? Math.max(0, Math.min(100, ((Number(v) - lo) / (hi - lo)) * 100)) : 50);
  const pctVsAvg = Number(h.leagueAvg) ? (diff / Number(h.leagueAvg)) * 100 : 0;
  const tier = rankTier(rank, of);
  const tierLabel = rank <= 2 ? "League leaders" : rank <= 7 ? "Top third" : rank <= 12 ? "Top half" : rank >= of - 1 ? "Bottom two" : rank >= of - 6 ? "Bottom third" : "Bottom half";
  const dangerShare = chains.perGame ? (Number(chains.threateningPerGame) / Number(chains.perGame)) * 100 : null;
  const verdict = `We add <b>${fmt(h.attack)}</b> threat a game, <b class="${diff >= 0 ? "at-up" : "at-down"}">${Math.abs(Math.round(pctVsAvg))}% ${diff >= 0 ? "above" : "below"}</b> the League Two average of ${fmt(h.leagueAvg)}.`
    + (diff < 0 ? ` Getting to average is worth <b>+${fmt(-diff)}</b> a game.` : "")
    + (h.leader && h.leader.club !== h.club ? ` ${escapeHtml(h.leader.club)} lead on <b>${fmt(h.leader.attack)}</b>.` : "");
  const tile = (value, label, sub, opts = {}) => `
    <div class="at-htile${opts.tone ? ` at-htile--${opts.tone}` : ""}">
      <span class="at-htile__label">${label}</span>
      <strong ${opts.count != null ? `data-count="${opts.count}" data-digits="${opts.digits ?? 2}"` : ""}>${value}</strong>
      <small>${sub}</small>
    </div>`;
  $("hero").innerHTML = `
    <div class="at-hero__top">
      <div class="at-ring at-ring--${tier}">
        <svg viewBox="0 0 190 190"><defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ffe27a"/><stop offset="100%" stop-color="#f59e0b"/></linearGradient></defs>
          <circle class="at-ring__track" cx="95" cy="95" r="80"/>
          <circle class="at-ring__value" id="ringValue" cx="95" cy="95" r="80" stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${circ.toFixed(1)}"/>
        </svg>
        <div class="at-ring__label"><strong data-count="${h.rank || 0}">${h.rank || "—"}</strong><span>of ${of} in League Two</span><em class="at-ring__tier">${tierLabel}</em></div>
      </div>
      <div class="at-hero__main">
        <p class="at-panel__kicker">League Two ${escapeHtml(report.season || "")} · ${escapeHtml(report.scope === "season" ? "full season" : windowLabel)} · ${report.matchCount || 0} games</p>
        <h2 class="at-hero__title">${escapeHtml(h.club || "Port Vale")} · <em>attacking threat</em></h2>
        <p class="at-hero__verdict">${verdict}</p>
        <div class="at-gauge" title="Every League Two side, threat per game">
          <div class="at-gauge__bar"></div>
          ${Number.isFinite(Number(h.leagueAvg)) ? `<div class="at-gauge__avg" style="left:${at(h.leagueAvg).toFixed(1)}%"><span>Avg ${fmt(h.leagueAvg)}</span></div>` : ""}
          ${h.leader ? `<div class="at-gauge__mark at-gauge__mark--top" style="left:${at(h.leader.attack).toFixed(1)}%"><span>${escapeHtml(initials(h.leader.club))} ${fmt(h.leader.attack)}</span></div>` : ""}
          <div class="at-gauge__mark at-gauge__mark--vale" style="left:${at(h.attack).toFixed(1)}%"><span>Vale ${fmt(h.attack)}</span></div>
        </div>
        <p class="at-hero__why">${escapeHtml(report.why || "")}</p>
      </div>
    </div>
    <div class="at-htiles">
      ${tile(fmt(h.attack), "Threat / game", `Impect squad threat · ${rank} of ${of}`, { count: h.attack || 0, tone: tier === "t4" ? "bad" : tier === "t1" ? "good" : "" })}
      ${tile(`${diff >= 0 ? "+" : "−"}${fmt(Math.abs(diff))}`, "vs league average", `${diff >= 0 ? "+" : "−"}${Math.abs(Math.round(pctVsAvg))}% on ${fmt(h.leagueAvg)}`, { tone: diff >= 0 ? "good" : "bad" })}
      ${tile(gap == null ? "—" : fmt(gap), `Gap to ${escapeHtml(h.leader?.club || "the top")}`, h.leader ? `They make ${fmt(h.leader.attack)} a game` : "")}
      ${tile(fmt(chains.threateningPerGame, 1), "Dangerous possessions / game", dangerShare == null ? "" : `${fmt(dangerShare, 1)}% of our ${Math.round(chains.perGame)} possessions`, { count: chains.threateningPerGame || 0, digits: 1 })}
      ${tile(String(chains.shotEnding ?? "—"), "Threat chains ending in a shot", `${chains.goals ?? 0} scored · ${fmt(chains.avgPassesThreatening, 1)} passes in a typical one`)}
      ${tile(pct(chains.topTenShare), "Threat from our best 10%", "Of possessions. High means we rely on a few big moments")}
    </div>
    <div class="at-hero__lower">
      <div class="at-profile">${rankProfile(report)}</div>
      <div class="at-trend">${trendChart(report)}</div>
    </div>`;
  requestAnimationFrame(() => { const ring = $("ringValue"); if (ring) ring.style.strokeDashoffset = (circ * (1 - Math.max(0.03, fill))).toFixed(1); });
  countUp($("hero"));
}
function rankProfile(report) {
  const vale = (report.table || []).find((row) => row.focus) || {};
  const of = Number(report.headline?.of) || 24;
  const ranks = vale.componentRanks || {};
  const items = [
    ["Overall threat", vale.rank],
    ["Crosses", vale.crossRank],
    ["Passes", ranks.pass],
    ["Dribbles", ranks.dribble],
    ["Shots", ranks.shot],
    ["Set pieces", ranks.setPiece],
    ["Ball wins", ranks.ballWin],
  ].filter(([, rank]) => rank);
  const weapons = (report.detail?.actions || []).filter((row) => row.rank && !["regain", "other"].includes(row.family) && Number(row.share) >= 4);
  const best = [...weapons].sort((a, b) => a.rank - b.rank)[0];
  const worst = [...weapons].sort((a, b) => b.rank - a.rank)[0];
  if (best) items.push([`Best weapon: ${best.label}`, best.rank]);
  if (worst && worst !== best) items.push([`Weakest: ${worst.label}`, worst.rank]);
  if (!items.length) return "";
  return `
    <p class="at-panel__kicker">Where we rank · 1 is best</p>
    <div class="at-prof">${items.map(([label, rank]) => `
      <div class="at-prof__row at-prof__row--${rankTier(rank, of)}">
        <span class="at-prof__label">${escapeHtml(label)}</span>
        <span class="at-prof__track"><i style="width:${(((of - rank) / Math.max(1, of - 1)) * 100).toFixed(1)}%"></i></span>
        <b>${rank}<small>/${of}</small></b>
      </div>`).join("")}
    </div>`;
}
function trendChart(report) {
  const rows = report.trend || [];
  if (!rows.length) return `<p class="at-panel__kicker">Match by match</p><p class="at-empty">Per-match threat appears after the next data refresh.</p>`;
  const badges = Object.fromEntries((report.table || []).map((row) => [String(row.squadId), row]));
  const max = Math.max(0.1, ...rows.flatMap((row) => [row.created, row.conceded]));
  const avgFor = rows.reduce((sum, row) => sum + row.created, 0) / rows.length;
  const avgAgainst = rows.reduce((sum, row) => sum + row.conceded, 0) / rows.length;
  const won = rows.filter((row) => row.created > row.conceded).length;
  const result = (row) => row.goalsFor == null ? "" : row.goalsFor > row.goalsAgainst ? "W" : row.goalsFor < row.goalsAgainst ? "L" : "D";
  return `
    <div class="at-trend__head">
      <p class="at-panel__kicker">Match by match · threat created vs conceded</p>
      <div class="at-trend__legend"><span><i class="at-trend__key at-trend__key--for"></i>Created <b>${fmt(avgFor)}</b>/g</span><span><i class="at-trend__key at-trend__key--against"></i>Conceded <b>${fmt(avgAgainst)}</b>/g</span><span>Won the threat battle <b>${won} of ${rows.length}</b></span></div>
    </div>
    <div class="at-trend__cols" style="--n:${rows.length}">
      ${rows.map((row, i) => {
        const r = result(row);
        const club = badges[String(row.opponentId)] || { club: row.opponent };
        return `<div class="at-trend__col${row.created > row.conceded ? " is-won" : ""}" title="${escapeHtml(`${row.home ? "vs" : "at"} ${row.opponent}: created ${fmt(row.created)}, conceded ${fmt(row.conceded)}${row.topAction ? ` · top weapon ${row.topAction}` : ""}`)}">
          <div class="at-trend__bars">
            <span class="at-trend__bar at-trend__bar--for" style="height:${((row.created / max) * 100).toFixed(1)}%;animation-delay:${i * 60}ms"><em>${fmt(row.created, 1)}</em></span>
            <span class="at-trend__bar at-trend__bar--against" style="height:${((row.conceded / max) * 100).toFixed(1)}%;animation-delay:${i * 60 + 30}ms"><em>${fmt(row.conceded, 1)}</em></span>
          </div>
          <div class="at-trend__crest">${badgeHtml(club, 34)}</div>
          <div class="at-trend__meta"><b class="at-res at-res--${r || "x"}">${r || "–"}</b> ${row.goalsFor ?? ""}${row.goalsFor == null ? "" : "-"}${row.goalsAgainst ?? ""} <small>${row.home ? "H" : "A"}</small></div>
        </div>`;
      }).join("")}
    </div>
    <p class="at-note">Event threat: the total of every positive action, so it runs higher than the squad figure above. Hover a column for the top weapon that day.</p>`;
}
function initials(name) { return String(name || "").replace(/^(FC|AFC)\s+/i, "").split(/\s+/).map((w) => w[0]).join("").slice(0, 3).toUpperCase(); }
function badgeHtml(row, size) {
  const fallback = `<span class="at-crest__alt" style="font-size:${Math.round(size * 0.32)}px">${escapeHtml(initials(row.club))}</span>`;
  return row.badge
    ? `<img src="${escapeHtml(row.badge)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'at-crest__alt',textContent:'${escapeHtml(initials(row.club))}'}))">`
    : fallback;
}
function renderStrip(report) {
  const rows = (report.table || []).filter((row) => Number.isFinite(Number(row.attack)));
  if (!rows.length) { $("leagueStrip").innerHTML = ""; return; }
  const values = rows.map((row) => Number(row.attack));
  const min = Math.min(...values); const max = Math.max(...values);
  const avg = Number(report.headline?.leagueAvg);
  const pos = (v) => (max > min ? ((v - min) / (max - min)) * 100 : 50);
  const vale = rows.find((row) => row.focus);
  $("leagueStrip").innerHTML = `
    <div class="at-strip__head">
      <p class="at-panel__kicker">Every League Two side · attacking threat per game</p>
      <div class="at-strip__legend">${vale ? `<span><b class="at-strip__vale-dot"></b>Port Vale <b>${fmt(vale.attack)}</b> · ${vale.rank} of ${rows.length}</span>` : ""}${Number.isFinite(avg) ? `<span><i class="at-strip__avg-key"></i>League avg <b>${fmt(avg)}</b></span>` : ""}</div>
    </div>
    <div class="at-strip__track" id="stripTrack">
      <div class="at-strip__axis"></div>
      ${Number.isFinite(avg) ? `<div class="at-strip__avg" style="left:${pos(avg).toFixed(2)}%"></div>` : ""}
      ${rows.map((row) => `<div class="at-crest${row.focus ? " at-crest--vale" : ""}${row.rank === 1 ? " at-crest--top" : ""}" data-x="${pos(Number(row.attack)).toFixed(3)}" title="${escapeHtml(`${row.rank}. ${row.club} — ${fmt(row.attack)} per game`)}">${badgeHtml(row, row.focus ? 46 : 32)}</div>`).join("")}
    </div>
    <div class="at-strip__scale"><span>${fmt(min)} · least threat</span><span>most threat · ${fmt(max)}</span></div>`;
  layoutStrip();
}
function layoutStrip() {
  const track = $("stripTrack");
  if (!track) return;
  const width = track.clientWidth;
  const crests = [...track.querySelectorAll(".at-crest")].sort((a, b) => Number(a.dataset.x) - Number(b.dataset.x));
  const lanes = [];
  const place = (el, x, need) => {
    let lane = lanes.findIndex((xs) => xs.every((item) => Math.abs(item.x - x) >= (item.need + need) / 2 + 4));
    if (lane < 0) { lanes.push([]); lane = lanes.length - 1; }
    lanes[lane].push({ x, need });
    const offset = lane === 0 ? 0 : (lane % 2 ? -1 : 1) * Math.ceil(lane / 2) * 40;
    el.style.left = `${x}px`;
    el.style.top = `calc(50% + ${offset}px)`;
  };
  const xOf = (el) => (Number(el.dataset.x) / 100) * width;
  crests.filter((el) => el.classList.contains("at-crest--vale")).forEach((el) => place(el, xOf(el), 52));
  crests.filter((el) => !el.classList.contains("at-crest--vale")).forEach((el) => place(el, xOf(el), 34));
  const used = Math.max(1, Math.ceil((lanes.length - 1) / 2));
  track.style.height = `${Math.max(110, 70 + used * 76)}px`;
}
window.addEventListener("resize", () => layoutStrip());
function renderInsights(report) {
  const rows = report.insights || [];
  $("insights").innerHTML = rows.map((row, i) => `<article class="at-insight at-insight--${escapeHtml(row.tone)}" style="animation-delay:${i * 70}ms"><h3>${escapeHtml(row.title)}</h3><p>${escapeHtml(row.text)}</p></article>`).join("");
}
function renderComponents(report) {
  const rows = report.components || [];
  const max = Math.max(...rows.map((row) => Math.abs(Number(row.value) || 0)), 0.01);
  const body = rows.length ? rows.map((row, i) => barRow(row.label, (Math.max(0, Number(row.value)) / max) * 100, `${fmt(row.value)} ${rankChip(row.rank, row.of)}`, "linear-gradient(90deg,#f59e0b,#f5c518)", i * 60)).join("") : `<p class="at-empty">No league components yet.</p>`;
  $("componentPanel").innerHTML = `${panelHead("Where the league number comes from", "Threat by type")}${body}<p class="at-note">Impect splits threat into passes, dribbles, shots, set pieces and ball wins. Each is ranked against every League Two side.</p>`;
}
function donut(rows) {
  const total = rows.reduce((sum, row) => sum + Number(row.total || 0), 0) || 1;
  let angle = -Math.PI / 2;
  const arcs = rows.map((row) => {
    const share = Number(row.total || 0) / total;
    const a2 = angle + share * Math.PI * 2;
    const large = share > 0.5 ? 1 : 0;
    const r = 70; const c = 85;
    const p1 = [c + r * Math.cos(angle), c + r * Math.sin(angle)];
    const p2 = [c + r * Math.cos(a2), c + r * Math.sin(a2)];
    angle = a2;
    return `<path d="M${p1[0].toFixed(2)} ${p1[1].toFixed(2)} A${r} ${r} 0 ${large} 1 ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}" stroke="${row.color}" stroke-width="22" fill="none"><title>${escapeHtml(`${row.label} ${row.share}%`)}</title></path>`;
  }).join("");
  const top = [...rows].sort((a, b) => b.total - a.total)[0];
  return `<svg class="at-donut" viewBox="0 0 170 170">${arcs}<text x="85" y="82" text-anchor="middle" fill="#eef2f7" font-size="26">${top ? pct(top.share) : ""}</text><text x="85" y="102" text-anchor="middle" fill="#8d9bb0" font-size="12" font-family="Manrope">${escapeHtml(top?.label || "")}</text></svg>`;
}
function renderPhases(report) {
  const phases = report.detail?.phases || [];
  const body = phases.length ? phases.map((row, i) => barRow(row.label, row.share, `${fmt(row.perGame)}/g · ${row.share}% ${row.rank ? rankChip(row.rank, row.of) : ""}`, row.color, i * 60)).join("") : `<p class="at-empty">No phase threat in this window.</p>`;
  const note = report.scope === "season" ? "Ranks compare our threat per game in each phase with every League Two side." : "League ranks are shown for the full season view.";
  $("phasePanel").innerHTML = `${panelHead("When we add it", "Threat by phase")}<div class="at-phase-wrap">${phases.length ? donut(phases) : ""}<div>${body}</div></div><p class="at-note">${note}</p>`;
}

/* ---------- chains ---------- */
function stepPills(steps) {
  return steps.map((step, i) => `${i ? `<span class="at-step__arrow">→</span>` : ""}<span class="at-step" style="background:${step.color || FAMILY_COLORS[step.family] || "#94a3b8"}">${escapeHtml(step.label)}${step.times > 1 ? ` ×${step.times}` : ""}</span>`).join("");
}
function renderChainSummary(report) {
  const s = report.chains?.summary;
  if (!s) { $("chainSummary").innerHTML = `<div class="at-tile"><span>Chains appear after the next Refresh data.</span></div>`; return; }
  const tiles = [
    [s.perGame, 1, "Possessions / game"],
    [s.threateningPerGame, 1, "Dangerous possessions / game"],
    [s.shotEnding, 0, "Possessions ending in a shot"],
    [s.goals, 0, "Goals from open chains"],
    [s.avgPassesThreatening, 1, "Passes in a dangerous possession"],
    [s.topTenShare, 0, "% of threat from our best 10%"],
  ];
  $("chainSummary").innerHTML = tiles.map(([value, digits, label]) => `<div class="at-tile"><strong data-count="${Number(value) || 0}" data-digits="${digits}">${fmt(value, digits)}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  countUp($("chainSummary"));
}
function renderPatterns(report) {
  const rows = report.chains?.patterns || [];
  const max = Math.max(...rows.map((row) => row.threat), 0.01);
  const body = rows.length ? `<div class="at-patterns">${rows.map((row, i) => `
    <button type="button" class="at-pattern" data-example="${escapeHtml(row.exampleId)}">
      <div class="at-pattern__top"><span class="at-pattern__rank">${i + 1}</span><div class="at-steps">${stepPills(row.steps)}</div></div>
      <div class="at-pattern__stats"><span><b>${row.count}</b> times</span><span><b>${row.share}%</b> of threat</span><span><b>${fmt(row.perChain, 3)}</b> each</span><span><b>${row.shots}</b> shots</span><span><b>${row.goals}</b> goals</span></div>
      <div class="at-bar"><span style="width:${(row.threat / max) * 100}%;background:linear-gradient(90deg,#f59e0b,#f5c518);animation-delay:${i * 50}ms"></span></div>
    </button>`).join("")}</div>` : `<p class="at-empty">No repeated threat chains in this window yet.</p>`;
  $("patternPanel").innerHTML = `${panelHead("The sequences that hurt teams", "Best threat chains")}${body}<p class="at-note">The last three threat-adding actions of each dangerous possession. Click one to replay our best example on the pitch.</p>`;
  $("patternPanel").querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => {
    const top = report.chains?.top || [];
    const found = top.find((chain) => chain.id === button.dataset.example);
    $("patternPanel").querySelectorAll(".at-pattern").forEach((item) => item.classList.toggle("is-active", item === button));
    if (found) { state.chainId = found.id; renderExplorer(report); }
    else setStatus("That example is not one of the top chains saved for replay — showing the best chain instead.");
  }));
}
function playerInitials(name) {
  const parts = String(name || "").replace(/[^\p{L}\s'-]/gu, "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
function chainSvg(chain) {
  const steps = chain.steps || [];
  const defs = arrowDefs(steps.map((step) => step.color || "#94a3b8"));
  let delay = 0;
  const nextStart = (i) => steps.slice(i + 1).find((later) => later.x1 != null);
  const parts = steps.map((step, i) => {
    if (step.x1 == null) return "";
    const a = toSvg(step.x1, step.y1);
    const after = nextStart(i);
    const endX = step.x2 != null ? step.x2 : (after && !step.shot ? after.x1 : null);
    const endY = step.x2 != null ? step.y2 : (after && !step.shot ? after.y1 : null);
    const hasEnd = endX != null;
    const b = hasEnd ? toSvg(endX, endY) : a;
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const d = delay; delay += 260;
    let link = "";
    if (after && step.x2 != null && !step.shot) {
      const n = toSvg(after.x1, after.y1);
      const gap = Math.hypot(n.x - b.x, n.y - b.y);
      if (gap > 20) link = `<line x1="${b.x.toFixed(1)}" y1="${b.y.toFixed(1)}" x2="${n.x.toFixed(1)}" y2="${n.y.toFixed(1)}" stroke="rgba(226,245,233,0.45)" stroke-width="2" stroke-dasharray="2 6" stroke-linecap="round" class="at-pop" style="animation-delay:${d + 200}ms"/>`;
    }
    const width = 3 + Math.min(7, Number(step.pxt) * 30);
    const dash = step.family === "dribble" ? ` stroke-dasharray="7 6"` : "";
    const trim = len > 40 ? 18 / len : 0;
    const tip = { x: b.x - (b.x - a.x) * trim, y: b.y - (b.y - a.y) * trim };
    const line = hasEnd && len > 4 ? `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${tip.x.toFixed(1)}" y2="${tip.y.toFixed(1)}" stroke="${step.color}" stroke-width="${width.toFixed(1)}" stroke-linecap="round" marker-end="url(#{id}a${i})" class="${dash ? "at-pop" : "at-draw"}" style="--len:${len.toFixed(0)};animation-delay:${d}ms"${dash}><title>${escapeHtml(`${i + 1}. ${step.player} — ${step.label} (${fmt(step.pxt, 3)})`)}</title></line>` : "";
    const node = `<g class="at-pop" style="animation-delay:${d}ms"><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="15" fill="${step.color}" stroke="#0b0f15" stroke-width="2.5"/><text x="${a.x.toFixed(1)}" y="${(a.y + 4.5).toFixed(1)}" text-anchor="middle" font-size="12.5" font-weight="800" fill="#0b0f15" font-family="Manrope" letter-spacing="-0.3">${escapeHtml(playerInitials(step.player))}</text><title>${escapeHtml(`${i + 1}. ${step.player} — ${step.label}`)}</title></g>`;
    const goal = step.goal ? `<g class="at-pop" style="animation-delay:${d + 400}ms"><circle cx="${b.x.toFixed(1)}" cy="${b.y.toFixed(1)}" r="20" fill="none" stroke="#f5c518" stroke-width="4"/><text x="${(b.x - 26).toFixed(1)}" y="${(b.y - 26).toFixed(1)}" text-anchor="end" fill="#f5c518" font-size="22" font-weight="800" font-family="Barlow Condensed">GOAL</text></g>` : "";
    return { lines: link + line, top: node + goal };
  }).filter(Boolean);
  return pitch(parts.map((p) => p.lines).join("") + parts.map((p) => p.top).join(""), "Chain replay, attacking to the right", defs);
}
function chainKey(chain) {
  const order = ["pass", "cross", "dribble", "shot", "setPiece", "regain", "other"];
  const names = { pass: "Pass", cross: "Cross", dribble: "Dribble / carry", shot: "Shot / header", setPiece: "Set piece", regain: "Regain / defensive", other: "Other" };
  const used = new Set((chain.steps || []).map((step) => step.family));
  const colours = order.filter((family) => used.has(family)).map((family) => `<span class="at-key__item"><i class="at-key__dot" style="background:${FAMILY_COLORS[family]}"></i>${names[family]}</span>`).join("");
  const styles = [
    used.has("dribble") ? `<span class="at-key__item"><i class="at-key__line at-key__line--dash"></i>Dashed = carrying the ball</span>` : "",
    `<span class="at-key__item"><i class="at-key__line at-key__line--thick"></i>Thicker = more threat added</span>`,
    chain.goal ? `<span class="at-key__item"><i class="at-key__ring"></i>Gold ring = goal</span>` : "",
    `<span class="at-key__item"><i class="at-key__badge">JG</i>Player initials</span>`,
  ].join("");
  return `<div class="at-key" aria-label="Key">${colours}<span class="at-key__sep"></span>${styles}</div>`;
}
function outcomeBadge(chain) {
  const map = { goal: ["goal", "Goal"], shot: ["shot", "Shot"], threat: ["threat", "Dangerous"], none: ["none", "No shot"] };
  const [cls, label] = map[chain.outcome] || map.none;
  return `<span class="at-badge at-badge--${cls}">${label}</span>`;
}
function renderExplorer(report) {
  const top = report.chains?.top || [];
  if (!top.length) { $("explorerPanel").innerHTML = `${panelHead("Replay", "Chain explorer")}<p class="at-empty">No chains saved for this window yet.</p>`; return; }
  let index = top.findIndex((chain) => chain.id === state.chainId);
  if (index < 0) index = 0;
  const chain = top[index];
  state.chainId = chain.id;
  const vs = chain.opponent ? `${chain.home ? "vs" : "at"} ${escapeHtml(chain.opponent)}` : "";
  const steps = (chain.steps || []).map((step, i) => `<div class="at-chain-step" style="animation-delay:${i * 260}ms"><span class="at-chain-step__n" style="background:${step.color}" title="Step ${i + 1}">${escapeHtml(playerInitials(step.player))}</span><span><b>${escapeHtml(step.player || "—")}</b> · ${escapeHtml(step.label)}${step.goal ? " ⚽" : ""}</span><span class="at-chain-step__v">${Number(step.pxt) > 0 ? `+${fmt(step.pxt, 3)}` : "·"}${step.xg ? ` · xG ${fmt(step.xg)}` : ""}</span></div>`).join("");
  const chips = top.map((item, i) => `<button type="button" class="at-chain-chip${i === index ? " is-active" : ""}" data-chain="${escapeHtml(item.id)}"><b>${fmt(item.threat, 2)}</b>${escapeHtml(item.opponent || "")} ${item.minute}'${item.goal ? " ⚽" : ""}</button>`).join("");
  $("explorerPanel").innerHTML = `
    <div class="at-explorer__head">
      <div>${panelHead("Replay our best moves", "Chain explorer")}<p class="at-explorer__meta">${outcomeBadge(chain)} &nbsp;${vs} · ${chain.minute}' · ${escapeHtml(chain.origin)} · ${chain.passes} passes · <b style="color:#f5c518">${fmt(chain.threat, 3)}</b> threat${chain.xg ? ` · xG ${fmt(chain.xg)}` : ""}</p></div>
      <div class="at-explorer__controls"><button type="button" class="at-icon-btn" data-nav="-1">‹ Prev</button><button type="button" class="at-icon-btn at-icon-btn--gold" data-nav="0">▶ Replay</button><button type="button" class="at-icon-btn" data-nav="1">Next ›</button></div>
    </div>
    ${chainSvg(chain)}
    ${chainKey(chain)}
    <div class="at-chain-steps">${steps}</div>
    <div class="at-chain-list">${chips}</div>`;
  $("explorerPanel").querySelectorAll("[data-nav]").forEach((button) => button.addEventListener("click", () => {
    const move = Number(button.dataset.nav);
    state.chainId = top[(index + move + top.length) % top.length].id;
    renderExplorer(report);
  }));
  $("explorerPanel").querySelectorAll("[data-chain]").forEach((button) => button.addEventListener("click", () => { state.chainId = button.dataset.chain; renderExplorer(report); }));
}
function renderOrigins(report) {
  const rows = report.chains?.origins || [];
  const max = Math.max(...rows.map((row) => row.perChain), 0.001);
  const body = rows.length ? `<div class="at-table-wrap"><table><thead><tr><th>Start</th><th></th><th>Possessions</th><th>Share of threat</th><th>Threat each</th><th>Shot %</th><th>Goals</th></tr></thead><tbody>${rows.map((row) => `<tr><td><span class="at-dot" style="background:${row.color}"></span>${escapeHtml(row.label)}</td><td><span class="at-cellbar" style="width:${Math.max(4, (row.perChain / max) * 90).toFixed(0)}px;background:${row.color}"></span></td><td>${row.count}</td><td>${row.share}%</td><td>${fmt(row.perChain, 3)}</td><td>${fmt(row.shotRate, 0)}%</td><td>${row.goals}</td></tr>`).join("")}</tbody></table></div>` : `<p class="at-empty">No possessions yet.</p>`;
  $("originPanel").innerHTML = `${panelHead("How dangerous possessions begin", "Chain origins")}${body}<p class="at-note">The bar is threat per possession: how valuable each start is, not how often it happens.</p>`;
}
function renderLengths(report) {
  const rows = report.chains?.lengths || [];
  const max = Math.max(...rows.map((row) => row.perChain), 0.001);
  const body = rows.length ? rows.map((row, i) => barRow(row.label, (row.perChain / max) * 100, `${fmt(row.perChain, 3)} each · ${row.share}% · shot ${fmt(row.shotRate, 0)}%`, ["#f97316", "#f5c518", "#34d399", "#38bdf8"][i % 4], i * 70)).join("") : `<p class="at-empty">No possessions yet.</p>`;
  $("lengthPanel").innerHTML = `${panelHead("Direct or patient?", "Possession length")}${body}<p class="at-note">Threat per possession by how many passes we strung together. Share is the slice of all our possession threat.</p>`;
}

/* ---------- links ---------- */
function layoutNodes(nodes, radius) {
  const pts = nodes.map((node) => { const p = toSvg(node.x, node.y); return { id: node.id, ax: p.x, ay: p.y, x: p.x, y: p.y, r: radius(node) }; });
  for (let iter = 0; iter < 260; iter++) {
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const a = pts[i]; const b = pts[j];
        let dx = b.x - a.x; let dy = b.y - a.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) { dx = 1; dy = 0.5; dist = 1.1; }
        const need = a.r + b.r + 46;
        if (dist < need) {
          const push = (need - dist) / 2;
          const ux = dx / dist; const uy = dy / dist;
          a.x -= ux * push; a.y -= uy * push * 1.25;
          b.x += ux * push; b.y += uy * push * 1.25;
        }
      }
    }
    pts.forEach((p) => {
      p.x += (p.ax - p.x) * 0.02; p.y += (p.ay - p.y) * 0.02;
      p.x = Math.max(p.r + 40, Math.min(1050 - p.r - 40, p.x));
      p.y = Math.max(p.r + 20, Math.min(680 - p.r - 34, p.y));
    });
  }
  return Object.fromEntries(pts.map((p) => [p.id, p]));
}
function renderNetwork(report) {
  const network = report.links?.network || { nodes: [], edges: [] };
  if (!network.nodes.length) { $("networkPanel").innerHTML = `${panelHead("Threat network", "Who creates together")}<p class="at-empty">Links appear after the next Refresh data.</p>`; return; }
  const maxEdge = Math.max(...network.edges.map((edge) => edge.total), 0.01);
  const maxNode = Math.max(...network.nodes.map((node) => node.threat), 0.01);
  const radius = (node) => 16 + Math.sqrt(node.threat / maxNode) * 18;
  const pos = layoutNodes(network.nodes, radius);
  const edges = [...network.edges].sort((a, b) => a.total - b.total).map((edge) => {
    const a = pos[edge.from]; const b = pos[edge.to];
    if (!a || !b) return "";
    const dx = b.x - a.x; const dy = b.y - a.y; const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len; const uy = dy / len;
    const bend = Math.min(60, len * 0.16);
    const cx = (a.x + b.x) / 2 - uy * bend; const cy = (a.y + b.y) / 2 + ux * bend;
    const sx = a.x + ((cx - a.x) / Math.hypot(cx - a.x, cy - a.y)) * (a.r + 3);
    const sy = a.y + ((cy - a.y) / Math.hypot(cx - a.x, cy - a.y)) * (a.r + 3);
    const ex = b.x + ((cx - b.x) / Math.hypot(cx - b.x, cy - b.y)) * (b.r + 7);
    const ey = b.y + ((cy - b.y) / Math.hypot(cx - b.x, cy - b.y)) * (b.r + 7);
    const t = edge.total / maxEdge;
    return `<path class="at-edge" data-from="${edge.from}" data-to="${edge.to}" d="M${sx.toFixed(1)} ${sy.toFixed(1)} Q${cx.toFixed(1)} ${cy.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}" stroke="rgba(245,197,24,${(0.28 + t * 0.67).toFixed(2)})" stroke-width="${(2 + t * 9).toFixed(1)}" fill="none" stroke-linecap="round" marker-end="url(#{id}a0)"><title>${escapeHtml(`${edge.fromName} → ${edge.toName}: ${edge.count} passes, ${fmt(edge.total, 3)} threat`)}</title></path>`;
  }).join("");
  const nodes = network.nodes.map((node) => {
    const p = pos[node.id];
    const t = node.threat / maxNode;
    const label = surname(node.name);
    const w = Math.max(44, label.length * 8.6 + 16);
    return `<g class="at-node" data-node="${node.id}">
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${p.r.toFixed(1)}" fill="#10151d" stroke="#f5c518" stroke-width="${(2 + t * 2).toFixed(1)}"/>
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${(p.r - 5).toFixed(1)}" fill="rgba(245,197,24,${(0.18 + t * 0.8).toFixed(2)})"/>
      <text x="${p.x.toFixed(1)}" y="${(p.y + 5).toFixed(1)}" text-anchor="middle" font-size="13" font-weight="800" fill="${t > 0.45 ? "#1a1403" : "#f5e6a8"}" font-family="Manrope">${escapeHtml(playerInitials(node.name))}</text>
      <rect x="${(p.x - w / 2).toFixed(1)}" y="${(p.y + p.r + 5).toFixed(1)}" width="${w.toFixed(1)}" height="21" rx="10.5" fill="rgba(7,9,13,0.85)" stroke="rgba(245,197,24,0.35)"/>
      <text x="${p.x.toFixed(1)}" y="${(p.y + p.r + 19.5).toFixed(1)}" text-anchor="middle" font-size="13" font-weight="700" fill="#eef2f7" font-family="Manrope">${escapeHtml(label)}</text>
      <title>${escapeHtml(`${node.name}: ${fmt(node.threat, 2)} threat created, ${fmt(node.received, 2)} received, ${node.touches} actions`)}</title></g>`;
  }).join("");
  const key = `<div class="at-key"><span class="at-key__item"><i class="at-key__ring" style="width:10px;height:10px"></i><i class="at-key__ring" style="width:18px;height:18px;background:rgba(245,197,24,.6)"></i>Bigger, brighter = more threat created</span><span class="at-key__item"><i class="at-key__line" style="border-color:#f5c518;border-top-width:2px"></i><i class="at-key__line" style="border-color:#f5c518;border-top-width:7px;border-radius:3px"></i>Thicker = more dangerous link</span><span class="at-key__item">Arrow points to the receiver</span><span class="at-key__item"><i class="at-key__line" style="border-color:#ef4444;border-top-width:3px"></i>Pass that led to a shot</span></div>`;
  $("networkPanel").innerHTML = `${panelHead("Threat network", "Who creates together", `<button type="button" class="at-chip-btn" id="netReset" hidden>Show everyone</button>`)}<div class="at-net" id="netWrap">${pitch(edges + `<g class="at-pairlayer" id="pairLayer"></g>` + nodes, "Threat network, attacking to the right", arrowDefs(["rgba(245,197,24,0.95)", "#ef4444", "#f5c518"]))}</div>${key}<div class="at-spot" id="netSpot"></div><p class="at-note">Our 11 most involved players, placed at their average position on the ball (nudged apart where they overlap). Only the ${network.edges.length} strongest links are drawn. Click a player or a partnership to dig in.</p>`;
  const wrap = $("netWrap");
  wrap.querySelectorAll("[data-node]").forEach((g) => g.addEventListener("click", () => {
    const id = Number(g.dataset.node);
    state.pairFocus = null;
    state.netFocus = state.netFocus === id ? null : id;
    applyNetFocus();
  }));
  $("netReset").addEventListener("click", () => { state.netFocus = null; state.pairFocus = null; applyNetFocus(); });
  applyNetFocus();
}
function focusedPair() {
  const key = state.pairFocus;
  return key ? (state.report?.links?.pairs || []).find((row) => `${row.from}-${row.to}` === key) || null : null;
}
function applyNetFocus() {
  const wrap = $("netWrap"); if (!wrap) return;
  const pair = focusedPair();
  const id = pair ? null : state.netFocus;
  const active = id != null || pair != null;
  wrap.classList.toggle("is-focus", active);
  wrap.classList.toggle("is-pair", pair != null);
  $("netReset").hidden = !active;
  const linked = new Set(pair ? [pair.from, pair.to] : [id]);
  wrap.querySelectorAll(".at-edge").forEach((edge) => {
    const from = Number(edge.dataset.from); const to = Number(edge.dataset.to);
    const on = pair ? from === pair.from && to === pair.to : id != null && (from === id || to === id);
    edge.classList.toggle("is-on", on);
    if (on && id != null) { linked.add(from); linked.add(to); }
  });
  wrap.querySelectorAll(".at-node").forEach((node) => node.classList.toggle("is-on", linked.has(Number(node.dataset.node))));
  document.querySelectorAll(".at-pair").forEach((row) => {
    const from = Number(row.dataset.from); const to = Number(row.dataset.to);
    row.classList.toggle("is-on", pair ? from === pair.from && to === pair.to : id != null && (from === id || to === id));
  });
  document.querySelectorAll(".at-mx td[data-from]").forEach((cell) => {
    const from = Number(cell.dataset.from); const to = Number(cell.dataset.to);
    cell.classList.toggle("is-on", pair ? from === pair.from && to === pair.to : id != null && (from === id || to === id));
  });
  drawPairLines(wrap, pair);
  renderSpot(pair, id);
}
function drawPairLines(wrap, pair) {
  const layer = wrap.querySelector("#pairLayer"); if (!layer) return;
  if (!pair || !(pair.lines || []).length) { layer.innerHTML = ""; return; }
  const markers = [...wrap.querySelectorAll("marker")].map((m) => m.id);
  const max = Math.max(...pair.lines.map((line) => line.v), 0.01);
  layer.innerHTML = [...pair.lines].reverse().map((line) => {
    const a = toSvg(line.x1, line.y1); const b = toSvg(line.x2, line.y2);
    const t = line.v / max;
    const color = line.shot ? "#ef4444" : "#f5c518";
    return `<line class="at-pline" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${color}" stroke-opacity="${(0.45 + t * 0.55).toFixed(2)}" stroke-width="${(2.5 + t * 4).toFixed(1)}" stroke-linecap="round" marker-end="url(#${line.shot ? markers[1] : markers[2]})"/><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="5" fill="${color}"/>`;
  }).join("");
}
function linkBars(rows, max, nameKey) {
  if (!rows.length) return `<p class="at-empty">None yet.</p>`;
  return rows.map((row) => `<div class="at-spot__link"><span>${escapeHtml(surname(row[nameKey]))}</span><i><b style="width:${Math.max(6, (row.total / max) * 100).toFixed(0)}%"></b></i><em>${fmt(row.total, 2)}</em></div>`).join("");
}
function renderSpot(pair, id) {
  const spot = $("netSpot"); if (!spot) return;
  const network = state.report?.links?.network || { nodes: [], matrix: [] };
  const names = Object.fromEntries(network.nodes.map((node) => [node.id, node.name]));
  if (pair) {
    const shotRate = pair.count ? Math.round((pair.shots / pair.count) * 100) : 0;
    spot.innerHTML = `
      <div class="at-spot__head"><span class="at-avatar">${escapeHtml(playerInitials(pair.fromName))}</span><span class="at-spot__arrow">→</span><span class="at-avatar at-avatar--to">${escapeHtml(playerInitials(pair.toName))}</span>
        <div><strong>${escapeHtml(pair.fromName)} → ${escapeHtml(pair.toName)}</strong><small>Mostly ${escapeHtml((pair.topAction || "passes").toLowerCase())} · the ${(pair.lines || []).length} most dangerous passes are drawn</small></div></div>
      <div class="at-spot__stats">
        <div><b>${pair.count}</b><span>Passes</span></div>
        <div><b>${fmt(pair.total, 2)}</b><span>Link threat</span></div>
        <div><b>${fmt(pair.passThreat, 2)}</b><span>From the pass</span></div>
        <div><b>${fmt(pair.followThreat, 2)}</b><span>Receiver's next action</span></div>
        <div class="${pair.shots ? "is-hot" : ""}"><b>${pair.shots || 0}</b><span>Led to a shot (${shotRate}%)</span></div>
        <div class="${pair.goals ? "is-gold" : ""}"><b>${pair.goals || 0}</b><span>Led to a goal</span></div>
      </div>`;
    return;
  }
  if (id == null) {
    const top = [...network.nodes].sort((a, b) => b.threat - a.threat)[0];
    const hub = [...network.nodes].map((node) => ({ node, n: (network.matrix || []).filter((row) => row.from === node.id || row.to === node.id).reduce((sum, row) => sum + row.total, 0) })).sort((a, b) => b.n - a.n)[0];
    spot.innerHTML = top ? `<div class="at-spot__hint"><span>Biggest threat creator <b>${escapeHtml(top.name)}</b> (${fmt(top.threat, 2)})</span>${hub ? `<span>Most connected <b>${escapeHtml(hub.node.name)}</b> (${fmt(hub.n, 2)} link threat)</span>` : ""}<span class="at-spot__tip">Tap a player for their links</span></div>` : "";
    return;
  }
  const node = network.nodes.find((row) => row.id === id); if (!node) { spot.innerHTML = ""; return; }
  const out = (network.matrix || []).filter((row) => row.from === id).map((row) => ({ ...row, name: names[row.to] })).sort((a, b) => b.total - a.total).slice(0, 4);
  const inn = (network.matrix || []).filter((row) => row.to === id).map((row) => ({ ...row, name: names[row.from] })).sort((a, b) => b.total - a.total).slice(0, 4);
  const max = Math.max(...out.map((row) => row.total), ...inn.map((row) => row.total), 0.01);
  const profile = (state.report?.detail?.players || []).find((row) => Number(row.id) === id) || {};
  spot.innerHTML = `
    <div class="at-spot__head"><span class="at-avatar at-avatar--big">${escapeHtml(playerInitials(node.name))}</span>
      <div><strong>${escapeHtml(node.name)}</strong><small>${node.touches} actions in our possessions${profile.share ? ` · ${profile.share}% of team threat` : ""}</small></div></div>
    <div class="at-spot__stats">
      <div><b>${fmt(node.threat, 2)}</b><span>Threat created</span></div>
      <div><b>${fmt(node.received, 2)}</b><span>Threat received</span></div>
      <div><b>${profile.chains ?? "—"}</b><span>Dangerous chains in</span></div>
      <div class="${profile.shotChains ? "is-hot" : ""}"><b>${profile.shotChains ?? "—"}</b><span>Chains ending in a shot</span></div>
    </div>
    <div class="at-spot__cols">
      <div><p class="at-spot__sub">Gives it to</p>${linkBars(out, max, "name")}</div>
      <div><p class="at-spot__sub">Gets it from</p>${linkBars(inn, max, "name")}</div>
    </div>`;
}
function setPairFocus(key) {
  state.pairFocus = state.pairFocus === key ? null : key;
  state.netFocus = null;
  applyNetFocus();
}
function renderPairs(report) {
  const rows = report.links?.pairs || [];
  const max = Math.max(...rows.map((row) => row.total), 0.01);
  const body = rows.length ? `<div class="at-legend"><span><i style="background:#f5c518"></i>Pass threat</span><span><i style="background:#38bdf8"></i>What the receiver did next</span><span><i style="background:#ef4444"></i>Led to a shot</span></div><div class="at-pairs">${rows.map((row, i) => `
    <div class="at-pair" data-from="${row.from}" data-to="${row.to}" data-key="${row.from}-${row.to}">
      <span class="at-pair__n">${i + 1}</span>
      <div class="at-pair__duo"><span class="at-avatar at-avatar--sm">${escapeHtml(playerInitials(row.fromName))}</span><span class="at-avatar at-avatar--sm at-avatar--to">${escapeHtml(playerInitials(row.toName))}</span></div>
      <div><div class="at-pair__names">${escapeHtml(row.fromName)}<span>→</span>${escapeHtml(row.toName)}</div><div class="at-pair__sub">${row.count} passes · mostly ${escapeHtml(row.topAction.toLowerCase())}${row.shots ? ` · <b class="at-pair__shot">${row.shots} shot${row.shots === 1 ? "" : "s"}</b>` : ""}${row.goals ? ` · <b class="at-pair__goal">${row.goals} goal${row.goals === 1 ? "" : "s"}</b>` : ""}</div>
        <div class="at-stack" style="width:${Math.max(8, (row.total / max) * 100)}%"><span style="width:${row.total ? (row.passThreat / row.total) * 100 : 0}%;background:#f5c518"></span><span style="width:${row.total ? (row.followThreat / row.total) * 100 : 0}%;background:#38bdf8"></span></div></div>
      <div class="at-pair__v">${fmt(row.total, 2)}<small>${fmt(row.perGame, 3)}/g</small></div>
    </div>`).join("")}</div><p class="at-note">Click a partnership to draw its passes on the network.</p>` : `<p class="at-empty">No links yet.</p>`;
  $("pairPanel").innerHTML = `${panelHead("Partnerships", "Most dangerous links")}${body}`;
  $("pairPanel").querySelectorAll(".at-pair").forEach((row) => row.addEventListener("click", () => setPairFocus(row.dataset.key)));
}
function renderMatrix(report) {
  const panel = $("matrixPanel"); if (!panel) return;
  const network = report.links?.network || { nodes: [], matrix: [] };
  const matrix = network.matrix || [];
  if (!network.nodes.length || !matrix.length) { panel.innerHTML = `${panelHead("Link matrix", "Who feeds who")}<p class="at-empty">Appears after the next Refresh data.</p>`; return; }
  const players = [...network.nodes].sort((a, b) => b.threat - a.threat);
  const cell = Object.fromEntries(matrix.map((row) => [`${row.from}-${row.to}`, row]));
  const max = Math.max(...matrix.map((row) => row.total), 0.01);
  const pairKeys = new Set((report.links?.pairs || []).map((row) => `${row.from}-${row.to}`));
  const head = players.map((p) => `<th title="${escapeHtml(p.name)}"><span>${escapeHtml(surname(p.name))}</span></th>`).join("");
  const body = players.map((from) => `<tr><th class="at-mx__row">${escapeHtml(surname(from.name))}</th>${players.map((to) => {
    if (from.id === to.id) return `<td class="at-mx__self"></td>`;
    const row = cell[`${from.id}-${to.id}`];
    if (!row) return `<td class="at-mx__empty" data-from="${from.id}" data-to="${to.id}"></td>`;
    const t = Math.sqrt(row.total / max);
    return `<td data-from="${from.id}" data-to="${to.id}" data-pair="${pairKeys.has(`${from.id}-${to.id}`) ? `${from.id}-${to.id}` : ""}" style="background:rgba(245,197,24,${(0.06 + t * 0.85).toFixed(2)});color:${t > 0.55 ? "#1a1403" : "#e2e8f0"}" title="${escapeHtml(`${from.name} → ${to.name}: ${row.count} passes, ${fmt(row.total, 3)} threat${row.shots ? `, ${row.shots} led to a shot` : ""}`)}">${row.total >= 0.05 ? fmt(row.total, 2) : ""}${row.shots ? `<i class="at-mx__shot"></i>` : ""}</td>`;
  }).join("")}</tr>`).join("");
  panel.innerHTML = `${panelHead("Link matrix", "Who feeds who")}<div class="at-mx-wrap"><table class="at-mx"><thead><tr><th class="at-mx__corner"><span>Passer ↓</span><span>Receiver →</span></th>${head}</tr></thead><tbody>${body}</tbody></table></div><p class="at-note">Every link between our 11 most involved players. Brighter = more threat. Red dot = at least one pass led to a shot. Click a cell to see it on the network.</p>`;
  panel.querySelectorAll("td[data-from]").forEach((td) => td.addEventListener("click", () => {
    if (td.dataset.pair) setPairFocus(td.dataset.pair);
    else { state.pairFocus = null; state.netFocus = Number(td.dataset.from); applyNetFocus(); }
    $("networkPanel").scrollIntoView({ behavior: "smooth", block: "center" });
  }));
}
function renderTrios(report) {
  const rows = report.links?.trios || [];
  const max = Math.max(...rows.map((row) => row.threat), 0.01);
  const body = rows.length ? `<div class="at-trios">${rows.map((row, i) => `<div class="at-trio">
      <div class="at-trio__top"><span class="at-pair__n">${i + 1}</span><span class="at-trio__val">${fmt(row.threat, 2)}<small> threat · ${row.count}×</small></span></div>
      <div class="at-trio__flow">${row.names.map((name, j) => `<div class="at-trio__p"><span class="at-avatar${j === 2 ? " at-avatar--to" : ""}">${escapeHtml(playerInitials(name))}</span><small>${escapeHtml(surname(name))}</small></div>`).join(`<span class="at-trio__arrow">→</span>`)}</div>
      <div class="at-trio__bar"><b style="width:${Math.max(6, (row.threat / max) * 100).toFixed(0)}%"></b></div>
    </div>`).join("")}</div>` : `<p class="at-empty">No three-man moves yet.</p>`;
  $("trioPanel").innerHTML = `${panelHead("Three-man moves", "Combinations that open teams up")}${body}<p class="at-note">A passes to B, B passes to C, inside one possession. Threat counts all three players' actions in the move.</p>`;
}

/* ---------- actions / map / zones ---------- */
function renderActions(report) {
  const actions = report.detail?.actions || [];
  const max = Math.max(...actions.map((row) => row.share), 1);
  const body = actions.length ? `<div class="at-table-wrap"><table><thead><tr><th>Action</th><th>Share of our threat</th><th>Per game</th><th>Count</th><th>League rank</th><th>League avg /g</th><th>Vs league</th></tr></thead><tbody>${actions.map((row) => {
    const vs = row.leaguePerGame == null ? null : Number(row.perGame) - Number(row.leaguePerGame);
    return `<tr><td><span class="at-dot" style="background:${row.color}"></span>${escapeHtml(row.label)}</td><td><span class="at-cellbar" style="width:${Math.max(3, (row.share / max) * 120).toFixed(0)}px;background:${row.color}"></span>${row.share}%</td><td>${fmt(row.perGame)}</td><td>${row.count}</td><td>${row.rank ? rankChip(row.rank, row.of) : report.scope === "season" ? "…" : "—"}</td><td>${row.leaguePerGame == null ? "—" : fmt(row.leaguePerGame)}</td><td class="${vs == null ? "" : vs >= 0 ? "at-up" : "at-down"}">${vs == null ? "—" : `${vs >= 0 ? "+" : ""}${fmt(vs)}`}</td></tr>`;
  }).join("")}</tbody></table></div>` : `<p class="at-empty">No threatening actions in this window.</p>`;
  $("actionPanel").innerHTML = `${panelHead("How the ball creates it", "Threat by action")}${body}<p class="at-note">Positive packing threat only — a low cross and a low pass are separate. Green ranks are top quarter of League Two, red bottom quarter.</p>`;
}
function renderMap(report) {
  const passes = report.detail?.passes || [];
  const families = ["all", ...new Set(passes.map((row) => row.family))];
  const players = [...new Set(passes.map((row) => row.player).filter(Boolean))].sort();
  const chips = families.map((family) => `<button type="button" class="at-toggle__btn${state.family === family ? " at-toggle__btn--active" : ""}" data-family="${escapeHtml(family)}">${escapeHtml(FAMILY_LABELS[family] || family)}</button>`).join("");
  const shown = passes.filter((row) => (state.family === "all" || row.family === state.family) && (state.mapPlayer === "all" || row.player === state.mapPlayer) && Number(row.pxt) >= state.minPxt);
  const max = Math.max(...shown.map((row) => Number(row.pxt) || 0), 0.05);
  const colors = Object.values(FAMILY_COLORS);
  const lines = shown.map((row, i) => {
    const a = toSvg(row.x1, row.y1); const b = toSvg(row.x2, row.y2);
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const idx = Math.max(0, colors.indexOf(row.color));
    const title = `${row.label} · ${fmt(row.pxt, 3)} · ${row.player || ""}${row.opponent ? ` vs ${row.opponent}` : ""}`;
    return `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${row.color || "#34d399"}" stroke-width="${(1.6 + (Number(row.pxt) / max) * 6).toFixed(1)}" stroke-linecap="round" opacity="0.9" marker-end="url(#{id}a${idx})" class="at-draw" style="--len:${len.toFixed(0)};animation-delay:${Math.min(i * 12, 700)}ms"><title>${escapeHtml(title)}</title></line><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="3.5" fill="${row.color}"/>`;
  }).join("");
  const playerSelect = `<select id="mapPlayer" class="at-select" style="min-width:180px"><option value="all">All players</option>${players.map((name) => `<option value="${escapeHtml(name)}"${state.mapPlayer === name ? " selected" : ""}>${escapeHtml(name)}</option>`).join("")}</select>`;
  $("mapPanel").innerHTML = `${panelHead("Where the threatening actions travel", "Threat map")}<div class="at-map-tools"><div class="at-toggle">${chips}</div>${playerSelect}<label>Min threat <input id="minPxt" type="range" min="0.02" max="0.4" step="0.01" value="${state.minPxt}" /> <b>${fmt(state.minPxt, 2)}</b></label></div>${pitch(lines, "Threatening actions, attacking to the right", arrowDefs(colors))}<p class="at-note">${shown.length} actions. Thicker arrows add more threat. Hover any arrow for player and opponent.</p>`;
  $("minPxt").addEventListener("change", (event) => { state.minPxt = Number(event.target.value); renderMap(report); });
  $("mapPlayer").addEventListener("change", (event) => { state.mapPlayer = event.target.value; renderMap(report); });
  $("mapPanel").querySelectorAll("[data-family]").forEach((button) => button.addEventListener("click", () => { state.family = button.dataset.family; renderMap(report); }));
}
function renderZones(report) {
  const zones = report.detail?.zones || { start: [], end: [] };
  const side = state.zoneSide === "start" ? zones.start : zones.end;
  const max = Math.max(...side.map((row) => Number(row.total) || 0), 0.01);
  const bubbles = side.filter((row) => row.x != null).map((row, i) => {
    const point = toSvg(row.x, row.y);
    const radius = 18 + (Number(row.total) / max) * 50;
    return `<g class="at-pop" style="animation-delay:${i * 60}ms"><circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="${radius.toFixed(1)}" fill="rgba(245,197,24,${(0.25 + (Number(row.total) / max) * 0.6).toFixed(2)})" stroke="#ffe27a" stroke-width="2"/><text x="${point.x.toFixed(1)}" y="${(point.y - 2).toFixed(1)}" text-anchor="middle" fill="#0b0f15" font-size="15" font-weight="800" font-family="Manrope">${escapeHtml(row.share)}%</text><text x="${point.x.toFixed(1)}" y="${(point.y + 15).toFixed(1)}" text-anchor="middle" fill="#0b0f15" font-size="11" font-weight="700" font-family="Manrope">${escapeHtml(row.label)}</text></g>`;
  }).join("");
  const list = side.slice(0, 6).map((row, i) => barRow(row.label, row.share, `${fmt(row.perGame)}/g · ${row.share}%`, "linear-gradient(90deg,#f59e0b,#f5c518)", i * 50)).join("");
  $("zonePanel").innerHTML = `${panelHead("Where on the pitch", "Threat zones")}<div class="at-map-tools"><div class="at-toggle"><button type="button" class="at-toggle__btn${state.zoneSide === "start" ? " at-toggle__btn--active" : ""}" data-zone="start">Where it starts</button><button type="button" class="at-toggle__btn${state.zoneSide === "end" ? " at-toggle__btn--active" : ""}" data-zone="end">Where it arrives</button></div></div>${pitch(bubbles, "Threat by zone, attacking to the right")}${list || `<p class="at-empty">No zone threat in this window.</p>`}`;
  $("zonePanel").querySelectorAll("[data-zone]").forEach((button) => button.addEventListener("click", () => { state.zoneSide = button.dataset.zone; renderZones(report); }));
}

/* ---------- players / league ---------- */
function renderPlayers(report) {
  const rows = report.detail?.players || [];
  const top = Math.max(...rows.map((row) => row.total), 0.01);
  const body = rows.length ? `<div class="at-players">${rows.slice(0, 18).map((row, i) => `
    <article class="at-player" style="animation:at-rise .5s both;animation-delay:${i * 40}ms">
      <div class="at-player__top"><span class="at-player__name">${escapeHtml(row.name)}</span><span class="at-player__rank">#${i + 1}</span></div>
      <div class="at-player__big">${fmt(row.perGame, 3)} <small>threat / game · ${row.count} actions</small></div>
      <div class="at-bar" style="margin-top:.4rem"><span style="width:${(row.total / top) * 100}%;background:linear-gradient(90deg,#f59e0b,#f5c518)"></span></div>
      <div class="at-player__grid">
        <div><b>${fmt(row.total, 2)}</b><span>Created</span></div>
        <div><b>${fmt(row.received, 2)}</b><span>Received</span></div>
        <div><b>${row.chains ?? "—"}</b><span>Dangerous chains</span></div>
        <div><b>${row.shotChains ?? "—"}</b><span>Ended in shot</span></div>
        <div><b>${row.goalChains ?? "—"}</b><span>Ended in goal</span></div>
        <div><b>${row.share != null ? `${row.share}%` : "—"}</b><span>Team share</span></div>
      </div>
      ${row.partners?.length ? `<div class="at-player__partners">Best link → ${row.partners.map((p) => `<b>${escapeHtml(p.name)}</b> (${fmt(p.total, 2)})`).join(", ")}</div>` : ""}
    </article>`).join("")}</div>` : `<p class="at-empty">No player threat in this window.</p>`;
  $("playerPanel").innerHTML = `${panelHead("Who adds it", "Player threat profiles")}${body}<p class="at-note">Created is threat from the player's own actions. Received is threat from passes played to them. Dangerous chains are possessions worth 0.1+ threat or ending in a shot that they touched.</p>`;
}
const TABLE_COLS = [
  { key: "attack", label: "Threat / g", tip: "Impect attacking threat per game", main: true },
  { key: "cross", label: "Cross threat / g", tip: "Threat added by crosses per game", cross: true },
  { key: "crossCount", label: "Threatening crosses / g", tip: "Crosses that added threat, per game", cross: true, digits: 1 },
  { key: "pass", label: "Pass" },
  { key: "dribble", label: "Dribble" },
  { key: "shot", label: "Shot" },
  { key: "setPiece", label: "Set piece" },
  { key: "ballWin", label: "Ball win" },
];
function heat(value, min, max) {
  if (value == null || !Number.isFinite(Number(value)) || max <= min) return "";
  const t = (Number(value) - min) / (max - min);
  const hue = Math.round(t * 140);
  return `background:hsla(${hue},70%,45%,${(0.08 + Math.abs(t - 0.5) * 0.36).toFixed(2)})`;
}
function renderTable(report) {
  const rows = [...(report.table || [])];
  const hasCross = rows.some((row) => row.cross != null);
  const cols = TABLE_COLS.filter((col) => !col.cross || hasCross);
  const sortKey = state.tableSort || "attack";
  rows.sort((a, b) => (Number(b[sortKey]) || -99) - (Number(a[sortKey]) || -99));
  const ranges = Object.fromEntries(cols.map((col) => {
    const values = rows.map((row) => Number(row[col.key])).filter(Number.isFinite);
    return [col.key, [Math.min(...values), Math.max(...values)]];
  }));
  const vale = rows.find((row) => row.focus) || {};
  const valeRank = (key) => {
    const ordered = [...rows].sort((a, b) => (Number(b[key]) || -99) - (Number(a[key]) || -99));
    const index = ordered.findIndex((row) => row.focus);
    return index >= 0 ? index + 1 : null;
  };
  const head = cols.map((col) => `<th class="at-lt__sort${sortKey === col.key ? " is-sorted" : ""}${col.cross ? " at-lt__cross" : ""}" data-sort="${col.key}" title="${escapeHtml(col.tip || col.label)}">${escapeHtml(col.label)}${sortKey === col.key ? " ▾" : ""}<small>${vale.club ? rankChip(valeRank(col.key), rows.length) : ""}</small></th>`).join("");
  const body = rows.map((row, i) => `<tr class="${row.focus ? "at-focus" : ""}">
    <td class="at-lt__pos">${i + 1}</td>
    <td><span class="at-lt__club"><span class="at-lt__crest">${badgeHtml(row, 26)}</span>${escapeHtml(row.club)}</span></td>
    ${cols.map((col) => {
      const [min, max] = ranges[col.key];
      const value = row[col.key];
      if (col.main) return `<td class="at-lt__main"><span class="at-cellbar" style="width:${max > 0 ? Math.max(4, (Number(value) / max) * 110).toFixed(0) : 4}px;background:${row.focus ? "#f5c518" : "#56657a"}"></span>${fmt(value)}</td>`;
      return `<td style="${heat(value, min, max)}">${value == null ? "—" : fmt(value, col.digits ?? 2)}</td>`;
    }).join("")}
    <td>${row.played}</td></tr>`).join("");
  $("tablePanel").innerHTML = `${panelHead("League Two", "Attacking threat table")}
    <p class="at-lt__lede">Every League Two side. Click a column to sort by it. Green cells are strong for that column, red weak. The chip under each heading is Port Vale's rank.</p>
    <div class="at-lt"><table><thead><tr><th>#</th><th>Club</th>${head}<th>Pld</th></tr></thead><tbody>${body}</tbody></table></div>
    <p class="at-note">Threat / g and the five type columns are Impect squad KPIs. Cross columns come from every League Two match saved in the data lake.</p>`;
  $("tablePanel").querySelectorAll("[data-sort]").forEach((th) => th.addEventListener("click", () => { state.tableSort = th.dataset.sort; renderTable(report); }));
}

/* ---------- render ---------- */
function renderEmpty(report) {
  const building = Boolean(report.progress);
  const message = report.message || "Nothing is saved in the data lake for this view yet.";
  document.body.classList.add("at-is-empty");
  $("hero").innerHTML = `<div class="at-hero__empty"><h2>${building ? "Saving to the data lake" : "Not in the data lake yet"}</h2><p>${escapeHtml(message)}</p>${building ? `<div class="at-skel" style="width:60%"></div><div class="at-skel" style="width:40%"></div>` : ""}</div>`;
  setStatus(building ? "Checking the data lake again every 20 seconds." : "Reading the data lake.");
  clearTimeout(lakeTimer);
  if (building) lakeTimer = setTimeout(() => { loadFixtures().then(loadReport).catch(() => {}); }, 20000);
}
function render(report) {
  state.report = report;
  clearTimeout(lakeTimer);
  if (report.ready === false) { renderEmpty(report); return; }
  document.body.classList.remove("at-is-empty");
  if (!(report.chains?.top || []).some((chain) => chain.id === state.chainId)) state.chainId = null;
  const steps = [renderHero, renderStrip, renderInsights, renderComponents, renderPhases, renderChainSummary, renderPatterns, renderExplorer, renderOrigins, renderLengths, renderNetwork, renderPairs, renderMatrix, renderTrios, renderActions, renderMap, renderZones, renderPlayers, renderTable];
  steps.forEach((fn) => { try { fn(report); } catch (err) { console.error(fn.name, err); } });
  applyNetFocus();
  setStatus(`${report.competition || "League Two"} ${report.season || ""} · ${report.matchCount || 0} Port Vale matches in this window · read from the data lake${report.generatedAt ? ` · saved ${new Date(report.generatedAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}.`);
}
async function loadReport() {
  setStatus("Reading the data lake…");
  const params = new URLSearchParams({ season: state.season, scope: state.scope });
  if (state.scope === "match" && state.matchId) params.set("matchId", String(state.matchId));
  render(await getJson(`/api/attacking-threat/report?${params.toString()}`));
}
async function loadFixtures() {
  const payload = await getJson(`/api/attacking-threat/fixtures?season=${encodeURIComponent(state.season)}`);
  state.fixtures = payload.fixtures || [];
  if (!state.matchId || !state.fixtures.some((row) => row.matchId === state.matchId)) state.matchId = payload.defaultMatchId;
  renderFixtures();
}
function bindNav() {
  const links = [...document.querySelectorAll("#sectionNav a")];
  const sections = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((link) => link.classList.toggle("is-active", link.getAttribute("href") === `#${entry.target.id}`));
    });
  }, { rootMargin: "-30% 0px -60% 0px" });
  sections.forEach((section) => observer.observe(section));
}
function bindControls() {
  document.querySelectorAll("[data-scope]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.scope = button.dataset.scope;
      document.querySelectorAll("[data-scope]").forEach((item) => item.classList.toggle("at-toggle__btn--active", item === button));
      $("matchSelectGroup").hidden = state.scope !== "match";
      try { await loadReport(); } catch (err) { setStatus(err.message); }
    });
  });
  $("seasonToggle").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-season]");
    if (!button) return;
    state.season = button.dataset.season; state.matchId = null; state.mapPlayer = "all";
    renderSeasons({ seasons: [...$("seasonToggle").querySelectorAll("[data-season]")].map((item) => ({ value: item.dataset.season, label: item.textContent })) });
    try { await loadFixtures(); await loadReport(); } catch (err) { setStatus(err.message); }
  });
  $("matchSelect").addEventListener("change", async () => {
    state.matchId = Number($("matchSelect").value);
    try { await loadReport(); } catch (err) { setStatus(err.message); }
  });
}
async function boot() {
  bindControls();
  bindNav();
  try {
    const meta = await getJson("/api/attacking-threat/meta");
    state.season = meta.defaultSeason || (meta.seasons[0] && meta.seasons[0].value) || "";
    renderSeasons(meta);
    await loadFixtures();
    await loadReport();
  } catch (err) { setStatus(err.message || "Attacking threat could not load."); }
}
boot();
