# OK-141 fresh-run authorization boundary v1

This checkpoint derives the exact first mutating-stage authorization request
from the merged `fresh-run-v1` package. It deliberately does not create a
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
python3 generate_authorization_candidate_v1.py
python3 verify_authorization_candidate_v1.py
python3 -m unittest -v test_authorization_candidate_v1.py
```
