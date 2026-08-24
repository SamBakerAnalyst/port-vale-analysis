const state = {
  iterations: [],
  players: [],
  selectedPlayer: null,
  comparedPlayers: [],
  studioPositionOptions: [],
  positionProfiles: new Map(),
  availableProfiles: [],
  profileLoadWarnings: [],
  selectedProfileNames: new Set(),
  lastChartData: null,
  positionCache: new Map(),
  exportExcluded: new Set(),
  studioView: "build",
};

const POSITION_CACHE_TTL_MS = 5 * 60 * 1000;
const RATE_LIMIT_RETRY_SECONDS = 45;
let loadChartsInFlight = null;
const positionRequestsInFlight = new Map();
let rateLimitRetryTimer = null;

const competitionFilterEl = document.getElementById("competitionFilter");
const seasonCardEl = document.getElementById("seasonCard");
const seasonChipsEl = document.getElementById("seasonChips");
const seasonListEl = document.getElementById("seasonList");
const playerSearchEl = document.getElementById("playerSearch");
const playerSelectEl = document.getElementById("playerSelect");
const addComparePlayerBtn = document.getElementById("addComparePlayerBtn");
const comparePlayerChipsEl = document.getElementById("comparePlayerChips");
const comparePlayerListEl = document.getElementById("comparePlayerList");
const studioPlayerGridEl = document.getElementById("studioPlayerGrid");
const STUDIO_PLAYER_SLOTS = 4;
const chartSourceEl = document.getElementById("chartSource");
const profilePickerEl = document.getElementById("profilePicker");
const profileChipsEl = document.getElementById("profileChips");
const profileListEl = document.getElementById("profileList");
const loadChartsBtn = document.getElementById("loadChartsBtn");
const studioPageBuildEl = document.getElementById("studioPageBuild");
const studioPageCompareEl = document.getElementById("studioPageCompare");
const studioPageTitleEl = document.getElementById("studioPageTitle");
const studioPageLedeEl = document.getElementById("studioPageLede");
const studioRosterMetaEl = document.getElementById("studioRosterMeta");
const studioRosterChipsEl = document.getElementById("studioRosterChips");
const studioPositionNavEl = document.getElementById("studioPositionNav");
const studioBuildHintEl = document.getElementById("studioBuildHint");
const studioCompareMetaEl = document.getElementById("studioCompareMeta");
const studioComparisonFrontEl = document.getElementById("studioComparisonFront");
const backToBuildBtn = document.getElementById("backToBuildBtn");

const CHARTS_FETCH_TIMEOUT_MS = 180000;
const EXPORT_FETCH_TIMEOUT_MS = 120000;
const MAX_CHART_FACTORS = 7;
const MAX_BAR_FACTORS = 4; // drilldown bar grid is 2×2
const exportRadarImageBtn = document.getElementById("exportRadarImageBtn");
const exportPizzaImageBtn = document.getElementById("exportPizzaImageBtn");
const connectionBadgeEl = document.getElementById("connectionBadge");
const alertBoxEl = document.getElementById("alertBox");
const statusBarEl = document.getElementById("statusBar");

const seasonColors = ["#f5c518", "#a78bfa", "#34d399", "#60a5fa", "#fb7185", "#f97316"];

const chartFonts = {
  family: '"DM Sans", system-ui, sans-serif',
  color: "#f5f5f5",
};

const plotlyConfig = { responsive: true, displayModeBar: false };

// Charts are often plotted while their page is still hidden, so Plotly falls
// back to its 700px default and never picks up the real container width —
// `responsive` only listens for window resizes. Watch the container instead.
const plotResizeObservers = new WeakMap();

function keepPlotFittedToContainer(elementId) {
  if (typeof ResizeObserver !== "function") {
    return;
  }
  const el = typeof elementId === "string" ? document.getElementById(elementId) : elementId;
  if (!el || plotResizeObservers.has(el)) {
    return;
  }

  let lastWidth = Math.round(el.clientWidth);
  const observer = new ResizeObserver(() => {
    const width = Math.round(el.clientWidth);
    if (width < 1 || width === lastWidth) {
      return;
    }
    lastWidth = width;
    if (el.data) {
      Plotly.Plots.resize(el);
    }
  });
  observer.observe(el);
  plotResizeObservers.set(el, observer);

  // First paint: the element may already be wider than the plot Plotly chose.
  requestAnimationFrame(() => {
    if (el.data && Math.abs(el.clientWidth - (el._fullLayout?.width || 0)) > 1) {
      Plotly.Plots.resize(el);
    }
  });
}

const PHRASE_REPLACEMENTS = [
  [/ratio\s*-\s*remove opponents(?:\s+defenders)?/i, "Opponents removed"],
  [/ratio\s*-\s*add teammates(?:\s+defenders)?/i, "Teammates added"],
  [/total touches fbl/i, "Touches in left channel"],
  [/total touches fbr/i, "Touches in right channel"],
  [/total touches cb/i, "Touches centrally"],
  [/total touches cm/i, "Touches in midfield"],
  [/total touches dm/i, "Touches in defensive midfield"],
  [/number of aerial duels in packing zone cb/i, "Aerial duels in central zone"],
  [/ground duel score/i, "Ground duels"],
  [/interception score/i, "Interceptions"],
  [/loose ball regain score/i, "Loose ball regains"],
  [/defensive header score/i, "Defensive headers"],
  [/offensive header score/i, "Attacking headers"],
  [/header shot score/i, "Headers on target"],
  [/ground duel success rate/i, "Ground duel win %"],
  [/aerial duel success rate/i, "Aerial duel win %"],
  [/ball wins\*?/i, "Ball wins"],
  [/passes\*?/i, "Passes"],
  [/suffered bypassed players/i, "Bypassed opponents"],
  [/\+\/-\s*suffered bypassed defenders/i, "Bypassed defenders"],
  [/bypassed opponents/i, "Bypassed opponents"],
  [/bypassed defenders/i, "Bypassed defenders"],
];

const ZONE_REPLACEMENTS = [
  [/\bfbl\b/gi, "left channel"],
  [/\bfbr\b/gi, "right channel"],
  [/\bcb\b/gi, "central"],
  [/\bcm\b/gi, "midfield"],
  [/\bdm\b/gi, "defensive midfield"],
  [/\bam\b/gi, "attacking midfield"],
  [/\bwl\b/gi, "left wing"],
  [/\bwr\b/gi, "right wing"],
];

function humanizeFootballLabel(label) {
  const text = String(label || "").trim();
  if (!text) {
    return text;
  }

  const lowered = text.toLowerCase();
  for (const [pattern, replacement] of PHRASE_REPLACEMENTS) {
    if (pattern.test(lowered)) {
      return replacement;
    }
  }

  let result = text
    .replace(/_/g, " ")
    .replace(/\s*-\s*/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  for (const [pattern, replacement] of ZONE_REPLACEMENTS) {
    result = result.replace(pattern, replacement);
  }

  result = result
    .replace(/\bSb\b/gi, "")
    .replace(/\bRatio\b/gi, "")
    .replace(/\bNumber Of\b/gi, "")
    .replace(/\bScore\b/gi, "")
    .replace(/\(\s*\)/g, "")
    .replace(/\s+/g, " ")
    .replace(/^[\s-]+|[\s-]+$/g, "");

  if (!result) {
    return text;
  }

  return result.charAt(0).toUpperCase() + result.slice(1);
}

function stripPvPrefix(name) {
  return String(name || "")
    .trim()
    .replace(/^\s*pv\b[\s\-:]*/i, "")
    .trim();
}

function humanizeProfileName(name) {
  const text = humanizeFootballLabel(stripPvPrefix(name))
    .replace(/\s*\([^)]*\)\s*/g, "")
    .trim();
  return text || stripPvPrefix(name) || String(name || "").trim();
}

function formatMetricValue(value) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  const rounded = Math.round(value);
  if (Math.abs(value - rounded) < 0.01) {
    return String(rounded);
  }
  if (Math.abs(value) < 10) {
    return Number(value.toFixed(2)).toString();
  }
  return Number(value.toFixed(1)).toString();
}

