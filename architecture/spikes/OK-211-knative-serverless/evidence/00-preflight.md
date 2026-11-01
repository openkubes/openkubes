# 00 — Preflight

- Test IDs: Phase 0 (environment, tooling, version pins, manifests, images, documentation facts). Guard negative tests are added in Phase 1.
- Date (UTC): 2026-10-30T12:56:39Z – 2026-10-30T13:10Z
- Worktree commit: `1b0739fc022418472980c835acaa67021e03192a` (branch `spike/OK-211-knative-serverless`, identical to `origin/main`)
- Environment: macOS 27.0.1 (build 26A434), arm64, 10 CPUs, 24 GiB RAM. No VM exists yet.
- Scope of this phase: read-only. No VM, cluster, package installation or system setting was changed. Only writes: `scripts/fetch-manifests.sh`, this document, `evidence/raw/preflight-*`, and downloads into `.local/`.

## Steps

```bash
# Repository state
git branch --show-current; git rev-parse HEAD origin/main; git merge-base HEAD origin/main
git status --porcelain --ignored; cat .git/info/exclude
shasum -a 256 architecture/spikes/OK-211-knative-serverless/BRIEF.md

# Kubeconfig isolation
echo "$KUBECONFIG"; ls -la "$KUBECONFIG"

# Host
uname -m; sw_vers; sysctl -n hw.ncpu hw.memsize vm.loadavg
vm_stat; memory_pressure -Q; df -h ~
pgrep -x com.docker.backend; docker info --format '{{.MemTotal}} {{.NCPU}}'

# Multipass, SSH, ports
multipass version; multipass get local.driver; multipass list
for f in ~/.ssh/id_ed25519.pub ~/.ssh/id_rsa.pub; do [ -e "$f" ] && echo "exists: $f"; done   # existence only
ssh-keygen -lf ~/.ssh/id_rsa.pub          # fingerprint of the public key only
ssh-add -l                                # key types/comments in the agent, no key material
lsof -nP -iTCP:<6450|6443|6444> -sTCP:LISTEN

# Tooling
command -v <tool>; <tool> --version

# Manifests (BRIEF B4 rule 10)
scripts/fetch-manifests.sh 1.23; scripts/fetch-manifests.sh 1.24; scripts/fetch-manifests.sh cert-manager

# Images — every reference in the downloaded manifests plus the self-referenced ones
oras manifest fetch <ref> | jq '.manifests[].platform'; oras resolve <ref>
#   with ORAS_CACHE and DOCKER_CONFIG under .local/

# Documentation facts — read-only GitHub API calls at fixed refs
gh api repos/<repo>/releases/tags/<tag>
gh api repos/knative/pkg/contents/version/version.go?ref=<pkg commit from go.mod>
gh api repos/knative/docs/contents/docs/versioned/install/upgrade/...?ref=ee1e810129b3
gh api repos/knative/community/contents/mechanics/RELEASE-SCHEDULE.md   # main = 8e1cb276c853
gh api repos/openkubes/ok-local/contents/Makefile?ref=60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e
```

## Observed

### Repository state — PASS

| Check | Expected | Observed |
|---|---|---|
| Branch | `spike/OK-211-knative-serverless` | `spike/OK-211-knative-serverless`, no upstream |
| Base | `origin/main` | `HEAD == origin/main == 1b0739f` (after `git fetch origin main`) |
| Untracked in spike dir | `BRIEF.md`, `.gitignore`, `.local/` | exactly those |
| Repo root | `CLAUDE.md`, `start-claude.sh`, `.claude/settings.local.json` via `.git/info/exclude` | exactly those; `.claude/` shows as ignored |
| Anything else | none | none |
| `BRIEF.md` SHA-256 | recorded for the final comparison (B14) | `fd96141bfd574455d398bcb2f4cefab9594672852315c9f6a6d1c6b8e335fac5` |

The spike `.gitignore` already contains `.local/`, `*.tar.gz`, `*.tgz`, `*.key`, `*.pem`, `*.sock`.

### Kubeconfig isolation — PASS

| Check | Observed |
|---|---|
| `KUBECONFIG` | `<spike>/.local/kubeconfig` (absolute) |
| `KUBECACHEDIR` | `<spike>/.local/kube-cache` |
| File exists | no, `.local/` was empty at start |

Side note: `kn` on this host is a shell alias for `kubens`. Running `kn version` during the tool inventory executed `kubens`, which tried to read the (absent) spike kubeconfig and failed. It made no other access. The Knative CLI `kn` is not installed.

### Host — FAIL (STOP-8)

