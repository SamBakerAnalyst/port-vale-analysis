(() => {
  "use strict";

  const els = {
    counts: document.getElementById("rlCounts"),
    kinds: document.getElementById("rlKinds"),
    search: document.getElementById("rlSearch"),
    position: document.getElementById("rlPosition"),
    level: document.getElementById("rlLevel"),
    action: document.getElementById("rlAction"),
    scout: document.getElementById("rlScout"),
    sort: document.getElementById("rlSort"),
    status: document.getElementById("rlStatus"),
    list: document.getElementById("rlList"),
    detail: document.getElementById("rlDetail"),
  };

  const state = {
    reports: [],
    counts: {},
    options: {},
    kind: "",
    query: "",
    position: "",
    level: "",
    action: "",
    scout: "",
    sort: "recent",
    selected: "",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function fetchJson(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.message || `HTTP ${res.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function setStatus(message, tone) {
    els.status.textContent = message || "";
    els.status.className = `rl-status${message ? "" : " hidden"}${tone ? ` ${tone}` : ""}`;
  }

  function formatDate(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  function formatDateTime(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function monthKey(iso) {
    const date = new Date(iso || "");
    if (Number.isNaN(date.getTime())) return "Undated";
    return date.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  }

  function kindLabel(kind) {
    return kind === "detailed" ? "Detailed" : "General";
  }

  function fillSelect(select, rows, allLabel) {
    const current = select.value;
    select.innerHTML = `<option value="">${escapeHtml(allLabel)}</option>${rows
      .map((row) => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.label)}</option>`)
      .join("")}`;
    if (rows.some((row) => row.id === current)) select.value = current;
  }

  function renderFilters() {
    const opts = state.options || {};
    fillSelect(
      els.position,
      (opts.positions || []).map((row) => ({ id: row.id, label: `${row.short} · ${row.label}` })),
      "All positions",
    );
    fillSelect(
      els.level,
      (opts.pvfc_levels || []).map((row) => ({ id: row.id, label: `${row.id} · ${row.label}` })),
      "All levels",
    );
    fillSelect(els.action, opts.next_actions || [], "All next actions");
    const scouts = [...new Set(state.reports.map((row) => row.scout).filter(Boolean))].sort((a, b) =>
      a.localeCompare(b),
    );
    fillSelect(els.scout, scouts.map((name) => ({ id: name, label: name })), "All scouts");
    els.position.value = state.position;
    els.level.value = state.level;
    els.action.value = state.action;
    els.scout.value = state.scout;
    els.sort.value = state.sort;
    els.search.value = state.query;
  }

  function renderKinds() {
    const c = state.counts || {};
    const n = { "": c.total || 0, general: c.general || 0, detailed: c.detailed || 0 };
    els.kinds.querySelectorAll("[data-kind]").forEach((btn) => {
      const kind = btn.dataset.kind;
      btn.classList.toggle("is-on", kind === state.kind);
      const label = kind === "" ? "All reports" : kindLabel(kind);
      btn.innerHTML = `${label}<span class="rl-chip__n">${n[kind]}</span>`;
    });
    els.counts.textContent = c.total
      ? `${c.total} report${c.total === 1 ? "" : "s"} on ${c.players} player${c.players === 1 ? "" : "s"} · ${c.general} general · ${c.detailed} detailed`
      : "No reports filed yet. File general or detailed reports in Match Scouting and they appear here.";
  }

  function filtered() {
    const q = state.query.trim().toLowerCase();
    const rows = state.reports.filter((row) => {
      if (state.kind && row.kind !== state.kind) return false;
      if (state.position && row.position_in_game !== state.position) return false;
      if (state.level && row.pvfc_level !== state.level) return false;
      if (state.action && row.next_action !== state.action) return false;
      if (state.scout && row.scout !== state.scout) return false;
      if (!q) return true;
      return [row.name, row.club, row.league, row.fixture_label, row.scout, row.updated_by, row.excerpt]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
    if (state.sort === "rating") {
      rows.sort((a, b) => (b.match_rating ?? -1) - (a.match_rating ?? -1) || (b.updated_at || "").localeCompare(a.updated_at || ""));
    } else if (state.sort === "player") {
      rows.sort((a, b) => a.name.localeCompare(b.name) || (b.updated_at || "").localeCompare(a.updated_at || ""));
    } else {
      rows.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
    }
    return rows;
  }

  function cardHtml(row) {
    const meta = [row.club, row.fixture_label, formatDate(row.updated_at), row.scout]
      .filter(Boolean)
      .map(escapeHtml)
      .join(" · ");
    const both = row.has_general && row.has_detailed;
    return `<button type="button" class="rl-card${row.id === state.selected ? " is-on" : ""}" data-id="${escapeHtml(row.id)}">
      <span class="rl-pos" title="${escapeHtml(row.position_label)}">${escapeHtml(row.position_short || "—")}</span>
      <span>
        <span class="rl-card__name">${escapeHtml(row.name)}</span>
        <div class="rl-card__meta">${meta}</div>
        ${row.excerpt ? `<div class="rl-card__excerpt">${escapeHtml(row.excerpt)}</div>` : ""}
      </span>
      <span class="rl-card__side">
        <span class="rl-tag rl-tag--${row.kind}" title="${both ? "General and detailed both filed for this game" : ""}">${kindLabel(row.kind)}${both ? " +1" : ""}</span>
        ${row.match_rating != null ? `<span class="rl-rating">${Number(row.match_rating).toFixed(1)}</span>` : ""}
        ${row.pvfc_level ? `<span class="rl-level rl-level--${escapeHtml(row.pvfc_level)}" title="${escapeHtml(row.pvfc_level_label)}">${escapeHtml(row.pvfc_level)}</span>` : ""}
        ${row.next_action_label ? `<span class="rl-tag rl-action--${escapeHtml(row.next_action)}">${escapeHtml(row.next_action_label)}</span>` : ""}
      </span>
    </button>`;
  }

  function renderList() {
    const rows = filtered();
    if (!state.reports.length) {
      els.list.innerHTML = `<div class="rl-none">No reports yet.<br /><a href="/match-scouting">Open Match Scouting →</a></div>`;
      return;
    }
    if (!rows.length) {
      els.list.innerHTML = `<div class="rl-none">No reports match these filters.</div>`;
      return;
    }
    let html = "";
    let lastGroup = null;
    for (const row of rows) {
      if (state.sort === "recent") {
        const group = monthKey(row.updated_at);
        if (group !== lastGroup) {
          html += `<p class="rl-group-head">${escapeHtml(group)}</p>`;
          lastGroup = group;
        }
      }
      html += cardHtml(row);
    }
    els.list.innerHTML = html;
  }

  function syncUrl() {
    const params = new URLSearchParams();
    if (state.kind) params.set("kind", state.kind);
    if (state.query) params.set("q", state.query);
    if (state.position) params.set("position", state.position);
    if (state.level) params.set("level", state.level);
    if (state.action) params.set("action", state.action);
    if (state.scout) params.set("scout", state.scout);
    if (state.sort !== "recent") params.set("sort", state.sort);
    if (state.selected) params.set("report", state.selected);
    const next = params.toString();
    window.history.replaceState({}, "", next ? `${window.location.pathname}?${next}` : window.location.pathname);
  }

  function fieldHtml(label, value, extra) {
    const empty = value === "" || value == null;
    return `<div class="rl-field">
      <div class="rl-field__label">${escapeHtml(label)}</div>
      <div class="rl-field__value${empty ? " rl-field__value--empty" : ""}">${empty ? "—" : escapeHtml(value)}</div>
      ${extra || ""}
    </div>`;
  }

  function physicalHtml(report, options, group) {
    const fields = options.physical || [];
    const wanted = group?.physical?.length ? group.physical : fields.map((f) => f.id);
    const physical = report.physical || {};
    const cells = fields
      .filter((field) => wanted.includes(field.id) || physical[field.id])
      .map((field) => {
        const raw = physical[field.id] || "";
        if (field.kind === "scale") {
          const num = Number(raw);
          const valid = raw !== "" && Number.isFinite(num);
          const bar = valid
            ? `<div class="rl-bar"><span style="width:${Math.max(0, Math.min(10, num)) * 10}%"></span></div>`
            : "";
          return fieldHtml(field.label, valid ? `${num}/10` : "", bar);
        }
        if (field.kind === "choice") {
          const choice = (field.choices || []).find((c) => c.id === raw);
          return fieldHtml(field.label, choice ? choice.label : raw);
        }
        return fieldHtml(field.label, raw);
      });
    if (physical.physical_ability) cells.push(fieldHtml("Physical (older report)", physical.physical_ability));
    if (!cells.length) return "";
    return `<div class="rl-section"><h3>Physical</h3><div class="rl-grid">${cells.join("")}</div></div>`;
  }

  function profilesHtml(report, group, kind) {
    const profiles = report.profiles || {};
    const known = (group?.profiles || []).map((p) => ({
      id: p.id,
      label: p.label,
      prompt: kind === "detailed" ? p.detailed_prompt : p.general_prompt,
    }));
    const knownIds = new Set(known.map((p) => p.id));
    const extra = Object.keys(profiles)
      .filter((id) => !knownIds.has(id) && String(profiles[id] || "").trim())
      .map((id) => ({ id, label: id.replace(/-/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()), prompt: "" }));
    const rows = [...known, ...extra].filter((p) => String(profiles[p.id] || "").trim());
    if (!rows.length) return "";
    return `<div class="rl-section"><h3>${escapeHtml(group?.title ? `${group.title} profiles` : "Profiles")}</h3>
      ${rows
        .map(
          (p) => `<div class="rl-profile">
            <div class="rl-profile__title">${escapeHtml(p.label)}</div>
            ${p.prompt ? `<div class="rl-profile__prompt">${escapeHtml(p.prompt)}</div>` : ""}
            <p class="rl-text">${escapeHtml(profiles[p.id])}</p>
          </div>`,
        )
        .join("")}
    </div>`;
  }

  function psychologyHtml(report, options) {
    const psych = report.psychology || {};
    const ymn = Object.fromEntries((options.yes_mixed_no || []).map((r) => [r.id, r.label]));
    const fields = options.psychology || [];
    const anyValue = fields.some((f) => psych[f.id]) || String(psych.notes || "").trim();
    if (!anyValue) return "";
    const cells = fields
      .map((field) => {
        const value = psych[field.id] || "";
        return `<div class="rl-field">
          <div class="rl-field__label">${escapeHtml(field.label)}</div>
          <div class="rl-field__value ${value ? `rl-${escapeHtml(value)}` : "rl-field__value--empty"}">${value ? escapeHtml(ymn[value] || value) : "—"}</div>
        </div>`;
      })
      .join("");
    return `<div class="rl-section"><h3>Psychology</h3><div class="rl-grid">${cells}</div>
      ${psych.notes ? `<p class="rl-text" style="margin-top:0.7rem">${escapeHtml(psych.notes)}</p>` : ""}
    </div>`;
  }

  function textSection(title, text) {
    const value = String(text || "").trim();
    if (!value) return "";
    return `<div class="rl-section"><h3>${escapeHtml(title)}</h3><p class="rl-text">${escapeHtml(value)}</p></div>`;
  }

  function matchScoutingHref(summary) {
    const params = new URLSearchParams();
    if (summary.league) params.set("league", summary.league);
    params.set("fixture", summary.fixture_id);
    params.set("player", String(summary.player_id));
    return `/match-scouting?${params}`;
  }

  function renderDetail(data) {
    const { summary, report, meta, match_conditions: cond, report_group: group, options, companion } = data;
    const kind = summary.kind;
    const level = (options.pvfc_levels || []).find((row) => row.id === report.pvfc_level);
    const stage = (options.pipeline_stages || []).find((row) => row.id === report.pipeline_stage);
    const headMeta = [
      [meta.club, meta.league].filter(Boolean).join(" · "),
      meta.age ? `Age ${meta.age}` : "",
    ]
      .filter(Boolean)
      .map(escapeHtml)
      .join(" · ");
    const fixtureLine = [
      meta.fixture_label,
      meta.home_away,
      summary.position_label ? `Played ${summary.position_label}` : "",
    ]
      .filter(Boolean)
      .map(escapeHtml)
      .join(" · ");
    const conditionsLine = [
      cond?.weather_label ? `Weather: ${cond.weather_label}${cond.weather_note ? ` (${cond.weather_note})` : ""}` : "",
      cond?.pitch_label ? `Pitch: ${cond.pitch_label}${cond.pitch_note ? ` (${cond.pitch_note})` : ""}` : "",
    ]
      .filter(Boolean)
      .map(escapeHtml)
      .join(" · ");

    els.detail.innerHTML = `<article class="rl-doc">
      <div class="rl-doc__head">
        <div>
          <p class="rl-doc__kind rl-doc__kind--${kind}">${kindLabel(kind)} report</p>
          <h2>${escapeHtml(meta.name)}</h2>
          <p class="rl-doc__meta">${headMeta}</p>
          <p class="rl-doc__meta">${fixtureLine}</p>
          ${conditionsLine ? `<p class="rl-doc__meta">${conditionsLine}</p>` : ""}
        </div>
        <div class="rl-doc__actions">
          ${companion?.available ? `<button type="button" class="rl-btn" data-open="${escapeHtml(`${companion.kind}:${summary.player_id}:${summary.fixture_id}`)}">View ${kindLabel(companion.kind).toLowerCase()} report</button>` : ""}
          <a class="rl-btn" href="/player/${encodeURIComponent(summary.player_id)}">Player page</a>
          <a class="rl-btn rl-btn--primary" href="${escapeHtml(matchScoutingHref(summary))}">Edit in Match Scouting</a>
        </div>
      </div>

      <div class="rl-verdict">
        <div class="rl-stat">
          <div class="rl-stat__label">Match rating</div>
          <div class="rl-stat__value">${report.match_rating != null ? `${Number(report.match_rating).toFixed(1)} / 10` : "—"}</div>
        </div>
        <div class="rl-stat">
          <div class="rl-stat__label">Port Vale level</div>
          <div class="rl-stat__value">${level ? `<span class="rl-level rl-level--${escapeHtml(level.id)}">${escapeHtml(level.id)}</span> ${escapeHtml(level.label)}` : "—"}</div>
          ${level?.hint ? `<div class="rl-stat__hint">${escapeHtml(level.hint)}</div>` : ""}
        </div>
        <div class="rl-stat">
          <div class="rl-stat__label">Next action</div>
          <div class="rl-stat__value rl-action--${escapeHtml(report.next_action || "")}">${escapeHtml(summary.next_action_label || "—")}</div>
        </div>
        <div class="rl-stat">
          <div class="rl-stat__label">Pipeline</div>
          <div class="rl-stat__value">${report.add_to_pipeline ? escapeHtml(stage?.label || "Added") : "Not added"}</div>
        </div>
      </div>

      ${physicalHtml(report, options, group)}
      ${profilesHtml(report, group, kind)}
      ${kind === "detailed" ? psychologyHtml(report, options) : ""}
      ${textSection(kind === "detailed" ? "Write-up" : "Notes", kind === "detailed" ? report.write_up : report.notes)}
      ${textSection("Next steps", report.next_steps)}

      <p class="rl-footer">Filed by ${escapeHtml(summary.scout || "Staff")}${summary.created_at ? ` on ${escapeHtml(formatDateTime(summary.created_at))}` : ""}${
        summary.updated_at && summary.updated_at !== summary.created_at
          ? ` · last edited by ${escapeHtml(summary.updated_by || "Staff")} on ${escapeHtml(formatDateTime(summary.updated_at))}`
          : ""
      }</p>
    </article>`;
    els.detail.scrollTop = 0;
  }

  async function openReport(id) {
    const [kind, playerId, ...rest] = String(id || "").split(":");
    const fixtureId = rest.join(":");
    if (!kind || !playerId || !fixtureId) return;
    state.selected = id;
    syncUrl();
    els.list.querySelectorAll(".rl-card").forEach((card) => card.classList.toggle("is-on", card.dataset.id === id));
    els.detail.innerHTML = `<div class="rl-empty"><p>Loading report…</p></div>`;
    try {
      const params = new URLSearchParams({ kind, player_id: playerId, fixture_id: fixtureId });
      const data = await fetchJson(`/api/reports-library/report?${params}`);
      if (state.selected !== id) return;
      renderDetail(data);
    } catch (error) {
      els.detail.innerHTML = `<div class="rl-empty"><p>Could not load this report</p><span>${escapeHtml(error.message || "")}</span></div>`;
    }
  }

  function rerender() {
    renderKinds();
    renderList();
    syncUrl();
  }

  function bind() {
    els.kinds.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-kind]");
      if (!btn) return;
      state.kind = btn.dataset.kind || "";
      rerender();
    });
    let timer = 0;
    els.search.addEventListener("input", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        state.query = els.search.value;
        rerender();
      }, 120);
    });
    for (const [key, el] of [
      ["position", els.position],
      ["level", els.level],
      ["action", els.action],
      ["scout", els.scout],
      ["sort", els.sort],
    ]) {
      el.addEventListener("change", () => {
        state[key] = el.value;
        rerender();
      });
    }
    els.list.addEventListener("click", (event) => {
      const card = event.target.closest(".rl-card");
      if (card) openReport(card.dataset.id);
    });
    els.detail.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-open]");
      if (btn) openReport(btn.dataset.open);
    });
  }

  async function boot() {
    const params = new URLSearchParams(window.location.search);
    state.kind = ["general", "detailed"].includes(params.get("kind")) ? params.get("kind") : "";
    state.query = params.get("q") || "";
    state.position = params.get("position") || "";
    state.level = params.get("level") || "";
    state.action = params.get("action") || "";
    state.scout = params.get("scout") || "";
    state.sort = ["recent", "rating", "player"].includes(params.get("sort")) ? params.get("sort") : "recent";
    state.selected = params.get("report") || "";
    bind();
    try {
      const data = await fetchJson("/api/reports-library");
      state.reports = data.reports || [];
      state.counts = data.counts || {};
      state.options = data.options || {};
      setStatus("");
    } catch (error) {
      setStatus(error.message || "Could not load reports", "is-error");
    }
    renderFilters();
    rerender();
    if (state.selected) openReport(state.selected);
  }

  boot();
})();
