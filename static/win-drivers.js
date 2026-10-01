const state = {
  meta: null,
  table: null,
  iterationId: null,
  loading: false,
  sortKey: "points",
  sortDir: "desc",
  breakdown: null,
  breakdownFor: null,
  breakdownPromise: null,
  detailKey: null,
  playerSort: { key: null, dir: "desc" },
  openTrends: new Set(),
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  lastUpdated: document.getElementById("lastUpdated"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusBanner: document.getElementById("statusBanner"),
  pageSubtitle: document.getElementById("pageSubtitle"),
  valeTitle: document.getElementById("valeTitle"),
  valeHint: document.getElementById("valeHint"),
  whyList: document.getElementById("whyList"),
  storyHeadline: document.getElementById("storyHeadline"),
  storyBullets: document.getElementById("storyBullets"),
  storySample: document.getElementById("storySample"),
  tableHint: document.getElementById("tableHint"),
  tableHead: document.getElementById("tableHead"),
  tableBody: document.getElementById("tableBody"),
  tableFoot: document.getElementById("tableFoot"),
  detail: document.getElementById("statDetail"),
  detailPanel: document.getElementById("detailPanel"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setStatus(message, isError = false) {
  if (!els.statusBanner) return;
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    els.statusBanner.classList.remove("status-banner--error");
    return;
  }
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
  els.statusBanner.classList.toggle("status-banner--error", isError);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* use default */
    }
    throw new Error(detail);
  }
  return res.json();
}

function formatValue(value, fmt, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const raw = Number(value);
  const n = Math.abs(raw) < 0.5 * 10 ** -digits ? 0 : raw;
  if (fmt === "int") return String(Math.round(n));
  if (fmt === "pct") return `${n.toFixed(digits)}%`;
  if (fmt === "signed") {
    const text = n.toFixed(digits);
    return n > 0 ? `+${text}` : text;
  }
  if (fmt === "dec") return n.toFixed(digits);
  return String(value);
}

function ordinal(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "—";
  const abs = Math.abs(num);
  const mod100 = abs % 100;
  const mod10 = abs % 10;
  let suffix = "th";
  if (mod100 < 11 || mod100 > 13) {
    if (mod10 === 1) suffix = "st";
    else if (mod10 === 2) suffix = "nd";
    else if (mod10 === 3) suffix = "rd";
  }
  return `${num}${suffix}`;
}

const HEAT_STOPS = [
  [0, [92, 10, 10]],
  [0.25, [176, 32, 32]],
  [0.5, [150, 98, 12]],
  [0.75, [24, 128, 62]],
  [1, [8, 60, 30]],
];

function heatColor(rank, total) {
  const r = Number(rank);
  if (!Number.isFinite(r) || !total || total < 2) return "rgba(55, 65, 81, 0.8)";
  const score = Math.min(1, Math.max(0, (total - r) / (total - 1)));
  for (let i = 1; i < HEAT_STOPS.length; i += 1) {
    const [p1, c1] = HEAT_STOPS[i];
    if (score <= p1) {
      const [p0, c0] = HEAT_STOPS[i - 1];
      const f = (score - p0) / (p1 - p0);
      const mix = c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
      return `rgb(${mix.join(", ")})`;
    }
  }
  return `rgb(${HEAT_STOPS[HEAT_STOPS.length - 1][1].join(", ")})`;
}

function rankInColumn(value, range, higherBetter) {
  const n = Number(value);
  if (!Number.isFinite(n) || !range?.values?.length) return null;
  const better = range.values.filter((v) => (higherBetter ? v > n : v < n)).length;
  return better + 1;
}

function columns() {
  const stats = state.table?.stats || [];
  return [
    { key: "position", label: "Pos", fmt: "int", heat: false },
    { key: "club", label: "Club", fmt: "club", heat: false },
    { key: "played", label: "P", fmt: "int", heat: false },
    { key: "won", label: "W", fmt: "int", higherBetter: true },
    { key: "drawn", label: "D", fmt: "int", heat: false },
    { key: "lost", label: "L", fmt: "int", higherBetter: false },
    { key: "points", label: "Pts", fmt: "int", higherBetter: true },
    { key: "ppg", label: "PPG", fmt: "dec", digits: 2, higherBetter: true },
    { key: "win_pct", label: "Win %", fmt: "pct", digits: 1, higherBetter: true },
    ...stats.map((stat) => ({
      key: stat.key,
      label: `#${stat.rank || ""} ${stat.short || stat.label}`.trim(),
      title: `${stat.label} — ${stat.why || stat.hint || ""} (${stat.strength || ""} · r=${stat.r} vs winning)`.trim(),
      fmt: stat.fmt || "dec",
      digits: stat.digits ?? 2,
      higherBetter: stat.higher_better !== false,
      heat: true,
      showRank: true,
    })),
  ];
}

function compareSortValues(a, b, key, dir) {
  const av = a?.[key];
  const bv = b?.[key];
  const aMissing = av == null || av === "";
  const bMissing = bv == null || bv === "";
  if (aMissing && bMissing) {
    return String(a.club || "").localeCompare(String(b.club || ""), undefined, { sensitivity: "base" });
  }
  if (aMissing) return 1;
  if (bMissing) return -1;
  let cmp;
  if (key === "club") {
    cmp = String(av).localeCompare(String(bv), undefined, { sensitivity: "base" });
  } else {
    cmp = Number(av) - Number(bv);
    if (Number.isNaN(cmp)) {
      cmp = String(av).localeCompare(String(bv), undefined, { sensitivity: "base", numeric: true });
    }
  }
  if (cmp === 0) {
    return String(a.club || "").localeCompare(String(b.club || ""), undefined, { sensitivity: "base" });
  }
  return dir === "asc" ? cmp : -cmp;
}

function sortedRows(rows, cols) {
  if (!state.sortKey) return rows;
  const col = cols.find((item) => item.key === state.sortKey);
  if (!col) return rows;
  return [...rows].sort((a, b) => compareSortValues(a, b, state.sortKey, state.sortDir));
}

function sortIndicator(key) {
  if (state.sortKey !== key) return "";
  return state.sortDir === "asc" ? " ▲" : " ▼";
}

function defaultDirFor(col) {
  if (col?.fmt === "club") return "asc";
  if (col?.higherBetter === false) return "asc";
  return "desc";
}

function cycleSort(col) {
  if (state.sortKey !== col.key) {
    state.sortKey = col.key;
    state.sortDir = defaultDirFor(col);
    return;
  }
  state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
}

function renderSeasons() {
  if (!els.seasonToggle || !state.meta) return;
  els.seasonToggle.innerHTML = "";
  for (const season of state.meta.seasons || []) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "season-toggle__btn";
    btn.textContent = season.label || season.season;
    btn.classList.toggle("is-active", Number(season.iteration_id) === Number(state.iterationId));
    btn.addEventListener("click", () => {
      if (Number(season.iteration_id) === Number(state.iterationId)) return;
      loadTable(season.iteration_id);
    });
    els.seasonToggle.appendChild(btn);
  }
}

function rankTone(rank, of) {
  if (!rank || !of) return "is-mid";
  if (rank <= Math.max(3, Math.ceil(of / 4))) return "is-good";
  if (rank >= of - Math.max(2, Math.floor(of / 4)) + 1) return "is-bad";
  return "is-mid";
}

function barTone(above) {
  if (above == null) return "";
  return above ? "is-good" : "is-bad";
}

/* Green = at/better than the top-7 avg, amber = between league avg and top 7, red = worse than league avg. */
function tone3(stat, value) {
  if (value == null || !Number.isFinite(Number(value))) return "";
  const dir = stat.higher_better !== false ? 1 : -1;
  const v = Number(value);
  if (stat.top7_avg != null && dir * (v - Number(stat.top7_avg)) >= 0) return "is-good";
  if (stat.league_avg != null && dir * (v - Number(stat.league_avg)) >= 0) return "is-mid";
  if (stat.top7_avg == null && stat.league_avg == null) return "";
  return "is-bad";
}

/* Head-to-head comparison: within `tol` (fraction of the bar) of the bar reads as amber. */
function toneVs(stat, value, bar, tol = 0.1) {
  if (value == null || bar == null) return "";
  const dir = stat.higher_better !== false ? 1 : -1;
  const diff = dir * (Number(value) - Number(bar));
  const band = Math.max(Math.abs(Number(bar)), Math.abs(Number(stat.league_avg) || 0), 1e-9) * tol;
  if (Math.abs(diff) <= band) return "is-mid";
  return diff > 0 ? "is-good" : "is-bad";
}

