# Prove an upgrade and a rollback without risking the live registry

This procedure stands a scratch registry up on the **older** zot version, restores real registry
content into it, upgrades it to the pinned version, rolls it back with `helm rollback`, and proves
the artifact data survived every transition. It never writes to the live registry.

This is the evidence for ADR-Platform-028 §8's upgrade / rollback criterion.

## Why this does not run against the live registry

At the time of writing there is **nothing to upgrade the live registry to**: the newest zot release
and the newest chart tag are both already pinned in `values-ok-shared.yaml`. An upgrade test needs
two versions, so the drill supplies the older one on a registry nobody depends on.

Do **not** "solve" this by downgrading the live registry and calling the return leg an upgrade. The
first leg is a downgrade whatever it is called, and a registry writes on-disk state that an older
build may not read — so that plan aims the risky direction at a shared service. On a scratch
registry the same incompatibility is a finding.

## What this proves, and what it does not

Proven: the chart's upgrade path, Helm's rollback mechanism, and artifact-data survival across both
transitions for the specific version pair used.

Not proven: that the **live** release survives an upgrade — no version exists to move it to — and
nothing about a version pair other than the one you run. When upstream ships a newer zot, re-run
this with `OLD_IMAGE` set to the currently pinned version and the values file bumped to the new one.

## The assertion that carries the weight

A scratch registry is ephemeral by default (`persistence: false`). On an ephemeral registry the
upgrade's pod restart discards the data for reasons that have nothing to do with the upgrade, so
"the data survived" would be an empty claim. `SCRATCH_PERSISTENCE=yes` gives the drill a PVC, and
the real evidence is then:

> the **PVC UID stays constant** while the **pod UID changes** at each transition

Pod UID changing proves the workload really was replaced. PVC UID constant proves the same volume
carried through. Either alone means nothing.

## 0. Preconditions

Take a fresh backup first — it is both the content this drill restores and your fallback:

```bash
ZOT_SHELF="$PWD/openkubes/platform/registry/zot"
BACKUP_DIR=/path/on/operator-retained-storage/upgrade-drill
install -d -m 700 "$BACKUP_DIR"
oks && make -C "$ZOT_SHELF" backup KUBECONFIG="$KUBECONFIG" BACKUP_DIR="$BACKUP_DIR"
```

Record the two printed paths as `RESTORE_ARTIFACT` and `INTEGRITY_MANIFEST`, then record the live
baseline you will compare against at the end:

```bash
oks && LIVE_POD_BEFORE="$(kubectl -n zot get pod zot-0 \
  -o jsonpath='{.metadata.uid}{"  "}{.status.containerStatuses[0].restartCount}')"
oks && LIVE_PVC_BEFORE="$(kubectl -n zot get pvc zot-pvc-zot-0 -o jsonpath='{.metadata.uid}')"
oks && LIVE_REV_BEFORE="$(helm -n zot history zot | tail -1 | awk '{print $1}')"
printf 'LIVE_POD_BEFORE=%s\nLIVE_PVC_BEFORE=%s\nLIVE_REV_BEFORE=%s\n' \
  "$LIVE_POD_BEFORE" "$LIVE_PVC_BEFORE" "$LIVE_REV_BEFORE"
```

Pick the version to upgrade **from**. It must be digest-pinned; the tooling rejects a bare tag.

```bash
OLD_IMAGE='v2.1.19@sha256:91bad7bc689d64ed80ba56435e957e82dd2cf0d83c686a76bbaeceb23d923606'
```

## 1. Stand the scratch registry up on the old version, with the real content

Attended: `restore-drill` requires a terminal. `RETAIN_SCRATCH=yes` is **required** here — without
it the drill tears the registry down and there is nothing left to upgrade.

```bash
oks && SCRATCH_IMAGE_TAG="$OLD_IMAGE" SCRATCH_UI=yes SCRATCH_PERSISTENCE=yes \
  make -C "$ZOT_SHELF" restore-drill \
    KUBECONFIG="$KUBECONFIG" \
    RESTORE_ARTIFACT="$RESTORE_ARTIFACT" \
    INTEGRITY_MANIFEST="$INTEGRITY_MANIFEST" \
    APPROVE_RESTORE_DRILL=yes RETAIN_SCRATCH=yes
```

It ends with `RESULT: PASS` and prints the retained namespace. Capture it, and pick any restored
manifest as the marker to follow through the drill:

