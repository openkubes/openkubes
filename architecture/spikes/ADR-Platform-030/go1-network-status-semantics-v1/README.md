# OK-141 Cilium network status semantics amendment v1

This additive, offline-only checkpoint corrects the functional network
evaluator's interpretation of the Cilium v1.19.6 health JSON model.

At the fixture-bound Cilium commit, a successful ICMP or HTTP probe leaves the
Go `Status` string at its zero value. The generated API model serializes that
field with `json:"status,omitempty"`, so successful JSON normally omits
`status`. Errors set a non-empty status string. The historical evaluator
required an explicitly present empty string and therefore treated an omitted
success field as a connectivity failure.

The amended rule is deliberately narrow:

```text
status omitted             -> success candidate
status present and ""      -> success candidate
status present and nonempty -> failure
status present and null/non-string -> failure
```

Success still additionally requires the exact expected node/path coverage,
fresh probe and path timestamps, and a successful fixed probe command. The
amendment does not weaken any of those checks.

The authoritative sources are pinned to Cilium commit
`9a8982433e18019e290b8199c0c4ad24f66befe8` in
[`connectivity_status.go`](https://github.com/cilium/cilium/blob/9a8982433e18019e290b8199c0c4ad24f66befe8/api/v1/health/models/connectivity_status.go)
and
[`prober.go`](https://github.com/cilium/cilium/blob/9a8982433e18019e290b8199c0c4ad24f66befe8/pkg/health/server/prober.go).

This checkpoint contains no raw runtime evidence, credentials, cluster access,
mutation, retry, Happy Run continuation, or evidence-publication authority.

Run the offline checks with:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-network-status-semantics-v1/test_network_status_semantics_v1.py
python3 architecture/spikes/ADR-Platform-030/go1-network-status-semantics-v1/network_status_semantics_v1.py verify
```

