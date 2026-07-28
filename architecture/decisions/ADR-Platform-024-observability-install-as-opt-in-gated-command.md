# ADR-Platform-024: Observability install and readiness gate as an opt-in ok-cluster command

**Date:** 2026-07-25
**Status:** Accepted — three-way review (Arash / Claude / GPT); human acceptance by Arash 2026-07-28. All "Path to acceptance" evidence complete: the credential-hardening fix landed (ok-cluster `463cfd8`), and the post-fix gate re-run passed on `ok-obs-verify` 2026-07-27 (all five guarantees) with both consumed revisions recorded (ok-cluster `f67aa1a`, ok-observability `6ed389d`). Accepted by the human reviewer, not self-accepted by the party that produced the evidence.

**Amends:** ADR-Platform-018 (scope: only the provisioning / readiness-gate consequence clause; the Capability, Contract v1 guarantees, Implementation Profile, Provider Values, and six-step verification are unchanged)
**Related:** ADR-Platform-009, ADR-Platform-011, ADR-Platform-014, ADR-Platform-017, ADR-Platform-020, OK-71, OK-77, OK-78, OK-79, OK-80, OK-109, OK-110

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
- The **invocation seam** is a stable entry point in the capability repository, `ok-observability/tests/contract-test.sh`. **The exit code is the normative machine contract**; stdout and stderr are diagnostic only, unless a versioned machine-readable result format is introduced. ok-cluster depends on that exit-code contract, not on the test's internals or on any particular stdout shape.
  - **Exit-code classes, and where the distinction is lost.** The install path distinguishes a *precondition* failure (`2`, nothing installed, gate never invoked) from a *gate* failure (`1`, stack installed, contract unmet) — verified by the OK-109 spot-checks. **`make` flattens both to its own generic error status**, so a consumer invoking the script directly can act on the distinction while a consumer going through the make target cannot. Any automation that needs to tell "not attempted" from "attempted and failed" must invoke the script, not the target.
- **Provider Values are supplied by the consumer at invocation time and never committed into the capability repository**: target kubeconfig, alert receiver endpoint, storage class (taken from the storage contract, ADR-009, not hardcoded), and admin credentials.
- Credentials are consumed **exclusively through Kubernetes Secret references**: the charts read a named Secret (Grafana `admin.existingSecret`, OpenSearch `secretKeyRef`, Fluent Bit `${OPENSEARCH_PASSWORD}` env from the same Secret). During phase 1, ok-cluster materializes that Secret from a local git-ignored provider-values source. **Secret values MUST NOT be exposed through process arguments, shell tracing, stdout or stderr, logs, temporary rendered manifests, or ConfigMaps** — the reference implementation writes values to `0600` files under a `umask 077` temp dir and feeds them via `kubectl --from-file` (wiped on exit), never `--from-literal`. The Secret shape is deliberately Vault-ready: the secret backend remains an envelope-specific Implementation Profile under the Secret Contract (ADR-Platform-011 §Secret Contract, OK-71), and replacing the Secret-creation step with a Vault sync from ok-shared — a `VaultStaticSecret` via the Vault Secrets Operator, per **ADR-Platform-025** (OK-110) — requires no chart change.
- Ownership is unchanged from ADR-018: ok-cluster *installs* the capability; all assets (profile, dashboards, rules, alerting config, contract test, docs) remain owned by `ok-observability`.

### What this changes in ADR-Platform-018

Only the consequence clause quoted above. The Capability, the Contract v1 guarantees, the Implementation Profile, the Provider Values list, and the six-step verification remain as accepted. ADR-018 remains `Accepted`; the contract test is still the sole definition of "observability-verified" — this ADR decides only *when and how* it is invoked.

---

## Rationale

1. **The gate must run against a live cluster.** Attaching it to a render-only step would either make the gate vacuous or force `new` to grow live-cluster behaviour it deliberately does not have.
2. **Layer ordering stays explicit.** Observability depends on a working StorageClass installed by a separate command; an explicit sequence (`bootstrap → install-storage → install-observability`) keeps the dependency visible instead of hiding it inside one target.
3. **Envelope compatibility — with an explicit state model.** Opt-in placement keeps the standard install out of the creation path, but it is an *execution-placement* decision, not an envelope declaration. **Not invoking the command does not itself constitute an approved Constraint Envelope reduction. A cluster that does not install the standard observability profile MUST either declare an applicable reduction under ADR-017 or remain explicitly `observability-not-ready`.** The three resulting states — (a) *observability-ready* (standard profile, green gate; OK-79), (b) *declared reduction* (an ADR-017 / ADR-018 edge-variant amendment, OK-80), and (c) *observability-not-ready* — and how readiness is asserted/enforced for an already-provisioned cluster are the subject of the phase model (OK-78).
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
- The gate is real and runs where it can actually observe the guarantees; initially proven end-to-end on ok-shared and ok-robotics (pre-hardening run). The authoritative evidence — both consumed commit hashes from a post-credential-hardening gate run — is recorded under "Path to acceptance" before this ADR moves to Accepted.
- Cluster creation stays render-only and provider-neutral.
- Credentials never enter Git, Helm arguments, or rendered output; the Vault migration (OK-110) is a swap of one step.

