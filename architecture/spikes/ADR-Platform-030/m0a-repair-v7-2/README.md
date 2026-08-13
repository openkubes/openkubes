# OK-141 M0a v7.2 exact deployment repair

Status: **OFFLINE CANDIDATE / NO-GO**

The v7.1 run created all 19 reviewed CAAPH objects but retained three provider
variable expressions literally in the controller arguments. This candidate
does not reinstall, retry, or delete the 19-object set. It proposes one exact
JSON Patch against the retained Deployment.

The patch is fail-closed through tests for the immutable Deployment UID, the
container name, and the complete old argument vector before replacing only the
argument vector. A changed UID, reordered container list, or changed arguments
stops before mutation.

Execution requires a new exact repair grant. Preparing and verifying this
directory performs no cluster mutation and grants no repair, retry, rollback,
publication, HCP/HRP submission, target convergence, M0b-I, GO-1, or failure
injection authority.
