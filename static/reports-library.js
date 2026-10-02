(function initReportsLibrary() {
  const els = {
    status: document.getElementById("rlStatus"),
    kpis: document.getElementById("rlKpis"),
    search: document.getElementById("rlSearch"),
    rating: document.getElementById("rlRating"),
    level: document.getElementById("rlLevel"),
    position: document.getElementById("rlPosition"),
    action: document.getElementById("rlAction"),
    scout: document.getElementById("rlScout"),
    count: document.getElementById("rlCount"),
    body: document.getElementById("rlBody"),
  };

  const state = {
    reports: [],
    options: {},
    query: "",
    rating: "all",
    level: "all",
    position: "all",
    action: "all",
    scout: "all",
  };

  const POSITION_SHORT = {
    GOALKEEPER: "GK",
    LEFT_WINGBACK_DEFENDER: "LB",
    RIGHT_WINGBACK_DEFENDER: "RB",
    CENTRAL_DEFENDER: "CB",
    DEFENSE_MIDFIELD: "DM",
    CENTRAL_MIDFIELD: "CM",
    ATTACKING_MIDFIELD: "AM",
    LEFT_WINGER: "LW",
    RIGHT_WINGER: "RW",
    CENTER_FORWARD: "ST",
  };

  const ACTION_LABELS = {
    not_to_standard: "Not to standard",
    low_priority: "Low priority",
    high_priority: "High priority",
    sign: "Sign",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(message, kind) {
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

  function ratingClass(rating) {
    if (rating == null) return "is-none";
    if (rating >= 8) return "is-hot";
    if (rating >= 6) return "is-ok";
    return "is-low";
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  function positionShort(code) {
    return POSITION_SHORT[code] || code || "—";
  }

  function unique(values) {
    return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  }

  function renderChipGroup(node, items, key, current) {
    if (!node) return;
    node.innerHTML = items
      .map((item) => {
        const id = item.id;
        const on = String(current) === String(id);
        return `<button type="button" class="rl-chip ${on ? "is-active" : ""}" data-${key}="${escapeHtml(id)}">${escapeHtml(item.label)}</button>`;
      })
      .join("");
    node.querySelectorAll(`[data-${key}]`).forEach((btn) => {
      btn.addEventListener("click", () => {
        state[key] = btn.dataset[key] || "all";
        render();
      });
    });
  }

  function filtered() {
    const q = state.query.trim().toLowerCase();
    return state.reports.filter((row) => {
      if (state.rating === "none" && row.match_rating != null) return false;
      if (state.rating !== "all" && state.rating !== "none") {
        if (row.match_rating == null || Number(row.match_rating) < Number(state.rating)) return false;
      }
      if (state.level !== "all" && row.pvfc_level !== state.level) return false;
      if (state.position !== "all" && row.position !== state.position) return false;
      if (state.action !== "all" && row.next_action !== state.action) return false;
      if (state.scout !== "all" && row.updated_by !== state.scout) return false;
      if (!q) return true;
      const hay = [row.name, row.club, row.fixture_label, row.league, row.updated_by]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  function renderKpis(rows) {
    const rated = rows.filter((row) => row.match_rating != null);
    const hot = rated.filter((row) => Number(row.match_rating) >= 8).length;
    const aLevel = rows.filter((row) => row.pvfc_level === "A").length;
    els.kpis.innerHTML = `
      <div class="rl-kpi"><span>Reports</span><strong>${rows.length}</strong></div>
      <div class="rl-kpi"><span>Rated</span><strong>${rated.length}</strong></div>
      <div class="rl-kpi"><span>8+</span><strong>${hot}</strong></div>
      <div class="rl-kpi"><span>A level</span><strong>${aLevel}</strong></div>
    `;
  }

  function renderFilters() {
    const positions = (state.options.positions || []).map((row) => ({
      id: row.id,
      label: row.short || row.label,
    }));
    renderChipGroup(
      els.position,
      [{ id: "all", label: "All" }, ...positions],
      "position",
      state.position
    );
    const actions = (state.options.next_actions || []).map((row) => ({
      id: row.id,
      label: row.label,
    }));
    renderChipGroup(
      els.action,
      [{ id: "all", label: "All" }, ...actions],
      "action",
      state.action
    );
    const scouts = unique(state.reports.map((row) => row.updated_by)).map((name) => ({
      id: name,
      label: name,
    }));
    renderChipGroup(
      els.scout,
      [{ id: "all", label: "All" }, ...scouts],
      "scout",
      state.scout
    );
  }

  function renderTable(rows) {
    if (!rows.length) {
      els.body.innerHTML = `<tr><td colspan="9" class="rl-empty">No reports match these filters.</td></tr>`;
      return;
    }
    els.body.innerHTML = rows
      .map((row) => {
        const rating = row.match_rating == null ? "—" : Number(row.match_rating);
        return `<tr data-href="${escapeHtml(row.href || "/player-reports")}">
          <td>
            <span class="rl-player">${escapeHtml(row.name || "Player")}</span>
            <span class="rl-meta">${escapeHtml(row.source === "detailed" ? "Detailed" : "General")}</span>
          </td>
          <td>${escapeHtml(row.club || "—")}<span class="rl-meta">${escapeHtml(row.league || "")}</span></td>
          <td>${escapeHtml(row.fixture_label || "—")}</td>
          <td>${escapeHtml(positionShort(row.position))}</td>
          <td class="rl-rating ${ratingClass(row.match_rating)}">${escapeHtml(rating)}</td>
          <td class="rl-level ${row.pvfc_level ? `is-${escapeHtml(row.pvfc_level)}` : ""}">${escapeHtml(row.pvfc_level || "—")}</td>
          <td>${escapeHtml(ACTION_LABELS[row.next_action] || row.next_action || "—")}</td>
          <td>${escapeHtml(row.updated_by || "—")}</td>
          <td>${escapeHtml(formatWhen(row.updated_at))}</td>
        </tr>`;
      })
      .join("");
    els.body.querySelectorAll("[data-href]").forEach((row) => {
      row.addEventListener("click", () => {
        window.location.href = row.dataset.href;
      });
    });
  }

  function render() {
    const rows = filtered();
    els.count.textContent = `${rows.length} of ${state.reports.length} reports`;
    renderTable(rows);
    els.rating.querySelectorAll("[data-rating]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.rating === state.rating);
    });
    els.level.querySelectorAll("[data-level]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.level === state.level);
    });
  }

  function bindStatic() {
    els.search?.addEventListener("input", (event) => {
      state.query = event.target.value || "";
      render();
    });
    els.rating?.querySelectorAll("[data-rating]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.rating = btn.dataset.rating || "all";
        render();
      });
    });
    els.level?.querySelectorAll("[data-level]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.level = btn.dataset.level || "all";
        render();
      });
    });
  }

  async function boot() {
    bindStatic();
    setStatus("Loading reports…");
    try {
      const data = await fetchJson("/api/reports-library");
      state.reports = data.reports || [];
      state.options = data.options || {};
      renderKpis(state.reports);
      renderFilters();
      render();
      setStatus("");
    } catch (error) {
      els.body.innerHTML = `<tr><td colspan="9" class="rl-empty">${escapeHtml(error.message || "Could not load reports.")}</td></tr>`;
      setStatus(error.message || "Could not load reports.", "is-error");
    }
  }

  boot();
})();
