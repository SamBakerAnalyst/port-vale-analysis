(function initPlayerPipelines() {
  const els = {
    board: document.getElementById("ppBoard"),
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
    drawerTags: document.getElementById("ppDrawerTags"),
    drawerNotes: document.getElementById("ppDrawerNotes"),
    customTagForm: document.getElementById("ppCustomTagForm"),
    customTag: document.getElementById("ppCustomTag"),
    noteForm: document.getElementById("ppNoteForm"),
    noteText: document.getElementById("ppNoteText"),
  };

  const state = {
    stages: [],
    positions: [],
    defaultTags: [],
    targets: [],
    me: "",
    openId: null,
    dragId: null,
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

  function stageTitle(id) {
    return state.stages.find((row) => row.id === id)?.title || id;
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
    els.filterPosition.innerHTML =
      `<option value="">All positions</option>` +
      state.positions
        .map((row) => `<option value="${esc(row.id)}">${esc(row.label)}</option>`)
        .join("");
    els.filterPosition.value = posKeep;

    const tags = new Set(state.defaultTags);
    state.targets.forEach((row) => (row.tags || []).forEach((tag) => tags.add(tag)));
    const tagKeep = els.filterTag.value;
    els.filterTag.innerHTML =
      `<option value="">All tags</option>` +
      [...tags]
        .sort((a, b) => a.localeCompare(b))
        .map((tag) => `<option value="${esc(tag)}">${esc(tag)}</option>`)
        .join("");
    els.filterTag.value = tagKeep;

    const staff = [...new Set(state.targets.map((row) => row.added_by).filter(Boolean))].sort();
    const staffKeep = els.filterStaff.value;
    els.filterStaff.innerHTML =
      `<option value="">Everyone</option>` +
      staff.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
    els.filterStaff.value = staffKeep;
  }

  function renderBoard() {
    const rows = filteredTargets();
    els.count.textContent = `${rows.length} of ${state.targets.length} players`;
    els.board.innerHTML = state.stages
      .map((stage) => {
        const cards = rows.filter((row) => row.stage === stage.id);
        return `<section class="pp-col${stage.id === "gone_elsewhere" ? " pp-col--gone" : ""}">
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

    els.board.querySelectorAll(".pp-card").forEach((card) => {
      const img = card.querySelector(".pp-card__photo");
      const fallback = card.querySelector(".pp-card__fallback");
      if (img && fallback) {
        img.addEventListener("error", () => {
          img.hidden = true;
          fallback.hidden = false;
        });
      }
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

    function cardHtml(row) {
    const meta = [row.position_label, row.club, row.age != null ? `Age ${row.age}` : ""]
      .filter(Boolean)
      .join(" · ");
    const tags = (row.tags || [])
      .slice(0, 3)
      .map((tag) => `<span class="pp-chip">${esc(tag)}</span>`)
      .join("");
    const noteCount = (row.notes || []).length;
    return `<article class="pp-card" draggable="true" data-id="${esc(row.id)}">
      ${photoBlock(row)}
      <div>
        <p class="pp-card__name">${esc(row.name)}</p>
        <p class="pp-card__meta">${esc(meta)}</p>
        <p class="pp-card__who">${esc(row.added_by ? `Added by ${row.added_by}` : "")}</p>
        <div class="pp-card__tags">
          ${tags}
          ${noteCount ? `<span class="pp-chip pp-chip--note">${noteCount} note${noteCount === 1 ? "" : "s"}</span>` : ""}
        </div>
      </div>
    </article>`;
  }

  function targetById(id) {
    return state.targets.find((row) => row.id === id) || null;
  }

  function openDrawer(id) {
    const row = targetById(id);
    if (!row) return;
    state.openId = id;
    els.drawer.hidden = false;
    els.drawerStage.textContent = stageTitle(row.stage);
    els.drawerName.textContent = row.name;
    els.drawerMeta.textContent = [row.position_label, row.club, row.league, row.age != null ? `Age ${row.age}` : ""]
      .filter(Boolean)
      .join(" · ");
    els.drawerDossier.href = row.dossier_href || `/player/${row.player_id}`;
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
      state.positions = data.positions || [];
      state.defaultTags = data.default_tags || [];
      state.targets = data.targets || [];
      fillFilters();
      renderBoard();
      if (state.openId) openDrawer(state.openId);
      setStatus("");
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
          stage: "data_identified",
        }),
      });
      els.search.value = "";
      els.results.classList.add("hidden");
      await loadBoard();
      if (data.target?.id) openDrawer(data.target.id);
      setStatus(data.created ? `${player.name} added to Data identified.` : `${player.name} is already on the board.`);
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  async function moveTarget(id, stage, beforeId) {
    try {
      await fetchJson(`/api/player-pipelines/targets/${id}/move`, {
        method: "POST",
        body: JSON.stringify({ stage, before_id: beforeId }),
      });
      await loadBoard();
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
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
      renderBoard();
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
        els.results.innerHTML = `<p class="pp-result__meta" style="padding:0.7rem">${esc(data.message || "No players found.")}</p>`;
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

  let searchTimer = null;
  els.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchPlayers(els.search.value), 280);
  });
  els.search.addEventListener("blur", () => {
    setTimeout(() => els.results.classList.add("hidden"), 180);
  });

  ["input", "change"].forEach((eventName) => {
    els.filterName.addEventListener(eventName, renderBoard);
    els.filterPosition.addEventListener(eventName, renderBoard);
    els.filterTag.addEventListener(eventName, renderBoard);
    els.filterStaff.addEventListener(eventName, renderBoard);
  });

  document.querySelectorAll("[data-close-drawer]").forEach((el) => {
    el.addEventListener("click", closeDrawer);
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
      renderBoard();
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
