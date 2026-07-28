# ADR-Platform-027: Assurance scope of the observability contract gate — control-plane-mediated reachability only

**Status:** Draft — awaiting human review. Records a ruling made on OK-109 (2026-07-27); not self-accepted by the party that produced the evidence.
**Date:** 2026-07-28
**Deciders:** Arash (final) · Claude
**Scopes:** ADR-Platform-018 §Verification (Contract Test), ADR-Platform-024 (gate invocation seam)
**Related:** OK-109 (Part 1 re-verify), OK-119 (ok-cluster `install-cni` Ubuntu path), ADR-Platform-021 (evidence status must be explicit, never silently reduced)

---

## Context

ADR-018 defines the five-guarantee Observability Capability Contract v1 and states that a
cluster is not fully provisioned until the contract test passes. ADR-024 makes that gate an
explicit opt-in ok-cluster command and makes its **exit code** the normative machine contract
for the `observability-ready` state.

The reference implementation reaches every target service through `kubectl port-forward`, and
Prometheus scrapes the synthetic target via the API server by IP. Both paths are mediated by
the control plane and neither traverses the cluster's pod network or the cluster DNS service.

This is not theoretical. During the OK-109 Part 1 work, guarantee #1 (ServiceMonitor
registration → Prometheus ingestion) passed on a cluster whose pod networking was
**completely unroutable**: Cilium had allocated pod IPs from its own range instead of the CAPI
podCIDR, cluster health was 1/4 reachable, and there was no pod DNS at all (the Ubuntu
`install-cni` defect tracked as OK-119). The gate reported a green guarantee on a cluster that
could not resolve `kubernetes.default.svc.cluster.local` from a pod. The misleading green cost
about an hour of misdirected diagnosis.

## Decision

> The observability contract gate asserts **control-plane-mediated reachability** of the five
> guarantees. It does **not** assert in-cluster service resolution, pod-to-pod routing, or
> cluster DNS. A green gate is therefore **not** evidence that pod networking is healthy, and
> `observability-ready` must be read with that boundary.

Concretely:

- The gate's transport (port-forward for service checks, API-server-proxied scrape for
  ingestion) is a **deliberate, documented limitation of the gate's assurance**, not a defect
  to be fixed. It is the same class of documented weaker pass as the *fired-only* alert
  guarantee (`CONTRACT_TEST_RECEIVER_CAPTURE_URL` unset) — explicit, not silent.
- **The gate is not hardened to detect this.** Adding an in-cluster reachability probe was
  considered and declined: pod-network health is the CNI layer's contract, not the
  observability capability's, and a probe in the gate would place a networking assertion
  behind an observability exit code.
- Consequently, **pod-network health is a precondition of reading a gate result, and belongs
  to the caller.** A gate result read from a cluster whose CNI health is degraded (for Cilium:
  anything below `Cluster health: N/N reachable`) is not valid conformance evidence — the run
  must be treated as unclassified and repeated on a healthy cluster.

## Rationale

1. **Layer ownership.** ADR-018's guarantees are about observability signals, not about the
   network. Folding a CNI assertion into the observability gate would make one exit code speak
   for two contracts and would fail in a way that names the wrong owner.
2. **Explicit over silent.** ADR-021 already establishes the platform-wide rule that reduced
   evidence is reported explicitly rather than by silently returning less. Naming this boundary
   in an ADR is the equivalent of `status: unavailable` with a reason.
3. **The failure mode is narrow and diagnosable once named.** The symptom set is distinctive
   (CNI health below full, no pod DNS, log-collector crash-looping) and the correct check is one
   command against the CNI, run before the gate — cheaper and better-placed than a gate feature.
4. **The blind spot is bounded by the existing hardening.** The gate does not produce contentless
   passes for unreachable services: each port-forward is health-probed — it must actually carry
   traffic before the check proceeds, and otherwise fails loudly rather than silently. What
   remains is exactly the network-path gap decided above, not a general false-positive class.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Add an in-cluster reachability / DNS probe to the gate | Puts a CNI assertion behind an observability exit code; wrong contract owner (rationale 1) |
| Run the guarantee checks from an in-cluster pod instead of via port-forward | Larger change to the invocation seam and its credential handling for a gap the caller can check in one command; not justified by any observed incident |
| Treat the misleading green as a gate defect and file a hardening ticket | Declined explicitly by the ADR-018/024 owner on OK-109; the gap is documented instead |
| Leave it undocumented (status quo before this ADR) | The green already misled a run once; an unrecorded limitation on a normative readiness state is exactly what an ADR is for |

## Consequences

**Positive:**
- `observability-ready` has a stated assurance boundary, so a green gate can no longer be cited
  as evidence of cluster network health.
- The CNI defect class stays visible as a CNI problem (OK-119) instead of being absorbed into
  observability flakiness.

**Negative / trade-offs:**
- The gate can still return a green guarantee on a cluster that is not usable in practice. This
  is accepted; detection is the caller's responsibility and is not enforced by any tooling
  today.
- One more precondition an operator must remember before reading gate output.

## Re-evaluation triggers

- The blind spot masks a real incident (the owner's stated condition for revisiting the
  hardening decision on OK-109).
- The gate moves into the GitOps/conformance path (ADR-011), where there is no operator to
  check CNI health first — then the precondition must become machine-enforced, by the
  conformance layer or by the gate.
- A cluster-network conformance contract is defined — it, not this ADR, becomes the home of the
  positive assertion.