| Property | Value | Verdict |
|---|---|---|
| Architecture | `arm64` | every image must have `linux/arm64`; all do (see below) |
| macOS | 27.0.1 (26A434) | — |
| CPUs / RAM | 10 / 25 769 803 776 B (24 GiB) | — |
| Load average | 1.73 1.49 1.90 | recorded as a disturbance factor |
| **Available memory (STOP-8 formula)** | (free 12 613 + inactive 302 376 + speculative 496 + purgeable 1 864) = 317 349 pages × 16 384 B ≈ **4.84 GiB** at 12:56Z; second reading at 12:57Z: 319 815 pages ≈ 4.88 GiB | **FAIL — below 10 GiB → STOP-8** |
| `memory_pressure -Q` | "System-wide memory free percentage: 40%" | recorded; the STOP-8 formula governs |
| Docker Desktop | running (`com.docker.backend`), VM memory 12 528 381 952 B (11.67 GiB), 10 CPUs | likely main consumer; not needed for this spike (A1) |
| Free disk | 144 GiB of 926 GiB | PASS (VM needs 40 GiB) |
| bash | GNU bash 3.2.57 | scripts stay bash-3.2 compatible |

### Multipass — BLOCKED (STOP-7)

| Check | Observed |
|---|---|
| `multipass version` | `command not found` |
| `/Applications/Multipass.app`, `/opt/homebrew/bin/multipass`, `/usr/local/bin/multipass` | absent; no Homebrew cask `multipass` |
| `multipass get local.driver`, `multipass list` | not runnable |

**Consequence:** the "before" record of `multipass list` that B12 asks for cannot be captured yet. It will be captured as soon as Multipass is installed, before any `multipass launch`. Without Multipass, `ok-mgmt-local` and `ok-infra-local` cannot exist on this host, so they cannot use memory now either. This contradicts the BRIEF's assumption (A1) that they may be running.

### SSH and ports

| Check | Observed | Verdict |
|---|---|---|
| `~/.ssh/id_ed25519.pub` | missing | — |
| `~/.ssh/id_rsa.pub` | exists, RSA 2048, fingerprint `SHA256:/IFc0mrbcsedgs+IWOWxarVPWB27MQfcIfBGgj1BURc` | this is the key cloud-init will use (same fallback order as ok-local `SSH_KEY`) |
| `~/.ssh/id_rsa` | exists (contents not read) | whether it has a passphrase is unknown |
| `ssh-agent` | one key, type ED25519, comment `dg@kubernauts.de`; **not** the RSA key above | `BatchMode=yes` needs `id_rsa` either unencrypted or loaded in the agent — open question for CP1 |
| Port 6450 | free | PASS |
| Port 6443 / 6444 | free (no ok-local tunnels running) | recorded only |

### Tooling

| Tool | Version | Path | Note |
|---|---|---|---|
| ssh | OpenSSH_10.3p1, LibreSSL 3.3.6 | `/usr/bin/ssh` | |
| curl | 8.7.1 | `/usr/bin/curl` | |
| jq | 1.7.1-apple | `/usr/bin/jq` | |
| yq | v4.53.6 (mikefarah) | `/opt/homebrew/bin/yq` | C10 confirmed |
| helm | v4.3.0 | `/opt/homebrew/bin/helm` | Helm 4: flags will be checked with `--help` (C4) |
| openssl | 3.6.4 | `/opt/homebrew/opt/openssl@3/bin/openssl` | `/usr/bin/openssl` is LibreSSL 3.3.6 |
| shellcheck | 0.11.0 | `/opt/homebrew/bin/shellcheck` | |
| yamllint | 1.38.0 | `/opt/homebrew/bin/yamllint` | |
| oras | 1.3.6 | `/opt/homebrew/bin/oras` | |
| cosign | v3.1.4 | `/opt/homebrew/bin/cosign` | optional, X6 |
| argocd | v3.5.6 | `/opt/homebrew/bin/argocd` | optional, G3 |
| gh | 2.101.0 | `/opt/homebrew/bin/gh` | read-only API calls only |
| git | 2.50.1 | | |
| GNU make | 3.81 | | |
| shasum | 6.02 | | `sha256sum` is not used (C10) |
| kubectl on `PATH` | v1.34.1 | `/usr/local/bin/kubectl` | not used; the spike uses `.local/bin/kubectl` only (C3) |

Missing:

