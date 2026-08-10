# OK-141 GHCR observer preflight

Status: **read-only observed; blocked; NO-GO**

This checkpoint evaluates the selected evidence destination without creating a
package, environment, workflow, credential, attestation, or artifact.

```text
ghcr.io/openkubes/ok141-evidence:  NOT FOUND (404)
Current token package listing:     FORBIDDEN (403 / missing read:packages)
GitHub Actions:                    enabled
Default GITHUB_TOKEN:              read-only
Organization Action SHA policy:    not enforced
Evidence publish environment:      absent
```

Official GitHub capabilities support OCI artifacts, pull-by-digest,
repository-linked `GITHUB_TOKEN` publication, granular package permissions,
and digest-bound artifact attestations. They do not make GHCR WORM storage:
package administrators may delete versions, restore is conditional, and
attestations can also be deleted.

The proposed runtime is a manually dispatched GitHub Actions workflow using an
exact environment, minimal explicit permissions, full-SHA Action references,
OCI digest capture, attestation, and pull-back verification. It remains a
proposal; no runnable workflow is present.

The cache-busted GitHub HTTPS time observation passed the five-second limit at
one point in time. A prior cached response was rejected. The measurement must
be repeated inside every later authorized window.

## Retention proposal awaiting acceptance

```text
Model:       DEV-BEST-EFFORT-NON-WORM
Minimum:     OK-141 closure + 90 days
Primary:     GHCR OCI artifact by digest
Index:       reviewed Git commit with OCI/bundle/attestation correlation
Monitoring:  required, not implemented
```

The Git index preserves correlation, not the complete payload. GHCR deletion
can still destroy evidence availability, so this proposal makes no production
retention, immutability, or DR claim.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-observer-preflight/verify_ghcr_observer_preflight.py \
  --preflight architecture/spikes/ADR-Platform-030/ghcr-observer-preflight/ghcr-observer-preflight-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-observer-preflight/ghcr-observer-preflight-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-observer-preflight/tests \
  -p 'test_*.py' -v
```

All external writes, credentials, installations, GO-1, and failure injection
remain `NO-GO`.
