# OK-141 M0a v4 risk acceptance

Status: **ACCEPTED-DEV-ONLY / non-authorizing**

This checkpoint records the explicit acceptance of the four risks bound to
security candidate
`sha256:ba2f854b2ce7d5e1528bd8d490a67dc8d163ad7548238117275c0b1d7db0dadd`:

- non-idempotent one-shot create and possible partial installation state;
- TokenRequest rejection observation through `expirationTimestamp + 100s`;
- the retained create-content boundary; and
- the temporary admission-bootstrap boundary.

The acceptance permits preparation of a new offline executable candidate. It
does not grant credentials, admission installation, a CAAPH retry or
installation, rollback, evidence publication, M0b-I, GO-1, target convergence,
or failure injection. The consumed v1-v3 grants remain unusable.

Verify with:

```bash
python3 verify_m0a_v4_risk_acceptance.py \
  --evidence m0a-v4-risk-acceptance-v1.yaml \
  --digest-file m0a-v4-risk-acceptance-v1.sha256
pytest -q tests
```
