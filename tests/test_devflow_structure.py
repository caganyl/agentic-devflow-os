"""
Tests for DevFlow OS file structure:
- Required skill, workflow, rule and template files exist
- Files have correct YAML frontmatter (skills) or required section headers
- Delivery Lead task routing covers all task types
"""

import ast
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_DIR = REPO_ROOT / ".claude"


REQUIRED_WORKFLOWS = [
    "new-product-discovery",
    "feature-delivery",
    "ai-rag-delivery",
    "data-dashboard-delivery",
    "bug-resolution",
    "security-response",
    "release-readiness",
    "cost-optimization",
]

REQUIRED_SKILLS = [
    "orchestrate-delivery",
    "task-routing",
    "project-context-synthesis",
    "notebooklm-grounded-retrieval",
    "obsidian-project-context",
    "requirement-traceability",
    "api-contract-design",
    "db-migration-safety",
    "qa-acceptance-verification",
    "adversarial-security-review",
    "visual-design-review",
    "evalops-regression",
    "release-scorecard",
]

REQUIRED_RULES = [
    "source-of-truth",
    "target-project-boundaries",
    "autonomy-gates",
    "task-routing",
    "context-distribution",
]

REQUIRED_TEMPLATES = [
    "task-packet.md",
    "source-register.yaml",
    "context-pack.md",
    "run-summary.md",
    "merge-recommendation.md",
]

TASK_TYPES_IN_ROUTING = [
    "ürün fikri",
    "feature",
    "AI/RAG",
    "dashboard",
    "Bug",
    "Güvenlik",
    "Release",
    "Maliyet",
]


class WorkflowStructureTest(unittest.TestCase):
    """Verify all required workflow files exist and have required sections."""

    def _workflow_path(self, name: str) -> Path:
        return CLAUDE_DIR / "workflows" / f"{name}.md"

    def test_all_workflows_exist(self):
        for name in REQUIRED_WORKFLOWS:
            path = self._workflow_path(name)
            self.assertTrue(path.exists(), f"Missing workflow: {path}")

    def test_workflows_have_required_sections(self):
        required_sections = [
            "## Ne Zaman",
            "## Girdiler",
            "## Kullanılacak Roller",
            "## Approval Gate",
            "## Üretilecek Artefakt",
            "## Completion Kriteri",
        ]
        for name in REQUIRED_WORKFLOWS:
            path = self._workflow_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            for section in required_sections:
                self.assertIn(
                    section,
                    content,
                    f"Workflow '{name}' missing section: {section}",
                )


class SkillStructureTest(unittest.TestCase):
    """Verify all required skill directories and SKILL.md files exist."""

    def _skill_path(self, name: str) -> Path:
        return CLAUDE_DIR / "skills" / name / "SKILL.md"

    def test_all_skills_exist(self):
        for name in REQUIRED_SKILLS:
            path = self._skill_path(name)
            self.assertTrue(path.exists(), f"Missing skill: {path}")

    def test_skills_have_yaml_frontmatter(self):
        for name in REQUIRED_SKILLS:
            path = self._skill_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            self.assertTrue(
                content.startswith("---"),
                f"Skill '{name}' missing YAML frontmatter",
            )
            end_idx = content.find("---", 3)
            self.assertGreater(
                end_idx,
                3,
                f"Skill '{name}' frontmatter not closed",
            )

    def test_skills_have_name_in_frontmatter(self):
        for name in REQUIRED_SKILLS:
            path = self._skill_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                f"name: {name}",
                content,
                f"Skill '{name}' missing 'name:' in frontmatter",
            )

    def test_skills_have_description_in_frontmatter(self):
        for name in REQUIRED_SKILLS:
            path = self._skill_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                "description:",
                content,
                f"Skill '{name}' missing 'description:' in frontmatter",
            )

    def test_skills_have_amaç_section(self):
        for name in REQUIRED_SKILLS:
            path = self._skill_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                "## Amaç",
                content,
                f"Skill '{name}' missing '## Amaç' section",
            )

    def test_skills_have_prosedür_section(self):
        for name in REQUIRED_SKILLS:
            path = self._skill_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            self.assertIn(
                "## Prosedür",
                content,
                f"Skill '{name}' missing '## Prosedür' section",
            )


class RuleStructureTest(unittest.TestCase):
    """Verify all required rule files exist."""

    def _rule_path(self, name: str) -> Path:
        return CLAUDE_DIR / "rules" / f"{name}.md"

    def test_all_rules_exist(self):
        for name in REQUIRED_RULES:
            path = self._rule_path(name)
            self.assertTrue(path.exists(), f"Missing rule: {path}")

    def test_rules_are_non_empty(self):
        for name in REQUIRED_RULES:
            path = self._rule_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8").strip()
            self.assertGreater(
                len(content),
                50,
                f"Rule '{name}' appears to be empty or trivial",
            )


