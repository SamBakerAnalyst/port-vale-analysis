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
    panel: document.getElementById("wlPanel"),
    legend: document.getElementById("wlLegend"),
    leagueGroup: document.getElementById("wlLeagueGroup"),
    positionGroup: document.getElementById("wlPositionGroup"),
    situationGroup: document.getElementById("wlSituationGroup"),
  };

  const LEAGUE_ORDER = [
    "League One",
    "League Two",
    "National League",
    "Scottish Prem",
    "PL2",
    "Irish Prem",
  ];

  let state = {
    targets: [],
    stages: [],
    pipelineStageIds: [],
    positionSections: [],
    snapshot: null,
    transferCheck: null,
    statsMissing: 0,
    // Pipelines is held back until every scout has a personal login.
    pipelinesLive: false,
    filters: {
      league: "all",
      position: "all",
      situation: "all",
    },
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

    function isLoanMove(move) {
      return move?.status === "loan_in" || move?.status === "loan_out";
    }

    function situationOf(target) {
      const move = target?.transfer;
      if (!move?.club) return "";
      if (isLoanMove(move)) return "loan";
      if (move.status === "gone") return "gone";
      return "check";
    }

    function matchesFilters(target) {
      const { league, position, situation } = state.filters;
      if (league !== "all" && String(target.league || "") !== league) return false;
      if (position !== "all") {
        const code = String(target.position || "").trim() || "OTHER";
        if (code !== position) return false;
      }
      if (situation !== "all" && situationOf(target) !== situation) return false;
      return true;
    }

    function situationCounts(targets) {
      const counts = { loan: 0, gone: 0, check: 0 };
      for (const row of targets || []) {
        const key = situationOf(row);
        if (key) counts[key] += 1;
      }
      return counts;
    }

    function uniqueLeagues(targets) {
      const present = new Set(
        (targets || []).map((row) => String(row.league || "").trim()).filter(Boolean),
      );
      const ranked = LEAGUE_ORDER.filter((name) => present.has(name));
      const rest = [...present].filter((name) => !LEAGUE_ORDER.includes(name)).sort((a, b) => a.localeCompare(b));
      return [...ranked, ...rest];
    }

    function uniquePositions(targets) {
      const present = new Set(
        (targets || []).map((row) => String(row.position || "").trim() || "OTHER"),
      );
      const sections = state.positionSections || [];
      const ordered = [];
      for (const section of sections) {
        if (present.has(section.id)) ordered.push(section);
      }
      if (present.has("OTHER") && !ordered.some((row) => row.id === "OTHER")) {
        ordered.push({ id: "OTHER", label: "Other", title: "Other" });
      }
      for (const code of present) {
        if (!ordered.some((row) => row.id === code)) {
          ordered.push({ id: code, label: code, title: code });
        }
      }
      return ordered;
    }

    function filterBtn(value, label, { group, extraClass = "", count = null, title = "" } = {}) {
      const active = state.filters[group] === value;
      const classes = ["wl-filter__btn", extraClass, active ? "is-active" : ""]
        .filter(Boolean)
        .join(" ");
      const shown = count == null ? label : `${label} ${count}`;
      return `<button type="button" class="${classes}" data-filter="${esc(group)}" data-value="${esc(value)}"${
        title ? ` title="${esc(title)}"` : ""
      }>${esc(shown)}</button>`;
    }

    function filtersActive() {
      return (
        state.filters.league !== "all" ||
        state.filters.position !== "all" ||
        state.filters.situation !== "all"
      );
    }

    function renderLegend(targets) {
      if (!els.legend) return;
      const total = (targets || []).length;
      const counts = situationCounts(targets);
      const chips = [];
      if (counts.loan) {
        chips.push(
          `<li><button type="button" class="wl-legend__chip wl-legend__chip--loan${
            state.filters.situation === "loan" ? " is-active" : ""
          }" data-filter="situation" data-value="loan" title="Show players on loan">
            <span class="wl-legend__dot" aria-hidden="true"></span>
            ${counts.loan} on loan
          </button></li>`,
        );
      }
      if (counts.gone) {
        chips.push(
          `<li><button type="button" class="wl-legend__chip wl-legend__chip--moved${
            state.filters.situation === "gone" ? " is-active" : ""
          }" data-filter="situation" data-value="gone" title="Show players who have signed elsewhere">
            <span class="wl-legend__dot" aria-hidden="true"></span>
            ${counts.gone} signed elsewhere
          </button></li>`,
        );
      }
      if (counts.check) {
        chips.push(
          `<li><button type="button" class="wl-legend__chip wl-legend__chip--check${
            state.filters.situation === "check" ? " is-active" : ""
          }" data-filter="situation" data-value="check" title="Name matched a signing — check it is the same player">
            <span class="wl-legend__dot" aria-hidden="true"></span>
            ${counts.check} to check
          </button></li>`,
        );
      }
      const hint =
        "Blue names are on loan — any deal is with the parent club. Red names have already signed elsewhere.";
      const check = state.transferCheck || {};
      const metaClass = check.stale ? "wl-legend__meta is-stale" : "wl-legend__meta";
      const meta = check.detail
        ? `<p class="${metaClass}">${esc(check.detail)}</p>`
        : "";
      const missing = state.statsMissing
        ? `<p class="wl-legend__meta">${state.statsMissing} still need a data refresh — click Refresh data.</p>`
        : "";
      els.legend.innerHTML = `
        <p class="wl-legend__lead">${total} player${total === 1 ? "" : "s"} on the watch list</p>
        ${chips.length ? `<ul class="wl-legend__keys">${chips.join("")}</ul>` : ""}
        <p class="wl-legend__hint">${esc(hint)}</p>
        ${meta}
        ${missing}
      `;
    }

    function renderFilterControls(targets) {
      if (els.leagueGroup) {
        const leagues = uniqueLeagues(targets);
        if (state.filters.league !== "all" && !leagues.includes(state.filters.league)) {
          state.filters.league = "all";
        }
        els.leagueGroup.innerHTML = [
          filterBtn("all", "All", { group: "league" }),
          ...leagues.map((name) =>
            filterBtn(name, name, {
              group: "league",
              count: targets.filter((row) => String(row.league || "") === name).length,
            }),
          ),
        ].join("");
      }
      if (els.positionGroup) {
        const positions = uniquePositions(targets);
        if (
          state.filters.position !== "all" &&
          !positions.some((row) => row.id === state.filters.position)
        ) {
          state.filters.position = "all";
        }
        els.positionGroup.innerHTML = [
          filterBtn("all", "All", { group: "position" }),
          ...positions.map((row) =>
            filterBtn(row.id, row.label || row.title || row.id, {
              group: "position",
              count: targets.filter((item) => (String(item.position || "").trim() || "OTHER") === row.id)
                .length,
              title: row.title || "",
            }),
          ),
        ].join("");
      }
      if (els.situationGroup) {
        const counts = situationCounts(targets);
        const buttons = [
          filterBtn("all", "All", { group: "situation" }),
          filterBtn("loan", "On loan", {
            group: "situation",
            extraClass: "wl-filter__btn--loan",
            count: counts.loan || null,
            title: "Players on loan at their current club, or out on loan",
          }),
          filterBtn("gone", "Signed elsewhere", {
            group: "situation",
            extraClass: "wl-filter__btn--moved",
            count: counts.gone || null,
            title: "Players who have already signed for another club",
          }),
        ];
        if (counts.check) {
          buttons.push(
            filterBtn("check", "Check", {
              group: "situation",
              extraClass: "wl-filter__btn--check",
              count: counts.check,
              title: "Name matched a signing — check it is the same player",
            }),
          );
        }
        if (filtersActive()) {
          buttons.push(
            `<button type="button" class="wl-filter__clear" data-filter-clear="1">Clear</button>`,
          );
        }
        els.situationGroup.innerHTML = buttons.join("");
      }
    }

    // A tracked player who has moved is the costliest stale row on the hub —
    // someone may be planning a trip. A tracked player who is on loan is the
    // second costliest: he is signable, but not from the club on the row.
    function clubCell(t) {
      const move = t?.transfer;
      const club = esc(t.club || "—");
      if (!move?.club) return `<td>${club}</td>`;
      const where = `${move.club}${move.league ? ` (${move.league})` : ""}`;
      let line;
      let tone;
      let title;
      let struck = false;

      if (move.status === "loan_in") {
        line = `on loan from ${move.from || "another club"}`;
        tone = "club-loan";
        title = `On loan at ${t.club || "this club"} from ${
          move.from || "another club"
        } — any deal is with ${move.from || "the parent club"}, not ${t.club || "this club"}`;
      } else if (move.status === "loan_out") {
        line = `on loan at ${move.club}`;
        tone = "club-loan";
        title = `Out on loan at ${where} — still ${t.club || "his club"}'s player`;
      } else if (move.status === "gone") {
        line = move.club;
        tone = "club-now";
        struck = true;
        title = `Signed for ${where}${move.from ? ` from ${move.from}` : ""}${
          move.fee ? ` · ${move.fee}` : ""
        }`;
      } else {
        line = `${move.club}?`;
        tone = "club-now club-now--check";
        title = `A player of this name signed for ${where}${
          move.from ? ` from ${move.from}` : ""
        } — check it is the same player before ruling him out`;
      }

      return `<td title="${esc(title)}">
        <span class="${struck ? "club-was" : "club-held"}">${club}</span>
        <span class="${tone}">${esc(line)}</span>
      </td>`;
    }

    function rowHtml(t) {
      const pid = Number(t.player_id || 0);
      const href = pid ? `/player/${encodeURIComponent(pid)}` : "#";
      const move = t?.transfer;
      const moveClass = !move?.club
        ? ""
        : isLoanMove(move)
          ? " is-loan"
          : move.status === "gone"
            ? " is-moved"
            : " is-move-check";
      return `<tr data-id="${esc(t.id)}" class="${moveClass.trim()}">
        <td class="col-player"><a href="${esc(href)}">${esc(t.name || "—")}</a></td>
        ${clubCell(t)}
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
    const all = targets || [];
    const visible = all.filter(matchesFilters);
    if (els.panel) els.panel.hidden = !all.length;
    if (all.length) {
      renderLegend(all);
      renderFilterControls(all);
    }

    const filtered = filtersActive();
    if (els.count) {
      if (filtered && all.length) {
        els.count.hidden = false;
        els.count.textContent = `Showing ${visible.length} of ${all.length}`;
      } else {
        els.count.hidden = true;
      }
    }

    if (!all.length) {
      els.list.innerHTML = `<p class="wl-empty">Nobody on the watch list yet. Tick players on <a href="/who-to-scout">Who To Scout</a> or Hub Stand outs.</p>`;
      return;
    }
    if (!visible.length) {
      els.list.innerHTML = `<p class="wl-empty">Nobody matches these filters. Clear league, position or situation to see the full list.</p>`;
      return;
    }

    const groups = groupTargets(visible);
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
      state.transferCheck = data.transfer_check || null;
      state.statsMissing = Number(data.stats_missing) || 0;
      applyPipelinesVisibility();
      setUpdated(data.snapshot || null);
      render(state.targets);
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

  function setFilter(group, value) {
    if (!["league", "position", "situation"].includes(group)) return;
    const next = String(value || "all");
    if (next !== "all" && state.filters[group] === next) {
      state.filters[group] = "all";
    } else {
      state.filters[group] = next;
    }
    render(state.targets);
  }

  function clearFilters() {
    state.filters = { league: "all", position: "all", situation: "all" };
    render(state.targets);
  }

  els.panel?.addEventListener("click", (event) => {
    const clearBtn = event.target.closest("[data-filter-clear]");
    if (clearBtn) {
      clearFilters();
      return;
    }
    const btn = event.target.closest("[data-filter]");
    if (!btn) return;
    setFilter(btn.dataset.filter, btn.dataset.value);
  });

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
