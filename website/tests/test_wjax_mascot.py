"""Check the W-JAX mascot's accessible fallback and motion-preference behavior."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / 'docs/ai/agentic-operations-hands-on.md'


class MascotHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.template_depth = 0
        self.videos = []
        self.poster = None
        self.scripts = []
        self.script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'template':
            self.template_depth += 1
        if tag == 'video':
            self.videos.append((attrs, self.template_depth))
        if tag == 'img' and attrs.get('id') == 'wjax-mascot-poster':
            self.poster = attrs
        if tag == 'script':
            self.script = ''

    def handle_endtag(self, tag):
        if tag == 'template':
            self.template_depth -= 1
        if tag == 'script':
            self.scripts.append(self.script)
            self.script = None

    def handle_data(self, data):
        if self.script is not None:
            self.script += data


class MascotTests(unittest.TestCase):
    def setUp(self):
        self.html = MascotHTML()
        self.html.feed(PAGE.read_text())

    def test_accessible_inert_player_and_static_fallback(self):
        self.assertEqual(len(self.html.videos), 1)
        video, template_depth = self.html.videos[0]
        self.assertEqual(template_depth, 1)  # No eager autoplay before preference detection.
        for attribute in ('controls', 'muted', 'playsinline', 'loop', 'autoplay'):
            self.assertIn(attribute, video)
        self.assertEqual(video['preload'], 'none')
        self.assertTrue(video['aria-label'])
        self.assertEqual(video['aria-describedby'], 'wjax-mascot-description')
        self.assertEqual(video['poster'], self.html.poster['src'])
        self.assertTrue(self.html.poster['alt'])
        self.assertTrue((ROOT / 'docs' / video['poster'].lstrip('/')).is_file())

    @unittest.skipUnless(shutil.which('node'), 'Node is needed to exercise the inline browser script')
    def test_motion_preferences_before_insertion_and_when_changed(self):
        script = next(script for script in self.html.scripts if 'wjax-mascot-player' in script)
        # Execute the shipped script with a minimal DOM/media-query fixture. Assert
        # effective autoplay at insertion, and later preference changes/manual pause.
        harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = SOURCE;
for (const mode of ['normal', 'reduced', 'unknown', 'legacy']) {
  const player = {autoplay: true, paused: true, muted: false, pauseCount: 0,
    removeAttribute(name) { if (name === 'autoplay') this.autoplay = false; },
    pause() { this.paused = true; this.pauseCount++; }};
  let inserted = false;
  let change;
  const motion = {matches: mode === 'reduced'};
  if (mode === 'legacy') motion.addListener = callback => { change = callback; };
  else motion.addEventListener = (name, callback) => {
    assert.equal(name, 'change'); change = callback;
  };
  const poster = {replaceWith(video) {
    assert.equal(video, player);
    assert.equal(video.muted, true);
    assert.equal(video.autoplay, mode === 'normal' || mode === 'legacy');
    inserted = true;
  }};
  const template = {content: {querySelector: () => ({cloneNode: () => player})}};
  const document = {getElementById(id) {
    return id === 'wjax-mascot-poster' ? poster : template;
  }};
  const window = mode === 'unknown' ? {} : {matchMedia(query) {
    assert.equal(query, '(prefers-reduced-motion: reduce)'); return motion;
  }};
  vm.runInNewContext(script, {document, window});
  assert.equal(inserted, true);
  if (change) {
    player.paused = false; // Playback was either automatic or explicitly started.
    motion.matches = true; change();
    assert.equal(player.autoplay, false);
    assert.equal(player.paused, true);
    assert.equal(player.pauseCount, 1);
    motion.matches = false; change();
    assert.equal(player.paused, true); // Do not restart a user-paused animation.
  }
}
console.log('Motion preference lifecycle: PASS');
'''
        result = subprocess.run(['node', '-e', harness.replace('SOURCE', json.dumps(script))],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
