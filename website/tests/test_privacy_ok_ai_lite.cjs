// Static regression for the documented browser-only OK AI Lite release boundary.
// A browser HAR test is still required before claiming no runtime data transfer.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');

const source = readFileSync(new URL('../assets/ok-ai-lite-preview.js', `file://${__filename}`), 'utf8');
const blockedPatterns = [
  /\bfetch\s*\(/i,
  /\bXMLHttpRequest\b/i,
  /\bWebSocket\b/i,
  /\bEventSource\b/i,
  /\bsendBeacon\s*\(/i,
  /\b(?:localStorage|sessionStorage|indexedDB|caches)\b/i,
  /\bdocument\s*\.\s*cookie\b/i,
  /\b(?:navigator|window)\s*\.\s*serviceWorker\b/i,
  /\b(?:eval|Function)\s*\(/i,
  /\b(?:importScripts)\s*\(/i,
];

test('Lite widget does not use network APIs, storage or dynamic code execution', () => {
  for (const pattern of blockedPatterns) {
    assert.doesNotMatch(source, pattern, `Unsupported browser capability: ${pattern}`);
  }
});

test('Lite continues to disclose that responses are static and unsupported questions are refused', () => {
  assert.match(source, /No AI backend/);
  assert.match(source, /Beta 1 Lite only answers/);
  assert.match(source, /Object\.freeze\(\{/);
  assert.match(source, /Object\.prototype\.hasOwnProperty\.call\(supported, key\)/);
});

test('User-supplied question content is assigned with textContent, not HTML', () => {
  assert.match(source, /el\.textContent\s*=\s*value/);
  assert.doesNotMatch(source, /\.innerHTML\s*=\s*(?:question|value|input\.value)/);
});

test('An external link to a pinned GitHub source is navigational only', () => {
  assert.match(source, /a\.href\s*=\s*sourceUrl/);
  assert.match(source, /a\.rel\s*=\s*"noopener noreferrer"/);
});
