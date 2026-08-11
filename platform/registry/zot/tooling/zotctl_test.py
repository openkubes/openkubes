#!/usr/bin/env python3
"""Offline positive and negative tests for zotctl backup integrity and restore guards."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import base64
import os
import ssl
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import zotctl


REPOSITORY = "openkubes/machine/tiny"
TAG = "proof"


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
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.paths: list[str] = []

    def request(self, method, path, **_kwargs):
        self.assert_get(method)
        self.paths.append(path)
        if path not in self.payloads:
            zotctl.die(f"fake scratch registry has no payload for {path}")
        return 200, self.payloads[path], {}

    def assert_get(self, method: str) -> None:
        if method != "GET":
            raise AssertionError(f"unexpected method: {method}")


class FakeCatalogRegistry:
    def __init__(self, repositories: list[str]) -> None:
        self.repositories = repositories

    def paginate(self, path, identity, key, page_size=0, label="pagination"):
        self.request = (path, identity, key, page_size, label)
        return self.repositories


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
        self.assertIs(verify.func, zotctl.command_verify)
        self.assertIs(restore.func, zotctl.command_restore)

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