function formatPercentileLabel(value) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${Math.round(value)}%`;
}

// One percentile scale for the whole tool. On-screen cards and exported slides
// both read from here, so a colour means the same thing in every place a coach
// sees it. Keys match the `--elite`/`--good`/… CSS band classes.
function percentileBandKey(value) {
  const numeric = Number(value);
  if (value == null || !Number.isFinite(numeric)) {
    return "na";
  }
  if (numeric >= 80) {
    return "elite";
  }
  if (numeric >= 60) {
    return "good";
  }
  if (numeric >= 40) {
    return "fair";
  }
  if (numeric >= 25) {
    return "poor";
  }
  return "weak";
}

const PERCENTILE_BAND_LABELS = {
  elite: "Elite",
  good: "Strong",
  fair: "Average",
  poor: "Below par",
  weak: "Weak",
  na: "No data",
};

function keynoteBandLabel(value) {
  return PERCENTILE_BAND_LABELS[percentileBandKey(value)];
}

// Profile names arrive inconsistently cased ("PV DEEP CREATOR", "PV Defensive").
// Everything user-facing goes through here so headings never mix the two.
function profileDisplayTitle(label) {
  const text = humanizeProfileName(label);
  if (!text || text !== text.toUpperCase() || text.length <= 3) {
    return text;
  }
  return text.charAt(0) + text.slice(1).toLowerCase();
}

function isRateStyleMetric(rawValue, percentile) {
  const raw = Number(rawValue);
  const pct = Number(percentile);
  if (!Number.isFinite(raw) || !Number.isFinite(pct)) {
    return false;
  }
  // Decimal Impect rates (0.07, 0.49, …).
  if (Math.abs(raw) < 10 && !Number.isInteger(raw)) {
    return true;
  }
  // Integer raw that is clearly an event rate, not a % score (e.g. raw 9, percentile 98).
  if (raw > 0 && raw <= 20 && pct - raw >= 20) {
    return true;
  }
  return false;
}

function resolveBarScores(percentile, rawValue) {
  let pct = percentile == null || Number.isNaN(Number(percentile)) ? null : Number(percentile);
  let raw =
    rawValue == null || rawValue === "" || Number.isNaN(Number(rawValue)) ? null : Number(rawValue);
  // Guard against occasional API alignment swaps between percentile and raw.
  if (pct != null && raw != null && raw > 50 && pct <= 25) {
    [pct, raw] = [raw, pct];
  }
  return { percentile: pct, rawValue: raw };
}

function barTrackPercentile(percentile, rawValue) {
  const resolved = resolveBarScores(percentile, rawValue);
  const pct = resolved.percentile;
  if (pct == null || Number.isNaN(pct)) {
    return 0;
  }
  if (isRateStyleMetric(resolved.rawValue, pct)) {
    return pct;
  }
  return pct;
}

function formatBarInnerValue(percentile, rawValue) {
  const resolved = resolveBarScores(percentile, rawValue);
  const pct = resolved.percentile;
  if (pct != null && !Number.isNaN(pct)) {
    return formatPercentileLabel(pct);
  }
  return formatMetricValue(resolved.rawValue);
}

function formatPlayerMinutes(minutes) {
  const value = Number(minutes);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  return `${Math.round(value).toLocaleString()} min`;
}

function playerLegendLabel(player, { includePosition = false } = {}) {
  const parts = [player.player];
  if (player.season_label) {
    parts.push(player.season_label);
  }
  if (includePosition && player.position_label) {
    parts.push(player.position_label);
  }
  const minutesLabel = formatPlayerMinutes(player.play_duration_minutes);
  if (minutesLabel) {
    parts.push(minutesLabel);
  }
  return parts.join(" · ");
}

function getComparedPlayersFromChartData(data) {
  if (data?.players?.length) {
    return data.players;
  }
  return [
    {
      player: data?.player || "Player",
      season_label: data?.season_label || "",
      position_label: data?.position_label || "",
      play_duration_minutes: data?.play_duration_minutes,
    },
  ];
}

function buildSlideMinutesHeader(players) {
  const header = document.createElement("div");
  header.className = "export-slide-minutes-header";

  players.forEach((player, index) => {
    const item = document.createElement("div");
    item.className = "export-slide-minutes-item";

    const swatch = document.createElement("span");
    swatch.className = "export-slide-minutes-swatch";
    swatch.style.backgroundColor = seasonColors[index % seasonColors.length];

    const name = document.createElement("span");
    name.className = "export-slide-minutes-name";
    name.textContent = player.player;

    const minutes = document.createElement("span");
    minutes.className = "export-slide-minutes-value";
    minutes.textContent = formatPlayerMinutes(player.play_duration_minutes) || "— min";

    item.appendChild(swatch);
    item.appendChild(name);
    item.appendChild(minutes);
    header.appendChild(item);
  });

  return header;
}

function appendSlideMinutesHeader(surface, players) {
  if (!players.length) {
    return;
  }
  surface.insertBefore(buildSlideMinutesHeader(players), surface.firstChild);
}

function playerPhotoUrl(player) {
  return player?.photo_url || player?.photoUrl || null;
}

function enrichDrilldownPlayers(players, chartPlayers = []) {
  const photoByKey = new Map();
  const photoByName = new Map();
  const photoSources = [...chartPlayers, ...state.comparedPlayers];
  photoSources.forEach((player) => {
    const photoUrl = playerPhotoUrl(player);
    if (!photoUrl) {
      return;
    }
    if (player.key) {
      photoByKey.set(player.key, photoUrl);
    }
    const name = player.player || player.name;
    if (name) {
      photoByName.set(name, photoUrl);
    }
  });

  return players.map((player) => ({
    ...player,
    photo_url:
      playerPhotoUrl(player) ||
      (player.key ? photoByKey.get(player.key) : null) ||
      (player.player ? photoByName.get(player.player) : null) ||
      null,
  }));
}

const PERCENTILE_SCALE_STEPS = [
  { key: "weak", label: "0–24 weak" },
  { key: "poor", label: "25–39 below par" },
  { key: "fair", label: "40–59 average" },
  { key: "good", label: "60–79 strong" },
  { key: "elite", label: "80–100 elite" },
];

function buildPercentileScaleKey() {
  const key = document.createElement("div");
  key.className = "pct-scale";
  PERCENTILE_SCALE_STEPS.forEach((step) => {
    const item = document.createElement("span");
    item.className = `pct-scale__step pctband pctband--${step.key}`;
    const swatch = document.createElement("span");
    swatch.className = "pct-scale__swatch";
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(step.label));
    key.appendChild(item);
  });
  return key;
}

// Photo + name + minutes for each player in a drilldown card, colour-matched to
// the radar traces so the shapes are identifiable without a separate legend.
function buildDrilldownPlayerStrip(players) {
  const strip = document.createElement("div");
  strip.className = "drilldown-players";
  strip.dataset.count = String(Math.min(players.length, 4));

  players.slice(0, 4).forEach((player, index) => {
    const color = seasonColors[index % seasonColors.length];
    const item = document.createElement("div");
    item.className = "drilldown-player";
    item.style.setProperty("--player-color", color);

    const photo = document.createElement("div");
    photo.className = "drilldown-player__photo";
    const photoUrl = player.photo_url || player.photoUrl || null;
    if (photoUrl) {
      const image = document.createElement("img");
      image.src = photoUrl;
      image.alt = "";
      photo.appendChild(image);
    } else {
      const placeholder = document.createElement("span");
      placeholder.className = "drilldown-player__initials";
      placeholder.textContent = playerInitials(player.player || "");
      photo.appendChild(placeholder);
    }
    item.appendChild(photo);

    const identity = document.createElement("div");
    identity.className = "drilldown-player__identity";
    const name = document.createElement("p");
    name.className = "drilldown-player__name";
    name.textContent = player.player || "";
    identity.appendChild(name);

    const metaParts = [player.season_label, formatPlayerMinutes(player.play_duration_minutes)]
      .filter(Boolean)
      .join(" · ");
    if (metaParts) {
      const meta = document.createElement("p");
      meta.className = "drilldown-player__meta";
      meta.textContent = metaParts;
      identity.appendChild(meta);
    }
    item.appendChild(identity);

    strip.appendChild(item);
  });

  return strip;
}

function averagePercentileForFactor(players, factorIndex, valueKey = "radar_values") {
  const values = players
    .map((player) => player[valueKey]?.[factorIndex])
    .filter((value) => value != null && !Number.isNaN(value));
  if (!values.length) {
    return null;
  }
  if (players.length === 1) {
    return 50;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function drilldownExportPlayers(entry) {
  if (entry?.players?.length) {
    return entry.players;
  }
  const data = state.lastChartData;
  return [
    {
      player: data?.player || "Player",
      bar_radar_values: entry?.bar_radar_values || entry?.radar_values || [],
      bar_raw_values: entry?.bar_raw_values || entry?.raw_values || [],
    },
  ];
}

function drilldownIndexFromExportIds({ chartId, barsId }) {
  const match = String(chartId || barsId || "").match(/(\d+)$/);
  return match ? Number(match[1]) : -1;
}

function formatAxisLabel(label) {
  const text =
    chartSourceEl?.value === "profiles"
      ? profileDisplayTitle(label)
      : humanizeFootballLabel(label);
  return text.replace(/\bGk\b/gi, "GK");
}

function pizzaTrace(values, labels, name, color = null) {
  const textLabels = values.map((value) => `${Math.round(value)}%`);
  const trace = {
    type: "barpolar",
    r: values,
    theta: labels.map(formatAxisLabel),
    name,
    text: textLabels,
    textposition: "inside",
    insidetextanchor: "middle",
    textfont: {
      family: chartFonts.family,
      size: 12,
      color: "#f8fafc",
    },
    hovertemplate: "<b>%{theta}</b><br>%{r:.1f} percentile<extra></extra>",
  };

  if (color) {
    trace.marker = { color, line: { color: "rgba(15, 23, 42, 0.8)", width: 1 } };
    trace.opacity = 0.85;
  } else {
    trace.marker = {
      color: values,
      colorscale: [
        [0, "#312e81"],
        [0.35, "#4f46e5"],
        [0.65, "#f5c518"],
        [1, "#a5f3fc"],
      ],
      line: { color: "rgba(15, 23, 42, 0.85)", width: 1.5 },
    };
  }

  return trace;
}

function closedRadarSeries(values, labels, labelFormatter = formatAxisLabel) {
  const theta = labels.map(labelFormatter);
  if (!values.length || !theta.length) {
    return { r: [], theta: [] };
  }
  return {
    r: [...values, values[0]],
    theta: [...theta, theta[0]],
  };
}

function wrapLabelText(text, maxCharsPerLine = 16, maxLines = 3) {
  const cleaned = String(text || "").trim();
  if (!cleaned) {
    return cleaned;
  }
  if (cleaned.length <= maxCharsPerLine) {
    return cleaned;
  }

  const words = cleaned.split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxCharsPerLine) {
      current = candidate;
      continue;
    }

    if (current) {
      lines.push(current);
      current = "";
    }

    if (word.length > maxCharsPerLine) {
      let rest = word;
      while (rest.length > maxCharsPerLine && lines.length < maxLines) {
        lines.push(rest.slice(0, maxCharsPerLine));
        rest = rest.slice(maxCharsPerLine);
      }
      current = rest;
    } else {
      current = word;
    }

    if (lines.length >= maxLines) {
      break;
    }
  }

  if (current && lines.length < maxLines) {
    lines.push(current);
  }

  const wrapped = lines.slice(0, maxLines);
  const joinedLength = wrapped.join(" ").replace(/<br>/g, " ").length;
  if (joinedLength < cleaned.length && wrapped.length) {
    const lastIndex = wrapped.length - 1;
    const last = wrapped[lastIndex];
    wrapped[lastIndex] =
      last.length > maxCharsPerLine - 1
        ? `${last.slice(0, Math.max(1, maxCharsPerLine - 1))}…`
        : `${last}…`;
  }

  return wrapped.join("<br>");
}

function wrappedAxisLabel(label, labelCount = 8) {
  const text = humanizeFootballLabel(label);
  const maxLine = labelCount >= 12 ? 12 : labelCount >= 8 ? 14 : 16;
  const maxLines = labelCount >= 10 ? 3 : 2;
  return wrapLabelText(text, maxLine, maxLines);
}

function drilldownAxisLabel(label) {
  const text = humanizeFootballLabel(label);
  if (text.length <= 22) {
    return text;
  }
  return `${text.slice(0, 20)}…`;
}

function drilldownThetaKeys(labelCount) {
  return Array.from({ length: labelCount }, (_, index) => `__dd_${index}`);
}

function drilldownThetaTickText(labels) {
  return labels.map((label, index) => {
    const text = humanizeFootballLabel(label);
    const basedOn = text.match(/\(\s*based on\s+(.+?)\s*\)$/i);
    if (basedOn) {
      const head = text
        .slice(0, basedOn.index)
        .trim()
        .replace(/\bPercent\b/i, "Pct")
        .replace(/\bTotal\b/i, "Total");
      const qualifier = basedOn[1]
        .replace(/\bshot based xg\b/i, "shot xG")
        .replace(/\bpost shot xg\b/i, "post xG");
      return `${head}<br>(${qualifier})`;
    }
    // Three lines rather than two: factor names like "Opponents bypassed left
    // channel" were being truncated with an ellipsis, losing the meaning.
    return wrapLabelText(text, 18, 3);
  });
}

function extractRadarLabelSeries(snapshot) {
  const trace = (snapshot.data || []).find((item) => item.type === "scatterpolar");
  if (!trace) {
    return [];
  }

  if (Array.isArray(trace.customdata) && trace.customdata.length > 1) {
    return trace.customdata.slice(0, -1).map((label) => String(label || "").trim());
  }

  const angular = snapshot.layout?.polar?.angularaxis;
  if (Array.isArray(angular?.ticktext) && angular.ticktext.length) {
    const count = trace.r?.length ? trace.r.length - 1 : angular.ticktext.length;
    return angular.ticktext.slice(0, count).map((label) => String(label || "").trim());
  }
  if (Array.isArray(angular?.categoryarray) && angular.categoryarray.length) {
    return angular.categoryarray.map((label) => String(label || "").trim());
  }
  if (Array.isArray(trace.theta) && trace.theta.length > 1) {
    return trace.theta.slice(0, -1).map((label) => String(label || "").trim());
  }
  return [];
}

function maxWrappedLabelLines(ticktext = []) {
  if (!ticktext.length) {
    return 1;
  }
  return Math.max(
    1,
    ...ticktext.map((label) => (String(label).match(/<br>/gi) || []).length + 1),
  );
}

function applyWrappedPolarAxis(snapshot, rawLabels, labelCount, wrapFn = wrappedAxisLabel) {
  if (!rawLabels.length) {
    return;
  }

  const keys = rawLabels.map((_, index) => `__axis_${index}`);
  const ticktext = rawLabels.map((label) => wrapFn(label, labelCount));

  snapshot.data.forEach((trace) => {
    if (!Array.isArray(trace.theta)) {
      return;
    }

    const pointCount =
      trace.type === "scatterpolar" && Array.isArray(trace.r)
        ? trace.r.length - 1
        : trace.theta.length;
    const seriesKeys = keys.slice(0, pointCount);

    if (trace.type === "scatterpolar" && pointCount > 0) {
      trace.theta = [...seriesKeys, seriesKeys[0]];
      if (trace.customdata) {
        const raw = rawLabels.slice(0, pointCount);
        trace.customdata = [...raw, raw[0] || ""];
      }
      return;
    }

    if (trace.type === "barpolar") {
      trace.theta = seriesKeys;
    }
  });

  const angular = snapshot.layout?.polar?.angularaxis || {};
  snapshot.layout.polar = snapshot.layout.polar || {};
  snapshot.layout.polar.angularaxis = {
    ...angular,
    type: "category",
    categoryorder: "array",
    categoryarray: keys,
    tickmode: "array",
    tickvals: keys,
    ticktext,
    showticklabels: true,
  };
}

function applyWrappedExportLabels(snapshot) {
  const labelCount = drilldownChartLabelCount(snapshot.layout, snapshot.data);
  const scatterTrace = (snapshot.data || []).find((item) => item.type === "scatterpolar");
  const barTrace = (snapshot.data || []).find((item) => item.type === "barpolar");

  if (scatterTrace) {
    applyWrappedPolarAxis(snapshot, extractRadarLabelSeries(snapshot), labelCount);
    return labelCount;
  }

  if (barTrace && Array.isArray(barTrace.theta)) {
    applyWrappedPolarAxis(
      snapshot,
      barTrace.theta.map((label) => String(label || "").trim()),
      labelCount,
    );
    return labelCount;
  }

  return labelCount;
}

function slideWrappedAxisLabel(label, labelCount = 7) {
  const text = String(label || "")
    .replace(/<br\s*\/?>/gi, " ")
    .trim();
  // Deck slides title-case profile names so the radar axes match the slide copy.
  const formatted =
    chartSourceEl?.value === "profiles" ? profileDisplayTitle(text) : humanizeFootballLabel(text);
  if (formatted.length <= 24) {
    return formatted;
  }
  const maxLine = labelCount >= 7 ? 22 : labelCount <= 3 ? 26 : 20;
  const maxLines = labelCount >= 7 ? 2 : 3;
  return wrapLabelText(formatted, maxLine, maxLines);
}

function radarExportRawLabels(snapshot) {
  let rawLabels = extractRadarLabelSeries(snapshot).map((label) =>
    String(label || "")
      .replace(/<br\s*\/?>/gi, " ")
      .trim(),
  );
  if (rawLabels.length) {
    return rawLabels;
  }
  const scatterTrace = (snapshot.data || []).find((item) => item.type === "scatterpolar");
  if (scatterTrace?.customdata?.length) {
    return scatterTrace.customdata
      .slice(0, -1)
      .map((label) => String(label || "").trim())
      .filter(Boolean);
  }
  return [];
}

function radarTrace(
  values,
  labels,
  name,
  color = "#f5c518",
  filled = true,
  labelFormatter = formatAxisLabel,
  options = {},
) {
  const fullLabels = options.fullLabels || labels;
  const compact = Boolean(options.compact);
  const { r, theta } = options.thetaLabels
    ? {
        r: [...values, values[0]],
        theta: [...options.thetaLabels, options.thetaLabels[0]],
      }
    : closedRadarSeries(values, labels, labelFormatter);
  const trace = {
    type: "scatterpolar",
    mode: "lines",
    r,
    theta,
    name,
    fill: filled ? "toself" : "none",
    line: {
      color,
      width: compact ? 2 : 2.5,
      shape: compact ? "linear" : "spline",
      smoothing: compact ? 0 : 0.85,
    },
    fillcolor: filled ? `${color}2e` : undefined,
    hovertemplate: compact
      ? "<b>%{customdata}</b><br>%{r:.1f} percentile<extra>%{fullData.name}</extra>"
      : "<b>%{theta}</b><br>%{r:.1f} percentile<extra></extra>",
  };
  if (compact) {
    trace.customdata = [...fullLabels, fullLabels[0]];
  }
  return trace;
}

function setChartMeta(playerElId, subtitleElId, metaElId, player, subtitle) {
  document.getElementById(playerElId).textContent = player;
  document.getElementById(subtitleElId).textContent = subtitle;
  document.getElementById(metaElId).classList.remove("hidden");
}

function angularRotation(labelCount) {
  const step = 360 / Math.max(labelCount, 1);
  return 90 + step / 2;
}

function shortAxisLabel(label) {
  const text = formatAxisLabel(label);
  if (text.length <= 24) {
    return text;
  }
  return `${text.slice(0, 22)}…`;
}

function polarChartLayout(labelCount, options = {}) {
  const {
    showLegend = false,
    radialaxis = {},
    compact = false,
    drilldownPanel = false,
    drilldownStacked = false,
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
        tickfont: {
          family: chartFonts.family,
          size: labelCount > 6 ? 12 : 13,
          color: "#e2e8f0",
        },
        showline: false,
        gridcolor: "rgba(148, 163, 184, 0.14)",
        linecolor: "rgba(148, 163, 184, 0.08)",
        rotation: angularRotation(labelCount),
        direction: "clockwise",
      }
    : {
        gridcolor: "rgba(148, 163, 184, 0.1)",
        linecolor: "rgba(148, 163, 184, 0.08)",
        tickfont: {
          family: chartFonts.family,
          size: 12,
          color: "#e2e8f0",
        },
        rotation: angularRotation(labelCount),
        direction: "clockwise",
      };

  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: chartFonts,
    polar: {
      domain: drilldownStacked
        ? { x: [0.04, 0.96], y: [0.04, 0.96] }
        : drilldownPanel
          ? { x: [0.05, 0.95], y: [0.04, showLegend ? 0.88 : 0.96] }
          : compact
            ? { x: [0.14, 0.86], y: [0.16, 0.78] }
            : { x: [0.1, 0.9], y: showLegend ? [0.08, 0.86] : [0.06, 0.94] },
      // Barely-there plot area. A solid navy disc fought with the card behind it.
      bgcolor: "rgba(255, 255, 255, 0.022)",
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
    margin: drilldownStacked
      ? { l: 124, r: 124, t: 48, b: 48 }
      : drilldownPanel
        ? { l: 52, r: 52, t: 8, b: showLegend ? 52 : 24 }
        : compact
          ? { l: 72, r: 72, t: 16, b: showLegend ? 64 : 40 }
          : { l: 110, r: 110, t: 24, b: showLegend ? 72 : 24 },
    showlegend: showLegend && !drilldownStacked,
    legend: drilldownPanel
      ? {
          orientation: "h",
          y: -0.12,
          x: 0.5,
          xanchor: "center",
          font: { family: chartFonts.family, size: 9, color: "#cbd5e1" },
          bgcolor: "rgba(15, 23, 42, 0.8)",
          bordercolor: "rgba(148, 163, 184, 0.15)",
        }
      : compact
      ? {
          orientation: "h",
          y: -0.18,
          x: 0.5,
          xanchor: "center",
          font: { family: chartFonts.family, size: 10, color: "#cbd5e1" },
          bgcolor: "rgba(15, 23, 42, 0.8)",
          bordercolor: "rgba(148, 163, 184, 0.15)",
        }
      : {
          orientation: "h",
          y: -0.1,
          x: 0.5,
          xanchor: "center",
          font: { family: chartFonts.family, size: 11, color: "#cbd5e1" },
          bgcolor: "rgba(15, 23, 42, 0.8)",
          bordercolor: "rgba(148, 163, 184, 0.15)",
        },
    hoverlabel: {
      bgcolor: "#0f172a",
      bordercolor: "#334155",
      font: { family: '"IBM Plex Mono", monospace', size: 12, color: "#e2e8f0" },
    },
  };
}

function setStatus(message) {
  statusBarEl.textContent = message;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function readJsonResponse(res) {
  const text = await res.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    const snippet = text.replace(/\s+/g, " ").trim().slice(0, 120);
    throw new Error(
      snippet
        ? `Server returned an invalid response (${res.status}): ${snippet}`
        : `Server returned an invalid response (${res.status}).`,
    );
  }
}

function formatApiError(detail, status) {
  const text = String(detail || "").trim();
  if (status === 429 || /rate limit|429|quota/i.test(text)) {
    return (
      "Impect API rate limit reached — too many requests. " +
      "Waiting to retry automatically, or hard-refresh (Cmd+Shift+R) after a few minutes."
    );
  }
  if (text.startsWith("Impect API error:")) {
    try {
      const payload = JSON.parse(text.replace(/^Impect API error:\s*/, ""));
      if (payload?.message) {
        return `Impect API: ${payload.message}`;
      }
    } catch (error) {
      // fall through
    }
  }
  return text || "Something went wrong — try again.";
}

function showAlert(message) {
  alertBoxEl.textContent = message;
  alertBoxEl.className = "alert";
  alertBoxEl.classList.remove("hidden");
}

function showWarning(message) {
  alertBoxEl.textContent = message;
  alertBoxEl.className = "alert alert-warning";
  alertBoxEl.classList.remove("hidden");
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

function hideAlert() {
  alertBoxEl.classList.add("hidden");
}

function isRateLimitError(message) {
  return /rate limit|429|quota/i.test(String(message || ""));
}

function scheduleRateLimitRetry(retryFn, { label = "Request" } = {}) {
  if (rateLimitRetryTimer) {
    return;
  }
  let remaining = RATE_LIMIT_RETRY_SECONDS;
  setStatus(`${label} paused — Impect rate limit. Retrying in ${remaining}s…`);
  rateLimitRetryTimer = setInterval(() => {
    remaining -= 1;
    if (remaining > 0) {
      setStatus(`${label} paused — Impect rate limit. Retrying in ${remaining}s…`);
      return;
    }
    clearInterval(rateLimitRetryTimer);
    rateLimitRetryTimer = null;
    setStatus(`Retrying ${label.toLowerCase()}…`);
    void retryFn();
  }, 1000);
}

function setConnection(status, message) {
  connectionBadgeEl.className = `badge badge-${status}`;
  connectionBadgeEl.textContent = message;
}

function getSelectedProfileNames() {
  return Array.from(state.selectedProfileNames);
}

function defaultSeasonForComparePlayer(player) {
  const chartableSeasons = (player.seasons || []).filter((season) => season.chartable);
  return chartableSeasons[0]?.iteration_id || null;
}

function getPlayerSeasonsPayload() {
  const payload = {};
  state.comparedPlayers.forEach((entry) => {
    if (entry.seasonIterationId) {
      payload[entry.key] = [entry.seasonIterationId];
    }
  });
  return payload;
}

function getPlayerPositionsPayload() {
  const payload = {};
  state.comparedPlayers.forEach((entry) => {
    if (entry.position) {
      payload[entry.key] = [entry.position];
    }
  });
  return payload;
}

function allComparedPlayersHavePosition() {
  return (
    state.comparedPlayers.length > 0 &&
    state.comparedPlayers.every((entry) => entry.position)
  );
}

function getSeasonModePayload() {
  return {
    last_n_seasons: null,
    combine_seasons: false,
  };
}

function getPlayerCatalogPayload() {
  const catalog = {};
  state.comparedPlayers.forEach((entry) => {
    if (entry.ids_by_iteration && Object.keys(entry.ids_by_iteration).length > 0) {
      catalog[entry.key] = {
        name: entry.name,
        ids_by_iteration: entry.ids_by_iteration,
        squad_ids_by_iteration: entry.squad_ids_by_iteration || {},
      };
    }
  });
  return catalog;
}

function formatPositionOptionLabel(positionEntry) {
  if (positionEntry.shortLabel && positionEntry.label) {
    return `${positionEntry.shortLabel} — ${positionEntry.label}`;
  }
  return positionEntry.label || positionEntry.position || "";
}

function getCompetitionName() {
  const search = playerSearchEl.value.trim();
  if (search.length >= 3) {
    return null;
  }
  return competitionFilterEl.value.trim() || null;
}

function formatPlayerLabel(player) {
  if (player?.label) {
    return player.label;
  }
  const name = player?.name || "Player";
  const namePart = player?.age != null ? `${name} (${player.age})` : name;
  const context = [player?.league, player?.club].filter(Boolean).join(" · ");
  return context ? `${namePart} — ${context}` : namePart;
}

function formatPlayerOptionLabel(player) {
  return formatPlayerLabel(player);
}

function playerDisplayLabel(playerOrEntry) {
  return formatPlayerLabel(playerOrEntry);
}

function formatEmptyPositionsLabel(entry) {
  if (entry.positionError) {
    return entry.positionError;
  }
  const seasons = entry.seasonsWithData || [];
  if (seasons.length > 0) {
    return `No data for this season — available: ${seasons.join(", ")}`;
  }
  return "No data for this season";
}

function getComparedPlayerKeys() {
  if (state.comparedPlayers.length > 0) {
    return state.comparedPlayers.map((entry) => entry.key);
  }
  return playerSelectEl.value ? [playerSelectEl.value] : [];
}

function getPrimaryPlayerKey() {
  return state.comparedPlayers[0]?.key || playerSelectEl.value || "";
}

function findComparedPlayer(key) {
  return state.comparedPlayers.find((entry) => entry.key === key) || null;
}

function findPlayerByKey(key) {
  if (!key) {
    return null;
  }
  const compared = findComparedPlayer(key);
  if (compared) {
    return compared;
  }
  return state.players.find((player) => player.key === key) || null;
}

function getPrimaryPlayer() {
  if (state.comparedPlayers.length > 0) {
    return state.comparedPlayers[0];
  }
  return getSelectedPlayerFromDropdown();
}

function getSelectedPlayer() {
  return getPrimaryPlayer();
}

function updateAddCompareButtonState() {
  const key = playerSelectEl.value;
  const alreadyAdded = state.comparedPlayers.some((entry) => entry.key === key);
  const atCapacity = state.comparedPlayers.length >= STUDIO_PLAYER_SLOTS;
  addComparePlayerBtn.disabled = !key || alreadyAdded || atCapacity;
  addComparePlayerBtn.textContent = alreadyAdded
    ? "Already added"
    : atCapacity
      ? "4 players max"
      : "Add player";
  if (atCapacity) {
    addComparePlayerBtn.title = `Maximum ${STUDIO_PLAYER_SLOTS} players`;
  } else {
    addComparePlayerBtn.removeAttribute("title");
  }
}

let photoStudioApi = null;

function applySavedPlayerPhoto(player, photoUrl) {
  const cacheBustedUrl = `${photoUrl}${photoUrl.includes("?") ? "&" : "?"}t=${Date.now()}`;
  const compared = state.comparedPlayers.find((entry) => entry.key === player.key);
  if (compared) {
    compared.photo_url = cacheBustedUrl;
  }
  if (state.lastChartData?.players?.length) {
    state.lastChartData.players = state.lastChartData.players.map((entry) =>
      entry.key === player.key || entry.player === player.name
        ? { ...entry, photo_url: cacheBustedUrl }
        : entry,
    );
    if (state.lastChartData.profile_drilldowns?.length) {
      state.lastChartData.profile_drilldowns = state.lastChartData.profile_drilldowns.map((drilldown) => ({
        ...drilldown,
        players: (drilldown.players || []).map((entry) =>
          entry.key === player.key || entry.player === player.name
            ? { ...entry, photo_url: cacheBustedUrl }
            : entry,
        ),
      }));
      renderProfileDrilldowns(state.lastChartData);
    }
  }
  refreshPhotoStudio();
}

function refreshPhotoStudio() {
  photoStudioApi?.refresh();
}

function seasonLabelForEntry(entry) {
  if (entry.seasonIterationId) {
    const season = (entry.seasons || []).find(
      (item) => item.iteration_id === entry.seasonIterationId,
    );
    return season?.label || "Selected season";
  }
  return "Pick a season";
}

function showStudioView(view) {
  state.studioView = view;
  if (studioPageBuildEl) {
    studioPageBuildEl.classList.toggle("hidden", view !== "build");
  }
  if (studioPageCompareEl) {
    studioPageCompareEl.classList.toggle("hidden", view !== "compare");
  }
  if (studioPageTitleEl) {
    studioPageTitleEl.textContent =
      view === "compare" ? "Profile comparison" : "Player comparison";
  }
  if (studioPageLedeEl) {
    studioPageLedeEl.textContent =
      view === "compare"
        ? "Profile scores up top, then the radar and a factor-by-factor breakdown of each profile."
        : "Search players, set position & season, pick profiles — then open the comparison view.";
  }
  if (view === "compare") {
    updateWholeDeckButtonState();
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderStudioPositionNav() {
  if (!studioPositionNavEl) {
    return;
  }
  const counts = new Map();
  state.comparedPlayers.forEach((entry) => {
    const key = entry.position || "UNKNOWN";
    const label = positionAbbrev(key, entry.position_label) || key;
    counts.set(label, (counts.get(label) || 0) + 1);
  });

  if (!counts.size) {
    studioPositionNavEl.innerHTML = `<span class="studio-position-pill">Add players to see groups</span>`;
    return;
  }

  studioPositionNavEl.innerHTML = [...counts.entries()]
    .map(
      ([label, count]) =>
        `<span class="studio-position-pill studio-position-pill--active">${label} (${count})</span>`,
    )
    .join("");
}

function renderStudioRosterChips() {
  if (!studioRosterMetaEl || !studioRosterChipsEl) {
    return;
  }
  const players = state.comparedPlayers;
  const profileCount = state.selectedProfileNames.size;
  studioRosterMetaEl.textContent = `${players.length}/${STUDIO_PLAYER_SLOTS} player${
    players.length === 1 ? "" : "s"
  } selected${profileCount ? ` · ${profileCount} profile${profileCount === 1 ? "" : "s"}` : ""}`;

  if (!players.length) {
    studioRosterChipsEl.innerHTML = "";
    return;
  }

  studioRosterChipsEl.innerHTML = "";
  players.forEach((entry) => {
    const chip = document.createElement("span");
    chip.className = "studio-roster-chip";
    chip.style.borderColor = "var(--border)";
    const name = document.createElement("span");
    name.textContent = entry.name;
    chip.appendChild(name);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${entry.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removePlayerFromComparison(entry.key));
    chip.appendChild(remove);
    studioRosterChipsEl.appendChild(chip);
  });
}

function updateStudioBuildHint() {
  if (!studioBuildHintEl) {
    return;
  }
  const reason = chartBlockReason();
  if (reason) {
    studioBuildHintEl.textContent = reason;
    return;
  }
  studioBuildHintEl.textContent = "Ready — pick one season per player above.";
}

function updateStudioCompareMeta(data) {
  if (!studioCompareMetaEl || !data) {
    return;
  }
  const players = data.players || [];
  const seasonParts = players
    .map((entry) => `${entry.player}: ${entry.season_label || "—"}`)
    .join(" · ");
  const positionParts = [...new Set(players.map((entry) => entry.position_label).filter(Boolean))].join(
    ", ",
  );
  studioCompareMetaEl.textContent = [seasonParts, positionParts].filter(Boolean).join(" · ");
}

function renderStudioShellUI() {
  renderStudioPositionNav();
  renderStudioRosterChips();
  updateStudioBuildHint();
}

function renderComparePlayerChips() {
  comparePlayerChipsEl.innerHTML = "";

  if (state.comparedPlayers.length === 0) {
    comparePlayerChipsEl.innerHTML = `<span class="chip muted-chip">Search and add players to compare</span>`;
    renderStudioPlayerGrid();
    renderStudioShellUI();
    refreshPhotoStudio();
    updateAddCompareButtonState();
    return;
  }

  comparePlayerChipsEl.innerHTML = `<span class="chip muted-chip">${state.comparedPlayers.length} player(s) · set position &amp; season per player below</span>`;
  renderStudioPlayerGrid();
  renderStudioShellUI();
  refreshPhotoStudio();
  updateAddCompareButtonState();
}

function positionCacheKey(entry) {
  const seasonId = entry.seasonIterationId;
  return `${entry.key}|${seasonId || "none"}|${chartSourceEl.value}|specific`;
}

function applyPositionCache(entry) {
  const cached = state.positionCache.get(positionCacheKey(entry));
  if (!cached) {
    return false;
  }
  if (cached.cachedAt && Date.now() - cached.cachedAt > POSITION_CACHE_TTL_MS) {
    state.positionCache.delete(positionCacheKey(entry));
    return false;
  }
  entry.positionsLoaded = true;
  entry.availablePositions = cached.positions || [];
  entry.positionHint = cached.hint || "";
  entry.seasonsWithData = cached.seasonsWithData || [];
  entry.positionError = cached.error || "";
  if (cached.iterationId) {
    entry.seasonIterationId = cached.iterationId;
  }
  const stillValid = entry.availablePositions.some(
    (positionEntry) => positionEntry.position === entry.position,
  );
  if (!stillValid && cached.defaultPosition) {
    entry.position = cached.defaultPosition;
  } else if (!entry.position && cached.defaultPosition) {
    entry.position = cached.defaultPosition;
  }
  return true;
}

function cachePositionData(entry, playerData) {
  if (!playerData) {
    return;
  }
  state.positionCache.set(positionCacheKey(entry), {
    positions: playerData.positions || [],
    hint: playerData.hint || "",
    seasonsWithData: playerData.seasons_with_data || [],
    error: "",
    defaultPosition: playerData.default_position || "",
    iterationId: playerData.iteration_id || entry.seasonIterationId,
    cachedAt: Date.now(),
  });
}

function applyPositionDataToEntry(entry, playerData) {
  entry.positionsLoaded = true;
  if (!playerData) {
    entry.availablePositions = [];
    entry.seasonsWithData = [];
    entry.positionError = "Player not found in catalog";
    return;
  }

  entry.positionError = "";
  entry.availablePositions = playerData.positions || [];
  entry.positionHint = playerData.hint || "";
  entry.seasonsWithData = playerData.seasons_with_data || [];

  if (playerData.iteration_id && entry.seasonIterationId !== playerData.iteration_id) {
    entry.seasonIterationId = playerData.iteration_id;
  }

  const stillValid = entry.availablePositions.some(
    (positionEntry) => positionEntry.position === entry.position,
  );
  if (!stillValid && playerData.default_position) {
    entry.position = playerData.default_position;
  } else if (!entry.position && playerData.default_position) {
    entry.position = playerData.default_position;
  }

  cachePositionData(entry, playerData);
}

function buildComparePlayerRow(entry, index) {
  const row = document.createElement("div");
  row.className = "compare-player-row compare-player-row--compact";
  row.dataset.playerKey = entry.key;

  const header = document.createElement("div");
  header.className = "compare-player-header";

  const name = document.createElement("span");
  name.className = "compare-player-name";
  name.textContent = playerDisplayLabel(entry);
  header.appendChild(name);

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "studio-player-remove";
  removeBtn.setAttribute("aria-label", `Remove ${entry.name}`);
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", () => {
    removePlayerFromComparison(entry.key);
  });
  header.appendChild(removeBtn);

  row.appendChild(header);

  const controls = document.createElement("div");
  controls.className = "compare-player-controls";

  const positionField = document.createElement("label");
  positionField.className = "compare-player-field";
  const positionLabel = document.createElement("span");
  positionLabel.textContent = "Position";
  positionField.appendChild(positionLabel);

  const positionSelect = document.createElement("select");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Select role…";
  positionSelect.appendChild(placeholder);

  (state.studioPositionOptions || []).forEach((positionEntry) => {
    const option = document.createElement("option");
    option.value = positionEntry.position;
    option.textContent = formatPositionOptionLabel(positionEntry);
    positionSelect.appendChild(option);
  });

  if (entry.position) {
    positionSelect.value = entry.position;
  }

  positionSelect.addEventListener("change", () => {
    entry.position = positionSelect.value;
    const selectedOption = (state.studioPositionOptions || []).find(
      (item) => item.position === entry.position,
    );
    entry.position_label = selectedOption?.label || "";
    updateProfilesFromPositionMeta();
    updateChartButtonState();
    renderStudioShellUI();
  });
  positionField.appendChild(positionSelect);
  controls.appendChild(positionField);

  const seasonField = document.createElement("label");
  seasonField.className = "compare-player-field";
  const seasonLabel = document.createElement("span");
  seasonLabel.textContent = "Season data";
  seasonField.appendChild(seasonLabel);

  const seasonSelect = document.createElement("select");
  seasonSelect.className = "season-select";
  const chartableSeasons = (entry.seasons || []).filter((season) => season.chartable);
  if (!chartableSeasons.length) {
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "No seasons with data";
    seasonSelect.appendChild(emptyOption);
    seasonSelect.disabled = true;
  } else {
    chartableSeasons.forEach((season) => {
      const option = document.createElement("option");
      option.value = String(season.iteration_id);
      option.textContent = season.label;
      option.title = season.label;
      seasonSelect.appendChild(option);
    });

    if (entry.seasonIterationId) {
      seasonSelect.value = String(entry.seasonIterationId);
    }
    if (seasonSelect.selectedOptions[0]) {
      seasonSelect.title = seasonSelect.selectedOptions[0].textContent;
    }

    seasonSelect.addEventListener("change", () => {
      entry.seasonIterationId = Number(seasonSelect.value);
      seasonSelect.title = seasonSelect.selectedOptions[0]?.textContent || "";
      updateChartButtonState();
    });
  }
  seasonField.appendChild(seasonSelect);
  controls.appendChild(seasonField);

  row.appendChild(controls);

  return row;
}

function updateComparePlayerRow(playerKey) {
  const index = state.comparedPlayers.findIndex((entry) => entry.key === playerKey);
  if (index < 0) {
    return;
  }
  const entry = state.comparedPlayers[index];
  const existing =
    studioPlayerGridEl?.querySelector(`[data-player-key="${CSS.escape(playerKey)}"]`) ||
    comparePlayerListEl?.querySelector(`[data-player-key="${CSS.escape(playerKey)}"]`);
  const row = buildComparePlayerRow(entry, index);
  if (existing) {
    existing.replaceWith(row);
    photoStudioApi?.refresh();
    return;
  }
  renderStudioPlayerGrid();
}

function buildStudioEmptySlot(index) {
  const empty = document.createElement("div");
  empty.className = "studio-player-empty";
  empty.innerHTML = `
    <span class="studio-player-empty__slot">Slot ${index + 1}</span>
    <span class="studio-player-empty__hint">Search &amp; add player</span>
  `;
  return empty;
}

function ensureStudioPlayerGridStructure() {
  if (!studioPlayerGridEl || studioPlayerGridEl.dataset.ready === "1") {
    return;
  }
  studioPlayerGridEl.innerHTML = "";
  const slotMarkup = window.PhotoStudio?.buildSlotMarkup;
  for (let index = 0; index < STUDIO_PLAYER_SLOTS; index += 1) {
    const column = document.createElement("div");
    column.className = "studio-player-column studio-player-column--empty";
    column.dataset.playerSlot = String(index);

    const cardMount = document.createElement("div");
    cardMount.className = "studio-player-card-mount";
    cardMount.dataset.playerCard = String(index);
    cardMount.appendChild(buildStudioEmptySlot(index));

    const photoMount = document.createElement("div");
    photoMount.className = "studio-player-photo-mount";
    photoMount.dataset.photoSlot = String(index);
    photoMount.innerHTML = slotMarkup ? slotMarkup(index) : "";

    column.appendChild(cardMount);
    column.appendChild(photoMount);
    studioPlayerGridEl.appendChild(column);
  }
  studioPlayerGridEl.dataset.ready = "1";
}

function renderStudioPlayerGrid() {
  ensureStudioPlayerGridStructure();
  if (!studioPlayerGridEl) {
    return;
  }

  for (let index = 0; index < STUDIO_PLAYER_SLOTS; index += 1) {
    const entry = state.comparedPlayers[index];
    const column = studioPlayerGridEl.querySelector(`[data-player-slot="${index}"]`);
    const cardMount = studioPlayerGridEl.querySelector(`[data-player-card="${index}"]`);
    if (!column || !cardMount) {
      continue;
    }

    cardMount.innerHTML = "";
    if (entry) {
      column.classList.remove("studio-player-column--empty");
      cardMount.appendChild(buildComparePlayerRow(entry, index));
    } else {
      column.classList.add("studio-player-column--empty");
      cardMount.appendChild(buildStudioEmptySlot(index));
    }
  }

  photoStudioApi?.refresh();
}

function renderComparePlayerList() {
  renderStudioPlayerGrid();
}

function playerHasSeasonCatalog(playerOrEntry) {
  const chartable = playerOrEntry?.chartable_season_ids || [];
  const ids = playerOrEntry?.ids_by_iteration || {};
  return chartable.length > 0 || Object.keys(ids).length > 0;
}

async function refreshComparedPlayerHistory(entry) {
  const res = await fetchWithTimeout(
    "/api/player-history",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        player_key: entry.key,
        player_catalog: {
          [entry.key]: {
            name: entry.name,
            impect_player_id: entry.impect_player_id ?? null,
            ids_by_iteration: entry.ids_by_iteration,
            squad_ids_by_iteration: entry.squad_ids_by_iteration,
          },
        },
      }),
    },
    60000,
  );
  const data = await readJsonResponse(res);
  if (!res.ok) {
    return false;
  }

  const player = data.player || {};
  entry.seasons = player.seasons || entry.seasons;
  entry.chartable_season_ids = player.chartable_season_ids || entry.chartable_season_ids;
  entry.ids_by_iteration = player.ids_by_iteration || entry.ids_by_iteration;
  entry.squad_ids_by_iteration = player.squad_ids_by_iteration || entry.squad_ids_by_iteration;
  entry.club = player.club || entry.club;
  entry.league = player.league || entry.league;
  entry.label = player.label || entry.label;
  if (
    !entry.seasonIterationId ||
    !(entry.chartable_season_ids || []).includes(entry.seasonIterationId)
  ) {
    entry.seasonIterationId = defaultSeasonForComparePlayer(entry);
  }
  return true;
}

async function addPlayerToComparison(player) {
  if (!player?.key || state.comparedPlayers.some((entry) => entry.key === player.key)) {
    return null;
  }
  if (state.comparedPlayers.length >= STUDIO_PLAYER_SLOTS) {
    showAlert(`Maximum ${STUDIO_PLAYER_SLOTS} players — remove one to add another.`);
    return null;
  }
  const entry = {
    key: player.key,
    name: player.name,
    impect_player_id: player.impect_player_id ?? null,
    label: player.label || formatPlayerOptionLabel(player),
    age: player.age ?? null,
    league: player.league || "",
    club: player.club || "",
    seasons: player.seasons || [],
    chartable_season_ids: player.chartable_season_ids || [],
    ids_by_iteration: player.ids_by_iteration || {},
    squad_ids_by_iteration: player.squad_ids_by_iteration || {},
    seasonIterationId: defaultSeasonForComparePlayer(player),
    position: null,
    position_label: "",
    positionsLoaded: true,
  };
  state.comparedPlayers.push(entry);
  renderComparePlayerChips();
  updateChartButtonState();

  if (playerHasSeasonCatalog(player)) {
    entry.historyLoaded = true;
  } else {
    const refreshed = await refreshComparedPlayerHistory(entry);
    entry.historyLoaded = refreshed || playerHasSeasonCatalog(entry);
  }
  renderComparePlayerChips();
  updateChartButtonState();

  return entry;
}

async function removePlayerFromComparison(key) {
  state.comparedPlayers = state.comparedPlayers.filter((entry) => entry.key !== key);

  if (state.comparedPlayers.length === 0) {
    state.availableProfiles = [];
    state.profileLoadWarnings = [];
    state.selectedProfileNames.clear();
    clearChartExportState();
    renderComparePlayerChips();
    renderProfileUI();
    updateChartButtonState();
    return;
  }

  renderComparePlayerChips();
  updateProfilesFromPositionMeta();
  updateChartButtonState();
}

function getValidSelectedProfiles() {
  return getSelectedProfileNames().filter((name) => state.availableProfiles.includes(name));
}

function syncSelectedProfilesToAvailable() {
  if (state.availableProfiles.length === 0) {
    state.selectedProfileNames.clear();
    return;
  }

  const kept = getValidSelectedProfiles();
  if (kept.length >= 2) {
    state.selectedProfileNames = new Set(kept);
    return;
  }

  if (state.availableProfiles.length >= 2) {
    state.selectedProfileNames = new Set(state.availableProfiles);
  } else {
    state.selectedProfileNames = new Set(kept);
  }
}

function comparedPlayersSharePosition() {
  const positions = state.comparedPlayers.map((entry) => entry.position).filter(Boolean);
  if (positions.length < 2) {
    return true;
  }
  return new Set(positions).size === 1;
}

function mixedPositionsProfileHint() {
  if (comparedPlayersSharePosition()) {
    return null;
  }
  const labels = [
    ...new Set(
      state.comparedPlayers
        .map((entry) => positionAbbrev(entry.position, entry.position_label) || entry.position)
        .filter(Boolean),
    ),
  ];
  if (labels.length < 2) {
    return null;
  }
  return `Players are in different positions (${labels.join(", ")}) — only profiles shared by every selected role are shown.`;
}

function chartBlockReason() {
  if (getComparedPlayerKeys().length === 0) {
    return "Add at least one player to the comparison.";
  }
  if (!allComparedPlayersHavePosition()) {
    return "Select a role for each compared player.";
  }
  const missingSeason = state.comparedPlayers.find((entry) => !entry.seasonIterationId);
  if (missingSeason) {
    return `Pick a season for ${missingSeason.name}.`;
  }
  if (chartSourceEl.value === "profiles") {
    if (state.availableProfiles.length < 2) {
      const mixedHint = mixedPositionsProfileHint();
      if (mixedHint) {
        return mixedHint;
      }
      const count = state.comparedPlayers.length || getComparedPlayerKeys().length;
      let message =
        `Only ${state.availableProfiles.length} profile(s) are shared by all ${count} players. ` +
        "Compare players in the same position, or use standard Impect profiles.";
      if (state.profileLoadWarnings.length > 0) {
        message += ` ${state.profileLoadWarnings.join(" ")}`;
      }
      return message;
    }
    if (getValidSelectedProfiles().length < 2) {
      return "Select at least 2 profiles from the shared list.";
    }
  }
  return null;
}

function canGenerateCharts() {
  return chartBlockReason() === null;
}

function updateChartButtonState() {
  const reason = chartBlockReason();
  loadChartsBtn.disabled = reason !== null;
  exportRadarImageBtn.disabled = !state.lastChartData;
  exportPizzaImageBtn.disabled = !state.lastChartData;
  updateWholeDeckButtonState();
  updateStudioBuildHint();
  if (reason && getComparedPlayerKeys().length > 0) {
    setStatus(reason);
  }
}

function clearChartExportState() {
  state.lastChartData = null;
  invalidateWholeDeckCaptureCache();
  exportRadarImageBtn.disabled = true;
  exportPizzaImageBtn.disabled = true;
  updateWholeDeckButtonState();
}

const POSITION_ABBREV = {
  GOALKEEPER: "GK",
  LEFT_WINGBACK_DEFENDER: "LWB",
  RIGHT_WINGBACK_DEFENDER: "RWB",
  CENTRAL_DEFENDER: "CB",
  DEFENSE_MIDFIELD: "DM",
  CENTRAL_MIDFIELD: "CM",
  ATTACKING_MIDFIELD: "AM",
  LEFT_WINGER: "LW",
  RIGHT_WINGER: "RW",
  CENTER_FORWARD: "CF",
};

function playerInitials(name) {
  return String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() || "")
    .join("");
}

function positionAbbrev(position, positionLabel = "") {
  const code = String(position || "")
    .trim()
    .toUpperCase();
  if (POSITION_ABBREV[code]) {
    return POSITION_ABBREV[code];
  }
  const label = String(positionLabel || "").trim().toLowerCase();
  const labelToAbbrev = {
    goalkeeper: "GK",
    "left wing-back": "LWB",
    "right wing-back": "RWB",
    "centre-back": "CB",
    "center-back": "CB",
    "defensive midfield": "DM",
    "central midfield": "CM",
    "attacking midfield": "AM",
    "left winger": "LW",
    "right winger": "RW",
    "centre-forward": "CF",
    "center-forward": "CF",
  };
  if (label && labelToAbbrev[label]) {
    return labelToAbbrev[label];
  }
  if (code) {
    return code
      .split("_")
      .map((part) => part[0] || "")
      .join("")
      .toUpperCase();
  }
  return "POS";
}

function playersForExportFilename(data) {
  if (data?.players?.length) {
    return data.players.map((entry, index) => {
      const compared = state.comparedPlayers[index];
      return {
        player: entry.player,
        position: entry.position || compared?.position || "",
        position_label: entry.position_label || "",
      };
    });
  }
  const compared = state.comparedPlayers[0];
  return [
    {
      player: data?.player || "Player",
      position: data?.position || compared?.position || "",
      position_label: data?.position_label || "",
    },
  ];
}

function exportDeckPdfFileName(data) {
  const players = playersForExportFilename(data);
  const initials = players.map((entry) => playerInitials(entry.player)).filter(Boolean);
  const positions = players.map((entry) =>
    positionAbbrev(entry.position, entry.position_label),
  );
  const uniquePositions = [...new Set(positions.filter(Boolean))];
  const positionPart =
    uniquePositions.length === 1
      ? uniquePositions[0]
      : positions.filter(Boolean).join("-");
  const date = new Date().toISOString().slice(0, 10);
  const slug = [...initials, positionPart].filter(Boolean).join("-") || "report";
  return `${slug}-${date}.pdf`;
}

function exportFileName(data, extension, { deck = false } = {}) {
  const players = (data.players || []).map((entry) => entry.player).join(" vs ") || data.player || "report";
  const slug = players
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const date = new Date().toISOString().slice(0, 10);
  const suffix = deck ? "-deck" : "";
  return `impect-${slug || "report"}${suffix}-${date}.${extension}`;
}

let wholeDeckExportButtons = [];

function canExportWholeDeck() {
  if (chartSourceEl.value !== "profiles" || typeof html2canvas !== "function") {
    return false;
  }
  const hasFront = Boolean(studioComparisonFrontEl?.querySelector(".comparison-frame--keynote"));
  const hasDrilldowns = (state.lastChartData?.profile_drilldowns || []).length > 0;
  const hasRadar = Boolean(document.getElementById("radarChart")?.data);
  return Boolean(state.lastChartData && (hasFront || hasDrilldowns || hasRadar));
}

function updateWholeDeckButtonState() {
  const enabled = canExportWholeDeck();
  wholeDeckExportButtons.forEach((button) => {
    button.disabled = !enabled;
  });
}

const APP_EXPORT_BG = "#0a0a0a";
const APP_EXPORT_POLAR_BG = "#111111";

const DARK_EXPORT_POLAR_GRID = {
  angularaxis: {
    gridcolor: "rgba(148, 163, 184, 0.14)",
    linecolor: "rgba(148, 163, 184, 0.08)",
  },
  radialaxis: {
    gridcolor: "rgba(148, 163, 184, 0.12)",
  },
};

function applyDarkExportPlotlyTheme(exportLayout, { transparent = false } = {}) {
  exportLayout.paper_bgcolor = transparent ? "rgba(0,0,0,0)" : APP_EXPORT_BG;
  exportLayout.plot_bgcolor = transparent ? "rgba(0,0,0,0)" : APP_EXPORT_BG;
  if (!exportLayout.polar) {
    return exportLayout;
  }
  exportLayout.polar.bgcolor = transparent
    ? "rgba(255, 255, 255, 0.035)"
    : APP_EXPORT_POLAR_BG;
  if (exportLayout.polar.angularaxis) {
    exportLayout.polar.angularaxis.gridcolor =
      DARK_EXPORT_POLAR_GRID.angularaxis.gridcolor;
    exportLayout.polar.angularaxis.linecolor =
      DARK_EXPORT_POLAR_GRID.angularaxis.linecolor;
  }
  if (exportLayout.polar.radialaxis) {
    exportLayout.polar.radialaxis.gridcolor =
      DARK_EXPORT_POLAR_GRID.radialaxis.gridcolor;
  }
  return exportLayout;
}

function scaleLayoutFonts(layout, factor = 1.5) {
  const scaled = JSON.parse(JSON.stringify(layout));
  if (scaled.font?.size) {
    scaled.font.size = Math.round(scaled.font.size * factor);
  }
  if (scaled.legend?.font?.size) {
    scaled.legend.font.size = Math.round(scaled.legend.font.size * factor);
  }
  if (scaled.polar?.angularaxis?.tickfont?.size) {
    scaled.polar.angularaxis.tickfont.size = Math.round(
      scaled.polar.angularaxis.tickfont.size * factor,
    );
  }
  return scaled;
}

const DRILLDOWN_CARD_EXPORT = {
  imageScale: 2,
};

const DECK_EXPORT = {
  imageScale: 1.5,
  captureConcurrency: 1,
  slideTimeoutMs: 90000,
  imageFormat: "jpeg",
  jpegQuality: 0.94,
};

let plotlyCaptureQueue = Promise.resolve();
let wholeDeckCaptureCache = null;

function resetPlotlyCaptureQueue() {
  plotlyCaptureQueue = Promise.resolve();
}

async function withTimeout(task, timeoutMs, timeoutMessage, { onTimeout } = {}) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(task),
      new Promise((_, reject) => {
        timer = window.setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
      }),
    ]);
  } catch (error) {
    if (onTimeout && error?.message === timeoutMessage) {
      onTimeout();
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

async function waitForPlotlyChart(elementId, maxMs = 12000) {
  const started = Date.now();
  return new Promise((resolve) => {
    function tick() {
      const el = document.getElementById(elementId);
      if (el?.data) {
        resolve();
        return;
      }
      if (Date.now() - started >= maxMs) {
        resolve();
        return;
      }
      requestAnimationFrame(tick);
    }
    tick();
  });
}

async function waitForExportImages(surface, timeoutMs = 8000) {
  const images = [...surface.querySelectorAll("img")];
  await Promise.all(
    images.map(
      (image) =>
        new Promise((resolve) => {
          if (image.complete && image.naturalWidth > 0) {
            resolve();
            return;
          }
          const timer = window.setTimeout(resolve, timeoutMs);
          image.onload = () => {
            window.clearTimeout(timer);
            resolve();
          };
          image.onerror = () => {
            window.clearTimeout(timer);
            resolve();
          };
        }),
    ),
  );
}

function wholeDeckCaptureCacheKey(data) {
  const drilldowns = data?.profile_drilldowns || [];
  return JSON.stringify({
    players: (data?.players || []).map((entry) => ({
      player: entry.player,
      season_label: entry.season_label || "",
      position_label: entry.position_label || "",
    })),
    profiles: drilldowns.map((entry) => entry.profile),
    excluded: [...state.exportExcluded].sort(),
  });
}

function invalidateWholeDeckCaptureCache() {
  wholeDeckCaptureCache = null;
}

async function mapWithConcurrency(items, limit, worker) {
  if (!items.length) {
    return [];
  }
  const results = new Array(items.length);
  let nextIndex = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(runners);
  return results;
}

function drilldownChartLabelCount(layout, data) {
  const categoryCount = layout?.polar?.angularaxis?.categoryarray?.length;
  if (categoryCount) {
    return categoryCount;
  }
  const thetaCount = data?.[0]?.theta?.length || 0;
  return Math.max(thetaCount - 1, 1);
}

function drilldownChartLabelFontSize(labelCount) {
  if (labelCount >= 11) {
    return 10;
  }
  if (labelCount >= 9) {
    return 11;
  }
  if (labelCount >= 7) {
    return 12;
  }
  if (labelCount >= 5) {
    return 13;
  }
  return 14;
}

// Slide radars are exported small and scaled up into the 1920px slide, so these
// sizes are deliberately larger than the on-screen chart.
function drilldownSlideChartLabelFontSize(labelCount) {
  if (labelCount >= 9) {
    return 26;
  }
  if (labelCount >= 7) {
    return 30;
  }
  if (labelCount >= 5) {
    return 33;
  }
  return 36;
}

function boostExportRadarTraces(snapshot) {
  (snapshot.data || []).forEach((trace) => {
    if (trace.type !== "scatterpolar") {
      return;
    }
    trace.fill = "toself";
    if (trace.line) {
      trace.line.width = Math.max(Number(trace.line.width) || 2, 2.75);
    }
    const lineColor = trace.line?.color;
    if (typeof lineColor === "string" && lineColor.startsWith("#") && lineColor.length >= 7) {
      trace.fillcolor = `${lineColor.slice(0, 7)}55`;
    } else if (trace.fillcolor && typeof trace.fillcolor === "string") {
      trace.fillcolor = trace.fillcolor.replace(/2e$/i, "55").replace(/33$/i, "55");
    }
    trace.opacity = 0.92;
  });
}

function drilldownSlideChartMargins(labelCount, ticktext = [], panelWidth = 1240) {
  const lineCount = maxWrappedLabelLines(ticktext);
  const lineBoost = Math.max(0, lineCount - 1) * 14;
  const narrow = panelWidth < 560;
  const baseSide = narrow
    ? labelCount <= 3
      ? 118
      : 96
    : labelCount >= 9
      ? 176
      : labelCount >= 7
        ? 194
        : labelCount <= 3
          ? 168
          : 186;
  const side = baseSide + lineBoost * 2;
  return {
    l: side + 14,
    r: side + 10,
    t: 62 + lineBoost,
    b: 62 + lineBoost,
  };
}

function drilldownChartExportSize(labelCount, showLegend = false) {
  const sidePad = labelCount >= 12 ? 88 : labelCount >= 9 ? 80 : labelCount >= 6 ? 72 : 64;
  const core = Math.min(480, 260 + labelCount * 14);
  const width = core + sidePad;
  const legendPad = showLegend ? 40 : 12;
  const height = Math.round(core * 1.15 + sidePad * 0.25 + legendPad);
  return {
    width: Math.round(width),
    height: Math.round(height),
  };
}

function drilldownChartDomain(labelCount, showLegend = false) {
  const bottom = showLegend ? 0.06 : 0.03;
  const top = 0.96;
  if (labelCount >= 12) {
    return { x: [0.08, 0.92], y: [bottom, top] };
  }
  if (labelCount >= 8) {
    return { x: [0.06, 0.94], y: [bottom, top] };
  }
  return { x: [0.05, 0.95], y: [bottom, top] };
}

function drilldownChartMargins(labelCount, showLegend, ticktext = []) {
  const side = labelCount >= 12 ? 70 : labelCount >= 9 ? 62 : labelCount >= 6 ? 54 : 46;
  const lineBoost = (maxWrappedLabelLines(ticktext) - 1) * 16;
  return {
    l: side + lineBoost,
    r: side + lineBoost,
    t: 10 + Math.round(lineBoost * 0.35),
    b: (showLegend ? 26 : 10) + Math.round(lineBoost * 0.2),
  };
}

function chartExportDimensions(el, compact = false) {
  const rect = el.getBoundingClientRect();
  const minWidth = compact ? 480 : 560;
  const minHeight = compact ? 380 : 420;
  return {
    width: Math.round(Math.max(rect.width, minWidth) * 2),
    height: Math.round(Math.max(rect.height, minHeight) * 2),
  };
}

function buildSlideDeckExportLayout(compact = false) {
  return {
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    "font.color": "#0f172a",
    "font.size": compact ? 15 : 14,
    "polar.bgcolor": "#f8fafc",
    "polar.gridcolor": "#e2e8f0",
    "polar.radialaxis.gridcolor": "#e2e8f0",
    "polar.domain.x": [0.05, 0.58],
    "polar.domain.y": compact ? [0.14, 0.82] : [0.1, 0.9],
    "polar.angularaxis.tickfont.size": compact ? 15 : 14,
    "polar.angularaxis.tickfont.color": "#1e293b",
    showlegend: true,
    legend: {
      orientation: "h",
      y: compact ? -0.1 : -0.08,
      x: 0.29,
      xanchor: "center",
      font: { family: "Arial, sans-serif", size: 13, color: "#334155" },
      bgcolor: "rgba(255,255,255,0.9)",
      bordercolor: "#e2e8f0",
    },
    margin: compact
      ? { l: 48, r: 420, t: 28, b: 72 }
      : { l: 56, r: 420, t: 32, b: 64 },
  };
}

function buildAppExportLayout(layout, { fontFactor = 1.5, marginFactor = 1.35 } = {}) {
  const exportLayout = applyDarkExportPlotlyTheme(scaleLayoutFonts(layout, fontFactor));
  delete exportLayout.width;
  delete exportLayout.height;

  const ticktext = exportLayout.polar?.angularaxis?.ticktext || [];
  const lineBoost = (maxWrappedLabelLines(ticktext) - 1) * 18;
  exportLayout.margin = {
    l: Math.round((exportLayout.margin?.l || 72) * marginFactor + lineBoost),
    r: Math.round((exportLayout.margin?.r || 72) * marginFactor + lineBoost),
    t: Math.round((exportLayout.margin?.t || 16) * marginFactor + lineBoost * 0.35),
    b: Math.round((exportLayout.margin?.b || 24) * marginFactor + lineBoost * 0.2),
  };

  if (exportLayout.polar?.angularaxis?.tickfont) {
    exportLayout.polar.angularaxis.tickfont.size = Math.max(
      exportLayout.polar.angularaxis.tickfont.size || 12,
      11,
    );
  }

  return exportLayout;
}

function buildMainRadarSlideChartLayout(layout, labelCount = 8) {
  const exportLayout = JSON.parse(JSON.stringify(layout));
  const axisFontSize = Math.max(drilldownSlideChartLabelFontSize(labelCount) - 2, 16);

  applyDarkExportPlotlyTheme(exportLayout, { transparent: true });
  exportLayout.autosize = false;
  exportLayout.showlegend = false;

  if (exportLayout.font?.size) {
    exportLayout.font.size = axisFontSize;
  }
  if (exportLayout.polar?.angularaxis?.tickfont) {
    exportLayout.polar.angularaxis.tickfont.size = axisFontSize;
    exportLayout.polar.angularaxis.tickfont.color = "#e2e8f0";
  }
  if (exportLayout.polar) {
    exportLayout.polar.domain = { x: [0.02, 0.98], y: [0.01, 0.99] };
  }

  // Side margins carry the long axis labels; top/bottom only need room for the
  // single label that sits on the vertical axis.
  const ticktext = exportLayout.polar?.angularaxis?.ticktext || [];
  const lineBoost = (maxWrappedLabelLines(ticktext) - 1) * 16;
  const side = (labelCount >= 8 ? 200 : labelCount <= 4 ? 240 : 220) + lineBoost;
  exportLayout.margin = {
    l: side,
    r: side,
    t: 62 + lineBoost,
    b: 62 + lineBoost,
  };

  return exportLayout;
}

function buildDrilldownCardChartLayout(layout, labelCount = 5) {
  const exportLayout = JSON.parse(JSON.stringify(layout));
  const axisFontSize = drilldownChartLabelFontSize(labelCount);
  const showLegend = Boolean(exportLayout.showlegend);
  const exportSize = drilldownChartExportSize(labelCount, showLegend);

  applyDarkExportPlotlyTheme(exportLayout);
  exportLayout.width = exportSize.width;
  exportLayout.height = exportSize.height;
  exportLayout.autosize = false;

  if (exportLayout.font?.size) {
    exportLayout.font.size = axisFontSize;
  }
  if (exportLayout.polar?.angularaxis?.tickfont) {
    exportLayout.polar.angularaxis.tickfont.size = axisFontSize;
  }
  if (exportLayout.polar) {
    exportLayout.polar.domain = drilldownChartDomain(labelCount, showLegend);
  }
  const ticktext = exportLayout.polar?.angularaxis?.ticktext || [];
  exportLayout.margin = drilldownChartMargins(labelCount, showLegend, ticktext);
  if (exportLayout.legend) {
    exportLayout.legend.orientation = "h";
    exportLayout.legend.x = 0.5;
    exportLayout.legend.xanchor = "center";
    exportLayout.legend.y = -0.02;
    exportLayout.legend.yanchor = "top";
    exportLayout.legend.font = {
      family: chartFonts.family,
      size: 12,
      color: "#e2e8f0",
    };
    exportLayout.legend.bgcolor = "rgba(15, 23, 42, 0.85)";
    exportLayout.legend.bordercolor = "rgba(148, 163, 184, 0.2)";
  }
  return exportLayout;
}

function buildDrilldownSlideChartLayout(
  layout,
  labelCount = 5,
  panelWidth = 1240,
  panelHeight = 540,
) {
  const exportLayout = JSON.parse(JSON.stringify(layout));
  const axisFontSize = drilldownSlideChartLabelFontSize(labelCount);
  const narrow = panelWidth < 560;

  applyDarkExportPlotlyTheme(exportLayout, { transparent: true });
  exportLayout.width = panelWidth;
  exportLayout.height = panelHeight;
  exportLayout.autosize = false;
  exportLayout.showlegend = false;

  if (exportLayout.font?.size) {
    exportLayout.font.size = axisFontSize;
  }
  if (exportLayout.polar?.angularaxis?.tickfont) {
    exportLayout.polar.angularaxis.tickfont.size = narrow
      ? Math.max(axisFontSize - 1, 17)
      : axisFontSize + 1;
    exportLayout.polar.angularaxis.tickfont.color = "#e2e8f0";
  }
  if (exportLayout.polar?.angularaxis) {
    exportLayout.polar.angularaxis.ticklabelstep = 1;
    exportLayout.polar.angularaxis.showticklabels = true;
  }
  if (exportLayout.polar) {
    exportLayout.polar.domain = { x: [0.02, 0.98], y: [0.02, 0.98] };
  }
  const ticktext = exportLayout.polar?.angularaxis?.ticktext || [];
  exportLayout.margin = drilldownSlideChartMargins(labelCount, ticktext, panelWidth);
  delete exportLayout.legend;
  return exportLayout;
}

function slideExportRadarLabels(snapshot) {
  const fromCustom = radarExportRawLabels(snapshot);
  if (fromCustom.length) {
    return fromCustom;
  }
  const angular = snapshot.layout?.polar?.angularaxis || {};
  const ticktext = angular.ticktext || [];
  if (ticktext.length) {
    return ticktext.map((label) =>
      String(label || "")
        .replace(/<br\s*\/?>/gi, " ")
        .trim(),
    );
  }
  return [];
}

async function capturePlotPng(
  elementId,
  {
    width,
    height,
    compact = false,
    slideDeck = false,
    drilldownCard = false,
    drilldownSlide = false,
    mainRadarSlide = false,
    preserveUiLayout = false,
    exportScale,
  } = {},
) {
  const task = plotlyCaptureQueue.then(() =>
    capturePlotPngCore(elementId, {
      width,
      height,
      compact,
      slideDeck,
      drilldownCard,
      drilldownSlide,
      mainRadarSlide,
      preserveUiLayout,
      exportScale,
    }),
  );
  plotlyCaptureQueue = task.catch(() => {});
  return task;
}

async function capturePlotPngCore(
  elementId,
  {
    width,
    height,
    compact = false,
    slideDeck = false,
    drilldownCard = false,
    drilldownSlide = false,
    mainRadarSlide = false,
    preserveUiLayout = false,
    exportScale,
  } = {},
) {
  const el = document.getElementById(elementId);
  if (!el?.data) {
    return null;
  }

  const snapshot = {
    data: JSON.parse(JSON.stringify(el.data)),
    layout: JSON.parse(JSON.stringify(el.layout)),
  };

  const labelCount = drilldownChartLabelCount(snapshot.layout, snapshot.data);
  const rawRadarLabels = slideExportRadarLabels(snapshot);
  let exportLabelCount = labelCount;

  if (!drilldownSlide && !drilldownCard) {
    exportLabelCount = applyWrappedExportLabels(snapshot);
  }

  let exportLayout;
  let exportWidth;
  let exportHeight;

  if (slideDeck) {
    snapshot.data.forEach((trace) => {
      if (trace.textfont) {
        trace.textfont.size = compact ? 15 : 14;
        trace.textfont.color = "#0f172a";
      }
      if (trace.marker?.line) {
        trace.marker.line.width = 1.25;
      }
    });
    exportLayout = { ...snapshot.layout, ...buildSlideDeckExportLayout(compact) };
    exportWidth = width || 1920;
    exportHeight = height || 1080;
  } else if (drilldownSlide) {
    if (rawRadarLabels.length) {
      applyWrappedPolarAxis(snapshot, rawRadarLabels, labelCount, slideWrappedAxisLabel);
    } else {
      applyWrappedExportLabels(snapshot);
    }
    boostExportRadarTraces(snapshot);
    exportLayout = buildDrilldownSlideChartLayout(
      snapshot.layout,
      labelCount,
      width || 1240,
      height || 540,
    );
    exportWidth = width || exportLayout.width;
    exportHeight = height || exportLayout.height;
  } else if (drilldownCard) {
    const cardLabelCount =
      exportLabelCount || drilldownChartLabelCount(snapshot.layout, snapshot.data);
    if (preserveUiLayout) {
      exportLayout = applyDarkExportPlotlyTheme(JSON.parse(JSON.stringify(snapshot.layout)));
      exportLayout.autosize = false;
      exportLayout.showlegend = false;
      delete exportLayout.legend;
      if (width) {
        exportLayout.width = width;
      }
      if (height) {
        exportLayout.height = height;
      }
      exportWidth = width || exportLayout.width || 1200;
      exportHeight = height || exportLayout.height || 360;
    } else {
      exportLayout = buildDrilldownCardChartLayout(snapshot.layout, cardLabelCount);
      if (width) {
        exportLayout.width = width;
      }
      if (height) {
        exportLayout.height = height;
      }
      exportWidth = width || exportLayout.width;
      exportHeight = height || exportLayout.height;
    }
  } else if (mainRadarSlide) {
    const labelCount = exportLabelCount || drilldownChartLabelCount(snapshot.layout, snapshot.data);
    if (rawRadarLabels.length) {
      applyWrappedPolarAxis(snapshot, rawRadarLabels, labelCount, slideWrappedAxisLabel);
    } else {
      applyWrappedExportLabels(snapshot);
    }
    boostExportRadarTraces(snapshot);
    exportLayout = buildMainRadarSlideChartLayout(snapshot.layout, labelCount);
    exportWidth = width || 1120;
    exportHeight = height || 540;
  } else {
    const dimensions = chartExportDimensions(el, compact);
    exportLayout = buildAppExportLayout(snapshot.layout);
    exportWidth = width || dimensions.width;
    exportHeight = height || dimensions.height;
  }

  await Plotly.react(el, snapshot.data, exportLayout);

  let png;
  try {
    const plotScale =
      exportScale ??
      (drilldownSlide || drilldownCard ? DRILLDOWN_CARD_EXPORT.imageScale : 2);
    png = await Plotly.toImage(el, {
      format: "png",
      width: exportWidth,
      height: exportHeight,
      scale: plotScale,
    });
  } catch (error) {
    await Plotly.react(el, snapshot.data, snapshot.layout);
    throw error;
  }

  await Plotly.react(el, snapshot.data, snapshot.layout);
  return png;
}

function chartImageSlug(text) {
  return String(text || "chart")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function chartImageFileName(slug) {
  const data = state.lastChartData;
  const players =
    (data?.players || []).map((entry) => entry.player).join(" vs ") || data?.player || "player";
  const playerSlug = chartImageSlug(players);
  const date = new Date().toISOString().slice(0, 10);
  return `impect-${playerSlug}-${slug}-${date}.png`;
}

// "Save bars" ships the on-screen factor list as-is. The card is already sized
// for reading, so the export only needs a fixed capture width.
function prepareBarsExportClone(source) {
  const clone = source.cloneNode(true);
  clone.classList.add("factor-list--export");
  return clone;
}

function buildExportCaptureSurface(source, title = "") {
  const surface = document.createElement("div");
  surface.className = "export-capture-surface export-capture-surface-app";

  if (title) {
    const heading = document.createElement("h3");
    heading.className = "export-capture-title";
    heading.textContent = title;
    surface.appendChild(heading);
  }

  surface.appendChild(prepareBarsExportClone(source));
  return surface;
}

async function measureDataUrlImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const probe = new Image();
    probe.onload = () =>
      resolve({ width: probe.naturalWidth, height: probe.naturalHeight });
    probe.onerror = () => reject(new Error("Could not read chart image."));
    probe.src = dataUrl;
  });
}

function fitImageDimensions(naturalWidth, naturalHeight, maxWidth, maxHeight) {
  const scale = Math.min(maxWidth / naturalWidth, maxHeight / naturalHeight, 1);
  return {
    width: Math.max(1, Math.round(naturalWidth * scale)),
    height: Math.max(1, Math.round(naturalHeight * scale)),
  };
}

// html2canvas ignores object-fit and stretches images to their box, which
// squashes every radar. Give marked images explicit letterboxed pixel sizes.
function fitExportImagesToParents(surface) {
  surface.querySelectorAll("img[data-fit-parent]").forEach((image) => {
    const parent = image.parentElement;
    if (!parent || !image.naturalWidth || !image.naturalHeight) {
      return;
    }
    const style = window.getComputedStyle(parent);
    const maxWidth =
      parent.clientWidth -
      (parseFloat(style.paddingLeft) || 0) -
      (parseFloat(style.paddingRight) || 0);
    const maxHeight =
      parent.clientHeight -
      (parseFloat(style.paddingTop) || 0) -
      (parseFloat(style.paddingBottom) || 0);
    if (maxWidth <= 0 || maxHeight <= 0) {
      return;
    }
    const scale = Math.min(maxWidth / image.naturalWidth, maxHeight / image.naturalHeight);
    image.style.width = `${Math.round(image.naturalWidth * scale)}px`;
    image.style.height = `${Math.round(image.naturalHeight * scale)}px`;
    image.style.maxWidth = "none";
    image.style.maxHeight = "none";
  });
}

function applyFittedImageSize(image, fitted) {
  image.width = fitted.width;
  image.height = fitted.height;
  image.style.width = `${fitted.width}px`;
  image.style.height = `${fitted.height}px`;
  image.style.maxWidth = "100%";
  image.style.maxHeight = "100%";
  image.style.display = "block";
  image.style.margin = "0 auto";
}

async function renderExportSurfaceToPng(
  surface,
  {
    scale = DRILLDOWN_CARD_EXPORT.imageScale,
    imageFormat = "png",
    jpegQuality = 0.92,
  } = {},
) {
  if (typeof html2canvas !== "function") {
    throw new Error("Image capture is unavailable — reload the page and try again.");
  }

  const host = document.createElement("div");
  host.className = "export-capture-host";
  host.appendChild(surface);
  document.body.appendChild(host);

  try {
    await waitForExportImages(surface);

    // Off-screen flex layouts need an explicit layout pass before html2canvas measures them.
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    fitExportImagesToParents(surface);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const captureWidth = Math.round(surface.scrollWidth || surface.offsetWidth);
    const captureHeight = Math.round(surface.scrollHeight || surface.offsetHeight);

    const canvas = await html2canvas(surface, {
      backgroundColor: APP_EXPORT_BG,
      scale,
      useCORS: true,
      logging: false,
      foreignObjectRendering: false,
      width: captureWidth,
      height: captureHeight,
      windowWidth: captureWidth,
      windowHeight: captureHeight,
    });
    if (imageFormat === "jpeg") {
      return canvas.toDataURL("image/jpeg", jpegQuality);
    }
    return canvas.toDataURL("image/png");
  } finally {
    document.body.removeChild(host);
  }
}

async function captureDrilldownSlidePng({
  chartId,
  barsId,
  title = "",
  exportScale = DRILLDOWN_CARD_EXPORT.imageScale,
}) {
  // Bars are drawn from the payload rather than cloned from the DOM, so only the
  // chart element and the drilldown entry need to exist.
  const drilldownIndex = drilldownIndexFromExportIds({ chartId, barsId });
  const entry = state.lastChartData?.profile_drilldowns?.[drilldownIndex];
  if (!entry) {
    throw new Error("Profile breakdown data is not ready yet.");
  }

  const chartPng = await capturePlotPng(chartId, {
    compact: true,
    drilldownSlide: true,
    width: 1280,
    height: 800,
    exportScale: 2,
  });
  if (!chartPng) {
    throw new Error("Chart is not ready yet.");
  }

  const data = state.lastChartData;
  const players = enrichDrilldownPlayers(
    entry.players?.length ? entry.players : drilldownExportPlayers(entry),
    data?.players || [],
  );
  const profileIndex = (data?.labels || []).indexOf(entry.profile);

  const slide = document.createElement("div");
  slide.className = "keynote-slide keynote-drilldown";

  const head = document.createElement("header");
  head.className = "keynote-drilldown__head";

  const headText = document.createElement("div");
  headText.className = "keynote-drilldown__head-text";
  const eyebrow = document.createElement("p");
  eyebrow.className = "keynote-drilldown__eyebrow";
  eyebrow.textContent = "Profile breakdown";
  headText.appendChild(eyebrow);
  const heading = document.createElement("h2");
  heading.className = "keynote-drilldown__title";
  heading.textContent = profileDisplayTitle(title || entry.profile || "Profile");
  headText.appendChild(heading);

  const barCount = (entry.bar_labels || entry.labels || []).length;
  const radarCount = (entry.labels || []).length;
  const sub = document.createElement("p");
  sub.className = "keynote-drilldown__sub";
  sub.textContent =
    radarCount > barCount
      ? `The ${barCount} factors that weigh heaviest in this profile — the radar shows all ${radarCount}`
      : "Every factor that feeds this profile";
  headText.appendChild(sub);
  head.appendChild(headText);

  // Tie each drilldown back to the headline score on the front page.
  if (profileIndex >= 0) {
    const scores = document.createElement("div");
    scores.className = "keynote-drilldown__scores";
    players.slice(0, 4).forEach((player, index) => {
      const chartPlayer = (data?.players || [])[index];
      const value = Number(chartPlayer?.radar_values?.[profileIndex]);
      if (!Number.isFinite(value)) {
        return;
      }
      const chip = document.createElement("div");
      chip.className = `keynote-drilldown__score ${keynoteBandClass(value)}`;
      chip.innerHTML = `
        <span class="keynote-drilldown__score-name">${player.player || ""}</span>
        <span class="keynote-drilldown__score-value">${Math.round(value)}</span>
        <span class="keynote-drilldown__score-band">${keynoteBandLabel(value)}</span>
      `;
      scores.appendChild(chip);
    });
    if (scores.childElementCount) {
      head.appendChild(scores);
    }
  }
  head.appendChild(buildKeynoteCrest());
  slide.appendChild(head);

  const body = document.createElement("div");
  body.className = "keynote-drilldown__body";

  const radarCol = document.createElement("div");
  radarCol.className = "keynote-drilldown__radar";

  const chartWrap = document.createElement("div");
  chartWrap.className = "keynote-drilldown__chart-wrap";
  const chartImage = document.createElement("img");
  chartImage.className = "keynote-drilldown__chart-img";
  chartImage.dataset.fitParent = "true";
  chartImage.src = chartPng;
  chartImage.alt = title || "Profile chart";
  chartWrap.appendChild(chartImage);
  radarCol.appendChild(chartWrap);

  if (players.length > 0) {
    const playersRow = document.createElement("div");
    playersRow.className = "keynote-drilldown__players";
    playersRow.dataset.count = String(Math.min(players.length, 4));
    players.slice(0, 4).forEach((player, index) => {
      const color = seasonColors[index % seasonColors.length];
      const cell = document.createElement("div");
      cell.className = "keynote-drilldown__player";
      cell.style.setProperty("--player-color", color);
      cell.appendChild(
        buildKeynotePhoto(player, { color, className: "keynote-drilldown__photo" }),
      );

      const identity = document.createElement("div");
      identity.className = "keynote-drilldown__player-identity";
      const name = document.createElement("p");
      name.className = "keynote-drilldown__player-name";
      name.textContent = player.player || "";
      identity.appendChild(name);
      const minutes = keynoteMinutesLabel(player);
      if (minutes) {
        const minutesEl = document.createElement("p");
        minutesEl.className = "keynote-drilldown__player-meta";
        minutesEl.textContent = minutes;
        identity.appendChild(minutesEl);
      }
      cell.appendChild(identity);
      playersRow.appendChild(cell);
    });
    radarCol.appendChild(playersRow);
  }
  body.appendChild(radarCol);

  const barsCol = document.createElement("div");
  barsCol.className = "keynote-drilldown__bars";
  barsCol.appendChild(buildKeynoteFactorBars(entry, players));
  body.appendChild(barsCol);

  slide.appendChild(body);

  const footer = document.createElement("footer");
  footer.className = "keynote-drilldown__footer";
  footer.appendChild(buildKeynoteFootnote(data));
  slide.appendChild(footer);

  const surface = document.createElement("div");
  surface.className = "export-capture-surface export-capture-surface-app";
  surface.appendChild(slide);
  return renderExportSurfaceToPng(surface, {
    scale: exportScale,
    imageFormat: DECK_EXPORT.imageFormat,
    jpegQuality: DECK_EXPORT.jpegQuality,
  });
}

// Percentile bands shared by every deck slide, matching percentileBarColors().
function keynoteBandClass(value) {
  return `keynote-band--${percentileBandKey(value)}`;
}

function buildKeynoteFactorBars(entry, players) {
  const grid = document.createElement("div");
  grid.className = "keynote-factors";

  const labels = entry.bar_labels || entry.labels || [];
  const weights = entry.bar_weights || [];
  const multiPlayer = players.length > 1;
  grid.dataset.factors = String(labels.length);
  // Slide height is fixed, so the bars have to shrink as players are added.
  grid.dataset.players = String(Math.min(players.length, 4));

  labels.forEach((label, factorIndex) => {
    const factor = document.createElement("div");
    factor.className = "keynote-factor";

    const factorHead = document.createElement("div");
    factorHead.className = "keynote-factor__head";
    const name = document.createElement("p");
    name.className = "keynote-factor__name";
    name.textContent = humanizeFootballLabel(label);
    factorHead.appendChild(name);
    if (weights[factorIndex] != null) {
      const weight = document.createElement("span");
      weight.className = "keynote-factor__weight";
      weight.textContent = `${Math.round(weights[factorIndex])}% of profile`;
      factorHead.appendChild(weight);
    }
    factor.appendChild(factorHead);

    const averagePercentile = multiPlayer
      ? averagePercentileForFactor(players, factorIndex, "bar_radar_values")
      : null;

    const rows = document.createElement("div");
    rows.className = "keynote-factor__rows";
    players.forEach((player, playerIndex) => {
      const resolved = resolveBarScores(
        player.bar_radar_values?.[factorIndex],
        player.bar_raw_values?.[factorIndex],
      );
      const percentile = barTrackPercentile(resolved.percentile, resolved.rawValue);
      const row = document.createElement("div");
      row.className = `keynote-factor__row ${keynoteBandClass(percentile)}`;

      if (multiPlayer) {
        const initial = document.createElement("span");
        initial.className = "keynote-factor__initial";
        initial.style.background = seasonColors[playerIndex % seasonColors.length];
        initial.textContent = playerInitials(player.player || "");
        row.appendChild(initial);
      }

      const track = document.createElement("div");
      track.className = "keynote-factor__track";
      if (percentile != null && Number.isFinite(Number(percentile))) {
        const fill = document.createElement("span");
        fill.className = "keynote-factor__fill";
        fill.style.width = `${Math.max(2, Math.min(100, Number(percentile)))}%`;
        track.appendChild(fill);
      }
      // Same marker as the on-screen card: where these players average out.
      if (averagePercentile != null && Number.isFinite(Number(averagePercentile))) {
        const marker = document.createElement("span");
        marker.className = "keynote-factor__avg";
        marker.style.left = `${Math.min(Math.max(Number(averagePercentile), 0), 100)}%`;
        track.appendChild(marker);
      }
      row.appendChild(track);

      const value = document.createElement("span");
      value.className = "keynote-factor__value";
      value.textContent = formatBarInnerValue(resolved.percentile, resolved.rawValue).replace(
        "%",
        "",
      );
      row.appendChild(value);

      rows.appendChild(row);
    });
    factor.appendChild(rows);
    grid.appendChild(factor);
  });

  return grid;
}

// Impect sends profile names in mixed case ("PV DEEP CREATOR", "PV Defensive").
function keynoteMinutesLabel(player) {
  const minutes = Math.round(
    Number(player?.minutes ?? player?.play_duration_minutes) || 0,
  );
  return minutes > 0 ? `${minutes.toLocaleString()} min` : "";
}

function buildKeynotePhoto(source, { color, round = false, className }) {
  const photo = document.createElement("div");
  photo.className = className;
  if (round) {
    photo.classList.add(`${className}--round`);
  }
  if (color) {
    photo.style.borderColor = color;
  }
  const photoUrl = source?.photo_url || source?.photoUrl || null;
  if (photoUrl) {
    const image = document.createElement("img");
    image.src = photoUrl;
    image.alt = source?.name || source?.player || "Player";
    image.loading = "eager";
    image.decoding = "sync";
    photo.appendChild(image);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = `${className}-placeholder`;
    placeholder.textContent = playerInitials(source?.name || source?.player || "");
    photo.appendChild(placeholder);
  }
  return photo;
}

function buildKeynoteBar(value, { leader = false } = {}) {
  const bar = document.createElement("div");
  bar.className = `keynote-bar ${keynoteBandClass(value)}`;
  if (leader) {
    bar.classList.add("keynote-bar--leader");
  }

  if (value != null && Number.isFinite(Number(value))) {
    const fill = document.createElement("span");
    fill.className = "keynote-bar__fill";
    fill.style.width = `${Math.max(2, Math.min(100, Number(value)))}%`;
    bar.appendChild(fill);
  }

  const valueEl = document.createElement("span");
  valueEl.className = "keynote-bar__value";
  if (leader) {
    const star = document.createElement("span");
    star.className = "keynote-bar__star";
    star.textContent = "★";
    valueEl.appendChild(star);
  }
  const number = document.createElement("span");
  number.className = "keynote-bar__number";
  number.textContent =
    value == null || !Number.isFinite(Number(value)) ? "—" : `${Math.round(Number(value))}`;
  valueEl.appendChild(number);
  bar.appendChild(valueEl);

  return bar;
}

function buildKeynoteFootnote(data, extra = "") {
  const benchmark = data?.benchmark;
  const parts = [];
  if (benchmark?.cohort_size) {
    parts.push(`Percentile rank vs ${benchmark.cohort_size} players at this position`);
    const competitions = (benchmark.competitions || []).join(", ");
    if (competitions) {
      parts.push(competitions);
    }
    parts.push(`${benchmark.min_minutes || 600}+ minutes`);
  } else {
    parts.push("Position-specific profiles · one selected season per player");
  }
  if (extra) {
    parts.push(extra);
  }
  const note = document.createElement("p");
  note.className = "keynote-footnote";
  note.textContent = parts.join("  ·  ");
  return note;
}

function buildKeynoteCrest() {
  const crest = document.createElement("img");
  crest.className = "keynote-crest";
  crest.src = "/standalone/port-vale-badge.png?v=2";
  crest.alt = "Port Vale";
  crest.loading = "eager";
  crest.decoding = "sync";
  return crest;
}

function buildKeynoteComparisonSlide(data) {
  const players = studioComparisonPlayersFromChart(data);
  const profiles = (data.labels || []).map((label) => ({
    apiName: label,
    label: profileDisplayTitle(label),
  }));
  if (!players.length || profiles.length < 2) {
    throw new Error("Comparison front page is not ready yet.");
  }

  const positionEntry =
    state.studioPositionOptions.find(
      (item) => item.position === state.comparedPlayers[0]?.position,
    ) || {};
  const positionLabel = positionEntry.label || players[0]?.position_label || "Player";
  const positionShort = positionEntry.shortLabel || positionAbbrev(state.comparedPlayers[0]?.position) || "POS";
  const reference = data.port_vale_reference || null;
  const referenceScores = studioReferenceProfileScores(
    reference,
    profiles.map((item) => item.apiName),
  );

  // Deck colours follow the radar traces (seasonColors) so a player keeps the
  // same colour on every slide. The reference column stays silver to avoid
  // clashing with the first player's gold.
  const columns = players.map((player, index) => ({
    kind: "player",
    name: player.name,
    photo_url: player.photo_url,
    color: seasonColors[index % seasonColors.length],
    // season_label already carries the league, so the club line must not repeat it.
    meta: player.club || player.league || "",
    season: player.season_label || player.league || "",
    minutes: keynoteMinutesLabel(player),
    tag: "",
    scores: profiles.map((profile) => player.profileScores?.[profile.apiName] ?? null),
  }));

  if (reference?.player) {
    columns.push({
      kind: "reference",
      name: reference.player,
      photo_url: reference.photo_url,
      color: "#e2e8f0",
      meta: reference.club || "Port Vale FC",
      season: reference.season_label || "",
      minutes: keynoteMinutesLabel(reference),
      tag: `Our most-used ${positionShort}`,
      scores: profiles.map((profile) => referenceScores[profile.apiName] ?? null),
    });
  }

  const slide = document.createElement("div");
  slide.className = "keynote-slide keynote-comparison";
  slide.style.setProperty("--player-cols", String(columns.length));
  slide.style.setProperty("--profile-rows", String(profiles.length));
  slide.dataset.players = String(columns.length);
  slide.dataset.profiles = String(profiles.length);

  const head = document.createElement("header");
  head.className = "keynote-comparison__head";
  head.innerHTML = `
    <div class="keynote-comparison__titles">
      <p class="keynote-comparison__eyebrow">Port Vale recruitment · player comparison</p>
      <h1 class="keynote-comparison__title">${String(positionLabel).toUpperCase()}</h1>
      <p class="keynote-comparison__sub">Higher bar is better — every score is a percentile rank against the same benchmark</p>
    </div>
  `;
  const brand = document.createElement("div");
  brand.className = "keynote-comparison__brand";
  brand.appendChild(buildKeynoteCrest());
  const badge = document.createElement("span");
  badge.className = "keynote-comparison__badge";
  badge.textContent = positionShort;
  brand.appendChild(badge);
  head.appendChild(brand);
  slide.appendChild(head);

  const table = document.createElement("div");
  table.className = "keynote-comparison__table";

  // The cell above the profile names used to be blank. The colour key reads
  // better there than buried in the footer.
  const corner = document.createElement("div");
  corner.className = "keynote-comparison__corner";
  corner.appendChild(buildKeynoteScaleKey());
  table.appendChild(corner);

  columns.forEach((column, index) => {
    const cell = document.createElement("div");
    cell.className = `keynote-comparison__player keynote-comparison__player--${column.kind}`;
    cell.style.gridColumn = String(index + 2);
    cell.style.setProperty("--player-color", column.color);

    cell.appendChild(
      buildKeynotePhoto(column, {
        color: column.color,
        className: "keynote-comparison__photo",
      }),
    );

    const name = document.createElement("p");
    name.className = "keynote-comparison__name";
    name.textContent = column.name;
    cell.appendChild(name);

    if (column.meta) {
      const meta = document.createElement("p");
      meta.className = "keynote-comparison__meta";
      meta.textContent = column.meta;
      cell.appendChild(meta);
    }

    const seasonLine = [column.season, column.minutes].filter(Boolean).join("  ·  ");
    if (seasonLine) {
      const minutes = document.createElement("p");
      minutes.className = "keynote-comparison__minutes";
      minutes.textContent = seasonLine;
      cell.appendChild(minutes);
    }

    // Every column gets the tag slot, even when empty. Columns are bottom
    // aligned, so an extra line on one of them lifted its photo out of line.
    const tag = document.createElement("p");
    tag.className = "keynote-comparison__tag";
    tag.textContent = column.tag || "\u00a0";
    cell.appendChild(tag);

    table.appendChild(cell);
  });

  profiles.forEach((profile, profileIndex) => {
    const row = document.createElement("div");
    row.className = "keynote-comparison__row";

    const rowValues = columns.map((column) => column.scores[profileIndex]);
    const numericValues = rowValues.filter(
      (value) => value != null && Number.isFinite(Number(value)),
    );
    // Best of everyone on show, including our own player — that is the
    // comparison a manager actually reads off this slide.
    const leaderValue = numericValues.length > 1 ? Math.max(...numericValues.map(Number)) : null;

    const label = document.createElement("div");
    label.className = "keynote-comparison__label";
    const labelMain = document.createElement("p");
    labelMain.className = "keynote-comparison__label-main";
    labelMain.textContent = profile.label;
    label.appendChild(labelMain);
    row.appendChild(label);

    rowValues.forEach((value) => {
      row.appendChild(
        buildKeynoteBar(value, {
          leader: leaderValue != null && Number(value) === leaderValue,
        }),
      );
    });

    table.appendChild(row);
  });

  slide.appendChild(table);

  const footer = document.createElement("footer");
  footer.className = "keynote-comparison__footer";
  footer.appendChild(buildKeynoteFootnote(data, "★ = best on this slide"));
  slide.appendChild(footer);

  return slide;
}

function buildKeynoteScaleKey() {
  const scale = document.createElement("div");
  scale.className = "keynote-scale";

  const heading = document.createElement("p");
  heading.className = "keynote-scale__heading";
  heading.textContent = "Percentile rank";
  scale.appendChild(heading);

  PERCENTILE_SCALE_STEPS.slice()
    .reverse()
    .forEach((step) => {
      const item = document.createElement("span");
      item.className = `keynote-scale__item keynote-band--${step.key}`;
      item.innerHTML = `<span class="keynote-scale__swatch"></span>${step.label}`;
      scale.appendChild(item);
    });

  return scale;
}

async function captureComparisonFrontSlidePng({ exportScale = 1 } = {}) {
  const data = state.lastChartData;
  if (!data) {
    throw new Error("Comparison front page is not ready yet.");
  }

  const slide = buildKeynoteComparisonSlide(data);
  const surface = document.createElement("div");
  surface.className = "export-capture-surface export-capture-surface-app";
  surface.appendChild(slide);
  return renderExportSurfaceToPng(surface, {
    scale: exportScale,
    imageFormat: DECK_EXPORT.imageFormat,
    jpegQuality: DECK_EXPORT.jpegQuality,
  });
}

// Best / worst profile for a radar player, used for the read-out cards.
function keynoteProfileExtremes(player, labels) {
  const scored = (labels || [])
    .map((label, index) => ({
      label: profileDisplayTitle(label),
      value: Number(player?.radar_values?.[index]),
    }))
    .filter((entry) => Number.isFinite(entry.value));
  if (scored.length < 2) {
    return null;
  }
  const sorted = [...scored].sort((a, b) => b.value - a.value);
  return { best: sorted[0], worst: sorted[sorted.length - 1] };
}

function buildKeynoteRadarPlayerCard(player, index, labels) {
  const color = seasonColors[index % seasonColors.length];
  const card = document.createElement("div");
  card.className = "keynote-radar__card";
  card.style.setProperty("--player-color", color);

  const top = document.createElement("div");
  top.className = "keynote-radar__card-top";
  top.appendChild(
    buildKeynotePhoto(player, { color, className: "keynote-radar__card-photo" }),
  );

  const identity = document.createElement("div");
  identity.className = "keynote-radar__card-identity";
  const name = document.createElement("p");
  name.className = "keynote-radar__card-name";
  name.textContent = player.player || "Player";
  identity.appendChild(name);
  const meta = [player.season_label, keynoteMinutesLabel(player)].filter(Boolean).join("  ·  ");
  if (meta) {
    const metaEl = document.createElement("p");
    metaEl.className = "keynote-radar__card-meta";
    metaEl.textContent = meta;
    identity.appendChild(metaEl);
  }
  top.appendChild(identity);
  card.appendChild(top);

  const extremes = keynoteProfileExtremes(player, labels);
  if (extremes) {
    const reads = document.createElement("div");
    reads.className = "keynote-radar__reads";
    [
      ["Best", extremes.best],
      ["Weakest", extremes.worst],
    ].forEach(([caption, entry]) => {
      const read = document.createElement("div");
      read.className = `keynote-radar__read ${keynoteBandClass(entry.value)}`;
      read.innerHTML = `
        <span class="keynote-radar__read-caption">${caption}</span>
        <span class="keynote-radar__read-label">${entry.label}</span>
        <span class="keynote-radar__read-value">${Math.round(entry.value)}</span>
      `;
      reads.appendChild(read);
    });
    card.appendChild(reads);
  }

  return card;
}

async function captureMainRadarSlidePng({ exportScale = DRILLDOWN_CARD_EXPORT.imageScale } = {}) {
  const chartPng = await capturePlotPng("radarChart", {
    width: 1200,
    height: 840,
    compact: true,
    mainRadarSlide: true,
    exportScale: 2,
  });
  if (!chartPng) {
    throw new Error("Main radar chart is not ready yet.");
  }

  const data = state.lastChartData;
  const players = getComparedPlayersFromChartData(data);
  const labels = data?.labels || [];

  const slide = document.createElement("div");
  slide.className = "keynote-slide keynote-radar";

  const head = document.createElement("header");
  head.className = "keynote-radar__head";
  head.innerHTML = `
    <div>
      <p class="keynote-radar__eyebrow">Profile shape</p>
      <h2 class="keynote-radar__title">${
        players.length > 1 ? "Where each player is strongest" : "Profile shape at a glance"
      }</h2>
      <p class="keynote-radar__sub">The further the shape reaches, the higher the percentile on that profile</p>
    </div>
  `;
  head.appendChild(buildKeynoteCrest());
  slide.appendChild(head);

  const body = document.createElement("div");
  body.className = "keynote-radar__body";

  const chartPanel = document.createElement("div");
  chartPanel.className = "keynote-radar__chart";
  const chartImage = document.createElement("img");
  chartImage.className = "export-main-radar-chart";
  chartImage.dataset.fitParent = "true";
  chartImage.src = chartPng;
  chartImage.alt = "Profile radar";
  chartPanel.appendChild(chartImage);
  body.appendChild(chartPanel);

  const side = document.createElement("div");
  side.className = "keynote-radar__side";
  side.dataset.cards = String(players.length);
  players.slice(0, 4).forEach((player, index) => {
    side.appendChild(buildKeynoteRadarPlayerCard(player, index, labels));
  });
  body.appendChild(side);
  slide.appendChild(body);

  const footer = document.createElement("footer");
  footer.className = "keynote-radar__footer";
  footer.appendChild(buildKeynoteFootnote(data));
  slide.appendChild(footer);

  const surface = document.createElement("div");
  surface.className = "export-capture-surface export-capture-surface-app";
  surface.appendChild(slide);
  return renderExportSurfaceToPng(surface, {
    scale: exportScale,
    imageFormat: DECK_EXPORT.imageFormat,
    jpegQuality: DECK_EXPORT.jpegQuality,
  });
}

async function downloadDrilldownCardImage({ chartId, barsId, slug, title = "" }) {
  const filename = chartImageFileName(slug);
  setStatus(`Saving ${filename}…`);

  const png = await captureDrilldownSlidePng({ chartId, barsId, title });
  const response = await fetch(png);
  const blob = await response.blob();
  downloadBlob(blob, filename);
  setStatus(`Saved ${filename}`);
}

async function downloadPanelImage(elementId, slug, { title = "" } = {}) {
  const source = document.getElementById(elementId);
  if (!source) {
    throw new Error("Panel is not ready yet.");
  }
  if (typeof html2canvas !== "function") {
    throw new Error("Panel capture is unavailable — reload the page and try again.");
  }

  const filename = chartImageFileName(slug);
  setStatus(`Saving ${filename}…`);

  const host = document.createElement("div");
  host.className = "export-capture-host";
  host.appendChild(buildExportCaptureSurface(source, title));
  document.body.appendChild(host);

  try {
    const canvas = await html2canvas(host.firstElementChild, {
      backgroundColor: APP_EXPORT_BG,
      scale: 2,
      useCORS: true,
      logging: false,
    });
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob((result) => {
        if (result) {
          resolve(result);
          return;
        }
        reject(new Error("Could not create panel image."));
      }, "image/png");
    });
    downloadBlob(blob, filename);
    setStatus(`Saved ${filename}`);
  } finally {
    document.body.removeChild(host);
  }
}

async function downloadChartImage(
  elementId,
  slug,
  { compact = false, drilldownCard = false } = {},
) {
  const el = document.getElementById(elementId);
  if (!el?.data) {
    throw new Error("Chart is not ready yet.");
  }

  const filename = chartImageFileName(slug);
  setStatus(`Saving ${filename}…`);

  const png = await capturePlotPng(elementId, {
    compact,
    slideDeck: false,
    drilldownCard,
  });
  if (!png) {
    throw new Error("Could not capture chart image.");
  }

  const response = await fetch(png);
  const blob = await response.blob();
  downloadBlob(blob, filename);
  setStatus(`Saved ${filename}`);
}

function createChartExportButton({
  elementId,
  slug,
  compact = false,
  drilldownCard = false,
  label = "Save chart",
}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-ghost chart-export-btn";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await downloadChartImage(elementId, slug, { compact, drilldownCard });
      hideAlert();
    } catch (error) {
      showAlert(error.message || "Could not save chart image.");
      setStatus("Chart image export failed.");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function exportSectionKeyForProfile(profile) {
  return `profile:${String(profile || "").trim().toLowerCase()}`;
}

function isExcludedFromExport(exportKey) {
  return state.exportExcluded.has(exportKey);
}

function toggleExportExcluded(exportKey) {
  if (state.exportExcluded.has(exportKey)) {
    state.exportExcluded.delete(exportKey);
  } else {
    state.exportExcluded.add(exportKey);
  }
  invalidateWholeDeckCaptureCache();
}

function syncExportToggleButton(button, { exportKey, cardElement }) {
  const excluded = isExcludedFromExport(exportKey);
  button.textContent = excluded ? "Include in export" : "Remove from export";
  button.setAttribute("aria-pressed", excluded ? "true" : "false");
  button.title = excluded
    ? "This chart is skipped in Export PDF and Export slides"
    : "Exclude this chart from Export PDF and Export slides";
  if (cardElement) {
    cardElement.classList.toggle("chart-card--excluded-export", excluded);
  }
}

function createExportToggleButton({ exportKey, cardElement }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-ghost chart-export-btn chart-export-btn--toggle";
  button.dataset.exportKey = exportKey;
  syncExportToggleButton(button, { exportKey, cardElement });
  button.addEventListener("click", () => {
    toggleExportExcluded(exportKey);
    syncExportToggleButton(button, { exportKey, cardElement });
  });
  return button;
}

function mountStudioDeckExportToolbar(parentEl, { hint = "", extraActions = [] } = {}) {
  const toolbar = document.createElement("div");
  toolbar.className = "studio-export-toolbar";

  const text = document.createElement("div");
  text.className = "studio-export-toolbar__text";
  text.innerHTML = hint
    ? `<p class="chart-caption">${hint}</p>`
    : `<p class="chart-caption">Export PDF or slides — use <strong>Remove from export</strong> on any profile to skip it.</p>`;
  toolbar.appendChild(text);

  const actions = document.createElement("div");
  actions.className = "studio-export-toolbar__actions";
  extraActions.forEach((button) => actions.appendChild(button));

  const deckSlidesBtn = document.createElement("button");
  deckSlidesBtn.type = "button";
  deckSlidesBtn.className = "btn btn-ghost";
  deckSlidesBtn.textContent = "Export slides";
  deckSlidesBtn.addEventListener("click", exportWholeDeckToPptx);

  const deckPdfBtn = document.createElement("button");
  deckPdfBtn.type = "button";
  deckPdfBtn.className = "btn btn-ghost";
  deckPdfBtn.textContent = "Export PDF";
  deckPdfBtn.addEventListener("click", exportWholeDeckToPdf);

  actions.appendChild(deckSlidesBtn);
  actions.appendChild(deckPdfBtn);
  toolbar.appendChild(actions);
  parentEl.appendChild(toolbar);

  wholeDeckExportButtons = [deckPdfBtn, deckSlidesBtn];
  updateWholeDeckButtonState();
  return toolbar;
}

function initStaticExportToggleButtons() {
  const configs = [
    { button: exportRadarImageBtn, exportKey: "main-radar" },
    { button: exportPizzaImageBtn, exportKey: "pizza" },
  ];

  configs.forEach(({ button, exportKey }) => {
    if (!button) return;
    const card = button.closest(".chart-card");
    const head = button.closest(".chart-card-head");
    if (!head || head.querySelector(`[data-export-key="${exportKey}"]`)) return;

    let actions = button.parentElement;
    if (!actions.classList.contains("chart-card-actions")) {
      actions = document.createElement("div");
      actions.className = "chart-card-actions";
      head.appendChild(actions);
      actions.appendChild(button);
    }

    actions.insertBefore(
      createExportToggleButton({ exportKey, cardElement: card }),
      button,
    );
  });
}

function createSlideExportButton({ chartId, barsId, slug, title = "", label = "Save slide" }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-ghost chart-export-btn";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await downloadDrilldownCardImage({ chartId, barsId, slug, title });
      hideAlert();
    } catch (error) {
      showAlert(error.message || "Could not save slide image.");
      setStatus("Slide export failed.");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function createBarsExportButton({ barsId, slug, title = "", label = "Save bars" }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-ghost chart-export-btn";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await downloadPanelImage(barsId, slug, { title });
      hideAlert();
    } catch (error) {
      showAlert(error.message || "Could not save factor bars image.");
      setStatus("Factor bars export failed.");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

async function bindChartExportButton(button, { elementId, slug, compact = false }) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await downloadChartImage(elementId, slug, { compact });
      hideAlert();
    } catch (error) {
      showAlert(error.message || "Could not save chart image.");
      setStatus("Chart image export failed.");
    } finally {
      button.disabled = !state.lastChartData;
    }
  });
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function buildExportPayload(data, extension) {
  const sections = [];
  if (!isExcludedFromExport("main-radar")) {
    const radarImage = await capturePlotPng("radarChart", {
      width: 1920,
      height: 1080,
      slideDeck: true,
    });
    if (radarImage) {
      sections.push({ title: "Profile radar", image_data: radarImage });
    }
  }

  const drilldowns = data.profile_drilldowns || [];
  if (chartSourceEl.value === "profiles" && drilldowns.length > 0) {
    for (let index = 0; index < drilldowns.length; index += 1) {
      const entry = drilldowns[index];
      const exportKey = exportSectionKeyForProfile(entry.profile);
      if (isExcludedFromExport(exportKey)) {
        continue;
      }
      const profileTitle = humanizeProfileName(entry.profile);
      const radarImage = await capturePlotPng(`profileDrilldown-${index}`, {
        width: 1920,
        height: 1080,
        compact: true,
        slideDeck: true,
      });
      if (radarImage) {
        sections.push({ title: `${profileTitle} radar`, image_data: radarImage });
      }
      if (typeof html2canvas === "function") {
        const barsEl = document.getElementById(`profileDrilldownBars-${index}`);
        if (barsEl) {
          const host = document.createElement("div");
          host.className = "export-capture-host";
          host.appendChild(buildExportCaptureSurface(barsEl, profileTitle));
          document.body.appendChild(host);
          try {
            const canvas = await html2canvas(host.firstElementChild, {
              backgroundColor: APP_EXPORT_BG,
              scale: 2,
              useCORS: true,
              logging: false,
            });
            sections.push({
              title: `${profileTitle} bars`,
              image_data: canvas.toDataURL("image/png"),
            });
          } finally {
            document.body.removeChild(host);
          }
        }
      }
    }
  }

  if (!isExcludedFromExport("pizza")) {
    const pizzaImage = await capturePlotPng("pizzaChart", {
      width: 1920,
      height: 1080,
      slideDeck: true,
    });
    if (pizzaImage) {
      sections.push({ title: "Squad percentile pizza", image_data: pizzaImage });
    }
  }

  if (!sections.length) {
    throw new Error("No charts selected for export — include at least one chart.");
  }

  const players = data.players?.length
    ? data.players.map((entry) => ({
        player: entry.player,
        season_label: entry.season_label || "",
        position_label: entry.position_label || "",
      }))
    : [{ player: data.player, season_label: "", position_label: "" }];

  return {
    filename: exportFileName(data, extension),
    generated_at: new Date().toLocaleString(),
    players,
    benchmark_subtitle: formatBenchmarkSubtitle(data.benchmark),
    profiles:
      chartSourceEl.value === "profiles"
        ? getValidSelectedProfiles().map(humanizeProfileName)
        : [],
    warnings: data.warnings || [],
    sections,
    drilldowns:
      chartSourceEl.value === "profiles"
        ? drilldowns
            .filter((entry) => !isExcludedFromExport(exportSectionKeyForProfile(entry.profile)))
            .map((entry) => ({
            profile: entry.profile,
            labels: entry.labels || [],
            players: (entry.players || [
              {
                player: data.player,
                radar_values: entry.radar_values || [],
                raw_values: entry.raw_values || [],
              },
            ]).map((player) => ({
              player: player.player,
              radar_values: player.radar_values || [],
              raw_values: player.raw_values || [],
            })),
          }))
        : [],
  };
}

async function buildWholeExportPayload(data, extension) {
  const drilldowns = data.profile_drilldowns || [];
  const hasFront = Boolean(studioComparisonFrontEl?.querySelector(".comparison-frame--keynote"));
  const hasRadar = Boolean(document.getElementById("radarChart")?.data);
  if (
    chartSourceEl.value !== "profiles" ||
    (!hasFront && drilldowns.length === 0 && !hasRadar)
  ) {
    throw new Error("Generate profile charts first, then export the deck.");
  }
  if (typeof html2canvas !== "function") {
    throw new Error("Image capture is unavailable — reload the page and try again.");
  }

  const cacheKey = wholeDeckCaptureCacheKey(data);
  if (wholeDeckCaptureCache?.key === cacheKey) {
    setStatus("Using cached slides — building file…");
    return {
      ...wholeDeckCaptureCache.payload,
      generated_at: new Date().toLocaleString(),
      filename:
        extension === "pdf"
          ? exportDeckPdfFileName(data)
          : exportFileName(data, extension || "pptx", { deck: true }),
    };
  }

  const includedDrilldowns = drilldowns.filter(
    (entry) => !isExcludedFromExport(exportSectionKeyForProfile(entry.profile)),
  );
  const includeFront =
    hasFront && !isExcludedFromExport("comparison-front");
  const includeRadar = !isExcludedFromExport("main-radar");
  const slideTotal =
    (includeFront ? 1 : 0) + (includeRadar ? 1 : 0) + includedDrilldowns.length;
  if (slideTotal === 0) {
    throw new Error(
      "No slides selected — click Include in export on the comparison page, radar, or at least one profile.",
    );
  }

  const deckScale = DECK_EXPORT.imageScale;
  const captureJobs = [];

  if (includeFront) {
    captureJobs.push({
      title: "Profile comparison",
      capture: () => captureComparisonFrontSlidePng({ exportScale: deckScale }),
    });
  }
  if (includeRadar) {
    captureJobs.push({
      title: "Profile radar",
      capture: () => captureMainRadarSlidePng({ exportScale: deckScale }),
    });
  }
  for (let index = 0; index < drilldowns.length; index += 1) {
    const entry = drilldowns[index];
    const exportKey = exportSectionKeyForProfile(entry.profile);
    if (isExcludedFromExport(exportKey)) {
      continue;
    }
    const chartId = `profileDrilldown-${index}`;
    const barsId = `profileDrilldownBars-${index}`;
    const chartEl = document.getElementById(chartId);
    const barsEl = document.getElementById(barsId);
    if (!barsEl || !chartEl?.data) {
      continue;
    }
    const profileTitle = humanizeProfileName(entry.profile);
    captureJobs.push({
      title: profileTitle,
      capture: () =>
        captureDrilldownSlidePng({
          chartId,
          barsId,
          title: profileTitle,
          exportScale: deckScale,
        }),
    });
  }

  if (captureJobs.length === 0) {
    throw new Error(
      "No exportable slides found — include the comparison page or radar, or regenerate charts.",
    );
  }

  const capturedSections = [];
  for (let index = 0; index < captureJobs.length; index += 1) {
    const job = captureJobs[index];
    setStatus(`Capturing slide ${index + 1} of ${captureJobs.length}: ${job.title}…`);
    const image_data = await withTimeout(
      () => job.capture(),
      DECK_EXPORT.slideTimeoutMs,
      `Timed out capturing “${job.title}”. Try removing that slide from export, then export again.`,
      { onTimeout: resetPlotlyCaptureQueue },
    );
    capturedSections.push({ title: job.title, image_data });
  }

  const missingSlides = capturedSections.filter(
    (section) => !section?.image_data?.startsWith("data:image"),
  );
  if (missingSlides.length) {
    throw new Error(
      `Could not capture ${missingSlides.length} slide${missingSlides.length === 1 ? "" : "s"} — try refreshing charts, then export again.`,
    );
  }

  const players = data.players?.length
    ? data.players.map((entry) => ({
        player: entry.player,
        season_label: entry.season_label || "",
        position_label: entry.position_label || "",
      }))
    : [{ player: data.player, season_label: "", position_label: "" }];

  const payload = {
    filename:
      extension === "pdf"
        ? exportDeckPdfFileName(data)
        : exportFileName(data, extension || "pptx", { deck: true }),
    generated_at: new Date().toLocaleString(),
    players,
    benchmark_subtitle: formatBenchmarkSubtitle(data.benchmark),
    profiles: getValidSelectedProfiles().map(humanizeProfileName),
    warnings: data.warnings || [],
    sections: capturedSections,
    drilldowns: [],
    export_mode: "whole",
  };

  wholeDeckCaptureCache = {
    key: cacheKey,
    payload: {
      ...payload,
      filename: payload.filename,
    },
  };

  return payload;
}

async function exportWholeDeck(endpoint, extension, busyLabel, successLabel) {
  if (loadChartsInFlight) {
    showAlert("Charts are still loading — wait for comparison to finish, then export.");
    return;
  }
  if (!canExportWholeDeck()) {
    showAlert("Generate profile charts first, then export the deck.");
    return;
  }

  const data = state.lastChartData;
  resetPlotlyCaptureQueue();
  wholeDeckExportButtons.forEach((button) => {
    button.disabled = true;
  });
  setStatus(busyLabel);

  try {
    const payload = await buildWholeExportPayload(data, extension);
    setStatus(`${successLabel} file ready — assembling download…`);
    const res = await fetchWithTimeout(
      endpoint,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      EXPORT_FETCH_TIMEOUT_MS,
    );

    if (!res.ok) {
      let message = `${successLabel} failed.`;
      try {
        const error = await readJsonResponse(res);
        message = error.detail || message;
      } catch (parseError) {
        const text = (await res.text()).trim();
        if (text) {
          message = text;
        }
      }
      throw new Error(message);
    }

    const blob = await res.blob();
    if (extension === "pdf") {
      const pdfHeader = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
      const looksLikePdf =
        pdfHeader.length === 4 &&
        pdfHeader[0] === 0x25 &&
        pdfHeader[1] === 0x50 &&
        pdfHeader[2] === 0x44 &&
        pdfHeader[3] === 0x46;
      if (!looksLikePdf) {
        const text = (await blob.text()).trim();
        throw new Error(text || `${successLabel} file was invalid.`);
      }
    }
    const savedDesktopPath = res.headers.get("X-Saved-Desktop-Path");
    downloadBlob(blob, payload.filename);
    hideAlert();
    if (savedDesktopPath) {
      const savedName = savedDesktopPath.split("/").pop();
      setStatus(`${successLabel} saved to Desktop (${savedName}) and downloaded.`);
    } else {
      setStatus(`${successLabel} downloaded. Could not save a copy to Desktop.`);
    }
  } catch (error) {
    showAlert(error.message || `${successLabel} failed.`);
    setStatus(`${successLabel} failed.`);
  } finally {
    wholeDeckExportButtons.forEach((button) => {
      button.disabled = !canExportWholeDeck();
    });
    updateChartButtonState();
  }
}

function exportWholeDeckToPptx() {
  return exportWholeDeck("/api/export-pptx", "pptx", "Building slides…", "Slides");
}

function exportWholeDeckToPdf() {
  return exportWholeDeck("/api/export-pdf", "pdf", "Building PDF…", "PDF");
}

async function exportChartsFile(endpoint, extension, busyLabel, successLabel) {
  if (!state.lastChartData) {
    showAlert("Generate charts first, then export.");
    return;
  }

  const data = state.lastChartData;
  setStatus(busyLabel);

  try {
    const payload = await buildExportPayload(data, extension);
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      let message = `${successLabel} failed.`;
      try {
        const error = await readJsonResponse(res);
        message = error.detail || message;
      } catch (parseError) {
        const text = (await res.text()).trim();
        if (text) {
          message = text;
        }
      }
      throw new Error(message);
    }

    const blob = await res.blob();
    const savedDesktopPath = res.headers.get("X-Saved-Desktop-Path");
    downloadBlob(blob, payload.filename);
    hideAlert();
    if (savedDesktopPath) {
      const savedName = savedDesktopPath.split("/").pop();
      setStatus(`${successLabel} saved to Desktop (${savedName}) and downloaded.`);
    } else {
      setStatus(`${successLabel} downloaded. Could not save a copy to Desktop.`);
    }
  } catch (error) {
    showAlert(error.message || `${successLabel} failed.`);
    setStatus(`${successLabel} failed.`);
  } finally {
    updateChartButtonState();
  }
}

function exportChartsToPdf() {
  return exportChartsFile("/api/export-pdf", "pdf", "Building PDF…", "PDF");
}

function exportChartsToSlides() {
  return exportChartsFile("/api/export-pptx", "pptx", "Building slides…", "Slides");
}

function getSelectedPlayerFromDropdown() {
  const key = playerSelectEl.value;
  if (!key) {
    return null;
  }
  return state.players.find((player) => player.key === key) || state.selectedPlayer;
}

function fillSelect(selectEl, items, placeholder, valueKey = "id", labelKey = "name") {
  const previous = selectEl.value;
  selectEl.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = placeholder;
  selectEl.appendChild(defaultOption);

  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = String(item[valueKey]);
    option.textContent = String(item[labelKey] || item.name || item[valueKey]);
    selectEl.appendChild(option);
  });

  if (previous && items.some((item) => String(item[valueKey]) === previous)) {
    selectEl.value = previous;
  }
}

function playerMatchesSearch(player, search) {
  const haystack = `${player.name || ""} ${player.label || ""}`.toLowerCase();
  const needle = search.toLowerCase();
  if (haystack.includes(needle)) {
    return true;
  }
  if (needle.includes("elliott")) {
    return haystack.includes(needle.replaceAll("elliott", "elliot"));
  }
  if (needle.includes("elliot")) {
    return haystack.includes(needle.replaceAll("elliot", "elliott"));
  }
  return false;
}

function renderPlayerDropdown() {
  const search = playerSearchEl.value.trim();
  const filtered = state.players.filter((player) => playerMatchesSearch(player, search));

  fillSelect(playerSelectEl, filtered, "Select a player", "key", "label");
  updateAddCompareButtonState();
  updateChartButtonState();
}

function getPlayerSeasons() {
  const player = getSelectedPlayer();
  if (!player || !Array.isArray(player.seasons)) {
    return [];
  }
  return player.seasons;
}

function renderSeasonUI() {
  if (!seasonChipsEl && !seasonListEl) {
    return;
  }
}

async function loadPlayers() {
  const search = playerSearchEl.value.trim();
  if (search.length < 3 && !getCompetitionName()) {
    state.players = [];
    fillSelect(playerSelectEl, [], "Type at least 3 letters to search…");
    loadChartsBtn.disabled = true;
    setStatus("Type at least 3 letters to search across our five leagues.");
    return;
  }

  if (search && search === lastPlayerSearchQuery) {
    return;
  }
  lastPlayerSearchQuery = search;

  if (playerSearchAbort) {
    playerSearchAbort.abort();
  }
  playerSearchAbort = new AbortController();
  const requestId = ++playerSearchRequestId;
  const requestQuery = search;

  setStatus(search ? `Searching for "${search}"…` : "Loading players…");

  const res = await fetch("/api/players", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      competition_name: getCompetitionName(),
      search: search || null,
    }),
    signal: playerSearchAbort.signal,
  });
  const data = await readJsonResponse(res);
  if (!res.ok) {
    throw new Error(formatApiError(data.detail, res.status));
  }

  if (requestId !== playerSearchRequestId || playerSearchEl.value.trim() !== requestQuery) {
    return;
  }

  state.players = data.players || [];
  renderPlayerDropdown();

  if (state.players.length === 0) {
    setStatus(data.message || "No players matched your search.");
    return;
  }

  hideAlert();
  const scope =
    data.search_scope === "all_leagues"
      ? "all five leagues"
      : getCompetitionName();
  setStatus(`Found ${state.players.length} player(s) in ${scope}.`);
}

function renderProfileUI() {
  syncSelectedProfilesToAvailable();
  renderProfileChips();
  renderProfileList();
  renderStudioShellUI();
  updateChartButtonState();
}

function renderProfileChips() {
  profileChipsEl.innerHTML = "";
  if (!getPrimaryPlayerKey() || chartSourceEl.value !== "profiles") {
    return;
  }

  const selected = state.availableProfiles.filter((name) =>
    state.selectedProfileNames.has(name),
  );

  if (state.comparedPlayers.some((entry) => !entry.position)) {
    profileChipsEl.innerHTML = `<span class="chip muted-chip">Select a role for each player to see shared profiles</span>`;
    return;
  }

  if (state.availableProfiles.length === 0) {
    profileChipsEl.innerHTML = `<span class="chip muted-chip">No profiles shared by all compared players</span>`;
    return;
  }

  const sharedHint = document.createElement("span");
  sharedHint.className = "chip muted-chip";
  sharedHint.textContent = `${state.availableProfiles.length} shared by ${state.comparedPlayers.length || 1} player(s)`;
  profileChipsEl.appendChild(sharedHint);

  if (selected.length === 0) {
    return;
  }

  selected.forEach((name) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `${humanizeProfileName(name)}<button type="button" aria-label="Remove profile">×</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.selectedProfileNames.delete(name);
      renderProfileUI();
    });
    profileChipsEl.appendChild(chip);
  });
}