| Tool | Required? | Install command (only after approval, STOP-7) |
|---|---|---|
| **multipass** | **required** | `brew install --cask multipass` |
| kubeconform | optional (`make lint`) | `brew install kubeconform` |
| mermaid-cli (`mmdc`) | optional (Phase 11 SVG) | `brew install mermaid-cli` |
| kn (Knative CLI) | optional, not needed | `brew install knative/client/kn`. It would clash with the `kn=kubens` alias, so the spike would call it by absolute path |
| codex | optional (Phase 12 review) | — |

### ok-local profile — PASS (read at the pinned commit)

The local checkout `../ok-local` is on branch `feature` (`a9de434`), and its local `main` (`9cc1248`) is behind. `git ls-remote origin main` shows `60397cdb2630…`, which matches the BRIEF pin `60397cd`. The checkout was not touched. The pinned files were read through the GitHub API instead (`Makefile`, `docs/tutorial-prerequisites.md` at `60397cd`):

| Item | Value at `60397cd` |
|---|---|
| VM | `multipass launch 24.04 --cpus 4 --memory 8G --disk 40G --cloud-init cloud-init.yaml` |
| K3s | `curl -sfL https://get.k3s.io \| INSTALL_K3S_VERSION=v1.35.5+k3s1 sh -s - --disable=traefik --tls-san=<ip>` |
| cloud-init | `package_update: true`, `package_upgrade: false`, user `ubuntu`, `sudo: ALL=(ALL) NOPASSWD:ALL`, `ssh_authorized_keys` |
| SSH key | `~/.ssh/id_ed25519.pub`, else `~/.ssh/id_rsa.pub` |
| Tunnels | `ssh -L 6443:127.0.0.1:6443 …` / `ssh -L 6444:…`; stopped with `pkill -f "ssh -L 6443"` / `"ssh -L 6444"`. The OK-211 tunnel starts with `ssh -F /dev/null` and does not match these patterns |
| `multipass shell` | "fails with `No route to host`" on recent macOS, use direct SSH (prerequisites doc) |

### Jira OK-211 — read only

The description matches B2 word for word. The ticket has no comments and no links. Status "In Arbeit", assignee Daniel Santiago Gawenda.

### Version pins — resolved

| Component | Pin (B6) | Observed | Verdict |
|---|---|---|---|
| K3s | `v1.35.5+k3s1` | release exists (2026-05-20, not prerelease), asset `k3s-arm64` digest `sha256:aced90be…dbc03`. Newer stable 1.35 patch: `v1.35.9+k3s1`. Not used, per B6 | PASS |
| K3s install script | `raw.githubusercontent.com/k3s-io/k3s/v1.35.5+k3s1/install.sh` | SHA-256 `8598e002e61d658fed7b7542fc6d2c66d8da6eae69e088830105d2ee1ffb6d91`, 1160 lines; git blob `1357d8fe…` equals the blob GitHub reports for that tag | PASS |
| kubectl | v1.35.x | proposed `v1.35.10` (`stable-1.35.txt`); darwin/arm64 SHA-256 from the official `.sha256` file: `77ec066f3404edb81760865c9cd812d03c25e9a89aa0349fd3c1aa60bd5fb068`. Binary not downloaded yet (Phase 2, `make kubectl-pin`) | PASS |
| Knative Serving | `knative-v1.23.0` → `knative-v1.24.0` | published 2026-07-29 and 2026-10-26 | PASS |
| net-kourier | `knative-v1.23.0` → `knative-v1.24.0` | published 2026-07-28 and 2026-10-27 | PASS |
| Knative Eventing | `knative-v1.23.1` → `knative-v1.24.0` | published 2026-10-08 and 2026-10-27 | PASS |
| Knative Operator | "1.23.1, cannot install 1.24" | latest release `knative-v1.23.1` (2026-09-01) | PASS (Annex A holds) |
| cert-manager | `v1.21.3` | published 2026-10-23, assets `cert-manager.yaml`, `cert-manager.crds.yaml` | PASS |
| podinfo 6.16.0 | `@sha256:2c88592f…6d4d` | tag resolves to exactly this digest; `linux/amd64,linux/arm64` | PASS |
| podinfo 6.17.0 | `@sha256:fa2f27c1…efb0` | tag resolves to exactly this digest; `linux/amd64,linux/arm64` | PASS |
| fortio | v1.76.0 by digest | Docker Hub tag is `1.76.0` (a tag `v1.76.0` does not exist) → `sha256:3dd31ddeb4f962a1dae8cc2a0bce62c408ac830c8435bbea51b1e0fd4c8f7181`, includes `linux/arm64` | PASS (tag name deviation noted) |
| curl | `curlimages/curl` by digest | proposed `8.23.0` (latest stable tag) → `sha256:3fb7e13e5d179a845c97d78204f3f1064d1907037f26a3ebf91710571151fd93`, includes `linux/arm64` | PASS |
| event-display | digest from `event-display.yaml` | 1.24: `…/eventing/cmd/event_display@sha256:e991bf5c…dae6c`, arm64 present | PASS |
| Traefik chart `v42.1.3`, Argo CD chart 10.11.6 | — | not resolved in Phase 0 (needed only for N2/G3; `helm show chart` runs with `HELM_*` under `.local/` once the Makefile exists) | NOT RUN, deferred to Phase 7/9 |

