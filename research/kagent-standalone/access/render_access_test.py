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
        "resources": ["configmaps"],
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


def test_only_evidenced_namespace_is_renderable() -> None:
    print("\nevidenced write namespace")
    out = render(base())
    rbac = out["manifests/20-rbac.yaml"]
    roles = [o for o in rbac if o["kind"] == "Role"]
    bindings = [o for o in rbac if o["kind"] == "RoleBinding"]
    check(len(roles) == 1, f"one Role for the evidenced namespace (got {len(roles)})")
    check(len(bindings) == 1, f"one RoleBinding for the evidenced namespace (got {len(bindings)})")
    check(
        [o["metadata"]["namespace"] for o in roles] == ["kagent-lab"],
        "the Role covers exactly kagent-lab",
    )
    expect_config_error(base(namespaces=["team-a"]), "exactly the evidenced target", "team-a target")
    expect_config_error(
        base(namespaces=["kagent-lab", "team-a"]),
        "exactly the evidenced target",
        "mixed evidenced and unevidenced targets",
    )


def test_v1_write_surface_is_configmaps_only() -> None:
    """RC2: the renderer may only produce the capability that was evidenced."""
    print("\nv1 write surface")
    check(
        sorted(ra.WRITABLE_RESOURCES) == ["configmaps"],
        f"only configmaps are renderable (got {sorted(ra.WRITABLE_RESOURCES)})",
    )
    check(
        ra.EVIDENCED_WRITE_NAMESPACES == {"kagent-lab"},
        "only kagent-lab is an evidenced write target",
    )
    check(
        not (set(ra.CANDIDATE_RESOURCES) & set(ra.WRITABLE_RESOURCES)),
        "no resource is both candidate work and renderable",
    )
    for candidate in ("deployments", "statefulsets", "daemonsets", "jobs", "cronjobs",
                      "services", "ingresses", "pods", "replicasets"):
        check(candidate in ra.CANDIDATE_RESOURCES, f"{candidate} is recorded as candidate work")

    out = render(base())
    rules = all_rules(out["manifests/20-rbac.yaml"])
    granted = {resource for rule in rules for resource in rule["resources"]}
    writable_verbs = set(ra.WRITE_VERBS)
    for rule in rules:
        if writable_verbs & set(rule["verbs"]):
            check(
                rule["resources"] == ["configmaps"],
                f"only configmaps carry write verbs (got {rule['resources']})",
            )

    # The summary claims "no permission of any kind on workload controllers".
    # Assert exactly that, including read verbs and the write-scope read context:
    # a stray `apps/replicasets` read would make the documented claim false.
    workload_kinds = {
        "deployments", "statefulsets", "daemonsets", "replicasets", "jobs", "cronjobs",
        "services", "ingresses",
    }
    leaked = granted & workload_kinds
    check(
        not leaked,
        f"no workload kind appears in any generated rule, read verbs included (leaked: {sorted(leaked)})",
    )
    check(
        not any("apps" in rule["apiGroups"] for rule in rules),
        "the write identity gets no rule in the apps apiGroup at all",
    )
    pod_rules = [
        rule for rule in rules
        if any(r == "pods" or r.startswith("pods/") for r in rule["resources"])
    ]
    check(
        all(not (writable_verbs & set(rule["verbs"])) for rule in pod_rules),
        "no Pod or Pod subresource carries a write verb",
    )


def test_no_cluster_scoped_object_is_renderable() -> None:
    """RC1: cluster write scope is gone, not merely discouraged."""
    print("\ncluster scope is removed")
    expect_config_error(
        base(scope="cluster", namespaces=[]),
        "refused",
        "write.scope=cluster",
    )
    expect_config_error(
        base(scope="cluster", namespaces=["kagent-lab"]),
        "refused",
        "write.scope=cluster with a namespace list",
    )
    out = render(base())
    for name, objects in out.items():
        if not name.endswith(".yaml") or not isinstance(objects, list):
            continue
        cluster_scoped = [o["kind"] for o in objects if str(o.get("kind", "")).startswith("Cluster")]
        check(not cluster_scoped, f"{name} contains no cluster-scoped object ({cluster_scoped})")


