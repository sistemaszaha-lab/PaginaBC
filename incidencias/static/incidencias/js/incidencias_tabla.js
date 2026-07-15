(function () {


  const dataEl = document.getElementById("incidencias-data");
  const tableData = dataEl ? JSON.parse(dataEl.textContent || "[]") : [];

  const endpoints = window.__INCIDENCIAS_ENDPOINTS__ || {};

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function badgeFromValue(type, value) {
    const v = String(value || "").toLowerCase();
    let cls = "bg-secondary";
    let label = value || "";

    if (type === "estado") {
      if (v === "abierto") cls = "bg-danger";
      else if (v === "proceso") cls = "bg-warning text-dark";
      else if (v === "cerrado") cls = "bg-success";
    }

    if (type === "prioridad") {
      if (v === "alta") cls = "bg-danger";
      else if (v === "media") cls = "bg-warning text-dark";
      else if (v === "baja") cls = "bg-secondary";
    }

    return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
  }

  const table = new Tabulator("#incidenciasTable", {
    data: tableData,
    index: "id",
    layout: "fitColumns",
    responsiveLayout: "collapse",
    pagination: "local",
    paginationSize: 25,
    paginationSizeSelector: false,
    movableColumns: true,
    resizableColumnFit: true,
    placeholder: "No hay incidencias todavía.",
    columns: [
      { title: "Incidencia", field: "incidencia", widthGrow: 1 },
      { title: "Responsable", field: "responsable", widthGrow: 1 },
      {
        title: "Estado",
        field: "estado",
        formatter: (cell) => badgeFromValue("estado", cell.getValue()),
        width: 140,
      },
      {
        title: "Prioridad",
        field: "prioridad",
        formatter: (cell) => badgeFromValue("prioridad", cell.getValue()),
        width: 140,
      },
      { title: "Fecha", field: "fecha", sorter: "string", width: 160 },
      { title: "Descripción", field: "descripcion", widthGrow: 2, formatter: "textarea" },
      {
        title: "Acciones",
        field: "id",
        headerSort: false,
        width: 160,
        formatter: (cell) => {
          const id = cell.getValue();
          return `
            <div class="d-flex gap-2 flex-wrap">
              <button type="button" class="btn btn-sm btn-outline-primary inc-action-edit" data-id="${id}">Editar</button>
              <button type="button" class="btn btn-sm btn-outline-danger inc-action-del" data-id="${id}">Eliminar</button>
            </div>`;
        },
      },
    ],
  });

  const searchInput = document.getElementById("incidenciasSearch");
  const searchBtn = document.getElementById("incidenciasSearchBtn");
  const clearBtn = document.getElementById("incidenciasSearchClear");
  const newBtn = document.getElementById("incidenciasNewBtn");

  const formWrap = document.getElementById("incidenciasFormWrap");
  const form = document.getElementById("incidenciasForm");
  const formErrors = document.getElementById("incidenciasFormErrors");
  const cancelBtn = document.getElementById("incidenciasCancelBtn");

  const pagerInfo = document.getElementById("incidenciasPagerInfo");
  const pager = document.getElementById("incidenciasPager");

  function applyGlobalSearch(value) {
    const v = String(value || "").trim();
    const url = new URL(window.location.href);
    if (!v) {
      table.clearFilter(true);
      url.searchParams.delete("q");
      history.replaceState(null, "", url.toString());
      return;
    }

    url.searchParams.set("q", v);
    history.replaceState(null, "", url.toString());

    const needle = v.toLowerCase();
    table.setFilter((rowData) => {
      return [
        rowData.incidencia,
        rowData.titulo,
        rowData.responsable,
        rowData.estado,
        rowData.prioridad,
        rowData.fecha,
        rowData.descripcion,
      ]
        .map((x) => String(x || "").toLowerCase())
        .some((x) => x.includes(needle));
    });
  }

  if (searchInput) searchInput.addEventListener("input", (e) => applyGlobalSearch(e.target.value));
  if (searchBtn) searchBtn.addEventListener("click", () => applyGlobalSearch(searchInput ? searchInput.value : ""));
  if (clearBtn)
    clearBtn.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      table.clearFilter(true);
      renderPager();
    });

  function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || "";
  }

  function showForm(mode, row) {
    if (!formWrap || !form) return;
    formWrap.classList.remove("d-none");
    if (formErrors) {
      formErrors.classList.add("d-none");
      formErrors.textContent = "";
    }

    document.getElementById("incidenciasId").value = row?.id || "";
    document.getElementById("incidenciasCodigo").value = row?.incidencia || "";
    document.getElementById("incidenciasTitulo").value = row?.titulo || "";
    document.getElementById("incidenciasDescripcion").value = row?.descripcion || "";
    document.getElementById("incidenciasResponsable").value = row?.responsable_id || "";
    document.getElementById("incidenciasEstado").value = row?.estado || "abierto";
    document.getElementById("incidenciasPrioridad").value = row?.prioridad || "media";
    document.getElementById("incidenciasFechaLimite").value = row?.fecha_limite || "";

    const saveBtn = document.getElementById("incidenciasSaveBtn");
    if (saveBtn) saveBtn.textContent = mode === "edit" ? "Guardar cambios" : "Guardar";

    formWrap.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function hideForm() {
    if (!formWrap || !form) return;
    form.reset();
    document.getElementById("incidenciasId").value = "";
    formWrap.classList.add("d-none");
    if (formErrors) {
      formErrors.classList.add("d-none");
      formErrors.textContent = "";
    }
  }

  if (newBtn) newBtn.addEventListener("click", () => showForm("new", null));
  if (cancelBtn) cancelBtn.addEventListener("click", hideForm);

  async function postUrlencoded(url, params) {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCsrfToken(),
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      },
      body: params,
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw payload;
    return payload;
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = document.getElementById("incidenciasId").value;
      const isEdit = Boolean(id);
      const url = isEdit
        ? String(endpoints.editar || "").replace("/0/editar/", `/${id}/editar/`)
        : endpoints.crear;

      try {
        const params = new URLSearchParams(new FormData(form));
        const payload = await postUrlencoded(url, params);
        const row = payload.row;
        if (isEdit) table.updateData([row]);
        else table.addRow(row, true);
        hideForm();
        renderPager();
      } catch (err) {
        const msg = err?.errors ? JSON.stringify(err.errors) : "No se pudo guardar la incidencia.";
        if (formErrors) {
          formErrors.textContent = msg;
          formErrors.classList.remove("d-none");
        }
      }
    });
  }

  document.addEventListener("click", async (e) => {
    const editBtn = e.target?.closest?.(".inc-action-edit");
    const delBtn = e.target?.closest?.(".inc-action-del");
    if (editBtn) {
      const id = editBtn.getAttribute("data-id");
      const row = table.getRow(id);
      showForm("edit", row ? row.getData() : null);
    }
    if (delBtn) {
      const id = delBtn.getAttribute("data-id");
      if (!window.confirm("¿Eliminar esta incidencia?")) return;
      const url = String(endpoints.eliminar || "").replace("/0/eliminar/", `/${id}/eliminar/`);
      try {
        await postUrlencoded(url, new URLSearchParams());
        const row = table.getRow(id);
        if (row) row.delete();
        renderPager();
      } catch {
        // noop
      }
    }
  });

  function renderPager() {
    if (!pager || !pagerInfo) return;
    const current = table.getPage() || 1;
    const max = table.getPageMax() || 1;
    pagerInfo.textContent = `Página ${current} de ${max}`;
    pager.innerHTML = "";

    function addItem(label, page, disabled, active) {
      const li = document.createElement("li");
      li.className = `page-item${disabled ? " disabled" : ""}${active ? " active" : ""}`;
      const a = document.createElement("a");
      a.className = "page-link";
      a.href = "#";
      a.textContent = label;
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        if (disabled) return;
        table.setPage(page);
      });
      li.appendChild(a);
      pager.appendChild(li);
    }

    addItem("Anterior", Math.max(1, current - 1), current <= 1, false);

    const windowSize = 5;
    let start = Math.max(1, current - Math.floor(windowSize / 2));
    let end = Math.min(max, start + windowSize - 1);
    start = Math.max(1, end - windowSize + 1);

    for (let p = start; p <= end; p++) addItem(String(p), p, false, p === current);

    addItem("Siguiente", Math.min(max, current + 1), current >= max, false);
  }

  table.on("pageLoaded", renderPager);
  table.on("dataFiltered", renderPager);
  table.on("dataLoaded", renderPager);
  if (searchInput && searchInput.value) {
    applyGlobalSearch(searchInput.value);
  }
  renderPager();
})();
