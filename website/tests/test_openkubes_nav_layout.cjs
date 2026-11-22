'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.join(__dirname, '../assets/openkubes-navigation.css'), 'utf8');

test('wide header uses a non-wrapping three-column layout', () => {
  const wide = css.match(/@media\s*\(min-width:\s*1080px\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(wide, 'wide desktop breakpoint required');
  assert.match(wide[1], /grid-template-columns:\s*max-content minmax\(0,1fr\) max-content/);
  assert.match(wide[1], /\.ok-global-nav__links\s*\{[^}]*flex-wrap:\s*nowrap/s);
  assert.match(wide[1], /\.ok-global-nav__socials\s*\{[^}]*flex-wrap:\s*nowrap/s);
});

test('sticky navigation and compact mobile behavior remain available', () => {
  assert.match(css, /\.ok-global-nav--material\s*\{[^}]*position:\s*sticky/s);
  assert.match(css, /@media\(max-width:720px\)/);
  assert.match(css, /\.ok-global-nav\{[^}]*position:sticky;top:0/s);
});
