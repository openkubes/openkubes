# 00 — Preflight

- Test IDs: Phase 0 (environment, tooling, version pins). Guard negative tests are added in Phase 1.
- Date (UTC): 2026-10-29T09:28:41Z
- Worktree commit: `d6772c83af7ea05bc9118840c63a6b9f507d64c1` (branch `spike/OK-167-gitless-gitops`, identical to `origin/main`)
- Environment: macOS 27.0.1 (build 26A434), arm64 (Apple Silicon), Docker Desktop 29.5.3
- Scope of this phase: read-only. No cluster was created, no package was installed, no system setting was changed.

## Steps

All checks were run by hand; Phase 1 turns them into `make preflight`.

```bash
# Repository state
git rev-parse --abbrev-ref HEAD
git merge-base --is-ancestor HEAD origin/main
git status --porcelain --untracked-files=all
cat "$(git rev-parse --git-path info/exclude)"

# Kubeconfig isolation
echo "$KUBECONFIG"
kubectl config get-contexts

# Host
uname -m; sw_vers
docker info --format '{{.NCPU}} {{.MemTotal}}'
lsof -nP -iTCP:30500 -sTCP:LISTEN
lsof -nP -iTCP:5000  -sTCP:LISTEN

# Tooling
for t in docker kind kubectl helm oras cosign jq yq gtar shellcheck yamllint argocd actionlint; do command -v "$t"; done

# Chart pins — Helm directories redirected into .local/ (BRIEF B4 rule 6), no global `helm repo add`
export HELM_CONFIG_HOME="$PWD/.local/helm/config" HELM_CACHE_HOME="$PWD/.local/helm/cache" \
       HELM_DATA_HOME="$PWD/.local/helm/data" HELM_REGISTRY_CONFIG="$PWD/.local/helm/config/registry/config.json"
helm show chart zot     --repo https://zotregistry.dev/helm-charts  --version 0.1.122
helm show chart argo-cd --repo https://argoproj.github.io/argo-helm --version 10.11.6
helm show chart oci://ghcr.io/stefanprodan/charts/podinfo

# Image pins — digest and platform list (oras is not installed yet, so buildx is used)
docker buildx imagetools inspect <ref> --raw | shasum -a 256
docker buildx imagetools inspect <ref> --raw | jq '.manifests[].platform'
```

## Observed

### Repository state — PASS

| Check | Expected | Observed |
|---|---|---|
| Branch | `spike/OK-167-gitless-gitops` | `spike/OK-167-gitless-gitops` |
| Base | `origin/main` | `HEAD == origin/main == d6772c8` |
| Untracked in spike dir | only `BRIEF.md`, `.gitignore`, `.local/` | exactly those (`.local/` ignored by the spike `.gitignore`) |
| Untracked at repo root | `CLAUDE.md`, `start-claude.sh`, `.claude/settings.local.json`, all via `.git/info/exclude` | exactly those three, all listed in `.git/info/exclude` |
| Anything else | none | none |

No S10 condition. `versions.env` is **not** matched by any `.gitignore` rule, so the pins will be tracked as B6 requires.

### Kubeconfig isolation — PASS

| Check | Observed |
|---|---|
| `KUBECONFIG` | `<spike>/.local/kubeconfig` (absolute, exact match) |
| `KUBECONTEXT` | unset |
| File exists | no — `.local/` is empty |
| `kubectl config get-contexts` | header only, zero contexts |

No S1 or S2 condition.

### Host — one finding

