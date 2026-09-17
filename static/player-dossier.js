(function initPlayerDossier() {
  const statusEl = document.getElementById("pdStatus");
  const errorEl = document.getElementById("pdError");
  const heroEl = document.getElementById("pdHero");
  const gridEl = document.getElementById("pdGrid");
  const shellEl = document.getElementById("pdShell");
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
    if (
      !ability ||
      ability.source === "example" ||
      (ability.current == null && ability.potential == null)
    ) {
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
    selectedProfile: null,
    profilesByPosition: {},
    factorsByPosition: {},
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setProfileSubtitle(label) {
    const card = document.querySelector(".pd-card--radar .pd-card__sub");
    if (!card) return;
    card.textContent = label
      ? `PV profiles · ${label}`
      : "Port Vale profile scores";
  }

  function renderPositions(player) {
    const root = document.getElementById("pdPositions");
    const positions = player.positions || [];
    if (!positions.length) {
      root.innerHTML = "";
      return;
    }
    const selected = chartState.selectedPosition || player.primary_position;
    const maxMins = Math.max(
      ...positions.map((pos) => Number(pos.minutes) || 0),
      1
    );
    root.innerHTML = positions
      .map((pos) => {
        const active = pos.code === selected;
        const minsNum = Number(pos.minutes);
        const mins = Number.isFinite(minsNum) ? `${fmt(minsNum)}′` : "—";
        const width = Math.max(6, Math.round(((Number.isFinite(minsNum) ? minsNum : 0) / maxMins) * 100));
        const label = pos.label || pos.code;
        return `<button type="button" class="pd-pos${active ? " is-primary" : ""}" data-position="${escapeHtml(pos.code)}" data-label="${escapeHtml(label)}" title="${escapeHtml(label)} · ${mins}" aria-pressed="${active ? "true" : "false"}">
          <span class="pd-pos__code">${escapeHtml(pos.abbrev || pos.code)}</span>
          <span class="pd-pos__label">${escapeHtml(label)}</span>
          <span class="pd-pos__mins">${mins}</span>
          <span class="pd-pos__bar"><i style="width:${width}%"></i></span>
        </button>`;
      })
      .join("");
  }

  async function loadProfilesForPosition(positionCode) {
    if (!chartState.playerId || !positionCode) return;
    const legend = document.getElementById("pdProfiles");
    const radarEl = document.getElementById("pdRadar");
    chartState.selectedPosition = positionCode;
    document.querySelectorAll("#pdPositions .pd-pos").forEach((btn) => {
      const active = btn.getAttribute("data-position") === positionCode;
      btn.classList.toggle("is-primary", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const cached = chartState.profilesByPosition[positionCode];
    if (cached) {
      const activeBtn = document.querySelector(`#pdPositions [data-position="${CSS.escape(positionCode)}"]`);
      const label = activeBtn?.getAttribute("data-label") || "";
      setProfileSubtitle(label || positionCode);
      renderProfiles(cached);
      return;
    }
    const bars = document.getElementById("pdProfileBars");
    if (legend) {
      legend.hidden = true;
      legend.innerHTML = "";
    }
    if (bars) bars.innerHTML = `<p class="pd-empty">Loading profiles…</p>`;
    radarEl.innerHTML = "";
    try {
      const url =
        `/api/player/${chartState.playerId}/profiles?position=${encodeURIComponent(positionCode)}` +
        (chartState.iterationId ? `&iteration=${chartState.iterationId}` : "");
      const res = await fetch(url, { cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(60000) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setProfileSubtitle(data.position_label || positionCode);
      chartState.profilesByPosition[positionCode] = data.profiles || [];
      renderProfiles(data.profiles || []);
    } catch (err) {
      if (legend) {
        legend.hidden = false;
        legend.innerHTML = `<p class="pd-empty">Could not load profiles (${err.message || err}).</p>`;
      }
      radarEl.innerHTML = "";
      if (bars) bars.innerHTML = "";
    }
  }

  function wireProfileFilters() {
    document.getElementById("pdProfileBars")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-profile]");
      if (!btn) return;
      const name = btn.getAttribute("data-profile");
      if (!name || name === chartState.selectedProfile) return;
      selectProfile(name);
    });
    document.getElementById("pdRadar")?.addEventListener("click", (event) => {
      const hit = event.target.closest("[data-profile]");
      if (!hit) return;
      const name = hit.getAttribute("data-profile");
      if (!name || name === chartState.selectedProfile) return;
      selectProfile(name);
    });
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
      player.foot && player.foot !== "—" ? player.foot : null,
      player.height && player.height !== "—" ? player.height : null,
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

    const scoreEl = document.getElementById("pdScore");
    const scoreNum = document.getElementById("pdScoreNum");
    if (scoreEl && scoreNum) {
      if (player.overall != null && !Number.isNaN(Number(player.overall))) {
        scoreNum.textContent = Number(player.overall).toFixed(0);
        scoreEl.hidden = false;
      } else {
        scoreEl.hidden = true;
      }
    }

    document.getElementById("pdBioStats").innerHTML = [
      { label: "Age", value: player.age != null ? String(player.age) : "" },
      { label: "Height", value: player.height && player.height !== "—" ? player.height : "" },
      { label: "Foot", value: player.foot && player.foot !== "—" ? player.foot : "" },
    ]
      .filter((stat) => stat.value)
      .map(
        (stat) => `<div class="pd-stat">
          <span class="pd-stat__label">${stat.label}</span>
          <span class="pd-stat__value">${escapeHtml(stat.value)}</span>
        </div>`
      )
      .join("");

    chartState.selectedPosition = player.primary_position || positionsFirstCode(player);
    renderPositions(player);
    if (player.primary_position_label) {
      setProfileSubtitle(player.primary_position_label);
    }
  }

  function positionsFirstCode(player) {
    return (player.positions || [])[0]?.code || null;
  }

  function renderKeyStats(stats) {
    if (!stats?.length) {
      keyStatsCard.hidden = true;
      return;
    }
    const visible = stats.filter((stat) => {
      if (stat.value == null || stat.value === "") return false;
      if (stat.source === "FBRef" && Number(stat.value) === 0) return false;
      return true;
    });
    if (!visible.length) {
      keyStatsCard.hidden = true;
      return;
    }
    document.getElementById("pdKeyStats").innerHTML = visible
      .map(
        (stat) => `<div class="pd-keystat">
          <span class="pd-keystat__label">${stat.label}${stat.source ? ` · ${stat.source}` : ""}</span>
          <span class="pd-keystat__value">${formatStat(stat)}</span>
        </div>`
      )
      .join("");
    keyStatsCard.hidden = false;
  }

  function renderFotmob(fotmob, link) {
    const card = document.getElementById("pdFotmobCard");
    if (!card) return;
    if (!fotmob) {
      card.hidden = true;
      return;
    }
    const linkEl = document.getElementById("pdFotmobLink");
    const href = link || fotmob.profile_url;
    if (href) {
      linkEl.href = href;
      linkEl.hidden = false;
    } else {
      linkEl.hidden = true;
    }
    const sub = document.getElementById("pdFotmobSub");
    if (sub) {
      sub.textContent = [fotmob.squad, fotmob.league, fotmob.season].filter(Boolean).join(" · ");
    }
    const stats = [
      { label: "Games", value: fotmob.games, format: "int" },
      { label: "Minutes", value: fotmob.minutes, format: "int" },
      { label: "Goals", value: fotmob.goals, format: "int" },
      { label: "Assists", value: fotmob.assists, format: "int" },
    ].filter((row) => row.value != null && row.value !== "");
    document.getElementById("pdFotmobStats").innerHTML = stats
      .map(
        (stat) => `<div class="pd-keystat">
          <span class="pd-keystat__label">${stat.label}</span>
          <span class="pd-keystat__value">${formatStat(stat)}</span>
        </div>`
      )
      .join("");
    card.hidden = !stats.length;
  }

  function wrapRadarLabel(label) {
    const text = String(label || "");
    if (text.length <= 16) return [text];
    const parts = text.split(/[\/·]/).map((part) => part.trim()).filter(Boolean);
    if (parts.length > 1) return parts.slice(0, 2);
    const words = text.split(/\s+/);
    if (words.length < 2) return [text];
    const mid = Math.ceil(words.length / 2);
    return [words.slice(0, mid).join(" "), words.slice(mid).join(" ")];
  }

  function renderRadarSvg(el, profiles) {
    const n = profiles.length;
    const width = 440;
    const height = 400;
    const cx = 220;
    const cy = 200;
    const radius = 118;
    const xy = (index, frac) => {
      const angle = -Math.PI / 2 + (index / n) * Math.PI * 2;
      return [cx + radius * frac * Math.cos(angle), cy + radius * frac * Math.sin(angle)];
    };
    const rings = [0.2, 0.4, 0.6, 0.8, 1]
      .map((frac) => {
        const pts = Array.from({ length: n }, (_, i) => xy(i, frac).join(",")).join(" ");
        return `<polygon points="${pts}" fill="none" stroke="rgba(148,163,184,0.18)" stroke-width="1"/>`;
      })
      .join("");
    const axes = Array.from({ length: n }, (_, i) => {
      const [x, y] = xy(i, 1);
      return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="rgba(148,163,184,0.14)"/>`;
    }).join("");
    const poly = profiles
      .map((row, i) => xy(i, Math.max(0, Math.min(100, Number(row.pct) || 0)) / 100).join(","))
      .join(" ");
    const dots = profiles
      .map((row, i) => {
        const [x, y] = xy(i, Math.max(0, Math.min(100, Number(row.pct) || 0)) / 100);
        return `<circle cx="${x}" cy="${y}" r="4.5" fill="#34d399"/>`;
      })
      .join("");
    const labels = profiles
      .map((row, i) => {
        const [x, y] = xy(i, 1.28);
        const lines = wrapRadarLabel(row.label);
        const startDy = -((lines.length - 1) * 6);
        const tspans = lines
          .map(
            (line, li) =>
              `<tspan x="${x.toFixed(1)}" dy="${li === 0 ? startDy : 13}">${escapeHtml(line)}</tspan>`
          )
          .join("");
        return `<g class="pd-radar-hit${row.name === chartState.selectedProfile ? " is-selected" : ""}" data-profile="${escapeHtml(row.name || "")}" data-label="${escapeHtml(row.label || "")}">
          <text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle" class="pd-radar-label">${tspans}</text>
        </g>`;
      })
      .join("");
    el.innerHTML = `<svg class="pd-radar-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="PV profile radar">${rings}${axes}<polygon points="${poly}" fill="rgba(61,139,253,0.22)" stroke="#3d8bfd" stroke-width="2.5" stroke-linejoin="round"/>${dots}${labels}</svg>`;
  }

  function renderProfiles(profiles) {
    const legend = document.getElementById("pdProfiles");
    const radarEl = document.getElementById("pdRadar");
    const barsEl = document.getElementById("pdProfileBars");
    if (!profiles?.length) {
      if (legend) {
        legend.hidden = false;
        legend.innerHTML = `<p class="pd-empty">No PV profiles for this season / position yet.</p>`;
      }
      radarEl.innerHTML = "";
      if (barsEl) barsEl.innerHTML = "";
      const factors = document.getElementById("pdFactorStats");
      if (factors) factors.innerHTML = `<p class="pd-empty">No PV profiles for this season / position yet.</p>`;
      return;
    }

    if (legend) {
      legend.hidden = true;
      legend.innerHTML = "";
    }

    const names = profiles.map((row) => row.name).filter(Boolean);
    if (!names.includes(chartState.selectedProfile)) {
      chartState.selectedProfile = names[0] || null;
    }

    if (barsEl) {
      barsEl.innerHTML = profiles
        .map((row) => {
          const selected = row.name === chartState.selectedProfile;
          return `<button type="button" class="pd-profile${selected ? " is-selected" : ""}" data-profile="${escapeHtml(row.name || "")}" data-label="${escapeHtml(row.label || "")}" aria-pressed="${selected ? "true" : "false"}">
            <span class="pd-profile__label">${escapeHtml(row.label)}</span>
            <span class="pd-profile__pct">${escapeHtml(row.pct)}</span>
            <div class="pd-profile__bar"><div class="pd-profile__fill" style="width:${Math.max(0, Math.min(100, Number(row.pct) || 0))}%"></div></div>
          </button>`;
        })
        .join("");
    }

    renderRadarSvg(radarEl, profiles);
    renderFactorStats();
    loadFactors(chartState.selectedPosition);
  }

  function currentProfiles() {
    const position = chartState.selectedPosition;
    if (position && chartState.profilesByPosition[position]) {
      return chartState.profilesByPosition[position];
    }
    return [];
  }

  function selectedFactorPack() {
    const packs = chartState.factorsByPosition[chartState.selectedPosition] || [];
    const wanted = String(chartState.selectedProfile || "").toLowerCase();
    return (
      packs.find((row) => String(row.name || "").toLowerCase() === wanted) ||
      packs.find((row) => String(row.label || "").toLowerCase() === wanted) ||
      null
    );
  }

  function renderFactorStats() {
    const root = document.getElementById("pdFactorStats");
    const heading = document.getElementById("pdFactorHeading");
    const sub = document.getElementById("pdFactorSub");
    if (!root) return;
    const pack = selectedFactorPack();
    const label =
      pack?.label ||
      currentProfiles().find((row) => row.name === chartState.selectedProfile)?.label ||
      "";
    if (heading) heading.textContent = label ? `${label}` : "Impect stats";
    if (sub) sub.textContent = label ? "Impect factors that feed this profile" : "Select a profile";
    if (!chartState.selectedProfile) {
      root.innerHTML = `<p class="pd-empty">Select a profile.</p>`;
      return;
    }
    if (chartState.factorsByPosition[chartState.selectedPosition] == null) {
      root.innerHTML = `<p class="pd-empty">Fetching Impect stats…</p>`;
      return;
    }
    const factors = pack?.factors || [];
    if (!factors.length) {
      root.innerHTML = `<p class="pd-empty">No Impect factors for this profile yet.</p>`;
      return;
    }
    root.innerHTML = factors
      .map(
        (row) => `<div class="pd-factor">
          <span class="pd-factor__label">${escapeHtml(row.label)}</span>
          <span class="pd-factor__value">${escapeHtml(row.valueLabel ?? row.value ?? "—")}</span>
          <div class="pd-factor__bar"><div class="pd-factor__fill" style="width:${Math.max(0, Math.min(100, Number(row.barPct) || 0))}%"></div></div>
        </div>`
      )
      .join("");
  }

  function selectProfile(profileName, { silent = false } = {}) {
    if (!profileName) return;
    chartState.selectedProfile = profileName;
    document.querySelectorAll("#pdProfileBars .pd-profile").forEach((btn) => {
      const active = btn.getAttribute("data-profile") === profileName;
      btn.classList.toggle("is-selected", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    document.querySelectorAll("#pdRadar .pd-radar-hit").forEach((hit) => {
      hit.classList.toggle("is-selected", hit.getAttribute("data-profile") === profileName);
    });
    if (!silent) renderFactorStats();
  }

  async function loadFactors(positionCode) {
    if (!chartState.playerId || !positionCode) return;
    if (chartState.factorsByPosition[positionCode]) {
      renderFactorStats();
      return;
    }
    renderFactorStats();
    const url =
      `/api/player/${chartState.playerId}/factors?position=${encodeURIComponent(positionCode)}` +
      (chartState.iterationId ? `&iteration=${chartState.iterationId}` : "");
    try {
      const res = await fetch(url, { cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(45000) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      chartState.factorsByPosition[positionCode] = data.profiles || [];
      if (positionCode === chartState.selectedPosition) renderFactorStats();
    } catch (_err) {
      if (chartState.factorsByPosition[positionCode] == null) {
        chartState.factorsByPosition[positionCode] = [];
      }
      if (positionCode === chartState.selectedPosition) renderFactorStats();
    }
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
    if (stage === "scout_identified") return "Scout identified";
    if (stage === "video_scouted") return "Video scouted";
    if (stage === "live_scouted") return "Live scouted";
    if (stage === "gone_elsewhere") return "Gone / turned us down";
    if (stage === "not_the_right_fit") return "Not the right fit";
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
    const card = document.getElementById("pdGamesCard");
    if (!games?.length) {
      if (card) card.hidden = true;
      if (root) root.innerHTML = "";
      return;
    }
    if (card) card.hidden = false;
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
    const card = document.getElementById("pdUpcomingCard");
    const sub = document.getElementById("pdUpcomingSub");
    if (!root) return;
    if (!games?.length) {
      if (card) card.hidden = true;
      root.innerHTML = "";
      return;
    }
    if (card) card.hidden = false;
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

  async function loadGames(playerId, iteration, columns) {
    const url =
      `/api/player/${playerId}/games` + (iteration ? `?iteration=${iteration}` : "");
    try {
      const res = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(180000) });
      if (!res.ok) return;
      const data = await res.json();
      renderGames(data.recent_games, data.impect_columns || columns);
      renderUpcoming(data.upcoming_games);
    } catch (_err) {
      // Fixtures are extra; don't stall the page with a hanging loader.
    }
  }

  async function loadWeb(url) {
    try {
      const res = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(45000) });
      if (!res.ok) return;
      const data = await res.json();
      const player = data.player || {};
      document.querySelectorAll("#pdBioStats .pd-stat").forEach((stat) => {
        const label = stat.querySelector(".pd-stat__label")?.textContent;
        const valueEl = stat.querySelector(".pd-stat__value");
        if (!valueEl) return;
        if (label === "Height" && player.height) valueEl.textContent = player.height;
        if (label === "Foot" && player.foot) valueEl.textContent = player.foot;
      });
      if (data.hero_stats?.length) renderKeyStats(data.hero_stats);
      renderFotmob(data.web?.fotmob, data.links?.fotmob);
      const tags = [];
      if (player.citizenship) tags.push({ text: player.citizenship, gold: false });
      if (player.market_value) tags.push({ text: player.market_value, gold: true });
      if (player.on_loan_from) tags.push({ text: `Loan from ${player.on_loan_from}`, gold: true });
      const tagsEl = document.getElementById("pdTags");
      if (tagsEl && tags.length) {
        tagsEl.innerHTML = tags
          .map((tag) => `<span class="pd-tag${tag.gold ? " pd-tag--gold" : ""}">${tag.text}</span>`)
          .join("");
      }
    } catch (_err) {
      // TM / FBRef is extra; the local page already painted.
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
        const href = season.iteration_id
          ? `/player/${playerId}?iteration=${season.iteration_id}`
          : `/player/${playerId}`;
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
    setError("");
    try {
      const res = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(20000) });
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
      chartState.profilesByPosition = data.profiles_by_position || {};
      if (chartState.selectedPosition && data.profiles?.length) {
        chartState.profilesByPosition[chartState.selectedPosition] = data.profiles;
      }
      renderHero(data.player, data.hero_stats, data.ability);
      renderKeyStats(data.hero_stats?.length ? data.hero_stats : data.key_stats);
      renderFotmob(data.web?.fotmob, data.links?.fotmob);
      renderProfiles(data.profiles);
      renderNotes(data.notes);
      renderReports(data.reports);
      renderSeasons(data.seasons, data.player.id);

      const charts = document.getElementById("pdChartsLink");
      const compare = document.getElementById("pdCompareLink");
      if (data.links?.charts) {
        charts.href = data.links.charts;
        charts.hidden = false;
      } else {
        charts.hidden = true;
      }
      if (data.links?.compare) compare.href = data.links.compare;
      wirePipelineButton(data.player);
      actionsEl.hidden = false;
      if (shellEl) shellEl.hidden = false;
      gridEl.hidden = false;
      setStatus("");

      if (data.games_deferred || !data.recent_games?.length || !data.upcoming_games?.length) {
        loadGames(playerId, iteration || data.player?.iteration_id, data.impect_columns);
      } else {
        renderGames(data.recent_games, data.impect_columns);
        renderUpcoming(data.upcoming_games);
      }
      if (data.links?.web && !data.web?.fotmob) {
        loadWeb(data.links.web);
      }
    } catch (err) {
      setStatus("");
      setError(err.message || String(err));
    }
  }

  wireNotesUi();
  wirePositionButtons();
  wireProfileFilters();
  load();
})();
