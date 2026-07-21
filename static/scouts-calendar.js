const ALLOWED_SEASONS = ["26/27", "25/26"];
const REFRESH_MS = 60000;

const leagueColors = {
  "League One": "#3d8bfd",
  "League Two": "#34d399",
  "National League": "#fbbf24",
  "Scottish Prem": "#a78bfa",
  PL2: "#f97316",
  "Irish Prem": "#22d3ee",
};

const state = {
  meta: null,
  payload: null,
  season: "26/27",
  staff: "",
  watchType: "LIVE",
  monthKey: "",
  loading: false,
  refreshTimer: null,
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  staffToggle: document.getElementById("staffToggle"),
  staffSelect: document.getElementById("staffSelect"),
  watchToggle: document.getElementById("watchToggle"),
  calendarRoot: document.getElementById("calendarRoot"),
  monthLabel: document.getElementById("monthLabel"),
  prevMonthBtn: document.getElementById("prevMonthBtn"),
  nextMonthBtn: document.getElementById("nextMonthBtn"),
  todayBtn: document.getElementById("todayBtn"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
};

async function fetchJson(url) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function monthKeyFromDate(dateKey) {
  return dateKey.slice(0, 7);
}

function formatMonthLabel(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return date.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function formatTime(iso) {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatShortDate(dateKey) {
  if (!dateKey) return "";
  const date = new Date(`${dateKey}T12:00:00`);
  return date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function staffFirstName(name) {
  return String(name || "").trim().split(" ")[0] || "Staff";
}

function fixtureLabel(row) {
  const home = String(row.home || "").trim();
  const away = String(row.away || "").trim();
  if (home && away) return `${home} vs ${away}`;
  if (home || away) return home || away;
  return "Fixture details pending";
}

function syncStaffInUrl() {
  const params = new URLSearchParams(window.location.search);
  if (state.staff) {
    params.set("staff", state.staff);
  } else {
    params.delete("staff");
  }
  const query = params.toString();
  const next = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState({}, "", next);
}

function setStaffFilter(staff) {
  state.staff = staff || "";
  state.monthKey = "";
  if (els.staffSelect) {
    els.staffSelect.value = state.staff;
  }
  renderStaffToggle();
  syncStaffInUrl();
  loadCalendar();
}

function renderStaffToggle() {
  if (!els.staffToggle) return;
  const staffList = state.meta?.staff || [];
  const buttons = [
    `<button type="button" class="fp-league-btn so-staff-btn${!state.staff ? " so-staff-btn--active" : ""}" data-staff=""${state.loading ? " disabled" : ""}>All staff</button>`,
    ...staffList.map((name) => {
      const active = state.staff === name;
      return `<button type="button" class="fp-league-btn so-staff-btn${active ? " so-staff-btn--active" : ""}" data-staff="${name}"${state.loading ? " disabled" : ""}>${staffFirstName(name)}</button>`;
    }),
  ];
  els.staffToggle.innerHTML = buttons.join("");

  els.staffToggle.querySelectorAll(".so-staff-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const next = btn.dataset.staff || "";
      if (next === state.staff) return;
      setStaffFilter(next);
    });
  });
}
function jumpToAssignmentMonth() {
  const first = state.payload?.fixtures?.[0]?.date;
  if (first) {
    state.monthKey = monthKeyFromDate(first);
  }
}

function renderUpcomingList() {
  const fixtures = state.payload?.fixtures || [];
  if (!fixtures.length) {
    return `
      <aside class="so-upcoming">
        <header class="so-upcoming__head">
          <h2 class="so-upcoming__title">Upcoming</h2>
        </header>
        <div class="so-upcoming__body">
          <p class="so-empty">No assigned fixtures yet. Assign scouts in the fixture planner.</p>
        </div>
      </aside>
    `;
  }

  return `
    <aside class="so-upcoming">
      <header class="so-upcoming__head">
        <h2 class="so-upcoming__title">Upcoming</h2>
      </header>
      <div class="so-upcoming__body">
        ${fixtures
          .slice(0, 12)
          .map((row) => {
            const color = leagueColors[row.league] || "#34d399";
            return `
              <article class="so-upcoming-item" style="--league-color:${color}">
                <div class="so-upcoming-item__date">${formatShortDate(row.date)} · ${formatTime(row.kickoff_utc)}</div>
                <div class="so-upcoming-item__teams">${fixtureLabel(row)}</div>
                <div class="so-upcoming-item__meta">
                  <span class="so-pill ${row.watch_type === "LIVE" ? "so-pill--live" : "so-pill--video"}">${row.watch_type}</span>
                  <span class="so-cal-event__league">${row.league || "League TBC"}</span>
                  ${state.staff ? "" : `<span class="so-cal-event__staff">${staffFirstName(row.staff)}</span>`}
                </div>
              </article>
            `;
          })
          .join("")}
      </div>
    </aside>
  `;
}

function shiftMonth(monthKey, delta) {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function renderSeasonToggle() {
  const seasons = state.meta?.seasons || ALLOWED_SEASONS;
  els.seasonToggle.innerHTML = seasons
    .map((season) => {
      const active = season === state.season;
      const label = season === "26/27" ? `This season (${season})` : `Last season (${season})`;
      return `<button type="button" class="fp-season-btn${active ? " fp-season-btn--active" : ""}" data-season="${season}"${state.loading ? " disabled" : ""}>${label}</button>`;
    })
    .join("");

  els.seasonToggle.querySelectorAll(".fp-season-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled || btn.classList.contains("fp-season-btn--active")) return;
      state.season = btn.dataset.season;
      state.monthKey = "";
      loadCalendar();
    });
  });
}

