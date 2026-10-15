# OK AI — Chat UI Preview

**Visual prototype only.** This is a local demonstration of the future free, no-login Documentation Assistant. It does **not** contact kagent, Ollama, MCP or any API. **Please do not enter secrets or private cluster data.**

<div id="okai-demo" class="okai-demo" aria-label="OK AI chat UI prototype">
  <div class="okai-header"><div class="okai-icon" aria-hidden="true">✦</div><div><strong>OK AI</strong><small>Documentation Assistant · Public Beta design</small></div><span class="okai-pill">UI DEMO</span></div>
  <div class="okai-thread" id="okai-thread" aria-live="polite">
    <div class="okai-message okai-assistant">Hi! I'm OK AI. Ask about OpenKubes installation, architecture or configuration.<small>Preview only — sample replies, not live AI answers.</small></div>
  </div>
  <div class="okai-examples" aria-label="Example questions">
    <button type="button" data-question="How do I install OpenKubes Local on macOS?">Install OpenKubes Local</button>
    <button type="button" data-question="What is OpenKubes Agentic Operations?">Agentic Operations</button>
    <button type="button" data-question="Where can I find the documentation?">Find documentation</button>
  </div>
  <form id="okai-form" class="okai-form"><label class="okai-sr" for="okai-question">Your question</label><input id="okai-question" type="text" maxlength="500" autocomplete="off" placeholder="Ask OK AI (demo)…" required><button type="submit">Send</button></form>
  <p class="okai-notice">Free · No login · No backend connected · Demo responses only</p>
</div>

<style>
#okai-demo {max-width:760px;margin:1.3rem auto;border:1px solid var(--md-default-fg-color--lightest,#d4d9e0);border-radius:18px;overflow:hidden;background:var(--md-default-bg-color,#fff);box-shadow:0 14px 36px rgba(16,39,70,.1);font-size:15px}
#okai-demo .okai-header {display:flex;align-items:center;gap:12px;padding:18px 20px;background:linear-gradient(110deg,#0e3564,#125eb3);color:white}
#okai-demo .okai-header strong {display:block;font-size:20px}
#okai-demo .okai-header small {display:block;font-size:12px;opacity:.85}
#okai-demo .okai-icon {height:40px;width:40px;border:1px solid #a4c9f2;border-radius:13px;display:grid;place-items:center;font-size:23px}
#okai-demo .okai-pill {margin-left:auto;border:1px solid #b0d3f5;border-radius:99px;padding:4px 9px;font-size:11px;letter-spacing:.05em;white-space:nowrap}
#okai-demo .okai-thread {height:330px;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:14px}
#okai-demo .okai-message {max-width:86%;border-radius:15px;padding:12px 15px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55}
#okai-demo .okai-assistant {align-self:flex-start;background:var(--md-code-bg-color,#f1f5f9)}
#okai-demo .okai-user {align-self:flex-end;background:#1461bb;color:white}
#okai-demo .okai-message small {display:block;margin-top:9px;opacity:.75;font-size:12px}
#okai-demo .okai-examples {padding:4px 18px 14px;display:flex;flex-wrap:wrap;gap:7px}
#okai-demo .okai-examples button {border:1px solid #7eace0;color:var(--md-primary-fg-color,#1461bb);border-radius:20px;padding:6px 10px;font-size:12px;cursor:pointer}
#okai-demo .okai-form {display:flex;gap:8px;padding:14px 18px;border-top:1px solid var(--md-default-fg-color--lightest,#ddd);margin:0}
#okai-demo .okai-form input {min-width:0;flex:1;padding:12px;border:1px solid #a6b5c5;border-radius:10px;background:var(--md-default-bg-color,#fff);color:var(--md-default-fg-color,#111)}
#okai-demo .okai-form button {background:#1461bb;color:white;border:0;border-radius:10px;padding:0 19px;cursor:pointer}
#okai-demo .okai-notice {font-size:12px;text-align:center;opacity:.75;margin:0;padding:0 12px 15px}
#okai-demo .okai-sr {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:560px){#okai-demo .okai-thread{height:300px}#okai-demo .okai-header{padding:14px}#okai-demo .okai-pill{font-size:9px}#okai-demo .okai-message{max-width:94%}}
</style>
<script>
(function () {
  const root = document.getElementById("okai-demo");
  if (!root || root.dataset.initialized) return;
  root.dataset.initialized = "true";
  const thread = root.querySelector("#okai-thread");
  const input = root.querySelector("#okai-question");
  const form = root.querySelector("#okai-form");
  const examples = root.querySelectorAll("[data-question]");
  const docsUrl = "https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md";
  function bubble(text, role) {
    const el = document.createElement("div");
    el.className = "okai-message " + (role === "user" ? "okai-user" : "okai-assistant");
    el.textContent = text;
    thread.appendChild(el);
    thread.scrollTop = thread.scrollHeight;
    return el;
  }
  function reply(question) {
    if (/install|local|macos/i.test(question)) {
      const el = bubble("Example: OpenKubes Local uses Multipass, Ubuntu 24.04, K3s and KubeVirt. The official beginner guide describes the steps. This is a static UI demonstration, not a validated AI answer.", "assistant");
      const link = document.createElement("a");
      link.href = docsUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View original documentation (pinned GitHub source)";
      el.appendChild(document.createElement("br"));
      el.appendChild(link);
    } else if (/agent|operation/i.test(question)) {
      bubble("Example: OpenKubes separates AI proposals from authorized execution and evidence. This is a sample UI response, not a live agent answer.", "assistant");
    } else {
      bubble("UI demonstration only. Live, source-validated AI responses will be enabled after the public gateway and security checks are complete.", "assistant");
    }
  }
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const question = input.value.trim().slice(0, 500);
    if (!question) return;
    bubble(question, "user");
    input.value = "";
    reply(question);
  });
  examples.forEach(function (button) {
    button.addEventListener("click", function () {
      input.value = button.dataset.question || "";
      form.requestSubmit();
    });
  });
})();
</script>

## Planned next stages

The public Chat UI will ultimately connect through a protected, rate-limited gateway to the private kagent A2A interface. Production requires source-grounded answer validation and a separate security approval. Until then, this page is **strictly a non-networked UI preview**.
