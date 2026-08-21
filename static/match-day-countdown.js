(() => {
  "use strict";

  // Dressing-room board timings as minutes before kick-off (from 15:00 board).
  const SCHEDULE = [
    { label: "Analysis", minutesBefore: 105 },
    { label: "Team sheet", minutesBefore: 75 },
    { label: "Set pieces / Staff team analysis", minutesBefore: 60 },
    { label: "Warm up", minutesBefore: 43 },
    { label: "Back in dressing room", minutesBefore: 14 },
    { label: "LEAVE DRESSING ROOM", minutesBefore: 6 },
    { label: "Kick off", minutesBefore: 0, isKickoff: true },
  ];

  const PV_BADGE = "/standalone/port-vale-badge.png?v=2";
  const REFRESH_MS = 5 * 60 * 1000;
  const WEATHER_MS = 10 * 60 * 1000;

  const els = {
    app: document.getElementById("app"),
    status: document.getElementById("status"),
    matchHeader: document.getElementById("matchHeader"),
    homeBadge: document.getElementById("homeBadge"),
    awayBadge: document.getElementById("awayBadge"),
    homeName: document.getElementById("homeName"),
    awayName: document.getElementById("awayName"),
    matchMeta: document.getElementById("matchMeta"),
    kickoffBlock: document.getElementById("kickoffBlock"),
    kickoffLabel: document.getElementById("kickoffLabel"),
    kickoffClock: document.getElementById("kickoffClock"),
    nextBlock: document.getElementById("nextBlock"),
    nextName: document.getElementById("nextName"),
    nextClock: document.getElementById("nextClock"),
    scheduleBlock: document.getElementById("scheduleBlock"),
    scheduleList: document.getElementById("scheduleList"),
    nowClock: document.getElementById("nowClock"),
    weatherBox: document.getElementById("weatherBox"),
    weatherPlace: document.getElementById("weatherPlace"),
    weatherTemp: document.getElementById("weatherTemp"),
    weatherCond: document.getElementById("weatherCond"),
    fullscreenBtn: document.getElementById("fullscreenBtn"),
  };

  let fixture = null;
  let lastScheduleKey = "";
  let lastWeatherKey = "";

  function pad(n) {
    return String(Math.max(0, n)).padStart(2, "0");
  }

  function formatDuration(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) return `${pad(h)}:${pad(m)}:${pad(s)}`;
    return `${pad(m)}:${pad(s)}`;
  }

  function formatClock(date) {
    return date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function formatNow(date) {
    return [
      pad(date.getHours()),
      pad(date.getMinutes()),
      pad(date.getSeconds()),
    ].join(":");
  }

  function parseKickoff(raw) {
    if (!raw) return null;
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function scheduleItems(kickoff) {
    return SCHEDULE.map((item) => ({
      ...item,
      at: new Date(kickoff.getTime() - item.minutesBefore * 60 * 1000),
    }));
  }

  function nextEvent(kickoff, now) {
    for (const item of scheduleItems(kickoff)) {
      if (item.at.getTime() > now.getTime()) return item;
    }
    return null;
  }

  function setBadge(img, url, name) {
    img.alt = name || "";
    img.onerror = () => {
      img.onerror = null;
      img.src = PV_BADGE;
    };
    img.src = url || PV_BADGE;
  }

  function hideAll() {
    els.matchHeader.hidden = true;
    els.kickoffBlock.hidden = true;
    els.nextBlock.hidden = true;
    els.scheduleBlock.hidden = true;
    els.weatherBox.hidden = true;
  }

  function renderSchedule(kickoff, now) {
    const items = scheduleItems(kickoff);
    const upcoming = nextEvent(kickoff, now);
    const key = items
      .map((item) => {
        const state =
          upcoming && item.at.getTime() === upcoming.at.getTime()
            ? "next"
            : item.at.getTime() <= now.getTime()
              ? "past"
              : "soon";
        return `${item.minutesBefore}:${formatClock(item.at)}:${state}`;
      })
      .join("|");

    if (key === lastScheduleKey) return;
    lastScheduleKey = key;

    els.scheduleList.innerHTML = items
      .map((item) => {
        const isNext = upcoming && item.at.getTime() === upcoming.at.getTime();
        const isPast = item.at.getTime() <= now.getTime();
        const classes = [
          "mdc-schedule-row",
          isPast ? "is-past" : "",
          isNext ? "is-next" : "",
          item.isKickoff ? "is-kickoff" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          `<li class="${classes}">` +
          `<span class="mdc-schedule-row__time">${formatClock(item.at)}</span>` +
          `<span class="mdc-schedule-row__label">${item.label}</span>` +
          `</li>`
        );
      })
      .join("");
  }

  async function loadWeather(row) {
    if (!row) {
      els.weatherBox.hidden = true;
      return;
    }
    const isHome = !!row.isHome;
    const opponent = (row.opponent && row.opponent.name) || "";
    const key = `${isHome ? "H" : "A"}:${opponent}`;
    if (key === lastWeatherKey && !els.weatherBox.hidden) return;
    lastWeatherKey = key;

    try {
      const params = new URLSearchParams({
        isHome: isHome ? "true" : "false",
      });
      if (opponent) params.set("opponent", opponent);
      const res = await fetch(`/api/match-day-countdown/weather?${params}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const temp =
        data.temp_c == null ? "—" : `${Math.round(Number(data.temp_c))}°C`;
      const wind =
        data.wind_mph == null ? "" : ` · ${Math.round(Number(data.wind_mph))} mph`;
      els.weatherPlace.textContent = data.place || (isHome ? "Vale Park" : opponent);
      els.weatherTemp.textContent = temp;
      els.weatherCond.textContent = `${data.condition || "—"}${wind}`;
      els.weatherBox.hidden = false;
    } catch (_) {
      els.weatherBox.hidden = true;
    }
  }

  function renderFixture(row) {
    fixture = row;
    lastScheduleKey = "";
    if (!row) {
      els.status.hidden = false;
      els.status.textContent = "No upcoming fixture found.";
      hideAll();
      return;
    }

    els.status.hidden = true;
    els.matchHeader.hidden = false;
    els.kickoffBlock.hidden = false;
    els.scheduleBlock.hidden = false;

    const opponent = row.opponent || {};
    const isHome = !!row.isHome;
    const homeName = isHome ? "Port Vale" : opponent.name || "Opponent";
    const awayName = isHome ? opponent.name || "Opponent" : "Port Vale";
    const homeBadge = row.home_badge || (isHome ? PV_BADGE : opponent.badge);
    const awayBadge = row.away_badge || (isHome ? opponent.badge : PV_BADGE);

    els.homeName.textContent = homeName;
    els.awayName.textContent = awayName;
    setBadge(els.homeBadge, homeBadge, homeName);
    setBadge(els.awayBadge, awayBadge, awayName);

    const kickoff = parseKickoff(row.kickoff_utc || row.scheduledDate);
    const when = kickoff
      ? kickoff.toLocaleString(undefined, {
          weekday: "short",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "Kick-off TBC";
    const venue = isHome ? "Home" : "Away";
    const competition = row.competition || "Match";
    els.matchMeta.textContent = `${competition} · ${venue} · ${when}`;

    loadWeather(row);
    tick();
  }

  function tick() {
    const now = new Date();
    els.nowClock.textContent = formatNow(now);

    if (!fixture) return;
    const kickoff = parseKickoff(fixture.kickoff_utc || fixture.scheduledDate);
    if (!kickoff) {
      els.kickoffClock.textContent = "--:--:--";
      els.nextBlock.hidden = true;
      els.scheduleBlock.hidden = true;
      return;
    }

    const toKickoff = kickoff.getTime() - now.getTime();

    els.app.classList.toggle("is-live", toKickoff <= 0 && toKickoff > -2 * 60 * 60 * 1000);
    els.app.classList.toggle("is-done", toKickoff <= -2 * 60 * 60 * 1000);

    if (toKickoff > 0) {
      els.kickoffLabel.textContent = "Kick off";
      els.kickoffClock.textContent = formatDuration(toKickoff);
    } else if (toKickoff > -2 * 60 * 60 * 1000) {
      els.kickoffLabel.textContent = "Match on";
      els.kickoffClock.textContent = "LIVE";
    } else {
      els.kickoffLabel.textContent = "Kick off";
      els.kickoffClock.textContent = "DONE";
    }

    const upcoming = nextEvent(kickoff, now);
    if (upcoming && toKickoff > 0) {
      els.nextBlock.hidden = false;
      els.nextName.textContent = upcoming.label;
      els.nextClock.textContent = formatDuration(upcoming.at.getTime() - now.getTime());
    } else {
      els.nextBlock.hidden = true;
    }

    els.scheduleBlock.hidden = false;
    renderSchedule(kickoff, now);
  }

  async function loadFixture() {
    try {
      const res = await fetch("/api/match-day-countdown/next", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderFixture(data.fixture || null);
    } catch (err) {
      els.status.hidden = false;
      els.status.textContent = `Could not load fixture: ${err.message || err}`;
      hideAll();
    }
  }

  els.fullscreenBtn.addEventListener("click", async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
        els.fullscreenBtn.textContent = "Exit";
      } else {
        await document.exitFullscreen();
        els.fullscreenBtn.textContent = "Fullscreen";
      }
    } catch (_) {
      /* ignore */
    }
  });

  document.addEventListener("fullscreenchange", () => {
    els.fullscreenBtn.textContent = document.fullscreenElement ? "Exit" : "Fullscreen";
  });

  loadFixture();
  tick();
  setInterval(tick, 250);
  setInterval(loadFixture, REFRESH_MS);
  setInterval(() => {
    lastWeatherKey = "";
    if (fixture) loadWeather(fixture);
  }, WEATHER_MS);
})();