```bash
NS=<printed zot-restore-drill-* namespace>
REL=zot-restore-drill
MARKER_REPO=<a repository the run reported restoring>
MARKER_DIGEST=<its immutable digest>
```

`SCRATCH_UI=yes` also makes the restored content browsable — see step 5.

## 2. Record the pre-upgrade shape, and prove the data is there first

Proving the data *after* an upgrade means nothing unless you showed it was there *before*.

```bash
oks && STS_UID_BEFORE="$(kubectl -n "$NS" get sts "$REL" -o jsonpath='{.metadata.uid}')"
oks && SCRATCH_PVC_BEFORE="$(kubectl -n "$NS" get pvc -o jsonpath='{.items[0].metadata.uid}')"
oks && POD_UID_BEFORE="$(kubectl -n "$NS" get pod "$REL-0" -o jsonpath='{.metadata.uid}')"

kubectl -n "$NS" port-forward "svc/$REL" 18111:5000 >/tmp/updrill-pf.log 2>&1 &
PF=$!
until grep -q 'Forwarding from 127.0.0.1:18111' /tmp/updrill-pf.log; do sleep 0.5; done

pull_marker() {  # echoes the sha256 of the returned manifest bytes
  curl -s --max-time 20 \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.oci.image.index.v1+json' \
    "http://127.0.0.1:$1/v2/$MARKER_REPO/manifests/$MARKER_DIGEST" \
  | sha256sum | cut -d' ' -f1 | sed 's/^/sha256:/'
}
count_repos() {
  curl -s --max-time 20 "http://127.0.0.1:$1/v2/_catalog?n=1000" \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("repositories",[])))'
}

MARKER_BEFORE="$(pull_marker 18111)"; REPOS_BEFORE="$(count_repos 18111)"
printf 'MARKER_BEFORE=%s\nREPOS_BEFORE=%s\n' "$MARKER_BEFORE" "$REPOS_BEFORE"
kill $PF
```

`MARKER_BEFORE` must equal `MARKER_DIGEST`. If it does not, stop: the restore did not produce what
it claimed and there is no point upgrading it.

## 3. Upgrade to the pinned version

`--reuse-values` keeps the scratch's hardening and config and changes only the image, which is what
a real version bump does.

```bash
NEW_IMAGE="$(python3 -c 'import yaml;i=yaml.safe_load(open("'"$ZOT_SHELF"'/values-ok-shared.yaml"))["image"];print(i["tag"])')"
oks && helm upgrade "$REL" "$ZOT_SHELF/../../../../zot/charts/zot" -n "$NS" \
  --reuse-values --set-string "image.tag=$NEW_IMAGE" --wait --timeout 5m
```

## 4. Prove the data survived the upgrade, then roll back and prove it again

```bash
check_after() {   # $1 = local port, $2 = label
  local marker repos pvc pod
  marker="$(pull_marker "$1")"; repos="$(count_repos "$1")"
  pvc="$(kubectl -n "$NS" get pvc -o jsonpath='{.items[0].metadata.uid}')"
  pod="$(kubectl -n "$NS" get pod "$REL-0" -o jsonpath='{.metadata.uid}')"
  # Every observation must be non-empty as well as equal: a failed query leaves a
  # variable empty, and empty == empty would read as "unchanged" having seen nothing.
  if test -n "$marker" && test -n "$repos" && test -n "$pvc" && test -n "$pod" \
    && test "$marker" = "$MARKER_DIGEST" \
    && test "$repos" = "$REPOS_BEFORE" \
    && test "$pvc" = "$SCRATCH_PVC_BEFORE" \
    && test "$pod" != "$POD_UID_BEFORE"; then
    printf '%s: DATA_SURVIVED=yes PVC_UID_UNCHANGED=yes POD_REPLACED=yes\n' "$2"
  else
    printf '%s: FAIL (an empty value means the query itself failed)\n  marker=%s want=%s\n  repos=%s want=%s\n  pvc=%s want=%s\n  pod=%s must differ from %s\n' \
      "$2" "${marker:-<none>}" "$MARKER_DIGEST" "${repos:-<none>}" "$REPOS_BEFORE" \
      "${pvc:-<none>}" "$SCRATCH_PVC_BEFORE" "${pod:-<none>}" "$POD_UID_BEFORE" >&2
    (exit 1)
  fi
}

kubectl -n "$NS" port-forward "svc/$REL" 18112:5000 >/tmp/updrill-pf2.log 2>&1 &
PF=$!
until grep -q 'Forwarding from 127.0.0.1:18112' /tmp/updrill-pf2.log; do sleep 0.5; done
check_after 18112 UPGRADE
kill $PF

oks && helm rollback "$REL" 1 -n "$NS" --wait --timeout 5m
oks && kubectl -n "$NS" get pod "$REL-0" \
  -o jsonpath='rolled back to: {.status.containerStatuses[0].imageID}{"\n"}'

kubectl -n "$NS" port-forward "svc/$REL" 18113:5000 >/tmp/updrill-pf3.log 2>&1 &
PF=$!
until grep -q 'Forwarding from 127.0.0.1:18113' /tmp/updrill-pf3.log; do sleep 0.5; done
check_after 18113 ROLLBACK
kill $PF

oks && helm -n "$NS" history "$REL"
```

