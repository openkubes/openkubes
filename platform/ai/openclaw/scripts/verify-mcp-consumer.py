#!/usr/bin/env python3
"""Render the OpenClaw chart and enforce the ADR-021 consumer boundary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path


HERE = Path(__file__).resolve().parent
CHART = HERE.parent / "charts" / "openclaw"
MAKEFILE = HERE.parent / "Makefile"
EXPECTED_TOOLS = {
    "get_platform_health",
    "investigate_workload",
    "collect_diagnostic_evidence",
}
EXPECTED_CONTRACT_VERSION = "1.1.0"
TEST_MCP_URL = "http://contract-adapter.test.svc:8080/mcp"


def fail(message: str) -> None:
    raise AssertionError(message)


def render_chart() -> str:
    subprocess.run(
        ["helm", "lint", str(CHART), "--set-string", "gateway.token=test-only"],
        check=True,
    )
    result = subprocess.run(
        [
            "helm",
            "template",
            "openclaw",
            str(CHART),
            "--namespace",
            "openclaw",
            "--set-string",
            "gateway.token=test-only",
            "--set-string",
            f"diagnostics.mcp.url={TEST_MCP_URL}",
            "--set-string",
            f"diagnostics.contractVersion={EXPECTED_CONTRACT_VERSION}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def configmap_document(rendered: str) -> str:
    marker = "# Source: openclaw/templates/configmap.yaml"
    for document in rendered.split("---"):
        if marker in document:
            return document
    fail("rendered ConfigMap not found")


def literal_block(document: str, key: str) -> str:
    match = re.search(
        rf"^  {re.escape(key)}: \|\n(?P<body>(?:    .*\n|\n)*)",
        document,
        flags=re.MULTILINE,
    )
    if not match:
        fail(f"ConfigMap literal block {key!r} not found")
    return textwrap.dedent(match.group("body")).rstrip()


def verify() -> None:
    rendered = render_chart()

    for forbidden_kind in ("Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"):
        if re.search(rf"^kind: {forbidden_kind}$", rendered, flags=re.MULTILINE):
            fail(f"consumer chart renders forbidden Kubernetes RBAC: {forbidden_kind}")
    if rendered.count("automountServiceAccountToken: false") < 2:
        fail("ServiceAccount token automount must be disabled on Pod and ServiceAccount")
    if "ghcr.io/openclaw/openclaw:2026.7.1" not in rendered:
        fail("consumer does not render the credential-less upstream image")
    if "openclaw-kubectl" in rendered or "KUBECONFIG" in rendered:
        fail("rendered consumer retains a direct Kubernetes client path")

    config_document = configmap_document(rendered)
    config = json.loads(literal_block(config_document, "openclaw.json"))
    servers = config.get("mcp", {}).get("servers", {})
    if set(servers) != {"platform-diagnostics"}:
        fail("diagnostics MCP registration is missing or exposes extra servers")
    diagnostics = servers["platform-diagnostics"]
    if diagnostics.get("url") != TEST_MCP_URL:
        fail("diagnostics MCP URL is not sourced from chart values")
    if diagnostics.get("transport") != "streamable-http":
        fail("diagnostics MCP transport must be streamable-http")
    included_tools = set(diagnostics.get("toolFilter", {}).get("include", []))
    if included_tools != EXPECTED_TOOLS:
        fail("diagnostics MCP tool filter differs from the three contract functions")
    if "exec" not in config.get("tools", {}).get("deny", []):
        fail("Exec must remain denied for the MCP-only consumer")

    instructions = literal_block(config_document, "AGENTS.md")
    for required_text in (*EXPECTED_TOOLS, "Source: platform-diagnostics/", "Jira", "GitHub"):
        if required_text not in instructions:
            fail(f"consumer instructions omit required text: {required_text}")
    if "kubectl commands" not in instructions:
        fail("consumer instructions do not prohibit the legacy kubectl path")
    if f"Contract version: {EXPECTED_CONTRACT_VERSION}." not in instructions:
        fail("consumer instructions are not pinned to the normative contract version")

    operator_path = MAKEFILE.read_text()
    if "install: $(TOKEN_FILE) prepare-diagnostics-consumer" not in operator_path:
        fail("install does not prepare the namespace for restricted adapter ingress")
    if "openkubes.io/diagnostics-consumer=true --overwrite" not in operator_path:
        fail("consumer namespace label does not match the adapter ingress contract")

    print("PASS: chart renders no consumer RBAC and disables ServiceAccount token automount")
    print("PASS: upstream image and denied Exec remove the direct Kubernetes client path")
    print("PASS: OpenClaw registers only the three diagnostics tools through the MCP adapter")
    print(f"PASS: consumer expectations are pinned to contract {EXPECTED_CONTRACT_VERSION}")
    print("PASS: install prepares the namespace for restricted adapter ingress")
    print("PASS: diagnostics output preserves provenance and supports sanitized workflow handoff")


def main() -> int:
    try:
        verify()
    except (AssertionError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