function renderProfileList() {
  profileListEl.innerHTML = "";

  if (chartSourceEl.value !== "profiles") {
    profileListEl.innerHTML = `<div class="pick-item static">Switch to profile scores to pick profiles.</div>`;
    return;
  }

  if (!getPrimaryPlayerKey()) {
    profileListEl.innerHTML = `<div class="pick-item static">Add a player to comparison to see profiles.</div>`;
    return;
  }

  if (state.comparedPlayers.some((entry) => !entry.position)) {
    profileListEl.innerHTML = `<div class="pick-item static">Select a role for each player to see shared profiles.</div>`;
    return;
  }

  if (state.availableProfiles.length === 0) {
    const mixedHint = mixedPositionsProfileHint();
    profileListEl.innerHTML = `<div class="pick-item static">${
      mixedHint || "No profiles shared by all compared players."
    }</div>`;
    return;
  }

  state.availableProfiles.forEach((name) => {
    const button = document.createElement("button");
    button.type = "button";
    const isSelected = state.selectedProfileNames.has(name);
    button.className = `pick-item${isSelected ? " selected" : ""}`;
    button.innerHTML = `
      <span>${humanizeProfileName(name)}</span>
      <small>${isSelected ? "Selected" : "Add"}</small>
    `;
    button.addEventListener("click", () => {
      if (state.selectedProfileNames.has(name)) {
        state.selectedProfileNames.delete(name);
      } else {
        state.selectedProfileNames.add(name);
      }
      renderProfileUI();
    });
    profileListEl.appendChild(button);
  });
}

