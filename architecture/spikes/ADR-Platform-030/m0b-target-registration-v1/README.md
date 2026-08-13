# OK-141 M0b runtime target registration v1

This read-only checkpoint specifies the bridge between the installed Argo CD
control plane on `ok-shared` and the future disposable workload Cluster. It
does not register a cluster, request a token, create target RBAC, submit an
Application, or grant GO-1.

## Finding

The target cannot be securely pre-registered: the CAPI Cluster UID, workload
`kube-system` UID, API CA fingerprint, endpoint, and credential expiration do
not exist until the later lifecycle and enablement phases have converged.
Runtime registration therefore belongs after current `NetworkReady=True` and
before Platform submission.

The bounded DEV candidate uses a project-scoped Argo cluster Secret and a
custom AppProject with `permitOnlyProjectScopedClusters: true`. The native
`default` project must remain unused. Target access is limited to the exact
observed platform inventory in `ok-observability` and `kube-system`; no RBAC
wildcards are present.

The credential candidate is a time-limited TokenRequest bearer token with a
maximum lifetime of three hours for a GO-1 boundary of two hours. Argo CD does
not natively rotate that static value. It is therefore not a production
credential model, and no credential bytes may enter Git or retained evidence.

## State

```text
M0b-I / Argo installation: complete
M0b-R / target registration: BLOCKED
Target credentials:          NOT GRANTED
Platform submission:         NOT GRANTED
GO-1:                        NOT GRANTED
Infrastructure mutation:     none in this checkpoint
```

Run the offline verifier:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-target-registration-v1/verify_m0b_target_registration_v1.py
```
