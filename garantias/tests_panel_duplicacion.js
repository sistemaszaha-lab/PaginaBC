// Ejecuta el script completo del panel con DOM y transporte simulados.
// No sustituye una prueba en navegador con sus bibliotecas y eventos reales.
const GLib = imports.gi.GLib;
const System = imports.system;
const ByteArray = imports.byteArray;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

class Element {
  constructor(dataset = {}) {
    this.dataset = dataset;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.className = '';
    this.parentElement = null;
  }
  matches(selector) {
    return selector.split(',').some(part => {
      const match = part.trim().match(/^\[data-([\w-]+)="([^"]+)"\]$/);
      return match && this.dataset[match[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())] === match[2];
    });
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  appendChild(child) { this.children.push(child); child.parentElement = this; }
  setAttribute() {}
  replaceWith(next) {
    const parent = this.parentElement;
    parent.children[parent.children.indexOf(this)] = next;
    next.parentElement = parent;
    this.parentElement = null;
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
}

const root = new Element();
const original = new Element({garantiaCard: '1', garantiaId: '101'});
original.id = 'garantia-101';
const other = new Element({garantiaCard: '1', garantiaId: '202'});
other.id = 'garantia-202';
root.appendChild(original);
root.appendChild(other);
const button = new Element({garantiaSendCuenta: '1', sendUrl: '/garantias/101/enviar-a-cuenta-gastos/'});
original.appendChild(button);
const config = {textContent: JSON.stringify({estadoUpdateUrl: '/estado/', inlineCreateUrl: '/crear/', inlineFormUrl: '/form/'})};
const documentListeners = {};
globalThis.document = {
  body: new Element(),
  querySelector: selector => selector === '.garantias-board' ? root : null,
  getElementById: id => id === 'panel-garantias-config' ? config : null,
  createElement: () => new Element(),
  addEventListener: (type, handler) => (documentListeners[type] ||= []).push(handler),
};
const requests = [];
// En GJS, window es un alias de globalThis.
Object.assign(globalThis, {
  createKanbanQuickEditController() {},
  setTimeout() {},
  csrfFetch(url, options) {
    return new Promise(resolve => requests.push({url, options, resolve}));
  },
});

const source = ByteArray.toString(GLib.file_get_contents(ARGV[0])[1]);
function click(target) {
  const event = {target, preventDefault() {}, stopPropagation() {}};
  for (const handler of root.listeners.click || []) handler(event);
  for (const handler of documentListeners.click || []) handler(event);
}
function cardIds() {
  return root.querySelectorAll('[data-garantia-card="1"]').map(card => card.id).join(',');
}
async function settle() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}
function reply(request, creada) {
  request.resolve({ok: true, headers: {get: () => 'application/json'}, json: async () => ({ok: true, creada, cuenta_id: 301})});
}

const loop = new GLib.MainLoop(null, false);
GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
(async () => {
  (0, eval)(source);
  const handlersBefore = root.listeners.click.length;
  (0, eval)(source);
  assert(root.listeners.click.length === handlersBefore, 'Inicialización repetida registró más handlers');
  const before = cardIds();
  click(button);
  click(button);
  assert(requests.length === 1, 'Doble clic generó más de una petición');
  assert(requests[0].url === button.dataset.sendUrl && requests[0].options.method === 'POST', 'Petición inesperada');
  assert(cardIds() === before, 'Tarjetas cambiaron durante el envío');
  reply(requests[0], true);
  await settle();
  assert(cardIds() === before && root.children[0] === original && root.children[1] === other, 'Respuesta AJAX duplicó o sustituyó tarjetas');
  assert(original.querySelectorAll('[data-garantia-send-cuenta-status="1"]').length === 1, 'No se actualizó el botón');
  assert(original.querySelectorAll('[data-garantia-send-cuenta="1"]').length === 0, 'Botón de envío sigue presente');
  assert(requests.length === 1, 'La respuesta produjo una petición adicional');
  // Simular otro envío autorizado de una cuenta ya existente.
  original.children[0].replaceWith(button);
  button.dataset.pending = '0';
  button.disabled = false;
  click(button);
  assert(requests.length === 2, 'No se ejecutó la repetición de diagnóstico');
  reply(requests[1], false);
  await settle();
  assert(cardIds() === before, 'Respuesta idempotente duplicó tarjetas');
  assert(original.querySelectorAll('[data-garantia-send-cuenta-status="1"]').length === 1, 'Estado enviado duplicado');
  print('OK: IDs 101,202 intactos; doble clic, respuesta AJAX, reenvío e inicialización repetida');
})().then(() => loop.quit()).catch(error => {
  printerr(String(error) + '\n' + (error.stack || ''));
  System.exit(1);
});
return GLib.SOURCE_REMOVE;
});
loop.run();