function formatWithUnit(card, value) {
  const text = formatValue(value, card.fmt, card.digits);
  if (text === "—" || card.fmt === "pct" || !card.unit) return text;
  return `${text} <span class="why-fig__unit">${escapeHtml(card.unit)}</span>`;
}

function figureHtml(label, valueHtml, { tone = "", extraClass = "" } = {}) {
  return `<span class="why-fig ${extraClass} ${tone}">
    <span class="why-fig__label">${escapeHtml(label)}</span>
    <strong class="why-fig__value">${valueHtml}</strong>
  </span>`;
}

function renderStory() {
  const story = state.table?.story;
  if (!story) return;
  if (els.storyHeadline && story.headline) els.storyHeadline.textContent = story.headline;
  if (els.storyBullets) {
    els.storyBullets.innerHTML = (story.bullets || [])
      .map((line) => `<li>${escapeHtml(line)}</li>`)
      .join("");
  }
  if (els.storySample) els.storySample.textContent = story.sample || "";
}

function renderWhyList() {
  const focus = state.table?.focus;
  const cards = focus?.cards || [];
  if (els.valeTitle) {
    const pos = focus?.position ? ` · ${ordinal(focus.position)} this season` : "";
    const played = focus?.played ? ` · ${focus.played} played` : "";
    els.valeTitle.textContent = `${focus?.club || "Port Vale"} on the 15${pos}${played}`;
  }
  if (!els.whyList) return;
  if (!cards.length) {
    els.whyList.innerHTML = `<p class="vale-panel__hint">No Port Vale row in this season’s table — pick a season we were in League Two.</p>`;
    return;
  }

  const groups = [
    { id: "process", start: 1, end: 5 },
    { id: "volume", start: 6, end: 10 },
    { id: "support", start: 11, end: 15 },
  ];
  els.whyList.innerHTML = groups
    .map((group) => {
      const rows = cards.filter((card) => {
        const rank = Number(card.importance || 0);
        return rank >= group.start && rank <= group.end;
      });
      if (!rows.length) return "";
      const tier = rows[0].tier || {};
      return `<div class="why-group" data-tier="${escapeHtml(tier.id || group.id)}">
        <div class="why-group__head">
          <h3>${escapeHtml(tier.label || group.id)}</h3>
          <p class="why-group__blurb">${escapeHtml(tier.blurb || "")}</p>
        </div>
        ${rows
          .map((card) => {
            const active = state.sortKey === card.key ? " is-active" : "";
            const valeRank = card.rank ? `${ordinal(card.rank)}\u00a0/\u00a0${card.of}` : "—";
            const open = state.openTrends.has(card.key);
            return `<div class="why-item${open ? " is-open" : ""}" data-trend-item="${escapeHtml(card.key)}">
            <button type="button" class="why-row${active}" data-sort-key="${escapeHtml(card.key)}" title="Open the full breakdown — every game and every player">
              <span class="why-row__num">#${card.importance}</span>
              <div>
                <p class="why-row__name">${escapeHtml(card.label)}</p>
                <span class="why-row__strength">${escapeHtml(card.strength || "")} · r=${card.r}</span>
              </div>
              <p class="why-row__why">${escapeHtml(card.why || card.hint || "")}</p>
              <span class="why-row__figures">
                ${figureHtml("Port Vale", formatWithUnit(card, card.value), { extraClass: "why-fig--vale", tone: tone3(card, card.value) || barTone(card.above_top7) })}
                ${figureHtml("League rank", valeRank, { tone: rankTone(card.rank, card.of) })}
                ${figureHtml("Top 7 avg", formatWithUnit(card, card.top7_avg))}
                ${figureHtml("League avg", formatWithUnit(card, card.league_avg))}
              </span>
            </button>
            <button type="button" class="why-toggle" data-trend-toggle="${escapeHtml(card.key)}" aria-expanded="${open}" aria-label="Show ${escapeHtml(card.label)} trend over our last games" title="Trend over our last games">
              <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
            <div class="why-trend" data-trend-panel="${escapeHtml(card.key)}"${open ? "" : " hidden"}></div>
            </div>`;
          })
          .join("")}
      </div>`;
    })
    .join("");

  els.whyList.querySelectorAll("[data-sort-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      void openDetail(btn.dataset.sortKey);
    });
  });
  els.whyList.querySelectorAll("[data-trend-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      void toggleTrend(btn.dataset.trendToggle);
    });
  });
  for (const key of state.openTrends) void renderTrend(key);
}

function bindSortHeaders(cols) {
  els.tableHead.querySelectorAll("th[data-sort-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const col = cols.find((item) => item.key === th.dataset.sortKey);
      if (!col) return;
      cycleSort(col);
      render();
    });
  });
}

function tableCells(row, cols, ranges, { pinned = false } = {}) {
  return cols
    .map((col) => {
      if (col.fmt === "club") {
        const pin = pinned ? ` <span class="pin-tag">pinned</span>` : "";
        return `<td class="club">${escapeHtml(row.club)}${pin}</td>`;
      }
      const raw = row[col.key];
      const text = formatValue(raw, col.fmt, col.digits ?? (col.fmt === "int" ? 0 : 2));
      const rank = col.showRank ? row.stat_ranks?.[col.key] : null;
      const rankHtml = rank ? `<span class="stat-rank">${ordinal(rank)}</span>` : "";
      if (col.heat === false || raw == null) {
        return `<td>${text}${rankHtml}</td>`;
      }
      const range = ranges[col.key];
      const colRank = rank || rankInColumn(raw, range, col.higherBetter !== false);
      const bg = heatColor(colRank, range?.values?.length || 0);
      return `<td class="heat-cell" style="background:${bg}">${text}${rankHtml}</td>`;
    })
    .join("");
}

function pinHeaderHeight() {
  const headRow = els.tableHead?.querySelector("tr:first-child");
  const height = headRow ? Math.ceil(headRow.getBoundingClientRect().height) : 44;
  document.documentElement.style.setProperty("--win-drivers-head-h", `${height}px`);
}

function renderTable() {
  const cols = columns();
  const rows = sortedRows(state.table?.rows || [], cols);
  const averages = state.table?.averages || {};
  const heatCols = cols.filter((col) => col.heat !== false && col.fmt !== "club");
  const ranges = Object.fromEntries(
    heatCols.map((col) => {
      const values = rows.map((row) => Number(row[col.key])).filter((n) => Number.isFinite(n));
      return [col.key, { values }];
    }),
  );

  const header = `<tr>${cols
    .map((col) => {
      const clubClass = col.fmt === "club" ? " club" : "";
      const sorted = state.sortKey === col.key ? ` is-sorted is-sorted--${state.sortDir}` : "";
      const title = escapeHtml(col.title || `${col.label} — click to sort ascending or descending`);
      return `<th class="sortable${clubClass}${sorted}" data-sort-key="${escapeHtml(col.key)}" title="${title}">${escapeHtml(
        col.label,
      )}${sortIndicator(col.key)}</th>`;
    })
    .join("")}</tr>`;

  const focus = rows.find((row) => row.focus);
  const pin = focus
    ? `<tr class="focus focus--pinned">${tableCells(focus, cols, ranges, { pinned: true })}</tr>`
    : "";

  els.tableHead.innerHTML = `${header}${pin}`;
  bindSortHeaders(cols);

  if (!rows.length) {
    els.tableBody.innerHTML = `<tr><td colspan="${cols.length}">No league table yet for this season.</td></tr>`;
    els.tableFoot.innerHTML = "";
    return;
  }

  els.tableBody.innerHTML = rows
    .map((row) => `<tr class="${row.focus ? "focus focus--place" : ""}">${tableCells(row, cols, ranges)}</tr>`)
    .join("");

  els.tableFoot.innerHTML = `<tr>${cols
    .map((col) => {
      if (col.fmt === "club") return `<td class="club">League avg</td>`;
      if (col.key === "position") return `<td></td>`;
      return `<td>${formatValue(averages[col.key], col.fmt, col.digits ?? 2)}</td>`;
    })
    .join("")}</tr>`;

  pinHeaderHeight();
  requestAnimationFrame(pinHeaderHeight);
}

