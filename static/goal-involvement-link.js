// Coach scoring link — one coach, one match, no login. The token in the URL is
// the identity, so there is no coach picker and nothing else from the hub here.
const TOKEN = window.location.pathname.split("/").filter(Boolean).pop() || "";
const POINTS = 10;

const state = {
  data: null,
  index: 0,
  allocations: {},
  busy: false,
};

const els = {
  coachName: document.getElementById("coachName"),
  matchLine: document.getElementById("matchLine"),
  progress: document.getElementById("progress"),
  stage: document.getElementById("stage"),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

function photoUrl(player) {
  return player.photo_url || `/api/player-photo?name=${encodeURIComponent(player.name || "")}`;
}

function allocated() {
  return Object.values(state.allocations).reduce((sum, value) => sum + Number(value || 0), 0);
}

function remaining() {
  return POINTS - allocated();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch (_) { /* keep the status message */ }
    throw new Error(detail);
  }
  return response.json();
}

function goals() {
  return state.data?.goals || [];
}

function outstanding() {
  return goals().filter((goal) => !goal.i_have_scored && goal.status !== "closed");
}

function renderHeader() {
  const coach = state.data?.coach;
  const match = state.data?.match || {};
  els.coachName.textContent = coach ? coach.display_name : "Score the goals";
  if (state.data?.multi_match) {
    const games = new Set(goals().map((goal) => goal.opponent).filter(Boolean));
    els.matchLine.textContent = `${goals().length} goals to score across ${games.size} games`;
  } else {
    const bits = [match.opponent ? `${match.venue || ""} v ${match.opponent}` : "", match.date || "", match.competition || ""];
    els.matchLine.textContent = bits.filter(Boolean).join(" · ");
  }
  const total = goals().length;
  const done = total - outstanding().length;
  els.progress.hidden = total === 0;
  els.progress.innerHTML = `
    <div class="gil-progress__bar"><span style="width:${total ? (done / total) * 100 : 0}%"></span></div>
    <span class="gil-progress__label">${done} of ${total} done</span>
  `;
}

function renderDone() {
  els.stage.innerHTML = `
    <div class="gil-done">
      <div class="gil-tick" aria-hidden="true">✓</div>
      <h2>That's the lot — thanks.</h2>
      <p class="gi-muted">Your points are saved. Averages stay hidden until every coach is in, so nobody is nudged by anyone else's numbers.</p>
      <ul class="gil-recap">
        ${goals().map((goal) => `
          <li>
            <strong>${escapeHtml(goal.side_label)} ${escapeHtml(goal.minute_label || "")}</strong>
            <span class="gi-muted">${escapeHtml(goal.scorer_name || "")}</span>
            <span class="gil-recap__state">${goal.i_have_scored ? "scored" : goal.status === "closed" ? "closed" : "not scored"}</span>
          </li>
        `).join("")}
      </ul>
      <button type="button" class="gi-btn gi-btn--ghost" id="againBtn">Change an answer</button>
    </div>
  `;
  document.getElementById("againBtn").addEventListener("click", () => {
    state.index = 0;
    renderGoal(true);
  });
}

