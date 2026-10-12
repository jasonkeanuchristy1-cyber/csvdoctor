"""Keep the documentation honest: every check the code can emit is in the README table."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocsTests(unittest.TestCase):
    def test_readme_lists_every_issue_code(self):
        source = (ROOT / "src" / "csvdoctor" / "diagnose.py").read_text(encoding="utf-8")
        in_code = set(re.findall(r'Issue\(\s*"([A-Z_]+)"', source))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        in_readme = set(re.findall(r"^\| `([A-Z_]+)`", readme, flags=re.MULTILINE))
        self.assertTrue(in_code)
        self.assertEqual(in_code - in_readme, set(), "missing from README table")
        self.assertEqual(in_readme - in_code, set(), "in README but not emitted by the code")

    def test_changelog_mentions_current_version(self):
        from csvdoctor import __version__

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"[{__version__}]", changelog)


if __name__ == "__main__":
    unittest.main()
