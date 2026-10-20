/* Beta 1 Lite: approved-host curated browser UI. No API calls, AI or execution. */
(function () {
  "use strict";
  if (!["preview.openkubes.org", "openkubes.org"].includes(window.location.hostname)) return;
  if (document.getElementById("okai-floating-demo")) return;

  // Release-reviewed fixed text. No model-generated content is ever displayed.
  // This is a static curated Lite answer, NOT a live gateway.
  var sourceUrl = "https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md";
  var approvedAnswer = "OpenKubes Local (ok-local) is a fully automated local development environment provided by the OpenKubes project.";
  var secondAnswer = "Yes. OpenKubes provides a fully automated local development environment called ok-local.";
  var supported = Object.freeze({
    "what is openkubes local": approvedAnswer,
    "what is ok local": approvedAnswer,
    "what is ok-local": approvedAnswer,
    "does openkubes provide a local development environment": secondAnswer
  });
  var unsupported = "Beta 1 Lite only answers a small set of reviewed questions. Please consult the official OpenKubes documentation.";
  var root = document.createElement("div");
  root.id = "okai-floating-demo";
  root.className = "okai-float";
  root.innerHTML = [
    '<button type="button" class="okai-launch" aria-label="Open curated OK AI Lite" aria-expanded="false" aria-controls="okai-float-panel">✦ <span>Ask OK AI</span><span class="okai-launch-tag">LITE</span></button>',
    '<section id="okai-float-panel" class="okai-panel" role="dialog" aria-modal="false" aria-label="OK AI curated documentation Lite" hidden>',
    '<header class="okai-panel-head"><span class="okai-symbol" aria-hidden="true">✦</span><span class="okai-heading"><strong>OK AI</strong><small>Documentation Q&A · Beta 1 Lite</small></span><button type="button" class="okai-close" aria-label="Close OK AI preview">×</button></header>',
    '<div class="okai-messages" role="log" aria-live="polite" aria-relevant="additions text"><div class="okai-bubble okai-assistant">Welcome to Beta 1 Lite. I can answer selected reviewed questions about OpenKubes Local.<small>Fixed reviewed replies · No live AI · No network requests</small></div></div>',
    '<div class="okai-suggestions"><button type="button" data-lite-question="What is OpenKubes Local?">What is OpenKubes Local?</button><button type="button" data-lite-question="Does OpenKubes provide a local development environment?">Local environment</button></div>',
    '<form class="okai-input-form"><label class="okai-visually-hidden" for="okai-floating-input">Documentation question</label><input id="okai-floating-input" type="text" maxlength="240" autocomplete="off" placeholder="Ask a reviewed question…" required><button type="submit" aria-label="Send question">Send</button></form>',
    '<p class="okai-disclaimer">Reviewed static answers · No AI backend · Do not enter secrets</p>',
    '</section>'
  ].join("");
  document.body.appendChild(root);

  var launch = root.querySelector(".okai-launch");
  var panel = root.querySelector(".okai-panel");
  var close = root.querySelector(".okai-close");
  var messages = root.querySelector(".okai-messages");
  var form = root.querySelector(".okai-input-form");
  var input = root.querySelector("#okai-floating-input");

  function bubble(value, role) {
    var el = document.createElement("div");
    el.className = "okai-bubble " + (role === "user" ? "okai-user" : "okai-assistant");
    // Never inject untrusted question text as HTML.
    el.textContent = value;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }
  function linkToSource(el) {
    var a = document.createElement("a");
    a.href = sourceUrl;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = "Review pinned documentation source ↗";
    el.appendChild(document.createElement("br"));
    el.appendChild(a);
  }
  function normalize(question) {
    if (typeof question !== "string" || !question.length || question.length > 240 ||
        /[\x00-\x1f\x7f]/.test(question)) return "";
    return question.trim().toLowerCase().replace(/\s+/g, " ").replace(/[?.!]$/, "").trim();
  }
  function send(question) {
    if (typeof question !== "string" || !question.trim()) return;
    bubble(question, "user");
    var key = normalize(question);
    // Strict allowlist. No regex topic inference, model calls, or generic fallback source claims.
    if (Object.prototype.hasOwnProperty.call(supported, key)) {
      linkToSource(bubble(supported[key], "assistant"));
    } else {
      bubble(unsupported, "assistant");
    }
  }
  function toggle(open) {
    panel.hidden = !open;
    launch.setAttribute("aria-expanded", String(open));
    launch.setAttribute("aria-label", open ? "Close curated OK AI Lite" : "Open curated OK AI Lite");
    if (open) input.focus();
    else launch.focus();
  }
  launch.addEventListener("click", function () { toggle(panel.hidden); });
  close.addEventListener("click", function () { toggle(false); });
  root.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) { event.preventDefault(); toggle(false); }
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var question = input.value;
    input.value = "";
    send(question);
    input.focus();
  });
  root.querySelectorAll("[data-lite-question]").forEach(function (button) {
    button.addEventListener("click", function () { send(button.getAttribute("data-lite-question")); });
  });
})();
