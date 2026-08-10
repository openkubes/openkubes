# OK-141 GHCR publisher offline prototype

Status: **implemented offline; inert and write-capable; not deployed; NO-GO**

This checkpoint implements deterministic publication planning, transport
creation, receipt materialization, and pull-back verification. Its candidate
workflow remains outside `.github/workflows`.

```text
Input:             already verified evidence bundle + exact source run ID
Transport:         deterministic tar
Internal identity: evidence bundle SHA-256
Registry identity: OCI manifest SHA-256
Tag:               non-authoritative run locator
Attestation:       exact OCI subject + repository/signer/ref verification
Pull-back:         OCI digest only
Live writes:       none performed
```

The candidate pins `actions/checkout`, `actions/attest`, ORAS v1.3.3, and the
ORAS Linux asset checksum. It models the exact write permissions required for
publication but grants none of them while stored in the spike directory.

The environment `ok-141-evidence-publish` does not exist. The workflow is not
deployed, no package or attestation was created, no credential was authorized,
and no live pull-back was attempted.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-publisher-offline-prototype/verify_publisher_offline_prototype.py \
  --manifest architecture/spikes/ADR-Platform-030/ghcr-publisher-offline-prototype/publisher-offline-prototype-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-publisher-offline-prototype/publisher-offline-prototype-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-publisher-offline-prototype/tests \
  -p 'test_*.py' -v
```

Deployment, environment/package creation, credentials, external writes,
M0a/M0b installation, GO-1, infrastructure mutation, and failure injection
remain `NO-GO`.
