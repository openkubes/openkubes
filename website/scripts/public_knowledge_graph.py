"""Build a conservative public graph from the checked-out public Git sources."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import os
from knowledge_graph_preview import render_preview

ROOT = Path(__file__).resolve().parents[2]

def stage_public_graph(target):
    source = ROOT / "docs"
    dest = target / "knowledge-graph"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "website/pages/knowledge-graph/index.md", dest / "index.md")
    spec = importlib.util.spec_from_file_location("okgraph", source / "okgraph.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temp:
        try:
            os.chdir(temp)
            graph = module.build(ROOT)
        finally:
            os.chdir(previous)
    # Explicit public projection: no commit subjects, state snapshots or arbitrary URLs.
    allowed = {"adr", "component", "capability", "issue"}
    public = graph.subgraph([n for n, d in graph.nodes(data=True) if d["type"] in allowed])
    data = module.nx.node_link_data(public, edges="links")
    fields = {"id", "type", "label", "title", "file", "status", "date"}
    data["nodes"] = [{k: v for k, v in n.items() if k in fields} for n in data["nodes"]]
    data["links"] = [{k: v for k, v in l.items() if k in {"source", "target", "key", "rel"}} for l in data["links"]]
    template = (source / "knowledge-graph-template.html").read_text(encoding="utf-8")
    marker = "/*__GRAPH_DATA__*/"
    if template.count(marker) != 1:
        raise ValueError("Expected exactly one graph data marker")
    payload = json.dumps(data, ensure_ascii=True).replace("<", r"\u003c")
    html = template.replace(marker, payload)
    html = html.replace("Engineering timeline", "Engineering timeline (local view only)")
    html = html.replace("Dated commits in the current view (latest 20).", "Commit history is excluded from this public projection pending publication review.")
    (dest / "viewer.html").write_text(html, encoding="utf-8")
    preview_template = (ROOT / "website/pages/knowledge-graph/brain-preview.svg").read_text(encoding="utf-8")
    (dest / "brain-preview.svg").write_text(render_preview(data, preview_template), encoding="utf-8")
    vendor = dest / "vendor"
    vendor.mkdir(exist_ok=True)
    for name in ("d3.v7.min.js", "D3-LICENSE.txt"):
        shutil.copy2(source / "vendor" / name, vendor / name)
    print(f"Staged public graph: {len(data['nodes'])} nodes, {len(data['links'])} edges")
