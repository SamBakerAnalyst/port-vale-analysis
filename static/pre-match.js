const PRE_MATCH_BUILD = document.querySelector('meta[name="pm-build"]')?.content || "";

(function ensureFreshPreMatchBuild() {
  if (!PRE_MATCH_BUILD) return;
  const script = document.querySelector('script[src*="pre-match"]');
  const src = script?.getAttribute("src") || "";
  if (src.includes("/static/pre-match.js")) {
    const bar = document.createElement("div");
    bar.setAttribute("role", "alert");
    bar.style.cssText = "position:fixed;inset:0 auto auto 0;right:0;z-index:99999;padding:.65rem 1rem;background:#b91c1c;color:#fff;font:700 .85rem/1.3 system-ui;text-align:center";
    bar.innerHTML = 'Outdated bookmark — loading latest… <a href="/pre-match" style="color:#fff;text-decoration:underline">Open /pre-match</a>';
    document.body?.prepend(bar);
    window.location.replace("/pre-match");
    return;
  }
  const prev = sessionStorage.getItem("pm-build");
  if (prev && prev !== PRE_MATCH_BUILD) {
    sessionStorage.setItem("pm-build", PRE_MATCH_BUILD);
    window.location.reload();
    return;
  }
  sessionStorage.setItem("pm-build", PRE_MATCH_BUILD);
})();

const state = {
  meta: null,
  fixtures: [],
  report: null,
  loading: false,
  slideIndex: 0,
  slides: [],
};

