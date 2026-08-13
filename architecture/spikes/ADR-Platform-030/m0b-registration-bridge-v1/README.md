# OK-141 M0b registration bridge v1

This is the final offline integration step for M0b runtime registration. It
joins the exact TokenRequest/anti-replay utility and the exact registration
materializer without broadening either component's authority.

The token utility sends the credential through an anonymous pipe. The bridge
adds it to the already validated runtime envelope in memory and sends that JSON
to the materializer through subprocess standard input. Raw child output is
never forwarded. Tests deliberately make both fake `kubectl` invocations echo
the synthetic token and registration payload to standard error; the bridge's
external output and receipt remain clean.

Two reciprocal one-run grants are required. The token grant is burned before
TokenRequest. The materializer grant has no separate durable receipt, but a
second bridge run cannot acquire another token while the first receipt exists.
This claim does not cover externally retained token bytes or deletion of the
DEV non-WORM receipt.

```text
Offline checks:       10 PASS
Real credentials:     not used
Cluster contact:      none
Bridge execution:     NOT GRANTED
Target registration: NOT GRANTED
GO-1:                 NOT GRANTED
```

Run:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-registration-bridge-v1/test_registration_bridge_v1.py
python3 architecture/spikes/ADR-Platform-030/m0b-registration-bridge-v1/verify_m0b_registration_bridge_v1.py
```
