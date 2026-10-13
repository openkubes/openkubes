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
| `install/` | provider-kubernetes with a named ServiceAccount and watches enabled, the `in-cluster` ProviderConfig (InjectedIdentity), and `namespace-guard.yaml`, a ValidatingAdmissionPolicy that keeps workspace Namespaces dedicated. |
| `rbac/provider-kubernetes-clusterrole.yaml` | The authority this capability adds to the provider: the kinds the Composition emits. No RBAC kinds, Pods or exec. |
| `rbac/authority-boundary.yaml` | Unbound operator and observer ClusterRoles. There is no requester role in this increment. See *Provider and human authority*. |
| `tests/functions.yaml` | Pinned function packages (go-templating v0.9.2, auto-ready v0.4.1). |

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
in a hyphen (the result contains two adjacent hyphens but ends in `r`). The name rule also makes the
`workspaceID` unique in the cluster: a second document with the same ID has the same Kubernetes
object key and the API server rejects its create with AlreadyExists. A distinct XR name with that
workspaceID is instead rejected by CEL before it is persisted or reconciled; this is the negative
case in the live proof. Deleting this rejected distinct name first returns NotFound and leaves the first workspace and its
resources intact; deleting the first document first cleans up its resources, and a later delete of
the rejected distinct name still returns NotFound because that XR never existed. Deleting the
canonical name always targets the owner, even if it is read from a duplicate manifest.