function render() {
  const table = state.table;
  if (els.tableHint) {
    const n = table?.team_seasons || 0;
    const seasons = (table?.history_seasons || []).map((item) => item.label).join(", ");
    els.tableHint.textContent = table?.method
      ? `${table.method} ${n} team-seasons${seasons ? ` (${seasons})` : ""}.`
      : "";
  }
  if (els.pageSubtitle && table?.season_label) {
    els.pageSubtitle.textContent = `League Two ${table.season_label} — 15 Impect stats that track winning, and where Port Vale sit on each.`;
  }
  if (els.lastUpdated && table?.generated_at) {
    const stamp = new Date(table.generated_at);
    els.lastUpdated.textContent = Number.isNaN(stamp.getTime())
      ? "Updated"
      : `Updated ${stamp.toLocaleString()}`;
  }
  renderStory();
  renderWhyList();
  renderTable();
}

/* ---------- Stat breakdown (click a row) ---------- */

const RESULT_LABEL = { W: "Won", D: "Drew", L: "Lost" };
const PER90_MIN_MINUTES = 90;
const RATE_MIN_CONTESTS = 5;

function shortClub(name, maxChars = 12) {
  const clean = String(name || "")
    .replace(/^FC\s+/i, "")
    .replace(/\s+(FC|AFC)$/i, "")
    .trim();
  return clean.length > maxChars ? `${clean.slice(0, maxChars - 1)}…` : clean;
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function isGood(stat, value, bar) {
  if (value == null || bar == null) return null;
  return stat.higher_better !== false ? Number(value) >= Number(bar) : Number(value) <= Number(bar);
}

function toneClass(good) {
  if (good == null) return "";
  return good ? "is-good" : "is-bad";
}

function mean(values) {
  const nums = values.filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

function statFmt(stat, value) {
  return formatValue(value, stat.fmt, stat.digits ?? 2);
}

function signedDelta(stat, value) {
  if (value == null) return "—";
  const text = formatValue(value, "signed", stat.digits ?? 2);
  return stat.fmt === "pct" ? `${text} pts` : text;
}

function orderedStatKeys() {
  return [...(state.table?.stats || [])]
    .sort((a, b) => Number(a.rank || 0) - Number(b.rank || 0))
    .map((item) => item.key);
}

async function ensureBreakdown() {
  const iid = state.iterationId;
  if (state.breakdown && state.breakdownFor === iid) return state.breakdown;
  if (state.breakdownPromise && state.breakdownFor === iid) return state.breakdownPromise;
  state.breakdownFor = iid;
  state.breakdown = null;
  const promise = api(`/api/win-drivers/breakdown?iteration_id=${iid}`).then((data) => {
    if (state.breakdownFor === iid) state.breakdown = data;
    return data;
  });
  state.breakdownPromise = promise;
  try {
    return await promise;
  } finally {
    if (state.breakdownPromise === promise) state.breakdownPromise = null;
  }
}

function detailHeadHtml(stat) {
  const rank = stat.rank ?? stat.importance;
  const tier = (state.table?.stats || []).find((item) => item.key === stat.key)?.tier;
  const total = (state.table?.stats || []).length || 15;
  return `<header class="detail__head">
    <div class="detail__nav">
      <button type="button" class="detail__navbtn" data-detail-step="-1" aria-label="Previous stat" title="Previous stat (←)">‹</button>
      <button type="button" class="detail__navbtn" data-detail-step="1" aria-label="Next stat" title="Next stat (→)">›</button>
    </div>
    <div class="detail__titles">
      <p class="detail__kicker">#${escapeHtml(rank)} of ${total}${tier?.label ? ` · ${escapeHtml(tier.label)}` : ""}</p>
      <h2 class="detail__title" id="detailTitle">${escapeHtml(stat.label)}</h2>
      <p class="detail__strength">${escapeHtml(stat.strength || "")} link to winning · r=${escapeHtml(stat.r)}${stat.higher_better === false ? " · lower is better" : ""}</p>
      <p class="detail__why">${escapeHtml(stat.why || stat.hint || "")}</p>
    </div>
    <button type="button" class="detail__close" data-detail-close aria-label="Back to all stats" title="Back to all stats (Esc)">×</button>
  </header>`;
}

function gameTag(match) {
  if (!match) return "";
  return `<span class="why-fig__sub">${match.venue === "H" ? "v" : "@"} ${escapeHtml(shortClub(match.opponent))} · ${escapeHtml(formatDate(match.date))}</span>`;
}

function summaryHtml(stat, played) {
  const key = stat.key;
  const hb = stat.higher_better !== false;
  const last5 = mean(played.slice(-5).map((m) => m.values[key]));
  let best = null;
  let worst = null;
  for (const match of played) {
    const v = Number(match.values[key]);
    if (!best || (hb ? v > best.v : v < best.v)) best = { v, match };
    if (!worst || (hb ? v < worst.v : v > worst.v)) worst = { v, match };
  }
  const atBar = stat.top7_avg == null ? null : played.filter((m) => isGood(stat, m.values[key], stat.top7_avg)).length;
  const rankText = stat.league_rank ? `${ordinal(stat.league_rank)}\u00a0/\u00a0${stat.of}` : "—";
  const atShare = atBar == null || !played.length ? null : atBar / played.length;
  const atTone = atShare == null ? "" : atShare >= 0.5 ? "is-good" : atShare >= 0.3 ? "is-mid" : "is-bad";
  return `<section class="detail__section">
    <div class="detail__figs">
      ${figureHtml("Port Vale · season", formatWithUnit(stat, stat.season_value), {
        extraClass: "why-fig--vale",
        tone: tone3(stat, stat.season_value),
      })}
      ${figureHtml("League rank", rankText, { tone: rankTone(stat.league_rank, stat.of) })}
      ${figureHtml("Top 7 avg", formatWithUnit(stat, stat.top7_avg))}
      ${figureHtml("League avg", formatWithUnit(stat, stat.league_avg))}
      ${figureHtml("Last 5 games", formatWithUnit(stat, last5), { tone: tone3(stat, last5) })}
      ${figureHtml("Best game", best ? `${statFmt(stat, best.v)}${gameTag(best.match)}` : "—", { tone: best ? tone3(stat, best.v) : "" })}
      ${figureHtml("Worst game", worst ? `${statFmt(stat, worst.v)}${gameTag(worst.match)}` : "—", { tone: worst ? tone3(stat, worst.v) : "" })}
      ${figureHtml("Games at top-7 level", atBar == null ? "—" : `${atBar} / ${played.length}`, { tone: atTone })}
    </div>
    <p class="detail__key"><span class="key key--good">Green</span> at or above the top-7 average · <span class="key key--mid">Amber</span> between league average and top 7 · <span class="key key--bad">Red</span> below league average</p>
  </section>`;
}

function resultSplitHtml(stat, played) {
  const key = stat.key;
  const groups = ["W", "D", "L"].map((result) => {
    const rows = played.filter((m) => m.result === result);
    return { result, n: rows.length, avg: mean(rows.map((m) => m.values[key])) };
  });
  const oppAvg = mean(played.map((m) => m.opp_values?.[key]));
  const oppCard =
    stat.player_mode === "xgd"
      ? ""
      : `<div class="split-card split-card--opp">
          <span class="split-card__label">Opponents v us · avg</span>
          <strong class="split-card__value">${formatWithUnit(stat, oppAvg)}</strong>
        </div>`;
  return `<section class="detail__section">
    <h3 class="detail__h">When we win, draw and lose</h3>
    <p class="detail__sub">Our average on this stat, split by result. If it is a real driver, the number should move with the result.</p>
    <div class="detail__split">
      ${groups
        .map(
          (g) => `<div class="split-card split-card--${g.result}">
            <span class="split-card__label">${RESULT_LABEL[g.result]} · ${g.n} game${g.n === 1 ? "" : "s"}</span>
            <strong class="split-card__value ${g.n ? tone3(stat, g.avg) : ""}">${g.n ? formatWithUnit(stat, g.avg) : "—"}</strong>
          </div>`,
        )
        .join("")}
      ${oppCard}
    </div>
  </section>`;
}

function niceFloor(value) {
  if (value <= 0) return 0;
  const step = 10 ** Math.floor(Math.log10(value)) / 2;
  return Math.floor(value / step) * step;
}

function chartHtml(stat, matches, width) {
  const key = stat.key;
  if (!matches.length) return "";
  const showOpp = stat.player_mode !== "xgd";
  const n = matches.length;
  const W = Math.max(n * 96 + 170, Math.floor(width || 0), 720);
  const H = 360;
  const padL = 70;
  const padR = 96;
  const padT = 30;
  const padB = 74;
  const vals = [];
  for (const m of matches) {
    if (m.values?.[key] != null) vals.push(Number(m.values[key]));
    if (showOpp && m.opp_values?.[key] != null) vals.push(Number(m.opp_values[key]));
  }
  for (const v of [stat.top7_avg, stat.league_avg]) if (v != null) vals.push(Number(v));
  if (!vals.length) return "";
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  let rawMin = Math.min(0, lo);
  let rawMax = Math.max(0, hi);
  if (lo > 0 && lo > hi * 0.5) rawMin = niceFloor(lo * 0.85);
  const span = rawMax - rawMin || 1;
  rawMax += span * 0.1;
  if (rawMin < 0) rawMin -= span * 0.1;
  const { min, max, ticks: tickValues } = niceTicks(rawMin, rawMax, 4);
  const plotH = H - padT - padB;
  const y = (v) => padT + ((max - v) / (max - min)) * plotH;
  const baseVal = min > 0 ? min : 0;
  const y0 = y(baseVal);
  const slot = (W - padL - padR) / n;
  const barW = Math.min(44, slot * (showOpp ? 0.42 : 0.55));
  const oppW = Math.min(16, slot * 0.16);

  const tickDigits = stat.fmt === "pct" ? 0 : Math.max(0, Math.min(2, stat.digits ?? 2));
  const ticks = tickValues.map(
    (v) => `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" class="ch-grid"/>
      <text x="${padL - 10}" y="${y(v) + 5}" class="ch-tick" text-anchor="end">${escapeHtml(formatValue(v, stat.fmt === "signed" ? "signed" : "dec", tickDigits))}${stat.fmt === "pct" ? "%" : ""}</text>`,
  );
  const nameChars = Math.max(10, Math.floor(slot / 9));

  const refY = {
    top7: stat.top7_avg == null ? null : y(Number(stat.top7_avg)),
    league: stat.league_avg == null ? null : y(Number(stat.league_avg)),
  };
  const labelY = { ...refY };
  if (labelY.top7 != null && labelY.league != null && Math.abs(labelY.top7 - labelY.league) < 36) {
    const mid = (labelY.top7 + labelY.league) / 2;
    const top7Above = labelY.top7 <= labelY.league;
    labelY.top7 = mid + (top7Above ? -18 : 18);
    labelY.league = mid + (top7Above ? 18 : -18);
  }
  const refLine = (value, cls, label, id) => {
    if (value == null) return "";
    const yy = refY[id];
    return `<line x1="${padL}" x2="${W - padR}" y1="${yy}" y2="${yy}" class="${cls}"/>
      <text x="${W - padR + 8}" y="${labelY[id] - 2}" class="ch-reflabel ${cls}-label">${escapeHtml(label)}</text>
      <text x="${W - padR + 8}" y="${labelY[id] + 14}" class="ch-reflabel ${cls}-label">${escapeHtml(statFmt(stat, value))}</text>`;
  };

  const bars = matches
    .map((m, i) => {
      const cx = padL + slot * i + slot / 2;
      const v = m.values?.[key];
      const resultCls = `ch-result--${m.result}`;
      const labels = `<text x="${cx}" y="${H - padB + 24}" class="ch-xlabel" text-anchor="middle">${escapeHtml(shortClub(m.opponent, nameChars))}</text>
        <text x="${cx}" y="${H - padB + 46}" class="ch-xsub ${resultCls}" text-anchor="middle">${m.result} ${m.scored}-${m.conceded} ${m.venue}</text>`;
      if (v == null) {
        return `<g><text x="${cx}" y="${y0 - 8}" class="ch-nodata" text-anchor="middle">no data</text>${labels}</g>`;
      }
      const yv = y(Number(v));
      const top = Math.min(yv, y0);
      const h = Math.max(1.5, Math.abs(y0 - yv));
      const tone = tone3(stat, v);
      const fill = tone === "is-good" ? "ch-bar--good" : tone === "is-bad" ? "ch-bar--bad" : "ch-bar--mid";
      const vx = showOpp ? cx - oppW / 2 - 1 : cx;
      let opp = "";
      const ov = m.opp_values?.[key];
      if (showOpp && ov != null) {
        const yo = y(Number(ov));
        opp = `<rect x="${cx + barW / 2 - oppW / 2 + 1}" y="${Math.min(yo, y0)}" width="${oppW}" height="${Math.max(1.5, Math.abs(y0 - yo))}" class="ch-bar--opp" rx="2"><title>${escapeHtml(m.opponent)}: ${escapeHtml(statFmt(stat, ov))}</title></rect>`;
      }
      const valueY = Number(v) >= baseVal ? top - 8 : top + h + 19;
      return `<g>
        <rect x="${vx - barW / 2}" y="${top}" width="${barW}" height="${h}" class="${fill}" rx="3">
          <title>${escapeHtml(formatDate(m.date))} ${m.venue === "H" ? "v" : "@"} ${escapeHtml(m.opponent)} — Port Vale ${escapeHtml(statFmt(stat, v))}</title>
        </rect>
        ${opp}
        <text x="${vx}" y="${valueY}" class="ch-val ${tone}" text-anchor="middle">${escapeHtml(statFmt(stat, v))}</text>
        ${labels}
      </g>`;
    })
    .join("");

  return `<section class="detail__section">
    <div class="detail__h-row">
      <h3 class="detail__h">Game by game</h3>
      <div class="ch-legend">
        <span><i class="lg lg--good"></i>Port Vale (green top-7 level · amber mid · red below avg)</span>
        ${showOpp ? `<span><i class="lg lg--opp"></i>Opponent</span>` : ""}
        <span><i class="lg lg--top7"></i>Top 7 avg</span>
        <span><i class="lg lg--league"></i>League avg</span>
      </div>
    </div>
    <div class="chart-wrap">
      <svg class="chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${escapeHtml(stat.label)} by game">
        ${ticks.join("")}
        ${min < 0 ? `<line x1="${padL}" x2="${W - padR}" y1="${y(0)}" y2="${y(0)}" class="ch-zero"/>` : ""}
        ${refLine(stat.league_avg, "ch-league", "League", "league")}
        ${refLine(stat.top7_avg, "ch-top7", "Top 7", "top7")}
        ${bars}
      </svg>
    </div>
  </section>`;
}

function topPlayerInMatch(stat, players, matchId) {
  const mode = stat.player_mode;
  if (mode === "on_pitch") return null;
  const valueKey = mode === "xgd" ? "xg_for" : stat.key;
  let best = null;
  for (const p of players) {
    const cell = p.by_match?.[String(matchId)]?.values?.[valueKey];
    if (cell == null) continue;
    const score = mode === "rate" ? Number(cell[0]) : Number(cell);
    if (!Number.isFinite(score) || score <= 0) continue;
    if (!best || score > best.score) best = { p, score, cell };
  }
  if (!best) return null;
  const surname = String(best.p.name || "").split(" ").slice(-1)[0];
  const text =
    mode === "rate"
      ? `${Math.round(best.cell[0])}/${Math.round(best.cell[1])}`
      : formatValue(best.cell, stat.fmt === "pct" ? "dec" : stat.fmt === "signed" ? "dec" : stat.fmt, stat.digits ?? 2);
  return `${escapeHtml(surname)} <span class="muted">${escapeHtml(text)}</span>`;
}

function matchTableHtml(stat, matches, players) {
  const key = stat.key;
  const xgd = stat.player_mode === "xgd";
  const hasSplit = xgd && matches.some((m) => m.values?.xg_for != null);
  const showTop = stat.player_mode !== "on_pitch";
  const topLabel = stat.player_mode === "rate" ? "Most won" : xgd ? "Most xG" : "Top player";
  const head = `<tr>
    <th>Date</th><th class="left">Opponent</th><th>H/A</th><th>Result</th>
    <th>Port Vale</th>
    ${hasSplit ? "<th>Our xG</th><th>Their xG</th>" : xgd ? "" : "<th>Opponent</th><th>Edge</th>"}
    <th>vs Top 7</th>
    ${showTop ? `<th class="left">${topLabel}</th>` : ""}
  </tr>`;
  const body = [...matches]
    .reverse()
    .map((m) => {
      const v = m.values?.[key];
      const ov = m.opp_values?.[key];
      const vsTop = v != null && stat.top7_avg != null ? Number(v) - Number(stat.top7_avg) : null;
      const edge = v != null && ov != null ? Number(v) - Number(ov) : null;
      const edgeTone = edge == null ? "" : toneVs(stat, v, ov);
      const middle = hasSplit
        ? `<td class="num">${formatValue(m.values.xg_for, "dec", 2)}</td><td class="num">${formatValue(m.values.xg_against, "dec", 2)}</td>`
        : xgd
          ? ""
          : `<td class="num">${statFmt(stat, ov)}</td><td class="num ${edgeTone}">${signedDelta(stat, edge)}</td>`;
      return `<tr>
        <td>${escapeHtml(formatDate(m.date))}</td>
        <td class="left">${escapeHtml(m.opponent)}</td>
        <td>${m.venue}</td>
        <td><span class="res res--${m.result}">${m.result}</span> ${m.scored}–${m.conceded}</td>
        <td class="num strong ${tone3(stat, v)}">${statFmt(stat, v)}</td>
        ${middle}
        <td class="num ${tone3(stat, v)}">${signedDelta(stat, vsTop)}</td>
        ${showTop ? `<td class="left">${topPlayerInMatch(stat, players, m.match_id) || '<span class="muted">—</span>'}</td>` : ""}
      </tr>`;
    })
    .join("");
  return `<section class="detail__section">
    <h3 class="detail__h">Every game</h3>
    <p class="detail__sub">Newest first. Green = top-7 level, amber = between league average and top 7, red = below league average. Edge: amber when within 10% of the opponent.</p>
    <div class="detail-table-wrap"><table class="detail-table"><thead>${head}</thead><tbody>${body}</tbody></table></div>
  </section>`;
}

function per90Ok(p) {
  return Number(p.minutes || 0) >= PER90_MIN_MINUTES;
}

function playerColumns(stat, ctx) {
  const teamTotal = ctx?.teamTotal;
  const mode = stat.player_mode;
  const key = stat.key;
  const digits = stat.digits ?? 2;
  const dec = (v, d = digits) => formatValue(v, "dec", d);
  const base = [
    { id: "name", label: "Player", left: true, get: (p) => p.name, html: (p) => escapeHtml(p.name), text: true },
    { id: "pos", label: "Pos", get: (p) => p.position_short, html: (p) => escapeHtml(p.position_short || "—"), text: true },
    { id: "apps", label: "Apps", get: (p) => p.apps, html: (p) => String(p.apps) },
    { id: "mins", label: "Mins", get: (p) => p.minutes, html: (p) => String(Math.round(p.minutes)) },
  ];
  if (mode === "rate") {
    return [
      ...base,
      { id: "won", label: "Won", get: (p) => p.counts?.[key]?.[0], html: (p) => String(Math.round(p.counts?.[key]?.[0] || 0)) },
      { id: "contested", label: "Contested", get: (p) => p.counts?.[key]?.[1], html: (p) => String(Math.round(p.counts?.[key]?.[1] || 0)) },
      {
        id: "pct",
        label: "Win %",
        primary: true,
        get: (p) => ((p.counts?.[key]?.[1] || 0) >= RATE_MIN_CONTESTS ? p.totals?.[key] : null),
        html: (p) => formatValue(p.totals?.[key], "pct", 1),
        tone: (p) =>
          p.totals?.[key] == null || (p.counts?.[key]?.[1] || 0) < RATE_MIN_CONTESTS
            ? null
            : toneVs(stat, p.totals[key], stat.season_value, 0.06),
      },
      {
        id: "c90",
        label: "Contested /90",
        get: (p) => (per90Ok(p) ? ((p.counts?.[key]?.[1] || 0) * 90) / p.minutes : null),
        html: (p) => (per90Ok(p) ? dec(((p.counts?.[key]?.[1] || 0) * 90) / p.minutes, 1) : "—"),
      },
    ];
  }
  if (mode === "xgd") {
    return [
      ...base,
      { id: "xg", label: "xG created", primary: true, get: (p) => p.totals?.xg_for, html: (p) => dec(p.totals?.xg_for, 2) },
      { id: "xg90", label: "xG /90", get: (p) => (per90Ok(p) ? p.per90?.xg_for : null), html: (p) => (per90Ok(p) ? dec(p.per90?.xg_for, 2) : "—") },
      {
        id: "xga90",
        label: "xGA on pitch /90",
        lowerBetter: true,
        get: (p) => (per90Ok(p) ? p.per90?.xg_against : null),
        html: (p) => (per90Ok(p) ? dec(p.per90?.xg_against, 2) : "—"),
      },
    ];
  }
  if (mode === "on_pitch") {
    const teamAvg = ctx?.teamPer90 ?? stat.season_value;
    return [
      ...base,
      { id: "total", label: "On pitch total", get: (p) => p.totals?.[key], html: (p) => dec(p.totals?.[key]) },
      {
        id: "p90",
        label: "On pitch /90",
        primary: true,
        lowerBetter: stat.higher_better === false,
        get: (p) => (per90Ok(p) ? p.per90?.[key] : null),
        html: (p) => (per90Ok(p) ? dec(p.per90?.[key]) : "—"),
        tone: (p) => (per90Ok(p) ? toneVs(stat, p.per90?.[key], teamAvg) : null),
      },
      {
        id: "vsteam",
        label: `vs team /90 (${dec(teamAvg)})`,
        get: (p) => (per90Ok(p) && teamAvg != null ? p.per90?.[key] - teamAvg : null),
        html: (p) => (per90Ok(p) && teamAvg != null ? signedDelta(stat, p.per90?.[key] - teamAvg) : "—"),
        tone: (p) => (per90Ok(p) ? toneVs(stat, p.per90?.[key], teamAvg) : null),
      },
    ];
  }
  const canShare = teamTotal != null && teamTotal > 0;
  return [
    ...base,
    { id: "total", label: "Total", primary: true, get: (p) => p.totals?.[key], html: (p) => dec(p.totals?.[key]) },
    { id: "p90", label: "Per 90", get: (p) => (per90Ok(p) ? p.per90?.[key] : null), html: (p) => (per90Ok(p) ? dec(p.per90?.[key]) : "—") },
    {
      id: "pergame",
      label: "Per app",
      get: (p) => (p.totals?.[key] != null && p.apps ? p.totals[key] / p.apps : null),
      html: (p) => (p.totals?.[key] != null && p.apps ? dec(p.totals[key] / p.apps) : "—"),
    },
    ...(canShare
      ? [
          {
            id: "share",
            label: "Share of team",
            get: (p) => (p.totals?.[key] != null ? p.totals[key] / teamTotal : null),
            html: (p) => {
              if (p.totals?.[key] == null) return "—";
              const share = Math.max(0, (100 * p.totals[key]) / teamTotal);
              return `<span class="share"><span class="share__bar" style="width:${Math.min(100, share).toFixed(1)}%"></span><span class="share__text">${share.toFixed(0)}%</span></span>`;
            },
          },
        ]
      : []),
  ];
}

const PLAYER_NOTES = {
  own: "Each player's own actions. Player totals add up to the team number. Per 90 shown from 90 minutes played.",
  on_pitch:
    "Impect splits this by what the team conceded while each player was on the pitch — a unit number, not individual blame. Compare his per 90 with the team's own per-90 rate (same minutes basis, stoppage time included).",
  rate: "Duels each player contested and won across the season. Win % compared with the team's season rate (players under 5 contests sort to the bottom).",
  xgd: "xG difference is a team number. Here: the xG each player created himself, and the xG the team conceded while he was on the pitch (per 90, from 90 minutes).",
};

function sortPlayers(players, cols) {
  const primary = cols.find((c) => c.primary) || cols[cols.length - 1];
  const sortKey = state.playerSort.key || primary.id;
  const col = cols.find((c) => c.id === sortKey) || primary;
  const defaultDir = col.text ? "asc" : col.lowerBetter ? "asc" : "desc";
  const dir = state.playerSort.key ? state.playerSort.dir : defaultDir;
  const sorted = [...players].sort((a, b) => {
    const av = col.get(a);
    const bv = col.get(b);
    if (av == null && bv == null) return Number(b.minutes) - Number(a.minutes);
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = col.text ? String(av).localeCompare(String(bv)) : Number(av) - Number(bv);
    if (cmp === 0) return Number(b.minutes) - Number(a.minutes);
    return dir === "asc" ? cmp : -cmp;
  });
  return { sorted, sortKey: col.id, dir };
}

function playerTableHtml(stat, players, ctx) {
  if (!players.length) {
    return `<section class="detail__section"><h3 class="detail__h">Players</h3><p class="detail__sub">No player data for this season yet.</p></section>`;
  }
  const cols = playerColumns(stat, ctx);
  const { sorted, sortKey, dir } = sortPlayers(players, cols);
  const head = `<tr>${cols
    .map((c) => {
      const active = c.id === sortKey ? ` is-sorted` : "";
      const arrow = c.id === sortKey ? (dir === "asc" ? " ▲" : " ▼") : "";
      return `<th class="sortable${c.left ? " left" : ""}${active}" data-psort="${c.id}">${escapeHtml(c.label)}${arrow}</th>`;
    })
    .join("")}</tr>`;
  const body = sorted
    .map((p) => {
      const low = per90Ok(p) ? "" : " is-low";
      return `<tr class="${low}">${cols
        .map((c) => {
          const tone = c.tone ? c.tone(p) || "" : "";
          return `<td class="${c.left ? "left" : "num"} ${c.primary ? "strong" : ""} ${tone}">${c.html(p)}</td>`;
        })
        .join("")}</tr>`;
    })
    .join("");
  return `<section class="detail__section">
    <h3 class="detail__h">Players — season</h3>
    <p class="detail__sub">${escapeHtml(PLAYER_NOTES[stat.player_mode] || PLAYER_NOTES.own)} Click a header to sort.</p>
    <div class="detail-table-wrap"><table class="detail-table detail-table--players"><thead>${head}</thead><tbody>${body}</tbody></table></div>
  </section>`;
}

function gridCell(stat, player, matchId) {
  const entry = player.by_match?.[String(matchId)];
  if (!entry) return { text: "", score: null, minutes: 0 };
  const mode = stat.player_mode;
  const valueKey = mode === "xgd" ? "xg_for" : stat.key;
  const cell = entry.values?.[valueKey];
  if (cell == null) return { text: mode === "rate" ? "0/0" : "0", score: mode === "rate" ? null : 0, minutes: entry.minutes };
  if (mode === "rate") {
    const pct = cell[1] > 0 ? (100 * cell[0]) / cell[1] : null;
    return { text: `${Math.round(cell[0])}/${Math.round(cell[1])}`, score: pct, minutes: entry.minutes };
  }
  return { text: formatValue(cell, "dec", stat.digits ?? 2), score: Number(cell), minutes: entry.minutes };
}

function gridHeat(score, min, max, higherBetter) {
  if (score == null || !Number.isFinite(score) || max === min) return "";
  const t = (score - min) / (max - min);
  const s = higherBetter ? t : 1 - t;
  return `rgba(34, 197, 94, ${(0.04 + 0.62 * s ** 1.4).toFixed(3)})`;
}

function playerGridHtml(stat, players, matches, ctx) {
  if (!players.length || !matches.length) return "";
  const cols = playerColumns(stat, ctx);
  const { sorted } = sortPlayers(players, cols);
  const mode = stat.player_mode;
  const higherBetter = mode === "xgd" || mode === "rate" ? true : stat.higher_better !== false;
  const scores = [];
  for (const p of sorted) for (const m of matches) {
    const c = gridCell(stat, p, m.match_id);
    if (c.score != null && c.minutes > 0) scores.push(c.score);
  }
  const min = scores.length ? Math.min(...scores) : 0;
  const max = scores.length ? Math.max(...scores) : 0;
  const totalLabel = mode === "rate" ? "Season %" : mode === "on_pitch" ? "On pitch total" : mode === "xgd" ? "xG total" : "Total";
  const head = `<tr><th class="left sticky-col">Player</th>${matches
    .map(
      (m) => `<th title="${escapeHtml(formatDate(m.date))} ${m.venue === "H" ? "v" : "@"} ${escapeHtml(m.opponent)}">
        <span class="grid-opp">${escapeHtml(shortClub(m.opponent))}</span>
        <span class="grid-res res--${m.result}">${m.result} ${m.scored}-${m.conceded}</span>
      </th>`,
    )
    .join("")}<th>${totalLabel}</th></tr>`;
  const valueKey = mode === "xgd" ? "xg_for" : stat.key;
  const body = sorted
    .map((p) => {
      const cells = matches
        .map((m) => {
          const c = gridCell(stat, p, m.match_id);
          if (!c.minutes) return `<td class="grid-empty">·</td>`;
          const bg = gridHeat(c.score, min, max, higherBetter);
          return `<td class="num" style="${bg ? `background:${bg}` : ""}" title="${escapeHtml(p.name)} — ${Math.round(c.minutes)} mins">${escapeHtml(c.text)}<span class="grid-min">${Math.round(c.minutes)}'</span></td>`;
        })
        .join("");
      const total = mode === "rate" ? formatValue(p.totals?.[valueKey], "pct", 1) : formatValue(p.totals?.[valueKey], "dec", stat.digits ?? 2);
      return `<tr><td class="left sticky-col">${escapeHtml(p.name)} <span class="muted">${escapeHtml(p.position_short || "")}</span></td>${cells}<td class="num strong">${total}</td></tr>`;
    })
    .join("");
  const what =
    mode === "on_pitch"
      ? "What the team conceded while he was on."
      : mode === "rate"
        ? "Won / contested."
        : mode === "xgd"
          ? "xG he created himself."
          : "His own number in that game.";
  return `<section class="detail__section">
    <h3 class="detail__h">Players — game by game</h3>
    <p class="detail__sub">${what} Small figure = minutes played. Blank = did not play.</p>
    <div class="detail-table-wrap"><table class="detail-table detail-grid"><thead>${head}</thead><tbody>${body}</tbody></table></div>
  </section>`;
}

function teamPer90(key, played, players) {
  let total = 0;
  let minutes = 0;
  for (const m of played) {
    const mins = Math.max(0, ...players.map((p) => Number(p.by_match?.[String(m.match_id)]?.minutes || 0)));
    if (!mins) continue;
    total += Number(m.values[key]);
    minutes += mins;
  }
  return minutes ? (total * 90) / minutes : null;
}

function renderDetail() {
  const key = state.detailKey;
  if (!key || !els.detailPanel) return;
  const data = state.breakdown;
  const stat = (data?.stats || []).find((item) => item.key === key);
  const card = (state.table?.focus?.cards || []).find((item) => item.key === key);
  if (!stat) {
    els.detailPanel.innerHTML = `${card ? detailHeadHtml(card) : ""}<p class="detail__loading">${escapeHtml(
      data?.message || "No game-by-game breakdown for this stat yet.",
    )}</p>`;
    bindDetailChrome();
    return;
  }
  const matches = data.matches || [];
  const players = data.players || [];
  const played = matches.filter((m) => m.has_data && m.values?.[key] != null);
  const teamTotal = played.reduce((sum, m) => sum + Number(m.values[key]), 0);
  const ctx = { teamTotal, teamPer90: teamPer90(key, played, players) };
  const scroll = window.scrollY;
  els.detailPanel.innerHTML = [
    detailHeadHtml(stat),
    summaryHtml(stat, played),
    resultSplitHtml(stat, played),
    chartHtml(stat, matches, (els.detailPanel.clientWidth || 0) - 14),
    matchTableHtml(stat, matches, players),
    playerTableHtml(stat, players, ctx),
    playerGridHtml(stat, players, matches, ctx),
  ].join("");
  window.scrollTo(0, scroll);
  bindDetailChrome();
  els.detailPanel.querySelectorAll("th[data-psort]").forEach((th) => {
    th.addEventListener("click", () => {
      const id = th.dataset.psort;
      if (state.playerSort.key === id) {
        state.playerSort.dir = state.playerSort.dir === "asc" ? "desc" : "asc";
      } else {
        const col = playerColumns(stat, ctx).find((c) => c.id === id);
        state.playerSort = { key: id, dir: col?.text || col?.lowerBetter ? "asc" : "desc" };
      }
      renderDetail();
    });
  });
}

function bindDetailChrome() {
  els.detailPanel.querySelectorAll("[data-detail-close]").forEach((btn) => btn.addEventListener("click", closeDetail));
  els.detailPanel.querySelectorAll("[data-detail-step]").forEach((btn) => {
    btn.addEventListener("click", () => stepDetail(Number(btn.dataset.detailStep)));
  });
}

function statUrl(key) {
  return `${location.pathname}${location.search}${key ? `#stat=${encodeURIComponent(key)}` : ""}`;
}

async function openDetail(key, { fromHistory = false } = {}) {
  if (!key || !els.detail) return;
  const switching = state.detailKey !== key;
  if (!state.detailKey) state.listScroll = window.scrollY;
  if (!fromHistory && hashStatKey() !== key) {
    if (state.detailKey) history.replaceState({ stat: key }, "", statUrl(key));
    else {
      history.pushState({ stat: key }, "", statUrl(key));
      state.detailPushed = true;
    }
  }
  state.detailKey = key;
  if (switching) state.playerSort = { key: null, dir: "desc" };
  els.detail.classList.remove("hidden");
  document.body.classList.add("has-detail");
  if (switching) window.scrollTo(0, 0);
  if (state.breakdown && state.breakdownFor === state.iterationId) {
    renderDetail();
    if (switching) window.scrollTo(0, 0);
    return;
  }
  const card = (state.table?.focus?.cards || []).find((item) => item.key === key);
  els.detailPanel.innerHTML = `${card ? detailHeadHtml(card) : ""}<p class="detail__loading">Loading every game and every player…</p>`;
  bindDetailChrome();
  try {
    await ensureBreakdown();
    if (state.detailKey === key) {
      renderDetail();
      if (switching) window.scrollTo(0, 0);
    }
  } catch (error) {
    if (state.detailKey !== key) return;
    const msg = els.detailPanel.querySelector(".detail__loading");
    if (msg) {
      msg.textContent = error.message || "Could not load the breakdown.";
      msg.classList.add("is-error");
    }
  }
}

function hideDetail() {
  if (!state.detailKey) return;
  state.detailKey = null;
  els.detail?.classList.add("hidden");
  document.body.classList.remove("has-detail");
  window.scrollTo(0, state.listScroll || 0);
}

function closeDetail() {
  if (!state.detailKey) return;
  if (state.detailPushed) {
    state.detailPushed = false;
    history.back();
    return;
  }
  history.replaceState(null, "", statUrl(null));
  hideDetail();
}

function stepDetail(delta) {
  const keys = orderedStatKeys();
  if (!keys.length || !state.detailKey) return;
  const index = keys.indexOf(state.detailKey);
  const next = keys[(index + delta + keys.length) % keys.length];
  void openDetail(next);
}

function hashStatKey() {
  const match = /^#stat=([\w-]+)/.exec(location.hash || "");
  return match ? decodeURIComponent(match[1]) : null;
}

els.detail?.querySelector(".detail__crumbs [data-detail-close]")?.addEventListener("click", closeDetail);
function syncDetailToUrl() {
  const linked = hashStatKey();
  if (!linked) {
    state.detailPushed = false;
    hideDetail();
  } else if (linked !== state.detailKey && state.table) {
    void openDetail(linked, { fromHistory: true });
  }
}
window.addEventListener("popstate", syncDetailToUrl);
window.addEventListener("hashchange", syncDetailToUrl);
document.addEventListener("keydown", (event) => {
  if (!state.detailKey) return;
  if (event.key === "Escape") closeDetail();
  else if (event.key === "ArrowRight") stepDetail(1);
  else if (event.key === "ArrowLeft") stepDetail(-1);
});

/* ---------- Row dropdown: trend over our last games ---------- */

function niceTicks(lo, hi, count = 4) {
  let span = hi - lo;
  if (!(span > 0)) span = Math.abs(hi) || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step === min ? min + step : Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = min; v <= max + step / 2; v += step) ticks.push(Number(v.toFixed(6)));
  return { min, max, ticks, step };
}

function trendSlope(values) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null && Number.isFinite(Number(v)));
  if (pts.length < 3) return null;
  const n = pts.length;
  const mx = pts.reduce((s, [x]) => s + x, 0) / n;
  const my = pts.reduce((s, [, y]) => s + Number(y), 0) / n;
  const num = pts.reduce((s, [x, y]) => s + (x - mx) * (Number(y) - my), 0);
  const den = pts.reduce((s, [x]) => s + (x - mx) ** 2, 0);
  return den ? num / den : null;
}

