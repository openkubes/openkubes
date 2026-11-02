<!-- Comment for OK-211, in English as BRIEF requires for all drafts. Posted after approval on 2026-11-02. -->

**Spike result OK-211 — Knative as an optional serverless / event-driven capability**

Proposed outcome: **CONDITIONAL GO**. We propose drafting an ADR for an **opt-in** capability with two product-neutral contracts: request-driven workloads and event routing. Knative would be the first implementation profile, initially in the `datacenter` envelope. This is not a rollout and not an implementation commitment. Decision in the three-way review (Gawenda, Arash).

Tested on a dedicated VM built to the ok-local profile: K3s v1.35.5, Knative 1.23 → 1.24.

- **Serving:** scale-to-zero ≈ 95 s with defaults. Cold start with a cached image: median 1.35 s; without cache 7–9 s (73–79 % of it image pull). Autoscaling 0 → 6 pods in 9 s, 0 errors across 1.1 million requests. Traffic split, tag routes and rollback work.
- **Eventing:** delivery, filters, retries and the dead-letter sink work. The InMemoryChannel is not durable: a dispatcher restart lost every event that was in delivery. The sender always received an error for those events.
- **Upgrade 1.23 → 1.24 under load:** 0 of 476 requests failed. This needed three derivation rules on the release manifests, because server-side apply otherwise conflicts on fields that controllers own at runtime.
- **ADR-010:** a single entry point through Traefik (`ok-ingress`) with Kourier as ClusterIP works. TLS for Knative, however, terminates at Kourier, not at the entry point.
- **Security:** PSA `restricted` and namespace-scoped rights are enough. **Finding:** on K3s' embedded kube-router, a default-deny NetworkPolicy did not apply to newly started pods for ≥ 10 min, i.e. to every cold start.
- **GitOps:** a re-apply runs without conflicts, but `pingsource-mt-adapter` drifts permanently. The Argo CD test (G3) was not run.

Conditions (proposed follow-ups, no tickets created):

1. Resolve the GitOps drift and runtime-owned fields; evaluate the Knative Operator
2. Decide TLS termination and the entry point for ADR-010
3. Re-test NetworkPolicy on the target CNI
4. Durable eventing only after an ADR-029 decision
5. Verify KServe on Knative 1.24

Effort (estimate): 33–59 person-days; 25–44 without durable eventing.

Report: `architecture/spikes/OK-211-knative-serverless/REPORT.md`, management summary next to it. PR for review: https://github.com/openkubes/openkubes/pull/463 (branch `spike/OK-211-knative-serverless`).

Arash, the PR is ready for your review.
