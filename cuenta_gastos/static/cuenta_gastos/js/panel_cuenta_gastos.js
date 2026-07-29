  document.addEventListener('DOMContentLoaded', function () {
    const root = document.querySelector('[data-cuenta-board="1"]');
    const configElement = document.getElementById('panel-cuenta-gastos-config');
    if (!root || !configElement || root.dataset.panelJsInitialized === '1') return;

    let config;
    try {
      config = JSON.parse(configElement.textContent);
    } catch (_) {
      return;
    }
    if (!config?.inlineCreateUrl || !config?.inlineFormUrl) return;
    root.dataset.panelJsInitialized = '1';

    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    const pendingCardIds = new Set();
    const inlineCreateUrl = config.inlineCreateUrl;
    const inlineFormUrl = config.inlineFormUrl;
    const inlineSlotHome = document.querySelector('[data-cuenta-inline-slot-home="1"]');
    const inlineSharedSlot = document.querySelector('[data-cuenta-inline-shared-slot="1"]');
    let inlineFormLoadPromise = null;
    let inlineFormLoaded = false;
    let latestInlineTarget = null;
    const inlineEditorRequests = new Map();
    const columnLoadRequests = new Map();
    let filterVersion = 0;
    let activeInlineEditorSlot = null;
    let inlineEditorVersion = 0;
    window.initcuentaSelects = window.initcuentaSelects || window.initGarantiaSelects;
    const modalEl = document.getElementById('cuentaModal');
    const modalContent = document.getElementById('modalContent');
    const drawerEl = document.getElementById('cuentaDrawer');
    const drawerContent = document.getElementById('cuentaDrawerContent');
    const drawerSupported = Boolean(drawerEl && drawerContent);
    const detailState = {
      id: null,
      url: null,
      layout: drawerSupported ? 'drawer' : 'modal',
    };

    document.getElementById('CuentaGastosUserFilter')?.addEventListener('change', function () {
      filterVersion += 1;
      columnLoadRequests.forEach((entry) => entry.controller.abort());
      columnLoadRequests.clear();
      this.form.submit();
    });

    function getCardElement(cardId) {
      return cardId ? document.getElementById(`cuenta-${cardId}`) : null;
    }

    function getDetailCardIdFromAction(action) {
      const match = (action || '').match(/\/(\d+)\/(?:editar\/|eliminar\/|agregar-|eliminar-|inline-update\/|mover\/)?$/);
      return match ? match[1] : detailState.id;
    }

    function buildDetailUrl(url, layout) {
      const detailUrl = new URL(url, window.location.origin);
      detailUrl.searchParams.set('layout', layout);
      return `${detailUrl.pathname}${detailUrl.search}`;
    }

    function getCurrentDetailContainer() {
      return detailState.layout === 'drawer' ? drawerContent : modalContent;
    }

    function setDetailState(cuentaId, url, layout) {
      detailState.id = cuentaId ? String(cuentaId) : null;
      detailState.url = url || null;
      detailState.layout = layout;
    }

    function openDrawer() {
      if (!drawerSupported) return;
      drawerEl.hidden = false;
      drawerEl.classList.add('is-open');
      drawerEl.setAttribute('aria-hidden', 'false');
      document.body.classList.add('cuenta-drawer-open');
    }

    function closeDrawer() {
      if (!drawerSupported) return;
      drawerEl.classList.remove('is-open');
      drawerEl.setAttribute('aria-hidden', 'true');
      drawerContent.innerHTML = '<div class="cuenta-drawer__loading">Selecciona una cuenta.</div>';
      document.body.classList.remove('cuenta-drawer-open');
      window.setTimeout(() => {
        if (!drawerEl.classList.contains('is-open')) {
          drawerEl.hidden = true;
        }
      }, 220);
    }

    function renderDetailHtml(layout, html) {
      const target = layout === 'drawer' ? drawerContent : modalContent;
      if (!target) return;
      target.innerHTML = html || '';
      if (typeof window.initcuentaSelects === 'function') {
        window.initcuentaSelects(target);
      }
    }

    function renderDetailError(layout, message) {
      const target = layout === 'drawer' ? drawerContent : modalContent;
      if (!target) return;
      target.innerHTML = `<div class="alert alert-danger m-3 mb-0">${message}</div>`;
    }

    function replaceCardFromHtml(cardId, cardHtml) {
      if (!cardId || !cardHtml) return;
      const existing = getCardElement(cardId);
      if (!existing) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = cardHtml;
      const nextCard = wrapper.firstElementChild;
      if (!nextCard) return;
      existing.replaceWith(nextCard);
    }

    function removeCardFromBoard(cardId) {
      const existing = getCardElement(cardId);
      if (!existing) return;
      const column = existing.closest('.columna-drop');
      existing.remove();
      adjustColumnTotal(column, -1);
    }

    function replaceCommentsSection(cardId, commentsHtml) {
      if (!commentsHtml) return;
      const currentContainer = getCurrentDetailContainer();
      const currentSection = currentContainer?.querySelector('[data-cuenta-comments-section="1"]');
      if (!currentSection) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = commentsHtml;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return;
      currentSection.replaceWith(nextSection);
    }

    function syncCommentsCount(cardId, commentsCount) {
      const detailSection = getCurrentDetailContainer()?.querySelector('[data-cuenta-detail-comments-count="1"]');
      if (detailSection) {
        detailSection.textContent = String(commentsCount);
      }
      const card = getCardElement(cardId);
      const cardCounter = card?.querySelector('[data-cuenta-card-comments-count="1"]');
      if (cardCounter) {
        cardCounter.textContent = `${commentsCount} comentarios`;
      }
    }

    function replaceArchivosSection(html) {
      if (!html) return;
      const currentContainer = getCurrentDetailContainer();
      const currentSection = currentContainer?.querySelector('[data-cuenta-files-section="1"]');
      if (!currentSection) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return;
      currentSection.replaceWith(nextSection);
    }

    function replaceEnlacesSection(html) {
      if (!html) return;
      const currentContainer = getCurrentDetailContainer();
      const currentSection = currentContainer?.querySelector('[data-cuenta-links-section="1"]');
      if (!currentSection) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return;
      currentSection.replaceWith(nextSection);
    }

    function getArchivosSection() {
      return getCurrentDetailContainer()?.querySelector('[data-cuenta-files-section="1"]');
    }

    function getEnlacesSection() {
      return getCurrentDetailContainer()?.querySelector('[data-cuenta-links-section="1"]');
    }

    function setArchivoPending(isPending) {
      const section = getArchivosSection();
      if (!section) return;
      section.dataset.pending = isPending ? '1' : '0';
      const controls = section.querySelectorAll('input, button, textarea, select');
      controls.forEach((control) => {
        control.disabled = isPending;
      });
    }

    function setEnlacePending(isPending) {
      const section = getEnlacesSection();
      if (!section) return;
      section.dataset.pending = isPending ? '1' : '0';
      const controls = section.querySelectorAll('input, button, textarea, select');
      controls.forEach((control) => {
        control.disabled = isPending;
      });
    }

    function updateFileCount(cardId, filesCount) {
      const detailCounter = getCurrentDetailContainer()?.querySelector('[data-cuenta-detail-files-count="1"]');
      if (detailCounter) {
        detailCounter.textContent = String(filesCount);
      }
      const cardCounter = getCardElement(cardId)?.querySelector('[data-cuenta-card-files-count="1"]');
      if (cardCounter) {
        cardCounter.textContent = `${filesCount} archivos`;
      }
    }

    function updateLinkCount(cardId, linksCount) {
      const detailCounter = getCurrentDetailContainer()?.querySelector('[data-cuenta-detail-links-count="1"]');
      if (detailCounter) {
        detailCounter.textContent = String(linksCount);
      }
    }

    function replaceEtiquetasSection(html) {
      if (!html) return;
      const currentSection = getCurrentDetailContainer()?.querySelector('[data-cuenta-tags-section="1"]');
      if (!currentSection) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return;
      currentSection.replaceWith(nextSection);
      if (typeof window.initcuentaSelects === 'function') {
        window.initcuentaSelects(nextSection);
      }
    }

    function replaceOpcionesSection(html) {
      if (!html) return;
      const currentSection = getCurrentDetailContainer()?.querySelector('[data-cuenta-options-section="1"]');
      if (!currentSection) return;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const nextSection = wrapper.firstElementChild;
      if (!nextSection) return;
      currentSection.replaceWith(nextSection);
    }

    function getEtiquetasSection() {
      return getCurrentDetailContainer()?.querySelector('[data-cuenta-tags-section="1"]');
    }

    function getOpcionesSection() {
      return getCurrentDetailContainer()?.querySelector('[data-cuenta-options-section="1"]');
    }

    function setEtiquetaPending(isPending) {
      const section = getEtiquetasSection();
      if (!section) return;
      section.dataset.pending = isPending ? '1' : '0';
      section.querySelectorAll('input, button, textarea, select').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function setOpcionPending(isPending) {
      const section = getOpcionesSection();
      if (!section) return;
      section.dataset.pending = isPending ? '1' : '0';
      section.querySelectorAll('input, button, textarea, select').forEach((control) => {
        control.disabled = isPending;
      });
    }

    function showSectionError(sectionName, message) {
      const section =
        sectionName === 'files' ? getArchivosSection() :
        sectionName === 'links' ? getEnlacesSection() :
        sectionName === 'tags' ? getEtiquetasSection() :
        getOpcionesSection();
      if (!section) return;
      let errorNode = section.querySelector('[data-cuenta-section-network-error="1"]');
      if (!errorNode) {
        errorNode = document.createElement('div');
        errorNode.className = 'cuenta-section-error mt-2';
        errorNode.setAttribute('data-cuenta-section-network-error', '1');
        section.prepend(errorNode);
      }
      errorNode.textContent = message;
    }

    function clearSectionError(sectionName) {
      const section =
        sectionName === 'files' ? getArchivosSection() :
        sectionName === 'links' ? getEnlacesSection() :
        sectionName === 'tags' ? getEtiquetasSection() :
        getOpcionesSection();
      const errorNode = section?.querySelector('[data-cuenta-section-network-error="1"]');
      if (errorNode) errorNode.remove();
    }

    function submitCuentaArchivoForm(form) {
      const cardId = form.dataset.cuentaId || getDetailCardIdFromAction(form.action);
      if (form.dataset.submitting === '1') return;
      form.dataset.submitting = '1';
      clearSectionError('files');
      setArchivoPending(true);

      fetch(form.action, {
        method: form.method || 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form)
      })
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok) throw data;
          return data;
        })
        .then((data) => {
          replaceArchivosSection(data.html);
          updateFileCount(cardId, data.files_count ?? 0);
        })
        .catch((error) => {
          if (error && error.html) {
            replaceArchivosSection(error.html);
            updateFileCount(cardId, error.files_count ?? 0);
            return;
          }
          console.error('No se pudo actualizar la seccion de archivos:', error);
          showSectionError('files', 'No se pudo actualizar la secciÃ³n de archivos.');
        })
        .finally(() => {
          delete form.dataset.submitting;
          setArchivoPending(false);
        });
    }

    function submitCuentaLinkForm(form) {
      const cardId = form.dataset.cuentaId || getDetailCardIdFromAction(form.action);
      if (form.dataset.submitting === '1') return;
      form.dataset.submitting = '1';
      clearSectionError('links');
      setEnlacePending(true);

      fetch(form.action, {
        method: form.method || 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form)
      })
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok) throw data;
          return data;
        })
        .then((data) => {
          replaceEnlacesSection(data.html);
          updateLinkCount(cardId, data.links_count ?? 0);
        })
        .catch((error) => {
          if (error && error.html) {
            replaceEnlacesSection(error.html);
            updateLinkCount(cardId, error.links_count ?? 0);
            return;
          }
          console.error('No se pudo actualizar la seccion de enlaces:', error);
          showSectionError('links', 'No se pudo actualizar la secciÃ³n de enlaces.');
        })
        .finally(() => {
          delete form.dataset.submitting;
          setEnlacePending(false);
        });
    }

    function submitCuentaEtiquetasForm(form) {
      const cardId = form.dataset.cuentaId || getDetailCardIdFromAction(form.action);
      if (form.dataset.submitting === '1') return;
      form.dataset.submitting = '1';
      clearSectionError('tags');
      setEtiquetaPending(true);

      fetch(form.action, {
        method: form.method || 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form)
      })
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok) throw data;
          return data;
        })
        .then((data) => {
          replaceEtiquetasSection(data.html);
          if (data.card_html && data.id) {
            replaceCardFromHtml(data.id, data.card_html);
          }
        })
        .catch((error) => {
          if (error && error.html) {
            replaceEtiquetasSection(error.html);
            return;
          }
          console.error('No se pudo actualizar la secciÃ³n de etiquetas:', error);
          showSectionError('tags', 'No se pudo actualizar la secciÃ³n de etiquetas.');
        })
        .finally(() => {
          delete form.dataset.submitting;
          setEtiquetaPending(false);
        });
    }

    function submitCuentaOpcionesForm(form) {
      const cardId = form.dataset.cuentaId || getDetailCardIdFromAction(form.action);
      if (form.dataset.submitting === '1') return;
      form.dataset.submitting = '1';
      clearSectionError('options');
      setOpcionPending(true);

      fetch(form.action, {
        method: form.method || 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: new FormData(form)
      })
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok) throw data;
          return data;
        })
        .then((data) => {
          replaceOpcionesSection(data.html);
          if (data.card_html && data.id) {
            replaceCardFromHtml(data.id, data.card_html);
          }
        })
        .catch((error) => {
          if (error && error.html) {
            replaceOpcionesSection(error.html);
            return;
          }
          console.error('No se pudo actualizar la secciÃ³n de opciones:', error);
          showSectionError('options', 'No se pudo actualizar la secciÃ³n de opciones.');
        })
        .finally(() => {
          delete form.dataset.submitting;
          setOpcionPending(false);
        });
    }

    function getColumnShell(column) {
      return column?.closest('[data-cuenta-column="1"]') || null;
    }

    function getColumnTotal(column) {
      const value = Number.parseInt(getColumnShell(column)?.dataset.total || '0', 10);
      return Number.isInteger(value) && value >= 0 ? value : 0;
    }

    function ensureEmptyState(column) {
      if (!column) return;
      const cards = column.querySelectorAll('[data-cuenta-card="1"]');
      let empty = column.querySelector('.cuenta-column__empty');
      if (!cards.length && getColumnTotal(column) === 0 && !empty) {
        empty = document.createElement('div');
        empty.className = 'cuenta-column__empty';
        empty.textContent = 'Sin registros.';
        column.appendChild(empty);
      }
      if ((cards.length || getColumnTotal(column) > 0) && empty) empty.remove();
    }

    function setInlineOpenButtonsDisabled(disabled) {
      document.querySelectorAll('[data-cuenta-inline-open="1"]').forEach((button) => {
        button.disabled = disabled;
        button.setAttribute('aria-busy', disabled ? 'true' : 'false');
      });
    }

    function destroyInlineTomSelects(root) {
      if (!root) return;
      root.querySelectorAll('[data-cuenta-tags-select="1"]').forEach((select) => {
        if (select.tomselect) {
          select.tomselect.destroy();
        }
      });
    }

    function initInlineTomSelects(root) {
      if (!root || typeof window.initcuentaSelects !== 'function') return;
      root.querySelectorAll('[data-cuenta-tags-select="1"]').forEach((select) => {
        if (select.tomselect) return;
      });
      window.initcuentaSelects(root);
    }

    function clearInlineFormErrors(root) {
      if (!root) return;
      root.querySelectorAll('.text-danger').forEach((errorNode) => errorNode.remove());
    }

    function configureInlineTarget(target, { clearErrors = true } = {}) {
      if (!inlineSharedSlot || !target) return;
      const form = inlineSharedSlot.querySelector('[data-cuenta-inline-form="1"]');
      const stateInput = form?.querySelector('[name="estado"]');
      const destination = inlineSharedSlot.querySelector('[data-cuenta-inline-destination="1"]');
      if (stateInput) stateInput.value = target.state;
      if (destination) destination.textContent = `Crear en: ${target.label}`;
      inlineSharedSlot.dataset.estado = target.state;
      if (clearErrors) clearInlineFormErrors(inlineSharedSlot);
    }

    function moveInlineSlot(target) {
      if (!inlineSharedSlot || !target?.column) return;
      const actions = target.column.querySelector('.cuenta-column__actions');
      if (!actions) return;
      actions.appendChild(inlineSharedSlot);
      inlineSharedSlot.classList.remove('d-none');
    }

    function showInlineLoading(target) {
      moveInlineSlot(target);
      inlineSharedSlot.innerHTML = (
        '<div class="cuenta-inline-form text-center text-muted small py-3" ' +
        'data-cuenta-inline-loading="1" role="status">Cargando formulario...</div>'
      );
    }

    function replaceInlineFormHtml(html) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const fragments = wrapper.querySelectorAll('[data-cuenta-inline-form-fragment="1"]');
      const forms = wrapper.querySelectorAll('[data-cuenta-inline-form="1"]');
      if (fragments.length !== 1 || forms.length !== 1) {
        throw new Error('La respuesta no contiene un formulario inline vÃ¡lido.');
      }

      destroyInlineTomSelects(inlineSharedSlot);
      inlineSharedSlot.replaceChildren(fragments[0]);
      inlineFormLoaded = true;
    }

    function loadInlineCreateForm() {
      if (inlineFormLoaded) return Promise.resolve();
      if (inlineFormLoadPromise) return inlineFormLoadPromise;

      setInlineOpenButtonsDisabled(true);
      inlineFormLoadPromise = fetch(inlineFormUrl, {
        method: 'GET',
        credentials: 'same-origin',
        redirect: 'error',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then(async (response) => {
          const contentType = response.headers.get('content-type') || '';
          if (!response.ok || !contentType.includes('text/html')) {
            throw new Error(`Respuesta inesperada (${response.status}).`);
          }
          return response.text();
        })
        .then((html) => {
          replaceInlineFormHtml(html);
        })
        .catch((error) => {
          inlineFormLoaded = false;
          if (inlineSharedSlot) {
            inlineSharedSlot.innerHTML = (
              '<div class="alert alert-danger small mb-0" data-cuenta-inline-load-error="1">' +
              'No se pudo cargar el formulario. Intenta nuevamente.</div>'
            );
          }
          throw error;
        })
        .finally(() => {
          inlineFormLoadPromise = null;
          setInlineOpenButtonsDisabled(false);
        });

      return inlineFormLoadPromise;
    }

    function openInlineCreate(target) {
      latestInlineTarget = target;
      if (!inlineFormLoaded) showInlineLoading(target);

      return loadInlineCreateForm()
        .then(() => {
          const finalTarget = latestInlineTarget;
          moveInlineSlot(finalTarget);
          configureInlineTarget(finalTarget);
          initInlineTomSelects(inlineSharedSlot);
          const firstInput = inlineSharedSlot.querySelector('input:not([type="hidden"]), select, textarea');
          if (firstInput) firstInput.focus();
        })
        .catch((error) => {
          moveInlineSlot(latestInlineTarget);
          console.error('No se pudo cargar el formulario inline:', error);
        });
    }

    function closeInlineCreate({ reset = false } = {}) {
      if (!inlineSharedSlot || !inlineSlotHome) return;
      const form = inlineSharedSlot.querySelector('[data-cuenta-inline-form="1"]');
      if (reset && form) {
        destroyInlineTomSelects(inlineSharedSlot);
        form.reset();
        clearInlineFormErrors(inlineSharedSlot);
      }
      inlineSharedSlot.classList.add('d-none');
      inlineSlotHome.appendChild(inlineSharedSlot);
    }

    function syncColumnState(column, totalValue) {
      if (!column) return;
      const shell = getColumnShell(column);
      if (!shell) return;
      if (Number.isInteger(totalValue) && totalValue >= 0) {
        shell.dataset.total = String(totalValue);
      }
      const total = getColumnTotal(column);
      const cards = column.querySelectorAll('[data-cuenta-card="1"]');
      const loaded = cards.length;
      shell.dataset.loaded = String(loaded);
      const countNode = shell.querySelector('[data-cuenta-column-count="1"]');
      if (countNode) countNode.textContent = String(total);

      const button = shell.querySelector('[data-cuenta-load-more="1"]');
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

    function getLoadedCardIds(column) {
      return Array.from(column?.querySelectorAll('[data-cuenta-card="1"]') || [])
        .map((card) => getCardId(card))
        .filter(Boolean);
    }

    function setColumnLoading(shell, isLoading) {
      const button = shell?.querySelector('[data-cuenta-load-more="1"]');
      const indicator = shell?.querySelector('[data-cuenta-load-indicator="1"]');
      if (button) {
        button.disabled = isLoading;
        button.setAttribute('aria-busy', isLoading ? 'true' : 'false');
      }
      if (indicator) indicator.hidden = !isLoading;
    }

    function showColumnLoadError(shell, message) {
      const errorNode = shell?.querySelector('[data-cuenta-load-error="1"]');
      if (!errorNode) return;
      errorNode.textContent = message || '';
      errorNode.hidden = !message;
    }

    function loadMoreCards(button) {
      const shell = button?.closest('[data-cuenta-column="1"]');
      const column = shell?.querySelector('.columna-drop');
      const state = shell?.dataset.estado || column?.dataset.estado || '';
      const loadUrl = button?.dataset.loadUrl || '';
      if (!shell || !column || !state || !loadUrl) {
        return Promise.reject(new Error('Columna no disponible.'));
      }

      const existing = columnLoadRequests.get(state);
      if (existing) return existing.promise;

      const loadedIds = getLoadedCardIds(column);
      const offset = loadedIds.length;
      const selectedUserId = document.getElementById('CuentaGastosUserFilter')?.value || '';
      const url = new URL(loadUrl, window.location.origin);
      url.searchParams.set('offset', String(offset));
      url.searchParams.set('loaded', loadedIds.join(','));
      if (selectedUserId) url.searchParams.set('usuario', selectedUserId);

      const controller = new AbortController();
      const requestVersion = filterVersion;
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
          if (requestVersion !== filterVersion || controller.signal.aborted) {
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
            Array.from(column.querySelectorAll('[data-cuenta-card="1"]'))
              .find((card) => getCardId(card) === cardId)
              ?.remove();
          });
          const wrapper = document.createElement('div');
          wrapper.innerHTML = data.html;
          const cards = Array.from(wrapper.children).filter(
            (node) => node.matches?.('[data-cuenta-card="1"]')
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
              card.dataset.cuentaState !== state
            ) {
              throw new Error('Tarjeta duplicada o incompatible.');
            }
            responseIds.add(cardId);
          });

          column.querySelector('.cuenta-column__empty')?.remove();
          const fragment = document.createDocumentFragment();
          cards.forEach((card) => fragment.appendChild(card));
          column.appendChild(fragment);
          syncColumnState(column, data.total);
          button.hidden = !data.has_more;
          return data;
        })
        .catch((error) => {
          if (error.name === 'AbortError' || requestVersion !== filterVersion) {
            return null;
          }
          showColumnLoadError(shell, 'No se pudieron cargar las tarjetas. Intenta nuevamente.');
          throw error;
        })
        .finally(() => {
          if (columnLoadRequests.get(state)?.promise === request) {
            columnLoadRequests.delete(state);
            setColumnLoading(shell, false);
          }
        });

      columnLoadRequests.set(state, {promise: request, controller});
      return request;
    }

    function insertCardAt(column, card, index) {
      if (!column || !card) return;
      const cards = Array.from(column.querySelectorAll('[data-cuenta-card="1"]')).filter((node) => node !== card);
      if (typeof index !== 'number' || index < 0 || index >= cards.length) {
        column.appendChild(card);
        return;
      }
      column.insertBefore(card, cards[index]);
    }

    function moveCardToColumn(card, targetColumn, index) {
      if (!card || !targetColumn) return;
      const emptyState = targetColumn.querySelector('.cuenta-column__empty');
      if (emptyState) emptyState.remove();
      const cards = Array.from(targetColumn.querySelectorAll('[data-cuenta-card="1"]')).filter((node) => node !== card);
      if (typeof index !== 'number' || index <= 0) {
        targetColumn.prepend(card);
        return;
      }
      if (index >= cards.length) {
        targetColumn.appendChild(card);
        return;
      }
      targetColumn.insertBefore(card, cards[index]);
    }

    function getEstadoLabel(value) {
      const option = document.querySelector(`[data-cuenta-state-select="1"] option[value="${value}"]`);
      return option ? option.textContent.trim() : value || '';
    }

    function getCardId(card) {
      return card?.getAttribute('data-id') || '';
    }

    function isCardPending(card) {
      return pendingCardIds.has(getCardId(card));
    }

    function setCardPendingById(cardId, isPending) {
      if (!cardId) return;
      if (isPending) {
        pendingCardIds.add(String(cardId));
      } else {
        pendingCardIds.delete(String(cardId));
      }
      const card = getCardElement(cardId);
      if (card) {
        setCardPending(card, isPending);
      }
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

      const stateSelect = card.querySelector('[data-cuenta-state-select="1"]');
      const detailButton = card.querySelector('[data-cuenta-modal-open="1"]');
      if (stateSelect) stateSelect.disabled = isPending;
      if (detailButton) detailButton.disabled = isPending;
    }

    function syncCardStateUI(card, estado, estadoLabel) {
      if (!card) return;
      card.dataset.cuentaState = estado;
      const stateSelect = card.querySelector('[data-cuenta-state-select="1"]');
      const stateBadge = card.querySelector('[data-cuenta-state-badge="1"]');
      if (stateSelect) stateSelect.value = estado;
      if (stateBadge) stateBadge.textContent = estadoLabel || getEstadoLabel(estado);
    }

    function rollbackCuentaGastosCard({ card, sourceColumn, targetColumn, sourceIndex, previousState }) {
      if (!card || !sourceColumn) return;
      insertCardAt(sourceColumn, card, sourceIndex);
      syncCardStateUI(card, previousState, getEstadoLabel(previousState));
      syncColumnState(sourceColumn);
      if (targetColumn && targetColumn !== sourceColumn) {
        syncColumnState(targetColumn);
      }
    }

    function loadInlineEditor(card, fieldName) {
      const cardId = getCardId(card);
      const endpoint = card?.dataset.cuentaEditorUrl;
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
      slot?.insertAdjacentHTML('beforeend', '<div class="text-danger small mt-1" data-cuenta-inline-load-error="1">No se pudo cargar el editor. Intenta nuevamente.</div>');
    }

    function openInlineEditor(slot, fieldName, card) {
      const selectedIdsSnapshot = slot.querySelector('[data-selected-ids]')?.dataset.selectedIds || '';
      if (activeInlineEditorSlot && activeInlineEditorSlot !== slot) restoreInlineSlot(activeInlineEditorSlot);
      slot.querySelector('[data-cuenta-inline-load-error="1"]')?.remove();
      slot.dataset.previousHtml = slot.innerHTML;
      activeInlineEditorSlot = slot;
      const version = ++inlineEditorVersion;
      slot.innerHTML = '<div class="text-muted small py-2" data-cuenta-inline-editor-loading="1">Cargando editor...</div>';

      return loadInlineEditor(card, fieldName).then((editorHtml) => {
      if (version !== inlineEditorVersion || activeInlineEditorSlot !== slot || !slot.isConnected) return null;
      slot.innerHTML = editorHtml;
      const form = slot.querySelector('[data-cuenta-inline-editor="1"]');
      if (!form || String(form.dataset.cuentaEditorId) !== String(getCardId(card)) || form.dataset.field !== fieldName) {
        throw new Error('Editor inesperado.');
      }

      if (fieldName === 'titulo') {
        const input = form.querySelector('[name="titulo"]');
        const currentValue = card.querySelector('[data-cuenta-inline-slot="titulo"] .cuenta-card__title')?.textContent?.trim() || '';
        if (input) {
          input.value = /^Sin tÃ­tulo$/.test(currentValue) ? '' : currentValue;
          input.focus();
          input.select();
        }
      } else if (fieldName === 'cliente') {
        const currentText = card.querySelector('[data-cuenta-inline-slot="cliente"] .cuenta-card__client')?.textContent?.trim() || '';
        const select = form.querySelector('[name="cliente"]');
        if (select) {
          const option = Array.from(select.options).find((item) => item.text.trim() === currentText);
          if (option) select.value = option.value;
          select.focus();
        }
      } else if (fieldName === 'prioridad') {
        const currentText = card.querySelector('[data-cuenta-inline-slot="prioridad"] .cuenta-chip')?.textContent?.trim() || '';
        const select = form.querySelector('[name="prioridad"]');
        if (select) {
          const option = Array.from(select.options).find((item) => item.text.trim() === currentText);
          if (option) select.value = option.value;
          select.focus();
        }
      } else if (fieldName === 'fecha_vencimiento') {
        const input = form.querySelector('[name="fecha_vencimiento"]');
        const currentValue = slot.querySelector('[data-date-value]')?.dataset.dateValue || '';
        if (input) {
          input.value = currentValue;
          input.focus();
        }
      } else if (fieldName === 'asignados') {
        const select = form.querySelector('[name="asignados"]');
        const selectedIds = selectedIdsSnapshot.split(',').map((value) => value.trim()).filter(Boolean);
        if (select) {
          Array.from(select.options).forEach((option) => {
            option.selected = selectedIds.includes(option.value);
          });
        }
        if (window.initcuentaSelects) {
          window.initcuentaSelects(form);
        }
      }

      return form;
      }).catch((error) => {
        if (version !== inlineEditorVersion || activeInlineEditorSlot !== slot) return null;
        console.error('No se pudo cargar el editor inline:', error);
        showInlineEditorLoadError(slot);
        return null;
      });
    }

    async function moveCuentaGastosCard({
      card,
      targetState,
      sourceColumn,
      targetColumn,
      sourceIndex,
      targetIndex,
      trigger,
    }) {
      if (!card || !sourceColumn || !targetColumn || !targetState) {
        throw new Error('Movimiento invalido');
      }

      if (isCardPending(card)) {
        throw new Error('La cuenta ya se esta actualizando');
      }

      const previousState = card.dataset.cuentaState || sourceColumn.dataset.estado || '';
      const sameColumn = sourceColumn === targetColumn;

      if (sameColumn && previousState === targetState && trigger === 'drag') {
        insertCardAt(sourceColumn, card, sourceIndex);
        syncColumnState(sourceColumn);
        return { ok: true, skipped: true };
      }

      setCardPending(card, true);

      try {
        const response = await fetch(`/cuenta-gastos/${getCardId(card)}/mover/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: `estado=${encodeURIComponent(targetState)}`
        });

        if (!response.ok) {
          throw new Error(`Error ${response.status}`);
        }

        const data = await response.json();
        if (!data.ok) {
          throw new Error('Estado no actualizado');
        }

        syncCardStateUI(card, data.estado || targetState, data.estado_label || getEstadoLabel(targetState));
        if (!sameColumn) {
          adjustColumnTotal(sourceColumn, -1);
          adjustColumnTotal(targetColumn, 1);
        } else {
          syncColumnState(sourceColumn);
        }
        return data;
      } catch (error) {
        rollbackCuentaGastosCard({
          card,
          sourceColumn,
          targetColumn,
          sourceIndex,
          previousState,
        });
        throw error;
      } finally {
        setCardPending(card, false);
      }
    }

    document.addEventListener('click', function (e) {
      const loadMoreButton = e.target.closest('[data-cuenta-load-more="1"]');
      if (loadMoreButton) {
        e.preventDefault();
        loadMoreCards(loadMoreButton).catch((error) => {
          console.error('No se pudieron cargar mas tarjetas:', error);
        });
        return;
      }

      const inlineOpenButton = e.target.closest('[data-cuenta-inline-open="1"]');
      if (inlineOpenButton) {
        e.preventDefault();
        const column = inlineOpenButton.closest('[data-cuenta-column="1"]');
        if (!column) return;
        openInlineCreate({
          column,
          state: inlineOpenButton.dataset.estado || '',
          label: inlineOpenButton.dataset.estadoLabel || '',
        });
        return;
      }

      const inlineCancelButton = e.target.closest('[data-cuenta-inline-cancel="1"]');
      if (inlineCancelButton) {
        e.preventDefault();
        closeInlineCreate({ reset: true });
        return;
      }

      const inlineFieldValue = e.target.closest('[data-cuenta-inline-field]');
      if (inlineFieldValue) {
        e.preventDefault();
        const card = inlineFieldValue.closest('[data-cuenta-card="1"]');
        const slot = inlineFieldValue.closest('[data-cuenta-inline-slot]');
        const fieldName = inlineFieldValue.dataset.cuentaInlineField;
        if (!card || !slot || !fieldName || isCardPending(card)) return;
        if (slot.querySelector('[data-cuenta-inline-editor="1"]')) return;
        openInlineEditor(slot, fieldName, card);
        return;
      }

      const inlineFieldCancelButton = e.target.closest('[data-cuenta-inline-field-cancel="1"]');
      if (inlineFieldCancelButton) {
        e.preventDefault();
        const slot = inlineFieldCancelButton.closest('[data-cuenta-inline-slot]');
        inlineEditorVersion += 1;
        restoreInlineSlot(slot);
        return;
      }

      const drawerCloseButton = e.target.closest('[data-cuenta-drawer-close="1"]');
      if (drawerCloseButton) {
        e.preventDefault();
        closeDrawer();
        return;
      }

      const btn = e.target.closest('[data-cuenta-modal-open="1"]');
      if (!btn) return;
      e.preventDefault();

      const cuentaId = btn.dataset.id;
      const url = btn.dataset.modalUrl || (cuentaId ? `/cuenta-gastos/detalle/${cuentaId}/` : null);
      if (!url) return;

      cargarDetalleCuentaDrawer(cuentaId, url);
    });

    document.querySelectorAll('.columna-drop').forEach((col) => {
      syncColumnState(col);
      Sortable.create(col, {
        group: 'cuentas',
        animation: 150,
        onMove: function (evt) {
          if (isCardPending(evt.dragged)) return false;
          return true;
        },
        onEnd: function (evt) {
          const card = evt.item;
          const sourceColumn = evt.from;
          const targetColumn = evt.to;
          const targetState = targetColumn?.dataset.estado;
          const sourceIndex = evt.oldIndex;
          const targetIndex = evt.newIndex;

          if (!card || !sourceColumn || !targetColumn || !targetState) return;

          moveCuentaGastosCard({
            card,
            targetState,
            sourceColumn,
            targetColumn,
            sourceIndex,
            targetIndex,
            trigger: 'drag',
          }).catch((error) => {
            console.error('No se pudo mover la cuenta de gastos:', error);
          });
        }
      });
    });

    document.addEventListener('change', function (e) {
      const stateSelect = e.target.closest('[data-cuenta-state-select="1"]');
      if (!stateSelect) return;

      const card = stateSelect.closest('[data-cuenta-card="1"]');
      const sourceColumn = card?.closest('.columna-drop');
      const previousState = card?.dataset.cuentaState || sourceColumn?.dataset.estado || '';
      const targetState = stateSelect.value;

      if (!card || !sourceColumn || !targetState || previousState === targetState) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      if (isCardPending(card)) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      const targetColumn = document.querySelector(`.columna-drop[data-estado="${targetState}"]`);
      if (!targetColumn) {
        syncCardStateUI(card, previousState, getEstadoLabel(previousState));
        return;
      }

      const sourceIndex = Array.from(sourceColumn.querySelectorAll('[data-cuenta-card="1"]')).indexOf(card);
      moveCardToColumn(card, targetColumn, 0);
      syncColumnState(sourceColumn);
      syncColumnState(targetColumn);

      moveCuentaGastosCard({
        card,
        targetState,
        sourceColumn,
        targetColumn,
        sourceIndex,
        targetIndex: 0,
        trigger: 'select',
      }).catch((error) => {
        console.error('No se pudo actualizar el estado de la cuenta de gastos:', error);
      });
    });

    function loadCuentaDetalle(cuentaId, url, preferredLayout) {
      const layout = preferredLayout === 'drawer' && drawerSupported ? 'drawer' : 'modal';
      const finalUrl = url || `/cuenta-gastos/detalle/${cuentaId}/`;
      setDetailState(cuentaId, finalUrl, layout);

      if (layout === 'drawer') {
        renderDetailHtml(layout, '<div class="cuenta-drawer__loading">Cargando detalle...</div>');
        openDrawer();
      } else {
        if (modalContent) {
          modalContent.innerHTML = '<div class="modal-body p-4 text-center text-muted">Cargando...</div>';
        }
        if (modalEl && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          bootstrap.Modal.getOrCreateInstance(modalEl).show();
        }
      }

      return fetch(buildDetailUrl(finalUrl, layout), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((response) => {
          if (!response.ok) throw new Error(`Error ${response.status}`);
          return response.json();
        })
        .then((data) => {
          renderDetailHtml(layout, data.html || '');
        })
        .catch((error) => {
          console.error('No se pudo cargar el detalle de la cuenta:', error);
          renderDetailError(layout, 'No se pudo cargar el detalle.');
        });
    }

    window.cargarDetalleCuenta = function (cuentaId, url) {
      return loadCuentaDetalle(cuentaId, url, 'modal');
    };

    window.cargarDetalleCuentaDrawer = function (cuentaId, url) {
      return loadCuentaDetalle(cuentaId, url, 'drawer');
    };

    document.addEventListener('submit', function (e) {
      const inlineEditor = e.target.closest('[data-cuenta-inline-editor="1"]');
      if (inlineEditor) {
        e.preventDefault();
        const slot = inlineEditor.closest('[data-cuenta-inline-slot]');
        const card = inlineEditor.closest('[data-cuenta-card="1"]');
        const fieldName = inlineEditor.dataset.field;
        if (!slot || !card || !fieldName || isCardPending(card)) return;

        const formData = new FormData(inlineEditor);
        const selectedUserId = document.getElementById('CuentaGastosUserFilter')?.value || '';
        if (selectedUserId) formData.set('usuario', selectedUserId);
        setCardPending(card, true);
        fetch(inlineEditor.dataset.updateUrl, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData
        })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;
            if (data.matches_filter === false) {
              const column = card.closest('.columna-drop');
              card.remove();
              syncColumnState(column, data.column_count);
              if (activeInlineEditorSlot === slot) activeInlineEditorSlot = null;
              return;
            }
            slot.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
            slot.innerHTML = data.html;
            delete slot.dataset.previousHtml;
            if (activeInlineEditorSlot === slot) activeInlineEditorSlot = null;
            syncColumnState(card.closest('.columna-drop'), data.column_count);
          })
          .catch((error) => {
            if (
              error?.html &&
              String(error.id) === String(getCardId(card)) &&
              error.field === fieldName
            ) {
              slot.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
              slot.innerHTML = error.html;
              const replacement = slot.querySelector('[data-cuenta-inline-editor="1"]');
              if (fieldName === 'asignados') window.initcuentaSelects?.(replacement);
              replacement?.querySelector('.is-invalid, input:not([type="hidden"]), select, textarea')?.focus();
              return;
            }
            const errorNode = inlineEditor.querySelector('[data-cuenta-inline-error="1"]');
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

      const inlineForm = e.target.closest('[data-cuenta-inline-form="1"]');
      if (inlineForm) {
        e.preventDefault();
        if (inlineForm.dataset.submitting === '1') return;
        const submittedState = inlineForm.querySelector('[name="estado"]')?.value || '';
        const submittedColumn = document.querySelector(
          `.columna-drop[data-estado="${submittedState}"]`
        );
        const submittedTarget = {
          column: submittedColumn?.closest('[data-cuenta-column="1"]'),
          state: submittedState,
          label: submittedColumn?.closest('[data-cuenta-column="1"]')
            ?.querySelector('[data-cuenta-inline-open="1"]')?.dataset.estadoLabel || submittedState,
        };
        if (!submittedColumn || !submittedTarget.column) return;

        const submitButton = inlineForm.querySelector('button[type="submit"]');
        if (submitButton?.disabled) return;
        if (submitButton) submitButton.disabled = true;
        inlineForm.dataset.submitting = '1';

        const formData = new FormData(inlineForm);
        const selectedUserId = document.getElementById('CuentaGastosUserFilter')?.value || '';
        if (selectedUserId) formData.set('usuario', selectedUserId);
        fetch(inlineCreateUrl, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData
        })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            if (!data.ok) return;

            const wrapper = document.createElement('div');
            wrapper.innerHTML = data.html;
            const card = wrapper.firstElementChild;
            if (!card) return;

            if (data.matches_filter !== false) {
              const targetColumn = document.querySelector(
                `.columna-drop[data-estado="${data.estado}"]`
              );
              if (targetColumn) {
                const emptyState = targetColumn.querySelector('.cuenta-column__empty');
                if (emptyState) emptyState.remove();
                const duplicateCard = getCardElement(data.id);
                if (duplicateCard) duplicateCard.remove();
                targetColumn.prepend(card);
                syncColumnState(targetColumn, data.column_count);
              }
            }

            closeInlineCreate({ reset: true });
          })
          .catch((error) => {
            if (error && error.html) {
              try {
                replaceInlineFormHtml(error.html);
                latestInlineTarget = submittedTarget;
                moveInlineSlot(submittedTarget);
                configureInlineTarget(submittedTarget, { clearErrors: false });
                initInlineTomSelects(inlineSharedSlot);
              } catch (renderError) {
                inlineSharedSlot.innerHTML = (
                  '<div class="alert alert-danger small mb-0">' +
                  'No se pudo mostrar el formulario. Intenta nuevamente.</div>'
                );
                inlineFormLoaded = false;
              }
              return;
            }
            console.error('No se pudo crear la cuenta de gastos:', error);
          })
          .finally(() => {
            if (submitButton) submitButton.disabled = false;
            delete inlineForm.dataset.submitting;
        });
        return;
      }

      const commentForm = e.target.closest('[data-cuenta-comentario-form="1"]');
      if (commentForm) {
        e.preventDefault();
        if (commentForm.dataset.submitting === '1') return;

        const cardId = commentForm.dataset.cuentaId || getDetailCardIdFromAction(commentForm.action);
        const activeCard = getCardElement(cardId);
        if (activeCard && isCardPending(activeCard)) return;

        commentForm.dataset.submitting = '1';
        setCardPendingById(cardId, true);

        fetch(commentForm.action, {
          method: commentForm.method || 'POST',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          body: new FormData(commentForm)
        })
          .then(async (response) => {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          })
          .then((data) => {
            replaceCommentsSection(cardId, data.comments_html);
            syncCommentsCount(cardId, data.comments_count ?? 0);
          })
          .catch((error) => {
            if (error && error.comments_html) {
              replaceCommentsSection(cardId, error.comments_html);
              syncCommentsCount(cardId, error.comments_count ?? 0);
              return;
            }
            console.error('No se pudo guardar el comentario:', error);
          })
          .finally(() => {
            delete commentForm.dataset.submitting;
            setCardPendingById(cardId, false);
          });
        return;
      }

      const archivoForm = e.target.closest('[data-cuenta-archivo-form="1"]');
      if (archivoForm) {
        e.preventDefault();
        submitCuentaArchivoForm(archivoForm);
        return;
      }

      const archivoDeleteForm = e.target.closest('[data-cuenta-archivo-delete="1"]');
      if (archivoDeleteForm) {
        e.preventDefault();
        if (!window.confirm('Â¿Eliminar este archivo?')) return;
        submitCuentaArchivoForm(archivoDeleteForm);
        return;
      }

      const enlaceForm = e.target.closest('[data-cuenta-enlace-form="1"]');
      if (enlaceForm) {
        e.preventDefault();
        submitCuentaLinkForm(enlaceForm);
        return;
      }

      const enlaceDeleteForm = e.target.closest('[data-cuenta-enlace-delete="1"]');
      if (enlaceDeleteForm) {
        e.preventDefault();
        if (!window.confirm('Â¿Eliminar este enlace?')) return;
        submitCuentaLinkForm(enlaceDeleteForm);
        return;
      }

      const etiquetasForm = e.target.closest('[data-cuenta-etiquetas-form="1"]');
      if (etiquetasForm) {
        e.preventDefault();
        submitCuentaEtiquetasForm(etiquetasForm);
        return;
      }

      const etiquetaCreateForm = e.target.closest('[data-cuenta-etiqueta-create-form="1"]');
      if (etiquetaCreateForm) {
        e.preventDefault();
        submitCuentaEtiquetasForm(etiquetaCreateForm);
        return;
      }

      const etiquetaRemoveForm = e.target.closest('[data-cuenta-etiqueta-remove="1"]');
      if (etiquetaRemoveForm) {
        e.preventDefault();
        submitCuentaEtiquetasForm(etiquetaRemoveForm);
        return;
      }

      const opcionesForm = e.target.closest('[data-cuenta-opciones-form="1"]');
      if (opcionesForm) {
        e.preventDefault();
        submitCuentaOpcionesForm(opcionesForm);
        return;
      }

      const opcionCreateForm = e.target.closest('[data-cuenta-opcion-create-form="1"]');
      if (opcionCreateForm) {
        e.preventDefault();
        submitCuentaOpcionesForm(opcionCreateForm);
        return;
      }

      const opcionRemoveForm = e.target.closest('[data-cuenta-opcion-remove="1"]');
      if (opcionRemoveForm) {
        e.preventDefault();
        submitCuentaOpcionesForm(opcionRemoveForm);
        return;
      }

      const form = e.target.closest('#modalContent form, #cuentaDrawerContent form');
      if (!form) return;
      e.preventDefault();

      if (form.dataset.submitting === '1') return;
      form.dataset.submitting = '1';

      const cardId = getDetailCardIdFromAction(form.action);
      const activeCard = getCardElement(cardId);
      if (activeCard && isCardPending(activeCard)) {
        delete form.dataset.submitting;
        return;
      }

      setCardPendingById(cardId, true);
      const formData = new FormData(form);
      const selectedUserId = document.getElementById('CuentaGastosUserFilter')?.value || '';
      if (selectedUserId) formData.set('usuario', selectedUserId);
      fetch(form.action, {
        method: form.method || 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        body: formData
      })
        .then(async (response) => {
          const contentType = response.headers.get('content-type') || '';
          if (contentType.includes('application/json')) {
            const data = await response.json();
            if (!response.ok) throw data;
            return data;
          }
          return { success: false, html: await response.text() };
        })
        .then((data) => {
          if (data.success) {
            if (data.matches_filter === false && data.id) {
              const card = getCardElement(data.id);
              const column = card?.closest('.columna-drop');
              card?.remove();
              syncColumnState(column, data.column_count);
            } else if (data.card_html && data.id) {
              replaceCardFromHtml(data.id, data.card_html);
              syncColumnState(
                getCardElement(data.id)?.closest('.columna-drop'),
                data.column_count
              );
            }
            if (data.redirect && data.id) {
              removeCardFromBoard(data.id);
              if (detailState.layout === 'drawer') {
                closeDrawer();
              } else if (modalEl && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                bootstrap.Modal.getOrCreateInstance(modalEl).hide();
              }
              detailState.id = null;
              detailState.url = null;
            } else if (data.html) {
              renderDetailHtml(detailState.layout, data.html);
            }
          } else if (data.html) {
            renderDetailHtml(detailState.layout, data.html);
          }
        })
        .catch((error) => {
          console.error('No se pudo actualizar la cuenta de gastos:', error);
          renderDetailError(detailState.layout, 'No se pudo actualizar la cuenta.');
        })
        .finally(() => {
          delete form.dataset.submitting;
          setCardPendingById(cardId, false);
        });
    });

    document.addEventListener('keydown', function (e) {
      const editor = e.target.closest('[data-cuenta-inline-editor="1"]');
      if (!editor) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        const slot = editor.closest('[data-cuenta-inline-slot]');
        restoreInlineSlot(slot);
        return;
      }

      if (editor.dataset.field !== 'asignados' && e.key === 'Enter' && e.target.tagName !== 'TEXTAREA' && !e.shiftKey) {
        e.preventDefault();
        editor.requestSubmit();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && drawerSupported && drawerEl.classList.contains('is-open')) {
        const activeInlineEditor = document.activeElement?.closest?.('[data-cuenta-inline-editor="1"]');
        if (!activeInlineEditor) {
          closeDrawer();
        }
      }
    });
  });
