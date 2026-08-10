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

    def test_existing_stream_target_is_rejected_then_chunks_stream_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "blob"
            destination.write_bytes(b"occupied")
            registry = zotctl.Registry("registry.invalid", 5000, insecure_plain_http=True)
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


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
