"""bin/install and the claude-devflow entry point as a user runs them:
installed into a bin dir on PATH as symlinks, invoked from a project folder."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL = REPO_ROOT / "bin" / "install"
BEGIN = "# >>> agentic-devflow-os >>>"


class CliInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin_dir = self.home / ".local" / "bin"
        self.tools = self.base / "tools"
        self.tools.mkdir()
        # A stand-in `claude` that records how it was called.
        fake = self.tools / "claude"
        fake.write_text('#!/bin/sh\necho "FAKE-CLAUDE $*"\n', encoding="utf-8")
        fake.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, path_extra=()):
        # Only the directories of the tools the scripts need, so a real
        # `claude` on the developer's PATH cannot leak into the test.
        dirs = []
        for tool in ("git", "python3", "jq", "awk", "sed", "readlink"):
            found = shutil.which(tool)
            if found and os.path.dirname(found) not in dirs:
                dirs.append(os.path.dirname(found))
        system_path = os.pathsep.join(dirs + ["/usr/bin", "/bin"])
        return {
            "HOME": str(self.home),
            "SHELL": "/bin/zsh",
            "PATH": os.pathsep.join([*map(str, path_extra), str(self.tools), system_path]),
            "DEVFLOW_BIN_DIR": str(self.bin_dir),
            "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
        }

    def run_install(self, *args, env=None):
        return subprocess.run(["sh", str(INSTALL), *args], capture_output=True, text=True,
                              env=env or self.env())

    def zshrc(self):
        path = self.home / ".zshrc"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_install_links_commands_and_adds_path_block_once(self):
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stderr)
        for cmd in ("claude-devflow", "devflow-manifest"):
            link = self.bin_dir / cmd
            self.assertTrue(link.is_symlink(), cmd)
            self.assertEqual(Path(os.readlink(link)), REPO_ROOT / "bin" / cmd)
        self.assertEqual(self.zshrc().count(BEGIN), 1)
        self.assertIn(f'export PATH="{self.bin_dir}:$PATH"', self.zshrc())

    def test_no_rc_change_when_bin_dir_already_on_path(self):
        result = self.run_install(env=self.env(path_extra=[self.bin_dir]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(BEGIN, self.zshrc())

    def test_no_path_flag_leaves_rc_alone(self):
        result = self.run_install("--no-path")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(BEGIN, self.zshrc())

    def test_warns_about_shadowing_shell_function(self):
        (self.home / ".zshrc").write_text(
            "claude-devflow() {\n  echo old\n}\n", encoding="utf-8")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("eski bir tanım", result.stdout)
        self.assertIn(".zshrc:1:", result.stdout)
        # The user's own lines are reported, never edited.
        self.assertTrue(self.zshrc().startswith("claude-devflow() {"))

    def test_uninstall_removes_links_and_block(self):
        self.run_install()
        result = self.run_install("--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.bin_dir / "claude-devflow").exists())
        self.assertNotIn(BEGIN, self.zshrc())

    def test_refuses_to_overwrite_a_real_file(self):
        self.bin_dir.mkdir(parents=True)
        (self.bin_dir / "claude-devflow").write_text("mine\n", encoding="utf-8")
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.bin_dir / "claude-devflow").read_text(), "mine\n")

    def test_symlinked_command_finds_framework_home(self):
        self.run_install()
        result = subprocess.run([str(self.bin_dir / "claude-devflow"), "--help"],
                                capture_output=True, text=True,
                                env=self.env(path_extra=[self.bin_dir]), cwd=self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"DEVFLOW_HOME: {REPO_ROOT}", result.stdout)

    @unittest.skipUnless(shutil.which("jq") and shutil.which("git"), "needs jq and git")
    def test_claude_devflow_bootstraps_project_and_starts_claude(self):
        self.run_install()
        project = self.base / "my-project"
        project.mkdir()
        env = self.env(path_extra=[self.bin_dir])
        env["DEVFLOW_PONYTAIL"] = "0"
        result = subprocess.run(["claude-devflow", "--model", "x"], capture_output=True,
                                text=True, env=env, cwd=project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plugin_dir = REPO_ROOT / "dist" / "devflow-plugin"
        self.assertIn(f"FAKE-CLAUDE --plugin-dir {plugin_dir} --model x", result.stdout)
        self.assertTrue((project / ".devflow").is_dir())
        self.assertTrue((plugin_dir / ".claude-plugin" / "plugin.json").is_file())

    @unittest.skipUnless(shutil.which("jq") and shutil.which("git"), "needs jq and git")
    def test_claude_devflow_loads_ponytail_when_node_exists(self):
        self.run_install()
        node = self.tools / "node"
        node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        node.chmod(0o755)
        fake = self.tools / "claude"
        fake.write_text('#!/bin/sh\necho "FAKE-CLAUDE $*"\n'
                        'echo "MODE=$PONYTAIL_DEFAULT_MODE MATCH=$PONYTAIL_SUBAGENT_MATCHER"\n',
                        encoding="utf-8")
        project = self.base / "my-project"
        project.mkdir()
        env = self.env(path_extra=[self.bin_dir])
        env["PONYTAIL_DEFAULT_MODE"] = "ultra"
        result = subprocess.run(["claude-devflow"], capture_output=True, text=True,
                                env=env, cwd=project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plugin_dir = REPO_ROOT / "dist" / "devflow-plugin"
        ponytail = REPO_ROOT / ".claude" / "vendor" / "ponytail"
        self.assertIn(f"FAKE-CLAUDE --plugin-dir {plugin_dir} --plugin-dir {ponytail}", result.stdout)
        self.assertIn("MODE=full MATCH=backend-engineer|", result.stdout)

    def test_map_command_reaches_code_map_wrapper(self):
        self.run_install()
        project = self.base / "my-project"
        project.mkdir()
        env = self.env(path_extra=[self.bin_dir])
        result = subprocess.run(["claude-devflow", "map", "status"], capture_output=True,
                                text=True, env=env, cwd=project)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Kod haritası: yok", result.stdout)
        env["DEVFLOW_GRAPHIFY_BIN"] = str(self.base / "missing-graphify")
        result = subprocess.run(["claude-devflow", "map"], capture_output=True,
                                text=True, env=env, cwd=project)
        self.assertEqual(result.returncode, 3)
        self.assertIn("graphifyy==0.9.93", result.stderr)

    def test_doctor_reports_ponytail(self):
        self.run_install()
        node = self.tools / "node"
        node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        node.chmod(0o755)
        env = self.env(path_extra=[self.bin_dir])
        result = subprocess.run([str(self.bin_dir / "claude-devflow"), "doctor"],
                                capture_output=True, text=True, env=env)
        self.assertIn("[ok]     ponytail", result.stdout)
        env["DEVFLOW_PONYTAIL"] = "0"
        result = subprocess.run([str(self.bin_dir / "claude-devflow"), "doctor"],
                                capture_output=True, text=True, env=env)
        self.assertIn("[kapalı] ponytail", result.stdout)

    def test_doctor_reports_missing_claude(self):
        self.run_install()
        (self.tools / "claude").unlink()
        result = subprocess.run([str(self.bin_dir / "claude-devflow"), "doctor"],
                                capture_output=True, text=True,
                                env=self.env(path_extra=[self.bin_dir]))
        self.assertEqual(result.returncode, 1)
        self.assertIn("[eksik]  claude", result.stdout)


if __name__ == "__main__":
    unittest.main()
