#!/usr/bin/env python3
import copy
import hashlib
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "m0b-runtime-registration-protocol-v1.yaml"
DIGEST = ROOT / "m0b-runtime-registration-protocol-v1.sha256"
BASELINE = ROOT / "live-baseline-observation-v1.yaml"
PROJECT = ROOT / "appproject-v5-candidate.yaml"
ACCESS = ROOT / "target-access-v1.template.yaml"
REGISTRATION = ROOT / "cluster-registration-v5.template.yaml"
FIXTURE = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def docs(path: Path):
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def wildcard(value) -> bool:
    if isinstance(value, str):
        return value == "*"
    if isinstance(value, list):
        return any(wildcard(item) for item in value)
    if isinstance(value, dict):
        return any(wildcard(item) for item in value.values())
    return False


def verify(protocol=None, project=None, access=None, registration=None, baseline=None) -> list[str]:
    errors = []
    protocol = protocol or yaml.safe_load(PROTOCOL.read_text())
    project = project or yaml.safe_load(PROJECT.read_text())
    access = access or docs(ACCESS)
    registration = registration or yaml.safe_load(REGISTRATION.read_text())
    baseline = baseline or yaml.safe_load(BASELINE.read_text())
    spec = protocol["spec"]

    if spec["protocolState"] != "BLOCKED":
        errors.append("protocol must remain BLOCKED")
    auth = spec["authorization"]
    if auth["decision"] != "NO-GO" or any(auth[key] for key in (
        "runtimeRegistrationGranted", "targetCredentialsGranted", "platformSubmissionGranted", "go1Granted"
    )):
        errors.append("runtime registration and GO-1 must remain NO-GO")
    if any(phase["enabled"] for phase in spec["phases"]):
        errors.append("all runtime phases must remain disabled")
    if any(candidate["applyEnabled"] for candidate in spec["candidates"].values()):
        errors.append("all candidate application must remain disabled")
    if any(item["status"] != "BLOCKED" for item in spec["blockers"]):
        errors.append("all runtime blockers must remain BLOCKED")
    if spec["fixture"]["fixtureDigest"] != FIXTURE:
        errors.append("fixture binding mismatch")

    observation = baseline["spec"]
    if observation["mutationPerformed"] or observation["managementPlane"]["disposableClusterExists"]:
        errors.append("baseline must be read-only and target-absent")
    if any(observation["gitOpsPlane"][key] for key in ("clusterCredentialSecrets", "applications", "applicationSets")):
        errors.append("baseline must contain no target registration or submissions")
    if observation["gitOpsPlane"]["appProjects"] != ["default"]:
        errors.append("baseline AppProject membership mismatch")

    expected_digests = {
        "liveBaseline": digest(BASELINE),
        "appProject": digest(PROJECT),
        "targetAccess": digest(ACCESS),
        "registration": digest(REGISTRATION),
    }
    if spec["liveBaseline"]["digest"] != expected_digests["liveBaseline"]:
        errors.append("baseline digest mismatch")
    for key in ("appProject", "targetAccess", "registration"):
        if spec["candidates"][key]["digest"] != expected_digests[key]:
            errors.append(f"{key} digest mismatch")

    project_spec = project["spec"]
    if not project_spec.get("permitOnlyProjectScopedClusters"):
        errors.append("AppProject must permit only project-scoped clusters")
    if wildcard(project_spec):
        errors.append("AppProject must contain no wildcard")
    destinations = {(item["name"], item["namespace"]) for item in project_spec["destinations"]}
    if destinations != {("disposable-ok141", "ok-observability"), ("disposable-ok141", "kube-system")}:
        errors.append("AppProject destinations mismatch")

    if len(access) != 8 or spec["candidates"]["targetAccess"]["objectCount"] != 8:
        errors.append("target access must contain exactly eight objects")
    kinds = [item["kind"] for item in access]
    if kinds != ["Namespace", "ServiceAccount", "ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding", "Role", "RoleBinding"]:
        errors.append("target access exact kind sequence mismatch")
    if wildcard(access):
        errors.append("target access RBAC must contain no wildcard")
    namespace = access[0]
    labels = namespace["metadata"].get("labels", {})
    if namespace["metadata"]["name"] != "ok-observability" or set(labels.values()) != {"privileged"} or len(labels) != 3:
        errors.append("precreated namespace or Pod Security labels mismatch")
    cluster_role = access[2]
    if any("create" in rule["verbs"] for rule in cluster_role["rules"] if "namespaces" in rule["resources"]):
        errors.append("target ServiceAccount must not create namespaces")
    for item in access:
        if item["kind"] not in ("RoleBinding", "ClusterRoleBinding"):
            continue
        subjects = item.get("subjects", [])
        if subjects != [{"kind": "ServiceAccount", "name": "ok141-argocd-manager", "namespace": "kube-system"}]:
            errors.append(f"binding {item['metadata']['name']} subject mismatch")

    data = registration["stringData"]
    if registration["metadata"]["labels"].get("argocd.argoproj.io/secret-type") != "cluster":
        errors.append("registration must be an Argo cluster Secret")
    if data.get("project") != "openkubes-disposable":
        errors.append("registration must be project-scoped")
    if data.get("namespaces") != "ok-observability,kube-system" or data.get("clusterResources") != "true":
        errors.append("registration namespace/cluster-resource scope mismatch")
    serialized_registration = yaml.safe_dump(registration)
    if "bearerToken" in serialized_registration or "clientKey" in serialized_registration:
        errors.append("registration template contains credential material")
    if data.get("config") != "RUNTIME-SERVER-SIDE-MATERIALIZATION-ONLY":
        errors.append("registration config must remain a runtime-only placeholder")
    required_runtime = {"openkubes.io/capi-cluster-uid", "openkubes.io/workload-kube-system-uid", "openkubes.io/workload-api-ca-sha256", "openkubes.io/token-expiration"}
    annotations = registration["metadata"].get("annotations", {})
    if not required_runtime.issubset(annotations) or any(annotations[key] != "RUNTIME-REQUIRED" for key in required_runtime):
        errors.append("runtime correlation placeholders mismatch")

    credential = spec["credentialModel"]
    if credential["tokenRequestMaximumLifetimeSeconds"] > 10800:
        errors.append("TokenRequest lifetime exceeds three-hour bound")
    if credential["tokenRequestMaximumLifetimeSeconds"] <= credential["go1MaximumWallClockSeconds"]:
        errors.append("TokenRequest lifetime must include a bounded margin beyond GO-1")
    if credential["nativeArgoRotationClaimed"] or credential["productionSuitable"]:
        errors.append("static TokenRequest must not claim native rotation or production suitability")
    if credential["secretBytesInGitOrEvidence"] != "forbidden":
        errors.append("secret persistence must be forbidden")
    if not spec["ordering"]["platformSubmissionAfterRegistrationOnly"]:
        errors.append("platform submission must follow verified registration")
    if spec["authorityBoundary"]["nativeDefaultProjectMustRemainUnused"] is not True:
        errors.append("native default project must remain unused")
    return errors


