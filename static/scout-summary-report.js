const ALLOWED_SEASONS = ["26/27", "25/26", "ALL"];

const coverageColors = {
  live: "#34d399",
  video: "#fbbf24",
  not_covered: "#64748b",
};

const coverageLabels = {
  live: "Live games covered",
  video: "Video games covered",
  not_covered: "Games not covered",
  not_seen: "Games not seen",
};

const state = {
  meta: null,
  season: "ALL",
  staff: "",
  preset: "",
  report: null,
  loading: false,
  lastQuery: null,
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  staffToggle: document.getElementById("staffToggle"),
  dateFrom: document.getElementById("dateFrom"),
  dateTo: document.getElementById("dateTo"),
  rangeSummary: document.getElementById("rangeSummary"),
  generateBtn: document.getElementById("generateBtn"),
  exportPdfBtn: document.getElementById("exportPdfBtn"),
  exportTwoPagerBtn: document.getElementById("exportTwoPagerBtn"),
  exportPlayerPosBtn: document.getElementById("exportPlayerPosBtn"),
  statusBar: document.getElementById("statusBar"),
  reportEmpty: document.getElementById("reportEmpty"),
  reportPreview: document.getElementById("reportPreview"),
  reportTitle: document.getElementById("reportTitle"),
  reportMeta: document.getElementById("reportMeta"),
  kpiPanel: document.getElementById("kpiPanel"),
  scoutTable: document.querySelector("#scoutTable tbody"),
  staffTeamTable: document.querySelector("#staffTeamTable tbody"),
  playerReportsTable: document.querySelector("#playerReportsTable tbody"),
  playerReportsTitle: document.getElementById("playerReportsTitle"),
  positionReportsGrid: document.getElementById("positionReportsGrid"),
  recommendationsPanel: document.getElementById("recommendationsPanel"),
  leaguePieGrid: document.getElementById("leaguePieGrid"),
  leagueTeamExposureGrid: document.getElementById("leagueTeamExposureGrid"),
};

