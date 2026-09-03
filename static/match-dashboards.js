const VIEWS = [
  { id: "story", title: "Match story" },
  { id: "progression", title: "Ball progression" },
  { id: "crosses", title: "Crosses" },
  { id: "shots", title: "Shots & xG" },
  { id: "duels", title: "Duels & pressing" },
];

const state = {
  view: "shots",
  side: "for",
  shotsPane: "map",
  chanceView: "summary",
  matches: [],
  selected: new Set(),
  report: null,
};

const CHANCE_TAG_SPECS = [
  { id: "excellent", label: "Excellent", className: "md-xca-tag--excellent" },
  { id: "very_good", label: "Very Good", className: "md-xca-tag--very-good" },
  { id: "ok", label: "OK", className: "md-xca-tag--ok" },
  { id: "poor", label: "Poor", className: "md-xca-tag--poor" },
  { id: "very_poor", label: "Very Poor", className: "md-xca-tag--very-poor" },
];

function chanceFromXg(xg) {
  const n = Number(xg) || 0;
  if (n >= 0.35) return { id: "excellent", label: "Excellent", color: "#166534" };
  if (n >= 0.19) return { id: "very_good", label: "Very Good", color: "#22c55e" };
  if (n >= 0.09) return { id: "ok", label: "OK", color: "#facc15" };
  if (n >= 0.04) return { id: "poor", label: "Poor", color: "#f97316" };
  return { id: "very_poor", label: "Very Poor", color: "#ef4444" };
}

function xgBarWidth(value, maxValue) {
  const max = Math.max(maxValue, 0.01);
  return Math.max(8, Math.round((Number(value) / max) * 100));
}

const els = {
  viewTabs: document.getElementById("viewTabs"),
  gamePicker: document.getElementById("gamePicker"),
  gameCountHint: document.getElementById("gameCountHint"),
  statusBanner: document.getElementById("statusBanner"),
  contextLine: document.getElementById("contextLine"),
  dashboardRoot: document.getElementById("dashboardRoot"),
  pageSubtitle: document.getElementById("pageSubtitle"),
};

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `md-status ${kind}`;
  els.statusBanner.textContent = message;
}

function paramsFromUrl() {
  const url = new URL(window.location.href);
  const view = url.searchParams.get("view");
  if (VIEWS.some((v) => v.id === view)) state.view = view;
  const side = url.searchParams.get("side");
  if (side === "for" || side === "against") state.side = side;
  const ids = url.searchParams.get("matchIds");
  if (ids) ids.split(",").filter(Boolean).forEach((id) => state.selected.add(Number(id)));
}

function writeUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("view", state.view);
  url.searchParams.set("side", state.side);
  url.searchParams.set("matchIds", [...state.selected].join(","));
  history.replaceState({}, "", url);
}

function matchLabel(match) {
  const opp = match?.opponent?.name || "Opponent";
  const venue = match?.isHome ? "H" : "A";
  const date = String(match?.scheduledDate || "").slice(0, 10);
  const short = match?.competitionShort || "";
  return [venue, opp, short, date].filter(Boolean).join(" · ");
}

function renderTabs() {
  els.viewTabs.innerHTML = VIEWS.map(
    (view) =>
      `<button type="button" class="md-view${view.id === state.view ? " is-active" : ""}" data-view="${view.id}">${esc(view.title)}</button>`
  ).join("");
}

function renderSide() {
  document.querySelectorAll("[data-side]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.side === state.side);
  });
}

function renderGames() {
  els.gamePicker.innerHTML = state.matches
    .map((match) => {
      const id = Number(match.matchId);
      const checked = state.selected.has(id) ? "checked" : "";
      return `<label class="md-game"><input type="checkbox" value="${id}" ${checked} /> ${esc(matchLabel(match))}</label>`;
    })
    .join("");
  els.gameCountHint.textContent = state.selected.size ? `(${state.selected.size} selected)` : "";
}

