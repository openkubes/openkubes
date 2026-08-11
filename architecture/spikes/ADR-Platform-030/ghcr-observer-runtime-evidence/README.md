# OK-141 public observer runtime evidence

Status: **first live read-only observation verified**

The deployed observer completed one manual GitHub Actions run against the exact
public P1 OCI manifest digest.

```text
Run:                  31519905262
Conclusion:           success
Result:               OBSERVED-PRESENT
Workflow permission:  contents: read
Registry credential:  none
Package mutation:     none
```

The active daily schedule remains best effort. A successful first run proves
the deployed observer can locate and evaluate the exact digest; it does not
guarantee that every future scheduled run starts, completes, or is noticed.
Missing, denied, stale, mismatched and unverifiable observations remain
fail-closed.

The Node 20 deprecation annotation belongs to the SHA-pinned checkout action,
which GitHub forced to Node 24 successfully. It did not affect the observation.

No Kubernetes access or infrastructure mutation occurred. GO-1 and failure
injection remain NO-GO.
