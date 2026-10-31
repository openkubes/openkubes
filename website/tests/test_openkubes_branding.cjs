// Dependency-free behavior tests for the supplied typewriter adaptation.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(new URL('../assets/openkubes-branding.js', `file://${__filename}`), 'utf8');

function setup({ reduced = false, homepage = true } = {}) {
  const text = { textContent: 'Contracts First.' };
  const cursor = { hidden: true };
  const button = { hidden: true, textContent: 'Pause animation', addEventListener(_, fn) { this.click = fn; } };
  const root = { dataset: {}, isConnected: true, querySelector(selector) {
    return ({ '[data-ok-typed]': text, '[data-ok-cursor]': cursor, '[data-ok-pause]': button })[selector];
  } };
  const listeners = new Map();
  const motion = { matches: reduced, addEventListener(_, fn) { this.change = fn; }, removeEventListener() {} };
  const timers = new Map();
  let nextId = 0, observe;
  const document = { readyState: 'complete', hidden: false,
    getElementById: () => homepage ? root : null,
    addEventListener: (event, fn) => listeners.set(event, fn),
    removeEventListener: event => listeners.delete(event),
  };
  const window = { matchMedia: () => motion,
    setTimeout: fn => { timers.set(++nextId, fn); return nextId; },
    clearTimeout: id => timers.delete(id),
    IntersectionObserver: function (fn) { observe = fn; this.observe = () => {}; this.disconnect = () => {}; },
  };
  let reinit;
  vm.runInNewContext(source, { window, document, IntersectionObserver: window.IntersectionObserver,
    document$: { subscribe: fn => { reinit = fn; } } });
  function tick() {
    const entry = timers.entries().next().value;
    assert.ok(entry, 'animation has a scheduled step');
    timers.delete(entry[0]); entry[1]();
  }
  return { text, cursor, button, root, motion, timers, tick, reinit,
    visibility(hidden) { document.hidden = hidden; listeners.get('visibilitychange')(); },
    intersection(visible) { observe([{ isIntersecting: visible }]); },
  };
}

test('cycles through all four principles and returns to the first', () => {
  const h = setup(), seen = new Set();
  for (let i = 0; i < 240; i++) { seen.add(h.text.textContent); h.tick(); }
  for (const phrase of ['Contracts First.', 'Evidence Driven.', 'Human Controlled.', 'Sovereign by Design.']) {
    assert.ok(seen.has(phrase), phrase);
  }
  assert.equal(h.timers.size, 1);
});

test('pause leaves a full principle, stops timers, and resumes on request', () => {
  const h = setup(); h.tick(); h.tick();
  assert.notEqual(h.text.textContent, 'Contracts First.');
  h.button.click();
  assert.equal(h.text.textContent, 'Contracts First.');
  assert.equal(h.timers.size, 0);
  assert.equal(h.cursor.hidden, true);
  assert.equal(h.button.textContent, 'Resume animation');
  h.button.click();
  assert.equal(h.timers.size, 1);
  assert.equal(h.button.textContent, 'Pause animation');
});

test('reduced motion shows every principle without timers or controls', () => {
  const h = setup({ reduced: true });
  assert.equal(h.text.textContent, 'Contracts First. Evidence Driven. Human Controlled. Sovereign by Design.');
  assert.equal(h.timers.size, 0);
  assert.equal(h.cursor.hidden, true);
  assert.equal(h.button.hidden, true);
});

test('responds to live reduced-motion changes while preserving user pause', () => {
  const h = setup(); h.button.click();
  h.motion.matches = true; h.motion.change();
  assert.equal(h.timers.size, 0);
  assert.match(h.text.textContent, /Sovereign by Design\./);
  h.motion.matches = false; h.motion.change();
  assert.equal(h.button.hidden, false);
  assert.equal(h.timers.size, 0);
  h.button.click(); assert.equal(h.timers.size, 1);
});

test('suspends hidden/offscreen work and avoids duplicate initialization', () => {
  const h = setup(); h.reinit(); assert.equal(h.timers.size, 1);
  h.intersection(false); assert.equal(h.timers.size, 0);
  h.visibility(true); h.intersection(true); assert.equal(h.timers.size, 0);
  h.visibility(false); assert.equal(h.timers.size, 1);
  h.root.isConnected = false; h.tick(); assert.equal(h.timers.size, 0);
});

test('documentation pages schedule no animation', () => {
  const h = setup({ homepage: false }); assert.equal(h.timers.size, 0);
});
