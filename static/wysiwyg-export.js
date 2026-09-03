/**
 * Shared WYSIWYG PDF export — capture EXACTLY what is on screen.
 *
 * Do not force PDF-view / export-capture layouts. Measure the live slide,
 * clone it as-is, uniform-scale into a 1920×1080 frame, then Playwright
 * screenshots that HTML on the server.
 */
(function (global) {
  "use strict";

  const FRAME_W = 1920;
  const FRAME_H = 1080;
  const DEVICE_SCALE = 2;
  const DEFAULT_ENDPOINT = "/api/wysiwyg-export-pdf";

  function waitForImages(root, timeoutMs = 6000) {
    const images = [...(root?.querySelectorAll?.("img") || [])];
    if (!images.length) return Promise.resolve();
    return Promise.all(
      images.map(
        (image) =>
          new Promise((resolve) => {
            if (image.complete && image.naturalWidth > 0) {
              resolve();
              return;
            }
            const timer = window.setTimeout(resolve, timeoutMs);
            const done = () => {
              window.clearTimeout(timer);
              resolve();
            };
            image.addEventListener("load", done, { once: true });
            image.addEventListener("error", done, { once: true });
          }),
      ),
    );
  }

  async function imageToDataUrl(img) {
    const src = img.currentSrc || img.src;
    if (!src || src.startsWith("data:")) return src || "";
    try {
      const response = await fetch(src, { credentials: "same-origin" });
      if (!response.ok) return src;
      const blob = await response.blob();
      return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || src));
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    } catch {
      return src;
    }
  }

  async function inlineImages(clone) {
    const images = [...clone.querySelectorAll("img")];
    await Promise.all(
      images.map(async (img) => {
        const dataUrl = await imageToDataUrl(img);
        if (dataUrl) {
          img.setAttribute("src", dataUrl);
          img.removeAttribute("srcset");
        }
      }),
    );
  }

  /** Replace live <canvas> paints with <img> so clones keep chart pixels. */
  function freezeCanvases(root) {
    const restores = [];
    [...(root?.querySelectorAll?.("canvas") || [])].forEach((canvas) => {
      try {
        if (!canvas.width || !canvas.height) return;
        const dataUrl = canvas.toDataURL("image/png");
        const img = document.createElement("img");
        img.src = dataUrl;
        img.alt = "";
        img.width = canvas.width;
        img.height = canvas.height;
        const style = canvas.getAttribute("style") || "";
        img.setAttribute("style", style);
        img.className = canvas.className;
        canvas.replaceWith(img);
        restores.push(() => img.replaceWith(canvas));
      } catch {
        /* tainted canvas — leave as-is */
      }
    });
    return () => restores.reverse().forEach((fn) => fn());
  }

  function prepareClone(slide, { width, height, stripClasses = [], activeClass = null } = {}) {
    const clone = slide.cloneNode(true);
    if (activeClass) clone.classList.add(activeClass);
    stripClasses.forEach((cls) => clone.classList.remove(cls));
    clone.querySelectorAll("[contenteditable]").forEach((field) => {
      const text = (field.innerText || "").replace(/\u00a0/g, " ");
      field.removeAttribute("contenteditable");
      if (field.matches("li, .tp-note__item")) {
        field.textContent = text.trim() ? text.replace(/\n+/g, " ").trim() : "";
      }
    });
    clone.style.setProperty("width", `${width}px`, "important");
    clone.style.setProperty("max-width", `${width}px`, "important");
    clone.style.setProperty("height", `${height}px`, "important");
    clone.style.setProperty("min-height", `${height}px`, "important");
    clone.style.setProperty("max-height", `${height}px`, "important");
    clone.style.setProperty("aspect-ratio", "auto", "important");
    clone.style.borderRadius = "0";
    clone.style.boxShadow = "none";
    clone.style.outline = "none";
    clone.style.overflow = "hidden";
    clone.style.margin = "0";
    clone.style.transform = "none";
    clone.style.removeProperty("--pm-export-w");
    clone.style.removeProperty("--pm-export-h");
    return clone;
  }

  async function collectCssText(extraUrls = []) {
    const chunks = [];
    for (const style of document.querySelectorAll("style")) {
      chunks.push(style.textContent || "");
    }
    const links = [...document.querySelectorAll('link[rel="stylesheet"]')].map((link) => link.href);
    const urls = [...new Set([...links, ...extraUrls].filter(Boolean))];
    await Promise.all(
      urls.map(async (href) => {
        try {
          const response = await fetch(href, { credentials: "same-origin" });
          if (response.ok) chunks.push(await response.text());
        } catch {
          /* skip missing stylesheet */
        }
      }),
    );
    return chunks.join("\n");
  }

  function fontLinkTags() {
    return [...document.querySelectorAll('link[href*="fonts.googleapis"], link[href*="fonts.gstatic"]')]
      .map((link) => link.outerHTML)
      .join("\n");
  }

  function buildDocument({
    slideHtml,
    frameWidth = FRAME_W,
    frameHeight = FRAME_H,
    liveWidth,
    liveHeight,
    cssText,
    bodyClass = "is-exporting",
    kitStyle = "",
    background = "#0b1220",
  }) {
    const liveW = Math.max(1, Math.round(liveWidth || frameWidth));
    const liveH = Math.max(1, Math.round(liveHeight || frameHeight));
    const scale = Math.min(frameWidth / liveW, frameHeight / liveH);
    const safeKit = String(kitStyle || "").replace(/"/g, "&quot;");
    const wrapped = `<div class="pv-export-frame" style="width:${frameWidth}px;height:${frameHeight}px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:${background};">
  <div class="pv-export-scale" style="width:${liveW}px;height:${liveH}px;transform:scale(${scale});transform-origin:center center;">
    ${slideHtml}
  </div>
</div>`;
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <base href="${window.location.origin}/" />
  ${fontLinkTags()}
  <style>
${cssText || ""}
html, body {
  margin: 0 !important;
  padding: 0 !important;
  width: ${frameWidth}px !important;
  height: ${frameHeight}px !important;
  overflow: hidden !important;
  background: ${background} !important;
}
body { display: block !important; }
.pv-export-frame, .pv-export-scale { box-sizing: border-box; }
.pv-export-scale > * { margin: 0 !important; }
  </style>
</head>
<body class="${bodyClass}" style="${safeKit}">
${wrapped}
</body>
</html>`;
  }

  function slugify(value, fallback = "slide") {
    const raw = String(value || "")
      .normalize("NFKD")
      .replace(/[^\w\s\-]+/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .slice(0, 60);
    return raw || fallback;
  }

  /**
   * @param {object} options
   * @param {Element[]} options.slides
   * @param {(index:number, slide:Element)=>void} [options.beforeSlide]
   * @param {(slide:Element)=>void|Promise<void>} [options.settleSlide]
   * @param {string[]} [options.stripClasses]
   * @param {string|null} [options.activeClass]
   * @param {string} [options.bodyClass]
   * @param {string} [options.background]
   * @param {boolean} [options.forceNativeSize] Use CSS design size (1920×1080) instead of
   *   scaled on-screen rect — required when slides use transform:scale() in a preview pane.
   * @param {number} [options.nativeWidth]
   * @param {number} [options.nativeHeight]
   * @param {(msg:string)=>void} [options.onProgress]
   */
  async function captureSlideHtmlPages(options = {}) {
    const slides = [...(options.slides || [])];
    if (!slides.length) throw new Error("No slides to export.");

    const frameWidth = options.frameWidth || FRAME_W;
    const frameHeight = options.frameHeight || FRAME_H;
    const stripClasses = options.stripClasses || [
      "pm-slide--export-capture",
      "sp-slide--export-capture",
      "slide--pdf-capture",
      "is-export-capture",
      "is-export-hidden",
      "is-exporting",
    ];
    const activeClass = options.activeClass ?? null;
    const cssText = options.cssText || (await collectCssText(options.cssUrls || []));
    const kitStyle = options.kitStyle || "";
    const bodyClass =
      options.bodyClass ||
      ["is-exporting", ...[...document.body.classList].filter((c) => c !== "is-present")].join(" ");
    const forceNative = Boolean(options.forceNativeSize);
    const nativeW = Math.max(1, Math.round(options.nativeWidth || frameWidth));
    const nativeH = Math.max(1, Math.round(options.nativeHeight || frameHeight));

    if (document.fonts?.ready) {
      try {
        await document.fonts.ready;
      } catch {
        /* ignore */
      }
    }

    const htmlPages = [];
    const htmlFilenames = [];

    for (let index = 0; index < slides.length; index += 1) {
      const slide = slides[index];
      options.beforeSlide?.(index, slide);
      slide.scrollIntoView({ behavior: "instant", block: "center" });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      if (options.settleSlide) await options.settleSlide(slide);
      await waitForImages(slide, options.imageTimeoutMs || 8000);
      await new Promise((resolve) => window.setTimeout(resolve, 60));

      const unfreeze = freezeCanvases(slide);
      try {
        const rect = slide.getBoundingClientRect();
        const liveW = forceNative ? nativeW : Math.max(1, Math.round(rect.width));
        const liveH = forceNative ? nativeH : Math.max(1, Math.round(rect.height));
        const clone = prepareClone(slide, {
          width: liveW,
          height: liveH,
          stripClasses,
          activeClass,
        });
        // Kill preview-only transform leftover on cloned slides.
        clone.style.transform = "none";
        clone.style.transformOrigin = "top left";
        await inlineImages(clone);
        const doc = buildDocument({
          slideHtml: clone.outerHTML,
          frameWidth,
          frameHeight,
          liveWidth: liveW,
          liveHeight: liveH,
          cssText,
          bodyClass,
          kitStyle,
          background: options.background || "#0b1220",
        });
        htmlPages.push(doc);
        const title =
          slide.dataset.slideTitle ||
          slide.getAttribute("data-title") ||
          slide.getAttribute("data-slide") ||
          slide.querySelector("h1, h2, .slide__hero-title, .mfp-profile__title")?.textContent ||
          `slide-${index + 1}`;
        htmlFilenames.push(slugify(title, `slide-${index + 1}`));
      } finally {
        unfreeze();
      }

      options.onProgress?.(`Preparing… ${index + 1}/${slides.length}`);
    }

    return {
      htmlPages,
      htmlFilenames,
      width: frameWidth,
      height: frameHeight,
      scale: options.scale || DEVICE_SCALE,
    };
  }

  async function downloadPdf({
    htmlPages,
    htmlFilenames,
    width = FRAME_W,
    height = FRAME_H,
    scale = DEVICE_SCALE,
    filename = "port-vale-export.pdf",
    documentTitle = "Port Vale export",
    endpoint = DEFAULT_ENDPOINT,
    opponentName = null,
  }) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        html_pages: htmlPages,
        html_filenames: htmlFilenames,
        width,
        height,
        scale,
        filename,
        document_title: documentTitle,
        opponent_name: opponentName,
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "PDF export failed");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return {
      blob,
      savedPath: response.headers.get("X-Saved-Desktop-Path"),
      sizeMb: (blob.size / (1024 * 1024)).toFixed(1),
      pageCount: htmlPages.length,
    };
  }

  async function downloadPngZip({
    htmlPages,
    htmlFilenames,
    width = FRAME_W,
    height = FRAME_H,
    scale = DEVICE_SCALE,
    filename = "port-vale-export.zip",
    documentTitle = "Port Vale export",
    endpoint = "/api/wysiwyg-export-png-zip",
    opponentName = null,
  }) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        html_pages: htmlPages,
        html_filenames: htmlFilenames,
        width,
        height,
        scale,
        filename,
        document_title: documentTitle,
        opponent_name: opponentName,
      }),
    });
    if (!response.ok) {
      let detail = "";
      try {
        const payload = await response.json();
        detail = payload.detail || "";
      } catch {
        detail = await response.text();
      }
      throw new Error(detail || "PNG zip export failed");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return {
      blob,
      savedPath: response.headers.get("X-Saved-Desktop-Path"),
      sizeMb: (blob.size / (1024 * 1024)).toFixed(1),
      pageCount: htmlPages.length,
    };
  }

  global.PortValeWysiwygExport = {
    FRAME_W,
    FRAME_H,
    DEVICE_SCALE,
    DEFAULT_ENDPOINT,
    waitForImages,
    inlineImages,
    freezeCanvases,
    prepareClone,
    collectCssText,
    buildDocument,
    slugify,
    captureSlideHtmlPages,
    downloadPdf,
    downloadPngZip,
  };
})(typeof window !== "undefined" ? window : globalThis);
