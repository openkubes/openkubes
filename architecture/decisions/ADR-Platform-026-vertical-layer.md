# ADR-Platform-026: Vertical Layer — ok-robotics / ok-ai / ok-iot

- **Status:** Draft / Spike Required
- **Date:** 2026-07-25
- **Deciders:** Arash (final) · Claude · GPT (three-way review)
- **Extends:** ADR-013 (Cluster Registration Contract), ADR-017 (Constraint Envelopes)
- **Relates:** ADR-020 (Shared Platform Services)

## Context

OpenKubes has, until now, treated domain consumers implicitly. `ok2-rmf` (robotics /
Open-RMF) was the first real consumer and the forcing consumer for the registration
contract (ADR-013). The Agentic AI work (OK-14/15) is a second, structurally different
consumer: inference/agent workloads on `ok-mgmt` / `ok1-talos`.

We now want to add **ok-iot** — an IoT vertical anchored by a concrete cluster instance
running a messaging/streaming broker (candidate profiles: Kafka, HiveMQ, ActiveMQ
Artemis). Placing ok-iot raises the question of *what layer it lives in*.

Two consumers can be coincidence. **Three heterogeneous consumers force us to name the
layer they share** and to prove the platform contracts are genuinely domain-agnostic.

## Decision (proposed)

1. **Introduce an explicit Vertical Layer** as a first-class concept:
   `ok-robotics`, `ok-ai`, `ok-iot`. Verticals are **domain consumers**, not
   capabilities. They consume the contract-driven capability layer (`ok-cluster`,
   `ok-storage`, `ok-observability`, …); they do not define platform guarantees.

2. **Naming rule:** verticals carry a domain name, never a component/tool name.
   → `ok-iot` is correct; `ok-kafka` / `ok-hivemq` are **not** verticals.
   Broker technologies are Implementation Profiles under a capability (see below).

3. **Each vertical requires a concrete forcing consumer** (a real workload / cluster
   instance), consistent with "No structure without a forcing consumer."
   ok-iot's anchor is the dedicated `ok-cluster` instance running the chosen broker.

4. **ok-messaging capability is a forced byproduct**, not part of the vertical.
   Kafka / HiveMQ / AMQ become Implementation Profiles of a broker-agnostic
   `ok-messaging` (a.k.a. eventing/streaming) capability, following the full chain:
   Capability → Contract → Implementation Profile → Provider Values → Contract Tests.

## Why now (forcing argument)

- ok-robotics, ok-ai and ok-iot present **three distinct constraint envelopes**
  (ADR-017): in-cluster robotics coordination, inference/agent workloads, and
  edge/intermittent MQTT+streaming. Three envelopes over one platform is the strongest
  available pressure test that the contracts are broker-, workload- and
  topology-neutral. → "A second constraint envelope forces the guarantees" — here, a third.

## Open question — verdict required (spike)

**Does ok-iot force the ok-messaging contract? (YES / NO / NOT YET)**

Four tests (to be answered in the spike, mirroring OK-75 discipline):
1. Is there a real IoT workload that cannot be served by an existing capability?
2. Do at least two broker profiles (e.g. HiveMQ edge/MQTT vs. Kafka core/streaming)
   express genuinely different delivery semantics, forcing a broker-agnostic contract?
3. Would placing the broker outside a contract (raw Helm per vertical) reproduce the
   "owns the components, not the contracts" anti-pattern?
4. Is the constraint envelope distinct enough from ok-robotics/ok-ai to add signal?

## Consequences

- **Positive:** explicit, symmetric vertical layer; contracts stress-tested by a third
  heterogeneous domain; broker choice deferred to Implementation Profiles.
- **Cost:** requires an `ok-messaging` contract + contract tests before ok-iot is
  "fully provisioned" (ADR-018 gate discipline applies).
- **Risk if skipped:** ok-iot degenerates into three broker deployments instead of one
  contract.

## Follow-ups

- OK-<this ticket>: introduce vertical layer + ok-iot; spawn ok-messaging spike.
- Provider Values for the broker profile live in `ok-cluster` (private/VPN-only).
- EN-first; DE Confluence translation follows.