### Release manifests — PASS (23 of 23)

`scripts/fetch-manifests.sh` downloaded every asset to `.local/manifests/<line>/` and compared each SHA-256 against the digest GitHub publishes for the asset. All 23 match. There is no pin to compare against yet; `versions.env` is created in Phase 1 with these values. Full table: [raw/preflight-manifests-20261030.tsv](raw/preflight-manifests-20261030.tsv).

| Line | Assets |
|---|---|
| 1.23 | `serving-crds`, `serving-core`, `serving-post-install-jobs`, `serving-storage-version-migration` (serving `knative-v1.23.0`), `kourier` (`knative-v1.23.0`), `eventing-crds`, `eventing-core`, `in-memory-channel`, `mt-channel-broker`, `eventing-post-install`, `event-display` (eventing `knative-v1.23.1`) |
| 1.24 | the same eleven assets at `knative-v1.24.0` |
| cert-manager | `cert-manager.yaml` (`v1.21.3`) |

Asset names match the BRIEF. Additions to the BRIEF list:

- `serving-storage-version-migration.yaml` exists as a separate asset. It contains the same `storage-version-migration-serving-` Job that `serving-post-install-jobs.yaml` also contains. Only `serving-post-install-jobs.yaml` will be used; the separate file is kept for comparison.
- `serving-default-domain.yaml` is deliberately **not downloaded** (sslip.io, B6).

Post-install content in 1.24 (and identical in shape for 1.23):

| File | Objects |
|---|---|
| `serving-post-install-jobs.yaml` | Job `generateName: storage-version-migration-serving-`, Job `generateName: cleanup-serving-` (both in `knative-serving`) |
| `eventing-post-install.yaml` | ClusterRole `knative-eventing-post-install-job-role`, ServiceAccount `knative-eventing-post-install-job`, ClusterRoleBinding, Job `generateName: storage-version-migration-eventing-` |

The 1.24 release notes for serving, eventing and net-kourier contain no "action required", migration, breaking-change or minimum-version entry. Under the upgrade doc, post-install jobs are needed "when the release notes point out that a Knative custom resource is transitioned to a new version". None does for 1.24. The jobs will still be run in U1 as the BRIEF requires; they are idempotent storage-version migrations.

### Images — arm64 PASS (71 of 71), digest pinning FAIL for one image (STOP-4)

All 71 unique image references in the downloaded manifests resolve to multi-arch indexes that include `linux/arm64` ([raw/preflight-images-arm64-20261030.tsv](raw/preflight-images-arm64-20261030.tsv), usage per file in [raw/preflight-image-usage-20261030.tsv](raw/preflight-image-usage-20261030.tsv)).

Core images from B6:

| Component | 1.23 digest | 1.24 digest | arm64 |
|---|---|---|---|
| activator | `sha256:e5ab46f3…b2e5` | `sha256:986b7623…308a` | yes |
| controller | `sha256:ca5062ec…3292` | `sha256:9bf7db63…24c4` | yes |
| autoscaler | `sha256:879da127…bde2` | `sha256:0fcd0d22…8dff` | yes |
| webhook | `sha256:3846e9a4…b650` | `sha256:7cc4b7bc…9a08` | yes |
| queue-proxy | `sha256:a3cc71ce…aaf2` | `sha256:acbd2866…a891` | yes |
| net-kourier controller | `sha256:eedfe393…cf0b` | `sha256:a9ff08c1…6453` | yes |
| **kourier-gateway (Envoy)** | **`docker.io/envoyproxy/envoy:v1.37-latest` — tag, no digest** | **same floating tag** | yes |
| broker ingress | `sha256:42d4a916…7a10` | `sha256:f6cfd10f…f074` | yes |
| broker filter | `sha256:77e9e439…b9a` | `sha256:ce794edb…bc9` | yes |
| imc-dispatcher | `sha256:edb4e71b…2f82` | `sha256:77bf2698…d0ea` | yes |
| event-display | `sha256:434f1ada…c78a` | `sha256:e991bf5c…e6c` | yes |

