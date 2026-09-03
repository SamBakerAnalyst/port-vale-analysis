const state = {
  meta: null,
  table: null,
  iterationId: null,
  loading: false,
  sortKey: "points",
  sortDir: "desc",
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
  const n = Number(value);
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

function heatColor(value, min, max, higherBetter = true) {
  const n = Number(value);
  if (Number.isNaN(n) || min === max) return "rgba(55, 65, 81, 0.8)";
  const t = (n - min) / (max - min);
  const score = higherBetter ? t : 1 - t;
  if (score >= 0.66) return "rgba(22, 101, 52, 0.95)";
  if (score >= 0.33) return "rgba(133, 77, 14, 0.92)";
  return "rgba(153, 27, 27, 0.95)";
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
            const valeRank = card.rank ? `${ordinal(card.rank)} / ${card.of}` : "—";
            return `<button type="button" class="why-row${active}" data-sort-key="${escapeHtml(card.key)}">
              <span class="why-row__num">#${card.importance}</span>
              <div>
                <p class="why-row__name">${escapeHtml(card.label)}</p>
                <span class="why-row__strength">${escapeHtml(card.strength || "")} · r=${card.r}</span>
              </div>
              <p class="why-row__why">${escapeHtml(card.why || card.hint || "")}</p>
              <span class="why-row__figures">
                ${figureHtml("Port Vale", formatWithUnit(card, card.value), { extraClass: "why-fig--vale", tone: barTone(card.above_top7) })}
                ${figureHtml("League rank", valeRank, { tone: rankTone(card.rank, card.of) })}
                ${figureHtml("Top 7 avg", formatWithUnit(card, card.top7_avg))}
                ${figureHtml("League avg", formatWithUnit(card, card.league_avg))}
              </span>
            </button>`;
          })
          .join("")}
      </div>`;
    })
    .join("");

  els.whyList.querySelectorAll("[data-sort-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const col = columns().find((item) => item.key === btn.dataset.sortKey);
      if (!col) return;
      cycleSort(col);
      render();
    });
  });
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
      const range = ranges[col.key] || { min: 0, max: 0 };
      const bg = heatColor(raw, range.min, range.max, col.higherBetter !== false);
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
      return [col.key, { min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 0 }];
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

async function loadTable(iterationId, { quiet = false } = {}) {
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
    if (state.iterationId) {
      await loadTable(state.iterationId, { quiet: true });
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
