const state = {
  meta: null,
  fixtures: [],
  report: null,
  slides: [],
  slideIndex: 0,
  loading: false,
  heightEdit: null,
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
  setExportOverlay("Building WhatsApp PDF…");
  setStatus("Building full-quality WhatsApp PDF (1920×1080)…", "loading");
  try {
    const pages = await captureSetPieceSlides({
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
    const response = await fetch("/api/set-piece-pre-match/export-whatsapp-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages,
        filename,
        document_title: `Set Piece Pre-Match · ${state.report?.opponent?.name || "Opponent"}`,
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
      setExportStatus(`PDF downloaded · ${pages.length} slides · still in PDF version`, "success");
      els.statusBar.textContent = `Share from Desktop: ${savedPath.split("/").pop()}`;
    } else {
      setStatus(`WhatsApp PDF downloaded · ${pages.length} slides · ${sizeMb} MB`, "");
      setExportStatus(`PDF downloaded · ${pages.length} slides`, "success");
      els.statusBar.textContent = "PDF ready — attach in WhatsApp";
    }
  } catch (error) {
    setStatus(error.message || "WhatsApp PDF export failed", "error");
    setExportStatus(error.message || "WhatsApp PDF export failed", "error");
  } finally {
    setExportOverlay("");
    setModeButtonsEnabled(Boolean(state.report));
    els.refreshBtn.disabled = false;
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

function crestHtml(team, className = "sp-cover__crest") {
  const name = team?.name || "Team";
  const image = team?.badge_url || team?.image_url || team?.imageUrl || team?.image || "";
  if (image) {
    return `<img class="${className}" src="${escapeHtml(image)}" alt="${escapeHtml(name)}" />`;
  }
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return `<div class="sp-cover__crest-fallback" aria-hidden="true">${escapeHtml(initial)}</div>`;
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
  const windowLabel = report.match_window_label || "Last 8 games";
  const seasonGames = report.season_games;

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
      <p class="sp-cover__meta">${escapeHtml(venue)} · ${escapeHtml(windowLabel)}${seasonGames ? ` + full season (${escapeHtml(seasonGames)})` : " + full season"} · League One</p>
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
    return `<div class="sp-side-mini-empty">No L8 first-contact winners</div>`;
  }
  const hint = defending ? "clears" : "wins";
  return `<div class="sp-side-mini-leaders">
    <div class="sp-side-mini-leaders__title">L8 first contact ${escapeHtml(hint)}</div>
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

function renderSideFamilyPanel(
  block,
  {
    title,
    hint,
    dangerContact = false,
    familyKey = "corners",
    side = {},
    pitch = {},
    defending = false,
  } = {}
) {
  const kpis = sideFamilyKpis(block, { dangerContact });
  const recentVolume = display(block?.chains, "0");
  const seasonVolume = display(block?.season?.chains, "—");
  const chips = (block?.byType || [])
    .map(
      (row) =>
        `<span class="sp-type-chip"><strong>${escapeHtml(row.count)}</strong>${escapeHtml(row.label)}</span>`
    )
    .join("");
  const points = familyContactPoints(side, familyKey);
  const leaders = familyLeadersFromPoints(points);
  const mapHtml = points.length
    ? renderFirstContactPitch(points, pitch, { drawW: 320, compact: true })
    : `<div class="sp-side-mini-empty">No L8 first-contact map points</div>`;
  const wonLabel = defending ? "Opp clear" : "Opp win";
  const lostLabel = defending ? "Attacker wins" : "Defended";

  return `
    <div class="sp-side-family">
      <div class="sp-side-family__head">
        <h3 class="sp-side-family__title">${escapeHtml(title)}</h3>
        <span class="sp-side-family__count"><strong>${escapeHtml(recentVolume)}</strong> L8 · <strong>${escapeHtml(seasonVolume)}</strong> SZN</span>
      </div>
      ${hint ? `<p class="sp-side-family__hint">${escapeHtml(hint)}</p>` : ""}
      <div class="sp-kpi-grid sp-kpi-grid--compact sp-kpi-grid--dual">
        ${kpis
          .map(
            (kpi) => `
          <div class="sp-kpi sp-kpi--dual${kpi.accent ? " sp-kpi--accent" : ""}${kpi.danger ? " sp-kpi--danger" : ""}${kpi.elite ? " sp-kpi--elite" : ""}${kpi.warn ? " sp-kpi--warn" : ""}">
            <div class="sp-kpi__label">${escapeHtml(kpi.label)}</div>
            <div class="sp-kpi__dual">
              <div class="sp-kpi__col">
                <div class="sp-kpi__col-label">L8</div>
                <div class="sp-kpi__value">${escapeHtml(kpi.recent)}</div>
                ${kpi.recentRank ? `<span class="sp-kpi__rank">Lg ${escapeHtml(kpi.recentRank)}</span>` : `<span class="sp-kpi__rank sp-kpi__rank--empty">—</span>`}
              </div>
              <div class="sp-kpi__col">
                <div class="sp-kpi__col-label">Season</div>
                <div class="sp-kpi__value">${escapeHtml(kpi.season)}</div>
                ${kpi.seasonRank ? `<span class="sp-kpi__rank">Lg ${escapeHtml(kpi.seasonRank)}</span>` : `<span class="sp-kpi__rank sp-kpi__rank--empty">—</span>`}
              </div>
            </div>
          </div>`
          )
          .join("")}
      </div>
      <div class="sp-side-family__lower">
        <div class="sp-side-mini-map">
          <div class="sp-side-mini-map__title">L8 first contacts · ${escapeHtml(String(points.length))} pts</div>
          <div class="sp-side-mini-map__pitch">${mapHtml}</div>
          <div class="sp-map-legend sp-map-legend--mini">
            <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--won"></span>${escapeHtml(wonLabel)}</span>
            <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--lost"></span>${escapeHtml(lostLabel)}</span>
          </div>
        </div>
        <div class="sp-side-family__aside">
          ${familyTrendBars(block)}
          ${familyLeadersHtml(leaders, { defending })}
          ${chips ? `<div class="sp-type-row sp-type-row--compact">${chips}</div>` : ""}
        </div>
      </div>
    </div>`;
}

function renderSideSlide(report, sideKey) {
  const side = report.set_plays?.[sideKey] || {};
  const pitch = report.set_plays?.pitch || {};
  const opponent = report.opponent?.name || "Opponent";
  const attacking = sideKey === "attacking";
  const title = attacking ? "Attacking Set Plays" : "Defending Set Plays";
  const subtitle = attacking
    ? `${opponent} · Corners vs free kicks for · last 8 + season`
    : `${opponent} · Corners vs free kicks against · last 8 + season`;
  const dangerContact = !attacking;
  const corners = side.corners || {};
  const freeKicks = side.freeKicks || {};

  return `<section class="sp-slide" data-slide-title="${title}">${slideShell({
    title,
    subtitle,
    body: `
      <div class="sp-side-split">
        ${renderSideFamilyPanel(corners, {
          title: "Corners",
          dangerContact,
          familyKey: "corners",
          side,
          pitch,
          defending: !attacking,
        })}
        ${renderSideFamilyPanel(freeKicks, {
          title: "Free kicks",
          hint: "Attacking-third free kicks only",
          dangerContact,
          familyKey: "freeKicks",
          side,
          pitch,
          defending: !attacking,
        })}
      </div>`,
  })}</section>`;
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

function buildHeightEditState(chart) {
  const bands = HEIGHT_BAND_ORDER.map((label) => {
    const source = (chart.bands || []).find((band) => band.label === label);
    return {
      label,
      players: (source?.players || []).map(cloneHeightPlayer),
    };
  });
  const unknown = (chart.unknown || []).map((player) =>
    cloneHeightPlayer({ ...player, band: HEIGHT_UNKNOWN_BAND })
  );
  // Legacy fallback: players without height_cm still in chart.players
  if (!unknown.length && Array.isArray(chart.players)) {
    for (const player of chart.players) {
      if (player.height_cm) continue;
      if (String(player.position_abbr || "").toUpperCase() === "GK") continue;
      unknown.push(cloneHeightPlayer({ ...player, band: HEIGHT_UNKNOWN_BAND }));
    }
  }
  return {
    bands,
    unknown,
    excluded_gk: chart.excluded_gk || 0,
  };
}

function ensureHeightEditState(report) {
  const opponentId = report?.opponent?.id ?? report?.fixture?.opponent?.id ?? null;
  if (
    state.heightEdit &&
    String(state.heightEdit.opponentId) === String(opponentId)
  ) {
    return state.heightEdit;
  }
  state.heightEdit = {
    opponentId,
    ...buildHeightEditState(report.height_chart || {}),
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

function firstContactMarkerStyle(point) {
  const won = firstContactWon(point);
  if (won === true) return { fill: "#38bdf8", stroke: "#0369a1" };
  if (won === false) return { fill: "#fb7185", stroke: "#9f1239" };
  return { fill: "#e2e8f0", stroke: "#64748b" };
}

function renderFirstContactPitch(points, pitch, { drawW = 420, compact = false } = {}) {
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
  const markerR = compact ? 4.4 : 6.2;
  const fontSize = compact ? 4.2 : 5.4;

  const markers = (points || [])
    .map((pt) => {
      const normalized = normalizeAttackingThirdCoords(pt.impectX, pt.impectY);
      if (!normalized) return "";
      const svg = crossImpectToSvg(normalized.x, normalized.y, pitchMeta, drawW, plotH, pitchY, padX, padY);
      if (!Number.isFinite(svg.x) || !Number.isFinite(svg.y)) return "";
      const colors = firstContactMarkerStyle(pt);
      const r = markerR;
      const shape = `<polygon points="${svg.x},${svg.y - r} ${svg.x + r * 0.9},${svg.y} ${svg.x},${svg.y + r} ${svg.x - r * 0.9},${svg.y}" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.1" />`;
      const label = pt.playerInitials
        ? `<text x="${svg.x}" y="${svg.y + 0.35}" text-anchor="middle" dominant-baseline="middle"
            fill="#111" font-family="Barlow Condensed, sans-serif" font-size="${fontSize}" font-weight="800">${escapeHtml(pt.playerInitials)}</text>`
        : "";
      const title = `${pt.minuteLabel || ""} ${pt.playerName || pt.playerInitials || "First contact"} · ${pt.typeLabel || ""}`;
      return `<g><title>${escapeHtml(title)}</title>${shape}${label}</g>`;
    })
    .join("");

  return `
    <svg class="sp-pitch${compact ? " sp-pitch--compact" : ""}" viewBox="0 0 ${vbW.toFixed(2)} ${vbH.toFixed(2)}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="First contact pitch map">
      <rect x="${pitchX}" y="${pitchY}" width="${drawW}" height="${drawH}" fill="#3f9f45" stroke="#fff" stroke-width="1.2" />
      <rect x="${penX}" y="${pitchY}" width="${penWidth}" height="${penDepth}" fill="none" stroke="#fff" stroke-width="0.9" opacity="0.9" />
      <rect x="${sixX}" y="${pitchY}" width="${sixWidth}" height="${sixDepth}" fill="none" stroke="#fff" stroke-width="0.8" opacity="0.8" />
      <line x1="${pitchX}" y1="${pitchY + drawH}" x2="${pitchX + drawW}" y2="${pitchY + drawH}" stroke="#fff" stroke-width="0.8" opacity="0.75" />
      <text x="${pitchX + drawW / 2}" y="${pitchY + (compact ? 9 : 11)}" text-anchor="middle" fill="rgba(255,255,255,0.9)"
        font-family="Barlow Condensed, sans-serif" font-size="${compact ? 7 : 8}" font-weight="800">GOAL</text>
      ${markers}
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
  const lostLabel = attacking ? "Defended" : "Attacker wins";
  const points = side.firstContactPoints || [];
  const wonCount = points.filter((pt) => firstContactWon(pt) === true).length;
  const intoBox = points.filter((pt) => pt.intoBox).length;
  const contactTotal =
    Number(side.firstContactTotal) > 0
      ? Number(side.firstContactTotal)
      : points.length;
  const pitchHtml = points.length
    ? renderFirstContactPitch(points, pitch)
    : `<div class="sp-empty">No first-contact locations in the recent window.</div>`;

  return `<section class="sp-slide" data-slide-title="${title}">${slideShell({
    title,
    subtitle,
    body: `
      <div class="sp-map-layout">
        <div class="sp-map-panel">
          <h3 class="sp-map-panel__title">First contact map</h3>
          <p class="sp-map-panel__hint">Attacking third · diamonds = first contact locations</p>
          <div class="sp-pitch-wrap">${pitchHtml}</div>
          <div class="sp-map-legend">
            <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--won"></span>${escapeHtml(wonLabel)}</span>
            <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--lost"></span>${escapeHtml(lostLabel)}</span>
            <span class="sp-map-legend__item"><span class="sp-map-legend__swatch sp-map-legend__swatch--neutral"></span>Unknown</span>
          </div>
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

function fixtureLabel(fixture) {
  const opponent = fixture.opponent?.name || "Opponent";
  const venue = fixture.is_home ? "H" : "A";
  return `${opponent} (${venue})`;
}

function renderFixtures() {
  els.matchBar.innerHTML = state.fixtures
    .map((fixture) => {
      const opponentId = fixture.opponent?.id;
      const matchId = fixture.match_id || "";
      const active =
        String(opponentId) === String(els.opponentId.value) &&
        String(matchId || "") === String(els.matchId.value || "");
      return `<button type="button" class="sp-fixture-chip${active ? " is-active" : ""}" role="option" data-opponent-id="${opponentId}" data-match-id="${matchId}">${escapeHtml(fixtureLabel(fixture))}</button>`;
    })
    .join("");

  els.matchBar.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      els.opponentId.value = btn.dataset.opponentId;
      els.matchId.value = btn.dataset.matchId || "";
      renderFixtures();
      await loadReport();
    });
  });
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
