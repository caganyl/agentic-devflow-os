"""
Tests for devflow_operations.py managed operations runner.

Covers:
1.  Valid git repo init-target → .devflow/ structure created (non-protected branch)
2.  Framework repo rejected as target
3.  Non-git path rejected
4.  Second init preserves existing state
5.  create-run produces deterministic run state and branch name
6.  prepare-delivery rejects main branch
7.  Forbidden git operations blocked by string validation
8.  Plugin build output includes operations script
9.  Plugin build output excludes hooks/settings/MCP
10. Source register rejects raw credentials and notebook content
11. init-target rejected on protected branches (main/master)
12. create-run rejected on protected branches
13. launch --dry-run creates no branch, worktree, or .devflow/
14. launch dry-run plan shows correct run branch and managed worktree path
15. launch dry-run shows --plugin-dir in claude command, no --print/-p
16. launch creates real worktree and run state in it (not in main checkout)
17. launch rejected when branch or worktree already exists (collision)
18. plugin copy devflow_operations.py gives clear framework runner error on launch
19. prepare-delivery makes no real git mutations; --confirm-delivery is gate validation only
"""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPS_SCRIPT = REPO_ROOT / "scripts" / "devflow_operations.py"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_devflow_plugin.py"


def _load_ops_module():
    spec = importlib.util.spec_from_file_location("devflow_ops", OPS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_git_repo(path: Path, branch: str = "main", feature_branch=None) -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@devflow.test"],
        check=True, capture_output=True, cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "DevFlow Test"],
        check=True, capture_output=True, cwd=str(path),
    )
    readme = path / "README.md"
    readme.write_text("test project\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True, capture_output=True, cwd=str(path),
    )
    if feature_branch:
        subprocess.run(
            ["git", "checkout", "-b", feature_branch],
            check=True, capture_output=True, cwd=str(path),
        )


def run_ops(args: list, env=None, **kwargs) -> subprocess.CompletedProcess:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(OPS_SCRIPT)] + args,
        capture_output=True,
        text=True,
        env=run_env,
        **kwargs,
    )