function selectAllProfiles() {
  state.selectedProfileNames = new Set(state.availableProfiles);
}

function updateProfilesFromPositionMeta() {
  if (chartSourceEl.value !== "profiles") {
    state.availableProfiles = [];
    state.profileLoadWarnings = [];
    state.selectedProfileNames.clear();
    renderProfileUI();
    return;
  }

  const playersWithPosition = state.comparedPlayers.filter((entry) => entry.position);
  if (playersWithPosition.length === 0) {
    state.availableProfiles = [];
    state.profileLoadWarnings = [];
    state.selectedProfileNames.clear();
    renderProfileUI();
    return;
  }

  let shared = null;
  for (const entry of playersWithPosition) {
    const profiles = state.positionProfiles.get(entry.position) || [];
    if (shared === null) {
      shared = new Set(profiles);
    } else {
      shared = new Set([...shared].filter((name) => profiles.includes(name)));
    }
  }

  state.availableProfiles = shared ? [...shared].sort() : [];
  state.profileLoadWarnings = [];

  const mixedHint = mixedPositionsProfileHint();
  if (mixedHint && state.availableProfiles.length < 2) {
    state.profileLoadWarnings = [mixedHint];
  }

  syncSelectedProfilesToAvailable();
  renderProfileUI();
}

async function loadStudioMeta() {
  try {
    const res = await fetchWithTimeout("/api/squad-balance/meta");
    const data = await readJsonResponse(res);
    if (!res.ok) {
      throw new Error(data.detail || "Could not load position meta");
    }
    state.studioPositionOptions = (data.positions || []).map((item) => ({
      position: item.id,
      label: item.label,
      shortLabel: item.shortLabel,
    }));
    state.positionProfiles = new Map();
    (data.positions || []).forEach((item) => {
      const apiNames = (item.profiles || []).map((profile) => profile.apiName);
      state.positionProfiles.set(item.id, apiNames);
    });
  } catch (error) {
    state.studioPositionOptions = [];
    state.positionProfiles = new Map();
    console.error("Failed to load studio meta:", error);
  }
}

