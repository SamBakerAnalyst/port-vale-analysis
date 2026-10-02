const state = {
  season: "", scope: "season", matchId: null, fixtures: [], report: null,
  side: "us", layer: "bw", mode: "zones", player: "all", zone: null,
  unit: "all", sort: "bwTotal", tableSort: "bwd",
};
const $ = (id) => document.getElementById(id);
const P = { SIDE: 0, KIND: 1, TYPE: 2, PLAYER: 3, X: 4, Y: 5, OI: 6, DI: 7, BWD: 8, MATCH: 9 };
const LAYERS = [
  { id: "bw", label: "Ball wins", color: "#f5c518", digits: 1, note: "Every ball win — loose balls, interceptions, duels, blocks." },
  { id: "oi", label: "Offensive int.", color: "#f97316", digits: 1, note: "Offensive interventions: opponents taken out of the game when we win it. Bigger = more opponents behind the ball." },
  { id: "di", label: "Defensive int.", color: "#60a5fa", digits: 1, note: "Defensive interventions: team-mates put back behind the ball when we win it. High numbers deep usually mean we are defending a lot." },
  { id: "bwd", label: "vs defenders", color: "#e11d48", digits: 2, note: "Ball wins that take opposition defenders out — the regain most linked to winning League Two games." },
  { id: "dw", label: "Duels won", color: "#34d399", digits: 1, note: "Ground and aerial duels won.", duel: true },
  { id: "dl", label: "Duels lost", color: "#f87171", digits: 1, note: "Ground and aerial duels lost.", duel: true },
];
const THIRDS = [["D", "Defensive third", -52.5, -17.5], ["M", "Middle third", -17.5, 17.5], ["F", "Final third", 17.5, 52.5]];
const LANES = [["L", "left wing", 20.16, 34], ["LH", "left half-space", 9.16, 20.16], ["C", "centre", -9.16, 9.16], ["RH", "right half-space", -20.16, -9.16], ["R", "right wing", -34, -20.16]];
const UNIT_LABELS = { DEF: "Defenders", MID: "Midfielders", ATT: "Forwards", GK: "Goalkeeper" };
let lakeTimer = null;
let svgSeq = 0;

/* ---------- utils ---------- */
function escapeHtml(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function num(value) { if (value == null || value === "") return null; const n = Number(value); return Number.isFinite(n) ? n : null; }
function fmt(value, digits = 1) { const n = num(value); return n == null ? "—" : n.toFixed(digits); }
function pct(value) { const n = num(value); return n == null ? "—" : `${n.toFixed(0)}%`; }
function setStatus(text) { $("statusBar").textContent = text; }
function panelHead(kicker, title, extra = "") { return `<div class="at-panel__head"><p class="at-panel__kicker">${escapeHtml(kicker)}</p><h2 class="at-panel__title">${escapeHtml(title)}</h2>${extra}</div>`; }
function rankTier(rank, of) {
  if (!rank) return "none";
  const size = Number(of) || 24;
  if (rank <= Math.ceil(size / 4)) return "t1";
  if (rank <= Math.ceil(size / 2)) return "t2";
  if (rank <= Math.ceil((size * 3) / 4)) return "t3";
  return "t4";
}
function rankChip(rank, of, prefix = "") { return rank ? `<span class="at-rank at-rank--${rankTier(rank, of)}" title="Season rank in League Two (1 is best)">${prefix}${rank} of ${of || 24}</span>` : ""; }
function resultChip(result) { return `<span class="at-res at-res--${result || "x"}">${result || "–"}</span>`; }
async function getJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (body.detail) detail = String(body.detail); } catch (_err) {}
    throw new Error(detail);
  }
  return response.json();
}
function countUp(root) {
  root.querySelectorAll("[data-count]").forEach((el) => {
    const target = Number(el.dataset.count);
    const digits = Number(el.dataset.digits || 0);
    const suffix = el.dataset.suffix || "";
    if (!Number.isFinite(target)) return;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 900);
      el.textContent = (target * (1 - Math.pow(1 - t, 3))).toFixed(digits) + suffix;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}
function heat(value, min, max, higher = true) {
  const n = num(value);
  if (n == null || max <= min) return "";
  let t = (n - min) / (max - min);
  if (!higher) t = 1 - t;
  const hue = Math.round(t * 130);
  return `background:hsla(${hue},70%,45%,0.22)`;
}
function badgeHtml(row, size = 26) {
  if (row.badge) return `<img src="${escapeHtml(row.badge)}" alt="" width="${size}" height="${size}" loading="lazy">`;
  return `<span class="at-crest__alt">${escapeHtml(String(row.club || "?").slice(0, 3).toUpperCase())}</span>`;
}

/* ---------- pitch ---------- */
function toSvg(x, y) { return { x: ((Number(x) + 52.5) / 105) * 1050, y: ((34 - Number(y)) / 68) * 680 }; }
function pitch(inner, label, under = "") {
  const id = `p${++svgSeq}`;
  const stripes = Array.from({ length: 10 }, (_, i) => `<rect x="${i * 105}" y="0" width="105" height="680" fill="${i % 2 ? "#123222" : "#143826"}"/>`).join("");
  const line = "rgba(226,245,233,0.55)";
  return `<svg class="at-pitch" viewBox="0 0 1050 680" role="img" aria-label="${escapeHtml(label)}">
    <defs><radialGradient id="${id}v" cx="50%" cy="50%" r="75%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity="0.45"/></radialGradient></defs>
    ${stripes}<rect width="1050" height="680" fill="url(#${id}v)"/>
    ${under}
    <g fill="none" stroke="${line}" stroke-width="2.5" pointer-events="none">
      <rect x="8" y="8" width="1034" height="664" rx="2"/><line x1="525" y1="8" x2="525" y2="672"/><circle cx="525" cy="340" r="70"/>
      <rect x="8" y="186" width="130" height="308"/><rect x="912" y="186" width="130" height="308"/>
      <rect x="8" y="258" width="48" height="164"/><rect x="994" y="258" width="48" height="164"/>
      <path d="M138 290 A70 70 0 0 1 138 390"/><path d="M912 290 A70 70 0 0 0 912 390"/>
    </g>
    <circle cx="525" cy="340" r="4" fill="${line}"/>
    <path d="M960 24 l30 0 m-10 -8 l10 8 l-10 8" stroke="rgba(245,197,24,0.8)" stroke-width="3" fill="none"/>
    <text x="950" y="30" text-anchor="end" fill="rgba(245,197,24,0.8)" font-size="15" font-family="Manrope" font-weight="700">ATTACK</text>
    ${inner}
  </svg>`;
}
function thirdOf(x) { return x < -17.5 ? "D" : x > 17.5 ? "F" : "M"; }
function laneOf(y) { return y > 20.16 ? "L" : y > 9.16 ? "LH" : y < -20.16 ? "R" : y < -9.16 ? "RH" : "C"; }
function zoneOf(x, y) { return `${thirdOf(x)}-${laneOf(y)}`; }
function zoneLabel(id) {
  const [third, lane] = String(id).split("-");
  const t = THIRDS.find((row) => row[0] === third);
  const l = LANES.find((row) => row[0] === lane);
  return `${t ? t[1] : third} · ${l ? l[1] : lane}`;
}

/* ---------- points ---------- */
function kindOf(point) { return state.report.pointKinds[point[P.KIND]]; }
function layerValue(point, layer) {
  const kind = kindOf(point);
  if (layer === "dw") return kind === "gw" || kind === "aw" ? 1 : 0;
  if (layer === "dl") return kind === "gl" || kind === "al" ? 1 : 0;
  if (kind !== "bw") return 0;
  if (layer === "bw") return 1;
  if (layer === "oi") return Number(point[P.OI]) || 0;
  if (layer === "di") return Number(point[P.DI]) || 0;
  if (layer === "bwd") return Number(point[P.BWD]) || 0;
  return 0;
}
function filteredPoints(layer = state.layer) {
  const side = state.side === "them" ? 1 : 0;
  const player = state.player === "all" ? null : Number(state.player);
  return (state.report.points || []).filter((point) => point[P.SIDE] === side
    && (player == null || point[P.PLAYER] === player)
    && layerValue(point, layer) > 0);
}
function divisor() {
  if (state.player !== "all") {
    const row = (state.report.players || []).find((item) => String(item.id) === String(state.player));
    return Math.max(1, Number(row?.games) || 1);
  }
  return Math.max(1, Number(state.report.matchCount) || 1);
}
function zoneTotals(layer = state.layer) {
  const totals = {};
  filteredPoints(layer).forEach((point) => {
    const zone = zoneOf(Number(point[P.X]), Number(point[P.Y]));
    totals[zone] = (totals[zone] || 0) + layerValue(point, layer);
  });
  return totals;
}
function playerName(id) {
  const row = (state.report.players || []).find((item) => Number(item.id) === Number(id));
  return row ? row.name : `Player ${id}`;
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
    const score = row.score ? ` ${row.score}` : "";
    return `<option value="${row.matchId}">${escapeHtml(row.opponent)} (${row.home ? "H" : "A"})${escapeHtml(score)}</option>`;
  }).join("");
  if (state.matchId) $("matchSelect").value = String(state.matchId);
  $("matchSelectGroup").hidden = state.scope !== "match";
}