| Property | Value | Verdict |
|---|---|---|
| Architecture | `arm64` (Docker reports `aarch64`) | every pinned image must have a `linux/arm64` variant — all do, see below |
| macOS | 27.0.1 (26A434) | — |
| Docker Desktop | 29.5.3, storage driver `overlayfs` | — |
| Docker CPUs | 10 | PASS (A1 asks for ≥ 4) |
| **Docker memory** | **3.83 GiB** (4 108 357 632 B) at first inspection; **11.67 GiB** (12 528 381 952 B) after the CP1 fix | initially FAIL (S8), **now PASS** — see F1 |
| Running containers | 2 of 13 | they consumed part of the original 3.83 GiB |
| Port 30500 | free | PASS |
| Port 5000 | occupied by `ControlCenter` (AirPlay Receiver), PID 644 | expected; confirms why the spike uses NodePort 30500 |
| Free disk | 153 GiB | PASS |

### Tooling

Installed:

| Tool | Version | Path | Note |
|---|---|---|---|
| docker | 29.5.3 | `/usr/local/bin/docker` | |
| docker buildx | v0.34.1-desktop.1 | — | used to resolve digests while `oras` is missing |
| kind | 0.33.0 | `/opt/homebrew/bin/kind` | matches pin exactly |
| kubectl | v1.34.1 | `/usr/local/bin/kubectl` | Docker Desktop's; symlink into `Docker.app` |
| kubectl | v1.37.0 | `/opt/homebrew/bin/kubectl` | Homebrew `kubernetes-cli` 1.37.2 |
| helm | v4.3.0 | `/opt/homebrew/bin/helm` | **Helm 4**, not Helm 3 — see finding F3 |
| jq | 1.7.1-apple | `/usr/bin/jq` | |
| yq | v4.53.6 (mikefarah) | `/opt/homebrew/bin/yq` | |
| openssl | 3.6.4 | `/opt/homebrew/opt/openssl@3/bin/openssl` | not on `PATH`; system `openssl` is LibreSSL 3.3.6 |
| htpasswd | Apache, bundled | `/usr/sbin/htpasswd` | supports `-B` (bcrypt), `-i` (stdin), `-n` — all three required |

Missing at first inspection; installed from Homebrew after approval at CP1 (see "CP1 resolution"
below), all at exactly the pinned versions:

| Tool | Pin in B6 | Homebrew formula | Installed version | Required for |
|---|---|---|---|---|
| oras | v1.3.x | `oras` | 1.3.6 | AC2, every push/pull (D1) |
| cosign | v3.1.x | `cosign` | v3.1.4 | Q4 |
| gtar | GNU tar | `gnu-tar` | 1.35 | deterministic archives (bsdtar cannot sort by name) |
| shellcheck | current | `shellcheck` | 0.11.0 | `make lint`, D1 gate |
| yamllint | current | `yamllint` | 1.38.0 | `make lint` |
| argocd | v3.5.x | `argocd` | v3.5.6 | optional; exactly matches the server pin |
| actionlint | current | `actionlint` | 1.7.12 | optional; validates `ci/github-actions-example.yaml` |

### Version pins — all resolved, all arm64-capable

