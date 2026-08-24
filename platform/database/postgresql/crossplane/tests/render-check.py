#!/usr/bin/env python3
"""Assert the locally rendered Database composition and t=0 evidence state."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(Path(path).read_text()) if isinstance(doc, dict)]


def validate(
    docs: list[dict],
    policy: str,
    expected_protection: tuple[str, str] | None = None,
) -> None:
    databases = [doc for doc in docs if doc.get("kind") == "Database" and "status" in doc]
    require(len(databases) == 1, f"expected one rendered Database status, found {len(databases)}")
    database = databases[0]
    evidence = database["status"]["evidence"]
    if expected_protection is None:
        require(
            (evidence["protection"].get("state"), evidence["protection"].get("reason"))
            == ("Unknown", "AwaitingFirstBackup"),
            "t=0 protection must be Unknown/AwaitingFirstBackup, got "
            f"{evidence['protection'].get('state')}/{evidence['protection'].get('reason')}",
        )
        require(
            (evidence["recovery"].get("state"), evidence["recovery"].get("reason"))
            == ("Unknown", "VerificationPending"),
            "t=0 recovery must be Unknown/VerificationPending, got "
            f"{evidence['recovery'].get('state')}/{evidence['recovery'].get('reason')}",
        )
        require(evidence["protection"]["state"] != "Stale" and evidence["recovery"]["state"] != "Stale",
                "never-proven evidence must not start Stale")
    else:
        expected_state, expected_reason = expected_protection
        protection = evidence["protection"]
        require(
            (protection.get("state"), protection.get("reason"))
            == (expected_state, expected_reason),
            "protection evidence mismatch: expected "
            f"{expected_state}/{expected_reason}, got "
            f"{protection.get('state')}/{protection.get('reason')}",
        )
    if policy == "production":
        require(database["status"]["serviceReady"] is False,
                "production must not render serviceReady=true with non-Valid evidence")
    elif expected_protection is None:
        require(database["status"]["serviceReady"] is False,
                "development must remain unready until operational evidence is Valid")

    signals = evidence["protection"].get("signals", {})
    require(set(signals) == {"execution", "availability", "archiving", "rpo"},
            "protection must expose independent execution, availability, archiving and rpo "
            "signals; rpo is §11.1's third signal and its absence is what let production reach "
            "Valid on ContinuousArchiving alone")

    objects = [doc for doc in docs if doc.get("apiVersion") == "kubernetes.crossplane.io/v1alpha2" and doc.get("kind") == "Object"]
    # Twelve now: the seven database resources plus five that compose the WAL-exposure collector
    # per Database. Verification ships WITH the capability rather than being hand-wired per cluster
    # — the hand-written CronJob named one cluster in six places and would not have survived a
    # second database, leaving whichever one was missed looking healthy while proving nothing.
    require(len(objects) == 12, f"expected twelve provider-kubernetes Objects, found {len(objects)}")
    require(all(obj["spec"]["providerConfigRef"]["name"] == "ok-robotics" for obj in objects),
            "every composed Object must target the XR clusterRef")
    manifests = [obj["spec"]["forProvider"]["manifest"] for obj in objects]
    kinds = {manifest["kind"] for manifest in manifests}
    require(kinds == {"Secret", "ClusterImageCatalog", "ObjectStore", "Cluster", "ScheduledBackup",
                      "Backup", "Pooler", "ServiceAccount", "Role", "RoleBinding", "CronJob"},
            f"unexpected composed manifest set: {sorted(kinds)}")

    # The collector must be namespaced and named from the XR, never from a literal. A composed
    # resource carrying a hardcoded cluster name is the defect this replaced.
    composed_cluster = next(m for m in manifests if m["kind"] == "Cluster")
    collector = [m for m in manifests if m["kind"] == "CronJob"]
    require(len(collector) == 1, f"expected one composed CronJob, found {len(collector)}")
    cron = collector[0]
    require(cron["metadata"]["namespace"] == composed_cluster["metadata"]["namespace"],
            "the collector must run in the database's own namespace")
    require(cron["metadata"]["name"].startswith(composed_cluster["metadata"]["name"]),
            f"the collector must be named from the composed cluster, got {cron['metadata']['name']}")
    # It publishes evidence; it must not be able to amend or delete it, and must never reach
    # recovery evidence — §7's approval act stays human.
    role = next(m for m in manifests if m["kind"] == "Role")
    verbs = {v for rule in role["rules"] for v in rule["verbs"]}
    require(not (verbs & {"delete", "patch", "update", "deletecollection"}),
            f"the collector Role grants mutating verbs on the database namespace: {sorted(verbs)}")

    # CNPG owns Services <cluster>-rw, -ro and -r for the Cluster itself, and a Pooler's name
    # becomes its Service name. No composed object may claim one of those names: the Pooler that
    # did sat phase=inactive for 28h on ok-robotics, re-emitting InvalidOwnership, because it
    # could not adopt a Service owned by the Cluster. Nothing asserted the name, which is exactly
    # how it shipped, so the rule is checked for every composed manifest rather than for Poolers.
    cluster = next(manifest for manifest in manifests if manifest["kind"] == "Cluster")
    reserved = {f"{cluster['metadata']['name']}-{suffix}" for suffix in ("rw", "ro", "r")}
    for manifest in manifests:
        if manifest["kind"] == "Cluster":
            continue
        name = manifest["metadata"]["name"]
        require(
            name not in reserved,
            f"composed {manifest['kind']} is named {name!r}, which CNPG already owns as a "
            f"Cluster Service ({sorted(reserved)}); it can never take ownership of that name",
        )

    secret = next(manifest for manifest in manifests if manifest["kind"] == "Secret")
    require("data" not in secret and "stringData" not in secret,
            "rendered Secret must contain references only, never credential values")
    require(secret["metadata"].get("labels", {}).get("cnpg.io/reload") == "true",
            "managed credential Secret must carry cnpg.io/reload=true")
    store = next(manifest for manifest in manifests if manifest["kind"] == "ObjectStore")
    require(store["spec"]["configuration"]["destinationPath"] == "s3://ok-db-backups",
            "backup root must derive its server folder only from the CNPG serverName")
    store_config = store["spec"]["configuration"]
    require(store_config["endpointURL"].startswith("https://"),
            "backup store endpoint must be https: backup data and its credentials must not cross a plaintext connection")
    require(store_config.get("endpointCA", {}).get("name"),
            "an https backup store endpoint must name the CA Secret that validates it")
    store_credentials = {
        store_config["s3Credentials"]["accessKeyId"]["name"],
        store_config["s3Credentials"]["secretAccessKey"]["name"],
    }
    require(all(name.endswith("-writer") for name in store_credentials),
            "the database's backup store identity must be the role-named writer Secret")
    require(not any(name.endswith("-reader") for name in store_credentials),
            "the database's backup store must never authenticate with a read-only source identity")
    cluster = next(manifest for manifest in manifests if manifest["kind"] == "Cluster")
    if policy == "production":
        require(cluster["spec"].get("primaryUpdateStrategy") == "supervised",
                "HA consequential Cluster updates must remain supervised")
    else:
        require("primaryUpdateStrategy" not in cluster["spec"],
                "CNPG rejects supervised primary updates for a single-instance Cluster")
    require(cluster["spec"]["plugins"][0]["parameters"]["serverName"] == "ok-robotics",
            "plugin serverName must equal the single protected CNPG cluster identity")
    require("backup" not in cluster["spec"], "deprecated in-tree Cluster backup surface must be absent")
    catalog = next(manifest for manifest in manifests if manifest["kind"] == "ClusterImageCatalog")
    catalog_image = catalog["spec"]["images"][0]
    # A requested capability is delivered by the BUNDLED `standard` image, because the catalogued
    # per-extension image-volume model needs containerd >= 2.1.0 and these nodes run 2.0.x. So the
    # provenance type follows the delivery mechanism rather than being a constant, and the two must
    # agree: a `standard` label on a minimal image (or the reverse) would misstate what is running.
    bundled = "-standard-" in catalog_image["image"]
    provenance = {
        "images.cnpg.io/date": "20260815",
        "images.cnpg.io/publisher": "cnpg.io",
        "images.cnpg.io/type": "standard" if bundled else "minimal",
        "images.cnpg.io/os": "trixie",
    }
    labels = catalog["metadata"].get("labels", {})
    require(all(labels.get(key) == value for key, value in provenance.items()),
            f"governed catalog provenance labels must remain exact and match the image actually "
            f"pinned ({'standard' if bundled else 'minimal'}); got {labels}")
    require("@sha256:" in catalog_image["image"],
            "the catalog image must be digest-pinned, not tag-only: a re-pushed tag would change "
            "what runs while every recorded proof still looked valid")
    # Declaring spec.postgresql.extensions IS the image-volume mechanism, so it must not reappear
    # alongside a bundled image — that combination is what stops the instance starting.
    if bundled:
        require("extensions" not in catalog_image,
                "a bundled image must not also carry catalogued extension images: that is the "
                "image-volume path, which containerd 2.0.x cannot mount")
        # Must be EMPTY rather than absent: omitting it leaves a previous value in place on the
        # target cluster, which put ok-robotics into "incomplete or invalid image catalog".
        declared = (cluster["spec"].get("postgresql") or {}).get("extensions", None)
        require(declared == [],
                "a bundled image must declare spec.postgresql.extensions as an EMPTY list, not "
                f"omit it: omission does not clear a previously set value. Got {declared!r}")
    # The catalogued per-extension images are the image-volume model, which is unusable on
    # containerd 2.0.x and therefore not composed. When it returns (containerd >= 2.1.0), these
    # assertions apply again — §6.4's governance lives here, so keep them rather than deleting.
    extensions = catalog_image.get("extensions")
    if extensions is not None:
        require([extension["name"] for extension in extensions] == ["pgvector"],
                "platform catalog must expose only the approved pgvector extension")
        require("@sha256:" in extensions[0]["image"]["reference"],
                "pgvector catalog image must be digest-pinned")

    rendered = yaml.safe_dump_all(docs)
    # ObjectStore recovery-window fields are valid normalized status. Only the
    # deprecated Cluster status-by-method and in-tree backup surfaces are banned.
    for forbidden in ("lastSuccessfulBackupByMethod", "firstRecoverabilityPointByMethod",
                      "barmanObjectStore"):
        require(forbidden not in rendered, f"render contains forbidden/deprecated field {forbidden}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rendered")
    parser.add_argument("--policy", choices=("development", "production"), required=True)
    parser.add_argument("--expected-protection-state", choices=("Pending", "Valid", "Stale", "Failed", "Unknown"))
    parser.add_argument("--expected-protection-reason")
    args = parser.parse_args()
    docs = load(args.rendered)
    expected_protection = None
    if args.expected_protection_state or args.expected_protection_reason:
        require(
            bool(args.expected_protection_state and args.expected_protection_reason),
            "both expected protection state and reason are required",
        )
        expected_protection = (
            args.expected_protection_state,
            args.expected_protection_reason,
        )
    validate(docs, args.policy, expected_protection)
    print(f"OK: {args.policy} render has exact Objects and expected evidence")


if __name__ == "__main__":
    main()
