# GO-1 v1 technical blocker summary

> **PUBLIC SANITIZED DERIVATIVE — NOT ORIGINAL EVIDENCE**

The historical read-only analysis concluded that the protocol could not become
executable merely by filling in missing fields. Material desired-state semantics
and prerequisite control-plane mechanisms first had to be reviewed and proven.

## Contract projection

An existing renderer was a plausible implementation mechanism, but its complete
input set and exact rendered object bytes were not bound to the semantic contract.
A safe run required one reviewed object-set identity and an explicitly selected
management target. The runner was not permitted to become a second lifecycle
renderer or reinterpret the contract independently.

## Worker and renderer semantics

Worker count, machine resources, operating-system identity, provider profile, and
upgrade-related choices materially affected the rendered machines. Those values
belonged in the semantic contract and its revision identity, not only in a runbook.

## Enablement mechanism

The proposed enablement API was technically suitable, but its controller installation,
immutable package retrieval, exact projection, compatibility, and recovery behavior
had not been proven. Installing or repairing that controller was outside GO-1.

## GitOps and target registration

The GitOps object model was understood, but control-plane placement, project scope,
target registration, credential lifetime, and recovery were unresolved. A future
protocol needed to correlate the disposable cluster identity with a narrowly scoped
registration without retaining privileged credential material.

## Required sequence

1. Complete the semantic contract and exact renderer projection.
2. Establish and evidence prerequisite enablement and GitOps mechanisms separately.
3. Bind a new protocol identity to those reviewed inputs.
4. Assign independent observers, decision authorities, evidence retention, and
   recovery responsibility before any GO request.

The analysis granted no mutation, installation, credential use, cleanup, retry, or
failure injection.
