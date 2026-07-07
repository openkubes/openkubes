#!/usr/bin/env python3
"""
okgraph — Knowledge Graph for OpenKubes (Immortal Mind, Layer 1).

The graph is a *derived projection* of Git. It owns nothing; it can be
destroyed and rebuilt from source at any time (same reconciliation model
as an OpenKubes cluster).

Sources:
  - ADRs in architecture/decisions/  (header-table or heuristic extraction)
  - git log (commits referencing ADRs / Jira issues / 'state:' prefix)
  - Jira issue keys (OK-nn) found in ADRs and commit messages

Usage:
  python3 okgraph.py build [repo_path]      # writes knowledge-graph.json
  python3 okgraph.py why <component>        # decisions governing a component
  python3 okgraph.py history <node-id>     # commits + issues behind a node
  python3 okgraph.py neighbors <node-id>   # everything directly connected
  python3 okgraph.py stats                 # graph summary
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import networkx as nx

GRAPH_FILE = "knowledge-graph.json"
ADR_DIR = "architecture/decisions"

# Seed vocabulary: components & capabilities the extractor recognizes in text.
COMPONENTS = [
    "Talos", "RKE2", "KubeVirt", "CDI", "MetalLB", "Cilium", "Traefik",
    "Crossplane", "CAPI", "CAPK", "Longhorn", "Ceph", "NFS", "Argo CD",
    "Multus", "WireGuard", "Ollama", "Open WebUI", "Hetzner", "Kamaji",
    "ingress-nginx", "containerd", "Kubernetes",
]
CAPABILITIES = [
    ("ok-linux", "Host OS"),
    ("ok-cluster", "Cluster Lifecycle"),
    ("ok-storage", "Storage"),
    ("ok-gitops", "GitOps"),
    ("ok-apps", "Applications"),
]
ISSUE_RE = re.compile(r"\bOK-\d+\b")
ADR_REF_RE = re.compile(r"\bADR(?:-Platform)?-\d{3}\b")


def sh(cmd, cwd):
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                          text=True).stdout


def adr_meta(text):
    """Extract Status/Date from either '**Status:** X' or table '| **Status** | X |'."""
    meta = {}
    for key in ("Status", "Date"):
        m = re.search(rf"\*\*{key}:?\*\*\s*[:|]?\s*\|?\s*([^\n|]+)", text)
        if m:
            meta[key.lower()] = m.group(1).strip()
    return meta


def build(repo):
    repo = Path(repo).resolve()
    G = nx.MultiDiGraph()

    # Capabilities
    for cap, label in CAPABILITIES:
        G.add_node(cap, type="capability", label=f"{cap} ({label})")

    # ADRs
    adr_dir = repo / ADR_DIR
    adr_texts = {}
    for f in sorted(adr_dir.glob("ADR-*.md")):
        text = f.read_text(errors="replace")
        m = re.match(r"ADR(?:-Platform)?-\d{3}", f.name)
        adr_id = f.stem.split("-")[0:3]
        adr_id = m.group(0) if m else f.stem
        title_m = re.search(r"^#\s*(.+)$", text, re.M)
        meta = adr_meta(text)
        G.add_node(adr_id, type="adr", label=adr_id,
                   title=(title_m.group(1).strip() if title_m else f.stem),
                   file=str(f.relative_to(repo)),
                   status=meta.get("status", "?"), date=meta.get("date", "?"))
        adr_texts[adr_id] = text

    # ADR -> component / capability / issue / ADR references
    for adr_id, text in adr_texts.items():
        for comp in COMPONENTS:
            if re.search(rf"\b{re.escape(comp)}\b", text):
                if comp not in G:
                    G.add_node(comp, type="component", label=comp)
                G.add_edge(adr_id, comp, rel="governs")
        for cap, _ in CAPABILITIES:
            if cap in text:
                G.add_edge(adr_id, cap, rel="defines")
        for iss in set(ISSUE_RE.findall(text)):
            if iss not in G:
                G.add_node(iss, type="issue", label=iss,
                           url=f"https://kubernauts.atlassian.net/browse/{iss}")
            G.add_edge(adr_id, iss, rel="tracked-by")
        for ref in set(ADR_REF_RE.findall(text)) - {adr_id}:
            if ref in adr_texts:
                G.add_edge(adr_id, ref, rel="references")

    # Commits
    log = sh("git log --pretty=format:'%h|%ad|%s' --date=short", repo)
    for line in log.splitlines():
        try:
            h, date, msg = line.split("|", 2)
        except ValueError:
            continue
        refs = set(ADR_REF_RE.findall(msg)) | set(ISSUE_RE.findall(msg))
        is_state = msg.startswith("state:")
        if not refs and not is_state:
            continue
        cid = f"commit:{h}"
        G.add_node(cid, type="cluster-state" if is_state else "commit",
                   label=h, message=msg, date=date)
        for r in refs:
            if r in G:
                G.add_edge(cid, r, rel="implements")

    data = nx.node_link_data(G, edges="links")
    out = Path.cwd() / GRAPH_FILE
    out.write_text(json.dumps(data, indent=1))
    print(f"✅ {out}: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    by_type = {}
    for _, d in G.nodes(data=True):
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"   {t:14s} {n}")
    return G


def load():
    data = json.loads(Path(GRAPH_FILE).read_text())
    return nx.node_link_graph(data, edges="links", multigraph=True, directed=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "build":
        build(sys.argv[2] if len(sys.argv) > 2 else ".")
        return
    G = load()
    if cmd == "stats":
        print(f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    elif cmd == "why":
        target = sys.argv[2]
        for u, v, d in G.edges(data=True):
            if v.lower() == target.lower() and d["rel"] in ("governs", "defines"):
                n = G.nodes[u]
                print(f"{u} [{n.get('status','?')}] — {n.get('title','')}")
    elif cmd in ("history", "neighbors"):
        node = sys.argv[2]
        for u, v, d in G.edges(data=True):
            if node in (u, v):
                other = v if u == node else u
                nd = G.nodes[other]
                extra = nd.get("message", nd.get("title", ""))
                print(f"{d['rel']:12s} {other:20s} {extra}")


if __name__ == "__main__":
    main()
