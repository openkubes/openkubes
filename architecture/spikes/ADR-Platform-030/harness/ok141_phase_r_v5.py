#!/usr/bin/env python3
"""Offline Phase-R v5 verifier for the external CAPK authority amendment."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from string import Template
from typing import Any

import yaml


HARNESS_DIR = Path(__file__).resolve().parent


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HARNESS_DIR / file)
    result = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


V4 = _module("ok141_phase_r_v4_for_v5", "ok141_phase_r_v4.py")
V2 = V4.V2
V1 = V4.V1
PLATFORM = V4.PLATFORM
FORMAT = "ok141-execution-fixture/v5"
VERSION = "phase-r-v5"
PROJECTION_VERSION = "ok141-contract-to-capi-projection/v2"
OK_CLUSTER_COMMIT = "c4bb72e368bdedb92d75485ce9972d86e8a75210"
OK_LINUX_COMMIT = "a1687263d46c48e47c14f5bf202c9a652d7c1a71"
SOURCE_FILES = {
    "renderer": (
        "render.py",
        "sha256:19a70213c6d47f6660b5794f8f0e0244e610055b17100bd78e1650659fc9526b",
    ),
    "talosResolver": (
        "profile_resolvers/talos.py",
        "sha256:d51633fd5e65b4e06b0c41e1a1f814790f4def08b19aeda1a6fd2a4b0cfdc550",
    ),
    "kubevirtTemplate": (
        "templates/talos/providers/kubevirt/cluster-base.yaml.tpl",
        "sha256:08a74622e2fe6f553ffba62fffb8601f905226db8d6f91d18b870a235cbd3566",
    ),
}


def _path(root: Path, requested: str) -> Path:
    candidate = (root / requested).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"fixture input is missing or outside root: {requested}")
    return candidate


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"Phase-R v5 {claim} mismatch")


def _documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _verify_source(root: Path, relative: str, digest: str) -> Path:
    path = root / relative
    if not path.is_file() or V1.sha256_bytes(path.read_bytes()) != digest:
        raise V1.HarnessError(f"pinned source digest mismatch: {relative}")
    return path


def _expected_access(contract: dict[str, Any]) -> dict[str, Any]:
    identity = contract["metadata"]
    access = contract["spec"]["infrastructure"]["providerAccess"]
    expected_ref = {
        "apiVersion": "v1",
        "kind": "Secret",
        "name": f"external-infra-kubeconfig-{identity['name']}",
        "namespace": identity["namespace"],
    }
    _expect(access["secretRef"], expected_ref, "per-cluster provider Secret reference")
    _expect(access["targetNamespace"], identity["namespace"], "provider target namespace")
    _expect(access["managementPlane"], "ok-mgmt", "provider management plane")
    _expect(access["providerPlane"], "ok-infra", "provider infrastructure plane")
    return access


def load_contract(contract_path: Path, schema_path: Path) -> tuple[dict[str, Any], str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    normalized = V1.normalize(V1.read_yaml_or_json(contract_path), schema)
    V1.validate_contract_semantics(normalized)
    _expected_access(normalized)
    projected = V1.semantic_projection(normalized, schema)
    return normalized, V1.semantic_revision(projected)


def raw_renderer_input(contract: dict[str, Any]) -> dict[str, Any]:
    result = V2.raw_renderer_input(contract)
    access = _expected_access(contract)
    result["infraClusterSecretRef"] = {
        key: access["secretRef"][key] for key in ("name", "namespace")
    }
    return result


def _load_ok_cluster(ok_cluster_root: Path):
    _expect(_git_head(ok_cluster_root), OK_CLUSTER_COMMIT, "ok-cluster source commit")
    renderer = _verify_source(ok_cluster_root, *SOURCE_FILES["renderer"])
    _verify_source(ok_cluster_root, *SOURCE_FILES["talosResolver"])
    _verify_source(ok_cluster_root, *SOURCE_FILES["kubevirtTemplate"])
    sys.path.insert(0, str(ok_cluster_root))
    try:
        spec = importlib.util.spec_from_file_location("ok141_pinned_ok_cluster_v5", renderer)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def render_source(
    contract: dict[str, Any], ok_cluster_root: Path, ok_linux_root: Path
) -> tuple[dict[str, Any], str]:
    module = _load_ok_cluster(ok_cluster_root)
    V2._verify_source(ok_linux_root, *V2.OK_LINUX_PROFILE)
    raw = raw_renderer_input(contract)
    resolved = module.resolve_talos_config(raw, ok_linux_root)
    V2._verify_resolved_identity(contract, resolved)
    context = module.build_context(resolved)
    template_path = ok_cluster_root / SOURCE_FILES["kubevirtTemplate"][0]
    rendered = Template(template_path.read_text(encoding="utf-8")).safe_substitute(context)
    rendered = module.apply_node_selector(rendered, context["NODE_SELECTOR"])
    return resolved, rendered


def project_authorities(
    rendered: str, contract: dict[str, Any], revision: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    management, infrastructure, authority = V2.project_authorities(
        rendered, contract, revision
    )
    access = _expected_access(contract)
    kubevirt_cluster = next(
        item for item in management if item.get("kind") == "KubevirtCluster"
    )
    _expect(
        kubevirt_cluster.get("spec", {}).get("infraClusterSecretRef"),
        access["secretRef"],
        "rendered infraClusterSecretRef",
    )
    if any(item.get("kind") == "Secret" for item in management + infrastructure):
        raise V1.HarnessError("credential materialization escaped into projection")
    authority["format"] = PROJECTION_VERSION
    authority["providerAccess"] = {
        "mode": access["mode"],
        "managementPlane": access["managementPlane"],
        "providerPlane": access["providerPlane"],
        "secretRef": access["secretRef"],
        "targetNamespace": access["targetNamespace"],
        "materialization": "separate-gated-prerequisite-no-credential-bytes-in-fixture",
    }
    return management, infrastructure, authority


def _resource_documents(rendered: str) -> list[dict[str, Any]]:
    return [item for item in yaml.safe_load_all(rendered) if item]


def render_projection(args: argparse.Namespace) -> None:
    contract, revision = load_contract(args.contract, args.schema)
    resolved, source = render_source(contract, args.ok_cluster_root, args.ok_linux_root)
    management, infrastructure, authority = project_authorities(source, contract, revision)
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "renderer-input.yaml": yaml.safe_dump(raw_renderer_input(contract), sort_keys=False),
        "resolved-renderer-input.yaml": yaml.safe_dump(resolved, sort_keys=False),
        "renderer-source.yaml": source,
        "ok-mgmt-lifecycle.yaml": yaml.safe_dump_all(management, sort_keys=False, explicit_start=True),
        "ok-infra-prerequisites.yaml": yaml.safe_dump_all(infrastructure, sort_keys=False, explicit_start=True),
        "authority-map.json": V1.jcs(authority) + "\n",
    }
    for name, content in artifacts.items():
        (args.output / name).write_text(content, encoding="utf-8")
    source_documents = _resource_documents(source)
    manifest = {
        "format": PROJECTION_VERSION,
        "authorizationState": "NO-GO",
        "R": revision,
        "source": {
            "okClusterCommit": OK_CLUSTER_COMMIT,
            "okLinuxCommit": _git_head(args.ok_linux_root),
            "files": {
                name: {"path": path, "digest": digest}
                for name, (path, digest) in SOURCE_FILES.items()
            },
            "okLinuxProfile": {
                "path": V2.OK_LINUX_PROFILE[0],
                "digest": V2.OK_LINUX_PROFILE[1],
            },
        },
        "providerAccess": authority["providerAccess"],
        "artifacts": {
            name: V1.sha256_bytes((args.output / name).read_bytes())
            for name in artifacts
        },
        "objectSets": {
            "rendererSource": {
                "count": len(source_documents),
                "digest": V1.semantic_revision(source_documents),
            },
            "okMgmtLifecycle": {
                "count": len(management),
                "digest": V1.semantic_revision(management),
            },
            "okInfraPrerequisites": {
                "count": len(infrastructure),
                "digest": V1.semantic_revision(infrastructure),
            },
        },
    }
    (args.output / "projection-manifest.json").write_text(
        V1.jcs(manifest) + "\n", encoding="utf-8"
    )
    print(revision)


def validate(document: dict[str, Any], root: Path) -> str:
    root = root.resolve()
    _expect(document.get("format"), FORMAT, "format")
    _expect(document.get("fixtureVersion"), VERSION, "version")
    _expect(document.get("authorizationState"), "NO-GO", "authorization")

    schema_claim = document["fixtureSchema"]
    schema_path = _path(root, schema_claim["path"])
    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes)
    _expect(schema.get("$id"), FORMAT, "schema identity")
    _expect(V1.sha256_bytes(schema_bytes), schema_claim["digest"], "schema digest")
    V1.normalize(document, schema)

    supersedes = document["supersedes"]
    _expect(supersedes.get("fixtureVersion"), "phase-r-v4", "superseded version")
    _expect(
        supersedes.get("fixtureDigest"),
        "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6",
        "superseded digest",
    )
    _expect(
        supersedes.get("disposition"),
        "valid-historical-superseded-not-mutated",
        "superseded disposition",
    )

    contract_claim = document["contract"]
    contract_path = _path(root, contract_claim["path"])
    contract_schema_path = _path(root, contract_claim["schemaPath"])
    contract, revision = load_contract(contract_path, contract_schema_path)
    _expect(V1.sha256_bytes(contract_path.read_bytes()), contract_claim["rawArtifactDigest"], "raw contract digest")
    _expect(V1.sha256_bytes(contract_schema_path.read_bytes()), contract_claim["schemaDigest"], "contract schema digest")
    _expect(revision, contract_claim["R"], "R")
    _expect(contract["metadata"], document["contractIdentity"], "contract identity")
    spec = contract["spec"]
    _expect(
        document["clusterSemantics"],
        {key: spec[key] for key in ("kubernetesVersion", "infrastructure", "operatingSystem", "topology", "connectivity")},
        "cluster semantics",
    )

    platform = document["platform"]
    profile_path = _path(root, platform["profilePath"])
    apps_path = _path(root, platform["applicationsPath"])
    values_path = _path(root, platform["providerValuesPath"])
    profile = json.loads(profile_path.read_text())
    apps = _documents(apps_path)
    provider_values = V1.read_yaml_or_json(values_path)
    p_revision = PLATFORM.validate_platform_source_amendment(profile, apps, provider_values)
    _expect(p_revision, platform["P"], "P")
    _expect(p_revision, spec["platform"]["revision"], "contract P")
    _expect(profile["profile"], spec["platform"]["profile"], "Platform profile")
    _expect(V1.semantic_revision(apps), platform["applicationSetDigest"], "Application set digest")
    _expect(V1.semantic_revision(provider_values), platform["providerValuesDigest"], "Provider Values digest")
    _expect(profile["target"]["immutableIdentityReference"]["scheme"], platform["immutableTargetIdentityScheme"], "target identity scheme")
    _expect({leaf["source"]["commit"] for leaf in profile["requiredApplications"]}, {platform["sourceCommit"]}, "Platform source commit")

    enablement = document["enablement"]
    enable_profile = json.loads(_path(root, enablement["profilePath"]).read_text())
    enable_values = V1.read_yaml_or_json(_path(root, enablement["valuesPath"]))
    e_revision = V1.validate_enablement_profile(enable_profile, enable_values)
    _expect(e_revision, enablement["E"], "E")
    _expect(e_revision, spec["enablement"]["revision"], "contract E")

    projection = document["projection"]
    manifest_path = _path(root, projection["manifestPath"])
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    _expect(V1.sha256_bytes(manifest_bytes), projection["manifestDigest"], "projection manifest digest")
    _expect(manifest["format"], PROJECTION_VERSION, "projection format")
    _expect(manifest["R"], revision, "projection R")
    _expect(manifest["source"]["okClusterCommit"], OK_CLUSTER_COMMIT, "projection source commit")
    _expect(manifest["source"]["okLinuxCommit"], OK_LINUX_COMMIT, "ok-linux source commit")
    _expect(
        manifest["source"]["files"],
        {
            name: {"path": path, "digest": digest}
            for name, (path, digest) in SOURCE_FILES.items()
        },
        "projection source files",
    )
    _expect(
        manifest["source"]["okLinuxProfile"],
        {"path": V2.OK_LINUX_PROFILE[0], "digest": V2.OK_LINUX_PROFILE[1]},
        "ok-linux profile source",
    )
    _expect(manifest["objectSets"], projection["objectSets"], "object sets")
    projection_dir = manifest_path.parent
    for artifact, digest in manifest["artifacts"].items():
        _expect(V1.sha256_bytes((projection_dir / artifact).read_bytes()), digest, f"projection artifact {artifact}")
    authority = json.loads(_path(root, projection["authorityMapPath"]).read_text())
    _expect(authority["format"], PROJECTION_VERSION, "authority format")
    _expect(authority["intentRevision"], revision, "authority R")
    _expect(authority["managementPlane"]["identity"], "ok-mgmt", "management authority")
    _expect(authority["infrastructurePlane"]["identity"], "ok-infra", "infrastructure authority")
    access = _expected_access(contract)
    expected_provider_access = {
        "mode": access["mode"],
        "managementPlane": access["managementPlane"],
        "providerPlane": access["providerPlane"],
        "secretRef": access["secretRef"],
        "targetNamespace": access["targetNamespace"],
        "materialization": "separate-gated-prerequisite-no-credential-bytes-in-fixture",
    }
    _expect(authority["providerAccess"], expected_provider_access, "provider access authority")
    _expect(manifest["providerAccess"], expected_provider_access, "provider access manifest")

    projected_sets = []
    for requested in (projection["managementObjectsPath"], projection["infrastructurePrerequisitesPath"]):
        documents = _documents(_path(root, requested))
        projected_sets.append(documents)
        for item in documents:
            _expect(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision"), revision, "object R carrier")
    _expect(len(projected_sets[0]), 8, "management object count")
    _expect(len(projected_sets[1]), 3, "infrastructure prerequisite count")
    kubevirt_cluster = next(item for item in projected_sets[0] if item.get("kind") == "KubevirtCluster")
    _expect(kubevirt_cluster["spec"].get("infraClusterSecretRef"), access["secretRef"], "projected infraClusterSecretRef")
    if any(item.get("kind") == "Secret" for items in projected_sets for item in items):
        raise V1.HarnessError("credential materialization escaped into projected object sets")
    if any(item.get("apiVersion", "").split("/", 1)[0] in V2.CAPI_GROUPS for item in projected_sets[1]):
        raise V1.HarnessError("CAPI lifecycle resource escaped to ok-infra")

    condition = document["conditions"]
    condition_profile = V1.read_yaml_or_json(_path(root, condition["profilePath"]))
    _expect(V1.semantic_revision(condition_profile), condition["profileDigest"], "condition profile")
    _expect(condition_profile["requiredConditions"], spec["conditions"]["required"], "condition membership")
    evidence = document["evidence"]
    evidence_bytes = _path(root, evidence["schemaPath"]).read_bytes()
    _expect(V1.sha256_bytes(evidence_bytes), evidence["schemaDigest"], "evidence schema digest")

    tools = document["tools"]
    _expect(V1.sha256_bytes(HARNESS_DIR.joinpath("ok141_phase_r_v5.py").read_bytes()), tools["phaseRV5ToolDigest"], "Phase-R v5 tool digest")
    ids = {item.get("id") for item in document["negativeControls"]}
    _expect(ids, V1.NEGATIVE_CONTROL_IDS, "negative controls")
    if any(item.get("expectedReady") == "True" for item in document["negativeControls"]):
        raise V1.HarnessError("negative control expects Ready=True")

    digest_input = copy.deepcopy(document)
    declared = digest_input.pop("fixtureDigest", None)
    digest = V1.semantic_revision(digest_input)
    if declared is not None:
        _expect(digest, declared, "FixtureDigest")
    if digest in {revision, p_revision, supersedes["fixtureDigest"]}:
        raise V1.HarnessError("FixtureDigest is not distinct")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render-projection")
    render.add_argument("--contract", type=Path, required=True)
    render.add_argument("--schema", type=Path, required=True)
    render.add_argument("--ok-cluster-root", type=Path, required=True)
    render.add_argument("--ok-linux-root", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("validate")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "render-projection":
            render_projection(args)
        else:
            print(validate(V1.read_yaml_or_json(args.input), args.root))
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
