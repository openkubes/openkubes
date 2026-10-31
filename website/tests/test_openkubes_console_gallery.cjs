const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(require.resolve('../assets/openkubes-console-gallery.js'), 'utf8');

function setup({ prefix = '/', native = true, present = true } = {}) {
  const document = { readyState: 'complete' };
  function element() {
    const handlers = {};
    return { handlers, focus() { document.activeElement = this; }, addEventListener(event, fn) {
      (handlers[event] ||= []).push(fn);
    }, emit(event, arg = {}) { (handlers[event] || []).forEach(fn => fn(arg)); } };
  }
  const titles = ['AI Agent Catalog', 'Cluster Inventory', 'AI Diagnostics Preview'];
  const files = ['agent-catalog', 'cluster-inventory', 'ai-diagnostics-preview'];
  const buttons = files.map((file, i) => Object.assign(element(), {
    querySelector: () => ({ src: `https://example.test${prefix}assets/images/console/ok-console-${file}.webp` }),
    getAttribute: () => titles[i],
  }));
  const dialog = Object.assign(element(), { close() { this.open = false; } });
  if (native) dialog.showModal = function () { this.open = true; };
  const big = {}, title = {}, count = {}, prev = element(), next = element(), close = element();
  const nodes = { '[data-ok-console-dialog]': dialog, '[data-ok-console-big]': big,
    '[data-ok-console-title]': title, '[data-ok-console-count]': count,
    '[data-ok-console-prev]': prev, '[data-ok-console-next]': next, '[data-ok-console-close]': close };
  const root = { dataset: {}, querySelector: s => nodes[s], querySelectorAll: () => buttons };
  const opened = [];
  let init;
  document.getElementById = () => present ? root : null;
  vm.runInNewContext(source, { document,
    window: { open: (...args) => opened.push(args) }, document$: { subscribe: fn => { init = fn; } } });
  return { buttons, dialog, big, title, count, prev, next, close, opened, init, document };
}

test('opens the selected original screenshot with matching title, alt and count', () => {
  const h = setup();
  for (let i = 0; i < 3; i++) {
    h.buttons[i].emit('click');
    assert.equal(h.dialog.open, true);
    assert.equal(h.big.src, h.buttons[i].querySelector().src);
    assert.equal(h.title.textContent, h.buttons[i].getAttribute());
    assert.equal(h.big.alt, 'OpenKubes Console – ' + h.title.textContent);
    assert.equal(h.count.textContent, `${i + 1} / 3`);
    h.close.emit('click'); assert.equal(h.dialog.open, false);
  }
});

test('previous/next and keyboard arrows wrap without changing focus', () => {
  const h = setup(); h.buttons[0].emit('click');
  h.prev.emit('click'); assert.equal(h.count.textContent, '3 / 3');
  h.next.emit('click'); assert.equal(h.count.textContent, '1 / 3');
  let prevented = 0;
  h.dialog.emit('keydown', { key: 'ArrowRight', preventDefault() { prevented++; } });
  assert.equal(h.count.textContent, '2 / 3');
  h.dialog.emit('keydown', { key: 'ArrowLeft', preventDefault() { prevented++; } });
  assert.equal(h.count.textContent, '1 / 3'); assert.equal(prevented, 2);
});

test('backdrop clicks close; image clicks leave the viewer open', () => {
  const h = setup(); h.buttons[0].emit('click');
  h.dialog.emit('click', { target: h.big }); assert.equal(h.dialog.open, true);
  h.dialog.emit('click', { target: h.dialog }); assert.equal(h.dialog.open, false);
});

test('modal paths resolve from thumbnails under a hosting prefix', () => {
  const h = setup({ prefix: '/review/' }); h.buttons[1].emit('click');
  assert.equal(h.big.src, 'https://example.test/review/assets/images/console/ok-console-cluster-inventory.webp');
});

test('fallback opens an image safely and reinitialization does not duplicate handlers', () => {
  const h = setup({ native: false }); h.init(); h.init(); h.buttons[2].emit('click');
  assert.equal(h.opened.length, 1);
  assert.equal(h.opened[0][0], h.buttons[2].querySelector().src);
  assert.equal(h.opened[0][2], 'noopener');
});

test('other pages do not initialize the gallery', () => {
  assert.doesNotThrow(() => setup({ present: false }));
});

test('Tab and Shift+Tab keep focus cycling within the modal controls', () => {
  const h = setup(); h.buttons[0].emit('click');
  let prevented = 0;
  h.close.focus();
  h.dialog.emit('keydown', { key: 'Tab', shiftKey: true, preventDefault() { prevented++; } });
  assert.equal(h.document.activeElement, h.next);
  h.dialog.emit('keydown', { key: 'Tab', shiftKey: false, preventDefault() { prevented++; } });
  assert.equal(h.document.activeElement, h.close);
  assert.equal(prevented, 2);
});
