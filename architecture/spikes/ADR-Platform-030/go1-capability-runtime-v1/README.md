# OK-141 capability runtime checkpoint

This checkpoint records the first live execution of the bound Observability
Capability test after all three Platform Applications converged for the v8
fixture.

The Platform itself converged successfully. Both the initial capability run
and its single diagnosis-bound retry stopped fail-closed because the test's
synthetic Pushgateway identity was 65 characters long. Kubernetes rejected the
Deployment and Service at their 63-character name/label boundary while the
ServiceMonitor could still be created. Prometheus therefore never discovered a
scrape target. OpenSearch independently observed the synthetic log marker.

The remediation is isolated in `openkubes/ok-observability` PR #13. That PR
does not change the capability contract or deployed Platform resources; it
derives checksum-suffixed synthetic names bounded to 63 characters.

No further capability retry is authorized from this checkpoint. After the
human merge of PR #13, OK-141 must bind the merged source commit and new test
digest, derive new `P`, `R`, and `FixtureDigest` identities, and prepare a new
single-run capability candidate. Historical v8 identities remain unchanged.

All raw runtime evidence, kubeconfigs, credentials, API endpoints, UIDs, and
resource versions remain under `/private/tmp` and are excluded from Git.
