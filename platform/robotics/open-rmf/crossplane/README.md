# OpenRMF Crossplane capability

This directory scaffolds the `OpenRMFClaim` API tracked by OK-60 and described
by ADR-Platform-019. It converts a namespaced Claim into one provider-helm
`Release` on a registered workload cluster.

## Status

The Composition pins the published `openrmf-deployment` chart version `1.0.1`:

```text
https://github.com/openkubes/rmf_deployment_template/releases/download/openrmf-deployment-v1.0.1/openrmf-deployment-1.0.1.tgz
```

It pins `chart.name` and `chart.version` as well as `chart.url`. Do not remove the
apparently redundant fields: provider-helm late-initializes name and version on
the managed Release, so changing only the URL can leave an earlier version in
`spec.forProvider.chart.version`.

Both original holds on applying a Claim are resolved. The repo pins
`function-patch-and-transform` `v0.9.0` (`tests/functions.yaml`) and renders
against core Crossplane `v2.3.3` (`--crossplane-version`); that this matches the
rebuilt `ok-mgmt` was verified on-cluster and recorded on OK-99, not in this
repo. `ok-robotics` is the only deployment target, and it is a clean install
with no pre-existing Helm release to take ownership of.

The local checks (`validate`, `chart-check`, `ready-check`, `render`,
`render-check`) still apply nothing anywhere. The `bind`, `deploy` and
`undeploy` targets **do** mutate `ok-mgmt`; each one requires
`APPROVE_MGMT=yes`, an attended terminal, a kubeconfig that really identifies
`ok-mgmt`, and a typed confirmation after a server-side dry run.

## Files

| File | Purpose |
|---|---|
| `xrd.yaml` | `OpenRMFInstance` XRD and namespaced `OpenRMFClaim` |
| `composition.yaml` | Simulation-profile provider-helm Release |
| `examples/ok-robotics.yaml` | Non-secret example Claim for the intended first managed-deployment target (OK-88/OK-99) |
| `rbac/claim-editor-role.yaml` | Claim-only namespaced Role; no Secret or Crossplane-internal access |
| `rbac/claim-editor-binding.yaml` | Binds that Role to the platform OIDC group `oidc:openrmf-claim-editors` |
| `tests/xr-ok-robotics.yaml` | Representative XR fixture for local rendering against `ok-robotics` |
| `tests/functions.yaml` | Local-render function package matching `ok-mgmt` |
| `Makefile` | Local checks, plus the approval-gated `ok-mgmt` bind/deploy lifecycle |

The Helm implementation remains in the sibling `rmf_deployment_template`
repository. This directory owns the platform API and the translation to Helm
values; it does not copy the chart.

## v1alpha1 contract

The first version exposes only the simulation profile:

- RMF simulation mode;
- RMF Web dashboard and API;
- authentication against the central Keycloak on `ok-shared` — the chart's own
  bundled Keycloak is switched off, see below;
- the RMF Web PostgreSQL database;
- Traefik routing with `ok-ingress` profile values;
- Traefik's default TLS certificate;
- monitoring disabled.

Real/core RMF, trusted PKI, observability, production DDS networking, backups,
and the remaining ADR-Platform-019 gates are deliberately outside this first
Composition.

## Claim example

```yaml
apiVersion: platform.openkubes.ai/v1alpha1
kind: OpenRMFClaim
metadata:
  name: ok-robotics
  namespace: openkubes-system
spec:
  clusterRef: ok-robotics
  namespace: rmf
  mode: simulation
  hostname: rmf.openkubes.local
  credentialsSecretRef:
    name: rmf-credentials
    namespace: crossplane-system
```

The Claim never contains passwords. `credentialsSecretRef` identifies a Secret
that provider-helm can read. The Secret contract currently requires these
keys:

| Key | Helm value |
|---|---|
| `rmfWebDatabasePassword` | `rmf_web.API_SERVER_DB_PASSWD` |
| `rmfWebAdminPassword` | `rmf_web.ADMIN_PASSWD` |

The Secret creation and vault/reconciliation workflow is intentionally not
part of this scaffold. Do not commit a Secret manifest containing usable
values.

Two keys were removed when identity moved to `ok-shared`:
`keycloakAdminPassword` and `keycloakDatabasePassword` configured the chart's own
Keycloak and its database, neither of which is deployed any more. They may still
be present in an existing `rmf-credentials` Secret; nothing reads them, and
`make validate` rejects any attempt to reintroduce them into the contract.

## Identity

