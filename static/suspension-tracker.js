(() => {
  const state = {
    bucket: "league_two",
    playerFilter: "all",
    cardFilter: "all",
    payload: null,
    saving: new Set(),
  };

  const els = {
    status: document.getElementById("status"),
    thresholds: document.getElementById("thresholds"),
    kpis: document.getElementById("kpis"),
    playerRows: document.getElementById("playerRows"),
    cardRows: document.getElementById("cardRows"),
    playersTitle: document.getElementById("playersTitle"),
    cardsTitle: document.getElementById("cardsTitle"),
    note: document.getElementById("note"),
    refreshBtn: document.getElementById("refreshBtn"),
    bucketTabs: document.getElementById("bucketTabs"),
    rules: document.getElementById("rules"),
    staffRows: document.getElementById("staffRows"),
    staffRules: document.getElementById("staffRules"),
    staffForm: document.getElementById("staffForm"),
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function currentBucket() {
    return state.payload?.buckets?.[state.bucket] || null;
  }

  function offenceOptions(cardKind) {
    const codes = state.payload?.offence_codes || {};
    if (cardKind === "Yellow") return codes.yellow || [];
    return [...(codes.red || []), ...(codes.yellow || [])];
  }

  function pillClass(status) {
    if (status === "Banned") return "st-pill st-pill--banned";
    if (status === "Watch") return "st-pill st-pill--watch";
    return "st-pill st-pill--ok";
  }

  function cardPill(kind) {
    if (kind === "Yellow") return "st-pill st-pill--yellow";
    return "st-pill st-pill--red";
  }

  function setStatus(message, bad = false) {
    els.status.textContent = message;
    els.status.classList.toggle("is-bad", bad);
  }

  function renderTabs() {
    const order = state.payload?.bucket_order || Object.keys(state.payload?.buckets || {});
    els.bucketTabs.innerHTML = order.map((id) => {
      const bucket = state.payload.buckets[id];
      if (!bucket) return "";
      const count = bucket.summary?.yellows ?? 0;
      const active = id === state.bucket ? " is-active" : "";
      return `<button type="button" class="st-tab${active}" data-bucket="${escapeHtml(id)}">${escapeHtml(bucket.short || bucket.label)} <span class="st-tab__count">${count}</span></button>`;
    }).join("");
  }

  function renderThresholds() {
    const bucket = currentBucket();
    els.rules.textContent = bucket?.rules || "";
    const rows = bucket?.thresholds || [];
    els.thresholds.innerHTML = rows
      .map((row) => `<div class="st-threshold"><strong>${escapeHtml(row.cards)} YC</strong> → ${escapeHtml(row.label)}</div>`)
      .join("") || `<div class="st-threshold">No automatic ban thresholds for this bucket</div>`;
  }

  function renderKpis() {
    const bucket = currentBucket();
    const summary = bucket?.summary || {};
    els.kpis.innerHTML = `
      <div class="st-kpi"><p class="st-kpi__label">Yellows</p><p class="st-kpi__value">${summary.yellows ?? "—"}</p></div>
      <div class="st-kpi"><p class="st-kpi__label">Reds</p><p class="st-kpi__value">${summary.reds ?? "—"}</p></div>
      <div class="st-kpi"><p class="st-kpi__label">Players booked</p><p class="st-kpi__value">${summary.players_booked ?? "—"}</p></div>
      <div class="st-kpi"><p class="st-kpi__label">Codes set</p><p class="st-kpi__value">${summary.coded ?? 0}/${(summary.coded ?? 0) + (summary.uncoded ?? 0)}</p></div>
      <div class="st-kpi"><p class="st-kpi__label">On watch</p><p class="st-kpi__value">${summary.watch ?? "—"}</p></div>
    `;
  }

  function renderPlayers() {
    const bucket = currentBucket();
    els.playersTitle.textContent = `Squad (${bucket?.label || "Competition"})`;
    const rows = (bucket?.players || []).filter(
      (row) => state.playerFilter === "all" || row.status === state.playerFilter
    );
    if (!rows.length) {
      els.playerRows.innerHTML = `<tr><td colspan="5"><p class="st-empty">No booked players in this view.</p></td></tr>`;
      return;
    }
    els.playerRows.innerHTML = rows.map((row) => {
      const ycClass = row.yellows > 0 ? "st-yc" : "st-yc st-yc--zero";
      const rcClass = row.reds > 0 ? "st-rc" : "st-rc st-rc--zero";
      return `
        <tr>
          <td>
            <div class="st-player">${escapeHtml(row.player)}</div>
            <div class="st-meta">${escapeHtml(row.last_card || "—")}</div>
          </td>
          <td><span class="${ycClass}">${row.yellows}</span></td>
          <td><span class="${rcClass}">${row.reds}</span></td>
          <td class="st-meta">${escapeHtml(row.risk || "—")}</td>
          <td><span class="${pillClass(row.status)}">${escapeHtml(row.status)}</span></td>
        </tr>`;
    }).join("");
  }

  function optionGroups(options, selected) {
    const groups = new Map();
    for (const opt of options) {
      const group = opt.group || "Codes";
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(opt);
    }
    let html = `<option value="">Select offence…</option>`;
    for (const [group, opts] of groups) {
      html += `<optgroup label="${escapeHtml(group)}">`;
      for (const opt of opts) {
        const sel = opt.value === selected ? " selected" : "";
        html += `<option value="${escapeHtml(opt.value)}"${sel}>${escapeHtml(opt.label)}</option>`;
      }
      html += `</optgroup>`;
    }
    return html;
  }

  function renderCards() {
    const bucket = currentBucket();
    els.cardsTitle.textContent = `Card log · ${bucket?.label || "Competition"}`;
    let rows = [...(bucket?.cards || [])].reverse();
    rows = rows.filter((row) => {
      if (state.cardFilter === "Yellow") return row.card === "Yellow";
      if (state.cardFilter === "Red") return row.card === "Red" || row.card === "SecondYellow";
      if (state.cardFilter === "uncoded") return !row.offence_code;
      return true;
    });
    if (!rows.length) {
      els.cardRows.innerHTML = `<tr><td colspan="5"><p class="st-empty">No cards in this filter.</p></td></tr>`;
      return;
    }
    els.cardRows.innerHTML = rows.map((row) => {
      const options = offenceOptions(row.card === "Yellow" ? "Yellow" : "Red");
      const missing = row.offence_code ? "" : " is-missing";
      const kindLabel = row.card === "SecondYellow" ? "2nd yellow" : row.card;
      return `
        <tr>
          <td>
            <div>${escapeHtml(row.date || "—")}</div>
            <div class="st-meta">${escapeHtml(row.minute ?? "—")}'</div>
          </td>
          <td class="st-player">${escapeHtml(row.player)}</td>
          <td>
            <div>${escapeHtml(row.venue)} v ${escapeHtml(row.opponent)}</div>
            <div class="st-meta">${escapeHtml(row.competition || "")}</div>
          </td>
          <td><span class="${cardPill(row.card === "Yellow" ? "Yellow" : "Red")}">${escapeHtml(kindLabel)}</span></td>
          <td>
            <select class="st-select${missing}" data-card-id="${escapeHtml(row.id)}" aria-label="Offence code for ${escapeHtml(row.player)}">
              ${optionGroups(options, row.offence_code || "")}
            </select>
          </td>
        </tr>`;
    }).join("");
  }

  function renderStaff() {
    els.staffRules.textContent = state.payload?.staff_rules || "";
    const rows = state.payload?.staff || [];
    els.staffRows.innerHTML = rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.date)}</td>
        <td class="st-player">${escapeHtml(row.name)}</td>
        <td>${escapeHtml(row.offence_code)}</td>
        <td class="st-meta">${escapeHtml(row.notes || "—")}</td>
        <td><button type="button" class="st-btn" data-staff-delete="${escapeHtml(row.id)}">Delete</button></td>
      </tr>
    `).join("") || `<tr><td colspan="5"><p class="st-empty">No staff cautions logged.</p></td></tr>`;
  }

  function render() {
    if (!state.payload) return;
    renderTabs();
    renderThresholds();
    renderKpis();
    renderPlayers();
    renderCards();
    renderStaff();
    els.note.textContent = state.payload.note || "";
  }

  async function load({ refresh = false } = {}) {
    els.refreshBtn.disabled = true;
    setStatus(refresh ? "Refreshing FotMob cards…" : "Loading cards from FotMob…");
    try {
      const url = `/api/suspension-tracker?refresh=${refresh ? "true" : "false"}`;
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.payload = await res.json();
      if (!state.payload.buckets?.[state.bucket]) state.bucket = state.payload.bucket_order?.[0] || "league_two";
      const played = state.payload.fixtures_played ?? 0;
      const total = state.payload.fixtures_total ?? 0;
      setStatus(`Season ${state.payload.season} · ${played}/${total} fixtures played · FotMob cards loaded.`);
      render();
    } catch (err) {
      setStatus(`Could not load Suspension Tracker: ${err.message}`, true);
    } finally {
      els.refreshBtn.disabled = false;
    }
  }

  async function saveOffence(cardId, offenceCode, selectEl) {
    if (state.saving.has(cardId)) return;
    state.saving.add(cardId);
    selectEl.classList.add("is-saving");
    selectEl.classList.remove("is-saved", "is-missing");
    try {
      const res = await fetch(`/api/suspension-tracker/card/${encodeURIComponent(cardId)}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ offence_code: offenceCode || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const saved = await res.json();
      const bucket = currentBucket();
      const card = (bucket?.cards || []).find((row) => row.id === cardId);
      if (card) {
        card.offence_code = saved.offence_code;
        card.offence_label = saved.offence_label;
      }
      if (bucket) {
        const coded = (bucket.cards || []).filter((row) => row.offence_code).length;
        bucket.summary.coded = coded;
        bucket.summary.uncoded = Math.max(0, (bucket.cards || []).length - coded);
      }
      selectEl.classList.toggle("is-missing", !saved.offence_code);
      selectEl.classList.add("is-saved");
      renderKpis();
    } catch (err) {
      setStatus(`Could not save offence code: ${err.message}`, true);
      selectEl.classList.add("is-missing");
    } finally {
      selectEl.classList.remove("is-saving");
      state.saving.delete(cardId);
    }
  }

  els.bucketTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-bucket]");
    if (!btn) return;
    state.bucket = btn.dataset.bucket;
    render();
  });

  document.getElementById("playerFilters").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-status]");
    if (!btn) return;
    state.playerFilter = btn.dataset.status;
    document.querySelectorAll("#playerFilters .st-chip").forEach((el) => {
      el.classList.toggle("is-active", el === btn);
    });
    renderPlayers();
  });

  document.getElementById("cardFilters").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-card]");
    if (!btn) return;
    state.cardFilter = btn.dataset.card;
    document.querySelectorAll("#cardFilters .st-chip").forEach((el) => {
      el.classList.toggle("is-active", el === btn);
    });
    renderCards();
  });

  els.cardRows.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-card-id]");
    if (!select) return;
    saveOffence(select.dataset.cardId, select.value, select);
  });

  els.refreshBtn.addEventListener("click", () => load({ refresh: true }));

  els.staffForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = {
      name: document.getElementById("staffName").value,
      date: document.getElementById("staffDate").value,
      offence_code: document.getElementById("staffCode").value || "C1",
      notes: document.getElementById("staffNotes").value,
    };
    const res = await fetch("/api/suspension-tracker/staff", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return setStatus(`Staff save failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    els.staffForm.reset();
    render();
  });

  els.staffRows?.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-staff-delete]");
    if (!btn) return;
    const res = await fetch(`/api/suspension-tracker/staff/${encodeURIComponent(btn.dataset.staffDelete)}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!res.ok) return setStatus(`Delete failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    render();
  });

  load();
})();
