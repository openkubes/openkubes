# OK-141 GHCR deletion-monitoring interval decision

Status: **24-hour DEV target accepted; implementation blocked; NO-GO**

This checkpoint records acceptance of a `PT24H` target interval for observing
the OK-141 evidence artifact by exact OCI manifest digest.

```text
Target interval:       24 hours
Digest present:        OBSERVED-PRESENT
Digest missing:        ALERT-AND-FAIL-CLOSED
Observer late/down:    UNKNOWN-AND-FAIL-CLOSED
Detection guarantee:   none
Package mutation:      forbidden
```

The interval is a DEV best-effort observation target. It does not guarantee
that deletion will be detected within 24 hours: a delayed, skipped, or
unavailable observer cannot establish continued evidence availability.

The observer may eventually read, verify, record, and alert. It may not
restore, repair, republish, write, or delete packages. Its workflow, schedule,
package-read authority, and alert integration are not implemented or
authorized by this decision.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-deletion-monitoring-decision/verify_ghcr_deletion_monitoring_decision.py \
  --decision architecture/spikes/ADR-Platform-030/ghcr-deletion-monitoring-decision/ghcr-deletion-monitoring-decision-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-deletion-monitoring-decision/ghcr-deletion-monitoring-decision-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-deletion-monitoring-decision/tests \
  -p 'test_*.py' -v
```

All workflow and credential changes, external writes, M0a/M0b installation,
GO-1, infrastructure mutation, and failure injection remain `NO-GO`.
