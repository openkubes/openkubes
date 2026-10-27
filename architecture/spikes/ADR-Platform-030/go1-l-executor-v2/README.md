# OK-141 GO1-L bounded executor v2

This additive amendment closes the credential-identity time-of-check/time-of-use
gap left by executor v1. It preserves v1 payloads, operation order, exact
kubectl transport, create-only behavior, and all authorization boundaries.

Immediately before each operation, v2 requires the credential receipt, current
credential file, PF-V2 evidence, and merged credential-identity closure to agree
on the target plane, fixed path, API server and CA-derived identity digest. The
provider-access operation checks both its ok-infra source and ok-mgmt destination.

The identity claim remains intentionally narrow: it proves the intended API
endpoint and CA, not an independent human identity or short-lived credential.
The accepted DEV-ADMIN-CREATE boundary remains unchanged.

This checkpoint is offline only. It contains no runtime receipts or grants and
authorizes no credential use, cluster contact, or mutation.

Candidate digest:

```text
sha256:0f9693df9b89bc96278f69134517fb2777a60373a61fadc40612cdaacdc2115c
```

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-executor-v2/bounded_go1_l_executor_v2.py verify
python3 -m unittest architecture/spikes/ADR-Platform-030/go1-l-executor-v2/test_go1_l_executor_v2.py
```

```text
Point-of-use target identity:  required for every operation
Principal identity claim:      not made
Credential use:                NOT GRANTED
GO1-L:                         NOT GRANTED
GO-1:                          NOT GRANTED
Infrastructure:                NO-GO
Failure Injection:             NO-GO
```