`POD_REPLACED=yes` matters as much as the rest: if the pod UID had *not* changed, nothing restarted
and the drill proved nothing about surviving a restart. The rollback must also report the **old**
image digest — a rollback that leaves the new image running is not a rollback.

## 5. Optional: browse the restored content

`SCRATCH_UI=yes` enabled `search` and `ui`. Port-forward and open <http://127.0.0.1:8080/> — the UI
is served at the **root**, not at `/zot`.

```bash
oks && kubectl -n "$NS" port-forward "svc/$REL" 8080:5000
```

The retained scratch is **authless HTTP and reachable in-cluster through its ClusterIP**. It holds a
copy of everything in the backup. Browse it, then go straight to step 6.

## 6. Tear down and prove the live registry was untouched

Confirm the UIDs you are about to destroy are the scratch's, not the live registry's, before
deleting anything:

```bash
oks && kubectl -n "$NS" get sts,pvc -o custom-columns='KIND:.kind,NAME:.metadata.name,UID:.metadata.uid'
echo "live PVC UID must NOT appear above: $LIVE_PVC_BEFORE"

oks && helm uninstall "$REL" -n "$NS"
oks && kubectl delete ns "$NS" --wait=true --timeout=180s

oks && ALL_NS="$(kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"
SCRATCH_REMAINS="$(printf '%s\n' "$ALL_NS" | grep '^zot-restore-drill-' || true)"
oks && LIVE_POD_AFTER="$(kubectl -n zot get pod zot-0 \
  -o jsonpath='{.metadata.uid}{"  "}{.status.containerStatuses[0].restartCount}')"
oks && LIVE_PVC_AFTER="$(kubectl -n zot get pvc zot-pvc-zot-0 -o jsonpath='{.metadata.uid}')"
oks && LIVE_REV_AFTER="$(helm -n zot history zot | tail -1 | awk '{print $1}')"

if test -n "$ALL_NS" && test -z "$SCRATCH_REMAINS" \
  && test -n "$LIVE_POD_BEFORE" && test -n "$LIVE_POD_AFTER" \
  && test "$LIVE_POD_AFTER" = "$LIVE_POD_BEFORE" \
  && test "$LIVE_PVC_AFTER" = "$LIVE_PVC_BEFORE" \
  && test "$LIVE_REV_AFTER" = "$LIVE_REV_BEFORE"; then
  printf 'SCRATCH_ABSENT=yes\nLIVE_UNCHANGED=yes\n'
else
  printf 'FAIL: teardown or live isolation not proven (empty means the query failed)\n  scratch=%s\n  pod %s -> %s\n  pvc %s -> %s\n  rev %s -> %s\n' \
    "${SCRATCH_REMAINS:-<none>}" "${LIVE_POD_BEFORE:-<unobserved>}" "${LIVE_POD_AFTER:-<unobserved>}" \
    "${LIVE_PVC_BEFORE:-<unobserved>}" "${LIVE_PVC_AFTER:-<unobserved>}" \
    "${LIVE_REV_BEFORE:-<unobserved>}" "${LIVE_REV_AFTER:-<unobserved>}" >&2
  (exit 1)
fi
```

Retain the whole transcript with the backup pair. Do not tick any ADR-Platform-028 §8 criterion from
this procedure alone; acceptance stays owner-reviewed.