| Component | Pin | Resolved | Verdict |
|---|---|---|---|
| zot chart | `zot-0.1.122` @ `https://zotregistry.dev/helm-charts` | `version 0.1.122`, `appVersion v2.1.18` | PASS — identical to `registry-default` |
| zot image | `ghcr.io/project-zot/zot:v2.1.20@sha256:542e25be…18234` | tag `v2.1.20` resolves to **exactly** `sha256:542e25be4d32e7879c0cfad93492a93c81b1e059cbd2d30d485d4bd567318234`; OCI index with `linux/arm64/v8`, `linux/amd64`, `freebsd/{arm64,amd64}` | PASS |
| Argo CD chart | `argo-cd-10.11.6` @ `https://argoproj.github.io/argo-helm` | `version 10.11.6`, `appVersion v3.5.6` | PASS — appVersion requirement met |
| Argo CD image | `quay.io/argoproj/argocd:v3.5.6` | `sha256:8e5cc5bb008df8a09dba439462e58c94c55b7735888d3ebde0c25fc05e4e5335`; index with `linux/arm64` | PASS |
| kind | v0.33.0 | `kind v0.33.0 go1.27.0 darwin/arm64` | PASS |
| kind node image | Kubernetes v1.36.x from the v0.33.0 release notes | `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`; index with `linux/arm64` | PASS — deliberately **not** the release default `v1.37.0`, because Argo CD 3.5 is tested only against Kubernetes v1.33–v1.36 |
| podinfo 6.16.0 | digest to be pinned | `ghcr.io/stefanprodan/podinfo:6.16.0` → `sha256:2c88592f2b8f51a9428c8039486fc41abac53c95dbbb884d03bebee0876a6d4d`; `linux/{amd64,arm64}` | PASS |
| podinfo 6.17.0 | digest to be pinned | `ghcr.io/stefanprodan/podinfo:6.17.0` → `sha256:fa2f27c1a8561097e5144bfc0853eba6054d743b68b03de4cad4675616ddefb0`; `linux/{amd64,arm64}` | PASS |
| podinfo chart | version matching 6.17.0 | `oci://ghcr.io/stefanprodan/charts/podinfo` → chart `6.17.0`, appVersion `6.17.0` | PASS — chart and image versions coincide |
| Event receiver | multi-arch HTTP echo, pinned by digest | `mendhak/http-https-echo:37` → `sha256:f55000d9196bd3c853d384af7315f509d21ffb85de315c26e9874033b9f83e15`; `linux/{amd64,arm64,arm/v6,arm/v7}` | PASS — selected because it logs request headers **and** body, which Q3.b needs to capture a CloudEvent in full |
| curl image | multi-arch, pinned by digest | `curlimages/curl:8.18.0` → `sha256:d94d07ba9e7d6de898b6d96c1a072f6f8266c687af78a74f380087a0addf5d17`; `linux/{amd64,arm64/v8,386,arm/v7,ppc64le}` | PASS |

No S4 condition: every pin resolved, and every pin has a variant for `arm64`.

### Chart reference material

Saved for later diffing, with redaction noted below:

- `evidence/raw/helm-values-zot-0.1.122.yaml` (370 lines)
- `evidence/raw/helm-values-argo-cd-10.11.6.yaml` (4969 lines)

### CI exposure of the spike directory — PASS

Every workflow under `.github/workflows/` was inspected with `yq '.on'`. None triggers on
`architecture/**`: the four `pull_request` triggers are path-filtered to
`platform/ai/openclaw/**`, `platform/console/observed-state-producer/**`, `website/**`/`mkdocs.yml`,
and their own workflow files. The remaining workflows are `workflow_dispatch`, `schedule`, or
tag-push only. A pull request touching only this spike directory therefore starts no GitHub
Actions workflow. (The Cloudflare Pages preview check is an external integration and is outside
this inspection.) This confirms the claim in BRIEF Appendix A.

## Findings

### F1 — Docker Desktop memory was below the required minimum (S8) — RESOLVED

**Observed:** `docker info` reported `MemTotal = 4 108 357 632` bytes = **3.83 GiB**. BRIEF A1 asks
for 6 GB; stop condition S8 triggers below 4 GB. Two containers were already running inside that
allowance.

**Why it matters:** the target state runs kind (control plane), zot with a 2 GiB PVC, Argo CD
(application-controller, repo-server, server, redis), an event receiver and the podinfo workloads
across up to ten namespaces. BRIEF A1 budgets 3–4 GB for that in steady state, which leaves no
headroom at 3.83 GiB total. The likely failure mode is not a clean error but OOM-killed Argo CD
pods midway through Phase 7, which would corrupt latency measurements rather than fail loudly.

**This was a human action (Docker Desktop → Settings → Resources → Memory).** It was listed as a
CP1 decision and not worked around.

**Resolution (2026-10-29, at CP1):** memory raised to `12 528 381 952` bytes = **11.67 GiB**,
verified with `docker info`. CPUs unchanged at 10. Comfortably above the 6 GB A1 asks for, so S8 no
longer applies. Actual consumption of the full stack is measured in Phase 10.

