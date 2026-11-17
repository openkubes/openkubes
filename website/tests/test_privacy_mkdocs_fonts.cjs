// Privacy regression guard for the MkDocs Material site configuration.
// Verify that remote Google Fonts are disabled in the version-controlled theme settings.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const config = readFileSync(new URL('../../mkdocs.yml', `file://${__filename}`), 'utf8');
test('Material theme disables externally hosted fonts', () => {
  const theme = config.match(/^theme:\s*\n((?:^[ \t]+[^\n]*\n)*)/m)?.[1] ?? '';
  assert.match(theme, /^  name:\s*material\s*$/m);
  assert.match(theme, /^  font:\s*false\s*$/m);
});
