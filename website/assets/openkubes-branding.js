/* Adapted from the OpenKubes MkDocs branding V1 package. No dependencies. */
(function () {
  'use strict';
  function initializeTypewriter(root) {
    if (!root || root.dataset.okInitialized === '1') return;
    root.dataset.okInitialized = '1';
    var text = root.querySelector('[data-ok-typed]');
    var cursor = root.querySelector('[data-ok-cursor]');
    var button = root.querySelector('[data-ok-pause]');
    if (!text || !cursor || !button) return;
    var phrases = ['Contracts First.', 'Evidence Driven.', 'Human Controlled.', 'Sovereign by Design.'];
    var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    var index = 0, position = phrases[0].length, deleting = false, timer = null;
    var inView = true, paused = false, nextDelay = 1900;
    function clearTimer() {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    }
    function schedule(ms) {
      nextDelay = ms;
      clearTimer();
      if (root.isConnected && inView && !document.hidden && !paused && !motion.matches) {
        timer = window.setTimeout(step, ms);
      }
    }
    function step() {
      timer = null;
      if (!root.isConnected) { cleanup(); return; }
      if (!inView || document.hidden || paused || motion.matches) return;
      var phrase = phrases[index];
      if (!deleting && position < phrase.length) {
        text.textContent = phrase.slice(0, ++position);
        schedule(80);
      } else if (!deleting) {
        deleting = true;
        schedule(1900);
      } else if (position > 0) {
        text.textContent = phrase.slice(0, --position);
        schedule(35);
      } else {
        deleting = false;
        index = (index + 1) % phrases.length;
        schedule(250);
      }
    }
    function updateMotion() {
      clearTimer();
      index = 0; position = phrases[0].length; deleting = false;
      // All principles stay visible when motion is reduced, including without a screen reader.
      text.textContent = motion.matches ? phrases.join(' ') : phrases[0];
      button.hidden = motion.matches;
      cursor.hidden = motion.matches || paused;
      schedule(1900);
    }
    function onVisibility() {
      if (!root.isConnected) { cleanup(); return; }
      if (document.hidden) clearTimer(); else schedule(1900);
    }
    button.addEventListener('click', function () {
      paused = !paused;
      var label = paused ? 'Resume animation' : 'Pause animation';
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
      button.setAttribute('data-paused', String(paused));
      cursor.hidden = paused;
      // Keep the current text, phrase index and typing/deleting direction intact.
      if (paused) clearTimer();
      else schedule(nextDelay);
    });
    var observer;
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(function (entries) {
        inView = !!(entries[0] && entries[0].isIntersecting);
        if (inView) schedule(1900); else clearTimer();
      }, {threshold: 0.05});
      observer.observe(root);
    }
    function cleanup() {
      clearTimer();
      if (observer) observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      motion.removeEventListener('change', updateMotion);
    }
    document.addEventListener('visibilitychange', onVisibility);
    motion.addEventListener('change', updateMotion);
    updateMotion();
  }
  function init() {
    initializeTypewriter(document.getElementById('ok-mkdocs-philosophy'));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  if (typeof document$ !== 'undefined' && document$ && typeof document$.subscribe === 'function') {
    document$.subscribe(init);
  }
})();
