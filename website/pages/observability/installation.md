# Installation & Verification

**`ok-cluster` installs the capability; `ok-observability` owns its implementation.**

The supported cluster integration is an explicit, gated `make install-observability` operation, as described by the [`ok-cluster` installer](https://github.com/openkubes/ok-cluster/blob/main/install-observability.sh).

## Before installation

- A target cluster and a suitable kubeconfig must already exist.
- Ensure storage, network/CNI and capacity meet the chosen implementation profile's requirements.
- Use a checked-out `ok-observability` capability source and the pinned revision expected by the installer.
- Supply the required **provider values and credentials** through the documented mechanism. Do not commit credentials, private endpoints or populated provider-value files.
- Determine whether the cluster uses the offline file-based secret profile or the Vault/Vault Secrets Operator path. These are environment choices, not interchangeable command-line shortcuts.

## Operator entry point

From the [`ok-cluster` repository](https://github.com/openkubes/ok-cluster), after configuring the prerequisites and pinned revision:

```bash
make install-observability CLUSTER=my-cluster
```

This is **not** a complete standalone command for an unconfigured machine. Consult the installer and its `OK_OBSERVABILITY_REF`, `OK_OBSERVABILITY_PATH`, `OBSERVABILITY_VALUES` and secret-source requirements before running against a live cluster.

The gated path deploys the selected profile and runs the contract test. Its exit status is the operation's readiness result; inspect individual guarantees and evidence rather than relying only on a green summary.

## Maintainer verification

In a local checkout of [`ok-observability`](https://github.com/openkubes/ok-observability):

```bash
make verify        # deterministic repository checks
make conformance   # cluster-dependent contract gate
make evidence      # evidence summary
```

`make conformance` requires appropriate live-cluster inputs and should not be mistaken for an offline unit test. Verify CNI health separately before interpreting the gate result, as required by [ADR-Platform-027](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-027-observability-gate-assurance-scope.md).

## Reference material

- [`ok-observability` README](https://github.com/openkubes/ok-observability/blob/main/README.md)
- [Provider values template](https://github.com/openkubes/ok-observability/blob/main/provider-values.example.yaml)
- [`ok-cluster` installer](https://github.com/openkubes/ok-cluster/blob/main/install-observability.sh)
- [ADR-Platform-024: Opt-in gated installation](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-024-observability-install-as-opt-in-gated-command.md)
- [Capability Contract](contract.md)

[Back to OK Observability](index.md)
