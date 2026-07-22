# Implementation Guideline: Agentic AI PoC (OpenClaw + Open WebUI)

**Scope:** This document defines the implementation guardrails for OK-14 and
OK-15 — it is normative for that work. It intentionally does *not* redefine
architecture decisions; those remain the responsibility of
[ADR-Platform-015 (Agentic AI)](../architecture/decisions/ADR-Platform-015-agentic-ai.md).
This guideline lives one layer below: Implementation Profile and Provider Values.

**Audience:** Engineers picking up OK-14 (PoC) and OK-15 (deployment) without
prior involvement in the ADR-015 review.

**Source of truth for tasks:** The Jira tickets. This guideline does not
duplicate their task lists or acceptance criteria — it adds the guardrails and
the platform-local knowledge the tickets assume.

- [OK-14 — PoC: OpenClaw + Open WebUI Tandem Architecture](https://kubernauts.atlassian.net/browse/OK-14)
- [OK-15 — Deploy OpenClaw on OpenKubes (Phase 1 Makefile+Helm, Phase 2 Crossplane)](https://kubernauts.atlassian.net/browse/OK-15)

> **Side note — compliance:** GDPR / EU AI Act assessment is explicitly
> deferred by ADR-015 (Out of Scope). This deployment is PoC-only; do not
> expose it to external users or feed it personal data.

---

## Part A — What is already decided (non-negotiable)

These four guardrails come from ADR-Platform-015 (Status: *Proposed*, pending
the Go/No-Go from OK-14). They are contract-level decisions. You implement
within them; you do not re-decide them. The wording below is a condensed
operational summary — when in doubt, ADR-015 is authoritative.

1. **Agent Interface Contract v1 = OpenAI Chat Completions API + Tool Calling.**
   This is the wire format between Open WebUI and the agent backend. Whatever
   backend you run, it must speak this — that is what makes it appear as a
   selectable model in Open WebUI and what makes it replaceable.

2. **Skills are contracts, not tools.** The agent reaches the platform only
   through named, read-only Skill Contracts (Cluster Inspection, Log Query,
   Knowledge Graph, Documentation). Concrete tools (kubectl, OpenSearch
   client, MCP server) are interchangeable implementations behind them. Each
   agent instance declares its skill set explicitly; the declared set is that
   agent's reviewed API surface.

3. **Read-only by default.** No agent mutates cluster state. Diagnosis,
   explanation, and *drafting* of artifacts are in scope; applying,
   remediating, and self-healing are not. The agent's ServiceAccount RBAC is
   derived from its declared Skill Contracts — read-only, **Secrets access
   explicitly excluded**. *AI may argue; only humans merge.*

4. **Open WebUI is the enterprise layer; the agent backend is replaceable.**
   Open WebUI owns multi-user, OIDC (Keycloak), RBAC, and chat persistence.
   The current implementation profile uses OpenClaw as a single-replica,
   token-authenticated backend, treated as stateless — its known limitations
   are contained behind the contract, and any framework speaking Contract v1
   (e.g. kagent) can substitute it.

   **Multi-cluster clarification (ADR-015 Addendum, 2026-07-21; amends
   ADR-005's documented default topology, core decisions unchanged):** Open
   WebUI remains ADR-005's self-service capability (any team/cluster may
   still claim its own instance) — a dedicated instance per workload cluster
   is no longer the *only* supported topology. Today only ok-ai has an
   instance and is deployed; ok-shared and ok-robotics are intended to run a
   kagent-backed ops agent instead of a per-team chat UI, registering into
   the ok-ai instance as a model rather than claiming their own — tracked as
   in-progress work (OK-87, OK-92), not yet a committed deployment. Open
   WebUI stays the frontend half of the initial tandem Implementation
   Profile; the **Agent Backend is the half being generalized** across
   clusters: OpenClaw + Ollama on ok-ai (deployed), OpenClaw with a
   kagent-based Skill Contract backend intended for ok-shared and
   ok-robotics. Agent Interface Contract v1 governs the runtime wire between
   every backend instance and Open WebUI once deployed. It does **not** yet
   cover backend *registration* (identity, endpoint, credentials, idempotent
   apply, de-registration) —
   `make connect-openwebui`'s env-var mechanism is today's informal adapter
   for a small **Agent Backend Registration Contract** that this addendum
   flags as a gap, not yet formalized.

If a step you are about to take conflicts with one of these four points, stop
and read Part C.

> **Implementation follows contracts.** If the implementation becomes easier
> by violating a contract, the implementation is wrong — not the contract.
> (ADR-Platform-001, in one sentence.)

---

## Part B — The PoC path (how)

Execute the implementation in this order: **OK-15 Phase 1 first** (you need a
running deployment), **then OK-14** (the PoC validates against it), **then
OK-15 Phase 2** (only after a Go from OK-14 makes platform integration
worthwhile).

The task lists and acceptance criteria live in the tickets. What follows is
the platform-local knowledge the tickets assume you have.

### Platform-specific Provider Values (adjust freely)

| Item | Value | Note |
|---|---|---|
| Shared LLM backend | Ollama, `http://192.168.100.202:11434` | MetalLB IP on the infra cluster, `ai-services` namespace (ADR-Platform-005) |
| Loaded model | `mistral:latest` | The `ollama/llama3` in OK-15's example config is illustrative — a Provider Value, not a requirement. Use what is loaded, or load what you need. |
| GPU | Single RTX 4000 Ada, 20 GB VRAM, shared | See ADR-015 AR-2: bound your agent's iteration count and timeouts; unbounded loops starve every other consumer. |
| Open WebUI | Exists as a Crossplane XRD (self-service claim); single fixed instance (ok-ai), not per-cluster | Deploying a fresh instance takes ~90 s on a bootstrapped workload cluster. See ADR-015 Addendum (2026-07-21). |
| Image registry | GHCR (`ghcr.io/openkubes/...`) | Harbor was evaluated but is not being implemented; the team standardized on GHCR instead (OK-15 closure, 2026-07-21). Push the custom OpenClaw image here (OK-15 Phase 1). |

### Known pitfalls

- **`OLLAMA_BASE_URL` is not applied by the Open WebUI chart.** After
  deploying Open WebUI, set it manually:
  `kubectl set env deployment/<open-webui> OLLAMA_BASE_URL=http://192.168.100.202:11434 -n <namespace>`.
  This is a known chart bug, not a network problem — check this before
  debugging connectivity.
- **`--bind lan` is required** for the OpenClaw gateway, otherwise the
  Kubernetes Service and health probes cannot reach the process (see OK-15
  key configuration).
- **Statelessness is an assumption, not a fact.** ADR-015 assumes OpenClaw
  can lose all local state on pod restart because Open WebUI owns chat
  persistence. OK-14 requires you to *verify* this: kill the pod mid-session
  and confirm no user-visible state is lost. If the assumption fails, that is
  a finding for the Go/No-Go — not something to patch around silently.

### The kagent evaluation is part of the PoC

OK-14 is not "make OpenClaw work" — the Go/No-Go recommendation must evaluate
OpenClaw *against kagent* (Solo.io, CNCF Sandbox). Two open questions are
tracked as checkboxes in OK-14:

1. Can kagent serve as an OpenAI-compatible backend behind Open WebUI, or
   does it impose its own frontend (which would force a different contract
   cut)?
2. What is kagent's maturity and release cadence *as of the decision date*?
   (Current-state web research required — do not rely on cached knowledge.)

Answer both in the PoC report. The outcome drives ADR-015's status transition
(Proposed → Accepted/Rejected), and a kagent-favoring result swaps the
implementation profile *without touching the contracts* — that is the point
of the architecture.

### RBAC derivation (Phase 1 hand-rolled, Phase 2 generated)

RBAC is derived from the declared Skill Contracts: **the contract determines
the required permissions — not the implementation.** Under the current Skill
Contracts (read-only by design, ADR-015 Decision 5), this results in read
verbs only, with Secrets access explicitly excluded.

In Phase 1 you write the ServiceAccount + Role/RoleBinding by hand in the Helm
chart; in Phase 2 the Crossplane Composition generates them from
`spec.parameters.skills`. Either way the rule is the same: the Role contains
exactly the read verbs (`get`, `list`, `watch`) for the resources the declared
Skill Contracts need — and **never** `secrets`, in any namespace, under any
skill. If a skill seems to need Secrets access, the implementation is asking
for more than its contract grants — stop: Part C.

---

## Part C — The stop rule (an escalation decision rule)

This is not a prohibition — it is decision logic: it tells you *which* of two
paths applies to the change in front of you. The boundary between "just do it"
and "escalate first" is the contract line from ADR-001: **Provider Values are
yours; contracts are not.**

**Set freely (Provider Values / implementation details):**
- IPs, endpoints, namespaces, tokens, replica-adjacent tuning within the
  single-replica constraint
- Which model Ollama serves; resource requests/limits; timeouts and
  iteration bounds
- Helm chart structure, Makefile targets, image build details
- Anything the tickets mark as a task

**Stop and escalate (contract touch → new ADR + three-way review):**
- Any skill that needs **write access** of any kind — including "just this
  one annotation"
- Any skill implementation that needs **Secrets** in its RBAC
- A **second agent backend running in parallel** as a platform offering
  (evaluating kagent *inside* OK-14 is in scope; operating both is a
  platform decision)
- Any change to the **Agent Interface Contract** (different wire format,
  version bump, MCP-native interface)
- Adding a **new Skill Contract** not listed in ADR-015 (new named contract =
  new reviewed API surface)
- Per-user authorization / token forwarding (explicitly deferred to a
  contract v2 consideration)

**How to escalate:** open the discussion with a short written problem
statement referencing the ADR-015 section you are bumping against, and run it
through the review checklist in
[`docs/platform-engineering-method.md`](platform-engineering-method.md).
The rule of the platform applies to us as much as to the agents we build:
anyone may argue; the contract only changes through a reviewed decision.

**The test:** if your change would survive a swap of OpenClaw for kagent
without anyone noticing, it is a Provider Value — proceed. If the swap would
break it, you are touching a contract — escalate.

---

*Language convention: EN-first (this document); DE version follows on
Confluence after review. Reviews run three-way (Arash / Claude / GPT) before
commit.*
