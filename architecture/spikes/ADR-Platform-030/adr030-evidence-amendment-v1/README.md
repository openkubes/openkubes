# ADR-030 evidence amendment v1

Status: **Prepared / ADR remains Proposed**

This amendment aligns ADR-Platform-030 with the final OK-141 outcome A for the
tested DEV profile. It removes the unevidenced requirement for a continuously
running OpenKubes Status Aggregator, makes bounded fail-closed evaluation the
default, preserves an optional single-writer status adapter for a future forcing
consumer, and aligns the control-plane source condition with
`ControlPlaneAvailable`.

It does not accept the ADR, select a stable public API, claim management-outage
recovery, or authorize infrastructure mutation.
