# OK-141 GHCR observer offline prototype

Status: **implemented offline; inert; not deployed; NO-GO**

This checkpoint implements a deterministic digest observer and a candidate
GitHub Actions workflow outside `.github/workflows`.

```text
Candidate workflow:  inert spike path
Active workflow:     absent
Active index:        absent by design
Registry operation:  HEAD manifest by exact OCI digest
Registry scope:      pull only
Success:             exact digest present within retention window
Failure:             exit 2 + bounded job summary
Mutation surface:    none
```

The candidate grants only `contents: read` and `packages: read`, pins
`actions/checkout` to a full commit SHA, and disables persisted checkout
credentials. It contains no package-write, delete, issue, webhook, restore,
repair, or republish operation.

The deterministic core is tested with offline observations. No GHCR request
was made. The real active index cannot exist until a separately authorized
first publication produces an OCI manifest digest and pull-back evidence.

A candidate under the spike directory is not a deployed workflow. Moving it
to `.github/workflows` requires a separate reviewed mutation gate and a new
bound digest.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-observer-offline-prototype/verify_observer_offline_prototype.py \
  --manifest architecture/spikes/ADR-Platform-030/ghcr-observer-offline-prototype/observer-offline-prototype-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-observer-offline-prototype/observer-offline-prototype-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-observer-offline-prototype/tests \
  -p 'test_*.py' -v
```

Workflow deployment, schedule creation, active-index creation, package
credentials, external writes, M0a/M0b installation, GO-1, infrastructure
mutation, and failure injection remain `NO-GO`.
