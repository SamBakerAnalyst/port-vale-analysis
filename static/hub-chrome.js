/**
 * Hub chrome behaviour on tool pages: clock, Next up card, full-height board layouts, and hiding the page's own duplicate title.
 * Markup is injected server-side by app/hub_chrome.py.
 */
(function initHubChrome() {
  const root = document.querySelector("[data-pv-hub-chrome]");
  if (!root) return;
  const meta = window.PV_HUB_CHROME || {};
  const OVERVIEW_KEY = "pvHub.overview";
  const OVERVIEW_MAX_AGE_MS = 3 * 3600 * 1000;

  function $(id) {
    return document.getElementById(id);
  }

  function updateClock() {
    const now = new Date();
    $("pvcTime").textContent = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    $("pvcDate").textContent = now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  }

  function normalise(text) {
    return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  function hideDuplicateTitle() {
    const want = normalise(meta.title);
    if (!want) return;
    const heading = Array.from(document.querySelectorAll("h1")).find(
      (el) => !root.contains(el) && normalise(el.textContent) === want
    );
    if (heading) heading.classList.add("pvc-dup-title");
  }

  // Board tools lock the body to the viewport; let their root fill what's left under the masthead.
  function fitBoardLayout() {
    if (document.body.classList.contains("pvc-board")) return;
    if (getComputedStyle(document.body).overflowY !== "hidden") return;
    const viewport = window.innerHeight;
    const fills = Array.from(document.body.children).filter((el) => {
      if (el === root || el.tagName === "SCRIPT" || el.tagName === "STYLE") return false;
      const style = getComputedStyle(el);
      if (style.position === "fixed" || style.position === "absolute" || style.display === "none") return false;
      return el.getBoundingClientRect().height >= viewport - 4;
    });
    fills.forEach((el) => el.classList.add("pvc-fill"));
    document.body.classList.add("pvc-board");
  }

  function bindFullscreen() {
    document.addEventListener("fullscreenchange", () => {
      document.body.classList.toggle("pvc-off", !!document.fullscreenElement);
    });
  }

  function ordinal(n) {
    const s = ["th", "st", "nd", "rd"];
    const v = n % 100;
    return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
  }

  function formatKickoff(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const day = date.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    const hasTime = /T\d{2}:\d{2}/.test(String(value));
    const time = hasTime ? date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
    return time ? `${day} · ${time}` : day;
  }

  function daysUntil(value) {
    const key = String(value || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return null;
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    return Math.round((new Date(`${key}T12:00:00`) - new Date(`${today}T12:00:00`)) / 86400000);
  }

  function renderOverview(data) {
    const league = $("pvcLeague");
    const pos = Number(data.position);
    league.hidden = !Number.isFinite(pos) || pos <= 0;
    if (!league.hidden) {
      league.textContent = `${ordinal(pos)} in League Two${data.points != null ? ` · ${data.points} pts` : ""}`;
    }

    const next = data.next;
    const card = $("pvcNext");
    card.hidden = !next;
    if (!next) return;
    $("pvcNextOpp").textContent = next.opponent || "TBC";
    const ha = $("pvcNextHa");
    ha.textContent = next.isHome ? "H" : "A";
    ha.classList.toggle("is-away", !next.isHome);
    $("pvcNextMeta").textContent = [formatKickoff(next.kickoff), next.competition].filter(Boolean).join(" · ");
    const crest = $("pvcNextCrest");
    crest.innerHTML = "";
    if (next.badge) {
      const img = document.createElement("img");
      img.src = next.badge;
      img.alt = "";
      img.onerror = () => img.remove();
      crest.appendChild(img);
    }
    const days = daysUntil(next.kickoff) ?? Number(next.days);
    const count = $("pvcNextCount");
    const unit = $("pvcNextUnit");
    if (days === 0) {
      count.textContent = "Today";
      unit.textContent = "matchday";
    } else if (days === 1) {
      count.textContent = "1";
      unit.textContent = "day";
    } else if (Number.isFinite(days) && days > 0) {
      count.textContent = String(days);
      unit.textContent = "days";
    } else {
      count.textContent = "—";
      unit.textContent = "TBC";
    }
  }

  function readCachedOverview() {
    try {
      const saved = JSON.parse(localStorage.getItem(OVERVIEW_KEY) || "null");
      if (saved && saved.data && Date.now() - Number(saved.savedAt || 0) < OVERVIEW_MAX_AGE_MS) return saved.data;
    } catch (_) {
      /* ignore bad cache */
    }
    return null;
  }

  async function loadOverview() {
    const cached = readCachedOverview();
    if (cached) {
      renderOverview(cached);
      return;
    }
    try {
      const res = await fetch("/api/home/fixtures", { cache: "no-store", signal: AbortSignal.timeout(8000) });
      if (!res.ok) return;
      const payload = await res.json();
      const up = payload.next;
      if (!up) return;
      const opponent =
        (typeof up.opponent === "string" ? up.opponent : up.opponent?.name) ||
        (up.isHome ? up.away?.name || up.away : up.home?.name || up.home) ||
        "TBC";
      renderOverview({
        next: {
          opponent,
          badge: up.opponent_badge || up.opponent?.badge || (up.isHome ? up.away_badge : up.home_badge) || "",
          isHome: Boolean(up.isHome),
          kickoff: up.kickoff_utc || up.scheduledDate || up.date || "",
          competition: up.competition || "",
        },
      });
    } catch (_) {
      /* no Next up card for accounts without fixtures access */
    }
  }

  updateClock();
  setInterval(updateClock, 30_000);
  hideDuplicateTitle();
  bindFullscreen();
  loadOverview();
  fitBoardLayout();
  window.addEventListener("load", fitBoardLayout, { once: true });
})();
