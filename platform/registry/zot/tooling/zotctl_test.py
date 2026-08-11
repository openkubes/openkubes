#!/usr/bin/env python3
"""Offline positive and negative tests for zotctl backup integrity and restore guards."""

from __future__ import annotations

import hashlib
import http.cookiejar
import io
import json
import base64
import os
import ssl
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zotctl


REPOSITORY = "openkubes/machine/tiny"
TAG = "proof"
EXPECTED_IMAGE_DIGEST = "sha256:" + "a" * 64
EXPECTED_IMAGE = f"ghcr.io/project-zot/zot:v2.1.20@{EXPECTED_IMAGE_DIGEST}"
EXPECTED_CONFIG = {"http": {"address": "0.0.0.0", "port": "5000"}}


def json_bytes(document: object) -> bytes:
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def digest_of(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def inventory_for(digests: list[tuple[str, str]]) -> dict:
    root_digest = digests[-1][0]
    return {
        "schemaVersion": zotctl.INVENTORY_SCHEMA,
        "createdAt": "2026-08-10T00:00:00Z",
        "source": {
            "registryHost": "registry.ok-shared.internal",
            "namespace": "zot",
            "release": "zot",
        },
        "layoutDirectory": zotctl.LAYOUT_DIRECTORY,
        "references": [
            {"repository": REPOSITORY, "tag": TAG, "digest": root_digest}
        ],
        "digests": [
            {
                "repository": REPOSITORY,
                "digest": digest,
                "layoutRef": f"entry-{position:06d}",
            }
            for position, (digest, _media_type) in enumerate(digests, 1)
        ],
        "referrerEdges": [],
        "representativePreBackup": {
            "repository": REPOSITORY,
            "tag": TAG,
            "digest": root_digest,
        },
        "discoveryLimitation": zotctl.DISCOVERY_LIMITATION,
        "scopeLimitation": zotctl.SCOPE_LIMITATION,
        "identityLimitation": zotctl.IDENTITY_LIMITATION,
    }


def write_layout(root: Path, manifests: list[tuple[bytes, str]]) -> tuple[Path, dict]:
    layout = root / zotctl.LAYOUT_DIRECTORY
    blob_root = layout / "blobs" / "sha256"
    blob_root.mkdir(parents=True)
    (layout / "oci-layout").write_text(
        '{"imageLayoutVersion":"1.0.0"}\n', encoding="utf-8"
    )
    digests: list[tuple[str, str]] = []
    entries = []
    for position, (payload, media_type) in enumerate(manifests, 1):
        digest = digest_of(payload)
        (blob_root / digest.removeprefix("sha256:")).write_bytes(payload)
        layout_ref = f"entry-{position:06d}"
        entries.append(
            {
                "mediaType": media_type,
                "digest": digest,
                "size": len(payload),
                "annotations": {"org.opencontainers.image.ref.name": layout_ref},
            }
        )
        digests.append((digest, media_type))
    (layout / "index.json").write_text(
        json.dumps({"schemaVersion": 2, "manifests": entries}), encoding="utf-8"
    )
    return layout, inventory_for(digests)


def write_backup(root: Path, basename: str = "tiny.tar") -> tuple[Path, Path]:
    manifest_payload = json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
            "config": {"digest": digest_of(b"{}")},
            "layers": [],
        }
    )
    layout, inventory = write_layout(
        root, [(manifest_payload, zotctl.MANIFEST_MEDIA_TYPE)]
    )
    config_digest = digest_of(b"{}").removeprefix("sha256:")
    (layout / "blobs" / "sha256" / config_digest).write_bytes(b"{}")
    inventory_file = root / zotctl.INVENTORY_NAME
    inventory_file.write_bytes(json_bytes(inventory))
    artifact = root / basename
    with tarfile.open(artifact, "w") as archive:
        archive.add(layout, arcname=zotctl.LAYOUT_DIRECTORY)
        archive.add(inventory_file, arcname=zotctl.INVENTORY_NAME)
    integrity = {
        "schemaVersion": zotctl.INTEGRITY_SCHEMA,
        "createdAt": "2026-08-10T00:00:00Z",
        "artifact": {
            "basename": artifact.name,
            "size": artifact.stat().st_size,
            "sha256": zotctl.sha256_file(artifact),
        },
        "inventory": {
            "path": zotctl.INVENTORY_NAME,
            "size": inventory_file.stat().st_size,
            "sha256": zotctl.sha256_file(inventory_file),
        },
    }
    detached = root / "tiny.integrity.json"
    detached.write_bytes(json_bytes(integrity))
    return artifact, detached


def repack_backup(root: Path, artifact: Path, detached: Path) -> None:
    if artifact.exists():
        artifact.unlink()
    with tarfile.open(artifact, "w") as archive:
        archive.add(root / zotctl.LAYOUT_DIRECTORY, arcname=zotctl.LAYOUT_DIRECTORY)
        archive.add(root / zotctl.INVENTORY_NAME, arcname=zotctl.INVENTORY_NAME)
    integrity = json.loads(detached.read_text())
    integrity["artifact"]["size"] = artifact.stat().st_size
    integrity["artifact"]["sha256"] = zotctl.sha256_file(artifact)
    detached.write_bytes(json_bytes(integrity))


def package_existing_backup(root: Path, basename: str) -> tuple[Path, Path]:
    artifact = root / basename
    inventory_file = root / zotctl.INVENTORY_NAME
    with tarfile.open(artifact, "w") as archive:
        archive.add(root / zotctl.LAYOUT_DIRECTORY, arcname=zotctl.LAYOUT_DIRECTORY)
        archive.add(inventory_file, arcname=zotctl.INVENTORY_NAME)
    detached = root / f"{basename}.integrity.json"
    detached.write_bytes(
        json_bytes(
            {
                "schemaVersion": zotctl.INTEGRITY_SCHEMA,
                "createdAt": "2026-08-10T00:00:00Z",
                "artifact": {
                    "basename": artifact.name,
                    "size": artifact.stat().st_size,
                    "sha256": zotctl.sha256_file(artifact),
                },
                "inventory": {
                    "path": zotctl.INVENTORY_NAME,
                    "size": inventory_file.stat().st_size,
                    "sha256": zotctl.sha256_file(inventory_file),
                },
            }
        )
    )
    return artifact, detached


def required_referrer(
    subject: str,
    referrer: str,
    artifact_type: str = "application/spdx+json",
) -> dict[str, str]:
    return {
        "name": "image-sbom",
        "repository": REPOSITORY,
        "subjectDigest": subject,
        "referrerDigest": referrer,
        "artifactType": artifact_type,
        "role": "sbom",
    }


def release_set_for(
    members: list[dict[str, str]], referrers: list[dict[str, str]] | None = None
) -> dict:
    if referrers is None:
        referrers = [
            required_referrer(members[0]["digest"], "sha256:" + "3" * 64)
        ]
    return {
        "schemaVersion": zotctl.RELEASE_SET_SCHEMA,
        "release": {"name": "ok-138-representative-v1"},
        "members": members,
        "referrers": referrers,
    }


def release_member(
    name: str, digest: str, kind: str = "container-image", role: str = "workload"
) -> dict[str, str]:
    return {
        "name": name,
        "repository": REPOSITORY,
        "digest": digest,
        "kind": kind,
        "role": role,
    }


class FakeDiscoveryRegistry:
    hostname = "registry.ok-shared.internal"

    def __init__(self, root_payload: bytes, referrer_payload: bytes) -> None:
        self.root_payload = root_payload
        self.referrer_payload = referrer_payload
        self.root_digest = digest_of(root_payload)
        self.referrer_digest = digest_of(referrer_payload)
        self.referrer_subjects: list[str] = []

    def request(self, method, path, **_kwargs):
        if path == "/v2/":
            return 200, b"", {}
        reference = path.rsplit("/", 1)[-1]
        if reference in (TAG, self.root_digest):
            return 200, self.root_payload, {"docker-content-digest": self.root_digest}
        if reference == self.referrer_digest:
            return 200, self.referrer_payload, {
                "docker-content-digest": self.referrer_digest
            }
        zotctl.die(f"fake registry has no manifest for {reference}")

    def paginate(self, path, identity, key, page_size=0, label="pagination"):
        del page_size, label
        if key == "repositories":
            return [REPOSITORY] if identity == "machine" else []
        if path.endswith(f"/{REPOSITORY}/tags/list?n=2"):
            return [TAG]
        raise AssertionError(f"unexpected pagination request: {path}")

    def paginate_descriptors(self, path, identity, page_size, label):
        del identity, page_size, label
        subject = path.split("/referrers/", 1)[1].split("?", 1)[0]
        self.referrer_subjects.append(subject)
        if subject == self.root_digest:
            return [{"digest": self.referrer_digest}]
        if subject == self.referrer_digest:
            return [{"digest": self.root_digest}]
        raise AssertionError(f"unexpected referrer subject: {subject}")