function trendSummaryHtml(stat, values) {
  const slope = trendSlope(values);
  const played = values.filter((v) => v != null);
  const last3 = mean(played.slice(-3));
  const parts = [`Last ${played.length} game${played.length === 1 ? "" : "s"}`];
  if (last3 != null && played.length > 3) parts.push(`last 3 avg <strong>${escapeHtml(statFmt(stat, last3))}</strong>`);
  let tag = "";
  if (slope != null) {
    const scale = Math.max(...played.map((v) => Math.abs(Number(v))), 1e-9);
    const flat = Math.abs(slope) < scale * 0.02;
    const better = stat.higher_better !== false ? slope > 0 : slope < 0;
    const cls = flat ? "is-flat" : better ? "is-good" : "is-bad";
    const word = flat ? "Flat" : better ? "Improving" : "Getting worse";
    const arrow = flat ? "→" : slope > 0 ? "↗" : "↘";
    tag = `<span class="trend-tag ${cls}">${arrow} ${word} <span class="trend-tag__rate">${escapeHtml(formatValue(slope, "signed", stat.digits ?? 2))}${stat.fmt === "pct" ? " pts" : ""} per game</span></span>`;
  }
  return `<div class="why-trend__head"><p class="why-trend__summary">${parts.join(" · ")}</p>${tag}</div>`;
}

