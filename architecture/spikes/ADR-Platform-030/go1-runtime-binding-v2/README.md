# OK-141 GO-1 runtime binding v2

This package closes the runtime identity gap between the current Phase-R v5
lifecycle/NetworkReady evidence and the later Argo target registration.

The bounded tool rereads exactly one CAPI workload-kubeconfig Secret, writes it
only to an exclusive `0600` file under `/private/tmp`, and performs exactly two
workload GETs: `Namespace/kube-system` and `StorageClass/local-path`. It then
creates a local runtime binding containing the immutable cluster incarnation,
API CA fingerprint, target identity, and current predecessor evidence digests.

The local binding contains the public API CA data needed by the later
server-side Argo registration materializer. It is runtime material and must not
be committed or published. Kubeconfig and credential bytes are deleted and are
never printed. The candidate grants no live authority.

Offline verification:

```bash
python3 bounded_runtime_binding_v2.py verify
python3 -m unittest discover -s . -p 'test_*.py' -v
```

Candidate digest:

```text
sha256:2f44cd8682691b0d6d22629e8bd75bc398c05c2492cc9e56460cbe1ef3e2dc96
```
