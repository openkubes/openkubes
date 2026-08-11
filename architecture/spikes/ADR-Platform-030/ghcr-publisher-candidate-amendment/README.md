# OK-141 GHCR publisher candidate amendment

Status: **implemented offline; inert; W0/P0 remain NOT GRANTED**

This additive amendment responds to the two blockers found by the publisher
deployment preflight. It does not modify or reinterpret the historical v1
prototype.

The v2 candidate now:

- permits the write-capable job only on `refs/heads/main`;
- requires exact source run ID, workflow ID, head SHA, and protocol digest
  inputs;
- reads the source run through the GitHub API before artifact download;
- requires `openkubes/openkubes`, `workflow_dispatch`, `main`, completed/success,
  and exact workflow/head identities;
- verifies the downloaded evidence manifest's run ID and protocol digest before
  deterministic transport creation;
- retains the v1 digest-only publication, attestation, and pull-back boundary.

The workflow remains under this inert spike directory. There is no active
workflow, protected environment, package, attestation, credential, or observer
index.

Source-run metadata is proven in the workflow log but is not yet embedded in
the OCI evidence payload. P0 therefore still requires a separate durable
correlation decision before first publication.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-publisher-candidate-amendment/verify_publisher_candidate_amendment.py \
  --amendment architecture/spikes/ADR-Platform-030/ghcr-publisher-candidate-amendment/publisher-candidate-amendment-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-publisher-candidate-amendment/publisher-candidate-amendment-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-publisher-candidate-amendment/tests \
  -p 'test_*.py' -v
```

```text
E0:                   NOT GRANTED
W0:                   NOT GRANTED
P0:                   NOT GRANTED
Active workflow:      absent
External write:       NO-GO
Infrastructure:       NO-GO
Failure Injection:    NO-GO
```
