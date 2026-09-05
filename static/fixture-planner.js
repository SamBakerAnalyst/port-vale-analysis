const DEFAULT_SEASON = "26/27";
const ALLOWED_SEASONS = ["26/27", "25/26"];
const ASSIGNMENTS_KEY = "fixture-planner-assignments-v1";
/** @type {"upcoming"|"played"} */
const APP_MODE = window.FIXTURE_PLANNER_MODE === "played" ? "played" : "upcoming";
const IS_PLAYED_APP = APP_MODE === "played";

const state = {
  meta: null,
  payload: null,
  season: DEFAULT_SEASON,
  leagues: [],
  /** @type {"leagues"|"germany"|"cups"|"all"} */
  compScope: "leagues",
  cupsMode: false,
  savedLeagueSelection: null,
  savedGermanySelection: null,
  savedCupSelection: null,
  savedAllSelection: null,
  expandedFixtureIds: {},
  staffFilter: "",
  monthFilter: "",
  view: "list",
  hidePast: !IS_PLAYED_APP,
  playedOnly: IS_PLAYED_APP,
  loading: false,
  assignments: {},
  enrichment: {},
  enrichmentPending: {},
  scoutingReportsByFixture: {},
  assignModal: null,
  matchDetailsFixtureId: null,
  teamNames: [],
  teamEntries: [],
  teamNamesLoaded: false,
};

const leagueColors = {
  "League One": "#3d8bfd",
  "League Two": "#34d399",
  "National League": "#fbbf24",
  "Scottish Prem": "#a78bfa",
  PL2: "#f97316",
  "Irish Prem": "#22d3ee",
  "Professional Development League": "#14b8a6",
  Bundesliga: "#e11d48",
  "2. Bundesliga": "#94a3b8",
  Manual: "#f472b6",
  "FA Cup": "#ef4444",
  "EFL Cup": "#fb923c",
  "EFL Trophy": "#eab308",
  "Vertu Trophy": "#eab308",
  "National League Cup": "#84cc16",
  "Premier League Cup": "#a855f7",
  "Scottish Cup": "#38bdf8",
  Cups: "#f43f5e",
};

