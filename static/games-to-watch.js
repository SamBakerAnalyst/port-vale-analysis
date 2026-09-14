(() => {
  const els = {
    status: document.getElementById("gwStatus"),
    sub: document.getElementById("gwSub"),
    kpis: document.getElementById("gwKpis"),
    leagues: document.getElementById("gwLeagues"),
    window: document.getElementById("gwWindow"),
    coverage: document.getElementById("gwCoverage"),
    phase: document.getElementById("gwPhase"),
    look: document.getElementById("gwLook"),
    search: document.getElementById("gwSearch"),
    list: document.getElementById("gwList"),
    listCount: document.getElementById("gwListCount"),
    listTitle: document.getElementById("gwListTitle"),
    sheetEmpty: document.getElementById("gwSheetEmpty"),
    sheetBody: document.getElementById("gwSheetBody"),
  };

  const state = {
    payload: null,
    league: "ALL",
    window: "all",
    phase: "played",
    coverage: "all",
    look: "scores",
    query: "",
    openId: "",
    sheet: null,
    watchType: "VIDEO",
    staff: "",
    picked: new Set(),
    loadingSheet: false,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function setStatus(message, kind = "") {
    if (!els.status) return;
    if (!message) {
      els.status.classList.add("hidden");
      els.status.textContent = "";
      return;
    }
    els.status.classList.remove("hidden", "is-error", "is-ok");
    if (kind) els.status.classList.add(kind);
    els.status.textContent = message;
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || data.message || `Request failed (${response.status})`);
    }
    return data;
  }

  function parseDate(value) {
    const token = String(value || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(token)) return null;
    return new Date(`${token}T12:00:00Z`);
  }

  function formatDate(value) {
    const date = parseDate(value);
    if (!date) return "";
    return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  }

  function formatKickoff(value) {
    const raw = String(value || "");
    if (!raw.includes("T")) return "";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  function daysFromToday(value) {
    const date = parseDate(value);
    if (!date) return 999;
    const today = new Date();
    const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    const other = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
    return Math.round((other - start) / 86400000);
  }

  function isFootballWeekend(value) {
    const date = parseDate(value);
    if (!date) return false;
    const day = date.getUTCDay();
    return day === 5 || day === 6 || day === 0;
  }

  function toneFor(pct) {
    if (pct == null) return "#64748b";
    if (pct >= 75) return "#22c55e";
    if (pct >= 50) return "#f5c518";
    if (pct >= 25) return "#f59e0b";
    return "#ef4444";
  }

  function watchLabel(pct) {
    if (pct == null) return { text: "No scores", cls: "" };
    if (pct >= 70) return { text: "Must watch", cls: "is-must" };
    if (pct >= 40) return { text: "Worth a look", cls: "is-mid" };
    if (pct >= 20) return { text: "Low yield", cls: "is-low" };
    return { text: "Skip", cls: "is-low" };
  }

  function lookMeta() {
    if (state.look === "young") {
      return { title: "Ranked by young players", lbl: "young", sheet: "Young" };
    }
    if (state.look === "both") {
      return { title: "Ranked by scores and youth", lbl: "both", sheet: "Both" };
    }
    return { title: "Ranked by high scores", lbl: "scores", sheet: "Scores" };
  }

  function mixingLeagues() {
    return state.league === "ALL";
  }

  function lookRank(game) {
    const mix = mixingLeagues();
    if (state.look === "young") {
      if (mix && game.young_mix_pct != null) return game.young_mix_pct;
      return game.young_pct != null ? game.young_pct : game.youth_pct;
    }
    if (state.look === "both") {
      if (mix && game.both_mix_pct != null) return game.both_mix_pct;
      if (game.both_pct != null) return game.both_pct;
      const score = game.score_pct != null ? game.score_pct : game.quality_pct;
      const young = game.young_pct != null ? game.young_pct : game.youth_pct;
      if (score == null) return young;
      if (young == null) return score;
      return Math.round((Number(score) + Number(young)) / 2);
    }
    if (mix && game.score_mix_pct != null) return game.score_mix_pct;
    if (game.score_pct != null) return game.score_pct;
    if (game.quality_pct != null) return game.quality_pct;
    return game.watch_pct;
  }

  function lookHeadlines(game) {
    if (state.look === "scores") return game.score_headlines || game.headlines || [];
    return game.headlines || [];
  }

  function applyLookCopy() {
    const notes = state.payload?.scoring?.notes || {};
    const note = notes[state.look] || state.payload?.scoring?.note || "";
    if (els.sub && note) els.sub.textContent = note;
    if (els.listTitle) els.listTitle.textContent = lookMeta().title;
  }

  function games() {
    return state.payload?.games || [];
  }

  function visibleGames() {
    const q = state.query.trim().toLowerCase();
    const rows = games().filter((game) => {
      if (state.league !== "ALL" && game.league !== state.league) return false;
      if (state.coverage === "assigned" && !game.assignment) return false;
      if (state.coverage === "unassigned" && game.assignment) return false;
      if (state.phase === "played" && !game.played) return false;
      if (state.phase === "upcoming" && game.played) return false;
      const days = daysFromToday(game.date);
      if (state.window === "weekend") {
        if (!isFootballWeekend(game.date) || Math.abs(days) > 10) return false;
      } else if (state.window !== "all") {
        const limit = Number(state.window);
        if (Math.abs(days) > limit) return false;
      }
      if (!q) return true;
      const hay = [
        game.home?.name,
        game.away?.name,
        game.league,
        ...lookHeadlines(game).map((row) => row.name),
        ...(game.headlines || []).map((row) => row.name),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
    rows.sort((a, b) => {
      const ap = lookRank(a);
      const bp = lookRank(b);
      if (ap == null && bp == null) return String(a.date || "").localeCompare(String(b.date || ""));
      if (ap == null) return 1;
      if (bp == null) return -1;
      if (bp !== ap) return bp - ap;
      return String(a.date || "").localeCompare(String(b.date || ""));
    });
    return rows;
  }

  function renderKpis() {
    const rows = visibleGames();
    const scored = rows.filter((row) => lookRank(row) != null);
    const must = scored.filter((row) => lookRank(row) >= 70).length;
    const open = rows.filter((row) => !row.assignment).length;
    const played = rows.filter((row) => row.played).length;
    els.kpis.innerHTML = `
      <div class="gw-kpi"><span>In view</span><strong>${rows.length}</strong></div>
      <div class="gw-kpi"><span>Must watch</span><strong>${must}</strong></div>
      <div class="gw-kpi"><span>Played</span><strong>${played}</strong></div>
      <div class="gw-kpi"><span>Unassigned</span><strong>${open}</strong></div>
    `;
  }

  function renderLeagues() {
    const leagues = state.payload?.leagues || [];
    els.leagues.innerHTML = [
      `<button type="button" class="gw-chip${state.league === "ALL" ? " is-active" : ""}" data-league="ALL">All leagues</button>`,
      ...leagues.map((league) => {
        const id = league.id || league;
        const color = league.color || "#3d8bfd";
        const active = state.league === id ? " is-active is-league" : "";
        return `<button type="button" class="gw-chip${active}" data-league="${escapeHtml(id)}" style="--league:${color}">${escapeHtml(id)}</button>`;
      }),
    ].join("");
    els.leagues.querySelectorAll("[data-league]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.league = btn.dataset.league || "ALL";
        render();
      });
    });
  }

  function paintChipGroup(root, key) {
    if (!root) return;
    root.querySelectorAll("button").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset[key] === String(state[key]));
    });
  }

  function bindChipGroup(root, key) {
    if (!root) return;
    root.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state[key] = btn.dataset[key];
        render();
        if (key === "look" && state.sheet) renderSheet();
      });
    });
  }

  function headlineText(game) {
    const names = lookHeadlines(game).map((row) => {
      const age = row.age != null ? ` ${row.age}` : "";
      const score = row.overall != null ? ` ${Number(row.overall).toFixed(0)}` : "";
      return `${row.name}${age}${score}`;
    });
    return names.join(" · ");
  }

  function renderList() {
    const rows = visibleGames();
    els.listCount.textContent = `${rows.length} game${rows.length === 1 ? "" : "s"}`;
    if (!rows.length) {
      els.list.innerHTML = `<p class="gw-assign__note" style="padding:.8rem">No fixtures in this filter.</p>`;
      return;
    }
    els.list.innerHTML = rows
      .map((game) => {
        const pct = lookRank(game);
        const label = watchLabel(pct);
        const assigned = game.assignment
          ? `${(game.assignment.staff || []).join(", ") || "Assigned"} · ${game.assignment.watch_type || ""}`.trim()
          : "";
        const open = state.openId === game.fixture_id ? " is-open" : "";
        const heads = headlineText(game);
        const rankLbl = lookMeta().lbl;
        return `
          <button type="button" class="gw-row${open}" data-open="${escapeHtml(game.fixture_id)}">
            <div class="gw-score">
              <span class="gw-score__n" style="color:${toneFor(pct)}">${pct == null ? "—" : `${pct}%`}</span>
              <span class="gw-score__bar"><span style="width:${pct || 0}%;background:${toneFor(pct)}"></span></span>
              <span class="gw-score__lbl">${rankLbl}</span>
            </div>
            <div class="gw-row__match">
              <p class="gw-row__teams">${escapeHtml(game.home?.name || "Home")} vs ${escapeHtml(game.away?.name || "Away")}</p>
              <p class="gw-row__meta">
                <span class="gw-league-dot" style="--league:${game.league_color || "#3d8bfd"}"></span>
                ${escapeHtml(game.league || "")} · ${escapeHtml(formatDate(game.date))}
                ${formatKickoff(game.kickoff_utc) ? ` · ${escapeHtml(formatKickoff(game.kickoff_utc))}` : ""}
                ${game.played ? ` · Played${game.score ? ` ${escapeHtml(game.score)}` : ""}` : ""}
                · ${game.u27_count || 0} U27s
                ${game.quality_pct != null ? ` · avg ${game.quality_pct}` : ""}
              </p>
              ${heads ? `<p class="gw-row__heads">${escapeHtml(heads)}</p>` : ""}
            </div>
            <div class="gw-row__side">
              <span class="gw-pill ${label.cls}">${escapeHtml(label.text)}</span>
              ${game.played ? `<span class="gw-pill is-played">Played</span>` : `<span class="gw-pill">Upcoming</span>`}
              ${assigned ? `<span class="gw-pill is-set">${escapeHtml(assigned)}</span>` : ""}
            </div>
          </button>
        `;
      })
      .join("");
    els.list.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => openFixture(btn.dataset.open));
    });
  }

  function transferClass(player) {
    const move = player?.transfer;
    if (!move?.status) return "";
    if (move.status === "loan_in") return "is-loan";
    if (move.status === "loan_out" || move.status === "gone") return "is-moved";
    if (move.status === "check") return "is-move-check";
    return "";
  }

  function transferHint(player) {
    const move = player?.transfer;
    if (!move?.status) return "";
    if (move.status === "loan_in") return `on loan from ${move.from || "parent club"}`;
    if (move.status === "loan_out") return `on loan at ${move.club}`;
    if (move.status === "gone") return `now ${move.club}`;
    if (move.status === "check") return `${move.club}?`;
    return "";
  }

  function playerRow(player, side) {
    const id = String(player.player_id || "");
    const picked = id && state.picked.has(id);
    const age = player.age != null ? String(player.age) : "—";
    const score = player.overall != null ? Number(player.overall).toFixed(1) : "—";
    const mins = player.minutes != null ? String(player.minutes) : "—";
    const href = player.dossier_href || (player.player_id ? `/player/${player.player_id}` : "");
    const name = href
      ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(player.name)}</a>`
      : escapeHtml(player.name);
    const hint = transferHint(player);
    const moveCls = transferClass(player);
    return `
      <tr class="${player.u27 ? "is-u27" : ""} ${picked ? "is-picked" : ""} ${moveCls}">
        <td>
          <label>
            <input type="checkbox" data-player-id="${escapeHtml(id)}" data-player-name="${escapeHtml(player.name)}" data-side="${side}" data-club="${escapeHtml(player.club || "")}" ${picked ? "checked" : ""} ${id ? "" : "disabled"} />
          </label>
        </td>
        <td>
          <div class="gw-name">
            ${name}
            <span>${escapeHtml(player.position_label || player.position || "")}${player.best_profile ? ` · ${escapeHtml(player.best_profile)}` : ""}${hint ? ` · ${escapeHtml(hint)}` : ""}</span>
          </div>
        </td>
        <td class="gw-num gw-age ${player.u27 ? "is-u27" : ""}">${escapeHtml(age)}</td>
        <td class="gw-num">${escapeHtml(mins)}</td>
        <td class="gw-num">${escapeHtml(score)}</td>
      </tr>
    `;
  }

  function teamColumn(side, team) {
    const players = team?.players || [];
    const u27 = players.filter((row) => row.u27).length;
    const rows = players.length
      ? players.map((player) => playerRow(player, side)).join("")
      : `<tr><td colspan="5" class="gw-assign__note">No profile scores for this club yet.</td></tr>`;
    return `
      <section class="gw-team">
        <h3>${escapeHtml(team?.name || (side === "home" ? "Home" : "Away"))} · ${players.length} · ${u27} U27</h3>
        <div class="gw-team__scroll">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Player</th>
                <th>Age</th>
                <th>Mins</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  function staffOptions(sheet) {
    const teams = sheet.staff_teams || state.payload?.staff_teams || [];
    const current = state.staff;
    const groups = teams
      .filter((team) => (team.members || []).length)
      .map((team) => {
        const options = (team.members || [])
          .map((name) => `<option value="${escapeHtml(name)}" ${name === current ? "selected" : ""}>${escapeHtml(name)}</option>`)
          .join("");
        return `<optgroup label="${escapeHtml(team.label)}">${options}</optgroup>`;
      })
      .join("");
    const fallback = (sheet.staff || state.payload?.staff || [])
      .map((name) => `<option value="${escapeHtml(name)}" ${name === current ? "selected" : ""}>${escapeHtml(name)}</option>`)
      .join("");
    return `<option value="">Choose scout</option>${groups || fallback}`;
  }

  function renderSheet() {
    const sheet = state.sheet;
    if (!sheet) {
      els.sheetEmpty.classList.remove("hidden");
      els.sheetBody.classList.add("hidden");
      els.sheetBody.innerHTML = "";
      return;
    }
    els.sheetEmpty.classList.add("hidden");
    els.sheetBody.classList.remove("hidden");
    const pct = lookRank(sheet);
    const label = watchLabel(pct);
    const assigned = sheet.assignment
      ? `${(sheet.assignment.staff || []).join(", ") || "Assigned"} · ${sheet.assignment.watch_type || ""}`
      : "Not in Fixture Planner yet";
    const rankLbl = lookMeta().sheet;
    els.sheetBody.innerHTML = `
      <div class="gw-sheet__top">
        <p class="gw-eyebrow">${escapeHtml(sheet.league || "")} · ${escapeHtml(formatDate(sheet.date))} ${formatKickoff(sheet.kickoff_utc) ? `· ${escapeHtml(formatKickoff(sheet.kickoff_utc))}` : ""} ${sheet.played ? `· Played${sheet.score ? ` ${escapeHtml(sheet.score)}` : ""}` : "· Upcoming"}</p>
        <h2>${escapeHtml(sheet.home?.name || "Home")} vs ${escapeHtml(sheet.away?.name || "Away")}</h2>
        <div class="gw-sheet__stats">
          <span class="gw-stat">${rankLbl} <strong style="color:${toneFor(pct)}">${pct == null ? "—" : `${pct}%`}</strong></span>
          <span class="gw-stat">Profile avg <strong>${sheet.quality_pct ?? "—"}</strong></span>
          <span class="gw-stat">U27 share <strong>${sheet.youth_pct ?? "—"}%</strong></span>
          <span class="gw-stat">U27s playing <strong>${sheet.u27_count ?? 0}</strong></span>
          <span class="gw-pill ${label.cls}">${escapeHtml(label.text)}</span>
          ${sheet.played ? `<span class="gw-pill is-played">Played${sheet.score ? ` · ${escapeHtml(sheet.score)}` : ""}</span>` : `<span class="gw-pill">Upcoming</span>`}
          <span class="gw-pill ${sheet.assignment ? "is-set" : ""}">${escapeHtml(assigned)}</span>
        </div>
      </div>
      <div class="gw-teams">
        ${teamColumn("home", sheet.home)}
        ${teamColumn("away", sheet.away)}
      </div>
      <form class="gw-assign" id="gwAssignForm">
        <p class="gw-assign__note">Tick players to watch, pick a scout, assign Video into Fixture Planner. Default is Video so we maximise the tape.</p>
        <div class="gw-assign__row">
          <label>Scout
            <select id="gwStaff">${staffOptions(sheet)}</select>
          </label>
          <div class="gw-watch" role="group" aria-label="Watch type">
            ${(sheet.watch_types || ["VIDEO", "LIVE"]).map((type) => `
              <button type="button" data-watch="${type}" class="${state.watchType === type ? "is-active" : ""}">${type}</button>
            `).join("")}
          </div>
          <button type="submit" class="gw-assign__go" id="gwAssignBtn">Assign to Fixture Planner</button>
          <a href="/player-reports?fixture=${encodeURIComponent(sheet.fixture_id || "")}">Player Reports →</a>
          <a href="/fixture-planner">Open planner</a>
        </div>
      </form>
    `;
    els.sheetBody.querySelectorAll("input[data-player-id]").forEach((input) => {
      input.addEventListener("change", () => {
        const id = input.dataset.playerId;
        if (!id) return;
        if (input.checked) state.picked.add(id);
        else state.picked.delete(id);
      });
    });
    els.sheetBody.querySelectorAll("[data-watch]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.watchType = btn.dataset.watch || "VIDEO";
        renderSheet();
      });
    });
    const staffSelect = document.getElementById("gwStaff");
    if (staffSelect) {
      staffSelect.addEventListener("change", () => {
        state.staff = staffSelect.value;
      });
    }
    document.getElementById("gwAssignForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      assignCurrent();
    });
  }

  function selectedPlayers() {
    const sheet = state.sheet;
    if (!sheet) return [];
    const rows = [...(sheet.home?.players || []).map((row) => ({ ...row, side: "home" })), ...(sheet.away?.players || []).map((row) => ({ ...row, side: "away" }))];
    return rows
      .filter((row) => row.player_id && state.picked.has(String(row.player_id)))
      .map((row) => ({
        player_id: row.player_id,
        player_name: row.name,
        team: row.club || (row.side === "home" ? sheet.home?.name : sheet.away?.name) || "",
        side: row.side,
      }));
  }

  async function assignCurrent() {
    const sheet = state.sheet;
    if (!sheet) return;
    if (!state.staff) {
      setStatus("Pick a scout before assigning.", "is-error");
      return;
    }
    const btn = document.getElementById("gwAssignBtn");
    if (btn) btn.disabled = true;
    setStatus("Saving into Fixture Planner…");
    try {
      const data = await fetchJson("/api/games-to-watch/assign", {
        method: "POST",
        body: JSON.stringify({
          fixture_id: sheet.fixture_id,
          staff: [...new Set([...(sheet.assignment?.staff || []), state.staff].filter(Boolean))],
          watch_type: state.watchType || "VIDEO",
          season: sheet.season || "",
          league: sheet.league || "",
          home: sheet.home?.name || "",
          away: sheet.away?.name || "",
          date: sheet.date || "",
          kickoff_utc: sheet.kickoff_utc || null,
          watched_players: selectedPlayers(),
        }),
      });
      const assignment = data.assignment || {
        staff: [state.staff],
        watch_type: state.watchType,
        watched_players: selectedPlayers(),
      };
      sheet.assignment = assignment;
      const listRow = games().find((row) => row.fixture_id === sheet.fixture_id);
      if (listRow) listRow.assignment = assignment;
      if (data.email?.sent) {
        setStatus(`Assigned · email sent to ${data.email.to}`, "is-ok");
      } else if (data.email && !data.email.sent) {
        setStatus(`Assigned · email not sent: ${data.email.reason || "no email"}`, "is-ok");
      } else {
        setStatus("Assigned to Fixture Planner.", "is-ok");
      }
      renderList();
      renderKpis();
      renderSheet();
    } catch (error) {
      setStatus(error.message || "Could not assign", "is-error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function openFixture(fixtureId) {
    if (!fixtureId) return;
    state.openId = fixtureId;
    window.location.hash = encodeURIComponent(fixtureId);
    renderList();
    els.sheetEmpty.classList.add("hidden");
    els.sheetBody.classList.remove("hidden");
    els.sheetBody.innerHTML = `<p class="gw-assign__note" style="padding:1rem">Loading team sheet…</p>`;
    state.loadingSheet = true;
    try {
      const sheet = await fetchJson(`/api/games-to-watch/fixture?fixture_id=${encodeURIComponent(fixtureId)}`);
      state.sheet = sheet;
      state.watchType = sheet.assignment?.watch_type || "VIDEO";
      state.staff = (sheet.assignment?.staff || [])[0] || state.staff || "";
      state.picked = new Set((sheet.assignment?.watched_players || []).map((row) => String(row.player_id || "")).filter(Boolean));
      renderSheet();
    } catch (error) {
      setStatus(error.message || "Could not load team sheet", "is-error");
      els.sheetBody.innerHTML = `<p class="gw-assign__note" style="padding:1rem">${escapeHtml(error.message || "Could not load team sheet.")}</p>`;
    } finally {
      state.loadingSheet = false;
    }
  }

  function render() {
    renderLeagues();
    paintChipGroup(els.window, "window");
    paintChipGroup(els.phase, "phase");
    paintChipGroup(els.coverage, "coverage");
    paintChipGroup(els.look, "look");
    applyLookCopy();
    renderKpis();
    renderList();
  }

  async function loadGamesList() {
    const payload = await fetchJson("/api/games-to-watch");
    state.payload = payload;
    if (payload.building && !(payload.games || []).length) {
      setStatus("Building the fixture list…");
      window.setTimeout(() => {
        loadGamesList()
          .then(render)
          .catch((error) => setStatus(error.message || "Could not load games", "is-error"));
      }, 2500);
    } else if (payload.building) {
      setStatus("Profile scores are still building — rankings will fill in. You can still open games and assign.", "");
    } else {
      setStatus("");
    }
    render();
    return payload;
  }

  async function boot() {
    bindChipGroup(els.window, "window");
    bindChipGroup(els.phase, "phase");
    bindChipGroup(els.coverage, "coverage");
    bindChipGroup(els.look, "look");
    setStatus("Ranking played and upcoming fixtures…");
    try {
      await loadGamesList();
      const hash = decodeURIComponent((window.location.hash || "").replace(/^#/, ""));
      if (hash) openFixture(hash);
    } catch (error) {
      setStatus(error.message || "Could not load games", "is-error");
    }
  }

  els.search?.addEventListener("input", () => {
    state.query = els.search.value || "";
    renderList();
    renderKpis();
  });

  boot();
})();
