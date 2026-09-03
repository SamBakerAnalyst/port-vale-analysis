const state = {
  meta: null,
  fixtures: [],
  report: null,
  slides: [],
  slideIndex: 0,
  loading: false,
  heightEdit: null,
  deckMode: "two_pager",
};

const els = {
  app: document.getElementById("spApp"),
  iterationId: document.getElementById("iterationId"),
  opponentId: document.getElementById("opponentId"),
  matchId: document.getElementById("matchId"),
  seasonToggle: document.getElementById("seasonToggle"),
  matchBar: document.getElementById("matchBar"),
  deck: document.getElementById("deck"),
  deckViewport: document.getElementById("deckViewport"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportWhatsappPdfBtn: document.getElementById("exportWhatsappPdfBtn"),
  pdfViewBtn: document.getElementById("pdfViewBtn"),
  pdfBackBtn: document.getElementById("pdfBackBtn"),
  presentBtn: document.getElementById("presentBtn"),
  exportStatus: document.getElementById("exportStatus"),
  exportOverlay: document.getElementById("exportOverlay"),
  presentCount: document.getElementById("presentCount"),
  presentPrev: document.getElementById("presentPrev"),
  presentNext: document.getElementById("presentNext"),
  prevSlideBtn: document.getElementById("prevSlideBtn"),
  nextSlideBtn: document.getElementById("nextSlideBtn"),
  slideCounter: document.getElementById("slideCounter"),
  deckModeFullBtn: document.getElementById("deckModeFullBtn"),
  deckModeTwoBtn: document.getElementById("deckModeTwoBtn"),
};

const SLIDE_EXPORT_WIDTH = 1920;
const SLIDE_EXPORT_HEIGHT = 1080;
const SLIDE_EXPORT_SCALE = 2;
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

function slugifyExportPart(value) {
  return String(value || "")
    .replace(/[^\w\s-]+/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 40) || "slide";
}

function setExportStatus(message, kind = "") {
  if (!els.exportStatus) return;
  els.exportStatus.textContent = message || "";
  els.exportStatus.className = `sp-toolbar__export-status${kind ? ` sp-toolbar__export-status--${kind}` : ""}`;
}

function setExportOverlay(message) {
  if (!els.exportOverlay) return;
  if (message) {
    els.exportOverlay.textContent = message;
    els.exportOverlay.classList.add("is-active");
  } else {
    els.exportOverlay.textContent = "";
    els.exportOverlay.classList.remove("is-active");
  }
}

function updatePdfScale() {
  if (!document.body.classList.contains("is-pdf-view")) return;
  const displayW = Math.min(window.innerWidth * 0.96, 1760);
  document.body.style.setProperty("--sp-pdf-scale", String(displayW / SLIDE_EXPORT_WIDTH));
}

function applyPdfViewToSlides() {
  if (!document.body.classList.contains("is-pdf-view")) return;
  els.deck?.querySelectorAll(".sp-slide").forEach((slide) => {
    slide.classList.add("sp-slide--export-capture", "sp-slide--active");
    slide.style.setProperty("--sp-export-w", `${SLIDE_EXPORT_WIDTH}px`);
    slide.style.setProperty("--sp-export-h", `${SLIDE_EXPORT_HEIGHT}px`);
  });
  updatePdfScale();
}

function setPdfView(on) {
  if (on && document.body.classList.contains("is-present")) setPresent(false);
  document.body.classList.toggle("is-pdf-view", on);
  if (on) {
    applyPdfViewToSlides();
    window.scrollTo({ top: 0, behavior: "smooth" });
    setExportStatus("PDF version — scroll the big slides, then WhatsApp PDF when ready.", "success");
    els.statusBar.textContent = "PDF version — export matches what you see on screen";
  } else {
    els.deck?.querySelectorAll(".sp-slide").forEach((slide, index) => {
      slide.classList.remove("sp-slide--export-capture");
      slide.classList.toggle("sp-slide--active", index === state.slideIndex);
      slide.style.removeProperty("--sp-export-w");
      slide.style.removeProperty("--sp-export-h");
    });
    setExportStatus("");
    highlightSlide(state.slideIndex);
    els.statusBar.textContent = `${state.report?.opponent?.name || ""} · deck view`;
  }
}

function updatePresentChrome() {
  const total = state.slides.length;
  const index = total ? state.slideIndex + 1 : 0;
  if (els.presentCount) {
    els.presentCount.textContent = total ? `${index} / ${total}` : "";
  }
}

function setPresent(on) {
  if (on && document.body.classList.contains("is-pdf-view")) setPdfView(false);
  document.body.classList.toggle("is-present", on);
  if (els.presentBtn) els.presentBtn.textContent = on ? "Exit present" : "Present";
  if (on) {
    try {
      document.documentElement.requestFullscreen();
    } catch {
      /* ignore */
    }
    highlightSlide(state.slideIndex);
    updatePresentChrome();
  } else {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    highlightSlide(state.slideIndex);
  }
}

function setModeButtonsEnabled(enabled) {
  if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.disabled = !enabled;
  if (els.pdfViewBtn) els.pdfViewBtn.disabled = !enabled;
  if (els.presentBtn) els.presentBtn.disabled = !enabled;
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

function exportWhatsappPdfBaseName() {
  const opponent = slugifyExportPart(state.report?.opponent?.name || "opponent").toLowerCase();
  return `port-vale-set-piece-${opponent}-whatsapp`;
}

async function captureSetPieceSlides(options = {}) {
  const layoutWidth = options.layoutWidth ?? options.width ?? SLIDE_EXPORT_WIDTH;
  const layoutHeight = options.layoutHeight ?? options.height ?? SLIDE_EXPORT_HEIGHT;
  const outputWidth = options.width ?? layoutWidth;
  const outputHeight = options.height ?? layoutHeight;
  const scale = options.scale ?? SLIDE_EXPORT_SCALE;
  const mimeType = options.mimeType ?? "image/png";
  const quality = options.quality ?? 0.92;
  if (typeof html2canvas !== "function") {
    throw new Error("Export unavailable — reload the page.");
  }

  const wasPdfView = document.body.classList.contains("is-pdf-view");
  const wasPresent = document.body.classList.contains("is-present");
  if (wasPresent) setPresent(false);
  if (!wasPdfView) setPdfView(true);

  const slides = [...els.deck.querySelectorAll(".sp-slide")];
  if (!slides.length) throw new Error("Load a report before exporting.");

  if (document.fonts?.ready) {
    try {
      await document.fonts.ready;
    } catch {
      /* ignore font readiness errors */
    }
  }

  els.app?.classList.add("sp-app--exporting");
  document.body.classList.add("is-exporting");
  const pages = [];
  const previousIndex = state.slideIndex;

  try {
    for (let index = 0; index < slides.length; index += 1) {
      const slide = slides[index];
      highlightSlide(index);
      slide.scrollIntoView({ behavior: "instant", block: "center" });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      await waitForExportImages(slide, 8000);
      await new Promise((resolve) => window.setTimeout(resolve, 80));

      const backgroundColor = "#ffffff";
      const saved = {
        width: slide.style.width,
        height: slide.style.height,
        margin: slide.style.margin,
        maxWidth: slide.style.maxWidth,
        aspectRatio: slide.style.aspectRatio,
        boxShadow: slide.style.boxShadow,
        borderRadius: slide.style.borderRadius,
        overflow: slide.style.overflow,
        transform: slide.style.transform,
      };

      slide.style.width = `${layoutWidth}px`;
      slide.style.height = `${layoutHeight}px`;
      slide.style.margin = "0 auto";
      slide.style.maxWidth = "none";
      slide.style.aspectRatio = "auto";
      slide.style.boxShadow = "none";
      slide.style.borderRadius = "0";
      slide.style.overflow = "hidden";
      slide.style.transform = "none";

      const scrollX = window.scrollX;
      const scrollY = window.scrollY;
      void slide.offsetWidth;
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

      let canvas;
      try {
        canvas = await html2canvas(slide, {
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
          scrollX: -window.scrollX,
          scrollY: -window.scrollY,
        });
      } finally {
        slide.style.width = saved.width;
        slide.style.height = saved.height;
        slide.style.margin = saved.margin;
        slide.style.maxWidth = saved.maxWidth;
        slide.style.aspectRatio = saved.aspectRatio;
        slide.style.boxShadow = saved.boxShadow;
        slide.style.borderRadius = saved.borderRadius;
        slide.style.overflow = saved.overflow;
        slide.style.transform = saved.transform;
        window.scrollTo(scrollX, scrollY);
      }

      const framed = downscaleCanvas(canvas, outputWidth, outputHeight, backgroundColor);
      const title = slugifyExportPart(slide.dataset.slideTitle || `slide-${index + 1}`);
      pages.push({
        imageData: framed.toDataURL(mimeType, quality),
        filename: `${title}.${mimeType === "image/jpeg" ? "jpg" : "png"}`,
        width: framed.width,
        height: framed.height,
      });
      const label = options.progressLabel || "Exporting";
      setExportStatus(`${label}… ${index + 1}/${slides.length}`, "loading");
      setStatus(`${label}… ${index + 1}/${slides.length}`, "loading");
    }
  } finally {
    document.body.classList.remove("is-exporting");
    els.app?.classList.remove("sp-app--exporting");
    highlightSlide(previousIndex);
  }

  return pages;
}

async function exportWhatsappPdf() {
  if (!state.report || !els.exportWhatsappPdfBtn) return;
  setModeButtonsEnabled(false);
  els.refreshBtn.disabled = true;
  setExportOverlay("Building WhatsApp PDF (Chrome)…");
  setStatus("Building WhatsApp PDF via real Chrome screenshots…", "loading");
  const wasPresent = document.body.classList.contains("is-present");
  if (wasPresent) setPresent(false);
  document.body.classList.add("is-exporting");
  try {
    if (!window.PortValeWysiwygExport) {
      throw new Error("WYSIWYG export helper failed to load — hard refresh and try again.");
    }
    const slides = [...els.deck.querySelectorAll(".sp-slide")];
    const pack = await window.PortValeWysiwygExport.captureSlideHtmlPages({
      slides,
      stripClasses: ["sp-slide--export-capture", "sp-slide--exporting"],
      activeClass: "sp-slide--active",
      background: "#0b1220",
      beforeSlide: (index) => highlightSlide(index),
      onProgress: (msg) => {
        setExportStatus(msg, "loading");
        setStatus(msg, "loading");
      },
    });
    setExportOverlay("Rendering PDF in Chrome…");
    const filename = `${exportWhatsappPdfBaseName()}.pdf`;
    const result = await window.PortValeWysiwygExport.downloadPdf({
      ...pack,
      filename,
      documentTitle: `Set Piece Pre-Match · ${state.report?.opponent?.name || "Opponent"}`,
      opponentName: state.report?.opponent?.name || "opponent",
      endpoint: "/api/set-piece-pre-match/export-whatsapp-pdf",
    });
    const n = result.pageCount;
    if (result.savedPath) {
      setStatus(`WhatsApp PDF ready · ${n} slides · ${result.sizeMb} MB · Desktop`, "");
      setExportStatus(`PDF downloaded · ${n} slides`, "success");
      els.statusBar.textContent = `Share from Desktop: ${result.savedPath.split("/").pop()}`;
    } else {
      setStatus(`WhatsApp PDF downloaded · ${n} slides · ${result.sizeMb} MB`, "");
      setExportStatus(`PDF downloaded · ${n} slides`, "success");
      els.statusBar.textContent = "PDF ready — attach in WhatsApp";
    }
  } catch (error) {
    setStatus(error.message || "WhatsApp PDF export failed", "error");
    setExportStatus(error.message || "WhatsApp PDF export failed", "error");
  } finally {
    document.body.classList.remove("is-exporting");
    setExportOverlay("");
    setModeButtonsEnabled(Boolean(state.report));
    els.refreshBtn.disabled = false;
    if (wasPresent) setPresent(true);
  }
}

function renderEmptyDeck(message) {
  if (document.body.classList.contains("is-present")) setPresent(false);
  if (document.body.classList.contains("is-pdf-view")) setPdfView(false);
  state.report = null;
  state.slides = [];
  state.slideIndex = 0;
  els.deck.innerHTML = `<div class="sp-placeholder">${escapeHtml(message)}</div>`;
  els.statusBar.textContent = message;
  els.refreshBtn.disabled = true;
  setModeButtonsEnabled(false);
  updateSlideNav();
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `sp-status sp-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatKickoff(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });
}

function display(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function pct(value) {
  if (value === null || value === undefined) return "—";
  return `${value}%`;
}

function parseRankNumber(rankLabel) {
  const match = String(rankLabel || "").match(/(\d+)/);
  return match ? Number(match[1]) : null;
}

function rankBarPct(rankLabel, leagueSize = 24) {
  const rank = parseRankNumber(rankLabel);
  const size = Number(leagueSize) || 24;
  if (!rank || rank < 1) return 28;
  return Math.max(10, Math.round(((size - rank + 1) / size) * 100));
}

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      const parsed = JSON.parse(detail);
      detail = parsed.detail || detail;
    } catch {
      /* keep text */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

function crestUrl(team) {
  if (team?.badge_url) return team.badge_url;
  const name = String(team?.name || "").toLowerCase();
  if (name.includes("port vale")) return "/standalone/port-vale-badge.png?v=2";
  return team?.image_url || team?.imageUrl || team?.image || "";
}

function crestInitials(name) {
  return String(name || "?")
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function crestHtml(team, className = "sp-cover__crest") {
  const name = team?.name || "Team";
  const image = crestUrl(team);
  if (image) {
    return `<img class="${className}" src="${escapeHtml(image)}" alt="${escapeHtml(name)}" />`;
  }
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return `<div class="sp-cover__crest-fallback" aria-hidden="true">${escapeHtml(initial)}</div>`;
}

function matchBarCrestHtml(team) {
  const name = team?.name || "?";
  const src = crestUrl(team);
  const initials = crestInitials(name);
  if (src) {
    return `<img class="sp-match-bar__crest" src="${escapeHtml(src)}" alt="${escapeHtml(name)}" onerror="this.onerror=null;this.replaceWith(Object.assign(document.createElement('div'),{className:'sp-match-bar__crest-fallback',textContent:'${escapeHtml(initials)}'}))" />`;
  }
  return `<div class="sp-match-bar__crest-fallback">${escapeHtml(initials)}</div>`;
}

function slideShell({ title, subtitle, body, foot = "Port Vale FC · Set Piece Pre-Match", barClass = "" }) {
  return `
    <div class="sp-slide__bar ${barClass}">${escapeHtml(title)}</div>
    ${subtitle ? `<div class="sp-slide__sub">${escapeHtml(subtitle)}</div>` : ""}
    <div class="sp-slide__body">${body}</div>
    <div class="sp-slide__foot">${escapeHtml(foot)}</div>
  `;
}

function renderCoverSlide(report) {
  const fixture = report.fixture || {};
  const portVale = fixture.port_vale || { name: "Port Vale" };
  const opponent = fixture.opponent || report.opponent || { name: "Opponent" };
  const dateLine = formatKickoff(fixture.scheduled_date);
  const venue = fixture.is_home ? "Home" : "Away";
  const windowLabel = report.match_window_label || "Season";

  return `<section class="sp-slide sp-slide--cover" data-slide-title="Cover">
    <div class="sp-cover__accent" aria-hidden="true"></div>
    <div class="sp-cover__corner sp-cover__corner--left" aria-hidden="true"></div>
    <div class="sp-cover__corner sp-cover__corner--right" aria-hidden="true"></div>
    <div class="sp-cover__body">
      <p class="sp-cover__kicker">Opposition set-piece briefing</p>
      <div class="sp-cover__matchup">
        <div class="sp-cover__team">
          ${crestHtml(portVale)}
          <p class="sp-cover__team-name">${escapeHtml(portVale.name || "Port Vale")}</p>
        </div>
        <p class="sp-cover__vs">vs</p>
        <div class="sp-cover__team">
          ${crestHtml(opponent)}
          <p class="sp-cover__team-name">${escapeHtml(opponent.name || "Opponent")}</p>
        </div>
      </div>
      ${dateLine ? `<p class="sp-cover__date">${escapeHtml(dateLine)}</p>` : ""}
      <p class="sp-cover__meta">${escapeHtml(venue)} · ${escapeHtml(windowLabel)} · left vs right delivery · League One</p>
    </div>
    <div class="sp-cover__footer">Set Piece <span>Pre Match</span></div>
  </section>`;
}

function renderRankingsSlide(report) {
  const metrics = report.team_metrics || [];
  const opponent = report.opponent?.name || "Opponent";
  if (!metrics.length) {
    return `<section class="sp-slide" data-slide-title="Rankings">${slideShell({
      title: "Set Play Rankings",
      subtitle: opponent,
      body: `<div class="sp-empty">No set-play squad KPIs available.</div>`,
    })}</section>`;
  }

  const cards = metrics
    .map((metric) => {
      const rankNum = parseRankNumber(metric.rank);
      const elite = rankNum != null && rankNum <= 5;
      const warn = metric.higher_better === false;
      const bar = rankBarPct(metric.rank);
      return `
        <div class="sp-rank-card${elite ? " sp-rank-card--elite" : ""}${warn ? " sp-rank-card--warn" : ""}">
          <div>
            <div class="sp-rank-card__label">${escapeHtml(metric.label)}</div>
            <div class="sp-rank-card__value">${escapeHtml(display(metric.display ?? metric.value))}</div>
          </div>
          <div>
            <span class="sp-rank-card__rank">${metric.rank ? `League ${escapeHtml(metric.rank)}` : "—"}</span>
            <div class="sp-rank-card__track" aria-hidden="true">
              <span class="sp-rank-card__bar" style="width:${bar}%"></span>
            </div>
          </div>
        </div>`;
    })
    .join("");

  return `<section class="sp-slide" data-slide-title="Rankings">${slideShell({
    title: "Set Play Rankings",
    subtitle: `${opponent} · Full season Impect KPIs`,
    body: `<div class="sp-rank-grid">${cards}</div>`,
  })}</section>`;
}

function sideFamilyKpis(block, { dangerContact = false } = {}) {
  const season = block?.season || {};
  const recentRanks = block?.ranks || {};
  const seasonRanks = season.ranks || {};
  const higherBetter = {
    ...(season.rankHigherBetter || {}),
    ...(block?.rankHigherBetter || {}),
  };
  const specs = [
    {
      key: "avgChains",
      recent: display(block?.avgChains),
      season: display(season.avgChains),
      label: "Per game",
      accent: true,
    },
    {
      key: "deliverySuccessPct",
      recent: pct(block?.deliverySuccessPct),
      season: pct(season.deliverySuccessPct),
      label: "Delivery success",
    },
    {
      key: "firstContactWonPct",
      recent: pct(block?.firstContactWonPct),
      season: pct(season.firstContactWonPct),
      label: "1st contact won",
      danger: dangerContact,
    },
    {
      key: "avgShotXg",
      recent: display(block?.avgShotXg),
      season: display(season.avgShotXg),
      label: "xG / game",
      accent: true,
    },
    {
      key: "goals",
      recent: display(block?.goals),
      season: display(season.goals),
      label: "Goals",
    },
    {
      key: "shots",
      recent: display(block?.shots),
      season: display(season.shots),
      label: "Shots",
    },
    {
      key: "intoBoxPct",
      recent: pct(block?.intoBoxPct),
      season: pct(season.intoBoxPct),
      label: "Into box %",
    },
    {
      key: "avgGoals",
      recent: display(block?.avgGoals),
      season: display(season.avgGoals),
      label: "Goals / game",
    },
  ];

  return specs.map((kpi) => {
    const recentRank = recentRanks[kpi.key] || null;
    const seasonRank = seasonRanks[kpi.key] || null;
    const rankNum = parseRankNumber(seasonRank || recentRank);
    const prefersHigh = higherBetter[kpi.key] !== false;
    const elite = rankNum != null && rankNum <= 5 && prefersHigh;
    const warn = rankNum != null && rankNum <= 5 && !prefersHigh;
    return { ...kpi, recentRank, seasonRank, elite, warn };
  });
}

function familyRestartKey(familyKey) {
  return familyKey === "corners" ? "corner" : "freeKick";
}

function familyContactPoints(side, familyKey) {
  const want = familyRestartKey(familyKey);
  return (side?.firstContactPoints || []).filter((point) => {
    if (point.restartFamily) return point.restartFamily === want;
    const label = String(point.typeLabel || "").toLowerCase();
    if (want === "corner") return label.includes("corner");
    return label.includes("free") || label.includes("fk");
  });
}

function familyLeadersFromPoints(points, { limit = 5 } = {}) {
  const buckets = new Map();
  for (const point of points || []) {
    if (point.focusContact === false) continue;
    const id = point.playerId ?? point.player_id;
    if (id == null) continue;
    const key = String(id);
    const bucket = buckets.get(key) || {
      player_id: id,
      name: point.playerName || point.player_name || `Player ${id}`,
      initials: point.playerInitials || point.player_initials || "?",
      contacts: 0,
      into_box: 0,
    };
    bucket.contacts += 1;
    if (point.intoBox) bucket.into_box += 1;
    if (point.playerName && bucket.name.startsWith("Player ")) {
      bucket.name = point.playerName;
    }
    buckets.set(key, bucket);
  }
  return [...buckets.values()]
    .sort(
      (a, b) =>
        b.contacts - a.contacts ||
        b.into_box - a.into_box ||
        String(a.name).localeCompare(String(b.name))
    )
    .slice(0, limit);
}

function familyTrendBars(block) {
  const season = block?.season || {};
  const rows = [
    {
      label: "Per game",
      recent: Number(block?.avgChains),
      season: Number(season.avgChains),
    },
    {
      label: "Delivery %",
      recent: Number(block?.deliverySuccessPct),
      season: Number(season.deliverySuccessPct),
      pct: true,
    },
    {
      label: "xG / game",
      recent: Number(block?.avgShotXg),
      season: Number(season.avgShotXg),
    },
    {
      label: "Into box %",
      recent: Number(block?.intoBoxPct),
      season: Number(season.intoBoxPct),
      pct: true,
    },
  ].filter(
    (row) =>
      Number.isFinite(row.recent) || Number.isFinite(row.season)
  );
  if (!rows.length) return "";
  return `<div class="sp-side-trends">${rows
    .map((row) => {
      const recent = Number.isFinite(row.recent) ? row.recent : 0;
      const seasonVal = Number.isFinite(row.season) ? row.season : 0;
      const max = Math.max(recent, seasonVal, 0.0001);
      const recentPct = Math.max(8, Math.round((recent / max) * 100));
      const seasonPct = Math.max(8, Math.round((seasonVal / max) * 100));
      const recentLabel = row.pct ? pct(row.recent) : display(row.recent);
      const seasonLabel = row.pct ? pct(row.season) : display(row.season);
      return `
        <div class="sp-side-trend">
          <div class="sp-side-trend__label">${escapeHtml(row.label)}</div>
          <div class="sp-side-trend__tracks">
            <div class="sp-side-trend__track">
              <span class="sp-side-trend__bar sp-side-trend__bar--l8" style="width:${recentPct}%"></span>
              <span class="sp-side-trend__val">${escapeHtml(recentLabel)}</span>
            </div>
            <div class="sp-side-trend__track">
              <span class="sp-side-trend__bar sp-side-trend__bar--szn" style="width:${seasonPct}%"></span>
              <span class="sp-side-trend__val">${escapeHtml(seasonLabel)}</span>
            </div>
          </div>
        </div>`;
    })
    .join("")}</div>`;
}

function familyLeadersHtml(rows, { defending = false } = {}) {
  if (!rows?.length) {
    return `<div class="sp-side-mini-empty">No first-contact winners</div>`;
  }
  const hint = defending ? "clears" : "wins";
  return `<div class="sp-side-mini-leaders">
    <div class="sp-side-mini-leaders__title">First contact ${escapeHtml(hint)}</div>
    ${rows
      .map((row, index) => {
        return `
          <div class="sp-side-mini-leader">
            <span class="sp-side-mini-leader__rank">${index + 1}</span>
            <span class="sp-side-mini-leader__name">${escapeHtml(row.name)}</span>
            <span class="sp-side-mini-leader__stat">${escapeHtml(row.contacts)} · ${escapeHtml(row.into_box)} box</span>
          </div>`;
      })
      .join("")}
  </div>`;
}

function formatXg(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "0.00";
  return n.toFixed(2);
}

function forTeamKpis(side) {
  return sideFamilyKpis(side, { dangerContact: false }).filter((kpi) =>
    ["avgChains", "deliverySuccessPct", "firstContactWonPct", "avgShotXg", "goals", "intoBoxPct"].includes(
      kpi.key
    )
  );
}

function renderMiniLeaderList(rows, { title, empty, stat } = {}) {
  if (!rows?.length) {
    return `<div class="sp-side-mini-leaders sp-side-mini-leaders--tight">
      <div class="sp-side-mini-leaders__title">${escapeHtml(title)}</div>
      <div class="sp-side-mini-empty sp-side-mini-empty--tight">${escapeHtml(empty || "—")}</div>
    </div>`;
  }
  return `<div class="sp-side-mini-leaders sp-side-mini-leaders--tight">
    <div class="sp-side-mini-leaders__title">${escapeHtml(title)}</div>
    ${rows
      .map((row, index) => {
        return `
          <div class="sp-side-mini-leader">
            <span class="sp-side-mini-leader__rank">${index + 1}</span>
            <span class="sp-side-mini-leader__name">${escapeHtml(row.name || "—")}</span>
            <span class="sp-side-mini-leader__stat">${escapeHtml(stat(row))}</span>
          </div>`;
      })
      .join("")}
  </div>`;
}

function teamKpisSingle(side, { dangerContact = false } = {}) {
  const ranks = side?.ranks || {};
  const higherBetter = side?.rankHigherBetter || {};
  const specs = [
    { key: "avgChains", value: display(side?.avgChains), label: "Per game", accent: true },
    { key: "deliverySuccessPct", value: pct(side?.deliverySuccessPct), label: "Delivery success" },
    {
      key: "firstContactWonPct",
      value: pct(side?.firstContactWonPct),
      label: "1st contact won",
      danger: dangerContact,
    },
    { key: "avgShotXg", value: display(side?.avgShotXg), label: "xG / game", accent: true },
    { key: "goals", value: display(side?.goals), label: "Goals" },
    { key: "intoBoxPct", value: pct(side?.intoBoxPct), label: "Into box %" },
  ];
  return specs.map((kpi) => {
    const rank = ranks[kpi.key] || null;
    const rankNum = parseRankNumber(rank);
    const prefersHigh = higherBetter[kpi.key] !== false;
    const elite = rankNum != null && rankNum <= 5 && prefersHigh;
    const warn = rankNum != null && rankNum <= 5 && !prefersHigh;
    return { ...kpi, rank, elite, warn };
  });
}

function clampPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

function teamMetricTone(side, key, { danger = false } = {}) {
  const ranks = side?.ranks || {};
  const higherBetter = side?.rankHigherBetter || {};
  const rank = ranks[key] || null;
  const rankNum = parseRankNumber(rank);
  const prefersHigh = higherBetter[key] !== false;
  const elite = rankNum != null && rankNum <= 5 && prefersHigh;
  const warn = (rankNum != null && rankNum <= 5 && !prefersHigh) || danger;
  return { rank, elite, warn };
}

function renderTeamMeter(side, { key, label, value, danger = false } = {}) {
  const tone = teamMetricTone(side, key, { danger });
  const bar = clampPct(value);
  const hasValue = value !== null && value !== undefined;
  return `
    <div class="sp-team-meter${tone.elite ? " sp-team-meter--elite" : ""}${tone.warn ? " sp-team-meter--warn" : ""}">
      <div class="sp-team-meter__row">
        <span class="sp-team-meter__label">${escapeHtml(label)}</span>
        <span class="sp-team-meter__value">${escapeHtml(hasValue ? pct(value) : "—")}</span>
      </div>
      <div class="sp-team-meter__track" aria-hidden="true">
        <span class="sp-team-meter__fill" style="width:${hasValue ? bar : 0}%"></span>
      </div>
      ${tone.rank ? `<span class="sp-team-meter__rank">Lg ${escapeHtml(tone.rank)}</span>` : ""}
    </div>`;
}

function renderTeamBoard(side, { dangerContact = false, accent = "gold", games = "0" } = {}) {
  const leftChains = Number(side?.left?.chains) || 0;
  const rightChains = Number(side?.right?.chains) || 0;
  const sideTotal = leftChains + rightChains;
  const leftShare = sideTotal ? Math.round((leftChains / sideTotal) * 100) : 0;
  const rightShare = sideTotal ? 100 - leftShare : 0;
  const goalsTone = teamMetricTone(side, "goals");
  const perGameTone = teamMetricTone(side, "avgChains");
  const xgTone = teamMetricTone(side, "avgShotXg");

  return `
    <div class="sp-team-board sp-team-board--${escapeHtml(accent)}">
      <div class="sp-team-board__head">
        <div>
          <h3 class="sp-side-family__title">Team</h3>
          <p class="sp-team-board__eyebrow">Season totals</p>
        </div>
        <span class="sp-team-board__games">${escapeHtml(games)} games</span>
      </div>

      <div class="sp-team-heroes">
        <div class="sp-team-hero${perGameTone.elite ? " sp-team-hero--elite" : ""}">
          <div class="sp-team-hero__value">${escapeHtml(display(side?.avgChains))}</div>
          <div class="sp-team-hero__label">Per game</div>
          <div class="sp-team-hero__sub">${escapeHtml(display(side?.chains, "0"))} total</div>
        </div>
        <div class="sp-team-hero${goalsTone.elite || xgTone.elite ? " sp-team-hero--elite" : ""}${goalsTone.warn ? " sp-team-hero--warn" : ""}">
          <div class="sp-team-hero__value">${escapeHtml(display(side?.goals))}</div>
          <div class="sp-team-hero__label">Goals</div>
          <div class="sp-team-hero__sub">${escapeHtml(display(side?.avgShotXg))} xG / game</div>
        </div>
      </div>

      <div class="sp-team-meters">
        ${renderTeamMeter(side, {
          key: "deliverySuccessPct",
          label: "Delivery success",
          value: side?.deliverySuccessPct,
        })}
        ${renderTeamMeter(side, {
          key: "firstContactWonPct",
          label: "1st contact won",
          value: side?.firstContactWonPct,
          danger: dangerContact,
        })}
        ${renderTeamMeter(side, {
          key: "intoBoxPct",
          label: "Into box",
          value: side?.intoBoxPct,
        })}
      </div>

      <div class="sp-team-mix">
        <div class="sp-team-mix__head">
          <span class="sp-team-mix__title">Delivery side</span>
          <span class="sp-team-mix__total">${escapeHtml(display(sideTotal, "0"))} set plays</span>
        </div>
        <div class="sp-team-mix__bar" aria-hidden="true">
          <span class="sp-team-mix__seg sp-team-mix__seg--left" style="flex:${Math.max(leftShare, sideTotal ? 1 : 0)}"></span>
          <span class="sp-team-mix__seg sp-team-mix__seg--right" style="flex:${Math.max(rightShare, sideTotal ? 1 : 0)}"></span>
        </div>
        <div class="sp-team-mix__stats">
          <div class="sp-team-mix__side sp-team-mix__side--left">
            <span class="sp-team-mix__dot"></span>
            <div>
              <strong>Left</strong>
              <span>${escapeHtml(display(leftChains, "0"))} · ${escapeHtml(String(leftShare))}%</span>
            </div>
          </div>
          <div class="sp-team-mix__side sp-team-mix__side--right">
            <span class="sp-team-mix__dot"></span>
            <div>
              <strong>Right</strong>
              <span>${escapeHtml(display(rightChains, "0"))} · ${escapeHtml(String(rightShare))}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>`;
}

function wonContactPoints(points) {
  return (points || []).filter((point) => firstContactWon(point) === true);
}

function deliverySideOf(point) {
  const side = String(point?.deliverySide || point?.side || "").toLowerCase();
  return side === "left" || side === "right" ? side : null;
}

function restartFamilyOf(point) {
  const family = String(point?.restartFamily || "").toLowerCase();
  if (family === "corner" || family === "freekick") {
    return family === "freekick" ? "freeKick" : "corner";
  }
  const label = String(point?.typeLabel || "").toLowerCase();
  if (label.includes("corner")) return "corner";
  if (label.includes("free")) return "freeKick";
  return null;
}

function sideContactPoints(side, deliverySide) {
  return wonContactPoints(side?.firstContactPoints).filter(
    (point) => deliverySideOf(point) === deliverySide
  );
}

function sideGoalPoints(side, deliverySide) {
  return (side?.goalPoints || []).filter((point) => deliverySideOf(point) === deliverySide);
}

function deliveryLegendHtml({ compact = false } = {}) {
  return `<div class="sp-map-legend${compact ? " sp-map-legend--mini" : ""}">
    <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--left"></span>Left</span>
    <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--right"></span>Right</span>
  </div>`;
}

function familyLegendHtml({ compact = false } = {}) {
  return `<div class="sp-map-legend${compact ? " sp-map-legend--mini" : ""}">
    <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--corner"></span>Corner</span>
    <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--fk"></span>Free kick</span>
  </div>`;
}

function familyWonContactPoints(side, familyKey) {
  return wonContactPoints(familyContactPoints(side, familyKey));
}

function familyGoalPoints(side, familyKey) {
  const want = familyRestartKey(familyKey);
  return (side?.goalPoints || []).filter((point) => {
    if (point.restartFamily) return point.restartFamily === want;
    const label = String(point.typeLabel || "").toLowerCase();
    if (want === "corner") return label.includes("corner");
    return label.includes("free") || label.includes("fk");
  });
}

function renderFamilyColumn(
  block,
  {
    title,
    familyKey = "corners",
    side = {},
    pitch = {},
    tone = "gold",
    defending = false,
  } = {}
) {
  const volume = display(block?.chains, "0");
  const perGame = display(block?.avgChains);
  const points = familyWonContactPoints(side, familyKey);
  const goalPts = familyGoalPoints(side, familyKey);
  const contacts = (
    block?.firstContactLeaders?.length
      ? block.firstContactLeaders
      : familyLeadersFromPoints(points, { limit: 5 })
  ).slice(0, 5);
  const goals = (block?.goalLeaders || []).slice(0, 4);
  const xg = (block?.xgLeaders || []).slice(0, 4);
  const leftCount = points.filter((pt) => deliverySideOf(pt) === "left").length;
  const rightCount = points.filter((pt) => deliverySideOf(pt) === "right").length;
  const mapHtml =
    points.length || goalPts.length
      ? renderFirstContactPitch(points, pitch, {
          drawW: 300,
          compact: true,
          bySide: true,
          goals: goalPts,
        })
      : `<div class="sp-side-mini-empty">No won first contacts</div>`;

  const lists = defending
    ? `${renderMiniLeaderList(contacts, {
        title: "Who clears",
        empty: "No defensive first contacts",
        stat: (row) => `${display(row.contacts, "0")} · ${display(row.into_box, "0")} box`,
      })}
      ${
        goals.length
          ? renderMiniLeaderList(goals, {
              title: "Goals conceded",
              empty: "No goals conceded",
              stat: (row) => `${display(row.goals, "0")} · ${formatXg(row.xg)} xG`,
            })
          : ""
      }
      ${renderMiniLeaderList(xg, {
        title: "Highest xG",
        empty: "No xG against",
        stat: (row) => `${formatXg(row.xg)} · ${display(row.goals, "0")} g`,
      })}`
    : `${renderMiniLeaderList(contacts, {
        title: "Most 1st contacts",
        empty: "No won first contacts",
        stat: (row) => `${display(row.contacts, "0")} · ${display(row.into_box, "0")} box`,
      })}
      ${renderMiniLeaderList(goals, {
        title: "Most goals",
        empty: "No goals",
        stat: (row) => `${display(row.goals, "0")} · ${formatXg(row.xg)} xG`,
      })}
      ${renderMiniLeaderList(xg, {
        title: "Highest xG",
        empty: "No xG",
        stat: (row) => `${formatXg(row.xg)} · ${display(row.goals, "0")} g`,
      })}`;

  return `
    <div class="sp-for-family sp-for-family--${escapeHtml(tone)}${defending ? " sp-for-family--against" : ""}">
      <div class="sp-side-family__head">
        <h3 class="sp-side-family__title">${escapeHtml(title)}</h3>
        <span class="sp-side-family__count"><strong>${escapeHtml(volume)}</strong> · ${escapeHtml(perGame)} / game</span>
      </div>
      <div class="sp-for-family__map">
        <div class="sp-side-mini-map">
          <div class="sp-side-mini-map__title">${defending ? "Clears" : "Won 1st contacts"} · ${escapeHtml(String(points.length))}</div>
          <div class="sp-side-mini-map__split">
            <span><i class="sp-map-legend__swatch sp-map-legend__swatch--left"></i>${escapeHtml(String(leftCount))} left</span>
            <span><i class="sp-map-legend__swatch sp-map-legend__swatch--right"></i>${escapeHtml(String(rightCount))} right</span>
          </div>
          <div class="sp-side-mini-map__pitch">${mapHtml}</div>
        </div>
      </div>
      <div class="sp-for-family__lists${defending ? " sp-for-family__lists--against" : ""}">
        ${lists}
      </div>
    </div>`;
}

function renderForSlide(report, { twoPager = false } = {}) {
  const side = report.set_plays?.attacking || {};
  const pitch = report.set_plays?.pitch || {};
  const opponent = report.opponent?.name || "Opponent";
  const title = twoPager ? "For" : "Attacking Set Plays";
  const games = display(side.gameCount || report.season_games, "0");

  return `<section class="sp-slide" data-slide-title="${title}">${slideShell({
    title,
    subtitle: `${opponent} · Season totals · corners vs free kicks · colour = left / right delivery`,
    barClass: "sp-slide__bar--gold",
    body: `
      <div class="sp-for">
        <div class="sp-for-totals">
          ${renderTeamBoard(side, { accent: "gold", games })}
        </div>
        ${renderFamilyColumn(side.corners || {}, {
          title: "Corners",
          familyKey: "corners",
          side,
          pitch,
          tone: "gold",
        })}
        ${renderFamilyColumn(side.freeKicks || {}, {
          title: "Free kicks",
          familyKey: "freeKicks",
          side,
          pitch,
          tone: "teal",
        })}
      </div>`,
  })}</section>`;
}

function renderAgainstSlide(report, { twoPager = false } = {}) {
  const side = report.set_plays?.defending || {};
  const pitch = report.set_plays?.pitch || {};
  const opponent = report.opponent?.name || "Opponent";
  const title = twoPager ? "Against" : "Defending Set Plays";
  const games = display(side.gameCount || report.season_games, "0");

  return `<section class="sp-slide" data-slide-title="${title}">${slideShell({
    title,
    subtitle: `${opponent} · Season totals · corners vs free kicks · colour = left / right delivery`,
    barClass: "sp-slide__bar--orange",
    body: `
      <div class="sp-for">
        <div class="sp-for-totals">
          ${renderTeamBoard(side, { dangerContact: true, accent: "orange", games })}
        </div>
        ${renderFamilyColumn(side.corners || {}, {
          title: "Corners",
          familyKey: "corners",
          side,
          pitch,
          tone: "gold",
          defending: true,
        })}
        ${renderFamilyColumn(side.freeKicks || {}, {
          title: "Free kicks",
          familyKey: "freeKicks",
          side,
          pitch,
          tone: "teal",
          defending: true,
        })}
      </div>`,
  })}</section>`;
}

function renderSideSlide(report, sideKey, { twoPager = false } = {}) {
  if (sideKey === "attacking") {
    return renderForSlide(report, { twoPager });
  }
  return renderAgainstSlide(report, { twoPager });
}

function opponentPhotoUrl(name, report = state.report) {
  if (!name) return null;
  const params = new URLSearchParams({ name });
  if (report?.opponent?.name) params.set("club", report.opponent.name);
  if (report?.season) params.set("season", String(report.season));
  return `/api/pre-match/player-photo?${params.toString()}`;
}

const HEIGHT_BAND_ORDER = [
  "6'4\"+",
  "6'3\"",
  "6'2\"",
  "6'1\"",
  "6'0\"",
  "5'11\"",
  "5'10\"",
  "<5'9\"",
];
const HEIGHT_UNKNOWN_BAND = "No height";

function normalizeBandLabel(label) {
  return String(label || "")
    .replace(/[’′]/g, "'")
    .replace(/[“”″]/g, '"')
    .trim();
}

function heightBandFromPlayer(player) {
  let cm = Number(player?.height_cm);
  if (!Number.isFinite(cm) || cm <= 0) {
    const raw = String(player?.height || "");
    const imperial = raw.match(/(\d+)\s*(?:ft|'|’)\s*(\d{1,2})/i);
    if (imperial) {
      cm = Math.round((Number(imperial[1]) * 12 + Number(imperial[2])) * 2.54);
    }
  }
  if (!Number.isFinite(cm) || cm <= 0) return null;
  const inches = Math.round(cm / 2.54);
  if (inches >= 76) return "6'4\"+";
  if (inches === 75) return "6'3\"";
  if (inches === 74) return "6'2\"";
  if (inches === 73) return "6'1\"";
  if (inches === 72) return "6'0\"";
  if (inches === 71) return "5'11\"";
  if (inches === 70) return "5'10\"";
  return "<5'9\"";
}

function cloneHeightPlayer(player) {
  return {
    player_id: player.player_id,
    name: player.name,
    surname: player.surname,
    shirt_number: player.shirt_number,
    position_abbr: player.position_abbr,
    height_cm: player.height_cm,
    height: player.height,
    band: player.band,
    photo_url: player.photo_url,
  };
}

function buildHeightEditState(chart, squad = []) {
  const bands = HEIGHT_BAND_ORDER.map((label) => ({ label, players: [] }));
  const bandByLabel = Object.fromEntries(bands.map((band) => [band.label, band]));
  const placed = new Set();
  const unknown = [];

  const resolvableBand = (player) => {
    const fromApi = normalizeBandLabel(player?.band);
    if (fromApi && HEIGHT_BAND_ORDER.includes(fromApi)) return fromApi;
    return heightBandFromPlayer(player);
  };

  const place = (player) => {
    if (!player) return;
    const id = String(player.player_id ?? player.name ?? "");
    if (!id || placed.has(id)) return;
    placed.add(id);
    const bandLabel = resolvableBand(player);
    if (bandLabel && bandByLabel[bandLabel]) {
      bandByLabel[bandLabel].players.push(cloneHeightPlayer({ ...player, band: bandLabel }));
      return;
    }
    unknown.push(cloneHeightPlayer({ ...player, band: HEIGHT_UNKNOWN_BAND }));
  };

  const sources = [];
  for (const source of chart.bands || []) {
    const label = normalizeBandLabel(source.label);
    for (const player of source.players || []) {
      sources.push({ ...player, band: player.band || label });
    }
  }
  if (Array.isArray(chart.players)) {
    for (const player of chart.players) {
      if (String(player.position_abbr || "").toUpperCase() === "GK") continue;
      sources.push(player);
    }
  }
  for (const player of squad || []) {
    if (String(player.position_abbr || "").toUpperCase() === "GK") continue;
    sources.push(player);
  }
  for (const player of chart.unknown || []) sources.push(player);

  const withBand = [];
  const rest = [];
  for (const player of sources) {
    if (resolvableBand(player)) withBand.push(player);
    else rest.push(player);
  }
  for (const player of withBand) place(player);
  for (const player of rest) place(player);

  return {
    bands,
    unknown,
    excluded_gk: chart.excluded_gk || 0,
  };
}

function ensureHeightEditState(report) {
  const opponentId = report?.opponent?.id ?? report?.fixture?.opponent?.id ?? null;
  const chart = report?.height_chart || {};
  const assigned = Number(chart.count || 0);
  if (
    state.heightEdit &&
    String(state.heightEdit.opponentId) === String(opponentId)
  ) {
    const placed = (state.heightEdit.bands || []).reduce(
      (n, band) => n + (band.players || []).length,
      0
    );
    if (assigned === 0 || placed >= assigned) return state.heightEdit;
  }
  state.heightEdit = {
    opponentId,
    ...buildHeightEditState(chart, report?.squad || []),
  };
  return state.heightEdit;
}

function findHeightPlayer(playerId) {
  const edit = state.heightEdit;
  if (!edit) return null;
  const id = String(playerId);
  for (const player of edit.unknown) {
    if (String(player.player_id) === id) {
      return { player, bandLabel: HEIGHT_UNKNOWN_BAND, list: edit.unknown };
    }
  }
  for (const band of edit.bands) {
    for (const player of band.players) {
      if (String(player.player_id) === id) {
        return { player, bandLabel: band.label, list: band.players };
      }
    }
  }
  return null;
}

function removeHeightPlayer(playerId) {
  const found = findHeightPlayer(playerId);
  if (!found) return null;
  const index = found.list.findIndex((row) => String(row.player_id) === String(playerId));
  if (index < 0) return null;
  const [player] = found.list.splice(index, 1);
  return player;
}

function addHeightPlayer(player, bandLabel, beforePlayerId = null) {
  const edit = state.heightEdit;
  if (!edit || !player) return;
  const targetList =
    bandLabel === HEIGHT_UNKNOWN_BAND
      ? edit.unknown
      : edit.bands.find((band) => band.label === bandLabel)?.players;
  if (!targetList) return;
  player.band = bandLabel;
  if (beforePlayerId != null) {
    const index = targetList.findIndex(
      (row) => String(row.player_id) === String(beforePlayerId)
    );
    if (index >= 0) {
      targetList.splice(index, 0, player);
      return;
    }
  }
  targetList.push(player);
}

function heightPlayerChipHtml(player, report) {
  const shirt =
    player.shirt_number != null && player.shirt_number !== ""
      ? `${player.shirt_number}. `
      : "";
  const photo = player.photo_url || opponentPhotoUrl(player.name, report) || "";
  const photoHtml = photo
    ? `<img class="sp-hc-player__photo" src="${escapeHtml(photo)}" alt="" loading="eager" decoding="async" draggable="false" onerror="this.classList.add('sp-hc-player__photo--empty');this.removeAttribute('src')" />`
    : `<span class="sp-hc-player__photo sp-hc-player__photo--empty" aria-hidden="true"></span>`;
  return `
    <div class="sp-hc-player" draggable="true" data-player-id="${escapeHtml(player.player_id)}" title="Drag to move · × to remove">
      ${photoHtml}
      <span class="sp-hc-player__name">${escapeHtml(shirt)}${escapeHtml(player.surname || player.name)}</span>
      <button type="button" class="sp-hc-player__remove" data-remove-player="${escapeHtml(player.player_id)}" aria-label="Remove ${escapeHtml(player.surname || player.name)}">×</button>
    </div>`;
}

function renderHeightSlide(report) {
  const edit = ensureHeightEditState(report);
  const opponent = report.opponent || {};
  const crest =
    opponent.badge_url || opponent.image || opponent.image_url || "";
  const hasPlayers =
    edit.unknown.length > 0 || edit.bands.some((band) => band.players.length);

  if (!hasPlayers) {
    return `<section class="sp-slide sp-slide--height" data-slide-title="Heights">${slideShell({
      title: "Height Chart",
      subtitle: opponent.name || "Opponent",
      body: `<div class="sp-empty">No outfield players available for the height chart.</div>`,
    })}</section>`;
  }

  const unknownHtml = edit.unknown.length
    ? edit.unknown.map((player) => heightPlayerChipHtml(player, report)).join("")
    : `<span class="sp-hc-unknown__empty">Drop unknowns here</span>`;

  const rowsHtml = edit.bands
    .map((band) => {
      const chips = (band.players || [])
        .map((player) => heightPlayerChipHtml(player, report))
        .join("");
      return `
        <div class="sp-hc-row" data-band="${escapeHtml(band.label)}">
          <div class="sp-hc-row__label">${escapeHtml(band.label)}</div>
          <div class="sp-hc-row__players" data-drop-band="${escapeHtml(band.label)}">${chips || `<span class="sp-hc-row__empty">Drop players here</span>`}</div>
        </div>`;
    })
    .join("");

  return `<section class="sp-slide sp-slide--height" data-slide-title="Heights">
    <div class="sp-hc">
      <header class="sp-hc__header">
        ${crest ? `<img class="sp-hc__crest" src="${escapeHtml(crest)}" alt="" />` : `<span class="sp-hc__crest sp-hc__crest--empty"></span>`}
        <h2 class="sp-hc__title">Height Chart</h2>
        <span class="sp-hc__badge">Outfield · drag to edit</span>
      </header>
      <div class="sp-hc__body sp-hc__body--editable">
        <aside class="sp-hc-unknown" data-drop-band="${escapeHtml(HEIGHT_UNKNOWN_BAND)}">
          <div class="sp-hc-unknown__label">No height</div>
          <div class="sp-hc-unknown__stack">${unknownHtml}</div>
        </aside>
        <div class="sp-hc__axis" aria-hidden="true">
          <span class="sp-hc__axis-arrow sp-hc__axis-arrow--top"></span>
          <span class="sp-hc__axis-line"></span>
          <span class="sp-hc__axis-arrow sp-hc__axis-arrow--bottom"></span>
        </div>
        <div class="sp-hc__rows">
          ${rowsHtml}
        </div>
        <div class="sp-hc-trash" data-drop-band="__remove__" title="Drop here to remove">
          <span>Remove</span>
        </div>
      </div>
    </div>
  </section>`;
}

function refreshHeightSlideDom() {
  if (!state.report || !state.slides.length) return;
  const heightIndex = state.slides.findIndex((html) =>
    html.includes('data-slide-title="Heights"')
  );
  if (heightIndex < 0) return;
  state.slides[heightIndex] = renderHeightSlide(state.report);
  const slideEls = [...els.deck.querySelectorAll(".sp-slide")];
  if (slideEls[heightIndex]) {
    slideEls[heightIndex].outerHTML = state.slides[heightIndex];
  }
  highlightSlide(state.slideIndex);
  bindHeightChartInteractions();
}

function bindHeightChartInteractions() {
  if (document.body.classList.contains("is-pdf-view") || document.body.classList.contains("is-present")) {
    return;
  }
  const root = els.deck.querySelector(".sp-slide--height .sp-hc");
  if (!root || root.dataset.bound === "1") return;
  root.dataset.bound = "1";

  let dragPlayerId = null;

  root.querySelectorAll(".sp-hc-player").forEach((el) => {
    el.addEventListener("dragstart", (event) => {
      dragPlayerId = el.dataset.playerId;
      el.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragPlayerId || "");
    });
    el.addEventListener("dragend", () => {
      el.classList.remove("is-dragging");
      root.querySelectorAll(".is-drop-target").forEach((node) =>
        node.classList.remove("is-drop-target")
      );
      dragPlayerId = null;
    });
  });

  root.querySelectorAll("[data-drop-band]").forEach((zone) => {
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      zone.classList.add("is-drop-target");
      event.dataTransfer.dropEffect = "move";
    });
    zone.addEventListener("dragleave", () => {
      zone.classList.remove("is-drop-target");
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is-drop-target");
      const playerId =
        dragPlayerId || event.dataTransfer.getData("text/plain") || null;
      if (!playerId) return;
      const bandLabel = zone.dataset.dropBand;
      const beforeEl = event.target.closest?.(".sp-hc-player");
      const beforeId =
        beforeEl && beforeEl.dataset.playerId !== String(playerId)
          ? beforeEl.dataset.playerId
          : null;
      const player = removeHeightPlayer(playerId);
      if (!player) return;
      if (bandLabel === "__remove__") {
        refreshHeightSlideDom();
        return;
      }
      addHeightPlayer(player, bandLabel, beforeId);
      refreshHeightSlideDom();
    });
  });

  root.querySelectorAll("[data-remove-player]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removeHeightPlayer(btn.dataset.removePlayer);
      refreshHeightSlideDom();
    });
  });
}

function leadersBlock(rows, mode) {
  if (!rows?.length) return `<div class="sp-empty">No leaders in the recent window.</div>`;
  return `<div class="sp-leader-list">${rows
    .slice(0, 7)
    .map((row, index) => {
      const shirt = row.shirt_number ? `#${row.shirt_number} ` : "";
      const stat =
        mode === "aerial"
          ? `${display(row.aerial_won_sp)} won · ${pct(row.aerial_win_pct_sp)}`
          : `${display(row.shot_xg_sp)} xG · ${display(row.goals_sp)} G`;
      return `
        <div class="sp-leader">
          <div class="sp-leader__rank">${index + 1}</div>
          <div>
            <div class="sp-leader__name">${escapeHtml(shirt)}${escapeHtml(row.name)}</div>
            <div class="sp-leader__meta">${escapeHtml(row.position_abbr || "—")} · ${escapeHtml(row.height || "—")}</div>
          </div>
          <div class="sp-leader__stat">${escapeHtml(stat)}</div>
        </div>`;
    })
    .join("")}</div>`;
}

function renderLeadersSlide(report) {
  const opponent = report.opponent?.name || "Opponent";
  return `<section class="sp-slide" data-slide-title="Key threats">${slideShell({
    title: "Set Piece Threats",
    subtitle: `${opponent} · Recent match window`,
    body: `
      <div class="sp-split">
        <div class="sp-panel">
          <h3 class="sp-panel__title">Aerial leaders</h3>
          <p class="sp-panel__hint">Won aerials at set-piece phase</p>
          ${leadersBlock(report.aerial_leaders, "aerial")}
        </div>
        <div class="sp-panel">
          <h3 class="sp-panel__title">Chance creators</h3>
          <p class="sp-panel__hint">Shot xG &amp; goals from set pieces</p>
          ${leadersBlock(report.threat_leaders, "threat")}
        </div>
      </div>`,
  })}</section>`;
}

const DEFAULT_PITCH = {
  goalX: 52.5,
  minX: 17.5,
  widthM: 68,
  depthM: 35,
  penaltyBoxDepthM: 16.5,
  penaltyBoxWidthM: 40.32,
  sixYardDepthM: 5.5,
  sixYardWidthM: 18.32,
};

function resolvePitchMeta(pitch) {
  const merged = { ...DEFAULT_PITCH, ...(pitch || {}) };
  const widthM = Number(merged.widthM) || DEFAULT_PITCH.widthM;
  const depthM = Number(merged.depthM) || DEFAULT_PITCH.depthM;
  const goalX = Number(merged.goalX) || DEFAULT_PITCH.goalX;
  const minX = Number(merged.minX) || DEFAULT_PITCH.minX;
  return {
    ...merged,
    widthM,
    depthM,
    goalX,
    minX,
  };
}

function normalizeAttackingThirdCoords(impectX, impectY) {
  let x = Number(impectX);
  let y = Number(impectY);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (x < 0) {
    x = -x;
    y = -y;
  }
  return { x, y };
}

function crossImpectToSvg(impectX, impectY, pitch, drawW = 360, plotHeight = null, plotYOffset = null, padX = 12, padY = 12) {
  const drawH = (pitch.depthM / pitch.widthM) * drawW;
  const plotH = plotHeight ?? drawH;
  const plotY = plotYOffset ?? padY;
  const halfW = pitch.widthM / 2;
  const xRange = pitch.goalX - pitch.minX;
  return {
    x: padX + ((halfW - impectY) / pitch.widthM) * drawW,
    y: plotY + ((pitch.goalX - impectX) / xRange) * plotH,
    drawW,
    drawH,
    padX,
    padY,
    plotH,
    plotY,
  };
}

function firstContactWon(point) {
  if (!point) return null;
  if (typeof point.won === "boolean") return point.won;
  if (typeof point.sameTeam !== "boolean") return null;
  return point.defending ? !point.sameTeam : point.sameTeam;
}

function firstContactMarkerStyle(point, { bySide = false, byFamily = false } = {}) {
  if (byFamily) {
    const family = restartFamilyOf(point);
    if (family === "corner") return { fill: "#f5c518", stroke: "#111111", text: "#111111" };
    if (family === "freeKick") return { fill: "#e85d04", stroke: "#7c2d12", text: "#ffffff" };
    return { fill: "#e2e8f0", stroke: "#64748b", text: "#111111" };
  }
  if (bySide) {
    const side = deliverySideOf(point);
    if (side === "left") return { fill: "#f5c518", stroke: "#111111", text: "#111111" };
    if (side === "right") return { fill: "#0d9488", stroke: "#042f2e", text: "#ffffff" };
    return { fill: "#e2e8f0", stroke: "#64748b", text: "#111111" };
  }
  const won = firstContactWon(point);
  if (won === true) return { fill: "#38bdf8", stroke: "#0369a1", text: "#111111" };
  if (won === false) return { fill: "#fb7185", stroke: "#9f1239", text: "#111111" };
  return { fill: "#e2e8f0", stroke: "#64748b", text: "#111111" };
}

function goalMarkerStyle(point, { bySide = false, byFamily = false } = {}) {
  if (byFamily) {
    const family = restartFamilyOf(point);
    if (family === "freeKick") return { fill: "#e85d04", stroke: "#7c2d12", text: "#ffffff" };
    return { fill: "#f5c518", stroke: "#111111", text: "#111111" };
  }
  if (bySide) {
    const side = deliverySideOf(point);
    if (side === "right") return { fill: "#0d9488", stroke: "#042f2e", text: "#ffffff" };
    return { fill: "#f5c518", stroke: "#111111", text: "#111111" };
  }
  return { fill: "#f5c518", stroke: "#111111", text: "#111111" };
}

function renderFirstContactPitch(points, pitch, { drawW = 420, compact = false, goals = [], bySide = false, byFamily = false } = {}) {
  const pitchMeta = resolvePitchMeta(pitch);
  const padX = compact ? 6 : 10;
  const padY = compact ? 6 : 10;
  const { drawH } = crossImpectToSvg(pitchMeta.minX, 0, pitchMeta, drawW);
  const plotH = drawH;
  const vbW = padX * 2 + drawW;
  const vbH = padY + drawH + padY;
  const pitchX = padX;
  const pitchY = padY;
  const penDepth = ((pitchMeta.penaltyBoxDepthM ?? 16.5) / pitchMeta.depthM) * plotH;
  const penWidth = ((pitchMeta.penaltyBoxWidthM ?? 40.32) / pitchMeta.widthM) * drawW;
  const sixDepth = ((pitchMeta.sixYardDepthM ?? 5.5) / pitchMeta.depthM) * plotH;
  const sixWidth = ((pitchMeta.sixYardWidthM ?? 18.32) / pitchMeta.widthM) * drawW;
  const penX = pitchX + (drawW - penWidth) / 2;
  const sixX = pitchX + (drawW - sixWidth) / 2;
  const markerR = compact ? 8.2 : 6.2;
  const fontSize = compact ? 7.2 : 5.4;

  const markers = (points || [])
    .map((pt) => {
      const normalized = normalizeAttackingThirdCoords(pt.impectX, pt.impectY);
      if (!normalized) return "";
      const svg = crossImpectToSvg(normalized.x, normalized.y, pitchMeta, drawW, plotH, pitchY, padX, padY);
      if (!Number.isFinite(svg.x) || !Number.isFinite(svg.y)) return "";
      const colors = firstContactMarkerStyle(pt, { bySide, byFamily });
      const r = markerR;
      const goldRing = pt.ledToGoal
        ? `<circle cx="${svg.x}" cy="${svg.y}" r="${(r + 2.8).toFixed(1)}" fill="none" stroke="#111" stroke-width="1.6" />`
        : "";
      const shape = compact
        ? `<circle cx="${svg.x}" cy="${svg.y}" r="${r}" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.35" />`
        : `<polygon points="${svg.x},${svg.y - r} ${svg.x + r * 0.9},${svg.y} ${svg.x},${svg.y + r} ${svg.x - r * 0.9},${svg.y}" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.1" />`;
      const label = pt.playerInitials
        ? `<text x="${svg.x}" y="${svg.y + (compact ? 0.55 : 0.35)}" text-anchor="middle" dominant-baseline="middle"
            fill="${colors.text}" font-family="Barlow Condensed, sans-serif" font-size="${fontSize}" font-weight="800" letter-spacing="-0.02em">${escapeHtml(pt.playerInitials)}</text>`
        : "";
      const title = `${pt.minuteLabel || ""} ${pt.playerName || pt.playerInitials || "First contact"} · ${pt.typeLabel || ""}`;
      return `<g><title>${escapeHtml(title)}</title>${goldRing}${shape}${label}</g>`;
    })
    .join("");

  const goalR = compact ? 8.4 : 7.4;
  const goalMarkers = (goals || [])
    .map((pt) => {
      const normalized = normalizeAttackingThirdCoords(pt.impectX, pt.impectY);
      if (!normalized) return "";
      const svg = crossImpectToSvg(normalized.x, normalized.y, pitchMeta, drawW, plotH, pitchY, padX, padY);
      if (!Number.isFinite(svg.x) || !Number.isFinite(svg.y)) return "";
      const colors = goalMarkerStyle(pt, { bySide, byFamily });
      const title = `${pt.minuteLabel || ""} ${pt.playerName || "Goal"} · ${pt.typeLabel || "Set play"}`;
      return `<g>
        <title>${escapeHtml(title)}</title>
        <circle cx="${svg.x}" cy="${svg.y}" r="${goalR}" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.5" />
        <text x="${svg.x}" y="${svg.y + 0.55}" text-anchor="middle" dominant-baseline="middle"
          fill="${colors.text}" font-family="Barlow Condensed, sans-serif" font-size="${compact ? 8 : 7.4}" font-weight="800">G</text>
      </g>`;
    })
    .join("");

  return `
    <svg class="sp-pitch${compact ? " sp-pitch--compact" : ""}" viewBox="0 0 ${vbW.toFixed(2)} ${vbH.toFixed(2)}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="First contact pitch map">
      <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="#2f7430" stroke="#fff" stroke-width="1.2" />
      <rect x="${penX}" y="${pitchY}" width="${penWidth}" height="${penDepth}" fill="none" stroke="#fff" stroke-width="0.9" opacity="0.9" />
      <rect x="${sixX}" y="${pitchY}" width="${sixWidth}" height="${sixDepth}" fill="none" stroke="#fff" stroke-width="0.8" opacity="0.8" />
      <line x1="${pitchX}" y1="${pitchY + drawH}" x2="${pitchX + drawW}" y2="${pitchY + drawH}" stroke="#fff" stroke-width="0.8" opacity="0.75" />
      ${compact ? "" : `<text x="${pitchX + drawW / 2}" y="${pitchY + 11}" text-anchor="middle" fill="rgba(255,255,255,0.9)"
        font-family="Barlow Condensed, sans-serif" font-size="8" font-weight="800">GOAL</text>`}
      ${markers}
      ${goalMarkers}
    </svg>`;
}

