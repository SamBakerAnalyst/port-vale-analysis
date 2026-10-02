(() => {
  const CLOSE_WITHIN = 3;
  const state = { view: "players", payload: null, filter: "", chip: "all", sort: "close" };
  const els = {
    status: document.getElementById("status"),
    kpis: document.getElementById("kpis"),
    spotWrap: document.getElementById("spotWrap"),
    spotlight: document.getElementById("spotlight"),
    playerRows: document.getElementById("playerRows"),
    matchdayRows: document.getElementById("matchdayRows"),
    note: document.getElementById("note"),
    playerFilter: document.getElementById("playerFilter"),
    sortBy: document.getElementById("sortBy"),
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

  function initials(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    return ((parts[0] || "")[0] || "").concat((parts.length > 1 ? parts[parts.length - 1][0] : "") || "").toUpperCase();
  }

  function avatar(row, size = "") {
    const fallback = `<span class="bt-ava__init">${esc(initials(row.name))}</span>`;
    const img = row.photo_url
      ? `<img src="${esc(row.photo_url)}" alt="" loading="lazy" onerror="this.remove()" />`
      : "";
    return `<span class="bt-ava ${size}">${fallback}${img}</span>`;
  }

  function milestoneClauses(row) {
    return (row.clauses || []).filter((c) => (c.thresholds || []).some((s) => s.target > 0));
  }

  function perMatchClauses(row) {
    return (row.clauses || []).filter((c) => !(c.thresholds || []).some((s) => s.target > 0));
  }

  /** Nearest open milestone for a player: { clause, step, remaining, pct } */
  function nextTrigger(row) {
    let best = null;
    for (const clause of milestoneClauses(row)) {
      if (clause.current == null) continue;
      const step = (clause.thresholds || []).find((s) => !s.met && s.target > 0);
      if (!step) continue;
      const pct = Math.min(1, clause.current / step.target);
      if (!best || step.remaining < best.remaining || (step.remaining === best.remaining && pct > best.pct)) {
        best = { clause, step, remaining: step.remaining, pct };
      }
    }
    return best;
  }

  function metCount(row) {
    return milestoneClauses(row).reduce(
      (n, c) => n + (c.thresholds || []).filter((s) => s.met).length, 0
    );
  }

  function shortUnit(unit, count) {
    const word = String(unit || "").replace(/^league\s+/i, "");
    return count === 1 ? word.replace(/s$/i, "") : word;
  }

  function ring(pct, tone) {
    const r = 26;
    const c = 2 * Math.PI * r;
    const off = c * (1 - Math.max(0, Math.min(1, pct)));
    return `<svg class="bt-ring ${tone}" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="${r}" class="bt-ring__bg"/>
      <circle cx="32" cy="32" r="${r}" class="bt-ring__fg" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/>
    </svg>`;
  }

  function renderKpis(players) {
    const p = state.payload;
    const s = p.summary || {};
    const close = players.filter((row) => {
      const t = nextTrigger(row);
      return t && t.remaining <= CLOSE_WITHIN;
    }).length;
    const met = players.reduce((n, row) => n + metCount(row), 0);
    const open = players.reduce(
      (n, row) => n + milestoneClauses(row).reduce((m, c) => m + (c.thresholds || []).filter((st) => !st.met).length, 0), 0
    );
    const unpaid = (p.matchday || []).filter((row) => !row.paid).length;
    const kpi = (label, value, sub, tone = "") => `
      <div class="bt-kpi ${tone}">
        <p class="bt-kpi__label">${label}</p>
        <p class="bt-kpi__value">${value}</p>
        <p class="bt-kpi__sub">${sub}</p>
      </div>`;
    els.kpis.innerHTML = [
      kpi("Players tracked", s.players ?? players.length, `${s.appearance_bonus_players ?? 0} on appearance bonus`),
      kpi("Within 3 of a trigger", close, close ? "Watch these next" : "Nobody close yet", close ? "is-gold" : ""),
      kpi("Milestones hit", met, `${open} still open`, met ? "is-green" : ""),
      kpi("Matchday bonuses", (p.matchday || []).length, unpaid ? `${unpaid} unpaid` : "All paid", unpaid ? "is-red" : ""),
    ].join("");
  }

  function renderSpotlight(players) {
    const ranked = players
      .map((row) => ({ row, t: nextTrigger(row) }))
      .filter((x) => x.t && (x.t.clause.current > 0 || x.t.remaining <= CLOSE_WITHIN))
      .sort((a, b) => a.t.remaining - b.t.remaining || b.t.pct - a.t.pct)
      .slice(0, 6);
    els.spotWrap.classList.toggle("hidden", !ranked.length);
    els.spotlight.innerHTML = ranked.map(({ row, t }) => {
      const tone = t.remaining <= CLOSE_WITHIN ? "is-gold" : "is-slate";
      return `<button type="button" class="bt-spotcard ${tone}" data-jump="${esc(row.id)}">
        <div class="bt-spotcard__ring">
          ${ring(t.pct, tone)}
          ${avatar(row, "bt-ava--ring")}
        </div>
        <div class="bt-spotcard__body">
          <p class="bt-spotcard__name">${esc(row.name)}</p>
          <p class="bt-spotcard__to"><strong>${t.remaining}</strong> ${esc(shortUnit(t.clause.unit, t.remaining))} to go</p>
          <p class="bt-spotcard__clause">${t.clause.current} / ${t.step.target} · ${esc(t.clause.text)}</p>
        </div>
      </button>`;
    }).join("");
  }

  function milestoneTrack(clause) {
    const steps = (clause.thresholds || []).filter((s) => s.target > 0);
    const current = clause.current;
    const known = current != null;
    const max = Math.max(...steps.map((s) => s.target));
    const fill = known ? Math.min(100, (current / max) * 100) : 0;
    const next = steps.find((s) => !s.met);
    const allMet = !next;
    const close = known && next && next.remaining <= CLOSE_WITHIN;
    const tone = allMet ? "is-done" : (close ? "is-close" : (known && current > 0 ? "is-live" : "is-idle"));

    const markers = steps.map((s) => {
      const pos = (s.target / max) * 100;
      const cls = s.met ? "is-met" : (next && s.target === next.target ? "is-next" : "");
      return `<span class="bt-mark ${cls}" style="left:${pos}%">
        <span class="bt-mark__dot"></span>
        <span class="bt-mark__num">${esc(s.target)}</span>
      </span>`;
    }).join("");

    const status = allMet
      ? `<span class="bt-badge is-done">✓ All hit</span>`
      : known
        ? `<span class="bt-badge ${close ? "is-close" : ""}">${next.remaining} to go</span>`
        : `<span class="bt-badge">No data</span>`;

    return `<div class="bt-ms ${tone}">
      <div class="bt-ms__top">
        <p class="bt-ms__text">${esc(clause.text)}</p>
        ${status}
      </div>
      <div class="bt-ms__read">
        <span class="bt-ms__now">${known ? current : "—"}</span>
        <span class="bt-ms__of">/ ${allMet ? max : next.target} ${esc(shortUnit(clause.unit))}</span>
      </div>
      <div class="bt-ms__rail" role="progressbar" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${known ? current : 0}">
        <span class="bt-ms__fill" style="width:${fill}%"></span>
        ${markers}
      </div>
    </div>`;
  }

  function perMatchChip(clause) {
    const has = clause.current != null;
    return `<div class="bt-pm ${has && clause.current > 0 ? "is-on" : ""}">
      <span class="bt-pm__count">${has ? clause.current : "—"}</span>
      <span class="bt-pm__text">${esc(clause.text)}
        <em>${has ? `${esc(clause.unit || "")} this season` : "log on matchday"}</em>
      </span>
    </div>`;
  }

  function playerCard(row) {
    const time = row.playing_time || {};
    const totals = row.totals || {};
    const logged = (totals.appearance || 0) + (totals.goal_assist || 0) + (totals.clean_sheet || 0)
      + (totals.squad_bonus || 0) + (totals.personal_win || 0);
    const t = nextTrigger(row);
    const met = metCount(row);
    const accent = t && t.remaining <= CLOSE_WITHIN ? "is-gold" : (met ? "is-green" : "");
    const ms = milestoneClauses(row);
    const pm = perMatchClauses(row);
    const stat = (v, l) => `<div class="bt-stat"><span>${v ?? 0}</span><small>${l}</small></div>`;

    return `<article class="bt-card ${accent}" id="player-${esc(row.id)}">
      <header class="bt-card__head">
        ${avatar(row)}
        <div class="bt-card__who">
          <h3>${esc(row.name)}</h3>
          <div class="bt-card__tags">
            ${row.appearance_bonus !== "none" ? `<span class="bt-tag is-green">${esc(row.appearance_bonus_label)}</span>` : ""}
            ${t ? `<span class="bt-tag ${t.remaining <= CLOSE_WITHIN ? "is-gold" : ""}">Next: ${t.remaining} ${esc(shortUnit(t.clause.unit, t.remaining))}</span>` : ""}
            ${met ? `<span class="bt-tag is-green">${met} hit</span>` : ""}
          </div>
        </div>
        <div class="bt-card__logged" title="Matchday bonuses logged">
          <span>${logged}</span><small>logged${totals.unpaid ? ` · ${totals.unpaid} unpaid` : ""}</small>
        </div>
      </header>
      <div class="bt-stats">
        ${stat(time.league_starts, "Starts")}
        ${stat(time.league_appearances, "Apps")}
        ${stat(time.league_minutes, "Mins")}
        ${stat(time.league_goals, "Goals")}
        ${stat(time.league_assists, "Assists")}
      </div>
      ${ms.length ? `<div class="bt-card__ms">${ms.map(milestoneTrack).join("")}</div>` : ""}
      ${pm.length ? `<div class="bt-card__pm">
        <p class="bt-mini-head">Per-match bonuses</p>
        <div class="bt-pm-list">${pm.map(perMatchChip).join("")}</div>
      </div>` : ""}
      ${!ms.length && !pm.length ? `<p class="bt-empty-line">No trackable clause.</p>` : ""}
    </article>`;
  }

  function sortPlayers(list) {
    const byName = (a, b) => String(a.name).localeCompare(String(b.name));
    const sorted = [...list];
    if (state.sort === "name") return sorted.sort(byName);
    if (state.sort === "minutes") {
      return sorted.sort((a, b) => (b.playing_time?.league_minutes || 0) - (a.playing_time?.league_minutes || 0) || byName(a, b));
    }
    if (state.sort === "starts") {
      return sorted.sort((a, b) => (b.playing_time?.league_starts || 0) - (a.playing_time?.league_starts || 0) || byName(a, b));
    }
    return sorted.sort((a, b) => {
      const ta = nextTrigger(a);
      const tb = nextTrigger(b);
      if (ta && tb) return ta.remaining - tb.remaining || tb.pct - ta.pct || byName(a, b);
      if (ta) return -1;
      if (tb) return 1;
      return byName(a, b);
    });
  }

  function render() {
    const p = state.payload;
    if (!p) return;
    const all = p.players || [];
    renderKpis(all);
    renderSpotlight(all);

    const q = state.filter.trim().toLowerCase();
    const filtered = all.filter((row) => {
      if (q && !String(row.name || "").toLowerCase().includes(q)) return false;
      if (state.chip === "close") {
        const t = nextTrigger(row);
        return !!t && t.remaining <= CLOSE_WITHIN;
      }
      if (state.chip === "milestones") return milestoneClauses(row).length > 0;
      if (state.chip === "met") return metCount(row) > 0;
      return true;
    });
    els.playerRows.innerHTML = sortPlayers(filtered).map(playerCard).join("")
      || `<div class="bt-empty">No players match this filter.</div>`;

    els.matchdayRows.innerHTML = (p.matchday || []).map((row) => `
      <tr>
        <td class="bt-date">${esc(row.date)}</td>
        <td class="bt-strong">${esc(row.player_name)}</td>
        <td>${esc(row.opponent)}${row.result ? ` <span class="bt-res">${esc(row.result)}</span>` : ""}</td>
        <td><span class="bt-tag">${esc(typeLabel(row.bonus_type))}</span></td>
        <td class="num bt-strong">${row.amount != null ? `£${esc(row.amount)}` : "—"}</td>
        <td>
          <label class="bt-toggle">
            <input type="checkbox" data-paid="${esc(row.id)}" ${row.paid ? "checked" : ""} />
            <span>${row.paid ? "Paid" : "Unpaid"}</span>
          </label>
          ${row.tracking ? `<div class="bt-meta">${esc(row.tracking)}</div>` : ""}
        </td>
        <td class="num"><button type="button" class="bt-linkbtn" data-delete="${esc(row.id)}">Delete</button></td>
      </tr>
    `).join("") || `<tr><td colspan="7" class="bt-empty-cell">No matchday bonuses logged yet. Use <strong>+ Log a bonus</strong> after a game.</td></tr>`;

    els.bonusPlayer.innerHTML = all.map((row) =>
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
      setStatus(`Season ${state.payload.season} · League Two starts, apps and minutes (added time included) against every contract trigger.`);
      render();
    } catch (err) {
      setStatus(`Could not load: ${err.message}`, true);
    }
  }

  document.querySelectorAll(".bt-tab").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });
  document.querySelectorAll(".bt-fchip").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.chip = btn.dataset.filter;
      document.querySelectorAll(".bt-fchip").forEach((el) => el.classList.toggle("is-active", el === btn));
      render();
    });
  });
  els.sortBy.addEventListener("change", () => {
    state.sort = els.sortBy.value;
    render();
  });
  els.playerFilter.addEventListener("input", () => {
    state.filter = els.playerFilter.value;
    render();
  });
  els.spotlight.addEventListener("click", (event) => {
    const card = event.target.closest("[data-jump]");
    if (!card) return;
    const target = document.getElementById(`player-${card.dataset.jump}`);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("is-flash");
    void target.offsetWidth;
    target.classList.add("is-flash");
  });
  document.getElementById("reseedBtn").addEventListener("click", async () => {
    setStatus("Reloading provisions…");
    const res = await fetch("/api/bonus-tracker/reseed", { method: "POST", credentials: "same-origin" });
    if (!res.ok) return setStatus(`Reload failed: HTTP ${res.status}`, true);
    state.payload = await res.json();
    setStatus("Provisions reloaded (existing players kept; new names added).");
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
