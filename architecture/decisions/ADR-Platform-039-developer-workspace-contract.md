# ADR-Platform-039: Developer Workspace Contract

**Date:** 2026-09-25

**Status:** Proposed

**Related:** OK-174, ADR-Platform-001, ADR-Platform-005, ADR-Platform-011, ADR-Platform-015, ADR-Platform-017, ADR-Platform-020, ADR-Platform-034

---

## Context

OpenKubes is beginning to support AI-assisted software engineering workflows in addition to general AI, platform-agent and workload use cases. Coding agents such as OpenCode can inspect repositories, edit files, run shell commands, execute tests and connect to external tools. That makes them materially more privileged than a conventional chat frontend.

The platform therefore needs an explicit boundary for a developer's or agent's execution environment before any particular coding-agent product is adopted as infrastructure.

The first forcing implementation is OpenCode. The first isolation implementation under consideration is one Kubernetes Namespace per workspace. Neither is stable enough to become the public platform contract.

Consistent with ADR-Platform-001, OpenKubes must own the semantics of a developer workspace, not the lifecycle or API of OpenCode, Kubernetes Namespaces, Kata, KubeVirt or another future sandbox implementation.

## Decision drivers

- A coding agent can read and modify source and execute processes; its isolation boundary must be explicit and testable.
- A workspace needs source, filesystem, identity, network, credentials, resources and lifecycle semantics as one coherent unit.
- Workspace identity must survive implementation changes.
- OpenCode must remain replaceable by another conforming coding-agent runtime.
- The default posture must not grant ambient Kubernetes or infrastructure authority.
- Git, ok-ai and tool/MCP access must be explicit capabilities rather than consequences of network placement.
- Persistent human workspaces and short-lived task/agent workspaces need different lifecycle behavior without creating separate platform concepts.
- Human review/merge/deployment authority must remain outside the workspace contract.
- The first implementation must be simple enough to prove on today's OpenKubes Kubernetes platform.

## Decision

OpenKubes defines a **Developer Workspace Contract**. A `DeveloperWorkspace` is a bounded, declarative execution environment for a human developer, coding agent or both.

The contract defines the required semantics for:

1. workspace identity;
2. source and revision;
3. runtime profile;
4. model/inference profile;
5. filesystem and persistence;
6. workload identity and credentials;
7. network and tool capabilities;
8. compute/resource bounds;
9. lifecycle and retention; and
10. observable state and evidence.

The first reference implementation maps **one `DeveloperWorkspace` to one Kubernetes Namespace**. The Namespace is an implementation detail of the initial isolation profile; it is not the workspace's public identity or contract.

OpenCode is the first forcing/reference coding-agent runtime profile. It is not required by the Developer Workspace Contract.

### 1. Contract boundary

DeveloperWorkspace Contract -> Implementation Profile -> Kubernetes Namespace (first profile), Kata/KubeVirt/remote sandbox (possible future profiles).

Consumers MUST NOT rely on Namespace names, pod topology, container image layout or an OpenCode-specific API as stable workspace semantics.

### 2. Minimal `DeveloperWorkspace` v0alpha1 shape

The spike will validate a contract shape with explicit fields for source/revision, runtime profile, model profile, storage mode/size, CPU/memory bounds, Git capability, inference capability, approved tools, Kubernetes access, lifecycle profile, idle timeout and retention.

This is an illustrative contract candidate, not an accepted schema. Field naming may change during OK-174, but the semantic boundaries above require explicit representation.

### 3. Workspace identity is not user identity

A user or service identity MAY own multiple workspaces. Workspace identity is therefore separate from the authenticated subject.

Authorization to create, attach to, mutate or delete a workspace is evaluated separately from the workload identity used inside that workspace.

### 4. Namespace reference profile

The first implementation profile maps one workspace to one dedicated Namespace.

A conforming Namespace profile MUST provide, at minimum:

- a dedicated Namespace per workspace;
- a dedicated workload ServiceAccount;
- no automatically mounted broad Kubernetes credentials;
- least-privilege RBAC only for explicitly declared Kubernetes capabilities;
- a workspace filesystem using ephemeral or persistent storage according to lifecycle profile;
- ResourceQuota and/or equivalent resource enforcement;
- LimitRange or equivalent bounded defaults;
- default-deny or equivalently restrictive NetworkPolicy;
- explicit egress allowances for declared services only;
- scoped credential delivery through the accepted Secret Contract;
- observable workspace readiness, failure and termination state; and
- deterministic cleanup behavior.

Namespace naming is a provider value and MUST NOT be used as the external workspace identity.

