(function initTransferCentre() {
  const VIEW_KEY = "pv-transfer-centre-view";
  const LEAGUE_KEY = "pv-transfer-centre-league";
  const LEAGUE_COLORS = {
    "league-one": "#3d8bfd",
    "league-two": "#22c55e",
    "national-league": "#a78bfa",
    "scottish-prem": "#f59e0b",
  };

  const els = {
    sub: document.getElementById("tcSub"),
    status: document.getElementById("tcStatus"),
    filter: document.getElementById("tcFilter"),
    kpis: document.getElementById("tcKpis"),
    filters: document.getElementById("tcFilters"),
    board: document.getElementById("tcBoard"),
    boardView: document.getElementById("tcBoardView"),
    reportsView: document.getElementById("tcReportsView"),
    reports: document.getElementById("tcReports"),
    viewBoard: document.getElementById("tcViewBoard"),
    viewReports: document.getElementById("tcViewReports"),
    drawer: document.getElementById("tcDrawer"),
    drawerClub: document.getElementById("tcDrawerClub"),
    drawerName: document.getElementById("tcDrawerName"),
    drawerMeta: document.getElementById("tcDrawerMeta"),
    drawerNotes: document.getElementById("tcDrawerNotes"),
    noteForm: document.getElementById("tcNoteForm"),
    noteText: document.getElementById("tcNoteText"),
  };

  const state = {
    view: (new URLSearchParams(location.search).get("tab") === "reports" || localStorage.getItem(VIEW_KEY) === "reports") ? "reports" : "board",
    leagueId: localStorage.getItem(LEAGUE_KEY) === null ? "league-two" : localStorage.getItem(LEAGUE_KEY),
    flagFilter: "",
    interestFilter: "",
    query: "",
    flags: [],
    interestOptions: [],
    positions: [],
    leagues: [],
    reports: [],
    totals: {},
    window: "",
    updated: "",
    catalog: {},
    saving: new Set(),
    openId: "",
    refreshTimer: 0,
  };

  const timers = {};

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(message, isError) {
    if (!message) {
      els.status.classList.add("hidden");
      els.status.textContent = "";
      return;
    }
    els.status.classList.remove("hidden");
    els.status.classList.toggle("is-error", Boolean(isError));
    els.status.textContent = message;
  }

  async function fetchJson(url, options) {
    const res = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
    return data;
  }

  function allPlayers() {
    const rows = [];
    state.leagues.forEach((league) => {
      (league.teams || []).forEach((team) => {
        (team.incomings || []).forEach((player) => {
          rows.push({ league, team, player });
        });
      });
    });
    return rows;
  }

  function matchesQuery(league, team, player) {
    const q = state.query.trim().toLowerCase();
    if (!q) return true;
    const notes = (player.notes || []).map((note) => note.text).join(" ");
    const interest = (state.interestOptions || []).find((row) => row.id === player.interest)?.label || player.interest;
    return [player.player, player.source_name, player.from_club, player.position, interest, team.name, league.name, notes]
      .join(" ")
      .toLowerCase()
      .includes(q);
  }

  function visibleLeagues() {
    return state.leagues
      .filter((league) => !state.leagueId || league.id === state.leagueId)
      .map((league) => {
        const teams = (league.teams || [])
          .map((team) => {
            const incomings = (team.incomings || []).filter((player) => {
              if (!matchesQuery(league, team, player)) return false;
              if (state.flagFilter && !player.flags?.[state.flagFilter]) return false;
              if (state.interestFilter === "out" && !player.is_out) return false;
              if (state.interestFilter === "open" && player.interest) return false;
              if (state.interestFilter && !["out", "open"].includes(state.interestFilter) && player.interest !== state.interestFilter) return false;
              return true;
            });
            return { ...team, incomings };
          })
          .filter((team) => team.incomings.length || (!state.query && !state.flagFilter && !state.interestFilter));
        return { ...league, teams };
      })
      .filter((league) => league.teams.length);
  }

  function setView(view) {
    state.view = view === "reports" ? "reports" : "board";
    localStorage.setItem(VIEW_KEY, state.view);
    els.viewBoard.classList.toggle("is-active", state.view === "board");
    els.viewReports.classList.toggle("is-active", state.view === "reports");
    els.boardView.classList.toggle("hidden", state.view !== "board");
    els.reportsView.classList.toggle("hidden", state.view !== "reports");
    els.filter.closest(".tc-search")?.classList.toggle("hidden", state.view !== "board");
  }

  function renderKpis() {
    const scoped = allPlayers().filter(({ league }) => !state.leagueId || league.id === state.leagueId);
    const count = (flagId) => scoped.filter(({ player }) => player.flags?.[flagId]).length;
    const interestCount = (id) => scoped.filter(({ player }) => player.interest === id).length;
    const cards = [
      { label: "Incomings", value: scoped.length, color: "#38bdf8" },
      { label: "Interested", value: interestCount("interested"), color: "#22c55e" },
      { label: "Not interested", value: interestCount("not_interested"), color: "#f97316" },
      { label: "Unrealistic", value: interestCount("unrealistic"), color: "#ef4444" },
      { label: "Left us", value: interestCount("released_by_us"), color: "#94a3b8" },
      { label: "Manager liked", value: count("manager_liked"), color: "#22c55e" },
      { label: "Rec team liked", value: count("recruitment_liked"), color: "#3d8bfd" },
    ];
    els.kpis.innerHTML = cards
      .map(
        (card) => `<article class="tc-kpi" style="--kpi:${esc(card.color)}">
          <p class="tc-kpi__label">${esc(card.label)}</p>
          <p class="tc-kpi__value">${esc(card.value)}</p>
        </article>`
      )
      .join("");
  }

  function renderFilters() {
    const leagueChips = [
      { id: "", label: "All leagues", color: "#38bdf8" },
      ...state.leagues.map((league) => ({
        id: league.id,
        label: league.name,
        color: LEAGUE_COLORS[league.id] || "#38bdf8",
      })),
    ];
    const interestChips = [
      { id: "", label: "All interest", color: "#9ca3af" },
      { id: "interested", label: "Interested", color: "#22c55e" },
      { id: "out", label: "Not for us", color: "#ef4444" },
      { id: "open", label: "Still to mark", color: "#38bdf8" },
    ];
    const flagChips = [
      { id: "", label: "All flags", color: "#9ca3af" },
      ...state.flags.map((flag) => ({ id: flag.id, label: flag.label, color: flag.color })),
    ];
    els.filters.innerHTML = `
      ${leagueChips
        .map(
          (chip) => `<button type="button" class="tc-chip${chip.id === state.leagueId ? " is-active" : ""}" data-league="${esc(chip.id)}" style="--chip:${esc(chip.color)}">${esc(chip.label)}</button>`
        )
        .join("")}
      <span class="tc-chip-split"></span>
      ${interestChips
        .map(
          (chip) => `<button type="button" class="tc-chip${chip.id === state.interestFilter ? " is-active" : ""}" data-interest="${esc(chip.id)}" style="--chip:${esc(chip.color)}">${esc(chip.label)}</button>`
        )
        .join("")}
      <span class="tc-chip-split"></span>
      ${flagChips
        .map(
          (chip) => `<button type="button" class="tc-chip${chip.id === state.flagFilter ? " is-active" : ""}" data-flag="${esc(chip.id)}" style="--chip:${esc(chip.color)}">${esc(chip.label)}</button>`
        )
        .join("")}
    `;
    els.filters.querySelectorAll("[data-league]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.leagueId = btn.dataset.league || "";
        localStorage.setItem(LEAGUE_KEY, state.leagueId);
        render();
      });
    });
    els.filters.querySelectorAll("[data-interest]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.interestFilter = btn.dataset.interest || "";
        render();
      });
    });
    els.filters.querySelectorAll("[data-flag]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.flagFilter = btn.dataset.flag || "";
        render();
      });
    });
  }

  function positionSelect(player) {
    const options = [""].concat(state.positions);
    const current = player.position || "";
    const extra = current && !options.includes(current) ? `<option value="${esc(current)}" selected>${esc(current)}</option>` : "";
    const title = player.position_source === "api"
      ? "Filled automatically — edit if this is wrong"
      : player.position_source === "staff"
        ? "Your edit"
        : "";
    return `<select class="tc-select" data-field="position" data-id="${esc(player.id)}" aria-label="Position" title="${esc(title)}">
      ${options
        .map((code) => {
          const label = code || "—";
          const selected = code === current ? " selected" : "";
          return `<option value="${esc(code)}"${selected}>${esc(label)}</option>`;
        })
        .join("")}
      ${extra}
    </select>`;
  }

  function interestTone(player) {
    const current = player?.interest || "";
    // One of ours who left reads differently from one we turned down. The row
    // is closed either way, but that was never a decision about a target, so
    // it should not sit on the board wearing the same red.
    if (current === "released_by_us") return " is-ours";
    if (current === "interested") return " is-interested";
    return player?.is_out ? " is-out" : "";
  }

  function isOutInterest(id) {
    // The server decides which marks take a player off the live list, so this
    // does not have to be kept in step with it by hand.
    return (state.interestOptions || []).some((row) => row.id === id && row.out);
  }

  function interestSelect(player) {
    const current = player.interest || "";
    const tone = interestTone(player);
    return `<select class="tc-select tc-interest${tone}" data-field="interest" data-id="${esc(player.id)}" aria-label="Interest">
      <option value=""${current ? "" : " selected"}>—</option>
      ${(state.interestOptions || [])
        .map((option) => `<option value="${esc(option.id)}"${option.id === current ? " selected" : ""}>${esc(option.label)}</option>`)
        .join("")}
    </select>`;
  }

  function renderBoard() {
    const leagues = visibleLeagues();
    if (!leagues.length) {
      els.board.innerHTML = `<div class="tc-board-empty">No incomings match these filters.</div>`;
      return;
    }
    els.board.innerHTML = leagues
      .map((league) => {
        const color = LEAGUE_COLORS[league.id] || "#38bdf8";
        const incoming = league.teams.reduce((sum, team) => sum + team.incomings.length, 0);
        const flagHeads = state.flags
          .map((flag) => `<span title="${esc(flag.label)}">${esc(flag.short)}</span>`)
          .join("");
        return `<section class="tc-league" style="--league:${esc(color)}">
          <header class="tc-league__head">
            <h2>${esc(league.name)}</h2>
            <span class="tc-league__count">${incoming} in</span>
          </header>
          <div class="tc-table">
            <div class="tc-table__head">
              <span>Player</span>
              <span>Position</span>
              <span>Age</span>
              <span>Interest</span>
              ${flagHeads}
              <span>Notes</span>
            </div>
            ${league.teams
              .map((team) => {
                const badge = team.badge_url
                  ? `<img src="${esc(team.badge_url)}" alt="" />`
                  : `<span class="tc-team__fallback">${esc((team.name || "?").slice(0, 1))}</span>`;
                const rows = team.incomings.length
                  ? team.incomings
                      .map((player) => {
                        const from = [player.from_club, player.fee].filter(Boolean).join(" · ");
                        const noteCount = (player.notes || []).length;
                        const checks = state.flags
                          .map((flag) => {
                            const on = Boolean(player.flags?.[flag.id]);
                            return `<span class="tc-flag"><button type="button" class="tc-check${on ? " is-on" : ""}" data-id="${esc(player.id)}" data-flag="${esc(flag.id)}" style="--flag:${esc(flag.color)}" aria-pressed="${on}" title="${esc(flag.label)}" aria-label="${esc(flag.label)}: ${on ? "Yes" : "No"}">${on ? "Yes" : "No"}</button></span>`;
                          })
                          .join("");
                        const nameTitle = player.name_source === "impect"
                          ? "Filled automatically — edit if this is wrong"
                          : player.name_source === "staff"
                            ? "Your edit"
                            : "";
                        return `<div class="tc-row${player.is_out ? " is-out" : ""}${player.interest === "released_by_us" ? " is-ours" : ""}" data-row="${esc(player.id)}">
                          <span class="tc-player">
                            <input class="tc-name" data-field="name" data-id="${esc(player.id)}" value="${esc(player.player)}" aria-label="Player name" title="${esc(nameTitle)}" />
                            <em>${esc(from || "Incoming")}</em>
                          </span>
                          ${positionSelect(player)}
                          <input class="tc-age" data-field="age" data-id="${esc(player.id)}" type="number" min="15" max="50" inputmode="numeric" value="${player.age != null ? esc(player.age) : ""}" aria-label="Age" />
                          ${interestSelect(player)}
                          ${checks}
                          <button type="button" class="tc-notes-btn${noteCount ? " has-notes" : ""}" data-notes="${esc(player.id)}">${noteCount ? `Notes · ${noteCount}` : "Notes"}</button>
                        </div>`;
                      })
                      .join("")
                  : `<div class="tc-empty-row">No incomings listed yet.</div>`;
                return `<div class="tc-team">${badge}<span>${esc(team.name)}</span><span class="tc-team__count">${team.incomings.length}</span></div>${rows}`;
              })
              .join("")}
          </div>
        </section>`;
      })
      .join("");

    els.board.querySelectorAll(".tc-check").forEach((btn) => {
      btn.addEventListener("click", () => toggleFlag(btn));
    });
    els.board.querySelectorAll("input[data-field='name']").forEach((input) => {
      input.addEventListener("change", () => {
        const raw = input.value.trim();
        if (!raw) {
          patchPlayer(input.dataset.id, { clear_name: true });
          return;
        }
        patchPlayer(input.dataset.id, { name: raw });
      });
    });
    els.board.querySelectorAll("select[data-field='position']").forEach((input) => {
      input.addEventListener("change", () => {
        if (!input.value) {
          patchPlayer(input.dataset.id, { clear_position: true });
          return;
        }
        patchPlayer(input.dataset.id, { position: input.value });
      });
    });
    els.board.querySelectorAll("input[data-field='age']").forEach((input) => {
      input.addEventListener("change", () => {
        const raw = input.value.trim();
        if (!raw) {
          patchPlayer(input.dataset.id, { clear_age: true });
          return;
        }
        const age = Number(raw);
        if (!Number.isFinite(age)) return;
        patchPlayer(input.dataset.id, { age });
      });
    });
    els.board.querySelectorAll("select[data-field='interest']").forEach((input) => {
      input.addEventListener("change", () => {
        const found = findPlayer(input.dataset.id);
        if (found) {
          found.player.interest = input.value;
          found.player.is_out = isOutInterest(input.value);
        }
        if (!input.value) {
          patchPlayer(input.dataset.id, { clear_interest: true });
        } else {
          patchPlayer(input.dataset.id, { interest: input.value });
        }
        if (state.interestFilter) renderBoard();
        else paintInterestRow(input.dataset.id, found?.player);
        renderKpis();
      });
    });
    els.board.querySelectorAll("[data-notes]").forEach((btn) => {
      btn.addEventListener("click", () => openDrawer(btn.dataset.notes));
    });
  }

  function formatWhen(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function renderDrawerNotes(player) {
    const notes = player.notes || [];
    if (!notes.length) {
      els.drawerNotes.innerHTML = `<p class="tc-notes-empty">No notes yet. Add the first one for the team.</p>`;
      return;
    }
    els.drawerNotes.innerHTML = notes
      .map(
        (note) => `<article class="tc-note">
          <p>${esc(note.text)}</p>
          <small>${esc(note.author || "Staff")}${note.created_at ? ` · ${esc(formatWhen(note.created_at))}` : ""}</small>
        </article>`
      )
      .join("");
    els.drawerNotes.scrollTop = els.drawerNotes.scrollHeight;
  }

  function openDrawer(playerId) {
    const found = findPlayer(playerId);
    if (!found) return;
    state.openId = playerId;
    els.drawerClub.textContent = found.team.name;
    els.drawerName.textContent = found.player.player;
    els.drawerMeta.textContent = [found.player.from_club, found.player.fee, found.player.position, found.player.age]
      .filter((bit) => bit !== "" && bit != null)
      .join(" · ");
    renderDrawerNotes(found.player);
    els.drawer.hidden = false;
    els.noteText.value = "";
    els.noteText.focus();
  }

  function closeDrawer() {
    state.openId = "";
    els.drawer.hidden = true;
  }

  function renderReports() {
    els.reports.innerHTML = (state.reports || [])
      .map(
        (report) => `<a class="tc-report" href="${esc(report.href)}">
          <span class="tc-report__icon">${esc(report.icon || "🔁")}</span>
          <span>
            <span class="tc-report__title">${esc(report.title)}</span>
            <span class="tc-report__desc">${esc(report.description || "")}</span>
            <span class="tc-report__meta">${esc(report.meta || report.window || "")}${report.updated ? ` · updated ${esc(report.updated)}` : ""}</span>
          </span>
          <span class="tc-report__go">Open</span>
        </a>`
      )
      .join("");
  }

  function findPlayer(playerId) {
    return allPlayers().find((row) => row.player.id === playerId) || null;
  }

  async function patchPlayer(playerId, body) {
    const found = findPlayer(playerId);
    if (!found) return;
    const key = `${playerId}:${JSON.stringify(body)}`;
    if (timers[playerId]) clearTimeout(timers[playerId]);
    timers[playerId] = setTimeout(async () => {
      try {
        state.saving.add(key);
        const data = await fetchJson(`/api/transfer-centre/players/${encodeURIComponent(playerId)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        const saved = data.player || {};
        Object.assign(found.player, saved);
        const nameInput = els.board.querySelector(`input[data-field='name'][data-id="${CSS.escape(playerId)}"]`);
        if (nameInput && saved.player) nameInput.value = saved.player;
        const posInput = els.board.querySelector(`select[data-field='position'][data-id="${CSS.escape(playerId)}"]`);
        if (posInput && "position" in saved) posInput.value = saved.position || "";
        const ageInput = els.board.querySelector(`input[data-field='age'][data-id="${CSS.escape(playerId)}"]`);
        if (ageInput && "age" in saved) ageInput.value = saved.age != null ? saved.age : "";
        const interestInput = els.board.querySelector(`select[data-field='interest'][data-id="${CSS.escape(playerId)}"]`);
        if (interestInput && "interest" in saved) interestInput.value = saved.interest || "";
        paintInterestRow(playerId, found.player);
        setStatus("");
        renderKpis();
      } catch (err) {
        setStatus(err.message || "Could not save.", true);
      } finally {
        state.saving.delete(key);
      }
    }, body.flags ? 0 : 180);
  }

  function toggleFlag(btn) {
    const playerId = btn.dataset.id;
    const flagId = btn.dataset.flag;
    const found = findPlayer(playerId);
    if (!found || !flagId) return;
    const next = !found.player.flags[flagId];
    found.player.flags[flagId] = next;
    btn.classList.toggle("is-on", next);
    btn.setAttribute("aria-pressed", String(next));
    btn.setAttribute("aria-label", `${btn.title || "Flag"}: ${next ? "Yes" : "No"}`);
    btn.textContent = next ? "Yes" : "No";
    if (state.flagFilter) renderBoard();
    renderKpis();
    patchPlayer(playerId, { flags: { [flagId]: next } });
  }

  function render() {
    if (state.window) {
      els.sub.textContent = `${state.window} — incomings only, tracked club by club.`;
    }
    renderKpis();
    renderFilters();
    renderBoard();
    renderReports();
    setView(state.view);
  }

  els.viewBoard.addEventListener("click", () => setView("board"));
  els.viewReports.addEventListener("click", () => setView("reports"));
  els.filter.addEventListener("input", () => {
    state.query = els.filter.value;
    renderBoard();
  });
  els.drawer.querySelectorAll("[data-close-drawer]").forEach((btn) => {
    btn.addEventListener("click", closeDrawer);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.drawer.hidden) closeDrawer();
  });
  els.noteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const playerId = state.openId;
    const found = findPlayer(playerId);
    const text = els.noteText.value.trim();
    if (!found || !text) return;
    try {
      const data = await fetchJson(`/api/transfer-centre/players/${encodeURIComponent(playerId)}/notes`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (data.player?.notes) found.player.notes = data.player.notes;
      els.noteText.value = "";
      renderDrawerNotes(found.player);
      const btn = els.board.querySelector(`[data-notes="${CSS.escape(playerId)}"]`);
      if (btn) {
        const count = (found.player.notes || []).length;
        btn.textContent = count ? `Notes · ${count}` : "Notes";
        btn.classList.toggle("has-notes", Boolean(count));
      }
      setStatus("");
    } catch (err) {
      setStatus(err.message || "Could not save note.", true);
    }
  });
  setView(state.view);

  function paintInterestRow(playerId, player) {
    const row = els.board.querySelector(`[data-row="${CSS.escape(playerId)}"]`);
    const input = els.board.querySelector(`select[data-field='interest'][data-id="${CSS.escape(playerId)}"]`);
    const tone = interestTone(player).trim();
    if (row) {
      row.classList.toggle("is-out", Boolean(player?.is_out));
      row.classList.toggle("is-ours", tone === "is-ours");
    }
    if (input) {
      // Mutually exclusive, so a repaint cannot leave two tones fighting.
      ["is-out", "is-interested", "is-ours"].forEach((cls) => input.classList.toggle(cls, cls === tone));
    }
  }

  function applyBoard(data, { silent } = {}) {
    state.flags = data.flags || [];
    state.interestOptions = data.interest_options || [];
    state.positions = data.positions || [];
    state.leagues = data.leagues || [];
    state.reports = data.reports || [];
    state.totals = data.totals || {};
    state.window = data.window || "";
    state.updated = data.updated || "";
    state.catalog = data.catalog || {};
    if (state.leagueId && !state.leagues.some((league) => league.id === state.leagueId)) {
      state.leagueId = state.leagues[0]?.id || "";
    }
    render();
    if (!silent) setStatus("");
    if (state.catalog.positions_pending) schedulePositionRefresh();
  }

  function boardHasFocus() {
    return Boolean(els.board && els.board.contains(document.activeElement));
  }

  function schedulePositionRefresh() {
    if (state.refreshTimer) clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(() => {
      if (boardHasFocus() || state.saving.size) {
        schedulePositionRefresh();
        return;
      }
      fetchJson("/api/transfer-centre")
        .then((data) => applyBoard(data, { silent: true }))
        .catch(() => {});
    }, 12000);
  }

  fetchJson("/api/transfer-centre")
    .then((data) => applyBoard(data))
    .catch((err) => {
      setStatus(err.message || "Could not load Transfer Centre.", true);
    });
})();
