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
| `xrd.yaml` | Cluster-scoped XRD, generated from the contract schema by `tests/xrd_schema.py`; the portable contract document is the composite resource, unchanged. |
| `composition.yaml` | Template port of the spike's `render()`; function-go-templating then function-auto-ready. |
| EnvironmentConfig `developer-workspace-profile` | Cluster-scoped input: `profile` (the reviewed NamespaceProfileCatalog), `providerConfigName`, optional `imagePullSecret`. Without it the render fails and nothing is composed. Every check `render()` makes in `validate_profile()` is a `fail` guard here, so any input `render()` rejects composes nothing. |
| `install/` | provider-kubernetes with a named ServiceAccount and watches enabled, the `in-cluster` ProviderConfig (InjectedIdentity), and admission policies that keep workspace Namespaces dedicated and require user namespaces where the profile selects them. |
| `rbac/` | The authority this capability adds to the provider: the kinds the Composition emits. No RBAC kinds, Pods or exec. See *Provider authority*. |
| `tests/functions.yaml` | Pinned function packages (go-templating v0.9.2, auto-ready v0.4.1). |
| `tests/profile_config.py` | Shared capability profile loader, reference rendering extension, and EnvironmentConfig builder for render-check and the live proof. |

`Ready` on a `DeveloperWorkspace` means the workspace Deployment has an available replica,
which means the checkout init container succeeded. `status.lifecyclePhase` is `pending` until
then and `running` after.

Composed Objects are named `dw-<10 hex of sha256(workspaceID)>-<resource>`, so names stay unique
and under 63 characters for every ID the schema allows; the template fails on a collision within
one workspace. Two `DeveloperWorkspace`s with the same `workspaceID` would compose the same Object
names; that case is not tested.

**Dedicated Namespace.** `install/namespace-guard.yaml` lets the provider identity change or delete
only Namespaces it created for a workspace (they carry `workspace.openkubes.io/id` from creation),
and write only objects whose workspace label matches their Namespace's. A workspace whose
Namespace already exists is refused it, and its `DeveloperWorkspace` never becomes Ready.

**Pod user namespace policy.** The catalog requires a boolean `spec.hostUsers`, emitted as the
workspace pod's `spec.hostUsers` for every runtime and storage lifecycle. It sits beside
`storageClassName` because these are cluster profile policies, independent of runtime image
choice; neither is a field in the portable DeveloperWorkspace contract. The checked-in
`local-path` catalogs derive from the frozen spike YAML via `tests/profile_config.py`, which
explicitly adds `hostUsers: true`. This includes the live profile used by `reconcile_proof.py`;
the spike files stay unchanged. A capacity-enforcing profile can set it to `false`.
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
Read-back equality includes it, and provider reconciliation manages that rendered field. Namespace
label authority remains platform authority: removing the label bypasses selection until restored,
and changing a profile or CompositionRevision does not retroactively validate existing Pods.
Workspace identities cannot create Pods or change Namespace labels. User namespaces close the
observed project-ID reset bypass; admission alone does not prove storage capacity enforcement.

**One workspace shape per cluster.** The profile is a single cluster-wide EnvironmentConfig whose
catalogs must match each workspace's references exactly (as `render()` requires), so every
workspace on a cluster declares the same source, model, capability and credential references.

## Provider authority

provider-kubernetes acts with its own identity, which a workspace never receives. That identity is
platform authority, close to cluster-admin in effect: besides `rbac/`, Crossplane's RBAC manager
grants every provider `*` on Secrets, ConfigMaps, Events and Leases cluster-wide, and creating
Deployments with any ServiceAccount in any Namespace reaches whatever those accounts can do. Only
platform operators may create `objects.kubernetes.crossplane.io`, edit the `in-cluster`
ProviderConfig, or edit the `developer-workspace-profile` EnvironmentConfig (it chooses images,
Secret names and the ProviderConfig). Creating a `DeveloperWorkspace` directs the provider too, so
it is granted through cluster RBAC on the cluster-scoped kind, not to workspaces. The live proof
records the provider's `can-i --list` as the privileged control.

## Checks

```bash
make functions-up      # function containers for the Development runtime
make render-check      # xrd-check; Composition output == reference_render() for both hostUsers settings and the
                       # longest workspaceID; status phases; fails on a missing profile and on
                       # every invalid input reference_render() rejects (IPv6 host routes are
                       # rejected too, which render() accepts)
make functions-down
```

`render-check` and the live proof share `tests/profile_config.py::reference_render()`. It
requires a boolean `spec.hostUsers`, removes only that field from a copy of the profile, calls
the unchanged spike `render()` that OK-174's evidence was recorded against, then sets the
Deployment pod's `hostUsers` to the supplied value and adds the Namespace selection label only
when it is false. Both checks add `imagePullSecrets` when
configured. The Composition has matching fail guards for missing or non-boolean `hostUsers`.
The extension lives beside the existing EnvironmentConfig helper so the function checks and
live proof use one reference without modifying OK-174's hash-bound historical artefact.