### F2 — `kubectl` on `PATH` is two minor versions behind the node image

**Observed:** `/usr/local/bin/kubectl` (Docker Desktop, v1.34.1) precedes
`/opt/homebrew/bin/kubectl` (v1.37.0) on `PATH`. The node image is Kubernetes v1.36.4. B6 requires
kubectl within ±1 minor: v1.34.1 is −2 (out of tolerance), v1.37.0 is +1 (in tolerance).

**Resolution — no installation needed:** the Phase 1 Makefile resolves a `KUBECTL` variable to the
Homebrew binary and uses `$(KUBECTL)` everywhere; `scripts/guard.sh` additionally asserts the
±1 relationship so a changed `PATH` cannot silently reintroduce the skew.

### F3 — Helm 4 is installed, not Helm 3

**Observed:** `helm version` → `v4.3.0+gbec5b06`, built against Kubernetes client v1.37.
`CONTRIBUTING.md` asks for ≥ 3.14; B6 anticipates Helm 4 and requires the `helm push` and
`helm registry` flags to be checked against it.

**Already verified in this phase:** `helm show chart --repo … --version …` and `helm show values`
behave as expected under Helm 4, and `helm pull --repo` works. **Still to verify before use:**
`helm pull`/`helm push` against an OCI registry (test S-D) and `helm registry login` flag names,
plus `helm upgrade --install --wait --timeout` and `--set-file` with escaped dots (Phase 5).
Checked with `--help` at the point of use, per B0 rule 2.

Side note: `helm pull --untar --untardir .local/charts` created a stray nested `.local/` directory
under the target. Harmless, removed; worth knowing before the Makefile relies on `--untar`.

### F4 — The chart's default htpasswd is inert, but for a different reason than B6 assumes

**Observed:** the chart's `secretFiles.htpasswd` does contain example `admin:admin` and `user:user`
bcrypt hashes, exactly as B6 and Appendix A state. However `templates/secret.yaml` is gated on:

```gotemplate
{{- if and .Values.mountSecret .Values.secretFiles }}
```

and `mountSecret` already defaults to **`false`** in the chart. `helm template zot .local/charts/zot`
with pure chart defaults rendered **no `Secret` object at all** (verified, not assumed).

**Consequence:** setting `mountSecret: false` and `secretFiles: null` as B6 instructs is still
correct and will be done — it makes the intent explicit and prevents a later values edit from
silently activating the example users — but it is defence in depth, not the thing that disarms the
default. The `helm template` proof required by B6 §3.4 will be recorded in `evidence/02-zot.md`.

### F5 — Probes may need an `authHeader`, which is a secret value (open, to be resolved in Phase 3)

**Observed:** the chart documents a top-level `authHeader` value as *"Authentication string for
Kubernetes probes, which is needed when `htpasswd` authentication is enabled, but the anonymous
access policy is not"* — a base64 `user:password` string. `templates/statefulset.yaml` injects it
into all three probes:

```gotemplate
livenessProbe:   httpGet: { path: /livez,    port: …, scheme: … }
readinessProbe:  httpGet: { path: /readyz,   port: …, scheme: … }
startupProbe:    httpGet: { path: /startupz, port: …, scheme: … }
  {{- if .Values.authHeader }}
  httpHeaders: [{ name: Authorization, value: "Basic {{ .Values.authHeader }}" }]
  {{- end }}
```

**Why this is a risk:** the planned `accessControl` has `defaultPolicy: []` for `**`, i.e. no
anonymous access — precisely the configuration the chart comment describes. If zot v2.1.20 gates
`/livez`, `/readyz` and `/startupz` behind authentication, the pod never becomes Ready and
`helm upgrade --wait` times out.

**Two further points, both unresolved by guesswork:**

