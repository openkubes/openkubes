# OK-141 bounded GO1-L submitter v2

Status: **OFFLINE-PROVEN-BLOCKED-NO-GO**

This additive checkpoint replaces the historical Phase-R-v4 submitter for
future recreation planning. It binds the static Create-only transport to the
corrected Phase-R v5 authority projection and preserves the required order:

```text
1. ok-infra  provider prerequisites (3 static objects)
2. ok-mgmt   management Namespace (one reviewed projection slice)
3. ok-mgmt   provider-access Secret (external materializer; not this tool)
4. ok-mgmt   remaining lifecycle resources (seven reviewed projection docs)
5. ok-mgmt   HelmChartProxy (blocked until a current-R candidate exists)
```

The management slices cover all eight Phase-R v5 documents exactly once and
recombine to the bound management semantic identity. The submitter accepts no
arbitrary manifest path, command, kubectl argument, Secret object, retry,
rollback, cleanup, update, patch, apply, or delete operation.

The existing HCP still carries the previous Phase-R-v4 `R` and FixtureDigest.
Its enablement revision `E` is unchanged, but carrier equivalence is not
inferred. The v2 tool therefore validates this historical candidate as a
negative control and refuses runtime execution of that operation. An additive
current-R HCP is required before the HCP operation can be enabled.

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-submitter-v2/verify_go1_l_submitter_v2.py
python3 architecture/spikes/ADR-Platform-030/go1-l-submitter-v2/test_bounded_go1_l_submitter_v2.py -v
```

```text
Phase-R v5 FixtureDigest: sha256:7536456a…e4cc3eb
Submitter candidate:      sha256:9f92172f…26d5f7a
Tests:                    13 PASS
```

Remaining blockers:

- secret-safe provider-access materializer and its independent receipt;
- additive HCP carrying Phase-R v5 `R` and FixtureDigest;
- additive recreation protocol bound to Phase-R v5 and this submitter;
- fresh per-operation credentials, grants, absence preflights, and receipts.

```text
Static submitter:       offline proven
Provider Secret:        external / not implemented
HCP runtime operation:  blocked by historical R carrier
Recreation:             NOT GRANTED
GO1-L:                  NOT GRANTED
GO-1:                   NOT GRANTED
Infrastructure:         NO-GO
Failure Injection:      NO-GO
```
