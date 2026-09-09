#!/usr/bin/env python3
"""Find resources in a Database's namespace that the platform no longer manages.

PR #259 review finding 5. Orphans are not hypothetical here, and one was created by this very
ticket: renaming the composed Pooler from `<cluster>-rw` to `<cluster>-pooler-rw` left the OLD
Pooler behind on ok-robotics. `deletionPolicy: Delete` did not fire, because the Object still
exists and simply points at a different manifest name now — Crossplane deleted nothing, and the
old Pooler had to be removed by hand. Any rename of a composed manifest does this.

Detection is the precondition for any decommission workflow, so this is the detection half. It is
strictly READ-ONLY: it names what it found and what it would take to remove, and deletes nothing.
Deciding to delete data-bearing resources is not a script's call.

Classification, which is the part that has to be right:

    managed  - the platform composes it (a provider-kubernetes Object targets it by name)
    derived  - owned, transitively, by something managed. Scheduled backups live here: CNPG
               creates `<schedule>-<timestamp>` Backups owned by the ScheduledBackup, and the
               platform cannot enumerate generated names (§13 bound 3), so calling those orphans
               would flag healthy backups as garbage every single day.
    ORPHAN   - neither. Nothing the platform composes claims it, and nothing managed owns it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

# The CNPG-family kinds a Database composes or causes to exist. Deliberately explicit: a wildcard
# sweep would pull in unrelated workloads sharing the namespace and bury the real finding.
WATCHED_KINDS = (
    "cluster.postgresql.cnpg.io",
    "pooler.postgresql.cnpg.io",
    "scheduledbackup.postgresql.cnpg.io",
    "backup.postgresql.cnpg.io",
    "objectstore.barmancloud.cnpg.io",
)


class OrphanError(RuntimeError):
    pass


def kubectl_json(kubeconfig: str, *args: str) -> dict:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, *args, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OrphanError(f"kubectl {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout or "{}")


def composed_set(mgmt_kubeconfig: str, namespace: str) -> set[tuple[str, str]]:
    """What the platform composes, read from the management plane rather than from a render.

    The provider-kubernetes Objects ARE the authority on what is managed: each carries the exact
    manifest it applies. Rendering the Composition locally would answer a different question —
    what the current source WOULD compose — and would miss precisely the case that matters, where
    the installed revision differs from the working tree.
    """
    objects = kubectl_json(mgmt_kubeconfig, "get", "objects.kubernetes.crossplane.io")
    managed: set[tuple[str, str]] = set()
    for item in objects.get("items", []):
        manifest = item.get("spec", {}).get("forProvider", {}).get("manifest", {})
        meta = manifest.get("metadata", {})
        if meta.get("namespace") != namespace:
            continue
        kind = manifest.get("kind")
        name = meta.get("name")
        if kind and name:
            managed.add((kind, name))
    return managed


def live_resources(workload_kubeconfig: str, namespace: str) -> list[dict]:
    found = []
    for kind in WATCHED_KINDS:
        try:
            listing = kubectl_json(workload_kubeconfig, "get", kind, "-n", namespace)
        except OrphanError as exc:
            # A CRD that is not installed is not a finding; a real failure is.
            if "the server doesn't have a resource type" in str(exc):
                continue
            raise
        found.extend(listing.get("items", []))
    return found


def classify(resources: list[dict], managed: set[tuple[str, str]]) -> dict[str, list[str]]:
    by_uid = {r["metadata"]["uid"]: r for r in resources}
    verdicts: dict[str, list[str]] = {"managed": [], "derived": [], "orphan": []}

    def is_managed(resource: dict) -> bool:
        return (resource["kind"], resource["metadata"]["name"]) in managed

    def owned_by_managed(resource: dict, seen: set[str]) -> bool:
        """Walk ownerReferences upward; a managed ancestor makes this legitimately derived."""
        uid = resource["metadata"]["uid"]
        if uid in seen:
            return False
        seen.add(uid)
        for owner in resource["metadata"].get("ownerReferences", []) or []:
            if (owner.get("kind"), owner.get("name")) in managed:
                return True
            parent = by_uid.get(owner.get("uid"))
            if parent is not None and owned_by_managed(parent, seen):
                return True
        return False

    for resource in resources:
        label = f"{resource['kind']}/{resource['metadata']['name']}"
        if is_managed(resource):
            verdicts["managed"].append(label)
        elif owned_by_managed(resource, set()):
            verdicts["derived"].append(label)
        else:
            verdicts["orphan"].append(label)
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mgmt-kubeconfig", required=True, help="management plane (Crossplane)")
    parser.add_argument("--workload-kubeconfig", required=True, help="cluster hosting the database")
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()

    try:
        managed = composed_set(args.mgmt_kubeconfig, args.namespace)
        if not managed:
            raise OrphanError(
                f"the management plane composes nothing into {args.namespace}. Refusing to report "
                "every resource as an orphan: an empty managed set means the wrong namespace or "
                "the wrong kubeconfig far more often than it means total abandonment"
            )
        resources = live_resources(args.workload_kubeconfig, args.namespace)
        verdicts = classify(resources, managed)
    except OrphanError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    print(f"  managed by the platform ({len(verdicts['managed'])}):")
    for label in sorted(verdicts["managed"]):
        print(f"    {label}")
    print(f"  derived from a managed resource ({len(verdicts['derived'])}):")
    for label in sorted(verdicts["derived"]):
        print(f"    {label}")

    if not verdicts["orphan"]:
        print("OK: no orphans — every resource is composed or owned by something composed")
        return 0

    print(f"  ORPHANED ({len(verdicts['orphan'])}):", file=sys.stderr)
    for label in sorted(verdicts["orphan"]):
        print(f"    {label}", file=sys.stderr)
    print(
        "\nFAIL: the above are claimed by nothing the platform composes. Renaming a composed\n"
        "manifest is the usual cause: the Object keeps existing and just points elsewhere, so\n"
        "deletionPolicy never fires and the previous resource is left behind. Some orphans are\n"
        "legitimate — a drill artifact, a deliberate manual backup — so review before removing,\n"
        "and never delete a data-bearing resource because a script listed it.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
