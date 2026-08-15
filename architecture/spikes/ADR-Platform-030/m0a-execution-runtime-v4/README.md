# OK-141 first M0a v4 runtime result

Status: **STOP-NOT-SUCCESS / grants consumed / no retry**

The single authorized M0a-v4 run started at `2026-08-12T18:01:29Z` and
finished at `2026-08-12T18:13:11Z`.

The corrected create-only submission was attempted once and returned a
non-zero result. The response body was not retained, so this checkpoint does
not assign a cause. Exact post-submit inventory proved that all 19 reviewed
CAAPH identities remained absent. All five temporary credential/admission
objects were removed; no CAAPH rollback is needed or authorized.

The final expiry-bound probe also stopped fail closed. The token authenticated
on the last probe at or before `expirationTimestamp + 100s`; the implementation
did not make a mandatory first probe after that deadline. Rejection is therefore
not proven, and no claim about authentication after the deadline is made.

The raw local evidence remains outside Git. This directory contains only a
redacted candidate checkpoint and grants no publication, retry, rollback,
M0b-I, GO-1, target convergence, or failure injection.
