(function () {
  "use strict";

  const STORAGE_PREFIX = "hub-origin-v3:";

  const deck = document.getElementById("deck");
  const filmstrip = document.getElementById("filmstrip");
  const presentProgress = document.getElementById("presentProgress");
  const presentBtn = document.getElementById("presentBtn");
  const presentCount = document.getElementById("presentCount");
  const presentChrome = document.getElementById("presentChrome");
  const meta = document.getElementById("slideMeta");
  const notesBody = document.getElementById("notesBody");
  const notesTitle = document.getElementById("notesTitle");
  const notesBtn = document.getElementById("notesBtn");
  const notesPanel = document.getElementById("notesPanel");
  const notesClose = document.getElementById("notesClose");
  const slides = Array.from(deck.querySelectorAll(".slide"));
  const total = slides.length;

  let index = 0;

  function isEditingTarget(el) {
    if (!el || el === document.body) return false;
    if (el.isContentEditable) return true;
    return Boolean(el.closest && el.closest('[contenteditable="true"]'));
  }

  function cssPath(el, root) {
    const parts = [];
    let node = el;
    while (node && node !== root && node !== document.body) {
      let sel = node.tagName.toLowerCase();
      if (node.id) {
        sel += `#${node.id}`;
        parts.unshift(sel);
        break;
      }
      const cls = String(node.className || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean)[0];
      if (cls) sel += `.${cls}`;
      const parent = node.parentElement;
      if (parent) {
        const sameTag = Array.from(parent.children).filter(
          (c) => c.tagName === node.tagName
        );
        if (sameTag.length > 1) {
          sel += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
        }
      }
      parts.unshift(sel);
      node = parent;
    }
    return parts.join(" > ");
  }

  function storageKey(slideIndex, el) {
    const id = el.getAttribute("data-edit-id");
    const suffix = id || cssPath(el, slides[slideIndex]);
    return `${STORAGE_PREFIX}${slideIndex}:${suffix}`;
  }

  function saveEditable(el, slideIndex) {
    try {
      localStorage.setItem(storageKey(slideIndex, el), el.innerHTML);
    } catch (_) {
      /* ignore quota errors */
    }
  }

  function initEditable() {
    slides.forEach((slide, slideIndex) => {
      const editables = slide.querySelectorAll('[contenteditable="true"]');
      let seq = 0;
      editables.forEach((el) => {
        if (!el.dataset.editId) {
          el.dataset.editId = `${slideIndex}-${++seq}`;
        }
        const key = storageKey(slideIndex, el);
        try {
          const saved = localStorage.getItem(key);
          if (saved !== null) {
            el.innerHTML = saved;
          }
        } catch (_) {
          /* ignore */
        }
        const persist = () => saveEditable(el, slideIndex);
        el.addEventListener("input", persist);
        el.addEventListener("blur", persist);
      });
    });
  }

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
    if (presentChrome) {
      presentChrome.hidden = !presenting();
    }
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

  function setNotes(on) {
    document.body.classList.toggle("show-notes", on);
    if (notesPanel) notesPanel.hidden = !on;
    updateChrome();
  }

  presentBtn.addEventListener("click", () => setPresent(!presenting()));
  notesBtn.addEventListener("click", () => setNotes(!document.body.classList.contains("show-notes")));
  notesClose.addEventListener("click", () => setNotes(false));
  document.getElementById("presentPrev").addEventListener("click", () => show(index - 1));
  document.getElementById("presentNext").addEventListener("click", () => show(index + 1));

  document.addEventListener("keydown", (e) => {
    if (isEditingTarget(e.target)) return;
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") {
      e.preventDefault();
      show(index + 1);
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      e.preventDefault();
      show(index - 1);
    } else if (e.key === "p" || e.key === "P") {
      e.preventDefault();
      setPresent(!presenting());
    } else if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      setNotes(!document.body.classList.contains("show-notes"));
    } else if (e.key === "Escape" && presenting()) {
      setPresent(false);
    } else if (e.key === "Home") {
      e.preventDefault();
      show(0);
    } else if (e.key === "End") {
      e.preventDefault();
      show(total - 1);
    }
  });

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && presenting()) {
      document.body.classList.remove("is-present");
      presentBtn.textContent = "Present";
      updateChrome();
    }
  });

  initEditable();
  show(0);
})();
