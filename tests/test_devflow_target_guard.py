"""
Tests for devflow_target_guard.py PreToolUse hook.

Covers:
7.  Guard blocks forbidden Git commands via simulated PreToolUse Bash payloads.
8.  Guard passes safe Git commands and test commands.
9.  Guard blocks protected target-path Write/Edit payloads.
10. Guard passes normal source, test, docs and .devflow/ paths.
11. Hook deny output does not leak raw input, token, path contents, or user data.
12. Guard is fail-closed: invalid input (empty, malformed, wrong types) exits 2.
13. Guard blocks equivalent destructive command variants (force-with-lease, --delete, -C merge, rm -fr, etc.).
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SCRIPT = REPO_ROOT / "scripts" / "devflow_target_guard.py"


def _load_guard_module():
    spec = importlib.util.spec_from_file_location("devflow_target_guard", GUARD_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_guard(payload: dict | str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the guard script with the given payload dict or JSON string as stdin.

    env: if provided, merged on top of os.environ for the subprocess. Pass a
    dict with explicit keys to add/override specific variables (including
    DEVFLOW_RUN_WORKTREE for boundary-enforcement tests).
    """
    if isinstance(payload, dict):
        stdin_data = json.dumps(payload)
    else:
        stdin_data = payload
    run_env = os.environ.copy()
    if env is not None:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=run_env,
    )


def bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def write_payload(path: str, content: str = "data") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def edit_payload(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


# ---------------------------------------------------------------------------
# Script existence
# ---------------------------------------------------------------------------

class GuardScriptExistsTest(unittest.TestCase):

    def test_guard_script_exists(self):
        self.assertTrue(GUARD_SCRIPT.exists(), f"Guard script not found: {GUARD_SCRIPT}")

    def test_guard_script_no_third_party_imports(self):
        content = GUARD_SCRIPT.read_text(encoding="utf-8")
        for lib in ["import requests", "import boto3", "import anthropic", "import openai", "import flask"]:
            self.assertNotIn(lib, content, f"Guard must not import {lib}")

    def test_guard_script_has_main(self):
        content = GUARD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__"', content)

    def test_guard_script_documents_scope(self):
        content = GUARD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("terminal", content.lower(), "Guard must document it doesn't protect terminal")

    def test_guard_exit_codes_documented(self):
        content = GUARD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("0", content)
        self.assertIn("2", content)


# ---------------------------------------------------------------------------
# Test 7: Blocked Bash — forbidden Git commands
# ---------------------------------------------------------------------------

class ForbiddenBashTest(unittest.TestCase):

    def _assert_blocked(self, command: str):
        result = run_guard(bash_payload(command))
        self.assertEqual(
            result.returncode, 2,
            f"Command should be blocked (exit 2): {command!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_git_merge_blocked(self):
        self._assert_blocked("git merge feature/my-branch")

    def test_git_merge_with_flags_blocked(self):
        self._assert_blocked("git merge --no-ff feature/abc")

    def test_git_push_force_blocked(self):
        self._assert_blocked("git push --force origin main")

    def test_git_push_f_blocked(self):
        self._assert_blocked("git push -f origin main")

    def test_git_branch_delete_lowercase_blocked(self):
        self._assert_blocked("git branch -d old-feature")

    def test_git_branch_delete_uppercase_blocked(self):
        self._assert_blocked("git branch -D old-feature")

    def test_git_reset_hard_blocked(self):
        self._assert_blocked("git reset --hard HEAD~1")

    def test_git_reset_hard_no_args_blocked(self):
        self._assert_blocked("git reset --hard")

    def test_git_reset_soft_blocked(self):
        self._assert_blocked("git reset --soft HEAD~1")

    def test_git_reset_mixed_blocked(self):
        self._assert_blocked("git reset --mixed HEAD~1")

    def test_git_clean_f_blocked(self):
        self._assert_blocked("git clean -f")

    def test_git_clean_f_with_path_blocked(self):
        self._assert_blocked("git clean -f src/")

    def test_git_checkout_double_dash_dot_blocked(self):
        self._assert_blocked("git checkout -- .")

    def test_git_restore_dot_blocked(self):
        self._assert_blocked("git restore .")

    def test_rm_rf_blocked(self):
        self._assert_blocked("rm -rf /tmp/something")

    def test_rm_rf_current_dir_blocked(self):
        self._assert_blocked("rm -rf .")

    # --- Test 13: Equivalent destructive command variants ---

    def test_git_push_force_after_remote_blocked(self):
        self._assert_blocked("git push origin main --force")

    def test_git_push_force_with_lease_blocked(self):
        self._assert_blocked("git push --force-with-lease origin main")

    def test_git_branch_delete_long_form_blocked(self):
        self._assert_blocked("git branch --delete old-branch")

    def test_git_c_merge_blocked(self):
        self._assert_blocked("git -C /some/repo merge feature/x")

    def test_rm_fr_blocked(self):
        self._assert_blocked("rm -fr /tmp/example")

    def test_rm_long_recursive_force_blocked(self):
        self._assert_blocked("rm --recursive --force /tmp/example")

    def test_rm_long_force_recursive_blocked(self):
        self._assert_blocked("rm --force --recursive /tmp/example")


# ---------------------------------------------------------------------------
# Test 8: Allowed Bash — safe Git commands and test commands
# ---------------------------------------------------------------------------

class SafeBashTest(unittest.TestCase):

    def _assert_allowed(self, command: str):
        result = run_guard(bash_payload(command))
        self.assertEqual(
            result.returncode, 0,
            f"Command should be allowed (exit 0): {command!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_git_status_allowed(self):
        self._assert_allowed("git status")

    def test_git_diff_allowed(self):
        self._assert_allowed("git diff HEAD")

    def test_git_add_allowed(self):
        self._assert_allowed("git add src/api.py")

    def test_git_add_dot_allowed(self):
        self._assert_allowed("git add .")

    def test_git_commit_allowed(self):
        self._assert_allowed("git commit -m 'fix: update handler'")

    def test_git_push_normal_allowed(self):
        self._assert_allowed("git push origin devflow/run-run-001")

    def test_git_push_upstream_allowed(self):
        self._assert_allowed("git push -u origin feature-branch")

    def test_git_worktree_add_allowed(self):
        self._assert_allowed("git worktree add -b devflow/run-run-001 /path/to/wt HEAD")

    def test_git_log_allowed(self):
        self._assert_allowed("git log --oneline -10")

    def test_git_branch_list_allowed(self):
        self._assert_allowed("git branch --list devflow/run-*")

    def test_python_test_allowed(self):
        self._assert_allowed("python3 -m unittest discover -s tests -p 'test_*.py' -v")

    def test_pytest_allowed(self):
        self._assert_allowed("pytest tests/ -v")

    def test_ls_allowed(self):
        self._assert_allowed("ls -la src/")

    def test_git_checkout_branch_allowed(self):
        self._assert_allowed("git checkout main")

    def test_git_checkout_new_branch_allowed(self):
        self._assert_allowed("git checkout -b feature/new-api")

    def test_rm_single_file_allowed(self):
        self._assert_allowed("rm /tmp/somefile.txt")

    def test_rm_r_without_f_allowed(self):
        self._assert_allowed("rm -r /tmp/some_dir")

    def test_git_restore_specific_file_allowed(self):
        self._assert_allowed("git restore src/some_file.py")


# ---------------------------------------------------------------------------
# Test 9: Blocked Write / Edit — protected paths
# ---------------------------------------------------------------------------

class ProtectedPathWriteTest(unittest.TestCase):

    def _assert_write_blocked(self, path: str):
        result = run_guard(write_payload(path))
        self.assertEqual(
            result.returncode, 2,
            f"Write to path should be blocked (exit 2): {path!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def _assert_edit_blocked(self, path: str):
        result = run_guard(edit_payload(path))
        self.assertEqual(
            result.returncode, 2,
            f"Edit to path should be blocked (exit 2): {path!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_env_file_write_blocked(self):
        self._assert_write_blocked("/project/.env")

    def test_env_local_write_blocked(self):
        self._assert_write_blocked("/project/.env.local")

    def test_env_production_write_blocked(self):
        self._assert_write_blocked("/project/.env.production")

    def test_env_test_write_blocked(self):
        self._assert_write_blocked(".env.test")

    def test_credentials_file_write_blocked(self):
        self._assert_write_blocked("/project/credentials.json")

    def test_credential_dir_write_blocked(self):
        self._assert_write_blocked("/project/credential/key.pem")

    def test_secrets_file_write_blocked(self):
        self._assert_write_blocked("/project/secrets/api_key.txt")

    def test_secret_file_write_blocked(self):
        self._assert_write_blocked("config/secret.yaml")

    def test_mcp_json_write_blocked(self):
        self._assert_write_blocked("/project/.mcp.json")

    def test_mcp_json_no_dot_write_blocked(self):
        self._assert_write_blocked("/project/mcp.json")

    def test_mcp_config_write_blocked(self):
        self._assert_write_blocked("/project/mcp_config.json")

    def test_claude_settings_write_blocked(self):
        self._assert_write_blocked("/project/.claude/settings.json")

    def test_claude_settings_local_write_blocked(self):
        self._assert_write_blocked("/project/.claude/settings.local.json")

    def test_claude_hooks_write_blocked(self):
        self._assert_write_blocked("/project/.claude/hooks/my-hook.sh")

    def test_claude_hooks_nested_write_blocked(self):
        self._assert_write_blocked("/project/.claude/hooks/enforce-role-boundaries.sh")

    def test_env_file_edit_blocked(self):
        self._assert_edit_blocked("/project/.env")

    def test_claude_settings_edit_blocked(self):
        self._assert_edit_blocked(".claude/settings.json")


# ---------------------------------------------------------------------------
# Test 10: Allowed Write / Edit — safe paths
# ---------------------------------------------------------------------------

class SafePathWriteTest(unittest.TestCase):

    def _assert_write_allowed(self, path: str):
        result = run_guard(write_payload(path))
        self.assertEqual(
            result.returncode, 0,
            f"Write to path should be allowed (exit 0): {path!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def _assert_edit_allowed(self, path: str):
        result = run_guard(edit_payload(path))
        self.assertEqual(
            result.returncode, 0,
            f"Edit to path should be allowed (exit 0): {path!r}\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_source_file_write_allowed(self):
        self._assert_write_allowed("/project/src/api/handler.py")

    def test_test_file_write_allowed(self):
        self._assert_write_allowed("/project/tests/test_api.py")

    def test_docs_file_write_allowed(self):
        self._assert_write_allowed("/project/docs/requirements/REQ-001.md")

    def test_devflow_context_write_allowed(self):
        self._assert_write_allowed("/project/.devflow/context/RUN-001-context-pack.md")

    def test_devflow_plans_write_allowed(self):
        self._assert_write_allowed("/project/.devflow/plans/RUN-001-task-graph.md")

    def test_devflow_runs_write_blocked(self):
        result = run_guard(write_payload("/project/.devflow/runs/RUN-001.json"))
        self.assertEqual(result.returncode, 2,
                         "Write to .devflow/runs/ must be blocked (canonical run state)")

    def test_devflow_reports_write_blocked(self):
        result = run_guard(write_payload("/project/.devflow/reports/RUN-001-delivery-summary.md"))
        self.assertEqual(result.returncode, 2,
                         "Write to .devflow/reports/ must be blocked (canonical scorecard)")

    def test_devflow_delegation_events_write_allowed(self):
        self._assert_write_allowed("/project/.devflow/delegation-events/evt-001.json")

    def test_readme_write_allowed(self):
        self._assert_write_allowed("/project/README.md")

    def test_python_source_write_allowed(self):
        self._assert_write_allowed("src/models/user.py")

    def test_js_source_edit_allowed(self):
        self._assert_edit_allowed("src/components/Button.tsx")

    def test_yaml_config_edit_allowed(self):
        self._assert_edit_allowed("config/app.yaml")

    def test_gitignore_edit_allowed(self):
        self._assert_edit_allowed(".gitignore")

    def test_requirements_txt_write_allowed(self):
        self._assert_write_allowed("requirements.txt")

    def test_package_json_write_allowed(self):
        self._assert_write_allowed("package.json")

    def test_acceptance_criteria_write_allowed(self):
        self._assert_write_allowed(
            "/project/docs/product/acceptance-criteria/AC-REQ-001.md"
        )


# ---------------------------------------------------------------------------
# Test 11: Deny output must not leak user data
# ---------------------------------------------------------------------------

class DenyOutputLeakTest(unittest.TestCase):

    def test_bash_deny_does_not_echo_command(self):
        secret_branch = "feature/my-very-secret-branch-name"
        result = run_guard(bash_payload(f"git merge {secret_branch}"))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(secret_branch, result.stderr)
        self.assertNotIn("git merge", result.stderr)

    def test_bash_deny_does_not_echo_path_args(self):
        result = run_guard(bash_payload("rm -rf /home/user/sensitive-data"))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("sensitive-data", result.stderr)
        self.assertNotIn("/home/user", result.stderr)

    def test_write_deny_does_not_echo_path(self):
        secret_path = "/project/secrets/my_api_key.txt"
        result = run_guard(write_payload(secret_path, "SECRET_KEY=abc123"))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(secret_path, result.stderr)
        self.assertNotIn("my_api_key.txt", result.stderr)
        self.assertNotIn("abc123", result.stderr)
        self.assertNotIn("SECRET_KEY", result.stderr)

    def test_write_deny_does_not_echo_file_content(self):
        result = run_guard(write_payload(".env", "TOKEN=supersecret_value_12345"))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("supersecret_value_12345", result.stderr)
        self.assertNotIn("TOKEN", result.stderr)

    def test_deny_message_is_short_and_fixed(self):
        """Deny messages should be short and deterministic."""
        result1 = run_guard(bash_payload("git merge branch-a"))
        result2 = run_guard(bash_payload("git merge branch-b"))
        self.assertEqual(result1.stderr.strip(), result2.stderr.strip())

    def test_path_deny_message_is_fixed(self):
        result1 = run_guard(write_payload(".env"))
        result2 = run_guard(write_payload("credentials.json"))
        self.assertEqual(result1.stderr.strip(), result2.stderr.strip())


# ---------------------------------------------------------------------------
# Test 12: Guard is fail-closed — invalid input exits 2
# ---------------------------------------------------------------------------

class GuardFailClosedTest(unittest.TestCase):

    def test_empty_input_blocked(self):
        """Empty stdin must be blocked (fail-closed)."""
        result = run_guard("")
        self.assertEqual(result.returncode, 2, "Empty input must fail closed (exit 2)")

    def test_invalid_json_blocked(self):
        """Invalid JSON must be blocked (fail-closed)."""
        result = run_guard("not-json-at-all {{{")
        self.assertEqual(result.returncode, 2, "Invalid JSON must fail closed (exit 2)")

    def test_non_dict_payload_blocked(self):
        """Non-dict JSON payload must be blocked."""
        result = run_guard("[1, 2, 3]")
        self.assertEqual(result.returncode, 2)

    def test_null_payload_blocked(self):
        """Null JSON payload must be blocked."""
        result = run_guard("null")
        self.assertEqual(result.returncode, 2)

    def test_unknown_tool_name_allowed(self):
        """Unknown tool names (not Bash/Write/Edit) pass through."""
        result = run_guard({"tool_name": "Read", "tool_input": {"file_path": ".env"}})
        self.assertEqual(result.returncode, 0, "Read tool should not be blocked (only Bash/Write/Edit)")

    def test_missing_tool_input_bash_blocked(self):
        """Missing tool_input for Bash must be blocked (fail-closed)."""
        result = run_guard({"tool_name": "Bash"})
        self.assertEqual(result.returncode, 2)

    def test_non_dict_tool_input_bash_blocked(self):
        """Non-dict tool_input for Bash must be blocked."""
        result = run_guard({"tool_name": "Bash", "tool_input": "not a dict"})
        self.assertEqual(result.returncode, 2)

    def test_missing_command_bash_blocked(self):
        """Missing command key for Bash must be blocked."""
        result = run_guard({"tool_name": "Bash", "tool_input": {}})
        self.assertEqual(result.returncode, 2)

    def test_non_string_command_bash_blocked(self):
        """Non-string command for Bash must be blocked."""
        result = run_guard({"tool_name": "Bash", "tool_input": {"command": 123}})
        self.assertEqual(result.returncode, 2)

    def test_missing_file_path_write_blocked(self):
        """Missing file_path key for Write must be blocked."""
        result = run_guard({"tool_name": "Write", "tool_input": {}})
        self.assertEqual(result.returncode, 2)

    def test_non_string_file_path_write_blocked(self):
        """Non-string file_path for Write must be blocked."""
        result = run_guard({"tool_name": "Write", "tool_input": {"file_path": None}})
        self.assertEqual(result.returncode, 2)

    def test_missing_file_path_edit_blocked(self):
        """Missing file_path key for Edit must be blocked."""
        result = run_guard({"tool_name": "Edit", "tool_input": {"old_string": "a"}})
        self.assertEqual(result.returncode, 2)

    def test_empty_command_allowed(self):
        """Empty bash command string (valid string) must not be blocked."""
        result = run_guard(bash_payload(""))
        self.assertEqual(result.returncode, 0)

    def test_empty_path_allowed(self):
        """Empty file path string (valid string) must not be blocked."""
        result = run_guard(write_payload(""))
        self.assertEqual(result.returncode, 0)

    def test_validation_denial_message_is_fixed(self):
        """Validation denial produces the same fixed message regardless of input."""
        result1 = run_guard("")
        result2 = run_guard("not valid json <<<")
        self.assertEqual(result1.stderr.strip(), result2.stderr.strip())
        self.assertIn("DevFlow guard", result1.stderr)

    def test_validation_denial_does_not_leak_input(self):
        """Validation denial message must not contain raw input data."""
        secret = "super_secret_token_xyz_12345"
        result = run_guard(secret)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn("{{{", result.stderr)

    def test_non_string_tool_name_blocked(self):
        """Non-string tool_name must be blocked."""
        result = run_guard({"tool_name": 42, "tool_input": {"command": "git status"}})
        self.assertEqual(result.returncode, 2)


# ---------------------------------------------------------------------------
# Run worktree boundary — Write/Edit enforcement
# (activated when DEVFLOW_RUN_WORKTREE is set)
# ---------------------------------------------------------------------------

class RunWorktreeBoundaryWriteTest(unittest.TestCase):
    """Guard blocks Write/Edit outside DEVFLOW_RUN_WORKTREE when env var is set."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.worktree = self.tmpdir / "run_worktree"
        self.worktree.mkdir()
        self.external = self.tmpdir / "external"
        self.external.mkdir()
        # Pass the resolved path so the guard sees the same path after resolve()
        self.boundary_env = {"DEVFLOW_RUN_WORKTREE": str(self.worktree.resolve())}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_write_allowed(self, path: str):
        result = run_guard(write_payload(path), env=self.boundary_env)
        self.assertEqual(
            result.returncode, 0,
            f"Write inside worktree should be allowed (exit 0): {path!r}\n"
            f"stderr={result.stderr}",
        )

    def _assert_write_blocked(self, path: str):
        result = run_guard(write_payload(path), env=self.boundary_env)
        self.assertEqual(
            result.returncode, 2,
            f"Write outside worktree should be blocked (exit 2): {path!r}\n"
            f"stderr={result.stderr}",
        )

    def test_write_inside_worktree_allowed(self):
        path = str(self.worktree / "src" / "api.py")
        self._assert_write_allowed(path)

    def test_write_absolute_external_denied(self):
        path = str(self.external / "file.py")
        self._assert_write_blocked(path)

    def test_edit_inside_worktree_allowed(self):
        path = str(self.worktree / "tests" / "test_api.py")
        result = run_guard(edit_payload(path), env=self.boundary_env)
        self.assertEqual(result.returncode, 0,
                         f"Edit inside worktree should be allowed: {path!r}")

    def test_edit_absolute_external_denied(self):
        path = str(self.external / "file.py")
        result = run_guard(edit_payload(path), env=self.boundary_env)
        self.assertEqual(result.returncode, 2,
                         f"Edit outside worktree should be blocked: {path!r}")

    def test_write_dotdot_escape_denied(self):
        # Absolute path that traverses above the worktree via ..
        path = str(self.worktree / ".." / "external" / "escaped.py")
        self._assert_write_blocked(path)

    def test_write_symlink_escape_denied(self):
        # Symlink inside worktree pointing to external dir
        link = self.worktree / "link_to_external"
        link.symlink_to(self.external)
        path = str(link / "file.py")
        self._assert_write_blocked(path)

    def test_deny_message_does_not_echo_path(self):
        path = str(self.external / "secret_output.py")
        result = run_guard(write_payload(path), env=self.boundary_env)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(str(self.external), result.stderr)
        self.assertNotIn("secret_output", result.stderr)

    def test_boundary_message_is_fixed(self):
        path1 = str(self.external / "a.py")
        path2 = str(self.external / "b.py")
        r1 = run_guard(write_payload(path1), env=self.boundary_env)
        r2 = run_guard(write_payload(path2), env=self.boundary_env)
        self.assertEqual(r1.returncode, 2)
        self.assertEqual(r2.returncode, 2)
        self.assertEqual(r1.stderr.strip(), r2.stderr.strip())


# ---------------------------------------------------------------------------
# Backward compatibility — no boundary when DEVFLOW_RUN_WORKTREE is absent
# ---------------------------------------------------------------------------

class NoBoundaryWithoutEnvTest(unittest.TestCase):
    """When DEVFLOW_RUN_WORKTREE is not set, boundary enforcement is inactive."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.external = self.tmpdir / "external"
        self.external.mkdir()
        # Env without DEVFLOW_RUN_WORKTREE
        self.no_boundary_env = {
            k: v for k, v in os.environ.items() if k != "DEVFLOW_RUN_WORKTREE"
        }

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_external_allowed_without_boundary(self):
        path = str(self.external / "file.py")
        result = run_guard(write_payload(path), env=self.no_boundary_env)
        self.assertEqual(
            result.returncode, 0,
            f"Without DEVFLOW_RUN_WORKTREE, external path should not be blocked: {path!r}",
        )

    def test_edit_external_allowed_without_boundary(self):
        path = str(self.external / "file.py")
        result = run_guard(edit_payload(path), env=self.no_boundary_env)
        self.assertEqual(result.returncode, 0)

    def test_cd_external_allowed_without_boundary(self):
        cmd = f"cd {self.external}"
        result = run_guard(bash_payload(cmd), env=self.no_boundary_env)
        self.assertEqual(
            result.returncode, 0,
            "Without DEVFLOW_RUN_WORKTREE, cd to external path must not be blocked",
        )


# ---------------------------------------------------------------------------
# Bash boundary — cd / git -C / git --work-tree enforcement
# ---------------------------------------------------------------------------

class BashBoundaryTest(unittest.TestCase):
    """Guard blocks explicit navigation outside DEVFLOW_RUN_WORKTREE in Bash."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.worktree = self.tmpdir / "run_worktree"
        self.worktree.mkdir()
        self.external = self.tmpdir / "external"
        self.external.mkdir()
        self.boundary_env = {"DEVFLOW_RUN_WORKTREE": str(self.worktree.resolve())}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_bash_allowed(self, cmd: str):
        result = run_guard(bash_payload(cmd), env=self.boundary_env)
        self.assertEqual(
            result.returncode, 0,
            f"Bash command should be allowed (exit 0): {cmd!r}\nstderr={result.stderr}",
        )

    def _assert_bash_blocked(self, cmd: str):
        result = run_guard(bash_payload(cmd), env=self.boundary_env)
        self.assertEqual(
            result.returncode, 2,
            f"Bash command should be blocked (exit 2): {cmd!r}\nstderr={result.stderr}",
        )

    # --- cd tests ---

    def test_cd_inside_worktree_allowed(self):
        self._assert_bash_allowed(f"cd {self.worktree}")

    def test_cd_absolute_external_blocked(self):
        self._assert_bash_blocked(f"cd {self.external}")

    def test_cd_dotdot_escape_blocked(self):
        # Absolute path with .. that resolves outside worktree
        escape = str(self.worktree / ".." / "external")
        self._assert_bash_blocked(f"cd {escape}")

    def test_cd_devflow_run_worktree_var_allowed(self):
        # cd "$DEVFLOW_RUN_WORKTREE" must always be allowed
        self._assert_bash_allowed('cd "$DEVFLOW_RUN_WORKTREE"')

    def test_cd_simple_relative_allowed(self):
        # Simple relative paths (no ..) are not checked — CWD unknown at hook time
        self._assert_bash_allowed("cd src")

    # --- git -C tests ---

    def test_git_c_inside_worktree_allowed(self):
        self._assert_bash_allowed(f"git -C {self.worktree} status")

    def test_git_c_external_blocked(self):
        self._assert_bash_blocked(f"git -C {self.external} status")

    def test_git_c_dotdot_escape_blocked(self):
        escape = str(self.worktree / ".." / "external")
        self._assert_bash_blocked(f"git -C {escape} status")

    # --- git --work-tree tests ---

    def test_git_work_tree_space_external_blocked(self):
        self._assert_bash_blocked(f"git --work-tree {self.external} status")

    def test_git_work_tree_eq_external_blocked(self):
        self._assert_bash_blocked(f"git --work-tree={self.external} status")

    def test_git_work_tree_space_inside_allowed(self):
        self._assert_bash_allowed(f"git --work-tree {self.worktree} status")

    def test_git_work_tree_eq_inside_allowed(self):
        self._assert_bash_allowed(f"git --work-tree={self.worktree} status")

    def test_bash_boundary_deny_message_is_fixed(self):
        cmd1 = f"cd {self.external}"
        cmd2 = f"git -C {self.external} status"
        r1 = run_guard(bash_payload(cmd1), env=self.boundary_env)
        r2 = run_guard(bash_payload(cmd2), env=self.boundary_env)
        self.assertEqual(r1.returncode, 2)
        self.assertEqual(r2.returncode, 2)
        self.assertEqual(r1.stderr.strip(), r2.stderr.strip())

    def test_bash_boundary_deny_does_not_echo_path(self):
        cmd = f"cd {self.external}"
        result = run_guard(bash_payload(cmd), env=self.boundary_env)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(str(self.external), result.stderr)


if __name__ == "__main__":
    unittest.main()
