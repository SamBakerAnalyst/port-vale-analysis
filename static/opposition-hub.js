/* Opposition Hub — one page on an opponent. Reads /api/opposition-hub (data lake only). */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  meta: null, season: null, window: "season", squadId: null, report: null,
  mapFamily: "all", concededFamily: "all", zoneSide: "start", squadBand: "all", squadSort: "minutes",
  poll: null, mapView: "start", chainId: null, progSort: "prog90",
  spf: { type: "corner", side: "all", style: "all", swing: "all", outcome: "all", half: "all", taker: "all", lines: true },
};
try { if (["start", "end", "arrows"].includes(localStorage.getItem("ohMapView"))) state.mapView = localStorage.getItem("ohMapView"); } catch (_) { /* private mode */ }
let svgSeq = 0;

const FAMILY_LABELS = { all: "All", cross: "Crosses", pass: "Passes", dribble: "Dribbles", shot: "Shots", setPiece: "Set pieces", regain: "Ball wins", other: "Other" };
const FAMILY_COLORS = { cross: "#38bdf8", pass: "#34d399", dribble: "#f97316", shot: "#ef4444", setPiece: "#c084fc", regain: "#fbbf24", other: "#94a3b8" };
const BANDS = [["all", "All"], ["gk", "Goalkeepers"], ["def", "Defenders"], ["mid", "Midfield"], ["attack", "Forwards"]];
const OUTCOME = {
  goal: { color: "#f5c518", label: "Goal" }, shot: { color: "#f97316", label: "Shot" },
  won: { color: "#34d399", label: "Won first contact" }, lost: { color: "#f87171", label: "Lost first contact" },
  none: { color: "#94a3b8", label: "No contact" },
};

/* ---------- helpers ---------- */
function esc(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function fmt(value, digits = 2) { const n = Number(value); return value != null && Number.isFinite(n) ? n.toFixed(digits) : "—"; }
function signed(value, digits = 2) { const n = Number(value); return value != null && Number.isFinite(n) ? `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(digits)}` : "—"; }
function ordinal(n) { if (!n) return "—"; const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"; return `${n}${s}`; }
function metricValue(row) { if (!row || row.value == null) return "—"; return row.pct ? `${Math.round(row.value)}%` : fmt(row.value, row.digits ?? 2); }
function quarter(of) { return Math.max(1, Math.min(6, Math.floor((of || 24) / 4))); }
/* Opponent ranks are coloured by what they mean for us: their strengths red, their weaknesses green. */
function oppTone(rank, of) { if (!rank) return "none"; const q = quarter(of); return rank <= q ? "danger" : rank > (of || 24) - q ? "chance" : "mid"; }
function valeTone(rank, of) { if (!rank) return "none"; const q = quarter(of); return rank <= q ? "chance" : rank > (of || 24) - q ? "danger" : "mid"; }
function rankChip(rank, of, tone) { return rank ? `<span class="oh-rk oh-rk--${tone}">${ordinal(rank)}<small>/${of || 24}</small></span>` : `<span class="oh-rk oh-rk--none">—</span>`; }
function oppRank(row) { return row ? rankChip(row.rank, row.of, oppTone(row.rank, row.of)) : rankChip(null); }
function shortDate(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" }); }
function longDate(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : `${d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })} · ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })}`; }
function resPill(result) { return `<span class="oh-res oh-res--${esc(result)}">${esc(result)}</span>`; }
function badge(url, name, size = 28) { return `<img class="oh-badge" src="${esc(url)}" alt="" width="${size}" height="${size}" loading="lazy" onerror="this.style.visibility='hidden'" title="${esc(name || "")}">`; }
function panelHead(kicker, title, extra = "") { return `<div class="at-panel__head oh-head"><div><p class="at-panel__kicker">${esc(kicker)}</p><h2 class="at-panel__title">${esc(title)}</h2></div>${extra}</div>`; }
function empty(text) { return `<p class="at-empty">${esc(text)}</p>`; }
function setStatus(text) { $("statusBar").textContent = text; }
function toggle(items, active, attr) { return `<div class="at-toggle">${items.map(([value, label]) => `<button type="button" class="at-toggle__btn${active === value ? " at-toggle__btn--active" : ""}" data-${attr}="${esc(value)}">${esc(label)}</button>`).join("")}</div>`; }
function bar(share, color = "linear-gradient(90deg,#f59e0b,#f5c518)") { return `<div class="at-bar"><span style="width:${Math.max(0, Math.min(100, Number(share) || 0)).toFixed(1)}%;background:${color}"></span></div>`; }
async function getJson(url, options) {
  const response = await fetch(url, { credentials: "same-origin", ...(options || {}) });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); if (body.detail) detail = String(body.detail); } catch (_err) { /* keep default */ }
    throw new Error(detail);
  }
  return response.json();
}
function metric(id) { return state.report?.metrics?.[id]; }
function tile(row, label, note = "") {
  if (!row) return "";
  return `<div class="oh-tile oh-tile--${oppTone(row.rank, row.of)}"><span class="oh-tile__label">${esc(label || row.label)}</span><strong>${metricValue(row)}</strong><span class="oh-tile__foot">${oppRank(row)}<em>avg ${row.pct ? `${Math.round(row.avg)}%` : fmt(row.avg, row.digits)}</em></span>${note ? `<small>${esc(note)}</small>` : ""}</div>`;
}

