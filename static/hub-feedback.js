/**
 * Shared Suggest / bug widget for hub + every standalone tool.
 * Posts to POST /api/feedback with page path + optional screenshots.
 * On the hub home, analysis can flick through everyone's tickets, edit, and close them.
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

  function isHubHome() {
    return path === "/" || path === "/hub" || path.endsWith("/hub.html") || path.endsWith("/index.html");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function relativeTime(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    if (!Number.isFinite(then)) return "";
    const seconds = Math.round((Date.now() - then) / 1000);
    if (seconds < 60) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 14) return `${days}d ago`;
    return new Date(iso).toLocaleDateString();
  }

  function ensureCss() {
    if (document.querySelector('link[data-hub-feedback-css]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/hub-feedback.css?v=3";
    link.setAttribute("data-hub-feedback-css", "1");
    document.head.appendChild(link);
  }

  function ensureDom() {
    if (!document.getElementById("hubFeedbackFab")) {
      const fab = document.createElement("button");
      fab.type = "button";
      fab.id = "hubFeedbackFab";
      fab.className = "hub-feedback-fab";
      fab.innerHTML = `Suggest <span class="hub-feedback-fab__count" id="hubFeedbackFabCount">0</span>`;
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

    if (!document.getElementById("hubFeedbackInbox")) {
      const inbox = document.createElement("div");
      inbox.className = "hub-feedback-modal";
      inbox.id = "hubFeedbackInbox";
      inbox.hidden = true;
      inbox.setAttribute("role", "dialog");
      inbox.setAttribute("aria-modal", "true");
      inbox.setAttribute("aria-labelledby", "hubFeedbackInboxTitle");
      inbox.innerHTML = `
        <div class="hub-feedback-modal__panel hub-feedback-inbox__panel">
          <div class="hub-feedback-inbox__top">
            <div>
              <h2 class="hub-feedback-modal__title" id="hubFeedbackInboxTitle">Everyone’s suggestions</h2>
              <div class="hub-feedback-inbox__filters" role="tablist">
                <button type="button" class="hub-feedback-inbox__filter is-active" data-filter="open">Open</button>
                <button type="button" class="hub-feedback-inbox__filter" data-filter="closed">Closed</button>
                <button type="button" class="hub-feedback-inbox__filter" data-filter="all">All</button>
              </div>
            </div>
            <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackInboxCloseBtn">Close</button>
          </div>
          <p class="hub-feedback-inbox__empty" id="hubFeedbackInboxEmpty">No open suggestions.</p>
          <div class="hub-feedback-inbox__ticket" id="hubFeedbackInboxTicket" hidden>
            <div class="hub-feedback-inbox__nav">
              <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackPrevBtn">Previous</button>
              <span class="hub-feedback-inbox__pos" id="hubFeedbackInboxPos"></span>
              <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackNextBtn">Next</button>
            </div>
            <p class="hub-feedback-inbox__meta">
              <span class="hub-feedback-inbox__status" id="hubFeedbackTicketStatus"></span>
              <span id="hubFeedbackTicketWho"></span>
              <span id="hubFeedbackTicketWhen"></span>
              <span id="hubFeedbackTicketPage"></span>
            </p>
            <label class="hub-feedback-inbox__label" for="hubFeedbackTicketMessage">Suggestion</label>
            <textarea class="hub-feedback-modal__textarea" id="hubFeedbackTicketMessage"></textarea>
            <div class="hub-feedback-modal__shot-grid" id="hubFeedbackTicketShots"></div>
            <label class="hub-feedback-inbox__label" for="hubFeedbackTicketResolution">What we changed</label>
            <textarea class="hub-feedback-modal__textarea" id="hubFeedbackTicketResolution" placeholder="They’ll see this the next time they open the hub."></textarea>
            <p class="hub-feedback-modal__error" id="hubFeedbackInboxError" role="alert"></p>
            <p class="hub-feedback-modal__success" id="hubFeedbackInboxSuccess" role="status"></p>
            <div class="hub-feedback-modal__actions">
              <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackNewBtn">New suggestion</button>
              <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackSaveBtn">Save</button>
              <button type="button" class="hub-feedback-modal__btn hub-feedback-modal__btn--primary" id="hubFeedbackCloseTicketBtn">Close ticket</button>
              <button type="button" class="hub-feedback-modal__btn" id="hubFeedbackReopenBtn" hidden>Reopen</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(inbox);
    }
  }

  function boot() {
    ensureCss();
    ensureDom();

    const modal = document.getElementById("hubFeedbackModal");
    const fab = document.getElementById("hubFeedbackFab");
    const fabCount = document.getElementById("hubFeedbackFabCount");
    const legacyOpen = document.getElementById("feedbackOpenBtn");
    const cancelBtn = document.getElementById("hubFeedbackCancelBtn");
    const submitBtn = document.getElementById("hubFeedbackSubmitBtn");
    const messageEl = document.getElementById("hubFeedbackMessage");
    const errorEl = document.getElementById("hubFeedbackError");
    const successEl = document.getElementById("hubFeedbackSuccess");
    const attachBtn = document.getElementById("hubFeedbackAttachBtn");
    const fileInput = document.getElementById("hubFeedbackFileInput");
    const shotGrid = document.getElementById("hubFeedbackShotGrid");
    const inbox = document.getElementById("hubFeedbackInbox");
    const inboxEmpty = document.getElementById("hubFeedbackInboxEmpty");
    const inboxTicket = document.getElementById("hubFeedbackInboxTicket");
    const inboxError = document.getElementById("hubFeedbackInboxError");
    const inboxSuccess = document.getElementById("hubFeedbackInboxSuccess");
    const ticketMessage = document.getElementById("hubFeedbackTicketMessage");
    const ticketResolution = document.getElementById("hubFeedbackTicketResolution");
    const ticketShots = document.getElementById("hubFeedbackTicketShots");
    let screenshots = [];
    let canManage = false;
    let allTickets = [];
    let filter = "open";
    let index = 0;
    let noticeQueue = [];

    function showError(msg) {
      errorEl.textContent = msg;
      errorEl.classList.add("hub-feedback-modal__error--visible");
      successEl.classList.remove("hub-feedback-modal__success--visible");
    }
    function showSuccess() {
      errorEl.classList.remove("hub-feedback-modal__error--visible");
      successEl.classList.add("hub-feedback-modal__success--visible");
    }
    function showInboxError(msg) {
      inboxError.textContent = msg || "";
      inboxError.classList.toggle("hub-feedback-modal__error--visible", Boolean(msg));
      inboxSuccess.classList.remove("hub-feedback-modal__success--visible");
    }
    function showInboxSuccess(msg) {
      inboxSuccess.textContent = msg || "";
      inboxSuccess.classList.toggle("hub-feedback-modal__success--visible", Boolean(msg));
      inboxError.classList.remove("hub-feedback-modal__error--visible");
    }
    function renderShots() {
      shotGrid.innerHTML = "";
      screenshots.forEach((dataUrl, shotIndex) => {
        const wrap = document.createElement("div");
        wrap.className = "hub-feedback-modal__shot";
        wrap.innerHTML = `<img src="${dataUrl}" alt="" /><button type="button" class="hub-feedback-modal__shot-remove" aria-label="Remove screenshot">×</button>`;
        wrap.querySelector(".hub-feedback-modal__shot-remove").addEventListener("click", () => {
          screenshots.splice(shotIndex, 1);
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
      inbox.hidden = true;
      resetModal();
      modal.hidden = false;
      messageEl.focus();
    }
    function closeModal() {
      modal.hidden = true;
    }

    function visibleTickets() {
      if (filter === "open") return allTickets.filter((row) => row.status !== "closed");
      if (filter === "closed") return allTickets.filter((row) => row.status === "closed");
      return allTickets.slice();
    }

    function currentTicket() {
      return visibleTickets()[index] || null;
    }

    function setFabCount(count) {
      const n = Number(count) || 0;
      fab.dataset.openCount = String(n);
      if (fabCount) fabCount.textContent = String(n);
      if (canManage && isHubHome()) {
        fab.title = n
          ? `${n} open suggestion${n === 1 ? "" : "s"} — click to review`
          : "Review everyone’s suggestions";
      }
    }

    function renderTicket() {
      const rows = visibleTickets();
      const ticket = rows[index] || null;
      showInboxError("");
      showInboxSuccess("");
      if (!ticket) {
        inboxTicket.hidden = true;
        inboxEmpty.hidden = false;
        inboxEmpty.textContent =
          filter === "closed"
            ? "No closed tickets yet."
            : filter === "all"
              ? "Nobody has sent a suggestion yet."
              : "No open suggestions — everyone’s clear.";
        return;
      }
      inboxEmpty.hidden = true;
      inboxTicket.hidden = false;
      document.getElementById("hubFeedbackInboxPos").textContent = `${index + 1} of ${rows.length}`;
      document.getElementById("hubFeedbackPrevBtn").disabled = index <= 0;
      document.getElementById("hubFeedbackNextBtn").disabled = index >= rows.length - 1;
      const statusEl = document.getElementById("hubFeedbackTicketStatus");
      const closed = ticket.status === "closed";
      statusEl.textContent = closed ? "Closed" : "Open";
      statusEl.classList.toggle("is-closed", closed);
      const who = ticket.display_name || ticket.username || "Unsigned";
      document.getElementById("hubFeedbackTicketWho").textContent = who;
      document.getElementById("hubFeedbackTicketWhen").textContent = relativeTime(ticket.at);
      document.getElementById("hubFeedbackTicketPage").textContent = ticket.page || "Hub";
      ticketMessage.value = ticket.message || "";
      ticketResolution.value = ticket.resolution || "";
      ticketShots.innerHTML = "";
      (ticket.screenshots || []).forEach((src) => {
        const wrap = document.createElement("a");
        wrap.className = "hub-feedback-modal__shot";
        wrap.href = src;
        wrap.target = "_blank";
        wrap.rel = "noopener";
        wrap.innerHTML = `<img src="${escapeHtml(src)}" alt="Screenshot" />`;
        ticketShots.appendChild(wrap);
      });
      document.getElementById("hubFeedbackCloseTicketBtn").hidden = closed;
      document.getElementById("hubFeedbackReopenBtn").hidden = !closed;
      document.getElementById("hubFeedbackSaveBtn").hidden = false;
    }

    async function loadTickets() {
      const res = await fetch(`${BASE}/api/feedback`, { credentials: "same-origin" });
      if (!res.ok) throw new Error("Could not load suggestions.");
      const data = await res.json();
      canManage = Boolean(data.can_manage);
      allTickets = Array.isArray(data.tickets) ? data.tickets : [];
      setFabCount(data.open_count);
      const rows = visibleTickets();
      if (index >= rows.length) index = Math.max(0, rows.length - 1);
      return data;
    }

    async function openInbox() {
      modal.hidden = true;
      showInboxError("");
      showInboxSuccess("");
      inbox.hidden = false;
      try {
        await loadTickets();
        renderTicket();
      } catch (_) {
        inboxTicket.hidden = true;
        inboxEmpty.hidden = false;
        inboxEmpty.textContent = "Could not load suggestions — try again in a moment.";
      }
    }

    function closeInbox() {
      inbox.hidden = true;
    }

    async function patchTicket(body) {
      const ticket = currentTicket();
      if (!ticket) return null;
      const res = await fetch(`${BASE}/api/feedback/${encodeURIComponent(ticket.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        throw new Error(typeof detail === "string" ? detail : "Could not save that ticket.");
      }
      const updated = data.ticket;
      if (updated) {
        allTickets = allTickets.map((row) => (row.id === updated.id ? updated : row));
      }
      setFabCount(allTickets.filter((row) => row.status !== "closed").length);
      return updated;
    }

    async function saveCurrent(extra, successText) {
      try {
        await patchTicket({
          message: ticketMessage.value.trim(),
          resolution: ticketResolution.value,
          ...extra,
        });
        await loadTickets();
        renderTicket();
        if (successText) showInboxSuccess(successText);
      } catch (err) {
        showInboxError(err.message || "Could not save that ticket.");
      }
    }

    async function onFabClick() {
      if (isHubHome()) {
        try {
          const data = await loadTickets();
          if (data.can_manage) {
            openInbox();
            return;
          }
        } catch (_) {
          /* fall through to the send form */
        }
      }
      openModal();
    }

    async function showNextNotice() {
      const notice = noticeQueue[0];
      if (!notice) return;
      let box = document.getElementById("hubFeedbackNotice");
      if (!box) {
        box = document.createElement("div");
        box.className = "hub-feedback-modal";
        box.id = "hubFeedbackNotice";
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-modal", "true");
        box.setAttribute("aria-labelledby", "hubFeedbackNoticeTitle");
        document.body.appendChild(box);
      }
      const who = notice.resolved_by ? ` from ${notice.resolved_by}` : "";
      box.innerHTML = `
        <div class="hub-feedback-modal__panel">
          <h2 class="hub-feedback-modal__title" id="hubFeedbackNoticeTitle">${escapeHtml(notice.title || "Your suggestion is done")}</h2>
          <p class="hub-feedback-modal__hint">You asked:</p>
          <p class="hub-feedback-notice__original">${escapeHtml(notice.message)}</p>
          <p class="hub-feedback-modal__hint">What we changed${escapeHtml(who)}:</p>
          <p class="hub-feedback-notice__fix">${escapeHtml(notice.resolution)}</p>
          <div class="hub-feedback-modal__actions">
            <button type="button" class="hub-feedback-modal__btn hub-feedback-modal__btn--primary" id="hubFeedbackNoticeGotIt">Got it</button>
          </div>
        </div>
      `;
      box.hidden = false;
      const dismiss = async () => {
        box.hidden = true;
        const current = noticeQueue.shift();
        if (current?.id) {
          try {
            await fetch(`${BASE}/api/feedback/${encodeURIComponent(current.id)}/seen`, {
              method: "POST",
              credentials: "same-origin",
            });
          } catch (_) {
            /* still move on so the hub is usable */
          }
        }
        if (noticeQueue.length) showNextNotice();
      };
      box.querySelector("#hubFeedbackNoticeGotIt")?.addEventListener("click", dismiss);
    }

    async function loadFixNotifications() {
      try {
        const res = await fetch(`${BASE}/api/feedback/notifications`, { credentials: "same-origin" });
        if (!res.ok) return;
        const data = await res.json();
        noticeQueue = Array.isArray(data.notifications) ? data.notifications.slice() : [];
        if (noticeQueue.length) showNextNotice();
      } catch (_) {
        /* optional */
      }
    }

    fab.addEventListener("click", onFabClick);
    if (legacyOpen) {
      legacyOpen.addEventListener("click", (event) => {
        event.preventDefault();
        onFabClick();
      });
    }
    cancelBtn.addEventListener("click", closeModal);
    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      addScreenshotFiles(Array.from(fileInput.files || []));
      fileInput.value = "";
    });
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModal();
    });
    inbox.addEventListener("click", (event) => {
      if (event.target === inbox) closeInbox();
    });
    document.getElementById("hubFeedbackInboxCloseBtn").addEventListener("click", closeInbox);
    document.getElementById("hubFeedbackNewBtn").addEventListener("click", openModal);
    document.getElementById("hubFeedbackPrevBtn").addEventListener("click", () => {
      if (index > 0) {
        index -= 1;
        renderTicket();
      }
    });
    document.getElementById("hubFeedbackNextBtn").addEventListener("click", () => {
      if (index < visibleTickets().length - 1) {
        index += 1;
        renderTicket();
      }
    });
    inbox.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        filter = btn.getAttribute("data-filter") || "open";
        inbox.querySelectorAll("[data-filter]").forEach((el) => {
          el.classList.toggle("is-active", el === btn);
        });
        index = 0;
        renderTicket();
      });
    });
    document.getElementById("hubFeedbackSaveBtn").addEventListener("click", () => {
      saveCurrent({}, "Saved.");
    });
    document.getElementById("hubFeedbackCloseTicketBtn").addEventListener("click", () => {
      saveCurrent({ status: "closed" }, "Closed — they’ll see what changed next time they open the hub.");
    });
    document.getElementById("hubFeedbackReopenBtn").addEventListener("click", () => {
      saveCurrent({ status: "open" }, "Ticket reopened.");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (!modal.hidden) closeModal();
        if (!inbox.hidden) closeInbox();
        return;
      }
      if (inbox.hidden) return;
      const typing = event.target && /^(INPUT|TEXTAREA)$/.test(event.target.tagName);
      if (typing) return;
      if (event.key === "ArrowLeft" && index > 0) {
        index -= 1;
        renderTicket();
      }
      if (event.key === "ArrowRight" && index < visibleTickets().length - 1) {
        index += 1;
        renderTicket();
      }
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
          closeModal();
          if (canManage && isHubHome()) {
            loadTickets().catch(() => {});
          }
        }, 1400);
      } catch (_) {
        showError("Could not reach the server.");
        submitBtn.disabled = false;
        submitBtn.textContent = "Send";
      }
    });

    if (isHubHome()) {
      loadTickets().catch(() => {});
    }
    loadFixNotifications();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
