const FETCH_TIMEOUT_MS = 90000;

const state = {
  payload: null,
  filters: {},
  loading: false,
  saving: false,
};

const els = {
  pageSubtitle: document.getElementById("pageSubtitle"),
  statusBanner: document.getElementById("statusBanner"),
  statusBar: document.getElementById("statusBar"),
  jumpNav: document.getElementById("jumpNav"),
  blocksRoot: document.getElementById("blocksRoot"),
  refreshBtn: document.getElementById("refreshBtn"),
  exportAllBtn: document.getElementById("exportAllBtn"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setStatus(message, kind = "") {
  if (!message) {
    els.statusBanner.classList.add("hidden");
    els.statusBanner.textContent = "";
    return;
  }
  els.statusBanner.className = `ba-status ba-status--${kind}`;
  els.statusBanner.textContent = message;
  els.statusBanner.classList.remove("hidden");
}

async function fetchJson(url, options = {}) {
  const busted = url.includes("?") ? `${url}&_=${Date.now()}` : `${url}?_=${Date.now()}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? FETCH_TIMEOUT_MS);
  try {
    const { timeoutMs: _t, ...rest } = options;
    const res = await fetch(busted, {
      cache: "no-store",
      headers: { Accept: "application/json", ...(rest.headers || {}) },
      ...rest,
      signal: controller.signal,
    });
    const raw = await res.text();
    let data = {};
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: raw.slice(0, 240) };
      }
    }
    if (!res.ok) {
      const detail = data.detail || data.message || res.statusText;
      throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function fmtNum(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function shortOpponent(name) {
  const text = String(name || "").replace(/\s+FC$/i, "").trim();
  const parts = text.split(/\s+/);
  if (parts.length <= 2) return text;
  return parts.slice(0, 2).join(" ");
}

function resultClass(outcome) {
  if (outcome === "win") return "ba-fix--win";
  if (outcome === "draw") return "ba-fix--draw";
  if (outcome === "loss") return "ba-fix--loss";
  return "";
}

function scoreLine(fixture) {
  const stats = fixture.stats || {};
  if (!fixture.played) return "";
  return `${stats.goals ?? "?"}–${stats.goalsAgainst ?? "?"}`;
}

function fixtureCard(fixture, filterId) {
  const tbc = !fixture.matchId;
  const focus = filterId && String(filterId) === String(fixture.matchId);
  const ha = fixture.isHome == null
    ? ""
    : `<span class="ba-fix__ha ${fixture.isHome ? "ba-fix__ha--home" : ""}">${fixture.isHome ? "HOME" : "AWAY"}</span>`;
  const badge = fixture.badgeUrl
    ? `<img class="ba-fix__badge" src="${escapeHtml(fixture.badgeUrl)}" alt="" crossorigin="anonymous" />`
    : `<span class="ba-fix__initials">${escapeHtml(fixture.opponentInitials || "?")}</span>`;
  const score = fixture.played
    ? `<p class="ba-fix__score">${escapeHtml(scoreLine(fixture))}</p>`
    : "";
  const date = fixture.dateLabel
    ? `${fixture.slot}. ${fixture.dateLabel}`
    : `${fixture.slot}. TBC`;
  return `
    <article class="ba-fix ${resultClass(fixture.outcome)} ${tbc ? "ba-fix--tbc" : ""} ${focus ? "ba-fix--focus" : ""}" data-match-id="${escapeHtml(fixture.matchId || "")}">
      <div class="ba-fix__top">
        <span class="ba-fix__date">${escapeHtml(date)}</span>
        ${ha}
      </div>
      ${badge}
      <p class="ba-fix__name">${escapeHtml(fixture.opponentName || "FIXTURE TBC")}</p>
      ${score}
    </article>
  `;
}

function medalPills(block) {
  const current = block.target?.medal || "silver";
  return ["gold", "silver", "bronze"].map((medal) => {
    const label = medal.toUpperCase();
    return `<button type="button" class="ba-medal-pill ${medal === current ? "is-active" : ""}" data-medal="${medal}" data-block="${block.id}">${label}</button>`;
  }).join("");
}

function posterHtml(block) {
  const target = block.target || {};
  const medal = target.medal || "silver";
  const csLabel = Number(target.cleanSheets) === 1 ? "clean sheet" : "clean sheets";
  return `
    <section class="ba-poster" data-poster="${block.id}">
      <header class="ba-poster__head">
        <div class="ba-poster__head-left">
          <img class="ba-poster__crest" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale" />
          <p class="ba-poster__kicker">BLOCK ${block.id} OF 9 • ${escapeHtml(block.title)}</p>
        </div>
        <p class="ba-poster__score">${escapeHtml(block.pointsLabel)}</p>
      </header>
      <div class="ba-poster__body">
        <h2 class="ba-poster__heading">${escapeHtml(block.heading)}</h2>
        <div class="ba-fixtures">
          ${(block.fixtures || []).map((row) => fixtureCard(row, state.filters[block.id])).join("")}
        </div>
        <div class="ba-aim-wrap">
          <p class="ba-aim-wrap__title">What are we aiming for?</p>
          <div class="ba-medal-pills ba-export-hide">${medalPills(block)}</div>
          <div class="ba-aim ba-aim--${escapeHtml(medal)}">
            <p class="ba-aim__label">${escapeHtml(target.label || "SILVER • AUTOMATIC")}</p>
            <span class="ba-aim__points-print">${escapeHtml(target.points)}</span>
            <input class="ba-aim__points ba-export-hide" type="number" min="0" max="18" step="1" value="${escapeHtml(target.points)}" data-block="${block.id}" aria-label="Points target" />
            <p class="ba-aim__cs">
              <span class="ba-aim__cs-print">${escapeHtml(target.cleanSheets)}</span>
              <input class="ba-aim__cs-input ba-export-hide" type="number" min="0" max="6" step="1" value="${escapeHtml(target.cleanSheets)}" data-block="${block.id}" aria-label="Clean sheet target" />
              ${csLabel}
            </p>
          </div>
        </div>
      </div>
      <footer class="ba-poster__foot">
        <p class="ba-poster__foot-text">${escapeHtml(block.footer)}</p>
        <div class="ba-poster__export ba-export-hide">
          <button type="button" class="ba-btn" data-export="${block.id}">PNG</button>
        </div>
      </footer>
    </section>
  `;
}

function selectedStats(block) {
  const filterId = state.filters[block.id];
  if (!filterId || filterId === "all") return { stats: block.totals, label: "All games in this block", single: false };
  const fixture = (block.fixtures || []).find((row) => String(row.matchId) === String(filterId));
  if (!fixture) return { stats: block.totals, label: "All games in this block", single: false };
  const stats = { ...(fixture.stats || {}) };
  stats.played = fixture.played ? 1 : 0;
  stats.cleanSheets = fixture.stats?.cleanSheet ? 1 : 0;
  return {
    stats,
    label: fixture.played
      ? `${fixture.opponentName} (${scoreLine(fixture)})`
      : `${fixture.opponentName} · not played`,
    single: true,
    fixture,
  };
}

function kpiTone(key, stats, target, single, scheduled) {
  if (single || !stats.played) return "";
  const complete = scheduled > 0 && stats.played >= scheduled;
  if (key === "points") {
    if (complete && stats.points >= (target?.points || 0)) return "hot";
    if (complete) return "cold";
    return "warn";
  }
  if (key === "cleanSheets" && complete) {
    return stats.cleanSheets >= (target?.cleanSheets || 0) ? "hot" : "cold";
  }
  return "";
}

function kpiCard(label, value, hint, tone) {
  return `
    <article class="ba-kpi ${tone ? `ba-kpi--${tone}` : ""}">
      <p class="ba-kpi__label">${escapeHtml(label)}</p>
      <p class="ba-kpi__value">${escapeHtml(value)}</p>
      ${hint ? `<p class="ba-kpi__hint">${escapeHtml(hint)}</p>` : ""}
    </article>
  `;
}

function dashHtml(block) {
  const { stats, label, single } = selectedStats(block);
  const filterId = state.filters[block.id] || "all";
  const scheduled = (block.fixtures || []).filter((row) => row.matchId).length;
  const pills = [`<button type="button" class="ba-filter__btn ${filterId === "all" ? "is-active" : ""}" data-filter="all" data-block="${block.id}">All games</button>`]
    .concat(
      (block.fixtures || [])
        .filter((row) => row.matchId)
        .map((row) => {
          const active = String(filterId) === String(row.matchId);
          return `<button type="button" class="ba-filter__btn ${active ? "is-active" : ""}" data-filter="${row.matchId}" data-block="${block.id}">${escapeHtml(row.slot)}. ${escapeHtml(shortOpponent(row.opponentName))}</button>`;
        })
    )
    .join("");

  const target = block.target || {};
  const pointsHint = single
    ? (stats.played ? "This match" : "Kick-off pending")
    : `Target ${target.points} · ${stats.played || 0} played`;
  const csHint = single
    ? (stats.cleanSheets ? "Clean sheet" : stats.played ? "Conceded" : "—")
    : `Target ${target.cleanSheets}`;

  const cards = [
    kpiCard("Points", fmtNum(stats.points), pointsHint, kpiTone("points", stats, target, single, scheduled)),
    kpiCard("Goals", fmtNum(stats.goals), single ? "For" : "Scored in block"),
    kpiCard("Goals against", fmtNum(stats.goalsAgainst), single ? "Against" : "Conceded in block"),
    kpiCard("Clean sheets", fmtNum(stats.cleanSheets), csHint, kpiTone("cleanSheets", stats, target, single, scheduled)),
    kpiCard("Defenders bypassed", fmtNum(stats.defendersBypassed), "Impect packing"),
    kpiCard("Offensive interventions", fmtNum(stats.offensiveInterventions), "Ball wins by action"),
    kpiCard("Duel rate", stats.duelRate == null ? "—" : `${fmtNum(stats.duelRate, 1)}%`, stats.duelTotal ? `${fmtNum(stats.duelWon)} / ${fmtNum(stats.duelTotal)}` : "Won / attempted"),
    kpiCard("Ball wins vs defenders", fmtNum(stats.ballWinsFromOppDefenders), "Removed opposition defenders"),
    kpiCard("Team xG", fmtNum(stats.xg, 2), "Shot xG"),
  ].join("");

  return `
    <section class="ba-dash">
      <div class="ba-dash__head">
        <div>
          <h3 class="ba-dash__title">Block Analysis</h3>
          <p class="ba-dash__sub">${escapeHtml(label)} · live after full time</p>
        </div>
        <div class="ba-filter" role="group" aria-label="Filter block ${block.id} to one game">${pills}</div>
      </div>
      <div class="ba-kpis">${cards}</div>
    </section>
  `;
}

function renderJump(blocks, currentBlockId) {
  els.jumpNav.innerHTML = blocks.map((block) => {
    const current = block.id === currentBlockId ? "is-current" : "";
    const done = block.status === "complete" ? "is-complete" : "";
    return `<button type="button" class="ba-jump__btn ${current} ${done}" data-jump="${block.id}">Block ${block.id}</button>`;
  }).join("");
}

function render() {
  const payload = state.payload;
  if (!payload) return;
  const y = window.scrollY;
  const blocks = payload.blocks || [];
  els.pageSubtitle.textContent = `${payload.competition || "League Two"} ${payload.season || ""} · ${payload.playedCount || 0} / ${payload.matchCount || 0} league games played`;
  renderJump(blocks, payload.currentBlockId);
  els.blocksRoot.innerHTML = blocks.map((block) => `
    <article class="ba-block" id="block-${block.id}">
      ${posterHtml(block)}
      ${dashHtml(block)}
    </article>
  `).join("");
  window.scrollTo(0, y);
}

async function load(refresh = false) {
  if (state.loading) return;
  state.loading = true;
  els.refreshBtn.disabled = true;
  setStatus(refresh ? "Refreshing live block data…" : "Loading blocks…", "loading");
  els.statusBar.textContent = "Loading…";
  try {
    const payload = await fetchJson(`/api/blocks-analysis${refresh ? "?refresh=true" : ""}`);
    state.payload = payload;
    (payload.blocks || []).forEach((block) => {
      if (!state.filters[block.id]) state.filters[block.id] = "all";
    });
    render();
    setStatus("");
    els.statusBar.textContent = `Updated ${new Date(payload.generatedAt || Date.now()).toLocaleTimeString("en-GB")} · Block ${payload.currentBlockId} of 9`;
  } catch (err) {
    setStatus(err.message || "Failed to load Blocks Analysis", "error");
    els.statusBar.textContent = "Load failed";
  } finally {
    state.loading = false;
    els.refreshBtn.disabled = false;
  }
}

function medalDefaults(medal) {
  const spec = (state.payload?.medals || []).find((row) => row.id === medal);
  if (spec) return spec;
  return { points: 9, cleanSheets: 2, label: "SILVER • AUTOMATIC" };
}

async function saveTarget(blockId, patch) {
  const block = (state.payload?.blocks || []).find((row) => row.id === blockId);
  if (!block) return;
  const next = {
    medal: patch.medal ?? block.target.medal,
    points: patch.points ?? block.target.points,
    cleanSheets: patch.cleanSheets ?? block.target.cleanSheets,
  };
  block.target = {
    ...block.target,
    ...next,
    label: medalDefaults(next.medal).label || block.target.label,
  };
  block.pointsLabel = `${block.totals.points} / ${next.points}`;
  render();
  try {
    await fetchJson("/api/blocks-analysis/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        blockId,
        medal: next.medal,
        points: Number(next.points),
        cleanSheets: Number(next.cleanSheets),
      }),
    });
  } catch (err) {
    setStatus(err.message || "Could not save target", "error");
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load export library"));
    document.head.appendChild(script);
  });
}

function downloadDataUrl(dataUrl, filename) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function slug(value) {
  return String(value || "block")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

async function exportPoster(blockId) {
  await loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js");
  if (typeof html2canvas !== "function") throw new Error("PNG export failed to load");
  if (document.fonts?.ready) await document.fonts.ready;
  const poster = document.querySelector(`[data-poster="${blockId}"]`);
  if (!poster) throw new Error("Block poster not found");
  document.body.classList.add("is-exporting");
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  try {
    const canvas = await html2canvas(poster, {
      backgroundColor: "#d7dbe2",
      scale: 2,
      logging: false,
      useCORS: true,
    });
    const block = (state.payload?.blocks || []).find((row) => row.id === Number(blockId));
    const name = `Block-${blockId}-${slug(block?.title || "league")}.png`;
    downloadDataUrl(canvas.toDataURL("image/png"), name);
  } finally {
    document.body.classList.remove("is-exporting");
  }
}

els.refreshBtn.addEventListener("click", () => load(true));
els.exportAllBtn.addEventListener("click", async () => {
  if (!state.payload?.blocks?.length) return;
  els.exportAllBtn.disabled = true;
  setStatus("Exporting posters…", "loading");
  try {
    for (const block of state.payload.blocks) {
      await exportPoster(block.id);
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    setStatus("PNGs downloaded.", "ok");
  } catch (err) {
    setStatus(err.message || "Export failed", "error");
  } finally {
    els.exportAllBtn.disabled = false;
  }
});

els.jumpNav.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-jump]");
  if (!btn) return;
  document.getElementById(`block-${btn.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
});

els.blocksRoot.addEventListener("click", async (event) => {
  const medalBtn = event.target.closest("[data-medal]");
  if (medalBtn) {
    const blockId = Number(medalBtn.dataset.block);
    const medal = medalBtn.dataset.medal;
    const defaults = medalDefaults(medal);
    await saveTarget(blockId, {
      medal,
      points: defaults.points,
      cleanSheets: defaults.cleanSheets,
    });
    return;
  }
  const filterBtn = event.target.closest("[data-filter]");
  if (filterBtn) {
    const blockId = Number(filterBtn.dataset.block);
    state.filters[blockId] = filterBtn.dataset.filter;
    render();
    return;
  }
  const exportBtn = event.target.closest("[data-export]");
  if (exportBtn) {
    exportBtn.disabled = true;
    try {
      await exportPoster(exportBtn.dataset.export);
    } catch (err) {
      setStatus(err.message || "Export failed", "error");
    } finally {
      exportBtn.disabled = false;
    }
  }
});

els.blocksRoot.addEventListener("change", async (event) => {
  const points = event.target.closest(".ba-aim__points");
  const cs = event.target.closest(".ba-aim__cs-input");
  const input = points || cs;
  if (!input) return;
  const blockId = Number(input.dataset.block);
  const value = Number(input.value);
  if (!Number.isFinite(value)) return;
  if (points) await saveTarget(blockId, { points: value });
  if (cs) await saveTarget(blockId, { cleanSheets: value });
});

load(false);
