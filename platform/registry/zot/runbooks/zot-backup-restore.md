# Back up and restore registry-default

This is the interim OK-138 recovery procedure for `registry-default` on `ok-shared`. It exports
OCI content through the Distribution API while the live zot remains Ready. It never mounts,
snapshots, scales, restarts or writes the live registry PVC.

The export target is an operator-supplied directory on storage outside the Kubernetes cluster.
That separation protects the copy from deletion of zot's `local-path` PVC. The operator is still
responsible for choosing retained storage with the required durability, access control and
replication. A workstation directory proves off-cluster export and recovery but is not, by itself,
production-approved durable storage. When OK-81 provides MinIO for `ok-shared`, point
`BACKUP_DIR` at the sanctioned MinIO-backed export target; do not deploy another object store for
the registry.

## Take an off-cluster export

Run from an attended shell at the workspace root. Use `oks` in the same shell expression; never
export `KUBECONFIG` manually.

```bash
ZOT_SHELF="$PWD/openkubes/platform/registry/zot"
BACKUP_DIR="/path/on/operator-retained-storage/registry-default"
install -d -m 700 "$BACKUP_DIR"
oks && make -C "$ZOT_SHELF" backup \
  KUBECONFIG="$KUBECONFIG" BACKUP_DIR="$BACKUP_DIR"
```

The target enumerates repositories and tags through the OCI Distribution catalog, resolves each
manifest to its immutable digest, follows OCI Referrers descriptors, and copies every discovered
manifest and blob into a local OCI image layout. Credentials are read from
`zot-machine-identities` and supplied to clients through an inherited file descriptor; they are
not written to argv, logs, the artifact or a temporary file.

Success publishes two mode-600 files atomically and prints their paths:

- `zot-<timestamp>-<pid>.tar` — the OCI layout and its source inventory;
- `zot-<timestamp>-<pid>.integrity.json` — a detached integrity manifest.

Copy the two printed absolute paths into shell variables; `make` cannot set its caller's
environment. Keep these assignments in the same attended shell for the remaining procedure:

```bash
RESTORE_ARTIFACT="<printed BACKUP_ARTIFACT path>"
INTEGRITY_MANIFEST="<printed INTEGRITY_MANIFEST path>"
test -f "$RESTORE_ARTIFACT" && test -f "$INTEGRITY_MANIFEST"
```

The artifact embeds `inventory.json`, which records the source registry, every discovered
repository/tag/digest and referrer relationship, and the representative repository/digest recorded
before export. The detached integrity manifest records the artifact basename, byte size and
SHA-256 plus the embedded inventory's byte size and SHA-256. The backup target recomputes both
commitments and verifies that every `blobs/sha256/<hex>` entry in the unpacked OCI layout hashes to
`<hex>` before printing PASS. A later operator can therefore detect truncation or alteration
without contacting the source registry by running the restore drill's validation phase.

This is integrity, not authenticity. An attacker able to replace both the artifact and its detached
manifest can construct a self-consistent replacement; no signing key or trusted timestamp is used.
The catalog also cannot reveal an untagged manifest that is neither referenced by a discovered
manifest nor otherwise listed by the Distribution API. Concurrent writes can make the export a
valid but non-transactional view across repositories. Retention or write quiescence is a separate
operational policy.

The interim credentials impose two further boundaries. The union covers the current normal
`openkubes/{machine,human}/**` prefixes, but cannot certify that a `platform-admins` user has not
created an invisible repository elsewhere. It also reuses two write-capable identities even though
the script itself sends only reads. A distinct read-only, all-repository exporter identity is the
correct steady state, but adding it requires an approved policy/htpasswd rollout and zot restart;
this drill must not take that outage while other tickets depend on the live registry.

## Prove the verifier rejects tampering

Never damage the retained artifact. Copy it into the retained backup work directory, change one
byte in that copy, and give the copy to `restore-drill` with the original integrity manifest. The
integrity check runs before cluster mutation and must reject it. Remove the corrupt copy after
capturing the failure; the published artifact remains unchanged.

```bash
TAMPER_DIR="$(mktemp -d)"
chmod 700 "$TAMPER_DIR"
cp -- "$RESTORE_ARTIFACT" "$TAMPER_DIR/$(basename "$RESTORE_ARTIFACT")"
printf X | dd of="$TAMPER_DIR/$(basename "$RESTORE_ARTIFACT")" bs=1 seek=512 count=1 conv=notrunc status=none
make -C "$ZOT_SHELF" verify-backup \
  RESTORE_ARTIFACT="$TAMPER_DIR/$(basename "$RESTORE_ARTIFACT")" \
  INTEGRITY_MANIFEST="$INTEGRITY_MANIFEST"
rm -r -- "$TAMPER_DIR"
```