function buildPositionsRequestBody(playerKeys) {
  return {
    iteration_ids: [],
    player_keys: playerKeys,
    player_key: playerKeys[0],
    independent_seasons: true,
    ...getSeasonModePayload(),
    player_seasons: getPlayerSeasonsPayload(),
    player_positions: getPlayerPositionsPayload(),
    player_catalog: getPlayerCatalogPayload(),
    chart_source: chartSourceEl.value,
  };
}

async function loadBatchPlayerPositions(entries) {
  const playerKeys = entries.map((entry) => entry.key);
  const batchKey = playerKeys.slice().sort().join("|");
  const inflight = positionRequestsInFlight.get(batchKey);
  if (inflight) {
    return inflight;
  }

  const request = (async () => {
    entries.forEach((entry) => {
      entry.positionsLoaded = false;
      updateComparePlayerRow(entry.key);
    });

    const res = await fetch("/api/player-positions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPositionsRequestBody(playerKeys)),
    });
    const data = await readJsonResponse(res);
    if (!res.ok) {
      entries.forEach((entry) => {
        entry.positionsLoaded = true;
        entry.availablePositions = [];
        entry.positionError = "Could not load positions";
        updateComparePlayerRow(entry.key);
      });
      throw new Error(formatApiError(data.detail, res.status));
    }

    entries.forEach((entry) => {
      applyPositionDataToEntry(entry, data.players?.[entry.key]);
      updateComparePlayerRow(entry.key);
    });

    if (data.warnings?.length) {
      showWarning(data.warnings.join(" "));
    }

    return entries;
  })();

  positionRequestsInFlight.set(batchKey, request);
  try {
    return await request;
  } finally {
    positionRequestsInFlight.delete(batchKey);
  }
}

