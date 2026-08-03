#!/usr/bin/env python3
"""
OK-129 access profile renderer.

One declarative config decides what a standalone kagent installation is allowed
to do. This script turns that config into the Helm value fragment and the
Kubernetes objects that implement it, so the permission model has exactly one
editable source instead of being spread across a chart, a Makefile and three
hand-maintained manifests.

Design rules, in order of importance:

1.  RBAC is the boundary this renderer controls. The tool identity's Role decides
    which API calls are permitted; ``toolNames`` and ``requireApproval`` shape
    *intent*, not permission. The renderer therefore never emits a write tool
    without emitting the matching, scoped Role in the same run.

    RBAC being the boundary *here* is not the claim that RBAC is a sufficient
    boundary in general: it constrains direct API calls, and some permissions
    (workload pod-template write above all) reach further than the verbs they
    name. That is why rule 4 exists — the surface is kept to permissions whose
    reach RBAC alone does describe.
2.  Fail closed. Any config the renderer does not fully understand is an error,
    not a default. Secrets, RBAC objects, ServiceAccounts and wildcards can not
    be granted at all.
3.  Read-only means nothing is generated for the write path. Switching the mode
    back removes objects rather than leaving them orphaned.
4.  **Only evidenced capability is executable.** v1 renders exactly the write
    profile that has been exercised against a live cluster and recorded in
    ``docs/kagent-standalone/evidence-protocol.md``: approval-gated ConfigMap
    writes in ``[kagent-lab]``. Everything wider — any other namespace target,
    workload kinds, Jobs, Services, Ingresses, Pod deletion, ungated writes and
    cluster-wide scope — is candidate work and is *refused*, not defaulted.

    Two different reasons, kept distinct on purpose:

    * **Boundary gaps.** Cluster scope and workload write cannot be bounded with
      what this lab has: a ``ClusterRoleBinding`` cannot exclude a namespace, and
      pod-template write reaches Secrets and other ServiceAccounts without the
      Role naming them. See the ``write.scope`` check and
      ``WORKLOAD_WRITE_PRECONDITION``.
    * **Evidence gaps.** Another namespace target, Services, Ingresses and Pod
      deletion are enforceable in the same shape that already works — they simply
      have no recorded drill. Shape is not evidence, so they are refused too, but
      promoting one is a drill rather than a design problem.

    Both are enforced by this module rather than left to a consumer. The
    allow-lists are ``WRITABLE_RESOURCES`` and ``EVIDENCED_WRITE_NAMESPACES``, and
    the rule for where they apply is deliberately blunt:

        **Nothing ``load_config`` refuses may be renderable.**

    Every public renderer calls ``_require_renderable_profile``, which does not
    re-list the invariants — it converts the config back to its on-disk shape and
    runs ``validate_raw_config``, the *same* validator ``load_config`` uses. There
    is therefore one validator and no second list to drift from the first, which is
    what makes the rule above true by construction. This matters because the module
    is the shared renderer: an importer can build the config by hand, and an
    invariant checked only in the loader is an invariant only for callers that use
    the loader — the same gap as leaving it to each consumer to re-implement.

Usage::

    render-access.py --config access-config.yaml --out .access.local
    render-access.py --config access-config.yaml --out .access.local --summary

Outputs, all inside ``--out``::

    values-access.yaml        Helm values fragment for the built-in read path
    tools-values.yaml         Helm values for the scoped write tool server
    manifests/10-namespace.yaml
    manifests/20-rbac.yaml
    manifests/30-tool-server.yaml
    manifests/40-agent.yaml
    profile.env               shell-sourceable facts for the installer
    SUMMARY.md                what this profile grants, in prose

Only ``manifests/`` is meant for ``kubectl apply -f``. Nothing written here is
private, but it is generated: keep it out of Git and regenerate instead.

Python 3.9+, PyYAML (already required by ok-cluster/render.py).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# --------------------------------------------------------------------------- #
# Policy tables — the hard limits of what this renderer will ever grant.
# --------------------------------------------------------------------------- #

READ_VERBS = ["get", "list", "watch"]
WRITE_VERBS = ["create", "update", "patch", "delete"]

#: Resources a v1 write profile may target: name -> (apiGroup, extra verbs).
#:
#: Exactly one entry, and that is the point. This is the only write capability
#: the PoC has evidenced on a live cluster (approval-gated ConfigMap create /
#: patch / delete in ``kagent-lab``), so it is the only one the renderer will
#: produce. Adding a kind here is a claim that a drill for it has been run and
#: recorded.
WRITABLE_RESOURCES = {
    "configmaps": ("", WRITE_VERBS),
}

#: Candidate work: recognised, deliberately refused, each with the reason it is
#: not just "untested". These are not defaults waiting for a flag — every one of
#: them needs a boundary that does not exist in this lab yet.
CANDIDATE_RESOURCES = {
    "deployments": "workload pod-template write — see WORKLOAD_WRITE_PRECONDITION",
    "statefulsets": "workload pod-template write — see WORKLOAD_WRITE_PRECONDITION",
    "daemonsets": "workload pod-template write — see WORKLOAD_WRITE_PRECONDITION",
    "replicasets": "workload pod-template write — see WORKLOAD_WRITE_PRECONDITION",
    "jobs": "workload pod-template write — see WORKLOAD_WRITE_PRECONDITION",
    "cronjobs": "workload pod-template write — see WORKLOAD_WRITE_PRECONDITION",
    "services": "traffic-path write: no drill, and no tested blast-radius bound",
    "ingresses": "traffic-path write: no drill, and no tested blast-radius bound",
    "pods": "Pod deletion is a disruption primitive; no recorded drill",
}

#: Why the workload kinds above are a boundary problem and not a test gap: a
#: principal that can create or patch a pod template can usually choose another
#: ``serviceAccountName``, mount an existing Secret, or change the image and
#: command. Withholding the Secret and RBAC verbs from the Role does not stop
#: that — it only stops the *direct* API call. Workload write therefore needs
#: either narrowly typed repair tools with deterministic field restrictions, or
#: a documented and tested admission-policy boundary, before it can ship.
WORKLOAD_WRITE_PRECONDITION = (
    "workload write needs typed repair tools with fixed editable fields, or a "
    "tested admission policy: pod-template mutation can reach existing Secrets "
    "or a more privileged ServiceAccount in the same namespace, which the Role "
    "itself never grants"
)

#: Never grantable, whatever the config says. Withholding these removes the
#: *direct* API path to Secrets and to RBAC objects. It does not by itself prove
#: that no indirect path exists — see WORKLOAD_WRITE_PRECONDITION.
FORBIDDEN_RESOURCES = {
    "*",
    "secrets",
    "serviceaccounts",
    "roles",
    "rolebindings",
    "clusterroles",
    "clusterrolebindings",
    "namespaces",
    "nodes",
    "persistentvolumes",
    "customresourcedefinitions",
    "validatingwebhookconfigurations",
    "mutatingwebhookconfigurations",
}

#: Read-only context the write identity gets inside its own scope, so the agent
#: can verify the change it just made instead of asserting success.
#:
#: Deliberately excludes every workload controller kind. Granting the write
#: identity even a read verb on ``apps`` resources would make the documented
#: claim "no permission on workload kinds" false, and cluster-wide read is
#: already available through the separate read tool server — the agent does not
#: need it twice.
WRITE_SCOPE_CONTEXT = [
    ("", ["pods", "pods/log", "events"], READ_VERBS),
]

PROTECTED_NAMESPACE_PREFIXES = ("kube-",)

#: Refused as write targets whatever else the config says. ``default`` is here
#: rather than in a warning because the generated summary asserts that writes in
#: ``default`` are denied — a warning would let that assertion become false.
PROTECTED_NAMESPACES = frozenset({"default"})

#: The only namespace target exercised by the recorded v1 drill. This belongs
#: in the shared renderer rather than only in an installer-side guard: every
#: consumer must get the same evidenced boundary without reimplementing it.
EVIDENCED_WRITE_NAMESPACES = frozenset({"kagent-lab"})

#: The port the kagent-tools chart serves on. This renderer does *not* template
#: the chart's service port — only the metrics port — so ``write.toolServer.port``
#: is the port the generated ``RemoteMCPServer`` URL points at, not the port the
#: chart is told to listen on. A different value would therefore produce a URL that
#: lies. Fail closed rather than emit it: the port is pinned until the chart value
#: is templated too.
CHART_TOOLS_PORT = 8084

#: Matched with ``fullmatch``. ``re.match`` with ``$`` would accept a trailing
#: newline, and ``"kagent\n"`` passing this check is enough to slip past the
#: install-namespace and tool-server-namespace comparisons below.
DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")

#: The write tools a profile exposes when it does not name its own.
DEFAULT_WRITE_TOOLS = [
    "k8s_apply_manifest",
    "k8s_patch_resource",
    "k8s_delete_resource",
]

#: Tool names are identifiers, not free text: they end up in a manifest and in a
#: shell-sourceable file.
TOOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,126}")

#: A container image tag. Interpolated into a Helm values file.
IMAGE_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")

#: Substrings that mark a tool name as mutating or Secret-flavoured. Used to keep
#: ``read.tools`` — which is rendered without an approval gate — free of anything
#: that is not a read. A substring heuristic cannot be complete; it is a
#: consistency check on the config, never the boundary. RBAC
#: (``readOnly: true``, ``allowSecrets: false``) is what actually denies these.
MUTATING_TOOL_MARKERS = (
    "annotate",
    "apply",
    "cordon",
    "create",
    "delete",
    "drain",
    "edit",
    "evict",
    "exec",
    "kill",
    "label_",
    "patch",
    "put_",
    "remove",
    "replace",
    "restart",
    "rollback",
    "rollout",
    "run_",
    "scale",
    "secret",
    "set_",
    "taint",
    "update",
    "write",
)

DEFAULT_READ_TOOLS = [
    "k8s_get_resources",
    "k8s_describe_resource",
    "k8s_get_events",
    "k8s_get_pod_logs",
    "k8s_get_resource_yaml",
]

COMMON_LABELS = {
    "app.kubernetes.io/part-of": "kagent-standalone",
    "app.kubernetes.io/managed-by": "render-access.py",
    "openkubes.io/ticket": "OK-129",
}

GENERATED_HEADER = (
    "# Generated by research/kagent-standalone/access/render-access.py\n"
    "# Source of truth: access-config.yaml. Do not edit this file — edit the\n"
    "# config and re-render, otherwise the next render silently reverts you.\n"
)


class ConfigError(Exception):
    """Raised for any config the renderer refuses to act on."""


# --------------------------------------------------------------------------- #
# Config loading and validation
# --------------------------------------------------------------------------- #


def _require_namespace_name(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) > 63 or not DNS_LABEL.fullmatch(value):
        raise ConfigError(f"{field}: {value!r} is not a valid namespace name")
    return value


def _require_object_name(value: object, field: str) -> str:
    """A Kubernetes object name that is also safe to write into ``profile.env``.

    ``profile.env`` is documented as shell-sourceable, so an unvalidated name is a
    command-injection surface in the installer, not merely an invalid manifest.
    Same shape as a namespace: lowercase DNS label.
    """
    if not isinstance(value, str) or len(value) > 63 or not DNS_LABEL.fullmatch(value):
        raise ConfigError(
            f"{field}: {value!r} is not a valid Kubernetes object name "
            "(lowercase DNS label, 1-63 chars). This value is also written into "
            "profile.env, which the installer sources."
        )
    return value


def _require_tool_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not TOOL_NAME.fullmatch(value):
        raise ConfigError(
            f"{field}: {value!r} is not a valid tool name. Expected an "
            "identifier — letters, digits, '_', '.', '-'. Check the installed "
            "server with `kubectl get remotemcpserver <name> -o yaml`."
        )
    return value


def _require_read_tool_name(value: object, field: str = "read.tools") -> str:
    """Refuse a mutating or Secret-flavoured tool name in ``read.tools``.

    The read tool reference is deliberately *not* approval-gated, because reads
    do not need a human. That is only defensible while the list actually contains
    reads. The read identity's RBAC would still deny the call, so this is not the
    boundary — but a mutating name in an ungated reference contradicts the
    documented statement that no ungated write path is configurable, and a
    contradiction between the documentation and the manifest is exactly the class
    of bug this renderer exists to remove.

    The check is a substring heuristic and cannot be complete. It catches the
    plausible mistakes; it is not a security control, and the docstring says so
    because someone will eventually read this as one.
    """
    name = _require_tool_name(value, field)
    lowered = name.lower()
    if name in DEFAULT_WRITE_TOOLS or any(
        marker in lowered for marker in MUTATING_TOOL_MARKERS
    ):
        raise ConfigError(
            f"{field}: {name!r} looks like a mutating or Secret-related tool. "
            "The read tool reference is ungated by design, so only read tools "
            "may appear in it. Put write tools in write.tools, where the "
            "approval gate is applied."
        )
    return name


def _reject_unknown_keys(mapping: dict, allowed: set, field: str) -> None:
    """Fail closed on a key the renderer does not act on.

    A silently ignored key is the worst failure mode here: ``install: {namespaces:
    ai}`` (plural typo) would leave ``install.namespace`` at its default and
    quietly disable the install-namespace protection that the summary advertises.
    """
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ConfigError(
            f"{field}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            "This renderer fails closed rather than ignoring configuration it "
            f"does not act on. Known keys: {', '.join(sorted(allowed))}."
        )


def _require_mapping(value: object, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field}: expected a mapping")
    return value


def _require_port(value: object, field: str) -> int:
    # bool is a subclass of int in Python. An explicit exclusion is required or
    # YAML `port: true` silently becomes port 1. Do not coerce strings or floats
    # either: both layers consume the same config and must agree on its type.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(
            f"{field}: {value!r} is not a port number; expected an integer"
        )
    port = value
    if not 1 <= port <= 65535:
        raise ConfigError(f"{field}: {port} is outside 1-65535")
    return port


def load_config(path: Path, quiet: bool = False) -> dict:
    """Parse and validate the access profile. Raises ConfigError on anything odd.

    ``quiet`` suppresses the advisory note about a parked write block. There are
    no boundary *warnings* left: every weakened boundary this renderer used to
    warn about is now a ``ConfigError``, because a warning is something an
    operator can pipe to /dev/null while the documentation keeps claiming the
    boundary holds.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"access config not found: {path}")
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}")

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a YAML mapping")

    return validate_raw_config(raw, quiet=quiet)