/* ---------- overview ---------- */
function windowLabel(report) {
  if (report.scope === "season") return `${report.season} season`;
  if (report.scope === "last6") return "last 6 games";
  const fixture = report.fixtures?.[0];
  return fixture ? `vs ${fixture.opponent}${fixture.score ? ` (${fixture.score})` : ""}` : "this match";
}
function renderHero(report) {
  const us = report.us || {};
  const them = report.them || {};
  const league = report.league || {};
  const ranks = league.focus?.ranks || {};
  const of = league.of || 24;
  const avg = league.averages || {};
  const duelDiff = (num(us.duelPct) ?? 0) - (num(them.duelPct) ?? 0);
  const verdict = `We win the ball <b>${fmt(us.bw)}</b> times a game — <b>${fmt(us.high)}</b> of them in their third (${pct(us.highShare)}). `
    + `We win <b class="${duelDiff >= 0 ? "at-up" : "at-down"}">${pct(us.duelPct)}</b> of our duels`
    + (ranks.duelPct ? ` (${ranks.duelPct} of ${of} this season)` : "") + `. `
    + `Ball wins that take out their defenders: <b>${fmt(us.bwd, 2)}</b> a game`
    + (num(avg.bwd) != null ? ` against a League Two average of ${fmt(avg.bwd, 2)}` : "") + ".";
  const tile = (o) => {
    const ours = num(o.us);
    const theirs = num(o.them);
    let tone = "";
    if (ours != null && theirs != null && Math.abs(ours - theirs) > 1e-9) tone = (o.higher === false ? ours < theirs : ours > theirs) ? "good" : "bad";
    const share = ours != null && theirs != null && ours + theirs > 0 ? (ours / (ours + theirs)) * 100 : 50;
    return `<div class="iv-htile${tone ? ` iv-htile--${tone}` : ""}">
      <div class="iv-htile__top"><span class="iv-htile__label">${escapeHtml(o.label)}</span>${rankChip(o.rank, of)}</div>
      <strong data-count="${ours ?? 0}" data-digits="${o.digits}" data-suffix="${o.suffix || ""}">${ours == null ? "—" : ours.toFixed(o.digits) + (o.suffix || "")}</strong>
      <small>Opponents <b>${theirs == null ? "—" : theirs.toFixed(o.digits) + (o.suffix || "")}</b>${o.sub ? ` · ${escapeHtml(o.sub)}` : ""}</small>
      <div class="iv-vs"><i class="iv-vs__us" style="width:${share.toFixed(1)}%"></i><i class="iv-vs__them" style="width:${(100 - share).toFixed(1)}%"></i></div>
    </div>`;
  };
  $("hero").innerHTML = `
    <div class="at-hero__main">
      <p class="at-panel__kicker">League Two ${escapeHtml(report.season || "")} · ${escapeHtml(windowLabel(report))} · ${report.matchCount || 0} games</p>
      <h2 class="at-hero__title">Port Vale · <em>interventions</em></h2>
      <p class="at-hero__verdict">${verdict}</p>
      <p class="at-hero__why">${escapeHtml(report.why || "")}</p>
    </div>
    <div class="iv-htiles">
      ${tile({ label: "Ball wins / game", us: us.bw, them: them.bw, digits: 1, rank: ranks.bw, sub: `${pct(us.deepShare)} in our third` })}
      ${tile({ label: "Final-third regains", us: us.high, them: them.high, digits: 1, sub: "Won in their third" })}
      ${tile({ label: "Ball wins vs defenders", us: us.bwd, them: them.bwd, digits: 2, rank: ranks.bwd, sub: "Their defenders removed" })}
      ${tile({ label: "Offensive interventions", us: us.oi, them: them.oi, digits: 1, rank: ranks.oi, sub: `${fmt(us.oiPerWin, 2)} opponents per win` })}
      ${tile({ label: "Defensive interventions", us: us.di, them: them.di, digits: 1, rank: ranks.di, higher: false, sub: "Lower = less time defending" })}
      ${tile({ label: "Duel win %", us: us.duelPct, them: them.duelPct, digits: 0, suffix: "%", rank: ranks.duelPct, sub: `per game we win ${fmt(us.duelsWon)}, lose ${fmt(them.duelsWon)}` })}
      ${tile({ label: "Aerial win %", us: us.aerialPct, them: them.aerialPct, digits: 0, suffix: "%", rank: ranks.aerialPct, sub: `per game we win ${fmt(us.aerialWon)}, lose ${fmt(them.aerialWon)}` })}
      ${tile({ label: "Ground duel %", us: us.groundPct, them: them.groundPct, digits: 0, suffix: "%", rank: ranks.groundPct, sub: `per game we win ${fmt(us.groundWon)}, lose ${fmt(them.groundWon)}` })}
    </div>`;
  countUp($("hero"));
}
function renderInsights(report) {
  $("insights").innerHTML = (report.insights || []).map((item, i) => `
    <div class="at-insight at-insight--${escapeHtml(item.tone || "info")}" style="animation-delay:${i * 70}ms">
      <h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.text)}</p>
    </div>`).join("");
}

