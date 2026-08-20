# OK-141 delete D0 storage-correlation amendment v3

Status: **OFFLINE-AMENDED / EXPLICIT NEW READ GRANT REQUIRED / NO-GO**

D0-v2 correctly amended DataVolume selection, then stopped at Longhorn
correlation. The subsequent two-GET diagnostic proved that both retained
Longhorn volumes exist and that all three proposed identity relations match
exactly two objects. It intentionally left the earlier zero-result classified
as transient-or-context-derivation.

V3 removes the fragile path entirely:

```text
raw provider PVs in memory
        ↓
bind exact PV name + CSI handle + claim namespace/name
        ↓
redact retained PV evidence independently of item.kind
        ↓
Longhorn Volume must satisfy metadata-name and kubernetesStatus equality
```

The DataVolume-v2 amendment and every other query remain unchanged. V3 uses
new private output paths and requires a new explicit single-use read grant. It
does not authorize D1-D7, mutation, deletion, cleanup, retry, outage or failure
injection.
