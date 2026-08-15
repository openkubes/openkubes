# OK-141 M0b TokenRequest and anti-replay v1

This offline checkpoint proves the two mechanisms left outside the stateless
registration materializer:

1. burn a one-run grant before token issuance by creating a mode-`0600`
   receipt with `O_EXCL`;
2. issue one bounded TokenRequest and transfer its bearer token only through an
   inherited anonymous pipe or socket.

The utility suppresses raw `kubectl` output and never prints, hashes, or writes
the token to a regular file. Its receipt contains only grant identity, candidate
digest, timestamp, and state.

The anti-replay claim is intentionally DEV-bounded: the utility fails closed
while the receipt exists, but it cannot prevent an external actor from deleting
or replacing that non-WORM receipt. A failed attempt after receipt creation
consumes the grant and does not authorize retry.

```text
Offline checks:       12 PASS
Real credentials:     not used
Cluster contact:      none
TokenRequest:         NOT GRANTED
Target registration: NOT GRANTED
GO-1:                 NOT GRANTED
```

Run:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-tokenrequest-antireplay-v1/test_tokenrequest_antireplay_v1.py
python3 architecture/spikes/ADR-Platform-030/m0b-tokenrequest-antireplay-v1/verify_m0b_tokenrequest_antireplay_v1.py
```
