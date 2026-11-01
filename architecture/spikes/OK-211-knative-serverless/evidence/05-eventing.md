# 05 — Eventing PoC

- Test IDs: E1–E8
- Date (UTC): 2026-10-31T12:14Z – 12:29Z
- Commit: `7b6f48a` plus the Phase 6 changes in this commit
- Environment: VM `ok-knative-local`, K3s `v1.35.5+k3s1`, Knative Eventing `1.24.0`. Broker `default` in `ok211-events` is an MTChannelBasedBroker with InMemoryChannel (from `config-br-defaults`).

**Setup:**

- **Senders** are Jobs in `ok211-load` (curl image by digest, PSA `restricted`). Each one logs `send <id>` before and `sent <id> code=<http> exit=<curl>` after every POST to `http://broker-ingress.knative-eventing.svc.cluster.local/ok211-events/default`.
- **Sinks** are `event-display` (by digest) as plain Deployments, except `event-display-ksvc` (E2) and `podinfo-fail` (E4).
- **Latency** = the kubelet timestamp of the sink's `id:` line minus that of the sender's `send <id>` line. There is one node, so both timestamps come from one clock (B11).

Results are recorded as JSON lines `E1`–`E4`, `E5-<scenario>`, `E6` and `E8` in [raw/measurements.json](raw/measurements.json). Each line carries the broker, `config-br-defaults` and every trigger with its filter, subscriber and delivery.

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless apps-eventing   # apps/eventing/{base,e2,e3,e4,e5}.yaml, waits for Ready/Available
make -C … measure-events TEST=e1
make -C … measure-events TEST=e2        # 5 runs, B11 zero state before each
make -C … measure-events TEST=e3
make -C … measure-events TEST=e4
make -C … exp-E5 SCENARIO=dispatcher    # kubectl delete pod -l …role=dispatcher --grace-period=0 --force
make -C … exp-E5 SCENARIO=ingress       # same for mt-broker-ingress
make -C … exp-E5 SCENARIO=restart       # kubectl rollout restart deploy/imc-dispatcher (comparison)
make -C … exp-E5 SCENARIO=none          # control: same sink outage, no disruption
make -C … measure-events TEST=e6
make -C … measure-events TEST=e8
```

**Triggers and filters:**

| Trigger | Filter | Subscriber | Delivery |
|---|---|---|---|
| `e1-test` | `type=dev.openkubes.ok211.test` | Service `event-display` | broker default |
| `e2-ksvc` | `type=dev.openkubes.ok211.e2` | ksvc `event-display-ksvc` (`window: 6s`) | broker default |
| `e3-a` | `type=dev.openkubes.ok211.e3.a` | Service `sink-a` | broker default |
| `e3-b` | `source=/ok211/e3/b` | Service `sink-b` | broker default |
| `e4-retry` | `type=dev.openkubes.ok211.e4` | ksvc `podinfo-fail` + `uri: /status/500` | `retry: 3`, exponential, `PT0.5S`, `deadLetterSink: event-display-dls` |
| `e5-durable` | `type=dev.openkubes.ok211.e5` | Service `sink-e5` | `retry: 5`, exponential, `PT1S` |
| `e6-ping` | `type=dev.knative.sources.ping` | Service `event-display` | broker default |
| `e8-zot` | `type=zotregistry.image.updated` | Service `event-display` | broker default |

`config-br-defaults` sets the broker's delivery to retry 10, exponential, `PT0.2S`. The triggers with their own `delivery` override it.

## Observed

### Finding first: the broker answers only after delivery

With MT broker and InMemoryChannel, the broker ingress returns its `202` only when the event has been delivered or has finally failed. It does not return when the event has been buffered:

- **E4:** the subscriber saw attempts at +0, +0.5, +1.5 and +3.5 s. The sender got the `202` only at +3.6 s, after the dead-letter delivery.
- **E2:** the `202` arrived after the cold-started `event-display-ksvc` had logged the event. The time from send to response was 1.7 / 1.2 / 0.76 / 1.3 / 1.5 s, the same as the measured latencies.
- **E5:** while the sink was down, the requests stayed open, up to 16.3 s. When the dispatcher or the ingress died, they ended with an error.

Consequences:

- A `202` here means "delivered or dead-lettered". A producer's request lasts as long as delivery, including retries, so `delivery.retry`/`backoffDelay` directly bound producer latency.
- Events in flight are not lost silently. The producer gets an error and can resend (E5).
- A producer must handle long-running requests, not just errors. The sender in U2 used `--max-time 5`, which would have timed out under retries.

### E1 — broker, trigger, binary and structured mode ([raw/e1-sender-20261031T121429Z.log](raw/e1-sender-20261031T121429Z.log), [raw/e1-sink-20261031T121429Z.tsv](raw/e1-sink-20261031T121429Z.tsv))

20 events, 0.5 s apart, alternating binary mode (`Ce-*` headers) and structured mode (`application/cloudevents+json`).

| | Sent | `202` | Delivered | Duplicates | Latency min / median / p90 / max |
|---|---|---|---|---|---|
| All | 20 | 20 | **20** | 0 | 3 / **5** / 10 / 48 ms |
| Binary (10) | 10 | 10 | 10 | 0 | 4 / 5 / – / 48 ms |
| Structured (10) | 10 | 10 | 10 | 0 | 3 / 5 / – / 11 ms |

Both modes arrive with `type`, `source`, `id` and the extension `seq`, and the broker adds `knativearrivaltime`.

### E2 — event-driven Knative Service from 0 pods ([raw/e2-20261031T121457Z.tsv](raw/e2-20261031T121457Z.tsv))

Each run started from the B11 zero state (no pod, PA `actualScale` 0, SKS `Proxy`), then waited 10 s and sent one event.

| Run | `202` | Delivered | Latency incl. cold start | Pod |
|---|---|---|---|---|
| 1 | yes | yes | 1722 ms | new (`…-7fcks`) |
| 2 | yes | yes | 1168 ms | new |
| 3 | yes | yes | 758 ms | new |
| 4 | yes | yes | 1323 ms | new |
| 5 | yes | yes | 1543 ms | new |
| **min / median / max** | 5/5 | **5/5** | **758 / 1323 / 1722 ms** | 5 different pods |

Delivery to a scaled-to-zero ksvc works without extra configuration: the activator buffers the request. The latency is in the range of the HTTP cold start in S3, which was 1028–2108 ms.

### E3 — filters ([raw/e3-20261031T121910Z.txt](raw/e3-20261031T121910Z.txt))

| Sent (5 each) | `sink-a` (type filter) | `sink-b` (source filter) |
|---|---|---|
| `e3a-*`: type `…e3.a`, source `/ok211/e3/x` | **5** | 0 |
| `e3b-*`: type `…e3.z`, source `/ok211/e3/b` | 0 | **5** |
| `e3z-*`: type `…e3.z`, source `/ok211/e3/z` | 0 | 0 |

Each sink got only its own events.

### E4 — retries and dead-letter sink ([raw/e4-20261031T121920Z.txt](raw/e4-20261031T121920Z.txt))

| Metric | Value |
|---|---|
| Attempts at `podinfo-fail /status/500` (podinfo debug log, one line per request) | **4** = 1 + 3 retries |
| Times of the attempts (UTC) | 12:19:21.254, 21.758, 22.761, 24.766: backoff ≈ 0.5, 1.0, 2.0 s (exponential `PT0.5S`) |
| Dead-letter sink `event-display-dls` | received the event (same id) |
| Extensions in the DLS | `knativeerrorcode=500`; `knativeerrordest=http://podinfo-fail.ok211-events.svc.cluster.local/status/500`; `knativeerrordata=ewogICJzdGF0dXMiOiA1MDAKfQ==` (base64 of the 500 body `{"status": 500}`); `knativebrokerttl=255`; `knativearrivaltime`; `seq=1` |
| Sender | `202` after 3.6 s (see the finding above) |

