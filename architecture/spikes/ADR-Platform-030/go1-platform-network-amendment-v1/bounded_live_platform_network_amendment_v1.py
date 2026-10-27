#!/usr/bin/env python3
"""Apply the exact OK-141 Platform network amendment with optimistic concurrency."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
MGMT = Path("/Users/arash/.kube/ok-mgmt.yaml")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


VERIFY = load("ok141_platform_network_amendment_verifier", HERE / "verify_platform_network_amendment_v1.py")
V1 = VERIFY.V1


class ActionError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def raw(client: Path, kubeconfig: Path, verb: str, uri: str, payload: bytes | None = None) -> dict:
    command = [str(client), "--kubeconfig", str(kubeconfig), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise ActionError(f"{verb} failed for bound object")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ActionError("API returned invalid JSON") from exc


def amended_document(current: dict, annotations: dict[str, str], values: dict | None = None) -> bytes:
    meta = current.get("metadata", {})
    uid, rv = meta.get("uid"), meta.get("resourceVersion")
    if not uid or not rv:
        raise ActionError("bound object lacks UID/resourceVersion")
    result = copy.deepcopy(current)
    result["metadata"].pop("managedFields", None)
    result["metadata"].pop("selfLink", None)
    result["metadata"].setdefault("annotations", {}).update(annotations)
    if values is not None:
        result["spec"]["source"]["helm"]["valuesObject"] = copy.deepcopy(values)
    return json.dumps(result, sort_keys=True, separators=(",", ":")).encode()


def uri(group: str, version: str, namespace: str | None, plural: str, name: str) -> str:
    prefix = f"/apis/{group}/{version}" if group else f"/api/{version}"
    scope = f"/namespaces/{namespace}" if namespace else ""
    return f"{prefix}{scope}/{plural}/{name}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", type=Path, required=True)
    args = parser.parse_args()
    action = V1.read_yaml_or_json(args.action)
    spec = action["spec"]
    amendment_path = HERE / spec["amendment"]["path"]
    amendment = V1.read_yaml_or_json(amendment_path)
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1PlatformNetworkAmendmentEvidence",
        "actionID": spec["actionID"],
        "actionDigest": sha(args.action),
        "amendmentDigest": sha(amendment_path),
        "fixtureDigest": spec["amendment"]["fixtureDigest"],
        "R": spec["amendment"]["R"],
        "P": spec["amendment"]["P"],
        "startedAt": now(),
        "state": "STARTED",
        "updates": [],
        "credentialPayloadRetained": False,
        "rawObjectsRetained": False,
        "retryPerformed": bool(spec.get("predecessor")),
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
    }
    output = Path(spec["outputPath"])
    try:
        if spec["authorization"] != {"state": "GRANTED", "source": "standing-dev-execution-envelope-v1", "envelopeDigest": "sha256:85e997df331d2ced4ea147c32cc4a94a419e9efdba6de17d8a8ef3cb1dbeac93"}:
            raise ActionError("standing authorization mismatch")
        if spec.get("predecessor"):
            predecessor = Path(spec["predecessor"].get("evidencePath", "/private/tmp/ok141-platform-network-amendment-live-v1-evidence.json"))
            if not predecessor.is_file() or sha(predecessor) != spec["predecessor"]["evidenceDigest"]:
                raise ActionError("predecessor evidence mismatch")
        if VERIFY.validate(amendment) != spec["amendment"]["fixtureDigest"]:
            raise ActionError("offline amendment validation failed")
        if not CLIENT.is_file() or sha(CLIENT) != "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf":
            raise ActionError("kubectl identity mismatch")
        for path in (MGMT, SHARED):
            if not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
                raise ActionError("kubeconfig mode mismatch")

        new = spec["amendment"]
        old = spec["precondition"]
        annotations = {"openkubes.io/intent-revision": new["R"], "openkubes.io/execution-fixture": new["fixtureDigest"]}
        lifecycle = [
            ("", "v1", None, "namespaces", "disposable-ok141"),
            ("cluster.x-k8s.io", "v1beta1", "disposable-ok141", "clusters", "disposable-ok141"),
            ("infrastructure.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "kubevirtclusters", "disposable-ok141"),
            ("controlplane.cluster.x-k8s.io", "v1alpha3", "disposable-ok141", "taloscontrolplanes", "disposable-ok141-cp"),
            ("bootstrap.cluster.x-k8s.io", "v1alpha3", "disposable-ok141", "talosconfigtemplates", "disposable-ok141-workers-v1-9-6"),
            ("cluster.x-k8s.io", "v1beta1", "disposable-ok141", "machinedeployments", "disposable-ok141-workers"),
            ("infrastructure.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "kubevirtmachinetemplates", "disposable-ok141-cp-7f5dd4276432"),
            ("infrastructure.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "kubevirtmachinetemplates", "disposable-ok141-workers-7f5dd4276432"),
        ]
        targets = [(MGMT, "lifecycle", uri(*item), annotations) for item in lifecycle]
        targets.append((MGMT, "enablement", uri("addons.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "helmchartproxies", "disposable-ok141-cilium"), annotations))
        registration_annotations = {**annotations, "openkubes.io/platform-revision": new["P"]}
        targets.append((SHARED, "registration", uri("", "v1", "argocd", "secrets", "disposable-ok141-cluster"), registration_annotations))

        prepared = []
        for kubeconfig, category, raw_uri, wanted in targets:
            current = raw(CLIENT, kubeconfig, "get", raw_uri)
            existing = current.get("metadata", {}).get("annotations", {})
            fixture_matches = existing.get("openkubes.io/execution-fixture") == old["oldFixtureDigest"]
            if existing.get("openkubes.io/intent-revision") != old["oldR"] or (category != "lifecycle" and not fixture_matches):
                raise ActionError(f"{category} old identity precondition failed")
            prepared.append((kubeconfig, category, raw_uri, current, amended_document(current, wanted), False, None))

        fixture = amendment["spec"]["fixture"]
        apps = {item["metadata"]["name"]: item for item in yaml.load_all((SPIKE / fixture["applicationsPath"]).read_text(), Loader=V1.UniqueKeyLoader) if item}
        for name in ("disposable-ok141-observability-alerting", "disposable-ok141-observability-dashboards", "disposable-ok141-observability-core"):
            raw_uri = uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
            current = raw(CLIENT, SHARED, "get", raw_uri)
            existing = current.get("metadata", {}).get("annotations", {})
            if existing.get("openkubes.io/intent-revision") != old["oldR"] or existing.get("openkubes.io/platform-revision") != old["oldP"] or existing.get("openkubes.io/execution-fixture") != old["oldFixtureDigest"]:
                raise ActionError("Application old identity precondition failed")
            wanted_values = None
            if name.endswith("-core"):
                wanted_values = apps[name]["spec"]["source"]["helm"]["valuesObject"]
            wanted = {**annotations, "openkubes.io/platform-revision": new["P"]}
            prepared.append((SHARED, "application", raw_uri, current, amended_document(current, wanted, wanted_values), name.endswith("-core"), wanted_values))

        if len(prepared) != 13:
            raise ActionError("preflight object count mismatch")
        evidence["preflightObjectCount"] = len(prepared)
        for kubeconfig, category, raw_uri, current, payload, spec_changed, wanted_values in prepared:
            returned = raw(CLIENT, kubeconfig, "replace", raw_uri, payload)
            meta, prior = returned.get("metadata", {}), current["metadata"]
            if meta.get("uid") != prior.get("uid") or meta.get("resourceVersion") == prior.get("resourceVersion"):
                raise ActionError(f"{category} optimistic-concurrency postcondition failed")
            if spec_changed and returned.get("spec", {}).get("source", {}).get("helm", {}).get("valuesObject") != wanted_values:
                raise ActionError("core Application semantic postcondition failed")
            evidence["updates"].append({"category": category, "identity": raw_uri.rsplit("/", 2)[-2] + "/" + raw_uri.rsplit("/", 1)[-1], "uidPreserved": True, "resourceVersionAdvanced": True, "specChanged": spec_changed})

        evidence["state"] = "PASS-AMENDED"
        evidence["finishedAt"] = now()
        evidence["updatedObjectCount"] = len(evidence["updates"])
        if evidence["updatedObjectCount"] != 13:
            raise ActionError("unexpected update count")
        output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(output, 0o600)
        print(json.dumps({"state": evidence["state"], "updatedObjectCount": evidence["updatedObjectCount"], "evidenceDigest": sha(output)}, sort_keys=True))
        return 0
    except (ActionError, KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        evidence["state"] = "STOP-PRESERVE-NO-RETRY"
        evidence["finishedAt"] = now()
        evidence["failureClass"] = type(exc).__name__
        output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(output, 0o600)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
