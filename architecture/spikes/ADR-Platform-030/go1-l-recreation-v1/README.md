# OK-141 GO1-L recreation preflight v1

This directory records the first offline checkpoint after the failed Phase-R v4
execution was cleaned to `PASS-R4-CLEAN-BASELINE`.

The clean baseline does not make the historical execution artifacts safe to
reuse. `go1-v5` and `go1-l-submitter-v1` still reference Phase-R v4, whose
projection omitted `KubevirtCluster.spec.infraClusterSecretRef`. The recreation
path must instead bind Phase-R v5 and preserve its external-provider authority.

The required pre-runtime order is:

```text
ok-infra: create 3 provider prerequisites
        ↓
ok-mgmt: create disposable Namespace only
        ↓
ok-mgmt: materialize exact provider-access Secret from local ok-infra kubeconfig
        ↓
ok-mgmt: create the remaining 7 CAPI/CAPK/Talos lifecycle objects
        ↓ current lifecycle evidence
ok-mgmt: create the exact HelmChartProxy
```

The Namespace and seven remaining objects are slices of the same reviewed
Phase-R v5 eight-document projection. Slicing changes submission ordering, not
the combined semantic identity. The dynamic Secret is deliberately outside the
fixture and projection because credential bytes may never enter Git, arguments,
environment variables, logs, or retained Evidence.

This checkpoint grants no credential use, Secret materialization, submission,
recreation, retry, rollback, GO1-L, GO-1, or failure injection.

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-recreation-v1/verify_recreation_preflight_v1.py
python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/go1-l-recreation-v1 \
  -p 'test_*.py' -v
```
