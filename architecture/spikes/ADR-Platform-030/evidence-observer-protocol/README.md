# OK-141 evidence destination and observer protocol

Status: **GHCR selected; offline mechanism defined; publication NO-GO**

The accepted DEV evidence destination is:

```text
ghcr.io/openkubes/ok141-evidence
```

Evidence is authoritative only through both its internal bundle digest and the
eventual OCI manifest digest. Tags are convenience locators and never evidence
identity. GHCR is external to the DEV Kubernetes Clusters, but administrators
can delete packages; this checkpoint therefore claims content integrity only,
not retention, availability, authenticity, or deletion protection.

The local bundle tool deterministically inventories already-redacted UTF-8
JSON, YAML, text, log, and Markdown evidence. It rejects Kubernetes Secret
objects, kubeconfigs, credential-like paths and keys, private keys, bearer
headers, symlinks, unknown media types, oversized input, changed files, stale
bindings, and invalid timestamp ordering. It never silently redacts content.

Two automated roles are defined but not deployed:

```text
ok-141-security-observer
ok-141-evidence-observer
```

Under the accepted DEV-SOLO model these are deterministic technical controls,
not an independent-human-review claim.

## Current boundary

```text
Destination selection:       ACCEPTED
Bundle build/verify:          offline defined
GHCR access:                  UNPROVEN
Retention:                    UNRESOLVED
Clock source/skew:            UNPROVEN
Automated observer runtime:   NOT DEPLOYED
Publication credential:      NOT AUTHORIZED
External write:               NO-GO
M0a-I / M0b-I / GO-1:        NOT GRANTED
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/evidence-observer-protocol/verify_evidence_observer_protocol.py \
  --protocol architecture/spikes/ADR-Platform-030/evidence-observer-protocol/evidence-observer-protocol-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/evidence-observer-protocol/evidence-observer-protocol-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/evidence-observer-protocol/tests \
  -p 'test_*.py' -v
```
