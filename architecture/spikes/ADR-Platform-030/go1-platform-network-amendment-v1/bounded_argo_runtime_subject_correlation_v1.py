#!/usr/bin/env python3
"""Correlate redacted Argo runtime error subjects with the registration token subject."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "argo-runtime-subject-correlation-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
SUBJECT = re.compile(r'\buser\s+"([^"]+)"', re.IGNORECASE)


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def exact(uri: str) -> dict:
    result = subprocess.run([str(CLIENT), "--kubeconfig", str(SHARED), "get", "--raw", uri], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("exact GET failed")
    return json.loads(result.stdout)


def decode_b64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def jwt_payload(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * ((4 - len(part) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(part.encode()))


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    predecessor = Path(spec["predecessor"]["path"])
    output = Path(spec["outputPath"])
    expected = set(spec["exactFailedClusterRoles"])
    if sha(predecessor) != spec["predecessor"]["digest"] or len(expected) != 5:
        raise RuntimeError("binding mismatch")
    if sha(CLIENT) != EXPECTED_CLIENT or SHARED.is_symlink() or (SHARED.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("local identity mismatch")
    if output.exists():
        raise RuntimeError("exclusive output exists")

    app = exact(spec["applicationURI"])
    secret = exact(spec["registrationSecretURI"])
    config = json.loads(decode_b64(secret["data"]["config"]))
    payload = jwt_payload(config["bearerToken"])
    registration_subject = payload.get("sub", "")
    if not registration_subject:
        raise RuntimeError("registration subject missing")

    seen_names = set()
    error_subjects = set()
    subject_bearing_messages = 0
    for item in app.get("status", {}).get("operationState", {}).get("syncResult", {}).get("resources") or []:
        if item.get("kind") != "ClusterRole" or item.get("name") not in expected or item.get("status") != "SyncFailed":
            continue
        seen_names.add(item["name"])
        match = SUBJECT.search(item.get("message", ""))
        if match:
            subject_bearing_messages += 1
            error_subjects.add(match.group(1))

    registration_digest = digest_text(registration_subject)
    error_digests = sorted(digest_text(value) for value in error_subjects)
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1ArgoRuntimeSubjectCorrelationEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "exactFailedClusterRoleSetObserved": seen_names == expected,
        "subjectBearingMessageCount": subject_bearing_messages,
        "distinctErrorSubjectCount": len(error_subjects),
        "registrationSubjectDigest": registration_digest,
        "errorSubjectDigests": error_digests,
        "allErrorSubjectsMatchRegistration": bool(error_subjects) and all(digest_text(value) == registration_digest for value in error_subjects),
        "tokenExpirationPresent": isinstance(payload.get("exp"), int),
        "rawMessagesRetained": False,
        "rawObjectsRetained": False,
        "subjectValuesRetained": False,
        "credentialPayloadRetained": False,
        "targetContactPerformed": False,
        "mutationPerformed": False,
        "retryPerformed": False,
        "cleanupPerformed": False,
        "failureInjectionPerformed": False,
    }
    evidence["state"] = "PASS-RUNTIME-SUBJECT-CORRELATED" if evidence["exactFailedClusterRoleSetObserved"] and evidence["allErrorSubjectsMatchRegistration"] else "UNRESOLVED-RUNTIME-SUBJECT"
    config = payload = app = secret = {}
    registration_subject = ""
    error_subjects.clear()

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "state": evidence["state"],
        "subjectBearingMessageCount": evidence["subjectBearingMessageCount"],
        "distinctErrorSubjectCount": evidence["distinctErrorSubjectCount"],
        "allErrorSubjectsMatchRegistration": evidence["allErrorSubjectsMatchRegistration"],
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