function trendChartHtml(stat, matches, W) {
  const key = stat.key;
  const n = matches.length;
  const H = 420;
  const padL = 76;
  const padR = 104;
  const padT = 40;
  const padB = 132;
  const values = matches.map((m) => (m.values?.[key] == null ? null : Number(m.values[key])));
  const nums = values.filter((v) => v != null);
  if (!nums.length) return `<p class="why-trend__msg">No Impect numbers for these games yet.</p>`;
  const refs = [stat.top7_avg, stat.league_avg].filter((v) => v != null).map(Number);
  const lo = Math.min(...nums, ...refs);
  const hi = Math.max(...nums, ...refs);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.12;
  const { min, max, ticks } = niceTicks(lo - pad, hi + pad, 4);
  const plotH = H - padT - padB;
  const y = (v) => padT + ((max - v) / (max - min)) * plotH;
  const slot = (W - padL - padR) / Math.max(1, n);
  const x = (i) => padL + slot * (i + 0.5);
  const tickDigits = stat.fmt === "pct" ? 0 : Math.max(0, Math.min(2, (stat.digits ?? 2)));

  const grid = ticks
    .map(
      (t) => `<line x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}" class="tr-grid"/>
        <text x="${padL - 12}" y="${y(t) + 6}" class="tr-tick" text-anchor="end">${escapeHtml(formatValue(t, stat.fmt === "signed" ? "signed" : "dec", tickDigits))}${stat.fmt === "pct" ? "%" : ""}</text>`,
    )
    .join("");
  const axisBreak = min > 0 ? `<path d="M${padL - 5} ${H - padB - 14} l5 -4 l-5 -4 l5 -4" class="tr-break"/>` : "";

  const refY = {
    top7: stat.top7_avg == null ? null : y(Number(stat.top7_avg)),
    league: stat.league_avg == null ? null : y(Number(stat.league_avg)),
  };
  const labelY = { ...refY };
  if (labelY.top7 != null && labelY.league != null && Math.abs(labelY.top7 - labelY.league) < 40) {
    const mid = (labelY.top7 + labelY.league) / 2;
    const top7Above = labelY.top7 <= labelY.league;
    labelY.top7 = mid + (top7Above ? -20 : 20);
    labelY.league = mid + (top7Above ? 20 : -20);
  }
  const ref = (id, value, cls, label) =>
    value == null
      ? ""
      : `<line x1="${padL}" x2="${W - padR}" y1="${refY[id]}" y2="${refY[id]}" class="${cls}"/>
        <text x="${W - padR + 10}" y="${labelY[id] - 2}" class="tr-reflabel ${cls}-label">${label}</text>
        <text x="${W - padR + 10}" y="${labelY[id] + 15}" class="tr-reflabel ${cls}-label">${escapeHtml(statFmt(stat, value))}</text>`;

  let path = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v == null) {
      pen = false;
      return;
    }
    path += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
    pen = true;
  });

  const labelBelow = (i) => {
    const v = values[i];
    const near = [values[i - 1], values[i + 1]].filter((w) => w != null);
    if (!near.length) return false;
    const belowRoom = y(v) + 34 < H - padB;
    return belowRoom && near.every((w) => w > v);
  };
  const marks = values
    .map((v, i) => {
      if (v == null) return "";
      const cx = x(i);
      const cy = y(v);
      const cls = tone3(stat, v);
      const s = 8;
      const m = matches[i];
      return `<g class="tr-mark ${cls}">
        <title>${escapeHtml(formatDate(m.date))} ${m.venue === "H" ? "v" : "@"} ${escapeHtml(m.opponent)} (${m.result} ${m.scored}-${m.conceded}) — ${escapeHtml(statFmt(stat, v))}</title>
        <circle cx="${cx}" cy="${cy}" r="16" class="tr-hit"/>
        <path d="M${cx - s} ${cy - s} L${cx + s} ${cy + s} M${cx + s} ${cy - s} L${cx - s} ${cy + s}" class="tr-x"/>
        <text x="${cx}" y="${labelBelow(i) ? cy + 30 : cy - 16}" class="tr-val" text-anchor="middle">${escapeHtml(statFmt(stat, v))}</text>
      </g>`;
    })
    .join("");

  const badgeSize = 50;
  const axisY = H - padB;
  const xAxis = matches
    .map((m, i) => {
      const cx = x(i);
      const top = axisY + 12;
      const badge = m.badge_url
        ? `<image href="${escapeHtml(m.badge_url)}" x="${cx - badgeSize / 2}" y="${top}" width="${badgeSize}" height="${badgeSize}" preserveAspectRatio="xMidYMid meet"/>`
        : `<circle cx="${cx}" cy="${top + badgeSize / 2}" r="${badgeSize / 2}" class="tr-badge-fallback"/>
           <text x="${cx}" y="${top + badgeSize / 2 + 6}" class="tr-badge-initials" text-anchor="middle">${escapeHtml(m.initials || "?")}</text>`;
      return `<g>
        <title>${escapeHtml(formatDate(m.date))} ${m.venue === "H" ? "v" : "@"} ${escapeHtml(m.opponent)}</title>
        <line x1="${cx}" x2="${cx}" y1="${axisY}" y2="${axisY + 6}" class="tr-axis"/>
        ${badge}
        <text x="${cx}" y="${top + badgeSize + 24}" class="tr-res tr-res--${m.result}" text-anchor="middle">${m.result} ${m.scored}-${m.conceded}</text>
        <text x="${cx}" y="${top + badgeSize + 44}" class="tr-venue" text-anchor="middle">${m.venue === "H" ? "Home" : "Away"}</text>
      </g>`;
    })
    .join("");

  return `${trendSummaryHtml(stat, values)}
    <svg class="trend-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${escapeHtml(stat.label)} over our last ${n} games">
      ${grid}
      <line x1="${padL}" x2="${padL}" y1="${padT - 6}" y2="${axisY}" class="tr-axis"/>
      <line x1="${padL}" x2="${W - padR}" y1="${axisY}" y2="${axisY}" class="tr-axis"/>
      ${axisBreak}
      ${ref("league", stat.league_avg, "tr-league", "League")}
      ${ref("top7", stat.top7_avg, "tr-top7", "Top 7")}
      <path d="${path}" class="tr-line"/>
      ${marks}
      ${xAxis}
    </svg>`;
}

