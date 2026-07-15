# ADR-Platform-019: Robotics Fleet Orchestration — Open-RMF RKE2 Profile

**Status:** Proposed — RKE2 profile deployed; production acceptance gates remain open
**Date:** 2026-07-14
**Deciders:** Author: Suchit · Review: three-way (Arash / Claude / GPT) · Merge: Arash. Suchit is additionally decider for §3 (Implementation Profile) as owner of `ok2-rmf`; §1–2 (Capability, Contract) remain platform decisions.
**Relates:** ADR-Platform-001 (Contracts, not Components), ADR-Platform-009 (Storage), ADR-Platform-010 (Ingress), ADR-Platform-011 (GitOps), ADR-Platform-013 (Workload Cluster Registration), ADR-Platform-017 (Constraint Envelopes), ADR-Platform-018 (Observability)
**Related work:** OK-60 (OpenRMF XRD), `rmf_deployment_template` (sibling repo)

---

## Context

Open-RMF is the first running robotics workload on OpenKubes. It coordinates
robot fleets through ROS 2/DDS, provides traffic scheduling and task dispatch,
and exposes an authenticated web and API surface for operators.

The upstream `open-rmf/rmf_deployment_template` is a useful reference
deployment, but its default platform assumptions do not match the existing
OpenKubes installation:

- the reference path targets k3s and nginx ingress;
- ingress and monitoring may be installed as part of the application stack;
- certificate issuance is driven from standard `Ingress` annotations;
- the deployment is optimized for demonstration and development rather than
  handover to a platform operations team.

The `rmf_deployment_template` fork (a sibling repository, not a subdirectory
of `openkubes`) has been adapted to run on RKE2 and deployed on a prior RKE2
cluster; the target cluster `ok2-rmf` is Talos-based and its rollout is
pending (see §5, ADR-013 row). It reuses cluster capabilities rather
than installing competing ones:

- Traefik routes `/dashboard`, `/auth`, `/rmf/api/v1`, and `/trajectory`;
- cert-manager creates the TLS secrets consumed by Traefik;
- the existing Prometheus Operator discovers the API through a
  `ServiceMonitor`, and the existing Grafana discovers dashboard ConfigMaps;
- Keycloak supplies browser identity and JWTs;
- the public API route explicitly excludes `/rmf/api/v1/_internal`;
- a Helm release owns the application lifecycle.

This creates a recurring architectural boundary. Robotics fleet orchestration
is the capability; Open-RMF is its first implementation. RKE2, Traefik,
cert-manager, Keycloak, PostgreSQL, and the concrete DNS name are profile or
provider choices. Treating all of them as the capability would make the
deployment inseparable from one cluster.

The second deployment design — upstream k3s/nginx and the running RKE2/Traefik
variant — also exposes which behavior is stable and which behavior is merely
an implementation choice. This ADR records that discovered boundary.

## Decision

### 1. Capability

OpenKubes adopts **Robotics Fleet Orchestration** as a workload capability.

The capability provides a deployable control and operator plane for
coordinating ROS 2 robot fleets. Open-RMF is the reference implementation, not
the name of the platform contract.

The capability does not include the Kubernetes cluster lifecycle, storage,
ingress, certificate issuance, or observability backends. It consumes those
OpenKubes capabilities through their contracts.

### 2. Robotics Fleet Orchestration Contract v1

A deployment conforms to v1 only when all of the following guarantees are
verified.

#### Runtime and mode

1. The deployment provides the RMF traffic, task, fleet-adapter, and web/API
   integration required by the selected site configuration.
2. Exactly one trajectory-producing mode is active for a release:
   **simulation** or **real/core RMF**. Enabling both, or neither, is invalid
   configuration. The current chart only documents this as an operator
   warning (`values.yaml` comments); render-time enforcement is an open
   acceptance gate, not yet a working guard.
3. ROS 2 participants use an explicitly configured DDS implementation,
   discovery/network configuration, and `ROS_DOMAIN_ID`; those values are not
   compiled into the application images.