const els = {
  app: document.getElementById("pmApp"),
  iterationId: document.getElementById("iterationId"),
  opponentId: document.getElementById("opponentId"),
  matchId: document.getElementById("matchId"),
  seasonToggle: document.getElementById("seasonToggle"),
  matchBar: document.getElementById("matchBar"),
  matchBarWrap: document.getElementById("matchBarWrap"),
  deck: document.getElementById("deck"),
  deckViewport: document.getElementById("deckViewport"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportPngsBtn: document.getElementById("exportPngsBtn"),
  exportWhatsappPdfBtn: document.getElementById("exportWhatsappPdfBtn"),
  prevSlideBtn: document.getElementById("prevSlideBtn"),
  nextSlideBtn: document.getElementById("nextSlideBtn"),
  slideCounter: document.getElementById("slideCounter"),
};

const SLIDE_EXPORT_WIDTH = 1920;
const SLIDE_EXPORT_HEIGHT = 1080;
const SLIDE_EXPORT_SCALE = 2;
/* Full Keynote frame in the WhatsApp PDF — no soft 720p downscale. */
const WHATSAPP_EXPORT_WIDTH = 1920;
const WHATSAPP_EXPORT_HEIGHT = 1080;
const WHATSAPP_JPEG_QUALITY = 0.93;
const WHATSAPP_CAPTURE_SCALE = 2;

function waitForExportImages(root, timeoutMs = 6000) {
  const images = [...(root?.querySelectorAll?.("img") || [])];
  if (!images.length) return Promise.resolve();
  return Promise.all(
    images.map(
      (image) =>
        new Promise((resolve) => {
          if (image.complete && image.naturalWidth > 0) {
            resolve();
            return;
          }
          const timer = window.setTimeout(resolve, timeoutMs);
          const done = () => {
            window.clearTimeout(timer);
            resolve();
          };
          image.addEventListener("load", done, { once: true });
          image.addEventListener("error", done, { once: true });
        }),
    ),
  );
}

function prepareExportClone(slide, width, height) {
  const clone = slide.cloneNode(true);
  clone.classList.add("pm-slide--export-capture", "pm-slide--active");
  clone.classList.remove("pm-slide--exporting");
  clone.style.setProperty("--pm-export-w", `${width}px`);
  clone.style.setProperty("--pm-export-h", `${height}px`);
  clone.style.setProperty("--slide-width", `${width}px`);
  clone.style.setProperty("width", `${width}px`, "important");
  clone.style.setProperty("max-width", `${width}px`, "important");
  clone.style.setProperty("height", `${height}px`, "important");
  clone.style.setProperty("min-height", `${height}px`, "important");
  clone.style.setProperty("max-height", `${height}px`, "important");
  clone.style.setProperty("aspect-ratio", "auto", "important");
  clone.style.borderRadius = "0";
  clone.style.boxShadow = "none";
  clone.style.outline = "none";
  clone.style.overflow = "hidden";
  clone.style.margin = "0";
  clone.style.transform = "none";
  return clone;
}

function downscaleCanvas(source, width, height, fillStyle = "#ffffff") {
  if (source.width === width && source.height === height) return source;
  const out = document.createElement("canvas");
  out.width = width;
  out.height = height;
  const ctx = out.getContext("2d");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.fillStyle = fillStyle;
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(source, 0, 0, width, height);
  return out;
}

async function capturePreMatchSlides(options = {}) {
  const layoutWidth = options.layoutWidth ?? options.width ?? SLIDE_EXPORT_WIDTH;
  const layoutHeight = options.layoutHeight ?? options.height ?? SLIDE_EXPORT_HEIGHT;
  const outputWidth = options.width ?? layoutWidth;
  const outputHeight = options.height ?? layoutHeight;
  const scale = options.scale ?? SLIDE_EXPORT_SCALE;
  const mimeType = options.mimeType ?? "image/png";
  const quality = options.quality ?? 0.92;
  const slides = [...els.deck.querySelectorAll(".pm-slide")];
  if (!slides.length) throw new Error("Load a report before exporting.");
  if (typeof html2canvas !== "function") {
    throw new Error("Export unavailable — reload the page.");
  }

  if (document.fonts?.ready) {
    try {
      await document.fonts.ready;
    } catch {
      /* ignore font readiness errors */
    }
  }

  els.app?.classList.add("pm-app--exporting");
  const pages = [];
  const previousIndex = state.slideIndex;

  const host = document.createElement("div");
  host.className = "pm-export-host";
  host.style.width = `${layoutWidth}px`;
  host.style.height = `${layoutHeight}px`;
  document.body.appendChild(host);

  try {
    for (let index = 0; index < slides.length; index += 1) {
      const slide = slides[index];
      highlightSlide(index);
      // Let the live slide settle (pitch markers, photos) before cloning.
      slide.scrollIntoView({ behavior: "instant", block: "nearest" });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

      const isDarkSlide = slide.classList.contains("pm-slide--team-style");
      const backgroundColor = isDarkSlide ? "#0f1115" : "#ffffff";

      host.replaceChildren();
      const clone = prepareExportClone(slide, layoutWidth, layoutHeight);
      host.appendChild(clone);
      warmDeckPhotos(clone);
      await waitForExportImages(clone, slide.classList.contains("pm-slide--rankings") ? 10000 : 6000);
      // Force layout at the export frame size before measuring.
      void clone.offsetWidth;
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      // Extra beat so late paint (fonts, badges, pitch markers) settles.
      await new Promise((resolve) => window.setTimeout(resolve, 60));

      const canvas = await html2canvas(clone, {
        backgroundColor,
        scale,
        useCORS: true,
        allowTaint: false,
        logging: false,
        foreignObjectRendering: false,
        width: layoutWidth,
        height: layoutHeight,
        windowWidth: layoutWidth,
        windowHeight: layoutHeight,
      });

      const framed = downscaleCanvas(canvas, outputWidth, outputHeight, backgroundColor);
      const title = slugifyExportPart(slide.dataset.slideTitle || `slide-${index + 1}`);
      pages.push({
        imageData: framed.toDataURL(mimeType, quality),
        filename: `${title}.${mimeType === "image/jpeg" ? "jpg" : "png"}`,
        width: framed.width,
        height: framed.height,
      });
      const label = options.progressLabel || "Exporting";
      setStatus(`${label}… ${index + 1}/${slides.length}`, "loading");
    }
  } finally {
    host.remove();
    els.app?.classList.remove("pm-app--exporting");
    highlightSlide(previousIndex);
  }

  return pages;
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `pm-status pm-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

function ordinalSuffix(value) {
  const mod100 = value % 100;
  if (mod100 >= 11 && mod100 <= 13) return "th";
  return { 1: "st", 2: "nd", 3: "rd" }[value % 10] || "th";
}

function formatLeaguePosition(position) {
  if (!position) return "—";
  return `${position}${ordinalSuffix(position)}`.toUpperCase();
}

function formatMatchDate(iso) {
  if (!iso) return "—";
  const text = String(iso).trim();
  const dayOnly = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (dayOnly && text.length <= 10) {
    const date = new Date(Number(dayOnly[1]), Number(dayOnly[2]) - 1, Number(dayOnly[3]));
    return date.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Europe/London",
  });
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    cache: "no-store",
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

function crestUrl(team) {
  if (team?.badge_url) return team.badge_url;
  const name = String(team?.name || "").toLowerCase();
  if (name.includes("port vale")) return "/standalone/port-vale-badge.png?v=2";
  return team?.image_url || team?.imageUrl || "";
}

function crestInitials(name) {
  return String(name || "?")
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function crestHtml(team, className = "pm-match-bar__crest") {
  const name = team?.name || "?";
  const src = crestUrl(team);
  const initials = crestInitials(name);
  if (src) {
    return `<img class="${className}" src="${escapeHtml(src)}" alt="${escapeHtml(name)}" onerror="this.onerror=null;this.replaceWith(Object.assign(document.createElement('div'),{className:'pm-match-bar__crest-fallback',textContent:'${escapeHtml(initials)}'}))" />`;
  }
  return `<div class="pm-match-bar__crest-fallback">${escapeHtml(initials)}</div>`;
}

function renderSeasonToggle() {
  const iterations = state.meta?.iterations || [];
  els.seasonToggle.innerHTML = iterations
    .map((iteration) => {
      const active = Number(iteration.id) === Number(els.iterationId.value);
      const label = iteration.season || iteration.label || "Season";
      const isCurrent = iterations[0]?.id === iteration.id;
      const buttonLabel = isCurrent ? `This season (${label})` : `Last season (${label})`;
      return `<button type="button" class="pm-season-btn${active ? " pm-season-btn--active" : ""}" data-iteration-id="${iteration.id}"${state.loading ? " disabled" : ""}>${buttonLabel}</button>`;
    })
    .join("");

  els.seasonToggle.querySelectorAll(".pm-season-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled || btn.classList.contains("pm-season-btn--active")) return;
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
    const data = await fetchJson(`/api/pre-match/fixtures?iteration_id=${iterationId}`);
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
        Number(row.opponent.id) === Number(preferred.opponent_id),
    );
    if (fromMeta) return fromMeta;
  }
  for (const name of state.meta?.default_opponent_names || []) {
    const hit = state.fixtures.find((row) => row.opponent.name === name);
    if (hit) return hit;
  }
  const withMatchId = state.fixtures.filter((row) => row.match_id);
  return withMatchId[withMatchId.length - 1] || state.fixtures[0];
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
      return `<button type="button" class="pm-match-bar__item${active ? " pm-match-bar__item--active" : ""}" data-match-id="${fixture.match_id}" data-opponent-id="${fixture.opponent.id}" title="${title}">
        ${crestHtml(fixture.opponent)}
        <span class="pm-match-bar__kickoff">${fixture.kickoff_label || "vs"}</span>
      </button>`;
    })
    .join("");

  els.matchBar.querySelectorAll(".pm-match-bar__item").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.matchId.value = btn.dataset.matchId;
      els.opponentId.value = btn.dataset.opponentId;
      loadReport();
    });
  });

  const activeEl = els.matchBar.querySelector(".pm-match-bar__item--active");
  if (activeEl) {
    activeEl.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }
}

function crestHtmlLarge(team, className = "pm-intro__crest-img") {
  const name = team?.name || "?";
  const src = crestUrl(team);
  const initials = crestInitials(name);
  if (src) {
    const fallbackClass = `${className} pm-intro__crest-fallback`;
    return `<img class="${className}" src="${escapeHtml(src)}" alt="${escapeHtml(name)}" onerror="this.onerror=null;this.replaceWith(Object.assign(document.createElement('div'),{className:'${fallbackClass}',textContent:'${escapeHtml(initials)}'}))" />`;
  }
  return `<div class="${className} pm-intro__crest-fallback">${escapeHtml(initials)}</div>`;
}

function renderIntroSlide(report) {
  const fixture = report.fixture || {};
  const portVale = fixture.port_vale || { name: "Port Vale" };
  const opponent = fixture.opponent || report.opponent || { name: "Opponent" };
  const fixtureLine = fixture.fixture_line || `${portVale.name} vs ${opponent.name}`;
  const dateParts = [fixture.date_label, fixture.time_label].filter(Boolean);
  const dateLine = dateParts.join(" · ");
  const venueLine = [fixture.competition_line, fixture.venue].filter(Boolean).join(" · ");

  return `<section class="pm-slide pm-slide--intro" data-slide-title="Pre-match">
    <div class="pm-intro__corner pm-intro__corner--left"></div>
    <div class="pm-intro__corner pm-intro__corner--right"></div>
    <div class="pm-intro__body">
      <div class="pm-intro__matchup">
        <div class="pm-intro__team">
          ${crestHtmlLarge(portVale)}
          <p class="pm-intro__team-name">${portVale.name || "Port Vale"}</p>
        </div>
        <div class="pm-intro__centre">
          <p class="pm-intro__vs">vs</p>
          <p class="pm-intro__fixture">${fixtureLine}</p>
        </div>
        <div class="pm-intro__team">
          ${crestHtmlLarge(opponent)}
          <p class="pm-intro__team-name">${opponent.name || "Opponent"}</p>
        </div>
      </div>
      ${dateLine ? `<p class="pm-intro__date">${dateLine}</p>` : ""}
      ${venueLine ? `<p class="pm-intro__meta">${venueLine}</p>` : ""}
    </div>
    <div class="pm-intro__footer">DATA PRE MATCH</div>
  </section>`;
}

function playerSurname(name) {
  const parts = String(name || "").trim().split(/\s+/);
  return parts[parts.length - 1] || name;
}

function pitchLabelText(player) {
  const surname = player.short_name || playerSurname(player.name);
  const number = player.shirt_number;
  const label = number != null && number !== "" ? `${number} ${surname}` : surname;
  if (label.length <= 12) return label;
  return `${label.slice(0, 11)}…`;
}

function pitchShapeStorageKey(report = state.report) {
  const iterationId = report?.iteration_id ?? Number(els.iterationId?.value || 0);
  const squadId = report?.opponent?.id ?? report?.squad_id ?? Number(els.opponentId?.value || 0);
  return `pm-pitch-shape:${iterationId}:${squadId}`;
}

function pitchXiStorageKey(report = state.report) {
  const iterationId = report?.iteration_id ?? Number(els.iterationId?.value || 0);
  const squadId = report?.opponent?.id ?? report?.squad_id ?? Number(els.opponentId?.value || 0);
  return `pm-pitch-xi:${iterationId}:${squadId}`;
}

function availabilityStorageKey(report = state.report) {
  const iterationId = report?.iteration_id ?? Number(els.iterationId?.value || 0);
  const squadId = report?.opponent?.id ?? report?.squad_id ?? Number(els.opponentId?.value || 0);
  return `pm-squad-availability:${iterationId}:${squadId}`;
}

function footStorageKey(report = state.report) {
  const iterationId = report?.iteration_id ?? Number(els.iterationId?.value || 0);
  const squadId = report?.opponent?.id ?? report?.squad_id ?? Number(els.opponentId?.value || 0);
  return `pm-squad-foot:${iterationId}:${squadId}`;
}

const AVAILABILITY_CYCLE = ["available", "injured", "suspended", "international"];

const AVAILABILITY_META = {
  available: { label: "Available", short: "" },
  injured: { label: "Injured", short: "INJ" },
  suspended: { label: "Suspended", short: "SUS" },
  international: { label: "International duty", short: "INT" },
};

function loadAvailability(report = state.report) {
  try {
    const raw = localStorage.getItem(availabilityStorageKey(report));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveAvailability(map, report = state.report) {
  try {
    localStorage.setItem(availabilityStorageKey(report), JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

function playerAvailability(playerId, report = state.report) {
  const key = String(playerId ?? "");
  if (!key) return "available";
  const status = loadAvailability(report)[key];
  return AVAILABILITY_CYCLE.includes(status) ? status : "available";
}

function nextAvailability(status) {
  const index = AVAILABILITY_CYCLE.indexOf(status);
  const current = index >= 0 ? index : 0;
  return AVAILABILITY_CYCLE[(current + 1) % AVAILABILITY_CYCLE.length];
}

function loadFootOverrides(report = state.report) {
  try {
    const raw = localStorage.getItem(footStorageKey(report));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveFootOverrides(map, report = state.report) {
  try {
    localStorage.setItem(footStorageKey(report), JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

function playerFoot(foot, playerId, report = state.report) {
  const key = String(playerId ?? "");
  if (key) {
    const override = loadFootOverrides(report)[key];
    if (override === "L" || override === "R") return override;
  }
  return shortFoot(foot);
}

function toggleFoot(code) {
  return code === "L" ? "R" : "L";
}

function availabilityIconHtml(status) {
  if (status === "injured") {
    return `<span class="squad-roster__icon squad-roster__icon--injured" aria-hidden="true" title="Injured">
      <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
        <path fill="currentColor" d="M6.2 1.4h3.6c.5 0 .9.4.9.9v3h3c.5 0 .9.4.9.9v3.6c0 .5-.4.9-.9.9h-3v3c0 .5-.4.9-.9.9H6.2c-.5 0-.9-.4-.9-.9v-3h-3c-.5 0-.9-.4-.9-.9V6.2c0-.5.4-.9.9-.9h3v-3c0-.5.4-.9.9-.9z"/>
      </svg>
    </span>`;
  }
  if (status === "suspended") {
    return `<span class="squad-roster__icon squad-roster__icon--suspended" aria-hidden="true" title="Suspended">
      <span class="squad-roster__redcard"></span>
    </span>`;
  }
  if (status === "international") {
    return `<span class="squad-roster__icon squad-roster__icon--international" aria-hidden="true" title="International duty">
      <svg viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M1.2 8.4l5.1-.7L9.1 2l1.3.4-1.4 4.8 3.7.5 1.3-1.6.9.3-1 2.2 1 2.2-.9.3-1.3-1.6-3.7.5 1.4 4.8-1.3.4-2.8-5.7-5.1-.7.2-1.3z"/></svg>
    </span>`;
  }
  return "";
}

function loadPitchShape(report = state.report) {
  try {
    const raw = localStorage.getItem(pitchShapeStorageKey(report));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function savePitchShape(shape, report = state.report) {
  try {
    localStorage.setItem(pitchShapeStorageKey(report), JSON.stringify(shape));
  } catch {
    /* ignore */
  }
}

function clearPitchShape(report = state.report) {
  try {
    localStorage.removeItem(pitchShapeStorageKey(report));
  } catch {
    /* ignore */
  }
}

function loadPitchXi(report = state.report) {
  try {
    const raw = localStorage.getItem(pitchXiStorageKey(report));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function savePitchXi(xi, report = state.report) {
  try {
    localStorage.setItem(pitchXiStorageKey(report), JSON.stringify(xi));
  } catch {
    /* ignore */
  }
}

function clearPitchXi(report = state.report) {
  try {
    localStorage.removeItem(pitchXiStorageKey(report));
  } catch {
    /* ignore */
  }
}

function opponentPhotoUrl(name, report = state.report) {
  if (!name) return null;
  const params = new URLSearchParams({ name });
  if (report?.opponent?.name) params.set("club", report.opponent.name);
  if (report?.season) params.set("season", String(report.season));
  return `/api/pre-match/player-photo?${params.toString()}`;
}

function playerPhotoUrl(player, report = state.report) {
  return player?.photo_url || opponentPhotoUrl(player?.name, report);
}

function warmDeckPhotos(root = els.deck) {
  if (!root) return;
  root.querySelectorAll(".squad-marker__photo, .pm-rank-row__photo").forEach((node) => {
    if (!(node instanceof HTMLImageElement)) return;
    node.loading = "eager";
    const src = node.getAttribute("src");
    if (!src) return;
    // Lazy load inside overflow:hidden slides often never fires — retry once if blank.
    if (node.complete && node.naturalWidth === 0) {
      node.removeAttribute("src");
      node.src = src;
    }
  });
}

function findSquadPlayer(playerId, report = state.report) {
  const id = Number(playerId);
  return (report?.squad || []).find((row) => Number(row.id) === id) || null;
}

function applyPitchShapeOverrides(players, report = state.report) {
  const shape = loadPitchShape(report);
  return (players || []).map((player) => {
    const key = String(player.player_id ?? player.name ?? "");
    const override = shape[key];
    if (!override) return player;
    const x = Number(override.x);
    const y = Number(override.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return player;
    return { ...player, x_pct: x, y_pct: y, shape_override: true };
  });
}

function applyPitchXiOverrides(players, report = state.report) {
  const xi = loadPitchXi(report);
  const next = (players || []).map((player) => ({ ...player }));
  const entries = Object.entries(xi)
    .map(([slotKey, replacementId]) => [Number(slotKey), Number(replacementId)])
    .filter(([index, id]) => Number.isInteger(index) && index >= 0 && Number.isFinite(id));

  for (const [index, replacementId] of entries) {
    if (index >= next.length) continue;
    const squadPlayer = findSquadPlayer(replacementId, report);
    if (!squadPlayer) continue;

    const existingIndex = next.findIndex(
      (player, i) => i !== index && Number(player.player_id) === Number(squadPlayer.id),
    );
    const displaced = { ...next[index] };
    const incoming = {
      ...displaced,
      player_id: Number(squadPlayer.id),
      name: squadPlayer.name,
      short_name: playerSurname(squadPlayer.name),
      position: squadPlayer.position_code || squadPlayer.position || displaced.position,
      band: squadPlayer.band || displaced.band,
      shirt_number: squadPlayer.shirt_number ?? displaced.shirt_number,
      photo_url: opponentPhotoUrl(squadPlayer.name, report),
      xi_override: true,
    };

    // Exchange if the chosen player is already on the pitch — never drop below 11.
    if (existingIndex >= 0) {
      next[existingIndex] = {
        ...next[existingIndex],
        player_id: displaced.player_id,
        name: displaced.name,
        short_name: displaced.short_name || playerSurname(displaced.name),
        position: displaced.position,
        band: displaced.band,
        shirt_number: displaced.shirt_number,
        photo_url: displaced.photo_url || opponentPhotoUrl(displaced.name, report),
        xi_override: true,
      };
    }
    next[index] = incoming;
  }
  return next;
}

function formatKeyStatParts(stat) {
  if (stat?.value == null || Number.isNaN(Number(stat.value))) {
    return { value: "—", rank: "" };
  }
  const value = Number(stat.value);
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(2);
  return { value: formatted, rank: stat.rank || "" };
}

function parseRankNumber(rankLabel) {
  const match = String(rankLabel || "").match(/(\d+)/);
  return match ? Number(match[1]) : null;
}

function keyStatBarPct(stat, leagueSize) {
  const rank = parseRankNumber(stat?.rank);
  const size = Number(leagueSize) || 24;
  if (!rank || rank < 1) return 35;
  // 1st = full bar, last = short stub (same for both higher/lower better ranks).
  return Math.max(10, Math.round(((size - rank + 1) / size) * 100));
}

function keyStatRowsHtml(stats, leagueSize = 24) {
  return (stats || [])
    .map((stat) => {
      const parts = formatKeyStatParts(stat);
      const pct = keyStatBarPct(stat, leagueSize);
      const tone = stat.higher_better === false ? "danger" : "good";
      const rankNum = parseRankNumber(parts.rank);
      const size = Number(leagueSize) || 24;
      const elite = rankNum != null && rankNum <= Math.max(3, Math.round(size / 8));
      const rowClass = [
        "squad-key-stats__row",
        `squad-key-stats__row--${tone}`,
        elite ? "squad-key-stats__row--elite" : "",
      ]
        .filter(Boolean)
        .join(" ");
      return `<div class="${rowClass}">
        <div class="squad-key-stats__top">
          <span class="squad-key-stats__label">${escapeHtml(stat.label || "")}</span>
          ${parts.rank ? `<span class="squad-key-stats__rank">${escapeHtml(parts.rank)}</span>` : ""}
        </div>
        <div class="squad-key-stats__mid">
          <span class="squad-key-stats__value">${parts.value}</span>
          <div class="squad-key-stats__track" aria-hidden="true">
            <span class="squad-key-stats__bar squad-key-stats__bar--${tone}" style="width:${pct}%"></span>
          </div>
        </div>
      </div>`;
    })
    .join("");
}

function pitchMarkersHtml(players) {
  return (players || [])
    .map((player, index) => {
      const left = Number(player.x_pct ?? 50);
      const top = Number(player.y_pct ?? 50);
      const label = pitchLabelText(player);
      const markerKey = player.player_id ?? player.name ?? index;
      const status = playerAvailability(player.player_id);
      const statusClass = status !== "available" ? ` squad-marker--${status}` : "";
      const badge = availabilityIconHtml(status);
      const shirt =
        player.shirt_number != null && player.shirt_number !== ""
          ? String(player.shirt_number)
          : "";
      const photoUrl = playerPhotoUrl(player);
      const fallback = `<span class="squad-marker__dot${photoUrl ? " squad-marker__dot--fallback" : ""}" aria-hidden="true">${escapeHtml(shirt || "?")}</span>`;
      const photo = photoUrl
        ? `<img class="squad-marker__photo" src="${escapeHtml(photoUrl)}" alt="" loading="eager" decoding="async" draggable="false" onerror="this.style.display='none';var d=this.nextElementSibling;if(d){d.style.display='flex'}" />
           ${fallback}`
        : fallback;
      return `<div class="squad-marker${statusClass}" data-slot-index="${index}" data-marker-key="${markerKey}" data-player-id="${player.player_id ?? ""}" style="left:${left}%;top:${top}%;z-index:${index + 1}" title="${player.name}${status !== "available" ? ` · ${AVAILABILITY_META[status].label}` : ""}">
        <span class="squad-marker__head">
          ${photo}
          ${badge ? `<span class="squad-marker__status">${badge}</span>` : ""}
        </span>
        <span class="squad-marker__label">${label}</span>
      </div>`;
    })
    .join("");
}

function ensurePitchResetButton(toolbar) {
  if (!toolbar || toolbar.querySelector("[data-pitch-reset]")) return;
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "squad-pitch__reset";
  reset.dataset.pitchReset = "";
  reset.textContent = "Reset";
  reset.addEventListener("click", (event) => {
    event.preventDefault();
    clearPitchShape();
    clearPitchXi();
    if (state.report) {
      rebuildSlides();
      paintDeck();
      highlightSlide(state.slideIndex);
    }
  });
  toolbar.appendChild(reset);
}

function bindPitchInteractions(root = document) {
  const slide = root.querySelector(".pm-slide--squad-list");
  if (!slide || slide.dataset.pitchUi === "1") return;
  slide.dataset.pitchUi = "1";

  const layer = slide.querySelector(".squad-pitch__players");
  const roster = slide.querySelector(".squad-roster");
  const toolbar = slide.querySelector(".squad-pitch__toolbar");
  if (!layer) return;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  let selectedMarker = null;

  const setSelected = (marker) => {
    layer.querySelectorAll(".squad-marker--selected").forEach((node) => {
      node.classList.remove("squad-marker--selected");
    });
    selectedMarker = marker;
    if (marker) marker.classList.add("squad-marker--selected");
    slide.classList.toggle("squad-list--picking", Boolean(marker));
  };

  layer.querySelectorAll(".squad-marker").forEach((marker) => {
    marker.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();

      const pointerId = event.pointerId;
      const startX = event.clientX;
      const startY = event.clientY;
      let dragging = false;
      const rect = layer.getBoundingClientRect();

      const onMove = (moveEvent) => {
        if (moveEvent.pointerId !== pointerId) return;
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (!dragging && dx * dx + dy * dy < 25) return;
        if (!dragging) {
          dragging = true;
          marker.classList.add("squad-marker--dragging");
          try {
            marker.setPointerCapture(pointerId);
          } catch {
            /* ignore */
          }
        }
        const width = rect.width || 1;
        const height = rect.height || 1;
        const x = clamp(((moveEvent.clientX - rect.left) / width) * 100, 4, 96);
        const y = clamp(((moveEvent.clientY - rect.top) / height) * 100, 4, 96);
        marker.style.left = `${x}%`;
        marker.style.top = `${y}%`;
        marker.dataset.xPct = String(x);
        marker.dataset.yPct = String(y);
      };

      const onUp = (upEvent) => {
        if (upEvent.pointerId !== pointerId) return;
        document.removeEventListener("pointermove", onMove, true);
        document.removeEventListener("pointerup", onUp, true);
        document.removeEventListener("pointercancel", onUp, true);
        marker.classList.remove("squad-marker--dragging");
        try {
          marker.releasePointerCapture(pointerId);
        } catch {
          /* ignore */
        }

        if (dragging) {
          const key = marker.dataset.markerKey;
          const x = Number(marker.dataset.xPct);
          const y = Number(marker.dataset.yPct);
          if (key && Number.isFinite(x) && Number.isFinite(y)) {
            const shape = loadPitchShape();
            shape[key] = { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
            savePitchShape(shape);
            ensurePitchResetButton(toolbar);
          }
          return;
        }

        setSelected(selectedMarker === marker ? null : marker);
      };

      document.addEventListener("pointermove", onMove, true);
      document.addEventListener("pointerup", onUp, true);
      document.addEventListener("pointercancel", onUp, true);
    });
  });

  roster?.querySelectorAll(".squad-roster__player").forEach((row) => {
    row.addEventListener("click", (event) => {
      event.preventDefault();
      const playerId = row.dataset.playerId;
      const squadPlayer = findSquadPlayer(playerId);
      if (!squadPlayer) return;

      // No pitch headshot selected → cycle availability (inj / sus / int).
      if (!selectedMarker) {
        const map = loadAvailability();
        const key = String(playerId);
        const next = nextAvailability(playerAvailability(playerId));
        if (next === "available") delete map[key];
        else map[key] = next;
        saveAvailability(map);
        if (state.report) {
          const keepIndex = state.slideIndex;
          rebuildSlides();
          paintDeck();
          highlightSlide(keepIndex);
        }
        const label = AVAILABILITY_META[next]?.label || "Available";
        setStatus(`${squadPlayer.name}: ${label}. Click again to cycle.`, next === "available" ? "" : "loading");
        return;
      }

      const slotIndex = selectedMarker.dataset.slotIndex;
      const xi = loadPitchXi();
      const incomingId = Number(playerId);
      // If already on the pitch, swap the two XI slots so the map stays unique.
      const existingSlot = Object.entries(xi).find(
        ([key, id]) => key !== String(slotIndex) && Number(id) === incomingId,
      );
      if (existingSlot) {
        const outgoingId = Number(selectedMarker.dataset.playerId);
        if (Number.isFinite(outgoingId)) {
          xi[existingSlot[0]] = outgoingId;
        } else {
          delete xi[existingSlot[0]];
        }
      } else {
        const markers = [...(layer.querySelectorAll(".squad-marker") || [])];
        const duplicateMarker = markers.find(
          (marker) =>
            marker !== selectedMarker && Number(marker.dataset.playerId) === incomingId,
        );
        if (duplicateMarker) {
          const outgoingId = Number(selectedMarker.dataset.playerId);
          const otherSlot = duplicateMarker.dataset.slotIndex;
          if (otherSlot != null && Number.isFinite(outgoingId)) {
            xi[String(otherSlot)] = outgoingId;
          }
        }
      }
      xi[String(slotIndex)] = incomingId;
      savePitchXi(xi);

      const oldKey = selectedMarker.dataset.markerKey;
      const shape = loadPitchShape();
      if (oldKey && shape[oldKey]) {
        const nextKey = String(playerId);
        shape[nextKey] = shape[oldKey];
        if (nextKey !== oldKey) delete shape[oldKey];
        savePitchShape(shape);
      }

      ensurePitchResetButton(toolbar);
      setStatus("");
      if (state.report) {
        const keepIndex = state.slideIndex;
        rebuildSlides();
        paintDeck();
        highlightSlide(keepIndex);
      }
    });
  });

  slide.querySelectorAll("[data-pitch-reset]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      clearPitchShape();
      clearPitchXi();
      if (state.report) {
        rebuildSlides();
        paintDeck();
        highlightSlide(state.slideIndex);
      }
    });
  });

  slide.addEventListener("click", (event) => {
    if (event.target.closest(".squad-marker") || event.target.closest(".squad-roster__player")) return;
    setSelected(null);
  });
}

function updateFootToggleButton(button, code) {
  button.dataset.foot = code;
  button.textContent = code;
  button.classList.remove("pm-data-foot--left", "pm-data-foot--right", "pm-data-foot--muted");
  if (code === "L") {
    button.classList.add("pm-data-foot--left");
    button.title = "Left footed · click to toggle";
  } else if (code === "R") {
    button.classList.add("pm-data-foot--right");
    button.title = "Right footed · click to toggle";
  } else {
    button.classList.add("pm-data-foot--muted");
    button.title = "Footedness unknown · click to toggle";
  }
}

function bindSquadDataInteractions(root = els.deck) {
  root.querySelectorAll("[data-foot-toggle]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const playerId = button.dataset.playerId;
      if (!playerId) return;
      const next = toggleFoot(button.dataset.foot || "R");
      const map = loadFootOverrides();
      map[playerId] = next;
      saveFootOverrides(map);
      updateFootToggleButton(button, next);
    });
  });
}

function squadGroupsHtml(groups, pitchNames) {
  const onPitch = pitchNames instanceof Set ? pitchNames : new Set(pitchNames || []);
  return (groups || [])
    .map((group) => {
      const players = (group.players || [])
        .map((player) => {
          const onPitchNow = onPitch.has(player.name) || onPitch.has(String(player.id));
          const isOn = Boolean(player.on_pitch) || onPitchNow;
          const status = playerAvailability(player.id);
          const classes = [
            "squad-roster__player",
            isOn ? "squad-roster__player--xi" : "squad-roster__player--squad",
            status !== "available" ? `squad-roster__player--${status}` : "",
          ]
            .filter(Boolean)
            .join(" ");
          const number =
            player.shirt_number != null && player.shirt_number !== ""
              ? `<span class="squad-roster__number">${player.shirt_number}</span>`
              : `<span class="squad-roster__number squad-roster__number--empty">–</span>`;
          const statusLabel = AVAILABILITY_META[status]?.label || "Available";
          return `<button type="button" class="${classes}" data-player-id="${player.id ?? ""}" data-player-name="${player.name}" data-availability="${status}" title="${escapeHtml(player.name)} · ${statusLabel}. Click to cycle availability.">
            ${number}
            <span class="squad-roster__name">${escapeHtml(player.name)}</span>
            ${availabilityIconHtml(status)}
          </button>`;
        })
        .join("");
      return `<div class="squad-roster__group">
        <div class="squad-roster__heading">${group.label}</div>
        <div class="squad-roster__players">${players}</div>
      </div>`;
    })
    .join("");
}

function ensureElevenPitchPlayers(players, report = state.report) {
  const seen = new Set();
  const unique = [];
  for (const player of players || []) {
    const key = player.player_id ?? player.name;
    if (key == null || key === "" || seen.has(String(key))) continue;
    seen.add(String(key));
    unique.push(player);
  }
  if (unique.length >= 11) return unique.slice(0, 11);

  for (const row of report?.squad || []) {
    if (unique.length >= 11) break;
    const id = row?.id;
    if (id == null || seen.has(String(id))) continue;
    seen.add(String(id));
    const band = row.band || "mid";
    unique.push({
      player_id: Number(id),
      name: row.name,
      short_name: playerSurname(row.name),
      position: row.position_code || row.position || "CENTRAL_MIDFIELD",
      band,
      shirt_number: row.shirt_number,
      x_pct: 50,
      y_pct: band === "gk" ? 94 : band === "def" ? 72 : band === "attack" ? 18 : 46,
      photo_url: opponentPhotoUrl(row.name, report),
      backfill: true,
    });
  }
  return unique.slice(0, 11);
}

function typicalPitchPlayers(squadList, report = state.report) {
  return ensureElevenPitchPlayers(squadList?.pitch_players || [], report).map((player) => ({
    ...player,
    photo_url: player.photo_url || opponentPhotoUrl(player.name, report),
  }));
}

function keyStatsHtml(stats, leagueSize = 24, { limit = 5, variant = "compact" } = {}) {
  const mod = variant === "slide" ? " squad-key-stats--slide" : "";
  // New shape: { in_possession: [...], out_of_possession: [...] }
  if (stats && !Array.isArray(stats) && (stats.in_possession || stats.out_of_possession)) {
    const inRows = keyStatRowsHtml((stats.in_possession || []).slice(0, limit), leagueSize);
    const outRows = keyStatRowsHtml((stats.out_of_possession || []).slice(0, limit), leagueSize);
    if (!inRows && !outRows) return "";
    return `<div class="squad-key-stats${mod}">
      <h4 class="squad-key-stats__title">Key metrics <span>per match · league rank</span></h4>
      <div class="squad-key-stats__columns">
        <div class="squad-key-stats__col">
          <p class="squad-key-stats__col-title">In possession</p>
          <div class="squad-key-stats__list">${inRows}</div>
        </div>
        <div class="squad-key-stats__col">
          <p class="squad-key-stats__col-title">Out of possession</p>
          <div class="squad-key-stats__list">${outRows}</div>
        </div>
      </div>
    </div>`;
  }

  const rows = keyStatRowsHtml((stats || []).slice(0, limit), leagueSize);
  if (!rows) return "";
  return `<div class="squad-key-stats${mod}">
    <h4 class="squad-key-stats__title">Key metrics <span>per match · league rank</span></h4>
    <div class="squad-key-stats__list">${rows}</div>
  </div>`;
}

function formationMetricBox(label, value, options = {}) {
  if (!label || value == null || value === "") return "";
  const kind = String(label).toLowerCase() === "ppg" ? "ppg" : options.kind || "";
  const kindClass = kind ? ` squad-form-metric--${kind}` : "";
  return `<div class="squad-form-metric${kindClass}">
    <strong>${escapeHtml(String(value))}</strong>
    <em>${escapeHtml(label)}</em>
  </div>`;
}

function formationInsightHtml(insights) {
  const rows = (insights || []).slice(0, 4);
  if (!rows.length) return "";
  return `<section class="squad-form-card squad-form-card--intel">
    <header class="squad-form-card__head">
      <h5 class="squad-form-card__title">Gameplan intel</h5>
    </header>
    <div class="squad-form-intel__grid">
      ${rows
        .map((row) => {
          const metric = formationMetricBox(row.metric_label, row.metric_value);
          const title = row.title || "";
          const body = row.body || "";
          const detail = row.detail || "";
          const hasMetric = Boolean(metric);
          const isPpg = String(row.metric_label || "").toLowerCase() === "ppg";
          // Fallback for cached reports that only ship a flat text string
          if (!title && !body && row.text) {
            return `<article class="squad-form-intel__item squad-form-intel__item--${escapeHtml(row.tone || "intel")} squad-form-intel__item--solo">
              <div class="squad-form-intel__copy">
                <span class="squad-form-intel__detail">${escapeHtml(row.text)}</span>
              </div>
            </article>`;
          }
          return `<article class="squad-form-intel__item squad-form-intel__item--${escapeHtml(row.tone || "intel")}${hasMetric ? "" : " squad-form-intel__item--solo"}${isPpg ? " squad-form-intel__item--metric-ppg" : ""}">
            <div class="squad-form-intel__copy">
              ${title ? `<span class="squad-form-intel__kicker">${escapeHtml(title)}</span>` : ""}
              ${body ? `<strong class="squad-form-intel__body">${escapeHtml(body)}</strong>` : ""}
              ${detail ? `<span class="squad-form-intel__detail">${escapeHtml(detail)}</span>` : ""}
            </div>
            ${metric}
          </article>`;
        })
        .join("")}
    </div>
  </section>`;
}

function formationSampleLabel(analysis) {
  const count = analysis?.matches_analysed ?? analysis?.match_sample ?? 0;
  if (!count) return "Season data";
  return `Full season · ${count} games`;
}

function formationWinToneClass(winPct) {
  if (winPct == null) return "";
  if (winPct >= 60) return " squad-form-table__pct--hot";
  if (winPct < 33) return " squad-form-table__pct--cold";
  return "";
}

function formationTableHead(includePpg = true) {
  return `<div class="squad-form-table__head${includePpg ? " squad-form-table__head--ppg" : ""}" aria-hidden="true">
    <span>Shape</span><span>Record</span><span>Win</span>${includePpg ? "<span>PPG</span>" : ""}
  </div>`;
}

function formationWinRowsHtml(results) {
  const rows = (results || [])
    .map((row, index) => {
      const winPct = row.win_pct != null ? Number(row.win_pct) : null;
      const winLabel = winPct != null ? `${winPct}%` : "—";
      const record = `${row.won ?? 0}W-${row.drawn ?? 0}D-${row.lost ?? 0}L`;
      const lead = index === 0 ? " squad-form-table__row--lead" : "";
      const sub =
        row.goals_for_pg != null || row.goals_against_pg != null
          ? `<div class="squad-form-table__sub">${row.goals_for_pg ?? "—"} GF · ${row.goals_against_pg ?? "—"} GA</div>`
          : "";
      return `<div class="squad-form-table__row squad-form-table__row--win${lead}">
        <div class="squad-form-table__line squad-form-table__line--ppg">
          <strong class="squad-form-table__shape">${escapeHtml(row.formation || "—")}</strong>
          <span class="squad-form-table__record">${record}</span>
          <span class="squad-form-table__pct${formationWinToneClass(winPct)}">${winLabel}</span>
          ${formationMetricBox("PPG", row.ppg ?? "—")}
        </div>
        ${sub}
      </div>`;
    })
    .join("");
  if (!rows) return "";
  return `<div class="squad-form-table">${formationTableHead(true)}${rows}</div>`;
}

function formationVsRowsHtml(rows) {
  const body = (rows || [])
    .map((row) => {
      const winPct = row.win_pct != null ? Number(row.win_pct) : null;
      const winLabel = winPct != null ? `${winPct}%` : "—";
      const record = `${row.won ?? 0}W-${row.drawn ?? 0}D-${row.lost ?? 0}L`;
      const vale = row.matches_vale_shape ? " squad-form-table__row--vale" : "";
      return `<div class="squad-form-table__row squad-form-table__row--vs${vale}">
        <div class="squad-form-table__line">
          <strong class="squad-form-table__shape">${escapeHtml(row.opponent_formation || "—")}${row.matches_vale_shape ? `<em class="squad-form-table__tag">Vale</em>` : ""}</strong>
          <span class="squad-form-table__record">${record}</span>
          <span class="squad-form-table__pct${formationWinToneClass(winPct)}">${winLabel}</span>
        </div>
      </div>`;
    })
    .join("");
  if (!body) return "";
  return `<div class="squad-form-table">${formationTableHead(false)}${body}</div>`;
}

function formationShiftHtml(shifts) {
  const rows = (shifts || []).slice(0, 3);
  if (!rows.length) return "";
  return `<div class="squad-form-shifts">
    ${rows
      .map(
        (row) =>
          `<span class="squad-form-shift">${escapeHtml(row.from || "—")} → ${escapeHtml(row.to || "—")} <em>${row.count ?? 0}×</em></span>`,
      )
      .join("")}
  </div>`;
}

function formationAsideHtml(
  analysis,
  { fallbackFormation = "—", leaguePosition = null, manager = null } = {},
) {
  const leagueLabel = formatLeaguePosition(leaguePosition);
  const managerLabel = manager || "—";
  const factsHtml = `<div class="squad-form-aside__facts">
    <span class="squad-form-fact"><em>League</em><strong>${escapeHtml(leagueLabel)}</strong></span>
    <span class="squad-form-fact"><em>Manager</em><strong>${escapeHtml(managerLabel)}</strong></span>
  </div>`;

  if (!analysis?.matches_analysed) {
    const hint =
      fallbackFormation && fallbackFormation !== "—"
        ? `Typical starts: ${fallbackFormation}. Refresh report for full breakdown.`
        : "Refresh report to load formation profile.";
    return `<div class="squad-form-aside squad-form-aside--empty">
      <header class="squad-form-aside__topbar">
        <div class="squad-form-aside__brand">
          <h4 class="squad-form-aside__title">Formation intel</h4>
        </div>
        ${factsHtml}
      </header>
      <p class="squad-form-aside__hint">${escapeHtml(hint)}</p>
    </div>`;
  }

  const usage = analysis.usage || [];
  const primary = usage[0];
  const primaryPct = Math.max(0, Math.min(100, Number(primary?.time_pct) || 0));
  const primaryDeg = (primaryPct / 100) * 360;

  const usageRows = usage
    .map((row, index) => {
      const pct = Math.max(0, Math.min(100, Number(row.time_pct) || 0));
      const rank = index + 1;
      return `<div class="squad-form-row${index === 0 ? " squad-form-row--lead" : ""}">
        <span class="squad-form-row__rank">${rank}</span>
        <div class="squad-form-row__main">
          <span class="squad-form-row__label">${escapeHtml(row.formation || "—")}</span>
          <span class="squad-form-row__bar" aria-hidden="true"><i style="width:${pct}%"></i></span>
        </div>
        <span class="squad-form-row__meta">${pct}%<span>${row.minutes ?? 0}′</span></span>
      </div>`;
    })
    .join("");

  const vsRows = formationVsRowsHtml(analysis.vs_opponent || []);

  const winRows = formationWinRowsHtml(analysis.results_by_shape || []);
  const intelHtml = formationInsightHtml(analysis.insights);
  const shiftsHtml = formationShiftHtml(analysis.in_game_shifts);

  const startsLabel =
    fallbackFormation && fallbackFormation !== "—" ? escapeHtml(fallbackFormation) : "—";

  return `<div class="squad-form-aside">
    <header class="squad-form-aside__topbar">
      <div class="squad-form-aside__brand">
        <h4 class="squad-form-aside__title">Formation intel</h4>
        <span class="squad-form-aside__sample">${escapeHtml(formationSampleLabel(analysis))}</span>
      </div>
      ${factsHtml}
    </header>

    <div class="squad-form-stack">
    ${
      primary
        ? `<article class="squad-form-card squad-form-card--hero">
      <div class="squad-form-hero">
      <div class="squad-form-hero__donut" style="--deg:${primaryDeg}deg" aria-hidden="true">
        <span class="squad-form-hero__pct">${primaryPct}<sup>%</sup></span>
      </div>
      <div class="squad-form-hero__copy">
        <span class="squad-form-hero__eyebrow">Primary shape</span>
        <strong class="squad-form-hero__shape">${escapeHtml(primary.formation || "—")}</strong>
        <span class="squad-form-hero__meta">${primary.minutes ?? 0}′ in shape · ${primary.matches_started ?? 0}/${analysis.matches_analysed ?? 0} starts</span>
      </div>
      </div>
    </article>`
        : ""
    }

    <article class="squad-form-card squad-form-card--kpis">
    <div class="squad-form-aside__kpis">
      <article class="squad-form-kpi">
        <strong class="squad-form-kpi__value">${analysis.phased_pct ?? 0}%</strong>
        <span class="squad-form-kpi__label">Mid-game shape change</span>
      </article>
      <article class="squad-form-kpi">
        <strong class="squad-form-kpi__value">${analysis.phased_matches ?? 0}<span>/${analysis.matches_analysed ?? 0}</span></strong>
        <span class="squad-form-kpi__label">Changed shape</span>
      </article>
      <article class="squad-form-kpi squad-form-kpi--starts">
        <strong class="squad-form-kpi__value squad-form-kpi__value--text">${startsLabel}</strong>
        <span class="squad-form-kpi__label">Typical starts</span>
      </article>
    </div>
    </article>

    ${intelHtml}
    ${
      shiftsHtml
        ? `<article class="squad-form-card squad-form-card--shifts">
        <header class="squad-form-card__head"><h5 class="squad-form-card__title">In-game shifts</h5></header>
        ${shiftsHtml}
      </article>`
        : ""
    }

    <div class="squad-form-aside__split">
      <section class="squad-form-card squad-form-card--panel">
        <header class="squad-form-card__head">
          <h5 class="squad-form-card__title">Win record by start shape</h5>
        </header>
        <div class="squad-form-panel__body squad-form-panel__body--table">
          ${winRows || `<p class="squad-form-aside__empty">No start-shape results.</p>`}
        </div>
      </section>
      ${
        vsRows
          ? `<section class="squad-form-card squad-form-card--panel">
        <header class="squad-form-card__head">
          <h5 class="squad-form-card__title">Vs opponent start shape${analysis.vale_formation ? ` · ${escapeHtml(analysis.vale_formation.split("/")[0].trim())} tagged` : ""}</h5>
        </header>
        <div class="squad-form-panel__body squad-form-panel__body--table">${vsRows}</div>
      </section>`
          : `<section class="squad-form-card squad-form-card--panel squad-form-card--placeholder">
        <header class="squad-form-card__head"><h5 class="squad-form-card__title">Vs opponent start shape</h5></header>
        <div class="squad-form-panel__body"><p class="squad-form-aside__empty">No opponent shape data.</p></div>
      </section>`
      }
    </div>

    <details class="squad-form-card squad-form-card--fold" data-export-hide>
      <summary>Time in shape breakdown</summary>
      <div class="squad-form-panel__body squad-form-panel__body--usage">${usageRows || `<p class="squad-form-aside__empty">No timeline data.</p>`}</div>
    </details>
    </div>
  </div>`;
}

function renderTeamStyleSlide(report) {
  const squadList = report.squad_list || {};
  const opponent = report.opponent?.name || "Opposition";
  const leagueSize = report.overview?.league_table_size;
  const stats = squadList.key_stats;
  const style = report.team_style || {};

  return `<section class="pm-slide pm-slide--team-style" data-slide-title="Team Style & Metrics">
    <div class="pm-slide__header-bar">TEAM STYLE &amp; METRICS</div>
    <div class="pm-slide__subheader">${escapeHtml(opponent)} · season to date · league comparison</div>
    <div class="pm-team-style-body">
      ${teamStyleArchetypesHtml(style)}
      <div class="pm-team-style-main">
        <div class="pm-team-style-radar-panel">
          <header class="pm-team-style-radar-head">
            <h3>League tactical rank</h3>
            <p>How they compare to other ${style.league_size || leagueSize || 24} teams — further out = stronger on that trait.</p>
          </header>
          ${teamStyleRadarSvg(style)}
          ${teamStyleSummaryHtml(style)}
          <div class="pm-team-style-radar-legend">
            <span><i class="pm-team-style-radar-legend__swatch pm-team-style-radar-legend__swatch--team"></i> ${escapeHtml(opponent)}</span>
            <span><i class="pm-team-style-radar-legend__swatch pm-team-style-radar-legend__swatch--league"></i> Mid-table profile</span>
          </div>
          ${style.methodology ? `<p class="pm-team-style-method">${escapeHtml(style.methodology)}</p>` : ""}
        </div>
        <div class="pm-team-style-metrics">
          ${teamStyleMetricsHtml(stats, leagueSize) || `<p class="pm-team-style-empty">No team metrics available.</p>`}
        </div>
      </div>
    </div>
  </section>`;
}

const STYLE_CHIP_STAT_KEYS = {
  possession: ["possession", "direct"],
  heavy_metal: ["pressing", "transition"],
  underdog_press: ["pressing", "transition"],
  direct_aerial: ["direct", "aerial"],
  safety_first: ["pressing", "progression"],
  counter: ["transition", "direct"],
};

function chipHighlights(row, style) {
  if (row.highlights?.length) return row.highlights.slice(0, 2);
  const radar = style?.radar || [];
  const byKey = Object.fromEntries(radar.map((axis) => [axis.key, axis]));
  return (STYLE_CHIP_STAT_KEYS[row.key] || [])
    .slice(0, 2)
    .map((key) => byKey[key])
    .filter(Boolean)
    .map((axis) => ({ label: axis.label, rank_label: axis.rank_label }));
}

function teamStyleChipStatsHtml(highlights) {
  const rows = (highlights || []).slice(0, 2);
  if (!rows.length) return "";
  return `<div class="pm-style-chip__stats">
    ${rows
      .map(
        (row) =>
          `<span class="pm-style-chip__stat">
            <em>${escapeHtml(row.label || "—")}</em>
            <strong>${escapeHtml(row.rank_label || "—")}</strong>
            <i>in L1</i>
          </span>`,
      )
      .join("")}
  </div>`;
}

function teamStyleArchetypesHtml(style) {
  const styles = style?.styles || [];
  if (!styles.length) {
    return `<div class="pm-team-style-archetypes pm-team-style-archetypes--empty">
      <p>Refresh report to load tactical profile.</p>
    </div>`;
  }
  const primaryKey = style.primary_style?.key;
  const cards = styles
    .map((row, index) => {
      const active = row.key === primaryKey || index === 0 ? " pm-style-chip--active" : "";
      const fit = Number(row.fit_pct ?? 0);
      return `<article class="pm-style-chip${active}">
        <div class="pm-style-chip__top">
          <span class="pm-style-chip__fit">${fit.toFixed(1)}<small>%</small></span>
          <span class="pm-style-chip__fit-label">fit</span>
        </div>
        <strong class="pm-style-chip__label">${escapeHtml(row.label || "—")}</strong>
        ${teamStyleChipStatsHtml(chipHighlights(row, style))}
        <span class="pm-style-chip__tag">${escapeHtml(row.tagline || "")}</span>
      </article>`;
    })
    .join("");
  const headline = style.primary_style
    ? `<div class="pm-team-style-archetypes__lead">
        <span class="pm-team-style-archetypes__eyebrow">Tactical resemblance</span>
        <strong>${escapeHtml(style.primary_style.label || "—")}</strong>
        ${style.secondary_style ? `<span>Also close to ${escapeHtml(style.secondary_style.label)} (${style.secondary_style.fit_pct}%)</span>` : ""}
        <span class="pm-team-style-archetypes__note">Approximate match to common profiles — not Impect's official style models.</span>
      </div>`
    : "";
  return `<div class="pm-team-style-archetypes">
    ${headline}
    <div class="pm-team-style-archetypes__strip">${cards}</div>
  </div>`;
}

function teamStyleRadarPoint(index, value, cx, cy, maxR, count) {
  const angle = ((Math.PI * 2 * index) / count) - Math.PI / 2;
  const radius = (Math.max(0, Math.min(100, Number(value) || 0)) / 100) * maxR;
  return {
    x: cx + Math.cos(angle) * radius,
    y: cy + Math.sin(angle) * radius,
  };
}

function teamStyleRadarLabelPoint(index, cx, cy, maxR, count, pad = 16) {
  const angle = ((Math.PI * 2 * index) / count) - Math.PI / 2;
  const radius = maxR + pad;
  return {
    x: cx + Math.cos(angle) * radius,
    y: cy + Math.sin(angle) * radius,
    anchor: Math.abs(Math.cos(angle)) < 0.2 ? "middle" : Math.cos(angle) > 0 ? "start" : "end",
  };
}

function teamStyleRadarSvg(style) {
  const axes = style?.radar || [];
  if (!axes.length) {
    return `<div class="pm-team-style-radar pm-team-style-radar--empty">No radar data.</div>`;
  }
  const count = axes.length;
  const size = 360;
  const cx = size / 2;
  const cy = size / 2;
  const maxR = size * 0.31;
  const rings = [25, 50, 75, 100]
    .map((pct) => {
      const r = (pct / 100) * maxR;
      return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="1" />`;
    })
    .join("");
  const spokes = axes
    .map((_, index) => {
      const pt = teamStyleRadarPoint(index, 100, cx, cy, maxR, count);
      return `<line x1="${cx}" y1="${cy}" x2="${pt.x}" y2="${pt.y}" stroke="rgba(255,255,255,0.16)" stroke-width="1" />`;
    })
    .join("");
  const teamPoly = axes
    .map((axis, index) => {
      const pt = teamStyleRadarPoint(index, axis.value, cx, cy, maxR, count);
      return `${pt.x},${pt.y}`;
    })
    .join(" ");
  const leaguePoly = axes
    .map((axis, index) => {
      const pt = teamStyleRadarPoint(index, axis.league_avg ?? 50, cx, cy, maxR, count);
      return `${pt.x},${pt.y}`;
    })
    .join(" ");
  const labels = axes
    .map((axis, index) => {
      const pt = teamStyleRadarLabelPoint(index, cx, cy, maxR, count, 22);
      const rankLabel = axis.rank_label || "—";
      return `<text x="${pt.x}" y="${pt.y - 4}" text-anchor="${pt.anchor}" dominant-baseline="middle" fill="rgba(255,255,255,0.92)" font-family="Barlow Condensed, sans-serif" font-size="10.5" font-weight="800">${escapeHtml(axis.label || "")}</text>
        <text x="${pt.x}" y="${pt.y + 8}" text-anchor="${pt.anchor}" dominant-baseline="middle" fill="#fbbf24" font-family="Barlow Condensed, sans-serif" font-size="11.5" font-weight="800">${escapeHtml(rankLabel)}</text>`;
    })
    .join("");
  const ringLabels = [25, 50, 75]
    .map((pct) => {
      const r = (pct / 100) * maxR;
      return `<text x="${cx + 4}" y="${cy - r}" fill="rgba(255,255,255,0.35)" font-family="Barlow Condensed, sans-serif" font-size="7" font-weight="700">${pct}</text>`;
    })
    .join("");
  return `<div class="pm-team-style-radar">
    <svg viewBox="0 0 ${size} ${size}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      ${rings}
      ${ringLabels}
      ${spokes}
      <polygon points="${leaguePoly}" fill="rgba(148,163,184,0.08)" stroke="rgba(148,163,184,0.75)" stroke-width="1.6" stroke-dasharray="5 4" />
      <polygon points="${teamPoly}" fill="rgba(245,197,24,0.28)" stroke="#f5c518" stroke-width="2.2" />
      ${axes
        .map((axis, index) => {
          const pt = teamStyleRadarPoint(index, axis.value, cx, cy, maxR, count);
          return `<circle cx="${pt.x}" cy="${pt.y}" r="3.4" fill="#f5c518" stroke="#111" stroke-width="1" />`;
        })
        .join("")}
      ${labels}
    </svg>
  </div>`;
}

