# Provenance and sanitization notice

> **This directory contains documentation derivatives, not immutable evidence.**

The source material was an uncommitted historical GO-1 draft, analysis, and checksum
record. The unchanged originals are retained outside public Git working trees under
restricted local access.

## What this public package preserves

- the historical purpose and blocked authorization state;
- the high-level execution and ownership boundary;
- the architectural blockers found by the read-only analysis; and
- the sequencing needed before a later protocol could request authorization.

## What was intentionally omitted

- internal network endpoints, address ranges, and environment layout;
- credential, certificate, CA, kubeconfig, and identity fingerprints;
- private filesystem and raw-evidence paths;
- private evidence identifiers and operational correlation values;
- grants, grant identifiers, decision windows, and operator-specific details; and
- original hashes and digests that could imply byte identity or evidentiary status.

## Usage restrictions

Do not use these summaries to authorize or execute a run. Do not claim that their
content or formatting reproduces the original artifacts. Do not derive an original
checksum from this package. Any future executable protocol requires its own reviewed
identity, prerequisites, evidence boundary, and explicit authorization.

## Publication review checklist

- [x] No internal endpoint or address-range information is present.
- [x] No credentials, fingerprints, private paths, or private evidence identifiers
      are present.
- [x] No operational grant or execution-window information is present.
- [x] Every file is labeled as a sanitized derivative.
- [x] No file claims immutable-evidence or authorization status.
- [x] The restricted archive location is not disclosed.
