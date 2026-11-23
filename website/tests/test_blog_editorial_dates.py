"""Tests for Git-backed blog dates, with no external network dependency."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "blog_editorial_dates.py"
spec = importlib.util.spec_from_file_location("blog_editorial_dates", SCRIPT)
assert spec is not None and spec.loader is not None
dates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dates)


class BlogDatesTests(unittest.TestCase):
    def test_dates_appear_immediately_after_h1(self):
        source = "---\ntitle: Example\n---\n\n# Example\n\n*Intro*\n"
        output = dates.add_editorial_dates(source, "2026-01-02", "2026-02-03")
        self.assertIn('# Example\n\n<p class="ok-editorial-dates">', output)
        self.assertIn('datetime="2026-01-02"', output)
        self.assertIn('datetime="2026-02-03"', output)
        self.assertIn("*Intro*", output)

    def test_explicit_frontmatter_is_preferred(self):
        source = '---\ntitle: Example\npublished: "2025-01-02"\nupdated: 2026-11-23\n---\n# Example'
        self.assertEqual(dates.overrides(source), {"published": "2025-01-02", "updated": "2026-11-23"})

    def test_invalid_dates_and_missing_heading_fail_closed(self):
        with self.assertRaises(ValueError):
            dates.add_editorial_dates("# Example", "2026-02-30", "2026-03-01")
        with self.assertRaises(ValueError):
            dates.add_editorial_dates("# Example", "2026-03-01", "2026-02-01")
        with self.assertRaises(ValueError):
            dates.add_editorial_dates("not a heading", "2026-02-01", "2026-02-02")
        with self.assertRaises(ValueError):
            dates.add_editorial_dates(
                '# Example\n<p class="ok-editorial-dates"></p>',
                "2026-02-01", "2026-02-02",
            )

    def test_first_and_last_git_commit_are_stable(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            def git(*args, date_value=None):
                env = None
                if date_value:
                    import os
                    env = dict(os.environ)
                    env.update(GIT_AUTHOR_DATE=date_value + "T12:00:00+0000",
                               GIT_COMMITTER_DATE=date_value + "T12:00:00+0000")
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)
            git("init", "-q")
            git("config", "user.email", "tests@openkubes.invalid")
            git("config", "user.name", "Test")
            (repo / "article.md").write_text("# Example\n", encoding="utf-8")
            git("add", "article.md")
            git("commit", "-qm", "first", date_value="2025-09-12")
            (repo / "article.md").write_text("# Example\nNew sentence.\n", encoding="utf-8")
            git("add", "article.md")
            git("commit", "-qm", "update", date_value="2026-11-20")
            self.assertEqual(
                dates.git_dates(repo, Path("article.md")),
                ("2025-09-12", "2026-11-20"),
            )
            self.assertEqual(
                dates.git_dates(repo, Path("article.md")),
                ("2025-09-12", "2026-11-20"),
            )


if __name__ == "__main__":
    unittest.main()
