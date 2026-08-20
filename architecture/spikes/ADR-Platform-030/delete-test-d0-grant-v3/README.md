# OK-141 delete D0 live-grant candidate v3

Status: **OFFLINE-PREPARED / EXPLICIT LIVE READ GRANT REQUIRED / NO-GO**

This checkpoint binds the merged D0-v3 reader to a fresh single-use grant
contract. It deliberately contains neither a grant ID nor timestamps. Those
values must be bound just in time after explicit authorization, and the window
may not exceed twenty minutes.

The later D0-v3 run may perform exactly 36 sealed GETs across `ok-shared`,
`ok-mgmt`, `ok-infra` and the disposable workload. It retains the v2
DataVolume derivation and uses exact provider-PV/Longhorn equality proven by
the preceding diagnostic. It may write only the two new private `0600` v3
outputs. Secret values are discarded before persistence.

The resulting private runtime binding expires after ten minutes and is valid
only for D1 through D3. It cannot be reused for D5 retained-storage cleanup.

Offline verification:

```bash
cd architecture/spikes/ADR-Platform-030/delete-test-d0-grant-v3
python3 verify_delete_d0_live_grant_candidate_v3.py verify \
  --candidate delete-d0-live-grant-candidate-v3.yaml
python3 test_delete_d0_live_grant_candidate_v3.py -v
```

Neither command contacts a cluster. D0-v3 execution, deletion, cleanup,
retry, outage and failure injection remain unauthorized.
