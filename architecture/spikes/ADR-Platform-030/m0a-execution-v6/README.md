# OK-141 M0a v6 offline fixes

Status: **OFFLINE ONLY / NO-GO**

The consumed v5 run proved two implementation defects without leaving CAAPH
or temporary bootstrap state behind:

1. the identity admission expression accessed `request.namespace` without a
   presence guard for cluster-scoped requests; and
2. a single `sleep()` could return a fraction before the exact token-rejection
   boundary, causing the local fail-closed guard to stop before the API probe.

This checkpoint provides deterministic, tested corrections only. The admission
amendment replaces exactly one reviewed expression with a presence-guarded
equivalent. The boundary helper rechecks wall-clock time after every sleep and
cannot return a sample earlier than the bound instant.

It is not an executable candidate, grants no credentials or admission
bootstrap, performs no cluster contact, and authorizes no retry.
