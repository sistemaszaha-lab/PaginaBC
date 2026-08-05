(function () {
  const MODULE_CONFIGS = {
    operacion: {
      columnSelector: "[data-operaciones-column='1']",
      countSelector: "[data-operaciones-column-count='1']",
      bodySelector: ".panel-operaciones-col",
      emptyHtml:
        '<div class="operaciones-column__empty text-muted panel-operacion-empty">Sin operaciones.</div>',
    },
    garantia: {
      columnSelector: "[data-garantia-column='1']",
      countSelector: "[data-garantias-column-count='1']",
      bodySelector: ".garantias-column__body",
      emptyHtml: '<div class="garantia-empty">Sin garantias.</div>',
    },
    cotizacion: {
      columnSelector: "[data-panel-cotizacion-column='1']",
      countSelector: "[data-panel-cotizacion-column-count='1']",
      bodySelector: ".panel-cotizacion-column__body",
      emptyHtml: '<div class="panel-cotizacion-empty">Sin cotizaciones.</div>',
    },
    cuenta_gastos: {
      columnSelector: "[data-cuenta-column='1']",
      countSelector: "[data-cuenta-column-count='1']",
      bodySelector: ".cuenta-column__body",
      emptyHtml: '<div class="cuenta-column__empty">Sin registros.</div>',
    },
  };

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function showMessage(message, level) {
    const host = document.querySelector(".content");
    if (!host) {
      return;
    }

    const existing = document.getElementById("directTrashFeedback");
    if (existing) {
      existing.remove();
    }

    const wrapper = document.createElement("div");
    wrapper.id = "directTrashFeedback";
    wrapper.innerHTML = `
      <div class="alert alert-${level} alert-dismissible fade show" role="alert">
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button>
      </div>
    `;
    host.prepend(wrapper);
  }

  function updateKanbanColumn(moduleName, column) {
    const config = MODULE_CONFIGS[moduleName];
    if (!config || !column) {
      return;
    }

    const countNode = column.querySelector(config.countSelector);
    if (countNode) {
      const nextCount = Math.max(0, Number.parseInt(countNode.textContent || "0", 10) - 1);
      countNode.textContent = String(nextCount);
      column.dataset.total = String(nextCount);
      column.dataset.loaded = String(
        Math.max(0, Number.parseInt(column.dataset.loaded || "0", 10) - 1)
      );
    }

    const body = column.querySelector(config.bodySelector);
    if (!body) {
      return;
    }

    const hasCards = body.querySelector("[data-trash-remove-item='1']");
    const hasEmptyState = body.querySelector(
      ".operaciones-column__empty, .garantia-empty, .panel-cotizacion-empty, .cuenta-column__empty"
    );
    if (!hasCards && !hasEmptyState) {
      body.insertAdjacentHTML("beforeend", config.emptyHtml);
    }
  }

  function updateTableBody(button, removedItem) {
    const tbody = removedItem.parentElement;
    if (!tbody) {
      return;
    }

    const remaining = tbody.querySelectorAll("[data-trash-remove-item='1']");
    if (remaining.length > 0) {
      return;
    }

    const colspan = button.dataset.trashEmptyColspan || tbody.dataset.trashEmptyColspan || "1";
    const message =
      button.dataset.trashEmptyMessage || tbody.dataset.trashEmptyMessage || "Sin registros.";
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="${colspan}" class="text-center">${message}</td>`;
    tbody.appendChild(row);
  }

  async function sendToTrash(button) {
    const endpoint = button.dataset.trashEndpoint;
    if (!endpoint || button.disabled) {
      return;
    }
    if (!window.confirm("Deseas enviar este elemento a la papelera?")) {
      return;
    }

    const item = button.closest("[data-trash-remove-item='1']");
    if (!item) {
      return;
    }

    button.disabled = true;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      const data = await response.json().catch(() => ({
        ok: false,
        message: "Respuesta invalida del servidor.",
      }));

      if (!response.ok || (data.ok === false && data.status !== "ok" && data.success !== true)) {
        throw new Error(data.message || "No se pudo enviar a la papelera.");
      }

      const moduleName = button.dataset.trashModule;
      const kanbanColumn = MODULE_CONFIGS[moduleName]
        ? item.closest(MODULE_CONFIGS[moduleName].columnSelector)
        : null;

      item.remove();

      if (MODULE_CONFIGS[moduleName]) {
        updateKanbanColumn(moduleName, kanbanColumn);
      } else {
        updateTableBody(button, item);
      }

      showMessage(data.message || "El elemento se envio a la papelera correctamente.", "success");
    } catch (error) {
      showMessage(error.message || "No se pudo enviar a la papelera.", "danger");
      button.disabled = false;
    }
  }

  document.addEventListener("mousedown", function (event) {
    const button = event.target.closest("[data-trash-send='1']");
    if (!button) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
  });

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-trash-send='1']");
    if (!button) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    void sendToTrash(button);
  });
})();
