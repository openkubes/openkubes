# OK AI Roadmap — Four Agents. One Trusted Platform.

**Four specialized AI agents. Independent authority. Human-governed operations. Verifiable outcomes.**

OpenKubes is developing four optional agent capabilities on a shared **Security-by-Contract** foundation. They are **parallel tracks, not a progression from assistant to unrestricted autonomy**. Core OpenKubes must continue to work without AI agents.

## Architecture at a glance

[![Four OpenKubes AI agents, two human oversight modes and independent policy-bounded execution, with future HOTL labelled research only.](ai-four-agents-security-architecture.svg)](ai-four-agents-security-architecture.svg)

*Conceptual target architecture, not a deployed four-agent system. Select the native SVG to enlarge it on this page.*

## Meet the four agents

<div class="ok-ai-roadmap" aria-label="Four specialized OpenKubes AI agent capability tracks">
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--docs">
    <div class="ok-ai-roadmap__top"><span class="ok-ai-roadmap__icon" aria-hidden="true">📖</span><span class="ok-ai-roadmap__status">Experimental validation</span></div>
    <p class="ok-ai-roadmap__phase">Knowledge &amp; guidance</p>
    <h3>AI Assistant</h3>
    <p>Answers documentation questions and guides users to OpenKubes architecture and tutorials.</p>
    <p class="ok-ai-roadmap__boundary"><strong>Boundary:</strong> No cluster access or command execution.</p>
    <a href="/ai/chat-preview/">Explore the chat prototype →</a>
  </article>
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--diagnostics">
    <div class="ok-ai-roadmap__top"><span class="ok-ai-roadmap__icon" aria-hidden="true">🔎</span><span class="ok-ai-roadmap__status ok-ai-roadmap__status--planned">Implementation</span></div>
    <p class="ok-ai-roadmap__phase">Observe &amp; investigate</p>
    <h3>AI Diagnostic Agent</h3>
    <p>Correlates scoped Kubernetes health, workload and observability data to explain incidents.</p>
    <p class="ok-ai-roadmap__boundary"><strong>Boundary:</strong> Read-only tools; no Secrets or mutations.</p>
    <a href="/ai/kagent-platform-diagnostics/">Explore diagnostic contracts →</a>
  </article>
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--operations">
    <div class="ok-ai-roadmap__top"><span class="ok-ai-roadmap__icon" aria-hidden="true">🛠️</span><span class="ok-ai-roadmap__status ok-ai-roadmap__status--planned">Proposed · HOTL research</span></div>
    <p class="ok-ai-roadmap__phase">Remediate &amp; recover</p>
    <h3>AI SRE Agent</h3>
    <p>Plans Kubernetes remediation, upgrades and recovery with <strong>HITL</strong> and future, bounded <strong>HOTL</strong>.</p>
    <p class="ok-ai-roadmap__boundary"><strong>Boundary:</strong> No direct write access; independently authorized transitions.</p>
    <a href="/ai/agentic-operations/">Explore SRE operations →</a>
  </article>
  <article class="ok-ai-roadmap__card ok-ai-roadmap__card--security">
    <div class="ok-ai-roadmap__top"><span class="ok-ai-roadmap__icon" aria-hidden="true">🛡️</span><span class="ok-ai-roadmap__status ok-ai-roadmap__status--planned">Research</span></div>
    <p class="ok-ai-roadmap__phase">Assess &amp; recommend</p>
    <h3>AI Security Agent</h3>
    <p>Investigates RBAC, policy drift, privilege risks and agentic-operation security evidence.</p>
    <p class="ok-ai-roadmap__boundary"><strong>Boundary:</strong> Cannot grant permissions or replace the Policy Authority.</p>
    <a href="/architecture/security-first/">Explore Security First →</a>
  </article>
</div>

!!! info "Capability maturity, not availability"
    **Experimental validation** means limited private-lab evidence (the Assistant passed one format/source-ID check, not grounding or public-beta certification). **Implementation** means a documented contract and components, not a verified production service. **Proposed** means a designed, unapproved execution path. **Research** means hypotheses requiring new architecture decisions and tests. None of these labels means that a production four-agent system or agent-originated HOTL is available.

