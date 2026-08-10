# OK-141 GHCR retention decision

Status: **policy accepted; implementation blocked; NO-GO**

This checkpoint records the explicit acceptance by
`github:arashkaffamanesh` of the following DEV-only evidence-retention model:

```text
Model:         DEV-BEST-EFFORT-NON-WORM
Minimum:       90 complete days after the recorded OK-141 closure timestamp
Primary copy:  ghcr.io/openkubes/ok141-evidence by OCI manifest digest
Git copy:      reviewed correlation index, not the full evidence payload
Monitoring:    required, not implemented, interval undecided
```

The decision accepts known deletion and availability limits. A package
administrator may delete evidence, restore is conditional rather than
guaranteed, and neither GHCR nor the Git correlation index is WORM storage.
The model therefore makes no production-retention, guaranteed-availability,
or disaster-recovery claim.

The 90-day period is a minimum, not a mandatory deletion date. It starts only
when an authoritative OK-141 closure timestamp exists. Retaining evidence
longer is allowed; shortening the period requires a new explicit decision.

Deletion monitoring remains a separate unimplemented prerequisite. When
implemented, it may detect a missing digest, alert, and fail closed. It may not
delete, restore, repair, republish, or otherwise mutate a package.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-retention-decision/verify_ghcr_retention_decision.py \
  --decision architecture/spikes/ADR-Platform-030/ghcr-retention-decision/ghcr-retention-decision-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-retention-decision/ghcr-retention-decision-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-retention-decision/tests \
  -p 'test_*.py' -v
```

This checkpoint creates no package, environment, workflow, credential,
attestation, or artifact. External writes, M0a/M0b installation, GO-1,
infrastructure mutation, and failure injection remain `NO-GO`.
