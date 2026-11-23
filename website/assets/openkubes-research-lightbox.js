/* OpenKubes diagram lightbox, shared across Architecture, Research, Open Universe,
 * Tutorials and Blog. Existing Markdown image links remain functional on GitHub
 * and with JavaScript disabled. Only images in the article content are enhanced.
 */
(function () {
  "use strict";

  function isSvgUrl(url) {
    try {
      return /\.svg$/i.test(new URL(url, document.baseURI).pathname);
    } catch (_) {
      return false;
    }
  }

  function initialize() {
    if (!("HTMLDialogElement" in window)) return;

    // Do not touch the global navigation, logo, social icons or other site chrome.
    const candidates = document.querySelectorAll(".md-content img[src]");
    const diagrams = Array.from(candidates).filter(function (img) {
      if (!isSvgUrl(img.getAttribute("src"))) return false;
      if (img.closest('[data-ok-svg-lightbox="off"]')) return false;
      const anchor = img.closest("a[href]");
      // On overview pages a linked thumbnail must still navigate to its article.
      if (anchor && !isSvgUrl(anchor.getAttribute("href"))) return false;
      return true;
    });
    if (!diagrams.length) return;

    const dialog = document.createElement("dialog");
    dialog.className = "ok-research-lightbox";
    dialog.setAttribute("aria-label", "Enlarged SVG diagram");
    const inner = document.createElement("div");
    inner.className = "ok-research-lightbox__inner";
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "ok-research-lightbox__close";
    closeButton.textContent = "Close ×";
    closeButton.setAttribute("aria-label", "Close enlarged diagram");
    const image = document.createElement("img");
    image.className = "ok-research-lightbox__image";
    image.alt = "Enlarged diagram";
    inner.append(closeButton, image);
    dialog.append(inner);
    document.body.append(dialog);

    let trigger = null;
    function close() { dialog.close(); }
    function open(source, element, alt) {
      trigger = element;
      image.alt = alt || "Enlarged SVG diagram";
      image.src = source;
      dialog.showModal();
      closeButton.focus();
    }

    closeButton.addEventListener("click", close);
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) close();
    });
    dialog.addEventListener("close", function () {
      image.removeAttribute("src");
      if (trigger && trigger.isConnected) trigger.focus({ preventScroll: true });
      trigger = null;
    });

    diagrams.forEach(function (img) {
      const anchor = img.closest("a[href]");
      const source = anchor ? anchor.href : img.src;
      const alt = img.alt || "SVG architecture diagram";
      if (anchor) {
        anchor.setAttribute("aria-label", "Enlarge diagram: " + alt);
        anchor.addEventListener("click", function (event) {
          // Keep modifiers and contextual actions native: new tabs remain possible.
          if (event.defaultPrevented || event.button !== 0 ||
              event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          open(source, anchor, alt);
        });
      } else {
        // A plain Markdown image becomes a keyboard-operable control.
        img.tabIndex = 0;
        img.setAttribute("role", "button");
        img.setAttribute("aria-label", "Enlarge diagram: " + alt);
        img.classList.add("ok-svg-lightbox-trigger");
        img.addEventListener("click", function () { open(source, img, alt); });
        img.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open(source, img, alt);
          }
        });
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