**Proposed amendment (OK-176, pending decision): persistent capacity.** A Namespace profile MAY
offer the persistent lifecycle profile only if its storage implementation enforces the declared
persistent capacity at runtime, so that a workspace cannot write past the declared size.
Admission-time sizing (a claim size or a `requests.storage` quota) alone does not meet this.
A profile whose storage does not enforce runtime capacity is a development or constrained profile:
it MUST NOT claim a persistent-capacity isolation guarantee, and it MUST NOT offer the persistent
profile as conforming until such an implementation is available. This rule is provider-neutral and
names no storage implementation; `local-path` is one implementation that does not meet it.

### 5. Capability model

Access from a workspace is capability-based and deny-by-default.

Capabilities may include Git source access, ok-ai or another conforming inference endpoint, approved MCP/tool endpoints, artifact/package registries, selected external network destinations, and optionally narrowly-scoped Kubernetes API operations.

A workspace does not gain a capability merely because it runs in a cluster where that service is reachable.

The default Kubernetes capability is `kubernetes.access = none`.

A broad kubeconfig, `cluster-admin`, wildcard RBAC or unrestricted service-account token does not conform to the default profile.

### 6. Coding-agent runtime profiles

A coding-agent runtime is an implementation profile behind the workspace contract.

The first forcing profile is `runtime.profile = opencode`.

Its responsibilities include starting the agent in the workspace filesystem and honoring the workspace's declared source, credentials, network and resource boundaries.

OpenCode-specific configuration, commands and internal APIs are not part of the public Developer Workspace Contract.

A second implementation such as Codex, Claude Code or another future coding agent must be able to satisfy the same workspace semantics without requiring consumers to adopt a different workspace API.

### 7. Source and filesystem semantics

A workspace declares an explicit source repository and revision.

The implementation profile is responsible for producing a filesystem state traceable to that declaration. Mutable working state is expected after startup.

The contract distinguishes source identity, mutable workspace filesystem state and published evidence such as commits, patches, test results, artifacts or pull requests.

A successful workspace does not imply that modified filesystem state is authoritative platform desired state.

### 8. Lifecycle profiles

The initial contract recognizes three lifecycle profiles.

#### Persistent

Intended for recurring human development. Workspace storage survives runtime restart; idle handling may stop compute while retaining storage; retention and final deletion are explicit.

#### Ephemeral

Intended for a ticket, PR, automation or bounded agent task. Retention after completion is explicit and finite; final deletion removes runtime and workspace-scoped credentials; required evidence must be exported before deletion.

#### Review

Intended for analysis of an existing change. Credentials and tool access SHOULD be more restrictive than a normal development profile, and the profile MUST NOT imply merge authority.

Additional profiles require a forcing consumer.

### 9. Human authority and platform transitions

The Developer Workspace Contract grants execution capability, not authority to accept a platform change.

A coding agent MAY inspect source, modify its workspace, run declared tests, generate patches or commits, create a pull request where explicitly permitted, and produce evidence.

The contract does not grant merge, release, production deployment or desired-state transition authority. Those remain governed by the relevant OpenKubes contracts and human/organizational approval paths, including ADR-Platform-034.

### 10. Status and lifecycle evidence

Workspace historical outcome and current runtime health are distinct. Current health MUST NOT rewrite historical task evidence.

The contract must distinguish requested/accepted workspace spec, current reconciliation/runtime health, terminal lifecycle outcome where applicable, and exported evidence.

## Normative invariants

- **INV-039-1 — Contract, not runtime.** `DeveloperWorkspace` semantics do not depend on OpenCode-specific APIs.
- **INV-039-2 — Workspace, not Namespace.** Kubernetes Namespace identity and naming are not public workspace identity.
- **INV-039-3 — Isolation by default.** Workspace filesystem, credentials, network and compute are scoped to the workspace implementation boundary.
- **INV-039-4 — No ambient cluster authority.** Broad Kubernetes API access is absent unless an explicit capability profile grants narrowly-scoped operations.
- **INV-039-5 — Explicit connectivity.** Git, inference, MCP/tool and external network access are declared capabilities, not implicit reachability.
- **INV-039-6 — Bounded lifecycle.** Creation, idling, retention, termination and deletion have explicit semantics.
- **INV-039-7 — Replaceable runtime.** A second conforming coding-agent runtime can implement the same workspace contract.
- **INV-039-8 — Execution is not acceptance.** Workspace or agent success does not imply merge, release, deployment or platform-transition authority.
- **INV-039-9 — Evidence survives cleanup when required.** Ephemeral workspace deletion cannot be the only location of evidence required by the governing workflow.
- **INV-039-10 — Historical outcome is immutable.** Later runtime drift or infrastructure failure does not rewrite a previously completed task outcome.

