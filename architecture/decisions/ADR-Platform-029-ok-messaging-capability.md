# ADR-Platform-029: ok-messaging Capability — Broker-Agnostic Pub/Sub & Streaming Contract

- **Status:** Draft
- **Date:** 2026-07-31
- **Deciders:** Arash (final) · Claude · GPT (three-way review)
- **Extends:** ADR-Platform-026 (Vertical Layer — verdict YES, this ADR is its spawned follow-up)
- **Relates:** ADR-Platform-017 (Constraint Envelopes), ADR-Platform-019 (Robotics Fleet Orchestration, contract-shape precedent), ADR-Platform-020 (Shared Platform Services)
- **Related work:** OK-134 (this spike), OK-111 (forcing decision)

---

## Context

ADR-Platform-026 established the Vertical Layer (`ok-robotics` / `ok-ai` / `ok-iot`) and
recorded a YES verdict: ok-iot's anchor — a dedicated `ok-cluster` instance running a
messaging/streaming broker — forces a capability that none of the existing platform
contracts cover. No existing capability (Storage/ADR-009, Ingress/ADR-010,
GitOps/ADR-011, Observability/ADR-018, Cluster Registration/ADR-013, Shared Platform
Services/ADR-020) models asynchronous pub/sub delivery, QoS, retained state, or ordered
replay.

Two broker profiles are the immediate candidates, and they are not interchangeable
implementations of one idea:

- **HiveMQ** (MQTT, edge-oriented): QoS 0/1/2, retained messages, last-will-on-disconnect,
  session-based delivery to intermittently-connected devices.
- **Kafka** (core streaming): append-only ordered log, consumer-group offsets, replay
  from any point in the log.

Consistent with ADR-Platform-001, OpenKubes owns the *contract* for messaging — not
Kafka, not HiveMQ, not ActiveMQ Artemis (candidate third profile). This ADR defines that
contract following the same shape ADR-Platform-019 used for Robotics Fleet
Orchestration: Capability, Contract v1 (testable guarantees), Implementation Profiles,
Provider Values, Contract Tests.

## Decision

### 1. Capability

OpenKubes adopts **ok-messaging** as a platform capability: broker-agnostic
asynchronous pub/sub and event-streaming, consumable by any vertical (ok-iot first,
ok-robotics/ok-ai as later consumers if a real need materializes — no structure without
a forcing consumer).

The capability does not include the Kubernetes cluster lifecycle, storage, ingress, or
observability backends. It consumes those OpenKubes capabilities through their
contracts, same as ADR-Platform-019's Robotics capability does.

### 2. ok-messaging Contract v1

A deployment conforms to v1 only when all of the following guarantees are verified.
Guarantees are written broker-agnostic; where HiveMQ and Kafka satisfy a guarantee
differently, both paths are named explicitly.

#### Delivery semantics

1. The contract exposes a named **delivery mode** per topic/stream: **at-most-once**,
   **at-least-once**, or **exactly-once-within-a-consumer-group**. A Provider Value
   selects the mode per topic; the contract does not silently default to one across all
   traffic.
2. **Ordering** is guaranteed within a partition/session key, not globally, unless the
   Implementation Profile explicitly documents stronger ordering (e.g. single-partition
   Kafka topics).
3. **Replay** is an explicit, testable capability: a consumer can request delivery from
   a named earlier point (offset, timestamp, or "since last acknowledged") where the
   Implementation Profile supports it (Kafka: yes, by design; HiveMQ: only via retained
   messages / session state, not general replay — this asymmetry is a Provider Value
   disclosure, not a contract violation).
4. **Retained/last-known state**: where a topic is marked retained, a new subscriber
   receives the last published value without waiting for the next publish (HiveMQ
   native; Kafka via compacted topic as the equivalent Implementation Profile
   mechanism).

#### Connectivity and session handling

5. The contract declares, per Constraint Envelope (ADR-Platform-017), whether publishers
   and subscribers are assumed **always-connected** (`datacenter`) or
   **intermittently-connected** (`constrained-edge`). Guarantees 1–4 are qualified per
   envelope; a `constrained-edge` publisher's delivery guarantee cannot silently assume
   an always-reachable broker.
6. **Session continuity**: a reconnecting client in `constrained-edge` resumes its
   session (undelivered messages queued per its declared QoS/delivery mode) rather than
   silently dropping backlog, up to a documented retention window.

#### Identity and access

7. Publishers and subscribers authenticate; credentials are supplied from Kubernetes
   Secrets or an envelope-valid secret reconciler (ADR-Platform-011/017), never
   committed as usable defaults.
8. Topic/stream access is authorized per client identity — a client's read/write scope
   is explicit, not "any authenticated client may publish/subscribe to anything."

#### State and lifecycle

9. Broker state (retained messages, committed offsets, persistent queues) uses
   persistent storage satisfying the applicable OpenKubes storage contract
   (ADR-Platform-009). Broker restarts must not implicitly discard undelivered,
   at-least-once-or-stronger messages.
10. The complete workload is declaratively renderable, versioned, and repeatably
    installable, upgradable, and reversible as one release — Helm v1, GitOps/Crossplane
    XRD as a later delivery mechanism, consistent with ADR-Platform-019 §3.10.

#### Operations and observability

11. Broker health, queue depth/lag, and connected-client count are discoverable by the
    cluster-local observability capability (ADR-Platform-018); dashboards are
    operational views, not the source of metric truth.