function teamStyleSummaryHtml(style) {
  const lines = style?.summary || [];
  if (!lines.length) return "";
  return `<div class="pm-team-style-summary">
    ${lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
  </div>`;
}

function teamStyleMetricCard(title, tone, stats, leagueSize, limit = 5) {
  const rows = (stats || []).slice(0, limit);
  if (!rows.length) return "";
  const body = rows
    .map((stat) => {
      const parts = formatKeyStatParts(stat);
      const rankNum = parseRankNumber(parts.rank);
      const size = Number(leagueSize) || 24;
      const elite = rankNum != null && rankNum <= Math.max(3, Math.round(size / 8));
      return `<article class="pm-ts-metric${elite ? " pm-ts-metric--elite" : ""}">
        <span class="pm-ts-metric__label">${escapeHtml(stat.label || "")}</span>
        <div class="pm-ts-metric__body">
          <strong class="pm-ts-metric__value">${parts.value}</strong>
          ${parts.rank ? `<span class="pm-ts-metric__rank">${escapeHtml(parts.rank)}</span>` : ""}
        </div>
      </article>`;
    })
    .join("");
  return `<section class="pm-ts-metrics-col pm-ts-metrics-col--${tone}">
    <header class="pm-ts-metrics-col__head">${escapeHtml(title)}</header>
    <div class="pm-ts-metrics-col__list">${body}</div>
  </section>`;
}