4. The browser/API plane and the ROS 2 plane communicate through cluster-local
   services. Internal RMF server endpoints are never exposed as public routes.

#### Identity and external access

5. Operator-facing HTTP traffic is encrypted at the cluster ingress entry
   point. Plain HTTP redirects to HTTPS.
6. The deployment exposes stable logical routes for the dashboard,
   authentication, public API, and trajectory stream. Exact hostnames and
   certificate issuers are Provider Values.
7. Interactive access is authenticated through an OIDC-capable identity
   provider. API and trajectory components validate signed tokens without
   requiring the signing service on every request.
8. The public API route excludes the internal API namespace. In the Open-RMF
   profile, `/rmf/api/v1/_internal` is cluster-internal only. A route that
   exposes it is a contract failure.

#### State and lifecycle

9. Identity and RMF Web application state use persistent storage satisfying
   the applicable OpenKubes storage contract. Release upgrades and pod
   restarts must not implicitly discard that state.
10. The complete workload is declaratively renderable, versioned, and
    repeatably installable, upgradable, and reversible as one release. Helm is
    the v1 packaging mechanism; GitOps or a Crossplane XRD may become the
    delivery mechanism without changing this contract.
11. Runtime configuration, credentials, and site-specific robot/map data are
    external to application images. Credentials must be supplied from
    Kubernetes Secrets or an envelope-valid secret reconciler and must not be
    committed as usable defaults.

#### Operations and observability

12. Kubernetes readiness and workload health can be assessed without entering
    a container. The public routes, authentication flow, database connectivity,
    ROS 2 integration, and selected RMF mode have executable verification.
13. Application metrics are discoverable by the cluster-local observability
    capability, and platform logs are collected under the cluster logging
    policy. Dashboards are useful operational views, not the source of metric
    truth.
14. Restore procedures cover both identity and RMF application state. A
    successful PVC bind is not evidence of recoverability. Backups are taken
    at the application level (`pg_dump` for both PostgreSQL data sets), not
    assumed from volume snapshots. Independent restore of the Keycloak and
    RMF data sets is accepted even though it can leave the two temporarily
    inconsistent (e.g. a user present in one but not the other). The accepted
    recovery point is the last successful backup; continuous replication is
    not required for v1.

The contract deliberately does **not** select:

- a Kubernetes distribution or ingress controller;
- a certificate authority or DNS domain;
- Keycloak as the only admissible identity provider;
- PostgreSQL topology or storage implementation;
- Prometheus, Grafana, or a log backend;
- image registries, image tags, robot maps, fleet adapters, DDS interfaces,
  retention, or resource sizes.

Those choices belong to implementation profiles or Provider Values.

### 3. Implementation Profile v1: `openrmf-rke2-datacenter`

The first profile is the deployed RKE2 adaptation in `rmf_deployment_template`.

| Layer | Profile choice |
|---|---|
| Kubernetes | Existing RKE2 cluster registered with OpenKubes |
| Packaging | `openrmf-deployment` Helm chart |
| Robotics runtime | Open-RMF core or `rmf_demos_gz` simulation, selected by values |
| ROS 2 transport | CycloneDDS over UDP with multicast discovery (`AllowMulticast: default`, auto `ParticipantIndex`); `ROS_DOMAIN_ID`/`RMW_IMPLEMENTATION` are Provider Values, but the mounted CycloneDDS discovery/network XML — including the discovery mode itself — is currently a fixed chart-template ConfigMap, not yet parameterized |
| Web/API | RMF Web dashboard and API server |
| Identity | Keycloak with a PostgreSQL database and bootstrap Job |
| Application state | PostgreSQL on RWO PVCs |
| Ingress | Existing Traefik; current manifests use `IngressRoute` and Middleware CRDs |
| TLS | Explicit cert-manager `Certificate` resources and a `ClusterIssuer` |
| Metrics | Instrumented API image, `ServiceMonitor`, existing Prometheus |
| Dashboards | Grafana sidecar-discovered ConfigMaps |
| Logs | Cluster logging policy supplied by ADR-Platform-018; not a separate RMF stack |