const els = {
  seasonToggle: document.getElementById("seasonToggle"),
  leagueToggle: document.getElementById("leagueToggle"),
  staffFilter: document.getElementById("staffFilter"),
  monthFilter: document.getElementById("monthFilter"),
  summaryPanel: document.getElementById("summaryPanel"),
  calendarRoot: document.getElementById("calendarRoot"),
  listRoot: document.getElementById("listRoot"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  ticketRequestBtn: document.getElementById("ticketRequestBtn"),
  scheduleUpdateBtn: document.getElementById("scheduleUpdateBtn"),
  ticketModal: document.getElementById("ticketModal"),
  ticketModalTitle: document.getElementById("ticketModalTitle"),
  ticketModalMeta: document.getElementById("ticketModalMeta"),
  ticketModalBody: document.getElementById("ticketModalBody"),
  ticketAdditionalRequests: document.getElementById("ticketAdditionalRequests"),
  ticketModalStatus: document.getElementById("ticketModalStatus"),
  ticketConfirmBtn: document.getElementById("ticketConfirmBtn"),
  pageSubtitle: document.getElementById("pageSubtitle"),
  hidePastToggle: document.getElementById("hidePastToggle"),
  coveragePanel: document.getElementById("coveragePanel"),
  assignModal: document.getElementById("assignModal"),
  assignModalTitle: document.getElementById("assignModalTitle"),
  assignModalMeta: document.getElementById("assignModalMeta"),
  assignModalStaff: document.getElementById("assignModalStaff"),
  assignModalWatch: document.getElementById("assignModalWatch"),
  assignModalBody: document.getElementById("assignModalBody"),
  assignConfirmBtn: document.getElementById("assignConfirmBtn"),
  matchDetailsModal: document.getElementById("matchDetailsModal"),
  matchDetailsTitle: document.getElementById("matchDetailsTitle"),
  matchDetailsMeta: document.getElementById("matchDetailsMeta"),
  matchDetailsBody: document.getElementById("matchDetailsBody"),
  createManualFixtureBtn: document.getElementById("createManualFixtureBtn"),
  manualFixtureModal: document.getElementById("manualFixtureModal"),
  manualFixtureForm: document.getElementById("manualFixtureForm"),
  manualFixtureSaveBtn: document.getElementById("manualFixtureSaveBtn"),
  manualPlayersList: document.getElementById("manualPlayersList"),
  manualAddPlayerBtn: document.getElementById("manualAddPlayerBtn"),
  manualStaff: document.getElementById("manualStaff"),
  manualStaffTeams: document.getElementById("manualStaffTeams"),
  manualTeamSheet: document.getElementById("manualTeamSheet"),
};

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `fp-status fp-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    cache: "no-store",
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

function downloadEmlFile(data) {
  const raw = String(data?.eml_base64 || "").trim();
  if (!raw) return false;
  try {
    const binary = atob(raw);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: "message/rfc822" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = data.eml_filename || "ticket-request.eml";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return true;
  } catch {
    return false;
  }
}

function fixtureFromState(id) {
  return (state.payload?.fixtures || []).find((row) => fixtureId(row) === id);
}

async function loadAssignmentsFromServer() {
  try {
    const data = await fetchJson("/api/fixture-planner/assignments");
    // Always trust the server store — including an empty wipe.
    state.assignments = data.assignments || {};
    localStorage.setItem(ASSIGNMENTS_KEY, JSON.stringify(state.assignments));
    return;
  } catch {
    // fall back to local cache below
  }

  loadAssignments();
}

function loadAssignments() {
  try {
    state.assignments = JSON.parse(localStorage.getItem(ASSIGNMENTS_KEY) || "{}");
  } catch {
    state.assignments = {};
  }
}

async function setFixturePostponed(fixtureId, postponed) {
  const fixture = fixtureFromState(fixtureId);
  const status = postponed ? "postponed" : "scheduled";
  try {
    await fetchJson("/api/fixture-planner/fixture-status", {
      method: "PATCH",
      body: JSON.stringify({ fixture_id: fixtureId, status }),
    });
    if (fixture) {
      fixture.status = status;
      fixture.postponed = postponed;
    }
    els.statusBar.textContent = postponed
      ? `Marked ${fixtureTeams(fixture || { home: { name: "" }, away: { name: "" } })} as postponed`
      : "Fixture restored to scheduled";
    renderView({ preserveScroll: true });
  } catch (error) {
    els.statusBar.textContent = error.message;
  }
}

function saveAssignments() {
  localStorage.setItem(ASSIGNMENTS_KEY, JSON.stringify(state.assignments));
}

let persistTimer = null;

function enrichAssignment(id) {
  const fixture = fixtureFromState(id);
  if (!state.assignments[id] || !fixture) return;
  state.assignments[id] = {
    ...state.assignments[id],
    season: state.season,
    league: fixture.league || "",
    home: fixture.home?.name || "",
    away: fixture.away?.name || "",
    date: fixtureDateKey(fixture),
    kickoff_utc: fixture.kickoff_utc || fixture.scheduled_date || null,
  };
}

async function flushPersistQueue() {
  // Avoid bulk PUT of in-memory state — that can resurrect assignments
  // deleted from Scout Summary in another tab. Retry individually instead.
  const ids = Object.keys(state.assignments || {});
  for (const id of ids) {
    try {
      await persistAssignment(id);
    } catch (error) {
      console.warn("Could not sync assignment", id, error);
    }
  }
}

function schedulePersist() {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(flushPersistQueue, 400);
}

function assignmentFor(fixtureId) {
  const row = state.assignments[fixtureId] || { staff: [], watch_type: "" };
  return {
    ...row,
    staff: staffNames(row.staff),
  };
}

function staffNames(value) {
  if (Array.isArray(value)) {
    return value.flatMap((item) => staffNames(item));
  }
  if (value && typeof value === "object") {
    return staffNames(value.name || value.staff || value.label || "");
  }
  const single = String(value || "").trim();
  return single ? [single] : [];
}

function staffLabel(value) {
  return staffNames(value).join(", ");
}

function hasStaff(value) {
  return staffNames(value).length > 0;
}

function primaryStaff(value) {
  return staffNames(value)[0] || "";
}

function assignmentSummaryText(id) {
  const assignment = assignmentFor(id);
  const assigned = staffNames(assignment.staff);
  const summaryBits = [];
  if (assigned.length) summaryBits.push(staffLabel(assigned));
  if (assignment.watch_type) summaryBits.push(assignment.watch_type);
  return summaryBits.length ? summaryBits.join(" · ") : "Click to assign staff";
}

function fixtureCardElement(id) {
  if (!els.listRoot || !id) return null;
  return els.listRoot.querySelector(`[data-fixture-card="${CSS.escape(id)}"]`);
}

function toggleAssignmentPanel(card, open) {
  if (!card) return;
  card.classList.toggle("fp-list-fixture--expanded", open);
  const assignment = card.querySelector(".fp-assignment");
  assignment?.classList.toggle("fp-assignment--open", open);
  const toggle = card.querySelector("[data-assign-toggle]");
  if (toggle) {
    toggle.classList.toggle("fp-assign-toggle--open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    const label = toggle.querySelector(".fp-assign-toggle__label");
    if (label) {
      label.textContent = open ? "Hide assign options" : assignmentSummaryText(card.dataset.fixtureCard);
    }
    const chevron = toggle.querySelector(".fp-assign-toggle__chevron");
    if (chevron) chevron.textContent = open ? "▴" : "▾";
  }
  card.querySelector(".fp-assignment__panel")?.classList.toggle("fp-assignment__panel--hidden", !open);
}

function refreshFixtureAssignmentCard(id) {
  const card = fixtureCardElement(id);
  const fixture = fixtureFromState(id);
  if (!card || !fixture) {
    renderView({ preserveScroll: true, scrollAnchorId: id });
    return;
  }

  const assignment = assignmentFor(id);
  const assigned = staffNames(assignment.staff);
  const hasCoverage = assigned.length > 0 || Boolean(assignment.watch_type);
  const expanded = Boolean(state.expandedFixtureIds[id]);

  const head = card.querySelector(".fp-list-fixture__head");
  if (head) head.innerHTML = assignmentBadge(fixture);

  const toggle = card.querySelector("[data-assign-toggle]");
  if (toggle) {
    toggle.classList.toggle("fp-assign-toggle--set", hasCoverage);
    if (!expanded) {
      const label = toggle.querySelector(".fp-assign-toggle__label");
      if (label) label.textContent = assignmentSummaryText(id);
    }
  }

  card.querySelectorAll(".fp-staff-select").forEach((select) => {
    const teamMembers = [...select.options].map((opt) => opt.value).filter(Boolean);
    const selected = teamMembers.find((name) => assigned.includes(name)) || "";
    select.value = selected;
  });

  card.querySelectorAll(".fp-watch-btn").forEach((btn) => {
    btn.classList.toggle("fp-watch-btn--active", assignment.watch_type === btn.dataset.watch);
  });

  const panel = card.querySelector(".fp-assignment__panel");
  if (panel) {
    let editBtn = panel.querySelector(".fp-assign-edit");
    if (assigned.length) {
      if (!editBtn) {
        const watchToggle = panel.querySelector(".fp-watch-toggle");
        watchToggle?.insertAdjacentHTML(
          "afterend",
          `<button type="button" class="fp-btn fp-btn--ghost fp-assign-edit" data-fixture-id="${escapeHtml(id)}" data-staff="${escapeHtml(primaryStaff(assigned))}">Players</button>`,
        );
        editBtn = panel.querySelector(".fp-assign-edit");
        editBtn?.addEventListener("click", () => {
          const current = assignmentFor(id);
          openAssignModal(id, editBtn.dataset.staff || primaryStaff(current.staff), staffNames(current.staff));
        });
      } else {
        editBtn.dataset.staff = primaryStaff(assigned);
      }
    } else {
      editBtn?.remove();
    }
  }

  if (!card.querySelector(".fp-assignment")) {
    const slot = card.querySelector("[data-assignment-slot]");
    if (slot) {
      slot.innerHTML = assignmentControls(fixture, { expanded });
      bindAssignmentEvents(slot);
    }
  }
}

function setAssignment(id, patch) {
  const current = assignmentFor(id);
  const next = {
    ...current,
    ...patch,
    staff: staffNames(patch.staff !== undefined ? patch.staff : current.staff),
  };
  if (!hasStaff(next.staff) && !next.watch_type) {
    delete state.assignments[id];
  } else {
    state.assignments[id] = next;
    enrichAssignment(id);
  }
  saveAssignments();
  renderSummary();
  refreshFixtureAssignmentCard(id);
  persistAssignment(id);
}

async function persistAssignment(id) {
  const assignment = state.assignments[id];
  const fixture = fixtureFromState(id);
  const body = assignment
    ? {
        fixture_id: id,
        staff: staffNames(assignment.staff),
        watch_type: assignment.watch_type || "",
        season: assignment.season || state.season || "",
        league: assignment.league || fixture?.league || "",
        home: assignment.home || fixture?.home?.name || "",
        away: assignment.away || fixture?.away?.name || "",
        date: assignment.date || fixtureDateKey(fixture) || "",
        kickoff_utc: assignment.kickoff_utc || fixture?.kickoff_utc || fixture?.scheduled_date || null,
        watched_players: assignment.watched_players || [],
      }
    : {
        fixture_id: id,
        staff: [],
        watch_type: "",
        watched_players: [],
      };

  try {
    const data = await fetchJson("/api/fixture-planner/assignment", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    if (data.assignments) {
      state.assignments = data.assignments;
      saveAssignments();
    }
    if (data.email?.sent) {
      setStatus(`Assignment saved · email sent to ${data.email.to}`, "ok");
    } else if (data.email && !data.email.sent) {
      const reason = data.email.reason || "Email not sent";
      setStatus(`Assignment saved · email not sent: ${reason}`, "error");
    }
  } catch (error) {
    console.warn("Could not persist assignment", error);
    setStatus(error.message || "Could not save assignment", "error");
    schedulePersist();
  }
}

async function sendBulkEmail(kind) {
  if (kind === "ticket-request") {
    openTicketRequestModal();
    return;
  }

  if (!window.confirm("Email coaching + recruitment with the next fortnight of assigned fixtures?")) {
    return;
  }

  const btn = els.scheduleUpdateBtn;
  if (btn) btn.disabled = true;
  setStatus("Sending fortnight schedule update…", "loading");

  try {
    const data = await fetchJson("/api/fixture-planner/email/schedule-update", {
      method: "POST",
      body: "{}",
    });
    if (data.sent) {
      const to = Array.isArray(data.to) ? data.to.join(", ") : data.to || "recipients";
      setStatus(`Schedule update sent to ${to} · ${data.fixture_count || 0} fixture(s)`, "ok");
    } else {
      setStatus(data.reason || "Email not sent", "error");
    }
  } catch (error) {
    setStatus(error.message || "Could not send email", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function setTicketModalStatus(message, kind = "") {
  const el = els.ticketModalStatus;
  if (!el) return;
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    el.className = "fp-ticket-modal__status";
    return;
  }
  el.hidden = false;
  el.textContent = message;
  el.className = `fp-ticket-modal__status${kind ? ` fp-ticket-modal__status--${kind}` : ""}`;
}

function closeTicketRequestModal() {
  if (!els.ticketModal) return;
  els.ticketModal.classList.add("fp-assign-modal--hidden");
  els.ticketModal.setAttribute("aria-hidden", "true");
  setTicketModalStatus("");
  if (els.ticketConfirmBtn) els.ticketConfirmBtn.textContent = "Send to admin";
}

function syncTicketRequestUi() {
  const count = els.ticketModalBody?.querySelectorAll(".fp-ticket-card").length || 0;
  if (els.ticketConfirmBtn) els.ticketConfirmBtn.disabled = count === 0;
  if (els.ticketModalTitle) {
    els.ticketModalTitle.textContent =
      count > 0
        ? `${count} live fixture${count === 1 ? "" : "s"} in this email`
        : "No fixtures in this email";
  }
  const list = els.ticketModalBody?.querySelector(".fp-ticket-list");
  if (count === 0 && list && !list.querySelector(".fp-ticket-modal__empty")) {
    list.innerHTML =
      '<p class="fp-ticket-modal__empty">All fixtures removed. Close and reopen the modal to load them again.</p>';
  }
}

function renderTicketRequestRows(fixtures, alreadyRequested = []) {
  if (!els.ticketModalBody) return;
  if (!fixtures.length && !alreadyRequested.length) {
    els.ticketModalBody.innerHTML = `<p class="fp-assign-modal__empty">No LIVE fixtures assigned in the next two weeks. Assign someone as LIVE first.</p>`;
    if (els.ticketConfirmBtn) els.ticketConfirmBtn.disabled = true;
    return;
  }
  if (!fixtures.length) {
    els.ticketModalBody.innerHTML = `
      <p class="fp-assign-modal__empty">All LIVE fixtures in the next two weeks have already been requested.</p>
      ${renderAlreadyRequestedTickets(alreadyRequested)}
    `;
    if (els.ticketConfirmBtn) els.ticketConfirmBtn.disabled = true;
    return;
  }
  if (els.ticketConfirmBtn) els.ticketConfirmBtn.disabled = false;
  els.ticketModalBody.innerHTML = `
    <p class="fp-ticket-modal__hint">New requests for the next two weeks only. Click × to leave a game out of this email.</p>
    <div class="fp-ticket-list">
      ${fixtures
        .map((row) => {
          const id = escapeHtml(row.fixture_id || "");
          const match = `${row.home || "Home"} vs ${row.away || "Away"}`;
          return `
            <article class="fp-ticket-card" data-fixture-id="${id}">
              <div class="fp-ticket-card__head">
                <div class="fp-ticket-card__main">
                  <strong class="fp-ticket-card__match">${escapeHtml(match)}</strong>
                  <span class="fp-ticket-card__meta">${escapeHtml(row.league || "")} · ${escapeHtml(row.kickoff_label || row.date || "TBC")} · ${escapeHtml(staffLabel(row.staff) || "TBC")}</span>
                </div>
                <button type="button" class="fp-ticket-card__remove" data-ticket-remove aria-label="Remove ${escapeHtml(match)} from email">×</button>
              </div>
              <div class="fp-ticket-card__fields">
                <label class="fp-ticket-field">
                  <span>Tickets</span>
                  <input type="number" min="0" step="1" value="1" data-ticket-qty />
                </label>
                <label class="fp-ticket-field">
                  <span>Parking</span>
                  <select data-ticket-parking>
                    <option value="No">No</option>
                    <option value="Yes">Yes</option>
                    <option value="Yes — 1 space">Yes — 1 space</option>
                    <option value="Yes — 2 spaces">Yes — 2 spaces</option>
                  </select>
                </label>
                <label class="fp-ticket-field fp-ticket-field--notes">
                  <span>Notes</span>
                  <input type="text" placeholder="Optional for this game" data-ticket-notes />
                </label>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
    ${renderAlreadyRequestedTickets(alreadyRequested)}
  `;
  syncTicketRequestUi();
}

function renderAlreadyRequestedTickets(rows) {
  if (!rows?.length) return "";
  return `
    <div class="fp-ticket-already">
      <h3 class="fp-ticket-already__title">Already requested (${rows.length})</h3>
      <ul class="fp-ticket-already__list">
        ${rows
          .map((row) => {
            const match = `${row.home || "Home"} vs ${row.away || "Away"}`;
            return `<li><strong>${escapeHtml(match)}</strong> · ${escapeHtml(row.kickoff_label || row.date || "TBC")} · ${escapeHtml(staffLabel(row.staff) || "TBC")}</li>`;
          })
          .join("")}
      </ul>
    </div>
  `;
}

async function openTicketRequestModal() {
  if (!els.ticketModal) return;
  els.ticketModal.classList.remove("fp-assign-modal--hidden");
  els.ticketModal.setAttribute("aria-hidden", "false");
  if (els.ticketModalBody) {
    els.ticketModalBody.innerHTML = `<p class="fp-assign-modal__loading">Loading next two weeks of LIVE fixtures…</p>`;
  }
  if (els.ticketAdditionalRequests) els.ticketAdditionalRequests.value = "";
  if (els.ticketConfirmBtn) els.ticketConfirmBtn.disabled = true;
  if (els.ticketModalMeta) els.ticketModalMeta.textContent = "Fetching LIVE assignments…";
  if (els.ticketModalTitle) els.ticketModalTitle.textContent = "Next two weeks · ticket requests";
  setTicketModalStatus("");

  try {
    const data = await fetchJson("/api/fixture-planner/email/ticket-request");
    const recipients = (data.recipients || []).join(", ") || "No admin recipients configured";
    const newCount = data.fixture_count || (data.fixtures || []).length || 0;
    const doneCount = data.already_requested_count || (data.already_requested || []).length || 0;
    if (els.ticketModalMeta) {
      els.ticketModalMeta.textContent = `${data.period_label || "Next two weeks"} · ${newCount} new · ${doneCount} already sent · To: ${recipients}`;
    }
    if (els.ticketModalTitle) {
      els.ticketModalTitle.textContent =
        newCount > 0
          ? `${newCount} new live fixture${newCount === 1 ? "" : "s"} needing tickets`
          : "No new ticket requests";
    }
    renderTicketRequestRows(data.fixtures || [], data.already_requested || []);
  } catch (error) {
    if (els.ticketModalBody) {
      els.ticketModalBody.innerHTML = `<p class="fp-assign-modal__empty">${escapeHtml(error.message || "Could not load fixtures.")}</p>`;
    }
  }
}

function collectTicketRequestPayload() {
  const fixtures = [...(els.ticketModalBody?.querySelectorAll(".fp-ticket-card") || [])].map((card) => ({
    fixture_id: card.dataset.fixtureId || "",
    tickets: Number(card.querySelector("[data-ticket-qty]")?.value || 1),
    parking: card.querySelector("[data-ticket-parking]")?.value || "No",
    notes: card.querySelector("[data-ticket-notes]")?.value || "",
  }));
  return {
    fixtures,
    additional_requests: els.ticketAdditionalRequests?.value || "",
  };
}

async function confirmTicketRequest() {
  const payload = collectTicketRequestPayload();
  if (!payload.fixtures.length) {
    setTicketModalStatus("No LIVE fixtures to send", "error");
    setStatus("No LIVE fixtures to send", "error");
    return;
  }
  if (els.ticketConfirmBtn) {
    els.ticketConfirmBtn.disabled = true;
    els.ticketConfirmBtn.textContent = "Sending…";
  }
  setTicketModalStatus("Sending ticket request to admin…", "loading");
  setStatus("Sending ticket request to admin…", "loading");
  try {
    const data = await fetchJson("/api/fixture-planner/email/ticket-request", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.sent) {
      const to = Array.isArray(data.to) ? data.to.join(", ") : data.to || "recipients";
      const message = `Ticket request sent to ${to} · ${data.fixture_count || 0} new fixture(s)`;
      setTicketModalStatus(message, "ok");
      setStatus(message, "ok");
      closeTicketRequestModal();
    } else {
      const reason = data.reason || "Email not sent";
      setTicketModalStatus(reason, "error");
      setStatus(reason, "error");
    }
  } catch (error) {
    const message = error.message || "Could not send email";
    setTicketModalStatus(message, "error");
    setStatus(message, "error");
  } finally {
    if (els.ticketConfirmBtn) {
      els.ticketConfirmBtn.disabled = false;
      els.ticketConfirmBtn.textContent = "Send to admin";
    }
  }
}

function isPlaceholderKickoff(iso, fixture) {
  const token = String(iso || "").trim();
  if (!token || !token.includes("T")) return true;
  const stamp = new Date(token);
  if (Number.isNaN(stamp.getTime())) return true;
  const hour = stamp.getUTCHours();
  const minute = stamp.getUTCMinutes();
  const day = stamp.getUTCDay(); // 0 Sun … 6 Sat
  if (minute === 0 && (hour === 0 || hour === 22 || hour === 23)) return true;
  const isCup = Boolean(fixture?.cup) || isCupCompetition(fixture?.league);
  // League 15:00 UK (14:00Z in summer) is a real KO — Bank Holiday Monday especially.
  if (fixture && !isCup) return false;
  // Tue–Fri midday UTC dumps from FotMob on cups (14:00Z → 15:00 UK in summer).
  if (day >= 2 && day <= 5 && minute === 0 && hour >= 12 && hour <= 14) return true;
  return false;
}

function formatTime(iso, fixture) {
  if (fixture?.kickoff_tbc || isPlaceholderKickoff(iso, fixture)) return "TBC";
  if (!iso) return "TBC";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Europe/London",
  });
}

function formatFixtureKickoff(fixture) {
  return formatTime(fixture?.kickoff_utc || fixture?.scheduled_date, fixture);
}

function formatDateLabel(dateKey) {
  if (!dateKey) return "Unknown date";
  const date = new Date(`${dateKey}T12:00:00`);
  return date.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
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

function fixtureDateKey(fixture) {
  const iso = fixture.kickoff_utc || fixture.scheduled_date || "";
  if (iso && String(iso).includes("T")) {
    try {
      return new Intl.DateTimeFormat("en-CA", {
        timeZone: "Europe/London",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date(iso));
    } catch (_err) {
      /* fall through */
    }
  }
  return fixture.date || String(iso || "").slice(0, 10);
}

function footballWeekendKey(dateKey) {
  if (!dateKey) return "";
  const date = new Date(`${dateKey}T12:00:00`);
  const day = date.getDay();
  const saturday = new Date(date);
  if (day === 6) {
    // Saturday anchor
  } else if (day === 0) {
    saturday.setDate(date.getDate() - 1);
  } else if (day === 5) {
    saturday.setDate(date.getDate() + 1);
  } else if (day === 1) {
    saturday.setDate(date.getDate() - 2);
  } else {
    return dateKey;
  }
  const year = saturday.getFullYear();
  const month = String(saturday.getMonth() + 1).padStart(2, "0");
  const dayNum = String(saturday.getDate()).padStart(2, "0");
  return `${year}-${month}-${dayNum}`;
}

function formatMonthLabel(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return date.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isCompletedFixture(fixture) {
  if (String(fixture?.status || "").toLowerCase() === "completed") return true;
  if (fixture?.manual && String(fixture?.status || "").toLowerCase() === "scheduled") return false;
  if (fixture?.manual && fixture?.score) return true;
  return false;
}

function isPostponedFixture(fixture) {
  return String(fixture?.status || "").toLowerCase() === "postponed" || Boolean(fixture?.postponed);
}

function isManualFixture(fixture) {
  return Boolean(fixture?.manual) || String(fixtureId(fixture) || "").startsWith("manual|");
}

function reportedPlayerIdsForFixture(fixtureIdValue) {
  const bucket = state.scoutingReportsByFixture[fixtureIdValue] || {};
  return new Set(
    Object.values(bucket)
      .map((row) => String(row?.player_id || ""))
      .filter(Boolean),
  );
}

function playerSurname(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return (parts[parts.length - 1] || name || "").toUpperCase();
}

function playerInitials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] || ""}${parts[parts.length - 1][0] || ""}`.toUpperCase();
}

function isGoalkeeper(player) {
  const position = String(player?.position_code || player?.position || "").toUpperCase();
  return position === "GOALKEEPER" || position === "GK";
}

function playerPhotoUrl(player) {
  if (player?.photo_url) return player.photo_url;
  const name = String(player?.name || "").trim();
  if (!name) return null;
  return `/api/player-photo?name=${encodeURIComponent(name)}`;
}

function playerPhotoMarkup(player) {
  const name = String(player?.name || "");
  const photoUrl = playerPhotoUrl(player);
  const shirt = player?.shirt_number ?? "";
  if (photoUrl) {
    return `<img class="so-pitch-player__img" src="${escapeHtml(photoUrl)}" alt="${escapeHtml(name)}" loading="lazy" onerror="this.closest('.so-pitch-player__face').classList.add('so-pitch-player__face--fallback'); this.remove();" />`;
  }
  return `<span class="so-pitch-player__initials">${escapeHtml(String(shirt || playerInitials(name)))}</span>`;
}

function teamCrestMarkup(team) {
  const name = String(team?.name || "?");
  const src = team?.image_url || team?.imageUrl || "";
  if (src) {
    return `<img class="so-match-team__crest" src="${escapeHtml(src)}" alt="" loading="lazy" />`;
  }
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return `<span class="so-match-team__crest so-match-team__crest--fallback">${escapeHtml(initials)}</span>`;
}

function pitchPlayerMarkup(player, index, { fixtureId, side }) {
  let left = Number(player.x_pct ?? 50);
  let top = Number(player.y_pct ?? 50);
  left = Math.max(14, Math.min(86, left));
  const goalkeeper = isGoalkeeper(player);
  if (goalkeeper) {
    top = Math.min(top, 80);
  } else if (top <= 16) {
    top = 12;
  } else {
    top = Math.max(12, Math.min(86, top));
  }
  const shirt = player.shirt_number ? String(player.shirt_number) : "";
  const reported = reportedPlayerIdsForFixture(fixtureId).has(String(player.player_id || ""));
  const pxt =
    player.pxt != null
      ? `<span class="so-pitch-player__pxt${player.pxt < 0 ? " so-pitch-player__pxt--neg" : ""}">${player.pxt}</span>`
      : `<span class="so-pitch-player__pxt so-pitch-player__pxt--na">—</span>`;
  const title = [player.name, player.position, player.pxt != null ? `PXT ${player.pxt}` : ""]
    .filter(Boolean)
    .join(" · ");
  return `<button type="button" class="so-pitch-player${reported ? " so-pitch-player--reported" : ""}" style="left:${left}%;top:${top}%;z-index:${index + 1}" title="${escapeHtml(title)}" data-player-id="${player.player_id}" data-side="${escapeHtml(side)}" data-player-name="${escapeHtml(player.name || "")}" data-position="${escapeHtml(player.position_code || player.position || "")}" aria-pressed="${reported ? "true" : "false"}">
    <div class="so-pitch-player__face${goalkeeper ? " so-pitch-player__face--gk" : ""}">${playerPhotoMarkup(player)}</div>
    <div class="so-pitch-player__card">
      ${shirt ? `<span class="so-pitch-player__shirt">${escapeHtml(shirt)}</span>` : ""}
      <span class="so-pitch-player__name">${escapeHtml(playerSurname(player.name))}</span>
      ${pxt}
    </div>
  </button>`;
}

function renderSquadTable(players, { fixtureId, side }) {
  const reported = reportedPlayerIdsForFixture(fixtureId);
  const rows = [...players].sort((a, b) => {
    const aPxt = a.pxt ?? -999;
    const bPxt = b.pxt ?? -999;
    return bPxt - aPxt;
  });
  return `
    <div class="so-match-team__squad">
      <div class="so-match-team__squad-head">
        <span>#</span>
        <span>Player</span>
        <span>Pos</span>
        <span>PXT</span>
      </div>
      ${rows
        .map((player) => {
          const pxtClass =
            player.pxt == null
              ? "so-match-team__pxt-val--na"
              : player.pxt < 0
                ? "so-match-team__pxt-val--neg"
                : "";
          const isReported = reported.has(String(player.player_id || ""));
          return `<div class="so-match-team__squad-row${isReported ? " so-match-team__squad-row--reported" : ""}" role="button" tabindex="0" data-player-id="${player.player_id}" data-side="${escapeHtml(side)}" data-player-name="${escapeHtml(player.name || "")}" data-position="${escapeHtml(player.position_code || player.position || "")}" aria-pressed="${isReported ? "true" : "false"}">
            <span class="so-match-team__num">${escapeHtml(String(player.shirt_number || "—"))}</span>
            <span class="so-match-team__player">${escapeHtml(player.name || "")}</span>
            <span class="so-match-team__pos">${escapeHtml(player.position || "—")}</span>
            <span class="so-match-team__pxt-val ${pxtClass}">${player.pxt != null ? player.pxt : "—"}</span>
          </div>`;
        })
        .join("")}
    </div>
  `;
}

function renderFormationPitch(sideLabel, team, lineup, teamPxt, { fixtureId, side }) {
  const players = lineup?.players || [];
  if (!players.length) {
    return `<section class="so-match-team"><p class="so-match-team__empty">Lineup not available.</p></section>`;
  }
  const formation = lineup.formation ? lineup.formation : "";
  const pxtLabel = teamPxt != null ? `<span class="so-match-team__pxt">Team PXT ${teamPxt}</span>` : "";
  const markers = players
    .map((player, index) => pitchPlayerMarkup(player, index, { fixtureId, side }))
    .join("");
  return `
    <section class="so-match-team" data-side="${escapeHtml(side)}">
      <header class="so-match-team__head">
        ${teamCrestMarkup(team)}
        <div class="so-match-team__titles">
          <h3 class="so-match-team__name">${escapeHtml(sideLabel)}</h3>
          <div class="so-match-team__sub">
            ${formation ? `<span class="so-match-team__formation">${escapeHtml(formation)}</span>` : ""}
            ${pxtLabel}
          </div>
        </div>
      </header>
      <div class="so-match-pitch">
        <div class="so-match-pitch__markings"></div>
        ${markers}
      </div>
      <details class="so-match-team__details" open>
        <summary class="so-match-team__details-summary">Full squad &amp; PXT</summary>
        ${renderSquadTable(players, { fixtureId, side })}
      </details>
    </section>
  `;
}

function renderEnrichmentBody(fixture, enrich) {
  if (!enrich) {
    return `<p class="fp-fixture-enrich__hint">Venue, PXT ratings and lineups will load here.</p>`;
  }
  const id = fixtureId(fixture);
  const homeName = fixture.home?.name || enrich.home_team?.name || "Home";
  const awayName = fixture.away?.name || enrich.away_team?.name || "Away";
  const homePxt = enrich.pxt?.home;
  const awayPxt = enrich.pxt?.away;
  const venue = enrich.venue
    ? `<div class="so-match-modal__stat so-match-modal__stat--venue">${escapeHtml(enrich.venue)}</div>`
    : "";
  const teamPxt =
    homePxt != null || awayPxt != null
      ? `<div class="so-match-modal__stat so-match-modal__stat--pxt"><span class="so-match-modal__stat-label">Team PXT</span> <strong>${homePxt ?? "—"}</strong> <span class="so-match-modal__stat-sep">vs</span> <strong>${awayPxt ?? "—"}</strong></div>`
      : "";
  const reportedIds = reportedPlayerIdsForFixture(id);
  const reportedNames = Object.values(state.scoutingReportsByFixture[id] || {})
    .map((row) => row.player_name)
    .filter(Boolean);
  const reportedSummary = reportedNames.length
    ? `<div class="so-match-modal__reports"><span class="so-match-modal__reports-label">Reports marked (${reportedIds.size})</span> ${reportedNames
        .map((name) => `<span class="so-match-modal__report-chip">${escapeHtml(name)}</span>`)
        .join("")}</div>`
    : `<p class="so-match-modal__reports-hint">Click players on the pitch or in the squad list to mark scouting reports.</p>`;

  return `
    <div class="so-match-modal__stats">${venue}${teamPxt}</div>
    ${reportedSummary}
    <div class="so-match-modal__pitches">
      ${renderFormationPitch(homeName, enrich.home_team || fixture.home, enrich.lineups?.home, homePxt, {
        fixtureId: id,
        side: "home",
      })}
      ${renderFormationPitch(awayName, enrich.away_team || fixture.away, enrich.lineups?.away, awayPxt, {
        fixtureId: id,
        side: "away",
      })}
    </div>
  `;
}

function renderCompletedExtras(fixture) {
  if (!isCompletedFixture(fixture)) {
    return "";
  }
  const id = fixtureId(fixture);
  if (isManualFixture(fixture)) {
    const players = fixture.watched_players || [];
    const sheet = fixture.team_sheet ? " · team sheet" : "";
    const hint = [
      fixture.venue || "",
      players.length ? `${players.length} player${players.length === 1 ? "" : "s"} watched` : "No players logged",
      fixture.notes ? "notes" : "",
    ]
      .filter(Boolean)
      .join(" · ");
    return `
      <button
        type="button"
        class="fp-match-details-btn"
        data-open-match-details="${escapeHtml(id)}"
      >
        <span class="fp-match-details-btn__title">Manual match details</span>
        <span class="fp-match-details-btn__hint">${escapeHtml(hint || "Open notes & players")}${escapeHtml(sheet)}</span>
      </button>
    `;
  }
  if (!fixture.match_id) {
    return `<p class="fp-fixture-enrich__hint">Match details need Impect data for this fixture.</p>`;
  }

  const enrich = state.enrichment[id];
  const pending = state.enrichmentPending[id];
  const summaryHint = enrich
    ? [enrich.venue, enrich.pxt?.home != null ? `PXT ${enrich.pxt.home}–${enrich.pxt.away}` : ""]
        .filter(Boolean)
        .join(" · ") || "Lineups ready"
    : pending
      ? "Loading…"
      : "Open for venue, PXT, lineups & reports";

  return `
    <button
      type="button"
      class="fp-match-details-btn"
      data-open-match-details="${escapeHtml(id)}"
    >
      <span class="fp-match-details-btn__title">Match details</span>
      <span class="fp-match-details-btn__hint">${escapeHtml(summaryHint)}</span>
    </button>
  `;
}

function closeMatchDetailsModal() {
  state.matchDetailsFixtureId = null;
  if (els.matchDetailsModal) {
    els.matchDetailsModal.classList.add("fp-assign-modal--hidden");
    els.matchDetailsModal.setAttribute("aria-hidden", "true");
  }
}

function renderMatchDetailsModalBody() {
  if (!els.matchDetailsBody) return;
  const id = state.matchDetailsFixtureId;
  if (!id) {
    els.matchDetailsBody.innerHTML = "";
    return;
  }
  const fixture = fixtureFromState(id);
  if (!fixture) {
    els.matchDetailsBody.innerHTML = `<p class="fp-assign-modal__empty">Fixture not found.</p>`;
    return;
  }
  if (isManualFixture(fixture)) {
    els.matchDetailsBody.innerHTML = `<div class="fp-fixture-enrich fp-fixture-enrich--modal">${renderManualMatchBody(fixture)}</div>`;
    return;
  }
  const enrich = state.enrichment[id];
  const pending = state.enrichmentPending[id];
  if (pending && !enrich) {
    els.matchDetailsBody.innerHTML = `<p class="fp-assign-modal__loading">Loading venue, PXT &amp; lineups…</p>`;
    return;
  }
  els.matchDetailsBody.innerHTML = `<div class="fp-fixture-enrich fp-fixture-enrich--modal">${renderEnrichmentBody(fixture, enrich)}</div>`;
}

function renderManualMatchBody(fixture) {
  const players = fixture.watched_players || [];
  const assignment = assignmentFor(fixtureId(fixture));
  const venue = fixture.venue
    ? `<div class="so-match-modal__stat so-match-modal__stat--venue">${escapeHtml(fixture.venue)}</div>`
    : "";
  const score = fixture.score
    ? `<div class="so-match-modal__stat"><span class="so-match-modal__stat-label">Score</span> <strong>${escapeHtml(fixture.score)}</strong></div>`
    : "";
  const coverage =
    hasStaff(assignment.staff) || hasStaff(fixture.staff)
      ? `<div class="so-match-modal__stat"><span class="so-match-modal__stat-label">Coverage</span> <strong>${escapeHtml(assignment.watch_type || fixture.watch_type || "LIVE")}</strong> · ${escapeHtml(staffLabel(assignment.staff || fixture.staff) || "")}</div>`
      : "";
  const notes = fixture.notes
    ? `<section class="fp-manual-detail"><h3>Game notes</h3><p>${escapeHtml(fixture.notes).replace(/\n/g, "<br>")}</p></section>`
    : `<p class="fp-fixture-enrich__hint">No game notes logged.</p>`;
  const sheet = fixture.team_sheet
    ? `<p class="fp-manual-detail__sheet"><a class="fp-btn fp-btn--ghost" href="/api/fixture-planner/manual-fixtures/${encodeURIComponent(fixtureId(fixture))}/team-sheet" target="_blank" rel="noopener">Open team sheet (${escapeHtml(fixture.team_sheet.filename || "file")})</a></p>`
    : `<p class="fp-fixture-enrich__hint">No team sheet attached.</p>`;
  const playerRows = players.length
    ? `<ul class="fp-manual-detail__players">${players
        .map((player) => {
          const name = player.player_name || "Player";
          const bits = [player.team || "", player.side || "", player.position || ""].filter(Boolean);
          const meta = bits.length ? ` · ${escapeHtml(bits.join(" · "))}` : "";
          const pid = Number(player.player_id || 0);
          const nameHtml =
            pid > 0
              ? `<a class="fp-manual-player-link" href="/player/${pid}">${escapeHtml(name)}</a>`
              : `<span class="fp-manual-player-link" data-resolve-player-name="${escapeHtml(name)}" data-resolve-player-team="${escapeHtml(player.team || "")}">${escapeHtml(name)}</span>`;
          return `<li>${nameHtml}${meta}</li>`;
        })
        .join("")}</ul>`
    : `<p class="fp-fixture-enrich__hint">No players logged for this game.</p>`;
  return `
    <div class="so-match-modal__stats">${venue}${score}${coverage}</div>
    ${notes}
    <section class="fp-manual-detail">
      <h3>Players watched</h3>
      ${playerRows}
    </section>
    <section class="fp-manual-detail">
      <h3>Team sheet</h3>
      ${sheet}
    </section>
  `;
}

async function resolvePlayerCatalogId(name, team = "") {
  const clean = String(name || "").trim();
  if (!clean) return null;
  try {
    const data = await fetchJson("/api/players", {
      method: "POST",
      body: JSON.stringify({ search: clean }),
    });
    const players = data.players || [];
    const norm = clean.toLowerCase();
    let matches = players.filter((row) => String(row.name || "").trim().toLowerCase() === norm);
    if (!matches.length) {
      matches = players.filter((row) => String(row.name || "").trim().toLowerCase().includes(norm));
    }
    const teamNorm = String(team || "").trim().toLowerCase();
    if (teamNorm && matches.length > 1) {
      const byClub = matches.filter((row) => {
        const club = String(row.club || row.context_club || row.label || "").toLowerCase();
        return club.includes(teamNorm) || teamNorm.includes(club);
      });
      if (byClub.length) matches = byClub;
    }
    const best = matches[0] || (players.length === 1 ? players[0] : null);
    if (!best) return null;
    const id = Number(best.impect_player_id || best.playerId || best.id || 0);
    return id > 0 ? id : null;
  } catch {
    return null;
  }
}

async function enrichManualPlayerLinks() {
  if (!els.matchDetailsBody) return;
  const nodes = [...els.matchDetailsBody.querySelectorAll("[data-resolve-player-name]")];
  await Promise.all(
    nodes.map(async (node) => {
      const name = node.dataset.resolvePlayerName || "";
      const team = node.dataset.resolvePlayerTeam || "";
      const id = await resolvePlayerCatalogId(name, team);
      if (!id) return;
      const link = document.createElement("a");
      link.className = "fp-manual-player-link";
      link.href = `/player/${id}`;
      link.textContent = name;
      node.replaceWith(link);
    }),
  );
}

async function openMatchDetailsModal(fixtureIdValue) {
  const fixture = fixtureFromState(fixtureIdValue);
  if (!fixture || !els.matchDetailsModal) return;
  state.matchDetailsFixtureId = fixtureIdValue;
  if (els.matchDetailsTitle) {
    els.matchDetailsTitle.textContent = fixtureTeams(fixture);
  }
  if (els.matchDetailsMeta) {
    const bits = [
      fixture.league || "",
      formatShortDate(fixtureDateKey(fixture)),
      formatTime(fixture.kickoff_utc || fixture.scheduled_date, fixture),
      isManualFixture(fixture) ? "Manual" : "",
    ].filter(Boolean);
    els.matchDetailsMeta.textContent = bits.join(" · ");
  }
  els.matchDetailsModal.classList.remove("fp-assign-modal--hidden");
  els.matchDetailsModal.setAttribute("aria-hidden", "false");
  renderMatchDetailsModalBody();
  if (isManualFixture(fixture)) {
    enrichManualPlayerLinks();
  } else {
    await loadEnrichmentForIds([fixtureIdValue]);
    renderMatchDetailsModalBody();
  }
}

async function loadEnrichmentForIds(ids) {
  const needed = ids.filter((id) => id && !state.enrichment[id] && !state.enrichmentPending[id]).slice(0, 24);
  if (!needed.length) {
    refreshEnrichmentPanels(ids.filter(Boolean));
    return;
  }

  needed.forEach((id) => {
    state.enrichmentPending[id] = true;
  });
  refreshEnrichmentPanels(needed);

  try {
    const params = new URLSearchParams({
      season: state.season,
      fixture_ids: needed.join(","),
    });
    const data = await fetchJson(`/api/fixture-planner/match-enrichment?${params}`);
    Object.assign(state.enrichment, data.enrichments || {});
    await Promise.all(needed.map((id) => loadScoutingReportsForFixture(id)));
  } catch (error) {
    console.warn("Could not load match enrichment", error);
  } finally {
    needed.forEach((id) => {
      delete state.enrichmentPending[id];
    });
    refreshEnrichmentPanels(needed);
  }
}

async function loadScoutingReportsForFixture(fixtureIdValue) {
  if (!fixtureIdValue) return;
  try {
    const params = new URLSearchParams({ fixture_id: fixtureIdValue });
    const data = await fetchJson(`/api/fixture-planner/scouting-reports?${params}`);
    state.scoutingReportsByFixture[fixtureIdValue] = data.reports || {};
  } catch (error) {
    console.warn("Could not load scouting reports", error);
  }
}

function refreshEnrichmentPanels(ids) {
  // Card buttons only need a light hint refresh via re-render if visible.
  const openId = state.matchDetailsFixtureId;
  if (openId && ids.includes(openId)) {
    renderMatchDetailsModalBody();
  }
  // Update button hints without rebuilding the whole list.
  ids.forEach((id) => {
    const roots = [els.listRoot, els.calendarRoot].filter(Boolean);
    let btn = null;
    for (const root of roots) {
      btn = [...root.querySelectorAll("[data-open-match-details]")].find(
        (el) => el.dataset.openMatchDetails === id,
      );
      if (btn) break;
    }
    if (!btn) return;
    const enrich = state.enrichment[id];
    const pending = state.enrichmentPending[id];
    const hint = btn.querySelector(".fp-match-details-btn__hint");
    if (!hint) return;
    hint.textContent = enrich
      ? [enrich.venue, enrich.pxt?.home != null ? `PXT ${enrich.pxt.home}–${enrich.pxt.away}` : ""]
          .filter(Boolean)
          .join(" · ") || "Lineups ready"
      : pending
        ? "Loading…"
        : "Open for venue, PXT, lineups & reports";
  });
}

async function toggleLineupReport(button) {
  const fixtureIdValue = button.dataset.fixtureId || state.matchDetailsFixtureId || "";
  const playerId = Number(button.dataset.playerId || 0);
  if (!fixtureIdValue || !playerId) return;

  const bucket = { ...(state.scoutingReportsByFixture[fixtureIdValue] || {}) };
  const key = String(playerId);
  const currentlyReported = Boolean(bucket[key]);
  const reported = !currentlyReported;
  const fixture = fixtureFromState(fixtureIdValue);
  const enrich = state.enrichment[fixtureIdValue];
  const assignment = assignmentFor(fixtureIdValue);
  const side = button.dataset.side || "";
  const team =
    button.dataset.team ||
    (side === "away"
      ? fixture?.away?.name || enrich?.away_team?.name || ""
      : fixture?.home?.name || enrich?.home_team?.name || "");
  const playerName = button.dataset.playerName || "";
  const position = button.dataset.position || "";

  if (reported) {
    bucket[key] = {
      player_id: playerId,
      player_name: playerName,
      side,
      team,
      position,
      marked_at: new Date().toISOString(),
    };
  } else {
    delete bucket[key];
  }
  state.scoutingReportsByFixture[fixtureIdValue] = bucket;
  refreshEnrichmentPanels([fixtureIdValue]);

  try {
    await fetchJson("/api/fixture-planner/scouting-report", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fixture_id: fixtureIdValue,
        player_id: playerId,
        player_name: playerName,
        side,
        team,
        position,
        season: state.season || fixture?.season || "",
        staff: primaryStaff(assignment.staff),
        fixture_date: fixtureDateKey(fixture) || "",
        reported,
      }),
    });
    els.statusBar.textContent = reported
      ? `Marked report: ${playerName || "player"}`
      : `Removed report mark: ${playerName || "player"}`;
  } catch (error) {
    await loadScoutingReportsForFixture(fixtureIdValue);
    refreshEnrichmentPanels([fixtureIdValue]);
    els.statusBar.textContent = error.message || "Could not save report mark.";
  }
}

function fixtureTeams(fixture) {
  const home = fixture.home?.name || "TBC";
  const away = fixture.away?.name || "TBC";
  const score = fixture.score ? ` (${fixture.score})` : "";
  return `${home} vs ${away}${score}`;
}

function fixtureId(fixture) {
  return fixture.fixture_id || `${fixture.league}|${fixture.date}|${fixture.home?.name}|${fixture.away?.name}`;
}

function todayKey() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isValidDateKey(dateKey) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(dateKey || ""));
}

const MAX_UNFILTERED_FIXTURES = 320;

function isCupCompetition(league) {
  const name = String(league || "").trim();
  if (!name) return false;
  // PDL is a league competition, even when the label looks development-ish.
  if (/professional development league|^pdl$/i.test(name)) return false;
  if (cupUis().includes(name)) return true;
  const lower = name.toLowerCase();
  return (
    lower.includes("cup") ||
    lower.includes("trophy") ||
    lower.includes("carabao") ||
    lower.includes("papa john") ||
    lower.includes("vertu")
  );
}

function fixturesForLeagues(all = state.payload?.fixtures || []) {
  if (state.compScope === "cups" || state.cupsMode) {
    const selected = (state.leagues.length ? state.leagues : cupUis()).filter((name) =>
      cupUis().includes(name),
    );
    const active = selected.length ? selected : cupUis();
    return all.filter((fixture) => {
      if (!(fixture.cup || isCupCompetition(fixture.league))) return false;
      const league = String(fixture.league || "").trim();
      if (active.includes(league)) return true;
      if (active.includes("Vertu Trophy") && /efl trophy|vertu trophy/i.test(league)) return true;
      return false;
    });
  }

  if (state.compScope === "germany") {
    const selected = (state.leagues.length ? state.leagues : germanyUis()).filter((name) =>
      germanyUis().includes(name),
    );
    const active = selected.length ? selected : germanyUis();
    return all.filter((fixture) => {
      if (fixture.manual) return false;
      if (isCupCompetition(fixture.league) || fixture.cup) return false;
      return active.includes(String(fixture.league || "").trim());
    });
  }

  if (state.compScope === "all") {
    const leagueNames = allLeagueUis();
    const germanyNames = germanyUis();
    const cupNames = cupUis();
    const selected = (state.leagues.length ? state.leagues : [...leagueNames, ...germanyNames, ...cupNames]).filter(
      (name) => leagueNames.includes(name) || germanyNames.includes(name) || cupNames.includes(name),
    );
    const active = selected.length ? selected : [...leagueNames, ...germanyNames, ...cupNames];
    return all.filter((fixture) => {
      if (fixture.manual) return true;
      const league = String(fixture.league || "").trim();
      if (active.includes(league)) return true;
      if (active.includes("Vertu Trophy") && /efl trophy|vertu trophy/i.test(league)) return true;
      if (active.includes("Professional Development League") && /^pdl$/i.test(league)) return true;
      return false;
    });
  }

  const leagues = state.leagues.length ? state.leagues : (state.meta?.default_leagues || []);
  return all.filter((fixture) => {
    if (fixture.manual) return true;
    if (isCupCompetition(fixture.league) || fixture.cup) return false;
    if (germanyUis().includes(String(fixture.league || "").trim())) return false;
    const league = String(fixture.league || "").trim();
    if (leagues.includes(league)) return true;
    if (leagues.includes("Professional Development League") && /^pdl$/i.test(league)) return true;
    return false;
  });
}

function cupFixturesInPayload(all = state.payload?.fixtures || []) {
  return all.filter((fixture) => fixture.cup || isCupCompetition(fixture.league));
}

function isPlayedFixture(fixture) {
  if (isCompletedFixture(fixture)) return true;
  const dateKey = fixtureDateKey(fixture);
  return isValidDateKey(dateKey) && dateKey < todayKey();
}

function defaultMonthForPastView() {
  const today = todayKey();
  const dated = fixturesForLeagues()
    .map((fixture) => fixtureDateKey(fixture))
    .filter(isValidDateKey)
    .sort();
  if (!dated.length) {
    return today.slice(0, 7);
  }
  if (state.playedOnly) {
    const past = dated.filter((dateKey) => dateKey < today);
    if (past.length) {
      return past[past.length - 1].slice(0, 7);
    }
    return dated[dated.length - 1].slice(0, 7);
  }
  const upcoming = dated.find((dateKey) => dateKey >= today);
  if (upcoming) {
    return upcoming.slice(0, 7);
  }
  return dated[dated.length - 1].slice(0, 7);
}

function visibleFixtures() {
  const all = state.payload?.fixtures || [];
  const today = todayKey();
  let fixtures = fixturesForLeagues(all).filter((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (state.playedOnly && !isPlayedFixture(fixture)) {
      return false;
    }
    if (state.hidePast && isValidDateKey(dateKey) && dateKey < today) {
      return false;
    }
    if (state.monthFilter && dateKey.slice(0, 7) !== state.monthFilter) {
      return false;
    }
    if (state.staffFilter) {
      const assignment = assignmentFor(fixtureId(fixture));
      return staffNames(assignment.staff).includes(state.staffFilter);
    }
    return true;
  });

  if (state.playedOnly && !state.monthFilter && fixtures.length > MAX_UNFILTERED_FIXTURES) {
    const monthKey = defaultMonthForPastView();
    fixtures = fixtures.filter((fixture) => fixtureDateKey(fixture).slice(0, 7) === monthKey);
  } else if (!state.monthFilter && fixtures.length > MAX_UNFILTERED_FIXTURES) {
    const monthKey = defaultMonthForPastView();
    fixtures = fixtures.filter((fixture) => fixtureDateKey(fixture).slice(0, 7) === monthKey);
  }

  return fixtures;
}

function visibleFixtureHint() {
  if (state.playedOnly) {
    const all = fixturesForLeagues().filter((fixture) => isPlayedFixture(fixture));
    if (!all.length) {
      return "No played fixtures in this season yet. Live assignments from Fixture Planner will appear here after kick-off.";
    }
    if (!state.monthFilter && all.length > MAX_UNFILTERED_FIXTURES) {
      const monthKey = defaultMonthForPastView();
      return `Showing ${formatMonthLabel(monthKey)} only — pick a month above to browse played games (${all.length} loaded).`;
    }
    return "";
  }
  if (state.cupsMode) {
    const all = fixturesForLeagues();
    const cupCount = cupFixturesInPayload().length;
    if (!all.length && !cupCount) {
      return `No cup fixtures loaded for this season yet (${cupsLabelShort()}). Hit Refresh.`;
    }
    if (!all.length && cupCount) {
      return `Cup fixtures are loaded (${cupCount}), but none match the current filters — clear the month filter or show past games.`;
    }
    if (state.monthFilter) {
      return `Cups month filter on (${formatMonthLabel(state.monthFilter)}) — clear month to see the full cup run, including early EFL Cup ties.`;
    }
  }
  if (state.hidePast) {
    const all = fixturesForLeagues();
    const today = todayKey();
    const upcoming = all.filter((fixture) => {
      const dateKey = fixtureDateKey(fixture);
      return !isValidDateKey(dateKey) || dateKey >= today;
    }).length;
    if (!upcoming) {
      return state.cupsMode
        ? "No upcoming cup fixtures from FotMob in this season. Clear filters or open Played Fixtures."
        : "No upcoming fixtures in this season. Open Played Fixtures for games that have already taken place.";
    }
  }
  if (!state.cupsMode && !state.hidePast && !state.monthFilter) {
    const count = fixturesForLeagues().length;
    if (count > MAX_UNFILTERED_FIXTURES) {
      const monthKey = defaultMonthForPastView();
      return `Showing ${formatMonthLabel(monthKey)} only — pick a month above to browse the full season (${count} fixtures loaded).`;
    }
  }
  return "";
}

function staffTeams() {
  if (state.meta?.staff_teams?.length) {
    return state.meta.staff_teams;
  }
  const fallback = state.meta?.staff || [];
  return fallback.length
    ? [{ id: "recruitment", label: "Recruitment Team", members: fallback }]
    : [
        { id: "recruitment", label: "Recruitment Team", members: [] },
        { id: "coaching", label: "Coaching Team", members: [] },
        { id: "scouting", label: "Scouting Team", members: [] },
      ];
}

function teamSelectOptions(team, selected = "") {
  const members = team?.members || [];
  const emptyLabel = members.length ? "Unassigned" : "No one listed yet";
  return [
    `<option value="">${emptyLabel}</option>`,
    ...members.map(
      (name) =>
        `<option value="${escapeHtml(name)}"${name === selected ? " selected" : ""}>${escapeHtml(name)}</option>`,
    ),
  ].join("");
}

function assignmentControls(fixture, { expanded = false } = {}) {
  const id = fixtureId(fixture);
  const assignment = assignmentFor(id);
  const assigned = staffNames(assignment.staff);
  const watchTypes = state.meta?.watch_types || ["LIVE", "VIDEO"];
  const teams = staffTeams();
  const hasCoverage = assigned.length > 0 || Boolean(assignment.watch_type);
  const summaryText = assignmentSummaryText(id);

  const teamSelects = teams
    .map((team) => {
      const selected = (team.members || []).find((name) => assigned.includes(name)) || "";
      const disabled = !(team.members || []).length ? " disabled" : "";
      return `
        <label class="fp-team-assign">
          <span class="fp-team-assign__label">${escapeHtml(team.label)}</span>
          <select
            class="fp-staff-select fp-team-assign__select"
            data-fixture-id="${id}"
            data-team-id="${escapeHtml(team.id)}"
            aria-label="${escapeHtml(team.label)}"
            ${disabled}
          >
            ${teamSelectOptions(team, selected)}
          </select>
        </label>
      `;
    })
    .join("");

  const watchButtons = watchTypes
    .map((type) => {
      const active = assignment.watch_type === type ? " fp-watch-btn--active" : "";
      const cls = type === "LIVE" ? "fp-watch-btn--live" : "fp-watch-btn--video";
      return `<button type="button" class="fp-watch-btn ${cls}${active}" data-fixture-id="${id}" data-watch="${type}">${type}</button>`;
    })
    .join("");

  const editPlayers =
    assigned.length
      ? `<button type="button" class="fp-btn fp-btn--ghost fp-assign-edit" data-fixture-id="${id}" data-staff="${escapeHtml(primaryStaff(assigned))}">Players</button>`
      : "";
  const reportsLink =
    IS_PLAYED_APP && assigned.length
      ? `<a class="fp-btn fp-btn--ghost" href="/scout-summary?staff=${encodeURIComponent(primaryStaff(assigned))}">Reports</a>`
      : "";
  const postponed = isPostponedFixture(fixture);
  const postponeControl = IS_PLAYED_APP
    ? ""
    : postponed
      ? `<button type="button" class="fp-btn fp-btn--ghost fp-postpone-btn" data-fixture-postpone="${id}" data-postponed="1">Restore fixture</button>`
      : `<button type="button" class="fp-btn fp-btn--ghost fp-postpone-btn" data-fixture-postpone="${id}" data-postponed="0">Mark postponed</button>`;
  const coverageNote =
    IS_PLAYED_APP && assigned.length && assignment.watch_type
      ? `<div class="fp-assignment__note">${escapeHtml(assignment.watch_type)} · ${escapeHtml(staffLabel(assigned))}</div>`
      : "";

  return `
    <div class="fp-assignment${expanded ? " fp-assignment--open" : ""}" data-fixture-id="${id}">
      <button
        type="button"
        class="fp-assign-toggle${expanded ? " fp-assign-toggle--open" : ""}${hasCoverage ? " fp-assign-toggle--set" : ""}"
        data-assign-toggle="${id}"
        aria-expanded="${expanded ? "true" : "false"}"
      >
        <span class="fp-assign-toggle__label">${escapeHtml(expanded ? "Hide assign options" : summaryText)}</span>
        <span class="fp-assign-toggle__chevron" aria-hidden="true">${expanded ? "▴" : "▾"}</span>
      </button>
      ${coverageNote}
      <div class="fp-assignment__panel${expanded ? "" : " fp-assignment__panel--hidden"}">
        <div class="fp-team-assigns">${teamSelects}</div>
        <div class="fp-watch-toggle">${watchButtons}</div>
        ${editPlayers}
        ${reportsLink}
        ${postponeControl}
      </div>
    </div>
  `;
}

function closeAssignModal() {
  state.assignModal = null;
  if (els.assignModal) {
    els.assignModal.classList.add("fp-assign-modal--hidden");
    els.assignModal.setAttribute("aria-hidden", "true");
  }
}

function selectedWatchedPlayersFromModal() {
  if (!els.assignModalBody) return [];
  return [...els.assignModalBody.querySelectorAll('input[type="checkbox"][data-player-id]:checked')].map((input) => ({
    player_id: Number(input.dataset.playerId),
    player_name: input.dataset.playerName || "",
    team: input.dataset.team || "",
    side: input.dataset.side || "",
  }));
}

function renderAssignSquadColumn(side, team) {
  const players = team?.players || [];
  const selected = new Set((state.assignModal?.selectedIds || []).map(String));
  const list = players.length
    ? players
        .map((player) => {
          const checked = selected.has(String(player.player_id)) ? " checked" : "";
          return `
          <li>
            <label class="fp-assign-player">
              <input type="checkbox" data-player-id="${player.player_id}" data-player-name="${escapeHtml(player.player_name || "")}" data-team="${escapeHtml(team?.name || "")}" data-side="${side}"${checked} />
              <span class="fp-assign-player__name">${escapeHtml(player.player_name || "Player")}</span>
            </label>
          </li>
        `;
        })
        .join("")
    : `<li class="fp-assign-modal__empty" style="padding:.65rem">No squad list available</li>`;

  return `
    <section class="fp-assign-squad">
      <header class="fp-assign-squad__head">
        <strong>${escapeHtml(team?.name || (side === "home" ? "Home" : "Away"))}</strong>
        <span class="fp-assign-squad__count">${players.length} players</span>
      </header>
      <ul class="fp-assign-squad__list">${list}</ul>
    </section>
  `;
}

function renderAssignModalBody(squads) {
  if (!els.assignModalBody) return;
  if (!squads) {
    els.assignModalBody.innerHTML = `<p class="fp-assign-modal__loading">Loading squad lists…</p>`;
    return;
  }
  if (!squads.available) {
    els.assignModalBody.innerHTML = `
      <p class="fp-assign-modal__empty">Squad lists aren't available for this fixture yet. You can still assign the scout for a full-game watch.</p>
    `;
    return;
  }
  els.assignModalBody.innerHTML = `
    <div class="fp-assign-squads">
      ${renderAssignSquadColumn("home", squads.home)}
      ${renderAssignSquadColumn("away", squads.away)}
    </div>
  `;
}

function renderAssignModalChrome() {
  const modal = state.assignModal;
  if (!modal) return;
  const fixture = fixtureFromState(modal.fixtureId);
  const home = fixture?.home?.name || modal.home || "Home";
  const away = fixture?.away?.name || modal.away || "Away";
  if (els.assignModalTitle) {
    els.assignModalTitle.textContent = `${home} vs ${away}`;
  }
  if (els.assignModalMeta) {
    const kickoff = formatTime(fixture?.kickoff_utc || fixture?.scheduled_date, fixture);
    const dateLabel = formatShortDate(fixtureDateKey(fixture) || modal.date || "");
    els.assignModalMeta.textContent = `${fixture?.league || modal.league || ""} · ${dateLabel} · ${kickoff} · Assigning ${staffLabel(modal.staffList || modal.staff)}`;
  }
  if (els.assignModalStaff) {
    els.assignModalStaff.textContent = staffLabel(modal.staffList || modal.staff);
  }
  if (els.assignModalWatch) {
    const watchTypes = state.meta?.watch_types || ["LIVE", "VIDEO"];
    els.assignModalWatch.innerHTML = watchTypes
      .map((type) => {
        const active = modal.watchType === type ? " fp-watch-btn--active" : "";
        const cls = type === "LIVE" ? "fp-watch-btn--live" : "fp-watch-btn--video";
        return `<button type="button" class="fp-watch-btn ${cls}${active}" data-assign-watch="${type}">${type}</button>`;
      })
      .join("");
  }
}

async function openAssignModal(fixtureIdValue, staffName, nextStaffList = null) {
  const fixture = fixtureFromState(fixtureIdValue);
  if (!fixture || !staffName) return;
  const current = assignmentFor(fixtureIdValue);
  const staffList = staffNames(nextStaffList ?? [...staffNames(current.staff), staffName]);

  // Manual fixtures have no Impect squad lists — keep logged players and assign directly.
  if (isManualFixture(fixture)) {
    setAssignment(fixtureIdValue, {
      staff: staffList,
      watch_type: current.watch_type || fixture.watch_type || "LIVE",
      watched_players: current.watched_players?.length
        ? current.watched_players
        : fixture.watched_players || [],
    });
    els.statusBar.textContent = `Assigned ${staffLabel(staffList)} to manual fixture`;
    return;
  }

  state.assignModal = {
    fixtureId: fixtureIdValue,
    staff: staffName,
    staffList,
    watchType: current.watch_type || "LIVE",
    selectedIds: (current.watched_players || []).map((row) => row.player_id),
    home: fixture.home?.name || "",
    away: fixture.away?.name || "",
    league: fixture.league || "",
    date: fixtureDateKey(fixture),
    squads: null,
  };
  renderAssignModalChrome();
  renderAssignModalBody(null);
  els.assignModal?.classList.remove("fp-assign-modal--hidden");
  els.assignModal?.setAttribute("aria-hidden", "false");

  try {
    const params = new URLSearchParams({
      season: state.season,
      fixture_id: fixtureIdValue,
    });
    const squads = await fetchJson(`/api/fixture-planner/fixture-squads?${params}`);
    if (state.assignModal?.fixtureId !== fixtureIdValue) return;
    state.assignModal.squads = squads;
    renderAssignModalBody(squads);
  } catch (error) {
    if (state.assignModal?.fixtureId !== fixtureIdValue) return;
    els.assignModalBody.innerHTML = `<p class="fp-assign-modal__empty">${escapeHtml(error.message || "Could not load squads.")}</p>`;
  }
}

function confirmAssignModal() {
  const modal = state.assignModal;
  if (!modal) return;
  const watched = selectedWatchedPlayersFromModal();
  setAssignment(modal.fixtureId, {
    staff: staffNames(modal.staffList?.length ? modal.staffList : modal.staff),
    watch_type: modal.watchType || "LIVE",
    watched_players: watched,
  });
  closeAssignModal();
}

function bindAssignmentEvents(root) {
  root.querySelectorAll("[data-assign-toggle]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const id = btn.dataset.assignToggle;
      if (!id) return;
      const card = fixtureCardElement(id);
      const opening = !state.expandedFixtureIds[id];
      if (opening) {
        state.expandedFixtureIds[id] = true;
      } else {
        delete state.expandedFixtureIds[id];
      }
      toggleAssignmentPanel(card, opening);
    });
  });

  root.querySelectorAll(".fp-staff-select").forEach((select) => {
    select.addEventListener("change", () => {
      const id = select.dataset.fixtureId;
      const next = select.value || "";
      const current = assignmentFor(id);
      const currentList = staffNames(current.staff);
      const teamMembers = [...select.options]
        .map((opt) => opt.value)
        .filter(Boolean);
      const withoutTeam = currentList.filter((name) => !teamMembers.includes(name));
      const previous = (teamMembers || []).find((name) => currentList.includes(name)) || "";

      if (!next) {
        setAssignment(id, {
          staff: withoutTeam,
          watched_players: withoutTeam.length ? current.watched_players || [] : [],
        });
        return;
      }

      select.value = previous;
      openAssignModal(id, next, [...withoutTeam, next]);
    });
  });

  root.querySelectorAll(".fp-assign-edit").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.fixtureId;
      const current = assignmentFor(id);
      openAssignModal(id, btn.dataset.staff || primaryStaff(current.staff), staffNames(current.staff));
    });
  });

  root.querySelectorAll(".fp-watch-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.fixtureId;
      const current = assignmentFor(id);
      const next = current.watch_type === btn.dataset.watch ? "" : btn.dataset.watch;
      setAssignment(id, { watch_type: next });
    });
  });

  root.querySelectorAll("[data-fixture-postpone]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const id = btn.dataset.fixturePostpone;
      if (!id) return;
      const restore = btn.dataset.postponed === "1";
      setFixturePostponed(id, !restore);
    });
  });
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
      state.monthFilter = "";
      loadFixtures();
    });
  });
}

function monthOptionsFromFixtures(fixtures) {
  const months = new Set();
  fixtures.forEach((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (dateKey) months.add(dateKey.slice(0, 7));
  });
  return [...months].sort();
}

function renderMonthFilter() {
  if (!els.monthFilter) return;
  const all = state.payload?.fixtures || [];
  const leagues = state.leagues.length ? state.leagues : (state.meta?.default_leagues || []);
  const months = monthOptionsFromFixtures(all.filter((f) => leagues.includes(f.league)));

  if (state.monthFilter && !months.includes(state.monthFilter)) {
    state.monthFilter = "";
  }

  els.monthFilter.innerHTML = [
    `<option value="">All months</option>`,
    ...months.map(
      (monthKey) =>
        `<option value="${monthKey}"${monthKey === state.monthFilter ? " selected" : ""}>${formatMonthLabel(monthKey)}</option>`,
    ),
  ].join("");
  els.monthFilter.disabled = state.loading || !months.length;
}

function cupUis() {
  if (state.meta?.cup_uis?.length) return state.meta.cup_uis;
  if (state.meta?.cups?.length) return state.meta.cups.map((row) => row.ui);
  return [
    "FA Cup",
    "EFL Cup",
    "Vertu Trophy",
    "National League Cup",
    "Premier League Cup",
    "Scottish Cup",
  ];
}

function cupsLabelShort() {
  const selected = state.cupsMode
    ? state.leagues.filter((name) => cupUis().includes(name))
    : cupUis();
  const names = selected.length ? selected : cupUis();
  return names.map(cupShortLabel).join(" · ");
}

function cupShortLabel(name) {
  const map = {
    "FA Cup": "FA Cup",
    "EFL Cup": "EFL Cup",
    "Vertu Trophy": "Vertu Trophy",
    "National League Cup": "NL Cup",
    "Premier League Cup": "PL Cup",
    "Professional Development League": "PDL",
    "Scottish Cup": "Scottish Cup",
  };
  return map[name] || name;
}

function cupMetaRows() {
  if (state.meta?.cups?.length) return state.meta.cups;
  return cupUis().map((ui) => ({
    ui,
    color: leagueColors[ui] || "#f43f5e",
  }));
}

function allLeagueUis() {
  return (state.meta?.leagues || []).map((row) => row.ui);
}

function germanyUis() {
  if (state.meta?.germany_uis?.length) return state.meta.germany_uis;
  if (state.meta?.germany?.length) return state.meta.germany.map((row) => row.ui);
  return ["Bundesliga", "2. Bundesliga"];
}

function germanyMetaRows() {
  if (state.meta?.germany?.length) return state.meta.germany;
  return germanyUis().map((ui) => ({
    ui,
    color: leagueColors[ui] || "#e11d48",
  }));
}

function selectedCupUis() {
  const selected = state.leagues.filter((name) => cupUis().includes(name));
  return selected.length ? selected : [...cupUis()];
}

function selectedLeagueUis() {
  const selected = state.leagues.filter((name) => allLeagueUis().includes(name));
  return selected.length ? selected : allLeagueUis();
}

function selectedGermanyUis() {
  const selected = state.leagues.filter((name) => germanyUis().includes(name));
  return selected.length ? selected : [...germanyUis()];
}

function selectedAllCompUis() {
  const allowed = [...allLeagueUis(), ...germanyUis(), ...cupUis()];
  const selected = state.leagues.filter((name) => allowed.includes(name));
  return selected.length ? selected : allowed;
}

function usesStackedCompLayout() {
  return state.compScope === "cups" || state.compScope === "all" || state.cupsMode;
}

function syncCompTabs() {
  document.querySelectorAll("[data-comp-tab]").forEach((btn) => {
    const active = btn.dataset.compTab === state.compScope;
    btn.classList.toggle("fp-comp-scope__btn--active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
}

function setCompetitionScope(nextScope, { refetch = false } = {}) {
  const scope =
    nextScope === "cups" || nextScope === "all" || nextScope === "germany" ? nextScope : "leagues";
  if (scope === state.compScope && !refetch) {
    renderLeagueToggle();
    renderMonthFilter();
    renderSummary();
    renderView();
    return;
  }

  if (state.compScope === "leagues") {
    state.savedLeagueSelection = selectedLeagueUis();
  } else if (state.compScope === "germany") {
    state.savedGermanySelection = selectedGermanyUis();
  } else if (state.compScope === "cups") {
    state.savedCupSelection = selectedCupUis();
  } else if (state.compScope === "all") {
    state.savedAllSelection = selectedAllCompUis();
  }

  state.compScope = scope;
  state.cupsMode = scope === "cups";

  if (scope === "cups") {
    state.leagues = state.savedCupSelection?.length ? [...state.savedCupSelection] : [...cupUis()];
    state.monthFilter = "";
    state.view = "list";
  } else if (scope === "germany") {
    state.leagues = state.savedGermanySelection?.length
      ? [...state.savedGermanySelection]
      : [...germanyUis()];
    state.monthFilter = "";
    state.view = "list";
  } else if (scope === "all") {
    state.leagues = state.savedAllSelection?.length
      ? [...state.savedAllSelection]
      : [...allLeagueUis(), ...germanyUis(), ...cupUis()];
    state.monthFilter = "";
    state.view = "list";
  } else {
    state.leagues = state.savedLeagueSelection?.length
      ? [...state.savedLeagueSelection]
      : allLeagueUis();
  }

  renderLeagueToggle();
  renderMonthFilter();
  renderSummary();
  renderView();
  if (scope === "cups" || scope === "all" || scope === "germany" || refetch) {
    els.statusBar.textContent =
      scope === "cups"
        ? "Loading cup fixtures…"
        : scope === "germany"
          ? "Loading German league fixtures…"
          : scope === "all"
            ? "Loading all competitions…"
            : "Loading league fixtures…";
    loadFixtures();
  }
}

function renderLeagueToggle() {
  const leagues = state.meta?.leagues || [];
  const germany = germanyMetaRows();
  const cups = cupMetaRows();
  syncCompTabs();

  if (!state.leagues.length) {
    if (state.compScope === "cups") state.leagues = [...cupUis()];
    else if (state.compScope === "germany") state.leagues = [...germanyUis()];
    else if (state.compScope === "all") state.leagues = [...allLeagueUis(), ...germanyUis(), ...cupUis()];
    else state.leagues = leagues.map((row) => row.ui);
  }

  if (state.compScope === "cups") {
    const selected = selectedCupUis();
    const allSelected = cupUis().every((name) => selected.includes(name));
    els.leagueToggle.innerHTML = [
      `<button type="button" class="fp-league-btn fp-league-btn--cups-all${allSelected ? " fp-league-btn--active" : ""}" data-league-action="all-cups"${state.loading ? " disabled" : ""}>All cups</button>`,
      ...cups.map((cup) => {
        const active = selected.includes(cup.ui);
        const color = cup.color || leagueColors[cup.ui] || "#f43f5e";
        return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-cup="${escapeHtml(cup.ui)}" title="${escapeHtml(cup.ui)}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${escapeHtml(cupShortLabel(cup.ui))}</button>`;
      }),
    ].join("");
  } else if (state.compScope === "germany") {
    const selected = selectedGermanyUis();
    const allSelected = germanyUis().every((name) => selected.includes(name));
    els.leagueToggle.innerHTML = [
      `<button type="button" class="fp-league-btn fp-league-btn--all${allSelected ? " fp-league-btn--active" : ""}" data-league-action="all-germany"${state.loading ? " disabled" : ""}>All German</button>`,
      ...germany.map((league) => {
        const active = selected.includes(league.ui);
        const color = league.color || leagueColors[league.ui] || "#e11d48";
        return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-germany="${escapeHtml(league.ui)}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${escapeHtml(league.ui)}</button>`;
      }),
    ].join("");
  } else if (state.compScope === "all") {
    const selected = selectedAllCompUis();
    const allowed = [...allLeagueUis(), ...germanyUis(), ...cupUis()];
    const allSelected = allowed.every((name) => selected.includes(name));
    els.leagueToggle.innerHTML = [
      `<button type="button" class="fp-league-btn fp-league-btn--all${allSelected ? " fp-league-btn--active" : ""}" data-league-action="all-comps"${state.loading ? " disabled" : ""}>All comps</button>`,
      ...leagues.map((league) => {
        const active = selected.includes(league.ui);
        const color = league.color || leagueColors[league.ui] || "#34d399";
        return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-league="${escapeHtml(league.ui)}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${escapeHtml(league.ui)}</button>`;
      }),
      ...germany.map((league) => {
        const active = selected.includes(league.ui);
        const color = league.color || leagueColors[league.ui] || "#e11d48";
        return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-germany="${escapeHtml(league.ui)}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${escapeHtml(league.ui)}</button>`;
      }),
      ...cups.map((cup) => {
        const active = selected.includes(cup.ui);
        const color = cup.color || leagueColors[cup.ui] || "#f43f5e";
        return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-cup="${escapeHtml(cup.ui)}" title="${escapeHtml(cup.ui)}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${escapeHtml(cupShortLabel(cup.ui))}</button>`;
      }),
    ].join("");
  } else {
    const selected = selectedLeagueUis();
    const allSelected =
      leagues.length > 0 && leagues.every((row) => selected.includes(row.ui));
    els.leagueToggle.innerHTML = [
      `<button type="button" class="fp-league-btn fp-league-btn--all${allSelected ? " fp-league-btn--active" : ""}" data-league-action="all"${state.loading ? " disabled" : ""}>All leagues</button>`,
      ...leagues.map((league) => {
        const active = selected.includes(league.ui);
        const color = league.color || leagueColors[league.ui] || "#34d399";
        return `<button type="button" class="fp-league-btn${active ? " fp-league-btn--active" : ""}" data-league="${escapeHtml(league.ui)}" style="--league-color:${color}"${state.loading ? " disabled" : ""}>${escapeHtml(league.ui)}</button>`;
      }),
    ].join("");
  }

  els.leagueToggle.querySelectorAll(".fp-league-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      if (btn.dataset.leagueAction === "all-cups") {
        state.compScope = "cups";
        state.cupsMode = true;
        state.leagues = [...cupUis()];
        state.savedCupSelection = [...cupUis()];
      } else if (btn.dataset.leagueAction === "all-germany") {
        state.compScope = "germany";
        state.cupsMode = false;
        state.leagues = [...germanyUis()];
        state.savedGermanySelection = [...state.leagues];
      } else if (btn.dataset.leagueAction === "all-comps") {
        state.compScope = "all";
        state.cupsMode = false;
        state.leagues = [...allLeagueUis(), ...germanyUis(), ...cupUis()];
        state.savedAllSelection = [...state.leagues];
      } else if (btn.dataset.leagueAction === "all") {
        state.compScope = "leagues";
        state.cupsMode = false;
        state.leagues = allLeagueUis();
        state.savedLeagueSelection = [...state.leagues];
      } else if (btn.dataset.cup) {
        const cup = btn.dataset.cup;
        if (state.compScope === "all") {
          let next = state.leagues.filter((item) =>
            allLeagueUis().includes(item) || germanyUis().includes(item) || cupUis().includes(item),
          );
          if (!next.length) next = [cup];
          else if (next.includes(cup)) {
            next = next.filter((item) => item !== cup);
            if (!next.length) next = [cup];
          } else next = [...next, cup];
          state.leagues = next;
          state.savedAllSelection = [...next];
        } else {
          state.compScope = "cups";
          state.cupsMode = true;
          let next = state.leagues.filter((item) => cupUis().includes(item));
          if (!next.length) next = [cup];
          else if (next.includes(cup)) {
            next = next.filter((item) => item !== cup);
            if (!next.length) next = [cup];
          } else next = [...next, cup];
          state.leagues = next;
          state.savedCupSelection = [...next];
        }
      } else if (btn.dataset.germany) {
        const league = btn.dataset.germany;
        if (state.compScope === "all") {
          let next = state.leagues.filter((item) =>
            allLeagueUis().includes(item) || germanyUis().includes(item) || cupUis().includes(item),
          );
          if (!next.length) next = [league];
          else if (next.includes(league)) {
            next = next.filter((item) => item !== league);
            if (!next.length) next = [league];
          } else next = [...next, league];
          state.leagues = next;
          state.savedAllSelection = [...next];
        } else {
          state.compScope = "germany";
          state.cupsMode = false;
          let next = state.leagues.filter((item) => germanyUis().includes(item));
          if (!next.length) next = [league];
          else if (next.includes(league)) {
            next = next.filter((item) => item !== league);
            if (!next.length) next = [league];
          } else next = [...next, league];
          state.leagues = next;
          state.savedGermanySelection = [...next];
        }
      } else {
        const league = btn.dataset.league;
        if (state.compScope === "all") {
          let next = state.leagues.filter((item) =>
            allLeagueUis().includes(item) || germanyUis().includes(item) || cupUis().includes(item),
          );
          if (!next.length) next = [league];
          else if (next.includes(league)) {
            next = next.filter((item) => item !== league);
            if (!next.length) next = [league];
          } else next = [...next, league];
          state.leagues = next;
          state.savedAllSelection = [...next];
        } else {
          state.compScope = "leagues";
          state.cupsMode = false;
          let next = state.leagues.filter((item) => allLeagueUis().includes(item));
          if (!next.length) next = [league];
          else if (next.includes(league)) {
            next = next.filter((item) => item !== league);
            if (!next.length) next = [league];
          } else next = [...next, league];
          state.leagues = next;
          state.savedLeagueSelection = [...next];
        }
      }
      renderLeagueToggle();
      renderMonthFilter();
      renderSummary();
      renderView();
    });
  });
}

