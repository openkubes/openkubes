# Aia at the Gate: AI Proposes, Humans Hold the Key

*How OpenKubes is designing safe agentic cluster lifecycle management*

*By Arash Kaffamanesh*

> **TL;DR:** OpenKubes is proposing a human-approved architecture in which AI may
> diagnose and draft cluster lifecycle changes but cannot authorize, accept, execute,
> or reconcile them. ADR-035 is public and remains `Proposed`; implementation and
> acceptance evidence still have to follow.

---

<!--
Hero image: Aia at the gate with her backpack full of plans, the sensor companions,
and the human builder holding the key.

Suggested alt text:
Aia presents a bridge plan beside four sensor companions while a human builder holds
the key to an ornate gate leading to the real bridge.

Suggested caption:
Aia brings ideas. Sensors bring evidence. A human holds the key to real change.
-->

Aia arrives with a purple backpack that is far too full.

Inside are plans, observations, possible improvements, and probably several ideas nobody
asked for yet. She reads quickly, compares clues, notices when a path no longer matches
the Book of Promises, and drafts a better one.

Then she reaches the gate.

Behind it, a proposal can become a real change. A cluster can be created, upgraded, or
deleted. Infrastructure can move. Machines can disappear. The consequences are no longer
part of a conversation; they become part of the world.

Aia looks for the key. The human builder is holding it.

This is not because the builder distrusts Aia. It is because trust works best when every
participant has a clear responsibility. Aia helps with thinking. Sensors check facts.
Contracts define the promises. Humans carry responsibility for consequential decisions.

