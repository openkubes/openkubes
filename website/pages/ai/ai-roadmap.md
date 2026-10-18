# OK AI Roadmap

**From trusted answers to governed operations.** OpenKubes is developing OK AI in three deliberately separated phases: documentation assistance, read-only diagnostics, and optional, policy-governed operations.

<div class="ok-ai-roadmap" aria-label="Three phases of the OK AI roadmap">
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--docs">
    <div class="ok-ai-roadmap__top">
      <span class="ok-ai-roadmap__icon" aria-hidden="true">📖</span>
      <span class="ok-ai-roadmap__status">Private lab: format PASS</span>
    </div>
    <p class="ok-ai-roadmap__phase">Phase 01</p>
    <h2>Documentation Assistant</h2>
    <p>Ask questions about OpenKubes architecture, installation, and configuration using allowlisted public documentation, READMEs, and tutorials.</p>
    <p class="ok-ai-roadmap__boundary">Read-only answers. No cluster access or command execution.</p>
    <a href="chat-preview.md">Explore the chat UI prototype →</a>
  </article>
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--diagnostics">
    <div class="ok-ai-roadmap__top">
      <span class="ok-ai-roadmap__icon" aria-hidden="true">🔎</span>
      <span class="ok-ai-roadmap__status ok-ai-roadmap__status--planned">Planned · optional</span>
    </div>
    <p class="ok-ai-roadmap__phase">Phase 02</p>
    <h2>Read-only Diagnostics</h2>
    <p>Analyze user-supplied, redacted logs and Kubernetes manifests, with future support for explicitly scoped, read-only diagnostic data.</p>
    <p class="ok-ai-roadmap__boundary">Investigate and explain. Never change cluster state.</p>
    <a href="kagent-platform-diagnostics.md">Read about platform diagnostics →</a>
  </article>
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--operations">
    <div class="ok-ai-roadmap__top">
      <span class="ok-ai-roadmap__icon" aria-hidden="true">⚙️</span>
      <span class="ok-ai-roadmap__status ok-ai-roadmap__status--planned">Proposed · optional</span>
    </div>
    <p class="ok-ai-roadmap__phase">Phase 03</p>
    <h2>Agentic Operations</h2>
    <p>Authenticated, policy-governed platform operations with explicit authorization, a bounded runner, and independently verifiable evidence.</p>
    <p class="ok-ai-roadmap__boundary">Agents propose. OpenKubes authorizes and executes. Evidence proves.</p>
    <a href="agentic-operations.md">Explore the reference architecture →</a>
  </article>
</div>

!!! info "Roadmap, not a release announcement"
    **Phase 1 has passed a private lab integration check for one documentation question, not a public beta or a semantic-grounding certification.** Installation-command handling and public security, quality, and release checks are still in progress. Phases 2 and 3 describe optional directions, not generally available features. OpenKubes remains functional without AI agents.

## One architecture, clear trust boundaries

**AI thinks. OpenKubes executes. Evidence proves.** Each phase adds capabilities without giving an AI agent unrestricted access to Kubernetes. In Phase 3, platform state changes must pass through independent policy, approval, and execution contracts; the agent never receives direct Kubernetes mutation authority.

For the publicly documented execution boundaries, see the [Agentic Operations Reference Architecture](../agentic-operations-reference-architecture.md).

[← Back to OK AI overview](index.md)
