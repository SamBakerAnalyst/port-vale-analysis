// Admin preview of the unpaid-invoice lock.
//
// Staff accounts never reach this file — the server replaces every page with an
// uncloseable SYSTEM LOCKED screen. The admin account still loads the hub, and
// this script pops the same box so you can preview it. Only admin gets Close.
(function () {
  "use strict";
  if (window.__SYSTEM_LOCK_BOOTED__) return;
  window.__SYSTEM_LOCK_BOOTED__ = true;

  var TITLE = "SYSTEM LOCKED";
  var MESSAGE =
    "Contractual Payment Terms ignored, therefore the system is locked until further notice";
  var DISMISS_KEY = "syslock-admin-preview-dismissed";

  var state = {
    locked: false,
    canClose: false,
    title: TITLE,
    message: MESSAGE,
  };

  function el(tag, attrs, html) {
    var node = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (html != null) node.innerHTML = html;
    return node;
  }

  function post(locked) {
    return fetch("/api/system-lock", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ locked: locked }),
    }).then(function (r) { return r.json(); });
  }

  function ensureStyles() {
    if (document.getElementById("system-lock-styles")) return;
    var css = ""
      + ".syslock-overlay{position:fixed;inset:0;z-index:2147483646;display:flex;"
      + "align-items:center;justify-content:center;background:rgba(6,8,10,.92);"
      + "backdrop-filter:blur(4px);padding:24px;box-sizing:border-box;}"
      + ".syslock-box{max-width:560px;width:100%;text-align:center;background:#15181d;"
      + "border:1px solid #2a2f37;border-radius:16px;padding:48px 40px;"
      + "box-shadow:0 24px 60px rgba(0,0,0,.55);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}"
      + ".syslock-box h1{margin:0 0 16px;font-size:40px;letter-spacing:2px;color:#ff5a5f;font-weight:800;}"
      + ".syslock-box p{margin:0;font-size:18px;line-height:1.5;color:#cfd4db;}"
      + ".syslock-actions{margin-top:28px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap;}"
      + ".syslock-btn{border:none;border-radius:10px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;}"
      + ".syslock-btn--close{background:#2a2f37;color:#f5f5f5;}"
      + ".syslock-note{margin-top:16px;font-size:12px;color:#8b93a0;}"
      + ".syslock-toggle{position:fixed;bottom:18px;left:18px;z-index:2147483645;"
      + "border:1px solid #2a2f37;border-radius:999px;padding:8px 14px;font-size:13px;"
      + "font-weight:600;cursor:pointer;color:#f5f5f5;background:#1b1f25;"
      + "box-shadow:0 6px 18px rgba(0,0,0,.35);}"
      + ".syslock-toggle[data-locked='1']{background:#3a1416;border-color:#7a2a2f;color:#ff8a8f;}";
    var style = el("style", { id: "system-lock-styles" });
    style.textContent = css;
    document.head.appendChild(style);
  }

  function removeOverlay() {
    var o = document.getElementById("syslock-overlay");
    if (o) o.remove();
  }

  function showPreview() {
    if (!state.canClose || !state.locked) return;
    removeOverlay();
    var overlay = el("div", { id: "syslock-overlay", class: "syslock-overlay" });
    overlay.addEventListener("click", function (e) {
      // Match the staff lock: clicking the dimmed background does nothing.
      e.stopPropagation();
    });
    var box = el("div", { class: "syslock-box", role: "alertdialog", "aria-modal": "true" });
    box.appendChild(el("h1", null, state.title));
    box.appendChild(el("p", null, state.message));
    var actions = el("div", { class: "syslock-actions" });
    var closeBtn = el("button", { class: "syslock-btn syslock-btn--close", type: "button" }, "Close");
    closeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      try { sessionStorage.setItem(DISMISS_KEY, "1"); } catch (_) {}
      removeOverlay();
    });
    actions.appendChild(closeBtn);
    box.appendChild(actions);
    box.appendChild(el("div", { class: "syslock-note" },
      "Admin preview — other accounts cannot close this."));
    overlay.appendChild(box);
    (document.body || document.documentElement).appendChild(overlay);
  }

  function renderToggle() {
    if (!state.canClose) return;
    var existing = document.getElementById("syslock-toggle");
    if (existing) existing.remove();
    var btn = el("button", { id: "syslock-toggle", class: "syslock-toggle", type: "button" });
    btn.setAttribute("data-locked", state.locked ? "1" : "0");
    btn.textContent = state.locked ? "System LOCKED — click to unlock" : "Lock system";
    btn.addEventListener("click", function () {
      var next = !state.locked;
      btn.disabled = true;
      post(next).then(function () {
        state.locked = next;
        btn.disabled = false;
        renderToggle();
        if (next) {
          try { sessionStorage.removeItem(DISMISS_KEY); } catch (_) {}
          showPreview();
        } else {
          removeOverlay();
        }
      }).catch(function () { btn.disabled = false; });
    });
    (document.body || document.documentElement).appendChild(btn);
  }

  function apply(lock) {
    // Only trust an explicit lock payload ({locked: true/false}). Never treat
    // /api/auth/me as lock state — that leaked this overlay onto Live.
    if (!lock || typeof lock.locked !== "boolean") return;
    state.locked = lock.locked;
    state.canClose = Boolean(lock.can_close || lock.can_control);
    if (lock.title) state.title = lock.title;
    if (lock.message) state.message = lock.message;
    if (!state.canClose) return;
    ensureStyles();
    renderToggle();
    var dismissed = false;
    try { dismissed = sessionStorage.getItem(DISMISS_KEY) === "1"; } catch (_) {}
    if (state.locked && !dismissed) showPreview();
  }

  function init() {
    var opts = { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } };
    fetch("/api/system-lock", opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (lock) {
        if (lock) apply(lock);
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