**Finding (STOP-4):** `kourier.yaml` pins every Knative image by digest, except the data-plane Envoy of the `3scale-kourier-gateway` Deployment. That one is `docker.io/envoyproxy/envoy:v1.37-latest` in both 1.23 and 1.24. On 2026-10-30 the tag resolves to `sha256:7765ad61185fca9c9a770c9e2cad640d085d708ae9c22f3741345e88331472a4`, the same digest as `v1.37.11`. The tag is mutable: a reinstall at a later date can pull a different Envoy, from Docker Hub (rate-limited) rather than `gcr.io`. That matters for reproducibility (AC2), for air-gap mirroring (WP8, ADR-028) and for the supply-chain assessment (X6).

cert-manager images are tag-referenced (`quay.io/jetstack/cert-manager-*:v1.21.3`), all with arm64. B6 only requires digests for images the spike references itself, so this is recorded, not a stop.

### Documentation facts (pinned sources)

**Minimum Kubernetes version**, read from `knative.dev/pkg` `version/version.go` (`DefaultKubernetesMinVersion`) at the exact `pkg` commit in each release's `go.mod`:

| Release | `knative.dev/pkg` | Minimum |
|---|---|---|
| serving `knative-v1.24.0`, eventing `knative-v1.24.0` | `v0.0.0-20261026113028-cfa0ac991c5a` | `v1.35.0` |
| serving `knative-v1.23.0`, eventing `knative-v1.23.1` | `v0.0.0-20260727151759-521cb33b33dd` | `v1.34.0` |

K3s `v1.35.5` satisfies both. The community release schedule (`knative/community` `mechanics/RELEASE-SCHEDULE.md`) gives the same minimums: 1.24 → K8s 1.35, 1.23 → K8s 1.34. Per `RELEASE-VERSIONING-PRINCIPLES.md`, "only the latest patch release of the minor version is tested for support". K3s 1.35.5 is not the latest 1.35 patch, so the spike runs in a best-effort support zone. This is recorded, not a stop.

**Release cadence and support window** (`knative/community` `main` = `8e1cb276c853`):

- Quarterly releases: "Tuesday of the 4th week of January, April, July, October".
- 1.24 released 2026-10-27, end of support 2027-05-04. 1.23 released 2026-07-28, end of support 2027-02-02. Next is 1.25 on 2027-01-26 (minimum K8s 1.36).
- "We (the community) support the most recent 2 versions of Knative."

**Upgrade and downgrade** (`knative/docs` `main` = `ee1e810129b3`):

- `install/upgrade/README.md`: "Knative supports upgrading by a single minor version number."
- `install/upgrade/upgrade-installation.md`: apply the YAML files of the next minor for all installed components. Post-install jobs run with `kubectl create -f serving-post-install-jobs.yaml` / `eventing-post-install.yaml` "when the release notes point out that a Knative custom resource is transitioned to a new version". It also warns: "You also have to transition the version in your custom resource YAML files if you store them externally, e.g. in git via GitOps."
- The docs give no order between components beyond "CRDs first" implied by the assets. The order in B9 Phase 3 / U1 stands.
- `admin/admin-overview.md`: "Downgrade by one Knative version. Downgrades work provided that no applications have used new features since the last upgrade." So a downgrade **is** documented as possible, with a condition. This adjusts the U3 hypothesis ("if not supported"); U3 will cite it.

**Defaults in `knative-v1.24.0`** (from the downloaded `serving-core.yaml` / `eventing-core.yaml`). All values in Annex A were confirmed, with these clarifications:

| ConfigMap | Confirmed | Clarification |
|---|---|---|
| `config-autoscaler` | all 20 values in Annex A, exact | — |
| `config-defaults` | `revision-timeout-seconds: "300"`, `max-revision-timeout-seconds: "600"`, `revision-response-start-timeout-seconds: "300"`, `revision-idle-timeout-seconds: "0"`, `container-concurrency: "0"` | `revision-cpu-request: "400m"` etc. appear in `_example` but are marked "By default, it is not set by Knative." |
| `config-deployment` | `queue-sidecar-cpu-request: "25m"` | `queue-sidecar-memory-request: "400Mi"` applies only "when `queueproxy.resource-defaults` is set to `Enabled`" |
| Serving `config-features` | `secure-pod-defaults: "disabled"`, `kubernetes.podspec-securitycontext: "disabled"` | `data` holds only `_example` |
| Serving `config-observability` | `metrics-protocol`, `request-metrics-protocol`, `tracing-protocol` default to `none` (comment: "'none' (the default)") | The `_example` *values* show `http/protobuf`. They are examples, not defaults |
| Eventing `config-features` (real `data`, not `_example`) | all 8 values in Annex A, exact | `default-authorization-mode` "is only used when `authentication-oidc` is enabled". With the default `authentication-oidc: disabled` there is no Eventing authorization (relevant for X2) |
| Eventing `config-observability` | `metrics-protocol` example `http/protobuf` | default to be confirmed on the cluster (X5) |

