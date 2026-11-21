# Getting Started with OpenKubes OK CLI v1.0.1

> **Release status:** v1.0.1 Community Release (15 November 2026). This is a Community Preview, not a production certification. The release artifacts are not signed, notarized or attested; verify the SHA-256 against the official release information before installation.

This tutorial introduces the `ok` command-line interface and walks through its supported first-cluster workflow. It assumes that you already have access to a **prepared Kubernetes management cluster** that meets the OpenKubes Same-Plane Talos/KubeVirt requirements.

The CLI runs on your workstation. The workload cluster is created as Talos VMs on the existing management cluster. These are two separate roles: installing `ok` does not install Kubernetes or prepare the management plane.

## What you will learn

1. Install and verify the `ok` CLI v1.0.1.
2. Explore its command surface and local configuration.
3. Understand the management-cluster prerequisites.
4. Create and inspect a read-only workload-cluster plan.
5. Provision a Talos/KubeVirt workload cluster with explicit confirmations.
6. Independently verify the workload and, when finished, destroy it with the same CLI version.

## 1. Understand the architecture and prerequisites

The supported v1.0.1 provisioning workflow is **Same-Plane Talos/KubeVirt**: the existing Kubernetes management cluster also hosts the workload-cluster VMs.

Before starting, arrange:

- An authorized management kubeconfig for the intended management cluster. It must be a private regular file with mode `0600` (or stricter) and contain a valid current context.
- A prepared management cluster with the required CAPI/Kubeadm and KubeVirt infrastructure, storage and networking integrations, CDI, cert-manager, Talos controllers and the reviewed Talos Golden Image prerequisites.
- Runtime tools available on the workstation: Git, Make, Python 3 with PyYAML, kubectl, clusterctl and Helm.
- An approved, disposable environment and identity for a first live provisioning exercise. Do not experiment against a shared or production cluster.

**What v1.0.1 does not do:** install or bootstrap the management Kubernetes cluster; install CAPI, KubeVirt, CDI, cert-manager, storage or networking; publish the Talos Golden Image; or acquire management credentials. A generic Kubernetes cluster or a Kind/CAPD development cluster is not automatically a compatible management plane.

### Workstation and workload architecture

The CLI bundle architecture describes the computer running `ok`, not the workload VM architecture.

| Workstation | CLI bundle | Workload architecture in v1.0.1 |
|---|---|---|
| Apple Silicon Mac | macOS ARM64 | AMD64 |
| Intel Mac | macOS AMD64 | AMD64 |
| Linux / WSL2 AMD64 | Linux AMD64 | AMD64 |

Native ARM64 workload provisioning is not supported by v1.0.1, even when the CLI itself runs natively on an Apple Silicon Mac.

## 2. Download and verify the CLI

