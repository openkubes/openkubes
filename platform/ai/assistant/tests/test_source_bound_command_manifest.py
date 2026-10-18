import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_beta.source_bound_command_manifest import source_bound_command_manifest

REV = "d" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
F = chr(96) * 3


def make_index(*, omit=None, extra_fences=0):
    corpus = []
    titles = ["Overview", "Prerequisites"] + [
        f"Step {n} — Example" for n in range(1, 9) if n != omit
    ]
    for n, title in enumerate(titles):
        num = int(title.split()[1]) if title.startswith("Step ") else 0
        lines = F + "bash\n" + "echo step\n" + F + "\n"
        if num == 3 and extra_fences:
            lines *= extra_fences
        text = ("intro\n" + lines) if num else "intro"
        sid = hashlib.sha256(f"{REPO}:{REV}:{PATH}:{n}".encode()).hexdigest()[:16]
        corpus.append({
            "source_id": sid, "repo": REPO, "path": PATH, "revision": REV,
            "chunk_number": n, "section": title,
            "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
            "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text
        })
    return {"schema_version": 1, "corpus": corpus}


def hits(index):
    return {"results": [{
        "source_id": doc["source_id"], "title": doc["section"],
        "repo": doc["repo"], "path": doc["path"],
        "commit_sha": doc["revision"], "url": doc["url"],
        "snippet": doc["text"]
    } for doc in index["corpus"][:2]]}


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.index = make_index()
        self.hits = hits(self.index)

    def test_source_hash_and_no_executable_text(self):
        result = source_bound_command_manifest(self.hits, self.index, step=3)
        self.assertEqual(result["status"], "MANIFEST_ONLY")
        self.assertEqual(result["command_block_count"], 1)
        block = result["blocks"][0]
        self.assertEqual(block["sha256"], hashlib.sha256(b"echo step\n").hexdigest())
        self.assertEqual(block["revision"], REV)
        self.assertEqual(block["line_count"], 1)
        self.assertFalse(result["display_authorized"])
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("echo step", str(result))

    def test_rejects_modified_anchor(self):
        changed = hits(self.index)
        changed["results"][0]["snippet"] = "forged"
        with self.assertRaises(ValueError):
            source_bound_command_manifest(changed, self.index, step=3)

    def test_rejects_missing_tutorial_step(self):
        index = make_index(omit=7)
        with self.assertRaises(ValueError):
            source_bound_command_manifest(hits(index), index, step=3)

    def test_rejects_non_integer_and_out_of_range_steps(self):
        for bad in (True, 0, 9, "1", 1.0):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                source_bound_command_manifest(self.hits, self.index, step=bad)

    def test_rejects_more_than_sixteen_fences_per_step(self):
        index = make_index(extra_fences=17)
        with self.assertRaises(ValueError):
            source_bound_command_manifest(hits(index), index, step=3)

    def test_source_change_invalidates_checksum(self):
        index = make_index()
        index["corpus"][4]["text"] += "changed"
        with self.assertRaises(ValueError):
            source_bound_command_manifest(hits(index), index, step=3)

    def test_zero_fence_step(self):
        index = make_index()
        index["corpus"][4]["text"] = "intro only"
        index["corpus"][4]["sha256"] = hashlib.sha256(b"intro only").hexdigest()
        result = source_bound_command_manifest(hits(index), index, step=3)
        self.assertEqual(result["command_block_count"], 0)
        self.assertEqual(result["blocks"], [])


if __name__ == "__main__":
    unittest.main()
