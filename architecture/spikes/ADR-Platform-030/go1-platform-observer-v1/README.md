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
sha256:abea5179e1ea7a310f68cdd8ae6d51949e48bf2f0d1e60b6736646d028348724
```
