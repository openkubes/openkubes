# ADR-Platform-029: ok-messaging Capability — Broker-Agnostic Pub/Sub & Streaming Contract

- **Status:** Accepted
- **Date:** 2026-07-31
- **Updated:** 2026-08-03 — revised per three-way review (GPT, via PR #49): RC1–RC8 addressed,
  restructured into base contract + declared message flow model + profile extensions.
- **Accepted:** 2026-08-03 — Arash, following the addressed review
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
Services/ADR-020) models asynchronous pub/sub delivery, session state, retained state,
or stream replay.

The first draft of this ADR modeled MQTT and Kafka as two implementations of one shared
delivery-semantics dial (one "delivery mode" concept, one "exactly-once" guarantee, one
"ordering within partition/session key" guarantee, retained messages treated as
equivalent to log compaction). Three-way review (GPT, via PR #49) requested changes:
MQTT session delivery and Kafka stream processing are structurally different
guarantees, and collapsing them into shared normative language made the contract
unclear and untestable. This revision separates a genuinely broker-agnostic **base
contract** from protocol-specific **extensions**, and demotes the Kafka profile to
**Candidate** status, consistent with "no structure without a forcing consumer": ok-iot
currently names a concrete need for MQTT/edge delivery, not for Kafka replay or
transactional streaming.

Consistent with ADR-Platform-001, OpenKubes owns the *contract* for messaging — not
Kafka, not HiveMQ, not ActiveMQ Artemis.

## Decision

### 1. Capability Decision

OpenKubes adopts **ok-messaging** as a platform capability: broker-agnostic
asynchronous pub/sub and event-streaming, consumable by any vertical (ok-iot first;
ok-robotics/ok-ai as later consumers only if a real need materializes). The capability
does not include cluster lifecycle, storage, ingress, or observability backends — it
consumes those through their own contracts, same as ADR-Platform-019's Robotics
capability does.

### 2. Base Contract v1 (`ok-messaging-base-v1`)

A deployment conforms to the base contract when all of the following are verified.
These guarantees hold regardless of protocol or broker; they say nothing about
delivery mode, ordering, or replay — those are extension concerns (§4–5).

#### Transport and identity

1. Client-to-broker transport is encrypted (TLS); clients verify broker/server
   identity — a deployment that only offers plaintext or unverified TLS does not
   conform.
2. Every publisher and subscriber authenticates. Credentials are supplied from
   Kubernetes Secrets or an envelope-valid secret reconciler (ADR-Platform-011/017),
   never committed as usable defaults.
3. Topic/stream access is authorized per client identity, with publish and
   subscribe (or produce and consume) scopes distinguished — "any authenticated client
   may do anything" does not conform.
4. Credential rotation and revocation are supported without a full broker redeploy.

#### State and lifecycle

5. Broker state that a declared message flow (§3) requires to survive a restart uses
   persistent storage satisfying the applicable OpenKubes storage contract
   (ADR-Platform-009). What must survive is defined per flow, not assumed globally.
6. The complete workload is declaratively renderable, versioned, and repeatably
   installable, upgradable, and reversible as one release — Helm v1, GitOps/Crossplane
   XRD as a later delivery mechanism (ADR-Platform-019 §3.10). Release/manifest
   rollback is distinguished from stateful data-format downgrade compatibility; the
   latter is a profile-specific concern (§4–5), not assumed free.

#### Operations and observability

7. Broker health, availability, and error rate are discoverable by the cluster-local
   observability capability (ADR-Platform-018) as base-contract signal categories.
   Profile-specific metrics (e.g. Kafka consumer lag, MQTT client queue depth) are
   extension concerns (§4–5), not base guarantees — they are not the same signal and
   must not be conflated.
8. Backup/restore is defined and tested for durable broker state. The exact protected
   state set (messages/logs, topic/queue configuration, ACLs, offsets, retained
   messages, sessions) is enumerated per profile (§4–5), not assumed from the base
   contract alone.

### 3. Declared Message Flow Model

Delivery semantics are properties of a **declared message flow** — a
producer/broker/consumer relationship over a named topic, queue, or stream — not of
the topic or stream in isolation, and not a single Provider Value selecting a mode
across all traffic. Each declared flow specifies, at minimum:

- producer-side acknowledgement/durability configuration;
- broker-side persistence and retention behavior;
- consumer-side acknowledgement or offset-commit strategy;
- its failure boundary — whether the flow's guarantee covers transport only, broker
  storage, or application-level processing.

A flow's declaration is its reviewed API surface, the same discipline ADR-Platform-015
applies to an agent instance's declared Skill Contracts.

**Explicit non-claim:** no profile claims exactly-once application-level side effects
outside the broker unless the destination participates in the same atomicity mechanism
as the flow, or the consumer implementation provides verified idempotency. The contract
does not, and cannot, guarantee this by itself.

### 4. Profile Extension: `mqtt-session-v1`

**Implementation Profile:** `ok-messaging-hivemq` (HiveMQ or equivalent MQTT
broker). **Forcing consumer:** ok-iot, `constrained-edge` envelope (ADR-Platform-017).
No second HiveMQ deployment topology exists to disambiguate against, so the profile
name carries no envelope qualifier; per "no structure without a forcing consumer,"
that qualifier is added only if and when a second HiveMQ topology is actually forced.

Extends the base contract with:

1. **Protocol delivery** is stated per declared flow as MQTT QoS 0, 1, or 2 — not as a
   shared "delivery mode" label. QoS is a publish/subscribe/acknowledgement property of
   the flow, per §3.
2. **Ordering**: messages from the same publishing client, on the same topic and QoS,
   delivered through a non-shared subscription, arrive in order. Retry/duplicate
   behavior is disclosed separately per QoS level (QoS 2 avoids duplicates; QoS 1 may
   redeliver).
3. **Retained messages (last-known-value delivery):** where a topic is marked
   retained, a new matching subscription receives the last retained value without
   waiting for the next publish. This is a distinct capability from state
   reconstruction or historical replay (§5) — it is not "the MQTT equivalent of Kafka
   compaction."
4. **Session continuity:** for a persistent session, QoS 1 and QoS 2 messages pending
   for the client survive disconnects until acknowledged, expired, administratively
   discarded, or the declared session-retention limit is reached. **QoS 0 message
   queuing during a disconnect is not guaranteed** unless the profile explicitly
   declares otherwise for that flow.
5. **Last Will:** if declared for a client/session, the broker publishes that client's
   configured Last Will message on ungraceful disconnect. This is a normative,
   testable guarantee of this extension, not merely rationale.
6. Tests for this extension must explicitly control and vary **Client ID**, **Clean
   Start / Clean Session**, and **Session Expiry Interval** — session-continuity claims
   are meaningless without pinning these.

### 5. Candidate Profile Extension: `durable-stream-v1`

**Candidate Implementation Profile:** `ok-messaging-kafka` (Kafka or
Kafka-API-compatible, e.g. Redpanda). **Status: Candidate — not yet specified for
acceptance.** No concrete consumer currently requires replay, consumer groups, or
transactional stream processing; per "no structure without a forcing consumer"
(ADR-Platform-026), this extension is recorded here so a future real consumer does not
have to re-derive its shape, but it is **not** part of the v1 acceptance surface. Same
treatment as Candidate Profile C below.

If/when a concrete consumer names this profile, it would extend the base contract
with:

1. **Ordering** guaranteed within one partition only — not globally, not per
   "session key" (that is an MQTT concept, not a Kafka one).
2. **Processing semantics** stated per declared flow as at-most-once, at-least-once, or
   transactional consume-process-produce — never labeled "exactly-once" as a bare
   term. Transactional consume-process-produce does not by itself prove idempotent
   external side effects (§3 non-claim applies).
3. **State reconstruction** via compacted topics: a distinct capability from MQTT
   retained-message delivery. Compaction is asynchronous background reconciliation; it
   does not mean "deliver the last value immediately on subscribe."
4. **Historical replay**: offset- or timestamp-based, from any retained point in the
   log — a third distinct capability, alongside last-known-value delivery (§4.3) and
   state reconstruction (above), native to this profile only.

### Candidate Profile C: `ok-messaging-artemis`

ActiveMQ Artemis remains a named candidate (per ADR-Platform-026) but is not specified
in this v1 — no forcing consumer exists yet. It would slot in as a third profile if a
use case needs AMQP/JMS semantics that neither the MQTT nor the (candidate) Kafka
extension satisfies.

### 6. Provider Values

Per-installation values, never promoted into the contract:

- broker hostname/endpoint and TLS certificate issuer;
- topic/queue/stream names and access-control mappings;
- retention window, partition count (Kafka candidate), replica factor, resource sizing;
- per-flow delivery configuration (QoS, ack strategy, transactional settings);
- credentials and secret backend wiring.

Provider Values for the ok-iot broker profile land in `ok-cluster` (private/VPN-only),
per ADR-Platform-026's follow-ups.

### 7. Base Contract Tests

Minimum acceptance verification for `ok-messaging-base-v1`, independent of protocol:

1. Install into a clean namespace using externally supplied secrets.
2. Verify TLS transport and broker/server identity verification; reject plaintext or
   unverified connections.
3. Verify authenticated publish/subscribe; verify an unauthorized client is rejected;
   verify publish-only and subscribe-only scoped clients cannot exceed their scope.
4. Verify credential rotation/revocation without full redeploy.
5. Restart the broker and verify state that the declared flow requires to survive
   does survive.
6. Confirm observability discovers broker health, availability, and error-rate signals.
7. Execute a backup and restore into an empty target for durable broker state, then
   rerun functional checks.
8. Rehearse an upgrade and rollback of the release/manifest.

### 8. Profile-specific Contract Tests

**`mqtt-session-v1` (required for v1 acceptance):**

1. Verify retained-message (last-known-value) delivery to a new matching subscriber.
2. Verify session resume after a simulated disconnect within the retention window, and
   correct drop behavior after the window expires — with Client ID, Clean
   Start/Session, and Session Expiry Interval explicitly pinned and varied.
3. Verify Last Will delivery on ungraceful disconnect, where declared.
4. Failure-path: disconnect after send but before acknowledgement, for QoS 1 and QoS 2;
   verify observed redelivery/duplication stays within the declared QoS semantics.
5. Restart the broker with unacknowledged QoS 1/2 messages pending; verify they survive
   per §4.4.

**`durable-stream-v1` (deferred — applies only once this profile is promoted from
Candidate to specified):**

1. Verify replay from an earlier offset/timestamp.
2. Verify transactional consume-process-produce, including transaction abort behavior.
3. Verify consumer restart both before and after offset commit; verify observed
   duplication/loss stays within the declared processing semantics.
4. Verify compacted-topic state reconstruction.

### 9. Explicitly Unclaimed Guarantees

- No profile claims exactly-once application-level side effects outside the broker,
  absent shared atomicity or verified consumer idempotency (§3).
- MQTT QoS 0 message queuing during a disconnect is not guaranteed.
- Kafka compaction is not a substitute for MQTT retained-message (last-known-value)
  delivery semantics, and retained messages are not a substitute for Kafka-style
  historical replay — these are three distinct capabilities (§4.3, §5.3, §5.4), never
  presented as interchangeable.
- This ADR does not select HiveMQ, Kafka, or Artemis as *the* platform default.
- Cross-broker federation/bridging (HiveMQ ↔ Kafka), schema registry / message-format
  governance, and multi-region/multi-cluster replication of broker state remain out of
  scope (see below).

## Consequences

**Positive:**
- ok-iot consumes a broker-agnostic base contract plus an explicitly-scoped MQTT
  extension instead of bespoke per-vertical Helm; the "owns components, not contracts"
  anti-pattern named in ADR-Platform-026 is avoided.
- The `constrained-edge` / `datacenter` envelope split (ADR-Platform-017) gets its
  first concrete non-storage, non-secrets application.
- Delivery, ordering, retained-state, and replay claims are now testable per protocol
  instead of asserted as one shared guarantee — addressing the core issue raised in
  three-way review.
- Demoting Kafka to Candidate keeps the ADR consistent with "no structure without a
  forcing consumer" instead of speculatively fully specifying a profile no one has
  asked for yet.

**Negative / Cost:**
- More upfront structure than a single shared contract (base + declared-flow model +
  one required extension + one candidate extension) — a deliberate cost for
  testability, per review feedback.
- The MQTT extension alone must carry v1 acceptance; if ok-iot's real need turns out to
  require Kafka-grade replay, `durable-stream-v1` must be promoted and re-reviewed
  before that need can be met under this contract.

**Revisit triggers:**
- A concrete consumer names a need for Kafka replay, consumer groups, or transactional
  stream processing → `durable-stream-v1` is promoted from Candidate to a specified,
  reviewed profile.
- ActiveMQ Artemis gets a real forcing consumer → Candidate Profile C is specified.
- ok-robotics or ok-ai develop a genuine messaging need → evaluated against this same
  base contract and declared-flow model before any new capability is considered.
- A second `constrained-edge` vertical arrives and either confirms the MQTT extension
  generalizes or exposes a wrongly-cut guarantee.

## Out of Scope

- Choosing HiveMQ vs. Kafka vs. Artemis as *the* platform default.
- Fully specifying `durable-stream-v1` or Artemis absent a forcing consumer.
- Cross-broker federation/bridging (HiveMQ ↔ Kafka) — a distinct capability if a real
  consumer forces it.
- Schema registry / message-format governance — deferred until a consumer needs it.
- Multi-region/multi-cluster replication of broker state.

## References

- OK-134 — this spike
- OK-111 — forcing decision (ADR-Platform-026 verdict)
- PR #49 — three-way review (GPT, via Arash) requesting the base/extension split
  addressed in this revision
- ADR-Platform-001 — Contracts, not Components
- ADR-Platform-009 — Storage Contract
- ADR-Platform-011 — GitOps / Secret Contract
- ADR-Platform-015 — Agentic AI (declared Skill Contract precedent for §3's flow model)
- ADR-Platform-017 — Constraint Envelopes
- ADR-Platform-018 — Observability Capability
- ADR-Platform-019 — Robotics Fleet Orchestration (contract-shape precedent)
- ADR-Platform-026 — Vertical Layer (verdict YES, spawns this ADR)
