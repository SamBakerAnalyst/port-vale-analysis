/* Exact A4 portrait pixel canvas @ 96dpi: 210mm × 297mm */
const SLIDE_EXPORT_WIDTH = 794;
const SLIDE_EXPORT_HEIGHT = 1123;
const EXPORT_SCALE = 2;
const PAPER_GAP_PX = 20;

const state = {
  meta: null,
  fixtures: [],
  report: null,
  loading: false,
  notes: {},
};

const els = {
  iterationId: document.getElementById("iterationId"),
  opponentId: document.getElementById("opponentId"),
  matchId: document.getElementById("matchId"),
  seasonToggle: document.getElementById("seasonToggle"),
  matchBar: document.getElementById("matchBar"),
  deck: document.getElementById("deck"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportPdfBtn: document.getElementById("exportPdfBtn"),
  exportPptxBtn: document.getElementById("exportPptxBtn"),
  editNotesBtn: document.getElementById("editNotesBtn"),
  notesPanel: document.getElementById("notesPanel"),
  closeNotesBtn: document.getElementById("closeNotesBtn"),
  saveNotesBtn: document.getElementById("saveNotesBtn"),
  notesInPossession: document.getElementById("notesInPossession"),
  notesOutPossession: document.getElementById("notesOutPossession"),
  notesConfirmedOut: document.getElementById("notesConfirmedOut"),
  notesPossiblyOut: document.getElementById("notesPossiblyOut"),
  notesSuspended: document.getElementById("notesSuspended"),
  playerNotesFields: document.getElementById("playerNotesFields"),
  deckViewport: document.getElementById("deckViewport"),
  paperScaler: document.getElementById("paperScaler"),
};

function fitPaperToViewport() {
  const shell = document.querySelector(".ph-deck-shell");
  if (!shell) return;

  const pages = document.querySelectorAll(".ph-page");
  const pageCount = Math.max(pages.length, 1);
  const shellWidth = shell.clientWidth;
  const shellHeight = shell.clientHeight;

  const scaleByWidth = (shellWidth - 24) / SLIDE_EXPORT_WIDTH;
  const totalDesignHeight = pageCount * SLIDE_EXPORT_HEIGHT + (pageCount - 1) * PAPER_GAP_PX;
  const scaleByHeight = (shellHeight - 16) / totalDesignHeight;
  const scale = Math.min(scaleByWidth, scaleByHeight, 1);

  document.documentElement.style.setProperty("--paper-scale", String(scale));

  if (els.paperScaler) {
    els.paperScaler.style.minHeight = `${totalDesignHeight * scale}px`;
  }
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `ph-status ph-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

function notesStorageKey() {
  const iterationId = els.iterationId.value || "0";
  const opponentId = els.opponentId.value || "0";
  return `pv-handout-notes:${iterationId}:${opponentId}`;
}

function loadNotes() {
  try {
    const raw = localStorage.getItem(notesStorageKey());
    state.notes = raw ? JSON.parse(raw) : {};
  } catch {
    state.notes = {};
  }
}

function saveNotes() {
  state.notes = {
    in_possession: els.notesInPossession.value.trim(),
    out_of_possession: els.notesOutPossession.value.trim(),
    confirmed_out: linesToList(els.notesConfirmedOut.value),
    possibly_out: linesToList(els.notesPossiblyOut.value),
    suspended: linesToList(els.notesSuspended.value),
    player_summaries: {},
  };
  els.playerNotesFields.querySelectorAll("textarea[data-player-id]").forEach((field) => {
    const summary = field.value.trim();
    if (summary) {
      state.notes.player_summaries[field.dataset.playerId] = summary;
    }
  });
  localStorage.setItem(notesStorageKey(), JSON.stringify(state.notes));
  if (state.report) renderDeck(state.report);
  setStatus("Notes saved.", "");
}

function linesToList(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function listToLines(items) {
  return (items || []).join("\n");
}

function applyNotesToHandout(handout) {
  const notes = state.notes || {};
  const merged = { ...handout };
  merged.team_style = {
    in_possession: notes.in_possession || handout.team_style?.in_possession || "",
    out_of_possession: notes.out_of_possession || handout.team_style?.out_of_possession || "",
  };
  merged.availability = {
    confirmed_out: notes.confirmed_out?.length ? notes.confirmed_out : handout.availability?.confirmed_out || [],
    possibly_out: notes.possibly_out?.length ? notes.possibly_out : handout.availability?.possibly_out || [],
    suspended: notes.suspended?.length ? notes.suspended : handout.availability?.suspended || [],
  };
  merged.key_players = (handout.key_players || []).map((player) => ({
    ...player,
    summary: notes.player_summaries?.[String(player.player_id)] || player.summary || "",
  }));
  return merged;
}

function populateNotesForm(handout) {
  const notes = state.notes || {};
  els.notesInPossession.value = notes.in_possession || handout.team_style?.in_possession || "";
  els.notesOutPossession.value = notes.out_of_possession || handout.team_style?.out_of_possession || "";
  els.notesConfirmedOut.value = listToLines(notes.confirmed_out || handout.availability?.confirmed_out);
  els.notesPossiblyOut.value = listToLines(notes.possibly_out || handout.availability?.possibly_out);
  els.notesSuspended.value = listToLines(notes.suspended || handout.availability?.suspended);

  els.playerNotesFields.innerHTML = (handout.key_players || [])
    .map(
      (player) => `<label class="ph-notes__field">
        <span>${player.shirt_number ? `${player.shirt_number}. ` : ""}${player.name} — summary</span>
        <textarea data-player-id="${player.player_id}" rows="2">${notes.player_summaries?.[String(player.player_id)] || player.summary || ""}</textarea>
      </label>`,
    )
    .join("");
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body,
    method: options.method || "GET",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

function crestHtml(team, className = "ph-match-bar__crest") {
  const name = team?.name || "?";
  const src = team?.image_url || team?.imageUrl || "";
  if (src) {
    return `<img class="${className}" src="${src}" alt="${name}" />`;
  }
  const initials = name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return `<div class="ph-match-bar__crest-fallback">${initials}</div>`;
}

function renderSeasonToggle() {
  const iterations = state.meta?.iterations || [];
  els.seasonToggle.innerHTML = iterations
    .map((iteration) => {
      const active = Number(iteration.id) === Number(els.iterationId.value);
      const label = iteration.season || iteration.label || "Season";
      const isCurrent = iterations[0]?.id === iteration.id;
      const buttonLabel = isCurrent ? `This season (${label})` : `Last season (${label})`;
      return `<button type="button" class="ph-season-btn${active ? " ph-season-btn--active" : ""}" data-iteration-id="${iteration.id}"${state.loading ? " disabled" : ""}>${buttonLabel}</button>`;
    })
    .join("");

  els.seasonToggle.querySelectorAll(".ph-season-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled || btn.classList.contains("ph-season-btn--active")) return;
      switchSeason(Number(btn.dataset.iterationId));
    });
  });
}

function opponentNameForId(opponentId) {
  const fixture = state.fixtures.find((row) => Number(row.opponent.id) === Number(opponentId));
  return fixture?.opponent?.name || state.report?.opponent?.name || "";
}

async function switchSeason(iterationId) {
  const previousName = opponentNameForId(els.opponentId.value);
  els.iterationId.value = String(iterationId);
  renderSeasonToggle();
  state.loading = true;
  renderSeasonToggle();
  setStatus("Switching season…", "loading");

  try {
    const data = await fetchJson(`/api/pre-match-handout/fixtures?iteration_id=${iterationId}`);
    state.fixtures = data.fixtures || [];
    if (!state.fixtures.length) {
      renderEmptyDeck("No opponents found for this season.");
      setStatus("");
      return;
    }
    const sameName = previousName
      ? state.fixtures.find((row) => row.opponent.name === previousName)
      : null;
    selectFixture(sameName || state.fixtures[0]);
    renderMatchBar();
    await loadReport();
  } catch (error) {
    setStatus(error.message, "error");
    renderEmptyDeck("Could not load this season.");
  } finally {
    state.loading = false;
    renderSeasonToggle();
  }
}

function selectFixture(fixture) {
  if (!fixture) return;
  els.matchId.value = String(fixture.match_id || "");
  els.opponentId.value = String(fixture.opponent.id);
}

function pickDefaultFixture() {
  const preferred = state.meta?.default_fixture;
  if (preferred?.opponent_id || preferred?.match_id) {
    const fromMeta = state.fixtures.find(
      (row) =>
        (preferred.match_id && Number(row.match_id) === Number(preferred.match_id)) ||
        (
          Number(row.opponent.id) === Number(preferred.opponent_id) &&
          (preferred.is_home === undefined || Boolean(row.is_home) === Boolean(preferred.is_home))
        ),
    );
    if (fromMeta) return fromMeta;
    if (preferred.opponent_name) {
      const byName = state.fixtures.find(
        (row) =>
          String(row.opponent.name || "").toLowerCase().includes(preferred.opponent_name.toLowerCase()) &&
          (preferred.is_home === undefined || Boolean(row.is_home) === Boolean(preferred.is_home)),
      );
      if (byName) return byName;
    }
  }
  for (const name of state.meta?.default_opponent_names || ["Rotherham"]) {
    const homeHit = state.fixtures.find(
      (row) => String(row.opponent.name || "").toLowerCase().includes(name.toLowerCase()) && row.is_home,
    );
    if (homeHit) return homeHit;
  }
  const upcoming = state.fixtures.filter((row) => row.match_id && !String(row.kickoff_label || "").match(/^\d/));
  if (upcoming.length) return upcoming[0];
  return state.fixtures[0];
}

function renderMatchBar() {
  const selectedMatchId = Number(els.matchId.value || 0);
  const selectedOpponentId = Number(els.opponentId.value || 0);
  els.matchBar.innerHTML = state.fixtures
    .map((fixture) => {
      const active = selectedMatchId
        ? Number(fixture.match_id) === selectedMatchId
        : Number(fixture.opponent.id) === selectedOpponentId;
      const matchDay = fixture.match_day ? `MD${fixture.match_day}` : "";
      const title = [fixture.opponent.name, matchDay, fixture.kickoff_label].filter(Boolean).join(" · ");
      return `<button type="button" class="ph-match-bar__item${active ? " ph-match-bar__item--active" : ""}" data-match-id="${fixture.match_id}" data-opponent-id="${fixture.opponent.id}" title="${title}">
        ${crestHtml(fixture.opponent)}
        <span class="ph-match-bar__kickoff">${fixture.kickoff_label || "vs"}</span>
      </button>`;
    })
    .join("");

  els.matchBar.querySelectorAll(".ph-match-bar__item").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.matchId.value = btn.dataset.matchId;
      els.opponentId.value = btn.dataset.opponentId;
      loadReport();
    });
  });
}

function pitchDisplayName(player) {
  const surname = String(player?.surname || "").trim();
  if (surname) {
    return surname.toUpperCase();
  }
  const name = String(player?.name || "").trim();
  if (!name) {
    return "";
  }
  const parts = name.split(/\s+/).filter(Boolean);
  return (parts[parts.length - 1] || name).toUpperCase();
}

function pitchKitStyle(kit = {}) {
  const resolved = kit || {};
  return [
    `--opp-kit:${resolved.primary || "#ffffff"}`,
    `--opp-kit-text:${resolved.text || "#111111"}`,
    `--opp-kit-border:${resolved.border || "#111111"}`,
    `--opp-gk-kit:${resolved.gk || "#111111"}`,
    `--opp-gk-text:${resolved.gk_text || "#f5c518"}`,
    `--opp-gk-border:${resolved.gk_border || resolved.gk_text || "#f5c518"}`,
  ].join(";");
}

function isGoalkeeper(player) {
  const position = String(player?.position || player?.formation_slot || "").toUpperCase();
  return position === "GOALKEEPER";
}

function predictedXiSourceLabel(meta = {}) {
  if (!meta?.source_opponent) {
    return "";
  }
  const venue = meta.source_venue ? ` (${meta.source_venue})` : "";
  const score = meta.source_score ? ` · ${meta.source_result || ""} ${meta.source_score}`.trim() : "";
  const formation = meta.formation ? ` · ${meta.formation}` : "";
  return `${meta.squad_name || "Opposition"} — last XI vs ${meta.source_opponent}${venue}${score}${formation}`;
}

function pitchCircleMarkersHtml(players, { compact = false } = {}) {
  const markerClass = compact ? "ph-circle ph-circle--mini" : "ph-circle ph-circle--main";
  return (players || [])
    .map((player, index) => {
      let left = Number(player.x_pct ?? 50);
      let top = Number(player.y_pct ?? 50);
      if (!compact) {
        left = Math.max(12, Math.min(88, left));
        top = top >= 84 ? 86 : top <= 20 ? 16 : Math.max(16, Math.min(86, top));
      }
      const number = player.shirt_number ?? "";
      const label = pitchDisplayName(player);
      const status = player.status || (player.sent_off ? "sent_off" : player.subbed_off ? "subbed_off" : "normal");
      const anchorBottom = !compact && top >= 82;
      const dotClass = isGoalkeeper(player) ? "ph-circle__dot ph-circle__dot--gk" : "ph-circle__dot ph-circle__dot--outfield";
      const titleParts = [player.name || label];
      if (status === "subbed_off") titleParts.push("Subbed off");
      if (status === "sent_off") titleParts.push("Sent off");
      return `<div class="${markerClass} ph-circle--${status}${anchorBottom ? " ph-circle--anchor-bottom" : ""}" style="left:${left}%;top:${top}%;z-index:${index + 1}" title="${titleParts.join(" · ")}">
        <span class="${dotClass}">${number || "·"}</span>
        <span class="ph-circle__name">${label}</span>
      </div>`;
    })
    .join("");
}

function pitchMarkersHtml(players) {
  return pitchCircleMarkersHtml(players, { compact: true });
}

function mainPitchMarkersHtml(players) {
  return pitchCircleMarkersHtml(players, { compact: false });
}

function renderAvailabilityList(items, emptyLabel) {
  if (!items?.length) {
    return `<li class="ph-availability__empty">${emptyLabel}</li>`;
  }
  return items.map((item) => `<li>${item}</li>`).join("");
}

function crestUrl(team) {
  if (team?.badge_url) return team.badge_url;
  const name = String(team?.name || "").toLowerCase();
  if (name.includes("port vale")) return "/standalone/port-vale-badge.png?v=2";
  return team?.image_url || team?.imageUrl || "";
}

function crestLargeHtml(team, className = "ph-topbar__crest-img") {
  const name = team?.name || "?";
  const src = crestUrl(team);
  if (src) {
    return `<img class="${className}" src="${src}" alt="${name}" />`;
  }
  const initials = name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return `<div class="${className} ph-topbar__crest-fallback">${initials}</div>`;
}

function renderFormStrip(formSequence) {
  const items = (formSequence || []).slice(-5);
  if (!items.length) {
    return `<div class="ph-topbar__form-wrap"><div class="ph-topbar__form-track"><span class="ph-topbar__form-empty">—</span></div></div>`;
  }
  const boxes = items
    .map((result, index) => {
      const label = index + 1;
      const isLatest = index === items.length - 1;
      return `<span class="ph-form-box ph-form-box--${result}${isLatest ? " ph-form-box--latest" : ""}" title="${result}">${label}</span>`;
    })
    .join("");
  return `<div class="ph-topbar__form-wrap" title="Oldest match on the left · most recent on the right">
    <div class="ph-topbar__form-arrow" aria-hidden="true"></div>
    <div class="ph-topbar__form-track">${boxes}</div>
  </div>`;
}

function renderTopBar(handout, report) {
  const fixture = report?.fixture || {};
  const portVale = fixture.port_vale || { name: "Port Vale" };
  const opponent = fixture.opponent || report?.opponent || { name: "Opponent" };
  const timePart =
    handout.time_line && handout.time_line !== "—" ? ` | ${handout.time_line} UK` : "";

  return `<header class="ph-topbar">
    <div class="ph-topbar__crest ph-topbar__crest--home">
      ${crestLargeHtml(portVale)}
    </div>
    <div class="ph-topbar__centre">
      <h1 class="ph-topbar__title">${handout.header_title || "OPPOSITION REPORT"}</h1>
      <p class="ph-topbar__datetime">${handout.date_line || "—"}${timePart}</p>
      <p class="ph-topbar__position">${handout.position_label || "POSITION: —"}</p>
      <div class="ph-topbar__form">
        <span class="ph-topbar__form-label">FORM:</span>
        ${renderFormStrip(handout.form_sequence)}
      </div>
    </div>
    <div class="ph-topbar__crest ph-topbar__crest--away">
      ${crestLargeHtml(opponent)}
    </div>
  </header>`;
}

function formatFootAbbrev(foot) {
  const value = String(foot || "").toLowerCase();
  if (value.includes("left")) return "L";
  if (value.includes("right")) return "R";
  if (value === "l" || value === "r") return value.toUpperCase();
  return foot || "—";
}

function renderPage1(handout, report) {
  const lineups = (handout.previous_lineups || []).slice(-3);
  const kitStyle = pitchKitStyle(handout.opponent_kit);
  const predictedSource = predictedXiSourceLabel(handout.predicted_xi_meta);
  const lineupsHtml = lineups
    .map(
      (lineup) => `<div class="ph-mini-lineup">
        <div class="ph-mini-lineup__head">
          <div>${lineup.opponent} (${lineup.venue})</div>
          <div class="ph-mini-lineup__result">${lineup.result} ${lineup.score}${lineup.formation ? ` · ${lineup.formation}` : ""}</div>
        </div>
        <div class="ph-mini-pitch" style="${kitStyle}">
          <div class="ph-mini-pitch__markings"></div>
          ${pitchMarkersHtml(lineup.players)}
        </div>
      </div>`,
    )
    .join("");

  const appearanceRows = (handout.appearance_list || [])
    .map(
      (row) => {
        const foot = formatFootAbbrev(row.foot);
        const isLeft = foot === "L";
        return `<tr>
        <td>${row.shirt_number ?? row.number ?? "—"}</td>
        <td>${row.name || "—"}</td>
        <td>${row.position_abbr}</td>
        <td>${row.age ?? "—"}</td>
        <td class="ph-foot-cell${isLeft ? " ph-foot-cell--left" : ""}">${foot}</td>
        <td>${row.appearances}</td>
        <td>${row.starts}</td>
        <td>${row.minutes}</td>
        <td>${row.goals}</td>
        <td>${row.assists}</td>
      </tr>`;
      },
    )
    .join("");

  return `<section class="ph-page ph-page--one" data-export-title="Pre-Match Handout — Page 1">
    ${renderTopBar(handout, report)}
    <div class="ph-page__body">
      <div class="ph-page1-top">
        <div class="ph-appearance">
          <h2 class="ph-block-title">Appearance list</h2>
          <div class="ph-appearance__table-wrap">
          <table class="ph-appearance-table">
            <colgroup>
              <col class="ph-col-num" />
              <col class="ph-col-player" />
              <col class="ph-col-pos" />
              <col class="ph-col-age" />
              <col class="ph-col-ft" />
              <col class="ph-col-mp" />
              <col class="ph-col-st" />
              <col class="ph-col-min" />
              <col class="ph-col-g" />
              <col class="ph-col-a" />
            </colgroup>
            <thead>
              <tr>
                <th>#</th><th>Player</th><th>Pos</th><th>Age</th><th>Foot</th>
                <th>MP</th><th>Starts</th><th>Min</th><th>Goals</th><th>Assists</th>
              </tr>
            </thead>
            <tbody>${appearanceRows}</tbody>
          </table>
          </div>
        </div>
        <div class="ph-predicted">
          <h2 class="ph-block-title">Predicted XI</h2>
          ${predictedSource ? `<p class="ph-predicted__source">${predictedSource}</p>` : ""}
          <div class="ph-predicted__pitch-wrap">
            <div class="ph-main-pitch" style="${kitStyle}">
              <div class="ph-main-pitch__markings"></div>
              ${mainPitchMarkersHtml(handout.predicted_xi)}
            </div>
          </div>
        </div>
      </div>
      <div class="ph-page1-bottom">
        <div>
          <h2 class="ph-section-title">Previous lineups</h2>
          <div class="ph-lineups-row">${lineupsHtml || "<p>No recent lineups.</p>"}</div>
        </div>
        <div>
          <h2 class="ph-section-title">Injuries / suspensions</h2>
          <div class="ph-availability">
            <h4>Confirmed out</h4>
            <ul>${renderAvailabilityList(handout.availability?.confirmed_out, "None listed")}</ul>
            <h4>Possibly out</h4>
            <ul>${renderAvailabilityList(handout.availability?.possibly_out, "None listed")}</ul>
            <h4>Suspended</h4>
            <ul>${renderAvailabilityList(handout.availability?.suspended, "None listed")}</ul>
          </div>
        </div>
      </div>
    </div>
  </section>`;
}

function renderPage2(handout, report) {
  const rankingsIn = (handout.rankings || []).slice(0, 2);
  const rankingsOut = (handout.rankings || []).slice(2, 4);

  const rankingColumn = (items) =>
    items
      .map(
        (row) => `<div class="ph-ranking-row">
          <div>
            <span class="ph-ranking-row__label">${row.label}</span>
            ${row.subtitle ? `<span class="ph-ranking-row__sub">${row.subtitle}</span>` : ""}
          </div>
          <span class="ph-ranking-row__value">${row.value ?? "—"}</span>
        </div>`,
      )
      .join("");

  const playerCards = (handout.key_players || [])
    .map((player) => {
      const numName = `${player.shirt_number ? `${player.shirt_number}. ` : ""}${(player.surname || player.name || "").toUpperCase()}`;
      const summary = player.summary || "Add analyst notes for this player in Edit notes.";
      return `<article class="ph-player-card">
        <div class="ph-player-card__head">
          <div class="ph-player-card__num-name">${numName}</div>
          <div class="ph-player-card__archetype">${player.archetype || ""}</div>
        </div>
        <div class="ph-player-card__meta">${player.foot || "—"} FOOT · ${player.height || "—"}</div>
        <p class="ph-player-card__summary">${summary}</p>
      </article>`;
    })
    .join("");

  return `<section class="ph-page ph-page--two" data-export-title="Pre-Match Handout — Page 2">
    ${renderTopBar(handout, report)}
    <div class="ph-page__body ph-page__body--two">
      <div class="ph-page2-grid">
        <div class="ph-style-box">
          <h3>Team style</h3>
          <div class="ph-style-columns">
            <div>
              <h4>In possession</h4>
              <p>${handout.team_style?.in_possession || "—"}</p>
            </div>
            <div>
              <h4>Out of possession</h4>
              <p>${handout.team_style?.out_of_possession || "—"}</p>
            </div>
          </div>
        </div>
        <div class="ph-rankings-box">
          <h3>Team rankings</h3>
          <div class="ph-rankings-grid">
            <div>
              <h4>In possession</h4>
              ${rankingColumn(rankingsIn)}
            </div>
            <div>
              <h4>Out of possession</h4>
              ${rankingColumn(rankingsOut)}
            </div>
          </div>
        </div>
      </div>
      <div class="ph-players-grid">${playerCards}</div>
    </div>
  </section>`;
}

function buildSlides(report) {
  const handout = applyNotesToHandout(report.handout || {});
  return [renderPage1(handout, report), renderPage2(handout, report)];
}

function syncPitchToTable() {
  const tableWrap = document.querySelector(".ph-appearance__table-wrap");
  const pitch = document.querySelector(".ph-main-pitch");
  if (!tableWrap || !pitch) return;
  pitch.style.height = `${tableWrap.offsetHeight}px`;
}

function renderDeck(report) {
  state.report = report;
  loadNotes();
  const handout = report.handout || {};
  populateNotesForm(handout);
  els.deck.innerHTML = buildSlides(report).join("");
  els.refreshBtn.disabled = false;
  els.exportPdfBtn.disabled = false;
  if (els.exportPptxBtn) els.exportPptxBtn.disabled = false;
  requestAnimationFrame(() => {
    syncPitchToTable();
    fitPaperToViewport();
    requestAnimationFrame(() => {
      syncPitchToTable();
      fitPaperToViewport();
    });
  });
}

function renderEmptyDeck(message) {
  state.report = null;
  els.deck.innerHTML = `<div class="ph-page" style="display:grid;place-items:center;padding:3rem;text-align:center;color:#6b7280;">${message}</div>`;
  els.statusBar.textContent = message;
  els.refreshBtn.disabled = true;
  els.exportPdfBtn.disabled = true;
  if (els.exportPptxBtn) els.exportPptxBtn.disabled = true;
  requestAnimationFrame(fitPaperToViewport);
}

async function loadFixtures({ forceDefault = false } = {}) {
  const iterationId = Number(els.iterationId.value);
  const data = await fetchJson(`/api/pre-match-handout/fixtures?iteration_id=${iterationId}`);
  state.fixtures = data.fixtures || [];
  if (!state.fixtures.length) {
    renderEmptyDeck("No opponents found for this season.");
    return false;
  }
  const currentMatchId = Number(els.matchId.value || 0);
  const stillValid =
    !forceDefault &&
    state.fixtures.some((row) => Number(row.match_id) === currentMatchId && currentMatchId > 0);
  if (forceDefault || !stillValid) {
    selectFixture(pickDefaultFixture());
  }
  renderMatchBar();
  return true;
}

async function loadReport() {
  const iterationId = Number(els.iterationId.value);
  const squadId = Number(els.opponentId.value);
  const matchId = Number(els.matchId.value || 0) || null;
  if (!squadId) return;

  state.loading = true;
  els.refreshBtn.disabled = true;
  els.exportPdfBtn.disabled = true;
  if (els.exportPptxBtn) els.exportPptxBtn.disabled = true;
  renderSeasonToggle();
  setStatus("Loading handout data from Impect… first load can take 20–40 seconds.", "loading");

  try {
    const report = await fetchJson("/api/pre-match-handout/report", {
      method: "POST",
      body: JSON.stringify({
        iteration_id: iterationId,
        squad_id: squadId,
        match_id: matchId,
      }),
    });
    renderMatchBar();
    loadNotes();
    renderDeck(report);
    setStatus("");
    els.statusBar.textContent = `Handout ready — ${report.opponent?.name || "opponent"} · export A4 PDF when ready`;
  } catch (error) {
    setStatus(error.message, "error");
    renderEmptyDeck("Could not load handout.");
  } finally {
    state.loading = false;
    renderSeasonToggle();
  }
}

async function waitForPaint() {
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

async function waitForImages(root) {
  const images = root.querySelectorAll("img");
  await Promise.all(
    [...images].map((image) => {
      if (image.complete) return Promise.resolve();
      return new Promise((resolve) => {
        image.onload = () => resolve();
        image.onerror = () => resolve();
      });
    }),
  );
}

async function preparePageForExport(page) {
  const prev = {
    width: page.style.width,
    height: page.style.height,
    minHeight: page.style.minHeight,
    maxWidth: page.style.maxWidth,
  };
  page.classList.add("ph-page--exporting");
  page.style.width = `${SLIDE_EXPORT_WIDTH}px`;
  page.style.maxWidth = `${SLIDE_EXPORT_WIDTH}px`;
  page.style.height = `${SLIDE_EXPORT_HEIGHT}px`;
  page.style.minHeight = `${SLIDE_EXPORT_HEIGHT}px`;
  await waitForImages(page);
  await waitForPaint();
  return () => {
    page.classList.remove("ph-page--exporting");
    page.style.width = prev.width;
    page.style.height = prev.height;
    page.style.minHeight = prev.minHeight;
    page.style.maxWidth = prev.maxWidth;
  };
}

function exportBaseName() {
  const opponent = (state.report?.opponent?.name || "opponent")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const matchId = els.matchId.value || "preview";
  return `port-vale-pre-match-handout-${opponent}-${matchId}`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function captureHandoutPages() {
  const pages = [...document.querySelectorAll(".ph-page")];
  if (!pages.length) {
    throw new Error("Load a handout before exporting.");
  }
  if (typeof html2canvas !== "function") {
    throw new Error("Export unavailable — reload the page.");
  }

  els.deck.classList.add("ph-deck--exporting");
  syncPitchToTable();
  const exportPages = [];
  try {
    for (const page of pages) {
      const restore = await preparePageForExport(page);
      try {
        const canvas = await html2canvas(page, {
          backgroundColor: "#ffffff",
          scale: EXPORT_SCALE,
          useCORS: true,
          allowTaint: false,
          logging: false,
          width: SLIDE_EXPORT_WIDTH,
          height: SLIDE_EXPORT_HEIGHT,
          windowWidth: SLIDE_EXPORT_WIDTH,
          windowHeight: SLIDE_EXPORT_HEIGHT,
          scrollX: 0,
          scrollY: 0,
          onclone: (_doc, clonedPage) => {
            clonedPage.classList.add("ph-page--pdf-capture", "ph-page--exporting");
            clonedPage.style.width = `${SLIDE_EXPORT_WIDTH}px`;
            clonedPage.style.maxWidth = `${SLIDE_EXPORT_WIDTH}px`;
            clonedPage.style.height = `${SLIDE_EXPORT_HEIGHT}px`;
            clonedPage.style.minHeight = `${SLIDE_EXPORT_HEIGHT}px`;
            clonedPage.style.borderRadius = "0";
            clonedPage.style.boxShadow = "none";
            clonedPage.style.overflow = "hidden";
          },
        });

        const trimmed = document.createElement("canvas");
        trimmed.width = Math.round(SLIDE_EXPORT_WIDTH * EXPORT_SCALE);
        trimmed.height = Math.round(SLIDE_EXPORT_HEIGHT * EXPORT_SCALE);
        const ctx = trimmed.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, trimmed.width, trimmed.height);
        ctx.drawImage(canvas, 0, 0, trimmed.width, trimmed.height);

        exportPages.push({
          imageData: trimmed.toDataURL("image/png"),
          width: trimmed.width,
          height: trimmed.height,
        });
      } finally {
        restore();
      }
    }
  } finally {
    els.deck.classList.remove("ph-deck--exporting");
  }
  return exportPages;
}

async function exportHandout(endpoint, extension, busyLabel, successLabel) {
  const exportBtn = extension === "pptx" ? els.exportPptxBtn : els.exportPdfBtn;
  if (exportBtn) exportBtn.disabled = true;
  els.exportPdfBtn.disabled = true;
  if (els.exportPptxBtn) els.exportPptxBtn.disabled = true;
  setStatus(busyLabel, "loading");

  try {
    const pages = await captureHandoutPages();
    const filename = `${exportBaseName()}.${extension}`;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages,
        document_title: state.report?.handout?.header_title || "Pre-Match Handout",
        filename,
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Export failed");
    }
    const blob = await response.blob();
    downloadBlob(blob, filename);
    const saved = response.headers.get("X-Saved-Desktop-Path");
    setStatus(saved ? `${successLabel} exported · also saved to Desktop` : `${successLabel} exported.`, "");
  } catch (error) {
    setStatus(error.message || "Export failed", "error");
  } finally {
    const ready = Boolean(state.report);
    els.exportPdfBtn.disabled = !ready;
    if (els.exportPptxBtn) els.exportPptxBtn.disabled = !ready;
  }
}

function exportPdf() {
  return exportHandout("/api/pre-match-handout/export-pdf", "pdf", "Building A4 PDF…", "A4 PDF");
}

function exportPptx() {
  return exportHandout("/api/pre-match-handout/export-pptx", "pptx", "Building A4 slides…", "A4 slides");
}

async function init() {
  renderEmptyDeck("Loading fixtures…");
  try {
    state.meta = await fetchJson(`/api/pre-match-handout/meta?_=${Date.now()}`);
    els.iterationId.value = String(state.meta.default_iteration_id);
    els.matchId.value = "";
    els.opponentId.value = "";
    renderSeasonToggle();
    const hasFixtures = await loadFixtures({ forceDefault: true });
    if (hasFixtures) {
      await loadReport();
    }
  } catch (error) {
    setStatus(error.message, "error");
    renderEmptyDeck("Could not initialise pre-match handout.");
  }
}

els.refreshBtn.addEventListener("click", loadReport);
els.exportPdfBtn.addEventListener("click", exportPdf);
if (els.exportPptxBtn) els.exportPptxBtn.addEventListener("click", exportPptx);
els.editNotesBtn.addEventListener("click", () => els.notesPanel.classList.remove("hidden"));
els.closeNotesBtn.addEventListener("click", () => els.notesPanel.classList.add("hidden"));
els.saveNotesBtn.addEventListener("click", saveNotes);
window.addEventListener("resize", () => {
  syncPitchToTable();
  fitPaperToViewport();
});

init();