## Consequences

### Positive

- OpenKubes gains a durable abstraction for developer and coding-agent execution without coupling the platform to OpenCode.
- Namespace isolation can be used immediately while leaving room for stronger sandbox/VM profiles later.
- Security policy becomes part of the workspace API surface rather than an undocumented deployment convention.
- Human, agentic and review workflows can share one contract with explicit lifecycle profiles.
- ok-ai and future MCP services gain a clean consumer boundary.

### Costs and risks

- Namespace isolation alone is not equivalent to a VM security boundary. The accepted profile must make its isolation claim precise.
- NetworkPolicy effectiveness depends on the cluster networking implementation.
- Coding agents execute untrusted or model-generated commands; supply-chain, shell and tool access remain security-sensitive even inside a namespace.
- Per-workspace namespaces, storage and policy objects add control-plane and operational overhead.
- Persistent workspaces introduce storage lifecycle and stale-credential concerns.

## Alternatives considered

### OpenCode deployment as the platform contract

Rejected. It couples OpenKubes to a specific coding agent and would make runtime replacement a breaking platform change.

### One permanent namespace per developer

Not selected as the contract model. A user may require multiple isolated repository/task contexts, and ephemeral agent/review workflows do not map cleanly to one long-lived namespace.

### Shared multi-user OpenCode service with shared filesystem and credentials

Rejected as the default reference architecture. The blast radius for source, credentials, network and shell execution is too broad and the isolation boundary becomes ambiguous.

### Cluster-admin coding workspace

Rejected. Coding convenience is not sufficient justification for ambient infrastructure authority.

### VM-only workspace from the start

Deferred. VM-backed isolation may become an implementation profile, but requiring it before a Namespace profile is tested would add infrastructure without evidence that the contract itself is correctly cut.

## Validated reference-profile boundary

`architecture/spikes/ADR-Platform-039/live/evidence/live-evidence-v1.yaml` records one live
run on `ok-obs-verify` that passed all 18 required effects. The run deployed `render()` output
for two `DeveloperWorkspace` documents that differ only in `spec.runtime.profile`: OpenCode,
then Codex on the same volume. The workspace Namespace, Deployment, NetworkPolicies,
ResourceQuota, LimitRange, ServiceAccount and PVC were read back and compared with the render
plus five recorded operational overlays; the harness-materialized Secrets and ConfigMap, and
the proof-service objects, were not. Each agent edited the fixture and ran the declared
verification command through its own shell tool, and the harness re-ran the test
independently. Every exec transcript is bound to the pod it ran in. The run also exercised
default-deny policy, explicit Git, inference and MCP egress, no mounted ServiceAccount token,
discovery-only RBAC, kernel cgroup CPU and memory limits matching the render, a
`requests.storage` quota rejection, ephemeral `emptyDir` eviction, credential-canary scans of
both runtime pods and the ephemeral pod, and UID-preconditioned cleanup. A separate
fail-on-purpose run, `negative-controls-v1.yaml`, broke each probe's precondition on the
cluster and required the probe to go red, then green after the revert.

What the evidence does not show:
- CPU and memory limits are configured in the kernel as rendered, but were not stressed.
- The MCP capability is network reachability to one reviewed endpoint; `approvedTools` is not
  enforced at the tool level.
- No reconciling controller exists. The harness applies the render and orders export before
  deletion; a future controller must own that.
- Inference is ok-ai's shared Ollama outside the cluster, reached through a reviewed `/32` host
  route.
- Codex runs with its own sandbox disabled, because it cannot nest inside the unprivileged pod.
- The raw transcripts are integrity-bound after capture, not attested. Beyond the cluster,
  node, image and model identifiers, their content could be recomputed offline.

The corrected proof fixes four profile and contract choices:

- **Capability destinations.** Besides a `/32` `{cidr, port}` host route, a reviewed profile may
  name an in-cluster `{service: {namespace, name}, port}` destination. It renders as a
  namespace and pod selector taken from the profile's reviewed Service selector, plus a kube-dns
  egress allow. CIDR rules cannot select cluster-managed pod backends under Cilium. The form lives
  only in the profile, so the `DeveloperWorkspace` contract stays cluster-agnostic.
- **Source TLS.** Source endpoints must be HTTPS. The profile names a CA bundle ConfigMap that
  is mounted only into the checkout init container, along with the Git credential. The runtime
  container receives neither.