/* ---------- what wins games ---------- */
function renderEvidence(report) {
  const evidence = report.evidence || {};
  const rows = [...(evidence.stats || [])].sort((a, b) => Number(b.r) - Number(a.r));
  const body = rows.map((row, i) => {
    const r = Number(row.r) || 0;
    const width = Math.min(50, Math.abs(r) * 100);
    const left = r >= 0 ? 50 : 50 - width;
    const color = r >= 0 ? "#34d399" : "#f87171";
    return `<div class="iv-ev__row"><span>${escapeHtml(row.label)}</span>
      <span class="iv-ev__track"><i class="iv-ev__bar" style="left:${left}%;width:${width}%;background:${color};animation-delay:${i * 80}ms"></i></span>
      <b style="color:${color}">${r >= 0 ? "+" : "−"}${Math.abs(r).toFixed(2)}</b></div>`;
  }).join("");
  $("evidencePanel").innerHTML = `${panelHead("League Two history", "Linked to winning")}
    <p class="at-section__lede" style="margin:-.4rem 0 .9rem;font-size:.88rem">How strongly each per-game stat tracks win percentage. Right is good, left means more of it goes with losing.</p>
    <div class="iv-ev">${body || '<p class="at-empty">No history saved yet.</p>'}</div>
    <p class="at-note">${escapeHtml(evidence.sample || "")} Same numbers as What Wins Games.</p>`;
}
function battleRows(battles, opts = {}) {
  const usable = (battles || []).filter((row) => row.won.games || row.lost.games);
  if (!usable.length) return `<p class="at-empty">${escapeHtml(opts.empty || "Not enough games yet.")}</p>`;
  return `<div class="iv-battles">${usable.map((row, i) => {
    const gap = num(row.ppgGap);
    const bar = (rec, label, color) => {
      const width = rec.ppg == null ? 0 : (rec.ppg / 3) * 100;
      const meta = rec.games ? (opts.records ? `${rec.w}W ${rec.d}D ${rec.l}L · ${fmt(rec.ppg, 2)}` : `${fmt(rec.ppg, 2)} ppg · ${fmt(rec.winPct, 0)}% W`) : "—";
      return `<div class="iv-battle__bar"><span>${label}</span><span class="at-bar"><span style="width:${width.toFixed(1)}%;background:${color}"></span></span><em>${meta}</em></div>`;
    };
    return `<div class="iv-battle${i === 0 && gap != null && gap > 0 ? " iv-battle--top" : ""}">
      <div class="iv-battle__name">${escapeHtml(row.label)}<small>${escapeHtml(row.hint)}${row.higher ? "" : " · fewer is better"}</small></div>
      <div class="iv-battle__bars">${bar(row.won, "Won it", "linear-gradient(90deg,#16a34a,#34d399)")}${bar(row.lost, "Lost it", "linear-gradient(90deg,#b91c1c,#f87171)")}</div>
      <div class="iv-battle__gap ${gap == null ? "" : gap >= 0 ? "at-up" : "at-down"}">${gap == null ? "—" : `${gap >= 0 ? "+" : "−"}${Math.abs(gap).toFixed(2)}`}<small>points / game</small></div>
    </div>`;
  }).join("")}</div>`;
}
function renderLeagueBattles(report) {
  const lb = report.leagueBattles || {};
  const note = lb.matches ? `${lb.matches} of ${lb.expected} League Two ${report.season} matches. Each match counted from both sides.` : "League-wide battles appear after the next data refresh.";
  $("leagueBattlePanel").innerHTML = `${panelHead(`League Two ${report.season || ""}`, "Win the battle, win the game?")}
    <p class="at-section__lede" style="margin:-.4rem 0 .9rem;font-size:.88rem">Points per game for the side that won each battle in a match, against the side that lost it. Biggest swing at the top.</p>
    ${battleRows(lb.battles, { empty: "League-wide battles appear after the next data refresh." })}
    <p class="at-note">${escapeHtml(note)} Final-third regains are only measured in our own games.</p>`;
}
function renderValeBattles(report) {
  $("valeBattlePanel").innerHTML = `${panelHead("Our games", "Port Vale battles")}
    <p class="at-section__lede" style="margin:-.4rem 0 .9rem;font-size:.88rem">Our record when we won each battle against when we lost it, ${escapeHtml(windowLabel(report))}.</p>
    ${battleRows(report.battles, { records: true, empty: "Needs finished games in this window." })}`;
}
function renderResults(report) {
  const rows = (report.results || []).filter((row) => row.games);
  if (!rows.length) { $("resultsPanel").innerHTML = `${panelHead("Our games", "Wins vs defeats")}<p class="at-empty">No finished games in this window.</p>`; return; }
  const cols = [
    ["bw", "Ball wins", 1, true], ["high", "Final-third regains", 1, true], ["bwd", "vs defenders", 2, true],
    ["oi", "Offensive int.", 1, true], ["di", "Defensive int.", 1, false], ["duelPct", "Duel %", 0, true],
    ["aerialPct", "Aerial %", 0, true], ["groundPct", "Ground %", 0, true],
  ];
  const body = cols.map(([key, label, digits, higher]) => {
    const values = rows.map((row) => num(row[key])).filter((v) => v != null);
    const best = higher ? Math.max(...values) : Math.min(...values);
    const worst = higher ? Math.min(...values) : Math.max(...values);
    return `<tr><td>${label}</td>${rows.map((row) => {
      const v = num(row[key]);
      const cls = values.length > 1 && v === best ? "iv-hi" : values.length > 1 && v === worst ? "iv-lo" : "";
      return `<td class="${cls}">${v == null ? "—" : v.toFixed(digits)}${key.endsWith("Pct") && v != null ? "%" : ""}</td>`;
    }).join("")}</tr>`;
  }).join("");
  $("resultsPanel").innerHTML = `${panelHead("Our games", "What changes when we win")}
    <p class="at-section__lede" style="margin:-.4rem 0 .9rem;font-size:.88rem">Port Vale averages per game in wins, draws and defeats. Green is the best of the three.</p>
    <div class="at-table-wrap"><table class="iv-split"><thead><tr><th>Per game</th>${rows.map((row) => `<th>${row.label} (${row.games})</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/* ---------- pitch ---------- */
function renderMap(report) {
  const layer = LAYERS.find((row) => row.id === state.layer) || LAYERS[0];
  if (state.side === "them" && layer.duel) state.layer = "bw";
  const active = LAYERS.find((row) => row.id === state.layer);
  const games = divisor();
  const totals = zoneTotals();
  const values = Object.values(totals);
  const max = values.length ? Math.max(...values) : 0;
  const sum = values.reduce((a, b) => a + b, 0);
  let inner = "";
  let under = "";
  if (state.mode === "zones") {
    THIRDS.forEach(([third, , x1, x2]) => {
      LANES.forEach(([lane, , y1, y2]) => {
        const id = `${third}-${lane}`;
        const value = totals[id] || 0;
        const a = toSvg(x1, y2);
        const b = toSvg(x2, y1);
        const alpha = max > 0 ? 0.06 + 0.6 * (value / max) : 0.04;
        const share = sum > 0 ? (value / sum) * 100 : 0;
        under += `<g class="iv-zone${state.zone === id ? " is-on" : ""}" data-zone="${id}">
          <rect x="${a.x + 3}" y="${a.y + 3}" width="${b.x - a.x - 6}" height="${b.y - a.y - 6}" rx="8" fill="${active.color}" fill-opacity="${alpha.toFixed(2)}" stroke="rgba(255,255,255,0.12)" stroke-width="1.5"><title>${escapeHtml(zoneLabel(id))}</title></rect>
        </g>`;
        inner += `<g pointer-events="none" font-family="JetBrains Mono, monospace" font-weight="700">
          <text x="${(a.x + b.x) / 2}" y="${(a.y + b.y) / 2 - 2}" text-anchor="middle" fill="#fff" font-size="${b.y - a.y > 90 ? 26 : 20}" paint-order="stroke" stroke="rgba(7,9,13,0.55)" stroke-width="4">${(value / games).toFixed(active.digits)}</text>
          <text x="${(a.x + b.x) / 2}" y="${(a.y + b.y) / 2 + 20}" text-anchor="middle" fill="rgba(255,255,255,0.8)" font-size="14" paint-order="stroke" stroke="rgba(7,9,13,0.55)" stroke-width="3">${share.toFixed(0)}%</text>
        </g>`;
      });
    });
  } else {
    const points = filteredPoints();
    const colors = report.typeColors || {};
    inner = points.map((point) => {
      const { x, y } = toSvg(point[P.X], point[P.Y]);
      const kind = kindOf(point);
      const type = point[P.TYPE] >= 0 ? report.pointTypes[point[P.TYPE]] : kind;
      let color = active.color;
      if (state.layer === "bw") color = colors[type] || "#94a3b8";
      if (state.layer === "dw" || state.layer === "dl") color = kind.startsWith("a") ? "#38bdf8" : (state.layer === "dw" ? "#34d399" : "#f87171");
      const value = layerValue(point, state.layer);
      const r = state.layer === "bw" || active.duel ? 6 : Math.min(15, 4 + value * 2.2);
      const fixture = report.fixtures?.[point[P.MATCH]];
      const label = `${playerName(point[P.PLAYER])} · ${(report.typeLabels || {})[type] || type.toUpperCase()}${fixture ? ` · vs ${fixture.opponent}` : ""}`;
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}" fill-opacity="0.72" stroke="#0b0f15" stroke-width="1"><title>${escapeHtml(state.side === "them" ? `${fixture ? fixture.opponent : "Opponent"} · ${(report.typeLabels || {})[type] || type}` : label)}</title></circle>`;
    }).join("");
  }
  const thirdTotals = THIRDS.map(([third, label]) => {
    const value = Object.entries(totals).filter(([id]) => id.startsWith(`${third}-`)).reduce((a, [, v]) => a + v, 0);
    return { label, value, share: sum > 0 ? (value / sum) * 100 : 0 };
  });
  const players = [...(report.players || [])].sort((a, b) => a.name.localeCompare(b.name));
  const typeKey = state.layer === "bw" && state.mode === "dots" && state.side === "us" ? Object.entries(report.typeColors || {})
    .filter(([key]) => !key.startsWith("GK_SAVE"))
    .map(([key, color]) => `<span class="at-key__item"><i class="at-key__dot" style="background:${color};color:${color}"></i>${escapeHtml((report.typeLabels || {})[key] || key)}</span>`).join("") : "";
  $("mapPanel").innerHTML = `${panelHead(state.side === "them" ? "Where opponents win it off us" : "Where we win it", active.label + (state.player !== "all" ? ` · ${playerName(state.player)}` : ""))}
    <div class="iv-tools">
      <div class="at-toggle" data-group="side">
        <button type="button" class="at-toggle__btn${state.side === "us" ? " at-toggle__btn--active" : ""}" data-side="us">Port Vale</button>
        <button type="button" class="at-toggle__btn${state.side === "them" ? " at-toggle__btn--active" : ""}" data-side="them">Opponents</button>
      </div>
      <div class="at-toggle" data-group="layer">${LAYERS.filter((row) => !(row.duel && state.side === "them")).map((row) => `<button type="button" class="at-toggle__btn${row.id === state.layer ? " at-toggle__btn--active" : ""}" data-layer="${row.id}">${row.label}</button>`).join("")}</div>
      <div class="at-toggle" data-group="mode">
        <button type="button" class="at-toggle__btn${state.mode === "zones" ? " at-toggle__btn--active" : ""}" data-mode="zones">Zones</button>
        <button type="button" class="at-toggle__btn${state.mode === "dots" ? " at-toggle__btn--active" : ""}" data-mode="dots">Every action</button>
      </div>
      ${state.side === "us" ? `<select class="at-select" id="mapPlayer" aria-label="Player"><option value="all">All players</option>${players.map((row) => `<option value="${row.id}"${String(row.id) === String(state.player) ? " selected" : ""}>${escapeHtml(row.name)}</option>`).join("")}</select>` : ""}
    </div>
    <div class="iv-pitch-wrap">${pitch(inner, `${active.label} pitch map`, under)}</div>
    <div class="iv-thirds">${thirdTotals.map((row) => `<div class="iv-third"><b>${(row.value / games).toFixed(active.digits)}</b><span>${row.label} · ${row.share.toFixed(0)}%</span></div>`).join("")}</div>
    ${typeKey ? `<div class="at-key">${typeKey}</div>` : ""}
    <p class="at-note">${escapeHtml(active.note)} Numbers are per game${state.player !== "all" ? ` across ${games} appearances` : ""}.</p>`;
  bindMap();
  renderZonePanel(report);
}
function bindMap() {
  const panel = $("mapPanel");
  panel.querySelectorAll("[data-side]").forEach((btn) => btn.addEventListener("click", () => { state.side = btn.dataset.side; if (state.side === "them") state.player = "all"; renderMap(state.report); }));
  panel.querySelectorAll("[data-layer]").forEach((btn) => btn.addEventListener("click", () => { state.layer = btn.dataset.layer; renderMap(state.report); }));
  panel.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => { state.mode = btn.dataset.mode; renderMap(state.report); }));
  panel.querySelectorAll("[data-zone]").forEach((g) => g.addEventListener("click", () => { state.zone = g.dataset.zone; renderMap(state.report); }));
  const select = $("mapPlayer");
  if (select) select.addEventListener("change", () => { state.player = select.value; renderMap(state.report); renderPlayers(state.report); });
}
function renderZonePanel(report) {
  const totals = zoneTotals();
  const ranked = Object.entries(totals).sort((a, b) => b[1] - a[1]);
  if (!state.zone || !(state.zone in totals)) state.zone = ranked[0]?.[0] || null;
  const games = divisor();
  const active = LAYERS.find((row) => row.id === state.layer) || LAYERS[0];
  if (!state.zone) { $("zonePanel").innerHTML = `${panelHead("Zone", "No actions")}<p class="at-empty">Nothing in this view.</p>`; return; }
  const inZone = (point) => zoneOf(Number(point[P.X]), Number(point[P.Y])) === state.zone;
  const side = state.side === "them" ? 1 : 0;
  const player = state.player === "all" ? null : Number(state.player);
  const base = (report.points || []).filter((point) => point[P.SIDE] === side && (player == null || point[P.PLAYER] === player) && inZone(point));
  const sumLayer = (layer) => base.reduce((a, point) => a + layerValue(point, layer), 0);
  const won = sumLayer("dw");
  const lost = sumLayer("dl");
  const stats = [
    ["Ball wins / g", (sumLayer("bw") / games).toFixed(1)],
    ["Offensive int. / g", (sumLayer("oi") / games).toFixed(1)],
    ["vs defenders / g", (sumLayer("bwd") / games).toFixed(2)],
    ["Defensive int. / g", (sumLayer("di") / games).toFixed(1)],
    ["Duels won–lost", side ? "—" : `${won}–${lost}`],
    ["Duel win %", side || won + lost === 0 ? "—" : `${Math.round((won / (won + lost)) * 100)}%`],
  ];
  const byPlayer = {};
  base.forEach((point) => {
    const value = layerValue(point, state.layer);
    if (value > 0) byPlayer[point[P.PLAYER]] = (byPlayer[point[P.PLAYER]] || 0) + value;
  });
  const top = Object.entries(byPlayer).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const topSum = top.reduce((a, [, v]) => a + v, 0) || 1;
  const rankList = ranked.slice(0, 5).map(([id, value], i) => `<div class="iv-zlist__row" data-zone-pick="${id}" style="cursor:pointer"><span class="iv-zlist__n">${i + 1}</span><span>${escapeHtml(zoneLabel(id))}</span><b>${(value / games).toFixed(active.digits)}</b></div>`).join("");
  $("zonePanel").innerHTML = `${panelHead("Selected zone", zoneLabel(state.zone))}
    <div class="iv-zone-detail">
      <div class="iv-zstats">${stats.map(([label, value]) => `<div><b>${value}</b><span>${label}</span></div>`).join("")}</div>
      ${side === 0 && state.player === "all" ? `<p class="at-panel__kicker" style="margin-bottom:.4rem">Who — ${escapeHtml(active.label.toLowerCase())} here</p>
      <div class="iv-zlist">${top.map(([id, value], i) => `<div class="iv-zlist__row"><span class="iv-zlist__n">${i + 1}</span><span>${escapeHtml(playerName(id))}</span><b>${active.digits > 1 ? value.toFixed(1) : Math.round(value)} <small style="color:var(--muted)">${Math.round((value / topSum) * 100)}%</small></b></div>`).join("") || '<p class="at-empty">Nobody here.</p>'}</div>` : ""}
      <p class="at-panel__kicker" style="margin:1rem 0 .4rem">Busiest zones · ${escapeHtml(active.label.toLowerCase())}</p>
      <div class="iv-zlist">${rankList}</div>
    </div>`;
  $("zonePanel").querySelectorAll("[data-zone-pick]").forEach((row) => row.addEventListener("click", () => { state.zone = row.dataset.zonePick; renderMap(state.report); }));
}