def _remove_worktrees_and_cleanup(target: Path, tmpdir: Path) -> None:
    """Remove any git worktrees before deleting the temp directory."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(target),
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                wt_path = line.split(" ", 1)[1].strip()
                if wt_path != str(target):
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", wt_path],
                        cwd=str(target),
                        capture_output=True,
                    )
    except Exception:
        pass
    shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Script existence and structure
# ---------------------------------------------------------------------------

class OpsScriptBasicTest(unittest.TestCase):

    def test_ops_script_exists(self):
        self.assertTrue(OPS_SCRIPT.exists(), f"devflow_operations.py not found: {OPS_SCRIPT}")

    def test_ops_script_no_third_party_imports(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for lib in ["import requests", "import boto3", "import anthropic", "import openai", "import flask"]:
            self.assertNotIn(lib, content, f"Script must not import {lib}")

    def test_ops_script_has_main(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__"', content)

    def test_ops_script_has_all_subcommands(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for cmd in ["init-target", "create-run", "launch", "status", "prepare-delivery"]:
            self.assertIn(cmd, content, f"Script missing subcommand: {cmd}")

    def test_ops_script_documents_forbidden_ops(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for op in ["merge", "push --force", "reset --hard", "branch -D", "branch -d"]:
            self.assertIn(op, content, f"Script missing forbidden op: {op}")

    def test_ops_script_execv_no_print_flag(self):
        """The execv call must not use --print or -p (interactive mode required)."""
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('"--print"', content)
        self.assertNotIn("'--print'", content)

    def test_ops_script_execv_has_plugin_dir(self):
        """The execv call must include --plugin-dir."""
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--plugin-dir", content)

    def test_ops_script_documents_exit_codes(self):
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        for code in ["11", "12"]:
            self.assertIn(code, content, f"Script missing exit code {code} documentation")


# ---------------------------------------------------------------------------
# Test 1: Valid git repo init-target creates .devflow/ structure
# ---------------------------------------------------------------------------

class InitTargetTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test-setup")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_devflow_dir(self):
        result = run_ops(["init-target", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / ".devflow").exists())

    def test_init_creates_all_subdirs(self):
        run_ops(["init-target", "--target", str(self.target)])
        devflow = self.target / ".devflow"
        for subdir in ["context", "plans", "task-packets", "runs", "reports", "cache", "logs"]:
            self.assertTrue((devflow / subdir).exists(), f".devflow/{subdir} missing")

    def test_init_creates_project_json(self):
        run_ops(["init-target", "--target", str(self.target)])
        project_json = self.target / ".devflow" / "project.json"
        self.assertTrue(project_json.exists())
        data = json.loads(project_json.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "1")
        self.assertIn("initialized_at", data)
        self.assertEqual(data["run_counter"], 0)
        self.assertIsNone(data["current_run_id"])

    def test_init_creates_policy_json(self):
        run_ops(["init-target", "--target", str(self.target)])
        policy_json = self.target / ".devflow" / "policy.json"
        self.assertTrue(policy_json.exists())
        data = json.loads(policy_json.read_text(encoding="utf-8"))
        self.assertIn("forbidden_git_operations", data)
        self.assertIsInstance(data["forbidden_git_operations"], list)
        self.assertGreater(len(data["forbidden_git_operations"]), 0)
        self.assertTrue(data.get("require_confirm_delivery"))
        self.assertTrue(data.get("dry_run_by_default"))

    def test_init_creates_source_register_json(self):
        run_ops(["init-target", "--target", str(self.target)])
        sr = self.target / ".devflow" / "source-register.json"
        self.assertTrue(sr.exists())
        data = json.loads(sr.read_text(encoding="utf-8"))
        self.assertIn("sources", data)
        self.assertIsInstance(data["sources"], list)

    def test_init_creates_devflow_gitignore(self):
        run_ops(["init-target", "--target", str(self.target)])
        gitignore = self.target / ".devflow" / ".gitignore"
        self.assertTrue(gitignore.exists())
        content = gitignore.read_text(encoding="utf-8")
        self.assertIn("cache/", content)
        self.assertIn("logs/", content)

    def test_policy_protects_main(self):
        run_ops(["init-target", "--target", str(self.target)])
        data = json.loads((self.target / ".devflow" / "policy.json").read_text(encoding="utf-8"))
        protected = data.get("protected_branches", [])
        self.assertIn("main", protected)


# ---------------------------------------------------------------------------
# Tests 2 & 3: Framework repo and non-git path rejected
# ---------------------------------------------------------------------------

class InitTargetRejectionTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_framework_repo_rejected(self):
        result = run_ops(["init-target", "--target", str(REPO_ROOT)])
        self.assertNotEqual(result.returncode, 0, "Framework repo should be rejected as target")
        self.assertIn("Hata", result.stderr)

    def test_non_git_directory_rejected(self):
        non_git = self.tmpdir / "not-a-repo"
        non_git.mkdir()
        result = run_ops(["init-target", "--target", str(non_git)])
        self.assertNotEqual(result.returncode, 0, "Non-git dir should be rejected")
        self.assertIn("Hata", result.stderr)

    def test_nonexistent_path_rejected(self):
        result = run_ops(["init-target", "--target", "/nonexistent/path/devflow_xyz_test"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Hata", result.stderr)

    def test_framework_repo_exit_code_is_2(self):
        result = run_ops(["init-target", "--target", str(REPO_ROOT)])
        self.assertEqual(result.returncode, 2)

    def test_non_git_exit_code_is_3(self):
        non_git = self.tmpdir / "plain-dir"
        non_git.mkdir()
        result = run_ops(["init-target", "--target", str(non_git)])
        self.assertEqual(result.returncode, 3)


# ---------------------------------------------------------------------------
# Test 4: Second init does not overwrite existing state
# ---------------------------------------------------------------------------

class InitIdempotencyTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test-setup")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_second_init_preserves_run_counter(self):
        run_ops(["init-target", "--target", str(self.target)])
        devflow = self.target / ".devflow"
        data = json.loads((devflow / "project.json").read_text(encoding="utf-8"))
        data["run_counter"] = 7
        data["current_run_id"] = "RUN-007"
        (devflow / "project.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        result = run_ops(["init-target", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0)
        data_after = json.loads((devflow / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(data_after["run_counter"], 7, "run_counter must not be reset on second init")
        self.assertEqual(data_after["current_run_id"], "RUN-007")

    def test_second_init_preserves_source_register(self):
        run_ops(["init-target", "--target", str(self.target)])
        devflow = self.target / ".devflow"
        sr_path = devflow / "source-register.json"
        data = json.loads(sr_path.read_text(encoding="utf-8"))
        data["sources"].append({"id": "test-src", "type": "local_docs", "label": "test"})
        sr_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        run_ops(["init-target", "--target", str(self.target)])
        data_after = json.loads(sr_path.read_text(encoding="utf-8"))
        ids = [s["id"] for s in data_after.get("sources", [])]
        self.assertIn("test-src", ids, "source-register should be preserved on second init")

    def test_force_flag_resets_state(self):
        run_ops(["init-target", "--target", str(self.target)])
        devflow = self.target / ".devflow"
        data = json.loads((devflow / "project.json").read_text(encoding="utf-8"))
        data["run_counter"] = 5
        (devflow / "project.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        run_ops(["init-target", "--target", str(self.target), "--force"])
        data_after = json.loads((devflow / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(data_after["run_counter"], 0, "force should reset run_counter")


# ---------------------------------------------------------------------------
# Test 5: create-run produces deterministic run state and branch name
# ---------------------------------------------------------------------------

class CreateRunTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test-setup")
        run_ops(["init-target", "--target", str(self.target)])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_run_succeeds(self):
        result = run_ops(["create-run", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_id_format(self):
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        run_id = project_data["current_run_id"]
        import re
        self.assertRegex(run_id, r"^RUN-\d{3}$")

    def test_branch_name_starts_with_prefix(self):
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        run_id = project_data["current_run_id"]
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        self.assertTrue(run_file.exists())
        run_data = json.loads(run_file.read_text(encoding="utf-8"))
        self.assertTrue(
            run_data["branch_name"].startswith("devflow/run-"),
            f"Branch name should start with devflow/run-: {run_data['branch_name']}",
        )

    def test_run_state_file_created(self):
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        run_id = project_data["current_run_id"]
        run_file = self.target / ".devflow" / "runs" / f"{run_id}.json"
        self.assertTrue(run_file.exists())

    def test_run_counter_increments_sequentially(self):
        run_ops(["create-run", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        self.assertEqual(project_data["run_counter"], 2)
        self.assertEqual(project_data["current_run_id"], "RUN-002")

    def test_run_has_approval_gates(self):
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        run_id = project_data["current_run_id"]
        run_data = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
        )
        self.assertIn("approval_gates", run_data)
        gates = run_data["approval_gates"]
        for gate in ["contract_approved", "tests_passing", "security_review_complete", "qa_sign_off", "human_approval"]:
            self.assertIn(gate, gates)
            self.assertFalse(gates[gate], f"Gate {gate} should start as False")

    def test_run_state_schema_version(self):
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        run_id = project_data["current_run_id"]
        run_data = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(run_data["schema_version"], "1")
        self.assertEqual(run_data["run_id"], run_id)

    def test_branch_name_contains_run_id(self):
        run_ops(["create-run", "--target", str(self.target)])
        project_data = json.loads(
            (self.target / ".devflow" / "project.json").read_text(encoding="utf-8")
        )
        run_id = project_data["current_run_id"]
        run_data = json.loads(
            (self.target / ".devflow" / "runs" / f"{run_id}.json").read_text(encoding="utf-8")
        )
        run_id_lower = run_id.lower().replace("_", "-")
        self.assertIn(run_id_lower, run_data["branch_name"])


# ---------------------------------------------------------------------------
# Test 6: prepare-delivery rejects main branch
# ---------------------------------------------------------------------------

class PrepareDeliveryOnMainTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        # Init and create-run on a feature branch, then switch to main for the test
        make_git_repo(self.target, branch="main", feature_branch="devflow/setup")
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target)])
        subprocess.run(
            ["git", "checkout", "main"],
            check=True, capture_output=True, cwd=str(self.target),
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_prepare_delivery_rejects_main(self):
        result = run_ops(["prepare-delivery", "--target", str(self.target)])
        self.assertNotEqual(result.returncode, 0, "prepare-delivery should reject main branch")
        self.assertIn("Hata", result.stderr)

    def test_prepare_delivery_on_main_exit_code_7(self):
        result = run_ops(["prepare-delivery", "--target", str(self.target)])
        self.assertEqual(result.returncode, 7)

    def test_prepare_delivery_on_feature_branch_accepted(self):
        subprocess.run(
            ["git", "checkout", "-b", "devflow/run-run-001"],
            check=True, capture_output=True, cwd=str(self.target),
        )
        result = run_ops(["prepare-delivery", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Test 7: Forbidden git operations blocked
# ---------------------------------------------------------------------------

class ForbiddenGitOperationsTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def test_merge_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git merge main")
        self.assertEqual(ctx.exception.code, 8)

    def test_force_push_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git push --force origin main")
        self.assertEqual(ctx.exception.code, 8)

    def test_force_push_short_flag_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git push -f")
        self.assertEqual(ctx.exception.code, 8)

    def test_reset_hard_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git reset --hard HEAD~1")
        self.assertEqual(ctx.exception.code, 8)

    def test_reset_soft_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git reset --soft HEAD~1")
        self.assertEqual(ctx.exception.code, 8)

    def test_branch_delete_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git branch -D feature/old")
        self.assertEqual(ctx.exception.code, 8)

    def test_branch_delete_lowercase_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git branch -d old-branch")
        self.assertEqual(ctx.exception.code, 8)

    def test_clean_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_forbidden_git_operation("git clean -f")
        self.assertEqual(ctx.exception.code, 8)

    def test_safe_add_allowed(self):
        try:
            self.mod.validate_forbidden_git_operation("git add .")
        except SystemExit:
            self.fail("git add should not be blocked")

    def test_safe_commit_allowed(self):
        try:
            self.mod.validate_forbidden_git_operation("git commit -m 'fix: something'")
        except SystemExit:
            self.fail("git commit should not be blocked")

    def test_safe_push_allowed(self):
        try:
            self.mod.validate_forbidden_git_operation("git push origin devflow/run-run-001")
        except SystemExit:
            self.fail("git push (without --force) should not be blocked")

    def test_validate_is_string_check_not_runtime_hook(self):
        """validate_forbidden_git_operation validates planned strings, not OS-level git."""
        content = OPS_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NOT a runtime git hook", content)


# ---------------------------------------------------------------------------
# Tests 8 & 9: Plugin build includes operations script, excludes sensitive files
# ---------------------------------------------------------------------------

class PluginBuildOperationsTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.output_dir = self.tmpdir
        self.plugin_dir = self.output_dir / "devflow-plugin"

        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--output-dir", str(self.output_dir)],
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

    def test_operations_script_in_plugin(self):
        ops_script = self.plugin_dir / "scripts" / "devflow_operations.py"
        self.assertTrue(
            ops_script.exists(),
            "devflow_operations.py should be in plugin output under scripts/",
        )

    def test_operations_script_is_runnable_python(self):
        ops_script = self.plugin_dir / "scripts" / "devflow_operations.py"
        if not ops_script.exists():
            self.skipTest("devflow_operations.py not in plugin output")
        content = ops_script.read_text(encoding="utf-8")
        self.assertIn("def main(", content)
        self.assertIn('if __name__ == "__main__"', content)

    def test_build_script_itself_not_in_plugin(self):
        build_in_plugin = self.plugin_dir / "scripts" / "build_devflow_plugin.py"
        self.assertFalse(
            build_in_plugin.exists(),
            "build_devflow_plugin.py should NOT be in plugin output",
        )

    def test_plugin_manifest_has_scripts_key(self):
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            self.skipTest("plugin.json not found")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertIn("scripts", data, "plugin.json should have 'scripts' key")

    def test_plugin_manifest_lists_devflow_operations(self):
        manifest = self.plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            self.skipTest("plugin.json not found")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        script_names = [s.get("name", "") for s in data.get("scripts", [])]
        self.assertIn("devflow_operations", script_names, "plugin.json should list devflow_operations")

    def test_settings_json_not_in_plugin(self):
        settings = self.plugin_dir / "settings.json"
        self.assertFalse(settings.exists(), "settings.json must NOT be in plugin output")

    def test_hooks_not_in_plugin(self):
        hooks = self.plugin_dir / "hooks"
        self.assertFalse(hooks.exists(), "hooks/ must NOT be in plugin output")

    def test_mcp_config_not_in_plugin(self):
        for fname in [".mcp.json", "mcp.json", "mcp_config.json"]:
            self.assertFalse(
                (self.plugin_dir / fname).exists(),
                f"{fname} must NOT be in plugin output",
            )

    def test_plugin_build_idempotent(self):
        result2 = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--output-dir", str(self.output_dir)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(result2.returncode, 0, "Second build run should succeed")
        ops_script = self.plugin_dir / "scripts" / "devflow_operations.py"
        self.assertTrue(ops_script.exists(), "operations script missing after second build")


# ---------------------------------------------------------------------------
# Test 10: Source register rejects raw credentials and notebook content
# ---------------------------------------------------------------------------

class SourceRegisterValidationTest(unittest.TestCase):

    def setUp(self):
        self.mod = _load_ops_module()

    def test_valid_notebooklm_entry_accepted(self):
        entry = {
            "id": "nb-1",
            "type": "notebooklm",
            "label": "Product Research Notebook",
            "freshness": "2026-06-26",
            "access_mode": "read-only",
            "relevance": "high",
            "notes": "Evidence for product decisions",
        }
        try:
            self.mod.validate_source_register_entry(entry)
        except SystemExit as e:
            self.fail(f"Valid notebooklm entry should be accepted, got exit {e.code}")

    def test_notebooklm_with_token_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "nb-1",
                "type": "notebooklm",
                "label": "My Notebook",
                "token": "eyJhbGciOiJSUzI1NiJ9.abc123",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_notebooklm_with_url_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "nb-1",
                "type": "notebooklm",
                "label": "My Notebook",
                "url": "https://notebooklm.google.com/notebook/abc123",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_notebooklm_with_notebook_content_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "nb-1",
                "type": "notebooklm",
                "label": "My Notebook",
                "notebook_content": "This is the raw notebook text...",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_notebooklm_with_raw_content_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "nb-1",
                "type": "notebooklm",
                "label": "My Notebook",
                "raw_content": "raw text here",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_any_source_with_credential_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "src-1",
                "type": "local_docs",
                "label": "Docs",
                "credential": "my-secret-token",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_any_source_with_password_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "src-1",
                "type": "git_repository",
                "label": "Repo",
                "password": "hunter2",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_any_source_with_api_key_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "src-1",
                "type": "local_docs",
                "label": "Docs",
                "api_key": "sk-abc123",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_any_source_with_secret_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            self.mod.validate_source_register_entry({
                "id": "src-1",
                "type": "obsidian",
                "label": "Notes",
                "secret": "supersecret",
            })
        self.assertEqual(ctx.exception.code, 10)

    def test_valid_git_repository_accepted(self):
        entry = {
            "id": "git-1",
            "type": "git_repository",
            "label": "Main repo",
            "relevance": "high",
            "confidence": "canonical",
            "notes": "",
        }
        try:
            self.mod.validate_source_register_entry(entry)
        except SystemExit as e:
            self.fail(f"Valid git_repository entry should be accepted, got exit {e.code}")

    def test_valid_obsidian_accepted(self):
        entry = {
            "id": "obs-1",
            "type": "obsidian",
            "label": "Product Strategy (selected notes)",
            "relevance": "medium",
            "notes": "Only selected strategic context",
        }
        try:
            self.mod.validate_source_register_entry(entry)
        except SystemExit as e:
            self.fail(f"Valid obsidian entry should be accepted, got exit {e.code}")

    def test_valid_local_docs_accepted(self):
        entry = {
            "id": "docs-1",
            "type": "local_docs",
            "label": "Architecture docs",
            "path": "docs/architecture/",
            "relevance": "high",
            "confidence": "approved",
        }
        try:
            self.mod.validate_source_register_entry(entry)
        except SystemExit as e:
            self.fail(f"Valid local_docs entry should be accepted, got exit {e.code}")


# ---------------------------------------------------------------------------
# Gitignore coverage
# ---------------------------------------------------------------------------

class GitignoreCoverageTest(unittest.TestCase):

    def test_devflow_cache_gitignored(self):
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".devflow/cache/", content)

    def test_devflow_logs_gitignored(self):
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".devflow/logs/", content)

    def test_plugin_output_gitignored(self):
        content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("dist/devflow-plugin/", content)


# ---------------------------------------------------------------------------
# Status subcommand
# ---------------------------------------------------------------------------

class StatusCommandTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, feature_branch="devflow/test-setup")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_before_init(self):
        result = run_ops(["status", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("başlatılmamış", result.stdout)

    def test_status_after_init(self):
        run_ops(["init-target", "--target", str(self.target)])
        result = run_ops(["status", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0)
        self.assertIn(str(self.target), result.stdout)

    def test_status_after_create_run(self):
        run_ops(["init-target", "--target", str(self.target)])
        run_ops(["create-run", "--target", str(self.target), "--objective", "test run"])
        result = run_ops(["status", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0)
        self.assertIn("RUN-001", result.stdout)


# ---------------------------------------------------------------------------
# New skill files exist
# ---------------------------------------------------------------------------

class NewSkillFilesTest(unittest.TestCase):

    def _skill_path(self, name: str) -> Path:
        return REPO_ROOT / ".claude" / "skills" / name / "SKILL.md"

    def test_bootstrap_target_project_exists(self):
        path = self._skill_path("bootstrap-target-project")
        self.assertTrue(path.exists(), f"Missing skill: {path}")

    def test_autonomous_delivery_run_exists(self):
        path = self._skill_path("autonomous-delivery-run")
        self.assertTrue(path.exists(), f"Missing skill: {path}")

    def test_managed_delivery_operations_exists(self):
        path = self._skill_path("managed-delivery-operations")
        self.assertTrue(path.exists(), f"Missing skill: {path}")

    def _has_yaml_frontmatter(self, path: Path) -> bool:
        content = path.read_text(encoding="utf-8")
        return content.startswith("---") and content.find("---", 3) > 3

    def test_all_new_skills_have_frontmatter(self):
        for name in ["bootstrap-target-project", "autonomous-delivery-run", "managed-delivery-operations"]:
            path = self._skill_path(name)
            if path.exists():
                self.assertTrue(self._has_yaml_frontmatter(path), f"{name} missing YAML frontmatter")

    def test_all_new_skills_have_amaç(self):
        for name in ["bootstrap-target-project", "autonomous-delivery-run", "managed-delivery-operations"]:
            path = self._skill_path(name)
            if path.exists():
                content = path.read_text(encoding="utf-8")
                self.assertIn("## Amaç", content, f"{name} missing '## Amaç' section")

    def test_all_new_skills_have_prosedür(self):
        for name in ["bootstrap-target-project", "autonomous-delivery-run", "managed-delivery-operations"]:
            path = self._skill_path(name)
            if path.exists():
                content = path.read_text(encoding="utf-8")
                self.assertIn("## Prosedür", content, f"{name} missing '## Prosedür' section")


# ---------------------------------------------------------------------------
# Test 11: init-target rejected on protected branches
# ---------------------------------------------------------------------------

class InitTargetProtectedBranchTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_repo_on_main(self) -> Path:
        target = self.tmpdir / "repo_on_main"
        target.mkdir()
        make_git_repo(target, branch="main")
        return target

    def test_init_target_rejects_main(self):
        target = self._make_repo_on_main()
        result = run_ops(["init-target", "--target", str(target)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Hata", result.stderr)

    def test_init_target_on_main_exit_code_7(self):
        target = self._make_repo_on_main()
        result = run_ops(["init-target", "--target", str(target)])
        self.assertEqual(result.returncode, 7)

    def test_init_target_on_main_devflow_not_created(self):
        target = self._make_repo_on_main()
        run_ops(["init-target", "--target", str(target)])
        self.assertFalse(
            (target / ".devflow").exists(),
            ".devflow/ must not be created on main branch",
        )

    def test_init_target_on_master_exit_code_7(self):
        target = self.tmpdir / "repo_on_master"
        target.mkdir()
        make_git_repo(target, branch="master")
        result = run_ops(["init-target", "--target", str(target)])
        self.assertEqual(result.returncode, 7)

    def test_init_target_error_mentions_launch(self):
        target = self._make_repo_on_main()
        result = run_ops(["init-target", "--target", str(target)])
        self.assertIn("launch", result.stderr.lower())


# ---------------------------------------------------------------------------
# Test 12: create-run rejected on protected branches
# ---------------------------------------------------------------------------

class CreateRunProtectedBranchTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, branch="main")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_run_rejects_main_exit_code_7(self):
        result = run_ops(["create-run", "--target", str(self.target)])
        self.assertEqual(result.returncode, 7)

    def test_create_run_on_main_no_run_state_created(self):
        devflow = self.target / ".devflow"
        devflow.mkdir()
        (devflow / "runs").mkdir()
        now = "2026-01-01T00:00:00Z"
        (devflow / "project.json").write_text(
            json.dumps({
                "schema_version": "1",
                "run_counter": 0,
                "current_run_id": None,
                "target_project_path": str(self.target),
                "framework_repo_path": str(REPO_ROOT),
                "initialized_at": now,
                "framework_version": "1.0.0",
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        run_ops(["create-run", "--target", str(self.target)])
        runs = list((devflow / "runs").glob("*.json"))
        self.assertEqual(len(runs), 0, "No run state should be created when on main branch")


# ---------------------------------------------------------------------------
# Test 13–15: launch --dry-run
# ---------------------------------------------------------------------------

class LaunchDryRunTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, branch="main")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _dry_run(self):
        return run_ops(["launch", "--target", str(self.target), "--dry-run"])

    def test_dry_run_returns_zero(self):
        result = self._dry_run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_creates_no_devflow_in_target(self):
        self._dry_run()
        self.assertFalse(
            (self.target / ".devflow").exists(),
            "dry-run must not create .devflow/ in main checkout",
        )

    def test_dry_run_creates_no_branch(self):
        self._dry_run()
        result = subprocess.run(
            ["git", "branch", "--list", "devflow/run-*"],
            cwd=str(self.target),
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "", "dry-run must not create any branches")

    def test_dry_run_creates_no_worktree_directory(self):
        self._dry_run()
        managed_root = self.target.parent / ".devflow-worktrees" / self.target.name
        self.assertFalse(managed_root.exists(), "dry-run must not create worktree directory")

    def test_dry_run_shows_run_id(self):
        result = self._dry_run()
        self.assertIn("RUN-001", result.stdout)

    def test_dry_run_shows_correct_branch(self):
        result = self._dry_run()
        self.assertIn("devflow/run-run-001", result.stdout)

    def test_dry_run_shows_managed_worktree_path(self):
        result = self._dry_run()
        expected = str(self.target.parent / ".devflow-worktrees" / self.target.name)
        self.assertIn(expected, result.stdout)

    def test_dry_run_shows_plugin_dir(self):
        result = self._dry_run()
        self.assertIn("devflow-plugin", result.stdout)

    def test_dry_run_shows_plugin_dir_flag(self):
        result = self._dry_run()
        self.assertIn("--plugin-dir", result.stdout)

    def test_dry_run_claude_cmd_has_no_print_flag(self):
        result = self._dry_run()
        lines = [l for l in result.stdout.splitlines() if "claude cmd" in l]
        for line in lines:
            self.assertNotIn("--print", line, "claude command must not use --print")
            self.assertNotIn(" -p ", line, "claude command must not use -p")

    def test_dry_run_shows_git_worktree_add_command(self):
        result = self._dry_run()
        self.assertIn("git worktree add", result.stdout)
        self.assertIn("devflow/run-run-001", result.stdout)

    def test_dry_run_second_launch_uses_run_002_when_001_exists(self):
        # Create run-001 branch to simulate existing run
        subprocess.run(
            ["git", "branch", "devflow/run-run-001"],
            cwd=str(self.target),
            capture_output=True,
        )
        result = self._dry_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUN-002", result.stdout)
        self.assertIn("devflow/run-run-002", result.stdout)


# ---------------------------------------------------------------------------
# Test 16–17: launch real worktree creation
# ---------------------------------------------------------------------------

def _make_fake_claude(tmpdir: Path, report_file: Path) -> Path:
    """Create a fake claude binary that records its CWD and args."""
    fake_claude = tmpdir / "fake_claude"
    fake_claude.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, json\n"
        "data = {\"cwd\": os.getcwd(), \"args\": sys.argv[1:]}\n"
        "report_path = os.environ.get(\"DEVFLOW_TEST_REPORT\")\n"
        "if report_path:\n"
        "    with open(report_path, \"w\") as f:\n"
        "        json.dump(data, f)\n",
        encoding="utf-8",
    )
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake_claude


class LaunchRealWorktreeTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, branch="main")
        self.report_file = self.tmpdir / "claude_report.json"
        self.fake_claude = _make_fake_claude(self.tmpdir, self.report_file)

    def tearDown(self):
        _remove_worktrees_and_cleanup(self.target, self.tmpdir)

    def _launch(self, extra_args=None):
        return run_ops(
            ["launch", "--target", str(self.target)] + (extra_args or []),
            env={
                "DEVFLOW_CLAUDE_BINARY": str(self.fake_claude),
                "DEVFLOW_TEST_REPORT": str(self.report_file),
            },
        )

    def _managed_root(self) -> Path:
        return self.target.parent / ".devflow-worktrees" / self.target.name

    def _worktree_path(self, run_num: int = 1) -> Path:
        return self._managed_root() / f"run-{run_num:03d}"

    def test_launch_creates_run_worktree(self):
        self._launch()
        self.assertTrue(
            self._worktree_path().exists(),
            "Launch should create the managed run worktree directory",
        )

    def test_launch_creates_run_branch(self):
        self._launch()
        result = subprocess.run(
            ["git", "branch", "--list", "devflow/run-run-001"],
            cwd=str(self.target),
            capture_output=True, text=True,
        )
        self.assertIn("devflow/run-run-001", result.stdout)

    def test_launch_devflow_written_in_worktree_not_main_checkout(self):
        self._launch()
        self.assertFalse(
            (self.target / ".devflow").exists(),
            "Main checkout must NOT have .devflow/ after launch",
        )
        self.assertTrue(
            (self._worktree_path() / ".devflow").exists(),
            "Run worktree must have .devflow/",
        )

    def test_launch_supervisor_cwd_is_run_worktree(self):
        self._launch()
        if not self.report_file.exists():
            self.skipTest("Fake claude did not write report (execv may have failed)")
        data = json.loads(self.report_file.read_text())
        # Resolve both paths to handle macOS /tmp → /private/tmp symlink
        actual_cwd = Path(data["cwd"]).resolve()
        expected_cwd = self._worktree_path().resolve()
        self.assertEqual(
            actual_cwd,
            expected_cwd,
            "Claude supervisor must start with CWD = run worktree",
        )

    def test_launch_claude_receives_plugin_dir(self):
        self._launch()
        if not self.report_file.exists():
            self.skipTest("Fake claude did not write report")
        data = json.loads(self.report_file.read_text())
        self.assertIn("--plugin-dir", data["args"], "Claude must receive --plugin-dir argument")

    def test_launch_claude_not_called_with_print_flag(self):
        self._launch()
        if not self.report_file.exists():
            self.skipTest("Fake claude did not write report")
        data = json.loads(self.report_file.read_text())
        self.assertNotIn("--print", data["args"], "Claude must not receive --print flag")
        self.assertNotIn("-p", data["args"], "Claude must not receive -p flag")

    def test_launch_collision_on_existing_worktree_path(self):
        """If the computed worktree path already exists, launch must exit 12."""
        worktree = self._worktree_path()
        worktree.mkdir(parents=True)
        result = self._launch()
        self.assertEqual(result.returncode, 12)
        self.assertIn("Hata", result.stderr)

    def test_launch_sequential_runs_get_different_ids(self):
        """Two sequential launches get different run IDs (no collision)."""
        result1 = self._launch()
        self.assertEqual(result1.returncode, 0, result1.stderr)

        # Remove the fake report so we can detect the second launch
        if self.report_file.exists():
            self.report_file.unlink()

        # After run-001 branch exists, next launch should use run-002
        result2 = self._launch()
        self.assertEqual(result2.returncode, 0, result2.stderr)

        branches = subprocess.run(
            ["git", "branch", "--list", "devflow/run-run-*"],
            cwd=str(self.target), capture_output=True, text=True,
        ).stdout
        self.assertIn("run-001", branches)
        self.assertIn("run-002", branches)

    def test_launch_dirty_working_tree_rejected(self):
        """Launch must reject if main checkout has uncommitted changes."""
        (self.target / "dirty_file.txt").write_text("dirty\n", encoding="utf-8")
        result = self._launch()
        self.assertEqual(result.returncode, 11)
        self.assertIn("Hata", result.stderr)


# ---------------------------------------------------------------------------
# Test 18: plugin copy devflow_operations.py gives framework runner error
# ---------------------------------------------------------------------------

class PluginCopyLaunchTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "target_project"
        self.target.mkdir()
        make_git_repo(self.target, branch="main")

        plugin_output = self.tmpdir / "plugin_output"
        build_result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), "--output-dir", str(plugin_output)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.build_ok = build_result.returncode == 0
        self.plugin_ops = plugin_output / "devflow-plugin" / "scripts" / "devflow_operations.py"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_plugin_ops(self, args: list) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.plugin_ops)] + args,
            capture_output=True, text=True,
        )

    def test_plugin_copy_launch_exit_code_5(self):
        if not self.build_ok or not self.plugin_ops.exists():
            self.skipTest("Plugin build failed or script not found")
        result = self._run_plugin_ops(["launch", "--target", str(self.target)])
        self.assertEqual(result.returncode, 5, result.stderr)

    def test_plugin_copy_launch_error_mentions_framework(self):
        if not self.build_ok or not self.plugin_ops.exists():
            self.skipTest("Plugin build failed or script not found")
        result = self._run_plugin_ops(["launch", "--target", str(self.target)])
        self.assertIn("framework", result.stderr.lower())

    def test_plugin_copy_launch_error_shows_runner_hint(self):
        if not self.build_ok or not self.plugin_ops.exists():
            self.skipTest("Plugin build failed or script not found")
        result = self._run_plugin_ops(["launch", "--target", str(self.target)])
        # Should tell user to use framework-side script
        stderr_lower = result.stderr.lower()
        self.assertTrue(
            "devflow_operations.py" in stderr_lower or "runner" in stderr_lower,
            f"Error should mention devflow_operations.py or runner: {result.stderr}",
        )

    def test_plugin_copy_status_still_works(self):
        """status and other non-launch commands work fine from plugin copy."""
        if not self.build_ok or not self.plugin_ops.exists():
            self.skipTest("Plugin build failed or script not found")
        result = self._run_plugin_ops(["status", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plugin_copy_dry_run_works(self):
        """launch --dry-run from plugin copy should work (plan only, no build needed)."""
        if not self.build_ok or not self.plugin_ops.exists():
            self.skipTest("Plugin build failed or script not found")
        result = self._run_plugin_ops(["launch", "--target", str(self.target), "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Test 19: prepare-delivery honesty (no real git mutations)
# ---------------------------------------------------------------------------

def _setup_devflow_with_all_gates_passed(target: Path) -> None:
    """Write a .devflow/ with all gates passed (except human_approval)."""
    devflow = target / ".devflow"
    devflow.mkdir(exist_ok=True)
    (devflow / "runs").mkdir(exist_ok=True)
    now = "2026-06-26T00:00:00Z"
    (devflow / "project.json").write_text(
        json.dumps({
            "schema_version": "1",
            "run_counter": 1,
            "current_run_id": "RUN-001",
            "target_project_path": str(target),
            "framework_repo_path": str(REPO_ROOT),
            "initialized_at": now,
            "framework_version": "1.0.0",
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    (devflow / "runs" / "RUN-001.json").write_text(
        json.dumps({
            "schema_version": "1",
            "run_id": "RUN-001",
            "created_at": now,
            "status": "created",
            "branch_name": "devflow/run-run-001",
            "objective": "test",
            "artifacts": [],
            "tasks": [],
            "approval_gates": {
                "contract_approved": True,
                "tests_passing": True,
                "security_review_complete": True,
                "qa_sign_off": True,
                "human_approval": False,
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )


class PrepareDeliveryHonestyTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.target = self.tmpdir / "myproject"
        self.target.mkdir()
        make_git_repo(self.target, branch="main", feature_branch="devflow/run-run-001")
        _setup_devflow_with_all_gates_passed(self.target)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _git_log(self) -> str:
        return subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(self.target), capture_output=True, text=True,
        ).stdout.strip()

    def test_prepare_delivery_makes_no_new_commit(self):
        before = self._git_log()
        run_ops(["prepare-delivery", "--target", str(self.target)])
        after = self._git_log()
        self.assertEqual(before, after, "prepare-delivery must not commit anything")

    def test_prepare_delivery_confirm_makes_no_new_commit(self):
        before = self._git_log()
        run_ops(["prepare-delivery", "--target", str(self.target), "--confirm-delivery"])
        after = self._git_log()
        self.assertEqual(before, after, "--confirm-delivery must not commit anything")

    def test_prepare_delivery_output_does_not_claim_git_push(self):
        result = run_ops(["prepare-delivery", "--target", str(self.target)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("git push", result.stdout)
        self.assertNotIn("git commit", result.stdout)

    def test_prepare_delivery_confirm_output_says_validation_only(self):
        result = run_ops(["prepare-delivery", "--target", str(self.target), "--confirm-delivery"])
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout.lower()
        self.assertTrue(
            "doğrulama" in output or "validation" in output or "gerçek" in output,
            "Output should state this is approval gate validation, not real git ops",
        )

    def test_prepare_delivery_confirm_no_real_git_push_in_output(self):
        result = run_ops(["prepare-delivery", "--target", str(self.target), "--confirm-delivery"])
        self.assertNotIn("git push", result.stdout)
        self.assertNotIn("git commit", result.stdout)

    def test_prepare_delivery_confirm_gates_failed_exit_9(self):
        """Fail all gates, confirm-delivery should exit 9."""
        devflow = self.target / ".devflow"
        run_data = json.loads((devflow / "runs" / "RUN-001.json").read_text())
        for k in run_data["approval_gates"]:
            run_data["approval_gates"][k] = False
        (devflow / "runs" / "RUN-001.json").write_text(
            json.dumps(run_data, indent=2) + "\n", encoding="utf-8"
        )
        result = run_ops(["prepare-delivery", "--target", str(self.target), "--confirm-delivery"])
        self.assertEqual(result.returncode, 9)


if __name__ == "__main__":
    unittest.main()
