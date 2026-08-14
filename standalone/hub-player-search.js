/**
 * Hub header — global player search → player dossier page.
 */
(function initHubPlayerSearch() {
  const input = document.getElementById("hubPlayerSearch");
  const results = document.getElementById("hubPlayerResults");
  const wrap = document.getElementById("hubPlayerSearchWrap");
  if (!input || !results) return;

  const MIN_CHARS = 3;
  const DEBOUNCE_MS = 280;
  let timer = null;
  let abort = null;
  let requestId = 0;
  let items = [];
  let activeIndex = -1;

  function hideResults() {
    results.classList.add("hidden");
    results.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    items = [];
    activeIndex = -1;
  }

  function playerMeta(player) {
    const bits = [
      player.club,
      player.league,
      player.age != null ? `Age ${player.age}` : null,
    ].filter(Boolean);
    return bits.join(" · ") || "Open player dossier";
  }

  function navigateTo(player) {
    const id = player.impect_player_id;
    if (!id) return;
    window.location.href = `/player/${id}`;
  }

  function renderResults(players, message) {
    if (!players.length) {
      results.innerHTML = `<p class="hub-search__empty">${message || "No players found."}</p>`;
      results.classList.remove("hidden");
      input.setAttribute("aria-expanded", "true");
      items = [];
      activeIndex = -1;
      return;
    }

    items = players.slice(0, 12);
    results.innerHTML = items
      .map(
        (player, index) => `<div class="hub-search__result${index === activeIndex ? " is-active" : ""}" data-index="${index}" role="option">
          <button type="button" class="hub-search__result-main">
            <strong>${player.name || "Unknown"}</strong>
            <span>${playerMeta(player)}</span>
          </button>
          <button type="button" class="hub-search__pipeline" data-pipeline="${index}">Add to pipeline</button>
        </div>`
      )
      .join("");
    results.classList.remove("hidden");
    input.setAttribute("aria-expanded", "true");

    results.querySelectorAll(".hub-search__result-main").forEach((btn) => {
      btn.addEventListener("mousedown", (event) => {
        event.preventDefault();
        const player = items[Number(btn.closest(".hub-search__result").dataset.index)];
        if (player) navigateTo(player);
      });
    });
    results.querySelectorAll("[data-pipeline]").forEach((btn) => {
      btn.addEventListener("mousedown", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const player = items[Number(btn.dataset.pipeline)];
        if (!player) return;
        btn.disabled = true;
        btn.textContent = "Adding…";
        try {
          const res = await fetch("/api/player-pipelines/targets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              player_id: player.impect_player_id,
              name: player.name || "",
              club: player.club || "",
              league: player.league || "",
              position: player.primary_position || "",
              position_label: player.primary_position_label || "",
              age: player.age ?? null,
              photo_url: player.photo_url || "",
              stage: "data_identified",
            }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
          btn.textContent = data.created ? "Added" : "On board";
          btn.classList.add("is-done");
        } catch (_err) {
          btn.disabled = false;
          btn.textContent = "Add to pipeline";
        }
      });
    });
  }

  function setActive(index) {
    if (!items.length) return;
    activeIndex = Math.max(0, Math.min(index, items.length - 1));
    results.querySelectorAll(".hub-search__result").forEach((btn, i) => {
      btn.classList.toggle("is-active", i === activeIndex);
    });
  }

  async function searchPlayers(query) {
    if (abort) abort.abort();
    abort = new AbortController();
    const current = ++requestId;

    try {
      const res = await fetch("/api/players", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ search: query }),
        signal: abort.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (current !== requestId || input.value.trim() !== query) return;
      if (!res.ok) throw new Error(data.detail || `Search failed (${res.status})`);
      renderResults(data.players || [], data.message);
    } catch (err) {
      if (err.name === "AbortError") return;
      if (current !== requestId) return;
      results.innerHTML = `<p class="hub-search__empty">${err.message || "Search unavailable."}</p>`;
      results.classList.remove("hidden");
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < MIN_CHARS) {
      hideResults();
      return;
    }
    timer = setTimeout(() => searchPlayers(query), DEBOUNCE_MS);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideResults();
      input.blur();
      return;
    }
    if (!items.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(activeIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(activeIndex <= 0 ? items.length - 1 : activeIndex - 1);
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      navigateTo(items[activeIndex]);
    }
  });

  document.addEventListener("click", (event) => {
    if (!wrap.contains(event.target)) hideResults();
  });
})();
