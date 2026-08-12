# OK-141 M0a v5 diagnostic boundary

Status: **BLOCKED / offline only / no authority**

The consumed M0a-v4 run stopped safely with zero retained CAAPH objects, but
the create response body was not retained and the token loop had no mandatory
first sample after its configured deadline. The run also used kubectl v1.26.1
against a Kubernetes v1.34.1 API server.

V5 makes no retrospective cause claim. It strengthens the next candidate by
requiring:

- the official darwin/amd64 kubectl v1.34.1 binary, verified against the
  published SHA-256 and exact Kubernetes commit;
- a full server-side dry-run of the reviewed 19-object stream before the one
  real create submission;
- bounded, sanitized capture of the failed kubectl operation, exit code, and
  API error text without command paths, tokens, kubeconfigs, or payloads;
- an exact post-submit inventory on any attempted real create; and
- a mandatory credential probe whose start time is not earlier than
  `expirationTimestamp + 100s`.

The v4 accepted risks remain unchanged: create is non-atomic and
non-idempotent, payload equality is not proven by RBAC/admission, and the
temporary admission bootstrap remains cluster-scoped. V5 adds compensating
controls and diagnostic precision; it grants no retry or mutation and requires
a new digest-bound grant before any executable run.
