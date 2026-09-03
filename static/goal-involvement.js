const POINTS = 10;
const COACH_KEY = "gi.coach";

const state = {
  boot: null,
  view: "home",
  season: "",
  coach: localStorage.getItem(COACH_KEY) || "",
  sheetGoal: null,
  sheetMode: "score",
  allocations: {},
  autoSyncStarted: false,
  matrix: null,
  matrixOnly: false,
  matrixSide: "all",
  boardSort: { field: "net", dir: "desc" },
  playType: "all",
  matrixDraft: {},
};

const els = {
  seasonSelect: document.getElementById("seasonSelect"),
  coachSelect: document.getElementById("coachSelect"),
  refreshBtn: document.getElementById("refreshBtn"),
  pageSub: document.getElementById("pageSub"),
  status: document.getElementById("statusBanner"),
  homeView: document.getElementById("homeView"),
  matrixView: document.getElementById("matrixView"),
  adminView: document.getElementById("adminView"),
  adminTab: document.getElementById("adminTab"),
  sheet: document.getElementById("sheet"),
  sheetPanel: document.getElementById("sheetPanel"),
};

function setStatus(message, kind = "") {
  if (!message) {
    els.status.classList.add("hidden");
    els.status.textContent = "";
    return;
  }
  els.status.className = `gi-status ${kind ? `gi-status--${kind}` : ""}`;
  els.status.textContent = message;
  if (kind === "ok") setTimeout(() => setStatus(""), 4000);
}

