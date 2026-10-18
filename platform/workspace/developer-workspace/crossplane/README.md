# DeveloperWorkspace — Namespace reference profile (Crossplane)

The reconciler for the `DeveloperWorkspace` contract of
[ADR-Platform-039](../../../../architecture/decisions/ADR-Platform-039-developer-workspace-contract.md)
(OK-175). One `DeveloperWorkspace` reconciles to one dedicated Namespace with a ServiceAccount,
default-deny NetworkPolicy, per-capability egress policies, ResourceQuota, LimitRange,
lifecycle-appropriate storage (a PVC when persistent, a size-limited `emptyDir` when ephemeral)
and the workspace Deployment. Deleting the `DeveloperWorkspace` deletes all of it.

ADR-Platform-039 stays Proposed; this directory supplies implementation evidence only.

## Pieces

| Path | Role |
|---|---|
| `xrd.yaml` | Cluster-scoped XRD, generated from the contract schema by `tests/xrd_schema.py`; the contract fields remain profile-independent, while this profile also requires the Kubernetes resource envelope name described below. |
| `composition.yaml` | Template port of the spike's `render()`; function-go-templating then function-auto-ready. |
| EnvironmentConfig `developer-workspace-profile` | Cluster-scoped input: `profile` (the reviewed NamespaceProfileCatalog), `providerConfigName`, optional `imagePullSecret`. Without it the render fails and nothing is composed. Every check `render()` makes in `validate_profile()` is a `fail` guard here, so any input `render()` rejects composes nothing. |
| EnvironmentConfig `developer-workspace-admission-ready` | Operator-owned installation receipt: exactly `data.guardRevision: ok185-v1`. `live-install` creates it after the admission gate passes. The Composition requires it before emitting workspace resources, including for direct XR submissions. |
| `install/` | provider-kubernetes with a named ServiceAccount and watches enabled, the `in-cluster` ProviderConfig (InjectedIdentity), and Namespace, provider-steering, Namespace label and Pod user-namespace admission policies described below. |
| `rbac/provider-kubernetes-clusterrole.yaml` | The authority this capability adds to the provider: the kinds the Composition emits. No RBAC kinds, Pods or exec. |
| `rbac/authority-boundary.yaml` | Unbound operator and observer ClusterRoles. There is no requester role in this increment. See *Provider and human authority*. |
| `tests/functions.yaml` | Pinned function packages (go-templating v0.9.2, auto-ready v0.4.1). |
| `tests/profile_config.py` | Shared capability profile loader, reference rendering extension, and EnvironmentConfig builder for render-check and the live proof. |

`Ready` on a `DeveloperWorkspace` means the workspace Deployment has an available replica,
which means the checkout init container succeeded. `status.lifecyclePhase` is `pending` until
then and `running` after.

### Resource envelope and workspace identity

This implementation profile requires `metadata.name` to equal `spec.workspaceID + "-xr"`. The
contract fields stay independent of the runtime and Namespace profile, but the complete Kubernetes
document is therefore portable only when its resource envelope follows this naming rule. For
example, `spec.workspaceID: ws-review-42` requires `metadata.name: ws-review-42-xr`; a consumer that
uses `metadata.name: alice-review` must rename the resource before this profile will admit it.

The schema permits a `workspaceID` of at most 51 characters. Appending `-xr` produces a canonical
name of at most 54 characters that remains a valid DNS subdomain, including when the ID itself ends
in a hyphen (the result contains two adjacent hyphens but ends in `r`). The live proof separates two
properties of this rule. `canonical-name-rule` shows that CEL rejects a noncanonical
`metadata.name` before persistence or reconciliation. `workspace-id-duplicate-create-refused`
submits a second real `kubectl create` with the owner's canonical name and requires the API server's
`AlreadyExists` response while the owner and its resources remain unchanged.

The canonical name is the Kubernetes object key, not a second authorization boundary. Applying,
replacing or deleting a duplicate manifest addresses the existing owner. Those actions require the
trusted `developer-workspace-operator` authority described below; this increment has no requester
role.

