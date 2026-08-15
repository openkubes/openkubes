# OK-141 M0a v5 runtime result

Status: **STOP-NOT-SUCCESS / grants consumed / no retry**

The single authorized M0a-v5 run started at `2026-08-13T07:00:48Z` and
finished at `2026-08-13T07:12:30Z`.

The exact create-only submission was attempted once. The retained, bounded API
diagnostic identifies an admission-expression failure for cluster-scoped
requests: the policy accessed the optional `request.namespace` field without a
presence guard. Exact post-submit inventory proved that all 19 reviewed CAAPH
identities remained absent. All five temporary credential/admission objects
were removed, the temporary kubeconfig was deleted, and no rollback is needed
or authorized.

The mandatory credential rejection probe did not contact the API. A
sub-second early return from `sleep()` placed the local sample immediately
before the exact whole-second boundary, so the executor stopped fail closed.
Token rejection is therefore not proven by this run.

The raw evidence remains local and excluded from Git. This directory contains
only a redacted, non-published checkpoint. It grants no publication, retry,
rollback, M0b-I, GO-1, target convergence, or failure injection.
