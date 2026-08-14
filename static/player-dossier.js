(function initPlayerDossier() {
  const statusEl = document.getElementById("pdStatus");
  const errorEl = document.getElementById("pdError");
  const heroEl = document.getElementById("pdHero");
  const gridEl = document.getElementById("pdGrid");
  const actionsEl = document.getElementById("pdActions");
  const keyStatsCard = document.getElementById("pdKeyStatsCard");

  function playerIdFromPath() {
    const match = window.location.pathname.match(/\/player\/(\d+)/);
    return match ? Number(match[1]) : null;
  }

  function seasonFromQuery() {
    const value = new URLSearchParams(window.location.search).get("iteration");
    return value && /^\d+$/.test(value) ? Number(value) : null;
  }

  function fmt(n, digits = 0) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return Number(n).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    });
  }

  function formatStat(stat) {
    if (stat.format === "text") return stat.value == null || stat.value === "" ? "—" : String(stat.value);
    if (stat.value == null || Number.isNaN(Number(stat.value))) return "—";
    if (stat.format === "2") return fmt(stat.value, 2);
    if (stat.format === "1") return fmt(stat.value, 1);
    return fmt(stat.value, 0);
  }

  function setStatus(message) {
    if (!message) {
      statusEl.hidden = true;
      statusEl.textContent = "";
      return;
    }
    statusEl.hidden = false;
    statusEl.textContent = message;
  }

  function setError(message) {
    if (!message) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = message;
  }

  function initials(name) {
    return String(name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() || "")
      .join("");
  }

  function starGlyphs(value, max = 5) {
    const rating = Math.max(0, Math.min(max, Number(value) || 0));
    const full = Math.floor(rating);
    const half = rating - full >= 0.5 ? 1 : 0;
    const empty = max - full - half;
    const parts = [];
    for (let i = 0; i < full; i += 1) parts.push('<span class="pd-star is-full" aria-hidden="true">★</span>');
    if (half) parts.push('<span class="pd-star is-half" aria-hidden="true">★</span>');
    for (let i = 0; i < empty; i += 1) parts.push('<span class="pd-star is-empty" aria-hidden="true">★</span>');
    return `<span class="pd-stars" title="${rating} / ${max}">${parts.join("")}</span>`;
  }

  function renderAbility(ability) {
    const root = document.getElementById("pdAbility");
    if (!root) return;
    if (!ability || (ability.current == null && ability.potential == null)) {
      root.hidden = true;
      root.innerHTML = "";
      return;
    }
    const max = ability.max || 5;
    const rows = [
      ability.current != null
        ? `<div class="pd-ability__row">
            <span class="pd-ability__label">Current ability</span>
            ${starGlyphs(ability.current, max)}
            <span class="pd-ability__score">${ability.current}</span>
          </div>`
        : "",
      ability.potential != null
        ? `<div class="pd-ability__row">
            <span class="pd-ability__label">Potential ability</span>
            ${starGlyphs(ability.potential, max)}
            <span class="pd-ability__score">${ability.potential}</span>
          </div>`
        : "",
    ]
      .filter(Boolean)
      .join("");
    root.innerHTML = `${rows}<p class="pd-ability__note">${ability.label || "Scout rating"}${
      ability.source === "example" ? " — sample until live reports are filed" : ""
    }</p>`;
    root.hidden = false;
  }

  const chartState = {
    playerId: null,
    iterationId: null,
    selectedPosition: null,
  };

  function setProfileSubtitle(label) {
    const card = document.querySelector(".pd-card--radar .pd-card__sub");
    if (!card) return;
    card.textContent = label
      ? `Port Vale Impect · ${label}`
      : "Port Vale Impect profiles";
  }

  function renderPositions(player) {
    const root = document.getElementById("pdPositions");
    const positions = player.positions || [];
    if (!positions.length) {
      root.innerHTML = "";
      return;
    }
    const selected = chartState.selectedPosition || player.primary_position;
    root.innerHTML = positions
      .map((pos) => {
        const active = pos.code === selected;
        const mins =
          pos.minutes != null && !Number.isNaN(Number(pos.minutes))
            ? `${fmt(pos.minutes)}′`
            : "—";
        return `<button type="button" class="pd-pos${active ? " is-primary" : ""}" data-position="${pos.code}" title="${pos.label || pos.code} · ${mins}" aria-pressed="${active ? "true" : "false"}">${pos.abbrev} · ${mins}</button>`;
      })
      .join("");
  }

  async function loadProfilesForPosition(positionCode) {
    if (!chartState.playerId || !positionCode) return;
    const legend = document.getElementById("pdProfiles");
    const radarEl = document.getElementById("pdRadar");
    legend.innerHTML = `<p class="pd-empty">Loading profiles…</p>`;
    radarEl.innerHTML = "";
    chartState.selectedPosition = positionCode;
    document.querySelectorAll("#pdPositions .pd-pos").forEach((btn) => {
      const active = btn.getAttribute("data-position") === positionCode;
      btn.classList.toggle("is-primary", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    try {
      const url =
        `/api/player/${chartState.playerId}/profiles?position=${encodeURIComponent(positionCode)}` +
        (chartState.iterationId ? `&iteration=${chartState.iterationId}` : "");
      const res = await fetch(url, { cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(60000) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setProfileSubtitle(data.position_label || positionCode);
      renderProfiles(data.profiles || []);
    } catch (err) {
      legend.innerHTML = `<p class="pd-empty">Could not load profiles (${err.message || err}).</p>`;
      radarEl.innerHTML = "";
    }
  }

  function wirePositionButtons() {
    document.getElementById("pdPositions")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-position]");
      if (!btn) return;
      const code = btn.getAttribute("data-position");
      if (!code || code === chartState.selectedPosition) return;
      loadProfilesForPosition(code);
    });
  }

  function renderHero(player, heroStats, ability) {
    document.title = `${player.name} · Port Vale Hub`;
    document.getElementById("pdClubSeason").textContent =
      `${player.club} · ${player.league} · ${player.season}`;
    document.getElementById("pdName").textContent = player.name;
    document.getElementById("pdMeta").textContent = [
      player.primary_position_label && player.primary_position_label !== "—"
        ? player.primary_position_label
        : null,
      player.age != null ? `Age ${player.age}` : null,
      player.foot && player.foot !== "—" ? `Foot ${player.foot}` : null,
      player.height && player.height !== "—" ? player.height : null,
      `ID ${player.id}`,
    ]
      .filter(Boolean)
      .join(" · ");

    const tags = [];
    if (player.citizenship) tags.push({ text: player.citizenship, gold: false });
    if (player.market_value) tags.push({ text: player.market_value, gold: true });
    if (player.on_loan_from) tags.push({ text: `Loan from ${player.on_loan_from}`, gold: true });
    document.getElementById("pdTags").innerHTML = tags
      .map((tag) => `<span class="pd-tag${tag.gold ? " pd-tag--gold" : ""}">${tag.text}</span>`)
      .join("");

    renderAbility(ability);

    const photo = document.getElementById("pdPhoto");
    const fallback = document.getElementById("pdPhotoFallback");
    fallback.textContent = initials(player.name);
    fallback.hidden = true;
    photo.hidden = false;
    photo.alt = player.name;
    photo.onerror = () => {
      photo.hidden = true;
      fallback.hidden = false;
    };
    photo.src = player.photo_url;

    document.getElementById("pdBioStats").innerHTML = [
      { label: "Height", value: player.height || "—" },
      { label: "Minutes", value: fmt(player.minutes) },
      { label: "Matches", value: fmt(player.matches) },
      { label: "Positions", value: String((player.positions || []).length || "—") },
    ]
      .map(
        (stat) => `<div class="pd-stat">
          <span class="pd-stat__label">${stat.label}</span>
          <span class="pd-stat__value">${stat.value}</span>
        </div>`
      )
      .join("");

    const metrics = heroStats || [];
    document.getElementById("pdHeroMetrics").innerHTML = metrics
      .map(
        (stat) => `<div class="pd-metric">
          <span class="pd-metric__source">${stat.source || "Data"}</span>
          <span class="pd-metric__label">${stat.label}</span>
          <span class="pd-metric__value">${formatStat(stat)}</span>
        </div>`
      )
      .join("");

    chartState.selectedPosition = player.primary_position || positionsFirstCode(player);
    renderPositions(player);
    if (player.primary_position_label) {
      setProfileSubtitle(player.primary_position_label);
    }

    heroEl.hidden = false;
  }

  function positionsFirstCode(player) {
    return (player.positions || [])[0]?.code || null;
  }

  function renderKeyStats(stats) {
    if (!stats?.length) {
      keyStatsCard.hidden = true;
      return;
    }
    document.getElementById("pdKeyStats").innerHTML = stats
      .map(
        (stat) => `<div class="pd-keystat">
          <span class="pd-keystat__label">${stat.label}${stat.source ? ` · ${stat.source}` : ""}</span>
          <span class="pd-keystat__value">${formatStat(stat)}</span>
        </div>`
      )
      .join("");
    keyStatsCard.hidden = false;
  }

  function renderFbref(fbref, link) {
    const card = document.getElementById("pdFbrefCard");
    if (!fbref) {
      card.hidden = true;
      return;
    }
    const linkEl = document.getElementById("pdFbrefLink");
    if (link || fbref.profile_url) {
      linkEl.href = link || fbref.profile_url;
      linkEl.hidden = false;
    } else {
      linkEl.hidden = true;
    }
    const stats = [
      { label: "Season", value: fbref.season, format: "text", source: "FBRef" },
      { label: "Squad", value: fbref.squad, format: "text", source: "FBRef" },
      { label: "Mins", value: fbref.minutes, format: "int", source: "FBRef" },
      { label: "Goals", value: fbref.goals, format: "int", source: "FBRef" },
      { label: "Assists", value: fbref.assists, format: "int", source: "FBRef" },
      { label: "xG", value: fbref.xg, format: "2", source: "FBRef" },
      { label: "xA", value: fbref.xg_assist, format: "2", source: "FBRef" },
      { label: "npxG", value: fbref.npxg, format: "2", source: "FBRef" },
    ].filter((row) => row.value != null && row.value !== "");
    document.getElementById("pdFbrefStats").innerHTML = stats
      .map(
        (stat) => `<div class="pd-keystat">
          <span class="pd-keystat__label">${stat.label}</span>
          <span class="pd-keystat__value">${formatStat(stat)}</span>
        </div>`
      )
      .join("");
    const pips = fbref.scout_pips || [];
    document.getElementById("pdFbrefPips").innerHTML = pips
      .map(
        (row) => `<span class="pd-profile-chip">${row.label}<strong>${row.pct}</strong></span>`
      )
      .join("");
    card.hidden = !stats.length && !pips.length;
  }

  function renderProfiles(profiles) {
    const legend = document.getElementById("pdProfiles");
    const radarEl = document.getElementById("pdRadar");
    if (!profiles?.length) {
      legend.innerHTML = `<p class="pd-empty">No PV profiles for this season / position yet.</p>`;
      radarEl.innerHTML = "";
      return;
    }

    legend.innerHTML = profiles
      .map(
        (row) => `<span class="pd-profile-chip">${row.label}<strong>${row.pct}</strong></span>`
      )
      .join("");

    if (!window.Plotly) {
      radarEl.innerHTML = `<p class="pd-empty">Radar chart library failed to load.</p>`;
      return;
    }

    const labels = profiles.map((row) => row.label);
    const values = profiles.map((row) => row.pct);
    const closedLabels = [...labels, labels[0]];
    const closedValues = [...values, values[0]];

    window.Plotly.newPlot(
      radarEl,
      [
        {
          type: "scatterpolar",
          mode: "lines+markers",
          r: closedValues,
          theta: closedLabels,
          fill: "toself",
          name: "PV profiles",
          line: { color: "#3d8bfd", width: 2.5, shape: "spline", smoothing: 0.7 },
          marker: { color: "#34d399", size: 6 },
          fillcolor: "rgba(61, 139, 253, 0.22)",
          hovertemplate: "<b>%{theta}</b><br>%{r:.0f}<extra></extra>",
        },
      ],
      {
        margin: { t: 36, r: 48, b: 36, l: 48 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        showlegend: false,
        font: { family: '"DM Sans", system-ui, sans-serif', color: "#e8edf4", size: 12 },
        polar: {
          bgcolor: "rgba(0,0,0,0)",
          radialaxis: {
            visible: true,
            range: [0, 100],
            tickvals: [20, 40, 60, 80, 100],
            tickfont: { size: 10, color: "#8b9bb0" },
            gridcolor: "rgba(148, 163, 184, 0.18)",
            linecolor: "rgba(148, 163, 184, 0.12)",
          },
          angularaxis: {
            direction: "clockwise",
            rotation: 90,
            tickfont: { size: labels.length > 6 ? 10 : 12, color: "#e8edf4" },
            gridcolor: "rgba(148, 163, 184, 0.14)",
            linecolor: "rgba(148, 163, 184, 0.08)",
          },
        },
      },
      { responsive: true, displayModeBar: false }
    );
  }

  function renderEntryList(rootId, rows, emptyMessage) {
    const root = document.getElementById(rootId);
    if (!root) return;
    if (!rows?.length) {
      root.innerHTML = `<p class="pd-empty">${emptyMessage}</p>`;
      return;
    }
    root.innerHTML = rows
      .map((row) => {
        const kind = row.kind === "report" ? "report" : "note";
        const abilityBits =
          kind === "report"
            ? [
                row.current_ability != null
                  ? `<span class="pd-report__ability"><em>CA</em>${starGlyphs(row.current_ability)}</span>`
                  : "",
                row.potential_ability != null
                  ? `<span class="pd-report__ability"><em>PA</em>${starGlyphs(row.potential_ability)}</span>`
                  : "",
              ]
                .filter(Boolean)
                .join("")
            : "";
        const badges = [
          row.example ? `<span class="pd-chip pd-chip--example">Example</span>` : "",
          kind === "report"
            ? `<span class="pd-chip pd-chip--report">Report</span>`
            : `<span class="pd-chip">Note</span>`,
        ]
          .filter(Boolean)
          .join("");
        const tag = row.href ? "a" : "div";
        const href = row.href ? ` href="${row.href}"` : "";
        const deleteBtn =
          row.editable && row.id
            ? `<button type="button" class="pd-report__delete" data-delete-note="${row.id}">Delete</button>`
            : "";
        return `<${tag} class="pd-report"${href}>
          <div class="pd-report__top">
            <p class="pd-report__title">${row.fixture}</p>
            <div class="pd-report__badges">${badges}${deleteBtn}</div>
          </div>
          <p class="pd-report__meta">${[
            row.staff && (kind === "report" ? `Scout: ${row.staff}` : row.staff),
            row.team,
            row.position,
            row.date,
          ]
            .filter(Boolean)
            .join(" · ")}</p>
          ${abilityBits ? `<div class="pd-report__stars">${abilityBits}</div>` : ""}
          ${row.summary ? `<p class="pd-report__summary">${row.summary}</p>` : ""}
        </${tag}>`;
      })
      .join("");
  }

  function renderNotes(notes) {
    renderEntryList(
      "pdNotes",
      notes,
      "No notes yet. Log agent chats, chasing, and work updates here."
    );
  }

  function renderReports(reports) {
    renderEntryList(
      "pdReports",
      reports,
      "No scout reports yet. Use <strong>Add report</strong> for a full look with CA / PA."
    );
  }

  function applyActivityPayload(data) {
    renderNotes(data.notes || []);
    renderReports(data.reports || []);
    renderAbility(data.ability);
  }

  const noteState = {
    playerId: null,
    playerName: "",
    kind: "note",
    ca: 0,
    pa: 0,
  };

  function renderStarPicker(root, value, onChange) {
    if (!root) return;
    const max = Number(root.dataset.max || 5);
    const current = Number(value) || 0;
    root.dataset.value = String(current);
    root.innerHTML = Array.from({ length: max }, (_, idx) => {
      const score = idx + 1;
      const active = score <= current;
      return `<button type="button" class="pd-star-picker__btn${active ? " is-active" : ""}" data-score="${score}" aria-label="${score} stars">★</button>`;
    }).join("");
    root.querySelectorAll("[data-score]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = Number(btn.dataset.score);
        const cleared = next === current ? 0 : next;
        onChange(cleared);
        renderStarPicker(root, cleared, onChange);
      });
    });
  }

  function openEntryModal(kind) {
    const modal = document.getElementById("pdNoteModal");
    if (!modal) return;
    const isReport = kind === "report";
    noteState.kind = isReport ? "report" : "note";
    noteState.ca = 0;
    noteState.pa = 0;
    document.getElementById("pdNoteForm").reset();
    document.getElementById("pdNoteKind").value = noteState.kind;
    document.getElementById("pdNoteError").hidden = true;
    document.getElementById("pdNoteModalHeading").textContent = isReport
      ? "Add scout report"
      : "Add notes";
    document.getElementById("pdNoteStaffLabel").textContent = isReport ? "Scout" : "Author";
    document.getElementById("pdNoteBodyLabel").textContent = isReport ? "Report" : "Notes";
    document.getElementById("pdNoteSummary").placeholder = isReport
      ? "What did you see? Strengths, weaknesses, role fit…"
      : "Work update, agent chat, chasing status…";
    document.getElementById("pdNoteTitleInput").placeholder = isReport
      ? "e.g. Live look · Vale Park"
      : "e.g. Agent call · transfer update";
    document.getElementById("pdNoteSave").textContent = isReport ? "Save report" : "Save notes";
    document.getElementById("pdNoteAbilityWrap").hidden = !isReport;
    document.getElementById("pdNotePositionWrap").hidden = !isReport;
    if (isReport) {
      renderStarPicker(document.getElementById("pdNoteCa"), 0, (v) => {
        noteState.ca = v;
      });
      renderStarPicker(document.getElementById("pdNotePa"), 0, (v) => {
        noteState.pa = v;
      });
    }
    modal.hidden = false;
    document.getElementById("pdNoteSummary")?.focus();
  }

  function closeNoteModal() {
    const modal = document.getElementById("pdNoteModal");
    if (modal) modal.hidden = true;
  }

  async function saveNote(event) {
    event.preventDefault();
    const errorEl = document.getElementById("pdNoteError");
    const saveBtn = document.getElementById("pdNoteSave");
    const summary = document.getElementById("pdNoteSummary").value.trim();
    const kind = noteState.kind === "report" ? "report" : "note";
    if (!summary) {
      errorEl.textContent = kind === "report" ? "Add report text before saving." : "Add some notes before saving.";
      errorEl.hidden = false;
      return;
    }
    errorEl.hidden = true;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    try {
      const res = await fetch(`/api/player/${noteState.playerId}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          kind,
          title: document.getElementById("pdNoteTitleInput").value.trim(),
          staff: document.getElementById("pdNoteStaff").value.trim(),
          position: kind === "report" ? document.getElementById("pdNotePosition").value.trim() : "",
          summary,
          current_ability: kind === "report" ? noteState.ca || null : null,
          potential_ability: kind === "report" ? noteState.pa || null : null,
          date: new Date().toISOString().slice(0, 10),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      applyActivityPayload(data);
      closeNoteModal();
    } catch (err) {
      errorEl.textContent = err.message || String(err);
      errorEl.hidden = false;
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = kind === "report" ? "Save report" : "Save notes";
    }
  }

  async function deleteNote(noteId) {
    if (!noteId || !noteState.playerId) return;
    if (!window.confirm("Delete this entry?")) return;
    try {
      const res = await fetch(`/api/player/${noteState.playerId}/notes/${noteId}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      applyActivityPayload(data);
    } catch (err) {
      setError(err.message || String(err));
    }
  }

  function pipelineStageLabel(stage) {
    if (stage === "data_identified") return "Data identified";
    if (stage === "video_scouted") return "Video scouted";
    if (stage === "live_scouted") return "Live scouted";
    if (stage === "gone_elsewhere") return "Gone / turned us down";
    return "";
  }

  function setPipelineButton(inPipeline, stageTitle) {
    const btn = document.getElementById("pdPipelineBtn");
    const link = document.getElementById("pdPipelineLink");
    if (!btn) return;
    if (inPipeline) {
      btn.textContent = stageTitle ? `In pipeline · ${stageTitle}` : "In pipeline";
      btn.disabled = true;
      if (link) link.hidden = false;
    } else {
      btn.textContent = "Add to pipeline";
      btn.disabled = false;
      if (link) link.hidden = true;
    }
  }

  async function refreshPipelineStatus(playerId) {
    try {
      const res = await fetch(`/api/player-pipelines/status?player_id=${playerId}`, { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      setPipelineButton(Boolean(data.in_pipeline), pipelineStageLabel(data.target?.stage));
    } catch (_err) {
      /* optional */
    }
  }

  function wirePipelineButton(player) {
    const btn = document.getElementById("pdPipelineBtn");
    if (!btn) return;
    if (btn.dataset.wired !== "1") {
      btn.dataset.wired = "1";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Adding…";
        try {
          const res = await fetch("/api/player-pipelines/targets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              player_id: player.id,
              name: player.name || "",
              club: player.club || "",
              league: player.league || "",
              position: player.primary_position || "",
              position_label: player.primary_position_label || "",
              age: player.age ?? null,
              photo_url: player.photo_url || "",
              stage: "data_identified",
            }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
          await refreshPipelineStatus(player.id);
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "Add to pipeline";
          setError(err.message || String(err));
        }
      });
    }
    refreshPipelineStatus(player.id);
  }

  function wireNotesUi() {
    document.getElementById("pdAddNoteBtn")?.addEventListener("click", () => openEntryModal("note"));
    document.getElementById("pdAddReportBtn")?.addEventListener("click", () => openEntryModal("report"));
    document.getElementById("pdNoteForm")?.addEventListener("submit", saveNote);
    document.querySelectorAll("[data-close-note]").forEach((el) => {
      el.addEventListener("click", closeNoteModal);
    });
    document.getElementById("pdNotes")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-delete-note]");
      if (!btn) return;
      event.preventDefault();
      event.stopPropagation();
      deleteNote(btn.getAttribute("data-delete-note"));
    });
    document.getElementById("pdReports")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-delete-note]");
      if (!btn) return;
      event.preventDefault();
      event.stopPropagation();
      deleteNote(btn.getAttribute("data-delete-note"));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeNoteModal();
    });
  }

  function shortDate(iso) {
    if (!iso || iso.length < 10) return iso || "—";
    const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function resultFromGame(game) {
    const match = String(game.score || "").match(/^(\d+)\s*[-–]\s*(\d+)$/);
    if (!match) return null;
    const home = Number(match[1]);
    const away = Number(match[2]);
    const ours = game.is_home ? home : away;
    const theirs = game.is_home ? away : home;
    if (ours > theirs) return "W";
    if (ours < theirs) return "L";
    return "D";
  }

  function venueChip(game) {
    const home = game.is_home === true || game.venue === "H";
    return `<span class="pd-chip pd-chip--venue">${home ? "H" : "A"}</span>`;
  }

  function renderGames(games, columns) {
    const root = document.getElementById("pdGames");
    if (!games?.length) {
      root.innerHTML = `<p class="pd-empty">No recent appearances found for this season.</p>`;
      return;
    }
    const preferred = [
      { key: "pxt_attack", label: "PXT att" },
      { key: "pxt_defend", label: "PXT def" },
      { key: "shot_xg", label: "xG" },
      { key: "goals", label: "G" },
    ];
    const cols = preferred.slice(0, 4);

    root.innerHTML = `<div class="pd-fixture-list">${games
      .map((game) => {
        const result = resultFromGame(game);
        const resultCls =
          result === "W" ? "is-win" : result === "D" ? "is-draw" : result === "L" ? "is-loss" : "";
        const impect = game.impect || {};
        const metrics = cols
          .map((c) => {
            const value = impect[c.key];
            const digits = String(c.key).includes("xg") || String(c.key).includes("pxt") ? 2 : 0;
            return `<span class="pd-metric"><em>${c.label}</em>${value == null ? "—" : fmt(value, digits)}</span>`;
          })
          .join("");
        return `<article class="pd-fixture pd-fixture--played">
          <div class="pd-fixture__when">
            <span class="pd-fixture__date">${shortDate(game.date)}</span>
            ${venueChip(game)}
          </div>
          <div class="pd-fixture__main">
            <p class="pd-fixture__opp">${game.opponent || "Opponent"}</p>
            <div class="pd-fixture__meta">
              <span class="pd-chip">${fmt(game.minutes)}′</span>
              <span class="pd-chip">${game.position_abbrev || "—"}</span>
            </div>
            <div class="pd-fixture__metrics">${metrics}</div>
          </div>
          <div class="pd-fixture__result">
            <span class="pd-result ${resultCls}">${result || "—"}</span>
            <span class="pd-fixture__score">${game.score || "—"}</span>
          </div>
        </article>`;
      })
      .join("")}</div>`;
  }

  function renderUpcoming(games) {
    const root = document.getElementById("pdUpcoming");
    const sub = document.getElementById("pdUpcomingSub");
    if (!root) return;
    if (!games?.length) {
      if (sub) sub.textContent = "FotMob · next for this club";
      root.innerHTML = `<p class="pd-empty">No upcoming fixtures scheduled for this club.</p>`;
      return;
    }
    const source = String(games[0]?.source || "fotmob").toLowerCase();
    if (sub) {
      sub.textContent =
        source === "fotmob"
          ? "FotMob · next for this club"
          : "Impect fallback · next for this club";
    }
    root.innerHTML = `<div class="pd-fixture-list">${games
      .map((game) => {
        const comp = game.competition || game.season || "";
        return `<article class="pd-fixture pd-fixture--next">
          <div class="pd-fixture__when">
            <span class="pd-fixture__date">${shortDate(game.date)}</span>
            ${venueChip(game)}
          </div>
          <div class="pd-fixture__main">
            <p class="pd-fixture__opp">${game.opponent || "TBC"}</p>
            <p class="pd-fixture__kick">${[game.time_label, comp].filter(Boolean).join(" · ") || "Kick-off TBC"}</p>
          </div>
        </article>`;
      })
      .join("")}</div>`;
  }

  function setGamesLoading() {
    const games = document.getElementById("pdGames");
    const upcoming = document.getElementById("pdUpcoming");
    if (games) games.innerHTML = `<p class="pd-empty">Loading recent games…</p>`;
    if (upcoming) upcoming.innerHTML = `<p class="pd-empty">Loading fixtures…</p>`;
  }

  async function loadGames(playerId, iteration, columns) {
    setGamesLoading();
    const url =
      `/api/player/${playerId}/games` + (iteration ? `?iteration=${iteration}` : "");
    try {
      const res = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(180000) });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      renderGames(data.recent_games, data.impect_columns || columns);
      renderUpcoming(data.upcoming_games);
    } catch (err) {
      const games = document.getElementById("pdGames");
      const upcoming = document.getElementById("pdUpcoming");
      const msg = err.message || String(err);
      if (games) games.innerHTML = `<p class="pd-empty">Could not load recent games (${msg}).</p>`;
      if (upcoming) upcoming.innerHTML = `<p class="pd-empty">Could not load fixtures (${msg}).</p>`;
    }
  }

  function renderSeasons(seasons, playerId) {
    const root = document.getElementById("pdSeasons");
    if (!seasons?.length) {
      root.innerHTML = `<p class="pd-empty">No seasons listed.</p>`;
      return;
    }
    root.innerHTML = seasons
      .map((season) => {
        const label = season.label || `${season.competition_name || ""} ${season.season || ""}`.trim();
        const club = season.club ? ` · ${season.club}` : "";
        const href = `/player/${playerId}?iteration=${season.iteration_id}`;
        return `<div class="pd-season-row">
          <a href="${href}">${label}</a>
          <span class="pd-season-row__meta">${club}${season.chartable ? "" : " · limited data"}</span>
        </div>`;
      })
      .join("");
  }

  async function load() {
    const playerId = playerIdFromPath();
    if (!playerId) {
      setStatus("");
      setError("Missing player id in URL.");
      return;
    }
    const iteration = seasonFromQuery();
    const url =
      `/api/player/${playerId}` + (iteration ? `?iteration=${iteration}` : "");
    setStatus("Loading player dossier from Impect…");
    setError("");
    try {
      const res = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(120000) });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      noteState.playerId = data.player.id;
      noteState.playerName = data.player.name;
      chartState.playerId = data.player.id;
      chartState.iterationId = data.player.iteration_id || iteration;
      chartState.selectedPosition = data.player.primary_position || null;
      renderHero(data.player, data.hero_stats, data.ability);
      renderKeyStats(data.hero_stats?.length ? data.hero_stats : data.key_stats);
      renderFbref(data.web?.fbref, data.links?.fbref);
      renderProfiles(data.profiles);
      renderNotes(data.notes);
      renderReports(data.reports);
      renderSeasons(data.seasons, data.player.id);

      const charts = document.getElementById("pdChartsLink");
      const compare = document.getElementById("pdCompareLink");
      if (data.links?.charts) charts.href = data.links.charts;
      if (data.links?.compare) compare.href = data.links.compare;
      wirePipelineButton(data.player);
      actionsEl.hidden = false;
      gridEl.hidden = false;
      setStatus("");

      if (data.games_deferred || !data.recent_games?.length || !data.upcoming_games?.length) {
        loadGames(playerId, iteration || data.player?.iteration_id, data.impect_columns);
      } else {
        renderGames(data.recent_games, data.impect_columns);
        renderUpcoming(data.upcoming_games);
      }
    } catch (err) {
      setStatus("");
      setError(err.message || String(err));
    }
  }

  wireNotesUi();
  wirePositionButtons();
  load();
})();