function renderWatchToggle() {
  els.watchToggle.querySelectorAll(".fp-view-btn").forEach((btn) => {
    btn.classList.toggle("fp-view-btn--active", btn.dataset.watch === state.watchType);
    btn.onclick = () => {
      if (btn.classList.contains("fp-view-btn--active")) return;
      state.watchType = btn.dataset.watch;
      state.monthKey = "";
      renderWatchToggle();
      loadCalendar();
    };
  });
}

function renderCalendar() {
  if (!state.monthKey) {
    state.monthKey = monthKeyFromDate(todayKey());
  }
  els.monthLabel.textContent = formatMonthLabel(state.monthKey);

  const byDate = state.payload?.by_date || {};
  const [year, month] = state.monthKey.split("-").map(Number);
  const firstDay = new Date(year, month - 1, 1);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = todayKey();

  const weekdayHtml = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    .map((day) => `<div class="so-cal-weekday">${day}</div>`)
    .join("");

  const cells = [];
  for (let i = 0; i < startOffset; i += 1) {
    cells.push(`<div class="so-cal-day so-cal-day--muted"></div>`);
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const events = byDate[dateKey] || [];
    const isToday = dateKey === today;
    cells.push(`
      <div class="so-cal-day${isToday ? " so-cal-day--today" : ""}">
        <div class="so-cal-day__num${isToday ? " so-cal-day__num--today" : ""}">${day}</div>
        ${events
          .map((row) => {
            const color = leagueColors[row.league] || "#34d399";
            return `
              <article class="so-cal-event" style="--league-color:${color}" title="${fixtureLabel(row)}">
                <div class="so-cal-event__time">${formatTime(row.kickoff_utc)} · ${row.watch_type}</div>
                <div class="so-cal-event__teams">${fixtureLabel(row)}</div>
                <div class="so-cal-event__meta">
                  <span class="so-cal-event__league">${row.league || "League TBC"}</span>
                  ${state.staff ? "" : `<span class="so-cal-event__staff">${staffFirstName(row.staff)}</span>`}
                </div>
              </article>
            `;
          })
          .join("")}
      </div>
    `);
  }

  const monthCount = (state.payload?.fixtures || []).filter(
    (row) => monthKeyFromDate(row.date) === state.monthKey,
  ).length;

  const staffLabel = state.staff ? staffFirstName(state.staff) : "All staff";
  els.calendarRoot.innerHTML = `
    <div class="so-cal-page">
      <section class="so-cal-shell">
        <header class="so-cal-shell__head">
          <h2 class="so-cal-shell__title">${formatMonthLabel(state.monthKey)}</h2>
          <span class="so-cal-shell__hint">${staffLabel} · ${monthCount} assignment${monthCount === 1 ? "" : "s"} this month</span>
        </header>
        <div class="so-cal-grid">
          ${weekdayHtml}
          ${cells.join("")}
        </div>
      </section>
      ${renderUpcomingList()}
    </div>
  `;
}

