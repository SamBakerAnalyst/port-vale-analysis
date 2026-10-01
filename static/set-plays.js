const state = { season: "", scope: "season", matchId: null, fixtures: [], report: null, attackFilter: "corner", defenceFilter: "corner", sort: { key: "xgDiff", dir: -1 } };
const OUTCOME = {
  goal: { label: "Goal", color: "#f5c518" },
  shot: { label: "Shot", color: "#e8edf4" },
  won: { label: "First contact won", color: "#b08a20" },
  lost: { label: "First contact lost", color: "#8b9bb0" },
  none: { label: "No contact", color: "#4b5563" },
};
const DEF_OUTCOME = {
  goal: { label: "Goal conceded", color: "#f87171" },
  shot: { label: "Shot conceded", color: "#e8edf4" },
  won: { label: "They won first contact", color: "#b45454" },
  lost: { label: "We won first contact", color: "#f5c518" },
  none: { label: "No contact", color: "#4b5563" },
};
const MAP_FILTERS = [
  ["corner", "Corners"], ["corner_left", "Left corners"], ["corner_right", "Right corners"],
  ["free_kick", "Free kicks"], ["throw_in", "Long throws"], ["all", "Everything"],
];
const $ = (id) => document.getElementById(id);
let lakeTimer = null;