function countAssignments() {
  const assigned = Object.values(state.assignments).filter((row) => hasStaff(row.staff)).length;
  const live = Object.values(state.assignments).filter((row) => row.watch_type === "LIVE").length;
  const video = Object.values(state.assignments).filter((row) => row.watch_type === "VIDEO").length;
  return { assigned, live, video };
}

function coverageFromFixtures(fixtures) {
  const byLeague = new Map();
  fixtures.forEach((fixture) => {
    const league = fixture.league;
    const dateKey = fixtureDateKey(fixture);
    if (!league || !dateKey) return;
    if (!byLeague.has(league)) {
      byLeague.set(league, {
        fixture_count: 0,
        first_date: dateKey,
        last_date: dateKey,
      });
    }
    const row = byLeague.get(league);
    row.fixture_count += 1;
    if (dateKey < row.first_date) row.first_date = dateKey;
    if (dateKey > row.last_date) row.last_date = dateKey;
  });
  return Object.fromEntries(byLeague);
}

function renderCoveragePanel() {
  if (!els.coveragePanel) return;
  const fixtures = state.payload?.fixtures || [];
  const apiCoverage = state.payload?.coverage || {};
  const computedCoverage = coverageFromFixtures(fixtures);
  const order =
    state.compScope === "cups"
      ? cupUis()
      : state.compScope === "germany"
        ? selectedGermanyUis()
        : state.compScope === "all"
          ? selectedAllCompUis()
          : activeLeagueOrder();
  const rows = order.map((league) => {
    const apiRow = apiCoverage[league] || {};
    const computedRow = computedCoverage[league] || {};
    const row =
      Number(apiRow.fixture_count || 0) >= Number(computedRow.fixture_count || 0)
        ? apiRow.fixture_count
          ? apiRow
          : computedRow
        : computedRow.fixture_count
          ? computedRow
          : apiRow;
    const color = leagueColors[league] || "#34d399";
    if (!row.fixture_count) {
      return `<div class="fp-coverage__item fp-coverage__item--empty" style="--league-color:${color}"><strong>${league}</strong><span>No ${state.season} fixtures published yet</span></div>`;
    }
    const start = formatShortDate(row.first_date);
    const end = formatShortDate(row.last_date);
    return `<div class="fp-coverage__item" style="--league-color:${color}"><strong>${league}</strong><span>${row.fixture_count} fixtures · ${start} – ${end}</span></div>`;
  });
  els.coveragePanel.innerHTML = rows.join("");
  els.coveragePanel.classList.remove("hidden");
}

