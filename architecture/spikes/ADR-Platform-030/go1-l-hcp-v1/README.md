# OK-141 Phase-R v5 HelmChartProxy amendment

Status: **OFFLINE-PROVEN-BLOCKED-NO-GO**

This checkpoint creates an additive HCP candidate carrying the current
Phase-R-v5 `R` and FixtureDigest. The desired Cilium/CAAPH Helm semantics and
enablement revision `E` remain exactly equal to the historical candidate.

```text
historical HCP
  R = Phase-R v4
  FixtureDigest = Phase-R v4
        ↓ carrier-only amendment
current HCP
  R = Phase-R v5
  FixtureDigest = Phase-R v5

spec / E / OCI identity / values identity = unchanged
```

The historical HCP remains reproducible and forbidden for future recreation.
The current candidate is also inert: no merged metadata or `blocked-no-go`
annotation is an authorization control. A future additive submitter binding,
recreation protocol, absence preflight, current lifecycle evidence, credential,
and explicit grant remain required before submission.

Verify offline:

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-hcp-v1/verify_hcp_phase_r_v5_amendment_v1.py
python3 architecture/spikes/ADR-Platform-030/go1-l-hcp-v1/test_hcp_phase_r_v5_amendment_v1.py -v
```

```text
HCP current carriers:   offline proven
Desired Helm semantics: unchanged
Submission:             NOT GRANTED
Recreation:             NOT GRANTED
GO1-L:                  NOT GRANTED
GO-1:                   NOT GRANTED
Infrastructure:         NO-GO
Failure Injection:      NO-GO
```
