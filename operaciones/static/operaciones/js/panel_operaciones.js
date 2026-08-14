  (function () {
    const root = document.querySelector('[data-operaciones-board="1"]');
    const configElement = document.getElementById('panel-operaciones-config');
    if (!root || !configElement || root.dataset.panelJsInitialized === '1') return;

    let config;
    try {
      config = JSON.parse(configElement.textContent);
    } catch (_) {
      return;
    }
    if (!config?.inlineCreateUrl || !config?.inlineFormUrl) return;
    root.dataset.panelJsInitialized = '1';

    const modalElement = document.getElementById('OperacionDetalleModal');
    const modalContent = document.getElementById('OperacionDetalleModalContent');
    const modalInstance = modalElement && window.bootstrap ? new bootstrap.Modal(modalElement) : null;
    const drawerElement = document.getElementById('OperacionDetalleDrawer');
    const drawerContent = document.getElementById('OperacionDetalleDrawerContent');
    const drawerSupported = Boolean(drawerElement && drawerContent);
    const confirmModalElement = document.getElementById('OperacionEliminarConfirmModal');
    const confirmModalInstance = confirmModalElement && window.bootstrap ? new bootstrap.Modal(confirmModalElement) : null;
    const columnCreateModalElement = document.getElementById('OperacionColumnCreateModal');
    const columnCreateModalInstance = columnCreateModalElement && window.bootstrap ? new bootstrap.Modal(columnCreateModalElement) : null;
    const columnEditModalElement = document.getElementById('OperacionColumnEditModal');
    const columnEditModalInstance = columnEditModalElement && window.bootstrap ? new bootstrap.Modal(columnEditModalElement) : null;
    const columnDeleteModalElement = document.getElementById('OperacionColumnDeleteModal');
    const columnDeleteModalInstance = columnDeleteModalElement && window.bootstrap ? new bootstrap.Modal(columnDeleteModalElement) : null;
    const columnCreateForm = columnCreateModalElement?.querySelector('form');
    const columnEditForm = columnEditModalElement?.querySelector('form');
    const columnDeleteForm = columnDeleteModalElement?.querySelector('form');
    const pendingCardIds = new Set();
    const quickEditingCardIds = new Set();
    const quickEditOriginalHtml = new WeakMap();
    const inlineCreateUrl = config.inlineCreateUrl;
    const inlineFormUrl = config.inlineFormUrl;
    const boardUrl = config.boardUrl || '';
    const columnCreateUrl = config.columnCreateUrl || '';
    const columnReorderUrl = config.columnReorderUrl || '';
    const inlineHost = document.querySelector('[data-operacion-inline-host="1"]');
    const inlineContainer = document.querySelector('[data-operacion-inline-container="1"]');
    const inlineFormSlot = inlineContainer?.querySelector('[data-operacion-inline-form-slot="1"]');
    const inlineLoading = inlineContainer?.querySelector('[data-operacion-inline-loading="1"]');
    const inlineLoadError = inlineContainer?.querySelector('[data-operacion-inline-load-error="1"]');
    const copiedCardStorageKey = 'operaciones.copiedCard';
    let inlineInitialFormHtml = '';
    let inlineFormLoaded = false;
    let inlineFormLoadPromise = null;
    let inlineRequestedTarget = null;
    let toastContainer = null;
    const detailState = {id: null, url: null, layout: 'modal', pending: false};
    let operacionDeleteUrl = null;
    let activeColumnShell = null;
    const columnLoadRequests = new Map();
    let boardVersion = 0;

    function reloadBoard() {
      invalidateColumnLoads();
      window.location.reload();
    }

    function postForm(url, formData, formElement = null) {
      const token = window.getCSRFToken(formElement);
      if (!token) return Promise.reject(new Error("CSRF token missing"));
      return fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': token,
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
        body: formData,
      });
    }

    function initInlineFormComponents(container) {
      if (!container) return;
      if (window.initGarantiaSelects) {
        window.initGarantiaSelects(container);
      }
      if (typeof TomSelect !== 'undefined') {
        container.querySelectorAll('[data-operacion-tags-select="1"]').forEach((select) => {
          if (select.tomselect) return;
          new TomSelect(select, {
            plugins: ['remove_button'],
            create: false,
            maxOptions: 200,
            persist: false,
            closeAfterSelect: false,
            hidePlaceholder: true,
            searchField: ['text'],
          });
        });
      }
      if (window.initOperacionSelects) {
        window.initOperacionSelects(container);
      }
    }

    function getHtml(url) {
      return fetch(url, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      }).then(async (response) => {
        if (!response.ok) {
          throw new Error(`Error ${response.status}`);
        }
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const data = await response.json();
          return data.html || '';
        }
        return response.text();
      });
    }

    function getCopiedCardPayload() {
      try {
        const raw = window.sessionStorage.getItem(copiedCardStorageKey);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (
          !parsed ||
          parsed.modulo !== 'operaciones' ||
          !Number.isInteger(parsed.tarjeta_id) ||
          parsed.tarjeta_id <= 0
        ) {
          return null;
        }
        return parsed;
      } catch (_) {
        return null;
      }
    }

    function setCopiedCardPayload(payload) {
      window.sessionStorage.setItem(copiedCardStorageKey, JSON.stringify(payload));
      syncCopyActions();
    }

    function clearCopiedCardPayload() {
      window.sessionStorage.removeItem(copiedCardStorageKey);
      syncCopyActions();
    }

    function syncCopyActions() {
      const payload = getCopiedCardPayload();
      document.querySelectorAll('[data-operacion-column-paste="1"]').forEach((button) => {
        button.disabled = !payload;
      });
      document.querySelectorAll('[data-operacion-copy-clear="1"]').forEach((button) => {
        button.disabled = !payload;
      });
    }

    function ensureEmptyState(column) {
      if (!column) return;
      const cards = column.querySelectorAll('[data-panel-operacion-card="1"]');
      let empty = column.querySelector('.panel-operacion-empty');
      if (!cards.length && !empty) {
        empty = document.createElement('div');
        empty.className = 'operaciones-column__empty text-muted panel-operacion-empty';
        empty.textContent = 'Sin operaciones.';
        column.appendChild(empty);
      }
      if (cards.length && empty) empty.remove();
    }

    function getColumnShell(column) {
      return column?.closest('[data-operaciones-column="1"]') || null;
    }

    function getColumnItems(shell) {
      return shell?.querySelector('.panel-operaciones-col') || null;
    }

    function getColumnId(shell) {
      const value = shell?.dataset.columnaId || getColumnItems(shell)?.dataset.columnaId || '';
      return value || '';
    }

    function getColumnState(shell) {
      return shell?.dataset.estado || getColumnItems(shell)?.dataset.estado || '';
    }

    function getColumnName(shell) {
      return shell?.dataset.columnaNombre || shell?.querySelector('[data-operacion-column-title="1"]')?.textContent?.trim() || '';
    }

    function getColumnTotal(column) {
      const value = Number.parseInt(getColumnShell(column)?.dataset.total || '', 10);
      return Number.isNaN(value) ? 0 : value;
    }

    function syncColumnState(column, totalOverride) {
      if (!column) return;
      const shell = getColumnShell(column);
      if (!shell) return;
      const loaded = column.querySelectorAll('[data-panel-operacion-card="1"]').length;
      const parsedTotal = Number.parseInt(totalOverride, 10);
      const total = Number.isNaN(parsedTotal)
        ? Math.max(getColumnTotal(column), loaded)
        : Math.max(parsedTotal, loaded);
      shell.dataset.total = String(total);
      shell.dataset.loaded = String(loaded);
      const countElement = shell.querySelector('[data-operaciones-column-count="1"]');
      if (countElement) countElement.textContent = String(total);
      const remaining = Math.max(0, total - loaded);
      const button = shell.querySelector('[data-operacion-load-more="1"]');
      if (button) {
        button.hidden = remaining === 0;
        button.textContent = remaining ? `Cargar más (${remaining})` : 'Cargar más';
      }
      ensureEmptyState(column);
    }

    function adjustColumnTotal(column, delta) {
      if (!column) return;
      syncColumnState(column, Math.max(0, getColumnTotal(column) + delta));
    }

    function updateColumnCountFromDom(column) {
      syncColumnState(column);
    }

    function syncColumnUI(...columns) {
      [...new Set(columns.filter(Boolean))].forEach((column) => {
        syncColumnState(column);
      });
    }

    function getCardIndex(card, column) {
      return [...column.querySelectorAll('[data-panel-operacion-card="1"]')].indexOf(card);
    }

    function isCardPending(card) {
      return Boolean(card?.dataset.panelOperacionId && pendingCardIds.has(card.dataset.panelOperacionId));
    }

    function isCardBusy(card) {
      const cardId = card?.dataset.panelOperacionId;
      return isCardPending(card) || Boolean(card?.dataset.quickEditing) || Boolean(cardId && quickEditingCardIds.has(cardId));
    }

    function setCardPending(card, isPending) {
      const cardId = card?.dataset.panelOperacionId;
      if (!cardId) return;
      if (isPending) {
        pendingCardIds.add(cardId);
        card.dataset.pending = '1';
      } else {
        pendingCardIds.delete(cardId);
        delete card.dataset.pending;
      }
      const selector = card.querySelector('[data-operacion-state-select="1"]');
      if (selector) selector.disabled = isPending;
    }

    function getStateLabel(card, estado) {
      const option = card?.querySelector(`[data-operacion-state-select="1"] option[value="${estado}"]`);
      return option?.textContent?.trim() || estado;
    }

    function syncCardStateUI(card, estado, estadoLabel) {
      if (!card || !estado) return;
      card.dataset.operacionState = estado;
      const selector = card.querySelector('[data-operacion-state-select="1"]');
      if (selector) selector.value = estado;
      const badge = card.querySelector('[data-operacion-state-badge="1"]');
      if (badge) badge.textContent = estadoLabel || getStateLabel(card, estado);
    }

    function restoreCardPosition(card, sourceColumn, sourceIndex) {
      if (!card || !sourceColumn) return;
      const cards = [...sourceColumn.querySelectorAll('[data-panel-operacion-card="1"]')]
        .filter((item) => item !== card);
      const referenceCard = cards[sourceIndex];
      if (referenceCard) {
        sourceColumn.insertBefore(card, referenceCard);
      } else {
        sourceColumn.appendChild(card);
      }
    }

    function moveOperacionCard({ card, targetColumn, targetState, sourceColumn, sourceIndex }) {
      const cardId = card?.dataset.panelOperacionId;
      const previousState = card?.dataset.operacionState || sourceColumn?.dataset.estado;
      const previousLabel = getStateLabel(card, previousState);
      const originColumn = sourceColumn || card?.closest('.panel-operaciones-col');
      const originIndex = Number.isInteger(sourceIndex) ? sourceIndex : getCardIndex(card, originColumn);

      if (!cardId || !targetColumn || !targetState || !originColumn || !previousState) {
        return Promise.resolve(false);
      }

      if (isCardBusy(card)) {
        restoreCardPosition(card, originColumn, originIndex);
        syncCardStateUI(card, previousState, previousLabel);
        syncColumnUI(originColumn, targetColumn);
        return Promise.resolve(false);
      }

      if (targetState === previousState) {
        syncCardStateUI(card, previousState, previousLabel);
        syncColumnUI(originColumn, targetColumn);
        return Promise.resolve(true);
      }

      if (card.parentElement !== targetColumn) {
        targetColumn.appendChild(card);
      }
      syncCardStateUI(card, targetState, getStateLabel(card, targetState));
      setCardPending(card, true);
      adjustColumnTotal(originColumn, -1);
      adjustColumnTotal(targetColumn, 1);

      const formData = new FormData();
      formData.append('estado', targetState);
      const targetColumnId = targetColumn?.dataset.columnaId || '';
      if (targetColumnId) formData.append('columna_id', targetColumnId);

      return postForm(card.dataset.operacionMoveUrl, formData)
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !(data.ok || data.status === 'ok')) throw new Error(data.message || data.error || `Error ${response.status}`);
          return data;
        })
        .then((data) => {
          invalidateColumnLoads();
          syncCardStateUI(card, data.estado, data.estado_label);
          return true;
        })
        .catch((error) => {
          console.error('No se pudo mover la operacion:', error);
          restoreCardPosition(card, originColumn, originIndex);
          adjustColumnTotal(originColumn, 1);
          adjustColumnTotal(targetColumn, -1);
          syncCardStateUI(card, previousState, previousLabel);
          return false;
        })
        .finally(() => {
          setCardPending(card, false);
          syncColumnUI(originColumn, targetColumn);
        });
    }

    function destroyInlineFormComponents(container) {
      if (!container) return;
      container.querySelectorAll('select').forEach((select) => {
        if (select.tomselect) select.tomselect.destroy();
      });
    }

    function syncInlineDestinationLabel(label) {
      const outerLabel = inlineContainer?.querySelector('[data-operacion-inline-target-label="1"]');
      if (outerLabel) outerLabel.textContent = label || '';
      const innerLabel = inlineFormSlot?.querySelector('[data-operacion-inline-destination="1"]');
      if (innerLabel) innerLabel.textContent = `Crear en: ${label || ''}`;
    }

    function resetSharedInlineForm(estado = '') {
      if (!inlineFormLoaded || !inlineContainer || !inlineFormSlot) return null;
      destroyInlineFormComponents(inlineFormSlot);
      inlineFormSlot.innerHTML = inlineInitialFormHtml;
      inlineContainer.dataset.estado = estado;
      const form = inlineFormSlot.querySelector('[data-operacion-inline-form="1"]');
      const stateInput = form?.querySelector('[name="estado"]');
      if (stateInput) stateInput.value = estado;
      syncInlineDestinationLabel(
        inlineRequestedTarget?.estadoLabel || inlineRequestedTarget?.estado || estado
      );
      return form;
    }

    function closeSharedInlineForm({reset = true} = {}) {
      if (!inlineContainer) return;
      const currentState = inlineContainer.dataset.estado || '';
      if (reset && inlineFormLoaded) resetSharedInlineForm(currentState);
      inlineContainer.classList.add('d-none');
      if (inlineHost) inlineHost.appendChild(inlineContainer);
    }

    function setInlineOpenButtonsLoading(isLoading) {
      document.querySelectorAll('[data-operacion-inline-open="1"]').forEach((button) => {
        button.disabled = isLoading;
        button.toggleAttribute('aria-busy', isLoading);
      });
    }

    function showInlineLoadFeedback({loading = false, error = false} = {}) {
      inlineLoading?.classList.toggle('d-none', !loading);
      inlineLoadError?.classList.toggle('d-none', !error);
    }

    function activateRequestedInlineTarget() {
      const target = inlineRequestedTarget;
      if (!inlineFormLoaded || !target?.estado) return;
      const form = resetSharedInlineForm(target.estado);
      syncInlineDestinationLabel(target.estadoLabel || target.estado);
      showInlineLoadFeedback();
      initInlineFormComponents(inlineFormSlot);
      const firstInput = form?.querySelector('input:not([type="hidden"]), select, textarea');
      if (firstInput) firstInput.focus();
    }

    function loadSharedInlineForm() {
      if (inlineFormLoaded) {
        activateRequestedInlineTarget();
        return Promise.resolve();
      }
      if (inlineFormLoadPromise) return inlineFormLoadPromise;

      setInlineOpenButtonsLoading(true);
      showInlineLoadFeedback({loading: true});

      inlineFormLoadPromise = getHtml(inlineFormUrl)
        .then((html) => {
          if (!html.includes('data-operacion-inline-form="1"')) {
            throw new Error('La respuesta no contiene el formulario esperado.');
          }
          inlineInitialFormHtml = html;
          inlineFormLoaded = true;
          activateRequestedInlineTarget();
        })
        .catch((error) => {
          console.error('No se pudo cargar el formulario inline:', error);
          inlineFormLoaded = false;
          inlineInitialFormHtml = '';
          if (inlineFormSlot) inlineFormSlot.innerHTML = '';
          showInlineLoadFeedback({error: true});
        })
        .finally(() => {
          setInlineOpenButtonsLoading(false);
          inlineFormLoadPromise = null;
        });

      return inlineFormLoadPromise;
    }

    function setInlineFormPending(form, isPending) {
      if (!form) return;
      if (isPending) {
        form.dataset.pending = '1';
      } else {
        delete form.dataset.pending;
      }
      form.querySelectorAll('button, input, select, textarea').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderInlineError(container, message) {
      if (!container) return;
      container.querySelector('.operaciones-inline-error')?.remove();
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-inline-error';
      error.textContent = message;
      container.prepend(error);
    }

    function getToastContainer() {
      if (toastContainer?.isConnected) return toastContainer;
      toastContainer = document.createElement('div');
      toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3 operaciones-toast-container';
      toastContainer.setAttribute('aria-live', 'polite');
      toastContainer.setAttribute('aria-atomic', 'true');
      document.body.appendChild(toastContainer);
      return toastContainer;
    }

    function showInlineNotification(message, level = 'success') {
      if (!message) return;
      const container = getToastContainer();
      const toast = document.createElement('div');
      const levelClass = level === 'success' ? 'text-bg-success' : 'text-bg-danger';
      toast.className = `toast align-items-center border-0 ${levelClass}`;
      toast.setAttribute('role', 'alert');
      toast.setAttribute('aria-live', 'assertive');
      toast.setAttribute('aria-atomic', 'true');
      toast.innerHTML = `
        <div class="d-flex">
          <div class="toast-body">${message}</div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Cerrar"></button>
        </div>
      `;
      container.appendChild(toast);
      if (window.bootstrap?.Toast) {
        const instance = bootstrap.Toast.getOrCreateInstance(toast, { delay: 3500 });
        toast.addEventListener('hidden.bs.toast', () => toast.remove(), { once: true });
        instance.show();
        return;
      }
      window.setTimeout(() => toast.remove(), 3500);
    }

    function addInlineLinkRow(scope) {
      const linksSection = scope?.querySelector('[data-operacion-inline-links="1"]');
      const rows = linksSection?.querySelector('[data-operacion-link-rows="1"]');
      const template = linksSection?.querySelector('[data-operacion-link-template="1"]');
      if (!rows || !template) return;
      rows.insertAdjacentHTML('beforeend', template.innerHTML.trim());
    }

    function removeInlineLinkRow(button) {
      const row = button?.closest('[data-operacion-link-row="1"]');
      const rows = row?.parentElement;
      if (!row || !rows) return;
      if (rows.querySelectorAll('[data-operacion-link-row="1"]').length <= 1) {
        row.querySelectorAll('input').forEach((input) => {
          input.value = '';
        });
        return;
      }
      row.remove();
    }

    function insertCardFromHtml(column, cardHtml) {
      if (!column || !cardHtml) return null;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = cardHtml;
      const card = wrapper.firstElementChild;
      if (!card) return null;
      const cardId = card.dataset.panelOperacionId;
      if (!cardId || getCardElement(cardId)) return null;
      invalidateColumnLoads();
      column.prepend(card);
      adjustColumnTotal(column, 1);
      return card;
    }

    function pasteCopiedCard(button) {
      const payload = getCopiedCardPayload();
      const shell = button?.closest('[data-operaciones-column="1"]');
      const column = shell?.querySelector('.panel-operaciones-col');
      const pasteUrl = button?.dataset.pasteUrl || '';
      const selectedUserId = document.getElementById('OperacionesUserFilter')?.value || '';
      if (!payload || !shell || !column || !pasteUrl) {
        syncCopyActions();
        showInlineNotification('No hay una tarjeta copiada valida.', 'danger');
        return;
      }

      const formData = new FormData();
      formData.append('tarjeta_id', String(payload.tarjeta_id));
      formData.append('modulo', payload.modulo);
      button.disabled = true;

      postForm(pasteUrl, formData)
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.ok || !data.html) {
            throw new Error(data.error || `Error ${response.status}`);
          }
          return data;
        })
        .then((data) => {
          const assignedUserIds = Array.isArray(data.assigned_user_ids)
            ? data.assigned_user_ids.map(String)
            : [];
          const shouldInsertCard = !selectedUserId || assignedUserIds.includes(selectedUserId);
          if (shouldInsertCard) {
            const inserted = insertCardFromHtml(column, data.html);
            if (!inserted) {
              throw new Error('No se pudo insertar la tarjeta copiada.');
            }
          } else {
            syncColumnState(column, data.column_count);
          }
          invalidateColumnLoads();
          showInlineNotification('Tarjeta pegada correctamente.', 'success');
          syncCopyActions();
        })
        .catch((error) => {
          console.error('No se pudo pegar la tarjeta:', error);
          showInlineNotification(error.message || 'No se pudo pegar la tarjeta.', 'danger');
          syncCopyActions();
        })
        .finally(() => {
          button.disabled = false;
        });
    }

    function createOperacionInline(form) {
      const container = form.closest('[data-operacion-inline-container="1"]');
      const estado = form.querySelector('[name="estado"]')?.value;
      const column = document.querySelector(`.panel-operaciones-col[data-estado="${estado}"]`);
      if (!container || !estado || !column || form.dataset.pending === '1') return;

      const formData = new FormData(form);
      const selectedUserId = document.getElementById('OperacionesUserFilter')?.value || '';
      const assignedUserIds = formData.getAll('asignados').map(String);
      const shouldInsertCard = !selectedUserId || assignedUserIds.includes(selectedUserId);
      setInlineFormPending(form, true);
      container.querySelector('.operaciones-inline-error')?.remove();

      postForm(form.action || inlineCreateUrl, formData, form)
        .then(async (response) => {
          const raw = await response.text();
          const contentType = response.headers.get('content-type') || '';
          if (!contentType.includes('application/json')) {
            throw new Error(`El servidor devolvio una respuesta no JSON. HTTP ${response.status}: ${raw}`);
          }
          let data;
          try {
            data = JSON.parse(raw);
          } catch (error) {
            throw new Error(`El servidor devolvio una respuesta no JSON. HTTP ${response.status}: ${raw}`);
          }
          if (!response.ok || !data.ok) return data;
          return data;
        })
        .then((data) => {
          const operacionId = data.operacion_id || data.id;
          if (data.ok && operacionId && data.estado && data.html) {
            const targetColumn = document.querySelector(`.panel-operaciones-col[data-estado="${data.estado}"]`);
            if (shouldInsertCard && !insertCardFromHtml(targetColumn, data.html)) {
              throw new Error('No se pudo insertar la operacion creada.');
            }
            closeSharedInlineForm();
            showInlineNotification(data.message || 'Operacion creada correctamente.', 'success');
            return;
          }

          if (data.html_form || data.html) {
            destroyInlineFormComponents(inlineFormSlot);
            inlineFormSlot.innerHTML = data.html_form || data.html;
            syncInlineDestinationLabel(inlineRequestedTarget?.estadoLabel || inlineRequestedTarget?.estado || estado);
            initInlineFormComponents(inlineFormSlot);
            const invalidInput = inlineFormSlot.querySelector('.is-invalid, input, select');
            if (invalidInput) invalidInput.focus();
          } else {
            const errors = data.errors || {};
            const firstError = Object.values(errors).flat().map((item) => item.message || item).find(Boolean);
            renderInlineError(container, data.message || firstError || 'No se pudo crear la operacion.');
            showInlineNotification(data.message || firstError || 'No se pudo crear la operacion.', 'danger');
          }
        })
        .catch((error) => {
          console.error('No se pudo crear la operacion:', error);
          renderInlineError(container, 'No se pudo crear la operacion. Intenta nuevamente.');
          showInlineNotification('No se pudo crear la operacion. Intenta nuevamente.', 'danger');
        })
        .finally(() => {
          const activeForm = container.querySelector('[data-operacion-inline-form="1"]');
          setInlineFormPending(activeForm, false);
        });
    }

    function replaceCardFromHtml(card, cardHtml) {
      if (!card || !cardHtml) return null;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = cardHtml;
      const nextCard = wrapper.firstElementChild;
      if (!nextCard) return null;
      invalidateColumnLoads();
      card.replaceWith(nextCard);
      syncColumnState(nextCard.closest('.panel-operaciones-col'));
      return nextCard;
    }

    function showColumnFormError(form, message) {
      if (!form) return;
      const errorNode = form.querySelector('[data-operacion-column-create-error="1"], [data-operacion-column-edit-error="1"], [data-operacion-column-delete-error="1"]');
      if (!errorNode) return;
      errorNode.textContent = message || '';
      errorNode.classList.toggle('d-none', !message);
    }

    function appendColumnFromHtml(columnHtml) {
      if (!columnHtml) return null;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = columnHtml.trim();
      const shell = wrapper.firstElementChild;
      if (!shell) return null;
      root.appendChild(shell);
      initSortable();
      syncInlineCreateAccess();
      return shell;
    }

    function syncDeleteDestinationOptions(currentShell) {
      if (!columnDeleteForm) return;
      const select = columnDeleteForm.querySelector('select[name="columna_destino_id"]');
      if (!select) return;
      const currentId = getColumnId(currentShell);
      const options = Array.from(root.querySelectorAll('[data-operaciones-column="1"]'))
        .filter((shell) => getColumnId(shell) && getColumnId(shell) !== currentId)
        .map((shell) => ({ id: getColumnId(shell), name: getColumnName(shell) }));
      select.innerHTML = '<option value="">Selecciona una columna</option>';
      options.forEach((option) => {
        const node = document.createElement('option');
        node.value = option.id;
        node.textContent = option.name;
        select.appendChild(node);
      });
    }

    function updateColumnMetadata(shell, { name }) {
      if (!shell || !name) return;
      shell.dataset.columnaNombre = name;
      const title = shell.querySelector('[data-operacion-column-title="1"]');
      if (title) title.textContent = name;
      const body = getColumnItems(shell);
      if (body) body.dataset.columnaNombre = name;
      const inlineButton = shell.querySelector('[data-operacion-inline-open="1"]');
      if (inlineButton) inlineButton.dataset.estadoLabel = name;
    }

    function buildInlineOpenButtonMarkup(shell) {
      const columnId = getColumnId(shell);
      const state = getColumnState(shell);
      const label = getColumnName(shell);
      return `
        <button
          type="button"
          class="btn btn-sm operaciones-column__add-btn"
          data-operacion-inline-open="1"
          data-columna-id="${columnId}"
          data-estado="${state}"
          data-estado-label="${label}">
          + Nueva operacion
        </button>
      `.trim();
    }

    function ensureColumnActions(shell) {
      if (!shell) return null;
      let actions = shell.querySelector('.operaciones-column__actions');
      if (!actions) {
        actions = document.createElement('div');
        actions.className = 'operaciones-column__actions px-3 pt-3';
        const header = shell.querySelector('.operaciones-column__header');
        header?.insertAdjacentElement('afterend', actions);
      }
      return actions;
    }

    function syncInlineCreateAccess() {
      const shells = Array.from(root.querySelectorAll('[data-operaciones-column="1"]'));
      const firstShell = shells[0] || null;
      const currentActions = root.querySelector('.operaciones-column__actions');

      if (!firstShell) {
        currentActions?.remove();
        closeSharedInlineForm({reset: false});
        return;
      }

      const targetActions = ensureColumnActions(firstShell);
      if (!targetActions) return;

      if (currentActions && currentActions !== targetActions) {
        if (inlineContainer && !inlineContainer.classList.contains('d-none')) {
          closeSharedInlineForm({reset: false});
        }
        currentActions.remove();
      }

      targetActions.innerHTML = buildInlineOpenButtonMarkup(firstShell);
    }

    function restoreQuickEditCard(card) {
      const cardId = card?.dataset.panelOperacionId;
      const originalHtml = quickEditOriginalHtml.get(card);
      if (!card || !originalHtml) return;
      card.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
      card.innerHTML = originalHtml;
      quickEditOriginalHtml.delete(card);
      if (cardId) quickEditingCardIds.delete(cardId);
      delete card.dataset.quickEditing;
    }

    function closeQuickEditors(exceptCard = null) {
      document.querySelectorAll('[data-panel-operacion-card="1"][data-quick-editing="1"]').forEach((card) => {
        if (card !== exceptCard && !isCardPending(card)) restoreQuickEditCard(card);
      });
    }

    function showQuickEditLoadError(card) {
      restoreQuickEditCard(card);
      const body = card?.querySelector('.operaciones-card__body');
      if (!body) return;
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-quick-edit-error';
      error.textContent = 'No se pudo cargar la edicion rapida.';
      body.prepend(error);
    }

    function openQuickEdit(card, url) {
      const cardId = card?.dataset.panelOperacionId;
      if (!card || !url || isCardBusy(card)) return;

      closeQuickEditors(card);
      quickEditOriginalHtml.set(card, card.innerHTML);
      quickEditingCardIds.add(cardId);
      card.dataset.quickEditing = '1';
      card.innerHTML = '<div class="operaciones-card__body text-center text-muted small py-4">Cargando edicion...</div>';

      fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.ok || !data.html) throw new Error(data.error || `Error ${response.status}`);
          return data;
        })
        .then((data) => {
          card.innerHTML = data.html;
          initOperacionModalContent(card);
          const firstInput = card.querySelector('input:not([type="hidden"]), select, textarea');
          if (firstInput) firstInput.focus();
        })
        .catch((error) => {
          console.error('No se pudo cargar la edicion rapida:', error);
          showQuickEditLoadError(card);
        });
    }

    function submitQuickEdit(form) {
      const card = form.closest('[data-panel-operacion-card="1"]');
      if (!card || isCardPending(card)) return;

      setCardPending(card, true);
      form.dataset.pending = '1';
      postForm(form.getAttribute('action'), new FormData(form), form)
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.ok) return data;
          return data;
        })
        .then((data) => {
          if (data.ok && replaceCardFromHtml(card, data.html)) {
            quickEditOriginalHtml.delete(card);
            quickEditingCardIds.delete(card.dataset.panelOperacionId);
            return;
          }

          if (data.html) {
            card.innerHTML = data.html;
            initOperacionModalContent(card);
            const invalidInput = card.querySelector('.is-invalid, input, select');
            if (invalidInput) invalidInput.focus();
          } else {
            throw new Error('No se pudo guardar la edicion rapida.');
          }
        })
        .catch((error) => {
          console.error('No se pudo guardar la edicion rapida:', error);
          const errorNode = card.querySelector('.operaciones-quick-edit-error');
          if (errorNode) {
            errorNode.textContent = 'No se pudo guardar la operacion. Intenta nuevamente.';
          } else {
            const formBody = card.querySelector('.operaciones-card__body');
            if (formBody) {
              formBody.insertAdjacentHTML(
                'afterbegin',
                '<div class="alert alert-danger small py-2 mb-2 operaciones-quick-edit-error">No se pudo guardar la operacion. Intenta nuevamente.</div>'
              );
            }
          }
        })
        .finally(() => {
          setCardPending(card, false);
          const activeForm = card.querySelector('[data-operacion-quick-edit-form="1"]');
          if (activeForm) delete activeForm.dataset.pending;
        });
    }

    function getLoadedCardIds(column) {
      return Array.from(
        column?.querySelectorAll('[data-panel-operacion-card="1"]') || []
      )
        .map((card) => card.dataset.panelOperacionId || '')
        .filter(Boolean);
    }

    function getSelectedUserId() {
      return document.getElementById('OperacionesUserFilter')?.value || '';
    }

    function setColumnLoading(shell, isLoading) {
      const button = shell?.querySelector('[data-operacion-load-more="1"]');
      const indicator = shell?.querySelector('[data-operacion-load-indicator="1"]');
      if (button) {
        button.disabled = isLoading;
        button.setAttribute('aria-busy', isLoading ? 'true' : 'false');
      }
      indicator?.classList.toggle('d-none', !isLoading);
    }

    function showColumnLoadError(shell, message) {
      const node = shell?.querySelector('[data-operacion-load-error="1"]');
      if (!node) return;
      node.textContent = message || '';
      node.classList.toggle('d-none', !message);
    }

    function invalidateColumnLoads() {
      boardVersion += 1;
      columnLoadRequests.forEach((entry) => entry.controller.abort());
      columnLoadRequests.clear();
    }

    function loadMoreCards(button) {
      const shell = button?.closest('[data-operaciones-column="1"]');
      const column = shell?.querySelector('.panel-operaciones-col');
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
          let data;
          try {
            data = await response.json();
          } catch (_) {
            throw new Error('Respuesta JSON invalida.');
          }
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
            data.loaded > 10 ||
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

          staleIds.forEach((cardId) => getCardElement(cardId)?.remove());
          const wrapper = document.createElement('div');
          wrapper.innerHTML = data.html;
          const cards = Array.from(wrapper.children).filter(
            (node) => node.matches?.('[data-panel-operacion-card="1"]')
          );
          if (cards.length !== data.loaded) {
            throw new Error('Cantidad de tarjetas inesperada.');
          }
          const existingIds = new Set(getLoadedCardIds(column));
          const responseIds = new Set();
          cards.forEach((card) => {
            const cardId = card.dataset.panelOperacionId || '';
            if (
              !cardId ||
              existingIds.has(cardId) ||
              responseIds.has(cardId) ||
              card.dataset.operacionState !== state
            ) {
              throw new Error('Tarjeta duplicada o incompatible.');
            }
            responseIds.add(cardId);
          });

          column.querySelector('.panel-operacion-empty')?.remove();
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
      if (!columnReorderUrl) return Promise.resolve();
      const formData = new FormData();
      Array.from(root.querySelectorAll('[data-operaciones-column="1"]')).forEach((shell) => {
        const columnId = getColumnId(shell);
        if (columnId) formData.append('columnas[]', columnId);
      });
      return postForm(columnReorderUrl, formData).then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) throw new Error(data.error || `Error ${response.status}`);
        return data;
      });
    }

    function initSortable() {
      if (typeof Sortable === 'undefined') return;
      if (root.dataset.columnSortableReady !== '1') {
        root.dataset.columnSortableReady = '1';
        Sortable.create(root, {
          animation: 150,
          draggable: '[data-operaciones-column="1"]',
          ghostClass: 'panel-operacion-ghost',
          dragClass: 'panel-operacion-drag',
          onEnd: function () {
            syncInlineCreateAccess();
            submitColumnOrder().catch((error) => {
              console.error('No se pudo reordenar las columnas:', error);
              reloadBoard();
            });
          }
        });
      }
      document.querySelectorAll('.panel-operaciones-col').forEach((column) => {
        if (column.dataset.sortableReady === '1') return;
        column.dataset.sortableReady = '1';
        Sortable.create(column, {
          group: 'panel-operaciones-kanban',
          animation: 150,
          ghostClass: 'panel-operacion-ghost',
          dragClass: 'panel-operacion-drag',
          onMove: function (evt) {
            return !isCardBusy(evt.dragged);
          },
          onEnd: function (evt) {
            const card = evt.item;
            moveOperacionCard({
              card,
              targetColumn: evt.to,
              targetState: evt.to?.dataset.estado,
              sourceColumn: evt.from,
              sourceIndex: evt.oldIndex,
            });
          }
        });
        syncColumnUI(column);
      });
    }

    function initOperacionModalContent(container) {
      if (!container) return;
      if (window.initGarantiaSelects) {
        window.initGarantiaSelects(container);
      }
      initInlineFormComponents(container);
      if (window.initOperacionSelects) {
        window.initOperacionSelects(container);
      }
    }

    function getCardElement(cardId) {
      return cardId ? document.getElementById(`panel-operacion-${cardId}`) : null;
    }

    function getDetailContainer() {
      return detailState.layout === 'drawer' ? drawerContent : modalContent;
    }

    function setDetailPending(isPending) {
      detailState.pending = isPending;
      const container = getDetailContainer();
      container?.querySelectorAll('button, input, select, textarea').forEach((control) => {
        control.disabled = isPending;
      });
      setCardPending(getCardElement(detailState.id), isPending);
    }

    function renderDetailHtml(html) {
      const container = getDetailContainer();
      if (!container) return;
      container.innerHTML = html || '';
      initOperacionModalContent(container);
    }

    function renderDetailError(message) {
      renderDetailHtml(`<div class="alert alert-danger m-3 mb-0">${message}</div>`);
    }

    function replaceFilesSection(filesHtml) {
      const container = getDetailContainer();
      const currentSection = container?.querySelector('[data-operacion-files-section="1"]');
      if (!currentSection || !filesHtml) return null;

      const wrapper = document.createElement('div');
      wrapper.innerHTML = filesHtml;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return null;
      currentSection.replaceWith(nextSection);
      return nextSection;
    }

    function syncFilesCount(cardId, count) {
      const container = getDetailContainer();
      const detailCount = container?.querySelector('[data-operacion-detail-files-count="1"]');
      if (detailCount) detailCount.textContent = String(count);

      const cardCount = getCardElement(cardId)?.querySelector('[data-operacion-card-files-count="1"]');
      if (cardCount) cardCount.textContent = `Archivos: ${count}`;
    }

    function setFilesPending(section, isPending) {
      if (!section) return;
      if (isPending) {
        section.dataset.pending = '1';
      } else {
        delete section.dataset.pending;
      }
      section.querySelectorAll('button, input[type="file"]').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderFilesError(section, message) {
      if (!section) return;
      section.querySelector('.operaciones-files-error')?.remove();
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-files-error';
      error.textContent = message;
      section.querySelector('[data-operacion-archivo-form="1"]')?.before(error);
    }

    function replaceLinksSection(linksHtml) {
      const container = getDetailContainer();
      const currentSection = container?.querySelector('[data-operacion-links-section="1"]');
      if (!currentSection || !linksHtml) return null;

      const wrapper = document.createElement('div');
      wrapper.innerHTML = linksHtml;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return null;
      currentSection.replaceWith(nextSection);
      return nextSection;
    }

    function syncLinksCount(cardId, count) {
      const container = getDetailContainer();
      const detailCount = container?.querySelector('[data-operacion-detail-links-count="1"]');
      if (detailCount) detailCount.textContent = String(count);

      const cardCount = getCardElement(cardId)?.querySelector('[data-operacion-card-links-count="1"]');
      if (cardCount) cardCount.textContent = `Enlaces: ${count}`;
    }

    function setLinksPending(section, isPending) {
      if (!section) return;
      if (isPending) {
        section.dataset.pending = '1';
      } else {
        delete section.dataset.pending;
      }
      section.setAttribute('aria-busy', isPending ? 'true' : 'false');
      section.querySelectorAll('button, input').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderLinksError(section, message) {
      if (!section) return;
      section.querySelector('.operaciones-links-error')?.remove();
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-links-error';
      error.setAttribute('role', 'alert');
      error.textContent = message;
      section.querySelector('[data-operacion-enlace-form="1"]')?.before(error);
    }

    function focusLinksForm(section) {
      const input = section?.querySelector('[data-operacion-enlace-form="1"] [name="titulo"]');
      if (input) input.focus();
    }

    function getActiveTagsSection(cardId) {
      const container = getDetailContainer();
      const currentSection = container?.querySelector('[data-operacion-tags-section="1"]');
      if (!currentSection || currentSection.dataset.operacionId !== String(cardId)) return null;
      return currentSection;
    }

    function replaceTagsSection(tagsHtml, cardId) {
      const currentSection = getActiveTagsSection(cardId);
      if (!currentSection || !tagsHtml) return null;

      const wrapper = document.createElement('div');
      wrapper.innerHTML = tagsHtml;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return null;
      currentSection.replaceWith(nextSection);
      return nextSection;
    }

    function isSafeTagColor(color) {
      return /^#[0-9a-f]{6}$/i.test(color || '');
    }

    function renderTagBadges(container, tags, className) {
      if (!container) return;
      container.replaceChildren();
      tags.forEach((tag) => {
        const badge = document.createElement('span');
        badge.className = className;
        badge.textContent = tag.nombre;
        if (className === 'operaciones-tag') {
          badge.style.setProperty('--operacion-tag-bg', isSafeTagColor(tag.color) ? tag.color : '#3e9fa2');
        } else {
          badge.style.backgroundColor = isSafeTagColor(tag.color) ? tag.color : '#3e9fa2';
          badge.style.color = '#fff';
        }
        container.appendChild(badge);
      });
    }

    function syncTagsUI(cardId, tags) {
      const safeTags = Array.isArray(tags) ? tags : [];
      renderTagBadges(
        getCardElement(cardId)?.querySelector('[data-operacion-card-tags="1"]'),
        safeTags,
        'operaciones-tag'
      );
      if (!getActiveTagsSection(cardId)) return;
      renderTagBadges(
        getDetailContainer()?.querySelector('[data-operacion-detail-header-tags="1"]'),
        safeTags,
        'badge'
      );
      const detailCount = getDetailContainer()?.querySelector('[data-operacion-detail-tags-count="1"]');
      if (detailCount) detailCount.textContent = String(safeTags.length);
    }

    function setTagsPending(section, isPending) {
      if (!section) return;
      if (isPending) {
        section.dataset.pending = '1';
      } else {
        delete section.dataset.pending;
      }
      section.setAttribute('aria-busy', isPending ? 'true' : 'false');
      section.querySelectorAll('button, input, select').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderTagsError(section, message) {
      if (!section) return;
      section.querySelector('.operaciones-tags-error')?.remove();
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-tags-error';
      error.setAttribute('role', 'alert');
      error.textContent = message;
      section.prepend(error);
    }

    function focusTagsForm(section, isCreate) {
      const selector = isCreate ? '[data-operacion-tag-create-form="1"] [name="nombre"]' : '[data-operacion-tag-assign-form="1"] select';
      section?.querySelector(selector)?.focus();
    }

    function getActiveOptionsSection(cardId) {
      if (String(detailState.id) !== String(cardId)) return null;
      const container = getDetailContainer();
      const currentSection = container?.querySelector('[data-operacion-options-section="1"]');
      if (!currentSection || currentSection.dataset.operacionId !== String(cardId)) return null;
      return currentSection;
    }

    function replaceOptionsSection(optionsHtml, cardId) {
      const currentSection = getActiveOptionsSection(cardId);
      if (!currentSection || !optionsHtml) return null;

      const wrapper = document.createElement('div');
      wrapper.innerHTML = optionsHtml;
      const nextSection = wrapper.firstElementChild;
      if (
        !nextSection ||
        !nextSection.matches('[data-operacion-options-section="1"]') ||
        nextSection.dataset.operacionId !== String(cardId)
      ) return null;
      currentSection.replaceWith(nextSection);
      return nextSection;
    }

    function syncOptionsCount(cardId, count) {
      const section = getActiveOptionsSection(cardId);
      const detailCount = section?.querySelector('[data-operacion-detail-options-count="1"]');
      if (detailCount) detailCount.textContent = String(count);
    }

    function setOptionsPending(section, isPending) {
      if (!section) return;
      if (isPending) {
        section.dataset.pending = '1';
      } else {
        delete section.dataset.pending;
      }
      section.setAttribute('aria-busy', isPending ? 'true' : 'false');
      section.querySelectorAll('button, input').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderOptionsError(section, message) {
      if (!section) return;
      section.querySelector('.operaciones-options-error')?.remove();
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-options-error';
      error.setAttribute('role', 'alert');
      error.textContent = message;
      section.prepend(error);
    }

    function focusOptionsForm(section, isCreate, isRemove) {
      const selector = isCreate
        ? '[data-operacion-option-create-form="1"] [name="nombre"]'
        : isRemove
          ? '[data-operacion-option-remove-form="1"] button, [data-operacion-options-form="1"] input[type="checkbox"], [data-operacion-option-create-form="1"] [name="nombre"]'
          : '[data-operacion-options-form="1"] input[type="checkbox"], [data-operacion-option-create-form="1"] [name="nombre"]';
      section?.querySelector(selector)?.focus();
    }

    function getActiveActionSection(cardId) {
      if (String(detailState.id) !== String(cardId)) return null;
      const container = getDetailContainer();
      const currentSection = container?.querySelector('[data-operacion-action-section="1"]');
      if (!currentSection || currentSection.dataset.operacionId !== String(cardId)) return null;
      return currentSection;
    }

    function replaceActionSection(sectionHtml, cardId) {
      const currentSection = getActiveActionSection(cardId);
      if (!currentSection || !sectionHtml) return null;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = sectionHtml;
      const nextSection = wrapper.querySelector('[data-operacion-action-section="1"]');
      if (!nextSection) return null;
      currentSection.replaceWith(nextSection);
      return nextSection;
    }

    function syncActionSummary(cardId, resumen) {
      const summaryNode = getActiveActionSection(cardId)?.querySelector('[data-operacion-action-summary="1"]');
      if (summaryNode && resumen) {
        summaryNode.textContent = `${resumen.completados}/${resumen.total}`;
      }
    }

    function setActionSectionPending(section, isPending) {
      if (!section) return;
      if (isPending) section.dataset.pending = '1';
      else delete section.dataset.pending;
      section.setAttribute('aria-busy', isPending ? 'true' : 'false');
      section.querySelectorAll('button, input').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function setActionItemPending(item, isPending) {
      if (!item) return;
      if (isPending) item.dataset.pending = '1';
      else delete item.dataset.pending;
      item.querySelectorAll('button, input').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderActionCreateError(section, message) {
      const errorNode = section?.querySelector('[data-operacion-action-create-error="1"]');
      if (!errorNode) return;
      if (message) {
        errorNode.textContent = message;
        errorNode.classList.remove('d-none');
      } else {
        errorNode.textContent = '';
        errorNode.classList.add('d-none');
      }
    }

    function renderActionItemError(item, message) {
      const errorNode = item?.querySelector('[data-operacion-action-error="1"]');
      if (!errorNode) return;
      if (message) {
        errorNode.textContent = message;
        errorNode.classList.remove('d-none');
      } else {
        errorNode.textContent = '';
        errorNode.classList.add('d-none');
      }
    }

    function setActionItemCompleted(item, completed) {
      if (!item) return;
      item.classList.toggle('is-completed', Boolean(completed));
      const checkbox = item.querySelector('.operacion-action-item__checkbox');
      if (checkbox) checkbox.checked = Boolean(completed);
      const hiddenInput = item.querySelector('[data-operacion-action-toggle-form="1"] input[name="completado"]');
      if (hiddenInput) hiddenInput.value = completed ? 'false' : 'true';
    }

    function openActionItemEditor(item) {
      if (!item) return;
      const textButton = item.querySelector('[data-operacion-action-edit-open="1"]');
      const form = item.querySelector('[data-operacion-action-edit-form="1"]');
      const input = form?.querySelector('[data-operacion-action-edit-input="1"]');
      if (!form || !input) return;
      item.dataset.editing = '1';
      textButton?.classList.add('d-none');
      form.classList.remove('d-none');
      renderActionItemError(item, '');
      input.dataset.originalValue = input.value;
      input.focus();
      input.select();
    }

    function closeActionItemEditor(item, {restore = false} = {}) {
      if (!item) return;
      const textButton = item.querySelector('[data-operacion-action-edit-open="1"]');
      const form = item.querySelector('[data-operacion-action-edit-form="1"]');
      const input = form?.querySelector('[data-operacion-action-edit-input="1"]');
      if (restore && input?.dataset.originalValue != null) {
        input.value = input.dataset.originalValue;
      }
      delete item.dataset.editing;
      form?.classList.add('d-none');
      textButton?.classList.remove('d-none');
      renderActionItemError(item, '');
    }

    function replaceCommentsSection(commentsHtml) {
      const container = getDetailContainer();
      const currentSection = container?.querySelector('[data-operacion-comments-section="1"]');
      if (!currentSection || !commentsHtml) return null;

      const wrapper = document.createElement('div');
      wrapper.innerHTML = commentsHtml;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return null;
      currentSection.replaceWith(nextSection);
      return nextSection;
    }

    function syncCommentsCount(cardId, count) {
      const container = getDetailContainer();
      const detailCount = container?.querySelector('[data-operacion-detail-comments-count="1"]');
      if (detailCount) detailCount.textContent = String(count);

      const cardCount = getCardElement(cardId)?.querySelector('[data-operacion-card-comments-count="1"]');
      if (cardCount) cardCount.textContent = `Comentarios: ${count}`;
    }

    function setCommentsPending(section, isPending) {
      if (!section) return;
      if (isPending) {
        section.dataset.pending = '1';
      } else {
        delete section.dataset.pending;
      }
      section.querySelectorAll('[data-operacion-comentario-form="1"] button, [data-operacion-comentario-form="1"] textarea').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function renderCommentsError(section, message) {
      if (!section) return;
      section.querySelector('.operaciones-comments-error')?.remove();
      const error = document.createElement('div');
      error.className = 'alert alert-danger small py-2 mb-2 operaciones-comments-error';
      error.textContent = message;
      section.querySelector('[data-operacion-comentario-form="1"]')?.before(error);
    }

    function submitCommentForm(commentForm) {
      if (!commentForm) return;

      const url = commentForm.getAttribute('action');
      const textarea = commentForm.querySelector('textarea[name="comentario"]');
      const text = (textarea?.value || '').trim();
      const section = commentForm.closest('[data-operacion-comments-section="1"]');
      const cardId = commentForm.dataset.operacionId || detailState.id;

      if (!url || !text || !section || !cardId || detailState.pending || section.dataset.pending === '1' || commentForm.dataset.submitting === '1') {
        return;
      }

      const scrollTop = getDetailContainer()?.scrollTop || 0;
      const formData = new FormData(commentForm);
      const csrfToken = window.getCSRFToken?.(commentForm);

      if (!csrfToken) {
        renderCommentsError(section, 'No se encontro un token CSRF valido. Recarga la pagina e intenta nuevamente.');
        return;
      }

      commentForm.dataset.submitting = '1';
      setCommentsPending(section, true);

      fetch(url, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrfToken,
          'Accept': 'application/json',
        }
      })
        .then(async (response) => {
          const contentType = response.headers.get('content-type') || '';
          let data = null;

          if (contentType.includes('application/json')) {
            data = await response.json().catch(() => null);
          }

          if (!data) {
            const error = new Error(response.status === 403
              ? 'La verificacion CSRF fallo. Recarga la pagina e intenta nuevamente.'
              : 'El servidor devolvio una respuesta inesperada.');
            error.status = response.status;
            throw error;
          }

          if (!response.ok || !data.success) {
            const error = new Error(data.error || `Error ${response.status}`);
            error.status = response.status;
            error.data = data;
            throw error;
          }

          return data;
        })
        .then((data) => {
          if (!replaceCommentsSection(data.comments_html)) {
            throw new Error('No se pudo actualizar la seccion de comentarios.');
          }
          syncCommentsCount(cardId, data.comments_count);
          const container = getDetailContainer();
          if (container) container.scrollTop = scrollTop;
        })
        .catch((error) => {
          console.error('No se pudo agregar el comentario:', error);
          if (error?.data?.comments_html && replaceCommentsSection(error.data.comments_html)) {
            syncCommentsCount(cardId, error.data.comments_count || 0);
            return;
          }
          const message = error?.status === 403
            ? 'La verificacion CSRF fallo. Recarga la pagina e intenta nuevamente.'
            : 'No se pudo agregar el comentario. Intenta nuevamente.';
          renderCommentsError(section, message);
        })
        .finally(() => {
          delete commentForm.dataset.submitting;
          setCommentsPending(section, false);
        });
    }

    function openDrawer() {
      if (!drawerSupported) return;
      drawerElement.hidden = false;
      drawerElement.classList.add('is-open');
      drawerElement.setAttribute('aria-hidden', 'false');
      document.body.classList.add('operaciones-drawer-open');
    }

    function closeDrawer(force = false) {
      if (!drawerSupported || (detailState.pending && !force)) return;
      drawerElement.classList.remove('is-open');
      drawerElement.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('operaciones-drawer-open');
      detailState.id = null;
      detailState.url = null;
      window.setTimeout(() => {
        if (!drawerElement.classList.contains('is-open')) {
          drawerElement.hidden = true;
          drawerContent.innerHTML = '<div class="operaciones-drawer__loading">Selecciona una operacion.</div>';
        }
      }, 220);
    }

    function closeDetail(force = false) {
      if (detailState.pending && !force) return;
      if (detailState.layout === 'drawer') {
        closeDrawer(force);
      } else if (modalInstance) {
        modalInstance.hide();
        detailState.id = null;
        detailState.url = null;
      }
    }

    if (drawerElement) {
      drawerElement.addEventListener('click', (e) => {
        const detailCloseButton = e.target.closest('[data-operacion-drawer-close="1"], [data-operacion-detail-close="1"]');
        if (!detailCloseButton) return;
        e.preventDefault();
        e.stopPropagation();
        closeDetail();
      });
    }

    function getDetailCardIdFromAction(action) {
      const match = (action || '').match(/\/(\d+)\/(?:editar|archivo|enlace|comentario|eliminar)\/?$/);
      return match ? match[1] : detailState.id;
    }

    function removeCardFromBoard(cardId) {
      const card = getCardElement(cardId);
      if (!card) return;
      const column = card.closest('.panel-operaciones-col');
      invalidateColumnLoads();
      card.remove();
      adjustColumnTotal(column, -1);
    }

    function loadDetail(cardId, url, preferredLayout) {
      const layout = preferredLayout === 'drawer' && drawerSupported ? 'drawer' : 'modal';
      detailState.id = cardId ? String(cardId) : null;
      detailState.url = url || null;
      detailState.layout = layout;

      if (layout === 'drawer') {
        openDrawer();
        renderDetailHtml('<div class="operaciones-drawer__loading">Cargando detalle...</div>');
      } else if (modalContent && modalInstance) {
        modalContent.innerHTML = '<div class="modal-body p-4 text-center text-muted">Cargando...</div>';
        modalInstance.show();
      } else {
        return Promise.resolve();
      }

      return getHtml(url)
        .then((html) => renderDetailHtml(html))
        .catch((error) => {
          console.error('No se pudo cargar la operacion:', error);
          renderDetailError('No se pudo cargar la operacion.');
        });
    }

    function performDelete() {
      if (!operacionDeleteUrl) return;
      const token = window.getCSRFToken();
      if (!token) return;
      fetch(operacionDeleteUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': token,
          'X-Requested-With': 'XMLHttpRequest'
        }
      })
        .then((response) => {
          if (!response.ok) throw new Error(`Error ${response.status}`);
          return response.json();
        })
        .then((data) => {
          if (data.success) {
            reloadBoard();
          }
        })
        .catch((error) => {
          console.error('No se pudo eliminar la operacion:', error);
          if (confirmModalInstance) confirmModalInstance.hide();
        });
    }

    root.addEventListener('change', (e) => {
      if (e.target && e.target.id === 'OperacionesUserFilter') {
        invalidateColumnLoads();
        e.target.form?.submit();
        return;
      }

      const stateSelect = e.target.closest('[data-operacion-state-select="1"]');
      if (!stateSelect) return;

      const card = stateSelect.closest('[data-panel-operacion-card="1"]');
      const sourceColumn = card?.closest('.panel-operaciones-col');
      const previousState = card?.dataset.operacionState || sourceColumn?.dataset.estado;
      const targetState = stateSelect.value;

      if (!card || !sourceColumn || !targetState || targetState === previousState || isCardBusy(card)) {
        syncCardStateUI(card, previousState, getStateLabel(card, previousState));
        return;
      }

      const targetColumn = document.querySelector(`.panel-operaciones-col[data-estado="${targetState}"]`);
      if (!targetColumn) {
        syncCardStateUI(card, previousState, getStateLabel(card, previousState));
        return;
      }

      moveOperacionCard({
        card,
        targetColumn,
        targetState,
        sourceColumn,
        sourceIndex: getCardIndex(card, sourceColumn),
      });
    });

    root.addEventListener('click', (e) => {
      const loadMoreButton = e.target.closest('[data-operacion-load-more="1"]');
      if (loadMoreButton) {
        e.preventDefault();
        loadMoreCards(loadMoreButton).catch(() => {});
        return;
      }

      const quickEditOpenButton = e.target.closest('[data-operacion-quick-edit-open="1"]');
      if (quickEditOpenButton) {
        e.preventDefault();
        const card = quickEditOpenButton.closest('[data-panel-operacion-card="1"]');
        openQuickEdit(card, quickEditOpenButton.dataset.operacionQuickEditUrl);
        return;
      }

      const quickEditCancelButton = e.target.closest('[data-operacion-quick-edit-cancel="1"]');
      if (quickEditCancelButton) {
        e.preventDefault();
        const card = quickEditCancelButton.closest('[data-panel-operacion-card="1"]');
        if (!isCardPending(card)) restoreQuickEditCard(card);
        return;
      }

      const copyCardButton = e.target.closest('[data-operacion-copy-card="1"]');
      if (copyCardButton) {
        e.preventDefault();
        e.stopPropagation();
        const cardId = Number.parseInt(copyCardButton.dataset.tarjetaId || '', 10);
        if (Number.isNaN(cardId) || cardId <= 0) {
          showInlineNotification('No se pudo copiar la tarjeta.', 'danger');
          return;
        }
        setCopiedCardPayload({ modulo: 'operaciones', tarjeta_id: cardId });
        showInlineNotification('Tarjeta copiada. Selecciona una columna para pegarla.', 'success');
        return;
      }

      const inlineOpenButton = e.target.closest('[data-operacion-inline-open="1"]');
      if (inlineOpenButton) {
        e.preventDefault();
        const column = inlineOpenButton.closest('[data-operaciones-column="1"]');
        const actions = column?.querySelector('.operaciones-column__actions');
        const estado = inlineOpenButton.dataset.estado || column?.querySelector('.panel-operaciones-col')?.dataset.estado;
        const estadoLabel = column?.querySelector('.operaciones-column__title')?.textContent?.trim() || estado;
        if (!inlineContainer || !actions || !estado) return;
        if (inlineContainer.querySelector('[data-operacion-inline-form="1"]')?.dataset.pending === '1') return;
        inlineRequestedTarget = {estado};
        inlineRequestedTarget.estadoLabel = estadoLabel;
        const targetLabel = inlineContainer.querySelector('[data-operacion-inline-target-label="1"]');
        if (targetLabel) targetLabel.textContent = estadoLabel;
        syncInlineDestinationLabel(estadoLabel);
        inlineContainer.dataset.estado = estado;
        actions.insertAdjacentElement('afterend', inlineContainer);
        inlineContainer.classList.remove('d-none');
        loadSharedInlineForm();
        return;
      }

      const pasteButton = e.target.closest('[data-operacion-column-paste="1"]');
      if (pasteButton) {
        e.preventDefault();
        pasteCopiedCard(pasteButton);
        return;
      }

      const clearCopyButton = e.target.closest('[data-operacion-copy-clear="1"]');
      if (clearCopyButton) {
        e.preventDefault();
        clearCopiedCardPayload();
        showInlineNotification('Copia cancelada.', 'success');
        return;
      }

      const columnEditButton = e.target.closest('[data-operacion-column-edit-open="1"]');
      if (columnEditButton) {
        e.preventDefault();
        activeColumnShell = columnEditButton.closest('[data-operaciones-column="1"]');
        if (!activeColumnShell || !columnEditForm) return;
        columnEditForm.querySelector('input[name="columna_id"]').value = getColumnId(activeColumnShell);
        columnEditForm.querySelector('input[name="nombre"]').value = getColumnName(activeColumnShell);
        showColumnFormError(columnEditForm, '');
        columnEditModalInstance?.show();
        return;
      }

      const columnDeleteButton = e.target.closest('[data-operacion-column-delete-open="1"]');
      if (columnDeleteButton) {
        e.preventDefault();
        activeColumnShell = columnDeleteButton.closest('[data-operaciones-column="1"]');
        if (!activeColumnShell || !columnDeleteForm) return;
        columnDeleteForm.querySelector('input[name="columna_id"]').value = getColumnId(activeColumnShell);
        const copy = columnDeleteForm.querySelector('[data-operacion-column-delete-copy="1"]');
        if (copy) copy.textContent = `Eliminar la columna "${getColumnName(activeColumnShell)}".`;
        syncDeleteDestinationOptions(activeColumnShell);
        showColumnFormError(columnDeleteForm, '');
        columnDeleteModalInstance?.show();
        return;
      }

      const inlineCancelButton = e.target.closest('[data-operacion-inline-cancel="1"]');
      if (inlineCancelButton) {
        e.preventDefault();
        const container = inlineCancelButton.closest('[data-operacion-inline-container="1"]');
        if (container && !container.querySelector('[data-operacion-inline-form="1"]')?.dataset.pending) {
          closeSharedInlineForm();
        }
        return;
      }

      const addLinkButton = e.target.closest('[data-operacion-link-add="1"]');
      if (addLinkButton) {
        e.preventDefault();
        addInlineLinkRow(addLinkButton.closest('[data-operacion-inline-form-fragment="1"]') || inlineFormSlot);
        return;
      }

      const removeLinkButton = e.target.closest('[data-operacion-link-remove="1"]');
      if (removeLinkButton) {
        e.preventDefault();
        removeInlineLinkRow(removeLinkButton);
        return;
      }

      const deleteButton = e.target.closest('[data-panel-operacion-delete="1"]');
      if (deleteButton) {
        e.preventDefault();
        operacionDeleteUrl = deleteButton.dataset.deleteUrl;
        if (confirmModalInstance) confirmModalInstance.show();
        return;
      }

      const confirmDeleteButton = e.target.closest('[data-operacion-confirm-delete="1"]');
      if (confirmDeleteButton) {
        e.preventDefault();
        performDelete();
        return;
      }

      const link = e.target.closest('[data-panel-operacion-modal-open="1"]');
      if (!link) return;
      e.preventDefault();
      e.stopPropagation();
      const url = link.getAttribute('data-modal-url') || link.getAttribute('href');
      const card = link.closest('[data-panel-operacion-card="1"]');
      if (url) loadDetail(card?.dataset.panelOperacionId, url, 'modal');
    });

    document.addEventListener('change', (e) => {
      const checkbox = e.target.closest('.operacion-action-item__checkbox');
      if (!checkbox) return;

      const form = checkbox.closest('[data-operacion-action-toggle-form="1"]');
      const item = checkbox.closest('[data-operacion-action-item="1"]');
      const section = checkbox.closest('[data-operacion-action-section="1"]');
      const cardId = section?.dataset.operacionId || detailState.id;
      if (!form || !item || !section || !cardId || form.dataset.submitting === '1') return;

      const nextChecked = checkbox.checked;
      const previousChecked = !nextChecked;
      const url = form.getAttribute('action');
      const csrfToken = window.getCSRFToken?.(form);
      if (!url || !csrfToken) {
        checkbox.checked = previousChecked;
        setActionItemCompleted(item, previousChecked);
        renderActionItemError(item, 'No se pudo actualizar el elemento.');
        return;
      }

      const hiddenInput = form.querySelector('input[name="completado"]');
      if (hiddenInput) hiddenInput.value = nextChecked ? 'true' : 'false';
      setActionItemCompleted(item, nextChecked);
      const body = new FormData();
      body.append('completado', nextChecked ? 'true' : 'false');
      form.dataset.submitting = '1';
      checkbox.disabled = true;
      renderActionItemError(item, '');

      fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
        body,
      })
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.success) throw data;
          return data;
        })
        .then((data) => {
          setActionItemCompleted(item, data.elemento?.completado);
          syncActionSummary(cardId, data.resumen);
        })
        .catch((error) => {
          console.error('No se pudo actualizar el elemento de accion:', error);
          checkbox.checked = previousChecked;
          if (hiddenInput) hiddenInput.value = previousChecked ? 'true' : 'false';
          setActionItemCompleted(item, previousChecked);
          renderActionItemError(item, error?.error || 'No se pudo actualizar el elemento.');
        })
        .finally(() => {
          delete form.dataset.submitting;
          checkbox.disabled = false;
        });
    });

    document.addEventListener('focusout', (e) => {
      const input = e.target.closest('[data-operacion-action-edit-input="1"]');
      if (!input) return;
      const form = input.closest('[data-operacion-action-edit-form="1"]');
      const item = input.closest('[data-operacion-action-item="1"]');
      if (!form || !item || form.dataset.submitting === '1') return;

      window.setTimeout(() => {
        if (!item.isConnected || item.contains(document.activeElement)) return;
        const nextValue = (input.value || '').trim();
        const originalValue = (input.dataset.originalValue || '').trim();
        if (!nextValue) {
          closeActionItemEditor(item, {restore: true});
          return;
        }
        if (nextValue === originalValue) {
          closeActionItemEditor(item);
          return;
        }
        form.requestSubmit();
      }, 0);
    });

    document.addEventListener('keydown', (e) => {
      const editInput = e.target.closest('[data-operacion-action-edit-input="1"]');
      if (!editInput) return;
      const item = editInput.closest('[data-operacion-action-item="1"]');
      const form = editInput.closest('[data-operacion-action-edit-form="1"]');
      if (!item || !form) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        closeActionItemEditor(item, {restore: true});
        return;
      }

      if (e.key === 'Enter') {
        e.preventDefault();
        form.requestSubmit();
      }
    });

    root.addEventListener('submit', (e) => {
      const quickEditForm = e.target.closest('[data-operacion-quick-edit-form="1"]');
      if (quickEditForm) {
        e.preventDefault();
        submitQuickEdit(quickEditForm);
        return;
      }

      const inlineForm = e.target.closest('[data-operacion-inline-form="1"]');
      if (inlineForm) {
        e.preventDefault();
        createOperacionInline(inlineForm);
        return;
      }

      const detailForm = e.target.closest('[data-operacion-modal-form="1"]');
      if (detailForm) {
        e.preventDefault();
        if (detailState.pending || detailForm.dataset.submitting === '1') return;
        const fd = new FormData(detailForm);
        detailForm.dataset.submitting = '1';
        setDetailPending(true);
        postForm(detailForm.getAttribute('action'), fd)
          .then(async (response) => {
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
              const data = await response.json();
              if (!response.ok) return data;
              return data;
            }
            return { success: false, html: await response.text() };
          })
          .then((data) => {
            if (data.success) {
              const card = getCardElement(detailState.id || getDetailCardIdFromAction(detailForm.action));
              const nextCard = replaceCardFromHtml(card, data.card_html || data.html);
              if (!nextCard) throw new Error('No se pudo actualizar la tarjeta.');
              if (detailState.url) {
                return loadDetail(nextCard.dataset.panelOperacionId, detailState.url, detailState.layout);
              }
            } else if (data.html) {
              renderDetailHtml(data.html);
            }
          })
          .catch((error) => {
            console.error('No se pudo guardar la operacion:', error);
            renderDetailError('No se pudo guardar la operacion.');
          })
          .finally(() => {
            delete detailForm.dataset.submitting;
            setDetailPending(false);
          });
        return;
      }

      const refreshForm = e.target.closest('[data-operacion-modal-delete="1"]');
      if (refreshForm) {
        e.preventDefault();
        if (detailState.pending || refreshForm.dataset.submitting === '1') return;
        const fd = new FormData(refreshForm);
        refreshForm.dataset.submitting = '1';
        setDetailPending(true);
        postForm(refreshForm.getAttribute('action'), fd)
          .then((response) => {
            if (!response.ok) throw new Error(`Error ${response.status}`);
            return response.json();
          })
          .then((data) => {
            if (data.success) {
              if (data.redirect && data.id) {
                removeCardFromBoard(data.id);
                closeDetail(true);
              } else {
                if (data.card_html && data.id) {
                  replaceCardFromHtml(getCardElement(data.id), data.card_html);
                }
                if (data.html) renderDetailHtml(data.html);
              }
            }
          })
          .catch((error) => {
            console.error('No se pudo actualizar la operacion:', error);
            renderDetailError('No se pudo actualizar la operacion.');
          })
          .finally(() => {
            delete refreshForm.dataset.submitting;
            setDetailPending(false);
          });
        return;
      }

      const fileForm = e.target.closest('[data-operacion-archivo-form="1"], [data-operacion-archivo-delete="1"]');
      if (fileForm) {
        e.preventDefault();
        const isDelete = fileForm.matches('[data-operacion-archivo-delete="1"]');
        if (isDelete && !window.confirm('Eliminar este archivo?')) return;

        const section = fileForm.closest('[data-operacion-files-section="1"]');
        const cardId = fileForm.dataset.operacionId || detailState.id;
        if (!section || !cardId || detailState.pending || section.dataset.pending === '1' || fileForm.dataset.submitting === '1') return;

        const input = fileForm.querySelector('input[type="file"]');
        if (!isDelete && !input?.files?.length) return;
        const scrollTop = getDetailContainer()?.scrollTop || 0;
        const fd = new FormData(fileForm);
        fileForm.dataset.submitting = '1';
        setFilesPending(section, true);
        postForm(fileForm.getAttribute('action'), fd, fileForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            if (!replaceFilesSection(data.files_html)) {
              throw new Error('No se pudo actualizar la seccion de archivos.');
            }
            syncFilesCount(cardId, data.files_count);
            const container = getDetailContainer();
            if (container) container.scrollTop = scrollTop;
          })
          .catch((error) => {
            console.error('No se pudo actualizar la seccion de archivos:', error);
            if (error?.files_html && replaceFilesSection(error.files_html)) {
              syncFilesCount(cardId, error.files_count || 0);
              return;
            }
            renderFilesError(section, 'No se pudo actualizar la seccion de archivos. Intenta nuevamente.');
          })
          .finally(() => {
            delete fileForm.dataset.submitting;
            setFilesPending(section, false);
          });
        return;
      }

      const optionForm = e.target.closest('[data-operacion-options-form="1"], [data-operacion-option-create-form="1"], [data-operacion-option-remove-form="1"]');
      if (optionForm) {
        e.preventDefault();
        const isRemove = optionForm.matches('[data-operacion-option-remove-form="1"]');
        const isCreate = optionForm.matches('[data-operacion-option-create-form="1"]');
        if (isRemove && !window.confirm('Quitar esta opcion de la operacion?')) return;

        const section = optionForm.closest('[data-operacion-options-section="1"]');
        const cardId = optionForm.dataset.operacionId || detailState.id;
        if (!section || !cardId || detailState.pending || section.dataset.pending === '1' || optionForm.dataset.submitting === '1') return;

        const nameInput = optionForm.querySelector('[name="nombre"]');
        if (isCreate && !(nameInput?.value || '').trim()) return;
        const scrollTop = getDetailContainer()?.scrollTop || 0;
        const submittedSection = section;
        const fd = new FormData(optionForm);
        optionForm.dataset.submitting = '1';
        setOptionsPending(section, true);
        postForm(optionForm.getAttribute('action'), fd, optionForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            const isActiveDetail = getActiveOptionsSection(cardId) === submittedSection;
            if (!isActiveDetail) return;
            const nextSection = replaceOptionsSection(data.options_html, cardId);
            if (!nextSection) {
              throw new Error('No se pudo actualizar la seccion de opciones.');
            }
            syncOptionsCount(cardId, data.options_count);
            const container = getDetailContainer();
            if (container) container.scrollTop = scrollTop;
            focusOptionsForm(nextSection, isCreate, isRemove);
          })
          .catch((error) => {
            console.error('No se pudo actualizar la seccion de opciones:', error);
            const nextSection =
              getActiveOptionsSection(cardId) === submittedSection &&
              error?.options_html &&
              replaceOptionsSection(error.options_html, cardId);
            if (nextSection) {
              syncOptionsCount(cardId, error.options_count || 0);
              const container = getDetailContainer();
              if (container) container.scrollTop = scrollTop;
              focusOptionsForm(nextSection, isCreate, isRemove);
              return;
            }
            if (getActiveOptionsSection(cardId) === submittedSection) {
              renderOptionsError(section, 'No se pudo actualizar la seccion de opciones. Intenta nuevamente.');
            }
          })
          .finally(() => {
            delete optionForm.dataset.submitting;
            setOptionsPending(section, false);
          });
        return;
      }

      const linkForm = e.target.closest('[data-operacion-enlace-form="1"], [data-operacion-enlace-delete="1"]');
      if (!linkForm) return;
      e.preventDefault();
      const isDelete = linkForm.matches('[data-operacion-enlace-delete="1"]');
      if (isDelete && !window.confirm('Eliminar este enlace?')) return;

      const section = linkForm.closest('[data-operacion-links-section="1"]');
      const cardId = linkForm.dataset.operacionId || detailState.id;
      if (!section || !cardId || detailState.pending || section.dataset.pending === '1' || linkForm.dataset.submitting === '1') return;

      const scrollTop = getDetailContainer()?.scrollTop || 0;
      const fd = new FormData(linkForm);
      linkForm.dataset.submitting = '1';
      setLinksPending(section, true);
      postForm(linkForm.getAttribute('action'), fd, linkForm)
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok || !data.success) throw data;
          return data;
        })
        .then((data) => {
          const nextSection = replaceLinksSection(data.links_html);
          if (!nextSection) {
            throw new Error('No se pudo actualizar la seccion de enlaces.');
          }
          syncLinksCount(cardId, data.links_count);
          const container = getDetailContainer();
          if (container) container.scrollTop = scrollTop;
          focusLinksForm(nextSection);
        })
        .catch((error) => {
          console.error('No se pudo actualizar la seccion de enlaces:', error);
          const nextSection = error?.links_html && replaceLinksSection(error.links_html);
          if (nextSection) {
            syncLinksCount(cardId, error.links_count || 0);
            focusLinksForm(nextSection);
            return;
          }
          renderLinksError(section, 'No se pudo actualizar la seccion de enlaces. Intenta nuevamente.');
        })
        .finally(() => {
          delete linkForm.dataset.submitting;
          setLinksPending(section, false);
        });
    });

    root.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && drawerSupported && drawerElement.classList.contains('is-open')) {
        closeDrawer();
      }
    });

    document.addEventListener('click', (e) => {
      const actionEditButton = e.target.closest('[data-operacion-action-edit-open="1"]');
      if (actionEditButton) {
        e.preventDefault();
        openActionItemEditor(actionEditButton.closest('[data-operacion-action-item="1"]'));
        return;
      }

      const createButton = e.target.closest('[data-operacion-column-create-open="1"]');
      if (createButton) {
        e.preventDefault();
        if (!columnCreateForm) return;
        columnCreateForm.reset();
        showColumnFormError(columnCreateForm, '');
        columnCreateModalInstance?.show();
        return;
      }
    });

    document.addEventListener('submit', (e) => {
      const createForm = e.target.closest('[data-operacion-column-create-form="1"]');
      if (createForm) {
        e.preventDefault();
        if (!columnCreateUrl) return;
        showColumnFormError(createForm, '');
        postForm(columnCreateUrl, new FormData(createForm), createForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok || !data.html) throw new Error(data.error || 'No se pudo crear la columna.');
            return data;
          })
          .then((data) => {
            appendColumnFromHtml(data.html);
            columnCreateModalInstance?.hide();
          })
          .catch((error) => {
            console.error('No se pudo crear la columna:', error);
            showColumnFormError(createForm, error.message || 'No se pudo crear la columna.');
          });
        return;
      }

      const editForm = e.target.closest('[data-operacion-column-edit-form="1"]');
      if (editForm) {
        e.preventDefault();
        const columnId = editForm.querySelector('input[name="columna_id"]')?.value || '';
        const url = activeColumnShell?.dataset.editUrl || (columnId ? `/operaciones/columnas/${columnId}/editar/` : '');
        if (!url) return;
        showColumnFormError(editForm, '');
        postForm(url, new FormData(editForm), editForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo editar la columna.');
            return data;
          })
          .then((data) => {
            updateColumnMetadata(activeColumnShell, { name: data.nombre });
            columnEditModalInstance?.hide();
          })
          .catch((error) => {
            console.error('No se pudo editar la columna:', error);
            showColumnFormError(editForm, error.message || 'No se pudo editar la columna.');
          });
        return;
      }

      const deleteForm = e.target.closest('[data-operacion-column-delete-form="1"]');
      if (deleteForm) {
        e.preventDefault();
        const columnId = deleteForm.querySelector('input[name="columna_id"]')?.value || '';
        const url = activeColumnShell?.dataset.deleteUrl || (columnId ? `/operaciones/columnas/${columnId}/eliminar/` : '');
        if (!url) return;
        showColumnFormError(deleteForm, '');
        postForm(url, new FormData(deleteForm), deleteForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo eliminar la columna.');
            return data;
          })
          .then((data) => {
            const destinationBody = data.columna_destino_id
              ? root.querySelector(`[data-operaciones-column="1"][data-columna-id="${data.columna_destino_id}"]`)?.querySelector('.panel-operaciones-col')
              : null;
            if (activeColumnShell && destinationBody) {
              activeColumnShell.querySelectorAll('[data-operacion-card="1"]').forEach((card) => {
                syncCardStateUI(card, data.columna_destino_codigo, getColumnName(destinationBody.closest('[data-operaciones-column="1"]')));
                card.dataset.estado = data.columna_destino_codigo;
                destinationBody.prepend(card);
              });
              syncColumnState(destinationBody, data.column_count);
            }
            activeColumnShell?.remove();
            syncDeleteDestinationOptions(null);
            invalidateColumnLoads();
            columnDeleteModalInstance?.hide();
            syncInlineCreateAccess();
          })
          .catch((error) => {
            console.error('No se pudo eliminar la columna:', error);
            showColumnFormError(deleteForm, error.message || 'No se pudo eliminar la columna.');
          });
      }
    });

    document.addEventListener('submit', (e) => {
      const actionCreateForm = e.target.closest('[data-operacion-action-create-form="1"]');
      if (actionCreateForm) {
        e.preventDefault();
        const section = actionCreateForm.closest('[data-operacion-action-section="1"]');
        const cardId = actionCreateForm.dataset.operacionId || detailState.id;
        const input = actionCreateForm.querySelector('input[name="texto"]');
        if (!section || !cardId || actionCreateForm.dataset.submitting === '1') return;
        const texto = (input?.value || '').trim();
        if (!texto) {
          renderActionCreateError(section, 'Este campo es obligatorio.');
          input?.focus();
          return;
        }

        const scrollTop = getDetailContainer()?.scrollTop || 0;
        if (input) input.value = texto;
        const formData = new FormData(actionCreateForm);
        actionCreateForm.dataset.submitting = '1';
        setActionSectionPending(section, true);
        renderActionCreateError(section, '');
        postForm(actionCreateForm.getAttribute('action'), formData, actionCreateForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            const nextSection = replaceActionSection(data.section_html, cardId);
            if (!nextSection) throw new Error('No se pudo actualizar la seccion de elementos de accion.');
            syncActionSummary(cardId, data.resumen);
            const container = getDetailContainer();
            if (container) container.scrollTop = scrollTop;
            nextSection.querySelector('[data-operacion-action-create-form="1"] input[name="texto"]')?.focus();
          })
          .catch((error) => {
            console.error('No se pudo crear el elemento de accion:', error);
            renderActionCreateError(
              getActiveActionSection(cardId) || section,
              error?.errors?.texto?.[0]?.message || error?.error || 'No se pudo crear el elemento.'
            );
            (getActiveActionSection(cardId) || section)
              ?.querySelector('[data-operacion-action-create-form="1"] input[name="texto"]')
              ?.focus();
          })
          .finally(() => {
            delete actionCreateForm.dataset.submitting;
            setActionSectionPending(getActiveActionSection(cardId) || section, false);
          });
        return;
      }

      const actionEditForm = e.target.closest('[data-operacion-action-edit-form="1"]');
      if (actionEditForm) {
        e.preventDefault();
        const item = actionEditForm.closest('[data-operacion-action-item="1"]');
        const section = actionEditForm.closest('[data-operacion-action-section="1"]');
        const cardId = section?.dataset.operacionId || detailState.id;
        const input = actionEditForm.querySelector('[data-operacion-action-edit-input="1"]');
        if (!item || !section || !cardId || actionEditForm.dataset.submitting === '1') return;

        const nextValue = (input?.value || '').trim();
        if (!nextValue) {
          renderActionItemError(item, 'Escribe un elemento de accion.');
          input?.focus();
          return;
        }

        actionEditForm.dataset.submitting = '1';
        setActionItemPending(item, true);
        renderActionItemError(item, '');
        postForm(actionEditForm.getAttribute('action'), new FormData(actionEditForm), actionEditForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            const wrapper = document.createElement('div');
            wrapper.innerHTML = data.item_html || '';
            const nextItem = wrapper.querySelector('[data-operacion-action-item="1"]');
            if (!nextItem) throw new Error('No se pudo actualizar el elemento.');
            item.replaceWith(nextItem);
            syncActionSummary(cardId, data.resumen);
          })
          .catch((error) => {
            console.error('No se pudo editar el elemento de accion:', error);
            renderActionItemError(item, error?.errors?.texto?.[0]?.message || 'No se pudo guardar el cambio.');
            input?.focus();
          })
          .finally(() => {
            delete actionEditForm.dataset.submitting;
            setActionItemPending(item, false);
          });
        return;
      }

      const actionDeleteForm = e.target.closest('[data-operacion-action-delete-form="1"]');
      if (actionDeleteForm) {
        e.preventDefault();
        const section = actionDeleteForm.closest('[data-operacion-action-section="1"]');
        const cardId = section?.dataset.operacionId || detailState.id;
        if (!section || !cardId || actionDeleteForm.dataset.submitting === '1') return;

        actionDeleteForm.dataset.submitting = '1';
        setActionSectionPending(section, true);
        postForm(actionDeleteForm.getAttribute('action'), new FormData(actionDeleteForm), actionDeleteForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            const nextSection = replaceActionSection(data.section_html, cardId);
            if (!nextSection) throw new Error('No se pudo actualizar la seccion de elementos de accion.');
            syncActionSummary(cardId, data.resumen);
          })
          .catch((error) => {
            console.error('No se pudo eliminar el elemento de accion:', error);
          })
          .finally(() => {
            delete actionDeleteForm.dataset.submitting;
            setActionSectionPending(getActiveActionSection(cardId) || section, false);
          });
        return;
      }

      const tagForm = e.target.closest('[data-operacion-tag-assign-form="1"], [data-operacion-tag-create-form="1"], [data-operacion-tag-remove-form="1"]');
      if (tagForm) {
        e.preventDefault();
        e.stopPropagation();
        const isRemove = tagForm.matches('[data-operacion-tag-remove-form="1"]');
        const isCreate = tagForm.matches('[data-operacion-tag-create-form="1"]');
        if (isRemove && !window.confirm('Quitar esta etiqueta de la operacion?')) return;

        const section = tagForm.closest('[data-operacion-tags-section="1"]');
        const cardId = tagForm.dataset.operacionId || detailState.id;
        if (!section || !cardId || detailState.pending || section.dataset.pending === '1' || tagForm.dataset.submitting === '1') return;

        const tagSelect = tagForm.querySelector('select[name="etiqueta"]');
        if (!isRemove && !isCreate && !tagSelect?.value) return;
        const scrollTop = getDetailContainer()?.scrollTop || 0;
        const fd = new FormData(tagForm);
        tagForm.dataset.submitting = '1';
        setTagsPending(section, true);
        postForm(tagForm.getAttribute('action'), fd, tagForm)
          .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) throw data;
            return data;
          })
          .then((data) => {
            const isActiveDetail = Boolean(getActiveTagsSection(cardId));
            const nextSection = replaceTagsSection(data.tags_html, cardId);
            if (isActiveDetail && !nextSection) {
              throw new Error('No se pudo actualizar la seccion de etiquetas.');
            }
            syncTagsUI(cardId, data.tags);
            if (!nextSection) return;
            const container = getDetailContainer();
            if (container) container.scrollTop = scrollTop;
            focusTagsForm(nextSection, isCreate);
          })
          .catch((error) => {
            console.error('No se pudo actualizar la seccion de etiquetas:', error);
            const nextSection = error?.tags_html && replaceTagsSection(error.tags_html, cardId);
            if (nextSection) {
              syncTagsUI(cardId, error.tags);
              focusTagsForm(nextSection, isCreate);
              return;
            }
            renderTagsError(section, 'No se pudo actualizar la seccion de etiquetas. Intenta nuevamente.');
          })
          .finally(() => {
            delete tagForm.dataset.submitting;
            setTagsPending(section, false);
          });
        return;
      }

      const commentForm = e.target.closest('[data-operacion-comentario-form="1"]');
      if (!commentForm) return;

      e.preventDefault();
      e.stopPropagation();
      submitCommentForm(commentForm);
    });

    const rootObserver = new MutationObserver(() => {
      if (!root.isConnected) {
        invalidateColumnLoads();
        rootObserver.disconnect();
      }
    });
    rootObserver.observe(document.documentElement, {childList: true, subtree: true});

    syncCopyActions();
    syncInlineCreateAccess();
    initSortable();
  })();
