"""Reference files a SKILL.md points to with "(bu klasörde)" must exist in
that skill's folder, so a rename cannot silently orphan a checklist."""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / ".claude" / "skills"
LOCAL_REF = re.compile(r"`([\w.-]+\.md)`\s*\(bu klasörde\)")


class SkillReferenceTest(unittest.TestCase):

    def test_local_references_exist(self):
        for skill in sorted(SKILLS.glob("*/SKILL.md")):
            for name in LOCAL_REF.findall(skill.read_text(encoding="utf-8")):
                with self.subTest(skill=skill.parent.name, ref=name):
                    self.assertTrue((skill.parent / name).is_file())

    def test_checklists_are_referenced(self):
        expected = {
            "visual-design-review": ["wcag-audit.md"],
            "adversarial-security-review": ["auth-checklist.md", "client-boundary.md"],
        }
        for skill, refs in expected.items():
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            for ref in refs:
                with self.subTest(skill=skill, ref=ref):
                    self.assertRegex(text, LOCAL_REF.pattern.replace(r"[\w.-]+\.md", re.escape(ref)))


if __name__ == "__main__":
    unittest.main()