function trendPanel(key) {
  return els.whyList?.querySelector(`[data-trend-panel="${CSS.escape(key)}"]`) || null;
}

async function renderTrend(key) {
  let panel = trendPanel(key);
  if (!panel) return;
  if (!(state.breakdown && state.breakdownFor === state.iterationId)) {
    panel.innerHTML = `<p class="why-trend__msg">Loading our last games…</p>`;
    try {
      await ensureBreakdown();
    } catch (error) {
      panel = trendPanel(key);
      if (panel) panel.innerHTML = `<p class="why-trend__msg is-error">${escapeHtml(error.message || "Could not load our games.")}</p>`;
      return;
    }
  }
  panel = trendPanel(key);
  if (!panel || !state.openTrends.has(key)) return;
  const data = state.breakdown;
  const stat = (data?.stats || []).find((item) => item.key === key);
  const matches = data?.matches || [];
  if (!stat || !matches.length) {
    panel.innerHTML = `<p class="why-trend__msg">${escapeHtml(data?.message || "No league games played yet this season.")}</p>`;
    return;
  }
  const width = Math.max(560, Math.floor(panel.clientWidth - 24));
  panel.innerHTML = trendChartHtml(stat, matches, width);
}

async function toggleTrend(key) {
  const item = els.whyList?.querySelector(`[data-trend-item="${CSS.escape(key)}"]`);
  const panel = trendPanel(key);
  const btn = item?.querySelector("[data-trend-toggle]");
  if (!item || !panel) return;
  const open = !state.openTrends.has(key);
  if (open) state.openTrends.add(key);
  else state.openTrends.delete(key);
  item.classList.toggle("is-open", open);
  panel.hidden = !open;
  btn?.setAttribute("aria-expanded", String(open));
  if (open) await renderTrend(key);
}

