# OK-141 GO-1 protocol v4 — gate-partition amendment

Status: **structurally complete; BLOCKED; GO-1 NOT GRANTED**

Baseline: `main @ 16b293781c47b4a1e3df120bee98f83b5fecc981`

This additive read-only amendment binds the merged gate partition to the exact
Phase-R-v4 fixture. It corrects the ordering contradiction in historical GO-1
v3 without changing v3 or any M0 artifact.

GO-1 v4 distinguishes:

```text
Pre-GO requirements
  -> must be CLOSED before a GO decision

Runtime obligations
  -> remain PENDING-RUNTIME before GO
  -> may be evaluated only in their bound G2-G5 phase
  -> missing, stale, conflicting, or uncorrelated evidence means STOP

Deferred scenarios
  -> excluded from GO-1
  -> require separate protocols and authorizations
```

`M0a-I` and `M0b-I` are installation-only gates. Even a future grant for either
gate cannot authorize workload-target convergence or GO-1.

The protocol remains non-authorizing:

```text
Protocol merged             != GO
Pre-GO requirements closed  != GO
Runtime obligations pending == expected before GO
Explicit human grant        == only possible GO transition
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-v4/verify_go1_protocol_v4.py \
  --protocol architecture/spikes/ADR-Platform-030/go1-v4/go1-protocol-v4.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/go1-v4/go1-protocol-v4.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/go1-v4/tests \
  -p 'test_*.py' -v
```

## Safety state

```text
GO-1 v4:           BLOCKED
M0a-I / M0b-I:     NOT GRANTED
M0a / M0b:         NOT GRANTED
GO-1:              NOT GRANTED
Infrastructure:    NO-GO
Failure Injection: NO-GO
```