/* ---------- players ---------- */
const PLAYER_COLS = [
  { key: "games", label: "Gms", digits: 0 },
  { key: "bwTotal", label: "Ball wins", digits: 0 },
  { key: "bw", label: "BW / g", digits: 1 },
  { key: "highTotal", label: "Final 3rd", digits: 0, tip: "Ball wins in their third" },
  { key: "oiTotal", label: "Off. int.", digits: 1, tip: "Offensive interventions" },
  { key: "diTotal", label: "Def. int.", digits: 1, tip: "Defensive interventions" },
  { key: "bwdTotal", label: "vs Def", digits: 1, tip: "Ball wins vs defenders" },
  { key: "duelsTotal", label: "Duels", digits: 0 },
  { key: "duelPct", label: "Duel %", digits: 0, pct: true },
  { key: "aerialPct", label: "Aerial %", digits: 0, pct: true },
  { key: "groundPct", label: "Ground %", digits: 0, pct: true },
];
function renderPlayers(report) {
  const all = report.players || [];
  const rows = all.filter((row) => state.unit === "all" || row.unit === state.unit)
    .sort((a, b) => (num(b[state.sort]) ?? -1) - (num(a[state.sort]) ?? -1));
  const ranges = Object.fromEntries(PLAYER_COLS.map((col) => {
    const values = rows.map((row) => num(row[col.key])).filter((v) => v != null);
    return [col.key, [Math.min(...values), Math.max(...values)]];
  }));
  const units = ["all", "DEF", "MID", "ATT", "GK"].filter((unit) => unit === "all" || all.some((row) => row.unit === unit));
  $("playerPanel").innerHTML = `${panelHead("Which players", "Ball winners and duellists")}
    <div class="iv-ptools">
      <div class="at-toggle">${units.map((unit) => `<button type="button" class="at-toggle__btn${state.unit === unit ? " at-toggle__btn--active" : ""}" data-unit="${unit}">${unit === "all" ? "All" : UNIT_LABELS[unit]}</button>`).join("")}</div>
      <span class="at-note" style="margin:0">Click a column to sort. Click a player to see where they win it on the pitch.</span>
    </div>
    <div class="at-table-wrap"><table class="iv-ptable"><thead><tr><th>#</th><th>Player</th><th>Unit</th>
      ${PLAYER_COLS.map((col) => `<th data-sort="${col.key}" class="${state.sort === col.key ? "is-sorted" : ""}" title="${escapeHtml(col.tip || col.label)}">${col.label}${state.sort === col.key ? " ▾" : ""}</th>`).join("")}<th>Main zone</th></tr></thead>
      <tbody>${rows.map((row, i) => `<tr data-player="${row.id}" class="${String(row.id) === String(state.player) ? "is-on" : ""}"><td>${i + 1}</td><td>${escapeHtml(row.name)}</td><td><span class="iv-unit iv-unit--${row.unit}">${escapeHtml(row.unit)}</span></td>
        ${PLAYER_COLS.map((col) => { const [lo, hi] = ranges[col.key]; const v = num(row[col.key]); return `<td><span class="iv-heat" style="${col.key === "games" ? "" : heat(v, lo, hi)}">${v == null ? "—" : v.toFixed(col.digits)}${col.pct && v != null ? "%" : ""}</span></td>`; }).join("")}
        <td style="font-family:var(--font);font-size:.8rem;color:var(--muted)">${escapeHtml(row.topZoneLabel || "—")}</td></tr>`).join("")}</tbody></table></div>
    <p class="at-note">Totals for the window. Games = appearances in the event data. Duel % needs a few duels before it means much.</p>`;
  $("playerPanel").querySelectorAll("[data-unit]").forEach((btn) => btn.addEventListener("click", () => { state.unit = btn.dataset.unit; renderPlayers(state.report); }));
  $("playerPanel").querySelectorAll("[data-sort]").forEach((th) => th.addEventListener("click", () => { state.sort = th.dataset.sort; renderPlayers(state.report); }));
  $("playerPanel").querySelectorAll("[data-player]").forEach((tr) => tr.addEventListener("click", () => {
    state.player = String(tr.dataset.player) === String(state.player) ? "all" : tr.dataset.player;
    state.side = "us";
    renderPlayers(state.report);
    renderMap(state.report);
    if (state.player !== "all") document.getElementById("pitch").scrollIntoView({ behavior: "smooth" });
  }));
}

