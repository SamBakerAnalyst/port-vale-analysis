function buildChartRequestFromParams(params) {
  const iterationId = Number(params.get("iteration"));
  const playerId = Number(params.get("playerId"));
  const name = params.get("name") || "";
  const position = params.get("position") || "";
  const profiles = (params.get("profiles") || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const squadRaw = params.get("squad");
  const squadId = squadRaw != null && squadRaw !== "" ? Number(squadRaw) : null;

  if (!name || !iterationId || !playerId || !position || profiles.length < 2) {
    return null;
  }

  const key = `${name.toLowerCase().trim()}|${playerId}`;
  const iterStr = String(iterationId);
  const catalogEntry = {
    name,
    ids_by_iteration: { [iterStr]: playerId },
  };
  if (squadId != null && !Number.isNaN(squadId)) {
    catalogEntry.squad_ids_by_iteration = { [iterStr]: squadId };
  }

  return {
    iteration_ids: [iterationId],
    player_keys: [key],
    player_catalog: { [key]: catalogEntry },
    player_seasons: { [key]: [iterationId] },
    player_positions: { [key]: [position] },
    positions: [position],
    profiles,
    chart_source: "profiles",
  };
}

async function bootstrapScoutingPlayerPage() {
  const params = new URLSearchParams(window.location.search);
  const name = params.get("name") || "Player";
  const titleEl = document.getElementById("scoutingPlayerTitle");
  const metaEl = document.getElementById("scoutingPlayerMeta");
  const loadingEl = document.getElementById("scoutingPlayerLoading");

  if (titleEl) titleEl.textContent = name;
  document.title = `${name} — Impect Scouting`;
  if (metaEl) {
    metaEl.textContent = [params.get("club"), params.get("league"), params.get("season")]
      .filter(Boolean)
      .join(" · ");
  }

  const chartRequest = buildChartRequestFromParams(params);
  if (!chartRequest) {
    if (loadingEl) {
      loadingEl.textContent =
        "Missing chart parameters. Click a player name in the scouting long list to open this page.";
      loadingEl.classList.remove("hidden");
    }
    return;
  }

  const waitForCharts = () =>
    new Promise((resolve, reject) => {
      let attempts = 0;
      const timer = window.setInterval(() => {
        if (window.ImpectPlayerCharts?.load) {
          window.clearInterval(timer);
          resolve();
          return;
        }
        attempts += 1;
        if (attempts > 200) {
          window.clearInterval(timer);
          reject(new Error("Comparison chart scripts failed to load."));
        }
      }, 50);
    });

  const statusEl = document.getElementById("statusBar");
  if (statusEl) {
    statusEl.textContent = "Fetching chart data from Impect… first load can take 60–90 seconds.";
  }

  try {
    await waitForCharts();
    await window.ImpectPlayerCharts.load(chartRequest);
    if (loadingEl) loadingEl.classList.add("hidden");
  } catch (error) {
    if (loadingEl) {
      loadingEl.textContent = error.message || "Could not load charts.";
      loadingEl.classList.remove("hidden");
    }
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrapScoutingPlayerPage);
} else {
  bootstrapScoutingPlayerPage();
}
