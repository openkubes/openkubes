# OK-141 M0b v2 preflight

Status: **read-only complete; historical M0b-I candidate invalidated; mutation NO-GO**

This checkpoint refreshes the bound `ok-shared` incarnation and replaces the
future installation candidate from the historical HA profile with Argo CD
`v3.4.2` `namespace-install.yaml`. It performs no installation.

Two independent mismatches make the historical 65-object candidate unsuitable
for execution:

1. it selected the HA manifest despite the accepted DEV-Solo, no-HA boundary;
2. its prospective `kubectl apply` transport omitted `--namespace argocd`, while
   the upstream namespace-install objects intentionally omit
   `metadata.namespace`.

The corrected source consists of 54 objects and seven desired Pods. Source
semantics and namespace-resolved target semantics are deliberately separate:

```text
source objects:                  54
source semantic digest:          sha256:60da7edf...2914ed
target-projected digest:         sha256:9664b22a...65b0b
target namespace:                argocd

ok-shared UID:                   46b9ecf7-...-6efb
Kubernetes:                      v1.34.1 / linux/amd64
Nodes:                           4/4 Ready
Argo objects before install:     0

M0b-I:                           NOT GRANTED
Target registration/convergence: NOT GRANTED
GO-1:                            NOT GRANTED
Failure injection:               NOT GRANTED
```

The next security candidate binds the non-HA controller RBAC, exact namespace
projection, and exact-object submission boundary. It deliberately proposes a
direct administrator, two-phase, create-only DEV operation instead of claiming
short-lived least privilege. The long-lived `system:masters` credential,
partial-state behavior, namespace Secret access, missing workload resource
requests, and repeated remote materialization all require an explicit risk
decision before an installation grant can be prepared. The historical protocol
remains unchanged as evidence.

The exact non-authorizing decision text is retained in
`m0b-v2-risk-acceptance-candidate.yaml`.

The exact statement was accepted by `github:arashkaffamanesh` at
`2026-08-13T11:19:19Z` and is retained additively in
`m0b-v2-risk-acceptance-v1.yaml`. The acceptance permits preparation of an
installation candidate but grants no mutation.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-preflight-v2/verify_m0b_preflight_v2.py

python3 architecture/spikes/ADR-Platform-030/m0b-preflight-v2/verify_m0b_security_v2.py

python3 architecture/spikes/ADR-Platform-030/m0b-preflight-v2/verify_m0b_risk_candidate_v2.py

python3 architecture/spikes/ADR-Platform-030/m0b-preflight-v2/verify_m0b_risk_acceptance_v2.py

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0b-preflight-v2/tests \
  -p 'test_*.py' -v
```
