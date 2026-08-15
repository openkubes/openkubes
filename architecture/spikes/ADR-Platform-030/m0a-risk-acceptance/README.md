# OK-141 M0a risk acceptance

Status: **two DEV-only risks accepted; no mutation authorized**

This additive record closes only:

1. the exact CAAPH/Kubernetes/CAPI/CAPK/cert-manager compatibility-risk decision;
2. the reviewed CAAPH controller-RBAC and bounded installer-credential-risk decision.

The acceptance does not issue a credential, grant `M0A-C1`, grant `M0a-I`, or
permit any target resource, rollback, GO-1, or failure injection. A fresh target
observation, separate digest-bound grants, and an exact execution window remain
mandatory.

```text
Risk decisions:       ACCEPTED / DEV ONLY
Credential issuance: NOT GRANTED
M0a-I:                NOT GRANTED
M0b-I:                NOT GRANTED
GO-1:                 NOT GRANTED
Infrastructure:       NO-GO
Failure Injection:    NO-GO
```