RMF authenticates against the one central Keycloak on `ok-shared`, realm
`rmf-web`. There is no profile-local identity provider — the Composition sets
`keycloak.enabled: false`, which stops the chart rendering its own Keycloak,
database, ingress and realm-setup Job.

The realm, its `dashboard` and `smart_cart` clients, the `dashboard` audience
mapper and the `admin` user are provisioned idempotently by `make rmf-realm` in
`platform/identity/keycloak`. That command also prints the realm's signing public
key, which the Composition pins as `keycloak.jwtPublicKey` because
`rmf-web-rmf-server` validates tokens from a mounted file rather than fetching
JWKS. **If that realm is rebuilt the key changes and logins begin failing as 401s
with nothing logged to explain it** — rerun the command, update the value, and
restart `Deployment/rmf-web-rmf-server`. The projected ConfigMap updates in the
running pod, but the API reads the key once at process startup.

`make validate` asserts all of this: Keycloak disabled, the expected issuer, a
well-formed PEM, and no Keycloak credential in the Secret contract.

## Claim-only RBAC

`rbac/claim-editor-role.yaml` grants create/read/update/delete/watch access
only to namespaced `openrmfclaims` in `openkubes-system`. It does not grant
access to Secrets, XRDs, Compositions, provider-helm Releases,
ProviderConfigs, Functions, or other Crossplane internals.

`rbac/claim-editor-binding.yaml` binds that Role to the group
`oidc:openrmf-claim-editors`. The `oidc:` prefix is not decoration: `ok-mgmt`'s
`AuthenticationConfiguration` sets `claimMappings.groups.prefix` to `oidc:`, so
the Keycloak group `openrmf-claim-editors` (realm `openkubes`, client `ok-mgmt`)
reaches the API server under that name. **A subject without the prefix binds
nobody and Kubernetes reports no error** — so `make validate` pins the manifest
exactly: one subject, that group, `roleRef` to this namespaced Role in
`openkubes-system`. Appending a second subject, swapping in another `oidc:`
group, escalating `roleRef` to a `ClusterRole`, or dropping the prefix each fail
the check. Widening the binding is therefore a reviewed edit to the invariant,
not something a stray list item can do quietly.

See the [claim-editor binding plan](docs/claim-editor-binding-plan.md) for the
resolved dependency chain and what each link was blocked on.

### Applying and proving it

```bash
make bind APPROVE_MGMT=yes                        # Role + RoleBinding, then authz-check
make authz-check CLUSTER=ok-robotics              # re-runnable proof, mutates nothing
```

`authz-check` impersonates the claim-editor subject and asserts both halves: it
**may** create `openrmfclaims` in `openkubes-system`, and it **may not** read
Secrets in any namespace or exercise any cluster-wide verb. Impersonation takes
the same `SubjectAccessReview` path a real token does, so it proves
authorization without holding anyone's credentials — it does not prove
authentication, which is evidenced separately by a real `kubectl oidc-login` on
OK-99. To reproduce a specific login's claim set, override the subject:

```bash
make authz-check CLAIM_EDITOR_USER=oidc:alice \
  CLAIM_EDITOR_GROUPS="oidc:openrmf-claim-editors oidc:platform-admins"
```

## Provider-helm chart-upgrade reconciliation

provider-helm v0.19.0 decides that a Release is current by comparing the desired
`chart.name` and `chart.version` with Helm's stored chart metadata before it
compares values. During the 1.0.0 to 1.0.1 central-identity rollout, the
Composition changed only `chart.url`; the composed Release retained its
late-initialized `chart.version: 1.0.0`. Every Helm upgrade successfully stored
1.0.1 with state `deployed`, but the next observation compared it with the stale
1.0.0 field, set `Ready=False` / `Unavailable`, and requested another upgrade.
Pinning all three chart identity fields makes the desired and observed versions
converge.

`rollbackLimit` did not drive that loop. In v0.19.0 rollback is considered only
for `failed`, `pending-install`, or `pending-upgrade` states; the looping release
was `deployed` after every successful upgrade. `wait: true` also remains useful:
it makes each Helm operation wait for Kubernetes resources, whereas the
Composition readiness check only propagates the provider's observed deployed
state.

### Recovering a looping Release

Pause the composite **before** pausing its Release. The Composition owns the
Release annotation map, so pausing only the Release does not stick: the next
composite reconcile removes that annotation.

1. Annotate the `OpenRMFInstance` with `crossplane.io/paused=true`.
2. Then annotate `Release/openrmf-ok-robotics` with the same value and confirm
   the Helm revision stops increasing.
