# OK-141 ok-shared Talos baseline amendment

Status: **SOURCE-BOUND READ-ONLY CHECKPOINT; LIVE REFRESH REQUIRED; NO-GO**

This checkpoint records the Talos registry-trust extension applied to the
existing `ok-shared` incarnation during OK-138. It binds the reviewed
`ok-cluster` implementation and preserves the live acceptance report as
historical Jira evidence. It does not repeat the live observation and performs
no infrastructure mutation.

## Result

```text
Talos registry CA trust:       reported applied to 4/4 existing Nodes
Static registry resolution:    reported applied to 4/4 existing Nodes
Uncached kubelet pull:         reported acceptance-proven
Replacement inheritance:      absent; runtime apply must be repeated
From-scratch recovery:         two-phase bootstrap required
Distinct consumer onboarding: not proven
General shared trust policy:   not established

M0b-I / GO-1:                 NOT GRANTED
Infrastructure:               NO-GO
Failure Injection:            NO-GO
```

The runtime patch adds the internal registry CA and a static host entry for
`registry.ok-shared.internal` at `192.168.100.207`. The address is a private
datacenter address published by `ok-infra`; it is not a public Internet address.

## OK-141 impact

This is an additive host-platform prerequisite for the current `ok-shared`
placement candidate. It is not part of Platform revision `P`: `P` describes the
platform desired state for an external workload target, while this Talos state
belongs to the GitOps control plane host.

The existing placement decision remains limited to external workload Clusters;
Argo on `ok-shared` may not manage `ok-shared` itself. The change does not prove
an OpenKubes-owned reconciler is necessary and does not change the leading
architecture hypothesis.

Before any M0b-I decision, the bounded live observer must refresh the
`ok-shared` incarnation and the registry-trust readback. Recovery evidence must
also account for both known gaps:

1. a from-scratch `ok-shared` bootstrap must first establish the registry stack
   and then apply registry trust; and
2. a new or replacement Talos Machine does not inherit the runtime-only patch,
   so the bounded trust operation must be rerun after its workload `Node`
   identity exists.

These are accepted DEV rebuild constraints, not production recovery or
lifecycle-continuity claims.

## Claim boundaries

- Jira comment `13556` is historical operational evidence, not a fresh
  independent observation by OK-141.
- Exact node identities and live configuration must be re-observed before an
  installation decision.
- Matching registry content digest proves integrity, not publisher
  authenticity.
- CA trust plus static resolution on `ok-shared` does not prove onboarding of a
  distinct consumer Cluster.
- Runtime trust is not inherited by CAPI replacement Machines because the CAPI
  bootstrap objects were intentionally not changed.
- `extraHostEntries` is an interim resolution mechanism until an authoritative
  DNS mechanism replaces it.
- This concrete registry case does not authorize a platform-wide trust policy or
  an ADR-020 amendment.

## Sources

- [OK-138 comment 13556](https://kubernauts.atlassian.net/browse/OK-138?focusedCommentId=13556)
- `openkubes/ok-cluster @ 16ba617d2a21578014df2506bcf5517ce4fb6550`
- registry-trust implementation: `a68b53a`, `c388b93`, `ec16e4d`
- recovery documentation: `585a92d`

Exact source-file digests and the evidence classification are bound in
`ok-shared-talos-baseline-v1.yaml`.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ok-shared-talos-baseline-amendment/verify_ok_shared_talos_baseline.py

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ok-shared-talos-baseline-amendment/tests \
  -p 'test_*.py' -v
```