function scrollListToUpcoming() {
  if (state.view !== "list" || !els.listRoot) return;
  requestAnimationFrame(() => {
    const today = todayKey();
    const sections = [...els.listRoot.querySelectorAll(".fp-list-day")];
    const target =
      sections.find((section) => section.dataset.weekendStart && section.dataset.weekendStart >= today) ||
      sections.find((section) => section.dataset.weekendStart) ||
      sections[0];
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function restoreScrollPosition(scrollY, anchorId = null) {
  if (scrollY == null || Number.isNaN(scrollY)) return;
  const apply = () => {
    window.scrollTo(0, scrollY);
    if (anchorId) {
      const card = fixtureCardElement(anchorId);
      if (card) {
        const rect = card.getBoundingClientRect();
        const nextTop = window.scrollY + rect.top;
        if (Math.abs(nextTop - scrollY) > 4) {
          window.scrollTo(0, scrollY);
        }
      }
    }
  };
  apply();
  requestAnimationFrame(apply);
  window.setTimeout(apply, 0);
}
function renderSummary() {
  const fixtures = visibleFixtures();
  const all = state.payload?.fixtures || [];
  const { assigned, live, video } = countAssignments();
  const selectionLabel =
    state.compScope === "cups"
      ? "Cup comps"
      : state.compScope === "germany"
        ? "German leagues"
        : state.compScope === "all"
          ? "Comps selected"
          : "Leagues selected";
  const selectionValue =
    state.compScope === "cups"
      ? selectedCupUis().length
      : state.compScope === "germany"
        ? selectedGermanyUis().length
        : state.compScope === "all"
          ? selectedAllCompUis().length
          : selectedLeagueUis().length;

  els.summaryPanel.innerHTML = `
    <div class="fp-summary__item">
      <span class="fp-summary__value">${fixtures.length}</span>
      <span class="fp-summary__label">Fixtures shown</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${selectionValue}</span>
      <span class="fp-summary__label">${selectionLabel}</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${assigned}</span>
      <span class="fp-summary__label">Assigned to staff</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${live} / ${video}</span>
      <span class="fp-summary__label">Live / Video</span>
    </div>
    <div class="fp-summary__item">
      <span class="fp-summary__value">${state.season}</span>
      <span class="fp-summary__label">Season (${all.length} total loaded)</span>
    </div>
  `;

  const leagueLabel =
    state.compScope === "cups"
      ? `Cups (${cupsLabelShort()})`
      : state.compScope === "germany"
        ? selectedGermanyUis().join(", ") || "Germany"
        : state.compScope === "all"
          ? `All comps (${selectedAllCompUis().length})`
          : state.leagues.filter((item) => allLeagueUis().includes(item)).join(", ") || "All leagues";
  if (els.pageSubtitle) {
    els.pageSubtitle.textContent = IS_PLAYED_APP
      ? `${state.season} played fixtures · ${leagueLabel} · keep LIVE coverage, pick up VIDEO, players & reports`
      : `${state.season} upcoming fixtures · ${leagueLabel} · assign scouts as Live or Video`;
  }
  renderCoveragePanel();
}

function compareDateKeys(a, b) {
  const cmp = String(a || "").localeCompare(String(b || ""));
  return IS_PLAYED_APP ? -cmp : cmp;
}

function groupFixturesByMonth(fixtures) {
  const months = new Map();
  fixtures.forEach((fixture) => {
    const dateKey = fixture.date || (fixture.scheduled_date || "").slice(0, 10);
    if (!dateKey) return;
    const monthKey = dateKey.slice(0, 7);
    if (!months.has(monthKey)) months.set(monthKey, []);
    months.get(monthKey).push({ ...fixture, date: dateKey });
  });
  return [...months.entries()].sort(([a], [b]) => compareDateKeys(a, b));
}

function groupFixturesByDate(fixtures) {
  const days = new Map();
  fixtures.forEach((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (!dateKey) return;
    if (!days.has(dateKey)) days.set(dateKey, []);
    days.get(dateKey).push({ ...fixture, date: dateKey });
  });
  return [...days.entries()].sort(([a], [b]) => compareDateKeys(a, b));
}

function groupFixturesByWeekend(fixtures) {
  const weekends = new Map();
  fixtures.forEach((fixture) => {
    const dateKey = fixtureDateKey(fixture);
    if (!dateKey) return;
    const key = footballWeekendKey(dateKey);
    if (!weekends.has(key)) weekends.set(key, []);
    weekends.get(key).push({ ...fixture, date: dateKey });
  });
  return [...weekends.entries()].sort(([a], [b]) => compareDateKeys(a, b));
}

function formatWeekendLabel(weekendKey, fixtures) {
  const dates = [...new Set(fixtures.map((fixture) => fixtureDateKey(fixture)))].sort();
  if (dates.length === 1) {
    return formatDateLabel(dates[0]);
  }
  const anchor = formatDateLabel(weekendKey);
  const span = `${formatShortDate(dates[0])} – ${formatShortDate(dates[dates.length - 1])}`;
  return `Weekend of ${anchor} (${span})`;
}

function assignmentBadge(fixture) {
  const assignment = assignmentFor(fixtureId(fixture));
  const assigned = staffNames(assignment.staff);
  if (!assigned.length && !assignment.watch_type) {
    return "";
  }
  const parts = [];
  assigned.forEach((name) => {
    parts.push(
      `<span class="fp-assignment-badge fp-assignment-badge--staff">${escapeHtml(name.split(" ")[0])}</span>`,
    );
  });
  if (assignment.watch_type) {
    const cls = assignment.watch_type === "LIVE" ? "fp-assignment-badge--live" : "fp-assignment-badge--video";
    parts.push(`<span class="fp-assignment-badge ${cls}">${assignment.watch_type}</span>`);
  }
  const watchedCount = (assignment.watched_players || []).length;
  if (watchedCount) {
    parts.push(`<span class="fp-assignment-badge fp-assignment-badge--players">${watchedCount} player${watchedCount === 1 ? "" : "s"}</span>`);
  }
  return `<div class="fp-assignment-badges">${parts.join("")}</div>`;
}

function buildMonthGrid(monthKey, fixtures) {
  const [year, month] = monthKey.split("-").map(Number);
  const startOffset = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(year, month, 0).getDate();
  const today = todayKey();

  const byDate = new Map();
  fixtures.forEach((fixture) => {
    if (!byDate.has(fixture.date)) byDate.set(fixture.date, []);
    byDate.get(fixture.date).push(fixture);
  });

  const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const weekdayHtml = weekdays.map((day) => `<div class="fp-weekday">${day}</div>`).join("");

  const cells = [];
  for (let i = 0; i < startOffset; i += 1) {
    cells.push('<div class="fp-day fp-day--muted"></div>');
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const dayFixtures = byDate.get(dateKey) || [];
    const todayClass = dateKey === today ? " fp-day__num--today" : "";
    cells.push(`
      <div class="fp-day">
        <div class="fp-day__num${todayClass}">${day}</div>
        ${dayFixtures
          .slice(0, 3)
          .map((fixture) => {
            const color = leagueColors[fixture.league] || "#34d399";
            return `
              <article class="fp-fixture" style="--league-color:${color}">
                <div class="fp-fixture__teams">${fixtureTeams(fixture)}</div>
                <div class="fp-fixture__meta">
                  <span class="fp-fixture__league">${fixture.league}</span>
                  <span>${formatTime(fixture.kickoff_utc || fixture.scheduled_date, fixture)}</span>
                </div>
                ${assignmentBadge(fixture)}
              </article>
            `;
          })
          .join("")}
        ${dayFixtures.length > 3 ? `<div class="fp-fixture__meta">+${dayFixtures.length - 3} more</div>` : ""}
      </div>
    `);
  }

  return `
    <section class="fp-month">
      <header class="fp-month__head">
        <h2 class="fp-month__title">${formatMonthLabel(monthKey)}</h2>
        <span class="fp-month__count">${fixtures.length} fixtures</span>
      </header>
      <div class="fp-month-grid">
        ${weekdayHtml}
        ${cells.join("")}
      </div>
    </section>
  `;
}

function renderCalendar() {
  const fixtures = visibleFixtures();
  if (!fixtures.length) {
    els.calendarRoot.innerHTML = `<div class="card" style="padding:1rem">No fixtures for the selected leagues.</div>`;
    return;
  }
  els.calendarRoot.innerHTML = groupFixturesByMonth(fixtures)
    .map(([monthKey, monthFixtures]) => buildMonthGrid(monthKey, monthFixtures))
    .join("");
}

function groupFixturesByLeague(fixtures) {
  const byLeague = new Map();
  fixtures.forEach((fixture) => {
    if (!byLeague.has(fixture.league)) {
      byLeague.set(fixture.league, []);
    }
    byLeague.get(fixture.league).push(fixture);
  });
  byLeague.forEach((rows) => {
    rows.sort((a, b) => {
      const ta = a.kickoff_utc || a.scheduled_date || "";
      const tb = b.kickoff_utc || b.scheduled_date || "";
      return compareDateKeys(ta, tb);
    });
  });
  return byLeague;
}

function activeLeagueOrder() {
  const defaults =
    state.compScope === "germany"
      ? germanyUis()
      : state.meta?.default_leagues || allLeagueUis() || Object.keys(leagueColors);
  const selected = state.leagues.length ? state.leagues : defaults;
  const order = defaults.filter((league) => selected.includes(league));
  const seen = new Set(order);
  for (const fixture of visibleFixtures()) {
    const league = fixture.league || "Manual";
    if (!seen.has(league)) {
      order.push(league);
      seen.add(league);
    }
  }
  return order;
}

function groupFixturesByDay(fixtures) {
  const byDay = new Map();
  fixtures.forEach((fixture) => {
    const day = fixtureDateKey(fixture) || "unknown";
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(fixture);
  });
  byDay.forEach((rows) => {
    rows.sort((a, b) => {
      const ta = a.kickoff_utc || a.scheduled_date || "";
      const tb = b.kickoff_utc || b.scheduled_date || "";
      return compareDateKeys(ta, tb);
    });
  });
  return [...byDay.entries()].sort((a, b) => compareDateKeys(a[0], b[0]));
}

function renderFixtureCard(fixture, { showDate = false } = {}) {
  const id = fixtureId(fixture);
  const color = leagueColors[fixture.league] || "#34d399";
  const completed = isCompletedFixture(fixture);
  const postponed = isPostponedFixture(fixture);
  const showDateLine = showDate || completed;
  const dateLine = showDateLine
    ? `<span class="fp-list-fixture__date">${formatShortDate(fixtureDateKey(fixture))}</span>`
    : "";
  const showCompBadge =
    usesStackedCompLayout() || isCupCompetition(fixture.league) || fixture.cup;
  const cupBadge = showCompBadge
    ? `<span class="fp-cup-badge" style="--league-color:${color}">${escapeHtml(fixture.league || "Cup")}</span>`
    : "";
  const timeLabel = postponed
    ? `<span class="fp-postponed-label">Postponed</span>`
    : `<span class="fp-list-fixture__time">${formatTime(fixture.kickoff_utc || fixture.scheduled_date, fixture)}</span>`;
  const collapsedPostpone = !IS_PLAYED_APP && postponed
    ? `<button type="button" class="fp-postponed-restore" data-fixture-postpone="${id}" data-postponed="1">Restore</button>`
    : "";
  const expanded = Boolean(state.expandedFixtureIds[id]);
  return `
    <article class="fp-list-fixture fp-list-fixture--stacked${completed ? " fp-list-fixture--completed" : ""}${postponed ? " fp-list-fixture--postponed" : ""}${usesStackedCompLayout() ? " fp-list-fixture--cup" : ""}${expanded ? " fp-list-fixture--expanded" : ""}" style="--league-color:${color}" data-fixture-card="${id}">
      <div class="fp-list-fixture__schedule">
        ${timeLabel}
        ${dateLine}
        ${cupBadge}
        ${collapsedPostpone}
      </div>
      <div class="fp-list-fixture__main">
        <div class="fp-list-fixture__head">
          ${assignmentBadge(fixture)}
        </div>
        <div class="fp-list-fixture__teams">${fixtureTeams(fixture)}</div>
        ${renderCompletedExtras(fixture)}
        <div class="fp-assignment-slot" data-assignment-slot="${escapeHtml(id)}">
          ${assignmentControls(fixture, { expanded })}
        </div>
      </div>
    </article>
  `;
}

function renderLeagueColumn(league, fixtures, { showDate = false } = {}) {
  const color = leagueColors[league] || "#34d399";
  const body = fixtures.length
    ? fixtures.map((fixture) => renderFixtureCard(fixture, { showDate })).join("")
    : `<p class="fp-league-column__empty">No fixtures</p>`;
  return `
    <div class="fp-league-column${fixtures.length ? "" : " fp-league-column--empty"}" style="--league-color:${color}">
      <header class="fp-league-column__head">
        <span>${league}</span>
        <span class="fp-league-column__count">${fixtures.length}</span>
      </header>
      <div class="fp-league-column__body">
        ${body}
      </div>
    </div>
  `;
}

function renderList({ scrollToUpcoming = false } = {}) {
  const fixtures = visibleFixtures();
  const hint = visibleFixtureHint();
  if (!fixtures.length) {
    const message =
      hint ||
      (state.compScope === "cups"
        ? `No cup fixtures for the selected season and filters. Cups: ${cupsLabelShort()} — clear the month filter and hit Refresh.`
        : state.compScope === "germany"
          ? "No German league fixtures for the selected season and filters."
          : state.compScope === "all"
            ? "No fixtures for the selected competitions and filters."
            : "No fixtures for the selected leagues and filters.");
    els.listRoot.innerHTML = `<div class="card fp-list-empty"><p>${escapeHtml(message)}</p></div>`;
    return;
  }

  const hintHtml = hint
    ? `<div class="fp-list-hint card"><p>${escapeHtml(hint)}</p></div>`
    : "";

  if (usesStackedCompLayout()) {
    const banner =
      state.compScope === "all"
        ? `<div class="fp-cups-banner card"><strong>All comps</strong><span>Leagues + cups · matchday grid</span></div>`
        : `<div class="fp-cups-banner card"><strong>Cups</strong><span>${escapeHtml(cupsLabelShort())} — matchday grid (no league columns)</span></div>`;
    els.listRoot.innerHTML =
      hintHtml +
      banner +
      groupFixturesByDay(fixtures)
        .map(([dayKey, dayFixtures]) => {
          const cards = dayFixtures.map((fixture) => renderFixtureCard(fixture)).join("");
          return `
            <section class="fp-list-day fp-list-day--cups" data-weekend-start="${escapeHtml(dayKey)}">
              <header class="fp-list-day__head">${formatShortDate(dayKey)} · ${dayFixtures.length} fixture${dayFixtures.length === 1 ? "" : "s"}</header>
              <div class="fp-list-day__stack">${cards}</div>
            </section>
          `;
        })
        .join("");
    bindAssignmentEvents(els.listRoot);
    if (!IS_PLAYED_APP && scrollToUpcoming) {
      scrollListToUpcoming();
    }
    return;
  }

  const leagueOrder = activeLeagueOrder();
  els.listRoot.innerHTML =
    hintHtml +
    groupFixturesByWeekend(fixtures)
      .map(([weekendKey, weekendFixtures]) => {
        const byLeague = groupFixturesByLeague(weekendFixtures);
        const showDate = new Set(weekendFixtures.map((fixture) => fixtureDateKey(fixture))).size > 1;
        const columns = leagueOrder
          .map((league) => renderLeagueColumn(league, byLeague.get(league) || [], { showDate }))
          .join("");

        return `
        <section class="fp-list-day" data-weekend-start="${escapeHtml(weekendKey)}">
          <header class="fp-list-day__head">${formatWeekendLabel(weekendKey, weekendFixtures)} · ${weekendFixtures.length} fixtures</header>
          <div class="fp-list-day__columns" style="--fp-league-count:${leagueOrder.length}">${columns}</div>
        </section>
      `;
      })
      .join("");

  bindAssignmentEvents(els.listRoot);
  if (!IS_PLAYED_APP && scrollToUpcoming) {
    scrollListToUpcoming();
  }
}

function renderView({ preserveScroll = false, scrollToUpcoming = false, scrollAnchorId = null } = {}) {
  const scrollY = preserveScroll ? window.scrollY : null;
  const isMonth = state.view === "month";
  els.calendarRoot.classList.toggle("hidden", !isMonth);
  els.listRoot.classList.toggle("hidden", isMonth);
  if (isMonth) renderCalendar();
  else renderList({ scrollToUpcoming: scrollToUpcoming && !preserveScroll });
  if (preserveScroll) {
    restoreScrollPosition(scrollY, scrollAnchorId);
  }
}

async function loadFixtures({ forceRefresh = false } = {}) {
  state.loading = true;
  state.enrichment = {};
  state.enrichmentPending = {};
  renderSeasonToggle();
  renderLeagueToggle();
  setStatus(`Loading ${state.season} fixtures…`, "loading");
  els.statusBar.textContent =
    state.compScope === "cups"
      ? "Pulling cup fixtures…"
      : state.compScope === "germany"
        ? "Pulling Bundesliga + 2. Bundesliga…"
        : state.compScope === "all"
          ? "Pulling league + cup fixtures…"
          : "Fetching fixtures from Impect, FotMob and BBC…";

  try {
    const refresh = forceRefresh ? "&refresh=1" : "";
    const upcoming = IS_PLAYED_APP ? "" : "&upcoming=1";
    state.payload = await fetchJson(
      `/api/fixture-planner/fixtures?season=${encodeURIComponent(state.season)}${refresh}${upcoming}&_=${Date.now()}`,
    );
    state.teamNamesLoaded = false;
    setTeamNameCatalog(teamNamesFromPayload(state.payload));
    await loadAssignmentsFromServer();
    if (!IS_PLAYED_APP && !state.monthFilter) {
      state.monthFilter = defaultMonthForPastView();
    }
    renderMonthFilter();
    renderSummary();
    renderView({ scrollToUpcoming: true });
    setStatus("");
    const coverage = state.payload?.coverage || {};
    const cupCount = cupFixturesInPayload().length;
    const eflCount = Number(coverage["EFL Cup"]?.fixture_count || 0);
    const manualCount = (state.payload?.fixtures || []).filter((row) => row.manual).length;
    if (state.cupsMode) {
      els.statusBar.textContent =
        cupCount > 0
          ? `Cups loaded: ${cupCount} fixtures (${eflCount} EFL Cup). Other comps appear when published.`
          : "No cup fixtures returned from FotMob yet for this season.";
    } else {
      const missing = activeLeagueOrder().filter((league) => !(coverage[league]?.fixture_count));
      if (state.season === "26/27" && missing.length) {
        els.statusBar.textContent = `Loaded ${state.payload.fixtures?.length || 0} fixtures for ${state.season}. ${missing.join(", ")} ${missing.length === 1 ? "has" : "have"} no published schedule yet. Cups: ${cupCount}.`;
      } else {
        els.statusBar.textContent = `Loaded ${state.payload.fixtures?.length || 0} fixtures for ${state.season}${manualCount ? ` · ${manualCount} manual` : ""} · cups ${cupCount}.`;
      }
    }
  } catch (error) {
    setStatus(error.message, "error");
    els.statusBar.textContent = "Could not load fixtures.";
  } finally {
    state.loading = false;
    renderSeasonToggle();
    renderLeagueToggle();
    renderMonthFilter();
  }
}

function populateManualStaffSelect() {
  const root = els.manualStaffTeams || els.manualStaff;
  if (!root) return;
  const teams = staffTeams();
  if (els.manualStaffTeams) {
    els.manualStaffTeams.innerHTML = teams
      .map((team) => {
        const disabled = !(team.members || []).length ? " disabled" : "";
        return `
          <label class="fp-team-assign">
            <span class="fp-team-assign__label">${escapeHtml(team.label)}</span>
            <select class="fp-manual-staff-select fp-team-assign__select" data-manual-staff-team="${escapeHtml(team.id)}"${disabled}>
              ${teamSelectOptions(team, "")}
            </select>
          </label>
        `;
      })
      .join("");
    return;
  }
  const options = [`<option value="">Unassigned</option>`];
  teams.forEach((team) => {
    const members = team.members || [];
    if (!members.length) return;
    options.push(
      `<optgroup label="${escapeHtml(team.label)}">${members
        .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
        .join("")}</optgroup>`,
    );
  });
  els.manualStaff.innerHTML = options.join("");
}

function collectManualStaff() {
  if (els.manualStaffTeams) {
    return [...els.manualStaffTeams.querySelectorAll(".fp-manual-staff-select")]
      .map((select) => select.value.trim())
      .filter(Boolean);
  }
  const single = els.manualStaff?.value?.trim() || "";
  return single ? [single] : [];
}

function teamNamesFromPayload(payload) {
  const entries = [];
  for (const fixture of payload?.fixtures || []) {
    const home = fixture?.home?.name || fixture?.home || "";
    const away = fixture?.away?.name || fixture?.away || "";
    if (home) entries.push({ name: String(home).trim(), country: "", country_label: "" });
    if (away) entries.push({ name: String(away).trim(), country: "", country_label: "" });
  }
  return entries;
}

function setTeamNameCatalog(entriesOrNames) {
  const entries = [];
  const seen = new Set();
  for (const row of entriesOrNames || []) {
    const name = typeof row === "string" ? row : row?.name;
    const clean = String(name || "").trim();
    if (!clean) continue;
    const key = clean.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push({
      name: clean,
      country: typeof row === "string" ? "" : String(row?.country || "").trim().toUpperCase(),
      country_label:
        typeof row === "string"
          ? ""
          : String(row?.country_label || row?.country || "").trim(),
    });
  }
  entries.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  state.teamEntries = entries;
  state.teamNames = entries.map((row) => row.name);
}

function normalizeTeamKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/\b(fc|afc|cf)\b/g, "")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function filterTeamNameSuggestions(query, limit = 8) {
  const typed = String(query || "").trim();
  if (!typed || !state.teamEntries.length) return [];
  const lower = typed.toLowerCase();
  const key = normalizeTeamKey(typed);
  const starts = [];
  const includes = [];
  const fuzzy = [];
  for (const entry of state.teamEntries) {
    const nameLower = entry.name.toLowerCase();
    if (nameLower.startsWith(lower)) {
      starts.push(entry);
    } else if (nameLower.includes(lower)) {
      includes.push(entry);
    } else if (key && normalizeTeamKey(entry.name).includes(key)) {
      fuzzy.push(entry);
    }
    if (starts.length >= limit) break;
  }
  return [...starts, ...includes, ...fuzzy].slice(0, limit);
}

function highlightTeamMatch(name, query) {
  const typed = String(query || "").trim();
  if (!typed) return escapeHtml(name);
  const lowerName = name.toLowerCase();
  const lowerQuery = typed.toLowerCase();
  const index = lowerName.indexOf(lowerQuery);
  if (index < 0) return escapeHtml(name);
  const before = name.slice(0, index);
  const match = name.slice(index, index + typed.length);
  const after = name.slice(index + typed.length);
  return `${escapeHtml(before)}<mark>${escapeHtml(match)}</mark>${escapeHtml(after)}`;
}

function snapTeamInputToCatalog(input) {
  if (!input) return;
  const typed = input.value.trim();
  if (!typed || !state.teamNames.length) return;
  const exact = state.teamNames.find((name) => name.toLowerCase() === typed.toLowerCase());
  if (exact) {
    input.value = exact;
    input.classList.toggle("fp-team-ac__input--matched", true);
    return;
  }
  const typedKey = normalizeTeamKey(typed);
  const matches = state.teamNames.filter((name) => normalizeTeamKey(name) === typedKey);
  if (matches.length === 1) {
    input.value = matches[0];
    input.classList.toggle("fp-team-ac__input--matched", true);
    return;
  }
  input.classList.toggle(
    "fp-team-ac__input--matched",
    state.teamNames.some((name) => name.toLowerCase() === typed.toLowerCase()),
  );
}

function closeTeamAutocompleteMenus(exceptWrap = null) {
  document.querySelectorAll(".fp-team-ac__menu").forEach((menu) => {
    if (exceptWrap && exceptWrap.contains(menu)) return;
    menu.hidden = true;
    menu.innerHTML = "";
  });
  document.querySelectorAll(".fp-team-ac__input").forEach((input) => {
    if (exceptWrap && exceptWrap.contains(input)) return;
    input.setAttribute("aria-expanded", "false");
  });
}

const playerAutocompleteUi = {
  openMenu: null,
  openInput: null,
  openWrap: null,
};

function closePlayerAutocompleteMenus(exceptWrap = null) {
  if (exceptWrap && playerAutocompleteUi.openWrap === exceptWrap) return;
  if (playerAutocompleteUi.openMenu) {
    hidePlayerAutocompleteMenu(playerAutocompleteUi.openMenu, playerAutocompleteUi.openInput);
  }
  document.querySelectorAll(".fp-player-ac__menu").forEach((menu) => {
    if (!menu.hidden) hidePlayerAutocompleteMenu(menu);
  });
  document.querySelectorAll(".fp-player-ac__input").forEach((input) => {
    if (exceptWrap && exceptWrap.contains(input)) return;
    input.setAttribute("aria-expanded", "false");
  });
}

function openTeamAutocompleteMenu(input, menu, options, activeIndex = 0) {
  if (!options.length) {
    menu.hidden = true;
    menu.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    return;
  }
  const query = input.value.trim();
  menu.innerHTML = options
    .map((entry, index) => {
      const name = entry.name || entry;
      const meta = entry.country_label || entry.country || "FotMob";
      return `
      <button type="button" class="fp-team-ac__option${index === activeIndex ? " fp-team-ac__option--active" : ""}" data-team-option="${escapeHtml(name)}" role="option" aria-selected="${index === activeIndex ? "true" : "false"}">
        <span class="fp-team-ac__option-name">${highlightTeamMatch(name, query)}</span>
        <span class="fp-team-ac__option-meta">${escapeHtml(meta)}</span>
      </button>
    `;
    })
    .join("");
  menu.hidden = false;
  input.setAttribute("aria-expanded", "true");
  menu.dataset.activeIndex = String(activeIndex);
}

function enhanceTeamAutocomplete(input) {
  if (!input || input.dataset.teamAcBound === "1") return;
  input.dataset.teamAcBound = "1";
  input.classList.add("fp-team-ac__input");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("list");

  const wrap = document.createElement("div");
  wrap.className = "fp-team-ac";
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);

  const menu = document.createElement("div");
  menu.className = "fp-team-ac__menu";
  menu.hidden = true;
  menu.setAttribute("role", "listbox");
  wrap.appendChild(menu);

  let activeIndex = 0;
  let currentOptions = [];

  const refresh = () => {
    currentOptions = filterTeamNameSuggestions(input.value);
    activeIndex = 0;
    openTeamAutocompleteMenu(input, menu, currentOptions, activeIndex);
  };

  const choose = (name) => {
    input.value = name;
    input.classList.add("fp-team-ac__input--matched");
    menu.hidden = true;
    menu.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };

  input.addEventListener("focus", () => {
    closeTeamAutocompleteMenus(wrap);
    closePlayerAutocompleteMenus();
    refresh();
  });
  input.addEventListener("input", () => {
    input.classList.remove("fp-team-ac__input--matched");
    refresh();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (menu.hidden) refresh();
      if (!currentOptions.length) return;
      activeIndex = (activeIndex + 1) % currentOptions.length;
      openTeamAutocompleteMenu(input, menu, currentOptions, activeIndex);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!currentOptions.length) return;
      activeIndex = (activeIndex - 1 + currentOptions.length) % currentOptions.length;
      openTeamAutocompleteMenu(input, menu, currentOptions, activeIndex);
    } else if (event.key === "Enter") {
      const selected = currentOptions[activeIndex];
      if (!menu.hidden && selected) {
        event.preventDefault();
        choose(selected.name || selected);
      }
    } else if (event.key === "Escape") {
      menu.hidden = true;
      menu.innerHTML = "";
      input.setAttribute("aria-expanded", "false");
    }
  });
  menu.addEventListener("mousedown", (event) => {
    const option = event.target.closest("[data-team-option]");
    if (!option) return;
    event.preventDefault();
    choose(option.dataset.teamOption || "");
  });
  input.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (wrap.contains(document.activeElement)) return;
      menu.hidden = true;
      menu.innerHTML = "";
      input.setAttribute("aria-expanded", "false");
      snapTeamInputToCatalog(input);
    }, 120);
  });
}

