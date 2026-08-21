# OK-141 fresh-run authorization boundary v2

This checkpoint derives the exact first mutating-stage authorization request
from the merged `fresh-run-v2` package. It deliberately does not create a
private key, signature or executable grant.

The candidate binds:

- the complete staged-plan digest and Phase-R v6 R/E/P/Fixture identities;
- Stage 1 `provider-prerequisites`, its canonical stage digest, operation and
  `ok-infra` authority role;
- an explicit empty predecessor set and single-use limit;
- the published runner image and its verified publication receipt.

The private authority may later replace the runtime placeholders only after a
separate live-window decision. The resulting Ed25519 grant may be valid for at
most 30 minutes and exactly one consumption. Every later mutating stage needs a
new grant bound to its verified predecessor receipt.

```text
candidate generated/reviewed != key generated != grant signed != stage run
```

Generate and verify offline:

```bash
python3 generate_authorization_candidate_v2.py
python3 verify_authorization_candidate_v2.py
python3 -m unittest -v test_authorization_candidate_v2.py
```

Bound checkpoint:

```text
fresh-run manifest:  sha256:c2c4c0b1e823347deaa44327b58b634554061233dfd6842bd7664028a5531501
plan:                sha256:d43288bd0f8fa68938783b9dbf6d8e09424f5143b82e6b5652a225d7991caf95
stage-1 request:     sha256:e63c315ee63eae2fe6afdf21824796f7932629605cda76a35f2bae845badf887
candidate:           sha256:701ce016b93f08654a318f9fe0e5d87aa17234c78a11befa589753f617c5e1a8
authorization:       NO-GO
```
