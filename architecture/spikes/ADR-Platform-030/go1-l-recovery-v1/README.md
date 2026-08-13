# OK-141 GO1-L recovery protocol v1

Status: **OFFLINE-PREPARED / BLOCKED / NO-GO**

The first GO1-L lifecycle run is preserved in a partial state because the v4
projection omitted the external CAPK provider authority. Phase-R v5 corrects
that contract and projection, but it does not authorize mutation of the old
objects.

This checkpoint selects one recovery strategy:

```text
fresh read-only UID inventory
        ↓
explicit destructive grant
        ↓
UID-preconditioned deletion of the disposable ok-mgmt namespace
        ↓
bounded observation until finalizers complete
        ↓
UID-preconditioned deletion of the three ok-infra prerequisites
        ↓
prove exact absence
        ↓
STOP
        ↓
future, separately authorized recreation from Phase-R v5
```

Bound offline identities:

```text
Recovery protocol:  sha256:0be2957f7c417e9c7c25f2595b5168a95f11e72c76508d83f774719045df8bd9
R0 candidate:       sha256:1748e1ae7bec8726fd5de8ca30699fa3f9b8c4650e946ef9373d6a63e926ba48
Phase-R v5 fixture: sha256:7536456a762880a78a37dcba76a5f3f0628140bd37b55d5fd62273c64e4cc3eb
```

Patch-in-place is rejected because it would mix resources created from `R'''`
with the corrected `R''''`. Force deletion, finalizer removal, automatic retry,
rollback, Secret materialization, and recreation are also excluded.

The public protocol contains no live object UIDs. A fresh private runtime
binding must carry the exact UIDs and resource versions, and its digest must be
bound by a later grant. The binding template is deliberately non-executable and
contains placeholders only.

The R0 observation also requires an explicit credential-use grant for exactly
the two bound DEV administrator kubeconfigs. It may use those files for the
reviewed reads, but may not copy, modify, print, or retain their contents.

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/verify_go1_l_recovery_v1.py
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_go1_l_recovery_v1.py -v
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/observe_recovery_snapshot_v1.py \
  verify \
  --candidate architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/recovery-snapshot-candidate-v1.yaml
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_recovery_snapshot_v1.py -v
```

```text
Recovery protocol:      offline prepared
Fresh runtime binding:  missing
Cleanup grant:          NOT GRANTED
Cleanup:                NOT GRANTED
Recreation:             NOT GRANTED
Secret materialize:     NOT GRANTED
GO1-L / GO-1:           NOT GRANTED
Failure injection:      NOT GRANTED
```