1. `registry-default` (`platform/registry/zot/values-ok-shared.yaml`) does **not** set `authHeader`
   and *does* use `defaultPolicy: []`. Either zot exempts the health endpoints from auth — in which
   case nothing is needed here either — or the production profile has a latent probe problem. Which
   of the two holds is a finding worth reporting back, so it will be measured rather than assumed.
2. If `authHeader` *is* required, it is a credential and must never appear in the tracked
   `zot/values-poc.yaml`. It would be passed by the make target via `--set authHeader=…` sourced
   from `.local/credentials.env`. Note that Kubernetes then stores it **in plaintext in the
   StatefulSet pod spec**, readable by anyone with `get pods`/`get statefulsets` in namespace `zot`
   — a security observation for the report either way.

**Plan:** install zot without `authHeader` first and observe. Record whichever answer reality gives.

## CP1 resolution (2026-10-29)

Both blockers raised at CP1 were cleared by the requester before Phase 1 started:

| Blocker | Action | Verification |
|---|---|---|
| F1 / S8 — Docker memory 3.83 GiB | Requester raised Docker Desktop memory | `docker info` → `MemTotal = 12 528 381 952` (**11.67 GiB**), NCPU 10 |
| S7 — seven tools missing | `brew install oras cosign gnu-tar shellcheck yamllint argocd actionlint`, run with explicit approval | all seven on `PATH` at the pinned versions, table above |

Two side effects of the install were checked rather than assumed:

- Homebrew's automatic cleanup removed the unrelated `openssl@4` and `sqlite` formulae in the same
  run. **`openssl@3` survived** (`brew list --versions openssl@3` → `3.6.4`), which matters because
  the Phase 3 PKI depends on it and the system `openssl` is LibreSSL 3.3.6.
- `gnu-tar` installed GNU tar as **`gtar` only**; `tar` on `PATH` is still `/usr/bin/tar`
  (bsdtar 3.5.3). This is the required arrangement — the packaging script calls `gtar` explicitly,
  so no `PATH` manipulation is needed and no other tool silently changes behaviour.

Cosmetic note for the record: `argocd version --client` reports `v3.5.6+c2b1e30.dirty`. The
`.dirty` suffix comes from Homebrew's build process, not from a modified binary; the version
matches the pinned server version exactly.

## Verdict

**PASS. Both CP1 blockers (F1, S7) resolved; F2–F5 resolved or planned.**

- Repository state, kubeconfig isolation and CI exposure: PASS, no stop condition.
- All thirteen version pins resolved to exact digests, all with `linux/arm64` variants: PASS, no S4.
- Tooling: complete, every tool at its pinned version: PASS, S7 cleared by approved install.
- Docker Desktop memory 11.67 GiB: PASS, S8 cleared.
- During Phase 0 itself no cluster was created and no system setting was touched; the only system
  change in this document is the explicitly approved Homebrew install recorded above.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Every version pin in B6 resolves today, to the exact digest named where one was named | That the pinned software behaves as Appendix A predicts — nothing has been run yet |
| Every pinned image publishes a `linux/arm64` variant, so the host architecture is supported | That the images start, pass probes, or interoperate on this host |
| The tag `zot:v2.1.20` resolves to exactly the digest `registry-default` pins | That zot's compiled extensions include `events`, `trust` or `search` — V7 measures that |
| `kindest/node:v1.36.4` exists for kind v0.33.0 and carries Kubernetes v1.36.4 | That Argo CD v3.5.6 runs correctly on it — only that the combination is inside the tested range |
| The zot chart renders no `Secret` under default values, because `mountSecret` defaults to false | That the chart renders no secret under **our** values — proven in Phase 3 |
| `KUBECONFIG` points only at an empty, spike-local file and no context exists | That the guard enforces this — Phase 1 tests the six negative cases |
| No GitHub Actions workflow triggers on `architecture/**` | That no external check (Cloudflare Pages) runs on a PR |
| Docker Desktop reports 3.83 GiB, below the A1 requirement | How much memory the full stack actually needs on this host — that is measured in Phase 10 |