def validate_raw_config(raw: dict, quiet: bool = False) -> dict:
    """Validate a parsed config mapping and return the internal config.

    Split out of ``load_config`` so that there is exactly *one* validator. The
    render path re-enters this same function (see ``_require_renderable_profile``)
    instead of re-implementing the checks, which is what makes "nothing
    ``load_config`` refuses may be renderable" true by construction rather than by
    keeping two lists in sync — and two lists in sync is precisely what kept
    failing review.
    """
    _reject_unknown_keys(raw, {"kind", "mode", "install", "read", "write"}, "<top level>")

    kind = raw.get("kind")
    if kind not in (None, "KagentAccessProfile"):
        raise ConfigError(f"kind: expected KagentAccessProfile, got {kind!r}")

    mode = raw.get("mode")
    if mode not in ("read-only", "read-write"):
        raise ConfigError("mode: must be 'read-only' or 'read-write'")

    install = _require_mapping(raw.get("install"), "install")
    _reject_unknown_keys(install, {"namespace"}, "install")
    install_ns = _require_namespace_name(
        install.get("namespace", "kagent"), "install.namespace"
    )

    read = _require_mapping(raw.get("read"), "read")
    _reject_unknown_keys(read, {"scope", "secrets", "tools"}, "read")
    read_scope = read.get("scope", "cluster")
    if read_scope != "cluster":
        raise ConfigError(
            "read.scope: only 'cluster' is implemented. Namespaced read scoping "
            "would have to take over the chart's built-in tool RBAC; that is a "
            "separate, testable change — do not fake it here."
        )
    if read.get("secrets", False):
        raise ConfigError(
            "read.secrets: refused. No profile in this deployment may grant "
            "Secret access to a tool identity."
        )

    cfg = {
        "mode": mode,
        "install_namespace": install_ns,
        "read": {"scope": read_scope, "secrets": False, "tools": None},
        "write": None,
    }

    read_tools = read.get("tools")
    if read_tools is None:
        cfg["read"]["tools"] = list(DEFAULT_READ_TOOLS)
    else:
        if not isinstance(read_tools, list) or not read_tools:
            raise ConfigError("read.tools: must be a non-empty list when set")
        cfg["read"]["tools"] = [_require_read_tool_name(t) for t in read_tools]

    if mode == "read-only":
        if raw.get("write"):
            # Not an error: keeping the write block while switching the mode off
            # is the normal way to park a profile. Say so, do not act on it.
            if not quiet:
                print(
                    "note: mode is read-only — the write block is parsed for "
                    "validation but nothing is generated for it.",
                    file=sys.stderr,
                )
            _validate_write(raw["write"], install_ns)
        return cfg

    write_raw = raw.get("write")
    if not write_raw:
        raise ConfigError("write: required when mode is 'read-write'")
    cfg["write"] = _validate_write(write_raw, install_ns)
    return cfg


