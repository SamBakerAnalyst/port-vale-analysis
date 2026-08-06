(() => {
  const API = window.location.origin;
  const SEASON_GAMES = 46;

  const els = {
    status: document.getElementById("statusBanner"),
    subtitle: document.getElementById("pageSubtitle"),
    updated: document.getElementById("lastUpdated"),
    refresh: document.getElementById("refreshBtn"),
    badge: document.getElementById("summaryBadge"),
    headline: document.getElementById("summaryHeadline"),
    meta: document.getElementById("summaryMeta"),
    kpiPlayed: document.getElementById("kpiPlayed"),
    kpiPoints: document.getElementById("kpiPoints"),
    kpiProj: document.getElementById("kpiProj"),
    kpiPos: document.getElementById("kpiPos"),
    chart: document.getElementById("pointsChart"),
    metrics: document.getElementById("metricsGrid"),
    source: document.getElementById("sourceNote"),
  };

  function setStatus(message, kind = "") {
    if (!message) {
      els.status.className = "st-status hidden";
      els.status.textContent = "";
      return;
    }
    els.status.className = `st-status${kind ? ` st-status--${kind}` : ""}`;
    els.status.textContent = message;
  }

  function statusLabel(status) {
    if (status === "ahead") return "Ahead of auto";
    if (status === "behind") return "Behind auto";
    return "On track vs auto";
  }

  function fmt(value, digits = 0) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    return digits > 0 ? n.toFixed(digits) : String(Math.round(n));
  }

  function renderSummary(data) {
    const s = data.summary || {};
    const status = s.status || "on_track";
    els.badge.textContent = statusLabel(status);
    els.badge.className = `st-summary__badge is-${status === "on_track" ? "track" : status}`;
    const proj = s.projected_points;
    const auto = s.auto_target;
    const delta = s.delta_vs_auto;
    const sign = delta > 0 ? "+" : "";
    els.headline.textContent =
      proj == null
        ? `${data.club} · waiting for league fixtures`
        : `Projected ${fmt(proj, 1)} pts · auto target ${fmt(auto, 1)} (${sign}${fmt(delta, 1)})`;
    els.meta.textContent = `${data.season || "Season"} · ${data.played}/${SEASON_GAMES} played · ${data.games_remaining} remaining · pos ${data.position ?? "—"}`;
    els.kpiPlayed.textContent = fmt(data.played);
    els.kpiPoints.textContent = fmt(data.metrics?.find((m) => m.id === "points")?.current);
    els.kpiProj.textContent = fmt(proj, 1);
    els.kpiPos.textContent = data.position != null ? String(data.position) : "—";
    els.subtitle.textContent = `${data.club} · live pace vs Strategy Report benchmarks`;
  }

  function renderPointsChart(data) {
    const series = data.points_series || [];
    const bench = data.benchmarks?.points || {};
    const played = data.played || 0;
    const currentPts = series.length ? series[series.length - 1].points : 0;
    const projected = played > 0 ? (currentPts / played) * SEASON_GAMES : null;

    const W = 1000;
    const H = 320;
    const pad = { l: 44, r: 18, t: 18, b: 36 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    const yMax = Math.max(
      100,
      bench.champion || 0,
      bench.auto || 0,
      projected || 0,
      currentPts,
    ) * 1.08;

    const x = (game) => pad.l + (game / SEASON_GAMES) * innerW;
    const y = (pts) => pad.t + innerH - (pts / yMax) * innerH;

    const grid = [];
    for (let g = 0; g <= SEASON_GAMES; g += 5) {
      grid.push(`<line x1="${x(g)}" y1="${pad.t}" x2="${x(g)}" y2="${pad.t + innerH}" stroke="rgba(255,255,255,0.05)" />`);
      grid.push(`<text x="${x(g)}" y="${H - 10}" fill="#8b9bb0" font-size="11" text-anchor="middle">${g}</text>`);
    }
    for (let p = 0; p <= yMax; p += 20) {
      grid.push(`<line x1="${pad.l}" y1="${y(p)}" x2="${pad.l + innerW}" y2="${y(p)}" stroke="rgba(255,255,255,0.05)" />`);
      grid.push(`<text x="${pad.l - 8}" y="${y(p) + 3}" fill="#8b9bb0" font-size="11" text-anchor="end">${Math.round(p)}</text>`);
    }

    function targetLine(value, color, dash = "6 5") {
      if (value == null) return "";
      return `<line x1="${x(0)}" y1="${y(0)}" x2="${x(SEASON_GAMES)}" y2="${y(value)}" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}" opacity="0.9" />`;
    }

    let valePath = "";
    if (series.length) {
      const pts = [`${x(0)},${y(0)}`].concat(series.map((row) => `${x(row.played)},${y(row.points)}`));
      valePath = `<polyline fill="none" stroke="#f5c518" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" points="${pts.join(" ")}" />`;
    }

    let projPath = "";
    if (projected != null && played > 0) {
      projPath = `<line x1="${x(played)}" y1="${y(currentPts)}" x2="${x(SEASON_GAMES)}" y2="${y(projected)}" stroke="#fde68a" stroke-width="2.5" stroke-dasharray="5 4" />`;
      projPath += `<circle cx="${x(SEASON_GAMES)}" cy="${y(projected)}" r="4.5" fill="#fde68a" />`;
    }

    const lastDot = series.length
      ? `<circle cx="${x(played)}" cy="${y(currentPts)}" r="5" fill="#f5c518" stroke="#0c0f14" stroke-width="2" />`
      : "";

    els.chart.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Port Vale points pace versus promotion targets">
        <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" />
        ${grid.join("")}
        ${targetLine(bench.playoff, "#94a3b8")}
        ${targetLine(bench.auto, "#3d8bfd")}
        ${targetLine(bench.champion, "#34d399")}
        ${valePath}
        ${projPath}
        ${lastDot}
        <text x="${pad.l}" y="14" fill="#8b9bb0" font-size="11">Points</text>
        <text x="${W / 2}" y="${H - 2}" fill="#8b9bb0" font-size="11" text-anchor="middle">Games played</text>
      </svg>`;
  }

  function renderMetrics(data) {
    els.metrics.innerHTML = (data.metrics || []).map((metric) => {
      const bench = metric.benchmarks || {};
      const compare = Number(metric.compare ?? metric.current ?? 0);
      const max = Math.max(
        compare,
        bench.champion || 0,
        bench.auto || 0,
        bench.playoff || 0,
        1,
      ) * 1.12;
      const pct = (value) => Math.max(0, Math.min(100, (Number(value) / max) * 100));
      const fill = pct(compare);
      const delta = metric.delta_vs_auto;
      const sign = delta > 0 ? "+" : "";
      const compareLabel = metric.project ? "Season proj." : "Current";
      return `
        <article class="st-metric">
          <div class="st-metric__head">
            <h3 class="st-metric__title">${metric.label}</h3>
            <span class="st-metric__status is-${metric.status}">${statusLabel(metric.status)}</span>
          </div>
          <div class="st-metric__values">
            <span>Now <strong>${fmt(metric.current, metric.project ? 0 : 0)}</strong></span>
            <span>${compareLabel} <strong>${fmt(compare, metric.project ? 1 : 0)}</strong></span>
          </div>
          <div class="st-rail" aria-hidden="true">
            <div class="st-rail__fill" style="width:${fill}%"></div>
            <span class="st-rail__mark st-rail__mark--playoff" style="left:${pct(bench.playoff)}%"></span>
            <span class="st-rail__mark st-rail__mark--auto" style="left:${pct(bench.auto)}%"></span>
            <span class="st-rail__mark st-rail__mark--champ" style="left:${pct(bench.champion)}%"></span>
          </div>
          <div class="st-rail__labels">
            <span>PO ${fmt(bench.playoff, 1)}</span>
            <span>Auto ${fmt(bench.auto, 1)}</span>
            <span>Champ ${fmt(bench.champion, 1)}</span>
          </div>
          <p class="st-rail__delta"><strong>${sign}${fmt(delta, 1)}</strong> vs auto-promotion average</p>
        </article>`;
    }).join("");
  }

  async function load(refresh = false) {
    els.refresh.disabled = true;
    setStatus(refresh ? "Refreshing live League Two data…" : "");
    try {
      const res = await fetch(`${API}/api/strategy-tracker?refresh=${refresh ? "true" : "false"}`);
      const raw = await res.text();
      let data;
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch {
        throw new Error(raw.slice(0, 160) || `Request failed (${res.status})`);
      }
      if (!res.ok) throw new Error(data.detail || `Failed to load tracker (${res.status})`);
      renderSummary(data);
      renderPointsChart(data);
      renderMetrics(data);
      els.source.textContent = data.source_note || "";
      const when = data.generated_at ? new Date(data.generated_at) : new Date();
      els.updated.textContent = `Updated ${when.toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })}`;
      setStatus("");
    } catch (err) {
      setStatus(err.message || "Could not load strategy tracker.", "error");
    } finally {
      els.refresh.disabled = false;
    }
  }

  els.refresh.addEventListener("click", () => load(true));
  load(false);
})();
