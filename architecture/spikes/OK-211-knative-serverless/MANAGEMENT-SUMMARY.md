# OK-211 — Knative as an optional serverless capability: management summary

*Details and sources: [REPORT.md](REPORT.md). Every number below comes from there.*

**Question.** Can Knative provide OpenKubes with an *optional* capability where apps scale up on demand and down to nothing when idle, and react to events, without changing the core platform?

**Answer.** Yes, with conditions. We propose drafting an architecture decision for such an opt-in capability, with Knative as its first implementation, for datacenter clusters (**CONDITIONAL GO**). This is not a rollout decision.

**What we tested.** We ran a full lab installation on a copy of our local cluster profile, then measured in eight areas:

- scaling and start-up times;
- event delivery and failure handling;
- an upgrade under live traffic;
- integration with our single ingress entry point;
- encrypted connections (TLS);
- tenant isolation and security;
- metrics;
- declarative (GitOps) operation.

**Benefits**

- **Pay only when used:** idle apps scale to zero after about 1.5 minutes and start again on the first request in about 1.3 seconds (median, cached image).
- **Elastic under load:** 0 → 6 instances in 9 seconds, with zero errors across 1.1 million requests.
- **Safe rollouts:** run two versions side by side with a percentage split, and roll back instantly by moving traffic.
- **Event-driven apps:** events are filtered, retried and parked on failure, and can wake apps that were scaled to zero.
- **Fits our architecture:** it works behind our one ingress entry point. Tenants need no cluster-wide rights. Release images are signed and verifiable.

**Risks**

- **Upkeep:** Knative ships 4 releases a year, each supported about 6 months. Its standard install files needed three corrections before our declarative tooling could re-apply them, and one setting still drifts after every sync.
- **Event loss:** the built-in event store is in-memory. A restart lost every event in flight (the sender was told). Durable events need a separate message broker, which our messaging roadmap has not chosen yet.
- **Isolation gap:** on our local cluster profile, network isolation rules did not apply to newly started instances for at least 10 minutes. Every scale-from-zero creates such an instance. This must be re-tested on our production network stack.
- **Resource reservation:** Knative uses little at idle, but reserves about 1.75 CPUs, about 44 % of the lab node.
- **AI limits:** a request may run 5 minutes by default and at most 10 minutes without extra configuration. Large AI images make cold starts slow, so they need pre-loading. Compatibility with the KServe inference layer on the current Knative version is unverified.

**Effort.** About **33–59 person-days** for a production-ready opt-in capability: decision record, installer, GitOps packaging, ingress/TLS integration, metrics, offline mirroring, tests, docs. Of that, **8–15** are durable eventing. Without durable eventing it is **25–44 person-days**. These are estimates; the assumptions are in REPORT §16.

**Conditions**

1. Fix or contain the declarative drift, possibly by using the Knative Operator.
2. Decide where TLS ends at our entry point.
3. Re-test network isolation on the production network stack.
4. Keep durable eventing out until the messaging decision exists.
5. Verify KServe before promising AI inference.

**Proposed next step.** In the three-way review (Gawenda, Arash), decide whether to start the decision record (about 3–5 person-days) and the network-isolation re-test (about 1–2 days).
