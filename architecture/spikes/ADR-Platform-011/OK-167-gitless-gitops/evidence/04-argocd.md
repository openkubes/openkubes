# 04 — Argo CD

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: Phase 5 (install, CA trust, repository Secret, AppProject)
- Date (UTC): 2026-10-29T12:09Z
- Worktree commit: `a8e904c`
- Environment: Argo CD v3.5.6, chart `argo-cd-10.11.6` — see `00-preflight.md`

## Steps

```bash
make argocd-install                      # asserts every image is digest-pinned, then installs
make argocd-repo REPO=podinfo-manifests  # Secret built in memory from .local/, piped to kubectl
make argocd-project                      # AppProject ok167
```

## Observed

### Install

All pods Running; `argocd-applicationset-controller` has no pod because it is scaled to zero.

| Component | State |
|---|---|
| `argocd-application-controller-0` | Running |
| `argocd-repo-server` | Running |
| `argocd-server` | Running |
| `argocd-redis` | Running |
| `dex`, `notifications` | not rendered |

Running image, read back from the cluster:

```text
quay.io/argoproj/argocd:v3.5.6@sha256:8e5cc5bb008df8a09dba439462e58c94c55b7735888d3ebde0c25fc05e4e5335
```

`make argocd-install` fails if any rendered image lacks a digest, so this is enforced rather
than inspected once.

### CA trust

`argocd-tls-certs-cm` holds the key `zot.zot.svc.cluster.local` (hostname without port) and its
value begins `-----BEGIN CERTIFICATE-----`. The CA was injected with
`--set-file 'configs.tls.certificates.zot\.zot\.svc\.cluster\.local=.local/pki/ca.crt'` —
the dots escaped, because Helm otherwise reads them as path separators — and never written into
the tracked values file.

### Reconciliation settings in effect

```json
{ "timeout.reconciliation": "120s", "timeout.reconciliation.jitter": "60s" }
```

Chart defaults, set explicitly so every latency figure states what it was measured under.

### Repository Secret — no secret value in Git

```json
{ "name": "ok167-zot-podinfo-manifests",
  "label": "repository",
  "keys": ["password","type","url","username"],
  "type_value": "oci",
  "url_value": "oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops/podinfo-manifests",
  "username_value": "gitops-puller",
  "password_present": true }
```

The identity is `gitops-puller`, which cannot write (proved by V5). The publisher credential is
never given to Argo CD, as ADR-028 §4.5 requires. The Secret is assembled with `jq` and piped
into `kubectl`; `argocd/repository-secret.template.yaml` carries only placeholders.
**M2 is met.**

### AppProject — deny by default

```json
{ "sourceRepos": ["oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops/*"],
  "destinations": [{"namespace": "ok167-*", "server": "https://kubernetes.default.svc"}],
  "clusterResourceWhitelist": [],
  "namespaceResourceWhitelist": ["apps/Deployment","/Service","/ServiceAccount","autoscaling/HorizontalPodAutoscaler"] }
```

`ServiceAccount` and `HorizontalPodAutoscaler` are present only because the podinfo Helm chart
(test S-D) renders them; both are namespace-scoped. No cluster-scoped resource may be created.

### No TLS errors

`argocd-repo-server` logs contain zero `x509`, `certificate problem` or `TLS handshake` errors.
The single TLS line is `Generating self-signed TLS certificate for this session`, which concerns
the repo-server's own gRPC listener, not zot.

## Finding — `applicationSet.enabled` does not exist in chart 10.11.6

The brief asks for Dex, Notifications and the ApplicationSet controller to be disabled "if the
chart allows it without side effects". Two of the three do:

```gotemplate
templates/dex/deployment.yaml                    {{- if .Values.dex.enabled }}
templates/argocd-notifications/deployment.yaml   {{- if .Values.notifications.enabled }}
templates/argocd-applicationset/deployment.yaml  (no gate at all)
```

`applicationSet` has **no `enabled` key** in this chart version, and the Deployment is rendered
unconditionally. A values file containing `applicationSet.enabled: false` would look correct,
change nothing, and mislead the next reader — which is exactly the kind of declaration nobody
measures. The values file sets `applicationSet.replicas: 0` instead and says why. The Deployment
and its RBAC still exist; only the pod does not.

## Verdict

**PASS.** Argo CD v3.5.6 runs digest-pinned, trusts the zot CA, authenticates with a read-only
identity whose credential never touches Git, and the AppProject restricts sources, destinations
and resource kinds.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Argo CD runs the pinned v3.5.6 image and trusts the zot CA through `argocd-tls-certs-cm` | That `argocd-tls-certs-cm` is what makes OCI trust work — Q1.d removes it to find out |
| The repository Secret holds a read-only identity and no value of it exists in Git | That the Secret is protected at rest beyond Kubernetes defaults — Q1.f checks who can read it |
| The AppProject forbids cluster-scoped resources and foreign repositories | That the restriction is enforced in practice — no Application has yet tried to violate it |
| The repo-server shows no TLS errors | That it has pulled anything — Phase 6 shows the pull |
