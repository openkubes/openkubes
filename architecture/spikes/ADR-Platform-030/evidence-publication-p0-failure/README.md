# OK-141 P0 publication failure checkpoint

Status: **P0 attempted once; failed closed; retry not authorized**

The exactly authorized publisher run reached the GHCR publish step only after
the source-run, bundle, binding, transport and ORAS checksum checks succeeded.
ORAS 1.3.3 then rejected the absolute layer path before creating a package.
Attestation and digest pull-back were skipped by the workflow.

The failure is bounded to local transport-path syntax:

```text
absolute layer path
  -> ORAS path validation rejects the push
  -> no GHCR package
  -> no attestation
  -> no pull-back
```

The inert amendment describes the minimal correction: enter the already
trusted runner temporary directory and publish the same verified transport by
relative path. It does not change the transport bytes, destination, tag,
permissions, source-run bindings or protected environment.

The original smoke protocol allowed two Actions runs. C1 and this P0 attempt
consumed both. Therefore this checkpoint grants neither deployment of the
amendment nor a retry. A new exact workflow digest, reviewed deployment gate,
amended run budget and explicit publication authorization are required.

No Kubernetes credentials were present and no DEV infrastructure was read or
mutated. The recorded evidence is redacted and safe for the public Git history.
