# OK-141 delete D0 live-grant candidate v1

Status: **OFFLINE-PREPARED / EXPLICIT LIVE READ GRANT REQUIRED / NO-GO**

This checkpoint binds the already merged D0 reader to a stable grant contract.
It deliberately does not contain a grant ID or timestamps: those values must be
created just in time after explicit authorization and the window may not exceed
twenty minutes.

The later D0 run may perform exactly 36 sealed GETs across `ok-shared`,
`ok-mgmt`, `ok-infra` and the disposable workload. It may write only the two
private `0600` outputs already bound by D0. Secret values are discarded before
persistence.

The resulting private runtime binding expires after ten minutes and is valid
only for D1 through D3. It cannot be reused for D5 retained-storage cleanup.

Offline verification:

```bash
python3 architecture/spikes/ADR-Platform-030/delete-test-d0-grant-v1/verify_delete_d0_live_grant_candidate_v1.py \
  verify \
  --candidate architecture/spikes/ADR-Platform-030/delete-test-d0-grant-v1/delete-d0-live-grant-candidate-v1.yaml

python3 architecture/spikes/ADR-Platform-030/delete-test-d0-grant-v1/test_delete_d0_live_grant_candidate_v1.py -v
```

Neither command contacts a cluster. D0 execution, deletion, cleanup, retry,
outage and failure injection remain unauthorized.
