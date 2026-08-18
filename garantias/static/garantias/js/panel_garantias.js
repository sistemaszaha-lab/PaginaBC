(function () {
    const root = document.querySelector('.garantias-board');
    const configElement = document.getElementById('panel-garantias-config');
    if (!root || !configElement || root.dataset.panelJsInitialized === '1') return;

    let config;
    try {
      config = JSON.parse(configElement.textContent);
    } catch (_) {
      return;
    }
    if (!config?.estadoUpdateUrl || !config?.inlineCreateUrl || !config?.inlineFormUrl) return;
    if (typeof window.createKanbanQuickEditController !== 'function') return;
    root.dataset.panelJsInitialized = '1';

    const updateUrl = config.estadoUpdateUrl;
    const boardUrl = config.boardUrl || '';
    const inlineCreateUrl = config.inlineCreateUrl;
    const inlineFormUrl = config.inlineFormUrl;
    const columnCreateUrl = config.columnCreateUrl || '';
    const columnReorderUrl = config.columnReorderUrl || '';
    const modalElement = document.getElementById('garantiaDetalleModal');
    const modalContent = document.getElementById('garantiaDetalleModalContent');
    const modalInstance = modalElement && window.bootstrap ? new bootstrap.Modal(modalElement) : null;
    const columnCreateModalElement = document.getElementById('garantiaColumnCreateModal');
    const columnEditModalElement = document.getElementById('garantiaColumnEditModal');
    const columnDeleteModalElement = document.getElementById('garantiaColumnDeleteModal');
    const columnCreateModal = columnCreateModalElement && window.bootstrap ? new bootstrap.Modal(columnCreateModalElement) : null;
    const columnEditModal = columnEditModalElement && window.bootstrap ? new bootstrap.Modal(columnEditModalElement) : null;
    const columnDeleteModal = columnDeleteModalElement && window.bootstrap ? new bootstrap.Modal(columnDeleteModalElement) : null;
    const drawerRoot = document.getElementById('garantia-drawer-root');
    const drawerElement = drawerRoot?.querySelector('.garantia-drawer');
    const drawerContent = document.getElementById('garantiaDrawerContent');
    const DETAIL_REQUEST_TIMEOUT_MS = 15000;
    const copyStorageKey = 'garantias.copiedCard';
    const pendingCardIds = new Set();
    const sectionRequestVersions = new WeakMap();
    const detailState = { version: 0, id: '', layout: 'modal' };
    let currentDetailUrl = '';
    let currentDetailCardId = '';
    let currentDetailLayout = 'modal';
    let detailRequestController = null;
    let drawerBusy = false;
    const inlineSharedSlot = document.querySelector('[data-garantia-inline-shared-slot="1"]');
    const inlineSlotHome = document.querySelector('[data-garantia-inline-slot-home="1"]');
    let inlineFormLoadPromise = null;
    let inlineFormLoaded = false;
    let latestInlineTarget = null;
    const columnLoadRequests = new Map();
    let boardVersion = 0;

    if (drawerRoot) {
      drawerRoot.addEventListener('click', (e) => {
        const closeDrawerButton = e.target.closest('[data-garantia-drawer-close="1"]');
        if (closeDrawerButton) {
          e.preventDefault();
          e.stopPropagation();
          closeDrawer(false);
          return;
        }

        if (e.target.closest('[data-garantia-drawer-overlay="1"]')) {
          e.preventDefault();
          e.stopPropagation();
          closeDrawer(false);
          return;
        }
      });
    }

    async function readJsonResponse(response) {
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        let errorMsg = 'Respuesta inesperada del servidor.';
        if (response.status === 403) {
          errorMsg = 'Tu sesión o el token CSRF no son válidos. Recarga la página e inténtalo nuevamente.';
        }
        const error = new Error(errorMsg);
        error.status = response.status;
        throw error;
      }
      try {
        return await response.json();
      } catch (_) {
        const error = new Error('La respuesta JSON no es valida.');
        error.status = response.status;
        throw error;
      }
    }

    async function readDetailFormResponse(response) {
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        const data = await readJsonResponse(response);
        if (!response.ok) {
          const error = new Error(`Error ${response.status}`);
          error.status = response.status;
          error.data = data;
          throw error;
        }
        return data;
      }
      if (contentType.includes('text/html') && response.status === 400) {
        const html = await response.text();
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html;
        if (wrapper.querySelector('.garantia-detail__body')) {
          return {status: 'validation_error', html};
        }
      }
      const error = new Error('Respuesta inesperada del servidor.');
      error.status = response.status;
      throw error;
    }

    function requestErrorMessage(error) {
      const status = error?.status;
      if (status === 400) return 'Revisa los datos enviados e intenta de nuevo.';
      if (status === 403) return 'Tu sesion no tiene permiso para esta accion.';
      if (status === 404) return 'La garantia o el recurso ya no existe.';
      if (status === 405) return 'La accion no esta permitida.';
      if (status >= 500) return 'El servidor no pudo completar la accion.';
      return 'No se pudo completar la accion. Verifica tu conexion e intenta de nuevo.';
    }

    function getHtml(url, options = {}) {
      const controller = options.controller || new AbortController();
      let timeoutReached = false;
      const timeoutId = window.setTimeout(() => {
        timeoutReached = true;
        controller.abort();
      }, DETAIL_REQUEST_TIMEOUT_MS);

      return fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html' },
        signal: controller.signal,
      }).then((response) => {
        if (!response.ok) {
          const error = new Error(`Error ${response.status}`);
          error.status = response.status;
          throw error;
        }
        if (!(response.headers.get('content-type') || '').includes('text/html')) {
          const error = new Error('Respuesta HTML inesperada.');
          error.status = response.status;
          throw error;
        }
        return response.text();
      }).catch((error) => {
        if (error?.name === 'AbortError' && timeoutReached) {
          const timeoutError = new Error('Tiempo de espera agotado.');
          timeoutError.status = 408;
          throw timeoutError;
        }
        throw error;
      }).finally(() => {
        window.clearTimeout(timeoutId);
      });
    }

    function abortActiveDetailRequest() {
      if (!detailRequestController) return;
      detailRequestController.abort();
      detailRequestController = null;
    }

    function renderDetailLoadError(layout, url, message) {
      const safeMessage = message || 'No fue posible cargar los detalles. Intenta nuevamente.';
      const retryButton = url
        ? `<button type="button" class="btn btn-outline-secondary btn-sm mt-3" data-garantia-detail-retry="1" data-detail-url="${url}" data-detail-layout="${layout}">Reintentar</button>`
        : '';
      if (layout === 'drawer') {
        return `<div class="garantia-drawer__loading text-danger">${safeMessage}${retryButton}</div>`;
      }
      return `<div class="modal-body p-4 text-center text-danger">${safeMessage}${retryButton}</div>`;
    }

    function ensureEmptyState(column) {
      const cards = column.querySelectorAll('[data-garantia-card="1"]');
      let empty = column.querySelector('.garantia-empty');
      if (!cards.length && !empty) {
        empty = document.createElement('div');
        empty.className = 'garantia-empty';
        empty.textContent = 'Sin garantias.';
        column.appendChild(empty);
      }
      if (cards.length && empty) empty.remove();
    }

    function getColumnShell(column) {
      return column?.closest('[data-garantia-column="1"]') || null;
    }

    function getColumnsContainer() {
      return root.querySelector('[data-garantia-columns="1"]');
    }

    function getColumnShellById(columnId) {
      return root.querySelector(`[data-garantia-column="1"][data-columna-id="${columnId}"]`);
    }

    function getColumnIdFromElement(element) {
      return element?.closest('[data-garantia-column="1"]')?.dataset.columnaId || element?.dataset.columnaId || '';
    }

    function getColumnCodeFromElement(element) {
      return element?.closest('[data-garantia-column="1"]')?.dataset.columnaCodigo || element?.dataset.columnaCodigo || '';
    }

    function getColumnNameFromElement(element) {
      return element?.closest('[data-garantia-column="1"]')?.dataset.columnaNombre || element?.dataset.columnaNombre || '';
    }

    function getColumnTotal(column) {
      const shell = getColumnShell(column);
      const value = Number.parseInt(shell?.dataset.total || '', 10);
      return Number.isNaN(value) ? 0 : value;
    }

    function syncColumnState(column, totalOverride) {
      if (!column) return;
      const shell = getColumnShell(column);
      if (!shell) return;
      const loaded = column.querySelectorAll('[data-garantia-card="1"]').length;
      const parsedTotal = Number.parseInt(totalOverride, 10);
      const total = Number.isNaN(parsedTotal)
        ? Math.max(getColumnTotal(column), loaded)
        : Math.max(parsedTotal, loaded);
      shell.dataset.total = String(total);
      shell.dataset.loaded = String(loaded);
      const countNode = shell.querySelector('[data-garantias-column-count="1"]');
      if (countNode) countNode.textContent = String(total);
      const remaining = Math.max(0, total - loaded);
      const button = shell.querySelector('[data-garantia-load-more="1"]');
      if (button) {
        button.hidden = remaining === 0;
        button.textContent = remaining
          ? `Cargar más (${remaining})`
          : 'Cargar más';
      }
      ensureEmptyState(column);
    }

    function adjustColumnTotal(column, delta) {
      if (!column) return;
      syncColumnState(column, Math.max(0, getColumnTotal(column) + delta));
    }

    function updateColumnCount(column, value) {
      syncColumnState(column, value);
    }

    function updateColumnCountFromDom(column) {
      if (!column) return;
      syncColumnState(column);
    }

    function getEstadoLabel(value) {
      if (!value) return '';
      const column = root.querySelector(`[data-garantia-column="1"][data-columna-codigo="${value}"]`);
      const domValue = column?.dataset.columnaNombre || column?.querySelector('[data-garantia-column-title="1"]')?.textContent?.trim();
      return domValue || value;
    }

    function syncCardStateUI(card, estado, estadoLabel) {
      if (!card) return;
      card.dataset.garantiaState = estado;
      const select = card.querySelector('[data-garantia-state-select="1"]');
      const badge = card.querySelector('[data-garantia-state-badge="1"]');
      if (select) select.value = estado;
      if (badge) badge.textContent = estadoLabel || getEstadoLabel(estado);
      card.querySelectorAll('.kanban-status-control__option[data-status-option]').forEach((button) => {
        const isActive = button.dataset.statusOption === estado;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      });
    }

    function getCardId(card) {
      return card?.getAttribute('data-garantia-id') || '';
    }

    function isCardPending(card) {
      return pendingCardIds.has(getCardId(card));
    }

    function setCardPending(card, isPending) {
      if (!card) return;
      const cardId = getCardId(card);
      if (!cardId) return;

      if (isPending) {
        pendingCardIds.add(cardId);
        card.dataset.pending = 'true';
      } else {
        pendingCardIds.delete(cardId);
        delete card.dataset.pending;
      }
      card.setAttribute('aria-busy', isPending ? 'true' : 'false');

      const stateSelect = card.querySelector('[data-garantia-state-select="1"]');
      if (stateSelect) stateSelect.disabled = isPending;
    }

    function lockBodyScroll() {
      document.body.classList.add('garantia-drawer-open');
    }

    function unlockBodyScroll() {
      document.body.classList.remove('garantia-drawer-open');
    }

    function setDrawerBusy(value) {
      drawerBusy = value;
      if (drawerElement) {
        if (value) drawerElement.dataset.busy = '1';
        else delete drawerElement.dataset.busy;
      }
    }

    function openDrawerShell() {
      if (!drawerRoot || !drawerElement) return;
      drawerRoot.classList.add('is-open');
      drawerRoot.setAttribute('aria-hidden', 'false');
      lockBodyScroll();
      drawerElement.focus();
    }

    function closeDrawer(force) {
      if (!drawerRoot || !drawerElement) return;
      if (drawerBusy && !force) return;
      abortActiveDetailRequest();
      drawerRoot.classList.remove('is-open');
      drawerRoot.setAttribute('aria-hidden', 'true');
      unlockBodyScroll();
      detailState.version += 1;
      detailState.id = '';
      currentDetailUrl = '';
      currentDetailCardId = '';
      currentDetailLayout = drawerElement ? 'drawer' : 'modal';
    }

    function replaceCardHtml(cardId, html) {
      if (!cardId || !html) return;
      const currentCard = document.querySelector(`[data-garantia-id="${cardId}"]`);
      if (!currentCard) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextCard = wrapper.firstElementChild;
      if (!nextCard) return;
      invalidateColumnLoads();
      currentCard.replaceWith(nextCard);
      // Los listeners del tablero usan delegaciÃ³n. Esta inicializaciÃ³n solo
      // cubre widgets que viven dentro de la nueva tarjeta.
      if (window.initGarantiaSelects) window.initGarantiaSelects(nextCard);
      const column = nextCard.closest('.kanban-col');
      syncColumnState(column);
    }

    function removeCard(cardId) {
      const card = document.querySelector(`[data-garantia-id="${cardId}"]`);
      if (!card) return;
      const column = card.closest('.kanban-col');
      invalidateColumnLoads();
      card.remove();
      adjustColumnTotal(column, -1);
    }

    function setCardCommentCount(cardId, value) {
      const card = document.querySelector(`[data-garantia-id="${cardId}"]`);
      const node = card?.querySelector('.garantia-card__comments span');
      if (!node) return;
      const nextValue = parseInt(value, 10);
      node.textContent = String(Number.isNaN(nextValue) ? 0 : nextValue);
    }

    function replaceCommentsSection(root, html) {
      if (!root || !html) return false;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.querySelector('[data-garantia-comments-section="1"]');
      const currentSection = root.querySelector('[data-garantia-comments-section="1"]');
      if (!nextSection || !currentSection) return false;
      currentSection.replaceWith(nextSection);
      return true;
    }

    function showCommentFormError(root, message) {
      const errorNode = root?.querySelector('[data-garantia-comment-error="1"]');
      if (!errorNode) return;
      errorNode.textContent = message;
      errorNode.classList.remove('d-none');
    }

    function getDetailRoot(node) {
      return node?.closest('.garantia-drawer__content, .modal-content') || null;
    }

    function replaceDetailSection(root, selector, html) {
      if (!root || !html) return false;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const current = root.querySelector(selector);
      const next = wrapper.querySelector(selector);
      if (!current || !next) return false;
      current.replaceWith(next);
      return true;
    }

    function setSectionPending(section, pending) {
      if (!section) return;
      if (pending) section.dataset.pending = 'true';
      else delete section.dataset.pending;
      section.setAttribute('aria-busy', pending ? 'true' : 'false');
      section.querySelectorAll('button, input').forEach((control) => {
        control.disabled = pending;
      });
    }

    function setFormPending(form, pending) {
      if (!form) return;
      if (pending) form.dataset.pending = 'true';
      else delete form.dataset.pending;
      form.setAttribute('aria-busy', pending ? 'true' : 'false');
      form.querySelectorAll('button, input, select, textarea').forEach((control) => {
        control.disabled = pending;
      });
    }

    function submitDetailDeleteForm(deleteForm) {
      if (!deleteForm || deleteForm.dataset.pending === 'true') return;

      const fd = new FormData(deleteForm);
      const layout = deleteForm.querySelector('[name="layout"]')?.value || currentDetailLayout || 'modal';
      const csrfToken = window.getCSRFToken(deleteForm);

      if (!csrfToken) {
        throw new Error('No se encontro un token CSRF valido para eliminar la garantia.');
      }

      setFormPending(deleteForm, true);
      setDrawerBusy(layout === 'drawer');

      window.csrfFetch(deleteForm.getAttribute('action'), {
        method: 'POST',
        body: fd,
        headers: {
          'Accept': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
        }
      })
        .then((response) => {
          return readJsonResponse(response).then((data) => ({ ok: response.ok, status: response.status, data }));
        })
        .then(({ ok, status, data }) => {
          if (!ok) {
            const error = new Error(`Error ${status}`);
            error.status = status;
            error.data = data;
            throw error;
          }
          if (!data.deleted) {
            throw new Error('Respuesta de eliminacion inesperada.');
          }
          removeCard(data.id || data.garantia_id);
          closeDrawer(true);
          if (modalInstance && modalElement?.classList.contains('show')) {
            modalInstance.hide();
          }
        })
        .catch((error) => {
          const rootElement = getDetailRoot(deleteForm);
          if (rootElement) {
            showCommentFormError(rootElement, requestErrorMessage(error));
          }
          console.error('No se pudo eliminar la garantia:', error);
        })
        .finally(() => {
          if (deleteForm.isConnected) setFormPending(deleteForm, false);
          setDrawerBusy(false);
        });
    }

    function syncCardResourceCount(cardId, resource, value) {
      const card = document.querySelector(`[data-garantia-id="${cardId}"]`);
      const node = card?.querySelector(`[data-garantia-card-${resource}-count="1"]`);
      if (node) node.textContent = String(Number.parseInt(value, 10) || 0);
    }

    async function postDetailSection(section, form, formData) {
      const version = (sectionRequestVersions.get(section) || 0) + 1;
      sectionRequestVersions.set(section, version);
      const response = await window.csrfFetch(form.action, { method: 'POST', body: formData, headers: {'Accept': 'application/json'} });
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        throw new Error('Respuesta inesperada del servidor.');
      }
      const data = await readJsonResponse(response);
      if (sectionRequestVersions.get(section) !== version) return {stale: true};
      return {ok: response.ok, data};
    }

    function setInlineCreateButtonsDisabled(disabled) {
      document.querySelectorAll('[data-garantia-inline-open="1"]').forEach((button) => {
        button.disabled = disabled;
      });
    }

    function destroyInlineCreateSelects(root) {
      if (!root) return;
      root.querySelectorAll('select').forEach((select) => {
        if (select.tomselect) {
          select.tomselect.destroy();
        }
      });
    }

    function initInlineCreateSelects(root) {
      if (!root || !window.initGarantiaSelects) return;
      root.querySelectorAll('select').forEach((select) => {
        if (select.tomselect) return;
      });
      window.initGarantiaSelects(root);
    }

    function ensureToastHost() {
      let host = document.getElementById('garantia-toast-host');
      if (host) return host;
      host = document.createElement('div');
      host.id = 'garantia-toast-host';
      host.className = 'toast-container position-fixed top-0 end-0 p-3';
      host.style.zIndex = '1095';
      document.body.appendChild(host);
      return host;
    }

    function showToast(message, level) {
      const host = ensureToastHost();
      const toast = document.createElement('div');
      const bgClass = level === 'danger' ? 'text-bg-danger' : 'text-bg-success';
      toast.className = `toast align-items-center border-0 ${bgClass}`;
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      toast.setAttribute('aria-atomic', 'true');
      toast.innerHTML = `
        <div class="d-flex">
          <div class="toast-body">${message || ''}</div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
        </div>
      `;
      host.appendChild(toast);
      if (window.bootstrap?.Toast) {
        const instance = bootstrap.Toast.getOrCreateInstance(toast, { delay: 3200 });
        toast.addEventListener('hidden.bs.toast', () => toast.remove(), { once: true });
        instance.show();
      } else {
        window.setTimeout(() => toast.remove(), 3200);
      }
    }

    function readCopiedCard() {
      try {
        const rawValue = window.sessionStorage?.getItem(copyStorageKey) || '';
        if (!rawValue) return null;
        const data = JSON.parse(rawValue);
        const parsedId = Number.parseInt(data?.tarjeta_id, 10);
        if (data?.modulo !== 'garantias' || Number.isNaN(parsedId) || parsedId <= 0) {
          return null;
        }
        return { modulo: 'garantias', tarjeta_id: parsedId };
      } catch (_) {
        return null;
      }
    }

    function syncCopyActions() {
      const copiedCard = readCopiedCard();
      const enabled = Boolean(copiedCard);
      root.querySelectorAll('[data-garantia-column-paste="1"]').forEach((button) => {
        button.disabled = !enabled;
      });
      root.querySelectorAll('[data-garantia-copy-clear="1"]').forEach((button) => {
        button.disabled = !enabled;
      });
    }

    function writeCopiedCard(cardId) {
      window.sessionStorage?.setItem(
        copyStorageKey,
        JSON.stringify({ modulo: 'garantias', tarjeta_id: Number(cardId) })
      );
      syncCopyActions();
    }

    function clearCopiedCard() {
      window.sessionStorage?.removeItem(copyStorageKey);
      syncCopyActions();
    }

    function getCurrentColumnOrder() {
      return Array.from(root.querySelectorAll('[data-garantia-column-item="1"] [data-garantia-column="1"]'))
        .map((node) => node.dataset.columnaId)
        .filter(Boolean);
    }

    function syncDeleteDestinationOptions(currentColumnId) {
      const select = columnDeleteModalElement?.querySelector('[name="columna_destino_id"]');
      if (!select) return;
      const currentValue = select.value;
      const options = ['<option value="">Selecciona una columna</option>'];
      root.querySelectorAll('[data-garantia-column="1"]').forEach((column) => {
        if (column.dataset.columnaId === String(currentColumnId || '')) return;
        options.push(
          `<option value="${column.dataset.columnaId}">${column.dataset.columnaNombre || column.dataset.estado || ''}</option>`
        );
      });
      select.innerHTML = options.join('');
      if (currentValue && select.querySelector(`option[value="${currentValue}"]`)) {
        select.value = currentValue;
      }
    }

    function setColumnFormError(scope, message) {
      const errorNode = scope?.querySelector('[data-garantia-column-create-error="1"], [data-garantia-column-edit-error="1"], [data-garantia-column-delete-error="1"]');
      if (!errorNode) return;
      if (message) {
        errorNode.textContent = message;
        errorNode.classList.remove('d-none');
      } else {
        errorNode.textContent = '';
        errorNode.classList.add('d-none');
      }
    }

    function extractJsonErrors(error) {
      if (!error?.data?.errors) return '';
      const chunks = [];
      Object.values(error.data.errors).forEach((items) => {
        (items || []).forEach((item) => {
          if (item?.message) chunks.push(item.message);
        });
      });
      return chunks.join(' ');
    }

    function updateColumnPresentation(columnShell, payload) {
      if (!columnShell || !payload) return;
      if (payload.columna_id) columnShell.dataset.columnaId = String(payload.columna_id);
      if (payload.columna_codigo) {
        columnShell.dataset.columnaCodigo = payload.columna_codigo;
        columnShell.dataset.estado = payload.columna_codigo;
      }
      if (payload.nombre) {
        columnShell.dataset.columnaNombre = payload.nombre;
        const title = columnShell.querySelector('[data-garantia-column-title="1"]');
        if (title) title.textContent = payload.nombre;
        const addButton = columnShell.querySelector('[data-garantia-inline-open="1"]');
        if (addButton) addButton.dataset.estadoLabel = payload.nombre;
      }
      const body = columnShell.querySelector('.kanban-col');
      if (body && payload.columna_codigo) {
        body.dataset.columnaCodigo = payload.columna_codigo;
        body.dataset.estado = payload.columna_codigo;
      }
      if (body && payload.nombre) {
        body.dataset.columnaNombre = payload.nombre;
      }
      syncCopyActions();
    }

    function buildInlineOpenButtonMarkup(shell) {
      const columnId = shell?.dataset.columnaId || '';
      const state = shell?.dataset.estado || '';
      const label = shell?.dataset.columnaNombre || shell?.querySelector('[data-garantia-column-title="1"]')?.textContent?.trim() || '';
      return `
        <button
          type="button"
          class="btn btn-sm garantias-column__add-btn"
          data-garantia-inline-open="1"
          data-columna-id="${columnId}"
          data-estado="${state}"
          data-estado-label="${label}">
          + Nueva garantia
        </button>
      `.trim();
    }

    function ensureColumnActions(shell) {
      if (!shell) return null;
      let actions = shell.querySelector('.garantias-column__actions');
      if (!actions) {
        actions = document.createElement('div');
        actions.className = 'garantias-column__actions px-3 pt-3';
        const header = shell.querySelector('.garantias-column__header');
        header?.insertAdjacentElement('afterend', actions);
      }
      return actions;
    }

    function syncInlineCreateAccess() {
      const shells = Array.from(root.querySelectorAll('[data-garantia-column="1"]'));
      const firstShell = shells[0] || null;
      const currentActions = root.querySelector('.garantias-column__actions');

      if (!firstShell) {
        currentActions?.remove();
        closeInlineCreateForm();
        return;
      }

      const targetActions = ensureColumnActions(firstShell);
      if (!targetActions) return;

      if (currentActions && currentActions !== targetActions) {
        if (inlineSharedSlot && !inlineSharedSlot.classList.contains('d-none')) {
          closeInlineCreateForm();
        }
        currentActions.remove();
      }

      targetActions.innerHTML = buildInlineOpenButtonMarkup(firstShell);
    }

    function insertCopiedCardIntoColumn(data) {
      const columnShell = getColumnShellById(String(data.columna_id));
      const column = columnShell?.querySelector('.kanban-col');
      if (!column || typeof data.html !== 'string') {
        throw new Error('Respuesta de tarjeta invalida.');
      }
      const wrapper = document.createElement('div');
      wrapper.innerHTML = data.html;
      const card = wrapper.querySelector('[data-garantia-card="1"]');
      if (!card) {
        throw new Error('No se pudo renderizar la tarjeta copiada.');
      }
      invalidateColumnLoads();
      column.querySelector('.garantia-empty')?.remove();
      column.prepend(card);
      updateColumnCount(column, data.column_count);
      window.initGarantiaSelects?.(card);
    }

    function addInlineLinkRow(root) {
      const template = root?.querySelector('[data-garantia-link-template="1"]');
      const rows = root?.querySelector('[data-garantia-link-rows="1"]');
      if (!template || !rows) return;
      rows.insertAdjacentHTML('beforeend', template.innerHTML.trim());
    }

    function removeInlineLinkRow(button) {
      const root = button?.closest('[data-garantia-inline-links="1"]');
      const rows = root?.querySelector('[data-garantia-link-rows="1"]');
      const row = button?.closest('[data-garantia-link-row="1"]');
      if (!rows || !row) return;
      const allRows = rows.querySelectorAll('[data-garantia-link-row="1"]');
      if (allRows.length <= 1) {
        row.querySelectorAll('input').forEach((input) => {
          input.value = '';
        });
        return;
      }
      row.remove();
    }

    function inlineTargetFromButton(button) {
      const column = button?.closest('.garantias-column');
      const estado = button?.dataset.estado || '';
      if (!column || !estado) return null;
      return {
        column,
        estado,
        label: button.dataset.estadoLabel || getEstadoLabel(estado),
      };
    }

    function findInlineTarget(estado) {
      const button = Array.from(
        document.querySelectorAll('[data-garantia-inline-open="1"]')
      ).find((item) => item.dataset.estado === estado);
      return inlineTargetFromButton(button);
    }

    function moveInlineSlot(target) {
      if (!inlineSharedSlot || !target?.column) return;
      const actions = target.column.querySelector('.garantias-column__actions');
      if (actions) actions.after(inlineSharedSlot);
    }

    function configureInlineSlot(target) {
      if (!inlineSharedSlot || !target) return;
      moveInlineSlot(target);
      inlineSharedSlot.dataset.estado = target.estado;
      const form = inlineSharedSlot.querySelector('[data-garantia-inline-form="1"]');
      const estadoInput = form?.querySelector('[name="estado"]');
      const destination = inlineSharedSlot.querySelector('[data-garantia-inline-destination="1"]');
      if (estadoInput) estadoInput.value = target.estado;
      if (destination) destination.textContent = target.label;
      inlineSharedSlot.classList.remove('d-none');
    }

    function showInlineLoading(target) {
      if (!inlineSharedSlot || !target) return;
      moveInlineSlot(target);
      inlineSharedSlot.classList.remove('d-none');
      inlineSharedSlot.innerHTML = '<div class="text-muted small py-2" data-garantia-inline-loading="1">Cargando formulario...</div>';
    }

    function parseInlineFragment(html) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const fragments = wrapper.querySelectorAll('[data-garantia-inline-form-fragment="1"]');
      const forms = wrapper.querySelectorAll('[data-garantia-inline-form="1"]');
      if (fragments.length !== 1 || forms.length !== 1) {
        throw new Error('El servidor no devolvio el formulario esperado.');
      }
      return fragments[0].outerHTML;
    }

    function loadInlineCreateForm() {
      if (inlineFormLoaded) return Promise.resolve();
      if (inlineFormLoadPromise) return inlineFormLoadPromise;

      setInlineCreateButtonsDisabled(true);
      inlineFormLoadPromise = fetch(inlineFormUrl, {
        method: 'GET',
        credentials: 'same-origin',
        redirect: 'error',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'text/html',
        },
      })
        .then(async (response) => {
          if (!response.ok || response.redirected) {
            const error = new Error(`Error ${response.status}`);
            error.status = response.status;
            throw error;
          }
          if (!(response.headers.get('content-type') || '').includes('text/html')) {
            throw new Error('Respuesta HTML inesperada.');
          }
          return parseInlineFragment(await response.text());
        })
        .then((html) => {
          if (!inlineSharedSlot) return;
          inlineSharedSlot.innerHTML = html;
          inlineFormLoaded = true;
          if (latestInlineTarget) configureInlineSlot(latestInlineTarget);
          initInlineCreateSelects(inlineSharedSlot);
        })
        .catch((error) => {
          inlineFormLoaded = false;
          if (inlineSharedSlot) {
            inlineSharedSlot.innerHTML = '<div class="alert alert-danger py-2 px-3 small mb-0" data-garantia-inline-load-error="1">No se pudo cargar el formulario. Intenta de nuevo.</div>';
            inlineSharedSlot.classList.remove('d-none');
          }
          throw error;
        })
        .finally(() => {
          inlineFormLoadPromise = null;
          setInlineCreateButtonsDisabled(false);
        });
      return inlineFormLoadPromise;
    }

    function openInlineCreateForm(button) {
      const target = inlineTargetFromButton(button);
      if (!target) return;
      latestInlineTarget = target;
      if (inlineFormLoaded) {
        configureInlineSlot(target);
        inlineSharedSlot?.querySelector('input, select, textarea')?.focus();
        return;
      }
      showInlineLoading(target);
      loadInlineCreateForm()
        .then(() => {
          if (latestInlineTarget) configureInlineSlot(latestInlineTarget);
          inlineSharedSlot?.querySelector('input, select, textarea')?.focus();
        })
        .catch((error) => {
          console.error('No se pudo cargar el formulario inline:', error);
        });
    }

    function closeInlineCreateForm() {
      latestInlineTarget = null;
      if (!inlineSharedSlot) return;
      inlineSharedSlot.classList.add('d-none');
      if (inlineSlotHome) inlineSlotHome.appendChild(inlineSharedSlot);
    }

    function replaceInlineCreateForm(html, target) {
      if (!inlineSharedSlot) return;
      destroyInlineCreateSelects(inlineSharedSlot);
      inlineSharedSlot.innerHTML = parseInlineFragment(html);
      inlineFormLoaded = true;
      latestInlineTarget = target;
      configureInlineSlot(target);
      initInlineCreateSelects(inlineSharedSlot);
    }

    async function readInlineCreateResponse(response) {
      if (!(response.headers.get('content-type') || '').includes('application/json')) {
        throw new Error('Respuesta JSON inesperada.');
      }
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(`Error ${response.status}`);
        error.status = response.status;
        error.data = data;
        throw error;
      }
      return data;
    }

    function insertCardAt(column, card, index) {
      if (!column || !card) return;
      const cards = Array.from(column.querySelectorAll('[data-garantia-card="1"]')).filter((node) => node !== card);
      if (typeof index !== 'number' || index < 0 || index >= cards.length) {
        column.appendChild(card);
        return;
      }
      column.insertBefore(card, cards[index]);
    }

    async function moveGarantiaCard({
      card,
      targetStatus,
      targetColumn,
      sourceColumn,
      sourceIndex,
      targetIndex,
      trigger,
      triggerElement,
    }) {
      if (!card || !targetStatus || !targetColumn || !sourceColumn) {
        throw new Error('Movimiento invalido');
      }
      if (isCardPending(card)) {
        throw new Error('La garantia ya se esta actualizando');
      }

      const previousState = sourceColumn.dataset.estado || '';
      const sameColumn = sourceColumn === targetColumn;

      invalidateColumnLoads();
      setCardPending(card, true);
      const fd = new FormData();
      fd.set('garantia_id', getCardId(card));
      fd.set('nuevo_estado', targetStatus);

      try {
        const response = await postGarantiaStateUpdate(fd, triggerElement || card);
        const data = await readJsonResponse(response);
        if (!response.ok) {
          const error = new Error(`Error ${response.status}`);
          error.status = response.status;
          error.data = data;
          throw error;
        }
        if (data.status !== 'ok' || String(data.id) !== getCardId(card)) {
          const error = new Error(data.error || 'Estado no actualizado.');
          error.data = data;
          throw error;
        }

        syncCardStateUI(card, data.estado || targetStatus, data.estado_label);
        if (!sameColumn) {
          adjustColumnTotal(sourceColumn, -1);
          adjustColumnTotal(targetColumn, 1);
        } else {
          syncColumnState(targetColumn);
        }
        return data;
      } catch (error) {
        if (sameColumn) {
          insertCardAt(sourceColumn, card, sourceIndex);
          syncColumnState(sourceColumn);
        } else {
          insertCardAt(sourceColumn, card, sourceIndex);
          syncColumnState(sourceColumn);
          syncColumnState(targetColumn);
        }
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        throw error;
      } finally {
        ensureEmptyState(sourceColumn);
        ensureEmptyState(targetColumn);
        setCardPending(card, false);
      }
    }

    function getLoadedCardIds(column) {
      return Array.from(
        column?.querySelectorAll('[data-garantia-card="1"]') || []
      )
        .map((card) => getCardId(card))
        .filter(Boolean);
    }

    function getSelectedUserId() {
      return document.getElementById('GarantiasUserFilter')?.value || '';
    }

    function setColumnLoading(shell, isLoading) {
      const button = shell?.querySelector('[data-garantia-load-more="1"]');
      const indicator = shell?.querySelector('[data-garantia-load-indicator="1"]');
      if (button) {
        button.disabled = isLoading;
        button.setAttribute('aria-busy', isLoading ? 'true' : 'false');
      }
      indicator?.classList.toggle('d-none', !isLoading);
    }

    function showColumnLoadError(shell, message) {
      const node = shell?.querySelector('[data-garantia-load-error="1"]');
      if (!node) return;
      node.textContent = message || '';
      node.classList.toggle('d-none', !message);
    }

    function getAjaxErrorMessage(error) {
      const serverMessage = error?.data?.error || error?.data?.detail || error?.data?.message;
      if (serverMessage) return serverMessage;
      if (error?.message && !/^Error \d+$/.test(error.message)) return error.message;
      return requestErrorMessage(error);
    }

    function postGarantiaStateUpdate(formData, triggerElement) {
      const csrfToken = window.getCSRFToken?.(triggerElement?.closest('form') || triggerElement || document);
      if (!csrfToken) {
        const error = new Error('No se encontro un token CSRF valido. Recarga la pagina e intenta nuevamente.');
        error.status = 403;
        throw error;
      }
      return fetch(updateUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
        body: formData,
      });
    }

    function invalidateColumnLoads() {
      boardVersion += 1;
      columnLoadRequests.forEach((entry) => entry.controller.abort());
      columnLoadRequests.clear();
    }

    function loadMoreCards(button) {
      const shell = button?.closest('[data-garantia-column="1"]');
      const column = shell?.querySelector('.kanban-col');
      const state = shell?.dataset.estado || column?.dataset.estado || '';
      const loadUrl = button?.dataset.loadUrl || '';
      if (!shell || !column || !state || !loadUrl) {
        return Promise.reject(new Error('Columna no disponible.'));
      }

      const existing = columnLoadRequests.get(state);
      if (existing) return existing.promise;

      const loadedIds = getLoadedCardIds(column);
      const offset = loadedIds.length;
      const url = new URL(loadUrl, window.location.origin);
      url.searchParams.set('offset', String(offset));
      url.searchParams.set('loaded', loadedIds.join(','));
      const selectedUserId = getSelectedUserId();
      if (selectedUserId) url.searchParams.set('usuario', selectedUserId);

      const controller = new AbortController();
      const requestVersion = boardVersion;
      setColumnLoading(shell, true);
      showColumnLoadError(shell, '');

      const request = fetch(`${url.pathname}${url.search}`, {
        method: 'GET',
        credentials: 'same-origin',
        signal: controller.signal,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
      })
        .then(async (response) => {
          const contentType = response.headers.get('content-type') || '';
          if (!contentType.includes('application/json')) {
            throw new Error('Respuesta JSON invalida.');
          }
          const data = await response.json();
          if (!response.ok || !data.ok) {
            throw new Error(data.error || `Error ${response.status}`);
          }
          return data;
        })
        .then((data) => {
          if (requestVersion !== boardVersion || controller.signal.aborted) {
            return null;
          }
          const staleIds = Array.isArray(data.stale_ids)
            ? data.stale_ids.map((value) => String(value))
            : null;
          const uniqueStaleIds = staleIds ? new Set(staleIds) : null;
          if (
            data.estado !== state ||
            !Number.isInteger(data.loaded) ||
            data.loaded < 0 ||
            !Number.isInteger(data.next_offset) ||
            !uniqueStaleIds ||
            uniqueStaleIds.size !== staleIds.length ||
            staleIds.some((cardId) => !loadedIds.includes(cardId)) ||
            data.next_offset !== offset - staleIds.length + data.loaded ||
            !Number.isInteger(data.total) ||
            data.total < data.next_offset ||
            typeof data.has_more !== 'boolean' ||
            typeof data.html !== 'string' ||
            (data.loaded > 0 && !data.html.trim()) ||
            (data.loaded === 0 && data.has_more)
          ) {
            throw new Error('Respuesta incompatible con la columna.');
          }

          staleIds.forEach((cardId) => {
            Array.from(column.querySelectorAll('[data-garantia-card="1"]'))
              .find((card) => getCardId(card) === cardId)
              ?.remove();
          });
          const wrapper = document.createElement('div');
          wrapper.innerHTML = data.html;
          const cards = Array.from(wrapper.children).filter(
            (node) => node.matches?.('[data-garantia-card="1"]')
          );
          if (cards.length !== data.loaded) {
            throw new Error('Cantidad de tarjetas inesperada.');
          }
          const existingIds = new Set(getLoadedCardIds(column));
          const responseIds = new Set();
          cards.forEach((card) => {
            const cardId = getCardId(card);
            if (
              !cardId ||
              existingIds.has(cardId) ||
              responseIds.has(cardId) ||
              card.dataset.garantiaState !== state
            ) {
              throw new Error('Tarjeta duplicada o incompatible.');
            }
            responseIds.add(cardId);
          });

          column.querySelector('.garantia-empty')?.remove();
          const fragment = document.createDocumentFragment();
          cards.forEach((card) => fragment.appendChild(card));
          column.appendChild(fragment);
          syncColumnState(column, data.total);
          button.hidden = !data.has_more;
          return data;
        })
        .catch((error) => {
          if (error.name === 'AbortError' || requestVersion !== boardVersion) {
            return null;
          }
          showColumnLoadError(
            shell,
            'No se pudieron cargar las tarjetas. Intenta nuevamente.'
          );
          throw error;
        })
        .finally(() => {
          if (columnLoadRequests.get(state)?.promise === request) {
            columnLoadRequests.delete(state);
            if (shell.isConnected) setColumnLoading(shell, false);
          }
        });

      columnLoadRequests.set(state, {promise: request, controller});
      return request;
    }

    function submitColumnOrder() {
      const ids = getCurrentColumnOrder();
      if (!columnReorderUrl || !ids.length) return Promise.resolve();
      const fd = new FormData();
      ids.forEach((id) => fd.append('columnas[]', id));
      return window.csrfFetch(columnReorderUrl, {
        method: 'POST',
        body: fd,
        headers: {'Accept': 'application/json'}
      }).then(readJsonResponse).then((data) => {
        if (!data.ok) throw new Error(data.error || 'No se pudo reordenar.');
        return data;
      });
    }

    function initSortable() {
      if (typeof Sortable === 'undefined') return;
      const columnsContainer = getColumnsContainer();
      if (columnsContainer && columnsContainer.dataset.sortableReady !== '1') {
        columnsContainer.dataset.sortableReady = '1';
        Sortable.create(columnsContainer, {
          animation: 150,
          draggable: '[data-garantia-column-item="1"]',
          ghostClass: 'garantia-ghost',
          dragClass: 'garantia-drag',
          onEnd: function () {
            syncInlineCreateAccess();
            submitColumnOrder().catch((error) => {
              console.error('No se pudo reordenar las columnas:', error);
              showToast(requestErrorMessage(error), 'danger');
            });
          }
        });
      }
      document.querySelectorAll('.kanban-col').forEach((column) => {
        if (column.dataset.sortableReady === '1') return;
        column.dataset.sortableReady = '1';
        Sortable.create(column, {
          group: 'garantias-kanban',
          animation: 150,
          ghostClass: 'garantia-ghost',
          dragClass: 'garantia-drag',
          onMove: function (evt) {
            if (isCardPending(evt.dragged)) return false;
            return true;
          },
          onEnd: function (evt) {
            const card = evt.item;
            const target = evt.to;
            const source = evt.from;
            const garantiaId = card.getAttribute('data-garantia-id');
            const nuevoEstado = target.getAttribute('data-estado');
            const sourceIndex = evt.oldIndex;
            const targetIndex = evt.newIndex;
            if (!garantiaId || !nuevoEstado || source === target || isCardPending(card)) {
              if (isCardPending(card) && source !== target) {
                insertCardAt(source, card, sourceIndex);
              }
              ensureEmptyState(source);
              ensureEmptyState(target);
              return;
            }

            moveGarantiaCard({
              card,
              targetStatus: nuevoEstado,
              targetColumn: target,
              sourceColumn: source,
              sourceIndex,
              targetIndex,
              trigger: 'drag',
              triggerElement: card,
            }).catch((error) => {
              console.error('No se pudo mover la garantia:', error);
            });
          },
        });
        syncColumnState(column);
      });
    }

    function loadModal(url, cardId) {
      if (!modalContent || !modalInstance) return;
      abortActiveDetailRequest();
      detailRequestController = new AbortController();
      const version = detailState.version + 1;
      detailState.version = version;
      detailState.id = cardId || '';
      detailState.layout = 'modal';
      modalContent.innerHTML = '<div class="modal-body p-4 text-center text-muted">Cargando...</div>';
      modalInstance.show();
      getHtml(url, {controller: detailRequestController})
        .then((html) => {
          if (detailState.version !== version || detailState.id !== cardId || !modalElement.classList.contains('show')) return;
          if (!html || !html.trim()) {
            const error = new Error('Respuesta HTML vacia.');
            error.status = 200;
            throw error;
          }
          modalContent.innerHTML = html;
          if (window.initGarantiaSelects) window.initGarantiaSelects(modalContent);
        })
        .catch((error) => {
          if (detailState.version !== version || detailState.id !== cardId || !modalElement.classList.contains('show')) return;
          if (error?.name === 'AbortError') return;
          console.error('No se pudo cargar la garantia:', error);
          modalContent.innerHTML = renderDetailLoadError('modal', url, 'No fue posible cargar los detalles. Intenta nuevamente.');
        })
        .finally(() => {
          if (detailState.version === version) detailRequestController = null;
        });
    }

    function loadDrawer(url, cardId) {
      if (!drawerRoot || !drawerElement || !drawerContent) return;
      abortActiveDetailRequest();
      detailRequestController = new AbortController();
      const detailUrl = url.includes('?') ? `${url}&layout=drawer` : `${url}?layout=drawer`;
      const version = detailState.version + 1;
      detailState.version = version;
      detailState.id = cardId || '';
      detailState.layout = 'drawer';
      currentDetailUrl = detailUrl;
      currentDetailCardId = cardId || '';
      currentDetailLayout = 'drawer';
      drawerContent.innerHTML = '<div class="garantia-drawer__loading">Cargando...</div>';
      openDrawerShell();
      setDrawerBusy(true);
      getHtml(detailUrl, {controller: detailRequestController})
        .then((html) => {
          if (detailState.version !== version || detailState.id !== cardId || !drawerRoot.classList.contains('is-open')) return;
          if (!html || !html.trim()) {
            const error = new Error('Respuesta HTML vacia.');
            error.status = 200;
            throw error;
          }
          drawerContent.innerHTML = html;
          if (window.initGarantiaSelects) window.initGarantiaSelects(drawerContent);
        })
        .catch((error) => {
          if (detailState.version !== version || detailState.id !== cardId || !drawerRoot.classList.contains('is-open')) return;
          if (error?.name === 'AbortError') return;
          console.error('No se pudo cargar la garantia:', error);
          drawerContent.innerHTML = renderDetailLoadError(
            'drawer',
            detailUrl,
            'No fue posible cargar los detalles. Intenta nuevamente.'
          );
        })
        .finally(() => {
          if (detailState.version === version) {
            detailRequestController = null;
            setDrawerBusy(false);
          }
        });
    }

    function refreshActiveDetail() {
      if (!currentDetailUrl) return Promise.resolve();
      const container = currentDetailLayout === 'drawer' ? drawerContent : modalContent;
      if (!container) return Promise.resolve();
      setDrawerBusy(currentDetailLayout === 'drawer');
      return getHtml(currentDetailUrl)
        .then((html) => {
          container.innerHTML = html;
          if (window.initGarantiaSelects) window.initGarantiaSelects(container);
        })
        .catch((error) => {
          console.error('No se pudo refrescar el detalle de la garantia:', error);
        })
        .finally(() => {
          setDrawerBusy(false);
        });
    }

    function handleGarantiaStateChange(stateSelect, triggerElement = stateSelect) {
      const card = stateSelect?.closest('[data-garantia-card="1"]');
      const sourceColumn = card?.closest('.kanban-col');
      const previousState = card?.dataset.garantiaState || sourceColumn?.dataset.estado || stateSelect?.dataset.previousValue || stateSelect?.value;
      const nuevoEstado = stateSelect?.value || '';
      if (!card || !sourceColumn || !stateSelect || !nuevoEstado || previousState === nuevoEstado) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      if (isCardPending(card)) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      const targetColumn = document.querySelector(`.kanban-col[data-estado="${nuevoEstado}"]`);
      if (!targetColumn) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      showColumnLoadError(getColumnShell(sourceColumn), '');
      showColumnLoadError(getColumnShell(targetColumn), '');

      const sourceIndex = Array.from(sourceColumn.querySelectorAll('[data-garantia-card="1"]')).indexOf(card);
      const targetIndex = 0;
      if (sourceColumn !== targetColumn) {
        const emptyState = targetColumn.querySelector('.garantia-empty');
        if (emptyState) emptyState.remove();
        targetColumn.prepend(card);
      }

      moveGarantiaCard({
        card,
        targetStatus: nuevoEstado,
        targetColumn,
        sourceColumn,
        sourceIndex,
        targetIndex,
        trigger: triggerElement === stateSelect ? 'select' : 'button',
        triggerElement,
      }).catch((error) => {
        const message = getAjaxErrorMessage(error);
        showColumnLoadError(getColumnShell(sourceColumn), message);
        if (sourceColumn !== targetColumn) {
          showColumnLoadError(getColumnShell(targetColumn), message);
        }
        console.error('No se pudo actualizar el estado de la garantia:', error);
      });
    }

    root.addEventListener('change', (e) => {
      if (e.target && e.target.id === 'GarantiasUserFilter') {
        invalidateColumnLoads();
        e.target.form?.submit();
        return;
      }

      const stateSelect = e.target.closest('[data-garantia-state-select="1"]');
      if (!stateSelect) return;
      handleGarantiaStateChange(stateSelect);
    });

    root.addEventListener('click', (e) => {
      const statusButton = e.target.closest('.kanban-status-control__option[data-status-option]');
      if (statusButton) {
        e.preventDefault();
        // El flujo de cambio por botones conserva a statusButton como disparador
        // original para CSRF y para el seguimiento del origen del movimiento:
        // triggerElement: statusButton,
        const control = statusButton.closest('.kanban-status-control');
        const stateSelect = control?.querySelector('[data-garantia-state-select="1"]');
        const card = statusButton.closest('[data-garantia-card="1"]');
        const previousState = card?.dataset.garantiaState || stateSelect?.value || '';
        const nextState = statusButton.dataset.statusOption || '';
        if (!stateSelect || !nextState) return;
        if (stateSelect.disabled) {
          syncCardStateUI(card, previousState, getEstadoLabel(previousState));
          return;
        }
        stateSelect.dataset.previousValue = previousState;
        stateSelect.value = nextState;
        handleGarantiaStateChange(stateSelect, statusButton);
        return;
      }

      const loadMoreButton = e.target.closest('[data-garantia-load-more="1"]');
      if (loadMoreButton) {
        e.preventDefault();
        loadMoreCards(loadMoreButton).catch((error) => {
          console.error('No se pudieron cargar mas garantias:', error);
        });
        return;
      }

      const inlineOpenButton = e.target.closest('[data-garantia-inline-open="1"]');
      if (inlineOpenButton) {
        e.preventDefault();
        openInlineCreateForm(inlineOpenButton);
        return;
      }

      const copyCardButton = e.target.closest('[data-garantia-copy-card="1"]');
      if (copyCardButton) {
        e.preventDefault();
        e.stopPropagation();
        const cardId = copyCardButton.dataset.tarjetaId || copyCardButton.closest('[data-garantia-card="1"]')?.dataset.garantiaId || '';
        if (!cardId) return;
        writeCopiedCard(cardId);
        showToast('Tarjeta copiada. Selecciona una columna para pegarla.', 'success');
        return;
      }

      const pasteCardButton = e.target.closest('[data-garantia-column-paste="1"]');
      if (pasteCardButton) {
        e.preventDefault();
        const copiedCard = readCopiedCard();
        const columnShell = pasteCardButton.closest('[data-garantia-column="1"]');
        const pasteUrl = columnShell?.dataset.pasteUrl || '';
        if (!copiedCard || !pasteUrl) {
          syncCopyActions();
          return;
        }
        pasteCardButton.disabled = true;
        const fd = new FormData();
        fd.append('tarjeta_id', String(copiedCard.tarjeta_id));
        fd.append('modulo', copiedCard.modulo);
        window.csrfFetch(pasteUrl, {
          method: 'POST',
          body: fd,
          headers: {'Accept': 'application/json'}
        })
          .then((response) => readJsonResponse(response).then((data) => ({ ok: response.ok, status: response.status, data })))
          .then(({ ok, status, data }) => {
            if (!ok || !data.ok) {
              const error = new Error(`Error ${status}`);
              error.status = status;
              error.data = data;
              throw error;
            }
            insertCopiedCardIntoColumn(data);
            showToast('Tarjeta pegada correctamente.', 'success');
          })
          .catch((error) => {
            showToast(error?.data?.error || requestErrorMessage(error), 'danger');
          })
          .finally(() => {
            syncCopyActions();
          });
        return;
      }

      const clearCopyButton = e.target.closest('[data-garantia-copy-clear="1"]');
      if (clearCopyButton) {
        e.preventDefault();
        clearCopiedCard();
        showToast('Copia cancelada.', 'success');
        return;
      }

      const columnEditOpenButton = e.target.closest('[data-garantia-column-edit-open="1"]');
      if (columnEditOpenButton) {
        e.preventDefault();
        const columnShell = columnEditOpenButton.closest('[data-garantia-column="1"]');
        const form = columnEditModalElement?.querySelector('[data-garantia-column-edit-form="1"]');
        if (!columnShell || !form) return;
        form.elements.columna_id.value = columnShell.dataset.columnaId || '';
        form.elements.nombre.value = columnShell.dataset.columnaNombre || '';
        setColumnFormError(form, '');
        columnEditModal?.show();
        return;
      }

      const columnDeleteOpenButton = e.target.closest('[data-garantia-column-delete-open="1"]');
      if (columnDeleteOpenButton) {
        e.preventDefault();
        const columnShell = columnDeleteOpenButton.closest('[data-garantia-column="1"]');
        const form = columnDeleteModalElement?.querySelector('[data-garantia-column-delete-form="1"]');
        const copy = columnDeleteModalElement?.querySelector('[data-garantia-column-delete-copy="1"]');
        if (!columnShell || !form || !copy) return;
        form.elements.columna_id.value = columnShell.dataset.columnaId || '';
        form.elements.columna_destino_id.value = '';
        copy.textContent = `Vas a eliminar la columna "${columnShell.dataset.columnaNombre || ''}".`;
        syncDeleteDestinationOptions(columnShell.dataset.columnaId || '');
        setColumnFormError(form, '');
        columnDeleteModal?.show();
        return;
      }

      const inlineCancelButton = e.target.closest('[data-garantia-inline-cancel="1"]');
      if (inlineCancelButton) {
        e.preventDefault();
        closeInlineCreateForm();
        return;
      }

      const inlineLinkAddButton = e.target.closest('[data-garantia-link-add="1"]');
      if (inlineLinkAddButton) {
        e.preventDefault();
        addInlineLinkRow(inlineLinkAddButton.closest('[data-garantia-inline-links="1"]'));
        return;
      }
      const inlineLinkRemoveButton = e.target.closest('[data-garantia-link-remove="1"]');
      if (inlineLinkRemoveButton) {
        e.preventDefault();
        removeInlineLinkRow(inlineLinkRemoveButton);
        return;
      }

      const link = e.target.closest('[data-garantia-modal-open="1"]');
      if (!link) return;
      e.preventDefault();
      e.stopPropagation();
      const url = link.getAttribute('data-modal-url') || link.getAttribute('href');
      const cardId = link.closest('[data-garantia-card="1"]')?.getAttribute('data-garantia-id') || '';
      if (!url) return;
      currentDetailLayout = 'modal';
      currentDetailUrl = url;
      currentDetailCardId = cardId;
      loadModal(url, cardId);
      return;
    });

    document.addEventListener('click', (e) => {
      const retryButton = e.target.closest('[data-garantia-detail-retry="1"]');
      if (!retryButton) return;
      e.preventDefault();
      const url = retryButton.dataset.detailUrl || currentDetailUrl;
      const layout = retryButton.dataset.detailLayout || currentDetailLayout || 'modal';
      if (!url) return;
      if (layout === 'drawer') {
        loadDrawer(url.replace(/[?&]layout=drawer\b/, ''), currentDetailCardId);
        return;
      }
      loadModal(url, currentDetailCardId);
    });

    root.addEventListener('submit', (e) => {
      const inlineEditor = e.target.closest('[data-garantia-inline-editor="1"]');
      if (inlineEditor) {
        e.preventDefault();
        const slot = inlineEditor.closest('[data-garantia-inline-slot]');
        const card = inlineEditor.closest('[data-garantia-card="1"]');
        const fieldName = inlineEditor.dataset.field;
        if (!slot || !card || !fieldName || isCardPending(card)) return;

        const fd = new FormData(inlineEditor);
        setCardPending(card, true);
        window.csrfFetch(inlineEditor.dataset.updateUrl, { method: 'POST', body: fd, headers: {'Accept': 'application/json'} })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;
            replaceCardHtml(getCardId(card), data.html);
          })
          .catch((error) => {
            const errorNode = inlineEditor.querySelector('[data-garantia-inline-error="1"]');
            if (error && error.errors && errorNode) {
              const fieldErrors = error.errors[fieldName] || error.errors.__all__ || [];
              errorNode.textContent = fieldErrors.map((item) => item.message).join(' ');
              return;
            }
            restoreInlineCard(card);
          })
          .finally(() => {
            setCardPending(card, false);
          });
        return;
      }

      const inlineForm = e.target.closest('[data-garantia-inline-form="1"]');
      if (inlineForm) {
        e.preventDefault();
        if (inlineForm.dataset.submitting === 'true') return;
        const fd = new FormData(inlineForm);
        const submittedEstado = String(fd.get('estado') || '');
        const submittedTarget = findInlineTarget(submittedEstado);
        const column = submittedTarget?.column.querySelector('.kanban-col');
        if (!submittedTarget || !column) return;
        const submitButton = inlineForm.querySelector('[data-garantia-inline-submit="1"]');
        const originalSubmitText = submitButton?.textContent || 'Guardar';
        inlineForm.dataset.submitting = 'true';
        inlineForm.setAttribute('aria-busy', 'true');
        if (submitButton) {
          submitButton.disabled = true;
          submitButton.textContent = 'Guardando...';
        }
        inlineForm.querySelectorAll('button, input, select, textarea').forEach((control) => {
          if (control === submitButton) return;
          control.disabled = true;
        });
        setInlineCreateButtonsDisabled(true);
        window.csrfFetch(inlineCreateUrl, {
          method: 'POST',
          body: fd,
          headers: {
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          }
        })
          .then((response) => readInlineCreateResponse(response))
          .then((data) => {
            if (!data.ok) return;

            const activeFilter = document.getElementById('GarantiasUserFilter')?.value || '';
            if (!activeFilter) {
              const wrapper = document.createElement('div');
              wrapper.innerHTML = data.html;
              const card = wrapper.firstElementChild;
              if (!card) return;
              invalidateColumnLoads();
              const duplicate = document.querySelector(
                `[data-garantia-id="${data.id}"]`
              );
              if (duplicate) {
                const duplicateColumn = duplicate.closest('.kanban-col');
                duplicate.remove();
                syncColumnState(duplicateColumn);
              }
              const emptyState = column.querySelector('.garantia-empty');
              if (emptyState) emptyState.remove();
              column.prepend(card);
              updateColumnCount(column, data.column_count);
            }

            destroyInlineCreateSelects(inlineForm);
            inlineForm.reset();
            initInlineCreateSelects(inlineForm);
            closeInlineCreateForm();
            showToast(data.message || 'Garantia creada correctamente.', 'success');
          })
          .catch((error) => {
            if (error?.data?.html) {
              replaceInlineCreateForm(error.data.html, submittedTarget);
              return;
            }
            console.error('No se pudo crear la garantia:', error);
            showToast(
              error?.data?.message || extractJsonErrors(error) || requestErrorMessage(error),
              'danger'
            );
          })
          .finally(() => {
            const activeForm = inlineSharedSlot?.querySelector('[data-garantia-inline-form="1"]');
            if (activeForm) {
              delete activeForm.dataset.submitting;
              activeForm.setAttribute('aria-busy', 'false');
              activeForm.querySelectorAll('button, input, select, textarea').forEach((control) => { control.disabled = false; });
            }
            if (submitButton) {
              submitButton.disabled = false;
              submitButton.textContent = originalSubmitText;
            }
            setInlineCreateButtonsDisabled(false);
          });
        return;
      }

      // El formulario de edición de garantías (data-garantia-modal-form="1") se
      // delega a document.addEventListener('submit') porque el drawer/modal está
      // fuera de .garantias-board y sus eventos submit no burbujean hasta root.

      const filesForm = e.target.closest('[data-garantia-files-form="1"], [data-garantia-file-delete-form="1"]');
      if (filesForm) {
        e.preventDefault();
        const section = filesForm.closest('[data-garantia-files-section="1"]');
        const detailRoot = getDetailRoot(filesForm);
        if (!section || section.dataset.pending === 'true') return;
        const fd = new FormData(filesForm);
        setSectionPending(section, true);
        postDetailSection(section, filesForm, fd)
          .then(({ok, data, stale}) => {
            if (stale) return;
            if (!data.files_html || !replaceDetailSection(detailRoot, '[data-garantia-files-section="1"]', data.files_html)) {
              throw new Error('No se pudo actualizar la seccion de archivos.');
            }
            syncCardResourceCount(data.id, 'files', data.files_count);
            if (!ok || !data.success) {
              const invalid = detailRoot?.querySelector('[data-garantia-files-section="1"] .is-invalid, [data-garantia-files-section="1"] input');
              invalid?.focus();
            }
          })
          .catch((error) => {
            console.error('No se pudo actualizar los archivos:', error);
            const form = section.querySelector('[data-garantia-files-form="1"]');
            form?.querySelector('input[type="file"]')?.focus();
          })
          .finally(() => {
            if (sectionRequestVersions.get(section)) setSectionPending(section, false);
          });
        return;
      }

      const linksForm = e.target.closest('[data-garantia-links-form="1"], [data-garantia-link-delete-form="1"]');
      if (linksForm) {
        e.preventDefault();
        const section = linksForm.closest('[data-garantia-links-section="1"]');
        const detailRoot = getDetailRoot(linksForm);
        if (!section || section.dataset.pending === 'true') return;
        const fd = new FormData(linksForm);
        setSectionPending(section, true);
        postDetailSection(section, linksForm, fd)
          .then(({ok, data, stale}) => {
            if (stale) return;
            if (!data.links_html || !replaceDetailSection(detailRoot, '[data-garantia-links-section="1"]', data.links_html)) {
              throw new Error('No se pudo actualizar la seccion de enlaces.');
            }
            syncCardResourceCount(data.id, 'links', data.links_count);
            if (!ok || !data.success) {
              const invalid = detailRoot?.querySelector('[data-garantia-links-section="1"] .is-invalid, [data-garantia-links-section="1"] input');
              invalid?.focus();
            }
          })
          .catch((error) => {
            console.error('No se pudo actualizar los enlaces:', error);
            section.querySelector('[data-garantia-links-form="1"] input')?.focus();
          })
          .finally(() => {
            if (sectionRequestVersions.get(section)) setSectionPending(section, false);
          });
        return;
      }

      const refreshForm = e.target.closest('[data-garantia-modal-refresh="1"]');
      if (refreshForm) {
        e.preventDefault();
        const fd = new FormData(refreshForm);
        const layout = refreshForm.querySelector('[name="layout"]')?.value || 'modal';
        setDrawerBusy(layout === 'drawer');
        window.csrfFetch(refreshForm.getAttribute('action'), { method: 'POST', body: fd, headers: {'Accept': 'application/json'} })
          .then((response) => {
            if (!response.ok) {
              throw new Error(`Error ${response.status}`);
            }
            return response.json();
          })
          .then((data) => {
            if (data.deleted) {
              removeCard(data.id);
              closeDrawer(true);
              if (modalInstance && modalElement?.classList.contains('show')) {
                modalInstance.hide();
              }
              return;
            }
            if (layout === 'drawer' && drawerContent) {
              drawerContent.innerHTML = data.html;
              if (window.initGarantiaSelects) window.initGarantiaSelects(drawerContent);
            } else if (modalContent) {
              modalContent.innerHTML = data.html;
              if (window.initGarantiaSelects) window.initGarantiaSelects(modalContent);
            }
            if (data.card_html) {
              replaceCardHtml(data.id, data.card_html);
            }
          })
          .catch((error) => {
            console.error('No se pudo actualizar la garantia:', error);
          })
          .finally(() => {
            setDrawerBusy(false);
          });
        return;
      }

      const commentForm = e.target.closest('[data-garantia-comentario-form="1"]');
      if (!commentForm) return;
      e.preventDefault();
      const url = commentForm.getAttribute('action');
      const detailRoot = commentForm.closest('.garantia-drawer__content, .modal-content');
      const textarea = commentForm.querySelector('textarea[name="comentario"]');
      const text = (textarea?.value || '').trim();
      if (!url) return;
      if (!text) {
        showCommentFormError(detailRoot, 'Escribe un comentario antes de enviarlo.');
        textarea?.focus();
        return;
      }
      const submitButton = commentForm.querySelector('[data-garantia-comment-submit="1"]');
      if (commentForm.dataset.pending === 'true') return;

      const fd = new FormData(commentForm);
      const layout = commentForm.querySelector('[name="layout"]')?.value || currentDetailLayout || 'drawer';
      fd.set('layout', layout);
      fd.set('comentario', text);
      const detailVersion = detailState.version;
      commentForm.dataset.pending = 'true';
      commentForm.setAttribute('aria-busy', 'true');
      if (submitButton) submitButton.disabled = true;
      setDrawerBusy(layout === 'drawer');
      window.csrfFetch(url, {
        method: 'POST',
        body: fd,
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        }
      })
        .then((response) => {
          return readJsonResponse(response).then((data) => ({ ok: response.ok, status: response.status, data }));
        })
        .then(({ ok, status, data }) => {
          if (detailState.version !== detailVersion || !detailRoot?.isConnected || String(data.id) !== String(currentDetailCardId)) return;
          if (!ok) {
            const error = new Error(`Error ${status}`);
            error.status = status;
            error.data = data;
            throw error;
          }
          if (data.status === 'ok') {
            if (detailRoot) {
              replaceCommentsSection(detailRoot, data.html);
            }
            setCardCommentCount(data.id, data.comentarios_count);
          }
        })
        .catch((error) => {
          if (error.data?.html && detailRoot) {
            replaceCommentsSection(detailRoot, error.data.html);
            return;
          }
          if (detailRoot?.isConnected && detailState.version === detailVersion) {
            showCommentFormError(detailRoot, requestErrorMessage(error));
          }
          console.error('No se pudo agregar el comentario:', error);
        })
        .finally(() => {
          delete commentForm.dataset.pending;
          commentForm.setAttribute('aria-busy', 'false');
          if (submitButton) submitButton.disabled = false;
          setDrawerBusy(false);
        });
    });

    document.addEventListener('click', (e) => {
      if (e.target.closest('[data-garantia-column-create-open="1"]')) {
        const form = columnCreateModalElement?.querySelector('[data-garantia-column-create-form="1"]');
        if (!form) return;
        form.reset();
        setColumnFormError(form, '');
        columnCreateModal?.show();
      }
    });

    document.addEventListener('submit', (e) => {
      const createForm = e.target.closest('[data-garantia-column-create-form="1"]');
      if (createForm) {
        e.preventDefault();
        setColumnFormError(createForm, '');
        const fd = new FormData(createForm);
        window.csrfFetch(columnCreateUrl, {
          method: 'POST',
          body: fd,
          headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        })
          .then((response) => readJsonResponse(response).then((data) => ({ok: response.ok, data})))
          .then(({ok, data}) => {
            if (!ok || !data.ok) {
              const error = new Error('No se pudo crear la columna.');
              error.data = data;
              throw error;
            }
            const wrapper = document.createElement('div');
            wrapper.innerHTML = data.html;
            const columnItem = wrapper.firstElementChild;
            if (!columnItem) throw new Error('HTML de columna invalido.');
            getColumnsContainer()?.appendChild(columnItem);
            initSortable();
            syncCopyActions();
            syncDeleteDestinationOptions('');
            columnCreateModal?.hide();
            showToast('Columna creada correctamente.', 'success');
          })
          .catch((error) => {
            setColumnFormError(createForm, extractJsonErrors(error) || requestErrorMessage(error));
          });
        return;
      }

      const editForm = e.target.closest('[data-garantia-column-edit-form="1"]');
      if (editForm) {
        e.preventDefault();
        setColumnFormError(editForm, '');
        const columnId = editForm.elements.columna_id.value;
        const url = getColumnShellById(columnId)?.dataset.editUrl;
        if (!url) return;
        const fd = new FormData(editForm);
        window.csrfFetch(url, {
          method: 'POST',
          body: fd,
          headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        })
          .then((response) => readJsonResponse(response).then((data) => ({ok: response.ok, data})))
          .then(({ok, data}) => {
            if (!ok || !data.ok) {
              const error = new Error('No se pudo editar la columna.');
              error.data = data;
              throw error;
            }
            const columnShell = getColumnShellById(columnId);
            updateColumnPresentation(columnShell, data);
            syncDeleteDestinationOptions(columnId);
            columnEditModal?.hide();
            showToast('Columna actualizada.', 'success');
          })
          .catch((error) => {
            setColumnFormError(editForm, extractJsonErrors(error) || requestErrorMessage(error));
          });
        return;
      }

      const deleteColumnForm = e.target.closest('[data-garantia-column-delete-form="1"]');
      if (deleteColumnForm) {
        e.preventDefault();
        setColumnFormError(deleteColumnForm, '');
        const columnId = deleteColumnForm.elements.columna_id.value;
        const columnShell = getColumnShellById(columnId);
        const url = columnShell?.dataset.deleteUrl;
        if (!url) return;
        const fd = new FormData(deleteColumnForm);
        window.csrfFetch(url, {
          method: 'POST',
          body: fd,
          headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        })
          .then((response) => readJsonResponse(response).then((data) => ({ok: response.ok, data})))
          .then(({ok, data}) => {
            if (!ok || !data.ok) {
              const error = new Error('No se pudo eliminar la columna.');
              error.data = data;
              throw error;
            }
            const destinationBody = data.columna_destino_id
              ? getColumnShellById(String(data.columna_destino_id))?.querySelector('.kanban-col')
              : null;
            if (columnShell && destinationBody) {
              columnShell.querySelectorAll('[data-garantia-card="1"]').forEach((card) => {
                syncCardStateUI(card, data.columna_destino_codigo, getEstadoLabel(data.columna_destino_codigo));
                card.dataset.garantiaColumnId = String(data.columna_destino_id);
                destinationBody.prepend(card);
              });
              syncColumnState(destinationBody, data.column_count);
            }
            columnShell?.closest('[data-garantia-column-item="1"]')?.remove();
            syncDeleteDestinationOptions('');
            invalidateColumnLoads();
            columnDeleteModal?.hide();
            showToast('Columna eliminada.', 'success');
          })
          .catch((error) => {
            setColumnFormError(deleteColumnForm, extractJsonErrors(error) || error?.data?.error || requestErrorMessage(error));
          });
        return;
      }
    });

    root.addEventListener('keydown', (e) => {
      const editor = e.target.closest('[data-garantia-inline-editor="1"]');
      if (editor) {
        if (e.key === 'Escape') {
          e.preventDefault();
          const card = editor.closest('[data-garantia-card="1"]');
          restoreInlineCard(card);
          return;
        }

        if (editor.dataset.field !== 'asignados' && e.key === 'Enter' && e.target.tagName !== 'TEXTAREA' && !e.shiftKey) {
          e.preventDefault();
          editor.requestSubmit();
          return;
        }
      }

      if (e.key === 'Escape' && drawerRoot?.classList.contains('is-open')) {
        e.preventDefault();
        closeDrawer(false);
      }
    });

    document.addEventListener('submit', (e) => {
      const deleteForm = e.target.closest('form[data-garantia-modal-delete="1"]');
      if (deleteForm) {
        e.preventDefault();
        e.stopPropagation();
        submitDetailDeleteForm(deleteForm);
        return;
      }

      const modalForm = e.target.closest('form[data-garantia-modal-form="1"]');
      if (!modalForm) return;

      e.preventDefault();
      e.stopPropagation();

      const tokenInput = modalForm.querySelector('input[name="csrfmiddlewaretoken"]');

      const fd = new FormData(modalForm);
      if (!fd.has("csrfmiddlewaretoken")) {
        throw new Error(
          "El formulario de Garantías no contiene csrfmiddlewaretoken."
        );
      }

      const csrfToken = tokenInput?.value;
      if (!csrfToken) {
        throw new Error(
          "No se encontró csrfmiddlewaretoken en el formulario de edición."
        );
      }

      if (modalForm.dataset.pending === 'true') return;
      setFormPending(modalForm, true);
      setDrawerBusy((modalForm.querySelector('[name="layout"]')?.value || '') === 'drawer');

      window.csrfFetch(modalForm.getAttribute('action'), {
        method: 'POST',
        body: fd,
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        }
      })
      .then((response) => readDetailFormResponse(response))
      .then((data) => {
        const layout = modalForm.querySelector('[name="layout"]')?.value || 'modal';
        if (data.status === 'validation_error') {
          if (layout === 'drawer' && drawerContent && drawerRoot?.classList.contains('is-open')) {
            drawerContent.innerHTML = data.html;
            if (window.initGarantiaSelects) window.initGarantiaSelects(drawerContent);
          } else if (modalContent) {
            modalContent.innerHTML = data.html;
            if (window.initGarantiaSelects) window.initGarantiaSelects(modalContent);
          }
          return;
        }
        if (!data.html || (data.id && String(data.id) !== String(currentDetailCardId))) {
          throw new Error('Respuesta de garantia inesperada.');
        }
        if (layout === 'drawer' && drawerContent && drawerRoot?.classList.contains('is-open')) {
          drawerContent.innerHTML = data.html;
          if (window.initGarantiaSelects) window.initGarantiaSelects(drawerContent);
        } else if (modalContent) {
          modalContent.innerHTML = data.html;
          if (window.initGarantiaSelects) window.initGarantiaSelects(modalContent);
        }
        if (data.status === 'ok') {
          replaceCardHtml(data.id, data.card_html);
        }
      })
      .catch((error) => {
        if (error?.data?.html) {
          const layout = modalForm.querySelector('[name="layout"]')?.value || 'modal';
          if (layout === 'drawer' && drawerContent && drawerRoot?.classList.contains('is-open')) {
            drawerContent.innerHTML = error.data.html;
            if (window.initGarantiaSelects) window.initGarantiaSelects(drawerContent);
          } else if (modalContent) {
            modalContent.innerHTML = error.data.html;
            if (window.initGarantiaSelects) window.initGarantiaSelects(modalContent);
          }
          return;
        }
        console.error('No se pudo guardar la garantia:', error);
        const rootElement = getDetailRoot(modalForm);
        showCommentFormError(rootElement, requestErrorMessage(error));
      })
      .finally(() => {
        if (modalForm.isConnected) setFormPending(modalForm, false);
        setDrawerBusy(false);
      });
    });

    window.createKanbanQuickEditController({
      cardSelector: '[data-garantia-card="1"]',
      openSelector: '[data-garantia-quick-edit-open="1"]',
      cancelSelector: '[data-garantia-quick-edit-cancel="1"]',
      formSelector: '[data-garantia-quick-edit-form="1"]',
      getId: (card) => getCardId(card),
      getUrl: (button) => button.dataset.garantiaQuickEditUrl,
      isPending: isCardPending,
      setPending: setCardPending,
      initComponents: (card) => {
        invalidateColumnLoads();
        window.initGarantiaSelects?.(card);
        syncColumnState(card?.closest('.kanban-col'));
      },
      showError: (card, message) => {
        const body = card.querySelector('.card-body');
        if (body) body.insertAdjacentHTML('afterbegin', `<div class="alert alert-danger small py-2 mb-2">${message}</div>`);
      },
      loadingHtml: '<div class="card-body text-center text-muted small py-4">Cargando edicion...</div>',
    });

    modalElement?.addEventListener('hidden.bs.modal', () => {
      abortActiveDetailRequest();
      detailState.version += 1;
      detailState.id = '';
      currentDetailUrl = '';
      currentDetailCardId = '';
    });

    syncCopyActions();
    syncInlineCreateAccess();
    initSortable();

    document.addEventListener('submit', (e) => {
      const tagForm = e.target.closest('[data-garantia-tag-assign-form="1"], [data-garantia-tag-create-form="1"], [data-garantia-tag-remove-form="1"]');
      if (tagForm) {
        e.preventDefault();
        e.stopPropagation();
        const isRemove = tagForm.matches('[data-garantia-tag-remove-form="1"]');
        if (isRemove && !window.confirm('¿Quitar esta etiqueta de la garantía?')) return;

        const section = tagForm.closest('[data-garantia-tags-section="1"]');
        if (!section || tagForm.dataset.submitting === '1') return;

        const fd = new FormData(tagForm);
        tagForm.dataset.submitting = '1';
        
        postForm(tagForm.getAttribute('action'), fd, tagForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            // Reemplazar la sección
            const parent = section.parentElement;
            const temp = document.createElement('div');
            temp.innerHTML = data.tags_html;
            const newSection = temp.firstElementChild;
            if (parent && newSection) {
              parent.replaceChild(newSection, section);
              // Re-inicializar TomSelect
              if (window.TomSelect) {
                newSection.querySelectorAll('select').forEach(select => {
                  if (!select.tomselect) {
                    new TomSelect(select, {
                      plugins: ['remove_button'],
                      create: true,
                      maxOptions: 200,
                      persist: false,
                      closeAfterSelect: false,
                      hidePlaceholder: true,
                      placeholder: 'Buscar o crear etiqueta...',
                      searchField: ['text']
                    });
                  }
                });
              }
            }
            
            // Actualizar tarjeta
            const card = document.querySelector(`[data-garantia-card="1"][data-garantia-id="${data.id}"]`);
            if (card) {
                const tagsContainer = card.querySelector('.garantia-card__tags');
                if (tagsContainer) {
                    tagsContainer.innerHTML = data.tags.map(t => 
                        `<div class="garantia-tag" style="--garantia-tag-bg: ${t.color};">${t.nombre}</div>`
                    ).join('');
                }
            }
          })
          .catch((error) => {
            console.error('Error al procesar etiqueta:', error);
            if (error && error.tags_html) {
                const parent = section.parentElement;
                const temp = document.createElement('div');
                temp.innerHTML = error.tags_html;
                const newSection = temp.firstElementChild;
                if (parent && newSection) {
                  parent.replaceChild(newSection, section);
                }
            } else {
                const msg = error && error.error ? error.error : 'No se pudo actualizar la etiqueta.';
                alert(msg);
            }
          })
          .finally(() => {
            delete tagForm.dataset.submitting;
          });
      }
    });

  })();
