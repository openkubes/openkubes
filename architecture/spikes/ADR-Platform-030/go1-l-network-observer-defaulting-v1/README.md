# OK-141 Network observer defaulting amendment v1

This additive checkpoint explains the fail-closed `FAIL-HCP-SPEC` result from
the first post-remediation Happy Run continuation. The live
`HelmChartProxy` differed from the reviewed payload only because Kubernetes
materialized the CAAPH CRD default
`spec.options.enableClientCache: false`.

The v1 observer compared the stored object directly with the pre-defaulted
payload. That comparison correctly stopped the run, but it was stricter than
semantic desired-state equality across the Kubernetes API boundary.

The amendment normalizes exactly one field from the bound CAAPH v0.6.4 CRD:

```text
missing spec.options.enableClientCache
    -> false
```

The rule is applied to both desired and observed projections. It neither drops
unknown fields nor accepts `true`; unrelated spec drift continues to fail.

The raw live object remains private under `/private/tmp`. This checkpoint
contains no raw runtime evidence, credential, Secret, retry grant, mutation, or
Happy Run authorization.

Run the offline checks with:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-network-observer-defaulting-v1/test_network_observer_defaulting_v1.py
python3 architecture/spikes/ADR-Platform-030/go1-l-network-observer-defaulting-v1/network_observer_defaulting_v1.py verify
```