def _hand_built(**write_overrides) -> tuple[dict, dict]:
    """A write dict and cfg built directly, bypassing load_config entirely."""
    write = {
        "scope": "namespaces",
        "namespaces": ["kagent-lab"],
        "resources": ["configmaps"],
        "require_approval": True,
        "tool_server_namespace": "kagent-write",
        "tool_server_release": "kagent-write-tools",
        "tool_server_port": 8084,
        "tool_server_metrics_port": 8085,
        "tools": ["k8s_apply_manifest"],
        "agent_name": "cluster-operator-gated",
    }
    write.update(write_overrides)
    cfg = {
        "mode": "read-write",
        "install_namespace": "kagent",
        "read": {"scope": "cluster", "secrets": False, "tools": ["k8s_get_resources"]},
        "write": write,
    }
    return write, cfg


def _entry_points(cfg: dict, out_dir: Path | None = None) -> dict:
    """Every public renderer, so "guarded at every entry point" is checkable.

    `render_namespace` and `write_outputs` were once absent from this list — and
    `render_namespace` was, not coincidentally, the one renderer without a guard.
    A list that omits an entry point cannot falsify a claim about all of them.
    """
    points = {
        "render_read_values": lambda: ra.render_read_values(cfg),
        "render_namespace": lambda: ra.render_namespace(cfg),
        "render_rbac": lambda: ra.render_rbac(cfg),
        "render_tool_server": lambda: ra.render_tool_server(cfg),
        "render_agent": lambda: ra.render_agent(cfg),
        "render_tools_values": lambda: ra.render_tools_values(cfg, None),
        "render_summary": lambda: ra.render_summary(cfg, Path("access-config.yaml")),
        "render_profile_env": lambda: ra.render_profile_env(cfg),
    }
    if out_dir is not None:
        points["write_outputs"] = lambda: ra.write_outputs(
            cfg, out_dir, Path("access-config.yaml"), None
        )
    return points


def _expect_every_entry_point_refuses(
    write: dict, cfg: dict, label: str, out_dir: Path | None = None
) -> None:
    for name, call in _entry_points(cfg, out_dir).items():
        try:
            call()
        except ra.ConfigError:
            check(True, f"{name} raises ConfigError on {label}")
        except AssertionError:
            check(False, f"{name} guards with assert, not ConfigError (stripped by -O)")
        except Exception as exc:  # noqa: BLE001 - any other type is also a finding
            check(False, f"{name} raised {type(exc).__name__}, expected ConfigError")
        else:
            check(False, f"{name} produced output for {label}")


