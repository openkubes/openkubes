# ADR-Platform-024: Observability install and readiness gate as an opt-in ok-cluster command

**Date:** 2026-07-25
**Status:** Draft — proposed for review; not yet accepted

**Clarifies:** ADR-Platform-018
**Related:** ADR-Platform-009, ADR-Platform-011, ADR-Platform-014, ADR-Platform-017, OK-77, OK-79, OK-109

---

## Context

ADR-Platform-018 accepted the per-cluster observability capability and its v1 contract, and recorded as a *consequence* that "the ok-cluster provisioning workflow gains a readiness gate: `make new` (or its GitOps successor) is complete only when the observability contract test passes", with the stack delivered "as part of provisioning, analogous to `install-storage`".

OK-77 delivered only the ADR and the `ok-observability` repository scaffold. OK-79 delivered the capability content, the contract test, and the ok-cluster integration — and in doing so exposed that the ADR-018 consequence clause was not implementable as written:

- ok-cluster's `new` target only scaffolds and renders manifests. It never touches a live cluster, so it cannot run a test that requires a reachable Kubernetes API, a working StorageClass, and a running stack.
- The contract test needs Provider Values that only exist after the workload cluster is live (target kubeconfig, storage class, alert receiver endpoint, admin credentials).
- ADR-018's own Constraint Envelope Clause already anticipates clusters that cannot carry the reference stack (ADR-014/017). An install wired unconditionally into cluster creation would have to be special-cased there.

OK-79 therefore reframed the delivery: the install and its gate are an explicit, separate command. This is a material narrowing of an accepted consequence clause and is recorded here rather than by editing ADR-018.

---

## Decision

> Installing the observability capability into a workload cluster and verifying it against the Observability Capability Contract v1 is **one explicit, opt-in, gated ok-cluster command** — not an implicit step of cluster creation. "Provisioned" and "observability-ready" are two distinct cluster states.

Concretely:

- The entry point is a single ok-cluster target (`make install-observability CLUSTER=<name>`), modeled on `install-storage`. It is **not** invoked by `make new`, `bootstrap`, or `register-cluster`.
- The target is **gated**: it installs the `ok-observability-standard` profile and then runs the contract test, and exits non-zero unless every contract guarantee passes. A cluster is "observability-ready" only when that command is green.
- The **invocation seam** is a stable entry point in the capability repository, `ok-observability/tests/contract-test.sh`, whose exit code is the gate. ok-cluster depends on that script's invocation contract (exit code + stdout), not on the test's internals.
- **Provider Values are supplied by the consumer at invocation time and never committed into the capability repository**: target kubeconfig, alert receiver endpoint, storage class (taken from the storage contract, ADR-009, not hardcoded), and admin credentials.
- Credentials are passed **by reference**: ok-cluster materializes a Kubernetes Secret in the target cluster from a git-ignored provider-values file, and the charts consume it by reference (Grafana `admin.existingSecret`, OpenSearch `secretKeyRef`, log collector via environment). No plaintext credential is passed to Helm, committed, or rendered into a ConfigMap. This Secret shape is deliberately Vault-ready: replacing the Secret-creation step with an External-Secrets sync from the ok-shared Vault requires no chart change.
- Ownership is unchanged from ADR-018: ok-cluster *installs* the capability; all assets (profile, dashboards, rules, alerting config, contract test, docs) remain owned by `ok-observability`.

### What this changes in ADR-Platform-018

Only the consequence clause quoted above. The Capability, the Contract v1 guarantees, the Implementation Profile, the Provider Values list, and the six-step verification remain as accepted. ADR-018 remains `Accepted`; the contract test is still the sole definition of "observability-verified" — this ADR decides only *when and how* it is invoked.

---

## Rationale

1. **The gate must run against a live cluster.** Attaching it to a render-only step would either make the gate vacuous or force `new` to grow live-cluster behaviour it deliberately does not have.
2. **Layer ordering stays explicit.** Observability depends on a working StorageClass installed by a separate command; an explicit sequence (`bootstrap → install-storage → install-observability`) keeps the dependency visible instead of hiding it inside one target.
3. **Envelope compatibility.** ADR-017 requires reductions to be declared, not silent. An opt-in command lets a constrained-edge cluster legitimately not run the standard profile without special-casing the creation path.
4. **Consumer/owner boundary preserved.** Pinning the gate behind one script in the capability repo keeps the test's implementation replaceable without touching ok-cluster.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Auto-invoke the install + gate from `make new` (literal ADR-018 wording) | `new` only renders; no live cluster, no kubeconfig, no storage class at that point |
| Gate `bootstrap` or `register-cluster` instead | Forces every cluster to pay the stack's resource cost at creation and conflicts with the edge envelope; also inverts the storage → observability ordering |
| Install without a gate, verify separately | An unverified contract is not a contract (ADR-018) |
| Let ok-cluster own the assets so no cross-repo seam is needed | Contradicts ADR-018's ownership split and the ok-storage precedent |

---

## Consequences

**Positive:**
- The gate is real and runs where it can actually observe the guarantees; proven end-to-end on ok-shared and ok-robotics.
- Cluster creation stays render-only and provider-neutral.
- Credentials never enter Git, Helm arguments, or rendered output; the Vault migration is a swap of one step.

**Negative / trade-offs:**
- "Every OpenKubes cluster is observable" (ADR-018) becomes an **operator-invoked** guarantee rather than a structurally enforced one: nothing currently prevents a cluster from being registered and used without a green gate. Continuous assertion of observability readiness for an already-provisioned cluster is not covered here.
- ok-cluster now depends on an out-of-repo script's invocation contract.

## Open items, to be resolved by amendment

1. **ok-observability ref pin — unresolved.** ok-cluster currently locates the capability through a filesystem path to a sibling checkout (`OK_OBSERVABILITY_PATH`, default `../ok-observability`) and therefore consumes whatever revision happens to be on disk. Where and how the consumed ok-observability ref is pinned (Makefile variable, dedicated version file, or `cluster-config.yaml`) is **open**; tracked in OK-109.
2. **Enforcement / drift.** How observability readiness is asserted for an already-provisioned cluster — and whether it belongs in the OK-78 phase/conformance model or in the GitOps successor path (ADR-011) — is open.
3. **Vault phase 2.** Replacing Secret creation with an External-Secrets sync from the ok-shared Vault is deferred (OK-109).
4. ADR-018's constrained-edge open item is unaffected: the `ok-edge-constrained` observability variant still requires an amendment to ADR-018 before that profile can be accepted.

## Re-evaluation triggers

- GitOps delivery becomes standard (ADR-011) → the gate's home moves from the Makefile path to the GitOps/conformance path; revisit this ADR.
- A consumer requires observability readiness as a precondition of cluster registration (ADR-013) → re-open the enforcement question.
- The constrained-edge observability variant is defined → confirm the opt-in placement is still sufficient or amend.