RKE2 is selected because it is the existing supported cluster substrate for
this installation and already supplies the required operational integrations.
It is not a Robotics Fleet Orchestration contract requirement.

The profile has this runtime boundary:

```text
Operator
   │ HTTPS
   ▼
Traefik ── /dashboard ───────► RMF Web Dashboard
   ├────── /auth ────────────► Keycloak ─────► PostgreSQL/PVC
   ├────── /rmf/api/v1 ──────► RMF API ──────► PostgreSQL/PVC
   │          └─ _internal is not externally routable
   └────── /trajectory ──────► Simulation OR Core Visualizer
                                      │
                 RMF API ◄──── ROS 2 / CycloneDDS ────► RMF Core/Adapters

RMF API /metrics ◄── ServiceMonitor ◄── cluster-local Prometheus/Grafana
```

Simulation and real/core mode are mutually exclusive profile variants. They
share the identity, web/API, ingress, persistence, and observability design.

### 4. Provider Values

The following are per-installation values and must not be promoted into the
contract:

- public hostname and base URL;
- cert-manager issuer and TLS secret names;
- ingress class and controller-specific parameters;
- storage class and PVC size;
- registry, immutable image digest/tag, and pull policy;
- monitoring selectors and Grafana namespace;
- ROS domain, simulation clock, site map, fleet adapters, bidding window, and
  trajectory level (the CycloneDDS discovery/network configuration is not yet
  a Provider Value — see Production Acceptance Gates);
- credentials, backup targets, resources, replicas, node placement, and
  retention.

The currently committed `rmf.openkubes.ai`, `letsencrypt-prod`, registry paths,
and monitoring labels are examples for one installation, not platform
defaults.

### 5. Relationship to OpenKubes contracts

| Existing decision | Required relationship |
|---|---|
| ADR-009 Storage | Both PostgreSQL data sets consume persistent storage. The profile must document durability and restore behavior; RWO alone does not imply either. |
| ADR-010 Ingress | A managed OpenKubes workload binds through the standard `Ingress` contract and `ok-ingress` class. Controller-specific routing must remain profile-local. |
| ADR-011 GitOps | Helm is packaging, not the desired-state authority. Production delivery moves behind GitOps when ADR-011 is implemented. |
| ADR-013 Registration | `ok2-rmf` is registered under one canonical cluster name and credential source before management-plane delivery is enabled. This ADR's deployed evidence comes from a prior RKE2 cluster; the target cluster `ok2-rmf` is Talos-based and its rollout is pending — this condition is open, not yet satisfied. |
| ADR-018 Observability | RMF publishes/discovers telemetry; it reuses the per-cluster stack and must not install a competing monitoring system. ADR-018 is Accepted, so this dependency does not rest on a Proposed document. |

The current RKE2 chart uses Traefik `IngressRoute` resources directly and the
class name `traefik`. This is functional but does **not** satisfy ADR-010's
standard `Ingress`/`ok-ingress` binding. It is recorded as transitional
profile debt, not as a new ingress contract. Before this profile is accepted
for OpenKubes-managed production, it must either:

1. bind through ADR-010 while preserving prefix rewriting and the `_internal`
   exclusion; or
2. be covered by a separate ADR that deliberately evolves the ingress
   contract.

Option 2 has genuine substance here: prefix rewriting, the trajectory
WebSocket, and the `_internal` exclusion are exactly the case where standard
`Ingress` annotations get awkward and a Gateway API `HTTPRoute` (native
URLRewrite) is clean — this profile may be the consumer that forces the
ADR-010 v2 evolution rather than one contorted into `Ingress` annotations.

### 6. Constraint Envelope Clause

The v1 profile targets the **`datacenter`** envelope from ADR-017: stable
cluster networking, reachable DNS/certificate services, sufficient resources
for RMF, Keycloak, and two databases, and an operable cluster-local
observability stack.

The capability is not yet qualified for **`constrained-edge`**. In particular,
the current profile assumes:

- enough memory and storage for multiple stateful services;
- stable ROS 2/DDS networking inside the site;
- certificate issuance and image availability during deployment;
- operational access for database recovery;
- a cluster-local observability implementation with adequate capacity.

A constrained-edge profile must explicitly qualify these guarantees and
decide where fleet coordination state lives during partitions. It may replace
components, but it may not silently weaken authentication, internal-route
isolation, state ownership, or recoverability.

## Production Acceptance Gates

The architectural profile exists and is deployable, but its current chart is
a production **candidate**, not a production baseline. Acceptance requires
evidence for every gate below.

| Gate | Required evidence |
|---|---|
| Secrets | No usable passwords in chart defaults or rendered release values; secret reconciliation and rotation tested. |
| Mode validation | Chart render fails for zero or two active trajectory modes (`ENABLE_RMF`/`ENABLE_RMF_SIM`); currently unenforced beyond a values-file comment. |
| Task-state persistence | Core-mode task dispatcher writes task state to the RMF API server without the data race that currently disables this connection (`rmf-core-modules.yaml`: `server_uri` wiring is commented out). |
| Ingress contract | ADR-010 conformance, or an accepted decision evolving that contract; `_internal` remains unreachable externally. |
| Supply chain | Images are pinned to reviewed immutable digests or release tags; `latest` and unconditional pulls are removed from production values. |
| Workload security | Non-root/read-only settings where supported, least-privilege ServiceAccounts/RBAC, NetworkPolicies, and a documented Pod Security posture. |
| Availability | Resource requests/limits, probes, disruption behavior, and replica/topology choices are defined from an SLO. Single-replica stateful services are explicitly accepted or replaced. |
| Data protection | Automated `pg_dump`-based backup and a timed, independent restore test for both PostgreSQL data sets; accepted RPO is the last successful backup; storage failure behavior documented. |
| Lifecycle | `helm lint`/render checks, upgrade and rollback rehearsal, and ownership of CRDs/cross-namespace dashboard objects are verified. |
| Contract test | Automated verification of routes, TLS, login/token validation, `_internal` denial, metrics discovery, persistence, and the selected RMF mode. |

Until these gates pass, documentation must not describe the chart merely as
"production-grade" without qualification.

## Verification (Contract Test)

The profile acceptance test must, at minimum:

1. Render the chart for simulation and core mode and reject zero or two active
   modes.
2. Install into a clean namespace using externally supplied secrets.
3. Wait for databases, Keycloak, bootstrap Job, API, dashboard, and the
   selected RMF runtime to become ready.
4. Verify a trusted certificate and HTTP-to-HTTPS redirect.
5. Complete the browser/OIDC login and call an authenticated public API.
6. Prove that `/rmf/api/v1/_internal` is unreachable through the external
   entry point while the cluster-local RMF server can use it.
7. Verify the trajectory WebSocket through ingress.
8. Publish or observe a known ROS 2/DDS event across the API/runtime
    boundary, with the event crossing at least two nodes — single-node DDS
    traffic does not exercise multicast/unicast discovery behavior on the
    overlay CNI.
9. Confirm Prometheus has the RMF API target and a synthetic metric, and that
   application logs are searchable under the cluster policy.
10. Restart the API, identity service, and database pods and verify state is
    retained.
11. Execute a backup and restore into an empty target, then rerun the
    functional checks.
12. Upgrade one supported chart version and roll back without losing state.

## Alternatives Considered

- **Upstream k3s/nginx stack unchanged:** rejected for the RKE2 profile —
  duplicates ingress/monitoring capabilities the cluster already owns and
  makes certificate/telemetry ownership ambiguous. Remains valuable for
  development and as evidence the capability contract is not RKE2-specific.
- **Run Open-RMF directly on the shared infrastructure cluster:** rejected —
  robotics workloads, DDS traffic, site data, and release lifecycle belong in
  a registered workload cluster, limiting blast radius.