## AI SRE — HITL and HOTL

These are **human oversight models**, not successive autonomy levels. Both must use independently enforced Policy-Bounded Execution.

<div class="ok-ai-oversight">
  <section class="ok-ai-oversight__item">
    <h3>HITL · Exact human approval</h3>
    <p>For the <strong>current proposed</strong> agent-originated mutation path, a person approves the exact canonical transition before independent authorization and bounded execution.</p>
    <p class="ok-ai-oversight__example">Examples: specific BYOH upgrade, machine replacement, handover or cluster deletion.</p>
  </section>
  <section class="ok-ai-oversight__item ok-ai-oversight__item--future">
    <h3>HOTL · Supervised bounded autonomy</h3>
    <p><strong>Future research only:</strong> humans set narrow, revocable eligibility mandates, monitor execution and retain stop and recovery controls. A standing mandate is never permanent agent RBAC.</p>
    <p class="ok-ai-oversight__example">Candidate: fixed-field workload remediation under scope, budgets and independent authorization.</p>
  </section>
</div>

**HOTL is not yet approved:** it requires a new accepted normative ADR beyond the current ADR-035 exact-approval baseline and validated revocation ordering, budgets, fencing, recovery and independent evidence. Even a valid proposal from the SRE Agent is **untrusted candidate input**, not a canonical transition or an authorization.

[Read Research Paper 001 — HITL, HOTL and Policy-Bounded Autonomy](../research/security/hitl-hotl-policy-bounded-autonomy.md).

## Capability roadmap and evidence gates

| Agent | Next milestone | Evidence required before advancing |
| --- | --- | --- |
| **AI Assistant** | Evaluate source-grounded answers and safe installation guidance | Documented corpus, correctness and prompt-injection tests; no tool privilege |
| **AI Diagnostic** | Validate provider-neutral read-only integration | RBAC denial, tool-server identity isolation, redaction and scoped diagnostic evidence |
| **AI SRE** | Validate protected exact HITL review → grant → acceptance → observed outcome | Digest-bound canonicalization, negative mutation tests, failure and recovery evidence |
| **AI Security** | Define read-only assessment contract and findings schema | Traceable RBAC/policy findings, false-positive tests and controlled handoff to SRE |

**Separate HOTL research gate for the AI SRE Agent:** standing mandate lifecycle, atomic risk reservations, reliable pre-acceptance revocation, effective stop/fencing, restore-safe authority and independently verified E2E failures must be designed, tested and approved before any agent-initiated HOTL execution claim.

## Security by Contract — common guardrails

1. **Agent identity is never execution authority.** AI agents propose; trusted intake authenticates provenance and canonicalizes the exact transition. A shared privileged tool-server ServiceAccount must not permit an agent to bypass this path.
2. **Independent Policy Authority and Contract Executor** verify scope, protected human approval where required, single-use grants and field restrictions. Admission must enforce the actual operation against the authorized context.
3. **Controllers own reconciliation.** A successful request, an accepted desired revision and a healthy final state are distinct outcomes; independent evidence records those distinctions.
4. **Fail closed without blocking legitimate recovery.** Unverifiable authorization is denied; emergency recovery follows a separately protected procedure. Revocation or restore guarantees are claims only after profile-specific tests.

The **AI Security Agent assesses risk but never approves its own findings or grants SRE execution authority**. Trusted policy evaluation remains independent of all four agents. Trusted deterministic controller recovery is a separate, explicitly authorized model, not a shortcut around the HOTL research requirement.

## Explore OpenKubes AI and security

- [OK AI overview](index.md) — platform components, backends and integration starting points
- [kagent & Platform Diagnostics](kagent-platform-diagnostics.md) — read-only provider contract and current integration constraints
- [Agentic Operations](agentic-operations.md) — SRE proposal-to-evidence responsibility model
- [Security First](../architecture/security-first.md) — common accepted security principles
- [Security & Trust Research](../research/security/index.md) — research, reviews and open proof obligations

**Humans govern. Policies constrain. Machines execute. Evidence verifies.**
