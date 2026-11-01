# 09 — Architecture assessment

- Test IDs: Phase 10 (sections 10.1–10.6); no new experiment
- Date (UTC): 2026-10-31
- Commit: `279a117` plus this document
- Inputs: the evidence of Phases 2–9 ([01](01-vm-k3s.md) … [08](08-gitops.md)), the ADRs in `architecture/decisions/`, and external sources (fetched 2026-10-31, URLs inline). External statements are quoted or paraphrased from the source given. No number in this document comes from anywhere other than a measurement in this spike or a cited source; estimates are marked **estimate**.

## 10.1 Capability cut (ADR-001, ADR-015)

ADR-001: "OpenKubes owns the contracts, not the components."

ADR-015 names the need without owning it. Source-to-app delivery "belongs to a separate Application Delivery capability with its own ADR, for which Epinio would be at most one implementation profile among stronger candidates (Knative, kpack/Buildpacks, ArgoCD + templates)".

**Sketch of a product-neutral contract.** Two capabilities, because the spike shows that their guarantees and failure modes differ (Serving: S1–S10; Eventing: E1–E8). In ADR-017's words, it would be a wrong cut to force them into one.

| Capability (proposal) | Contract v1 would promise | Explicitly not part of it |
|---|---|---|
| **Request-driven workloads** (working title `ok-serverless`) | An app declared by image digest, port and resource bounds is reachable as `<app>.<cluster>.internal` through the ADR-010 entry point. It scales with request concurrency, and to zero when idle (opt-in per app) or never (`min-scale`, S7). There is a bounded request duration (default 300 s, max 600 s: S9), traffic split between immutable revisions with rollback by traffic (S8), cluster-local visibility as an option (N4), Pod Security `restricted` compatibility (X1), and namespace-scoped tenant rights (X2) | Knative CRD names (`serving.knative.dev/Service`), Kourier, Knative ConfigMaps, the activator, KPA tuning knobs, the domain template |
| **Event routing** (working title `ok-event-routing`) | CloudEvents 1.0 in binary and structured mode (E1), routing by attribute filter (E3), delivery to request-driven workloads including from zero (E2), per-route retry with backoff and a dead-letter destination carrying error metadata (E4), and a schedule source (E6). Delivery semantics are declared per flow, as ADR-029 §3 requires | Durability. That belongs to ok-messaging (ADR-029): E5 shows the routing layer itself guarantees nothing across a restart. Also out: ordering (E7), Broker/Trigger CRD names, channel implementations |

**Knative as the Implementation Profile:**

| Layer | Content |
|---|---|
| Capability | Request-driven workloads / event routing |
| Contract | Both contracts above |
| Implementation Profile | Knative Serving + Kourier, or a Gateway API networking layer (10.2); Knative Eventing with a channel or broker class chosen per envelope |
| Provider Values | cluster domain, entry point (NodePort or Gateway), issuer, metrics protocol and endpoint, channel/broker backend, `config-autoscaler` overrides |
| Contract tests | the reproducible subset of this spike: S1/S2/S3/S8/S9, E1–E4, N2/N4, X1/X2, U1 |

What makes the cut product-neutral, and where Knative leaks:

- **The workload description does not have to be Knative's.** G2 shows that the webhook fills in eight fields. A contract that exposes `ksvc` directly would make those Knative defaults part of the contract. A thin claim (an XRD with Crossplane, or a template rendered to `ksvc`) keeps the contract stable.
- **Leaks to watch:**
  - the host schema (N2b: `{{.Name}}-{{.Namespace}}` is needed for `<app>.<cluster>.internal`);
  - the 600 s request ceiling (S9);
  - the cold-start latency of the activator path (S3, E2);
  - the `successThreshold` requirement for named revisions (S8).
- **Verdict for M6:** possible. Knative fits behind both contracts as an Implementation Profile. No consumer needs a Knative name if the claim layer exists.

## 10.2 Fit with the ADRs

