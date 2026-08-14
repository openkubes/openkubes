# OK-141 GO1-L bounded executor v1

This additive executor closes the transport gap discovered after GO-1 v6 was
bound. It composes the reviewed static submitter v3 and provider-access
materializer v1, but replaces their unbound `kubectl` lookup with the exact
verified v1.34.1 client.

No desired-state semantics or payloads are reimplemented. The tool obtains all
four static payloads from submitter v3 and the dynamic Secret template and
validation from materializer v1. Every operation remains independently
authorized, create-only, single-run, predecessor-bound, and fail-closed.

The first operation requires a fresh PF-V2 evidence file. Later operations bind
the same baseline digest through their predecessor chain; they do not pretend
that a five-minute baseline remains fresh throughout cluster convergence.

This checkpoint is offline only. It contains no runtime receipts or grants and
authorizes no credential use, cluster contact, or mutation.

Candidate digest:

```text
sha256:206b62b955d7709f69601989d91b7b5938afba03b2235a4909c64fcecd4fac70
```

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-executor-v1/bounded_go1_l_executor_v1.py verify
python3 -m unittest architecture/spikes/ADR-Platform-030/go1-l-executor-v1/test_go1_l_executor_v1.py
```

```text
Executor mechanism:  offline proven
Exact client:        kubectl v1.34.1, digest-bound, no PATH lookup
Operations:          5
Objects:             13
Credential use:      NOT GRANTED
GO1-L:               NOT GRANTED
GO-1:                NOT GRANTED
Infrastructure:      NO-GO
Failure Injection:   NO-GO
```