### E5 — durability under disruption ([raw/e5-*](raw/))

The sink `sink-e5` was scaled to 0 before the first event and back to 1 about 14 s after the sender started, so events waited in the dispatcher's retry loop (`retry: 5`, exponential `PT1S`, up to 31 s).

The sender posted 100 events at 5/s **asynchronously**, `curl --max-time 90`, so the rate stayed fixed although the broker answers late. At about 8 s, in the middle of the outage, came the disruption: the pod was force-deleted (`--grace-period=0 --force`), or the dispatcher was rollout-restarted for comparison. A control run used the same outage without any disruption.

| Scenario | Sent | `202` | Rejected (code/curl exit) | Delivered | **Lost after `202`** | Duplicates | Out of order |
|---|---|---|---|---|---|---|---|
| `none` (control) | 100 | **100** | – | **100** | 0 | 0 | 10 |
| `dispatcher` (force-delete `imc-dispatcher`) | 100 | 52 | **48 × `500`** (seq 1–48) | 52 | **0** | 0 | 11 |
| `ingress` (force-delete `mt-broker-ingress`) | 100 | 40 | **60**: 50 × empty reply (`000/52`), 6 × refused (`000/7`), 4 × timeout (`000/28`); seq 1–60 | 40 | **0** | 0 | 8 |
| `restart` (`rollout restart imc-dispatcher`) | 100 | 48 | **52 × `500`** (seq 1–52) | 48 | **0** | 0 | 11 |

