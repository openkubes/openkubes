# OK-141 delete D1 preflight v3

Status: **OFFLINE PREPARED / BLOCKED / NO-GO**

D1-v2 correctly bound all five GitOps identities but serialized the final two
records as AppProject then registration Secret. The authoritative delete
protocol requires the registration Secret before the AppProject. The v1
destructive runner stopped before cluster contact when it detected that
difference.

V3 preserves the v2 Application canonicalization and target-correlation
proof, but creates a new private binding identity whose records follow the
exact protocol order:

1. Dashboards Application
2. Alerting Application
3. Core Application
4. registration Secret
5. AppProject

No v2 digest is reinterpreted. This checkpoint remains read-only and grants no
delete authority.

```bash
cd architecture/spikes/ADR-Platform-030/delete-test-d1-preflight-v3
python3 prepare_delete_d1_preflight_v3.py verify --candidate delete-d1-preflight-candidate-v3.yaml
python3 test_prepare_delete_d1_preflight_v3.py -v
```
