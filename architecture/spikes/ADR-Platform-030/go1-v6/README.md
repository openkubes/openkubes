# OK-141 GO-1 protocol v6

Status: **structurally complete; BLOCKED; GO-1 NOT GRANTED**

GO-1 v6 is the first protocol root that combines the corrected Phase-R-v5
authority projection with the current HCP, bounded submitter v3, and the
secret-safe provider-access materializer.

```text
1. ok-infra  create 3 provider prerequisites
2. ok-mgmt   create management Namespace
3. ok-mgmt   materialize exact provider-access Secret
4. ok-mgmt   create 7 CAPI/CAPK/Talos lifecycle objects
5. ok-mgmt   create current Phase-R-v5 HCP
        ↓
   observe lifecycle + NetworkReady
        ↓ explicit runtime pause
   target access + Argo registration + exact P
        ↓
   bounded Ready evaluation + redacted evidence
```

The later runtime-pause, Platform, expected-evidence, STOP, and exclusion
semantics are inherited from v5 by six individual canonical digests plus one
aggregate digest. They are not copied or silently reinterpreted. They are
evaluated under the v6 fixture identity.

The historical v5 protocol remains reproducible but is forbidden for future
execution because it is bound to Phase-R v4. Every v6 phase and gate remains
disabled. Merge and protocol digest do not grant credentials, submission,
Secret creation, target registration, Platform convergence, retry, rollback,
cleanup, GO1-L, GO-1, or failure injection.

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-v6/verify_go1_protocol_v6.py
python3 architecture/spikes/ADR-Platform-030/go1-v6/test_go1_protocol_v6.py -v
```

Remaining pre-runtime work:

- refresh the exact clean-baseline/absence preflight;
- bind current source and destination credential receipts;
- bind five independent single-run operation grants to one test window;
- bind observers, authorities, raw evidence destinations, and recovery checks;
- make one explicit GO1-L decision for the final protocol digest.

```text
Protocol structure:     complete offline
Phase-R-v5 mechanisms:  bound
Pre-runtime blockers:   open
GO1-L:                  NOT GRANTED
GO-1:                   NOT GRANTED
Infrastructure:         NO-GO
Failure Injection:      NO-GO
```
