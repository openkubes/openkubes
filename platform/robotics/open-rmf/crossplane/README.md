# OpenRMF Crossplane capability

This directory scaffolds the `OpenRMFClaim` API tracked by OK-60 and described
by ADR-Platform-019. It converts a namespaced Claim into one provider-helm
`Release` on a registered workload cluster.

## Status

The Composition pins the published `openrmf-deployment` chart version `1.0.0`:

```text
https://github.com/openkubes/rmf_deployment_template/releases/download/openrmf-deployment-v1.0.0/openrmf-deployment-1.0.0.tgz
```

**Do not apply the Claim to the live release yet.** Crossplane function
compatibility and the existing direct-Helm ownership handoff still require
validation and approval.

No command in this directory applies resources to `ok-mgmt` or `ok2-rmf`.

## Files

| File | Purpose |
|---|---|
| `xrd.yaml` | `OpenRMFInstance` XRD and namespaced `OpenRMFClaim` |
| `composition.yaml` | Simulation-profile provider-helm Release |
| `examples/ok2-rmf.yaml` | Non-secret example Claim for the registered cluster |
| `Makefile` | Local parsing, guard, and Helm chart checks only |

The Helm implementation remains in the sibling `rmf_deployment_template`
repository. This directory owns the platform API and the translation to Helm
values; it does not copy the chart.

## v1alpha1 contract

The first version exposes only the profile already smoke-tested on `ok2-rmf`:

- RMF simulation mode;
- RMF Web dashboard and API;
- profile-local Keycloak;
- RMF and Keycloak PostgreSQL databases;
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
  name: ok2-rmf
  namespace: openkubes-system
spec:
  clusterRef: ok2-rmf
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
| `keycloakAdminPassword` | `keycloak.KEYCLOAK_ADMIN_PASSWD` |
| `keycloakDatabasePassword` | `keycloak.KEYCLOAK_DB_PASSWD` |

The Secret creation and vault/reconciliation workflow is intentionally not
part of this scaffold. Do not commit a Secret manifest containing usable
values.

## Stateful lifecycle policy

The composed Release uses `deletionPolicy: Orphan`. Deleting a Claim therefore
must not automatically uninstall the external Helm release. This is a safety
default while the two PostgreSQL data sets lack a proven automated backup and
restore path.

The existing `ok2-rmf` Helm release is named `rmf`. The Composition preserves
that external name, but this does not prove safe adoption. Before the first
Claim is applied, rehearse provider-helm behavior away from the live namespace
and approve the direct-Helm-to-Crossplane ownership handoff.

## Local validation

From this directory:

```bash
make validate
make chart-check
make ready-check
```

- `validate` parses all scaffold YAML and checks required safety invariants.
- `chart-check` runs `helm lint` and `helm template` against the sibling chart
  using the Composition's non-secret simulation profile. It also rejects
  rendered cert-manager/monitoring CRs and ingress-class annotations on
  `IngressRoute`. It does not contact a cluster.
- `ready-check` verifies that the published chart URL is reachable and reports
  chart name `openrmf-deployment`, version `1.0.0`.

Override the chart location if the repositories are not siblings:

```bash
make chart-check RMF_CHART=/path/to/rmf_deployment_template/charts/rmf-deployment
```

## Before any apply

The chart is published and pinned, and the current credential Secret contract
has been populated outside Git. The remaining sequence is:

1. Pass `make validate`, `make chart-check`, and `make ready-check`.
2. Validate the Composition with the supported Crossplane function version.
3. Rehearse adoption of a release named `rmf` outside the live namespace.
4. Review the rendered provider-helm Release and Helm manifests for secret
   leakage and unintended changes.
5. Only then plan an explicit management-plane apply and ownership handoff.

## References

- [ADR-Platform-019](../../../../architecture/decisions/ADR-Platform-019-robotics-fleet-orchestration.md)
- [OpenWebUI Crossplane reference](../../../ai/open-webui/crossplane/)
- [Provider Helm Release schema](https://github.com/crossplane-contrib/provider-helm/blob/main/package/crds/helm.crossplane.io_releases.yaml)