class FakePullRegistry:
    hostname = "registry.ok-shared.internal"
    port = 5000
    insecure_plain_http = False

    def __init__(
        self,
        payloads: dict[str, bytes],
        auth_headers: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.payloads = payloads
        self.paths: list[str] = []
        self.identities: list[str] = []
        self.auth_headers = auth_headers or {}

    def request(self, method, path, **kwargs):
        self.assert_get(method)
        self.paths.append(path)
        self.identities.append(kwargs.get("identity", ""))
        if path not in self.payloads:
            zotctl.die(f"fake scratch registry has no payload for {path}")
        return 200, self.payloads[path], {}

    def assert_get(self, method: str) -> None:
        if method != "GET":
            raise AssertionError(f"unexpected method: {method}")


class FakeCatalogRegistry:
    def __init__(
        self,
        repositories: list[str] | dict[str, list[str]],
        authenticated: bool = False,
    ) -> None:
        self.repositories = repositories
        self.auth_headers = (
            {"machine": {"Authorization": "Basic x"}, "human": {"Cookie": "session=x"}}
            if authenticated
            else {}
        )
        self.requests: list[tuple[str, str, str, int, str]] = []

    def paginate(self, path, identity, key, page_size=0, label="pagination"):
        self.request = (path, identity, key, page_size, label)
        self.requests.append(self.request)
        if isinstance(self.repositories, dict):
            return self.repositories[identity]
        return self.repositories


class FakeWriteRegistry:
    hostname = "registry.ok-shared.internal"
    port = 5000
    insecure_plain_http = False

    def __init__(self, authenticated: bool) -> None:
        self.auth_headers = (
            {"machine": {"Authorization": "Basic x"}, "human": {"Cookie": "session=x"}}
            if authenticated
            else {}
        )
        self.requests: list[tuple[str, str, str]] = []

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs.get("identity", "")))
        if method == "HEAD":
            return 404, b"", {}
        if method == "POST":
            return 202, b"", {"location": "/v2/upload/session"}
        if method == "PUT":
            return 201, b"", {}
        raise AssertionError(f"unexpected request: {method} {path}")


class FakeRecoveryKube:
    def __init__(self, pvc_uid: str = "uid-reconstructed") -> None:
        self.pvc_uid = pvc_uid
        self.calls: list[tuple[str, ...]] = []
        self.service = {
            "metadata": {
                "namespace": "zot",
                "name": "zot",
                "labels": {
                    "app.kubernetes.io/instance": "zot",
                    "app.kubernetes.io/name": "zot",
                },
            },
            "spec": {
                "type": "ClusterIP",
                "clusterIP": "10.96.0.10",
                "selector": {
                    "app.kubernetes.io/instance": "zot",
                    "app.kubernetes.io/name": "zot",
                },
                "ports": [
                    {"name": "zot", "port": 5000, "targetPort": "zot", "protocol": "TCP"}
                ],
            },
        }
        self.statefulset = {
            "metadata": {
                "namespace": "zot",
                "name": "zot",
                "uid": "statefulset-uid",
                "labels": {
                    "app.kubernetes.io/instance": "zot",
                    "app.kubernetes.io/name": "zot",
                },
            },
            "spec": {"serviceName": "", "replicas": 1},
            "status": {"readyReplicas": 1},
        }
        self.pod = {
            "metadata": {
                "namespace": "zot",
                "name": "zot-0",
                "uid": "pod-uid",
                "labels": {
                    "app.kubernetes.io/instance": "zot",
                    "app.kubernetes.io/name": "zot",
                },
                "ownerReferences": [
                    {
                        "apiVersion": "apps/v1",
                        "kind": "StatefulSet",
                        "name": "zot",
                        "uid": "statefulset-uid",
                        "controller": True,
                    }
                ],
            },
            "spec": {
                "containers": [
                    {
                        "name": "zot",
                        "image": EXPECTED_IMAGE,
                        "volumeMounts": [
                            {"mountPath": "/var/lib/registry", "name": "zot-pvc"},
                            {"mountPath": "/etc/zot", "name": "zot-config"},
                            {"mountPath": "/tls", "name": "zot-server-tls"},
                            {"mountPath": "/auth", "name": "zot-htpasswd"},
                            {"mountPath": "/oidc", "name": "zot-oidc"},
                        ],
                    }
                ],
                "volumes": [
                    {
                        "name": "zot-pvc",
                        "persistentVolumeClaim": {"claimName": zotctl.LIVE_PVC},
                    },
                    {"name": "zot-config", "configMap": {"name": "zot-config"}},
                    {
                        "name": "zot-server-tls",
                        "secret": {"secretName": "zot-server-tls"},
                    },
                    {
                        "name": "zot-htpasswd",
                        "secret": {"secretName": "zot-htpasswd"},
                    },
                    {"name": "zot-oidc", "secret": {"secretName": "zot-oidc"}},
                ],
            },
            "status": {
                "phase": "Running",
                "podIP": "10.244.0.7",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [
                    {
                        "name": "zot",
                        "ready": True,
                        "imageID": f"ghcr.io/project-zot/zot@{EXPECTED_IMAGE_DIGEST}",
                    }
                ],
            },
        }
        self.endpoint_slice = {
            "metadata": {
                "namespace": "zot",
                "labels": {"kubernetes.io/service-name": "zot"},
            },
            "ports": [{"name": "zot", "port": 5000, "protocol": "TCP"}],
            "endpoints": [
                {
                    "addresses": ["10.244.0.7"],
                    "conditions": {"ready": True, "serving": True, "terminating": False},
                    "targetRef": {
                        "kind": "Pod",
                        "namespace": "zot",
                        "name": "zot-0",
                        "uid": "pod-uid",
                    },
                }
            ],
        }
        self.configmap = {"data": {"config.json": json.dumps(EXPECTED_CONFIG)}}

    def run(self, *args, **_kwargs):
        self.calls.append(args)
        if args[:2] == ("get", "namespace"):
            return "zot"
        raise AssertionError(f"unexpected run: {args}")

    def helm_json(self, *args):
        self.calls.append(args)
        return [{"name": "zot", "status": "deployed"}]

    def json(self, *args, **_kwargs):
        self.calls.append(args)
        kind = args[1]
        if kind == "service":
            return self.service
        if kind == "statefulset":
            return self.statefulset
        if kind == "pods":
            return {"items": [self.pod]}
        if kind == "pvc":
            return {
                "metadata": {
                    "namespace": "zot",
                    "name": zotctl.LIVE_PVC,
                    "uid": self.pvc_uid,
                },
                "status": {"phase": "Bound"},
            }
        if kind == "configmap":
            return self.configmap
        if kind == "endpointslices":
            return {"items": [self.endpoint_slice]}
        raise AssertionError(f"unexpected json: {args}")