function bindTeamAutocompletes(root = document) {
  root.querySelectorAll("[data-team-autocomplete]").forEach((input) => enhanceTeamAutocomplete(input));
}

async function ensureTeamNameSuggestions() {
  const local = teamNamesFromPayload(state.payload);
  if (local.length) {
    setTeamNameCatalog(local);
  }
  if (state.teamNamesLoaded && state.teamNames.length) {
    return state.teamNames;
  }
  try {
    const season = state.season && state.season !== "ALL" ? state.season : "";
    const query = season ? `?season=${encodeURIComponent(season)}` : "";
    const data = await fetchJson(`/api/fixture-planner/team-names${query}`);
    const remote = Array.isArray(data.teams) ? data.teams : [];
    setTeamNameCatalog([...local, ...remote]);
    state.teamNamesLoaded = true;
  } catch (error) {
    if (!state.teamNames.length && local.length) {
      setTeamNameCatalog(local);
    }
    console.warn("Could not load team name suggestions", error);
  }
  return state.teamNames;
}

function manualPlayerRowMarkup(index = 0) {
  return `
    <div class="fp-manual-player-row" data-manual-player-row>
      <div class="fp-player-ac" data-player-ac>
        <input type="text" data-manual-player-name data-player-autocomplete placeholder="Search player…" autocomplete="off" aria-autocomplete="list" aria-expanded="false" />
        <a class="fp-player-ac__link" data-manual-player-link hidden target="_blank" rel="noopener" title="Open player page" aria-label="Open player page">↗</a>
        <div class="fp-player-ac__menu" hidden role="listbox"></div>
      </div>
      <input type="text" data-manual-player-team data-team-autocomplete placeholder="Club / team" autocomplete="off" />
      <select data-manual-player-side>
        <option value="">Side</option>
        <option value="home">Home</option>
        <option value="away">Away</option>
      </select>
      <input type="text" data-manual-player-position placeholder="Pos" autocomplete="off" />
      <button type="button" class="fp-btn fp-btn--ghost" data-manual-player-remove aria-label="Remove player">×</button>
    </div>
  `;
}

