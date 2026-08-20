# OK-141 Longhorn correlation diagnostic closure v1

Status: **PASS-READ-ONLY-DIAGNOSTIC / REDACTED / NO-GO**

The authorized two-GET diagnostic observed exactly two provider PVs and all
three proposed Longhorn correlations returned exactly two matches. The selected
Longhorn volumes were attached, degraded and not restored from backup at the
observation time.

This disproves missing Longhorn storage as the explanation for the D0-v2 stop.
It localizes the remaining defect to the D0-v2 query/context path, but does not
claim whether the earlier zero-result was transient or caused by context being
derived after metadata redaction. D0-v3 must derive PV identities directly from
the raw in-memory PV response before redaction and retain the
`kubernetesStatus` tuple as an independent equality check.

No raw names, Kubernetes objects, UIDs, resourceVersions, endpoints,
credentials or Kubeconfigs are published. This closure grants no D0 retry,
mutation, delete, cleanup or evidence-publication authority.
