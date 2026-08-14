# OK-141 PlatformReady observer v1

The observer first requires all three exact Argo CD Applications to be current,
`Synced`, `Healthy`, and applied from the immutable `ok-observability` commit.
It then executes the exact capability-test script bound by
`minimal-observability-v4`. `PlatformReady=True` is emitted only when both
layers pass in the same bounded run.

The capability test owns only its documented synthetic resources and cleanup.
It does not repair Argo or the Platform. Runtime passwords and the workload
kubeconfig are private `/private/tmp` inputs and are deleted on exit; raw test
output and secret values are never retained or published.

The fixture explicitly uses `alertAcceptance=firing-only`; real receiver
delivery remains outside this Happy Run. This candidate grants no live
authority.

Candidate digest:

```text
sha256:0cf9fb378652893de8dcb999cc1f8e2bbad0113c6e5db049fd902c44f63c4509
```
