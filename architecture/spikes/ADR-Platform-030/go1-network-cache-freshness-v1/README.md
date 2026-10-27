# OK-141 Cilium cached-health freshness amendment v1

This offline-only amendment replaces the historical fixed 120-second path-age
limit with a bounded rule derived from Cilium's own cached-health timing:

```text
maximum age = advertised probe interval
            + 60-second API publication interval
            + 10-second scheduling/clock tolerance
```

The advertised interval must be positive and at most 300 seconds. Response and
path timestamps may not be more than ten seconds in the future. Exact node and
path coverage, successful status semantics, and current timestamps remain
mandatory.

The fixture's observed interval is 96.566 seconds, yielding a maximum accepted
age of 166.566 seconds. The diagnostic itself remains private and unpublished.
This candidate grants no cluster contact, retry, continuation, or mutation.

