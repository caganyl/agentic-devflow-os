"""
Tests for the DevFlow plugin build script.
Verifies that the build script produces the expected output structure.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_devflow_plugin.py"


class PluginBuildScriptExistsTest(unittest.TestCase):
    """Verify the build script exists and is executable Python."""

    def test_build_script_exists(self):
        self.assertTrue(BUILD_SCRIPT.exists(), f"Build script not found: {BUILD_SCRIPT}")

    def test_build_script_is_python(self):
        content = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("def build(", content, "build() function not found in script")

    def test_build_script_has_main(self):
        content = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__"', content)

    def test_build_script_no_third_party_imports(self):
        content = BUILD_SCRIPT.read_text(encoding="utf-8")
        forbidden = ["import requests", "import boto3", "import anthropic", "import openai"]
        for lib in forbidden:
            self.assertNotIn(lib, content, f"Build script must not import {lib}")


class PluginBuildOutputTest(unittest.TestCase):
    """Run the build script and verify the output structure."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = Path(self.tmpdir)
        self.plugin_dir = self.output_dir / "devflow-plugin"

        import subprocess
        result = subprocess.run(
            ["python3", str(BUILD_SCRIPT), "--output-dir", str(self.output_dir)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.build_result = result
        self.build_success = result.returncode == 0

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_build_succeeds(self):
        self.assertTrue(
            self.build_success,
            f"Build failed:\nSTDOUT: {self.build_result.stdout}\nSTDERR: {self.build_result.stderr}",
        )

    def test_plugin_dir_created(self):
        self.assertTrue(self.plugin_dir.exists(), "dist/devflow-plugin/ not created")
        self.assertTrue(self.plugin_dir.is_dir())

    def test_claude_plugin_dir_created(self):
        claude_plugin = self.plugin_dir / ".claude-plugin"
        self.assertTrue(claude_plugin.exists(), ".claude-plugin/ not created")

    def test_plugin_json_created(self):
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        self.assertTrue(manifest.exists(), ".claude-plugin/plugin.json not created")

    def test_plugin_json_is_valid_json(self):
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            self.skipTest("plugin.json not found")
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_plugin_json_has_required_metadata_fields(self):
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            self.skipTest("plugin.json not found")
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
        for key in ("name", "description", "version"):
            self.assertIn(key, data, f"plugin.json missing required metadata key: {key}")

    def test_plugin_json_has_no_invalid_fields(self):
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            self.skipTest("plugin.json not found")
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
        forbidden = (
            "schema_version", "plugin_version",
            "agents", "skills", "templates", "workflows", "rules", "scripts", "notes",
        )
        for key in forbidden:
            self.assertNotIn(key, data, f"plugin.json must not contain invalid field: {key}")

    def test_agents_dir_copied(self):
        agents_dir = self.plugin_dir / "agents"
        self.assertTrue(agents_dir.exists(), "agents/ not copied to plugin")
        md_files = list(agents_dir.glob("*.md"))
        self.assertGreater(len(md_files), 0, "No agent .md files in plugin")

    def test_skills_dir_copied(self):
        skills_dir = self.plugin_dir / "skills"
        self.assertTrue(skills_dir.exists(), "skills/ not copied to plugin")

    def test_templates_dir_copied(self):
        templates_dir = self.plugin_dir / "templates"
        self.assertTrue(templates_dir.exists(), "templates/ not copied to plugin")

    def test_workflows_dir_copied(self):
        workflows_dir = self.plugin_dir / "workflows"
        self.assertTrue(workflows_dir.exists(), "workflows/ not copied to plugin")

    def test_settings_json_not_copied(self):
        settings = self.plugin_dir / "settings.json"
        self.assertFalse(settings.exists(), "settings.json must NOT be in plugin output")

    def test_plugin_hooks_json_copied(self):
        hooks_json = self.plugin_dir / "hooks" / "hooks.json"
        self.assertTrue(
            hooks_json.exists(),
            "hooks/hooks.json must be in plugin output (target safety hook)",
        )

    def test_plugin_target_guard_copied(self):
        guard = self.plugin_dir / "scripts" / "devflow_target_guard.py"
        self.assertTrue(
            guard.exists(),
            "scripts/devflow_target_guard.py must be in plugin output",
        )

    def test_runtime_enforcement_hooks_shipped(self):
        # Reversed invariant: the runtime enforcement shell hooks now ship so
        # claude-devflow applies the same protection in any target project as
        # the framework repo dogfoods on itself.
        for fname in [
            "enforce-role-boundaries.sh",
            "protect-main.sh",
            "protect-sensitive-paths.sh",
            "session-start.sh",
        ]:
            hook = self.plugin_dir / "hooks" / fname
            self.assertTrue(
                hook.exists(),
                f"Runtime enforcement hook {fname} must be in plugin output",
            )
            self.assertTrue(os.access(hook, os.X_OK), f"{fname} must be executable")

    def test_ownership_validator_shipped(self):
        # enforce-role-boundaries.sh resolves the validator from the plugin root,
        # so it must ship for implementer authorization to work in a target.
        validator = self.plugin_dir / "scripts" / "validate_ownership_manifest.py"
        self.assertTrue(validator.exists(),
                        "validate_ownership_manifest.py must be in plugin output")

    def test_plugin_hooks_json_registers_enforcement_hooks(self):
        hooks_json = json.loads(
            (self.plugin_dir / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )
        commands = json.dumps(hooks_json)
        for fname in ["protect-main.sh", "protect-sensitive-paths.sh",
                      "enforce-role-boundaries.sh", "session-start.sh"]:
            self.assertIn(fname, commands,
                          f"hooks.json must register {fname}")
        # enforce-role-boundaries must receive the plugin root so it can find
        # the validator.
        self.assertIn("DEVFLOW_PLUGIN_ROOT", commands)

    def test_gitkeep_not_in_agents(self):
        gitkeep = self.plugin_dir / "agents" / ".gitkeep"
        self.assertFalse(gitkeep.exists(), ".gitkeep should not be in plugin agents/")

    def test_build_is_idempotent(self):
        import subprocess
        result2 = subprocess.run(
            ["python3", str(BUILD_SCRIPT), "--output-dir", str(self.output_dir)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(result2.returncode, 0, "Second build run failed")
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        self.assertTrue(manifest.exists(), "plugin.json missing after second build")


if __name__ == "__main__":
    unittest.main()
