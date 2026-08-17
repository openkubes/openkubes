# OK-141 capability-name-boundary amendment v1

This additive amendment responds to the failed capability run without
reinterpreting the historical v8 fixture.

The failure was in the test method: the bound run identifier produced a
Kubernetes Service name and label value longer than 63 characters. The
authoritative capability script now derives a deterministic, checksum-suffixed,
bounded identity. The same source revision also strengthens the existing
artifact lock by binding the Helm version and image that produced its unchanged
render digest.

The amendment proves offline that:

- the new capability script and artifact lock match the authoritative Git commit;
- the Platform render inputs and required resource membership are unchanged;
- the three Applications differ only by their immutable source revision;
- the new `P`, `R`, and `FixtureDigest` are reproducible;
- the historical v8 identities remain reproducible; and
- old, mutable, stale, or semantically changed inputs fail closed.

`authorization: NO-GO` is intentional. This document does not authorize a live
metadata amendment or another capability execution.
