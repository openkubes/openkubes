# 02 — zot registry (AC1)

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: V1–V8 (BRIEF Phase 3.6)
- Date (UTC): 2026-10-29T11:57Z
- Worktree commit: `72aa815` (Phase 2)
- Environment: kind `ok167` (Kubernetes v1.36.4), zot `v2.1.20@sha256:542e25be…18234`,
  chart `zot-0.1.122`, oras 1.3.6 — see `00-preflight.md`
- Deviations from `registry-default`: `zot/DEVIATIONS.md`

## Steps

```bash
make namespaces      # 10 namespaces
make pki             # CA + server cert into .local/pki/, verified against the CA
make identities      # 3 machine identities, bcrypt htpasswd, netrc files, all 600
make zot-secrets     # zot-server-tls and zot-htpasswd, piped into kubectl, never via a file
make events-install  # CloudEvents sink, deployed before zot
make zot-install     # helm upgrade --install, after asserting the rendered image and no Secret
make zot-verify      # V1-V8
```

Credentials are never arguments: `curl --netrc-file .local/netrc-<identity>`,
`oras login --password-stdin --registry-config .local/registry-auth/<identity>.json`. Nothing was
written to `~/.docker` or `~/Library/Preferences/helm`.

## Observed

### V1–V8

| ID | Check | Observed | Verdict |
|---|---|---|---|
| V1 | TLS with the CA, then without | With `--cacert`: 200. Without: `curl: (60) SSL certificate problem: unable to get local issuer certificate` | PASS |
| V2 | anonymous `GET /v2/` | **401** | PASS |
| V3 | publisher `GET /v2/` | **200**, `Docker-Distribution-API-Version: registry/2.0` | PASS |
| V4 | publisher pushes to `openkubes/machine/gitops/smoke`, pull by digest | pushed; layer blob fetched by digest; **pulled bytes hash to `sha256:ca13c72a2249…`, equal to the digest** | PASS |
| V5 | puller reads; puller writes | read OK; push **denied** | PASS |
| V6 | publisher pushes to `openkubes/machine/other/smoke` | **403** | PASS |
| V7 | extensions active | `search=on` (GraphQL returned data), `trust=on` (`/v2/_zot/ext/cosign` advertised), `events=on` (CloudEvent received) | PASS |
| V8 | `oras attach` SBOM + `oras discover` | **1 referrer** on the smoke subject, artifactType `application/vnd.openkubes.sbom.v1+json` | PASS |

**8 passed, 0 failed.**

### Extensions compiled into the image

From zot's own startup banner (`evidence/raw/zot-binary-type.txt`):

```text
BinaryType=-events-imagetrust-lint-metrics-mgmt-profile-scrub-search-sync-ui-userprefs
```

and the live extension API (`evidence/raw/zot-extensions-discover.json`) advertises
`/v2/_zot/ext/cosign`, `/v2/_zot/ext/search`, `/v2/_zot/ext/mgmt`.

CVE scanning is **off** by design — the `search` extension carries no `cve` block, and zot logged
`cve config not provided, skipping cve-db update`. No Trivy database is downloaded.

### CloudEvent captured (groundwork for Q3.b)

`evidence/raw/cloudevent-image-updated.json`, received by the sink on the V4 push:

| Header | Value |
|---|---|
| `ce-type` | `zotregistry.image.updated` |
| `ce-source` | `zotregistry.dev` |
| `ce-specversion` | `1.0` |
| `ce-id`, `ce-time` | per event |

Body keys: `actor`, `digest`, `manifest`, `mediaType`, `name`, `reference`, `request` — i.e. the
repository (`name`), the tag (`reference`), the digest and the pushing identity (`actor.name`:
`gitops-publisher`). A refresh bridge (Q3.d) would have everything it needs. Across the run the
sink saw 6 × `zotregistry.image.updated` and 1 × `zotregistry.repository.created`.

Note for Q3: the CloudEvent carries the repository in the **body**, not in a `ce-subject` header.

### Authorization is real, not nominal

