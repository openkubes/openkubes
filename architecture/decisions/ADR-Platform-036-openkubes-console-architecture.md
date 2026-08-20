# ADR-Platform-036: Native OpenKubes Console — Curated First Delivery and Evolution toward Contract-Adaptive UI

**Date:** 2026-08-20

**Status:** Proposed

**Extends:** ADR-Platform-001, ADR-Platform-030, ADR-Platform-034

**Related:** ADR-Platform-004, ADR-Platform-013, ADR-Platform-015, ADR-Platform-021, ADR-Platform-023, ADR-Platform-035

**Spike:** OK-151

---

## Context

OpenKubes exposes a contract-governed platform model across cluster lifecycle,
Capabilities, workload Claims, normalized Conditions, authorization, and durable
Evidence. Its first native graphical interface should make that model approachable
without becoming a generic Kubernetes resource dashboard or creating a second source
of platform truth.

The current OpenKubes implementation already provides enough stable concepts and
observable state to prototype a useful first Console relatively quickly. A small set
of deliberately designed screens can cover the initial product path:

1. platform and Cluster overview;
2. Cluster lifecycle and Evidence inspection; and
3. Cluster declaration and Contract review.

It would be counterproductive to block that first feedback loop on a generic schema
renderer, a stable public Presentation Contract, or autonomous AI-driven UI adaptation.
Those mechanisms do not yet have forcing-consumer evidence and are not required to
validate the Console's primary product model.

At the same time, a tightly coupled frontend that embeds backend field names,
provider-specific implementation details, or lifecycle authority assumptions throughout
its components would make later Contract evolution unnecessarily expensive. OpenKubes
therefore needs an explicit delivery sequence and architectural seams that permit a
future contract-adaptive Console without claiming that capability in the first release.

This ADR defines that evolution path. It does not select a frontend framework, prescribe
a final Console API, accept a `ConsoleDescriptor` schema, or authorize an AI model to
change executable behavior.

## Decision drivers

- Deliver a useful, visually coherent first Console quickly against the current
  OpenKubes implementation.
- Validate user journeys before designing a generic presentation system.
- Keep OpenKubes Contracts, not frontend components, authoritative for platform
  semantics.
- Preserve the Policy, Authority, Contract Executor, and controller boundaries from
  ADR-030, ADR-034, and ADR-035.
- Make Conditions and Evidence understandable without turning decorative UI state into
  a new readiness claim.
- Avoid coupling the product surface to one infrastructure provider, controller,
  transport, or frontend technology.
- Preserve a deliberate path to stable Presentation Contracts and optional schema- and
  AI-assisted adaptation.
- Fail closed for mutation when Contract or presentation compatibility is unknown.

## Decision

OpenKubes adopts a **curated-first, contract-aligned Console architecture** with an
explicit evolution path toward optional contract-adaptive presentation.

The delivery sequence is:

```text
graphical spike
      |
      v
small curated prototype
      |
      v
real user feedback and backend experience
      |
      v
stable Presentation Contracts
      |
      v
optional schema- and AI-adaptive Console
```

Each step must produce evidence for the next. Later steps are not prerequisites for the
first prototype, and the sequence is not a commitment that every optional step will be
implemented.

### 1. Graphical spike

OK-151 is the forcing design spike for the initial Console. It defines and reviews the
information architecture, visual system, primary product objects, critical user flows,
and explicit trust-boundary representation without creating application code.

The spike must cover at least:

- Platform Overview with `ok-mgmt` visibly distinguished as the Management Plane;
- Cluster detail with lifecycle, normalized Conditions, and Evidence navigation;
- Cluster declaration and Contract review with distinct Draft, Review, Authorization,
  Execution, and Evidence states;
- basic responsive and accessibility intent; and
- a design decision record with a `GO`, `REVISE`, or `STOP` recommendation for a first
  implementation.

The first AI-generated concept is historical seed material, not accepted product design
or architectural evidence by itself.

### 2. Small curated prototype

If the graphical spike returns `GO`, the first implementation should use a small number
of deliberately designed, manually curated screens against the currently supported
OpenKubes Contract surface.