function renderManualPlayerRows(count = 2) {
  if (!els.manualPlayersList) return;
  els.manualPlayersList.innerHTML = Array.from({ length: Math.max(1, count) }, (_, index) =>
    manualPlayerRowMarkup(index),
  ).join("");
  bindTeamAutocompletes(els.manualPlayersList);
  bindPlayerAutocompletes(els.manualPlayersList);
}

function collectManualPlayers() {
  if (!els.manualPlayersList) return [];
  return [...els.manualPlayersList.querySelectorAll("[data-manual-player-row]")]
    .map((row) => {
      const playerId = Number(row.dataset.playerId || 0);
      return {
        player_name: row.querySelector("[data-manual-player-name]")?.value?.trim() || "",
        team: row.querySelector("[data-manual-player-team]")?.value?.trim() || "",
        side: row.querySelector("[data-manual-player-side]")?.value || "",
        position: row.querySelector("[data-manual-player-position]")?.value?.trim() || "",
        player_id: playerId > 0 ? playerId : undefined,
      };
    })
    .filter((row) => row.player_name);
}

function playerCatalogClub(player) {
  return String(
    player?.club ||
      player?.context_club ||
      player?.seasons?.[0]?.club ||
      "",
  ).trim();
}

function playerCatalogMeta(player) {
  const club = playerCatalogClub(player);
  const label = String(player?.label || "").trim();
  if (club && label && !label.toLowerCase().includes(club.toLowerCase())) {
    return `${club} · ${label}`;
  }
  return club || label || "Impect";
}