async function loadSinglePlayerPositions(entry) {
  return loadBatchPlayerPositions([entry]);
}

async function loadPositionsForPlayers({ playerKeys = null, force = false } = {}) {
  const targets = (playerKeys || getComparedPlayerKeys())
    .map((key) => state.comparedPlayers.find((entry) => entry.key === key))
    .filter(Boolean);

  if (!targets.length) {
    return;
  }

  const pending = [];
  for (const entry of targets) {
    if (!force && applyPositionCache(entry)) {
      updateComparePlayerRow(entry.key);
      continue;
    }
    pending.push(entry);
  }

  if (!pending.length) {
    updateChartButtonState();
    return;
  }

  setStatus(
    `Loading positions for ${pending.length} player${pending.length === 1 ? "" : "s"}…`,
  );

  try {
    await loadBatchPlayerPositions(pending);
  } catch (error) {
    const message = error.message || "Could not load positions";
    showAlert(message);
    setStatus("Could not load positions — try again.");
    if (isRateLimitError(message)) {
      scheduleRateLimitRetry(
        () => loadPositionsForPlayers({ playerKeys: pending.map((entry) => entry.key), force: true }),
        { label: "Position load" },
      );
    }
    updateChartButtonState();
    return;
  }

  const loadedCount = pending.length;
  setStatus(`Positions loaded for ${loadedCount} player${loadedCount === 1 ? "" : "s"}.`);

  const hintMessage = pending.find((entry) => entry.positionHint)?.positionHint;
  if (hintMessage && state.comparedPlayers.length === 1) {
    showWarning(hintMessage);
  } else {
    hideAlert();
  }

  updateChartButtonState();
}

