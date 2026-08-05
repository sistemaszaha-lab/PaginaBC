/* Controlador compartido para la edicion rapida de tarjetas Kanban. */
(function () {
  window.createKanbanQuickEditController = function (options) {
    const originals = new WeakMap();
    const editingIds = new Set();
    const requestVersions = new WeakMap();
    const controllers = new WeakMap();
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    const getId = options.getId;

    function isEditing(card) {
      return Boolean(card && editingIds.has(getId(card)));
    }

    function replaceCard(card, html) {
      if (!card?.isConnected || !html) return null;
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html || '';
      const next = wrapper.firstElementChild;
      if (!next) return null;
      card.replaceWith(next);
      options.initComponents?.(next);
      return next;
    }

    function nextRequest(card) {
      controllers.get(card)?.abort();
      const controller = new AbortController();
      const version = (requestVersions.get(card) || 0) + 1;
      requestVersions.set(card, version);
      controllers.set(card, controller);
      return { controller, version };
    }

    async function readJson(response) {
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        throw new Error('Respuesta inesperada del servidor.');
      }
      try {
        return await response.json();
      } catch (_) {
        throw new Error('La respuesta JSON no es valida.');
      }
    }

    function restore(card) {
      const html = originals.get(card);
      if (!card || !html) return;
      card.querySelectorAll('select').forEach((select) => select.tomselect?.destroy());
      card.innerHTML = html;
      originals.delete(card);
      editingIds.delete(getId(card));
      delete card.dataset.quickEditing;
    }

    function closeOthers(except) {
      document.querySelectorAll(options.cardSelector).forEach((card) => {
        if (card !== except && isEditing(card) && !options.isPending?.(card)) restore(card);
      });
    }

    async function open(card, url) {
      if (!card || !url || isEditing(card) || options.isPending?.(card)) return;
      closeOthers(card);
      originals.set(card, card.innerHTML);
      editingIds.add(getId(card));
      card.dataset.quickEditing = '1';
      card.innerHTML = options.loadingHtml || '<div class="text-center text-muted small py-4">Cargando edicion...</div>';
      const request = nextRequest(card);
      try {
        const response = await fetch(url, {
          credentials: 'same-origin',
          signal: request.controller.signal,
          headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
        });
        const data = await readJson(response);
        if (!card.isConnected || requestVersions.get(card) !== request.version) return;
        if (!response.ok || !data.ok || !data.html) throw new Error();
        card.innerHTML = data.html;
        options.initComponents?.(card);
        card.querySelector('input:not([type="hidden"]), select, textarea')?.focus();
      } catch (error) {
        if (error.name === 'AbortError' || !card.isConnected || requestVersions.get(card) !== request.version) return;
        restore(card);
        options.showError?.(card, options.loadError || 'No se pudo cargar la edicion rapida.');
      }
    }

    async function submit(form) {
      const card = form.closest(options.cardSelector);
      if (!card || options.isPending?.(card)) return;
      options.setPending?.(card, true);
      form.dataset.pending = 'true';
      form.setAttribute('aria-busy', 'true');
      const request = nextRequest(card);
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          credentials: 'same-origin',
          signal: request.controller.signal,
          headers: {'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
          body: new FormData(form),
        });
        const data = await readJson(response);
        if (!card.isConnected || requestVersions.get(card) !== request.version) return;
        if (String(data.id || getId(card)) !== String(getId(card))) throw new Error();
        if (response.ok && data.ok && data.html) {
          options.setPending?.(card, false);
          if (!replaceCard(card, data.html)) throw new Error();
          originals.delete(card);
          editingIds.delete(getId(card));
          return;
        }
        if (data.html) {
          card.innerHTML = data.html;
          options.initComponents?.(card);
          card.querySelector('.is-invalid, input, select')?.focus();
          return;
        }
        throw new Error();
      } catch (error) {
        if (error.name === 'AbortError' || !card.isConnected || requestVersions.get(card) !== request.version) return;
        options.showError?.(card, options.saveError || 'No se pudo guardar la edicion rapida.');
      } finally {
        if (card.isConnected && requestVersions.get(card) === request.version) {
          options.setPending?.(card, false);
          const currentForm = card.querySelector(options.formSelector);
          if (currentForm) {
            delete currentForm.dataset.pending;
            currentForm.setAttribute('aria-busy', 'false');
          }
        }
      }
    }

    document.addEventListener('click', (event) => {
      const opener = event.target.closest(options.openSelector);
      if (opener) {
        event.preventDefault();
        open(opener.closest(options.cardSelector), options.getUrl(opener));
        return;
      }
      const cancel = event.target.closest(options.cancelSelector);
      if (cancel) {
        event.preventDefault();
        const card = cancel.closest(options.cardSelector);
        if (!options.isPending?.(card)) restore(card);
      }
    });
    document.addEventListener('submit', (event) => {
      const form = event.target.closest(options.formSelector);
      if (form) {
        event.preventDefault();
        submit(form);
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const form = event.target.closest(options.formSelector);
      if (!form) return;
      event.preventDefault();
      const card = form.closest(options.cardSelector);
      if (!options.isPending?.(card)) restore(card);
    });
    return { open, restore, isEditing };
  };
})();