class FakeResetKube:
    helm = "helm"

    def __init__(
        self,
        pvc_uid: str = "uid-reconstructed",
        *,
        release_present: bool = True,
        retain_workload: bool = False,
        created: str = "2026-08-11T12:00:00Z",
    ) -> None:
        self.pvc_uid = pvc_uid
        self.created = created
        self.pvc_present = True
        self.release_present = release_present
        self.workload_present = release_present
        self.retain_workload = retain_workload
        self.calls: list[tuple[str, ...]] = []

    def json(self, *args, **_kwargs):
        self.calls.append(("kubectl-json",) + args)
        if args[:2] != ("get", "pvc") or not self.pvc_present:
            raise AssertionError(f"unexpected json: {args}")
        return {
            "metadata": {
                "namespace": "zot",
                "name": zotctl.LIVE_PVC,
                "uid": self.pvc_uid,
                "creationTimestamp": self.created,
            },
            "status": {"phase": "Bound"},
        }

    def helm_json(self, *args):
        self.calls.append(("helm-json",) + args)
        if self.release_present:
            return [{"name": "zot", "namespace": "zot", "status": "failed"}]
        return []

    def run(self, *args, binary=None, **_kwargs):
        command = binary or "kubectl"
        self.calls.append((command,) + args)
        if command == self.helm and args[:2] == ("uninstall", "zot"):
            self.release_present = False
            if not self.retain_workload:
                self.workload_present = False
            return ""
        if args[:2] == ("get", "statefulset"):
            return "statefulset.apps/zot" if self.workload_present else ""
        if args[:2] == ("get", "pod"):
            return "pod/zot-0" if self.workload_present else ""
        if args[:3] == ("wait", "--for=delete", f"pvc/{zotctl.LIVE_PVC}"):
            return ""
        if args[:3] == ("get", "pvc", zotctl.LIVE_PVC):
            return f"persistentvolumeclaim/{zotctl.LIVE_PVC}" if self.pvc_present else ""
        raise AssertionError(f"unexpected run: command={command} args={args}")

    def delete_pvc_with_uid_precondition(self, namespace, name, expected_uid):
        self.calls.append(("api-delete", namespace, name, expected_uid))
        if expected_uid != self.pvc_uid:
            raise zotctl.Fail("API server rejected PVC UID precondition")
        self.pvc_present = False


class FakeProxyProcess:
    def __init__(self) -> None:
        self.stdout = io.StringIO("Starting to serve on 127.0.0.1:43123\n")
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        return 0

    def kill(self):
        self.terminated = True


class FakeDeleteResponse:
    status = 200

    def read(self, _size=-1):
        return b'{"kind":"Status","status":"Success"}'


class FakeDeleteConnection:
    def __init__(self, host, port, timeout=None) -> None:
        self.destination = (host, port, timeout)
        self.request_args = None

    def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)

    def getresponse(self):
        return FakeDeleteResponse()

    def close(self):
        pass


def assert_recovery_boundary(
    kube: FakeRecoveryKube,
    namespace: str = "zot",
    release: str = "zot",
    pvc_uid: str = "uid-reconstructed",
) -> None:
    zotctl.assert_disaster_recovery_boundary(
        kube,
        namespace,
        release,
        pvc_uid,
        EXPECTED_IMAGE,
        EXPECTED_IMAGE_DIGEST,
        EXPECTED_CONFIG,
    )


class ChunkedResponse:
    status = 200

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)

    def getheaders(self):
        return []

    def read(self, _size=-1):
        return next(self.chunks, b"")


class FakeConnection:
    def __init__(self, response: ChunkedResponse) -> None:
        self.response = response

    def request(self, *args, **kwargs):
        del args, kwargs

    def getresponse(self):
        return self.response

    def close(self):
        pass


class FakeRunningProcess:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        del timeout
        return 0

    def kill(self):
        self.terminated = True