function contactLeadersHtml(rows) {
  if (!rows?.length) return `<div class="sp-empty">No first-contact winners in the window.</div>`;
  return `<div class="sp-leader-list">${rows
    .slice(0, 7)
    .map((row, index) => {
      return `
        <div class="sp-leader">
          <div class="sp-leader__rank">${index + 1}</div>
          <div>
            <div class="sp-leader__name">${escapeHtml(row.name)}</div>
            <div class="sp-leader__meta">${escapeHtml(row.initials || "")} · ${escapeHtml(row.into_box || 0)} in box</div>
          </div>
          <div class="sp-leader__stat">${escapeHtml(row.contacts)} contacts</div>
        </div>`;
    })
    .join("")}</div>`;
}

function renderFirstContactSlide(report, sideKey) {
  const side = report.set_plays?.[sideKey] || {};
  const pitch = report.set_plays?.pitch || {};
  const opponent = report.opponent?.name || "Opponent";
  const attacking = sideKey === "attacking";
  const title = attacking ? "First Contacts · For" : "First Contacts · Against";
  const subtitle = attacking
    ? `${opponent} attacking set plays · who wins the first ball`
    : `${opponent} defending set plays · who clears the first ball`;
  const wonLabel = attacking ? "Opp win" : "Opp clear";
  const points = wonContactPoints(side.firstContactPoints);
  const wonCount = points.length;
  const intoBox = points.filter((pt) => pt.intoBox).length;
  const contactTotal =
    Number(side.firstContactTotal) > 0
      ? Number(side.firstContactTotal)
      : points.length;
  const pitchHtml = points.length
    ? renderFirstContactPitch(points, pitch, { bySide: true })
    : `<div class="sp-empty">No won first-contact locations this season.</div>`;

  return `<section class="sp-slide" data-slide-title="${title}">${slideShell({
    title,
    subtitle,
    body: `
      <div class="sp-map-layout">
        <div class="sp-map-panel">
          <h3 class="sp-map-panel__title">First contact map</h3>
          <p class="sp-map-panel__hint">Attacking third · won first contacts only · gold = left, teal = right</p>
          <div class="sp-pitch-wrap">${pitchHtml}</div>
          ${deliveryLegendHtml()}
        </div>
        <div class="sp-map-panel">
          <h3 class="sp-map-panel__title">Who gets them</h3>
          <p class="sp-map-panel__hint">${attacking ? "Opponent attackers winning first contact" : "Opponent defenders winning first contact"}</p>
          <div class="sp-map-kpis">
            <div class="sp-map-kpi">
              <div class="sp-map-kpi__value">${escapeHtml(contactTotal)}</div>
              <div class="sp-map-kpi__label">Contacts</div>
            </div>
            <div class="sp-map-kpi">
              <div class="sp-map-kpi__value">${escapeHtml(pct(side.firstContactWonPct))}</div>
              <div class="sp-map-kpi__label">Win %</div>
            </div>
            <div class="sp-map-kpi">
              <div class="sp-map-kpi__value">${escapeHtml(points.length ? wonCount : "—")}</div>
              <div class="sp-map-kpi__label">${escapeHtml(wonLabel)}</div>
            </div>
            <div class="sp-map-kpi">
              <div class="sp-map-kpi__value">${escapeHtml(points.length ? intoBox : "—")}</div>
              <div class="sp-map-kpi__label">In box</div>
            </div>
          </div>
          ${contactLeadersHtml(side.firstContactLeaders)}
        </div>
      </div>`,
  })}</section>`;
}