V5 and V6 are the checks that matter. A registry that accepted everything would pass V1–V4 and V8
unchanged. The publisher is confined to its prefix (**403** outside it) and the puller cannot
write — so the `accessControl` block is enforced rather than decorative.

## Findings

### Hurdle H1 — `oras` sends plain HTTP to a registry called `localhost`

The first `oras login localhost:30500` failed with:

```text
Error response from registry: GET "http://localhost:30500/v2/": response status code 400: Bad Request
```

`oras`, like Docker, treats a registry whose host is `localhost` as a local plain-HTTP registry and
never attempts TLS; zot, serving only HTTPS, answers the HTTP request with 400. The obvious fix,
`--plain-http`, is forbidden by BRIEF B4 rule 9.

**Resolution: use `127.0.0.1:30500`.** The IP is in the certificate's SANs and `oras` does *not*
apply the plain-HTTP shortcut to it. Verified rather than assumed — omitting `--ca-file` now fails
with a certificate error, which proves TLS is actually in play:

```text
Get "https://127.0.0.1:30500/v2/": tls: failed to verify certificate:
x509: "zot.zot.svc.cluster.local" certificate is not trusted
```

`oras --resolve zot.zot.svc.cluster.local:30500:127.0.0.1` works equally well and is the better
pattern where a real hostname is wanted. Recorded for the report: a host-side publisher against a
loopback registry must avoid the literal name `localhost`, or it silently loses TLS.

### F5 closed in `registry-default`'s favour

zot v2.1.20 exempts `/livez`, `/readyz` and `/startupz` from access control (200 anonymously,
while `/v2/` returns 401). No `authHeader` is needed with `defaultPolicy: []`, and
`values-ok-shared.yaml` has no latent probe problem. Details in `zot/DEVIATIONS.md`.

### Two defects in the verification script, found by running it

Both initially looked like registry problems and were not:

1. **`search` reported OFF.** The GraphQL query asked for `ImageListWithLatestTag`, which does not
   exist in v2.1.20; zot answered **422** with `Cannot query field "ImageListWithLatestTag"`. A
   check that only looks at the status code cannot tell a disabled extension from a malformed
   query. Schema introspection gave the real field list, and `RepoListWithNewestImage` returns data.
2. **`trust` reported OFF.** The check grepped `kubectl logs --tail=400` for "setting up cosign
   route" — a line printed at **startup**, i.e. at the *beginning* of the log, which a bounded tail
   stops reaching once a few requests have been served. It now asks the live extension API instead
   of scraping a log.

A third, V8, reported "no referrer" because the jq path was `.manifests`; `oras discover --format
json` returns `.referrers`.

## Verdict

**PASS — AC1 is met.** zot runs with TLS from a private CA, htpasswd machine identities, enforced
repository-scoped authorization, and the `search`, `trust`, `events`, `metrics` and `scrub`
extensions. No insecure flag was used anywhere.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| zot serves TLS from the local CA and rejects clients that do not trust it | That the certificate chain would satisfy a stricter client, or survive expiry — it is valid 30 days |
| Anonymous access is refused and both machine identities authenticate | Anything about OIDC/human access, which this PoC deliberately omits |
| `accessControl` is enforced: publisher confined to its prefix (403), puller read-only | That the policy is correct for production — the prefixes and identities differ from `registry-default` (see DEVIATIONS) |
| Bytes pulled by digest hash to exactly that digest | That zot preserves content across restarts, GC or a PVC remount — not yet tested |
| The Referrers API accepts an attach and returns the referrer | That referrers survive an offline copy — Phase 9 tests that |
| `search`, `trust`, `events`, `metrics`, `scrub` are compiled in and enabled | That `trust` actually *verifies* a signature — Q4 measures that; zot's trust output is informational either way |
| zot emits CloudEvents on push with repository, tag, digest and actor | That Argo CD can consume them — it cannot, which is the point of Q3.c |
| zot's health endpoints need no credentials under `defaultPolicy: []` | That this holds for other zot versions or other auth configurations |
| No Secret is rendered by the chart under these values | That no secret reached the cluster — two were created deliberately by `make zot-secrets` from `.local/` |
