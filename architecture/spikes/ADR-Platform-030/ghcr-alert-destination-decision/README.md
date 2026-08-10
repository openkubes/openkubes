# OK-141 GHCR alert-destination decision

Status: **GitHub Actions alert surface accepted; implementation blocked; NO-GO**

This checkpoint selects the failed GitHub Actions run and its job summary in
`openkubes/openkubes` as the DEV alert surface for the OK-141 evidence
observer.

```text
Primary signal:    failed workflow run
Details:           GitHub Actions job summary
Recipient:         github:arashkaffamanesh
Extra API writes:  none
Delivery claim:    best effort, not guaranteed
```

This choice avoids `issues:write`, webhook, package-write, and package-delete
authority. A started workflow can fail and report a missing digest or another
verification error. A scheduled workflow that never starts cannot report its
own absence, so independent freshness evaluation remains unresolved.

The decision creates no workflow, schedule, notification, issue, webhook,
credential, package, or infrastructure resource.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-alert-destination-decision/verify_ghcr_alert_destination_decision.py \
  --decision architecture/spikes/ADR-Platform-030/ghcr-alert-destination-decision/ghcr-alert-destination-decision-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-alert-destination-decision/ghcr-alert-destination-decision-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-alert-destination-decision/tests \
  -p 'test_*.py' -v
```

Workflow deployment, schedule creation, alert testing, credentials, external
writes, M0a/M0b installation, GO-1, infrastructure mutation, and failure
injection remain `NO-GO`.