def _validate_write(write_raw: object, install_ns: str) -> dict:
    if not isinstance(write_raw, dict):
        raise ConfigError("write: expected a mapping")

    _reject_unknown_keys(
        write_raw,
        {
            "scope",
            "namespaces",
            "resources",
            "requireApproval",
            "toolServer",
            "tools",
            "agentName",
        },
        "write",
    )

    scope = write_raw.get("scope")
    if scope == "cluster":
        raise ConfigError(
            "write.scope: 'cluster' is refused. This is not a missing test — a "
            "normal ClusterRoleBinding applies in every namespace, including the "
            "install namespace, the write tool server's own namespace, kube-* and "
            "any namespace created later, and RBAC cannot express those "
            "exclusions. An allow-list of namespaces can be checked one entry at "
            "a time; a cluster-scoped binding has no entries to check. "
            "Cluster-wide write stays candidate work until there is a forcing "
            "consumer and an enforceable boundary (admission policy, or a tool "
            "server that scopes its own calls). Use write.scope: namespaces with "
            "the evidenced target, EVIDENCED_WRITE_NAMESPACES."
        )
    if scope != "namespaces":
        raise ConfigError(
            "write.scope: must be 'namespaces'. v1 renders only the evidenced "
            "target, EVIDENCED_WRITE_NAMESPACES."
        )

    namespaces = write_raw.get("namespaces") or []
    if not isinstance(namespaces, list):
        raise ConfigError("write.namespaces: expected a list")
    namespaces = [_require_namespace_name(n, "write.namespaces[]") for n in namespaces]

    if not namespaces:
        raise ConfigError(
            "write.namespaces: must name the evidenced write target: "
            + repr(sorted(EVIDENCED_WRITE_NAMESPACES))
            + ". There is no implicit, wildcard or empty scope."
        )

    if len(set(namespaces)) != len(namespaces):
        raise ConfigError("write.namespaces: contains a duplicate entry")

    for ns in namespaces:
        if ns.startswith(PROTECTED_NAMESPACE_PREFIXES):
            raise ConfigError(f"write.namespaces: {ns!r} is a protected namespace")
        if ns == install_ns:
            raise ConfigError(
                f"write.namespaces: {ns!r} is the kagent install namespace. "
                "Letting an agent write into kagent's own namespace means it can "
                "rewrite its own Agent and tool definitions."
            )
        if ns in PROTECTED_NAMESPACES:
            raise ConfigError(
                f"write.namespaces: {ns!r} is refused. Everything unqualified "
                "lands there, so it is not a bounded target — and the profile "
                "summary asserts that writes in it are denied, which a warning "
                "would quietly turn into a false claim. Use a purpose-named "
                "namespace."
            )

    if set(namespaces) != EVIDENCED_WRITE_NAMESPACES:
        expected = ", ".join(sorted(EVIDENCED_WRITE_NAMESPACES))
        raise ConfigError(
            "write.namespaces: v1 requires exactly the evidenced target: "
            f"[{expected}]. Other namespace targets are candidate work until "
            "they have their own recorded drill and reviewed boundary."
        )

    resources = write_raw.get("resources") or []
    if not isinstance(resources, list) or not resources:
        raise ConfigError("write.resources: must list at least one resource")
    for r in resources:
        if not isinstance(r, str):
            raise ConfigError(f"write.resources: {r!r} is not a resource name")
    resources = [r.lower() for r in resources]
    if len(set(resources)) != len(resources):
        raise ConfigError("write.resources: contains a duplicate entry")

    for res in resources:
        if res in FORBIDDEN_RESOURCES:
            raise ConfigError(
                f"write.resources: {res!r} can never be granted by this renderer"
            )
        if res in CANDIDATE_RESOURCES:
            reason = CANDIDATE_RESOURCES[res]
            if "WORKLOAD_WRITE_PRECONDITION" in reason:
                reason = WORKLOAD_WRITE_PRECONDITION
            raise ConfigError(
                f"write.resources: {res!r} is candidate work, not a v1 option "
                f"({reason}). v1 renders only: "
                + ", ".join(sorted(WRITABLE_RESOURCES))
            )
        if res not in WRITABLE_RESOURCES:
            raise ConfigError(
                f"write.resources: {res!r} is not supported. Supported: "
                + ", ".join(sorted(WRITABLE_RESOURCES))
            )

    require_approval = write_raw.get("requireApproval", True)
    if not isinstance(require_approval, bool):
        raise ConfigError("write.requireApproval: must be true or false")
    if not require_approval:
        raise ConfigError(
            "write.requireApproval: must be true. The only evidenced write "
            "profile is approval-gated; an ungated writer has no recorded drill "
            "and no compensating control in this lab. Ungated writes are "
            "candidate work."
        )

    tool_server = _require_mapping(write_raw.get("toolServer"), "write.toolServer")
    _reject_unknown_keys(
        tool_server,
        {"namespace", "releaseName", "port", "metricsPort"},
        "write.toolServer",
    )
    ts_namespace = _require_namespace_name(
        tool_server.get("namespace", "kagent-write"), "write.toolServer.namespace"
    )
    if ts_namespace in namespaces:
        raise ConfigError(
            f"write.toolServer.namespace: {ts_namespace!r} is also a write "
            "target. Host the tool server outside the namespaces it may change, "
            "otherwise the agent can modify its own tool deployment."
        )
    if ts_namespace == install_ns:
        raise ConfigError(
            "write.toolServer.namespace: must differ from the kagent install "
            "namespace so the write identity stays separately auditable."
        )
    # The protected list applies here too. The profile *creates* this namespace, so
    # `toolServer.namespace: kube-system` would relabel kube-system on apply.
    if ts_namespace.startswith(PROTECTED_NAMESPACE_PREFIXES) or ts_namespace in PROTECTED_NAMESPACES:
        raise ConfigError(
            f"write.toolServer.namespace: {ts_namespace!r} is a protected "
            "namespace, and the profile creates this one — it must be its own."
        )

    tools = write_raw.get("tools") or DEFAULT_WRITE_TOOLS
    if not isinstance(tools, list) or not tools:
        raise ConfigError("write.tools: must be a non-empty list when set")
    tools = [_require_tool_name(t, "write.tools[]") for t in tools]
    if len(set(tools)) != len(tools):
        raise ConfigError("write.tools: contains a duplicate entry")

    port = _require_port(tool_server.get("port", 8084), "write.toolServer.port")
    metrics_port = _require_port(
        tool_server.get("metricsPort", 8085), "write.toolServer.metricsPort"
    )
    if port != CHART_TOOLS_PORT:
        raise ConfigError(
            f"write.toolServer.port: must be {CHART_TOOLS_PORT}, got {port}. This "
            "renderer does not template the chart's tool service port — it only "
            "renders metrics.port — so this value only reaches the generated "
            "RemoteMCPServer URL. Any other number produces a URL pointing at a "
            "port the tool server is not serving. See CHART_TOOLS_PORT."
        )
    if port == metrics_port:
        raise ConfigError(
            f"write.toolServer.metricsPort: must differ from the tool port "
            f"({port}); the chart would otherwise render two container ports with "
            "the same number, which Kubernetes rejects."
        )

    return {
        "scope": scope,
        "namespaces": namespaces,
        "resources": resources,
        # Constant True: an ungated profile is refused above. Kept in the dict so
        # the renderers read a fact rather than an assumption.
        "require_approval": require_approval,
        "tool_server_namespace": ts_namespace,
        "tool_server_release": _require_object_name(
            tool_server.get("releaseName", "kagent-write-tools"),
            "write.toolServer.releaseName",
        ),
        "tool_server_port": port,
        "tool_server_metrics_port": metrics_port,
        "tools": tools,
        "agent_name": _require_object_name(
            write_raw.get("agentName", "cluster-operator-gated"), "write.agentName"
        ),
    }


