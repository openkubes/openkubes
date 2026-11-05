"""Offline-only display of whole, verified documentation shell fences.

No LLM-selected source IDs, executable access, network I/O, or deployment.
An explicit gateway-selected source_id must come from same-request retrieval.
Conservative policy: ambiguous or potentially dangerous shell is refused.
"""
from __future__ import annotations

import re

from docs_mcp import validate_index
from public_beta.structured_answer import ContractRejected

FENCE = re.compile(r"(?m)^```(bash|sh)\n([^`]*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
# This allowlist is intentionally narrow. Docs provenance never implies safety.
SAFE = re.compile(r"^[A-Za-z0-9_./:=@+%, \t\\-]+$")
COMMANDS = {"kubectl", "helm", "multipass", "git"}
BLOCKED = re.compile(r"(?:\bsudo\b|\brm\b|\bcurl\b|\bwget\b|\bssh\b|\bscp\b|\bdd\b|\bmkfs\b|\bchmod\b|\bchown\b|\beval\b|\bexec\b|\bdelete\b|\bdrain\b|\breset\b|\bupgrade\b|\binstall\b|\buninstall\b|\bcreate\b|\bapply\b|\bpatch\b|\bscale\b|\brollout\b|\bsecrets?\b|token|password|key=)", re.I)


def render_source_commands(retrieval: dict, index: dict, source_id: str) -> str:
    """Return a bounded *reference-only* Markdown block, never execute it.

    source_id must be selected by trusted gateway logic, not by an LLM or
    untrusted browser input. A returned block is not endorsed for execution.
    """
    try:
        docs = {d["source_id"]: d for d in validate_index(index)["corpus"]}
        hits = retrieval["results"]
        if not isinstance(hits, list) or not 1 <= len(hits) <= 8:
            raise ValueError()
        if not isinstance(source_id, str) or source_id not in docs:
            raise ValueError()
        seen = set()
        for hit in hits:
            if not isinstance(hit, dict):
                raise ValueError()
            sid = hit.get("source_id")
            if sid in seen or sid not in docs:
                raise ValueError()
            seen.add(sid)
            doc = docs[sid]
            if any(hit.get(field) != value for field, value in (
                ("snippet", doc["text"]), ("url", doc["url"]),
                ("repo", doc["repo"]), ("path", doc["path"]),
                ("commit_sha", doc["revision"]), ("title", doc["section"])
            )):
                raise ValueError()
        if source_id not in seen:
            raise ValueError()
        doc = docs[source_id]
        text = doc["text"]
        if text.count("```") != len(list(FENCE.finditer(text))) * 2:
            raise ValueError()
        blocks = FENCE.findall(text)
        if not 1 <= len(blocks) <= 2:
            raise ValueError()
        rendered = []
        for language, commands in blocks:
            if len(commands) > 600 or not commands.endswith("\n"):
                raise ValueError()
            lines = commands.splitlines()
            if not 1 <= len(lines) <= 6:
                raise ValueError()
            for line in lines:
                if not line or len(line) > 140 or not SAFE.fullmatch(line) or BLOCKED.search(line):
                    raise ValueError()
                # v0.2: permit only exact, argument-free, non-mutating forms.
                # Subcommand-level allowlists are insufficient: e.g.
                # "kubectl config set-context" mutates kubeconfig.
                allowed_lines = {
                    "kubectl get pods",
                    "kubectl get nodes",
                    "kubectl get namespaces",
                    "kubectl version",
                    "kubectl config current-context",
                    "helm list",
                    "helm version",
                    "multipass list",
                    "multipass version",
                    "git status",
                    "git log",
                    "git version",
                }
                if line != line.strip() or line not in allowed_lines:
                    raise ValueError()
            rendered.append("```" + language + "\n" + commands + "```")
        return ("Documented reference only — not executed or verified safe for your environment.\n\n"
                + "\n\n".join(rendered) + "\n\n[Source](" + doc["url"] + ")")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ContractRejected("untrusted_or_unsupported_command_block") from None