The first prototype:

- SHOULD optimize the three primary flows identified above;
- MAY use manually maintained presentation mappings or an internal adapter;
- MUST NOT require a generic schema-rendering engine;
- MUST NOT require a stable public Presentation Contract;
- MUST NOT claim automatic adaptation to arbitrary backend changes;
- MUST keep provider-specific resources behind OpenKubes product concepts where the
  applicable Contract already provides that abstraction; and
- MUST preserve the authority and evidence boundaries in this ADR.

The prototype is permitted to support an explicitly bounded set of Contract versions.
Its supported-version set must be inspectable rather than inferred from successful
rendering.

### 3. Architectural seams required from the first implementation

Although dynamic adaptation is not a first-version requirement, the initial Console
must avoid decisions that make it impractical later. The implementation architecture
must preserve distinct boundaries for:

1. **Domain data** — versioned OpenKubes Contracts and their instances;
2. **Observed state** — Contract-defined, revision- and generation-correlated Conditions;
3. **Evidence projection** — redaction-safe references and summaries suitable for the
   current user and authority context;
4. **Presentation mapping** — labels, grouping, ordering, controls, and navigation that
   may initially be curated in the frontend or an internal adapter;
5. **Compatibility evaluation** — the declared relationship between a supported
   Contract version and the Console presentation that understands it; and
6. **Operation invocation** — explicit calls into existing review, Policy, Authority,
   and Contract Executor paths rather than mutation embedded in a renderer.

These are logical seams, not a mandate for six services or repositories. A monolithic
prototype may implement them internally provided their responsibilities remain
distinguishable and testable.

Internal backend refactoring that preserves the published OpenKubes Contract must not
require a Console change. A published Contract change is the compatibility boundary the
Console evaluates.

### 4. Future Presentation Contracts

After real prototype use provides forcing-consumer evidence, OpenKubes may define a
separate, versioned Presentation Contract describing how a Domain Contract is presented.
Candidate semantics include:

- product labels and descriptions;
- list columns and primary identity fields;
- form groups, field ordering, and visibility rules;
- read-only Condition and Evidence projections;
- links between related product objects;
- capability-specific visual extensions; and
- declarations of available operations and the authority boundary each operation must
  enter.

A Presentation Contract is not a Domain Contract, Policy decision, authorization,
desired-state authority, readiness source, or execution instruction. It may describe an
operation, but it cannot grant permission to perform it. Server-side Contract,
authentication, Policy, authorization, concurrency, and point-of-use checks remain
normative.

The final representation, API group, storage, delivery mechanism, and lifecycle of a
Presentation Contract require separate acceptance evidence. Names such as
`ConsoleDescriptor` remain illustrative until that contract is accepted.

### 5. Optional contract-adaptive presentation

A later Console may interpret Domain and Presentation Contracts at runtime or build time
to reduce manual UI work. Compatibility classes should distinguish at least:

| Change class | Default presentation response |
|---|---|
| Additive optional field or read-only Condition | May be rendered automatically in a bounded fallback or advanced view |
| New enum member or validation constraint | May update a generated control after compatibility checks |
| New required field, changed default, rename, move, or type change | Requires explicit compatibility review and, where applicable, migration |
| Changed Condition or Evidence semantics | Requires Contract and UX review; must not be inferred from schema shape alone |
| New mutation, Authority, or authorization requirement | Must never be enabled solely by automatic rendering or AI output |

An unknown or incompatible presentation may retain a bounded read-only view when that
view can be produced without inventing semantics or exposing restricted data. Mutating
actions MUST fail closed until the exact Contract/presentation compatibility is reviewed.

The Console must not convert a field's presence, a schema default, a controller message,
or an AI interpretation into a normative OpenKubes Condition.

### 6. AI-assisted adaptation

AI may later assist the Console development workflow by:

- comparing old and new Contract schemas;
- classifying candidate presentation impact;
- proposing updated presentation metadata and human-readable copy;
- generating before/after visual reviews;
- proposing compatibility, accessibility, and regression tests; and
- preparing a reviewable change for human approval.

