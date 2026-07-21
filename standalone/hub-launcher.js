/**
 * Shared launcher for Port Vale analysis apps.
 * Ensures the hub (and any sibling server) is running before navigation.
 */
(function initHubLauncher(global) {
  const SCOUTING_SERVER = "http://127.0.0.1:8000";
  const BASE =
    global.location.protocol === "file:"
      ? SCOUTING_SERVER
      : global.location.origin;

  const SERVER_BY_PORT = {
    8000: "hub",
    8002: "pre-match-standalone",
  };

  let overlayEl = null;

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function healthOk(url) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2500), cache: "no-store" });
      return res.ok;
    } catch (_) {
      return false;
    }
  }

  function ensureOverlay() {
    if (overlayEl) return overlayEl;
    overlayEl = document.createElement("div");
    overlayEl.id = "hubLauncherOverlay";
    overlayEl.className = "hub-launcher";
    overlayEl.hidden = true;
    overlayEl.innerHTML = `
      <div class="hub-launcher__panel" role="status" aria-live="polite">
        <div class="hub-launcher__spinner" aria-hidden="true"></div>
        <p class="hub-launcher__title" id="hubLauncherTitle">Starting…</p>
        <p class="hub-launcher__detail" id="hubLauncherDetail">Please wait a few seconds.</p>
      </div>
    `;
    document.body.appendChild(overlayEl);
    return overlayEl;
  }

  function showOverlay(title, detail) {
    const overlay = ensureOverlay();
    overlay.hidden = false;
    document.getElementById("hubLauncherTitle").textContent = title;
    document.getElementById("hubLauncherDetail").textContent = detail || "";
  }

  function hideOverlay() {
    if (overlayEl) overlayEl.hidden = true;
  }

  async function postEnsure(payload) {
    const res = await fetch(`${BASE}/api/server/ensure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(60000),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Could not start server (${res.status})`);
    }
    return data;
  }

  async function ensureHub() {
    if (await healthOk(`${BASE}/health`)) {
      return { started: false };
    }
    showOverlay("Starting analysis hub…", "Port 8000 · this only takes a few seconds.");
    await postEnsure({ server: "hub" });
    const online = await waitForHealth(`${BASE}/health`, 35000);
    if (!online) {
      throw new Error("Analysis hub did not come online. Run ./restart.sh in the project root.");
    }
    return { started: true };
  }

  async function waitForHealth(url, maxMs) {
    const started = Date.now();
    while (Date.now() - started < maxMs) {
      if (await healthOk(url)) return true;
      await wait(400);
    }
    return false;
  }

  function resolveServerForHref(href, explicitServer) {
    if (explicitServer) return explicitServer;
    try {
      const url = new URL(href, BASE);
      if (!["127.0.0.1", "localhost"].includes(url.hostname)) return null;
      const port = Number(url.port || (url.protocol === "https:" ? 443 : 80));
      if (!port || port === 8000) return null;
      return SERVER_BY_PORT[port] || null;
    } catch (_) {
      return null;
    }
  }

  async function ensureServer(serverId, label) {
    showOverlay(`Starting ${label}…`, "Launching the local dashboard server.");
    await postEnsure({ server: serverId });
    // Hub /api/server/ensure already verified health server-side.
    // Don't re-check from the browser (cross-origin CORS can false-fail).
  }

  async function openHref(href, options = {}) {
    const title = options.title || "Opening tool";
    const serverId = resolveServerForHref(href, options.server);
    try {
      await ensureHub();
      if (serverId && serverId !== "hub") {
        await ensureServer(serverId, options.serverLabel || title);
      }
      hideOverlay();
      global.location.href = href;
    } catch (err) {
      hideOverlay();
      throw err;
    }
  }

  async function openApp(app, href) {
    return openHref(href, {
      title: app.title,
      server: app.server,
      serverLabel: app.title,
    });
  }

  function attachLink(link, options = {}) {
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      const href = link.getAttribute("href");
      if (!href) return;
      try {
        await openHref(href.startsWith("http") ? href : `${BASE}${href}`, options);
      } catch (err) {
        window.alert(err.message || String(err));
      }
    });
  }

  global.HubLauncher = {
    BASE,
    ensureHub,
    openApp,
    openHref,
    attachLink,
    resolveServerForHref,
  };
})(window);
