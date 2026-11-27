import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "website/scripts"))
from knowledge_graph_preview import render_preview

class GraphPreviewTest(unittest.TestCase):
    def test_svg_contains_only_public_graph_geometry(self):
        template = (ROOT / "website/pages/knowledge-graph/brain-preview.svg").read_text()
        data = {"nodes": [
            {"id":"a", "type":"adr"},
            {"id":"b", "type":"component"},
            {"id":"c", "type":"commit", "message":"not public"}
        ], "links":[{"source":"a","target":"b"},{"source":"a","target":"c"}]}
        svg = render_preview(data, template)
        self.assertEqual(svg, render_preview(data, template))
        root = ET.fromstring(svg)
        ns = {"s":"http://www.w3.org/2000/svg"}
        self.assertEqual(len(root.findall("s:line", ns)), 1)
        self.assertEqual(len(root.findall("s:circle", ns)), 2)
        self.assertNotIn("not public", svg)
        self.assertNotIn("<script", svg)
        self.assertNotIn("GRAPH_EDGES", svg)
        self.assertNotIn("GRAPH_NODES", svg)

if __name__ == "__main__":
    unittest.main()
