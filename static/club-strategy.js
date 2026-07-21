const state = {
  meta: null,
  report: null,
  competition: "League Two",
  iterationId: null,
  activeTab: "standings",
  loading: false,
  firstGoalLoading: false,
  exporting: false,
  timingView: "periods",
};

const els = {
  competitionToggle: document.getElementById("competitionToggle"),
  seasonToggle: document.getElementById("seasonToggle"),
  lastUpdated: document.getElementById("lastUpdated"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportBtn: document.getElementById("exportBtn"),
  tabNav: document.getElementById("tabNav"),
  statusBanner: document.getElementById("statusBanner"),
  panelTitle: document.getElementById("panelTitle"),
  panelHint: document.getElementById("panelHint"),
  tableHead: document.getElementById("tableHead"),
  tableBody: document.getElementById("tableBody"),
  tableFoot: document.getElementById("tableFoot"),
  timingViewToggle: document.getElementById("timingViewToggle"),
  dataTable: document.getElementById("dataTable"),
  pageEyebrow: document.getElementById("pageEyebrow"),
};

const TAB_CONFIG = {
  standings: {
    title: "League + Shooting",
    hint: "League table with shots, shots on target, clean sheets, and season projections",
    columns: [
      { key: "position", label: "Position", fmt: "int" },
      { key: "club", label: "Club", fmt: "club" },
      { key: "played", label: "Played", fmt: "int" },
      { key: "won", label: "Won", fmt: "int", higherBetter: true },
      { key: "drawn", label: "Drawn", fmt: "int" },
      { key: "lost", label: "Lost", fmt: "int", higherBetter: false },
      { key: "goals_for", label: "Goals for", fmt: "int", higherBetter: true },
      { key: "goals_against", label: "Goals ag", fmt: "int", higherBetter: false },
      { key: "goal_difference", label: "Goal diff", fmt: "signed", higherBetter: true },
      { key: "shots", label: "Total shots", fmt: "int", higherBetter: true },
      { key: "sot", label: "On target", fmt: "int", higherBetter: true },
      { key: "sot_pct", label: "On target %", fmt: "pct", higherBetter: true },
      { key: "clean_sheets", label: "Clean sheets", fmt: "int", higherBetter: true },
      { key: "clean_sheet_pct", label: "Clean sheet %", fmt: "pct", higherBetter: true },
      { key: "points", label: "Points", fmt: "int", higherBetter: true },
      { key: "ppg", label: "Pts per game", fmt: "dec", higherBetter: true },
      { key: "ppg_x46", label: "Season proj.", title: "Points per game × 46 games", fmt: "dec", higherBetter: true },
    ],
    source: "standings",
  },
  strategy: {
    title: "Club Strategy (xG)",
    hint: "Expected goals and points vs actual — green Pts vs xPts = over-performing, red = under-performing",
    columns: [
      { key: "position", label: "Position", fmt: "int" },
      { key: "club", label: "Club", fmt: "club" },
      { key: "xg_for", label: "xG for", fmt: "dec", higherBetter: true },
      { key: "xg_against", label: "xG against", fmt: "dec", higherBetter: false },
      { key: "xg_difference", label: "xG difference", fmt: "signed", higherBetter: true },
      { key: "xpoints", label: "Expected pts", fmt: "dec", higherBetter: true },
      { key: "xppg", label: "Expected PPG", fmt: "dec", higherBetter: true },
      { key: "xppg_x46", label: "xPts proj.", title: "Expected points per game × 46 games", fmt: "dec", higherBetter: true },
      { key: "xp_vs_actual", label: "Pts vs xPts", title: "Actual points minus expected points — positive = over-performing", fmt: "signed", higherBetter: true },
      { key: "points", label: "Actual points", fmt: "int", higherBetter: true },
    ],
    source: "standings",
  },
  first_goal: {
    title: "First Goal",
    hint: "What happens when a team scores or concedes the opening goal of the match",
    columns: [
      { key: "position", label: "Position", fmt: "int" },
      { key: "club", label: "Club", fmt: "club" },
      { key: "fg_scored", label: "Scored first", title: "Matches where this team scored the first goal", fmt: "int", higherBetter: true },
      { key: "nil_nil", label: "Nil-nil", title: "Matches that finished 0-0", fmt: "int", higherBetter: false },
      { key: "fg_conceded", label: "Conceded first", title: "Matches where this team conceded the first goal", fmt: "int", higherBetter: false },
      { key: "fgs_w", label: "Wins (scored 1st)", title: "Wins after scoring the first goal", fmt: "int", higherBetter: true, group: "scored" },
      { key: "fgs_d", label: "Draws (scored 1st)", title: "Draws after scoring the first goal", fmt: "int", group: "scored" },
      { key: "fgs_l", label: "Losses (scored 1st)", title: "Losses after scoring the first goal", fmt: "int", higherBetter: false, group: "scored" },
      { key: "fgs_ppg", label: "PPG (scored 1st)", title: "Points per game when scoring first", fmt: "dec", higherBetter: true, group: "scored" },
      { key: "fgc_w", label: "Wins (conc. 1st)", title: "Wins after conceding the first goal", fmt: "int", higherBetter: true, group: "conceded" },
      { key: "fgc_d", label: "Draws (conc. 1st)", title: "Draws after conceding the first goal", fmt: "int", group: "conceded" },
      { key: "fgc_l", label: "Losses (conc. 1st)", title: "Losses after conceding the first goal", fmt: "int", higherBetter: false, group: "conceded" },
      { key: "fgc_ppg", label: "PPG (conc. 1st)", title: "Points per game when conceding first", fmt: "dec", higherBetter: true, group: "conceded" },
      { key: "fgs_w_pct", label: "Win % (scored 1st)", title: "Win percentage after scoring the first goal", fmt: "pct", higherBetter: true, group: "scored" },
      { key: "fgc_w_pct", label: "Win % (conc. 1st)", title: "Win percentage after conceding the first goal", fmt: "pct", higherBetter: true, group: "conceded" },
    ],
    source: "first_goal",
  },
  fg_scored_times: {
    title: "Goals Scored First — Times",
    hint: "Opening goals by 15-minute window — green = scored first more often in that period",
    source: "first_goal",
    timing: "fg_scored_times",
  },
  fg_conceded_times: {
    title: "Goals Conceded First — Times",
    hint: "When the opening goal goes against you — green = conceded first less often in that period",
    source: "first_goal",
    timing: "fg_conceded_times",
    invertHeat: true,
  },
};

const TIMING_VIEW_OPTIONS = [
  { id: "periods", label: "By period" },
  { id: "summary", label: "+ Home/Away & halves" },
  { id: "full", label: "Full detail" },
];

const TIMING_BUCKETS = ["0-15", "16-30", "31-45", "45+", "45-60", "61-75", "76-90", "90+", "unknown"];
const TIMING_BUCKET_LABELS = {
  "0-15": "0–15",
  "16-30": "16–30",
  "31-45": "31–45",
  "45+": "1H added",
  "45-60": "45–60",
  "61-75": "61–75",
  "76-90": "76–90",
  "90+": "2H added",
  unknown: "Unknown",
};

async function api(path, { timeoutMs = 0 } = {}) {
  let res;
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer =
    controller &&
    setTimeout(() => controller.abort(), timeoutMs);

  try {
    res = await fetch(path, controller ? { signal: controller.signal } : undefined);
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        "First-goal load timed out — data is still building on the server. Wait a moment, then click Refresh.",
      );
    }
    throw new Error(
      "Could not reach the server — first-goal data can take up to 2 minutes on first load. Keep this tab open and try Refresh.",
    );
  } finally {
    if (timer) clearTimeout(timer);
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function setStatus(message, isError = false) {
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

function formatValue(value, fmt) {
  if (value == null || Number.isNaN(value)) return "—";
  if (fmt === "club") return String(value);
  if (fmt === "int") return String(Math.round(Number(value)));
  if (fmt === "dec") return Number(value).toFixed(2);
  if (fmt === "pct") return `${Number(value).toFixed(1)}%`;
  if (fmt === "signed") {
    const n = Number(value);
    return n > 0 ? `+${n.toFixed(n % 1 ? 2 : 0)}` : n.toFixed(n % 1 ? 2 : 0);
  }
  return String(value);
}

function heatColor(value, min, max, higherBetter = true, { subtle = false } = {}) {
  const n = Number(value);
  if (Number.isNaN(n)) return subtle ? "transparent" : "rgba(55, 65, 81, 0.8)";
  if (subtle && n === 0) return "transparent";
  if (min === max) return subtle ? "rgba(55, 65, 81, 0.35)" : "rgba(55, 65, 81, 0.8)";
  const t = (n - min) / (max - min);
  const score = higherBetter ? t : 1 - t;
  if (subtle) {
    if (score >= 0.66) return "rgba(22, 101, 52, 0.55)";
    if (score >= 0.33) return "rgba(133, 77, 14, 0.4)";
    return "rgba(153, 27, 27, 0.45)";
  }
  if (score >= 0.66) return "rgba(22, 101, 52, 0.95)";
  if (score >= 0.33) return "rgba(133, 77, 14, 0.92)";
  return "rgba(153, 27, 27, 0.95)";
}

function isTimingTab() {
  return Boolean(TAB_CONFIG[state.activeTab]?.timing);
}

function renderTimingViewToggle() {
  if (!els.timingViewToggle) return;
  if (!isTimingTab()) {
    els.timingViewToggle.classList.add("hidden");
    els.timingViewToggle.innerHTML = "";
    return;
  }

  els.timingViewToggle.classList.remove("hidden");
  els.timingViewToggle.innerHTML = "";
  for (const option of TIMING_VIEW_OPTIONS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "timing-view-toggle__btn";
    btn.textContent = option.label;
    btn.classList.toggle("is-active", state.timingView === option.id);
    btn.addEventListener("click", () => {
      if (state.timingView === option.id) return;
      state.timingView = option.id;
      renderTable();
    });
    els.timingViewToggle.appendChild(btn);
  }
}

function timingColumns(prefix, view = "periods", invertHeat = false) {
  const higherBetter = prefix === "fg_scored_times";
  const cols = [
    {
      key: `${prefix}.total`,
      label: "Total",
      title: "Season total",
      fmt: "int",
      heat: false,
    },
  ];

  if (view === "summary" || view === "full") {
    cols.push(
      { key: `${prefix}.home`, label: "Home", title: "At home", fmt: "int", heat: false },
      { key: `${prefix}.away`, label: "Away", title: "Away", fmt: "int", heat: false },
      { key: `${prefix}.first_half`, label: "1st half", title: "First half", fmt: "int", heat: false },
      { key: `${prefix}.second_half`, label: "2nd half", title: "Second half", fmt: "int", heat: false },
    );
  }

  for (const bucket of TIMING_BUCKETS) {
    const label = TIMING_BUCKET_LABELS[bucket] || bucket;
    cols.push({
      key: `${prefix}.buckets.${bucket}.total`,
      label: view === "full" ? "Σ" : label,
      title: `${label} min — total`,
      fmt: "int",
      heat: true,
      higherBetter: invertHeat ? false : higherBetter,
      bucketGroup: view === "full" ? bucket : null,
      bucketRole: view === "full" ? "total" : null,
    });
    if (view === "full") {
      cols.push({
        key: `${prefix}.buckets.${bucket}.home`,
        label: "H",
        title: `${label} min at home`,
        fmt: "int",
        heat: true,
        higherBetter: invertHeat ? false : higherBetter,
        bucketGroup: bucket,
        bucketRole: "home",
      });
      cols.push({
        key: `${prefix}.buckets.${bucket}.away`,
        label: "A",
        title: `${label} min away`,
        fmt: "int",
        heat: true,
        higherBetter: invertHeat ? false : higherBetter,
        bucketGroup: bucket,
        bucketRole: "away",
      });
    }
  }
  return cols;
}

function renderTimingTableHead(columns, view) {
  if (view !== "full") {
    return `<tr>${columns
      .map((col) => {
        const title = col.title ? ` title="${escapeHtml(col.title)}"` : "";
        return `<th class="${col.fmt === "club" ? "club" : ""}"${title}>${col.label}</th>`;
      })
      .join("")}</tr>`;
  }

  const fixed = columns.filter((col) => !col.bucketGroup);
  const fixedCells = fixed
    .map((col) => {
      const title = col.title ? ` title="${escapeHtml(col.title)}"` : "";
      return `<th class="${col.fmt === "club" ? "club" : ""}" rowspan="2"${title}>${col.label}</th>`;
    })
    .join("");

  const groupCells = TIMING_BUCKETS.map((bucket) => {
    const label = TIMING_BUCKET_LABELS[bucket] || bucket;
    return `<th colspan="3" class="timing-group">${label} min</th>`;
  }).join("");

  const subCells = TIMING_BUCKETS.map(
    () => `<th class="timing-sub">Σ</th><th class="timing-sub">H</th><th class="timing-sub">A</th>`,
  ).join("");

  return `<tr class="timing-head__group">${fixedCells}${groupCells}</tr><tr class="timing-head__sub">${subCells}</tr>`;
}

function renderCompetitionToggle() {
  if (!els.competitionToggle) return;
  els.competitionToggle.innerHTML = "";
  const competitions = state.meta?.competitions || [];
  for (const competition of competitions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "season-toggle__btn";
    btn.textContent = competition.label;
    btn.classList.toggle("is-active", competition.id === state.competition);
    btn.addEventListener("click", () => {
      if (state.competition === competition.id) return;
      switchCompetition(competition.id);
    });
    els.competitionToggle.appendChild(btn);
  }
}

function updateChrome() {
  const competition = state.competition || state.meta?.competition || "League Two";
  if (els.pageEyebrow) {
    els.pageEyebrow.innerHTML = `${competition} strategy · <a href="/">← All apps</a>`;
  }
}

function renderSeasonToggle() {
  els.seasonToggle.innerHTML = "";
  for (const season of state.meta.seasons) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "season-toggle__btn";
    btn.textContent = season.label;
    btn.dataset.iterationId = String(season.iteration_id);
    btn.classList.toggle("is-active", season.iteration_id === state.iterationId);
    btn.addEventListener("click", () => {
      if (state.iterationId === season.iteration_id) return;
      state.iterationId = season.iteration_id;
      state.report = { ...(state.report || {}), first_goal: null };
      if (needsFirstGoal()) {
        renderTable();
        loadFirstGoal();
      } else {
        loadReport();
      }
    });
    els.seasonToggle.appendChild(btn);
  }
}

async function switchCompetition(competition) {
  state.competition = competition;
  state.report = null;
  setStatus(`Loading ${competition}…`);
  try {
    state.meta = await api(
      `/api/club-strategy/meta?competition=${encodeURIComponent(competition)}`,
    );
    state.iterationId =
      state.meta.default_iteration_id || state.meta.seasons[0]?.iteration_id || null;
    updateChrome();
    renderCompetitionToggle();
    renderSeasonToggle();
    renderTabNav();
    if (!state.iterationId) {
      setStatus(`No seasons found for ${competition}.`, true);
      return;
    }
    await loadReport();
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderTabNav() {
  els.tabNav.innerHTML = "";
  for (const tab of state.meta.tabs) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tab-nav__btn";
    btn.textContent = tab.label;
    btn.dataset.tab = tab.id;
    btn.classList.toggle("is-active", tab.id === state.activeTab);
    btn.addEventListener("click", () => {
      if (state.activeTab === tab.id) return;
      state.activeTab = tab.id;
      renderTabNav();
      if (needsFirstGoal() && !state.report?.first_goal) {
        renderTable();
        loadFirstGoal();
      } else {
        renderTable();
      }
    });
    els.tabNav.appendChild(btn);
  }
}

function needsFirstGoal() {
  const cfg = TAB_CONFIG[state.activeTab];
  return cfg?.source === "first_goal";
}

function rowsForActiveTab() {
  const cfg = TAB_CONFIG[state.activeTab];
  if (cfg.source === "first_goal") {
    return state.report?.first_goal?.rows || [];
  }
  return state.report?.standings || [];
}

function averagesForActiveTab() {
  const cfg = TAB_CONFIG[state.activeTab];
  if (cfg.source === "first_goal") {
    return state.report?.first_goal?.averages || {};
  }
  return state.report?.averages || {};
}

function getNested(row, path) {
  return path.split(".").reduce((acc, key) => (acc == null ? undefined : acc[key]), row);
}

function renderTable() {
  const cfg = TAB_CONFIG[state.activeTab];
  els.panelTitle.textContent = cfg.title;
  els.panelHint.textContent = cfg.hint;
  renderTimingViewToggle();
  els.dataTable?.classList.toggle("data-table--timing", Boolean(cfg.timing));

  let columns = cfg.columns || [];
  const timingSubtleHeat = Boolean(cfg.timing);
  if (cfg.timing) {
    columns = [
      { key: "position", label: "Pos", fmt: "int", heat: false },
      { key: "club", label: "Club", fmt: "club", heat: false },
      ...timingColumns(cfg.timing, state.timingView, cfg.invertHeat),
    ];
  }

  const rows = rowsForActiveTab();
  const averages = averagesForActiveTab();

  if (needsFirstGoal() && state.firstGoalLoading && !rows.length) {
    const colCount = columns.length || 1;
    els.tableHead.innerHTML = `<tr>${columns
      .map((col) => `<th>${col.label}</th>`)
      .join("")}</tr>`;
    els.tableBody.innerHTML = `<tr><td colspan="${colCount}">Loading first-goal data from match events — first load can take up to 2 minutes…</td></tr>`;
    els.tableFoot.innerHTML = "";
    return;
  }

  if (cfg.timing) {
    els.tableHead.innerHTML = renderTimingTableHead(columns, state.timingView);
  } else {
    els.tableHead.innerHTML = `<tr>${columns
      .map((col) => {
        const title = col.title ? ` title="${escapeHtml(col.title)}"` : "";
        const groupClass = col.group ? ` data-group="${col.group}"` : "";
        return `<th class="${col.fmt === "club" ? "club" : ""}"${title}${groupClass}>${col.label}</th>`;
      })
      .join("")}</tr>`;
  }

  const heatCols = columns.filter((col) => col.fmt !== "club" && col.heat !== false);
  const ranges = Object.fromEntries(
    heatCols.map((col) => {
      const values = rows
        .map((row) => {
          const raw = col.key.includes(".") ? getNested(row, col.key) : row[col.key];
          return Number(raw);
        })
        .filter((n) => !Number.isNaN(n));
      return [col.key, { min: Math.min(...values, 0), max: Math.max(...values, 0) }];
    }),
  );

  els.tableBody.innerHTML = rows
    .map((row) => {
      const focusClass = row.focus ? "focus" : "";
      const cells = columns
        .map((col) => {
          const raw = col.key.includes(".") ? getNested(row, col.key) : row[col.key];
          if (col.fmt === "club") {
            return `<td class="club">${escapeHtml(String(raw || ""))}</td>`;
          }
          const range = col.heat === false ? null : ranges[col.key];
          const style = range
            ? `background:${heatColor(raw, range.min, range.max, col.higherBetter !== false, {
                subtle: timingSubtleHeat,
              })}`
            : "";
          const bucketClass = col.bucketGroup ? " timing-bucket" : "";
          return `<td class="heat-cell${bucketClass}" style="${style}">${formatValue(raw, col.fmt)}</td>`;
        })
        .join("");
      return `<tr class="${focusClass}">${cells}</tr>`;
    })
    .join("");

  if (!rows.length) {
    els.tableBody.innerHTML = `<tr><td colspan="${columns.length}">No data yet for this view.</td></tr>`;
    els.tableFoot.innerHTML = "";
    return;
  }

  const avgCells = columns
    .map((col) => {
      if (col.fmt === "club") return `<td class="club">AVERAGE</td>`;
      const avg = col.key.includes(".") ? getNested(averages, col.key) : averages[col.key];
      return `<td class="heat-cell">${formatValue(avg, col.fmt)}</td>`;
    })
    .join("");
  els.tableFoot.innerHTML = `<tr>${avgCells}</tr>`;
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadFirstGoal({ force = false } = {}) {
  if (state.firstGoalLoading) return;
  if (state.report?.first_goal && !force) {
    renderTable();
    return;
  }

  state.firstGoalLoading = true;
  els.refreshBtn.disabled = true;
  setStatus(
    "Loading first-goal data from match events — first load can take up to 2 minutes. Please wait…",
  );

  try {
    const params = new URLSearchParams({
      iteration_id: String(state.iterationId),
    });
    if (force) params.set("refresh", "1");
    const firstGoal = await api(`/api/club-strategy/first-goal?${params}`, {
      timeoutMs: 180000,
    });
    state.report = { ...(state.report || {}), first_goal: firstGoal };
    renderTable();
    const missing = firstGoal.missing_matches || [];
    const inferred = firstGoal.inferred_matches || [];
    const coverage = firstGoal.coverage || {};
    if (missing.length) {
      const preview = missing
        .slice(0, 6)
        .map((m) => `${m.date || "?"} ${m.home} ${m.score} ${m.away}`)
        .join(" · ");
      setStatus(
        `First-goal coverage gap: ${missing.length} match${missing.length === 1 ? "" : "es"} unresolved`
          + `. ${preview}${missing.length > 6 ? " …" : ""}`,
        true,
      );
    } else if (inferred.length) {
      setStatus(
        `All matches covered. ${inferred.length} used HT/FT inference (minute unknown — shown in Unknown column).`,
      );
    } else {
      setStatus("");
    }
  } catch (error) {
    setStatus(error.message, true);
    renderTable();
  } finally {
    state.firstGoalLoading = false;
    els.refreshBtn.disabled = false;
  }
}

function prefetchFirstGoal() {
  if (!state.iterationId || state.report?.first_goal || state.firstGoalLoading) return;
  loadFirstGoal().catch(() => {});
}

async function loadReport({ force = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  els.refreshBtn.disabled = true;
  setStatus("Refreshing league data…");

  try {
    const params = new URLSearchParams({
      iteration_id: String(state.iterationId),
    });
    if (force) params.set("refresh", "1");
    const report = await api(`/api/club-strategy/report?${params}`);
    const cachedFirstGoal = state.report?.first_goal;
    state.report = report;
    if (cachedFirstGoal && !force) {
      state.report.first_goal = cachedFirstGoal;
    }
    renderSeasonToggle();
    renderTable();
    const when = new Date(report.generated_at);
    els.lastUpdated.textContent = `${report.season} · updated ${when.toLocaleString()}`;
    setStatus("");
    prefetchFirstGoal();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.loading = false;
    els.refreshBtn.disabled = false;
  }
}

async function exportPdf() {
  if (!state.iterationId || state.exporting) return;
  state.exporting = true;
  if (els.exportBtn) els.exportBtn.disabled = true;
  setStatus(
    "Building Keynote-style PDF deck (all tabs) — first-goal data may take up to 2 minutes on first export…",
  );

  try {
    const params = new URLSearchParams({
      iteration_id: String(state.iterationId),
    });
    let res;
    try {
      res = await fetch(`/api/club-strategy/export-pdf?${params}`, {
        signal: AbortSignal.timeout(180000),
      });
    } catch {
      throw new Error(
        "PDF export timed out or could not reach the server. Keep the page open and try again.",
      );
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const filename = match?.[1] || "club-strategy.pdf";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("PDF deck downloaded.");
    window.setTimeout(() => setStatus(""), 2500);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.exporting = false;
    if (els.exportBtn) els.exportBtn.disabled = false;
  }
}

async function init() {
  try {
    state.meta = await api(
      `/api/club-strategy/meta?competition=${encodeURIComponent(state.competition)}`,
    );
    state.competition = state.meta.competition || state.competition;
    state.iterationId = state.meta.default_iteration_id || state.meta.seasons[0]?.iteration_id;
    updateChrome();
    renderCompetitionToggle();
    renderSeasonToggle();
    renderTabNav();
    await loadReport();
    prefetchFirstGoal();
  } catch (error) {
    setStatus(error.message, true);
  }
}

els.refreshBtn.addEventListener("click", () => {
  if (needsFirstGoal()) {
    loadFirstGoal({ force: true });
  } else {
    loadReport({ force: true });
  }
});

if (els.exportBtn) {
  els.exportBtn.addEventListener("click", () => {
    exportPdf();
  });
}

init();
