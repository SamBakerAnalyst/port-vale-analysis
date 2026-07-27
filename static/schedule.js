const DEFAULT_REPORT_TIME = "09:00";
const DEFAULT_OWNERS = [
  { id: "team", label: "Team" },
  { id: "sam", label: "Sam" },
  { id: "tommy", label: "Tommy" },
  { id: "lee", label: "Lee" },
  { id: "martin", label: "Martin" },
];

const state = {
  payload: null,
  owner: "team",
  monthKey: "",
  selectedDate: "",
  loading: false,
  saving: false,
};

const els = {
  calendarRoot: document.getElementById("calendarRoot"),
  ownerToggle: document.getElementById("ownerToggle"),
  monthLabel: document.getElementById("monthLabel"),
  seasonLabel: document.getElementById("seasonLabel"),
  prevMonthBtn: document.getElementById("prevMonthBtn"),
  nextMonthBtn: document.getElementById("nextMonthBtn"),
  todayBtn: document.getElementById("todayBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusBar: document.getElementById("statusBar"),
  panelTitle: document.getElementById("panelTitle"),
  panelSubtitle: document.getElementById("panelSubtitle"),
  panelBody: document.getElementById("panelBody"),
};

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((row) => row.msg || JSON.stringify(row)).join("; ")
          : `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

function todayKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function monthKeyFromDate(dateKey) {
  return String(dateKey || "").slice(0, 7);
}

function formatMonthLabel(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-GB", {
    month: "long",
    year: "numeric",
  });
}

function formatLongDate(dateKey) {
  if (!dateKey) return "Select a day";
  return new Date(`${dateKey}T12:00:00`).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function formatDayHead(dateKey) {
  const date = new Date(`${dateKey}T12:00:00`);
  const weekday = date.toLocaleDateString("en-GB", { weekday: "long" });
  const day = String(date.getDate()).padStart(2, "0");
  const mon = date.toLocaleDateString("en-GB", { month: "short" });
  return `${weekday} ${day}-${mon}`;
}

function formatKickoff(iso) {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatReportLabel(hhmm) {
  if (!hhmm) return "9am Report";
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "pm" : "am";
  const hour12 = ((h + 11) % 12) + 1;
  if (m) return `${hour12}:${String(m).padStart(2, "0")}${suffix} Report`;
  return `${hour12}${suffix} Report`;
}

function shiftMonth(monthKey, delta) {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function ownerQuery() {
  return new URLSearchParams({ owner: state.owner }).toString();
}

function dayEntry(dateKey) {
  return state.payload?.days?.[dateKey] || null;
}

function dayType(dateKey) {
  return dayEntry(dateKey)?.type || null;
}

function recruitmentIn(dateKey) {
  return Boolean(dayEntry(dateKey)?.recruitment_in);
}

function reportTimeFor(dateKey) {
  const entry = dayEntry(dateKey);
  if (entry?.type === "training") {
    return entry.report_time || state.payload?.default_report_time || DEFAULT_REPORT_TIME;
  }
  return state.payload?.default_report_time || DEFAULT_REPORT_TIME;
}

function badgeImg(src, alt) {
  if (!src) return "";
  return `<img class="pv-sch__badge" src="${escapeHtml(src)}" alt="${escapeHtml(alt || "")}" loading="lazy" width="36" height="36" onerror="this.style.display='none'" />`;
}

function renderOwnerToggle() {
  if (!els.ownerToggle) return;
  const owners = state.payload?.owners?.length ? state.payload.owners : DEFAULT_OWNERS;
  els.ownerToggle.innerHTML = owners
    .map(
      (owner) =>
        `<button type="button" class="pv-sch__owner${owner.id === state.owner ? " is-active" : ""}" data-owner="${owner.id}">${escapeHtml(owner.label)}</button>`
    )
    .join("");
  els.ownerToggle.querySelectorAll("[data-owner]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = btn.dataset.owner;
      if (!next || next === state.owner || state.loading) return;
      state.owner = next;
      loadSchedule();
    });
  });
}

function renderMatchBody(row) {
  const isHome = Boolean(row.isHome);
  const opp = row.opponent?.name || (isHome ? row.away : row.home) || "TBC";
  const ha = isHome ? "H" : "A";
  const ko = formatKickoff(row.kickoff_utc || row.scheduledDate);
  const played = row.status === "completed" || Boolean(row.outcome);
  const score = played ? row.scoreLabel || row.score : "";
  const oppBadge = row.opponent_badge || (isHome ? row.away_badge : row.home_badge) || "";
  return `
    <div class="pv-sch__match">
      <div class="pv-sch__match-badges">
        ${badgeImg(oppBadge, opp)}
      </div>
      <div class="pv-sch__match-text">${escapeHtml(opp)} (${ha})</div>
      <div class="pv-sch__match-ko">${score ? escapeHtml(score) : `${escapeHtml(ko)} KO`}</div>
    </div>
  `;
}

function renderSessionBody(dateKey, type) {
  if (type === "training") {
    return `
      <div class="pv-sch__label">IN</div>
      <div class="pv-sch__report">${escapeHtml(formatReportLabel(reportTimeFor(dateKey)))}</div>
    `;
  }
  if (type === "regen") {
    return `<div class="pv-sch__label">REGEN</div>`;
  }
  if (type === "preseason") {
    return `<div class="pv-sch__label">PRE-SEASON</div>`;
  }
  return "";
}

function renderCalendar() {
  if (!state.monthKey) state.monthKey = monthKeyFromDate(todayKey());
  els.monthLabel.textContent = formatMonthLabel(state.monthKey);

  const [year, month] = state.monthKey.split("-").map(Number);
  const firstDay = new Date(year, month - 1, 1);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = todayKey();
  const fixturesByDate = state.payload?.fixtures_by_date || {};
  const eventsByDate = state.payload?.events_by_date || {};

  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    .map((day) => `<div class="pv-sch__weekday">${day}</div>`)
    .join("");

  const cells = [];
  for (let i = 0; i < startOffset; i += 1) {
    cells.push(`<div class="pv-sch__cell pv-sch__cell--muted"></div>`);
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const type = dayType(dateKey);
    const fixtures = fixturesByDate[dateKey] || [];
    const events = eventsByDate[dateKey] || [];
    const match = fixtures[0] || null;
    const hasR = recruitmentIn(dateKey);

    const classes = ["pv-sch__cell"];
    if (dateKey === today) classes.push("pv-sch__cell--today");
    if (dateKey === state.selectedDate) classes.push("pv-sch__cell--selected");
    if (match) {
      classes.push("pv-sch__cell--match");
      classes.push(match.isHome ? "pv-sch__cell--home" : "pv-sch__cell--away");
    } else if (type === "training") {
      classes.push("pv-sch__cell--in");
    } else if (type === "regen") {
      classes.push("pv-sch__cell--regen");
    } else if (type === "preseason") {
      classes.push("pv-sch__cell--preseason");
    }

    const travelHtml = events
      .map((event) => {
        const label = [event.time, event.title].filter(Boolean).join(" · ");
        return `<div class="pv-sch__travel">${escapeHtml(label || "Event")}</div>`;
      })
      .join("");

    const body = match ? renderMatchBody(match) : renderSessionBody(dateKey, type);

    cells.push(`
      <button type="button" class="${classes.join(" ")}" data-date="${dateKey}">
        ${hasR ? '<span class="pv-sch__r" title="Recruitment in">R</span>' : ""}
        <div class="pv-sch__cell-head">
          <span>${escapeHtml(formatDayHead(dateKey))}</span>
        </div>
        <div class="pv-sch__cell-body">
          ${travelHtml}
          ${body}
        </div>
      </button>
    `);
  }

  els.calendarRoot.innerHTML = `
    <div class="pv-sch__weekdays">${weekdays}</div>
    <div class="pv-sch__week">${cells.join("")}</div>
  `;

  els.calendarRoot.querySelectorAll(".pv-sch__cell[data-date]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      const dateKey = btn.dataset.date;
      if (!dateKey || state.saving) return;
      state.selectedDate = dateKey;
      renderCalendar();
      renderPanel();
      if (event.shiftKey) {
        await toggleRecruitment(dateKey);
      } else if (event.altKey) {
        await togglePreseason(dateKey);
      } else {
        await cycleDay(dateKey);
      }
    });
    btn.addEventListener("contextmenu", async (event) => {
      const dateKey = btn.dataset.date;
      if (!dateKey || state.saving) return;
      event.preventDefault();
      state.selectedDate = dateKey;
      await toggleRecruitment(dateKey);
    });
  });
}

function renderPanel() {
  const dateKey = state.selectedDate;
  if (!dateKey) {
    els.panelTitle.textContent = "Select a day";
    els.panelSubtitle.textContent = "Click a date to edit report time, day type, R, or events.";
    els.panelBody.innerHTML = `<p class="pv-sch__empty">No day selected.</p>`;
    return;
  }

  const type = dayType(dateKey);
  const hasR = recruitmentIn(dateKey);
  const fixtures = state.payload?.fixtures_by_date?.[dateKey] || [];
  const events = state.payload?.events_by_date?.[dateKey] || [];
  const reportTime = reportTimeFor(dateKey);

  els.panelTitle.textContent = formatLongDate(dateKey);
  const bits = [];
  if (fixtures.length) bits.push(fixtures[0].isHome ? "Match day · Home" : "Match day · Away");
  if (type === "training") bits.push(`IN · ${formatReportLabel(reportTime)}`);
  else if (type === "regen") bits.push("Regen");
  else if (type === "preseason") bits.push("Pre-season game");
  if (hasR) bits.push("Recruitment in");
  els.panelSubtitle.textContent = bits.join(" · ") || "No session set yet";

  const eventsHtml = events.length
    ? events
        .map(
          (event) => `
      <div class="pv-sch__event">
        <span>${escapeHtml(event.time || "—")}</span>
        <div>${escapeHtml(event.title || "Event")}${event.notes ? `<div style="color:#9ca3af;font-size:0.78rem;margin-top:0.15rem">${escapeHtml(event.notes)}</div>` : ""}</div>
        <button type="button" data-delete-event="${escapeHtml(event.id)}">Delete</button>
      </div>`
        )
        .join("")
    : `<p class="pv-sch__empty">No travel / notes yet.</p>`;

  els.panelBody.innerHTML = `
    <section class="pv-sch__section">
      <h3>Day type</h3>
      <div class="pv-sch__type-row">
        <button type="button" class="pv-sch__type-btn pv-sch__type-btn--in${type === "training" ? " is-active" : ""}" data-set-type="training">IN</button>
        <button type="button" class="pv-sch__type-btn pv-sch__type-btn--regen${type === "regen" ? " is-active" : ""}" data-set-type="regen">Regen</button>
        <button type="button" class="pv-sch__type-btn pv-sch__type-btn--preseason${type === "preseason" ? " is-active" : ""}" data-set-type="preseason">Pre-season</button>
        <button type="button" class="pv-sch__type-btn pv-sch__type-btn--clear${!type ? " is-active" : ""}" data-set-type="none">Clear</button>
      </div>
    </section>

    <section class="pv-sch__section">
      <h3>Recruitment</h3>
      <button type="button" class="pv-sch__type-btn" id="toggleRBtn" style="${hasR ? "background:#f5c518;color:#111;border-color:#f5c518" : ""}">
        ${hasR ? "R · recruitment in" : "Mark recruitment in (R)"}
      </button>
    </section>

    <section class="pv-sch__section${type === "training" ? "" : " hidden"}" id="reportTimeSection">
      <h3>Report time</h3>
      <div class="pv-sch__field">
        <label for="reportTimeInput">Defaults to 09:00</label>
        <div class="pv-sch__actions">
          <input type="time" id="reportTimeInput" class="pv-sch__input" value="${escapeHtml(reportTime)}" />
          <button type="button" class="pv-sch__btn" id="saveReportTimeBtn">Save</button>
        </div>
      </div>
    </section>

    <section class="pv-sch__section">
      <h3>Travel / notes</h3>
      ${eventsHtml}
      <form id="eventForm">
        <div class="pv-sch__field">
          <label for="eventTitle">New note</label>
          <input id="eventTitle" class="pv-sch__input" name="title" maxlength="120" placeholder="e.g. Travel to Doncaster" required />
        </div>
        <div class="pv-sch__field">
          <label for="eventTime">Time (optional)</label>
          <input type="time" id="eventTime" class="pv-sch__input" name="time" />
        </div>
        <div class="pv-sch__field">
          <label for="eventNotes">Details (optional)</label>
          <input id="eventNotes" class="pv-sch__input" name="notes" maxlength="500" placeholder="Departure time TBC" />
        </div>
        <button type="submit" class="pv-sch__btn">Add</button>
      </form>
    </section>
  `;

  els.panelBody.querySelectorAll("[data-set-type]").forEach((btn) => {
    btn.addEventListener("click", async () => setDayType(dateKey, btn.dataset.setType));
  });
  document.getElementById("toggleRBtn")?.addEventListener("click", async () => {
    await toggleRecruitment(dateKey);
  });
  document.getElementById("saveReportTimeBtn")?.addEventListener("click", async () => {
    const value = document.getElementById("reportTimeInput")?.value || DEFAULT_REPORT_TIME;
    await setDayType(dateKey, "training", value);
  });
  els.panelBody.querySelectorAll("[data-delete-event]").forEach((btn) => {
    btn.addEventListener("click", async () => removeEvent(btn.dataset.deleteEvent));
  });
  document.getElementById("eventForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    await addEvent({
      date: dateKey,
      title: form.title.value.trim(),
      time: form.time.value || null,
      notes: form.notes.value.trim(),
      owner: state.owner,
    });
    form.reset();
  });
}

function mergeDayResponse(result) {
  if (!state.payload) return;
  if (result.days) state.payload.days = result.days;
}

function mergeEventsResponse(result) {
  if (!state.payload) return;
  const events = result.events || [];
  state.payload.events = events;
  const byDate = {};
  events.forEach((event) => {
    if (!event?.date) return;
    byDate[event.date] = byDate[event.date] || [];
    byDate[event.date].push(event);
  });
  Object.values(byDate).forEach((rows) => {
    rows.sort((a, b) => String(a.time || "99:99").localeCompare(String(b.time || "99:99")));
  });
  state.payload.events_by_date = byDate;
}

async function cycleDay(dateKey) {
  state.saving = true;
  els.statusBar.textContent = "Updating day…";
  try {
    const result = await fetchJson(`/api/schedule/day/${dateKey}?${ownerQuery()}`, {
      method: "PUT",
      body: JSON.stringify({ cycle: true }),
    });
    mergeDayResponse(result);
    renderCalendar();
    renderPanel();
    const type = result.day?.type;
    const label =
      type === "training"
        ? "IN"
        : type === "regen"
          ? "REGEN"
          : type === "preseason"
            ? "PRE-SEASON"
            : type
              ? String(type).toUpperCase()
              : null;
    els.statusBar.textContent = label
      ? `${formatLongDate(dateKey)} → ${label}`
      : `${formatLongDate(dateKey)} cleared`;
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    state.saving = false;
  }
}

async function toggleRecruitment(dateKey) {
  state.saving = true;
  els.statusBar.textContent = "Updating recruitment…";
  try {
    const result = await fetchJson(`/api/schedule/day/${dateKey}?${ownerQuery()}`, {
      method: "PUT",
      body: JSON.stringify({ toggle_recruitment: true }),
    });
    mergeDayResponse(result);
    renderCalendar();
    renderPanel();
    els.statusBar.textContent = result.day?.recruitment_in
      ? `${formatLongDate(dateKey)} · R on`
      : `${formatLongDate(dateKey)} · R off`;
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    state.saving = false;
  }
}

async function togglePreseason(dateKey) {
  state.saving = true;
  els.statusBar.textContent = "Updating pre-season…";
  try {
    const result = await fetchJson(`/api/schedule/day/${dateKey}?${ownerQuery()}`, {
      method: "PUT",
      body: JSON.stringify({ toggle_preseason: true }),
    });
    mergeDayResponse(result);
    renderCalendar();
    renderPanel();
    els.statusBar.textContent = result.day?.type === "preseason"
      ? `${formatLongDate(dateKey)} → PRE-SEASON`
      : `${formatLongDate(dateKey)} cleared`;
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    state.saving = false;
  }
}

async function setDayType(dateKey, type, reportTime = null) {
  state.saving = true;
  els.statusBar.textContent = "Saving day…";
  try {
    const body = { type };
    if (type === "training") {
      body.report_time = reportTime || reportTimeFor(dateKey) || DEFAULT_REPORT_TIME;
    }
    const result = await fetchJson(`/api/schedule/day/${dateKey}?${ownerQuery()}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    mergeDayResponse(result);
    renderCalendar();
    renderPanel();
    els.statusBar.textContent = "Day saved.";
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    state.saving = false;
  }
}