- **Define an "Open-RMF capability" tied to Keycloak and Traefik:** rejected —
  confuses one component stack with the stable platform ability and blocks
  substitution of identity, ingress, database, or robotics implementations.
- **Bundle a dedicated monitoring stack with RMF:** rejected — ADR-018 owns
  the cluster observability guarantee; RMF supplies instrumentation and
  dashboards, not a second Prometheus/Grafana installation.
- **Make Helm the permanent production control plane:** rejected as an
  architectural commitment — Helm stays the packaging/rollback unit; GitOps
  or Crossplane delivery (including OK-60) can own reconciliation without
  changing the application contract.

## Consequences

### Positive

- Robotics fleet orchestration becomes a named platform capability without
  making Open-RMF or RKE2 permanent dependencies.
- The deployed chart reuses ingress, certificates, storage, registration, and
  observability rather than duplicating platform services.
- Public and internal API boundaries are explicit and contract-testable.
- The OpenRMF XRD can expose stable capability parameters instead of leaking
  every Helm value into its API.
- A future implementation can replace Traefik, Keycloak, PostgreSQL, or even
  Open-RMF while preserving the operator-facing contract.

### Negative / Cost

- The profile depends on several cluster CRDs and controllers; missing or
  mismatched Traefik, cert-manager, or Prometheus Operator APIs fail at render
  or reconciliation time.
- ROS 2/DDS networking remains sensitive to CNI, interface selection,
  multicast/discovery behavior, and node placement.
- Two single-replica PostgreSQL deployments and single-replica identity/API
  services create availability and recovery obligations not solved by Helm.
- Cross-namespace Grafana ConfigMaps and controller-specific route resources
  complicate release ownership and least-privilege delivery.
- Maintaining the fork creates an upstream-rebase and security-patch burden
  (see Fork Maintenance below).

**Fork maintenance.** `openkubes/rmf_deployment_template` follows an
upstream-first policy: changes not specific to the OpenKubes profile are
submitted to `open-rmf/rmf_deployment_template`; only profile-specific
adaptations remain fork delta. The fork is rebased against upstream at least
once per upstream release. Image digest updates and CVE response for the
profile's pinned images are owned by the profile owner (§3 decider). The fork
repository applies the same branch protection as the mother repo (PRs
required, no force-push); merge authority for the fork lies with the profile
owner, since it carries implementation-profile code, not contracts —
contract-level decisions are made via ADR in `openkubes/openkubes`.

## Revisit Triggers

- A second robotics implementation conforms to the contract or exposes a
  wrongly cut guarantee.
- OK-60 introduces an OpenRMF XRD and reveals parameters that belong in the
  contract rather than the profile.
- ADR-010 moves from `Ingress` to Gateway API, or the RKE2 profile removes its
  Traefik CRD dependency.
- A production SLO requires HA identity/API/database topology.
- Real robot fleets require DDS traffic across nodes, VLANs, or clusters and
  the current discovery model no longer satisfies the runtime guarantee.
- A constrained-edge deployment becomes real and forces envelope-specific
  guarantees.
- Open-RMF state or robot-control behavior becomes safety-critical enough to
  require a dedicated safety and failure-containment decision.

## Out of Scope

- Robot safety certification, emergency-stop systems, and direct motor
  control
- Selection and lifecycle of physical robots or fleet-adapter vendors
- Cross-site traffic coordination and active/active RMF state
- A constrained-edge Open-RMF profile
- Final OpenRMF XRD schema and composition implementation (OK-60)
- DDS reachability between RMF and physical robots across the pod network ↔
  site network boundary; v1 is simulation-only for this concern (see Revisit
  Triggers)
- SLO values, capacity numbers, and site-specific runbooks

## References

- `docs/platform-engineering-method.md`
- `architecture/decisions/README.md`
- `rmf_deployment_template/docs/RKE2-DEPLOYMENT.md` (sibling repo, not nested under `openkubes`)
- `rmf_deployment_template/charts/rmf-deployment`
- `open-rmf/rmf_deployment_template` (upstream reference implementation)
- OK-60 — OpenRMF XRD
