// Privacy regression: the homepage must not connect to YouTube/Google merely to show a video preview.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const homepage = readFileSync(new URL('../../docs/index.html', `file://${__filename}`), 'utf8');

test('video preview uses a first-party CSS label rather than an external thumbnail', () => {
  assert.match(homepage, /class="demo-preview-label"/);
  assert.doesNotMatch(homepage, /<img[^>]+src=["']https?:\/\/(?:i\.ytimg\.com|img\.youtube\.com)\//i);
  assert.doesNotMatch(homepage, /<iframe[^>]+(?:youtube\.com|youtube-nocookie\.com)/i);
});

test('YouTube navigation is still explicit and opens in a separate tab', () => {
  assert.match(homepage, /class="demo-preview"[^>]+href="https:\/\/youtu\.be\/_LJ8tCLHrO0"[^>]+target="_blank"[^>]+rel="noopener noreferrer"/);
});
