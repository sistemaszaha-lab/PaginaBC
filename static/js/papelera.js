(function () {
  const app = document.querySelector("[data-trash-app='1']");
  if (!app || !window.trashConfig) return;

  const list = app.querySelector("[data-trash-list]");
  const selectVisible = app.querySelector("[data-trash-select-visible]");
  const selectedCount = app.querySelector("[data-trash-selected-count]");
  const totalCount = app.querySelector("[data-trash-total-count]");
  const bulkRestoreButton = app.querySelector("[data-trash-bulk-restore]");
  const bulkDeleteButton = app.querySelector("[data-trash-bulk-delete]");
  const feedback = document.getElementById("trashFeedback");
  const emptyState = app.querySelector("[data-trash-empty-state]");

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function showMessage(message, level) {
    if (!feedback) return;
    feedback.innerHTML = `
      <div class="alert alert-${level} alert-dismissible fade show" role="alert">
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button>
      </div>
    `;
  }

  function visibleItems() {
    return Array.from(list.querySelectorAll("[data-trash-item]"));
  }

  function selectedItems() {
    return visibleItems()
      .filter((item) => item.querySelector("[data-trash-checkbox]")?.checked)
      .map((item) => ({
        tipo: item.dataset.tipo,
        id: Number(item.dataset.id),
        element: item,
      }));
  }

  function updateSelectionState() {
    const items = visibleItems();
    const selected = selectedItems();
    if (selectedCount) selectedCount.textContent = String(selected.length);
    if (bulkRestoreButton) bulkRestoreButton.disabled = selected.length === 0;
    if (bulkDeleteButton) bulkDeleteButton.disabled = selected.length === 0;
    if (selectVisible) {
      const enabled = items
        .map((item) => item.querySelector("[data-trash-checkbox]"))
        .filter(Boolean)
        .filter((checkbox) => !checkbox.disabled);
      selectVisible.checked = enabled.length > 0 && enabled.every((checkbox) => checkbox.checked);
      selectVisible.indeterminate =
        enabled.length > 0 &&
        enabled.some((checkbox) => checkbox.checked) &&
        !enabled.every((checkbox) => checkbox.checked);
    }
  }

  function updateEmptyState() {
    const items = visibleItems();
    if (totalCount) totalCount.textContent = String(items.length);
    if (emptyState) {
      emptyState.classList.toggle("d-none", items.length > 0);
    }
  }

  function buildItemUrl(template, tipo, id) {
    return template
      .replace("__tipo__", tipo)
      .replace("/999999/", `/${id}/`);
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({ ok: false, message: "Respuesta inválida del servidor." }));
    if (!response.ok || data.ok === false) {
      throw new Error(data.message || "No se pudo completar la operación.");
    }
    return data;
  }

  async function postItem(url) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    const data = await response.json().catch(() => ({ ok: false, message: "Respuesta inválida del servidor." }));
    if (!response.ok || (data.ok === false && data.status !== "ok")) {
      throw new Error(data.message || "No se pudo completar la operación.");
    }
    return data;
  }

  function removeItems(items) {
    items.forEach((item) => item.remove());
    updateSelectionState();
    updateEmptyState();
  }

  selectVisible?.addEventListener("change", function () {
    const checked = this.checked;
    visibleItems().forEach((item) => {
      const checkbox = item.querySelector("[data-trash-checkbox]");
      if (checkbox && !checkbox.disabled) {
        checkbox.checked = checked;
      }
    });
    updateSelectionState();
  });

  list?.addEventListener("change", function (event) {
    if (event.target.matches("[data-trash-checkbox]")) {
      updateSelectionState();
    }
  });

  list?.addEventListener("click", async function (event) {
    const restoreButton = event.target.closest("[data-trash-restore]");
    const deleteButton = event.target.closest("[data-trash-delete]");
    const item = event.target.closest("[data-trash-item]");
    if (!item) return;

    if (restoreButton) {
      restoreButton.disabled = true;
      try {
        const url = buildItemUrl(window.trashConfig.restoreUrlTemplate, item.dataset.tipo, item.dataset.id);
        const data = await postItem(url);
        removeItems([item]);
        showMessage(data.message || "El elemento se restauró correctamente.", "success");
      } catch (error) {
        showMessage(error.message, "danger");
        restoreButton.disabled = false;
      }
      return;
    }

    if (deleteButton) {
      const confirmed = window.confirm("Esta acción es permanente y no se puede deshacer.");
      if (!confirmed) return;
      deleteButton.disabled = true;
      try {
        const url = buildItemUrl(window.trashConfig.deleteUrlTemplate, item.dataset.tipo, item.dataset.id);
        const data = await postItem(url);
        removeItems([item]);
        showMessage(data.message || "El elemento se eliminó definitivamente.", "success");
      } catch (error) {
        showMessage(error.message, "danger");
        deleteButton.disabled = false;
      }
    }
  });

  bulkRestoreButton?.addEventListener("click", async function () {
    const items = selectedItems();
    if (items.length === 0) return;
    this.disabled = true;
    try {
      const data = await postJson(window.trashConfig.restoreSelectionUrl, {
        items: items.map(({ tipo, id }) => ({ tipo, id })),
      });
      removeItems(items.map((item) => item.element));
      showMessage(data.message || "Se restauraron los elementos seleccionados.", "success");
    } catch (error) {
      showMessage(error.message, "danger");
    } finally {
      updateSelectionState();
    }
  });

  bulkDeleteButton?.addEventListener("click", async function () {
    const items = selectedItems();
    if (items.length === 0) return;
    if (!window.confirm("Esta acción es permanente y no se puede deshacer.")) return;
    this.disabled = true;
    try {
      const data = await postJson(window.trashConfig.deleteSelectionUrl, {
        items: items.map(({ tipo, id }) => ({ tipo, id })),
      });
      removeItems(items.map((item) => item.element));
      showMessage(data.message || "Se eliminaron definitivamente los elementos seleccionados.", "success");
    } catch (error) {
      showMessage(error.message, "danger");
    } finally {
      updateSelectionState();
    }
  });

  updateSelectionState();
  updateEmptyState();
})();