12. Backup/restore for durable broker state (Kafka log segments, HiveMQ persistence) is
    defined and tested — a successful PVC bind is not evidence of recoverability, same
    principle as ADR-Platform-019 §2.14.

The contract deliberately does **not** select:

- a specific broker product or version;
- topic/queue naming conventions (Provider Values, per deployment);
- exact retention windows, partition counts, or replica factors;
- the wire protocol exposed to end devices (MQTT, Kafka protocol, AMQP) — that is an
  Implementation Profile property, not a contract requirement, as long as delivery-mode
  guarantees (1–4) are honored.

### 3. Implementation Profiles

#### Profile A: `ok-messaging-hivemq-edge`

| Layer | Profile choice |
|---|---|
| Broker | HiveMQ (or equivalent MQTT broker) |
| Wire protocol | MQTT 3.1.1/5 |
| Constraint envelope | `constrained-edge` (ADR-Platform-017) — primary target |
| Delivery modes | QoS 0/1/2 map to at-most-once / at-least-once / exactly-once-per-session |
| Retained state | Native retained messages |
| Replay | Session-resume only; no arbitrary historical replay |
| Persistence | Broker-local persistent session store on PVC |

#### Profile B: `ok-messaging-kafka-core`

| Layer | Profile choice |
|---|---|
| Broker | Kafka (or Kafka-API-compatible, e.g. Redpanda) |
| Wire protocol | Kafka protocol |
| Constraint envelope | `datacenter` (ADR-Platform-017) — primary target |
| Delivery modes | At-least-once by default; exactly-once via transactional producer/consumer-group config |
| Retained state | Compacted topics as the equivalent mechanism |
| Replay | Native, offset- or timestamp-based, from any retained point |
| Persistence | Log segments on PVC per ADR-Platform-009 |

#### Candidate Profile C: `ok-messaging-artemis`

ActiveMQ Artemis remains a named candidate (per ADR-Platform-026) but is **not**
specified in this v1 — no forcing consumer exists for it yet ("no structure without a
forcing consumer"). It would slot in as a third profile if a use case needs AMQP/JMS
semantics that neither HiveMQ nor Kafka profiles satisfy.

### 4. Provider Values

Per-installation values, never promoted into the contract:

- broker hostname/endpoint and TLS certificate issuer;
- topic/queue names and access-control mappings;
- retention window, partition count, replica factor, resource sizing;
- QoS/delivery-mode selection per topic;
- credentials and secret backend wiring.

Provider Values for the ok-iot broker profile land in `ok-cluster` (private/VPN-only),
per ADR-Platform-026's follow-ups.

### 5. Contract Tests

Minimum acceptance verification, mirroring ADR-Platform-019 §"Verification":

1. Install into a clean namespace using externally supplied secrets.
2. Verify authenticated publish/subscribe; verify an unauthorized client is rejected.
3. Verify the declared delivery mode end-to-end for at least one at-least-once and one
   exactly-once (where supported) topic.
4. Verify retained/last-known-value delivery to a new subscriber.
5. For Kafka profile: verify replay from an earlier offset/timestamp.
6. For HiveMQ profile: verify session resume after a simulated disconnect within the
   retention window, and correct drop behavior after the window expires.
7. Restart the broker and verify undelivered at-least-once-or-stronger messages survive.
8. Confirm Prometheus/observability discovers broker health, queue depth, and connected
   clients.
9. Execute a backup and restore into an empty target for durable broker state, then
   rerun functional checks.

## Consequences

**Positive:**
- ok-iot (and any future vertical) consumes a broker-agnostic contract instead of
  bespoke per-vertical Helm; the "owns components, not contracts" anti-pattern named in
  ADR-Platform-026 is avoided.
- The `constrained-edge` / `datacenter` envelope split (ADR-Platform-017) gets its first
  concrete non-storage, non-secrets application.
- HiveMQ and Kafka profiles are both real precedent for delivery-mode qualification,
  not speculative design.

**Negative / Cost:**
- Two Implementation Profiles from day one (not one) — more upfront contract-test
  surface than a single-broker decision would require.
- Delivery-mode guarantees (1–4) require care to keep genuinely broker-agnostic; a
  future profile with weaker guarantees (e.g. no session resume) must qualify itself
  explicitly rather than silently weakening the contract.

**Revisit triggers:**
- A second `constrained-edge` vertical or a second `datacenter` streaming consumer
  arrives and either confirms these profiles generalize or exposes a wrongly-cut
  guarantee.
- ActiveMQ Artemis gets a real forcing consumer → Profile C is specified.
- ok-robotics or ok-ai develop a genuine messaging need → evaluated against this same
  contract before any new capability is considered.

## Out of Scope

- Choosing HiveMQ vs. Kafka vs. Artemis as *the* platform default — both v1 profiles
  are first-class, selected per vertical's constraint envelope.
- Cross-broker federation/bridging (HiveMQ ↔ Kafka) — a distinct capability if a real
  consumer forces it.
- Schema registry / message-format governance — deferred until a consumer needs it.
- Multi-region/multi-cluster replication of broker state.

## References

- OK-134 — this spike
- OK-111 — forcing decision (ADR-Platform-026 verdict)
- ADR-Platform-001 — Contracts, not Components
- ADR-Platform-009 — Storage Contract
- ADR-Platform-011 — GitOps / Secret Contract
- ADR-Platform-017 — Constraint Envelopes
- ADR-Platform-018 — Observability Capability
- ADR-Platform-019 — Robotics Fleet Orchestration (contract-shape precedent)
- ADR-Platform-026 — Vertical Layer (verdict YES, spawns this ADR)