| ADR | Fit | Reason and evidence |
|---|---|---|
| **ADR-010** ingress contract | **fits with condition** | Kourier's release default is a second LoadBalancer entry point (N1). Behind Traefik (`ok-ingress`, NodePort) it works with one entry point and ≈ 0.6 ms p50 extra (N2). The host schema fits with the domain template (N2b). **Conditions:** keep Kourier's Service `ClusterIP` declaratively, since it conflicts with server-side apply (N2 finding). TLS must terminate at the entry point (N3: Knative's cert-manager path terminates at Kourier and Traefik does not know those certificates). Alternative: `net-gateway-api`, "in beta", tested with Istio, Contour and Envoy Gateway, not with Traefik (N2) |
| **ADR-029** ok-messaging | **fits as a consumer, with condition** | Knative Eventing on InMemoryChannel is best effort (E5). The Knative docs: "They should NOT be used in Production". A durable path exists on the Knative side: `eventing-kafka-broker`, `eventing-natss` and `eventing-rabbitmq` are active and released `knative-v1.24.0` on 2026-10-27/30 (GitHub API, research note). On the ADR-029 side the matching profile `durable-stream-v1` (`ok-messaging-kafka`) is a **candidate without a forcing consumer** (§5). Knative would make Eventing a consumer of ok-messaging-kafka, not a replacement. **MQTT** (ADR-029's accepted forcing case): the eventing repo holds only `config/tools/mqttsource/mqttsource.yaml`, a `ContainerSource` example with an unbuilt `ko://` image. GitHub search finds no MQTT repository in `knative` or `knative-extensions`. An MQTT bridge would be self-built |
| **ADR-028** artifact registry | **fits** | The release YAMLs reference every image by digest (Phase 3; research note: `serving-core.yaml` 1.24, e.g. `activator@sha256:986b7623…`). Signatures and SLSA provenance are verifiable with cosign (X6). Mirroring into `registry-default` (zot) means copying digests and rewriting the registry host. Official private-registry guidance exists only for the Operator (`spec.registry`, research note) and not for YAML installs |
| **ADR-011** GitOps | **fits with condition** | Re-apply works declaratively with three derivation rules (Phase 4). The server-side diff of ksvc is clean (G2), but there is a perpetual drift on `pingsource-mt-adapter` (G1). Argo CD needs `ServerSideDiff=true` (opt-in), `ignoreDifferences` for four runtime-owned fields, and sync waves (G1). G3 was not run. The Operator path (G4) would move most of this out of the GitOps diff |
| **ADR-018** observability | **fits with condition** | Metrics are off by default. With `prometheus` they are available on fixed ports after a component restart (X5), which matches ADR-018 v1's "Prometheus scrape semantics". OTLP push exists but is outside ADR-018 v1. The condition is a Provider Value plus a restart step in the install target |
| **ADR-017** envelopes | **`datacenter`: fits; `constrained-edge`: open** | Idle usage is 32m CPU / 291 Mi, but the **requests are 1750m CPU / 1338 Mi** (S10), 44 % of a 4-CPU node. For `constrained-edge`, reconcilability is the issue: scale-from-zero needs the activator, the autoscaler and the image on the node, and an uncached cold start depends on the registry link (S4: 73–79 % pull). No measurement on edge hardware. **Estimate:** not a fit without pre-pulled images and lower requests |
| **ADR-004** runner, **ADR-030/035** control-plane execution | **not touched** | Knative runs workloads; it is no Contract Executor and takes no authorized transitions. See 10.3 |
| **ADR-015** agentic AI | **fits** | Knative is a named candidate for Application Delivery. Event-driven agent workers fit (10.3) |
| **ADR-001** | **fits** | see 10.1 |

## 10.3 Runner, Crossplane, agentic operations (scope 5)

Where Knative complements the platform:

- **Crossplane composes `ksvc`.** A claim (XRD) for "request-driven workload" can render a `serving.knative.dev/Service` as its composed resource. That keeps the Knative object out of the contract (10.1) and gives tenants namespace-scoped rights only (X2: `edit` suffices).
- **Event-driven, scale-to-zero workers.** A Trigger filtered on a type (E3) delivers to a ksvc at 0 pods (E2: 0.8–1.7 s including cold start), with retries and a dead-letter sink (E4). That suits agent skills that run rarely, such as the UC-8-style ticket summarization in ADR-015 §Use cases, provided their runtime stays below the request ceiling.
- **Image-update events.** The zot event from OK-167 can be routed by type (E8). A subscriber that triggers an Argo CD refresh would be the missing push piece for OK-167 K1. That subscriber does not exist.

Where it does not:

- **The Contract Executor (ADR-030/035) and the approval chain stay untouched.** Knative executes nothing on behalf of the platform. A ksvc that calls a Contract Executor is just a client; ADR-035's human approval and Policy Authority apply unchanged.
- **The runner (ADR-004)** is a Kubernetes Job doing imperative work with a defined end. Knative Serving's request model (bounded request, scale on concurrency) does not fit a long, stateful lifecycle operation. Knative Eventing's `job-sink` exists (`knative-eventing/job-sink`, Phase 3) but was not tested.
- **Durability of operational events:** E5 shows that the in-memory broker cannot carry platform events that must not be lost.

## 10.4 Long-running and GPU-heavy AI workloads

| Aspect | Observed / sourced | Meaning |
|---|---|---|
| Request duration | default 300 s, ceiling 600 s, `504` from the queue-proxy at the limit (S9). The ceiling can be raised: "If this value is increased, the activator's `terminationGracePeriodSeconds` should also be increased" ([config-defaults](https://knative.dev/docs/serving/configuration/config-defaults/)) | Batch inference, training and long agent runs do not fit synchronous Knative requests. Use a Job, or an async pattern (event in, result out) |
| Cold start, large images | measured: 34 MB image, pull 5.7–6.8 s at ≈ 5–6 MB/s over this lab's link (S4). **Estimate:** a 10 GB inference image would take ≈ 30 min to pull at that rate, or ≈ 80 s at a datacenter-local 125 MB/s (1 Gbit/s). Both are derived figures, not measurements | Scale-to-zero is only useful for large models with pre-pulled images (node-local cache) or a mirror next to the nodes. Even then, model loading adds time that this spike did not measure |
| Response-start timeout | `revision-response-start-timeout-seconds`, default 300 s ([config-defaults](https://knative.dev/docs/serving/configuration/config-defaults/)) | Bounds how long a cold-starting model may take before the first byte |
| GPU | knative.dev: "Knative Serving can leverage Kubernetes pod capabilities to access specialized hardware resources like GPUs" ([docs home](https://knative.dev/docs/)). Not tested; no `nvidia.com/gpu` example on the resources page | GPUs are plain resource requests. A GPU pod held by `min-scale: 1` costs a whole GPU permanently (S7 logic); scale-to-zero frees it at the price of the cold start above |
| KServe | default deployment mode is Knative ("The default KServe deployment mode is Knative which depends on Knative"). "Standard" mode has "No dependency on Knative or Istio", but "Scale from Zero is currently not supported in Standard mode for HTTP requests". Latest KServe v0.21.0 (2026-09-25); its serverless matrix lists Knative 1.19/1.20 only ([kubernetes-deployment](https://kserve.github.io/website/docs/admin-guide/kubernetes-deployment), [serverless](https://kserve.github.io/website/docs/admin-guide/serverless)) | KServe is the natural inference layer on top of this capability. Its support for Knative 1.24 is **not stated**, so compatibility is unverified (BLOCKED until tested). Without Knative, KServe works but without scale-from-zero |

## 10.5 Alternatives (AC1)

This is a documentation comparison only; nothing was installed.

- Sources were fetched on 2026-10-31 and are listed below the table.
- "not stated" means the cited pages give no figure. No footprint number is invented.
- Two claims were re-checked first-hand: the HPA scale-to-zero stage and OpenFaaS scale-to-zero being a Pro feature.
- The remaining quotes come from a research pass whose fetch tool summarizes pages. Spot-check them before they go into an ADR.

| Option | Scale-to-zero | Eventing / routing | Footprint (components) | Project status (seen 2026-10-31) | Fit with ADR-001 (contract, not component) |
|---|---|---|---|---|---|
| **Knative** (this spike) | yes, OSS; KPA, global switch; the activator buffers during scale-from-zero (measured S2/S3) | Broker/Trigger on CloudEvents, sources, retries, DLS (measured E1–E8) | activator, autoscaler, controller, webhook, networking layer; Eventing controllers; measured 32m / 291 Mi idle, 1750m requested (S10). Docs: "One node requires at least 6 CPUs, 6 GB of memory, and 30 GB of disk storage" (this spike ran on 4 vCPU / 8 GiB) | CNCF Graduated; Serving `knative-v1.24.0` (2026-10-26) | own CRDs, but CloudEvents gives a neutral event format; fits as a profile behind a claim (10.1) |
| **Knative Serving with the HPA class** (`serving-hpa.yaml`, release asset of 1.24.0; `pod-autoscaler-class: hpa.autoscaling.knative.dev`) | **no**: "Scale to zero can only be enabled if you are using the KnativePodAutoscaler (KPA)" | as Knative (the class only changes the autoscaler) | Knative plus the `autoscaler-hpa` controller from `serving-hpa.yaml`; not installed | same release as Knative | same as Knative; useful if scale-to-zero is not wanted but revisions/traffic split are |
| **KEDA + HTTP add-on** | yes, OSS: "all the way to zero if needed"; not with CPU/memory triggers; HTTP via the add-on ("including to/from zero") | none: event-driven *scaling* (scalers), no routing; the add-on interceptor proxies HTTP | keda-operator, metrics-apiserver, admission webhooks; add-on interceptor, scaler, operator; resources not stated | KEDA CNCF Graduated, v2.21.0; HTTP add-on "Project status: beta", v0.16.0 | own CRDs (ScaledObject, …), but under the HPA, so easy to keep out of a contract; covers scaling only |
| **Deployment + HPA** | only with object/external metrics: "Scaling to zero is only supported for object and external metrics". `HPAScaleToZero` is "Beta since Kubernetes v1.37; enabled by default", so it is **not available by default on K3s v1.35** (ok-local) | none | built in, plus a custom/external metrics adapter | Kubernetes core | most neutral (core API only); no HTTP scale-from-zero (nothing buffers the first request), no eventing |
| **OpenFaaS** | **Pro only**: "OpenFaaS Pro offers an additional component that can be used to scale idle functions to zero replicas"; CE min 1 / max 5 replicas | async via NATS; Kafka/SQS/SNS event connectors are Pro | gateway, faas-netes, Prometheus, NATS; resources not stated | not a CNCF project; CE "is not licensed for commercial usage beyond a one-off 60-day trial" | poor: licence and vendor API |
| **Fission** | yes, OSS; idle pods are reaped at min scale 0 | HTTP, message-queue triggers, timers, KubeWatcher | router, executor, builder manager, storagesvc, webhook, optional triggers; resources not stated | not in the CNCF project lists; v1.27.0 (2026-06-22); Apache-2.0 | own Function/Environment/Trigger model would leak unless fully wrapped |
| **Dapr** | no; "the autoscaling of Dapr applications is managed by the hosting layer" (KEDA in its docs) | pub/sub and bindings between apps and external systems | operator, sidecar injector, sentry, placement, scheduler, **plus a sidecar per pod**; resources not stated | CNCF Graduated; v1.19.0 (2026-10-22) | sidecar API reaches into app code; at most an eventing profile, not the platform model |
| **Argo Events** | not stated | EventSource → EventBus (NATS JetStream/Kafka) → Sensor → Trigger, "20+ event sources" | controller, optional webhook, EventBus deployed separately; resources not stated | part of the CNCF Graduated Argo project; v1.9.11 (2026-07-13) | event routing only, own CRDs; would need a separate scaler |
| **Direct ok-messaging clients** (ADR-029) | n/a, the consumer keeps running | whatever the broker profile offers (MQTT session or the Kafka candidate) | the broker itself, no extra layer | platform-owned contract | best fit for durable flows (ADR-029 §3); no request-driven scaling |

Reading it:

- Only Knative and Fission offer **HTTP scale-from-zero plus event routing** in one open-source package.
- KEDA with the HTTP add-on covers the scaling half with a smaller surface. It is beta for HTTP and has no event routing.
- For the **event-routing** contract, Argo Events and Dapr are real alternatives. Neither scales workloads.
- For **durable** flows, ADR-029's own clients remain the reference, whichever router sits in front.
- OpenFaaS is excluded by its CE licence terms.

Sources:

- Knative: [scale-to-zero](https://knative.dev/docs/serving/autoscaling/scale-to-zero/), [install with YAML](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/), [releases](https://github.com/knative/serving/releases)
- KEDA: [concepts](https://keda.sh/docs/latest/concepts/), [http-add-on](https://github.com/kedacore/http-add-on), [releases](https://github.com/kedacore/keda/releases)
- HPA: [Horizontal Pod Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/), §"Scaling to and from zero" (read first-hand)
- OpenFaaS: [scale-to-zero](https://docs.openfaas.com/openfaas-pro/scale-to-zero/) (read first-hand), [autoscaling](https://docs.openfaas.com/architecture/autoscaling/), [Pro introduction](https://docs.openfaas.com/openfaas-pro/introduction/)
- Fission: [executor](https://fission.io/docs/architecture/executor/), [repo](https://github.com/fission/fission)
- Dapr: [autoscale with KEDA](https://docs.dapr.io/integrations/autoscale-keda/), [repo](https://github.com/dapr/dapr)
- Argo Events: [docs](https://argoproj.github.io/argo-events/), [releases](https://github.com/argoproj/argo-events/releases)
- CNCF: [projects](https://www.cncf.io/projects/)

## 10.6 Operating costs, bare metal, upgrade and rollback (scope 6)

| Aspect | Value | Source |
|---|---|---|
| Components (Deployments) | Serving 5 (activator, autoscaler, controller, webhook, net-kourier-controller), Kourier gateway 1, Eventing 9 plus StatefulSet `request-reply` | Phase 3, U1 |
| Control-plane objects | 30 CRDs, 55 ClusterRoles (13 with `*`), 10 ClusterRoleBindings, 9 webhooks (8 `Fail`) | X4 |
| Idle usage | Knative 32m CPU / 291 Mi; queue-proxy 1m / 6 Mi per pod | S10 |
| Scheduling reservation | 1750m CPU / 1338 Mi (Knative); +25m CPU per pod (queue-proxy) | S10 |
| Release cadence | "The Knative project releases quarterly, on Tuesday of the 4th week of January, April, July, October" | [RELEASE-SCHEDULE.md](https://github.com/knative/community/blob/main/mechanics/RELEASE-SCHEDULE.md) |
| Support window | EOL = release date of `n+2`. 1.24: released 2026-10-27, EOL 2027-05-04, min K8s 1.35. 1.23: EOL 2027-02-02. That is ≈ 6 months per minor | same |
| Upgrade path | one minor at a time ("Knative supports upgrading by a single minor version number"). With quarterly releases that means **4 upgrades per year** to stay supported | U3 |
| Upgrade behaviour | 99 s window, 0/476 HTTP errors, 0 events lost after `202`, 1 producer-visible refusal (U1, U2). The plain release YAMLs fail on server-side re-apply; three derivation rules fix it | Phase 4 |
| Rollback | YAML: no documented downgrade. Operator: `spec.version`. Lab: VM snapshot ≈ 2 min | U3 |
| LoadBalancer / bare metal | Kourier wants a LoadBalancer (N1). Behind `ok-ingress` a NodePort is enough (N2), so no MetalLB is needed under ADR-010 profile v1 | N1, N2 |
| DNS | one wildcard per cluster domain with the N2b template (`*.<cluster>.internal`), or one per namespace with the default | N2b |
| Certificates | cert-manager per route at Kourier (N3), or one wildcard at the entry point (option a, N3). The latter needs DNS-01 for a public CA; a lab or internal CA needs nothing extra | N3 |
| Air-gap | every image is referenced by digest and verifiable (X6). Mirroring means rewriting the registry host; there is no official YAML-install procedure | 10.2 |
| Restart window | ≈ 40–80 s of `503` after a node restart although every deployment is Available (3 observations) | P3-restart, U3 |
| Network policy | on K3s' kube-router, new pods are not covered by an existing default-deny for ≥ 10 min | X3 |

**Operating effort, estimate:**

- 4 minor upgrades per year, each with a dry run (`knative-dry-run`), the ordered apply and post-install Jobs: ≈ 1 person-day each including review, if the derivation rules still hold.
- The rules must be re-checked per release, which is what `knative-dry-run` is for.
- Plus the networking and TLS integration once (WP4/WP5).

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| A product-neutral cut into two contracts (request-driven workloads, event routing) is possible, with Knative behind both as an Implementation Profile (M6) | That a claim layer (XRD, template) hides Knative completely; it was not built |
| Where Knative fits or conflicts with ADR-010/011/017/018/028/029, each with evidence from this spike or a cited source | Fit on the target clusters (ok-infra RKE2, ok-ai Talos) or behind the RKE2 host proxy of ADR-010 profile v1 |
| Which alternatives cover which half (scaling vs. routing), from their docs | Any measured comparison; footprints of the alternatives are not stated in their docs |
| The limits for long and GPU-heavy AI workloads (600 s ceiling, pull-dominated cold starts) | KServe on Knative 1.24, GPU behaviour, model load times; all marked BLOCKED or estimate |

## Deviations from BRIEF

1. External facts were collected by two research passes (Knative cadence, air-gap, MQTT, KServe, GPU; alternatives), each told to quote its sources and to write "not stated" instead of guessing. Two claims were re-checked first-hand (HPA scale-to-zero stage, OpenFaaS scale-to-zero). The others are marked to spot-check.
2. The MQTT question (BRIEF 10.2) was answered by source search. There is no MQTT channel or source in `knative` or `knative-extensions`, only the `ContainerSource` example under `config/tools/mqttsource`.
3. **Estimates** in 10.4 (large-image pull time) and 10.6 (upgrade effort) are labelled as such and are not measurements.
