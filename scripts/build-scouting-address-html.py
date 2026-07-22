#!/usr/bin/env python3
"""Build standalone/scouting-address.html — JS at end of body, after Leaflet."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "standalone/scouting-address.css").read_text(encoding="utf-8")
JS = (ROOT / "standalone/scouting-address.js").read_text(encoding="utf-8")
BUILD = "webpage-v12"

HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
  <title>Scouting Address Tool</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
  <link rel="stylesheet" href="/static/fixture-planner.css?v=13" />
  <link rel="stylesheet" href="/static/scout-ops.css?v=3" />
  <style>
{CSS}
  </style>
</head>
<body>
  <div class="sa-app">
    <header class="so-toolbar">
      <div class="so-toolbar__left">
        <p class="so-toolbar__eyebrow">Scouts · <a href="/?section=scouts">← Scouts</a> · <a href="/">All apps</a></p>
        <h1 class="so-toolbar__title">Scouting Address Tool</h1>
        <p class="so-toolbar__subtitle">UK stadium map — enter a scout's address to see which grounds are reachable within an hour's drive</p>
      </div>
      <div class="so-toolbar__right">
        <nav class="so-toolbar__nav" aria-label="Related pages">
          <a href="/fixture-planner" class="fp-btn fp-btn--ghost">Fixture planner</a>
          <a href="/scout-summary" class="fp-btn fp-btn--ghost">Scout summary</a>
          <a href="/scouts-calendar" class="fp-btn fp-btn--ghost">Scouts calendar</a>
        </nav>
      </div>
    </header>

    <section class="sa-controls card">
      <div class="sa-controls__row">
        <div class="sa-controls__group sa-controls__group--grow">
          <span class="fp-controls__label">Scout address</span>
          <div class="sa-address-row">
            <input type="text" id="addressInput" class="sa-address-input" placeholder="Postcode or address — e.g. NN4 5BF, ST4 4EG, 19 Hamil Road Stoke" autocomplete="street-address" />
            <button type="button" class="fp-btn fp-btn--primary" id="searchBtn">Find reachable games</button>
          </div>
        </div>
        <div class="sa-controls__group">
          <span class="fp-controls__label">Max drive time</span>
          <select id="maxMinutes" class="fp-staff-filter" aria-label="Maximum drive time">
            <option value="45">45 minutes</option>
            <option value="60" selected>60 minutes</option>
            <option value="75">75 minutes</option>
            <option value="90">90 minutes</option>
          </select>
        </div>
        <div class="sa-controls__group">
          <span class="fp-controls__label">Max distance</span>
          <select id="maxMiles" class="fp-staff-filter" aria-label="Maximum drive distance">
            <option value="20">20 miles</option>
            <option value="30">30 miles</option>
            <option value="36" selected>36 miles</option>
            <option value="45">45 miles</option>
            <option value="60">60 miles</option>
            <option value="75">75 miles</option>
            <option value="90">90 miles</option>
          </select>
        </div>
      </div>
      <div class="sa-controls__row">
        <div class="sa-controls__group sa-controls__group--grow">
          <span class="fp-controls__label">Leagues</span>
          <div id="leagueToggle" class="fp-league-toggle" role="group" aria-label="Leagues"></div>
        </div>
        <div class="sa-controls__group">
          <span class="fp-controls__label">Season</span>
          <div id="seasonToggle" class="fp-season-toggle" role="group" aria-label="Season"></div>
        </div>
      </div>
    </section>

    <div id="statusBanner" class="fp-status hidden" role="status"></div>

    <section class="sa-layout">
      <div class="sa-map-panel card">
        <div id="map" class="sa-map" aria-label="UK stadium map"></div>
        <div class="sa-legend" id="mapLegend"></div>
      </div>

      <aside class="sa-side-panel">
        <section class="sa-summary card" id="summaryPanel" aria-live="polite">
          <p class="sa-summary__empty">Enter a scout address to highlight reachable stadiums and upcoming fixtures.</p>
        </section>
        <section class="sa-fixtures card" id="dayPlansPanel" aria-live="polite">
          <h2 class="sa-panel-title">Day plans</h2>
          <p class="sa-panel-hint">Same-day double headers — assumes you can leave the first game from half-time onwards. Shows the latest minute you can stay.</p>
          <div id="dayPlansList" class="sa-day-plans-list">
            <p class="sa-summary__empty">Enter your address to see feasible two-game days.</p>
          </div>
        </section>
        <section class="sa-fixtures card" id="fixturesPanel" aria-live="polite">
          <h2 class="sa-panel-title">Reachable fixtures</h2>
          <div id="fixturesList" class="sa-fixtures-list">
            <p class="sa-summary__empty">Fixtures at reachable grounds will appear here.</p>
          </div>
        </section>
      </aside>
    </section>

    <footer id="statusBar" class="fp-footer">Loading stadium data…</footer>
    <p id="buildStamp" style="margin:.35rem 0 0;font-size:.75rem;color:#8b9bb0;text-align:center">Build: {BUILD}</p>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script>
{JS}
  </script>
</body>
</html>
"""

out = ROOT / "standalone/scouting-address.html"
out.write_text(HTML, encoding="utf-8")
print(f"Wrote {out} (build {BUILD}, {len(HTML):,} bytes)")
