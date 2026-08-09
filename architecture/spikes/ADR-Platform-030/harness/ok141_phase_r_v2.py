#!/usr/bin/env python3
"""Offline Phase-R v2 contract-to-CAPI projection and fixture verifier.

This spike tool imports the frozen v1 canonicalizer instead of changing it. It
renders the pinned ok-cluster template, adds correlation-only metadata, and
separates resources by their authoritative target. It never applies resources.
"""

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
V1_PATH = HARNESS_DIR / "ok141_harness.py"
V1_SPEC = importlib.util.spec_from_file_location("ok141_harness_v1_frozen", V1_PATH)
V1 = importlib.util.module_from_spec(V1_SPEC)
assert V1_SPEC.loader is not None
V1_SPEC.loader.exec_module(V1)

FORMAT = "ok141-execution-fixture/v2"
VERSION = "phase-r-v2"
PROJECTION_VERSION = "ok141-contract-to-capi-projection/v1"
MANAGEMENT_PLANE = "ok-mgmt"
INFRASTRUCTURE_PLANE = "ok-infra"
CAPI_GROUPS = {
    "cluster.x-k8s.io",
    "infrastructure.cluster.x-k8s.io",
    "controlplane.cluster.x-k8s.io",
    "bootstrap.cluster.x-k8s.io",
}
SOURCE_FILES = {
    "renderer": ("render.py", "sha256:b74ef85c9dab5d3a52c8ea985f0f2521e8533d3d8643d1c5c98dc2faced0558e"),
    "talosResolver": (
        "profile_resolvers/talos.py",
        "sha256:d51633fd5e65b4e06b0c41e1a1f814790f4def08b19aeda1a6fd2a4b0cfdc550",
    ),
    "kubevirtTemplate": (
        "templates/talos/providers/kubevirt/cluster-base.yaml.tpl",
        "sha256:6f9de34f54c2cab6423b2979694d29adb5cc10c0c98f33417e8dd5e1d5700a2b",
    ),
}
OK_LINUX_PROFILE = (
    "profiles/kubevirt/profile.yaml",
    "sha256:f460d2aa68e3d989c5322d63b55a8ce79854c4d36a83b54c724d8aced0613116",
)


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _verify_source(root: Path, relative: str, digest: str) -> Path:
    path = root / relative
    if not path.is_file():
        raise V1.HarnessError(f"pinned source is missing: {path}")
    actual = V1.sha256_bytes(path.read_bytes())
    if actual != digest:
        raise V1.HarnessError(f"pinned source digest mismatch: {relative}")
    return path