---

# Phase 1 addendum — guard and scanner negative tests

- Test IDs: Phase 1 step 4 (guard negative tests), Phase 1 step 5 (secret scan trip test)
- Date (UTC): 2026-10-29T11:38Z
- Scope: still no cluster. Every test below runs against synthetic kubeconfigs and planted
  files; nothing contacted a Kubernetes API server.

## Guard — `scripts/guard.sh`

Synthetic kubeconfigs under `.local/test/` contain structure only: no tokens, no client
certificates, no CA data. Each case was run by invoking the guard directly, not through
`make`, because the Makefile sets `KUBECONFIG` itself and would mask the variable under test.

| # | Case | Expected | Exit | Message | Verdict |
|---|---|---|---|---|---|
| 0 | correctly shaped local kubeconfig | accept | 0 | `guard: context=kind-ok167 server=https://127.0.0.1:62345` | PASS |
| 1 | `KUBECONFIG` empty | reject | 10 | "KUBECONFIG is unset or empty." | PASS |
| 2 | path outside `.local/` (`~/.kube/config`) | reject | 12 | "KUBECONFIG points outside the spike's .local/ directory." | PASS |
| 3 | file does not exist | reject | 13 | "KUBECONFIG names a file that does not exist" | PASS |
| 4 | context is not `kind-ok167` | reject | 15 | "Current context is 'some-other-cluster', expected 'kind-ok167'" | PASS |
| 5 | server is not `https://127.0.0.1:` | reject | 16 | "API server is 'https://api.ok-shared.example.internal:6443'" | PASS |
| 6 | two contexts in one file | reject | 14 | "Expected exactly one context in the kubeconfig, found: 2" | PASS |

All six required cases reject, each with its own exit code, and case 0 confirms the guard is
not simply refusing everything.

### Two escapes found while testing, and closed

Testing the guard rather than assuming it works surfaced two holes. Both are now covered by
the cases below, which did **not** pass on the first implementation:

| # | Case | First result | After fix | Verdict |
|---|---|---|---|---|
| 7 | `.local/../Makefile` — traversal out through the parent | 12 (already correct) | 12 | PASS |
| 8 | symlink **inside** `.local/` pointing at `/etc/hosts` | **exit 1, no message** | 12 | PASS after fix |
| 9 | relative path | 11 | 11 | PASS |
| 10 | `KUBECONFIG` holding an `a:b` list | 11 | 11 | PASS |
| 11 | forced stale `kubectl` (`KUBECTL=/usr/local/bin/kubectl`) | 17 | 17 | PASS |

**Escape 8** was the real defect. The original path resolution canonicalised the *parent
directory* but not the final component, so a symlink sitting inside `.local/` could point
anywhere. The file then existed, passed the prefix check, and failed later inside a pipeline
where `set -o pipefail` turned it into a bare `exit 1` with no explanation. Two changes:
the final component is now followed by hand (macOS has no `readlink -f`), bounded to 32 hops;
and a kubeconfig that does not parse now exits **18** with kubectl's own message instead of
failing silently. A guard that fails incomprehensibly is a guard that gets switched off.

**Case 11** records a second consequence of finding F2. Invoked directly — the form BRIEF B4
rule 3 prescribes for ad-hoc reads, `scripts/guard.sh && kubectl get …` — the guard originally
resolved `kubectl` from `PATH` and therefore always failed with exit 17 on this host. It now
selects, among `kubectl`, `/opt/homebrew/bin/kubectl` and `/usr/local/bin/kubectl`, the first
binary within one minor of the cluster, while an explicit `KUBECTL` still wins. Choosing by
measured version rather than by hard-coded path keeps this correct on a host where the two
installations are the other way round.