def negative_controls() -> list[str]:
    failures = []
    base_protocol = yaml.safe_load(PROTOCOL.read_text())
    base_project = yaml.safe_load(PROJECT.read_text())
    base_access = docs(ACCESS)
    base_registration = yaml.safe_load(REGISTRATION.read_text())

    cases = []
    mutated = copy.deepcopy(base_project)
    mutated["spec"]["permitOnlyProjectScopedClusters"] = False
    cases.append(("project-scope-disabled", {"project": mutated}))
    mutated = copy.deepcopy(base_project)
    mutated["spec"]["sourceRepos"] = ["*"]
    cases.append(("project-wildcard", {"project": mutated}))
    mutated = copy.deepcopy(base_access)
    mutated[2]["rules"][0]["verbs"] = ["*"]
    cases.append(("rbac-wildcard", {"access": mutated}))
    mutated = copy.deepcopy(base_access)
    mutated[2]["rules"][1]["verbs"].append("create")
    cases.append(("namespace-create", {"access": mutated}))
    mutated = copy.deepcopy(base_registration)
    mutated["stringData"]["config"] = '{"bearerToken":"not-a-real-token"}'
    cases.append(("credential-material", {"registration": mutated}))
    mutated = copy.deepcopy(base_protocol)
    mutated["spec"]["authorization"]["go1Granted"] = True
    cases.append(("premature-grant", {"protocol": mutated}))
    mutated = copy.deepcopy(base_protocol)
    mutated["spec"]["credentialModel"]["tokenRequestMaximumLifetimeSeconds"] = 14400
    cases.append(("excessive-token-lifetime", {"protocol": mutated}))

    for name, overrides in cases:
        if not verify(**overrides):
            failures.append(f"negative control did not fail closed: {name}")
    return failures


def main() -> int:
    errors = verify() + negative_controls()
    expected = DIGEST.read_text().strip() if DIGEST.exists() else ""
    actual = digest(PROTOCOL)
    if expected != actual:
        errors.append(f"protocol digest mismatch: expected {expected!r}, got {actual!r}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: M0b runtime registration verified ({actual}); 7 negative controls fail closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