**Operational:**
- Re-running the command MUST be safe (idempotent — `helm upgrade --install` + `kubectl apply`). A successfully installed stack does **not** imply observability readiness; only the latest successful contract-gate result establishes the `observability-ready` state.

**Negative / trade-offs:**
- "Every OpenKubes cluster is observable" (ADR-018) becomes an **operator-invoked** guarantee rather than a structurally enforced one: nothing currently prevents a cluster from being registered and used without a green gate. Continuous assertion of observability readiness for an already-provisioned cluster is not covered here.
- ok-cluster now depends on an out-of-repo script's invocation contract.

## Open items, to be resolved by amendment

1. **ok-observability ref pin — recording half implemented; durable pin still open.** ok-cluster locates the capability through a filesystem path to a sibling checkout (`OK_OBSERVABILITY_PATH`, default `../ok-observability`) and therefore consumes whatever revision happens to be on disk. The **invariant is normative**: a durable, reproducible observability-readiness result MUST identify the consumed `ok-observability` revision. The *recording* half of that invariant now holds — `install-observability.sh` resolves and prints both consumed revisions with a clean/`DIRTY` marker, warns that a dirty checkout is not reproducible conformance evidence, and honours an optional `OK_OBSERVABILITY_REF` that asserts which revision a run may consume and fails loudly on mismatch (it deliberately does not check the sibling repo out). The sibling-checkout mechanism therefore remains **transitional** but no longer produces unattributable evidence. Still open: where the *durable* pin lives (Makefile variable, dedicated version file, or `cluster-config.yaml`); tracked in OK-109.
2. **Enforcement / drift.** How observability readiness is asserted for an already-provisioned cluster — and whether it belongs in the OK-78 phase/conformance model or in the GitOps successor path (ADR-011) — is open.
3. **Vault phase 2.** Replacing Secret creation with a Vault sync from ok-shared is deferred — tracked in **OK-110** (Vault standup; blocks OK-109 Part 2), governed by the **Secret Contract** (ADR-Platform-011 §Secret Contract, amendment 2026-07-25, OK-71) and profiled by **ADR-Platform-025** (Draft), which selects **Vault + Vault Secrets Operator (VSO)** for the datacenter envelope and rejects ESO *for that envelope only*. Under the contract the secret *tool* is an Implementation Profile per envelope, not part of the contract, so the phase-1 file-based Secret remains the offline-reconcilable profile for constrained-edge and **stays** — it is not superseded by phase 2. Note ADR-025's own scoping: the observability credential proves *provisioning and migration*, not that this bootstrap password is rotatable by Secret replacement alone.
4. ADR-018's constrained-edge open item is unaffected: the `ok-edge-constrained` observability variant still requires an amendment to ADR-018 before that profile can be accepted.

## Path to acceptance

This ADR stays **Draft** until its own credential invariant holds in the reference implementation:

1. ~~**Fix the credential exposure**~~ in `ok-cluster/install-observability.sh` — the Secret is created via `kubectl --from-file` from `0600` temp files (`umask 077`, wiped on exit), never `--from-literal`. **Done: ok-cluster `463cfd8` on `main`.**
2. ~~**Make the evidence attributable and the install non-vacuous.**~~ **Done:** gate passthrough + consumed-revision evidence + empty-render guard (ok-cluster `30648be`), the durable ref pin (ok-cluster `c3ef580`), and the two-level chart dependency build (ok-observability `349b280`). The last mattered for this ADR specifically: the profile is a two-level umbrella, so on a fresh clone it rendered to nothing and Helm installed a release with **no workloads** — a state in which a "successful install" is meaningless, which is precisely why the Consequences above insist that a successfully installed stack does not imply readiness.
3. ~~**Re-run** install + gate on a reference cluster~~ **Done 2026-07-27** on the throwaway `ok-obs-verify` (Talos, 1 CP + 3 workers): **Contract Test Gate PASS, all five guarantees** (run `1785164209-35440`). Both partial-failure spot-checks also exercised: a forced gate failure left the install intact while cleaning test resources, and a pre-gate precondition failure never invoked the gate.
4. ~~**Record evidence**~~ **Done** — consumed `ok-cluster f67aa1a`, consumed `ok-observability 6ed389d` (clean, pin-verified). Full evidence in OK-109. One caveat on that line: ok-cluster printed `DIRTY`, caused solely by the untracked `<cluster>/` render directory that `make new` creates, with zero tracked modifications — the provenance check counts untracked files, so a *fresh-cluster* run always trips it. Being corrected to `--untracked-files=no`; until then read `DIRTY` on a first run as "unclassified", not as modified code.
5. ~~**Remaining, and the only open item:** set `Status: Accepted` and merge — reserved for a human reviewer, not the evidence producer.~~ **Done: accepted by Arash 2026-07-28 (see Status).**

Note the coupling: this ADR's acceptance and OK-109's Part 1 re-verify are the **same evidence run**, not two independent tasks.

## Re-evaluation triggers

- GitOps delivery becomes standard (ADR-011) → the gate's home moves from the Makefile path to the GitOps/conformance path; revisit this ADR.
- A consumer requires observability readiness as a precondition of cluster registration (ADR-013) → re-open the enforcement question.
- The constrained-edge observability variant is defined → confirm the opt-in placement is still sufficient or amend.