async function loadCalendar() {
  state.loading = true;
  renderSeasonToggle();
  renderStaffToggle();
  els.statusBar.textContent = "Loading scouts calendar…";

  try {
    const params = new URLSearchParams({
      season: state.season,
      watch_type: state.watchType,
      include_past: "false",
    });
    if (state.staff) {
      params.set("staff", state.staff);
    }
    state.payload = await fetchJson(`/api/fixture-planner/scouts-calendar?${params}`);

    jumpToAssignmentMonth();

    renderCalendar();
    const updated = state.payload.generated_at
      ? new Date(state.payload.generated_at).toLocaleTimeString("en-GB")
      : "—";
    const scoutLabel = state.staff || "All staff";
    const count = state.payload.fixtures?.length || 0;
    els.statusBar.textContent = `${scoutLabel} · ${count} upcoming ${state.watchType === "ALL" ? "assignments" : "live games"} · updated ${updated}`;
  } catch (error) {
    els.statusBar.textContent = error.message;
    els.calendarRoot.innerHTML = `<div class="card so-empty">${error.message}</div>`;
  } finally {
    state.loading = false;
    renderSeasonToggle();
    renderStaffToggle();
  }
}

function scheduleRefresh() {
  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
  }
  state.refreshTimer = setInterval(() => {
    if (document.hidden) return;
    loadCalendar();
  }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      loadCalendar();
    }
  });
}

async function init() {
  const params = new URLSearchParams(window.location.search);
  const staffParam = params.get("staff");
  if (staffParam) {
    state.staff = staffParam;
  }

  els.staffSelect?.addEventListener("change", () => {
    setStaffFilter(els.staffSelect.value);
  });

  els.prevMonthBtn?.addEventListener("click", () => {
    state.monthKey = shiftMonth(state.monthKey || monthKeyFromDate(todayKey()), -1);
    renderCalendar();
  });

  els.nextMonthBtn?.addEventListener("click", () => {
    state.monthKey = shiftMonth(state.monthKey || monthKeyFromDate(todayKey()), 1);
    renderCalendar();
  });

  els.todayBtn?.addEventListener("click", () => {
    state.monthKey = monthKeyFromDate(todayKey());
    renderCalendar();
  });

  els.refreshBtn?.addEventListener("click", () => loadCalendar());
  renderWatchToggle();

  try {
    state.meta = await fetchJson("/api/fixture-planner/meta");
    state.season = state.meta.season || ALLOWED_SEASONS[0];
    if (els.staffSelect && state.meta.staff) {
      els.staffSelect.innerHTML = [
        `<option value="">All staff</option>`,
        ...state.meta.staff.map((name) => `<option value="${name}"${name === state.staff ? " selected" : ""}>${name}</option>`),
      ].join("");
    }
    renderStaffToggle();
    syncStaffInUrl();
    renderSeasonToggle();
    await loadCalendar();
    scheduleRefresh();
  } catch (error) {
    els.statusBar.textContent = error.message;
  }
}

init();
