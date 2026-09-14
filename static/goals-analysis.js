(() => {
  const API = "/api/goals-analysis";
  const state = {
    payload: null,
    tab: "log",
    week: "all",
    status: "uncoded",
    club: "",
    valeOnly: false,
    currentId: null,
    pitchTarget: "goal",
    draft: {},
    teamKey: "port-vale",
    teamProfile: null,
    playerKey: null,
    playerQuery: "",
  };

  const $ = (id) => document.getElementById(id);
  const statusEl = $("gaStatus");

  function showStatus(text, isError) {
    if (!text) {
      statusEl.classList.add("hidden");
      return;
    }
    statusEl.textContent = text;
    statusEl.classList.toggle("hidden", false);
    statusEl.classList.toggle("is-error", Boolean(isError));
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {
        detail = await res.text();
      }
      throw new Error(detail || "Request failed");
    }
    const type = res.headers.get("content-type") || "";
    if (type.includes("application/json")) return res.json();
    return res;
  }

  async function downloadExport(path) {
    const res = await fetch(path);
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {
        detail = await res.text();
      }
      throw new Error(detail || "Export failed");
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const filename = match?.[1] || "goals.csv";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function originClass(origin) {
    if (origin === "possession") return "is-poss";
    if (origin === "transition") return "is-trans";
    if (origin === "set_play") return "is-set";
    return "";
  }

  function originLabel(goal) {
    const tax = state.payload?.taxonomy;
    if (!goal?.origin) return "—";
    const origin = (tax?.origins || []).find((row) => row.id === goal.origin);
    const sub = ((tax?.subtypes || {})[goal.origin] || []).find((row) => row.id === goal.subtype);
    const phase = (tax?.phases || []).find((row) => row.id === goal.set_play_phase);
    const bits = [origin?.label || goal.origin, sub?.label || goal.subtype].filter(Boolean);
    if (phase && goal.origin === "set_play" && goal.subtype !== "penalty") bits.push(phase.label);
    return bits.join(" · ");
  }

  function finishLabel(goal) {
    const tax = state.payload?.taxonomy;
    const finish = (tax?.finishes || []).find((row) => row.id === goal?.finish_type);
    return finish?.label || "";
  }

  function barCount(bars, id) {
    const hit = (bars || []).find((row) => row.id === id);
    return hit ? hit.count : 0;
  }

  function goals() {
    return state.payload?.goals || [];
  }

  function filteredGoals() {
    const club = state.club.trim().toLowerCase();
    return goals().filter((goal) => {
      if (state.week !== "all" && String(goal.match_week) !== String(state.week)) return false;
      if (state.valeOnly && !goal.focus) return false;
      if (state.status === "uncoded" && goal.coded) return false;
      if (state.status === "coded" && !goal.coded) return false;
      if (state.status === "clips" && !goal.has_clip) return false;
      if (club) {
        const hay = `${goal.home} ${goal.away} ${goal.scorer_team} ${goal.scorer}`.toLowerCase();
        if (!hay.includes(club)) return false;
      }
      return true;
    });
  }

  function currentGoal() {
    return goals().find((goal) => goal.id === state.currentId) || null;
  }

  function renderKpis() {
    const tot = state.payload?.totals || {};
    $("gaKpis").innerHTML = [
      ["Goals", tot.goals || 0],
      ["Coded", tot.coded || 0],
      ["Clips", tot.clips || 0],
      ["Weeks", tot.weeks || 0],
    ]
      .map(([label, value]) => `<div class="ga-kpi"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`)
      .join("");
  }

  function renderWeekChips() {
    const weeks = state.payload?.weeks || [];
    const chips = [`<button type="button" class="ga-chip${state.week === "all" ? " is-active" : ""}" data-week="all">All</button>`];
    for (const week of weeks) {
      chips.push(
        `<button type="button" class="ga-chip${String(state.week) === String(week.week) ? " is-active" : ""}" data-week="${week.week}">MW${week.week} · ${week.coded}/${week.goals}</button>`
      );
    }
    $("gaWeekChips").innerHTML = chips.join("");
  }

  function renderQueue() {
    const rows = filteredGoals();
    $("gaQueueCount").textContent = `${rows.length} shown`;
    $("gaQueueList").innerHTML = rows
      .map((goal) => {
        const active = goal.id === state.currentId ? " is-active" : "";
        const vale = goal.focus ? " is-vale" : "";
        const clip = goal.has_clip ? " · clip" : "";
        const coded = goal.coded ? originLabel(goal) : "Queue";
        return `<button type="button" class="ga-q${active}${vale}" data-id="${esc(goal.id)}">
          <strong>${esc(goal.scorer)}</strong>
          <span>MW${esc(goal.match_week)} · ${esc(goal.minute_label)}' · ${esc(goal.scorer_team)} vs ${esc(goal.conceding_team)} · ${esc(coded)}${clip}</span>
        </button>`;
      })
      .join("") || `<p class="ga-empty">No goals match those filters.</p>`;
  }

  function pitchMarkings() {
    return `
      <rect x="0" y="0" width="105" height="68" fill="#147a3c" stroke="#f5f5f5" stroke-width=".45" />
      <line x1="52.5" y1="0" x2="52.5" y2="68" stroke="#f5f5f5" stroke-width=".35" />
      <circle cx="52.5" cy="34" r="9.15" fill="none" stroke="#f5f5f5" stroke-width=".35" />
      <circle cx="52.5" cy="34" r=".45" fill="#f5f5f5" />
      <rect x="0" y="13.84" width="16.5" height="40.32" fill="none" stroke="#f5f5f5" stroke-width=".35" />
      <rect x="88.5" y="13.84" width="16.5" height="40.32" fill="none" stroke="#f5f5f5" stroke-width=".35" />
      <rect x="0" y="24.84" width="5.5" height="18.32" fill="none" stroke="#f5f5f5" stroke-width=".35" />
      <rect x="99.5" y="24.84" width="5.5" height="18.32" fill="none" stroke="#f5f5f5" stroke-width=".35" />
      <circle cx="11" cy="34" r=".55" fill="#f5f5f5" />
      <circle cx="94" cy="34" r=".55" fill="#f5f5f5" />
      <rect x="-1.2" y="30.34" width="1.2" height="7.32" fill="none" stroke="#f5f5f5" stroke-width=".35" />
      <rect x="105" y="30.34" width="1.2" height="7.32" fill="none" stroke="#f5f5f5" stroke-width=".35" />
    `;
  }

  function xyToPitch(xy) {
    if (!xy) return null;
    return { x: xy.x + 52.5, y: 34 - xy.y };
  }

  function pitchToXy(xM, yM) {
    return {
      x: Math.round((xM - 52.5) * 100) / 100,
      y: Math.round((34 - yM) * 100) / 100,
    };
  }

  function renderPitch(goal) {
    const goalPt = xyToPitch(state.draft.goal_xy || goal.goal_xy);
    const assistPt = xyToPitch(state.draft.assist_xy || goal.assist_xy);
    const goalDot = goalPt
      ? `<circle cx="${goalPt.x}" cy="${goalPt.y}" r="1.6" fill="#f5c518" stroke="#111" stroke-width=".25" />`
      : "";
    const assistDot = assistPt
      ? `<circle cx="${assistPt.x}" cy="${assistPt.y}" r="1.25" fill="#38bdf8" stroke="#111" stroke-width=".25" />`
      : "";
    return `<svg class="ga-pitch" id="gaPitch" viewBox="-2 -2 109 72" role="img" aria-label="Impect pitch, attacking to the right">
      ${pitchMarkings()}${assistDot}${goalDot}
    </svg>`;
  }

  function choiceButtons(items, selected, attr) {
    return items
      .map(
        (item) =>
          `<button type="button" class="ga-choice${item.id === selected ? " is-active" : ""}" data-${attr}="${esc(item.id)}">${esc(item.label)}</button>`
      )
      .join("");
  }

  function renderCoder() {
    const goal = currentGoal();
    const box = $("gaCoder");
    if (!goal) {
      box.innerHTML = `<p class="ga-empty">Load League Two goals, drop the Wyscout folder, then pick a goal to code.</p>`;
      return;
    }
    const tax = state.payload.taxonomy;
    const origin = state.draft.origin || goal.origin || "";
    const subtype = state.draft.subtype || goal.subtype || "";
    const phase = state.draft.set_play_phase || goal.set_play_phase || "";
    const subs = tax.subtypes[origin] || [];
    const showPhase = origin === "set_play" && subtype && subtype !== "penalty";
    const finish = finishLabel(goal);
    const clip = goal.has_clip
      ? `<video class="ga-video" controls src="${esc(goal.clip_url)}"></video>`
      : `<div class="ga-clip-empty">No clip yet. Wyscout name: <code>${esc(goal.suggested_filename)}</code>
          <div class="ga-drop__row">
            <input id="gaAttachClip" type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm" hidden />
            <button type="button" class="btn btn--ghost btn--small" id="gaAttachBtn">Attach clip</button>
          </div>
        </div>`;

    box.innerHTML = `
      <h2>${esc(goal.scorer)} <span class="ga-pill ${originClass(origin)}">${esc(goal.minute_label)}'</span>${finish ? ` <span class="ga-pill">${esc(finish)}</span>` : ""}</h2>
      <p class="ga-meta">MW${esc(goal.match_week)} · ${esc(goal.date)} · ${esc(goal.scorer_team)} vs ${esc(goal.conceding_team)} · Assist ${esc(goal.assist || "none")}</p>
      <div class="ga-coder-grid">
        <div>
          ${clip}
          <p class="ga-label">Was the goal</p>
          <div class="ga-origin">${choiceButtons(tax.origins, origin, "origin")}</div>
          <div id="gaSubBlock" class="${origin ? "" : "hidden"}">
            <p class="ga-label">Type</p>
            <div class="ga-subs">${choiceButtons(subs, subtype, "sub")}</div>
          </div>
          <div id="gaPhaseBlock" class="${showPhase ? "" : "hidden"}">
            <p class="ga-label">Set-play phase</p>
            <div class="ga-phases">${choiceButtons(tax.phases, phase, "phase")}</div>
          </div>
          <p class="ga-label">Notes</p>
          <textarea class="ga-notes" id="gaNotes">${esc(state.draft.notes ?? goal.notes ?? "")}</textarea>
          <div class="ga-save-row">
            <button type="button" class="btn btn--gold" id="gaSaveNext">Save & next</button>
            <button type="button" class="btn btn--ghost" id="gaSave">Save</button>
            <button type="button" class="btn btn--ghost btn--small" id="gaClearAssist">No assist location</button>
          </div>
        </div>
        <div class="ga-pitch-wrap">
          <p class="ga-label">Locations · Impect XY, attacking to the right</p>
          <div class="ga-pitch-toggle">
            <button type="button" class="ga-chip${state.pitchTarget === "goal" ? " is-active" : ""}" data-target="goal">Goal</button>
            <button type="button" class="ga-chip${state.pitchTarget === "assist" ? " is-active" : ""}" data-target="assist">Assist</button>
          </div>
          ${renderPitch(goal)}
          <p class="ga-pitch-help">Click the pitch to stamp ${state.pitchTarget === "goal" ? "the shot" : "the assist"}. Gold = goal, blue = assist. Source: ${esc(goal.xy_source || "none")}.</p>
        </div>
      </div>
    `;
  }

  function barRows(items, color) {
    const max = Math.max(1, ...items.map((row) => row.count));
    return items
      .map((row) => {
        const width = Math.round((row.count / max) * 100);
        return `<div class="ga-bar"><span>${esc(row.label)}</span><span><i style="width:${width}%;background:${color}"></i></span><b>${row.count}</b></div>`;
      })
      .join("");
  }

  function sideHtml(title, side, color) {
    const points = (side.goal_points || [])
      .map((pt) => {
        const p = xyToPitch(pt);
        return p ? `<circle cx="${p.x}" cy="${p.y}" r="1.35" fill="${color}" />` : "";
      })
      .join("");
    const assists = (side.assist_points || [])
      .map((pt) => {
        const p = xyToPitch(pt);
        return p ? `<circle cx="${p.x}" cy="${p.y}" r=".9" fill="#38bdf8" />` : "";
      })
      .join("");
    return `<section>
      <h3>${esc(title)} · ${side.total}</h3>
      <div class="ga-bars">${barRows(side.origins || [], color)}</div>
      <div class="ga-bars">${barRows(side.subtypes || [], color)}</div>
      <svg class="ga-pitch" viewBox="-2 -2 109 72">${pitchMarkings()}${assists}${points}</svg>
    </section>`;
  }

  function playerGoalRows(rows) {
    return (rows || [])
      .map((goal) => {
        const finish = finishLabel(goal);
        return `<div class="ga-mini">
          <span>MW${esc(goal.match_week)} · ${esc(goal.minute_label)}' vs ${esc(goal.opponent)} · ${esc(originLabel(goal))}${finish ? ` · ${esc(finish)}` : ""}</span>
          <span>${goal.has_clip ? "clip" : ""}</span>
        </div>`;
      })
      .join("") || `<p class="ga-empty">No goals listed.</p>`;
  }

  function renderLeague() {
    const clubs = state.payload?.league || [];
    $("gaLeagueBody").innerHTML = clubs
      .map((club) => {
        const badge = club.badge ? `<img src="${esc(club.badge)}" alt="" />` : "";
        return `<tr data-club="${esc(club.id)}" class="${club.focus ? "is-vale" : ""}">
          <td><div class="ga-fix">${badge}<span>${esc(club.name)}</span></div></td>
          <td>${club.scored}</td>
          <td>${club.conceded}</td>
          <td>${club.gd > 0 ? "+" : ""}${club.gd}</td>
          <td>${barCount(club.scored_origins, "possession")}</td>
          <td>${barCount(club.scored_origins, "transition")}</td>
          <td>${barCount(club.scored_origins, "set_play")}</td>
          <td>${barCount(club.conceded_origins, "possession")}</td>
          <td>${barCount(club.conceded_origins, "transition")}</td>
          <td>${barCount(club.conceded_origins, "set_play")}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="10" class="ga-empty">Load League Two goals first.</td></tr>`;
  }

  function renderTeamSelect() {
    const clubs = state.payload?.clubs || [];
    const select = $("gaTeamSelect");
    if (!clubs.length) {
      select.innerHTML = `<option value="">No clubs yet</option>`;
      return;
    }
    if (!state.teamKey || !clubs.some((club) => club.id === state.teamKey)) {
      const vale = clubs.find((club) => club.focus);
      state.teamKey = vale?.id || clubs[0].id;
    }
    select.innerHTML = clubs
      .map((club) => `<option value="${esc(club.id)}">${esc(club.name)}</option>`)
      .join("");
    select.value = state.teamKey;
  }

  async function openTeam(clubKey) {
    if (!clubKey) return;
    state.teamKey = clubKey;
    $("gaTeamSelect").value = clubKey;
    showStatus("Loading club profile…");
    try {
      const profile = await api(`${API}/teams/${encodeURIComponent(clubKey)}`);
      state.teamProfile = profile;
      const players = (profile.players || [])
        .map((player) => {
          return `<article class="ga-player-card">
            <header>
              <strong>${esc(player.name)}</strong>
              <span>${player.goals} goal${player.goals === 1 ? "" : "s"} scored</span>
            </header>
            <div class="ga-mini-list">${playerGoalRows(player.rows)}</div>
          </article>`;
        })
        .join("") || `<p class="ga-empty">No scorers for this club yet.</p>`;
      $("gaTeam").innerHTML = `
        <h2>${esc(profile.name)}</h2>
        <p class="ga-meta">${profile.scored.coded}/${profile.scored.total} scored coded · ${profile.conceded.coded}/${profile.conceded.total} conceded coded</p>
        <div class="ga-split">
          ${sideHtml("Goals scored", profile.scored, "#f5c518")}
          ${sideHtml("Goals conceded", profile.conceded, "#e52320")}
        </div>
        <h3 class="ga-players-head">Players — goals scored</h3>
        <div class="ga-player-cards">${players}</div>
      `;
      showStatus(state.payload.updated_at ? `Last loaded ${state.payload.updated_at}` : "");
    } catch (err) {
      showStatus(err.message, true);
    }
  }

  function renderPlayers() {
    const needle = state.playerQuery.trim().toLowerCase();
    const rows = (state.payload?.players || []).filter((player) => {
      if (!needle) return true;
      return `${player.name} ${player.club}`.toLowerCase().includes(needle);
    });
    $("gaPlayerBody").innerHTML = rows
      .map((player) => {
        const badge = player.badge ? `<img src="${esc(player.badge)}" alt="" />` : "";
        const active = player.id === state.playerKey ? " is-active" : "";
        return `<tr data-player="${esc(player.id)}" class="${active}">
          <td><strong>${esc(player.name)}</strong></td>
          <td><div class="ga-fix">${badge}<span>${esc(player.club)}</span></div></td>
          <td>${player.goals}</td>
          <td>${player.coded}</td>
          <td>${player.clips}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="5" class="ga-empty">No scorers match.</td></tr>`;
    const selected = (state.payload?.players || []).find((player) => player.id === state.playerKey);
    if (!selected) {
      $("gaPlayerDetail").innerHTML = `<p class="ga-empty">Click a player to see each goal scored.</p>`;
      return;
    }
    $("gaPlayerDetail").innerHTML = `
      <h3>${esc(selected.name)} · ${esc(selected.club)} · ${selected.goals} goals</h3>
      <div class="ga-mini-list">${playerGoalRows(selected.rows)}</div>
    `;
  }

  async function renderVideos() {
    try {
      const payload = await api(`${API}/videos`);
      $("gaVideoList").innerHTML = (payload.files || [])
        .map(
          (file) => `<div class="ga-v"><span>${esc(file.filename)}</span><span>${esc(file.label)}</span></div>`
        )
        .join("") || `<p class="ga-empty">No clips stored yet.</p>`;
    } catch (err) {
      $("gaVideoList").innerHTML = `<p class="ga-empty">${esc(err.message)}</p>`;
    }
  }

  function render() {
    if (!state.payload) return;
    renderKpis();
    renderWeekChips();
    renderQueue();
    renderCoder();
    renderLeague();
    renderTeamSelect();
    renderPlayers();
    const updated = state.payload.updated_at ? `Last loaded ${state.payload.updated_at}` : "Goals not loaded yet.";
    if (state.payload.needs_refresh) {
      showStatus("No catalog yet — click Load League Two goals. That pulls every completed league match from Impect.");
    } else if (state.payload.error) {
      showStatus(`${updated}. Some matches failed: ${state.payload.error}`, true);
    } else {
      showStatus(updated);
    }
  }

  async function load() {
    state.payload = await api(API);
    if (!state.currentId) {
      const next = filteredGoals()[0] || goals()[0];
      state.currentId = next?.id || null;
    }
    state.draft = {};
    render();
    if (state.tab === "log") renderVideos();
    if (state.tab === "team" && state.teamKey) openTeam(state.teamKey);
  }

  async function refreshCatalog() {
    const btn = $("gaRefreshBtn");
    btn.disabled = true;
    btn.textContent = "Loading…";
    showStatus("Pulling League Two goals from Impect. First run can take a minute.");
    try {
      state.payload = await api(`${API}/refresh`, { method: "POST" });
      const next = filteredGoals()[0] || goals()[0];
      state.currentId = next?.id || state.currentId;
      render();
    } catch (err) {
      showStatus(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Load League Two goals";
    }
  }

  function setTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".ga-tab").forEach((btn) => {
      const on = btn.dataset.tab === tab;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".ga-panel").forEach((panel) => {
      panel.classList.toggle("hidden", panel.dataset.panel !== tab);
    });
    if (tab === "log") {
      renderCoder();
      renderVideos();
    }
    if (tab === "league") renderLeague();
    if (tab === "team" && state.teamKey) openTeam(state.teamKey);
    if (tab === "player") renderPlayers();
  }

  function openGoal(id) {
    state.currentId = id;
    state.draft = {};
    if (state.tab !== "log") setTab("log");
    renderQueue();
    renderCoder();
  }

  function nextFiltered(afterId) {
    const rows = filteredGoals();
    const idx = rows.findIndex((row) => row.id === afterId);
    const next = rows[idx + 1] || rows[0] || null;
    return next && next.id !== afterId ? next.id : null;
  }

  async function saveGoal(andNext) {
    const goal = currentGoal();
    if (!goal) return;
    const notes = $("gaNotes") ? $("gaNotes").value : "";
    const body = {
      origin: state.draft.origin || goal.origin || null,
      subtype: state.draft.subtype || goal.subtype || null,
      set_play_phase: state.draft.set_play_phase || goal.set_play_phase || null,
      goal_xy: state.draft.goal_xy || undefined,
      assist_xy: state.draft.assist_xy || undefined,
      clear_assist_xy: Boolean(state.draft.clear_assist_xy),
      notes,
    };
    try {
      await api(`${API}/goals/${encodeURIComponent(goal.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (andNext) state.currentId = nextFiltered(goal.id);
      state.draft = {};
      await load();
    } catch (err) {
      showStatus(err.message, true);
    }
  }

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const data = new FormData();
    for (const file of fileList) data.append("files", file);
    showStatus("Copying clips into the store…");
    try {
      const result = await api(`${API}/videos`, { method: "POST", body: data });
      showStatus(`Stored ${result.uploaded?.length || 0}. Matched ${result.matched?.length || 0}. Unmatched ${result.unmatched?.length || 0}.`);
      await load();
    } catch (err) {
      showStatus(err.message, true);
    }
  }

  async function scanInbox() {
    showStatus("Scanning folder…");
    try {
      const result = await api(`${API}/videos/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: $("gaScanPath").value.trim() }),
      });
      showStatus(`Copied ${result.copied}. Matched ${result.matched.length}. Unmatched: ${result.unmatched.length}.`);
      await load();
    } catch (err) {
      showStatus(err.message, true);
    }
  }

  async function importFile(kind, file) {
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    const path = kind === "csv" ? `${API}/import/csv` : `${API}/import/impect`;
    showStatus(`Importing ${kind.toUpperCase()}…`);
    try {
      const result = await api(path, { method: "POST", body: data });
      showStatus(JSON.stringify(result));
      await load();
    } catch (err) {
      showStatus(err.message, true);
    }
  }

  document.addEventListener("click", (event) => {
    const tab = event.target.closest(".ga-tab");
    if (tab) {
      setTab(tab.dataset.tab);
      return;
    }
    const weekChip = event.target.closest("[data-week]");
    if (weekChip && weekChip.closest("#gaWeekChips")) {
      state.week = weekChip.dataset.week;
      renderWeekChips();
      renderQueue();
      return;
    }
    const statusChip = event.target.closest("[data-status]");
    if (statusChip) {
      state.status = statusChip.dataset.status;
      document.querySelectorAll("#gaStatusChips .ga-chip").forEach((btn) => {
        btn.classList.toggle("is-active", btn === statusChip);
      });
      renderQueue();
      return;
    }
    const q = event.target.closest(".ga-q[data-id]");
    if (q) {
      openGoal(q.dataset.id);
      return;
    }
    const originBtn = event.target.closest("[data-origin]");
    if (originBtn) {
      state.draft.origin = originBtn.dataset.origin;
      state.draft.subtype = "";
      state.draft.set_play_phase = "";
      renderCoder();
      return;
    }
    const subBtn = event.target.closest("[data-sub]");
    if (subBtn) {
      state.draft.subtype = subBtn.dataset.sub;
      if (subBtn.dataset.sub === "penalty") state.draft.set_play_phase = "";
      renderCoder();
      return;
    }
    const phaseBtn = event.target.closest("[data-phase]");
    if (phaseBtn) {
      state.draft.set_play_phase = phaseBtn.dataset.phase;
      renderCoder();
      return;
    }
    const targetBtn = event.target.closest("[data-target]");
    if (targetBtn) {
      state.pitchTarget = targetBtn.dataset.target;
      renderCoder();
      return;
    }
    const leagueRow = event.target.closest("#gaLeagueBody tr[data-club]");
    if (leagueRow) {
      state.teamKey = leagueRow.dataset.club;
      setTab("team");
      return;
    }
    const playerRow = event.target.closest("#gaPlayerBody tr[data-player]");
    if (playerRow) {
      state.playerKey = playerRow.dataset.player;
      renderPlayers();
      return;
    }
    if (event.target.id === "gaSaveNext") saveGoal(true);
    if (event.target.id === "gaSave") saveGoal(false);
    if (event.target.id === "gaClearAssist") {
      state.draft.assist_xy = null;
      state.draft.clear_assist_xy = true;
      renderCoder();
    }
    if (event.target.id === "gaAttachBtn") $("gaAttachClip")?.click();
  });

  document.addEventListener("change", (event) => {
    if (event.target.id === "gaClubFilter") {
      state.club = event.target.value;
      renderQueue();
    }
    if (event.target.id === "gaValeOnly") {
      state.valeOnly = event.target.checked;
      renderQueue();
    }
    if (event.target.id === "gaTeamSelect") {
      openTeam(event.target.value);
    }
    if (event.target.id === "gaPlayerSearch") {
      state.playerQuery = event.target.value;
      renderPlayers();
    }
    if (event.target.id === "gaAttachClip" && event.target.files?.[0]) {
      const goal = currentGoal();
      if (!goal) return;
      const data = new FormData();
      data.append("file", event.target.files[0]);
      api(`${API}/goals/${encodeURIComponent(goal.id)}/clip`, { method: "POST", body: data })
        .then(load)
        .catch((err) => showStatus(err.message, true));
    }
    if (event.target.id === "gaFileInput") uploadFiles(event.target.files);
    if (event.target.id === "gaCsvInput") importFile("csv", event.target.files[0]);
    if (event.target.id === "gaJsonInput") importFile("json", event.target.files[0]);
  });

  document.addEventListener("input", (event) => {
    if (event.target.id === "gaClubFilter") {
      state.club = event.target.value;
      renderQueue();
    }
    if (event.target.id === "gaPlayerSearch") {
      state.playerQuery = event.target.value;
      renderPlayers();
    }
  });

  document.addEventListener("click", (event) => {
    const svg = event.target.closest("#gaPitch");
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const xM = ((event.clientX - rect.left) / rect.width) * 109 - 2;
    const yM = ((event.clientY - rect.top) / rect.height) * 72 - 2;
    const xy = pitchToXy(Math.max(0, Math.min(105, xM)), Math.max(0, Math.min(68, yM)));
    if (state.pitchTarget === "assist") {
      state.draft.assist_xy = xy;
      state.draft.clear_assist_xy = false;
    } else {
      state.draft.goal_xy = xy;
    }
    renderCoder();
  });

  $("gaRefreshBtn").addEventListener("click", refreshCatalog);
  $("gaPickFiles").addEventListener("click", () => $("gaFileInput").click());
  $("gaScanBtn").addEventListener("click", scanInbox);
  $("gaCsvBtn").addEventListener("click", () => $("gaCsvInput").click());
  $("gaJsonBtn").addEventListener("click", () => $("gaJsonInput").click());
  $("gaLeagueExport").addEventListener("click", () => {
    downloadExport(`${API}/export/league.csv`).catch((err) => showStatus(err.message, true));
  });
  $("gaLeaguePrint").addEventListener("click", () => window.print());
  $("gaTeamExport").addEventListener("click", () => {
    if (!state.teamKey) return;
    downloadExport(`${API}/export/team/${encodeURIComponent(state.teamKey)}`).catch((err) => showStatus(err.message, true));
  });
  $("gaTeamPrint").addEventListener("click", () => window.print());
  $("gaPlayerExport").addEventListener("click", () => {
    const path = state.playerKey
      ? `${API}/export/player/${encodeURIComponent(state.playerKey)}`
      : `${API}/export/players.csv`;
    downloadExport(path).catch((err) => showStatus(err.message, true));
  });
  $("gaPlayerPrint").addEventListener("click", () => window.print());

  const drop = $("gaDrop");
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("is-over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("is-over");
    uploadFiles(event.dataTransfer.files);
  });

  load().catch((err) => showStatus(err.message, true));
})();
