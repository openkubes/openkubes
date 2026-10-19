# Your First AI Coding Workspace

!!! warning "Reference implementation — not production-ready"
    ADR-Platform-039 is **Proposed**. This tutorial demonstrates one bounded fixture task on a disposable cluster. It does not establish general agent capability, performance, hostile multi-tenant isolation, or production readiness.

## What you will do

Create a persistent OpenCode workspace, ask the agent to change a fixture README, independently check the result, and remove the workspace. The model runs on an external inference host; the OpenCode client and its shell tools run inside the workspace Pod.

This is a beginner's hands-on path **after a platform operator prepares the disposable environment**. It is not a laptop cluster installer. If you are starting with a laptop, read [Running locally?](#running-locally) first.

**Validation & reproducibility:** validated on a disposable Talos cluster, with **39/39 checks passing**. Read the [security and storage boundaries](#security-and-storage-boundaries) and [local-environment limitations](#running-locally) before continuing. The [canonical README][readme], [Makefile][makefile] and [harness][harness] remain authoritative for commands and refusal behavior. Optional [technical validation and evidence](#technical-validation-evidence) records the exact revisions and run details.

## Prerequisites and supported environment

**Tested environment:** a fresh, disposable **Talos/KubeVirt guest**, Kubernetes **1.34.1**, Crossplane **2.3.3**, Cilium enforcing NetworkPolicy, and the `ok-storage-local-quota` StorageClass. This tutorial assumes a dedicated guest because installation and uninstallation change cluster-wide components.

Ask your operator to provide:

| Requirement | Why it matters |
| --- | --- |
| An allowlisted disposable context and its kubeconfig | The harness checks context and cluster identity before operating. A context name alone is not authorization to use a shared cluster. |
| Verified `ok-storage-local-quota` storage | OpenEBS hostpath with XFS project quotas must enforce bytes at runtime. A PVC request alone is insufficient. |
| Working user namespaces | Workers need kernel/runtime support, idmap-compatible storage and `user.max_user_namespaces > 0`. The reference setup uses the cluster's `workloadUserNamespaces` opt-in; Talos defaults the sysctl to zero. |
| A NetworkPolicy-enforcing CNI | It must enforce the profile's egress rules, including `ipBlock`. Policy objects existing in the API is insufficient. |
| Reachable registry, trusted CA and digest-pinned images | Supply the approved runtime and fixture image references. Private images also need a pull-only identity and a protected password file. |
| Reviewed inference host and tool-calling model | The selected catalog must route to a reachable OpenAI-compatible endpoint and model alias. A small chat-only model is insufficient for this task. |
| Operator terminal tools | Bash, Python 3 with PyYAML, kubectl, make, Helm, git, curl and sha256sum; the installer obtains the pinned Crossplane chart. |

**Proposed preparation for your environment:** have the operator follow the [canonical prerequisites][readme] and verify storage and worker user namespaces before continuing. The [storage implementation][storage] and [cluster implementation][cluster] are pinned to the revisions used by the recorded run. Installing those dependencies is deliberately outside this beginner path.

## 1. Select a profile and protect the target

**Tested selection:** the [enforcing local-quota profile][quota-profile] declares `hostUsers: false`, `runtimeEnforced: true`, and `ok-storage-local-quota` as capacity-enforcing. The runtime proof requires a nonidentity UID map and bounded persistent writes.

The [local-path profile][path-profile] instead declares `hostUsers: true` and `runtimeEnforced: false`. It is an **observed-negative** development profile: request quotas still limit PVC admission, but persistent byte capacity and user-namespace isolation are not guaranteed. Historical negative evidence recorded a 1 GiB workspace writing 1280 MiB. **Proposed alternative for this tutorial:** selecting local-path was not part of the final-main hands-on run. Do not use it to claim the enforcing result.

**Proposed setup template (not exercised in the recorded run; replace placeholders before use):** in Bash, from the operator-supplied repository checkout, replace each placeholder with reviewed values. The context shown is the one used in the tested run; a new cluster must satisfy the harness's explicit allowlist. Do not rename an unrelated context to bypass it.

```text
cd platform/workspace/developer-workspace/crossplane
export KUBECONFIG='<disposable-guest-kubeconfig>'
export TARGET_CONTEXT='ok-178-ws-admin@ok-178-ws'
export OK175_TARGET_UID_SHA256="$(kubectl --context "$TARGET_CONTEXT" get ns kube-system -o jsonpath='{.metadata.uid}' | sha256sum | cut -d' ' -f1)"
export OK176_PROFILE_FILE="$PWD/profiles/namespace-profile-local-quota.yaml"
export OK175_RUNTIME_IMAGE='<approved-registry/runtime@sha256:digest>'
export OK175_FIXTURE_IMAGE='<approved-registry/fixture@sha256:digest>'
```

`KUBECONFIG` must name exactly one readable file whose **current context** is `TARGET_CONTEXT`; the harness reads the current context, not `--context`. The UID hash intentionally has no added newline. Confirm the guest's identity independently before computing it. Keep these settings for cleanup. Image digests in the [live-proof record][live-evidence] (its `images` key) identify the tested artifacts; a digest alone does not supply registry access.

**Proposed private-registry input template** (the pull-only descriptor mechanism was tested):

```text
export OK175_REGISTRY_USERNAME='<pull-only-user>'
export OK175_REGISTRY_PASSWORD_FD=3
```

Keep the password out of command arguments and logs. In the next commands, replace `<protected-password-file>` with the operator-provided file; descriptor 3 must be reopened on every invocation. For anonymous image pulls, omit these variables and the descriptor redirection.

## 2. Install the capability

**Tested (exercised in the recorded run):** from the same directory and terminal:

```bash
make live-install
```

This installs and observes four admission policies and Deny bindings before enabling the XRD and Composition. It exercises allowed and denied dry-runs and writes an installation receipt only after the gate succeeds. A missing or invalid receipt prevents new provisioning. It does not continuously attest policy health: operators must preserve the admission configuration after installation.

**Tested, optional full proof:** the recorded 39/39 run used:

```bash
make live-run REQUIRE_CLEAN=1 3< '<protected-password-file>'
```

This performs destructive lifecycle tests on its own fixtures and cleans them up. It leaves no usable workspace and does **not** rerun OpenCode inference. Its final JSON under `evidence/` is the proof record; preserve it. Use clean reviewed implementation inputs for this command.

## 3. Understand the OpenCode model configuration

**Tested:** the runtime entrypoint generates OpenCode configuration from the selected profile catalog's `OK174_INFERENCE_BASE_URL` and `OK174_MODEL`. You do not need to type model credentials into the workspace. The profile routes inference to **a reviewed inference host** and permits its egress; changing OpenCode's model name alone does not change that network capability.

The tested catalog alias is `ok174-gpt-oss:20b`, derived from `gpt-oss:20b` with `num_ctx: 32768`. The operator created the alias before `live-up` and confirmed it in Ollama's model list. **Proposed endpoint template for that tested operation**, run by the inference operator:

```text
curl --fail-with-body 'http://<reviewed-inference-host>:11434/api/create' \
  -d '{"model":"ok174-gpt-oss:20b","from":"gpt-oss:20b","parameters":{"num_ctx":32768},"stream":false}'
curl --fail-with-body 'http://<reviewed-inference-host>:11434/api/tags'
```

The alias must appear in the list. The [runtime implementation][runtime] defines configuration generation. One task with this alias does not establish that arbitrary prompts or other models work.

## 4. Start your workspace

**Proposed ledger-location template; tested lifecycle operation:** choose an absolute path on writable storage that survives a reboot, and create its parent directory. For example, `$HOME/.local/state/developer-workspace/hands-on.json` is a possible location. The recorded run used its own persistent ledger location.

```text
export OK180_STATE_FILE='<absolute-persistent-ledger-path>/hands-on.json'
mkdir -p "$(dirname "$OK180_STATE_FILE")"
make live-up 3< '<protected-password-file>'
```

`live-up` prints **Workspace**, **Namespace**, **Runtime Pod**, and a task-execution example. Its tested example has this shape (substitute the current printed values):

```text
kubectl --context <context> exec -n <namespace> pod/<runtime-pod> -c runtime -- sh -c 'cd /workspace && opencode run --format json <quoted task> && sh verify.sh'
```

Use the exact printed command if running a task directly; its quoting matters. For the step-by-step task below, **proposed interactive-shell convenience** (the recorded task used noninteractive execs):

```text
kubectl --context "$TARGET_CONTEXT" -n <namespace> exec -it <runtime-pod> -c runtime -- sh
cd /workspace
```

The workspace is `Ready` when checkout succeeds and the Deployment has an available replica. That status alone does not certify all isolation guarantees.

## 5. Check isolation, then run the agent task

**Tested checks:** in the operator terminal, use the Namespace and Runtime Pod printed by `live-up`:

```bash
kubectl --context "$TARGET_CONTEXT" -n <namespace> get pod <runtime-pod> \
  -o jsonpath='{.spec.hostUsers}{"\n"}'
kubectl --context "$TARGET_CONTEXT" -n <namespace> exec <runtime-pod> -c runtime -- \
  cat /proc/self/uid_map
```

Expect `false` and a **nonidentity UID mapping**: container UID 0 maps to a nonzero host UID, rather than host UID 0. The recorded mapping was `0 242614272 65536`; your host range may differ. Stop if these expectations fail.

**Tested fixture task:** inside the runtime shell, first run:

```sh
cd /workspace
sh verify.sh
```

**Proposed observation template:** `git status --short` may also be run before the task.

The initial verification must exit **1**, because the fixture has not been modified. The added initial Git status observation is **proposed**; the recorded Git status was taken after the task. An already modified fixture is not the same before/after experiment.

Use this exact deterministic prompt from the [canonical task implementation][task]. An open-ended prompt previously stopped without editing.

```sh
TASK=$(cat <<'TASK_EOF'
You are in /workspace. Make exactly two shell tool calls, one per command, each command exactly as written with nothing added, removed or combined. Call 1: printf '%s\n' 'developer workspace fixture modified by agent' > README.md Call 2: sh verify.sh Then report both exit codes.
TASK_EOF
)
opencode run --format json "$TASK"
```

Expect **two shell tool calls**, both with exit code **0**. Independently check the result:

```sh
sh verify.sh
git status --short
```

Expect verification exit **0** and ` M README.md`. A successful OpenCode process alone is insufficient. Save the task output, before/after verification exit codes, Git status and user-namespace observations before cleanup. `live-up` and `live-down` do not write evidence themselves.

## Security and storage boundaries

**Tested scope:** the lifecycle proof checks admission, rendered resources, drift correction, discovery-only workspace authority, sampled Kubernetes API unreachability, read-only source access, CPU throttling, memory limits, ephemeral eviction, PVC admission quota, persistent byte enforcement and cleanup. The enforcing capacity check requires ENOSPC/EDQUOT with allocation and filesystem capacity within 1 MiB of the declared size, plus a rejected owned-file project-ID reset. It is not a proof of every filesystem operation, quota bypass, reboot or adversarial attack.

**`live-up` does not perform the UID-map check or the sampled Kubernetes API unreachability probe that `live-run` performs.** A Ready workspace can therefore lack intended guarantees on an unsuitable cluster. The manual UID checks above address the hands-on Pod; run the full proof on the selected environment before claiming the full boundary. A NetworkPolicy manifest alone proves no network isolation.

The runtime receives no mounted Kubernetes token or source push credential. Source authentication and CA are mounted into checkout, not the runtime. Provider-kubernetes has broad platform authority; it is not the workspace identity. Operators control catalog, admission and Namespace labels. A Namespace is not a VM boundary, and declared resource limits are not platform-wide maxima.

Persistent data survives Pod replacement, **not workspace deletion**. Export work products through an approved operator process first. `evidence.exportBeforeCleanup`, idle timeout, retention and after-retention deletion declarations do not implement export or automatic cleanup.

## 6. Remove the workspace safely

**Tested:** exit the runtime shell, return to the operator terminal and use the same environment and ledger:

```bash
make live-down
```

The ledger records cluster identity, a run nonce and created object UIDs. Cleanup checks UID and ownership markers and uses UID/resourceVersion delete preconditions. It waits for the workspace Namespace, composed Objects and PV to disappear. It refuses foreign, replaced, unmarked or ambiguous objects and missing ownership evidence. A second `live-up` with an existing ledger is refused: **do not erase the ledger to retry**.

**Proposed manual recovery — not exercised in the final-main run:** inspect the named object's UID and `workspace.openkubes.io/hands-on-run` annotation against the ledger. An intent without a recorded UID is ambiguous even if its nonce matches. The operator must establish ownership independently, then delete with a UID precondition using the API path appropriate to that resource:

```text
kubectl --context "$TARGET_CONTEXT" get <kind> <name> -o yaml
kubectl --context "$TARGET_CONTEXT" delete --raw '<resource-api-path>' -f - <<'DELETE_EOF'
{"preconditions":{"uid":"<confirmed-owned-uid>"}}
DELETE_EOF
make live-down
```

Never authorize deletion by name or timestamp alone. Leave foreign objects untouched. Remove the ledger only after all owned objects are gone. See [manual recovery in the README][readme] for ownership and PV-chain details.

## 7. Teardown and cleanup

**Tested:** after `live-down` succeeds, and with no remaining DeveloperWorkspaces:

```bash
make live-uninstall
```

It refuses while DeveloperWorkspaces remain. Uninstallation removes this capability, provider, functions, Crossplane and remaining Crossplane-group CRDs; use it only on the disposable target. A successful `live-run` already deleted its test workspaces. **Proposed recovery:** if another workspace remains, identify its owner and export its data before an operator removes it; do not blindly delete all workspaces.

**Proposed operator-specific cleanup templates:** after guest-side cleanup, the operator removes quota storage from the storage repository, then tears down the guest from the cluster repository. Keep the guest kubeconfig and UID guard until guest-side cleanup is complete.

```text
# From the pinned storage repository:
LOCAL_QUOTA_REMOVE=yes make local-quota-remove \
  LOCAL_QUOTA_GUEST_KUBECONFIG='<guest-kubeconfig>'
# From the pinned cluster repository:
make teardown CLUSTER='<disposable-cluster-name>' CONFIRM=yes \
  TALOS_INFRA_KUBECONFIG='<infrastructure-kubeconfig>'
```

Storage removal refuses while a PVC or PV references the class and retains the provisioner Namespace. Teardown removes the guest and its render directory, including Retain-policy disk cleanup. If teardown reports incomplete cleanup, fix the reported cause and repeat it; do not discard the retained recovery records. After successful teardown, the operator removes the exported guest kubeconfig and any separately exported talosconfig.

**Tested alias removal, proposed endpoint template:** remove only an alias created for this disposable exercise, after coordinating with its owner:

```text
curl --fail-with-body -X DELETE 'http://<reviewed-inference-host>:11434/api/delete' \
  -d '{"model":"ok174-gpt-oss:20b"}'
```

Confirm it is absent from the model list. Preserve exported work and proof records independently of the removed guest.

## Troubleshooting

**Proposed responses:** these remedies are guidance, not additional tested recovery scenarios. Quoted harness errors below exist in the pinned code; external-service and runtime observations are explicitly symptoms.

| Error or symptom | Next action |
| --- | --- |
| `OK180_STATE_FILE must name an explicit absolute path` | Set an absolute persistent ledger path; reuse it for cleanup. |
| `OK180_STATE_FILE parent is not a writable directory: ...` | Create the parent directory with write access for your user. |
| `current context '...' is not the selected disposable target` | Switch the kubeconfig's current context to `TARGET_CONTEXT` (an allowlisted disposable context); `--context` alone is not enough. |
| `OK175_TARGET_UID_SHA256 does not match the kube-system UID of the selected cluster` | Confirm the intended guest and recompute the hash without a newline. Finish guest cleanup before teardown. |
| `registry password descriptor is empty`, or `OSError: [Errno 9] Bad file descriptor` | Reopen the protected password file as descriptor 3 with the pull-only identity. |
| `capability directory or spike inputs have uncommitted changes` | Supply clean reviewed implementation inputs for `REQUIRE_CLEAN=1`; preserve your work first. |
| `runtime lacks python3 or perl required for the exact FS_IOC_FSSETXATTR errno probe` | Use an approved runtime digest with one of these supported probe tools. |
| `DeveloperWorkspaces still exist; delete them first` | Complete ownership-checked workspace cleanup and wait for volume removal before uninstalling. |
| **Symptom:** OpenCode reports HTTP 404 during model lookup | Ask the inference operator to confirm the catalog alias exists and matches the generated configuration. |
| **Symptom:** OpenCode exits without changing the fixture | Use the exact two-call prompt, inspect tool exits, and independently run verification and Git status. |
| **Symptom:** Pod sandbox or idmap mount creation fails | Verify worker user namespaces and the storage BasePath; local-path on the reference Talos setup cannot supply the enforcing mount. |
| **Symptom:** quota provisioner is not Ready or storage verification fails | Have the operator check image pulls and XFS project quotas before retrying. |
| **Symptom:** `live-down` refuses ownership or teardown is incomplete | Preserve the ledger and recovery records; follow UID-based recovery rather than name-based deletion. |

## Running locally?

**This hands-on workflow is proven only on disposable Talos clusters.** There is **no recorded run on ok-local (K3s/Multipass on macOS), kind, or Docker Desktop**. A kind context in the harness allowlist is not evidence that this workflow works there. Talos evidence does not transfer to kind.

**The enforcing profile cannot run locally in the assessed setups.** They lack the verified XFS project-quota storage and user-namespace/idmapped-mount prerequisites. ok-local is a K3s/Multipass environment, not kind; Docker Desktop is a separate reference environment.

**Proposed local trial, not exercised:** an operator would need a separately reviewed observed-negative profile, an explicitly allowlisted disposable context, reachable digest-pinned images and registry trust, a reachable OpenAI-compatible endpoint with a tool-calling model, and a CNI whose egress enforcement, including `ipBlock` rules, is verified separately; the live proof samples only Kubernetes API unreachability. A bundled small chat model is insufficient. Check host kernel, runtime, storage mounts and available memory rather than assuming desktop Kubernetes provides the Talos setup.

Starting from local-path would lose the persistent byte-capacity guarantee and user-namespace isolation. Network isolation remains unproven until exercised on that CNI. CPU, memory and ephemeral limits, admission guards, receipt gating, RBAC, PVC request quotas and API-server-mediated drift correction would all need a fresh local run before any local claim. This tutorial supplies no tested local installation recipe.

## Technical validation & evidence

**Source pin:** current merged `origin/main` when this tutorial was prepared is
`944b1dd17a0418f61008e3bdc65b8849f7bf42af`. All OpenKubes repository links in this tutorial use that immutable commit. Use a checkout of that revision supplied by your operator. The [canonical README][readme], [Makefile][makefile] and [harness][harness] define the commands and refusal behavior.

**Evidence labels used throughout:**

- **Tested** means the operation was exercised in the **2026-10-18 final-main run**, at implementation commit `8a5123bd6c1933c4147e41b286d19198efab80b3`. The results are in the [live-proof record][live-evidence] (`evidence/live-ok-178-ws-933f69ab290b2fd0.json`, 39/39 checks) and the [hands-on evidence][hands-on-evidence] (`evidence/hands-on-ok-178-ws-2026-10-18/`); the [live-proof section][proof] and [hands-on section][hands-on] of the README describe how they were produced. The source pin above is newer; these labels do not claim a new run at that pin.
- **Proposed** means an instruction or recovery path was not exercised in that run. Placeholder values must be supplied by your operator; commands containing placeholders are templates, not copy-and-run commands.

[Back to Developer Workspace](index.md)

[readme]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/README.md
[makefile]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/Makefile
[harness]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/tests/live/reconcile_proof.py
[proof]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/README.md#live-proof-disposable-clusters-only
[hands-on]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/README.md#hands-on-opencode-quickstart
[live-evidence]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/evidence/live-ok-178-ws-933f69ab290b2fd0.json
[hands-on-evidence]: https://github.com/openkubes/openkubes/tree/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/evidence/hands-on-ok-178-ws-2026-10-18
[quota-profile]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/profiles/namespace-profile-local-quota.yaml
[path-profile]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/platform/workspace/developer-workspace/crossplane/profiles/namespace-profile-local-path.yaml
[runtime]: https://github.com/openkubes/openkubes/tree/944b1dd17a0418f61008e3bdc65b8849f7bf42af/architecture/spikes/ADR-Platform-039/live/runtime/opencode
[task]: https://github.com/openkubes/openkubes/blob/944b1dd17a0418f61008e3bdc65b8849f7bf42af/architecture/spikes/ADR-Platform-039/live/probes/live_proof.py
[storage]: https://github.com/openkubes/ok-storage/blob/e24edcb10822922b3942eab5de81c9cd5b9f0183/README.md
[cluster]: https://github.com/openkubes/ok-cluster/blob/751163d35438c6f330b3ea2f68ea8ab92a89ebc4/README.md
