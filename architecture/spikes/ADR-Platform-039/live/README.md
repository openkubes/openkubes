# ADR-039 live proof package

This package is the OK-174 rendered-contract proof harness. It is fail-closed to the
explicit `ok-obs-verify-admin@ok-obs-verify` context selected by `KUBECONFIG`; the
Python harness repeats the Makefile context check before mutation.
It also reads the `kube-system` Namespace UID from that API server and requires the reviewed
`ok-obs-verify` identity pin; a matching context name alone is insufficient.

The coordinator-owned Makefile builds the pinned runtime and fixture images, publishes
the three custom images to the approved zot machine repository, validates immutable
digest references, and drives a live proof. Inference is not hosted in the proof cluster:
the `inference-shared` capability is a reviewed `/32` host route to ok-ai's shared Ollama
(`192.168.100.202:11434`). `OLLAMA_MODEL` is the one model parameter and defaults to
`ok174-gpt-oss:20b`, an alias of the `gpt-oss:20b` that server already serves with `num_ctx`
32768. The server's 4096-token default truncated OpenCode's system prompt and tool list, and
the OpenAI-compatible API cannot raise it per request. An in-cluster Ollama was tried first and
removed: on ok-obs-verify's 4 GiB workers it caused a node SystemOOM and DiskPressure, and
the 1.5b/1.7b models it could hold did not use tools reliably.

`probes/live_proof.py` actions used by Make targets:

```text
render
apply
probe
evidence
clean-workspaces
```

`live-render` is a cluster-free development check. Supply `OK174_REVISION` and it renders
the exact objects and prints their kind, namespace, and name. If the published-image env is
absent, deterministic `example.invalid` digest references are used; these placeholders are
not evidence and cannot be applied. Local rendering is never verification evidence.

Live verification happens only later on `ok-obs-verify`. `probe` executes actual OpenCode and
Codex inference, validates successfully completed JSON edit/exec events for the declared command, runs the source fixture checks, and
exercises authority, network, quota, persistence, and ephemeral controls. It requires the
run ID emitted by `live-apply`. `evidence` serializes that run's candidate and re-verifies it
against the raw transcripts. The transcripts are integrity-bound after capture, not attested by
the cluster. `live-negative` breaks each probe's precondition on a fresh apply and requires the
probe to go red, then green after the revert.

The rendered profile is authoritative. The operational overlays are `imagePullSecrets` and
run/owner labels. The harness also materializes the referenced registry pull Secret, source
credential Secret, and source CA ConfigMap because their per-run values cannot be committed.
All five differences are recorded in the overlay/mismatch evidence; the final verifier independently
rerenders the documents, binds the documents/renders/applied objects/overlay ledger by digest,
and rejects unexpected live readback drift, including Namespace drift. `storageClassName` belongs in the reviewed profile. Persistent
`local-path` requested capacity is not enforced; the storage proof is a
`ResourceQuota` rejection naming `requests.storage` plus ephemeral `emptyDir.sizeLimit`
eviction. The ephemeral render is read back before pressure, and eviction must name the
`workspace` volume and its `8Mi` limit.

Fixture access is selected by namespace and pod selectors for `ok174-proof-services`; no
caller-supplied CIDRs or public broad ranges are used. The run owns only
`ok174-proof-services`, `dw-ok174-proof`, `dw-ok174-ephemeral`, and `ok174-evidence`.

Credentials are supplied through stdin or an inherited file descriptor and Kubernetes Secret
references. The Git canary is checked against manifests, harness argv, the runtime-writable
mounts of both runtime pods and the ephemeral pod, captured output, and Pod logs without placing the value in argv or evidence. Checkout and
runtime use separate `/tmp` and home `emptyDir` volumes, and log custody requires zero container
restarts. The fixture rejects absent and wrong per-run Git tokens. This is a bounded scan and does
not prove that a malicious runtime could not exfiltrate a credential to an allowed endpoint.

