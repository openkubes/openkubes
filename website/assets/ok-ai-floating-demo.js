/* OK AI Preview UI demo. No network calls, no model, no telemetry. */
(function () {
  "use strict";
  if (window.location.hostname !== "preview.openkubes.org") return;
  if (document.getElementById("okai-floating-demo")) return;

  var docsUrl = "https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md";
  var root = document.createElement("div");
  root.id = "okai-floating-demo";
  root.className = "okai-float";
  root.innerHTML = [
    '<button type="button" class="okai-launch" aria-label="Open OK AI demo chat" aria-expanded="false" aria-controls="okai-float-panel">✦ <span>Ask OK AI</span><span class="okai-launch-tag">DEMO</span></button>',
    '<section id="okai-float-panel" class="okai-panel" role="dialog" aria-modal="false" aria-label="OK AI documentation demo" hidden>',
    '<header class="okai-panel-head"><span class="okai-symbol" aria-hidden="true">✦</span><span class="okai-heading"><strong>OK AI</strong><small>Documentation Assistant · UI Demo</small></span><button type="button" class="okai-close" aria-label="Close OK AI demo">×</button></header>',
    '<div class="okai-messages" role="log" aria-live="polite" aria-relevant="additions text"><div class="okai-bubble okai-assistant">Hi! I’m OK AI. Try a sample question about OpenKubes.<small>Demo only — answers are predefined, not AI-generated.</small></div></div>',
    '<div class="okai-suggestions"><button type="button" data-demo-question="How do I install OpenKubes Local on macOS?">Install OpenKubes Local</button><button type="button" data-demo-question="What are Agentic Operations?">Agentic Operations</button></div>',
    '<form class="okai-input-form"><label class="okai-visually-hidden" for="okai-floating-input">Your question</label><input id="okai-floating-input" maxlength="500" autocomplete="off" placeholder="Ask OK AI (demo)…" required /><button type="submit" aria-label="Send demo question">Send</button></form>',
    '<p class="okai-disclaimer">Preview-only UI demo · No AI backend · Do not enter secrets</p>',
    '</section>'
  ].join("");
  document.body.appendChild(root);

  var launch = root.querySelector(".okai-launch");
  var panel = root.querySelector(".okai-panel");
  var close = root.querySelector(".okai-close");
  var messages = root.querySelector(".okai-messages");
  var form = root.querySelector(".okai-input-form");
  var input = root.querySelector("#okai-floating-input");

  function toggle(open) {
    panel.hidden = !open;
    launch.setAttribute("aria-expanded", String(open));
    launch.setAttribute("aria-label", open ? "Close OK AI demo chat" : "Open OK AI demo chat");
    if (open) input.focus();
    else launch.focus();
  }
  function bubble(text, role) {
    var el = document.createElement("div");
    el.className = "okai-bubble " + (role === "user" ? "okai-user" : "okai-assistant");
    el.textContent = text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }
  function reply(question) {
    if (/install|local|macos/i.test(question)) {
      var el = bubble("Sample response: OpenKubes Local has a beginner installation guide. This is only a visual demo; please check the original instructions.", "assistant");
      var a = document.createElement("a");
      a.href = docsUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "Open the installation guide ↗";
      el.appendChild(document.createElement("br"));
      el.appendChild(a);
    } else if (/agent|operation/i.test(question)) {
      bubble("Sample response: Agentic Operations separates AI proposals, authorization, execution and evidence. No live AI connection is enabled here.", "assistant");
    } else {
      bubble("This is a preview UI demo with predefined responses. The real OK AI Documentation Assistant is being developed and is not connected.", "assistant");
    }
  }
  function send(question) {
    question = String(question || "").trim().slice(0, 500);
    if (!question) return;
    bubble(question, "user");
    reply(question);
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
  root.querySelectorAll("[data-demo-question]").forEach(function (button) {
    button.addEventListener("click", function () { send(button.getAttribute("data-demo-question")); });
  });
})();