function teamStyleMetricsHtml(stats, leagueSize) {
  const ip = stats?.in_possession || [];
  const oop = stats?.out_of_possession || [];
  if (!ip.length && !oop.length) return "";
  return `<div class="pm-ts-metrics-grid">
    ${teamStyleMetricCard("In possession", "ip", ip, leagueSize)}
    ${teamStyleMetricCard("Out of possession", "oop", oop, leagueSize)}
  </div>`;
}

function renderSquadListSlide(report) {
  const squadList = report.squad_list || {};
  const opponent = report.opponent?.name || "Opposition";
  let pitchPlayers = typicalPitchPlayers(squadList, report);
  pitchPlayers = applyPitchXiOverrides(pitchPlayers, report);
  pitchPlayers = ensureElevenPitchPlayers(pitchPlayers, report);
  pitchPlayers = applyPitchShapeOverrides(pitchPlayers, report);
  const pitchNames = new Set(
    pitchPlayers.flatMap((player) => [player.name, String(player.player_id ?? "")].filter(Boolean)),
  );
  const squadGroups = squadList.squad_groups || [];
  const hasCustom =
    Object.keys(loadPitchShape(report)).length > 0 || Object.keys(loadPitchXi(report)).length > 0;

  const formation =
    (report.overview?.formations || []).filter(Boolean).join(" / ") || squadList.formation || "—";
  const refNote = squadList.reference_date
    ? `Typical XI · last 8 matches to ${formatMatchDate(squadList.reference_date)}`
    : "Typical XI · last 8 matches";

  return `<section class="pm-slide pm-slide--squad-list" data-slide-title="Squad List">
    <div class="pm-slide__header-bar">SQUAD LIST</div>
    <div class="pm-slide__subheader pm-slide__subheader--crest">${crestHtml(report.opponent, "pm-slide__crest")} <span>${escapeHtml(opponent)}</span></div>
    <div class="squad-list-body">
      <div class="squad-pitch" aria-label="Predicted XI">
        <div class="squad-pitch__banner">
          <span>Predicted XI</span>
          ${formation && formation !== "—" ? `<span class="squad-pitch__banner-shape">${escapeHtml(formation)}</span>` : ""}
        </div>
        <div class="squad-pitch__markings"></div>
        <div class="squad-pitch__players">${pitchMarkersHtml(pitchPlayers)}</div>
        <div class="squad-pitch__toolbar" data-export-hide>
          <span>Drag to move · click headshot then list to swap · click list to mark unavailable</span>
          ${hasCustom ? `<button type="button" class="squad-pitch__reset" data-pitch-reset>Reset</button>` : ""}
        </div>
      </div>
      <div class="squad-roster" aria-label="Squad by position">${squadGroupsHtml(squadGroups, pitchNames)}</div>
      <aside class="squad-aside squad-aside--formations">
        <div class="squad-meta squad-meta--formations">
          ${formationAsideHtml(squadList.formation_analysis, {
            fallbackFormation: formation,
            leaguePosition: squadList.league_position || report.opponent?.league_position,
            manager: squadList.manager || report.overview?.manager,
          })}
          <p class="squad-meta__note" data-export-hide>${refNote}. Click roster names to mark availability.</p>
        </div>
      </aside>
    </div>
  </section>`;
}

function shortFoot(foot) {
  const text = String(foot || "").trim().toLowerCase();
  if (text.startsWith("l")) return "L";
  if (text.startsWith("r")) return "R";
  if (text.startsWith("b") || text.includes("both")) return "B";
  return text ? String(foot).charAt(0).toUpperCase() : "—";
}

function shortPosition(position) {
  const text = String(position || "").trim();
  if (!text || text === "—") return "—";
  const key = text.toLowerCase().replace(/[_-]+/g, " ");
  const map = {
    goalkeeper: "GK",
    "central defender": "CB",
    "centre back": "CB",
    "centre-back": "CB",
    "left back": "LB",
    "left-back": "LB",
    "left wing back": "LWB",
    "right back": "RB",
    "right-back": "RB",
    "right wing back": "RWB",
    "defensive midfield": "DM",
    "central midfield": "CM",
    "attacking midfield": "AM",
    "left midfield": "LM",
    "right midfield": "RM",
    "left winger": "LW",
    "right winger": "RW",
    "center forward": "CF",
    "centre forward": "CF",
    "second striker": "SS",
    striker: "ST",
    forward: "FW",
  };
  if (map[key]) return map[key];
  if (key.includes("goal")) return "GK";
  if (key.includes("wing back") && key.includes("left")) return "LWB";
  if (key.includes("wing back") && key.includes("right")) return "RWB";
  if (key.includes("back") && key.includes("left")) return "LB";
  if (key.includes("back") && key.includes("right")) return "RB";
  if (key.includes("defend")) return "CB";
  if (key.includes("attacking mid")) return "AM";
  if (key.includes("defensive mid")) return "DM";
  if (key.includes("midfield")) return "CM";
  if (key.includes("winger") && key.includes("left")) return "LW";
  if (key.includes("winger") && key.includes("right")) return "RW";
  if (key.includes("striker") || key.includes("forward")) return "CF";
  return text.length > 8 ? `${text.slice(0, 7)}…` : text;
}

function squadPositionBand(player) {
  const band = String(player?.band || "").toLowerCase();
  if (band === "gk" || band === "def" || band === "mid" || band === "attack") return band;
  const pos = shortPosition(player?.position).toUpperCase();
  if (pos === "GK") return "gk";
  if (["CB", "LB", "RB", "LWB", "RWB"].includes(pos)) return "def";
  if (["CF", "ST", "FW", "SS", "LW", "RW"].includes(pos)) return "attack";
  return "mid";
}

function squadLeaderIds(squad, key) {
  let best = -Infinity;
  for (const player of squad || []) {
    const value = Number(player?.[key] || 0);
    if (value > best) best = value;
  }
  if (!Number.isFinite(best) || best <= 0) return new Set();
  return new Set(
    (squad || [])
      .filter((player) => Number(player?.[key] || 0) === best)
      .map((player) => player.id ?? player.name),
  );
}

function footCellHtml(foot, playerId) {
  const code = playerFoot(foot, playerId);
  const classes = ["pm-data-foot", "pm-data-foot--toggle"];
  if (code === "L") classes.push("pm-data-foot--left");
  else if (code === "R") classes.push("pm-data-foot--right");
  else classes.push("pm-data-foot--muted");
  const label = code === "L" ? "Left footed" : code === "R" ? "Right footed" : "Footedness unknown";
  return `<button type="button" class="${classes.join(" ")}" data-foot-toggle data-player-id="${escapeHtml(String(playerId ?? ""))}" data-foot="${escapeHtml(code)}" title="${escapeHtml(label)} · click to toggle">${escapeHtml(code)}</button>`;
}

function renderSquadDataSlide(report) {
  const fixtureDate = formatMatchDate(report.fixture?.scheduled_date);
  const squad = report.squad || [];
  const sub =
    report.fixture?.scheduled_date && fixtureDate !== "—"
      ? `${report.opponent?.name || "Opposition"} · as of ${fixtureDate}`
      : report.opponent?.name || "Opposition";

  const ordered = [...squad].sort(
    (a, b) =>
      Number(b.minutes || 0) - Number(a.minutes || 0) ||
      String(a.name || "").localeCompare(String(b.name || "")),
  );

  const highlights = {
    minutes: squadLeaderIds(squad, "minutes"),
    goals: squadLeaderIds(squad, "goals"),
    assists: squadLeaderIds(squad, "assists"),
  };

  const rows = ordered
    .map((player) => {
      const id = player.id ?? player.name;
      const tags = [];
      if (highlights.minutes.has(id)) tags.push("min");
      if (highlights.goals.has(id)) tags.push("goals");
      if (highlights.assists.has(id)) tags.push("assists");
      const gold = tags.length > 0;
      const titleBits = [];
      if (tags.includes("min")) titleBits.push("Most minutes");
      if (tags.includes("goals")) titleBits.push("Most goals");
      if (tags.includes("assists")) titleBits.push("Most assists");
      const rowClass = gold ? "pm-data-table__row--gold" : "";
      const title = titleBits.length ? ` title="${escapeHtml(titleBits.join(" · "))}"` : "";
      const displayName = String(player.name || "—").toUpperCase();
      return `<tr class="${rowClass}"${title}>
        <td class="pm-data-table__num">${player.shirt_number ?? "—"}</td>
        <td class="pm-data-table__name">${escapeHtml(displayName)}</td>
        <td class="pm-data-table__pos">${escapeHtml(shortPosition(player.position))}</td>
        <td>${player.age ?? "—"}</td>
        <td class="pm-data-table__foot">${footCellHtml(player.foot, id)}</td>
        <td>${player.appearances ?? "—"}</td>
        <td>${player.starts ?? "—"}</td>
        <td class="${tags.includes("min") ? "pm-data-table__stat--gold" : ""}">${player.minutes ?? "—"}</td>
        <td class="${tags.includes("goals") ? "pm-data-table__stat--gold" : ""}">${player.goals ?? "—"}</td>
        <td class="${tags.includes("assists") ? "pm-data-table__stat--gold" : ""}">${player.assists ?? "—"}</td>
      </tr>`;
    })
    .join("");

  const rowCount = Math.max(ordered.length, 1);
  const density = rowCount >= 34 ? "tight" : rowCount >= 28 ? "snug" : "comfy";

  return `<section class="pm-slide pm-slide--data" data-slide-title="Squad Data">
    <div class="pm-slide__header-bar">SQUAD DATA</div>
    <div class="pm-slide__subheader">${escapeHtml(sub)}</div>
    <div class="pm-data-legend">
      <span class="pm-data-legend__item"><i class="pm-data-legend__swatch pm-data-legend__swatch--gold"></i>Most mins / goals / assists</span>
      <span class="pm-data-legend__item"><i class="pm-data-legend__swatch pm-data-legend__swatch--left">L</i>Left footed<span data-export-hide> · click Ft to toggle</span></span>
      <span class="pm-data-legend__count">${ordered.length} players</span>
    </div>
    <div class="pm-data-body pm-data-body--single" style="--pm-squad-rows:${rowCount}">
      <div class="pm-data-table-wrap">
        <table class="pm-data-table pm-data-table--dense pm-data-table--${density}">
          <thead>
            <tr>
              <th>#</th><th>Name</th><th>Pos</th><th>Age</th><th>Ft</th>
              <th>MP</th><th>Starts</th><th>Min</th><th>Goals</th><th>Assists</th>
            </tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="10">No squad data.</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  </section>`;
}

