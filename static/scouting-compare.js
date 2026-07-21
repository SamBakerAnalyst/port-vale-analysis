const SCOUTING_COMPARE_STORAGE_PREFIX = "scouting-compare:";
const COMPARE_BATCH_TTL_MS = 30 * 60 * 1000;

function readCompareBatch(batchId) {
  if (!batchId) return null;
  try {
    const raw = localStorage.getItem(`${SCOUTING_COMPARE_STORAGE_PREFIX}${batchId}`);
    if (!raw) return null;
    const batch = JSON.parse(raw);
    if (batch?.createdAt && Date.now() - batch.createdAt > COMPARE_BATCH_TTL_MS) {
      localStorage.removeItem(`${SCOUTING_COMPARE_STORAGE_PREFIX}${batchId}`);
      return null;
    }
    return batch;
  } catch {
    return null;
  }
}

function clearCompareBatch(batchId) {
  if (!batchId) return;
  try {
    localStorage.removeItem(`${SCOUTING_COMPARE_STORAGE_PREFIX}${batchId}`);
  } catch {
    return;
  }
}

async function bootstrapScoutingComparePage() {
  const params = new URLSearchParams(window.location.search);
  const batchId = params.get("batch");
  const batch = readCompareBatch(batchId);

  const titleEl = document.getElementById("scoutingPlayerTitle");
  const metaEl = document.getElementById("scoutingPlayerMeta");
  const loadingEl = document.getElementById("scoutingPlayerLoading");

  if (!batch?.chartRequest) {
    if (titleEl) titleEl.textContent = "Player comparison";
    if (loadingEl) {
      loadingEl.textContent =
        "Comparison data missing or expired. Go back to the scouting long list, select players, and click Send to comparison again.";
      loadingEl.classList.remove("hidden");
    }
    return;
  }

  const playerCount = batch.chartRequest.player_keys?.length || 0;
  const title = batch.title || `${playerCount} player${playerCount === 1 ? "" : "s"} compared`;
  document.title = `${title} — Impect Scouting`;
  if (titleEl) titleEl.textContent = title;
  if (metaEl) metaEl.textContent = batch.meta || "";

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
    statusEl.textContent =
      playerCount > 1
        ? `Generating comparison for ${playerCount} players… this can take up to 2 minutes.`
        : "Fetching chart data from Impect… first load can take 60–90 seconds.";
  }
  if (loadingEl) {
    loadingEl.textContent =
      playerCount > 1
        ? `Loading comparison charts for ${playerCount} players… this may take 1–2 minutes.`
        : loadingEl.textContent;
  }

  try {
    await waitForCharts();
    await window.ImpectPlayerCharts.load(batch.chartRequest);
    clearCompareBatch(batchId);
    if (loadingEl) loadingEl.classList.add("hidden");
  } catch (error) {
    if (loadingEl) {
      loadingEl.textContent = error.message || "Could not load comparison charts.";
      loadingEl.classList.remove("hidden");
    }
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrapScoutingComparePage);
} else {
  bootstrapScoutingComparePage();
}
