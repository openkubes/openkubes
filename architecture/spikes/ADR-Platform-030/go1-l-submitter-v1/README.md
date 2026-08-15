# OK-141 bounded GO1-L submitter v1

Status: **OFFLINE-PROVEN-BLOCKED-NO-GO**

This checkpoint binds a non-authoritative submitter to GO-1 v5 and exactly
twelve reviewed objects. It accepts no arbitrary manifest path, kubectl
argument, context, shell command, retry, rollback, cleanup, update, or patch.

The operation is intentionally split:

```text
1. provider-prerequisites (G1, ok-infra, 3 objects)
2. capi-lifecycle         (G1, ok-mgmt, 8 objects)
3. helmchartproxy         (G3, ok-mgmt, 1 object)
```

Each operation is Create-only and needs a fresh, maximum-20-minute operation
grant plus a separate mode-`0600` credential file and redacted credential
receipt. Later operations additionally require predecessor evidence. A grant
for one operation cannot authorize the next.

The merged candidate carries no grant and exposes only offline `verify` and
`plan` commands. The tested `execute_once` library entry point remains
unreachable without a future external grant and credential materialization.

## Bound identities

```text
GO-1 v5:  sha256:685b7e142e9b2e67dcee89ef091df93e4b9aa5d43ff32c7becf6df743e3df2b9
Candidate: sha256:e5b4185b7dcd4f1e3fb026d03ce29b5b35e0b6c5c6e51f29d921a240636b73cc
Objects:   12 across three operations and two authority planes
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-submitter-v1/verify_go1_l_submitter_v1.py

python3 architecture/spikes/ADR-Platform-030/go1-l-submitter-v1/test_bounded_go1_l_submitter_v1.py -v
```

## Remaining blockers

- exact least-privilege credential issuance and revocation for each operation
- absence preflight for all twelve object identities
- predecessor submission/readiness receipt formats
- fresh GO1-L and per-operation grants bound to one test window
- accepted partial-state risk for the non-atomic Create-only operations

```text
Submitter artifact:  offline proven
Credential gate:     unresolved
GO1-L:               NOT GRANTED
GO-1:                NOT GRANTED
Infrastructure:      NO-GO
Failure Injection:   NO-GO
```