**Webhooks in 1.24:**

| Webhook | `failurePolicy` |
|---|---|
| `config.webhook.serving.knative.dev` (Validating) | `Fail` |
| `webhook.serving.knative.dev` (Mutating) | `Fail` |
| `validation.webhook.serving.knative.dev` (Validating) | `Fail` |
| `config.webhook.eventing.knative.dev` (Validating) | `Ignore` |
| `webhook.eventing.knative.dev` (Mutating) | `Fail` |
| `validation.webhook.eventing.knative.dev` (Validating) | `Fail` |
| `sinkbindings.webhook.sources.knative.dev` (Mutating) | `Fail` |

The labels `app.kubernetes.io/version` are `"1.24.0"` across serving-core (62), kourier (13) and eventing-core (105, plus 2 × `"v1.24.0"` — the U1 version check must accept both spellings).

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| P0-repo | PASS | `HEAD == origin/main == 1b0739f` | only the prepared files |
| P0-kubeconfig | PASS | `<spike>/.local/kubeconfig`, absent | — |
| P0-memory | **FAIL (STOP-8)** | 4.84–4.88 GiB available < 10 GiB | Docker Desktop running with 11.67 GiB VM |
| P0-multipass | **BLOCKED (STOP-7)** | not installed | `multipass list` "before" record pending |
| P0-ssh | PASS with open question | only `id_rsa.pub` (RSA 2048) | passphrase/agent status of `id_rsa` unknown |
| P0-ports | PASS | 6450 free | 6443/6444 free |
| P0-tools | PASS with gaps | all required tools present except multipass | kubeconform, mmdc, kn optional |
| P0-pins | PASS | all pins resolvable; podinfo digests exact | fortio tag is `1.76.0`; kubectl `v1.35.10` and curl `8.23.0` proposed |
| P0-manifests | PASS | 23/23 match GitHub digests | `versions.env` pins follow in Phase 1 |
| P0-arm64 | PASS | 71/71 references with `linux/arm64` | — |
| P0-image-digests | **FAIL (STOP-4)** | kourier-gateway `envoy:v1.37-latest` (today `v1.37.11`, `sha256:7765ad61…72a4`) | decision needed |
| P0-docs | PASS | min K8s 1.35.0/1.34.0 from source; downgrade by one version documented | U3 hypothesis adjusted |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Every Knative 1.23/1.24 and cert-manager manifest the spike will apply is downloadable and byte-identical to the digest GitHub publishes for it | That GitHub's published digests are themselves trustworthy (signature checks are X6) |
| Every image in those manifests has a `linux/arm64` variant today | That the floating Envoy tag will resolve to the same image at install time |
| K3s `v1.35.5` meets the minimum Kubernetes version of both Knative lines, read from source | That Knative works on K3s `v1.35.5` (Phase 2–3) |
| The host currently does not have the 10 GiB headroom STOP-8 requires, and Multipass is missing | How much memory frees up once Docker Desktop is stopped (re-measure after CP1) |
| ok-local's profile at `60397cd` is what B1 describes | That the local `ok-local` checkout matches `60397cd` (it does not; it was not changed) |

## Deviations from BRIEF

1. **Tunnel socket name.** B5 and B7 name `.local/ssh-tunnel.sock`, while B4 rule 5 and B8 name `.local/tun.sock` and justify it with the 104-byte socket-path limit. The spike uses `.local/tun.sock` everywhere. The two names point the same way and there is no conflict to resolve, so this is a documented choice, not STOP-10.
2. **fortio tag.** The image tag is `1.76.0`, not `v1.76.0`. The digest above is for `1.76.0`.
3. **ok-local read path.** The pinned files were read from `60397cd` through the GitHub API, because the local checkout is on a different branch and an older `main`.
4. **Downgrade.** Annex A treated downgrades as possibly unsupported. The docs allow a one-version downgrade with a condition (see above).
5. **Additional asset.** `serving-storage-version-migration.yaml` was downloaded for comparison only.
6. **Traefik and Argo CD chart pins** were not resolved in Phase 0. They are only needed in Phase 7 (N2) and Phase 9 (G3).

