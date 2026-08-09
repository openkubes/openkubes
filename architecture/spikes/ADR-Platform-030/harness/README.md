# OK-141 Read-only Harness

This directory implements only the Phase-R test sensors defined by OK-141:

- `canonicalize`: strict schema validation, versioned defaults, semantic projection,
  canonical JSON, and intent revision `R`;
- `evaluate`: fail-closed `True`/`False`/`Unknown` aggregation over retained source
  evidence;
- `bundle`: content-addressed evidence manifest creation; and
- `verify`: independent artifact-hash verification; and
- `verify-fixture`: reconstruction and fail-closed verification of the exact Phase-R
  execution fixture, including the distinct `R`, `E`, `P`, and `FixtureDigest`
  identities.

It is not a public OpenKubes API, Contract-to-CAPI compiler, controller, allocator, or
infrastructure client. It has no Kubernetes write path.

Requirements: Python 3.11+ and PyYAML 6.x.

Run the tests:

```bash
python3 -m unittest discover \
  architecture/spikes/ADR-Platform-030/harness/tests -v
```

Canonicalize a fixture:

```bash
python3 architecture/spikes/ADR-Platform-030/harness/ok141_harness.py \
  canonicalize \
  --profile openkubes-contract-c14n/v1 \
  --schema architecture/spikes/ADR-Platform-030/harness/schema/contract-v1.schema.json \
  --input architecture/spikes/ADR-Platform-030/harness/fixtures/contracts/base.yaml \
  --normalized-output /tmp/contract.canonical.json \
  --manifest-output /tmp/canonicalization.json
```

All output paths must be explicit. Tests use temporary directories.

Verify the Phase-R execution fixture:

```bash
python3 architecture/spikes/ADR-Platform-030/harness/ok141_harness.py \
  verify-fixture \
  --root architecture/spikes/ADR-Platform-030/harness \
  --input architecture/spikes/ADR-Platform-030/harness/fixtures/execution/phase-r-v1.json
```

The checked-in fixture remains `NO-GO`; successful offline verification does not
authorize an apply or any other infrastructure mutation.
