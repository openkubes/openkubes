# OK-205 — Source claim review (2026-10-20)

**Review stage:** technical evidence inspection, **not human publication approval**.

## Immutable evidence baseline

Repository: `openkubes/ok-local`  
Commit: `60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e`  
Document: [docs/tutorial-basic.md](https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md).

At the end of the **What's next** section, the document explicitly describes an OpenKubes automated local dev environment named `ok-local`. This supports the core subject and existence claims in both currently proposed manifest entries. The phrase **fully automated** is present; this is documentation evidence, not an independently executed end-to-end product test.

| Question ID | Existing answer | Evidence assessment | Decision |
| --- | --- | --- | --- |
| `ok-local-definition` | OpenKubes Local (ok-local) is a fully automated local development environment provided by the OpenKubes project. | The pinned tutorial's closing OpenKubes reference describes a fully automated local dev environment (`ok-local`). | Source supports the answer wording; human review remains required. |
| `ok-local-availability` | Yes. OpenKubes provides a fully automated local development environment called ok-local. | Same explicit closing OpenKubes reference. | Source supports the answer wording; human review remains required. |

### Important scope caveat

The bulk of `tutorial-basic.md` is a **single-node KubeVirt on macOS / Multipass exercise**, not a complete end-to-end tutorial of the multi-cluster `ok-local` environment. Do not cite its main exercise as proof that the complete platform stack was deployed or validated.

## Additional candidate intents (not released)

1. **Local prerequisites** — [docs/tutorial-prerequisites.md](https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-prerequisites.md): covers Mac host requirements and required tools. Proposed narrowly scoped wording: “The documented macOS prerequisites include Multipass, kubectl, Git and an SSH public key; see the pinned prerequisites guide for versions and setup.” Verify intended supported OS scope before approval.
2. **Introductory KubeVirt exercise** — [docs/tutorial-basic.md](https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md): shows Multipass VM, K3s and KubeVirt on a Mac. Proposed wording: “The basic tutorial demonstrates K3s and KubeVirt in a Multipass VM on macOS; it is not the complete multi-cluster ok-local setup.”
3. **CAPI tutorial** — [docs/tutorial-capi.md](https://github.com/openkubes/ok-local/blob/60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-capi.md): documents CAPI and CAPK setup on `ok-mgmt-local` and KubeVirt on `ok-infra-local`. Proposed wording: “The CAPI tutorial installs CAPI with the KubeVirt infrastructure provider on ok-mgmt-local and demonstrates VM management involving ok-infra-local.” Do not imply full workload-cluster lifecycle is already exercised; its later section calls that an advanced follow-up.

## Human review checklist

- Confirm each answer's meaning, not just that URLs resolve.
- Verify documentation reflects the intended product scope and current release.
- Assign named reviewer, review date, and re-review due date to each manifest entry only on explicit approval.
- Add separately pinned citations for new entries, plus positive/negative golden fixtures.
- Run PR CI and accessibility/browser checks; production release requires its own approval.

**No FAQ content has been approved by this inspection, and no widget/release change is requested.**