# --------------------------------------------------------------------------- #
# Rule building
# --------------------------------------------------------------------------- #


def build_policy_rules(resources: list[str]) -> list[dict]:
    """Group the requested resources into PolicyRules, one per (apiGroup, verbs).

    Raises ``ConfigError`` — not ``KeyError`` — for a resource outside the v1
    allow-list, so a caller that skipped ``load_config`` still gets this module's
    documented failure mode rather than a traceback.
    """
    grouped: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for res in sorted(resources):
        if res not in WRITABLE_RESOURCES:
            raise ConfigError(
                f"build_policy_rules: {res!r} is not in the v1 allow-list "
                f"({', '.join(sorted(WRITABLE_RESOURCES))}). No rule is generated "
                "for a resource this renderer does not support."
            )
        api_group, extra_verbs = WRITABLE_RESOURCES[res]
        verbs = tuple(READ_VERBS + [v for v in extra_verbs if v not in READ_VERBS])
        grouped.setdefault((api_group, verbs), []).append(res)

    rules = [
        {
            "apiGroups": [api_group],
            "resources": res_list,
            "verbs": list(verbs),
        }
        for (api_group, verbs), res_list in sorted(grouped.items())
    ]

    for api_group, ctx_resources, verbs in WRITE_SCOPE_CONTEXT:
        already = {r for rule in rules if rule["apiGroups"] == [api_group] for r in rule["resources"]}
        missing = [r for r in ctx_resources if r not in already]
        if missing:
            rules.append(
                {"apiGroups": [api_group], "resources": missing, "verbs": list(verbs)}
            )
    return rules


def _inline_code(value: object) -> str:
    """Make an arbitrary string safe inside a markdown inline-code span.

    Newlines out (a heading needs a line start), backticks and backslashes out (they
    end the span), and a length cap. The config filename is caller-supplied and
    lands in the one document whose purpose is to be the reviewable statement of the
    boundary, so it must not be able to add a section to it.
    """
    text = re.sub(r"\s+", " ", str(value))
    return re.sub(r"[`\\]", "", text).strip()[:120]