def test_no_renderer_entry_point_accepts_an_unevidenced_scope() -> None:
    """The v1 boundary must not depend on going through load_config.

    ``render-access.py`` is the *shared* renderer — any future consumer may import
    it. A restriction that lives only in ``load_config`` is a restriction only for
    callers that happen to use ``load_config``, which is the same gap as leaving it
    to each downstream consumer to re-implement.

    Both halves of the scope are covered: the kind of scope (no cluster) *and* the
    namespace set (only the evidenced one). ``profile.env`` publishes both as
    ``KAGENT_WRITE_SCOPE`` and ``KAGENT_WRITE_NAMESPACES``, and those are what an
    installer reads to decide what to verify — so neither may disagree with the
    rendered RBAC. ConfigError rather than assert, because `python3 -O` strips
    asserts.
    """
    print("\nno renderer entry point accepts an unevidenced scope")

    # Every invariant load_config refuses, asserted against the render path too.
    # The rule is deliberately blunt: nothing load_config refuses may be
    # renderable. Anything missing here is an asymmetry waiting to be found.
    cases: list[tuple[str, dict, dict]] = [
        ("cluster scope", {"scope": "cluster", "namespaces": []}, {}),
        ("an empty namespace list", {"namespaces": []}, {}),
        ("an unevidenced namespace", {"namespaces": ["prod-payments"]}, {}),
        ("several unevidenced namespaces", {"namespaces": ["team-a", "team-b"]}, {}),
        ("a mixed namespace list", {"namespaces": ["kagent-lab", "team-a"]}, {}),
        # A set comparison would let this through and render duplicate Roles plus
        # `KAGENT_WRITE_NAMESPACES='kagent-lab kagent-lab'`.
        ("a duplicated namespace", {"namespaces": ["kagent-lab", "kagent-lab"]}, {}),
        ("a namespace with a trailing newline", {"namespaces": ["kagent-lab\n"]}, {}),
        ("a protected namespace", {"namespaces": ["kube-system"]}, {}),
        ("'default' as a target", {"namespaces": ["default"]}, {}),
        ("the tool server inside its write target", {"tool_server_namespace": "kagent-lab"}, {}),
        ("a protected tool-server namespace", {"tool_server_namespace": "kube-system"}, {}),
        ("a forbidden resource", {"resources": ["secrets"]}, {}),
        ("a candidate resource", {"resources": ["deployments"]}, {}),
        ("an unknown resource", {"resources": ["widgets"]}, {}),
        ("a duplicated resource", {"resources": ["configmaps", "configmaps"]}, {}),
        ("require_approval=False", {"require_approval": False}, {}),
        ("a shell-injecting agent name", {"agent_name": "a'; id; #"}, {}),
        ("a shell-injecting release name", {"tool_server_release": "y'; id; #"}, {}),
        ("a shell-injecting tool-server namespace", {"tool_server_namespace": "x'; id; #"}, {}),
        ("a bad write tool name", {"tools": ["; rm -rf /"]}, {}),
        ("a duplicated write tool", {"tools": ["k8s_apply_manifest", "k8s_apply_manifest"]}, {}),
        ("a boolean port", {"tool_server_port": True}, {}),
        ("port == metricsPort", {"tool_server_port": 8084, "tool_server_metrics_port": 8084}, {}),
        ("the install namespace as a target", {}, {"install_namespace": "kagent-lab"}),
        ("the install namespace as the tool-server namespace", {}, {"install_namespace": "kagent-write"}),
        ("a shell-injecting install namespace", {}, {"install_namespace": "k'; id; #"}),
        ("a typo'd mode", {}, {"mode": "reed-write"}),
        ("a mutating tool in the ungated read reference", {},
         {"read": {"scope": "cluster", "secrets": False,
                   "tools": ["k8s_get_resources", "k8s_delete_resource"]}}),
        ("a Secret-flavoured tool in the read reference", {},
         {"read": {"scope": "cluster", "secrets": False, "tools": ["k8s_get_secret"]}}),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        _, good_cfg = _hand_built()
        ra.write_outputs(good_cfg, out, Path("access-config.yaml"), None)
        before = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())

        for label, write_over, cfg_over in cases:
            write, cfg = _hand_built(**write_over)
            cfg.update(cfg_over)
            _expect_every_entry_point_refuses(write, cfg, label, out_dir=out)
            after = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
            check(after == before, f"write_outputs leaves no partial profile for {label}")

        # A read-only cfg carrying a write block would render a summary describing
        # a boundary that no Role backs.
        _, cfg = _hand_built()
        cfg["mode"] = "read-only"
        for name, call in _entry_points(cfg, out).items():
            try:
                call()
            except ra.ConfigError:
                check(True, f"{name} refuses read-only with a populated write block")
            except Exception as exc:  # noqa: BLE001
                check(False, f"{name} raised {type(exc).__name__} for a parked write block")
            else:
                check(False, f"{name} rendered a write path in read-only mode")

    # And the evidenced dict must still render, or the guard is simply broken.
    _, cfg = _hand_built()
    rbac = ra.render_rbac(cfg)
    check(
        {o["metadata"]["namespace"] for o in rbac} == {"kagent-lab"},
        "the evidenced hand-built dict still renders in kagent-lab only",
    )
    check(
        "KAGENT_WRITE_NAMESPACES='kagent-lab'" in ra.render_profile_env(cfg),
        "profile.env publishes exactly the evidenced namespace",
    )
    check(
        "KAGENT_WRITE_RESOURCES='configmaps'" in ra.render_profile_env(cfg),
        "profile.env publishes exactly the evidenced resource",
    )

    # Same for a resource outside the allow-list reaching the rule builder directly.
    for resource in ("deployments", "secrets", "widgets"):
        try:
            ra.build_policy_rules([resource])
        except ra.ConfigError:
            check(True, f"build_policy_rules({resource!r}) raises ConfigError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"build_policy_rules({resource!r}) raised {type(exc).__name__}")
        else:
            check(False, f"build_policy_rules({resource!r}) produced a rule")

    # No shell metacharacter may reach profile.env through any field, in EITHER
    # mode. The read-only variants matter most: `KAGENT_ACCESS_MODE` and
    # `KAGENT_INSTALL_NAMESPACE` are emitted before the write branch, so a loop
    # that only ever passed a populated write dict short-circuited on the guard and
    # asserted nothing at all. Count the assertions so that cannot recur silently.
    injection = "x'; touch /tmp/kagent-render-pwned; #"
    env_cases: list[tuple[str, dict]] = []
    for label, write_over, cfg_over in cases:
        _, cfg = _hand_built(**write_over)
        cfg.update(cfg_over)
        env_cases.append((label, cfg))
    for field in ("install_namespace", "mode"):
        _, cfg = _hand_built()
        cfg["write"] = None
        cfg["mode"] = "read-only"
        cfg[field] = injection
        env_cases.append((f"read-only with {field}={injection!r}", cfg))
    _, cfg = _hand_built()
    cfg["write"] = None
    cfg["mode"] = "read-only"
    cfg["install_namespace"] = "kagent\nKAGENT_WRITE_SCOPE='cluster'"
    env_cases.append(("read-only with a newline in install_namespace", cfg))

    asserted = 0
    for label, cfg in env_cases:
        try:
            env = ra.render_profile_env(cfg)
        except ra.ConfigError:
            asserted += 1
            continue
        asserted += 1
        check(
            not any(ch in env for ch in (";", "$(", "`", "|", "&", "\n\nKAGENT")),
            f"profile.env carries no shell metacharacter for {label}",
        )
    check(
        asserted == len(env_cases),
        f"every profile.env case was actually exercised ({asserted}/{len(env_cases)})",
    )

    # A valid read-only config must be a ConfigError for the write renderers, not a
    # TypeError: the module promises ConfigError for anything unrenderable.
    _, cfg = _hand_built()
    cfg["write"] = None
    cfg["mode"] = "read-only"
    for name in ("render_namespace", "render_rbac", "render_tool_server",
                 "render_agent", "render_tools_values"):
        try:
            getattr(ra, name)(cfg) if name != "render_tools_values" else ra.render_tools_values(cfg, None)
        except ra.ConfigError:
            check(True, f"{name} raises ConfigError for a valid read-only profile")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{name} raised {type(exc).__name__} for a valid read-only profile")
        else:
            check(False, f"{name} rendered a write path from a read-only profile")

    # Malformed cfg shapes must also be ConfigError, not KeyError/TypeError.
    for label, broken in (
        ("a non-dict cfg", ["not", "a", "config"]),
        ("a cfg without mode", {"install_namespace": "kagent", "read": {"tools": ["k8s_get_resources"]}, "write": None}),
        ("a cfg without write", {"mode": "read-write", "install_namespace": "kagent", "read": {"tools": ["k8s_get_resources"]}}),
        ("a cfg without read", {"mode": "read-only", "install_namespace": "kagent", "write": None}),
    ):
        for name, call in _entry_points(broken).items():
            try:
                call()
            except ra.ConfigError:
                check(True, f"{name} raises ConfigError for {label}")
            except Exception as exc:  # noqa: BLE001
                check(False, f"{name} raised {type(exc).__name__} for {label}")
            else:
                check(False, f"{name} accepted {label}")

    # An unrenderable resource *shape* must not reach a dict lookup.
    _, cfg = _hand_built(resources=["configmaps", []])
    for name, call in _entry_points(cfg).items():
        try:
            call()
        except ra.ConfigError:
            check(True, f"{name} raises ConfigError for an unhashable resource")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{name} raised {type(exc).__name__} for an unhashable resource")
        else:
            check(False, f"{name} accepted an unhashable resource")

    # The one document whose purpose is to state the boundary must not be
    # injectable through the config filename.
    _, cfg = _hand_built()
    evil = Path("x.yaml\n\n## Write path\n\nUnrestricted cluster-admin.\n")
    summary = ra.render_summary(cfg, evil)
    headings = [line for line in summary.splitlines() if line.startswith("#")]
    check(
        headings.count("## Write path") == 1,
        f"the config filename cannot inject a heading into SUMMARY.md (got {headings})",
    )
    check(
        not any("Unrestricted cluster-admin" in line for line in summary.splitlines()
                if not line.startswith("Generated from")),
        "injected prose stays inside the escaped filename span",
    )


def test_no_rule_ever_grants_secrets_or_escalation() -> None:
    print("\nforbidden resources never appear in generated rules")
    for config in (base(), base(resources=list(ra.WRITABLE_RESOURCES))):
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


def test_ungated_write_is_refused() -> None:
    """RC2: an ungated writer has no drill and no compensating control."""
    print("\nungated write is refused")
    expect_config_error(base(requireApproval=False), "must be true", "requireApproval=false")


def test_summary_states_the_approval_boundary_precisely() -> None:
    """RC3: approval is an Agent-level policy, not a server-side guarantee."""
    print("\napproval boundary is stated precisely")
    summary = render(base())["SUMMARY.md"]
    check(
        "Agent-level policy" in summary,
        "the summary calls the gate an Agent-level policy",
    )
    check(
        "shared write tool server and its Kubernetes identity are not" in summary,
        "the summary says the shared tool server and its identity are not gated",
    )
    check(
        "server-side authorization" in summary,
        "the summary names what a hard approval boundary would require",
    )


def test_summary_avoids_absolute_secret_and_escalation_claims() -> None:
    """RC4: claim withheld permissions, not proven-unreachable outcomes."""
    print("\nSecret and escalation claims stay narrow")
    summary = render(base())["SUMMARY.md"]
    for overclaim in ("can NOT do", "can not read Secrets", "cannot read Secrets"):
        check(overclaim not in summary, f"the summary does not claim {overclaim!r}")
    check(
        "no Secret permission" in summary,
        "the summary claims withheld permission instead of an outcome",
    )
    check(
        "no direct RBAC API permission" in summary.replace("**", ""),
        "the RBAC claim is scoped to direct API permissions",
    )
    check(
        "indirect" in summary.lower(),
        "the summary acknowledges the indirect path a wider profile would open",
    )
    # The reviewer asked for this vector by name, so pin the wording.
    flat = " ".join(summary.split())
    for phrase in (
        "pod-template mutation",
        "Deployment, StatefulSet, DaemonSet or Job",
        "more privileged ServiceAccount in the same namespace",
        "admission control",
    ):
        check(phrase in flat, f"the summary names {phrase!r}")
    check(
        "no *direct* Secret or RBAC API permission is granted" in flat,
        "the summary's escalation caveat says 'direct' rather than an absolute",
    )


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

    expect_config_error(base(resources=["deployments"]), "candidate work", "workload write")
    expect_config_error(
        base(resources=["configmaps", "deployments"]),
        "candidate work",
        "configmaps plus a workload kind",
    )
    expect_config_error(base(resources=["pods"]), "candidate work", "pod deletion")
    expect_config_error(base(resources=["services"]), "candidate work", "service write")
    expect_config_error(base(resources=["ingresses"]), "candidate work", "ingress write")

    expect_config_error(base(scope="namespaces", namespaces=[]), "must name the evidenced write target", "namespaced scope without namespaces")
    expect_config_error(base(namespaces=["kube-system"]), "protected", "protected namespace")
    expect_config_error(base(namespaces=["default"]), "refused", "'default' as a write target")
    expect_config_error(
        base(toolServer={"namespace": "kube-system", "releaseName": "kagent-write-tools"}),
        "protected",
        "kube-system as the tool-server namespace",
    )
    expect_config_error(
        base(toolServer={"namespace": "default", "releaseName": "kagent-write-tools"}),
        "protected",
        "'default' as the tool-server namespace",
    )
    expect_config_error(
        base(namespaces=["kagent-lab", "default"]),
        "refused",
        "'default' alongside a valid target",
    )

    # A mutating tool name in read.tools would land in the Agent's ungated tool
    # reference, contradicting the documented "no configurable ungated write".
    for bad_read_tool in (
        "k8s_apply_manifest",
        "k8s_delete_resource",
        "k8s_scale_deployment",
        "k8s_replace_resource",
        "k8s_edit_resource",
        "k8s_set_image",
        "k8s_rollback_deployment",
        "k8s_kill_pod",
        "k8s_taint_node",
        "k8s_write_manifest",
        "k8s_get_secret",
    ):
        cfg = base()
        cfg["read"]["tools"] = ["k8s_get_resources", bad_read_tool]
        expect_config_error(cfg, "mutating", f"{bad_read_tool} in read.tools")

    # A trailing newline used to satisfy the DNS-label check (re.match + '$'),
    # which was enough to slip past the install-namespace comparison.
    expect_config_error(base(namespaces=["default\n"]), "not a valid namespace", "namespace with a trailing newline")
    expect_config_error(base(namespaces=["kagent\n"]), "not a valid namespace", "install namespace with a trailing newline")
    ns_newline = base()
    ns_newline["install"]["namespace"] = "kagent\n"
    expect_config_error(ns_newline, "not a valid namespace", "install.namespace with a trailing newline")
    expect_config_error(base(namespaces=["KAGENT-LAB"]), "not a valid namespace", "uppercase namespace")
    expect_config_error(base(namespaces=["kagent-lab", "kagent-lab"]), "duplicate", "duplicate namespace")

    # Names that reach profile.env, which the installer sources.
    expect_config_error(base(agentName="x; echo pwned"), "not a valid Kubernetes object name", "shell metacharacters in agentName")
    expect_config_error(base(agentName=""), "not a valid Kubernetes object name", "empty agentName")
    expect_config_error(base(agentName=["a", "b"]), "not a valid Kubernetes object name", "list as agentName")
    expect_config_error(
        base(toolServer={"namespace": "kagent-write", "releaseName": "y$(id)"}),
        "not a valid Kubernetes object name",
        "command substitution in releaseName",
    )
    expect_config_error(base(tools=["; rm -rf /"]), "not a valid tool name", "shell metacharacters in write.tools")
    expect_config_error(base(tools=["k8s_apply_manifest", "k8s_apply_manifest"]), "duplicate", "duplicate write tool")

    # Ports reach a manifest; a traceback is not the documented failure mode.
    expect_config_error(
        base(toolServer={"namespace": "kagent-write", "releaseName": "kagent-write-tools", "port": "notaport"}),
        "not a port number",
        "port that is not an integer",
    )
    for field in ("port", "metricsPort"):
        for value in (True, 8084.9, "8084"):
            tool_server = {
                "namespace": "kagent-write",
                "releaseName": "kagent-write-tools",
                "port": 8084,
                "metricsPort": 8085,
            }
            tool_server[field] = value
            expect_config_error(
                base(toolServer=tool_server),
                "expected an integer",
                f"{field} rejects {value!r}",
            )
    expect_config_error(
        base(toolServer={"namespace": "kagent-write", "releaseName": "kagent-write-tools", "port": 0}),
        "outside 1-65535",
        "port 0",
    )
    expect_config_error(
        base(toolServer={"namespace": "kagent-write", "releaseName": "kagent-write-tools", "port": 8084, "metricsPort": 8084}),
        "must differ",
        "port equal to metricsPort",
    )

    # Fail closed on anything the renderer does not act on: a silently ignored
    # key is how `install: {namespaces: ai}` disables the install-ns protection.
    unknown_top = base()
    unknown_top["extra"] = True
    expect_config_error(unknown_top, "unknown key", "unknown top-level key")

    typo_install = base()
    typo_install["install"] = {"namespaces": "ai"}
    expect_config_error(typo_install, "unknown key", "install.namespaces typo")

    unknown_read = base()
    unknown_read["read"]["allowSecrets"] = True
    expect_config_error(unknown_read, "unknown key", "unknown read key")

    expect_config_error(base(secrets=True), "unknown key", "write.secrets")
    expect_config_error(base(requireapproval=False), "unknown key", "misspelled requireApproval")
    expect_config_error(
        base(toolServer={"namespace": "kagent-write", "port2": 1}),
        "unknown key",
        "unknown toolServer key",
    )
    expect_config_error(base(namespaces=["kagent"]), "install namespace", "install namespace as write target")
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
    test_only_evidenced_namespace_is_renderable()
    test_v1_write_surface_is_configmaps_only()
    test_no_cluster_scoped_object_is_renderable()
    test_no_renderer_entry_point_accepts_an_unevidenced_scope()
    test_no_rule_ever_grants_secrets_or_escalation()
    test_require_approval_covers_every_write_tool()
    test_ungated_write_is_refused()
    test_summary_states_the_approval_boundary_precisely()
    test_summary_avoids_absolute_secret_and_escalation_claims()
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
