// Video navigation is explicit; no third-party thumbnail or iframe is loaded.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const homepage = readFileSync(new URL('../../docs/index.html', `file://${__filename}`), 'utf8');
const getting = readFileSync(new URL('../../docs/getting-started/README.md', `file://${__filename}`), 'utf8');
test('homepage and onboarding do not embed YouTube resources', () => {
  for (const source of [homepage, getting]) {
    assert.doesNotMatch(source, /<img[^>]+src=["']https?:\/\/(?:i\.ytimg\.com|img\.youtube\.com)\//i);
    assert.doesNotMatch(source, /<iframe[^>]+(?:youtube\.com|youtube-nocookie\.com)/i);
  }
  assert.match(getting, /\[video walkthrough on YouTube\]\(https:\/\/youtu\.be\/_LJ8tCLHrO0\)/);
});
test('external demo is a link, not an embedded third-party resource', () => {
  assert.match(homepage, /href="https:\/\/demo\.kubernautic\.com\/" target="_blank" rel="noopener noreferrer"/);
  assert.doesNotMatch(homepage, /<(?:iframe|img|script)[^>]+src=["']https:\/\/demo\.kubernautic\.com/i);
});
