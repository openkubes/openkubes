# M0b v2 — GitOps fixture and source binding refresh

**Ticket:** OK-141

**Baseline:** `main` at `67a4271ab9d539f77f27c2a239db81db0caefd76`

**Prepared:** 2026-08-09

```text
Protocol state:     BLOCKED
M0b:                NOT GRANTED
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure injection:  NO-GO
```

This additive directory refreshes the M0b binding after Phase-R-v4 and T3-v3,
and consumes the merged authoritative `ok-observability` source closure. It
does not modify the historical `m0b/` checkpoint, install Argo resources,
create registration credentials, submit an Application, or grant M0b/GO-1.

```text
FixtureDigest'''  sha256:a2ae3437…a7f936f6
R'''              sha256:636fe234…3128a16e
P'''              sha256:b0f25c63…17bd47bf
Source commit     b5f7be6a…a9798b6
Artifact lock     sha256:cdcc6f63…fa85bf5
```

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

## Source-provenance closure

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

Therefore `clusterResources: false` remains incompatible with `P'''`. The target
credential needs narrowly enumerated cluster-scoped access plus namespace-bound
access. No wildcard is accepted.

The historical M0b checkpoint exposed a provenance gap: its pinned source did
not contain the chart packages used locally. That single blocker is now closed
by `ok-observability @ b5f7be6`, which commits an artifact lock and exactly
three wrapper packages containing the full transitive graph.

```text
Git commit pinned                  yes
artifact lock pinned               yes
transitive wrapper packages        3/3 tracked at source commit
fresh Git-archive render            sha256:2adb637c…c5b7ecf
semantic inventory                 sha256:a14300e9…7a361cf
Argo source render provenance      CLOSED
```

The raw render and semantic inventory remain identical to the historical local
candidate. Desired Platform semantics did not change; source provenance became
authoritative. All other placement, compatibility, identity, credential, RBAC,
capability, evidence, and recovery blockers remain `BLOCKED`.

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

Any further blocker closure changes this protocol and requires a new digest,
review, and explicit authorization.

References:

- [Argo CD v3.4.2 release](https://github.com/argoproj/argo-cd/releases/tag/v3.4.2)
- [Argo CD installation profiles](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)
- [Argo CD high availability](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/)