async function loadIterations() {
  setStatus("Loading competitions from Impect…");
  setConnection("loading", "Connecting…");

  try {
    const res = await fetchWithTimeout("/api/iterations");
    const data = await readJsonResponse(res);
    if (!res.ok) {
      throw new Error(data.detail || "Could not load seasons");
    }

    state.iterations = data.iterations || [];
    fillSelect(
      competitionFilterEl,
      (data.competitions || []).map((name) => ({ id: name, name })),
      "All five leagues",
      "id",
      "name",
    );

    renderSeasonUI();
    hideAlert();
    setConnection("ok", `${state.iterations.length} seasons across 5 leagues`);
    setStatus("Type a player name to search — e.g. Jed Ward.");
  } catch (error) {
    setConnection("error", "Connection failed");
    const hint =
      error.name === "AbortError"
        ? "The server took too long to respond."
        : error.message || "Could not reach the dashboard server.";
    showAlert(
      `${hint} Open http://127.0.0.1:8000 after starting the server: ./start.sh`,
    );
    setStatus("Failed to load data.");
  }
}

async function onPlayerChanged() {
  const player = getSelectedPlayerFromDropdown();
  state.selectedPlayer = player;
  updateAddCompareButtonState();

  if (!player) {
    return;
  }

  if (state.comparedPlayers.length === 0) {
    setStatus(`Loading ${player.name} history from Impect…`);
    const entry = await addPlayerToComparison(player);
    if (!entry) {
      return;
    }

    if (!entry.historyLoaded) {
      showAlert(
        `Could not load season history for ${player.name}. Check the connection and try again.`,
      );
      loadChartsBtn.disabled = true;
      return;
    }

    const chartableCount = (entry.chartable_season_ids || []).length;
    const seasonCount = Object.keys(entry.ids_by_iteration || {}).length;
    if (chartableCount === 0 && seasonCount === 0) {
      showAlert(
        `${player.name} is listed in Impect but has no squad data in our five leagues. Try another player or season.`,
      );
      loadChartsBtn.disabled = true;
      return;
    }

    hideAlert();
    setStatus(
      `${player.name}: ${chartableCount} season${chartableCount === 1 ? "" : "s"} with data. Latest auto-selected.`,
    );
    updateChartButtonState();
  }
}

async function onAddComparePlayer() {
  const player = getSelectedPlayerFromDropdown();
  if (!player) {
    showAlert("Select a player from search results first.");
    return;
  }

  if (state.comparedPlayers.some((entry) => entry.key === player.key)) {
    return;
  }

  setStatus(`Loading ${player.name} history from Impect…`);
  const entry = await addPlayerToComparison(player);
  if (!entry) {
    return;
  }

  if (!entry.historyLoaded) {
    if (playerHasSeasonCatalog(entry)) {
      entry.historyLoaded = true;
      hideAlert();
      setStatus(`${player.name} added — using seasons from search.`);
    } else {
      showAlert(
        `Could not load season history for ${player.name}. Check the connection and try again.`,
      );
      updateChartButtonState();
      return;
    }
  }

  if (!(entry.chartable_season_ids || []).length && !Object.keys(entry.ids_by_iteration || {}).length) {
    showAlert(
      `${player.name} is listed in Impect but has no squad data in our five leagues.`,
    );
    updateChartButtonState();
    return;
  }

  hideAlert();
  setStatus(
    `${player.name} added (${state.comparedPlayers.length} player${state.comparedPlayers.length === 1 ? "" : "s"}). Pick their season above if needed.`,
  );
  updateChartButtonState();
}

function buildSeasonTraces(seasons, valueKey, chartType) {
  return seasons.map((season, index) => {
    const color = seasonColors[index % seasonColors.length];
    if (chartType === "scatterpolar") {
      return radarTrace(season[valueKey], season.labels, season.label, color);
    }

    return pizzaTrace(season[valueKey], season.labels, season.label, color);
  });
}

function buildComparedPlayerTraces(comparedPlayers, fallbackLabels = [], options = {}) {
  const multiPlayer = comparedPlayers.length > 1;
  const mixedPositions =
    new Set(comparedPlayers.map((entry) => entry.position_label || entry.position).filter(Boolean))
      .size > 1;
  const compact = Boolean(options.compact);

  return comparedPlayers.map((entry, index) => {
    const traceName = playerLegendLabel(entry, { includePosition: mixedPositions });
    const labels = entry.labels || fallbackLabels;
    return radarTrace(
      entry.radar_values,
      labels,
      traceName,
      seasonColors[index % seasonColors.length],
      !multiPlayer || index === 0,
      formatAxisLabel,
      {
        compact,
        fullLabels: labels,
        thetaLabels: options.thetaLabels,
      },
    );
  });
}

function   plotComparedRadar(elementId, comparedPlayers, fallbackLabels, benchmark, options = {}) {
  const chartEl = document.getElementById(elementId);
  if (!chartEl) {
    return;
  }
  chartEl.classList.remove("empty-chart");
  chartEl.textContent = "";
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
  Plotly.newPlot(
    elementId,
    traces,
    polarChartLayout(labelCount, {
      showLegend,
      radialaxis: { ticksuffix: "%", range: [0, 100] },
      compact,
      drilldownPanel: compact && !options.layout?.drilldownStacked,
      drilldownStacked: Boolean(options.layout?.drilldownStacked),
      categoryarray: thetaKeys || [],
      ticktext: thetaTickText,
      ...options.layout,
    }),
    plotlyConfig,
  ).then(() => keepPlotFittedToContainer(elementId));
}

function limitChartFactorSeries(labels, ...series) {
  const trimmedLabels = (labels || []).slice(0, MAX_CHART_FACTORS);
  return [trimmedLabels, ...series.map((values) => (values || []).slice(0, MAX_CHART_FACTORS))];
}

function limitChartPayload(data) {
  if (!data) {
    return data;
  }

  const limited = { ...data };

  if (limited.labels) {
    [limited.labels, limited.radar_values, limited.pizza_values] = limitChartFactorSeries(
      limited.labels,
      limited.radar_values,
      limited.pizza_values,
    );
  }

  if (limited.players?.length) {
    limited.players = limited.players.map((player) => {
      const copy = { ...player };
      [copy.labels, copy.radar_values, copy.pizza_values] = limitChartFactorSeries(
        copy.labels,
        copy.radar_values,
        copy.pizza_values,
      );
      return copy;
    });
  }

  if (limited.seasons?.length) {
    limited.seasons = limited.seasons.map((season) => {
      const copy = { ...season };
      [copy.labels, copy.radar_values, copy.pizza_values] = limitChartFactorSeries(
        copy.labels,
        copy.radar_values,
        copy.pizza_values,
      );
      return copy;
    });
  }

  if (limited.profile_drilldowns?.length) {
    limited.profile_drilldowns = limited.profile_drilldowns.map((entry) => {
      const copy = { ...entry };
      [copy.labels, copy.radar_values, copy.raw_values] = limitChartFactorSeries(
        copy.labels,
        copy.radar_values,
        copy.raw_values,
      );
      if (copy.inverted) {
        copy.inverted = copy.inverted.slice(0, MAX_CHART_FACTORS);
      }
      copy.bar_labels = (copy.bar_labels || []).slice(0, MAX_BAR_FACTORS);
      copy.bar_radar_values = (copy.bar_radar_values || []).slice(0, MAX_BAR_FACTORS);
      copy.bar_raw_values = (copy.bar_raw_values || []).slice(0, MAX_BAR_FACTORS);
      copy.bar_weights = (copy.bar_weights || []).slice(0, MAX_BAR_FACTORS);
      copy.bar_inverted = (copy.bar_inverted || []).slice(0, MAX_BAR_FACTORS);
      if (copy.players?.length) {
        copy.players = copy.players.map((player) => ({
          ...player,
          labels: (copy.labels || player.labels || []).slice(0, MAX_CHART_FACTORS),
          radar_values: (player.radar_values || []).slice(0, MAX_CHART_FACTORS),
          raw_values: (player.raw_values || []).slice(0, MAX_CHART_FACTORS),
          bar_labels: (copy.bar_labels || []).slice(0, MAX_BAR_FACTORS),
          bar_radar_values: (player.bar_radar_values || []).slice(0, MAX_BAR_FACTORS),
          bar_raw_values: (player.bar_raw_values || []).slice(0, MAX_BAR_FACTORS),
        }));
      }
      return copy;
    });
  }

  return limited;
}

function studioProfileLabelParts(label) {
  const text = String(label || "").trim();
  const parts = text.split(" - ").map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) {
    const main = parts[0].toUpperCase();
    const sub = parts.slice(1).join(" - ");
    if (sub.toUpperCase() === main) {
      return { main, sub: null };
    }
    return { main, sub };
  }
  return { main: text.toUpperCase(), sub: null };
}

function studioProfileLabelMarkup(label) {
  const parts = studioProfileLabelParts(label);
  if (parts.sub) {
    return `
      <p class="comparison-row__label-main">${parts.main}</p>
      <p class="comparison-row__label-sub">${parts.sub}</p>
    `;
  }
  return `<p class="comparison-row__label-main">${parts.main}</p>`;
}

function studioAverageClass(value) {
  if (value == null || Number.isNaN(value)) {
    return "comparison-cell--avg-low";
  }
  if (value >= 66) {
    return "comparison-cell--avg-high";
  }
  if (value >= 33) {
    return "comparison-cell--avg-mid";
  }
  return "comparison-cell--avg-low";
}

function studioPlayerPhotoMarkup(player) {
  if (player.photo_url) {
    return `<img class="player-photo__image" src="${player.photo_url}" alt="${player.name}" />`;
  }
  return `<div class="player-photo__placeholder">${playerInitials(player.name)}</div>`;
}

function studioComparisonPlayersFromChart(data) {
  const profiles = data.labels || [];
  return (data.players || []).map((entry, index) => {
    const compared = state.comparedPlayers.find((row) => row.key === entry.key) || {};
    const profileScores = {};
    profiles.forEach((label, profileIndex) => {
      const value = entry.radar_values?.[profileIndex];
      if (value != null && !Number.isNaN(Number(value))) {
        profileScores[label] = Number(value);
      }
    });
    return {
      key: entry.key,
      name: entry.player,
      photo_url: entry.photo_url || compared.photo_url,
      minutes: Math.round(Number(entry.play_duration_minutes) || 0),
      season_label: entry.season_label || "",
      position_label: entry.position_label || compared.position_label || "",
      club: compared.club || "",
      league: compared.league || "",
      profileScores,
      colorIndex: index,
    };
  });
}

function studioMinutesLabel(player) {
  const minutes = Math.round(Number(player.minutes) || 0);
  const season = String(player.season_label || "").trim();
  if (minutes > 0 && season) {
    return `(${minutes}′ · ${season})`;
  }
  if (minutes > 0) {
    return `(${minutes}′)`;
  }
  return season;
}

function studioReferenceProfileScores(reference, profileApiNames) {
  const scores = reference?.profile_scores || {};
  const mapped = {};
  profileApiNames.forEach((apiName) => {
    if (scores[apiName] != null && !Number.isNaN(Number(scores[apiName]))) {
      mapped[apiName] = Number(scores[apiName]);
      return;
    }
    const match = Object.keys(scores).find(
      (key) => key.toLowerCase() === apiName.toLowerCase(),
    );
    if (match != null && !Number.isNaN(Number(scores[match]))) {
      mapped[apiName] = Number(scores[match]);
    }
  });
  return mapped;
}

function studioAverageProfileScores(players, profiles) {
  const averages = {};
  profiles.forEach((label) => {
    const values = players
      .map((player) => player.profileScores?.[label])
      .filter((value) => value != null)
      .map(Number);
    averages[label] = values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : null;
  });
  return averages;
}

