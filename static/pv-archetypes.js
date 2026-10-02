(() => {
  "use strict";

  const WATCH_STAGE = "watch_list";
  const WATCH_TAG = "Watching";
  const BLEND_COLOURS = ["#f5c518", "#3d8bfd", "#34d399", "#f97316", "#a78bfa"];
  const STORE_KEY = "pv-archetypes:v1";
  // Second 8 and second striker in the 3-5-2 start as a complementary type,
  // not a copy of the first.
  const DEFAULT_SLOT_ARCH = {
    "352": { l8: "eight-running", r8: "eight-creative", l9: "nine-runner", r9: "nine-target", six: "six-winner" },
    "343": { six: "six-winner", eight: "eight-running", nine: "nine-presser" },
  };

  const $ = (id) => document.getElementById(id);

  const state = {
    config: null,
    pool: [],
    leagues: [],
    formation: "352",
    view: "pitch",
    slot: "six",
    slotArch: {},
    tuned: {},
    filters: { leagues: new Set(), minMinutes: 270, maxAge: null, hideMoved: true, footStrict: false },
    watch: new Map(),
    watchBusy: new Set(),
    editing: false,
    rankCache: new Map(),
  };

  // ---------------------------------------------------------------- helpers
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function fetchJson(url, opts = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...opts });
    if (!res.ok) {
      let detail = `${res.status}`;
      try { detail = (await res.json()).detail || detail; } catch { /* plain text */ }
      throw new Error(detail);
    }
    return res.json();
  }

  function toast(message, isError = false) {
    const el = $("toast");
    el.textContent = message;
    el.classList.toggle("is-error", isError);
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 2800);
  }

  function initials(name) {
    return String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  }

  function surname(name) {
    const parts = String(name || "").trim().split(/\s+/);
    return parts.length > 1 ? parts.slice(1).join(" ") : parts[0] || "";
  }

  function fitClass(fit) {
    if (fit >= 85) return "elite";
    if (fit >= 75) return "strong";
    if (fit >= 65) return "good";
    return "low";
  }

  function isPortVale(player) {
    return /port vale/i.test(String(player.club || ""));
  }

  function persist() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        formation: state.formation,
        slotArch: state.slotArch,
        filters: { ...state.filters, leagues: [...state.filters.leagues] },
      }));
    } catch { /* private mode */ }
  }

  function restore() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
      if (raw.formation) state.formation = raw.formation;
      if (raw.slotArch && typeof raw.slotArch === "object") state.slotArch = raw.slotArch;
      if (raw.filters) {
        const f = raw.filters;
        state.filters.minMinutes = Number.isFinite(f.minMinutes) ? f.minMinutes : 270;
        state.filters.maxAge = Number.isFinite(f.maxAge) ? f.maxAge : null;
        state.filters.hideMoved = f.hideMoved !== false;
        state.filters.footStrict = !!f.footStrict;
        if (Array.isArray(f.leagues)) state.filters.leagues = new Set(f.leagues);
      }
    } catch { /* ignore */ }
  }

  // ---------------------------------------------------------------- model
  function roles() { return state.config?.roles || []; }
  function roleById(id) { return roles().find((r) => r.id === id) || null; }
  function archById(id) {
    for (const role of roles()) {
      const hit = role.archetypes.find((a) => a.id === id);
      if (hit) return hit;
    }
    return null;
  }
  function formation() {
    return (state.config?.formations || []).find((f) => f.id === state.formation) || state.config?.formations?.[0];
  }
  function slotDef(slotId) { return formation()?.slots.find((s) => s.slot === slotId) || null; }

  function archForSlot(slotId) {
    const slot = slotDef(slotId);
    if (!slot) return null;
    const role = roleById(slot.role);
    if (!role) return null;
    const chosen = state.slotArch[state.formation]?.[slotId] || DEFAULT_SLOT_ARCH[state.formation]?.[slotId];
    return role.archetypes.find((a) => a.id === chosen) || role.archetypes[0];
  }

  function setArchForSlot(slotId, archId) {
    state.slotArch[state.formation] = { ...(state.slotArch[state.formation] || {}), [slotId]: archId };
    persist();
  }

  function weightsFor(arch) { return state.tuned[arch.id] || arch.weights; }
  function isTuned(arch) { return !!state.tuned[arch.id]; }

  function fitFor(scores, weights) {
    let total = 0;
    let sum = 0;
    for (const [name, w] of Object.entries(weights)) {
      if (!(w > 0)) continue;
      const v = scores[name];
      if (v == null) return null;
      total += v * w;
      sum += w;
    }
    return sum > 0 ? Math.round((total / sum) * 10) / 10 : null;
  }

  function passesFilters(player, arch) {
    const f = state.filters;
    if ((player.minutes || 0) < f.minMinutes) return false;
    if (f.maxAge != null && player.age != null && player.age > f.maxAge) return false;
    if (f.leagues.size && !f.leagues.has(player.league)) return false;
    if (f.hideMoved && player.transfer?.status === "gone") return false;
    if (f.footStrict && arch.foot && player.foot !== arch.foot && player.foot !== "Both") return false;
    return true;
  }

  /** Ranked fits for an archetype; Port Vale players are kept apart. */
  function rank(arch) {
    const key = `${arch.id}|${JSON.stringify(weightsFor(arch))}`;
    if (state.rankCache.has(key)) return state.rankCache.get(key);
    const sources = new Set(arch.sources);
    const weights = weightsFor(arch);
    const best = new Map();
    const vale = new Map();
    for (const p of state.pool) {
      if (!sources.has(p.position)) continue;
      const pv = isPortVale(p);
      if (pv) {
        if ((p.minutes || 0) < 45) continue;
      } else if (!passesFilters(p, arch)) {
        continue;
      }
      const fit = fitFor(p.scores, weights);
      if (fit == null) continue;
      const bucket = pv ? vale : best;
      const id = p.playerId || p.name;
      const prev = bucket.get(id);
      if (prev && prev.fit >= fit) continue;
      bucket.set(id, { ...p, fit });
    }
    const out = {
      list: [...best.values()].sort((a, b) => b.fit - a.fit),
      vale: [...vale.values()].sort((a, b) => b.fit - a.fit),
    };
    state.rankCache.set(key, out);
    return out;
  }

  function invalidate() { state.rankCache.clear(); }

  /** Pool's best XI for the formation — no player picked twice. */
  function bestXi() {
    const used = new Set();
    const xi = {};
    for (const slot of formation()?.slots || []) {
      const arch = archForSlot(slot.slot);
      if (!arch) continue;
      const pick = rank(arch).list.find((p) => !used.has(p.playerId));
      if (pick) used.add(pick.playerId);
      xi[slot.slot] = { arch, player: pick || null };
    }
    return xi;
  }

  // ---------------------------------------------------------------- header + filters
  function renderFormationSeg() {
    const seg = $("formationSeg");
    seg.innerHTML = (state.config.formations || []).map((f) =>
      `<button type="button" class="seg__btn${f.id === state.formation ? " is-active" : ""}" data-formation="${esc(f.id)}">${esc(f.label)}</button>`
    ).join("");
    $("formationNote").textContent = formation()?.note || "";
  }

  function renderLeagueChips() {
    const chips = $("leagueChips");
    const all = state.filters.leagues.size === 0;
    chips.innerHTML =
      `<button type="button" class="chip${all ? " is-on" : ""}" data-league="">All</button>` +
      state.leagues.map((l) =>
        `<button type="button" class="chip${state.filters.leagues.has(l) ? " is-on" : ""}" data-league="${esc(l)}">${esc(l)}</button>`
      ).join("");
  }

  function syncFilterInputs() {
    $("minMinutes").value = state.filters.minMinutes;
    $("maxAge").value = state.filters.maxAge ?? "";
    $("hideMoved").checked = state.filters.hideMoved;
    $("footStrict").checked = state.filters.footStrict;
  }

  // ---------------------------------------------------------------- pitch
  function renderPitch() {
    const layer = $("slotLayer");
    const xi = bestXi();
    layer.innerHTML = (formation()?.slots || []).map((slot) => {
      const role = roleById(slot.role);
      const pick = xi[slot.slot] || {};
      const player = pick.player;
      return `
        <button type="button" class="slot${slot.slot === state.slot ? " is-active" : ""}" data-slot="${esc(slot.slot)}"
          style="left:${slot.x}%;top:${100 - slot.y}%"
          title="${esc(role?.name || "")} — ${esc(pick.arch?.name || "")}${player ? `\nBest fit: ${esc(player.name)} (${esc(player.club)}) ${player.fit.toFixed(1)}` : ""}">
          <span class="slot__disc" data-short="${esc(role?.short || "")}">${esc(role?.number || "")}</span>
          <span class="slot__arch">${esc(pick.arch?.name || "")}</span>
          <span class="slot__player">${player ? `${esc(surname(player.name))}<span class="slot__fit">${player.fit.toFixed(1)}</span>` : "—"}</span>
        </button>`;
    }).join("");
  }

  // ---------------------------------------------------------------- role panel
  function listHtml(items) {
    return `<ul>${(items || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  }

  function starsHtml(n) {
    return Array.from({ length: 5 }, (_, i) => `<span class="${i < n ? "" : "off"}">★</span>`).join("");
  }

  function blendParts(arch) {
    const weights = weightsFor(arch);
    const total = Object.values(weights).reduce((s, w) => s + (w > 0 ? w : 0), 0) || 1;
    return arch.profiles.map((p, i) => ({
      ...p,
      colour: BLEND_COLOURS[i % BLEND_COLOURS.length],
      weight: weights[p.apiName] || 0,
      pct: Math.round(((weights[p.apiName] || 0) / total) * 100),
    }));
  }

  function renderRolePanel() {
    const panel = $("rolePanel");
    const slot = slotDef(state.slot) || formation()?.slots[0];
    if (!slot) { panel.innerHTML = ""; return; }
    state.slot = slot.slot;
    const role = roleById(slot.role);
    const arch = archForSlot(slot.slot);

    panel.innerHTML = `
      <div class="card role-hero">
        <div class="role-hero__num">${esc(role.number)}</div>
        <div>
          <p class="role-hero__eyebrow">${esc(role.nickname)}</p>
          <h2 class="role-hero__name">${esc(role.name)}</h2>
          <p class="role-hero__summary">${esc(role.summary)}</p>
        </div>
        <div class="importance">
          <div class="importance__label">Importance</div>
          <div class="importance__stars">${starsHtml(role.importance)}</div>
        </div>
      </div>

      <div class="role-grid">
        <div class="card role-box role-box--why"><h3>⚡ Why it matters in our system</h3><p>${esc(role.importance_note)}</p></div>
        <div class="card role-box"><h3>⚽ In possession</h3>${listHtml(role.in_possession)}</div>
        <div class="card role-box role-box--off"><h3>🛡️ Out of possession</h3>${listHtml(role.out_of_possession)}</div>
        <div class="card role-box role-box--req"><h3>📋 Requirements</h3>${listHtml(role.requirements)}</div>
      </div>

      <p class="section-title">Archetypes — which ${esc(role.name.toLowerCase())} do we want here?</p>
      <div class="arch-tabs" id="archTabs"></div>

      <div class="card arch-detail" id="archDetail"></div>

      <div class="card board">
        <div class="board__head">
          <h3 class="board__title">Best fits — ${esc(arch.name)}</h3>
          <span class="board__meta" id="lbMeta"></span>
        </div>
        <div id="lbBody"></div>
        <div class="pv-fit" id="pvFit"></div>
      </div>

      <div id="editMount"></div>
    `;
    renderArchTabs(role, arch);
    renderArchDetail(arch);
    renderLeaderboard(arch);
    if (state.editing) renderEditCard(role);
  }

  function renderArchTabs(role, activeArch) {
    $("archTabs").innerHTML = role.archetypes.map((a) => {
      const top = rank(a).list[0];
      return `
        <button type="button" class="arch-tab${a.id === activeArch.id ? " is-active" : ""}" data-arch="${esc(a.id)}">
          <span class="arch-tab__name">${esc(a.name)}</span>
          <span class="arch-tab__tag">${esc(a.tagline)}</span>
          <span class="arch-tab__top">${top ? `<span>${esc(top.name)}</span><b>${top.fit.toFixed(1)}</b>` : "<span>No fits</span>"}</span>
        </button>`;
    }).join("");
  }

  function renderArchDetail(arch) {
    const parts = blendParts(arch);
    const foot = arch.foot === "L" ? "Left-footed preferred" : arch.foot === "R" ? "Right-footed preferred" : "";
    $("archDetail").innerHTML = `
      <div>
        <h3 class="arch-detail__name">${esc(arch.name)}</h3>
        <p class="arch-detail__tag">${esc(arch.tagline)}</p>
        <p class="arch-detail__desc">${esc(arch.description)}</p>
        <div class="traits">${(arch.traits || []).map((t) => `<span class="trait">${esc(t)}</span>`).join("")}</div>
        <p class="arch-detail__src">Ranked from Impect <b>${esc(arch.sourceLabels.join(" + "))}</b> profiles${foot ? ` · ${esc(foot)}` : ""}.</p>
      </div>
      <div class="blend">
        <p class="blend__title">
          <span>Profile blend ${isTuned(arch) ? '<span class="blend__tuned">· tuned</span>' : ""}</span>
          <span>
            ${isTuned(arch) ? '<button type="button" class="btn btn--small btn--ghost" data-action="reset-blend">Reset</button>' : ""}
            ${isTuned(arch) && state.config.can_edit ? '<button type="button" class="btn btn--small btn--gold" data-action="save-blend">Save as default</button>' : ""}
          </span>
        </p>
        <div class="blend__bar" id="blendBar">${parts.map((p) => `<div class="blend__seg" style="width:${p.pct}%;background:${p.colour}" title="${esc(p.label)} ${p.pct}%"></div>`).join("")}</div>
        <div class="blend__rows">
          ${parts.map((p) => `
            <div class="blend__row">
              <span class="blend__dot" style="background:${p.colour}"></span>
              <span>${esc(p.label)}</span>
              <span class="blend__pct" data-pct="${esc(p.apiName)}">${p.pct}%</span>
              <input type="range" min="0" max="10" step="1" value="${p.weight}" data-weight="${esc(p.apiName)}" aria-label="${esc(p.label)} weight" />
            </div>`).join("")}
        </div>
      </div>`;
  }

  function updateBlendVisual(arch) {
    const parts = blendParts(arch);
    const bar = $("blendBar");
    if (bar) bar.innerHTML = parts.map((p) => `<div class="blend__seg" style="width:${p.pct}%;background:${p.colour}"></div>`).join("");
    for (const p of parts) {
      const el = document.querySelector(`[data-pct="${CSS.escape(p.apiName)}"]`);
      if (el) el.textContent = `${p.pct}%`;
    }
  }

  function transferFlag(p) {
    const t = p.transfer;
    if (!t) return "";
    if (t.status === "gone") return `<span class="flag flag--gone" title="Moved${t.to ? ` to ${esc(t.to)}` : ""}">Moved</span>`;
    if (t.status === "loan_in" || t.status === "loan_out") return `<span class="flag flag--loan" title="${t.from ? `On loan from ${esc(t.from)}` : "Loan"}">Loan</span>`;
    return "";
  }

  function watchButton(p) {
    const tracked = state.watch.get(p.playerId);
    if (tracked) {
      const label = tracked.stage === WATCH_STAGE ? "✓ Watching" : "✓ Pipeline";
      return `<button type="button" class="btn btn--small is-on" disabled>${label}</button>`;
    }
    return `<button type="button" class="btn btn--small" data-watch="${esc(p.playerId)}">+ Watch</button>`;
  }

  function renderLeaderboard(arch) {
    const { list, vale } = rank(arch);
    const parts = blendParts(arch).filter((p) => p.weight > 0);
    const top = list.slice(0, 10);
    const f = state.filters;
    const bits = [`${list.length} qualify`, `${f.minMinutes}+ mins`];
    if (f.maxAge != null) bits.push(`U${f.maxAge + 1}`);
    if (f.leagues.size) bits.push([...f.leagues].join(", "));
    $("lbMeta").textContent = bits.join(" · ");

    $("lbBody").innerHTML = top.length ? top.map((p, i) => {
      const footOff = arch.foot && p.foot && p.foot !== arch.foot && p.foot !== "Both" && p.foot !== "—";
      return `
        <div class="lb-row is-podium-${i + 1}">
          <span class="lb-rank">${i + 1}</span>
          <span class="avatar">${esc(initials(p.name))}</span>
          <div>
            <a class="lb-name" href="/player/${encodeURIComponent(p.playerId)}" target="_blank" rel="noopener">${esc(p.name)}</a>
            ${transferFlag(p)}${footOff ? `<span class="flag flag--foot" title="Preferred foot for this role is ${arch.foot === "L" ? "left" : "right"}">${esc(p.foot)} foot</span>` : ""}
            <div class="lb-sub">${p.age ?? "—"} yrs · ${esc(p.club)} · ${esc(p.league)} · ${Math.round(p.minutes || 0)} mins</div>
          </div>
          <div class="bars">
            ${parts.map((b) => {
              const v = p.scores[b.apiName];
              return `<div class="bar"><span>${esc(b.label)}</span><span class="bar__track"><span class="bar__fill" style="width:${Math.max(0, Math.min(100, v || 0))}%;background:${b.colour}"></span></span><span class="bar__val">${v != null ? Math.round(v) : "—"}</span></div>`;
            }).join("")}
          </div>
          <div class="fit fit--${fitClass(p.fit)}">${p.fit.toFixed(1)}<span class="fit__label">Fit</span></div>
          ${watchButton(p)}
        </div>`;
    }).join("") : `<p class="lb-empty">No players match these filters for this archetype. Lower the minutes or widen the leagues.</p>`;

    const leader = top[0];
    $("pvFit").innerHTML = `
      <p class="pv-fit__title">Port Vale's current best fits</p>
      <div class="pv-fit__list">
        ${vale.length ? vale.slice(0, 4).map((p) => `
          <div class="pv-chip"><span class="flag flag--pv">PV</span><a href="/player/${encodeURIComponent(p.playerId)}" target="_blank" rel="noopener">${esc(p.name)}</a>
            <b>${p.fit.toFixed(1)}</b>${leader ? `<span class="gap">${(p.fit - leader.fit).toFixed(1)} vs #1</span>` : ""}</div>`).join("")
          : '<span class="pv-chip">No Port Vale minutes in this position yet.</span>'}
      </div>`;
  }

  // ---------------------------------------------------------------- edit mode
  function renderEditCard(role) {
    const mount = $("editMount");
    const lines = (arr) => esc((arr || []).join("\n"));
    mount.innerHTML = `
      <div class="card edit-card">
        <h3>Edit position book — ${esc(role.name)}</h3>
        <div class="edit-grid">
          <label class="edit-field">Position name<input data-f="name" value="${esc(role.name)}" /></label>
          <label class="edit-field">Nickname<input data-f="nickname" value="${esc(role.nickname)}" /></label>
          <label class="edit-field">Importance
            <select data-f="importance">${[1, 2, 3, 4, 5].map((n) => `<option value="${n}"${n === role.importance ? " selected" : ""}>${n} ★</option>`).join("")}</select>
          </label>
          <span></span>
          <label class="edit-field edit-field--wide">Summary<textarea rows="2" data-f="summary">${esc(role.summary)}</textarea></label>
          <label class="edit-field edit-field--wide">Why it matters<textarea rows="3" data-f="importance_note">${esc(role.importance_note)}</textarea></label>
          <label class="edit-field">In possession (one per line)<textarea rows="4" data-f="in_possession">${lines(role.in_possession)}</textarea></label>
          <label class="edit-field">Out of possession (one per line)<textarea rows="4" data-f="out_of_possession">${lines(role.out_of_possession)}</textarea></label>
          <label class="edit-field edit-field--wide">Requirements (one per line)<textarea rows="4" data-f="requirements">${lines(role.requirements)}</textarea></label>
        </div>
        ${role.archetypes.map((a) => `
          <h3>Archetype — ${esc(a.name)}</h3>
          <div class="edit-grid" data-arch-edit="${esc(a.id)}">
            <label class="edit-field">Name<input data-a="name" value="${esc(a.name)}" /></label>
            <label class="edit-field">Tagline<input data-a="tagline" value="${esc(a.tagline)}" /></label>
            <label class="edit-field edit-field--wide">Description<textarea rows="2" data-a="description">${esc(a.description)}</textarea></label>
            <label class="edit-field edit-field--wide">Traits (comma separated)<input data-a="traits" value="${esc((a.traits || []).join(", "))}" /></label>
          </div>`).join("")}
        <div class="edit-actions">
          <span class="edit-actions__meta">${state.config.saved_at ? `Last saved ${esc(new Date(state.config.saved_at).toLocaleString("en-GB"))}${state.config.saved_by ? ` by ${esc(state.config.saved_by)}` : ""}` : "Using the default position book."} Blends tuned with the sliders are saved too.</span>
          <button type="button" class="btn btn--ghost" data-action="cancel-edit">Cancel</button>
          <button type="button" class="btn btn--gold" data-action="save-edit">Save</button>
        </div>
      </div>`;
  }

  async function saveConfig(body, message) {
    try {
      const res = await fetchJson("/api/pv-archetypes/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      state.config.roles = res.roles;
      state.config.saved_at = res.saved_at;
      for (const id of Object.keys(body.archetypes || {})) delete state.tuned[id];
      invalidate();
      toast(message);
      return true;
    } catch (err) {
      toast(`Save failed: ${err.message}`, true);
      return false;
    }
  }

  async function saveEdit() {
    const role = roleById(slotDef(state.slot).role);
    const mount = $("editMount");
    const roleEdit = {};
    mount.querySelectorAll("[data-f]").forEach((el) => {
      const f = el.dataset.f;
      if (["in_possession", "out_of_possession", "requirements"].includes(f)) {
        roleEdit[f] = el.value.split("\n").map((s) => s.trim()).filter(Boolean);
      } else if (f === "importance") {
        roleEdit[f] = Number(el.value);
      } else {
        roleEdit[f] = el.value;
      }
    });
    const archetypes = {};
    mount.querySelectorAll("[data-arch-edit]").forEach((grid) => {
      const id = grid.dataset.archEdit;
      const edit = {};
      grid.querySelectorAll("[data-a]").forEach((el) => {
        edit[el.dataset.a] = el.dataset.a === "traits" ? el.value.split(",").map((s) => s.trim()).filter(Boolean) : el.value;
      });
      if (state.tuned[id]) edit.weights = state.tuned[id];
      archetypes[id] = edit;
    });
    const ok = await saveConfig({ roles: { [role.id]: roleEdit }, archetypes }, `${role.name} saved.`);
    if (ok) {
      state.editing = false;
      $("editBtn").textContent = "Edit position book";
      renderAll();
    }
  }

  // ---------------------------------------------------------------- board view
  function renderBoard() {
    const seen = new Set();
    const html = [];
    for (const slot of formation()?.slots || []) {
      if (seen.has(slot.role)) continue;
      seen.add(slot.role);
      const role = roleById(slot.role);
      if (!role) continue;
      html.push(`
        <section class="card bv-role">
          <div class="bv-role__head">
            <span class="bv-role__num">${esc(role.number)}</span>
            <h2 class="bv-role__name">${esc(role.name)}</h2>
            <span class="bv-role__nick">${esc(role.nickname)}</span>
            <span class="importance__stars">${starsHtml(role.importance)}</span>
            <button type="button" class="btn btn--small btn--ghost bv-role__open" data-open-slot="${esc(slot.slot)}">Open role →</button>
          </div>
          <div class="bv-grid">
            ${role.archetypes.map((a) => {
              const parts = blendParts(a);
              const list = rank(a).list.slice(0, 5);
              return `
                <div class="bv-arch">
                  <p class="bv-arch__name">${esc(a.name)}</p>
                  <p class="bv-arch__tag">${esc(a.tagline)}</p>
                  <div class="bv-mini-bar">${parts.map((p) => `<span style="width:${p.pct}%;background:${p.colour}" title="${esc(p.label)} ${p.pct}%"></span>`).join("")}</div>
                  ${list.length ? list.map((p, i) => `
                    <div class="bv-pl">
                      <span class="bv-pl__rank">${i + 1}</span>
                      <span><a href="/player/${encodeURIComponent(p.playerId)}" target="_blank" rel="noopener">${esc(p.name)}</a>${transferFlag(p)}
                        <span class="bv-pl__club">${p.age ?? "—"} · ${esc(p.club)}</span></span>
                      <span class="bv-pl__fit fit--${fitClass(p.fit)}" style="background:none">${p.fit.toFixed(1)}</span>
                    </div>`).join("") : '<p class="bv-arch__tag">No fits with these filters.</p>'}
                </div>`;
            }).join("")}
          </div>
        </section>`);
    }
    $("boardView").innerHTML = html.join("");
  }

  // ---------------------------------------------------------------- render
  function renderAll() {
    renderFormationSeg();
    renderLeagueChips();
    const pitch = state.view === "pitch";
    $("pitchView").hidden = !pitch;
    $("boardView").hidden = pitch;
    document.querySelectorAll("#viewSeg .seg__btn").forEach((b) => b.classList.toggle("is-active", b.dataset.view === state.view));
    if (pitch) {
      renderPitch();
      renderRolePanel();
    } else {
      renderBoard();
    }
    const qualifying = state.pool.filter((p) => !isPortVale(p) && (p.minutes || 0) >= state.filters.minMinutes).length;
    $("poolMeta").textContent = state.pool.length
      ? `${qualifying.toLocaleString()} player-positions over ${state.filters.minMinutes} mins · Fit = weighted blend of PV Impect profile scores`
      : "Player pool unavailable";
    history.replaceState(null, "", `#${state.formation}/${state.slot}`);
  }

  function onFiltersChanged() {
    invalidate();
    persist();
    renderAll();
  }

  // ---------------------------------------------------------------- events
  function bind() {
    $("formationSeg").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-formation]");
      if (!btn) return;
      state.formation = btn.dataset.formation;
      if (!slotDef(state.slot)) state.slot = "six";
      persist();
      renderAll();
    });

    $("viewSeg").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-view]");
      if (!btn) return;
      state.view = btn.dataset.view;
      renderAll();
    });

    $("leagueChips").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-league]");
      if (!btn) return;
      const league = btn.dataset.league;
      if (!league) state.filters.leagues.clear();
      else if (state.filters.leagues.has(league)) state.filters.leagues.delete(league);
      else state.filters.leagues.add(league);
      onFiltersChanged();
    });

    $("minMinutes").addEventListener("change", (e) => {
      state.filters.minMinutes = Math.max(0, Number(e.target.value) || 0);
      onFiltersChanged();
    });
    $("maxAge").addEventListener("change", (e) => {
      const v = Number(e.target.value);
      state.filters.maxAge = e.target.value === "" || !Number.isFinite(v) ? null : v;
      onFiltersChanged();
    });
    $("hideMoved").addEventListener("change", (e) => { state.filters.hideMoved = e.target.checked; onFiltersChanged(); });
    $("footStrict").addEventListener("change", (e) => { state.filters.footStrict = e.target.checked; onFiltersChanged(); });

    $("slotLayer").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-slot]");
      if (!btn) return;
      state.slot = btn.dataset.slot;
      renderAll();
      if (window.innerWidth < 1100) $("rolePanel").scrollIntoView({ behavior: "smooth" });
    });

    $("boardView").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-open-slot]");
      if (!btn) return;
      state.slot = btn.dataset.openSlot;
      state.view = "pitch";
      renderAll();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });

    const panel = $("rolePanel");
    panel.addEventListener("click", (e) => {
      const tab = e.target.closest("[data-arch]");
      if (tab) {
        setArchForSlot(state.slot, tab.dataset.arch);
        renderAll();
        return;
      }
      const watch = e.target.closest("[data-watch]");
      if (watch) { addToWatch(Number(watch.dataset.watch)); return; }
      const action = e.target.closest("[data-action]")?.dataset.action;
      const arch = archForSlot(state.slot);
      if (action === "reset-blend") {
        delete state.tuned[arch.id];
        invalidate();
        renderAll();
      } else if (action === "save-blend") {
        saveConfig({ archetypes: { [arch.id]: { weights: state.tuned[arch.id] } } }, `${arch.name} blend saved as default.`).then((ok) => ok && renderAll());
      } else if (action === "save-edit") {
        saveEdit();
      } else if (action === "cancel-edit") {
        state.editing = false;
        $("editBtn").textContent = "Edit position book";
        renderAll();
      }
    });

    let raf = 0;
    panel.addEventListener("input", (e) => {
      const slider = e.target.closest("[data-weight]");
      if (!slider) return;
      const arch = archForSlot(state.slot);
      const wasTuned = isTuned(arch);
      const weights = { ...weightsFor(arch), [slider.dataset.weight]: Number(slider.value) };
      if (!Object.values(weights).some((w) => w > 0)) { slider.value = 1; weights[slider.dataset.weight] = 1; }
      state.tuned[arch.id] = weights;
      updateBlendVisual(arch);
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        renderLeaderboard(arch);
        renderArchTabs(roleById(slotDef(state.slot).role), arch);
        renderPitch();
      });
      // The Reset / Save buttons appear on the first nudge; rebuild once, not per tick.
      if (!wasTuned) slider.addEventListener("change", () => renderArchDetail(arch), { once: true });
    });

    $("editBtn").addEventListener("click", () => {
      state.editing = !state.editing;
      $("editBtn").textContent = state.editing ? "Close editor" : "Edit position book";
      if (state.view !== "pitch") state.view = "pitch";
      renderAll();
      if (state.editing) $("editMount")?.scrollIntoView({ behavior: "smooth" });
    });
  }

  async function addToWatch(pid) {
    if (!pid || state.watchBusy.has(pid)) return;
    const player = state.pool.find((p) => p.playerId === pid);
    if (!player) return;
    const arch = archForSlot(state.slot);
    const fit = rank(arch).list.find((p) => p.playerId === pid)?.fit ?? null;
    state.watchBusy.add(pid);
    try {
      const data = await fetchJson("/api/player-pipelines/targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          player_id: pid,
          name: player.name,
          club: player.club || "",
          league: player.league || "",
          position: player.position || "",
          position_label: roleById(slotDef(state.slot).role)?.name || "",
          age: player.age ?? null,
          stage: WATCH_STAGE,
          tags: [WATCH_TAG, arch.name],
          overall_score: fit,
          minutes: player.minutes ?? null,
          top_profile: arch.name,
          top_profile_score: fit,
          enrich: false,
        }),
      });
      const target = data.target || {};
      state.watch.set(pid, { id: String(target.id || ""), stage: String(target.stage || WATCH_STAGE) });
      toast(`${player.name} added to the Watch list as ${arch.name}.`);
      renderLeaderboard(arch);
    } catch (err) {
      toast(`Could not add to Watch list: ${err.message}`, true);
    } finally {
      state.watchBusy.delete(pid);
    }
  }

  async function loadWatch() {
    try {
      const data = await fetchJson("/api/player-pipelines/track-index");
      for (const row of data.targets || []) state.watch.set(Number(row.player_id), { id: row.id, stage: row.stage });
    } catch { /* watch chips are optional */ }
  }

  function readHash() {
    const [f, s] = location.hash.replace(/^#/, "").split("/");
    if (f && (state.config.formations || []).some((x) => x.id === f)) state.formation = f;
    if (s) state.slot = s;
    if (!slotDef(state.slot)) state.slot = "six";
  }

  async function loadPool() {
    const banner = $("statusBanner");
    try {
      const data = await fetchJson("/api/pv-archetypes/pool");
      if (data.building) {
        banner.hidden = false;
        banner.classList.remove("is-error");
        banner.textContent = data.message || "The recruitment pool is rebuilding — retrying in 30 seconds.";
        setTimeout(loadPool, 30000);
        return;
      }
      banner.hidden = true;
      state.pool = data.players || [];
      state.leagues = data.leagues || [];
      for (const l of [...state.filters.leagues]) if (!state.leagues.includes(l)) state.filters.leagues.delete(l);
      invalidate();
      renderAll();
    } catch (err) {
      banner.hidden = false;
      banner.classList.add("is-error");
      banner.textContent = `Could not load the player pool: ${err.message}`;
    }
  }

  async function boot() {
    restore();
    syncFilterInputs();
    bind();
    try {
      state.config = await fetchJson("/api/pv-archetypes/config");
    } catch (err) {
      $("rolePanel").innerHTML = `<div class="card empty-card">Could not load the position book: ${esc(err.message)}</div>`;
      return;
    }
    $("editBtn").hidden = !state.config.can_edit;
    readHash();
    renderAll();
    await Promise.all([loadWatch(), loadPool()]);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
