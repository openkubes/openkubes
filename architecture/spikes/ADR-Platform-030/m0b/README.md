# M0b — GitOps prerequisite protocol

**Ticket:** OK-141

**Baseline:** `main` at `38d06bd898735ef5380e7e13803fd0a79f809ce7`

**Prepared:** 2026-08-09

```text
Protocol state:     BLOCKED
M0b:                NOT GRANTED
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure injection:  NO-GO
```

This directory turns the T2b feasibility result into an executable but fully
disabled prerequisite protocol. It installs no Argo resources, creates no
registration Secret, submits no Application, and does not modify T3.

## Read-only findings

The current `ok-shared` snapshot has four `linux/amd64` Nodes but only one
control-plane/etcd member. Argo CD, its namespace, and its CRDs are absent. The
Metrics API is absent and the only StorageClass is `local-path` with `Delete`
reclaim policy. Placement remains plausible, not authorized or production-ready.

Argo CD `v3.4.2` is the reviewed mechanism candidate. Its HA namespace-only
installation is the least-privilege control-plane shape for an instance that
manages external Clusters only. It still needs three CRDs and one Namespace as
separate reviewed prerequisites. All release and image identities are bound in
`argocd-installation-inventory.yaml`.

## Important new blockers

The exact Platform profile renders cluster-scoped resources and resources in
two namespaces:

```text
rendered candidate objects       120
target namespaces                ok-observability, kube-system
cluster-scoped kinds             CRD, ClusterRole, ClusterRoleBinding,
                                 MutatingWebhookConfiguration,
                                 ValidatingWebhookConfiguration
Argo-created Namespace           additional mechanism-owned prerequisite
```

Therefore `clusterResources: false` is incompatible with `P''`. The target
credential needs narrowly enumerated cluster-scoped access plus namespace-bound
access. No wildcard is accepted.

The render also exposed a provenance gap. The pinned `ok-observability` commit
does not contain `Chart.lock` or vendored dependency packages. Seven local
ignored chart archives made the offline render possible, but they are not part
of the Git source Argo would clone. Their content is observed and hashed, not an
authoritative projection of `P''`.

```text
Git commit pinned                  yes
top-level Chart metadata pinned    yes
transitive chart packages pinned   no
local candidate render             reproducible on this workstation
Argo source render provenance      BLOCKED
```

An immutable source amendment or equivalent artifact mechanism is required
before this candidate can be execution-authorized. A version in `Chart.yaml`
alone is not content identity.

Argo CD 3.4 is tested upstream with Kubernetes v1.32–v1.35. `ok-shared`
v1.34.1 is within that range; the disposable target declared as v1.36.2 is not.
Target compatibility remains a separate M0b blocker.

## Boundary

Argo remains the candidate owner of platform convergence. OpenKubes may submit,
observe, correlate, evaluate, and retain evidence; it must not duplicate Argo's
sync/self-heal loop.

The metadata-only registration candidate contains no credential. The RBAC
candidate contains no ServiceAccount or binding. Kubernetes RBAC cannot limit a
cluster-scoped `Namespace create` permission to one semantic object digest, so
the exact submission/admission path remains unresolved.

Any later blocker closure changes this protocol and requires a new digest,
review, and explicit authorization.

References:

- [Argo CD v3.4.2 release](https://github.com/argoproj/argo-cd/releases/tag/v3.4.2)
- [Argo CD installation profiles](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)
- [Argo CD high availability](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/)