## Live proof (disposable clusters only)

`tests/live/reconcile_proof.py` accepts only `ok-175-proof-admin@ok-175-proof`,
`ok-176-c3-admin@ok-176-c3`, `ok-178-ws-admin@ok-178-ws`, or the local pre-flight `kind-ok175-preflight`,
requires `TARGET_CONTEXT` to repeat it, and requires
`OK175_TARGET_UID_SHA256` to equal the sha256 of the selected cluster's `kube-system` UID.

```bash
export KUBECONFIG=<disposable cluster kubeconfig> TARGET_CONTEXT=ok-175-proof-admin@ok-175-proof
export OK175_TARGET_UID_SHA256=$(kubectl get ns kube-system -o jsonpath='{.metadata.uid}' | sha256sum | cut -d' ' -f1)
make live-install
# Choose all three explicitly; there is no implicit storage/proof mode.
export OK176_STORAGE_CLASS=local-path OK176_HOST_USERS=true OK176_CAPACITY_MODE=observed-negative
# Images default to the OK-174 published digests in the spike's (untracked) published-images.env;
# otherwise set OK175_RUNTIME_IMAGE and OK175_FIXTURE_IMAGE to digest references.
OK175_REGISTRY_USERNAME=<pull-only user> OK175_REGISTRY_PASSWORD_FD=3 make live-run REQUIRE_CLEAN=1 3< <password file>
make live-uninstall
```

`live-run` first checks the installed Composition, XRD, ClusterRole and Pod admission policy/binding
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
- resource bounds (OK-176): three busy loops are throttled to the CPU limit (`cpu.stat`;
  control: usage reaches the limit); allocating 1.5x the memory limit gets the runtime
  `OOMKilled` (control: 0.5x succeeds); the quota rejects a second PVC beyond the declared size
  (control: the quota is fully used); writing 2x the ephemeral `emptyDir` limit evicts the pod and
  the reconciler replaces it (control: half the limit is fine). Overfilling a persistent PVC is
  recorded as negative evidence in `observed-negative` mode: local-path writes past the declared
  size. In `enforced` mode, checks require `hostUsers: false`, a non-identity runtime UID map,
  rejection of resetting an owned file's project ID to zero with the ID unchanged, and
  ENOSPC/EDQUOT on overfill with allocated bytes bounded by the declared size and stated tolerance;
- a marker written in the persistent runtime survives workspace pod replacement with a changed
  pod UID and unchanged contents;
- deleting the XR removes its Namespace, every composed Object (counted first) and the PV;
- then the same for an ephemeral workspace (`emptyDir`, no PVC), one workspace at a time.

The source endpoint is `tests/live/source-server.py`, mounted over the OK-174 fixture image: it
models a provider that issues workspaces read-only credentials. Results are written to
`evidence/` with the hashes of this directory's files and of the spike inputs (`render()`, the
reused helpers, the live profile), and the target's identity hash.

For the capacity-enforcing disposable run, the coordinator selects the existing kubeconfig via
the workspace's cluster switch and supplies:

```bash
export TARGET_CONTEXT=ok-178-ws-admin@ok-178-ws
export OK175_TARGET_UID_SHA256=<sha256 of that cluster's kube-system UID, without a newline>
export OK176_STORAGE_CLASS=ok-storage-local-quota OK176_HOST_USERS=false OK176_CAPACITY_MODE=enforced
# Set OK175_RUNTIME_IMAGE and OK175_FIXTURE_IMAGE to the approved digest references,
# or use make live-run's published-images.env inputs as above.
make live-install
make live-run REQUIRE_CLEAN=1
```

`OK175_REGISTRY_USERNAME` and `OK175_REGISTRY_PASSWORD_FD` are needed only when the images need
registry authentication; pass the password through the inherited descriptor as above. The storage
class name is a profile input; the contract names no implementation. The enforced mode refuses
host users, and observed-negative mode requires `local-path` with host users. Evidence names the
selected class, user namespace policy and proof mode, plus its proof boundaries.

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
- The quota and limits are the values the workspace declares; the profile sets no maximum, so they
  are not a platform cap.
- Resource bounds as proven on a disposable cluster (OK-176):
  - CPU runtime bound: proven.
  - Memory runtime bound: proven.
  - Ephemeral storage runtime bound: proven.
  - Persistent allocation/request bound: proven at admission.
  - Persistent byte-capacity runtime bound with `local-path`: **not supported, not proven.** A
    workspace declaring 1 GiB wrote 1280 MiB.
- With `local-path` this is a development or constrained profile. It makes no persistent-capacity
  isolation guarantee, and its persistent workspaces are not conforming under the proposed
  ADR-Platform-039 persistent-capacity amendment. That needs a storage implementation that enforces
  the declared capacity at runtime; the contract names none.
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
- The live proof does not rerun OpenCode inference. OK-174 proved it for the frozen base render;
  `render-check` and read-back tie that base plus the capability's `hostUsers` extension to this
  reconciler. Inference under user namespaces remains unproven.
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
