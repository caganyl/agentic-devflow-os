"""
Parity and self-protection for the two DevFlow target guards.

scripts/devflow_target_guard.py (Claude plugin) and scripts/devflow_guard_core.py
(Codex adapter) used to carry separate rule sets that disagreed: e.g.
`sudo rm -rf build` was denied by one and allowed by the other, `cd $HOME` the
reverse, and neither protected .git/config, .git/hooks/, the guard scripts or
.devflow/delegation-events/. The Claude plugin ships the target guard without
the core module, so the shared policy is a verbatim copy between markers; these
tests keep the copies identical and run one decision table through both.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
CLAUDE_GUARD = SCRIPTS / "devflow_target_guard.py"
CORE = SCRIPTS / "devflow_guard_core.py"
CODEX_ADAPTER = SCRIPTS / "devflow_codex_target_guard.py"
PLUGIN_HOOKS = REPO_ROOT / "hooks" / "hooks.json"

_BLOCK = re.compile(
    r"# --- BEGIN SHARED GUARD POLICY -+\n.*?# --- END SHARED GUARD POLICY -+\n", re.S
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DANGEROUS_COMMANDS = (
    "sudo rm -rf build",
    "sudo ls",
    "find . -name '*.tmp' | xargs rm -rf",
    "xargs rm -rf < list.txt",
    "find . -exec rm -rf {} +",
    "bash -c 'rm -rf build'",
    "sh -c \"git merge feature\"",
    "echo \"$(rm -rf build)\"",
    "echo `rm -rf build`",
    "eval rm -rf build",
    "env FOO=1 rm -rf build",
    "/bin/rm -rf build",
    "git --no-pager merge feature",
    "/usr/bin/git merge feature",
    "git -c core.editor=true merge feature",
    "git --git-dir=.git --work-tree=. merge feature",
    "git push origin +main",
    "git push origin :main",
    "git push --delete origin feature",
    "git push -d origin feature",
    "git push --force origin main",
    "git push --mirror origin",
    "git reset --keep HEAD~1",
    "git reset --hard",
    "git -C . reset --hard",
    "git checkout -f main",
    "git checkout .",
    "git checkout -- .",
    "git switch --discard-changes main",
    "git restore .",
    "git branch -D feature",
    "git clean -fdx",
    "rm -r -f directory",
)

SAFE_COMMANDS = (
    "git status",
    "git log --format='%h -> %s' -5",
    "git push origin feature",
    "git push -u origin feature",
    "git checkout -b feature/x",
    "git checkout main",
    "git merge-base main HEAD",
    "git -C /some/repo merge-base main HEAD",
    "git branch --list devflow/run-*",
    "git reset HEAD~1 -- src/api.py",
    "git restore src/app.py",
    "git clean -n",
    "echo 'rm -rf example'",
    "rm -f one-file",
    "rm -r one-directory",
    "find . -name '*.py' -exec grep -n foo {} +",
    "ls | xargs grep foo",
    "python3 -m unittest discover -s tests -p 'test_*.py'",
    "npm test 2>&1 | tail -50",
)

# With a managed worktree these must be refused as shell navigation escapes.
NAVIGATION_ESCAPES = (
    "(cd /etc && ls)",
    "cd $HOME",
    "cd ~",
    "cd ~/other",
    "cd",
    "cd ..",
    "pushd /etc",
    "{ cd /etc; }",
    "FOO=1 cd /etc",
    "bash -c 'cd /etc && ls'",
    "echo $(cd /etc && pwd)",
    "git --git-dir=/etc/.git status",
    "git -C /etc status",
)

NAVIGATION_INSIDE = (
    "cd src && ls",
    'cd "$DEVFLOW_RUN_WORKTREE"',
    "git status --short",
    "ls -la",
)

PROTECTED_PATHS = (
    ".git/config",
    ".git/hooks/pre-commit",
    ".git/worktrees/run/config",
    ".codex/hooks.json",
    ".codex/config.toml",
    "hooks/hooks.json",
    "scripts/devflow_target_guard.py",
    "scripts/devflow_guard_core.py",
    "scripts/devflow_codex_target_guard.py",
    ".devflow/cache/state-signing.key",
    ".devflow/project.json",
    ".devflow/delegation-events/evt-1.json",
    ".devflow/runs/RUN-001.json",
    ".devflow/reports/RUN-001.md",
    ".env",
    ".ENV.production",
    "config/secrets/a.txt",
    ".claude/settings.json",
    ".claude/hooks/x.sh",
)

SAFE_PATHS = (
    "src/app.py",
    "docs/handoffs/RUN-001.md",
    ".devflow/context/RUN-001-context-pack.md",
    "scripts/other_tool.py",
    ".gitignore",
)


class SharedBlockIdenticalTest(unittest.TestCase):
    def test_shared_policy_block_is_byte_identical(self):
        claude = _BLOCK.search(CLAUDE_GUARD.read_text(encoding="utf-8"))
        core = _BLOCK.search(CORE.read_text(encoding="utf-8"))
        self.assertIsNotNone(claude, "shared block markers missing in devflow_target_guard.py")
        self.assertIsNotNone(core, "shared block markers missing in devflow_guard_core.py")
        self.assertEqual(claude.group(0), core.group(0))


class DecisionParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = _load(CORE, "parity_core")
        cls.claude = _load(CLAUDE_GUARD, "parity_claude_guard")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.worktree = Path(cls.tmp.name).resolve()
        (cls.worktree / "src").mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _both_bash(self, command):
        return (self.core.dangerous_command_reason(command) is not None,
                self.claude._check_bash(command) is not None)

    def test_dangerous_commands_denied_by_both(self):
        for command in DANGEROUS_COMMANDS:
            with self.subTest(command=command):
                self.assertEqual(self._both_bash(command), (True, True))

    def test_safe_commands_allowed_by_both(self):
        for command in SAFE_COMMANDS:
            with self.subTest(command=command):
                self.assertEqual(self._both_bash(command), (False, False))

    def test_navigation_parity(self):
        for command in NAVIGATION_ESCAPES:
            with self.subTest(command=command):
                core = self.core.shell_navigation_reason(command, self.worktree) is not None
                claude = self.claude._check_bash_boundary(command, self.worktree) is not None
                self.assertEqual((core, claude), (True, True))
        for command in NAVIGATION_INSIDE:
            with self.subTest(command=command):
                core = self.core.shell_navigation_reason(command, self.worktree) is not None
                claude = self.claude._check_bash_boundary(command, self.worktree) is not None
                self.assertEqual((core, claude), (False, False))

    def test_path_parity(self):
        for path in PROTECTED_PATHS:
            with self.subTest(path=path):
                self.assertTrue(self.core.is_protected_or_sensitive_path(path))
                self.assertIsNotNone(self.claude._check_path(path))
                self.assertIsNotNone(self.core.validate_target_path(path, self.worktree))
                self.assertIsNotNone(self.claude._check_path_boundary(path, self.worktree))
        for path in SAFE_PATHS:
            with self.subTest(path=path):
                self.assertFalse(self.core.is_protected_or_sensitive_path(path))
                self.assertIsNone(self.claude._check_path(path))
                self.assertIsNone(self.core.validate_target_path(path, self.worktree))
                self.assertIsNone(self.claude._check_path_boundary(path, self.worktree))


class EndToEndParityTest(unittest.TestCase):
    """Run both guard processes on the same events inside a managed worktree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.worktree = Path(self.tmp.name).resolve()
        (self.worktree / "src").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self):
        env = os.environ.copy()
        env["DEVFLOW_RUN_WORKTREE"] = str(self.worktree)
        env.pop("DEVFLOW_RUN_BRANCH", None)
        return env

    def _claude_denies(self, payload):
        r = subprocess.run([sys.executable, str(CLAUDE_GUARD)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self._env())
        self.assertIn(r.returncode, (0, 2), r.stderr)
        return r.returncode == 2

    def _codex_denies(self, payload):
        r = subprocess.run([sys.executable, str(CODEX_ADAPTER)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self._env())
        if r.returncode == 2:
            return True
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout.strip():
            return False
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def _assert_same(self, payload, expected_deny):
        self.assertEqual(
            (self._claude_denies(payload), self._codex_denies(payload)),
            (expected_deny, expected_deny), payload)

    def test_commands(self):
        for command in DANGEROUS_COMMANDS[:8] + NAVIGATION_ESCAPES[:4]:
            with self.subTest(command=command):
                self._assert_same({"tool_name": "Bash", "tool_input": {"command": command}}, True)
        for command in SAFE_COMMANDS[:6] + NAVIGATION_INSIDE:
            with self.subTest(command=command):
                self._assert_same({"tool_name": "Bash", "tool_input": {"command": command}}, False)

    def test_paths(self):
        for path in PROTECTED_PATHS:
            with self.subTest(path=path):
                self._assert_same({"tool_name": "Write",
                                   "tool_input": {"file_path": path, "content": "x"}}, True)
        for path in SAFE_PATHS:
            with self.subTest(path=path):
                self._assert_same({"tool_name": "Write",
                                   "tool_input": {"file_path": path, "content": "x"}}, False)


class ClaudeGuardFailClosedTest(unittest.TestCase):
    def _run(self, payload, worktree):
        env = os.environ.copy()
        env["DEVFLOW_RUN_WORKTREE"] = str(worktree)
        return subprocess.run([sys.executable, str(CLAUDE_GUARD)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    def test_unresolvable_worktree_denies_write(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "src/a.py", "content": "x"}}
        r = self._run(payload, "/nonexistent/devflow-worktree-xyz")
        self.assertEqual(r.returncode, 2)

    def test_uninterpretable_path_denies_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for path in ("src/a\x00.py", "src/a\n.py", ""):
                with self.subTest(path=path):
                    payload = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
                    self.assertEqual(self._run(payload, root).returncode, 2)

    def test_notebook_edit_uses_notebook_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            denied = self._run({"tool_name": "NotebookEdit",
                                "tool_input": {"notebook_path": "secrets/n.ipynb"}}, root)
            self.assertEqual(denied.returncode, 2)
            outside = self._run({"tool_name": "NotebookEdit",
                                 "tool_input": {"notebook_path": "/tmp/elsewhere/n.ipynb"}}, root)
            self.assertEqual(outside.returncode, 2)
            allowed = self._run({"tool_name": "NotebookEdit",
                                 "tool_input": {"notebook_path": str(root / "n.ipynb")}}, root)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            missing = self._run({"tool_name": "NotebookEdit", "tool_input": {}}, root)
            self.assertEqual(missing.returncode, 2)


class PluginHookRegistrationTest(unittest.TestCase):
    def setUp(self):
        self.hooks = json.loads(PLUGIN_HOOKS.read_text(encoding="utf-8"))["hooks"]

    def test_every_hook_has_a_timeout(self):
        for event, groups in self.hooks.items():
            for group in groups:
                for handler in group["hooks"]:
                    with self.subTest(event=event, command=handler["command"]):
                        self.assertIsInstance(handler.get("timeout"), int)
                        self.assertGreater(handler["timeout"], 0)

    def test_notebook_edit_is_guarded(self):
        matchers = [g.get("matcher", "") for g in self.hooks["PreToolUse"]]
        self.assertTrue(any(re.fullmatch(m, "NotebookEdit") for m in matchers), matchers)
        for tool in ("Bash", "Write", "Edit", "NotebookEdit"):
            group = next(g for g in self.hooks["PreToolUse"] if re.fullmatch(g["matcher"], tool))
            commands = json.dumps(group["hooks"])
            for script in ("devflow_target_guard.py", "protect-main.sh",
                           "protect-sensitive-paths.sh", "enforce-role-boundaries.sh"):
                self.assertIn(script, commands, f"{tool} misses {script}")


if __name__ == "__main__":
    unittest.main()
