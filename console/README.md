# OpenKubes Platform Console prototype

This directory contains the curated, frontend-only prototype from
[OK-153](https://kubernauts.atlassian.net/browse/OK-153), following the graphical
spike in OK-151 and the boundaries proposed in ADR-Platform-036.

> **Contracts. Clusters. Evidence.**

## Run locally

Prerequisites: Node.js 20 or newer and pnpm 9 or newer.

```bash
cd console
pnpm install
pnpm dev
```

Open the local URL printed by Vite. The production-shaped static build is created
with:

```bash
pnpm build
pnpm preview
```

## Verification

```bash
pnpm lint
pnpm test
pnpm build
```

## Prototype boundaries

- All platform content comes from deterministic fixtures in `src/data/fixtures.ts`.
- `ConsoleDataPort` is the narrow replacement seam for a future backend adapter.
- Cluster, Capability, Workload Claim, and Evidence v0 presentation shapes live in
  `src/domain/contracts.ts`.
- Create Cluster is a safe interaction prototype. It sends no request, grants no
  authority, and mutates no cluster or backend.
- Cluster Shell is a simulated diagnostic experience. It keeps cluster, namespace,
  authority, expiry, and evidence context visible, but creates no terminal process,
  WebSocket, credential, kubeconfig, or backend session. A small read-only allowlist
  returns deterministic responses; mutating commands are visibly blocked.
- Authentication, RBAC, live Kubernetes access, deployment, generic schema rendering,
  and AI-driven runtime adaptation are deliberately out of scope.

## Architecture seams

| ADR-036 concern | Prototype location |
|---|---|
| Domain/presentation shapes | `src/domain/contracts.ts` |
| Observed state | `Cluster.lifecycle` and `Readiness` |
| Evidence projection | `EvidenceRef` and Evidence drawer |
| Presentation mapping | curated React views and design tokens |
| Compatibility | `Cluster.compatibility` and visible contract strip |
| Operation invocation | explicitly disabled Create Cluster execution preview |
| Diagnostic session | simulated Cluster Shell with read-only guardrails |

The supported presentation mapping is inspectable as
`console.openkubes.io/v0alpha1`. Unknown compatibility remains read-only and no UI
control is presented as a security boundary.
