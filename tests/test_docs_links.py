"""Repo paths written in backticks in the main docs must exist.

Checks README.md, CLAUDE.md, AGENTS.md, docs/ARCHITECTURE.md and
.claude/templates/TARGET_CLAUDE.md. A backtick span counts as a repo path when
its first word starts with docs/, scripts/, .claude/, bin/, hooks/ or tests/.
Placeholders (XXX, NNN, <...>, globs, ellipses) are skipped.
"""

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "docs/ARCHITECTURE.md",
    ".claude/templates/TARGET_CLAUDE.md",
]
PREFIXES = ("docs/", "scripts/", ".claude/", "bin/", "hooks/", "tests/")
PLACEHOLDERS = ("XXX", "NNN", "<", "*", "…", "{")
BACKTICK = re.compile(r"`([^`\n]+)`")
# Files that exist only in a target project, not in the framework repo.
TARGET_ONLY = {
    "docs/architecture/profile/ARCHITECTURE_PROFILE.md",
    "docs/architecture/profile/architecture-profile.json",
    "docs/product/GLOSSARY.md",
}


def repo_paths(text):
    for span in BACKTICK.findall(text):
        words = span.strip().split()
        if not words:
            continue
        candidate = words[0].rstrip(".,;:)")
        candidate = candidate.split("#", 1)[0]
        if not candidate.startswith(PREFIXES):
            continue
        if any(marker in candidate for marker in PLACEHOLDERS):
            continue
        if candidate in TARGET_ONLY:
            continue
        yield candidate


class DocsLinksTest(unittest.TestCase):

    def test_backticked_repo_paths_exist(self):
        for doc in DOCS:
            text = (REPO_ROOT / doc).read_text(encoding="utf-8")
            for path in repo_paths(text):
                with self.subTest(doc=doc, path=path):
                    self.assertTrue(
                        (REPO_ROOT / path).exists(),
                        f"{doc} mentions `{path}`, which does not exist",
                    )

    def test_handoff_template_copies_match(self):
        """docs/templates and .claude/templates (shipped) hold the same template."""
        def body(rel):
            lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
            return [line for line in lines if "Aynı içerik:" not in line]

        self.assertEqual(
            body("docs/templates/REQ_HANDOFF_TEMPLATE.md"),
            body(".claude/templates/handoff.md"),
        )


if __name__ == "__main__":
    unittest.main()