AI output remains untrusted candidate authoring input under the principles of ADR-035.
An AI model MUST NOT at runtime:

- declare a Contract compatible;
- create a normative Condition or Evidence statement;
- authorize, approve, or execute a mutation;
- invent an operation not present in a reviewed Contract surface;
- select or expand user authority; or
- silently change the effective payload presented for review.

AI assistance is optional. A conforming Console and Presentation Contract must remain
usable and testable without an LLM.

### 7. Authority, review, and execution boundary

The Console is a user experience over the existing control-plane model; it is not a new
control plane.

For every state-changing flow, the UI must preserve the semantic distinction:

```text
Draft -> Review -> Authorization -> Execution -> Observation -> Evidence
```

No visual consolidation may collapse those states into an implied direct mutation.
Displaying a button does not prove authorization. Disabling or hiding a button is a
usability measure, not a security boundary. The authoritative server-side path must
independently authenticate the caller, validate the exact Contract request, verify
Policy and authorization, enforce concurrency, and record the resulting Evidence.

The Console may display redaction-safe Evidence and correlation identities. It must not
require raw credentials, private Evidence payloads, or unrestricted kubeconfigs in the
browser to prove platform state.

### 8. Product objects and provider neutrality

The initial primary navigation model is organized around:

- Platform Overview;
- Clusters;
- Capabilities;
- Workloads or Claims; and
- Evidence and Audit.

Pods, Namespaces, CAPI resources, Crossplane managed resources, infrastructure-provider
objects, and controller internals may appear in explicit diagnostic drill-downs, but do
not become the top-level product information architecture merely because they are easy
to query.

Infrastructure providers, OS profiles, and other implementations remain selectable or
observable Implementation Profiles beneath the applicable OpenKubes Contract. A future
Presentation Contract must not make one provider's vocabulary normative for all
conforming distributions.

### 9. Version and provenance visibility

The Console must make the semantic basis of its display inspectable. For views that
support state-changing operations, the implementation must be able to identify at least:

- the Domain Contract kind and version;
- the presentation mapping or Presentation Contract version, when one exists;
- the supported compatibility decision; and
- the relevant revision, Condition, receipt, or Evidence correlation displayed to the
  user.

Digest binding between Domain Contract, Presentation Contract, renderer, and immutable
human-visible review artifacts is a candidate mechanism, particularly where ADR-035
WYSIWYS review applies. Its exact normative shape is deferred until the forcing flow and
artifacts exist.

### 10. Normative invariants

- **INV-036-1 — Curated-first delivery.** A generic renderer, stable Presentation
  Contract, and AI adaptation are not prerequisites for the first Console prototype.
- **INV-036-2 — Contract authority.** Frontend code and presentation metadata MUST NOT
  redefine Domain Contract validation, Conditions, Policy, authorization, or Evidence
  semantics.
- **INV-036-3 — Evolution seam.** The initial implementation MUST keep domain data,
  observed state, Evidence projection, presentation mapping, compatibility evaluation,
  and operation invocation logically distinguishable.
- **INV-036-4 — Fail-closed mutation compatibility.** An unknown or incompatible
  Contract/presentation combination MUST NOT expose or invoke a mutating operation.
- **INV-036-5 — Server enforcement.** UI visibility and enablement are not security
  boundaries; every mutation MUST traverse the authoritative server-side Contract,
  Policy, authorization, concurrency, and execution controls.
- **INV-036-6 — AI non-authority.** AI output is an untrusted proposal and MUST NOT by
  itself establish compatibility, readiness, authority, or execution intent.
- **INV-036-7 — Evidence fidelity.** The Console MUST distinguish desired intent,
  observed state, immutable historical outcome, and current health, and MUST NOT present
  a decorative state as normative Evidence.
- **INV-036-8 — Provider neutrality.** Presentation MUST remain organized around
  OpenKubes Contracts and Implementation Profiles rather than promote one provider's
  resources to universal platform semantics.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Build a generic schema-driven Console before any curated prototype | Delays user feedback, assumes presentation semantics before forcing-consumer evidence, and makes an optional mechanism a v1 dependency |
