(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const deck = $("deck");
  const filmstrip = $("filmstrip");
  const presentBtn = $("presentBtn");
  const presentCount = $("presentCount");
  const presentBar = $("presentBar");
  const meta = $("slideMeta");
  const notesBody = $("notesBody");
  const notesTitle = $("notesTitle");
  const notesBtn = $("notesBtn");
  const jumpSelect = $("jumpSelect");

  let slides = [];
  let index = 0;
  let reportData = null;

  const LEAGUE_PDF = [
    { id: "league-one", name: "League One", file: "League-One" },
    { id: "league-two", name: "League Two", file: "League-Two" },
    { id: "national-league", name: "National League", file: "National-League" },
    { id: "scottish-prem", name: "Scottish Premiership", file: "Scottish-Premiership" },
  ];

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function kindChip(kind) {
    if (!kind || kind === "undisclosed" || kind === "fee" || kind === "other") return "";
    const label = kind === "loan-ended" ? "loan ended" : kind;
    return `<em class="kind kind-${esc(kind)}">${esc(label)}</em>`;
  }

  function playerLine(row) {
    const other = row.other && row.other !== row.fee ? row.other : "";
    const detail = [other, row.fee && row.fee !== other ? row.fee : ""].filter(Boolean).join(" · ");
    const meta = detail ? `<span>${esc(detail)}</span>` : "";
    return `<li><p class="who"><b>${esc(row.player)}</b>${kindChip(row.kind)}</p>${meta}</li>`;
  }

  function badgeImg(url, cls, alt) {
    if (!url) return "";
    return `<img class="${cls}" src="${esc(url)}" alt="${esc(alt || "")}" />`;
  }

  function totals(data) {
    return (data.leagues || []).reduce(
      (acc, league) => {
        acc.clubs += league.teams.length;
        acc.signed += league.signed_count;
        acc.released += league.released_count;
        return acc;
      },
      { clubs: 0, signed: 0, released: 0 },
    );
  }

  function titleSlide(data) {
    const sum = totals(data);
    return `
      <section class="slide slide--open is-active" data-label="Title" data-pdf-role="title" data-notes="Summer 2026 window only. Released is not the same as sold or loaned out.">
        <div class="slide__body">
          ${badgeImg("/standalone/port-vale-badge.png?v=2", "open-badge", "Port Vale")}
          <p class="open-kicker">${esc(data.window)}</p>
          <h2 class="open-title">EFL Transfer Report</h2>
          <p class="open-sub">League One, League Two, National League and Scottish Premiership — who each club signed and released.</p>
          <div class="open-rule" aria-hidden="true"></div>
          <div class="open-stats">
            <span><b>${sum.clubs}</b><em>clubs</em></span>
            <span><b>${sum.signed}</b><em>signed</em></span>
            <span><b>${sum.released}</b><em>released</em></span>
            <span><b>4</b><em>leagues</em></span>
          </div>
        </div>
      </section>
    `;
  }

  function leagueSlide(league) {
    const gridClass = league.id === "scottish-prem" ? "crest-grid crest-grid--scot" : "crest-grid";
    const notes = `${league.name}: ${league.signed_count} signed, ${league.released_count} released across ${league.teams.length} clubs.`;
    const cards = league.teams.map((team) => `
      <button type="button" class="crest-card${team.id === "port-vale" ? " is-vale" : ""}" data-jump-club="${esc(team.id)}">
        ${badgeImg(team.badge_url, "", team.name)}
        <span>${esc(team.name)}</span>
      </button>
    `).join("");
    return `
      <section class="slide slide--league" data-label="${esc(league.name)}" data-notes="${esc(notes)}" data-league="${esc(league.id)}" data-pdf-role="league">
        <div class="slide__bar">
          <div class="slide__bar-left">
            <div>
              <p class="slide__bar-kicker">Summer 2026 window</p>
              <h2 class="slide__bar-name">${esc(league.name)}</h2>
            </div>
          </div>
          <span class="slide__bar-num"></span>
        </div>
        <div class="slide__body">
          <div class="league-stats">
            <span><b>${league.teams.length}</b><em>Clubs</em></span>
            <span><b>${league.signed_count}</b><em>Signed</em></span>
            <span><b>${league.released_count}</b><em>Released</em></span>
          </div>
          <div class="${gridClass}">${cards}</div>
        </div>
      </section>
    `;
  }

  function isLoanOut(row) {
    return row.kind === "loan" || row.kind === "loan-ended";
  }

  function isLoanIn(row) {
    return row.kind === "loan";
  }

  function splitLeft(left) {
    const transferred = [];
    const loans = [];
    for (const row of left || []) {
      if (isLoanOut(row)) loans.push(row);
      else transferred.push(row);
    }
    return { transferred, loans };
  }

  function splitSigned(signed) {
    const perms = [];
    const loans = [];
    for (const row of signed || []) {
      if (isLoanIn(row)) loans.push(row);
      else perms.push(row);
    }
    return { perms, loans };
  }

  function nameList(rows, empty) {
    if (!rows.length) return `<p class="muted">${esc(empty)}</p>`;
    return `<ul class="names">${rows.map(playerLine).join("")}</ul>`;
  }

  function countChip(n, label, cls) {
    return `<span class="count ${cls}"><b>${n}</b><em>${esc(label)}</em></span>`;
  }

  function colBlock(title, cls, rows) {
    return `<div class="col ${cls}"><h3>${esc(title)} <i>${rows.length}</i></h3>${nameList(rows, "None listed.")}</div>`;
  }

  function clubSlide(league, team) {
    const { transferred, loans: loansOut } = splitLeft(team.left);
    const { perms, loans: loansIn } = splitSigned(team.signed);
    const colCounts = [perms.length, loansIn.length, team.released.length, transferred.length, loansOut.length];
    const maxCol = Math.max(...colCounts);
    const total = colCounts.reduce((sum, n) => sum + n, 0);
    let sizeClass = "";
    if (maxCol > 14 || total > 28) sizeClass = " slide--dense";
    else if (maxCol <= 5) sizeClass = " slide--huge";
    else if (maxCol <= 8) sizeClass = " slide--roomy";
    else if (maxCol >= 12) sizeClass = " slide--pack";
    const vale = team.id === "port-vale";
    const notes = `${team.name}: ${perms.length} permanents, ${loansIn.length} loans, ${team.released.length} released, ${transferred.length} transferred, ${loansOut.length} end of loan.`;
    return `
      <section class="slide slide--club${vale ? " slide--vale" : ""}${sizeClass}" data-label="${esc(team.name)}" data-notes="${esc(notes)}" data-club="${esc(team.id)}" data-league="${esc(league.id)}" data-pdf-role="club">
        ${badgeImg(team.badge_url, "slide__watermark", "")}
        <div class="slide__bar">
          <div class="slide__bar-left">
            ${badgeImg(team.badge_url, "slide__bar-badge", team.name)}
            <div>
              <p class="slide__bar-kicker">${esc(league.name)}</p>
              <h2 class="slide__bar-name">${esc(team.name)}</h2>
            </div>
          </div>
          <div class="slide__counts" aria-hidden="true">
            ${countChip(perms.length, "Permanents", "count--in")}
            ${countChip(loansIn.length, "Loans", "count--loan")}
            ${countChip(team.released.length, "Released", "count--out")}
            ${countChip(transferred.length, "Transferred", "count--moved")}
            ${countChip(loansOut.length, "End of loan", "count--loan")}
          </div>
          <span class="slide__bar-num"></span>
        </div>
        <div class="slide__body">
          <div class="cols">
            <section class="board board--in">
              <p class="board__label">Incoming</p>
              <div class="in-cols">
                ${colBlock("Permanents", "col--in", perms)}
                ${colBlock("Loans", "col--loan-in", loansIn)}
              </div>
            </section>
            <section class="board board--out">
              <p class="board__label">Outgoing</p>
              <div class="out-cols">
                ${colBlock("Released", "col--out", team.released)}
                ${colBlock("Transferred", "col--moved", transferred)}
                ${colBlock("End of loan", "col--loan", loansOut)}
              </div>
            </section>
          </div>
        </div>
      </section>
    `;
  }

  function notesSlide(data) {
    const notes = (data.notes || []).map((row) => `<li>${esc(row)}</li>`).join("");
    const sources = (data.sources || []).map((row) => `<li>${esc(row)}</li>`).join("");
    return `
      <section class="slide" data-label="Notes" data-pdf-role="notes" data-notes="Ins split into permanents and loans. Released is only when BBC said released or retired. Transferred is sold or free to another club. End of loan is back to the parent club.">
        <div class="slide__bar">
          <div class="slide__bar-left">
            ${badgeImg("/standalone/port-vale-badge.png?v=2", "slide__bar-badge", "Port Vale")}
            <div>
              <h2 class="slide__bar-name">How to read this</h2>
              <p class="slide__bar-kicker">Sources and limits</p>
            </div>
          </div>
          <span class="slide__bar-num"></span>
        </div>
        <div class="slide__body notes-slide">
          <p class="kicker">Notes</p>
          <ul>${notes}</ul>
          <p class="kicker">Sources</p>
          <ol>${sources}</ol>
          <p class="source">Updated ${esc(data.updated)} · ${esc(data.window)}</p>
        </div>
      </section>
    `;
  }

  function buildDeck(data) {
    const parts = [titleSlide(data)];
    for (const league of data.leagues || []) {
      parts.push(leagueSlide(league));
      for (const team of league.teams) {
        parts.push(clubSlide(league, team));
      }
    }
    parts.push(notesSlide(data));
    deck.innerHTML = parts.join("");
  }

  function presenting() {
    return document.body.classList.contains("is-present");
  }

  function updateChrome() {
    if (!slides.length) return;
    filmstrip.querySelectorAll(".filmstrip__item").forEach((el, n) => {
      el.classList.toggle("is-active", n === index);
    });
    const label = slides[index].dataset.label || "";
    meta.textContent = presenting()
      ? `Slide ${index + 1} of ${slides.length} · ${label}`
      : `${slides.length} slides · P to present · arrows to move · Notes for talking points`;
    presentCount.textContent = `${String(index + 1).padStart(2, "0")} / ${String(slides.length).padStart(2, "0")}`;
    if (presentBar) {
      presentBar.querySelector("i").style.width = `${((index + 1) / slides.length) * 100}%`;
    }
    const prevBtn = $("presentPrev");
    const nextBtn = $("presentNext");
    if (prevBtn) prevBtn.disabled = index <= 0;
    if (nextBtn) nextBtn.disabled = index >= slides.length - 1;
    notesTitle.textContent = `Speaker notes · ${label}`;
    notesBody.textContent = slides[index].dataset.notes || "No notes on this slide.";
    notesBtn.classList.toggle("is-on", document.body.classList.contains("show-notes"));
    if (jumpSelect && String(jumpSelect.value) !== String(index)) {
      jumpSelect.value = String(index);
    }
  }

  function show(i) {
    index = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, n) => s.classList.toggle("is-active", n === index));
    updateChrome();
  }

  function setPresent(on) {
    document.body.classList.toggle("is-present", on);
    presentBtn.textContent = on ? "Exit present" : "Present";
    if (on) {
      try {
        document.documentElement.requestFullscreen();
      } catch (_) {
        /* ignore */
      }
      show(index);
    } else if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
    updateChrome();
  }

  function setExportStatus(msg, kind) {
    const el = $("exportStatus");
    el.textContent = msg || "";
    el.className = "toolbar__export-status" + (kind ? ` toolbar__export-status--${kind}` : "");
  }

  function setExportOverlay(msg) {
    const el = $("export-overlay");
    if (!msg) {
      el.classList.remove("is-active");
      el.textContent = "";
      return;
    }
    el.textContent = msg;
    el.classList.add("is-active");
  }

  function leaguePdfFilename(league) {
    return `Port-Vale-EFL-Transfer-Report-2026-${league.file}.pdf`;
  }

  function slidesForLeague(leagueId) {
    const title = slides.find((s) => s.dataset.pdfRole === "title" || s.classList.contains("slide--open"));
    const notes = slides.find((s) => s.dataset.pdfRole === "notes" || s.dataset.label === "Notes");
    const leagueSlides = slides.filter((s) => s.dataset.league === leagueId);
    return [title, ...leagueSlides, notes].filter(Boolean);
  }

  function closePdfMenu() {
    const menu = $("exportPdfMenu");
    const btn = $("exportPdfMenuBtn");
    if (menu) menu.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function togglePdfMenu() {
    const menu = $("exportPdfMenu");
    const btn = $("exportPdfMenuBtn");
    if (!menu || !btn) return;
    const open = menu.hidden;
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function paintLeagueOpen(league) {
    const slide = deck.querySelector(".slide--open");
    if (!slide || !league) return () => {};
    const html = slide.innerHTML;
    const label = slide.dataset.label;
    const notes = slide.dataset.notes;
    const windowLabel = (reportData && reportData.window) || "Summer 2026";
    slide.innerHTML = `
      <div class="slide__body">
        ${badgeImg("/standalone/port-vale-badge.png?v=2", "open-badge", "Port Vale")}
        <p class="open-kicker">${esc(windowLabel)}</p>
        <h2 class="open-title">${esc(league.name)}</h2>
        <p class="open-sub">Who each club signed and released — summer 2026.</p>
        <div class="open-rule" aria-hidden="true"></div>
        <div class="open-stats">
          <span><b>${league.teams.length}</b><em>clubs</em></span>
          <span><b>${league.signed_count}</b><em>signed</em></span>
          <span><b>${league.released_count}</b><em>released</em></span>
        </div>
      </div>
    `;
    slide.dataset.label = league.name;
    slide.dataset.notes = `${league.name}: ${league.signed_count} signed, ${league.released_count} released across ${league.teams.length} clubs.`;
    return () => {
      slide.innerHTML = html;
      slide.dataset.label = label;
      slide.dataset.notes = notes;
    };
  }

  async function exportToPdf(opts) {
    const leagueId = opts && opts.leagueId;
    const meta = leagueId ? LEAGUE_PDF.find((row) => row.id === leagueId) : null;
    const league = meta && reportData
      ? (reportData.leagues || []).find((row) => row.id === meta.id)
      : null;
    closePdfMenu();
    const wasPresent = presenting();
    if (wasPresent) setPresent(false);
    document.body.classList.add("is-exporting");
    let restoreTitle = null;
    try {
      if (!window.PortValeWysiwygExport) {
        throw new Error("WYSIWYG export helper failed to load — hard refresh and try again.");
      }
      let captureSlides = slides;
      if (meta) {
        restoreTitle = paintLeagueOpen(league || {
          name: meta.name,
          teams: [],
          signed_count: 0,
          released_count: 0,
        });
        captureSlides = slidesForLeague(meta.id);
        if (captureSlides.length < 3) {
          throw new Error(`No slides found for ${meta.name}.`);
        }
      }
      console.info("EFL transfer PDF slides", {
        league: meta ? meta.name : "all",
        count: captureSlides.length,
        labels: captureSlides.map((s) => s.dataset.label),
      });
      const preparing = meta
        ? `Preparing ${meta.name} PDF from on-screen slides…`
        : "Preparing transfer-report PDF from on-screen slides…";
      setExportStatus(preparing, "loading");
      setExportOverlay(meta ? `Building ${meta.name} PDF…` : "Building PDF…");
      captureSlides.forEach((s) => s.classList.add("is-active"));
      const pack = await window.PortValeWysiwygExport.captureSlideHtmlPages({
        slides: captureSlides,
        stripClasses: ["is-leaving", "is-entering"],
        activeClass: "is-active",
        background: "#111111",
        beforeSlide: (i) => {
          slides.forEach((s) => s.classList.remove("is-active"));
          captureSlides.forEach((s, n) => s.classList.toggle("is-active", n === i));
        },
        onProgress: (msg) => {
          setExportStatus(msg, "loading");
          setExportOverlay(msg);
        },
      });
      setExportOverlay("Rendering PDF…");
      const result = await window.PortValeWysiwygExport.downloadPdf({
        ...pack,
        filename: meta ? leaguePdfFilename(meta) : "Port-Vale-EFL-Transfer-Report-2026.pdf",
        documentTitle: meta
          ? `EFL Transfer Report — ${meta.name} — Summer 2026`
          : "EFL Transfer Report — Summer 2026",
        endpoint: "/api/wysiwyg-export-pdf",
      });
      setExportStatus(
        `PDF downloaded (${result.pageCount} slides · ${result.sizeMb} MB).`,
        "success",
      );
    } catch (err) {
      setExportStatus(err.message || "PDF export failed.", "error");
      console.error(err);
    } finally {
      if (restoreTitle) restoreTitle();
      document.body.classList.remove("is-exporting");
      slides.forEach((s, n) => s.classList.toggle("is-active", n === index));
      setExportOverlay("");
      if (wasPresent) setPresent(true);
    }
  }

  function wireDeck() {
    slides = Array.from(deck.querySelectorAll(".slide"));
    filmstrip.innerHTML = "";
    jumpSelect.innerHTML = "";
    const total = slides.length;
    slides.forEach((slide, i) => {
      const n = String(i + 1).padStart(2, "0");
      const num = slide.querySelector(".slide__bar-num");
      if (num) num.textContent = `${n} / ${String(total).padStart(2, "0")}`;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "filmstrip__item" + (slide.classList.contains("slide--league") ? " is-league" : "");
      const leagueMark = { "league-one": "L1", "league-two": "L2", "national-league": "NL", "scottish-prem": "SP" };
      btn.textContent = slide.classList.contains("slide--league")
        ? (leagueMark[slide.dataset.league] || n)
        : n;
      if (i === 0) btn.textContent = "T";
      if (slide.dataset.label === "Notes") btn.textContent = "N";
      btn.title = slide.dataset.label || `Slide ${i + 1}`;
      btn.classList.toggle("is-active", i === 0);
      btn.addEventListener("click", () => {
        show(i);
        if (!presenting()) {
          slide.scrollIntoView({ behavior: "auto", block: "center" });
        }
      });
      filmstrip.appendChild(btn);

      const option = document.createElement("option");
      option.value = String(i);
      option.textContent = `${n} · ${slide.dataset.label || `Slide ${i + 1}`}`;
      jumpSelect.appendChild(option);
    });

    deck.querySelectorAll("[data-jump-club]").forEach((button) => {
      button.addEventListener("click", () => {
        const club = button.getAttribute("data-jump-club");
        const target = slides.findIndex((slide) => slide.dataset.club === club);
        if (target >= 0) {
          show(target);
          if (!presenting()) {
            slides[target].scrollIntoView({ behavior: "auto", block: "center" });
          }
        }
      });
    });
  }

  presentBtn.addEventListener("click", () => setPresent(!presenting()));
  notesBtn.addEventListener("click", () => {
    document.body.classList.toggle("show-notes");
    updateChrome();
  });
  $("exportPdf").addEventListener("click", () => exportToPdf());
  const exportPdfMenuBtn = $("exportPdfMenuBtn");
  const exportPdfMenu = $("exportPdfMenu");
  if (exportPdfMenuBtn && exportPdfMenu) {
    exportPdfMenuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      togglePdfMenu();
    });
    exportPdfMenu.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-league-pdf]");
      if (!btn) return;
      exportToPdf({ leagueId: btn.getAttribute("data-league-pdf") });
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#pdfSplit")) closePdfMenu();
    });
  }
  $("presentPrev").addEventListener("click", (e) => {
    e.stopPropagation();
    show(index - 1);
  });
  $("presentNext").addEventListener("click", (e) => {
    e.stopPropagation();
    show(index + 1);
  });
  jumpSelect.addEventListener("change", () => {
    const next = Number(jumpSelect.value);
    show(next);
    if (!presenting() && slides[next]) {
      slides[next].scrollIntoView({ behavior: "auto", block: "center" });
    }
  });

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && presenting()) setPresent(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === "p" || e.key === "P") {
      setPresent(!presenting());
      return;
    }
    if (e.key === "n" || e.key === "N") {
      document.body.classList.toggle("show-notes");
      updateChrome();
      return;
    }
    if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
      e.preventDefault();
      show(index + 1);
    }
    if (e.key === "ArrowLeft" || e.key === "PageUp" || e.key === "Backspace") {
      e.preventDefault();
      show(index - 1);
    }
    if (e.key === "Home") {
      e.preventDefault();
      show(0);
    }
    if (e.key === "End") {
      e.preventDefault();
      show(slides.length - 1);
    }
    if (e.key === "Escape") {
      closePdfMenu();
      if (presenting()) setPresent(false);
    }
  });

  document.addEventListener("click", (e) => {
    if (!presenting()) return;
    if (e.target.closest(".present-ui, button, a")) return;
    const forward = e.clientX >= window.innerWidth / 2;
    show(forward ? index + 1 : index - 1);
  });

  fetch("/api/efl-transfer-report", { credentials: "same-origin" })
    .then((res) => {
      if (!res.ok) throw new Error("Could not load transfer report.");
      return res.json();
    })
    .then((data) => {
      reportData = data;
      buildDeck(data);
      wireDeck();
      const params = new URLSearchParams(window.location.search);
      const club = params.get("club");
      const start = club
        ? Math.max(0, slides.findIndex((slide) => slide.dataset.club === club))
        : 0;
      show(start === -1 ? 0 : start);
    })
    .catch((err) => {
      deck.innerHTML = `<section class="slide slide--open is-active" data-label="Error"><div class="slide__body"><p class="lede">${esc(err.message)}</p></div></section>`;
      wireDeck();
      show(0);
    });

  window.EflTransferReport = {
    LEAGUE_PDF,
    slidesForLeague,
    leaguePdfFilename,
  };
})();