Reading it:

- **The control shows that the losses come from the disruption.** With the sink down for about 14 s and no disruption, all 100 arrived. The highest latency was 16.3 s, spent in the retry loop.
- **Every event that the dispatcher held in its retry loop when it died was lost.** That was seq 1–48: all events sent before the disruption, waiting for the sink. A graceful `rollout restart` loses them the same way (seq 1–52). The InMemoryChannel keeps nothing across a dispatcher restart.
- When the ingress pod dies, the open requests that went through it are cut, and new requests fail until the new pod is Ready (`connection refused`).
- **No silent loss was observed:** 0 events lost after a `202`, because the `202` only comes after delivery. The producer received an error for every lost event. At-least-once therefore depends on the **producer retrying on error**, and a retrying producer creates duplicates whenever an error hides a successful delivery. In these runs no rejected event was delivered anyway, so there were 0 duplicates.
- The documentation says the same in general terms. [Available Channels](https://knative.dev/docs/eventing/channels/channels-crds/): "In-memory channels are a best effort Channel. They should NOT be used in Production. They are useful for development."

**Durable alternatives**, as listed in the Knative docs (not tested here):

- [Available Channels](https://knative.dev/docs/eventing/channels/channels-crds/): KafkaChannel (Beta), NatssChannel (Alpha).
- [Available Broker types](https://knative.dev/docs/eventing/brokers/broker-types/): Knative Broker for Apache Kafka, RabbitMQ Broker.

**Relation to ADR-Platform-029 (ok-messaging):**

- ADR-029 treats delivery semantics as properties of a declared flow. It names producer acknowledgement, broker persistence, consumer acknowledgement and the failure boundary (§3).
- Its only durable streaming profile, `durable-stream-v1` (`ok-messaging-kafka`), is a *candidate* without a forcing consumer (§5).
- A Knative Broker on InMemoryChannel cannot be declared as a durable flow in that sense: there is no broker persistence. A Kafka-backed Knative Broker would put Knative Eventing **on top of** an ok-messaging Kafka profile, not replace it. That dependency is input for the assessment (Phase 10).

### E6 — PingSource on 1.24 ([raw/e6-ping-20261031T122910Z.tsv](raw/e6-ping-20261031T122910Z.tsv))

PingSource `ok211-ping` (`* * * * *`, same spec as in U2), created at 12:14:17Z.

| Metric | Value |
|---|---|
| Cycles observed | **15** (12:15 – 12:29), 15 distinct minutes |
| Duplicates per minute | 0 |
| Event logged after the full minute: min / median / p90 / max | 52 / 260 / 487 / 506 ms |

No cycle was missed, including the minutes of the E5 disruptions (12:21–12:28). The pings are sent on the full minute, and none coincided with the few seconds in which the ingress or dispatcher was down. Behaviour during the upgrade is in U2: 2 of 2 cycles.

### E7 — ordering and delivery guarantees (from E5, E1, U2)

| Property | Observed | Statement |
|---|---|---|
| Ordering | out of order in every E5 run, **including the control** (8–11 of 40–100); E1 and U2 had no reordering at a steady rate and with a healthy sink | **No ordering guarantee.** Retries with backoff reorder events, so consumers must not depend on order. |
| Duplicates | 0 in all runs (E1, E5 × 4, E6, U2) | No duplicates were observed, but none are excluded: a producer that retries on an error caused by a cut connection after delivery would create one. Consumers must be idempotent (ADR-029 §3 non-claim). |
| Loss | 0 after `202`; all events in flight in the dispatcher lost on its restart, producer informed by `500` / cut connection | **At-most-once on the broker side**, at-least-once only with producer retries. The guarantee covers transport, not broker storage (ADR-029 failure boundary). |

### E8 — bridge to OK-167 ([raw/e8-zot-20261031T122911Z.txt](raw/e8-zot-20261031T122911Z.txt))

The event recorded in OK-167 was sent in binary mode with its original `ce-*` headers and JSON body. The source was `../openkubes-ok-167/architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/evidence/raw/cloudevent-image-updated.json` at commit `95e176d`, copied unchanged to [apps/eventing/e8-zot-event.json](../apps/eventing/e8-zot-event.json) (SHA-256 `5643a552…b0c3`, identical).

| Metric | Value |
|---|---|
| Broker response | `202` |
| Routed by trigger `e8-zot` (`type=zotregistry.image.updated`) | **yes**: `event-display` logged id `e05846b0-df32-4927-a35e-bf74c2c05ffb`, source `zotregistry.dev`, the original `time`, and the full body (digest, name `openkubes/machine/gitops/smoke`, reference `v1`) |

This shows the part that would already exist: zot's webhook can be pointed at a Knative Broker, and a trigger can route `zotregistry.image.updated` to a subscriber.

It does **not** close the OK-167 gap (criterion K1, push-based refresh). A subscriber that triggers an Argo CD refresh does not exist, and zot was not involved here; the recorded event was replayed.

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| E1 | PASS | 20/20 delivered, median 5 ms, both modes | — |
| E2 | PASS | 5/5 delivered from 0 pods, 758 / 1323 / 1722 ms | the `202` comes after delivery |
| E3 | PASS | each sink only its 5 events, 5 events nowhere | — |
| E4 | PASS | 4 attempts, exponential 0.5 / 1 / 2 s, DLS with `knativeerror*` extensions | — |
| E5 | PASS (executed) | Dispatcher kill: 48/100 lost, restart: 52/100, ingress kill: 60/100 not accepted; 0 lost after `202`; control 100/100 | InMemoryChannel is not durable, as documented |
| E6 | PASS | 15/15 cycles, 0 duplicates | PingSource recreated (see Deviations) |
| E7 | EVALUATED | no ordering guarantee, no duplicates seen, at-most-once broker-side | — |
| E8 | PASS | the OK-167 zot event is routed by type | does not close OK-167 K1 |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Broker, triggers, type/source filters, retries with exponential backoff and a dead-letter sink work as specified on 1.24 | Behaviour with the Kafka or RabbitMQ broker, or KafkaChannel; nothing durable was installed |
| A trigger can deliver to a scaled-to-zero ksvc; the cold start adds ≈ 0.8–1.7 s | Behaviour when the cold start exceeds the broker's or the producer's timeout |
| With InMemoryChannel, a dispatcher or ingress restart loses every event in flight, and the producer is told by an error | That this holds for every failure mode (e.g. a node crash, or the dispatcher dying after delivery but before answering) |
| Retries reorder events; no ordering guarantee | Ordering with a partitioned Kafka broker |
| The zot event format from OK-167 can be routed by type | A push-based Argo CD refresh (OK-167 K1) |

## Deviations from BRIEF

1. **The E1/E6 base was recreated:** broker `default`, `event-display` and PingSource `ok211-ping`. After Phase 4, `make apps-upgrade-down` deleted the namespace `ok211-events` with all U2 objects. That was broader than B9 asks: only `podinfo-upgrade` had to be deleted. The objects were re-applied from `apps/eventing/base.yaml` with the same specs. So E6 does not continue the PingSource from Phase 4. It shows 15 new cycles on 1.24. Behaviour during the upgrade is covered by U2.
2. **E5 sender asynchronous:** the broker answers only after delivery, so a sequential sender cannot hold a fixed rate while the sink is down. The sender fires each POST in the background at 5/s with `--max-time 90`. Its memory limit is 512 Mi; the first attempt with 64 Mi was OOMKilled at about 43 concurrent curls, and that run was discarded.
3. **E5 disruption by sink outage:** the BRIEF offers a slow sink or a sink at 0 replicas, and the sink at 0 replicas was used. A **control run without disruption** (`SCENARIO=none`) was added, so the losses can be attributed.
4. **E5 first attempt aborted:** `kubectl wait -l job-name=…` failed because the Job's pod did not exist yet. That orphaned sender then ran into the OOM above. Its events carry their own id prefix and are not counted.
5. **E4 `podinfo-fail` runs with `min-scale: 1`,** so the attempts are not mixed with a cold start.
6. **The OK-167 event file was copied into the spike** (`apps/eventing/e8-zot-event.json`), because the sender must read it from the spike folder. Its checksum is identical to the source.
