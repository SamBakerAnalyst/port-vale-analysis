/**
 * Port Vale Hub — home dashboard (tabs + live widgets + activity/changelog).
 */
(function initHubHome(global) {
  const COMPETITION = "League Two";
  const FALLBACK_ITERATION = 2120;
  const FALLBACK_SQUAD = 882;
  let activeTab = "home";
  let refreshTimer = null;
  let cachedMatches = [];
  let cachedFixtures = null;
  let cachedStrategyBundle = null;
  let cachedStrategySnapshot = null;
  let cachedScoutCalendar = null;
  let cachedSchedule = null;
  let scheduleMonthKey = "";
  let scheduleOwner = "team";
  let scheduleSaving = false;
  let recruitmentLoaded = false;
  let standoutsLoaded = false;
  let standoutsPollTimer = null;
  let recruitSub = "league";
  let standoutsPeriod = "season";
  let standoutsPosition = "ALL";
  let standoutsYear = null;
  let standoutsMonth = null;
  let standoutsU25 = false;
  let standoutsProfile = "";
  let standoutsLastData = null;
  let strategyDetailLoaded = false;
  /** @type {Map<number, {id: string, stage: string, name: string}>} */
  let watchByPlayerId = new Map();
  let watchBusy = new Set();
  let watchListLoaded = false;
  let watchBoardCache = null;

  const WATCH_STAGE = "watch_list";
  const WATCH_TAG = "Watching";
  /** Already on the pipeline board — unticking removes them from Pipelines. */
  const PIPELINE_STAGES = new Set([
    "watched",
    "data_identified",
    "scout_identified",
    "video_scouted",
    "live_scouted",
    "gone_elsewhere",
    "not_the_right_fit",
  ]);
  const STAGE_CHIP = {
    watch_list: { kind: "watch", label: "Watch", title: "On the Watch list" },
    watched: { kind: "pipe", label: "Watched", title: "On Pipelines · Watched" },
    data_identified: { kind: "pipe", label: "Data", title: "On Pipelines · Data identified" },
    scout_identified: { kind: "pipe", label: "Scout", title: "On Pipelines · Scout identified" },
    video_scouted: { kind: "pipe", label: "Video", title: "On Pipelines · Video scouted" },
    live_scouted: { kind: "pipe", label: "Live", title: "On Pipelines · Live scouted" },
    gone_elsewhere: { kind: "closed", label: "Gone", title: "On Pipelines · Gone / turned us down" },
    not_the_right_fit: { kind: "closed", label: "Out", title: "On Pipelines · Not the right fit" },
  };

  function stageChipMeta(stage) {
    return (
      STAGE_CHIP[stage] || {
        kind: "pipe",
        label: "Pipe",
        title: `On Pipelines · ${String(stage || "").replaceAll("_", " ")}`,
      }
    );
  }

  const SCHEDULE_OWNERS = [
    { id: "team", label: "Team" },
    { id: "sam", label: "Sam" },
    { id: "tommy", label: "Tommy" },
    { id: "lee", label: "Lee" },
    { id: "martin", label: "Martin" },
  ];

  function fmt(n, digits = 1) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return Number(n).toFixed(digits);
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  function widgetError(id, message) {
    setHtml(id, `<p class="home-empty">${message}</p>`);
  }

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, {
      signal: AbortSignal.timeout(180000),
      cache: "no-store",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        if (typeof data.detail === "string") detail = data.detail;
      } catch (_) {
        /* keep status */
      }
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  function relativeTime(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.round(mins / 60);
    if (hours < 48) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    return `${days}d ago`;
  }

  function signed(n, digits = 1) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const v = Number(n);
    return (v > 0 ? "+" : "") + v.toFixed(digits);
  }

  function todayKey() {
    return new Date().toISOString().slice(0, 10);
  }

  function monthKeyFromDate(dateKey) {
    return String(dateKey || "").slice(0, 7);
  }

  function formatMonthLabel(monthKey) {
    const [year, month] = monthKey.split("-").map(Number);
    if (!year || !month) return "—";
    return new Date(year, month - 1, 1).toLocaleDateString("en-GB", {
      month: "long",
      year: "numeric",
    });
  }

  function formatShortDate(dateKey) {
    if (!dateKey) return "";
    return new Date(`${dateKey}T12:00:00`).toLocaleDateString("en-GB", {
      weekday: "short",
      day: "numeric",
      month: "short",
    });
  }

  function formatTime(iso) {
    if (!iso) return "TBC";
    return new Date(iso).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function shiftMonth(monthKey, delta) {
    const [year, month] = monthKey.split("-").map(Number);
    const date = new Date(year, month - 1 + delta, 1);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }

  function matchDateKey(match) {
    return String(match?.scheduledDate || match?.kickoff_utc || match?.date || "").slice(0, 10);
  }

  function daysUntil(dateKey) {
    if (!dateKey) return null;
    const then = new Date(`${dateKey}T12:00:00`).getTime();
    const now = new Date(`${todayKey()}T12:00:00`).getTime();
    return Math.round((then - now) / 86400000);
  }

  function pvMatchesByDate(matches) {
    const map = {};
    (matches || []).forEach((match) => {
      const day = matchDateKey(match) || String(match?.date || "").slice(0, 10);
      if (!day) return;
      if (!map[day]) map[day] = [];
      map[day].push(match);
    });
    return map;
  }

  function scoutFixtureLabel(row) {
    const home = String(row?.home || "").trim();
    const away = String(row?.away || "").trim();
    if (home && away) return `${home} vs ${away}`;
    return home || away || "Fixture TBC";
  }

  function staffFirstName(name) {
    return String(name || "").trim().split(" ")[0] || "Scout";
  }

  function renderHomeOverview(pv, averages, seasonLabel, strategySnapshot, matches) {
    setText("homeOverviewSeason", seasonLabel || COMPETITION);
    const pace = strategySnapshot?.pace || {};
    const upcoming = (matches || []).find((m) => !m.outcome);
    const fotmobLeaguePlayed = (matches || []).filter((m) => {
      const comp = String(m.competition || "").toLowerCase();
      const isL2 = comp.includes("league two") || comp.includes("league 2");
      return isL2 && (m.outcome || m.status === "completed");
    });
    const seasonStarted =
      Number(pv?.played || 0) > 0 ||
      Number(pace.played || 0) > 0 ||
      fotmobLeaguePlayed.length > 0;

    if (!seasonStarted) {
      setKpi("homeKpiOverviewPos", "TBC", "League Two 26/27 — table not live in Impect yet");
      setKpi("homeKpiOverviewPpg", "—", "Waiting for first league games");
      setKpi("homeKpiOverviewPace", "—", "Play-off line after matchday 1");
    } else if (!pv) {
      // Season has started in FotMob but Impect standings are still catching up.
      const played = fotmobLeaguePlayed.length;
      const pts = fotmobLeaguePlayed.reduce((sum, m) => {
        const o = String(m.outcome || "").toLowerCase();
        if (o === "win" || o === "w") return sum + 3;
        if (o === "draw" || o === "d") return sum + 1;
        return sum;
      }, 0);
      const ppg = played ? pts / played : null;
      setKpi(
        "homeKpiOverviewPos",
        "Updating",
        `${pts} pts · ${played} played · table refreshing`
      );
      setKpi(
        "homeKpiOverviewPpg",
        ppg == null ? "—" : fmt(ppg, 2),
        "From results · Impect table catching up"
      );
      setKpi("homeKpiOverviewPace", "—", "Play-off line after standings load");
    } else {
      const pos = pv?.position ?? "—";
      const pts = pv?.points ?? "—";
      setKpi("homeKpiOverviewPos", `#${pos}`, `${pts} pts · ${pv?.played ?? "—"} played`);
      setKpi(
        "homeKpiOverviewPpg",
        fmt(pv?.ppg, 2),
        `League ${fmt(averages?.ppg, 2)} · xPPG ${fmt(pace.xppg ?? pv?.xppg, 2)}`
      );
      const onTrack = pace.on_track_playoff;
      setKpi(
        "homeKpiOverviewPace",
        onTrack == null ? "—" : onTrack ? "On track" : "Off pace",
        pace.playoff_ppg != null
          ? `Need ${fmt(pace.playoff_ppg, 2)} · ${signed(pace.pts_vs_playoff, 0)} pts`
          : "Play-off line"
      );
    }
    if (upcoming) {
      const days = daysUntil(matchDateKey(upcoming));
      const dayLabel =
        days === 0 ? "Today" : days === 1 ? "Tomorrow" : days != null ? `${days}d` : "TBC";
      setKpi(
        "homeKpiOverviewNext",
        upcoming.opponent?.name || "TBC",
        `${upcoming.isHome ? "Home" : "Away"} · ${dayLabel}`
      );
    } else {
      setKpi("homeKpiOverviewNext", "—", "No upcoming fixture yet");
    }
  }

  function renderTodaySchedule(matches, scoutByDate) {
    const today = todayKey();
    setText("homeTodayLabel", formatShortDate(today));
    const pvToday = pvMatchesByDate(matches)[today] || [];
    const scoutsToday = scoutByDate[today] || [];
    const items = [];

    pvToday.forEach((match) => {
      const done = !!match.outcome;
      items.push(`<article class="home-schedule-item">
        <span class="home-schedule-item__time">${formatTime(match.scheduledDate)}</span>
        <div>
          <p class="home-schedule-item__title">${match.isHome ? "vs" : "@"} ${match.opponent?.name || "TBC"}</p>
          <p class="home-schedule-item__meta">${match.isHome ? "Home" : "Away"} · Port Vale ${done ? `· ${match.scoreLabel || "FT"}` : ""}</p>
          <span class="home-schedule-item__tag home-schedule-item__tag--pv">Port Vale</span>
        </div>
      </article>`);
    });

    scoutsToday.forEach((row) => {
      const live = String(row.watch_type || "").toUpperCase() === "LIVE";
      items.push(`<article class="home-schedule-item">
        <span class="home-schedule-item__time">${formatTime(row.kickoff_utc)}</span>
        <div>
          <p class="home-schedule-item__title">${scoutFixtureLabel(row)}</p>
          <p class="home-schedule-item__meta">${row.league || "League TBC"} · ${staffFirstName(row.staff)}</p>
          <span class="home-schedule-item__tag ${live ? "home-schedule-item__tag--live" : "home-schedule-item__tag--video"}">${row.watch_type || "LIVE"}</span>
        </div>
      </article>`);
    });

    if (!items.length) {
      setHtml(
        "homeTodaySchedule",
        `<p class="home-empty">Nothing on today — check the month view or upcoming lists below.</p>`
      );
      return;
    }
    setHtml("homeTodaySchedule", `<div class="home-schedule-list">${items.join("")}</div>`);
  }

  function renderPeopleTabs() {
    const root = document.getElementById("homeCalPeople");
    if (!root) return;
    const owners = cachedSchedule?.owners?.length ? cachedSchedule.owners : SCHEDULE_OWNERS;
    root.innerHTML = owners
      .map(
        (owner) =>
          `<button type="button" class="home-cal-people__btn${owner.id === scheduleOwner ? " is-active" : ""}" data-owner="${owner.id}" role="tab" aria-selected="${owner.id === scheduleOwner}">${owner.label}</button>`
      )
      .join("");
    root.querySelectorAll("[data-owner]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const next = btn.dataset.owner;
        if (!next || next === scheduleOwner || scheduleSaving) return;
        scheduleOwner = next;
        renderPeopleTabs();
        await loadTeamSchedule({ silent: true });
        renderMonthCalendar(cachedMatches, cachedScoutCalendar?.by_date || {});
      });
    });
  }

  async function loadTeamSchedule({ silent = false } = {}) {
    try {
      const params = new URLSearchParams({ owner: scheduleOwner });
      cachedSchedule = await fetchJson(`/api/schedule?${params}`);
      if (cachedSchedule?.owner) scheduleOwner = cachedSchedule.owner;
      return cachedSchedule;
    } catch (err) {
      if (!silent) console.warn("Schedule:", err.message);
      if (!cachedSchedule) {
        cachedSchedule = { days: {}, owners: SCHEDULE_OWNERS, owner: scheduleOwner };
      }
      return cachedSchedule;
    }
  }

  async function updateScheduleDay(dateKey, body) {
    if (!dateKey || scheduleSaving) return null;
    scheduleSaving = true;
    try {
      const params = new URLSearchParams({ owner: scheduleOwner });
      const result = await fetchJson(`/api/schedule/day/${dateKey}?${params}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (!cachedSchedule) cachedSchedule = { days: {}, owner: scheduleOwner };
      if (result.days) cachedSchedule.days = result.days;
      return result;
    } finally {
      scheduleSaving = false;
    }
  }

  function escapeAttr(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatHomeReport(hhmm) {
    if (!hhmm) return "9am";
    const [h, m] = String(hhmm).split(":").map(Number);
    const suffix = h >= 12 ? "pm" : "am";
    const hour12 = ((h + 11) % 12) + 1;
    return m ? `${hour12}:${String(m).padStart(2, "0")}${suffix}` : `${hour12}${suffix}`;
  }

  function formatKickoffShort(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const h = d.getHours();
    const m = d.getMinutes();
    const suffix = h >= 12 ? "pm" : "am";
    const hour12 = ((h + 11) % 12) + 1;
    return m ? `${hour12}:${String(m).padStart(2, "0")}${suffix}` : `${hour12}${suffix}`;
  }

  function homeCalBadge(src, alt) {
    if (!src) return "";
    return `<img class="home-cal__badge" src="${escapeAttr(src)}" alt="${escapeAttr(alt || "")}" loading="lazy" width="28" height="28" onerror="this.style.display='none'" />`;
  }

  function homeCalFixtureChip(row) {
    const isHome = Boolean(row.isHome);
    const oppName =
      (typeof row.opponent === "string" ? row.opponent : row.opponent?.name) ||
      (isHome ? row.away : row.home) ||
      "TBC";
    const ha = isHome ? "H" : "A";
    const oppBadge =
      row.opponent_badge ||
      (isHome ? row.away_badge : row.home_badge) ||
      "";
    const played = row.status === "completed" || Boolean(row.outcome);
    const score = played ? row.scoreLabel || row.score || "" : "";
    const ko = formatKickoffShort(row.kickoff_utc || row.scheduledDate);
    const timeLine = score || ko;
    const title = `${isHome ? "Home" : "Away"} vs ${oppName}${ko ? ` · ${ko}` : ""}${
      score ? ` · ${score}` : ""
    }${row.competition ? ` · ${row.competition}` : ""}`;
    return `<span class="home-cal__fixture home-cal__fixture--${isHome ? "home" : "away"}" title="${escapeAttr(title)}">
      ${homeCalBadge(oppBadge, oppName)}
      <span class="home-cal__fixture-meta">
        <strong>${escapeAttr(ha)} ${escapeAttr(oppName)}</strong>
        ${timeLine ? `<span>${escapeAttr(timeLine)}</span>` : ""}
      </span>
    </span>`;
  }

  function renderMonthCalendar(matches, scoutByDate) {
    if (!scheduleMonthKey) scheduleMonthKey = monthKeyFromDate(todayKey());
    setText("homeMonthCalLabel", formatMonthLabel(scheduleMonthKey));
    renderPeopleTabs();

    const calendarRows =
      cachedFixtures?.calendar?.length
        ? cachedFixtures.calendar
        : cachedFixtures?.fixtures?.length
          ? cachedFixtures.fixtures
          : matches;
    const pvByDate = pvMatchesByDate(calendarRows);
    const dayState = cachedSchedule?.days || {};
    const [year, month] = scheduleMonthKey.split("-").map(Number);
    const firstDay = new Date(year, month - 1, 1);
    const startOffset = (firstDay.getDay() + 6) % 7;
    const daysInMonth = new Date(year, month, 0).getDate();
    const today = todayKey();
    const showScoutDots = scheduleOwner === "team";

    const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
      .map((d) => `<div class="home-cal__weekday">${d}</div>`)
      .join("");

    const cells = [];
    for (let i = 0; i < startOffset; i += 1) {
      cells.push(`<div class="home-cal__day home-cal__day--muted"></div>`);
    }

    for (let day = 1; day <= daysInMonth; day += 1) {
      const dateKey = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const entry = dayState[dateKey];
      const dayType = entry?.type || "";
      const recruitmentIn = Boolean(entry?.recruitment_in);
      const pvEvents = pvByDate[dateKey] || [];
      const scoutEvents = showScoutDots ? scoutByDate[dateKey] || [] : [];
      const match = pvEvents[0] || null;

      const classes = ["home-cal__day"];
      if (dateKey === today) classes.push("home-cal__day--today");
      if (match) {
        classes.push("home-cal__day--match");
        classes.push(match.isHome ? "home-cal__day--home" : "home-cal__day--away");
      } else if (dayType === "training") {
        classes.push("home-cal__day--training");
      } else if (dayType === "regen") {
        classes.push("home-cal__day--regen");
      } else if (dayType === "preseason") {
        classes.push("home-cal__day--preseason");
      }

      let body = "";
      if (match) {
        body = homeCalFixtureChip(match);
      } else if (dayType === "training") {
        body = `<div class="home-cal__session"><strong>IN</strong><span>${escapeAttr(formatHomeReport(entry?.report_time || "09:00"))}</span></div>`;
      } else if (dayType === "regen") {
        body = `<div class="home-cal__session"><strong>REGEN</strong></div>`;
      } else if (dayType === "preseason") {
        body = `<div class="home-cal__session"><strong>PRE-SEASON</strong></div>`;
      }

      const scoutHtml = scoutEvents
        .slice(0, 2)
        .map((row) => {
          const live = String(row.watch_type || "").toUpperCase() === "LIVE";
          return `<span class="home-cal__dot ${live ? "home-cal__dot--live" : "home-cal__dot--video"}" title="${escapeAttr(scoutFixtureLabel(row))}"></span>`;
        })
        .join("");

      const titleParts = [];
      if (match) titleParts.push(match.isHome ? "Home fixture" : "Away fixture");
      if (dayType === "training") titleParts.push(`IN · report ${entry?.report_time || "09:00"}`);
      if (dayType === "regen") titleParts.push("Regen");
      if (dayType === "preseason") titleParts.push("Pre-season game");
      if (recruitmentIn) titleParts.push("Recruitment in");
      titleParts.push("Click: IN → Regen → Pre-season → blank · Shift-click: R");

      cells.push(`<button type="button" class="${classes.join(" ")}" data-date="${dateKey}" title="${escapeAttr(titleParts.join(" · "))}">
        ${recruitmentIn ? '<span class="home-cal__r" aria-label="Recruitment in">R</span>' : ""}
        <div class="home-cal__num">${day}</div>
        <div class="home-cal__dots">${body}${scoutHtml}</div>
      </button>`);
    }

    const ownerLabel =
      (cachedSchedule?.owners || SCHEDULE_OWNERS).find((row) => row.id === scheduleOwner)?.label ||
      "Team";

    setHtml(
      "homeMonthCal",
      `<div class="home-cal">${weekdays}${cells.join("")}</div>
      <div class="home-cal__legend">
        <span><i style="background:#2fd46a"></i> IN</span>
        <span><i style="background:#ff4d6d"></i> Regen</span>
        <span><i style="background:#38bdf8"></i> Pre-season</span>
        <span><i class="home-cal__legend-r">R</i> Recruitment in</span>
        <span><i style="background:#c9a227"></i> Home</span>
        <span><i style="background:#1a4fd6"></i> Away</span>
        ${showScoutDots ? `<span><i style="background:var(--green)"></i> Scout LIVE</span>
        <span><i style="background:var(--accent)"></i> Scout VIDEO</span>` : ""}
      </div>
      <p class="home-cal__hint">${ownerLabel} — click: <strong>IN</strong> → <strong>Regen</strong> → <strong>Pre-season</strong> (blue) → blank. Shift-click for <strong>R</strong>. Open <a href="/schedule">Full schedule</a> for the big board.</p>`
    );

    const root = document.getElementById("homeMonthCal");
    root?.querySelectorAll(".home-cal__day[data-date]").forEach((btn) => {
      btn.addEventListener("click", async (event) => {
        const dateKey = btn.dataset.date;
        if (!dateKey || scheduleSaving) return;
        event.preventDefault();
        if (event.shiftKey) {
          await updateScheduleDay(dateKey, { toggle_recruitment: true });
        } else if (event.altKey) {
          await updateScheduleDay(dateKey, { toggle_preseason: true });
        } else {
          await updateScheduleDay(dateKey, { cycle: true });
        }
        renderMonthCalendar(cachedMatches, cachedScoutCalendar?.by_date || {});
      });
      btn.addEventListener("contextmenu", async (event) => {
        const dateKey = btn.dataset.date;
        if (!dateKey || scheduleSaving) return;
        event.preventDefault();
        await updateScheduleDay(dateKey, { toggle_recruitment: true });
        renderMonthCalendar(cachedMatches, cachedScoutCalendar?.by_date || {});
      });
    });
  }

  function renderPvUpcoming(fixtures) {
    const upcoming = fixtures?.upcoming || (cachedMatches || []).filter((m) => !m.outcome);
    const rows = (upcoming || []).slice(0, 6);
    if (!rows.length) {
      setHtml("homePvUpcoming", `<p class="home-empty">No upcoming Port Vale fixtures on FotMob yet.</p>`);
      return;
    }
    const html = rows
      .map((match) => {
        const day = matchDateKey(match);
        const days = daysUntil(day);
        const when =
          days === 0 ? "Today" : days === 1 ? "Tomorrow" : days != null ? `In ${days} days` : formatShortDate(day);
        const comp = match.competition ? ` · ${match.competition}` : "";
        return `<article class="home-schedule-item">
          <span class="home-schedule-item__time">${formatShortDate(day)}</span>
          <div>
            <p class="home-schedule-item__title">${match.isHome ? "vs" : "@"} ${match.opponent?.name || "TBC"}</p>
            <p class="home-schedule-item__meta">${formatTime(match.scheduledDate || match.kickoff_utc)} · ${match.isHome ? "Home" : "Away"} · ${when}${comp}</p>
          </div>
        </article>`;
      })
      .join("");
    setHtml("homePvUpcoming", `<div class="home-schedule-list">${html}</div>`);
  }

  function renderPvPlayed(fixtures) {
    const played = (fixtures?.played || []).slice(-6).reverse();
    if (!played.length) {
      setHtml("homePvPlayed", `<p class="home-empty">No recent Port Vale results on FotMob yet.</p>`);
      return;
    }
    const html = played
      .map((match) => {
        const day = matchDateKey(match);
        const letter =
          match.outcome === "win" ? "W" : match.outcome === "draw" ? "D" : match.outcome === "loss" ? "L" : "·";
        const cls =
          match.outcome === "win"
            ? "is-win"
            : match.outcome === "draw"
              ? "is-draw"
              : match.outcome === "loss"
                ? "is-loss"
                : "";
        const comp = match.competition ? ` · ${match.competition}` : "";
        const score = match.scoreLabel || match.score;
        return `<article class="home-schedule-item">
          <span class="home-schedule-item__time">${formatShortDate(day)}</span>
          <div>
            <p class="home-schedule-item__title">
              <span class="home-form__pill ${cls}" style="margin-right:0.35rem">${letter}</span>
              ${match.isHome ? "vs" : "@"} ${match.opponent?.name || "TBC"}${score ? ` · ${score}` : ""}
            </p>
            <p class="home-schedule-item__meta">${match.isHome ? "Home" : "Away"}${comp}</p>
          </div>
        </article>`;
      })
      .join("");
    setHtml("homePvPlayed", `<div class="home-schedule-list">${html}</div>`);
  }

  function renderScoutUpcoming(calendar) {
    const fixtures = calendar?.fixtures || [];
    if (!fixtures.length) {
      setHtml(
        "homeScoutUpcoming",
        `<p class="home-empty">No scout assignments yet. Add them in Fixture Planner.</p>`
      );
      return;
    }
    const html = fixtures
      .slice(0, 6)
      .map(
        (row) => `<article class="home-schedule-item">
          <span class="home-schedule-item__time">${formatShortDate(row.date)}</span>
          <div>
            <p class="home-schedule-item__title">${scoutFixtureLabel(row)}</p>
            <p class="home-schedule-item__meta">${formatTime(row.kickoff_utc)} · ${row.league || "League TBC"} · ${staffFirstName(row.staff)}</p>
            <span class="home-schedule-item__tag ${String(row.watch_type).toUpperCase() === "LIVE" ? "home-schedule-item__tag--live" : "home-schedule-item__tag--video"}">${row.watch_type}</span>
          </div>
        </article>`
      )
      .join("");
    setHtml("homeScoutUpcoming", `<div class="home-schedule-list">${html}</div>`);
  }

  function bindCalendarNav() {
    const prev = document.getElementById("homeCalPrev");
    const next = document.getElementById("homeCalNext");
    const todayBtn = document.getElementById("homeCalToday");
    if (prev && !prev.dataset.bound) {
      prev.dataset.bound = "1";
      prev.addEventListener("click", () => {
        scheduleMonthKey = shiftMonth(scheduleMonthKey || monthKeyFromDate(todayKey()), -1);
        renderMonthCalendar(cachedMatches, cachedScoutCalendar?.by_date || {});
      });
    }
    if (next && !next.dataset.bound) {
      next.dataset.bound = "1";
      next.addEventListener("click", () => {
        scheduleMonthKey = shiftMonth(scheduleMonthKey || monthKeyFromDate(todayKey()), 1);
        renderMonthCalendar(cachedMatches, cachedScoutCalendar?.by_date || {});
      });
    }
    if (todayBtn && !todayBtn.dataset.bound) {
      todayBtn.dataset.bound = "1";
      todayBtn.addEventListener("click", () => {
        scheduleMonthKey = monthKeyFromDate(todayKey());
        renderMonthCalendar(cachedMatches, cachedScoutCalendar?.by_date || {});
      });
    }
  }

  async function loadScoutCalendar() {
    let season = "26/27";
    try {
      const meta = await fetchJson("/api/fixture-planner/meta");
      season = meta.season || season;
    } catch (_) {
      /* default season */
    }
    const params = new URLSearchParams({
      season,
      watch_type: "ALL",
      include_past: "false",
    });
    cachedScoutCalendar = await fetchJson(`/api/fixture-planner/scouts-calendar?${params}`);
    return cachedScoutCalendar;
  }

  function renderHomeTab() {
    bindCalendarNav();
    renderHomeOverview(
      cachedStrategyBundle?.pv,
      cachedStrategyBundle?.averages,
      cachedStrategyBundle ? `${COMPETITION} · ${cachedStrategyBundle.season}` : COMPETITION,
      cachedStrategySnapshot,
      cachedMatches
    );
    const scoutByDate = cachedScoutCalendar?.by_date || {};
    renderTodaySchedule(cachedMatches, scoutByDate);
    renderMonthCalendar(cachedMatches, scoutByDate);
    renderPvUpcoming(cachedFixtures);
    renderPvPlayed(cachedFixtures);
    renderScoutUpcoming(cachedScoutCalendar);
  }

  async function loadFotmobFixtures() {
    const data = await fetchJson("/api/home/fixtures");
    cachedFixtures = data;
    cachedMatches = data.matches || [];
    renderForm(cachedMatches);
    if (data.next) {
      const when = data.next.scheduledDate
        ? new Date(data.next.scheduledDate).toLocaleString(undefined, {
            weekday: "short",
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })
        : "TBC";
      setHtml(
        "homeNext",
        `<div class="home-next">
          <p class="home-next__opp">${data.next.opponent?.name || "TBC"}</p>
          <p class="home-next__meta">${data.next.isHome ? "Home" : "Away"} · ${when}${data.next.competition ? ` · ${data.next.competition}` : ""}</p>
        </div>`
      );
    }
    return data;
  }

  function setKpi(id, value, sub) {
    const card = document.getElementById(id);
    if (!card) return;
    const valueEl = card.querySelector(".home-kpi__value");
    const subEl = card.querySelector(".home-kpi__sub");
    if (valueEl) valueEl.textContent = value;
    if (subEl) subEl.textContent = sub;
  }

  function renderKpis(pv, averages, seasonLabel) {
    const pos = pv?.position ?? "—";
    const pts = pv?.points ?? "—";
    const played = pv?.played ?? "—";
    setText("homeSeasonLabel", seasonLabel || COMPETITION);
    setKpi("homeKpiPos", `#${pos}`, `${pts} pts · ${played} played`);
    setKpi("homeKpiPpg", fmt(pv?.ppg, 2), `League avg ${fmt(averages?.ppg, 2)}`);
    setKpi(
      "homeKpiXgd",
      (pv?.xg_difference >= 0 ? "+" : "") + fmt(pv?.xg_difference, 1),
      `League avg ${fmt(averages?.xg_difference, 1)}`
    );
    setKpi(
      "homeKpiCs",
      `${fmt(pv?.clean_sheet_pct, 0)}%`,
      `League avg ${fmt(averages?.clean_sheet_pct, 0)}%`
    );
  }

  function renderTable(standings) {
    if (!standings?.length) {
      widgetError("homeTableBody", "No standings yet.");
      return;
    }
    const focusIdx = standings.findIndex((r) => r.focus);
    let rows = standings;
    if (standings.length > 12 && focusIdx >= 0) {
      const start = Math.max(0, focusIdx - 4);
      rows = standings.slice(start, Math.min(standings.length, start + 10));
    } else if (standings.length > 12) {
      rows = standings.slice(0, 10);
    }
    const html = rows
      .map((row) => {
        const cls = row.focus ? ' class="is-focus"' : "";
        return `<tr${cls}>
          <td class="col-pos">${row.position}</td>
          <td class="col-club">${row.club}</td>
          <td class="col-num">${row.played}</td>
          <td class="col-num">${row.goal_difference > 0 ? "+" : ""}${row.goal_difference}</td>
          <td class="col-pts">${row.points}</td>
        </tr>`;
      })
      .join("");
    setHtml(
      "homeTableBody",
      `<table class="home-table">
        <thead><tr>
          <th class="col-pos">#</th>
          <th class="col-club">Club</th>
          <th class="col-num">P</th>
          <th class="col-num">GD</th>
          <th class="col-pts">Pts</th>
        </tr></thead>
        <tbody>${html}</tbody>
      </table>`
    );
    renderLeagueFormTable(standings);
    renderPerfRankings(standings);
  }

  function formPillsHtml(form) {
    return (form || [])
      .map((letter) => {
        const cls =
          letter === "W" ? "is-win" : letter === "D" ? "is-draw" : "is-loss";
        return `<span class="home-form__pill ${cls}">${letter}</span>`;
      })
      .join("");
  }

  function renderLeagueFormTable(standings) {
    if (!standings?.length) {
      widgetError("homeLeagueForm", "No league form yet.");
      return;
    }
    const ranked = [...standings].sort((a, b) => {
      const pts = (Number(b.form_pts) || 0) - (Number(a.form_pts) || 0);
      if (pts) return pts;
      return (Number(a.position) || 99) - (Number(b.position) || 99);
    });
    const html = ranked
      .map((row, index) => {
        const cls = row.focus ? ' class="is-focus"' : "";
        const form = row.form || String(row.form_string || "").split("").filter(Boolean);
        return `<tr${cls}>
          <td class="col-pos">${index + 1}</td>
          <td class="col-club">${row.club}</td>
          <td class="col-form"><span class="home-form-inline">${formPillsHtml(form)}</span></td>
          <td class="col-val">${row.form_pts ?? "—"}</td>
          <td class="col-rank">#${row.position}</td>
        </tr>`;
      })
      .join("");
    setHtml(
      "homeLeagueForm",
      `<table class="home-table">
        <thead><tr>
          <th class="col-pos">#</th>
          <th class="col-club">Club</th>
          <th class="col-form">Last 5</th>
          <th class="col-val">Pts</th>
          <th class="col-rank">Table</th>
        </tr></thead>
        <tbody>${html}</tbody>
      </table>`
    );
  }

  function renderPerfRankings(standings) {
    if (!standings?.length) {
      widgetError("homePerfRankings", "No ranking data yet.");
      return;
    }
    const metrics = [
      { key: "ppg", label: "Points / game", digits: 2, higher: true },
      { key: "xg_difference", label: "xG difference", digits: 1, higher: true, signed: true },
      { key: "sot_pct", label: "Shots on target %", digits: 0, higher: true, suffix: "%" },
      { key: "clean_sheet_pct", label: "Clean sheet %", digits: 0, higher: true, suffix: "%" },
      { key: "goals_for", label: "Goals for", digits: 0, higher: true },
      { key: "goals_against", label: "Goals against", digits: 0, higher: false },
      { key: "xp_vs_actual", label: "Pts vs xPts", digits: 1, higher: true, signed: true },
      { key: "xppg", label: "Expected PPG", digits: 2, higher: true },
    ];

    const blocks = metrics
      .map((metric) => {
        const scored = standings
          .map((row) => ({
            club: row.club,
            focus: !!row.focus,
            value: Number(row[metric.key]),
            squad_id: row.squad_id,
          }))
          .filter((row) => Number.isFinite(row.value));
        if (!scored.length) return "";
        scored.sort((a, b) =>
          metric.higher ? b.value - a.value : a.value - b.value
        );
        const focusIdx = scored.findIndex((row) => row.focus);
        const focusRank = focusIdx >= 0 ? focusIdx + 1 : null;
        const windowRows = rankWindow(
          scored.map((row, index) => ({
            ...row,
            rank: index + 1,
          })),
          null,
          7
        );
        // rankWindow uses focus flag — ensure it's set
        const body = windowRows
          .map((row) => {
            const cls = row.focus ? ' class="is-focus"' : "";
            let valueLabel = fmt(row.value, metric.digits) + (metric.suffix || "");
            if (metric.signed && row.value > 0) valueLabel = `+${valueLabel}`;
            return `<tr${cls}>
              <td class="col-pos">${row.rank}</td>
              <td class="col-club">${row.club}</td>
              <td class="col-val">${valueLabel}</td>
            </tr>`;
          })
          .join("");
        const rankLabel = focusRank != null ? ordinal(focusRank) : "—";
        return `<div class="home-rank-block">
          <p class="home-rank-block__title">${metric.label} · Vale ${rankLabel}</p>
          <table class="home-table">
            <thead><tr><th class="col-pos">#</th><th class="col-club">Club</th><th class="col-val">Value</th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>`;
      })
      .filter(Boolean);

    if (!blocks.length) {
      widgetError("homePerfRankings", "No ranking data yet.");
      return;
    }
    setText("homePerfRankNote", `${standings.length} clubs`);
    setHtml("homePerfRankings", `<div class="home-rank-grid">${blocks.join("")}</div>`);
  }

  function ordinal(n) {
    const num = Number(n);
    if (!Number.isFinite(num)) return "—";
    const mod100 = num % 100;
    if (mod100 >= 10 && mod100 <= 20) return `${num}th`;
    const suffix = { 1: "st", 2: "nd", 3: "rd" }[num % 10] || "th";
    return `${num}${suffix}`;
  }

  function renderPerfPhases(data) {
    const phases = data?.phases || {};
    if (phases.deferred) {
      setHtml("homePerfPhases", `<p class="home-empty">Loading phase scoring…</p>`);
      setHtml("homePerfPhasesConceded", `<p class="home-empty">Loading phase defending…</p>`);
      return;
    }
    if (phases.error) {
      widgetError("homePerfPhases", phases.error);
      widgetError("homePerfPhasesConceded", "Phase defending unavailable.");
      return;
    }
    renderPhaseBars("homePerfPhases", "homePerfPhaseNote", phases.scored, "scored");
    renderPhaseBars(
      "homePerfPhasesConceded",
      "homePerfPhaseConcededNote",
      phases.conceded,
      "conceded"
    );
    if (phases.matches) {
      setText(
        "homePerfPhaseNote",
        `${phases.matches} matches · GF ${phases.goals_for ?? "—"} · Poss / Trans / SP`
      );
      setText(
        "homePerfPhaseConcededNote",
        `${phases.matches} matches · GA ${phases.goals_against ?? "—"} · vs play-off BM`
      );
    }
  }

  function renderVsLeague(pv, averages) {
    if (!pv || !averages) {
      widgetError("homeVsLeague", "No comparison data yet.");
      return;
    }
    const metrics = [
      { key: "ppg", label: "Points / game", digits: 2 },
      { key: "sot_pct", label: "Shots on target %", digits: 0, suffix: "%" },
      { key: "clean_sheet_pct", label: "Clean sheet %", digits: 0, suffix: "%" },
      { key: "xg_difference", label: "xG difference", digits: 1, signed: true },
      { key: "xp_vs_actual", label: "Pts vs xPts", digits: 1, signed: true },
      { key: "goals_for", label: "Goals for", digits: 0 },
    ];
    const html = metrics
      .map((m) => {
        const us = Number(pv[m.key]);
        const them = Number(averages[m.key]);
        const better = m.key === "goals_against" ? us <= them : us >= them;
        const usLabel = (m.signed && us > 0 ? "+" : "") + fmt(us, m.digits) + (m.suffix || "");
        const themLabel =
          (m.signed && them > 0 ? "+" : "") + fmt(them, m.digits) + (m.suffix || "");
        return `<div class="home-vs__row">
          <span class="home-vs__label">${m.label}</span>
          <span class="home-vs__us ${better ? "is-up" : "is-down"}">${usLabel}</span>
          <span class="home-vs__vs">vs</span>
          <span class="home-vs__league">${themLabel}</span>
        </div>`;
      })
      .join("");
    setHtml("homeVsLeague", html);
  }

  function renderForm(matches) {
    const played = (matches || []).filter((m) => m.outcome).slice(-6).reverse();
    if (!played.length) {
      widgetError("homeForm", "No completed matches yet.");
      setHtml("homeNext", `<p class="home-empty">No upcoming fixture found.</p>`);
      return;
    }
    const pills = played
      .map((m) => {
        const letter = m.outcome === "win" ? "W" : m.outcome === "draw" ? "D" : "L";
        const cls =
          m.outcome === "win" ? "is-win" : m.outcome === "draw" ? "is-draw" : "is-loss";
        const tip = `${m.isHome ? "H" : "A"} vs ${m.opponent?.name || "?"} · ${m.scoreLabel || ""}`;
        return `<span class="home-form__pill ${cls}" title="${tip}">${letter}</span>`;
      })
      .join("");
    setHtml("homeForm", `<div class="home-form__row">${pills}</div>`);

    const upcoming = (matches || []).find((m) => !m.outcome);
    if (!upcoming) {
      setHtml("homeNext", `<p class="home-empty">Season complete — no next fixture.</p>`);
      return;
    }
    const when = upcoming.scheduledDate
      ? new Date(upcoming.scheduledDate).toLocaleString(undefined, {
          weekday: "short",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "TBC";
    setHtml(
      "homeNext",
      `<div class="home-next">
        <p class="home-next__opp">${upcoming.opponent?.name || "TBC"}</p>
        <p class="home-next__meta">${upcoming.isHome ? "Home" : "Away"} · ${when}</p>
      </div>`
    );
  }

  async function loadAvailability() {
    try {
      const board = await fetchJson("/api/availability/board");
      const players = board.players || board.roster || [];
      if (!players.length) {
        setHtml("homeAvail", `<p class="home-empty">Open Squad Availability to load the board.</p>`);
        return;
      }
      let inj = 0;
      let unavail = 0;
      let avail = 0;
      players.forEach((p) => {
        const status = String(
          p.matchStatus?.status || p.injury?.status || p.status || "AVAIL"
        ).toUpperCase();
        if (status === "INJ") inj += 1;
        else if (status === "UN" || status === "LOAN" || status === "SUS") unavail += 1;
        else avail += 1;
      });
      setHtml(
        "homeAvail",
        `<div class="home-avail">
          <div><strong>${avail}</strong><span>Available</span></div>
          <div><strong>${inj}</strong><span>Injured</span></div>
          <div><strong>${unavail}</strong><span>Out / loan</span></div>
        </div>`
      );
    } catch (_) {
      setHtml("homeAvail", `<p class="home-empty">Availability not loaded.</p>`);
    }
  }

  function renderRecruitmentActivity(events) {
    const recruit = (events || []).filter((e) =>
      ["watched", "report", "assignment"].includes(e.kind)
    );
    if (!recruit.length) {
      setHtml(
        "homeRecruitFeed",
        `<p class="home-empty">No recent watches, reports, or assignments yet. Activity appears as scouts use Fixture Planner / Played Fixtures.</p>`
      );
      return;
    }
    const html = recruit
      .slice(0, 8)
      .map(
        (e) => `<a class="home-feed__item" href="${e.href || "#"}">
          <span class="home-feed__icon">${e.icon || "•"}</span>
          <span class="home-feed__body">
            <strong>${e.title}</strong>
            <span>${e.detail || ""}</span>
          </span>
          <span class="home-feed__time">${relativeTime(e.at)}</span>
        </a>`
      )
      .join("");
    setHtml("homeRecruitFeed", html);
  }

  function renderActivity(events) {
    if (!events?.length) {
      setHtml(
        "homeActivity",
        `<p class="home-empty">No team activity yet — assignments, watches, and reports will show up here live.</p>`
      );
      return;
    }
    const html = events
      .map(
        (e) => `<a class="home-feed__item" href="${e.href || "#"}">
          <span class="home-feed__icon">${e.icon || "•"}</span>
          <span class="home-feed__body">
            <strong>${e.title}</strong>
            <span>${e.detail || ""}${e.meta ? ` · ${e.meta}` : ""}</span>
          </span>
          <span class="home-feed__time">${relativeTime(e.at)}</span>
        </a>`
      )
      .join("");
    setHtml("homeActivity", html);
  }

  function renderChangelog(entries) {
    if (!entries?.length) {
      setHtml("homeChangelog", `<p class="home-empty">No release notes yet — add entries in standalone/app-changelog.json when you promote Staging → Live.</p>`);
      return;
    }
    const html = entries
      .map(
        (e) => `<div class="home-change__item">
          <div class="home-change__top">
            <span class="home-change__tag">${e.tag || "Update"}</span>
            <span class="home-change__date">${e.date || ""}</span>
          </div>
          <strong>${e.title}</strong>
          <p>${e.detail || ""}</p>
        </div>`
      )
      .join("");
    setHtml("homeChangelog", html);
  }

  async function loadBrokeJoke() {
    const el = document.getElementById("hubBrokeJoke");
    if (!el) return;
    try {
      const data = await fetchJson("/api/home/days-since-broke");
      const days = Number(data.days);
      if (!Number.isFinite(days)) return;
      const unit = days === 1 ? "day" : "days";
      el.innerHTML = `<strong>${days}</strong> ${unit} since we last broke`;
      el.title = data.last_broke
        ? `Last broke ${data.last_broke}. Edit standalone/hub-uptime-joke.json to reset.`
        : el.title;
    } catch (_) {
      /* keep placeholder */
    }
  }

  function ensureHubNoticeCss() {
    if (document.querySelector('link[data-hub-notice-css]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/hub-feedback.css?v=1";
    link.setAttribute("data-hub-notice-css", "1");
    document.head.appendChild(link);
  }

  function showHubNotice(notice) {
    if (!notice?.id || !notice?.message) return;
    const storageKey = `hub-notice-seen:${notice.id}`;
    try {
      if (localStorage.getItem(storageKey)) return;
    } catch (_) {
      /* private mode — still show once per session */
    }

    ensureHubNoticeCss();

    const escapeHtml = (value) =>
      String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");

    let modal = document.getElementById("hubNoticeModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.className = "hub-feedback-modal";
      modal.id = "hubNoticeModal";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      modal.setAttribute("aria-labelledby", "hubNoticeTitle");
      document.body.appendChild(modal);
    }

    const title = notice.title || "Quick note from analysis";
    const button = notice.button || "Got it";
    modal.innerHTML = `
      <div class="hub-feedback-modal__panel">
        <h2 class="hub-feedback-modal__title" id="hubNoticeTitle">${escapeHtml(title)}</h2>
        <p class="hub-feedback-modal__hint" style="white-space:pre-line">${escapeHtml(notice.message)}</p>
        <div class="hub-feedback-modal__actions">
          <button type="button" class="hub-feedback-modal__btn hub-feedback-modal__btn--primary" id="hubNoticeDismissBtn">${escapeHtml(button)}</button>
        </div>
      </div>
    `;
    modal.hidden = false;

    const dismiss = () => {
      modal.hidden = true;
      try {
        localStorage.setItem(storageKey, "1");
      } catch (_) {
        /* ignore */
      }
    };

    modal.querySelector("#hubNoticeDismissBtn")?.addEventListener("click", dismiss);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) dismiss();
    });
    document.addEventListener(
      "keydown",
      function onEsc(event) {
        if (event.key !== "Escape" || modal.hidden) return;
        dismiss();
        document.removeEventListener("keydown", onEsc);
      },
      { once: true },
    );
  }

  async function loadHubNotice() {
    try {
      const data = await fetchJson("/standalone/hub-uptime-joke.json");
      showHubNotice(data.notice);
    } catch (_) {
      /* optional */
    }
  }

  function ageBandClass(label) {
    if (label === "U21") return "is-age-u21";
    if (label === "21–25") return "is-age-2125";
    if (label === "26–29") return "is-age-2629";
    return "is-age-30";
  }

  function phaseFillClass(key) {
    if (key === "possession") return "is-poss";
    if (key === "transition") return "is-trans";
    return "is-set";
  }

  function metricByKey(metrics, key) {
    return (metrics || []).find((row) => row.key === key) || null;
  }

  function formatMetricValue(row, value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const digits = row?.digits ?? 1;
    const suffix = row?.suffix || "";
    return `${fmt(value, digits)}${suffix}`;
  }

  function deltaClass(row, delta) {
    if (delta == null || Number.isNaN(Number(delta))) return "";
    const higherBetter = row?.higher_is_better !== false;
    const good = higherBetter ? delta >= 0 : delta <= 0;
    return good ? "is-up" : "is-down";
  }

  function rankWindow(standings, focusId, windowSize = 7) {
    const rows = standings || [];
    if (rows.length <= windowSize + 2) return rows;
    const focusIdx = rows.findIndex((r) => r.focus || (focusId != null && r.squad_id === focusId));
    if (focusIdx < 0) return rows.slice(0, windowSize);
    const half = Math.floor(windowSize / 2);
    const start = Math.max(0, Math.min(rows.length - windowSize, focusIdx - half));
    return rows.slice(start, start + windowSize);
  }

  const COMPARE_COLGROUP = `<colgroup>
    <col class="compare-col-metric">
    <col class="compare-col-val">
    <col class="compare-col-val">
    <col class="compare-col-delta">
    <col class="compare-col-rank">
  </colgroup>`;

  function compareTableHtml(metricHeader, rowsHtml) {
    return `<table class="home-table home-compare-table">
      ${COMPARE_COLGROUP}
      <thead><tr>
        <th class="col-metric">${metricHeader}</th>
        <th class="col-val">Us</th>
        <th class="col-val">League</th>
        <th class="col-delta">Δ</th>
        <th class="col-rank">Rank</th>
      </tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;
  }

  function renderAgeBands(bands, leagueBands) {
    if (!bands?.length) {
      widgetError("homeAgeBands", "No minutes-by-age data yet.");
      return;
    }
    const maxShare = Math.max(...bands.map((b) => Number(b.share_pct) || 0), 1);
    const bars = bands
      .map((b) => {
        const share = Number(b.share_pct) || 0;
        const width = Math.max(4, Math.round((share / maxShare) * 100));
        return `<div class="home-bar">
          <span class="home-bar__label">${b.label}</span>
          <div class="home-bar__track"><div class="home-bar__fill ${ageBandClass(b.label)}" style="width:${width}%"></div></div>
        </div>`;
      })
      .join("");

    const tableRows = (leagueBands || [])
      .map((row) => {
        const cls = deltaClass(row, row.delta_pp);
        return `<tr>
          <td class="col-metric">${row.label}</td>
          <td class="col-val">${fmt(row.us_pct, 1)}%</td>
          <td class="col-val">${fmt(row.league_avg_pct, 1)}%</td>
          <td class="col-delta ${cls}">${signed(row.delta_pp, 1)} pp</td>
          <td class="col-rank">${row.rank_label} / ${row.squads}</td>
        </tr>`;
      })
      .join("");

    const table = tableRows
      ? `<div class="home-age-bands__table">${compareTableHtml("Band", tableRows)}</div>`
      : "";

    setHtml("homeAgeBands", `<div class="home-bars">${bars}</div>${table}`);
  }

  function renderRecruitVsLeague(metrics, leagueBands, squads) {
    if (!metrics?.length) {
      widgetError("homeRecruitVsLeague", "League comparison not ready yet.");
      return;
    }
    const preferred = [
      "avg_age",
      "minutes_weighted_age",
      "u25_minutes_pct",
      "u23_minutes_pct",
      "u21_minutes_pct",
      "u25_regulars_500",
      "total_minutes",
    ];
    const byKey = Object.fromEntries(metrics.map((row) => [row.key, row]));
    const ordered = preferred.map((key) => byKey[key]).filter(Boolean);
    const rows = ordered
      .map((row) => {
        const cls = deltaClass(row, row.delta);
        const deltaLabel =
          row.suffix === "%"
            ? `${signed(row.delta, row.digits)} pp`
            : signed(row.delta, row.digits);
        return `<tr>
          <td class="col-metric">${row.label}</td>
          <td class="col-val">${formatMetricValue(row, row.us)}</td>
          <td class="col-val">${formatMetricValue(row, row.league_avg)}</td>
          <td class="col-delta ${cls}">${deltaLabel}</td>
          <td class="col-rank">${row.rank_label} / ${row.squads}</td>
        </tr>`;
      })
      .join("");

    const bandRows = (leagueBands || [])
      .map((row) => {
        const cls = deltaClass(row, row.delta_pp);
        return `<tr>
          <td class="col-metric">${row.label} minutes share</td>
          <td class="col-val">${fmt(row.us_pct, 1)}%</td>
          <td class="col-val">${fmt(row.league_avg_pct, 1)}%</td>
          <td class="col-delta ${cls}">${signed(row.delta_pp, 1)} pp</td>
          <td class="col-rank">${row.rank_label} / ${row.squads}</td>
        </tr>`;
      })
      .join("");

    setText("homeRecruitLeagueNote", squads ? `${squads} clubs` : "Rank · avg");
    setHtml("homeRecruitVsLeague", compareTableHtml("Metric", `${rows}${bandRows}`));
  }

  function renderRecruitRankings(metrics, focusSquadId) {
    const keys = [
      "u25_minutes_pct",
      "u23_minutes_pct",
      "u21_minutes_pct",
      "avg_age",
      "minutes_weighted_age",
      "u25_regulars_500",
    ];
    const blocks = keys
      .map((key) => metricByKey(metrics, key))
      .filter(Boolean)
      .map((row) => {
        const windowRows = rankWindow(row.standings || [], focusSquadId, 7);
        const body = windowRows
          .map((club) => {
            const cls = club.focus ? ' class="is-focus"' : "";
            return `<tr${cls}>
              <td class="col-pos">${club.rank}</td>
              <td class="col-club">${club.club}</td>
              <td class="col-val">${formatMetricValue(row, club.value)}</td>
            </tr>`;
          })
          .join("");
        return `<div class="home-rank-block">
          <p class="home-rank-block__title">${row.label} · Vale ${row.rank_label}</p>
          <table class="home-table">
            <thead><tr><th class="col-pos">#</th><th class="col-club">Club</th><th class="col-val">Value</th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>`;
      });

    if (!blocks.length) {
      widgetError("homeRecruitRankings", "Club rankings not ready yet.");
      return;
    }
    setText("homeRecruitRankNote", "Young minutes + age");
    setHtml("homeRecruitRankings", `<div class="home-rank-grid">${blocks.join("")}</div>`);
  }

  function renderRecruitment(data) {
    if (data?.building) {
      setText("homeRecruitSeason", "Building league comparison…");
      ["homeAgeBands", "homeRecruitSnapshot", "homeRecruitVsLeague", "homeRecruitRankings"].forEach(
        (id) => setHtml(id, `<p class="home-empty">Building Port Vale vs league snapshot…</p>`)
      );
      setTimeout(() => {
        loadRecruitmentTab().catch(() => {});
      }, 4000);
      return;
    }
    if (data?.error) {
      widgetError("homeAgeBands", data.error);
      widgetError("homeRecruitSnapshot", data.error);
      widgetError("homeRecruitVsLeague", data.error);
      widgetError("homeRecruitRankings", data.error);
      return;
    }
    const seasonBits = [data.competition, data.season].filter(Boolean).join(" · ");
    setText("homeRecruitSeason", seasonBits || "Squad profile");
    const metrics = data.league_metrics || [];
    const ageRow = metricByKey(metrics, "avg_age");
    const u25Row = metricByKey(metrics, "u25_minutes_pct");
    const u21Row = metricByKey(metrics, "u21_minutes_pct");
    const weightedRow = metricByKey(metrics, "minutes_weighted_age");
    const regularsRow = metricByKey(metrics, "u25_regulars_500");

    setKpi(
      "recruitKpiAge",
      fmt(data.avg_age, 1),
      ageRow
        ? `League ${fmt(ageRow.league_avg, 1)} · ${ageRow.rank_label} of ${ageRow.squads}`
        : `Median ${fmt(data.median_age, 1)} · ${data.roster_size || 0} players`
    );

    setKpi(
      "recruitKpiU25",
      data.u25_minutes_pct == null ? "—" : `${fmt(data.u25_minutes_pct, 0)}%`,
      u25Row
        ? `League ${fmt(u25Row.league_avg, 0)}% · ${u25Row.rank_label} · ${signed(u25Row.delta, 1)} pp`
        : "Of squad minutes"
    );
    setKpi(
      "recruitKpiU21",
      data.u21_minutes_pct == null ? "—" : `${fmt(data.u21_minutes_pct, 0)}%`,
      u21Row
        ? `League ${fmt(u21Row.league_avg, 0)}% · ${u21Row.rank_label} · U23 ${fmt(data.u23_minutes_pct, 0)}%`
        : `U23 ${fmt(data.u23_minutes_pct, 0)}% of minutes`
    );
    setKpi(
      "recruitKpiWeighted",
      fmt(data.minutes_weighted_age, 1),
      weightedRow
        ? `League ${fmt(weightedRow.league_avg, 1)} · ${weightedRow.rank_label} of ${weightedRow.squads}`
        : `${data.players_with_minutes || 0} with minutes`
    );

    renderAgeBands(data.age_bands || [], data.league_age_bands || []);
    renderRecruitVsLeague(metrics, data.league_age_bands || [], data.league_squads);
    renderRecruitRankings(metrics, data.squad_id);

    const young = data.youngest_regular;
    const old = data.oldest_regular;
    const regularsSub = regularsRow
      ? `League ${fmt(regularsRow.league_avg, 0)} · ${regularsRow.rank_label}`
      : "trusted young core";
    const totalSub = (() => {
      const totalRow = metricByKey(metrics, "total_minutes");
      return totalRow
        ? `League avg ${Math.round(totalRow.league_avg).toLocaleString()} · ${totalRow.rank_label}`
        : "squad season load";
    })();

    setHtml(
      "homeRecruitSnapshot",
      `<div class="home-stat-grid">
        <div class="home-stat">
          <p class="home-stat__label">U25 with 500+ mins</p>
          <p class="home-stat__value">${data.u25_regulars_500 ?? "—"}</p>
          <p class="home-stat__sub">${regularsSub}</p>
        </div>
        <div class="home-stat">
          <p class="home-stat__label">Total minutes</p>
          <p class="home-stat__value">${data.total_minutes?.toLocaleString?.() || data.total_minutes || "—"}</p>
          <p class="home-stat__sub">${totalSub}</p>
        </div>
        <div class="home-stat">
          <p class="home-stat__label">Youngest used</p>
          <p class="home-stat__value">${young ? young.age : "—"}</p>
          <p class="home-stat__sub">${young ? `${young.name} · ${young.minutes}'` : "—"}</p>
        </div>
        <div class="home-stat">
          <p class="home-stat__label">Oldest used</p>
          <p class="home-stat__value">${old ? old.age : "—"}</p>
          <p class="home-stat__sub">${old ? `${old.name} · ${old.minutes}'` : "—"}</p>
        </div>
      </div>`
    );
  }

  function defaultStandoutsMonthOptions(count = 12) {
    const labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const now = new Date();
    let year = now.getFullYear();
    let month = now.getMonth() + 1;
    const options = [];
    for (let i = 0; i < count; i += 1) {
      options.push({
        year,
        month,
        label: `${labels[month - 1]} ${year}`,
        value: `${year}-${String(month).padStart(2, "0")}`,
      });
      if (month === 1) {
        year -= 1;
        month = 12;
      } else {
        month -= 1;
      }
    }
    return options;
  }

  function toggleStandoutsMonthPicker(show) {
    const wrap = document.getElementById("homeStandoutsMonthWrap");
    if (wrap) wrap.hidden = !show;
    if (show) {
      const sel = document.getElementById("homeStandoutsMonth");
      const hasMonths = sel && [...sel.options].some((opt) => /^\d{4}-\d{2}$/.test(opt.value));
      if (sel && !hasMonths) {
        const options = defaultStandoutsMonthOptions();
        const first = options[0];
        fillStandoutsMonths(options, standoutsYear || first.year, standoutsMonth || first.month);
      }
    }
  }

  function parseStandoutsMonthValue(value) {
    const match = /^(\d{4})-(\d{2})$/.exec(String(value || ""));
    if (!match) return null;
    return { year: Number(match[1]), month: Number(match[2]) };
  }

  function fillStandoutsMonths(options, selectedYear, selectedMonth) {
    const sel = document.getElementById("homeStandoutsMonth");
    if (!sel || !options?.length) return;
    const selectedValue = `${selectedYear}-${String(selectedMonth).padStart(2, "0")}`;
    sel.innerHTML = options
      .map(
        (opt) =>
          `<option value="${opt.value}"${
            opt.value === selectedValue ? " selected" : ""
          }>${opt.label}</option>`
      )
      .join("");
    standoutsYear = selectedYear;
    standoutsMonth = selectedMonth;
  }

  function syncStandoutsMonthFromData(data) {
    if (data?.period !== "month") {
      toggleStandoutsMonthPicker(false);
      return;
    }
    toggleStandoutsMonthPicker(true);
    const options = data.month_options?.length ? data.month_options : defaultStandoutsMonthOptions();
    const year = data.year ?? standoutsYear ?? options[0]?.year;
    const month = data.month ?? standoutsMonth ?? options[0]?.month;
    if (options.length && year != null && month != null) {
      fillStandoutsMonths(options, year, month);
    }
  }

  function fillStandoutsPositions(positions) {
    const group = document.getElementById("homeStandoutsPosition");
    if (!group) return;
    if (!positions?.length) return;
    if (group.dataset.filled === "1" && group.querySelectorAll("[data-position]").length > 1) {
      group.querySelectorAll(".home-filter__btn").forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.position === standoutsPosition);
      });
      return;
    }
    const shortLabel = (label, value) => {
      const map = {
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
      return map[value] || label || value;
    };
    const buttons = [
      `<button type="button" class="home-filter__btn${
        standoutsPosition === "ALL" ? " is-active" : ""
      }" data-position="ALL" title="All positions">All</button>`,
    ].concat(
      positions.map((row) => {
        const value = row.value || "";
        const label = shortLabel(row.label, value);
        const full = row.label || value;
        return `<button type="button" class="home-filter__btn${
          standoutsPosition === value ? " is-active" : ""
        }" data-position="${value}" title="${full}">${label}</button>`;
      })
    );
    group.innerHTML = buttons.join("");
    group.dataset.filled = "1";
  }

  function fillStandoutsProfiles(profiles) {
    const wrap = document.getElementById("homeStandoutsProfileWrap");
    const sel = document.getElementById("homeStandoutsProfile");
    if (!wrap || !sel) return;
    if (standoutsPosition === "ALL" || !profiles?.length) {
      wrap.hidden = true;
      standoutsProfile = "";
      return;
    }
    wrap.hidden = false;
    const options = [`<option value="">Overall (equal-weighted)</option>`].concat(
      profiles.map((p) => {
        const selected = standoutsProfile === p.apiName ? " selected" : "";
        return `<option value="${p.apiName}"${selected}>${p.label}</option>`;
      })
    );
    sel.innerHTML = options.join("");
  }

  function scoutCountCell(count, kind) {
    const value = Number(count) || 0;
    if (!value) {
      return `<td class="col-scout"><span class="home-scout-dash">—</span></td>`;
    }
    return `<td class="col-scout"><span class="home-scout-pill home-scout-pill--${kind}">${value}</span></td>`;
  }

  function standoutsThresholdText(block, fallbackMin = 85) {
    const mode = block?.min_score_mode || "absolute";
    const minScore = block?.min_score ?? fallbackMin;
    const minEff = block?.min_score_effective ?? minScore;
    if (mode === "percent_of_pool") {
      return `≥${minScore}% of pool (= ${fmt(minEff, 1)})`;
    }
    return `≥ ${fmt(minEff, 1)}`;
  }

  function standoutsPosShort(label, value) {
    const map = {
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
    return map[value] || label || value || "—";
  }

  function standoutsPlayerHref(p) {
    const id = p.playerId ?? p.player_id ?? null;
    if (id != null && id !== "") {
      return `/player/${encodeURIComponent(id)}`;
    }
    const composite = String(p.id || "");
    if (composite.includes(":")) {
      const tail = composite.split(":").pop();
      if (tail) return `/player/${encodeURIComponent(tail)}`;
    }
    return "#";
  }

  function pipelinePlayerId(p) {
    const raw = p?.playerId ?? p?.player_id ?? null;
    if (raw != null && raw !== "") {
      const n = Number(raw);
      return Number.isFinite(n) && n > 0 ? n : null;
    }
    const composite = String(p?.id || "");
    if (composite.includes(":")) {
      const parts = composite.split(":");
      const mid = Number(parts[1]);
      if (Number.isFinite(mid) && mid > 0) return mid;
      const tail = Number(parts[parts.length - 1]);
      return Number.isFinite(tail) && tail > 0 ? tail : null;
    }
    return null;
  }

  async function loadWatchIndex() {
    try {
      const data = await fetchJson("/api/player-pipelines");
      watchBoardCache = data;
      const next = new Map();
      for (const target of data.targets || []) {
        const pid = Number(target.player_id || 0);
        if (!pid) continue;
        next.set(pid, {
          id: String(target.id || ""),
          stage: String(target.stage || ""),
          name: String(target.name || ""),
        });
      }
      watchByPlayerId = next;
    } catch {
      /* optional */
    }
  }

  function standoutsWatchCell(p) {
    const pid = pipelinePlayerId(p);
    if (!pid) {
      return `<td class="col-watch"><span class="home-watch-chip home-watch-chip--disabled">—</span></td>`;
    }
    const existing = watchByPlayerId.get(pid);
    const busy = watchBusy.has(pid);
    if (!existing) {
      return `<td class="col-watch">
        <label class="home-watch-chip home-watch-chip--idle${busy ? " is-busy" : ""}" title="Add to Watch list">
          <input type="checkbox" class="home-watch-toggle" data-player-id="${pid}" ${busy ? "disabled" : ""} />
          <span class="home-watch-chip__mark" aria-hidden="true">+</span>
          <span class="home-watch-chip__label">Add</span>
        </label>
      </td>`;
    }
    const meta = stageChipMeta(existing.stage);
    return `<td class="col-watch">
      <label class="home-watch-chip home-watch-chip--${meta.kind}${busy ? " is-busy" : ""}" title="${meta.title} — uncheck to remove">
        <input type="checkbox" class="home-watch-toggle" data-player-id="${pid}" checked ${busy ? "disabled" : ""} />
        <span class="home-watch-chip__mark" aria-hidden="true"></span>
        <span class="home-watch-chip__label">${meta.label}</span>
      </label>
    </td>`;
  }

  async function toggleHomeWatch(checkbox) {
    const pid = Number(checkbox.dataset.playerId || 0);
    if (!pid || watchBusy.has(pid)) return;
    const wantOn = checkbox.checked;
    const existing = watchByPlayerId.get(pid);
    const player =
      (standoutsLastData?.by_league || [])
        .flatMap((block) => block.players || [])
        .find((row) => pipelinePlayerId(row) === pid) ||
      (watchBoardCache?.targets || []).find((row) => Number(row.player_id) === pid) ||
      null;

    if (!wantOn && existing && PIPELINE_STAGES.has(existing.stage)) {
      const ok = window.confirm(
        `${existing.name || "This player"} is already ${existing.stage.replaceAll("_", " ")} on Pipelines. Remove them?`,
      );
      if (!ok) {
        checkbox.checked = true;
        return;
      }
    }

    watchBusy.add(pid);
    // Optimistic chip — flip immediately; network must not gate the UI.
    if (wantOn) {
      watchByPlayerId.set(pid, {
        id: existing?.id || `pending-${pid}`,
        stage: WATCH_STAGE,
        name: player?.name || existing?.name || `Player ${pid}`,
      });
    } else {
      watchByPlayerId.delete(pid);
    }
    checkbox.disabled = true;
    const label = checkbox.closest(".home-watch-chip");
    label?.classList.add("is-busy");
    label?.classList.toggle("home-watch-chip--idle", !wantOn);
    label?.classList.toggle("home-watch-chip--watch", wantOn);

    try {
      if (wantOn) {
        const overall =
          player?.overall != null && player.overall !== ""
            ? Number(player.overall)
            : player?.profile_score != null
              ? Number(player.profile_score)
              : null;
        const res = await fetch("/api/player-pipelines/targets", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            player_id: pid,
            name: player?.name || existing?.name || `Player ${pid}`,
            club: player?.club || "",
            league: player?.league || "",
            position: player?.position || "",
            position_label: player?.positionLabel || player?.position_label || "",
            age: player?.age ?? null,
            stage: WATCH_STAGE,
            tags: [WATCH_TAG],
            overall_score: Number.isFinite(overall) ? overall : null,
            minutes: player?.minutes ?? null,
            enrich: false,
          }),
        });
        if (!res.ok) throw new Error(`Could not add to watch list (${res.status}).`);
        const data = await res.json();
        const target = data.target || {};
        watchByPlayerId.set(pid, {
          id: String(target.id || ""),
          stage: String(target.stage || WATCH_STAGE),
          name: String(target.name || player?.name || ""),
        });
      } else if (existing?.id && !String(existing.id).startsWith("pending-")) {
        const res = await fetch(`/api/player-pipelines/targets/${encodeURIComponent(existing.id)}`, {
          method: "DELETE",
          credentials: "same-origin",
        });
        if (!res.ok && res.status !== 404) {
          throw new Error(`Could not remove from watch list (${res.status}).`);
        }
        watchByPlayerId.delete(pid);
      } else {
        watchByPlayerId.delete(pid);
      }
      document.querySelectorAll(`.home-watch-toggle[data-player-id="${pid}"]`).forEach((node) => {
        node.checked = wantOn;
        const chip = node.closest(".home-watch-chip");
        if (!chip) return;
        chip.classList.remove(
          "home-watch-chip--idle",
          "home-watch-chip--watch",
          "home-watch-chip--pipe",
          "home-watch-chip--closed",
        );
        const mark = chip.querySelector(".home-watch-chip__mark");
        const labelEl = chip.querySelector(".home-watch-chip__label");
        if (!wantOn) {
          chip.classList.add("home-watch-chip--idle");
          if (mark) mark.textContent = "+";
          if (labelEl) labelEl.textContent = "Add";
          chip.title = "Add to Watch list";
        } else {
          const stage = watchByPlayerId.get(pid)?.stage || WATCH_STAGE;
          const meta = stageChipMeta(stage);
          chip.classList.add(`home-watch-chip--${meta.kind}`);
          if (mark) mark.textContent = "";
          if (labelEl) labelEl.textContent = meta.label;
          chip.title = `${meta.title} — uncheck to remove`;
        }
      });
      if (recruitSub === "watchlist") {
        await loadWatchListTab({ silent: true });
      }
    } catch (err) {
      if (wantOn) {
        if (existing) watchByPlayerId.set(pid, existing);
        else watchByPlayerId.delete(pid);
      } else if (existing) {
        watchByPlayerId.set(pid, existing);
      }
      checkbox.checked = !wantOn;
      window.alert(err.message || "Watch list update failed.");
    } finally {
      watchBusy.delete(pid);
      checkbox.disabled = false;
      label?.classList.remove("is-busy");
    }
  }

  function renderWatchList(data) {
    const targets = data?.targets || [];
    const seasonEl = document.getElementById("homeWatchSeason");
    if (seasonEl) {
      seasonEl.textContent = `${targets.length} player${targets.length === 1 ? "" : "s"} on the Watch list`;
    }
    if (!targets.length) {
      setHtml(
        "homeWatchList",
        `<p class="home-empty">Nobody on the Watch list yet — tick Watch on Stand outs or Who To Scout. <a href="/who-to-scout">Open Who To Scout →</a></p>`,
      );
      return;
    }

    const body = `<table class="home-watch-table">
      <thead>
        <tr>
          <th></th>
          <th>Player</th>
          <th>Club</th>
          <th>Pos</th>
          <th>Age</th>
          <th>League</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${targets
          .map((t) => {
            const pid = Number(t.player_id || 0);
            const href = pid ? `/player/${encodeURIComponent(pid)}` : "#";
            const checked = pid && watchByPlayerId.has(pid);
            const watch =
              pid > 0
                ? `<label class="home-watch-chip home-watch-chip--watch" title="Remove from Watch list">
                    <input type="checkbox" class="home-watch-toggle" data-player-id="${pid}" checked />
                    <span class="home-watch-chip__mark" aria-hidden="true"></span>
                    <span class="home-watch-chip__label">Watch</span>
                  </label>`
                : "";
            return `<tr data-target-id="${String(t.id || "").replace(/"/g, "&quot;")}">
              <td class="col-watch">${watch}</td>
              <td class="col-player"><a href="${href}">${t.name || "—"}</a></td>
              <td>${t.club || "—"}</td>
              <td>${t.position_label || t.position || "—"}</td>
              <td>${t.age ?? "—"}</td>
              <td>${t.league || "—"}</td>
              <td class="col-promote">
                <button type="button" class="home-promote-btn" data-promote-id="${String(t.id || "").replace(/"/g, "&quot;")}">→ Pipeline</button>
              </td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;

    setHtml("homeWatchList", `<div class="home-watch-grid">${body}</div>`);
  }

  async function promoteWatchToPipeline(targetId, button) {
    if (!targetId) return;
    button.disabled = true;
    try {
      const res = await fetch(`/api/watch-list/promote/${encodeURIComponent(targetId)}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!res.ok) throw new Error(`Could not promote (${res.status}).`);
      await loadWatchIndex();
      await loadWatchListTab({ silent: true });
    } catch (err) {
      window.alert(err.message || "Could not promote to Pipelines.");
      button.disabled = false;
    }
  }

  async function loadWatchListTab({ silent = false } = {}) {
    if (!silent) {
      setHtml("homeWatchList", `<p class="home-empty">Loading watch list…</p>`);
    }
    try {
      await loadWatchIndex();
      const data = await fetchJson("/api/watch-list");
      watchListLoaded = true;
      renderWatchList(data);
    } catch (err) {
      setHtml(
        "homeWatchList",
        `<p class="home-empty">Could not load watch list: ${err.message || err}</p>`,
      );
    }
  }

  function standoutsPlayerRows(players) {
    return (players || [])
      .map((p, index) => {
        const mins =
          p.minutes == null || p.minutes === ""
            ? "—"
            : `${Number(p.minutes).toLocaleString()}′`;
        const age =
          p.age == null || p.age === "" ? "—" : String(Math.round(Number(p.age)));
        let ageClass = "";
        const ageNum = Number(p.age);
        if (Number.isFinite(ageNum)) {
          if (ageNum < 23) ageClass = " is-age-u23";
          else if (ageNum > 30) ageClass = " is-age-o30";
        }
        const href = standoutsPlayerHref(p);
        const scout = p.scout || {};
        const scoutTotal = Number(p.scout_total) || 0;
        const posFull = p.positionLabel || p.position || "—";
        const pos = standoutsPosShort(p.positionLabel, p.position);
        const below = p.above_threshold === false ? " is-below" : "";
        return `<tr class="${scoutTotal ? "has-scout" : ""}${below}">
          ${standoutsWatchCell(p)}
          <td class="col-rank">${index + 1}</td>
          <td class="col-player"><a href="${href}">${p.name || "—"}</a></td>
          <td class="col-club" title="${p.club || ""}">${p.club || "—"}</td>
          <td class="col-pos" title="${posFull}">${pos}</td>
          <td class="col-age${ageClass}">${age}</td>
          <td class="col-overall">${fmt(standoutsProfile && p.profile_score != null ? p.profile_score : p.overall, 1)}</td>
          <td class="col-mins">${mins}</td>
          ${scoutCountCell(scout.live_watches, "live")}
          ${scoutCountCell(scout.video_watches, "video")}
          ${scoutCountCell(scout.report_count, "report")}
        </tr>`;
      })
      .join("");
  }

  function standoutsLeagueTable(players) {
    const body = standoutsPlayerRows(players);
    const scoreHeader = standoutsProfile ? "Profile" : "Ovr";
    return `<div class="home-standouts-scroll"><table class="home-table home-standouts-table">
      <colgroup>
        <col class="col-watch"><col class="col-rank"><col class="col-player"><col class="col-club"><col class="col-pos">
        <col class="col-age"><col class="col-overall"><col class="col-mins"><col class="col-scout"><col class="col-scout"><col class="col-scout">
      </colgroup>
      <thead>
        <tr>
          <th class="col-watch" title="Watch list / Pipelines status">Track</th>
          <th class="col-rank">#</th>
          <th class="col-player">Player</th>
          <th class="col-club">Club</th>
          <th class="col-pos">Pos</th>
          <th class="col-age">Age</th>
          <th class="col-overall">${scoreHeader}</th>
          <th class="col-mins">Mins</th>
          <th class="col-scout">Live</th>
          <th class="col-scout">Vid</th>
          <th class="col-scout">Rep</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table></div>`;
  }

  function renderStandouts(data) {
    if (data?.error) {
      widgetError("homeStandoutsList", data.error);
      return;
    }
    standoutsLastData = data;
    fillStandoutsPositions(data.positions || []);
    fillStandoutsProfiles(data.profiles || []);
    syncStandoutsMonthFromData(data);
    const periodLabel = data.period_label || (data.period === "month" ? "Monthly" : "Full season");
    const minScore = data.min_score ?? 85;
    const perLeagueLimit = data.per_league_limit || 10;
    setText(
      "homeStandoutsSeason",
      `${periodLabel} · Top ${perLeagueLimit} per league (fill below ${minScore}% cut-off if needed)`
    );
    const scoringNote =
      data.scoring?.note ||
      "Equal-weighted Impect profile overall — same Overall column as Who To Scout.";
    setText(
      "homeStandoutsNote",
      `${scoringNote} Live / Video / Reports from Fixture Planner. Open Who To Scout for profile weights and filters.`
    );
    const noteEl = document.getElementById("homeStandoutsNote");
    if (noteEl && !noteEl.querySelector("a[href='/who-to-scout']")) {
      noteEl.innerHTML = `${noteEl.textContent} <a href="/who-to-scout">Who To Scout →</a>`;
    }

    if (data.building) {
      setHtml(
        "homeStandoutsList",
        `<p class="home-empty">Building stand outs across positions — this can take a minute on first load…</p>`
      );
      if (standoutsPollTimer) clearTimeout(standoutsPollTimer);
      standoutsPollTimer = setTimeout(() => {
        loadStandoutsTab({ silent: true }).catch(() => {});
      }, 5000);
      return;
    }

    if (data.cache_stale && data.missing_leagues?.length) {
      if (standoutsPollTimer) clearTimeout(standoutsPollTimer);
      standoutsPollTimer = setTimeout(() => {
        loadStandoutsTab({ silent: true }).catch(() => {});
      }, 8000);
    }

    const blocks = data.by_league || [];
    const hasAny = blocks.some((block) => (block.players || []).length);
    if (!blocks.length || !hasAny) {
      const highest =
        data.highest_overall != null ? ` Highest overall in pool: ${fmt(data.highest_overall, 1)}.` : "";
      setHtml(
        "homeStandoutsList",
        `<p class="home-empty">No stand outs at ≥ ${minScore}% of any league pool for this filter.${standoutsU25 ? " (U25 only)" : ""}${highest}</p>`
      );
      return;
    }

    const cards = blocks
      .map((block) => {
        const players = block.players || [];
        const threshold = standoutsThresholdText(block, minScore);
        const meta =
          block.pool_count != null
            ? `${threshold} · ${block.player_count || 0} qualify · pool ${block.pool_count}`
            : threshold;
        const inner = block.loading
          ? `<p class="home-standouts-league__empty">Loading ${block.league}…</p>`
          : players.length
          ? standoutsLeagueTable(players)
          : `<p class="home-standouts-league__empty">No stand outs${
              block.highest_overall != null
                ? ` (league max ${fmt(block.highest_overall, 1)})`
                : ""
            }.</p>`;
        return `<section class="home-standouts-league">
          <div class="home-standouts-league__head">
            <div>
              <h3 class="home-standouts-league__title">${block.league || "League"}</h3>
              <p class="home-standouts-league__meta">${meta}</p>
            </div>
            <span class="home-standouts-league__count">${players.length}/${perLeagueLimit}</span>
          </div>
          ${inner}
        </section>`;
      })
      .join("");

    setHtml("homeStandoutsList", `<div class="home-standouts-grid">${cards}</div>`);
  }

  function setRecruitSub(subId) {
    if (!subId) return;
    recruitSub = subId;
    document.querySelectorAll(".home-subtab[data-recruit-sub]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.recruitSub === subId);
    });
    document.querySelectorAll(".home-subpanel").forEach((panel) => {
      panel.hidden = panel.dataset.recruitPanel !== subId;
    });
    if (subId === "standouts") {
      void loadWatchIndex().then(() => {
        if (standoutsLastData && standoutsLoaded) {
          renderStandouts(standoutsLastData);
        } else {
          loadStandoutsTab().finally(() => {
            standoutsLoaded = true;
          });
        }
      });
    }
    if (subId === "watchlist") {
      void loadWatchListTab();
    }
  }

  function bindRecruitSubtabs() {
    document.querySelectorAll(".home-subtab[data-recruit-sub]").forEach((btn) => {
      btn.addEventListener("click", () => setRecruitSub(btn.dataset.recruitSub));
    });
    document.getElementById("homeStandoutsList")?.addEventListener("change", (event) => {
      const checkbox = event.target.closest("input.home-watch-toggle");
      if (!checkbox) return;
      void toggleHomeWatch(checkbox);
    });
    document.getElementById("homeWatchList")?.addEventListener("change", (event) => {
      const checkbox = event.target.closest("input.home-watch-toggle");
      if (!checkbox) return;
      void toggleHomeWatch(checkbox);
    });
    document.getElementById("homeWatchList")?.addEventListener("click", (event) => {
      const promoteBtn = event.target.closest("[data-promote-id]");
      if (!promoteBtn) return;
      void promoteWatchToPipeline(promoteBtn.dataset.promoteId, promoteBtn);
    });
    document.querySelectorAll("#homeStandoutsPeriod .home-filter__btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        standoutsPeriod = btn.dataset.period || "season";
        document.querySelectorAll("#homeStandoutsPeriod .home-filter__btn").forEach((el) => {
          el.classList.toggle("is-active", el === btn);
        });
        toggleStandoutsMonthPicker(standoutsPeriod === "month");
        standoutsLastData = null;
        loadStandoutsTab();
      });
    });
    const ageGroup = document.getElementById("homeStandoutsAge");
    if (ageGroup) {
      ageGroup.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-age]");
        if (!btn) return;
        standoutsU25 = btn.dataset.age === "u25";
        standoutsLastData = null;
        ageGroup.querySelectorAll(".home-filter__btn").forEach((el) => {
          el.classList.toggle("is-active", el === btn);
        });
        loadStandoutsTab();
      });
    }
    const monthSel = document.getElementById("homeStandoutsMonth");
    if (monthSel) {
      monthSel.addEventListener("change", () => {
        const parsed = parseStandoutsMonthValue(monthSel.value);
        if (!parsed) return;
        standoutsYear = parsed.year;
        standoutsMonth = parsed.month;
        loadStandoutsTab();
      });
    }
    const pos = document.getElementById("homeStandoutsPosition");
    if (pos) {
      pos.addEventListener("click", (event) => {
        const btn = event.target.closest(".home-filter__btn[data-position]");
        if (!btn || !pos.contains(btn)) return;
        standoutsPosition = btn.dataset.position || "ALL";
        standoutsProfile = "";
        standoutsLastData = null;
        pos.querySelectorAll(".home-filter__btn").forEach((el) => {
          el.classList.toggle("is-active", el === btn);
        });
        loadStandoutsTab();
      });
    }
    const profileSel = document.getElementById("homeStandoutsProfile");
    if (profileSel) {
      profileSel.addEventListener("change", () => {
        standoutsProfile = profileSel.value;
        standoutsLastData = null;
        loadStandoutsTab();
      });
    }
  }

  function renderPhaseBars(targetId, noteId, rows, side) {
    if (!rows?.length) {
      widgetError(targetId, "Phase goal data not ready yet.");
      return;
    }
    const maxPg = Math.max(
      ...rows.map((r) => Math.max(Number(r.per_game) || 0, Number(r.benchmark_per_game) || 0)),
      0.01
    );
    const html = rows
      .map((r) => {
        const pg = Number(r.per_game);
        const bench = Number(r.benchmark_per_game);
        const width = Math.max(4, Math.round(((Number.isFinite(pg) ? pg : 0) / maxPg) * 100));
        const delta = r.delta_vs_playoff;
        const good =
          side === "scored"
            ? delta != null && delta >= -0.05
            : delta != null && delta <= 0.05;
        const deltaCls = good ? "is-up" : "is-down";
        return `<div class="home-bar">
          <span class="home-bar__label">${r.label}</span>
          <div class="home-bar__track"><div class="home-bar__fill ${phaseFillClass(r.key)} ${good ? "is-good" : "is-bad"}" style="width:${width}%"></div></div>
          <span class="home-bar__meta">${fmt(pg, 2)}/g <span class="${deltaCls}">(${signed(delta, 2)})</span> · BM ${fmt(bench, 2)}</span>
        </div>`;
      })
      .join("");
    setHtml(targetId, `<div class="home-bars">${html}</div>`);
    if (noteId) {
      setText(noteId, "Goals/game vs Strategy Report play-off (7th) avg");
    }
  }

  function renderStrategy(data) {
    if (data?.error) {
      widgetError("homePhaseScored", data.error);
      widgetError("homePhaseConceded", data.error);
      widgetError("homeGameState", data.error);
      widgetError("homePerfPhases", data.error);
      widgetError("homePerfPhasesConceded", data.error);
      return;
    }
    renderPerfPhases(data);
    const pace = data.pace || {};
    const onTrack = !!pace.on_track_playoff;
    const banner = document.getElementById("homePaceBanner");
    if (banner) {
      banner.innerHTML = `
        <span class="home-pace__badge ${onTrack ? "is-on" : "is-off"}">${onTrack ? "On track for play-offs" : "Below play-off pace"}</span>
        <p class="home-pace__text">
          <strong>${fmt(pace.ppg, 2)} PPG</strong>
          · play-off line <strong>${fmt(pace.playoff_ppg, 2)}</strong>${pace.playoff_club ? ` (${pace.playoff_club})` : ""}
          · auto <strong>${fmt(pace.auto_ppg, 2)}</strong>
          · ${signed(pace.pts_vs_playoff, 0)} pts vs 6th
        </p>
        <a class="home-card__link" href="/strategy-tracker">Season Progress →</a>`;
    }

    setKpi(
      "stratKpiPpg",
      fmt(pace.ppg, 2),
      `Play-off ${fmt(pace.playoff_ppg, 2)} · ${signed(pace.ppg_vs_playoff, 2)}`
    );
    setKpi(
      "stratKpiProj",
      fmt(pace.ppg_x46, 0),
      `xPts proj ${fmt(pace.xppg_x46, 0)} · ${pace.played || "—"} played`
    );
    setKpi("stratKpiXppg", fmt(pace.xppg, 2), `League PPG ${fmt(pace.league_ppg, 2)}`);
    setKpi(
      "stratKpiLuck",
      signed(pace.xp_vs_actual, 1),
      Number(pace.xp_vs_actual) >= 0 ? "Overperforming xPts" : "Underperforming xPts"
    );

    const phases = data.phases || {};
    if (phases.deferred) {
      setHtml("homePhaseScored", `<p class="home-empty">Loading phase scoring…</p>`);
      setHtml("homePhaseConceded", `<p class="home-empty">Loading phase defending…</p>`);
    } else {
      renderPhaseBars("homePhaseScored", "homePhaseScoredNote", phases.scored, "scored");
      renderPhaseBars("homePhaseConceded", "homePhaseConcededNote", phases.conceded, "conceded");
      if (phases.matches) {
        setText(
          "homePhaseScoredNote",
          `${phases.matches} matches · GF ${phases.goals_for ?? "—"} · vs play-off BM`
        );
        setText(
          "homePhaseConcededNote",
          `${phases.matches} matches · GA ${phases.goals_against ?? "—"} · vs play-off BM`
        );
      }
    }

    const gs = data.game_state || {};
    if (gs.deferred) {
      setHtml("homeGameState", `<p class="home-empty">Loading game-state board…</p>`);
    } else if (gs.error) {
      widgetError("homeGameState", "First-goal board still building.");
    } else {
      setHtml(
        "homeGameState",
        `<div class="home-stat-grid">
          <div class="home-stat">
            <p class="home-stat__label">PPG when scoring 1st</p>
            <p class="home-stat__value">${fmt(gs.ppg_scored_first, 2)}</p>
            <p class="home-stat__sub">League ${fmt(gs.league_ppg_scored_first, 2)} · ${gs.scored_first ?? "—"} games</p>
          </div>
          <div class="home-stat">
            <p class="home-stat__label">PPG when conceding 1st</p>
            <p class="home-stat__value">${fmt(gs.ppg_conceded_first, 2)}</p>
            <p class="home-stat__sub">League ${fmt(gs.league_ppg_conceded_first, 2)} · ${gs.conceded_first ?? "—"} games</p>
          </div>
          <div class="home-stat">
            <p class="home-stat__label">Clean sheet %</p>
            <p class="home-stat__value">${fmt(gs.clean_sheet_pct, 0)}%</p>
            <p class="home-stat__sub">League ${fmt(gs.league_clean_sheet_pct, 0)}%</p>
          </div>
          <div class="home-stat">
            <p class="home-stat__label">First goal split</p>
            <p class="home-stat__value">${gs.scored_first ?? "—"} / ${gs.conceded_first ?? "—"}</p>
            <p class="home-stat__sub">scored 1st / conceded 1st</p>
          </div>
        </div>`
      );
    }

    const vs = data.vs_league || {};
    const flat = {};
    const averages = {};
    Object.entries(vs).forEach(([key, row]) => {
      flat[key] = row?.us;
      averages[key] = row?.league;
    });
    if (Object.keys(flat).length) {
      renderVsLeague(flat, averages);
    }
  }

  async function loadStrategyBundle() {
    const meta = await fetchJson(
      `/api/club-strategy/meta?competition=${encodeURIComponent(COMPETITION)}`
    );
    const iterationId = meta.default_iteration_id || FALLBACK_ITERATION;
    const season =
      (meta.seasons || []).find((s) => s.iteration_id === iterationId)?.label ||
      meta.competition ||
      COMPETITION;
    const report = await fetchJson(`/api/club-strategy/report?iteration_id=${iterationId}`);
    const standings = report.standings || [];
    const averages = report.averages || {};
    const pv = standings.find((r) => r.focus) || null;
    return { iterationId, season, standings, averages, pv };
  }

  async function loadFormBundle(iterationId) {
    let squadId = FALLBACK_SQUAD;
    try {
      const cfg = await fetchJson("/api/post-match/config");
      if (cfg.portValeSquadId) squadId = cfg.portValeSquadId;
    } catch (_) {
      /* defaults */
    }
    const data = await fetchJson(
      `/api/post-match/iterations/${iterationId}/matches?squad_id=${squadId}`
    );
    return data.matches || data || [];
  }

  function setTab(tabId) {
    activeTab = tabId;
    document.querySelectorAll(".home-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.tab === tabId);
    });
    document.querySelectorAll(".home-panel").forEach((panel) => {
      panel.hidden = panel.dataset.panel !== tabId;
    });
    if (tabId === "recruitment" && !recruitmentLoaded) {
      loadRecruitmentTab().finally(() => {
        recruitmentLoaded = true;
      });
    }
    if (tabId === "recruitment") {
      loadStandoutsTab({ silent: recruitSub !== "standouts" }).finally(() => {
        standoutsLoaded = true;
      });
    }
    if (tabId === "performance") {
      loadAvailability();
      // Performance tab needs both:
      // 1) phase goals / defending (from /api/home/strategy?detail=true)
      // 2) league form + rankings (from /api/club-strategy/report)
      //
      // If the user opens Performance directly, the Home loader may not have run yet.
      (async () => {
        try {
          const bundle = await loadStrategyBundle();
          if (bundle?.pv) {
            cachedStrategyBundle = bundle;
            cachedMatches = cachedMatches || [];
            renderKpis(
              bundle.pv,
              bundle.averages,
              bundle ? `${COMPETITION} · ${bundle.season}` : COMPETITION
            );
            renderTable(bundle.standings || []);
            strategyDetailLoaded = true;
          }
        } catch (e) {
          widgetError("homeTableBody", `Could not load league data: ${e.message}`);
        }

        try {
          const snap = await loadStrategyTab({ detail: true });
          if (!snap) return;
          cachedStrategySnapshot = snap;
          renderPerfPhases(snap);
          if (snap?.phases?.deferred) {
            for (let attempt = 0; attempt < 8; attempt += 1) {
              await new Promise((resolve) => setTimeout(resolve, 4000));
              const again = await loadStrategyTab({ detail: true });
              if (again && !again?.phases?.deferred) {
                cachedStrategySnapshot = again;
                strategyDetailLoaded = true;
                renderPerfPhases(again);
                break;
              }
            }
          } else {
            strategyDetailLoaded = true;
          }
        } catch (e) {
          widgetError("homePerfPhases", `Could not load phase goals: ${e.message}`);
          widgetError("homePerfPhasesConceded", `Could not load phase defending: ${e.message}`);
        }
      })();
    }
    if (tabId === "strategy" && !strategyDetailLoaded) {
      loadStrategyTab({ detail: true }).then((snap) => {
        if (snap) {
          cachedStrategySnapshot = snap;
          strategyDetailLoaded = true;
          renderHomeOverview(
            cachedStrategyBundle?.pv,
            cachedStrategyBundle?.averages,
            cachedStrategyBundle ? `${COMPETITION} · ${cachedStrategyBundle.season}` : COMPETITION,
            cachedStrategySnapshot,
            cachedMatches
          );
        }
      });
    }
  }

  function bindTabs() {
    document.querySelectorAll(".home-tab").forEach((btn) => {
      btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });
    setTab(activeTab);
  }

  async function loadFeeds() {
    try {
      const activity = await fetchJson("/api/home/activity?limit=40");
      renderActivity(activity.events || []);
      renderRecruitmentActivity(activity.events || []);
    } catch (_) {
      widgetError("homeActivity", "Could not load live activity.");
      widgetError("homeRecruitFeed", "Could not load recruitment activity.");
    }
    try {
      const changelog = await fetchJson("/api/home/changelog?limit=12");
      renderChangelog(changelog.entries || []);
    } catch (_) {
      widgetError("homeChangelog", "Could not load release notes.");
    }
  }

  async function loadRecruitmentTab() {
    try {
      const data = await fetchJson("/api/home/recruitment");
      renderRecruitment(data);
    } catch (err) {
      widgetError("homeAgeBands", `Could not load recruitment stats: ${err.message}`);
      widgetError("homeRecruitSnapshot", "Waiting for Impect squad data…");
      widgetError("homeRecruitVsLeague", "League comparison failed to load.");
      widgetError("homeRecruitRankings", "Club rankings failed to load.");
    }
  }

  async function loadStandoutsTab({ silent = false, retry = 0 } = {}) {
    if (!silent) {
      setHtml("homeStandoutsList", `<p class="home-empty">Loading stand outs…</p>`);
    } else if (standoutsPeriod === "month" && retry > 0) {
      setHtml(
        "homeStandoutsList",
        `<p class="home-empty">Building stand outs for this month — first load can take a minute…</p>`
      );
    }
    try {
      const params = new URLSearchParams({
        period: standoutsPeriod,
        position: standoutsPosition,
        min_score: "85",
      });
      if (standoutsPeriod === "month" && standoutsYear != null && standoutsMonth != null) {
        params.set("year", String(standoutsYear));
        params.set("month", String(standoutsMonth));
      }
      if (standoutsProfile) {
        params.set("profile", standoutsProfile);
      }
      if (standoutsU25) {
        params.set("max_age", "25");
      }
      const data = await fetchJson(`/api/home/recruitment/standouts?${params}`);
      renderStandouts(data);
    } catch (err) {
      if (retry < 10 && /503|502|504|timeout/i.test(String(err.message || ""))) {
        await new Promise((resolve) => setTimeout(resolve, 2500 + retry * 1500));
        return loadStandoutsTab({ silent: true, retry: retry + 1 });
      }
      widgetError(
        "homeStandoutsList",
        `Could not load stand outs: ${err.message}. Try again in a moment.`
      );
    }
  }

  async function loadStrategyTab({ detail = true } = {}) {
    try {
      const params = new URLSearchParams({
        competition: COMPETITION,
        detail: detail ? "true" : "false",
      });
      const data = await fetchJson(`/api/home/strategy?${params}`);
      if (detail || !strategyDetailLoaded) {
        renderStrategy(data);
      }
      return data;
    } catch (err) {
      if (detail) {
        widgetError("homePhaseScored", `Could not load strategy: ${err.message}`);
        widgetError("homePhaseConceded", "Phase goals still building…");
        widgetError("homeGameState", "Game state still building…");
      }
      return null;
    }
  }

  async function loadHomeDashboard() {
    document.body.classList.add("home-loading");
    bindTabs();
    bindRecruitSubtabs();
    bindCalendarNav();

    // Paint each home widget as soon as its data arrives — never leave
    // "Loading…" forever because one slow request held Promise.all.
    const paintHome = () => {
      try {
        renderHomeTab();
      } catch (err) {
        console.error("Home render failed:", err);
      }
    };

    const jobs = [
      loadBrokeJoke(),
      loadHubNotice(),
      loadFotmobFixtures()
        .then(paintHome)
        .catch((err) => {
          widgetError("homePvUpcoming", `Could not load FotMob fixtures: ${err.message}`);
          widgetError("homePvPlayed", "FotMob results unavailable.");
          setHtml("homeNext", `<p class="home-empty">Could not load next fixture.</p>`);
        }),
      loadFeeds(),
      loadScoutCalendar()
        .then(paintHome)
        .catch((err) => {
          widgetError("homeScoutUpcoming", "Assign fixtures in Fixture Planner.");
          console.warn("Scout calendar:", err.message);
        }),
      loadTeamSchedule({ silent: true }).then(paintHome),
      // Overview KPIs need league standings + play-off pace (light, cached).
      loadStrategyBundle()
        .then((strategy) => {
          cachedStrategyBundle = strategy;
          paintHome();
        })
        .catch((err) => {
          setKpi("homeKpiOverviewPos", "—", "League data unavailable");
          setKpi("homeKpiOverviewPpg", "—", "—");
          setKpi("homeKpiOverviewPace", "—", "—");
          console.warn("Strategy bundle:", err.message);
        }),
      loadStrategyTab({ detail: false })
        .then((snap) => {
          cachedStrategySnapshot = snap;
          paintHome();
        })
        .catch((err) => {
          console.warn("Strategy snapshot:", err.message);
        }),
    ];

    await Promise.allSettled(jobs);
    paintHome();
    document.body.classList.remove("home-loading");

    // Heavy recruitment / stand outs / phase detail still wait for their tabs.
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(loadFeeds, 60000);
  }

  global.HubHome = { load: loadHomeDashboard, setTab };
})(window);
