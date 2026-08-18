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
    require(set(signals) == {"execution", "availability", "archiving"},
            "protection must expose independent execution, availability, and archiving signals")

    objects = [doc for doc in docs if doc.get("apiVersion") == "kubernetes.crossplane.io/v1alpha2" and doc.get("kind") == "Object"]
    require(len(objects) == 7, f"expected seven provider-kubernetes Objects, found {len(objects)}")
    require(all(obj["spec"]["providerConfigRef"]["name"] == "ok-robotics" for obj in objects),
            "every composed Object must target the XR clusterRef")
    manifests = [obj["spec"]["forProvider"]["manifest"] for obj in objects]
    kinds = {manifest["kind"] for manifest in manifests}
    require(kinds == {"Secret", "ClusterImageCatalog", "ObjectStore", "Cluster", "ScheduledBackup", "Backup", "Pooler"},
            f"unexpected composed manifest set: {sorted(kinds)}")

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
    provenance = {
        "images.cnpg.io/date": "20260815",
        "images.cnpg.io/publisher": "cnpg.io",
        "images.cnpg.io/type": "minimal",
        "images.cnpg.io/os": "trixie",
    }
    labels = catalog["metadata"].get("labels", {})
    require(all(labels.get(key) == value for key, value in provenance.items()),
            "governed catalog provenance labels must remain exact")
    image = catalog["spec"]["images"][0]["image"]
    require("@sha256:" in image, "PostgreSQL catalog image must be digest-pinned")
    extensions = catalog["spec"]["images"][0]["extensions"]
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