def _labels(extra: dict | None = None) -> dict:
    labels = dict(COMMON_LABELS)
    if extra:
        labels.update(extra)
    return labels


# --------------------------------------------------------------------------- #
# Manifest rendering
# --------------------------------------------------------------------------- #


def _to_raw_config(cfg: dict) -> dict:
    """Map the internal config back to the on-disk config shape.

    The inverse of what ``validate_raw_config`` produces. Its only job is to let
    the render path re-enter the single validator, so no invariant has to be
    written twice.
    """
    if not isinstance(cfg, dict):
        raise ConfigError(f"expected a config mapping, got {type(cfg).__name__}")
    read = cfg.get("read")
    if not isinstance(read, dict):
        raise ConfigError("read: expected a mapping")
    raw: dict = {
        "kind": "KagentAccessProfile",
        "mode": cfg.get("mode"),
        "install": {"namespace": cfg.get("install_namespace")},
        "read": {
            "scope": read.get("scope", "cluster"),
            "secrets": read.get("secrets", False),
            "tools": read.get("tools"),
        },
    }
    write = cfg.get("write")
    if write is not None:
        if not isinstance(write, dict):
            raise ConfigError("write: expected a mapping")
        raw["write"] = {
            "scope": write.get("scope"),
            "namespaces": write.get("namespaces"),
            "resources": write.get("resources"),
            "requireApproval": write.get("require_approval"),
            "toolServer": {
                "namespace": write.get("tool_server_namespace"),
                "releaseName": write.get("tool_server_release"),
                "port": write.get("tool_server_port"),
                "metricsPort": write.get("tool_server_metrics_port"),
            },
            "tools": write.get("tools"),
            "agentName": write.get("agent_name"),
        }
    return raw


def _require_renderable_profile(cfg: dict, caller: str) -> None:
    """Re-validate the whole profile, through the *same* validator, at every
    render entry point.

    This module is the shared renderer: an importer can build ``cfg`` by hand and
    never call ``load_config``. An invariant checked only in ``load_config`` is
    therefore an invariant only for callers that use ``load_config`` — the same gap
    as leaving it to each downstream consumer to re-implement.

    Earlier versions of this function re-listed the invariants. That is the wrong
    shape: the list drifted from ``_validate_write`` three times, and each time a
    reviewer found the one that had been missed. So it does not re-list anything —
    it converts the config back to its on-disk shape and runs
    ``validate_raw_config`` over it. Divergence is then impossible by construction,
    and the guarantee is checkable in one sentence:

        **Nothing ``load_config`` refuses may be renderable.**

    Round-tripping also catches a config that would validate but not survive the
    conversion, which is how a silently dropped or renamed field would show up.

    A ``ConfigError``, never an ``assert``: ``python3 -O`` strips asserts, and
    ``profile.env`` — which an installer sources, and reads to decide what to
    verify — must not be able to disagree with the manifests beside it.
    """
    try:
        revalidated = validate_raw_config(_to_raw_config(cfg), quiet=True)
    except ConfigError as exc:
        raise ConfigError(f"{caller}: {exc}") from None

    # The round trip must be lossless. If it is not, this config is not the one
    # the validator just approved.
    if revalidated != cfg:
        raise ConfigError(
            f"{caller}: the config does not survive revalidation unchanged. "
            f"Validated: {revalidated!r}. Given: {cfg!r}. A field was dropped, "
            "renamed or carries a value the validator normalises — either way the "
            "rendered output would not match the profile that was checked."
        )


def _require_write_profile(cfg: dict, caller: str) -> dict:
    """The full guard, plus: this renderer only exists for a write profile.

    Without the mode check the write renderers accepted a valid *read-only* config
    and failed with ``TypeError: 'NoneType' object is not subscriptable`` — a
    traceback where the module promises a ``ConfigError``.
    """
    _require_renderable_profile(cfg, caller)
    if not _is_read_write(cfg):
        raise ConfigError(
            f"{caller}: mode is {cfg['mode']!r}; there is no write profile to "
            "render. Read-only means nothing is generated for the write path."
        )
    return cfg["write"]


def _is_read_write(cfg: dict) -> bool:
    """The single predicate for the mode.

    ``write_outputs``, ``render_summary`` and ``render_profile_env`` each used to
    test this differently — ``mode == "read-write"``, ``mode == "read-only"``, and
    ``if write:`` — so a typo'd mode took a different branch in each and produced a
    summary describing RBAC that was never rendered.
    """
    return cfg["mode"] == "read-write"


def render_namespace(cfg: dict) -> list[dict]:
    """The write tool server's own namespace.

    Guarded like every other entry point. It was previously the only renderer
    without a guard — and, not coincidentally, the only one missing from the test
    that claims every entry point is guarded.
    """
    write = _require_write_profile(cfg, "render_namespace")
    return [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": write["tool_server_namespace"],
                "labels": _labels({"openkubes.io/purpose": "kagent-write-tools"}),
            },
        }
    ]


def render_rbac(cfg: dict) -> list[dict]:
    """One Role + RoleBinding in each evidenced namespace. Nothing else.

    In v1 that is exactly one namespace, ``kagent-lab``. The loop is kept because
    the shape is per-namespace and stays correct if the evidenced set ever grows —
    but the set, not the loop, is the boundary.

    No cluster-scoped *RBAC* object is ever emitted anywhere in this module (the
    tool server's own ``Namespace`` in ``10-namespace.yaml`` is cluster-scoped and
    intended). A ClusterRoleBinding cannot exclude
    namespaces, so the protected-namespace validation — which iterates the
    explicit list — would not hold for it.

    The ServiceAccount is created by the tool-server Helm release, not here. The
    installer asserts that it exists before applying these bindings, so a chart
    that stops creating it fails loudly instead of silently binding nothing.
    """
    write = _require_write_profile(cfg, "render_rbac")
    rules = build_policy_rules(write["resources"])
    sa_namespace = write["tool_server_namespace"]
    sa_name = write["tool_server_release"]
    subject = {
        "kind": "ServiceAccount",
        "name": sa_name,
        "namespace": sa_namespace,
    }

    objects: list[dict] = []
    for namespace in write["namespaces"]:
        objects.append(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {
                    "name": sa_name,
                    "namespace": namespace,
                    "labels": _labels(),
                },
                "rules": rules,
            }
        )
        objects.append(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {
                    "name": sa_name,
                    "namespace": namespace,
                    "labels": _labels(),
                },
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": sa_name,
                },
                "subjects": [subject],
            }
        )
    return objects


