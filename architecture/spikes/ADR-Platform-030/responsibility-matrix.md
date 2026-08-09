# OK-141 Responsibility Matrix

Status: **Capability mapping; component decision pending**

Based on: [contract inventory](contract-inventory.md)

Safety state: **NO-GO for infrastructure mutation**

## Reading the matrix

`OpenKubes-owned?` describes ownership of the domain meaning, not necessarily the
controller that performs reconciliation:

- **Yes** — OpenKubes must define the semantic contract.
- **Reference** — OpenKubes may select/reference a value whose truth belongs elsewhere.
- **Coordination** — OpenKubes may define a cross-system outcome without owning each
  underlying resource.
- **No** — an existing subsystem owns both meaning and reconciliation.
- **Undetermined** — the spike needs evidence before assigning ownership.

`Existing mechanism sufficient?` is deliberately conservative. **Unknown** is not a
justification to create a component.

## Matrix

| Semantics | Today owner | Target owner | OpenKubes-owned? | Existing mechanism sufficient? | Evidence |
|---|---|---|---|---|---|
| Cluster identity/name | Crossplane claim or local `ok-cluster` directory; then CAPI `Cluster` | One authoritative cluster contract; CAPI consumes identity | Yes | Partial — identity exists, single authority does not | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`new-cluster.sh`](../../../../ok-cluster/new-cluster.sh) |
| Cluster role/type (`ok-ai`, `ok-mgmt`, etc.) | `ok-cluster` configuration conventions | OpenKubes contract/profile semantics | Yes | Partial — modeled locally, durable server-side meaning unproven | [`ok-ai/cluster-config.yaml`](../../../../ok-cluster/ok-ai/cluster-config.yaml) |
| Kubernetes target version | Crossplane claim/upgrade claim or `ok-cluster`; CAPI control-plane/workers reconcile | CAPI topology/lifecycle objects under one authorized desired state | Coordination | Likely — CAPI supports it; single mutation path must be proved | [`xrd-upgrade.yaml`](../../../platform/cluster-management/crossplane/xrd-upgrade.yaml), [`Makefile`](../../../../ok-cluster/Makefile) |
| OS distribution/version/profile/image identity | `ok-cluster` references; `ok-linux` owns profiles/images | `ok-linux` owns truth; OpenKubes references a versioned identity | Reference | Partial — reference flow exists; immutability/compatibility evidence needed | [`render.py`](../../../../ok-cluster/render.py), [`ok-linux README`](../../../../ok-linux/README.md) |
| Infrastructure provider | v4.2 XRD and `ok-cluster` provider profile | CAPI provider and infrastructure profile reference | Reference | Yes for provider lifecycle; profile-selection contract needs validation | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`render.py`](../../../../ok-cluster/render.py) |
| Infrastructure profile, placement and storage constraints | `ok-cluster` provider profiles/templates | Infrastructure/provider profile owner; selected by OpenKubes intent | Reference | Partial — mature rendering exists, authoritative profile API not established | [`render.py`](../../../../ok-cluster/render.py) |
| Control-plane replicas/resources | Claims/config rendered into CAPI objects | CAPI control-plane/topology reconciliation | Coordination | Yes for reconciliation; input authority is fragmented | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`templates`](../../../../ok-cluster/templates) |
| Worker replicas/resources | Claims/config rendered into MachineDeployments | CAPI MachineDeployment/topology reconciliation | Coordination | Yes for reconciliation; input authority is fragmented | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`templates`](../../../../ok-cluster/templates) |
| Endpoint IP allocation/reservation | Manual Crossplane input; `ok-cluster` local allocation plus live checks | Dedicated infrastructure/network allocation authority referenced by cluster intent | Undetermined | No single sufficient authority identified | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`render.py`](../../../../ok-cluster/render.py) |
| Pod/service CIDR allocation | `ok-cluster` local inventory and renderer | Single collision-safe allocation authority; CAPI consumes values | Undetermined | No single sufficient authority identified | [`render.py`](../../../../ok-cluster/render.py) |
| CNI provider/version intent | v4.2 claim or `ok-cluster` convention | OpenKubes enablement/profile contract; enablement mechanism reconciles it | Coordination | Partial — input/install exist, durable owner and version status do not | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`deploy-full.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/deploy-full.sh) |
| CNI installation and network readiness | Runner or Make/Helm process | Durable enablement mechanism; workload API supplies observed state | No for low-level resources; coordination for outcome | No reviewed mechanism proves generation-aware `NetworkReady` | [`deploy-full.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/deploy-full.sh), [`Makefile`](../../../../ok-cluster/Makefile) |
| Multus enablement | v4.2 claim and runner apply | Enablement or platform profile, depending on forcing workload | Undetermined | Partial — procedural support only; boundary needs a consumer | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`deploy-full.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/deploy-full.sh) |
| CSI/cloud-controller prerequisites | Provider-specific scripts/profiles and platform targets | Enablement only when required for minimum viability; otherwise platform | Undetermined | Unknown — must be assessed per provider/bootstrap path | [`Makefile`](../../../../ok-cluster/Makefile) |
| Platform profile selection | `ok-cluster` cluster type and imperative targets; GitOps conventions | OpenKubes semantic reference; GitOps owns convergence | Yes for selection, not rendered resources | Partial — convergence mechanisms exist; profile contract/status is not unified | [`README.md`](../../../../ok-cluster/README.md), [`Makefile`](../../../../ok-cluster/Makefile) |
| Ingress, observability and ordinary add-ons | Make targets and GitOps/platform repositories | GitOps/platform controllers | No | Yes where already GitOps-managed; migration evidence may be needed | [`Makefile`](../../../../ok-cluster/Makefile) |
| Upgrade strategy | Separate Crossplane upgrade claim or `ok-cluster` blue/green workflow | One cluster contract transition plus CAPI-supported rollout semantics | Yes where it expresses product policy | Partial — CAPI covers rollout primitives; blue/green workflow is procedural | [`xrd-upgrade.yaml`](../../../platform/cluster-management/crossplane/xrd-upgrade.yaml), [`Makefile`](../../../../ok-cluster/Makefile) |
| Workload migration policy | `ok-cluster` blue/green convention and human confirmation | Platform/application owners; OpenKubes may declare admissible policy | Coordination | Partial — stateless GitOps and app-native assumptions exist, outcome is not reconciled | [`Makefile`](../../../../ok-cluster/Makefile) |
| Registration with management services | `ok-cluster` register/unregister commands | Derived, policy-authorized integration with explicit trust boundary | Undetermined | Partial — resources and protections exist; lifecycle trigger/status not defined | [`Makefile`](../../../../ok-cluster/Makefile) |
| Credential and secret material | Crossplane secret fields, runner mounts, generated kubeconfigs | Secret-management/trust-domain mechanisms; short-lived least privilege for executors | No | Partial — current path works but exposes implementation/security wiring | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`composition.yaml`](../../../platform/cluster-management/crossplane/composition.yaml) |
| Executor/runner image | Crossplane cluster and operation claims | Deployment/release configuration outside the cluster contract | No | Yes — normal workload release mechanisms | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml) |
| Rendered manifests and kubeconfig files | Runner filesystem and `ok-cluster` working tree | Disposable executor artifacts; never lifecycle authority | No | Yes if treated as non-authoritative and reproducible | [`README.md`](../../../platform/cluster-management/capi-platform-v4.2/README.md), [`render.py`](../../../../ok-cluster/render.py) |
| CAPI/infra objects and Machine remediation | CAPI/CAPK in `ok-mgmt` | CAPI/CAPK and bootstrap/control-plane providers | No | Yes, subject to management-plane recoverability evidence | [ADR-031](../../decisions/ADR-Platform-031-ok-mgmt-disaster-recovery.md), [outage scenario](scenarios/management-plane-outage.md) |
| Enablement condition/status | Runner waits and command outcomes | Owner of enablement reconciliation publishes current-generation conditions | Coordination | No durable owner demonstrated | [`wait-cluster.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/wait-cluster.sh) |
| Platform convergence/status | GitOps and workload controllers; command-line observations | GitOps owns resources; OpenKubes may reference/aggregate their condition | Coordination | Partial — convergence exists, normalized generation-aware status unproven | [ADR-030](../../decisions/ADR-Platform-030-control-plane-execution-model.md) |
| Overall lifecycle outcome (`Ready`) | Ad hoc runner/Make success and underlying conditions | Derived from named owner conditions for requested generation | Coordination | Unknown — may be composition/status aggregation or require a thin reconciler | [ADR-030](../../decisions/ADR-Platform-030-control-plane-execution-model.md), [`evidence-plan.md`](evidence-plan.md) |
| Operation authorization | Human command access, Kubernetes RBAC and test GO gate | Policy/RBAC authorizes a bounded semantic mutation | Yes for operation vocabulary/policy integration | Partial — primitives exist; semantic operation enforcement is unproved | [`preflight-go-no-go.md`](preflight-go-no-go.md) |
| Evidence/audit record | Logs, commands and spike evidence directory | Evidence mechanism records request generation, authorization, observations and outcome | Yes for evidence contract | Partial — spike structure exists; durable product mechanism undecided | [`evidence-plan.md`](evidence-plan.md), [`evidence/README.md`](evidence/README.md) |
| Deletion/finalization | Cleanup claim, runner direct deletes, CAPI finalizers | Contract deletion transition; each controller finalizes owned resources; evidence retained separately | Coordination | Partial — CAPI finalization exists, fallback cleanup can bypass ownership | [`xrd-cleanup.yaml`](../../../platform/cluster-management/crossplane/xrd-cleanup.yaml), [`cleanup.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/cleanup.sh) |
| Management-plane authority, fencing and DR | `ok-mgmt`; proposed ADR-031 controls | ADR-031/Tier-0 DR mechanism | No — outside ADR-030 component decision | Not evaluated by this spike beyond controlled recoverability | [ADR-031](../../decisions/ADR-Platform-031-ok-mgmt-disaster-recovery.md) |

## Boundary conclusions supported by current evidence

### Existing owners that must not be duplicated

- CAPI and infrastructure providers own cluster, control-plane, Machine and provider
  resource reconciliation.
- `ok-linux` owns OS profile/image construction and identity.
- GitOps and workload controllers own persistent platform resources and drift
  convergence.
- Provider and workload APIs remain the authorities for their observed actual state.

### OpenKubes semantics that exist independently of an operator

- a cluster identity and role/profile selection;
- a bounded operation vocabulary and policy integration;
- the distinction between infrastructure, enablement and platform readiness;
- evidence that ties authorization, requested generation and observed outcome;
- product policy such as allowed upgrade strategy.

These semantics justify a contract boundary, but do **not** yet justify a new
long-running controller.

### Gaps requiring evidence, not immediate components

- one authoritative desired-state record instead of cluster/upgrade/cleanup workflow
  objects and local state;
- endpoint and CIDR allocation authority;
- durable cluster enablement and its condition owner;
- generation-aware aggregation of infrastructure, enablement and platform outcomes;
- deletion evidence and bounded exceptional cleanup;
- server-side interpretation that cannot drift from CLI validation/diff behavior.

## Component decision gate

The spike will classify the result only after existing mechanisms are tested against
the gaps above:

| Outcome | Evidence-based interpretation |
|---|---|
| **A — no operator** | Existing APIs/controllers can own all durable semantics; CLI/contract/policy and evidence tooling are sufficient. |
| **B — thin adapter/aggregator** | Only OpenKubes composition or normalized status remains, and cannot be expressed reliably with existing mechanisms. |
| **C — OpenKubes operator** | A distinct, durable OpenKubes desired state requires continuous reconciliation that no existing owner can correctly perform. |
| **D — redraw boundaries** | A proposed component would duplicate CAPI, enablement, GitOps, policy, allocation or OS/provider authority. |

**Current checkpoint: unclassified.** The inventory shows candidate gaps, but no
evidence yet selects A, B, C or D. In particular, neither a read-only CLI nor a
ClusterClass evaluation requires an OpenKubes operator.

## Next read-only experiments

1. Map the current rendered CAPI resources and variables to ClusterClass/managed
   topology capabilities; record unsupported semantics without implementing a class.
2. Trace each status signal to its sole writer and test whether existing composition
   mechanisms can express current-generation aggregate readiness.
3. Model endpoint/CIDR allocation as a capability and authority problem, comparing
   current local/live checks with existing IPAM mechanisms.
4. Define a normalized, implementation-neutral sample input only after those mappings;
   use it for validation/explain/diff experiments, not submission.
5. Re-evaluate the A/B/C/D gate before proposing any write path or controller.

Infrastructure mutation remains governed by
[`preflight-go-no-go.md`](preflight-go-no-go.md) and is currently **NO-GO**.
