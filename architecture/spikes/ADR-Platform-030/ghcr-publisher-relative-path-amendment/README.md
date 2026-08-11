# OK-141 publisher relative-path amendment

Status: **reviewed W1 deployment candidate; no dispatch authorized**

The first authorized P0 attempt proved every guard through deterministic
transport creation, then ORAS 1.3.3 rejected the absolute layer path before
upload. This amendment applies the exact transform recorded by the merged
failure checkpoint:

```text
cd "$RUNNER_TEMP"
$RUNNER_TEMP/evidence-bundle.tar
  -> evidence-bundle.tar
```

The amended workflow digest is:

```text
sha256:6837271e8929eac133d1f5f6fb1bbaba3b83f61a772f27a856b51e79d673a27b
```

The layer bytes, source-run correlation, protocol binding, OCI artifact type,
destination, non-authoritative run tag, permissions, protected environment,
action pins and ORAS checksum are unchanged.

Merging this amendment only deploys reviewed workflow source. The workflow is
manual-only and is not dispatched by this change. The consumed two-run budget
from the original smoke remains closed. A new bounded retry protocol and a
separate exact publication authorization are still required.

```text
W1 source deployment: candidate
Publisher dispatch:   NOT AUTHORIZED
Package write:        NOT AUTHORIZED
GO-1:                 NOT GRANTED
Infrastructure:       NO-GO
Failure injection:    NO-GO
```
