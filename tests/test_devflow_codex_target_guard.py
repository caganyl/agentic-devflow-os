"""Focused acceptance tests for the Codex DevFlow target guard."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SCRIPT = REPO_ROOT / "scripts" / "devflow_codex_target_guard.py"


def apply_patch_payload(patch: str) -> dict:
    return {"tool_name": "apply_patch", "tool_input": {"command": patch}}


def bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def run_guard(payload: dict | str, worktree: Path) -> subprocess.CompletedProcess:
    stdin_data = json.dumps(payload) if isinstance(payload, dict) else payload
    env = os.environ.copy()
    env["DEVFLOW_RUN_WORKTREE"] = str(worktree)
    env.pop("DEVFLOW_RUN_BRANCH", None)
    return subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def denial_reason(result: subprocess.CompletedProcess) -> str:
    if result.returncode == 2:
        return result.stderr.strip()
    if result.returncode == 0 and result.stdout.strip():
        data = json.loads(result.stdout)
        output = data["hookSpecificOutput"]
        if output.get("permissionDecision") == "deny":
            return output["permissionDecisionReason"]
    return ""


class CodexTargetGuardTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.worktree = Path(self.tempdir.name).resolve()

    def tearDown(self):
        self.tempdir.cleanup()

    def assert_allowed(self, payload: dict):
        result = run_guard(payload, self.worktree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def assert_denied(self, payload: dict | str) -> subprocess.CompletedProcess:
        result = run_guard(payload, self.worktree)
        self.assertIn(result.returncode, (0, 2))
        self.assertTrue(denial_reason(result), (result.stdout, result.stderr))
        return result

    def test_safe_apply_patch_path_inside_managed_worktree(self):
        self.assert_allowed(apply_patch_payload(
            "*** Begin Patch\n*** Update File: src/app.py\n@@\n-old\n+new\n*** End Patch"
        ))

    def test_absolute_path_outside_worktree_denied(self):
        result = self.assert_denied(apply_patch_payload(
            "*** Begin Patch\n*** Add File: /tmp/outside.txt\n+data\n*** End Patch"
        ))
        self.assertIn("outside", denial_reason(result))

    def test_parent_traversal_denied(self):
        result = self.assert_denied(apply_patch_payload(
            "*** Begin Patch\n*** Add File: ../outside.txt\n+data\n*** End Patch"
        ))
        self.assertIn("traversal", denial_reason(result))

    def test_symlink_escape_denied(self):
        outside = Path(self.tempdir.name).parent / "devflow-guard-outside"
        outside.mkdir(exist_ok=True)
        link = self.worktree / "escape"
        link.symlink_to(outside, target_is_directory=True)
        try:
            result = self.assert_denied(apply_patch_payload(
                "*** Begin Patch\n*** Add File: escape/payload.txt\n+data\n*** End Patch"
            ))
            self.assertIn("outside", denial_reason(result))
        finally:
            link.unlink()
            try:
                outside.rmdir()
            except OSError:
                pass

    def test_symlink_to_codex_config_inside_worktree_denied_without_leak(self):
        protected = self.worktree / ".codex" / "config.toml"
        protected.parent.mkdir()
        protected.write_text("model = 'sensitive'\n", encoding="utf-8")
        (self.worktree / "safe-alias").symlink_to(protected)

        result = self.assert_denied({
            "tool_name": "Edit",
            "tool_input": {"file_path": "safe-alias", "new_string": "unsafe"},
        })

        self.assertIn("protected path", denial_reason(result))
        self.assertNotIn(".codex/config.toml", result.stdout + result.stderr)

    def test_symlink_to_dotenv_inside_worktree_denied_without_leak(self):
        protected = self.worktree / ".env"
        protected.write_text("TOKEN=sensitive\n", encoding="utf-8")
        (self.worktree / "environment-alias").symlink_to(protected)

        result = self.assert_denied({
            "tool_name": "Write",
            "tool_input": {"path": "environment-alias", "content": "unsafe"},
        })

        self.assertIn("protected path", denial_reason(result))
        self.assertNotIn(".env", result.stdout + result.stderr)

    def test_non_sensitive_symlink_inside_worktree_allowed(self):
        target = self.worktree / "src" / "actual.py"
        target.parent.mkdir()
        target.write_text("value = 1\n", encoding="utf-8")
        (self.worktree / "safe-source-alias").symlink_to(target)

        self.assert_allowed({
            "tool_name": "Edit",
            "tool_input": {"file_path": "safe-source-alias", "new_string": "value = 2"},
        })

    def test_multi_file_patch_one_unsafe_path_denied(self):
        self.assert_denied(apply_patch_payload(
            "*** Begin Patch\n"
            "*** Add File: src/safe.py\n+safe\n"
            "*** Update File: ../unsafe.py\n@@\n-old\n+new\n"
            "*** End Patch"
        ))

    def test_add_file_supported(self):
        self.assert_allowed(apply_patch_payload(
            "*** Begin Patch\n*** Add File: src/new.py\n+value = 1\n*** End Patch"
        ))

    def test_update_file_supported(self):
        self.assert_allowed(apply_patch_payload(
            "*** Begin Patch\n*** Update File: src/old.py\n@@\n-a\n+b\n*** End Patch"
        ))

    def test_delete_file_supported(self):
        self.assert_allowed(apply_patch_payload(
            "*** Begin Patch\n*** Delete File: src/old.py\n*** End Patch"
        ))

    def test_move_destination_supported_and_validated(self):
        self.assert_allowed(apply_patch_payload(
            "*** Begin Patch\n*** Update File: src/old.py\n*** Move to: src/new.py\n@@\n-a\n+b\n*** End Patch"
        ))
        self.assert_denied(apply_patch_payload(
            "*** Begin Patch\n*** Update File: src/old.py\n*** Move to: ../new.py\n@@\n-a\n+b\n*** End Patch"
        ))

    def test_malformed_patch_header_fails_closed(self):
        self.assert_denied(apply_patch_payload(
            "*** Begin Patch\n*** Modify File: src/app.py\n@@\n-a\n+b\n*** End Patch"
        ))

    def test_bash_cd_outside_worktree_denied(self):
        self.assert_denied(bash_payload("cd /tmp && pwd"))

    def test_bash_git_c_outside_worktree_denied(self):
        self.assert_denied(bash_payload("git -C /tmp status"))

    def test_bash_git_work_tree_outside_worktree_denied(self):
        self.assert_denied(bash_payload("git --work-tree=/tmp status"))

    def test_dangerous_git_command_denied(self):
        self.assert_denied(bash_payload("git reset --hard HEAD~1"))

    def test_git_clean_force_forms_denied(self):
        # `-[^\s]*f\b` matched only a flag cluster ending in f, so `git clean -fd`
        # — which still deletes untracked files — slipped through.
        commands = (
            "git clean -f target",
            "git clean -fd target",
            "git clean -ffdx",
            "git clean -d -f target",
            "git clean --force",
            "git -C /some/repo clean -fd",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(bash_payload(command))

    def test_git_clean_dry_run_allowed(self):
        for command in ("git clean -n", "git clean -nd"):
            with self.subTest(command=command):
                self.assert_allowed(bash_payload(command))

    def test_recursive_force_rm_forms_denied(self):
        commands = (
            "rm -r -f directory",
            "rm -R -f directory",
            "rm -r --force directory",
            "rm --recursive -f directory",
            "rm --recursive --force directory",
            "rm -fr directory",
            "rm -rf directory",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(bash_payload(command))

    def test_non_recursive_or_non_force_rm_does_not_trigger_rule(self):
        for command in ("rm -f one-file", "rm -r one-directory"):
            with self.subTest(command=command):
                self.assert_allowed(bash_payload(command))

    def test_quoted_rm_text_argument_does_not_trigger_rule(self):
        self.assert_allowed(bash_payload("echo 'rm -rf example'"))

    def test_protected_or_sensitive_path_denied(self):
        self.assert_denied(apply_patch_payload(
            "*** Begin Patch\n*** Add File: config/secrets/api-key.txt\n+token\n*** End Patch"
        ))

    def test_safe_shell_command_inside_worktree(self):
        self.assert_allowed(bash_payload(
            f"cd {self.worktree} && git status --short"
        ))

    def test_denial_does_not_leak_secret_or_full_patch(self):
        secret = "TOP_SECRET_VALUE_9f3c"
        patch = (
            "*** Begin Patch\n*** Add File: ../unsafe.txt\n+" + secret +
            "\n+unrelated patch body\n*** End Patch"
        )
        result = self.assert_denied(apply_patch_payload(patch))
        combined = result.stdout + result.stderr
        self.assertNotIn(secret, combined)
        self.assertNotIn("unrelated patch body", combined)
        self.assertNotIn(patch, combined)

    def test_structured_deny_or_exit_code_two_fallback(self):
        result = self.assert_denied(bash_payload("rm -rf ."))
        if result.returncode == 0:
            output = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "PreToolUse")
            self.assertEqual(output["permissionDecision"], "deny")
            self.assertTrue(output["permissionDecisionReason"])
        else:
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr.strip())

    def test_malformed_json_fails_safely(self):
        result = self.assert_denied('{"tool_name":')
        self.assertNotIn('{"tool_name":', result.stdout + result.stderr)

    def test_unsupported_tool_allows_without_mutation(self):
        sentinel = self.worktree / "sentinel.txt"
        sentinel.write_text("unchanged", encoding="utf-8")
        self.assert_allowed({
            "tool_name": "Read",
            "tool_input": {"file_path": str(sentinel), "content": "mutated"},
        })
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_write_and_edit_aliases_are_tolerated(self):
        self.assert_allowed({
            "tool_name": "Write",
            "tool_input": {"path": "src/new.py", "content": "safe"},
        })
        self.assert_denied({
            "tool_name": "Edit",
            "tool_input": {"file_path": ".codex/config.toml", "new_string": "unsafe"},
        })


class SharedCoreMergePatternTest(unittest.TestCase):
    """devflow_guard_core feeds this guard, so its blocklist is tested here.

    `git merge-base` / `merge-tree` / `merge-file` are read-only plumbing and
    must pass; a real merge must not.
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util

        core = REPO_ROOT / "scripts" / "devflow_guard_core.py"
        spec = importlib.util.spec_from_file_location("devflow_guard_core", core)
        cls.core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.core)

    def test_real_merge_is_refused(self):
        for command in ("git merge feature/x", "git merge --no-ff x",
                        "git merge", "git -C /repo merge x"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.core.dangerous_command_reason(command))

    def test_merge_plumbing_is_allowed(self):
        for command in ("git merge-base --is-ancestor abc origin/main",
                        "git merge-base main HEAD",
                        "git merge-tree base b1 b2",
                        "git merge-file cur.py base.py other.py",
                        "git -C /repo merge-base main HEAD"):
            with self.subTest(command=command):
                self.assertIsNone(self.core.dangerous_command_reason(command))


if __name__ == "__main__":
    unittest.main()
