(() => {
  "use strict";

  const els = {
    list: document.getElementById("wlList"),
    count: document.getElementById("wlCount"),
    status: document.getElementById("wlStatus"),
    updated: document.getElementById("wlUpdated"),
    refreshBtn: document.getElementById("wlRefreshBtn"),
    sub: document.getElementById("wlSub"),
    pipelinesLink: document.getElementById("wlPipelinesLink"),
  };

  let state = {
    targets: [],
    stages: [],
    pipelineStageIds: [],
    positionSections: [],
    snapshot: null,
    // Pipelines is held back until every scout has a personal login.
    pipelinesLive: false,
  };
  let refreshPollTimer = null;

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
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
    return data;
  }

  function formatMinutes(value) {
    if (value == null || value === "") return "—";
    return `${Number(value).toLocaleString()}′`;
  }

  function formatMinutesBreakdown(row) {
    const byPos = Array.isArray(row.minutes_by_position) ? row.minutes_by_position : [];
    if (!byPos.length) {
      const fallback = formatMinutes(row.minutes);
      if (fallback === "—") return "—";
      const label = row.position_label || "";
      return label
        ? `<span class="wl-mins"><span class="wl-mins__main">${fallback} <span class="wl-mins__pos">${esc(label)}</span></span></span>`
        : fallback;
    }
    const focus = String(row.position || "");
    const ordered = [...byPos].sort((a, b) => {
      const aFocus = a.position === focus ? 0 : 1;
      const bFocus = b.position === focus ? 0 : 1;
      if (aFocus !== bFocus) return aFocus - bFocus;
      return Number(b.minutes || 0) - Number(a.minutes || 0);
    });
    const primary = ordered[0];
    const rest = ordered.slice(1);
    const title = ordered
      .map((item) => `${item.label || item.position}: ${formatMinutes(item.minutes)}`)
      .join(" · ");
    return `<span class="wl-mins" title="${esc(title)}">
      <span class="wl-mins__main">${formatMinutes(primary.minutes)} <span class="wl-mins__pos">${esc(primary.label || primary.position || "")}</span></span>
      ${
        rest.length
          ? `<span class="wl-mins__rest">${rest
              .map((item) => `${esc(item.label || item.position)} ${formatMinutes(item.minutes)}`)
              .join(" · ")}</span>`
          : ""
      }
    </span>`;
  }

  function scoreTier(score) {
    if (score == null || Number.isNaN(Number(score))) return "";
    const value = Number(score);
    if (value >= 70) return "high";
    if (value >= 50) return "mid";
    return "low";
  }

  function formatOverall(score) {
    if (score == null || score === "") return "—";
    const tier = scoreTier(score);
    return `<span class="wl-score wl-score--${tier}" title="Impect overall (same scale as Who To Scout)">${Math.round(Number(score))}</span>`;
  }

  function formatBestProfile(row) {
    if (!row.top_profile || row.top_profile_score == null) return "—";
    const tier = scoreTier(row.top_profile_score);
    const score = Number(row.top_profile_score);
    const label = Number.isInteger(score) ? String(Math.round(score)) : score.toFixed(1);
    return `<span class="wl-profile">
      <span class="wl-profile__name">${esc(row.top_profile)}</span>
      <span class="wl-score wl-score--${tier}" title="Impect profile score (0–100)">${esc(label)}</span>
    </span>`;
  }

  function pipelineStages() {
    const ids = new Set(state.pipelineStageIds || []);
    return (state.stages || []).filter(
      (stage) => ids.has(stage.id) || (!ids.size && stage.id !== "watch_list" && !stage.watch_list_only),
    );
  }

  function stageSelect(targetId) {
    if (!state.pipelinesLive) return "";
    const options = pipelineStages()
      .map(
        (stage) =>
          `<option value="${esc(stage.id)}">${esc(stage.title)}</option>`,
      )
      .join("");
    return `<select class="wl-stage" data-stage-for="${esc(targetId)}" aria-label="Move to pipeline stage">
      <option value="">Move to…</option>
      ${options}
    </select>`;
  }

  function tableHeader() {
    return `<thead>
      <tr>
        <th>Player</th>
        <th>Club</th>
        <th>Age</th>
        <th>League</th>
        <th class="col-num">Pos mins</th>
        <th class="col-num">Overall</th>
        <th>Best profile</th>
        <th>Added by</th>
        <th class="col-actions">${state.pipelinesLive ? "Pipeline" : ""}</th>
      </tr>
    </thead>`;
  }

  function rowHtml(t) {
    const pid = Number(t.player_id || 0);
    const href = pid ? `/player/${encodeURIComponent(pid)}` : "#";
    return `<tr data-id="${esc(t.id)}">
      <td class="col-player"><a href="${esc(href)}">${esc(t.name || "—")}</a></td>
      <td>${esc(t.club || "—")}</td>
      <td>${t.age ?? "—"}</td>
      <td>${esc(t.league || "—")}</td>
      <td class="col-num">${formatMinutesBreakdown(t)}</td>
      <td class="col-num">${formatOverall(t.overall_score)}</td>
      <td>${formatBestProfile(t)}</td>
      <td>${esc(t.added_by || "—")}</td>
      <td class="col-actions">
        ${stageSelect(t.id)}
        <button type="button" class="btn btn--danger" data-remove="${esc(t.id)}">Remove</button>
      </td>
    </tr>`;
  }

  function groupTargets(targets) {
    const sections = state.positionSections || [];
    const order = sections.map((s) => s.id);
    const titleById = Object.fromEntries(
      sections.map((s) => [s.id, s.title || s.label || s.id]),
    );
    const buckets = new Map();

    for (const target of targets) {
      const code = String(target.position || "").trim() || "OTHER";
      if (!buckets.has(code)) buckets.set(code, []);
      buckets.get(code).push(target);
    }

    const keys = [...buckets.keys()].sort((a, b) => {
      const ai = order.indexOf(a);
      const bi = order.indexOf(b);
      const av = ai === -1 ? order.length : ai;
      const bv = bi === -1 ? order.length : bi;
      if (av !== bv) return av - bv;
      return a.localeCompare(b);
    });

    return keys.map((code) => {
      const rows = buckets.get(code) || [];
      const sampleLabel = rows[0]?.position_label || "";
      const title =
        titleById[code] ||
        sampleLabel ||
        (code === "OTHER" ? "Other" : code.replaceAll("_", " ").toLowerCase());
      return { code, title, rows };
    });
  }

  function render(targets) {
    els.count.textContent = `${targets.length} player${targets.length === 1 ? "" : "s"} on the watch list`;
    if (!targets.length) {
      els.list.innerHTML = `<p class="wl-empty">Nobody on the watch list yet. Tick players on <a href="/who-to-scout">Who To Scout</a> or Hub Stand outs.</p>`;
      return;
    }

    const groups = groupTargets(targets);
    els.list.innerHTML = groups
      .map(
        (group) => `<section class="wl-section" data-position="${esc(group.code)}">
          <header class="wl-section__head">
            <h2>${esc(group.title)}</h2>
            <span>${group.rows.length}</span>
          </header>
          <div class="wl-section__table">
            <table class="wl-table">
              ${tableHeader()}
              <tbody>${group.rows.map(rowHtml).join("")}</tbody>
            </table>
          </div>
        </section>`,
      )
      .join("");
  }

  function formatUpdatedLabel(snapshot) {
    const snap = snapshot || {};
    if (snap.refreshing || snap.last_refresh_status === "running") {
      return "Refreshing data…";
    }
    const stamp = snap.players_updated_at || snap.standings_updated_at || snap.last_refresh_finished_at;
    if (!stamp) {
      return "No snapshot yet — click Refresh data";
    }
    const when = new Date(stamp);
    if (Number.isNaN(when.getTime())) return "Updated —";
    const label = when.toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
    if (snap.last_refresh_status === "error") {
      return `Refresh failed · last ok ${label}`;
    }
    return `Updated ${label}`;
  }

  function setUpdated(snapshot) {
    state.snapshot = snapshot || state.snapshot;
    if (els.updated) {
      els.updated.textContent = formatUpdatedLabel(state.snapshot);
    }
    if (els.refreshBtn) {
      const busy = Boolean(state.snapshot?.refreshing || state.snapshot?.last_refresh_status === "running");
      els.refreshBtn.disabled = busy;
      els.refreshBtn.textContent = busy ? "Refreshing…" : "Refresh data";
    }
  }

  function applyPipelinesVisibility() {
    if (els.pipelinesLink) els.pipelinesLink.hidden = !state.pipelinesLive;
    if (els.sub && !state.pipelinesLive) {
      els.sub.textContent =
        "Targets from Who To Scout / Stand outs. Everyone sees the same list.";
    }
  }

  async function load() {
    try {
      const data = await fetchJson("/api/watch-list");
      state.targets = data.targets || [];
      state.stages = data.stages || [];
      state.pipelineStageIds = data.pipeline_stage_ids || [];
      state.positionSections = data.position_sections || data.positions || [];
      state.pipelinesLive = Boolean(data.pipelines_live);
      applyPipelinesVisibility();
      setUpdated(data.snapshot || null);
      render(state.targets);
      if (data.stats_missing) {
        setStatus(
          `${data.stats_missing} player${data.stats_missing === 1 ? "" : "s"} still need a data refresh — click Refresh data.`,
          false,
        );
      }
    } catch (err) {
      els.list.innerHTML = `<p class="wl-empty">${esc(err.message || "Failed to load")}</p>`;
      setStatus(err.message || "Failed to load watch list.", true);
    }
  }

  async function pollRefreshStatus() {
    try {
      const status = await fetchJson("/api/hub-snapshots/status");
      setUpdated(status);
      if (status.refreshing || status.last_refresh_status === "running") {
        return;
      }
      if (refreshPollTimer) {
        window.clearInterval(refreshPollTimer);
        refreshPollTimer = null;
      }
      if (status.last_refresh_status === "error") {
        setStatus(status.last_refresh_error || "Data refresh failed.", true);
      } else {
        setStatus("Data refresh finished.", false);
      }
      await load();
    } catch (err) {
      setStatus(err.message || "Could not check refresh status.", true);
    }
  }

  async function refreshData() {
    if (!els.refreshBtn) return;
    els.refreshBtn.disabled = true;
    els.refreshBtn.textContent = "Refreshing…";
    setUpdated({ ...(state.snapshot || {}), refreshing: true, last_refresh_status: "running" });
    try {
      const started = await fetchJson("/api/hub-snapshots/refresh", {
        method: "POST",
        body: JSON.stringify({ scope: "all" }),
      });
      setUpdated({ ...started, refreshing: true, last_refresh_status: "running" });
      setStatus("Pulling latest Impect data in the background…", false);
      if (refreshPollTimer) window.clearInterval(refreshPollTimer);
      refreshPollTimer = window.setInterval(() => {
        void pollRefreshStatus();
      }, 2500);
      window.setTimeout(() => {
        void pollRefreshStatus();
      }, 800);
    } catch (err) {
      setStatus(err.message || "Could not start refresh.", true);
      setUpdated(state.snapshot);
    }
  }

  async function promote(targetId, stage, control) {
    if (!stage) return;
    const stageMeta = pipelineStages().find((row) => row.id === stage);
    let reason = "";
    if (stageMeta?.require_reason) {
      reason = window.prompt("Why are they not the right fit?") || "";
      if (reason.trim().length < 8) {
        setStatus("Need a short reason before moving them there.", true);
        if (control) control.value = "";
        return;
      }
    }
    if (control) control.disabled = true;
    try {
      const data = await fetchJson(`/api/watch-list/promote/${encodeURIComponent(targetId)}`, {
        method: "POST",
        body: JSON.stringify({ stage, reason }),
      });
      const title = stageMeta?.title || stage;
      setStatus(
        data.promoted
          ? `${data.target?.name || "Player"} moved to ${title}.`
          : data.detail || "Already on the pipeline.",
        false,
      );
      await load();
    } catch (err) {
      setStatus(err.message || "Could not move to pipeline.", true);
      if (control) {
        control.disabled = false;
        control.value = "";
      }
    }
  }

  async function remove(targetId, button) {
    if (!window.confirm("Remove this player from the watch list?")) return;
    button.disabled = true;
    try {
      await fetchJson(`/api/player-pipelines/targets/${encodeURIComponent(targetId)}`, {
        method: "DELETE",
      });
      setStatus("Removed from watch list.", false);
      await load();
    } catch (err) {
      setStatus(err.message || "Could not remove.", true);
      button.disabled = false;
    }
  }

  els.list.addEventListener("change", (event) => {
    const select = event.target.closest("[data-stage-for]");
    if (!select) return;
    void promote(select.dataset.stageFor, select.value, select);
  });

  els.list.addEventListener("click", (event) => {
    const removeBtn = event.target.closest("[data-remove]");
    if (removeBtn) {
      void remove(removeBtn.dataset.remove, removeBtn);
    }
  });

  if (els.refreshBtn) {
    els.refreshBtn.addEventListener("click", () => {
      void refreshData();
    });
  }

  load();
})();