function formResultCodes(items) {
  return (items || [])
    .map((item) => {
      if (typeof item === "string") return item.toUpperCase();
      return String(item?.result || "").toUpperCase();
    })
    .filter((code) => code === "W" || code === "D" || code === "L");
}

function formDotsHtml(results, { large = false, xl = false } = {}) {
  const sizeClass = xl ? " pm-form-dot--xl" : large ? " pm-form-dot--lg" : "";
  return formResultCodes(results)
    .map(
      (result) =>
        `<span class="pm-form-dot${sizeClass} pm-form-dot--${escapeHtml(result)}" title="${escapeHtml(result)}">${escapeHtml(result)}</span>`,
    )
    .join("");
}

function formSummaryCounts(results) {
  let w = 0;
  let d = 0;
  let l = 0;
  for (const result of formResultCodes(results)) {
    if (result === "W") w += 1;
    else if (result === "D") d += 1;
    else if (result === "L") l += 1;
  }
  return { w, d, l, played: w + d + l, pts: w * 3 + d };
}

function formMatchesChronological(form) {
  return [...(form || [])].sort((a, b) => {
    const da = Date.parse(a?.date || "") || 0;
    const db = Date.parse(b?.date || "") || 0;
    return da - db || (Number(a?.match_id) || 0) - (Number(b?.match_id) || 0);
  });
}

function formRibbonHtml(form) {
  const chronological = formMatchesChronological(form);
  if (!chronological.length) {
    return `<div class="pm-form-ribbon"><p class="pm-form-ribbon__empty">No recent form.</p></div>`;
  }
  const sum = formSummaryCounts(chronological);
  return `<div class="pm-form-ribbon">
    <div class="pm-form-ribbon__strip">
      <div class="pm-form-ribbon__head">
        <span class="pm-form-ribbon__label">Recent form · ${chronological.length}</span>
        <span class="pm-form-ribbon__tally"><em class="pm-form-ribbon__w">${sum.w}W</em> · <em class="pm-form-ribbon__d">${sum.d}D</em> · <em class="pm-form-ribbon__l">${sum.l}L</em> · ${sum.pts} pts</span>
      </div>
      <div class="pm-form-ribbon__dots">${formDotsHtml(chronological, { large: true })}</div>
    </div>
    <p class="pm-form-ribbon__hint">Left = older · right = most recent</p>
  </div>`;
}

function homeAwayCardHtml(label, block) {
  const stats = block || {};
  const tone = label.toLowerCase();
  const played = Number(stats.played) || 0;
  const won = Number(stats.won) || 0;
  const gf = Number(stats.goals_for);
  const ga = Number(stats.goals_against);
  const gdRaw = stats.goal_difference != null
    ? Number(stats.goal_difference)
    : (Number.isFinite(gf) && Number.isFinite(ga) ? gf - ga : null);
  const gd = stats.goal_difference_label
    ?? (gdRaw == null || !Number.isFinite(gdRaw) ? "—" : (gdRaw > 0 ? `+${gdRaw}` : String(gdRaw)));
  const winPct = stats.win_pct != null
    ? `${stats.win_pct}%`
    : (played ? `${Math.round((1000 * won) / played) / 10}%` : "—");
  const metric = (title, value, hint = "", extraClass = "") =>
    `<div class="pm-ha-metric ${extraClass}">
      <span class="pm-ha-metric__label">${escapeHtml(title)}</span>
      <strong class="pm-ha-metric__value">${value ?? "—"}</strong>
      ${hint ? `<span class="pm-ha-metric__hint">${escapeHtml(hint)}</span>` : ""}
    </div>`;
  return `<article class="pm-ha-card pm-ha-card--${tone}">
    <header class="pm-ha-card__head">
      <span class="pm-ha-card__badge">${escapeHtml(label)}</span>
      <div class="pm-ha-card__form">${formDotsHtml(stats.form) || `<span class="pm-ha-card__empty">No games</span>`}</div>
    </header>
    <div class="pm-ha-card__hero">
      <div class="pm-ha-pillars">
        <div class="pm-ha-pillar pm-ha-pillar--w">
          <strong>${won}</strong>
          <span>Win</span>
        </div>
        <div class="pm-ha-pillar pm-ha-pillar--d">
          <strong>${stats.drawn ?? 0}</strong>
          <span>Draw</span>
        </div>
        <div class="pm-ha-pillar pm-ha-pillar--l">
          <strong>${stats.lost ?? 0}</strong>
          <span>Loss</span>
        </div>
      </div>
      <p class="pm-ha-card__meta">${played} played · ${stats.points ?? 0} pts</p>
    </div>
    <div class="pm-ha-card__grid">
      ${metric("Goals for", stats.goals_for, stats.goals_for_pg != null ? `${stats.goals_for_pg}/m` : "")}
      ${metric("Goals against", stats.goals_against, stats.goals_against_pg != null ? `${stats.goals_against_pg}/m` : "")}
      ${metric("Goal diff", gd, "", "pm-ha-metric--accent")}
      ${metric("Clean sheets", stats.clean_sheets, stats.clean_sheet_pct != null ? `${stats.clean_sheet_pct}%` : "")}
      ${metric("Points / game", stats.ppg, stats.points != null ? `${stats.points} pts` : "", "pm-ha-metric--accent")}
      ${metric("Win rate", winPct, "")}
    </div>
  </article>`;
}

function renderFormSlide(report) {
  const focusId = report.opponent?.id;
  const clubName = report.opponent?.name || "Opposition";
  const table = report.league_table || [];
  const tableSize = table.length || Number(report.overview?.league_table_size) || 24;
  const form = report.form || [];
  const homeAway = report.home_away || {};

  const tableRows = table
    .map((row) => {
      const pos = Number(row.position) || 0;
      const isFocus = focusId != null && Number(row.squad_id) === Number(focusId);
      const classes = ["pm-league-row"];
      if (isFocus) classes.push("pm-league-row--focus");
      if (pos >= 1 && pos <= 2) classes.push("pm-league-row--promo");
      else if (pos >= 3 && pos <= 6) classes.push("pm-league-row--playoff");
      else if (pos > tableSize - 4) classes.push("pm-league-row--relegation");
      const gd = Number(row.goal_difference);
      const gdText = Number.isFinite(gd) ? (gd > 0 ? `+${gd}` : String(gd)) : "—";
      return `<tr class="${classes.join(" ")}">
        <td class="pm-league-pos">${pos || "—"}</td>
        <td class="pm-league-name">${escapeHtml(row.name || "—")}</td>
        <td>${row.played ?? "—"}</td>
        <td>${row.won ?? "—"}</td>
        <td>${row.drawn ?? "—"}</td>
        <td>${row.lost ?? "—"}</td>
        <td>${row.goals_for ?? "—"}</td>
        <td>${row.goals_against ?? "—"}</td>
        <td>${gdText}</td>
        <td class="pm-league-pts">${row.points ?? "—"}</td>
        <td class="pm-league-form">${formDotsHtml(row.form)}</td>
      </tr>`;
    })
    .join("");

  // Oldest at top → most recent at bottom.
  const resultRows = formMatchesChronological(form)
    .map((match) => {
      const result = match.result || "";
      const crestSrc =
        match.opponent_image_url
        || (match.opponent_id ? `/api/pre-match-handout/badge/${match.opponent_id}` : "");
      const crest = crestSrc
        ? `<img class="pm-result-row__crest" src="${escapeHtml(crestSrc)}" alt="" loading="lazy" onerror="this.classList.add('pm-result-row__crest--empty');this.removeAttribute('src')" />`
        : `<span class="pm-result-row__crest pm-result-row__crest--empty" aria-hidden="true">${escapeHtml(crestInitials(match.opponent))}</span>`;
      return `<article class="pm-result-row pm-result-row--${escapeHtml(result)}">
        ${crest}
        <div class="pm-result-row__body">
          <div class="pm-result-row__top">
            <div class="pm-result-row__identity">
              <span class="pm-result-row__opp">${escapeHtml(match.opponent || "Opponent")}</span>
              <div class="pm-result-row__subline">
                <span class="pm-result-row__venue">${escapeHtml(match.venue || "—")}</span>
                <span class="pm-result-row__date">${formatMatchDate(match.date)}</span>
              </div>
            </div>
            <div class="pm-result-row__side pm-result-row__side--score">
              <span class="pm-result-row__badge">${escapeHtml(result || "—")}</span>
              <strong class="pm-result-row__score">${escapeHtml(match.score || "—")}</strong>
            </div>
          </div>
        </div>
      </article>`;
    })
    .join("");

  return `<section class="pm-slide pm-slide--form" data-slide-title="Form & Team Stats">
    <div class="pm-slide__header-bar">FORM AND TEAM STATS</div>
    <div class="pm-slide__subheader">${escapeHtml(clubName)} · ${escapeHtml(report.competition || "League")} ${escapeHtml(report.season || "")}</div>
    <div class="pm-form-layout">
      <div class="pm-form-layout__table">
        <div class="pm-league-wrap" style="--pm-league-rows:${Math.max(tableSize, 1)}">
          <table class="pm-league-table">
            <thead>
              <tr>
                <th>#</th><th>Team</th><th>GP</th><th>W</th><th>D</th><th>L</th>
                <th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Form</th>
              </tr>
            </thead>
            <tbody>${tableRows || `<tr><td colspan="11">No table data.</td></tr>`}</tbody>
          </table>
        </div>
      </div>
      <div class="pm-form-layout__results">
        <header class="pm-panel-title">Recent results · oldest → newest</header>
        <div class="pm-form-results-stack">
          ${formRibbonHtml(form)}
          <div class="pm-result-list">${resultRows || `<p class="previous-xis-empty">No recent results.</p>`}</div>
        </div>
      </div>
      <div class="pm-form-layout__splits">
        <header class="pm-panel-title">Home / Away</header>
        ${homeAwayCardHtml("Home", homeAway.home)}
        ${homeAwayCardHtml("Away", homeAway.away)}
      </div>
    </div>
  </section>`;
}

function goalTypeTableHtml(title, tone, rows) {
  const body = (rows || [])
    .map(
      (row) => `<div class="pm-goal-type__row">
        <span class="pm-goal-type__rank">${escapeHtml(row.rank || "—")}</span>
        <span class="pm-goal-type__label">${escapeHtml(row.label || "—")}</span>
        <strong class="pm-goal-type__count">${row.goals ?? 0}</strong>
      </div>`,
    )
    .join("");
  return `<section class="pm-goal-type pm-goal-type--${tone}">
    <header class="pm-goal-type__head">${escapeHtml(title)}</header>
    <div class="pm-goal-type__cols" aria-hidden="true">
      <span>#</span><span>Type</span><span>Goals</span>
    </div>
    <div class="pm-goal-type__body">${body || `<p class="pm-goal-type__empty">No goals recorded.</p>`}</div>
  </section>`;
}

function goalsPitchDefaults() {
  return {
    goalX: 52.5,
    minX: 0,
    widthM: 68,
    depthM: 52.5,
    penaltyBoxDepthM: 16.5,
    penaltyBoxWidthM: 40.32,
    sixYardDepthM: 5.5,
    sixYardWidthM: 18.32,
    penaltySpotM: 11,
    penaltyArcM: 9.15,
  };
}

function goalsImpectToSvg(impectX, impectY, pitch, drawW, plotH, pitchY, padX = 10) {
  const halfW = pitch.widthM / 2;
  const xRange = pitch.goalX - pitch.minX;
  return {
    x: padX + ((halfW - impectY) / pitch.widthM) * drawW,
    y: pitchY + ((pitch.goalX - impectX) / xRange) * plotH,
  };
}

/**
 * 12-zone danger grid:
 * - Box: 2x2 (NEAR/MID x BOX L/R) inside the penalty area
 * - Each outside: 2x2 (TOUCH/CHANNEL x BOX-BAND/DEEP)
 * Deep-centre finishes (beyond 18yd, in box width) map into the near-side CHANNEL DEEP.
 */
const GOALS_ZONE_COUNT = 12;
const GOALS_ZONE_BOX = { NL: 0, NR: 1, ML: 2, MR: 3 };
const GOALS_ZONE_OUT_L = { BT: 4, BC: 5, DT: 6, DC: 7 };
const GOALS_ZONE_OUT_R = { BT: 8, BC: 9, DT: 10, DC: 11 };

function goalsZoneGeometry(pitch) {
  const widthM = pitch.widthM || 68;
  const boxW = pitch.penaltyBoxWidthM || 40.32;
  const boxDepth = pitch.penaltyBoxDepthM || 16.5;
  const sixDepth = pitch.sixYardDepthM || 5.5;
  const goalX = pitch.goalX;
  const leftBox = (widthM - boxW) / 2;
  const rightBox = leftBox + boxW;
  const center = widthM / 2;
  const leftMid = leftBox / 2;
  const rightMid = (rightBox + widthM) / 2;
  return {
    widthM,
    leftBox,
    rightBox,
    center,
    leftMid,
    rightMid,
    sixLine: goalX - sixDepth,
    boxLine: goalX - boxDepth,
    goalX,
    minX: pitch.minX,
  };
}

function goalsZoneId(impectX, impectY, pitch) {
  const geo = goalsZoneGeometry(pitch);
  const halfW = geo.widthM / 2;
  const fromLeft = halfW - Number(impectY);
  const x = Number(impectX);
  const inBoxWidth = fromLeft >= geo.leftBox && fromLeft < geo.rightBox;
  const inBoxDepth = x > geo.boxLine;

  if (inBoxWidth && inBoxDepth) {
    const left = fromLeft < geo.center;
    const near = x > geo.sixLine;
    if (near && left) return GOALS_ZONE_BOX.NL;
    if (near && !left) return GOALS_ZONE_BOX.NR;
    if (left) return GOALS_ZONE_BOX.ML;
    return GOALS_ZONE_BOX.MR;
  }

  if (inBoxWidth && !inBoxDepth) {
    return fromLeft < geo.center ? GOALS_ZONE_OUT_L.DC : GOALS_ZONE_OUT_R.DC;
  }

  if (fromLeft < geo.leftBox) {
    const touch = fromLeft < geo.leftMid;
    const boxBand = inBoxDepth;
    if (boxBand && touch) return GOALS_ZONE_OUT_L.BT;
    if (boxBand && !touch) return GOALS_ZONE_OUT_L.BC;
    if (touch) return GOALS_ZONE_OUT_L.DT;
    return GOALS_ZONE_OUT_L.DC;
  }

  const touch = fromLeft >= geo.rightMid;
  const boxBand = inBoxDepth;
  if (boxBand && touch) return GOALS_ZONE_OUT_R.BT;
  if (boxBand && !touch) return GOALS_ZONE_OUT_R.BC;
  if (touch) return GOALS_ZONE_OUT_R.DT;
  return GOALS_ZONE_OUT_R.DC;
}

function dangerHeatStyle(heat) {
  if (heat <= 0) return { fill: "#14532d", opacity: 0.1 };
  let r;
  let g;
  let b;
  if (heat < 0.5) {
    const t = heat * 2;
    r = Math.round(250 + t * (249 - 250));
    g = Math.round(204 + t * (115 - 204));
    b = Math.round(21 + t * (22 - 21));
  } else {
    const t = (heat - 0.5) * 2;
    r = Math.round(249 + t * (220 - 249));
    g = Math.round(115 + t * (38 - 115));
    b = Math.round(22 + t * (38 - 22));
  }
  return { fill: `rgb(${r},${g},${b})`, opacity: 0.44 + heat * 0.5 };
}

function goalsZoneRectSvg(x0, y0, x1, y1) {
  const x = Math.min(x0, x1);
  const y = Math.min(y0, y1);
  const w = Math.abs(x1 - x0);
  const h = Math.abs(y1 - y0);
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
}