## CP1 — open decisions, installations and plan

Open decisions:

1. **STOP-7 Multipass:** approve `brew install --cask multipass`. You run it yourself or approve it for me.
2. **STOP-8 memory:** quit Docker Desktop (frees part of its 11.67 GiB VM), then I re-measure before `vm-up`. `ok-mgmt-local`/`ok-infra-local` do not exist, so there is nothing to stop there.
3. **STOP-4 Envoy tag:** (a) apply `kourier.yaml` unchanged, record the digest the gateway pod actually runs (`imageID`) in `versions.env`, and let `knative-verify` fail if it ever differs. Recommended, because it keeps the release manifests byte-identical. (b) Rewrite the tag to the digest in the local copy, which gives a second checksum. (c) Accept the floating tag and only document it.
4. **SSH key:** `~/.ssh/id_rsa` is the key ok-local would use. If it has a passphrase, load it with `ssh-add ~/.ssh/id_rsa`. Otherwise name another key pair to use.
5. **STOP-10 candidate:** the local `CLAUDE.md` says "Read-only everywhere except the `kagent-lab` namespace on the `ok-kagent` lab cluster". The BRIEF requires writes to the new local cluster `ok211`. The stricter rule would forbid the whole PoC, so I need your explicit confirmation that `ok211` (VM `ok-knative-local`) is in scope for writes through the guarded make targets.
6. Optional installs: `kubeconform`, `mermaid-cli`.

Plan after Go (≤ 10 lines):

1. Phase 1: `versions.env` (pins and checksums above), `lib.sh`/`guard.sh`/`scan-secrets.sh`/`kc.sh` adapted from OK-167, Makefile skeleton, ten guard negative tests, lint, secret scan, commit.
2. Re-measure memory, capture `multipass list` "before"; then Phase 2: `kubectl-pin` (v1.35.10), `vm-up`, `k3s-install` (versioned script), `kubeconfig`, `tunnel`, baseline.
3. Phase 3: Knative 1.23 install with patches, verify, smoke test, optional snapshot.
4. Phase 4: upgrade to 1.24 under load (U1/U2), U3 from the docs.
5. Phases 5–9: serving, eventing, networking/TLS, security/observability, GitOps experiments, each with evidence and a commit.
6. Phases 10–12: assessment, report, management summary, drafts, final checks → CP2.

## CP1 resolution (in progress)

Re-checked at 2026-10-30T13:11:12Z, after the human installed Multipass, quit Docker Desktop and added the SSH key to the agent:

| Item | Observed | Verdict |
|---|---|---|
| Multipass | `multipass 1.16.4+mac`, `multipassd 1.16.4+mac`, `/usr/local/bin/multipass` (≥ 1.16; 1.17.0 is available, not installed) | STOP-7 resolved |
| `local.driver` | `qemu` (read only, not changed) | recorded for U3 snapshots |
| `multipass list` (before the spike) | `No instances found.` / JSON `{"list": []}` | recorded for the Phase 12 comparison; `ok-mgmt-local`, `ok-infra-local` and `ok-knative-local` do not exist |
| Docker Desktop | backend not running | — |
| ssh-agent | now holds RSA 2048 `SHA256:/IFc0mrbcsedgs+IWOWxarVPWB27MQfcIfBGgj1BURc`, the same fingerprint as `~/.ssh/id_rsa.pub` | SSH question resolved |
| Ports 6450 / 6443 / 6444 | all free | PASS |
| **Available memory (STOP-8 formula)** | 528 202 pages ≈ **8.06 GiB** at 13:11Z, 521 765 pages ≈ **7.96 GiB** 20 s later; `memory_pressure -Q` 56 % free; load 3.16 4.15 3.33 | **still FAIL — below 10 GiB** |
| Largest remaining consumers | compressor holds 425 609 pages (≈ 6.5 GiB), wired 215 700 pages (≈ 3.3 GiB); processes: WebKit ≈ 1.1 GB, Codex ≈ 0.6 GB, Claude ≈ 0.7 GB, a Steam web helper ≈ 0.4 GB | recorded |

Still open: STOP-8 (memory), STOP-4 (Envoy tag decision), the `CLAUDE.md` write-scope confirmation, and the explicit Go.

## CP1 decisions (human, 2026-10-30)