3. Run the approval-gated `make setup APPROVE_MGMT=yes` from this directory to
   install the corrected Composition.
4. Remove the pause from the composite and wait until it writes the pinned chart
   name/version/URL to the Release.
5. Remove the pause from the Release. Confirm it performs at most the one needed
   upgrade, the revision remains stable afterward, and both Release and Claim
   report `Ready=True`.
6. When the chart change updates `keycloak.jwtPublicKey` or the issuer, restart
   `Deployment/rmf-web-rmf-server` on the workload cluster. The API loads that
   mounted configuration only at process startup. Complete a browser login and
   require the authenticated `/rmf/api/v1/user` request to return HTTP 200; a
   successful Keycloak token exchange alone is insufficient.

Do not delete or recreate the Release, Claim, composite, namespace, or PVCs as a
recovery shortcut. `deletionPolicy: Orphan` is unchanged.

## Stateful lifecycle policy

The composed Release uses `deletionPolicy: Orphan`. Deleting a Claim therefore
must not automatically uninstall the external Helm release. This is a safety
default while the two PostgreSQL data sets lack a proven automated backup and
restore path.

`make undeploy` deletes only the Claim, and says plainly that the Release and
the target namespace survive it. Rolling a deployment back is consequently two
deliberate acts, not one — the second destroys data and is not automated here:

```bash
make undeploy CLUSTER=ok-robotics APPROVE_MGMT=yes    # removes the Claim only
kubectl delete release.helm.crossplane.io openrmf-ok-robotics   # separate, destructive
```

The Composition sets the external release name to `rmf`. There is no live
release anywhere to adopt, so no direct-Helm-to-Crossplane ownership handoff has
to be rehearsed before a Claim is submitted.

## Local validation

From this directory:

```bash
make validate
make chart-check
make ready-check
make render-check
```

- `validate` parses all scaffold YAML and checks required safety invariants.
- `chart-check` runs `helm lint` and `helm template` against the sibling chart
  using the Composition's non-secret simulation profile. It also rejects
  rendered cert-manager/monitoring CRs and ingress-class annotations on
  `IngressRoute`. It does not contact a cluster.
- `ready-check` verifies that the published chart URL is reachable and reports
  chart name `openrmf-deployment`, version `1.0.1`.
- `render-check` uses Crossplane CLI `v2.3.3` and Docker to execute
  `function-patch-and-transform:v0.9.0` against the representative XR. It then
  verifies that exactly one Helm Release is produced with the expected pinned
  chart name/version/URL, ProviderConfig, external release name, orphan policy,
  and two Secret references.

`CLUSTER` selects the XR fixture (`tests/xr-$(CLUSTER).yaml`) and the expected
`ProviderConfig` and release name. It defaults to `ok-robotics`, the only
registered target, so the explicit form below is equivalent:

```bash
make render-check CLUSTER=ok-robotics
```

Adding a second target cluster means adding `tests/xr-<cluster>.yaml` and
`examples/<cluster>.yaml` alongside it.

Crossplane CLI rendering uses Docker by default. If Docker is unavailable,
`render-prerequisites` fails explicitly and no render result should be
claimed. See the official
[Crossplane composition render reference](https://docs.crossplane.io/cli/latest/command-reference/#crossplane-composition-render).

Override the chart location if the repositories are not siblings:

```bash
make chart-check RMF_CHART=/path/to/rmf_deployment_template/charts/rmf-deployment
```

## Before any apply

The chart is published and pinned, and the credential Secret contract has been
populated outside Git. Run, in order:

1. `make validate`, `make chart-check`, `make ready-check`.
2. `make render-check CLUSTER=ok-robotics` with the function version `ok-mgmt`
   runs — review the rendered Release for secret leakage and unintended changes.
3. `make bind CLUSTER=ok-robotics APPROVE_MGMT=yes` — binds the claim-only Role
   and proves both authorization halves.
4. `make deploy CLUSTER=ok-robotics APPROVE_MGMT=yes`.

Step 4 is the first reconcile of any XR against this Composition, so
provider-side failures that rendering cannot catch — the chart pull from the
workload cluster, a credential key mismatch — surface there first.

There is no adoption rehearsal step: this is a clean install with no live
release to take ownership of.

## References

- [ADR-Platform-019](../../../../architecture/decisions/ADR-Platform-019-robotics-fleet-orchestration.md)
- [OpenWebUI Crossplane reference](../../../ai/open-webui/crossplane/)
- [Provider Helm Release schema](https://github.com/crossplane-contrib/provider-helm/blob/main/package/crds/helm.crossplane.io_releases.yaml)