const DIRECT_VIDEO = /\.(mp4|m4v|mov|webm)(\?|#|$)/i;

// Coaches watch before they allocate, so the clip sits above the steppers.
// preload="metadata" keeps it off their mobile data until they press play.
function clipBlock(goal) {
  const clip = goal.clip || {};
  if (!clip.has_clip) return "";
  const player = (src) => `
    <video class="gil-clip" controls playsinline preload="metadata"
           src="${escapeHtml(src)}"></video>
  `;
  if (clip.kind === "file") {
    return player(`/api/gi/${encodeURIComponent(TOKEN)}/goals/${encodeURIComponent(goal.id)}/clip`);
  }
  if (clip.kind === "embed") {
    return `
      <div class="gil-clip gil-clip--frame">
        <iframe src="${escapeHtml(clip.url)}" title="Goal clip" allowfullscreen
                referrerpolicy="no-referrer" loading="lazy"></iframe>
      </div>
    `;
  }
  if (DIRECT_VIDEO.test(clip.url || "")) return player(clip.url);
  // Providers that refuse to be framed still get a way through.
  return `
    <a class="gi-btn gi-btn--ghost gil-clip__out" href="${escapeHtml(clip.url)}"
       target="_blank" rel="noopener">Watch the clip</a>
  `;
}

function goalTitle(goal) {
  if (goal.team_for_or_against === "scored") {
    return `We scored — ${goal.scorer_name || "goal"} ${goal.minute_label || ""}`;
  }
  return `We conceded — ${goal.minute_label || ""}`;
}

function renderGoal(force = false) {
  renderHeader();
  const queue = force ? goals() : outstanding();
  if (!queue.length) {
    renderDone();
    return;
  }
  if (state.index >= queue.length) state.index = 0;
  const goal = queue[state.index];
  state.allocations = {};
  (goal.my_allocations || []).forEach((row) => {
    if (row.points) state.allocations[row.player_id] = Number(row.points);
  });

  const label = goal.points_label || "involvement";
  const players = goal.players_on_pitch || [];
  const squad = (state.data.squad || []).filter(
    (row) => !players.some((player) => Number(player.id) === Number(row.id))
  );

  // Count against the whole game, not the leftover queue, or the second goal of
  // two reads "goal 1 of 1" once the first is saved.
  const position = goals().findIndex((row) => row.id === goal.id) + 1;

  // With one game the header already names it; across games each goal must say
  // which one it came from.
  const fixture = state.data?.multi_match
    ? `${goal.venue || ""} v ${goal.opponent || ""} · ${goal.date || ""} · `
    : "";

  els.stage.innerHTML = `
    <p class="gi-kicker">${escapeHtml(fixture)}Goal ${position} of ${goals().length} · ${escapeHtml(goal.scoreline_before || "")}</p>
    <h2 class="gil-goal">${escapeHtml(goalTitle(goal))}</h2>
    ${clipBlock(goal)}
    <p class="gi-muted gil-instruction">Split <strong>10 ${escapeHtml(label)} points</strong> between the players who mattered. Tap + and −. It has to total 10.</p>
    <div id="playerList">
      ${players.map((player) => `
        <div class="gi-player ${state.allocations[player.id] ? "gi-player--has" : ""}">
          <img class="gi-avatar" alt="" src="${escapeHtml(photoUrl(player))}" />
          <div>
            <strong>${escapeHtml(player.name)}</strong>
            <div class="gi-muted">${player.shirt ? `#${player.shirt} · ` : ""}${escapeHtml(player.position || "")}${player.started ? "" : player.added_by ? " · added" : " · sub"}</div>
          </div>
          <div class="gi-stepper">
            <button type="button" data-act="minus" data-id="${player.id}" aria-label="Remove a point from ${escapeHtml(player.name)}">−</button>
            <span class="gi-pts" id="pts-${player.id}">${state.allocations[player.id] || 0}</span>
            <button type="button" data-act="plus" data-id="${player.id}" aria-label="Add a point to ${escapeHtml(player.name)}">+</button>
          </div>
        </div>
      `).join("")}
    </div>
    ${squad.length ? `
      <label class="gi-addplayer">
        <span class="gi-muted">Someone missing?</span>
        <select id="addPlayer">
          <option value="">Add a player…</option>
          ${squad.map((row) => `<option value="${row.id}">${escapeHtml(row.name)}</option>`).join("")}
        </select>
      </label>
    ` : ""}
    <div class="gi-sticky">
      <div class="gi-remain ${remaining() === 0 ? "gi-remain--ok" : "gi-remain--bad"}">${remaining()} left</div>
      <button type="button" class="gi-btn gi-btn--primary" id="submitBtn" ${remaining() === 0 ? "" : "disabled"}>
        ${state.index + 1 < queue.length ? "Save &amp; next goal" : "Save &amp; finish"}
      </button>
    </div>
    <p class="gil-error" id="error" hidden></p>
  `;

  els.stage.querySelectorAll("[data-act]").forEach((button) => {
    button.addEventListener("click", () => {
      changePoints(Number(button.dataset.id), button.dataset.act === "plus" ? 1 : -1);
    });
  });
  document.getElementById("addPlayer")?.addEventListener("change", (event) => {
    const playerId = Number(event.target.value);
    if (playerId) addPlayer(goal.id, playerId);
  });
  document.getElementById("submitBtn").addEventListener("click", () => submit(goal, queue));
}

// Patch in place — re-rendering would throw the phone back to the top on every tap.
function changePoints(playerId, delta) {
  const next = Number(state.allocations[playerId] || 0) + delta;
  if (next < 0) return;
  if (delta > 0 && remaining() <= 0) return;
  state.allocations[playerId] = next;
  if (!state.allocations[playerId]) delete state.allocations[playerId];
  const cell = document.getElementById(`pts-${playerId}`);
  if (cell) {
    cell.textContent = String(state.allocations[playerId] || 0);
    cell.closest(".gi-player")?.classList.toggle("gi-player--has", Boolean(state.allocations[playerId]));
  }
  const left = remaining();
  const remain = els.stage.querySelector(".gi-remain");
  if (remain) {
    remain.textContent = `${left} left`;
    remain.className = `gi-remain ${left === 0 ? "gi-remain--ok" : "gi-remain--bad"}`;
  }
  const submit = document.getElementById("submitBtn");
  if (submit) submit.disabled = left !== 0;
}

function showError(message) {
  const box = document.getElementById("error");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
}

async function addPlayer(goalId, playerId) {
  try {
    state.data = await api(`/api/gi/${TOKEN}/goals/${goalId}/players`, {
      method: "POST",
      body: JSON.stringify({ player_id: playerId }),
    });
    renderGoal(true);
  } catch (error) {
    showError(error.message);
  }
}

async function submit(goal, queue) {
  if (state.busy) return;
  state.busy = true;
  const button = document.getElementById("submitBtn");
  if (button) {
    button.disabled = true;
    button.textContent = "Saving…";
  }
  try {
    const allocations = Object.entries(state.allocations).map(([playerId, points]) => ({
      player_id: Number(playerId),
      points: Number(points),
    }));
    state.data = await api(`/api/gi/${TOKEN}/goals/${goal.id}/score`, {
      method: "PUT",
      body: JSON.stringify({ allocations }),
    });
    state.busy = false;
    const more = outstanding();
    if (!more.length) {
      renderHeader();
      renderDone();
      return;
    }
    state.index = 0;
    renderGoal();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    state.busy = false;
    showError(error.message);
    if (button) {
      button.disabled = false;
      button.textContent = "Try again";
    }
  }
}

async function boot() {
  try {
    state.data = await api(`/api/gi/${TOKEN}`);
  } catch (error) {
    els.coachName.textContent = "Link not working";
    els.matchLine.textContent = "";
    els.stage.innerHTML = `
      <div class="gil-dead">
        <p>${escapeHtml(error.message)}</p>
        <p class="gi-muted">Ask the analysis team for a fresh link.</p>
      </div>
    `;
    return;
  }
  if (!goals().length) {
    // Normal state for a standing link once they are up to date, so this needs
    // to read as reassurance rather than as a fault.
    els.coachName.textContent = state.data?.coach?.display_name || "All done";
    els.matchLine.textContent = "";
    els.progress.hidden = true;
    els.stage.innerHTML = `
      <div class="gil-done">
        <div class="gil-tick" aria-hidden="true">✓</div>
        <h2>Nothing to score.</h2>
        <p class="gi-muted">You're up to date. Keep this link — when there are new goals to score it'll show them here, so there's no need to wait for another message.</p>
      </div>
    `;
    return;
  }
  renderGoal();
}

boot();
