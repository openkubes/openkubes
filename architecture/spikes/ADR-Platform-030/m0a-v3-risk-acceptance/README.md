# OK-141 M0a v3 risk acceptance

Status: **ACCEPTED-DEV-ONLY / non-authorizing**

This checkpoint records the explicit acceptance of the three risks bound to
security candidate
`sha256:d3c6d3336486594da39ad380edbbd7b753a417a662283529d9bca4fd26af777e`:

- expiry-bound TokenRequest rejection observation;
- the retained create-content boundary;
- the temporary admission-bootstrap boundary.

The acceptance permits preparation of a new offline executable candidate. It
does not grant credentials, admission installation, a CAAPH retry or
installation, rollback, evidence publication, M0b-I, GO-1, target convergence,
or failure injection. The consumed v1 and v2 grants remain unusable.

Verify with:

```bash
python3 verify_m0a_v3_risk_acceptance.py \
  --evidence m0a-v3-risk-acceptance-v1.yaml \
  --digest-file m0a-v3-risk-acceptance-v1.sha256
pytest -q tests
```