function escapeHtml(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function fmt(value, digits = 2) { const n = Number(value); return value != null && Number.isFinite(n) ? n.toFixed(digits) : "—"; }
function pct(value) { const n = Number(value); return value != null && Number.isFinite(n) ? `${Math.round(n)}%` : "—"; }
function signed(value, digits = 2) { const n = Number(value); if (value == null || !Number.isFinite(n)) return "—"; return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`; }
function rankTier(rank, of) {
  if (!rank) return "none";
  const size = Number(of) || 24;
  if (rank <= Math.ceil(size / 4)) return "t1";
  if (rank <= Math.ceil(size / 2)) return "t2";
  if (rank <= Math.ceil((size * 3) / 4)) return "t3";
  return "t4";
}
function rankChip(rank, of) { return rank ? `<span class="at-rank at-rank--${rankTier(rank, of)}">${rank} of ${of || 24}</span>` : `<span class="at-rank at-rank--none">—</span>`; }
function panelHead(kicker, title, extra = "") { return `<div class="at-panel__head"><p class="at-panel__kicker">${escapeHtml(kicker)}</p><h2 class="at-panel__title">${escapeHtml(title)}</h2>${extra}</div>`; }
function barRow(label, share, meta, color, delay = 0) {
  const width = Math.max(0, Math.min(100, Number(share) || 0));
  return `<div class="at-row"><div class="at-row__label">${escapeHtml(label)}</div><div class="at-bar"><span style="width:${width}%;background:${color};animation-delay:${delay}ms"></span></div><div class="at-row__meta">${meta}</div></div>`;
}
function setStatus(text) { $("statusBar").textContent = text; }
function windowLabel(report) {
  if (report.scope === "season") return `${report.season} season`;
  if (report.scope === "last6") return "last 6 games";
  const f = report.fixtures?.[0];
  return f ? `vs ${f.opponent} (${f.home ? "H" : "A"}) ${f.score}` : "this match";
}
async function getJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (body.detail) detail = String(body.detail); } catch (_err) {}
    throw new Error(detail);
  }
  return response.json();
}
/* ---------- half pitch (goal at the top) ---------- */
const HP = { w: 680, h: 360, top: 24 };
function hp(x, y) { return { x: (34 - Number(y)) * 10, y: HP.top + (52.5 - Number(x)) * 10 }; }
function halfPitch(inner, goalLabel) {
  const line = "rgba(226,245,233,0.55)";
  const t = HP.top;
  const stripes = Array.from({ length: 7 }, (_, i) => `<rect x="0" y="${t + i * 50}" width="${HP.w}" height="50" fill="${i % 2 ? "#0f1f17" : "#11241a"}"/>`).join("");
  return `<svg class="sp-half" viewBox="0 0 ${HP.w} ${HP.h + t}" role="img" aria-label="${escapeHtml(goalLabel)}">
    <rect width="${HP.w}" height="${HP.h + t}" fill="#0e1c15"/>${stripes}
    <g fill="none" stroke="${line}" stroke-width="2">
      <rect x="2" y="${t}" width="${HP.w - 4}" height="${HP.h - 2}"/>
      <rect x="138.4" y="${t}" width="403.2" height="165"/>
      <rect x="248.4" y="${t}" width="183.2" height="55"/>
      <path d="M266.9 ${t + 165} A91.5 91.5 0 0 0 413.1 ${t + 165}"/>
      <path d="M2 ${t + 10} A10 10 0 0 0 12 ${t}"/><path d="M${HP.w - 12} ${t} A10 10 0 0 0 ${HP.w - 2} ${t + 10}"/>
    </g>
    <rect x="303.4" y="${t - 14}" width="73.2" height="14" fill="rgba(255,255,255,0.08)" stroke="${line}" stroke-width="2"/>
    <circle cx="340" cy="${t + 110}" r="3" fill="${line}"/>
    <text x="340" y="13" text-anchor="middle" fill="rgba(232,237,244,0.7)" font-size="13" font-family="Barlow Condensed" font-weight="600" letter-spacing="3">${escapeHtml(goalLabel.toUpperCase())}</text>
    ${inner}
  </svg>`;
}
function mapFilter(points, filter) {
  return points.filter((p) => {
    if (filter === "all") return true;
    if (filter === "corner") return p.type === "corner";
    if (filter === "corner_left") return p.type === "corner" && p.side === "left";
    if (filter === "corner_right") return p.type === "corner" && p.side === "right";
    return p.type === filter;
  });
}
function deliveryLayer(points, palette) {
  const order = { none: 0, lost: 1, won: 2, shot: 3, goal: 4 };
  return [...points].sort((a, b) => order[a.outcome] - order[b.outcome]).map((p, i) => {
    const s = hp(p.sx, p.sy); const e = hp(p.dx, p.dy);
    const color = (palette[p.outcome] || palette.none).color;
    const big = p.outcome === "goal" || p.outcome === "shot";
    const tip = `${p.minute}' ${p.opponent ? `vs ${p.opponent} · ` : ""}${p.taker} · ${palette[p.outcome].label}${p.xg ? ` · ${fmt(p.xg, 2)} xG` : ""}`;
    const lineOk = p.sub !== "short" && Math.abs(s.y - e.y) + Math.abs(s.x - e.x) > 8;
    return `<g class="at-pop" style="animation-delay:${Math.min(i * 6, 600)}ms"><title>${escapeHtml(tip)}</title>
      ${lineOk ? `<line x1="${s.x.toFixed(1)}" y1="${s.y.toFixed(1)}" x2="${e.x.toFixed(1)}" y2="${e.y.toFixed(1)}" stroke="${color}" stroke-opacity="${big ? 0.75 : 0.22}" stroke-width="${big ? 2 : 1.2}"/>` : ""}
      <circle cx="${e.x.toFixed(1)}" cy="${e.y.toFixed(1)}" r="${big ? 7 : 4.5}" fill="${color}" fill-opacity="${big ? 1 : 0.8}" stroke="#0b0f15" stroke-width="1.2"/></g>`;
  }).join("");
}
function shotLayer(shots, goalColor) {
  return [...shots].sort((a, b) => Number(a.goal) - Number(b.goal)).map((s, i) => {
    const p = hp(s.x, s.y);
    const r = 4 + Math.sqrt(Math.max(0, Number(s.xg) || 0)) * 22;
    const fill = s.goal ? goalColor : s.phase === "second" ? "#8b9bb0" : "#e8edf4";
    const tip = `${s.minute}' ${s.player}${s.opponent ? ` vs ${s.opponent}` : ""} · ${fmt(s.xg, 2)} xG${s.head ? " · header" : ""}${s.goal ? " · GOAL" : ""}`;
    return `<g class="at-pop" style="animation-delay:${Math.min(i * 12, 700)}ms"><title>${escapeHtml(tip)}</title>
      ${s.head ? `<rect x="${(p.x - r).toFixed(1)}" y="${(p.y - r).toFixed(1)}" width="${(2 * r).toFixed(1)}" height="${(2 * r).toFixed(1)}" transform="rotate(45 ${p.x.toFixed(1)} ${p.y.toFixed(1)})" fill="${fill}" fill-opacity="${s.goal ? 1 : s.phase === "second" ? 0.7 : 0.9}" stroke="#0b0f15" stroke-width="1.2"/>`
        : `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${fill}" fill-opacity="${s.goal ? 1 : s.phase === "second" ? 0.7 : 0.9}" stroke="#0b0f15" stroke-width="1.2"/>`}</g>`;
  }).join("");
}

/* ---------- controls ---------- */
function renderSeasons(meta) {
  $("seasonToggle").innerHTML = (meta.seasons || []).map((row) => `<button type="button" class="at-toggle__btn${row.value === state.season ? " at-toggle__btn--active" : ""}" data-season="${escapeHtml(row.value)}">${escapeHtml(row.label || row.value)}</button>`).join("");
}
function renderFixtures() {
  $("matchSelect").innerHTML = [...state.fixtures].reverse().map((row) => `<option value="${row.matchId}">${escapeHtml(row.opponent)} (${row.home ? "H" : "A"}) ${escapeHtml(row.score || "")}</option>`).join("");
  if (state.matchId) $("matchSelect").value = String(state.matchId);
  $("matchSelectGroup").hidden = state.scope !== "match";
}

/* ---------- overview ---------- */
function renderHero(report) {
  const h = report.headline || {};
  const diff = Number(h.goalDiff) || 0;
  const xgDiff = Number(h.xgFor) - Number(h.xgAgainst);
  $("hero").innerHTML = `
    <div class="sp-scoreboard">
      <div class="sp-scoreboard__side sp-scoreboard__for"><strong data-count="${h.goalsFor || 0}">${h.goalsFor ?? "—"}</strong><span>Scored</span></div>
      <div class="sp-scoreboard__dash">–</div>
      <div class="sp-scoreboard__side sp-scoreboard__against"><strong data-count="${h.goalsAgainst || 0}">${h.goalsAgainst ?? "—"}</strong><span>Conceded</span></div>
      <div class="sp-scoreboard__foot">Set-play goals, ${escapeHtml(windowLabel(report))} · difference <b class="${diff >= 0 ? "at-up" : "at-down"}">${diff > 0 ? "+" : ""}${diff}</b></div>
    </div>
    <div>
      <h2 class="at-hero__title">${escapeHtml(windowLabel(report))}</h2>
      <div class="at-kpis">
        <div class="at-kpi"><strong>${fmt(h.xgFor)} <small style="color:var(--muted);font-size:.8rem">v</small> ${fmt(h.xgAgainst)}</strong><span>Set-play xG for v against <em class="${xgDiff >= 0 ? "at-up" : "at-down"}">${signed(xgDiff)}</em></span></div>
        <div class="at-kpi"><strong>${h.rank ? `${h.rank}<small style="color:var(--muted);font-size:.8rem"> / ${h.of}</small>` : "—"}</strong><span>League rank, set-play xG difference (season)</span></div>
        <div class="at-kpi"><strong>${pct(h.shareFor)}</strong><span>Of our goals from set plays, pens excluded <em>(league ${pct(h.leagueShareFor)})</em></span></div>
        <div class="at-kpi"><strong>${pct(h.shareAgainst)}</strong><span>Of goals conceded from set plays, pens excluded</span></div>
        <div class="at-kpi"><strong>${h.pensScored ?? 0}/${h.pensFor ?? 0} <small style="color:var(--muted);font-size:.8rem">v</small> ${h.pensConceded ?? 0}/${h.pensAgainst ?? 0}</strong><span>Penalties scored/won v conceded/given</span></div>
        <div class="at-kpi"><strong class="at-up">+${fmt(h.goalsSwingTop3 ?? h.goalsSwing, 1)}</strong><span>Goals a season if our set plays matched the top three (≈ ${fmt(h.pointsSwingTop3 ?? h.pointsSwing, 0)} pts)</span></div>
      </div>
    </div>`;
}
function renderInsights(report) {
  $("insights").innerHTML = (report.insights || []).map((row, i) => `<article class="at-insight at-insight--${escapeHtml(row.tone)}" style="animation-delay:${i * 70}ms"><h3>${escapeHtml(row.title)}</h3><p>${escapeHtml(row.text)}</p></article>`).join("");
}
function benchValue(b, value) { if (value == null) return "—"; return b.pct ? pct(value) : fmt(value, b.digits); }
const LADDER_GROUPS = [
  { title: "Overall", tone: "", ids: ["xgDiff"] },
  { title: "Our set plays · for", tone: "for", ids: ["goalsFor", "xgFor", "cornersFor", "xgPerCornerFor", "fcAttack", "shotRateFor", "secondXgFor", "spShareFor"] },
  { title: "Their set plays · against", tone: "against", ids: ["goalsAgainst", "xgAgainst", "cornersAgainst", "xgPerCornerAgainst", "fcDefence", "shotRateAgainst", "secondXgAgainst", "counterXgAgainst"] },
];
function renderLadder(report) {
  const marks = report.benchmarks || [];
  const table = report.table || [];
  const byId = Object.fromEntries(marks.map((b) => [b.id, b]));
  const grouped = new Set(LADDER_GROUPS.flatMap((g) => g.ids));
  const row = (b) => {
    const values = table.map((r) => r[b.id]).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
    if (!values.length) return "";
    const lo = Math.min(...values); const hi = Math.max(...values);
    const pos = (v) => { if (hi === lo) return 50; const t = (Number(v) - lo) / (hi - lo); return (b.better === "high" ? t : 1 - t) * 100; };
    const dots = values.map((v) => `<span class="sp-track__dot" style="left:${pos(v).toFixed(1)}%"></span>`).join("");
    return `<div class="sp-ladder__row" title="${escapeHtml(`League avg ${benchValue(b, b.leagueAvg)} · top-3 avg ${benchValue(b, b.top3Avg)} · best ${benchValue(b, b.best)} (${b.bestClub})`)}">
      <div class="sp-ladder__label">${escapeHtml(b.label)}</div>
      <div class="sp-track"><div class="sp-track__line"></div>${dots}
        <span class="sp-track__mark" style="left:${pos(b.leagueAvg).toFixed(1)}%"></span>
        <span class="sp-track__mark sp-track__mark--top3" style="left:${pos(b.top3Avg).toFixed(1)}%"></span>
        ${b.vale != null ? `<span class="sp-track__vale" style="left:${pos(b.vale).toFixed(1)}%"></span>` : ""}</div>
      <div class="sp-ladder__value">${benchValue(b, b.vale)}</div>
      ${rankChip(b.rank, b.of)}
    </div>`;
  };
  const groups = LADDER_GROUPS.map((g) => ({ ...g, marks: g.ids.map((id) => byId[id]).filter(Boolean) }));
  const extra = marks.filter((b) => !grouped.has(b.id));
  if (extra.length) groups[0].marks.push(...extra);
  const key = `<div class="sp-key"><span><i class="sp-key__vale"></i>Port Vale</span><span><i class="sp-key__team"></i>Other clubs</span><span><i class="sp-key__avg"></i>League average</span><span><i class="sp-key__top3"></i>Top-3 average</span><span>Right is always better</span></div>`;
  const kicker = `Season, every League Two side · ${report.leagueMatches || 0} matches`;
  const panel = (id, title, group) => {
    const body = group ? group.marks.map(row).join("") : "";
    $(id).innerHTML = `${panelHead(kicker, title)}${key}
      <div class="sp-ladder"><div class="sp-ladder__group${group?.tone ? ` sp-ladder__group--${group.tone}` : ""}">${body || `<p class="at-empty">No league comparison yet.</p>`}</div></div>`;
  };
  panel("ladderPanel", "Where we stand overall", groups[0]);
  panel("ladderFor", "Where we rank: our set plays", groups[1]);
  panel("ladderAgainst", "Where we rank: their set plays", groups[2]);
}

/* ---------- plan ---------- */
function renderPlan(report) {
  const plan = report.plan || [];
  const h = report.headline || {};
  const top3Goals = plan.reduce((s, r) => s + Number(r.goalsAtTop3 || 0), 0);
  const top3Pts = plan.reduce((s, r) => s + Number(r.pointsAtTop3 || 0), 0);
  if (!plan.length) {
    const empty = `<p class="at-empty">The plan needs a few more league games before the comparison is fair.</p>`;
    $("planTotal").innerHTML = "";
    $("planAttack").innerHTML = empty;
    $("planDefence").innerHTML = empty;
    return;
  }
  const sideGoals = (end) => plan.filter((r) => r.end === end).reduce((s, r) => s + Number(r.goalsAtTop3 || 0), 0);
  $("planTotal").innerHTML = `<div class="sp-plan-sum">
      <p>Get our set plays up to the level of League Two's top three teams and we gain about</p>
      <div class="sp-plan-sum__nums"><span><strong>${fmt(top3Goals, 1)}</strong> goals a season</span><span><strong>${fmt(top3Pts, 0)}</strong> points</span></div>
      <div class="sp-plan-sum__split">
        <a href="#attack"><b>+${fmt(sideGoals("attack"), 1)}</b> scoring more from ours →</a>
        <a href="#defence" class="is-against"><b>+${fmt(sideGoals("defence"), 1)}</b> conceding fewer from theirs →</a>
      </div>
      <p class="sp-plan-sum__small">Match the single best team at every one of them and it is ${fmt(h.goalsSwing, 1)} goals (about ${fmt(h.pointsSwing, 0)} points).</p>
    </div>`;
  const card = (row) => {
    const attack = row.end === "attack";
    const name = PLAN_NAMES[row.id] || row.title;
    const us = Number(row.vale) * 100;
    const top = Number(row.top3) * 100;
    const season = Math.round(Number(row.valeVolume) * 46);
    const gain = Number(row.goalsAtTop3 || 0);
    const max = Math.max(us, top, 0.1);
    const bar = (label, value, cls) => `<div class="sp-lever__bar"><span>${label}</span><div class="at-bar"><span class="${cls}" style="width:${(value / max) * 100}%"></span></div><b>${fmt(value, 1)}</b></div>`;
    const sentence = attack
      ? `We take about <b>${season}</b> a season. Every 100 of them is worth <b>${fmt(us, 1)}</b> goals to us. The top three get <b>${fmt(top, 1)}</b>.`
      : `We face about <b>${season}</b> a season. Every 100 of them costs us <b>${fmt(us, 1)}</b> goals. The top three concede <b>${fmt(top, 1)}</b>.`;
    return `<article class="sp-lever sp-lever--${row.end}">
      <div class="sp-lever__prize"><strong>${gain > 0 ? `+${fmt(gain, 1)}` : "✓"}</strong><span>${gain > 0 ? "goals a season" : "already top three"}</span></div>
      <div class="sp-lever__body">
        <h3>${escapeHtml(name)} ${rankChip(row.rank, row.of)}</h3>
        <p class="sp-lever__what">${sentence}</p>
        <div class="sp-lever__bars">
          ${bar("Port Vale", us, "sp-bar--vale")}
          ${bar("Top three", top, "sp-bar--top")}
        </div>
      </div>
    </article>`;
  };
  const column = (end, title, sub) => {
    const rows = plan.filter((r) => r.end === end).sort((a, b) => Number(b.goalsAtTop3) - Number(a.goalsAtTop3));
    const total = rows.reduce((s, r) => s + Number(r.goalsAtTop3 || 0), 0);
    return `<div class="sp-plan__col sp-plan__col--${end}">
      <header><h3>${title}</h3><span>+${fmt(total, 1)} goals</span></header>
      <p class="sp-plan__sub">${sub}</p>
      ${rows.map(card).join("") || `<p class="at-empty">Not enough of these yet to compare.</p>`}
    </div>`;
  };
  $("planAttack").innerHTML = column("attack", "Where the goals are: score more", "If each of our set plays was as good as League Two's top three. Goals per 100 set plays — higher is better.");
  $("planDefence").innerHTML = column("defence", "Where the goals are: concede fewer", "If we defended each set play as well as League Two's top three. Goals conceded per 100 set plays — lower is better.");
}
const PLAN_NAMES = {
  corner_attack: "Our corners",
  fk_attack: "Our free kicks into the box",
  throw_attack: "Our long throws",
  corner_defence: "Corners against us",
  fk_defence: "Free kicks into our box",
  throw_defence: "Long throws against us",
};

/* ---------- attacking / defending ---------- */
function tiles(id, s, attacking) {
  const items = attacking ? [
    [s.perGame, 1, "Set plays / game (no pens)"], [s.xgPerGame, 2, "Set-play xG / game"], [s.goals, 0, "Set-play goals"],
    [s.shotRate, 0, "% ending in a shot", true], [s.fcWonPct, 0, "% first contacts won", true], [s.secondXg, 2, "Second-ball xG"],
    [s.counterXg, 2, "Counter xG conceded off them"],
  ] : [
    [s.perGame, 1, "Opposition set plays / game"], [s.xgPerGame, 2, "xG conceded / game"], [s.goals, 0, "Goals conceded"],
    [s.shotRate, 0, "% ending in a shot", true], [s.fcWonPct, 0, "% first contacts we win", true], [s.secondXg, 2, "Second-ball xG conceded"],
    [s.gkClaims, 0, "Keeper claims / saves at first contact"],
  ];
  $(id).innerHTML = items.map(([v, d, l, isPct]) => `<div class="at-tile"><strong data-count="${Number(v) || 0}" data-digits="${d}">${v == null ? "—" : fmt(v, d)}</strong><span>${escapeHtml(l)}${isPct ? "" : ""}</span></div>`).join("");
}
function bucketTable(id, rows, attacking) {
  const body = rows.map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${r.n}</td><td>${fmt(r.perGame, 1)}</td><td>${pct(r.shotRate)}</td><td>${fmt(r.xg, 2)}</td><td>${fmt(r.xgPer, 3)}</td><td>${r.goals}</td><td>${pct(r.fcWonPct)}</td><td>${pct(r.intoBoxPct)}</td><td>${fmt(r.secondXg, 2)}</td></tr>`).join("");
  $(id).innerHTML = `${panelHead(attacking ? "Every type, our set plays" : "Every type, against us", attacking ? "What each set play gives us" : "What each set play costs us")}
    <div class="at-table-wrap"><table class="sp-table sp-num2"><thead><tr><th>Type</th><th>No.</th><th>/ game</th><th>Shot %</th><th>xG</th><th>xG each</th><th>Goals</th><th>${attacking ? "1st contact won" : "1st contact we win"}</th><th>Into box</th><th>2nd-ball xG</th></tr></thead><tbody>${body}</tbody></table></div>
    <p class="at-note">Inswing and outswing come from the taker's foot and the side. Throw-ins count from the final third only. Free kicks from our own half are left out.</p>`;
}
function renderMapPanel(id, points, filterKey, attacking) {
  const filter = state[filterKey];
  const shown = mapFilter(points, filter);
  const palette = attacking ? OUTCOME : DEF_OUTCOME;
  const counts = {};
  shown.forEach((p) => { counts[p.outcome] = (counts[p.outcome] || 0) + 1; });
  const chips = MAP_FILTERS.map(([key, label]) => `<button type="button" class="sp-chip${filter === key ? " is-on" : ""}" data-map="${filterKey}" data-filter="${key}">${escapeHtml(label)}</button>`).join("");
  const legend = ["goal", "shot", "won", "lost", "none"].map((k) => `<span><i style="background:${palette[k].color}"></i>${escapeHtml(palette[k].label)} (${counts[k] || 0})</span>`).join("");
  $(id).innerHTML = `${panelHead(attacking ? "Where our deliveries land" : "Where their deliveries land", attacking ? "Delivery map" : "Delivery map against")}
    <div class="sp-filters">${chips}</div>
    ${halfPitch(deliveryLayer(shown, palette), attacking ? "Their goal" : "Our goal")}
    <div class="sp-legend">${legend}</div>
    <p class="at-note">Dot = where the delivery ended. Hover for the minute, opponent and taker. Short corners show where the follow-up ball landed.</p>`;
}
function renderZones(id, zones, attacking) {
  const max = Math.max(...zones.map((z) => z.n), 1);
  const color = attacking ? "#f5c518" : "#f87171";
  const body = zones.map((z) => `<tr><td>${escapeHtml(z.label)}</td><td><span class="at-cellbar" style="width:${((z.n / max) * 70).toFixed(0)}px;background:${color}"></span>${z.n}</td><td>${pct(z.share)}</td><td>${pct(z.fcWonPct)}</td><td>${fmt(z.xgPer, 3)}</td><td>${z.goals}</td></tr>`).join("");
  const best = [...zones].filter((z) => z.n >= 5).sort((a, b) => b.xgPer - a.xgPer)[0];
  $(id).innerHTML = `${panelHead("Corners and free kicks", attacking ? "Target zones" : "Zones they attack")}
    <div class="at-table-wrap"><table class="sp-table sp-num2"><thead><tr><th>Zone</th><th>Balls</th><th>Share</th><th>${attacking ? "1st won" : "We win 1st"}</th><th>xG each</th><th>Goals</th></tr></thead><tbody>${body}</tbody></table></div>
    <p class="at-note">Near and far post are relative to the side the ball comes from. ${best ? `${attacking ? "Our most dangerous" : "Their most dangerous"} zone: <b>${escapeHtml(best.label)}</b> at ${fmt(best.xgPer, 3)} xG per delivery.` : ""}</p>`;
}
function renderShotPanel(id, shots, attacking) {
  const total = shots.reduce((s, r) => s + Number(r.xg || 0), 0);
  const goals = shots.filter((s) => s.goal).length;
  const headers = shots.filter((s) => s.head).length;
  $(id).innerHTML = `${panelHead(attacking ? "Shots from our set plays" : "Shots from their set plays", attacking ? "Shot map" : "Shot map against")}
    ${halfPitch(shotLayer(shots, attacking ? "#f5c518" : "#f87171"), attacking ? "Their goal" : "Our goal")}
    <div class="sp-legend"><span><i style="background:${attacking ? "#f5c518" : "#f87171"}"></i>Goal</span><span><i style="background:#e8edf4"></i>First phase</span><span><i style="background:#8b9bb0"></i>Second ball</span><span>◆ header · size = xG</span></div>
    <p class="at-note">${shots.length} shots · ${fmt(total, 2)} xG · ${goals} goals · ${headers} headers. Penalties included.</p>`;
}
function renderFkPanel(id, rows, title) {
  const max = Math.max(...rows.map((r) => r.n), 1);
  const body = rows.map((r, i) => barRow(r.label, (r.n / max) * 100, `${r.n} · ${r.crossed} crossed · ${r.direct} direct · ${fmt(r.xg, 2)} xG · ${r.goals} g`, "#e8edf4", i * 60)).join("");
  return `${panelHead("Free kicks by area", title)}${body}`;
}
function renderAttack(report) {
  const a = report.attack || {};
  tiles("attackTiles", a.summary || {}, true);
  bucketTable("attackBuckets", a.buckets || [], true);
  renderMapPanel("attackMap", a.deliveries || [], "attackFilter", true);
  renderZones("attackZones", a.zones || [], true);
  renderShotPanel("attackShots", a.shots || [], true);
  $("attackFk").innerHTML = renderFkPanel("attackFk", a.fkAreas || [], "Our free kicks") + `<p class="at-note">Wide = outside the width of the box. Central final third = the direct-shot zone.</p>`;
}
function renderDefence(report) {
  const d = report.defence || {};
  tiles("defenceTiles", d.summary || {}, false);
  bucketTable("defenceBuckets", d.buckets || [], false);
  renderMapPanel("defenceMap", d.deliveries || [], "defenceFilter", false);
  renderZones("defenceZones", d.zones || [], false);
  renderShotPanel("defenceShots", d.shots || [], false);
  const gk = d.gk || {};
  $("defenceExtra").innerHTML = `${panelHead("Our keeper and the box", "Goalkeeper")}
    <div class="sp-gk">
      <div class="at-tile"><strong>${pct(gk.claimPct)}</strong><span>Box deliveries claimed or saved at first contact (${gk.claims || 0} of ${gk.boxDeliveries || 0})</span></div>
      <div class="at-tile"><strong>${pct(gk.goalmouthClaimPct)}</strong><span>Goalmouth deliveries dealt with by the keeper (${gk.goalmouthDeliveries || 0} into the six-yard box)</span></div>
    </div>${renderFkPanel("", d.fkAreas || [], "Free kicks we give away")}`;
}

/* ---------- players ---------- */
function renderPlayers(report) {
  const takers = report.attack?.takers || [];
  $("takerPanel").innerHTML = `${panelHead("Corners and free kicks into the box", "Our deliverers")}${takers.length ? `<div class="sp-takers">${takers.map((t, i) => {
    const swingTotal = (t.inswing || 0) + (t.outswing || 0) || 1;
    return `<article class="at-player"><div class="at-player__top"><span class="at-player__name">${escapeHtml(t.name)}</span><span class="at-player__rank">${i + 1}</span></div>
      <div class="at-player__big">${t.deliveries} <small>deliveries · ${t.corners} corners · ${t.freeKicks} FKs · ${t.foot === "L" ? "left" : t.foot === "R" ? "right" : "?"} foot</small></div>
      <div class="sp-swing" title="Inswing ${t.inswing} · outswing ${t.outswing}"><span style="width:${(t.inswing / swingTotal) * 100}%;background:#f5c518"></span><span style="width:${(t.outswing / swingTotal) * 100}%;background:#e8edf4"></span></div>
      <div class="at-player__grid">
        <div><b>${pct(t.intoBoxPct)}</b><span>Into the box</span></div>
        <div><b>${pct(t.fcWonPct)}</b><span>We win 1st contact</span></div>
        <div><b>${pct(t.shotRate)}</b><span>Lead to a shot</span></div>
        <div><b>${fmt(t.xgPer, 3)}</b><span>xG per ball</span></div>
        <div><b>${t.goals}</b><span>Goals</span></div>
        <div><b>${escapeHtml(t.topZone)}</b><span>Favourite target</span></div>
      </div></article>`;
  }).join("")}</div><div class="sp-legend"><span><i style="background:#f5c518"></i>Inswing</span><span><i style="background:#e8edf4"></i>Outswing</span></div>` : `<p class="at-empty">No deliveries in this window.</p>`}`;

  const targets = report.attack?.targets || [];
  $("targetPanel").innerHTML = `${panelHead("Who attacks the ball", "Our targets")}<div class="at-table-wrap"><table class="sp-table sp-num2"><thead><tr><th>Player</th><th>1st contacts won</th><th>Headed</th><th>Shots</th><th>xG</th><th>Goals</th></tr></thead><tbody>${targets.map((t) => `<tr><td>${escapeHtml(t.name)}</td><td>${t.fcWon}</td><td>${t.headers}</td><td>${t.shots}</td><td>${fmt(t.xg, 2)}</td><td>${t.goals ? `<span class="sp-pill sp-pill--goal">${t.goals}</span>` : 0}</td></tr>`).join("") || `<tr><td colspan="6">No data.</td></tr>`}</tbody></table></div>`;

  const defenders = report.defence?.defenders || [];
  $("defenderPanel").innerHTML = `${panelHead("Opposition deliveries", "Our defenders at first contact")}<div class="at-table-wrap"><table class="sp-table sp-num2"><thead><tr><th>Player</th><th>Won</th><th>Lost duel</th><th>Win %</th><th>Lost → shot</th><th>Lost → goal</th></tr></thead><tbody>${defenders.map((d) => `<tr><td>${escapeHtml(d.name)}</td><td class="sp-good">${d.won}</td><td class="${d.lostDuels ? "sp-bad" : ""}">${d.lostDuels}</td><td>${pct(d.winPct)}</td><td>${d.lostOnShot}</td><td class="${d.lostOnGoal ? "sp-bad" : ""}">${d.lostOnGoal}</td></tr>`).join("") || `<tr><td colspan="6">No data.</td></tr>`}</tbody></table></div><p class="at-note">Won = first touch after the delivery was ours (clearance, header, interception). Lost duel = the attacker beat this player in the duel for the first contact.</p>`;

  const threats = report.defence?.threats || [];
  $("threatPanel").innerHTML = `${panelHead("Opposition players", "Who has hurt us from set plays")}<div class="at-table-wrap"><table class="sp-table"><thead><tr><th>Player</th><th>Club</th><th>Shots</th><th>xG</th><th>Goals</th></tr></thead><tbody>${threats.map((t) => `<tr><td>${escapeHtml(t.name)}</td><td>${escapeHtml(t.team || "")}</td><td>${t.shots}</td><td>${fmt(t.xg, 2)}</td><td>${t.goals ? `<span class="sp-pill sp-pill--goal">${t.goals}</span>` : 0}</td></tr>`).join("") || `<tr><td colspan="5">Nobody yet.</td></tr>`}</tbody></table></div>`;
}

/* ---------- goals ---------- */
function goalTable(rows, attacking) {
  if (!rows.length) return `<p class="at-empty">${attacking ? "No set-play goals scored" : "No set-play goals conceded"} in this window.</p>`;
  return `<div class="at-table-wrap"><table class="sp-table"><thead><tr><th>Match</th><th>Min</th><th>Type</th><th>Delivery</th><th>Scorer</th><th>xG</th><th>1st contact</th>${attacking ? "" : "<th>Beaten</th>"}</tr></thead><tbody>${rows.map((g) => `<tr>
    <td>${escapeHtml(g.opponent || "")} (${g.home ? "H" : "A"})</td><td>${g.minute}'</td>
    <td>${escapeHtml(g.typeLabel)}${g.routine ? `<br><small style="color:var(--muted)">${escapeHtml(g.routine)}</small>` : ""}</td>
    <td>${escapeHtml(g.taker)}${g.swing ? ` · ${g.swing}swing` : ""}${g.zone && g.type !== "penalty" ? `<br><small style="color:var(--muted)">${escapeHtml(g.zone)}</small>` : ""}</td>
    <td>${escapeHtml(g.scorer)} ${g.head ? `<span class="sp-pill sp-pill--head">Header</span>` : ""}<br><small style="color:var(--muted)">${escapeHtml(g.phase)}</small></td>
    <td>${fmt(g.xg, 2)}</td><td>${escapeHtml(g.firstContact)}</td>${attacking ? "" : `<td>${escapeHtml(g.beaten || "—")}</td>`}</tr>`).join("")}</tbody></table></div>`;
}
function renderGoals(report) {
  const f = report.attack?.goals || [];
  const a = report.defence?.goals || [];
  $("goalsFor").innerHTML = `${panelHead(`${f.length} goals`, "Scored")}${goalTable(f, true)}`;
  $("goalsAgainst").innerHTML = `${panelHead(`${a.length} goals`, "Conceded")}${goalTable(a, false)}`;
}

/* ---------- matches ---------- */
function renderTrend(report) {
  const rows = report.matches || [];
  if (!rows.length) { $("trendPanel").innerHTML = `${panelHead("Game by game", "Set-play xG")}<p class="at-empty">No matches.</p>`; return; }
  const W = 640; const H = 260; const mid = 130; const pad = 28;
  const max = Math.max(...rows.map((r) => Math.max(r.xgFor, r.xgAgainst)), 0.5);
  const bw = Math.min(26, (W - pad * 2) / rows.length - 4);
  const step = (W - pad * 2) / rows.length;
  const scale = (v) => (v / max) * (mid - 30);
  const bars = rows.map((r, i) => {
    const x = pad + i * step + (step - bw) / 2;
    const up = scale(r.xgFor); const down = scale(r.xgAgainst);
    const tip = `${r.opponent} (${r.home ? "H" : "A"}) ${r.score} · xG ${fmt(r.xgFor)} v ${fmt(r.xgAgainst)} · goals ${r.goalsFor}-${r.goalsAgainst}`;
    const gf = Array.from({ length: r.goalsFor }, (_, k) => `<circle cx="${x + bw / 2}" cy="${mid - up - 8 - k * 11}" r="4.5" fill="#f5c518"/>`).join("");
    const ga = Array.from({ length: r.goalsAgainst }, (_, k) => `<circle cx="${x + bw / 2}" cy="${mid + down + 8 + k * 11}" r="4.5" fill="#f87171"/>`).join("");
    return `<g><title>${escapeHtml(tip)}</title><rect x="${x}" y="${mid - up}" width="${bw}" height="${up}" rx="3" fill="url(#spUp)"/><rect x="${x}" y="${mid}" width="${bw}" height="${down}" rx="3" fill="url(#spDown)"/>${gf}${ga}
      <text x="${x + bw / 2}" y="${H - 4}" text-anchor="middle" fill="#8d9bb0" font-size="9">${escapeHtml(String(r.opponent || "").slice(0, 3).toUpperCase())}</text></g>`;
  }).join("");
  $("trendPanel").innerHTML = `${panelHead("Game by game", "Set-play xG for and against")}
    <svg class="sp-chart" viewBox="0 0 ${W} ${H}"><defs><linearGradient id="spUp" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#f5c518"/><stop offset="1" stop-color="#f5c518"/></linearGradient><linearGradient id="spDown" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f87171"/><stop offset="1" stop-color="#f87171"/></linearGradient></defs>
    <line x1="${pad}" y1="${mid}" x2="${W - pad}" y2="${mid}" stroke="rgba(148,163,184,0.35)"/>
    <text x="${pad}" y="14" fill="#f5c518" font-size="11" font-weight="700">For ↑</text><text x="${pad}" y="${H - 18}" fill="#f87171" font-size="11" font-weight="700">Against ↓</text>${bars}</svg>
    <p class="at-note">Bars = non-penalty set-play xG. Dots = set-play goals (penalties included).</p>`;
}
function renderMinutes(report) {
  const rows = report.minutes || [];
  const max = Math.max(...rows.map((r) => Math.max(r.xgFor, r.xgAgainst)), 0.3);
  const body = rows.map((r, i) => `<div class="at-row" style="grid-template-columns:4.2rem 1fr 1fr 5.6rem"><div class="at-row__label">${escapeHtml(r.label)}</div>
    <div class="at-bar" style="direction:rtl"><span style="width:${(r.xgAgainst / max) * 100}%;background:#f87171;animation-delay:${i * 50}ms"></span></div>
    <div class="at-bar"><span style="width:${(r.xgFor / max) * 100}%;background:#f5c518;animation-delay:${i * 50}ms"></span></div>
    <div class="at-row__meta">${r.goalsFor}–${r.goalsAgainst}</div></div>`).join("");
  $("minutePanel").innerHTML = `${panelHead("When it happens", "By 15-minute block")}<div class="sp-legend" style="margin:0 0 .4rem"><span><i style="background:#f87171"></i>xG against</span><span><i style="background:#f5c518"></i>xG for</span><span>Goals for–against</span></div>${body}<p class="at-note">Late concessions point to concentration and fresh legs on the block; early ones to the first set play of the game.</p>`;
}
function renderMatches(report) {
  const rows = report.matches || [];
  $("matchPanel").innerHTML = `${panelHead("Every Port Vale game in the window", "Match by match")}<div class="at-table-wrap"><table class="sp-table"><thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>Set plays for</th><th>Corners for</th><th>xG for</th><th>Goals for</th><th>Set plays against</th><th>Corners against</th><th>xG against</th><th>Goals against</th></tr></thead><tbody>${[...rows].reverse().map((r) => `<tr>
    <td>${escapeHtml(String(r.date || "").slice(0, 10))}</td><td>${escapeHtml(r.opponent)} (${r.home ? "H" : "A"})</td><td><span class="sp-pill sp-pill--${r.result}">${r.result}</span> ${escapeHtml(r.score)}</td>
    <td>${r.nFor}</td><td>${r.cornersFor}</td><td>${fmt(r.xgFor)}</td><td class="${r.goalsFor ? "sp-good" : ""}">${r.goalsFor}</td>
    <td>${r.nAgainst}</td><td>${r.cornersAgainst}</td><td>${fmt(r.xgAgainst)}</td><td class="${r.goalsAgainst ? "sp-bad" : ""}">${r.goalsAgainst}</td></tr>`).join("")}</tbody></table></div>`;
}

/* ---------- league ---------- */
const TABLE_COLS = [
  ["xgDiff", "xG diff / g", 2], ["xgFor", "xG for / g", 2], ["xgAgainst", "xG ag / g", 2],
  ["goalsForTotal", "Goals for", 0], ["goalsAgainstTotal", "Goals ag", 0], ["goalDiffTotal", "Goal diff", 0],
  ["cornersFor", "Corners / g", 1], ["xgPerCornerFor", "xG / corner", 3], ["xgPerCornerAgainst", "xG / corner ag", 3],
  ["fcAttack", "1st contact att", "pct"], ["fcDefence", "1st contact def", "pct"], ["spShareFor", "% goals from SP", "pct"],
];
function renderTable(report) {
  const rows = [...(report.table || [])];
  const { key, dir } = state.sort;
  rows.sort((a, b) => ((Number(a[key] ?? -1e9) - Number(b[key] ?? -1e9)) * dir) || String(a.club).localeCompare(b.club));
  const head = TABLE_COLS.map(([k, label]) => `<th data-sort="${k}" class="${k === key ? "is-sorted" : ""}">${escapeHtml(label)}${k === key ? (dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("");
  const body = rows.map((r, i) => `<tr class="${r.focus ? "at-focus" : ""}"><td>${i + 1}</td><td>${escapeHtml(r.club)}</td>${TABLE_COLS.map(([k, , d]) => `<td>${d === "pct" ? pct(r[k]) : k === "goalDiffTotal" ? `${r[k] > 0 ? "+" : ""}${r[k]}` : fmt(r[k], d)}</td>`).join("")}<td>${r.played}</td></tr>`).join("");
  $("tablePanel").innerHTML = `${panelHead(`${report.season} season · every club · click a column to sort`, "League Two set-play table")}<div class="at-table-wrap"><table class="sp-table"><thead><tr><th>#</th><th>Club</th>${head}<th>Pld</th></tr></thead><tbody>${body}</tbody></table></div><p class="at-note">Non-penalty set plays. xG is Impect shot xG; goals come from shots, so own goals are not counted.</p>`;
}
function renderTypeValue(report) {
  const rows = report.typeValue || [];
  const max = Math.max(...rows.map((r) => r.xgPer), 0.01);
  const ours = Object.fromEntries((report.attack?.buckets || []).map((b) => [b.id, b]));
  const body = rows.map((r, i) => barRow(r.label, (r.xgPer / max) * 100, `${fmt(r.xgPer, 3)} xG each · ${fmt(r.goalPct, 1)}% scored · us ${ours[r.id] ? fmt(ours[r.id].xgPer, 3) : "—"}`, "#8b9bb0", i * 50)).join("");
  $("typeValuePanel").innerHTML = `${panelHead("League Two, every match this season", "What each set play is worth")}${body}<p class="at-note">The value of one set play of each kind across the whole league, with ours alongside. Use it to decide which routines deserve training time.</p>`;
  $("typeValuePanel").style.marginTop = "1rem";
}

/* ---------- render ---------- */
function renderEmpty(report) {
  document.body.classList.add("at-is-empty");
  $("hero").innerHTML = `<div class="at-hero__empty"><h2>Not in the data lake yet</h2><p>${escapeHtml(report.message || "Nothing is saved for this view yet.")}</p></div>`;
  setStatus("Reading the data lake.");
}
function render(report) {
  state.report = report;
  clearTimeout(lakeTimer);
  if (report.ready === false) { renderEmpty(report); return; }
  document.body.classList.remove("at-is-empty");
  const steps = [renderHero, renderInsights, renderLadder, renderPlan, renderAttack, renderDefence, renderPlayers, renderGoals, renderTrend, renderMinutes, renderMatches, renderTable, renderTypeValue];
  steps.forEach((fn) => { try { fn(report); } catch (err) { console.error(fn.name, err); } });
  const saved = report.generatedAt ? ` · saved ${new Date(report.generatedAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "";
  setStatus(`${report.competition || "League Two"} ${report.season || ""} · ${report.matchCount || 0} Port Vale matches in this window · league benchmarks from ${report.leagueMatches || 0} matches · ${fmt(report.pointsPerGoal, 2)} points per goal this season · read from the data lake${saved}.`);
}
async function loadReport() {
  setStatus("Reading the data lake…");
  const params = new URLSearchParams({ season: state.season, scope: state.scope });
  if (state.scope === "match" && state.matchId) params.set("matchId", String(state.matchId));
  render(await getJson(`/api/set-plays/report?${params.toString()}`));
}
async function loadFixtures() {
  const payload = await getJson(`/api/set-plays/fixtures?season=${encodeURIComponent(state.season)}`);
  state.fixtures = payload.fixtures || [];
  if (!state.matchId || !state.fixtures.some((row) => row.matchId === state.matchId)) state.matchId = payload.defaultMatchId;
  renderFixtures();
}
const TAB_ALIASES = { plan: "overview", players: "attack", goals: "attack" };
function showTab(id, { scroll = true } = {}) {
  const tabs = [...document.querySelectorAll(".sp-tab")];
  const target = TAB_ALIASES[id] || id;
  const chosen = tabs.find((tab) => tab.id === target) ? target : "overview";
  tabs.forEach((tab) => { tab.hidden = tab.id !== chosen; tab.classList.toggle("is-shown", tab.id === chosen); });
  document.querySelectorAll("#sectionNav a").forEach((link) => {
    const on = link.getAttribute("href") === `#${chosen}`;
    link.classList.toggle("is-active", on);
    link.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (location.hash !== `#${chosen}`) history.replaceState(null, "", `#${chosen}`);
  if (scroll) {
    const nav = $("sectionNav");
    const top = nav.getBoundingClientRect().top + window.scrollY;
    if (window.scrollY > top) window.scrollTo({ top, behavior: "auto" });
  }
}
function bindNav() {
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    const id = link.getAttribute("href").slice(1);
    if (!document.getElementById(TAB_ALIASES[id] || id)?.classList.contains("sp-tab")) return;
    event.preventDefault();
    showTab(id);
  });
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1), { scroll: false }));
  showTab(location.hash.slice(1), { scroll: false });
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
    state.season = button.dataset.season; state.matchId = null;
    renderSeasons({ seasons: [...$("seasonToggle").querySelectorAll("[data-season]")].map((item) => ({ value: item.dataset.season, label: item.textContent })) });
    try { await loadFixtures(); await loadReport(); } catch (err) { setStatus(err.message); }
  });
  $("matchSelect").addEventListener("change", async () => {
    state.matchId = Number($("matchSelect").value);
    try { await loadReport(); } catch (err) { setStatus(err.message); }
  });
  document.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-map]");
    if (chip && state.report) {
      state[chip.dataset.map] = chip.dataset.filter;
      if (chip.dataset.map === "attackFilter") renderMapPanel("attackMap", state.report.attack?.deliveries || [], "attackFilter", true);
      else renderMapPanel("defenceMap", state.report.defence?.deliveries || [], "defenceFilter", false);
      return;
    }
    const th = event.target.closest("#tablePanel th[data-sort]");
    if (th && state.report) {
      const key = th.dataset.sort;
      state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : -1 };
      renderTable(state.report);
    }
  });
}
async function boot() {
  bindControls();
  bindNav();
  try {
    const meta = await getJson("/api/set-plays/meta");
    state.season = meta.defaultSeason || (meta.seasons?.[0]?.value) || "";
    renderSeasons(meta);
    await loadFixtures();
    await loadReport();
  } catch (err) { setStatus(err.message || "Set plays could not load."); }
}
boot();
