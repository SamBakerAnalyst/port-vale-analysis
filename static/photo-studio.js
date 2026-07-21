(function () {
  const PHOTO_SLOT_COUNT = 4;

  function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("Could not read that image."));
      reader.readAsDataURL(file);
    });
  }

  function clipboardImageFile(clipboardData) {
    const items = clipboardData?.items;
    if (!items) {
      return null;
    }
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        return item.getAsFile();
      }
    }
    return null;
  }

  function buildSlotMarkup(index) {
    return `
      <div
        class="photo-studio-dropzone"
        data-photo-dropzone="${index}"
        tabindex="0"
        role="button"
        aria-label="Paste photo for player ${index + 1}"
      >
        <img class="photo-studio-preview hidden" data-photo-preview="${index}" alt="" />
        <div class="photo-studio-placeholder" data-photo-placeholder="${index}">
          <p class="photo-studio-dropzone__title">Paste photo</p>
          <p class="photo-studio-dropzone__hint">Cmd+V · drop · click</p>
        </div>
        <input data-photo-file="${index}" type="file" accept="image/jpeg,image/png,image/webp" hidden />
      </div>
    `;
  }

  function attachPhotoSlots(gridEl, { getComparedPlayers, onPhotoSaved, showAlert, setStatus }) {
    if (!gridEl) {
      return { refresh() {} };
    }

    const slotState = Array.from({ length: PHOTO_SLOT_COUNT }, () => ({
      busy: false,
      dataUrl: null,
    }));
    const slotPlayerKeys = Array(PHOTO_SLOT_COUNT).fill(null);

    function players() {
      return getComparedPlayers() || [];
    }

    function playerAtSlot(index) {
      return players()[index] || null;
    }

    function slotElements(index) {
      return {
        mount: gridEl.querySelector(`[data-photo-slot="${index}"]`),
        dropzone: gridEl.querySelector(`[data-photo-dropzone="${index}"]`),
        preview: gridEl.querySelector(`[data-photo-preview="${index}"]`),
        placeholder: gridEl.querySelector(`[data-photo-placeholder="${index}"]`),
        fileInput: gridEl.querySelector(`[data-photo-file="${index}"]`),
      };
    }

    function showPreview(index, dataUrl) {
      const { preview, placeholder, dropzone } = slotElements(index);
      if (!preview || !placeholder) {
        return;
      }
      slotState[index].dataUrl = dataUrl;
      preview.src = dataUrl;
      preview.classList.remove("hidden");
      placeholder.classList.add("hidden");
      dropzone?.classList.add("has-image");
    }

    function clearPreview(index) {
      const { preview, placeholder, dropzone } = slotElements(index);
      if (!preview || !placeholder) {
        return;
      }
      slotState[index].dataUrl = null;
      preview.src = "";
      preview.classList.add("hidden");
      placeholder.classList.remove("hidden");
      dropzone?.classList.remove("has-image");
    }

    async function uploadDataUrl(index, dataUrl) {
      const player = playerAtSlot(index);
      if (!player || slotState[index].busy) {
        return;
      }
      slotState[index].busy = true;
      setStatus(`Saving photo for ${player.name}…`);
      try {
        const res = await fetch("/api/player-photo/upload", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            player_name: player.name,
            image_data: dataUrl,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || "Could not save player photo.");
        }
        onPhotoSaved(player, data.photo_url);
        setStatus(`Photo saved for ${player.name}.`);
      } catch (error) {
        showAlert(error.message || "Could not save player photo.");
        setStatus("Photo save failed.");
      } finally {
        slotState[index].busy = false;
      }
    }

    async function acceptImageFile(index, file) {
      const player = playerAtSlot(index);
      if (!player) {
        return;
      }
      if (!file || !file.type.startsWith("image/")) {
        showAlert("Paste or drop a JPG, PNG, or WebP image.");
        return;
      }
      const dataUrl = await readFileAsDataUrl(file);
      showPreview(index, dataUrl);
      await uploadDataUrl(index, dataUrl);
    }

    function wireGrid() {
      if (gridEl.dataset.photoWired === "1") {
        return;
      }
      gridEl.dataset.photoWired = "1";

      gridEl.addEventListener("click", (event) => {
        const dropzone = event.target.closest("[data-photo-dropzone]");
        if (!dropzone || dropzone.classList.contains("is-disabled")) {
          return;
        }
        const index = Number(dropzone.dataset.photoDropzone);
        if (!playerAtSlot(index)) {
          return;
        }
        const fileInput = slotElements(index).fileInput;
        fileInput?.click();
      });

      gridEl.addEventListener("keydown", (event) => {
        const dropzone = event.target.closest("[data-photo-dropzone]");
        if (!dropzone || (event.key !== "Enter" && event.key !== " ")) {
          return;
        }
        event.preventDefault();
        dropzone.click();
      });

      gridEl.addEventListener("paste", async (event) => {
        const dropzone = event.target.closest("[data-photo-dropzone]");
        if (!dropzone || dropzone.classList.contains("is-disabled")) {
          return;
        }
        event.preventDefault();
        const index = Number(dropzone.dataset.photoDropzone);
        const file = clipboardImageFile(event.clipboardData);
        if (!file) {
          showAlert("Clipboard does not contain an image — copy a photo first.");
          return;
        }
        await acceptImageFile(index, file);
      });

      gridEl.addEventListener("change", async (event) => {
        const input = event.target.closest("[data-photo-file]");
        if (!input) {
          return;
        }
        const index = Number(input.dataset.photoFile);
        const file = input.files?.[0];
        input.value = "";
        if (file) {
          await acceptImageFile(index, file);
        }
      });

      gridEl.addEventListener("dragover", (event) => {
        const dropzone = event.target.closest("[data-photo-dropzone]");
        if (!dropzone || dropzone.classList.contains("is-disabled")) {
          return;
        }
        event.preventDefault();
        dropzone.classList.add("is-dragover");
      });

      gridEl.addEventListener("dragleave", (event) => {
        const dropzone = event.target.closest("[data-photo-dropzone]");
        dropzone?.classList.remove("is-dragover");
      });

      gridEl.addEventListener("drop", async (event) => {
        const dropzone = event.target.closest("[data-photo-dropzone]");
        if (!dropzone || dropzone.classList.contains("is-disabled")) {
          return;
        }
        event.preventDefault();
        dropzone.classList.remove("is-dragover");
        const index = Number(dropzone.dataset.photoDropzone);
        const file = event.dataTransfer?.files?.[0];
        if (file) {
          await acceptImageFile(index, file);
        }
      });
    }

    function refresh() {
      wireGrid();
      for (let index = 0; index < PHOTO_SLOT_COUNT; index += 1) {
        const player = playerAtSlot(index);
        const { dropzone, mount } = slotElements(index);
        const column = gridEl.querySelector(`[data-player-slot="${index}"]`);
        if (!dropzone || !mount) {
          continue;
        }

        if (player) {
          dropzone.classList.remove("is-disabled");
          column?.classList.remove("studio-player-column--empty");
          if (slotPlayerKeys[index] !== player.key) {
            slotPlayerKeys[index] = player.key;
            slotState[index].dataUrl = null;
            clearPreview(index);
          }
          if (!slotState[index].dataUrl && player.photo_url) {
            showPreview(index, player.photo_url);
          }
        } else {
          dropzone.classList.add("is-disabled");
          column?.classList.add("studio-player-column--empty");
          slotPlayerKeys[index] = null;
          slotState[index].dataUrl = null;
          clearPreview(index);
        }
      }
    }

    return { refresh, buildSlotMarkup };
  }

  window.PhotoStudio = {
    attachPhotoSlots,
    buildSlotMarkup,
    PHOTO_SLOT_COUNT,
  };
})();