Expected effect: failure names the size or SHA-256 mismatch, no scratch namespace is created, and
the live registry is not contacted as a destination.

## Run the isolated restore drill

Review the two published files and record the live PVC identity before the drill, then run:

```bash
oks && PVC_BEFORE="$(kubectl get pvc zot-pvc-zot-0 -n zot \
  -o jsonpath='{.metadata.uid}{"  "}{.metadata.creationTimestamp}')"
printf 'PVC_BEFORE=%s\n' "$PVC_BEFORE"

oks && make -C "$ZOT_SHELF" restore-drill \
  KUBECONFIG="$KUBECONFIG" \
  RESTORE_ARTIFACT="$RESTORE_ARTIFACT" \
  INTEGRITY_MANIFEST="$INTEGRITY_MANIFEST" \
  APPROVE_RESTORE_DRILL=yes
```

The attended approval creates a unique `zot-restore-drill-*` namespace and installs the pinned zot
chart there as a second release named `zot-restore-drill`. The scratch registry is authless,
HTTP-only, `ClusterIP`-only and ephemeral (`persistence=false`). It has no Ingress, certificate,
OIDC configuration, live Secret mount or live PVC mount. The restore destination is not an operator
variable: the script constructs it only as `127.0.0.1:<ephemeral-port>` through `kubectl
port-forward` to the just-created scratch Service. It rejects any live namespace/release value and
re-checks the scratch labels and Service shape before pushing. Consequently a wrong environment
variable cannot redirect restored bytes to `registry.ok-shared.internal`.

The drill pushes the recorded OCI entries with digest preservation, retrieves the representative
manifest from scratch by the exact digest recorded before backup, and hashes the returned manifest
bytes. PASS requires the computed `sha256:<hex>` to equal the recorded digest exactly.

By default the cleanup trap uninstalls the scratch Helm release, deletes its namespace and proves
the namespace is absent. The mode-700 local work directory is always retained and printed, matching
the Keycloak recovery precedent; it contains extracted artifact content but no credential.

For diagnosis only, `RETAIN_SCRATCH=yes` leaves the scratch namespace running. This creates an
unmonitored second copy of every restored artifact. The operator must isolate access, investigate
immediately, then run the exact `helm uninstall` and `kubectl delete namespace` commands printed by
the drill and prove the namespace is gone. Retention must never become a scheduled default.

## Reconstruct service configuration

The content artifact deliberately excludes live OIDC/authz configuration and credentials.
`config.json` is rendered from the version-controlled `values-ok-shared.yaml`; the namespace,
identities, TLS route, metrics registration and OIDC client are reconstructed by the existing
Makefile targets and templates. The bcrypt htpasswd Secret and its separate cleartext machine
identity Secret are a pair and must be recovered from their sanctioned secret escrow or recreated
together, followed by the already-documented zot restart required for credential rotation. The
OIDC client secret and session keys similarly belong in secret escrow, not in an artifact-content
tarball.

This is the honest recovery boundary: repository configuration is reproducible from Git, while
secret values are not. Until Vault/VSO escrow is implemented for this profile, a full disaster
recovery claim requires an independently protected copy or approved recreation ceremony for those
Secrets. Never add them to this backup artifact.

## Post-drill live checks

Compare the live PVC UID and creation timestamp mechanically afterward:

```bash
oks && kubectl wait pod/zot-0 -n zot --for=condition=Ready --timeout=1s
oks && PVC_AFTER="$(kubectl get pvc zot-pvc-zot-0 -n zot \
  -o jsonpath='{.metadata.uid}{"  "}{.metadata.creationTimestamp}')"
printf 'PVC_AFTER=%s\n' "$PVC_AFTER"
test "$PVC_AFTER" = "$PVC_BEFORE"
printf 'PVC_IDENTITY_UNCHANGED=yes\n'
oks && make -C "$ZOT_SHELF" post-check KUBECONFIG="$KUBECONFIG"
```

PASS requires the live pod to remain Ready, the PVC UID and creation timestamp to be unchanged,
and `post-check` to pass. Do not tick or rewrite any ADR-Platform-028 §8 acceptance criterion from
this run alone.
