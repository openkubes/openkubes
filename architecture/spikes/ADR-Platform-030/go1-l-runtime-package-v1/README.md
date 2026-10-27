# OK-141 GO1-L runtime package v1

This package turns the reviewed five-operation lifecycle sequence into two
separately authorized, fail-closed execution stages:

```text
fresh PF-V2
  -> G1: provider prerequisites, management Namespace,
         provider-access Secret, CAPI lifecycle
  -> bounded lifecycle/API observation
  -> G3: one current HelmChartProxy
  -> bounded enablement/NetworkReady observation
```

The package creates six short-lived, redacted credential receipts internally
and derives one exact inner operation grant immediately before each operation.
All derived grants remain bounded by the human-authorized outer stage grant,
the exact executor-v2 digest, the PF-V2 evidence digest and the predecessor
evidence chain.

The merged candidate remains inert. It contains no live grant, credential,
Secret, preflight result or mutation authority.

Candidate digest:

```text
sha256:ac2bb971898606c08e076f89cb153fc0ff0589a12db608e339975ea7bf4245a4
```

```text
G1:                NOT GRANTED
G3:                NOT GRANTED
GO1-L:             NOT GRANTED
GO-1:              NOT GRANTED
Retry/Cleanup:     NOT GRANTED
Failure Injection: NOT GRANTED
```