/* ---------- pitches ---------- */
function toSvg(x, y) { return { x: ((Number(x) + 52.5) / 105) * 1050, y: ((34 - Number(y)) / 68) * 680 }; }
function pitch(inner, label, defs = "", attackLabel = "ATTACK") {
  const id = `oh${++svgSeq}`;
  const stripes = Array.from({ length: 10 }, (_, i) => `<rect x="${i * 105}" y="0" width="105" height="680" fill="${i % 2 ? "#123222" : "#143826"}"/>`).join("");
  const line = "rgba(226,245,233,0.55)";
  return `<svg class="at-pitch" viewBox="0 0 1050 680" role="img" aria-label="${esc(label)}">
    <defs>${defs.replaceAll("{id}", id)}</defs>${stripes}
    <g fill="none" stroke="${line}" stroke-width="2.5">
      <rect x="8" y="8" width="1034" height="664" rx="2"/><line x1="525" y1="8" x2="525" y2="672"/><circle cx="525" cy="340" r="70"/>
      <rect x="8" y="186" width="130" height="308"/><rect x="912" y="186" width="130" height="308"/>
      <rect x="8" y="258" width="48" height="164"/><rect x="994" y="258" width="48" height="164"/>
      <path d="M138 290 A70 70 0 0 1 138 390"/><path d="M912 290 A70 70 0 0 0 912 390"/>
    </g>
    <path d="M960 24 l30 0 m-10 -8 l10 8 l-10 8" stroke="rgba(245,197,24,0.8)" stroke-width="3" fill="none"/>
    <text x="950" y="30" text-anchor="end" fill="rgba(245,197,24,0.8)" font-size="15" font-family="Manrope" font-weight="700">${esc(attackLabel)}</text>
    ${inner.replaceAll("{id}", id)}
  </svg>`;
}
function arrowDefs() { return Object.values(FAMILY_COLORS).map((color, i) => `<marker id="{id}a${i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${color}"/></marker>`).join(""); }
function arrowLayer(passes) {
  const colors = Object.values(FAMILY_COLORS);
  const max = Math.max(...passes.map((row) => Number(row.pxt) || 0), 0.05);
  return passes.map((row) => {
    const a = toSvg(row.x1, row.y1); const b = toSvg(row.x2, row.y2);
    const color = FAMILY_COLORS[row.family] || FAMILY_COLORS.other;
    const idx = Math.max(0, colors.indexOf(color));
    const tip = `${row.label} · ${fmt(row.pxt, 3)} threat · ${row.player || ""}${row.opponent ? ` vs ${row.opponent}` : ""}`;
    return `<g data-tip="${esc(tip)}"><line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${color}" stroke-width="${(1.6 + (Number(row.pxt) / max) * 6).toFixed(1)}" stroke-linecap="round" opacity="0.9" marker-end="url(#{id}a${idx})"/><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="4" fill="${color}"/><line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="transparent" stroke-width="14"/></g>`;
  }).join("");
}
const ZONE_X = [-52.5, -40, -18, 0, 18, 35, 52.5];
const ZONE_Y = [34, 13.84, -13.84, -34];
const ZONE_RECTS = {
  GKL: [0, 1, 0, 1], GKC: [0, 1, 1, 2], GKR: [0, 1, 2, 3],
  FBL: [1, 2, 0, 1], CB: [1, 2, 1, 2], FBR: [1, 2, 2, 3],
  WL: [2, 4, 0, 1], DM: [2, 3, 1, 2], CM: [3, 4, 1, 2], WR: [2, 4, 2, 3],
  IBWL: [4, 6, 0, 1], AM: [4, 5, 1, 2], IB: [5, 6, 1, 2], IBWR: [4, 6, 2, 3],
};
const ZONE_NAMES = { GKL: "Keeper", GKC: "Keeper", GKR: "Keeper", IBWL: "In behind wide", IBWR: "In behind wide", IB: "In behind", AM: "Attacking mid", CM: "Centre mid", DM: "Defensive mid", WL: "Wide", WR: "Wide", FBL: "Full-back", FBR: "Full-back", CB: "Centre-backs" };
function zoneHeatmap(zones, { rgb = "245,197,24", label = "Threat by zone" } = {}) {
  const byId = Object.fromEntries((zones || []).map((row) => [row.id, row]));
  const max = Math.max(...Object.keys(ZONE_RECTS).map((id) => Number(byId[id]?.share) || 0), 0.1);
  const ranked = Object.keys(ZONE_RECTS).filter((id) => Number(byId[id]?.share) > 0).sort((a, b) => byId[b].share - byId[a].share);
  const gap = 3;
  const cells = Object.entries(ZONE_RECTS).map(([id, [c0, c1, r0, r1]]) => {
    const a = toSvg(ZONE_X[c0], ZONE_Y[r0]); const b = toSvg(ZONE_X[c1], ZONE_Y[r1]);
    const x = a.x + gap; const y = a.y + gap; const w = b.x - a.x - gap * 2; const h = b.y - a.y - gap * 2;
    const row = byId[id]; const share = Number(row?.share) || 0;
    const heat = Math.pow(share / max, 1.15);
    const alpha = share ? 0.06 + heat * 0.86 : 0.03;
    const dark = alpha > 0.5;
    const ink = dark ? "#10141b" : "rgba(238,242,247,0.92)";
    const sub = dark ? "rgba(16,20,27,0.72)" : "rgba(238,242,247,0.55)";
    const cx = x + w / 2; const cy = y + h / 2;
    const isGk = id.startsWith("GK");
    const big = isGk ? 20 : 26 + heat * 22;
    const rank = ranked.indexOf(id);
    const tip = row ? `${row.label}: ${row.share}% of threat · ${fmt(row.perGame, 3)} a game` : `${ZONE_NAMES[id]}: no threat`;
    return `<g class="oh-zone" data-tip="${esc(tip)}">
      <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="10" fill="rgba(${rgb},${alpha.toFixed(2)})" stroke="${rank === 0 ? `rgb(${rgb})` : "rgba(255,255,255,0.06)"}" stroke-width="${rank === 0 ? 3 : 1}"/>
      ${Math.round(share) ? `<text x="${cx.toFixed(1)}" y="${(cy + (isGk ? 4 : big * 0.28)).toFixed(1)}" text-anchor="middle" fill="${ink}" font-size="${big.toFixed(0)}" font-weight="800" font-family="JetBrains Mono, monospace">${Math.round(share)}%</text>` : ""}
      ${isGk ? "" : `<text x="${cx.toFixed(1)}" y="${(cy + big * 0.28 + 22).toFixed(1)}" text-anchor="middle" fill="${sub}" font-size="13" font-weight="700" letter-spacing="1.2" font-family="Manrope, sans-serif">${esc(ZONE_NAMES[id].toUpperCase())}</text>`}
      ${rank >= 0 && rank < 3 && !isGk ? `<circle cx="${(x + 20).toFixed(1)}" cy="${(y + 20).toFixed(1)}" r="12" fill="${dark ? "rgba(16,20,27,0.85)" : `rgb(${rgb})`}"/><text x="${(x + 20).toFixed(1)}" y="${(y + 25).toFixed(1)}" text-anchor="middle" fill="${dark ? `rgb(${rgb})` : "#10141b"}" font-size="13" font-weight="800" font-family="Manrope, sans-serif">${rank + 1}</text>` : ""}
    </g>`;
  }).join("");
  const line = "rgba(226,245,233,0.22)";
  return `<svg class="at-pitch oh-heat" viewBox="0 0 1050 680" role="img" aria-label="${esc(label)}">
    <rect width="1050" height="680" rx="14" fill="#0c1511"/>
    ${cells}
    <g fill="none" stroke="${line}" stroke-width="2" pointer-events="none">
      <rect x="8" y="8" width="1034" height="664" rx="2"/><line x1="525" y1="8" x2="525" y2="672"/><circle cx="525" cy="340" r="70"/>
      <rect x="8" y="186" width="130" height="308"/><rect x="912" y="186" width="130" height="308"/>
      <rect x="8" y="258" width="48" height="164"/><rect x="994" y="258" width="48" height="164"/>
    </g>
  </svg>`;
}
function heatKey(rgb, direction, text) {
  return `<div class="oh-heatkey"><b>${esc(direction)} <span aria-hidden="true">→</span></b><span>Less</span><i style="background:linear-gradient(90deg, rgba(${rgb},0.08), rgba(${rgb},0.9))"></i><span>More</span><em>${esc(text)}</em></div>`;
}
const HP = { w: 680, h: 360, top: 24 };
function hp(x, y) { return { x: (34 - Number(y)) * 10, y: HP.top + (52.5 - Number(x)) * 10 }; }
function halfPitch(inner, label) {
  const line = "rgba(226,245,233,0.55)"; const t = HP.top;
  const stripes = Array.from({ length: 7 }, (_, i) => `<rect x="0" y="${t + i * 50}" width="${HP.w}" height="50" fill="${i % 2 ? "#0f1f17" : "#11241a"}"/>`).join("");
  return `<svg class="oh-half" viewBox="0 0 ${HP.w} ${HP.h + t}" role="img" aria-label="${esc(label)}">
    <rect width="${HP.w}" height="${HP.h + t}" fill="#0e1c15"/>${stripes}
    <g fill="none" stroke="${line}" stroke-width="2"><rect x="2" y="${t}" width="${HP.w - 4}" height="${HP.h - 2}"/><rect x="138.4" y="${t}" width="403.2" height="165"/><rect x="248.4" y="${t}" width="183.2" height="55"/><path d="M266.9 ${t + 165} A91.5 91.5 0 0 0 413.1 ${t + 165}"/></g>
    <rect x="303.4" y="${t - 14}" width="73.2" height="14" fill="rgba(255,255,255,0.08)" stroke="${line}" stroke-width="2"/>
    <text x="340" y="13" text-anchor="middle" fill="rgba(232,237,244,0.7)" font-size="13" font-family="Barlow Condensed" font-weight="600" letter-spacing="3">${esc(label.toUpperCase())}</text>${inner}</svg>`;
}
function deliveryLayer(points, showLines = true) {
  const order = { none: 0, lost: 1, won: 2, shot: 3, goal: 4 };
  return [...points].sort((a, b) => order[a.outcome] - order[b.outcome]).map((p) => {
    const s = hp(p.sx, p.sy); const e = hp(p.dx, p.dy);
    const out = OUTCOME[p.outcome] || OUTCOME.none;
    const big = p.outcome === "goal" || p.outcome === "shot";
    const who = big ? p.shooter : p.contact;
    const tip = `${p.type.replace("_", " ")} · ${p.taker}${p.swing ? ` (${p.swing}swing)` : ""} · ${out.label}${who ? ` — ${who}` : ""}${p.opponent ? ` · vs ${p.opponent}` : ""}${p.minute ? ` ${p.minute}'` : ""}`;
    const lineOk = showLines && p.sub !== "short" && Math.abs(s.y - e.y) + Math.abs(s.x - e.x) > 8;
    return `<g data-tip="${esc(tip)}">${lineOk ? `<line x1="${s.x.toFixed(1)}" y1="${s.y.toFixed(1)}" x2="${e.x.toFixed(1)}" y2="${e.y.toFixed(1)}" stroke="${out.color}" stroke-opacity="${big ? 0.75 : 0.2}" stroke-width="${big ? 2 : 1.2}"/>` : ""}<circle cx="${e.x.toFixed(1)}" cy="${e.y.toFixed(1)}" r="${p.outcome === "goal" ? 9 : big ? 7 : 4.5}" fill="${out.color}" stroke="#0b0f15" stroke-width="1.2"/><circle cx="${e.x.toFixed(1)}" cy="${e.y.toFixed(1)}" r="10" fill="transparent"/></g>`;
  }).join("");
}

/* ---------- hero ---------- */
function renderHero(r) {
  const pos = r.position || {};
  const picked = stripFixture();
  const fx = picked && picked.squadId === r.club.id
    ? { valeHome: picked.home, played: picked.played, date: picked.date, score: picked.score, result: picked.result }
    : r.fixture;
  const sq = r.squad || {};
  let fixtureLine = "No Port Vale fixture on file";
  if (fx && fx.score) {
    const [us, them] = fx.score.split("-");
    fixtureLine = `${fx.valeHome ? `Port Vale ${us}–${them} ${r.club.name}` : `${r.club.name} ${them}–${us} Port Vale`} · ${longDate(fx.date)}`;
  } else if (fx) {
    fixtureLine = `${fx.valeHome ? `Port Vale vs ${r.club.name}` : `${r.club.name} vs Port Vale`} · ${fx.played ? "played" : longDate(fx.date)}`;
  }
  const spDiff = metric("sp:xgFor") && metric("sp:xgAgainst") ? Number(metric("sp:xgFor").value) - Number(metric("sp:xgAgainst").value) : null;
  $("hero").innerHTML = `
    <div class="oh-hero__id">
      ${badge(r.club.badge, r.club.name, 96)}
      <div>
        <p class="at-kicker">${esc(fx && !fx.played ? "Next opponent" : "Opponent")} · ${esc(r.season)}</p>
        <h2 class="oh-hero__name">${esc(r.club.name)}</h2>
        <p class="oh-hero__fixture">${esc(fixtureLine)}</p>
        <p class="oh-hero__meta">${pos.position ? `<b>${ordinal(pos.position)}</b> in League Two · ${pos.pts} pts from ${pos.played}` : ""}${sq.manager ? ` · Manager <b>${esc(sq.manager)}</b>` : ""}${(sq.formationUsage || [])[0] ? ` · Usually <b>${esc(sq.formationUsage[0].formation)}</b>` : ""}</p>
        <div class="oh-form">${(r.record.form || []).map(resPill).join("")}<span>${r.window === "last6" ? "Last 6" : "Season"}: ${r.record.w}W ${r.record.d}D ${r.record.l}L · ${r.record.gf}–${r.record.ga}</span></div>
      </div>
    </div>
    <div class="oh-hero__tiles">
      <div class="oh-tile"><span class="oh-tile__label">Points a game</span><strong>${fmt(r.record.ppg)}</strong><span class="oh-tile__foot"><em>${r.games} games</em></span></div>
      ${tile(metric("xgFor"), "npxG for / game")}
      ${tile(metric("xgAgainst"), "npxG against / game")}
      ${tile(metric("threatFor"), "Threat created / game")}
      <div class="oh-tile oh-tile--${spDiff == null ? "none" : spDiff >= 0 ? "danger" : "chance"}"><span class="oh-tile__label">Set-play xG diff / game</span><strong>${signed(spDiff)}</strong><span class="oh-tile__foot"><em>for ${metricValue(metric("sp:xgFor"))} · against ${metricValue(metric("sp:xgAgainst"))}</em></span></div>
      ${tile(metric("aerialPct"), "Aerial duels won")}
    </div>
    <p class="oh-legend"><span class="oh-rk oh-rk--danger">1st<small>/24</small></span> their strength — a threat to us <span class="oh-rk oh-rk--chance">22nd<small>/24</small></span> their weakness — a chance for us</p>`;
}

/* ---------- game plan ---------- */
function renderPlan(r) {
  const plan = r.plan || {};
  const list = (rows, tone) => rows.length ? `<ol class="oh-plan__list">${rows.map((row) => `<li><span class="oh-rk oh-rk--${tone}">${ordinal(row.rank)}</span><div><b>${esc(row.label)}</b><p>${esc(row.text)}</p></div></li>`).join("")}</ol>` : empty("Nothing stands out in the top or bottom quarter of the league.");
  $("strengthPanel").innerHTML = `${panelHead("Their strengths", "Stop these")}${list(plan.strengths || [], "danger")}`;
  $("weaknessPanel").innerHTML = `${panelHead("Their weaknesses", "Where we hurt them")}${list(plan.weaknesses || [], "chance")}`;
  $("notes").innerHTML = (plan.notes || []).map((note) => `<article class="at-insight${note.tone === "good" ? " at-insight--good" : note.tone === "bad" ? " at-insight--bad" : ""}"><h3>${esc(note.title)}</h3><p>${esc(note.text)}</p></article>`).join("");
}

/* ---------- matchup ---------- */
function renderMatchup(r) {
  const groups = [
    ["theirAttack", `${r.club.name} attack vs our defence`],
    ["ourAttack", `Our attack vs ${r.club.name} defence`],
    ["battle", "Duels head to head"],
  ];
  const html = groups.map(([side, title]) => {
    const rows = (r.matchup || []).filter((row) => row.side === side);
    if (!rows.length) return "";
    const vale = rows.filter((row) => row.edge === "vale").length;
    const them = rows.filter((row) => row.edge === "them").length;
    return `<article class="card oh-mu"><div class="oh-head"><div><p class="at-panel__kicker">${vale > them ? "Port Vale edge" : them > vale ? `${esc(r.club.name)} edge` : "Even"}</p><h2 class="at-panel__title">${esc(title)}</h2></div><div class="oh-mu__score"><b class="oh-mu__them">${them}</b><span>–</span><b class="oh-mu__vale">${vale}</b></div></div>
      <div class="oh-mu__cols"><span>${badge(r.club.badge, r.club.name, 20)} Them</span><span></span><span>Us ${badge(r.vale.badge, "Port Vale", 20)}</span></div>
      ${rows.map((row) => {
        const of = row.them.of || 24;
        const themStrength = 100 * (1 - (row.them.rank - 1) / Math.max(1, of - 1));
        const usStrength = 100 * (1 - (row.us.rank - 1) / Math.max(1, (row.us.of || 24) - 1));
        return `<div class="oh-mu__row oh-mu__row--${row.edge}">
          <div class="oh-mu__side"><b>${metricValue(row.them)}</b>${rankChip(row.them.rank, row.them.of, oppTone(row.them.rank, row.them.of))}</div>
          <div class="oh-mu__mid"><span class="oh-mu__label" data-tip="${esc(`Them: ${row.them.label} · Us: ${row.us.label}`)}">${esc(row.label)}</span><div class="oh-mu__bars"><i class="oh-mu__bar oh-mu__bar--them" style="width:${(themStrength / 2).toFixed(1)}%"></i><i class="oh-mu__bar oh-mu__bar--vale" style="width:${(usStrength / 2).toFixed(1)}%"></i></div></div>
          <div class="oh-mu__side oh-mu__side--us">${rankChip(row.us.rank, row.us.of, valeTone(row.us.rank, row.us.of))}<b>${metricValue(row.us)}</b></div>
        </div>`;
      }).join("")}
      <p class="at-note">Bars show league standing — longer is better for that club.</p></article>`;
  }).join("");
  $("matchupPanel").innerHTML = html || empty("Not enough saved data for a matchup yet.");
}

/* ---------- squad ---------- */
function spWeight(p) {
  const sp = p.setPlays || {};
  return (sp.taker?.deliveries || 0) + (sp.target?.fcWon || 0) * 3 + (sp.defending?.won || 0);
}
function setPlayCell(p) {
  const sp = p.setPlays || {};
  const out = [];
  if (sp.taker) {
    const t = sp.taker;
    const swing = t.inswing || t.outswing ? (t.inswing >= t.outswing ? "inswing" : "outswing") : "";
    out.push(`<span class="oh-sp oh-sp--taker" data-tip="${esc(`Takes ${t.deliveries}: ${t.corners} corners, ${t.freeKicks} free kicks${t.foot ? ` · ${t.foot === "L" ? "left" : "right"} foot` : ""}${swing ? ` · mostly ${swing}` : ""}${t.topZone ? ` · aims at ${t.topZone.toLowerCase()}` : ""}${t.goals ? ` · ${t.goals} goals from his deliveries` : ""}`)}">Takes ${t.deliveries}</span>`);
  }
  if (sp.target) {
    const t = sp.target;
    out.push(`<span class="oh-sp oh-sp--target" data-tip="${esc(`Attacking set plays: ${t.fcWon} first contacts won · ${t.shots} shots · ${t.goals} goals · ${fmt(t.xg)} xG`)}">Wins ${t.fcWon}${t.goals ? ` · ${t.goals}G` : ""}</span>`);
  }
  if (sp.defending) {
    const d = sp.defending;
    const weak = d.lostOnGoal > 0 || (d.lost >= 3 && (d.winPct ?? 100) < 60);
    out.push(`<span class="oh-sp oh-sp--def${weak ? " oh-sp--weak" : ""}" data-tip="${esc(`Defending set plays: won ${d.won}, lost ${d.lost}${d.winPct != null ? ` (${d.winPct}% won)` : ""} · lost duels leading to ${d.lostOnShot} shots and ${d.lostOnGoal} goals${weak ? " — one to attack" : ""}`)}">Def ${d.won}–${d.lost}</span>`);
  }
  return out.join("");
}
function squadSorted(players) {
  const key = state.squadSort;
  const rows = players.filter((p) => state.squadBand === "all" || p.band === state.squadBand);
  const dir = key === "name" || key === "shirt" ? 1 : -1;
  const value = (p) => (key === "setPlays" ? spWeight(p) || null : p[key]);
  return rows.sort((a, b) => {
    const va = value(a) ?? (dir > 0 ? Infinity : -Infinity); const vb = value(b) ?? (dir > 0 ? Infinity : -Infinity);
    if (typeof va === "string") return va.localeCompare(vb);
    return dir * (va - vb) || (b.minutes - a.minutes);
  });
}
function logCell(entry) {
  if (entry === null || entry === undefined) return `<td class="oh-log oh-log--out" title="Not in the squad">·</td>`;
  if (!entry.min) return `<td class="oh-log oh-log--bench" title="Unused sub">B</td>`;
  const marks = `${entry.g ? `<i class="oh-log__g" title="${entry.g} goal${entry.g > 1 ? "s" : ""}"></i>` : ""}${entry.a ? `<i class="oh-log__a" title="${entry.a} assist${entry.a > 1 ? "s" : ""}"></i>` : ""}`;
  return `<td class="oh-log ${entry.start ? (entry.min >= 85 ? "oh-log--full" : "oh-log--start") : "oh-log--sub"}" title="${entry.start ? "Started" : "Came on"} · ${entry.min} mins">${entry.min}${marks}</td>`;
}
function renderSquad(r) {
  const sq = r.squad || {};
  const panel = $("squadPanel");
  if (!sq.ready) {
    const build = sq.build || {};
    const running = build.status === "running";
    panel.innerHTML = `${panelHead("Squad", "Squad data not built yet")}<p class="oh-muted">Squad, minutes, line-ups and style come from the Pre-Match report for ${esc(r.club.name)}. ${running ? "It is building now — this panel fills in on its own in a minute or two." : build.status === "failed" ? `The last build failed: ${esc(build.detail || "")}` : "Build it once and it is saved for everyone."}</p>${running ? `<p class="oh-building">Building from Impect…</p>` : `<button type="button" class="oh-btn" id="buildSquad">Build squad data</button>`}`;
    $("xiPanel").innerHTML = `${panelHead("Line-ups", "Previous XIs")}${empty("Waiting for squad data.")}`;
    $("shapePanel").innerHTML = `${panelHead("Shape", "Formations")}${empty("Waiting for squad data.")}`;
    $("buildSquad")?.addEventListener("click", buildSquad);
    if (running) schedulePoll();
    return;
  }
  const players = squadSorted(sq.players || []);
  const logHead = (sq.logFixtures || []).map((f) => `<th class="oh-log__h" title="${esc(`${f.home ? "H" : "A"} ${f.opponent} ${f.score} · ${shortDate(f.date)}`)}">${badge(f.badge, f.opponent, 18)}<small class="oh-res--${esc(f.result)}">${esc(f.result)}</small></th>`).join("");
  const cols = [["shirt", "#"], ["name", "Player"], ["position", "Pos"], ["age", "Age"], ["foot", "Foot"], ["apps", "Apps"], ["starts", "Starts"], ["minutes", "Mins"], ["minutesShare", "% mins"], ["goals", "G"], ["assists", "A"], ["ga90", "G+A /90"], ["threat90", "Threat /90"], ["threatShare", "Threat %"], ["setPlays", "Set plays"]];
  const head = cols.map(([key, label]) => `<th data-sort="${key}" class="${state.squadSort === key ? "is-sorted" : ""}">${label}</th>`).join("");
  const stale = sq.gamesSince > 0 ? `<span class="oh-warn">${sq.gamesSince} game${sq.gamesSince > 1 ? "s" : ""} played since this squad data was built</span>` : "";
  const building = (sq.build || {}).status === "running";
  const tools = `<div class="oh-tools">${toggle(BANDS, state.squadBand, "band")}<span class="oh-muted">Covers ${sq.gamesAvailable} league games${sq.builtAt ? ` · built ${shortDate(sq.builtAt)}` : ""}</span>${stale}${building ? `<span class="oh-building">Rebuilding…</span>` : `<button type="button" class="oh-btn oh-btn--ghost" id="buildSquad">Rebuild squad data</button>`}</div>`;
  const rows = players.map((p) => `<tr class="${p.minutes ? "" : "oh-dim"}">
      <td class="oh-num">${p.shirt ?? ""}</td>
      <td class="oh-name"><b>${esc(p.name)}</b>${(p.tags || []).map((tag) => `<span class="oh-tag oh-tag--${tag.toLowerCase().replace(/[^a-z]+/g, "-")}">${esc(tag)}</span>`).join("")}${(p.leaders || []).map((l) => `<span class="oh-tag oh-tag--leader oh-tag--${l.side === "in_possession" ? "lead-in" : "lead-out"}" data-tip="${esc(`Best in the squad for ${l.label.toLowerCase()} (${l.value}${/\/90/.test(l.label) || /%$/.test(String(l.value)) ? "" : " per 90"}, min. 450 mins)`)}">★ ${esc(l.label)}</span>`).join("")}</td>
      <td>${esc(p.position || "")}</td><td>${p.age ?? ""}</td><td>${esc(p.foot || "")}</td>
      <td>${p.apps}</td><td>${p.starts}</td><td><b>${p.minutes}</b></td>
      <td><div class="oh-share"><span style="width:${Math.min(100, p.minutesShare || 0)}%"></span><em>${p.minutesShare == null ? "—" : `${p.minutesShare}%`}</em></div></td>
      <td>${p.goals || ""}</td><td>${p.assists || ""}</td><td>${p.ga90 ? fmt(p.ga90) : ""}</td><td>${p.threat90 == null ? "" : fmt(p.threat90, 3)}</td>
      <td>${p.threatShare == null ? "" : `${fmt(p.threatShare, 1)}%`}</td>
      <td class="oh-spcell">${setPlayCell(p)}</td>
      ${sq.hasLog ? (p.log || (sq.logFixtures || []).map(() => undefined)).map(logCell).join("") : ""}
    </tr>`).join("");
  panel.innerHTML = `${panelHead("Squad", `${(sq.players || []).filter((p) => p.minutes).length} players used`)}${tools}
    <div class="at-table-wrap oh-squad-wrap"><table class="oh-squad"><thead><tr>${head}${sq.hasLog ? logHead : ""}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="at-note">${sq.hasLog ? "Last games, oldest to newest: green started (bright = full game), amber came on, B unused sub, · not in the squad. Gold dot = goal, blue dot = assist. " : "Game-by-game minutes appear after the next squad rebuild. "}Threat /90 is Impect attacking threat per 90 minutes; Threat % is his share of the team's. Set plays: purple = deliveries he takes, orange = first contacts he wins attacking, Def = first contacts won–lost defending (red = loses ones that lead to shots or goals). Hover any tag for detail.</p>`;
  panel.querySelectorAll("[data-sort]").forEach((th) => th.addEventListener("click", () => { state.squadSort = th.dataset.sort; renderSquad(state.report); }));
  panel.querySelectorAll("[data-band]").forEach((btn) => btn.addEventListener("click", () => { state.squadBand = btn.dataset.band; renderSquad(state.report); }));
  $("buildSquad")?.addEventListener("click", buildSquad);
  if (building) schedulePoll();
  renderXis(sq);
  renderShape(sq);
}
function xiPitch(xi, photos) {
  const players = (xi.players || []).map((p) => {
    const left = 8 + (Number(p.x) || 50) * 0.84;
    const top = 3 + (Number(p.y) || 50) * 0.84;
    const photo = photos[p.name];
    const img = photo ? `<img src="${esc(photo)}" alt="" onerror="this.closest('.oh-xp').classList.add('is-nophoto');this.remove()">` : "";
    const shirt = p.shirt != null ? `<em>${esc(p.shirt)}</em>` : "";
    return `<div class="oh-xp${photo ? "" : " is-nophoto"}" style="left:${left.toFixed(1)}%;top:${top.toFixed(1)}%" data-tip="${esc(`${p.shirt ?? ""} ${p.name}`)}"><span class="oh-xp__face"><b>${esc(p.shirt ?? "")}</b>${img}${shirt}</span><span class="oh-xp__name">${esc(p.short || p.name || "")}</span></div>`;
  }).join("");
  return `<div class="oh-xpitch"><i class="oh-xpitch__half"></i><i class="oh-xpitch__circle"></i><i class="oh-xpitch__box oh-xpitch__box--top"></i><i class="oh-xpitch__box oh-xpitch__box--bottom"></i>${players}</div>`;
}
function renderXis(sq) {
  const xis = sq.xis || [];
  const photos = Object.fromEntries((sq.players || []).filter((p) => p.photo).map((p) => [p.name, p.photo]));
  $("xiPanel").innerHTML = `${panelHead("Line-ups", "Last starting XIs")}${xis.length ? `<div class="oh-xis">${xis.map((xi) => `<figure class="oh-xi"><figcaption>${resPill(xi.result)} <b>${esc(xi.venue)} ${esc(xi.opponent)}</b> <span class="oh-xi__score">${esc(xi.score)}</span><span>${esc(xi.formation || "")} · ${shortDate(xi.date)}</span></figcaption>${xiPitch(xi, photos)}</figure>`).join("")}</div>` : empty("No line-ups saved.")}`;
}
function renderShape(sq) {
  const usage = sq.formationUsage || [];
  const results = sq.resultsByShape || [];
  const vs = sq.vsShapes || [];
  $("shapePanel").innerHTML = `${panelHead("Shape", "Formations")}<div class="oh-shapes">
    <div><h3 class="oh-sub">Time in each shape</h3>${usage.length ? usage.slice(0, 5).map((row) => `<div class="at-row"><span class="at-row__label">${esc(row.formation)}</span>${bar(row.time_pct)}<span class="at-row__meta">${fmt(row.time_pct, 0)}% of mins · ${row.matches_started} starts</span></div>`).join("") : empty("No formation data.")}</div>
    <div>${results.length ? `<h3 class="oh-sub">Results by their shape</h3><table class="oh-mini-table"><thead><tr><th>Shape</th><th>P</th><th>W-D-L</th><th>PPG</th><th>GF/g</th><th>GA/g</th></tr></thead><tbody>${results.map((row) => `<tr><td>${esc(row.formation)}</td><td>${row.played}</td><td>${row.won}-${row.drawn}-${row.lost}</td><td>${fmt(row.ppg)}</td><td>${fmt(row.goals_for_pg)}</td><td>${fmt(row.goals_against_pg)}</td></tr>`).join("")}</tbody></table>` : ""}</div>
    <div>${vs.length ? `<h3 class="oh-sub">Against opponent shapes</h3><table class="oh-mini-table"><thead><tr><th>Opponent shape</th><th>P</th><th>W-D-L</th><th>PPG</th></tr></thead><tbody>${vs.map((row) => `<tr class="${row.matches_vale_shape ? "oh-hl" : ""}"><td>${esc(row.opponent_formation)}${row.matches_vale_shape ? ' <span class="oh-tag">Our shape</span>' : ""}</td><td>${row.played}</td><td>${row.won}-${row.drawn}-${row.lost}</td><td>${fmt(row.ppg)}</td></tr>`).join("")}</tbody></table>` : ""}</div></div>`;
}

/* ---------- ball progression ---------- */
function renderProgression(r) {
  const sq = r.squad || {};
  const style = sq.style || [];
  $("stylePanel").innerHTML = `${panelHead("Team style", "How they play")}${style.length ? style.map((axis) => {
    const value = Number(axis.value) || 0;
    const read = value >= 60 ? axis.coach_high : value <= 40 ? axis.coach_low : "Around league average.";
    return `<div class="oh-style"><div class="oh-style__top"><b>${esc(axis.label)}</b>${rankChip(axis.rank, axis.league_size, oppTone(axis.rank, axis.league_size))}</div><div class="oh-style__track"><i style="width:${value}%"></i><span style="left:50%"></span></div><p>${esc(read || "")}</p></div>`;
  }).join("") : empty("Style radar appears once squad data is built.")}`;
  const left = metric("leftShare"); const right = metric("rightShare");
  const centre = left?.value != null && right?.value != null ? Math.max(0, 100 - left.value - right.value) : null;
  const keyIn = (sq.keyStats?.in_possession || []).filter((row) => row.value != null);
  $("routePanel").innerHTML = `${panelHead("Route to goal", "Direct or through the thirds?")}
    <div class="oh-tiles">${tile(metric("longShare"), "Passing threat from long balls")}${tile(metric("deepShare"), "Threat started from their back line")}${tile(metric("famFor:dribble"), "Threat from dribbles / game")}${tile(metric("famFor:cross"), "Threat from crosses / game")}</div>
    <h3 class="oh-sub">Which flank their threat starts on</h3>
    <div class="oh-flank"><div style="flex:${left?.value || 0}" class="oh-flank__l"><b>${metricValue(left)}</b><span>Left</span></div><div style="flex:${centre || 0}" class="oh-flank__c"><b>${centre == null ? "—" : `${Math.round(centre)}%`}</b><span>Centre</span></div><div style="flex:${right?.value || 0}" class="oh-flank__r"><b>${metricValue(right)}</b><span>Right</span></div></div>
    ${keyIn.length ? `<h3 class="oh-sub">Season numbers per game</h3><div class="oh-keystats">${keyIn.map((row) => `<div><span>${esc(row.label)}</span><b>${fmt(row.value, row.value > 20 ? 0 : 2)}</b><em>${esc(String(row.rank || "").toLowerCase())}</em></div>`).join("")}</div>` : ""}`;
  const zones = r.threat?.zones || { start: [], end: [] };
  const side = state.zoneSide === "start" ? zones.start : zones.end;
  $("startZonePanel").innerHTML = `${panelHead("Where on the pitch", state.zoneSide === "start" ? "Where their threat starts" : "Where their threat arrives", toggle([["start", "Starts"], ["end", "Arrives"]], state.zoneSide, "zone"))}${side.length ? `${zoneHeatmap(side, { label: "Threat zones" })}${heatKey("245,197,24", "They attack", state.zoneSide === "start" ? "Share of their attacking threat by where the action started. 1–3 are their main zones." : "Share of their attacking threat by where the action ended. 1–3 are their main zones.")}` : empty("No zone threat saved for this window.")}`;
  $("startZonePanel").querySelectorAll("[data-zone]").forEach((btn) => btn.addEventListener("click", () => { state.zoneSide = btn.dataset.zone; renderProgression(state.report); }));
  const phases = [...(r.threat?.phases || [])].sort((a, b) => b.share - a.share);
  const main = phases.filter((row) => row.share >= 2);
  const rare = phases.filter((row) => row.share < 2);
  const scale = Math.max(...main.flatMap((row) => [row.perGame || 0, row.leaguePerGame || 0]), 0.01);
  const phaseRow = (row) => {
    const vs = row.leaguePerGame ? Math.round(((row.perGame - row.leaguePerGame) / row.leaguePerGame) * 100) : null;
    const tone = oppTone(row.rank, row.of);
    return `<div class="oh-ph oh-ph--${tone}">
      <div class="oh-ph__head"><b>${esc(row.label)}</b><strong>${Math.round(row.share)}<small>%</small></strong></div>
      <div class="oh-ph__track"><i style="width:${((row.perGame / scale) * 100).toFixed(1)}%"></i>${row.leaguePerGame != null ? `<span style="left:${((row.leaguePerGame / scale) * 100).toFixed(1)}%" data-tip="League average ${fmt(row.leaguePerGame, 3)} a game"></span>` : ""}</div>
      <div class="oh-ph__foot"><span>${fmt(row.perGame, 3)} a game${vs != null ? ` · <em class="${vs >= 0 ? "is-up" : "is-down"}">${vs >= 0 ? "+" : ""}${vs}% vs league</em>` : ""}</span>${row.rank ? rankChip(row.rank, row.of, tone) : ""}</div>
    </div>`;
  };
  $("phasePanel").innerHTML = `${panelHead("Phases", "Which phase creates their threat")}${main.length ? `<div class="oh-phs">${main.map(phaseRow).join("")}</div>${rare.length ? `<p class="oh-muted oh-ph__rare">Rarely: ${rare.map((row) => `${esc(row.label)} ${row.share}%`).join(" · ")}</p>` : ""}<p class="at-note">Big number is the share of their threat. Bar is threat a game; the white line is the League Two average.</p>` : empty("No phase data saved for this window.")}`;
  const actions = r.threat?.actions || [];
  const maxA = Math.max(...actions.map((row) => row.share), 1);
  renderChains(r);
  renderProgressors(r);
  $("actionPanel").innerHTML = `${panelHead("Actions", "How the ball creates their threat")}${actions.length ? `<div class="at-table-wrap"><table><thead><tr><th>Action</th><th>Share of threat</th><th>Per game</th><th>Count</th><th>League rank</th><th>League avg /g</th></tr></thead><tbody>${actions.map((row) => `<tr><td><span class="at-dot" style="background:${row.color}"></span>${esc(row.label)}</td><td><span class="at-cellbar" style="width:${Math.max(3, (row.share / maxA) * 120).toFixed(0)}px;background:${row.color}"></span>${row.share}%</td><td>${fmt(row.perGame, 3)}</td><td>${row.count}</td><td>${row.rank ? rankChip(row.rank, row.of, oppTone(row.rank, row.of)) : "—"}</td><td>${row.leaguePerGame == null ? "—" : fmt(row.leaguePerGame, 3)}</td></tr>`).join("")}</tbody></table></div>` : empty("No action data saved for this window.")}<p class="at-note">Positive packing threat only. A red rank means they are among the most dangerous in League Two with that action.</p>`;
}

/* ---------- threat chains ---------- */
function initials(name) {
  const parts = String(name || "").replace(/[^\p{L}\s'-]/gu, "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return parts.length === 1 ? parts[0].slice(0, 2).toUpperCase() : (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
function stepPills(steps) {
  return steps.map((step, i) => `${i ? `<span class="at-step__arrow">→</span>` : ""}<span class="at-step" style="background:${step.color || FAMILY_COLORS[step.family] || FAMILY_COLORS.other}">${esc(step.label)}${step.times > 1 ? ` ×${step.times}` : ""}</span>`).join("");
}
function chainSvg(chain) {
  const steps = chain.steps || [];
  const defs = steps.map((step, i) => `<marker id="{id}c${i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${step.color}"/></marker>`).join("");
  let delay = 0;
  const parts = steps.map((step, i) => {
    if (step.x1 == null) return "";
    const a = toSvg(step.x1, step.y1);
    const hasEnd = step.x2 != null;
    const b = hasEnd ? toSvg(step.x2, step.y2) : a;
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const d = delay; delay += 260;
    const width = 3 + Math.min(7, Number(step.pxt) * 30);
    const carry = step.family === "dribble";
    const tip = `${i + 1}. ${step.player || ""} — ${step.label}${Number(step.pxt) > 0 ? ` (+${fmt(step.pxt, 3)})` : ""}`;
    const line = hasEnd && len > 4 ? `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="${step.color}" stroke-width="${width.toFixed(1)}" stroke-linecap="round" marker-end="url(#{id}c${i})" class="${carry ? "at-pop" : "at-draw"}" style="--len:${len.toFixed(0)};animation-delay:${d}ms"${carry ? ` stroke-dasharray="7 6"` : ""}/>` : "";
    const node = `<g class="at-pop" style="animation-delay:${d}ms" data-tip="${esc(tip)}"><circle cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="15" fill="${step.color}" stroke="#0b0f15" stroke-width="2.5"/><text x="${a.x.toFixed(1)}" y="${(a.y + 4.5).toFixed(1)}" text-anchor="middle" font-size="12.5" font-weight="800" fill="#0b0f15" font-family="Manrope">${esc(initials(step.player))}</text></g>`;
    const goal = step.goal ? `<g class="at-pop" style="animation-delay:${d + 400}ms"><circle cx="${b.x.toFixed(1)}" cy="${b.y.toFixed(1)}" r="20" fill="none" stroke="#f5c518" stroke-width="4"/><text x="${(b.x - 26).toFixed(1)}" y="${(b.y - 26).toFixed(1)}" text-anchor="end" fill="#f5c518" font-size="22" font-weight="800" font-family="Barlow Condensed">GOAL</text></g>` : "";
    return line + node + goal;
  }).join("");
  return pitch(parts, "Move replay, attacking to the right", defs);
}
function chainKey(chain) {
  const used = new Set((chain.steps || []).map((step) => step.family));
  const items = ["pass", "cross", "dribble", "shot", "setPiece", "regain", "other"].filter((f) => used.has(f))
    .map((f) => `<span><i style="background:${FAMILY_COLORS[f]}"></i>${esc(f === "dribble" ? "Carry / dribble (dashed)" : FAMILY_LABELS[f])}</span>`).join("");
  return `<div class="oh-mapkey">${items}<span>Thicker = more threat</span>${chain.goal ? "<span>Gold ring = goal</span>" : ""}</div>`;
}
function renderChains(r) {
  const prog = r.progression || {};
  const chains = prog.chains;
  const top = chains?.top || [];
  if (!top.length) {
    const msg = prog.ready === false ? "Move patterns need the saved match events for this club. They fill in on the next hub refresh." : "No dangerous moves saved for this window.";
    $("chainPanel").innerHTML = `${panelHead("Replay their best moves", "Move explorer")}${empty(msg)}`;
    $("patternPanel").innerHTML = `${panelHead("Patterns", "The sequences that hurt teams")}${empty(msg)}`;
    return;
  }
  let index = top.findIndex((c) => c.id === state.chainId);
  if (index < 0) index = 0;
  const chain = top[index];
  state.chainId = chain.id;
  const outcome = { goal: "Goal", shot: "Shot", threat: "Dangerous", none: "No shot" }[chain.outcome] || "Dangerous";
  const vs = chain.opponent ? `${chain.home ? "vs" : "at"} ${esc(chain.opponent)}` : "";
  const stepRows = (chain.steps || []).map((step, i) => `<div class="at-chain-step" style="animation-delay:${i * 260}ms"><span class="at-chain-step__n" style="background:${step.color}">${esc(initials(step.player))}</span><span><b>${esc(step.player || "—")}</b> · ${esc(step.label)}${step.goal ? " ⚽" : ""}</span><span class="at-chain-step__v">${Number(step.pxt) > 0 ? `+${fmt(step.pxt, 3)}` : "·"}${step.xg ? ` · xG ${fmt(step.xg)}` : ""}</span></div>`).join("");
  const chips = top.map((item, i) => `<button type="button" class="at-chain-chip${i === index ? " is-active" : ""}" data-chain="${esc(item.id)}"><b>${fmt(item.threat, 2)}</b>${esc(item.opponent || "")} ${item.minute}'${item.goal ? " ⚽" : ""}</button>`).join("");
  $("chainPanel").innerHTML = `
    <div class="at-explorer__head">
      <div>${panelHead("Replay their best moves", "Move explorer")}<p class="at-explorer__meta"><span class="at-badge at-badge--${esc(chain.outcome)}">${outcome}</span> &nbsp;${vs} · ${chain.minute}' · ${esc(chain.origin)} · ${chain.passes} passes · <b style="color:#f5c518">${fmt(chain.threat, 3)}</b> threat${chain.xg ? ` · xG ${fmt(chain.xg)}` : ""}</p></div>
      <div class="at-explorer__controls"><button type="button" class="at-icon-btn" data-nav="-1">‹ Prev</button><button type="button" class="at-icon-btn at-icon-btn--gold" data-nav="0">▶ Replay</button><button type="button" class="at-icon-btn" data-nav="1">Next ›</button></div>
    </div>
    ${chainSvg(chain)}${chainKey(chain)}
    <div class="at-chain-steps">${stepRows}</div>
    <div class="at-chain-list">${chips}</div>`;
  $("chainPanel").querySelectorAll("[data-nav]").forEach((btn) => btn.addEventListener("click", () => {
    state.chainId = top[(index + Number(btn.dataset.nav) + top.length) % top.length].id;
    renderChains(r);
  }));
  $("chainPanel").querySelectorAll("[data-chain]").forEach((btn) => btn.addEventListener("click", () => { state.chainId = btn.dataset.chain; renderChains(r); }));

  const rows = chains.patterns || [];
  const max = Math.max(...rows.map((row) => row.threat), 0.01);
  const s = chains.summary || {};
  $("patternPanel").innerHTML = `${panelHead("Patterns", "The sequences that hurt teams")}
    <div class="oh-chainsum"><div><b>${fmt(s.threateningPerGame, 1)}</b><span>dangerous moves a game</span></div><div><b>${fmt(s.avgPassesThreatening, 1)}</b><span>passes in a dangerous move</span></div><div><b>${s.goals ?? 0}</b><span>open-play goals from moves</span></div></div>
    ${rows.length ? `<div class="at-patterns">${rows.slice(0, 8).map((row, i) => `
      <button type="button" class="at-pattern${top.some((c) => c.id === row.exampleId) ? "" : " is-noreplay"}" data-example="${esc(row.exampleId)}">
        <div class="at-pattern__top"><span class="at-pattern__rank">${i + 1}</span><div class="at-steps">${stepPills(row.steps)}</div></div>
        <div class="at-pattern__stats"><span><b>${row.count}</b> times</span><span><b>${row.share}%</b> of threat</span><span><b>${row.shots}</b> shots</span><span><b>${row.goals}</b> goals</span></div>
        <div class="at-bar"><span style="width:${(row.threat / max) * 100}%;background:linear-gradient(90deg,#f59e0b,#f5c518)"></span></div>
      </button>`).join("")}</div>` : empty("No repeated patterns in this window yet.")}
    <p class="at-note">The last three threat-adding actions of each dangerous move. Click one to replay their best example on the pitch.</p>`;
  $("patternPanel").querySelectorAll("[data-example]").forEach((btn) => btn.addEventListener("click", () => {
    if (!top.some((c) => c.id === btn.dataset.example)) { setStatus("That pattern's best example isn't one of the saved replays — showing the top move instead."); return; }
    state.chainId = btn.dataset.example;
    renderChains(r);
    $("chainPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }));
}

/* ---------- who progresses it ---------- */
const PROG_COLORS = { short: "#34d399", long: "#60a5fa", carry: "#f97316", cross: "#38bdf8" };
const LANE_LABEL = { left: "left", centre: "through the middle", right: "right" };
function methodBar(methods) {
  return `<div class="oh-method">${methods.filter((m) => m.share > 0).map((m) => `<i style="flex:${m.share};background:${PROG_COLORS[m.id]}" data-tip="${esc(`${m.label} ${m.share}%`)}"></i>`).join("")}</div>`;
}
function renderProgressors(r) {
  const prog = r.progression || {};
  const team = prog.team;
  const players = [...(prog.players || [])].sort((a, b) => (b[state.progSort] || 0) - (a[state.progSort] || 0));
  if (!team || !players.length) {
    $("progPlayersPanel").innerHTML = `${panelHead("Who moves it forward", "Their most progressive players")}${empty("Progressive actions appear once the saved match events are in for this club.")}`;
    return;
  }
  const max = Math.max(...players.map((p) => p[state.progSort] || 0), 0.01);
  const cols = [["prog90", "Prog. actions /90"], ["passes90", "Prog. passes /90"], ["carries90", "Carries /90"], ["finalThird90", "Into final third /90"], ["box90", "Into box /90"], ["threat90", "Threat /90"]];
  const how = (p) => {
    const main = p.methods[0];
    const bits = [main ? `${main.share}% ${main.label.toLowerCase()}` : "", p.lane && p.laneShare >= 45 ? `mostly ${LANE_LABEL[p.lane]}` : "", p.targets.length ? `to ${p.targets.map((t) => esc(t.name.split(" ").slice(-1)[0])).join(", ")}` : ""].filter(Boolean);
    return `${methodBar(p.methods)}<small>${bits.join(" · ")}</small>`;
  };
  const teamMix = team.methods.map((m) => `<div><i style="background:${PROG_COLORS[m.id]}"></i><b>${m.share}%</b><span>${esc(m.label)}</span><em>${fmt(m.perGame, 1)} a game</em></div>`).join("");
  $("progPlayersPanel").innerHTML = `${panelHead("Who moves it forward", "Their most progressive players")}
    <div class="oh-progteam">
      <div class="oh-progteam__nums"><div><b>${fmt(team.progPerGame, 1)}</b><span>progressive actions a game</span></div><div><b>${fmt(team.finalThirdPerGame, 1)}</b><span>entries into the final third</span></div><div><b>${fmt(team.boxPerGame, 1)}</b><span>entries into the box</span></div></div>
      <div class="oh-progteam__mix"><p class="oh-sub">How they move it forward</p>${methodBar(team.methods)}<div class="oh-progteam__legend">${teamMix}</div><p class="oh-muted">Starts from the ${team.lanes.left}% left · ${team.lanes.centre}% centre · ${team.lanes.right}% right</p></div>
    </div>
    <div class="at-table-wrap"><table class="oh-squad oh-progtable"><thead><tr><th>Player</th><th>Mins</th>${cols.map(([key, label]) => `<th data-progsort="${key}" class="${state.progSort === key ? "is-sorted" : ""}">${label}</th>`).join("")}<th>How they do it</th></tr></thead>
    <tbody>${players.map((p) => `<tr><td class="oh-name"><b>${esc(p.name)}</b><small>${esc(p.position || "")}</small></td><td>${p.minutes}</td>${cols.map(([key]) => `<td>${key === state.progSort ? `<span class="at-cellbar" style="width:${Math.max(3, ((p[key] || 0) / max) * 70).toFixed(0)}px;background:var(--gold)"></span>` : ""}${fmt(p[key], key === "threat90" ? 3 : 1)}</td>`).join("")}<td class="oh-how">${how(p)}</td></tr>`).join("")}</tbody></table></div>
    <p class="at-note">Season, players with ${270}+ minutes. Progressive = a completed pass that moves the ball 10m+ towards goal (not into their own third), a carry of 8m+, or a cross. Bar colours: <span style="color:${PROG_COLORS.short}">short passes</span>, <span style="color:${PROG_COLORS.long}">long balls</span>, <span style="color:${PROG_COLORS.carry}">carries</span>, <span style="color:${PROG_COLORS.cross}">crosses</span>.</p>`;
  $("progPlayersPanel").querySelectorAll("[data-progsort]").forEach((btn) => btn.addEventListener("click", () => { state.progSort = btn.dataset.progsort; renderProgressors(r); }));
}

/* ---------- attack ---------- */
function dotLayer(passes, end) {
  const max = Math.max(...passes.map((row) => Number(row.pxt) || 0), 0.05);
  return [...passes].sort((a, b) => (Number(a.pxt) || 0) - (Number(b.pxt) || 0)).map((row) => {
    const p = end ? toSvg(row.x2, row.y2) : toSvg(row.x1, row.y1);
    const color = FAMILY_COLORS[row.family] || FAMILY_COLORS.other;
    const r = 6 + Math.sqrt((Number(row.pxt) || 0) / max) * 10;
    const tip = `${row.label} · ${fmt(row.pxt, 3)} threat · ${row.player || ""}${row.opponent ? ` vs ${row.opponent}` : ""}`;
    return `<circle class="oh-dot" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}" fill-opacity="0.78" stroke="rgba(10,13,18,0.85)" stroke-width="1.5" data-tip="${esc(tip)}"/>`;
  }).join("");
}
const MAP_VIEWS = [["start", "Dots: started"], ["end", "Dots: ended"], ["arrows", "Arrows"]];
function mapPanel(id, passes, familyKey, title, kicker, attackLabel) {
  const families = ["all", ...new Set(passes.map((row) => row.family))];
  const shown = passes.filter((row) => state[familyKey] === "all" || row.family === state[familyKey]);
  const view = state.mapView;
  const layer = view === "arrows" ? pitch(arrowLayer(shown), title, arrowDefs(), attackLabel) : pitch(dotLayer(shown, view === "end"), title, "", attackLabel);
  const used = [...new Set(shown.map((row) => row.family))];
  const key = `<div class="oh-mapkey">${used.map((f) => `<span><i style="background:${FAMILY_COLORS[f] || FAMILY_COLORS.other}"></i>${esc(FAMILY_LABELS[f] || f)}</span>`).join("")}</div>`;
  const note = view === "arrows"
    ? "Thicker arrows add more threat."
    : `Each dot is where the action ${view === "end" ? "ended" : "started"}; bigger dots added more threat.`;
  $(id).innerHTML = `${panelHead(kicker, title, toggle(families.map((f) => [f, FAMILY_LABELS[f] || f]), state[familyKey], "family"))}
    ${passes.length ? `<div class="oh-mapview"><span>View</span>${toggle(MAP_VIEWS, view, "mapview")}</div>${layer}${key}` : empty("No threat map saved for this window.")}
    <p class="at-note">${shown.length} most threatening actions. ${note} Hover for player and game.</p>`;
  $(id).querySelectorAll("[data-family]").forEach((btn) => btn.addEventListener("click", () => { state[familyKey] = btn.dataset.family; mapPanel(id, passes, familyKey, title, kicker, attackLabel); }));
  $(id).querySelectorAll("[data-mapview]").forEach((btn) => btn.addEventListener("click", () => {
    state.mapView = btn.dataset.mapview;
    try { localStorage.setItem("ohMapView", state.mapView); } catch (_) { /* private mode */ }
    if (state.report) { renderAttack(state.report); renderDefence(state.report); }
  }));
}
function chanceBars(rows) {
  const total = rows.reduce((sum, row) => sum + row.count, 0) || 1;
  return `<div class="oh-chance">${rows.map((row) => `<i style="flex:${row.count};background:${row.color}" data-tip="${esc(`${row.label}: ${row.count} shots · ${fmt(row.xg)} xG · ${row.goals} goals`)}"></i>`).join("")}</div>
    <table class="oh-mini-table"><thead><tr><th>Chance</th><th>Shots</th><th>Share</th><th>xG</th><th>Goals</th></tr></thead><tbody>${rows.map((row) => `<tr><td><span class="at-dot" style="background:${row.color}"></span>${esc(row.label)}</td><td>${row.count}</td><td>${Math.round((100 * row.count) / total)}%</td><td>${fmt(row.xg)}</td><td>${row.goals}</td></tr>`).join("")}</tbody></table>`;
}
function xgCoverage(xg) {
  if (!xg || xg.covered == null || xg.covered >= xg.of) return "";
  return `<p class="oh-warn">xG saved for ${xg.covered} of ${xg.of} games so far — shot numbers and ranks use those games only and fill in automatically.</p>`;
}
function renderAttack(r) {
  mapPanel("mapPanel", r.threat?.passes || [], "mapFamily", "Their most threatening actions", "Threat map", "THEY ATTACK");
  const squadById = Object.fromEntries((r.squad?.players || []).map((p) => [String(p.id), p]));
  const players = (r.threat?.players || []).slice(0, 8);
  const top = Math.max(...players.map((p) => p.total), 0.01);
  $("dangerPanel").innerHTML = `${panelHead("Players", "Danger men")}${players.length ? players.map((p, i) => {
    const sp = squadById[String(p.id)];
    return `<div class="oh-danger"><span class="oh-danger__n">${i + 1}</span><div><div class="oh-danger__top"><b>${esc(p.name)}</b><span>${esc(sp?.position || "")}</span></div>${bar((p.total / top) * 100, "linear-gradient(90deg,#ef4444,#f97316)")}<span class="oh-muted">${fmt(p.perGame, 3)} threat a game · ${p.share}% of team threat${sp?.threat90 != null ? ` · ${fmt(sp.threat90, 3)} per 90` : ""}${sp ? ` · ${sp.goals}G ${sp.assists}A` : ""}</span></div></div>`;
  }).join("") : empty("No player threat saved.")}`;
  const xg = r.xg || {};
  $("chanceForPanel").innerHTML = `${panelHead("Shot quality", "Chances they create")}<div class="oh-tiles">${tile(metric("xgFor"), "npxG / game")}${tile(metric("shotsFor"), "Shots / game")}${tile(metric("bigFor"), "Big chances / game")}${tile(metric("xgPerShot"), "npxG per shot")}${tile(metric("finishing"), "Goals minus xG")}</div>${(xg.for || []).some((row) => row.count) ? chanceBars(xg.for) : empty("No shot data saved for this window.")}${xgCoverage(xg)}`;
  const trend = xg.trend || [];
  const max = Math.max(...trend.flatMap((row) => [row.xgFor, row.xgAgainst]), 0.5);
  $("xgTrendPanel").innerHTML = `${panelHead("Game by game", "xG for and against")}${trend.length ? `<div class="oh-trend">${trend.map((row) => `<div class="oh-trend__col" data-tip="${esc(`${row.home ? "H" : "A"} ${row.opponent} ${row.score} · xG ${fmt(row.xgFor)}–${fmt(row.xgAgainst)}`)}"><div class="oh-trend__bars"><i class="oh-trend__for" style="height:${((row.xgFor / max) * 100).toFixed(0)}%"></i><i class="oh-trend__against" style="height:${((row.xgAgainst / max) * 100).toFixed(0)}%"></i></div>${badge(row.badge, row.opponent, 20)}${resPill(row.result)}</div>`).join("")}</div><p class="at-note"><span class="oh-key oh-key--for"></span>xG for <span class="oh-key oh-key--against"></span>xG against, oldest to newest.</p>` : empty("No xG saved for this window.")}`;
}

/* ---------- defence ---------- */
function renderDefence(r) {
  const against = r.threat?.against || {};
  mapPanel("concededMapPanel", against.passes || [], "concededFamily", "Most threatening actions against them", "Threat conceded", "OPPONENT ATTACKS");
  const phases = (against.phases || []).filter((row) => row.share > 0);
  const actions = (against.actions || []).slice(0, 8);
  const maxP = Math.max(...phases.map((row) => row.share), 1);
  const maxA = Math.max(...actions.map((row) => row.share), 1);
  $("concededPanel").innerHTML = `${panelHead("Threat conceded", `${fmt(r.threat?.concededPerGame, 3)} a game`, oppRank(metric("threatAgainst")))}
    <h3 class="oh-sub">By phase</h3>${phases.map((row) => {
      const rank = metric(`phaseAgainst:${row.id}`);
      return `<div class="at-row"><span class="at-row__label">${esc(row.label)}</span>${bar((row.share / maxP) * 100, row.color)}<span class="at-row__meta">${row.share}% ${rank ? oppRank(rank) : ""}</span></div>`;
    }).join("") || empty("No phase data.")}
    <h3 class="oh-sub">By action</h3>${actions.map((row) => `<div class="at-row"><span class="at-row__label">${esc(row.label)}</span>${bar((row.share / maxA) * 100, row.color)}<span class="at-row__meta">${row.share}% · ${fmt(row.perGame, 3)}/g</span></div>`).join("") || empty("No action data.")}
    <p class="at-note">A green rank means they concede more of it than most of League Two — a chance for us.</p>`;
  const xg = r.xg || {};
  $("chanceAgainstPanel").innerHTML = `${panelHead("Shot quality", "Chances they concede")}<div class="oh-tiles">${tile(metric("xgAgainst"), "npxG conceded / game")}${tile(metric("shotsAgainst"), "Shots conceded / game")}${tile(metric("bigAgainst"), "Big chances conceded / game")}${tile(metric("keeping"), "Conceded minus xG")}</div>${(xg.against || []).some((row) => row.count) ? chanceBars(xg.against) : empty("No shot data saved for this window.")}`;
  $("concededZonePanel").innerHTML = `${panelHead("Where it arrives", "Where teams hurt them")}<div class="oh-tiles">${tile(metric("concededLeft"), "Arriving on their left")}${tile(metric("concededRight"), "Arriving on their right")}${tile(metric("famAgainst:cross"), "Threat conceded from crosses")}${tile(metric("phaseAgainst:ATTACKING_TRANSITION"), "Conceded in transition")}</div>${(against.zonesEnd || []).length ? `${zoneHeatmap(against.zonesEnd, { rgb: "248,113,113", label: "Threat conceded by zone" })}${heatKey("248,113,113", "Opponent attacks", "Where opponents' threatening actions ended against them. Their left flank is at the bottom.")}` : empty("No zone data.")}`;
}

/* ---------- duels ---------- */
function renderDuels(r) {
  $("ivTilesPanel").innerHTML = `${panelHead("Season numbers", "Ball wins and duels")}<div class="oh-tiles oh-tiles--wide">${tile(metric("duelPct"))}${tile(metric("aerialPct"))}${tile(metric("groundPct"))}${tile(metric("aerialDuels"))}${tile(metric("bw"))}${tile(metric("bwd"))}${tile(metric("oi"))}${tile(metric("bwThreat"))}${tile(metric("bwAgainst"))}${tile(metric("bwdAgainst"))}</div><p class="at-note">Ball wins vs defenders and duel win % are the intervention numbers most linked to winning League Two games. Opponents winning it off their defenders tells you whether pressing their back line pays.</p>`;
  const battles = (r.interventions?.battles || []).filter((row) => row.id !== "di");
  $("battlePanel").innerHTML = `${panelHead("What decides their results", "Which battles matter for them")}${battles.length ? `<table class="oh-mini-table oh-battles"><thead><tr><th>Battle</th><th>Won it</th><th>Lost it</th><th>PPG swing</th></tr></thead><tbody>${battles.map((row, i) => `<tr class="${i === 0 && row.ppgGap ? "oh-hl" : ""}"><td><b>${esc(row.label)}</b><small>${esc(row.hint)}</small></td><td>${row.won.games ? `${row.won.w}-${row.won.d}-${row.won.l} <em>${fmt(row.won.ppg)}</em>` : "—"}</td><td>${row.lost.games ? `${row.lost.w}-${row.lost.d}-${row.lost.l} <em>${fmt(row.lost.ppg)}</em>` : "—"}</td><td class="${row.ppgGap > 0 ? "at-up" : row.ppgGap < 0 ? "at-down" : ""}">${row.ppgGap == null ? "—" : signed(row.ppgGap)}</td></tr>`).join("")}</tbody></table><p class="at-note">W-D-L and points a game in matches where they won or lost each battle. The biggest swing is the battle to win.</p>` : empty("Not enough games saved yet.")}`;
  const trend = r.interventions?.trend || [];
  $("ivTrendPanel").innerHTML = `${panelHead("Game by game", "Duels and ball wins")}${trend.length ? `<div class="at-table-wrap"><table class="oh-mini-table"><thead><tr><th>Game</th><th>Res</th><th>Ball wins</th><th>vs defenders</th><th>Duels</th><th>Aerials</th><th>Lost it high</th></tr></thead><tbody>${[...trend].reverse().map((row) => `<tr><td>${badge(row.badge, row.opponent, 18)} ${row.home ? "H" : "A"} ${esc(row.opponent)}</td><td>${resPill(row.result)} ${esc(row.score)}</td><td>${fmt(row.bw, 0)}</td><td>${fmt(row.bwd, 1)}</td><td>${row.duelPct == null ? "—" : `${Math.round(row.duelPct)}%`}</td><td>${row.aerialPct == null ? "—" : `${Math.round(row.aerialPct)}%`}</td><td>${fmt(row.oppBwd, 1)}</td></tr>`).join("")}</tbody></table></div><p class="at-note">"Lost it high" is the opponent's ball wins against their defenders.</p>` : empty("No interventions saved for this window.")}`;
}

/* ---------- set plays ---------- */
const SP_FILTERS = [
  ["type", "Type", [["corner", "Corners"], ["free_kick", "Free kicks"], ["throw_in", "Long throws"], ["all", "All"]]],
  ["side", "Side", [["all", "Both"], ["left", "From left"], ["right", "From right"], ["central", "Central"]]],
  ["style", "Delivery", [["all", "All"], ["box", "Into the box"], ["short", "Short / worked"], ["shot", "Direct shot"]]],
  ["swing", "Swing", [["all", "All"], ["in", "Inswing"], ["out", "Outswing"]]],
  ["outcome", "Outcome", [["all", "All"], ["threat", "Shot or goal"], ["won", "Won 1st contact"], ["lost", "Lost 1st contact"], ["none", "No contact"]]],
  ["half", "Half", [["all", "Both"], ["1", "1st half"], ["2", "2nd half"]]],
];
const SP_STYLE = { box: ["direct", "cross", "long"], short: ["short", "pass"], shot: ["direct_shot"] };
const SP_ZONES = [["near_post", "Near post"], ["goalmouth", "Goalmouth"], ["far_post", "Far post"], ["penalty_spot", "Penalty spot"], ["edge_box", "Edge of the box"], ["outside", "Outside the box"]];
function spFilterPoints(points, { useTaker = false } = {}) {
  const f = state.spf;
  return (points || []).filter((p) => (f.type === "all" || p.type === f.type)
    && (f.side === "all" || p.side === f.side)
    && (f.style === "all" || (SP_STYLE[f.style] || []).includes(p.sub))
    && (f.swing === "all" || p.swing === f.swing)
    && (f.outcome === "all" || (f.outcome === "threat" ? ["shot", "goal"].includes(p.outcome) : p.outcome === f.outcome))
    && (f.half === "all" || (f.half === "1" ? (p.minute || 0) <= 45 : (p.minute || 0) > 45))
    && (!useTaker || f.taker === "all" || p.taker === f.taker));
}
function spSummary(points) {
  const shots = points.filter((p) => p.outcome === "shot" || p.outcome === "goal").length;
  const goals = points.filter((p) => p.outcome === "goal").length;
  const contested = points.filter((p) => p.outcome !== "none");
  const won = contested.filter((p) => p.outcome !== "lost").length;
  const xg = points.reduce((sum, p) => sum + (Number(p.xg) || 0), 0);
  return `<div class="oh-spsum"><div><b>${points.length}</b><span>deliveries</span></div><div><b>${shots}</b><span>shots</span></div><div><b>${goals}</b><span>goals</span></div><div><b>${fmt(xg)}</b><span>xG</span></div><div><b>${contested.length ? `${Math.round((100 * won) / contested.length)}%` : "—"}</b><span>attack won 1st contact</span></div></div>`;
}
function spZoneBoxes(points) {
  const rows = SP_ZONES.map(([id, label]) => {
    const set = points.filter((p) => p.zone === id);
    return { id, label, n: set.length, shots: set.filter((p) => p.outcome === "shot" || p.outcome === "goal").length, goals: set.filter((p) => p.outcome === "goal").length, xg: set.reduce((s, p) => s + (Number(p.xg) || 0), 0) };
  });
  const total = rows.reduce((s, r) => s + r.n, 0);
  if (!total) return "";
  const max = Math.max(...rows.map((r) => r.n), 1);
  return `<h3 class="oh-sub">Where these deliveries go</h3><div class="oh-zones">${rows.map((z) => `<div class="${z.n === max ? "is-top" : ""}" data-tip="${esc(`${z.n} deliveries · ${z.shots} shots · ${z.goals} goals · ${fmt(z.xg)} xG`)}"><b>${Math.round((100 * z.n) / total)}%</b><span>${esc(z.label)}</span><i style="width:${((100 * z.n) / max).toFixed(0)}%"></i></div>`).join("")}</div>`;
}
function renderSpFilters(sp) {
  const f = state.spf;
  const takers = [...new Set((sp.attack?.deliveries || []).filter((p) => f.type === "all" || p.type === f.type).map((p) => p.taker).filter(Boolean))].sort();
  const active = Object.entries(f).filter(([k, v]) => !["type", "lines"].includes(k) && v !== "all").length;
  $("spFilterPanel").innerHTML = `<div class="oh-spf">
    ${SP_FILTERS.map(([key, label, items]) => `<div class="oh-spf__group"><span>${label}</span>${toggle(items, f[key], `spf-${key}`)}</div>`).join("")}
    <div class="oh-spf__group"><span>Their taker</span><select class="at-select oh-spf__select" id="spTaker"><option value="all">All takers</option>${takers.map((t) => `<option${t === f.taker ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></div>
    <div class="oh-spf__group"><span>Lines</span>${toggle([["on", "Show"], ["off", "Hide"]], f.lines ? "on" : "off", "spf-lines")}</div>
    ${active ? `<button type="button" class="oh-btn oh-btn--ghost" id="spReset">Clear ${active} filter${active > 1 ? "s" : ""}</button>` : ""}
  </div>`;
  const rerender = () => renderSetPlays(state.report);
  SP_FILTERS.forEach(([key]) => $("spFilterPanel").querySelectorAll(`[data-spf-${key}]`).forEach((btn) => btn.addEventListener("click", () => {
    f[key] = btn.dataset[`spf${key[0].toUpperCase()}${key.slice(1)}`];
    if (key === "type") f.taker = "all";
    rerender();
  })));
  $("spFilterPanel").querySelectorAll("[data-spf-lines]").forEach((btn) => btn.addEventListener("click", () => { f.lines = btn.dataset.spfLines === "on"; rerender(); }));
  $("spTaker").addEventListener("change", (e) => { f.taker = e.target.value; rerender(); });
  $("spReset")?.addEventListener("click", () => { Object.assign(f, { side: "all", style: "all", swing: "all", outcome: "all", half: "all", taker: "all" }); rerender(); });
}
function renderSetPlays(r) {
  const sp = r.setPlays;
  const ids = ["spHeadPanel", "spFilterPanel", "spAttackMapPanel", "spDefenceMapPanel", "spPeoplePanel", "spDefPeoplePanel", "spGoalsPanel"];
  if (!sp) { ids.forEach((id) => { $(id).innerHTML = id === "spHeadPanel" ? `${panelHead("Set plays", "No set-play data saved")}${empty("Set-play packs appear after the hub data refresh.")}` : ""; }); return; }
  const h = sp.headline || {};
  const marks = sp.benchmarks || [];
  $("spHeadPanel").innerHTML = `${panelHead("Set plays", `${h.goalsFor ?? 0} scored · ${h.goalsAgainst ?? 0} conceded`)}
    <div class="oh-tiles oh-tiles--wide">${marks.filter((m) => !["spShareFor", "counterXgAgainst"].includes(m.id)).map((m) => {
      const row = { value: m.vale, rank: m.rank, of: m.of, avg: m.leagueAvg, pct: m.pct, digits: m.digits };
      return `<div class="oh-tile oh-tile--${oppTone(m.rank, m.of)}"><span class="oh-tile__label">${esc(m.label)}</span><strong>${metricValue(row)}</strong><span class="oh-tile__foot">${rankChip(m.rank, m.of, oppTone(m.rank, m.of))}<em>avg ${m.pct ? `${Math.round(m.leagueAvg)}%` : fmt(m.leagueAvg, m.digits)}</em></span></div>`;
    }).join("")}</div>
    <p class="oh-muted">${sp.games} games · set-play goals ${h.goalsFor ?? 0} for, ${h.goalsAgainst ?? 0} against (incl. ${h.pensScored ?? 0}/${h.pensFor ?? 0} pens scored, ${h.pensConceded ?? 0}/${h.pensAgainst ?? 0} conceded). ${h.shareFor != null ? `${h.shareFor}% of their goals come from set plays (league average ${h.leagueShareFor}%).` : ""}</p>`;
  const legend = `<div class="oh-sp-legend">${Object.values(OUTCOME).map((o) => `<span><i style="background:${o.color}"></i>${esc(o.label)}</span>`).join("")}</div>`;
  renderSpFilters(sp);
  const attackPts = spFilterPoints(sp.attack?.deliveries, { useTaker: true });
  const defencePts = spFilterPoints(sp.defence?.deliveries);
  const takerNote = state.spf.taker !== "all" ? ` · ${state.spf.taker}` : "";
  const mapBody = (pts, label) => pts.length ? `${halfPitch(deliveryLayer(pts, state.spf.lines), label)}${legend}${spSummary(pts)}${spZoneBoxes(pts)}` : empty("No deliveries match these filters.");
  $("spAttackMapPanel").innerHTML = `${panelHead("Their deliveries", `${attackPts.length} into our box${takerNote}`)}${mapBody(attackPts, "Goal they attack")}`;
  $("spDefenceMapPanel").innerHTML = `${panelHead("Deliveries against them", `${defencePts.length} into their box`)}${mapBody(defencePts, "Goal they defend")}${state.spf.taker !== "all" ? `<p class="at-note">The taker filter only applies to their deliveries.</p>` : ""}`;
  const takers = sp.attack?.takers || [];
  const targets = sp.attack?.targets || [];
  $("spPeoplePanel").innerHTML = `${panelHead("Attacking set plays", "Takers and targets")}
    ${takers.length ? `<table class="oh-mini-table"><thead><tr><th>Taker</th><th>Del.</th><th>Foot</th><th>In / out</th><th>Into box</th><th>Aimed at</th><th>xG</th></tr></thead><tbody>${takers.slice(0, 6).map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${t.deliveries}</td><td>${esc(t.foot || "—")}</td><td>${t.inswing} / ${t.outswing}</td><td>${t.intoBoxPct}%</td><td>${esc(t.topZone)}</td><td>${fmt(t.xg)}</td></tr>`).join("")}</tbody></table>` : empty("No takers saved.")}
    ${targets.length ? `<h3 class="oh-sub">Aerial targets — who attacks the ball</h3><table class="oh-mini-table"><thead><tr><th>Player</th><th>1st contacts</th><th>Headers</th><th>Shots</th><th>xG</th><th>Goals</th></tr></thead><tbody>${targets.slice(0, 8).map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${t.fcWon}</td><td>${t.headers}</td><td>${t.shots}</td><td>${fmt(t.xg)}</td><td>${t.goals}</td></tr>`).join("")}</tbody></table>` : ""}`;
  const defenders = sp.defence?.defenders || [];
  const gk = sp.defence?.gk || {};
  $("spDefPeoplePanel").innerHTML = `${panelHead("Defending set plays", "Who wins it — and who loses it")}
    <div class="oh-tiles">${tile(metric("sp:fcDefence"), "First contacts won defending")}${tile(metric("sp:xgAgainst"), "Set-play xG conceded / game")}<div class="oh-tile"><span class="oh-tile__label">Keeper claims</span><strong>${gk.claimPct == null ? "—" : `${gk.claimPct}%`}</strong><span class="oh-tile__foot"><em>${gk.claims ?? 0} of ${gk.boxDeliveries ?? 0} box deliveries</em></span></div></div>
    ${defenders.length ? `<table class="oh-mini-table"><thead><tr><th>Defender</th><th>Won</th><th>Headed clear</th><th>Lost duels</th><th>Lost → shot</th><th>Lost → goal</th><th>Win %</th></tr></thead><tbody>${defenders.slice(0, 8).map((d) => `<tr class="${d.lostOnGoal ? "oh-hl-bad" : ""}"><td><b>${esc(d.name)}</b></td><td>${d.won}</td><td>${d.headedClear}</td><td>${d.lostDuels}</td><td>${d.lostOnShot}</td><td>${d.lostOnGoal}</td><td>${d.winPct == null ? "—" : `${d.winPct}%`}</td></tr>`).join("")}</tbody></table><p class="at-note">Players who lose first contacts that lead to goals are the ones to attack on our set plays.</p>` : ""}`;
  const goalTally = (rows) => {
    const byType = {};
    rows.forEach((g) => { byType[g.typeLabel] = (byType[g.typeLabel] || 0) + 1; });
    const heads = rows.filter((g) => g.head).length;
    return `${Object.entries(byType).map(([t, n]) => { const word = t.toLowerCase(); return `${n} ${n > 1 ? (word.endsWith("y") ? `${word.slice(0, -1)}ies` : `${word}s`) : word}`; }).join(" · ")}${heads ? ` · ${heads} header${heads > 1 ? "s" : ""}` : ""}`;
  };
  const club = r.club?.name || "They";
  const contactText = (value) => {
    const v = String(value || "").toLowerCase();
    if (v.includes("won")) return `${esc(club)} won 1st contact`;
    if (v.includes("lost")) return `${esc(club)} lost 1st contact`;
    return "";
  };
  const goalCard = (g, attacking) => {
    const route = [g.side && g.side !== "central" ? `from the ${g.side}` : "", g.swing ? `${g.swing}swing` : ""].filter(Boolean).join(", ");
    const how = [g.routine, g.zone && g.type !== "penalty" ? `→ ${g.zone}` : ""].filter(Boolean).join(" ");
    const facts = [
      g.taker && g.taker !== g.scorer ? `Taken by <b>${esc(g.taker)}</b>` : "",
      !attacking && g.beaten ? `Beaten: <b>${esc(g.beaten)}</b>` : "",
      contactText(g.firstContact),
    ].filter(Boolean);
    return `<div class="oh-goal oh-goal--${attacking ? "for" : "against"}">
      <div class="oh-goal__min">${g.minute ?? "—"}<small>'</small></div>
      <div class="oh-goal__body">
        <div class="oh-goal__top"><b>${esc(g.scorer || "Unknown")}</b>${g.head ? `<span class="oh-goal__pill">Header</span>` : ""}<span class="oh-goal__xg">${fmt(g.xg)} xG</span></div>
        <div class="oh-goal__how"><span class="oh-goal__type">${esc(g.typeLabel)}</span>${route ? ` ${esc(route)}` : ""}${how ? ` · ${esc(how)}` : ""}</div>
        ${facts.length ? `<div class="oh-goal__facts">${facts.join("<i>·</i>")}</div>` : ""}
        <div class="oh-goal__game">${g.home ? "H" : "A"} vs ${esc(g.opponent || "")} · ${shortDate(g.date)}</div>
      </div>
    </div>`;
  };
  const goalCol = (rows, attacking, title) => `<div><h3 class="oh-sub">${title} <span class="oh-goal__count">${rows.length}</span></h3>${rows.length ? `<p class="oh-muted oh-goal__tally">${goalTally(rows)}</p><div class="oh-goals">${rows.map((g) => goalCard(g, attacking)).join("")}</div>` : empty("None in this window.")}</div>`;
  $("spGoalsPanel").innerHTML = `${panelHead("Every set-play goal", "Scored and conceded")}<div class="at-grid at-grid--2 oh-mt0">${goalCol(sp.attack?.goals || [], true, "Scored")}${goalCol(sp.defence?.goals || [], false, "Conceded")}</div>`;
}
/* ---------- trends & timings ---------- */
function mirrorChart(rows, { forKey, againstKey, forLabel, againstLabel, digits = 0, forColor = "#f87171", againstColor = "#34d399" }) {
  const max = Math.max(...rows.flatMap((row) => [row[forKey] || 0, row[againstKey] || 0]), digits ? 0.01 : 1);
  const peakFor = Math.max(...rows.map((row) => row[forKey] || 0));
  const peakAgainst = Math.max(...rows.map((row) => row[againstKey] || 0));
  const col = (row) => {
    const f = row[forKey] || 0; const a = row[againstKey] || 0;
    return `<div class="oh-mirror__col">
      <div class="oh-mirror__up"><b class="${f && f === peakFor ? "is-peak" : ""}">${f ? fmt(f, digits) : ""}</b><i style="height:${((f / max) * 100).toFixed(1)}%;background:${forColor}" data-tip="${esc(`${forLabel} ${row.label}: ${fmt(f, digits)}`)}"></i></div>
      <span class="oh-mirror__label">${esc(row.label)}</span>
      <div class="oh-mirror__down"><i style="height:${((a / max) * 100).toFixed(1)}%;background:${againstColor}" data-tip="${esc(`${againstLabel} ${row.label}: ${fmt(a, digits)}`)}"></i><b class="${a && a === peakAgainst ? "is-peak" : ""}">${a ? fmt(a, digits) : ""}</b></div>
    </div>`;
  };
  return `<div class="oh-mirror">${rows.slice(0, 3).map(col).join("")}<div class="oh-mirror__ht"><span>HT</span></div>${rows.slice(3).map(col).join("")}</div>
    <div class="oh-mapkey"><span><i style="background:${forColor}"></i>${esc(forLabel)}</span><span><i style="background:${againstColor}"></i>${esc(againstLabel)}</span></div>`;
}
function timelineRow(game) {
  const pos = (g) => {
    const m = Number(g.minute) || 0;
    return g.period === 1 ? Math.min(m, 45.9) / 45 * 48 : 52 + (Math.min(Math.max(m, 45), 90.9) - 45) / 45 * 48;
  };
  const dots = game.goals.map((g) => `<span class="oh-tl__goal ${g.us ? "is-us" : "is-them"}" style="left:${pos(g).toFixed(1)}%" data-tip="${esc(`${g.label}' ${g.player || ""}${g.pen ? " (pen)" : ""}${g.own ? " (own goal)" : ""} — ${g.us ? "scored" : "conceded"}`)}">${esc(g.label)}</span>`).join("");
  return `<div class="oh-tl__row">
    <div class="oh-tl__fx">${resPill(game.result)}<span class="oh-fixture__date">${shortDate(game.date)}</span><span>${game.home ? "H" : "A"}</span>${badge(game.badge, game.opponent, 20)}<b>${esc(game.opponent)}</b><span class="oh-tl__score">${esc(game.score)}<small>HT ${esc(game.ht)}</small></span></div>
    <div class="oh-tl__track"><i class="oh-tl__half"></i>${dots}</div>
  </div>`;
}
function renderTrends(r) {
  const t = r.trends || {};
  const ids = ["trendTilesPanel", "goalTimingPanel", "threatTimingPanel", "gameStatePanel", "timelinePanel"];
  if (!t.ready) {
    ids.forEach((id, i) => { $(id).innerHTML = i ? "" : `${panelHead("Trends", "When it happens")}${empty("Goal times need the saved match events for this club. They fill in on the next hub refresh.")}`; });
    return;
  }
  const club = r.club?.name || "They";
  const m = t.metrics || {};
  const coverage = t.missing ? `<p class="oh-warn">${t.missing} game${t.missing === 1 ? "" : "s"} without saved events — timings cover ${t.games}.</p>` : "";
  $("trendTilesPanel").innerHTML = `${panelHead("Ranked against League Two", "Timing and game-state numbers")}${coverage}
    <div class="oh-tiles oh-tiles--7">${tile(m.lateFor, "Goals 76'+ / game")}${tile(m.lateAgainst, "Conceded 76'+ / game")}${tile(m.earlyAgainst, "Conceded in first 15' / game")}${tile(m.secondHalfFor, "2nd-half goals / game")}${tile(m.scoredFirst, "Score first")}${tile(m.fromBehind, "Points from losing positions")}${tile(m.dropped, "Points dropped from winning positions")}</div>
    <p class="at-note">Red rank = one of their strengths (top quarter of the league). Green = a weakness we can target.</p>`;

  const bands = t.bands || [];
  const peakFor = bands.reduce((best, row) => (row.for > (best?.for ?? -1) ? row : best), null);
  const peakAgainst = bands.reduce((best, row) => (row.against > (best?.against ?? -1) ? row : best), null);
  const half = (key, from, to) => bands.slice(from, to).reduce((sum, row) => sum + row[key], 0);
  $("goalTimingPanel").innerHTML = `${panelHead("Goal times", "When they score and concede")}
    ${mirrorChart(bands, { forKey: "for", againstKey: "against", forLabel: `${club} scored`, againstLabel: `${club} conceded` })}
    <p class="at-note">${peakFor?.for ? `Most goals scored ${esc(peakFor.label)}' (${peakFor.for}). ` : ""}${peakAgainst?.against ? `Most conceded ${esc(peakAgainst.label)}' (${peakAgainst.against}). ` : ""}First half ${half("for", 0, 3)}–${half("against", 0, 3)}, second half ${half("for", 3, 6)}–${half("against", 3, 6)}.</p>`;

  const tb = t.threatBands;
  $("threatTimingPanel").innerHTML = `${panelHead("Threat by time", "When they are dangerous")}${tb ? `${mirrorChart(bands.map((row, i) => ({ label: row.label, for: tb.for[i], against: tb.against[i] })), { forKey: "for", againstKey: "against", forLabel: "Threat created a game", againstLabel: "Threat conceded a game", digits: 2, forColor: "#f5c518", againstColor: "#38bdf8" })}<p class="at-note">Average attacking threat in each 15-minute spell, per game (${tb.games} games). Shows when they push and when they get pinned back — even in games without goals.</p>` : empty("No threat timings saved.")}`;

  const s = t.states || {};
  const rec = (arr) => `${arr[0]}W ${arr[1]}D ${arr[2]}L`;
  $("gameStatePanel").innerHTML = `${panelHead("Game states", "Ahead, behind, half-time")}
    <div class="oh-states">
      <div><b>${s.scoredFirst}<small>/${t.games}</small></b><span>Scored first</span><em>${rec(s.recordScoringFirst)} · ${s.ptsAfterScoringFirst} pts</em></div>
      <div><b>${s.concededFirst}<small>/${t.games}</small></b><span>Conceded first</span><em>${rec(s.recordConcedingFirst)} · ${s.ptsAfterConcedingFirst} pts</em></div>
      <div><b>${s.ptsFromBehind}</b><span>Points won after going behind</span><em>in ${s.gamesBehind} game${s.gamesBehind === 1 ? "" : "s"} they trailed</em></div>
      <div><b>${s.ptsDropped}</b><span>Points dropped after leading</span><em>in ${s.gamesAhead} game${s.gamesAhead === 1 ? "" : "s"} they led</em></div>
      <div><b>${s.avgFirstGoal ? `${s.avgFirstGoal}'` : "—"}</b><span>Average time of their first goal</span><em>${s.goalless ? `${s.goalless} goalless` : "&nbsp;"}</em></div>
    </div>
    <h3 class="oh-sub">Half-time → full-time</h3>
    <table class="oh-mini-table"><thead><tr><th>At half-time</th><th>P</th><th>W</th><th>D</th><th>L</th></tr></thead><tbody>${(t.htft || []).map((row) => `<tr><td>${esc(row.label)}</td><td>${row.games}</td><td>${row.w}</td><td>${row.d}</td><td>${row.l}</td></tr>`).join("")}</tbody></table>`;

  $("timelinePanel").innerHTML = `${panelHead("Every game", "Goal timeline")}
    <div class="oh-tl__scale"><span>0'</span><span>HT</span><span>90'</span></div>
    <div class="oh-tl">${(t.timeline || []).map(timelineRow).join("")}</div>
    <div class="oh-mapkey"><span><i style="background:#f87171"></i>${esc(club)} scored</span><span><i style="background:#34d399"></i>${esc(club)} conceded</span><span>Hover a goal for the scorer</span></div>`;
}

/* ---------- results ---------- */
function venueBlock(label, rec) {
  return `<div class="oh-venue"><h3>${esc(label)}</h3><div class="oh-venue__big">${rec.w}<small>W</small> ${rec.d}<small>D</small> ${rec.l}<small>L</small></div><p>${fmt(rec.ppg)} pts a game · ${rec.gf} scored · ${rec.ga} conceded · ${rec.cleanSheets} clean sheets · failed to score ${rec.failedToScore}</p><div class="oh-form">${(rec.form || []).map(resPill).join("")}</div></div>`;
}
function renderResults(r) {
  $("formPanel").innerHTML = `${panelHead("Results", r.window === "last6" ? "Last 6 league games" : "Every league game")}<div class="oh-fixtures">${(r.fixtures || []).map((f) => `<div class="oh-fixture">${resPill(f.result)}<span class="oh-fixture__date">${shortDate(f.date)}</span><span>${f.home ? "H" : "A"}</span>${badge(f.badge, f.opponent, 22)}<b>${esc(f.opponent)}</b><span class="oh-fixture__score">${esc(f.score)}</span></div>`).join("")}</div>`;
  const table = r.leagueTable || [];
  $("tablePanel").innerHTML = `${panelHead("League Two", "Table")}<div class="at-table-wrap"><table class="oh-mini-table oh-table"><thead><tr><th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th><th>Form</th></tr></thead><tbody>${table.map((row) => `<tr class="${row.squadId === r.club.id ? "oh-hl" : row.squadId === r.vale.id ? "oh-hl-vale" : ""}"><td>${row.position}</td><td>${badge(row.badge, row.club, 18)} ${esc(row.club)}</td><td>${row.played}</td><td>${row.w}</td><td>${row.d}</td><td>${row.l}</td><td>${row.gd > 0 ? "+" : ""}${row.gd}</td><td><b>${row.pts}</b></td><td class="oh-form oh-form--sm">${(row.form || []).slice(-5).map(resPill).join("")}</td></tr>`).join("")}</tbody></table></div><p class="at-note">From saved League Two results.</p>`;
  const fx = r.fixture;
  const where = fx && fx.valeHome != null ? (fx.valeHome ? "away" : "home") : null;
  $("venuePanel").innerHTML = `${panelHead("Home and away", where ? `They are ${where} against us` : "Venue split")}<div class="oh-venues"><div class="${where === "home" ? "oh-venue--on" : ""}">${venueBlock("At home", r.home)}</div><div class="${where === "away" ? "oh-venue--on" : ""}">${venueBlock("Away", r.away)}</div></div>`;
  const h2h = r.h2h || [];
  $("h2hPanel").innerHTML = `${panelHead("Head to head", "Port Vale meetings")}${h2h.length ? `<div class="oh-fixtures">${h2h.map((f) => `<div class="oh-fixture">${resPill(f.result)}<span class="oh-fixture__date">${esc(f.season)} · ${shortDate(f.date)}</span><span>${f.home ? "H" : "A"}</span><b>Port Vale ${esc(f.score)}</b></div>`).join("")}</div><p class="at-note">Result from Port Vale's side.</p>` : empty("No league meetings in the saved seasons.")}`;
}

/* ---------- squad build ---------- */
async function buildSquad() {
  const btn = $("buildSquad");
  if (btn) { btn.disabled = true; btn.textContent = "Starting…"; }
  try {
    const params = new URLSearchParams({ squadId: state.squadId, season: state.season || "" });
    const res = await getJson(`/api/opposition-hub/squad-build?${params}`, { method: "POST" });
    setStatus(res.detail || "Squad build started.");
    schedulePoll(true);
  } catch (err) {
    setStatus(`Could not start the squad build: ${err.message}`);
    if (btn) { btn.disabled = false; btn.textContent = "Try again"; }
  }
}
function schedulePoll(immediate = false) {
  clearTimeout(state.poll);
  state.poll = setTimeout(() => loadReport({ quiet: true }), immediate ? 4000 : 20000);
}

/* ---------- tooltip + nav ---------- */
function bindTip() {
  const tip = $("tip");
  document.addEventListener("mousemove", (event) => {
    const host = event.target.closest?.("[data-tip]");
    if (!host) { tip.hidden = true; return; }
    tip.textContent = host.dataset.tip;
    tip.hidden = false;
    const x = Math.min(window.innerWidth - tip.offsetWidth - 12, event.clientX + 14);
    tip.style.left = `${x}px`;
    tip.style.top = `${event.clientY + 16}px`;
  });
}
function bindNav() {
  const links = [...document.querySelectorAll("#sectionNav a")];
  const sections = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("is-active", a.getAttribute("href") === `#${entry.target.id}`));
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  sections.forEach((s) => observer.observe(s));
}

/* ---------- load ---------- */
function syncUrl() {
  const params = new URLSearchParams();
  if (state.squadId) params.set("team", state.squadId);
  if (state.season && state.season !== state.meta?.defaultSeason) params.set("season", state.season);
  if (state.window !== "season") params.set("window", state.window);
  if (state.matchId) params.set("match", state.matchId);
  history.replaceState(null, "", `${location.pathname}${params.toString() ? `?${params}` : ""}${location.hash}`);
}
function renderAll(r) {
  const parts = [renderHero, renderPlan, renderMatchup, renderSquad, renderProgression, renderAttack, renderDefence, renderDuels, renderSetPlays, renderTrends, renderResults];
  parts.forEach((fn) => {
    try { fn(r); } catch (err) { console.error(fn.name, err); }
  });
}
async function loadReport({ quiet = false } = {}) {
  if (!state.squadId) return;
  syncUrl();
  if (!quiet) { setStatus("Reading the data lake…"); document.body.classList.add("oh-loading"); }
  try {
    const params = new URLSearchParams({ squadId: state.squadId, window: state.window });
    if (state.season) params.set("season", state.season);
    const report = await getJson(`/api/opposition-hub/report?${params}`);
    if (!report.ready) {
      $("hero").innerHTML = `<p class="at-empty">${esc(report.message || "Nothing saved for this opponent yet.")}</p>`;
      setStatus(report.message || "");
      return;
    }
    state.report = report;
    document.title = `${report.club.name} · Opposition Hub`;
    renderAll(report);
    setStatus(`${report.club.name} · ${report.season} · ${report.games} league games · built ${new Date(report.generatedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} from the data lake`);
  } catch (err) {
    setStatus(`Could not load: ${err.message}`);
  } finally {
    document.body.classList.remove("oh-loading");
  }
}
function stripFixture() {
  const rows = state.meta?.fixtures || [];
  const chosen = rows.find((f) => f.matchId === state.matchId && f.squadId === state.squadId);
  if (chosen) return chosen;
  const mine = rows.filter((f) => f.squadId === state.squadId);
  return mine.find((f) => !f.played) || mine[mine.length - 1] || null;
}
function renderStrip({ scroll = true } = {}) {
  const rows = state.meta?.fixtures || [];
  const track = $("fixtureStrip");
  if (!rows.length) { track.closest(".oh-strip").hidden = true; return; }
  const active = stripFixture();
  const nextId = rows.find((f) => !f.played)?.matchId;
  track.innerHTML = rows.map((f) => {
    const d = new Date(f.date);
    const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
    const homeAway = f.score ? (f.home ? f.score : f.score.split("-").reverse().join("-")) : "";
    const right = f.score
      ? `<span class="oh-chip__score oh-chip__score--${esc(f.result)}">${esc(homeAway)}</span>`
      : f.played ? `<span class="oh-chip__time oh-chip__time--none">—</span>` : `<span class="oh-chip__time">${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })}</span>`;
    const label = `${f.home ? `Port Vale vs ${f.name}` : `${f.name} vs Port Vale`} · ${day}${f.score ? ` · ${homeAway}` : f.played ? " · result not saved yet" : ""}`;
    return `<button type="button" role="listitem" class="oh-chip${active && f.matchId === active.matchId ? " is-active" : ""}${f.played ? " is-played" : ""}${f.matchId === nextId ? " is-next" : ""}" data-match="${f.matchId}" data-squad="${f.squadId}" title="${esc(label)}">
      <span class="oh-chip__top"><span>${esc(day)}</span><b>${f.home ? "H" : "A"}</b></span>
      <span class="oh-chip__mid">${badge(f.badge, f.name, 46)}${right}</span>
      <span class="oh-chip__name">${esc(f.name)}</span>
      ${f.matchId === nextId ? `<span class="oh-chip__flag">Next</span>` : ""}
    </button>`;
  }).join("");
  track.querySelectorAll("[data-match]").forEach((btn) => btn.addEventListener("click", () => {
    state.matchId = Number(btn.dataset.match);
    const squad = Number(btn.dataset.squad);
    if (squad !== state.squadId) { state.squadId = squad; state.squadBand = "all"; $("teamSelect").value = String(squad); loadReport(); }
    else { syncUrl(); if (state.report) renderHero(state.report); }
    renderStrip();
  }));
  if (scroll) track.querySelector(".is-active")?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
}
function renderControls() {
  const meta = state.meta;
  const next = meta.next;
  $("teamSelect").innerHTML = meta.teams.map((team) => `<option value="${team.id}"${team.id === state.squadId ? " selected" : ""}>${esc(team.name)}${next && next.squadId === team.id ? " — next opponent" : ""}</option>`).join("");
  $("seasonToggle").innerHTML = (meta.seasons || []).map((s) => `<button type="button" class="at-toggle__btn${s.value === state.season ? " at-toggle__btn--active" : ""}" data-season="${esc(s.value)}">${esc(s.label)}</button>`).join("");
  $("seasonToggle").querySelectorAll("[data-season]").forEach((btn) => btn.addEventListener("click", () => { state.season = btn.dataset.season; renderControls(); loadReport(); }));
  document.querySelectorAll("[data-window]").forEach((btn) => btn.classList.toggle("at-toggle__btn--active", btn.dataset.window === state.window));
}
async function init() {
  bindTip();
  bindNav();
  try {
    state.meta = await getJson("/api/opposition-hub/meta");
  } catch (err) {
    setStatus(`Could not load: ${err.message}`);
    return;
  }
  if (!state.meta.ready) { $("hero").innerHTML = `<p class="at-empty">${esc(state.meta.message)}</p>`; setStatus(state.meta.message); return; }
  const params = new URLSearchParams(location.search);
  state.season = params.get("season") || state.meta.defaultSeason;
  state.window = params.get("window") === "last6" ? "last6" : "season";
  const wanted = Number(params.get("team"));
  const ids = new Set(state.meta.teams.map((t) => t.id));
  state.squadId = ids.has(wanted) ? wanted : (state.meta.next && ids.has(state.meta.next.squadId) ? state.meta.next.squadId : state.meta.teams[0]?.id);
  state.matchId = Number(params.get("match")) || null;
  renderControls();
  renderStrip();
  document.querySelectorAll("[data-strip]").forEach((btn) => btn.addEventListener("click", () => {
    const track = $("fixtureStrip");
    track.scrollBy({ left: Number(btn.dataset.strip) * track.clientWidth * 0.8, behavior: "smooth" });
  }));
  $("teamSelect").addEventListener("change", (event) => { state.squadId = Number(event.target.value); state.squadBand = "all"; state.matchId = null; renderStrip(); loadReport(); });
  document.querySelectorAll("[data-window]").forEach((btn) => btn.addEventListener("click", () => { state.window = btn.dataset.window; renderControls(); loadReport(); }));
  loadReport();
}
document.addEventListener("DOMContentLoaded", init);
