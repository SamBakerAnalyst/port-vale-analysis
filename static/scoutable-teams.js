(function initScoutableTeams() {
  const VIEW_KEY = "pv-scoutable-teams-view";
  const POS_COLORS = {
    GOALKEEPER: "#3d8bfd",
    LEFT_WINGBACK_DEFENDER: "#06b6d4",
    RIGHT_WINGBACK_DEFENDER: "#0ea5e9",
    CENTRAL_DEFENDER: "#22c55e",
    DEFENSE_MIDFIELD: "#a78bfa",
    CENTRAL_MIDFIELD: "#8b5cf6",
    ATTACKING_MIDFIELD: "#f59e0b",
    LEFT_WINGER: "#f472b6",
    RIGHT_WINGER: "#fb7185",
    CENTER_FORWARD: "#ef4444",
  };

  const els = {
    title: document.getElementById("stTitle"),
    sub: document.getElementById("stSub"),
    status: document.getElementById("stStatus"),
    filter: document.getElementById("stFilter"),
    leagues: document.getElementById("stLeagues"),
    club: document.getElementById("stClub"),
    back: document.getElementById("stBackBtn"),
    clubToggle: document.getElementById("stClubViewToggle"),
    viewBoard: document.getElementById("stViewBoard"),
    viewTable: document.getElementById("stViewTable"),
    reasonModal: document.getElementById("stReasonModal"),
    reasonForm: document.getElementById("stReasonForm"),
    reasonText: document.getElementById("stReasonText"),
    reasonError: document.getElementById("stReasonError"),
  };

  const state = {
    leagues: [],
    stages: [],
    positions: [],
    profilesByPosition: {},
    // Table-first (Monday-style). Only board if user explicitly chose it.
    view: localStorage.getItem(VIEW_KEY) === "board" ? "board" : "table",
    mode: "leagues",
    club: null,
    pendingStatus: null,
  };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(message, isError = false) {
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
    let res;
    try {
      res = await fetch(url, {
        cache: "no-store",
        headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
        ...options,
      });
    } catch {
      throw new Error(
        "Couldn’t reach the server (Impect may be busy / rate-limiting). Wait a minute and try again."
      );
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
            : `Request failed (${res.status})`
      );
    }
    return data;
  }

  function scoreTier(score) {
    if (score == null || Number.isNaN(Number(score))) return "";
    const value = Number(score);
    if (value >= 70) return "high";
    if (value >= 50) return "mid";
    return "low";
  }

  function scoreChip(score, { title = "" } = {}) {
    if (score == null || score === "") {
      return `<span class="st-chip st-chip--empty">—</span>`;
    }
    const tier = scoreTier(score);
    return `<span class="st-chip st-chip--${tier}" title="${esc(title)}">${Math.round(Number(score))}</span>`;
  }

  function scoreBadge(score) {
    if (score == null || score === "") return "";
    const tier = scoreTier(score);
    return `<span class="st-score st-score--${tier}" title="Data overall">${Math.round(Number(score))}</span>`;
  }

  function stageOptions(selected, player) {
    const noneSelected = !selected ? "selected" : "";
    const none = `<option value="" ${noneSelected}>Not in pipeline</option>`;
    const hasComment = Boolean(String(player?.scout_comment || "").trim());
    const opts = state.stages
      .map((stage) => {
        const label = selected ? stage.title : `Add → ${stage.title}`;
        const disabled =
          stage.id === "watched" && !hasComment ? "disabled" : "";
        const hint =
          stage.id === "watched" && !hasComment
            ? " (add scout comments first)"
            : "";
        return `<option value="${esc(stage.id)}" ${stage.id === selected ? "selected" : ""} ${disabled}>${esc(
          label + hint
        )}</option>`;
      })
      .join("");
    return none + opts;
  }

  function stageSelect(player) {
    const stage = player.pipeline_stage || "";
    const color = player.pipeline_stage_color || "#374151";
    return `<label class="st-status" style="--stage:${esc(color)}">
      <select data-status-for="${esc(player.player_id)}" aria-label="Pipeline status for ${esc(player.name)}">
        ${stageOptions(stage, player)}
      </select>
    </label>`;
  }

  function scoutScoreInput(player, profileKey, profileLabel) {
    const scores = player.scout_scores || {};
    const value =
      profileKey && scores[profileKey] != null && scores[profileKey] !== ""
        ? Number(scores[profileKey])
        : "";
    const label = profileLabel
      ? `Scout score for ${player.name} — ${profileLabel}`
      : `Scout score for ${player.name}`;
    return `<input
      type="number"
      min="0"
      max="100"
      step="1"
      inputmode="numeric"
      class="st-scout-score"
      data-scout-score-for="${esc(player.player_id)}"
      data-profile-key="${esc(profileKey || "")}"
      value="${value === "" ? "" : esc(value)}"
      placeholder="—"
      aria-label="${esc(label)}"
    />`;
  }

  function scoutCommentInput(player) {
    return `<input
      type="text"
      maxlength="280"
      class="st-scout-comment"
      data-scout-comment-for="${esc(player.player_id)}"
      value="${esc(player.scout_comment || "")}"
      placeholder="Brief scout notes…"
      autocomplete="off"
      spellcheck="true"
      aria-label="Scout comments for ${esc(player.name)}"
    />`;
  }

  const scoutSaveTimers = new Map();
  let skipCommentBlurCommit = false;

  function findPlayer(playerId) {
    return (state.club?.players || []).find((row) => row.player_id === playerId);
  }

  function refreshWatchedOption(playerId) {
    const player = findPlayer(playerId);
    const select = els.club?.querySelector(`select[data-status-for="${playerId}"]`);
    if (!player || !select) return;
    const hasComment = Boolean(String(player.scout_comment || "").trim());
    const watchedOpt = select.querySelector('option[value="watched"]');
    if (!watchedOpt) return;
    watchedOpt.disabled = !hasComment;
    watchedOpt.textContent = player.pipeline_stage === "watched" ? "Watched" : "Add → Watched";
    if (!hasComment && select.value === "watched") {
      select.value = player.pipeline_stage || "";
    }
  }

  function applyPipelineTarget(player, target) {
    if (!player || !target) return;
    player.in_pipeline = true;
    player.pipeline_stage = target.stage || "watched";
    player.pipeline_stage_title =
      state.stages.find((row) => row.id === player.pipeline_stage)?.title ||
      target.stage ||
      "Watched";
    player.pipeline_stage_color =
      state.stages.find((row) => row.id === player.pipeline_stage)?.color ||
      target.stage_color ||
      "#eab308";
    player.pipeline_target_id = target.id || "";
  }

  function syncPipelineSelect(player) {
    const select = els.club?.querySelector(`select[data-status-for="${player.player_id}"]`);
    if (!select) return;
    const stage = player.pipeline_stage || "";
    const color = player.pipeline_stage_color || "#374151";
    select.innerHTML = stageOptions(stage, player);
    select.value = stage;
    const label = select.closest(".st-status");
    if (label) label.style.setProperty("--stage", color);
    const row = select.closest("tr.st-row, .st-grid--row, .st-player");
    if (row) {
      if (stage) {
        row.classList.add("is-piped");
        row.style.setProperty("--stage", color);
      } else {
        row.classList.remove("is-piped");
      }
    }
  }

  async function saveScoutNotes(player, patch) {
    const nextScores = { ...(player.scout_scores || {}) };
    if (patch.scout_scores) {
      Object.entries(patch.scout_scores).forEach(([key, val]) => {
        if (val == null || val === "" || Number.isNaN(val)) {
          delete nextScores[key];
        } else {
          nextScores[key] = Math.max(0, Math.min(100, Number(val)));
        }
      });
    }
    const payload = {
      player_id: player.player_id,
      scout_scores: nextScores,
      scout_comment: patch.scout_comment ?? player.scout_comment ?? "",
      name: player.name,
      club: player.club || state.club?.club || "",
      league: player.league || state.club?.league || "",
      position: player.position || "",
      position_label: player.position_label || "",
      age: player.age ?? null,
    };
    try {
      const data = await fetchJson("/api/scoutable-teams/scout-notes", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      player.scout_scores = data.scout_scores || {};
      player.scout_comment = data.scout_comment || "";
      if (data.pipeline) {
        const current = player.pipeline_stage || "";
        if (!current || current === "watched") {
          applyPipelineTarget(player, data.pipeline);
          syncPipelineSelect(player);
        }
      }
      refreshWatchedOption(player.player_id);
      return true;
    } catch (err) {
      setStatus(err.message || String(err), true);
      return false;
    }
  }

  function queueScoutSave(playerId, patch) {
    const player = findPlayer(playerId);
    if (!player) return;
    Object.assign(player, patch);
    refreshWatchedOption(playerId);
    const prev = scoutSaveTimers.get(playerId);
    if (prev) clearTimeout(prev);
    scoutSaveTimers.set(
      playerId,
      setTimeout(async () => {
        scoutSaveTimers.delete(playerId);
        // Never rebuild the table while typing — that steals focus.
        await saveScoutNotes(player, patch);
      }, 700)
    );
  }

  async function commitScoutComment(input) {
    const playerId = Number(input.dataset.scoutCommentFor);
    const player = findPlayer(playerId);
    if (!player) return false;

    const prev = scoutSaveTimers.get(playerId);
    if (prev) {
      clearTimeout(prev);
      scoutSaveTimers.delete(playerId);
    }

    const comment = String(input.value || "");
    return saveScoutNotes(player, { scout_comment: comment });
  }

  function wireScoutFields(root) {
    root.querySelectorAll("input[data-scout-score-for]").forEach((input) => {
      input.addEventListener("keydown", (event) => {
        event.stopPropagation();
      });
      input.addEventListener("change", async () => {
        const playerId = Number(input.dataset.scoutScoreFor);
        const profileKey = String(input.dataset.profileKey || "").trim();
        const player = findPlayer(playerId);
        if (!player || !profileKey) return;
        const raw = String(input.value || "").trim();
        const score = raw === "" ? null : Math.max(0, Math.min(100, Number(raw)));
        if (raw !== "" && Number.isNaN(score)) {
          input.value = player.scout_scores?.[profileKey] ?? "";
          return;
        }
        await saveScoutNotes(player, {
          scout_scores: { [profileKey]: score },
          scout_comment: player.scout_comment || "",
        });
      });
    });

    root.querySelectorAll("input[data-scout-comment-for]").forEach((input) => {
      // Keep keys inside the comment box — don't let page handlers steal focus.
      input.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (event.key !== "Enter") return;
        event.preventDefault();
        skipCommentBlurCommit = true;
        commitScoutComment(input).finally(() => {
          skipCommentBlurCommit = false;
          // Stay in the box so typing can continue immediately.
          input.focus();
        });
      });
      input.addEventListener("keyup", (event) => event.stopPropagation());
      input.addEventListener("keypress", (event) => event.stopPropagation());
      input.addEventListener("input", () => {
        const playerId = Number(input.dataset.scoutCommentFor);
        queueScoutSave(playerId, { scout_comment: input.value });
      });
      input.addEventListener("blur", async () => {
        if (skipCommentBlurCommit) return;
        await commitScoutComment(input);
      });
    });
  }

  function filterText() {
    return els.filter.value.trim().toLowerCase();
  }

  function clubWatchMeta(club) {
    const live = Number(club.watch_live || 0);
    const video = Number(club.watch_video || 0);
    const pipe = Number(club.pipeline_count || 0);
    const bits = [];
    bits.push(`${live} live`);
    bits.push(`${video} video`);
    if (pipe) bits.push(`${pipe} on pipelines`);
    return bits.join(" · ");
  }

  function clubWatchPills(club) {
    const live = Number(club.watch_live || 0);
    const video = Number(club.watch_video || 0);
    const pipe = Number(club.pipeline_count || 0);
    const pills = [
      `<span class="st-pill st-pill--live${live ? "" : " is-empty"}" title="Live watches from fixture planner">${live}L</span>`,
      `<span class="st-pill st-pill--video${video ? "" : " is-empty"}" title="Video watches from fixture planner">${video}V</span>`,
    ];
    if (pipe) {
      pills.push(
        `<span class="st-pill st-pill--pipe" title="Players on Player Pipelines">${pipe}</span>`
      );
    }
    return `<span class="st-team__pills">${pills.join("")}</span>`;
  }

  function renderLeagues() {
    const q = filterText();
    els.leagues.innerHTML = state.leagues
      .map((league) => {
        const clubs = (league.clubs || []).filter((club) => {
          if (!q) return true;
          return String(club.name || "").toLowerCase().includes(q);
        });
        return `<section class="st-league" style="--league:${esc(league.color || "#34d399")}">
          <header class="st-league__head">
            <h2 class="st-league__title">
              <span>${esc(league.title)}</span>
              <span class="st-league__count">${clubs.length}</span>
            </h2>
            <p class="st-league__season">${esc(league.season ? `Season ${league.season}` : "No squads loaded")}</p>
          </header>
          <div class="st-league__list">
            ${
              clubs
                .map((club) => {
                  const meta = clubWatchMeta(club);
                  const tip = `Fixture planner: ${Number(club.watch_live || 0)} live · ${Number(club.watch_video || 0)} video`;
                  return `<button type="button" class="st-team" title="${esc(tip)}" data-league="${esc(league.id)}" data-club="${esc(club.name)}" data-squad="${esc(club.id)}" data-iteration="${esc(club.iteration_id)}">
                    <span>
                      <span class="st-team__name">${esc(club.name)}</span>
                      <span class="st-team__meta">${esc(meta)}</span>
                    </span>
                    ${clubWatchPills(club)}
                  </button>`;
                })
                .join("") || `<p class="st-empty">No clubs match.</p>`
            }
          </div>
        </section>`;
      })
      .join("");

    els.leagues.querySelectorAll(".st-team").forEach((btn) => {
      btn.addEventListener("click", () => {
        openClub({
          name: btn.dataset.club,
          league: btn.dataset.league,
          squad_id: Number(btn.dataset.squad),
          iteration_id: Number(btn.dataset.iteration),
        });
      });
    });
  }

  function playerMeta(player) {
    return [
      player.position_label,
      player.age != null ? `${player.age}y` : "",
      player.minutes != null ? `${Number(player.minutes).toLocaleString()}′` : "",
      player.foot,
      player.height,
    ]
      .filter(Boolean)
      .join(" · ");
  }

  function playerCard(player) {
    const color = player.pipeline_stage_color || POS_COLORS[player.position] || "#2a2a2a";
    const highlight =
      player.top_profile && player.top_profile_score != null
        ? `Strong: ${player.top_profile} (${player.top_profile_score})`
        : "";
    const profiles = state.profilesByPosition[player.position] || [];
    const profileRow = profiles
      .slice(0, 6)
      .map((profile) => {
        const value = player.profile_scores?.[profile.apiName];
        return `<span class="st-mini-prof">
          <span class="st-mini-prof__top">
            <span class="st-mini-prof__label">${esc(shortProfileLabel(profile.label))}</span>
            ${scoreChip(value)}
          </span>
          ${scoutScoreInput(player, profile.apiName, profile.label)}
        </span>`;
      })
      .join("");
    return `<article class="st-player" style="--stage:${esc(color)}" data-player-id="${esc(player.player_id)}">
      <div class="st-player__top">
        <div>
          <p class="st-player__name">${esc(player.name)}</p>
          <p class="st-player__meta">${esc(playerMeta(player))}</p>
          ${highlight ? `<p class="st-player__highlight">${esc(highlight)}</p>` : ""}
        </div>
        ${scoreBadge(player.overall)}
      </div>
      ${profileRow ? `<div class="st-player__profiles">${profileRow}</div>` : ""}
      <div class="st-player__actions">
        ${stageSelect(player)}
        ${
          player.dossier_href
            ? `<a class="st-player__link" href="${esc(player.dossier_href)}" target="_blank" rel="noopener">Dossier</a>`
            : ""
        }
      </div>
      <label class="st-player__comment">
        <span>Scout comments</span>
        ${scoutCommentInput(player)}
      </label>
    </article>`;
  }

  function filteredPlayers() {
    const q = filterText();
    const players = state.club?.players || [];
    if (!q) return players;
    return players.filter((player) => {
      const hay = `${player.name} ${player.position_label} ${player.foot}`.toLowerCase();
      return hay.includes(q);
    });
  }

  function wireStatusSelects(root) {
    root.querySelectorAll("select[data-status-for]").forEach((select) => {
      select.addEventListener("change", () => {
        const playerId = Number(select.dataset.statusFor);
        const player = findPlayer(playerId);
        if (!player) return;
        if (select.value === "watched" && !String(player.scout_comment || "").trim()) {
          select.value = player.pipeline_stage || "";
          setStatus("Add scout comments before marking as Watched.", true);
          return;
        }
        requestStatusChange(player, select.value, select);
      });
    });
  }

  function profilesForPosition(positionId, playersInGroup) {
    if (!positionId) return [];
    const configured = state.profilesByPosition[positionId] || [];
    if (configured.length) return configured;
    // Only fall back to a player's own position profiles — never the full dump.
    const seen = new Map();
    for (const player of playersInGroup) {
      Object.keys(player.profile_scores || {}).forEach((apiName) => {
        if (!seen.has(apiName)) {
          seen.set(apiName, { apiName, label: apiName.replace(/^PV\s*-\s*/i, "") });
        }
      });
    }
    return [...seen.values()].slice(0, 8);
  }

  function shortProfileLabel(label) {
    return String(label || "")
      .replace(/Goal Keeper/gi, "GK")
      .replace(/Central /gi, "")
      .replace(/Ball Playing/gi, "Ball play")
      .replace(/Shot Stopping/gi, "Shot stop")
      .replace(/Sweeper Keeper/gi, "Sweeper")
      .replace(/Box Goal Keeper/gi, "Box GK")
      .replace(/Running Threat/gi, "Runner")
      .replace(/Goal Threat/gi, "Finisher")
      .replace(/Ball Progressor/gi, "Progress")
      .replace(/Ball Winner/gi, "Winner")
      .replace(/Deep Creator/gi, "Deep create")
      .replace(/Wide receiver/gi, "Wide recv")
      .replace(/Left Side Dueler/gi, "L dueler")
      .replace(/Right Side Dueler/gi, "R dueler")
      .replace(/Aerial Central/gi, "Aerial")
      .replace(/Central Dueler/gi, "Dueler");
  }

  function renderMondayTable() {
    const players = filteredPlayers();
    const positions = state.positions.length
      ? state.positions
      : [...new Set(players.map((row) => row.position).filter(Boolean))].map((id) => ({
          id,
          label: id,
        }));

    const groups = positions
      .map((pos) => ({
        pos,
        rows: players.filter((row) => row.position === pos.id),
        profiles: profilesForPosition(pos.id, players.filter((row) => row.position === pos.id)),
      }))
      .filter((group) => group.rows.length);

    const known = new Set(positions.map((pos) => pos.id));
    const other = players.filter((row) => !row.position || !known.has(row.position));
    if (other.length) {
      // Never invent profile columns for Other — that dumped every PV metric.
      groups.push({
        pos: { id: "", label: "Other (no position yet)" },
        rows: other,
        profiles: [],
      });
    }

    if (!groups.length) {
      els.club.innerHTML = `<div class="st-monday-empty">No players match.</div>`;
      return;
    }

    const positioned = groups.filter((group) => group.pos.id);
    const maxProfiles = Math.max(
      1,
      ...(positioned.length ? positioned.map((group) => group.profiles.length) : [1])
    );

    function profileHeaderCells(profiles) {
      const cells = [];
      for (let i = 0; i < maxProfiles; i += 1) {
        const profile = profiles[i];
        if (!profile) {
          cells.push(`<th class="st-th st-th--pad" aria-hidden="true"></th>`);
          continue;
        }
        cells.push(
          `<th class="st-th st-th--prof" title="${esc(profile.label)}">
            <span class="st-prof-head">
              <span>${esc(shortProfileLabel(profile.label))}</span>
              <span class="st-prof-head__scout">Scout</span>
            </span>
          </th>`
        );
      }
      return cells.join("");
    }

    function profileDataCells(profiles, player) {
      const cells = [];
      for (let i = 0; i < maxProfiles; i += 1) {
        const profile = profiles[i];
        if (!profile) {
          cells.push(`<td class="st-td st-td--pad" aria-hidden="true"></td>`);
          continue;
        }
        const value = player.profile_scores?.[profile.apiName];
        cells.push(
          `<td class="st-td st-td--prof">
            <span class="st-prof-stack">
              ${scoreChip(value, { title: profile.label })}
              ${scoutScoreInput(player, profile.apiName, profile.label)}
            </span>
          </td>`
        );
      }
      return cells.join("");
    }

    function tableColgroup() {
      const profCols = Array.from({ length: maxProfiles }, () => `<col class="st-col--prof" />`).join("");
      return `<colgroup>
        <col class="st-col--player" />
        <col class="st-col--ovr" />
        <col class="st-col--age" />
        <col class="st-col--mins" />
        <col class="st-col--ft" />
        ${profCols}
        <col class="st-col--status" />
        <col class="st-col--link" />
        <col class="st-col--comment" />
      </colgroup>`;
    }

    els.club.innerHTML = `<div class="st-monday">
      <div class="st-monday__scroll">
        ${groups
          .map(({ pos, rows, profiles }) => {
            const color = POS_COLORS[pos.id] || "#6b7280";
            return `<section class="st-group" style="--pos:${esc(color)}">
              <header class="st-group__head">
                <span class="st-group__dot"></span>
                <h2 class="st-group__title">${esc(pos.label)}</h2>
                <span class="st-group__count">${rows.length}</span>
              </header>
              <div class="st-table-wrap">
                <table class="st-table">
                  ${tableColgroup()}
                  <thead>
                    <tr>
                      <th class="st-th st-th--player">Player</th>
                      <th class="st-th">Ovr</th>
                      <th class="st-th">Age</th>
                      <th class="st-th">Mins</th>
                      <th class="st-th">Ft</th>
                      ${profileHeaderCells(profiles)}
                      <th class="st-th st-th--status">Pipeline</th>
                      <th class="st-th st-th--link"></th>
                      <th class="st-th st-th--comment">Comments</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${rows
                      .map((player) => {
                        const inPipe = Boolean(player.pipeline_stage);
                        return `<tr class="st-row${inPipe ? " is-piped" : ""}" style="--stage:${esc(
                          player.pipeline_stage_color || color
                        )}" data-player-id="${esc(player.player_id)}">
                          <td class="st-td st-td--player">
                            <span class="st-namecell">
                              <strong>${esc(player.name)}</strong>
                              ${
                                player.top_profile
                                  ? `<span class="st-namecell__hint">${esc(
                                      shortProfileLabel(player.top_profile)
                                    )}</span>`
                                  : ""
                              }
                            </span>
                          </td>
                          <td class="st-td st-td--center">${scoreChip(player.overall, { title: "Overall" })}</td>
                          <td class="st-td st-td--center"><span class="st-plain">${
                            player.age != null ? esc(player.age) : "—"
                          }</span></td>
                          <td class="st-td st-td--center"><span class="st-plain">${
                            player.minutes != null ? esc(Number(player.minutes).toLocaleString()) : "—"
                          }</span></td>
                          <td class="st-td st-td--center"><span class="st-plain">${esc(player.foot || "—")}</span></td>
                          ${profileDataCells(profiles, player)}
                          <td class="st-td st-td--status">${stageSelect(player)}</td>
                          <td class="st-td st-td--link">${
                            player.dossier_href
                              ? `<a class="st-link" href="${esc(player.dossier_href)}" target="_blank" rel="noopener">Dossier</a>`
                              : ""
                          }</td>
                          <td class="st-td st-td--comment">${scoutCommentInput(player)}</td>
                        </tr>`;
                      })
                      .join("")}
                  </tbody>
                </table>
              </div>
            </section>`;
          })
          .join("")}
      </div>
    </div>`;
    wireStatusSelects(els.club);
    wireScoutFields(els.club);
  }

  function renderClubBoard() {
    if (state.view === "table") {
      renderMondayTable();
      return;
    }

    const players = filteredPlayers();
    const positions = state.positions.length
      ? state.positions
      : [...new Set(players.map((row) => row.position).filter(Boolean))].map((id) => ({
          id,
          label: id,
        }));

    els.club.innerHTML = `<div class="st-club-board">
      ${positions
        .map((pos) => {
          const cards = players.filter((row) => row.position === pos.id);
          if (!cards.length && filterText()) return "";
          const color = POS_COLORS[pos.id] || "#3d8bfd";
          return `<section class="st-col" style="--pos:${esc(color)}">
            <header class="st-col__head">
              <h2 class="st-col__title">
                <span>${esc(pos.label)}</span>
                <span>${cards.length}</span>
              </h2>
            </header>
            <div class="st-col__list">
              ${cards.map(playerCard).join("") || `<p class="st-empty">No players</p>`}
            </div>
          </section>`;
        })
        .filter(Boolean)
        .join("")}
      ${(() => {
        const known = new Set(positions.map((pos) => pos.id));
        const other = players.filter((row) => !known.has(row.position));
        if (!other.length) return "";
        return `<section class="st-col" style="--pos:#6b7280">
          <header class="st-col__head">
            <h2 class="st-col__title"><span>Other</span><span>${other.length}</span></h2>
          </header>
          <div class="st-col__list">${other.map(playerCard).join("")}</div>
        </section>`;
      })()}
    </div>`;
    wireStatusSelects(els.club);
    wireScoutFields(els.club);
  }

  function setMode(mode) {
    state.mode = mode;
    const isClub = mode === "club";
    els.leagues.classList.toggle("hidden", isClub);
    els.club.classList.toggle("hidden", !isClub);
    els.back.classList.toggle("hidden", !isClub);
    els.clubToggle.classList.toggle("hidden", !isClub);
    els.filter.placeholder = isClub ? "Filter players" : "Club name";
    if (!isClub) {
      els.title.textContent = "Scoutable Teams";
      els.sub.textContent =
        "Every club by league — comment + Enter → Watched (lowest stage). Move up to Scout identified when you want to push them forward.";
      renderLeagues();
    }
  }

  function setClubView(view) {
    state.view = view === "board" ? "board" : "table";
    localStorage.setItem(VIEW_KEY, state.view);
    els.viewBoard.classList.toggle("is-active", state.view === "board");
    els.viewTable.classList.toggle("is-active", state.view === "table");
    if (state.mode === "club") renderClubBoard();
  }

  async function openClub(club) {
    setStatus(`Loading ${club.name}…`);
    try {
      const params = new URLSearchParams({
        club: club.name,
        league: club.league || "",
        squad_id: String(club.squad_id || ""),
        iteration_id: String(club.iteration_id || ""),
      });
      const data = await fetchJson(`/api/scoutable-teams/club?${params}`);
      state.club = data;
      if (data.stages?.length) state.stages = data.stages;
      if (data.positions?.length) state.positions = data.positions;
      state.profilesByPosition = data.profiles_by_position || {};
      els.title.textContent = data.club || club.name;
      els.sub.textContent = [
        data.league,
        data.season ? `Season ${data.season}` : "",
        `${data.player_count || 0} players`,
        "Default: Not in pipeline — comment + Enter → Watched. Scout identified = touted to progress",
      ]
        .filter(Boolean)
        .join(" · ");
      setMode("club");
      setClubView(state.view);
      setStatus("");
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  function requestStatusChange(player, stage, selectEl) {
    if (!stage) {
      applyStatus(player, "", "", selectEl);
      return;
    }
    const stageMeta = state.stages.find((row) => row.id === stage);
    if (stageMeta?.require_reason) {
      state.pendingStatus = { player, stage, selectEl };
      els.reasonError.hidden = true;
      els.reasonText.value = "";
      els.reasonModal.hidden = false;
      setTimeout(() => els.reasonText.focus(), 30);
      return;
    }
    applyStatus(player, stage, "", selectEl);
  }

  async function applyStatus(player, stage, reason, selectEl) {
    const previous = player.pipeline_stage || "";
    const playerId = player.player_id;
    const pendingSave = scoutSaveTimers.get(playerId);
    if (pendingSave) {
      clearTimeout(pendingSave);
      scoutSaveTimers.delete(playerId);
    }
    setStatus(stage ? `Updating ${player.name}…` : `Removing ${player.name} from pipelines…`);
    try {
      const data = await fetchJson("/api/scoutable-teams/set-status", {
        method: "POST",
        body: JSON.stringify({
          player_id: player.player_id,
          name: player.name,
          club: player.club || state.club?.club || "",
          league: player.league || state.club?.league || "",
          position: player.position || "",
          position_label: player.position_label || "",
          age: player.age ?? null,
          stage: stage || "",
          reason,
        }),
      });
      if (!stage || data.removed) {
        player.in_pipeline = false;
        player.pipeline_stage = "";
        player.pipeline_stage_title = "";
        player.pipeline_stage_color = "";
        player.pipeline_target_id = "";
        if (selectEl) selectEl.value = "";
        renderClubBoard();
        setStatus(`${player.name} is Not in pipeline.`);
        return;
      }
      const target = data.target || {};
      player.in_pipeline = true;
      player.pipeline_stage = target.stage || stage;
      player.pipeline_stage_title =
        state.stages.find((row) => row.id === player.pipeline_stage)?.title || stage;
      player.pipeline_stage_color =
        state.stages.find((row) => row.id === player.pipeline_stage)?.color || "#3d8bfd";
      player.pipeline_target_id = target.id || "";
      if (selectEl) selectEl.value = player.pipeline_stage;
      renderClubBoard();
      const verb = data.created ? "added to" : data.moved ? "moved on" : "already on";
      setStatus(
        `${player.name} ${verb} Player Pipelines → ${player.pipeline_stage_title}.`
      );
    } catch (err) {
      if (selectEl) selectEl.value = previous;
      setStatus(err.message || String(err), true);
    }
  }

  async function loadBoard() {
    setStatus("Loading leagues…");
    try {
      const data = await fetchJson("/api/scoutable-teams");
      state.leagues = data.leagues || [];
      state.stages = data.stages || [];
      state.positions = data.positions || [];
      setMode("leagues");
      setStatus("");
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  els.filter.addEventListener("input", () => {
    if (state.mode === "club") renderClubBoard();
    else renderLeagues();
  });
  els.back.addEventListener("click", () => {
    state.club = null;
    els.filter.value = "";
    loadBoard();
  });
  els.viewBoard.addEventListener("click", () => setClubView("board"));
  els.viewTable.addEventListener("click", () => setClubView("table"));

  document.querySelectorAll("[data-close-reason]").forEach((el) => {
    el.addEventListener("click", () => {
      els.reasonModal.hidden = true;
      if (state.pendingStatus?.selectEl) {
        state.pendingStatus.selectEl.value = state.pendingStatus.player.pipeline_stage || "";
      }
      state.pendingStatus = null;
    });
  });

  els.reasonForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const reason = els.reasonText.value.trim();
    if (reason.length < 8) {
      els.reasonError.hidden = false;
      return;
    }
    const pending = state.pendingStatus;
    els.reasonModal.hidden = true;
    state.pendingStatus = null;
    if (!pending) return;
    await applyStatus(pending.player, pending.stage, reason, pending.selectEl);
  });

  // Sync toggle UI on boot (table is default).
  els.viewBoard.classList.toggle("is-active", state.view === "board");
  els.viewTable.classList.toggle("is-active", state.view === "table");

  const params = new URLSearchParams(window.location.search);
  loadBoard().then(() => {
    const club = params.get("club");
    if (club) {
      openClub({
        name: club,
        league: params.get("league") || "",
        squad_id: Number(params.get("squad_id") || 0) || null,
        iteration_id: Number(params.get("iteration_id") || 0) || null,
      });
    }
  });
})();