let trendResizeTimer = null;
window.addEventListener("resize", () => {
  if (!state.openTrends.size && !state.detailKey) return;
  window.clearTimeout(trendResizeTimer);
  trendResizeTimer = window.setTimeout(() => {
    if (state.detailKey) {
      if (state.breakdown) renderDetail();
      return;
    }
    for (const key of state.openTrends) void renderTrend(key);
  }, 200);
});

async function loadTable(iterationId, { quiet = false } = {}) {
  if (state.detailKey && Number(iterationId) !== Number(state.iterationId)) closeDetail();
  state.iterationId = iterationId;
  state.loading = true;
  if (!quiet) {
    els.refreshBtn.disabled = true;
    setStatus("Opening local snapshot…");
  }
  renderSeasons();
  try {
    state.table = await api(`/api/win-drivers/table?iteration_id=${iterationId}`);
    setStatus("");
    render();
    const linked = hashStatKey();
    if (linked && !state.detailKey) void openDetail(linked);
    ensureBreakdown().catch(() => {});
    try {
      const snap = await api("/api/hub-snapshots/status");
      if (els.lastUpdated) {
        const stamp = snap.win_drivers_updated_at || state.table?.generated_at;
        if (stamp) {
          const when = new Date(stamp);
          els.lastUpdated.textContent = Number.isNaN(when.getTime())
            ? "Updated"
            : `Updated ${when.toLocaleString()}`;
        }
      }
    } catch {
      /* ignore status fetch */
    }
  } catch (error) {
    setStatus(error.message || "Could not load win stats.", true);
  } finally {
    state.loading = false;
    els.refreshBtn.disabled = false;
  }
}

