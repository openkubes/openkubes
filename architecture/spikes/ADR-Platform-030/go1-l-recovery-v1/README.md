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

The first R0 grant was consumed by a fail-closed observation attempt. No
mutation occurred and no partial API results were retained. It exposed that
`ok-mgmt` does not serve the KubeVirt VM/VMI API and that v1 did not model this
as an observation result. The additive v2 candidate binds `API_NOT_SERVED` only
for those two exact, label-bounded `ok-mgmt` collections:

```text
R0 v1 candidate: sha256:1748e1ae7bec8726fd5de8ca30699fa3f9b8c4650e946ef9373d6a63e926ba48
Attempt closure: sha256:4bfacec6191c5c1a2d8ec32052454c8f319b74d9c4ef3ead4455f7cde493f8ab (private)
R0 v2 candidate: sha256:4cc18693b948844a0516492395e7943cd1f1925d66b35f25d35977c989bac71f
```

All other API errors still stop fail-closed. Candidate v2 requires a new grant;
the consumed v1 grant cannot be reused.

R0-v2 was successfully consumed and its redacted closure was published. It is
valid historical evidence, but it cannot be reused for destructive cleanup: a
runtime binding is valid for at most ten minutes. The additive R0-v3 candidate
therefore uses a new private output path and binds v2 as preserved history:

```text
R0 v2 candidate:          sha256:4cc18693b948844a0516492395e7943cd1f1925d66b35f25d35977c989bac71f
R0 v2 private evidence:   sha256:33c617b54d6de4e31fd15335487102a229150d9210a7cd4ee1fd0f302b8c10c3
R0 v2 redacted closure:   sha256:42e9da5225e02f551c12ea4a14a85eeef73de2b6462b4e9bd9b9855b367e439d
R0 v3 candidate:          sha256:cc16cd21ae73948b1db83d1fa3490d545fd1b0616ecf81776281b36aa21df435
R0 v3 private output:      /private/tmp/ok141-go1-l-recovery-snapshot-v3-evidence.json
```

R0-v3 carries no read or credential authority. Its output must be absent before
a separately granted run.

The cleanup mechanism is prepared offline but remains blocked. A deterministic
materializer converts only a successful, fresh R0-v2 snapshot into a private
ten-minute UID/resourceVersion binding. The bounded executor then exposes two
strictly separate stages:

```text
R1: ok-mgmt Namespace only
    exact GET
    UID + resourceVersion equality
    foreground DELETE with both preconditions
    STOP; no automatic observation or continuation

R3: ok-infra RoleBinding -> Role -> Namespace
    requires a separately proven R2 closure
    same exact GET and DELETE preconditions per object
    persist partial-state evidence before and after each attempt
    STOP on first error; no retry or rollback
```

The cleanup candidate carries no authority:

```text
Cleanup candidate: sha256:b49375ae04357a16835f57bf4f224fa7ab8038b17da9a3b1157e5953e9527478
R1:                NOT GRANTED
R3:                NOT GRANTED
```

The additive cleanup candidate for R0-v3 uses a v2 executor and materializer.
Besides the historical v1 checks, they require the exact R0-v3 observation
candidate identity and binding version. An R0-v1/v2 binding cannot be passed to
the additive candidate, even if its object inventory would otherwise match.
The v1 executor and candidate remain unchanged historical evidence.

```text
R0-v3 cleanup candidate: sha256:b47453ee2d318648b3fa6a6dffa5a2471cb40c97b41cca245488fcfca45b4f1c
R1:                      NOT GRANTED
R3:                      NOT GRANTED
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
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/observe_recovery_snapshot_v2.py \
  verify \
  --candidate architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/recovery-snapshot-candidate-v2.yaml
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_recovery_snapshot_v2.py -v
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/observe_recovery_snapshot_v3.py \
  verify \
  --candidate architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/recovery-snapshot-candidate-v3.yaml
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_recovery_snapshot_v3.py -v
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_materialize_recovery_binding_v1.py -v
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_materialize_recovery_binding_v2.py -v
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/bounded_recovery_cleanup_v1.py verify
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/test_bounded_recovery_cleanup_v1.py -v
python3 architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/bounded_recovery_cleanup_v2.py \
  verify \
  --candidate architecture/spikes/ADR-Platform-030/go1-l-recovery-v1/recovery-cleanup-candidate-v1-r0-v3.yaml
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
