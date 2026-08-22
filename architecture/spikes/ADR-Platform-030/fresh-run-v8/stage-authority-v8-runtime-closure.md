# OK-147 Stage Authority v8 runtime closure

This redacted checkpoint records the one authorized Stage Authority rebind
needed after Fresh-Run v8 completed the Stage-7 target-access input.

```text
state:                    PASS
candidate:                sha256:30229fb80e76bc76879a1e40aaf336069ab315d69bcd0cc98c41cead67000c6f
policy:                   sha256:6bdc6242be014915accef722deb8e1231dc29f320a515298174b5fbb1839184c
plan:                     sha256:6ee040f56518e479f1d4153fce7dbd630939b8f0a5ef2fc4ca7e1f9f73e4cc6d
runner image:             ghcr.io/openkubes/ok-cluster-runner@sha256:86b5b1175944785d787fcc1b408114d31341c67be90841f896aedc43389f5af2
ready replicas:           1
updated replicas:         1
```

The run created only immutable Secret
`openkubes-execution-system/ok147-stage-authority-private-v8` and performed one
UID- and resourceVersion-protected patch of StatefulSet
`openkubes-execution-system/ok147-stage-authority`. The patch changed only the
policy digest annotation, source Secret and the two expected-policy-digest
arguments. The runner image, TLS and client material, existing PVC and prior
private Secret were retained.

The private local evidence is mode `0600` and has raw-artifact digest
`sha256:c7854ffe66d839739c5aa14d16c2454a3a7a7536dd3200f19da7f39a9c2054cc`.
Its bytes are deliberately excluded from Git.

No TokenRequest, stage execution, disposable-cluster lifecycle mutation,
retry, rollback, cleanup or failure injection occurred. This checkpoint does
not authorize any subsequent operation.