function goalsZonesOverlay(pitch, points, drawW, plotH, pitchY, padX, pitchX, options = {}) {
  const dangerMode = options.mode === "danger";
  const geo = goalsZoneGeometry(pitch);
  const topY = pitchY;
  const botY = pitchY + plotH;
  const mToX = (edgeM) => pitchX + (edgeM / geo.widthM) * drawW;
  const mToY = (lineX) => {
    if (lineX >= geo.goalX) return topY;
    if (lineX <= geo.minX) return botY;
    return goalsImpectToSvg(lineX, 0, pitch, drawW, plotH, pitchY, padX).y;
  };

  const xTouchL0 = mToX(0);
  const xTouchL1 = mToX(geo.leftMid);
  const xChanL1 = mToX(geo.leftBox);
  const xBoxC = mToX(geo.center);
  const xChanR0 = mToX(geo.rightBox);
  const xTouchR0 = mToX(geo.rightMid);
  const xTouchR1 = mToX(geo.widthM);

  const yGoal = topY;
  const ySix = mToY(geo.sixLine);
  const yBox = mToY(geo.boxLine);
  const yHalf = botY;

  const zoneRects = {
    [GOALS_ZONE_BOX.NL]: goalsZoneRectSvg(xChanL1, yGoal, xBoxC, ySix),
    [GOALS_ZONE_BOX.NR]: goalsZoneRectSvg(xBoxC, yGoal, xChanR0, ySix),
    [GOALS_ZONE_BOX.ML]: goalsZoneRectSvg(xChanL1, ySix, xBoxC, yBox),
    [GOALS_ZONE_BOX.MR]: goalsZoneRectSvg(xBoxC, ySix, xChanR0, yBox),
    [GOALS_ZONE_OUT_L.BT]: goalsZoneRectSvg(xTouchL0, yGoal, xTouchL1, yBox),
    [GOALS_ZONE_OUT_L.BC]: goalsZoneRectSvg(xTouchL1, yGoal, xChanL1, yBox),
    [GOALS_ZONE_OUT_L.DT]: goalsZoneRectSvg(xTouchL0, yBox, xTouchL1, yHalf),
    [GOALS_ZONE_OUT_L.DC]: goalsZoneRectSvg(xTouchL1, yBox, xBoxC, yHalf),
    [GOALS_ZONE_OUT_R.BC]: goalsZoneRectSvg(xChanR0, yGoal, xTouchR0, yBox),
    [GOALS_ZONE_OUT_R.BT]: goalsZoneRectSvg(xTouchR0, yGoal, xTouchR1, yBox),
    [GOALS_ZONE_OUT_R.DC]: goalsZoneRectSvg(xBoxC, yBox, xTouchR0, yHalf),
    [GOALS_ZONE_OUT_R.DT]: goalsZoneRectSvg(xTouchR0, yBox, xTouchR1, yHalf),
  };

  const counts = Array(GOALS_ZONE_COUNT).fill(0);
  for (const pt of points) {
    if (pt.hasLocation === false || pt.impectX == null || pt.impectY == null) continue;
    const id = goalsZoneId(Number(pt.impectX), Number(pt.impectY), pitch);
    counts[id] += 1;
  }
  const totalEvents = counts.reduce((sum, count) => sum + count, 0);
  const maxCount = Math.max(1, ...counts);
  const fills = [];
  const labels = [];
  const borders = [];

  for (let id = 0; id < GOALS_ZONE_COUNT; id += 1) {
    const rect = zoneRects[id];
    if (!rect || rect.w < 0.5 || rect.h < 0.5) continue;
    const count = counts[id];
    const heat = count / maxCount;
    if (dangerMode) {
      const style = dangerHeatStyle(count ? heat : 0);
      fills.push(
        `<rect x="${rect.x}" y="${rect.y}" width="${rect.w}" height="${rect.h}" fill="${style.fill}" opacity="${style.opacity}" />`,
      );
      const pct = totalEvents ? Math.round((count / totalEvents) * 100) : 0;
      const tight = rect.h < 48 || rect.w < 64;
      const mainSize = count ? (tight ? 22 : 28) : 12;
      const subSize = tight ? 9.5 : 11;
      const mainY = count ? (tight ? -5 : -6) : 0;
      const subY = tight ? 11 : 13;
      const pillW = Math.min(rect.w - 10, tight ? 36 : 42);
      if (!count) {
        labels.push(
          `<g transform="translate(${rect.cx}, ${rect.cy})" opacity="0.28">
            <text text-anchor="middle" dominant-baseline="middle" fill="#fff" font-family="Barlow Condensed, sans-serif" font-size="11" font-weight="800">${count}</text>
          </g>`,
        );
      } else {
        labels.push(
          `<g transform="translate(${rect.cx}, ${rect.cy})">
            <text text-anchor="middle" dominant-baseline="middle" y="${mainY}" fill="#fff" font-family="Barlow Condensed, sans-serif" font-size="${mainSize}" font-weight="800" stroke="#0a0a0a" stroke-width="2.4" paint-order="stroke fill" stroke-linejoin="round">${count}</text>
            <rect x="${-pillW / 2}" y="${subY - 6.5}" width="${pillW}" height="13" rx="4" fill="rgba(0,0,0,0.5)" />
            <text text-anchor="middle" dominant-baseline="middle" y="${subY}" fill="#fff" font-family="Barlow Condensed, sans-serif" font-size="${subSize}" font-weight="800" letter-spacing="0.02em">${pct}%</text>
          </g>`,
        );
      }
    } else {
      const fillOpacity = count ? 0.1 + heat * 0.28 : 0.04;
      const checker = id % 2 === 0;
      fills.push(
        `<rect x="${rect.x}" y="${rect.y}" width="${rect.w}" height="${rect.h}" fill="${checker ? "#0b3d14" : "#14532d"}" opacity="${fillOpacity}" />`,
      );
      labels.push(
        `<g transform="translate(${rect.x + rect.w - 11}, ${rect.y + 11})" opacity="${count ? 0.92 : 0.3}">
          <rect x="-8" y="-7" width="16" height="14" rx="3" fill="rgba(0,0,0,0.45)" stroke="rgba(255,255,255,0.45)" stroke-width="0.7" />
          <text text-anchor="middle" dominant-baseline="middle" y="1" fill="#fff" font-family="Barlow Condensed, sans-serif" font-size="10" font-weight="800">${count}</text>
        </g>`,
      );
    }
  }

  const borderOpacity = dangerMode ? 0.72 : 0.55;
  const borderWidth = dangerMode ? 1.25 : 1.1;
  const dash = "5 3.2";
  const lines = [
    [xTouchL1, topY, xTouchL1, botY],
    [xChanL1, topY, xChanL1, botY],
    [xBoxC, topY, xBoxC, botY],
    [xChanR0, topY, xChanR0, botY],
    [xTouchR0, topY, xTouchR0, botY],
    [xChanL1, ySix, xChanR0, ySix],
    [pitchX, yBox, pitchX + drawW, yBox],
  ];
  for (const [x1, y1, x2, y2] of lines) {
    borders.push(
      `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(255,255,255,${borderOpacity})" stroke-width="${borderWidth}" stroke-dasharray="${dash}" />`,
    );
  }

  const labelFill = `rgba(255,255,255,${dangerMode ? 0.7 : 0.5})`;
  const rowLabels = [
    { x: pitchX + 3, y: (yGoal + ySix) / 2, text: "NEAR" },
    { x: pitchX + 3, y: (ySix + yBox) / 2, text: "MID" },
    { x: pitchX + 3, y: (yBox + yHalf) / 2, text: "DEEP" },
  ]
    .map(
      (row) =>
        `<text x="${row.x}" y="${row.y}" fill="${labelFill}" font-family="Barlow Condensed, sans-serif" font-size="6" font-weight="800" letter-spacing="0.06em" dominant-baseline="middle">${row.text}</text>`,
    )
    .join("");

  const colLabels = [
    { x: (xTouchL0 + xChanL1) / 2, text: "OUT L" },
    { x: (xChanL1 + xBoxC) / 2, text: "BOX L" },
    { x: (xBoxC + xChanR0) / 2, text: "BOX R" },
    { x: (xChanR0 + xTouchR1) / 2, text: "OUT R" },
  ]
    .map(
      (col) =>
        `<text x="${col.x}" y="${botY - 2}" text-anchor="middle" fill="${labelFill}" font-family="Barlow Condensed, sans-serif" font-size="5.6" font-weight="800" letter-spacing="0.04em">${col.text}</text>`,
    )
    .join("");

  return {
    svg: `${fills.join("")}${borders.join("")}${rowLabels}${colLabels}`,
    labels: labels.join(""),
    counts,
    totalEvents,
  };
}

function goalsHeatEventMarks(points, pitch, drawW, plotH, pitchY, padX) {
  return goalsSpreadMarkers(points, pitch, drawW, plotH, pitchY, padX, 5.2)
    .map(({ x, y }) => {
      const s = 2.7;
      return `<g class="pm-goals-heat-x" transform="translate(${x}, ${y})" opacity="0.92">
        <line x1="${-s}" y1="${-s}" x2="${s}" y2="${s}" stroke="#0a0a0a" stroke-width="2.35" stroke-linecap="round"/>
        <line x1="${s}" y1="${-s}" x2="${-s}" y2="${s}" stroke="#0a0a0a" stroke-width="2.35" stroke-linecap="round"/>
        <line x1="${-s}" y1="${-s}" x2="${s}" y2="${s}" stroke="#fafafa" stroke-width="1.05" stroke-linecap="round"/>
        <line x1="${s}" y1="${-s}" x2="${-s}" y2="${s}" stroke="#fafafa" stroke-width="1.05" stroke-linecap="round"/>
      </g>`;
    })
    .join("");
}

function goalsSpreadMarkers(points, pitch, drawW, plotH, pitchY, padX, minDist = 15.5) {
  const pitchX = padX;
  const pitchRight = padX + drawW;
  const pitchBottom = pitchY + plotH;

  const items = points.map((pt, index) => {
    const svg = goalsImpectToSvg(Number(pt.impectX), Number(pt.impectY), pitch, drawW, plotH, pitchY, padX);
    return {
      pt,
      index,
      x: svg.x,
      y: svg.y,
      origX: svg.x,
      origY: svg.y,
    };
  });

  for (let pass = 0; pass < 14; pass += 1) {
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        const a = items[i];
        const b = items[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) {
          dx = pass % 2 === 0 ? 1 : 0.4;
          dy = pass % 2 === 0 ? 0 : 1;
          dist = Math.hypot(dx, dy);
        }
        if (dist < minDist) {
          const push = (minDist - dist) / 2;
          const ux = dx / dist;
          const uy = dy / dist;
          a.x -= ux * push;
          a.y -= uy * push;
          b.x += ux * push;
          b.y += uy * push;
        }
      }
    }
    for (const item of items) {
      item.x = Math.max(pitchX + 10, Math.min(pitchRight - 10, item.x));
      item.y = Math.max(pitchY + 10, Math.min(pitchBottom - 16, item.y));
    }
  }

  for (const item of items) {
    const nearBottom = item.y > pitchBottom - 20;
    item.initialsAbove = nearBottom;
    item.labelOffsetX = 0;
    const neighbors = items.filter((other) => other !== item && Math.hypot(other.x - item.x, other.y - item.y) < 13);
    if (neighbors.length) {
      const leftCount = neighbors.filter((other) => other.x <= item.x).length;
      item.labelOffsetX = leftCount % 2 === 0 ? -9 : 9;
    }
  }

  return items;
}

function goalsMarkerSvg(x, y, point, kind, maxXg, { initialsAbove = false, labelOffsetX = 0 } = {}) {
  const phase = point.phase || "Possession";
  const initials = escapeHtml(point.playerInitials || "");
  const xgDisplay = escapeHtml(point.xgDisplay || "");
  const xg = Number(point.xg) || 0;
  const isAssist = kind === "assists" || point.outcome === "assist";
  const fill = isAssist ? "#facc15" : "#22c55e";
  const baseStroke = "#0a0a0a";
  const r = isAssist ? 7.2 : 8.2;
  let shape = "";
  if (phase === "Transition") {
    const s = r * 1.35;
    shape = `<rect x="${-s / 2}" y="${-s / 2}" width="${s}" height="${s}" fill="${fill}" stroke="${baseStroke}" stroke-width="0.9" transform="rotate(45)"/>`;
  } else if (phase === "Set Play") {
    const s = r * 1.35;
    shape = `<rect x="${-s / 2}" y="${-s / 2}" width="${s}" height="${s}" rx="1.2" fill="${fill}" stroke="${baseStroke}" stroke-width="0.9"/>`;
  } else {
    shape = `<circle r="${r}" fill="${fill}" stroke="${baseStroke}" stroke-width="0.9"/>`;
  }

  let goldRing = "";
  if (!isAssist && xg > 0.08 && maxXg > 0) {
    const ratio = Math.min(1, xg / Math.max(maxXg, 0.18));
    if (ratio >= 0.35) {
      const width = 0.7 + ratio * 1.6;
      goldRing =
        phase === "Transition"
          ? `<rect x="${(-r * 1.35) / 2}" y="${(-r * 1.35) / 2}" width="${r * 1.35}" height="${r * 1.35}" fill="none" stroke="#fbbf24" stroke-width="${width}" transform="rotate(45)"/>`
          : phase === "Set Play"
            ? `<rect x="${(-r * 1.35) / 2}" y="${(-r * 1.35) / 2}" width="${r * 1.35}" height="${r * 1.35}" rx="1.2" fill="none" stroke="#fbbf24" stroke-width="${width}"/>`
            : `<circle r="${r}" fill="none" stroke="#fbbf24" stroke-width="${width}"/>`;
    }
  }

  const valueText = !isAssist && xgDisplay
    ? `<text y="0.6" text-anchor="middle" dominant-baseline="middle" fill="#fff" stroke="#111" stroke-width="0.45" paint-order="stroke fill" font-family="Barlow Condensed, sans-serif" font-size="6.6" font-weight="800">${xgDisplay}</text>`
    : "";
  const initialsText = initials
    ? `<text x="${labelOffsetX}" y="${initialsAbove ? -(r + 6.8) : r + 6.8}" text-anchor="middle" dominant-baseline="middle" fill="#111" stroke="rgba(255,255,255,0.9)" stroke-width="2.4" paint-order="stroke fill" font-family="Barlow Condensed, sans-serif" font-size="6.2" font-weight="800" letter-spacing="0.03em">${initials}</text>`
    : "";

  return `<g transform="translate(${x}, ${y - 2})">${shape}${goldRing}${valueText}${initialsText}</g>`;
}

function goalsMarkerKindForPoint(point, fallbackKind = "goals") {
  if (point?.markerKind === "assists" || point?.outcome === "assist") return "assists";
  if (point?.markerKind === "goals") return "goals";
  return fallbackKind;
}

function goalsPitchSvg(grid, options = {}) {
  const pitch = { ...goalsPitchDefaults(), ...(options.pitch || grid?.pitch || {}) };
  const points = options.points ?? grid?.points ?? [];
  const fallbackKind = grid?.kind || "goals";
  const drawW = options.drawW ?? 340;
  const padX = options.padX ?? 14;
  const padTop = options.padTop ?? 10;
  const padBottom = options.padBottom ?? 18;
  const spreadDist = options.spreadDist ?? 15.5;
  const drawH = (pitch.depthM / pitch.widthM) * drawW;
  const plotH = drawH;
  const pitchX = padX;
  const pitchY = padTop;
  const vbW = padX * 2 + drawW;
  const vbH = padTop + padBottom + drawH;
  const penDepth = ((pitch.penaltyBoxDepthM || 16.5) / pitch.depthM) * plotH;
  const penWidth = ((pitch.penaltyBoxWidthM || 40.32) / pitch.widthM) * drawW;
  const sixDepth = ((pitch.sixYardDepthM || 5.5) / pitch.depthM) * plotH;
  const sixWidth = ((pitch.sixYardWidthM || 18.32) / pitch.widthM) * drawW;
  const penX = pitchX + (drawW - penWidth) / 2;
  const sixX = pitchX + (drawW - sixWidth) / 2;
  const cx = pitchX + drawW / 2;
  const goalMouthW = (7.32 / pitch.widthM) * drawW;
  const goalMouthX = cx - goalMouthW / 2;

  const spotDepthM = pitch.penaltySpotM || 11;
  const arcRadiusM = pitch.penaltyArcM || 9.15;
  const boxDepthM = pitch.penaltyBoxDepthM || 16.5;
  const edgeFromSpotM = boxDepthM - spotDepthM;
  const arcHalfM = Math.sqrt(Math.max(0, arcRadiusM * arcRadiusM - edgeFromSpotM * edgeFromSpotM));
  const paLineY = pitchY + penDepth;
  const arcHalfSvg = (arcHalfM / pitch.widthM) * drawW;
  const ry = (arcRadiusM / pitch.depthM) * plotH;
  const penaltyArc = `<path d="M ${cx - arcHalfSvg} ${paLineY} A ${arcHalfSvg} ${ry} 0 0 1 ${cx + arcHalfSvg} ${paLineY}" fill="none" stroke="#fff" stroke-width="1" opacity="0.92" />`;
  const spot = goalsImpectToSvg(pitch.goalX - spotDepthM, 0, pitch, drawW, plotH, pitchY, padX);
  const halfWayY = pitchY + ((pitch.goalX - 0) / (pitch.goalX - pitch.minX)) * plotH;

  const plotted = points.filter(
    (pt) => pt.hasLocation !== false && pt.impectX != null && pt.impectY != null,
  );
  const zones = goalsZonesOverlay(
    pitch,
    plotted,
    drawW,
    plotH,
    pitchY,
    padX,
    pitchX,
    {
      mode: options.heatmapOnly ? "danger" : "subtle",
      fallbackKind,
      heatmapKind: options.heatmapKind,
      compact: options.compact,
    },
  );

  const maxXg = plotted
    .filter((pt) => goalsMarkerKindForPoint(pt, fallbackKind) === "goals")
    .reduce((max, pt) => Math.max(max, Number(pt.xg) || 0), 0);
  const patternId = options.svgId ?? `pmGoals-${fallbackKind}-${Math.round(Math.random() * 1e6)}`;
  const heatMarks = options.heatmapOnly
    ? goalsHeatEventMarks(plotted, pitch, drawW, plotH, pitchY, padX)
    : "";
  const markers = options.heatmapOnly
    ? ""
    : goalsSpreadMarkers(plotted, pitch, drawW, plotH, pitchY, padX, spreadDist)
      .sort((a, b) => {
        const aAssist = goalsMarkerKindForPoint(a.pt, fallbackKind) === "assists" ? 0 : 1;
        const bAssist = goalsMarkerKindForPoint(b.pt, fallbackKind) === "assists" ? 0 : 1;
        if (aAssist !== bAssist) return aAssist - bAssist;
        return (Number(a.pt.xg) || 0) - (Number(b.pt.xg) || 0) || a.index - b.index;
      })
      .map((item) => {
        const markerKind = goalsMarkerKindForPoint(item.pt, fallbackKind);
        return goalsMarkerSvg(item.x, item.y, item.pt, markerKind, maxXg, {
          initialsAbove: item.initialsAbove,
          labelOffsetX: item.labelOffsetX,
        });
      })
      .join("");

  return `<svg class="pm-goals-pitch${options.combined ? " pm-goals-pitch--combined" : ""}${options.paired || options.stacked ? " pm-goals-pitch--pair" : ""}${options.heatmapOnly ? " pm-goals-pitch--heatmap" : ""}" viewBox="0 0 ${vbW} ${vbH}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <defs>
      <pattern id="${patternId}" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(18)">
        <rect width="5" height="10" fill="#fff" />
      </pattern>
      <linearGradient id="${patternId}-shade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#000" stop-opacity="0.08"/>
        <stop offset="35%" stop-color="#000" stop-opacity="0"/>
        <stop offset="100%" stop-color="#000" stop-opacity="0.06"/>
      </linearGradient>
    </defs>
    <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="#2f8f3a" stroke="#fff" stroke-width="1.6" />
    <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="url(#${patternId})" opacity="0.08" />
    <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="url(#${patternId}-shade)" />
    ${zones.svg}
    <line x1="${pitchX}" y1="${halfWayY}" x2="${pitchX + drawW}" y2="${halfWayY}" stroke="#fff" stroke-width="1.1" opacity="0.9" />
    <rect x="${penX}" y="${pitchY}" width="${penWidth}" height="${penDepth}" fill="none" stroke="#fff" stroke-width="1.15" opacity="0.95" />
    <rect x="${sixX}" y="${pitchY}" width="${sixWidth}" height="${sixDepth}" fill="none" stroke="#fff" stroke-width="1" opacity="0.9" />
    ${penaltyArc}
    <circle cx="${spot.x}" cy="${spot.y}" r="1.35" fill="#fff" />
    <rect x="${goalMouthX}" y="${pitchY - 3.2}" width="${goalMouthW}" height="3.2" fill="none" stroke="#fff" stroke-width="1.4" />
    <line x1="${pitchX}" y1="${pitchY}" x2="${pitchX + drawW}" y2="${pitchY}" stroke="#fff" stroke-width="2" />
    ${heatMarks}
    ${zones.labels || ""}
    ${markers}
  </svg>`;
}

