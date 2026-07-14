"""Static validation for the project-local Codex hook registration."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / ".codex" / "hooks.json"
CODEX_CONFIG_PATH = REPO_ROOT / ".codex" / "config.toml"
ADAPTER_PATH = REPO_ROOT / "scripts" / "devflow_codex_target_guard.py"
CLAUDE_HOOK_PATH = REPO_ROOT / "hooks" / "hooks.json"
BOOTSTRAP_DENIAL = (
    "DevFlow guard: hook bootstrap failed; tool call blocked by policy."
)


class CodexHookRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw_hook = HOOK_PATH.read_text(encoding="utf-8")
        cls.registration = json.loads(cls.raw_hook)

    def _pre_tool_use_groups(self) -> list[dict]:
        hooks = self.registration["hooks"]
        self.assertIsInstance(hooks, dict)
        groups = hooks.get("PreToolUse")
        self.assertIsInstance(groups, list)
        return groups

    def _handler(self) -> dict:
        groups = self._pre_tool_use_groups()
        self.assertEqual(len(groups), 1)
        handlers = groups[0].get("hooks")
        self.assertIsInstance(handlers, list)
        self.assertEqual(len(handlers), 1)
        return handlers[0]

    def _run_command(
        self, cwd: Path, *, guard_required: bool
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("DEVFLOW_CODEX_GUARD_REQUIRED", None)
        env["DEVFLOW_BOOTSTRAP_TEST_VALUE"] = "sensitive-test-value"
        if guard_required:
            env["DEVFLOW_CODEX_GUARD_REQUIRED"] = "1"
        return subprocess.run(
            ["/bin/sh", "-c", self._handler()["command"]],
            cwd=cwd,
            env=env,
            input="hook-payload-must-not-be-exposed",
            text=True,
            capture_output=True,
            check=False,
        )

    def test_hook_file_is_valid_json_with_top_level_hooks_object(self) -> None:
        self.assertIsInstance(self.registration, dict)
        self.assertIn("hooks", self.registration)
        self.assertIsInstance(self.registration["hooks"], dict)

    def test_exactly_one_pre_tool_use_matcher_group_is_registered(self) -> None:
        groups = self._pre_tool_use_groups()
        self.assertEqual(len(groups), 1)

    def test_matcher_covers_bash_and_apply_patch(self) -> None:
        matcher = self._pre_tool_use_groups()[0].get("matcher")
        self.assertEqual(matcher, r"^(Bash|bash|apply_patch|Edit|Write)$")
        self.assertIsNotNone(re.fullmatch(matcher, "Bash"))
        self.assertIsNotNone(re.fullmatch(matcher, "apply_patch"))

    def test_exactly_one_command_handler_exists(self) -> None:
        handler = self._handler()
        self.assertEqual(handler.get("type"), "command")

    def test_command_has_activation_gate_and_successful_inactive_exit(self) -> None:
        command = self._handler().get("command", "")
        self.assertIn("DEVFLOW_CODEX_GUARD_REQUIRED", command)
        self.assertRegex(command, r'!= [\\"]+1[\\"]+')
        self.assertRegex(command, r"then\s+exit 0;")

    def test_inactive_command_exits_silently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = self._run_command(
                Path(temporary_directory), guard_required=False
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_active_command_blocks_silently_on_git_root_bootstrap_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            result = self._run_command(temporary_path, guard_required=True)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"{BOOTSTRAP_DENIAL}\n")
        self.assertNotIn(str(temporary_path), result.stderr)
        self.assertNotIn("sensitive-test-value", result.stderr)

    def test_active_command_blocks_when_adapter_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            initialization = subprocess.run(
                ["git", "init", "--quiet"],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(initialization.returncode, 0)
            result = self._run_command(temporary_path, guard_required=True)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"{BOOTSTRAP_DENIAL}\n")

    def test_active_command_resolves_adapter_from_git_root(self) -> None:
        command = self._handler().get("command", "")
        self.assertIn("git rev-parse --show-toplevel", command)
        self.assertIn("$root/scripts/devflow_codex_target_guard.py", command)

    def test_command_uses_env_python_and_exec_handoff(self) -> None:
        command = self._handler().get("command", "")
        self.assertIn("/usr/bin/env python3", command)
        self.assertRegex(
            command,
            r'exec\s+/usr/bin/env\s+python3\s+[\\"]\$adapter[\\"]',
        )

    def test_handler_has_short_timeout_and_status_message(self) -> None:
        handler = self._handler()
        timeout = handler.get("timeout")
        self.assertIsInstance(timeout, int)
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 15)
        status_message = handler.get("statusMessage")
        self.assertIsInstance(status_message, str)
        self.assertTrue(status_message.strip())

    def test_hook_definition_contains_no_sensitive_configuration(self) -> None:
        forbidden_patterns = (
            r"(?i)api[_ -]?key\s*[:=]",
            r"(?i)bearer\s+[a-z0-9._~-]+",
            r"(?i)authorization\s*[:=]",
            r"(?i)mcp(?:servers?|[_ -]?configuration)?\s*[:=]",
            r"(?i)(?:secret|token)\s*[:=]\s*[^,}\s]+",
            r"/Users/[^/\s\"]+",
            r"/home/[^/\s\"]+",
        )
        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.raw_hook))

    def test_codex_config_does_not_also_define_inline_hooks(self) -> None:
        config = CODEX_CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?m)^\s*\[hooks(?:\.|\])", config))
        self.assertIsNone(re.search(r"(?m)^\s*hooks\s*=", config))

    def test_referenced_adapter_exists(self) -> None:
        self.assertTrue(ADAPTER_PATH.is_file())

    def test_claude_hook_registration_is_unchanged(self) -> None:
        self.assertTrue(CLAUDE_HOOK_PATH.is_file())
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", "hooks/hooks.json"],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