| Item | Decision |
|---|---|
| STOP-8 memory | Accepted by the human: "my machine has 24 GB". The spike proceeds with ≈ 8 GiB available before `vm-up`. Memory is re-measured before `vm-up` and recorded as a disturbance factor for all measurements (B11) |
| STOP-4 Envoy tag | Option (a): apply `kourier.yaml` unchanged; pin the digest the gateway pod actually runs in `versions.env` (`KOURIER_GATEWAY_EXPECTED_DIGEST`); `knative-verify` fails on any difference |
| `CLAUDE.md` write scope | Confirmed by the human: writes to the local cluster `ok211` (VM `ok-knative-local`) are allowed. The BRIEF guardrails (guarded make targets, isolation) still apply in full |
| Plan | Approved ("dann los") |

## Guard negative tests (Phase 1)

- Date (UTC): 2026-10-30T14:02:30Z
- Command: `make test-guard` (runs `scripts/test-guard.sh`; synthetic kubeconfigs under `.local/test/` with the placeholder data `ZmFrZQ==`; no cluster contacted)
- kubectl: `make kubectl-pin` placed `v1.35.10` in `.local/bin/`. SHA-256 `77ec066f…b068` equals both the pin and the official `.sha256` file. The first attempt timed out at 46/57 MB (dl.k8s.io ≈ 150 KB/s), so the script now resumes with `curl -C -`
- Raw record: [raw/guard-negative-tests-20261030T140230Z.txt](raw/guard-negative-tests-20261030T140230Z.txt)

| ID | Case | Expected exit | Actual | Verdict |
|---|---|---|---|---|
| C0 | positive control: valid synthetic kubeconfig | 0 | 0 | PASS |
| N1 | `KUBECONFIG` empty | 10 | 10 | PASS |
| N2 | path outside `.local/` (traversal `.local/test/../../versions.env`) | 12 | 12 | PASS |
| N3 | file does not exist | 13 | 13 | PASS |
| N4 | wrong context name (`kind-ok167`) | 15 | 15 | PASS |
| N5 | server `https://127.0.0.1:6443` (ok-local tunnel port) | 16 | 16 | PASS |
| N6 | two contexts | 14 | 14 | PASS |
| N7 | symlink in `.local/` pointing outside | 12 | 12 | PASS |
| N8 | unreadable kubeconfig (mode 000) | 18 | 18 | PASS |
| N9 | kubectl from PATH (`/usr/local/bin/kubectl`) instead of `.local/bin/` | 19 | 19 | PASS |
| N10 | `ok211::vm_guard` with `VM_NAME=ok-infra-local` | 30 | 30 | PASS |
| X1 | server with userinfo `https://127.0.0.1:6450@remote.example:6443` | 16 | 16 | PASS |
| X2 | `insecure-skip-tls-verify: true` | 16 | 16 | PASS |
| X3 | `KUBECTL=kubectl` resolved from a PATH without `.local/bin/` | 19 | 19 | PASS |
| X4 | `ok211::vm_guard` with `VM_NAME` unset | 30 | 30 | PASS |
| X5 | `ok211::vm_guard` with `VM_NAME=ok-knative-local` (positive control) | 0 | 0 | PASS |

Each refusal prints a one-line reason. None prints kubeconfig contents.

**The tests fail for the reason claimed (mutation check).** I made a temporary copy of `guard.sh` with the server comparison replaced by `if false` and ran it through the same suite (`OK211_GUARD_UNDER_TEST`). N5 and X1 turned to FAIL (actual exit 0), C0 stayed PASS, and the suite exited non-zero. The mutant was deleted and the real guard re-run green.

**Secret scan self-test.** An untracked, unstaged file `scan-selftest.txt` held a random PEM-shaped private key, an `Authorization: Bearer` header and an `api_token:` assignment. `make scan-secrets` reported 3 findings (`private-key`, `auth-header`, `assignment`) and exited non-zero. After the file was removed the scan was clean (exit 0). The known-value check against `.local/kubeconfig` can only be exercised once that file exists (Phase 2).

**Lint.** `make lint`: shellcheck clean (15 scripts), yamllint clean (7 files). kubeconform is not installed (optional) and was skipped.

| ID | Verdict | Note |
|---|---|---|
| P1-guard | PASS | 10/10 required negative cases refused with the documented code; 4 additional cases and 2 positive controls behave as expected; mutation check red |
| P1-lint | PASS | kubeconform skipped (not installed) |
| P1-scan | PASS | fires on the planted file, clean afterwards |

Deviation: the VM launch (Phase 2 step 2) was started before the Phase 1 commit, to overlap two slow downloads. No VM or cluster state was used by any Phase 1 check.
