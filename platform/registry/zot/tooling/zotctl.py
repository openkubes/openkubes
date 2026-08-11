#!/usr/bin/env python3
"""Backup, verify and restore-drill the ok-shared registry (OK-138).

Replaces the former zot-backup.sh and zot-restore-drill.sh, which between them made 99 jq
subprocess calls and already shelled out to Python six times for the parts that are structural:
safe tar extraction, the recursive manifest ordering, and YAML reading. Those islands were the
whole logic; this module makes them the program and leaves bash to orchestrate processes.

Parity with those scripts was demonstrated before they were retired: identical export (39
entries, 87 blobs, same representative digest), identical verification and failure messages, and
the same guards, gates and warnings. The port also fixed a real defect they carried -- they
pushed every layout blob into every repository, so a drill exceeded ten minutes without
finishing; restoring only the blobs each manifest references completes in under three.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterable

INTEGRITY_SCHEMA = "openkubes.zot-backup.integrity/v1"
INVENTORY_SCHEMA = "openkubes.zot-backup.inventory/v1"
RELEASE_SET_SCHEMA = "openkubes.artifact-release/v1"
LAYOUT_DIRECTORY = "zot-oci-layout"
INVENTORY_NAME = "inventory.json"

MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"

REPOSITORY_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
LAYOUT_REF_RE = re.compile(r"^entry-[0-9]{6}$")
DNS_RE = re.compile(r"^[A-Za-z0-9.-]+$")
SCRATCH_RELEASE = "zot-restore-drill"
SCRATCH_NAMESPACE_RE = re.compile(r"^zot-restore-drill-[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
RELEASE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RELEASE_ROLE_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
ARTIFACT_TYPE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
)
RELEASE_MEMBER_KINDS = frozenset(("container-image", "oci-helm-chart"))
OCI_IMAGE_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
OCI_IMAGE_LAYER_MEDIA_TYPES = frozenset(
    (
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.oci.image.layer.v1.tar+zstd",
    )
)
HELM_CONFIG_MEDIA_TYPE = "application/vnd.cncf.helm.config.v1+json"
HELM_LAYER_MEDIA_TYPES = frozenset(
    (
        "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
        "application/vnd.cncf.helm.chart.provenance.v1.prov",
    )
)

DISCOVERY_LIMITATION = (
    "Catalog and tags plus recursive referrers cannot discover unattached, untagged manifests; "
    "such content is not included."
)
SCOPE_LIMITATION = (
    "The two available identities cover openkubes/machine/** and openkubes/human/**; a "
    "platform-admin-created repository outside those prefixes is not observable and cannot be "
    "certified absent."
)
IDENTITY_LIMITATION = (
    "Interim export reuses write-capable machine publisher and conformance-writer identities; a "
    "distinct read-only exporter identity requires a separately approved policy rollout and zot "
    "restart."
)
STORAGE_LIMITATION = (
    "local-path storage remains interim; copy both files to independently durable off-host "
    "storage."
)


class Fail(RuntimeError):
    """Raised for every operator-visible failure; printed as FAIL and exits non-zero."""


class Gate(Fail):
    """An approval/attendance gate, matching the reference scripts' exit status 2."""


def die(message: str) -> None:
    raise Fail(message)


def gate(message: str) -> None:
    raise Gate(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"could not parse {label} JSON: {exc}")


def require_commands(*names: str) -> None:
    for name in names:
        if shutil.which(name) is None:
            die(f"required command not found: {name}")


def secret_bytes(document: Any, name: str, key: str) -> bytes:
    encoded = (document.get("data") or {}).get(key, "") if isinstance(document, dict) else ""
    try:
        value = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        die(f"Secret {name} has an invalid {key}")
    if not value:
        die(f"Secret {name} has no non-empty {key}")
    return value


# --------------------------------------------------------------------------------------
# Cluster access. Subprocesses, because kubectl and helm are the interface -- but the data
# they return is parsed as JSON here rather than piped through another process per field.
# --------------------------------------------------------------------------------------


@dataclass
class Kube:
    kubectl: str = "kubectl"
    helm: str = "helm"
    kubeconfig: str = ""

    def _base(self, binary: str) -> list[str]:
        argv = [binary]
        if self.kubeconfig:
            argv += ["--kubeconfig", self.kubeconfig]
        return argv

    def run(self, *args: str, check: bool = True, binary: str | None = None) -> str:
        argv = self._base(binary or self.kubectl) + list(args)
        result = subprocess.run(argv, capture_output=True, text=True)
        if check and result.returncode != 0:
            die(f"{' '.join(argv[:2])} failed: {result.stderr.strip()}")
        return result.stdout

    def json(self, *args: str, binary: str | None = None) -> Any:
        raw = self.run(*args, binary=binary)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            die(f"could not parse JSON from kubectl/helm: {exc}")

    def helm_json(self, *args: str) -> Any:
        return self.json(*args, binary=self.helm)

    def secret_value(self, namespace: str, name: str, key: str) -> str:
        """Read one Secret key. Never echoed, never written to a file, never in argv."""
        escaped = key.replace(".", r"\.")
        raw = self.run(
            "get", "secret", name, "-n", namespace, "-o", f"jsonpath={{.data.{escaped}}}"
        )
        if not raw:
            die(f"Secret {namespace}/{name} has no non-empty {key}")
        try:
            value = base64.b64decode(raw, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            die(f"Secret {namespace}/{name} key {key} is not valid base64 text: {exc}")
        if "\n" in value or "\r" in value:
            die(f"Secret {namespace}/{name} key {key} contains a newline")
        return value


class PortForward:
    """kubectl port-forward on an ephemeral loopback port, torn down on exit."""

    def __init__(self, kube: Kube, namespace: str, target: str, remote_port: int, log: Path):
        self.kube = kube
        self.namespace = namespace
        self.target = target
        self.remote_port = remote_port
        self.log = log
        self.process: subprocess.Popen | None = None
        self.port: int | None = None

    def __enter__(self) -> "PortForward":
        argv = self.kube._base(self.kube.kubectl) + [
            "-n", self.namespace, "port-forward", "--address", "127.0.0.1",
            self.target, f":{self.remote_port}",
        ]
        handle = self.log.open("w")
        try:
            self.process = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT)
        finally:
            handle.close()
        handle.close()
        pattern = re.compile(r"^Forwarding from 127\.0\.0\.1:(\d+) -> \d+$", re.M)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                die(f"port-forward exited early; see {self.log}")
            match = pattern.search(self.log.read_text(errors="replace"))
            if match:
                self.port = int(match.group(1))
                return self
            time.sleep(0.5)
        self.__exit__(None, None, None)
        die("could not determine the port-forward port")
        return self  # unreachable, keeps type checkers happy

    def __exit__(self, *exc: object) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


# --------------------------------------------------------------------------------------
# Registry client. One code path for every request, so blob upload, manifest PUT and the
# paginated catalog/tags/referrers traversal share one retry and error policy.
# --------------------------------------------------------------------------------------


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a pinned address while presenting and validating the real hostname.

    This is the Python equivalent of curl --resolve host:port:address: the socket goes to the
    pinned address but SNI and certificate verification still use the real hostname, so pinning
    never weakens TLS. DNS for the .internal zone is not wired yet (OK-57), which is why callers
    must pin at all; when it lands, the pins go away and this class stays correct.

    One mechanism serves both users: the registry client over a loopback port-forward, and the
    OIDC browser-flow login against the registry and Keycloak over the shared ingress VIP.
    """

    def __init__(
        self,
        hostname: str,
        connect_port: int,
        context: ssl.SSLContext,
        connect_address: str = "127.0.0.1",
        timeout: float | None = None,
    ):
        super().__init__(hostname, connect_port, context=context)
        self._connect_target = (connect_address, connect_port)
        self._sni_hostname = hostname
        if timeout is not None:
            self.timeout = timeout

    def connect(self) -> None:  # pragma: no cover - exercised live
        sock = socket.create_connection(self._connect_target, timeout=self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._sni_hostname)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """urllib opener that resolves selected hostnames to a fixed address.

    The former standalone OIDC helper achieved this by monkey-patching socket.getaddrinfo
    globally, which changed name resolution for the whole process. Pinning per connection is
    narrower and shares _PinnedHTTPSConnection with the registry client.
    """

    def __init__(self, context: ssl.SSLContext, pinned: dict[str, str], timeout: float = 30.0):
        super().__init__(context=context)
        self._pinned = pinned
        self._ssl_context = context
        self._timeout = timeout

    def https_open(self, req: urllib.request.Request):  # pragma: no cover - exercised live
        def factory(host: str, **_: Any) -> http.client.HTTPSConnection:
            hostname, _, raw_port = host.partition(":")
            port = int(raw_port) if raw_port else 443
            address = self._pinned.get(hostname, hostname)
            return _PinnedHTTPSConnection(
                hostname, port, self._ssl_context, connect_address=address,
                timeout=self._timeout,
            )

        return self.do_open(factory, req)


class _LoginForm(HTMLParser):
    """Find the Keycloak login form's action URL."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and (values.get("id") == "kc-form-login" or self.action is None):
            self.action = values.get("action")


