"""Offline tests for pinned same-revision installation sequence metadata."""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs_mcp import DocsRetriever
from public_beta.source_bound_install_plan import source_bound_install_plan

REV = "c" * 40
OTHER_REV = "d" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"


def doc(n, section, *, revision=REV, repo=REPO, path=PATH):
    text = "Documented source section " + section
    sid = hashlib.sha256(f"{repo}:{revision}:{path}:{n}".encode()).hexdigest()[:16]
    return {
        "source_id": sid, "repo": repo, "path": path,
        "revision": revision, "chunk_number": n, "section": section,
        "url": f"https://github.com/{repo}/blob/{revision}/{path}",
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text,
    }


def index_of(sections):
    return {"schema_version": 1, "corpus": [
        doc(n, title) for n, title in enumerate(sections)
    ]}


def retrieval(index):
    return {"results": [{
        "source_id": d["source_id"], "title": d["section"],
        "repo": d["repo"], "path": d["path"],
        "commit_sha": d["revision"], "url": d["url"],
        "snippet": d["text"],
    } for d in index["corpus"][:2]]}


class SourceBoundPlanTests(unittest.TestCase):
    def setUp(self):
        self.sections = ["KubeVirt on macOS with Multipass", "Prerequisites"] + [
            f"Step {n} — Install component {n}" for n in range(1, 9)
        ]
        self.index = index_of(self.sections)

    def test_follows_index_beyond_eight_hit_limit(self):
        result = source_bound_install_plan(retrieval(self.index), self.index)
        self.assertEqual(result["status"], "SOURCE_SEQUENCE_FOUND")
        self.assertEqual(result["present_steps"], list(range(1, 9)))
        self.assertEqual(len(result["steps"]), 8)
        self.assertTrue(all(s["source_ids"] for s in result["steps"]))
        self.assertFalse(result["display_authorized"])
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("Documented source section", str(result))

    def test_missing_step_fail_closed(self):
        index = index_of([s for s in self.sections if not s.startswith("Step 6 ")])
        result = source_bound_install_plan(retrieval(index), index)
        self.assertEqual(result["status"], "INCOMPLETE_SEQUENCE")
        self.assertEqual(result["steps"][5]["source_ids"], [])
        self.assertFalse(result["display_authorized"])

    def test_duplicate_chunk_same_heading_is_allowed(self):
        sections = self.sections[:4] + [self.sections[3]] + self.sections[4:]
        index = index_of(sections)
        result = source_bound_install_plan(retrieval(index), index)
        self.assertEqual(result["status"], "SOURCE_SEQUENCE_FOUND")
        self.assertEqual(len(result["steps"][1]["source_ids"]), 2)

    def test_out_of_order_steps_rejected(self):
        index = index_of(self.sections[:4] + [self.sections[5], self.sections[4]] +
                         self.sections[6:])
        with self.assertRaises(ValueError):
            source_bound_install_plan(retrieval(index), index)

    def test_forged_hit_rejected(self):
        hits = retrieval(self.index)
        hits["results"][0]["snippet"] = "forged"
        with self.assertRaises(ValueError):
            source_bound_install_plan(hits, self.index)

    def test_missing_anchor(self):
        other = index_of(["Unrelated page"])
        other["corpus"][0] = doc(0, "Unrelated page", path="docs/tutorial-capi.md")
        result = source_bound_install_plan(retrieval(other), other)
        self.assertEqual(result["status"], "NO_GUIDE_ANCHOR")
        self.assertFalse(result["display_authorized"])

    def test_mixed_revisions_rejected(self):
        index = index_of(self.sections)
        index["corpus"][-1] = doc(9, "Step 8 — Install component 8",
                                    revision=OTHER_REV)
        with self.assertRaises(ValueError):
            source_bound_install_plan(retrieval(index), index)

    def test_no_network_or_model_inputs_and_empty_hits_rejected(self):
        with self.assertRaises(ValueError):
            source_bound_install_plan({"results": []}, self.index)


if __name__ == "__main__":
    unittest.main()
