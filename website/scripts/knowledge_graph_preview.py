"""Render a static SVG from the same public graph used by the explorer."""
from collections import defaultdict
from math import cos, sin, sqrt
from pathlib import Path

ZONES = {
    "adr": (325, 205, 105, 80, "#2e75cf", 4.5),
    "capability": (205, 145, 65, 45, "#e58a18", 5.5),
    "component": (495, 195, 90, 70, "#21966a", 3.5),
    "issue": (175, 300, 85, 65, "#a94e9b", 3),
}

def render_preview(data, template):
    groups = defaultdict(list)
    for node in data["nodes"]:
        if node["type"] in ZONES:
            groups[node["type"]].append(node)
    positions = {}
    dots = []
    for kind, nodes in sorted(groups.items()):
        cx, cy, rx, ry, color, radius = ZONES[kind]
        for i, node in enumerate(sorted(nodes, key=lambda n: n["id"])):
            angle = i * 2.39996323
            radial = sqrt((i + .5) / len(nodes))
            x, y = cx + cos(angle)*rx*radial, cy + sin(angle)*ry*radial
            positions[node["id"]] = (x, y)
            dots.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{color}" stroke="white" stroke-width="1"/>')
    edges = []
    for edge in data["links"]:
        a, b = positions.get(edge["source"]), positions.get(edge["target"])
        if a is not None and b is not None:
            edges.append(f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="#8ea4bf" stroke-opacity=".25" stroke-width=".7"/>')
    for marker in ("<!-- GRAPH_EDGES -->", "<!-- GRAPH_NODES -->"):
        if template.count(marker) != 1:
            raise ValueError("Missing unique SVG marker: " + marker)
    return template.replace("<!-- GRAPH_EDGES -->", "\n".join(edges)).replace("<!-- GRAPH_NODES -->", "\n".join(dots))
