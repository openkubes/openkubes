/* Adapted from openkubes-console-carousel.js in the supplied V2 package.
 * Retains path-prefix support, lifecycle guards and keyboard focus wrapping. */
(function () {
  'use strict';
  function init() {
    var root = document.getElementById('ok-home-console-en');
    if (!root || root.dataset.okConsoleReady === '1') return;
    root.dataset.okConsoleReady = '1';
    var dialog = root.querySelector('[data-ok-console-dialog]');
    var big = root.querySelector('[data-ok-console-big]');
    var title = root.querySelector('[data-ok-console-title]');
    var count = root.querySelector('[data-ok-console-count]');
    var buttons = Array.from(root.querySelectorAll('[data-ok-console-index]'));
    // Resolve from the actual thumbnails so modal URLs also work under a path prefix.
    var urls = buttons.map(function (btn) { return btn.querySelector('img').src; });
    var titles = buttons.map(function (btn) { return btn.getAttribute('aria-label'); });
    var pos = 0;
    function render(i) {
      pos = (i + urls.length) % urls.length;
      big.src = urls[pos];
      big.alt = 'OpenKubes Console – ' + titles[pos];
      title.textContent = titles[pos];
      count.textContent = (pos + 1) + ' / ' + urls.length;
    }
    buttons.forEach(function (btn, i) {
      btn.addEventListener('click', function () {
        if (typeof dialog.showModal === 'function') {
          render(i);
          dialog.showModal();
        } else {
          window.open(urls[i], '_blank', 'noopener');
        }
      });
    });
    var closeButton = root.querySelector('[data-ok-console-close]');
    var nextButton = root.querySelector('[data-ok-console-next]');
    root.querySelector('[data-ok-console-prev]').addEventListener('click', function () { render(pos - 1); });
    nextButton.addEventListener('click', function () { render(pos + 1); });
    closeButton.addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener('keydown', function (e) {
      if (e.key === 'Tab' && e.shiftKey && document.activeElement === closeButton) {
        e.preventDefault(); nextButton.focus();
      } else if (e.key === 'Tab' && !e.shiftKey && document.activeElement === nextButton) {
        e.preventDefault(); closeButton.focus();
      } else if (e.key === 'ArrowLeft') { e.preventDefault(); render(pos - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); render(pos + 1); }
    });
    // Native dialog provides Escape handling, background inertness and focus restoration.
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  if (typeof document$ !== 'undefined' && document$ && typeof document$.subscribe === 'function') {
    document$.subscribe(init);
  }
})();