/* ---------- units / types / periods ---------- */
function renderUnits(report) {
  const us = report.units?.us || [];
  const them = Object.fromEntries((report.units?.them || []).map((row) => [row.id, row]));
  const def = us.find((row) => row.id === "DEF");
  $("unitPanel").innerHTML = `${panelHead("By unit", "Who wins it back")}
    ${def ? `<p class="at-section__lede" style="margin:-.4rem 0 .8rem;font-size:.88rem">Our defenders make <b style="color:var(--gold)">${pct(def.share)}</b> of our ball wins (opponents' defenders ${pct(them.DEF?.share)}).</p>` : ""}
    <div class="iv-unitcard">${us.map((row) => `<div class="iv-unitrow">
      <div class="iv-unitrow__top"><span class="iv-unit iv-unit--${row.id}">${escapeHtml(row.label)}</span><b>${fmt(row.bw)} <small style="color:var(--muted);font:500 .72rem var(--font)">ball wins / g</small></b></div>
      <div class="at-bar" style="margin-top:.45rem"><span style="width:${row.share}%;background:linear-gradient(90deg,#f59e0b,#ffe27a)"></span></div>
      <div class="iv-unitrow__stats"><span><b>${pct(row.share)}</b> of ours</span><span>Their 3rd <b>${fmt(row.high)}</b></span><span>Off. int. <b>${fmt(row.oi)}</b></span><span>vs Def <b>${fmt(row.bwd, 2)}</b></span><span>Duels <b>${pct(row.duelPct)}</b></span><span>Opp ${escapeHtml(row.label.toLowerCase())} <b>${fmt(them[row.id]?.bw)}</b></span></div>
    </div>`).join("")}</div>`;
}
function renderTypes(report) {
  const us = report.types?.us || [];
  const them = Object.fromEntries((report.types?.them || []).map((row) => [row.id, row]));
  const max = Math.max(1, ...us.map((row) => Number(row.perGame) || 0));
  $("typePanel").innerHTML = `${panelHead("How", "How we win it")}
    ${us.map((row, i) => `<div class="at-row"><div class="at-row__label"><span class="at-dot" style="background:${row.color}"></span>${escapeHtml(row.label)}</div><div class="at-bar"><span style="width:${((row.perGame / max) * 100).toFixed(1)}%;background:${row.color};animation-delay:${i * 60}ms"></span></div><div class="at-row__meta">${fmt(row.perGame)} <small>opp ${fmt(them[row.id]?.perGame)}</small></div></div>`).join("")}
    <p class="at-note">Per game. Header = loose-ball header won, aerial/ground duel = ball won in a duel.</p>`;
}
function renderPeriods(report) {
  const us = report.periods?.us || [];
  const them = Object.fromEntries((report.periods?.them || []).map((row) => [row.id, row]));
  const max = Math.max(1, ...us.map((row) => row.perGame), ...Object.values(them).map((row) => row.perGame));
  $("periodPanel").innerHTML = `${panelHead("When", "Ball wins by 15 minutes")}
    <div class="at-legend"><span><i style="background:#f5c518"></i>Port Vale</span><span><i style="background:#f87171"></i>Opponents</span></div>
    <div class="iv-periods">${us.map((row) => `<div class="iv-period"><div class="iv-period__bars">
      <i style="height:${((row.perGame / max) * 100).toFixed(1)}%;background:linear-gradient(180deg,#ffe27a,#f59e0b)" title="Port Vale ${fmt(row.perGame)}"></i>
      <i style="height:${(((them[row.id]?.perGame || 0) / max) * 100).toFixed(1)}%;background:linear-gradient(180deg,#fca5a5,#b91c1c)" title="Opponents ${fmt(them[row.id]?.perGame)}"></i>
    </div><span>${row.id}</span></div>`).join("")}</div>
    <p class="at-note">Ball wins per game in each 15-minute block (stoppage time sits in the last block of each half).</p>`;
}

/* ---------- match by match ---------- */
function renderMatches(report) {
  const rows = [...(report.trend || [])].reverse();
  if (!rows.length) { $("matchPanel").innerHTML = `${panelHead("Match by match", "Every game")}<p class="at-empty">No matches in this window.</p>`; return; }
  const cmp = (us, them, digits, opts = {}) => {
    const a = num(us);
    const b = num(them);
    const better = a != null && b != null && a !== b ? (opts.lower ? a < b : a > b) : null;
    const suffix = opts.pct ? "%" : "";
    return `<td><span class="iv-cmp"><b class="${better == null ? "" : better ? "iv-won" : "iv-lost"}">${a == null ? "—" : a.toFixed(digits) + suffix}</b><small>${b == null ? "—" : b.toFixed(digits) + suffix}</small></span></td>`;
  };
  $("matchPanel").innerHTML = `${panelHead("Match by match", "Did we win the battles?")}
    <p class="at-section__lede" style="margin:-.4rem 0 .9rem;font-size:.88rem">Port Vale number first, opponent second. Green when we won that battle. Click a game to open it.</p>
    <div class="at-table-wrap"><table class="iv-mt"><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>Ball wins</th><th>Final 3rd</th><th>vs Def</th><th>Off. int.</th><th>Def. int.</th><th>Duel %</th><th>Aerial %</th><th>Ground %</th></tr></thead>
    <tbody>${rows.map((row) => `<tr data-match="${row.matchId}" style="cursor:pointer">
      <td>${row.date ? new Date(row.date).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : ""}</td>
      <td>${escapeHtml(row.opponent)} <small style="color:var(--muted)">${row.home ? "H" : "A"}</small></td>
      <td>${resultChip(row.result)} ${row.goalsFor ?? ""}–${row.goalsAgainst ?? ""}</td>
      ${cmp(row.us.bw, row.them.bw, 0)}${cmp(row.us.high, row.them.high, 0)}${cmp(row.us.bwd, row.them.bwd, 1)}${cmp(row.us.oi, row.them.oi, 0)}${cmp(row.us.di, row.them.di, 0, { lower: true })}
      ${cmp(row.us.duelPct, row.them.duelPct, 0, { pct: true })}${cmp(row.us.aerialPct, row.them.aerialPct, 0, { pct: true })}${cmp(row.us.groundPct, row.them.groundPct, 0, { pct: true })}
    </tr>`).join("")}</tbody></table></div>`;
  $("matchPanel").querySelectorAll("[data-match]").forEach((tr) => tr.addEventListener("click", async () => {
    state.scope = "match";
    state.matchId = Number(tr.dataset.match);
    document.querySelectorAll("[data-scope]").forEach((item) => item.classList.toggle("at-toggle__btn--active", item.dataset.scope === "match"));
    renderFixtures();
    try { await loadReport(); window.scrollTo({ top: 0, behavior: "smooth" }); } catch (err) { setStatus(err.message); }
  }));
}

/* ---------- league ---------- */
const TABLE_COLS = [
  { key: "bw", label: "Ball wins / g", digits: 1 },
  { key: "bwd", label: "Ball wins vs def / g", digits: 2 },
  { key: "oi", label: "Off. int. / g", digits: 1 },
  { key: "di", label: "Def. int. / g", digits: 1, lower: true },
  { key: "duelPct", label: "Duel %", digits: 1 },
  { key: "aerialPct", label: "Aerial %", digits: 1 },
  { key: "groundPct", label: "Ground %", digits: 1 },
  { key: "threat", label: "Ball-win threat / g", digits: 3 },
];
function renderTable(report) {
  const league = report.league || {};
  const of = league.of || 24;
  const sortKey = state.tableSort;
  const col = TABLE_COLS.find((item) => item.key === sortKey) || TABLE_COLS[0];
  const rows = [...(league.rows || [])].sort((a, b) => {
    const diff = (num(b[sortKey]) ?? -999) - (num(a[sortKey]) ?? -999);
    return col.lower ? -diff : diff;
  });
  if (!rows.length) { $("tablePanel").innerHTML = `${panelHead("League Two", "Interventions table")}<p class="at-empty">League table appears after the next data refresh.</p>`; return; }
  const ranges = Object.fromEntries(TABLE_COLS.map((item) => {
    const values = rows.map((row) => num(row[item.key])).filter((v) => v != null);
    return [item.key, [Math.min(...values), Math.max(...values)]];
  }));
  const vale = rows.find((row) => row.focus) || {};
  $("tablePanel").innerHTML = `${panelHead(`League Two ${report.season || ""}`, "Interventions table")}
    <p class="at-lt__lede">Every League Two side, season per-game Impect squad KPIs. Click a column to sort. Green is good for that column (fewer defensive interventions counts as good). The chip is Port Vale's rank.</p>
    <div class="at-lt"><table><thead><tr><th>#</th><th>Club</th>${TABLE_COLS.map((item) => `<th class="at-lt__sort${sortKey === item.key ? " is-sorted" : ""}" data-sort="${item.key}">${item.label}${sortKey === item.key ? " ▾" : ""}<small>${rankChip(vale.ranks?.[item.key], of)}</small></th>`).join("")}<th>Pld</th></tr></thead>
    <tbody>${rows.map((row, i) => `<tr class="${row.focus ? "at-focus" : ""}"><td class="at-lt__pos">${i + 1}</td>
      <td><span class="at-lt__club"><span class="at-lt__crest">${badgeHtml(row)}</span>${escapeHtml(row.club)}</span></td>
      ${TABLE_COLS.map((item) => { const [lo, hi] = ranges[item.key]; return `<td style="${heat(row[item.key], lo, hi, !item.lower)}">${fmt(row[item.key], item.digits)}</td>`; }).join("")}
      <td>${row.played}</td></tr>`).join("")}</tbody></table></div>`;
  $("tablePanel").querySelectorAll("[data-sort]").forEach((th) => th.addEventListener("click", () => { state.tableSort = th.dataset.sort; renderTable(state.report); }));
}

/* ---------- render ---------- */
function renderEmpty(report) {
  const building = Boolean(report.progress);
  document.body.classList.add("at-is-empty");
  $("hero").innerHTML = `<div class="at-hero__empty"><h2>${building ? "Saving to the data lake" : "Not in the data lake yet"}</h2><p>${escapeHtml(report.message || "Nothing saved for this view yet.")}</p>${building ? '<div class="at-skel" style="width:60%"></div><div class="at-skel" style="width:40%"></div>' : ""}</div>`;
  setStatus(building ? "Checking the data lake again every 20 seconds." : "Reading the data lake.");
  clearTimeout(lakeTimer);
  if (building) lakeTimer = setTimeout(() => { loadFixtures().then(loadReport).catch(() => {}); }, 20000);
}
function render(report) {
  state.report = report;
  clearTimeout(lakeTimer);
  if (report.ready === false) { renderEmpty(report); return; }
  document.body.classList.remove("at-is-empty");
  if (state.player !== "all" && !(report.players || []).some((row) => String(row.id) === String(state.player))) state.player = "all";
  const steps = [renderHero, renderInsights, renderEvidence, renderLeagueBattles, renderValeBattles, renderResults, renderMap, renderPlayers, renderUnits, renderTypes, renderPeriods, renderMatches, renderTable];
  steps.forEach((fn) => { try { fn(report); } catch (err) { console.error(fn.name, err); } });
  setStatus(`${report.competition || "League Two"} ${report.season || ""} · ${report.matchCount || 0} Port Vale matches in this window · read from the data lake${report.generatedAt ? ` · saved ${new Date(report.generatedAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}.`);
}
async function loadReport() {
  setStatus("Reading the data lake…");
  const params = new URLSearchParams({ season: state.season, scope: state.scope });
  if (state.scope === "match" && state.matchId) params.set("matchId", String(state.matchId));
  render(await getJson(`/api/interventions/report?${params.toString()}`));
}
async function loadFixtures() {
  const payload = await getJson(`/api/interventions/fixtures?season=${encodeURIComponent(state.season)}`);
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
    state.season = button.dataset.season; state.matchId = null; state.player = "all"; state.zone = null;
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
    const meta = await getJson("/api/interventions/meta");
    state.season = meta.defaultSeason || (meta.seasons[0] && meta.seasons[0].value) || "";
    renderSeasons(meta);
    await loadFixtures();
    await loadReport();
  } catch (err) { setStatus(err.message || "Interventions could not load."); }
}
boot();
