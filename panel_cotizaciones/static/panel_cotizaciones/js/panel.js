  (function () {
    const root = document.getElementById('panelCotizacionesBoard');
    const configElement = document.getElementById('panel-cotizaciones-config');
    if (!root || !configElement || root.dataset.panelJsInitialized === '1') return;

    let config;
    try {
      config = JSON.parse(configElement.textContent);
    } catch (_) {
      return;
    }
    if (!config?.estadoUpdateUrl || !config?.boardUrl || !config?.inlineCreateUrl || !config?.inlineFormUrl) return;
    root.dataset.panelJsInitialized = '1';

    const updateUrl = config.estadoUpdateUrl;
    const boardUrl = config.boardUrl;
    const inlineCreateUrl = config.inlineCreateUrl;
    const inlineFormUrl = config.inlineFormUrl;
    const columnCreateUrl = config.columnCreateUrl || '';
    const columnReorderUrl = config.columnReorderUrl || '';

    const modalElement = document.getElementById('panelCotizacionDetalleModal');
    const modalContent = document.getElementById('panelCotizacionDetalleModalContent');
    const modalInstance = modalElement && window.bootstrap ? new bootstrap.Modal(modalElement) : null;
    const drawerElement = document.getElementById('panelCotizacionDrawer');
    const drawerContent = document.getElementById('panelCotizacionDrawerContent');
    const drawerInstance = drawerElement && window.bootstrap ? new bootstrap.Offcanvas(drawerElement) : null;
    const confirmModalElement = document.getElementById('panelCotizacionEliminarConfirmModal');
    const confirmModalInstance = confirmModalElement && window.bootstrap ? new bootstrap.Modal(confirmModalElement) : null;
    const columnCreateModalElement = document.getElementById('panelCotizacionColumnaCrearModal');
    const columnCreateModalInstance = columnCreateModalElement && window.bootstrap ? new bootstrap.Modal(columnCreateModalElement) : null;
    const columnEditModalElement = document.getElementById('panelCotizacionColumnaEditarModal');
    const columnEditModalInstance = columnEditModalElement && window.bootstrap ? new bootstrap.Modal(columnEditModalElement) : null;
    const columnDeleteModalElement = document.getElementById('panelCotizacionColumnaEliminarModal');
    const columnDeleteModalInstance = columnDeleteModalElement && window.bootstrap ? new bootstrap.Modal(columnDeleteModalElement) : null;
    let panelCotizacionDeleteUrl = null;
    const pendingCardIds = new Set();
    let currentDetailUrl = '';
    const inlineSharedSlot = document.querySelector('[data-panel-cotizacion-inline-shared-slot="1"]');
    const inlineSlotHome = document.querySelector('[data-panel-cotizacion-inline-slot-home="1"]');
    let inlineFormLoadPromise = null;
    let inlineFormLoaded = false;
    let latestInlineTarget = null;
    const inlineEditorRequests = new Map();
    const columnLoadRequests = new Map();
    let activeInlineEditorSlot = null;
    let inlineEditorVersion = 0;
    let boardVersion = 0;
    let boardRefreshController = null;
    let columnSortable = null;
    let lastColumnOrder = [];
    const clipboardStorageKey = 'panel_cotizaciones_clipboard';

    function getColumnsContainer() {
      return document.querySelector('[data-panel-cotizacion-columns="1"]');
    }

    function getColumnCodeFromElement(element) {
      return element?.dataset.columnaCodigo || element?.dataset.estado || '';
    }

    function getColumnIdFromElement(element) {
      return element?.dataset.columnaId || '';
    }

    function getColumnNameFromElement(element) {
      return element?.dataset.columnaNombre || '';
    }

    function getColumnNameByCode(code) {
      if (!code) return '';
      const body = document.querySelector(`.panel-cotizaciones-col[data-columna-codigo="${code}"]`);
      if (body) {
        return getColumnNameFromElement(body);
      }
      const shell = document.querySelector(`[data-panel-cotizacion-column="1"][data-columna-codigo="${code}"]`);
      return getColumnNameFromElement(shell) || code;
    }

    function getCurrentColumnOrder() {
      return Array.from(
        document.querySelectorAll('[data-panel-cotizacion-column-item="1"] [data-panel-cotizacion-column="1"]')
      )
        .map((shell) => getColumnIdFromElement(shell))
        .filter(Boolean);
    }

    function readClipboard() {
      try {
        const raw = window.sessionStorage.getItem(clipboardStorageKey);
        if (!raw) return null;
        const data = JSON.parse(raw);
        if (
          !data ||
          data.modulo !== 'panel_cotizaciones' ||
          !Number.isInteger(Number(data.tarjeta_id)) ||
          Number(data.tarjeta_id) <= 0
        ) {
          return null;
        }
        return {
          modulo: 'panel_cotizaciones',
          tarjeta_id: String(data.tarjeta_id),
        };
      } catch (_) {
        return null;
      }
    }

    function writeClipboard(cardId) {
      window.sessionStorage.setItem(
        clipboardStorageKey,
        JSON.stringify({
          modulo: 'panel_cotizaciones',
          tarjeta_id: Number(cardId),
        })
      );
    }

    function clearClipboard() {
      window.sessionStorage.removeItem(clipboardStorageKey);
    }

    function syncPasteActions() {
      const clipboard = readClipboard();
      const canPaste = Boolean(clipboard?.tarjeta_id);
      document.querySelectorAll('[data-panel-cotizacion-column-paste="1"]').forEach((button) => {
        button.disabled = !canPaste;
      });
      document.querySelectorAll('[data-panel-cotizacion-copy-clear="1"]').forEach((button) => {
        button.disabled = !canPaste;
      });
    }

    function createCardFromHtml(html) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html || '';
      return wrapper.querySelector('[data-panel-cotizacion-card="1"]');
    }

    function pasteCardIntoColumn(shell) {
      const clipboard = readClipboard();
      const targetColumn = shell?.querySelector('.panel-cotizaciones-col');
      const pasteUrl = shell?.dataset.pasteUrl || '';
      if (!clipboard || !targetColumn || !pasteUrl) {
        showInlineNotification('No hay una tarjeta valida copiada para pegar.', 'warning');
        syncPasteActions();
        return Promise.resolve();
      }

      const fd = new FormData();
      fd.set('tarjeta_id', clipboard.tarjeta_id);
      return postForm(pasteUrl, fd, shell)
        .then((response) => readJsonResponse(response).then((data) => ({response, data})))
        .then(({response, data}) => {
          if (!response.ok || !data.ok) {
            const error = new Error(data.error || `Error ${response.status}`);
            error.data = data;
            error.status = response.status;
            throw error;
          }
          const card = createCardFromHtml(data.html);
          if (!card) {
            throw new Error('No se recibio una tarjeta valida.');
          }
          targetColumn.querySelector('.panel-cotizacion-empty')?.remove();
          targetColumn.prepend(card);
          syncColumnState(targetColumn, data.column_count);
          showInlineNotification('Tarjeta pegada correctamente.', 'success');
          return data;
        })
        .catch((error) => {
          showInlineNotification(
            error?.data?.error || error?.message || 'No se pudo pegar la tarjeta.',
            'danger'
          );
          throw error;
        });
    }

    function syncDeleteDestinationOptions(columnId) {
      const select = columnDeleteModalElement?.querySelector('[name="columna_destino_id"]');
      if (!select) return;
      const options = ['<option value="">Selecciona una columna</option>'];
      document.querySelectorAll('[data-panel-cotizacion-column="1"]').forEach((shell) => {
        const currentId = getColumnIdFromElement(shell);
        if (!currentId) return;
        const disabled = Boolean(columnId) && currentId === String(columnId);
        options.push(
          `<option value="${currentId}"${disabled ? ' disabled' : ''}>${getColumnNameFromElement(shell)}</option>`
        );
      });
      select.innerHTML = options.join('');
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

    function readJsonResponse(response) {
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        const error = new Error(
          response.status === 403
            ? 'Tu sesion o el token CSRF no son validos. Recarga la pagina e intenta nuevamente.'
            : 'Respuesta inesperada del servidor.'
        );
        error.status = response.status;
        throw error;
      }
      return response.json().catch(() => {
        const error = new Error('La respuesta JSON no es valida.');
        error.status = response.status;
        throw error;
      });
    }

    function getHtml(url, options = {}) {
      return fetch(url, {
        ...options,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          ...(options.headers || {}),
        },
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Error ${response.status}`);
          }
          return response.text();
        });
    }

    function ensureEmptyState(column) {
      const cards = column.querySelectorAll('[data-panel-cotizacion-card="1"]');
      let empty = column.querySelector('.panel-cotizacion-empty');
      if (!cards.length && !empty) {
        empty = document.createElement('div');
        empty.className = 'panel-cotizacion-empty';
        empty.textContent = 'Sin cotizaciones.';
        column.appendChild(empty);
      }
      if (cards.length && empty) empty.remove();
    }

    function getColumnShell(column) {
      return column?.closest('[data-panel-cotizacion-column="1"]') || null;
    }

    function getColumnTotal(column) {
      const value = Number.parseInt(getColumnShell(column)?.dataset.total || '0', 10);
      return Number.isInteger(value) && value >= 0 ? value : 0;
    }

    function syncColumnState(column, totalValue) {
      if (!column) return;
      const shell = getColumnShell(column);
      if (!shell) return;
      if (Number.isInteger(totalValue) && totalValue >= 0) {
        shell.dataset.total = String(totalValue);
      }
      const total = getColumnTotal(column);
      const loaded = column.querySelectorAll('[data-panel-cotizacion-card="1"]').length;

    function getHtml(url, options = {}) {
      return fetch(url, {
        ...options,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          ...(options.headers || {}),
        },
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Error ${response.status}`);
          }
          return response.text();
        });
    }

    function ensureEmptyState(column) {
      const cards = column.querySelectorAll('[data-panel-cotizacion-card="1"]');
      let empty = column.querySelector('.panel-cotizacion-empty');
      if (!cards.length && !empty) {
        empty = document.createElement('div');
        empty.className = 'panel-cotizacion-empty';
        empty.textContent = 'Sin cotizaciones.';
        column.appendChild(empty);
      }
      if (cards.length && empty) empty.remove();
    }

    function getColumnShell(column) {
      return column?.closest('[data-panel-cotizacion-column="1"]') || null;
    }

    function getColumnTotal(column) {
      const value = Number.parseInt(getColumnShell(column)?.dataset.total || '0', 10);
      return Number.isInteger(value) && value >= 0 ? value : 0;
    }

    function syncColumnState(column, totalValue) {
      if (!column) return;
      const shell = getColumnShell(column);
      if (!shell) return;
      if (Number.isInteger(totalValue) && totalValue >= 0) {
        shell.dataset.total = String(totalValue);
      }
      const total = getColumnTotal(column);
      const loaded = column.querySelectorAll('[data-panel-cotizacion-card="1"]').length;
      shell.dataset.loaded = String(loaded);
      const countNode = shell.querySelector('[data-panel-cotizacion-column-count="1"]');
      if (countNode) {
        countNode.textContent = String(total);
      }
      ensureEmptyState(column);
    }

    function adjustColumnTotal(column, delta) {
      if (!column) return;
      syncColumnState(column, Math.max(0, getColumnTotal(column) + delta));
    }

    function getEstadoLabel(value) {
      return getColumnNameByCode(value) || value || '';
    }

    function syncCardStateUI(card, estado, estadoLabel) {
      if (!card) return;
      card.dataset.panelCotizacionState = estado;
      const select = card.querySelector('[data-panel-cotizacion-state-select="1"]');
      const badge = card.querySelector('[data-panel-cotizacion-state-badge="1"]');
      if (select) {
        select.value = estado;
      }
      if (badge) {
        badge.textContent = estadoLabel || getEstadoLabel(estado);
      }
      card.querySelectorAll('.kanban-status-control__option[data-status-option]').forEach((button) => {
        const isActive = button.dataset.statusOption === estado;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      });
    }

    function updateCardCommentCount(cardId, count) {
      const card = document.querySelector(`[data-panel-cotizacion-id="${cardId}"]`);
      const countNode = card?.querySelector('[data-panel-cotizacion-comentarios-count="1"]');
      if (countNode) {
        countNode.textContent = String(count);
      }
    }

    function getCardId(card) {
      return card?.getAttribute('data-panel-cotizacion-id') || '';
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
        card.dataset.pending = '1';
      } else {
        pendingCardIds.delete(cardId);
        delete card.dataset.pending;
      }

      const stateSelect = card.querySelector('[data-panel-cotizacion-state-select="1"]');
      if (stateSelect) {
        stateSelect.disabled = isPending;
      }
    }

    function moveCardToColumn(card, targetColumn) {
      if (!card || !targetColumn) return;
      const emptyState = targetColumn.querySelector('.panel-cotizacion-empty');
      if (emptyState) emptyState.remove();
      targetColumn.prepend(card);
      syncColumnState(targetColumn);
    }

    function getStateChangeErrorMessage(error) {
      const serverMessage = error?.data?.error || error?.data?.detail || error?.data?.message;
      if (serverMessage) return serverMessage;
      if (error?.message && !/^Error \d+$/.test(error.message)) return error.message;
      if (error?.status === 400) return 'Revisa los datos enviados e intenta de nuevo.';
      if (error?.status === 403) return 'Tu sesion o el token CSRF no son validos. Recarga la pagina e intenta nuevamente.';
      return 'No se pudo actualizar el estado.';
    }

    function persistCardState(card, sourceColumn, targetColumn, nuevoEstado, previousSelectValue, triggerElement = card) {
      if (!card || isCardPending(card)) {
        return Promise.reject(new Error('La tarjeta ya se esta actualizando'));
      }

      setCardPending(card, true);
      const fd = new FormData();
      fd.set('cotizacion_id', getCardId(card));
      fd.set('nuevo_estado', nuevoEstado);

      return postForm(updateUrl, fd, triggerElement?.closest('form') || triggerElement || card)
        .then((response) => {
          return readJsonResponse(response).then((data) => {
            if (!response.ok) {
              const error = new Error(`Error ${response.status}`);
              error.status = response.status;
              error.data = data;
              throw error;
            }
            return data;
          });
        })
        .then((data) => {
          if (data.status !== 'ok') {
            const error = new Error(data.error || 'Estado no actualizado');
            error.data = data;
            throw error;
          }

          syncCardStateUI(card, data.estado || nuevoEstado, data.estado_display);
          if (sourceColumn && targetColumn && sourceColumn !== targetColumn) {
            adjustColumnTotal(sourceColumn, -1);
            adjustColumnTotal(targetColumn, 1);
          } else if (targetColumn) {
            syncColumnState(targetColumn);
          }
          return data;
        })
        .catch((error) => {
          if (sourceColumn && targetColumn && sourceColumn !== targetColumn) {
            sourceColumn.prepend(card);
            syncColumnState(sourceColumn);
            syncColumnState(targetColumn);
          }
          syncCardStateUI(card, previousSelectValue, getEstadoLabel(previousSelectValue));
          throw error;
        })
        .finally(() => {
          setCardPending(card, false);
        });
    }

    function setInlineCreateButtonsDisabled(disabled) {
      document.querySelectorAll('[data-panel-cotizacion-inline-open="1"]').forEach((button) => {
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
      if (!root) return;
      if (window.initGarantiaSelects) {
        root.querySelectorAll('select').forEach((select) => {
          if (select.tomselect) return;
        });
        window.initGarantiaSelects(root);
      }
      initPanelCotizacionTagSelects(root);
    }

    function initPanelCotizacionTagSelects(root) {
      const scope = root || document;
      if (typeof TomSelect === 'undefined') return;
      scope.querySelectorAll('[data-panel-cotizacion-tags-select="1"]').forEach((select) => {
        if (select.tomselect) return;
        new TomSelect(select, {
          plugins: ['remove_button'],
          create: true,
          maxOptions: 200,
          persist: false,
          closeAfterSelect: false,
          hidePlaceholder: true,
          placeholder: 'Buscar o crear etiqueta...',
          searchField: ['text'],
        });
      });
    }

    function inlineTargetFromButton(button) {
      const column = button?.closest('.panel-cotizacion-column');
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
        document.querySelectorAll('[data-panel-cotizacion-inline-open="1"]')
      ).find((item) => item.dataset.estado === estado);
      return inlineTargetFromButton(button);
    }

    function moveInlineSlot(target) {
      if (!inlineSharedSlot || !target?.column) return;
      const actions = target.column.querySelector('.panel-cotizacion-column__actions');
      if (actions) actions.after(inlineSharedSlot);
    }

    function configureInlineSlot(target) {
      if (!inlineSharedSlot || !target) return;
      moveInlineSlot(target);
      inlineSharedSlot.dataset.estado = target.estado;
      const form = inlineSharedSlot.querySelector('[data-panel-cotizacion-inline-form="1"]');
      const estadoInput = form?.querySelector('[name="estado"]');
      const destination = inlineSharedSlot.querySelector('[data-panel-cotizacion-inline-destination="1"]');
      if (form) form.dataset.estado = target.estado;
      if (estadoInput) estadoInput.value = target.estado;
      if (destination) destination.textContent = target.label;
      inlineSharedSlot.classList.remove('d-none');
    }

    function showInlineLoading(target) {
      if (!inlineSharedSlot || !target) return;
      moveInlineSlot(target);
      inlineSharedSlot.classList.remove('d-none');
      inlineSharedSlot.innerHTML = '<div class="text-muted small py-2" data-panel-cotizacion-inline-loading="1">Cargando formulario...</div>';
    }

    function parseInlineFragment(html) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const fragments = wrapper.querySelectorAll('[data-panel-cotizacion-inline-form-fragment="1"]');
      const forms = wrapper.querySelectorAll('[data-panel-cotizacion-inline-form="1"]');
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
            throw new Error(`Error ${response.status}`);
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
            inlineSharedSlot.innerHTML = '<div class="alert alert-danger py-2 px-3 small mb-0" data-panel-cotizacion-inline-load-error="1">No se pudo cargar el formulario. Intenta de nuevo.</div>';
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

    function ensureInlineLinkRows(root) {
      const rows = root?.querySelector('[data-panel-cotizacion-link-rows="1"]');
      const template = root?.querySelector('[data-panel-cotizacion-link-template="1"]');
      if (!rows || !template || rows.querySelector('[data-panel-cotizacion-link-row="1"]')) return;
      rows.insertAdjacentHTML('beforeend', template.innerHTML.trim());
    }

    function resetInlineCreateForm(form) {
      if (!form) return;
      destroyInlineCreateSelects(form);
      form.reset();
      const rows = form.querySelector('[data-panel-cotizacion-link-rows="1"]');
      const template = form.querySelector('[data-panel-cotizacion-link-template="1"]');
      if (rows && template) {
        rows.innerHTML = template.innerHTML.trim();
      }
      form.querySelectorAll('.text-danger.small.mt-1').forEach((node) => {
        if (node.closest('[data-panel-cotizacion-link-row="1"]')) return;
      });
      initInlineCreateSelects(form);
    }

    function showInlineNotification(message, tone = 'success') {
      const alert = document.createElement('div');
      alert.className = `alert alert-${tone} alert-dismissible fade show panel-cotizacion-inline-notice`;
      alert.setAttribute('role', 'alert');
      alert.innerHTML = (
        `<span>${message}</span>` +
        '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button>'
      );
      document.body.appendChild(alert);
      window.setTimeout(() => {
        alert.classList.remove('show');
        window.setTimeout(() => alert.remove(), 150);
      }, 2600);
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

    function loadInlineEditor(card, fieldName) {
      const cardId = getCardId(card);
      const endpoint = card?.dataset.panelCotizacionEditorUrl;
      if (!cardId || !endpoint) return Promise.reject(new Error('Editor no disponible.'));
      const existing = inlineEditorRequests.get(cardId);
      if (existing) {
        if (existing.fieldName === fieldName) return existing.promise;
        existing.controller.abort();
      }

      const url = new URL(endpoint, window.location.origin);
      url.searchParams.set('field', fieldName);
      const controller = new AbortController();
      const request = fetch(`${url.pathname}${url.search}`, {
        credentials: 'same-origin',
        signal: controller.signal,
        headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
      }).then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok || String(data.id) !== String(cardId) || data.field !== fieldName || !data.html) {
          throw new Error(data.error || `Error ${response.status}`);
        }
        return data.html;
      }).finally(() => {
        if (inlineEditorRequests.get(cardId)?.promise === request) {
          inlineEditorRequests.delete(cardId);
        }
      });
      inlineEditorRequests.set(cardId, {fieldName, promise: request, controller});
      return request;
    }

    function restoreInlineSlot(slot) {
      if (!slot || typeof slot.dataset.previousHtml === 'undefined') return;
      slot.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
      slot.innerHTML = slot.dataset.previousHtml;
      delete slot.dataset.previousHtml;
      if (activeInlineEditorSlot === slot) activeInlineEditorSlot = null;
    }

    function showInlineEditorLoadError(slot) {
      restoreInlineSlot(slot);
      slot?.insertAdjacentHTML('beforeend', '<div class="text-danger small mt-1" data-panel-cotizacion-inline-load-error="1">No se pudo cargar el editor. Intenta nuevamente.</div>');
    }

    function openInlineEditor(slot, fieldName, card) {
      const selectedIdsSnapshot = slot.querySelector('[data-selected-ids]')?.dataset.selectedIds || '';
      if (activeInlineEditorSlot && activeInlineEditorSlot !== slot) restoreInlineSlot(activeInlineEditorSlot);
      slot.querySelector('[data-panel-cotizacion-inline-load-error="1"]')?.remove();
      slot.dataset.previousHtml = slot.innerHTML;
      activeInlineEditorSlot = slot;
      const version = ++inlineEditorVersion;
      slot.innerHTML = '<div class="text-muted small py-2" data-panel-cotizacion-inline-editor-loading="1">Cargando editor...</div>';

      return loadInlineEditor(card, fieldName).then((editorHtml) => {
        if (version !== inlineEditorVersion || activeInlineEditorSlot !== slot || !slot.isConnected) return null;
        slot.innerHTML = editorHtml;
        const form = slot.querySelector('[data-panel-cotizacion-inline-editor="1"]');
        if (!form || String(form.dataset.panelCotizacionEditorId) !== String(getCardId(card)) || form.dataset.field !== fieldName) {
          throw new Error('Editor inesperado.');
        }
        const firstInput = form.querySelector('input:not([type="hidden"]), select, textarea');
        if (fieldName === 'cliente') {
          const currentText = card.querySelector('[data-panel-cotizacion-inline-slot="cliente"] .panel-cotizacion-card__client')?.textContent?.trim() || '';
          const select = form.querySelector('[name="cliente"]');
          const option = select && Array.from(select.options).find((item) => item.text.trim() === currentText);
          if (option) select.value = option.value;
        } else if (fieldName === 'asignados') {
          const select = form.querySelector('[name="asignados"]');
          const selectedIds = selectedIdsSnapshot.split(',').map((value) => value.trim()).filter(Boolean);
          if (select) Array.from(select.options).forEach((option) => { option.selected = selectedIds.includes(option.value); });
          window.initGarantiaSelects?.(form);
        } else if (fieldName === 'titulo') {
          const currentTitle = card.querySelector('[data-panel-cotizacion-inline-slot="titulo"] .panel-cotizacion-card__title')?.textContent?.trim() || '';
          if (firstInput instanceof HTMLInputElement && !firstInput.value && currentTitle) {
            firstInput.value = currentTitle;
          }
        }
        firstInput?.focus();
        if (fieldName === 'titulo') firstInput?.select();
        return form;
      }).catch((error) => {
        if (version !== inlineEditorVersion || activeInlineEditorSlot !== slot) return null;
        console.error('No se pudo cargar el editor inline:', error);
        showInlineEditorLoadError(slot);
        return null;
      });
    }

    function getSelectedUserIds() {
      const select = document.getElementById('panelCotizacionesUserFilter');
      return select
        ? Array.from(select.selectedOptions)
          .map((option) => option.value)
          .filter(Boolean)
        : [];
    }

    function getLoadedCardIds(column) {
      return Array.from(
        column?.querySelectorAll('[data-panel-cotizacion-card="1"]') || []
      ).map((card) => getCardId(card)).filter(Boolean);
    }

    function initSortables() {
      if (typeof Sortable === 'undefined') return;
      const columnsContainer = getColumnsContainer();
      if (columnsContainer && columnsContainer.dataset.sortableReady !== '1' && columnReorderUrl) {
        columnsContainer.dataset.sortableReady = '1';
        lastColumnOrder = getCurrentColumnOrder();
        columnSortable = Sortable.create(columnsContainer, {
          animation: 150,
          direction: 'horizontal',
          draggable: '[data-panel-cotizacion-column-item="1"]',
          handle: '.panel-cotizacion-column__header',
          ghostClass: 'panel-cotizacion-ghost',
          dragClass: 'panel-cotizacion-drag',
          chosenClass: 'panel-cotizacion-chosen',
          onStart: function () {
            lastColumnOrder = getCurrentColumnOrder();
          },
          onEnd: function () {
            const nextOrder = getCurrentColumnOrder();
            if (!nextOrder.length || nextOrder.join(',') === lastColumnOrder.join(',')) {
              return;
            }
            const fd = new FormData();
            nextOrder.forEach((columnId) => fd.append('columnas[]', columnId));
            postForm(columnReorderUrl, fd, columnsContainer)
              .then((response) => readJsonResponse(response).then((data) => ({response, data})))
              .then(({response, data}) => {
                if (!response.ok || !data.ok) {
                  throw new Error(data.error || `Error ${response.status}`);
                }
                lastColumnOrder = nextOrder;
              })
              .catch((error) => {
                console.error('No se pudo reordenar las columnas:', error);
                refreshBoard();
              });
          },
        });
      }
      document.querySelectorAll('.panel-cotizaciones-col').forEach((column) => {
        if (column.dataset.sortableReady === '1') return;
        column.dataset.sortableReady = '1';
        Sortable.create(column, {
          group: 'panel-cotizaciones-kanban',
          animation: 150,
          ghostClass: 'panel-cotizacion-ghost',
          dragClass: 'panel-cotizacion-drag',
          chosenClass: 'panel-cotizacion-chosen',
          onMove: function (evt) {
            if (isCardPending(evt.dragged)) {
              return false;
            }
            return true;
          },
          onEnd: function (evt) {
            const card = evt.item;
            const target = evt.to;
            const source = evt.from;
            const id = card.getAttribute('data-panel-cotizacion-id');
            const nuevoEstado = getColumnCodeFromElement(target);
            if (!id || !nuevoEstado || source === target || isCardPending(card)) {
              ensureEmptyState(source);
              ensureEmptyState(target);
              if (isCardPending(card) && source !== target) {
                source.prepend(card);
              }
              return;
            }

            const previousState = getColumnCodeFromElement(source);

            persistCardState(card, source, target, nuevoEstado, previousState, card)
              .catch((error) => {
                console.error('No se pudo mover la cotizacion:', error);
              })
              .finally(() => {
                ensureEmptyState(source);
                ensureEmptyState(target);
              });
          },
        });
        syncColumnState(column);
      });
    }

    function initPanelCotizacionModalContent(container) {
      if (!container) return;
      if (window.initGarantiaSelects) {
        window.initGarantiaSelects(container);
      }
      initPanelCotizacionTagSelects(container);
    }

    function loadModal(url) {
      if (!modalContent || !modalInstance) return;
      modalContent.innerHTML = '<div class="modal-body p-4 text-center text-muted">Cargando...</div>';
      modalInstance.show();
      getHtml(url)
        .then((html) => {
          modalContent.innerHTML = html;
          initPanelCotizacionModalContent(modalContent);
        })
        .catch((error) => {
          console.error('No se pudo cargar la cotizacion:', error);
          modalContent.innerHTML = '<div class="modal-body p-4 text-center text-danger">No se pudo cargar la cotizacion.</div>';
        });
    }

    function loadDrawer(url) {
      if (!drawerContent || !drawerInstance) return;
      const detailUrl = url.includes('?') ? `${url}&layout=drawer` : `${url}?layout=drawer`;
      currentDetailUrl = detailUrl;
      drawerContent.innerHTML = '<div class="offcanvas-body p-4 text-center text-muted">Cargando...</div>';
      drawerInstance.show();
      getHtml(detailUrl)
        .then((html) => {
          drawerContent.innerHTML = html;
          initPanelCotizacionModalContent(drawerContent);
        })
        .catch((error) => {
          console.error('No se pudo cargar el detalle de la cotizacion:', error);
          drawerContent.innerHTML = '<div class="offcanvas-body p-4 text-center text-danger">No se pudo cargar el detalle.</div>';
        });
    }

    function replaceDrawerSection(selector, html) {
      const detailRoot = drawerContent || modalContent;
      if (!detailRoot) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.firstElementChild;
      const currentSection = detailRoot.querySelector(selector);
      if (nextSection && currentSection) {
        currentSection.replaceWith(nextSection);
      }
    }

    function showDeleteConfirm(url) {
      panelCotizacionDeleteUrl = url;
      if (confirmModalInstance) {
        confirmModalInstance.show();
      }
    }

    function performDelete() {
      if (!panelCotizacionDeleteUrl) return;
      const token = window.getCSRFToken();
      if (!token) return;
      fetch(panelCotizacionDeleteUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': token,
          'X-Requested-With': 'XMLHttpRequest',
        },
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Error ${response.status}`);
          }
          return response.json();
        })
        .then((data) => {
          if (data.status === 'ok') {
            if (drawerInstance && drawerElement?.classList.contains('show')) {
              drawerInstance.hide();
            }
            if (modalInstance && modalElement?.classList.contains('show')) {
              modalInstance.hide();
            }
            refreshBoard();
          }
        })
        .catch((error) => {
          console.error('No se pudo eliminar la cotizacion:', error);
          if (confirmModalInstance) {
            confirmModalInstance.hide();
          }
        });
    }

    function refreshBoard() {
      boardRefreshController?.abort();
      const controller = new AbortController();
      boardRefreshController = controller;
      const selectedUsuarios = getSelectedUserIds();
      const params = new URLSearchParams();
      selectedUsuarios.forEach((usuarioId) => params.append('usuario', usuarioId));
      const url = params.toString() ? `${boardUrl}?${params.toString()}` : boardUrl;
      return getHtml(url, {signal: controller.signal})
        .then((html) => {
          if (controller.signal.aborted) return;
          const board = document.getElementById('panelCotizacionesBoard');
          if (!board) return;
          closeInlineCreateForm();
          board.innerHTML = html;
          initSortables();
          syncPasteActions();
        })
        .catch((error) => {
          if (error.name === 'AbortError') return;
          console.error('No se pudo refrescar el tablero de cotizaciones:', error);
        })
        .finally(() => {
          if (boardRefreshController === controller) {
            boardRefreshController = null;
          }
        });
    }

    function handleCardStateChange(stateSelect, triggerElement = stateSelect) {
      const card = stateSelect?.closest('[data-panel-cotizacion-card="1"]');
      const sourceColumn = card?.closest('.panel-cotizaciones-col');
      const previousState = card?.dataset.panelCotizacionState || sourceColumn?.dataset.estado || stateSelect?.dataset.previousValue || stateSelect?.value;
      const nuevoEstado = stateSelect?.value || '';
      if (!card || !sourceColumn || !stateSelect || !nuevoEstado || previousState === nuevoEstado) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      if (isCardPending(card)) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      const targetColumn = document.querySelector(`.panel-cotizaciones-col[data-estado="${nuevoEstado}"]`);
      if (!targetColumn) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      moveCardToColumn(card, targetColumn);
      persistCardState(card, sourceColumn, targetColumn, nuevoEstado, previousState, triggerElement)
        .catch((error) => {
          console.error('No se pudo actualizar el estado de la cotizacion:', error);
        })
        .finally(() => {
          ensureEmptyState(sourceColumn);
          ensureEmptyState(targetColumn);
        });
    }

    document.addEventListener('change', (e) => {
      if (e.target && e.target.id === 'panelCotizacionesUserFilter') refreshBoard();

      const stateSelect = e.target.closest('[data-panel-cotizacion-state-select="1"]');
      if (!stateSelect) return;
      handleCardStateChange(stateSelect);
    });

    document.addEventListener('click', (e) => {
      const statusButton = e.target.closest('.kanban-status-control__option[data-status-option]');
      if (statusButton) {
        e.preventDefault();
        const control = statusButton.closest('.kanban-status-control');
        const stateSelect = control?.querySelector('[data-panel-cotizacion-state-select="1"]');
        const card = statusButton.closest('[data-panel-cotizacion-card="1"]');
        const previousState = card?.dataset.panelCotizacionState || stateSelect?.value || '';
        const nextState = statusButton.dataset.statusOption || '';
        if (!stateSelect || !nextState) return;
        if (stateSelect.disabled) {
          syncCardStateUI(card, previousState, getEstadoLabel(previousState));
          return;
        }
        stateSelect.dataset.previousValue = previousState;
        stateSelect.value = nextState;
        handleCardStateChange(stateSelect, statusButton);
        return;
      }

      const copyCardButton = e.target.closest('[data-panel-cotizacion-copy="1"]');
      if (copyCardButton) {
        e.preventDefault();
        e.stopPropagation();
        const card = copyCardButton.closest('[data-panel-cotizacion-card="1"]');
        const cardId = getCardId(card);
        if (!cardId) return;
        writeClipboard(cardId);
        syncPasteActions();
        showInlineNotification('Tarjeta copiada. Selecciona una columna para pegarla.', 'success');
        return;
      }

      const pasteCardButton = e.target.closest('[data-panel-cotizacion-column-paste="1"]');
      if (pasteCardButton) {
        e.preventDefault();
        if (pasteCardButton.disabled) return;
        const shell = pasteCardButton.closest('[data-panel-cotizacion-column="1"]');
        pasteCardIntoColumn(shell).catch((error) => {
          console.error('No se pudo pegar la tarjeta:', error);
        });
        return;
      }

      const clearCopyButton = e.target.closest('[data-panel-cotizacion-copy-clear="1"]');
      if (clearCopyButton) {
        e.preventDefault();
        clearClipboard();
        syncPasteActions();
        showInlineNotification('Se limpio la tarjeta copiada.', 'secondary');
        return;
      }

      const columnEditButton = e.target.closest('[data-panel-cotizacion-column-edit-open="1"]');
      if (columnEditButton) {
        e.preventDefault();
        const shell = columnEditButton.closest('[data-panel-cotizacion-column="1"]');
        const form = columnEditModalElement?.querySelector('[data-panel-cotizacion-column-edit-form="1"]');
        if (!shell || !form) return;
        form.dataset.action = shell.dataset.editUrl || '';
        form.querySelector('[name="columna_id"]').value = getColumnIdFromElement(shell);
        form.querySelector('[name="nombre"]').value = getColumnNameFromElement(shell);
        const errorNode = form.querySelector('[data-panel-cotizacion-column-edit-error="1"]');
        if (errorNode) errorNode.textContent = '';
        columnEditModalInstance?.show();
        return;
      }

      const columnDeleteButton = e.target.closest('[data-panel-cotizacion-column-delete-open="1"]');
      if (columnDeleteButton) {
        e.preventDefault();
        const shell = columnDeleteButton.closest('[data-panel-cotizacion-column="1"]');
        const form = columnDeleteModalElement?.querySelector('[data-panel-cotizacion-column-delete-form="1"]');
        if (!shell || !form) return;
        form.dataset.action = shell.dataset.deleteUrl || '';
        form.querySelector('[name="columna_id"]').value = getColumnIdFromElement(shell);
        form.querySelector('[name="columna_destino_id"]').value = '';
        syncDeleteDestinationOptions(getColumnIdFromElement(shell));
        const messageNode = form.querySelector('[data-panel-cotizacion-column-delete-message="1"]');
        if (messageNode) {
          messageNode.textContent = `Si la columna "${getColumnNameFromElement(shell)}" tiene tarjetas, deberas elegir una columna destino.`;
        }
        const errorNode = form.querySelector('[data-panel-cotizacion-column-delete-error="1"]');
        if (errorNode) errorNode.textContent = '';
        columnDeleteModalInstance?.show();
        return;
      }

      const inlineOpenButton = e.target.closest('[data-panel-cotizacion-inline-open="1"]');
      if (inlineOpenButton) {
        e.preventDefault();
        openInlineCreateForm(inlineOpenButton);
        return;
      }

      const inlineCancelButton = e.target.closest('[data-panel-cotizacion-inline-cancel="1"]');
      if (inlineCancelButton) {
        e.preventDefault();
        closeInlineCreateForm();
        return;
      }

      const addLinkButton = e.target.closest('[data-panel-cotizacion-link-add="1"]');
      if (addLinkButton) {
        e.preventDefault();
        const root = addLinkButton.closest('[data-panel-cotizacion-inline-links="1"]');
        const rows = root?.querySelector('[data-panel-cotizacion-link-rows="1"]');
        const template = root?.querySelector('[data-panel-cotizacion-link-template="1"]');
        if (!rows || !template) return;
        rows.insertAdjacentHTML('beforeend', template.innerHTML.trim());
        return;
      }

      const removeLinkButton = e.target.closest('[data-panel-cotizacion-link-remove="1"]');
      if (removeLinkButton) {
        e.preventDefault();
        const row = removeLinkButton.closest('[data-panel-cotizacion-link-row="1"]');
        const root = removeLinkButton.closest('[data-panel-cotizacion-inline-links="1"]');
        row?.remove();
        ensureInlineLinkRows(root);
        return;
      }

      const inlineFieldValue = e.target.closest('[data-panel-cotizacion-inline-field]');
      if (inlineFieldValue) {
        e.preventDefault();
        const card = inlineFieldValue.closest('[data-panel-cotizacion-card="1"]');
        const slot = inlineFieldValue.closest('[data-panel-cotizacion-inline-slot]');
        const fieldName = inlineFieldValue.dataset.panelCotizacionInlineField;
        if (!card || !slot || !fieldName || isCardPending(card)) return;
        if (slot.querySelector('[data-panel-cotizacion-inline-editor="1"]')) return;
        openInlineEditor(slot, fieldName, card);
        return;
      }

      const inlineFieldCancelButton = e.target.closest('[data-panel-cotizacion-inline-field-cancel="1"]');
      if (inlineFieldCancelButton) {
        e.preventDefault();
        const slot = inlineFieldCancelButton.closest('[data-panel-cotizacion-inline-slot]');
        inlineEditorVersion += 1;
        restoreInlineSlot(slot);
        return;
      }

      const closeDrawerButton = e.target.closest('[data-panel-cotizacion-close-drawer="1"]');
      if (closeDrawerButton) {
        e.preventDefault();
        if (drawerInstance) drawerInstance.hide();
        return;
      }

      const deleteArchivoButton = e.target.closest('[data-panel-cotizacion-archivo-delete="1"]');
      if (deleteArchivoButton) {
        e.preventDefault();
        const url = deleteArchivoButton.dataset.deleteUrl;
        const token = window.getCSRFToken();
        if (!token) return;
        fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': token,
            'X-Requested-With': 'XMLHttpRequest',
          },
        })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-archivos-section="1"]', data.html);
            }
          })
          .catch((error) => {
            console.error('No se pudo eliminar el archivo:', error);
          });
        return;
      }

      const deleteEnlaceButton = e.target.closest('[data-panel-cotizacion-enlace-delete="1"]');
      if (deleteEnlaceButton) {
        e.preventDefault();
        const url = deleteEnlaceButton.dataset.deleteUrl;
        const token = window.getCSRFToken();
        if (!token) return;
        fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': token,
            'X-Requested-With': 'XMLHttpRequest',
          },
        })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-enlaces-section="1"]', data.html);
            }
          })
          .catch((error) => {
            console.error('No se pudo eliminar el enlace:', error);
          });
        return;
      }

      const deleteButton = e.target.closest('[data-panel-cotizacion-delete="1"]');
      if (deleteButton) {
        e.preventDefault();
        const url = deleteButton.dataset.deleteUrl;
        if (url) showDeleteConfirm(url);
        return;
      }

      const confirmDeleteButton = e.target.closest('[data-panel-cotizacion-confirm-delete="1"]');
      if (confirmDeleteButton) {
        e.preventDefault();
        performDelete();
        return;
      }


      const link = e.target.closest('[data-panel-cotizacion-modal-open="1"]');
      if (!link) return;
      e.preventDefault();
      const url = link.getAttribute('data-modal-url') || link.getAttribute('href');
      if (!url) return;
      currentDetailUrl = url;
      loadModal(url);
    });

    document.addEventListener('submit', (e) => {
      const columnCreateForm = e.target.closest('[data-panel-cotizacion-column-create-form="1"]');
      if (columnCreateForm) {
        e.preventDefault();
        const errorNode = columnCreateForm.querySelector('[data-panel-cotizacion-column-create-error="1"]');
        if (errorNode) errorNode.textContent = '';
        const fd = new FormData(columnCreateForm);
        postForm(columnCreateUrl, fd, columnCreateForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;
            columnCreateModalInstance?.hide();
            columnCreateForm.reset();
            refreshBoard();
          })
          .catch((error) => {
            if (errorNode) {
              const errors = error?.errors?.nombre || error?.errors?.__all__ || [];
              errorNode.textContent = errors.map((item) => item.message).join(' ') || 'No se pudo crear la columna.';
            }
          });
        return;
      }

      const deleteChecklistButton = e.target.closest('[data-panel-cotizacion-checklist-delete="1"]');
      if (deleteChecklistButton) {
        e.preventDefault();
        const url = deleteChecklistButton.dataset.deleteUrl;
        const token = window.getCSRFToken();
        if (!url || !token) return;
        fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': token,
            'X-Requested-With': 'XMLHttpRequest',
          },
        })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-checklist-section="1"]', data.html);
            }
          })
          .catch((error) => {
            console.error('No se pudo eliminar el elemento de accion:', error);
          });
        return;
      }

      const columnEditForm = e.target.closest('[data-panel-cotizacion-column-edit-form="1"]');
      if (columnEditForm) {
        e.preventDefault();
        const errorNode = columnEditForm.querySelector('[data-panel-cotizacion-column-edit-error="1"]');
        if (errorNode) errorNode.textContent = '';
        const fd = new FormData(columnEditForm);
        postForm(columnEditForm.dataset.action || '', fd, columnEditForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;
            columnEditModalInstance?.hide();
            refreshBoard();
          })
          .catch((error) => {
            if (errorNode) {
              const errors = error?.errors?.nombre || error?.errors?.__all__ || [];
              errorNode.textContent = errors.map((item) => item.message).join(' ') || 'No se pudo actualizar la columna.';
            }
          });
        return;
      }

      const columnDeleteForm = e.target.closest('[data-panel-cotizacion-column-delete-form="1"]');
      if (columnDeleteForm) {
        e.preventDefault();
        const errorNode = columnDeleteForm.querySelector('[data-panel-cotizacion-column-delete-error="1"]');
        if (errorNode) errorNode.textContent = '';
        const fd = new FormData(columnDeleteForm);
        postForm(columnDeleteForm.dataset.action || '', fd, columnDeleteForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;
            columnDeleteModalInstance?.hide();
            refreshBoard();
          })
          .catch((error) => {
            if (errorNode) {
              errorNode.textContent = error?.error || 'No se pudo eliminar la columna.';
            }
          });
        return;
      }

      const inlineEditor = e.target.closest('[data-panel-cotizacion-inline-editor="1"]');
      if (inlineEditor) {
        e.preventDefault();
        const slot = inlineEditor.closest('[data-panel-cotizacion-inline-slot]');
        const card = inlineEditor.closest('[data-panel-cotizacion-card="1"]');
        const fieldName = inlineEditor.dataset.field;
        if (!slot || !card || !fieldName || isCardPending(card)) return;

        const fd = new FormData(inlineEditor);
        setCardPending(card, true);
        postForm(inlineEditor.dataset.updateUrl, fd, inlineEditor)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;
            slot.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
            slot.innerHTML = data.html;
            delete slot.dataset.previousHtml;
            if (activeInlineEditorSlot === slot) activeInlineEditorSlot = null;
            if (fieldName === 'asignados') {
              refreshBoard();
            }
          })
          .catch((error) => {
            if (
              error?.html &&
              String(error.id) === String(getCardId(card)) &&
              error.field === fieldName
            ) {
              slot.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
              slot.innerHTML = error.html;
              const replacement = slot.querySelector('[data-panel-cotizacion-inline-editor="1"]');
              if (fieldName === 'asignados') window.initGarantiaSelects?.(replacement);
              replacement?.querySelector('.is-invalid, input:not([type="hidden"]), select, textarea')?.focus();
              return;
            }
            const errorNode = inlineEditor.querySelector('[data-panel-cotizacion-inline-error="1"]');
            if (error && error.errors && errorNode) {
              const fieldErrors = error.errors[fieldName] || error.errors.__all__ || [];
              errorNode.textContent = fieldErrors.map((item) => item.message).join(' ');
              return;
            }
            restoreInlineSlot(slot);
          })
          .finally(() => {
            setCardPending(card, false);
          });
        return;
      }

      const archivoForm = e.target.closest('[data-panel-cotizacion-archivo-form="1"]');
      if (archivoForm) {
        e.preventDefault();
        const submitButton = archivoForm.querySelector('[data-panel-cotizacion-archivo-submit="1"]');
        const errorNode = archivoForm.querySelector('[data-panel-cotizacion-archivo-error="1"]');
        if (submitButton?.disabled) return;
        if (errorNode) errorNode.textContent = '';
        if (submitButton) submitButton.disabled = true;

        const fd = new FormData(archivoForm);
        postForm(archivoForm.getAttribute('action'), fd, archivoForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-archivos-section="1"]', data.html);
            }
          })
          .catch((error) => {
            if (error?.html) {
              replaceDrawerSection('[data-panel-cotizacion-archivos-section="1"]', error.html);
            } else if (errorNode) {
              const fieldErrors = error?.errors?.archivos || error?.errors?.__all__ || [];
              errorNode.textContent = fieldErrors.map((item) => item.message).join(' ') || 'No se pudieron agregar los archivos.';
            }
          })
          .finally(() => {
            if (submitButton) submitButton.disabled = false;
          });
        return;
      }

      const enlaceForm = e.target.closest('[data-panel-cotizacion-enlace-form="1"]');
      if (enlaceForm) {
        e.preventDefault();
        const submitButton = enlaceForm.querySelector('[data-panel-cotizacion-enlace-submit="1"]');
        const errorNode = enlaceForm.querySelector('[data-panel-cotizacion-enlace-error="1"]');
        if (submitButton?.disabled) return;
        if (errorNode) errorNode.textContent = '';
        if (submitButton) submitButton.disabled = true;

        const fd = new FormData(enlaceForm);
        postForm(enlaceForm.getAttribute('action'), fd, enlaceForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-enlaces-section="1"]', data.html);
            }
          })
          .catch((error) => {
            if (error?.html) {
              replaceDrawerSection('[data-panel-cotizacion-enlaces-section="1"]', error.html);
            } else if (errorNode) {
              const fieldErrors = error?.errors?.url || error?.errors?.titulo || error?.errors?.__all__ || [];
              errorNode.textContent = fieldErrors.map((item) => item.message).join(' ') || 'No se pudo agregar el enlace.';
            }
          })
          .finally(() => {
            if (submitButton) submitButton.disabled = false;
          });
        return;
      }

      const inlineForm = e.target.closest('[data-panel-cotizacion-inline-form="1"]');
      if (inlineForm) {
        e.preventDefault();
        if (inlineForm.dataset.submitting === 'true') return;
        const fd = new FormData(inlineForm);
        const submittedEstado = String(fd.get('estado') || '');
        const submittedTarget = findInlineTarget(submittedEstado);
        const column = submittedTarget?.column.querySelector('.panel-cotizaciones-col');
        if (!submittedTarget || !column) return;
        inlineForm.dataset.submitting = 'true';
        inlineForm.setAttribute('aria-busy', 'true');
        inlineForm.querySelectorAll('button, input, select, textarea').forEach((control) => { control.disabled = true; });
        setInlineCreateButtonsDisabled(true);
        postForm(inlineCreateUrl, fd, inlineForm)
          .then((response) => readInlineCreateResponse(response))
          .then((data) => {
            if (!data.ok) return;
            const activeFilterSelect = document.getElementById('panelCotizacionesUserFilter');
            const hasActiveFilter = activeFilterSelect
              ? Array.from(activeFilterSelect.selectedOptions).some((option) => !!option.value)
              : false;

            if (hasActiveFilter) {
              refreshBoard();
            } else {
              const wrapper = document.createElement('div');
              wrapper.innerHTML = data.card_html || data.html || '';
              const card = wrapper.firstElementChild;
              if (!card) return;

              const emptyState = column.querySelector('.panel-cotizacion-empty');
              if (emptyState) emptyState.remove();
              const duplicateCard = document.querySelector(
                `[data-panel-cotizacion-id="${data.id}"]`
              );
              if (duplicateCard) duplicateCard.remove();
              column.prepend(card);
              syncColumnState(column, data.column_count);
            }

            resetInlineCreateForm(inlineForm);
            closeInlineCreateForm();
            showInlineNotification(
              data.message || 'La cotizacion se creo correctamente.',
              'success'
            );
          })
          .catch((error) => {
            if (error?.data?.html) {
              replaceInlineCreateForm(error.data.html, submittedTarget);
              return;
            }
            console.error('No se pudo crear la cotizacion:', error);
            showInlineNotification(
              error?.data?.errors?.__all__?.[0]?.message || 'No se pudo crear la cotizacion.',
              'danger'
            );
          })
          .finally(() => {
            const activeForm = inlineSharedSlot?.querySelector('[data-panel-cotizacion-inline-form="1"]');
            if (activeForm) {
              delete activeForm.dataset.submitting;
              activeForm.setAttribute('aria-busy', 'false');
              activeForm.querySelectorAll('button, input, select, textarea').forEach((control) => { control.disabled = false; });
            }
            setInlineCreateButtonsDisabled(false);
          });
        return;
      }

      const modalForm = e.target.closest('[data-panel-cotizacion-modal-form="1"]');
      if (modalForm) {
        e.preventDefault();
        const fd = new FormData(modalForm);
        postForm(modalForm.getAttribute('action'), fd, modalForm)
          .then(async (response) => {
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
              const data = await response.json();
              if (!response.ok) {
                throw data;
              }
              return data;
            }
            return { status: 'error', html: await response.text() };
          })
          .then((data) => {
            if ((modalForm.querySelector('[name="layout"]')?.value || '') === 'drawer' && drawerContent) {
              drawerContent.innerHTML = data.html;
              initPanelCotizacionModalContent(drawerContent);
            } else {
              modalContent.innerHTML = data.html;
              initPanelCotizacionModalContent(modalContent);
            }
            if (data.status === 'ok') {
              refreshBoard();
            }
          })
          .catch((error) => {
            console.error('No se pudo guardar la cotizacion:', error);
          });
        return;
      }

      const checklistForm = e.target.closest('[data-panel-cotizacion-checklist-form="1"]');
      if (checklistForm) {
        e.preventDefault();
        const fd = new FormData(checklistForm);
        postForm(checklistForm.getAttribute('action'), fd, checklistForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-checklist-section="1"]', data.html);
            }
          })
          .catch((error) => {
            if (error?.html) {
              replaceDrawerSection('[data-panel-cotizacion-checklist-section="1"]', error.html);
            } else {
              console.error('No se pudo agregar el elemento de accion:', error);
            }
          });
        return;
      }

      const checklistItemForm = e.target.closest('[data-panel-cotizacion-checklist-item-form="1"]');
      if (checklistItemForm) {
        e.preventDefault();
        const input = checklistItemForm.querySelector('[data-panel-cotizacion-checklist-text="1"]');
        const nextValue = (input?.value || '').trim();
        const initialValue = (input?.dataset.initialValue || '').trim();
        if (!input || nextValue === initialValue) return;
        if (!nextValue) {
          input.value = initialValue;
          return;
        }
        const fd = new FormData(checklistItemForm);
        postForm(checklistItemForm.getAttribute('action'), fd, checklistItemForm)
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (data.ok && data.html) {
              replaceDrawerSection('[data-panel-cotizacion-checklist-section="1"]', data.html);
            }
          })
          .catch((error) => {
            if (error?.html) {
              replaceDrawerSection('[data-panel-cotizacion-checklist-section="1"]', error.html);
            } else {
              console.error('No se pudo actualizar el elemento de accion:', error);
            }
          });
        return;
      }

      const commentForm = e.target.closest('[data-panel-cotizacion-comentario-form="1"]');
      if (!commentForm) return;
      e.preventDefault();
      const url = commentForm.getAttribute('action');
      const id = commentForm.getAttribute('data-panel-cotizacion-id');
      if (!url || !id) return;
      const submitButton = commentForm.querySelector('[data-panel-cotizacion-comment-submit="1"]');
      if (submitButton?.disabled) return;
      const textarea = commentForm.querySelector('textarea[name="texto"]');
      const errorNode = commentForm.querySelector('[data-panel-cotizacion-comment-error="1"]');
      const text = (textarea?.value || '').trim();
      if (errorNode) errorNode.textContent = '';
      if (!text) {
        if (errorNode) errorNode.textContent = 'Escribe un comentario.';
        return;
      }
      const fd = new FormData(commentForm);
      if (submitButton) submitButton.disabled = true;
      postForm(url, fd, commentForm)
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok) {
            throw data;
          }
          return data;
        })
        .then((data) => {
          if (data.status !== 'ok') return;
          if (textarea) textarea.value = '';
          const commentsList = commentForm.closest('.panel-cotizacion-detail-body')?.querySelector('[data-panel-cotizacion-comentarios="1"]');
          if (commentsList && data.html) {
            const emptyState = commentsList.querySelector('[data-panel-cotizacion-comments-empty="1"]');
            if (emptyState) emptyState.remove();
            const wrapper = document.createElement('div');
            wrapper.innerHTML = data.html;
            const commentNode = wrapper.firstElementChild;
            if (commentNode) commentsList.prepend(commentNode);
          }
          updateCardCommentCount(id, data.comentarios_count || 0);
        })
        .catch((error) => {
          const fieldErrors = error?.errors?.texto || error?.errors?.__all__ || [];
          if (errorNode && fieldErrors.length) {
            errorNode.textContent = fieldErrors.map((item) => item.message).join(' ');
          } else if (errorNode) {
            errorNode.textContent = 'No se pudo agregar el comentario.';
          } else {
            console.error('No se pudo agregar el comentario:', error);
          }
            if (submitButton) submitButton.disabled = false;
        });

      const tagForm = e.target.closest('[data-panel-cotizacion-tag-assign-form="1"], [data-panel-cotizacion-tag-create-form="1"], [data-panel-cotizacion-tag-remove-form="1"]');
      if (tagForm) {
        e.preventDefault();
        e.stopPropagation();
        const isRemove = tagForm.matches('[data-panel-cotizacion-tag-remove-form="1"]');
        if (isRemove && !window.confirm('¿Quitar esta etiqueta de la cotización?')) return;

        const section = tagForm.closest('[data-panel-cotizacion-tags-section="1"]');
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
            const parent = section.parentElement;
            const temp = document.createElement('div');
            temp.innerHTML = data.tags_html;
            const newSection = temp.firstElementChild;
            if (parent && newSection) {
              parent.replaceChild(newSection, section);
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
            
            const card = document.querySelector(`[data-panel-cotizacion-card="1"][data-panel-cotizacion-id="${data.id}"]`);
            if (card) {
                const tagsContainer = card.querySelector('.panel-cotizacion-card__tags');
                if (tagsContainer) {
                    tagsContainer.innerHTML = data.tags.map(t => 
                        `<div class="panel-cotizacion-tag" style="--panel-tag-bg: ${t.color};">${t.nombre}</div>`
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
                const msg = error && error.error ? error.error : 'No se pudo actualizar la etiqueta. Verifica los datos.';
                alert(msg);
            }
          })
          .finally(() => {
            delete tagForm.dataset.submitting;
          });
      }
    });

    document.addEventListener('keydown', (e) => {
      const checklistTextInput = e.target.closest('[data-panel-cotizacion-checklist-text="1"]');
      if (checklistTextInput && e.key === 'Enter') {
        e.preventDefault();
        checklistTextInput.closest('form')?.requestSubmit();
        return;
      }

      const editor = e.target.closest('[data-panel-cotizacion-inline-editor="1"]');
      if (!editor) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        const slot = editor.closest('[data-panel-cotizacion-inline-slot]');
        restoreInlineSlot(slot);
        return;
      }

      if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA' && !e.shiftKey) {
        e.preventDefault();
        editor.requestSubmit();
      }
    });

    document.addEventListener('change', (e) => {
      const checklistToggle = e.target.closest('[data-panel-cotizacion-checklist-toggle="1"]');
      if (!checklistToggle) return;
      const url = checklistToggle.dataset.toggleUrl;
      if (!url) return;
      const fd = new FormData();
      fd.append('completado', checklistToggle.checked ? '1' : '0');
      postForm(url, fd, checklistToggle)
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok) throw data;
          return data;
        })
        .then((data) => {
          if (data.ok && data.html) {
            replaceDrawerSection('[data-panel-cotizacion-checklist-section="1"]', data.html);
          }
        })
        .catch((error) => {
          console.error('No se pudo actualizar el estado del elemento de accion:', error);
        });
    });

    document.addEventListener('focusout', (e) => {
      const checklistTextInput = e.target.closest('[data-panel-cotizacion-checklist-text="1"]');
      if (!checklistTextInput) return;
      const currentValue = (checklistTextInput.value || '').trim();
      const initialValue = (checklistTextInput.dataset.initialValue || '').trim();
      if (currentValue && currentValue !== initialValue) {
        checklistTextInput.closest('form')?.requestSubmit();
      }
    });

    document.getElementById('panelCotizacionesFilterReset')?.addEventListener('click', () => {
      const select = document.getElementById('panelCotizacionesUserFilter');
      if (!select) return;
      Array.from(select.options).forEach((option) => {
        option.selected = false;
      });
      if (select.tomselect) {
        select.tomselect.clear();
      }
      refreshBoard();
    });

    initSortables();
    syncPasteActions();

  })();