function setManualPlayerSelection(row, player) {
  if (!row) return;
  const nameInput = row.querySelector("[data-manual-player-name]");
  const teamInput = row.querySelector("[data-manual-player-team]");
  const link = row.querySelector("[data-manual-player-link]");
  const name = String(player?.name || "").trim();
  const id = Number(player?.impect_player_id || player?.playerId || player?.id || 0);
  if (nameInput && name) {
    nameInput.value = name;
    nameInput.classList.add("fp-player-ac__input--matched");
  }
  if (id > 0) {
    row.dataset.playerId = String(id);
    if (link) {
      link.href = `/player/${id}`;
      link.hidden = false;
    }
  } else {
    delete row.dataset.playerId;
    if (link) {
      link.removeAttribute("href");
      link.hidden = true;
    }
  }
  const club = playerCatalogClub(player);
  if (teamInput && club && !teamInput.value.trim()) {
    teamInput.value = club;
    snapTeamInputToCatalog(teamInput);
  }
}

function clearManualPlayerSelection(row) {
  if (!row) return;
  delete row.dataset.playerId;
  const nameInput = row.querySelector("[data-manual-player-name]");
  const link = row.querySelector("[data-manual-player-link]");
  nameInput?.classList.remove("fp-player-ac__input--matched");
  if (link) {
    link.removeAttribute("href");
    link.hidden = true;
  }
}

async function searchPlayerCatalog(query, { team = "", limit = 8 } = {}) {
  const clean = String(query || "").trim();
  if (clean.length < 2) return [];
  try {
    const data = await fetchJson("/api/players", {
      method: "POST",
      body: JSON.stringify({ search: clean }),
    });
    let players = Array.isArray(data.players) ? data.players : [];
    const teamNorm = String(team || "").trim().toLowerCase();
    if (teamNorm) {
      const byClub = players.filter((row) => {
        const club = playerCatalogClub(row).toLowerCase();
        const label = String(row.label || "").toLowerCase();
        return club.includes(teamNorm) || teamNorm.includes(club) || label.includes(teamNorm);
      });
      if (byClub.length) players = byClub;
    }
    return players.slice(0, limit);
  } catch {
    return [];
  }
}

function hidePlayerAutocompleteMenu(menu, input = null) {
  if (!menu) return;
  menu.hidden = true;
  menu.innerHTML = "";
  menu.classList.remove("fp-player-ac__menu--fixed");
  menu.style.cssText = "";
  if (input) input.setAttribute("aria-expanded", "false");
  if (playerAutocompleteUi.openMenu === menu) {
    playerAutocompleteUi.openMenu = null;
    playerAutocompleteUi.openInput = null;
    playerAutocompleteUi.openWrap = null;
  }
}

function positionPlayerAutocompleteMenu(input, menu) {
  const rect = input.getBoundingClientRect();
  const width = Math.max(rect.width, 280);
  const left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
  let top = rect.bottom + 6;
  menu.hidden = false;
  menu.classList.add("fp-player-ac__menu--fixed");
  const menuHeight = Math.min(menu.scrollHeight || 240, 280);
  if (top + menuHeight > window.innerHeight - 12 && rect.top > menuHeight + 12) {
    top = rect.top - menuHeight - 6;
  }
  menu.style.position = "fixed";
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.style.width = `${width}px`;
  menu.style.right = "auto";
  menu.style.zIndex = "240";
  if (menu.parentElement !== document.body) {
    document.body.appendChild(menu);
  }
  playerAutocompleteUi.openMenu = menu;
  playerAutocompleteUi.openInput = input;
  playerAutocompleteUi.openWrap = input.closest("[data-player-ac]");
}

function openPlayerAutocompleteMenu(input, menu, options, activeIndex = 0, { emptyMessage = "" } = {}) {
  const query = input.value.trim();
  if (!options.length) {
    if (!emptyMessage) {
      hidePlayerAutocompleteMenu(menu, input);
      return;
    }
    menu.innerHTML = `<div class="fp-player-ac__empty">${escapeHtml(emptyMessage)}</div>`;
    positionPlayerAutocompleteMenu(input, menu);
    input.setAttribute("aria-expanded", "true");
    menu.dataset.activeIndex = "-1";
    return;
  }
  menu.innerHTML = options
    .map((player, index) => {
      const name = String(player.name || "").trim();
      const id = Number(player.impect_player_id || player.id || 0);
      return `
      <button type="button" class="fp-player-ac__option${index === activeIndex ? " fp-player-ac__option--active" : ""}" data-player-option-index="${index}" data-player-id="${id}" role="option" aria-selected="${index === activeIndex ? "true" : "false"}">
        <span class="fp-player-ac__option-name">${highlightTeamMatch(name, query)}</span>
        <span class="fp-player-ac__option-meta">${escapeHtml(playerCatalogMeta(player))}</span>
      </button>
    `;
    })
    .join("");
  positionPlayerAutocompleteMenu(input, menu);
  input.setAttribute("aria-expanded", "true");
  menu.dataset.activeIndex = String(activeIndex);
}