- **Declared verification.** `spec.verification.command` is a portable, runtime-agnostic test
  declaration. The agent is told to run it, and the harness runs it again independently.
- **Storage bounds.** A `requests.storage` quota bounds persistent claims at admission, and an
  ephemeral `emptyDir.sizeLimit` bounds ephemeral workspaces by eviction. The `local-path`
  provisioner does not enforce requested capacity on a persistent volume.

The reconciler proof on a disposable cluster (OK-175, OK-176) adds runtime bound evidence:

- CPU runtime bound: proven (demand above the limit is throttled to it).
- Memory runtime bound: proven (an allocation above the limit is OOM-killed).
- Ephemeral storage runtime bound: proven (overflowing the `emptyDir` limit evicts the pod).
- Persistent allocation/request bound: proven at admission (the quota rejects a claim beyond the
  declared size).
- Persistent byte-capacity runtime bound with `local-path`: not supported, not proven. A workspace
  declaring 1 GiB wrote 1280 MiB. This is negative evidence; the proposed persistent-capacity
  amendment under section 4 decides what a conforming persistent profile requires.

This profile isolates workspace resources through Kubernetes Namespace, ServiceAccount, Secret,
quota, storage and NetworkPolicy boundaries. It does not provide a separate kernel, VM or hostile
multi-tenant boundary; it trusts the cluster, nodes, CNI, storage provisioner and reviewed runtime
images. The credential check is a bounded scan of manifests, argv, workspace content, captured
output and Pod logs. It does not prove that a malicious runtime could not exfiltrate a credential
to an allowed endpoint. The evidence binds the source known commit, implementation revision, and
image digests separately; it is not a build attestation tying those images to that revision. Stronger threat
models require a future sandbox or VM profile.

## Required acceptance evidence

ADR-Platform-039 remains **Proposed** until a human decision-holder accepts the architecture
after reviewing the required acceptance evidence. The current evidence, recorded in
`developer-workspace-verdict-v1.yaml`, supports a GO recommendation for the contract and
Namespace reference-profile direction, but does not by itself waive unmet evidence items or
implementation-profile readiness gates. The limits stated under the reference-profile boundary
above apply to items 9 and 11. The evidence items are:

1. a rendered `DeveloperWorkspace` v0alpha1 candidate independent of OpenCode internals;
2. creation of one workspace as one dedicated Kubernetes Namespace;
3. source checkout at a declared repository/revision;
4. workspace filesystem mutation and test execution;
5. persistence test for the persistent profile across runtime restart;
6. cleanup test for the ephemeral profile, including credential and storage semantics;
7. negative RBAC evidence proving no undeclared Kubernetes API authority;
8. negative network evidence proving undeclared egress is blocked;
9. positive connectivity evidence for explicitly allowed Git, inference and one tool/MCP capability;
10. secret/redaction evidence showing credentials do not appear in manifests, logs or exported evidence;
11. resource-bound evidence showing CPU/memory/storage constraints are enforced;
12. one OpenCode workspace execution using the same contract candidate;
13. one conceptual or executable second runtime mapping demonstrating runtime replaceability;
14. evidence/export behavior before ephemeral deletion;
15. a documented isolation claim stating exactly what the Namespace profile does and does not protect against; and
16. a GO / REVISE / STOP verdict for the Namespace reference profile and OpenCode reference runtime.

Acceptance of this ADR does not automatically make OpenCode or the Namespace profile production ready. Implementation profiles may retain their own readiness gates.

## Non-goals

This ADR does not make OpenCode mandatory, standardize a browser IDE, define Git hosting or merge policy, grant production deployment authority to agents, replace CI/CD or GitOps, specify an MCP implementation, claim Namespace isolation equals a VM, or require every OpenKubes installation to enable Developer Workspaces.

## Revisit triggers

Revisit this ADR when Namespace isolation is insufficient for a real consumer, a second coding-agent runtime exposes a contract mismatch, a non-coding developer environment forces new semantics, multi-cluster workspace placement becomes necessary, accelerator semantics become necessary, or publication/PR operations require a dedicated authority contract.

## References

- OK-174 — Developer Workspace Contract spike
- ADR-Platform-001 — Contracts, not Components
- ADR-Platform-005 — Shared AI Services
- ADR-Platform-011 — GitOps / Secret Contract
- ADR-Platform-015 — Agentic AI
- ADR-Platform-017 — Constraint Envelopes
- ADR-Platform-020 — Shared Platform Services
- ADR-Platform-034 — authorized desired-state transitions
- OpenCode — first forcing/reference coding-agent runtime