## Secret scan — `scripts/scan-secrets.sh`

Required by Phase 1 step 5: the scanner must fire on a planted file and be clean once it is
removed. Three shapes were planted, one at a time, each in a file Git would actually pick up:

| Shape | Detected | Exit | Verdict |
|---|---|---|---|
| complete bcrypt hash | `tripwire-a.yaml:3 [bcrypt]` | 1 | PASS |
| PEM private key with a base64 body | `tripwire-b.yaml:2 [private-key]` | 1 | PASS |
| opaque value on a `password:` key | `tripwire-c.yaml:2 [assignment]` | 1 | PASS |
| *(no tripwire)* | — | 0 | PASS |

All three tripwire files were removed; the working tree ends clean at `exit 0` over 11 files.

### Three defects found by running it rather than reading it

1. **`mapfile` is a bash 4 builtin.** macOS ships bash 3.2.57 and has no newer bash installed,
   so the first version died at `mapfile: command not found` (exit 127) before running a single
   check. All scripts are now bash-3.2 compatible: no `mapfile`, no associative arrays. This
   also matters for `scripts/package-and-push.sh` (D1), which must run unmodified in CI.
2. **The findings counter lived in a variable incremented inside a `cmd | while read` loop.**
   That loop runs in a subshell, so the increments were discarded: the scanner would have
   printed findings and still exited 0 — the single failure mode a secret scanner must not
   have. Findings are now appended to a file and counted from it.
3. **The value extraction was greedy.** `sed 's/.*[:=][[:space:]]*//'` cuts at the *last*
   separator on a line, so

   ```yaml
   #   clientSecret: $dex.github.clientSecret # Alternatively $<some_K8S_secret>:dex.github.clientSecret
   ```

   yielded `dex.github.clientSecret` and lost the leading `$`. That `$` is what marks the value
   a *reference* rather than a literal — Argo CD's documented secret indirection, and exactly
   what the Secret Contract in ADR-011 asks for. Extraction now splits on the first separator
   and strips any trailing comment, and a `$`-prefixed value is recognised as a reference
   (bcrypt hashes, which also start with `$`, are excluded and still caught by their own rule).

These were the four false positives noted at the end of Phase 0 in the `argo-cd` chart
reference dump. None of them was a secret; all are commented upstream documentation. The
scanner now reports zero findings on the real tree while still catching all three planted
shapes — it was tuned to be correct, not merely quiet.

## Lint

`make lint` is green: `shellcheck -x -P SCRIPTDIR --severity=style` clean over all scripts,
`yamllint` clean over all tracked YAML. Two host-specific fixes were needed in the
`CONTRIBUTING.md` help-target template, both recorded as comments in the `Makefile`:
`include versions.env` appends to `MAKEFILE_LIST` so `grep` prefixed every line with a
filename, and `.*?` is a PCRE lazy quantifier that macOS's BSD awk does not support.

## Verdict

**PASS.** Guard rejects all six required negative cases plus four more found during testing,
and accepts the correct one. Secret scan fires on three planted shapes and is clean otherwise.
`make lint` and `make scan-secrets` are green.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| The guard rejects every malformed or foreign `KUBECONFIG` tested, including symlink and traversal escapes | That it rejects every conceivable escape — it was tested against eleven cases, not proved correct |
| The guard accepts a correctly shaped local kubeconfig, so it is not failing closed on everything | That it behaves identically against a real kind-generated kubeconfig — Phase 2 exercises that |
| The secret scanner exits non-zero on bcrypt hashes, PEM key bodies and opaque credential assignments | That it would catch a secret in a shape not tested, such as a JWT or a cloud access key |
| The scanner is clean on the current tree without suppressing a directory | That the tree contains no secret — only that none matches a known shape or a known value |
| All scripts run on the bash this host actually has (3.2.57) | That they run on bash 4+, or on Linux CI — untested so far |