async function fetchJson(url) {
  const res = await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function loadFixtures() {
  const payload = await fetchJson("/api/match-dashboards/fixtures");
  state.matches = payload.matches || [];
  if (!state.selected.size && payload.defaultMatchId) {
    state.selected.add(Number(payload.defaultMatchId));
  }
  renderGames();
}

async function loadReport() {
  const ids = [...state.selected];
  if (!ids.length) {
    setStatus("Select at least one game.", "error");
    return;
  }
  setStatus("Loading dashboard…");
  writeUrl();
  const qs = new URLSearchParams({
    view: state.view,
    side: state.side,
    matchIds: ids.join(","),
  });
  try {
    const report = await fetchJson(`/api/match-dashboards/report?${qs}`);
    state.report = report;
    setStatus("");
    const sideLabel = state.side === "against" ? "Against" : "For";
    const combine = report.combined ? ` · ${report.gameCount} games combined` : "";
    els.contextLine.textContent = `${sideLabel}${combine} · ${(report.matchLabels || []).join("  |  ")}`;
    els.pageSubtitle.textContent = report.data?.title || els.pageSubtitle.textContent;
    renderDashboard(report);
  } catch (err) {
    setStatus(err.message || "Failed to load", "error");
  }
}

function pillRow(items) {
  return `<div class="md-pills">${items
    .map((item) => `<span class="md-pill${item.ok ? " md-pill--ok" : ""}">${esc(item.text)}</span>`)
    .join("")}</div>`;
}

function teamTable(rows, matchHeader) {
  if (!rows?.length) return "<p>No team metrics.</p>";
  return `<table class="md-table"><thead><tr>
    <th>Metric</th><th>7 game avg</th><th>Top 7 avg</th><th>${esc(matchHeader || "This selection")}</th>
  </tr></thead><tbody>${rows
    .map(
      (row) => `<tr>
      <td class="md-metric" style="background:${esc(row.metricColor || "#e2e8f0")}">${esc(row.label)}</td>
      <td><span class="md-num">${esc(row.avgDisplay || "—")}</span>${row.avgRank ? `<span class="md-rank">${esc(row.avgRank)}</span>` : ""}</td>
      <td><span class="md-num">${esc(row.top7AvgDisplay || "—")}</span></td>
      <td class="md-matchcol"><span class="md-num">${esc(row.matchDisplay || "—")}</span></td>
    </tr>`
    )
    .join("")}</tbody></table>`;
}

function fmtOrdinal(rank) {
  const n = Number(rank);
  if (!Number.isFinite(n)) return "";
  const mod100 = n % 100;
  let suffix = "th";
  if (mod100 < 11 || mod100 > 13) {
    const mod10 = n % 10;
    if (mod10 === 1) suffix = "st";
    else if (mod10 === 2) suffix = "nd";
    else if (mod10 === 3) suffix = "rd";
  }
  return `${n}${suffix}`;
}

function progRankClass(rank, leagueSize) {
  const n = Number(rank);
  const size = Number(leagueSize) || 24;
  if (!Number.isFinite(n)) return "";
  if (n <= Math.max(3, Math.round(size * 0.2))) return "prog-table__rank--top";
  if (n >= size - Math.max(2, Math.round(size * 0.15))) return "prog-table__rank--bottom";
  return "";
}

function progSoftColor(hex, alpha = 0.2) {
  const raw = String(hex || "").replace("#", "");
  if (raw.length !== 6) return `rgba(226, 232, 240, ${alpha})`;
  const r = parseInt(raw.slice(0, 2), 16);
  const g = parseInt(raw.slice(2, 4), 16);
  const b = parseInt(raw.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function shotImpectToSvg(impectX, impectY, pitch, drawW, plotH, pitchY, padX = 8) {
  const depthM = Number(pitch.depthM) || 35;
  const widthM = Number(pitch.widthM) || 68;
  const drawH = (depthM / widthM) * drawW;
  const plotHeight = plotH ?? drawH;
  const halfW = widthM / 2;
  const goalX = Number(pitch.goalX) || 52.5;
  const minX = Number(pitch.minX) || 17.5;
  const xRange = goalX - minX || depthM;
  return {
    x: padX + ((halfW - Number(impectY)) / widthM) * drawW,
    y: pitchY + ((goalX - Number(impectX)) / xRange) * plotHeight,
    drawH,
  };
}

function shotLegendShapeSvg(shape, fill = "#d1d5db") {
  if (shape === "diamond") {
    return `<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="2.2" y="2.2" width="7.6" height="7.6" fill="${fill}" stroke="#111" stroke-width="0.8" transform="rotate(45 6 6)"/></svg>`;
  }
  if (shape === "square") {
    return `<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="2" y="2" width="8" height="8" rx="0.8" fill="${fill}" stroke="#111" stroke-width="0.8"/></svg>`;
  }
  return `<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.8" fill="${fill}" stroke="#111" stroke-width="0.8"/></svg>`;
}

function shotXgGoldStroke(xg, maxXg) {
  if (!xg || xg <= 0.04) return { width: 0, opacity: 0 };
  const ref = Math.max(maxXg || xg, 0.12);
  const ratio = Math.min(1, xg / ref);
  if (ratio < 0.2) return { width: 0, opacity: 0 };
  return {
    width: 0.55 + ratio * 2.15,
    opacity: 0.45 + ratio * 0.55,
  };
}

const SHOT_MARKER_TEXT_STYLE = 'fill="#fff" stroke="#111" stroke-width="0.45" paint-order="stroke fill"';

function renderShotMarker(x, y, outcome, phase, initials, xgDisplay, xgValue, maxXg) {
  const colors = {
    scored: "#22c55e",
    saved: "#facc15",
    off_target: "#ef4444",
  };
  const fill = colors[outcome] || "#9ca3af";
  const gold = shotXgGoldStroke(Number(xgValue) || 0, maxXg);
  const baseStroke = "rgba(17,17,17,0.75)";
  const baseStrokeWidth = 0.7;
  const init = initials || "";
  const xg = xgDisplay || "";
  const r = 9.2;
  let shape = "";
  if (phase === "Transition") {
    shape = `<rect x="${-r}" y="${-r}" width="${r * 2}" height="${r * 2}" fill="${fill}" stroke="${baseStroke}" stroke-width="${baseStrokeWidth}" transform="rotate(45)"/>`;
  } else if (phase === "Set Play") {
    shape = `<rect x="${-r}" y="${-r}" width="${r * 2}" height="${r * 2}" rx="1.2" fill="${fill}" stroke="${baseStroke}" stroke-width="${baseStrokeWidth}"/>`;
  } else {
    shape = `<circle r="${r}" fill="${fill}" stroke="${baseStroke}" stroke-width="${baseStrokeWidth}"/>`;
  }
  const goldRing = gold.width > 0
    ? (phase === "Transition"
      ? `<rect x="${-r}" y="${-r}" width="${r * 2}" height="${r * 2}" fill="none" stroke="#fbbf24" stroke-width="${gold.width * 0.85}" opacity="${gold.opacity}" transform="rotate(45)"/>`
      : phase === "Set Play"
        ? `<rect x="${-r}" y="${-r}" width="${r * 2}" height="${r * 2}" rx="1.2" fill="none" stroke="#fbbf24" stroke-width="${gold.width * 0.85}" opacity="${gold.opacity}"/>`
        : `<circle r="${r}" fill="none" stroke="#fbbf24" stroke-width="${gold.width * 0.85}" opacity="${gold.opacity}"/>`)
    : "";
  const xgText = xg
    ? `<text y="1" text-anchor="middle" dominant-baseline="middle"
        ${SHOT_MARKER_TEXT_STYLE} font-family="Barlow Condensed, sans-serif" font-size="8.4" font-weight="800">${esc(xg)}</text>`
    : "";
  const initialsText = init
    ? `<text y="16.5" text-anchor="middle" dominant-baseline="middle"
        fill="#0f172a" font-family="Barlow Condensed, sans-serif" font-size="8.6" font-weight="700"
        letter-spacing="0.03em" opacity="0.9">${esc(init)}</text>`
    : "";
  return `
    <g transform="translate(${x}, ${y - 3})">
      ${shape}
      ${goldRing}
      ${xgText}
      ${initialsText}
    </g>`;
}

function renderShotsPitchSvg(data) {
  const pitch = data.pitch || { goalX: 52.5, minX: 17.5, widthM: 68, depthM: 35 };
  const points = data.shotPoints || [];
  const drawW = 640;
  const padX = 14;
  const padY = 8;
  const { drawH } = shotImpectToSvg(pitch.minX, 0, pitch, drawW, null, padY, padX);
  const plotH = drawH;
  const vbW = padX * 2 + drawW;
  const vbH = padY + drawH + padY;
  const pitchX = padX;
  const pitchY = padY;
  const plotBottom = pitchY + plotH;
  const penDepth = ((pitch.penaltyBoxDepthM ?? 16.5) / pitch.depthM) * plotH;
  const penWidth = (40.32 / pitch.widthM) * drawW;
  const sixDepth = (5.5 / pitch.depthM) * plotH;
  const sixWidth = (18.32 / pitch.widthM) * drawW;
  const penX = pitchX + (drawW - penWidth) / 2;
  const sixX = pitchX + (drawW - sixWidth) / 2;
  const cx = pitchX + drawW / 2;

  const boundaries = [-20.4, -13.6, 13.6, 20.4];
  const gridLines = boundaries.map((impectY) => {
    const svg = shotImpectToSvg(pitch.minX, impectY, pitch, drawW, plotH, pitchY, padX);
    return `<line x1="${svg.x}" y1="${pitchY}" x2="${svg.x}" y2="${plotBottom}"
      stroke="rgba(255,255,255,0.22)" stroke-width="0.55" />`;
  }).join("");
  const horizontalGrid = [1 / 3, 2 / 3].map((ratio) => {
    const y = pitchY + plotH * ratio;
    return `<line x1="${pitchX}" y1="${y}" x2="${pitchX + drawW}" y2="${y}"
      stroke="rgba(255,255,255,0.22)" stroke-width="0.55" />`;
  }).join("");

  const spotDepthM = pitch.penaltySpotM ?? 11;
  const arcRadiusM = pitch.penaltyArcM ?? 9.15;
  const boxDepthM = pitch.penaltyBoxDepthM ?? 16.5;
  const edgeFromSpotM = boxDepthM - spotDepthM;
  const arcHalfM = Math.sqrt(Math.max(0, arcRadiusM * arcRadiusM - edgeFromSpotM * edgeFromSpotM));
  const paLineY = pitchY + penDepth;
  const arcHalfSvg = (arcHalfM / pitch.widthM) * drawW;
  const ry = (arcRadiusM / pitch.depthM) * plotH;
  // Goal is at the top (smaller Y). Sweep 0 bulges the D into the pitch, away from goal.
  const penaltyArc = `<path d="M ${cx - arcHalfSvg} ${paLineY} A ${arcHalfSvg} ${ry} 0 0 0 ${cx + arcHalfSvg} ${paLineY}"
    fill="none" stroke="#fff" stroke-width="1.1" opacity="0.95" />`;

  const maxXg = points.reduce((max, pt) => Math.max(max, Number(pt.xg) || 0), 0);

  const markers = points.filter((pt) => pt.hasLocation !== false && pt.impectX != null && pt.impectY != null).map((pt) => {
    const svg = shotImpectToSvg(pt.impectX, pt.impectY, pitch, drawW, plotH, pitchY, padX);
    return renderShotMarker(
      svg.x,
      svg.y,
      pt.outcome,
      pt.phase,
      pt.playerInitials,
      pt.xgDisplay,
      pt.xg,
      maxXg,
    );
  }).join("");

  return `
    <svg class="shots-pitch" viewBox="0 0 ${vbW} ${vbH}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <pattern id="mdShotsPitchStripes" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(18)">
          <rect width="4" height="8" fill="#fff" />
        </pattern>
      </defs>
      <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="#3f9f45" stroke="#fff" stroke-width="1.4" />
      <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="url(#mdShotsPitchStripes)" opacity="0.1" />
      ${gridLines}
      ${horizontalGrid}
      <rect x="${penX}" y="${pitchY}" width="${penWidth}" height="${penDepth}" fill="none" stroke="#fff" stroke-width="1" opacity="0.9" />
      <rect x="${sixX}" y="${pitchY}" width="${sixWidth}" height="${sixDepth}" fill="none" stroke="#fff" stroke-width="0.85" opacity="0.8" />
      ${penaltyArc}
      <line x1="${pitchX}" y1="${plotBottom}" x2="${pitchX + drawW}" y2="${plotBottom}" stroke="#fff" stroke-width="1" opacity="0.85" />
      ${markers}
    </svg>`;
}

function renderPitch(points, pitch, extra = "") {
  const fake = {
    pitch: pitch || {},
    shotPoints: (points || []).map((pt) => ({
      ...pt,
      outcome: pt.successful === true ? "scored" : "off_target",
      xgDisplay: "",
      xg: 0,
    })),
  };
  const svg = renderShotsPitchSvg(fake).replace("</svg>", `${extra}</svg>`);
  return `<div class="shots-pitch-wrap">${svg}</div>`;
}

function renderProgTeamMetricRows(rows, leagueSize) {
  return (rows || []).map((row) => {
    const rankHtml = row.avgRank
      ? `<span class="prog-table__rank ${progRankClass(row.avgRank, leagueSize)}">(${fmtOrdinal(row.avgRank)})</span>`
      : "";
    return `
      <tr>
        <td class="prog-table__metric" style="background:${progSoftColor(row.metricColor)}">
          ${esc(row.label)}
        </td>
        <td class="prog-table__avg">
          <div class="prog-table__avg-inner">
            <span class="prog-table__avg-val">${esc(row.avgDisplay ?? "—")}</span>
            ${rankHtml}
          </div>
        </td>
        <td class="prog-table__top7">${esc(row.top7AvgDisplay ?? "—")}</td>
        <td class="prog-table__match prog-table__match--${esc(row.matchBand || "neutral")}">
          ${esc(row.matchDisplay ?? "—")}
        </td>
      </tr>`;
  }).join("");
}

function renderShotsSummaryChips(summary) {
  if (!summary) return "";
  const chips = [
    `<span class="shots-summary__chip">${esc(summary.totalShots)} shots</span>`,
    `<span class="shots-summary__chip">${esc(summary.totalXgDisplay ?? summary.totalXg)} shot xG</span>`,
    `<span class="shots-summary__chip${summary.goals > 0 ? " shots-summary__chip--good" : ""}">${esc(summary.goals)} goal${summary.goals === 1 ? "" : "s"}</span>`,
    `<span class="shots-summary__chip">${esc(summary.onTarget)} on target</span>`,
  ];
  if (summary.avgShotsDisplay != null || summary.avgXgDisplay != null) {
    const avgLine = [
      summary.avgShotsDisplay != null ? `${summary.avgShotsDisplay} shots` : null,
      summary.avgXgDisplay != null ? `${summary.avgXgDisplay} shot xG` : null,
    ].filter(Boolean).join(" · ");
    chips.push(
      `<span class="shots-summary__chip shots-summary__chip--avg">7-game avg · ${esc(avgLine)}</span>`,
    );
  }
  return `<div class="shots-summary">${chips.join("")}</div>`;
}

function defaultShotsLegend() {
  return [
    { id: "off_target", label: "Blocked / Off target", color: "#ef4444" },
    { id: "saved", label: "Saved", color: "#facc15" },
    { id: "scored", label: "Scored", color: "#22c55e" },
  ];
}

function defaultShotsPhaseLegend() {
  return [
    { id: "Possession", label: "Possession", shape: "circle" },
    { id: "Transition", label: "Transition", shape: "diamond" },
    { id: "Set Play", label: "Set Play", shape: "square" },
  ];
}

function renderShotsKey(data) {
  const outcomeItems = (data.legend?.length ? data.legend : defaultShotsLegend())
    .map(
      (item) => `
    <span class="shots-key__item">
      <span class="shots-key__swatch">${shotLegendShapeSvg("circle", item.color)}</span>
      <span>${esc(item.label)}</span>
    </span>`
    )
    .join("");
  const phaseItems = (data.phaseLegend?.length ? data.phaseLegend : defaultShotsPhaseLegend())
    .map(
      (item) => `
    <span class="shots-key__item">
      <span class="shots-key__swatch">${shotLegendShapeSvg(
        item.shape === "diamond" ? "diamond" : item.shape === "square" ? "square" : "circle",
        "#cbd5e1"
      )}</span>
      <span>${esc(item.label)}</span>
    </span>`
    )
    .join("");
  const goldRing = `
    <span class="shots-key__item">
      <span class="shots-key__swatch shots-key__swatch--gold">
        <svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.2" fill="#ef4444" stroke="#fbbf24" stroke-width="1.6"/></svg>
      </span>
      <span>Gold ring · higher xG</span>
    </span>`;
  return `
    <aside class="shots-key" aria-label="Shot map key">
      <div class="shots-key__title">Key</div>
      <div class="shots-key__group">
        <div class="shots-key__label">Outcome</div>
        <div class="shots-key__items">${outcomeItems}</div>
      </div>
      <div class="shots-key__group">
        <div class="shots-key__label">Phase</div>
        <div class="shots-key__items">${phaseItems}</div>
      </div>
      <div class="shots-key__group">
        <div class="shots-key__label">Quality</div>
        <div class="shots-key__items">${goldRing}</div>
      </div>
    </aside>`;
}

function renderShotsPhaseCell(value, avgDisplay, suffix = "") {
  if (avgDisplay == null) {
    return `<span class="shots-phase-table__val">${esc(value)}${esc(suffix)}</span>`;
  }
  return `
    <span class="shots-phase-table__stack">
      <span class="shots-phase-table__val">${esc(value)}${esc(suffix)}</span>
      <span class="shots-phase-table__avg">${esc(avgDisplay)} avg</span>
    </span>`;
}

function renderStory(data) {
  const mom = data.momentum || {};
  const blocks = mom.blocks || [];
  const summary = mom.summary || {};
  const race = data.xgRace || {};
  const blockHtml = blocks
    .map((block) => {
      const vale = Number(block.focusSharePercent || 0);
      const opp = Math.max(0, 100 - vale);
      return `<article class="md-block">
        <div class="md-block__time">${esc(block.label || `${block.start}'–${block.end}'`)}</div>
        <div class="md-dom">
          <div class="md-dom__vale" style="flex:${vale}">${vale}%</div>
          <div class="md-dom__opp" style="flex:${opp}">${opp}%</div>
        </div>
        <div class="md-press">
          <strong>${esc(block.focusPressCount ?? "—")}</strong>
          presses · ${esc(block.focusDuelWinPct ?? "—")}% duels
          <div>${esc(block.focusMeanPressure ?? "—")} int · ${esc(block.focusRegains ?? 0)} regains</div>
        </div>
        <div class="md-xg"><span style="color:#16a34a">${esc(block.focusXg)}</span> vs <span style="color:#2563eb">${esc(block.opponentXg)}</span><br>${esc(block.focusShots)}-${esc(block.opponentShots)} shots</div>
      </article>`;
    })
    .join("");

  const home = race.home || {};
  const away = race.away || {};
  const maxXg = Math.max(home.totalXg || 0, away.totalXg || 0, 1);
  const w = 900;
  const h = 220;
  const toPath = (series, color) => {
    if (!series.length) return "";
    const pts = series.map((p, i) => {
      const x = 40 + (Number(p.minute || 0) / 95) * (w - 60);
      const y = h - 24 - (Number(p.xg || 0) / maxXg) * (h - 40);
      return `${i ? "L" : "M"}${x},${y}`;
    });
    return `<path d="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="3"/>`;
  };

  return `<section class="md-panel">
    <div class="md-bar">Match story — 15-minute blocks</div>
    <div class="md-body">
      <div class="md-blocks">${blockHtml}</div>
      <h3 style="margin:1rem 0 .4rem">Shot-based xG</h3>
      <svg viewBox="0 0 ${w} ${h}" width="100%" xmlns="http://www.w3.org/2000/svg" style="background:#fff;border-radius:10px">
        ${toPath(home.series || [], "#3b82f6")}
        ${toPath(away.series || [], "#22c55e")}
        <text x="48" y="18" fill="#64748b" font-size="12">${esc(home.name || "Home")} ${esc(home.totalXg)} xG vs ${esc(away.name || "Away")} ${esc(away.totalXg)} xG</text>
      </svg>
      <div class="md-footcards">
        <div class="md-footcard"><h4>Press & ball wins</h4>${esc(summary.matchPressCount)} presses · ${esc(summary.matchRegains)} regains · ${esc(summary.matchDuelWinPct)}% duels</div>
        <div class="md-footcard"><h4>xG</h4>Port Vale ${esc(summary.matchFocusXg)} · Opp ${esc(summary.matchOpponentXg)}</div>
        <div class="md-footcard"><h4>Blocks led</h4>Vale ${esc(summary.focusBlocksWon)} · Opp ${esc(summary.opponentBlocksWon)}</div>
        <div class="md-footcard"><h4>Shots</h4>${esc(summary.matchFocusShots)} for · ${esc(summary.matchOpponentShots)} against</div>
        <div class="md-footcard"><h4>Regain rate</h4>${esc(summary.matchRegainRate ?? "—")}%</div>
      </div>
    </div>
  </section>`;
}

function renderProgression(data) {
  const players = data.players || [];
  return `<section class="md-panel">
    <div class="md-bar">${esc(data.title || "Ball progression")}</div>
    <div class="md-body">
      <div class="md-grid-2">
        ${teamTable(data.teamMetrics, data.opponentLabel)}
        <table class="md-table"><thead><tr><th>Player</th><th>Mins</th><th>Breaking</th><th>Progression</th><th>Def. control</th></tr></thead>
        <tbody>${players
          .map(
            (p) => `<tr>
            <td>${esc(p.playerName)}</td><td>${esc(p.minutes)}</td>
            <td class="${esc(p.breakingOpponentDefenceHighlight || "")}">${esc(p.breakingOpponentDefence)}</td>
            <td class="${esc(p.ballProgressionHighlight || "")}">${esc(p.ballProgression)}</td>
            <td class="${esc(p.defensiveBallControlHighlight || "")}">${esc(p.defensiveBallControl)}</td>
          </tr>`
          )
          .join("")}</tbody></table>
      </div>
      <p style="font-size:.8rem;color:#64748b">${(data.legend || []).map((l) => l.label).join(" · ")}</p>
    </div>
  </section>`;
}

function renderCrosses(data) {
  const summary = data.summary || {};
  const lanes = data.lanes || [];
  const maxLane = data.maxLaneValue || 1;
  return `<section class="md-panel">
    <div class="md-bar">${esc(data.title || "Crosses")}</div>
    <div class="md-body">
      ${pillRow([
        { text: `${summary.total || 0} crosses` },
        { text: `${summary.highCross || 0} high · ${summary.lowCross || 0} low` },
        { text: `${summary.successful || 0} successful · ${summary.failed || 0} failed`, ok: true },
        { text: `Altered threat ${summary.alteredThreat ?? "—"}%` },
      ])}
      <div class="md-grid-2">
        <div>
          ${renderPitch(data.crossPoints, data.pitch)}
          <div class="md-lanes">${lanes
            .map((lane) => {
              const t = 0.25 + 0.75 * (Number(lane.value || 0) / maxLane);
              return `<div class="md-lane" style="background:rgba(34,197,94,${t})">${esc(lane.label)}<br>${esc(lane.value)}</div>`;
            })
            .join("")}</div>
        </div>
        <table class="md-table"><thead><tr><th>Player</th><th>Crosses</th><th>Threat</th></tr></thead>
        <tbody>${(data.players || [])
          .map((p) => {
            const threat = Number(p.alteredThreat || 0);
            const cls = threat > 0 ? "hl-green" : "hl-pink";
            return `<tr><td>${esc(p.playerName)}</td><td>${esc(p.crosses)} (${esc(p.successful || 0)} suc)</td><td class="${cls}">${esc(p.alteredThreat)}%</td></tr>`;
          })
          .join("")}</tbody></table>
      </div>
    </div>
  </section>`;
}

function renderXgHero(xg) {
  if (!xg) return "";
  if (xg.scope === "match" && xg.matches?.length) {
    const match = xg.matches[0];
    const valeGoals = match.valeGoals ?? "—";
    const oppGoals = match.oppGoals ?? "—";
    const valeXg = Number(match.valeXg || 0);
    const oppXg = Number(match.oppXg || 0);
    const maxXg = Math.max(valeXg, oppXg, 0.01);
    const valeWon = Number.isFinite(match.valeGoals) && Number.isFinite(match.oppGoals) && match.valeGoals > match.oppGoals;
    const oppWon = Number.isFinite(match.valeGoals) && Number.isFinite(match.oppGoals) && match.oppGoals > match.valeGoals;
    const opponentCrest = match.opponent?.imageUrl
      ? `<img class="xca-match-hero__crest" src="${esc(match.opponent.imageUrl)}" alt="" />`
      : `<div class="xca-match-hero__crest xca-match-hero__crest--placeholder">${esc((match.opponent?.name || "Opp").slice(0, 2))}</div>`;
    return `<section class="card">
      <div class="xca-match-hero">
        <div class="xca-match-hero__top">
          <div class="xca-match-hero__chips">
            <span class="xca-match-hero__chip xca-match-hero__chip--accent">MD${esc(match.matchDay ?? "?")}</span>
            <span class="xca-match-hero__chip">${esc(match.dateLabel || "")}</span>
            <span class="xca-match-hero__chip">${esc(match.venue || "")}</span>
          </div>
          <div class="xca-match-hero__comp">${esc(xg.competition || "")} ${esc(xg.season || "")}</div>
        </div>
        <div class="xca-match-hero__scoreboard">
          <div class="xca-match-hero__team xca-match-hero__team--vale ${valeWon ? "xca-match-hero__team--winner" : ""}">
            <img class="xca-match-hero__crest" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" />
            <div class="xca-match-hero__team-name">Port Vale</div>
            <div class="xca-match-hero__goals">${esc(valeGoals)}</div>
          </div>
          <div class="xca-match-hero__versus">–</div>
          <div class="xca-match-hero__team xca-match-hero__team--opp ${oppWon ? "xca-match-hero__team--winner" : ""}">
            ${opponentCrest}
            <div class="xca-match-hero__team-name">${esc(match.opponent?.name || "Opponent")}</div>
            <div class="xca-match-hero__goals">${esc(oppGoals)}</div>
          </div>
        </div>
        <div class="xca-match-hero__xg">
          <div class="xca-match-hero__xg-row">
            <div class="xca-match-hero__xg-label">Vale xG</div>
            <div class="xca-match-hero__xg-track"><div class="xca-match-hero__xg-fill xca-match-hero__xg-fill--vale" style="width:${xgBarWidth(valeXg, maxXg)}%"></div></div>
            <div class="xca-match-hero__xg-value">${valeXg.toFixed(3)}</div>
          </div>
          <div class="xca-match-hero__xg-row">
            <div class="xca-match-hero__xg-label">Opp xG</div>
            <div class="xca-match-hero__xg-track"><div class="xca-match-hero__xg-fill xca-match-hero__xg-fill--opp" style="width:${xgBarWidth(oppXg, maxXg)}%"></div></div>
            <div class="xca-match-hero__xg-value">${oppXg.toFixed(3)}</div>
          </div>
        </div>
        <div class="xca-match-hero__footer">
          <span><strong>${esc(match.valeShots ?? 0)}</strong> Vale shots</span>
          <span><strong>${esc(match.shotCount ?? 0)}</strong> total shots</span>
          <span><strong>${esc(match.oppShots ?? 0)}</strong> Opp shots</span>
        </div>
      </div>
    </section>`;
  }
  const averages = xg.averages || {};
  return `<section class="card">
    <div class="xca-match-hero xca-match-hero--multi">
      <div class="xca-match-hero__top">
        <div class="xca-match-hero__chips">
          <span class="xca-match-hero__chip xca-match-hero__chip--accent">${esc(xg.scopeLabel || "Combined")}</span>
          <span class="xca-match-hero__chip">${esc(averages.games || xg.matchCount || 0)} games</span>
        </div>
        <div class="xca-match-hero__comp">${esc(xg.competition || "")} ${esc(xg.season || "")}</div>
      </div>
      <div class="xca-avg-grid">
        <div class="xca-avg-card"><div class="xca-avg-card__label">xG for / game</div><div class="xca-avg-card__value">${Number(averages.valeXg || 0).toFixed(3)}</div></div>
        <div class="xca-avg-card"><div class="xca-avg-card__label">xG against / game</div><div class="xca-avg-card__value">${Number(averages.oppXg || 0).toFixed(3)}</div></div>
        <div class="xca-avg-card"><div class="xca-avg-card__label">xG difference</div><div class="xca-avg-card__value">${Number(averages.xgDiff || 0).toFixed(3)}</div></div>
        <div class="xca-avg-card"><div class="xca-avg-card__label">HQ shot share</div><div class="xca-avg-card__value">${Number(averages.valeHighQualityPct || 0).toFixed(1)}%</div></div>
      </div>
    </div>
  </section>`;
}

function renderBucketCard(title, summary) {
  const rows = (summary?.buckets || [])
    .map((row) => `<tr>
        <td><span class="xca-rating-pill" style="background:${esc(row.color)}">${esc(row.label)}</span></td>
        <td>${esc(row.goals)}</td><td>${esc(row.count)}</td><td>${esc(row.pct)}%</td>
        <td>${Number(row.cumulativeXg || 0).toFixed(3)}</td>
      </tr>`)
    .join("");
  const grouped = summary?.grouped || {};
  const totals = summary?.totals || {};
  return `<section class="card xca-bucket-panel">
    <h2 class="xca-panel-title">${esc(title)}</h2>
    <table class="xca-bucket-table">
      <thead><tr><th>Chance rating</th><th>Goals</th><th>Count</th><th>%</th><th>Cumulative xG</th></tr></thead>
      <tbody>
        ${rows}
        <tr class="xca-grouped-row"><td>${esc(grouped.highQuality?.label || "Excellent / Very Good")}</td><td>${esc(grouped.highQuality?.goals ?? 0)}</td><td>${esc(grouped.highQuality?.count ?? 0)}</td><td>—</td><td>${Number(grouped.highQuality?.cumulativeXg || 0).toFixed(3)}</td></tr>
        <tr class="xca-grouped-row"><td>${esc(grouped.lowQuality?.label || "Poor / Very Poor")}</td><td>${esc(grouped.lowQuality?.goals ?? 0)}</td><td>${esc(grouped.lowQuality?.count ?? 0)}</td><td>—</td><td>${Number(grouped.lowQuality?.cumulativeXg || 0).toFixed(3)}</td></tr>
      </tbody>
      <tfoot><tr><td>Total</td><td>${esc(totals.goals ?? 0)}</td><td>${esc(totals.shots ?? 0)}</td><td>100%</td><td>${Number(totals.cumulativeXg || 0).toFixed(3)}</td></tr></tfoot>
    </table>
  </section>`;
}

function gameStatePill(id, label) {
  return `<span class="xca-state-pill xca-state-pill--${esc(id)}">${esc(label)}</span>`;
}

function renderPlayerCards(title, players, variant) {
  const list = players || [];
  const accentClass = variant === "vale" ? "xca-player-panel--vale" : "xca-player-panel--opp";
  if (!list.length) {
    return `<section class="card"><div class="xca-player-panel ${accentClass}"><h2 class="xca-panel-title">${esc(title)}</h2><p class="xca-player-panel__empty">No shots recorded</p></div></section>`;
  }
  const maxXg = Math.max(...list.map((row) => Number(row.xg) || 0), 0.01);
  const totalXg = list.reduce((sum, row) => sum + (Number(row.xg) || 0), 0);
  const totalShots = list.reduce((sum, row) => sum + (Number(row.shots) || 0), 0);
  const totalGoals = list.reduce((sum, row) => sum + (Number(row.goals) || 0), 0);
  const hq = list.reduce((sum, row) => sum + Number(row.chanceCounts?.excellent || 0) + Number(row.chanceCounts?.very_good || 0), 0);
  const cards = list.map((row, index) => {
    const width = Math.max(10, Math.round(((Number(row.xg) || 0) / maxXg) * 100));
    const tags = CHANCE_TAG_SPECS.map((spec) => {
      const cls = {
        excellent: "xca-player-tag--excellent",
        very_good: "xca-player-tag--very-good",
        ok: "xca-player-tag--ok",
        poor: "xca-player-tag--poor",
        very_poor: "xca-player-tag--very-poor",
      }[spec.id];
      return `<span class="xca-player-tag ${cls}">${Number(row.chanceCounts?.[spec.id] || 0)} ${spec.label}</span>`;
    }).join("");
    const goals = row.goals ? `<span class="xca-player-card__goal">${row.goals} goal${row.goals === 1 ? "" : "s"}</span>` : "";
    return `<article class="xca-player-card">
      <div class="xca-player-card__head">
        <div class="xca-player-card__identity">
          <span class="xca-player-card__rank">#${index + 1}</span>
          <div>
            <div class="xca-player-card__name">${esc(row.playerName)}</div>
            <div class="xca-player-card__sub">${esc(row.shots)} shots · ${Number(row.avgXg || 0).toFixed(3)} avg xG ${goals}</div>
          </div>
        </div>
        <div class="xca-player-card__xg">${Number(row.xg || 0).toFixed(3)}</div>
      </div>
      <div class="xca-player-card__bar"><div class="xca-player-card__bar-fill" style="width:${width}%"></div></div>
      <div class="xca-player-card__tags">${tags}</div>
    </article>`;
  }).join("");
  return `<section class="card"><div class="xca-player-panel ${accentClass}">
    <div class="xca-player-panel__header">
      <h2 class="xca-panel-title">${esc(title)}</h2>
      <div class="xca-player-panel__summary">
        <span><strong>${totalShots}</strong> shots</span>
        <span><strong>${totalXg.toFixed(3)}</strong> xG</span>
        <span><strong>${totalGoals}</strong> goals</span>
        <span><strong>${hq}</strong> Exc/VG</span>
      </div>
    </div>
    <div class="xca-player-panel__list">${cards}</div>
  </div></section>`;
}

function renderShotLog(xg) {
  const showMatch = (xg.matchCount || 0) > 1;
  const colCount = showMatch ? 16 : 14;
  const timeline = [];
  for (const dismissal of xg.dismissals || []) timeline.push({ kind: "dismissal", seconds: dismissal.seconds, dismissal });
  for (const shot of xg.shots || []) timeline.push({ kind: "shot", seconds: shot.seconds, shot });
  timeline.sort((a, b) => a.seconds - b.seconds);
  const rows = [];
  for (const item of timeline) {
    if (item.kind === "dismissal") {
      const d = item.dismissal;
      rows.push(`<tr class="xca-dismissal-marker"><td colspan="${colCount}">${esc((d.playerName || "Player").toUpperCase())} RED · ${esc(d.minute)}'</td></tr>`);
      continue;
    }
    const shot = item.shot;
    const rating = shot.chanceRating || chanceFromXg(shot.xg);
    const matchCols = showMatch ? `<td class="col-left">MD${esc(shot.matchDay ?? "")}</td><td class="col-left">${esc(shot.opponentName || "")}</td>` : "";
    const teamClass = shot.team === "vale" ? "xca-team-pill--vale" : "xca-team-pill--opp";
    const outcomeClass = shot.outcome === "goal" ? "xca-outcome--goal" : "xca-outcome--miss";
    rows.push(`<tr>
      ${matchCols}
      <td>${gameStatePill(shot.gameState, shot.gameStateLabel)}</td>
      <td class="col-left">${esc(shot.playerName)}</td>
      <td><span class="xca-team-pill ${teamClass}">${shot.team === "vale" ? "VALE" : "OPP"}</span></td>
      <td>${esc(shot.minute)}</td>
      <td>${String(shot.second ?? 0).padStart(2, "0")}</td>
      <td>${esc(shot.xgDisplay || Number(shot.xg || 0).toFixed(3))}</td>
      <td>${esc(shot.shotNumber)}</td>
      <td><span class="xca-rating-pill" style="background:${esc(rating.color)}">${esc(rating.label)}</span></td>
      <td>${esc(shot.inBoxLabel)}</td>
      <td>${esc(shot.onTargetLabel)}</td>
      <td class="${outcomeClass}">${esc(shot.outcomeLabel)}</td>
      <td>${Number(shot.cumulativeXg || 0).toFixed(3)}</td>
      <td>${esc(shot.halfLabel)}</td>
      <td>${esc(shot.manpower)}</td>
    </tr>`);
  }
  const head = showMatch
    ? `<tr><th class="col-left">MD</th><th class="col-left">Opponent</th><th>State</th><th class="col-left">Player</th><th>Team</th><th>Min</th><th>Sec</th><th>xG</th><th>#</th><th>Rating</th><th>Box</th><th>On tgt</th><th>Outcome</th><th>Cum xG</th><th>Half</th><th>MP</th></tr>`
    : `<tr><th>State</th><th class="col-left">Player</th><th>Team</th><th>Min</th><th>Sec</th><th>xG</th><th>#</th><th>Rating</th><th>Box</th><th>On tgt</th><th>Outcome</th><th>Cum xG</th><th>Half</th><th>MP</th></tr>`;
  return `<section class="card xca-shot-log-wrap"><div class="xca-shot-log-scroll"><table class="xca-shot-table"><thead>${head}</thead>
    <tbody>${rows.join("") || `<tr><td colspan="${colCount}">No shots recorded</td></tr>`}</tbody></table></div></section>`;
}

function renderTrends(xg) {
  const insights = xg?.trends?.insights || [];
  const metrics = xg?.trends?.metrics || [];
  if (!insights.length && !metrics.length) return "";
  const metricHtml = metrics.map((row) => {
    const dirClass = row.direction === "up" ? "xca-trend--up" : row.direction === "down" ? "xca-trend--down" : "xca-trend--flat";
    return `<div class="xca-trend-metric ${dirClass}">
      <div class="xca-trend-metric__label">${esc(row.label)}</div>
      <div class="xca-trend-metric__values"><span>${esc(row.earlier)}</span><span>→</span><span>${esc(row.recent)}</span></div>
      <div class="xca-trend-metric__dir">${esc((row.direction || "flat").toUpperCase())}</div>
    </div>`;
  }).join("");
  const matchRows = (xg.matchTrends || []).map((row) => `<tr>
      <td>MD${esc(row.matchDay ?? "")}</td>
      <td class="col-left">${esc(row.opponent?.name || "")}</td>
      <td>${esc(row.score || "—")}</td>
      <td>${Number(row.valeXg || 0).toFixed(3)}</td>
      <td>${Number(row.oppXg || 0).toFixed(3)}</td>
      <td>${Number(row.valeHighQualityPct || 0).toFixed(1)}%</td>
    </tr>`).join("");
  return `<section class="card xca-trends-panel">
    <div class="xca-trends">
      <div class="xca-trends__copy">
        <h2 class="xca-panel-title">Recent form &amp; trends</h2>
        <ul class="xca-trends__insights">${insights.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
      </div>
      <div class="xca-trends__metrics">${metricHtml}</div>
      <div class="xca-trends__table-wrap">
        <table class="xca-mini-table">
          <thead><tr><th>MD</th><th class="col-left">Opponent</th><th>Score</th><th>Vale xG</th><th>Opp xG</th><th>HQ%</th></tr></thead>
          <tbody>${matchRows}</tbody>
        </table>
      </div>
    </div>
  </section>`;
}

function renderXgChance(xg, error) {
  if (!xg) {
    return `<section class="xca-embed"><p class="xca-empty">${esc(error || "xG chance breakdown unavailable for this selection.")}</p></section>`;
  }
  const periodRows = (rows, a, b, c, d) =>
    (rows || [])
      .map(
        (row) =>
          `<tr><td>${esc(row.label)}</td><td>${esc(row[a])}</td><td>${Number(row[b] || 0).toFixed(3)}</td><td>${esc(row[c])}</td><td>${Number(row[d] || 0).toFixed(3)}</td></tr>`
      )
      .join("");
  const view = state.chanceView || "summary";
  const summaryPane = `
    <div class="xca-summary-grid">
      ${renderBucketCard("xG Created (Vale)", xg.xgCreated)}
      ${renderBucketCard("xG Against (Opposition)", xg.xgAgainst)}
    </div>
    <div class="xca-secondary-grid">
      <section class="card">
        <h2 class="xca-panel-title">Game state when shooting (Vale)</h2>
        <table class="xca-mini-table"><thead><tr><th>State</th><th>Shots</th><th>Goals</th><th>xG</th></tr></thead>
        <tbody>${(xg.gameStateBreakdown?.vale || [])
          .map(
            (row) =>
              `<tr><td>${gameStatePill(row.id, row.label)}</td><td>${esc(row.shots)}</td><td>${esc(row.goals)}</td><td>${Number(row.xg || 0).toFixed(3)}</td></tr>`
          )
          .join("")}</tbody></table>
      </section>
      <section class="card">
        <h2 class="xca-panel-title">Half &amp; manpower splits</h2>
        <table class="xca-mini-table"><thead><tr><th>Period</th><th>Vale shots</th><th>Vale xG</th><th>Opp shots</th><th>Opp xG</th></tr></thead>
        <tbody>${periodRows(xg.periodBreakdown?.halves, "valeShots", "valeXg", "oppShots", "oppXg")}</tbody></table>
        <table class="xca-mini-table" style="margin-top:.6rem"><thead><tr><th>Manpower</th><th>Vale shots</th><th>Vale xG</th><th>Opp shots</th><th>Opp xG</th></tr></thead>
        <tbody>${periodRows(xg.periodBreakdown?.manpower, "valeShots", "valeXg", "oppShots", "oppXg")}</tbody></table>
      </section>
    </div>`;
  const body =
    view === "shots"
      ? renderShotLog(xg)
      : view === "players"
        ? `<div class="xca-players-grid">${renderPlayerCards("Vale — shot quality by player", xg.playerBreakdown?.vale, "vale")}${renderPlayerCards("Opposition — shot quality by player", xg.playerBreakdown?.opp, "opp")}</div>`
        : summaryPane;
  return `<section class="xca-embed md-xca">
    ${renderXgHero(xg)}
    ${renderTrends(xg)}
    <div class="md-xca-tabs" role="tablist" aria-label="Chance analysis views">
      <button type="button" class="md-xca-tab${view === "summary" ? " is-active" : ""}" data-chance-view="summary">Summary</button>
      <button type="button" class="md-xca-tab${view === "shots" ? " is-active" : ""}" data-chance-view="shots">Shot log</button>
      <button type="button" class="md-xca-tab${view === "players" ? " is-active" : ""}" data-chance-view="players">Players</button>
    </div>
    <div class="xca-main">${body}</div>
  </section>`;
}

function renderMapPanel(data) {
  if (!data) return `<section class="md-empty">No shots data.</section>`;
  const opponent = data.opponentLabel || "Opponent";
  const leagueSize = data.leagueSize || 24;
  const teamRows = renderProgTeamMetricRows(data.teamMetrics, leagueSize);
  const summaryChips = renderShotsSummaryChips(data.summary);
  const shotsKey = renderShotsKey(data);
  const players = data.players || [];
  const playerBodyRows = players.length
    ? players.map((row) => {
      const xgClass = row.highlightXg ? "shots-player-table__xg shots-player-table__xg--top" : "shots-player-table__xg";
      return `
      <tr>
        <td class="shots-player-table__name">${esc(row.playerName)}</td>
        <td class="shots-player-table__shots">${esc(row.shots)}</td>
        <td class="${xgClass}">${esc(row.xgDisplay ?? row.xg)}</td>
      </tr>`;
    }).join("")
    : `<tr><td colspan="3">No shots recorded for this match.</td></tr>`;
  const playerRowCount = players.length ? players.length + 1 : 1;
  const playerTableClass = players.length >= 7
    ? "shots-player-table shots-player-table--compact"
    : "shots-player-table";
  const totalRow = players.length
    ? `<tr class="shots-player-table__total">
        <td class="shots-player-table__name">Total</td>
        <td class="shots-player-table__shots">${esc(data.summary?.totalShots ?? players.reduce((sum, row) => sum + (row.shots || 0), 0))}</td>
        <td class="shots-player-table__xg">${esc(data.summary?.totalXgDisplay ?? "—")}</td>
      </tr>`
    : "";
  const phaseRows = (data.phases || []).map((row) => `
      <tr class="${row.isTotal ? "shots-phase-table__total" : ""}">
        <td class="shots-phase-table__phase">${esc(row.label)}</td>
        <td class="shots-phase-table__shots">${renderShotsPhaseCell(row.shots, row.avgShotsDisplay)}</td>
        <td class="shots-phase-table__xg">${renderShotsPhaseCell(row.xgDisplay ?? row.xg, row.avgXgDisplay)}</td>
      </tr>`).join("");

  return `
    <section class="md-panel md-panel--map">
      <div class="shots-keynote">
        <div class="shots-keynote__bar">${esc(data.title || "In-possession — shots & xG")}</div>
        <div class="shots-keynote__body">
          <div class="shots-sidebar">
            ${summaryChips}
            <div class="shots-metrics-panel">
              <table class="prog-table shots-team-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>7 Game Avg</th>
                    <th>Top 7 Avg</th>
                    <th>Vs ${esc(opponent)}</th>
                  </tr>
                </thead>
                <tbody>${teamRows || `<tr><td colspan="4">No data</td></tr>`}</tbody>
              </table>
            </div>
          </div>
          <div class="shots-center">
            ${shotsKey}
            <div class="shots-pitch-wrap">${renderShotsPitchSvg(data)}</div>
          </div>
          <div class="shots-bottom">
            <table class="${playerTableClass}" style="--shot-player-rows:${playerRowCount}">
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Shots</th>
                  <th>xG</th>
                </tr>
              </thead>
              <tbody>${playerBodyRows}${totalRow}</tbody>
            </table>
            <div class="shots-phase-panel">
              <table class="shots-phase-table">
                <thead>
                  <tr>
                    <th>Phase</th>
                    <th>Shots</th>
                    <th>xG</th>
                  </tr>
                </thead>
                <tbody>${phaseRows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </section>`;
}

function renderShots(data) {
  return `${renderMapPanel(data)}${renderXgChance(data.xgChance, data.xgChanceError)}`;
}


function highlightClass(value) {
  if (!value) return "";
  const text = String(value).toLowerCase();
  if (text.includes("gold") || text.includes("top")) return "hl-gold";
  if (text.includes("blue")) return "hl-blue";
  if (text.includes("green")) return "hl-green";
  if (text.includes("red")) return "hl-red";
  return "";
}

function renderDuels(data) {
  const players = data.players || [];
  return `<section class="md-panel">
    <div class="md-bar">${esc(data.title || "Duels and pressing")}</div>
    <div class="md-body">
      <div class="md-grid-2">
        <div>
          <h3>Duels</h3>
          ${teamTable(data.duelMetrics || [], data.opponentLabel)}
          <h3>Pressing</h3>
          ${teamTable(data.pressingMetrics || [], data.opponentLabel)}
        </div>
        <table class="md-table"><thead><tr>
          <th>Player</th><th>Ground</th><th>Aerial</th><th>Win %</th><th>Off int</th><th>Def int</th><th>Wins vs defs</th>
        </tr></thead>
        <tbody>${players
          .map(
            (p) => `<tr>
            <td>${esc(p.playerName)}</td>
            <td>${esc(p.groundDuelsWin)}</td>
            <td>${esc(p.aerialDuelsWin)}</td>
            <td>${esc(p.totalWinDisplay || p.totalWinPct)}</td>
            <td>${esc(p.offensiveInterventions)}</td>
            <td>${esc(p.defensiveInterventions)}</td>
            <td>${esc(p.ballWinsFromOppositionDefenders)}</td>
          </tr>`
          )
          .join("")}</tbody></table>
      </div>
    </div>
  </section>`;
}

function renderDashboard(report) {
  const data = report.data || {};
  const view = report.view;
  if (view === "story") els.dashboardRoot.innerHTML = renderStory(data);
  else if (view === "progression") els.dashboardRoot.innerHTML = renderProgression(data);
  else if (view === "crosses") els.dashboardRoot.innerHTML = renderCrosses(data);
  else if (view === "duels") els.dashboardRoot.innerHTML = renderDuels(data);
  else els.dashboardRoot.innerHTML = renderShots(data);
}

async function exportShotsPdf() {
  const ids = [...state.selected];
  if (!ids.length) {
    setStatus("Select at least one game.", "error");
    return;
  }
  const btn = document.getElementById("exportBtn");
  if (btn) btn.disabled = true;
  setStatus("Building Keynote PDF…");
  try {
    const params = new URLSearchParams({
      matchIds: ids.join(","),
      side: state.side,
      view: "shots",
      _: String(Date.now()),
    });
    const res = await fetch(`/api/match-dashboards/export-pdf?${params}`, { cache: "no-store" });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] || "shots-xg-chance.pdf";
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
    setStatus(err.message || "PDF export failed", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function bind() {
  els.viewTabs.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-view]");
    if (!btn) return;
    state.view = btn.dataset.view;
    renderTabs();
    loadReport();
  });
  els.dashboardRoot.addEventListener("click", (ev) => {
    const paneBtn = ev.target.closest("[data-shots-pane]");
    if (paneBtn && state.report) {
      state.shotsPane = paneBtn.dataset.shotsPane;
      renderDashboard(state.report);
      return;
    }
    const chanceBtn = ev.target.closest("[data-chance-view]");
    if (chanceBtn && state.report) {
      state.chanceView = chanceBtn.dataset.chanceView;
      renderDashboard(state.report);
    }
  });
  document.querySelectorAll("[data-side]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.side = btn.dataset.side;
      renderSide();
      loadReport();
    });
  });
  els.gamePicker.addEventListener("change", (ev) => {
    const input = ev.target;
    if (input.type !== "checkbox") return;
    const id = Number(input.value);
    if (input.checked) state.selected.add(id);
    else state.selected.delete(id);
    renderGames();
    loadReport();
  });
  document.getElementById("selectLatest").addEventListener("click", () => {
    state.selected.clear();
    if (state.matches[0]) state.selected.add(Number(state.matches[0].matchId));
    renderGames();
    loadReport();
  });
  document.getElementById("selectAll").addEventListener("click", () => {
    state.selected = new Set(state.matches.map((m) => Number(m.matchId)));
    renderGames();
    loadReport();
  });
  document.getElementById("refreshBtn").addEventListener("click", loadReport);
  document.getElementById("exportBtn").addEventListener("click", () => {
    if (state.view === "shots") exportShotsPdf();
    else window.print();
  });
}

async function boot() {
  paramsFromUrl();
  renderTabs();
  renderSide();
  bind();
  try {
    await loadFixtures();
    await loadReport();
  } catch (err) {
    setStatus(err.message || "Could not load fixtures", "error");
  }
}

boot();
