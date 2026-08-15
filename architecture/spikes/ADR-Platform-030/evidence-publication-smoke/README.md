# OK-141 evidence publication smoke protocol

Status: **ready for bounded C1/P0 decision; NO-GO**

This protocol defines a synthetic, redacted smoke test of the complete evidence
transport without Kubernetes access or infrastructure mutation. C1 may create
one seven-day Actions artifact. P0 may later create one GHCR artifact and one
attestation, then verify a digest-only pull-back.

Smoke success proves the evidence pipeline mechanics only. It is not GO-1,
cluster-lifecycle, enablement, platform, recovery, or failure-injection evidence.
