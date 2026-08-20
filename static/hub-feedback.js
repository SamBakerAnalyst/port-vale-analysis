/**
 * Shared Suggest / bug widget for hub + every standalone tool.
 * Posts to POST /api/feedback with page path + optional screenshots.
 */
(function () {
  if (window.__HUB_FEEDBACK_BOOTED__) return;
  window.__HUB_FEEDBACK_BOOTED__ = true;

  const path = window.location.pathname || "";
  if (path === "/login" || path.endsWith("/login.html")) return;

  const BASE =
    window.location.protocol === "http:" || window.location.protocol === "https:"
      ? window.location.origin
      : "";

  function ensureCss() {
    if (document.querySelector('link[data-hub-feedback-css]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/hub-feedback.css?v=1";
    link.setAttribute("data-hub-feedback-css", "1");
    document.head.appendChild(link);
  }

  function ensureDom() {
    if (!document.getElementById("hubFeedbackFab")) {
      const fab = document.createElement("button");
      fab.type = "button";
      fab.id = "hubFeedbackFab";
      fab.className = "hub-feedback-fab";
      fab.textContent = "Suggest";
      fab.title = "Send a suggestion or bug report to analysis";
      document.body.appendChild(fab);
    }

    if (!document.getElementById("hubFeedbackModal")) {
      const modal = document.createElement("div");
      modal.className = "hub-feedback-modal";
      modal.id = "hubFeedbackModal";
      modal.hidden = true;
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      modal.setAttribute("aria-labelledby", "hubFeedbackModalTitle");
      modal.innerHTML = `
        <div class="hub-feedback-modal__panel">
          <h2 class="hub-feedback-modal__title" id="hubFeedbackModalTitle">Suggestion or bug report</h2>
          <p class="hub-feedback-modal__hint">Describe what happened or what you’d like improved. This goes straight to the analysis team.</p>
          <textarea class="hub-feedback-modal__textarea" id="hubFeedbackMessage" placeholder="What’s working, what’s broken, or what you’d change…"></textarea>
          <div class="hub-feedback-modal__shots">
            <span class="hub-feedback-modal__shots-label">Screenshots (optional)</span>
            <p class="hub-feedback-modal__shots-hint">Attach up to 3 images, or paste with Cmd+V / Ctrl+V.</p>
            <div class="hub-feedback-modal__shot-actions">
              <button type="button" class="hub-feedback-modal__shot-btn" id="hubFeedbackAttachBtn">Add screenshot</button>
              <input class="hub-feedback-modal__shot-input" id="hubFeedbackFileInput" type="file" accept="image/png,image/jpeg,image/webp" multiple />
            </div>
            <div class="hub-feedback-modal__shot-grid" id="hubFeedbackShotGrid"></div>
          </div>
          <p class="hub-feedback-modal__error" id="hubFeedbackError" role="alert"></p>
          <p class="hub-feedback-modal__success" id="hubFeedbackSuccess" role="status">Thanks — we’ve logged that and will take a look.</p>
          <div class="hub-feedback-modal__actions">
            <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackCancelBtn">Cancel</button>
            <button type="button" class="hub-feedback-modal__btn hub-feedback-modal__btn--primary" id="hubFeedbackSubmitBtn">Send</button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
    }
  }

  function boot() {
    ensureCss();
    ensureDom();

    const modal = document.getElementById("hubFeedbackModal");
    const fab = document.getElementById("hubFeedbackFab");
    const legacyOpen = document.getElementById("feedbackOpenBtn");
    const cancelBtn = document.getElementById("hubFeedbackCancelBtn");
    const submitBtn = document.getElementById("hubFeedbackSubmitBtn");
    const messageEl = document.getElementById("hubFeedbackMessage");
    const errorEl = document.getElementById("hubFeedbackError");
    const successEl = document.getElementById("hubFeedbackSuccess");
    const attachBtn = document.getElementById("hubFeedbackAttachBtn");
    const fileInput = document.getElementById("hubFeedbackFileInput");
    const shotGrid = document.getElementById("hubFeedbackShotGrid");
    let screenshots = [];

    function showError(msg) {
      errorEl.textContent = msg;
      errorEl.classList.add("hub-feedback-modal__error--visible");
      successEl.classList.remove("hub-feedback-modal__success--visible");
    }
    function showSuccess() {
      errorEl.classList.remove("hub-feedback-modal__error--visible");
      successEl.classList.add("hub-feedback-modal__success--visible");
    }
    function renderShots() {
      shotGrid.innerHTML = "";
      screenshots.forEach((dataUrl, index) => {
        const wrap = document.createElement("div");
        wrap.className = "hub-feedback-modal__shot";
        wrap.innerHTML = `<img src="${dataUrl}" alt="" /><button type="button" class="hub-feedback-modal__shot-remove" aria-label="Remove screenshot">×</button>`;
        wrap.querySelector(".hub-feedback-modal__shot-remove").addEventListener("click", () => {
          screenshots.splice(index, 1);
          renderShots();
        });
        shotGrid.appendChild(wrap);
      });
    }
    function addScreenshotFiles(files) {
      files.slice(0, 3 - screenshots.length).forEach((file) => {
        const reader = new FileReader();
        reader.onload = () => {
          if (screenshots.length >= 3) return;
          screenshots.push(reader.result);
          renderShots();
        };
        reader.readAsDataURL(file);
      });
    }
    function resetModal() {
      messageEl.value = "";
      screenshots = [];
      renderShots();
      errorEl.classList.remove("hub-feedback-modal__error--visible");
      successEl.classList.remove("hub-feedback-modal__success--visible");
      submitBtn.disabled = false;
      submitBtn.textContent = "Send";
    }
    function openModal() {
      resetModal();
      modal.hidden = false;
      messageEl.focus();
    }

    fab.addEventListener("click", openModal);
    if (legacyOpen) legacyOpen.addEventListener("click", openModal);
    cancelBtn.addEventListener("click", () => {
      modal.hidden = true;
    });
    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      addScreenshotFiles(Array.from(fileInput.files || []));
      fileInput.value = "";
    });
    modal.addEventListener("click", (event) => {
      if (event.target === modal) modal.hidden = true;
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) modal.hidden = true;
    });
    modal.addEventListener("paste", (event) => {
      if (modal.hidden) return;
      const items = Array.from(event.clipboardData?.items || []);
      const imageItems = items.filter((item) => item.type.startsWith("image/"));
      if (!imageItems.length) return;
      event.preventDefault();
      addScreenshotFiles(imageItems.map((item) => item.getAsFile()).filter(Boolean));
    });

    submitBtn.addEventListener("click", async () => {
      const message = messageEl.value.trim();
      if (message.length < 3) {
        showError("Please add a few words so we know what to look at.");
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = "Sending…";
      const pageTitle = document.title || "";
      try {
        const res = await fetch(`${BASE}/api/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            message,
            page: `${window.location.pathname}${window.location.search}${pageTitle ? ` · ${pageTitle}` : ""}`,
            screenshots,
          }),
        });
        if (!res.ok) {
          showError("Could not send — try again in a moment.");
          submitBtn.disabled = false;
          submitBtn.textContent = "Send";
          return;
        }
        showSuccess();
        setTimeout(() => {
          modal.hidden = true;
        }, 1400);
      } catch (_) {
        showError("Could not reach the server.");
        submitBtn.disabled = false;
        submitBtn.textContent = "Send";
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