def _load_ok_cluster(ok_cluster_root: Path):
    renderer = _verify_source(ok_cluster_root, *SOURCE_FILES["renderer"])
    _verify_source(ok_cluster_root, *SOURCE_FILES["talosResolver"])
    _verify_source(ok_cluster_root, *SOURCE_FILES["kubevirtTemplate"])
    sys.path.insert(0, str(ok_cluster_root))
    try:
        spec = importlib.util.spec_from_file_location("ok141_pinned_ok_cluster", renderer)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def load_contract(contract_path: Path, schema_path: Path) -> tuple[dict[str, Any], str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    normalized = V1.normalize(V1.read_yaml_or_json(contract_path), schema)
    V1.validate_contract_semantics(normalized)
    projected = V1.semantic_projection(normalized, schema)
    return normalized, V1.semantic_revision(projected)


def raw_renderer_input(contract: dict[str, Any]) -> dict[str, Any]:
    """Map v2 desired Cluster semantics to the reviewed ok-cluster input seam."""
    spec = contract["spec"]
    cp = spec["topology"]["controlPlane"]
    workers = spec["topology"]["workers"]
    os_identity = spec["operatingSystem"]
    provider = spec["infrastructure"]["profile"]
    return {
        "name": contract["metadata"]["name"],
        "type": "talos",
        "provider": spec["infrastructure"]["provider"],
        "versions": {
            "kubernetes": spec["kubernetesVersion"],
            "talos": os_identity["version"],
        },
        "controlPlane": {
            "replicas": cp["replicas"],
            "cores": cp["machine"]["cores"],
            "memory": cp["machine"]["memory"],
            "disk": cp["machine"]["disk"],
        },
        "workers": {
            "replicas": workers["replicas"],
            "cores": workers["machine"]["cores"],
            "memory": workers["machine"]["memory"],
            "disk": workers["machine"]["disk"],
        },
        "network": {
            # No address is selected offline. The submitted KubevirtCluster asks
            # CAPK/MetalLB for a LoadBalancer endpoint at reconciliation time.
            "endpoint": "provider-allocated",
            "podCIDR": spec["connectivity"]["podCIDR"],
            "serviceCIDR": spec["connectivity"]["serviceCIDR"],
        },
        "nodeSelector": provider["nodeSelector"],
        "os": {
            "distribution": os_identity["distribution"],
            "profile": os_identity["profile"],
            "schematic_id": os_identity["schematicID"],
        },
        "providerProfile": {"name": provider["name"]},
    }


def _verify_resolved_identity(contract: dict[str, Any], resolved: dict[str, Any]) -> None:
    wanted_os = contract["spec"]["operatingSystem"]
    actual_os = resolved["os"]
    checks = {
        "distribution": actual_os.get("distribution") == wanted_os["distribution"],
        "profile": actual_os.get("profile") == wanted_os["profile"],
        "architecture": actual_os.get("architecture") == wanted_os["architecture"],
        "schematicID": actual_os.get("schematic_id") == wanted_os["schematicID"],
        "imageDigest": actual_os.get("imageDigest") == wanted_os["imageDigest"],
        "identity": actual_os.get("identity") == wanted_os["identity"],
        "goldenImage": {
            "namespace": actual_os.get("goldenImage", {}).get("namespace"),
            "claim": actual_os.get("goldenImage", {}).get("claim"),
            "storageClass": actual_os.get("goldenImage", {}).get("storageClass"),
        } == wanted_os["goldenImage"],
        "providerProfile": resolved.get("providerProfile")
        == contract["spec"]["infrastructure"]["profile"],
    }
    failed = sorted(name for name, valid in checks.items() if not valid)
    if failed:
        raise V1.HarnessError(
            "ok-linux/ok-cluster resolution differs from R: " + ", ".join(failed)
        )


def render_source(
    contract: dict[str, Any], ok_cluster_root: Path, ok_linux_root: Path
) -> tuple[dict[str, Any], str]:
    module = _load_ok_cluster(ok_cluster_root)
    profile_path = _verify_source(ok_linux_root, *OK_LINUX_PROFILE)
    del profile_path
    raw = raw_renderer_input(contract)
    resolved = module.resolve_talos_config(raw, ok_linux_root)
    _verify_resolved_identity(contract, resolved)
    context = module.build_context(resolved)
    template_path = ok_cluster_root / SOURCE_FILES["kubevirtTemplate"][0]
    rendered = Template(template_path.read_text(encoding="utf-8")).safe_substitute(context)
    rendered = module.apply_node_selector(rendered, context["NODE_SELECTOR"])
    return resolved, rendered


def _resource_ref(document: dict[str, Any]) -> dict[str, str]:
    metadata = document.get("metadata", {})
    result = {
        "apiVersion": document.get("apiVersion", ""),
        "kind": document.get("kind", ""),
        "name": metadata.get("name", ""),
    }
    if metadata.get("namespace"):
        result["namespace"] = metadata["namespace"]
    return result


def _with_correlation(document: dict[str, Any], contract: dict[str, Any], revision: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    metadata = result.setdefault("metadata", {})
    annotations = metadata.setdefault("annotations", {})
    annotations.update(
        {
            "openkubes.io/contract-name": contract["metadata"]["name"],
            "openkubes.io/contract-namespace": contract["metadata"]["namespace"],
            "openkubes.io/intent-revision": revision,
        }
    )
    return result


def project_authorities(
    rendered: str, contract: dict[str, Any], revision: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    source = [item for item in yaml.load_all(rendered, Loader=V1.UniqueKeyLoader) if item]
    management: list[dict[str, Any]] = []
    infrastructure: list[dict[str, Any]] = []
    for item in source:
        correlated = _with_correlation(item, contract, revision)
        if item.get("kind") in {"Role", "RoleBinding"}:
            infrastructure.append(correlated)
        else:
            management.append(correlated)
        if item.get("kind") == "Namespace":
            infrastructure.append(copy.deepcopy(correlated))

    expected_management_kinds = {
        "Namespace": 1,
        "Cluster": 1,
        "KubevirtCluster": 1,
        "TalosControlPlane": 1,
        "TalosConfigTemplate": 1,
        "MachineDeployment": 1,
        "KubevirtMachineTemplate": 2,
    }
    actual_management_kinds = {
        kind: sum(item.get("kind") == kind for item in management)
        for kind in expected_management_kinds
    }
    if actual_management_kinds != expected_management_kinds or len(management) != 8:
        raise V1.HarnessError("management-plane object membership is not exact")
    if [item.get("kind") for item in infrastructure] != ["Namespace", "Role", "RoleBinding"]:
        raise V1.HarnessError("infrastructure prerequisite membership is not exact")
    if any(
        item.get("apiVersion", "").split("/", 1)[0] in CAPI_GROUPS
        for item in infrastructure
    ):
        raise V1.HarnessError("CAPI lifecycle object would be submitted to ok-infra")
    if any(item.get("kind") in {"Role", "RoleBinding"} for item in management):
        raise V1.HarnessError("infra-plane clone RBAC would be submitted to ok-mgmt")

    cluster_name = contract["metadata"]["name"]
    if any(
        item.get("kind") != "Role"
        and item.get("kind") != "RoleBinding"
        and item.get("metadata", {}).get("name") != cluster_name
        and item.get("metadata", {}).get("namespace") != cluster_name
        for item in management
    ):
        raise V1.HarnessError("projected resource escaped the disposable cluster namespace")

    authority = {
        "format": PROJECTION_VERSION,
        "intentRevision": revision,
        "contractIdentity": contract["metadata"],
        "managementPlane": {
            "identity": MANAGEMENT_PLANE,
            "role": "single-lifecycle-writer",
            "resources": [_resource_ref(item) for item in management],
        },
        "infrastructurePlane": {
            "identity": INFRASTRUCTURE_PLANE,
            "role": "provider-runtime-and-golden-image-prerequisites",
            "resources": [_resource_ref(item) for item in infrastructure],
        },
        "excludedRendererArtifacts": [
            {
                "path": "templates/talos/providers/kubevirt/cluster-v2.yaml.tpl",
                "reason": "auxiliary KubeVirtMachineTemplate is unreferenced by the lifecycle graph",
            }
        ],
    }
    return management, infrastructure, authority


def _yaml_documents(documents: list[dict[str, Any]]) -> str:
    return yaml.safe_dump_all(documents, sort_keys=False, explicit_start=True)


def render_command(args: argparse.Namespace) -> None:
    contract, revision = load_contract(args.contract, args.schema)
    resolved, source = render_source(contract, args.ok_cluster_root, args.ok_linux_root)
    management, infrastructure, authority = project_authorities(source, contract, revision)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "renderer-input.yaml").write_text(
        yaml.safe_dump(raw_renderer_input(contract), sort_keys=False), encoding="utf-8"
    )
    (args.output / "resolved-renderer-input.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8"
    )
    (args.output / "renderer-source.yaml").write_text(source, encoding="utf-8")
    (args.output / "ok-mgmt-lifecycle.yaml").write_text(
        _yaml_documents(management), encoding="utf-8"
    )
    (args.output / "ok-infra-prerequisites.yaml").write_text(
        _yaml_documents(infrastructure), encoding="utf-8"
    )
    (args.output / "authority-map.json").write_text(
        V1.jcs(authority) + "\n", encoding="utf-8"
    )
    manifest = {
        "format": PROJECTION_VERSION,
        "authorizationState": "NO-GO",
        "R": revision,
        "source": {
            "okClusterCommit": _git_head(args.ok_cluster_root),
            "okLinuxCommit": _git_head(args.ok_linux_root),
            "files": {
                name: {"path": path, "digest": digest}
                for name, (path, digest) in SOURCE_FILES.items()
            },
            "okLinuxProfile": {
                "path": OK_LINUX_PROFILE[0],
                "digest": OK_LINUX_PROFILE[1],
            },
        },
        "artifacts": {
            name: V1.sha256_bytes((args.output / name).read_bytes())
            for name in [
                "renderer-input.yaml",
                "resolved-renderer-input.yaml",
                "renderer-source.yaml",
                "ok-mgmt-lifecycle.yaml",
                "ok-infra-prerequisites.yaml",
                "authority-map.json",
            ]
        },
        "objectSets": {
            "rendererSource": {
                "count": len([item for item in yaml.safe_load_all(source) if item]),
                "digest": V1.semantic_revision(
                    [item for item in yaml.safe_load_all(source) if item]
                ),
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


def _fixture_path(root: Path, requested: str) -> Path:
    path = (root / requested).resolve()
    if root not in path.parents or not path.is_file():
        raise V1.HarnessError(f"fixture input is missing or outside root: {requested}")
    return path


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"Phase-R v2 {claim} mismatch")


def _read_documents(path: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in yaml.load_all(path.read_text(encoding="utf-8"), Loader=V1.UniqueKeyLoader)
        if item
    ]


def validate_execution_fixture_v2(
    document: dict[str, Any],
    root: Path,
    ok_cluster_root: Path | None = None,
    ok_linux_root: Path | None = None,
) -> str:
    root = root.resolve()
    if document.get("format") != FORMAT or document.get("fixtureVersion") != VERSION:
        raise V1.HarnessError("unsupported Phase-R v2 execution fixture")
    if document.get("authorizationState") != "NO-GO":
        raise V1.HarnessError("Phase-R v2 fixture must remain NO-GO")

    schema_claim = document.get("fixtureSchema", {})
    fixture_schema_path = _fixture_path(root, schema_claim.get("path", ""))
    fixture_schema_bytes = fixture_schema_path.read_bytes()
    fixture_schema = json.loads(fixture_schema_bytes)
    _expect(fixture_schema.get("$id"), FORMAT, "fixture schema identity")
    _expect(V1.sha256_bytes(fixture_schema_bytes), schema_claim.get("digest"), "fixture schema digest")
    V1.normalize(document, fixture_schema)

    supersedes = document.get("supersedes", {})
    _expect(supersedes.get("fixtureVersion"), "phase-r-v1", "superseded version")
    _expect(
        supersedes.get("fixtureDigest"),
        "sha256:a97e1e31e1f09cc44210679b48130e36edd90709d84ba3ee7b729ba5df82c9ba",
        "superseded FixtureDigest",
    )
    if supersedes.get("disposition") != "valid-historical-superseded-not-mutated":
        raise V1.HarnessError("v1 disposition is not explicit")

    contract_claim = document.get("contract", {})
    contract_path = _fixture_path(root, contract_claim.get("path", ""))
    contract_schema_path = _fixture_path(root, contract_claim.get("schemaPath", ""))
    contract, revision = load_contract(contract_path, contract_schema_path)
    _expect(V1.sha256_bytes(contract_path.read_bytes()), contract_claim.get("rawArtifactDigest"), "raw contract digest")
    _expect(V1.sha256_bytes(contract_schema_path.read_bytes()), contract_claim.get("schemaDigest"), "contract schema digest")
    _expect(contract_claim.get("canonicalizationProfile"), V1.PROFILE, "canonicalization profile")
    _expect(revision, contract_claim.get("R"), "R")
    _expect(document.get("contractIdentity"), contract["metadata"], "contract identity")

    semantics = document.get("clusterSemantics", {})
    spec = contract["spec"]
    expected_semantics = {
        "kubernetesVersion": spec["kubernetesVersion"],
        "infrastructure": spec["infrastructure"],
        "operatingSystem": spec["operatingSystem"],
        "topology": spec["topology"],
        "connectivity": spec["connectivity"],
    }
    _expect(semantics, expected_semantics, "cluster semantics projection")

    enablement = document.get("enablement", {})
    enablement_profile = json.loads(
        _fixture_path(root, enablement.get("profilePath", "")).read_text(encoding="utf-8")
    )
    enablement_values = V1.read_yaml_or_json(
        _fixture_path(root, enablement.get("valuesPath", ""))
    )
    enablement_revision = V1.validate_enablement_profile(enablement_profile, enablement_values)
    _expect(enablement_revision, enablement.get("E"), "E")
    _expect(enablement_revision, spec["enablement"]["revision"], "contract E")
    _expect(enablement_profile.get("profile"), spec["enablement"]["profile"], "Enablement profile")
    _expect(enablement_profile.get("target", {}).get("contractIdentity"), contract["metadata"], "Enablement target")

    platform = document.get("platform", {})
    platform_profile = json.loads(
        _fixture_path(root, platform.get("profilePath", "")).read_text(encoding="utf-8")
    )
    platform_apps = _read_documents(_fixture_path(root, platform.get("applicationsPath", "")))
    platform_revision = V1.validate_platform_applications(platform_profile, platform_apps)
    _expect(platform_revision, platform.get("P"), "P")
    _expect(platform_revision, spec["platform"]["revision"], "contract P")
    _expect(platform_profile.get("profile"), spec["platform"]["profile"], "Platform profile")
    _expect(platform_profile.get("target", {}).get("contractIdentity"), contract["metadata"], "Platform target")

    projection = document.get("projection", {})
    projection_manifest_path = _fixture_path(root, projection.get("manifestPath", ""))
    projection_manifest_bytes = projection_manifest_path.read_bytes()
    _expect(V1.sha256_bytes(projection_manifest_bytes), projection.get("manifestDigest"), "projection manifest digest")
    projection_manifest = json.loads(projection_manifest_bytes)
    _expect(projection_manifest.get("format"), PROJECTION_VERSION, "projection format")
    _expect(projection_manifest.get("authorizationState"), "NO-GO", "projection authorization")
    _expect(projection_manifest.get("R"), revision, "projection R")
    _expect(projection_manifest.get("source"), projection.get("source"), "projection source provenance")
    _expect(projection_manifest.get("objectSets"), projection.get("objectSets"), "projection object sets")
    projection_dir = projection_manifest_path.parent
    for artifact, digest in projection_manifest.get("artifacts", {}).items():
        artifact_path = _fixture_path(root, projection_dir.relative_to(root).joinpath(artifact).as_posix())
        _expect(V1.sha256_bytes(artifact_path.read_bytes()), digest, f"projection artifact {artifact}")

    authority = json.loads(
        _fixture_path(root, projection.get("authorityMapPath", "")).read_text(encoding="utf-8")
    )
    _expect(authority.get("intentRevision"), revision, "authority-map R")
    _expect(authority.get("managementPlane", {}).get("identity"), MANAGEMENT_PLANE, "management authority")
    _expect(authority.get("infrastructurePlane", {}).get("identity"), INFRASTRUCTURE_PLANE, "infrastructure authority")
    mgmt_documents = _read_documents(_fixture_path(root, projection.get("managementObjectsPath", "")))
    infra_documents = _read_documents(_fixture_path(root, projection.get("infrastructurePrerequisitesPath", "")))
    _expect(V1.semantic_revision(mgmt_documents), projection["objectSets"]["okMgmtLifecycle"]["digest"], "management object-set digest")
    _expect(V1.semantic_revision(infra_documents), projection["objectSets"]["okInfraPrerequisites"]["digest"], "infrastructure object-set digest")
    if any(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != revision for item in mgmt_documents + infra_documents):
        raise V1.HarnessError("a projected object lacks the exact R carrier")

    if (ok_cluster_root is None) != (ok_linux_root is None):
        raise V1.HarnessError("both source roots are required for fresh projection verification")
    if ok_cluster_root is not None and ok_linux_root is not None:
        _expect(_git_head(ok_cluster_root), projection["source"]["okClusterCommit"], "ok-cluster commit")
        _expect(_git_head(ok_linux_root), projection["source"]["okLinuxCommit"], "ok-linux commit")
        resolved, rendered = render_source(contract, ok_cluster_root, ok_linux_root)
        fresh_mgmt, fresh_infra, fresh_authority = project_authorities(rendered, contract, revision)
        _expect(V1.semantic_revision(fresh_mgmt), V1.semantic_revision(mgmt_documents), "fresh management projection")
        _expect(V1.semantic_revision(fresh_infra), V1.semantic_revision(infra_documents), "fresh infrastructure projection")
        _expect(fresh_authority, authority, "fresh authority map")
        resolved_path = projection_dir / "resolved-renderer-input.yaml"
        _expect(V1.semantic_revision(resolved), V1.semantic_revision(V1.read_yaml_or_json(resolved_path)), "fresh resolved renderer input")

    conditions = document.get("conditions", {})
    condition_profile = V1.read_yaml_or_json(
        _fixture_path(root, conditions.get("profilePath", ""))
    )
    _expect(V1.semantic_revision(condition_profile), conditions.get("profileDigest"), "condition profile digest")
    _expect(condition_profile.get("requiredConditions"), spec["conditions"]["required"], "condition membership")

    evidence = document.get("evidence", {})
    evidence_schema_bytes = _fixture_path(root, evidence.get("schemaPath", "")).read_bytes()
    _expect(V1.sha256_bytes(evidence_schema_bytes), evidence.get("schemaDigest"), "evidence schema digest")
    _expect(json.loads(evidence_schema_bytes).get("$id"), evidence.get("schemaId"), "evidence schema identity")

    tools = document.get("tools", {})
    _expect(tools.get("canonicalizerVersion"), V1.PROFILE, "canonicalizer version")
    _expect(tools.get("evaluatorVersion"), "ok141-evaluator/v1", "evaluator version")
    _expect(V1.sha256_bytes(V1_PATH.read_bytes()), tools.get("frozenV1HarnessDigest"), "frozen v1 harness digest")
    _expect(V1.sha256_bytes(Path(__file__).read_bytes()), tools.get("phaseRV2ToolDigest"), "Phase-R v2 tool digest")

    controls = document.get("negativeControls", [])
    ids = {item.get("id") for item in controls}
    if ids != V1.NEGATIVE_CONTROL_IDS or len(ids) != len(controls):
        raise V1.HarnessError("Phase-R v2 negative-control set is incomplete or duplicated")
    if any(item.get("expectedReady") == "True" for item in controls):
        raise V1.HarnessError("a negative control must not expect Ready=True")
    if not document.get("positiveAssertions") or not document.get("expectedEvidence"):
        raise V1.HarnessError("Phase-R v2 assertions and expected evidence are required")

    digest_input = copy.deepcopy(document)
    declared_digest = digest_input.pop("fixtureDigest", None)
    fixture_digest = V1.semantic_revision(digest_input)
    if declared_digest is not None:
        _expect(fixture_digest, declared_digest, "FixtureDigest")
    if fixture_digest in {revision, supersedes.get("fixtureDigest")}:
        raise V1.HarnessError("Phase-R v2 FixtureDigest is not distinct")
    return fixture_digest


def verify_fixture_command(args: argparse.Namespace) -> None:
    document = V1.read_yaml_or_json(args.input)
    print(
        validate_execution_fixture_v2(
            document,
            args.root,
            args.ok_cluster_root,
            args.ok_linux_root,
        )
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render")
    render.add_argument("--contract", type=Path, required=True)
    render.add_argument("--schema", type=Path, required=True)
    render.add_argument("--ok-cluster-root", type=Path, required=True)
    render.add_argument("--ok-linux-root", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.set_defaults(function=render_command)
    verify_fixture = commands.add_parser("verify-fixture")
    verify_fixture.add_argument("--root", type=Path, required=True)
    verify_fixture.add_argument("--input", type=Path, required=True)
    verify_fixture.add_argument("--ok-cluster-root", type=Path)
    verify_fixture.add_argument("--ok-linux-root", type=Path)
    verify_fixture.set_defaults(function=verify_fixture_command)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        args.function(args)
        return 0
    except (V1.HarnessError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
