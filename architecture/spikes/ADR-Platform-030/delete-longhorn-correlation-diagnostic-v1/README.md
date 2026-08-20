# OK-141 Longhorn correlation diagnostic v1

Status: **OFFLINE-PREPARED / EXPLICIT READ GRANT REQUIRED / NO-GO**

D0-v2 corrected DataVolume selection, then stopped fail-closed at the final
provider-storage query: two provider PV identities were bound, but correlation
through `PV.spec.csi.volumeHandle == Longhorn Volume.metadata.name` returned no
objects. No D0-v2 private output, mutation, delete or retry followed.

This diagnostic performs only two collection GETs on `ok-infra`:

1. PersistentVolumes, post-filtered to claim namespace `disposable-ok141`.
2. Longhorn Volumes in `longhorn-system`.

It compares three candidate correlations entirely in memory:

- PV `csi.volumeHandle` to Longhorn `metadata.name`;
- PV `metadata.name` to Longhorn `metadata.name`;
- PV namespace/name/claim to Longhorn `status.kubernetesStatus`.

Only counts, booleans, categorical status values and SHA-256 identity digests
may be written to the private `0600` evidence file. Raw names, UIDs,
resourceVersions, endpoints and objects are not retained. The diagnostic grants
no D0 retry, mutation, deletion, cleanup or publication.