let refreshPollTimer = null;

async function pollRefreshStatus() {
  try {
    const status = await api("/api/hub-snapshots/status");
    if (status.refreshing || status.last_refresh_status === "running") {
      if (els.lastUpdated) els.lastUpdated.textContent = "Refreshing…";
      return;
    }
    if (refreshPollTimer) {
      window.clearInterval(refreshPollTimer);
      refreshPollTimer = null;
    }
    if (status.last_refresh_status === "error") {
      setStatus(status.last_refresh_error || "Data refresh failed.", true);
      els.refreshBtn.disabled = false;
      return;
    }
    setStatus("Data refresh finished.", false);
    state.breakdown = null;
    state.breakdownFor = null;
    if (state.iterationId) {
      await loadTable(state.iterationId, { quiet: true });
      if (state.detailKey) void openDetail(state.detailKey);
    }
  } catch (error) {
    setStatus(error.message || "Could not check refresh status.", true);
    els.refreshBtn.disabled = false;
  }
}

async function refreshData() {
  els.refreshBtn.disabled = true;
  if (els.lastUpdated) els.lastUpdated.textContent = "Refreshing…";
  setStatus("Pulling latest Impect data in the background…");
  try {
    await api("/api/hub-snapshots/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: "win_drivers" }),
    });
    if (refreshPollTimer) window.clearInterval(refreshPollTimer);
    refreshPollTimer = window.setInterval(() => {
      void pollRefreshStatus();
    }, 2500);
    window.setTimeout(() => {
      void pollRefreshStatus();
    }, 800);
  } catch (error) {
    setStatus(error.message || "Could not start refresh.", true);
    els.refreshBtn.disabled = false;
  }
}

async function boot() {
  try {
    state.meta = await api("/api/win-drivers/meta");
    const iterationId = state.meta.default_iteration_id;
    if (!iterationId) {
      setStatus("No League Two season found in Impect.", true);
      return;
    }
    await loadTable(iterationId);
  } catch (error) {
    setStatus(error.message || "Could not load seasons.", true);
  }
}

els.refreshBtn?.addEventListener("click", () => {
  void refreshData();
});

boot();
