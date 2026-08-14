# OK-141 GO-1 v6 preflight v1

This package turns the remaining pre-runtime observations of GO-1 v6 into one
bounded, fail-closed and read-only preflight. It does not contact a cluster
unless a separate, current, single-run grant is supplied to the runner.

The preflight checks two independent claims:

1. all thirteen GO-1 v6 create targets are absent on their authoritative
   planes; and
2. the already-installed CAAPH and Argo CD control planes still satisfy a
   small exact-name readiness boundary.

The offline checkpoint contains no grant. `verify` and `plan` are safe offline
operations. `run` additionally requires the exact three kubeconfig files, a
short-lived grant bound to their redacted identity, and the fixed evidence
path. No Secret, token, private-key or kubeconfig bytes are retained.

```bash
python3 bounded_go1_v6_preflight_v1.py verify
python3 bounded_go1_v6_preflight_v1.py plan
python3 -m unittest -v test_go1_v6_preflight_v1.py
```

Current state:

```text
GO-1 v6 protocol:  BLOCKED
Preflight:          OFFLINE-PROVEN / NOT-RUN
Credential use:    NOT GRANTED
Cluster contact:   none
Mutation:           NO-GO
GO1-L / GO-1:      NOT GRANTED
```
