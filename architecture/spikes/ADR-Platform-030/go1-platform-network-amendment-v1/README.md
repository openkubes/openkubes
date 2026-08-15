# OK-141 Platform target-network amendment v1

The live Happy Run proved that the historical Platform profile rendered five
monitoring Services into `kube-system`. The deliberately namespace-scoped Argo
registration cannot safely cache those resources without broader read access.

This additive amendment disables exactly the kube-prometheus-stack components
that create those cross-namespace Services for the Talos/Cilium target:
CoreDNS, controller-manager, etcd, kube-proxy and scheduler monitoring. The
five capability-contract guarantees remain unchanged; the disabled scrapes are
not part of that contract.

```text
base P              sha256:b0f25c63…17bd47bf
amended P           sha256:02206b92…2266472
base R              sha256:166504ae…448aa0f
amended R           sha256:89248df8…2a0aaa4
amended Fixture     sha256:3aa621cd…274b9ae6
rendered objects    120 → 105
removed objects     exactly 15
rendered namespaces ok-observability only
authorization       NO-GO
```

The old profile and Phase-R v5 fixture remain reproducible historical
evidence. This checkpoint alone neither mutates the live Applications nor
authorizes destructive cleanup or broader RBAC.

## Core synchronization boundary discovered during the Happy Run

The amended Core Application reached the target and rendered the bound Git
revision, but its two explicitly authorized sync operations failed on the same
five cluster-scoped monitoring roles. All five roles were then created exactly
from the immutable render and verified semantically. The second and final sync
still returned the same privilege-escalation result.

The follow-up diagnostics narrow the failure without introducing another
write:

```text
five exact ClusterRoles present             yes
named bind/escalate SSAR                     allowed
global ClusterRole list/watch SSAR           allowed
named identical PUT with dryRun=All          accepted; RV unchanged
kubectl apply --dry-run=server               accepted; RV unchanged
sync-error subject == registration subject   yes (digest correlation)
third Core sync                              NOT AUTHORIZED
```

This disproves three candidate causes: missing live prerequisites, insufficient
current target RBAC, and a registration-subject mismatch. The remaining fault
boundary is the Argo application-controller runtime/cache state used by the
failed operation. Kubernetes v1.36.2 authorizes named `escalate` using the
request resource name, while Argo CD v3.4.2 builds its monitored-resource set
through list/watch plus `SelfSubjectAccessReview` when
`resource.respectRBAC=strict` is enabled.

The smallest next experiment is a graceful restart of the single DEV Argo
application-controller followed by bounded Application observation. It is not
covered by the final-sync grant: because automated self-heal is enabled, a
restart may implicitly initiate another reconciliation. The experiment must
therefore remain blocked until a grant explicitly supersedes the no-further-
retry boundary.

Primary implementation references:

- Kubernetes v1.36.2 named escalation authorization:
  <https://github.com/kubernetes/kubernetes/blob/v1.36.2/pkg/registry/rbac/escalation_check.go>
- Kubernetes v1.36.2 ClusterRole escalation gate:
  <https://github.com/kubernetes/kubernetes/blob/v1.36.2/pkg/registry/rbac/clusterrole/policybased/storage.go>
- Argo CD v3.4.2 strict RBAC cache behavior:
  <https://github.com/argoproj/argo-cd/blob/v3.4.2/gitops-engine/pkg/cache/cluster.go>
- Argo CD v3.4.2 sync apply path:
  <https://github.com/argoproj/argo-cd/blob/v3.4.2/gitops-engine/pkg/sync/sync_context.go>
