# OK-141 active public evidence observer

Status: **deployment candidate; first observation not yet performed**

This checkpoint activates the reviewed credential-free observer and binds it to
the exact public P1 evidence manifest.

```text
Observed identity:    OCI manifest digest only
Registry access:      anonymous HEAD
Workflow permission:  contents: read
Schedule target:      03:17 UTC daily
Mutation capability:  none
```

`retainedUntil` is deliberately later than the accepted minimum. The retention
policy permits extension without a new gate. At OK-141 closure the index must
still be checked and extended if closure plus 90 full days would exceed the
bound timestamp.

The source revision identifies the immutable reviewed commit that first
contains this exact active workflow and runtime evaluator, not a mutable branch
name: `c177b56a9a925a64f78a56350822e6747a5f169b`. The active workflow digest is:

```text
sha256:6fed6d68998ce1d79e4465cf8c50ebf264535483e98ea33adca8e89adf06c5c7
```

Deployment creates a read-only scheduled workflow but neither writes GHCR nor
accesses Kubernetes. The first manual observation is a separate evidence step.
GO-1, infrastructure mutation and failure injection remain NO-GO.
