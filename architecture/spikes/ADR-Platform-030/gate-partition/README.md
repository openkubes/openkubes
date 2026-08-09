# OK-141 GO-1 gate partition

This read-only checkpoint corrects a gate-ordering contradiction discovered in
the historical GO-1 v3 protocol. That protocol requires all blockers to be
closed before a GO decision, although some claims can only be observed after
the disposable cluster exists.

The partition separates three kinds of obligations:

1. **Pre-GO requirements** must be closed before a GO-1 decision.
2. **Runtime obligations** start as `PENDING-RUNTIME`, are evaluated in an
   exact G2-G5 phase, and fail closed if their evidence is absent or invalid.
3. **Deferred scenarios** are outside GO-1 and require separate protocols and
   authorizations.

Controller installation is also separated from target convergence:

- `M0a-I` may authorize only installation of the CAAPH control plane.
- `M0b-I` may authorize only installation of the Argo CD control plane.
- Neither installation gate authorizes GO-1, workload registration, package
  submission, or target convergence.

The existing GO-1 v3 and M0 artifacts remain immutable historical evidence.
This checkpoint does not rewrite them and does not grant any mutation.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/gate-partition/verify_gate_partition.py \
  --partition architecture/spikes/ADR-Platform-030/gate-partition/gate-partition-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/gate-partition/gate-partition-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/gate-partition/tests \
  -p 'test_*.py'
```

## Safety state

```text
Gate partition:     PROPOSED-READ-ONLY
M0a-I:              NOT GRANTED
M0b-I:              NOT GRANTED
M0a / M0b:          NOT GRANTED
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure Injection:  NO-GO
```