| Hard-code the first UI directly to backend implementation objects | Produces a fast demo but couples product semantics to controllers and providers, making Contract evolution and distribution portability costly |
| Allow AI to regenerate and deploy the UI automatically after backend changes | Treats non-deterministic output as a compatibility and release authority and can silently expose changed mutations or misleading semantics |
| Use a generic Kubernetes dashboard as the OpenKubes Console | Exposes resources but does not express OpenKubes Contracts, Authority boundaries, Claims, normalized Conditions, or durable Evidence as the product model |
| Define the full Presentation Contract in this ADR | Prematurely freezes an API before the graphical spike and curated prototype reveal the required semantics |
| Never support adaptive presentation | Keeps the initial implementation simple but needlessly closes a valuable path for future Capabilities, distributions, and AI-assisted maintenance |

## Consequences

### Positive

- A first Console can be prototyped quickly against the current implementation.
- Product and visual feedback arrive before a generic presentation architecture is
  standardized.
- The UI remains aligned with OpenKubes Contracts and existing security boundaries.
- Future schema-driven or AI-assisted adaptation remains possible without being
  promised for v1.
- New Capabilities can later share a presentation mechanism without making it a source
  of Domain semantics or authority.
- The same versioned Domain Contracts may serve Console, CLI, and agent consumers while
  their identities and Authorities remain separate.

### Costs and risks

- Curated presentation mappings require manual maintenance during the first phase.
- The internal presentation seam may later need migration to a stable public Contract.
- Supporting multiple Contract versions requires explicit compatibility tests and a
  bounded support policy.
- A generic fallback can produce technically valid but poor UX if it is allowed to
  replace curated primary flows.
- AI-generated presentation changes can appear plausible while misrepresenting business
  semantics; mandatory review and server enforcement reduce but do not eliminate that
  risk.
- Read-only fallback still requires authorization and redaction design; read-only is not
  synonymous with safe for all users or Evidence.

## Acceptance criteria

This ADR may advance from `Proposed` only when reviewed spike and prototype evidence
demonstrate at least:

1. **Graphical product model:** OK-151 produces reviewed designs for the three primary
   flows and records a `GO`, `REVISE`, or `STOP` recommendation.
2. **Curated feasibility:** A bounded implementation plan shows that the first prototype
   can consume the current OpenKubes backend without first building a generic renderer or
   stable Presentation Contract.
3. **Boundary visibility:** The design visibly distinguishes Draft, Review,
   Authorization, Execution, Observation, and Evidence.
4. **Management-plane identity:** `ok-mgmt` is clearly distinguished from workload
   Clusters without creating provider-specific top-level semantics.
5. **Evidence fidelity:** Readiness displays trace to Contract-defined Conditions and
   redaction-safe Evidence rather than UI-owned health calculations.
6. **Compatibility seam:** The proposed implementation identifies explicit boundaries
   for domain data, presentation mapping, compatibility, and operation invocation.
7. **Fail-closed example:** At least one unknown or incompatible Contract-version case
   demonstrates that mutation is unavailable while a safe diagnostic response remains
   understandable.
8. **AI non-authority review:** Any AI-assisted design or compatibility proposal is
   reviewed as candidate input and cannot independently affect runtime authority.
9. **Accessibility review:** The primary designs are reviewed for readable contrast,
   non-color-only status meaning, and keyboard-oriented interaction intent.
10. **Evolution decision:** Prototype evidence records whether a stable Presentation
    Contract should proceed, be revised, or remain deferred; this ADR does not presume
    acceptance of that later Contract.

## Re-evaluation triggers

- A stable public Presentation Contract or `ConsoleDescriptor` is proposed.
- Runtime schema rendering is proposed for primary mutating workflows.
- AI-generated presentation changes are proposed for automatic deployment or runtime
  activation.
- The Console is proposed as a Policy Authority, Contract Executor, desired-state
  authority, readiness evaluator, or Evidence source.
- The first curated prototype cannot support the current backend without material
  changes to Domain Contracts.
- Provider-specific UI requirements cannot be expressed as replaceable Implementation
  Profile presentation.
- The separation between immutable historical transition outcome and current platform
  health changes materially.