def oidc_session_cookie(
    registry_host: str,
    keycloak_host: str,
    pinned_address: str,
    ca_file: Path,
    username: str,
    password: str,
) -> str:
    """Log in through Keycloak and return an in-memory registry session cookie.

    Deliberately no API key: zot binds a user's groups into an API key when it is minted, so a
    key would outlive this export and survive a group-membership change. A session cookie dies
    with the process.

    Credentials stay as local variables. Previously this lived in a separate script, which meant
    the caller had to open pipes, write the credentials into them, and re-exec Python through an
    os.dup2 shim purely to hand them over on descriptors 3 and 4.
    """
    context = ssl.create_default_context(cafile=str(ca_file))
    jar = CookieJar()
    opener = urllib.request.build_opener(
        _PinnedHTTPSHandler(context, {registry_host: pinned_address, keycloak_host: pinned_address}),
        urllib.request.HTTPCookieProcessor(jar),
    )
    opener.addheaders = [("X-ZOT-API-CLIENT", "zot-ui")]

    try:
        with opener.open(
            f"https://{registry_host}/zot/auth/login?provider=oidc", timeout=30
        ) as response:
            page = response.read().decode("utf-8", "replace")
    except OSError as exc:
        die(f"OIDC login could not reach the registry: {exc}")

    form = _LoginForm()
    form.feed(page)
    if not form.action:
        die("Keycloak login page had no login form action")

    payload = urllib.parse.urlencode(
        {"username": username, "password": password, "credentialId": ""}
    ).encode()
    request = urllib.request.Request(
        str(form.action),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            response.read()
    except OSError as exc:
        die(f"OIDC login POST failed: {exc}")

    cookies = [
        f"{cookie.name}={cookie.value}"
        for cookie in jar
        if cookie.domain.lstrip(".") == registry_host
    ]
    if not cookies:
        die("OIDC login returned no registry-scoped session cookie")
    return "; ".join(cookies)


@dataclass
class Registry:
    """An OCI Distribution endpoint reached over a loopback tunnel."""

    hostname: str
    port: int
    ca_file: Path | None = None
    insecure_plain_http: bool = False
    auth_headers: dict[str, dict[str, str]] = field(default_factory=dict)

    def _connection(self) -> http.client.HTTPConnection:
        if self.insecure_plain_http:
            return http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        context = ssl.create_default_context(cafile=str(self.ca_file) if self.ca_file else None)
        return _PinnedHTTPSConnection(self.hostname, self.port, context)

    def request(
        self,
        method: str,
        path: str,
        *,
        identity: str = "",
        headers: dict[str, str] | None = None,
        body: bytes | BinaryIO | None = None,
        expect: Iterable[int] = (200,),
        absolute: str = "",
        destination: Path | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        # The scratch registry is authless by construction and carries no auth_headers, so an
        # unnamed identity is only legitimate there. On a registry that does hold credentials,
        # an unnamed identity would silently send an unauthenticated request.
        if self.auth_headers and not identity:
            die(
                f"{method} {absolute or path} named no export identity on a registry that "
                "holds credentials"
            )
        if identity and identity not in self.auth_headers:
            die(
                f"no {identity} credential was established for this run, but "
                f"{method} {absolute or path} requires one"
            )
        merged = dict(self.auth_headers.get(identity, {}))
        merged.update(headers or {})
        target = absolute or path
        connection = self._connection()
        try:
            connection.request(method, target, body=body, headers=merged)
            response = connection.getresponse()
            received = {k.lower(): v for k, v in response.getheaders()}
            status = response.status
            if status not in expect:
                payload = response.read(200)
            elif destination is None:
                payload = response.read()
            else:
                if destination.exists() or destination.is_symlink():
                    die(f"refusing to overwrite response destination: {destination}")
                digest = hashlib.sha256()
                with destination.open("xb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
                        digest.update(chunk)
                payload = digest.hexdigest().encode("ascii")
        finally:
            connection.close()
        if expect and status not in expect:
            snippet = payload[:200].decode("utf-8", "replace")
            die(f"{method} {target} returned HTTP {status} (expected {sorted(expect)}): {snippet}")
        return status, payload, received

    def download(
        self,
        path: str,
        destination: Path,
        *,
        identity: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Stream a response to a new file and return the receipt-time SHA-256."""
        _, digest, received = self.request(
            "GET", path, identity=identity, headers=headers, destination=destination
        )
        return digest.decode("ascii"), received

    def paginate(
        self, path: str, identity: str, key: str, page_size: int = 0, label: str = "pagination"
    ) -> list[str]:
        """Follow RFC5988 Link rel=next, rejecting any redirect off this registry."""
        collected: list[str] = []
        target = path
        visited: set[str] = set()
        while target:
            if target in visited:
                die(f"pagination repeated a page for {identity}: {target}")
            visited.add(target)
            _, payload, headers = self.request("GET", target, identity=identity)
            try:
                document = json.loads(payload or b"{}")
            except json.JSONDecodeError as exc:
                die(f"malformed pagination JSON for {identity}: {exc}")
            values = document.get(key) or []
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                die(f"pagination field {key} for {identity} is malformed")
            collected.extend(values)
            target = self._next_link(headers.get("link", ""))
            if not target and page_size and len(values) >= page_size and values:
                separator = "&" if "?" in path else "?"
                target = f"{path}{separator}last={urllib.parse.quote(values[-1], safe='')}"
            if target in visited:
                die(f"{label} pagination repeated a page for {identity}")
        return collected

    def paginate_descriptors(
        self, path: str, identity: str, page_size: int, label: str
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        target = path
        visited: set[str] = set()
        while target:
            if target in visited:
                die(f"{label} pagination repeated a page for {identity}")
            visited.add(target)
            _, payload, headers = self.request(
                "GET", target, identity=identity, headers={"Accept": INDEX_MEDIA_TYPE}
            )
            try:
                document = json.loads(payload)
            except json.JSONDecodeError as exc:
                die(f"{label} API response is malformed: {exc}")
            values = document.get("manifests") if isinstance(document, dict) else None
            if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
                die(f"{label} API response is malformed")
            for descriptor in values:
                if not DIGEST_RE.match(str(descriptor.get("digest"))):
                    die(f"unsupported referrer digest: {descriptor.get('digest')}")
            collected.extend(values)
            target = self._next_link(headers.get("link", ""))
            if not target and len(values) >= page_size and values:
                separator = "&" if "?" in path else "?"
                last = urllib.parse.quote(values[-1]["digest"], safe="")
                target = f"{path}{separator}last={last}"
            if target in visited:
                die(f"{label} pagination repeated a page for {identity}")
        return collected

    def _next_link(self, link: str) -> str:
        target = ""
        if link:
            matches = [
                item.strip()
                for item in link.split(",")
                if 'rel="next"' in item.replace(" ", "") or "rel=next" in item.replace(" ", "")
            ]
            if len(matches) > 1:
                die("malformed or ambiguous OCI Link rel=next header")
            if matches:
                if "<" not in matches[0] or ">" not in matches[0]:
                    die("malformed or ambiguous OCI Link rel=next header")
                raw = matches[0].split("<", 1)[1].split(">", 1)[0]
                parsed = urllib.parse.urlsplit(raw)
                if parsed.scheme and parsed.scheme != ("http" if self.insecure_plain_http else "https"):
                    die("OCI pagination Link changed registry origin")
                if parsed.netloc and parsed.hostname != self.hostname:
                    die("OCI pagination Link changed registry origin")
                target = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
                if not target.startswith("/"):
                    die("OCI pagination Link is not an absolute registry path")
        return target


# --------------------------------------------------------------------------------------
# Artifact model
# --------------------------------------------------------------------------------------


@dataclass
class Inventory:
    source_host: str
    source_namespace: str
    source_release: str
    references: list[dict[str, str]] = field(default_factory=list)
    digests: list[dict[str, str]] = field(default_factory=list)
    referrer_edges: list[dict[str, str]] = field(default_factory=list)
    representative: dict[str, str] = field(default_factory=dict)
    release_set: dict[str, Any] | None = None
    release_closure: dict[str, Any] | None = None

    def document(self) -> dict[str, Any]:
        document = {
            "schemaVersion": INVENTORY_SCHEMA,
            "createdAt": utc_now(),
            "source": {
                "registryHost": self.source_host,
                "namespace": self.source_namespace,
                "release": self.source_release,
            },
            "layoutDirectory": LAYOUT_DIRECTORY,
            "references": self.references,
            "digests": self.digests,
            "referrerEdges": self.referrer_edges,
            "representativePreBackup": self.representative,
            "discoveryLimitation": DISCOVERY_LIMITATION,
            "scopeLimitation": SCOPE_LIMITATION,
            "identityLimitation": IDENTITY_LIMITATION,
        }
        if self.release_set is not None:
            document["releaseSet"] = self.release_set
            document["releaseClosure"] = self.release_closure
        return document


def validate_release_set(document: Any) -> dict[str, Any]:
    """Validate and normalize the separately versioned release-selection input."""
    if (
        not isinstance(document, dict)
        or set(document) != {"schemaVersion", "release", "members", "referrers"}
        or document.get("schemaVersion") != RELEASE_SET_SCHEMA
    ):
        die("release-set schema or required fields are invalid")
    release = document.get("release")
    if not isinstance(release, dict) or set(release) != {"name"}:
        die("release-set release must contain exactly one name")
    if not isinstance(release.get("name"), str) or not RELEASE_NAME_RE.fullmatch(release["name"]):
        die("release-set release name is invalid")
    members = document.get("members")
    if not isinstance(members, list) or not members:
        die("release-set members must be a non-empty list")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    seen_names: set[str] = set()
    for position, member in enumerate(members, 1):
        if not isinstance(member, dict) or set(member) != {
            "name", "repository", "digest", "kind", "role"
        }:
            die(f"release-set member {position} has invalid fields")
        name = member.get("name")
        repository = member.get("repository")
        digest = member.get("digest")
        kind = member.get("kind")
        role = member.get("role")
        if not isinstance(name, str) or not RELEASE_NAME_RE.fullmatch(name):
            die(f"release-set member {position} has an invalid name")
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            die(f"release-set member {position} has an unsafe repository")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            die(f"release-set member {position} has an invalid immutable digest")
        if kind not in RELEASE_MEMBER_KINDS:
            die(f"release-set member {position} has an unsupported kind: {kind}")
        if not isinstance(role, str) or not RELEASE_ROLE_RE.fullmatch(role):
            die(f"release-set member {position} has an invalid role")
        key = (repository, digest)
        if key in seen:
            die(f"duplicate release-set member: {repository}@{digest}")
        if name in seen_names:
            die(f"duplicate release-set member name: {name}")
        seen.add(key)
        seen_names.add(name)
        normalized.append(
            {
                "name": name,
                "repository": repository,
                "digest": digest,
                "kind": kind,
                "role": role,
            }
        )
    referrers = document.get("referrers")
    if not isinstance(referrers, list) or not referrers:
        die("release-set referrers must be a non-empty list")
    normalized_referrers: list[dict[str, str]] = []
    seen_referrer_names: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    for position, referrer in enumerate(referrers, 1):
        if not isinstance(referrer, dict) or set(referrer) != {
            "name",
            "repository",
            "subjectDigest",
            "referrerDigest",
            "artifactType",
            "role",
        }:
            die(f"release-set referrer {position} has invalid fields")
        name = referrer.get("name")
        repository = referrer.get("repository")
        subject = referrer.get("subjectDigest")
        digest = referrer.get("referrerDigest")
        artifact_type = referrer.get("artifactType")
        role = referrer.get("role")
        if not isinstance(name, str) or not RELEASE_NAME_RE.fullmatch(name):
            die(f"release-set referrer {position} has an invalid name")
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            die(f"release-set referrer {position} has an unsafe repository")
        if not isinstance(subject, str) or not DIGEST_RE.fullmatch(subject):
            die(f"release-set referrer {position} has an invalid subject digest")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            die(f"release-set referrer {position} has an invalid referrer digest")
        if not isinstance(artifact_type, str) or not ARTIFACT_TYPE_RE.fullmatch(artifact_type):
            die(f"release-set referrer {position} has an invalid artifactType")
        if not isinstance(role, str) or not RELEASE_ROLE_RE.fullmatch(role):
            die(f"release-set referrer {position} has an invalid role")
        edge = (repository, subject, digest)
        if edge in seen_edges:
            die(f"duplicate release-set referrer edge: {repository}|{subject}|{digest}")
        if name in seen_referrer_names:
            die(f"duplicate release-set referrer name: {name}")
        seen_edges.add(edge)
        seen_referrer_names.add(name)
        normalized_referrers.append(
            {
                "name": name,
                "repository": repository,
                "subjectDigest": subject,
                "referrerDigest": digest,
                "artifactType": artifact_type,
                "role": role,
            }
        )
    return {
        "schemaVersion": RELEASE_SET_SCHEMA,
        "release": {"name": release["name"]},
        "members": normalized,
        "referrers": normalized_referrers,
    }


def validate_inventory(document: Any) -> None:
    if not isinstance(document, dict) or document.get("schemaVersion") != INVENTORY_SCHEMA:
        die("embedded backup inventory schema or required fields are invalid")
    if document.get("layoutDirectory") != LAYOUT_DIRECTORY:
        die("embedded backup inventory names an unexpected layout directory")
    source = document.get("source") or {}
    if source.get("namespace") != "zot" or source.get("release") != "zot":
        die("embedded backup inventory source is not live zot/zot")
    for key in ("references", "digests", "referrerEdges"):
        if not isinstance(document.get(key), list):
            die(f"embedded backup inventory field {key} is not a list")
    is_release = document.get("releaseSet") is not None
    if not document["digests"] or (not is_release and not document["references"]):
        die("embedded backup inventory records no digests")
    representative = document.get("representativePreBackup") or {}
    representative_key = (
        representative.get("repository"),
        representative.get("tag"),
        representative.get("digest"),
    )
    if not is_release and not (
        REPOSITORY_RE.match(str(representative_key[0]))
        and TAG_RE.match(str(representative_key[1]))
        and DIGEST_RE.match(str(representative_key[2]))
    ):
        die("representative pre-backup digest is missing or malformed")
    seen: set[tuple[str, str]] = set()
    for item in document["digests"]:
        repository, digest, ref = item.get("repository"), item.get("digest"), item.get("layoutRef")
        if not REPOSITORY_RE.match(str(repository)):
            die(f"unsafe repository in inventory: {repository}")
        if not DIGEST_RE.match(str(digest)):
            die(f"invalid recorded digest: {digest}")
        if not LAYOUT_REF_RE.match(str(ref)):
            die(f"invalid OCI layout reference: {ref}")
        if (repository, digest) in seen:
            die(f"duplicate recorded repository digest: {repository}|{digest}")
        seen.add((repository, digest))
    for item in document["references"]:
        if not REPOSITORY_RE.match(str(item.get("repository"))):
            die("unsafe reference repository")
        if not TAG_RE.match(str(item.get("tag"))):
            die("unsafe reference tag")
        if (item.get("repository"), item.get("digest")) not in seen:
            die("reference points to an unrecorded digest")
    references = {
        (item["repository"], item["tag"], item["digest"]) for item in document["references"]
    }
    if not is_release and representative_key not in references:
        die("representative pre-backup reference is not in the recorded references")
    for edge in document["referrerEdges"]:
        repository = edge.get("repository")
        subject = edge.get("subject")
        referrer = edge.get("referrer")
        if (repository, subject) not in seen or (repository, referrer) not in seen:
            die("referrer edge points to an unrecorded digest")
    release_set = document.get("releaseSet")
    release_closure = document.get("releaseClosure")
    if (release_set is None) != (release_closure is None):
        die("embedded release definition and closure must appear together")
    if release_set is not None:
        normalized = validate_release_set(release_set)
        if release_set != normalized:
            die("embedded release-set is not in canonical form")
        member_keys = {
            (member["repository"], member["digest"]) for member in normalized["members"]
        }
        if not member_keys.issubset(seen):
            die("release-set member points to an unrecorded digest")
        if not isinstance(release_closure, dict):
            die("embedded release closure is invalid")
        if release_closure.get("recursiveReferrers") is not True:
            die("embedded release closure does not assert recursive referrer traversal")
        for key in ("manifests", "blobs"):
            if not isinstance(release_closure.get(key), list):
                die(f"embedded release closure field {key} is not a list")
        closure_manifests: set[tuple[str, str]] = set()
        for item in release_closure["manifests"]:
            if not isinstance(item, dict) or set(item) != {"repository", "digest"}:
                die("embedded release closure has an invalid manifest entry")
            key = (item.get("repository"), item.get("digest"))
            if not REPOSITORY_RE.fullmatch(str(key[0])) or not DIGEST_RE.fullmatch(str(key[1])):
                die("embedded release closure has an invalid manifest entry")
            if key in closure_manifests:
                die("embedded release closure has a duplicate manifest")
            closure_manifests.add(key)
        if closure_manifests != seen:
            die("embedded release closure manifests differ from inventory digests")
        closure_blobs = release_closure["blobs"]
        if any(not isinstance(digest, str) for digest in closure_blobs):
            die("embedded release closure blobs are invalid or duplicated")
        if len(set(closure_blobs)) != len(closure_blobs) or any(
            not DIGEST_RE.fullmatch(digest) for digest in closure_blobs
        ):
            die("embedded release closure blobs are invalid or duplicated")


def validate_integrity_document(document: Any) -> None:
    if not isinstance(document, dict) or document.get("schemaVersion") != INTEGRITY_SCHEMA:
        die("integrity manifest schema or required fields are invalid")
    artifact = document.get("artifact") or {}
    inventory = document.get("inventory") or {}
    if not isinstance(artifact.get("basename"), str):
        die("integrity manifest artifact basename is invalid")
    for block, label in ((artifact, "artifact"), (inventory, "inventory")):
        if not isinstance(block.get("size"), int) or block["size"] < 1:
            die(f"integrity manifest {label} size is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(block.get("sha256", ""))):
            die(f"integrity manifest {label} sha256 is invalid")
    if inventory.get("path") != INVENTORY_NAME:
        die("integrity manifest inventory path is invalid")


def safe_extract(archive: Path, destination: Path) -> None:
    """Extract with member-type and path-traversal validation before writing anything."""
    try:
        with tarfile.open(archive, "r:*") as handle:
            members = handle.getmembers()
            if not members:
                die("empty tar archive")
            root = destination.resolve()
            for member in members:
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    die(f"unsafe tar member type: {member.name}")
                target = (root / member.name).resolve()
                if target != root and root not in target.parents:
                    die(f"unsafe tar path: {member.name}")
            handle.extractall(destination, members=members)
    except (tarfile.TarError, OSError) as exc:
        die(f"could not safely extract backup artifact: {exc}")


def verify_layout(layout: Path, inventory: dict[str, Any]) -> int:
    """Every blob must hash to its own filename, and every recorded digest must be present."""
    marker = layout / "oci-layout"
    index_file = layout / "index.json"
    for path in (marker, index_file):
        if not path.is_file() or path.is_symlink():
            die(f"OCI layout file is absent or not a regular file: {path.name}")
    marker_document = read_json(marker, "OCI layout marker")
    if not isinstance(marker_document, dict) or marker_document.get("imageLayoutVersion") != "1.0.0":
        die("invalid OCI layout version")
    index = read_json(index_file, "OCI layout index")
    if not isinstance(index, dict) or index.get("schemaVersion") != 2 or not isinstance(index.get("manifests"), list):
        die("invalid OCI layout index")

    count = 0
    for blob in sorted((layout / "blobs").glob("*/*")):
        if not blob.is_file() or blob.is_symlink():
            die(f"OCI blob is not a regular file: {blob}")
        if blob.parent.name != "sha256":
            die(f"unsupported OCI blob algorithm: {blob.parent.name}")
        if not re.fullmatch(r"[0-9a-f]{64}", blob.name):
            die(f"invalid OCI blob filename: {blob.name}")
        if sha256_file(blob) != blob.name:
            die(f"OCI blob digest mismatch: {blob}")
        count += 1
    if count == 0:
        die("OCI layout has no blobs")

    for item in inventory["digests"]:
        blob = layout / "blobs" / "sha256" / item["digest"].removeprefix("sha256:")
        if not blob.is_file():
            die(f"recorded manifest blob is absent: {item['digest']}")
        matches = [
            entry for entry in index["manifests"]
            if entry.get("digest") == item["digest"]
            and (entry.get("annotations") or {}).get("org.opencontainers.image.ref.name")
            == item["layoutRef"]
        ]
        if len(matches) != 1:
            die(f"recorded OCI entry is absent: {item['layoutRef']}")
        verify_declared_size(matches[0], blob, f"OCI layout entry {item['layoutRef']}")
    verify_inventory_completeness(layout, inventory)
    return count


def manifest_media_type(document: dict[str, Any]) -> str:
    declared = document.get("mediaType")
    if declared:
        return str(declared)
    return INDEX_MEDIA_TYPE if "manifests" in document else MANIFEST_MEDIA_TYPE


def validate_release_member_kinds(
    release_set: dict[str, Any],
    load: Any,
) -> None:
    """Bind declared release kinds to OCI image or Helm descriptor semantics."""

    def validate_image(repository: str, digest: str, name: str, visiting: set[str]) -> None:
        if digest in visiting:
            die(f"container image member {name} has a cyclic manifest graph")
        visiting.add(digest)
        document = load(repository, digest)
        media_type = document.get("mediaType")
        if media_type == INDEX_MEDIA_TYPE:
            children = document.get("manifests")
            if not isinstance(children, list) or not children:
                die(f"container image member {name} index records no child manifests")
            for child in children:
                child_digest = child.get("digest") if isinstance(child, dict) else None
                child_media_type = child.get("mediaType") if isinstance(child, dict) else None
                if child_media_type not in (INDEX_MEDIA_TYPE, MANIFEST_MEDIA_TYPE):
                    die(f"container image member {name} index has a non-image child mediaType")
                if not DIGEST_RE.fullmatch(str(child_digest)):
                    die(f"container image member {name} index has an invalid child digest")
                validate_image(repository, child_digest, name, visiting)
        elif media_type == MANIFEST_MEDIA_TYPE:
            config = document.get("config")
            if not isinstance(config, dict) or config.get("mediaType") != OCI_IMAGE_CONFIG_MEDIA_TYPE:
                die(f"container image member {name} does not use OCI image config semantics")
            layers = document.get("layers")
            if not isinstance(layers, list) or any(
                not isinstance(layer, dict)
                or layer.get("mediaType") not in OCI_IMAGE_LAYER_MEDIA_TYPES
                for layer in layers
            ):
                die(f"container image member {name} has a non-image layer mediaType")
        else:
            die(f"container image member {name} has a non-image root mediaType: {media_type}")
        visiting.remove(digest)

    for member in release_set["members"]:
        repository = member["repository"]
        digest = member["digest"]
        name = member["name"]
        if member["kind"] == "container-image":
            validate_image(repository, digest, name, set())
            continue
        document = load(repository, digest)
        if manifest_media_type(document) != MANIFEST_MEDIA_TYPE:
            die(f"OCI Helm chart member {name} root is not an OCI image manifest")
        config = document.get("config")
        if not isinstance(config, dict) or config.get("mediaType") != HELM_CONFIG_MEDIA_TYPE:
            die(f"OCI Helm chart member {name} does not use Helm config mediaType")
        layers = document.get("layers")
        if (
            not isinstance(layers, list)
            or not layers
            or not any(
                isinstance(layer, dict)
                and layer.get("mediaType") == "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
                for layer in layers
            )
            or any(
                not isinstance(layer, dict) or layer.get("mediaType") not in HELM_LAYER_MEDIA_TYPES
                for layer in layers
            )
        ):
            die(f"OCI Helm chart member {name} does not use Helm chart layer mediaTypes")


def validate_required_referrers(
    release_set: dict[str, Any],
    edges: Iterable[tuple[str, str, str]],
    load: Any,
) -> None:
    discovered = set(edges)
    for required in release_set["referrers"]:
        edge = (
            required["repository"],
            required["subjectDigest"],
            required["referrerDigest"],
        )
        if edge not in discovered:
            die(
                f"required release referrer {required['name']} is absent from recursive "
                "Referrers API discovery"
            )
        document = load(required["repository"], required["referrerDigest"])
        subject = document.get("subject")
        if not isinstance(subject, dict) or subject.get("digest") != required["subjectDigest"]:
            die(f"required release referrer {required['name']} has a mismatched subject")
        if document.get("artifactType") != required["artifactType"]:
            die(f"required release referrer {required['name']} has a mismatched artifactType")


def restore_order(layout: Path, inventory: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Depth-first: a child manifest is pushed before any index that references it."""
    ordered: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    visiting: set[tuple[str, str]] = set()

    def visit(repository: str, digest: str) -> None:
        if (repository, digest) in seen:
            return
        if (repository, digest) in visiting:
            die(f"manifest graph contains a cycle at {repository}@{digest}")
        visiting.add((repository, digest))
        blob = layout / "blobs" / "sha256" / digest.removeprefix("sha256:")
        if not blob.is_file() or blob.is_symlink():
            die(f"recorded manifest blob is absent: {digest}")
        document = load_manifest(blob, repository, digest)
        for child in document.get("manifests", []):
            child_digest = child.get("digest")
            if not DIGEST_RE.match(str(child_digest)):
                die(f"manifest {repository}@{digest} has an invalid child digest")
            visit(repository, child_digest)
        visiting.remove((repository, digest))
        seen.add((repository, digest))
        ordered.append((repository, digest, manifest_media_type(document)))

    for item in inventory["digests"]:
        visit(item["repository"], item["digest"])
    return ordered


def load_manifest(path: Path, repository: str, digest: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"manifest {repository}@{digest} is not valid JSON: {exc}")
    if not isinstance(document, dict) or document.get("schemaVersion") != 2:
        die(f"manifest {repository}@{digest} is not schemaVersion 2 JSON")
    return document


def manifest_descriptors(document: dict[str, Any], repository: str, digest: str) -> set[str]:
    """Return only config/layer/blob descriptors belonging to one manifest."""
    descriptors: list[Any] = []
    if "config" in document:
        descriptors.append(document["config"])
    for key in ("layers", "blobs"):
        value = document.get(key, [])
        if not isinstance(value, list):
            die(f"manifest {repository}@{digest} field {key} is not a list")
        descriptors.extend(value)
    result: set[str] = set()
    for descriptor in descriptors:
        candidate = descriptor.get("digest") if isinstance(descriptor, dict) else None
        if not DIGEST_RE.match(str(candidate)):
            die(f"manifest {repository}@{digest} has an invalid blob descriptor")
        result.add(candidate)
    return result


def verify_declared_size(descriptor: dict[str, Any], path: Path, label: str) -> None:
    """When an OCI descriptor declares size, bind it to the locally verified bytes."""
    if "size" not in descriptor:
        return
    size = descriptor["size"]
    if type(size) is not int or size < 0:
        die(f"{label} has an invalid declared size")
    if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
        die(f"{label} declared size does not match OCI layout bytes")


def repository_blob_requirements(
    layout: Path, inventory: dict[str, Any]
) -> dict[str, set[str]]:
    """Map repositories to the descriptor blobs their own manifests reference."""
    requirements: dict[str, set[str]] = {}
    for repository, digest, _ in restore_order(layout, inventory):
        manifest = load_manifest(
            layout / "blobs" / "sha256" / digest.removeprefix("sha256:"),
            repository,
            digest,
        )
        requirements.setdefault(repository, set()).update(
            manifest_descriptors(manifest, repository, digest)
        )
    return requirements


def verify_inventory_completeness(layout: Path, inventory: dict[str, Any]) -> None:
    """Re-assert manifest/config/layer/child completeness using only extracted layout bytes."""
    recorded = {(item["repository"], item["digest"]) for item in inventory["digests"]}
    for repository, digest in sorted(recorded):
        manifest = load_manifest(
            layout / "blobs" / "sha256" / digest.removeprefix("sha256:"),
            repository,
            digest,
        )
        children = manifest.get("manifests", [])
        if not isinstance(children, list):
            die(f"manifest {repository}@{digest} field manifests is not a list")
        for child in children:
            child_digest = child.get("digest") if isinstance(child, dict) else None
            if not DIGEST_RE.fullmatch(str(child_digest)):
                die(f"manifest {repository}@{digest} has an invalid child digest")
            if (repository, child_digest) not in recorded:
                die(
                    f"manifest {repository}@{digest} references an unrecorded child manifest: "
                    f"{child_digest}"
                )
            child_blob = layout / "blobs" / "sha256" / child_digest.removeprefix("sha256:")
            verify_declared_size(
                child, child_blob, f"child manifest {repository}@{child_digest}"
            )
        for blob_digest in manifest_descriptors(manifest, repository, digest):
            blob = layout / "blobs" / "sha256" / blob_digest.removeprefix("sha256:")
            if not blob.is_file() or blob.is_symlink():
                die(
                    f"manifest-referenced OCI blob is absent: "
                    f"{repository}@{digest} -> {blob_digest}"
                )
        descriptors: list[Any] = []
        if "config" in manifest:
            descriptors.append(manifest["config"])
        descriptors.extend(manifest.get("layers", []))
        descriptors.extend(manifest.get("blobs", []))
        for descriptor in descriptors:
            blob_digest = descriptor["digest"]
            verify_declared_size(
                descriptor,
                layout / "blobs" / "sha256" / blob_digest.removeprefix("sha256:"),
                f"descriptor {repository}@{digest} -> {blob_digest}",
            )
    for edge in inventory["referrerEdges"]:
        repository = edge["repository"]
        referrer = edge["referrer"]
        manifest = load_manifest(
            layout / "blobs" / "sha256" / referrer.removeprefix("sha256:"),
            repository,
            referrer,
        )
        subject = manifest.get("subject")
        if not isinstance(subject, dict) or subject.get("digest") != edge["subject"]:
            die(
                f"referrer manifest {repository}@{referrer} subject does not match "
                f"recorded edge {edge['subject']}"
            )
        verify_declared_size(
            subject,
            layout / "blobs" / "sha256" / edge["subject"].removeprefix("sha256:"),
            f"referrer subject {repository}@{edge['subject']}",
        )
    if inventory.get("releaseSet") is not None:
        def load_release_manifest(repository: str, digest: str) -> dict[str, Any]:
            return load_manifest(
                layout / "blobs" / "sha256" / digest.removeprefix("sha256:"),
                repository,
                digest,
            )

        validate_required_referrers(
            inventory["releaseSet"],
            (
                (edge["repository"], edge["subject"], edge["referrer"])
                for edge in inventory["referrerEdges"]
            ),
            load_release_manifest,
        )
        validate_release_member_kinds(inventory["releaseSet"], load_release_manifest)
        verify_release_closure(layout, inventory)


def _walk_release_closure(
    layout: Path,
    release_set: dict[str, Any],
    recorded: set[tuple[str, str]],
    edges: list[dict[str, str]],
) -> tuple[set[tuple[str, str]], set[str]]:
    """Walk members, child indexes, and referrers recursively from layout metadata."""
    referrers: dict[tuple[str, str], set[str]] = {}
    for edge in edges:
        referrers.setdefault((edge["repository"], edge["subject"]), set()).add(
            edge["referrer"]
        )
    queue = [
        (member["repository"], member["digest"]) for member in release_set["members"]
    ]
    visited: set[tuple[str, str]] = set()
    blobs: set[str] = set()
    cursor = 0
    while cursor < len(queue):
        repository, digest = queue[cursor]
        cursor += 1
        key = (repository, digest)
        if key in visited:
            continue
        if key not in recorded:
            die(f"release closure references an unrecorded manifest: {repository}@{digest}")
        visited.add(key)
        manifest = load_manifest(
            layout / "blobs" / "sha256" / digest.removeprefix("sha256:"),
            repository,
            digest,
        )
        blobs.update(manifest_descriptors(manifest, repository, digest))
        children = manifest.get("manifests", [])
        if not isinstance(children, list):
            die(f"manifest {repository}@{digest} field manifests is not a list")
        for child in children:
            child_digest = child.get("digest") if isinstance(child, dict) else None
            if not DIGEST_RE.fullmatch(str(child_digest)):
                die(f"manifest {repository}@{digest} has an invalid child digest")
            queue.append((repository, child_digest))
        for referrer in sorted(referrers.get(key, set())):
            queue.append((repository, referrer))
    return visited, blobs


def release_closure_document(layout: Path, inventory: Inventory) -> dict[str, Any]:
    if inventory.release_set is None:
        die("cannot build a release closure without a release-set")
    recorded = {
        (item["repository"], item["digest"]) for item in inventory.digests
    }
    manifests, blobs = _walk_release_closure(
        layout, inventory.release_set, recorded, inventory.referrer_edges
    )
    if manifests != recorded:
        die("exported inventory contains manifests outside the declared release closure")
    return {
        "recursiveReferrers": True,
        "manifests": [
            {"repository": repository, "digest": digest}
            for repository, digest in sorted(manifests)
        ],
        "blobs": sorted(blobs),
    }


def verify_release_closure(layout: Path, inventory: dict[str, Any]) -> None:
    recorded = {(item["repository"], item["digest"]) for item in inventory["digests"]}
    manifests, blobs = _walk_release_closure(
        layout, inventory["releaseSet"], recorded, inventory["referrerEdges"]
    )
    if manifests != recorded:
        die("release closure is incomplete or contains unrelated manifests")
    closure = inventory["releaseClosure"]
    declared_manifests = {
        (item["repository"], item["digest"]) for item in closure["manifests"]
    }
    if declared_manifests != manifests:
        die("embedded release manifest closure does not match layout traversal")
    if set(closure["blobs"]) != blobs:
        die("embedded release blob closure does not match layout traversal")
    actual_blobs = {
        f"sha256:{path.name}" for path in (layout / "blobs" / "sha256").iterdir()
        if path.is_file() and not path.is_symlink()
    }
    expected_blobs = blobs | {digest for _repository, digest in manifests}
    if actual_blobs != expected_blobs:
        die("OCI layout contains missing or unrelated content outside the release closure")


def validate_restore_order(
    layout: Path,
    order: list[tuple[str, str, str]],
) -> None:
    """Reject an upload plan that puts an index before one of its children."""
    positions = {(repository, digest): index for index, (repository, digest, _) in enumerate(order)}
    if len(positions) != len(order):
        die("restore manifest order contains a duplicate")
    for repository, digest, _ in order:
        document = load_manifest(
            layout / "blobs" / "sha256" / digest.removeprefix("sha256:"),
            repository,
            digest,
        )
        for child in document.get("manifests", []):
            child_key = (repository, child.get("digest"))
            if child_key not in positions or positions[child_key] >= positions[(repository, digest)]:
                die(f"restore order puts index {repository}@{digest} before child {child_key[1]}")


def identity_for_repository(repository: str) -> str:
    if repository.startswith("openkubes/machine/"):
        return "machine"
    if repository.startswith("openkubes/human/"):
        return "human"
    die(f"no reviewed export identity covers repository: {repository}")
    return ""  # unreachable


def release_set_identities(release_set: dict[str, Any]) -> set[str]:
    """Which export identities a declared release actually needs.

    A machine-only release must not drag in the central identity plane: htpasswd covers
    openkubes/machine/**, and making an export depend on Keycloak would put the identity
    plane on the registry's own recovery path.
    """
    identities = {
        identity_for_repository(member["repository"]) for member in release_set["members"]
    }
    identities.update(
        identity_for_repository(referrer["repository"]) for referrer in release_set["referrers"]
    )
    return identities


def validate_scratch_identity(
    namespace: str,
    release: str,
    live_namespace: str = "zot",
    live_release: str = "zot",
) -> None:
    if not SCRATCH_NAMESPACE_RE.fullmatch(namespace):
        die(
            "scratch namespace must be unique and use the zot-restore-drill-* prefix: "
            f"{namespace}"
        )
    if release != SCRATCH_RELEASE:
        die("scratch release must be exactly zot-restore-drill, never the live release zot")
    if (namespace, release) == (live_namespace, live_release):
        die("scratch registry collides with live zot/zot")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# backup -- live reads, detached OCI layout publication
# --------------------------------------------------------------------------------------


def assert_live_zot(kube: Kube, namespace: str, release: str) -> None:
    if namespace != "zot":
        die(f"live registry namespace must be exactly zot, got: {namespace}")
    if release != "zot":
        die(f"live registry release must be exactly zot, got: {release}")
    service = kube.json("get", "service", release, "-n", namespace, "-o", "json")
    metadata = service.get("metadata") or {}
    labels = metadata.get("labels") or {}
    spec = service.get("spec") or {}
    ports = spec.get("ports") or []
    if not (
        metadata.get("namespace") == "zot"
        and metadata.get("name") == "zot"
        and labels.get("app.kubernetes.io/instance") == release
        and labels.get("app.kubernetes.io/name") == "zot"
        and spec.get("type") == "ClusterIP"
        and spec.get("clusterIP") != "None"
        and sum(item.get("name") == "zot" and item.get("port") == 5000 for item in ports) == 1
    ):
        die("Service zot/zot is not the live Zot release ClusterIP contract")
    pods = kube.json(
        "get", "pods", "-n", namespace,
        "-l", f"app.kubernetes.io/instance={release},app.kubernetes.io/name=zot", "-o", "json",
    )
    ready = 0
    for pod in pods.get("items") or []:
        conditions = (pod.get("status") or {}).get("conditions") or []
        if (pod.get("status") or {}).get("phase") == "Running" and any(
            item.get("type") == "Ready" and item.get("status") == "True" for item in conditions
        ):
            ready += 1
    if ready != 1:
        die("expected exactly one Ready live Zot pod for release zot")


def get_manifest(
    registry: Registry, repository: str, reference: str, identity: str
) -> tuple[bytes, str, dict[str, Any]]:
    _, payload, headers = registry.request(
        "GET",
        f"/v2/{repository}/manifests/{reference}",
        identity=identity,
        headers={"Accept": MANIFEST_ACCEPT},
    )
    digest = headers.get("docker-content-digest", reference if DIGEST_RE.match(reference) else "")
    if not DIGEST_RE.match(digest):
        die(f"manifest GET for {repository}:{reference} omitted a sha256 digest")
    computed = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if computed != digest:
        die(f"manifest bytes for {repository}:{reference} hash to {computed}, header recorded {digest}")
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        die(f"manifest {repository}@{digest} is not valid JSON: {exc}")
    if not isinstance(document, dict) or document.get("schemaVersion") != 2:
        die(f"manifest {repository}@{digest} is not schemaVersion 2 JSON")
    return payload, digest, document


def discover(registry: Registry, page_size: int) -> Inventory:
    repositories: set[str] = set()
    for identity in ("machine", "human"):
        registry.request("GET", "/v2/", identity=identity)
        repositories.update(
            registry.paginate(
                f"/v2/_catalog?n={page_size}", identity, "repositories", page_size, "catalog"
            )
        )
    for repository in repositories:
        if not REPOSITORY_RE.fullmatch(repository):
            die(f"catalog returned an unsafe repository name: {repository}")
        identity_for_repository(repository)

    references: list[dict[str, str]] = []
    queue: list[tuple[str, str]] = []
    queued: set[tuple[str, str]] = set()

    def enqueue(repository: str, digest: str) -> None:
        if not DIGEST_RE.fullmatch(digest):
            die(f"registry returned an unsupported manifest digest: {digest}")
        key = (repository, digest)
        if key not in queued:
            queued.add(key)
            queue.append(key)

    for repository in sorted(repositories):
        identity = identity_for_repository(repository)
        tags = registry.paginate(
            f"/v2/{repository}/tags/list?n={page_size}",
            identity,
            "tags",
            page_size,
            f"tag enumeration for {repository}",
        )
        for tag in tags:
            if not TAG_RE.fullmatch(tag):
                die(f"unsafe OCI tag in {repository}: {tag}")
            _, digest, _ = get_manifest(registry, repository, tag, identity)
            references.append({"repository": repository, "tag": tag, "digest": digest})
            enqueue(repository, digest)
    references = sorted(
        {(item["repository"], item["tag"]): item for item in references}.values(),
        key=lambda item: (item["repository"], item["tag"]),
    )
    if not references:
        die("registry has no discoverable tagged manifest; cannot record a representative pre-backup digest")

    edges: set[tuple[str, str, str]] = set()
    visited: set[tuple[str, str]] = set()
    cursor = 0
    while cursor < len(queue):
        repository, subject = queue[cursor]
        cursor += 1
        key = (repository, subject)
        if key in visited:
            continue
        visited.add(key)
        identity = identity_for_repository(repository)
        _, actual, document = get_manifest(registry, repository, subject, identity)
        if actual != subject:
            die(f"subject manifest bytes do not reproduce {repository}@{subject}")
        children = document.get("manifests", [])
        if not isinstance(children, list):
            die(f"manifest {repository}@{subject} field manifests is not a list")
        for child in children:
            digest = child.get("digest") if isinstance(child, dict) else None
            if not DIGEST_RE.fullmatch(str(digest)):
                die(f"manifest {repository}@{subject} has an invalid child digest")
            enqueue(repository, digest)
        descriptors = registry.paginate_descriptors(
            f"/v2/{repository}/referrers/{subject}?n={page_size}",
            identity,
            page_size,
            f"Referrers API for {repository}@{subject}",
        )
        for descriptor in descriptors:
            referrer = descriptor["digest"]
            edges.add((repository, subject, referrer))
            enqueue(repository, referrer)
    if visited != queued:
        die("recursive referrer traversal did not visit every queued digest")

    inventory = Inventory(source_host=registry.hostname, source_namespace="zot", source_release="zot")
    inventory.references = references
    inventory.digests = [
        {"repository": repository, "digest": digest, "layoutRef": f"entry-{index:06d}"}
        for index, (repository, digest) in enumerate(queue, 1)
    ]
    inventory.referrer_edges = [
        {"repository": repository, "subject": subject, "referrer": referrer}
        for repository, subject, referrer in sorted(edges)
    ]
    inventory.representative = dict(references[0])
    return inventory


def discover_release(
    registry: Registry, release_set_document: Any, page_size: int
) -> Inventory:
    """Resolve only declared members, their descriptor/child closure, and recursive referrers."""
    release_set = validate_release_set(release_set_document)
    identities = {
        identity_for_repository(member["repository"]) for member in release_set["members"]
    }
    for identity in sorted(identities):
        registry.request("GET", "/v2/", identity=identity)

    queue: list[tuple[str, str]] = []
    queued: set[tuple[str, str]] = set()

    def enqueue(repository: str, digest: str) -> None:
        if not DIGEST_RE.fullmatch(str(digest)):
            die(f"registry returned an unsupported manifest digest: {digest}")
        key = (repository, digest)
        if key not in queued:
            queued.add(key)
            queue.append(key)

    for member in release_set["members"]:
        enqueue(member["repository"], member["digest"])

    edges: set[tuple[str, str, str]] = set()
    visited: set[tuple[str, str]] = set()
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    cursor = 0
    while cursor < len(queue):
        repository, subject = queue[cursor]
        cursor += 1
        if (repository, subject) in visited:
            continue
        visited.add((repository, subject))
        identity = identity_for_repository(repository)
        _, actual, document = get_manifest(registry, repository, subject, identity)
        if actual != subject:
            die(f"manifest bytes do not reproduce declared closure {repository}@{subject}")
        documents[(repository, subject)] = document
        children = document.get("manifests", [])
        if not isinstance(children, list):
            die(f"manifest {repository}@{subject} field manifests is not a list")
        for child in children:
            child_digest = child.get("digest") if isinstance(child, dict) else None
            if not DIGEST_RE.fullmatch(str(child_digest)):
                die(f"manifest {repository}@{subject} has an invalid child digest")
            enqueue(repository, child_digest)
        descriptors = registry.paginate_descriptors(
            f"/v2/{repository}/referrers/{subject}?n={page_size}",
            identity,
            page_size,
            f"recursive Referrers API for {repository}@{subject}",
        )
        for descriptor in descriptors:
            referrer = descriptor["digest"]
            edges.add((repository, subject, referrer))
            enqueue(repository, referrer)
    if visited != queued:
        die("recursive release referrer traversal did not visit every queued digest")

    def load_discovered(repository: str, digest: str) -> dict[str, Any]:
        document = documents.get((repository, digest))
        if document is None:
            die(f"release declaration references unavailable manifest {repository}@{digest}")
        return document

    validate_required_referrers(release_set, edges, load_discovered)
    validate_release_member_kinds(release_set, load_discovered)

    inventory = Inventory(
        source_host=registry.hostname,
        source_namespace="zot",
        source_release="zot",
        release_set=release_set,
    )
    inventory.digests = [
        {"repository": repository, "digest": digest, "layoutRef": f"entry-{index:06d}"}
        for index, (repository, digest) in enumerate(queue, 1)
    ]
    inventory.referrer_edges = [
        {"repository": repository, "subject": subject, "referrer": referrer}
        for repository, subject, referrer in sorted(edges)
    ]
    return inventory


def commit_new_file(partial: Path, destination: Path, label: str) -> None:
    try:
        os.link(partial, destination)
    except FileExistsError:
        die(f"refusing to overwrite existing {label}: {destination}")
    except OSError as exc:
        die(f"atomic no-clobber {label} publication failed: {exc}")
    partial.unlink()


def export_layout(registry: Registry, inventory: Inventory, work: Path) -> Path:
    layout = work / LAYOUT_DIRECTORY
    if layout.exists() or layout.is_symlink():
        die(f"OCI layout path unexpectedly exists: {layout}")
    blob_root = layout / "blobs" / "sha256"
    blob_root.mkdir(parents=True, mode=0o700)
    (layout / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}\n')
    copied_manifests: set[tuple[str, str]] = set()

    def copy_blob(repository: str, digest: str) -> None:
        if not DIGEST_RE.fullmatch(digest):
            die(f"unsupported OCI blob digest: {digest}")
        destination = blob_root / digest.removeprefix("sha256:")
        if destination.is_file() and not destination.is_symlink():
            if sha256_file(destination) != destination.name:
                die(f"cached OCI blob digest mismatch: {digest}")
            return
        if destination.exists() or destination.is_symlink():
            die(f"unsafe OCI blob destination: {destination}")
        partial = destination.with_name(destination.name + ".partial")
        actual, _ = registry.download(
            f"/v2/{repository}/blobs/{digest}",
            partial,
            identity=identity_for_repository(repository),
        )
        if actual != destination.name:
            die(f"blob bytes for {repository}@{digest} hash to sha256:{actual}")
        commit_new_file(partial, destination, "OCI blob")

    def copy_manifest(repository: str, digest: str) -> None:
        key = (repository, digest)
        if key in copied_manifests:
            return
        copied_manifests.add(key)
        destination = blob_root / digest.removeprefix("sha256:")
        if not destination.is_file():
            partial = destination.with_name(destination.name + ".partial")
            actual, _ = registry.download(
                f"/v2/{repository}/manifests/{digest}",
                partial,
                identity=identity_for_repository(repository),
                headers={"Accept": MANIFEST_ACCEPT},
            )
            actual_digest = f"sha256:{actual}"
            if actual_digest != digest:
                die(f"manifest bytes for {repository}@{digest} hash to {actual_digest}")
            commit_new_file(partial, destination, "OCI manifest")
        document = load_manifest(destination, repository, digest)
        for descriptor in manifest_descriptors(document, repository, digest):
            copy_blob(repository, descriptor)
        children = document.get("manifests", [])
        if not isinstance(children, list):
            die(f"manifest {repository}@{digest} field manifests is not a list")
        for child in children:
            child_digest = child.get("digest") if isinstance(child, dict) else None
            if not DIGEST_RE.fullmatch(str(child_digest)):
                die(f"manifest {repository}@{digest} has an invalid child digest")
            copy_manifest(repository, child_digest)

    entries: list[dict[str, Any]] = []
    for item in inventory.digests:
        print(f"copying {item['repository']}@{item['digest']} as OCI layout entry {item['layoutRef']}")
        copy_manifest(item["repository"], item["digest"])
        manifest_path = blob_root / item["digest"].removeprefix("sha256:")
        document = load_manifest(manifest_path, item["repository"], item["digest"])
        entries.append(
            {
                "mediaType": manifest_media_type(document),
                "digest": item["digest"],
                "size": manifest_path.stat().st_size,
                "annotations": {"org.opencontainers.image.ref.name": item["layoutRef"]},
            }
        )
    (layout / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": entries}))
    return layout


def write_json_new(path: Path, document: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, separators=(",", ":"))
        handle.write("\n")
    os.chmod(path, 0o600)


def publish_backup(
    work: Path, backup_dir: Path, inventory: Inventory, layout: Path
) -> tuple[Path, Path]:
    if not backup_dir.is_dir():
        die(f"BACKUP_DIR is not an existing directory: {backup_dir}")
    if not os.access(backup_dir, os.W_OK):
        die(f"BACKUP_DIR is not writable: {backup_dir}")
    inventory_file = work / INVENTORY_NAME
    write_json_new(inventory_file, inventory.document())
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"zot-{stamp}-{os.getpid()}"
    artifact = backup_dir / f"{base}.tar"
    manifest = backup_dir / f"{base}.integrity.json"
    artifact_partial = Path(str(artifact) + ".partial")
    manifest_partial = Path(str(manifest) + ".partial")
    for target in (artifact, manifest, artifact_partial, manifest_partial):
        if target.exists() or target.is_symlink():
            die(f"refusing to overwrite existing output: {target}")
    with tarfile.open(artifact_partial, "x") as archive:
        archive.add(layout, arcname=LAYOUT_DIRECTORY, recursive=True)
        archive.add(inventory_file, arcname=INVENTORY_NAME, recursive=False)
    if artifact_partial.stat().st_size == 0:
        die("tar produced an empty artifact")
    os.chmod(artifact_partial, 0o600)
    integrity = {
        "schemaVersion": INTEGRITY_SCHEMA,
        "createdAt": utc_now(),
        "artifact": {
            "basename": artifact.name,
            "size": artifact_partial.stat().st_size,
            "sha256": sha256_file(artifact_partial),
        },
        "inventory": {
            "path": INVENTORY_NAME,
            "size": inventory_file.stat().st_size,
            "sha256": sha256_file(inventory_file),
        },
    }
    write_json_new(manifest_partial, integrity)
    validate_integrity_document(integrity)
    commit_new_file(artifact_partial, artifact, "artifact")
    commit_new_file(manifest_partial, manifest, "integrity-manifest")
    published = json.loads(manifest.read_text())
    if published["artifact"]["basename"] != artifact.name:
        die("detached manifest basename mismatch")
    if published["artifact"]["size"] != artifact.stat().st_size:
        die("detached manifest size mismatch")
    if published["artifact"]["sha256"] != sha256_file(artifact):
        die("detached manifest checksum mismatch")
    verify_work = work / "published-verification"
    verify_work.mkdir(mode=0o700)
    load_and_verify(artifact, manifest, verify_work)
    return artifact, manifest


def command_backup(args: argparse.Namespace) -> int:
    require_commands(args.kubectl)
    if args.registry_host is None or args.registry_lb is None:
        defaults = registry_defaults()
        args.registry_host = args.registry_host or defaults["REGISTRY_HOST"]
        args.registry_lb = args.registry_lb or defaults["REGISTRY_LB"]
    if args.page_size is None:
        raw_page_size = os.environ.get("OCI_PAGE_SIZE", "1000")
        try:
            args.page_size = int(raw_page_size)
        except ValueError:
            die("OCI_PAGE_SIZE must be an integer from 1 through 1000")
    if not args.kubeconfig:
        die("KUBECONFIG is required")
    if not DNS_RE.fullmatch(args.registry_host):
        die(f"REGISTRY_HOST is not a safe DNS name: {args.registry_host}")
    if not args.registry_lb:
        die("REGISTRY_LB must not be empty")
    if not args.backup_dir:
        die("BACKUP_DIR is required and must be off-cluster operator storage")
    if not 1 <= args.page_size <= 1000:
        die("OCI_PAGE_SIZE must be an integer from 1 through 1000")
    work = Path(tempfile.mkdtemp(prefix="zot-backup."))
    os.chmod(work, 0o700)
    artifact: Path | None = None
    manifest: Path | None = None
    try:
        print(f"work dir: {work}")
        kube = Kube(kubectl=args.kubectl, kubeconfig=args.kubeconfig)
        assert_live_zot(kube, args.namespace, args.release)
        ca_file = work / "ca.crt"
        tls_secret = kube.json(
            "get", "secret", args.tls_secret, "-n", args.namespace, "-o", "json"
        )
        ca_file.write_bytes(secret_bytes(tls_secret, args.tls_secret, "ca.crt"))
        machine_user = kube.secret_value(args.namespace, args.machine_secret, "machine-username")
        machine_password = kube.secret_value(args.namespace, args.machine_secret, "machine-password")
        # A whole-registry backup walks the catalog, so it may meet openkubes/human/**. A declared
        # release states its repositories up front, so it can say it needs only htpasswd.
        release_input = (
            read_json(Path(args.release_set), "release-set input") if args.release_set else None
        )
        if release_input is None:
            needs_human = True
        else:
            needs_human = "human" in release_set_identities(validate_release_set(release_input))
        with PortForward(kube, args.namespace, f"service/{args.release}", 5000, work / "live-port-forward.log") as tunnel:
            assert tunnel.port is not None
            print(
                f"source: asserted Service zot/zot through https://127.0.0.1:{tunnel.port} "
                "(loopback tunnel)"
            )
            basic = base64.b64encode(f"{machine_user}:{machine_password}".encode()).decode()
            auth_headers = {"machine": {"Authorization": f"Basic {basic}"}}
            if needs_human:
                human_user = kube.secret_value(
                    args.namespace, args.conformance_secret, "writer-username"
                )
                human_password = kube.secret_value(
                    args.namespace, args.conformance_secret, "writer-password"
                )
                cookie = oidc_session_cookie(
                    args.registry_host, args.keycloak_host, args.registry_lb,
                    ca_file, human_user, human_password,
                )
                auth_headers["human"] = {"Cookie": cookie, "X-ZOT-API-CLIENT": "zot-ui"}
                print("export identities: machine (htpasswd) and human (central OIDC session)")
            else:
                print(
                    "export identities: machine (htpasswd) only; no central OIDC session is "
                    "established because the declared release is entirely openkubes/machine/**"
                )
            registry = Registry(
                hostname=args.registry_host,
                port=tunnel.port,
                ca_file=ca_file,
                auth_headers=auth_headers,
            )
            if release_input is not None:
                inventory = discover_release(registry, release_input, args.page_size)
                print(
                    "release export: declared members plus full descriptor/child closure; "
                    "OCI referrers are followed recursively"
                )
            else:
                inventory = discover(registry, args.page_size)
            layout = export_layout(registry, inventory, work)
            if inventory.release_set is not None:
                inventory.release_closure = release_closure_document(layout, inventory)
        verify_layout(layout, inventory.document())
        artifact, manifest = publish_backup(work, Path(args.backup_dir), inventory, layout)
        print("RESULT: PASS — selected OCI content exported and detached integrity fully verified")
        print(f"BACKUP_ARTIFACT={artifact}")
        print(f"INTEGRITY_MANIFEST={manifest}")
        if inventory.release_set is not None:
            print(f"RELEASE={inventory.release_set['release']['name']}")
            print(f"RELEASE_MEMBERS={len(inventory.release_set['members'])}")
        else:
            representative = inventory.representative
            print(
                f"REPRESENTATIVE_PRE_BACKUP={args.registry_host}/{representative['repository']}"
                f"@{representative['digest']}"
            )
        warnings = (IDENTITY_LIMITATION, STORAGE_LIMITATION) if inventory.release_set else (
            DISCOVERY_LIMITATION, SCOPE_LIMITATION, IDENTITY_LIMITATION, STORAGE_LIMITATION
        )
        for warning in warnings:
            print(f"WARNING: {warning}")
        return 0
    finally:
        print(f"work dir RETAINED (mode 700; contains no registry credential): {work}")
        if artifact and artifact.is_file():
            print(f"backup artifact RETAINED (trust only if RESULT: PASS was printed): {artifact}")
        if manifest and manifest.is_file():
            print(f"integrity manifest RETAINED (trust only if RESULT: PASS was printed): {manifest}")


# --------------------------------------------------------------------------------------
# restore-drill -- isolated scratch registry, exact bytes, immutable-digest proof
# --------------------------------------------------------------------------------------


def load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        die("PyYAML is required for restore-drill")
    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        die(f"could not read {label}: {exc}")
    if not isinstance(document, dict):
        die(f"{label} is not a YAML object")
    return document


def derive_scratch_values(values_file: Path, chart_dir: Path) -> dict[str, Any]:
    if not chart_dir.is_dir() or not (chart_dir / "Chart.yaml").is_file():
        die(f"pinned Zot chart is absent: {chart_dir}")
    if not values_file.is_file():
        die(f"production values file is unreadable: {values_file}")
    chart = load_yaml(chart_dir / "Chart.yaml", "pinned chart metadata")
    if chart.get("name") != "zot":
        die("CHART_DIR is not the pinned Zot chart")
    values = load_yaml(values_file, "production values")
    image = values.get("image") or {}
    repository = image.get("repository")
    tag = image.get("tag")
    if not re.fullmatch(r"[A-Za-z0-9./_-]+", str(repository)):
        die("unsafe production image repository")
    if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", str(tag)):
        die("production Zot image is not digest pinned")

    missing = [key for key in ("podSecurityContext", "securityContext") if key not in values]
    if missing:
        die(f"production values lack {missing}; refusing to build a less-hardened scratch")
    pod_security = values["podSecurityContext"]
    container_security = values["securityContext"]
    if not isinstance(pod_security, dict) or not isinstance(container_security, dict):
        die("production pod hardening is not an object; refusing scratch deployment")
    dropped = ((container_security.get("capabilities") or {}).get("drop") or [])
    if not (
        ((pod_security.get("seccompProfile") or {}).get("type") == "RuntimeDefault")
        and container_security.get("allowPrivilegeEscalation") is False
        and container_security.get("readOnlyRootFilesystem") is True
        and container_security.get("runAsNonRoot") is True
        and "ALL" in dropped
    ):
        die("production values lack required restricted pod hardening; refusing scratch deployment")
    carried = {
        "podSecurityContext": pod_security,
        "securityContext": container_security,
    }
    if "resources" in values:
        carried["resources"] = values["resources"]
    scratch_config = json.dumps(
        {
            "storage": {"rootDirectory": "/var/lib/registry"},
            "http": {
                "address": "0.0.0.0",
                "port": "5000",
                "readTimeout": "60s",
                "writeTimeout": "60s",
            },
            "log": {"level": "info"},
        },
        separators=(",", ":"),
    )
    return {
        "replicaCount": 1,
        "image": {"repository": repository, "tag": tag, "pullPolicy": "IfNotPresent"},
        "service": {"type": "ClusterIP", "port": 5000, "clusterIP": None},
        "serviceHeadless": {"enabled": False},
        "ingress": {"enabled": False},
        "httproute": {"enabled": False},
        "listenerset": {"enabled": False},
        "persistence": False,
        "mountConfig": True,
        "mountSecret": False,
        "externalSecrets": [],
        "metrics": {"enabled": False, "serviceMonitor": {"enabled": False}},
        "configFiles": {"config.json": scratch_config},
        **carried,
    }


def normalize_upload_location(registry: Registry, raw: str) -> str:
    if not raw:
        die("scratch registry omitted blob upload Location")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        expected_scheme = "http" if registry.insecure_plain_http else "https"
        if (
            parsed.scheme != expected_scheme
            or parsed.hostname != registry.hostname
        ):
            die("scratch blob upload Location changed registry origin")
        target = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
    else:
        target = raw
    if not target.startswith("/"):
        die("scratch blob upload Location is not an absolute registry path")
    return target


def put_blob(registry: Registry, repository: str, path: Path, digest: str) -> None:
    status, _, _ = registry.request(
        "HEAD", f"/v2/{repository}/blobs/{digest}", expect=(200, 404)
    )
    if status == 200:
        return
    _, _, headers = registry.request(
        "POST", f"/v2/{repository}/blobs/uploads/", expect=(202,)
    )
    location = normalize_upload_location(registry, headers.get("location", ""))
    separator = "&" if "?" in location else "?"
    with path.open("rb") as body:
        registry.request(
            "PUT",
            f"{location}{separator}digest={urllib.parse.quote(digest, safe=':')}",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(path.stat().st_size),
            },
            body=body,
            expect=(201,),
        )


def put_manifest(
    registry: Registry,
    repository: str,
    reference: str,
    path: Path,
    media_type: str,
) -> None:
    payload = path.read_bytes()
    registry.request(
        "PUT",
        f"/v2/{repository}/manifests/{reference}",
        headers={"Content-Type": media_type, "Content-Length": str(len(payload))},
        body=payload,
        expect=(201,),
    )


def assert_live_restore_boundary(kube: Kube, namespace: str, release: str) -> None:
    if kube.run("get", "namespace", namespace, "-o", "jsonpath={.metadata.name}").strip() != "zot":
        die("live namespace validation did not return zot")
    releases = kube.helm_json("list", "--all", "-n", namespace, "-o", "json")
    if sum(item.get("name") == release and item.get("status") == "deployed" for item in releases) != 1:
        die("expected exactly one deployed live Helm release zot/zot")
    service = kube.json("get", "service", release, "-n", namespace, "-o", "json")
    metadata = service.get("metadata") or {}
    labels = metadata.get("labels") or {}
    if not (
        metadata.get("namespace") == "zot"
        and metadata.get("name") == "zot"
        and labels.get("app.kubernetes.io/instance") == release
        and labels.get("app.kubernetes.io/name") == "zot"
    ):
        die("live Service does not belong to release zot/zot")


def scratch_absent(kube: Kube, namespace: str, release: str) -> None:
    if kube.run(
        "get", "namespace", namespace, "--ignore-not-found", "-o", "name"
    ).strip():
        die(f"scratch namespace collision: namespace/{namespace} already exists")
    releases = kube.helm_json("list", "--all-namespaces", "-o", "json")
    if any(item.get("namespace") == namespace and item.get("name") == release for item in releases):
        die("scratch Helm release collision")


def teardown_scratch(kube: Kube, namespace: str, release: str) -> bool:
    failed = False
    try:
        releases = kube.helm_json("list", "--all", "-n", namespace, "-o", "json")
        count = sum(item.get("name") == release for item in releases)
    except Fail:
        count = -1
    if count == 1:
        try:
            kube.run("uninstall", release, "-n", namespace, binary=kube.helm)
            print(f"cleanup: uninstalled Helm release {namespace}/{release}")
        except Fail as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            failed = True
    elif count not in (0,):
        print(f"FAIL: exact scratch Helm release lookup returned {count}", file=sys.stderr)
        failed = True
    try:
        kube.run("delete", "namespace", namespace, "--wait=true", "--timeout=180s")
        print(f"cleanup: deleted namespace {namespace}")
    except Fail as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        failed = True
    if kube.run("get", "namespace", namespace, "--ignore-not-found", "-o", "name").strip():
        print(f"FAIL: scratch namespace still exists after cleanup: {namespace}", file=sys.stderr)
        failed = True
    releases = kube.helm_json("list", "--all-namespaces", "-o", "json")
    if any(item.get("namespace") == namespace and item.get("name") == release for item in releases):
        print("FAIL: scratch Helm release remains after cleanup", file=sys.stderr)
        failed = True
    if not failed:
        print("cleanup proof: namespace and Helm release are absent")
    return not failed


def assert_scratch_shape(
    kube: Kube,
    namespace: str,
    release: str,
    image_repository: str,
    image_tag: str,
) -> str:
    selector = f"app.kubernetes.io/instance={release},app.kubernetes.io/name=zot"
    workloads = kube.json(
        "get", "deployments,statefulsets", "-n", namespace, "-l", selector, "-o", "json"
    ).get("items") or []
    if len(workloads) != 1:
        die(f"expected exactly one scratch Zot workload, got {len(workloads)}")
    if workloads[0].get("kind") != "Deployment":
        die("persistence=false did not produce a Deployment")
    workload = (workloads[0].get("metadata") or {}).get("name")
    kube.run("rollout", "status", f"deployment/{workload}", "-n", namespace, "--timeout=180s")
    services = kube.json("get", "services", "-n", namespace, "-o", "json").get("items") or []
    if len(services) != 1:
        die("scratch registry is not ClusterIP-only")
    service_spec = services[0].get("spec") or {}
    ports = service_spec.get("ports") or []
    if not (
        service_spec.get("type") == "ClusterIP"
        and service_spec.get("clusterIP") != "None"
        and sum(item.get("port") == 5000 and "nodePort" not in item for item in ports) == 1
    ):
        die("scratch registry is not ClusterIP-only")
    pods = kube.json("get", "pods", "-n", namespace, "-l", selector, "-o", "json")
    expected_image = f"{image_repository}:{image_tag}"
    ready = 0
    for pod in pods.get("items") or []:
        status = pod.get("status") or {}
        conditions = status.get("conditions") or []
        containers = (pod.get("spec") or {}).get("containers") or []
        if (
            status.get("phase") == "Running"
            and any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions)
            and any(item.get("name") == "zot" and item.get("image") == expected_image for item in containers)
        ):
            ready += 1
    if ready != 1:
        die("scratch Zot is not Ready on the exact production image pin")
    return (services[0].get("metadata") or {}).get("name", "")


def assert_empty_registry(registry: Registry) -> None:
    repositories = registry.paginate(
        "/v2/_catalog?n=1000", "", "repositories", 0, "scratch pre-import catalog"
    )
    if repositories:
        die(
            "scratch registry is not empty before import; repositories present: "
            + ", ".join(sorted(repositories))
        )
    print("SCRATCH_PREIMPORT_REPOSITORIES=0")


def pull_release_members(registry: Registry, release_set: dict[str, Any]) -> None:
    """Pull every member and its child/config/layer/blob closure by immutable digest."""
    members = release_set["members"]
    manifest_sizes: dict[tuple[str, str], int] = {}
    blob_sizes: dict[tuple[str, str], int] = {}

    def assert_size(descriptor: dict[str, Any], actual: int, label: str) -> None:
        if "size" not in descriptor:
            return
        declared = descriptor["size"]
        if type(declared) is not int or declared < 0:
            die(f"{label} has an invalid declared size")
        if declared != actual:
            die(f"{label} declared size does not match scratch bytes")

    def pull_blob(repository: str, descriptor: dict[str, Any], owner: str) -> None:
        digest = descriptor.get("digest")
        if not DIGEST_RE.fullmatch(str(digest)):
            die(f"release member {owner} has an invalid blob descriptor")
        key = (repository, digest)
        if key not in blob_sizes:
            _, payload, _ = registry.request("GET", f"/v2/{repository}/blobs/{digest}")
            pulled = f"sha256:{hashlib.sha256(payload).hexdigest()}"
            if pulled != digest:
                die(
                    f"pulled release member {owner} blob hashes to {pulled}, expected {digest}"
                )
            blob_sizes[key] = len(payload)
        assert_size(descriptor, blob_sizes[key], f"release member {owner} blob {digest}")

    def pull_manifest(
        repository: str,
        digest: str,
        owner: str,
        descriptor: dict[str, Any] | None = None,
    ) -> None:
        key = (repository, digest)
        if key not in manifest_sizes:
            _, payload, _ = registry.request(
                "GET",
                f"/v2/{repository}/manifests/{digest}",
                headers={"Accept": MANIFEST_ACCEPT},
            )
            pulled = f"sha256:{hashlib.sha256(payload).hexdigest()}"
            if pulled != digest:
                die(
                    f"pulled release member {owner} manifest hashes to {pulled}, "
                    f"expected {digest}"
                )
            try:
                document = json.loads(payload)
            except json.JSONDecodeError as exc:
                die(f"pulled release member {owner} manifest is not valid JSON: {exc}")
            if not isinstance(document, dict) or document.get("schemaVersion") != 2:
                die(f"pulled release member {owner} manifest is not schemaVersion 2 JSON")
            manifest_sizes[key] = len(payload)
            children = document.get("manifests", [])
            if not isinstance(children, list):
                die(f"pulled release member {owner} field manifests is not a list")
            for child in children:
                child_digest = child.get("digest") if isinstance(child, dict) else None
                if not DIGEST_RE.fullmatch(str(child_digest)):
                    die(f"pulled release member {owner} has an invalid child manifest")
                pull_manifest(repository, child_digest, owner, child)
            descriptors: list[Any] = []
            if "config" in document:
                descriptors.append(document["config"])
            descriptors.extend(document.get("layers", []))
            descriptors.extend(document.get("blobs", []))
            for blob_descriptor in descriptors:
                if not isinstance(blob_descriptor, dict):
                    die(f"pulled release member {owner} has an invalid blob descriptor")
                pull_blob(repository, blob_descriptor, owner)
        if descriptor is not None:
            assert_size(
                descriptor,
                manifest_sizes[key],
                f"release member {owner} child manifest {digest}",
            )

    for member in members:
        pull_manifest(member["repository"], member["digest"], member["name"])
        print(
            f"PULLED_RELEASE_MEMBER={member['name']} KIND={member['kind']} "
            f"ROLE={member['role']} REFERENCE={member['repository']}@{member['digest']}"
        )
    print(
        f"PULLED_RELEASE_MEMBERS={len(members)} "
        f"MEMBER_CLOSURE_MANIFESTS={len(manifest_sizes)} "
        f"MEMBER_DESCRIPTOR_BLOBS={len(blob_sizes)} ALL_EXACT_RECORDED_DIGESTS=yes"
    )


def pull_referrer_content(registry: Registry, inventory: dict[str, Any]) -> None:
    """Pull/hash every discovered referrer manifest and its descriptor/child closure."""
    manifest_sizes: dict[tuple[str, str], int] = {}
    blob_sizes: dict[tuple[str, str], int] = {}

    def assert_size(descriptor: dict[str, Any], actual: int, label: str) -> None:
        if "size" in descriptor and (
            type(descriptor["size"]) is not int or descriptor["size"] != actual
        ):
            die(f"{label} declared size does not match scratch bytes")

    def pull_blob(repository: str, descriptor: dict[str, Any], owner: str) -> None:
        digest = descriptor.get("digest")
        if not DIGEST_RE.fullmatch(str(digest)):
            die(f"referrer {owner} has an invalid blob descriptor")
        key = (repository, digest)
        if key not in blob_sizes:
            _, payload, _ = registry.request("GET", f"/v2/{repository}/blobs/{digest}")
            pulled = f"sha256:{hashlib.sha256(payload).hexdigest()}"
            if pulled != digest:
                die(f"pulled referrer {owner} blob hashes to {pulled}, expected {digest}")
            blob_sizes[key] = len(payload)
        assert_size(descriptor, blob_sizes[key], f"referrer {owner} blob {digest}")

    def pull_manifest(
        repository: str,
        digest: str,
        descriptor: dict[str, Any] | None = None,
    ) -> None:
        key = (repository, digest)
        if key not in manifest_sizes:
            _, payload, _ = registry.request(
                "GET",
                f"/v2/{repository}/manifests/{digest}",
                headers={"Accept": MANIFEST_ACCEPT},
            )
            pulled = f"sha256:{hashlib.sha256(payload).hexdigest()}"
            if pulled != digest:
                die(f"pulled referrer manifest hashes to {pulled}, expected {digest}")
            try:
                document = json.loads(payload)
            except json.JSONDecodeError as exc:
                die(f"pulled referrer {repository}@{digest} is not valid JSON: {exc}")
            if not isinstance(document, dict) or document.get("schemaVersion") != 2:
                die(f"pulled referrer {repository}@{digest} is not schemaVersion 2 JSON")
            manifest_sizes[key] = len(payload)
            children = document.get("manifests", [])
            if not isinstance(children, list):
                die(f"pulled referrer {repository}@{digest} field manifests is not a list")
            for child in children:
                child_digest = child.get("digest") if isinstance(child, dict) else None
                if not DIGEST_RE.fullmatch(str(child_digest)):
                    die(f"pulled referrer {repository}@{digest} has an invalid child manifest")
                pull_manifest(repository, child_digest, child)
            descriptors: list[Any] = []
            if "config" in document:
                descriptors.append(document["config"])
            descriptors.extend(document.get("layers", []))
            descriptors.extend(document.get("blobs", []))
            for blob_descriptor in descriptors:
                if not isinstance(blob_descriptor, dict):
                    die(f"pulled referrer {repository}@{digest} has an invalid blob descriptor")
                pull_blob(repository, blob_descriptor, digest)
        if descriptor is not None:
            assert_size(
                descriptor,
                manifest_sizes[key],
                f"referrer child manifest {repository}@{digest}",
            )

    for edge in inventory["referrerEdges"]:
        pull_manifest(edge["repository"], edge["referrer"])
    print(
        f"PULLED_REFERRER_MANIFESTS={len(manifest_sizes)} "
        f"REFERRER_DESCRIPTOR_BLOBS={len(blob_sizes)} ALL_EXACT_RECORDED_DIGESTS=yes"
    )


def restore_content(registry: Registry, layout: Path, inventory: dict[str, Any], work: Path) -> None:
    order = restore_order(layout, inventory)
    validate_restore_order(layout, order)
    requirements = repository_blob_requirements(layout, inventory)
    for repository, digests in sorted(requirements.items()):
        for digest in sorted(digests):
            blob = layout / "blobs" / "sha256" / digest.removeprefix("sha256:")
            if not blob.is_file() or blob.is_symlink():
                die(f"manifest-referenced OCI blob is absent: {repository}@{digest}")
            put_blob(registry, repository, blob, digest)

    for repository, digest, media_type in order:
        manifest = layout / "blobs" / "sha256" / digest.removeprefix("sha256:")
        synthetic_tag = f"ok138-restore-{digest.removeprefix('sha256:')}"
        put_manifest(registry, repository, synthetic_tag, manifest, media_type)
        _, payload, _ = registry.request(
            "GET",
            f"/v2/{repository}/manifests/{synthetic_tag}",
            headers={"Accept": MANIFEST_ACCEPT},
        )
        if f"sha256:{hashlib.sha256(payload).hexdigest()}" != digest:
            die(f"scratch changed restored manifest bytes for {repository}@{digest}")

    for item in inventory["references"]:
        manifest = layout / "blobs" / "sha256" / item["digest"].removeprefix("sha256:")
        document = load_manifest(manifest, item["repository"], item["digest"])
        print(f"restoring {item['repository']}:{item['tag']} at {item['digest']}")
        put_manifest(
            registry, item["repository"], item["tag"], manifest, manifest_media_type(document)
        )
    for edge in inventory["referrerEdges"]:
        _, payload, _ = registry.request(
            "GET",
            f"/v2/{edge['repository']}/referrers/{edge['subject']}",
            headers={"Accept": INDEX_MEDIA_TYPE},
        )
        try:
            referrers = json.loads(payload).get("manifests") or []
        except (json.JSONDecodeError, AttributeError):
            die(f"restored Referrers API lookup failed for {edge['repository']}@{edge['subject']}")
        if sum(item.get("digest") == edge["referrer"] for item in referrers) != 1:
            die(
                f"restored Referrers API omitted {edge['referrer']} for "
                f"{edge['repository']}@{edge['subject']}"
            )
    print(f"restored referrer relationships: {len(inventory['referrerEdges'])}")
    pull_referrer_content(registry, inventory)

    if inventory.get("releaseSet") is not None:
        pull_release_members(registry, inventory["releaseSet"])
    else:
        representative = inventory["representativePreBackup"]
        _, payload, _ = registry.request(
            "GET",
            f"/v2/{representative['repository']}/manifests/{representative['digest']}",
            headers={"Accept": MANIFEST_ACCEPT},
        )
        pulled = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if pulled != representative["digest"]:
            die(
                f"pulled representative manifest hashes to {pulled}, expected "
                f"{representative['digest']}"
            )
        print(
            f"CURL_PULL=http://127.0.0.1:{registry.port}/v2/{representative['repository']}"
            f"/manifests/{representative['digest']} HTTP 200"
        )
        print(
            f"PULLED_MANIFEST_SHA256={pulled} "
            f"EXACT_RECORDED_DIGEST={representative['digest']}"
        )


def command_restore(args: argparse.Namespace) -> int:
    if args.approve is None:
        args.approve = env_choice("APPROVE_RESTORE_DRILL")
    if args.retain_scratch is None:
        args.retain_scratch = env_choice("RETAIN_SCRATCH")
    if args.verify_only is None:
        args.verify_only = env_choice("VERIFY_ONLY")
    artifact = Path(args.artifact)
    manifest = Path(args.manifest)
    work = Path(tempfile.mkdtemp(prefix="zot-restore-drill."))
    os.chmod(work, 0o700)
    kube: Kube | None = None
    namespace_created = False
    port_forward: PortForward | None = None
    try:
        print(f"work dir: {work}")
        inventory, layout, _ = load_and_verify(artifact, manifest, work)
        if args.verify_only:
            print(
                "RESULT: PASS — detached size/SHA-256 and every OCI blob digest verified "
                "without cluster mutation"
            )
            return 0
        if args.namespace != "zot":
            die(f"live registry namespace must be exactly zot, got: {args.namespace}")
        if args.release != "zot":
            die(f"live registry release must be exactly zot, got: {args.release}")
        validate_scratch_identity(args.scratch_namespace, args.scratch_release)
        print(f"scratch target: {args.scratch_namespace}/{args.scratch_release}")
        if not args.kubeconfig:
            die("KUBECONFIG is required for restore-drill")
        if not args.approve:
            gate(
                "restore-drill creates and normally deletes an isolated registry namespace.\n"
                "       Review the artifact and sequence; rerun with APPROVE_RESTORE_DRILL=yes."
            )
        if not sys.stdin.isatty():
            gate("restore-drill must be run attended from a terminal")
        if not args.chart_dir:
            die("CHART_DIR is required")
        if not args.values_file:
            die("VALUES_FILE is required")
        require_commands(args.kubectl, args.helm)
        scratch_values = derive_scratch_values(Path(args.values_file), Path(args.chart_dir))
        kube = Kube(kubectl=args.kubectl, helm=args.helm, kubeconfig=args.kubeconfig)
        assert_live_restore_boundary(kube, args.namespace, args.release)
        scratch_absent(kube, args.scratch_namespace, args.scratch_release)
        scratch_file = work / "scratch-values.json"
        write_json_new(scratch_file, scratch_values)
        kube.run("create", "namespace", args.scratch_namespace)
        namespace_created = True
        kube.run(
            "install", args.scratch_release, args.chart_dir,
            "-n", args.scratch_namespace, "-f", str(scratch_file),
            "--wait", "--timeout", "3m", binary=kube.helm,
        )
        image = scratch_values["image"]
        service = assert_scratch_shape(
            kube, args.scratch_namespace, args.scratch_release, image["repository"], image["tag"]
        )
        port_forward = PortForward(
            kube,
            args.scratch_namespace,
            f"service/{service}",
            5000,
            work / "scratch-port-forward.log",
        )
        tunnel = port_forward.__enter__()
        assert tunnel.port is not None
        registry = Registry(
            hostname="127.0.0.1", port=tunnel.port, insecure_plain_http=True
        )
        registry.request("GET", "/v2/")
        assert_empty_registry(registry)
        print(
            f"restore destination: locally constructed kubectl port-forward at "
            f"127.0.0.1:{tunnel.port} only"
        )
        restore_content(registry, layout, inventory, work)
        port_forward.__exit__(None, None, None)
        port_forward = None
        if not args.retain_scratch:
            if not teardown_scratch(kube, args.scratch_namespace, args.scratch_release):
                die("default scratch cleanup could not be proven")
            namespace_created = False
        if inventory.get("releaseSet") is not None:
            print(
                "RESULT: PASS — OCI release export restored and every declared member "
                "reproduced byte-for-byte by immutable digest"
            )
        else:
            print(
                "RESULT: PASS — OCI export restored and representative manifest reproduced "
                "byte-for-byte by immutable digest"
            )
            print(
                f"WARNING: the backup discovery limitation remains: "
                f"{inventory['discoveryLimitation']}"
            )
            print(f"WARNING: the backup scope limitation remains: {inventory['scopeLimitation']}")
        print(f"WARNING: the backup identity limitation remains: {inventory['identityLimitation']}")
        return 0
    finally:
        if port_forward is not None:
            port_forward.__exit__(None, None, None)
        if namespace_created and kube is not None:
            if args.retain_scratch:
                print(
                    f"SCRATCH RETAINED: namespace={args.scratch_namespace} "
                    f"release={args.scratch_release}"
                )
                print(
                    "RISK: the retained registry is authless HTTP and reachable to in-cluster "
                    "clients through its ClusterIP."
                )
                print(
                    f"CLEANUP: {args.helm} uninstall {args.scratch_release} -n "
                    f"{args.scratch_namespace} --kubeconfig {args.kubeconfig} && {args.kubectl} "
                    f"--kubeconfig {args.kubeconfig} delete namespace {args.scratch_namespace}"
                )
            elif not teardown_scratch(kube, args.scratch_namespace, args.scratch_release):
                print("FAIL: scratch cleanup could not be proven", file=sys.stderr)
        print(f"work dir RETAINED (mode 700; contains no registry credential): {work}")
        print("WARNING: delete the retained work dir manually after reviewing this result.")


# --------------------------------------------------------------------------------------
# verify -- pure local, no cluster access at all
# --------------------------------------------------------------------------------------


def load_and_verify(artifact: Path, manifest: Path, work: Path) -> tuple[dict[str, Any], Path, int]:
    for path in (artifact, manifest):
        if not path.is_file() or path.stat().st_size == 0:
            die(f"file is absent, empty or unreadable: {path}")
    document = read_json(manifest, "detached integrity manifest")
    validate_integrity_document(document)

    recorded = document["artifact"]
    if recorded["basename"] != artifact.name:
        die("artifact basename does not match detached manifest")
    if recorded["size"] != artifact.stat().st_size:
        die("artifact size does not match detached manifest")
    if recorded["sha256"] != sha256_file(artifact):
        die("artifact checksum does not match detached manifest")

    extract_dir = work / "extracted"
    extract_dir.mkdir(mode=0o700)
    safe_extract(artifact, extract_dir)

    inventory_file = extract_dir / INVENTORY_NAME
    if not inventory_file.is_file() or inventory_file.is_symlink():
        die("embedded backup inventory is absent")
    if inventory_file.stat().st_size != document["inventory"]["size"]:
        die("embedded backup inventory size does not match detached manifest")
    if sha256_file(inventory_file) != document["inventory"]["sha256"]:
        die("embedded backup inventory checksum does not match detached manifest")

    inventory = read_json(inventory_file, "embedded backup inventory")
    validate_inventory(inventory)
    layout = extract_dir / LAYOUT_DIRECTORY
    blob_count = verify_layout(layout, inventory)
    print(f"pre-verification: detached checksum/size and {blob_count} OCI blobs PASS")
    return inventory, layout, blob_count


def command_verify(args: argparse.Namespace) -> int:
    work = Path(tempfile.mkdtemp(prefix="zotctl-verify."))
    os.chmod(work, 0o700)
    try:
        inventory, _layout, _count = load_and_verify(
            Path(args.artifact), Path(args.manifest), work
        )
        if inventory.get("releaseSet") is not None:
            print(
                "RESULT: PASS — detached size/SHA-256, every OCI blob digest and the "
                "complete release descriptor/referrer closure verified without cluster "
                "or source-registry access"
            )
        else:
            print(
                "RESULT: PASS — detached size/SHA-256 and every OCI blob digest verified "
                "without cluster mutation"
            )
        return 0
    finally:
        print(f"work dir RETAINED (mode 700; contains no registry credential): {work}")


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def registry_defaults(path: Path | None = None) -> dict[str, str]:
    """Resolve how to reach the registry by running the one implementation of that logic.

    registry-defaults.sh discovers the address rather than carrying it: an explicit override
    first, then DNS for the registry hostname (which is what OK-57 will provide), then the
    LoadBalancer address the infrastructure cluster publishes for this cluster's ingress.

    This executes that file instead of re-deriving the ladder in Python. Scraping it with a
    regex was fine while it held a literal default; parsing a shell script's control flow to
    avoid running it would be the wrong trade, and a second implementation is exactly the
    duplication this file was introduced to remove.
    """
    source = path or Path(__file__).with_name("registry-defaults.sh")
    if not source.is_file():
        die(f"registry defaults file is absent: {source}")
    result = subprocess.run(
        ["bash", "-c", f'. "$1"; printf "%s\\n%s\\n" "$REGISTRY_HOST" "$REGISTRY_LB"', "_", str(source)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        die(result.stderr.strip() or "registry defaults could not resolve a registry address")
    lines = result.stdout.splitlines()
    if len(lines) < 2 or not lines[0] or not lines[1]:
        die("registry defaults did not yield both a hostname and an address")
    return {"REGISTRY_HOST": lines[0], "REGISTRY_LB": lines[1]}


def env_choice(name: str, default: str = "no") -> bool:
    value = os.environ.get(name, default)
    if value not in ("yes", "no"):
        die(f"{name} must be yes or no")
    return value == "yes"


def default_scratch_namespace() -> str:
    supplied = os.environ.get("SCRATCH_NAMESPACE", "")
    if supplied:
        return supplied
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"zot-restore-drill-{stamp}-{os.getpid()}-{os.urandom(3).hex()}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    export_options = argparse.ArgumentParser(add_help=False)
    export_options.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"))
    export_options.add_argument("--kubeconfig", default=os.environ.get("KUBECONFIG", ""))
    export_options.add_argument("--namespace", default=os.environ.get("NAMESPACE", "zot"))
    export_options.add_argument("--release", default=os.environ.get("RELEASE", "zot"))
    export_options.add_argument(
        "--machine-secret", default=os.environ.get("MACHINE_SECRET", "zot-machine-identities")
    )
    export_options.add_argument(
        "--conformance-secret",
        default=os.environ.get("CONFORMANCE_SECRET", "zot-conformance-identities"),
    )
    export_options.add_argument("--tls-secret", default=os.environ.get("TLS_SECRET", "zot-server-tls"))
    export_options.add_argument("--registry-host", default=os.environ.get("REGISTRY_HOST"))
    export_options.add_argument("--registry-lb", default=os.environ.get("REGISTRY_LB"))
    export_options.add_argument("--backup-dir", default=os.environ.get("BACKUP_DIR", ""))
    export_options.add_argument(
        "--keycloak-host",
        default=os.environ.get("KEYCLOAK_HOST", "keycloak.ok-shared.internal"),
    )
    export_options.add_argument("--page-size", type=int, default=None)

    backup = sub.add_parser(
        "backup",
        parents=[export_options],
        help="export every discoverable tagged manifest and recursive referrer",
    )
    backup.set_defaults(func=command_backup, release_set=None)

    release_export = sub.add_parser(
        "release-export",
        parents=[export_options],
        help="export declared release members, descriptor closure and recursive referrers",
    )
    release_export.add_argument("release_set", help="versioned release-set JSON input")
    release_export.set_defaults(func=command_backup)

    verify = sub.add_parser("verify", help="verify a backup artifact without any cluster access")
    verify.add_argument("artifact")
    verify.add_argument("manifest")
    verify.set_defaults(func=command_verify)

    restore = sub.add_parser(
        "restore-drill", help="restore into an isolated scratch Zot and prove immutable bytes"
    )
    restore.add_argument("artifact")
    restore.add_argument("manifest")
    restore.add_argument("--kubectl", default=os.environ.get("KUBECTL", "kubectl"))
    restore.add_argument("--helm", default=os.environ.get("HELM", "helm"))
    restore.add_argument("--kubeconfig", default=os.environ.get("KUBECONFIG", ""))
    restore.add_argument("--chart-dir", default=os.environ.get("CHART_DIR", ""))
    restore.add_argument("--values-file", default=os.environ.get("VALUES_FILE", ""))
    restore.add_argument("--namespace", default=os.environ.get("NAMESPACE", "zot"))
    restore.add_argument("--release", default=os.environ.get("RELEASE", "zot"))
    restore.add_argument(
        "--scratch-namespace", default=default_scratch_namespace()
    )
    restore.add_argument(
        "--scratch-release", default=os.environ.get("SCRATCH_RELEASE", SCRATCH_RELEASE)
    )
    restore.add_argument(
        "--approve", action="store_true", default=None
    )
    restore.add_argument(
        "--retain-scratch", action="store_true", default=None
    )
    restore.add_argument("--verify-only", action="store_true", default=None)
    restore.set_defaults(func=command_restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except Gate as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Fail as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
