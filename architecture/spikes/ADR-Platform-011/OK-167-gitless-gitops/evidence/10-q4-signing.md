# 10 — Q4: artifact signing with cosign and zot trust

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: Q4.0 – Q4.f
- Date (UTC): 2026-10-29T12:38Z – 12:44Z
- Environment: cosign v3.1.4, zot v2.1.20 (trust extension on, cosign: true), Argo CD v3.5.6

## Q4.0 — public key uploaded before signing

zot verifies signatures **at push time** and then only periodically (roughly every two hours), so
a key uploaded afterwards would not trigger a re-check. Uploaded first, as `ok167-admin`:

```text
POST https://127.0.0.1:30500/v2/_zot/ext/cosign   ->  HTTP 200
```

## Q4.a — signing offline

```sh
cosign sign --key .local/cosign/cosign.key \
  --use-signing-config=false --tlog-upload=false \
  --registry-cacert .local/pki/ca.crt -y <ref>@<digest>
```

All three flags were confirmed accepted **before** signing, precisely because `-y` without
`--tlog-upload=false` would consent to a public Rekor upload. Both deprecation warnings appeared
and both flags still work:

```text
Flag --use-signing-config has been deprecated, an offline signing flag will be added in the future;
  TUF will continue to provide a signing config by default if one is not provided manually
Flag --tlog-upload has been deprecated, prefer using a --signing-config file with no transparency log services
```

Worth flagging for the report: these are the flags that keep signing **offline**, and both are
deprecated with no stable replacement yet. An air-gapped pipeline on cosign v3 is relying on
deprecated behaviour today.

Signing was done **by digest**, never by tag.

## Q4.b — where the signature lives, and it depends on the format

| Format | Where it lands | Tag list |
|---|---|---|
| default (OCI 1.1 bundle) | **referrer**, `artifactType: application/vnd.dev.sigstore.bundle.v0.3+json` | unchanged |
| `--new-bundle-format=false` (legacy) | **tag** `sha256-<digest>.sig` | a new tag appears |

## Q4.c — verification, and why digests matter

| Step | Result |
|---|---|
| `cosign verify` by digest | **succeeds** |
| `cosign verify` by tag `v1.1.0`, while the tag points at the signed digest | **succeeds** |
| push different content to `v1.1.0`, then verify by tag | **`Error: no signatures found`** |
| verify the original digest again | **still succeeds** |

A textbook demonstration of ADR-028 §4.3. A signature binds to a digest; a tag is a pointer that
anyone with write access can move. Verifying by tag is verifying wherever the tag happens to
point right now.

## Q4.d — zot's trust verdict differs by format

```json
v1.1.0 (bundle): {"IsSigned": true, "SignatureInfo": [{"Tool": "cosign", "IsTrusted": false, "Author": ""}]}
v1.5.0 (legacy): {"IsSigned": true, "SignatureInfo": [{"Tool": "cosign", "IsTrusted": true,
                                                      "Author": "-----BEGIN PUBLIC KEY-----\nMFkwE…"}]}
```

Both match the brief's expectation exactly. The operational consequence is the finding:

> **zot v2.1.20 only actually *verifies* the legacy signature format, while cosign v3 produces
> bundles by default.** Signing with current defaults leaves zot reporting `IsSigned: true,
> IsTrusted: false` — it sees a signature and cannot check it.

And it pulls against the transfer requirement: see Q4/Phase 9 below.

## Q4.e — Argo CD does not care, at all

The `v1.1.0` tag was moved to **unsigned** content and the Application refreshed:

```json
{ "targetRevision": "v1.1.0", "sync": "Synced", "health": "Healthy",
  "revision": "sha256:1522ba14cf8c…", "resources": 2, "conditions": [] }
```

`oras discover` on that digest returned no referrers. That observation alone did not exclude
a legacy `.sig` tag. The revised Q4 experiment checks both formats and a failed signature
verification before recording the unsigned Application result. Argo CD raised **no condition, no warning, nothing**.

**This is the decisive result for criterion K2.** Argo CD v3.5.6's "Source Integrity" feature
covers Git GPG only; there is no signature verification for OCI sources. Signing today is
*evidence*, not *enforcement*.

## Q4.f — enforcement options (documentation)

| Option | Assessment |
|---|---|
| **Promotion gate in CI**: `cosign verify`, then promote by digest | **Recommended.** Verification happens where the key material already is, and what reaches the cluster is a digest-pinned Application. Works today, no new components. |
| **Config Management Plugin** that verifies before rendering | Possible, but puts key distribution and verification inside the repo-server and makes every sync depend on custom code in the critical path. |
| **Admission policy** (Kyverno, sigstore policy-controller) | Verifies **container images**, not the manifest artifact. Complementary, not a substitute — it would not have caught Q4.e. |
| **zot trust extension** | Informational only, and only for the legacy format. Useful as a dashboard signal, never as a gate. |

The gap is narrow and well understood: nothing between the registry and the cluster checks the
signature, so the check has to happen before the digest is written into an Application.

## Verdict

**PASS as an investigation; K2 is NOT met.** Signing, storage, verification and zot's trust
reporting all work and are fully characterised. What does not exist is any mechanism in
Argo CD v3.5.6 that would *prevent* an unsigned or tampered artifact from being synced.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| cosign v3.1.4 signs into zot offline, with no transparency-log upload | That the offline flags will keep working — both are deprecated |
| A signature binds to a digest and breaks when a tag is moved | That anyone notices — nothing in the sync path checks |
| zot verifies legacy-format signatures (`IsTrusted: true`) and only detects bundles | That zot's periodic re-verification works — only push-time verification was observed |
| Argo CD v3.5.6 syncs demonstrably unsigned content without any objection | That v3.6 behaves the same way — out of scope |
| A CI promotion gate would close the gap | That it has been built or tested — it is a design recommendation |
