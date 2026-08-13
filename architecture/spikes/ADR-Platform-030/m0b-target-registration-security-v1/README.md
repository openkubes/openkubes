# OK-141 M0b runtime registration security v1

This offline checkpoint classifies the security boundary of the future bridge
from the installed Argo CD control plane on `ok-shared` to the disposable
workload Cluster. It performs no cluster contact and grants no authority.

The candidate does not introduce an OpenKubes lifecycle reconciler. Argo CD
remains the Platform convergence owner; OpenKubes only binds runtime identity,
submits a bounded registration transition, and evaluates evidence.

The remaining DEV risks concern:

- administrator creation of the eight-object target-access prerequisite;
- RBAC's inability to constrain create requests to exact object content;
- cluster-scoped CRD, webhook, and RBAC authority required by the profile;
- privileged Pod Security for `ok-observability`;
- a static, expiring TokenRequest credential without native Argo rotation;
- non-atomic cross-plane partial state without retry, rollback, or cleanup;
- unproven Argo CD v3.4.2 / Kubernetes v1.36.2 execution compatibility;
- secret exposure risk in the not-yet-implemented runtime materializer.

State:

```text
Security candidate:          READY FOR RISK DECISION / NO-GO
Risk acceptance:             NOT ACCEPTED
Target access:               NOT GRANTED
TokenRequest:                NOT GRANTED
Target registration:         NOT GRANTED
Application submission:      NOT GRANTED
GO-1:                        NOT GRANTED
Infrastructure mutation:     none
```

Run:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-target-registration-security-v1/verify_m0b_runtime_registration_security_v1.py
```