class ZotctlOfflineTest(unittest.TestCase):
    def assert_rejected(self, function, expected: str) -> None:
        try:
            function()
        except zotctl.Fail as error:
            self.assertRegex(str(error), expected)
            print(f"REJECTED {error}")
        else:
            self.fail(f"production guard accepted violation matching: {expected}")

    def verify(self, artifact: Path, manifest: Path, root: Path) -> tuple[dict, Path, int]:
        work = root / f"verify-{len(list(root.glob('verify-*'))):02d}"
        work.mkdir()
        return zotctl.load_and_verify(artifact, manifest, work)

    def test_tampered_artifact_is_rejected_then_tiny_artifact_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact, detached = write_backup(root)
            original = artifact.read_bytes()
            artifact.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))
            self.assert_rejected(
                lambda: self.verify(artifact, detached, root),
                "artifact checksum does not match detached manifest",
            )
            artifact.write_bytes(original)
            inventory, _layout, blob_count = self.verify(artifact, detached, root)
            self.assertEqual(inventory["references"][0]["tag"], TAG)
            self.assertEqual(blob_count, 2)

    def test_truncated_artifact_is_rejected_then_tiny_artifact_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact, detached = write_backup(root)
            original = artifact.read_bytes()
            artifact.write_bytes(original[: len(original) // 2])
            self.assert_rejected(
                lambda: self.verify(artifact, detached, root),
                "artifact size does not match detached manifest",
            )
            artifact.write_bytes(original)
            _inventory, _layout, blob_count = self.verify(artifact, detached, root)
            self.assertEqual(blob_count, 2)

    def test_unrecorded_reference_is_rejected_then_inventory_passes(self) -> None:
        payload = json_bytes({"schemaVersion": 2, "layers": []})
        digest = digest_of(payload)
        inventory = inventory_for([(digest, zotctl.MANIFEST_MEDIA_TYPE)])
        bad = json.loads(json.dumps(inventory))
        bad["references"][0]["digest"] = "sha256:" + "f" * 64
        self.assert_rejected(
            lambda: zotctl.validate_inventory(bad),
            "reference points to an unrecorded digest",
        )
        zotctl.validate_inventory(inventory)

    def test_child_after_index_is_rejected_then_depth_first_order_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = json_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                    "layers": [],
                }
            )
            child_digest = digest_of(child)
            index = json_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": zotctl.INDEX_MEDIA_TYPE,
                    "manifests": [{"digest": child_digest}],
                }
            )
            index_digest = digest_of(index)
            layout, inventory = write_layout(
                root,
                [
                    (child, zotctl.MANIFEST_MEDIA_TYPE),
                    (index, zotctl.INDEX_MEDIA_TYPE),
                ],
            )
            bad_order = [
                (REPOSITORY, index_digest, zotctl.INDEX_MEDIA_TYPE),
                (REPOSITORY, child_digest, zotctl.MANIFEST_MEDIA_TYPE),
            ]
            self.assert_rejected(
                lambda: zotctl.validate_restore_order(layout, bad_order),
                "restore order puts index .* before child",
            )
            order = zotctl.restore_order(layout, inventory)
            zotctl.validate_restore_order(layout, order)
            self.assertEqual([item[1] for item in order], [child_digest, index_digest])

    def test_scratch_equal_to_live_is_rejected_then_distinct_target_passes(self) -> None:
        scratch_namespace = "zot-restore-drill-proof"
        self.assert_rejected(
            lambda: zotctl.validate_scratch_identity(
                scratch_namespace,
                zotctl.SCRATCH_RELEASE,
                live_namespace=scratch_namespace,
                live_release=zotctl.SCRATCH_RELEASE,
            ),
            "scratch registry collides with live",
        )
        zotctl.validate_scratch_identity(scratch_namespace, zotctl.SCRATCH_RELEASE)

    def test_recursive_referrer_is_visited_then_inventory_passes(self) -> None:
        root_payload = json_bytes({"schemaVersion": 2, "layers": []})
        referrer_payload = json_bytes(
            {"schemaVersion": 2, "layers": [], "artifactType": "example/tiny-proof"}
        )
        registry = FakeDiscoveryRegistry(root_payload, referrer_payload)
        inventory = zotctl.discover(registry, 2)
        self.assertEqual(
            registry.referrer_subjects,
            [registry.root_digest, registry.referrer_digest],
        )
        self.assertCountEqual(
            inventory.referrer_edges,
            [
                {
                    "repository": REPOSITORY,
                    "subject": registry.root_digest,
                    "referrer": registry.referrer_digest,
                },
                {
                    "repository": REPOSITORY,
                    "subject": registry.referrer_digest,
                    "referrer": registry.root_digest,
                },
            ],
        )
        zotctl.validate_inventory(inventory.document())

    def test_release_export_recursively_visits_referrers_without_catalog_or_tags(self) -> None:
        root_payload = json_bytes(
            {
                "schemaVersion": 2,
                "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                "config": {
                    "mediaType": zotctl.OCI_IMAGE_CONFIG_MEDIA_TYPE,
                    "digest": digest_of(b"{}"),
                    "size": 2,
                },
                "layers": [],
            }
        )
        root_digest = digest_of(root_payload)
        referrer_payload = json_bytes(
            {
                "schemaVersion": 2,
                "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                "layers": [],
                "artifactType": "application/spdx+json",
                "subject": {"digest": root_digest, "size": len(root_payload)},
            }
        )
        registry = FakeDiscoveryRegistry(root_payload, referrer_payload)
        release_set = release_set_for(
            [release_member("tiny-image", registry.root_digest)],
            [required_referrer(registry.root_digest, registry.referrer_digest)],
        )
        inventory = zotctl.discover_release(registry, release_set, 2)
        self.assertEqual(
            registry.referrer_subjects,
            [registry.root_digest, registry.referrer_digest],
        )
        self.assertEqual(inventory.references, [])
        self.assertEqual(inventory.release_set, release_set)
        self.assertCountEqual(
            [(item["repository"], item["digest"]) for item in inventory.digests],
            [
                (REPOSITORY, registry.root_digest),
                (REPOSITORY, registry.referrer_digest),
            ],
        )
        missing_required = json.loads(json.dumps(release_set))
        missing_required["referrers"][0]["referrerDigest"] = "sha256:" + "e" * 64
        self.assert_rejected(
            lambda: zotctl.discover_release(registry, missing_required, 2),
            "required release referrer image-sbom is absent",
        )
        bad_artifact_type = json.loads(json.dumps(release_set))
        bad_artifact_type["referrers"][0]["artifactType"] = "application/vnd.cyclonedx+json"
        self.assert_rejected(
            lambda: zotctl.discover_release(registry, bad_artifact_type, 2),
            "required release referrer image-sbom has a mismatched artifactType",
        )
        bad_subject_payload = json_bytes(
            {
                "schemaVersion": 2,
                "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                "layers": [],
                "artifactType": "application/spdx+json",
                "subject": {"digest": "sha256:" + "d" * 64, "size": 1},
            }
        )
        bad_subject_registry = FakeDiscoveryRegistry(root_payload, bad_subject_payload)
        bad_subject_release = release_set_for(
            [release_member("tiny-image", bad_subject_registry.root_digest)],
            [
                required_referrer(
                    bad_subject_registry.root_digest, bad_subject_registry.referrer_digest
                )
            ],
        )
        self.assert_rejected(
            lambda: zotctl.discover_release(bad_subject_registry, bad_subject_release, 2),
            "required release referrer image-sbom has a mismatched subject",
        )
        unavailable = json.loads(json.dumps(release_set))
        unavailable["members"][0]["digest"] = "sha256:" + "f" * 64
        self.assert_rejected(
            lambda: zotctl.discover_release(registry, unavailable, 2),
            "fake registry has no manifest",
        )
        positive = zotctl.discover_release(registry, release_set, 2)
        self.assertEqual(positive.release_set, release_set)

    def test_release_set_rejects_malformed_duplicate_and_unknown_kind_then_both_kinds_pass(self) -> None:
        image_digest = "sha256:" + "1" * 64
        chart_digest = "sha256:" + "2" * 64
        valid = release_set_for(
            [
                release_member("tiny-image", image_digest),
                release_member(
                    "tiny-chart", chart_digest, "oci-helm-chart", "deployment-chart"
                ),
            ]
        )
        malformed = json.loads(json.dumps(valid))
        malformed["members"][0]["unexpected"] = True
        self.assert_rejected(
            lambda: zotctl.validate_release_set(malformed),
            "member 1 has invalid fields",
        )
        duplicated = json.loads(json.dumps(valid))
        duplicated["members"][1]["repository"] = REPOSITORY
        duplicated["members"][1]["digest"] = image_digest
        self.assert_rejected(
            lambda: zotctl.validate_release_set(duplicated),
            "duplicate release-set member",
        )
        bad_kind = json.loads(json.dumps(valid))
        bad_kind["members"][0]["kind"] = "helm"
        self.assert_rejected(
            lambda: zotctl.validate_release_set(bad_kind),
            "unsupported kind: helm",
        )
        empty_referrers = json.loads(json.dumps(valid))
        empty_referrers["referrers"] = []
        self.assert_rejected(
            lambda: zotctl.validate_release_set(empty_referrers),
            "referrers must be a non-empty list",
        )
        self.assertEqual(zotctl.validate_release_set(valid), valid)

    def test_member_kind_rejects_mislabeled_helm_and_image_then_matching_media_passes(self) -> None:
        image_document = {
            "schemaVersion": 2,
            "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": zotctl.OCI_IMAGE_CONFIG_MEDIA_TYPE,
                "digest": "sha256:" + "a" * 64,
                "size": 2,
            },
            "layers": [],
        }
        helm_document = {
            "schemaVersion": 2,
            "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": zotctl.HELM_CONFIG_MEDIA_TYPE,
                "digest": "sha256:" + "b" * 64,
                "size": 2,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
                    "digest": "sha256:" + "c" * 64,
                    "size": 10,
                }
            ],
        }
        image_digest = digest_of(json_bytes(image_document))
        helm_digest = digest_of(json_bytes(helm_document))
        documents = {
            (REPOSITORY, image_digest): image_document,
            (REPOSITORY, helm_digest): helm_document,
        }

        def load(repository: str, digest: str) -> dict:
            return documents[(repository, digest)]

        mislabeled_image = release_set_for(
            [release_member("not-an-image", helm_digest, "container-image")]
        )
        self.assert_rejected(
            lambda: zotctl.validate_release_member_kinds(mislabeled_image, load),
            "container image member not-an-image does not use OCI image config semantics",
        )
        valid_image = release_set_for(
            [release_member("tiny-image", image_digest, "container-image")]
        )
        zotctl.validate_release_member_kinds(valid_image, load)

        mislabeled_chart = release_set_for(
            [release_member("not-a-chart", image_digest, "oci-helm-chart", "deployment-chart")]
        )
        self.assert_rejected(
            lambda: zotctl.validate_release_member_kinds(mislabeled_chart, load),
            "OCI Helm chart member not-a-chart does not use Helm config mediaType",
        )
        valid_chart = release_set_for(
            [release_member("tiny-chart", helm_digest, "oci-helm-chart", "deployment-chart")]
        )
        zotctl.validate_release_member_kinds(valid_chart, load)

        helm_without_media_type = json.loads(json.dumps(helm_document))
        helm_without_media_type.pop("mediaType")
        inferred_digest = digest_of(json_bytes(helm_without_media_type))
        documents[(REPOSITORY, inferred_digest)] = helm_without_media_type
        inferred_chart = release_set_for(
            [
                release_member(
                    "inferred-chart", inferred_digest, "oci-helm-chart", "deployment-chart"
                )
            ]
        )
        zotctl.validate_release_member_kinds(inferred_chart, load)

        helm_with_wrong_media_type = json.loads(json.dumps(helm_document))
        helm_with_wrong_media_type["mediaType"] = "application/example.manifest.v1+json"
        wrong_digest = digest_of(json_bytes(helm_with_wrong_media_type))
        documents[(REPOSITORY, wrong_digest)] = helm_with_wrong_media_type
        explicit_wrong = release_set_for(
            [
                release_member(
                    "wrong-root", wrong_digest, "oci-helm-chart", "deployment-chart"
                )
            ]
        )
        self.assert_rejected(
            lambda: zotctl.validate_release_member_kinds(explicit_wrong, load),
            "OCI Helm chart member wrong-root root is not an OCI image manifest",
        )

    def test_missing_referenced_layer_with_all_present_hashes_valid_is_rejected_then_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = b"{}"
            layer = b"release-layer"
            manifest_payload = json_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                    "config": {"digest": digest_of(config), "size": len(config)},
                    "layers": [{"digest": digest_of(layer), "size": len(layer)}],
                }
            )
            layout, inventory = write_layout(
                root, [(manifest_payload, zotctl.MANIFEST_MEDIA_TYPE)]
            )
            blob_root = layout / "blobs" / "sha256"
            (blob_root / digest_of(config).removeprefix("sha256:")).write_bytes(config)
            layer_path = blob_root / digest_of(layer).removeprefix("sha256:")
            layer_path.write_bytes(layer)
            self.assert_rejected(
                lambda: zotctl.verify_declared_size(
                    {"digest": digest_of(layer), "size": len(layer) + 1},
                    layer_path,
                    "test layer",
                ),
                "declared size does not match OCI layout bytes",
            )
            zotctl.verify_declared_size(
                {"digest": digest_of(layer), "size": len(layer)}, layer_path, "test layer"
            )
            inventory_file = root / zotctl.INVENTORY_NAME
            inventory_file.write_bytes(json_bytes(inventory))
            artifact, detached = package_existing_backup(root, "complete.tar")
            layer_path.unlink()
            repack_backup(root, artifact, detached)
            self.assert_rejected(
                lambda: self.verify(artifact, detached, root),
                "manifest-referenced OCI blob is absent",
            )
            layer_path.write_bytes(layer)
            repack_backup(root, artifact, detached)
            _inventory, _layout, count = self.verify(artifact, detached, root)
            self.assertEqual(count, 3)

    def test_release_closure_requires_recursive_referrer_edge_then_layout_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = b"{}"
            member_payload = json_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                    "config": {
                        "mediaType": zotctl.OCI_IMAGE_CONFIG_MEDIA_TYPE,
                        "digest": digest_of(config),
                        "size": len(config),
                    },
                    "layers": [],
                }
            )
            member_digest = digest_of(member_payload)
            referrer_payload = json_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                    "layers": [],
                    "artifactType": "application/spdx+json",
                    "subject": {"digest": member_digest, "size": len(member_payload)},
                }
            )
            referrer_digest = digest_of(referrer_payload)
            nested_payload = json_bytes(
                {
                    "schemaVersion": 2,
                    "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                    "layers": [],
                    "artifactType": "application/vnd.dev.cosign.simplesigning.v1+json",
                    "subject": {"digest": referrer_digest, "size": len(referrer_payload)},
                }
            )
            layout, inventory = write_layout(
                root,
                [
                    (member_payload, zotctl.MANIFEST_MEDIA_TYPE),
                    (referrer_payload, zotctl.MANIFEST_MEDIA_TYPE),
                    (nested_payload, zotctl.MANIFEST_MEDIA_TYPE),
                ],
            )
            nested_digest = digest_of(nested_payload)
            (layout / "blobs" / "sha256" / digest_of(config).removeprefix("sha256:")).write_bytes(
                config
            )
            inventory["references"] = []
            inventory["representativePreBackup"] = {}
            inventory["releaseSet"] = release_set_for(
                [release_member("tiny-image", member_digest)],
                [required_referrer(member_digest, referrer_digest)],
            )
            inventory["referrerEdges"] = [
                {
                    "repository": REPOSITORY,
                    "subject": member_digest,
                    "referrer": referrer_digest,
                }
            ]
            inventory["releaseClosure"] = {
                "recursiveReferrers": True,
                "manifests": [
                    {"repository": REPOSITORY, "digest": digest}
                    for digest in (member_digest, referrer_digest, nested_digest)
                ],
                "blobs": [],
            }
            zotctl.validate_inventory(inventory)
            self.assert_rejected(
                lambda: zotctl.verify_layout(layout, inventory),
                "release closure is incomplete or contains unrelated manifests",
            )
            inventory["referrerEdges"].append(
                {
                    "repository": REPOSITORY,
                    "subject": member_digest,
                    "referrer": nested_digest,
                }
            )
            self.assert_rejected(
                lambda: zotctl.verify_layout(layout, inventory),
                "referrer manifest .* subject does not match recorded edge",
            )
            inventory["referrerEdges"][-1]["subject"] = referrer_digest
            model = zotctl.Inventory(
                source_host="registry.ok-shared.internal",
                source_namespace="zot",
                source_release="zot",
                release_set=inventory["releaseSet"],
            )
            model.digests = inventory["digests"]
            model.referrer_edges = inventory["referrerEdges"]
            inventory["releaseClosure"] = zotctl.release_closure_document(layout, model)
            model.release_closure = inventory["releaseClosure"]
            self.assertTrue(inventory["releaseClosure"]["recursiveReferrers"])
            zotctl.verify_layout(layout, inventory)
            output = root / "retained"
            output.mkdir()
            artifact, detached = zotctl.publish_backup(root, output, model, layout)
            verify_work = root / "release-verification"
            verify_work.mkdir()
            embedded, _extracted, count = zotctl.load_and_verify(
                artifact, detached, verify_work
            )
            self.assertEqual(embedded["releaseSet"], inventory["releaseSet"])
            self.assertEqual(count, 4)

    def test_every_release_member_is_pulled_and_verified_by_digest(self) -> None:
        image_config = b"{}"
        chart_layer = b"helm-chart-payload"
        image = json_bytes(
            {
                "schemaVersion": 2,
                "config": {"digest": digest_of(image_config), "size": len(image_config)},
                "layers": [],
            }
        )
        chart = json_bytes(
            {
                "schemaVersion": 2,
                "layers": [{"digest": digest_of(chart_layer), "size": len(chart_layer)}],
                "artifactType": "helm/chart",
            }
        )
        image_digest = digest_of(image)
        chart_digest = digest_of(chart)
        release_set = release_set_for(
            [
                release_member("tiny-image", image_digest),
                release_member(
                    "tiny-chart", chart_digest, "oci-helm-chart", "deployment-chart"
                ),
            ]
        )
        image_path = f"/v2/{REPOSITORY}/manifests/{image_digest}"
        chart_path = f"/v2/{REPOSITORY}/manifests/{chart_digest}"
        config_path = f"/v2/{REPOSITORY}/blobs/{digest_of(image_config)}"
        chart_layer_path = f"/v2/{REPOSITORY}/blobs/{digest_of(chart_layer)}"
        registry = FakePullRegistry(
            {image_path: image, config_path: image_config, chart_path: b"wrong"}
        )
        self.assert_rejected(
            lambda: zotctl.pull_release_members(registry, release_set),
            "pulled release member tiny-chart manifest hashes to",
        )
        registry = FakePullRegistry(
            {
                image_path: image,
                config_path: image_config,
                chart_path: chart,
                chart_layer_path: chart_layer,
            }
        )
        zotctl.pull_release_members(registry, release_set)
        self.assertEqual(
            registry.paths, [image_path, config_path, chart_path, chart_layer_path]
        )

    def test_nonempty_scratch_catalog_is_rejected_then_empty_catalog_passes(self) -> None:
        self.assert_rejected(
            lambda: zotctl.assert_empty_registry(FakeCatalogRegistry([REPOSITORY])),
            "scratch registry is not empty before import",
        )
        empty = FakeCatalogRegistry([])
        zotctl.assert_empty_registry(empty)
        self.assertEqual(empty.request[:4], ("/v2/_catalog?n=1000", "", "repositories", 0))

    def test_live_empty_guard_rejects_either_visible_identity_then_both_empty_pass(self) -> None:
        human_visible = FakeCatalogRegistry(
            {"machine": [], "human": ["openkubes/human/existing"]}, authenticated=True
        )
        self.assert_rejected(
            lambda: zotctl.assert_empty_registry(human_visible),
            "registry is not empty before import in the visible machine/human catalog views",
        )
        empty = FakeCatalogRegistry({"machine": [], "human": []}, authenticated=True)
        zotctl.assert_empty_registry(empty)
        self.assertEqual([request[1] for request in empty.requests], ["machine", "human"])

    def test_disaster_recovery_rejects_wrong_target_before_lookup_then_exact_target_passes(self) -> None:
        kube = FakeRecoveryKube()
        self.assert_rejected(
            lambda: assert_recovery_boundary(kube, namespace="not-zot"),
            "disaster-recovery namespace must be exactly zot",
        )
        self.assertEqual(kube.calls, [])
        self.assert_rejected(
            lambda: assert_recovery_boundary(kube, release="not-zot"),
            "disaster-recovery release must be exactly zot",
        )
        self.assertEqual(kube.calls, [])
        assert_recovery_boundary(kube)

    def test_disaster_recovery_rejects_missing_or_wrong_pvc_uid_then_exact_uid_passes(self) -> None:
        kube = FakeRecoveryKube("uid-reconstructed")
        self.assert_rejected(
            lambda: assert_recovery_boundary(kube, pvc_uid=""),
            "EXPECTED_PVC_UID is required",
        )
        self.assert_rejected(
            lambda: assert_recovery_boundary(kube, pvc_uid="uid-from-another-pvc"),
            "UID is uid-reconstructed, not operator-supplied EXPECTED_PVC_UID uid-from-another-pvc",
        )
        assert_recovery_boundary(kube)

    def test_disaster_recovery_rejects_redirected_service_or_endpoint(self) -> None:
        redirected_service = FakeRecoveryKube()
        redirected_service.service["spec"]["selector"]["app.kubernetes.io/instance"] = "other"
        self.assert_rejected(
            lambda: assert_recovery_boundary(redirected_service),
            "Service zot/zot is not the exact ClusterIP selector and named-port target",
        )

        redirected_endpoint = FakeRecoveryKube()
        redirected_endpoint.endpoint_slice["endpoints"][0]["addresses"] = ["10.244.0.99"]
        self.assert_rejected(
            lambda: assert_recovery_boundary(redirected_endpoint),
            "EndpointSlice is not bound to the exact ready nonterminating zot-0",
        )

    def test_disaster_recovery_rejects_wrong_image_or_runtime_image_id(self) -> None:
        wrong_image = FakeRecoveryKube()
        wrong_image.pod["spec"]["containers"][0]["image"] = "ghcr.io/attacker/zot:latest"
        self.assert_rejected(
            lambda: assert_recovery_boundary(wrong_image),
            "image or runtime imageID does not match the digest-pinned production values",
        )

        wrong_runtime = FakeRecoveryKube()
        wrong_runtime.pod["status"]["containerStatuses"][0]["imageID"] = (
            "ghcr.io/project-zot/zot@sha256:" + "b" * 64
        )
        self.assert_rejected(
            lambda: assert_recovery_boundary(wrong_runtime),
            "image or runtime imageID does not match the digest-pinned production values",
        )

    def test_disaster_recovery_rejects_wrong_pvc_or_secret_mounts_then_complete_chain_passes(self) -> None:
        wrong_claim = FakeRecoveryKube()
        wrong_claim.pod["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = "other"
        self.assert_rejected(
            lambda: assert_recovery_boundary(wrong_claim),
            "volumes do not bind the exact PVC, config and authentication Secrets",
        )

        wrong_secret = FakeRecoveryKube()
        wrong_secret.pod["spec"]["volumes"][2]["secret"]["secretName"] = "other-tls"
        self.assert_rejected(
            lambda: assert_recovery_boundary(wrong_secret),
            "volumes do not bind the exact PVC, config and authentication Secrets",
        )

        wrong_mount = FakeRecoveryKube()
        wrong_mount.pod["spec"]["containers"][0]["volumeMounts"][0]["name"] = "other-pvc"
        self.assert_rejected(
            lambda: assert_recovery_boundary(wrong_mount),
            "does not have the exact registry/config/TLS/auth/OIDC volume mounts",
        )

        extra_mount = FakeRecoveryKube()
        extra_mount.pod["spec"]["containers"][0]["volumeMounts"].append(
            {"mountPath": "/unreviewed", "name": "zot-config"}
        )
        self.assert_rejected(
            lambda: assert_recovery_boundary(extra_mount),
            "does not have the exact registry/config/TLS/auth/OIDC volume mounts",
        )

        wrong_config = FakeRecoveryKube()
        wrong_config.configmap["data"]["config.json"] = '{"http":{"port":"9999"}}'
        self.assert_rejected(
            lambda: assert_recovery_boundary(wrong_config),
            "ConfigMap zot/zot-config does not match reviewed production config.json",
        )

        assert_recovery_boundary(FakeRecoveryKube())

    def test_incomplete_recovery_reset_rejects_wrong_uid_before_any_mutation(self) -> None:
        kube = FakeResetKube()
        self.assert_rejected(
            lambda: zotctl.reset_incomplete_disaster_recovery(
                kube, "zot", "zot", "uid-from-another-pvc", "2026-08-11T10:00:00Z"
            ),
            "is not the Bound operator-approved EXPECTED_PVC_UID uid-from-another-pvc",
        )
        self.assertFalse(any(call[1:2] in (("uninstall",), ("delete",)) for call in kube.calls))

    def test_reset_refuses_a_pvc_older_than_the_recovery_point_then_accepts_a_replacement(self) -> None:
        """The UID alone cannot tell the original claim from a replacement.

        Step 4 of the runbook hands the operator a UID. If the PVC was never actually lost,
        that UID belongs to the ORIGINAL claim and deleting it destroys the registry. A genuine
        replacement is created during the recovery, so it postdates the backup being restored.
        """
        original = FakeResetKube(created="2026-08-10T07:42:16Z")
        self.assert_rejected(
            lambda: zotctl.reset_incomplete_disaster_recovery(
                original, "zot", "zot", "uid-reconstructed", "2026-08-11T10:00:00Z"
            ),
            "it is NOT a replacement claim created during this recovery",
        )
        self.assertFalse(
            any(
                call[1:2] == ("uninstall",) or call[:1] == ("api-delete",)
                for call in original.calls
            ),
            "refused, but only after mutating something",
        )

        replacement = FakeResetKube(created="2026-08-11T12:00:00Z")
        zotctl.reset_incomplete_disaster_recovery(
            replacement, "zot", "zot", "uid-reconstructed", "2026-08-11T10:00:00Z"
        )
        self.assertTrue(any(call[:1] == ("api-delete",) for call in replacement.calls))

    def test_incomplete_recovery_reset_refuses_pvc_delete_while_workload_remains(self) -> None:
        kube = FakeResetKube(retain_workload=True)
        self.assert_rejected(
            lambda: zotctl.reset_incomplete_disaster_recovery(
                kube, "zot", "zot", "uid-reconstructed", "2026-08-11T10:00:00Z"
            ),
            "refusing to delete PVC while workload remains after uninstall",
        )
        self.assertFalse(any(call[:1] == ("api-delete",) for call in kube.calls))

    def test_incomplete_recovery_reset_revalidates_then_deletes_only_exact_pvc(self) -> None:
        kube = FakeResetKube()
        zotctl.reset_incomplete_disaster_recovery(
            kube, "zot", "zot", "uid-reconstructed", "2026-08-11T10:00:00Z"
        )
        mutations = [
            call
            for call in kube.calls
            if call[1:2] == ("uninstall",) or call[:1] == ("api-delete",)
        ]
        self.assertEqual(
            mutations,
            [
                ("helm", "uninstall", "zot", "-n", "zot", "--wait", "--timeout", "5m"),
                ("api-delete", "zot", zotctl.LIVE_PVC, "uid-reconstructed"),
            ],
        )
        pvc_reads = [call for call in kube.calls if call[:3] == ("kubectl-json", "get", "pvc")]
        self.assertEqual(len(pvc_reads), 2)
        self.assertFalse(kube.pvc_present)

    def test_kube_pvc_delete_sends_server_side_uid_precondition(self) -> None:
        process = FakeProxyProcess()
        connection = FakeDeleteConnection("unused", 0)
        with mock.patch.object(zotctl.subprocess, "Popen", return_value=process), mock.patch.object(
            zotctl.select, "select", return_value=([process.stdout], [], [])
        ), mock.patch.object(
            zotctl.http.client, "HTTPConnection", return_value=connection
        ):
            zotctl.Kube(kubeconfig="/reviewed/kubeconfig").delete_pvc_with_uid_precondition(
                "zot", zotctl.LIVE_PVC, "uid-reconstructed"
            )
        args, kwargs = connection.request_args
        self.assertEqual(args[0], "DELETE")
        self.assertEqual(
            args[1],
            f"/api/v1/namespaces/zot/persistentvolumeclaims/{zotctl.LIVE_PVC}",
        )
        body = json.loads(kwargs["body"])
        self.assertEqual(body["preconditions"], {"uid": "uid-reconstructed"})
        self.assertTrue(process.terminated)

    def test_authenticated_pulls_select_repository_identity_and_authless_scratch_stays_authless(self) -> None:
        machine_payload = json_bytes({"schemaVersion": 2, "layers": []})
        human_payload = json_bytes({"schemaVersion": 2, "layers": []})
        machine_digest = digest_of(machine_payload)
        human_digest = digest_of(human_payload)
        release_set = release_set_for(
            [
                release_member("machine", machine_digest),
                release_member("human", human_digest),
            ]
        )
        release_set["members"][1]["repository"] = "openkubes/human/tiny"
        payloads = {
            f"/v2/{REPOSITORY}/manifests/{machine_digest}": machine_payload,
            f"/v2/openkubes/human/tiny/manifests/{human_digest}": human_payload,
        }
        authenticated = FakePullRegistry(
            payloads,
            auth_headers={
                "machine": {"Authorization": "Basic x"},
                "human": {"Cookie": "session=x"},
            },
        )
        zotctl.pull_release_members(authenticated, release_set)
        self.assertEqual(authenticated.identities, ["machine", "human"])

        authless = FakePullRegistry(payloads)
        zotctl.pull_release_members(authless, release_set)
        self.assertEqual(authless.identities, ["", ""])

        self.assert_rejected(
            lambda: zotctl.restore_identity(authenticated, "outside/reviewed-prefixes"),
            "no reviewed export identity covers repository",
        )

    def test_authenticated_restore_writes_select_repository_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            blob = Path(temporary) / "blob"
            blob.write_bytes(b"content")
            digest = digest_of(blob.read_bytes())
            authenticated = FakeWriteRegistry(authenticated=True)
            zotctl.put_blob(authenticated, REPOSITORY, blob, digest)
            zotctl.put_manifest(
                authenticated,
                "openkubes/human/tiny",
                digest,
                blob,
                zotctl.MANIFEST_MEDIA_TYPE,
            )
            self.assertEqual(
                [identity for _method, _path, identity in authenticated.requests],
                ["machine", "machine", "machine", "human"],
            )

            authless = FakeWriteRegistry(authenticated=False)
            zotctl.put_blob(authless, REPOSITORY, blob, digest)
            self.assertEqual(
                [identity for _method, _path, identity in authless.requests], ["", "", ""]
            )

    def test_production_restore_uses_only_digest_and_original_tags_while_scratch_keeps_diagnostic_tag(self) -> None:
        manifest_payload = json_bytes({"schemaVersion": 2, "layers": []})
        digest = digest_of(manifest_payload)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = root / zotctl.LAYOUT_DIRECTORY
            blob_root = layout / "blobs" / "sha256"
            blob_root.mkdir(parents=True)
            (blob_root / digest.removeprefix("sha256:")).write_bytes(manifest_payload)
            inventory = {
                "references": [
                    {"repository": REPOSITORY, "tag": "original", "digest": digest}
                ],
                "referrerEdges": [],
                "representativePreBackup": {"repository": REPOSITORY, "digest": digest},
            }
            manifest_path = f"/v2/{REPOSITORY}/manifests/{digest}"
            registry = FakePullRegistry(
                {manifest_path: manifest_payload},
                auth_headers={"machine": {"Authorization": "Basic x"}},
            )
            references: list[str] = []

            def record_manifest(_registry, _repository, reference, _path, _media_type):
                references.append(reference)

            with mock.patch.object(
                zotctl,
                "restore_order",
                return_value=[(REPOSITORY, digest, zotctl.MANIFEST_MEDIA_TYPE)],
            ), mock.patch.object(zotctl, "validate_restore_order"), mock.patch.object(
                zotctl, "repository_blob_requirements", return_value={}
            ), mock.patch.object(
                zotctl, "put_manifest", side_effect=record_manifest
            ), mock.patch.object(
                zotctl, "pull_referrer_content"
            ):
                zotctl.restore_content(registry, layout, inventory, root)

            self.assertEqual(references, [digest, "original"])
            self.assertFalse(any(reference.startswith("ok138-restore-") for reference in references))

        scratch = zotctl.Registry(hostname="127.0.0.1", port=1, insecure_plain_http=True)
        self.assertEqual(
            zotctl.restore_manifest_reference(scratch, digest),
            f"ok138-restore-{digest.removeprefix('sha256:')}",
        )

    def test_referrer_manifest_and_blob_are_pulled_by_digest_after_import(self) -> None:
        subject_digest = "sha256:" + "1" * 64
        sbom = b'{"bomFormat":"CycloneDX"}'
        referrer = json_bytes(
            {
                "schemaVersion": 2,
                "mediaType": zotctl.MANIFEST_MEDIA_TYPE,
                "artifactType": "application/vnd.cyclonedx+json",
                "subject": {"digest": subject_digest, "size": 1},
                "blobs": [{"digest": digest_of(sbom), "size": len(sbom)}],
            }
        )
        referrer_digest = digest_of(referrer)
        manifest_path = f"/v2/{REPOSITORY}/manifests/{referrer_digest}"
        blob_path = f"/v2/{REPOSITORY}/blobs/{digest_of(sbom)}"
        inventory = {
            "referrerEdges": [
                {
                    "repository": REPOSITORY,
                    "subject": subject_digest,
                    "referrer": referrer_digest,
                }
            ]
        }
        self.assert_rejected(
            lambda: zotctl.pull_referrer_content(
                FakePullRegistry({manifest_path: referrer}), inventory
            ),
            "fake scratch registry has no payload",
        )
        self.assert_rejected(
            lambda: zotctl.pull_referrer_content(
                FakePullRegistry({manifest_path: referrer, blob_path: b"corrupt"}), inventory
            ),
            "pulled referrer .* blob hashes to",
        )
        registry = FakePullRegistry({manifest_path: referrer, blob_path: sbom})
        zotctl.pull_referrer_content(registry, inventory)
        self.assertEqual(registry.paths, [manifest_path, blob_path])

    def test_existing_stream_target_is_rejected_then_chunks_stream_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "blob"
            destination.write_bytes(b"occupied")
            registry = zotctl.Registry(
                "registry.invalid",
                5000,
                insecure_plain_http=True,
                auth_headers={"machine": {"Authorization": "Basic x"}},
            )
            response = ChunkedResponse([b"tiny-", b"artifact"])
            with mock.patch.object(
                registry, "_connection", return_value=FakeConnection(response)
            ):
                self.assert_rejected(
                    lambda: registry.download("/blob", destination, identity="machine"),
                    "refusing to overwrite response destination",
                )
            destination.unlink()
            response = ChunkedResponse([b"tiny-", b"artifact"])
            with mock.patch.object(
                registry, "_connection", return_value=FakeConnection(response)
            ):
                digest, _headers = registry.download(
                    "/blob", destination, identity="machine"
                )
            self.assertEqual(destination.read_bytes(), b"tiny-artifact")
            self.assertEqual(digest, hashlib.sha256(b"tiny-artifact").hexdigest())

    def test_invalid_secret_data_is_rejected_then_multiline_ca_passes(self) -> None:
        self.assert_rejected(
            lambda: zotctl.secret_bytes({"data": {"ca.crt": "%%%"}}, "tls", "ca.crt"),
            "Secret tls has an invalid ca.crt",
        )
        pem = b"-----BEGIN CERTIFICATE-----\nproof\n-----END CERTIFICATE-----\n"
        document = {"data": {"ca.crt": base64.b64encode(pem).decode("ascii")}}
        self.assertEqual(zotctl.secret_bytes(document, "tls", "ca.crt"), pem)

    def test_oidc_login_form_and_cookie_scope_are_enforced(self) -> None:
        """The login flow must reject a page with no form, and keep only registry-scoped cookies.

        Replaces the old test of the standalone helper: the flow is now in-process, so the parts
        worth pinning are the two ways it can silently produce a useless session.
        """
        # A non-form element carrying an action attribute must never be adopted: that is how a
        # too-permissive parser would post credentials at an attacker-chosen URL.
        form = zotctl._LoginForm()
        form.feed('<html><body><div action="https://elsewhere.invalid/collect"></div></body></html>')
        self.assertIsNone(form.action)

        form = zotctl._LoginForm()
        form.feed('<form id="kc-form-login" action="https://keycloak.invalid/login"></form>')
        self.assertEqual(form.action, "https://keycloak.invalid/login")

        jar = http.cookiejar.CookieJar()
        registry_host = "registry.invalid"

        def cookie_for(domain: str, name: str) -> http.cookiejar.Cookie:
            return http.cookiejar.Cookie(
                0, name, "value", None, False, domain, True, domain.startswith("."),
                "/", True, False, None, True, None, None, {},
            )

        jar.set_cookie(cookie_for("keycloak.invalid", "KEYCLOAK_SESSION"))
        scoped = [
            f"{c.name}={c.value}" for c in jar if c.domain.lstrip(".") == registry_host
        ]
        self.assertEqual(scoped, [], "a Keycloak-domain cookie must not be sent to the registry")

        jar.set_cookie(cookie_for(registry_host, "session"))
        scoped = [
            f"{c.name}={c.value}" for c in jar if c.domain.lstrip(".") == registry_host
        ]
        self.assertEqual(scoped, ["session=value"])

    def test_pinned_handler_resolves_only_named_hosts(self) -> None:
        """Pinning is per connection now; an unnamed host must not be redirected."""
        context = ssl.create_default_context()
        handler = zotctl._PinnedHTTPSHandler(context, {"registry.invalid": "10.0.0.9"})
        self.assertEqual(handler._pinned.get("registry.invalid"), "10.0.0.9")
        self.assertIsNone(handler._pinned.get("example.invalid"))

    def test_port_forward_timeout_rejects_and_terminates_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            process = FakeRunningProcess()
            forward = zotctl.PortForward(
                zotctl.Kube(), "zot", "service/zot", 5000, Path(temporary) / "forward.log"
            )
            with mock.patch.object(zotctl.subprocess, "Popen", return_value=process), mock.patch.object(
                zotctl.time, "monotonic", side_effect=[0.0, 31.0]
            ):
                self.assert_rejected(
                    forward.__enter__, "could not determine the port-forward port"
                )
            self.assertTrue(process.terminated)

    def test_verify_parser_ignores_unrelated_invalid_environment(self) -> None:
        with mock.patch.dict(
            os.environ, {"RETAIN_SCRATCH": "true", "OCI_PAGE_SIZE": "not-an-integer"}
        ):
            args = zotctl.build_parser().parse_args(["verify", "artifact", "manifest"])
        self.assertIs(args.func, zotctl.command_verify)

    def test_release_export_parser_selects_versioned_input_and_reuses_restore_verify(self) -> None:
        export = zotctl.build_parser().parse_args(
            ["release-export", "release.json", "--backup-dir", "/retained"]
        )
        self.assertIs(export.func, zotctl.command_backup)
        self.assertEqual(export.release_set, "release.json")
        verify = zotctl.build_parser().parse_args(["verify", "release.tar", "integrity.json"])
        restore = zotctl.build_parser().parse_args(
            ["restore-drill", "release.tar", "integrity.json"]
        )
        recovery = zotctl.build_parser().parse_args(
            [
                "disaster-recovery",
                "release.tar",
                "integrity.json",
                "--expected-pvc-uid",
                "uid-reconstructed",
                "--values-file",
                "/reviewed/values.yaml",
            ]
        )
        reset = zotctl.build_parser().parse_args(
            [
                "reset-incomplete-disaster-recovery",
                "--expected-pvc-uid",
                "uid-reconstructed",
            ]
        )
        self.assertIs(verify.func, zotctl.command_verify)
        self.assertIs(restore.func, zotctl.command_restore)
        self.assertIs(recovery.func, zotctl.command_disaster_recovery)
        self.assertEqual(recovery.expected_pvc_uid, "uid-reconstructed")
        self.assertEqual(recovery.values_file, "/reviewed/values.yaml")
        self.assertIs(reset.func, zotctl.command_reset_incomplete_disaster_recovery)
        self.assertEqual(reset.expected_pvc_uid, "uid-reconstructed")

    def test_disaster_recovery_requires_approval_then_attended_terminal(self) -> None:
        base = [
            "disaster-recovery",
            "release.tar",
            "integrity.json",
            "--kubeconfig",
            "/not-read-before-gates",
            "--expected-pvc-uid",
            "uid-reconstructed",
            "--values-file",
            "/not-read-before-gates",
            "--registry-host",
            "registry.invalid",
            "--registry-lb",
            "127.0.0.1",
        ]
        with mock.patch.dict(os.environ, {"APPROVE_DISASTER_RECOVERY": "no"}):
            self.assertEqual(zotctl.main(base), 2)
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertEqual(zotctl.main(base + ["--approve"]), 2)

    def test_incomplete_recovery_reset_requires_approval_then_attended_terminal(self) -> None:
        base = [
            "reset-incomplete-disaster-recovery",
            "--kubeconfig",
            "/not-read-before-gates",
            "--expected-pvc-uid",
            "uid-reconstructed",
        ]
        with mock.patch.dict(os.environ, {"APPROVE_INCOMPLETE_RECOVERY_RESET": "no"}):
            self.assertEqual(zotctl.main(base), 2)
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertEqual(zotctl.main(base + ["--approve"]), 2)

    def test_reviewed_values_produce_exact_image_and_configuration(self) -> None:
        values_file = Path(__file__).resolve().parent.parent / "values-ok-shared.yaml"
        image, digest, config = zotctl.reviewed_live_settings(values_file)
        self.assertEqual(
            image,
            "ghcr.io/project-zot/zot:v2.1.20@sha256:"
            "542e25be4d32e7879c0cfad93492a93c81b1e059cbd2d30d485d4bd567318234",
        )
        self.assertEqual(
            digest,
            "sha256:542e25be4d32e7879c0cfad93492a93c81b1e059cbd2d30d485d4bd567318234",
        )
        self.assertEqual(config["storage"]["rootDirectory"], "/var/lib/registry")

    def test_malformed_json_is_rejected_then_valid_backup_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "malformed.tar"
            artifact.write_bytes(b"not-empty")
            detached = root / "malformed.integrity.json"
            detached.write_text("{", encoding="utf-8")
            self.assert_rejected(
                lambda: self.verify(artifact, detached, root),
                "could not parse detached integrity manifest JSON",
            )
            valid_artifact, valid_detached = write_backup(root, "valid.tar")
            _inventory, _layout, count = self.verify(valid_artifact, valid_detached, root)
            self.assertEqual(count, 2)

    def test_machine_only_release_needs_no_human_identity_then_human_member_requires_it(self) -> None:
        machine_only = zotctl.validate_release_set(
            release_set_for([release_member("tiny-image", "sha256:" + "1" * 64)])
        )
        self.assertEqual(zotctl.release_set_identities(machine_only), {"machine"})

        human_digest = "sha256:" + "4" * 64
        with_human = release_set_for(
            [
                release_member("tiny-image", "sha256:" + "1" * 64),
                release_member("human-image", human_digest),
            ]
        )
        with_human["members"][1]["repository"] = "openkubes/human/tiny"
        identities = zotctl.release_set_identities(zotctl.validate_release_set(with_human))
        self.assertEqual(identities, {"machine", "human"})

        unreviewed = release_set_for([release_member("tiny-image", "sha256:" + "1" * 64)])
        unreviewed["members"][0]["repository"] = "somebody-else/tiny"
        self.assert_rejected(
            lambda: zotctl.release_set_identities(zotctl.validate_release_set(unreviewed)),
            "no reviewed export identity covers repository",
        )

    def test_unestablished_identity_is_rejected_before_any_connection_then_established_proceeds(self) -> None:
        machine_only = zotctl.Registry(
            hostname="registry.ok-shared.internal",
            port=1,
            insecure_plain_http=True,
            auth_headers={"machine": {"Authorization": "Basic x"}},
        )
        # Fails closed on the missing credential rather than sending an unauthenticated request.
        self.assert_rejected(
            lambda: machine_only.request("GET", "/v2/", identity="human"),
            "no human credential was established for this run",
        )
        # An unnamed identity must not slip past on a registry that holds credentials: that
        # would send an unauthenticated request and surface a bare 401 far from the cause.
        self.assert_rejected(
            lambda: machine_only.request("GET", "/v2/", identity=""),
            "named no export identity on a registry that holds credentials",
        )
        self.assert_rejected(
            lambda: machine_only.request("GET", "/v2/"),
            "named no export identity on a registry that holds credentials",
        )
        # The established identity gets past the guard, so it fails on the closed port instead.
        with self.assertRaises(OSError):
            machine_only.request("GET", "/v2/", identity="machine")
        # The authless scratch registry carries no credentials, so an unnamed identity is
        # legitimate there and must still reach the network.
        scratch = zotctl.Registry(hostname="127.0.0.1", port=1, insecure_plain_http=True)
        with self.assertRaises(OSError):
            scratch.request("GET", "/v2/")


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