That scene from the [Oki Universe](https://oki.openkubes.org/#start) has become the most
useful explanation of how we want AI to participate in the OpenKubes control plane.

It is also the story behind our new architecture decision,
[ADR-Platform-035](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-035-hybrid-intent-and-control-plane-execution.md).

## The Question That Sent Us to the Gate

Our starting question sounded simple:

> Could an AI agent replace the custom runner that helps provision and manage OpenKubes
> workload clusters?

The runner contains deterministic Go and Python logic. It validates declarations,
submits lifecycle changes, observes Cluster API and related controllers, and records
evidence. An agent can reason across more context, explain failures, and translate natural
language into configuration. Why maintain both?

Because this is not really a choice between two components.

The runner itself is replaceable. It is one implementation of a deeper architectural
role: the **Contract Executor**. The safety property we need to preserve is not a specific
container, language, or API. It is the boundary between reasoning about a change and
authoritatively accepting and executing that change.

Once we framed the problem that way, the answer became clear:

> The agent may help create intent. It must not become the authority, executor, or
> reconciler merely because it can call tools.

## Aia Is an Author, Not an Authority

In the Oki Universe, the metaphors already line up with the architecture.

Aia and her backpack represent the untrusted authoring layer and its candidate proposals.
The Book of Promises represents versioned OpenKubes Contracts. The sensors represent
read-only diagnostics and evidence. Reviewing the plan together represents deterministic
canonicalization and a human-readable semantic review. The builder holding the key is the
authenticated Human Approver. The gate represents the Policy, Authority, and Contract
Executor boundary. Beyond the gate, controllers reconcile the accepted state across the
islands.

The resulting principle is simple enough to remember:

> **Aia helps us think. Humans approve. Policies authorize. Executors submit. Controllers
> reconcile.**

The implementation behind that sentence is deliberately less magical.

## From a Candidate to a Real Cluster Change

An agent-originated lifecycle proposal follows the same control-plane model as any other
request. It does not receive a privileged shortcut.

```text
User and Aia
    -> untrusted candidate input
    -> server-attested proposal provenance
    -> deterministic canonicalization and transition planning
    -> authenticated human review of the exact semantic change
    -> policy authorization bound to that exact transition
    -> Executor verification and single-use authorization claim
    -> atomic compare-and-swap acceptance by the Authority Profile
    -> asynchronous reconciliation by GitOps and lifecycle controllers
    -> generation-correlated Conditions and durable evidence
```

Each arrow matters.

The Candidate Proposal service records who produced the proposal using server-attested
workload identity. An agent cannot simply label its own work as human-authored.

The Canonicalizer converts flexible authoring input into one deterministic representation.
It rejects duplicate keys, ambiguous fields, unsupported schema versions, and
parser-dependent interpretations. Semantically identical input must produce identical
canonical bytes and the same digest.

The human reviews the effective change, including defaults, rather than approving an
opaque hash. The human-visible review artifact is derived from the exact canonical
predecessor and requested revision. Its digest, renderer version, canonicalization profile,
and request digest remain bound together.

The Policy Authority verifies that protected approval and issues a single-use decision for
one exact transition. The Contract Executor independently verifies and durably claims that
authorization. Only then may the selected Authority Profile atomically accept the new
desired revision.

Acceptance changes authority. It does not prove convergence.

Cluster API, infrastructure providers, Cluster Enablement, GitOps, and other responsible
controllers still reconcile asynchronously. Their revision- and generation-correlated
Conditions determine whether the requested state was realized. An LLM response and a
successful runner exit code do not.

## Human Approval Must Mean More Than Clicking “Approve”

Digest binding solves only part of the problem. A person cannot meaningfully approve a
digest they do not understand.

The security property we need is often called **WYSIWYS: What You See Is What You Sign**.
The semantic change shown to the reviewer, the canonical representation used to compute
the request digest, and the revision later presented for acceptance must remain
inseparably correlated.

If the proposal changes after review, the approval becomes invalid. If the canonicalizer
profile changes, the proposal must be reviewed again. If the human-visible artifact
changes, its protected binding changes too. A later deployment of the renderer does not
rewrite history; the immutable versioned review artifact remains the evidence of what the
person actually approved.

This may sound strict for creating a Kubernetes cluster. It is exactly as strict as we
want it to be for deleting one.

## Why the Agent Never Sees the Full Executor API

One tempting design is to expose the entire mutating API through MCP and rely on RBAC to
deny dangerous calls.

We rejected that design.

An authorization defect, confused-deputy path, or accidentally broadened role would turn
an advertised tool into a real mutation capability. Instead, the agent-facing MCP surface
is constructed from two intentionally narrow contracts:

- the existing Read-Only Platform Diagnostics Contract; and
- a separate, non-authoritative Candidate Proposal Contract.

It is not produced by taking a powerful Executor API and subtracting methods until it
looks safe. Mutating Executor and Authority operations live behind separate identity,
authorization, and network boundaries. They do not appear in the agent-facing tool
surface at all.

Prompts and tool descriptions remain helpful interaction material. They are never
validation logic, policy, provenance, authorization, or readiness evidence.

## Prompt Injection Does Not Disappear at the Gate

Read-only is not the same as harmless.

Poisoned documentation, logs, diagnostic output, or retrieval context can influence the
model's next proposal. An agent can create a syntactically valid but undesirable candidate.
It can consume review capacity. It may expose information available to its read identity.
And a human reviewer can still be deceived into approving a manipulated proposal.

Human approval bounds this risk; it does not eliminate it.

That is why the design also requires least-privilege read identities, server-attested
provenance, quotas, rate limits, audit records, deterministic canonicalization, explicit
semantic review, and a policy decision bound to the exact transition. The gate is a system
of independent controls, not a ceremonial button.

## What Exists Today — and What Is Still a Target

We want to be precise about current reality.

OpenKubes has already validated the read-only diagnostic foundation in the OK-14/OK-92
proof of concept: agents access platform state through scoped contracts and dedicated
workload identities, while writes and Secrets are denied. This boundary is documented in
ADR-015 and ADR-021. OpenClaw remains an optional broad assistant, while kagent is the
first diagnostics implementation behind the OpenKubes-owned contract. The
candidate-to-acceptance lifecycle path defined by ADR-035 remains target architecture and
still requires its acceptance evidence.

ADR-Platform-035 is the next architectural step. It has been merged into the public
repository with **Status: Proposed**. Merging the document means the design is available
for review and implementation. It does not mean the end-to-end Candidate Proposal,
approval, Authority, and Executor path already exists or has passed conformance.

Before the ADR can move to `Accepted`, OpenKubes requires reviewed evidence for fourteen
criteria. They cover provenance and identity isolation, GitOps reconciliation isolation,
human-approval enforcement, digest and transition locking, stale-write rejection, replay
and crash recovery, MCP attack-surface verification, Condition correctness, WYSIWYS
review, canonical-form correlation, parser-differential resistance, and renderer binding.

This distinction matters. We are publishing an architecture and an evidence bar, not
announcing an autonomous production feature.

## Why We Are Publishing Before We Build

Agentic infrastructure management is moving quickly. The easy demonstrations are
impressive: give a model cluster-admin, ask it to fix something, and watch the terminal.

The harder questions begin after the demo:

- Who owns the desired state?
- What exactly did the human approve?
- Can the model alter the evidence shown to the reviewer?
- What happens after a stale plan or a lost response?
- Can a candidate branch ever be reconciled accidentally?
- How do we prove that an MCP surface contains no mutation path?
- Which state remains authoritative after the Executor crashes?

We would rather expose those questions now than hide them behind an apparently seamless
chat interface.

The implementation work is tracked under OpenKubes Epic `OK-149`. We are deliberately
starting with this article and community discussion. Feedback that changes a contract
will go back through the ADR process. Public feedback is design input; it does not silently
become platform authority either.

## We Would Like Your Feedback

If you operate Kubernetes platforms, build agent frameworks, design authorization
systems, or work on GitOps control planes, we would especially value your perspective:

1. Where do you place the human approval boundary for agent-originated infrastructure
   changes?
2. Have you implemented WYSIWYS review for declarative configuration or GitOps changes?
3. How do you perform atomic, transition-correlated acceptance with Git as authority?
4. Do your agent-facing APIs expose a safe contract by construction, or a filtered view of
   a more powerful API?
5. Which lifecycle changes, if any, could eventually qualify for scoped standing approval?
6. What evidence would you require before trusting this design in production?

We have intentionally excluded autonomous and standing approval from this ADR. If we ever
introduce it, it will require a separate decision, a bounded operation scope, an explicit
threat model, and its own acceptance evidence.

## The Key Stays Visible

Aia's backpack will keep getting fuller. That is a feature.

We want agents that can read more evidence, connect more clues, explain failures, and
prepare better proposals. We want the interaction to feel natural and the underlying
platform to remain boringly explicit about authority.

The goal is not to keep AI away from infrastructure engineering. The goal is to give AI a
valuable role without allowing convenience to erase responsibility.

At the OpenKubes gate, Aia brings the plan. The sensors bring the evidence. The Contracts
define the promises. A human turns the key. Deterministic systems carry the accepted
change into the world.

That is how we intend to make agentic cluster lifecycle management useful, reviewable,
and worthy of trust.

---

## References

- [ADR-Platform-035: Hybrid Intent and Control-Plane Execution Architecture](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-035-hybrid-intent-and-control-plane-execution.md)
- [ADR-Platform-035 pull request and design discussion](https://github.com/openkubes/openkubes/pull/258)
- [ADR-Platform-015: Agentic AI](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-015-agentic-ai.md)
- [ADR-Platform-021: Read-Only Platform Diagnostics Contract](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-021-read-only-platform-diagnostics-contract.md)
- [Oki Universe — Oki und das Geheimnis der Inseln](https://oki.openkubes.org/#start)
- [OpenKubes on GitHub](https://github.com/openkubes/openkubes)

---

*Author's note: This article was developed from ADR-Platform-035 through a human-led
review involving Codex, Claude, and Gemini. The architectural decision, editorial
framing, and final publication authority remain with the author.*
