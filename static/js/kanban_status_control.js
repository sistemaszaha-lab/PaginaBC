window.initKanbanStatusControl = function(container) {
  if (!container) return;
  container.addEventListener('click', e => {
    const btn = e.target.closest('.kanban-status-control__option');
    if (btn) {
      const optionValue = btn.dataset.statusOption;
      // Encuentra el card superior que lo contiene
      const card = btn.closest('.card, .operaciones-card, .garantia-card');
      if (!card || btn.disabled || btn.classList.contains('active')) return;
      
      // Busca un select interno que tenga clase .d-none dentro del mismo contenedor
      const statusControl = btn.closest('.kanban-status-control');
      if (statusControl) {
        const select = statusControl.querySelector('select.d-none');
        if (select) {
          select.value = optionValue;
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
    }
  });
};
