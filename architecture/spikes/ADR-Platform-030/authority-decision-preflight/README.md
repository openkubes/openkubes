# OK-141 authority decision inputs

Status: **three inputs recorded; all gates remain NO-GO**

This additive record preserves three user-confirmed inputs without modifying
the historical nine-outcome authority package:

1. `github:arashkaffamanesh` is the principal for the seven named authority
   roles.
2. The constrained `DEV-SOLO` governance exception is accepted without any
   independent-human-review claim.
3. Argo on the bound `ok-shared` incarnation may manage external workload
   Clusters only. Local resources and Argo self-management remain forbidden.

These inputs do not accept either RBAC boundary, bind a test window, approve
the proposed GHCR evidence destination, implement automated observers, issue
credentials, or grant M0a-I, M0b-I, or GO-1.

```text
Authority input groups:     3 confirmed
Historical outcomes:        9/9 UNDECIDED
Evidence destination:       UNDECIDED
Execution window:           proposed 180 minutes / NOT BOUND
Automated observers:        NOT IMPLEMENTED
M0a/M0b RBAC decisions:     UNDECIDED
Installer credentials:      NOT AUTHORIZED
Infrastructure:             NO-GO
Failure Injection:          NO-GO
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/authority-decision-preflight/verify_authority_inputs.py \
  --inputs architecture/spikes/ADR-Platform-030/authority-decision-preflight/authority-inputs-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/authority-decision-preflight/authority-inputs-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/authority-decision-preflight/tests \
  -p 'test_*.py' -v
```
