# OK-141 M0b runtime registration risk acceptance v1

This record captures the explicit DEV-only acceptance of the eight risks bound
to security candidate
`sha256:3def094077184842e0d1f73292043b8d882e9ad7ba73d09e086ca8f291c1ff81`.

It is deliberately non-authorizing:

```text
Risk decision:          ACCEPTED DEV ONLY
Mutation:               NO-GO
Target access:          NOT GRANTED
TokenRequest:           NOT GRANTED
Target registration:    NOT GRANTED
Application submission: NOT GRANTED
GO-1:                   NOT GRANTED
```

Run:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-target-registration-risk-acceptance-v1/verify_m0b_runtime_registration_risk_acceptance_v1.py
```
