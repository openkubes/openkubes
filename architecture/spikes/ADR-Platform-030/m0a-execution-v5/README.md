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

The initial v5 boundary hypothesized a full-stream server dry-run before real
create. Implementation analysis rejected that hypothesis: the required
`caaph-system` Namespace is intentionally absent, and a dry-run Namespace is
not persisted for validation of subsequent namespaced objects. V5 therefore
does not treat full-stream dry-run success as a valid gate. The matched client,
existing authorization/admission probes, exact absence, sanitized failure
capture, and exact post-submit inventory remain the applicable controls.

## Executable candidate

`m0a-execution-candidate-v5.yaml` binds the amended diagnostic boundary, the
unchanged v4 risk acceptance and 19-object payload, and the checksum-pinned
kubectl binary. `controlled_m0a_execution_v5.py` refuses cluster contact until
the binary path, size, digest, release, commit, and platform all match.

The read-only live preflight passed with the matched client and proved all 19
identities absent. The `NO-GO` grant template still requires three new,
distinct, exact grants, one UTC window, one run, and one absent raw evidence
path. This checkpoint grants none of them.

## Expired grant record (2026-08-12)

The received v5 grant bound the UTC window `2026-08-12T20:10:00Z` through
`2026-08-12T23:10:00Z`. It was received and evaluated only after that window
had ended. It therefore authorized no mutation and consumed none of its three
single-run grants.

The fail-closed record is
`m0a-expired-grant-v5-20260812.yaml`. A fresh read-only preflight is retained as
`m0a-v5-live-preflight-v2.yaml`; it observed all 19 reviewed identities absent,
zero CAPI lifecycle objects, the expected management-plane identity, and the
bound kubectl toolchain. That observation does not revive or extend the expired
grant.

Any future v5 execution requires a new explicit UTC window, new grant IDs, and
a newly bound raw-evidence path. Until then M0a remains `NOT GRANTED` and no
infrastructure mutation is authorized.
