"""scripts/claude-devflow.ps1: the Windows entry point must offer the same
subcommands and Ponytail loading as bin/claude-devflow.

Behavior tests need PowerShell (`pwsh`, preinstalled on GitHub's Ubuntu and
macOS runners); the static checks run everywhere."""

import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PS1 = REPO_ROOT / "scripts" / "claude-devflow.ps1"
PONYTAIL = REPO_ROOT / ".claude" / "vendor" / "ponytail"
PLUGIN = REPO_ROOT / "dist" / "devflow-plugin"
PWSH = shutil.which("pwsh")


def ops_roles():
    spec = importlib.util.spec_from_file_location("devflow_ops_win", REPO_ROOT / "scripts" / "devflow_operations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PONYTAIL_ROLES


class StaticTest(unittest.TestCase):

    def test_ascii_only_for_windows_powershell_51(self):
        # PowerShell 5.1 reads BOM-less files as ANSI; non-ASCII text would be garbled.
        PS1.read_bytes().decode("ascii")

    def test_same_ponytail_roles_as_other_launchers(self):
        m = re.search(r"^\$PonytailRoles = '([^']+)'", PS1.read_text(encoding="ascii"), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), ops_roles())

    def test_same_subcommands_as_shell_launcher(self):
        text = PS1.read_text(encoding="ascii")
        for sub in ("doctor", "office", "map", "launch"):
            with self.subTest(sub=sub):
                self.assertIn(f"'{sub}'", text)


@unittest.skipUnless(PWSH and shutil.which("git") and shutil.which("jq"), "needs pwsh, git and jq")
class BehaviorTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.tools = base / "tools"
        self.tools.mkdir()
        claude = self.tools / "claude"
        claude.write_text('#!/bin/sh\necho "FAKE-CLAUDE $*"\n'
                          'echo "MODE=$PONYTAIL_DEFAULT_MODE MATCH=$PONYTAIL_SUBAGENT_MATCHER"\n')
        claude.chmod(0o755)
        self.project = base / "proj"
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_ps(self, *args, node=True, **extra):
        node_bin = self.tools / "node"
        if node:
            node_bin.write_text("#!/bin/sh\nexit 0\n")
            node_bin.chmod(0o755)
        elif node_bin.exists():
            node_bin.unlink()
        env = dict(os.environ, PATH=os.pathsep.join([str(self.tools), os.environ.get("PATH", "")]),
                   GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com")
        for key in ("DEVFLOW_HOME", "DEVFLOW_PONYTAIL", "PONYTAIL_DEFAULT_MODE", "PONYTAIL_SUBAGENT_MATCHER"):
            env.pop(key, None)
        if not node:
            # Hide any real node on the host.
            env["PATH"] = os.pathsep.join([str(self.tools)] + [d for d in env["PATH"].split(os.pathsep)[1:]
                                                                 if not (Path(d) / "node").exists()])
        env.update(extra)
        return subprocess.run([PWSH, "-NoProfile", "-File", str(PS1), *args], cwd=str(self.project),
                              capture_output=True, text=True, env=env, timeout=180)

    def test_default_starts_claude_with_devflow_and_ponytail(self):
        result = self.run_ps("--model", "x", PONYTAIL_DEFAULT_MODE="ultra")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"FAKE-CLAUDE --plugin-dir {PLUGIN} --plugin-dir {PONYTAIL} --model x", result.stdout)
        self.assertIn(f"MODE=full MATCH={ops_roles()}", result.stdout)
        self.assertTrue((self.project / ".devflow").is_dir())

    def test_ponytail_off_or_without_node(self):
        for kwargs in ({"DEVFLOW_PONYTAIL": "0"}, {"node": False}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                result = self.run_ps(**kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"FAKE-CLAUDE --plugin-dir {PLUGIN}\n", result.stdout)

    def test_map_reaches_code_map_wrapper(self):
        result = self.run_ps("map", "status")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Kod haritas", result.stdout)
        self.assertNotIn("FAKE-CLAUDE", result.stdout)

    def test_doctor_lists_tools(self):
        result = self.run_ps("doctor")
        for label in ("git", "python", "claude", "ponytail", "graphify"):
            with self.subTest(label=label):
                self.assertIn(label, result.stdout)


if __name__ == "__main__":
    unittest.main()
