#!/usr/bin/env python3
"""
Tests for the OK-129 access profile renderer.

Static only — no cluster, no network. Every test asserts a property of the
*generated* objects, because those are what the API server enforces. Exit
non-zero on any failure (same convention as ok-cluster/tests/*_test.py).

Run:  python3 render_access_test.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("render_access", HERE / "render-access.py")
assert _spec and _spec.loader
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


def render(config: dict) -> dict:
    """Render a config dict and return {relative path: parsed content}."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config_path = tmp_path / "access-config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        out = tmp_path / "out"
        cfg = ra.load_config(config_path)
        ra.write_outputs(cfg, out, config_path, "0.2.1")

        result: dict = {}
        for path in sorted(out.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(out))
                text = path.read_text(encoding="utf-8")
                if path.suffix == ".yaml":
                    result[rel] = [d for d in yaml.safe_load_all(text) if d]
                else:
                    result[rel] = text
        return result


def expect_config_error(config: dict, needle: str, label: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "access-config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        try:
            ra.load_config(config_path)
        except ra.ConfigError as exc:
            check(needle.lower() in str(exc).lower(), f"{label} → refused ({exc})")
            return
    check(False, f"{label} → should have been refused but was accepted")


def base(mode: str = "read-write", **write_overrides) -> dict:
    write = {
        "scope": "namespaces",
        "namespaces": ["kagent-lab"],
        "resources": ["configmaps", "deployments"],
        "requireApproval": True,
        "toolServer": {"namespace": "kagent-write", "releaseName": "kagent-write-tools"},
        "tools": ["k8s_apply_manifest", "k8s_patch_resource", "k8s_delete_resource"],
    }
    write.update(write_overrides)
    return {
        "kind": "KagentAccessProfile",
        "mode": mode,
        "install": {"namespace": "kagent"},
        "read": {"scope": "cluster", "secrets": False},
        "write": write,
    }


def all_rules(objects: list[dict]) -> list[dict]:
    return [rule for obj in objects if obj.get("rules") for rule in obj["rules"]]


# --------------------------------------------------------------------------- #


def test_read_only_generates_no_write_path() -> None:
    print("\nread-only mode")
    out = render(base(mode="read-only"))
    check("manifests/20-rbac.yaml" not in out, "no RBAC manifest is generated")
    check("manifests/40-agent.yaml" not in out, "no write Agent is generated")
    check("tools-values.yaml" not in out, "no write tool-server values are generated")
    check("values-access.yaml" in out, "the read-path Helm fragment is still generated")

    values = out["values-access.yaml"][0]["kagent-tools"]
    check(values["rbac"]["readOnly"] is True, "built-in tool server stays readOnly")
    check(values["rbac"]["allowSecrets"] is False, "built-in tool server denies Secrets")


def test_namespace_scope() -> None:
    print("\nnamespace-scoped write")
    out = render(base())
    rbac = out["manifests/20-rbac.yaml"]
    kinds = sorted({obj["kind"] for obj in rbac})
    check(kinds == ["Role", "RoleBinding"], f"only namespaced RBAC is emitted (got {kinds})")
    check(
        all(obj["metadata"]["namespace"] == "kagent-lab" for obj in rbac),
        "every RBAC object lands in the configured namespace",
    )

    binding = next(o for o in rbac if o["kind"] == "RoleBinding")
    subject = binding["subjects"][0]
    check(
        subject["namespace"] == "kagent-write",
        "the bound ServiceAccount lives outside the write target namespace",
    )

    ts = out["manifests/30-tool-server.yaml"][0]
    check(
        ts["spec"]["url"] == "http://kagent-write-tools.kagent-write:8084/mcp",
        "the RemoteMCPServer points at the scoped tool server",
    )


def test_multiple_namespaces_get_one_role_each() -> None:
    print("\nmultiple write namespaces")
    out = render(base(namespaces=["team-a", "team-b", "kagent-lab"]))
    rbac = out["manifests/20-rbac.yaml"]
    roles = [o for o in rbac if o["kind"] == "Role"]
    bindings = [o for o in rbac if o["kind"] == "RoleBinding"]
    check(len(roles) == 3, f"one Role per namespace (got {len(roles)})")
    check(len(bindings) == 3, f"one RoleBinding per namespace (got {len(bindings)})")
    check(
        sorted(o["metadata"]["namespace"] for o in roles) == ["kagent-lab", "team-a", "team-b"],
        "Roles cover exactly the configured namespaces",
    )
    check(
        not any(o["kind"].startswith("Cluster") for o in rbac),
        "no cluster-scoped RBAC leaks into a namespaced profile",
    )


def test_cluster_scope() -> None:
    print("\ncluster-scoped write")
    out = render(base(scope="cluster", namespaces=[]))
    rbac = out["manifests/20-rbac.yaml"]
    kinds = sorted({obj["kind"] for obj in rbac})
    check(kinds == ["ClusterRole", "ClusterRoleBinding"], f"cluster RBAC is emitted (got {kinds})")
    agent = out["manifests/40-agent.yaml"][0]
    check(
        agent["metadata"]["labels"]["openkubes.io/access-scope"] == "cluster",
        "the Agent is labelled with its access scope",
    )


def test_no_rule_ever_grants_secrets_or_escalation() -> None:
    print("\nforbidden resources never appear in generated rules")
    for config in (base(), base(scope="cluster", namespaces=[]), base(resources=list(ra.WRITABLE_RESOURCES))):
        out = render(config)
        granted = {
            resource
            for rule in all_rules(out["manifests/20-rbac.yaml"])
            for resource in rule["resources"]
        }
        leaked = granted & ra.FORBIDDEN_RESOURCES
        check(not leaked, f"no forbidden resource in generated rules (leaked: {sorted(leaked)})")


def test_require_approval_covers_every_write_tool() -> None:
    print("\napproval gate")
    out = render(base())
    agent = out["manifests/40-agent.yaml"][0]
    write_tool = next(
        t["mcpServer"]
        for t in agent["spec"]["declarative"]["tools"]
        if t["mcpServer"]["name"] == "kagent-write-tools"
    )
    check(
        sorted(write_tool["requireApproval"]) == sorted(write_tool["toolNames"]),
        "every exposed write tool is in requireApproval",
    )
    read_tool = next(
        t["mcpServer"]
        for t in agent["spec"]["declarative"]["tools"]
        if t["mcpServer"]["name"] == "kagent-tool-server"
    )
    check(
        "requireApproval" not in read_tool,
        "read tools are not gated",
    )


def test_ungated_namespaced_is_allowed_and_marked() -> None:
    print("\nungated write, namespaced")
    out = render(base(requireApproval=False))
    agent = out["manifests/40-agent.yaml"][0]
    write_tool = next(
        t["mcpServer"]
        for t in agent["spec"]["declarative"]["tools"]
        if t["mcpServer"]["name"] == "kagent-write-tools"
    )
    check("requireApproval" not in write_tool, "no approval gate is rendered")
    check("UNGATED" in agent["spec"]["description"], "the Agent description says UNGATED")
    check("**NO —" in out["SUMMARY.md"], "the summary flags the missing gate")


def test_stale_manifests_are_removed_on_downgrade() -> None:
    print("\nswitching read-write → read-only clears the write manifests")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out = tmp_path / "out"

        rw = tmp_path / "rw.yaml"
        rw.write_text(yaml.safe_dump(base()), encoding="utf-8")
        ra.write_outputs(ra.load_config(rw), out, rw, "0.2.1")
        check((out / "manifests" / "20-rbac.yaml").exists(), "write RBAC exists first")

        ro = tmp_path / "ro.yaml"
        ro.write_text(yaml.safe_dump(base(mode="read-only")), encoding="utf-8")
        ra.write_outputs(ra.load_config(ro), out, ro, "0.2.1")
        check(
            not (out / "manifests" / "20-rbac.yaml").exists(),
            "write RBAC is gone after re-render",
        )
        check(
            not (out / "tools-values.yaml").exists(),
            "write tool-server values are gone after re-render",
        )


def test_rejected_configs() -> None:
    print("\nconfigs that must be refused")
    cfg = base()
    cfg["read"]["secrets"] = True
    expect_config_error(cfg, "secret", "read.secrets=true")

    expect_config_error(base(resources=["secrets"]), "never be granted", "write secrets")
    expect_config_error(base(resources=["*"]), "never be granted", "write wildcard")
    expect_config_error(base(resources=["clusterroles"]), "never be granted", "write clusterroles")
    expect_config_error(base(resources=["nodes"]), "never be granted", "write nodes")
    expect_config_error(base(resources=["widgets"]), "not supported", "unknown resource")

    expect_config_error(base(scope="namespaces", namespaces=[]), "at least one namespace", "namespaced scope without namespaces")
    expect_config_error(base(scope="cluster", namespaces=["kagent-lab"]), "ambiguous", "both scopes at once")
    expect_config_error(base(namespaces=["kube-system"]), "protected", "protected namespace")
    expect_config_error(base(namespaces=["kagent"]), "install namespace", "install namespace as write target")
    expect_config_error(
        base(scope="cluster", namespaces=[], requireApproval=False),
        "refused",
        "ungated cluster-wide write",
    )
    expect_config_error(
        base(toolServer={"namespace": "kagent-lab", "releaseName": "x"}),
        "also a write target",
        "tool server inside its own write target",
    )
    expect_config_error(
        base(toolServer={"namespace": "kagent", "releaseName": "x"}),
        "install",
        "tool server in the install namespace",
    )

    bad_mode = base()
    bad_mode["mode"] = "write"
    expect_config_error(bad_mode, "read-only", "invalid mode")

    bad_read = base()
    bad_read["read"]["scope"] = "namespaces"
    expect_config_error(bad_read, "only 'cluster'", "unimplemented read scope")

    no_write = base()
    del no_write["write"]
    expect_config_error(no_write, "required", "read-write without a write block")


def test_example_config_is_valid() -> None:
    print("\nshipped example config")
    example = HERE / "access-config.example.yaml"
    check(example.exists(), "access-config.example.yaml exists")
    if example.exists():
        cfg = ra.load_config(example)
        check(cfg["mode"] == "read-only", "the example ships as read-only")


def main() -> int:
    print("OK-129 access renderer tests")
    test_read_only_generates_no_write_path()
    test_namespace_scope()
    test_multiple_namespaces_get_one_role_each()
    test_cluster_scope()
    test_no_rule_ever_grants_secrets_or_escalation()
    test_require_approval_covers_every_write_tool()
    test_ungated_namespaced_is_allowed_and_marked()
    test_stale_manifests_are_removed_on_downgrade()
    test_rejected_configs()
    test_example_config_is_valid()

    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