Composed Objects are named `dw-<32 lowercase hex characters of sha256(workspaceID)>-<resource-key>`,
then truncated to 63 characters and stripped of a trailing hyphen. The prefix, 128-bit digest and
separator consume 36 characters, leaving 27 visible resource-key characters. A capability-derived
key can reach 93 characters, so the final name intentionally retains only its first 27 characters.
The template fails closed if two keys in one workspace produce the same final name. The live
`distinct-workspace-isolation` check uses `ws-c69924` and `ws-cd9634`,
which collided under the former 40-bit names, and requires disjoint Object names and UIDs and
separate Namespaces before deleting either workspace.
Crossplane 2.3.3 supplies a secondary safeguard: its function composer uses
server-side apply and records that adding a controller owner reference fails when the object already
has a different controller. Its observer also ignores a referenced composed resource controlled by
a different XR before a later apply fails. See the pinned
[Crossplane 2.3.3 composer source](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/apiextensions/composite/composition_functions.go#L615-L628)
and [observer source](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/apiextensions/composite/composition_functions.go#L824-L829).
The capability does not rely on that implementation behavior for workspace identity: Kubernetes
object-key uniqueness rejects a second create at the canonical name, while XRD admission rejects a
noncanonical name before reconciliation.

**Dedicated Namespace.** `install/namespace-guard.yaml` lets the provider identity change or delete
only Namespaces it created for a workspace (they carry `workspace.openkubes.io/id` from creation),
and write only objects whose workspace label matches their Namespace's. A workspace whose
Namespace already exists is refused it, and its `DeveloperWorkspace` never becomes Ready.

**Pod user namespace and persistent-capacity policy.** The catalog requires `spec.hostUsers` and
the following operator-owned declaration beside `spec.storageClassName`:

```yaml
spec:
  storageClassName: quota-class
  hostUsers: false
  persistentCapacity:
    runtimeEnforced: true
    capacityEnforcingStorageClasses:
      - quota-class
```

`runtimeEnforced` is a boolean, and `capacityEnforcingStorageClasses` is a list of StorageClass
names. The profile fails closed: when `runtimeEnforced` is true, `hostUsers` must be false and the
selected `storageClassName` must appear in the list. Missing fields, wrong types, unknown keys,
invalid names and inconsistent combinations are rejected before rendering. These are cluster
profile policies, independent of runtime image choice; none is a field in the portable
DeveloperWorkspace contract.

This declaration is a Composition gate owned by the operator. It is not runtime certification of a
storage backend. Before setting `runtimeEnforced: true`, a deployment must separately prove that
each listed StorageClass enforces the declared byte capacity at runtime under the selected
`hostUsers: false` boundary. The checked-in profiles derive from the frozen live spike YAML;
`tests/live/profile_examples_selftest.py` checks each one against that catalog plus its reviewed
capability fields. The `namespace-profile-local-path.yaml` example sets `hostUsers: true`,
`runtimeEnforced: false`, and an empty `capacityEnforcingStorageClasses` list. It remains the
observed-negative profile and cannot claim capacity enforcement. The spike files stay unchanged.
The Composition sets `workspace.openkubes.io/host-users: "false"` on the Namespace only when
`hostUsers: false` is required. `install/pod-user-namespace-guard.yaml` binds the
`workspace-pod-user-namespace-required` ValidatingAdmissionPolicy with `validationActions: [Deny]`
and `failurePolicy: Fail`. In those Namespaces it requires an explicit `spec.hostUsers: false`
on every Pod CREATE and UPDATE, including `pods/ephemeralcontainers`; it excludes `pods/status`.
This applies to manual Pods and ReplicaSet-created Pods regardless of caller identity. Rolling
updates create compliant replacement Pods; ordinary updates and ephemeral-container additions
retain the existing Pod's user namespace setting. A legacy noncompliant Pod's update is denied:
the rule does not repair or evict existing Pods. Profiles with `hostUsers: true` omit the label
and are unaffected.

Namespace-only placement keeps the selection signal off unrelated objects and Pod templates;
the capability reference rendering adds exactly the same Namespace label as the Composition.
Read-back equality includes it, and provider reconciliation manages that rendered field.

**Label trust boundary.** `install/namespace-host-users-guard.yaml` protects both the old and new
Namespace identity and selection labels, including Namespace subresource updates. Two bindings
select the workspace-ID label or the host-users label before parameter loading; each selector
matches the old or new object, so removing both labels still reaches admission. Unrelated
Namespaces remain writable when the profile is missing. A workspace
identity or observer cannot add, remove or change either protected label, including removing
both labels in one update, even with Namespace update/patch RBAC. This guarantee covers the
labels only. The guard does not protect `ownerReferences` or `finalizers`: a caller with Namespace
update/patch authority can change those while preserving labels. Pointing an ownerReference at a
deletable owner can cause garbage collection through the trusted garbage collector's deletion
authority. Production installations must reserve Namespace mutation permissions to trusted platform
identities; the workspace and observer roles grant none. Temporary name-scoped grants in the live
proof exist only to distinguish admission denials from RBAC denials.

The provider may reconcile only the value rendered from the named,
operator-owned `developer-workspace-profile`: `"false"` when `spec.hostUsers` is false, otherwise
no label. An arbitrary provider-kubernetes Object cannot supply an alternative value.
The operator exemption uses authorization to update that named EnvironmentConfig, including
the trusted platform identities in the authority-holder table below. That is platform authority because changing the profile changes the runtime boundary for all workspaces;
the existing operator role also permits arbitrary provider Objects. The provider is explicitly
excluded from this operator exemption. Direct Namespace changes still require Namespace RBAC;
the operator ClusterRole alone does not grant it. Changing the profile or CompositionRevision
does not retroactively validate or evict existing Pods. User namespaces close the observed
project-ID reset bypass; admission alone does not prove storage capacity enforcement.

The rendered Namespace alone records the declaration as
`workspace.openkubes.io/persistent-capacity: runtime-enforced` or
`workspace.openkubes.io/persistent-capacity: not-runtime-enforced`. This label is an audit marker
for the operator's declaration; it is not a certification result. 

**One workspace shape per cluster.** The profile is a single cluster-wide EnvironmentConfig whose
catalogs must match each workspace's references exactly (as `render()` requires), so every
workspace on a cluster declares the same source, model, capability and credential references.

## Provider and human authority

provider-kubernetes acts with its own identity, which a workspace never receives. That identity is
platform authority, close to cluster-admin in effect: besides `rbac/`, Crossplane's RBAC manager
grants every provider `*` on Secrets, ConfigMaps, Events and Leases cluster-wide, and creating
Deployments with any ServiceAccount in any Namespace reaches whatever those accounts can do. Only
platform operators and the default platform identities listed below may create
`objects.kubernetes.crossplane.io`, edit the `in-cluster`
ProviderConfig, or edit the `developer-workspace-profile` EnvironmentConfig (it chooses images,
Secret names and the ProviderConfig). Creating a `DeveloperWorkspace` directs the provider too, so
it is granted through cluster RBAC on the cluster-scoped kind, not to workspaces. The live proof
records the provider's `can-i --list` as the privileged control.

These grants come from the pinned Crossplane 2.3.3
[provider system role](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/rbac/provider/roles/roles.go#L57-L79),
[provider ServiceAccount binding](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/rbac/provider/binding/reconciler.go#L201-L214),
and the chart's default-enabled
[RBAC manager](https://github.com/crossplane/crossplane/blob/v2.3.3/cluster/charts/crossplane/values.yaml#L94-L98).

`rbac/authority-boundary.yaml` defines the human-facing boundary. It intentionally contains no
RoleBinding or ClusterRoleBinding; a production installation must select its operator and observer
subjects. The live harness creates temporary ServiceAccounts and bindings only for its proof, then
removes them. There is no requester role in this increment, so workspace creation is operator-only.

| Role | Kind (API group) | Verbs | Name boundary |
|---|---|---|---|
| `developer-workspace-operator` | `DeveloperWorkspace` (`workspace.openkubes.io`) | `get`, `list`, `watch`, `create`, `update`, `patch`, `delete` | all |
| `developer-workspace-operator` | `Object` (`kubernetes.crossplane.io`) | `get`, `list`, `watch`, `create`, `update`, `patch`, `delete` | all |
| `developer-workspace-operator` | `ProviderConfig` (`kubernetes.crossplane.io`) | `get`, `update`, `patch`, `delete` | `in-cluster` only |
| `developer-workspace-operator` | `ProviderConfig` (`kubernetes.crossplane.io`) | `create` | all names |
| `developer-workspace-operator` | `EnvironmentConfig` (`apiextensions.crossplane.io`) | `get`, `update`, `patch`, `delete` | `developer-workspace-profile` only |
| `developer-workspace-operator` | `EnvironmentConfig` (`apiextensions.crossplane.io`) | `create` | all names |
| `developer-workspace-observer` | `DeveloperWorkspace` (`workspace.openkubes.io`) | `get`, `list`, `watch` | all |
| requester | none | none | no requester role is defined |

Kubernetes cannot restrict top-level `create` by `resourceNames`, because authorization occurs
before the new object's name is known. The two all-name create rules above are therefore broader
than their named read/write/delete partners; constraining creation further requires admission
policy, as described in the
[Kubernetes RBAC reference](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-resources).

The direct holder policy checked by `authority-who-can` is below. `C/U/P/D/DC` means
`create/update/patch/delete/deletecollection`; “original four” means DeveloperWorkspace, cluster
Object, cluster ProviderConfig and EnvironmentConfig. “all audited kinds” adds the provider APIs
listed below (including ProviderConfigUsage for the complete namespaced inventory).
ServiceAccount subjects are written as `namespace:name`.
The table counts any name-restricted mutation grant on a kind, not only grants on the two installed
config names.

| Subject | Binding / role | Kind | Mutation verbs |
|---|---|---|---|
| Group `system:masters` | Kubernetes `cluster-admin` | all audited kinds | C/U/P/D/DC |
| ServiceAccount `kube-system:generic-garbage-collector` | `system:controller:generic-garbage-collector` | all audited kinds | U/P/D |
| ServiceAccount `kube-system:namespace-controller` | `system:controller:namespace-controller` | all audited kinds | D/DC |
| ServiceAccount `crossplane-system:crossplane` | `crossplane`, including materialized system aggregates | all audited kinds | C/U/P/D/DC |
| Group `crossplane:masters`, if default binding exists | `crossplane-admin` | all audited kinds | C/U/P/D/DC |
| ServiceAccount `crossplane-system:rbac-manager` | `crossplane-rbac-manager` | none of the audited kinds | none (manages RBAC instead) |
| ServiceAccount `crossplane-system:developer-workspace-provider-kubernetes` | generated provider-revision system role | all provider-kubernetes audited kinds | C/U/P (no D) |
| ServiceAccount `ok174-proof-services:developer-workspace-operator` | temporary proof binding to `developer-workspace-operator` | original four | C/U/P/D, no DC (config U/P/D have the name boundary above) |

This expected set is written explicitly in the harness, derived from documented sources rather
than a cluster dump. The pinned Crossplane 2.3.3 chart defines the
[default group binding and base/aggregated controller roles](https://github.com/crossplane/crossplane/blob/v2.3.3/cluster/charts/crossplane/templates/rbac-manager-managed-clusterroles.yaml),
the [controller ServiceAccount](https://github.com/crossplane/crossplane/blob/v2.3.3/cluster/charts/crossplane/templates/serviceaccount.yaml),
and the [RBAC-manager ServiceAccount](https://github.com/crossplane/crossplane/blob/v2.3.3/cluster/charts/crossplane/templates/rbac-manager-serviceaccount.yaml)
and [permissions](https://github.com/crossplane/crossplane/blob/v2.3.3/cluster/charts/crossplane/templates/rbac-manager-clusterrole.yaml).
Its [XRD roles](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/rbac/definition/roles.go)
and [provider roles](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/rbac/provider/roles/roles.go)
aggregate the XR/provider CRD kinds into `crossplane-admin`/`crossplane-edit` and the core controller
role. The provider's own system role omits `delete`. The pinned provider-kubernetes
[v1.3.1 CRDs](https://github.com/crossplane-contrib/provider-kubernetes/tree/v1.3.1/package/crds)
supply the cluster and namespaced provider kinds listed below. Kubernetes v1.34.1 (the live profile's tested version) defines the
[controller wildcard grants and default ServiceAccount bindings](https://github.com/kubernetes/kubernetes/blob/v1.34.1/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/controller_policy.go)
and the [cluster-admin role and system:masters binding](https://github.com/kubernetes/kubernetes/blob/v1.34.1/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/policy.go).
The controller ServiceAccount bindings are RBAC holders even if controller loops use a shared
credential; they are not workspace identities. Feature-gated or site-specific additional holders
are not silently accepted.

**Trusted Namespace label operators.** The Namespace guard's `operator` CEL variable uses
authorization to update the named `developer-workspace-profile`, rather than membership in the
human operator role. The following platform subjects therefore intentionally satisfy the exemption.
This is documented platform trust, not an assertion that they lack Namespace mutation routes.

| Trusted subject | Namespace guard trust |
|---|---|
| Group `system:masters` | Cluster administration, including named profile updates. |
| ServiceAccount `crossplane-system:crossplane` | Crossplane controller authority includes named profile updates. |
| ServiceAccount `kube-system:generic-garbage-collector` | Garbage collection authority includes named profile updates and deletion through ownerReferences. |
| Group `crossplane:masters`, when its default binding exists | Crossplane administration includes named profile updates. |
| Subjects granted update on `EnvironmentConfig/developer-workspace-profile` | Trusted platform operators; direct Namespace writes still require separate Namespace RBAC. |

These identities must remain outside workspace and observer control, including impersonation,
token and RBAC escalation routes audited by `authority-indirect-who-can`. Trusting the controllers
matches their existing platform lifecycle authority; treating them as untrusted would require a
different controller/RBAC design. The named provider identity remains explicitly excluded from
`operator`, even when authorization says it can update the profile.

`authority-indirect-who-can` checks the following ways to mint or use authority. Cluster-scoped
mutations and User/Group impersonation count ClusterRoleBindings; ServiceAccount impersonation,
Role bind/escalate, ClusterRole bind through RoleBindings and RoleBinding mutations count grants
in every namespace. The token, Pod and Secret rows are
restricted to `crossplane-system`. `M` is Group `system:masters`; `G` is the optional Group
`crossplane:masters` when the chart's default binding exists. Every other entry is a User or
ServiceAccount (`namespace:name`) exactly as shown.

| Permission | Expected subjects |
|---|---|
| `impersonate` users or groups | M |
| `impersonate` serviceaccounts | M; `crossplane-system:crossplane` |
| `bind` Roles | M |
| `bind` ClusterRoles | M; `crossplane-system:rbac-manager` |
| `escalate` Roles | M; `crossplane-system:rbac-manager` |
| `escalate` ClusterRoles | M; `crossplane-system:rbac-manager`; `kube-system:clusterrole-aggregation-controller` |
| `create` ClusterRoleBindings | M; `crossplane-system:rbac-manager`; G |
| `update` or `patch` ClusterRoleBindings | M; `crossplane-system:rbac-manager`; `kube-system:generic-garbage-collector`; G |
| `create` RoleBindings | M; G |
| `update` or `patch` RoleBindings | M; `kube-system:generic-garbage-collector`; G |
| `create` ServiceAccounts in `crossplane-system` | M; User `system:kube-controller-manager`; `kube-system:service-account-controller`; `crossplane-system:crossplane`; `crossplane-system:developer-workspace-provider-kubernetes` |
| `create` `serviceaccounts/token` in `crossplane-system` | M; User `system:kube-controller-manager` |
| `create` Pods in `crossplane-system` | M; `kube-system:daemon-set-controller`; `kube-system:job-controller`; `kube-system:persistent-volume-binder`; `kube-system:replicaset-controller`; `kube-system:replication-controller`; `kube-system:statefulset-controller`; when the ok-storage `ok-storage-local-quota` profile is installed, `ok-storage-local-quota:ok-storage-local-quota-provisioner` |
| `get` Secrets in `crossplane-system` | M; User `system:kube-controller-manager`; `kube-system:generic-garbage-collector`; `kube-system:namespace-controller`; `crossplane-system:crossplane`; `crossplane-system:developer-workspace-provider-kubernetes`; `kube-system:cilium-operator`; G |
| `list` Secrets in `crossplane-system` | the `get` set plus `kube-system:resourcequota-controller` |

The Secret-list row includes name-restricted grants: a matching `metadata.name` field selector can
authorize those requests. ClusterRole `bind` grants through a RoleBinding also count because they
authorize binding that ClusterRole inside the RoleBinding's namespace. See the
[Kubernetes RBAC resource-name and binding rules](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).

The Cilium subject comes from its pinned
[v1.19.6 operator ClusterRole](https://github.com/cilium/cilium/blob/v1.19.6/install/kubernetes/cilium/templates/cilium-operator/clusterrole.yaml).
The pinned local-path manifest grants its provisioner Pod creation only through a RoleBinding in
`local-path-storage`; its ClusterRole grants Pod reads but no Secret reads, so it contributes no
subject to these Pod-create or Secret-read rows in `crossplane-system`. Talos uses
the Kubernetes controller identities in the pinned v1.34.1 bootstrap policy linked above.
The ok-storage `ok-storage-local-quota` profile (pinned OpenEBS localpv 4.6.0) binds a ClusterRole
granting its provisioner all verbs on Pods and Namespaces cluster-wide, so that ServiceAccount can
start a Pod under the provider's ServiceAccount: it is platform authority, like the controllers
above. The proof expects it only when that exact ClusterRoleBinding (that ServiceAccount to that
ClusterRole) exists; any other shape of the grant fails the check. ok-storage documents the grant.

The live proof enumerates all ClusterRoles, ClusterRoleBindings, Roles and RoleBindings and asserts
the documented direct holder set on the disposable cluster for each kind and verb. It uses the server's
materialized `rules`, including any `admin`/`edit` aggregation, matches API-group/resource/verb
wildcards, and fails with the names of extra or missing subjects. Evidence records only subject
kind/name/namespace per kind/verb, never credentials or group membership. The harness checks each
installed CRD against its expected scope. RoleBindings to Roles or ClusterRoles count as effective
for Namespaced kinds in their namespace, and are reported as non-effective only for Cluster kinds. A production installation must keep that
set: operators add subjects only via the operator role (in place of the temporary proof
identity), retaining the same name boundaries. Broader human bindings to `cluster-admin`,
`crossplane-admin` or `crossplane-edit` violate this policy. Kubernetes `admin`/`edit`/`view`
do not aggregate these provider kinds in the pinned installation; namespace wildcard Roles still
grant them. The group subjects denote trusted
administrative membership; RBAC enumeration does not enumerate external identity-provider members
or authorization from non-RBAC authorizers.

The operator can steer reconciliation through a `DeveloperWorkspace`, directly manage any
provider-kubernetes `Object`, and change or remove the named ProviderConfig and profile. Creating a
ProviderConfig or EnvironmentConfig is all-name for the reason above, although this Composition
reads only `developer-workspace-profile`, whose `providerConfigName` selects the provider (installed
as `in-cluster`). This role has no permissions for the
Composition, XRD, or the Namespace ValidatingAdmissionPolicy and its binding. The namespace policy
still bounds writes made by the provider identity. The observer can read only
`DeveloperWorkspace` resources and cannot read Objects or the steering configs, or edit anything.

Through a DeveloperWorkspace alone, a creator can choose the workspace identity, source revision,
runtime and lifecycle variants, and declared resource requests/limits. The Composition resolves
source, model, capability and credential references against the exact reviewed profile catalogs;
it refuses unresolved or mismatched references. The creator cannot use these contract fields to
supply another provider identity, arbitrary manifests, a privileged ServiceAccount, arbitrary
images, endpoints or Secret values. The namespace guard bounds the provider's rendered writes to
the dedicated, matching workspace Namespace. The observer cannot edit the profile that supplies
those mappings or create any steering resources. An operator additionally holds direct Object and
profile authority and is therefore trusted platform authority; the guards do not constrain that
operator to the contract-only interface. A requester role would require additional authorization
and resource-bound evidence, so it is intentionally deferred.

The additional provider-kubernetes v1.3.1 API inventory is:

| API group | Resources | Scope |
|---|---|---|
| `kubernetes.m.crossplane.io` | `objects`, `providerconfigs`, `providerconfigusages`, `observedobjectcollections` | Namespaced |
| `kubernetes.m.crossplane.io` | `clusterproviderconfigs` | Cluster |
| `kubernetes.crossplane.io` | `observedobjectcollections` | Cluster |

A namespace RoleBinding to `crossplane-edit` (or a namespace Role with wildcard rules) can grant
creation and updates of the namespaced kinds. Crossplane aggregates these APIs into
`crossplane-admin` and `crossplane-edit` with `*` verbs. A namespaced ProviderConfig can select
`credentials.source: InjectedIdentity`; paired with an Object it directs the provider's own
privileged identity. A namespaced grant therefore reaches cluster-wide provider authority even
though the original four APIs are Cluster scoped.

`install/provider-steering-guard.yaml` closes this admission path. The
`developer-workspace-provider-steering` policy and Deny binding use `failurePolicy: Fail` and
permit CREATE/UPDATE only when the caller is authorized to update EnvironmentConfig
`developer-workspace-profile` in `apiextensions.crossplane.io`. That named-profile authorization
is the operator definition; a role name or provider identity alone is no exemption. The policy
covers namespaced Objects, ProviderConfigs and ObservedObjectCollections, plus ClusterProviderConfigs
and cluster ObservedObjectCollections, for every served API version. RBAC remains necessary:
passing admission grants no permission, and the shipped operator role does not add these APIs.

The policy denies all non-operator writes to these kinds rather than filtering only
`InjectedIdentity`. This capability uses none of them, so non-operators have no supported use that
requires an exception. Denying the whole kind also covers alternative credential sources and
provider references without depending on their field layout. Operators remain trusted platform
authority. ProviderConfigUsage is inventoried by who-can but is not an admission target: it tracks
usage rather than supplying a credential or manifest to reconcile.

The `namespaced-provider-steering-denied` live check temporarily grants a non-operator
`crossplane-edit` in a scratch Namespace, proves its RBAC create permission, and submits real
ProviderConfig (InjectedIdentity) and Object creates. Both must fail naming the steering policy;
operator controls use server dry-run. The proof removes its temporary resources even on failure.
Offline CEL and harness selftests exercise this path; only a live run establishes API-server
admission enforcement.

## Checks

Install the CEL evaluator used by `xrd-check` in a virtual environment (recommended on systems
with externally managed Python):

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -r tests/cel-requirements.txt
source .venv/bin/activate
```

```bash
make admission-cel-check # provider-steering policy, matching, operator and negative controls
make functions-up      # function containers for the Development runtime
make admission-cel-check # offline Namespace label / Pod policy cases and mutation controls
make render-check      # xrd-check + admission-cel-check; Composition output == reference_render() for both hostUsers settings and the
                       # longest workspaceID; status phases; fails on a missing profile and on
                       # every invalid input reference_render() rejects (IPv6 host routes are
                       # rejected too, which render() accepts)
make functions-down
```

`render-check` and the live proof share `tests/profile_config.py::reference_render()`. It
validates the required `spec.hostUsers` and `spec.persistentCapacity` declaration, removes only
those capability-owned fields from a copy of the profile, calls the unchanged spike `render()`
that OK-174's evidence was recorded against, then sets the Deployment pod's `hostUsers` to the
validated value and adds the Namespace selection label when it is false. Both checks add
`imagePullSecrets` when configured. The Composition has matching
fail guards for malformed or inconsistent declarations.
The extension lives beside the existing EnvironmentConfig helper so the function checks and
live proof use one reference without modifying OK-174's hash-bound historical artefact.
For a local render engine, set `CROSSPLANE_RENDER_BINARY` to the Crossplane **controller** binary
from the pinned v2.3.3 image (the CLI binary is a separate executable). This selects
`--crossplane-binary` instead of `--crossplane-version`; functions must still be listening at the
Development targets. Offline harness assertions run with
`make live-selftest`; it runs the ownership mutation controls, ownership and existing live
harness selftests, and both committed profile examples without contacting a cluster. To see the
named ownership checks fail with their guard disabled, run
`python3 tests/live/hands_on_ownership_selftest.py --prove-mutations`.

`render-check` equality is with `reference_render()`, extending the reviewed `render()` that OK-174's live evidence was
recorded against, for the example profile; the live proof reads back the same equality for the
live profile.

## Live proof (disposable clusters only)

`tests/live/reconcile_proof.py` accepts only `ok-175-proof-admin@ok-175-proof`,
`ok-176-c3-admin@ok-176-c3`, `ok-178-ws-admin@ok-178-ws`, or the local pre-flight `kind-ok175-preflight`,
requires `TARGET_CONTEXT` to repeat it, and requires
`OK175_TARGET_UID_SHA256` to equal the sha256 of the selected cluster's `kube-system` UID.

The disposable `ok-175-proof` profile was bootstrapped from the OpenKubes
[Talos KubeVirt profile](https://github.com/openkubes/ok-linux/blob/a1687263d46c48e47c14f5bf202c9a652d7c1a71/profiles/kubevirt/profile.yaml)
(Talos v1.9.6), with the digest-pinned
[Cilium 1.19.6 acquisition](https://github.com/openkubes/ok-cluster/blob/df5c778f53c1ad3c90fecf5303421d6cc9c408a6/scripts/prepare_cilium_chart.py)
and the vendored upstream
[local-path-provisioner v0.0.30 manifest](https://github.com/openkubes/openkubes/blob/86b12075bac46fd776562510b42ffbb18e005fd7/architecture/spikes/ADR-Platform-030/go1-local-path-prerequisite-v1/upstream-local-path-storage-v0.0.30.yaml).
The proof reads its Kubernetes version from the API server and installs the pinned
[Crossplane 2.3.3 chart](https://github.com/crossplane/crossplane/tree/v2.3.3/cluster/charts/crossplane).
The evidence records Kubernetes and Crossplane versions. Talos and add-on versions here describe
the bootstrap inputs and are not independently attested by that evidence document.

```bash
export KUBECONFIG=<disposable cluster kubeconfig> TARGET_CONTEXT=ok-175-proof-admin@ok-175-proof
export OK175_TARGET_UID_SHA256=$(kubectl get ns kube-system -o jsonpath='{.metadata.uid}' | sha256sum | cut -d' ' -f1)
make live-install
# Required: a capability profile containing spec.storageClassName, spec.hostUsers and
# spec.persistentCapacity. The proof derives its mode from that declaration.
export OK176_PROFILE_FILE=<reviewed-capability-profile.yaml>
# Images default to the OK-174 published digests in the spike's (untracked) published-images.env;
# otherwise set OK175_RUNTIME_IMAGE and OK175_FIXTURE_IMAGE to digest references.
OK175_REGISTRY_USERNAME=<pull-only user> OK175_REGISTRY_PASSWORD_FD=3 make live-run REQUIRE_CLEAN=1 3< <password file>
make live-uninstall
```

`live-install` installs all four admission policies and their Deny bindings before installing
this capability's XRD and Composition. It waits for each policy's current generation to be
observed and for type checking to finish without warnings. Bindings have no readiness status,
so the installer also observes actual denied and allowed server-side dry-runs, using temporary
profile and Namespace fixtures that it removes afterwards. A failed observation stops installation.
See the [Kubernetes VAP type-checking reference](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/#type-checking).

**Creation gate.** Before changing admission guards, `live-install` invalidates the installation
receipt, then installs all four policies and their bindings, waits for current type-checked policy
status, compares installed
specifications to the local files, and exercises admission allow/deny controls. Only after those
checks pass does it create `EnvironmentConfig/developer-workspace-admission-ready` with exactly
`data.guardRevision: ok185-v1`, then install the XRD and Composition. An admission gate failure
leaves the receipt absent. The Composition independently requires this exact receipt before emitting
workspace resources; absent, malformed or obsolete receipts block new provisioning through direct
XR submissions as well as the harness. XR creation itself can still be admitted while provisioning
fails and the XR remains unready. Offline renders exercise absent, wrong and valid receipts; the
live proof also submits direct XRs with absent and wrong receipts and requires zero composed
Objects and no Namespace before restoring the valid receipt and provisioning normally.

Every XR submission through the live harness also repeats the admission gate:
missing, changed or unobserved policies or bindings abort before sending a workspace creation
request. The live proof removes a binding before any workspace exists, verifies that the gated
create refuses it and that neither the XR nor composed Objects appear, then restores admission
and exercises the allowed path.

The receipt attests that guard revision `ok185-v1` passed the installation gate before provisioning
was enabled. It does not continuously certify policy health or detect later mutation. Trusted
platform operators can forge or retain a receipt, change a CompositionRevision, or remove admission
after installation. They must invalidate the receipt before policy installation/update, bump the
guard revision when the guard contract changes, and preserve admission throughout workspace use.
The gate does not retroactively certify existing workspaces, evict existing Pods, or remove
already-created resources when the receipt disappears. Requiring the receipt keeps the enforcement
small while using the installation gate's equality, status and behavioral checks; duplicating those
checks inside the Composition would require a separate policy-inspection implementation. The
Composition also independently fails closed on a missing or invalid profile.

`live-run` first checks the installed Composition, XRD, ClusterRoles and all admission policies/bindings
equal the local files and
that each XR runs a CompositionRevision with the local pipeline. It then requires, each check with
a control that shows it can fail:

- the API server rejects a persistent lifecycle with ephemeral storage (XRD CEL) and admits the
  consistent document;
- without the profile EnvironmentConfig a workspace composes nothing and is not Ready;
- a workspace whose Namespace already exists is refused it: no label added, nothing written,
  the owner's data intact, not Ready (control: the persistent workspace below; with the policy
  binding removed, the same workspace adopted the Namespace on the kind pre-flight);
- a persistent workspace: no pre-existing Namespace; reconciled objects equal the capability reference rendering; XR
  `Ready` with `lifecyclePhase: running`;
- `canonical-name-rule`: a noncanonical XR name is rejected by CEL before persistence or
  reconciliation;
- `workspace-id-duplicate-create-refused`: a second `kubectl create` at the existing canonical
  name returns `AlreadyExists`; owner UID, desired spec, Namespace identity and resourceVersion,
  composed Object identities, resourceVersions and managed specs, and normalized read-back remain
  unchanged. This immediate duplicate-create check requires identical resourceVersions;
- `distinct-workspace-isolation`: the formerly hash-colliding `ws-c69924-xr` and `ws-cd9634-xr`
  are Ready concurrently with
  the ephemeral profile at 100m CPU and 256Mi memory each, disjoint 128-bit-derived Object names and
  UIDs, and distinct Namespaces. Failure to schedule and reach Ready is a proof failure. Deleting the
  second removes only its resources and leaves the first workspace's UIDs, managed specs and
  read-back unchanged. Over this interval, XR, Object and rendered-resource status writes may advance resourceVersions; their
  before/after versions are recorded, while UIDs, desired specs, XR/Object generations and
  normalized rendered content must match. The surviving workspace then supplies the ephemeral
  overflow control: eviction must replace its pod, after which deleting the survivor removes its
  remaining resources;
- temporary operator and observer bindings satisfy the table above with `auth can-i --as` and
  real server-side dry-run create/update attempts for all four kinds; each observer denial has
  an operator allowed control. Positive XR attempts pass admission, while the canonical-name-rule
  request independently proves that the server executes its CEL;
- `authority-who-can` enumerates cluster RBAC holders for
  `create/update/patch/delete/deletecollection` on every audited steering kind, asserts the documented
  direct sets, and records effective namespaced grants and non-effective cluster RoleBinding rules; extra bindings or
  wildcard grants fail the proof. The shipped operator role has no `deletecollection` grant;
- `namespaced-provider-steering-denied` creates a scratch namespace RoleBinding to
  `crossplane-edit` for a non-operator. Real ProviderConfig/InjectedIdentity and Object creates must
  fail naming the steering policy, with admitted operator dry-run controls and cleanup;
- `authority-indirect-who-can` enumerates the documented indirect RBAC paths, using the scopes in
  the table above; extra subjects fail the proof. External identity-group
  membership and non-RBAC authorizers remain outside this enumeration;
- a deleted `default-deny` is recreated (control: new UID) and a patched quota value is reverted;
- the checkout is the declared revision (control: the source's default branch is a newer commit);
- no token mounted; `can-i --list` equals an unbound identity's and passes OK-174's discovery-only
  allowlist, plus the public ClusterTrustBundle read Kubernetes grants every authenticated
  identity; no RoleBindings (control: the provider identity fails both);
- the Kubernetes API is unreachable from the runtime (control: reachable from the proof namespace);
- no push or merge authority: no credential in the runtime's git config or environment, and the
  source refuses its push to `main` for lack of one (TLS verification off for that probe, so the
  answer is the source's); the source refuses a push with the workspace credential (403) while a
  write-credential control push succeeds; no Secret in the workspace Namespace holds the write
  credential;
- Pod user namespace admission (OK-178): in enforced mode, server-side dry-run Pods with
  `hostUsers` absent or true are denied specifically by `workspace-pod-user-namespace-required`,
  and an otherwise identical Pod with false is admitted. In observed-negative mode the Namespace
  lacks the selection label and the policy does not select it;
- label integrity: temporary, named Namespace grants give workspace and observer exactly the
  permissions needed to reach admission. Server dry-runs cover `kubectl label` removal/alteration,
  one UPDATE dropping both protected labels, an UPDATE changing the workspace ID,
  `namespaces/status` and `namespaces/finalize` UPDATEs dropping both labels, and DELETE of the
  protected Namespace. Every denial must name `developer-workspace-namespace-host-users-guard`;
  each attempt has an operator allowed control. The Namespace labels and UID remain unchanged.
  The provider has a rendered-value allowed control and an out-of-value
  Object negative. After denied changes, both `hostUsers: true` and omitted-hostUsers Pods remain
  denied. All temporary grants are removed before the workspace discovery-only authority check;
- `pods/ephemeralcontainers`: a real subresource request on a compliant Pod is allowed, while a
  legacy noncompliant Pod is denied by the Pod policy. Workspace and observer identities are also
  checked for lack of subresource update authority;
- resource bounds (OK-176): three busy loops are throttled to the CPU limit (`cpu.stat`;
  control: usage reaches the limit); allocating 1.5x the memory limit gets the runtime
  `OOMKilled` (control: 0.5x succeeds); the quota rejects a second PVC beyond the declared size
  (control: the quota is fully used); writing 2x the ephemeral `emptyDir` limit evicts the pod and
  the reconciler replaces it (control: half the limit is fine). Overfilling a persistent PVC is
  recorded as negative evidence in `observed-negative` mode: local-path writes past the declared
  size. A valid declaration with `runtimeEnforced: true`, `hostUsers: false`, and `local-path` in
  the declared class list selects the `self-declared-negative` control solely from those profile
  values. That mode always refuses certification: a workspace that does not become Ready records
  the refusal at readiness; a Ready workspace exercises the capacity assertion and records its
  failure, while unexpected enforcement still refuses negative-control certification. In ordinary
  `enforced` mode, checks require `hostUsers: false`, a non-identity runtime UID map,
  rejection of resetting an owned file's project ID to zero with the ID unchanged, and
  ENOSPC/EDQUOT on overfill with allocated bytes bounded by the declared size and stated tolerance;
- a marker written in the persistent runtime survives workspace pod replacement with a changed
  pod UID and unchanged contents;
- deleting the persistent XR removes its Namespace, every composed Object (counted first) and the
  PV; deleting the surviving ephemeral XR after the eviction check removes its Namespace and every
  composed Object, with no PV to remove.

The source endpoint is `tests/live/source-server.py`, mounted over the OK-174 fixture image: it
models a provider that issues workspaces read-only credentials. Successful proof results are
written to `evidence/` with the hashes of this directory's files and of the spike inputs
(`render()`, the reused helpers, the live profile), and the target's identity hash. A self-declared
negative control never writes an evidence report.

To exercise the deliberately incorrect self-declaration, use the checked-in fixture on the
allowlisted disposable proof cluster:

```bash
export KUBECONFIG=<disposable cluster kubeconfig> TARGET_CONTEXT=ok-175-proof-admin@ok-175-proof
export OK175_TARGET_UID_SHA256=$(kubectl get ns kube-system -o jsonpath='{.metadata.uid}' | sha256sum | cut -d' ' -f1)
export OK176_PROFILE_FILE=tests/fixtures/self-declared-local-path.yaml
# Set OK175_RUNTIME_IMAGE and OK175_FIXTURE_IMAGE to the approved digest references,
# or use make live-run's published-images.env inputs as above.
make live-install
make live-run REQUIRE_CLEAN=1
```

`make live-run` is expected to exit 1. It prints one JSON refusal named
`persistent-capacity-certification-refused` to stdout and writes no evidence report. If the
workspace is not Ready, the refusal identifies the readiness stage. Otherwise the harness runs the
same capacity assertion used for certification and records the failed assertion; if `local-path`
unexpectedly enforces the bound, the negative control still refuses certification.

`OK175_REGISTRY_USERNAME` and `OK175_REGISTRY_PASSWORD_FD` are needed only when the images need
registry authentication; pass the password through the inherited descriptor as above.
`OK176_PROFILE_FILE` is required and is the only source for the selected StorageClass, user
namespace policy and persistent-capacity mode; those values are no longer free-form proof flags.
The harness checks the installed EnvironmentConfig data against that profile before bringing up
each workspace. Successful runs check it again before cleanup and record its UID, resourceVersion
and data hash in evidence; declaration drift or replacement fails the proof. The refusal-only path
cleans up in `finally` without a final profile readback or evidence write.
The proof derives its mode only from the validated operator declaration. A true declaration with
`hostUsers: false` and the selected class in `capacityEnforcingStorageClasses` selects `enforced`,
except that the same valid declaration for `local-path` selects the refusal-only
`self-declared-negative` control. A false declaration with `local-path` and `hostUsers: true` runs
the `observed-negative` path; invalid declarations fail before cluster operations. The contract
names no storage implementation. Successful evidence records the loaded declaration, derived mode
and proof boundaries; the refusal-only path prints its JSON result to stdout instead.

The enforced overfill probe runs Node in the runtime container, writes in 1 MiB chunks with
`fsync`, and counts allocated bytes (`st_blocks * 512`) recursively in `/workspace`, including
the existing checkout. Total allocation must be within ±1 MiB of the declared capacity; this
is one maximum write quantum, allowing a final partial allocation and filesystem accounting
rounding. Substantial successful filling is required before ENOSPC/EDQUOT counts as a bound.
`statfs` must report total capacity within the same tolerance of the declaration before and
after pressure; a larger backing filesystem with coincidentally low free space fails this check.
The project-ID probe runs in that same runtime: Python 3 `fcntl.ioctl` reads the file's
`FS_IOC_FSGETXATTR`, attempts `FS_IOC_FSSETXATTR` with project ID zero, captures errno and reads
the ID again. If Python is absent, it uses Perl's built-in `ioctl` and numeric `$!` for the
same operation and exact errno. The assertion requires EINVAL (errno 22), as observed for the
Linux user namespace project-ID guard; an unsupported ioctl returning ENOTTY cannot pass.
The runtime Dockerfile installs Git but does not explicitly install Python or Perl; its pinned Node base is not an inventory of available tools. The proof
detects both tools in the runtime and fails closed if neither is available. The smallest image
addition is Python 3, followed by a newly published digest. An `xfs_io` exit status would not
be an exact errno, so it is not a fallback. The probe always runs in the workspace runtime.

## Hands-on OpenCode quickstart

Before using the enforcing profile, install and verify the `ok-storage-local-quota` StorageClass on
the disposable cluster (ok-storage: `LOCAL_QUOTA_APPLY=yes make local-quota-apply`, then
`LOCAL_QUOTA_VERIFY=operator-proof LOCAL_QUOTA_EXPECTED_CONTEXT=<context> make local-quota-verify`,
both with `LOCAL_QUOTA_GUEST_KUBECONFIG`). Create the cluster with ok-cluster's
`workloadUserNamespaces` opt-in and run its `make verify-workload-user-namespaces`; it must print
`PASS` (the worker `provisionerBasePath` matches the StorageClass `BasePath`). Its provisioner must
enforce XFS project quotas at runtime. Workers must
support Kubernetes user namespaces, idmapped mounts for that provisioner, and a nonzero
`user.max_user_namespaces`; Talos defaults that sysctl to zero. The profile routes inference to the
reviewed ok-ai host endpoint, where Ollama must serve the configured model alias
`ok174-gpt-oss:20b`. These are prerequisites to the enforcing example; choose the local-path profile
for observed-negative work on a cluster without that storage and user-namespace setup.

After `make live-install`, use the disposable-context and cluster UID guards, digest image inputs,
and optional registry password descriptor as `live-run` above. `live-up` defaults to the enforcing
`profiles/namespace-profile-local-quota.yaml`; set `OK176_PROFILE_FILE` to an absolute path to select
another reviewed profile:

```bash
export OK180_STATE_FILE="$HOME/.local/state/ok180-hands-on.json"   # persistent; not a tmpfs path
make live-up
# With private images instead:
# OK175_REGISTRY_USERNAME=<pull-only user> OK175_REGISTRY_PASSWORD_FD=3 make live-up 3< <password file>
# Copy the printed kubectl exec command and replace <task> with your OpenCode task.
# It runs opencode run --format json followed by sh verify.sh in /workspace.
make live-down
make live-uninstall
```

Use the same `OK180_STATE_FILE` path for `live-up` and `live-down`, on storage that survives a
reboot: the ledger is the only ownership evidence, and without it cleanup must be done by hand.
The ledger records a per-run
nonce, cluster UID and context, and UIDs of resources this run directly created (XR,
EnvironmentConfig, fixture Namespace and workspace Namespace). The versioned JSON file uses
mode 0600, atomic replacement and fsync so a failed write preserves the last complete journal. It records
provisioner PV ownership only through the bound PVC UID chain. Cleanup requires the recorded UID
and ownership marker before each delete; in `live-up`/`live-down` names and timestamps never
establish ownership (`live-run` instead refuses to start while any object its cleanup deletes by
name already exists). A DELETE that hits a resourceVersion conflict from a controller write is
retried from a fresh ownership-checked read with the same UID precondition. If a run
is interrupted, preserve the ledger and use it for `live-down`. A second `live-up` with an existing
ledger is refused; do not remove the ledger to retry, because that would discard ownership evidence.
`live-up` creates and journals the rendered workspace Namespace before submitting the XR. An
atomic Namespace CREATE rejects a racing existing object; provider observation never substitutes
for that create receipt. The reconciler then manages this explicitly owned Namespace.
The UID boundary means a same-name replacement or an object whose ownership marker is missing or
changed is left untouched, and cleanup reports failure for operator review.
Creates record the UID from the API response before setup continues. If the API create succeeds
but its response or ledger write is lost, the ledger retains an ambiguous intent without a UID.
`live-down` leaves that object untouched and exits nonzero for operator inspection, even if its
nonce matches: a copied nonce cannot prove that a same-name replacement is the original object.

**Manual recovery when `live-down` refuses.** The error names the object and the reason. Inspect
it (`kubectl get <kind> <name> -o yaml`) and compare its UID and the
`workspace.openkubes.io/hands-on-run` annotation with the ledger. If it is the object this run
created (for example an intent-only ledger entry whose create did succeed), an operator deletes it
with a UID precondition (`kubectl delete --raw <api path> -f -` with
`{"preconditions": {"uid": "<uid>"}}`), then reruns `live-down`. If it is not, leave it, remove the
remaining owned objects the same way, and delete the ledger file only after every owned object is
gone. Never delete objects by name alone.

`live-up` leaves one persistent `ws-hands-on-xr` DeveloperWorkspace (`spec.workspaceID: ws-hands-on`) Ready and prints its Namespace,
runtime Pod and exact exec command. Inference endpoint, model and MCP settings come from the
selected profile catalog; the storage class, `hostUsers` and capacity policy are declared there.
The runtime entrypoint renders OpenCode configuration and sleeps until you exec a task.
The source fixture keeps only a read credential: writer authentication is disabled, and no
write-credential control Pod or write Secret is created. The workspace needs fetch authority only.

Both commands require the capability installed and matching the local files. `live-up` refuses
existing workspaces, either destination Namespace, or the shared profile EnvironmentConfig.
`live-down` validates the local ledger and recorded ownership markers, deletes only matching
resources using API DELETE with both UID and current resourceVersion preconditions, and waits for
the workspace Namespace, composed Objects and PV to disappear. For provisioner-created PVs, the
ledger binds the XR UID to the provider Object controller owner reference, its observed PVC UID,
the live PVC UID, and the PV claimRef UID. The initial stamp also tests UID and resourceVersion.
A foreign marker is never overwritten. Namespace and nonce PV scans only detect unrecorded
objects to refuse; they cannot authorize adoption or deletion. Export any
wanted workspace data before deletion. Neither command writes evidence. `live-run` retains its proof
controls and automatic cleanup; it requires an explicit `OK176_PROFILE_FILE` choice and derives
enforcement mode from that profile.
OpenCode inference under user namespaces (`hostUsers: false`) was exercised once at openkubes
`8a5123b`; the operator-retained transcripts are in the
[2026-10-18 hands-on evidence](evidence/hands-on-ok-178-ws-2026-10-18/README.md).
That recorded task used a manual model alias and two scripted tool calls; it does not establish
general agent capability, performance, or production readiness.

## Rollback and cleanup

- **Remove one workspace:** `kubectl delete developerworkspace <name>`. Every composed object has
  `deletionPolicy: Delete`, so the Namespace, its PVC and the Deployment go with it. Export
  anything you need from a persistent workspace first.
- **Roll back a Composition change:** the XRD sets `defaultCompositionUpdatePolicy: Manual`, so
  existing workspaces stay on their CompositionRevision until moved; set
  `spec.crossplane.compositionRevisionRef` to the previous revision to roll one back. This is
  Crossplane's revision mechanism; the live proof does not exercise a rollback.
- **Missing or malformed profile during cleanup:** restore the reviewed
  `developer-workspace-profile` before deleting workspaces. The label guard intentionally denies
  matched Namespace operations, including deletion, without valid parameters.
- **Uninstall:** delete every `DeveloperWorkspace`, then `make live-uninstall` (Composition, XRD,
  ProviderConfig, all admission policies/bindings, RBAC, provider, functions, Crossplane).
- **Disposable cluster:** tear it down with its lifecycle tooling and delete its kubeconfig.

## Limits (not claimed)

- A Namespace is not a VM or a hostile multi-tenant boundary.
- The quota and limits are the values the workspace declares; the profile sets no maximum, so they
  are not a platform cap.
- Resource bounds as proven on a disposable cluster (OK-176):
  - CPU runtime bound: proven.
  - Memory runtime bound: proven.
  - Ephemeral storage runtime bound: proven.
  - Persistent allocation/request bound: proven at admission.
  - Persistent byte-capacity runtime bound with `local-path`: **not supported, not proven.** A
    workspace declaring 1 GiB wrote 1280 MiB.
- The checked-in `local-path` profile is a development or constrained profile and declares
  `runtimeEnforced: false` with no capacity-enforcing StorageClasses. Profile configuration also
  accepts an internally consistent true declaration for `local-path`, because Composition cannot
  inspect backend behavior; the live proof treats that declaration as the refusal-only
  `self-declared-negative` control. `local-path` makes no persistent-capacity isolation guarantee,
  and its persistent workspaces are not conforming under the proposed ADR-Platform-039
  persistent-capacity amendment. Conformance requires a backend proven by the
  `persistent-capacity-enforced` live check; the contract names none.
- `hostUsers: false` requires Kubernetes/runtime support for user namespaces, idmap-compatible
  storage mounts, and `user.max_user_namespaces > 0` on the worker. Talos defaults that sysctl
  to zero; cluster configuration belongs to the cluster/OS implementation. The Talos `/opt`
  local-path directories cannot be idmap-mounted, so this local-path profile keeps host users.
- The new enforcing workspace proof must be run on the selected disposable cluster before
  claiming runtime persistent-capacity enforcement. It covers the owned-file project-ID reset
  and bounded write paths from the workspace runtime, not every ioctl or adversarial operation,
  provisioner restart, worker reboot, or production adoption.
- Push denial is shown against a source that scopes credentials, standing in for a real
  provider's read-only token; it is not a test of any particular Git host's permissions.
- `live-run` itself does not rerun OpenCode inference. OK-174 proved it for the frozen base render;
  `render-check` and read-back tie that base plus the capability's `hostUsers` extension to this
  reconciler. Inference under user namespaces (`hostUsers: false`) was exercised once at openkubes
  `8a5123b` via the [2026-10-18 hands-on flow](evidence/hands-on-ok-178-ws-2026-10-18/README.md): one task,
  one disposable cluster, a manual model alias and two scripted tool calls. This does not prove
  general agent capability, performance, or production readiness.
- Drift correction covers deleted objects and changed values of rendered fields. A field added
  outside the rendered set (for example an extra egress rule on `default-deny`) is not removed:
  provider-kubernetes v1.3.1 uses server-side apply and manages the fields owned by each Object. Making that change
  needs authority no workspace holds.
- The namespace guard keys on the `workspace.openkubes.io/id` label. Anyone who can label a
  Namespace can mark it as a workspace's; that authority already covers the Namespace itself.
- `lifecycle.idleTimeoutMinutes`, `retentionMinutes`, `deletion: after-retention` and
  `evidence.exportBeforeCleanup` are accepted and validated, but not acted on.
- Kubernetes API unreachability is sampled at `kubernetes.default.svc`; node and control-plane
  addresses are not probed.
- Read-back normalization drops fields the API server defaults (inherited from OK-174's harness).
