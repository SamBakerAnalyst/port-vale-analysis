(() => {
  "use strict";

  const TEMPLATE_KEY = "template";
  const CLUB_COLORS = { lincoln: "#e5484d", stockport: "#3b82f6", bradford: "#f59e0b", vale: "#f5c518" };
  const TRANSFER_TEAM_IDS = { stockport: "stockport-county", bradford: "bradford-city", lincoln: "lincoln-city" };

  const CLUB_SECTIONS = [
    ["overview", "Overview"],
    ["why", "Why they won"],
    ["style", "Style of play"],
    ["goals", "Goals"],
    ["patterns", "Patterns"],
    ["squad", "Squad archetype"],
    ["recruitment", "Recruitment"],
    ["vale", "vs Port Vale"],
    ["notes", "Staff notes"],
  ];
  const TEMPLATE_SECTIONS = [
    ["overview", "The template"],
    ["traits", "Shared traits"],
    ["goals", "Goals"],
    ["squad", "Squad & recruitment"],
    ["patterns", "Patterns"],
    ["lessons", "Lessons"],
    ["notes", "Staff notes"],
  ];

  const state = {
    data: null,
    notes: [],
    transfers: null,
    club: "lincoln",
    season: {},
    valeSeason: null,
    playerSort: "minutes",
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d));
  const ordinal = (n) => {
    if (n === null || n === undefined) return "—";
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  };
  const status = (msg) => { $("#statusBar").textContent = msg; };

  // ---------------------------------------------------------------- data helpers

  const clubOf = (key) => (key === "vale" ? state.data.vale : state.data.clubs[key]);
  const seasonsOf = (key) => (clubOf(key)?.seasons || []).slice().sort((a, b) => a.season.localeCompare(b.season));
  const seasonOf = (key, season) => seasonsOf(key).find((s) => s.season === season) || null;
  const prevSeasonCode = (code) => {
    const a = Number(code.slice(0, 2));
    return `${String(a - 1).padStart(2, "0")}/${String(a).padStart(2, "0")}`;
  };

  function fmtMetric(spec, value) {
    if (value === null || value === undefined) return "—";
    const text = Number(value).toFixed(spec.digits);
    if (spec.unit === "%") return `${text}%`;
    if (spec.unit === "m") return `${text} m`;
    if (spec.unit === "min") return `${text} min`;
    return text;
  }

  // Percentile where higher always means "better for the team" (style metrics: as-is).
  function goodPct(spec, pct) {
    if (pct === null || pct === undefined) return null;
    return spec.better === "low" ? 100 - pct : pct;
  }

  function defaultSeason(key) {
    const club = clubOf(key);
    const list = seasonsOf(key);
    if (club?.spotlight_season && list.some((s) => s.season === club.spotlight_season)) return club.spotlight_season;
    return list.length ? list[list.length - 1].season : null;
  }

  function defaultValeSeason() {
    const list = seasonsOf("vale");
    const current = list.find((s) => s.current);
    if (current && current.table.played >= 20) return current.season;
    const done = list.filter((s) => !s.current);
    return (done[done.length - 1] || list[list.length - 1] || {}).season || null;
  }

  function outcomeOf(cs) {
    return cs.table.final_outcome || cs.table.outcome;
  }

  function badge(url, cls = "st-badge") {
    return url ? `<img class="${cls}" src="${esc(url)}" alt="" loading="lazy" onerror="this.style.display='none'">` : "";
  }

  function clubLabel(key) {
    return key === "vale" ? "Port Vale" : (state.data.clubs[key]?.short || key);
  }

  // ---------------------------------------------------------------- boot

  async function boot() {
    try {
      const [dataRes, notesRes] = await Promise.all([
        fetch("/api/shadow-teams/data", { credentials: "same-origin" }),
        fetch("/api/shadow-teams/notes", { credentials: "same-origin" }),
      ]);
      if (!dataRes.ok) throw new Error((await dataRes.json().catch(() => ({}))).detail || `HTTP ${dataRes.status}`);
      state.data = await dataRes.json();
      state.notes = notesRes.ok ? (await notesRes.json()).notes || [] : [];
    } catch (err) {
      $("#view").innerHTML = `<div class="card st-empty">Could not load Shadow Teams: ${esc(err.message)}</div>`;
      status("Load failed.");
      return;
    }
    fetch("/api/efl-transfer-report", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { state.transfers = d; if (state.club !== TEMPLATE_KEY) renderRecruitmentWindow(); })
      .catch(() => {});

    const hash = (location.hash || "").replace("#", "");
    const fromUrl = new URLSearchParams(location.search).get("club");
    if (fromUrl && (state.data.clubs[fromUrl] || fromUrl === TEMPLATE_KEY)) state.club = fromUrl;
    for (const key of state.data.club_order) state.season[key] = defaultSeason(key);
    state.valeSeason = defaultValeSeason();
    renderControls();
    render();
    if (hash) document.getElementById(hash)?.scrollIntoView();
    const gen = state.data.generated_at ? new Date(state.data.generated_at) : null;
    status(`Impect data built ${gen ? gen.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—"} · ${state.data.source}`);
  }

  function renderControls() {
    const toggle = $("#clubToggle");
    const items = [...state.data.club_order.map((k) => [k, state.data.clubs[k].short]), [TEMPLATE_KEY, "Shadow template"]];
    toggle.innerHTML = items.map(([k, label]) =>
      `<button type="button" class="at-toggle__btn${k === state.club ? " at-toggle__btn--active" : ""}" data-club="${k}">${esc(label)}</button>`).join("");
    toggle.onclick = (e) => {
      const btn = e.target.closest("[data-club]");
      if (!btn) return;
      state.club = btn.dataset.club;
      const url = new URL(location.href);
      url.searchParams.set("club", state.club);
      history.replaceState(null, "", url);
      renderControls();
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const seasonSel = $("#seasonSelect");
    $("#seasonGroup").hidden = state.club === TEMPLATE_KEY;
    if (state.club !== TEMPLATE_KEY) {
      seasonSel.innerHTML = seasonsOf(state.club).slice().reverse().map((s) =>
        `<option value="${s.season}"${s.season === state.season[state.club] ? " selected" : ""}>${esc(s.label)} — ${s.partial ? "partial data" : esc(ordinal(s.table.position))}${s.current ? " (live)" : ""}</option>`).join("");
      seasonSel.onchange = () => { state.season[state.club] = seasonSel.value; render(); };
    }
    const valeSel = $("#valeSelect");
    valeSel.innerHTML = seasonsOf("vale").slice().reverse().map((s) =>
      `<option value="${s.season}"${s.season === state.valeSeason ? " selected" : ""}>${esc(s.label)} — ${esc(ordinal(s.table.position))}${s.current ? ` (live, ${s.table.played} games)` : ""}</option>`).join("");
    valeSel.onchange = () => { state.valeSeason = valeSel.value; render(); };
  }

  function renderNav(sections) {
    const nav = $("#sectionNav");
    nav.innerHTML = sections.map(([id, label], i) => `<a href="#${id}"${i === 0 ? ' class="is-active"' : ""}>${esc(label)}</a>`).join("");
  }

  function render() {
    if (state.club === TEMPLATE_KEY) {
      renderNav(TEMPLATE_SECTIONS);
      renderTemplate();
    } else {
      renderNav(CLUB_SECTIONS);
      renderClub();
    }
    wireNavSpy();
  }

  function wireNavSpy() {
    const links = [...document.querySelectorAll("#sectionNav a")];
    const sections = links.map((a) => document.getElementById(a.getAttribute("href").slice(1))).filter(Boolean);
    if (state.observer) state.observer.disconnect();
    state.observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        links.forEach((a) => a.classList.toggle("is-active", a.getAttribute("href") === `#${entry.target.id}`));
      }
    }, { rootMargin: "-30% 0px -60% 0px" });
    sections.forEach((s) => state.observer.observe(s));
  }

  function sectionHead(kicker, title, lede) {
    return `<header class="at-section__head"><p class="at-kicker">${esc(kicker)}</p><h2>${esc(title)}</h2>${lede ? `<p class="at-section__lede">${lede}</p>` : ""}</header>`;
  }

  // ---------------------------------------------------------------- club view

  function renderClub() {
    const key = state.club;
    const club = clubOf(key);
    const cs = seasonOf(key, state.season[key]);
    const vale = seasonOf("vale", state.valeSeason);
    if (!cs) {
      $("#view").innerHTML = `<div class="card st-empty">No Impect seasons for ${esc(club.name)}.</div>`;
      return;
    }
    $("#view").innerHTML = [
      `<section id="overview" class="at-section">${overviewHtml(key, club, cs)}</section>`,
      `<section id="why" class="at-section">${whyHtml(key, club, cs)}</section>`,
      `<section id="style" class="at-section">${styleHtml(key, cs, vale)}</section>`,
      `<section id="goals" class="at-section">${goalsHtml(key, cs, vale)}</section>`,
      `<section id="patterns" class="at-section">${patternsHtml(key, cs, vale)}</section>`,
      `<section id="squad" class="at-section">${squadHtml(key, cs, vale)}</section>`,
      `<section id="recruitment" class="at-section">${recruitmentHtml(key, club, cs)}</section>`,
      `<section id="vale" class="at-section">${vsValeHtml(key, cs, vale)}</section>`,
      `<section id="notes" class="at-section">${notesHtml(key)}</section>`,
    ].join("");
    wirePlayerSort(key, cs);
    wireNotes(key);
    renderRecruitmentWindow();
  }

  function overviewHtml(key, club, cs) {
    const seasons = seasonsOf(key);
    const color = CLUB_COLORS[key];
    const tiles = seasons.map((s) => {
      const managers = s.managers.map((m) => m.name.split(" ").slice(-1)[0]).join(" → ");
      const active = s.season === cs.season;
      const success = (club.success_seasons || []).includes(s.season);
      return `<button type="button" class="st-journey__tile${active ? " is-active" : ""}${success ? " is-success" : ""}" data-season="${s.season}">
        <span class="st-journey__season">${esc(s.season_long)}</span>
        <span class="st-journey__comp">${esc(s.competition)}</span>
        <span class="st-journey__pos">${s.partial ? "—" : esc(ordinal(s.table.position))}</span>
        <span class="st-journey__pts">${s.partial ? `Impect has ${s.table.played} of ${(s.teams - 1) * 2} games` : `${s.table.points} pts · ${num(s.table.ppg, 2)} ppg`}</span>
        <span class="st-journey__out">${esc(outcomeOf(s))}</span>
        <span class="st-journey__mgr">${esc(managers || "—")}</span>
      </button>`;
    }).join("");
    const timeline = (club.timeline || []).map((t) =>
      `<li><span class="st-tl__when">${esc(t.season)}</span><span class="st-tl__lvl">${esc(t.level)}</span><span class="st-tl__text">${esc(t.text)}</span></li>`).join("");
    const t = cs.table;
    const kpis = [
      ["Finish", cs.partial ? "—" : ordinal(t.position), cs.partial ? `${outcomeOf(cs)} · Impect has ${t.played} games` : outcomeOf(cs)],
      ["Points", t.points, `${t.won}W ${t.drawn}D ${t.lost}L · ${num(t.ppg, 2)} ppg`],
      ["Goals", `${t.gf}–${t.ga}`, `GD ${t.gd > 0 ? "+" : ""}${t.gd}`],
      ["xG for / against", `${num(t.xg_for, 2)} / ${num(t.xg_against, 2)}`, "per game"],
      ["Expected points", num(t.xppg, 2), `per game (actual ${num(t.ppg, 2)})`],
      ["Main shape", cs.squad.main_formation || "—", `${cs.squad.formations[0]?.games || 0} of ${t.played} games`],
    ];
    setTimeout(() => {
      document.querySelectorAll(".st-journey__tile").forEach((btn) => btn.addEventListener("click", () => {
        state.season[key] = btn.dataset.season;
        renderControls();
        render();
      }));
    });
    return `
      <div class="card st-hero" style="--club:${color}">
        <div class="st-hero__id">
          ${badge(club.badge, "st-hero__badge")}
          <div>
            <p class="at-kicker">Shadow team</p>
            <h2 class="st-hero__name">${esc(club.name)}</h2>
            <p class="st-hero__headline">${esc(club.headline || "")}</p>
          </div>
        </div>
        <p class="st-hero__lede">${esc(club.one_liner || "")}</p>
        <p class="st-hero__now"><strong>Now:</strong> ${esc(club.status_now || "")}</p>
      </div>
      ${sectionHead("The journey", "Every season in Impect", "Click a season to load it. Gold-edged seasons are the ones we treat as their success template.")}
      <div class="st-journey">${tiles}</div>
      <div class="at-grid st-grid--overview">
        <article class="card">
          <p class="at-panel__kicker">${esc(cs.label)}</p>
          <h3 class="at-panel__title">Season at a glance</h3>
          <div class="st-kpis">${kpis.map(([l, v, s]) => `<div class="st-kpi"><span class="st-kpi__label">${esc(l)}</span><span class="st-kpi__value">${esc(v)}</span><span class="st-kpi__sub">${esc(s)}</span></div>`).join("")}</div>
          ${pointsChartHtml(key, cs)}
        </article>
        <article class="card">
          <p class="at-panel__kicker">Before and beyond the data</p>
          <h3 class="at-panel__title">Milestones</h3>
          <ol class="st-tl">${timeline}</ol>
        </article>
      </div>`;
  }

  function pointsChartHtml(key, cs) {
    const pts = cs.patterns.cumulative || [];
    if (!pts.length) return "";
    const league = state.data.leagues[String(cs.iteration_id)];
    const games = cs.teams ? (cs.teams - 1) * 2 : 46;
    const w = 560, h = 200, pad = 28;
    const maxPts = Math.max(...pts, league?.table?.[0]?.points || 0, 100);
    const x = (i) => pad + (i / games) * (w - pad * 2);
    const y = (p) => h - pad - (p / maxPts) * (h - pad * 2);
    const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i + 1).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
    const lines = [];
    const autoLine = league && !league.current ? league.promotion_line : null;
    const poLine = league && !league.current ? league.playoff_line : null;
    if (autoLine) lines.push([autoLine, "Automatic pace", "var(--good)"]);
    if (poLine) lines.push([poLine, "Play-off pace", "var(--info)"]);
    const paceLines = lines.map(([p, label, color]) =>
      `<line x1="${x(0)}" y1="${y(0)}" x2="${x(games)}" y2="${y(p)}" stroke="${color}" stroke-dasharray="4 4" stroke-width="1.2" opacity="0.7"/>
       <text x="${x(games) - 4}" y="${y(p) - 5}" text-anchor="end" class="st-chart__lbl" fill="${color}">${label} (${p})</text>`).join("");
    return `<div class="st-chart">
      <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Cumulative points">
        <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="rgba(148,163,184,.25)"/>
        ${paceLines}
        <path d="${path}" fill="none" stroke="${CLUB_COLORS[key]}" stroke-width="2.5" stroke-linejoin="round"/>
        <circle cx="${x(pts.length)}" cy="${y(pts[pts.length - 1])}" r="4" fill="${CLUB_COLORS[key]}"/>
        <text x="${pad}" y="${h - 8}" class="st-chart__lbl">Game 1</text>
        <text x="${w - pad}" y="${h - 8}" text-anchor="end" class="st-chart__lbl">Game ${games}</text>
      </svg>
      <p class="st-note">Points race across the season. Dashed lines run at the pace of the final automatic and play-off spots.</p>
    </div>`;
  }

  function whyHtml(key, club, cs) {
    const pillars = (club.pillars || []).map((p) => `
      <article class="card st-pillar">
        <p class="at-panel__kicker">${esc(clubLabel(key))}</p>
        <h3 class="at-panel__title">${esc(p.title)}</h3>
        <ul class="st-list">${p.points.map((pt) => `<li>${esc(pt)}</li>`).join("")}</ul>
      </article>`).join("");
    const insights = (cs.insights || []).slice(0, 10).map((i) =>
      `<div class="st-insight st-insight--${esc(i.tone)}"><strong>${esc(i.title)}</strong><span>${esc(i.text)}</span></div>`).join("");
    const tags = (cs.tags || []).map((t) => `<span class="st-tag" title="${esc(t.why)}">${esc(t.label)}</span>`).join("");
    const lessons = (club.lessons || []).map((l) => `<li>${esc(l)}</li>`).join("");
    const sources = (club.sources || []).map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a></li>`).join("");
    return `${sectionHead("What made them successful", "Why they won", "The club-side story (ownership, structure, coach, recruitment) next to what the Impect data says about the selected season.")}
      <div class="at-grid st-grid--why">
        <article class="card">
          <p class="at-panel__kicker">Impect · ${esc(cs.label)}</p>
          <h3 class="at-panel__title">What the data says</h3>
          ${tags ? `<div class="st-tags">${tags}</div>` : ""}
          <div class="st-insights">${insights || '<p class="st-note">No standout metrics this season.</p>'}</div>
        </article>
        <article class="card st-lessons">
          <p class="at-panel__kicker">For Port Vale</p>
          <h3 class="at-panel__title">Lessons to copy</h3>
          <ol class="st-list st-list--num">${lessons}</ol>
        </article>
      </div>
      <div class="at-grid st-grid--pillars">${pillars}</div>
      <details class="card st-sources"><summary>Sources (${(club.sources || []).length})</summary><ul>${sources}</ul></details>`;
  }

  function styleHtml(key, cs, vale) {
    const groups = state.data.metric_groups.map((g) => {
      const rows = state.data.metrics.filter((m) => m.group === g.id).map((m) => {
        const cell = cs.style[m.key];
        if (!cell) return "";
        const vc = vale?.style?.[m.key];
        const shown = m.better ? goodPct(m, cell.pct_high) : cell.pct_high;
        const valeShown = vc ? (m.better ? goodPct(m, vc.pct_high) : vc.pct_high) : null;
        const rank = m.better === "low" ? cs.teams - cell.rank_high + 1 : cell.rank_high;
        const tone = m.better ? (shown >= 67 ? "good" : shown <= 33 ? "bad" : "mid") : "style";
        const lowHint = m.better === "low" && !/lower/i.test(m.label) ? " (lower is better)" : "";
        return `<div class="st-bar" title="${esc(m.label)}: ${esc(fmtMetric(m, cell.value))}, ${ordinal(rank)} ${m.better ? "best" : "highest"} of ${cs.teams}${vc ? ` · Port Vale ${esc(vale.season_long)}: ${esc(fmtMetric(m, vc.value))}` : ""}">
          <span class="st-bar__label">${esc(m.label)}${lowHint ? `<em class="st-dim">${lowHint}</em>` : ""}</span>
          <span class="st-bar__track">
            <span class="st-bar__fill st-bar__fill--${tone}" style="width:${Math.max(3, shown)}%"></span>
            ${vc ? `<span class="st-bar__vale" style="left:${valeShown}%" aria-label="Port Vale"></span>` : ""}
          </span>
          <span class="st-bar__value">${esc(fmtMetric(m, cell.value))}</span>
          <span class="st-bar__rank">${ordinal(rank)}</span>
        </div>`;
      }).join("");
      return `<article class="card"><p class="at-panel__kicker">${esc(g.label)}</p>${rows}</article>`;
    }).join("");
    const formations = cs.squad.formations.map((f) => {
      const pct = cs.table.played ? Math.round((100 * f.games) / cs.table.played) : 0;
      return `<div class="st-mini"><span>${esc(f.formation)}</span><span class="st-mini__track"><span style="width:${pct}%"></span></span><span>${f.games}</span></div>`;
    }).join("");
    return `${sectionHead("How they play", "Style of play", `League percentiles for ${esc(cs.label)}. Where more or less is clearly better, the bar is green or red, a full bar means best in the division and the rank counts from the best. Blue bars are style choices with no right answer, where a full bar means highest. <span class="st-vale-key"></span> marks Port Vale ${esc(vale ? vale.label : "")}, ranked against Port Vale's own league.`)}
      <div class="at-grid st-grid--style">${groups}</div>
      <div class="at-grid st-grid--3">
        <article class="card"><p class="at-panel__kicker">Starting shapes</p><h3 class="at-panel__title">Formations</h3>${formations || '<p class="st-note">No line-ups.</p>'}</article>
      </div>`;
  }

  // ---------------------------------------------------------------- goals

  const PHASES = [
    ["possession", "Build-up possession", "#60a5fa", "Controlled attacks after settled possession at the back."],
    ["transition", "Attacking transition", "#34d399", "Direct attacks straight after winning the ball."],
    ["set_piece", "Set piece", "#f5c518", "Corners, free kicks, throw-ins and penalties, including the follow-up."],
    ["second_ball", "Second ball", "#c084fc", "Loose balls after duels, blocks and clearances."],
  ];
  const ACTIONS = [
    ["close_range", "Close range (inside 10 m)"], ["mid_range", "Mid range (10–22 m)"], ["long_range", "Long range (22 m+)"],
    ["header", "Header"], ["one_v_one", "1v1 with the keeper"], ["open_goal", "Open goal"],
    ["penalty", "Penalty"], ["free_kick", "Direct free kick"], ["corner", "Direct from a corner"],
  ];
  const GROUPS = [["ATT", "Forwards & wingers", "#f87171"], ["MID", "Midfielders", "#34d399"], ["DEF", "Defenders & wing-backs", "#60a5fa"], ["GK", "Goalkeepers", "#f5c518"]];
  const PHASE_SHORT = { possession: "Build-up", transition: "Transition", set_piece: "Set piece", second_ball: "Second ball" };
  const ACTION_SHORT = { close_range: "Close", mid_range: "Mid", long_range: "Long", header: "Header", one_v_one: "1v1", open_goal: "Open goal", penalty: "Pen", free_kick: "FK", corner: "Corner" };

  function stackedBar(parts, total, label) {
    const sum = total || parts.reduce((s, p) => s + p.value, 0) || 1;
    return `<div class="st-gstack">${label ? `<span class="st-gstack__label">${label}</span>` : ""}<span class="st-gstack__bar">${parts.filter((p) => p.value > 0).map((p) =>
      `<span style="width:${(100 * p.value) / sum}%;background:${p.color}" title="${esc(p.name)}: ${p.value} (${num((100 * p.value) / sum, 0)}%)">${(100 * p.value) / sum >= 9 ? num((100 * p.value) / sum, 0) + "%" : ""}</span>`).join("")}</span></div>`;
  }

  function goalsHtml(key, cs, vale) {
    const g = cs.goals;
    if (!g || !g.total) return `${sectionHead("How they score and concede", "Goals", "")}<div class="card st-empty">No goal data for this season.</div>`;
    const vg = vale?.goals || null;
    const ag = g.against || {};
    const vag = vg?.against || {};
    const teams = cs.teams;
    const tableGoals = cs.table.gf;
    const setShare = g.phases.set_piece?.share;
    const box = g.zones.box || 0;
    const tiles = [
      ["Goals scored", g.total, `${num(g.total / cs.table.played, 2)} a game · xG ${num(g.xg, 1)}${tableGoals !== g.total ? ` · table ${tableGoals} incl. opponent own goals` : ""}`],
      ["Goals vs xG", `${g.total - g.xg >= 0 ? "+" : ""}${num(g.total - g.xg, 1)}`, g.total >= g.xg ? "finished above expectation" : "finished below expectation"],
      ["Inside the box", `${num((100 * box) / g.total, 0)}%`, `${box} of ${g.total} goals`],
      ["From set pieces", `${num(setShare, 0)}%`, `${g.phases.set_piece?.goals ?? 0} goals · ${ordinal(g.phases.set_piece?.rank)} most in the league`],
      ["Headers", g.actions.header?.goals ?? 0, `${ordinal(g.actions.header?.rank)} most in the league`],
      ["Goals conceded", ag.total ?? "—", ag.matches ? `${num(ag.total / ag.matches, 2)} a game · ${ag.phases?.set_piece ?? 0} from set pieces` : ""],
    ];
    const valeCol = (v) => (vg ? `<td class="st-vale-col">${v}</td>` : "");
    const phaseRows = PHASES.map(([k, label, color, why]) => {
      const c = g.phases[k] || {};
      const vc = vg?.phases?.[k] || {};
      const max = Math.max(1, ...PHASES.map(([pk]) => g.phases[pk]?.goals || 0));
      return `<tr title="${esc(why)}">
        <td><i class="st-src" style="background:${color}"></i>${esc(label)}</td>
        <td class="st-strong">${c.goals ?? 0}</td>
        <td><span class="st-share st-share--wide"><span style="width:${(100 * (c.goals || 0)) / max}%;background:${color}"></span></span>${num(c.share, 0)}%</td>
        <td class="st-dim">${num(c.league_share, 0)}%</td>
        <td>${ordinal(c.rank)}</td>
        <td>${num(c.xg, 1)}</td>
        <td class="st-bad-text">${ag.phases?.[k] ?? "—"}</td>
        ${valeCol(vg ? `${vc.goals ?? 0} <span class="st-dim">(${num(vc.share, 0)}%)</span> · <span class="st-bad-text">${vag.phases?.[k] ?? "—"}</span>` : "")}
      </tr>`;
    }).join("");
    const actionMax = Math.max(1, ...ACTIONS.map(([k]) => g.actions[k]?.goals || 0));
    const actionRows = ACTIONS.map(([k, label]) => {
      const c = g.actions[k] || {};
      const vc = vg?.actions?.[k] || {};
      return `<tr>
        <td>${esc(label)}</td>
        <td class="st-strong">${c.goals ?? 0}</td>
        <td><span class="st-share st-share--wide"><span style="width:${(100 * (c.goals || 0)) / actionMax}%"></span></span>${num(c.share, 0)}%</td>
        <td class="st-dim">${num(c.league_share, 0)}%</td>
        <td>${ordinal(c.rank)}</td>
        <td>${num(c.xg, 1)}</td>
        <td class="st-bad-text">${ag.actions?.[k] ?? "—"}</td>
        ${valeCol(vg ? `${vc.goals ?? 0} · <span class="st-bad-text">${vag.actions?.[k] ?? "—"}</span>` : "")}
      </tr>`;
    }).join("");
    const head = (first) => `<thead><tr><th>${first}</th><th>Scored</th><th>Share</th><th title="Average share across the league">League share</th><th title="Rank for goals scored this way, of ${teams}">Rank</th><th>xG</th><th>Conceded</th>${vg ? `<th class="st-vale-col">Port Vale scored · conceded</th>` : ""}</tr></thead>`;

    const phaseBars = [
      stackedBar(PHASES.map(([k, n, c]) => ({ name: n, value: g.phases[k]?.goals || 0, color: c })), 0, `${esc(clubLabel(key))} scored`),
      ag.total ? stackedBar(PHASES.map(([k, n, c]) => ({ name: n, value: ag.phases?.[k] || 0, color: c })), 0, `${esc(clubLabel(key))} conceded`) : "",
      vg ? stackedBar(PHASES.map(([k, n, c]) => ({ name: n, value: vg.phases?.[k]?.goals || 0, color: c })), 0, `Port Vale scored`) : "",
      vag.total ? stackedBar(PHASES.map(([k, n, c]) => ({ name: n, value: vag.phases?.[k] || 0, color: c })), 0, `Port Vale conceded`) : "",
    ].join("");

    const groupsPresent = GROUPS.filter(([k]) => g.groups[k]);
    const groupBars = [
      stackedBar(groupsPresent.map(([k, n, c]) => ({ name: n, value: g.groups[k]?.goals || 0, color: c })), 0, `${esc(clubLabel(key))} goals`),
      stackedBar(groupsPresent.map(([k, n, c]) => ({ name: n, value: g.groups[k]?.assists || 0, color: c })), 0, `${esc(clubLabel(key))} assists`),
      vg ? stackedBar(GROUPS.filter(([k]) => vg.groups?.[k]).map(([k, n, c]) => ({ name: n, value: vg.groups[k]?.goals || 0, color: c })), 0, "Port Vale goals") : "",
    ].join("");
    const matrixMax = Math.max(1, ...groupsPresent.flatMap(([k]) => PHASES.map(([p]) => g.groups[k]?.phases?.[p] || 0)));
    const matrix = `<table class="st-table st-matrix"><thead><tr><th></th>${PHASES.map(([k]) => `<th>${PHASE_SHORT[k]}</th>`).join("")}<th>Goals</th><th>Assists</th></tr></thead><tbody>
      ${groupsPresent.map(([k, n, c]) => `<tr><td><i class="st-src" style="background:${c}"></i>${esc(n)}</td>${PHASES.map(([p]) => {
        const v = g.groups[k]?.phases?.[p] || 0;
        return `<td class="st-heat" style="--a:${(v / matrixMax).toFixed(2)}">${v || ""}</td>`;
      }).join("")}<td class="st-strong">${g.groups[k].goals}</td><td>${g.groups[k].assists}</td></tr>`).join("")}
    </tbody></table>`;
    const positions = (g.positions || []).filter((p) => p.goals || p.assists).map((p) => {
      const topActions = Object.entries(p.actions || {}).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([a, v]) => `${ACTION_SHORT[a] || a} ${v}`).join(" · ");
      return `<tr><td><span class="st-pos st-pos--${esc(p.group)}">${esc(p.pos)}</span></td><td class="st-strong">${p.goals}</td><td>${p.assists}</td><td class="st-dim">${esc(topActions)}</td></tr>`;
    }).join("");

    const lanes = [["left_wing", "Left wing"], ["left_half", "Left half-space"], ["center", "Centre"], ["right_half", "Right half-space"], ["right_wing", "Right wing"]];
    const laneMax = Math.max(1, ...lanes.map(([k]) => g.lanes[k] || 0));
    const laneHtml = `<div class="st-lanes">${lanes.map(([k, l]) => `<div class="st-lane" style="--a:${((g.lanes[k] || 0) / laneMax).toFixed(2)}" title="${esc(l)}"><b>${g.lanes[k] || 0}</b><span>${esc(l)}</span></div>`).join("")}</div>
      <div class="st-zones"><span>In the box <b>${g.zones.box || 0}</b></span><span>Rest of final third <b>${g.zones.final_third || 0}</b></span><span>Further out <b>${g.zones.outside || 0}</b></span></div>`;

    const scorers = (g.scorers || []).filter((s) => s.goals).slice(0, 12).map((s) => `<tr>
      <td><span class="st-pos st-pos--${esc(s.group || "")}">${esc(s.pos || "")}</span></td>
      <td class="st-strong">${esc(s.name)}</td><td class="st-strong">${s.goals}</td><td>${s.assists || ""}</td><td>${num(s.xg, 1)}</td>
      <td>${PHASES.filter(([k]) => s.phases?.[k]).map(([k, , c]) => `<span class="st-gchip" style="--c:${c}">${PHASE_SHORT[k]} ${s.phases[k]}</span>`).join("")}</td>
      <td class="st-dim">${Object.entries(s.actions || {}).sort((a, b) => b[1] - a[1]).map(([a, v]) => `${ACTION_SHORT[a] || a} ${v}`).join(" · ")}</td>
    </tr>`).join("");

    return `${sectionHead("How they score and concede", "Goals", `Every Impect-tagged goal in ${esc(cs.label)}, split by phase of play, type of finish, scorer's position and where on the pitch it was scored. Rank is among all ${teams} clubs for goals scored that way. Conceded is added up from each of their league matches.${vg ? ` Port Vale = ${esc(vale.label)}.` : ""}`)}
      <div class="st-kpis st-kpis--6">${tiles.map(([l, v, s]) => `<div class="st-kpi"><span class="st-kpi__label">${esc(l)}</span><span class="st-kpi__value">${esc(v)}</span><span class="st-kpi__sub">${esc(s)}</span></div>`).join("")}</div>
      <div class="at-grid">
        <article class="card"><p class="at-panel__kicker">By phase of play</p><h3 class="at-panel__title">How the goals came</h3>
          ${phaseBars}
          <div class="st-table-wrap st-mt"><table class="st-table">${head("Phase")}<tbody>${phaseRows}</tbody></table></div>
        </article>
        <article class="card"><p class="at-panel__kicker">By type of finish</p><h3 class="at-panel__title">How they finished</h3>
          <div class="st-table-wrap"><table class="st-table">${head("Finish")}<tbody>${actionRows}</tbody></table></div>
        </article>
      </div>
      <div class="at-grid st-grid--goals">
        <article class="card"><p class="at-panel__kicker">By scorer's position</p><h3 class="at-panel__title">Who scored</h3>
          ${groupBars}
          <p class="at-panel__kicker st-mt">Position group × phase</p>${matrix}
          <p class="at-panel__kicker st-mt">By position played when scoring</p>
          <table class="st-table"><thead><tr><th>Pos</th><th>Goals</th><th>Assists</th><th>Main finishes</th></tr></thead><tbody>${positions}</tbody></table>
        </article>
        <article class="card"><p class="at-panel__kicker">Where on the pitch</p><h3 class="at-panel__title">Scoring lanes</h3>
          ${laneHtml}
        </article>
      </div>
      <article class="card st-mt"><p class="at-panel__kicker">Scorers · how each player's goals came</p>
        <div class="st-table-wrap"><table class="st-table"><thead><tr><th>Pos</th><th>Player</th><th>G</th><th>A</th><th>xG</th><th>Phase</th><th>Finish</th></tr></thead><tbody>${scorers}</tbody></table></div>
      </article>`;
  }

  function templateGoalsHtml(t, vale) {
    const tg = t.goals || {};
    const vm = vale?.goal_mix || {};
    const block = (title, part, items) => {
      const rows = items.filter(([k]) => tg[part]?.[k] && (tg[part][k].share >= 0.5 || (vm[part]?.[k] || 0) >= 0.5)).map(([k, label, color]) => {
        const cell = tg[part][k];
        const v = vm[part]?.[k];
        const dots = cell.by_season.map((s) => `<span class="st-gap__dot" style="left:${Math.min(100, s.share * (100 / 60))}%;background:${CLUB_COLORS[s.club]}" title="${esc(clubLabel(s.club))} ${esc(s.season)}: ${num(s.share, 0)}%"></span>`).join("");
        const gap = v === undefined || v === null ? null : v - cell.share;
        return `<div class="st-trait">
          <span class="st-gap__label">${color ? `<i class="st-src" style="background:${color}"></i>` : ""}${esc(label)} <em class="st-dim">template ${num(cell.share, 0)}%</em></span>
          <span class="st-gap__track">${dots}${v !== undefined && v !== null ? `<span class="st-gap__dot st-gap__dot--vale" style="left:${Math.min(100, v * (100 / 60))}%" title="Port Vale ${num(v, 0)}%"></span>` : ""}</span>
          <span class="st-trait__verdict">${gap === null ? "" : `<span class="st-chip st-chip--${Math.abs(gap) < 5 ? "good" : "style"}">Port Vale ${num(v, 0)}%${Math.abs(gap) >= 5 ? ` (${gap > 0 ? "+" : ""}${num(gap, 0)})` : ""}</span>`}</span>
        </div>`;
      }).join("");
      return `<article class="card"><p class="at-panel__kicker">${esc(title)}</p>${rows || '<p class="st-note">No data.</p>'}</article>`;
    };
    return `${sectionHead("Where the goals come from", "Goals", `Share of goals in each success season (dots, scale 0–60%) against Port Vale ${esc(vale ? vale.label : "")} (ringed). The success seasons averaged <b>${num(tg.per_game, 2)}</b> goals a game scored and <b>${num(tg.conceded_per_game, 2)}</b> conceded.`)}
      <div class="at-grid st-grid--2">
        ${block("Goals scored by phase", "phases", PHASES)}
        ${block("Goals conceded by phase", "against_phases", PHASES)}
        ${block("Goals by type of finish", "actions", ACTIONS)}
        ${block("Goals by scorer's position", "groups", GROUPS)}
      </div>`;
  }

  function recordRow(label, rec, vrec) {
    if (!rec || !rec.p) return "";
    return `<tr><td>${esc(label)}</td><td>${rec.p}</td><td>${rec.w}-${rec.d}-${rec.l}</td><td>${rec.gf}–${rec.ga}</td><td class="st-strong">${num(rec.ppg, 2)}</td><td class="st-vale-col">${vrec && vrec.p ? num(vrec.ppg, 2) : "—"}</td></tr>`;
  }

  function patternsHtml(key, cs, vale) {
    const p = cs.patterns;
    const vp = vale?.patterns || {};
    const ht = p.half_time;
    const results = (cs.results || []).slice().sort((a, b) => a.date.localeCompare(b.date));
    const strip = results.map((r) =>
      `<span class="st-res st-res--${r.res}" title="${esc(r.date)} ${r.ha === "H" ? "vs" : "at"} ${esc(r.opp)} (${ordinal(r.opp_pos)}) ${r.gf}-${r.ga}${r.ht_gf !== null && r.ht_gf !== undefined ? ` · HT ${r.ht_gf}-${r.ht_ga}` : ""}${r.formation ? ` · ${esc(r.formation)}` : ""}">${r.res}</span>`).join("");
    const blocks = (p.blocks || []).map((b) => `<div class="st-block"><span>Games ${b.from}–${b.to}</span><strong>${num(b.ppg, 2)}</strong><em>${b.w}-${b.d}-${b.l}</em></div>`).join("");
    const managers = (cs.managers || []).map((m) => `<tr><td>${esc(m.name)}</td><td>${esc(m.from)} → ${esc(m.to)}</td><td>${m.games}</td><td class="st-strong">${num(m.ppg, 2)}</td></tr>`).join("");
    const tiles = [
      ["Clean sheets", p.clean_sheets, vale ? vale.patterns.clean_sheets : null],
      ["Failed to score", p.failed_to_score, vale ? vale.patterns.failed_to_score : null],
      ["One-goal games won / lost", `${p.one_goal.won} / ${p.one_goal.lost}`, vale ? `${vale.patterns.one_goal.won} / ${vale.patterns.one_goal.lost}` : null],
      ["Points from losing positions at HT", p.points_from_behind, vale ? vale.patterns.points_from_behind : null],
      ["Points dropped from winning at HT", p.points_dropped_from_ahead, vale ? vale.patterns.points_dropped_from_ahead : null],
      ["Longest unbeaten", p.longest_unbeaten, vale ? vale.patterns.longest_unbeaten : null],
      ["Longest winning run", p.longest_winning, vale ? vale.patterns.longest_winning : null],
      ["Longest without a win", p.longest_winless, vale ? vale.patterns.longest_winless : null],
    ].map(([l, v, vv]) => `<div class="st-kpi"><span class="st-kpi__label">${esc(l)}</span><span class="st-kpi__value">${esc(v)}</span>${vv !== null ? `<span class="st-kpi__sub">Port Vale ${esc(vv)}</span>` : ""}</div>`).join("");
    return `${sectionHead("How their seasons were won", "Patterns", `Results splits, game states and runs for ${esc(cs.label)}. Port Vale column = ${esc(vale ? vale.label : "—")}.`)}
      <article class="card"><p class="at-panel__kicker">Every league game in order</p><div class="st-strip">${strip}</div><div class="st-blocks">${blocks}</div></article>
      <div class="at-grid st-grid--2">
        <article class="card">
          <p class="at-panel__kicker">Results by split</p>
          <table class="st-table"><thead><tr><th></th><th>P</th><th>W-D-L</th><th>Goals</th><th>PPG</th><th class="st-vale-col">PV PPG</th></tr></thead><tbody>
            ${recordRow("Overall", p.overall, vp.overall)}
            ${recordRow("Home", p.home, vp.home)}
            ${recordRow("Away", p.away, vp.away)}
            ${recordRow("vs top half", p.vs_top_half, vp.vs_top_half)}
            ${recordRow("vs bottom half", p.vs_bottom_half, vp.vs_bottom_half)}
            ${recordRow("vs top 7", p.vs_top7, vp.vs_top7)}
            ${recordRow("Leading at HT", ht.leading, vp.half_time?.leading)}
            ${recordRow("Level at HT", ht.level, vp.half_time?.level)}
            ${recordRow("Trailing at HT", ht.trailing, vp.half_time?.trailing)}
            ${recordRow("Scored 2+", p.scored_2plus, vp.scored_2plus)}
            ${recordRow("Conceded 2+", p.conceded_2plus, vp.conceded_2plus)}
          </tbody></table>
        </article>
        <article class="card">
          <p class="at-panel__kicker">Game management</p>
          <div class="st-kpis st-kpis--2">${tiles}</div>
          ${managers ? `<p class="at-panel__kicker st-mt">Head coaches</p><table class="st-table"><thead><tr><th>Coach</th><th>Span</th><th>Games</th><th>PPG</th></tr></thead><tbody>${managers}</tbody></table>` : ""}
        </article>
      </div>`;
  }

  function pitchHtml(xi, color) {
    const dots = xi.map((p) => `
      <div class="st-pitch__p" style="left:${p.x}%;top:${p.y}%;--club:${color}" title="${esc(p.name)} · ${esc(p.pos)} · ${p.starts_in_slot} starts here${p.profile ? ` · ${esc(p.profile)}` : ""}">
        <span class="st-pitch__dot">${esc(p.pos)}</span>
        <span class="st-pitch__name">${esc(p.name.split(" ").slice(-1)[0])}</span>
        <span class="st-pitch__meta">${p.age ? `${Math.floor(p.age)}y · ` : ""}${p.minutes ?? 0}′${p.goals ? ` · ${p.goals}g` : ""}</span>
      </div>`).join("");
    return `<div class="st-pitch"><div class="st-pitch__lines"><span class="st-pitch__half"></span><span class="st-pitch__circle"></span><span class="st-pitch__box st-pitch__box--top"></span><span class="st-pitch__box st-pitch__box--bot"></span></div>${dots}</div>`;
  }

  function squadSummaryRows(cs, vale) {
    const s = cs.squad.summary, v = vale?.squad?.summary || {};
    const rows = [
      ["Players used", s.players_used, v.players_used, 0, ""],
      ["Players with 2,000+ minutes", s.core_players, v.core_players, 0, ""],
      ["Minutes-weighted age", s.avg_age, v.avg_age, 1, ""],
      ["Outfield height (weighted)", s.avg_height, v.avg_height, 2, " m"],
      ["Minutes taken by top 11", s.top11_share, v.top11_share, 1, "%"],
      ["Minutes to U23s", s.u23_share, v.u23_share, 1, "%"],
      ["Minutes to 30+", s.over30_share, v.over30_share, 1, "%"],
      ["Left-footed outfield minutes", s.left_foot_pct, v.left_foot_pct, 1, "%"],
      ["Different scorers", s.scorers, v.scorers, 0, ""],
      ["Goals from top 3 scorers", s.top3_goal_share, v.top3_goal_share, 1, "%"],
    ];
    return rows.map(([l, a, b, d, u]) => `<tr><td>${esc(l)}</td><td class="st-strong">${a === null || a === undefined ? "—" : num(a, d) + u}</td><td class="st-vale-col">${b === null || b === undefined ? "—" : num(b, d) + u}</td></tr>`).join("");
  }

  function playersTableHtml(cs) {
    const sorters = {
      minutes: (a, b) => b.minutes - a.minutes,
      age: (a, b) => (a.age ?? 99) - (b.age ?? 99),
      goals: (a, b) => b.goals - a.goals || b.assists - a.assists,
      pos: (a, b) => ["GK", "DEF", "MID", "ATT", ""].indexOf(a.group) - ["GK", "DEF", "MID", "ATT", ""].indexOf(b.group) || b.minutes - a.minutes,
    };
    const players = cs.squad.players.filter((p) => p.minutes > 0).sort(sorters[state.playerSort] || sorters.minutes);
    const total = players.reduce((s, p) => s + p.minutes, 0) || 1;
    const head = [["pos", "Pos"], ["", "Player"], ["age", "Age"], ["", "Ht"], ["", "Foot"], ["minutes", "Min"], ["", "Share"], ["", "Starts"], ["goals", "G"], ["", "A"], ["", "xG"], ["", "Impect profile"], ["", "Status"]];
    return `<table class="st-table st-table--players"><thead><tr>${head.map(([k, l]) => k ? `<th><button type="button" class="st-sort${state.playerSort === k ? " is-active" : ""}" data-sort="${k}">${l}</button></th>` : `<th>${l}</th>`).join("")}</tr></thead><tbody>
      ${players.map((p) => `<tr>
        <td><span class="st-pos st-pos--${esc(p.group)}">${esc(p.pos)}</span></td>
        <td class="st-strong">${esc(p.name)}</td>
        <td>${p.age ? Math.floor(p.age) : "—"}</td>
        <td>${p.height ? num(p.height, 2) : "—"}</td>
        <td>${esc((p.foot || "").slice(0, 1) || "—")}</td>
        <td>${p.minutes.toLocaleString("en-GB")}</td>
        <td><span class="st-share"><span style="width:${(100 * p.minutes) / (players[0] ? Math.max(...players.map((x) => x.minutes)) : 1)}%"></span></span>${num((100 * p.minutes) / total, 1)}%</td>
        <td>${p.starts}${p.sub_apps ? ` <span class="st-dim">(+${p.sub_apps})</span>` : ""}</td>
        <td>${p.goals || ""}</td>
        <td>${p.assists || ""}</td>
        <td>${p.xg ? num(p.xg, 1) : ""}</td>
        <td>${p.profile ? `${esc(p.profile)} <span class="st-dim">${num(p.profile_score)}</span>` : "—"}</td>
        <td>${p.status === "new" ? `<span class="st-chip st-chip--new" title="${esc(p.arrived_from || "Outside Impect cover")}">New${p.arrived_from ? ` · ${esc(p.arrived_from)}` : ""}</span>` : p.status === "retained" ? '<span class="st-chip">Retained</span>' : ""}</td>
      </tr>`).join("")}
    </tbody></table>`;
  }

  function squadHtml(key, cs, vale) {
    const mix = cs.squad.profile_mix || [];
    const mixMax = Math.max(1, ...mix.map((m) => m.minutes));
    return `${sectionHead("Who they used", "Squad archetype", `The most-used XI in their main shape (${esc(cs.squad.main_formation || "—")}), how the minutes were shared, and the Impect player profiles they were built on.`)}
      <div class="at-grid st-grid--squad">
        <article class="card"><p class="at-panel__kicker">Most-used XI · ${esc(cs.squad.main_formation || "")}</p>${pitchHtml(cs.squad.xi || [], CLUB_COLORS[key])}</article>
        <article class="card">
          <p class="at-panel__kicker">Squad shape</p>
          <table class="st-table"><thead><tr><th></th><th>${esc(clubLabel(key))}</th><th class="st-vale-col">Port Vale ${esc(vale ? vale.season_long : "")}</th></tr></thead><tbody>${squadSummaryRows(cs, vale)}</tbody></table>
          <p class="st-note">Top scorer: ${cs.squad.summary.top_scorer ? `${esc(cs.squad.summary.top_scorer.name)} (${cs.squad.summary.top_scorer.goals})` : "—"}</p>
        </article>
        <article class="card">
          <p class="at-panel__kicker">Impect PV profiles (450+ minutes)</p>
          <h3 class="at-panel__title">Profile mix by minutes</h3>
          ${mix.map((m) => `<div class="st-mini"><span>${esc(m.profile)}</span><span class="st-mini__track"><span style="width:${(100 * m.minutes) / mixMax}%"></span></span><span>${m.minutes.toLocaleString("en-GB")}</span></div>`).join("") || '<p class="st-note">No profile scores.</p>'}
        </article>
      </div>
      <article class="card st-mt"><p class="at-panel__kicker">Every player used · click a header to sort</p><div class="st-table-wrap" id="playersTable">${playersTableHtml(cs)}</div></article>`;
  }

  function wirePlayerSort(key, cs) {
    const wrap = $("#playersTable");
    if (!wrap) return;
    wrap.onclick = (e) => {
      const btn = e.target.closest("[data-sort]");
      if (!btn) return;
      state.playerSort = btn.dataset.sort;
      wrap.innerHTML = playersTableHtml(cs);
    };
  }

  const SOURCE_SHORT = { step_up: "Step up", same_level: "Same level", drop_down: "Drop down", academy: "Academy / PL2", scotland: "Scotland", outside: "Outside cover" };
  const SOURCE_COLORS = { step_up: "#34d399", same_level: "#60a5fa", drop_down: "#f5c518", academy: "#c084fc", scotland: "#22d3ee", outside: "#64748b" };

  function recruitmentHtml(key, club, cs) {
    const seasons = seasonsOf(key);
    const rec = cs.recruitment || {};
    const history = seasons.map((s) => {
      const r = s.recruitment || {};
      if (!r.covered) return `<tr><td>${esc(s.season_long)}</td><td>${esc(s.competition)}</td><td colspan="6" class="st-dim">Previous season outside Impect cover</td><td>${s.partial ? "—" : esc(ordinal(s.table.position))}</td></tr>`;
      return `<tr class="${s.season === cs.season ? "is-active" : ""}"><td>${esc(s.season_long)}</td><td>${esc(s.competition)}</td>
        <td>${num(r.retained_share_prev, 0)}%</td><td>${r.arrivals_count}</td><td>${r.arrivals_core}</td><td>${r.arrivals_rotation}</td>
        <td>${num(r.new_minutes_share, 0)}%</td><td>${r.hit_rate === null ? "—" : `${num(r.hit_rate, 0)}%`}</td><td class="st-strong">${esc(ordinal(s.table.position))}</td></tr>`;
    }).join("");
    let body;
    if (!rec.covered) {
      body = `<article class="card st-empty">${esc(rec.note || "Not covered.")}</article>`;
    } else {
      const mix = rec.source_mix || [];
      const mixTotal = mix.reduce((s, m) => s + m.minutes, 0) || 1;
      const stacked = mix.map((m) => `<span style="width:${(100 * m.minutes) / mixTotal}%;background:${SOURCE_COLORS[m.source]}" title="${esc(m.label)}: ${m.count} players, ${m.minutes.toLocaleString("en-GB")} min"></span>`).join("");
      const legend = mix.map((m) => `<li><i style="background:${SOURCE_COLORS[m.source]}"></i>${esc(m.label)} <strong>${m.count}</strong> · ${num((100 * m.minutes) / mixTotal, 0)}% of new minutes</li>`).join("");
      const arrivals = (rec.arrivals || []).map((a) => `<tr>
        <td><span class="st-chip st-chip--${a.impact}">${esc(a.impact)}</span></td>
        <td class="st-strong">${esc(a.name)}</td><td>${esc(a.pos)}</td><td>${a.age ? Math.floor(a.age) : "—"}</td>
        <td>${a.from_club ? `${esc(a.from_club)} <span class="st-dim">${esc(a.from_competition)} · ${a.from_minutes}′</span>` : '<span class="st-dim">Outside Impect cover</span>'}</td>
        <td title="${esc(state.data.source_labels[a.source] || "")}"><i class="st-src" style="background:${SOURCE_COLORS[a.source]}"></i>${esc(SOURCE_SHORT[a.source] || a.source)}</td>
        <td>${a.minutes.toLocaleString("en-GB")}</td><td>${a.starts}</td><td>${a.goals || ""}${a.assists ? `<span class="st-dim"> +${a.assists}a</span>` : ""}</td>
        <td>${a.profile ? esc(a.profile) : "—"}</td></tr>`).join("");
      const departures = (rec.departures || []).filter((d) => d.minutes_before > 0).map((d) => `<tr>
        <td class="st-strong">${esc(d.name)}</td><td>${esc(d.pos || "")}</td><td>${d.age ? Math.floor(d.age) : "—"}</td>
        <td>${d.minutes_before.toLocaleString("en-GB")} <span class="st-dim">(${num(d.share_before, 1)}%)</span></td>
        <td>${d.to_club ? `${esc(d.to_club)} <span class="st-dim">${esc(d.to_competition)} · ${d.to_minutes}′</span>` : '<span class="st-dim">Outside Impect cover / unknown</span>'}</td></tr>`).join("");
      body = `
        <div class="st-kpis st-kpis--6">
          ${[["Last season's minutes kept", `${num(rec.retained_share_prev, 0)}%`], ["Minutes to new players", `${num(rec.new_minutes_share, 0)}%`], ["New players used", rec.arrivals_count], ["Became core (2,000+)", rec.arrivals_core], ["Hit rate (900+ min)", rec.hit_rate === null ? "—" : `${num(rec.hit_rate, 0)}%`], ["Age of arrivals who played", num(rec.avg_age_used_arrivals, 1)]]
            .map(([l, v]) => `<div class="st-kpi"><span class="st-kpi__label">${esc(l)}</span><span class="st-kpi__value">${esc(v)}</span></div>`).join("")}
        </div>
        <article class="card st-mt"><p class="at-panel__kicker">Where the new minutes came from</p><div class="st-stack">${stacked}</div><ul class="st-legend">${legend}</ul></article>
        <article class="card st-mt"><p class="at-panel__kicker">Arrivals · ${esc(cs.season_long)} (players who appeared, by minutes)</p>
          <div class="st-table-wrap"><table class="st-table"><thead><tr><th>Impact</th><th>Player</th><th>Pos</th><th>Age</th><th>Came from (minutes there the season before)</th><th>Type</th><th>Min</th><th>Starts</th><th>G</th><th>Profile</th></tr></thead><tbody>${arrivals || '<tr><td colspan="10" class="st-dim">No new players used.</td></tr>'}</tbody></table></div>
        </article>
        <article class="card st-mt"><p class="at-panel__kicker">Departures after ${esc(seasonOf(key, prevSeasonCode(cs.season))?.season_long || "last season")} (by minutes they played)</p>
          <div class="st-table-wrap"><table class="st-table"><thead><tr><th>Player</th><th>Pos</th><th>Age</th><th>Minutes (share)</th><th>Went to (minutes there)</th></tr></thead><tbody>${departures || '<tr><td colspan="5" class="st-dim">Nobody who played left.</td></tr>'}</tbody></table></div>
        </article>`;
    }
    return `${sectionHead("How they built it", "Recruitment history", "Who came in, where from, and whether they played. Where a signing came from is traced through every League One, League Two, National League (North/South), Premier League 2 and Scottish Premiership squad in Impect; Championship and foreign moves show as outside cover.")}
      <article class="card"><p class="at-panel__kicker">Season by season</p>
        <div class="st-table-wrap"><table class="st-table"><thead><tr><th>Season</th><th>League</th><th>Minutes kept</th><th>New used</th><th>New core</th><th>New rotation</th><th>New minutes</th><th>Hit rate</th><th>Finish</th></tr></thead><tbody>${history}</tbody></table></div>
      </article>
      <div class="st-mt">${body}</div>
      <article class="card st-mt" id="windowPanel"></article>`;
  }

  function renderRecruitmentWindow() {
    const panel = $("#windowPanel");
    if (!panel) return;
    const teamId = TRANSFER_TEAM_IDS[state.club];
    const team = state.transfers ? (state.transfers.leagues || []).flatMap((l) => l.teams || []).find((t) => t.id === teamId) : null;
    if (!team) {
      panel.innerHTML = `<p class="at-panel__kicker">Summer 2026 window</p><p class="st-note">${state.transfers ? `${esc(clubLabel(state.club))} are not in the League One / League Two summer 2026 transfer report.` : "Loading transfer report…"}</p>`;
      return;
    }
    const list = (rows, cls) => (rows || []).map((r) => `<li class="${cls}"><strong>${esc(r.player)}</strong><span>${esc(r.other || "")}</span><em>${esc(r.fee || "")}</em></li>`).join("") || '<li class="st-dim">None listed</li>';
    panel.innerHTML = `<p class="at-panel__kicker">Summer 2026 window · from the EFL Transfer Report</p>
      <div class="at-grid st-grid--3 st-window">
        <div><h4>Signed (${team.signed_count ?? (team.signed || []).length})</h4><ul>${list(team.signed, "in")}</ul></div>
        <div><h4>Sold / left (${team.left_count ?? (team.left || []).length})</h4><ul>${list(team.left, "out")}</ul></div>
        <div><h4>Released (${team.released_count ?? (team.released || []).length})</h4><ul>${list(team.released, "out")}</ul></div>
      </div>`;
  }

  function gapRows(cs, vale, filterFn) {
    return state.data.metrics.filter(filterFn).map((m) => {
      const a = cs.style[m.key], b = vale?.style?.[m.key];
      if (!a || !b) return null;
      return { m, a, b, gap: (goodPct(m, a.pct_high) ?? 0) - (goodPct(m, b.pct_high) ?? 0), styleGap: a.pct_high - b.pct_high };
    }).filter(Boolean);
  }

  function gapBarHtml(row, mode) {
    const { m, a, b } = row;
    const ap = mode === "good" ? goodPct(m, a.pct_high) : a.pct_high;
    const bp = mode === "good" ? goodPct(m, b.pct_high) : b.pct_high;
    const left = Math.min(ap, bp), width = Math.abs(ap - bp);
    return `<div class="st-gap">
      <span class="st-gap__label">${esc(m.label)}</span>
      <span class="st-gap__track">
        <span class="st-gap__span" style="left:${left}%;width:${width}%"></span>
        <span class="st-gap__dot st-gap__dot--club" style="left:${ap}%" title="${esc(fmtMetric(m, a.value))}"></span>
        <span class="st-gap__dot st-gap__dot--vale" style="left:${bp}%" title="Port Vale ${esc(fmtMetric(m, b.value))}"></span>
      </span>
      <span class="st-gap__vals"><b>${esc(fmtMetric(m, a.value))}</b> vs <b class="st-vale-text">${esc(fmtMetric(m, b.value))}</b></span>
    </div>`;
  }

  function vsValeHtml(key, cs, vale) {
    if (!vale) return `${sectionHead("Side by side", "vs Port Vale", "")}<div class="card st-empty">No Port Vale season selected.</div>`;
    const good = gapRows(cs, vale, (m) => m.better).sort((x, y) => y.gap - x.gap);
    const ahead = good.filter((r) => r.gap >= 15);
    const behind = good.filter((r) => r.gap <= -15).sort((x, y) => x.gap - y.gap);
    const style = gapRows(cs, vale, (m) => !m.better).sort((x, y) => Math.abs(y.styleGap) - Math.abs(x.styleGap)).slice(0, 10);
    const crossLeague = cs.competition !== vale.competition;
    return `${sectionHead("Side by side", `${esc(clubLabel(key))} vs Port Vale`, `${esc(cs.label)} against Port Vale ${esc(vale.label)}. Dots are league percentiles: <b class="st-club-text" style="color:${CLUB_COLORS[key]}">${esc(clubLabel(key))}</b> and <b class="st-vale-text">Port Vale</b>, with the line showing the gap.${crossLeague ? " The two seasons are in different divisions, so each is ranked within its own league." : ""}`)}
      <div class="at-grid st-grid--2">
        <article class="card" style="--club:${CLUB_COLORS[key]}"><p class="at-panel__kicker">Where ${esc(clubLabel(key))} were clearly better (good-direction percentile)</p>
          ${ahead.map((r) => gapBarHtml(r, "good")).join("") || '<p class="st-note">No gaps of 15+ percentile points.</p>'}</article>
        <article class="card" style="--club:${CLUB_COLORS[key]}"><p class="at-panel__kicker">Where Port Vale were already better</p>
          ${behind.map((r) => gapBarHtml(r, "good")).join("") || '<p class="st-note">No gaps of 15+ percentile points.</p>'}</article>
      </div>
      <article class="card st-mt" style="--club:${CLUB_COLORS[key]}"><p class="at-panel__kicker">Biggest style differences (no right or wrong, just how each side plays)</p>
        ${style.map((r) => gapBarHtml(r, "style")).join("")}</article>`;
  }

  // ---------------------------------------------------------------- template view

  function renderTemplate() {
    const t = state.data.template;
    const vale = seasonOf("vale", state.valeSeason);
    $("#view").innerHTML = [
      `<section id="overview" class="at-section">${templateOverviewHtml(t)}</section>`,
      `<section id="traits" class="at-section">${templateTraitsHtml(t, vale)}</section>`,
      `<section id="goals" class="at-section">${templateGoalsHtml(t, vale)}</section>`,
      `<section id="squad" class="at-section">${templateSquadHtml(t, vale)}</section>`,
      `<section id="patterns" class="at-section">${templatePatternsHtml(t, vale)}</section>`,
      `<section id="lessons" class="at-section">${templateLessonsHtml()}</section>`,
      `<section id="notes" class="at-section">${notesHtml(TEMPLATE_KEY)}</section>`,
    ].join("");
    wireNotes(TEMPLATE_KEY);
  }

  function templateOverviewHtml(t) {
    const rows = t.seasons.map((s) => `<div class="st-tseason" style="--club:${CLUB_COLORS[s.club]}">
      ${badge(state.data.clubs[s.club].badge)}
      <div><strong>${esc(clubLabel(s.club))}</strong><span>${esc(s.competition)} ${esc(s.season)}</span></div>
      <div class="st-tseason__res"><b>${esc(ordinal(s.position))}</b><span>${s.points} pts</span></div>
      <em>${esc(s.outcome)}</em></div>`).join("");
    return `<div class="card st-hero" style="--club:var(--gold)">
        <p class="at-kicker">Shadow template</p>
        <h2 class="st-hero__name">What the three have in common</h2>
        <p class="st-hero__lede">${esc(t.intro)}</p>
        <p class="st-note">Built from these success seasons. Each is ranked against its own league, so a League Two title and a League One title can be compared fairly.</p>
        <div class="st-tseasons">${rows}</div>
      </div>`;
  }

  function templateTraitsHtml(t, vale) {
    const specs = state.data.metrics;
    const rows = specs.map((m) => ({ m, cell: t.style[m.key], vc: vale?.style?.[m.key] })).filter((r) => r.cell);
    const shared = rows.filter((r) => r.cell.shared);
    const rest = rows.filter((r) => !r.cell.shared);
    const traitHtml = ({ m, cell, vc }) => {
      const dots = cell.by_season.map((s) => `<span class="st-gap__dot" style="left:${s.pct}%;background:${CLUB_COLORS[s.club]}" title="${esc(clubLabel(s.club))} ${esc(s.season)}: ${esc(fmtMetric(m, s.value))} (${ordinal(s.rank)})"></span>`).join("");
      const vgap = vc ? vc.pct_high - cell.pct : null;
      const verdict = vc === undefined || vc === null ? "" : (Math.abs(vgap) < 15 ? '<span class="st-chip st-chip--good">On template</span>'
        : `<span class="st-chip st-chip--${m.better ? ((m.better === "high") === (vgap < 0) ? "bad" : "good") : "style"}">${vgap < 0 ? "Port Vale lower" : "Port Vale higher"} by ${Math.abs(Math.round(vgap))}</span>`);
      return `<div class="st-trait">
        <span class="st-gap__label">${esc(m.label)}${cell.shared ? ` <em class="st-dim">${cell.shared === "high" ? "all high" : "all low"}</em>` : ""}</span>
        <span class="st-gap__track"><span class="st-trait__band" style="left:${cell.min_pct}%;width:${cell.max_pct - cell.min_pct}%"></span>${dots}${vc ? `<span class="st-gap__dot st-gap__dot--vale" style="left:${vc.pct_high}%" title="Port Vale ${esc(fmtMetric(m, vc.value))}"></span>` : ""}</span>
        <span class="st-trait__verdict">${verdict}</span>
      </div>`;
    };
    const legend = Object.keys(state.data.clubs).map((k) => `<li><i style="background:${CLUB_COLORS[k]}"></i>${esc(clubLabel(k))}</li>`).join("") + `<li><i class="st-vale-swatch"></i>Port Vale ${esc(vale ? vale.label : "")}</li>`;
    return `${sectionHead("Copy these", "Shared traits", "Metrics where every success season sat on the same side of its league (all at or above the 60th percentile, or all at or below the 40th). The shaded band is the range across the success seasons. Port Vale is the ringed dot.")}
      <article class="card"><ul class="st-legend st-legend--row">${legend}</ul>${shared.map(traitHtml).join("") || '<p class="st-note">No fully shared traits.</p>'}</article>
      <details class="card st-mt st-details"><summary>Everything else (traits where the three differ)</summary>${rest.map(traitHtml).join("")}</details>`;
  }

  function templateCompareTable(obj, valeValue, title) {
    const rows = Object.entries(obj).map(([key, row]) => {
      const v = valeValue(key);
      const unit = row.unit === "%" ? "%" : row.unit === "m" ? " m" : "";
      const per = row.by_season.map((s) => `<span class="st-dot-val" style="--club:${CLUB_COLORS[s.club]}" title="${esc(clubLabel(s.club))} ${esc(s.season)}">${s.value === null || s.value === undefined ? "—" : num(s.value, row.digits ?? 2)}</span>`).join("");
      return `<tr><td>${esc(row.label)}</td><td class="st-strong">${row.value === null ? "—" : num(row.value, row.digits ?? 2) + unit}</td><td class="st-vale-col">${v === null || v === undefined ? "—" : num(v, row.digits ?? 2) + unit}</td><td class="st-per">${per}</td></tr>`;
    }).join("");
    return `<article class="card"><p class="at-panel__kicker">${esc(title)}</p><table class="st-table"><thead><tr><th></th><th>Template</th><th class="st-vale-col">Port Vale</th><th>Each success season</th></tr></thead><tbody>${rows}</tbody></table></article>`;
  }

  function templateSquadHtml(t, vale) {
    const squad = templateCompareTable(t.squad, (k) => vale?.squad?.summary?.[k], "Squad shape");
    const recruit = templateCompareTable(t.recruitment, (k) => vale?.recruitment?.[k], "Recruitment in the success seasons");
    return `${sectionHead("Who they used and how they built it", "Squad & recruitment", `Averages across the success seasons against Port Vale ${esc(vale ? vale.label : "")}.`)}<div class="at-grid st-grid--2">${squad}${recruit}</div>`;
  }

  function templatePatternsHtml(t, vale) {
    const table = templateCompareTable(
      Object.fromEntries(Object.entries(t.patterns).map(([k, v]) => [k, { ...v, digits: k.endsWith("rate") && !k.startsWith("points") ? 1 : 2, unit: k.endsWith("rate") && !k.startsWith("points") ? "%" : "" }])),
      (k) => vale?.pattern_rates?.[k],
      "Results patterns",
    );
    return `${sectionHead("How the seasons were won", "Patterns", `Expected points per game across the success seasons: <b>${num(t.xppg, 2)}</b>${vale ? ` · Port Vale ${esc(vale.label)}: <b class="st-vale-text">${num(vale.table.xppg, 2)}</b>` : ""}.`)}${table}`;
  }

  function templateLessonsHtml() {
    const cards = state.data.club_order.map((k) => {
      const c = state.data.clubs[k];
      return `<article class="card st-lessons" style="--club:${CLUB_COLORS[k]}"><p class="at-panel__kicker">${esc(c.name)}</p><ol class="st-list st-list--num">${(c.lessons || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ol></article>`;
    }).join("");
    return `${sectionHead("For Port Vale", "Lessons", "What each club's route says we should copy.")}<div class="at-grid st-grid--3">${cards}</div>`;
  }

  // ---------------------------------------------------------------- notes

  function notesHtml(key) {
    const notes = state.notes.filter((n) => n.club === key).slice().reverse();
    const label = key === TEMPLATE_KEY ? "the shadow template" : clubLabel(key);
    return `${sectionHead("Staff", "Staff notes", `Notes on ${esc(label)}: what to copy, questions to ask, contacts. Everyone with access to this tool can see them.`)}
      <article class="card">
        <form class="st-noteform" id="noteForm"><textarea id="noteText" rows="3" placeholder="Add a note on ${esc(label)}…" maxlength="4000"></textarea><button type="submit" class="at-toggle__btn at-toggle__btn--active">Save note</button></form>
        <ul class="st-notes">${notes.map((n) => `<li><p>${esc(n.text)}</p><span>${esc(n.author)} · ${esc((n.created || "").replace("T", " ").slice(0, 16))}</span><button type="button" class="st-notes__del" data-id="${esc(n.id)}" title="Delete">×</button></li>`).join("") || '<li class="st-dim">No notes yet.</li>'}</ul>
      </article>`;
  }

  function wireNotes(key) {
    const form = $("#noteForm");
    if (!form) return;
    form.onsubmit = async (e) => {
      e.preventDefault();
      const text = $("#noteText").value.trim();
      if (!text) return;
      const res = await fetch("/api/shadow-teams/notes", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ club: key, text }),
      });
      if (!res.ok) { status("Could not save note."); return; }
      state.notes.push((await res.json()).note);
      $("#notes").innerHTML = notesHtml(key);
      wireNotes(key);
      status("Note saved.");
    };
    document.querySelectorAll(".st-notes__del").forEach((btn) => btn.addEventListener("click", async () => {
      if (!confirm("Delete this note?")) return;
      const res = await fetch(`/api/shadow-teams/notes/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE", credentials: "same-origin" });
      if (!res.ok) { status("Could not delete note."); return; }
      state.notes = state.notes.filter((n) => n.id !== btn.dataset.id);
      $("#notes").innerHTML = notesHtml(key);
      wireNotes(key);
    }));
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
