"""Focused acceptance tests for the deterministic Codex plugin build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_codex_devflow_plugin.py"
MARKETPLACE_PATH = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN_NAME = "codex-devflow-plugin"
BUILD_MARKER_NAME = ".devflow-codex-plugin-build.json"
BUILD_MARKER = {
    "schema_version": 1,
    "generator": "build_codex_devflow_plugin.py",
    "plugin_name": "codex-devflow",
    "plugin_version": "0.1.0",
}
SKILL_NAMES = {
    "managed-delivery-operations",
    "visual-design-review",
    "qa-acceptance-verification",
}
BOOTSTRAP_DENIAL = (
    "DevFlow guard: hook bootstrap failed; tool call blocked by policy."
)


def run_builder(output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output-dir", str(output_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}
    values = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


class CodexPluginBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temporary_directory.name)
        cls.result = run_builder(cls.output_dir)
        if cls.result.returncode != 0:
            raise AssertionError(
                f"build failed\nstdout: {cls.result.stdout}\nstderr: {cls.result.stderr}"
            )
        cls.plugin_dir = cls.output_dir / PLUGIN_NAME
        cls.manifest = json.loads(
            (cls.plugin_dir / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        cls.raw_hook = (cls.plugin_dir / "hooks" / "hooks.json").read_text(
            encoding="utf-8"
        )
        cls.hook = json.loads(cls.raw_hook)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def handler(self) -> dict[str, object]:
        return self.hook["hooks"]["PreToolUse"][0]["hooks"][0]

    def run_hook(
        self, *, plugin_root: Path | None = None, active: bool = True, payload: str = "event"
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("DEVFLOW_CODEX_GUARD_REQUIRED", None)
        env.pop("PLUGIN_ROOT", None)
        if active:
            env["DEVFLOW_CODEX_GUARD_REQUIRED"] = "1"
        if plugin_root is not None:
            env["PLUGIN_ROOT"] = str(plugin_root)
        return subprocess.run(
            ["/bin/sh", "-c", str(self.handler()["command"])],
            cwd=REPO_ROOT,
            env=env,
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builder_help_succeeds(self) -> None:
        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--help"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--output-dir", result.stdout)

    def test_build_succeeds_and_prints_final_path(self) -> None:
        self.assertEqual(self.result.returncode, 0)
        self.assertEqual(self.result.stdout.strip(), str(self.plugin_dir.resolve()))
        self.assertTrue(self.plugin_dir.is_dir())

    def test_final_output_directory_name(self) -> None:
        self.assertEqual(self.plugin_dir.name, PLUGIN_NAME)

    def test_manifest_is_valid_json_with_required_values(self) -> None:
        self.assertEqual(self.manifest["name"], "codex-devflow")
        self.assertEqual(self.manifest["version"], "0.1.0")
        self.assertEqual(self.manifest["skills"], "./skills/")
        self.assertEqual(self.manifest["hooks"], "./hooks/hooks.json")

    def test_generated_build_marker_is_exact_and_deterministic(self) -> None:
        marker_path = self.plugin_dir / BUILD_MARKER_NAME
        self.assertEqual(json.loads(marker_path.read_text(encoding="utf-8")), BUILD_MARKER)
        self.assertEqual(
            marker_path.read_text(encoding="utf-8"),
            json.dumps(BUILD_MARKER, indent=2, ensure_ascii=False) + "\n",
        )

    def test_manifest_has_no_mcp_or_app_definition(self) -> None:
        self.assertNotIn("mcpServers", self.manifest)
        self.assertNotIn("apps", self.manifest)

    def test_exactly_three_phase_one_skills_are_bundled(self) -> None:
        bundled = {path.parent.name for path in self.plugin_dir.glob("skills/*/SKILL.md")}
        self.assertEqual(bundled, SKILL_NAMES)

    def test_each_bundled_skill_has_name_and_description(self) -> None:
        for skill_name in SKILL_NAMES:
            with self.subTest(skill=skill_name):
                metadata = frontmatter(
                    self.plugin_dir / "skills" / skill_name / "SKILL.md"
                )
                self.assertTrue(metadata.get("name"))
                self.assertTrue(metadata.get("description"))

    def test_both_guard_scripts_are_bundled(self) -> None:
        self.assertTrue((self.plugin_dir / "scripts" / "devflow_guard_core.py").is_file())
        self.assertTrue(
            (self.plugin_dir / "scripts" / "devflow_codex_target_guard.py").is_file()
        )

    def test_excluded_repository_content_is_not_bundled(self) -> None:
        paths = [path.relative_to(self.plugin_dir).as_posix() for path in self.plugin_dir.rglob("*")]
        self.assertFalse(any(path.endswith(".toml") for path in paths))
        self.assertFalse(any(".claude" in Path(path).parts for path in paths))
        self.assertNotIn(".codex/config.toml", paths)
        self.assertNotIn("AGENTS.md", paths)
        self.assertFalse(any("workspaces" in Path(path).parts for path in paths))
        self.assertFalse(any("tests" in Path(path).parts for path in paths))

    def test_generated_plugin_hook_is_valid_json(self) -> None:
        self.assertIsInstance(self.hook, dict)
        self.assertIsInstance(self.hook["hooks"]["PreToolUse"], list)

    def test_generated_matcher_is_exact(self) -> None:
        matcher = self.hook["hooks"]["PreToolUse"][0]["matcher"]
        self.assertEqual(matcher, r"^(Bash|bash|apply_patch|Edit|Write)$")

    def test_hook_uses_plugin_root_without_target_repository_fallback(self) -> None:
        command = str(self.handler()["command"])
        self.assertIn('$PLUGIN_ROOT/scripts/devflow_codex_target_guard.py', command)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", command)
        self.assertNotIn("git rev-parse", command)
        self.assertNotIn("DEVFLOW_RUN_WORKTREE", command)
        self.assertNotIn('$root/scripts', command)

    def test_hook_handler_metadata(self) -> None:
        self.assertEqual(self.handler()["timeout"], 10)
        self.assertTrue(str(self.handler()["statusMessage"]).strip())
        self.assertIn('exec /usr/bin/env python3 "$adapter"', self.handler()["command"])

    def test_inactive_hook_exits_silently(self) -> None:
        result = self.run_hook(active=False, payload="must remain private")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_missing_plugin_root_fails_closed(self) -> None:
        result = self.run_hook()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"{BOOTSTRAP_DENIAL}\n")

    def test_missing_adapter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_hook(plugin_root=Path(directory))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"{BOOTSTRAP_DENIAL}\n")

    def test_valid_adapter_handoff_preserves_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            adapter = scripts / "devflow_codex_target_guard.py"
            adapter.write_text(
                "import sys\nsys.stdout.write(sys.stdin.read())\n", encoding="utf-8"
            )
            result = self.run_hook(plugin_root=root, payload="preserved-input")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "preserved-input")
        self.assertEqual(result.stderr, "")

    def test_rebuild_removes_only_final_stale_content(self) -> None:
        stale = self.plugin_dir / "stale.txt"
        sibling = self.output_dir / "unrelated.txt"
        stale.write_text("stale", encoding="utf-8")
        sibling.write_text("keep", encoding="utf-8")
        result = run_builder(self.output_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stale.exists())
        self.assertEqual(sibling.read_text(encoding="utf-8"), "keep")

    def test_unrelated_existing_plugin_without_marker_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            target = output / PLUGIN_NAME
            target.mkdir()
            original = target / "original.txt"
            original.write_text("keep this content", encoding="utf-8")

            result = run_builder(output)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(original.read_text(encoding="utf-8"), "keep this content")

    def test_malformed_marker_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            target = output / PLUGIN_NAME
            target.mkdir()
            marker = target / BUILD_MARKER_NAME
            marker.write_text("not json", encoding="utf-8")

            result = run_builder(output)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "not json")

    def test_mismatched_marker_fields_are_not_deleted(self) -> None:
        mismatches = {
            "schema_version": 2,
            "generator": "other-builder.py",
            "plugin_name": "other-plugin",
            "plugin_version": "9.9.9",
        }
        for field, value in mismatches.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                target = output / PLUGIN_NAME
                target.mkdir()
                marker = dict(BUILD_MARKER)
                marker[field] = value
                marker_path = target / BUILD_MARKER_NAME
                marker_path.write_text(json.dumps(marker), encoding="utf-8")

                result = run_builder(output)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(marker_path.read_text(encoding="utf-8")), marker)

    def test_valid_marker_requires_matching_plugin_manifest(self) -> None:
        manifests = (None, {"name": "wrong", "version": "0.1.0"}, {"name": "codex-devflow", "version": "9.9.9"})
        for manifest in manifests:
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                target = output / PLUGIN_NAME
                target.mkdir()
                marker_path = target / BUILD_MARKER_NAME
                marker_path.write_text(json.dumps(BUILD_MARKER), encoding="utf-8")
                if manifest is not None:
                    manifest_path = target / ".codex-plugin" / "plugin.json"
                    manifest_path.parent.mkdir()
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                result = run_builder(output)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(marker_path.read_text(encoding="utf-8")), BUILD_MARKER)

    def test_protected_output_parents_are_rejected(self) -> None:
        protected = (
            Path(Path.cwd().anchor),
            Path.home(),
            REPO_ROOT,
            REPO_ROOT / "scripts",
            REPO_ROOT / ".claude",
            REPO_ROOT / ".codex",
            REPO_ROOT / ".agents",
            REPO_ROOT / "hooks",
            REPO_ROOT / "tests",
            REPO_ROOT / "workspaces",
        )
        for output in protected:
            with self.subTest(output=output):
                result = run_builder(output)
                self.assertNotEqual(result.returncode, 0)

    def test_temporary_output_parent_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = run_builder(output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / PLUGIN_NAME / BUILD_MARKER_NAME).is_file())

    def test_unsafe_output_choices_fail_safely(self) -> None:
        result = run_builder(REPO_ROOT)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((REPO_ROOT / PLUGIN_NAME).exists())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            target = output / PLUGIN_NAME
            target.symlink_to(output / "elsewhere", target_is_directory=True)
            symlink_result = run_builder(output)
            self.assertNotEqual(symlink_result.returncode, 0)
            self.assertTrue(target.is_symlink())

    def test_marketplace_json_is_valid_and_exactly_one_local_plugin(self) -> None:
        marketplace = json.loads(MARKETPLACE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(marketplace["name"], "agentic-devflow-local")
        self.assertEqual(marketplace["interface"]["displayName"], "Agentic DevFlow Local")
        self.assertEqual(len(marketplace["plugins"]), 1)
        plugin = marketplace["plugins"][0]
        self.assertEqual(plugin["name"], "codex-devflow")
        self.assertEqual(plugin["source"], {"source": "local", "path": "./dist/codex-devflow-plugin"})
        self.assertEqual(plugin["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertEqual(plugin["category"], "Productivity")

    def test_marketplace_has_no_machine_specific_or_sensitive_values(self) -> None:
        raw = MARKETPLACE_PATH.read_text(encoding="utf-8")
        forbidden = (
            r"/Users/",
            r"/home/",
            r"(?i)api[_-]?key",
            r"(?i)bearer\s+",
            r"(?i)(?:secret|token)\s*[:=]",
            r"(?i)mcpServers",
        )
        for pattern in forbidden:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, raw))

    def test_claude_builder_and_hook_registration_are_unchanged(self) -> None:
        # Updated when the Claude plugin build gained INCLUDED_SHELL_SCRIPTS so
        # devflow_bootstrap.sh / devflow_new_manifest.sh ship with the plugin
        # (zero-step target provisioning). Previously updated for the runtime
        # enforcement shell hooks + ownership validator. This tripwire still
        # guards the Claude build from unintended Codex-side edits.
        expected = {
            REPO_ROOT / "scripts" / "build_devflow_plugin.py": "e11f6f06f6d6a601b582a78d6f690fcb33b5b738b8b504703b43b879f2ec596c",
            REPO_ROOT / "hooks" / "hooks.json": "baf288402c0c8d3264b47502cca4578f831fcd5f3796a84aeafc227f0827925e",
        }
        for path, digest in expected.items():
            with self.subTest(path=path):
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(actual, digest)
                result = subprocess.run(
                    ["git", "diff", "--quiet", "HEAD", "--", str(path)],
                    cwd=REPO_ROOT,
                    check=False,
                )
                self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