function goalsHeatmapPitchSvg(grid, heatmapKind) {
  const points = (grid?.points || []).map((pt) => ({
    ...pt,
    markerKind: heatmapKind,
    ...(heatmapKind === "assists" ? { outcome: "assist" } : {}),
  }));
  return goalsPitchSvg(grid, {
    points,
    pitch: grid?.pitch,
    drawW: 480,
    padX: 14,
    padTop: 8,
    padBottom: 16,
    combined: true,
    paired: true,
    heatmapOnly: true,
    heatmapKind,
    svgId: `pmGoals-heat-${heatmapKind}-${Math.round(Math.random() * 1e6)}`,
  });
}

function goalsCombinedPitchMapHtml(goalGrid, assistGrid, metaNote = "") {
  const goalsTotal = Number(goalGrid?.total) || 0;
  const assistsTotal = Number(assistGrid?.total) || 0;
  return `<section class="pm-goal-map pm-goal-map--pitch pm-goal-map--combined pm-goal-map--paired">
    <div class="pm-goals-heatmap-pair">
      <article class="pm-goals-heatmap-panel">
        <header class="pm-goals-heatmap-panel__head">
          <h4>Goals · open play</h4>
          <span>${goalsTotal} goals</span>
        </header>
        <div class="pm-goals-pitch-wrap pm-goals-pitch-wrap--pair">
          ${goalsHeatmapPitchSvg(goalGrid, "goals")}
        </div>
      </article>
      <article class="pm-goals-heatmap-panel">
        <header class="pm-goals-heatmap-panel__head">
          <h4>Assists · open play</h4>
          <span>${assistsTotal} assists</span>
        </header>
        <div class="pm-goals-pitch-wrap pm-goals-pitch-wrap--pair">
          ${goalsHeatmapPitchSvg(assistGrid, "assists")}
        </div>
      </article>
    </div>
    <div class="pm-goals-pitch-legend pm-goals-pitch-legend--combined pm-goals-pitch-legend--heatmap">
      <span class="pm-goals-heat-legend">
        <i class="pm-goals-heat-legend__bar" aria-hidden="true"></i>
        Low → high threat
      </span>
      <span class="pm-goals-pitch-legend__zones">12 zones · box 2×2 · outside 2×2 · near / mid / deep</span>
    </div>
    ${metaNote ? `<p class="pm-goal-map__note">${escapeHtml(metaNote)}</p>` : ""}
  </section>`;
}

function goalsPitchMapHtml(title, grid, metaNote = "") {
  const total = Number(grid?.total) || 0;
  const kind = grid?.kind || "goals";
  const countLabel = kind === "assists" ? "assists" : "goals";
  return `<section class="pm-goal-map pm-goal-map--pitch">
    <header class="pm-goal-map__head">
      <h3>${escapeHtml(title)}</h3>
      <span class="pm-goal-map__count">${total} ${countLabel}</span>
    </header>
    <div class="pm-goals-pitch-wrap">
      ${goalsPitchSvg(grid)}
    </div>
    <div class="pm-goals-pitch-legend">
      <span><i class="pm-goals-legend__shape pm-goals-legend__shape--circle"></i> Possession</span>
      <span><i class="pm-goals-legend__shape pm-goals-legend__shape--diamond"></i> Transition</span>
      <span><i class="pm-goals-pitch-legend__swatch ${kind === "assists" ? "pm-goals-pitch-legend__swatch--assist" : "pm-goals-pitch-legend__swatch--goal"}"></i>
      ${kind === "assists" ? "Assist" : "Goal + xG"}</span>
      <span class="pm-goals-pitch-legend__zones">12 zones · box 2×2 · outside 2×2 · near / mid / deep</span>
    </div>
    ${metaNote ? `<p class="pm-goal-map__note">${escapeHtml(metaNote)}</p>` : ""}
  </section>`;
}

function goalHeatMapHtml(title, grid, metaNote = "") {
  return goalsPitchMapHtml(title, grid, metaNote);
}

function goalsPhaseStripHtml(side, tone) {
  const total = Number(side?.total) || 0;
  const phases = side?.phases || [];
  const cards = phases
    .map((phase) => {
      const count = Number(phase.goals) || 0;
      const pct = total ? Math.round((count / total) * 100) : 0;
      return `<article class="pm-goal-phase pm-goal-phase--${escapeHtml(phase.key || "")}">
        <span class="pm-goal-phase__label">${escapeHtml(phase.label || "—")}</span>
        <div class="pm-goal-phase__stats">
          <strong class="pm-goal-phase__value">${count}</strong>
          <span class="pm-goal-phase__unit">goals</span>
          <span class="pm-goal-phase__pct">${pct}%</span>
        </div>
        <div class="pm-goal-phase__bar"><span style="width:${pct}%"></span></div>
      </article>`;
    })
    .join("");
  return `<div class="pm-goal-topline pm-goal-topline--${tone}">
    <div class="pm-goal-total">
      <span class="pm-goal-total__label">Total goals</span>
      <strong class="pm-goal-total__value">${total}</strong>
    </div>
    <div class="pm-goal-phases">${cards}</div>
  </div>`;
}

function renderGoalsSideSlide(report, sideKey) {
  const analysis = report.goals_analysis;
  if (!analysis) return "";
  const side = analysis[sideKey] || {};
  const clubName = report.opponent?.name || "Opposition";
  const matches = Number(analysis.matches) || 0;
  const tone = sideKey === "for" ? "for" : "against";
  const title = sideKey === "for" ? "Goals For" : "Goals Against";
  const meta = side.map_meta || {};
  const mapNote =
    meta.goals_mapped != null || meta.assists_found != null
      ? `${meta.goals_mapped ?? 0} open-play goals · ${meta.assists_mapped ?? 0} of ${meta.assists_found ?? 0} assists · attacking half`
      : "";

  return `<section class="pm-slide pm-slide--goals pm-slide--goals-${tone}" data-slide-title="${title}">
    <div class="pm-slide__header-bar">GOALS ANALYSIS · ${title.toUpperCase()}</div>
    <div class="pm-slide__subheader">${escapeHtml(clubName)} · last ${matches} matches · possession / transition / set play</div>
    ${goalsPhaseStripHtml(side, tone)}
    <div class="pm-goals-layout pm-goals-layout--combined">
      <div class="pm-goals-layout__left">
        ${goalTypeTableHtml("By chance type", tone, side.types)}
      </div>
      <div class="pm-goals-layout__right pm-goals-layout__right--combined">
        ${goalsCombinedPitchMapHtml(side.goal_map, side.assist_map, mapNote)}
      </div>
    </div>
  </section>`;
}

