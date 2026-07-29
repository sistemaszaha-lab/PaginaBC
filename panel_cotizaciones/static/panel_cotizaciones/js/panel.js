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

    const modalElement = document.getElementById('panelCotizacionDetalleModal');
    const modalContent = document.getElementById('panelCotizacionDetalleModalContent');
    const modalInstance = modalElement && window.bootstrap ? new bootstrap.Modal(modalElement) : null;
    const drawerElement = document.getElementById('panelCotizacionDrawer');
    const drawerContent = document.getElementById('panelCotizacionDrawerContent');
    const drawerInstance = drawerElement && window.bootstrap ? new bootstrap.Offcanvas(drawerElement) : null;
    const confirmModalElement = document.getElementById('panelCotizacionEliminarConfirmModal');
    const confirmModalInstance = confirmModalElement && window.bootstrap ? new bootstrap.Modal(confirmModalElement) : null;
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
      shell.dataset.loaded = String(loaded);
      const countNode = shell.querySelector('[data-panel-cotizacion-column-count="1"]');
      if (countNode) {
        countNode.textContent = String(total);
      }
      const button = shell.querySelector('[data-panel-cotizacion-load-more="1"]');
      const remaining = Math.max(0, total - loaded);
      if (button) {
        button.hidden = remaining === 0;
        button.textContent = `Cargar más (${remaining} restantes)`;
      }
      ensureEmptyState(column);
    }

    function adjustColumnTotal(column, delta) {
      if (!column) return;
      syncColumnState(column, Math.max(0, getColumnTotal(column) + delta));
    }

    function getEstadoLabel(value) {
      if (value === 'REQUERIMIENTO') return 'Requerimiento';
      if (value === 'EN_PROGRESO') return 'En progreso';
      if (value === 'ENVIADA') return 'Enviada';
      return value || '';
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
      if (!root || !window.initGarantiaSelects) return;
      root.querySelectorAll('select').forEach((select) => {
        if (select.tomselect) return;
      });
      window.initGarantiaSelects(root);
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
        }
        const firstInput = form.querySelector('input:not([type="hidden"]), select, textarea');
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

    function setColumnLoading(shell, isLoading) {
      const button = shell?.querySelector('[data-panel-cotizacion-load-more="1"]');
      const indicator = shell?.querySelector('[data-panel-cotizacion-load-indicator="1"]');
      if (button) {
        button.disabled = isLoading;
        button.setAttribute('aria-busy', isLoading ? 'true' : 'false');
      }
      if (indicator) indicator.hidden = !isLoading;
    }

    function showColumnLoadError(shell, message) {
      const errorNode = shell?.querySelector('[data-panel-cotizacion-load-error="1"]');
      if (!errorNode) return;
      errorNode.textContent = message || '';
      errorNode.hidden = !message;
    }

    function invalidateColumnLoads() {
      boardVersion += 1;
      columnLoadRequests.forEach((entry) => entry.controller.abort());
      columnLoadRequests.clear();
    }

    function loadMoreCards(button) {
      const shell = button?.closest('[data-panel-cotizacion-column="1"]');
      const column = shell?.querySelector('.panel-cotizaciones-col');
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
      getSelectedUserIds().forEach((userId) => {
        url.searchParams.append('usuario', userId);
      });

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
            Array.from(column.querySelectorAll('[data-panel-cotizacion-card="1"]'))
              .find((card) => getCardId(card) === cardId)
              ?.remove();
          });
          const wrapper = document.createElement('div');
          wrapper.innerHTML = data.html;
          const cards = Array.from(wrapper.children).filter(
            (node) => node.matches?.('[data-panel-cotizacion-card="1"]')
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
              card.dataset.panelCotizacionState !== state
            ) {
              throw new Error('Tarjeta duplicada o incompatible.');
            }
            responseIds.add(cardId);
          });

          column.querySelector('.panel-cotizacion-empty')?.remove();
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

    function initSortable() {
      if (typeof Sortable === 'undefined') return;
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
            const nuevoEstado = target.getAttribute('data-estado');
            if (!id || !nuevoEstado || source === target || isCardPending(card)) {
              ensureEmptyState(source);
              ensureEmptyState(target);
              if (isCardPending(card) && source !== target) {
                source.prepend(card);
              }
              return;
            }

            const previousState = source.dataset.estado;

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
      if (!drawerContent) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.firstElementChild;
      const currentSection = drawerContent.querySelector(selector);
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
      invalidateColumnLoads();
      boardRefreshController?.abort();
      const controller = new AbortController();
      boardRefreshController = controller;
      const requestVersion = boardVersion;
      const selectedUsuarios = getSelectedUserIds();
      const params = new URLSearchParams();
      selectedUsuarios.forEach((usuarioId) => params.append('usuario', usuarioId));
      const url = params.toString() ? `${boardUrl}?${params.toString()}` : boardUrl;
      return getHtml(url, {signal: controller.signal})
        .then((html) => {
          if (requestVersion !== boardVersion || controller.signal.aborted) return;
          const board = document.getElementById('panelCotizacionesBoard');
          if (!board) return;
          closeInlineCreateForm();
          board.innerHTML = html;
          initSortable();
        })
        .catch((error) => {
          if (error.name === 'AbortError' || requestVersion !== boardVersion) return;
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

      showColumnLoadError(getColumnShell(sourceColumn), '');
      showColumnLoadError(getColumnShell(targetColumn), '');
      moveCardToColumn(card, targetColumn);
      persistCardState(card, sourceColumn, targetColumn, nuevoEstado, previousState, triggerElement)
        .catch((error) => {
          const message = getStateChangeErrorMessage(error);
          showColumnLoadError(getColumnShell(sourceColumn), message);
          if (sourceColumn !== targetColumn) {
            showColumnLoadError(getColumnShell(targetColumn), message);
          }
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

      const loadMoreButton = e.target.closest('[data-panel-cotizacion-load-more="1"]');
      if (loadMoreButton) {
        e.preventDefault();
        loadMoreCards(loadMoreButton).catch((error) => {
          console.error('No se pudieron cargar mas tarjetas:', error);
        });
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
      if (drawerInstance) {
        loadDrawer(url);
      } else {
        currentDetailUrl = url;
        loadModal(url);
      }
    });

    document.addEventListener('submit', (e) => {
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
        inlineForm.querySelectorAll('button, input, select').forEach((control) => { control.disabled = true; });
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
              wrapper.innerHTML = data.html;
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

            destroyInlineCreateSelects(inlineForm);
            inlineForm.reset();
            initInlineCreateSelects(inlineForm);
            closeInlineCreateForm();
          })
          .catch((error) => {
            if (error?.data?.html) {
              replaceInlineCreateForm(error.data.html, submittedTarget);
              return;
            }
            console.error('No se pudo crear la cotizacion:', error);
          })
          .finally(() => {
            const activeForm = inlineSharedSlot?.querySelector('[data-panel-cotizacion-inline-form="1"]');
            if (activeForm) {
              delete activeForm.dataset.submitting;
              activeForm.setAttribute('aria-busy', 'false');
              activeForm.querySelectorAll('button, input, select').forEach((control) => { control.disabled = false; });
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
        })
        .finally(() => {
          if (submitButton) submitButton.disabled = false;
        });
    });

    document.addEventListener('keydown', (e) => {
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

    initSortable();
  })();
