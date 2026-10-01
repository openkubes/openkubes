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
| `install/` | provider-kubernetes with a named ServiceAccount and watches enabled, and the `in-cluster` ProviderConfig (InjectedIdentity). |
| `rbac/` | The authority this capability adds to the provider: the kinds the Composition emits. No RBAC kinds, Pods or exec. See *Provider authority*. |
| `tests/functions.yaml` | Pinned function packages (go-templating v0.9.2, auto-ready v0.4.1). |

`Ready` on a `DeveloperWorkspace` means the workspace Deployment has an available replica,
which means the checkout init container succeeded. `status.lifecyclePhase` is `pending` until
then and `running` after.

Composed Objects are named `dw-<10 hex of sha256(workspaceID)>-<resource>`, so names stay unique
and under 63 characters for every ID the schema allows; the template fails on any collision.

## Provider authority

provider-kubernetes acts with its own identity, which a workspace never receives. That identity is
platform authority, close to cluster-admin in effect: besides `rbac/`, Crossplane's RBAC manager
grants every provider `*` on Secrets, ConfigMaps, Events and Leases cluster-wide, and creating
Deployments with any ServiceAccount in any Namespace reaches whatever those accounts can do. Only
platform operators may create `objects.kubernetes.crossplane.io` or edit the `in-cluster`
ProviderConfig; the live proof records the provider's `can-i --list` as the privileged control.

## Checks

```bash
make functions-up      # function containers for the Development runtime
make render-check      # xrd-check; Composition output == render() for 8 variants and the
                       # longest workspaceID; status phases; fails on a missing profile and on
                       # every one of 28 inputs render() rejects
make functions-down
```

`render-check` equality is with the reviewed `render()` that OK-174's live evidence was
recorded against, so the reconciler emits exactly the objects already proven live.

## Live proof (disposable clusters only)

`tests/live/reconcile_proof.py` refuses any context other than `admin@ok-175-proof` or the local
pre-flight `kind-ok175-preflight`, requires `TARGET_CONTEXT` to repeat it, and requires
`OK175_TARGET_UID_SHA256` to equal the sha256 of the selected cluster's `kube-system` UID.

```bash
export KUBECONFIG=<disposable cluster kubeconfig> TARGET_CONTEXT=admin@ok-175-proof
export OK175_TARGET_UID_SHA256=$(kubectl get ns kube-system -o jsonpath='{.metadata.uid}' | sha256sum | cut -d' ' -f1)
make live-install
OK175_REGISTRY_USERNAME=<pull-only user> OK175_REGISTRY_PASSWORD_FD=3 make live-run REQUIRE_CLEAN=1 3< <password file>
make live-uninstall
```

`live-run` first checks the installed Composition, XRD and ClusterRole equal the local files and
that each XR runs a CompositionRevision with the local pipeline. It then requires, each check with
a control that shows it can fail:

- the API server rejects a persistent lifecycle with ephemeral storage (XRD CEL) and admits the
  consistent document;
- without the profile EnvironmentConfig a workspace composes nothing and is not Ready;
- a persistent workspace: no pre-existing Namespace; reconciled objects equal `render()`; XR
  `Ready` with `lifecyclePhase: running`;
- a deleted `default-deny` is recreated (control: new UID) and a patched quota value is reverted;
- the checkout is the declared revision (control: the source's default branch is a newer commit);
- no token mounted; `can-i --list` equals an unbound identity's and passes OK-174's discovery-only
  allowlist; no RoleBindings (control: the provider identity fails both);
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
- CPU and memory limits are configured, not stress-tested (OK-176).
- `local-path` does not enforce PVC capacity (OK-176).
- Push denial is shown against a source that scopes credentials, standing in for a real
  provider's read-only token; it is not a test of any particular Git host's permissions.
- The live proof does not rerun OpenCode inference; OK-174 proved that for the same rendered
  objects, which `render-check` and the read-back tie to this reconciler.
- Drift correction covers deleted objects and changed values of rendered fields. A field added
  outside the rendered set (for example an extra egress rule on `default-deny`) is not removed:
  provider-kubernetes applies client-side and manages only the fields it wrote. Making that change
  needs authority no workspace holds.
- An existing Namespace with a workspace's name would be adopted, and deleted with the workspace.
  The live proof requires none to exist; nothing prevents it in general.
- `lifecycle.idleTimeoutMinutes`, `retentionMinutes`, `deletion: after-retention` and
  `evidence.exportBeforeCleanup` are accepted and validated, but not acted on.
- Kubernetes API unreachability is sampled at `kubernetes.default.svc`; node and control-plane
  addresses are not probed.
- Read-back normalization drops fields the API server defaults (inherited from OK-174's harness).