Composed Objects are named `dw-<10 hex of sha256(workspaceID)>-<resource>` and stay under 63
characters for every ID the schema allows; the template fails on a collision within one workspace.
The truncated hash is not a uniqueness guarantee between different workspaceIDs. The admission
rule closes reuse of the same workspaceID; distinct-ID hash collisions remain outside this proof.
Crossplane 2.3.3 supplies a secondary safeguard: its function composer uses
server-side apply and records that adding a controller owner reference fails when the object already
has a different controller. Its observer also ignores a referenced composed resource controlled by
a different XR before a later apply fails. See the pinned
[Crossplane 2.3.3 composer source](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/apiextensions/composite/composition_functions.go#L615-L628)
and [observer source](https://github.com/crossplane/crossplane/blob/v2.3.3/internal/controller/apiextensions/composite/composition_functions.go#L824-L829).
The capability does not rely on that implementation behavior for workspace identity: Kubernetes
object-key uniqueness rejects a canonical duplicate, while XRD admission rejects a distinct-name
duplicate before reconciliation.

**Dedicated Namespace.** `install/namespace-guard.yaml` lets the provider identity change or delete
only Namespaces it created for a workspace (they carry `workspace.openkubes.io/id` from creation),
and write only objects whose workspace label matches their Namespace's. A workspace whose
Namespace already exists is refused it, and its `DeveloperWorkspace` never becomes Ready.

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

The complete default holder policy checked by `authority-who-can` is below. `C/U/P/D` means
`create/update/patch/delete`; “all four” means DeveloperWorkspace, Object, ProviderConfig and
EnvironmentConfig. ServiceAccount subjects are written as `namespace:name`. The table counts any
name-restricted mutation grant on a kind, not only grants on the two installed config names.

| Subject | Binding / role | Kind | Mutation verbs |
|---|---|---|---|
| Group `system:masters` | Kubernetes `cluster-admin` | all four | C/U/P/D |
| ServiceAccount `kube-system:generic-garbage-collector` | `system:controller:generic-garbage-collector` | all four | U/P/D |
| ServiceAccount `kube-system:namespace-controller` | `system:controller:namespace-controller` | all four | D |
| ServiceAccount `crossplane-system:crossplane` | `crossplane`, including materialized system aggregates | all four | C/U/P/D |
| Group `crossplane:masters`, if default binding exists | `crossplane-admin` | all four | C/U/P/D |
| ServiceAccount `crossplane-system:rbac-manager` | `crossplane-rbac-manager` | none of the four | none (manages RBAC instead) |
| ServiceAccount `crossplane-system:developer-workspace-provider-kubernetes` | generated provider-revision system role | Object, ProviderConfig | C/U/P (no D) |
| ServiceAccount `ok174-proof-services:developer-workspace-operator` | temporary proof binding to `developer-workspace-operator` | all four | C/U/P/D (config U/P/D have the name boundary above) |

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
supply Object and ProviderConfig. Kubernetes v1.34.1 (the live profile's tested version) defines the
[controller wildcard grants and default ServiceAccount bindings](https://github.com/kubernetes/kubernetes/blob/v1.34.1/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/controller_policy.go)
and the [cluster-admin role and system:masters binding](https://github.com/kubernetes/kubernetes/blob/v1.34.1/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/policy.go).
The controller ServiceAccount bindings are RBAC holders even if controller loops use a shared
credential; they are not workspace identities. Feature-gated or site-specific additional holders
are not silently accepted.

The live proof enumerates all ClusterRoles, ClusterRoleBindings, Roles and RoleBindings and asserts
the complete holder set on the disposable cluster for each kind and verb. It uses the server's
materialized `rules`, including any `admin`/`edit` aggregation, matches API-group/resource/verb
wildcards, and fails with the names of extra or missing subjects. Evidence records only subject
kind/name/namespace per kind/verb, never credentials or group membership. All four installed CRDs
must be cluster-scoped; a RoleBinding to either a Role or ClusterRole therefore cannot grant these
mutations and is reported separately as non-effective. A production installation must keep that
set: operators add subjects only via the operator role (in place of the temporary proof
identity), retaining the same name boundaries. Broader human bindings to `cluster-admin`,
`crossplane-admin`, `admin` or `edit` violate this policy. The group subjects denote trusted
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

## Checks

Install the CEL evaluator used by `xrd-check` in a virtual environment (recommended on systems
with externally managed Python):

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -r tests/cel-requirements.txt
source .venv/bin/activate
```

```bash
make functions-up      # function containers for the Development runtime
make render-check      # xrd-check; Composition output == render() for 8 variants and the
                       # longest workspaceID; status phases; fails on a missing profile and on
                       # every one of 35 inputs render() rejects (IPv6 host routes are
                       # rejected too, which render() accepts)
make functions-down
```

For a local render engine, set `CROSSPLANE_RENDER_BINARY` to the Crossplane **controller** binary
from the pinned v2.3.3 image (the CLI binary is a separate executable). This selects
`--crossplane-binary` instead of `--crossplane-version`; functions must still be listening at the
Development targets. Offline harness assertions run with
`python3 tests/live/reconcile_proof_selftest.py`; they do not contact a cluster.

`render-check` equality is with the reviewed `render()` that OK-174's live evidence was
recorded against, for the example profile; the live proof reads back the same equality for the
live profile.

## Live proof (disposable clusters only)

`tests/live/reconcile_proof.py` refuses any context other than `ok-175-proof-admin@ok-175-proof` or the local
pre-flight `kind-ok175-preflight`, requires `TARGET_CONTEXT` to repeat it, and requires
`OK175_TARGET_UID_SHA256` to equal the sha256 of the selected cluster's `kube-system` UID.

```bash
export KUBECONFIG=<disposable cluster kubeconfig> TARGET_CONTEXT=ok-175-proof-admin@ok-175-proof
export OK175_TARGET_UID_SHA256=$(kubectl get ns kube-system -o jsonpath='{.metadata.uid}' | sha256sum | cut -d' ' -f1)
make live-install
# Images default to the OK-174 published digests in the spike's (untracked) published-images.env;
# otherwise set OK175_RUNTIME_IMAGE and OK175_FIXTURE_IMAGE to digest references.
OK175_REGISTRY_USERNAME=<pull-only user> OK175_REGISTRY_PASSWORD_FD=3 make live-run REQUIRE_CLEAN=1 3< <password file>
make live-uninstall
```

`live-run` first checks the installed Composition, XRD and ClusterRole equal the local files and
that each XR runs a CompositionRevision with the local pipeline. It then requires, each check with
a control that shows it can fail:

- the API server rejects a persistent lifecycle with ephemeral storage (XRD CEL) and admits the
  consistent document;
- without the profile EnvironmentConfig a workspace composes nothing and is not Ready;
- a workspace whose Namespace already exists is refused it: no label added, nothing written,
  the owner's data intact, not Ready (control: the persistent workspace below; with the policy
  binding removed, the same workspace adopted the Namespace on the kind pre-flight);
- a persistent workspace: no pre-existing Namespace; reconciled objects equal `render()`; XR
  `Ready` with `lifecyclePhase: running`;
- duplicate workspaceID CREATE under a distinct XR name is rejected by the canonical-name CEL
  rule before persistence, with no composed refs or Ready state; before/after owner identity,
  desired content and Namespace resourceVersion stay unchanged, and read-back still equals
  `render()` (Object resourceVersions are recorded; status reconciliation may advance them);
- deleting the rejected name before its persistent owner leaves the owner intact; deleting the
  ephemeral owner before the rejected name cleans up normally (both orders);
- temporary operator and observer bindings satisfy the table above with `auth can-i --as` and
  real server-side dry-run create/update attempts for all four kinds; each observer denial has
  an operator allowed control. Positive XR attempts pass admission, while the duplicate request
  independently proves that the server executes its CEL;
- `authority-who-can` enumerates the complete cluster RBAC holder set for create/update/patch/delete
  on all four steering kinds, asserts the documented table, and records subject identities and
  non-effective RoleBinding rules; extra bindings or wildcard grants fail the proof;
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
- deleting the XR removes its Namespace, every composed Object (counted first) and the PV;
- then the same for an ephemeral workspace (`emptyDir`, no PVC), one workspace at a time.

The source endpoint is `tests/live/source-server.py`, mounted over the OK-174 fixture image: it
models a provider that issues workspaces read-only credentials. Results are written to
`evidence/` with the hashes of this directory's files and of the spike inputs (`render()`, the
reused helpers, the live profile), and the target's identity hash.

## Rollback and cleanup

- **Remove one workspace:** `kubectl delete developerworkspace <name>`. Every composed object has
  `deletionPolicy: Delete`, so the Namespace, its PVC and the Deployment go with it. Export
  anything you need from a persistent workspace first.
- **Roll back a Composition change:** the XRD sets `defaultCompositionUpdatePolicy: Manual`, so
  existing workspaces stay on their CompositionRevision until moved; set
  `spec.crossplane.compositionRevisionRef` to the previous revision to roll one back. This is
  Crossplane's revision mechanism; the live proof does not exercise a rollback.
- **Uninstall:** delete every `DeveloperWorkspace`, then `make live-uninstall` (Composition, XRD,
  ProviderConfig, RBAC, provider, functions, Crossplane).
- **Disposable cluster:** tear it down with its lifecycle tooling and delete its kubeconfig.

## Limits (not claimed)

- A Namespace is not a VM or a hostile multi-tenant boundary.
- CPU and memory limits are configured, not stress-tested (OK-176). The quota and limits are the
  values the workspace declares; the profile sets no maximum, so they are not a platform cap.
- `local-path` does not enforce PVC capacity (OK-176).
- Push denial is shown against a source that scopes credentials, standing in for a real
  provider's read-only token; it is not a test of any particular Git host's permissions.
- The live proof does not rerun OpenCode inference; OK-174 proved that for the same rendered
  objects, which `render-check` and the read-back tie to this reconciler.
- Drift correction covers deleted objects and changed values of rendered fields. A field added
  outside the rendered set (for example an extra egress rule on `default-deny`) is not removed:
  provider-kubernetes applies client-side and manages only the fields it wrote. Making that change
  needs authority no workspace holds.
- The namespace guard keys on the `workspace.openkubes.io/id` label. Anyone who can label a
  Namespace can mark it as a workspace's; that authority already covers the Namespace itself.
- `lifecycle.idleTimeoutMinutes`, `retentionMinutes`, `deletion: after-retention` and
  `evidence.exportBeforeCleanup` are accepted and validated, but not acted on.
- Kubernetes API unreachability is sampled at `kubernetes.default.svc`; node and control-plane
  addresses are not probed.
- Read-back normalization drops fields the API server defaults (inherited from OK-174's harness).
