# OK-141 evidence publication P1 retry protocol

Status: **ready for one exact P1 decision; no dispatch authorized**

P0 failed before upload because ORAS rejected an absolute layer path. W1 has
deployed the exact relative-path correction without dispatch. P1 is a new,
single-run authorization envelope for retrying the same already verified C1
bundle.

The collector bundle is immutable and remains bound to the original smoke
protocol digest. Therefore the publisher input must remain that original
digest. The new P1 protocol digest authorizes the retry itself and is enforced
at the protected-environment approval boundary, where it must be recorded with
the exact new publisher run ID.

```text
original protocol digest
  -> verifies the immutable C1 bundle inside the workflow

P1 protocol digest
  -> authorizes exactly one retry at environment approval
```

This split is explicit rather than pretending that the historical bundle was
created under a later authorization. The final evidence must retain both
identities.

P1 remains ungranted until a human decision cites the exact P1 protocol digest.
No cluster access, infrastructure mutation or failure injection is in scope.
