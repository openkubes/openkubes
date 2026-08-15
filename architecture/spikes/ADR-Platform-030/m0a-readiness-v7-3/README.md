# OK-141 M0a v7.3 corrected readiness evaluation

Status: **READ-ONLY EVALUATOR / NO MUTATION AUTHORITY**

The v7.2 repair made CAAPH operational, but the historical readiness function
compared the runtime `imageID` to the locked linux/amd64 child-manifest digest.
On this target, containerd reports the pulled OCI index digest as `imageID`.

This evaluator preserves both identities and their distinct claims:

```text
runtime imageID
  -> locked OCI index digest

target architecture linux/amd64
  -> locked linux/amd64 child-manifest digest
```

It accepts runtime image identity only when the live `imageID` equals the
locked index digest and the same installation lock carries the linux/amd64
child digest. It also re-evaluates the other CAAPH readiness and zero-target
conditions. It cannot write to the cluster and grants no publication, HCP/HRP,
target convergence, M0b-I, GO-1, or failure-injection authority.
