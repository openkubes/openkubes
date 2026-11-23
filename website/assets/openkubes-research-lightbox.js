/* OpenKubes Research: progressively enhance native SVG links into an accessible lightbox.
 * Keep the plain relative Markdown link functional on GitHub and without JavaScript.
 */
(function () {
  "use strict";
  function initialize() {
    if (!("HTMLDialogElement" in window)) return;
    const selector = 'a[href$="policy-bounded-autonomy.svg"]:has(> img)';
    const links = document.querySelectorAll(selector);
    if (!links.length) return;

    const dialog = document.createElement("dialog");
    dialog.className = "ok-research-lightbox";
    dialog.setAttribute("aria-label", "Policy-Bounded Autonomy diagram enlarged");
    const inner = document.createElement("div");
    inner.className = "ok-research-lightbox__inner";
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "ok-research-lightbox__close";
    closeButton.textContent = "Close ×";
    closeButton.setAttribute("aria-label", "Close enlarged diagram");
    const image = document.createElement("img");
    image.alt = "Policy-Bounded Autonomy architecture diagram, enlarged";
    image.className = "ok-research-lightbox__image";
    inner.append(closeButton, image);
    dialog.append(inner);
    document.body.append(dialog);

    let trigger = null;
    function close() { dialog.close(); }
    closeButton.addEventListener("click", close);
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) close();
    });
    dialog.addEventListener("close", function () {
      if (trigger && trigger.isConnected) trigger.focus({ preventScroll: true });
      trigger = null;
      image.removeAttribute("src");
    });

    links.forEach(function (link) {
      link.setAttribute("aria-label", "Enlarge architecture diagram in a popup");
      link.addEventListener("click", function (event) {
        // Preserve browser-native open-in-new-tab and context-menu functionality.
        if (event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        trigger = link;
        image.src = link.href;
        dialog.showModal(); // Native Escape behavior and focus isolation.
        closeButton.focus();
      });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
