#!/usr/bin/env python3
"""Read-only OK-141 canonicalization, evaluation, and evidence harness."""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


PROFILE = "openkubes-contract-c14n/v1"
FIXTURE_FORMAT = "ok141-execution-fixture/v1"
NEGATIVE_CONTROL_IDS = {
    "NC-R-WRONG",
    "NC-E-WRONG",
    "NC-P-WRONG",
    "NC-STALE-GENERATION",
    "NC-MISSING-SOURCE",
    "NC-CONFLICTING-AUTHORITY",
    "NC-HISTORICAL-SUCCESS",
    "NC-TAMPERED-EVIDENCE",
}


class HarnessError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise HarnessError(f"duplicate mapping key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def tool_digest() -> str:
    return sha256_bytes(Path(__file__).read_bytes())


def is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def read_yaml_or_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return yaml.load(stream, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise HarnessError(f"cannot parse {path}: {exc}") from exc


def _jcs_key(value: str) -> bytes:
    try:
        return value.encode("utf-16-be")
    except UnicodeEncodeError as exc:
        raise HarnessError("object key contains an invalid Unicode surrogate") from exc


def jcs(value: Any) -> str:
    """RFC-8785-compatible encoding for the schema's no-float data subset."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        raise HarnessError("floating-point values are not allowed by this test profile")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(jcs(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise HarnessError("all object keys must be strings")
        keys = sorted(value, key=_jcs_key)
        return "{" + ",".join(jcs(key) + ":" + jcs(value[key]) for key in keys) + "}"
    raise HarnessError(f"unsupported canonical JSON type: {type(value).__name__}")


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def normalize(value: Any, schema: dict[str, Any], path: str = "$") -> Any:
    expected = schema.get("type")
    if expected and not _type_matches(value, expected):
        raise HarnessError(f"{path}: expected {expected}, got {type(value).__name__}")

    if "enum" in schema and value not in schema["enum"]:
        raise HarnessError(f"{path}: value is not in the declared enum")
    if "const" in schema and value != schema["const"]:
        raise HarnessError(f"{path}: value differs from the declared constant")

    if expected == "object":
        properties = schema.get("properties", {})
        unknown = sorted(set(value) - set(properties))
        if unknown and schema.get("additionalProperties", True) is False:
            raise HarnessError(f"{path}: unknown fields: {', '.join(unknown)}")
        result = {}
        for name, child_schema in properties.items():
            child_path = f"{path}.{name}"
            if name in value:
                result[name] = normalize(value[name], child_schema, child_path)
            elif "default" in child_schema:
                result[name] = normalize(
                    copy.deepcopy(child_schema["default"]), child_schema, child_path
                )
            elif name in schema.get("required", []):
                raise HarnessError(f"{child_path}: required field is missing")
        return result

    if expected == "array":
        result = [normalize(item, schema["items"], f"{path}[{index}]")
                  for index, item in enumerate(value)]
        if schema.get("uniqueItems") and len({jcs(item) for item in result}) != len(result):
            raise HarnessError(f"{path}: array items must be unique")
        minimum = schema.get("minItems")
        if minimum is not None and len(result) < minimum:
            raise HarnessError(f"{path}: requires at least {minimum} items")
        maximum = schema.get("maxItems")
        if maximum is not None and len(result) > maximum:
            raise HarnessError(f"{path}: allows at most {maximum} items")
        return result

    if expected == "string":
        minimum = schema.get("minLength")
        if minimum is not None and len(value) < minimum:
            raise HarnessError(f"{path}: string is shorter than {minimum}")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise HarnessError(f"{path}: string does not match the declared pattern")
        if schema.get("format") == "sha256":
            prefix, separator, digest = value.partition(":")
            if separator != ":" or prefix != "sha256" or len(digest) != 64:
                raise HarnessError(f"{path}: expected sha256:<64 lowercase hex>")
            if any(character not in "0123456789abcdef" for character in digest):
                raise HarnessError(f"{path}: digest is not lowercase hexadecimal")
        if schema.get("format") == "ipv4-cidr":
            try:
                canonical = str(ipaddress.IPv4Network(value, strict=True))
            except ValueError as exc:
                raise HarnessError(f"{path}: invalid canonical IPv4 CIDR") from exc
            if canonical != value:
                raise HarnessError(f"{path}: CIDR must be canonical ({canonical})")
        return value

    if expected == "integer":
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise HarnessError(f"{path}: integer must be >= {minimum}")
    return value


def semantic_projection(value: Any, schema: dict[str, Any]) -> Any:
    if schema.get("x-openkubes-semantic", True) is False:
        return None
    if schema.get("type") == "object":
        projected = {}
        for name, child_schema in schema.get("properties", {}).items():
            if name in value and child_schema.get("x-openkubes-semantic", True):
                projected[name] = semantic_projection(value[name], child_schema)
        return projected
    if schema.get("type") == "array":
        return [semantic_projection(item, schema["items"]) for item in value]
    return value


def validate_contract_semantics(contract: dict[str, Any]) -> None:
    connectivity = contract["spec"]["connectivity"]
    pod = ipaddress.IPv4Network(connectivity["podCIDR"], strict=True)
    service = ipaddress.IPv4Network(connectivity["serviceCIDR"], strict=True)
    if connectivity["profile"] == "datacenter-isolated-v1":
        if pod.prefixlen != 16:
            raise HarnessError("$.spec.connectivity.podCIDR: profile requires /16")
        if service.prefixlen != 20:
            raise HarnessError("$.spec.connectivity.serviceCIDR: profile requires /20")
    if pod.overlaps(service):
        raise HarnessError("Pod and Service CIDRs must not overlap")
    for forbidden_text in connectivity["forbiddenCIDRs"]:
        forbidden = ipaddress.IPv4Network(forbidden_text, strict=True)
        if pod.overlaps(forbidden) or service.overlaps(forbidden):
            raise HarnessError(f"Cluster CIDR overlaps forbidden range {forbidden}")


def semantic_revision(value: Any) -> str:
    return sha256_bytes(jcs(value).encode("utf-8"))


def validate_enablement_profile(profile: dict[str, Any], values: Any) -> str:
    if profile.get("format") != "ok141-enable-profile/v1":
        raise HarnessError("unsupported Enablement profile format")
    package = profile.get("package", {})
    if package.get("valuesDigest") != semantic_revision(values):
        raise HarnessError("Enablement values digest mismatch")
    if not is_sha256(package.get("artifactDigest")):
        raise HarnessError("Enablement artifact digest is not immutable")
    images = profile.get("renderedImages", [])
    if not images or any("@sha256:" not in image for image in images):
        raise HarnessError("every rendered Enablement image must be digest-bound")
    target = profile.get("target", {})
    identity = target.get("contractIdentity", {})
    if not identity.get("namespace") or not identity.get("name"):
        raise HarnessError("Enablement target contract identity is required")
    if "intentRevision" in target:
        raise HarnessError("Enablement profile must not embed R; the fixture correlates R to E")
    if not profile.get("requiredSources"):
        raise HarnessError("Enablement readiness sources are required")
    return semantic_revision(profile)


def validate_platform_applications(profile: dict[str, Any], documents: list[Any]) -> str:
    if profile.get("format") != "ok141-platform-profile/v1":
        raise HarnessError("unsupported Platform profile format")
    target = profile.get("target", {})
    identity = target.get("contractIdentity", {})
    if not identity.get("namespace") or not identity.get("name"):
        raise HarnessError("Platform target contract identity is required")
    if "intentRevision" in target:
        raise HarnessError("Platform profile must not embed R; the fixture correlates R to P")
    expected = profile.get("requiredApplications", [])
    expected_by_name = {item.get("name"): item for item in expected}
    if None in expected_by_name or len(expected_by_name) != len(expected) or not expected:
        raise HarnessError("required Application membership must be non-empty and unique")
    applications = [item for item in documents if item is not None]
    if any(item.get("apiVersion") != "argoproj.io/v1alpha1" or item.get("kind") != "Application"
           for item in applications):
        raise HarnessError("only Argo CD Application documents are accepted")
    actual_by_name = {item.get("metadata", {}).get("name"): item for item in applications}
    if set(actual_by_name) != set(expected_by_name) or len(actual_by_name) != len(applications):
        raise HarnessError("Application membership differs from Platform profile")
    for name, leaf in expected_by_name.items():
        application = actual_by_name[name]
        source = application.get("spec", {}).get("source", {})
        destination = application.get("spec", {}).get("destination", {})
        commit = source.get("targetRevision", "")
        if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
            raise HarnessError(f"{name}: targetRevision must be an immutable Git commit")
        expected_source = leaf.get("source", {})
        checks = {
            "repoURL": source.get("repoURL") == expected_source.get("repoURL"),
            "path": source.get("path") == expected_source.get("path"),
            "targetRevision": commit == expected_source.get("commit"),
            "destinationName": destination.get("name") == leaf.get("destination", {}).get("name"),
            "destinationNamespace": destination.get("namespace") == leaf.get("destination", {}).get("namespace"),
        }
        failed = sorted(key for key, passed in checks.items() if not passed)
        if failed:
            raise HarnessError(f"{name}: Application projection mismatch: {', '.join(failed)}")
        if not leaf.get("capabilityChecks"):
            raise HarnessError(f"{name}: capability checks are required")
    return semantic_revision(profile)


def write_canonical(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jcs(value) + "\n", encoding="utf-8")


def canonicalize(args: argparse.Namespace) -> None:
    if args.profile != PROFILE:
        raise HarnessError(f"unsupported canonicalization profile: {args.profile}")
    schema_bytes = args.schema.read_bytes()
    schema = json.loads(schema_bytes)
    raw_bytes = args.input.read_bytes()
    source = read_yaml_or_json(args.input)
    normalized = normalize(source, schema)
    validate_contract_semantics(normalized)
    projected = semantic_projection(normalized, schema)
    canonical_bytes = jcs(projected).encode("utf-8")
    revision = sha256_bytes(canonical_bytes)
    write_canonical(args.normalized_output, projected)
    write_canonical(args.manifest_output, {
        "canonicalizationProfile": PROFILE,
        "canonicalizerDigest": tool_digest(),
        "normalizedArtifactDigest": revision,
        "normalizedContractDigest": revision,
        "rawArtifactDigest": sha256_bytes(raw_bytes),
        "testSchemaDigest": sha256_bytes(schema_bytes),
    })


def evaluate_document(document: dict[str, Any], input_digest: str | None = None) -> dict[str, Any]:
    required = document.get("requiredConditions")
    sources = document.get("sources")
    revision = document.get("intentRevision")
    if not isinstance(required, list) or not required or len(set(required)) != len(required):
        raise HarnessError("requiredConditions must be a non-empty unique list")
    if not isinstance(sources, list) or not is_sha256(revision):
        raise HarnessError("intentRevision and sources are required")
    if not is_sha256(document.get("profileDigest")):
        raise HarnessError("profileDigest must be a sha256 digest")
    if not isinstance(document.get("evaluatedAt"), str) or not document["evaluatedAt"]:
        raise HarnessError("evaluatedAt must be supplied explicitly")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        by_type.setdefault(source.get("type"), []).append(source)

    results = []
    for condition_type in required:
        candidates = by_type.get(condition_type, [])
        if not candidates:
            results.append({"type": condition_type, "status": "Unknown",
                            "reason": "RequiredEvidenceMissing"})
            continue
        if len(candidates) != 1 or candidates[0].get("conflictingAuthority", False):
            results.append({"type": condition_type, "status": "Unknown",
                            "reason": "ConflictingAuthority"})
            continue
        source = candidates[0]
        status = source.get("status")
        reason = source.get("reason", "SourceReported")
        if not is_sha256(source.get("intentRevision")):
            raise HarnessError(f"{condition_type}: source intentRevision is required")
        if not is_sha256(source.get("expectedRevision")) or not is_sha256(source.get("observedRevision")):
            raise HarnessError(f"{condition_type}: expected and observed revisions are required")
        if not isinstance(source.get("generation"), int) or not isinstance(source.get("observedGeneration"), int):
            raise HarnessError(f"{condition_type}: generation fields are required")
        if source.get("observerAvailable") is not True:
            status, reason = "Unknown", "ObserverUnavailable"
        elif source.get("intentRevision") != revision:
            status, reason = "Unknown", "RevisionCorrelationUnproven"
        elif source.get("expectedRevision") != source.get("observedRevision"):
            status, reason = "Unknown", "RevisionCorrelationUnproven"
        elif source.get("observedGeneration") != source.get("generation"):
            status, reason = "Unknown", "SourceObservationStale"
        elif status not in {"True", "False", "Unknown"}:
            raise HarnessError(f"{condition_type}: invalid source status")
        result = {"type": condition_type, "status": status, "reason": reason}
        if source.get("message"):
            result["message"] = source["message"]
        results.append(result)

    statuses = {item["status"] for item in results}
    if "False" in statuses:
        aggregate, reason = "False", "RequiredConditionFailed"
    elif "Unknown" in statuses:
        aggregate = "Unknown"
        unknown_reasons = {item["reason"] for item in results if item["status"] == "Unknown"}
        reason_order = ["ConflictingAuthority", "RevisionCorrelationUnproven",
                        "SourceObservationStale", "ObserverUnavailable",
                        "RequiredEvidenceMissing"]
        reason = next((candidate for candidate in reason_order
                       if candidate in unknown_reasons), "EvaluationProfileInvalid")
    elif statuses == {"True"}:
        aggregate, reason = "True", "AllRequiredConditionsSatisfied"
    else:
        aggregate, reason = "Unknown", "EvaluationProfileInvalid"
    result = {
        "evaluatedAt": document["evaluatedAt"],
        "evaluatorDigest": tool_digest(),
        "intentRevision": revision,
        "profileDigest": document.get("profileDigest"),
        "conditions": results,
        "ready": {"status": aggregate, "reason": reason},
    }
    if input_digest is not None:
        result["inputArtifactDigest"] = input_digest
    return result


def evaluate(args: argparse.Namespace) -> None:
    raw = args.input.read_bytes()
    document = read_yaml_or_json(args.input)
    write_canonical(args.output, evaluate_document(document, sha256_bytes(raw)))


def bundle(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    artifacts = []
    for requested in sorted(args.artifact):
        path = (root / requested).resolve()
        if root not in path.parents or not path.is_file():
            raise HarnessError(f"artifact is missing or outside root: {requested}")
        data = path.read_bytes()
        artifacts.append({"path": path.relative_to(root).as_posix(),
                          "sha256": sha256_bytes(data), "size": len(data)})
    write_canonical(args.output, {"artifacts": artifacts,
                                  "format": "ok141-evidence/v1",
                                  "harnessDigest": tool_digest()})


def verify(args: argparse.Namespace) -> None:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    root = args.root.resolve()
    if manifest.get("format") != "ok141-evidence/v1":
        raise HarnessError("unsupported evidence manifest format")
    for artifact in manifest.get("artifacts", []):
        path = (root / artifact["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise HarnessError(f"artifact missing or outside root: {artifact['path']}")
        data = path.read_bytes()
        if len(data) != artifact["size"] or sha256_bytes(data) != artifact["sha256"]:
            raise HarnessError(f"artifact verification failed: {artifact['path']}")
    print(sha256_bytes(args.manifest.read_bytes()))


def _fixture_path(root: Path, requested: str) -> Path:
    path = (root / requested).resolve()
    if root not in path.parents or not path.is_file():
        raise HarnessError(f"fixture input is missing or outside root: {requested}")
    return path


def _expect_digest(actual: str, expected: Any, claim: str) -> None:
    if not is_sha256(expected) or actual != expected:
        raise HarnessError(f"execution fixture {claim} mismatch")


def validate_execution_fixture(document: dict[str, Any], root: Path) -> str:
    """Verify every offline identity bound by the Phase-R execution fixture."""
    root = root.resolve()
    if document.get("format") != FIXTURE_FORMAT:
        raise HarnessError("unsupported execution fixture format")
    if document.get("fixtureVersion") != "phase-r-v1":
        raise HarnessError("unsupported execution fixture version")
    if document.get("authorizationState") != "NO-GO":
        raise HarnessError("Phase-R fixture must remain NO-GO")

    fixture_schema = document.get("fixtureSchema", {})
    fixture_schema_bytes = _fixture_path(root, fixture_schema.get("path", "")).read_bytes()
    parsed_fixture_schema = json.loads(fixture_schema_bytes)
    if parsed_fixture_schema.get("$id") != FIXTURE_FORMAT:
        raise HarnessError("execution fixture schema identity mismatch")
    _expect_digest(sha256_bytes(fixture_schema_bytes), fixture_schema.get("digest"),
                   "fixture schema digest")
    normalize(document, parsed_fixture_schema, "$")

    contract = document.get("contract", {})
    contract_path = _fixture_path(root, contract.get("path", ""))
    schema_path = _fixture_path(root, contract.get("schemaPath", ""))
    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes)
    raw_bytes = contract_path.read_bytes()
    normalized = normalize(read_yaml_or_json(contract_path), schema)
    validate_contract_semantics(normalized)
    projected = semantic_projection(normalized, schema)
    revision = semantic_revision(projected)
    if contract.get("canonicalizationProfile") != PROFILE:
        raise HarnessError("execution fixture canonicalization profile mismatch")
    _expect_digest(sha256_bytes(raw_bytes), contract.get("rawArtifactDigest"), "raw contract digest")
    _expect_digest(sha256_bytes(schema_bytes), contract.get("schemaDigest"), "contract schema digest")
    _expect_digest(revision, contract.get("R"), "R")

    identity = document.get("contractIdentity", {})
    if identity != {"namespace": normalized["metadata"]["namespace"],
                    "name": normalized["metadata"]["name"]}:
        raise HarnessError("execution fixture contract identity mismatch")
    if document.get("connectivity") != normalized["spec"]["connectivity"]:
        raise HarnessError("execution fixture connectivity projection mismatch")

    enablement = document.get("enablement", {})
    enablement_profile = json.loads(
        _fixture_path(root, enablement.get("profilePath", "")).read_text(encoding="utf-8")
    )
    enablement_values = read_yaml_or_json(_fixture_path(root, enablement.get("valuesPath", "")))
    enablement_revision = validate_enablement_profile(enablement_profile, enablement_values)
    _expect_digest(enablement_revision, enablement.get("E"), "E")
    if enablement_revision != normalized["spec"]["enablement"]["revision"]:
        raise HarnessError("contract Enablement revision does not equal E")
    if enablement_profile.get("target", {}).get("contractIdentity") != identity:
        raise HarnessError("Enablement target identity mismatch")
    if enablement.get("images") != enablement_profile.get("renderedImages"):
        raise HarnessError("Enablement image set mismatch")

    platform = document.get("platform", {})
    platform_profile = json.loads(
        _fixture_path(root, platform.get("profilePath", "")).read_text(encoding="utf-8")
    )
    application_path = _fixture_path(root, platform.get("applicationsPath", ""))
    applications = list(yaml.load_all(application_path.read_text(encoding="utf-8"),
                                      Loader=UniqueKeyLoader))
    platform_revision = validate_platform_applications(platform_profile, applications)
    _expect_digest(platform_revision, platform.get("P"), "P")
    _expect_digest(semantic_revision(applications), platform.get("applicationSetDigest"),
                   "Application set digest")
    if platform_revision != normalized["spec"]["platform"]["revision"]:
        raise HarnessError("contract Platform revision does not equal P")
    if platform_profile.get("target", {}).get("contractIdentity") != identity:
        raise HarnessError("Platform target identity mismatch")

    conditions = document.get("conditions", {})
    condition_profile = read_yaml_or_json(_fixture_path(root, conditions.get("profilePath", "")))
    _expect_digest(semantic_revision(condition_profile), conditions.get("profileDigest"),
                   "condition profile digest")
    if condition_profile.get("requiredConditions") != normalized["spec"]["conditions"]["required"]:
        raise HarnessError("condition profile membership differs from contract")

    evidence = document.get("evidence", {})
    evidence_schema = _fixture_path(root, evidence.get("schemaPath", "")).read_bytes()
    _expect_digest(sha256_bytes(evidence_schema), evidence.get("schemaDigest"),
                   "evidence schema digest")
    if json.loads(evidence_schema).get("$id") != evidence.get("schemaId"):
        raise HarnessError("evidence schema identity mismatch")

    tools = document.get("tools", {})
    if tools.get("canonicalizerVersion") != PROFILE or tools.get("evaluatorVersion") != "ok141-evaluator/v1":
        raise HarnessError("execution fixture tool version mismatch")
    _expect_digest(tool_digest(), tools.get("harnessDigest"), "harness digest")

    controls = document.get("negativeControls", [])
    ids = {item.get("id") for item in controls}
    if ids != NEGATIVE_CONTROL_IDS or len(ids) != len(controls):
        raise HarnessError("execution fixture negative-control set is incomplete or duplicated")
    if any(item.get("expectedReady") == "True" for item in controls):
        raise HarnessError("a negative control must not expect Ready=True")
    if not document.get("positiveAssertions") or not document.get("expectedEvidence"):
        raise HarnessError("execution fixture assertions and expected evidence are required")

    digest_input = copy.deepcopy(document)
    declared_digest = digest_input.pop("fixtureDigest", None)
    fixture_digest = semantic_revision(digest_input)
    if declared_digest is not None:
        _expect_digest(fixture_digest, declared_digest, "FixtureDigest")
    if fixture_digest == revision:
        raise HarnessError("FixtureDigest must be distinct from R")
    return fixture_digest


def fixture(args: argparse.Namespace) -> None:
    document = read_yaml_or_json(args.input)
    print(validate_execution_fixture(document, args.root))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    c14n = commands.add_parser("canonicalize")
    c14n.add_argument("--profile", required=True)
    c14n.add_argument("--schema", type=Path, required=True)
    c14n.add_argument("--input", type=Path, required=True)
    c14n.add_argument("--normalized-output", type=Path, required=True)
    c14n.add_argument("--manifest-output", type=Path, required=True)
    c14n.set_defaults(function=canonicalize)
    evaluator = commands.add_parser("evaluate")
    evaluator.add_argument("--input", type=Path, required=True)
    evaluator.add_argument("--output", type=Path, required=True)
    evaluator.set_defaults(function=evaluate)
    bundler = commands.add_parser("bundle")
    bundler.add_argument("--root", type=Path, required=True)
    bundler.add_argument("--output", type=Path, required=True)
    bundler.add_argument("--artifact", action="append", required=True)
    bundler.set_defaults(function=bundle)
    verifier = commands.add_parser("verify")
    verifier.add_argument("--root", type=Path, required=True)
    verifier.add_argument("--manifest", type=Path, required=True)
    verifier.set_defaults(function=verify)
    fixture_verifier = commands.add_parser("verify-fixture")
    fixture_verifier.add_argument("--root", type=Path, required=True)
    fixture_verifier.add_argument("--input", type=Path, required=True)
    fixture_verifier.set_defaults(function=fixture)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        args.function(args)
        return 0
    except (HarnessError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