def render_tool_server(cfg: dict) -> list[dict]:
    write = _require_write_profile(cfg, "render_tool_server")
    url = (
        f"http://{write['tool_server_release']}."
        f"{write['tool_server_namespace']}:{write['tool_server_port']}/mcp"
    )
    return [
        {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "RemoteMCPServer",
            "metadata": {
                "name": write["tool_server_release"],
                "namespace": cfg["install_namespace"],
                "labels": _labels(),
            },
            "spec": {
                "description": (
                    "Scoped Kubernetes write tools for the OK-129 access profile "
                    f"({_scope_phrase(write)})."
                ),
                "protocol": "STREAMABLE_HTTP",
                "url": url,
            },
        }
    ]


def _scope_phrase(write: dict) -> str:
    """Prose for the write scope.

    Both branches are live: the singular one is what v1 renders, and the plural
    one keeps this correct if ``EVIDENCED_WRITE_NAMESPACES`` ever grows after a
    drill. It is never reached with an unvalidated list — every caller has passed
    ``_require_renderable_profile`` first.
    """
    namespaces = list(write["namespaces"])
    if len(namespaces) == 1:
        return f"namespace {namespaces[0]}"
    return "namespaces " + ", ".join(namespaces)


def _system_message(cfg: dict) -> str:
    write = _require_write_profile(cfg, "_system_message")
    resources = ", ".join(sorted(write["resources"]))

    allowed = ", ".join(write["namespaces"])
    scope_rules = [
        f"You may operate only in these namespaces: {allowed}.",
        "Never operate in another namespace, even if asked directly.",
    ]

    approval_rule = (
        "The tool approval gate is the confirmation. If a request is "
        "unambiguous, do not ask for a separate confirmation."
    )

    lines = [
        "You diagnose Kubernetes workloads cluster-wide and make small, "
        "reversible configuration changes within a fixed permission boundary.",
        "",
        "Rules:",
    ]
    lines += [f"- {rule}" for rule in scope_rules]
    lines += [
        f"- You may change only these resource kinds: {resources}.",
        "- Never request or access Secrets. Your identity is not granted Secret "
        "permissions; do not try.",
        "- Prefer patching an existing object over replacing it, and prefer the "
        "smallest reversible change.",
        "- Before a write, state the target namespace, kind, name, and the "
        "expected result.",
        f"- {approval_rule}",
        "- If a name, namespace, or value is ambiguous, use ask_user.",
        "- If a tool call is rejected, acknowledge the rejection and do not "
        "retry it or ask for approval again.",
        "- After a write, verify the result with a read tool. If a rollout does "
        "not become healthy, report the evidence and stop instead of making "
        "another speculative change.",
        "- If a tool reports a permission error, stop and report it. Never try "
        "to work around the restriction.",
    ]
    return "\n".join(lines) + "\n"


def render_agent(cfg: dict) -> list[dict]:
    """The write Agent.

    ``requireApproval`` here is a property of *this Agent's reference* to the
    write tool server. It is not a policy of the RemoteMCPServer and not a
    property of the write ServiceAccount: another Agent that references the same
    tool server is not forced to declare it. That is why the ServiceAccount's
    Role, not this field, is the capability boundary.
    """
    write = _require_write_profile(cfg, "render_agent")
    write_tool = {
        "type": "McpServer",
        "mcpServer": {
            "apiGroup": "kagent.dev",
            "kind": "RemoteMCPServer",
            "name": write["tool_server_release"],
            "toolNames": list(write["tools"]),
            "requireApproval": list(write["tools"]),
        },
    }

    return [
        {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "Agent",
            "metadata": {
                "name": write["agent_name"],
                "namespace": cfg["install_namespace"],
                "labels": _labels(
                    {"openkubes.io/access-scope": write["scope"]}
                ),
            },
            "spec": {
                "description": (
                    f"Scoped ConfigMap repairs limited to {_scope_phrase(write)}"
                    " — every write from this Agent needs human approval."
                ),
                "type": "Declarative",
                "declarative": {
                    "runtime": "go",
                    "modelConfig": "default-model-config",
                    "a2aConfig": {},
                    "deployment": {
                        "podSecurityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 1001,
                            "runAsGroup": 1001,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                    },
                    "systemMessage": _system_message(cfg),
                    "tools": [
                        {
                            "type": "McpServer",
                            "mcpServer": {
                                "apiGroup": "kagent.dev",
                                "kind": "RemoteMCPServer",
                                "name": "kagent-tool-server",
                                "toolNames": list(cfg["read"]["tools"]),
                            },
                        },
                        write_tool,
                    ],
                },
            },
        }
    ]


def render_read_values(cfg: dict) -> dict:
    """Helm values fragment that pins the built-in tool server to read-only.

    Guarded like every other public renderer even though the body ignores ``cfg``.
    That the current body happens not to use it is an accident of this
    implementation, not a property the tests or the documentation establish — and
    an unguarded public renderer is how `render_namespace` stayed unguarded for a
    review round.
    """
    _require_renderable_profile(cfg, "render_read_values")
    return {
        "kagent-tools": {
            "enabled": True,
            "tools": {"enabledTools": ["k8s"], "args": ["--read-only"]},
            "rbac": {
                "create": True,
                "readOnly": True,
                "allowSecrets": False,
            },
        }
    }


