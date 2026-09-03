(function () {
  "use strict";

  const deck = document.getElementById("deck");
  const filmstrip = document.getElementById("filmstrip");
  const presentProgress = document.getElementById("presentProgress");
  const presentBtn = document.getElementById("presentBtn");
  const presentCount = document.getElementById("presentCount");
  const meta = document.getElementById("slideMeta");
  const notesBody = document.getElementById("notesBody");
  const notesTitle = document.getElementById("notesTitle");
  const notesBtn = document.getElementById("notesBtn");
  const slides = Array.from(deck.querySelectorAll(".slide"));
  const total = slides.length;

  let index = 0;

  slides.forEach((slide, i) => {
    const n = String(i + 1).padStart(2, "0");
    const num = slide.querySelector(".slide__bar-num");
    if (num) num.textContent = `${n} / ${String(total).padStart(2, "0")}`;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "filmstrip__item" + (i === 0 ? " is-active" : "");
    btn.textContent = n;
    btn.title = slide.dataset.label || `Slide ${i + 1}`;
    btn.addEventListener("click", () => {
      show(i);
      if (!document.body.classList.contains("is-present")) {
        slide.scrollIntoView({ behavior: "auto", block: "center" });
      }
    });
    filmstrip.appendChild(btn);

    const dot = document.createElement("button");
    dot.type = "button";
    dot.setAttribute("aria-label", `Go to slide ${i + 1}`);
    dot.addEventListener("click", (e) => {
      e.stopPropagation();
      show(i);
    });
    presentProgress.appendChild(dot);
  });

  function presenting() {
    return document.body.classList.contains("is-present");
  }

  function updateChrome() {
    filmstrip.querySelectorAll(".filmstrip__item").forEach((el, n) => {
      el.classList.toggle("is-active", n === index);
    });
    presentProgress.querySelectorAll("button").forEach((el, n) => {
      el.classList.toggle("is-active", n === index);
    });
    const label = slides[index].dataset.label || "";
    meta.textContent = presenting()
      ? `Slide ${index + 1} of ${total} · ${label}`
      : `${total} slides · P to present · arrows to move · Notes for talking points`;
    presentCount.textContent = `${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
    const prevBtn = document.getElementById("presentPrev");
    const nextBtn = document.getElementById("presentNext");
    if (prevBtn) prevBtn.disabled = index <= 0;
    if (nextBtn) nextBtn.disabled = index >= total - 1;
    notesTitle.textContent = `Speaker notes · ${label}`;
    notesBody.textContent = slides[index].dataset.notes || "No notes on this slide.";
    notesBtn.classList.toggle("is-on", document.body.classList.contains("show-notes"));
  }

  function show(i) {
    index = Math.max(0, Math.min(total - 1, i));
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
    const el = document.getElementById("exportStatus");
    el.textContent = msg || "";
    el.className = "toolbar__export-status" + (kind ? ` toolbar__export-status--${kind}` : "");
  }

  function setExportOverlay(msg) {
    const el = document.getElementById("export-overlay");
    if (!msg) {
      el.classList.remove("is-active");
      el.textContent = "";
      return;
    }
    el.textContent = msg;
    el.classList.add("is-active");
  }

  async function exportToPdf() {
    const wasPresent = presenting();
    if (wasPresent) setPresent(false);
    document.body.classList.add("is-exporting");
    try {
      if (!window.PortValeWysiwygExport) {
        throw new Error("WYSIWYG export helper failed to load — hard refresh and try again.");
      }
      setExportStatus("Preparing board PDF from on-screen slides…", "loading");
      setExportOverlay("Building board PDF…");
      slides.forEach((s) => s.classList.add("is-active"));
      const pack = await window.PortValeWysiwygExport.captureSlideHtmlPages({
        slides,
        stripClasses: ["is-leaving", "is-entering"],
        activeClass: "is-active",
        background: "#111111",
        beforeSlide: (i) => {
          slides.forEach((s, n) => s.classList.toggle("is-active", n === i));
        },
        onProgress: (msg) => {
          setExportStatus(msg, "loading");
          setExportOverlay(msg);
        },
      });
      setExportOverlay("Rendering PDF…");
      const result = await window.PortValeWysiwygExport.downloadPdf({
        ...pack,
        filename: "Port-Vale-Analysis-Hub-Board-Briefing.pdf",
        documentTitle: "Port Vale Analysis Hub — Board briefing",
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
      document.body.classList.remove("is-exporting");
      slides.forEach((s, n) => s.classList.toggle("is-active", n === index));
      setExportOverlay("");
      if (wasPresent) setPresent(true);
    }
  }

  presentBtn.addEventListener("click", () => setPresent(!presenting()));
  notesBtn.addEventListener("click", () => {
    document.body.classList.toggle("show-notes");
    updateChrome();
  });
  document.getElementById("exportPdf").addEventListener("click", () => exportToPdf());
  document.getElementById("presentPrev").addEventListener("click", (e) => {
    e.stopPropagation();
    show(index - 1);
  });
  document.getElementById("presentNext").addEventListener("click", (e) => {
    e.stopPropagation();
    show(index + 1);
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
      show(total - 1);
    }
    if (e.key === "Escape" && presenting()) setPresent(false);
  });

  document.addEventListener("click", (e) => {
    if (!presenting()) return;
    if (e.target.closest(".present-ui, button, a")) return;
    const forward = e.clientX >= window.innerWidth / 2;
    show(forward ? index + 1 : index - 1);
  });

  show(0);
})();