Download the bundle for your workstation from the [official v1.0.1 release](https://github.com/openkubes/ok-cluster/releases/tag/v1.0.1).

| Workstation | Archive | Official SHA-256 |
|---|---|---|
| Apple Silicon Mac | `ok-v1.0.1-darwin-arm64.tar.gz` | `28e412ea9fa6c116d85caf4650c6449030d17d8b50de9d964c6ed2ee39795d11` |
| Intel Mac | `ok-v1.0.1-darwin-amd64.tar.gz` | `3b69891825e641e1f1dc09c7102b9f8fc82205577d08713341394bb3b1cb5369` |
| Linux AMD64 | `ok-v1.0.1-linux-amd64.tar.gz` | `722c09f3307d70bb5e05a76d93dd685c9fa9918ac2c2ce69a316d3afaee7e694` |

The following example is for Apple Silicon. Substitute the archive and checksum for your platform.

```bash
ARCHIVE=ok-v1.0.1-darwin-arm64.tar.gz
EXPECTED=28e412ea9fa6c116d85caf4650c6449030d17d8b50de9d964c6ed2ee39795d11

printf '%s  %s\\n' "$EXPECTED" "$ARCHIVE" | shasum -a 256 -c - || exit 1

tar -xzOf "$ARCHIVE" "${ARCHIVE%.tar.gz}/ok-cluster/scripts/install-ok.sh" > install-ok.sh
sh install-ok.sh --archive "$ARCHIVE" --sha256 "$EXPECTED" --link

~/.local/bin/ok version
```

On Linux, use `sha256sum -c -` instead of `shasum -a 256 -c -`. The installer verifies the archive again and installs without root under `~/.local/share/ok/`, creating the `~/.local/bin/ok` link if that destination does not already exist. It does not edit shell startup files; add `~/.local/bin` to `PATH` yourself if needed.

The installer intentionally refuses to overwrite an existing installation or link. For macOS browser downloads, account for quarantine only after the checksum has been verified. The release is unsigned: a checksum establishes byte integrity only when the expected value itself was obtained through a trusted channel.

## 3. Explore the CLI

Start with commands that do not provision infrastructure:

```bash
ok version
ok --help
ok config --help
ok up --help
ok cluster --help
ok cluster plan --help
ok destroy --help
```

The root help introduces the main command groups. `ok up` is the supported Same-Plane Talos/KubeVirt operator workflow. `ok cluster plan` validates a request and prints a plan without contacting Kubernetes or invoking Make.

## 4. Configure the management kubeconfig

Set a shell variable to the path of your own management kubeconfig. Do not paste kubeconfig contents into a tutorial, ticket or chat.

```bash
MGMT="$HOME/.kube/management-operator.yaml"

chmod 600 "$MGMT"
kubectl --kubeconfig "$MGMT" config current-context
kubectl --kubeconfig "$MGMT" get nodes
```

Check that this is the intended management cluster. The CLI does not infer its management target from the ambient `KUBECONFIG` variable or the current kubectl context.

Initialize the local CLI configuration:

```bash
ok config init --management "$MGMT"
ok config show
```

Review the displayed bundle/source verification and accept the configuration when prompted. The configuration is create-only: it does not overwrite an existing file.

`ok config init` saves a **path reference**, not the kubeconfig contents. It does not create credentials, create a management cluster, contact Kubernetes or authorize provisioning. `ok config show` is read-only and displays the saved paths plus the running-bundle verification.

## 5. Create a read-only ClusterRequest plan

Create a request file, for example `my-cluster.yaml`:

```yaml
apiVersion: cli.openkubes.io/v1alpha1
kind: ClusterRequest
metadata:
  name: my-cluster
spec:
  profile: talos-kubevirt-reference
  network:
    endpoint: auto
    podCIDR: auto
    serviceCIDR: auto
```

The v1.0.1 reference profile defaults to one control-plane replica and one worker. The supported request allows one control plane and one to ten workers. The profile pins the Talos/KubeVirt reference inputs; it is not a general-purpose provider selector.

Validate the request and inspect the plan:

```bash
ok cluster plan -f my-cluster.yaml
```

This operation is read-only. It validates the YAML and prints the reference plan. It does not reserve a cluster name or IP/CIDR values, contact the management cluster, render manifests, or authorize execution. The local allocation lock does not coordinate allocations between different operators, so coordinate endpoint and CIDR choices with the management-cluster operator.

## 6. Provision the workload cluster

Only continue when you have explicit authorization to create resources in the selected disposable management environment.

Start the guided workflow:

```bash
ok up -f my-cluster.yaml
```

Review the selected management-cluster identity, request, endpoint and network values. The workflow requires two distinct typed confirmations: one for provisioning and another for bootstrap. Read each prompt carefully; do not approve a plan whose target or values you do not recognize.

The CLI verifies its bundled sources and required inputs before running the trusted Make-backed Talos/KubeVirt workflow. It does not silently switch to another kubeconfig or management context. Operations are not automatically retried or cleaned up after an ambiguous failure; preserve the generated state and evidence for diagnosis.

A successful command completion is **not by itself proof that the workload Kubernetes cluster is Ready**.

## 7. Verify the workload independently

Use the workload kubeconfig generated by the CLI. For the example request name:

```bash
WORKLOAD="$HOME/.config/ok/kubeconfigs/my-cluster.yaml"

kubectl --kubeconfig "$WORKLOAD" get nodes -o wide
kubectl --kubeconfig "$WORKLOAD" get pods -A
kubectl --kubeconfig "$MGMT" -n my-cluster get cluster,machines,vm,vmi,pvc
```

Confirm that the expected control-plane and worker Nodes are `Ready`, the CNI and CoreDNS are healthy, and the corresponding CAPI/KubeVirt resources and storage claims have converged. Investigate conditions and events if any expected resource is not ready; do not infer readiness from the CLI exit code alone.

The default workload kubeconfig location is under `~/.config/ok/kubeconfigs/`. Keep kubeconfigs, logs and lifecycle evidence private. Never commit them to Git.

## 8. Destroy the cluster when finished

Use the same CLI version that created the cluster:

```bash
ok destroy my-cluster
```

Review the displayed management identity and UID-bound deletion inventory, then provide the exact confirmation requested by the CLI. Independently verify that the workload namespace and its cluster resources are absent.

Cross-version destruction is not supported. Keep the creating v1.0.1 bundle until its clusters have been destroyed. A destroyed cluster name cannot currently be reused because teardown evidence is retained. Never delete lifecycle evidence, finalizers, namespaces or storage manually to bypass a refusal.

## Troubleshooting and safety

- If `ok config init` reports missing tools or an unverified bundle, stop and resolve that prerequisite before provisioning.
- If the management kubeconfig is not private, fix its permissions and verify the intended context before continuing.
- If a provisioning or bootstrap stage fails, preserve local state and evidence. Do not rerun blindly, remove finalizers or manually delete resources.
- Do not use a Kind/CAPD management cluster as a substitute for the prepared Talos/KubeVirt management profile required by v1.0.1.
- Do not publish kubeconfigs, credentials, raw logs or private evidence reports.

## What comes next

This tutorial uses an existing management plane so that you can focus on learning the OK CLI and its workload-cluster lifecycle.

Future tutorials can cover how to build the management plane itself, how OpenKubes BYOH can provide infrastructure for a compatible management environment, and how native ARM64 workload support can expand the supported architecture matrix. Those capabilities are separate from the v1.0.1 contract documented here.

## References

- [OK CLI v1.0.1 release and assets](https://github.com/openkubes/ok-cluster/releases/tag/v1.0.1)
- [OK CLI v1.0.1 Same-Plane Quickstart](https://github.com/openkubes/ok-cluster/blob/main/docs/cli-v1-same-plane-quickstart.md)
- [OK CLI v1.0.1 release acceptance checklist](https://github.com/openkubes/ok-cluster/blob/main/docs/cli-v1.0.1-release-acceptance.md)
- [OpenKubes ok-cluster repository](https://github.com/openkubes/ok-cluster)