function enhancePlayerAutocomplete(input) {
  if (!input || input.dataset.playerAcBound === "1") return;
  input.dataset.playerAcBound = "1";
  input.classList.add("fp-player-ac__input");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");

  const wrap = input.closest("[data-player-ac]");
  const row = input.closest("[data-manual-player-row]");
  let menu = wrap?.querySelector(".fp-player-ac__menu");
  if (!wrap) return;
  if (!menu) {
    menu = document.createElement("div");
    menu.className = "fp-player-ac__menu";
    menu.hidden = true;
    menu.setAttribute("role", "listbox");
    wrap.appendChild(menu);
  }

  let activeIndex = 0;
  let currentOptions = [];
  let searchToken = 0;
  let debounceTimer = 0;

  const closeMenu = () => hidePlayerAutocompleteMenu(menu, input);

  const refresh = async () => {
    const query = input.value.trim();
    if (query.length < 2) {
      currentOptions = [];
      openPlayerAutocompleteMenu(input, menu, [], 0, {
        emptyMessage: "Type at least 2 letters to search players",
      });
      return;
    }
    const token = ++searchToken;
    openPlayerAutocompleteMenu(input, menu, [], 0, { emptyMessage: "Searching…" });
    const team = row?.querySelector("[data-manual-player-team]")?.value || "";
    const options = await searchPlayerCatalog(query, { team });
    if (token !== searchToken) return;
    currentOptions = options;
    activeIndex = 0;
    openPlayerAutocompleteMenu(input, menu, currentOptions, activeIndex, {
      emptyMessage: `No players matched “${query}”`,
    });
  };

  const choose = (player) => {
    setManualPlayerSelection(row, player);
    closeMenu();
  };

  input.addEventListener("focus", () => {
    closeTeamAutocompleteMenus();
    closePlayerAutocompleteMenus(wrap);
    refresh();
  });
  input.addEventListener("input", () => {
    clearManualPlayerSelection(row);
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(() => {
      refresh();
    }, 180);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (menu.hidden) refresh();
      if (!currentOptions.length) return;
      activeIndex = (activeIndex + 1) % currentOptions.length;
      openPlayerAutocompleteMenu(input, menu, currentOptions, activeIndex);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!currentOptions.length) return;
      activeIndex = (activeIndex - 1 + currentOptions.length) % currentOptions.length;
      openPlayerAutocompleteMenu(input, menu, currentOptions, activeIndex);
    } else if (event.key === "Enter") {
      if (!menu.hidden && currentOptions[activeIndex]) {
        event.preventDefault();
        choose(currentOptions[activeIndex]);
      }
    } else if (event.key === "Escape") {
      closeMenu();
    }
  });
  menu.addEventListener("mousedown", (event) => {
    const option = event.target.closest("[data-player-option-index]");
    if (!option) return;
    event.preventDefault();
    const index = Number(option.dataset.playerOptionIndex || -1);
    if (index >= 0 && currentOptions[index]) choose(currentOptions[index]);
  });
  const reposition = () => {
    if (!menu.hidden) positionPlayerAutocompleteMenu(input, menu);
  };
  window.addEventListener("resize", reposition);
  document.querySelector(".fp-assign-modal__body")?.addEventListener("scroll", reposition, { passive: true });
  input.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (wrap.contains(document.activeElement) || menu.contains(document.activeElement)) return;
      closeMenu();
    }, 160);
  });
}

function bindPlayerAutocompletes(root = document) {
  root.querySelectorAll("[data-player-autocomplete]").forEach((input) => enhancePlayerAutocomplete(input));
}

function tomorrowKey() {
  const now = new Date();
  now.setDate(now.getDate() + 1);
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function configureManualFixtureModalChrome() {
  const title = document.getElementById("manualFixtureTitle");
  const meta = document.getElementById("manualFixtureMeta");
  const eyebrow = document.getElementById("manualFixtureEyebrow");
  const playersHeading = document.getElementById("manualPlayersHeading");
  const playersHelp = document.getElementById("manualPlayersHelp");
  const notesLabel = document.getElementById("manualNotesLabel");
  const scoreField = document.getElementById("manualScoreField");
  const teamSheetField = document.getElementById("manualTeamSheetField");
  if (IS_PLAYED_APP) {
    if (title) title.textContent = "Create manual fixture";
    if (eyebrow) eyebrow.textContent = "Outside the pulled schedule";
    if (meta) {
      meta.textContent = "For games you attended that aren’t in the league pulls.";
    }
    if (playersHeading) playersHeading.textContent = "Players watched";
    if (playersHelp) {
      playersHelp.textContent =
        "Click a player name field and type 2+ letters — pick from the list (Scout Summary marks them reported).";
    }
    if (notesLabel) notesLabel.textContent = "Game notes";
    if (els.manualFixtureSaveBtn) els.manualFixtureSaveBtn.textContent = "Save fixture";
    if (els.createManualFixtureBtn) els.createManualFixtureBtn.textContent = "Create manual fixture";
    scoreField?.classList.remove("hidden");
    teamSheetField?.classList.remove("hidden");
  } else {
    if (title) title.textContent = "Add upcoming game";
    if (eyebrow) eyebrow.textContent = "Outside the pulled schedule";
    if (meta) {
      meta.textContent = "Add a future game that isn’t in the league pulls, then assign coverage as usual.";
    }
    if (playersHeading) playersHeading.textContent = "Players to watch";
    if (playersHelp) {
      playersHelp.textContent =
        "Click a player name field and type 2+ letters — pick from the list, then open their page with ↗.";
    }
    if (notesLabel) notesLabel.textContent = "Notes";
    if (els.manualFixtureSaveBtn) els.manualFixtureSaveBtn.textContent = "Save game";
    if (els.createManualFixtureBtn) els.createManualFixtureBtn.textContent = "Add upcoming game";
    scoreField?.classList.add("hidden");
    // Keep team sheet available for upcoming too (optional).
    teamSheetField?.classList.remove("hidden");
  }
}

function openManualFixtureModal() {
  if (!els.manualFixtureModal) return;
  configureManualFixtureModalChrome();
  populateManualStaffSelect();
  ensureTeamNameSuggestions().catch(() => {});
  els.manualFixtureForm?.reset();
  const dateInput = document.getElementById("manualDate");
  if (dateInput) {
    dateInput.value = IS_PLAYED_APP ? todayKey() : tomorrowKey();
  }
  const leagueInput = document.getElementById("manualLeague");
  if (leagueInput) {
    leagueInput.value = "Manual";
  }
  renderManualPlayerRows(IS_PLAYED_APP ? 3 : 2);
  bindTeamAutocompletes(els.manualFixtureModal);
  els.manualFixtureModal.classList.remove("fp-assign-modal--hidden");
  els.manualFixtureModal.setAttribute("aria-hidden", "false");
  document.getElementById("manualHome")?.focus();
}

function closeManualFixtureModal() {
  if (!els.manualFixtureModal) return;
  els.manualFixtureModal.classList.add("fp-assign-modal--hidden");
  els.manualFixtureModal.setAttribute("aria-hidden", "true");
  if (els.manualTeamSheet) {
    els.manualTeamSheet.value = "";
  }
}

async function saveManualFixture() {
  snapTeamInputToCatalog(document.getElementById("manualHome"));
  snapTeamInputToCatalog(document.getElementById("manualAway"));
  els.manualPlayersList
    ?.querySelectorAll("[data-manual-player-team]")
    .forEach((input) => snapTeamInputToCatalog(input));
  const home = document.getElementById("manualHome")?.value?.trim() || "";
  const away = document.getElementById("manualAway")?.value?.trim() || "";
  const date = document.getElementById("manualDate")?.value || "";
  if (!home || !away || !date) {
    els.statusBar.textContent = "Home, away and date are required.";
    return;
  }
  const kickoff = document.getElementById("manualKickoff")?.value || "";
  const league = document.getElementById("manualLeague")?.value?.trim() || "Manual";
  const score = document.getElementById("manualScore")?.value?.trim() || "";
  const venue = document.getElementById("manualVenue")?.value?.trim() || "";
  const notes = document.getElementById("manualNotes")?.value?.trim() || "";
  const staff = collectManualStaff();
  const watchType = document.getElementById("manualWatchType")?.value || "LIVE";
  const players = collectManualPlayers();
  const resolvedPlayers = [];
  for (const player of players) {
    const playerId =
      Number(player.player_id || 0) > 0
        ? Number(player.player_id)
        : await resolvePlayerCatalogId(player.player_name, player.team);
    resolvedPlayers.push({
      ...player,
      player_id: playerId || undefined,
    });
  }

  if (els.manualFixtureSaveBtn) {
    els.manualFixtureSaveBtn.disabled = true;
    els.manualFixtureSaveBtn.textContent = "Saving…";
  }

  try {
    const created = await fetchJson("/api/fixture-planner/manual-fixtures", {
      method: "POST",
      body: JSON.stringify({
        season: state.season,
        league,
        competition: league,
        home,
        away,
        date,
        kickoff,
        score: IS_PLAYED_APP ? score : "",
        venue,
        notes,
        staff,
        watch_type: watchType,
        players: resolvedPlayers,
        mark_reports: IS_PLAYED_APP,
        status: IS_PLAYED_APP ? "completed" : "scheduled",
      }),
    });
    const fixtureIdValue = created?.fixture?.fixture_id || "";
    const file = els.manualTeamSheet?.files?.[0];
    if (file && fixtureIdValue) {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `/api/fixture-planner/manual-fixtures/${encodeURIComponent(fixtureIdValue)}/team-sheet`,
        { method: "POST", body: form },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Fixture saved, but team sheet upload failed.");
      }
    }
    closeManualFixtureModal();
    await loadFixtures();
    els.statusBar.textContent = `Manual fixture saved: ${home} vs ${away}`;
  } catch (error) {
    els.statusBar.textContent = error.message || "Could not save manual fixture.";
  } finally {
    if (els.manualFixtureSaveBtn) {
      els.manualFixtureSaveBtn.disabled = false;
      els.manualFixtureSaveBtn.textContent = "Save fixture";
    }
  }
}

function bindManualFixtureUi() {
  if (!els.manualFixtureModal) return;
  els.createManualFixtureBtn?.addEventListener("click", openManualFixtureModal);
  els.manualFixtureModal.querySelectorAll("[data-manual-close]").forEach((btn) => {
    btn.addEventListener("click", closeManualFixtureModal);
  });
  els.manualAddPlayerBtn?.addEventListener("click", () => {
    if (!els.manualPlayersList) return;
    els.manualPlayersList.insertAdjacentHTML("beforeend", manualPlayerRowMarkup());
    bindTeamAutocompletes(els.manualPlayersList);
    bindPlayerAutocompletes(els.manualPlayersList);
  });
  els.manualPlayersList?.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-manual-player-remove]");
    if (!remove) return;
    const row = remove.closest("[data-manual-player-row]");
    row?.remove();
    if (!els.manualPlayersList.querySelector("[data-manual-player-row]")) {
      renderManualPlayerRows(1);
    }
  });
  document.addEventListener("pointerdown", (event) => {
    const teamWrap = event.target.closest?.(".fp-team-ac");
    const playerWrap = event.target.closest?.(".fp-player-ac");
    const playerMenu = event.target.closest?.(".fp-player-ac__menu");
    if (playerMenu) return;
    if (teamWrap) {
      closeTeamAutocompleteMenus(teamWrap);
      closePlayerAutocompleteMenus();
      return;
    }
    if (playerWrap) {
      closePlayerAutocompleteMenus(playerWrap);
      closeTeamAutocompleteMenus();
      return;
    }
    closeTeamAutocompleteMenus();
    closePlayerAutocompleteMenus();
  });
  els.manualFixtureSaveBtn?.addEventListener("click", () => {
    saveManualFixture();
  });
}

async function init() {
  if (els.pageSubtitle && IS_PLAYED_APP) {
    els.pageSubtitle.textContent =
      "Games that have taken place · LIVE coverage carries over · create a manual fixture when the game isn’t in the pulled list";
  }
  if (els.createManualFixtureBtn) {
    els.createManualFixtureBtn.classList.remove("hidden");
    configureManualFixtureModalChrome();
  }

  await loadAssignmentsFromServer();

  if (IS_PLAYED_APP) {
    state.hidePast = false;
    state.playedOnly = true;
    document.getElementById("hidePastControl")?.classList.add("hidden");
    els.ticketRequestBtn?.classList.add("hidden");
    els.scheduleUpdateBtn?.classList.add("hidden");
    if (els.assignConfirmBtn) {
      els.assignConfirmBtn.textContent = "Save coverage";
    }
  } else {
    state.hidePast = true;
    state.playedOnly = false;
    if (els.hidePastToggle) {
      els.hidePastToggle.checked = true;
      els.hidePastToggle.disabled = true;
    }
  }

  document.querySelectorAll(".fp-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.classList.contains("fp-view-btn--active")) return;
      document.querySelectorAll(".fp-view-btn").forEach((item) => item.classList.remove("fp-view-btn--active"));
      btn.classList.add("fp-view-btn--active");
      state.view = btn.dataset.view;
      renderView();
    });
  });

  document.querySelectorAll("[data-comp-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const tab = btn.dataset.compTab;
      const nextScope =
        tab === "cups" ? "cups" : tab === "all" ? "all" : tab === "germany" ? "germany" : "leagues";
      setCompetitionScope(nextScope, {
        refetch:
          (nextScope === "cups" || nextScope === "all" || nextScope === "germany") &&
          state.compScope === "leagues",
      });
    });
  });

  els.staffFilter?.addEventListener("change", () => {
    state.staffFilter = els.staffFilter.value;
    renderSummary();
    renderView();
  });

  els.monthFilter?.addEventListener("change", () => {
    state.monthFilter = els.monthFilter.value;
    renderSummary();
    renderView();
  });

  els.hidePastToggle?.addEventListener("change", () => {
    state.hidePast = els.hidePastToggle.checked;
    if (!state.hidePast && !state.monthFilter) {
      const count = fixturesForLeagues().length;
      if (count > MAX_UNFILTERED_FIXTURES) {
        state.monthFilter = defaultMonthForPastView();
        if (els.monthFilter) {
          els.monthFilter.value = state.monthFilter;
        }
      }
    }
    renderMonthFilter();
    renderSummary();
    renderView();
  });

  els.refreshBtn.addEventListener("click", () => loadFixtures({ forceRefresh: true }));

  els.ticketRequestBtn?.addEventListener("click", () => sendBulkEmail("ticket-request"));
  els.scheduleUpdateBtn?.addEventListener("click", () => sendBulkEmail("schedule-update"));
  els.ticketModal?.querySelectorAll("[data-ticket-close]").forEach((btn) => {
    btn.addEventListener("click", closeTicketRequestModal);
  });
  els.ticketModalBody?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-ticket-remove]");
    if (!btn) return;
    event.preventDefault();
    btn.closest(".fp-ticket-card")?.remove();
    syncTicketRequestUi();
  });
  els.ticketConfirmBtn?.addEventListener("click", confirmTicketRequest);

  els.assignModal?.querySelectorAll("[data-assign-close]").forEach((btn) => {
    btn.addEventListener("click", closeAssignModal);
  });
  els.assignConfirmBtn?.addEventListener("click", confirmAssignModal);
  els.assignModalWatch?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-assign-watch]");
    if (!btn || !state.assignModal) return;
    state.assignModal.watchType = btn.dataset.assignWatch || "LIVE";
    renderAssignModalChrome();
  });

  // Match details opens as a popup (not an inline accordion).
  const onOpenMatchDetails = (event) => {
    const button = event.target.closest("[data-open-match-details]");
    if (!button) return;
    event.preventDefault();
    openMatchDetailsModal(button.dataset.openMatchDetails || "");
  };
  els.listRoot?.addEventListener("click", onOpenMatchDetails);
  els.calendarRoot?.addEventListener("click", onOpenMatchDetails);

  els.matchDetailsModal?.querySelectorAll("[data-match-details-close]").forEach((btn) => {
    btn.addEventListener("click", closeMatchDetailsModal);
  });

  const onReportClick = (event) => {
    if (event.target.closest("summary, a, .so-match-team__details-summary")) return;
    const target = event.target.closest("[data-player-id]");
    if (!target || !els.matchDetailsBody?.contains(target)) return;
    event.preventDefault();
    toggleLineupReport(target);
  };
  els.matchDetailsModal?.addEventListener("click", onReportClick);
  els.matchDetailsModal?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target.closest("[data-player-id]");
    if (!target || !els.matchDetailsBody?.contains(target)) return;
    event.preventDefault();
    toggleLineupReport(target);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.matchDetailsFixtureId) {
      closeMatchDetailsModal();
    }
    if (event.key === "Escape" && els.manualFixtureModal && !els.manualFixtureModal.classList.contains("fp-assign-modal--hidden")) {
      closeManualFixtureModal();
    }
  });

  bindManualFixtureUi();

  try {
    state.meta = await fetchJson("/api/fixture-planner/meta");
    state.season = state.meta.season || DEFAULT_SEASON;
    state.leagues = [...(state.meta.default_leagues || [])];

    if (els.staffFilter) {
      const teams = staffTeams();
      const grouped = teams
        .map((team) => {
          const members = team.members || [];
          if (!members.length) {
            return `<optgroup label="${escapeHtml(team.label)}"><option value="" disabled>No one listed yet</option></optgroup>`;
          }
          return `<optgroup label="${escapeHtml(team.label)}">${members
            .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
            .join("")}</optgroup>`;
        })
        .join("");
      els.staffFilter.innerHTML = `<option value="">All staff</option>${grouped}`;
    }

    renderSeasonToggle();
    renderLeagueToggle();
    await loadFixtures();
  } catch (error) {
    setStatus(error.message, "error");
    els.statusBar.textContent = "Could not load fixture planner.";
  }
}

init();