def render_tools_values(cfg: dict, image_tag: str | None) -> dict:
    """Helm values for the scoped write tool server release.

    ``rbac.create: false`` on purpose: the chart's own RBAC is cluster-wide.
    The scoped Role in ``20-rbac.yaml`` is the whole point of this profile.
    """
    write = _require_write_profile(cfg, "render_tools_values")
    values: dict = {
        "fullnameOverride": write["tool_server_release"],
        "tools": {
            "enabledTools": ["k8s"],
            # The chart otherwise renders tools and metrics on the same container
            # port, which Kubernetes rejects as a duplicate port key. Note the
            # asymmetry: only the metrics port is templated here, which is why
            # write.toolServer.port is pinned to CHART_TOOLS_PORT.
            # int() first: an int subclass such as IntEnum would otherwise
            # stringify to its member name.
            "metrics": {"port": str(int(write["tool_server_metrics_port"]))},
        },
        "rbac": {"create": False},
        "podSecurityContext": {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    if image_tag is not None:
        # Straight into a Helm values file, so it has to be a plain tag: a
        # multi-line string would become a block scalar and could add sibling keys.
        if not isinstance(image_tag, str) or not IMAGE_TAG.fullmatch(image_tag):
            raise ConfigError(
                f"render_tools_values: image tag {image_tag!r} is not a valid "
                "container image tag."
            )
        values["tools"]["image"] = {"tag": image_tag}
    return values


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


def render_summary(cfg: dict, config_path: Path) -> str:
    # Before the mode branch, not inside it: the read-only summary asserts that no
    # write path exists, which is a claim about the profile and must be validated
    # even when nothing is rendered for the write path.
    _require_renderable_profile(cfg, "render_summary")
    read_tools = ", ".join(f"`{t}`" for t in cfg["read"]["tools"])
    lines = [
        "# Access profile summary",
        "",
        # Escaped: the filename is caller-supplied, and an unescaped one could
        # inject headings into the one document whose purpose is to be the
        # reviewable statement of the boundary.
        f"Generated from `{_inline_code(config_path.name)}`. Regenerate after every",
        "change; do",
        "not hand-edit the manifests.",
        "",
        f"**Mode:** `{cfg['mode']}`",
        "",
        "## Read path (always on)",
        "",
        "| Property | Value |",
        "|---|---|",
        "| Identity | the tool server ServiceAccount created by the kagent chart |",
        "| Scope | cluster-wide **read** |",
        "| Secrets | no Secret permission is granted — `allowSecrets: false` |",
        "| Writes | denied by RBAC, not only by prompt |",
        f"| Tools exposed | {read_tools} |",
        "",
        "`Tools exposed` is the list this profile puts on a generated Agent's tool",
        "reference. It is not a server-side restriction: the chart's tool server",
        "runs `enabledTools: [k8s]`, i.e. the whole Kubernetes tool set, and any",
        "Agent may reference any of them. In `read-only` mode no Agent is generated",
        "here at all, so nothing in this profile narrows the read tools — the read",
        "identity's RBAC is what bounds them.",
        "",
    ]

    if not _is_read_write(cfg):
        lines += [
            "## Write path",
            "",
            "Not deployed. No write ServiceAccount, no Role, no write tool server,",
            "and no write Agent exist in this profile. Switching the mode back to",
            "`read-only` removes them again rather than orphaning them.",
            "",
        ]
        return "\n".join(lines)

    write = _require_write_profile(cfg, "render_summary")
    rules = build_policy_rules(write["resources"])

    namespace_list = ", ".join(f"`{ns}`" for ns in write["namespaces"])
    rbac_objects = f"Role + RoleBinding in {namespace_list} — no cluster-scoped object"

    lines += [
        "## Write path",
        "",
        "| Property | Value |",
        "|---|---|",
        f"| Identity | `system:serviceaccount:{write['tool_server_namespace']}:{write['tool_server_release']}` |",
        f"| Scope | {_scope_phrase(write)} |",
        f"| RBAC objects | {rbac_objects} |",
        f"| Approval gate | on the generated Agent `{write['agent_name']}` — see below |",
        "| Secrets | no Secret permission is granted in any generated rule |",
        f"| Write tools | {', '.join(f'`{t}`' for t in write['tools'])} |",
        f"| Agent | `{write['agent_name']}` in `{cfg['install_namespace']}` |",
        "",
        "### Effective permissions",
        "",
        "| apiGroup | Resources | Verbs |",
        "|---|---|---|",
    ]
    for rule in rules:
        group = rule["apiGroups"][0] or "core"
        lines.append(
            f"| `{group}` | {', '.join(rule['resources'])} | {', '.join(rule['verbs'])} |"
        )

    targets = list(write["namespaces"])
    lines += [
        "",
        "### What this profile does not grant",
        "",
        "Stated as permissions, not as outcomes — the table above is what the API",
        "server enforces:",
        "",
        "- **no Secret permission**, read or write, in any generated rule;",
        "- **no direct RBAC API permission**: Roles, RoleBindings, ClusterRoles,",
        "  ClusterRoleBindings and ServiceAccounts appear in no rule;",
        "- no Namespace, Node, PersistentVolume, CRD or webhook permission;",
        f"- no permission in any namespace other than {namespace_list} — RBAC",
        "  denies it, the prompt is not the boundary;",
        "- no permission in the kagent install namespace, so the identity cannot",
        "  rewrite its own Agent or tool definitions;",
        "- no permission of any kind — not even `get` — on workload controllers",
        "  (Deployments, StatefulSets, DaemonSets, ReplicaSets, Jobs, CronJobs), on",
        "  Services, or on Ingresses. Those are candidate work and this renderer",
        "  refuses them; the read identity is what reads them.",
        "- no Pod *mutation* of any kind, including deletion. Pods, Pod logs and",
        f"  Events are readable in {namespace_list} — that is the write",
        "  identity's verification context, and it is in the table above.",
        "",
        "### Two limits of these guarantees",
        "",
        "1. **The approval gate is an Agent-level policy, not a server-side one.**",
        f"   `requireApproval` is set on `{write['agent_name']}`'s reference to the",
        "   write tool server. Neither the shared `RemoteMCPServer` nor the write",
        "   ServiceAccount enforces it: another Agent in the cluster may reference",
        "   the same tool server without declaring approval, and nothing upstream",
        "   prevents that. Precisely: *the generated Agent is approval-gated; the",
        "   shared write tool server and its Kubernetes identity are not.* Making",
        "   approval a hard capability boundary requires enforcement in the tool",
        "   server or another server-side authorization mechanism.",
        "2. **Withholding a verb is not proof that no indirect path exists.** It is",
        "   accurate that no *direct* Secret or RBAC API permission is granted. It",
        "   would not be accurate to conclude from that alone that no escalation is",
        "   reachable in a wider profile: pod-template mutation on a Deployment,",
        "   StatefulSet, DaemonSet or Job can reach existing Secrets or a more",
        "   privileged ServiceAccount in the same namespace, without ever calling",
        "   the Secret API. RBAC alone does not prevent it — admission control does.",
        "   That is one reason workload write is refused here.",
        "",
        "Verify, do not trust this table:",
        "",
        "```bash",
        f"SUBJECT='system:serviceaccount:{write['tool_server_namespace']}:{write['tool_server_release']}'",
        "kubectl auth can-i get secrets --all-namespaces --as=\"$SUBJECT\"   # expect no",
        "kubectl auth can-i '*' '*' --all-namespaces --as=\"$SUBJECT\"       # expect no",
    ]
    # Every target, not only the first: a block that checks one namespace of
    # several would under-report the moment the evidenced set grows.
    for target in targets:
        lines += [
            f"kubectl auth can-i patch configmaps -n {target} --as=\"$SUBJECT\"    # expect yes",
            f"kubectl auth can-i patch deployments -n {target} --as=\"$SUBJECT\"   # expect no",
            f"kubectl auth can-i get deployments -n {target} --as=\"$SUBJECT\"     # expect no",
        ]
    lines += [
        # 'default' is refused as a write target, so it is always a valid
        # negative control here.
        "kubectl auth can-i patch configmaps -n default --as=\"$SUBJECT\"     # expect no",
        "```",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


class _BlockDumper(yaml.SafeDumper):
    """SafeDumper that renders multi-line strings as literal blocks.

    Without this, a generated system prompt comes out as a folded single-quoted
    scalar — valid YAML that no human wants to review. These manifests exist to
    be read before they are applied, so readability is a requirement.
    """


def _represent_str(dumper: yaml.Dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_BlockDumper.add_representer(str, _represent_str)


def _dump(objects: list[dict]) -> str:
    return GENERATED_HEADER + yaml.dump_all(
        objects, Dumper=_BlockDumper, default_flow_style=False, sort_keys=False
    )


def _dump_values(values: dict) -> str:
    return GENERATED_HEADER + yaml.dump(
        values, Dumper=_BlockDumper, default_flow_style=False, sort_keys=False
    )


def render_profile_env(cfg: dict) -> str:
    """Shell-sourceable facts about the profile, for the installer.

    The installer must assert the same boundary the renderer generated. Deriving
    that from this file instead of re-parsing YAML in Make keeps one source of
    truth and keeps the Makefile portable.
    """
    _require_renderable_profile(cfg, "render_profile_env")
    write = cfg["write"]
    lines = [
        "# Generated by render-access.py — source, do not edit.",
        f"KAGENT_ACCESS_MODE='{cfg['mode']}'",
        f"KAGENT_INSTALL_NAMESPACE='{cfg['install_namespace']}'",
    ]
    if write:
        # Every value here has passed _require_renderable_profile in this same
        # call — DNS label, object name, tool name or literal — and every one is
        # single-quoted. Both halves matter: this file is sourced by the installer,
        # so a value that skipped validation would be command execution rather than
        # a broken manifest. Validation used to live only in load_config, which
        # made that guarantee true for callers of load_config instead of true of
        # this function.
        lines += [
            f"KAGENT_WRITE_SCOPE='{write['scope']}'",
            "KAGENT_WRITE_NAMESPACES='" + " ".join(write["namespaces"]) + "'",
            f"KAGENT_WRITE_SA_NAMESPACE='{write['tool_server_namespace']}'",
            f"KAGENT_WRITE_SA_NAME='{write['tool_server_release']}'",
            f"KAGENT_WRITE_RELEASE='{write['tool_server_release']}'",
            f"KAGENT_WRITE_AGENT='{write['agent_name']}'",
            # Constant in v1 — an ungated profile is refused at validation time.
            # Kept as a variable so the installer's assertions stay written the
            # same way if a gated/ungated distinction ever returns.
            "KAGENT_WRITE_REQUIRE_APPROVAL='true'",
            "KAGENT_WRITE_RESOURCES='" + " ".join(sorted(write["resources"])) + "'",
        ]
    else:
        lines += [
            "KAGENT_WRITE_SCOPE=''",
            "KAGENT_WRITE_NAMESPACES=''",
            "KAGENT_WRITE_SA_NAMESPACE=''",
            "KAGENT_WRITE_SA_NAME=''",
            "KAGENT_WRITE_RELEASE=''",
            "KAGENT_WRITE_AGENT=''",
            "KAGENT_WRITE_REQUIRE_APPROVAL=''",
            "KAGENT_WRITE_RESOURCES=''",
        ]
    return "\n".join(lines) + "\n"


def write_outputs(cfg: dict, out_dir: Path, config_path: Path, image_tag: str | None) -> list[Path]:
    # Before anything reads cfg, so a malformed config is a ConfigError rather than
    # a KeyError from _is_read_write.
    _require_renderable_profile(cfg, "write_outputs")
    # Render everything in memory before touching the filesystem. Emitting as we
    # go meant a refusal part-way through left `values-access.yaml` and
    # `10-namespace.yaml` on disk next to a stale `profile.env` and `SUMMARY.md`
    # describing RBAC that had just been deleted — the precise "stale output from a
    # wider profile" failure the directory clearing below exists to prevent.
    payload: list[tuple[Path, str]] = [
        (out_dir / "values-access.yaml", _dump_values(render_read_values(cfg)))
    ]
    if _is_read_write(cfg):
        payload += [
            (out_dir / "manifests" / "10-namespace.yaml", _dump(render_namespace(cfg))),
            (out_dir / "manifests" / "20-rbac.yaml", _dump(render_rbac(cfg))),
            (out_dir / "manifests" / "30-tool-server.yaml", _dump(render_tool_server(cfg))),
            (out_dir / "manifests" / "40-agent.yaml", _dump(render_agent(cfg))),
            (out_dir / "tools-values.yaml", _dump_values(render_tools_values(cfg, image_tag))),
        ]
    payload += [
        (out_dir / "profile.env", render_profile_env(cfg)),
        (out_dir / "SUMMARY.md", render_summary(cfg, config_path)),
    ]

    manifests_dir = out_dir / "manifests"
    # A stale manifest from a previous, wider profile is a security bug, not
    # clutter: clear the directory before writing.
    if manifests_dir.exists():
        # Every file, not only *.yaml: the documented promise is that the directory
        # holds nothing from a previous profile, and `kubectl apply -f manifests/`
        # picks up .yml and .json too.
        for stale in sorted(p for p in manifests_dir.iterdir() if p.is_file()):
            stale.unlink()
    # Only keep manifests/ when there is something to put in it: the runbook tells
    # an operator to `kubectl apply -f manifests/`, and an empty directory makes
    # that error instead of being a no-op — which reads like a broken install
    # rather than a read-only profile.
    out_dir.mkdir(parents=True, exist_ok=True)
    if _is_read_write(cfg):
        manifests_dir.mkdir(parents=True, exist_ok=True)
    elif manifests_dir.exists() and not any(manifests_dir.iterdir()):
        manifests_dir.rmdir()

    written: list[Path] = []
    for path, content in payload:
        path.write_text(content, encoding="utf-8")
        written.append(path)

    if not _is_read_write(cfg):
        # Leave no usable write values behind in a read-only profile.
        stale_values = out_dir / "tools-values.yaml"
        if stale_values.exists():
            stale_values.unlink()

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the kagent standalone access profile (OK-129)."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--tools-image-tag",
        default=None,
        help="Image tag for the scoped write tool server. Pass the pinned "
        "version from the installer so it is not duplicated here.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print the profile summary to stdout as well.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-file output and the parked-write-block note. "
        "Refusals are errors, not warnings, so nothing about the boundary can be "
        "silenced by this flag.",
    )
    args = parser.parse_args(argv)

    # Both calls inside the handler. The render path re-validates, so it can raise
    # ConfigError too — and a ConfigError there is still a config problem for the
    # operator, not a bug worth a traceback.
    try:
        cfg = load_config(args.config, quiet=args.quiet)
        written = write_outputs(cfg, args.out, args.config, args.tools_image_tag)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"access profile: mode={cfg['mode']}", end="")
        if cfg["write"]:
            print(f", write scope={_scope_phrase(cfg['write'])} [approval-gated]", end="")
        print()
        for path in written:
            print(f"  wrote {path}")

    if args.summary:
        print()
        print((args.out / "SUMMARY.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
