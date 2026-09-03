(function initPlayerPipelines() {
  const VIEW_KEY = "pv-pipelines-view";

  const els = {
    board: document.getElementById("ppBoard"),
    table: document.getElementById("ppTable"),
    status: document.getElementById("ppStatus"),
    search: document.getElementById("ppPlayerSearch"),
    results: document.getElementById("ppSearchResults"),
    filterName: document.getElementById("ppFilterName"),
    filterPosition: document.getElementById("ppFilterPosition"),
    filterTag: document.getElementById("ppFilterTag"),
    filterStaff: document.getElementById("ppFilterStaff"),
    count: document.getElementById("ppCount"),
    drawer: document.getElementById("ppDrawer"),
    drawerStage: document.getElementById("ppDrawerStage"),
    drawerName: document.getElementById("ppDrawerName"),
    drawerMeta: document.getElementById("ppDrawerMeta"),
    drawerDossier: document.getElementById("ppDrawerDossier"),
    drawerRemove: document.getElementById("ppDrawerRemove"),
    drawerPosition: document.getElementById("ppDrawerPosition"),
    drawerStatsBlock: document.getElementById("ppDrawerStatsBlock"),
    drawerStats: document.getElementById("ppDrawerStats"),
    drawerRefreshStats: document.getElementById("ppDrawerRefreshStats"),
    drawerTags: document.getElementById("ppDrawerTags"),
    drawerNotes: document.getElementById("ppDrawerNotes"),
    customTagForm: document.getElementById("ppCustomTagForm"),
    customTag: document.getElementById("ppCustomTag"),
    noteForm: document.getElementById("ppNoteForm"),
    noteText: document.getElementById("ppNoteText"),
    manualBtn: document.getElementById("ppManualBtn"),
    manualModal: document.getElementById("ppManualModal"),
    manualForm: document.getElementById("ppManualForm"),
    viewBoard: document.getElementById("ppViewBoard"),
    viewTable: document.getElementById("ppViewTable"),
  };

  const state = {
    stages: [],
    pipelineStageIds: [],
    positions: [],
    defaultTags: [],
    targets: [],
    openId: null,
    dragId: null,
    view: localStorage.getItem(VIEW_KEY) === "table" ? "table" : "board",
  };

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
      headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
    return data;
  }

  function initials(name) {
    return String(name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() || "")
      .join("");
  }

  function formatMinutes(value) {
    if (value == null || value === "") return "";
    return `${Number(value).toLocaleString()}′`;
  }

  function scoreTier(score) {
    if (score == null || Number.isNaN(Number(score))) return "";
    const value = Number(score);
    if (value >= 70) return "high";
    if (value >= 50) return "mid";
    return "low";
  }

  function scoreBadge(row, { compact = false } = {}) {
    if (row.overall_score == null || row.overall_score === "") return "";
    const tier = scoreTier(row.overall_score);
    const label = Math.round(Number(row.overall_score));
    const title = "League-relative data score (position percentiles)";
    if (compact) {
      return `<span class="pp-table__score pp-score--${tier}" title="${title}">${label}</span>`;
    }
    return `<span class="pp-score pp-score--${tier}" title="${title}">${label}</span>`;
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const mins = Math.max(1, Math.floor((Date.now() - then) / 60000));
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 48) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 60) return `${days}d ago`;
    const months = Math.floor(days / 30);
    return `${months}mo ago`;
  }

  function cardMeta(row) {
    return [
      row.position_label || row.position,
      row.club,
      row.age != null ? `${row.age}y` : "",
      formatMinutes(row.minutes),
      row.league,
    ]
      .filter(Boolean)
      .join(" · ");
  }

  function profileHighlight(row) {
    if (!row.top_profile || row.top_profile_score == null) return "";
    return `Strong: ${row.top_profile} (${Math.round(Number(row.top_profile_score))})`;
  }

  function stageMeta(id) {
    return state.stages.find((row) => row.id === id) || { id, title: id, color: "#3d8bfd" };
  }

  function stageTitle(id) {
    return stageMeta(id).title || id;
  }

  function stageColor(id) {
    return stageMeta(id).color || "#3d8bfd";
  }

  function filteredTargets() {
    const nameQ = els.filterName.value.trim().toLowerCase();
    const position = els.filterPosition.value;
    const tag = els.filterTag.value.toLowerCase();
    const staff = els.filterStaff.value.toLowerCase();
    return state.targets.filter((row) => {
      if (nameQ) {
        const hay = `${row.name} ${row.club}`.toLowerCase();
        if (!hay.includes(nameQ)) return false;
      }
      if (position && row.position !== position && row.position_label !== position) return false;
      if (tag && !(row.tags || []).some((item) => String(item).toLowerCase() === tag)) return false;
      if (staff && String(row.added_by || "").toLowerCase() !== staff) return false;
      return true;
    });
  }

  function fillFilters() {
    const posKeep = els.filterPosition.value;
    const posOptions =
      `<option value="">All positions</option>` +
      state.positions.map((row) => `<option value="${esc(row.id)}">${esc(row.label)}</option>`).join("");
    els.filterPosition.innerHTML = posOptions;
    els.filterPosition.value = posKeep;

    if (els.drawerPosition) {
      els.drawerPosition.innerHTML =
        `<option value="">—</option>` +
        state.positions.map((row) => `<option value="${esc(row.id)}">${esc(row.label)}</option>`).join("");
    }

    const manualPos = document.getElementById("ppManualPosition");
    if (manualPos) {
      manualPos.innerHTML =
        `<option value="">—</option>` +
        state.positions.map((row) => `<option value="${esc(row.id)}">${esc(row.label)}</option>`).join("");
    }

    const tags = new Set(state.defaultTags);
    state.targets.forEach((row) => (row.tags || []).forEach((t) => tags.add(t)));
    const tagKeep = els.filterTag.value;
    els.filterTag.innerHTML =
      `<option value="">All tags</option>` +
      [...tags]
        .sort((a, b) => a.localeCompare(b))
        .map((t) => `<option value="${esc(t)}">${esc(t)}</option>`)
        .join("");
    els.filterTag.value = tagKeep;

    const staff = [...new Set(state.targets.map((row) => row.added_by).filter(Boolean))].sort();
    const staffKeep = els.filterStaff.value;
    els.filterStaff.innerHTML =
      `<option value="">Everyone</option>` +
      staff.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
    els.filterStaff.value = staffKeep;
  }

  function setView(view) {
    state.view = view === "table" ? "table" : "board";
    localStorage.setItem(VIEW_KEY, state.view);
    els.viewBoard.classList.toggle("is-active", state.view === "board");
    els.viewTable.classList.toggle("is-active", state.view === "table");
    els.board.classList.toggle("hidden", state.view !== "board");
    els.table.classList.toggle("hidden", state.view !== "table");
    render();
  }

  function render() {
    const rows = filteredTargets();
    els.count.textContent = `${rows.length} of ${state.targets.length} players`;
    if (state.view === "table") renderTable(rows);
    else renderBoard(rows);
  }

  function photoBlock(row) {
    const url =
      row.photo_url ||
      `/api/pre-match/player-photo?name=${encodeURIComponent(row.name || "")}` +
        (row.club ? `&club=${encodeURIComponent(row.club)}` : "");
    return `<span class="pp-card__mug">
      <img class="pp-card__photo" alt="" src="${esc(url)}" />
      <span class="pp-card__fallback" hidden>${esc(initials(row.name))}</span>
    </span>`;
  }

  function statusPill(row) {
    const color = row.stage_color || stageColor(row.stage);
    return `<span class="pp-status-pill" style="--stage:${esc(color)}">${esc(stageTitle(row.stage))}</span>`;
  }

  function cardHtml(row) {
    const meta = cardMeta(row);
    const highlight = profileHighlight(row);
    const tags = (row.tags || [])
      .slice(0, 3)
      .map((tag) => `<span class="pp-chip">${esc(tag)}</span>`)
      .join("");
    const noteCount = (row.notes || []).length;
    const color = row.stage_color || stageColor(row.stage);
    const updated = timeAgo(row.moved_at || row.added_at);
    return `<article class="pp-card" draggable="true" data-id="${esc(row.id)}" style="--stage:${esc(color)}">
      ${photoBlock(row)}
      <div class="pp-card__body">
        <div class="pp-card__top">
          <p class="pp-card__name">${esc(row.name)}${row.manual ? ` <span class="pp-manual-badge">Manual</span>` : ""}</p>
          ${scoreBadge(row)}
        </div>
        <p class="pp-card__meta">${esc(meta)}</p>
        ${highlight ? `<p class="pp-card__highlight">${esc(highlight)}</p>` : ""}
        ${
          row.stage === "not_the_right_fit" && row.close_reason
            ? `<p class="pp-card__reason">${esc(row.close_reason)}</p>`
            : ""
        }
        <div class="pp-card__tags">
          ${tags}
          ${noteCount ? `<span class="pp-chip pp-chip--note">${noteCount} note${noteCount === 1 ? "" : "s"}</span>` : ""}
        </div>
        <div class="pp-card__footer">
          <p class="pp-card__who">${esc(row.added_by ? `Added by ${row.added_by}` : "")}</p>
          ${updated ? `<p class="pp-card__when">Updated ${esc(updated)}</p>` : ""}
        </div>
      </div>
    </article>`;
  }

  function wireCardPhotos(root) {
    root.querySelectorAll(".pp-card__photo").forEach((img) => {
      const fallback = img.parentElement?.querySelector(".pp-card__fallback");
      if (!fallback) return;
      img.addEventListener("error", () => {
        img.hidden = true;
        fallback.hidden = false;
      });
    });
  }

  function pipelineStages() {
    const allowed = new Set(state.pipelineStageIds || []);
    if (!allowed.size) {
      return state.stages.filter((stage) => stage.id !== "watch_list" && !stage.watch_list_only);
    }
    return state.stages.filter((stage) => allowed.has(stage.id));
  }

  function renderBoard(rows) {
    const stages = pipelineStages();
    els.board.innerHTML = stages
      .map((stage) => {
        const cards = rows.filter((row) => row.stage === stage.id);
        const color = stage.color || "#3d8bfd";
        return `<section class="pp-col" style="--stage:${esc(color)}">
          <header class="pp-col__head">
            <h2 class="pp-col__title">${esc(stage.title)} <span class="pp-col__count">${cards.length}</span></h2>
            <p class="pp-col__hint">${esc(stage.hint)}</p>
          </header>
          <div class="pp-col__list" data-stage="${esc(stage.id)}">
            ${cards.map(cardHtml).join("") || `<p class="pp-card__meta">Drop players here</p>`}
          </div>
        </section>`;
      })
      .join("");

    wireCardPhotos(els.board);

    els.board.querySelectorAll(".pp-card").forEach((card) => {
      card.addEventListener("click", () => openDrawer(card.dataset.id));
      card.addEventListener("dragstart", (event) => {
        state.dragId = card.dataset.id;
        card.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.id);
      });
      card.addEventListener("dragend", () => {
        state.dragId = null;
        card.classList.remove("is-dragging");
      });
    });

    els.board.querySelectorAll(".pp-col__list").forEach((list) => {
      list.addEventListener("dragover", (event) => {
        event.preventDefault();
        list.classList.add("is-over");
      });
      list.addEventListener("dragleave", () => list.classList.remove("is-over"));
      list.addEventListener("drop", async (event) => {
        event.preventDefault();
        list.classList.remove("is-over");
        const id = event.dataTransfer.getData("text/plain") || state.dragId;
        if (!id) return;
        const after = event.target.closest(".pp-card");
        await moveTarget(id, list.dataset.stage, after?.dataset.id || null);
      });
    });
  }

  function renderTable(rows) {
    if (!rows.length) {
      els.table.innerHTML = `<div class="pp-table-empty">No players match these filters.</div>`;
      return;
    }

    const groups = pipelineStages()
      .map((stage) => ({
        stage,
        rows: rows.filter((row) => row.stage === stage.id),
      }))
      .filter((group) => group.rows.length);

    els.table.innerHTML = groups
      .map(({ stage, rows: groupRows }) => {
        const color = stage.color || "#3d8bfd";
        return `<section class="pp-table-group" style="--stage:${esc(color)}">
          <header class="pp-table-group__head">
            <span class="pp-table-group__dot"></span>
            <h2>${esc(stage.title)}</h2>
            <span class="pp-table-group__count">${groupRows.length}</span>
          </header>
          <div class="pp-table">
            <div class="pp-table__head">
              <span>Player</span>
              <span>Score</span>
              <span>Position</span>
              <span>Club</span>
              <span>Age</span>
              <span>Stage</span>
              <span>Tags</span>
              <span>Added by</span>
            </div>
            ${groupRows
              .map((row) => {
                const tags = (row.tags || [])
                  .slice(0, 4)
                  .map((tag) => `<span class="pp-chip">${esc(tag)}</span>`)
                  .join("");
                return `<button type="button" class="pp-table__row" data-id="${esc(row.id)}">
                  <span class="pp-table__player">
                    ${photoBlock(row)}
                    <span>
                      <strong>${esc(row.name)}</strong>
                      ${row.manual ? `<span class="pp-manual-badge">Manual</span>` : ""}
                      ${
                        row.close_reason
                          ? `<em class="pp-table__reason">${esc(row.close_reason)}</em>`
                          : ""
                      }
                    </span>
                  </span>
                  <span>${scoreBadge(row, { compact: true }) || "—"}</span>
                  <span>${esc(row.position_label || "—")}</span>
                  <span>${esc(row.club || "—")}</span>
                  <span>${row.age != null ? esc(row.age) : "—"}</span>
                  <span>${statusPill(row)}</span>
                  <span class="pp-table__tags">${tags || "—"}</span>
                  <span>${esc(row.added_by || "—")}</span>
                </button>`;
              })
              .join("")}
          </div>
        </section>`;
      })
      .join("");

    wireCardPhotos(els.table);
    els.table.querySelectorAll(".pp-table__row").forEach((row) => {
      row.addEventListener("click", () => openDrawer(row.dataset.id));
    });
  }

  function targetById(id) {
    return state.targets.find((row) => row.id === id) || null;
  }

  function renderDrawerStats(row) {
    if (!els.drawerStatsBlock || !els.drawerStats) return;
    if (row.manual || !row.player_id) {
      els.drawerStatsBlock.hidden = true;
      els.drawerStats.innerHTML = "";
      return;
    }
    els.drawerStatsBlock.hidden = false;
    const stats = [
      ["Data score", row.overall_score != null ? Math.round(Number(row.overall_score)) : "—"],
      ["Minutes", row.minutes != null ? formatMinutes(row.minutes) : "—"],
      [
        "Top profile",
        row.top_profile && row.top_profile_score != null
          ? `${row.top_profile} (${Math.round(Number(row.top_profile_score))})`
          : "—",
      ],
      ["Foot", row.foot || "—"],
      ["Height", row.height || "—"],
    ];
    els.drawerStats.innerHTML = stats
      .map(
        ([label, value]) =>
          `<div class="pp-drawer__stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`
      )
      .join("");
    if (els.drawerRefreshStats) {
      els.drawerRefreshStats.disabled = !row.position;
      els.drawerRefreshStats.title = row.position
        ? ""
        : "Set a position first to load Impect data scores";
    }
  }

  function mergeTargets(updatedTargets) {
    if (!Array.isArray(updatedTargets) || !updatedTargets.length) return;
    const byId = new Map(updatedTargets.map((row) => [row.id, row]));
    state.targets = state.targets.map((row) => byId.get(row.id) || row);
  }

  async function refreshMissingStats() {
    const missing = state.targets.filter(
      (row) => !row.manual && row.player_id && row.position && row.overall_score == null
    );
    if (!missing.length) return;
    try {
      const data = await fetchJson("/api/player-pipelines/refresh-stats", {
        method: "POST",
        body: JSON.stringify({ target_ids: missing.map((row) => row.id) }),
      });
      mergeTargets(data.targets || []);
      render();
      if (state.openId) openDrawer(state.openId);
    } catch {
      /* background refresh — ignore */
    }
  }

  async function refreshTargetStats(targetId) {
    setStatus("Refreshing data score…");
    try {
      const data = await fetchJson("/api/player-pipelines/refresh-stats", {
        method: "POST",
        body: JSON.stringify({ target_ids: [targetId] }),
      });
      mergeTargets(data.targets || []);
      render();
      openDrawer(targetId);
      setStatus("");
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  function openDrawer(id) {
    const row = targetById(id);
    if (!row) return;
    state.openId = id;
    els.drawer.hidden = false;
    const color = row.stage_color || stageColor(row.stage);
    els.drawerStage.textContent = stageTitle(row.stage);
    els.drawerStage.style.color = color;
    els.drawerName.textContent = row.name;
    els.drawerMeta.textContent = [
      row.position_label,
      row.club,
      row.league,
      row.age != null ? `Age ${row.age}` : "",
      row.manual ? "Manual entry" : "",
    ]
      .filter(Boolean)
      .join(" · ");
    const reasonEl = document.getElementById("ppDrawerReason");
    if (reasonEl) {
      if (row.stage === "not_the_right_fit" && row.close_reason) {
        reasonEl.hidden = false;
        reasonEl.textContent = `Why: ${row.close_reason}${row.close_reason_by ? ` — ${row.close_reason_by}` : ""}`;
      } else {
        reasonEl.hidden = true;
        reasonEl.textContent = "";
      }
    }
    if (row.dossier_href) {
      els.drawerDossier.hidden = false;
      els.drawerDossier.href = row.dossier_href;
    } else {
      els.drawerDossier.hidden = true;
    }
    if (els.drawerPosition) {
      els.drawerPosition.value = row.position || "";
    }
    renderDrawerStats(row);
    renderDrawerTags(row);
    renderDrawerNotes(row);
  }

  function closeDrawer() {
    state.openId = null;
    els.drawer.hidden = true;
  }

  function renderDrawerTags(row) {
    const current = new Set((row.tags || []).map((tag) => tag.toLowerCase()));
    const labels = [...new Set([...state.defaultTags, ...(row.tags || [])])];
    els.drawerTags.innerHTML = labels
      .map((tag) => {
        const on = current.has(tag.toLowerCase());
        return `<button type="button" class="pp-tag${on ? " is-on" : ""}" data-tag="${esc(tag)}">${esc(tag)}</button>`;
      })
      .join("");
    els.drawerTags.querySelectorAll(".pp-tag").forEach((btn) => {
      btn.addEventListener("click", () => toggleTag(row.id, btn.dataset.tag));
    });
  }

  function renderDrawerNotes(row) {
    const notes = [...(row.notes || [])].reverse();
    if (!notes.length) {
      els.drawerNotes.innerHTML = `<p class="pp-hint">No notes yet.</p>`;
      return;
    }
    els.drawerNotes.innerHTML = notes
      .map((note) => {
        const when = note.created_at ? new Date(note.created_at).toLocaleString() : "";
        return `<article class="pp-note">
          <p class="pp-note__meta">${esc(note.author || "Staff")} · ${esc(when)}</p>
          <p>${esc(note.text)}</p>
        </article>`;
      })
      .join("");
  }

  async function loadBoard() {
    setStatus("Loading pipelines…");
    try {
      const data = await fetchJson("/api/player-pipelines");
      state.stages = data.stages || [];
      state.pipelineStageIds = data.pipeline_stage_ids || [];
      state.positions = data.positions || [];
      state.defaultTags = data.default_tags || [];
      const pipelineIds = new Set(state.pipelineStageIds);
      state.targets = (data.targets || []).filter((row) =>
        pipelineIds.size ? pipelineIds.has(row.stage) : row.stage !== "watch_list",
      );
      fillFilters();
      setView(state.view);
      if (state.openId) openDrawer(state.openId);
      setStatus("");
      refreshMissingStats();
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  async function addPlayer(player) {
    const playerId = player.impect_player_id || player.id;
    if (!playerId) return;
    setStatus(`Adding ${player.name}…`);
    try {
      const data = await fetchJson("/api/player-pipelines/targets", {
        method: "POST",
        body: JSON.stringify({
          player_id: playerId,
          name: player.name || "",
          club: player.club || "",
          league: player.league || player.competition_name || "",
          position: player.primary_position || player.position || "",
          position_label: player.primary_position_label || player.position_label || "",
          age: player.age ?? null,
          photo_url: player.photo_url || "",
          iteration_ids: player.chartable_season_ids || [],
          stage: "data_identified",
          manual: false,
        }),
      });
      els.search.value = "";
      els.results.classList.add("hidden");
      await loadBoard();
      if (data.target?.id) openDrawer(data.target.id);
      setStatus(
        data.created
          ? `${player.name} added to Data identified.`
          : `${player.name} is already on the board.`
      );
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  async function moveTarget(id, stage, beforeId) {
    const current = targetById(id);
    const needsReason =
      Boolean(state.stages.find((row) => row.id === stage)?.require_reason) &&
      current?.stage !== stage;
    let reason = "";
    if (needsReason) {
      reason = await askCloseReason(current?.name || "this player");
      if (!reason) return;
    }
    try {
      await fetchJson(`/api/player-pipelines/targets/${id}/move`, {
        method: "POST",
        body: JSON.stringify({ stage, before_id: beforeId, reason }),
      });
      await loadBoard();
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  function askCloseReason(playerName) {
    const modal = document.getElementById("ppReasonModal");
    const form = document.getElementById("ppReasonForm");
    const input = document.getElementById("ppReasonText");
    const error = document.getElementById("ppReasonError");
    const heading = document.getElementById("ppReasonHeading");
    if (!modal || !form || !input) {
      const typed = window.prompt(`Why is ${playerName} not the right fit?`);
      return Promise.resolve((typed || "").trim().length >= 8 ? typed.trim() : null);
    }
    heading.textContent = `Why is ${playerName} not the right fit?`;
    input.value = "";
    error.hidden = true;
    modal.hidden = false;
    setTimeout(() => input.focus(), 30);
    return new Promise((resolve) => {
      const close = (value) => {
        modal.hidden = true;
        form.onsubmit = null;
        resolve(value);
      };
      form.onsubmit = (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (text.length < 8) {
          error.hidden = false;
          return;
        }
        close(text);
      };
      modal.querySelectorAll("[data-close-reason]").forEach((el) => {
        el.onclick = () => close(null);
      });
    });
  }

  async function toggleTag(id, tag) {
    const row = targetById(id);
    if (!row) return;
    const current = row.tags || [];
    const has = current.some((item) => item.toLowerCase() === tag.toLowerCase());
    const tags = has
      ? current.filter((item) => item.toLowerCase() !== tag.toLowerCase())
      : [...current, tag];
    try {
      const data = await fetchJson(`/api/player-pipelines/targets/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ tags }),
      });
      const idx = state.targets.findIndex((item) => item.id === id);
      if (idx >= 0) state.targets[idx] = data.target;
      fillFilters();
      render();
      openDrawer(id);
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  async function searchPlayers(query) {
    if (query.trim().length < 3) {
      els.results.classList.add("hidden");
      els.results.innerHTML = "";
      return;
    }
    try {
      const data = await fetchJson("/api/players", {
        method: "POST",
        body: JSON.stringify({ search: query.trim() }),
      });
      const players = data.players || [];
      if (!players.length) {
        els.results.innerHTML = `<p class="pp-result__meta" style="padding:0.7rem">${esc(
          data.message || "No Impect players found — use Add manually."
        )}</p>`;
        els.results.classList.remove("hidden");
        return;
      }
      els.results.innerHTML = players
        .slice(0, 12)
        .map((player, index) => {
          const meta = [player.club, player.league, player.age != null ? `Age ${player.age}` : ""]
            .filter(Boolean)
            .join(" · ");
          return `<button type="button" class="pp-result" data-index="${index}">
            <span><span class="pp-result__name">${esc(player.name)}</span><span class="pp-result__meta">${esc(meta)}</span></span>
            <span class="pp-result__add">Add to pipeline</span>
          </button>`;
        })
        .join("");
      els.results.classList.remove("hidden");
      els.results.querySelectorAll(".pp-result").forEach((btn) => {
        btn.addEventListener("mousedown", (event) => {
          event.preventDefault();
          addPlayer(players[Number(btn.dataset.index)]);
        });
      });
    } catch (err) {
      els.results.innerHTML = `<p class="pp-result__meta" style="padding:0.7rem">${esc(err.message)}</p>`;
      els.results.classList.remove("hidden");
    }
  }

  function openManualModal() {
    const error = document.getElementById("ppManualError");
    if (error) error.hidden = true;
    document.getElementById("ppManualName").value = "";
    document.getElementById("ppManualClub").value = "";
    document.getElementById("ppManualAge").value = "";
    document.getElementById("ppManualLeague").value = "";
    document.getElementById("ppManualPosition").value = "";
    els.manualModal.hidden = false;
    setTimeout(() => document.getElementById("ppManualName").focus(), 30);
  }

  function closeManualModal() {
    els.manualModal.hidden = true;
  }

  let searchTimer = null;
  els.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchPlayers(els.search.value), 280);
  });
  els.search.addEventListener("blur", () => {
    setTimeout(() => els.results.classList.add("hidden"), 180);
  });

  ["input", "change"].forEach((eventName) => {
    els.filterName.addEventListener(eventName, render);
    els.filterPosition.addEventListener(eventName, render);
    els.filterTag.addEventListener(eventName, render);
    els.filterStaff.addEventListener(eventName, render);
  });

  els.viewBoard.addEventListener("click", () => setView("board"));
  els.viewTable.addEventListener("click", () => setView("table"));
  els.manualBtn.addEventListener("click", openManualModal);
  document.querySelectorAll("[data-close-manual]").forEach((el) => {
    el.addEventListener("click", closeManualModal);
  });

  els.manualForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("ppManualName").value.trim();
    const club = document.getElementById("ppManualClub").value.trim();
    const position = document.getElementById("ppManualPosition").value;
    const ageRaw = document.getElementById("ppManualAge").value;
    const league = document.getElementById("ppManualLeague").value.trim();
    const error = document.getElementById("ppManualError");
    if (!name) {
      error.hidden = false;
      error.textContent = "Name is required.";
      return;
    }
    const posLabel = state.positions.find((row) => row.id === position)?.label || "";
    try {
      const data = await fetchJson("/api/player-pipelines/targets", {
        method: "POST",
        body: JSON.stringify({
          manual: true,
          name,
          club,
          league,
          position,
          position_label: posLabel,
          age: ageRaw ? Number(ageRaw) : null,
          stage: "data_identified",
        }),
      });
      closeManualModal();
      await loadBoard();
      if (data.target?.id) openDrawer(data.target.id);
      setStatus(`${name} added manually to Data identified.`);
    } catch (err) {
      error.hidden = false;
      error.textContent = err.message || String(err);
    }
  });

  document.querySelectorAll("[data-close-drawer]").forEach((el) => {
    el.addEventListener("click", closeDrawer);
  });

  els.drawerPosition?.addEventListener("change", async () => {
    if (!state.openId) return;
    const position = els.drawerPosition.value;
    const position_label = state.positions.find((row) => row.id === position)?.label || "";
    try {
      const data = await fetchJson(`/api/player-pipelines/targets/${state.openId}`, {
        method: "PATCH",
        body: JSON.stringify({ position, position_label }),
      });
      const idx = state.targets.findIndex((item) => item.id === state.openId);
      if (idx >= 0) state.targets[idx] = data.target;
      fillFilters();
      render();
      openDrawer(state.openId);
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  });

  els.drawerRefreshStats?.addEventListener("click", () => {
    if (!state.openId) return;
    refreshTargetStats(state.openId);
  });

  els.customTagForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const tag = els.customTag.value.trim();
    if (!tag || !state.openId) return;
    els.customTag.value = "";
    toggleTag(state.openId, tag);
  });

  els.noteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.openId) return;
    const text = els.noteText.value.trim();
    if (!text) return;
    try {
      const data = await fetchJson(`/api/player-pipelines/targets/${state.openId}/notes`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      els.noteText.value = "";
      const idx = state.targets.findIndex((item) => item.id === state.openId);
      if (idx >= 0) state.targets[idx] = data.target;
      render();
      openDrawer(state.openId);
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  });

  els.drawerRemove.addEventListener("click", async () => {
    if (!state.openId) return;
    if (!window.confirm("Remove this player from the pipeline?")) return;
    try {
      await fetchJson(`/api/player-pipelines/targets/${state.openId}`, { method: "DELETE" });
      closeDrawer();
      await loadBoard();
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  });

  loadBoard();
})();