async function addEvent(payload) {
  state.saving = true;
  els.statusBar.textContent = "Adding note…";
  try {
    const result = await fetchJson("/api/schedule/events", {
      method: "POST",
      body: JSON.stringify({ ...payload, owner: state.owner }),
    });
    mergeEventsResponse(result);
    renderCalendar();
    renderPanel();
    els.statusBar.textContent = "Note added.";
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    state.saving = false;
  }
}

async function removeEvent(eventId) {
  if (!eventId) return;
  state.saving = true;
  els.statusBar.textContent = "Removing note…";
  try {
    const result = await fetchJson(`/api/schedule/events/${eventId}?${ownerQuery()}`, {
      method: "DELETE",
    });
    mergeEventsResponse(result);
    renderCalendar();
    renderPanel();
    els.statusBar.textContent = "Note removed.";
  } catch (error) {
    els.statusBar.textContent = error.message;
  } finally {
    state.saving = false;
  }
}

async function loadSchedule({ refresh = false } = {}) {
  state.loading = true;
  els.statusBar.textContent = refresh ? "Refreshing FotMob fixtures…" : "Loading schedule…";
  try {
    const params = new URLSearchParams({ owner: state.owner });
    if (refresh) params.set("refresh", "true");
    state.payload = await fetchJson(`/api/schedule?${params}`);
    if (state.payload?.owner) state.owner = state.payload.owner;
    if (!state.monthKey) state.monthKey = monthKeyFromDate(todayKey());
    if (!state.selectedDate) state.selectedDate = todayKey();
    if (els.seasonLabel) els.seasonLabel.textContent = "26/27 season · fixtures from FotMob";
    renderOwnerToggle();
    renderCalendar();
    renderPanel();
    const counts = state.payload.fixture_counts || {};
    const ownerLabel =
      (state.payload.owners || DEFAULT_OWNERS).find((row) => row.id === state.owner)?.label || "Team";
    els.statusBar.textContent = `${ownerLabel} · ${counts.total || 0} Port Vale fixtures loaded`;
  } catch (error) {
    els.statusBar.textContent = error.message;
    els.calendarRoot.innerHTML = `<div style="padding:1rem">${escapeHtml(error.message)}</div>`;
  } finally {
    state.loading = false;
    renderOwnerToggle();
  }
}

function init() {
  state.monthKey = monthKeyFromDate(todayKey());
  state.selectedDate = todayKey();
  els.prevMonthBtn?.addEventListener("click", () => {
    state.monthKey = shiftMonth(state.monthKey, -1);
    renderCalendar();
  });
  els.nextMonthBtn?.addEventListener("click", () => {
    state.monthKey = shiftMonth(state.monthKey, 1);
    renderCalendar();
  });
  els.todayBtn?.addEventListener("click", () => {
    state.monthKey = monthKeyFromDate(todayKey());
    state.selectedDate = todayKey();
    renderCalendar();
    renderPanel();
  });
  els.refreshBtn?.addEventListener("click", () => loadSchedule({ refresh: true }));
  loadSchedule();
}

init();