function renderGoalsAnalysisSlides(report) {
  if (!report.goals_analysis) return [];
  return [
    renderGoalsSideSlide(report, "for"),
    renderGoalsSideSlide(report, "against"),
  ];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pitchMarkingsHtml(extraClass = "") {
  const cls = ["pm-pitch-markings", extraClass].filter(Boolean).join(" ");
  return `<div class="${cls}" aria-hidden="true">
    <span class="pm-pitch-markings__halfway"></span>
    <span class="pm-pitch-markings__circle"></span>
    <span class="pm-pitch-markings__pen pm-pitch-markings__pen--top"></span>
    <span class="pm-pitch-markings__pen pm-pitch-markings__pen--bot"></span>
    <span class="pm-pitch-markings__six pm-pitch-markings__six--top"></span>
    <span class="pm-pitch-markings__six pm-pitch-markings__six--bot"></span>
    <span class="pm-pitch-markings__spot pm-pitch-markings__spot--top"></span>
    <span class="pm-pitch-markings__spot pm-pitch-markings__spot--bot"></span>
  </div>`;
}

function numberedXiMarkersHtml(players) {
  return (players || [])
    .map((player, index) => {
      const left = Number(player.x_pct ?? 50);
      const top = Number(player.y_pct ?? 50);
      const number = player.shirt_number ?? "";
      const surname = player.short_name || playerSurname(player.name);
      const highlight = String(player.highlight || "").toLowerCase();
      const isRed = highlight === "red" || Boolean(player.ghost);
      const label = surname.length <= 11 ? surname : `${surname.slice(0, 10)}…`;
      const isGk = String(player.position || player.band || "").toUpperCase().includes("GOAL")
        || String(player.band || "") === "gk";
      const classes = ["xi-circle"];
      if (highlight === "sub" || highlight === "red" || highlight === "moved") {
        classes.push(`xi-circle--${highlight}`);
      }
      if (player.ghost || isRed) classes.push("xi-circle--ghost");
      const z = isRed ? 40 + index : index + 1;
      return `<div class="${classes.join(" ")}" style="left:${left}%;top:${top}%;z-index:${z}" title="${escapeHtml(player.name || label)}">
        <span class="xi-circle__dot${isGk && !isRed ? " xi-circle__dot--gk" : ""}">${number || "·"}</span>
        <span class="xi-circle__name">${escapeHtml(label)}</span>
      </div>`;
    })
    .join("");
}

function lastGamePhaseLabelHtml(phase) {
  if (!phase || phase.kind === "start") return "Starting XI";
  const minutes = (phase.minute_labels || []).join(", ");
  const onHtml = (phase.on_names || [])
    .map((name) => `<span class="lg-chg lg-chg--sub">${escapeHtml(name)}</span>`)
    .join(", ");
  const offHtml = (phase.off_names || [])
    .map((name, index) => {
      const kind = String((phase.off_kinds || [])[index] || "sub").toLowerCase() === "red"
        ? "red"
        : "off";
      return `<span class="lg-chg lg-chg--${kind}">${escapeHtml(name)}</span>`;
    })
    .join(", ");

  const parts = [];
  if (minutes) parts.push(escapeHtml(minutes));
  if (onHtml) parts.push(`<span class="lg-chg-pair"><em class="lg-chg-pair__dir">On</em> ${onHtml}</span>`);
  if (offHtml) parts.push(`<span class="lg-chg-pair"><em class="lg-chg-pair__dir lg-chg-pair__dir--off">Off</em> ${offHtml}</span>`);
  let body = parts.length ? parts.join(" · ") : escapeHtml(phase.label || "Change");

  if (phase.formation_changed && phase.formation) {
    body += ` · <span class="lg-chg lg-chg--shape">→ ${escapeHtml(phase.formation)}</span>`;
  }
  return body;
}

function renderPreviousXisSlide(report) {
  const clubName = report.opponent?.name || "Opposition";
  const lineups = (report.previous_xis || []).slice(0, 3);
  const fixtureDate = formatMatchDate(report.fixture?.scheduled_date);
  const sub =
    report.fixture?.scheduled_date && fixtureDate !== "—"
      ? `${clubName} · last ${lineups.length || 0} before ${fixtureDate}`
      : `${clubName} · last ${lineups.length || 0} matches`;
  const cards = lineups
    .map((lineup) => {
      const players = (lineup?.pitch_players || []).slice(0, 11);
      const result = lineup?.result || "";
      const resultClass = result ? `pm-xi-result--${result}` : "";
      return `<article class="previous-xi-card">
        <header class="previous-xi-card__head">
          <div>
            <p class="previous-xi-card__vs">vs ${lineup.opponent || "Opponent"}</p>
            <p class="previous-xi-card__meta">${formatMatchDate(lineup.date)} · ${lineup.venue || "—"} · ${lineup.formation || "—"}</p>
          </div>
          <div class="pm-xi-result pm-xi-result--compact ${resultClass}">
            <span>${result || "—"}</span>
            <strong>${lineup.score || "—"}</strong>
          </div>
        </header>
          <div class="previous-xi-mini-pitch" aria-label="Starting XI vs ${lineup.opponent || "Opponent"}">
          ${pitchMarkingsHtml("previous-xi-mini-pitch__markings")}
          <div class="previous-xi-mini-pitch__players">${numberedXiMarkersHtml(players)}</div>
        </div>
      </article>`;
    })
    .join("");

  return `<section class="pm-slide pm-slide--previous-xi" data-slide-title="Previous XIs">
    <div class="pm-slide__header-bar">PREVIOUS XIs</div>
    <div class="pm-slide__subheader">${sub}</div>
    <div class="previous-xis-row">
      ${cards || `<p class="previous-xis-empty">No recent starting XIs available.</p>`}
    </div>
  </section>`;
}

function renderLastGameSlide(report) {
  const lastGame = report.last_game;
  if (!lastGame) return "";
  const clubName = report.opponent?.name || "Opposition";
  const result = lastGame.result || "";
  const resultClass = result ? `pm-xi-result--${result}` : "";
  const formationNote = lastGame.formation_changed
    ? `Shape changed · ${(lastGame.formations_used || []).join(" → ") || lastGame.starting_formation || "—"}`
    : `Held ${lastGame.starting_formation || "—"}`;
  const phases = lastGame.phases || [];
  const panels = phases
    .map((phase) => {
      const players = phase.pitch_players || [];
      return `<article class="last-game-panel">
        <header class="last-game-panel__head">
          <p class="last-game-panel__label">${lastGamePhaseLabelHtml(phase)}</p>
          <p class="last-game-panel__formation">${escapeHtml(phase.formation || "—")}</p>
        </header>
        <div class="last-game-pitch" aria-label="${escapeHtml(phase.label || "Lineup")}">
          ${pitchMarkingsHtml("last-game-pitch__markings")}
          <div class="last-game-pitch__players">${numberedXiMarkersHtml(players)}</div>
        </div>
      </article>`;
    })
    .join("");

  const legend = `<div class="last-game-legend" aria-label="Colour key">
    <span class="last-game-legend__item"><i class="last-game-legend__swatch last-game-legend__swatch--xi"></i>Starting XI</span>
    <span class="last-game-legend__item"><i class="last-game-legend__swatch last-game-legend__swatch--sub"></i>Sub on</span>
    <span class="last-game-legend__item"><i class="last-game-legend__swatch last-game-legend__swatch--moved"></i>Position change</span>
    <span class="last-game-legend__item"><i class="last-game-legend__swatch last-game-legend__swatch--red"></i>Sent off</span>
  </div>`;

  return `<section class="pm-slide pm-slide--last-game" data-slide-title="Last Game">
    <div class="pm-slide__header-bar">LAST GAME · TEAM &amp; SUBS</div>
    <div class="pm-slide__subheader">${escapeHtml(clubName)} vs ${escapeHtml(lastGame.opponent || "Opponent")}</div>
    <div class="last-game-meta">
      <div class="last-game-meta__left">
        <p class="last-game-meta__when">${formatMatchDate(lastGame.date)} · ${escapeHtml(lastGame.venue || "—")}</p>
        <p class="last-game-meta__shape">${escapeHtml(formationNote)}</p>
      </div>
      ${legend}
      <div class="pm-xi-result pm-xi-result--compact ${resultClass}">
        <span>${escapeHtml(result || "—")}</span>
        <strong>${escapeHtml(lastGame.score || "—")}</strong>
      </div>
    </div>
    <div class="last-game-row" style="--last-game-cols:${Math.max(1, phases.length)}">
      ${panels || `<p class="previous-xis-empty">No lineup detail available for the last match.</p>`}
    </div>
  </section>`;
}

function formatRankSplitValue(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return escapeHtml(String(value ?? "—"));
  if (Number.isInteger(num)) return String(num);
  return num.toFixed(1).replace(/\.0$/, "");
}

function rankingSplitKind(breakdown) {
  const keys = new Set((breakdown || []).map((part) => part.key));
  if (["pass", "dribble", "regain", "shot", "set", "rec", "left", "centre", "right"].some((key) => keys.has(key))) {
    return "threat";
  }
  if (["build", "btl", "counter"].some((key) => keys.has(key))) return "press";
  if (["duel", "intercept", "loose", "header", "block"].some((key) => keys.has(key))) return "oi";
  if (["ground", "aerial"].some((key) => keys.has(key))) return "duel";
  return "phase";
}

const RANK_SPLIT_ARIA = {
  threat: "Threat type · pass dribble regain",
  press: "Press type",
  oi: "Intervention type",
  duel: "Duel type",
  phase: "Phase split",
};

const RANK_SPLIT_STAT = {
  threat: "PXT",
  press: "/90",
  oi: "/90",
  duel: "Win%",
  phase: "Total",
};

function rankingPlayerNameHtml(name, { compact = false } = {}) {
  const text = String(name || "—").trim();
  const compactClass = compact ? " pm-rank-row__name--compact" : "";
  if (!text || text === "—") {
    return `<span class="pm-rank-row__name pm-rank-row__name--stack${compactClass}"><span class="pm-rank-row__name-part">—</span></span>`;
  }
  const parts = text.split(/\s+/).filter(Boolean);
  if (parts.length === 1) {
    return `<span class="pm-rank-row__name pm-rank-row__name--stack${compactClass}" aria-label="${escapeHtml(text)}"><span class="pm-rank-row__name-part pm-rank-row__name-part--single">${escapeHtml(parts[0])}</span></span>`;
  }
  const surname = parts.pop();
  const first = parts.join(" ");
  return `<span class="pm-rank-row__name pm-rank-row__name--stack${compactClass}" aria-label="${escapeHtml(text)}">
    <span class="pm-rank-row__name-part pm-rank-row__name-part--first">${escapeHtml(first)}</span>
    <span class="pm-rank-row__name-part pm-rank-row__name-part--last">${escapeHtml(surname)}</span>
  </span>`;
}

function rankingPlayerRowHtml(player, index) {
  const photoUrl = playerPhotoUrl(player);
  const photo = photoUrl
    ? `<img class="pm-rank-row__photo" src="${escapeHtml(photoUrl)}" alt="" loading="eager" decoding="async" onerror="this.classList.add('pm-rank-row__photo--empty');this.removeAttribute('src')" />`
    : `<span class="pm-rank-row__photo pm-rank-row__photo--empty" aria-hidden="true"></span>`;
  const shirt =
    player.shirt_number != null && player.shirt_number !== ""
      ? `<span class="pm-rank-row__shirt-badge" title="Squad number">#${escapeHtml(player.shirt_number)}</span>`
      : "";
  const breakdown = (player.breakdown || [])
    .map((part) => {
      const shown =
        part.value_label != null && part.value_label !== ""
          ? escapeHtml(String(part.value_label))
          : formatRankSplitValue(part.value);
      return `<span class="pm-rank-split pm-rank-split--${escapeHtml(part.key || "")}">
        <em>${escapeHtml(part.label || "")}</em><strong>${shown}</strong>
      </span>`;
    })
    .join("");
  const hasSplits = Boolean(breakdown);
  const splitKind = rankingSplitKind(player.breakdown);
  return `<article class="pm-rank-row${index === 0 ? " pm-rank-row--lead" : ""}${hasSplits ? " pm-rank-row--splits" : ""}">
    <div class="pm-rank-row__media">
      ${photo}
      <span class="pm-rank-row__pos">${index + 1}</span>
      ${shirt}
    </div>
    <div class="pm-rank-row__meta">
      <div class="pm-rank-row__name-line">
        ${rankingPlayerNameHtml(player.name, { compact: hasSplits })}
      </div>
      ${breakdown ? `<div class="pm-rank-row__splits" aria-label="${RANK_SPLIT_ARIA[splitKind] || "Breakdown"}">${breakdown}</div>` : ""}
    </div>
    <div class="pm-rank-row__stat">
      <span class="pm-rank-row__stat-label">${hasSplits ? (RANK_SPLIT_STAT[splitKind] || "Total") : ""}</span>
      <strong class="pm-rank-row__value">${escapeHtml(player.value_label ?? player.value ?? "—")}</strong>
    </div>
  </article>`;
}

function rankingBoardHtml(board) {
  const rows = (board.players || [])
    .map((player, index) => rankingPlayerRowHtml(player, index))
    .join("");
  return `<section class="pm-rank-board">
    <header class="pm-rank-board__head">
      <h3>${escapeHtml(board.label || "—")}</h3>
      <span>${escapeHtml(board.subtitle || "")}</span>
    </header>
    <div class="pm-rank-board__list">
      ${rows || `<p class="pm-rank-board__empty">No data.</p>`}
    </div>
  </section>`;
}

function renderPlayerRankingsSlide(report, sideKey) {
  const rankings = report.player_rankings;
  if (!rankings) return "";
  const boards = rankings[sideKey] || [];
  if (!boards.length) return "";
  const clubName = report.opponent?.name || "Opposition";
  const matches = Number(rankings.matches) || 0;
  const minMinutes = Number(rankings.min_minutes) || 450;
  const isIn = sideKey === "in_possession";
  const title = isIn ? "Player Rankings · In Possession" : "Player Rankings · Out of Possession";
  const tone = isIn ? "in" : "out";
  const splitsReady = Number(rankings.splits_version || 0) >= 5;
  const staleNote = splitsReady
    ? ""
    : `<p class="pm-rank-stale">Rankings splits outdated — click <strong>Refresh data</strong> for clearer labels and reconciled breakdowns.</p>`;
  const sub = isIn
    ? `${clubName} · goals & assists total · rest /90 · min ${minMinutes}' · last ${matches} · assist phase · PXT by action`
    : `${clubName} · per 90 · min ${minMinutes}' · last ${matches} · win type · press phase · ground/aerial`;
  return `<section class="pm-slide pm-slide--rankings pm-slide--rankings-${tone}" data-slide-title="${isIn ? "IP Rankings" : "OOP Rankings"}">
    <div class="pm-slide__header-bar">${title.toUpperCase()}</div>
    <div class="pm-slide__subheader">${escapeHtml(sub)}</div>
    ${staleNote}
    <div class="pm-rank-grid pm-rank-grid--${boards.length}">
      ${boards.map(rankingBoardHtml).join("")}
    </div>
  </section>`;
}

function renderPlayerRankingsSlides(report) {
  if (!report.player_rankings) return [];
  return [
    renderPlayerRankingsSlide(report, "in_possession"),
    renderPlayerRankingsSlide(report, "out_of_possession"),
  ].filter(Boolean);
}

function buildSlides(report) {
  const previousSlide = (report.previous_xis || []).length
    ? [renderPreviousXisSlide(report)]
    : [];
  const lastGameSlide = report.last_game ? [renderLastGameSlide(report)] : [];
  const rankingSlides = renderPlayerRankingsSlides(report);
  const goalsSlides = renderGoalsAnalysisSlides(report);
  return [
    renderIntroSlide(report),
    renderSquadListSlide(report),
    renderTeamStyleSlide(report),
    ...previousSlide,
    ...lastGameSlide,
    renderFormSlide(report),
    renderSquadDataSlide(report),
    ...rankingSlides,
    ...goalsSlides,
  ];
}

function updateSlideNav() {
  const total = state.slides.length;
  const index = total ? state.slideIndex + 1 : 0;
  els.slideCounter.textContent = total ? `${index} / ${total}` : "—";
  els.prevSlideBtn.disabled = state.loading || state.slideIndex <= 0;
  els.nextSlideBtn.disabled = state.loading || state.slideIndex >= total - 1;
}

function highlightSlide(index) {
  const slides = [...els.deck.querySelectorAll(".pm-slide")];
  if (!slides.length) return;
  state.slideIndex = Math.max(0, Math.min(index, slides.length - 1));
  slides.forEach((slide, slideIndex) => {
    slide.classList.toggle("pm-slide--active", slideIndex === state.slideIndex);
  });
  const active = slides[state.slideIndex];
  const title = active?.dataset.slideTitle || "Pre-match report";
  els.statusBar.textContent = `${title} · ${state.report?.opponent?.name || ""} · scroll or ← →`;
  updateSlideNav();
}

function paintDeck() {
  els.deck.innerHTML = state.slides.join("");
  els.deck.querySelectorAll(".pm-slide").forEach((slide, slideIndex) => {
    slide.dataset.slideIndex = String(slideIndex);
  });
  warmDeckPhotos(els.deck);
  try {
    bindPitchInteractions(els.deck);
    bindSquadDataInteractions(els.deck);
  } catch (error) {
    console.error("Pitch UI bind failed", error);
  }
}

function showSlide(index, { scroll = true, repaint = false } = {}) {
  if (!state.slides.length) {
    els.deck.innerHTML = "";
    updateSlideNav();
    return;
  }
  const existing = els.deck.querySelectorAll(".pm-slide").length;
  if (repaint || existing !== state.slides.length) {
    paintDeck();
  }
  highlightSlide(index);
  if (scroll) {
    const active = els.deck.querySelectorAll(".pm-slide")[state.slideIndex];
    active?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function rebuildSlides() {
  if (!state.report) return;
  state.slides = buildSlides(state.report);
}

function renderDeck(report) {
  state.report = report;
  rebuildSlides();
  state.slideIndex = 0;
  paintDeck();
  highlightSlide(0);
  els.refreshBtn.disabled = false;
  if (els.exportPngsBtn) els.exportPngsBtn.disabled = false;
  if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.disabled = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function slugifyExportPart(value) {
  return String(value || "")
    .replace(/[^\w\s-]+/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 40) || "slide";
}

function exportPngBaseName() {
  const opponent = slugifyExportPart(state.report?.opponent?.name || "opponent").toLowerCase();
  return `port-vale-pre-match-${opponent}-slides`;
}

function exportWhatsappPdfBaseName() {
  const opponent = slugifyExportPart(state.report?.opponent?.name || "opponent").toLowerCase();
  return `port-vale-pre-match-${opponent}-whatsapp`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function setExportButtonsEnabled(enabled) {
  if (els.exportPngsBtn) els.exportPngsBtn.disabled = !enabled;
  if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.disabled = !enabled;
}

async function exportPreMatchPngs() {
  if (!state.report || !els.exportPngsBtn) return;
  els.exportPngsBtn.disabled = true;
  if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.disabled = true;
  els.refreshBtn.disabled = true;
  setStatus("Capturing slides as PNGs for WhatsApp…", "loading");
  try {
    const pages = await capturePreMatchSlides({ progressLabel: "Exporting PNGs" });
    const filename = `${exportPngBaseName()}.zip`;
    const response = await fetch("/api/pre-match/export-pngs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages,
        filename,
        document_title: `Pre-match · ${state.report?.opponent?.name || "Opponent"}`,
        opponent_name: state.report?.opponent?.name || "opponent",
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "PNG export failed");
    }
    const blob = await response.blob();
    downloadBlob(blob, filename);
    const folder = response.headers.get("X-Saved-Desktop-Folder");
    const zipPath = response.headers.get("X-Saved-Desktop-Path");
    if (folder) {
      setStatus(`PNG pack ready · folder on Desktop for WhatsApp · ${pages.length} slides`, "");
    } else if (zipPath) {
      setStatus(`PNG zip saved to Desktop · ${pages.length} slides`, "");
    } else {
      setStatus(`PNG zip downloaded · ${pages.length} slides`, "");
    }
    els.statusBar.textContent = folder
      ? `WhatsApp pack: ${folder}`
      : `Exported ${pages.length} PNG slides`;
  } catch (error) {
    setStatus(error.message || "PNG export failed", "error");
  } finally {
    setExportButtonsEnabled(Boolean(state.report));
    els.refreshBtn.disabled = false;
  }
}

async function exportWhatsappPdf() {
  if (!state.report || !els.exportWhatsappPdfBtn) return;
  setExportButtonsEnabled(false);
  els.refreshBtn.disabled = true;
  setStatus("Building full-quality WhatsApp PDF (1920×1080)…", "loading");
  try {
    const pages = await capturePreMatchSlides({
      layoutWidth: SLIDE_EXPORT_WIDTH,
      layoutHeight: SLIDE_EXPORT_HEIGHT,
      width: WHATSAPP_EXPORT_WIDTH,
      height: WHATSAPP_EXPORT_HEIGHT,
      scale: WHATSAPP_CAPTURE_SCALE,
      mimeType: "image/jpeg",
      quality: WHATSAPP_JPEG_QUALITY,
      progressLabel: "Capturing slides",
    });
    const filename = `${exportWhatsappPdfBaseName()}.pdf`;
    const response = await fetch("/api/pre-match/export-whatsapp-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages,
        filename,
        document_title: `Pre-match · ${state.report?.opponent?.name || "Opponent"}`,
        opponent_name: state.report?.opponent?.name || "opponent",
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "WhatsApp PDF export failed");
    }
    const blob = await response.blob();
    downloadBlob(blob, filename);
    const savedPath = response.headers.get("X-Saved-Desktop-Path");
    const sizeMb = (blob.size / (1024 * 1024)).toFixed(1);
    if (savedPath) {
      setStatus(`WhatsApp PDF ready · ${pages.length} slides · ${sizeMb} MB · Desktop`, "");
      els.statusBar.textContent = `Share from Desktop: ${savedPath.split("/").pop()}`;
    } else {
      setStatus(`WhatsApp PDF downloaded · ${pages.length} slides · ${sizeMb} MB`, "");
      els.statusBar.textContent = `PDF ready — attach in WhatsApp`;
    }
  } catch (error) {
    setStatus(error.message || "WhatsApp PDF export failed", "error");
  } finally {
    setExportButtonsEnabled(Boolean(state.report));
    els.refreshBtn.disabled = false;
  }
}

function renderEmptyDeck(message) {
  state.report = null;
  state.slides = [];
  state.slideIndex = 0;
  els.deck.innerHTML = `<div class="pm-slide pm-slide--active" style="display:flex !important;align-items:center;justify-content:center;background:#111;border:1px solid #2a2a2a;padding:3rem;text-align:center;color:#9ca3af;border-radius:12px;">${message}</div>`;
  els.statusBar.textContent = message;
  els.refreshBtn.disabled = true;
  if (els.exportPngsBtn) els.exportPngsBtn.disabled = true;
  if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.disabled = true;
  updateSlideNav();
}

async function loadFixtures() {
  const iterationId = Number(els.iterationId.value);
  const data = await fetchJson(`/api/pre-match/fixtures?iteration_id=${iterationId}`);
  state.fixtures = data.fixtures || [];
  if (!state.fixtures.length) {
    renderEmptyDeck("No opponents found for this season.");
    return false;
  }
  const currentMatchId = Number(els.matchId.value || 0);
  const stillValid = state.fixtures.some((row) => Number(row.match_id) === currentMatchId);
  if (!stillValid) {
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
  renderSeasonToggle();
  updateSlideNav();
  setStatus("Loading pre-match report from Impect… first load can take 20–40 seconds.", "loading");

  try {
    const report = await fetchJson("/api/pre-match/report", {
      method: "POST",
      body: JSON.stringify({
        iteration_id: iterationId,
        squad_id: squadId,
        match_id: matchId,
      }),
    });
    renderMatchBar();
    renderDeck(report);
    setStatus("");
    els.statusBar.textContent = `Loaded ${report.opponent?.name || "opponent"} · build ${PRE_MATCH_BUILD.slice(0, 8) || "—"} · slide 1 is the match intro`;
  } catch (error) {
    setStatus(error.message, "error");
    renderEmptyDeck("Could not load report.");
  } finally {
    state.loading = false;
    renderSeasonToggle();
    updateSlideNav();
  }
}

async function init() {
  renderEmptyDeck("Loading fixtures…");
  try {
    state.meta = await fetchJson("/api/pre-match/meta");
    els.iterationId.value = String(state.meta.default_iteration_id);
    if (state.meta.default_fixture) {
      els.matchId.value = String(state.meta.default_fixture.match_id || "");
      els.opponentId.value = String(state.meta.default_fixture.opponent_id || "");
    }
    renderSeasonToggle();
    const hasFixtures = await loadFixtures();
    if (hasFixtures) {
      await loadReport();
    }
  } catch (error) {
    setStatus(error.message, "error");
    renderEmptyDeck("Could not initialise pre-match report.");
  }
}

els.refreshBtn.addEventListener("click", loadReport);
if (els.exportPngsBtn) els.exportPngsBtn.addEventListener("click", exportPreMatchPngs);
if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.addEventListener("click", exportWhatsappPdf);
els.prevSlideBtn.addEventListener("click", () => showSlide(state.slideIndex - 1));
els.nextSlideBtn.addEventListener("click", () => showSlide(state.slideIndex + 1));

document.addEventListener("keydown", (event) => {
  if (!state.slides.length) return;
  if (event.key === "ArrowRight" || event.key === "PageDown") {
    event.preventDefault();
    showSlide(state.slideIndex + 1);
  } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
    event.preventDefault();
    showSlide(state.slideIndex - 1);
  }
});

let scrollTick = 0;
window.addEventListener(
  "scroll",
  () => {
    if (!state.slides.length) return;
    window.clearTimeout(scrollTick);
    scrollTick = window.setTimeout(() => {
      const slides = [...els.deck.querySelectorAll(".pm-slide")];
      if (!slides.length) return;
      const probe = window.scrollY + 180;
      let best = 0;
      slides.forEach((slide, index) => {
        if (slide.offsetTop <= probe) best = index;
      });
      if (best !== state.slideIndex) highlightSlide(best);
    }, 80);
  },
  { passive: true },
);

init();