function renderStudioComparisonFront(data) {
  if (!studioComparisonFrontEl || chartSourceEl.value !== "profiles") {
    if (studioComparisonFrontEl) {
      studioComparisonFrontEl.innerHTML = "";
    }
    return;
  }

  const players = studioComparisonPlayersFromChart(data);
  const profiles = (data.labels || []).map((label) => ({
    apiName: label,
    label: humanizeProfileName(label),
  }));
  if (!players.length || profiles.length < 2) {
    studioComparisonFrontEl.innerHTML = "";
    return;
  }

  const positionEntry =
    state.studioPositionOptions.find(
      (item) => item.position === state.comparedPlayers[0]?.position,
    ) || {};
  const positionLabel = positionEntry.label || players[0]?.position_label || "Player";
  const positionShort = positionEntry.shortLabel || positionAbbrev(state.comparedPlayers[0]?.position) || "POS";
  const seasonNote = "One selected season per player at role";
  const reference = data.port_vale_reference || null;
  const referenceScores = studioReferenceProfileScores(
    reference,
    profiles.map((item) => item.apiName),
  );
  const playerCount = players.length;

  const frame = document.createElement("div");
  frame.className = "comparison-frame comparison-frame--keynote";
  frame.dataset.players = String(playerCount);
  frame.dataset.profiles = String(profiles.length);
  if (playerCount >= 4 && profiles.length >= 4) {
    frame.classList.add("comparison-frame--dense");
  }

  const frameHead = document.createElement("div");
  frameHead.className = "comparison-frame__head";
  frameHead.innerHTML = `
    <div class="comparison-frame__titles">
      <p class="comparison-frame__club">PLAYER COMPARISON</p>
      <h2 class="comparison-frame__title">${String(positionLabel).toUpperCase()} COMPARISON</h2>
      <p class="comparison-frame__season">${seasonNote}</p>
    </div>
    <span class="comparison-frame__badge">${positionShort}</span>
  `;
  frame.appendChild(frameHead);

  const body = document.createElement("div");
  body.className = "comparison-frame__body";
  body.style.setProperty("--player-cols", String(playerCount));

  const table = document.createElement("div");
  table.className = "comparison-table";
  table.style.setProperty("--player-cols", String(playerCount));

  const corner = document.createElement("div");
  corner.className = "comparison-table__corner";
  corner.setAttribute("aria-hidden", "true");
  table.appendChild(corner);

  // Player colours follow the radar traces (seasonColors) so a player is the
  // same colour in the table, the radar and the exported deck.
  players.forEach((player, index) => {
    const color = seasonColors[index % seasonColors.length];
    const photo = document.createElement("div");
    photo.className = "player-photo";
    photo.style.gridColumn = String(index + 2);

    const wrap = document.createElement("div");
    wrap.className = "player-photo__image-wrap";
    wrap.style.borderColor = color;
    wrap.innerHTML = studioPlayerPhotoMarkup(player);
    photo.appendChild(wrap);

    const name = document.createElement("p");
    name.className = "player-photo__name";
    name.style.color = color;
    name.textContent = player.name;
    photo.appendChild(name);

    const minutes = document.createElement("p");
    minutes.className = "player-photo__minutes";
    minutes.textContent = studioMinutesLabel(player);
    photo.appendChild(minutes);

    table.appendChild(photo);
  });

  const refPhoto = document.createElement("div");
  refPhoto.className = "player-photo player-photo--average player-photo--reference";
  refPhoto.style.gridColumn = String(playerCount + 2);
  if (reference?.player) {
    // Silver, not gold: gold is the first compared player's trace colour.
    refPhoto.innerHTML = `
      <div class="player-photo__image-wrap" style="border-color:#e2e8f0">
        ${reference.photo_url
          ? `<img class="player-photo__image" src="${reference.photo_url}" alt="${reference.player}" />`
          : `<div class="player-photo__placeholder">${playerInitials(reference.player)}</div>`}
      </div>
      <p class="player-photo__name" style="color:#e2e8f0">${reference.player}</p>
      <p class="player-photo__minutes">${studioMinutesLabel(reference)}</p>
      <p class="player-photo__minutes player-photo__minutes--hint">PV most mins at ${positionShort}</p>
    `;
  } else {
    refPhoto.innerHTML = `
      <div class="player-photo__image-wrap player-photo__image-wrap--average">
        <img class="player-photo__badge" src="/standalone/port-vale-badge.png?v=2" alt="Port Vale FC crest" />
      </div>
      <p class="player-photo__name" style="color:var(--gold)">Port Vale</p>
      <p class="player-photo__minutes">No squad data</p>
    `;
  }
  table.appendChild(refPhoto);

  profiles.forEach((profile) => {
    const row = document.createElement("div");
    row.className = "comparison-row";

    const labelCell = document.createElement("div");
    labelCell.className = "comparison-row__label";
    labelCell.innerHTML = studioProfileLabelMarkup(profile.label);
    row.appendChild(labelCell);

    const rowValues = players.map((player) => player.profileScores?.[profile.apiName] ?? null);
    const numericValues = rowValues.filter((value) => value != null);
    const leaderValue =
      numericValues.length > 0 ? Math.max(...numericValues.map((value) => Number(value))) : null;

    // Bars are banded by percentile, not by player, so a weak score never
    // looks the same as a strong one. Player identity lives in the photo row.
    players.forEach((player) => {
      const value = player.profileScores?.[profile.apiName];
      const cell = document.createElement("div");
      const isLeader = value != null && leaderValue != null && Number(value) === leaderValue;
      cell.className = `comparison-cell comparison-cell--bar pctband pctband--${percentileBandKey(
        value,
      )}${isLeader ? " comparison-cell--leader" : ""}`;
      if (value != null) {
        cell.style.setProperty("--bar-width", `${Math.max(0, Math.min(100, Number(value)))}%`);
      }
      cell.innerHTML = `<span class="comparison-cell__value">${value == null ? "—" : `${Math.round(value)}%`}</span>`;
      row.appendChild(cell);
    });

    const refValue = referenceScores[profile.apiName];
    const refCell = document.createElement("div");
    refCell.className = `comparison-cell comparison-cell--bar comparison-cell--average comparison-cell--reference pctband pctband--${percentileBandKey(
      refValue,
    )} ${studioAverageClass(refValue)}`;
    if (refValue != null) {
      refCell.style.setProperty("--bar-width", `${Math.max(0, Math.min(100, refValue))}%`);
    }
    refCell.innerHTML = `<span class="comparison-cell__value">${refValue == null ? "—" : `${Math.round(refValue)}%`}</span>`;
    row.appendChild(refCell);

    table.appendChild(row);
  });

  body.appendChild(table);

  // The photo row above already names every player and their club, so the old
  // legend repeated it. A percentile key is what actually needed explaining.
  body.appendChild(buildPercentileScaleKey());

  const note = document.createElement("p");
  note.className = "comparison-note";
  const benchmark = data.benchmark;
  note.textContent = benchmark?.cohort_size
    ? `Percentiles vs ${benchmark.cohort_size} players · ${(benchmark.competitions || []).join(", ")} · ${benchmark.min_minutes || 600}+ min`
    : "Position-specific profiles · one selected season per player.";
  body.appendChild(note);

  frame.appendChild(body);

  const card = document.createElement("div");
  card.className = "card chart-card studio-comparison-export-card";

  // The frame carries its own heading, so a second title block above it was
  // just repetition. One toolbar row holds the export controls instead.
  mountStudioDeckExportToolbar(card, {
    hint: "Export the whole deck as a PDF or slides. <strong>Remove from export</strong> skips a panel.",
    extraActions: [createExportToggleButton({ exportKey: "comparison-front", cardElement: card })],
  });

  card.appendChild(frame);

  studioComparisonFrontEl.innerHTML = "";
  studioComparisonFrontEl.appendChild(card);
  updateWholeDeckButtonState();
}

function renderRadar(data) {
  const comparedPlayers = data.players?.length
    ? data.players
    : [{ player: data.player, labels: data.labels, radar_values: data.radar_values }];
  const multiPlayer = comparedPlayers.length > 1;
  // Name the players rather than counting them — "2 players compared" told the
  // reader nothing the legend did not already say.
  const title = multiPlayer
    ? comparedPlayers
        .slice(0, 3)
        .map((entry) => entry.player)
        .join("  vs  ") + (comparedPlayers.length > 3 ? `  +${comparedPlayers.length - 3}` : "")
    : comparedPlayers[0]?.player || data.player;

  setChartMeta(
    "radarChartPlayer",
    "radarChartSubtitle",
    "radarChartMeta",
    title,
    formatBenchmarkSubtitle(data.benchmark),
  );

  plotComparedRadar("radarChart", comparedPlayers, data.labels || [], data.benchmark, {
    layout: {
      showLegend: comparedPlayers.length > 1,
      compact: false,
      drilldownPanel: false,
    },
  });
}

// Factor bars for the on-screen drilldown card. The track is coloured by
// percentile band so strong and weak read instantly; the player's own colour
// stays on the initial chip so you can still tell the rows apart.
function renderDrilldownFactorList(entry, players, barsId = "") {
  const list = document.createElement("div");
  list.className = "factor-list";
  if (barsId) {
    list.id = barsId;
  }
  const multiPlayer = players.length > 1;
  const barLabels = entry.bar_labels || entry.labels || [];
  const barWeights = entry.bar_weights || [];
  list.dataset.factors = String(barLabels.length);

  barLabels.forEach((label, factorIndex) => {
    const hasMissingValue = players.some((player) => {
      const percentile = player.bar_radar_values?.[factorIndex];
      return percentile == null || Number.isNaN(percentile);
    });
    if (hasMissingValue) {
      return;
    }

    const group = document.createElement("div");
    group.className = "factor";

    const groupHead = document.createElement("div");
    groupHead.className = "factor__head";
    const name = document.createElement("p");
    name.className = "factor__name";
    name.textContent = humanizeFootballLabel(label);
    groupHead.appendChild(name);
    if (barWeights[factorIndex] != null) {
      const weight = document.createElement("span");
      weight.className = "factor__weight";
      weight.textContent = `${Math.round(barWeights[factorIndex])}% of profile`;
      groupHead.appendChild(weight);
    }
    group.appendChild(groupHead);

    const averagePercentile = multiPlayer
      ? averagePercentileForFactor(players, factorIndex, "bar_radar_values")
      : null;

    players.forEach((player, playerIndex) => {
      group.appendChild(
        buildFactorBarRow(player, factorIndex, {
          color: seasonColors[playerIndex % seasonColors.length],
          showInitials: multiPlayer,
          averagePercentile,
        }),
      );
    });

    list.appendChild(group);
  });

  return list;
}

function buildFactorBarRow(player, factorIndex, { color, showInitials, averagePercentile }) {
  const resolved = resolveBarScores(
    player.bar_radar_values?.[factorIndex],
    player.bar_raw_values?.[factorIndex],
  );
  const percentile = barTrackPercentile(resolved.percentile, resolved.rawValue);

  const row = document.createElement("div");
  row.className = `factor__row pctband pctband--${percentileBandKey(percentile)}`;

  if (showInitials) {
    const chip = document.createElement("span");
    chip.className = "factor__who";
    chip.style.background = color;
    chip.textContent = playerInitials(player.player || "");
    chip.title = player.player || "";
    row.appendChild(chip);
  }

  const track = document.createElement("div");
  track.className = "factor__track";

  const fill = document.createElement("span");
  fill.className = "factor__fill";
  fill.style.width = `${Math.max(2, Math.min(100, Number(percentile) || 0))}%`;
  track.appendChild(fill);

  if (averagePercentile != null && Number.isFinite(Number(averagePercentile))) {
    const marker = document.createElement("span");
    marker.className = "factor__avg";
    marker.style.left = `${Math.min(Math.max(Number(averagePercentile), 0), 100)}%`;
    marker.title = `Average of these players: ${formatPercentileLabel(averagePercentile)}`;
    track.appendChild(marker);
  }
  row.appendChild(track);

  const value = document.createElement("span");
  value.className = "factor__value";
  value.textContent = formatBarInnerValue(resolved.percentile, resolved.rawValue);
  row.appendChild(value);

  return row;
}

function renderProfileDrilldowns(data) {
  const section = document.getElementById("profileDrilldownSection");
  section.innerHTML = "";

  const drilldowns = data.profile_drilldowns || [];
  if (chartSourceEl.value !== "profiles" || drilldowns.length === 0) {
    section.classList.add("hidden");
    updateWholeDeckButtonState();
    return;
  }

  section.classList.remove("hidden");

  const header = document.createElement("div");
  header.className = "drilldown-header";

  const headerText = document.createElement("div");
  headerText.innerHTML = `
    <h2>Profile breakdown</h2>
    <p class="chart-caption">Each profile has a drilldown slide in the deck. Use <strong>Remove from export</strong> on any card you want to skip.</p>
  `;
  header.appendChild(headerText);

  section.appendChild(header);

  const stack = document.createElement("div");
  stack.className = "profile-drilldown-stack";
  section.appendChild(stack);

  drilldowns.forEach((entry, index) => {
    const card = document.createElement("div");
    card.className = "card chart-card profile-drilldown-card";
    const chartId = `profileDrilldown-${index}`;
    const barsId = `profileDrilldownBars-${index}`;
    const profileTitle = humanizeProfileName(entry.profile);
    const profileSlug = chartImageSlug(profileTitle);

    const head = document.createElement("div");
    head.className = "chart-card-head";
    const headText = document.createElement("div");

    const title = document.createElement("h3");
    title.textContent = profileDisplayTitle(entry.profile);
    headText.appendChild(title);

    const players = enrichDrilldownPlayers(
      entry.players?.length
        ? entry.players
        : [
            {
              player: data.player,
              labels: entry.labels,
              radar_values: entry.radar_values,
              raw_values: entry.raw_values || [],
              bar_labels: entry.bar_labels || entry.labels || [],
              bar_radar_values: entry.bar_radar_values || entry.radar_values || [],
              bar_raw_values: entry.bar_raw_values || entry.raw_values || [],
            },
          ],
      data.players || [],
    );

    head.appendChild(headText);

    const actions = document.createElement("div");
    actions.className = "chart-card-actions";
    const exportKey = exportSectionKeyForProfile(entry.profile);
    actions.appendChild(
      createExportToggleButton({
        exportKey,
        cardElement: card,
      }),
    );
    actions.appendChild(
      createSlideExportButton({
        chartId,
        barsId,
        slug: `${profileSlug}-slide`,
        title: profileTitle,
        label: "Save slide",
      }),
    );
    actions.appendChild(
      createChartExportButton({
        elementId: chartId,
        slug: `${profileSlug}-radar`,
        compact: true,
        drilldownCard: true,
        label: "Save radar",
      }),
    );
    actions.appendChild(
      createBarsExportButton({
        barsId,
        slug: `${profileSlug}-bars`,
        title: profileTitle,
        label: "Save bars",
      }),
    );
    head.appendChild(actions);
    card.appendChild(head);

    // Caption sits on its own full-width row so the export buttons cannot
    // squeeze it into a two-word column.
    const meta = document.createElement("p");
    meta.className = "drilldown-card-meta";
    const radarCount = entry.labels?.length || 0;
    const barCount = entry.bar_labels?.length || radarCount;
    meta.textContent =
      radarCount > barCount
        ? `The ${barCount} factors that weigh heaviest in this profile — the radar shows all ${radarCount}`
        : "Every factor that feeds this profile";
    card.appendChild(meta);

    const body = document.createElement("div");
    body.className = "profile-drilldown-body";

    const radarPanel = document.createElement("div");
    radarPanel.className = "profile-drilldown-radar";
    const chart = document.createElement("div");
    chart.id = chartId;
    chart.className = "chart drilldown-chart";
    radarPanel.appendChild(chart);
    // One player strip carries photo, name and colour. It replaces the old
    // floating side portraits plus legend pill, which showed the same thing twice.
    radarPanel.appendChild(buildDrilldownPlayerStrip(players));
    body.appendChild(radarPanel);

    const barsPanel = document.createElement("div");
    barsPanel.className = "profile-drilldown-bars";
    barsPanel.appendChild(
      renderDrilldownFactorList(
        {
          bar_labels: entry.bar_labels || entry.labels || [],
          bar_weights: entry.bar_weights || [],
        },
        players,
        barsId,
      ),
    );
    body.appendChild(barsPanel);

    card.appendChild(body);
    stack.appendChild(card);

    plotComparedRadar(chartId, players, entry.labels || [], data.benchmark, {
      compact: true,
      layout: {
        showLegend: false,
        drilldownStacked: true,
      },
    });
  });
}

function renderPizza(data) {
  const pizzaEl = document.getElementById("pizzaChart");
  if (!pizzaEl) {
    return;
  }
  pizzaEl.classList.remove("empty-chart");
  const useCombined = data.combine_seasons || (data.seasons?.length ?? 0) <= 1;
  const labelCount = data.labels?.length ?? 0;
  const traces = useCombined
    ? [pizzaTrace(data.pizza_values, data.labels, data.player)]
    : buildSeasonTraces(data.seasons, "pizza_values", "barpolar");

  setChartMeta(
    "pizzaChartPlayer",
    "pizzaChartSubtitle",
    "pizzaChartMeta",
    data.player,
    formatBenchmarkSubtitle(data.benchmark),
  );

  Plotly.newPlot(
    "pizzaChart",
    traces,
    polarChartLayout(labelCount, {
      showLegend: traces.length > 1,
      radialaxis: { ticksuffix: "%", range: [0, 100] },
    }),
    plotlyConfig,
  ).then(() => keepPlotFittedToContainer("pizzaChart"));
}

async function loadCharts() {
  const blockReason = chartBlockReason();
  if (blockReason) {
    showAlert(blockReason);
    updateChartButtonState();
    return;
  }

  if (loadChartsInFlight) {
    return loadChartsInFlight;
  }

  loadChartsBtn.disabled = true;
  const playerCount = getComparedPlayerKeys().length;
  const statusPrefix = `Building charts for ${playerCount} player${playerCount === 1 ? "" : "s"}`;
  const loadStartedAt = Date.now();
  const statusTicker = window.setInterval(() => {
    const elapsed = Math.round((Date.now() - loadStartedAt) / 1000);
    setStatus(`${statusPrefix}… (${elapsed}s — one season per player)`);
  }, 2000);
  setStatus(`${statusPrefix}…`);

  loadChartsInFlight = (async () => {
    invalidateWholeDeckCaptureCache();
    try {
      const basePayload = {
        player_keys: getComparedPlayerKeys(),
        player_seasons: getPlayerSeasonsPayload(),
        player_positions: getPlayerPositionsPayload(),
        player_catalog: getPlayerCatalogPayload(),
        independent_seasons: true,
        profiles: getValidSelectedProfiles(),
        chart_source: chartSourceEl.value,
        ...getSeasonModePayload(),
      };

      const res = await fetchWithTimeout(
        "/api/charts",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...basePayload, include_drilldowns: true }),
        },
        CHARTS_FETCH_TIMEOUT_MS,
      );
      const data = limitChartPayload(await readJsonResponse(res));
      if (!res.ok) {
        throw new Error(formatApiError(data.detail, res.status));
      }

      renderRadar(data);
      renderStudioComparisonFront(data);
      renderPizza(data);
      renderProfileDrilldowns(data);
      state.lastChartData = data;
      updateWholeDeckButtonState();

      await waitForPlotlyChart("radarChart");
      const drilldownCount = data.profile_drilldowns?.length || 0;
      for (let index = 0; index < drilldownCount; index += 1) {
        await waitForPlotlyChart(`profileDrilldown-${index}`);
      }
      updateWholeDeckButtonState();
      updateStudioCompareMeta(data);
      if (state.studioView === "build") {
        showStudioView("compare");
      }

      if (
        chartSourceEl.value === "profiles" &&
        getValidSelectedProfiles().length >= 2 &&
        !data.profile_drilldowns?.length
      ) {
        showWarning(
          "Profile factor breakdown unavailable — front page and radar can still be exported.",
        );
      }

      if (data.warnings?.length) {
        showWarning(data.warnings.join(" "));
      } else {
        hideAlert();
      }

      const chartPlayerCount = data.players?.length || 1;
      const playerLabel = chartPlayerCount > 1 ? `${chartPlayerCount} players` : data.player;
      const benchmarkNote = data.benchmark?.cohort_size
        ? ` · benchmark cohort ${data.benchmark.cohort_size} players`
        : "";
      const seasonNote = data.players?.length
        ? ` · ${data.players
            .map((entry) => entry.season_label || entry.player)
            .join(" · ")}`
        : "";
      setStatus(
        `Charts ready for ${playerLabel} (${data.labels.length} metrics)${benchmarkNote}${seasonNote}.`,
      );
    } catch (error) {
      const message =
        error.name === "AbortError"
          ? "Chart request timed out — Impect is still slow. Restart the dashboard, hard-refresh, then try 2–3 players or “this season” only."
          : error.message || "Chart generation failed.";
      if (isRateLimitError(message)) {
        if (state.lastChartData) {
          showWarning(
            `${message} Showing your last successful charts until Impect recovers.`,
          );
          updateWholeDeckButtonState();
          scheduleRateLimitRetry(() => loadCharts(), { label: "Chart load" });
        } else {
          showAlert(message);
          scheduleRateLimitRetry(() => loadCharts(), { label: "Chart load" });
        }
      } else {
        clearChartExportState();
        showAlert(message);
      }
      setStatus(message || "Chart generation failed.");
    } finally {
      window.clearInterval(statusTicker);
      updateChartButtonState();
      updateWholeDeckButtonState();
    }
  })();

  try {
    await loadChartsInFlight;
  } finally {
    loadChartsInFlight = null;
  }
}

let playerSearchTimer = null;
let lastPlayerSearchQuery = "";
let playerSearchAbort = null;
let playerSearchRequestId = 0;

competitionFilterEl.addEventListener("change", async () => {
  if (playerSearchEl.value.trim().length >= 3) {
    return;
  }
  playerSelectEl.value = "";
  state.selectedPlayer = null;
  state.comparedPlayers = [];
  renderComparePlayerChips();
  updateProfilesFromPositionMeta();
  try {
    await loadPlayers();
  } catch (error) {
    showAlert(error.message);
  }
});

playerSearchEl.addEventListener("input", () => {
  clearTimeout(playerSearchTimer);
  const search = playerSearchEl.value.trim();
  if (search !== lastPlayerSearchQuery) {
    lastPlayerSearchQuery = "";
  }
  playerSearchTimer = setTimeout(async () => {
    try {
      await loadPlayers();
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }
      showAlert(error.message);
    }
  }, 600);
});

playerSelectEl.addEventListener("change", onPlayerChanged);
addComparePlayerBtn.addEventListener("click", onAddComparePlayer);
chartSourceEl.addEventListener("change", () => {
  profilePickerEl.hidden = chartSourceEl.value !== "profiles";
  updateProfilesFromPositionMeta();
  updateChartButtonState();
});
loadChartsBtn.addEventListener("click", () => {
  loadCharts();
});
bindChartExportButton(exportRadarImageBtn, { elementId: "radarChart", slug: "profile-radar" });
bindChartExportButton(exportPizzaImageBtn, { elementId: "pizzaChart", slug: "squad-pizza" });

function initApp() {
  renderComparePlayerChips();
  initStaticExportToggleButtons();
  if (window.PhotoStudio?.attachPhotoSlots && studioPlayerGridEl) {
    ensureStudioPlayerGridStructure();
    photoStudioApi = window.PhotoStudio.attachPhotoSlots(studioPlayerGridEl, {
      getComparedPlayers: () => state.comparedPlayers,
      onPhotoSaved: applySavedPlayerPhoto,
      showAlert,
      setStatus,
    });
    photoStudioApi.refresh();
  }
  backToBuildBtn?.addEventListener("click", () => showStudioView("build"));
  showStudioView("build");
  if (window.location.pathname.endsWith("/scouting/player") || window.location.pathname.endsWith("/scouting/compare")) {
    setConnection("ok", "Scouting player view");
    return;
  }
  void Promise.all([loadStudioMeta(), loadIterations()]);
}

window.ImpectPlayerCharts = {
  render(data) {
    const limited = limitChartPayload(data);
    renderRadar(limited);
    renderStudioComparisonFront(limited);
    renderProfileDrilldowns(limited);
    renderPizza(limited);
    state.lastChartData = limited;
    exportRadarImageBtn.disabled = false;
    exportPizzaImageBtn.disabled = false;
    updateWholeDeckButtonState();
  },
  async load(chartRequest) {
    const res = await fetch("/api/charts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(chartRequest),
    });
    const data = await readJsonResponse(res);
    if (!res.ok) {
      throw new Error(data.detail || "Could not generate charts");
    }
    this.render(data);
    if (data.warnings?.length) {
      showWarning(data.warnings.join(" "));
    } else {
      hideAlert();
    }
    const playerLabel = data.players?.[0]?.player || data.player || "Player";
    setStatus(`Charts ready for ${playerLabel} (${data.labels?.length || 0} metrics).`);
    return data;
  },
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