async function fetchJson(url) {
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function dateKeyFromDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatShortDate(dateKey) {
  if (!dateKey) return "";
  return new Date(`${dateKey}T12:00:00`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function addDays(dateKey, days) {
  const date = new Date(`${dateKey}T12:00:00`);
  date.setDate(date.getDate() + days);
  return dateKeyFromDate(date);
}

function footballWeekStart(dateKey) {
  const date = new Date(`${dateKey}T12:00:00`);
  const day = date.getDay();
  const daysBack = day === 6 ? 0 : day + 1;
  date.setDate(date.getDate() - daysBack);
  return dateKeyFromDate(date);
}

function footballWeekRangeFromStart(startKey) {
  return { from: startKey, to: addDays(startKey, 6) };
}

function monthDateRange(year, monthIndex) {
  const start = new Date(year, monthIndex, 1);
  const end = new Date(year, monthIndex + 1, 0);
  return {
    from: dateKeyFromDate(start),
    to: dateKeyFromDate(end),
  };
}

function seasonDateRange(seasonCode) {
  const code = seasonCode && seasonCode !== "ALL" ? seasonCode : "26/27";
  const startYear = 2000 + Number.parseInt(code.split("/")[0], 10);
  return { from: `${startYear}-08-01`, to: `${startYear + 1}-07-31` };
}

function lastSeasonDateRange(seasonCode) {
  const code = seasonCode && seasonCode !== "ALL" ? seasonCode : "26/27";
  const year = Number.parseInt(code.split("/")[0], 10);
  return seasonDateRange(`${String(year - 1).padStart(2, "0")}/${String(year).padStart(2, "0")}`);
}

function exportPresetRange(presetId) {
  const now = new Date();
  const today = todayKey();
  const weekStart = footballWeekStart(today);
  switch (presetId) {
    case "all_time":
      return { from: "", to: "", label: "All time", period: "all" };
    case "this_week":
      return { ...footballWeekRangeFromStart(weekStart), label: "This week", period: "this_week" };
    case "last_week": {
      const start = addDays(weekStart, -7);
      return { ...footballWeekRangeFromStart(start), label: "Last week", period: "last_week" };
    }
    case "next_week": {
      const start = addDays(weekStart, 7);
      return { ...footballWeekRangeFromStart(start), label: "Next week", period: "next_week" };
    }
    case "last_month": {
      const range = monthDateRange(now.getFullYear(), now.getMonth() - 1);
      return { ...range, label: "Last month", period: "last_month" };
    }
    case "this_month": {
      const range = monthDateRange(now.getFullYear(), now.getMonth());
      return { ...range, label: "This month", period: "this_month" };
    }
    case "this_season": {
      const range = seasonDateRange(state.season);
      const label = state.season && state.season !== "ALL" ? `Season ${state.season}` : "This season";
      return { ...range, label, period: "this_season" };
    }
    case "last_season": {
      const range = lastSeasonDateRange(state.season);
      const year = state.season && state.season !== "ALL"
        ? Number.parseInt(state.season.split("/")[0], 10)
        : 26;
      const labelCode = `${String(year - 1).padStart(2, "0")}/${String(year).padStart(2, "0")}`;
      return { ...range, label: `Season ${labelCode}`, period: "last_season" };
    }
    case "last_3_months": {
      const start = new Date(now);
      start.setDate(start.getDate() - 90);
      return { from: dateKeyFromDate(start), to: today, label: "Last 3 months", period: "last_3_months" };
    }
    case "last_6_months": {
      const start = new Date(now);
      start.setDate(start.getDate() - 183);
      return { from: dateKeyFromDate(start), to: today, label: "Last 6 months", period: "last_6_months" };
    }
    case "upcoming":
      return { from: today, to: "", label: "Upcoming", period: "upcoming" };
    default:
      return { from: "", to: "", label: "", period: "" };
  }
}

function formatRangeLabel(from, to) {
  if (!from && !to) return "All time";
  if (from && to) return `${formatShortDate(from)} to ${formatShortDate(to)}`;
  if (from) return `From ${formatShortDate(from)}`;
  if (to) return `Up to ${formatShortDate(to)}`;
  return "Choose a date range";
}

function updateRangeSummary() {
  const from = els.dateFrom?.value || "";
  const to = els.dateTo?.value || "";
  if (els.rangeSummary) {
    els.rangeSummary.textContent = formatRangeLabel(from, to);
  }
}

function setPreset(presetId) {
  state.preset = presetId;
  const range = exportPresetRange(presetId);
  if (els.dateFrom) els.dateFrom.value = range.from;
  if (els.dateTo) els.dateTo.value = range.to;
  document.querySelectorAll("[data-export-preset]").forEach((button) => {
    button.classList.toggle("so-export-preset--active", button.dataset.exportPreset === presetId);
  });
  updateRangeSummary();
}

function currentDateQuery() {
  if (state.preset === "all_time") {
    return { from: "", to: "", presetLabel: "All time", period: "all" };
  }
  const from = els.dateFrom?.value || "";
  const to = els.dateTo?.value || "";
  if (!from && !to) {
    throw new Error("Pick a quick range or enter at least one date.");
  }
  if (from && to && from > to) {
    throw new Error("The start date must be on or before the end date.");
  }
  const preset = state.preset ? exportPresetRange(state.preset) : null;
  const presetLabel = preset?.label || formatRangeLabel(from, to);
  return {
    from,
    to,
    presetLabel,
    period: preset?.period || "",
  };
}

function buildReportParams() {
  const { from, to, presetLabel, period } = currentDateQuery();
  const params = new URLSearchParams({ include_past: "true" });
  if (state.season !== "ALL") params.set("season", state.season);
  if (state.staff) params.set("staff", state.staff);
  if (period === "all") {
    params.set("period", "all");
  } else {
    if (from) params.set("date_from", from);
    if (to) params.set("date_to", to);
    if (period) params.set("period", period);
  }
  params.set("period_label", presetLabel);
  state.lastQuery = { from, to, presetLabel, period, params: params.toString() };
  return params;
}

function renderSeasonToggle() {
  if (!els.seasonToggle) return;
  const seasons = state.meta?.seasons || ALLOWED_SEASONS;
  const options = ["ALL", ...seasons.filter((row) => row !== "ALL")];
  els.seasonToggle.innerHTML = options
    .map(
      (season) => `
      <button type="button" class="fp-season-btn${state.season === season ? " fp-season-btn--active" : ""}" data-season="${season}">${season}</button>
    `
    )
    .join("");
}

function renderStaffToggle() {
  if (!els.staffToggle) return;
  const staff = state.meta?.staff || [];
  els.staffToggle.innerHTML = `
    <button type="button" class="fp-league-btn${!state.staff ? " fp-league-btn--active" : ""}" data-staff="">All scouts</button>
    ${staff
      .map(
        (name) => `
      <button type="button" class="fp-league-btn${state.staff === name ? " fp-league-btn--active" : ""}" data-staff="${name}">${name.split(" ")[0]}</button>
    `
      )
      .join("")}
  `;
}

function renderKpis(totals) {
  const row = totals || {};
  els.kpiPanel.innerHTML = `
    <div class="fp-summary__item"><span class="so-kpi__value">${row.assigned || 0}</span><span class="so-kpi__label">Games covered</span></div>
    <div class="fp-summary__item"><span class="so-kpi__value">${row.live || 0}</span><span class="so-kpi__label">Live</span></div>
    <div class="fp-summary__item"><span class="so-kpi__value">${row.video || 0}</span><span class="so-kpi__label">Video</span></div>
    <div class="fp-summary__item"><span class="so-kpi__value">${row.scouting_reports || 0}</span><span class="so-kpi__label">Player reports</span></div>
  `;
}

function renderScoutTable(staffRows) {
  if (!staffRows.length) {
    els.scoutTable.innerHTML = `<tr><td colspan="4" class="so-report-table__empty">No scout assignments in this period.</td></tr>`;
    return;
  }
  els.scoutTable.innerHTML = staffRows
    .map(
      (row) => `
    <tr>
      <td>${row.staff || "—"}</td>
      <td>${row.total || 0}</td>
      <td>${row.live || 0}</td>
      <td>${row.video || 0}</td>
    </tr>
  `
    )
    .join("");
}

function renderStaffTeamTable(rows) {
  if (!els.staffTeamTable) return;
  if (!rows.length) {
    els.staffTeamTable.innerHTML = `<tr><td colspan="5" class="so-report-table__empty">No staff team data.</td></tr>`;
    return;
  }
  els.staffTeamTable.innerHTML = rows
    .map(
      (row) => `
    <tr>
      <td>${row.label || "—"}</td>
      <td>${row.total || 0}</td>
      <td>${row.live || 0}</td>
      <td>${row.video || 0}</td>
      <td>${row.avg_per_member ?? 0}</td>
    </tr>
  `
    )
    .join("");
}

function renderPositionReports(rows) {
  if (!els.positionReportsGrid) return;
  if (!rows.length) {
    els.positionReportsGrid.innerHTML = `<p class="so-report-chart-empty">No position totals yet.</p>`;
    return;
  }
  els.positionReportsGrid.innerHTML = rows
    .map(
      (row) => `
    <article class="so-report-position-card">
      <span class="so-report-position-card__id">${row.bucket_id || "—"}</span>
      <strong class="so-report-position-card__label">${row.label || "—"}</strong>
      <span class="so-report-position-card__count">${row.report_count || 0}</span>
      <span class="so-report-position-card__meta">${row.player_count || 0} players</span>
    </article>
  `
    )
    .join("");
}

function renderRecommendations(rows) {
  if (!els.recommendationsPanel) return;
  if (!rows.length) {
    els.recommendationsPanel.innerHTML = `<p class="so-report-chart-empty">Mark player reports to build recommendations.</p>`;
    return;
  }
  els.recommendationsPanel.innerHTML = `
    <ul class="so-report-recs__list">
      ${rows
        .map(
          (row) => `<li>
            <strong>${row.player_name || "—"}</strong>
            <span>${row.position_label || "—"} · ${row.team || "—"} · ${row.report_count || 0} reports${row.staff ? ` · ${row.staff}` : ""}</span>
          </li>`
        )
        .join("")}
    </ul>
  `;
}

function polarToCartesian(cx, cy, radius, angleDeg) {
  const angle = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
}

function describeArc(cx, cy, radius, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, radius, endAngle);
  const end = polarToCartesian(cx, cy, radius, startAngle);
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
  return `M ${cx} ${cy} L ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${radius} ${radius} 0 ${largeArc} 0 ${end.x.toFixed(2)} ${end.y.toFixed(2)} Z`;
}

function renderCoveragePie(segments, size = 140) {
  const total = segments.reduce((sum, segment) => sum + segment.count, 0);
  if (!total) {
    return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-hidden="true"><circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 8}" fill="#334155"></circle></svg>`;
  }
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 8;
  let angle = 0;
  const slices = segments
    .filter((segment) => segment.count > 0)
    .map((segment) => {
      const sweep = (segment.count / total) * 360;
      const path = describeArc(cx, cy, radius, angle, angle + sweep);
      const color = coverageColors[segment.key] || "#94a3b8";
      angle += sweep;
      return `<path d="${path}" fill="${color}" stroke="#0d1218" stroke-width="1.2"></path>`;
    });
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-hidden="true">${slices.join("")}</svg>`;
}

function renderLeagueCoverageGrid(rows) {
  if (!rows.length) {
    els.leaguePieGrid.innerHTML = `<p class="so-report-chart-empty">No league data in this period.</p>`;
    return;
  }
  els.leaguePieGrid.innerHTML = rows
    .map((row) => {
      const segments = [
        { key: "live", count: row.live || 0 },
        { key: "video", count: row.video || 0 },
        { key: "not_covered", count: row.not_covered || 0 },
      ];
      const total = row.total || segments.reduce((sum, segment) => sum + segment.count, 0);
      const legend = segments
        .map((segment) => {
          const pct = total ? ((segment.count / total) * 100).toFixed(1) : "0.0";
          return `<li><span class="so-report-legend__swatch" style="background:${coverageColors[segment.key]}"></span>${coverageLabels[segment.key]} · ${segment.count} (${pct}%)</li>`;
        })
        .join("");
      return `
      <article class="so-report-league-card">
        <h4 class="so-report-league-card__title">${row.league || "Unknown"}</h4>
        <div class="so-report-league-card__pie">${renderCoveragePie(segments)}</div>
        <ul class="so-report-legend so-report-legend--compact">${legend}</ul>
        <p class="so-report-league-card__total">${total} games in period</p>
      </article>
    `;
    })
    .join("");
}

function renderPlayerReports(rows) {
  els.playerReportsTitle.textContent = `Total reports per player (${rows.length})`;
  if (!rows.length) {
    els.playerReportsTable.innerHTML = `<tr><td colspan="4" class="so-report-table__empty">No player reports in this period.</td></tr>`;
    return;
  }
  els.playerReportsTable.innerHTML = rows
    .map(
      (row) => `
      <tr>
        <td>${row.player_name || "—"}</td>
        <td>${row.team || "—"}</td>
        <td>${row.position_label || "—"}</td>
        <td>${row.report_count || 0}</td>
      </tr>
    `
    )
    .join("");
}

function renderStackedTeamBar(team, live, video, notSeen, maxTotal) {
  const total = live + video + notSeen;
  const scale = maxTotal ? 100 / maxTotal : 0;
  const segments = [
    { key: "live", count: live, color: coverageColors.live },
    { key: "video", count: video, color: coverageColors.video },
    { key: "not_seen", count: notSeen, color: coverageColors.not_covered },
  ];
  const fills = segments
    .filter((segment) => segment.count > 0)
    .map(
      (segment) =>
        `<span class="so-report-stacked-bar__segment" style="width:${segment.count * scale}%;background:${segment.color}" title="${coverageLabels[segment.key] || segment.key}: ${segment.count}"></span>`
    )
    .join("");
  return `
    <div class="so-report-stacked-bar-row">
      <span class="so-report-stacked-bar-row__label">${team}</span>
      <div class="so-report-stacked-bar-row__track">${fills}</div>
      <span class="so-report-stacked-bar-row__total">${total}</span>
    </div>
  `;
}

function renderLeagueTeamExposure(rows) {
  if (!rows.length) {
    els.leagueTeamExposureGrid.innerHTML = `<p class="so-report-chart-empty">No team exposure data in this period.</p>`;
    return;
  }
  els.leagueTeamExposureGrid.innerHTML = rows
    .map((leagueRow) => {
      const teams = leagueRow.teams || [];
      const maxTotal = Math.max(...teams.map((team) => team.total || 0), 1);
      const bars = teams
        .map((team) =>
          renderStackedTeamBar(
            team.team || "—",
            team.live || 0,
            team.video || 0,
            team.not_seen || 0,
            maxTotal
          )
        )
        .join("");
      return `
      <article class="so-report-team-exposure-card">
        <header class="so-report-team-exposure-card__head">
          <h4>${leagueRow.league || "Unknown"}</h4>
          <ul class="so-report-legend so-report-legend--compact">
            <li><span class="so-report-legend__swatch" style="background:${coverageColors.live}"></span>Live</li>
            <li><span class="so-report-legend__swatch" style="background:${coverageColors.video}"></span>Video</li>
            <li><span class="so-report-legend__swatch" style="background:${coverageColors.not_covered}"></span>Not seen</li>
          </ul>
        </header>
        <div class="so-report-stacked-bars">${bars}</div>
      </article>
    `;
    })
    .join("");
}

function setExportEnabled(enabled) {
  els.exportPdfBtn.disabled = !enabled;
  if (els.exportTwoPagerBtn) els.exportTwoPagerBtn.disabled = !enabled;
  if (els.exportPlayerPosBtn) els.exportPlayerPosBtn.disabled = !enabled;
}

function showReport(report) {
  state.report = report;
  const totals = report.totals || {};
  const hasData = Number(totals.assigned || 0) > 0;

  els.reportEmpty.classList.add("so-report-preview--hidden");
  els.reportPreview.classList.remove("so-report-preview--hidden");
  setExportEnabled(hasData);

  els.reportTitle.textContent = report.period_label || "Scout summary";
  const seasonLabel = (report.seasons || []).join(", ") || "All seasons";
  const staffLabel = report.staff_filter ? ` · ${report.staff_filter}` : "";
  const generated = report.generated_at
    ? new Date(report.generated_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })
    : "";
  els.reportMeta.textContent = `${seasonLabel}${staffLabel}${generated ? ` · Generated ${generated}` : ""}`;

  renderKpis(totals);
  renderStaffTeamTable(report.staff_teams || []);
  renderScoutTable(report.staff || []);
  renderLeagueCoverageGrid(report.league_coverage || []);
  renderPlayerReports(report.player_reports || []);
  renderPositionReports(report.position_reports || []);
  renderRecommendations(report.recommendations || []);
  renderLeagueTeamExposure(report.league_team_exposure || []);

  if (!hasData) {
    els.statusBar.textContent = "No assignments found for this date range. Try widening the window.";
  } else {
    els.statusBar.textContent = `Report ready — ${totals.assigned} games covered. Export two-pager, full review, or player & position.`;
  }
}

async function generateReport() {
  state.loading = true;
  els.generateBtn.disabled = true;
  setExportEnabled(false);
  els.statusBar.textContent = "Generating report…";

  try {
    const params = buildReportParams();
    const report = await fetchJson(`/api/fixture-planner/scout-summary/report?${params}`);
    showReport(report);
  } catch (error) {
    els.statusBar.textContent = error.message;
    els.reportEmpty.classList.remove("so-report-preview--hidden");
    els.reportPreview.classList.add("so-report-preview--hidden");
  } finally {
    state.loading = false;
    els.generateBtn.disabled = false;
  }
}

async function exportPdf(reportFormat = "full") {
  if (!state.lastQuery) {
    els.statusBar.textContent = "Generate a report first.";
    return;
  }
  const labels = {
    full: "full review",
    two_pager: "two-pager",
    player_position: "player & position",
    one_pager: "one pager",
  };
  setExportEnabled(false);
  els.statusBar.textContent = `Exporting ${labels[reportFormat] || "report"}…`;
  try {
    const params = new URLSearchParams(state.lastQuery.params);
    params.set("report_format", reportFormat);
    const res = await fetch(`/api/fixture-planner/scout-summary/export?${params}`);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] || `scout-summary-${reportFormat}.pdf`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    els.statusBar.textContent = `${labels[reportFormat] || "Report"} downloaded.`;
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    const hasData = Number(state.report?.totals?.assigned || 0) > 0;
    setExportEnabled(hasData);
  }
}

async function init() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("season")) state.season = params.get("season");
  if (params.get("staff")) state.staff = params.get("staff");

  state.meta = await fetchJson("/api/fixture-planner/meta");
  renderSeasonToggle();
  renderStaffToggle();
  updateRangeSummary();

  els.seasonToggle?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-season]");
    if (!button) return;
    state.season = button.dataset.season || "ALL";
    renderSeasonToggle();
  });

  els.staffToggle?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-staff]");
    if (!button) return;
    state.staff = button.dataset.staff || "";
    renderStaffToggle();
  });

  document.querySelectorAll("[data-export-preset]").forEach((button) => {
    button.addEventListener("click", () => setPreset(button.dataset.exportPreset || ""));
  });

  els.dateFrom?.addEventListener("change", () => {
    state.preset = "";
    document.querySelectorAll("[data-export-preset]").forEach((node) => {
      node.classList.remove("so-export-preset--active");
    });
    updateRangeSummary();
  });
  els.dateTo?.addEventListener("change", () => {
    state.preset = "";
    document.querySelectorAll("[data-export-preset]").forEach((node) => {
      node.classList.remove("so-export-preset--active");
    });
    updateRangeSummary();
  });

  els.generateBtn?.addEventListener("click", () => generateReport());
  els.exportPdfBtn?.addEventListener("click", () => exportPdf("full"));
  els.exportTwoPagerBtn?.addEventListener("click", () => exportPdf("two_pager"));
  els.exportPlayerPosBtn?.addEventListener("click", () => exportPdf("player_position"));

  if (params.get("from")) {
    els.dateFrom.value = params.get("from");
  }
  if (params.get("to")) {
    els.dateTo.value = params.get("to");
  }
  if (params.get("preset")) {
    setPreset(params.get("preset"));
  }
  updateRangeSummary();

  if (params.get("autogen") === "1" && (els.dateFrom?.value || els.dateTo?.value)) {
    generateReport();
  }
}

init().catch((error) => {
  els.statusBar.textContent = error.message;
});
