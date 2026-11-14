"""Provider registry for the provider-neutral ADR-021 contract suite.

The suite itself must stay free of provider knowledge, so this module is the
single place that knows how to start a provider. The suite consumes the registry
and runs the *same* assertions against every entry. That is what turns contract
test 4 (backend swap) into a real check: a provider value that leaked into the
contract fails against the other provider instead of passing unnoticed. A suite
that only ever sees one provider cannot detect the thing it exists to detect.

Providers shipped with the repository:

* ``profile-b`` — the deterministic stub, spoken to over real HTTP on an
  ephemeral loopback port.
* ``profile-a`` — the kagent facade, spoken to in-process over ASGI. Its cluster
  and model calls are replaced by deterministic doubles; its identity check,
  request validation, response schema, error mapping and response assembly are
  the real implementation. The provider layer is what this suite tests, not the
  cluster behind it.

``DIAGNOSTICS_BASE_URL`` adds an external provider (a deployed facade, or any
other conformant implementation) without changing the suite.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from contextlib import ExitStack
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DIAGNOSTICS_ROOT = Path(__file__).resolve().parents[2]
STUB_ROOT = DIAGNOSTICS_ROOT / "profiles" / "stub"
FACADE_ROOT = DIAGNOSTICS_ROOT / "profiles" / "kagent" / "facade"

BEARER_TOKEN = os.getenv("DIAGNOSTICS_BEARER_TOKEN", "contract-suite-consumer")

Response = tuple[int, dict[str, str], bytes]


class Transport:
    """How the suite reaches one provider. The suite knows nothing else."""

    def send(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> Response:
        raise NotImplementedError

    def close(self) -> None:
        return None


class HttpTransport(Transport):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def send(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> Response:
        request = Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()


class LoopbackTransport(HttpTransport):
    """Real HTTP against an in-process server on an ephemeral port."""

    def __init__(self, handler: type) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._httpd.server_address
        super().__init__(f"http://{host}:{port}")

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


class AsgiTransport(Transport):
    """In-process ASGI. No uvicorn, no port, same request handling."""

    def __init__(self, app: Any, resources: ExitStack) -> None:
        from fastapi.testclient import TestClient

        self._resources = resources
        self._client = TestClient(app, raise_server_exceptions=False)

    def send(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> Response:
        response = self._client.post(path, content=json.dumps(body), headers=headers)
        return response.status_code, dict(response.headers), response.content

    def close(self) -> None:
        self._client.close()
        self._resources.close()


@dataclass(frozen=True)
class Provider:
    """One conformant implementation the suite can be pointed at."""

    key: str
    description: str
    rbac_path: Path
    start: Callable[[], Transport]
    metadata: dict[str, str] = field(default_factory=dict)


def _start_profile_b() -> Transport:
    if str(STUB_ROOT) not in sys.path:
        sys.path.insert(0, str(STUB_ROOT))
    from server import ProfileBHandler

    return LoopbackTransport(ProfileBHandler)


def _start_profile_a() -> Transport:
    """Start the facade with its cluster and model calls replaced.

    The doubles stand in for the *cluster*, not for the contract: routing,
    consumer-identity enforcement, input validation, response assembly, evidence
    identity and error mapping all run as deployed. Hypothesis-bearing
    investigation paths need a live agent and are covered by the facade's own
    tests; here the deterministic inventory path is used so that the same
    requests can be replayed against every provider.
    """
    os.environ.setdefault("DIAGNOSTICS_BEARER_TOKEN", BEARER_TOKEN)
    if str(FACADE_ROOT) not in sys.path:
        sys.path.insert(0, str(FACADE_ROOT))

    from unittest.mock import AsyncMock, patch

    import app as facade

    health_reply = json.dumps(
        {
            "clusters": [
                {
                    "cluster": "contract-test",
                    "status": "healthy",
                    "summary": "deterministic harness reply",
                    "signals": [],
                }
            ]
        }
    )
    collected = facade.EvidenceRef(
        id="ev-harness-events",
        type="events",
        source="k8s_get_events",
        status=facade.EvidenceStatus.available,
        uri="k8s://contract-test/namespaces/fixtures/workloads/checkout-api/events",
    )

    resources = ExitStack()
    resources.enter_context(
        patch.object(facade, "invoke_agent", AsyncMock(return_value=health_reply))
    )
    resources.enter_context(
        patch.object(facade, "_get_workload_pods", AsyncMock(return_value=[]))
    )
    resources.enter_context(
        patch.object(
            facade,
            "_collect_workload_observations",
            AsyncMock(return_value=({}, [collected])),
        )
    )
    return AsgiTransport(facade.app, resources)


def registry() -> list[Provider]:
    """Every provider this run will exercise, in a deterministic order."""
    providers = [
        Provider(
            key="profile-b",
            description="deterministic conformance stub over loopback HTTP",
            rbac_path=STUB_ROOT / "rbac.yaml",
            start=_start_profile_b,
        ),
        Provider(
            key="profile-a",
            description="kagent facade over in-process ASGI, cluster calls doubled",
            rbac_path=DIAGNOSTICS_ROOT / "profiles" / "kagent" / "rbac.yaml",
            start=_start_profile_a,
        ),
    ]

    external_url = os.getenv("DIAGNOSTICS_BASE_URL")
    if external_url:
        rbac_path = os.getenv("DIAGNOSTICS_RBAC_PATH")
        providers.append(
            Provider(
                key="external",
                description=f"external provider at {external_url}",
                rbac_path=Path(rbac_path) if rbac_path else STUB_ROOT / "rbac.yaml",
                start=lambda: HttpTransport(external_url),
            )
        )
    return providers
