#!/usr/bin/env python3
"""Generate the additive OK-141 capability-name-boundary amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
V8_PROFILE = HARNESS / "profiles/platform/minimal-observability-v8"
V9_PROFILE = HARNESS / "profiles/platform/minimal-observability-v9"
V8_CONTRACT = HARNESS / "fixtures/contracts-v8/base.yaml"
V9_CONTRACT = HARNESS / "fixtures/contracts-v9/base.yaml"
SOURCE = SPIKE.parents[3] / "ok-observability"

OLD_COMMIT = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
NEW_COMMIT = "c09c18759aeb7526d22106ccb001599f5f06bc4e"
OLD_SCRIPT_DIGEST = "sha256:bd68328f35de960bfc291880dd7f85274021c0cce8d7b69ccecde0a459ead648"
NEW_SCRIPT_DIGEST = "sha256:98f41106b7ddc2f7ecffaca9bd9e3c3584d97ab41b169054d8be91ae9cdfb949"
OLD_LOCK_DIGEST = "sha256:cdcc6f63b6202a89e90510ddb371cfd3130ff2ebc450336b3ee66e0f1fa85bf5"
NEW_LOCK_DIGEST = "sha256:f916900bccb3731636969145d4677dc0e1578cd16ab7cf053fb1afbbf047ce31"
BASE_IDENTITIES = {
    "fixtureDigest": "sha256:3ad6f2dbe82da2abc15e8dc44bbf2aabf5afcfd8cb54b54b2d2807fd815b7eba",
    "R": "sha256:81a57ef118e339a08e80608c64da7dd6eaed7d67dcdbcfa74a34636ab16dd35f",
    "P": "sha256:311a581894905faa1eb57f93f0d236a84a4a016e82c64c5f51ee7d6c1e29c952",
}
RENDER_INPUT_PATHS = [
    "profiles/ok-observability-standard/Chart.yaml",
    "profiles/ok-observability-standard/values.yaml",
    "profiles/ok-observability-standard/charts",
    "alerting/prometheus-rules.yaml",
    "dashboards/platform-overview-configmap.yaml",
]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_capability_boundary", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def update_leaf_digests(profile: dict, apps: list[dict]) -> None:
    by_name = {item["metadata"]["name"]: item for item in apps}
    for leaf in profile["requiredApplications"]:
        leaf["applicationDigest"] = V1.semantic_revision(by_name[leaf["name"]])


def git_bytes(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(SOURCE), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
    ).stdout


def assert_source_boundary() -> None:
    if not (SOURCE / ".git").exists():
        raise RuntimeError("ok-observability sibling source is unavailable")
    subprocess.run(
        ["git", "-C", str(SOURCE), "cat-file", "-e", f"{NEW_COMMIT}^{{commit}}"],
        check=True,
    )
    if V1.sha256_bytes(git_bytes(NEW_COMMIT, "tests/contract-test.sh")) != NEW_SCRIPT_DIGEST:
        raise RuntimeError("new capability script digest mismatch")
    if V1.sha256_bytes(git_bytes(NEW_COMMIT, "profiles/ok-observability-standard/artifact-lock.json")) != NEW_LOCK_DIGEST:
        raise RuntimeError("new artifact lock digest mismatch")
    unchanged = subprocess.run(
        ["git", "-C", str(SOURCE), "diff", "--quiet", OLD_COMMIT, NEW_COMMIT, "--", *RENDER_INPUT_PATHS],
        check=False,
    )
    if unchanged.returncode != 0:
        raise RuntimeError("authoritative rendered Platform inputs changed unexpectedly")


def main() -> None:
    assert_source_boundary()
    profile = json.loads((V8_PROFILE / "profile.json").read_text())
    apps = documents(V8_PROFILE / "applications.yaml")
    values = V1.read_yaml_or_json(V8_PROFILE / "provider-values.yaml")
    if V1.semantic_revision(profile) != BASE_IDENTITIES["P"]:
        raise RuntimeError("historical v8 Platform identity mismatch")

    v9_profile = copy.deepcopy(profile)
    v9_apps = copy.deepcopy(apps)
    v9_profile["format"] = "ok141-platform-profile/v8"
    v9_profile["profile"] = "minimal-observability-v9"
    v9_profile["capabilityCheck"]["executable"]["digest"] = NEW_SCRIPT_DIGEST
    for leaf in v9_profile["requiredApplications"]:
        leaf["source"]["commit"] = NEW_COMMIT
        if leaf["name"] == "disposable-ok141-observability-core":
            lock = leaf["sourceArtifacts"]["sourceClosure"]["artifactLock"]
            if lock["digest"] != OLD_LOCK_DIGEST:
                raise RuntimeError("historical artifact lock digest mismatch")
            lock["digest"] = NEW_LOCK_DIGEST
    for app in v9_apps:
        app["spec"]["source"]["targetRevision"] = NEW_COMMIT
    update_leaf_digests(v9_profile, v9_apps)

    V9_PROFILE.mkdir(parents=True, exist_ok=True)
    (V9_PROFILE / "profile.json").write_text(json.dumps(v9_profile, indent=2, sort_keys=True) + "\n")
    (V9_PROFILE / "applications.yaml").write_text(yaml.safe_dump_all(v9_apps, sort_keys=False))
    (V9_PROFILE / "provider-values.yaml").write_text(yaml.safe_dump(values, sort_keys=False))

    p9 = V1.semantic_revision(v9_profile)
    contract = V1.read_yaml_or_json(V8_CONTRACT)
    contract["spec"]["platform"] = {"profile": "minimal-observability-v9", "revision": p9}
    V9_CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    V9_CONTRACT.write_text(yaml.safe_dump(contract, sort_keys=False))
    schema = json.loads((HARNESS / "schema/contract-v3.schema.json").read_text())
    normalized = V1.normalize(contract, schema)
    V1.validate_contract_semantics(normalized)
    r9 = V1.semantic_revision(V1.semantic_projection(normalized, schema))

    fixture = {
        "format": "ok141-execution-fixture-amendment/capability-name-boundary-v1",
        "base": BASE_IDENTITIES,
        "basePlatform": {
            "profile": "minimal-observability-v8",
            "sourceCommit": OLD_COMMIT,
            "artifactLockDigest": OLD_LOCK_DIGEST,
            "capabilityScriptDigest": OLD_SCRIPT_DIGEST,
        },
        "platform": {
            "profile": "minimal-observability-v9",
            "profilePath": "harness/profiles/platform/minimal-observability-v9/profile.json",
            "applicationsPath": "harness/profiles/platform/minimal-observability-v9/applications.yaml",
            "providerValuesPath": "harness/profiles/platform/minimal-observability-v9/provider-values.yaml",
            "P": p9,
            "applicationSetDigest": V1.semantic_revision(v9_apps),
            "providerValuesDigest": V1.semantic_revision(values),
            "sourceCommit": NEW_COMMIT,
            "artifactLockDigest": NEW_LOCK_DIGEST,
            "capabilityScriptDigest": NEW_SCRIPT_DIGEST,
        },
        "contract": {
            "path": "harness/fixtures/contracts-v9/base.yaml",
            "schemaPath": "harness/schema/contract-v3.schema.json",
            "R": r9,
        },
        "semanticDelta": {
            "capabilityNameBoundaryCorrected": True,
            "capabilityExecutableChanged": True,
            "artifactLockProvenanceStrengthened": True,
            "sourceRevisionChanged": True,
            "desiredResourceSetChanged": False,
            "renderedPlatformSemanticsChanged": False,
            "applicationDesiredSpecsChangedOnlyByTargetRevision": True,
        },
        "authorization": "NO-GO",
    }
    fixture_digest = V1.semantic_revision(fixture)
    amendment = {
        "apiVersion": "test.openkubes.io/v1alpha1",
        "kind": "CapabilityNameBoundaryAmendment",
        "metadata": {"name": "ok141-capability-name-boundary-amendment-v1"},
        "spec": {
            **fixture,
            "fixtureDigest": fixture_digest,
            "identities": {"P": p9, "R": r9, "FixtureDigest": fixture_digest},
        },
    }
    (HERE / "capability-name-boundary-amendment-v1.json").write_text(
        json.dumps(amendment, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(amendment["spec"]["identities"], sort_keys=True))


if __name__ == "__main__":
    main()