class TemplateStructureTest(unittest.TestCase):
    """Verify all required template files exist."""

    def _template_path(self, name: str) -> Path:
        return CLAUDE_DIR / "templates" / name

    def test_all_templates_exist(self):
        for name in REQUIRED_TEMPLATES:
            path = self._template_path(name)
            self.assertTrue(path.exists(), f"Missing template: {path}")

    def test_templates_are_non_empty(self):
        for name in REQUIRED_TEMPLATES:
            path = self._template_path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8").strip()
            self.assertGreater(
                len(content),
                30,
                f"Template '{name}' appears to be empty or trivial",
            )


class TaskRoutingCoverageTest(unittest.TestCase):
    """Verify task-routing.md covers all required task types."""

    def setUp(self):
        routing_path = CLAUDE_DIR / "rules" / "task-routing.md"
        self.routing_content = routing_path.read_text(encoding="utf-8") if routing_path.exists() else ""

    def test_routing_file_exists(self):
        path = CLAUDE_DIR / "rules" / "task-routing.md"
        self.assertTrue(path.exists(), "task-routing.md not found")

    def test_all_task_types_covered(self):
        for task_type in TASK_TYPES_IN_ROUTING:
            self.assertIn(
                task_type,
                self.routing_content,
                f"Task type '{task_type}' not found in task-routing.md",
            )

    def test_routing_has_table(self):
        self.assertIn(
            "| Task türü",
            self.routing_content,
            "task-routing.md missing routing table",
        )

    def test_routing_has_parallel_rules(self):
        self.assertIn(
            "Paralel",
            self.routing_content,
            "task-routing.md missing parallel work rules",
        )


class DeliveryLeadAgentTest(unittest.TestCase):
    """Verify delivery-lead.md has updated task routing section."""

    def setUp(self):
        agent_path = CLAUDE_DIR / "agents" / "delivery-lead.md"
        self.content = agent_path.read_text(encoding="utf-8") if agent_path.exists() else ""

    def test_delivery_lead_exists(self):
        path = CLAUDE_DIR / "agents" / "delivery-lead.md"
        self.assertTrue(path.exists())

    def test_delivery_lead_has_task_routing(self):
        self.assertIn(
            "Task Routing",
            self.content,
            "delivery-lead.md missing Task Routing section",
        )

    def test_delivery_lead_has_workflow_references(self):
        self.assertIn(
            "workflows/",
            self.content,
            "delivery-lead.md missing workflow references",
        )

    def test_delivery_lead_has_skill_references(self):
        self.assertIn(
            "orchestrate-delivery",
            self.content,
            "delivery-lead.md missing skill references",
        )

    def test_delivery_lead_has_human_approval_section(self):
        self.assertIn(
            "İnsan Onay",
            self.content,
            "delivery-lead.md missing human approval section",
        )


class ScriptPythonCompatibilityTest(unittest.TestCase):
    """Scripts must import on the Python the operator actually has.

    macOS ships 3.9 as /usr/bin/python3, and the docs tell people to run these
    with a bare `python3`. PEP 604 unions (`str | None`) in an annotation are
    evaluated at import time there and raise TypeError before argparse runs —
    which is exactly how devflow_operations.py became unrunnable while its
    tests, executed under a newer interpreter, stayed green.

    `from __future__ import annotations` defers annotation evaluation, so a
    script may use the modern syntax as long as it opts in. Quoted annotations
    ("Path | None") are already strings and are correctly ignored here.
    """

    @staticmethod
    def _annotations_of(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and node.annotation:
                yield node.annotation
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.returns:
                    yield node.returns
                args = node.args
                for arg in (list(args.posonlyargs) + list(args.args)
                            + list(args.kwonlyargs)
                            + [a for a in (args.vararg, args.kwarg) if a]):
                    if arg.annotation:
                        yield arg.annotation

    def test_pep604_annotations_require_future_import(self):
        scripts = sorted((REPO_ROOT / "scripts").glob("*.py"))
        self.assertTrue(scripts, "no scripts found to check")
        for path in scripts:
            with self.subTest(script=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                has_future = any(
                    isinstance(node, ast.ImportFrom)
                    and node.module == "__future__"
                    and any(alias.name == "annotations" for alias in node.names)
                    for node in tree.body
                )
                uses_pep604 = any(
                    isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)
                    for annotation in self._annotations_of(tree)
                    for sub in ast.walk(annotation)
                )
                if uses_pep604:
                    self.assertTrue(
                        has_future,
                        f"{path.name} uses `X | Y` annotations but lacks "
                        "`from __future__ import annotations`; it will fail to "
                        "import on Python 3.9 (/usr/bin/python3 on macOS).",
                    )


class GitignoreTest(unittest.TestCase):
    """Verify dist/devflow-plugin/ is in .gitignore."""

    def test_plugin_output_gitignored(self):
        gitignore = REPO_ROOT / ".gitignore"
        self.assertTrue(gitignore.exists())
        content = gitignore.read_text(encoding="utf-8")
        self.assertIn(
            "dist/devflow-plugin/",
            content,
            "dist/devflow-plugin/ not in .gitignore",
        )


if __name__ == "__main__":
    unittest.main()