function renderSquadSlide(report) {
  const rows = report.squad || [];
  const opponent = report.opponent?.name || "Opponent";
  if (!rows.length) {
    return `<section class="sp-slide" data-slide-title="Squad">${slideShell({
      title: "Squad · Set Piece Data",
      subtitle: opponent,
      body: `<div class="sp-empty">No squad data.</div>`,
    })}</section>`;
  }

  const visible = rows.slice(0, 18);
  const body = `
    <div class="sp-table-wrap">
      <table class="sp-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Player</th>
            <th>Pos</th>
            <th>Height</th>
            <th class="num">Age</th>
            <th>Foot</th>
            <th class="num">Apps</th>
            <th class="num">Aer W</th>
            <th class="num">Aer %</th>
            <th class="num">SP xG</th>
            <th class="num">SP G</th>
          </tr>
        </thead>
        <tbody>
          ${visible
            .map(
              (row) => `
            <tr>
              <td>${escapeHtml(display(row.shirt_number, "—"))}</td>
              <td class="player">${escapeHtml(row.name)}</td>
              <td>${escapeHtml(row.position_abbr)}</td>
              <td>${escapeHtml(row.height)}</td>
              <td class="num">${escapeHtml(display(row.age))}</td>
              <td>${escapeHtml(display(row.foot))}</td>
              <td class="num">${escapeHtml(display(row.appearances, "0"))}</td>
              <td class="num">${escapeHtml(display(row.aerial_won_sp, "0"))}</td>
              <td class="num">${escapeHtml(pct(row.aerial_win_pct_sp))}</td>
              <td class="num">${escapeHtml(display(row.shot_xg_sp, "0"))}</td>
              <td class="num">${escapeHtml(display(row.goals_sp, "0"))}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>`;

  return `<section class="sp-slide" data-slide-title="Squad">${slideShell({
    title: "Squad · Set Piece Data",
    subtitle: `${opponent} · Heights + recent set-play output`,
    body,
  })}</section>`;
}

function buildSlides(report) {
  if (state.deckMode === "two_pager") {
    return [
      renderSideSlide(report, "attacking", { twoPager: true }),
      renderSideSlide(report, "defending", { twoPager: true }),
      renderHeightSlide(report),
    ];
  }
  return [
    renderCoverSlide(report),
    renderHeightSlide(report),
    renderRankingsSlide(report),
    renderSideSlide(report, "attacking"),
    renderSideSlide(report, "defending"),
    renderFirstContactSlide(report, "attacking"),
    renderFirstContactSlide(report, "defending"),
    renderLeadersSlide(report),
    renderSquadSlide(report),
  ];
}

function setDeckMode(mode) {
  const next = mode === "two_pager" ? "two_pager" : "full";
  state.deckMode = next;
  document.body.classList.toggle("is-two-pager", next === "two_pager");
  els.deckModeFullBtn?.classList.toggle("sp-deck-mode__btn--active", next === "full");
  els.deckModeTwoBtn?.classList.toggle("sp-deck-mode__btn--active", next === "two_pager");
  try {
    localStorage.setItem("sp-deck-mode", next);
  } catch {
    /* ignore */
  }
  if (state.report) {
    if (document.body.classList.contains("is-pdf-view")) setPdfView(false);
    state.slides = buildSlides(state.report);
    paintDeck();
    highlightSlide(0);
    showSlide(0, { scroll: true });
  }
}

function restoreDeckMode() {
  let saved = "";
  try {
    saved = localStorage.getItem("sp-deck-mode") || "";
  } catch {
    saved = "";
  }
  const mode = saved === "full" ? "full" : "two_pager";
  state.deckMode = mode;
  document.body.classList.toggle("is-two-pager", mode === "two_pager");
  els.deckModeFullBtn?.classList.toggle("sp-deck-mode__btn--active", mode === "full");
  els.deckModeTwoBtn?.classList.toggle("sp-deck-mode__btn--active", mode === "two_pager");
}

function updateSlideNav() {
  const total = state.slides.length;
  const index = total ? state.slideIndex + 1 : 0;
  els.slideCounter.textContent = total ? `${index} / ${total}` : "—";
  els.prevSlideBtn.disabled = state.loading || state.slideIndex <= 0;
  els.nextSlideBtn.disabled = state.loading || state.slideIndex >= total - 1;
}

function highlightSlide(index) {
  const slides = [...els.deck.querySelectorAll(".sp-slide")];
  if (!slides.length) {
    updateSlideNav();
    return;
  }
  state.slideIndex = Math.max(0, Math.min(index, slides.length - 1));
  const inPresent = document.body.classList.contains("is-present");
  const inPdfView = document.body.classList.contains("is-pdf-view");
  slides.forEach((slide, slideIndex) => {
    if (inPdfView) {
      slide.classList.add("sp-slide--active");
    } else {
      slide.classList.toggle("sp-slide--active", slideIndex === state.slideIndex);
    }
    if (inPresent) {
      slide.style.zIndex = slideIndex === state.slideIndex ? "2" : "1";
    } else {
      slide.style.removeProperty("z-index");
    }
  });
  const active = slides[state.slideIndex];
  const title = active?.dataset.slideTitle || "Set Piece Pre-Match";
  if (!inPdfView && !inPresent) {
    els.statusBar.textContent = `${title} · ${state.report?.opponent?.name || ""} · scroll or ← →`;
  }
  updateSlideNav();
  updatePresentChrome();
}

function paintDeck() {
  els.deck.innerHTML = state.slides.join("");
  els.deck.querySelectorAll(".sp-slide").forEach((slide, slideIndex) => {
    slide.dataset.slideIndex = String(slideIndex);
  });
  bindHeightChartInteractions();
  applyPdfViewToSlides();
}

function showSlide(index, { scroll = true } = {}) {
  if (!state.slides.length) {
    els.deck.innerHTML = "";
    updateSlideNav();
    return;
  }
  if (els.deck.querySelectorAll(".sp-slide").length !== state.slides.length) {
    paintDeck();
  }
  highlightSlide(index);
  if (scroll && !document.body.classList.contains("is-present")) {
    const active = els.deck.querySelectorAll(".sp-slide")[state.slideIndex];
    active?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderDeck(report) {
  state.report = report;
  state.heightEdit = null;
  state.slides = buildSlides(report);
  state.slideIndex = 0;
  paintDeck();
  highlightSlide(0);
  els.refreshBtn.disabled = false;
  setModeButtonsEnabled(true);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderSeasons() {
  const iterations = state.meta?.iterations || [];
  els.seasonToggle.innerHTML = iterations
    .map((item) => {
      const id = item.iteration_id || item.id;
      const label = item.season || item.label || id;
      const active = String(id) === String(els.iterationId.value);
      return `<button type="button" class="sp-season-btn${active ? " is-active" : ""}" data-iteration-id="${id}">${escapeHtml(label)}</button>`;
    })
    .join("");

  els.seasonToggle.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      els.iterationId.value = btn.dataset.iterationId;
      await loadFixtures();
    });
  });
}

function renderFixtures() {
  const selectedMatchId = Number(els.matchId.value || 0);
  const selectedOpponentId = Number(els.opponentId.value || 0);
  els.matchBar.innerHTML = state.fixtures
    .map((fixture) => {
      const opponentId = fixture.opponent?.id;
      const matchId = fixture.match_id || "";
      const active = selectedMatchId
        ? Number(matchId) === selectedMatchId
        : String(opponentId) === String(selectedOpponentId);
      const matchDay = fixture.match_day ? `MD${fixture.match_day}` : "";
      const kickoff = fixture.kickoff_label || (fixture.is_home ? "H" : "A") || "vs";
      const title = [fixture.opponent?.name, matchDay, kickoff].filter(Boolean).join(" · ");
      return `<button type="button" class="sp-match-bar__item${active ? " sp-match-bar__item--active" : ""}" role="option" aria-selected="${active ? "true" : "false"}" data-opponent-id="${opponentId}" data-match-id="${matchId}" title="${escapeHtml(title)}">
        ${matchBarCrestHtml(fixture.opponent)}
        <span class="sp-match-bar__kickoff">${escapeHtml(kickoff)}</span>
      </button>`;
    })
    .join("");

  els.matchBar.querySelectorAll(".sp-match-bar__item").forEach((btn) => {
    btn.addEventListener("click", async () => {
      els.opponentId.value = btn.dataset.opponentId;
      els.matchId.value = btn.dataset.matchId || "";
      renderFixtures();
      await loadReport();
    });
  });

  const activeEl = els.matchBar.querySelector(".sp-match-bar__item--active");
  if (activeEl) {
    activeEl.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }
}

async function loadFixtures() {
  const iterationId = Number(els.iterationId.value);
  if (!iterationId) return;
  setStatus("Loading fixtures…", "loading");
  try {
    const data = await apiGet(`/api/set-piece-pre-match/fixtures?iteration_id=${iterationId}`);
    state.fixtures = data.fixtures || [];
    renderFixtures();
    if (!els.opponentId.value && state.fixtures.length) {
      const first = state.fixtures[0];
      els.opponentId.value = first.opponent?.id || "";
      els.matchId.value = first.match_id || "";
      renderFixtures();
      await loadReport();
    } else if (els.opponentId.value) {
      await loadReport();
    } else {
      setStatus("");
      els.deck.innerHTML = `<div class="sp-placeholder">No fixtures found for this season.</div>`;
      els.statusBar.textContent = "No fixtures found for this season.";
    }
  } catch (err) {
    setStatus(err.message || "Failed to load fixtures", "error");
  }
}

async function loadReport({ refresh = false } = {}) {
  const iterationId = Number(els.iterationId.value);
  const squadId = Number(els.opponentId.value);
  if (!iterationId || !squadId) return;

  state.loading = true;
  els.refreshBtn.disabled = true;
  els.prevSlideBtn.disabled = true;
  els.nextSlideBtn.disabled = true;
  setStatus(
    refresh
      ? "Refreshing set-piece data from Impect…"
      : "Building set-piece slides from Impect…",
    "loading"
  );
  els.statusBar.textContent = refresh
    ? "Rebuilding last-8 + season (bypassing cache)…"
    : "Loading set-piece prep (uses cache when available)…";

  try {
    const body = {
      iteration_id: iterationId,
      squad_id: squadId,
      refresh: Boolean(refresh),
    };
    if (els.matchId.value) body.match_id = Number(els.matchId.value);
    const report = await apiPost("/api/set-piece-pre-match/report", body);
    renderDeck(report);
    const cache = report.cache || {};
    if (cache.stale) {
      setStatus("Showing cached report — Impect rate-limited a rebuild.", "error");
      els.statusBar.textContent = "Cached set-piece prep (rate limited).";
    } else if (cache.hit) {
      setStatus("Loaded from cache", "");
      els.statusBar.textContent = "Set-piece prep ready (cache).";
    } else {
      setStatus("");
      els.statusBar.textContent = "Set-piece prep ready.";
    }
  } catch (err) {
    renderEmptyDeck(err.message || "Failed to build report");
    setStatus(err.message || "Failed to build report", "error");
  } finally {
    state.loading = false;
    els.refreshBtn.disabled = false;
    updateSlideNav();
  }
}

async function boot() {
  restoreDeckMode();
  els.deckModeFullBtn?.addEventListener("click", () => setDeckMode("full"));
  els.deckModeTwoBtn?.addEventListener("click", () => setDeckMode("two_pager"));
  els.refreshBtn.addEventListener("click", () => loadReport({ refresh: true }));
  if (els.exportWhatsappPdfBtn) els.exportWhatsappPdfBtn.addEventListener("click", exportWhatsappPdf);
  if (els.pdfViewBtn) els.pdfViewBtn.addEventListener("click", () => setPdfView(true));
  if (els.pdfBackBtn) els.pdfBackBtn.addEventListener("click", () => setPdfView(false));
  if (els.presentBtn) {
    els.presentBtn.addEventListener("click", () => {
      setPresent(!document.body.classList.contains("is-present"));
    });
  }
  if (els.presentPrev) {
    els.presentPrev.addEventListener("click", (event) => {
      event.stopPropagation();
      showSlide(state.slideIndex - 1, { scroll: false });
    });
  }
  if (els.presentNext) {
    els.presentNext.addEventListener("click", (event) => {
      event.stopPropagation();
      showSlide(state.slideIndex + 1, { scroll: false });
    });
  }
  els.prevSlideBtn.addEventListener("click", () => showSlide(state.slideIndex - 1));
  els.nextSlideBtn.addEventListener("click", () => showSlide(state.slideIndex + 1));

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && document.body.classList.contains("is-present")) {
      setPresent(false);
    }
  });

  window.addEventListener("resize", () => {
    updatePdfScale();
  });

  document.addEventListener("keydown", (event) => {
    if (event.target && /input|textarea|select/i.test(event.target.tagName)) return;
    if (!state.slides.length) return;

    if (event.key === "p" || event.key === "P") {
      if (!document.body.classList.contains("is-pdf-view")) {
        setPresent(!document.body.classList.contains("is-present"));
      }
      return;
    }

    if (event.key === "Escape") {
      if (document.body.classList.contains("is-present")) {
        event.preventDefault();
        setPresent(false);
        return;
      }
      if (document.body.classList.contains("is-pdf-view")) {
        event.preventDefault();
        setPdfView(false);
        return;
      }
    }

    if (document.body.classList.contains("is-present") || document.body.classList.contains("is-pdf-view")) {
      if (event.key === "ArrowRight" || event.key === " " || event.key === "PageDown") {
        event.preventDefault();
        showSlide(state.slideIndex + 1, { scroll: !document.body.classList.contains("is-present") });
      } else if (event.key === "ArrowLeft" || event.key === "PageUp" || event.key === "Backspace") {
        event.preventDefault();
        showSlide(state.slideIndex - 1, { scroll: !document.body.classList.contains("is-present") });
      } else if (event.key === "Home") {
        event.preventDefault();
        showSlide(0, { scroll: !document.body.classList.contains("is-present") });
      } else if (event.key === "End") {
        event.preventDefault();
        showSlide(state.slides.length - 1, { scroll: !document.body.classList.contains("is-present") });
      }
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      showSlide(state.slideIndex - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      showSlide(state.slideIndex + 1);
    }
  });

  els.deck.innerHTML = `<div class="sp-placeholder">Select a fixture to build the set-piece slide deck.</div>`;
  setModeButtonsEnabled(false);

  try {
    state.meta = await apiGet("/api/set-piece-pre-match/meta");
    const iterations = state.meta.iterations || [];
    const preferredId = state.meta.default_iteration_id;
    const preferred =
      iterations.find((item) => Number(item.id) === Number(preferredId)) ||
      iterations.find((item) => String(item.season || "").includes("26/27")) ||
      iterations[0];
    if (!preferred) {
      setStatus("No Impect seasons available.", "error");
      return;
    }
    els.iterationId.value = preferred.id;
    if (state.meta.default_fixture?.opponent_id) {
      els.opponentId.value = state.meta.default_fixture.opponent_id;
      els.matchId.value = state.meta.default_fixture.match_id || "";
    }
    renderSeasons();
    await loadFixtures();
  } catch (err) {
    setStatus(err.message || "Failed to start", "error");
  }
}

boot();
