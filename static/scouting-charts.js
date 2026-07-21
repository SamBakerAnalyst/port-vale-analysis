(function () {
  const seasonColors = ["#56d4ff", "#a78bfa", "#34d399", "#fbbf24", "#fb7185", "#60a5fa"];
  const chartFonts = { family: '"DM Sans", system-ui, sans-serif', color: "#e2e8f0" };
  const plotlyConfig = { responsive: true, displayModeBar: false };

  function humanizeFootballLabel(label) {
    const text = String(label || "").trim();
    if (!text) return text;
    return text
      .replace(/_/g, " ")
      .replace(/\s*-\s*/g, " ")
      .replace(/\bPv\b/gi, "")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^./, (c) => c.toUpperCase());
  }

  function humanizeProfileName(name) {
    return humanizeFootballLabel(String(name || "").replace(/^\s*pv\b[\s\-:]*/i, ""));
  }

  function formatAxisLabel(label) {
    return humanizeProfileName(label);
  }

  function formatMetricValue(value) {
    if (value == null || Number.isNaN(value)) return "—";
    const rounded = Math.round(value);
    if (Math.abs(value - rounded) < 0.01) return String(rounded);
    if (Math.abs(value) < 10) return Number(value.toFixed(2)).toString();
    return Number(value.toFixed(1)).toString();
  }

  function formatPercentileLabel(value) {
    if (value == null || Number.isNaN(value)) return "—";
    return `${Math.round(value)}%`;
  }

  function percentileBarColors(value) {
    if (value == null || Number.isNaN(value)) {
      return { fill: "#94a3b8", badgeBg: "#f1f5f9", badgeText: "#64748b" };
    }
    if (value >= 80) return { fill: "#1e6b3a", badgeBg: "#dcfce7", badgeText: "#166534" };
    if (value >= 60) return { fill: "#388e5c", badgeBg: "#ecfdf5", badgeText: "#15803d" };
    if (value >= 40) return { fill: "#ca8a04", badgeBg: "#fef9c3", badgeText: "#a16207" };
    if (value >= 25) return { fill: "#c2410c", badgeBg: "#ffedd5", badgeText: "#9a3412" };
    return { fill: "#dc2626", badgeBg: "#fee2e2", badgeText: "#b91c1c" };
  }

  function formatBenchmarkSubtitle(benchmark) {
    if (!benchmark) {
      return "Cross-league percentile · Nat Lge, Lg Two, Scot Prem · 600+ min";
    }
    const leagues = (benchmark.competitions || []).join(", ");
    const cohort = benchmark.cohort_size ?? "?";
    const minMinutes = benchmark.min_minutes ?? 600;
    return `Percentile vs ${cohort} players · ${leagues} · ${minMinutes}+ min`;
  }

  function angularRotation(labelCount) {
    const step = 360 / Math.max(labelCount, 1);
    return 90 + step / 2;
  }

  function closedRadarSeries(values, labels, labelFormatter) {
    const theta = labels.map(labelFormatter);
    if (!values.length || !theta.length) return { r: [], theta: [] };
    return { r: [...values, values[0]], theta: [...theta, theta[0]] };
  }

  function drilldownThetaKeys(labelCount) {
    return Array.from({ length: labelCount }, (_, index) => `__dd_${index}`);
  }

  function drilldownThetaTickText(labels) {
    return labels.map((label) => humanizeFootballLabel(label));
  }

  function radarTrace(values, labels, name, color, filled, labelFormatter, options) {
    const fullLabels = options.fullLabels || labels;
    const compact = Boolean(options.compact);
    const series = options.thetaLabels
      ? { r: [...values, values[0]], theta: [...options.thetaLabels, options.thetaLabels[0]] }
      : closedRadarSeries(values, labels, labelFormatter);
    const trace = {
      type: "scatterpolar",
      mode: "lines",
      r: series.r,
      theta: series.theta,
      name,
      fill: filled ? "toself" : "none",
      line: { color, width: compact ? 2 : 2.5, shape: compact ? "linear" : "spline", smoothing: compact ? 0 : 0.85 },
      fillcolor: filled ? `${color}2e` : undefined,
      hovertemplate: compact
        ? "<b>%{customdata}</b><br>%{r:.1f} percentile<extra>%{fullData.name}</extra>"
        : "<b>%{theta}</b><br>%{r:.1f} percentile<extra></extra>",
    };
    if (compact) trace.customdata = [...fullLabels, fullLabels[0]];
    return trace;
  }

  function polarChartLayout(labelCount, options) {
    const {
      showLegend = false,
      radialaxis = {},
      compact = false,
      drilldownPanel = false,
      categoryarray = [],
      ticktext = [],
    } = options;
    const axisTickText = ticktext.length ? ticktext : categoryarray;
    const angularaxis = compact
      ? {
          type: "category",
          categoryorder: "array",
          categoryarray,
          showticklabels: true,
          tickmode: "array",
          tickvals: categoryarray,
          ticktext: axisTickText,
          ticklabelstep: 1,
          tickfont: { family: chartFonts.family, size: labelCount > 6 ? 11 : 12, color: "#e2e8f0" },
          showline: false,
          gridcolor: "rgba(148, 163, 184, 0.14)",
          linecolor: "rgba(148, 163, 184, 0.08)",
          rotation: angularRotation(labelCount),
          direction: "clockwise",
        }
      : {
          gridcolor: "rgba(148, 163, 184, 0.1)",
          linecolor: "rgba(148, 163, 184, 0.08)",
          tickfont: { family: chartFonts.family, size: 12, color: "#e2e8f0" },
          rotation: angularRotation(labelCount),
          direction: "clockwise",
        };

    return {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: chartFonts,
      polar: {
        domain: drilldownPanel
          ? { x: [0.05, 0.95], y: [0.04, showLegend ? 0.88 : 0.96] }
          : compact
            ? { x: [0.14, 0.86], y: [0.16, 0.78] }
            : { x: [0.1, 0.9], y: showLegend ? [0.08, 0.86] : [0.06, 0.94] },
        bgcolor: "rgba(17, 24, 39, 0.6)",
        radialaxis: {
          visible: true,
          showticklabels: false,
          ticks: "",
          gridcolor: "rgba(148, 163, 184, 0.12)",
          gridwidth: 1,
          linecolor: "rgba(148, 163, 184, 0.08)",
          angle: 90,
          ...radialaxis,
        },
        angularaxis,
      },
      margin: drilldownPanel
        ? { l: 52, r: 52, t: 8, b: showLegend ? 52 : 24 }
        : compact
          ? { l: 72, r: 72, t: 16, b: showLegend ? 64 : 40 }
          : { l: 110, r: 110, t: 24, b: showLegend ? 72 : 24 },
      showlegend: showLegend,
      legend: {
        orientation: "h",
        y: -0.1,
        x: 0.5,
        xanchor: "center",
        font: { family: chartFonts.family, size: 11, color: "#cbd5e1" },
        bgcolor: "rgba(15, 23, 42, 0.8)",
        bordercolor: "rgba(148, 163, 184, 0.15)",
      },
    };
  }

  function playerLegendLabel(player) {
    const parts = [player.player];
    if (player.season_label) parts.push(player.season_label);
    if (player.position_label) parts.push(player.position_label);
    if (player.play_duration_minutes) parts.push(`${Math.round(player.play_duration_minutes)} min`);
    return parts.join(" · ");
  }

  function buildComparedPlayerTraces(comparedPlayers, fallbackLabels, options) {
    const compact = Boolean(options.compact);
    return comparedPlayers.map((entry, index) => {
      const labels = entry.labels || fallbackLabels;
      return radarTrace(
        entry.radar_values,
        labels,
        playerLegendLabel(entry),
        seasonColors[index % seasonColors.length],
        !compact || index === 0,
        formatAxisLabel,
        { compact, fullLabels: labels, thetaLabels: options.thetaLabels },
      );
    });
  }

  function plotComparedRadar(elementId, comparedPlayers, fallbackLabels, benchmark, options) {
    const chartEl = document.getElementById(elementId);
    if (!chartEl || !window.Plotly) return;
    const compact = Boolean(options.compact);
    const axisLabels = comparedPlayers[0]?.labels || fallbackLabels || [];
    const labelCount = axisLabels.length;
    const thetaKeys = compact ? drilldownThetaKeys(labelCount) : null;
    const thetaTickText = compact ? drilldownThetaTickText(axisLabels) : [];
    const traces = buildComparedPlayerTraces(comparedPlayers, fallbackLabels, {
      compact,
      thetaLabels: thetaKeys,
    });
    const showLegend = options.layout?.showLegend ?? traces.length > 1;
    window.Plotly.newPlot(
      elementId,
      traces,
      polarChartLayout(labelCount, {
        showLegend,
        radialaxis: { ticksuffix: "%", range: [0, 100] },
        compact,
        drilldownPanel: compact,
        categoryarray: thetaKeys || [],
        ticktext: thetaTickText,
        ...options.layout,
      }),
      plotlyConfig,
    );
  }

  function createFactorBarRow(label, percentile, rawValue) {
    const row = document.createElement("div");
    row.className = "factor-bar-row";

    const labelEl = document.createElement("div");
    labelEl.className = "factor-bar-label";
    const labelText = document.createElement("span");
    labelText.className = "factor-bar-label-text";
    labelText.textContent = label;
    labelEl.appendChild(labelText);
    row.appendChild(labelEl);

    const trackWrap = document.createElement("div");
    trackWrap.className = "factor-bar-track-wrap";
    const track = document.createElement("div");
    track.className = "factor-bar-track";
    const fill = document.createElement("div");
    fill.className = "factor-bar-fill";
    const width = percentile == null ? 0 : Math.max(percentile, 4);
    fill.style.width = `${width}%`;
    const colors = percentileBarColors(percentile);
    fill.style.backgroundColor = colors.fill;
    const valueEl = document.createElement("span");
    valueEl.className = "factor-bar-value";
    valueEl.textContent = formatMetricValue(rawValue);
    fill.appendChild(valueEl);
    track.appendChild(fill);
    trackWrap.appendChild(track);

    const badge = document.createElement("div");
    badge.className = "factor-bar-badge";
    badge.style.backgroundColor = colors.badgeBg;
    badge.style.color = colors.badgeText;
    badge.textContent = formatPercentileLabel(percentile);
    trackWrap.appendChild(badge);
    row.appendChild(trackWrap);
    return row;
  }

  function renderDrilldownFactorList(entry, players) {
    const list = document.createElement("div");
    list.className = "factor-bar-list factor-bar-list-slide-grid";
    const barLabels = entry.bar_labels || entry.labels || [];
    const barWeights = entry.bar_weights || [];
    barLabels.forEach((label, factorIndex) => {
      const group = document.createElement("div");
      group.className = "factor-bar-group";
      const heading = document.createElement("div");
      heading.className = "factor-bar-factor-name";
      const weightLabel = barWeights[factorIndex] != null ? ` · ${Math.round(barWeights[factorIndex])}%` : "";
      heading.textContent = `${label}${weightLabel}`;
      group.appendChild(heading);
      const player = players[0] || {};
      const row = createFactorBarRow(
        player.player || "Player",
        player.bar_radar_values?.[factorIndex],
        player.bar_raw_values?.[factorIndex],
      );
      group.appendChild(row);
      list.appendChild(group);
    });
    return list;
  }

  function render(root, data) {
    root.innerHTML = "";
    root.classList.add("scouting-charts");

    const note = document.createElement("p");
    note.className = "player-chart-note";
    note.textContent =
      "Charts use the comparison-tool benchmark (cross-league percentiles), not the league-relative scores in the long list table.";
    root.appendChild(note);

    const comparedPlayers = data.players?.length
      ? data.players
      : [{ player: data.player, labels: data.labels, radar_values: data.radar_values, season_label: data.season_label, position_label: data.position_label, play_duration_minutes: data.play_duration_minutes }];

    const main = document.createElement("section");
    main.className = "player-chart-main";
    const title = document.createElement("h3");
    title.className = "player-chart-main__title";
    title.textContent = comparedPlayers[0]?.player || data.player || "Player";
    const subtitle = document.createElement("p");
    subtitle.className = "player-chart-main__subtitle";
    subtitle.textContent = formatBenchmarkSubtitle(data.benchmark);
    const mainChart = document.createElement("div");
    mainChart.id = "scoutingMainRadar";
    mainChart.className = "chart";
    main.appendChild(title);
    main.appendChild(subtitle);
    main.appendChild(mainChart);
    root.appendChild(main);

    plotComparedRadar("scoutingMainRadar", comparedPlayers, data.labels || [], data.benchmark, {
      layout: { showLegend: comparedPlayers.length > 1, compact: false, drilldownPanel: false },
    });

    const drilldowns = data.profile_drilldowns || [];
    if (!drilldowns.length) return;

    const stack = document.createElement("div");
    stack.className = "profile-drilldown-stack";
    drilldowns.forEach((entry, index) => {
      const card = document.createElement("article");
      card.className = "profile-drilldown-card";
      const chartId = `scoutingDrilldown-${index}`;
      const head = document.createElement("div");
      head.style.padding = "1rem 1rem 0";
      const h3 = document.createElement("h3");
      h3.textContent = humanizeProfileName(entry.profile);
      const meta = document.createElement("p");
      meta.className = "drilldown-card-meta";
      meta.textContent = `Top ${(entry.bar_labels || entry.labels || []).length} weighted factors · bar = Impect score · badge = percentile`;
      head.appendChild(h3);
      head.appendChild(meta);
      card.appendChild(head);

      const body = document.createElement("div");
      body.className = "profile-drilldown-body";
      const radarPanel = document.createElement("div");
      radarPanel.className = "profile-drilldown-radar";
      const chart = document.createElement("div");
      chart.id = chartId;
      chart.className = "chart drilldown-chart";
      radarPanel.appendChild(chart);
      body.appendChild(radarPanel);

      const players = entry.players?.length
        ? entry.players
        : [{
            player: data.player,
            labels: entry.labels,
            radar_values: entry.radar_values,
            bar_labels: entry.bar_labels || entry.labels || [],
            bar_radar_values: entry.bar_radar_values || entry.radar_values || [],
            bar_raw_values: entry.bar_raw_values || entry.raw_values || [],
          }];

      const barsPanel = document.createElement("div");
      barsPanel.className = "profile-drilldown-bars";
      barsPanel.appendChild(renderDrilldownFactorList(entry, players));
      body.appendChild(barsPanel);
      card.appendChild(body);
      stack.appendChild(card);

      plotComparedRadar(chartId, players, entry.labels || [], data.benchmark, {
        compact: true,
        layout: { showLegend: false },
      });
    });
    root.appendChild(stack);
  }

  window.ScoutingCharts = { render };
})();