The workspace source revision is the fixture's observed `knownCommit`. The evidence separately
binds that checkout commit, the clean implementation Git revision, and all approved image digests;
it does not contain a build attestation proving those images were built from that revision.
OpenCode and Codex runtime conformance therefore applies to the recorded image digests.

## System requirements

These are the resources the proof actually needed on `ok-obs-verify`, and what failed below them.

**Workspace cluster**
- Kubernetes v1.34 (tested with v1.34.1) and a CNI that enforces NetworkPolicy, including
  `ipBlock` egress to an external host (tested with Cilium).
- A StorageClass for the persistent workspace (tested with `local-path`, which does not enforce
  requested capacity), and kubelet ephemeral-storage accounting so an `emptyDir.sizeLimit`
  evicts.
- Nodes that can pull from the private registry with its CA trusted (Talos registry trust here).

**Per workspace**
- 500m CPU and 1Gi memory. OpenCode was OOM-killed at 512Mi once the model made real tool calls.
- A 1Gi persistent volume. The quota admits exactly one workspace pod, so the Deployment uses
  `Recreate`.
- Node disk for the runtime images: OpenCode about 1.04 GB, Codex about 0.96 GB, fixture about
  0.37 GB. On 12.6 GiB worker disks, repeatedly replaced image digests caused DiskPressure.

**Inference**
- An OpenAI-compatible endpoint whose model makes native tool calls, with at least a 16k–32k
  context. Tested: Ollama 0.31.1 on a GPU host with `gpt-oss:20b` at `num_ctx` 32768, using
  12.9 GB of VRAM at about 61 tokens/s.
- Before a run, create the alias on the inference server, and delete it afterwards:
  `curl <server>:11434/api/create -d '{"model":"ok174-gpt-oss:20b","from":"gpt-oss:20b","parameters":{"num_ctx":32768}}'`
  and `curl -X DELETE <server>:11434/api/delete -d '{"model":"ok174-gpt-oss:20b"}'`.
- Not sufficient: Ollama inside a cluster of 4 GiB workers, which caused a node SystemOOM; the
  1.5b and 1.7b models, which did not use tools reliably; and the server's default 4096-token
  context, which truncated OpenCode's system prompt and tool list.

**Runtimes**
- Codex runs with `--sandbox danger-full-access`. Its Landlock/seccomp sandbox refused every
  command inside the non-root, capability-dropped pod, so the pod is the sandbox.

**Operator workstation**
- `kubectl`, `git`, `openssl`, and Python 3 with PyYAML and `jsonschema`.
- Docker to build the images. If the local Docker cannot resolve or trust the registry, push
  with a `skopeo` container that is given the registry address and CA.

## Rollback and retention

`live-clean` delegates to `clean-workspaces` and requires all of: `APPROVE_LIVE_CLEANUP=yes`,
an explicit `KUBECONFIG`, the exact target context, and the 24-hex `OK174_RUN_ID` emitted by
the corresponding apply. Cleanup reads the run ledger and deletes only its namespaces with a
UID precondition, so a recreated namespace is not deleted. It deletes ticket-owned live
resources and workspace-scoped credentials; it does not delete published proof images. Keep
those images until merge.

## Evidence status

`evidence/live-evidence-v1.yaml` is the current evidence: run `a57e1ff2733802b6010a3ede`, 18/18
effects. `evidence/negative-controls-v1.yaml` is the fail-on-purpose run `0882f260441814da5b74be15`: all
seven controls went green, then red on their live fault, then green after the revert. Both ran
against implementation `implementationTreeSha256: 200ee3c295b0d43522989286d3fedc0696c8f84ae18ba6d13c372bfa8a4b5e93`, a
content hash of every implementation file in this spike, so they stay checkable after a rebase
or squash merge. `evidence/raw/<run-id>/` holds their hash-bound transcripts, reduced at capture
time to the fields the verifier needs. Regenerate the evidence only with `live-apply`,
`live-probe`, `live-evidence` and `live-negative` from a clean tree; never edit it by hand.
