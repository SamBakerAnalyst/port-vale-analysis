(() => {
  const state = { view: "players", payload: null, filter: "" };
  const els = {
    status: document.getElementById("status"),
    kpis: document.getElementById("kpis"),
    playerRows: document.getElementById("playerRows"),
    matchdayRows: document.getElementById("matchdayRows"),
    note: document.getElementById("note"),
    playerFilter: document.getElementById("playerFilter"),
    bonusPlayer: document.getElementById("bonusPlayer"),
    bonusType: document.getElementById("bonusType"),
    bonusForm: document.getElementById("bonusForm"),
  };

  function esc(v) {
    return String(v ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function setStatus(msg, bad = false) {
    els.status.textContent = msg;
    els.status.classList.toggle("is-bad", bad);
  }

  function showView(view) {
    state.view = view;
    document.querySelectorAll(".bt-tab").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.view === view);
    });
    document.getElementById("playersView").classList.toggle("hidden", view !== "players");
    document.getElementById("matchdayView").classList.toggle("hidden", view !== "matchday");
    document.getElementById("addView").classList.toggle("hidden", view !== "add");
  }

  function typeLabel(id) {
    return (state.payload?.matchday_types || []).find((row) => row.id === id)?.label || id;
  }

  function render() {
    const p = state.payload;
    if (!p) return;
    const s = p.summary || {};
    els.kpis.innerHTML = `
      <div class="bt-kpi"><p class="bt-kpi__label">Players</p><p class="bt-kpi__value">${s.players ?? 0}</p></div>
      <div class="bt-kpi"><p class="bt-kpi__label">With provisions</p><p class="bt-kpi__value">${s.with_provisions ?? 0}</p></div>
      <div class="bt-kpi"><p class="bt-kpi__label">Appearance bonus</p><p class="bt-kpi__value">${s.appearance_bonus_players ?? 0}</p></div>
      <div class="bt-kpi"><p class="bt-kpi__label">Matchday rows</p><p class="bt-kpi__value">${s.matchday_logged ?? 0}</p></div>
      <div class="bt-kpi"><p class="bt-kpi__label">Unpaid</p><p class="bt-kpi__value">${s.unpaid ?? 0}</p></div>
    `;
    const q = state.filter.trim().toLowerCase();
    const players = (p.players || []).filter((row) => !q || String(row.name || "").toLowerCase().includes(q));
    els.playerRows.innerHTML = players.map((row) => {
      const pill = row.appearance_bonus === "none"
        ? `<span class="bt-pill bt-pill--muted">None</span>`
        : `<span class="bt-pill">${esc(row.appearance_bonus_label)}</span>`;
      const totals = row.totals || {};
      const logged = (totals.appearance || 0) + (totals.goal_assist || 0) + (totals.clean_sheet || 0) + (totals.squad_bonus || 0) + (totals.personal_win || 0);
      return `<tr>
        <td><div class="bt-player">${esc(row.name)}</div></td>
        <td>${pill}</td>
        <td><div class="bt-meta">${esc(row.provisions || "—")}</div></td>
        <td>${logged}</td>
        <td>${totals.unpaid || 0}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="5">No players.</td></tr>`;

    els.matchdayRows.innerHTML = (p.matchday || []).map((row) => `
      <tr>
        <td>${esc(row.date)}</td>
        <td class="bt-player">${esc(row.player_name)}</td>
        <td>${esc(row.opponent)}${row.result ? ` · ${esc(row.result)}` : ""}</td>
        <td>${esc(typeLabel(row.bonus_type))}</td>
        <td>${row.amount != null ? `£${esc(row.amount)}` : "—"}</td>
        <td>
          <label class="bt-meta">
            <input type="checkbox" data-paid="${esc(row.id)}" ${row.paid ? "checked" : ""} /> Paid
          </label>
          <div class="bt-meta">${esc(row.tracking || "")}</div>
        </td>
        <td><button type="button" class="bt-linkbtn" data-delete="${esc(row.id)}">Delete</button></td>
      </tr>
    `).join("") || `<tr><td colspan="7">No matchday bonuses logged yet.</td></tr>`;

    els.bonusPlayer.innerHTML = (p.players || []).map((row) =>
      `<option value="${esc(row.id)}">${esc(row.name)}</option>`
    ).join("");
    els.bonusType.innerHTML = (p.matchday_types || []).map((row) =>
      `<option value="${esc(row.id)}">${esc(row.label)}</option>`
    ).join("");
    els.note.textContent = p.note || "";
  }

  async function load() {
    setStatus("Loading bonus board…");
    try {
      const res = await fetch("/api/bonus-tracker", { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.payload = await res.json();
      setStatus(`Season ${state.payload.season} · provisions from ${state.payload.seeded_from || "store"}.`);
      render();
    } catch (err) {
      setStatus(`Could not load: ${err.message}`, true);
    }
  }

  document.querySelectorAll(".bt-tab").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });
  els.playerFilter.addEventListener("input", () => {
    state.filter = els.playerFilter.value;
    render();
  });
  document.getElementById("reseedBtn").addEventListener("click", async () => {
    setStatus("Reseeding provisions…");
    const res = await fetch("/api/bonus-tracker/reseed", { method: "POST", credentials: "same-origin" });
    if (!res.ok) return setStatus(`Reseed failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    setStatus("Provisions seed reloaded (existing players kept; new names added).");
    render();
  });
  els.bonusForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const amountRaw = document.getElementById("bonusAmount").value;
    const body = {
      player_id: els.bonusPlayer.value,
      date: document.getElementById("bonusDate").value,
      opponent: document.getElementById("bonusOpponent").value,
      result: document.getElementById("bonusResult").value,
      bonus_type: els.bonusType.value,
      amount: amountRaw === "" ? null : Number(amountRaw),
      tracking: document.getElementById("bonusTracking").value,
      notes: document.getElementById("bonusNotes").value,
    };
    const res = await fetch("/api/bonus-tracker/matchday", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return setStatus(`Save failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    els.bonusForm.reset();
    showView("matchday");
    setStatus("Bonus logged.");
    render();
  });
  els.matchdayRows.addEventListener("change", async (event) => {
    const box = event.target.closest("[data-paid]");
    if (!box) return;
    const res = await fetch(`/api/bonus-tracker/matchday/${encodeURIComponent(box.dataset.paid)}`, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paid: box.checked }),
    });
    if (!res.ok) return setStatus(`Update failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    render();
  });
  els.matchdayRows.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-delete]");
    if (!btn) return;
    if (!confirm("Delete this bonus row?")) return;
    const res = await fetch(`/api/bonus-tracker/matchday/${encodeURIComponent(btn.dataset.delete)}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!res.ok) return setStatus(`Delete failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    render();
  });

  load();
})();