async function fetchJson(url, options = {}) {
  const joined = url.includes("?") ? `${url}&_=${Date.now()}` : `${url}?_=${Date.now()}`;
  const res = await fetch(joined, {
    cache: "no-store",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    const detail = data.detail || data.error || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function coachParam() {
  return state.coach ? `coach_id=${encodeURIComponent(state.coach)}` : "";
}

function photoUrl(player) {
  return player.photo_url || `/api/player-photo?name=${encodeURIComponent(player.name || "")}`;
}

function remaining() {
  const used = Object.values(state.allocations).reduce((sum, n) => sum + Number(n || 0), 0);
  return POINTS - used;
}

function goals() {
  return state.boot?.goals || [];
}

function pendingGoals() {
  return goals().filter((goal) => goal.status === "open" && !goal.i_have_scored);
}

function coachName(id) {
  const row = (state.boot?.coaches || []).find((coach) => coach.id === id);
  return row ? row.display_name : id;
}

function setView(view) {
  let allowed = "home";
  if (view === "matrix") allowed = "matrix";
  if (view === "admin" && state.boot?.me?.is_admin) allowed = "admin";
  state.view = allowed;
  document.querySelectorAll(".gi-tab").forEach((tab) => {
    tab.classList.toggle("gi-tab--active", tab.dataset.view === allowed);
  });
  els.homeView.classList.toggle("hidden", allowed !== "home");
  els.matrixView.classList.toggle("hidden", allowed !== "matrix");
  els.adminView.classList.toggle("hidden", allowed !== "admin");
  window.scrollTo(0, 0);
  if (allowed === "admin") {
    els.pageSub.textContent = "Sync, clips, close goals, send WhatsApp";
    loadAdmin();
  } else if (allowed === "matrix") {
    els.pageSub.textContent = "Every goal · every coach · splits highlighted";
    loadMatrix();
  } else if (state.boot) {
    renderHome();
  }
}

function renderSelects() {
  const seasons = state.boot?.seasons || [];
  els.seasonSelect.innerHTML = seasons
    .map(
      (row) =>
        `<option value="${escapeHtml(row.value)}" ${row.value === state.season ? "selected" : ""}>${escapeHtml(row.label || row.value)}</option>`
    )
    .join("");
  const coaches = (state.boot?.coaches || []).filter((coach) => coach.active);
  els.coachSelect.innerHTML = `
    <option value="">Who are you?</option>
    ${coaches
      .map(
        (coach) =>
          `<option value="${escapeHtml(coach.id)}" ${coach.id === state.coach ? "selected" : ""}>${escapeHtml(coach.display_name)} (${escapeHtml(coach.id)})</option>`
      )
      .join("")}
  `;
  els.coachSelect.classList.toggle("gi-select--warn", !state.coach);
}

function goalTitle(goal) {
  const home = goal.venue === "Home" ? "Vale" : goal.opponent;
  const away = goal.venue === "Home" ? goal.opponent : "Vale";
  return `${home} ${goal.scoreline || ""} ${away}`;
}

function goalCard(goal, { actionLabel } = {}) {
  const pill = goal.team_for_or_against === "scored" ? "gi-pill--scored" : "gi-pill--conceded";
  const wait = goal.i_have_scored
    ? `<span class="gi-pill gi-pill--done">${goal.submitted_count}/${goal.expected} in</span>`
    : `<span class="gi-pill gi-pill--wait">Your turn</span>`;
  const flag = goal.revealed && goal.agreement?.flagged
    ? `<span class="gi-pill gi-pill--flag">${escapeHtml(goal.agreement.label)}</span>`
    : "";
  const clipMark = goal.clip?.has_clip
    ? `<span class="gi-pill gi-pill--done">Clip</span>`
    : state.boot?.me?.is_admin
      ? `<span class="gi-pill">No clip</span>`
      : "";
  return `
    <article class="gi-card gi-card--tap" data-goal-id="${escapeHtml(goal.id)}">
      <p class="gi-kicker">${escapeHtml(goal.date || "")} · ${escapeHtml(goal.venue || "")} · ${escapeHtml(goal.competition || "")}</p>
      <div class="gi-row">
        <h3>${escapeHtml(goalTitle(goal))}</h3>
        <span class="gi-pill ${pill}">${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")}</span>
      </div>
      <p class="gi-muted">${goal.scorer_name ? `Scorer ${escapeHtml(goal.scorer_name)} · ` : ""}from ${escapeHtml(goal.scoreline_before || "0-0")}</p>
      <div class="gi-row" style="margin-top:.4rem">
        <span>${wait} ${flag} ${clipMark}</span>
        <strong>${escapeHtml(actionLabel || (goal.i_have_scored ? "View" : "Score now"))}</strong>
      </div>
    </article>
  `;
}

function formatPts(value) {
  const n = Number(value || 0);
  return n.toFixed(1);
}

function formatNet(value) {
  const n = Number(value || 0);
  if (n > 0) return `+${n.toFixed(1)}`;
  return n.toFixed(1);
}

function netClass(value) {
  const n = Number(value || 0);
  if (n > 0) return "gi-net gi-net--pos";
  if (n < 0) return "gi-net gi-net--neg";
  return "gi-net";
}

const BOARD_SORTS = {
  scored: { key: "scored_points", label: "goals for" },
  conceded: { key: "conceded_points", label: "goals against" },
  net: { key: "net_points", label: "net" },
};

function sortedBoardRows(rows) {
  const spec = BOARD_SORTS[state.boardSort.field] || BOARD_SORTS.net;
  const dir = state.boardSort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const diff = Number(a[spec.key] || 0) - Number(b[spec.key] || 0);
    if (diff !== 0) return diff * dir;
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
}

function boardSortButton(field, label) {
  const on = state.boardSort.field === field;
  const arrow = on ? (state.boardSort.dir === "asc" ? " ↑" : " ↓") : "";
  return `<button type="button" class="gi-board__sort ${on ? "gi-board__sort--on" : ""}" data-board-sort="${field}">${label}${arrow}</button>`;
}

function boardRankLabel() {
  const spec = BOARD_SORTS[state.boardSort.field] || BOARD_SORTS.net;
  const order = state.boardSort.dir === "asc" ? "low to high" : "high to low";
  const play = playTypeLabel();
  const playBit = play ? `${play} · ` : "";
  if (state.boardSort.field === "net") {
    return `${playBit}Ranked by net · goals for minus goals against · 10 points per goal`;
  }
  return `${playBit}Ranked by ${spec.label}, ${order} · 10 points per goal`;
}

function playTypeButtons() {
  const on = state.playType || "all";
  return `
    <div class="gi-mx-sides" role="group" aria-label="Open play or set play">
      <button type="button" class="gi-mx-side ${on === "all" ? "gi-mx-side--on" : ""}" data-play-type="all">All</button>
      <button type="button" class="gi-mx-side ${on === "open_play" ? "gi-mx-side--on" : ""}" data-play-type="open_play" title="Possession and transition">Open play</button>
      <button type="button" class="gi-mx-side ${on === "set_play" ? "gi-mx-side--on" : ""}" data-play-type="set_play">Set play</button>
    </div>
  `;
}

function playTypeLabel() {
  if (state.playType === "open_play") return "Open play";
  if (state.playType === "set_play") return "Set play";
  return "";
}

function renderBoardTable(table) {
  const rows = sortedBoardRows(table?.players || []);
  const counted = table?.goals_counted || 0;
  const provisional = Boolean(table?.provisional);
  const expected = table?.settings?.expected_coach_count || 5;
  const season = escapeHtml(state.season || "");
  if (!rows.length) {
    return `
      <section class="gi-board">
        <header class="gi-board__head">
          <p class="gi-board__eyebrow">Port Vale · ${season}</p>
          <h2>Goal involvement</h2>
          <p class="gi-board__sub">${boardRankLabel()}</p>
        </header>
        <p class="gi-muted" style="padding:0 1.1rem 1.1rem">No scores in yet. The table fills as coaches submit.</p>
      </section>
    `;
  }
  const maxInv = Math.max(1, ...rows.map((row) => Number(row.scored_points || 0)));
  const maxResp = Math.max(1, ...rows.map((row) => Number(row.conceded_points || 0)));
  return `
    <section class="gi-board">
      <header class="gi-board__head">
        <p class="gi-board__eyebrow">Port Vale · ${season}</p>
        <h2>Goal involvement</h2>
        <p class="gi-board__sub">${boardRankLabel()}</p>
        <p class="gi-board__live">${counted} goal${counted === 1 ? "" : "s"}${provisional ? ` · running totals, waiting on coaches (${expected} expected)` : " · all expected scores in"}</p>
      </header>
      <div class="gi-board__scroll">
        <table class="gi-board__table">
          <thead>
            <tr>
              <th class="gi-board__rank">#</th>
              <th>Player</th>
              <th class="gi-board__num">${boardSortButton("scored", "Goals for")}</th>
              <th class="gi-board__num">${boardSortButton("conceded", "Goals against")}</th>
              <th class="gi-board__num">${boardSortButton("net", "Net")}</th>
            </tr>
          </thead>
          <tbody>
            ${rows
              .map((row, index) => {
                const rank = index + 1;
                const top = state.boardSort.dir === "desc" && rank <= 3 ? `gi-board__row--top${rank}` : "";
                return `
              <tr class="${top}">
                <td class="gi-board__rank">${rank}</td>
                <td>
                  <div class="gi-league__player">
                    <img class="gi-avatar" alt="" src="${escapeHtml(row.photo_url || "")}" />
                    <strong>${escapeHtml(row.name)}</strong>
                  </div>
                </td>
                <td class="gi-board__num">
                  <div class="gi-bar"><span style="width:${(Number(row.scored_points) / maxInv) * 100}%"></span></div>
                  ${formatPts(row.scored_points)}
                </td>
                <td class="gi-board__num">
                  <div class="gi-bar"><span class="conceded" style="width:${(Number(row.conceded_points) / maxResp) * 100}%"></span></div>
                  ${formatPts(row.conceded_points)}
                </td>
                <td class="gi-board__num"><span class="${netClass(row.net_points)}">${formatNet(row.net_points)}</span></td>
              </tr>
            `;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function formatCell(value) {
  if (value == null || value === "") return "–";
  const n = Number(value);
  if (Number.isNaN(n)) return "–";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function goalHasSplit(goal) {
  if ((goal.agreement || {}).flagged) return true;
  return (goal.players || []).some((row) => row.flagged);
}

function filterMatrixGoals(allGoals) {
  let rows = allGoals;
  if (state.playType === "open_play" || state.playType === "set_play") {
    rows = rows.filter((goal) => goal.play_type === state.playType);
  }
  if (state.matrixSide === "scored" || state.matrixSide === "conceded") {
    rows = rows.filter((goal) => goal.team_for_or_against === state.matrixSide);
  }
  if (state.matrixOnly) rows = rows.filter(goalHasSplit);
  return rows;
}

function renderMatrix(payload) {
  const coaches = payload?.coaches || [];
  const allGoals = payload?.goals || [];
  const goals = filterMatrixGoals(allGoals);
  const splits = Number(payload?.anomaly_count || 0);
  const season = escapeHtml(state.season || "");
  const side = state.matrixSide;
  els.pageSub.textContent = splits
    ? `${splits} big split${splits === 1 ? "" : "s"} · tap a cell to edit · orange is 2+ points off`
    : "Tap a cell to edit · each coach column must add up to 10";
  if (!allGoals.length) {
    els.matrixView.innerHTML = `
      <section class="gi-board">
        <header class="gi-board__head">
          <p class="gi-board__eyebrow">Port Vale · ${season}</p>
          <h2>Score matrix</h2>
          <p class="gi-board__sub">No goals in this season yet.</p>
        </header>
      </section>
    `;
    return;
  }
  const emptyCopy = state.matrixOnly
    ? `<section class="gi-card"><h3>No big splits</h3><p class="gi-muted">Clear “Splits only”, or switch For / Against.</p></section>`
    : state.playType === "open_play"
      ? `<section class="gi-card"><h3>No open-play goals</h3><p class="gi-muted">Open play is possession and transition. Switch to All or Set play.</p></section>`
      : state.playType === "set_play"
        ? `<section class="gi-card"><h3>No set-play goals</h3><p class="gi-muted">Switch to All or Open play.</p></section>`
    : side === "scored"
      ? `<section class="gi-card"><h3>No goals for</h3><p class="gi-muted">Switch to All or Against.</p></section>`
      : side === "conceded"
        ? `<section class="gi-card"><h3>No goals against</h3><p class="gi-muted">Switch to All or For.</p></section>`
        : `<section class="gi-card"><p>Nothing to show.</p></section>`;
  els.matrixView.innerHTML = `
    <section class="gi-mx-toolbar">
      <p class="gi-muted">${goals.length} of ${allGoals.length} · ${coaches.map((row) => escapeHtml(row.id)).join(" · ")}</p>
      <div class="gi-mx-filters">
        ${playTypeButtons()}
        <div class="gi-mx-sides" role="group" aria-label="Goals for or against">
          <button type="button" class="gi-mx-side ${side === "all" ? "gi-mx-side--on" : ""}" data-matrix-side="all">All</button>
          <button type="button" class="gi-mx-side ${side === "scored" ? "gi-mx-side--on" : ""}" data-matrix-side="scored">For</button>
          <button type="button" class="gi-mx-side ${side === "conceded" ? "gi-mx-side--on" : ""}" data-matrix-side="conceded">Against</button>
        </div>
        <label class="gi-mx-toggle">
          <input type="checkbox" id="matrixOnly" ${state.matrixOnly ? "checked" : ""} />
          Splits only
        </label>
      </div>
    </section>
    ${goals.length ? goals.map((goal) => matrixGoal(goal, coaches)).join("") : emptyCopy}
  `;
  paintMatrixDrafts();
}

function matrixGoal(goal, coaches) {
  const flag = goalHasSplit(goal);
  const wait = `${goal.submitted_count}/${goal.expected} in`;
  const players = goal.players || [];
  const titleHome = goal.venue === "Home" ? "Vale" : goal.opponent;
  const titleAway = goal.venue === "Home" ? goal.opponent : "Vale";
  const pill = goal.team_for_or_against === "scored" ? "gi-pill--scored" : "gi-pill--conceded";
  const playMark = goal.play_label ? ` · ${escapeHtml(goal.play_label)}` : "";
  const closed = goal.status === "closed";
  if (!players.length) {
    return `
      <section class="gi-mx ${flag ? "gi-mx--flag" : ""}" data-goal-id="${escapeHtml(goal.id)}">
        <header class="gi-mx__head">
          <p class="gi-kicker">${escapeHtml(goal.date || "")} · ${escapeHtml(goal.venue || "")}${playMark}</p>
          <div class="gi-row">
            <h3>${escapeHtml(titleHome)} ${escapeHtml(goal.scoreline || "")} ${escapeHtml(titleAway)}</h3>
            <span class="gi-pill ${pill}">${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")}</span>
          </div>
          <p class="gi-muted">${wait} · no players listed yet</p>
        </header>
      </section>
    `;
  }
  return `
    <section class="gi-mx ${flag ? "gi-mx--flag" : ""}" data-mx-goal="${escapeHtml(goal.id)}">
      <header class="gi-mx__head" data-goal-id="${escapeHtml(goal.id)}">
        <p class="gi-kicker">${escapeHtml(goal.date || "")} · ${escapeHtml(goal.venue || "")}${goal.scorer_name ? ` · ${escapeHtml(goal.scorer_name)}` : ""}${playMark}${closed ? " · closed" : ""}</p>
        <div class="gi-row">
          <h3>${escapeHtml(titleHome)} ${escapeHtml(goal.scoreline || "")} ${escapeHtml(titleAway)}</h3>
          <span>
            <span class="gi-pill ${pill}">${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")}</span>
            ${flag ? `<span class="gi-pill gi-pill--flag">${escapeHtml(goal.agreement?.label || "Split")}</span>` : ""}
            <span class="gi-pill gi-pill--done">${wait}</span>
          </span>
        </div>
      </header>
      <div class="gi-mx__scroll">
        <table class="gi-mx__table">
          <thead>
            <tr>
              <th>Player</th>
              ${coaches
                .map(
                  (coach) => `
                <th title="${escapeHtml(coach.display_name)}">
                  ${escapeHtml(coach.id)}
                  <div class="gi-mx__remain" data-mx-remain="${escapeHtml(goal.id)}:${escapeHtml(coach.id)}"></div>
                  <button type="button" class="gi-btn gi-btn--primary gi-mx__save" data-mx-save="${escapeHtml(goal.id)}" data-mx-coach="${escapeHtml(coach.id)}" hidden>Save</button>
                </th>`
                )
                .join("")}
              <th>Avg</th>
            </tr>
          </thead>
          <tbody>
            ${players
              .map((row) => {
                const hotRow = row.flagged ? "gi-mx__row--flag" : "";
                return `
              <tr class="${hotRow}">
                <td>
                  <div class="gi-league__player">
                    <img class="gi-avatar" alt="" src="${escapeHtml(row.photo_url || "")}" />
                    <strong>${escapeHtml(row.name)}</strong>
                  </div>
                </td>
                ${coaches
                  .map((coach) => {
                    const value = matrixCellValue(goal, row.player_id, coach.id);
                    const hot = Boolean(row.outliers?.[coach.id]) && value != null;
                    const shown = value == null || value === "" ? "" : String(value);
                    return `<td class="${hot ? "gi-mx--hot" : ""}">
                      <input class="gi-mx__input" type="number" min="0" max="10" step="1" inputmode="numeric"
                        data-mx-cell data-mx-goal="${escapeHtml(goal.id)}" data-mx-coach="${escapeHtml(coach.id)}" data-mx-player="${row.player_id}"
                        value="${escapeHtml(shown)}" placeholder="–" aria-label="${escapeHtml(row.name)} ${escapeHtml(coach.id)}" />
                    </td>`;
                  })
                  .join("")}
                <td class="gi-mx__avg">${formatPts(row.mean)}</td>
              </tr>
            `;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function matrixFindGoal(goalId) {
  return (state.matrix?.goals || []).find((goal) => goal.id === goalId) || null;
}

function originalColumn(goal, coachId) {
  const players = goal.players || [];
  if (!players.length) return null;
  if (players.every((row) => row.by_coach?.[coachId] == null)) return null;
  const out = {};
  for (const row of players) out[row.player_id] = Number(row.by_coach?.[coachId] || 0);
  return out;
}

function ensureMatrixDraft(goal, coachId) {
  state.matrixDraft[goal.id] ||= {};
  if (state.matrixDraft[goal.id][coachId]) return state.matrixDraft[goal.id][coachId];
  const orig = originalColumn(goal, coachId);
  const draft = {};
  for (const row of goal.players || []) {
    draft[row.player_id] = orig ? Number(orig[row.player_id] || 0) : 0;
  }
  state.matrixDraft[goal.id][coachId] = draft;
  return draft;
}

function matrixCellValue(goal, playerId, coachId) {
  const draft = state.matrixDraft[goal.id]?.[coachId];
  if (draft) return draft[playerId] ?? 0;
  const row = (goal.players || []).find((item) => String(item.player_id) === String(playerId));
  return row?.by_coach?.[coachId];
}

function refreshMatrixColumn(goalId, coachId) {
  const goal = matrixFindGoal(goalId);
  if (!goal) return;
  const draft = state.matrixDraft[goalId]?.[coachId];
  const remain = document.querySelector(`[data-mx-remain="${CSS.escape(goalId)}:${CSS.escape(coachId)}"]`);
  const btn = document.querySelector(`[data-mx-save="${CSS.escape(goalId)}"][data-mx-coach="${CSS.escape(coachId)}"]`);
  if (!draft) {
    if (remain) remain.textContent = "";
    if (btn) btn.hidden = true;
    return;
  }
  const sum = Object.values(draft).reduce((total, n) => total + Number(n || 0), 0);
  const left = POINTS - sum;
  if (remain) {
    remain.textContent = left === 0 ? "10/10" : left > 0 ? `${left} left` : `${-left} over`;
    remain.classList.toggle("gi-mx__remain--ok", left === 0);
    remain.classList.toggle("gi-mx__remain--bad", left !== 0);
  }
  const orig = originalColumn(goal, coachId);
  const dirty = orig
    ? Object.keys({ ...orig, ...draft }).some((id) => Number(draft[id] || 0) !== Number(orig[id] || 0))
    : sum > 0;
  if (btn) {
    btn.hidden = !(dirty && left === 0);
    btn.disabled = !(dirty && left === 0);
  }
}

function paintMatrixDrafts() {
  for (const [goalId, coaches] of Object.entries(state.matrixDraft)) {
    for (const coachId of Object.keys(coaches || {})) refreshMatrixColumn(goalId, coachId);
  }
}

function onMatrixCellInput(input) {
  const goalId = input.dataset.mxGoal;
  const coachId = input.dataset.mxCoach;
  const playerId = Number(input.dataset.mxPlayer);
  const goal = matrixFindGoal(goalId);
  if (!goal || !coachId || !playerId) return;
  const draft = ensureMatrixDraft(goal, coachId);
  let n = parseInt(input.value, 10);
  if (Number.isNaN(n) || input.value === "") n = 0;
  n = Math.max(0, Math.min(POINTS, n));
  draft[playerId] = n;
  if (input.value !== "" && Number(input.value) !== n) input.value = String(n);
  refreshMatrixColumn(goalId, coachId);
}

async function saveMatrixColumn(goalId, coachId) {
  const goal = matrixFindGoal(goalId);
  if (!goal) return;
  const draft = state.matrixDraft[goalId]?.[coachId];
  if (!draft) return;
  const allocations = Object.entries(draft)
    .filter(([, points]) => Number(points) > 0)
    .map(([player_id, points]) => ({ player_id: Number(player_id), points: Number(points) }));
  const btn = document.querySelector(`[data-mx-save="${CSS.escape(goalId)}"][data-mx-coach="${CSS.escape(coachId)}"]`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Saving…";
  }
  try {
    await fetchJson(`/api/goal-involvement/goals/${encodeURIComponent(goalId)}/score`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allocations, coach_id: coachId }),
    });
    if (state.matrixDraft[goalId]) delete state.matrixDraft[goalId][coachId];
    setStatus(`Saved ${coachId}.`, "ok");
    await loadBoot(state.season);
  } catch (err) {
    setStatus(err.message, "err");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Save";
    }
  }
}

async function loadMatrix() {
  try {
    const payload = await fetchJson(
      `/api/goal-involvement/matrix?season=${encodeURIComponent(state.season || "")}`
    );
    state.matrix = payload;
    renderMatrix(payload);
  } catch (err) {
    setStatus(err.message, "err");
    els.matrixView.innerHTML = `<section class="gi-card"><p>${escapeHtml(err.message)}</p></section>`;
  }
}

function renderHome() {
  const view = state.boot?.overview || {};
  const pending = pendingGoals();
  const done = goals().filter((goal) => goal.i_have_scored).slice(0, 8);
  const progress = view.coach_progress || [];
  els.pageSub.textContent = state.coach
    ? pending.length
      ? `${coachName(state.coach)} — ${pending.length} to score`
      : `${coachName(state.coach)} — up to date`
    : "Pick your name to score";
  els.homeView.innerHTML = `
    <section class="gi-mx-toolbar">
      ${playTypeButtons()}
    </section>
    ${renderBoardTable(view.table)}
    ${state.coach
      ? ""
      : `<section class="gi-card gi-card--prompt">
          <h3>Pick your name to score</h3>
          <p class="gi-muted">Use the dropdown at the top. Everyone shares this login, so your points are saved against the coach you pick.</p>
        </section>`}
    ${pending.length
      ? `<h2 class="gi-kicker">Still to score</h2>${pending.map((goal) => goalCard(goal)).join("")}`
      : ""}
    ${done.length ? `<h2 class="gi-kicker">Recently scored by you</h2>${done.map((goal) => goalCard(goal, { actionLabel: "Open" })).join("")}` : ""}
    ${progress.length
      ? `<section class="gi-card">
          <h3>Who has filed</h3>
          ${progress
            .map(
              (row) => `
            <div class="gi-progress">
              <span>${escapeHtml(row.display_name)}</span>
              <div class="gi-bar"><span style="width:${row.total ? (row.scored / row.total) * 100 : 0}%"></span></div>
              <strong>${row.scored}/${row.total}</strong>
            </div>`
            )
            .join("")}
        </section>`
      : ""}
  `;
}

function addPlayerPicker(goal) {
  const listed = new Set((goal.players_on_pitch || []).map((player) => Number(player.id)));
  const options = (state.boot?.squad || []).filter((player) => !listed.has(Number(player.id)));
  if (!options.length) return "";
  return `
    <label class="gi-muted gi-addplayer">Add a player
      <select class="gi-select gi-select--wide" id="addPlayer">
        <option value="">Someone else involved…</option>
        ${options
          .map((player) => `<option value="${player.id}">${escapeHtml(player.name)}${player.shirt ? ` (#${player.shirt})` : ""}</option>`)
          .join("")}
      </select>
    </label>
  `;
}

const DIRECT_VIDEO = /\.(mp4|m4v|mov|webm)(\?|#|$)/i;

function clipPlayer(goal) {
  const clip = goal.clip || {};
  if (!clip.has_clip) return "";
  const video = (src) =>
    `<video class="gi-clip" controls playsinline preload="metadata" src="${escapeHtml(src)}"></video>`;
  if (clip.kind === "file") {
    return video(`/api/goal-involvement/goals/${encodeURIComponent(goal.id)}/clip`);
  }
  if (clip.kind === "embed") {
    return `
      <div class="gi-clip gi-clip--frame">
        <iframe src="${escapeHtml(clip.url)}" title="Goal clip" allowfullscreen
                referrerpolicy="no-referrer" loading="lazy"></iframe>
      </div>
    `;
  }
  if (DIRECT_VIDEO.test(clip.url || "")) return video(clip.url);
  return `<a class="gi-btn gi-btn--ghost" href="${escapeHtml(clip.url)}" target="_blank" rel="noopener">Watch the clip</a>`;
}

// Admin only: whatever is attached here is what the coaches see on their link.
function clipAdmin(goal) {
  if (!state.boot?.me?.is_admin) return "";
  const clip = goal.clip || {};
  return `
    <details class="gi-clipadmin" ${clip.has_clip ? "" : "open"}>
      <summary>${clip.has_clip ? "Replace clip" : "Attach the goal clip"}</summary>
      <p class="gi-muted">Coaches watch this above the points on their link. MP4, MOV or WebM, up to 150MB — or paste a YouTube / Vimeo / Veo link.</p>
      <input type="file" id="clipFile" accept="video/mp4,video/quicktime,video/webm,.mp4,.m4v,.mov,.webm" />
      <div class="gi-clipadmin__row">
        <input type="url" id="clipUrl" placeholder="https://… (YouTube, Vimeo, or a direct .mp4)" value="" />
        <button type="button" class="gi-btn gi-btn--ghost" id="clipSaveUrl">Use link</button>
      </div>
      ${clip.has_clip ? `<button type="button" class="gi-btn gi-btn--ghost" id="clipRemove">Remove clip</button>` : ""}
      <p class="gi-clipadmin__state" id="clipState" hidden></p>
    </details>
  `;
}

function bindClipAdmin(goal) {
  const fileInput = document.getElementById("clipFile");
  const state_ = document.getElementById("clipState");
  const say = (message, bad = false) => {
    if (!state_) return;
    state_.textContent = message;
    state_.hidden = false;
    state_.classList.toggle("is-bad", bad);
  };
  const send = async (body) => {
    say("Uploading…");
    try {
      const response = await fetch(
        `/api/goal-involvement/goals/${encodeURIComponent(goal.id)}/clip`,
        { method: "POST", body }
      );
      if (!response.ok) {
        let detail = `Upload failed (${response.status})`;
        try {
          const payload = await response.json();
          if (payload.detail) detail = payload.detail;
        } catch (_) { /* keep the status */ }
        throw new Error(detail);
      }
      state.sheetGoal = await response.json();
      showDetail(state.sheetGoal);
      loadBoot(state.season).catch(() => {});
      if (state.view === "admin") loadAdmin();
    } catch (error) {
      say(error.message, true);
    }
  };
  fileInput?.addEventListener("change", () => {
    const picked = fileInput.files?.[0];
    if (!picked) return;
    const form = new FormData();
    form.append("file", picked);
    send(form);
  });
  document.getElementById("clipSaveUrl")?.addEventListener("click", () => {
    const value = document.getElementById("clipUrl")?.value.trim();
    if (!value) {
      say("Paste a link first.", true);
      return;
    }
    const form = new FormData();
    form.append("url", value);
    send(form);
  });
  document.getElementById("clipRemove")?.addEventListener("click", async () => {
    try {
      state.sheetGoal = await fetchJson(
        `/api/goal-involvement/goals/${encodeURIComponent(goal.id)}/clip`,
        { method: "DELETE" }
      );
      showDetail(state.sheetGoal);
      loadBoot(state.season).catch(() => {});
      if (state.view === "admin") loadAdmin();
    } catch (error) {
      say(error.message, true);
    }
  });
}

function renderSheet(goal) {
  const players = goal.players_on_pitch || [];
  const left = remaining();
  const label = goal.points_label || "involvement";
  els.sheetPanel.innerHTML = `
    <p class="gi-kicker">${escapeHtml(goal.date || "")} · ${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")} · ${escapeHtml(goal.competition || "")}</p>
    <h2 style="margin:.1rem 0 .4rem">${escapeHtml(goalTitle(goal))}</h2>
    ${clipPlayer(goal)}
    ${clipAdmin(goal)}
    <p class="gi-muted">${escapeHtml(coachName(state.coach) || "You")} — split 10 ${escapeHtml(label)} points. Tap + / −. Must total 10.</p>
    <div id="playerList">
      ${players
        .map(
          (player) => `
        <div class="gi-player ${state.allocations[player.id] ? "gi-player--has" : ""}">
          <img class="gi-avatar" alt="" src="${escapeHtml(photoUrl(player))}" />
          <div>
            <strong>${escapeHtml(player.name)}</strong>
            <div class="gi-muted">${player.shirt ? `#${player.shirt} · ` : ""}${escapeHtml(player.position || "")}${player.started ? "" : player.added_by ? " · added" : " · sub"}</div>
          </div>
          <div class="gi-stepper">
            <button type="button" data-act="minus" data-id="${player.id}">−</button>
            <span class="gi-pts" id="pts-${player.id}">${state.allocations[player.id] || 0}</span>
            <button type="button" data-act="plus" data-id="${player.id}">+</button>
          </div>
        </div>
      `
        )
        .join("")}
    </div>
    ${addPlayerPicker(goal)}
    <div class="gi-sticky">
      <div class="gi-remain ${left === 0 ? "gi-remain--ok" : "gi-remain--bad"}">${left} left</div>
      <div style="display:flex;gap:.5rem">
        <button type="button" class="gi-btn gi-btn--ghost" id="sheetClose">Close</button>
        <button type="button" class="gi-btn gi-btn--primary" id="sheetSubmit" ${left === 0 ? "" : "disabled"}>Submit 10</button>
      </div>
    </div>
  `;
  els.sheet.hidden = false;
  bindClipAdmin(goal);
}

function syncSheetTotals() {
  const left = remaining();
  const remain = els.sheetPanel.querySelector(".gi-remain");
  if (remain) {
    remain.textContent = `${left} left`;
    remain.className = `gi-remain ${left === 0 ? "gi-remain--ok" : "gi-remain--bad"}`;
  }
  const submit = document.getElementById("sheetSubmit");
  if (submit) submit.disabled = left !== 0;
}

// Patch in place rather than re-rendering — a re-render would throw a phone
// back to the top of the list on every tap.
function changePoints(playerId, delta) {
  const current = Number(state.allocations[playerId] || 0);
  const next = current + delta;
  if (next < 0) return;
  if (delta > 0 && remaining() <= 0) return;
  state.allocations[playerId] = next;
  if (!state.allocations[playerId]) delete state.allocations[playerId];
  const cell = document.getElementById(`pts-${playerId}`);
  if (cell) {
    cell.textContent = String(state.allocations[playerId] || 0);
    cell.closest(".gi-player")?.classList.toggle("gi-player--has", Boolean(state.allocations[playerId]));
  }
  syncSheetTotals();
}

async function openGoal(goalId, { forClip = false } = {}) {
  try {
    const goal = await fetchJson(`/api/goal-involvement/goals/${encodeURIComponent(goalId)}?${coachParam()}`);
    state.sheetGoal = goal;
    if (forClip && state.boot?.me?.is_admin) {
      state.sheetMode = "detail";
      showDetail(goal);
      return;
    }
    if (goal.revealed || (goal.i_have_scored && goal.status === "open") || !state.coach) {
      state.sheetMode = "detail";
      showDetail(goal);
      return;
    }
    state.sheetMode = "score";
    state.allocations = {};
    for (const row of goal.my_allocations || []) {
      if (row.points) state.allocations[row.player_id] = row.points;
    }
    renderSheet(goal);
  } catch (err) {
    setStatus(err.message, "err");
  }
}

function coachSpread(row, names) {
  const by = row.by_coach || {};
  return Object.entries(by)
    .map(([id, pts]) => `<span class="gi-chip">${escapeHtml(String(names[id] || id).split(" ")[0])} ${Number(pts)}</span>`)
    .join("");
}

function showDetail(goal) {
  const averages = (goal.averages || []).filter((row) => Number(row.mean) > 0 || Number(row.stdev) > 0);
  const agreement = goal.agreement;
  const names = goal.coach_names || {};
  const submitted = new Set(goal.submitted_coaches || []);
  const roster = (state.boot?.coaches || []).filter((coach) => coach.active);
  els.sheetPanel.innerHTML = `
    <p class="gi-kicker">${escapeHtml(goal.date || "")} · ${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")} · ${goal.submitted_count}/${goal.expected} coaches</p>
    <h2 style="margin:.1rem 0 .4rem">${escapeHtml(goalTitle(goal))}</h2>
    ${clipPlayer(goal)}
    ${clipAdmin(goal)}
    ${roster.length
      ? `<div class="gi-spread">${roster
          .map((coach) => `<span class="gi-chip ${submitted.has(coach.id) ? "gi-chip--in" : ""}">${escapeHtml(coach.id)} ${submitted.has(coach.id) ? "✓" : "–"}</span>`)
          .join("")}</div>`
      : ""}
    ${agreement
      ? `<p class="${agreement.flagged ? "gi-flag" : ""}">${escapeHtml(agreement.label)}${agreement.flagged ? " — flagged for review, nothing auto-corrected." : ""} · avg sd ${agreement.average_stdev}</p>`
      : `<p class="gi-muted">${escapeHtml(goal.waiting_label || "Waiting on other coaches.")}</p>`}
    ${averages.length
      ? averages
          .map(
            (row) => `
      <div class="gi-player gi-player--stack">
        <img class="gi-avatar" alt="" src="${escapeHtml(photoUrl(row))}" />
        <div>
          <strong>${escapeHtml(row.name)}</strong>
          <div class="gi-muted">avg ${Number(row.mean).toFixed(2)} · range ${Number(row.min).toFixed(0)}–${Number(row.max).toFixed(0)} · sd ${Number(row.stdev).toFixed(2)}</div>
          <div class="gi-bar"><span class="${goal.team_for_or_against === "conceded" ? "conceded" : ""}" style="width:${Math.min(100, Number(row.mean) * 10)}%"></span></div>
          <div class="gi-spread">${coachSpread(row, names)}</div>
        </div>
        <strong>${Number(row.mean).toFixed(1)}</strong>
      </div>
    `
          )
          .join("")
      : `<p class="gi-muted">No points allocated yet.</p>`}
    <div class="gi-sticky">
      <span class="gi-muted">${goal.i_have_scored ? `${escapeHtml(coachName(state.coach))} has scored this one.` : ""}</span>
      <div style="display:flex;gap:.5rem">
        ${goal.status === "open" && state.coach
          ? `<button type="button" class="gi-btn gi-btn--ghost" id="sheetEdit">${goal.i_have_scored ? "Change mine" : "Score it"}</button>`
          : ""}
        <button type="button" class="gi-btn gi-btn--primary" id="sheetClose">Done</button>
      </div>
    </div>
  `;
  els.sheet.hidden = false;
  bindClipAdmin(goal);
}

function editFromDetail() {
  const goal = state.sheetGoal;
  if (!goal) return;
  state.sheetMode = "score";
  state.allocations = {};
  for (const row of goal.my_allocations || []) {
    if (row.points) state.allocations[row.player_id] = row.points;
  }
  renderSheet(goal);
}

async function addPlayer(playerId) {
  if (!state.sheetGoal || !playerId) return;
  try {
    const goal = await fetchJson(
      `/api/goal-involvement/goals/${encodeURIComponent(state.sheetGoal.id)}/players?${coachParam()}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_id: Number(playerId) }),
      }
    );
    state.sheetGoal = goal;
    renderSheet(goal);
  } catch (err) {
    setStatus(err.message, "err");
  }
}

async function submitScore() {
  if (!state.sheetGoal) return;
  if (remaining() !== 0) return;
  const allocations = Object.entries(state.allocations)
    .filter(([, points]) => Number(points) > 0)
    .map(([player_id, points]) => ({ player_id: Number(player_id), points: Number(points) }));
  try {
    await fetchJson(`/api/goal-involvement/goals/${encodeURIComponent(state.sheetGoal.id)}/score`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allocations, coach_id: state.coach }),
    });
    els.sheet.hidden = true;
    setStatus("Saved. Next goal when you’re ready.", "ok");
    await loadBoot(state.season);
  } catch (err) {
    setStatus(err.message, "err");
  }
}

function lastSyncLabel(iso) {
  if (!iso) return "not yet";
  try {
    const when = new Date(iso);
    if (Number.isNaN(when.getTime())) return iso;
    return when.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
  } catch (_) {
    return iso;
  }
}

function coachRowHtml(coach = {}) {
  return `
    <div class="gi-coachrow">
      <input class="gi-input" data-coach-id value="${escapeHtml(coach.id || "")}" placeholder="Initials" />
      <input class="gi-input" data-coach-name value="${escapeHtml(coach.display_name || "")}" placeholder="Full name" />
      <input class="gi-input" data-coach-phone value="${escapeHtml(coach.phone || "")}" placeholder="Mobile (07… or +44…)" inputmode="tel" />
      <input class="gi-input" data-coach-email value="${escapeHtml(coach.email || "")}" placeholder="Email" inputmode="email" />
      <button type="button" class="gi-btn gi-btn--ghost gi-coachrow__del" data-remove-coach>Remove</button>
    </div>
  `;
}

function renderAdmin(payload) {
  const coaches = payload.coaches || [];
  const goalRows = payload.goals || [];
  const settings = payload.settings || {};
  const active = coaches.filter((coach) => coach.active);
  const expected = settings.expected_coach_count || 5;
  els.adminView.innerHTML = `
    <section class="gi-card">
      <h3>Submission board</h3>
      <p class="gi-muted">Add clip is the video coaches watch while they split the 10. Close a goal if someone is away and you still want averages out.</p>
      <div style="overflow:auto">
        <table class="gi-table">
          <thead>
            <tr>
              <th>Goal</th>
              ${active.map((coach) => `<th>${escapeHtml(coach.id)}</th>`).join("")}
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${goalRows
              .map(
                (goal) => `
              <tr>
                <td>${escapeHtml(goal.date || "")} ${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")}<br /><span class="gi-muted">${escapeHtml(goal.opponent)}</span></td>
                ${active.map((coach) => `<td>${goal.by_coach?.[coach.id] ? "✓" : "–"}</td>`).join("")}
                <td class="gi-actions">
                  <button type="button" class="gi-btn gi-btn--${goal.clip?.has_clip ? "ghost" : "primary"}" data-clip="${escapeHtml(goal.id)}">${goal.clip?.has_clip ? "Clip ✓" : "Add clip"}</button>
                  ${goal.status === "open"
                    ? `<button type="button" class="gi-btn gi-btn--ghost" data-close="${escapeHtml(goal.id)}">Close</button>`
                    : `<button type="button" class="gi-btn gi-btn--ghost" data-reopen="${escapeHtml(goal.id)}">Reopen</button>`}
                  ${goal.submitted_count ? `<button type="button" class="gi-btn gi-btn--danger" data-reset="${escapeHtml(goal.id)}">Reset</button>` : ""}
                </td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </section>
    <section class="gi-card gi-card--send" id="sendCard">
      <h3>Send out unranked goals</h3>
      <p class="gi-muted">Checking what's outstanding…</p>
    </section>
    <section class="gi-card">
      <h3>Goals from Impect</h3>
      <p class="gi-muted">Completed Vale league matches pull in on their own. Last pulled ${escapeHtml(lastSyncLabel(settings.last_sync_at))}.</p>
      <button type="button" class="gi-btn gi-btn--ghost" id="syncBtn">Sync now</button>
    </section>
    <section class="gi-card">
      <h3>Coaches</h3>
      <p class="gi-muted">Initials are the ID coaches pick at the top of the page. Expected ${expected}, quorum ${settings.quorum || 4} — quorum is a reminder, close a goal manually if someone is away.</p>
      <div id="coachList">
        ${coaches.filter((coach) => coach.active).map((coach) => coachRowHtml(coach)).join("")}
      </div>
      <div class="gi-coach-actions">
        <button type="button" class="gi-btn gi-btn--ghost" id="addCoachBtn">Add coach</button>
      </div>
      <p class="gi-muted">Mobile numbers are only used to open WhatsApp with the message ready — nothing is sent automatically. Remove someone, then Save, and they drop off the picker and the matrix.</p>
      <div class="gi-grid-2" style="margin:.6rem 0">
        <label class="gi-muted">Expected<input class="gi-input" id="expectedCount" type="number" min="1" max="20" value="${settings.expected_coach_count || 5}" /></label>
        <label class="gi-muted">Quorum<input class="gi-input" id="quorumCount" type="number" min="1" max="20" value="${settings.quorum || 4}" /></label>
      </div>
      <button type="button" class="gi-btn gi-btn--primary" id="saveCoachesBtn">Save coaches</button>
    </section>
    <details class="gi-card" id="linksCard">
      <summary><strong>Send one specific game instead</strong></summary>
      <p class="gi-muted">Loading matches…</p>
    </details>
  `;
}

async function loadAdmin() {
  if (!state.boot?.me?.is_admin) {
    els.adminView.innerHTML = `<section class="gi-card"><p>Admin only.</p></section>`;
    return;
  }
  try {
    const payload = await fetchJson(`/api/goal-involvement/admin?season=${encodeURIComponent(state.season || "")}`);
    renderAdmin(payload);
    await Promise.all([loadSendOut(), loadLinks()]);
  } catch (err) {
    setStatus(err.message, "err");
  }
}

function sendRow(row) {
  return `
    <div class="gi-linkrow">
      <div>
        <strong>${escapeHtml(row.display_name)}</strong>
        <div class="gi-muted">${row.outstanding} goal${row.outstanding === 1 ? "" : "s"} outstanding${row.games?.length > 1 ? ` · ${escapeHtml(row.games.join(", "))}` : ""}</div>
      </div>
      <div class="gi-actions">
        ${row.whatsapp_ready
          ? `<a class="gi-btn gi-btn--primary" href="${escapeHtml(row.whatsapp_url)}" target="_blank" rel="noopener" data-sent="${escapeHtml(row.id)}">WhatsApp</a>`
          : `<span class="gi-muted">No mobile saved</span>`}
        <button type="button" class="gi-btn gi-btn--ghost" data-copy="${escapeHtml(row.message)}">Copy message</button>
      </div>
    </div>
  `;
}

function renderSendOut(payload) {
  const card = document.getElementById("sendCard");
  if (!card) return;
  const waiting = payload.waiting || [];
  const done = (payload.coaches || []).filter((row) => !row.outstanding);
  const older = payload.older_unranked
    ? `<p class="gi-muted">${payload.older_unranked} unranked goal${payload.older_unranked === 1 ? "" : "s"} from earlier seasons are left alone. Use "Send one specific game" below for those.</p>`
    : "";

  if (payload.nothing_to_send) {
    card.innerHTML = `
      <h3>Send out unranked goals</h3>
      <p class="gi-ok-line">Everything's scored — nothing to send.</p>
      ${older}
      <button type="button" class="gi-btn gi-btn--ghost" id="sendRefresh">Check again</button>
    `;
    document.getElementById("sendRefresh").addEventListener("click", () =>
      loadSendOut().catch((err) => setStatus(err.message, "err"))
    );
    return;
  }

  const fixtures = (payload.fixtures || [])
    .map((f) => `${escapeHtml(f.venue)} v ${escapeHtml(f.opponent || "")}`)
    .join(" · ");

  card.innerHTML = `
    <h3>Send out unranked goals</h3>
    <p class="gi-muted">${waiting.length} coach${waiting.length === 1 ? "" : "es"} still to score${fixtures ? ` · ${fixtures}` : ""}. Tap WhatsApp, press send, next one. Each link covers everything that coach owes.</p>
    ${payload.secure ? "" : `<p class="gi-warn">Still on plain HTTP — fine for testing, but wait for HTTPS before these go to coaches.</p>`}
    ${older}
    <div class="gi-linklist">${waiting.map(sendRow).join("")}</div>
    ${done.length ? `<p class="gi-muted">Already done: ${done.map((row) => escapeHtml(row.display_name)).join(", ")}</p>` : ""}
    <button type="button" class="gi-btn gi-btn--ghost" id="sendRefresh">Refresh</button>
  `;

  document.getElementById("sendRefresh").addEventListener("click", () =>
    loadSendOut().catch((err) => setStatus(err.message, "err"))
  );
  // Tick off who you have already messaged, so you do not lose your place.
  card.querySelectorAll("[data-sent]").forEach((link) => {
    link.addEventListener("click", () => link.closest(".gi-linkrow")?.classList.add("gi-linkrow--sent"));
  });
  bindCopyButtons(card);
}

async function loadSendOut() {
  const params = new URLSearchParams();
  if (state.season) params.set("season", state.season);
  renderSendOut(await fetchJson(`/api/goal-involvement/send-out?${params.toString()}`));
}

// navigator.clipboard does not exist on plain HTTP, which is exactly where this
// hub lives, so fall back to the old textarea trick before giving up.
async function copyText(text) {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) { /* fall through */ }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.top = "-1000px";
  document.body.appendChild(area);
  area.select();
  area.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {
    ok = false;
  }
  area.remove();
  return ok;
}

// Last resort: show it so it can be selected by hand rather than losing it.
function showCopyFallback(text) {
  const box = document.createElement("div");
  box.className = "gi-copybox";
  box.innerHTML = `
    <p class="gi-muted">Copy couldn't reach the clipboard. Select this and copy it manually:</p>
    <textarea readonly rows="4"></textarea>
  `;
  box.querySelector("textarea").value = text;
  document.getElementById("sendCard")?.appendChild(box);
  const area = box.querySelector("textarea");
  area.focus();
  area.select();
}

function bindCopyButtons(scope) {
  scope.querySelectorAll("[data-copy]").forEach((button) => {
    const label = button.textContent;
    button.addEventListener("click", async () => {
      const text = button.dataset.copy;
      if (await copyText(text)) {
        button.textContent = "Copied";
        setTimeout(() => { button.textContent = label; }, 1500);
      } else {
        showCopyFallback(text);
      }
    });
  });
}

function renderLinks(payload) {
  const card = document.getElementById("linksCard");
  if (!card) return;
  const matches = payload.matches || [];
  const rows = payload.coaches || [];
  const heading = `<summary><strong>Send one specific game instead</strong></summary>`;
  if (!matches.length) {
    card.innerHTML = `
      ${heading}
      <p class="gi-muted">No goals logged yet — sync a season first.</p>
    `;
    return;
  }
  card.innerHTML = `
    ${heading}
    <p class="gi-muted">For backfilling an older game, or re-sending one match on its own.</p>
    <label class="gi-muted" style="display:block;margin:.6rem 0">Match
      <select class="gi-select gi-select--wide" id="linkMatch">
        ${matches
          .map(
            (match) => `<option value="${match.match_id}" ${match.match_id === payload.match_id ? "selected" : ""}>
              ${escapeHtml(match.date || "")} · ${escapeHtml(match.venue)} v ${escapeHtml(match.opponent || "")} · ${match.goals} goal${match.goals === 1 ? "" : "s"}${match.open_goals ? "" : " · all closed"}
            </option>`
          )
          .join("")}
      </select>
    </label>
    <div class="gi-linklist">
      ${rows
        .map(
          (row) => `
        <div class="gi-linkrow">
          <div>
            <strong>${escapeHtml(row.display_name)}</strong>
            <div class="gi-muted">${row.done}/${row.total} scored${row.outstanding ? "" : " · nothing outstanding"}</div>
          </div>
          <div class="gi-actions">
            ${row.whatsapp_ready
              ? `<a class="gi-btn gi-btn--primary" href="${escapeHtml(row.whatsapp_url)}" target="_blank" rel="noopener">WhatsApp</a>`
              : `<span class="gi-muted">Add a mobile above</span>`}
            <button type="button" class="gi-btn gi-btn--ghost" data-copy="${escapeHtml(row.url)}">Copy link</button>
          </div>
        </div>
      `
        )
        .join("")}
    </div>
  `;
  document.getElementById("linkMatch")?.addEventListener("change", (event) => {
    card.open = true;
    loadLinks(event.target.value).catch((err) => setStatus(err.message, "err"));
  });
  bindCopyButtons(card);
}

async function loadLinks(matchId) {
  const params = new URLSearchParams();
  if (state.season) params.set("season", state.season);
  if (matchId) params.set("match_id", matchId);
  renderLinks(await fetchJson(`/api/goal-involvement/links?${params.toString()}`));
}

async function saveCoaches() {
  const ids = [...document.querySelectorAll("[data-coach-id]")];
  const names = [...document.querySelectorAll("[data-coach-name]")];
  const phones = [...document.querySelectorAll("[data-coach-phone]")];
  const emails = [...document.querySelectorAll("[data-coach-email]")];
  const coaches = [];
  ids.forEach((input, index) => {
    const id = input.value.trim();
    if (!id) return;
    coaches.push({
      id,
      display_name: names[index]?.value.trim() || id,
      active: true,
      sort_order: index,
      phone: phones[index]?.value.trim() || "",
      email: emails[index]?.value.trim() || "",
    });
  });
  try {
    await fetchJson("/api/goal-involvement/coaches", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        coaches,
        expected_coach_count: Number(document.getElementById("expectedCount")?.value || 5),
        quorum: Number(document.getElementById("quorumCount")?.value || 4),
        disagreement_threshold: 1.5,
      }),
    });
    setStatus("Coach list saved.", "ok");
    await loadBoot(state.season);
    await loadAdmin();
  } catch (err) {
    setStatus(err.message, "err");
  }
}

async function loadBoot(season) {
  const params = new URLSearchParams();
  if (season) params.set("season", season);
  if (state.coach) params.set("coach_id", state.coach);
  if (state.playType === "open_play" || state.playType === "set_play") {
    params.set("play_type", state.playType);
  }
  state.boot = await fetchJson(`/api/goal-involvement/bootstrap?${params.toString()}`);
  state.season = state.boot.season || season || "";
  if (state.boot.me?.coach_id) state.coach = state.boot.me.coach_id;
  const isAdmin = Boolean(state.boot.me?.is_admin);
  els.adminTab.hidden = !isAdmin;
  renderSelects();
  if (state.view === "admin") loadAdmin();
  else if (state.view === "matrix") loadMatrix();
  else renderHome();
  autoSync();
}

async function autoSync() {
  if (!state.boot?.me?.is_admin || state.autoSyncStarted) return;
  state.autoSyncStarted = true;
  try {
    const result = await fetchJson(
      `/api/goal-involvement/sync?season=${encodeURIComponent(state.season || "")}`,
      { method: "POST" }
    );
    if (result.skipped) return;
    const created = Number(result.goals_created || 0);
    if (created > 0) {
      setStatus(`Pulled ${created} new goal${created === 1 ? "" : "s"} from Impect.`, "ok");
    }
    await loadBoot(state.season);
  } catch (_) {
    // A failed background pull must not block scoring; Sync now is still there.
  }
}

function bind() {
  document.querySelectorAll(".gi-tab").forEach((tab) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
  });
  els.refreshBtn.addEventListener("click", () =>
    loadBoot(state.season).catch((err) => setStatus(err.message, "err"))
  );
  els.seasonSelect.addEventListener("change", () => {
    state.autoSyncStarted = false;
    loadBoot(els.seasonSelect.value).catch((err) => setStatus(err.message, "err"));
  });
  els.coachSelect.addEventListener("change", () => {
    state.coach = els.coachSelect.value;
    localStorage.setItem(COACH_KEY, state.coach);
    loadBoot(state.season).catch((err) => setStatus(err.message, "err"));
  });

  document.body.addEventListener("change", (event) => {
    if (event.target.id === "addPlayer") {
      addPlayer(event.target.value);
      return;
    }
    if (event.target.id === "matrixOnly") {
      state.matrixOnly = event.target.checked;
      if (state.matrix) renderMatrix(state.matrix);
    }
  });

  document.body.addEventListener("input", (event) => {
    if (event.target.matches("[data-mx-cell]")) onMatrixCellInput(event.target);
  });

  document.body.addEventListener("click", async (event) => {
    const sortBtn = event.target.closest("[data-board-sort]");
    if (sortBtn) {
      const field = sortBtn.dataset.boardSort;
      if (state.boardSort.field === field) {
        state.boardSort.dir = state.boardSort.dir === "desc" ? "asc" : "desc";
      } else {
        state.boardSort = { field, dir: "desc" };
      }
      renderHome();
      return;
    }
    const playBtn = event.target.closest("[data-play-type]");
    if (playBtn) {
      state.playType = playBtn.dataset.playType || "all";
      loadBoot(state.season).catch((err) => setStatus(err.message, "err"));
      return;
    }
    const sideBtn = event.target.closest("[data-matrix-side]");
    if (sideBtn) {
      state.matrixSide = sideBtn.dataset.matrixSide || "all";
      if (state.matrix) renderMatrix(state.matrix);
      return;
    }
    const saveMx = event.target.closest("[data-mx-save]");
    if (saveMx) {
      saveMatrixColumn(saveMx.dataset.mxSave, saveMx.dataset.mxCoach);
      return;
    }
    const card = event.target.closest("[data-goal-id]");
    if (card && !event.target.closest("button") && !event.target.closest("input")) {
      openGoal(card.dataset.goalId);
      return;
    }
    if (event.target.id === "sheetClose") {
      els.sheet.hidden = true;
      loadBoot(state.season).catch((err) => setStatus(err.message, "err"));
      return;
    }
    if (event.target.id === "sheetEdit") {
      editFromDetail();
      return;
    }
    if (event.target.id === "sheetSubmit") {
      submitScore();
      return;
    }
    const step = event.target.closest("[data-act]");
    if (step) {
      changePoints(Number(step.dataset.id), step.dataset.act === "plus" ? 1 : -1);
      return;
    }
    if (event.target.id === "addCoachBtn") {
      const list = document.getElementById("coachList");
      if (!list) return;
      list.insertAdjacentHTML("beforeend", coachRowHtml());
      list.querySelector(".gi-coachrow:last-child [data-coach-id]")?.focus();
      return;
    }
    const removeBtn = event.target.closest("[data-remove-coach]");
    if (removeBtn) {
      const row = removeBtn.closest(".gi-coachrow");
      const name = row?.querySelector("[data-coach-name]")?.value.trim()
        || row?.querySelector("[data-coach-id]")?.value.trim()
        || "this coach";
      if (!confirm(`Remove ${name} from the scoring list?`)) return;
      row?.remove();
      saveCoaches();
      return;
    }
    if (event.target.id === "saveCoachesBtn") {
      saveCoaches();
      return;
    }
    if (event.target.id === "syncBtn") {
      event.target.disabled = true;
      event.target.textContent = "Syncing…";
      try {
        const result = await fetchJson(
          `/api/goal-involvement/sync?season=${encodeURIComponent(state.season || "")}&force=true`,
          { method: "POST" }
        );
        setStatus(`Synced ${result.matches || 0} matches · ${result.goals_created || 0} new goals.`, "ok");
        await loadBoot(state.season);
        await loadAdmin();
      } catch (err) {
        setStatus(err.message, "err");
      } finally {
        event.target.disabled = false;
        event.target.textContent = "Sync now";
      }
      return;
    }
    const clipId = event.target.dataset.clip;
    if (clipId) {
      openGoal(clipId, { forClip: true });
      return;
    }
    const closeId = event.target.dataset.close;
    if (closeId) {
      try {
        await fetchJson(`/api/goal-involvement/goals/${encodeURIComponent(closeId)}/close`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: "Closed from admin board" }),
        });
        await loadBoot(state.season);
        await loadAdmin();
      } catch (err) {
        setStatus(err.message, "err");
      }
      return;
    }
    const reopenId = event.target.dataset.reopen;
    if (reopenId) {
      try {
        await fetchJson(`/api/goal-involvement/goals/${encodeURIComponent(reopenId)}/reopen`, {
          method: "POST",
        });
        await loadBoot(state.season);
        await loadAdmin();
      } catch (err) {
        setStatus(err.message, "err");
      }
      return;
    }
    const resetId = event.target.dataset.reset;
    if (resetId) {
      if (!confirm("Wipe every coach score for this goal? They will have to score it again.")) return;
      try {
        await fetchJson(`/api/goal-involvement/goals/${encodeURIComponent(resetId)}/scores`, {
          method: "DELETE",
        });
        setStatus("Scores cleared for that goal.", "ok");
        await loadBoot(state.season);
        await loadAdmin();
      } catch (err) {
        setStatus(err.message, "err");
      }
    }
  });
}

bind();
loadBoot().catch((err) => setStatus(err.message, "err"));
