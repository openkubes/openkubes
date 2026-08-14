# OK-141 bounded Happy Run v1

This package composes the previously reviewed components into exactly one
`create + converge + observe` run. One outer digest-bound grant is consumed
before the first cluster contact; the orchestrator generates narrower internal
single-run grants for each existing component.

The run is create-only and fail-closed. Any deviation stops and preserves the
partial state for evidence. Retry, rollback, broad cleanup, outage, and failure
injection are excluded. The only cleanup included is the exact synthetic
resource cleanup owned by the immutable Observability capability test.

Success requires current CAPI lifecycle evidence, functional NetworkReady,
current immutable target identity, exact Argo convergence, and a passing
capability contract. Process termination alone is not success.

This checkpoint grants no live authority. Its candidate digest must be merged
and then named by one explicit future Happy Run grant.

Candidate digest:

```text
sha256:2792206fca811633ec7f30cc5fd04814802fe4cf20645bb888cb9e13aca784e6
```
