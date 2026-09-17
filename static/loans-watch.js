(() => {
  const els = {
    status: document.getElementById("lwStatus"),
    sub: document.getElementById("lwSub"),
    kpis: document.getElementById("lwKpis"),
    leagues: document.getElementById("lwLeagues"),
    positions: document.getElementById("lwPositions"),
    view: document.getElementById("lwView"),
    usage: document.getElementById("lwUsage"),
    age: document.getElementById("lwAge"),
    sort: document.getElementById("lwSort"),
    sortDir: document.getElementById("lwSortDir"),
    search: document.getElementById("lwSearch"),
    board: document.getElementById("lwBoard"),
    listCount: document.getElementById("lwListCount"),
    listTitle: document.getElementById("lwListTitle"),
  };

  const state = {
    payload: null,
    league: "league-two",
    position: "all",
    view: "club",
    usage: "all",
    age: "all",
    sort: "score",
    sortDir: "desc",
    query: "",
  };

  const SORT_COLS = {
    player: { label: "Player", type: "text", value: (row) => row.player, defaultDir: "asc" },
    club: { label: "Club", type: "text", value: (row) => row.club, defaultDir: "asc" },
    from: { label: "From", type: "text", value: (row) => row.from_club, defaultDir: "asc" },
    age: { label: "Age", type: "num", value: (row) => row.age, defaultDir: "asc" },
    starts: { label: "Starts", type: "num", value: (row) => row.starts, defaultDir: "desc" },
    matches: { label: "Matches", type: "num", value: (row) => row.matches, defaultDir: "desc" },
    minutes: { label: "Minutes", type: "num", value: (row) => row.minutes, defaultDir: "desc" },
    score: { label: "Score", type: "num", value: (row) => row.overall, defaultDir: "desc" },
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
    els.status.classList.remove("hidden", "is-error");
    if (kind) els.status.classList.add(kind);
    els.status.textContent = message;
  }

  async function fetchJson(url) {
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || data.message || `Request failed (${response.status})`);
    }
    return data;
  }

  function scoreClass(score) {
    if (score == null) return "is-none";
    if (score >= 70) return "is-hot";
    if (score >= 50) return "is-ok";
    return "is-low";
  }

  function formatNum(value, estimated) {
    if (value == null || value === "") return "—";
    const text = Number(value).toLocaleString("en-GB");
    return estimated ? `~${text}` : text;
  }

  function formatMinutes(value) {
    if (value == null || value === "") return "—";
    return `${Number(value).toLocaleString("en-GB")}′`;
  }

  function formatScore(value) {
    if (value == null || value === "") return "—";
    return Number(value).toFixed(Number(value) % 1 ? 1 : 0);
  }

  function matchesFilters(row) {
    if (state.league !== "all" && row.league_id !== state.league) return false;
    if (state.position === "none") {
      if (row.position_group) return false;
    } else if (state.position !== "all" && row.position_group !== state.position) {
      return false;
    }
    if (state.usage !== "all" && row.usage !== state.usage) return false;
    if (state.age === "u21" && !row.u21) return false;
    if (state.age === "u23" && !row.u23) return false;
    if (state.age === "u25" && !row.u25) return false;
    const q = state.query.trim().toLowerCase();
    if (!q) return true;
    const hay = [row.player, row.club, row.from_club, row.position, row.position_group]
      .map((part) => String(part || "").toLowerCase())
      .join(" ");
    return hay.includes(q);
  }

  function sortRows(rows) {
    const col = SORT_COLS[state.sort] || SORT_COLS.score;
    const dir = state.sortDir === "asc" ? 1 : -1;
    const copy = rows.slice();
    copy.sort((a, b) => {
      const av = col.value(a);
      const bv = col.value(b);
      let cmp = 0;
      if (col.type === "text") {
        const aText = String(av || "").trim();
        const bText = String(bv || "").trim();
        if (!aText && !bText) cmp = 0;
        else if (!aText) return 1;
        else if (!bText) return -1;
        else cmp = aText.localeCompare(bText, "en-GB", { sensitivity: "base" });
      } else {
        const aMiss = av == null || av === "";
        const bMiss = bv == null || bv === "";
        if (aMiss && bMiss) cmp = 0;
        else if (aMiss) return 1;
        else if (bMiss) return -1;
        else cmp = Number(av) - Number(bv);
      }
      if (cmp) return cmp * dir;
      return String(a.player || "").localeCompare(String(b.player || ""), "en-GB", { sensitivity: "base" });
    });
    return copy;
  }

  function setSort(key, { toggle = true, dir } = {}) {
    const col = SORT_COLS[key];
    if (!col) return;
    if (dir === "asc" || dir === "desc") {
      state.sort = key;
      state.sortDir = dir;
    } else if (toggle && state.sort === key) {
      state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    } else {
      state.sort = key;
      state.sortDir = col.defaultDir;
    }
    render();
  }

  function sortHeader(key) {
    const col = SORT_COLS[key];
    if (!col) return "";
    const active = state.sort === key;
    const dirClass = active ? (state.sortDir === "asc" ? " is-asc" : " is-desc") : "";
    const aria = active ? (state.sortDir === "asc" ? "ascending" : "descending") : "none";
    const next = !active ? col.defaultDir : state.sortDir === "asc" ? "desc" : "asc";
    const title = active
      ? `${col.label}: ${state.sortDir === "asc" ? "low to high" : "high to low"}. Click for ${next === "asc" ? "low to high" : "high to low"}.`
      : `Sort by ${col.label}`;
    return `<button type="button" class="lw-col${col.type === "num" ? " is-num" : ""}${active ? " is-active" : ""}${dirClass}" data-sort="${key}" aria-sort="${aria}" title="${escapeHtml(title)}">${escapeHtml(col.label)}</button>`;
  }

  function filteredLoans() {
    const rows = (state.payload?.loans || []).filter(matchesFilters);
    return sortRows(rows);
  }

  function playerCell(row, { hideClub = false } = {}) {
    const name = escapeHtml(row.player || "—");
    const meta = (hideClub ? [row.position] : [row.club, row.position])
      .filter(Boolean)
      .map(escapeHtml)
      .join(" · ");
    const inner = row.dossier_href
      ? `<a href="${escapeHtml(row.dossier_href)}">${name}</a>`
      : `<strong>${name}</strong>`;
    return `<span class="lw-player">${inner}${meta ? `<em>${meta}</em>` : ""}</span>`;
  }

  function statsCells(row) {
    return `
      <span class="lw-age">${row.age == null ? "—" : escapeHtml(row.age)}</span>
      <span class="lw-num${row.starts_estimated ? " is-est" : ""}">${formatNum(row.starts, row.starts_estimated)}</span>
      <span class="lw-num${row.matches_estimated ? " is-est" : ""}">${formatNum(row.matches, row.matches_estimated)}</span>
      <span class="lw-num">${formatMinutes(row.minutes)}</span>
      <span class="lw-score ${scoreClass(row.overall)}">${formatScore(row.overall)}</span>
    `;
  }

  function rowClass(row) {
    const bits = ["lw-row"];
    if (row.usage === "unused") bits.push("is-unused");
    if (String(row.club || "").toLowerCase().includes("port vale")) bits.push("is-vale");
    return bits.join(" ");
  }

  function renderKpis() {
    const totals = state.payload?.totals || {};
    const shown = filteredLoans();
    els.kpis.innerHTML = [
      ["Loans", totals.loans ?? "—"],
      ["Showing", shown.length],
      ["Regulars", totals.regular ?? "—"],
      ["U23", totals.u23 ?? "—"],
      ["With score", totals.scored ?? "—"],
    ]
      .map(([label, value]) => `<article class="lw-kpi"><span>${label}</span><strong>${escapeHtml(value)}</strong></article>`)
      .join("");
  }

  function renderLeagues() {
    const leagues = state.payload?.leagues || [];
    const chips = [`<button type="button" class="lw-chip${state.league === "all" ? " is-active" : ""}" data-league="all">All</button>`];
    for (const league of leagues) {
      const count = league.loan_count || 0;
      chips.push(
        `<button type="button" class="lw-chip${state.league === league.id ? " is-active" : ""}" data-league="${escapeHtml(league.id)}">${escapeHtml(league.name)} · ${count}</button>`
      );
    }
    els.leagues.innerHTML = chips.join("");
    els.leagues.querySelectorAll("[data-league]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.league = btn.dataset.league || "all";
        render();
      });
    });
  }

  function renderClubBoard(rows) {
    const byLeague = new Map();
    for (const league of state.payload?.leagues || []) {
      if (state.league !== "all" && league.id !== state.league) continue;
      byLeague.set(league.id, {
        id: league.id,
        name: league.name,
        color: league.color,
        teams: [],
      });
    }
    const teams = new Map();
    for (const row of rows) {
      const league = byLeague.get(row.league_id);
      if (!league) continue;
      const key = `${row.league_id}:${row.team_id || row.club}`;
      if (!teams.has(key)) {
        const team = {
          id: row.team_id,
          name: row.club,
          badge_url: row.badge_url,
          loans: [],
        };
        teams.set(key, team);
        league.teams.push(team);
      }
      teams.get(key).loans.push(row);
    }
    const html = [];
    for (const league of byLeague.values()) {
      const visible = league.teams.filter((team) => team.loans.length);
      if (!visible.length) continue;
      const count = visible.reduce((sum, team) => sum + team.loans.length, 0);
      html.push(`<section class="lw-league" style="--league:${escapeHtml(league.color || "#f59e0b")}">
        <header class="lw-league__head">
          <h3>${escapeHtml(league.name)}</h3>
          <span class="lw-league__count">${count} loans</span>
        </header>
        <div class="lw-table">
          <div class="lw-table__head">
            ${sortHeader("player")}
            ${sortHeader("from")}
            ${sortHeader("age")}
            ${sortHeader("starts")}
            ${sortHeader("matches")}
            ${sortHeader("minutes")}
            ${sortHeader("score")}
          </div>
          ${visible
            .map((team) => {
              const badge = team.badge_url
                ? `<img src="${escapeHtml(team.badge_url)}" alt="" />`
                : `<span class="lw-team__fallback">${escapeHtml((team.name || "?").slice(0, 1))}</span>`;
              const loans = sortRows(team.loans)
                .map((row) => `<div class="${rowClass(row)}">
                  ${playerCell(row)}
                  <span class="lw-from" title="${escapeHtml(row.from_club || "")}">${escapeHtml(row.from_club || "—")}</span>
                  ${statsCells(row)}
                </div>`)
                .join("");
              return `<div class="lw-team">${badge}<span>${escapeHtml(team.name)}</span><span class="lw-team__count">${team.loans.length}</span></div>${loans}`;
            })
            .join("")}
        </div>
      </section>`);
    }
    els.board.innerHTML = html.join("") || `<p class="lw-empty">No loanees match those filters.</p>`;
  }

  function renderRanked(rows) {
    if (!rows.length) {
      els.board.innerHTML = `<p class="lw-empty">No loanees match those filters.</p>`;
      return;
    }
    els.board.innerHTML = `<div class="lw-table lw-ranked">
      <div class="lw-table__head">
        ${sortHeader("player")}
        ${sortHeader("club")}
        ${sortHeader("from")}
        ${sortHeader("age")}
        ${sortHeader("starts")}
        ${sortHeader("matches")}
        ${sortHeader("minutes")}
        ${sortHeader("score")}
      </div>
      ${rows
        .map((row) => `<div class="${rowClass(row)}">
          ${playerCell(row, { hideClub: true })}
          <span class="lw-from">${escapeHtml(row.club || "—")}</span>
          <span class="lw-from" title="${escapeHtml(row.from_club || "")}">${escapeHtml(row.from_club || "—")}</span>
          ${statsCells(row)}
        </div>`)
        .join("")}
    </div>`;
  }

  function render() {
    if (!state.payload) return;
    renderLeagues();
    const rows = filteredLoans();
    const col = SORT_COLS[state.sort] || SORT_COLS.score;
    const arrow = state.sortDir === "asc" ? "↑" : "↓";
    const sortLabel = col.label.toLowerCase();
    els.listTitle.textContent = state.view === "ranked"
      ? `Ranked by ${sortLabel} ${arrow}`
      : `By club · ${sortLabel} ${arrow}`;
    els.listCount.textContent = `${rows.length} loanee${rows.length === 1 ? "" : "s"}`;
    renderKpis();
    renderSortControls();
    if (state.view === "ranked") renderRanked(rows);
    else renderClubBoard(rows);
    bindHeaderSort();
  }

  function renderSortControls() {
    els.sort?.querySelectorAll("[data-sort]").forEach((btn) => {
      const key = btn.dataset.sort;
      const active = key === state.sort;
      btn.classList.toggle("is-active", active);
      const base = btn.dataset.label || btn.textContent.replace(/\s+[↑↓]$/, "").trim();
      btn.dataset.label = base;
      btn.textContent = active ? `${base} ${state.sortDir === "asc" ? "↑" : "↓"}` : base;
    });
    els.sortDir?.querySelectorAll("[data-dir]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.dir === state.sortDir);
    });
  }

  function bindHeaderSort() {
    els.board?.querySelectorAll(".lw-table__head [data-sort]").forEach((btn) => {
      btn.addEventListener("click", () => setSort(btn.dataset.sort));
    });
  }

  function bindChips(root, key, attr) {
    root?.querySelectorAll(`[data-${attr}]`).forEach((btn) => {
      btn.addEventListener("click", () => {
        state[key] = btn.dataset[attr];
        root.querySelectorAll(".lw-chip").forEach((chip) => chip.classList.toggle("is-active", chip === btn));
        render();
      });
    });
  }

  async function boot() {
    bindChips(els.positions, "position", "position");
    bindChips(els.view, "view", "view");
    bindChips(els.usage, "usage", "usage");
    bindChips(els.age, "age", "age");
    els.sort?.querySelectorAll("[data-sort]").forEach((btn) => {
      btn.addEventListener("click", () => setSort(btn.dataset.sort));
    });
    els.sortDir?.querySelectorAll("[data-dir]").forEach((btn) => {
      btn.addEventListener("click", () => setSort(state.sort, { toggle: false, dir: btn.dataset.dir }));
    });
    els.search?.addEventListener("input", () => {
      state.query = els.search.value || "";
      render();
    });
    setStatus("Loading every club’s loans…");
    try {
      state.payload = await fetchJson("/api/loans-watch");
      const updated = state.payload.updated ? ` Snapshot ${state.payload.updated}.` : "";
      if (els.sub) {
        els.sub.textContent = state.payload?.scoring?.note
          ? `${state.payload.scoring.note}${updated}`
          : els.sub.textContent;
      }
      setStatus("");
      render();
    } catch (err) {
      setStatus(err.message || "Could not load Loans Watch.", "is-error");
    }
  }

  boot();
})();
